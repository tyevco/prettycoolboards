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

/* ---- internal (ble_*.c) ---- */
#define BLE_MAX_CONN 2

typedef struct {
    bool used;
    uint16_t handle;
    uint16_t mtu;
    bool encrypted;
    bool live_sub, log_sub, hid_sub, bat_sub;
} ble_conn_t;

extern ble_conn_t g_ble_conn[BLE_MAX_CONN];
extern uint16_t g_h_live, g_h_log, g_h_hid_input, g_h_battery;

int ble_gatt_register(void);     /* custom service */
int ble_std_register(void);      /* BAS, DIS, HID */
ble_conn_t *ble_conn_find(uint16_t handle);
int ble_notify(uint16_t conn, uint16_t attr, const void *data, uint16_t len); /* retries on ENOMEM */
void ble_worker_start(void);
void ble_worker_log_read(uint16_t conn, uint32_t from_seq);

#ifdef __cplusplus
}
#endif
