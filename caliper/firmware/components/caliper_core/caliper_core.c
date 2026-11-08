/* caliper_core: live state, commands, settings, profiles, statistics. */
#include "caliper_core.h"

#include <stdio.h>
#include <string.h>
#include <sys/time.h>
#include <time.h>

#include "caliper_gatt.h"
#include "capture.h"
#include "esp_attr.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "gatt_codec.h"
#include "store.h"

static const char *TAG = "core";

esp_err_t bus_init(void);

/* Capture modes (capture.h; the parameters are meas_cap_cfg_default()): SETTLE (the old auto-hold,
 * now the median of the still window) and SWEEP (min/max while in contact). Button presses blank
 * the capture from 50 ms before the debounced press to 100 ms after the release. */
#define CAPTURE_SAMPLE_MS 10 /* app_main sensor_task */
#define BLANK_BEFORE_MS   50
#define BLANK_AFTER_MS    100
/* Activity: a change of more than 20 um counts as use (resets auto-off). */
#define ACTIVITY_NM 20000
#define TIME_VALID_AFTER 1700000000u

/* The zero survives deep sleep (the sensor count is recovered by sensor_mag). */
#define ZH_MAGIC 0xCA11CA11u
RTC_DATA_ATTR static uint32_t s_zh_magic;
RTC_DATA_ATTR static meas_zh_t s_zh;

/* EXPERIMENTAL capacitive reading. Its unwrapper (sensor_cap) restarts at every boot, relative to
 * its first valid burst, so a cap zero kept across a deep sleep pointed into the old origin and the
 * reading came back off by a multiple of 2.54 mm (2026-11-07 review). The cap zero is therefore not
 * kept: after a boot, and after a ZERO taken while the cap had no valid burst, the first valid cap
 * burst is aligned to the magnetic reading ("seeded"); after that it moves on its own. A cap/mag
 * disagreement of more than a quarter pitch can only be a lost half-pitch in the cap unwrapper
 * (bursts are 40 ms apart, it tracks < 1.27 mm between them): whole half-pitches are taken back
 * out, the sub-half-pitch part stays the capacitive scale's own measurement. */
#define CAP_HALF_PITCH_NM 2540000 /* cap_demod.h CAP_HALF_PITCH_NM */
static int64_t s_cap_zero_nm;
static bool s_cap_seeded;

static SemaphoreHandle_t s_lock;
static cal_live_t s_live;
static int64_t s_raw_nm;
static int64_t s_cap_raw_nm;
static bool s_cap_ok;
static meas_capture_t s_cap;
static meas_cap_result_t s_capres; /* the shown capture result, refreshed with s_live */
static bool s_manual_hold;         /* HOLD froze the live value by hand; the capture waits */
static meas_stats_t s_stats;
static settings_t s_settings;
static store_state_t s_state;
static meas_profile_t s_profiles[CALIPER_PROFILES_MAX];
static size_t s_nprofiles;
static cal_status_t s_status;
static uint32_t s_last_activity_ms;
static int32_t s_activity_ref_nm;
static bool s_zero_from_rtc; /* the zero came from RTC memory: valid only if the count was recovered */
static bool s_need_zero;     /* CALIPER_FLAG_REZERO: the zero could not be carried over */

static void toast(const char *msg);

#define LOCK()   xSemaphoreTake(s_lock, portMAX_DELAY)
#define UNLOCK() xSemaphoreGive(s_lock)

static uint32_t now_ms(void)
{
    return (uint32_t)(esp_timer_get_time() / 1000);
}

static const meas_profile_t *active_profile_locked(void)
{
    for (size_t i = 0; i < s_nprofiles; i++) {
        if (s_profiles[i].id == s_state.profile_id) {
            return &s_profiles[i];
        }
    }
    return NULL;
}

static meas_fmt_t fmt_locked(void)
{
    return meas_fmt_for(s_state.unit ? MEAS_UNIT_INCH : MEAS_UNIT_MM, s_settings.decimals);
}

/* The capture result decides the hold: a frozen capture is a hold (old clients see HOLD and the
 * held value), anything else is not, unless HOLD froze the live value by hand. */
static void cap_sync_locked(void)
{
    meas_cap_result(&s_cap, &s_capres);
    if (s_manual_hold) {
        return;
    }
    s_zh.hold = s_capres.state == MEAS_CAPST_DONE;
    if (s_zh.hold) {
        s_zh.held_nm = s_capres.value_nm;
    }
}

/* Recomputes everything derived from the raw values. Caller holds the lock. */
static void refresh_locked(bool mag_ok)
{
    meas_fmt_t f = fmt_locked();
    cap_sync_locked();
    s_live.live_nm = meas_zh_value(&s_zh, s_raw_nm);
    if (s_zh.hold) {
        s_live.value_nm = s_zh.held_nm;
    } else if (s_capres.state == MEAS_CAPST_RUN && s_cap.mode == MEAS_CAP_SWEEP) {
        s_live.value_nm = s_capres.value_nm; /* the running extreme while in contact */
    } else {
        s_live.value_nm = s_live.live_nm;
    }
    bool cap_valid = s_cap_ok && s_cap_seeded;
    s_live.cap_nm = cap_valid ? meas_sat_i32(s_cap_raw_nm - s_cap_zero_nm) : CALIPER_CAP_INVALID;
    s_live.unit = s_state.unit;
    meas_format(s_live.value_nm, &f, s_live.text, sizeof(s_live.text));

    const meas_profile_t *p = active_profile_locked();
    /* go/no-go is decided on the displayed (rounded) value, like a hand-held gauge. In a capture
     * mode that is the judged statistic: SWEEP the selected extreme (live while in contact, final
     * when frozen), SETTLE the median; the other extreme is a misalignment artefact, not a size. */
    s_live.tol = meas_tol_check(p, meas_round_nm(s_live.value_nm, &f), &s_live.gauge);
    s_live.profile_id = p ? p->id : 0;
    if (p) {
        memcpy(s_live.profile_name, p->name, sizeof(s_live.profile_name));
    } else {
        s_live.profile_name[0] = '\0';
    }
    cal_capture_t *cp = &s_live.capture;
    cp->mode = (uint8_t)s_cap.mode;
    cp->sel = (uint8_t)s_cap.sel;
    cp->state = (uint8_t)s_capres.state;
    cp->which = s_capres.which;
    cp->manual_hold = s_manual_hold;
    cp->n = s_capres.n;
    cp->other_nm = s_capres.other_nm;
    cp->range_nm = s_capres.range_nm;
    cp->sd_nm = s_capres.sd_nm;

    uint8_t fl = s_live.flags & CALIPER_FLAG_CHARGING;
    if (s_zh.hold) fl |= CALIPER_FLAG_HOLD;
    if (meas_tol_is_pass(s_live.tol)) fl |= CALIPER_FLAG_TOL_PASS;
    if (meas_tol_is_fail(s_live.tol)) fl |= CALIPER_FLAG_TOL_FAIL;
    if (!mag_ok) fl |= CALIPER_FLAG_SENSOR_ERR;
    if (cap_valid) fl |= CALIPER_FLAG_CAP_VALID;
    if (s_need_zero) fl |= CALIPER_FLAG_REZERO;
    s_live.flags = fl;
}

void core_sample(int64_t raw_nm, bool mag_ok, int64_t cap_raw_nm, bool cap_ok, uint32_t t_ms)
{
    meas_cap_ev_t ev = MEAS_CAPEV_NONE;
    LOCK();
    s_raw_nm = raw_nm;
    s_cap_raw_nm = cap_raw_nm;
    s_cap_ok = cap_ok;
    int32_t live = meas_zh_value(&s_zh, raw_nm);
    if (cap_ok && mag_ok) {
        if (!s_cap_seeded) {
            s_cap_zero_nm = cap_raw_nm - live; /* the cap starts out reading what the magnetic scale reads */
            s_cap_seeded = true;
        } else {
            int64_t diff = (cap_raw_nm - s_cap_zero_nm) - live;
            if (diff > CAP_HALF_PITCH_NM / 2 || diff < -CAP_HALF_PITCH_NM / 2) {
                int64_t k = (diff + (diff >= 0 ? CAP_HALF_PITCH_NM / 2 : -CAP_HALF_PITCH_NM / 2)) / CAP_HALF_PITCH_NM;
                s_cap_zero_nm += k * CAP_HALF_PITCH_NM;
                ESP_LOGD(TAG, "cap unwrap re-aligned by %lld half-pitch(es)", (long long)k);
            }
        }
    }
    if (!s_manual_hold) {
        ev = meas_cap_update(&s_cap, live, mag_ok, t_ms);
    }
    int64_t d = (int64_t)live - s_activity_ref_nm;
    if (d > ACTIVITY_NM || d < -ACTIVITY_NM) {
        s_activity_ref_nm = live;
        s_last_activity_ms = t_ms;
    }
    refresh_locked(mag_ok);
    s_live.samples++;
    UNLOCK();
    if (ev == MEAS_CAPEV_DONE) {
        uint32_t ms = 30; /* "captured" */
        bus_post(CAL_EVT_BEEP, &ms, sizeof(ms));
    } else if (ev == MEAS_CAPEV_ABORT) {
        toast("Sensor error: capture dropped");
    }
    if (ev != MEAS_CAPEV_NONE) {
        bus_post(CAL_EVT_STATE, NULL, 0);
    }
}

void core_button_edge(bool down, uint32_t t_ms)
{
    if (!s_lock) {
        return;
    }
    LOCK();
    meas_cap_button(&s_cap, down, t_ms, BLANK_BEFORE_MS, BLANK_AFTER_MS);
    UNLOCK();
}

void core_mag_slip(void)
{
    if (!s_lock) {
        return;
    }
    LOCK();
    meas_cap_ev_t ev = s_manual_hold ? MEAS_CAPEV_NONE : meas_cap_slip(&s_cap);
    refresh_locked(!(s_live.flags & CALIPER_FLAG_SENSOR_ERR));
    UNLOCK();
    if (ev == MEAS_CAPEV_ABORT) {
        toast("Sensor slip: capture dropped");
        bus_post(CAL_EVT_STATE, NULL, 0);
    }
}

void core_get_live(cal_live_t *out)
{
    LOCK();
    *out = s_live;
    UNLOCK();
}

void core_get_stats(meas_stats_t *out)
{
    LOCK();
    *out = s_stats;
    UNLOCK();
}

int64_t core_zero_raw(void)
{
    return s_zh.zero_raw_nm;
}

void core_mag_origin(bool recovered, bool lost)
{
    LOCK();
    bool had_zero = s_zero_from_rtc;
    if (!recovered) {
        if (had_zero) {
            meas_zh_init(&s_zh); /* the stored zero belongs to the old origin */
            s_zh_magic = 0;
        }
        s_need_zero = had_zero || lost;
    }
    s_zero_from_rtc = false;
    bool need = s_need_zero;
    refresh_locked(!(s_live.flags & CALIPER_FLAG_SENSOR_ERR));
    UNLOCK();
    if (need) {
        ESP_LOGW(TAG, "position not recovered after sleep/reset: zero dropped, press ZERO");
        toast("Position lost: press ZERO");
        bus_post(CAL_EVT_STATE, NULL, 0);
    }
}

/* ---- commands ------------------------------------------------------------------------------ */

static void save_state(void)
{
    store_state_t st;
    LOCK();
    st = s_state;
    UNLOCK();
    store_state_save(&st);
}

static void toast(const char *msg)
{
    char m[32];
    strlcpy(m, msg, sizeof(m));
    bus_post(CAL_EVT_TOAST, m, sizeof(m));
}

static bool record(logrec_t *rec, cal_send_t *send)
{
    time_t now = time(NULL);
    LOCK();
    rec->unix_s = (uint32_t)now >= TIME_VALID_AFTER ? (uint32_t)now : 0;
    rec->value_nm = s_live.value_nm;
    rec->unit = s_live.unit;
    rec->flags = s_live.flags & (CALIPER_FLAG_HOLD | CALIPER_FLAG_TOL_PASS | CALIPER_FLAG_TOL_FAIL |
                                 CALIPER_FLAG_SENSOR_ERR | CALIPER_FLAG_REZERO);
    /* what the shown value is: a SETTLE median, a SWEEP extreme (frozen or running), or plain */
    rec->kind = CALIPER_LOG_KIND_PLAIN;
    rec->set_bits = 0;
    if (!s_manual_hold && s_capres.state == MEAS_CAPST_DONE && s_cap.mode == MEAS_CAP_SETTLE) {
        rec->kind = CALIPER_LOG_KIND_SETTLE;
    } else if (!s_manual_hold && s_cap.mode == MEAS_CAP_SWEEP &&
               (s_capres.state == MEAS_CAPST_DONE || s_capres.state == MEAS_CAPST_RUN)) {
        rec->kind = s_capres.which < 0 ? CALIPER_LOG_KIND_SWEEP_MIN : CALIPER_LOG_KIND_SWEEP_MAX;
    }
    rec->profile_id = s_live.profile_id;
    if (send) {
        snprintf(send->text, sizeof(send->text), "%s%s", s_live.text, s_settings.hid_suffix);
    }
    bool sensor_err = (s_live.flags & CALIPER_FLAG_SENSOR_ERR) != 0;
    UNLOCK();
    if (sensor_err) {
        toast("Sensor error: not saved");
        return false;
    }
    if (store_log_append(rec) != ESP_OK) {
        toast("Log write failed");
        return false;
    }
    LOCK();
    meas_stats_add(&s_stats, rec->value_nm);
    UNLOCK();
    return true;
}

static void select_profile(uint16_t id)
{
    LOCK();
    bool found = id == 0;
    for (size_t i = 0; i < s_nprofiles && !found; i++) {
        found = s_profiles[i].id == id;
    }
    if (found) {
        s_state.profile_id = id;
        refresh_locked(!(s_live.flags & CALIPER_FLAG_SENSOR_ERR));
    }
    UNLOCK();
    if (found) {
        save_state();
        bus_post(CAL_EVT_STATE, NULL, 0);
    } else {
        toast("No such profile");
    }
}

static void run_command(const core_cmd_msg_t *m)
{
    switch (m->cmd) {
    case CORE_CMD_ZERO:
        LOCK();
        meas_zh_zero(&s_zh, s_raw_nm);
        meas_cap_reset(&s_cap); /* a capture spanning a zero shift means nothing */
        s_cap_zero_nm = s_cap_raw_nm;
        s_cap_seeded = s_cap_ok; /* no valid burst now: the next one is seeded from the new zero */
        s_zh_magic = ZH_MAGIC;
        s_need_zero = false;
        refresh_locked(!(s_live.flags & CALIPER_FLAG_SENSOR_ERR));
        UNLOCK();
        bus_post(CAL_EVT_STATE, NULL, 0);
        break;
    case CORE_CMD_HOLD_TOGGLE:
        LOCK();
        if (s_manual_hold) {
            /* release a hand hold; in a capture mode it also re-arms */
            s_manual_hold = false;
            s_zh.hold = false;
            meas_cap_reset(&s_cap);
        } else if (s_cap.mode == MEAS_CAP_LIVE ||
                   meas_cap_hold_press(&s_cap) == MEAS_CAP_HOLD_MANUAL) {
            /* nothing captured or running: freeze the live value by hand (stays until HOLD) */
            s_manual_hold = true;
            s_zh.hold = false;
            meas_zh_set_hold(&s_zh, true, s_raw_nm);
        }
        /* else: a running capture was frozen, or a frozen one cleared and re-armed */
        refresh_locked(!(s_live.flags & CALIPER_FLAG_SENSOR_ERR));
        UNLOCK();
        bus_post(CAL_EVT_STATE, NULL, 0);
        break;
    case CORE_CMD_RECORD:
    case CORE_CMD_SEND: {
        logrec_t rec;
        cal_send_t send;
        if (record(&rec, m->cmd == CORE_CMD_SEND ? &send : NULL)) {
            bus_post(CAL_EVT_RECORDED, &rec, sizeof(rec));
            if (m->cmd == CORE_CMD_SEND) {
                bus_post(CAL_EVT_SEND, &send, sizeof(send));
            }
            uint32_t ms = 15;
            bus_post(CAL_EVT_BEEP, &ms, sizeof(ms));
        }
        break;
    }
    case CORE_CMD_SET_UNIT:
    case CORE_CMD_TOGGLE_UNIT:
        LOCK();
        s_state.unit = m->cmd == CORE_CMD_SET_UNIT ? (m->arg ? 1 : 0) : (uint8_t)!s_state.unit;
        refresh_locked(!(s_live.flags & CALIPER_FLAG_SENSOR_ERR));
        UNLOCK();
        save_state();
        bus_post(CAL_EVT_STATE, NULL, 0);
        break;
    case CORE_CMD_LOG_CLEAR:
        if (store_log_clear() == ESP_OK) {
            bus_post(CAL_EVT_LOG_CLEARED, NULL, 0);
            toast("Log cleared");
        }
        break;
    case CORE_CMD_SELECT_PROFILE:
        select_profile((uint16_t)m->arg);
        break;
    case CORE_CMD_NEXT_PROFILE: {
        LOCK();
        uint16_t next = s_nprofiles ? s_profiles[0].id : 0;
        for (size_t i = 0; i < s_nprofiles; i++) {
            if (s_profiles[i].id == s_state.profile_id) {
                next = i + 1 < s_nprofiles ? s_profiles[i + 1].id : 0;
            }
        }
        UNLOCK();
        select_profile(next);
        break;
    }
    case CORE_CMD_SET_TIME: {
        struct timeval tv = {.tv_sec = (time_t)m->arg, .tv_usec = 0};
        settimeofday(&tv, NULL);
        ESP_LOGI(TAG, "time set to %lu", (unsigned long)m->arg);
        break;
    }
    case CORE_CMD_STATS_RESET:
        LOCK();
        meas_stats_reset(&s_stats);
        UNLOCK();
        toast("Stats reset");
        break;
    case CORE_CMD_SET_CAPTURE:
    case CORE_CMD_CAPTURE_NEXT:
    case CORE_CMD_SWEEP_SEL_NEXT: {
        LOCK();
        meas_cap_mode_t mode = s_cap.mode;
        meas_sweep_sel_t sel = s_cap.sel;
        if (m->cmd == CORE_CMD_SET_CAPTURE) {
            mode = (meas_cap_mode_t)(m->arg & 0xFFu);
            sel = (meas_sweep_sel_t)((m->arg >> 8) & 0xFFu);
        } else if (m->cmd == CORE_CMD_CAPTURE_NEXT) {
            mode = (meas_cap_mode_t)((mode + 1) % (MEAS_CAP_SWEEP + 1)); /* SET is not offered */
        } else {
            sel = (meas_sweep_sel_t)((sel + 1) % MEAS_SWEEP_SELS);
        }
        bool ok = true;
        if (mode != s_cap.mode) {
            ok = meas_cap_set_mode(&s_cap, mode, sel);
            if (ok) {
                s_manual_hold = false;
                s_zh.hold = false;
            }
        } else if ((unsigned)sel < MEAS_SWEEP_SELS) {
            meas_cap_set_sel(&s_cap, sel); /* both extremes are kept: a frozen result re-renders */
        } else {
            ok = false;
        }
        if (ok) {
            s_state.capture = (uint8_t)s_cap.mode;
            s_state.sweep_sel = (uint8_t)s_cap.sel;
        }
        refresh_locked(!(s_live.flags & CALIPER_FLAG_SENSOR_ERR));
        UNLOCK();
        if (ok) {
            save_state();
            bus_post(CAL_EVT_STATE, NULL, 0);
        } else {
            toast("Capture mode not available");
        }
        break;
    }
    case CORE_CMD_CAPTURE_RESET:
        LOCK();
        s_manual_hold = false;
        s_zh.hold = false;
        meas_cap_reset(&s_cap);
        refresh_locked(!(s_live.flags & CALIPER_FLAG_SENSOR_ERR));
        UNLOCK();
        bus_post(CAL_EVT_STATE, NULL, 0);
        break;
    case CORE_CMD_SLEEP:
        bus_post(CAL_EVT_SLEEP, NULL, 0);
        break;
    case CORE_CMD_WIFI:
        bus_post(CAL_EVT_WIFI, &m->arg, sizeof(m->arg));
        break;
    }
}

static void on_cmd(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
    (void)base;
    (void)id;
    run_command((const core_cmd_msg_t *)data);
}

esp_err_t core_command(core_cmd_t cmd, uint32_t arg)
{
    core_activity();
    core_cmd_msg_t m = {.cmd = cmd, .arg = arg};
    return bus_post(CAL_EVT_CMD, &m, sizeof(m));
}

/* ---- settings ------------------------------------------------------------------------------ */

void core_get_settings(settings_t *out)
{
    LOCK();
    *out = s_settings;
    UNLOCK();
}

static int commit_settings(const settings_t *s)
{
    if (store_settings_save(s) != ESP_OK) {
        return SETTINGS_ERR_VALUE;
    }
    LOCK();
    s_settings = *s;
    refresh_locked(!(s_live.flags & CALIPER_FLAG_SENSOR_ERR));
    UNLOCK();
    bus_post(CAL_EVT_SETTINGS, NULL, 0);
    return SETTINGS_OK;
}

int core_settings_write_json(const char *json, size_t len)
{
    settings_t s;
    core_get_settings(&s);
    int rc = settings_from_json(&s, json, len);
    return rc == SETTINGS_OK ? commit_settings(&s) : rc;
}

int core_settings_set(const char *key, const char *value)
{
    settings_t s;
    core_get_settings(&s);
    int rc = settings_set_kv(&s, key, value);
    return rc == SETTINGS_OK ? commit_settings(&s) : rc;
}

int core_settings_read_json(char *buf, size_t n)
{
    settings_t s;
    core_get_settings(&s);
    return settings_to_json(&s, buf, n);
}

/* ---- profiles ------------------------------------------------------------------------------ */

size_t core_get_profiles(meas_profile_t *out, size_t max)
{
    LOCK();
    size_t n = s_nprofiles < max ? s_nprofiles : max;
    memcpy(out, s_profiles, n * sizeof(*out));
    UNLOCK();
    return n;
}

size_t core_profiles_read(uint8_t *buf, size_t max)
{
    size_t used = 0;
    LOCK();
    for (size_t i = 0; i < s_nprofiles && used + CALIPER_PROFILE_LEN <= max; i++) {
        gatt_profile_pack(&s_profiles[i], buf + used);
        used += CALIPER_PROFILE_LEN;
    }
    UNLOCK();
    return used;
}

esp_err_t core_profiles_write(const uint8_t *buf, size_t len)
{
    if (len == 0 || len % CALIPER_PROFILE_LEN != 0) {
        return ESP_ERR_INVALID_SIZE;
    }
    meas_profile_t tmp[CALIPER_PROFILES_MAX];
    LOCK();
    size_t n = s_nprofiles;
    memcpy(tmp, s_profiles, sizeof(tmp));
    UNLOCK();
    for (size_t off = 0; off < len; off += CALIPER_PROFILE_LEN) {
        meas_profile_t p;
        gatt_profile_unpack(buf + off, &p);
        if (p.id == 0) {
            return ESP_ERR_INVALID_ARG;
        }
        size_t i = 0;
        while (i < n && tmp[i].id != p.id) {
            i++;
        }
        if (gatt_profile_is_delete(&p)) {
            if (i < n) {
                memmove(&tmp[i], &tmp[i + 1], (n - i - 1) * sizeof(tmp[0]));
                n--;
            }
        } else if (i < n) {
            tmp[i] = p;
        } else if (n < CALIPER_PROFILES_MAX) {
            tmp[n++] = p;
        } else {
            return ESP_ERR_NO_MEM;
        }
    }
    esp_err_t err = store_profiles_save(tmp, n);
    if (err != ESP_OK) {
        return err;
    }
    LOCK();
    memcpy(s_profiles, tmp, sizeof(tmp));
    s_nprofiles = n;
    refresh_locked(!(s_live.flags & CALIPER_FLAG_SENSOR_ERR));
    UNLOCK();
    bus_post(CAL_EVT_PROFILES, NULL, 0);
    return ESP_OK;
}

/* ---- status -------------------------------------------------------------------------------- */

void core_get_status(cal_status_t *out)
{
    LOCK();
    *out = s_status;
    UNLOCK();
}

void core_set_power(uint8_t pct, uint16_t mv, bool charging, bool vbus)
{
    LOCK();
    s_status.battery_pct = pct;
    s_status.battery_mv = mv;
    s_status.charging = charging;
    s_status.vbus = vbus;
    if (charging) {
        s_live.flags |= CALIPER_FLAG_CHARGING;
    } else {
        s_live.flags &= (uint8_t)~CALIPER_FLAG_CHARGING;
    }
    UNLOCK();
}

void core_set_usb_host(bool host)
{
    LOCK();
    s_status.usb_host = host;
    UNLOCK();
}

void core_set_ble(bool connected)
{
    LOCK();
    s_status.ble_connected = connected;
    UNLOCK();
}

void core_set_wifi(uint8_t state, const char *ip, const char *ap_ssid, const char *ap_pass)
{
    LOCK();
    s_status.wifi = state;
    strlcpy(s_status.ip, ip ? ip : "", sizeof(s_status.ip));
    strlcpy(s_status.ap_ssid, ap_ssid ? ap_ssid : "", sizeof(s_status.ap_ssid));
    strlcpy(s_status.ap_pass, ap_pass ? ap_pass : "", sizeof(s_status.ap_pass));
    UNLOCK();
}

void core_activity(void)
{
    s_last_activity_ms = now_ms();
}

uint32_t core_idle_ms(void)
{
    return now_ms() - s_last_activity_ms;
}

/* ---- init ---------------------------------------------------------------------------------- */

esp_err_t core_init(void)
{
    s_lock = xSemaphoreCreateMutex();
    if (!s_lock) {
        return ESP_ERR_NO_MEM;
    }
    ESP_ERROR_CHECK(bus_init());
    if (s_zh_magic != ZH_MAGIC) {
        meas_zh_init(&s_zh); /* cold boot: zero = sensor origin until ZERO is pressed */
    } else {
        s_zh.hold = false; /* waking up never shows a stale held value */
        s_zero_from_rtc = true; /* until core_mag_origin() confirms the count was recovered */
    }
    store_settings_load(&s_settings);
    store_state_load(&s_state);
    s_nprofiles = store_profiles_load(s_profiles, CALIPER_PROFILES_MAX);
    meas_cap_cfg_t cc;
    meas_cap_cfg_default(&cc);
    cc.sample_ms = CAPTURE_SAMPLE_MS;
    meas_cap_init(&s_cap, &cc, MEAS_CAP_LIVE, MEAS_SWEEP_AUTO);
    if (!meas_cap_set_mode(&s_cap, (meas_cap_mode_t)s_state.capture, (meas_sweep_sel_t)s_state.sweep_sel)) {
        s_state.capture = CALIPER_CAPTURE_LIVE;
        s_state.sweep_sel = CALIPER_SWEEP_AUTO;
    }
    meas_stats_reset(&s_stats);
    s_live.cap_nm = CALIPER_CAP_INVALID;
    s_last_activity_ms = now_ms();
    refresh_locked(false);
    ESP_ERROR_CHECK(bus_subscribe(CAL_EVT_CMD, on_cmd, NULL));
    ESP_LOGI(TAG, "unit %s, %u profiles, active %u, capture %u/%u, %lu log records", s_state.unit ? "in" : "mm",
             (unsigned)s_nprofiles, (unsigned)s_state.profile_id, (unsigned)s_state.capture,
             (unsigned)s_state.sweep_sel, (unsigned long)store_log_count());

    return ESP_OK;
}
