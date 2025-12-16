/**
 * @file ble_peripheral.h
 * @brief BLE Peripheral role - accepts connections from chess app
 *
 * Advertises as a Millennium ChessLink board for chess apps to connect to.
 * Exposes the same GATT services and characteristics as the real board.
 * Forwards all received commands to the central side for relay to the real board.
 */

#ifndef BLE_PERIPHERAL_H
#define BLE_PERIPHERAL_H

#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>

/**
 * Callback for data received from chess app.
 *
 * Called when the chess app writes to the RX characteristic.
 * This data should be forwarded to the real board via the central side.
 *
 * @param data Pointer to received data
 * @param len Length of data
 */
typedef void (*peripheral_rx_callback_t)(const uint8_t *data, size_t len);

/**
 * Initialize BLE peripheral role.
 *
 * Sets up GATT services matching the real Millennium board and starts advertising.
 *
 * @param rx_callback Callback for data received from chess app
 * @return 0 on success, negative errno on failure
 */
int ble_peripheral_init(peripheral_rx_callback_t rx_callback);

/**
 * Start advertising.
 *
 * Makes the proxy visible to chess apps as "MILLENNIUM CHESS".
 *
 * @return 0 on success, negative errno on failure
 */
int ble_peripheral_start_advertising(void);

/**
 * Stop advertising.
 *
 * @return 0 on success, negative errno on failure
 */
int ble_peripheral_stop_advertising(void);

/**
 * Check if a chess app is connected.
 *
 * @return true if an app is connected to the peripheral
 */
bool ble_peripheral_is_connected(void);

/**
 * Send data to connected chess app.
 *
 * Sends data via TX characteristic notification.
 * This is used to forward responses from the real board to the app.
 *
 * @param data Pointer to data buffer
 * @param len Length of data
 * @return 0 on success, negative errno on failure
 */
int ble_peripheral_send(const uint8_t *data, size_t len);

/**
 * Disconnect from chess app.
 *
 * @return 0 on success, negative errno on failure
 */
int ble_peripheral_disconnect(void);

#endif /* BLE_PERIPHERAL_H */

