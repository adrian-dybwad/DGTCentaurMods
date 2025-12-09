/**
 * @file protocol.c
 * @brief Millennium protocol decoding for human-readable output
 *
 * Decodes Millennium ChessLink protocol messages for display on the
 * USB console. This provides insight into what commands the app sends
 * and what responses the board returns.
 */

#include "protocol.h"
#include "usb_console.h"

#include <zephyr/logging/log.h>
#include <stdio.h>
#include <string.h>
#include <ctype.h>

LOG_MODULE_REGISTER(protocol, LOG_LEVEL_INF);

/**
 * Decode and log a Millennium protocol message.
 *
 * The Millennium protocol uses ASCII characters with 7-bit parity:
 * - Each byte has parity in MSB (bit 7)
 * - Command format: [parity_bytes...] [crc]
 * - Commands: V (version), S (board state), L (LED), X (LED off), etc.
 * - Responses: v (version), s (board state 64 chars), r (ack)
 *
 * @param dir Traffic direction
 * @param data Raw data buffer
 * @param len Data length
 */
void protocol_decode_and_log(traffic_dir_t dir, const uint8_t *data, size_t len)
{
    if (len == 0) {
        return;
    }
    
    char msg[256];
    int pos = 0;
    
    /* Extract command byte (strip parity) */
    uint8_t cmd = data[0] & 0x7F;
    
    /* Check if this looks like a Millennium protocol message */
    if (!isprint(cmd) && cmd != '\r' && cmd != '\n') {
        /* Not ASCII - just show raw hex */
        pos = snprintf(msg, sizeof(msg), "RAW[%zu]: ", len);
        for (size_t i = 0; i < len && pos < (int)sizeof(msg) - 4; i++) {
            pos += snprintf(msg + pos, sizeof(msg) - pos, "%02x ", data[i]);
        }
        usb_console_log_decoded(dir, msg);
        return;
    }
    
    /* Decode based on command type */
    switch (cmd) {
    case 'V':
        snprintf(msg, sizeof(msg), "CMD: VERSION request");
        break;
    
    case 'v':
        /* Version response - payload is version string */
        if (len > 2) {
            char version[64];
            size_t vlen = 0;
            for (size_t i = 1; i < len - 1 && vlen < sizeof(version) - 1; i++) {
                version[vlen++] = data[i] & 0x7F;
            }
            version[vlen] = '\0';
            snprintf(msg, sizeof(msg), "RESP: VERSION = \"%s\"", version);
        } else {
            snprintf(msg, sizeof(msg), "RESP: VERSION (empty)");
        }
        break;
    
    case 'S':
        snprintf(msg, sizeof(msg), "CMD: BOARD STATE request");
        break;
    
    case 's':
        /* Board state response - 64 chars for squares */
        if (len >= 66) {  /* 's' + 64 squares + crc */
            pos = snprintf(msg, sizeof(msg), "RESP: BOARD STATE\n");
            
            /* Format as 8x8 board */
            for (int rank = 7; rank >= 0; rank--) {
                pos += snprintf(msg + pos, sizeof(msg) - pos, "    %d: ", rank + 1);
                for (int file = 0; file < 8; file++) {
                    int idx = rank * 8 + file + 1;  /* +1 for 's' prefix */
                    char sq = data[idx] & 0x7F;
                    pos += snprintf(msg + pos, sizeof(msg) - pos, "%c ", sq);
                }
                pos += snprintf(msg + pos, sizeof(msg) - pos, "\n");
            }
            pos += snprintf(msg + pos, sizeof(msg) - pos, "       a b c d e f g h");
        } else {
            snprintf(msg, sizeof(msg), "RESP: BOARD STATE (%zu bytes, expected 66)", len);
        }
        break;
    
    case 'L':
        /* LED command */
        if (len >= 3) {
            uint8_t square = data[1] & 0x7F;
            uint8_t state = data[2] & 0x7F;
            int file = (square % 9);
            int rank = (square / 9);
            snprintf(msg, sizeof(msg), "CMD: LED square=%d (%c%d) state=%c",
                     square, 
                     (file >= 1 && file <= 8) ? ('a' + file - 1) : '?',
                     rank,
                     state);
        } else {
            snprintf(msg, sizeof(msg), "CMD: LED (incomplete)");
        }
        break;
    
    case 'X':
        snprintf(msg, sizeof(msg), "CMD: ALL LEDs OFF");
        break;
    
    case 'R':
        snprintf(msg, sizeof(msg), "CMD: RESET");
        break;
    
    case 'r':
        snprintf(msg, sizeof(msg), "RESP: ACK");
        break;
    
    case 'B':
        snprintf(msg, sizeof(msg), "CMD: BEEP");
        break;
    
    case 'W':
        snprintf(msg, sizeof(msg), "CMD: SCAN ON (enable board scanning)");
        break;
    
    case 'I':
        snprintf(msg, sizeof(msg), "CMD: SCAN OFF (disable board scanning)");
        break;
    
    default:
        /* Unknown command - show ASCII and hex */
        if (isprint(cmd)) {
            pos = snprintf(msg, sizeof(msg), "CMD: '%c' (0x%02x) [", cmd, cmd);
        } else {
            pos = snprintf(msg, sizeof(msg), "CMD: 0x%02x [", cmd);
        }
        
        /* Show payload as ASCII where printable */
        for (size_t i = 0; i < len && pos < (int)sizeof(msg) - 4; i++) {
            char c = data[i] & 0x7F;
            if (isprint(c)) {
                pos += snprintf(msg + pos, sizeof(msg) - pos, "%c", c);
            } else {
                pos += snprintf(msg + pos, sizeof(msg) - pos, "\\x%02x", data[i]);
            }
        }
        pos += snprintf(msg + pos, sizeof(msg) - pos, "]");
        break;
    }
    
    usb_console_log_decoded(dir, msg);
}

/**
 * Validate Millennium protocol CRC.
 *
 * @param data Data buffer including CRC byte at end
 * @param len Total length including CRC
 * @return true if CRC is valid
 */
bool protocol_validate_crc(const uint8_t *data, size_t len)
{
    if (len < 2) {
        return false;
    }
    
    uint8_t crc = millennium_crc(data, len - 1);
    return (crc == data[len - 1]);
}

