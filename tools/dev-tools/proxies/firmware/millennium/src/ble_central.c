/**
 * @file ble_central.c
 * @brief BLE Central role implementation
 *
 * Scans for and connects to the real Millennium ChessLink board.
 * Subscribes to TX notifications and forwards data via callback.
 */

#include "ble_central.h"
#include "protocol.h"
#include "usb_console.h"

#include <zephyr/kernel.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/gatt.h>
#include <zephyr/bluetooth/uuid.h>
#include <zephyr/logging/log.h>

#include <string.h>
#include <ctype.h>

LOG_MODULE_REGISTER(ble_central, LOG_LEVEL_INF);

/* Connection state */
static struct bt_conn *real_board_conn = NULL;
static bool connected = false;
static bool subscribed = false;

/* GATT handles for characteristics */
static uint16_t tx_handle = 0;
static uint16_t tx_ccc_handle = 0;
static uint16_t rx_handle = 0;

/* Callback for received data */
static central_rx_callback_t rx_callback = NULL;

/* Target device name filter (optional) */
static char target_name_filter[32] = {0};

/* GATT subscription state */
static struct bt_gatt_subscribe_params subscribe_params;

/* Discovery state */
static struct bt_gatt_discover_params discover_params;

/* UUID for filtering scan results */
static struct bt_uuid_128 millennium_uuid = BT_UUID_INIT_128(MILLENNIUM_SERVICE_UUID);

/**
 * Case-insensitive string comparison (first n chars).
 */
static int strnicmp(const char *s1, const char *s2, size_t n)
{
    for (size_t i = 0; i < n; i++) {
        char c1 = s1[i];
        char c2 = s2[i];
        
        if (c1 >= 'A' && c1 <= 'Z') c1 += 32;
        if (c2 >= 'A' && c2 <= 'Z') c2 += 32;
        
        if (c1 != c2) return c1 - c2;
        if (c1 == '\0') return 0;
    }
    return 0;
}

/**
 * Notification callback for TX characteristic.
 *
 * Called when real board sends data via notifications.
 */
static uint8_t notify_callback(struct bt_conn *conn,
                               struct bt_gatt_subscribe_params *params,
                               const void *data, uint16_t length)
{
    if (!data) {
        LOG_WRN("Unsubscribed from TX notifications");
        subscribed = false;
        return BT_GATT_ITER_STOP;
    }
    
    /* Log raw traffic */
    usb_console_log_traffic(DIR_BOARD_TO_APP, data, length);
    
    /* Forward to peripheral side */
    if (rx_callback) {
        rx_callback(data, length);
    }
    
    return BT_GATT_ITER_CONTINUE;
}

/**
 * Subscribe to TX characteristic notifications.
 */
static int subscribe_to_tx(void)
{
    if (tx_handle == 0 || tx_ccc_handle == 0) {
        LOG_ERR("TX handles not discovered");
        return -EINVAL;
    }
    
    subscribe_params.notify = notify_callback;
    subscribe_params.value_handle = tx_handle;
    subscribe_params.ccc_handle = tx_ccc_handle;
    subscribe_params.value = BT_GATT_CCC_NOTIFY;
    
    int err = bt_gatt_subscribe(real_board_conn, &subscribe_params);
    if (err) {
        LOG_ERR("Subscribe failed: %d", err);
        return err;
    }
    
    LOG_INF("Subscribed to TX notifications");
    usb_console_log_status("Subscribed to real board notifications");
    subscribed = true;
    
    return 0;
}

/**
 * GATT discovery callback.
 *
 * Called for each discovered attribute during service discovery.
 */
static uint8_t discover_callback(struct bt_conn *conn,
                                 const struct bt_gatt_attr *attr,
                                 struct bt_gatt_discover_params *params)
{
    if (!attr) {
        LOG_INF("Discovery complete");
        
        /* Now subscribe to TX notifications */
        if (tx_handle != 0) {
            subscribe_to_tx();
        } else {
            LOG_ERR("TX characteristic not found");
        }
        
        return BT_GATT_ITER_STOP;
    }
    
    char uuid_str[64];
    bt_uuid_to_str(attr->uuid, uuid_str, sizeof(uuid_str));
    LOG_DBG("Discovered: handle=%u, uuid=%s", attr->handle, uuid_str);
    
    /* Check for TX characteristic */
    if (bt_uuid_cmp(attr->uuid, BT_UUID_MILLENNIUM_TX) == 0) {
        tx_handle = attr->handle;
        LOG_INF("Found TX characteristic: handle=%u", tx_handle);
    }
    
    /* Check for RX characteristic */
    if (bt_uuid_cmp(attr->uuid, BT_UUID_MILLENNIUM_RX) == 0) {
        rx_handle = attr->handle;
        LOG_INF("Found RX characteristic: handle=%u", rx_handle);
    }
    
    /* Check for CCC descriptor (for notifications) */
    if (bt_uuid_cmp(attr->uuid, BT_UUID_GATT_CCC) == 0) {
        /* Assume this is for the most recently discovered characteristic */
        if (tx_handle != 0 && tx_ccc_handle == 0) {
            tx_ccc_handle = attr->handle;
            LOG_INF("Found TX CCC: handle=%u", tx_ccc_handle);
        }
    }
    
    return BT_GATT_ITER_CONTINUE;
}

/**
 * Start GATT service discovery.
 */
static int discover_services(void)
{
    memset(&discover_params, 0, sizeof(discover_params));
    
    discover_params.uuid = BT_UUID_MILLENNIUM_SERVICE;
    discover_params.func = discover_callback;
    discover_params.start_handle = BT_ATT_FIRST_ATTRIBUTE_HANDLE;
    discover_params.end_handle = BT_ATT_LAST_ATTRIBUTE_HANDLE;
    discover_params.type = BT_GATT_DISCOVER_ATTRIBUTE;
    
    int err = bt_gatt_discover(real_board_conn, &discover_params);
    if (err) {
        LOG_ERR("Discovery start failed: %d", err);
        return err;
    }
    
    LOG_INF("Started service discovery");
    return 0;
}

/**
 * Connection callback.
 */
static void connected_callback(struct bt_conn *conn, uint8_t err)
{
    if (err) {
        LOG_ERR("Connection failed: %d", err);
        real_board_conn = NULL;
        connected = false;
        usb_console_log_status("Failed to connect to real board");
        return;
    }
    
    LOG_INF("Connected to real Millennium board");
    usb_console_log_status("Connected to real Millennium board");
    
    connected = true;
    
    /* Start service discovery */
    discover_services();
}

/**
 * Disconnection callback.
 */
static void disconnected_callback(struct bt_conn *conn, uint8_t reason)
{
    char msg[64];
    snprintf(msg, sizeof(msg), "Disconnected from real board (reason: %u)", reason);
    
    LOG_INF("Disconnected: reason=%u", reason);
    usb_console_log_status(msg);
    
    if (real_board_conn) {
        bt_conn_unref(real_board_conn);
        real_board_conn = NULL;
    }
    
    connected = false;
    subscribed = false;
    tx_handle = 0;
    tx_ccc_handle = 0;
    rx_handle = 0;
    
    /* Restart scanning */
    ble_central_start_scan(target_name_filter[0] ? target_name_filter : NULL);
}

/* Connection callbacks */
BT_CONN_CB_DEFINE(conn_callbacks) = {
    .connected = connected_callback,
    .disconnected = disconnected_callback,
};

/**
 * Check if scan data matches Millennium board.
 */
static bool is_millennium_device(struct bt_data *data, void *user_data)
{
    bool *found = user_data;
    
    switch (data->type) {
    case BT_DATA_UUID128_ALL:
    case BT_DATA_UUID128_SOME:
        /* Check for Millennium service UUID */
        if (data->data_len >= 16) {
            if (memcmp(data->data, millennium_uuid.val, 16) == 0) {
                *found = true;
                return false;  /* Stop parsing */
            }
        }
        break;
    
    case BT_DATA_NAME_COMPLETE:
    case BT_DATA_NAME_SHORTENED:
        /* Check for "MILLENNIUM" in name */
        if (data->data_len >= 10) {
            if (strnicmp((const char *)data->data, "MILLENNIUM", 10) == 0) {
                *found = true;
                return false;
            }
        }
        break;
    }
    
    return true;  /* Continue parsing */
}

/**
 * Scan callback.
 */
static void scan_callback(const bt_addr_le_t *addr, int8_t rssi,
                          uint8_t type, struct net_buf_simple *ad)
{
    /* Check if this is a Millennium device */
    bool is_millennium = false;
    bt_data_parse(ad, is_millennium_device, &is_millennium);
    
    if (!is_millennium) {
        return;
    }
    
    /* Stop scanning */
    bt_le_scan_stop();
    
    char addr_str[BT_ADDR_LE_STR_LEN];
    bt_addr_le_to_str(addr, addr_str, sizeof(addr_str));
    
    char msg[80];
    snprintf(msg, sizeof(msg), "Found Millennium board: %s (RSSI: %d)", addr_str, rssi);
    LOG_INF("%s", msg);
    usb_console_log_status(msg);
    
    /* Connect */
    struct bt_conn_le_create_param create_param = BT_CONN_LE_CREATE_PARAM_INIT(
        BT_CONN_LE_OPT_NONE,
        BT_GAP_SCAN_FAST_INTERVAL,
        BT_GAP_SCAN_FAST_WINDOW
    );
    
    struct bt_le_conn_param conn_param = BT_LE_CONN_PARAM_INIT(
        24, 40,  /* interval min/max (30-50ms) */
        0,       /* latency */
        400      /* timeout (4s) */
    );
    
    int err = bt_conn_le_create(addr, &create_param, &conn_param, &real_board_conn);
    if (err) {
        LOG_ERR("Connect failed: %d", err);
        usb_console_log_status("Failed to initiate connection");
        /* Restart scanning */
        ble_central_start_scan(target_name_filter[0] ? target_name_filter : NULL);
    }
}

int ble_central_init(central_rx_callback_t callback)
{
    rx_callback = callback;
    
    LOG_INF("BLE central initialized");
    return 0;
}

int ble_central_start_scan(const char *target_name)
{
    if (connected) {
        LOG_WRN("Already connected, not scanning");
        return 0;
    }
    
    if (target_name) {
        strncpy(target_name_filter, target_name, sizeof(target_name_filter) - 1);
    } else {
        target_name_filter[0] = '\0';
    }
    
    struct bt_le_scan_param scan_param = {
        .type = BT_LE_SCAN_TYPE_ACTIVE,
        .options = BT_LE_SCAN_OPT_NONE,
        .interval = BT_GAP_SCAN_FAST_INTERVAL,
        .window = BT_GAP_SCAN_FAST_WINDOW,
    };
    
    int err = bt_le_scan_start(&scan_param, scan_callback);
    if (err) {
        LOG_ERR("Scan start failed: %d", err);
        return err;
    }
    
    LOG_INF("Scanning for real Millennium board...");
    usb_console_log_status("Scanning for real Millennium board...");
    
    return 0;
}

int ble_central_stop_scan(void)
{
    return bt_le_scan_stop();
}

bool ble_central_is_connected(void)
{
    return connected && subscribed;
}

int ble_central_send(const uint8_t *data, size_t len)
{
    if (!connected || !real_board_conn) {
        LOG_WRN("Not connected to real board");
        return -ENOTCONN;
    }
    
    if (rx_handle == 0) {
        LOG_ERR("RX handle not discovered");
        return -EINVAL;
    }
    
    /* Log traffic */
    usb_console_log_traffic(DIR_APP_TO_BOARD, data, len);
    
    int err = bt_gatt_write_without_response(real_board_conn, rx_handle,
                                              data, len, false);
    if (err) {
        LOG_ERR("Write failed: %d", err);
        return err;
    }
    
    return 0;
}

int ble_central_disconnect(void)
{
    if (!connected || !real_board_conn) {
        return 0;
    }
    
    return bt_conn_disconnect(real_board_conn, BT_HCI_ERR_REMOTE_USER_TERM_CONN);
}

