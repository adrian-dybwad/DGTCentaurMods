/**
 * @file usb_console.h
 * @brief USB CDC console for streaming proxy traffic to host
 *
 * Provides functions to output timestamped, formatted protocol messages
 * over USB CDC to the host computer for real-time analysis.
 */

#ifndef USB_CONSOLE_H
#define USB_CONSOLE_H

#include <stdint.h>
#include <stddef.h>

/**
 * Traffic direction for logging.
 */
typedef enum {
    DIR_APP_TO_BOARD,   /* Chess app -> Real board */
    DIR_BOARD_TO_APP,   /* Real board -> Chess app */
} traffic_dir_t;

/**
 * Initialize USB CDC console.
 *
 * @return 0 on success, negative errno on failure
 */
int usb_console_init(void);

/**
 * Log raw traffic with timestamp.
 *
 * Outputs in format:
 * [HH:MM:SS.mmm] APP->BOARD: xx xx xx xx
 * [HH:MM:SS.mmm] BOARD->APP: xx xx xx xx
 *
 * @param dir Traffic direction
 * @param data Pointer to data buffer
 * @param len Length of data
 */
void usb_console_log_traffic(traffic_dir_t dir, const uint8_t *data, size_t len);

/**
 * Log a decoded protocol message.
 *
 * @param dir Traffic direction
 * @param msg Human-readable message describing the protocol data
 */
void usb_console_log_decoded(traffic_dir_t dir, const char *msg);

/**
 * Log a status message.
 *
 * @param msg Status message (connection events, errors, etc.)
 */
void usb_console_log_status(const char *msg);

/**
 * Print formatted output to USB console.
 *
 * @param fmt printf-style format string
 * @param ... Format arguments
 */
void usb_console_printf(const char *fmt, ...);

#endif /* USB_CONSOLE_H */

