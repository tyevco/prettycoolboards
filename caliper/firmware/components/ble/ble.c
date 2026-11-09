/* NimBLE host bring-up, GAP (advertising, connections, bonding) and notifications. */
#include "ble.h"

#include <string.h>

#include "caliper_core.h"
#include "caliper_gatt.h"
#include "esp_bt.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "host/ble_hs.h"
#include "host/util/util.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "services/gap/ble_svc_gap.h"
#include "services/gatt/ble_svc_gatt.h"

static const char *TAG = "ble";

void ble_store_config_init(void);
const ble_uuid128_t *ble_gatt_svc_uuid(void);
void ble_gatt_pack_live(uint8_t out[CALIPER_LIVE_LEN]);

static ble_conn_t s_conn[BLE_MAX_CONN];
static portMUX_TYPE s_conn_mux = portMUX_INITIALIZER_UNLOCKED; /* guards s_conn: short copies only */
static uint8_t s_own_addr_type;
static char s_name[SETTINGS_NAME_MAX + 1];
static uint8_t s_last_live[CALIPER_LIVE_LEN];
static int64_t s_last_live_us;
static uint8_t s_last_bat = 0xFF;

static int gap_event(struct ble_gap_event *ev, void *arg);

/* caller holds s_conn_mux */
static ble_conn_t *conn_find_locked(uint16_t handle)
{
    for (int i = 0; i < BLE_MAX_CONN; i++) {
        if (s_conn[i].used && s_conn[i].handle == handle) {
            return &s_conn[i];
        }
    }
    return NULL;
}

bool ble_conn_get(uint16_t handle, ble_conn_t *out)
{
    taskENTER_CRITICAL(&s_conn_mux);
    ble_conn_t *c = conn_find_locked(handle);
    if (c) {
        *out = *c;
    }
    taskEXIT_CRITICAL(&s_conn_mux);
    return c != NULL;
}

int ble_conn_snapshot(ble_conn_t out[BLE_MAX_CONN])
{
    int n = 0;
    taskENTER_CRITICAL(&s_conn_mux);
    for (int i = 0; i < BLE_MAX_CONN; i++) {
        if (s_conn[i].used) {
            out[n++] = s_conn[i];
        }
    }
    taskEXIT_CRITICAL(&s_conn_mux);
    return n;
}

static int conn_count(void)
{
    int n = 0;
    taskENTER_CRITICAL(&s_conn_mux);
    for (int i = 0; i < BLE_MAX_CONN; i++) {
        n += s_conn[i].used;
    }
    taskEXIT_CRITICAL(&s_conn_mux);
    return n;
}

/* Applies one GAP update to a connection's entry under the lock. */
typedef enum { UPD_SUB, UPD_MTU, UPD_ENC, UPD_FREE } conn_upd_t;

static void conn_update(uint16_t handle, conn_upd_t what, uint16_t attr, uint16_t val)
{
    taskENTER_CRITICAL(&s_conn_mux);
    ble_conn_t *c = conn_find_locked(handle);
    if (c) {
        switch (what) {
        case UPD_SUB:
            if (attr == g_h_live) c->live_sub = val != 0;
            else if (attr == g_h_log) c->log_sub = val != 0;
            else if (attr == g_h_hid_input) c->hid_sub = val != 0;
            else if (attr == g_h_battery) c->bat_sub = val != 0;
            break;
        case UPD_MTU: c->mtu = val; break;
        case UPD_ENC: c->encrypted = val != 0; break;
        case UPD_FREE: c->used = false; break;
        }
    }
    taskEXIT_CRITICAL(&s_conn_mux);
}

bool ble_any_connected(void)
{
    return conn_count() > 0;
}

static void start_adv(void)
{
    if (conn_count() >= BLE_MAX_CONN || ble_gap_adv_active()) {
        return;
    }
    struct ble_hs_adv_fields f;
    memset(&f, 0, sizeof(f));
    f.flags = BLE_HS_ADV_F_DISC_GEN | BLE_HS_ADV_F_BREDR_UNSUP;
    f.appearance = 0x03C1; /* HID keyboard */
    f.appearance_is_present = 1;
    static const ble_uuid16_t hid = BLE_UUID16_INIT(CALIPER_UUID16_HID);
    f.uuids16 = &hid;
    f.num_uuids16 = 1;
    f.uuids16_is_complete = 0;
    size_t nl = strlen(s_name);
    /* 31 bytes: flags 3 + appearance 4 + uuid16 4 leave 20 for the name (2 header) */
    f.name = (const uint8_t *)s_name;
    f.name_len = (uint8_t)(nl > 18 ? 18 : nl);
    f.name_is_complete = nl <= 18;
    int rc = ble_gap_adv_set_fields(&f);
    if (rc) {
        ESP_LOGE(TAG, "adv fields: %d", rc);
        return;
    }
    struct ble_hs_adv_fields r;
    memset(&r, 0, sizeof(r));
    r.uuids128 = ble_gatt_svc_uuid();
    r.num_uuids128 = 1;
    r.uuids128_is_complete = 1;
    rc = ble_gap_adv_rsp_set_fields(&r);
    if (rc) {
        ESP_LOGE(TAG, "scan rsp: %d", rc);
        return;
    }
    struct ble_gap_adv_params p;
    memset(&p, 0, sizeof(p));
    p.conn_mode = BLE_GAP_CONN_MODE_UND;
    p.disc_mode = BLE_GAP_DISC_MODE_GEN;
    p.itvl_min = 160; /* 100 ms (0.625 ms units) */
    p.itvl_max = 240; /* 150 ms */
    rc = ble_gap_adv_start(s_own_addr_type, NULL, BLE_HS_FOREVER, &p, gap_event, NULL);
    if (rc && rc != BLE_HS_EALREADY) {
        ESP_LOGE(TAG, "adv start: %d", rc);
    }
}

void ble_diag(ble_diag_t *out)
{
    memset(out, 0, sizeof(*out));
    out->synced = ble_hs_synced();
    out->advertising = out->synced && ble_gap_adv_active();
    if (out->synced) {
        ble_hs_id_copy_addr(s_own_addr_type, out->addr, NULL);
    }
    /* level index -> dBm: -24 + 3 * index up to +18 dBm (index 14), index 15 = +20 dBm */
    esp_power_level_t lvl = esp_ble_tx_power_get(ESP_BLE_PWR_TYPE_ADV);
    out->tx_adv_dbm = lvl == ESP_PWR_LVL_INVALID ? -128 : lvl >= 15 ? 20 : -24 + 3 * (int)lvl;
    ble_conn_t c[BLE_MAX_CONN];
    out->conns = ble_conn_snapshot(c);
    for (int i = 0; i < out->conns; i++) {
        out->handle[i] = c[i].handle;
        if (ble_gap_conn_rssi(c[i].handle, &out->rssi[i]) != 0) {
            out->rssi[i] = 127; /* not available */
        }
    }
}

static void update_core_link(void)
{
    core_set_ble(ble_any_connected());
}

static int gap_event(struct ble_gap_event *ev, void *arg)
{
    (void)arg;
    switch (ev->type) {
    case BLE_GAP_EVENT_CONNECT:
        if (ev->connect.status == 0) {
            taskENTER_CRITICAL(&s_conn_mux);
            for (int i = 0; i < BLE_MAX_CONN; i++) {
                if (!s_conn[i].used) {
                    memset(&s_conn[i], 0, sizeof(s_conn[i]));
                    s_conn[i].used = true;
                    s_conn[i].handle = ev->connect.conn_handle;
                    s_conn[i].mtu = BLE_ATT_MTU_DFLT;
                    break;
                }
            }
            taskEXIT_CRITICAL(&s_conn_mux);
            ESP_LOGI(TAG, "connected (%d)", ev->connect.conn_handle);
            core_activity();
        }
        update_core_link();
        start_adv();
        return 0;
    case BLE_GAP_EVENT_DISCONNECT: {
        conn_update(ev->disconnect.conn.conn_handle, UPD_FREE, 0, 0);
        ESP_LOGI(TAG, "disconnected (reason 0x%x)", ev->disconnect.reason);
        update_core_link();
        start_adv();
        return 0;
    }
    case BLE_GAP_EVENT_ADV_COMPLETE:
        start_adv();
        return 0;
    case BLE_GAP_EVENT_SUBSCRIBE:
        conn_update(ev->subscribe.conn_handle, UPD_SUB, ev->subscribe.attr_handle, ev->subscribe.cur_notify);
        return 0;
    case BLE_GAP_EVENT_MTU:
        conn_update(ev->mtu.conn_handle, UPD_MTU, 0, ev->mtu.value);
        return 0;
    case BLE_GAP_EVENT_ENC_CHANGE: {
        conn_update(ev->enc_change.conn_handle, UPD_ENC, 0, ev->enc_change.status == 0);
        ESP_LOGI(TAG, "encryption %s", ev->enc_change.status == 0 ? "on" : "failed");
        return 0;
    }
    case BLE_GAP_EVENT_REPEAT_PAIRING: {
        /* the peer lost its bond: forget ours and pair again */
        struct ble_gap_conn_desc d;
        if (ble_gap_conn_find(ev->repeat_pairing.conn_handle, &d) == 0) {
            ble_store_util_delete_peer(&d.peer_id_addr);
        }
        return BLE_GAP_REPEAT_PAIRING_RETRY;
    }
    default:
        return 0;
    }
}

static void on_sync(void)
{
    int rc = ble_hs_util_ensure_addr(0);
    if (rc == 0) {
        rc = ble_hs_id_infer_auto(0, &s_own_addr_type);
    }
    if (rc) {
        ESP_LOGE(TAG, "address: %d", rc);
        return;
    }
    start_adv();
}

static void on_reset(int reason)
{
    ESP_LOGW(TAG, "host reset, reason %d", reason);
}

static void host_task(void *param)
{
    (void)param;
    nimble_port_run();
    nimble_port_freertos_deinit();
}

int ble_notify(uint16_t conn, uint16_t attr, const void *data, uint16_t len)
{
    for (int attempt = 0; attempt < 100; attempt++) {
        struct os_mbuf *om = ble_hs_mbuf_from_flat(data, len);
        if (!om) {
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }
        int rc = ble_gatts_notify_custom(conn, attr, om); /* consumes om */
        if (rc != BLE_HS_ENOMEM) {
            return rc;
        }
        vTaskDelay(pdMS_TO_TICKS(10));
    }
    return BLE_HS_ENOMEM;
}

void ble_tick(void)
{
    if (!ble_any_connected()) {
        return;
    }
    uint8_t live[CALIPER_LIVE_LEN];
    ble_gatt_pack_live(live);
    int64_t now = esp_timer_get_time();
    bool changed = memcmp(live, s_last_live, sizeof(live)) != 0;
    ble_conn_t conns[BLE_MAX_CONN];
    int nc = ble_conn_snapshot(conns); /* notify outside the lock */
    if (changed || now - s_last_live_us > 1000000) {
        memcpy(s_last_live, live, sizeof(live));
        s_last_live_us = now;
        for (int i = 0; i < nc; i++) {
            if (conns[i].live_sub) {
                ble_notify(conns[i].handle, g_h_live, live, sizeof(live));
            }
        }
    }
    cal_status_t st;
    core_get_status(&st);
    if (st.battery_pct != s_last_bat) {
        s_last_bat = st.battery_pct;
        for (int i = 0; i < nc; i++) {
            if (conns[i].bat_sub) {
                ble_notify(conns[i].handle, g_h_battery, &st.battery_pct, 1);
            }
        }
    }
}

static void on_settings(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
    (void)base;
    (void)id;
    (void)data;
    settings_t s;
    core_get_settings(&s);
    if (strcmp(s.name, s_name) != 0) {
        strlcpy(s_name, s.name, sizeof(s_name));
        ble_svc_gap_device_name_set(s_name);
        if (ble_gap_adv_active()) { /* refresh the advertised name */
            ble_gap_adv_stop();
            start_adv();
        }
    }
}

esp_err_t ble_init(void)
{
    esp_err_t err = nimble_port_init();
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "nimble_port_init: %s", esp_err_to_name(err));
        return err;
    }
    ble_hs_cfg.reset_cb = on_reset;
    ble_hs_cfg.sync_cb = on_sync;
    ble_hs_cfg.store_status_cb = ble_store_util_status_rr;
    ble_hs_cfg.sm_io_cap = BLE_SM_IO_CAP_NO_IO; /* Just Works: no display/keyboard for a passkey */
    ble_hs_cfg.sm_bonding = 1;
    ble_hs_cfg.sm_mitm = 0;
    ble_hs_cfg.sm_sc = 1;
    ble_hs_cfg.sm_our_key_dist = BLE_SM_PAIR_KEY_DIST_ENC | BLE_SM_PAIR_KEY_DIST_ID;
    ble_hs_cfg.sm_their_key_dist = BLE_SM_PAIR_KEY_DIST_ENC | BLE_SM_PAIR_KEY_DIST_ID;

    ble_svc_gap_init();
    ble_svc_gatt_init();
    int rc = ble_gatt_register();
    if (rc == 0) {
        rc = ble_std_register();
    }
    if (rc) {
        ESP_LOGE(TAG, "GATT registration failed: %d", rc);
        return ESP_FAIL;
    }
    settings_t s;
    core_get_settings(&s);
    strlcpy(s_name, s.name, sizeof(s_name));
    ble_svc_gap_device_name_set(s_name);
    ble_svc_gap_device_appearance_set(0x03C1);
    ble_store_config_init();
    bus_subscribe(CAL_EVT_SETTINGS, on_settings, NULL);
    ble_worker_start();
    nimble_port_freertos_init(host_task);
    return ESP_OK;
}
