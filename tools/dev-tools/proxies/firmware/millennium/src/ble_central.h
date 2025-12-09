/**
 * @file ble_central.h
 * @brief BLE Central role - connects to real Millennium board
 *
 * Handles scanning for and connecting to the real Millennium ChessLink board.
 * Discovers services/characteristics and subscribes to notifications.
 * Forwards all received data to the peripheral side for relay to the app.
 */

#ifndef BLE_CENTRAL_H
#define BLE_CENTRAL_H

#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>

/**
 * Callback for data received from real board.
 *
 * Called when data is received from the real Millennium board's TX characteristic.
 * This data should be forwarded to the chess app via the peripheral side.
 *
 * @param data Pointer to received data
 * @param len Length of data
 */
typedef void (*central_rx_callback_t)(const uint8_t *data, size_t len);

/**
 * Initialize BLE central role.
 *
 * Sets up scanning and connection handling for the real Millennium board.
 *
 * @param rx_callback Callback for data received from real board
 * @return 0 on success, negative errno on failure
 */
int ble_central_init(central_rx_callback_t rx_callback);

/**
 * Start scanning for real Millennium board.
 *
 * Scans for devices advertising the Millennium service UUID.
 *
 * @param target_name Optional device name to filter (NULL for any Millennium)
 * @return 0 on success, negative errno on failure
 */
int ble_central_start_scan(const char *target_name);

/**
 * Stop scanning.
 *
 * @return 0 on success, negative errno on failure
 */
int ble_central_stop_scan(void);

/**
 * Check if connected to real board.
 *
 * @return true if connected to real Millennium board
 */
bool ble_central_is_connected(void);

/**
 * Send data to real board.
 *
 * Writes data to the real Millennium board's RX characteristic.
 * This is used to forward commands from the chess app to the real board.
 *
 * @param data Pointer to data buffer
 * @param len Length of data
 * @return 0 on success, negative errno on failure
 */
int ble_central_send(const uint8_t *data, size_t len);

/**
 * Disconnect from real board.
 *
 * @return 0 on success, negative errno on failure
 */
int ble_central_disconnect(void);

#endif /* BLE_CENTRAL_H */

