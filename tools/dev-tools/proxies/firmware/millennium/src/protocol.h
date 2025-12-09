/**
 * @file protocol.h
 * @brief Millennium ChessLink protocol definitions
 *
 * Defines the BLE UUIDs, command types, and protocol structures for the
 * Millennium ChessLink board. Based on protocol analysis from the existing
 * DGTCentaurMods simulator implementation.
 */

#ifndef PROTOCOL_H
#define PROTOCOL_H

#include <zephyr/bluetooth/uuid.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "usb_console.h"

/*
 * Millennium ChessLink BLE Service and Characteristic UUIDs
 *
 * The service uses a custom 128-bit UUID with 5 characteristics:
 * - Config: READ/WRITE configuration
 * - Notify1: WRITE/NOTIFY
 * - TX: READ/WRITE/WRITE_NO_RESP/NOTIFY (main data from board)
 * - RX: WRITE/WRITE_NO_RESP (main data to board)
 * - Notify2: WRITE/NOTIFY
 */

/* Millennium Service UUID: 49535343-fe7d-4ae5-8fa9-9fafd205e455 */
#define MILLENNIUM_SERVICE_UUID \
    BT_UUID_128_ENCODE(0x49535343, 0xfe7d, 0x4ae5, 0x8fa9, 0x9fafd205e455)

/* Config Characteristic: 49535343-6daa-4d02-abf6-19569aca69fe */
#define MILLENNIUM_CONFIG_UUID \
    BT_UUID_128_ENCODE(0x49535343, 0x6daa, 0x4d02, 0xabf6, 0x19569aca69fe)

/* Notify1 Characteristic: 49535343-aca3-481c-91ec-d85e28a60318 */
#define MILLENNIUM_NOTIFY1_UUID \
    BT_UUID_128_ENCODE(0x49535343, 0xaca3, 0x481c, 0x91ec, 0xd85e28a60318)

/* TX Characteristic: 49535343-1e4d-4bd9-ba61-23c647249616 */
#define MILLENNIUM_TX_UUID \
    BT_UUID_128_ENCODE(0x49535343, 0x1e4d, 0x4bd9, 0xba61, 0x23c647249616)

/* RX Characteristic: 49535343-8841-43f4-a8d4-ecbe34729bb3 */
#define MILLENNIUM_RX_UUID \
    BT_UUID_128_ENCODE(0x49535343, 0x8841, 0x43f4, 0xa8d4, 0xecbe34729bb3)

/* Notify2 Characteristic: 49535343-026e-3a9b-954c-97daef17e26e */
#define MILLENNIUM_NOTIFY2_UUID \
    BT_UUID_128_ENCODE(0x49535343, 0x026e, 0x3a9b, 0x954c, 0x97daef17e26e)

/* Declare UUID structures */
#define BT_UUID_MILLENNIUM_SERVICE BT_UUID_DECLARE_128(MILLENNIUM_SERVICE_UUID)
#define BT_UUID_MILLENNIUM_CONFIG  BT_UUID_DECLARE_128(MILLENNIUM_CONFIG_UUID)
#define BT_UUID_MILLENNIUM_NOTIFY1 BT_UUID_DECLARE_128(MILLENNIUM_NOTIFY1_UUID)
#define BT_UUID_MILLENNIUM_TX      BT_UUID_DECLARE_128(MILLENNIUM_TX_UUID)
#define BT_UUID_MILLENNIUM_RX      BT_UUID_DECLARE_128(MILLENNIUM_RX_UUID)
#define BT_UUID_MILLENNIUM_NOTIFY2 BT_UUID_DECLARE_128(MILLENNIUM_NOTIFY2_UUID)

/*
 * Millennium Protocol Commands
 *
 * Commands use ASCII characters with 7-bit parity and XOR CRC.
 * Format: <parity_byte> <command_char> [payload...] <crc>
 */

/* Command types (ASCII characters) */
#define CMD_VERSION     'V'  /* Request version info */
#define CMD_BOARD_STATE 'S'  /* Request board state */
#define CMD_LED_SET     'L'  /* Set LEDs */
#define CMD_LED_OFF     'X'  /* All LEDs off */
#define CMD_RESET       'R'  /* Reset board */
#define CMD_BEEP        'B'  /* Beep */
#define CMD_SCAN_ON     'W'  /* Enable scanning */
#define CMD_SCAN_OFF    'I'  /* Disable scanning */

/* Response types */
#define RESP_VERSION    'v'  /* Version response */
#define RESP_BOARD      's'  /* Board state (64 chars) */
#define RESP_OK         'r'  /* Command acknowledged */

/**
 * Calculate XOR CRC for Millennium protocol.
 *
 * @param data Pointer to data buffer
 * @param len Length of data
 * @return XOR of all bytes
 */
static inline uint8_t millennium_crc(const uint8_t *data, size_t len)
{
    uint8_t crc = 0;
    for (size_t i = 0; i < len; i++) {
        crc ^= data[i];
    }
    return crc;
}

/**
 * Add 7-bit parity to a byte.
 *
 * @param byte Input byte (7-bit value)
 * @return Byte with parity bit set in MSB
 */
static inline uint8_t add_parity(uint8_t byte)
{
    uint8_t parity = 0;
    uint8_t val = byte & 0x7F;
    
    /* Count set bits */
    for (int i = 0; i < 7; i++) {
        if (val & (1 << i)) {
            parity ^= 1;
        }
    }
    
    /* Set parity bit (MSB) for even parity */
    return (parity ? (byte | 0x80) : (byte & 0x7F));
}

/**
 * Check parity of a byte.
 *
 * @param byte Input byte with parity
 * @return true if parity is valid
 */
static inline bool check_parity(uint8_t byte)
{
    uint8_t count = 0;
    for (int i = 0; i < 8; i++) {
        if (byte & (1 << i)) {
            count++;
        }
    }
    return (count % 2) == 0;
}

/**
 * Decode and log a Millennium protocol message.
 *
 * @param dir Traffic direction
 * @param data Raw data buffer
 * @param len Data length
 */
void protocol_decode_and_log(traffic_dir_t dir, const uint8_t *data, size_t len);

/**
 * Validate Millennium protocol CRC.
 *
 * @param data Data buffer including CRC byte at end
 * @param len Total length including CRC
 * @return true if CRC is valid
 */
bool protocol_validate_crc(const uint8_t *data, size_t len);

#endif /* PROTOCOL_H */

