/**
 * @file ble_peripheral.c
 * @brief BLE Peripheral role implementation
 *
 * Advertises as a Millennium ChessLink board and exposes matching GATT services.
 * The chess app connects here thinking it's the real board.
 */

#include "ble_peripheral.h"
#include "protocol.h"
#include "usb_console.h"

#include <zephyr/kernel.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/gatt.h>
#include <zephyr/bluetooth/uuid.h>
#include <zephyr/logging/log.h>

#include <string.h>

LOG_MODULE_REGISTER(ble_peripheral, LOG_LEVEL_INF);

/* Connection state */
static struct bt_conn *app_conn = NULL;
static bool connected = false;
static bool tx_notifications_enabled = false;

/* Callback for received data from app */
static peripheral_rx_callback_t rx_callback = NULL;

/* Characteristic values (buffers for reads) */
static uint8_t config_value[20] = {0};
static uint8_t tx_value[244] = {0};  /* Max BLE payload */
static uint16_t tx_value_len = 0;

/**
 * TX characteristic CCC changed callback.
 *
 * Called when the app enables/disables notifications on TX.
 */
static void tx_ccc_changed(const struct bt_gatt_attr *attr, uint16_t value)
{
    tx_notifications_enabled = (value == BT_GATT_CCC_NOTIFY);
    
    LOG_INF("TX notifications %s", tx_notifications_enabled ? "enabled" : "disabled");
    
    if (tx_notifications_enabled) {
        usb_console_log_status("App subscribed to TX notifications");
    } else {
        usb_console_log_status("App unsubscribed from TX notifications");
    }
}

/**
 * RX characteristic write callback.
 *
 * Called when the app writes data to send to the board.
 */
static ssize_t rx_write_callback(struct bt_conn *conn,
                                  const struct bt_gatt_attr *attr,
                                  const void *buf, uint16_t len,
                                  uint16_t offset, uint8_t flags)
{
    if (offset > 0) {
        return BT_GATT_ERR(BT_ATT_ERR_INVALID_OFFSET);
    }
    
    LOG_DBG("RX write: %u bytes", len);
    
    /* Forward to central side (to send to real board) */
    if (rx_callback && len > 0) {
        rx_callback(buf, len);
    }
    
    return len;
}

/**
 * Config characteristic read callback.
 */
static ssize_t config_read_callback(struct bt_conn *conn,
                                     const struct bt_gatt_attr *attr,
                                     void *buf, uint16_t len, uint16_t offset)
{
    return bt_gatt_attr_read(conn, attr, buf, len, offset,
                             config_value, sizeof(config_value));
}

/**
 * Config characteristic write callback.
 */
static ssize_t config_write_callback(struct bt_conn *conn,
                                      const struct bt_gatt_attr *attr,
                                      const void *buf, uint16_t len,
                                      uint16_t offset, uint8_t flags)
{
    if (offset > 0) {
        return BT_GATT_ERR(BT_ATT_ERR_INVALID_OFFSET);
    }
    
    if (len > sizeof(config_value)) {
        return BT_GATT_ERR(BT_ATT_ERR_INVALID_ATTRIBUTE_LEN);
    }
    
    memcpy(config_value, buf, len);
    LOG_DBG("Config write: %u bytes", len);
    
    return len;
}

/**
 * TX characteristic read callback.
 */
static ssize_t tx_read_callback(struct bt_conn *conn,
                                 const struct bt_gatt_attr *attr,
                                 void *buf, uint16_t len, uint16_t offset)
{
    return bt_gatt_attr_read(conn, attr, buf, len, offset,
                             tx_value, tx_value_len);
}

/**
 * Notify1 and Notify2 CCC changed callbacks.
 */
static void notify1_ccc_changed(const struct bt_gatt_attr *attr, uint16_t value)
{
    LOG_DBG("Notify1 CCC changed: %u", value);
}

static void notify2_ccc_changed(const struct bt_gatt_attr *attr, uint16_t value)
{
    LOG_DBG("Notify2 CCC changed: %u", value);
}

/*
 * GATT Service Definition
 *
 * Matches the real Millennium board's service structure:
 * - Service: 49535343-fe7d-4ae5-8fa9-9fafd205e455
 *   - Config:  49535343-6daa-4d02-abf6-19569aca69fe (READ/WRITE)
 *   - Notify1: 49535343-aca3-481c-91ec-d85e28a60318 (WRITE/NOTIFY)
 *   - TX:      49535343-1e4d-4bd9-ba61-23c647249616 (READ/WRITE/WRITE_NR/NOTIFY)
 *   - RX:      49535343-8841-43f4-a8d4-ecbe34729bb3 (WRITE/WRITE_NR)
 *   - Notify2: 49535343-026e-3a9b-954c-97daef17e26e (WRITE/NOTIFY)
 */
BT_GATT_SERVICE_DEFINE(millennium_svc,
    /* Service declaration */
    BT_GATT_PRIMARY_SERVICE(BT_UUID_MILLENNIUM_SERVICE),
    
    /* Config characteristic */
    BT_GATT_CHARACTERISTIC(BT_UUID_MILLENNIUM_CONFIG,
        BT_GATT_CHRC_READ | BT_GATT_CHRC_WRITE,
        BT_GATT_PERM_READ | BT_GATT_PERM_WRITE,
        config_read_callback, config_write_callback, NULL),
    
    /* Notify1 characteristic */
    BT_GATT_CHARACTERISTIC(BT_UUID_MILLENNIUM_NOTIFY1,
        BT_GATT_CHRC_WRITE | BT_GATT_CHRC_NOTIFY,
        BT_GATT_PERM_WRITE,
        NULL, NULL, NULL),
    BT_GATT_CCC(notify1_ccc_changed, BT_GATT_PERM_READ | BT_GATT_PERM_WRITE),
    
    /* TX characteristic (main data output) */
    BT_GATT_CHARACTERISTIC(BT_UUID_MILLENNIUM_TX,
        BT_GATT_CHRC_READ | BT_GATT_CHRC_WRITE | 
        BT_GATT_CHRC_WRITE_WITHOUT_RESP | BT_GATT_CHRC_NOTIFY,
        BT_GATT_PERM_READ | BT_GATT_PERM_WRITE,
        tx_read_callback, NULL, NULL),
    BT_GATT_CCC(tx_ccc_changed, BT_GATT_PERM_READ | BT_GATT_PERM_WRITE),
    
    /* RX characteristic (main data input from app) */
    BT_GATT_CHARACTERISTIC(BT_UUID_MILLENNIUM_RX,
        BT_GATT_CHRC_WRITE | BT_GATT_CHRC_WRITE_WITHOUT_RESP,
        BT_GATT_PERM_WRITE,
        NULL, rx_write_callback, NULL),
    
    /* Notify2 characteristic */
    BT_GATT_CHARACTERISTIC(BT_UUID_MILLENNIUM_NOTIFY2,
        BT_GATT_CHRC_WRITE | BT_GATT_CHRC_NOTIFY,
        BT_GATT_PERM_WRITE,
        NULL, NULL, NULL),
    BT_GATT_CCC(notify2_ccc_changed, BT_GATT_PERM_READ | BT_GATT_PERM_WRITE),
);

/**
 * Connection callback.
 */
static void peripheral_connected(struct bt_conn *conn, uint8_t err)
{
    /* Check if this is a connection we initiated (central role) */
    struct bt_conn_info info;
    bt_conn_get_info(conn, &info);
    
    if (info.role != BT_CONN_ROLE_PERIPHERAL) {
        return;  /* Not a peripheral connection */
    }
    
    if (err) {
        LOG_ERR("App connection failed: %d", err);
        return;
    }
    
    app_conn = bt_conn_ref(conn);
    connected = true;
    
    char addr_str[BT_ADDR_LE_STR_LEN];
    bt_addr_le_to_str(bt_conn_get_dst(conn), addr_str, sizeof(addr_str));
    
    char msg[80];
    snprintf(msg, sizeof(msg), "Chess app connected: %s", addr_str);
    LOG_INF("%s", msg);
    usb_console_log_status(msg);
}

/**
 * Disconnection callback.
 */
static void peripheral_disconnected(struct bt_conn *conn, uint8_t reason)
{
    if (conn != app_conn) {
        return;  /* Not our connection */
    }
    
    char msg[64];
    snprintf(msg, sizeof(msg), "Chess app disconnected (reason: %u)", reason);
    LOG_INF("%s", msg);
    usb_console_log_status(msg);
    
    bt_conn_unref(app_conn);
    app_conn = NULL;
    connected = false;
    tx_notifications_enabled = false;
    
    /* Restart advertising */
    ble_peripheral_start_advertising();
}

/* Connection callbacks structure */
static struct bt_conn_cb peripheral_conn_callbacks = {
    .connected = peripheral_connected,
    .disconnected = peripheral_disconnected,
};

/* Advertising data */
static const struct bt_data ad[] = {
    BT_DATA_BYTES(BT_DATA_FLAGS, (BT_LE_AD_GENERAL | BT_LE_AD_NO_BREDR)),
    BT_DATA(BT_DATA_NAME_COMPLETE, "MILLENNIUM CHESS", 16),
};

/* Scan response data with service UUID */
static const struct bt_data sd[] = {
    BT_DATA_BYTES(BT_DATA_UUID128_ALL, MILLENNIUM_SERVICE_UUID),
};

int ble_peripheral_init(peripheral_rx_callback_t callback)
{
    rx_callback = callback;
    
    bt_conn_cb_register(&peripheral_conn_callbacks);
    
    LOG_INF("BLE peripheral initialized");
    return 0;
}

int ble_peripheral_start_advertising(void)
{
    /* Use connectable advertising parameters */
    struct bt_le_adv_param adv_param = BT_LE_ADV_PARAM_INIT(
        BT_LE_ADV_OPT_CONN,
        BT_GAP_ADV_FAST_INT_MIN_2,
        BT_GAP_ADV_FAST_INT_MAX_2,
        NULL
    );
    
    int err = bt_le_adv_start(&adv_param, ad, ARRAY_SIZE(ad), sd, ARRAY_SIZE(sd));
    if (err) {
        LOG_ERR("Advertising start failed: %d", err);
        return err;
    }
    
    LOG_INF("Advertising as 'MILLENNIUM CHESS'");
    usb_console_log_status("Advertising as 'MILLENNIUM CHESS' - waiting for app...");
    
    return 0;
}

int ble_peripheral_stop_advertising(void)
{
    return bt_le_adv_stop();
}

bool ble_peripheral_is_connected(void)
{
    return connected && tx_notifications_enabled;
}

int ble_peripheral_send(const uint8_t *data, size_t len)
{
    if (!connected || !app_conn) {
        LOG_WRN("No app connected");
        return -ENOTCONN;
    }
    
    if (!tx_notifications_enabled) {
        LOG_WRN("TX notifications not enabled");
        return -EINVAL;
    }
    
    /* Store value for reads */
    tx_value_len = MIN(len, sizeof(tx_value));
    memcpy(tx_value, data, tx_value_len);
    
    /* Get TX characteristic attribute */
    const struct bt_gatt_attr *tx_attr = &millennium_svc.attrs[6];  /* TX char value */
    
    int err = bt_gatt_notify(app_conn, tx_attr, data, len);
    if (err) {
        LOG_ERR("Notify failed: %d", err);
        return err;
    }
    
    return 0;
}

int ble_peripheral_disconnect(void)
{
    if (!connected || !app_conn) {
        return 0;
    }
    
    return bt_conn_disconnect(app_conn, BT_HCI_ERR_REMOTE_USER_TERM_CONN);
}

