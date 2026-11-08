/* LVGL screens. Everything here runs with the LVGL lock held (ui_lock) or in LVGL timers. */
#include <stdio.h>
#include <string.h>

#include "caliper_core.h"
#include "caliper_gatt.h"
#include "esp_app_desc.h"
#include "lvgl.h"
#include "measure.h"
#include "ui.h"

#define REFRESH_MS    40  /* 25 Hz label refresh */
#define CHART_MS      100 /* 10 Hz chart samples */
#define CHART_POINTS  100
#define TOAST_MS      1500

#define C_BG     lv_color_black()
#define C_TEXT   lv_color_white()
#define C_DIM    lv_color_hex(0x8a8f98)
#define C_GREEN  lv_color_hex(0x22c55e)
#define C_AMBER  lv_color_hex(0xf59e0b)
#define C_RED    lv_color_hex(0xef4444)
#define C_ACCENT lv_color_hex(0x38bdf8)

static lv_obj_t *s_scr[UI_SCR_COUNT];
static ui_screen_t s_cur;

/* main. s_tag (top left): HOLD / ZERO? / the capture mode and state. s_line (under the reading): the
 * capture's other extreme, range and count, the SETTLE spread, or the capacitive reading. */
static lv_obj_t *s_value, *s_unit, *s_tag, *s_status, *s_profile, *s_gauge, *s_line;
/* chart */
static lv_obj_t *s_chart, *s_chart_lbl;
static lv_chart_series_t *s_series;
static int32_t s_chart_min = INT32_MAX, s_chart_max = INT32_MIN;
static int32_t s_chart_buf[CHART_POINTS];
static int s_chart_n;
/* stats */
static lv_obj_t *s_stats_lbl;
/* menu */
static lv_obj_t *s_menu_items[UI_MENU_COUNT];
static int s_menu_sel;
/* overlay */
static lv_obj_t *s_toast;
static lv_timer_t *s_toast_timer;
static lv_obj_t *s_prov;

static lv_obj_t *new_screen(void)
{
    lv_obj_t *s = lv_obj_create(NULL);
    lv_obj_set_style_bg_color(s, C_BG, 0);
    lv_obj_set_style_bg_opa(s, LV_OPA_COVER, 0);
    lv_obj_set_style_text_color(s, C_TEXT, 0);
    lv_obj_remove_flag(s, LV_OBJ_FLAG_SCROLLABLE);
    return s;
}

static lv_obj_t *label(lv_obj_t *parent, const lv_font_t *font, lv_color_t color, lv_align_t align, int32_t x,
                       int32_t y)
{
    lv_obj_t *l = lv_label_create(parent);
    lv_obj_set_style_text_font(l, font, 0);
    lv_obj_set_style_text_color(l, color, 0);
    lv_label_set_text(l, "");
    lv_obj_align(l, align, x, y);
    return l;
}

/* extra: digits beyond the reading's (R and sigma take one more, from the exact nm value) */
static void fmt_nm_x(int32_t nm, uint8_t unit, uint8_t extra, char *buf, size_t n)
{
    settings_t st;
    core_get_settings(&st);
    meas_fmt_t f = meas_fmt_for(unit ? MEAS_UNIT_INCH : MEAS_UNIT_MM, (uint8_t)(st.decimals + extra));
    meas_format(nm, &f, buf, n);
}

static void fmt_nm(int32_t nm, uint8_t unit, char *buf, size_t n)
{
    fmt_nm_x(nm, unit, 0, buf, n);
}

static const char *battery_symbol(uint8_t pct)
{
    if (pct >= 85) return LV_SYMBOL_BATTERY_FULL;
    if (pct >= 60) return LV_SYMBOL_BATTERY_3;
    if (pct >= 35) return LV_SYMBOL_BATTERY_2;
    if (pct >= 10) return LV_SYMBOL_BATTERY_1;
    return LV_SYMBOL_BATTERY_EMPTY;
}

/* ---- refresh -------------------------------------------------------------------------------- */

static void refresh_status(lv_obj_t *lbl, const cal_status_t *st)
{
    char b[64];
    snprintf(b, sizeof(b), "%s%s%s %s%u%%", st->ble_connected ? LV_SYMBOL_BLUETOOTH " " : "",
             st->wifi == 2 ? LV_SYMBOL_WIFI " " : (st->wifi == 3 ? "AP " : ""),
             st->usb_host ? LV_SYMBOL_USB " " : "", st->charging ? LV_SYMBOL_CHARGE : battery_symbol(st->battery_pct),
             (unsigned)st->battery_pct);
    lv_label_set_text(lbl, b);
}

/* The capture tag: mode, the extreme shown, and the state ("..." armed, PLAY tracking, STOP frozen). */
static void refresh_tag(const cal_live_t *lv, bool rezero)
{
    const cal_capture_t *c = &lv->capture;
    lv_color_t col = C_DIM;
    char b[40];
    const char *st = c->state == CALIPER_CAPST_RUN    ? " " LV_SYMBOL_PLAY
                     : c->state == CALIPER_CAPST_DONE ? " " LV_SYMBOL_STOP
                                                      : " ...";
    if (c->manual_hold) {
        snprintf(b, sizeof(b), "HOLD");
        col = C_AMBER;
    } else if (rezero) {
        snprintf(b, sizeof(b), "ZERO?");
        col = C_AMBER;
    } else if (c->mode == CALIPER_CAPTURE_SETTLE) {
        snprintf(b, sizeof(b), "SETTLE%s", st);
    } else if (c->mode == CALIPER_CAPTURE_SWEEP && c->state == CALIPER_CAPST_ABORT) {
        snprintf(b, sizeof(b), "SWEEP SENSOR");
        col = C_RED;
    } else if (c->mode == CALIPER_CAPTURE_SWEEP && (c->state == CALIPER_CAPST_RUN || c->state == CALIPER_CAPST_DONE)) {
        snprintf(b, sizeof(b), "%s%s%s%s", c->which < 0 ? LV_SYMBOL_DOWN : LV_SYMBOL_UP, c->which < 0 ? "MIN" : "MAX",
                 c->sel == CALIPER_SWEEP_AUTO ? " auto" : "", st);
    } else if (c->mode == CALIPER_CAPTURE_SWEEP) {
        snprintf(b, sizeof(b), "SWEEP %s%s", c->sel == CALIPER_SWEEP_MIN ? "min" : c->sel == CALIPER_SWEEP_MAX ? "max" : "auto", st);
    } else {
        b[0] = '\0';
    }
    if (!c->manual_hold && !rezero) {
        col = c->state == CALIPER_CAPST_DONE ? C_AMBER : c->state == CALIPER_CAPST_RUN ? C_ACCENT : col;
    }
    lv_label_set_text(s_tag, b);
    lv_obj_set_style_text_color(s_tag, col, 0);
}

/* The detail line under the reading. */
static void refresh_line(const cal_live_t *lv)
{
    const cal_capture_t *c = &lv->capture;
    char a[16], r[16], b[48];
    lv_color_t col = C_DIM;
    b[0] = '\0';
    if (c->manual_hold) {
        /* nothing: a hand hold of the live value */
    } else if (c->mode == CALIPER_CAPTURE_SWEEP && (c->state == CALIPER_CAPST_RUN || c->state == CALIPER_CAPST_DONE)) {
        fmt_nm(c->other_nm, lv->unit, a, sizeof(a));
        fmt_nm_x(c->range_nm, lv->unit, 1, r, sizeof(r)); /* the exact nm difference, one digit more */
        snprintf(b, sizeof(b), "%s%s  R %s  n %lu", c->which < 0 ? LV_SYMBOL_UP : LV_SYMBOL_DOWN, a, r,
                 (unsigned long)c->n);
        col = C_TEXT;
    } else if (c->mode == CALIPER_CAPTURE_SWEEP) {
        snprintf(b, sizeof(b), c->state == CALIPER_CAPST_ABORT ? "capture dropped: lift off, retry"
                                                                : "on the part: rock / sweep slowly");
    } else if (c->mode == CALIPER_CAPTURE_SETTLE && c->state == CALIPER_CAPST_DONE) {
        /* the spread is normally below one display step: sigma in um (mm) or 1e-5 in */
        if (lv->unit) {
            fmt_nm_x(c->sd_nm, 1, 1, r, sizeof(r));
            snprintf(b, sizeof(b), "median  n %lu  sd %s in", (unsigned long)c->n, r);
        } else {
            snprintf(b, sizeof(b), "median  n %lu  sd %ld.%ld um", (unsigned long)c->n, (long)(c->sd_nm / 1000),
                     (long)((c->sd_nm % 1000) / 100));
        }
        settings_t s;
        core_get_settings(&s);
        meas_fmt_t f = meas_fmt_for(lv->unit ? MEAS_UNIT_INCH : MEAS_UNIT_MM, s.decimals);
        col = c->range_nm > meas_step_nm(&f) ? C_AMBER : C_TEXT; /* more than a step: not really settled */
    } else if (c->mode == CALIPER_CAPTURE_SETTLE && c->state == CALIPER_CAPST_RUN) {
        snprintf(b, sizeof(b), "settling...");
    } else if (lv->flags & CALIPER_FLAG_CAP_VALID) {
        fmt_nm(lv->cap_nm, lv->unit, a, sizeof(a));
        snprintf(b, sizeof(b), "cap %s", a);
    }
    lv_label_set_text(s_line, b);
    lv_obj_set_style_text_color(s_line, col, 0);
}

static void refresh_main(const cal_live_t *lv, const cal_status_t *st)
{
    lv_label_set_text(s_value, lv->text);
    bool rezero = (lv->flags & CALIPER_FLAG_REZERO) != 0; /* the zero was lost in a sleep or reset */
    lv_obj_set_style_text_color(s_value,
                                (lv->flags & CALIPER_FLAG_SENSOR_ERR) ? C_RED : rezero ? C_AMBER : C_TEXT, 0);
    lv_label_set_text(s_unit, lv->unit ? "in" : "mm");
    refresh_tag(lv, rezero);
    refresh_line(lv);
    refresh_status(s_status, st);

    if (lv->profile_id) {
        const char *verdict = lv->tol == MEAS_TOL_PASS ? "GO" : lv->tol == MEAS_TOL_WARN ? "GO (edge)"
                                                                                           : "NO GO";
        /* name what was judged when it is not simply the live value */
        const cal_capture_t *cp = &lv->capture;
        const char *judged = "";
        if (!cp->manual_hold && cp->mode == CALIPER_CAPTURE_SWEEP &&
            (cp->state == CALIPER_CAPST_RUN || cp->state == CALIPER_CAPST_DONE)) {
            judged = cp->which < 0 ? " (min)" : " (max)";
        } else if (!cp->manual_hold && cp->mode == CALIPER_CAPTURE_SETTLE && cp->state == CALIPER_CAPST_DONE) {
            judged = " (median)";
        }
        lv_label_set_text_fmt(s_profile, "%s  %s%s", lv->profile_name, verdict, judged);
        lv_color_t c = lv->tol == MEAS_TOL_PASS ? C_GREEN : lv->tol == MEAS_TOL_WARN ? C_AMBER : C_RED;
        lv_obj_set_style_text_color(s_profile, c, 0);
        lv_obj_set_style_bg_color(s_gauge, c, LV_PART_INDICATOR);
        lv_bar_set_value(s_gauge, lv->gauge, LV_ANIM_OFF);
        lv_obj_remove_flag(s_gauge, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_label_set_text(s_profile, "");
        lv_obj_add_flag(s_gauge, LV_OBJ_FLAG_HIDDEN);
    }
}

static void refresh_stats(const cal_live_t *lv)
{
    meas_stats_t s;
    core_get_stats(&s);
    if (s.n == 0) {
        lv_label_set_text(s_stats_lbl, "No readings yet.\nHOLD long = record + send");
        return;
    }
    char mean[16], sd[16], mn[16], mx[16], rg[16];
    fmt_nm(meas_sat_i32((int64_t)(s.mean >= 0 ? s.mean + 0.5 : s.mean - 0.5)), lv->unit, mean, sizeof(mean));
    double sdv = meas_stats_stddev(&s);
    /* the standard deviation gets one digit more than the reading */
    settings_t st;
    core_get_settings(&st);
    meas_fmt_t f = meas_fmt_for(lv->unit ? MEAS_UNIT_INCH : MEAS_UNIT_MM, (uint8_t)(st.decimals + 1));
    meas_format(meas_sat_i32((int64_t)(sdv + 0.5)), &f, sd, sizeof(sd));
    fmt_nm(s.min, lv->unit, mn, sizeof(mn));
    fmt_nm(s.max, lv->unit, mx, sizeof(mx));
    fmt_nm(meas_sat_i32((int64_t)s.max - s.min), lv->unit, rg, sizeof(rg));
    lv_label_set_text_fmt(s_stats_lbl, "n      %lu\nmean   %s\nsigma  %s\nmin    %s\nmax    %s\nrange  %s",
                          (unsigned long)s.n, mean, sd, mn, mx, rg);
}

static const char *menu_text(int i, const cal_live_t *lv, const cal_status_t *st, char *b, size_t n)
{
    switch (i) {
    case UI_MENU_UNIT: snprintf(b, n, "Unit: %s", lv->unit ? "inch" : "mm"); break;
    case UI_MENU_PROFILE: snprintf(b, n, "Profile: %s", lv->profile_id ? lv->profile_name : "none"); break;
    case UI_MENU_CAPTURE:
        snprintf(b, n, "Capture: %s", lv->capture.mode == CALIPER_CAPTURE_SWEEP    ? "sweep"
                                      : lv->capture.mode == CALIPER_CAPTURE_SETTLE ? "settle"
                                                                                   : "off");
        break;
    case UI_MENU_SWEEP_SEL:
        snprintf(b, n, "Sweep: %s", lv->capture.sel == CALIPER_SWEEP_MIN   ? "min"
                                    : lv->capture.sel == CALIPER_SWEEP_MAX ? "max"
                                                                           : "auto");
        break;
    case UI_MENU_WIFI: snprintf(b, n, "Wi-Fi: %s", st->wifi == 2 ? st->ip : st->wifi ? "starting" : "off"); break;
    case UI_MENU_PROVISION: snprintf(b, n, "Wi-Fi setup (AP)"); break;
    case UI_MENU_STATS_RESET: snprintf(b, n, "Reset stats"); break;
    case UI_MENU_LOG_CLEAR: snprintf(b, n, "Clear log (hold)"); break;
    case UI_MENU_SLEEP: snprintf(b, n, "Sleep"); break;
    default: snprintf(b, n, "About"); break;
    }
    return b;
}

static void refresh_menu(const cal_live_t *lv, const cal_status_t *st)
{
    /* show a window of 5 items around the selection */
    int first = s_menu_sel - 2;
    if (first > UI_MENU_COUNT - 5) first = UI_MENU_COUNT - 5;
    if (first < 0) first = 0;
    for (int i = 0; i < UI_MENU_COUNT; i++) {
        lv_obj_t *it = s_menu_items[i];
        if (i < first || i >= first + 5) {
            lv_obj_add_flag(it, LV_OBJ_FLAG_HIDDEN);
            continue;
        }
        char b[40];
        lv_label_set_text(it, menu_text(i, lv, st, b, sizeof(b)));
        lv_obj_remove_flag(it, LV_OBJ_FLAG_HIDDEN);
        lv_obj_set_pos(it, 6, 6 + (i - first) * 25);
        lv_obj_set_style_bg_opa(it, i == s_menu_sel ? LV_OPA_COVER : LV_OPA_TRANSP, 0);
        lv_obj_set_style_text_color(it, i == s_menu_sel ? C_BG : C_TEXT, 0);
    }
}

static void refresh_prov(const cal_status_t *st)
{
    if (st->wifi == 3) {
        lv_label_set_text_fmt(s_prov, "Wi-Fi setup\nJoin  %s\nPass  %s\nOpen  http://192.168.4.1", st->ap_ssid,
                              st->ap_pass);
        lv_obj_remove_flag(s_prov, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(s_prov, LV_OBJ_FLAG_HIDDEN);
    }
}

static void refresh_cb(lv_timer_t *t)
{
    (void)t;
    cal_live_t lv;
    cal_status_t st;
    core_get_live(&lv);
    core_get_status(&st);
    switch (s_cur) {
    case UI_SCR_MAIN: refresh_main(&lv, &st); break;
    case UI_SCR_CHART: {
        char a[16], b[16];
        fmt_nm(s_chart_min * 1000, lv.unit, a, sizeof(a));
        fmt_nm(s_chart_max * 1000, lv.unit, b, sizeof(b));
        lv_label_set_text_fmt(s_chart_lbl, "%s  %s .. %s", lv.text, a, b);
        break;
    }
    case UI_SCR_STATS: refresh_stats(&lv); break;
    case UI_SCR_MENU: refresh_menu(&lv, &st); break;
    default: break;
    }
    refresh_prov(&st);
}

static void chart_cb(lv_timer_t *t)
{
    (void)t;
    cal_live_t lv;
    core_get_live(&lv);
    int32_t um = lv.live_nm / 1000;
    if (s_chart_n < CHART_POINTS) {
        s_chart_buf[s_chart_n++] = um;
    } else {
        memmove(s_chart_buf, s_chart_buf + 1, (CHART_POINTS - 1) * sizeof(int32_t));
        s_chart_buf[CHART_POINTS - 1] = um;
    }
    s_chart_min = INT32_MAX;
    s_chart_max = INT32_MIN;
    for (int i = 0; i < s_chart_n; i++) {
        if (s_chart_buf[i] < s_chart_min) s_chart_min = s_chart_buf[i];
        if (s_chart_buf[i] > s_chart_max) s_chart_max = s_chart_buf[i];
    }
    int32_t lo = s_chart_min, hi = s_chart_max;
    if (hi - lo < 20) { /* at least +-10 um of span so noise doesn't fill the screen */
        int32_t mid = (hi + lo) / 2;
        lo = mid - 10;
        hi = mid + 10;
    }
    lv_chart_set_range(s_chart, LV_CHART_AXIS_PRIMARY_Y, lo, hi);
    lv_chart_set_next_value(s_chart, s_series, um);
}

static void toast_cb(lv_timer_t *t)
{
    lv_obj_add_flag(s_toast, LV_OBJ_FLAG_HIDDEN);
    lv_timer_pause(t); /* reused: ui_toast() resumes it */
}

/* ---- creation ------------------------------------------------------------------------------- */

static void create_main(void)
{
    lv_obj_t *s = s_scr[UI_SCR_MAIN] = new_screen();
    s_status = label(s, &lv_font_montserrat_14, C_DIM, LV_ALIGN_TOP_RIGHT, -4, 2);
    s_tag = label(s, &lv_font_montserrat_14, C_AMBER, LV_ALIGN_TOP_LEFT, 4, 2);
    s_value = label(s, &lv_font_montserrat_48, C_TEXT, LV_ALIGN_RIGHT_MID, -40, -14);
    s_unit = label(s, &lv_font_montserrat_20, C_DIM, LV_ALIGN_RIGHT_MID, -6, -4);
    s_line = label(s, &lv_font_montserrat_14, C_DIM, LV_ALIGN_TOP_LEFT, 4, 82);

    s_profile = label(s, &lv_font_montserrat_14, C_GREEN, LV_ALIGN_BOTTOM_LEFT, 4, -18);

    s_gauge = lv_bar_create(s);
    lv_obj_set_size(s_gauge, 232, 10);
    lv_obj_align(s_gauge, LV_ALIGN_BOTTOM_MID, 0, -4);
    lv_bar_set_mode(s_gauge, LV_BAR_MODE_SYMMETRICAL);
    lv_bar_set_range(s_gauge, -MEAS_GAUGE_CLAMP, MEAS_GAUGE_CLAMP);
    lv_obj_set_style_bg_color(s_gauge, lv_color_hex(0x262a31), LV_PART_MAIN);
    lv_obj_add_flag(s_gauge, LV_OBJ_FLAG_HIDDEN);
    /* tick marks at the tolerance limits (+-1000 of +-1500) */
    for (int k = -1; k <= 1; k += 2) {
        lv_obj_t *m = lv_obj_create(s_gauge);
        lv_obj_set_size(m, 2, 10);
        lv_obj_set_style_bg_color(m, C_TEXT, 0);
        lv_obj_set_style_border_width(m, 0, 0);
        lv_obj_set_style_radius(m, 0, 0);
        lv_obj_align(m, LV_ALIGN_CENTER, k * 232 * MEAS_GAUGE_LIMIT / (2 * MEAS_GAUGE_CLAMP), 0);
    }
}

static void create_chart(void)
{
    lv_obj_t *s = s_scr[UI_SCR_CHART] = new_screen();
    s_chart_lbl = label(s, &lv_font_montserrat_14, C_DIM, LV_ALIGN_TOP_LEFT, 4, 2);
    s_chart = lv_chart_create(s);
    lv_obj_set_size(s_chart, 236, 112);
    lv_obj_align(s_chart, LV_ALIGN_BOTTOM_MID, 0, -2);
    lv_chart_set_type(s_chart, LV_CHART_TYPE_LINE);
    lv_chart_set_point_count(s_chart, CHART_POINTS);
    lv_chart_set_update_mode(s_chart, LV_CHART_UPDATE_MODE_SHIFT);
    lv_chart_set_div_line_count(s_chart, 3, 0);
    lv_obj_set_style_bg_color(s_chart, C_BG, 0);
    lv_obj_set_style_border_color(s_chart, lv_color_hex(0x262a31), 0);
    lv_obj_set_style_width(s_chart, 0, LV_PART_INDICATOR); /* no point markers */
    lv_obj_set_style_height(s_chart, 0, LV_PART_INDICATOR);
    s_series = lv_chart_add_series(s_chart, C_ACCENT, LV_CHART_AXIS_PRIMARY_Y);
}

static void create_stats(void)
{
    lv_obj_t *s = s_scr[UI_SCR_STATS] = new_screen();
    lv_obj_t *t = label(s, &lv_font_montserrat_14, C_DIM, LV_ALIGN_TOP_LEFT, 4, 2);
    lv_label_set_text(t, "Statistics (recorded)");
    s_stats_lbl = label(s, &lv_font_montserrat_14, C_TEXT, LV_ALIGN_TOP_LEFT, 8, 22);
}

static void create_menu(void)
{
    lv_obj_t *s = s_scr[UI_SCR_MENU] = new_screen();
    for (int i = 0; i < UI_MENU_COUNT; i++) {
        lv_obj_t *it = label(s, &lv_font_montserrat_20, C_TEXT, LV_ALIGN_TOP_LEFT, 6, 6);
        lv_obj_set_width(it, 228);
        lv_obj_set_style_bg_color(it, C_ACCENT, 0);
        lv_obj_set_style_pad_hor(it, 4, 0);
        s_menu_items[i] = it;
    }
}

void ui_screens_create(void)
{
    create_main();
    create_chart();
    create_stats();
    create_menu();
    /* overlays live on the top layer so they show on every screen */
    s_toast = lv_label_create(lv_layer_top());
    lv_obj_set_style_bg_color(s_toast, lv_color_hex(0x334155), 0);
    lv_obj_set_style_bg_opa(s_toast, LV_OPA_COVER, 0);
    lv_obj_set_style_text_color(s_toast, C_TEXT, 0);
    lv_obj_set_style_pad_all(s_toast, 4, 0);
    lv_obj_align(s_toast, LV_ALIGN_BOTTOM_MID, 0, -20);
    lv_obj_add_flag(s_toast, LV_OBJ_FLAG_HIDDEN);
    s_toast_timer = lv_timer_create(toast_cb, TOAST_MS, NULL);
    lv_timer_pause(s_toast_timer);

    s_prov = lv_label_create(lv_layer_top());
    lv_obj_set_size(s_prov, 240, 135);
    lv_obj_set_style_bg_color(s_prov, C_BG, 0);
    lv_obj_set_style_bg_opa(s_prov, LV_OPA_COVER, 0);
    lv_obj_set_style_text_color(s_prov, C_TEXT, 0);
    lv_obj_set_style_text_font(s_prov, &lv_font_montserrat_14, 0);
    lv_obj_set_style_pad_all(s_prov, 8, 0);
    lv_obj_add_flag(s_prov, LV_OBJ_FLAG_HIDDEN);

    lv_timer_create(refresh_cb, REFRESH_MS, NULL);
    lv_timer_create(chart_cb, CHART_MS, NULL);
    ui_screens_show(UI_SCR_MAIN);
}

void ui_screens_show(ui_screen_t s)
{
    if (s >= UI_SCR_COUNT) {
        s = UI_SCR_MAIN;
    }
    s_cur = s;
    lv_screen_load(s_scr[s]);
}

ui_screen_t ui_screens_current(void)
{
    return s_cur;
}

void ui_menu_move(int delta)
{
    s_menu_sel = (s_menu_sel + delta + UI_MENU_COUNT) % UI_MENU_COUNT;
}

int ui_menu_selected(void)
{
    return s_menu_sel;
}

void ui_toast(const char *msg)
{
    if (!s_toast) {
        return;
    }
    lv_label_set_text(s_toast, msg);
    lv_obj_remove_flag(s_toast, LV_OBJ_FLAG_HIDDEN);
    lv_timer_reset(s_toast_timer);
    lv_timer_resume(s_toast_timer);
}
