/* Standard services: Battery (0x180F), Device Information (0x180A), HID over GATT (0x1812). */
#include <string.h>

#include "ble.h"
#include "caliper_core.h"
#include "caliper_gatt.h"
#include "esp_app_desc.h"
#include "host/ble_hs.h"

uint16_t g_h_hid_input, g_h_battery;
static uint16_t s_h_hid_output;
static uint8_t s_protocol_mode = 1; /* report protocol */
static uint8_t s_kbd_leds;

/* Keyboard, report ID 1: 8-byte input {mod, 0, k1..k6}, 1-byte LED output. */
static const uint8_t s_report_map[] = {
    0x05, 0x01, 0x09, 0x06, 0xA1, 0x01, 0x85, 0x01,             /* Usage Page Desktop, Keyboard, Report ID 1 */
    0x05, 0x07, 0x19, 0xE0, 0x29, 0xE7, 0x15, 0x00, 0x25, 0x01, /* modifiers */
    0x75, 0x01, 0x95, 0x08, 0x81, 0x02,
    0x95, 0x01, 0x75, 0x08, 0x81, 0x01,                         /* reserved */
    0x95, 0x05, 0x75, 0x01, 0x05, 0x08, 0x19, 0x01, 0x29, 0x05, 0x91, 0x02, /* LEDs */
    0x95, 0x01, 0x75, 0x03, 0x91, 0x01,
    0x95, 0x06, 0x75, 0x08, 0x15, 0x00, 0x25, 0x65, 0x05, 0x07, 0x19, 0x00, 0x29, 0x65, 0x81, 0x00, /* keys */
    0xC0,
};

static const uint8_t s_hid_info[4] = {0x11, 0x01, 0x00, 0x02}; /* bcdHID 1.11, country 0, normally connectable */
static const uint8_t s_ref_input[2] = {0x01, 0x01};  /* report ID 1, input */
static const uint8_t s_ref_output[2] = {0x01, 0x02}; /* report ID 1, output */
/* PnP ID: USB VID source, Espressif VID 0x303A, product 0x4001 (placeholder), version 1.0 */
static const uint8_t s_pnp_id[7] = {0x02, 0x3A, 0x30, 0x01, 0x40, 0x00, 0x01};

enum { A_BAT, A_MFR, A_MODEL, A_FW, A_PNP, A_PROTO, A_MAP, A_INFO, A_CTRL, A_IN, A_OUT, A_REF_IN, A_REF_OUT };

static int append(struct ble_gatt_access_ctxt *ctxt, const void *d, size_t n)
{
    return os_mbuf_append(ctxt->om, d, n) == 0 ? 0 : BLE_ATT_ERR_INSUFFICIENT_RES;
}

static int std_access(uint16_t conn, uint16_t attr, struct ble_gatt_access_ctxt *ctxt, void *arg)
{
    (void)conn;
    (void)attr;
    int which = (int)(intptr_t)arg;
    bool is_read = ctxt->op == BLE_GATT_ACCESS_OP_READ_CHR || ctxt->op == BLE_GATT_ACCESS_OP_READ_DSC;
    switch (which) {
    case A_BAT: {
        cal_status_t st;
        core_get_status(&st);
        return append(ctxt, &st.battery_pct, 1);
    }
    case A_MFR: return append(ctxt, "PrettyCool", 10);
    case A_MODEL: return append(ctxt, "Caliper rev A", 13);
    case A_FW: {
        const char *v = esp_app_get_description()->version;
        return append(ctxt, v, strlen(v));
    }
    case A_PNP: return append(ctxt, s_pnp_id, sizeof(s_pnp_id));
    case A_PROTO:
        if (is_read) {
            return append(ctxt, &s_protocol_mode, 1);
        }
        if (OS_MBUF_PKTLEN(ctxt->om) != 1) {
            return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
        }
        ble_hs_mbuf_to_flat(ctxt->om, &s_protocol_mode, 1, NULL);
        return 0;
    case A_MAP: return append(ctxt, s_report_map, sizeof(s_report_map));
    case A_INFO: return append(ctxt, s_hid_info, sizeof(s_hid_info));
    case A_CTRL: return 0; /* suspend / exit suspend: nothing to do */
    case A_IN: {
        static const uint8_t empty[8] = {0};
        return append(ctxt, empty, sizeof(empty));
    }
    case A_OUT:
        if (is_read) {
            return append(ctxt, &s_kbd_leds, 1);
        }
        ble_hs_mbuf_to_flat(ctxt->om, &s_kbd_leds, 1, NULL);
        return 0;
    case A_REF_IN: return append(ctxt, s_ref_input, sizeof(s_ref_input));
    case A_REF_OUT: return append(ctxt, s_ref_output, sizeof(s_ref_output));
    default: return BLE_ATT_ERR_UNLIKELY;
    }
}

#define ARG(x) ((void *)(intptr_t)(x))

static const struct ble_gatt_svc_def s_std_svcs[] = {
    {
        .type = BLE_GATT_SVC_TYPE_PRIMARY,
        .uuid = BLE_UUID16_DECLARE(CALIPER_UUID16_BAS),
        .characteristics = (struct ble_gatt_chr_def[]){
            {.uuid = BLE_UUID16_DECLARE(0x2A19), .access_cb = std_access, .arg = ARG(A_BAT),
             .flags = BLE_GATT_CHR_F_READ | BLE_GATT_CHR_F_NOTIFY, .val_handle = &g_h_battery},
            {0},
        },
    },
    {
        .type = BLE_GATT_SVC_TYPE_PRIMARY,
        .uuid = BLE_UUID16_DECLARE(CALIPER_UUID16_DIS),
        .characteristics = (struct ble_gatt_chr_def[]){
            {.uuid = BLE_UUID16_DECLARE(0x2A29), .access_cb = std_access, .arg = ARG(A_MFR), .flags = BLE_GATT_CHR_F_READ},
            {.uuid = BLE_UUID16_DECLARE(0x2A24), .access_cb = std_access, .arg = ARG(A_MODEL), .flags = BLE_GATT_CHR_F_READ},
            {.uuid = BLE_UUID16_DECLARE(0x2A26), .access_cb = std_access, .arg = ARG(A_FW), .flags = BLE_GATT_CHR_F_READ},
            {.uuid = BLE_UUID16_DECLARE(0x2A50), .access_cb = std_access, .arg = ARG(A_PNP), .flags = BLE_GATT_CHR_F_READ},
            {0},
        },
    },
    {
        .type = BLE_GATT_SVC_TYPE_PRIMARY,
        .uuid = BLE_UUID16_DECLARE(CALIPER_UUID16_HID),
        .characteristics = (struct ble_gatt_chr_def[]){
            {.uuid = BLE_UUID16_DECLARE(0x2A4E), .access_cb = std_access, .arg = ARG(A_PROTO),
             .flags = BLE_GATT_CHR_F_READ | BLE_GATT_CHR_F_READ_ENC | BLE_GATT_CHR_F_WRITE_NO_RSP |
                      BLE_GATT_CHR_F_WRITE_ENC},
            {.uuid = BLE_UUID16_DECLARE(0x2A4B), .access_cb = std_access, .arg = ARG(A_MAP),
             .flags = BLE_GATT_CHR_F_READ | BLE_GATT_CHR_F_READ_ENC},
            {.uuid = BLE_UUID16_DECLARE(0x2A4A), .access_cb = std_access, .arg = ARG(A_INFO),
             .flags = BLE_GATT_CHR_F_READ | BLE_GATT_CHR_F_READ_ENC},
            {.uuid = BLE_UUID16_DECLARE(0x2A4C), .access_cb = std_access, .arg = ARG(A_CTRL),
             .flags = BLE_GATT_CHR_F_WRITE_NO_RSP | BLE_GATT_CHR_F_WRITE_ENC},
            {.uuid = BLE_UUID16_DECLARE(0x2A4D), .access_cb = std_access, .arg = ARG(A_IN),
             .flags = BLE_GATT_CHR_F_READ | BLE_GATT_CHR_F_READ_ENC | BLE_GATT_CHR_F_NOTIFY,
             .val_handle = &g_h_hid_input,
             .descriptors = (struct ble_gatt_dsc_def[]){
                 {.uuid = BLE_UUID16_DECLARE(0x2908), .att_flags = BLE_ATT_F_READ | BLE_ATT_F_READ_ENC,
                  .access_cb = std_access, .arg = ARG(A_REF_IN)},
                 {0},
             }},
            {.uuid = BLE_UUID16_DECLARE(0x2A4D), .access_cb = std_access, .arg = ARG(A_OUT),
             .flags = BLE_GATT_CHR_F_READ | BLE_GATT_CHR_F_READ_ENC | BLE_GATT_CHR_F_WRITE |
                      BLE_GATT_CHR_F_WRITE_NO_RSP | BLE_GATT_CHR_F_WRITE_ENC,
             .val_handle = &s_h_hid_output,
             .descriptors = (struct ble_gatt_dsc_def[]){
                 {.uuid = BLE_UUID16_DECLARE(0x2908), .att_flags = BLE_ATT_F_READ | BLE_ATT_F_READ_ENC,
                  .access_cb = std_access, .arg = ARG(A_REF_OUT)},
                 {0},
             }},
            {0},
        },
    },
    {0},
};

int ble_std_register(void)
{
    int rc = ble_gatts_count_cfg(s_std_svcs);
    if (rc == 0) {
        rc = ble_gatts_add_svcs(s_std_svcs);
    }
    return rc;
}
