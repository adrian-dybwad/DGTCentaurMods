/**
 * @file main.c
 * @brief Millennium BLE Proxy - Main application
 *
 * BLE man-in-the-middle proxy for Millennium ChessLink protocol analysis.
 *
 * Architecture:
 * - Central role: Connects to real Millennium board
 * - Peripheral role: Accepts connections from chess app
 * - USB CDC: Streams all traffic to host for real-time analysis
 *
 * Data flow:
 * - App writes to proxy RX -> Forward to real board RX
 * - Real board notifies proxy TX -> Forward to app TX
 *
 * The proxy is transparent to both the app and the board.
 */

#include <zephyr/kernel.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/logging/log.h>

#include "ble_central.h"
#include "ble_peripheral.h"
#include "usb_console.h"
#include "protocol.h"

#include <string.h>

LOG_MODULE_REGISTER(main, LOG_LEVEL_INF);

/* LED for status indication (nRF52840 dongle has LED on P0.06) */
#define LED0_NODE DT_ALIAS(led0)
#if DT_NODE_EXISTS(LED0_NODE)
static const struct gpio_dt_spec led = GPIO_DT_SPEC_GET(LED0_NODE, gpios);
static bool led_available = false;
#endif

/* Forward declarations */
static void on_data_from_board(const uint8_t *data, size_t len);
static void on_data_from_app(const uint8_t *data, size_t len);

/**
 * Data received from real board (via central role).
 *
 * Forward to chess app via peripheral TX notifications.
 * Also log and decode for USB console.
 */
static void on_data_from_board(const uint8_t *data, size_t len)
{
    /* Decode for human-readable output */
    protocol_decode_and_log(DIR_BOARD_TO_APP, data, len);
    
    /* Forward to app */
    if (ble_peripheral_is_connected()) {
        int err = ble_peripheral_send(data, len);
        if (err) {
            LOG_ERR("Failed to forward to app: %d", err);
        }
    } else {
        LOG_WRN("App not connected, dropping board data");
    }
}

/**
 * Data received from chess app (via peripheral RX).
 *
 * Forward to real board via central RX write.
 * Also log and decode for USB console.
 */
static void on_data_from_app(const uint8_t *data, size_t len)
{
    /* Decode for human-readable output */
    protocol_decode_and_log(DIR_APP_TO_BOARD, data, len);
    
    /* Forward to real board */
    if (ble_central_is_connected()) {
        int err = ble_central_send(data, len);
        if (err) {
            LOG_ERR("Failed to forward to board: %d", err);
        }
    } else {
        LOG_WRN("Board not connected, dropping app data");
    }
}

/**
 * Initialize LED for status indication.
 */
static void led_init(void)
{
#if DT_NODE_EXISTS(LED0_NODE)
    if (!gpio_is_ready_dt(&led)) {
        LOG_WRN("LED device not ready");
        return;
    }
    
    int ret = gpio_pin_configure_dt(&led, GPIO_OUTPUT_INACTIVE);
    if (ret < 0) {
        LOG_WRN("Failed to configure LED: %d", ret);
        return;
    }
    
    led_available = true;
    LOG_INF("LED initialized");
#endif
}

/**
 * Update LED based on connection status.
 *
 * - Off: No connections
 * - Slow blink: Scanning/advertising only
 * - Fast blink: One connection (central or peripheral)
 * - Solid: Both connections established (proxy active)
 */
static void led_update(bool board_connected, bool app_connected)
{
#if DT_NODE_EXISTS(LED0_NODE)
    if (!led_available) {
        return;
    }
    
    static uint32_t last_toggle = 0;
    static bool led_state = false;
    uint32_t now = k_uptime_get_32();
    
    if (board_connected && app_connected) {
        /* Solid on - proxy fully active */
        gpio_pin_set_dt(&led, 1);
    } else if (board_connected || app_connected) {
        /* Fast blink - one connection */
        if (now - last_toggle >= 200) {
            led_state = !led_state;
            gpio_pin_set_dt(&led, led_state);
            last_toggle = now;
        }
    } else {
        /* Slow blink - scanning/advertising */
        if (now - last_toggle >= 1000) {
            led_state = !led_state;
            gpio_pin_set_dt(&led, led_state);
            last_toggle = now;
        }
    }
#endif
}

/**
 * Print startup banner.
 */
static void print_banner(void)
{
    usb_console_printf("\r\n");
    usb_console_printf("============================================\r\n");
    usb_console_printf("  Millennium BLE Proxy\r\n");
    usb_console_printf("  nRF52840 USB Dongle Firmware\r\n");
    usb_console_printf("============================================\r\n");
    usb_console_printf("\r\n");
    usb_console_printf("This proxy sits between a chess app and a\r\n");
    usb_console_printf("real Millennium ChessLink board, logging\r\n");
    usb_console_printf("all BLE traffic for protocol analysis.\r\n");
    usb_console_printf("\r\n");
    usb_console_printf("Traffic format:\r\n");
    usb_console_printf("  [timestamp] APP->BOARD: xx xx xx ...\r\n");
    usb_console_printf("  [timestamp] BOARD->APP: xx xx xx ...\r\n");
    usb_console_printf("  [timestamp] STATUS: status message\r\n");
    usb_console_printf("\r\n");
    usb_console_printf("============================================\r\n");
    usb_console_printf("\r\n");
}

int main(void)
{
    int err;
    
    LOG_INF("Millennium BLE Proxy starting...");
    
    /* Initialize LED */
    led_init();
    
    /* Initialize USB console */
    err = usb_console_init();
    if (err) {
        LOG_ERR("USB console init failed: %d", err);
        /* Continue anyway - we can still proxy */
    }
    
    /* Print startup banner */
    print_banner();
    
    /* Initialize Bluetooth */
    err = bt_enable(NULL);
    if (err) {
        LOG_ERR("Bluetooth init failed: %d", err);
        usb_console_log_status("ERROR: Bluetooth init failed");
        return err;
    }
    
    LOG_INF("Bluetooth initialized");
    usb_console_log_status("Bluetooth initialized");
    
    /* Initialize peripheral role (for chess app connections) */
    err = ble_peripheral_init(on_data_from_app);
    if (err) {
        LOG_ERR("Peripheral init failed: %d", err);
        usb_console_log_status("ERROR: Peripheral init failed");
        return err;
    }
    
    /* Initialize central role (for real board connection) */
    err = ble_central_init(on_data_from_board);
    if (err) {
        LOG_ERR("Central init failed: %d", err);
        usb_console_log_status("ERROR: Central init failed");
        return err;
    }
    
    /* Start advertising (for chess app to find us) */
    err = ble_peripheral_start_advertising();
    if (err) {
        LOG_ERR("Advertising start failed: %d", err);
        usb_console_log_status("ERROR: Advertising failed");
        return err;
    }
    
    /* Start scanning for real Millennium board */
    err = ble_central_start_scan("MILLENNIUM");
    if (err) {
        LOG_ERR("Scan start failed: %d", err);
        usb_console_log_status("ERROR: Scanning failed");
        return err;
    }
    
    usb_console_log_status("Proxy initialized - scanning for board, advertising for app");
    
    /* Main loop - update LED status */
    while (1) {
        bool board_conn = ble_central_is_connected();
        bool app_conn = ble_peripheral_is_connected();
        
        led_update(board_conn, app_conn);
        
        k_sleep(K_MSEC(50));
    }
    
    return 0;
}

