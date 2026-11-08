/* The custom caliper service (main/proto/caliper_gatt.h). */
#include <string.h>

#include "ble.h"
#include "caliper_core.h"
#include "caliper_gatt.h"
#include "esp_log.h"
#include "gatt_codec.h"
#include "host/ble_hs.h"

static const char *TAG = "ble_gatt";

uint16_t g_h_live, g_h_log;
static uint16_t s_h_cmd, s_h_settings, s_h_profiles;

static const ble_uuid128_t s_uuid_svc = BLE_UUID128_INIT(CALIPER_UUID128_BYTES(CALIPER_UUID_SVC));
static const ble_uuid128_t s_uuid_live = BLE_UUID128_INIT(CALIPER_UUID128_BYTES(CALIPER_UUID_LIVE));
static const ble_uuid128_t s_uuid_cmd = BLE_UUID128_INIT(CALIPER_UUID128_BYTES(CALIPER_UUID_COMMAND));
static const ble_uuid128_t s_uuid_log = BLE_UUID128_INIT(CALIPER_UUID128_BYTES(CALIPER_UUID_LOG));
static const ble_uuid128_t s_uuid_settings = BLE_UUID128_INIT(CALIPER_UUID128_BYTES(CALIPER_UUID_SETTINGS));
static const ble_uuid128_t s_uuid_profiles = BLE_UUID128_INIT(CALIPER_UUID128_BYTES(CALIPER_UUID_PROFILES));

const ble_uuid128_t *ble_gatt_svc_uuid(void);
const ble_uuid128_t *ble_gatt_svc_uuid(void)
{
    return &s_uuid_svc;
}

/* ATT error codes returned on writes (the contract: caliper_gatt.h CALIPER_ATT_ERR_*) */
#define ERR_LEN    CALIPER_ATT_ERR_LEN    /* 0x0D: wrong length */
#define ERR_OPCODE CALIPER_ATT_ERR_OPCODE /* 0x06: unknown opcode */
#define ERR_VALUE  CALIPER_ATT_ERR_VALUE  /* 0x80: application error: bad argument */
_Static_assert(CALIPER_ATT_ERR_LEN == BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN, "0x0D");
_Static_assert(CALIPER_ATT_ERR_OPCODE == BLE_ATT_ERR_REQ_NOT_SUPPORTED, "0x06");
_Static_assert(CALIPER_ATT_ERR_AUTHEN == BLE_ATT_ERR_INSUFFICIENT_AUTHEN, "0x05");
_Static_assert(CALIPER_ATT_ERR_ENC == BLE_ATT_ERR_INSUFFICIENT_ENC, "0x0F");

static int append(struct ble_gatt_access_ctxt *ctxt, const void *d, size_t n)
{
    return os_mbuf_append(ctxt->om, d, (uint16_t)n) == 0 ? 0 : BLE_ATT_ERR_INSUFFICIENT_RES;
}

static int read_flat(struct ble_gatt_access_ctxt *ctxt, void *buf, size_t max, uint16_t *len)
{
    uint16_t n = OS_MBUF_PKTLEN(ctxt->om);
    if (n > max) {
        return ERR_LEN;
    }
    return ble_hs_mbuf_to_flat(ctxt->om, buf, (uint16_t)max, len) == 0 ? 0 : BLE_ATT_ERR_UNLIKELY;
}

void ble_gatt_pack_live(uint8_t out[CALIPER_LIVE_LEN]);
void ble_gatt_pack_live(uint8_t out[CALIPER_LIVE_LEN])
{
    cal_live_t lv;
    core_get_live(&lv);
    gatt_live_t g = {.value_nm = lv.value_nm, .cap_nm = lv.cap_nm, .unit = lv.unit, .flags = lv.flags,
                     .active_profile_id = lv.profile_id};
    gatt_live_pack(&g, out);
}

static int on_command(uint16_t conn, struct ble_gatt_access_ctxt *ctxt)
{
    uint8_t buf[8];
    uint16_t len = 0;
    int rc = read_flat(ctxt, buf, sizeof(buf), &len);
    if (rc) {
        return rc;
    }
    gatt_cmd_t c;
    switch (gatt_cmd_parse(buf, len, &c)) {
    case GATT_CMD_OK: break;
    case GATT_CMD_ERR_OPCODE: return ERR_OPCODE;
    case GATT_CMD_ERR_LEN: return ERR_LEN;
    default: return ERR_VALUE;
    }
    switch (c.op) {
    case CALIPER_OP_ZERO: core_command(CORE_CMD_ZERO, 0); break;
    case CALIPER_OP_HOLD_TOGGLE: core_command(CORE_CMD_HOLD_TOGGLE, 0); break;
    case CALIPER_OP_RECORD_NOW: core_command(CORE_CMD_RECORD, 0); break;
    case CALIPER_OP_SET_UNIT: core_command(CORE_CMD_SET_UNIT, c.arg); break;
    case CALIPER_OP_LOG_READ: ble_worker_log_read(conn, c.arg); break;
    case CALIPER_OP_LOG_CLEAR: core_command(CORE_CMD_LOG_CLEAR, 0); break;
    case CALIPER_OP_SELECT_PROFILE: core_command(CORE_CMD_SELECT_PROFILE, c.arg); break;
    case CALIPER_OP_SET_TIME: core_command(CORE_CMD_SET_TIME, c.arg); break;
    default: return ERR_OPCODE;
    }
    return 0;
}

static int gatt_access(uint16_t conn, uint16_t attr, struct ble_gatt_access_ctxt *ctxt, void *arg)
{
    (void)arg;
    if (attr == g_h_live) {
        uint8_t b[CALIPER_LIVE_LEN];
        ble_gatt_pack_live(b);
        return append(ctxt, b, sizeof(b));
    }
    if (attr == s_h_cmd) {
        return on_command(conn, ctxt);
    }
    if (attr == g_h_log) {
        return BLE_ATT_ERR_READ_NOT_PERMITTED; /* notify only */
    }
    if (attr == s_h_settings) {
        if (ctxt->op == BLE_GATT_ACCESS_OP_READ_CHR) {
            char js[CALIPER_SETTINGS_MAX_LEN + 1];
            int n = core_settings_read_json(js, sizeof(js));
            return n < 0 ? BLE_ATT_ERR_UNLIKELY : append(ctxt, js, (size_t)n);
        }
        char js[CALIPER_SETTINGS_MAX_LEN + 1];
        uint16_t len = 0;
        int rc = read_flat(ctxt, js, CALIPER_SETTINGS_MAX_LEN, &len);
        if (rc) {
            return rc;
        }
        int s = core_settings_write_json(js, len);
        if (s != SETTINGS_OK) {
            ESP_LOGW(TAG, "settings write rejected (%d)", s);
            return s == SETTINGS_ERR_TOOBIG ? ERR_LEN : ERR_VALUE;
        }
        return 0;
    }
    if (attr == s_h_profiles) {
        if (ctxt->op == BLE_GATT_ACCESS_OP_READ_CHR) {
            uint8_t b[CALIPER_PROFILES_MAX * CALIPER_PROFILE_LEN];
            size_t n = core_profiles_read(b, sizeof(b));
            return append(ctxt, b, n);
        }
        uint8_t b[CALIPER_PROFILES_MAX * CALIPER_PROFILE_LEN];
        uint16_t len = 0;
        int rc = read_flat(ctxt, b, sizeof(b), &len);
        if (rc) {
            return rc;
        }
        esp_err_t e = core_profiles_write(b, len);
        if (e == ESP_ERR_INVALID_SIZE) {
            return ERR_LEN;
        }
        return e == ESP_OK ? 0 : ERR_VALUE;
    }
    return BLE_ATT_ERR_UNLIKELY;
}

static const struct ble_gatt_svc_def s_svcs[] = {
    {
        .type = BLE_GATT_SVC_TYPE_PRIMARY,
        .uuid = &s_uuid_svc.u,
        .characteristics = (struct ble_gatt_chr_def[]){
            {.uuid = &s_uuid_live.u, .access_cb = gatt_access,
             .flags = BLE_GATT_CHR_F_READ | BLE_GATT_CHR_F_NOTIFY, .val_handle = &g_h_live},
            {.uuid = &s_uuid_cmd.u, .access_cb = gatt_access, .flags = BLE_GATT_CHR_F_WRITE,
             .val_handle = &s_h_cmd},
            {.uuid = &s_uuid_log.u, .access_cb = gatt_access, .flags = BLE_GATT_CHR_F_NOTIFY,
             .val_handle = &g_h_log},
            /* writing SETTINGS can carry wifi_pass: the write needs an encrypted link (pairing) */
            {.uuid = &s_uuid_settings.u, .access_cb = gatt_access,
             .flags = BLE_GATT_CHR_F_READ | BLE_GATT_CHR_F_WRITE | BLE_GATT_CHR_F_WRITE_ENC,
             .val_handle = &s_h_settings},
            {.uuid = &s_uuid_profiles.u, .access_cb = gatt_access,
             .flags = BLE_GATT_CHR_F_READ | BLE_GATT_CHR_F_WRITE, .val_handle = &s_h_profiles},
            {0},
        },
    },
    {0},
};

int ble_gatt_register(void)
{
    int rc = ble_gatts_count_cfg(s_svcs);
    if (rc == 0) {
        rc = ble_gatts_add_svcs(s_svcs);
    }
    return rc;
}
