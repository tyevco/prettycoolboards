/*
 * caliper_core: the application state shared by every front end (display, BLE, Wi-Fi, USB).
 *
 *  - an event bus: a dedicated esp_event loop with its own task ("bus")
 *  - the live reading: written by the sensor task (core_sample), read by anyone (core_get_live)
 *  - commands (zero, hold, record, send, unit, profile, ...): posted from any task with
 *    core_command() and executed in order on the bus task
 *  - settings, tolerance profiles and running statistics
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "capture.h"
#include "esp_err.h"
#include "esp_event.h"
#include "logrec.h"
#include "measure.h"
#include "settings.h"

#ifdef __cplusplus
extern "C" {
#endif

ESP_EVENT_DECLARE_BASE(CALIPER_EVENT);

typedef enum {
    CAL_EVT_CMD = 0,     /* internal: core_cmd_msg_t */
    CAL_EVT_RECORDED,    /* logrec_t: a reading was stored */
    CAL_EVT_SEND,        /* cal_send_t: type this text over BLE HID */
    CAL_EVT_STATE,       /* unit / hold / zero / profile / capture changed (no payload) */
    CAL_EVT_SETTINGS,    /* settings changed (no payload) */
    CAL_EVT_PROFILES,    /* profile list changed (no payload) */
    CAL_EVT_LOG_CLEARED, /* no payload */
    CAL_EVT_TOAST,       /* char[32]: a short message for the display */
    CAL_EVT_SLEEP,       /* deep sleep requested (no payload) */
    CAL_EVT_WIFI,        /* uint32_t: CAL_WIFI_OFF / CAL_WIFI_ON / CAL_WIFI_PROVISION */
    CAL_EVT_BEEP,        /* uint32_t: duration in ms */
} cal_evt_t;

enum { CAL_WIFI_OFF = 0, CAL_WIFI_ON = 1, CAL_WIFI_PROVISION = 2, CAL_WIFI_TOGGLE = 3 };

typedef enum {
    CORE_CMD_ZERO = 0,
    CORE_CMD_HOLD_TOGGLE,
    CORE_CMD_RECORD,         /* store the shown value */
    CORE_CMD_SEND,           /* store + type it over BLE HID */
    CORE_CMD_SET_UNIT,       /* arg: 0 mm, 1 inch */
    CORE_CMD_TOGGLE_UNIT,
    CORE_CMD_LOG_CLEAR,
    CORE_CMD_SELECT_PROFILE, /* arg: profile id, 0 = none */
    CORE_CMD_NEXT_PROFILE,
    CORE_CMD_SET_TIME,       /* arg: unix seconds */
    CORE_CMD_STATS_RESET,
    CORE_CMD_SET_CAPTURE,    /* arg: mode (CALIPER_CAPTURE_*) | sweep selection (CALIPER_SWEEP_*) << 8 */
    CORE_CMD_CAPTURE_NEXT,   /* the menu: Off -> Settle -> Sweep -> Off */
    CORE_CMD_SWEEP_SEL_NEXT, /* the menu: Auto -> Min -> Max (re-renders a frozen result) */
    CORE_CMD_CAPTURE_RESET,  /* clear the capture result and re-arm */
    CORE_CMD_SLEEP,
    CORE_CMD_WIFI,           /* arg: CAL_WIFI_* */
} core_cmd_t;

typedef struct {
    core_cmd_t cmd;
    uint32_t arg;
} core_cmd_msg_t;

typedef struct {
    char text[28]; /* the formatted reading + hid_suffix */
} cal_send_t;

/* The capture shown with the reading (capture.h): what the display, LIVE v3 and the log use. */
typedef struct {
    uint8_t mode;      /* CALIPER_CAPTURE_* (= meas_cap_mode_t) */
    uint8_t sel;       /* CALIPER_SWEEP_* (= meas_sweep_sel_t) */
    uint8_t state;     /* CALIPER_CAPST_* (= meas_cap_state_t) */
    int8_t which;      /* SWEEP: -1 MIN, +1 MAX, else 0 */
    bool manual_hold;  /* HOLD froze the live value by hand (the capture is paused) */
    uint32_t n;
    int32_t other_nm;  /* SWEEP: the other extreme */
    int32_t range_nm;  /* SWEEP: max - min; SETTLE: the window's max - min */
    int32_t sd_nm;     /* SETTLE: the window's standard deviation */
} cal_capture_t;

typedef struct {
    int32_t value_nm;  /* shown value (the held value while holding), zeroed */
    int32_t live_nm;   /* zeroed live magnetic value */
    int32_t cap_nm;    /* zeroed capacitive value, or INT32_MIN */
    uint8_t unit;      /* 0 mm, 1 inch */
    uint8_t flags;     /* CALIPER_FLAG_* */
    meas_tol_t tol;
    int32_t gauge;     /* -1500..1500, see meas_tol_check */
    char text[16];     /* value_nm formatted in the current unit */
    uint16_t profile_id;
    char profile_name[MEAS_PROFILE_NAME_LEN + 1];
    cal_capture_t capture;
    uint32_t samples;
} cal_live_t;

typedef struct {
    uint8_t battery_pct;
    uint16_t battery_mv;
    bool charging;
    bool vbus;
    bool usb_host;     /* enumerated by a USB host */
    bool ble_connected;
    uint8_t wifi;      /* 0 off, 1 connecting, 2 station up, 3 provisioning AP */
    char ip[16];
    char ap_ssid[24];
    char ap_pass[12];
} cal_status_t;

/* ---- lifecycle ---- */
esp_err_t core_init(void); /* after store_init() */

/* ---- event bus ---- */
esp_err_t bus_post(cal_evt_t id, const void *data, size_t len);
esp_err_t bus_subscribe(cal_evt_t id, esp_event_handler_t handler, void *arg); /* id -1 = all */

/* ---- live data ---- */
/* Called by the sensor task for every sample. raw_nm: un-zeroed magnetic position. */
void core_sample(int64_t raw_nm, bool mag_ok, int64_t cap_raw_nm, bool cap_ok, uint32_t t_ms);
void core_get_live(cal_live_t *out);
/* Debounced button edges from the button task: samples taken while a button is pressed (it lifts
 * the slider pads) are kept out of a capture. */
void core_button_edge(bool down, uint32_t t_ms);
/* The sensor applied a confirmed count-slip correction (the position stepped): a running SWEEP
 * capture is dropped, a SETTLE still window restarts. Called by the sensor task before core_sample(). */
void core_mag_slip(void);
void core_get_stats(meas_stats_t *out);
/* The zero point, kept in RTC memory across deep sleep. */
int64_t core_zero_raw(void);
/* Call once after sensor_mag_init(). recovered: the AS5311 count continues from before the deep
 * sleep, so the zero kept in RTC memory still applies. Otherwise that zero is dropped, and if one
 * had been set, or lost (woke from deep sleep but the position could not be recovered), LIVE and
 * the display carry CALIPER_FLAG_REZERO until ZERO is pressed. */
void core_mag_origin(bool recovered, bool lost);

/* ---- commands ---- */
esp_err_t core_command(core_cmd_t cmd, uint32_t arg);

/* ---- settings ---- */
void core_get_settings(settings_t *out);
int core_settings_write_json(const char *json, size_t len); /* SETTINGS_OK or SETTINGS_ERR_* */
int core_settings_set(const char *key, const char *value);
int core_settings_read_json(char *buf, size_t n);

/* ---- profiles ---- */
size_t core_get_profiles(meas_profile_t *out, size_t max);
/* PROFILES characteristic: read packs every profile; write upserts (or deletes) each record. */
size_t core_profiles_read(uint8_t *buf, size_t max);
esp_err_t core_profiles_write(const uint8_t *buf, size_t len);

/* ---- status shown on the display / web ---- */
void core_get_status(cal_status_t *out);
void core_set_power(uint8_t pct, uint16_t mv, bool charging, bool vbus);
void core_set_usb_host(bool host);
void core_set_ble(bool connected);
void core_set_wifi(uint8_t state, const char *ip, const char *ap_ssid, const char *ap_pass);

/* ---- activity (auto-off) ---- */
void core_activity(void);
uint32_t core_idle_ms(void);

#ifdef __cplusplus
}
#endif
