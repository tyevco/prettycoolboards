/*
 * ble: NimBLE peripheral.
 *   - the custom caliper service, exactly as main/proto/caliper_gatt.h
 *   - Battery 0x180F, Device Information 0x180A, HID over GATT 0x1812 (keyboard)
 *   - bonding (Just Works, LE Secure Connections), bonds persisted in NVS
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

esp_err_t ble_init(void);   /* after core_init(); starts advertising */
void ble_tick(void);        /* 10 Hz from the app: LIVE + battery notifications */
bool ble_any_connected(void);

#define BLE_MAX_CONN 2

/* bring-up diagnostics (the CLI "bu ble"): advertising state, own address, advertising TX power,
 * and the RSSI the controller measures on each connection (127 = not available). */
typedef struct {
    bool synced, advertising;
    uint8_t addr[6]; /* little-endian, as NimBLE stores it */
    int tx_adv_dbm;
    int conns;
    uint16_t handle[BLE_MAX_CONN];
    int8_t rssi[BLE_MAX_CONN];
} ble_diag_t;
void ble_diag(ble_diag_t *out);

/* ---- internal (ble_*.c) ---- */
typedef struct {
    bool used;
    uint16_t handle;
    uint16_t mtu;
    bool encrypted;
    bool live_sub, log_sub, hid_sub, bat_sub;
} ble_conn_t;

/* The connection table lives in ble.c behind a spinlock: the NimBLE host task writes it (GAP
 * events) while the app task (ble_tick) and ble_wrk read it. Readers get copies. */
extern uint16_t g_h_live, g_h_log, g_h_hid_input, g_h_battery;

int ble_gatt_register(void);     /* custom service */
int ble_std_register(void);      /* BAS, DIS, HID */
bool ble_conn_get(uint16_t handle, ble_conn_t *out);  /* false if not connected */
int ble_conn_snapshot(ble_conn_t out[BLE_MAX_CONN]); /* copies the used entries, returns how many */
int ble_notify(uint16_t conn, uint16_t attr, const void *data, uint16_t len); /* retries on ENOMEM */
void ble_worker_start(void);
/* ext: the 6-byte LOG_READ with CALIPER_LOG_OPT_KIND (record byte 12 whole, else only the unit) */
void ble_worker_log_read(uint16_t conn, uint32_t from_seq, bool ext);

#ifdef __cplusplus
}
#endif
