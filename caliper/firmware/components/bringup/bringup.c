/*
 * Bring-up checks on the USB console ("bu help"). They run in the CLI task next to the normal
 * firmware and read the drivers' own state (no second owner of a bus or pin): the I2C chips through
 * power_diag_read() (the I2C driver's bus lock), the AS5311 and the capacitive burst through the
 * snapshots their tasks publish, BLE and Wi-Fi through their components. Procedure, meter points and
 * limits: docs/bringup.md.
 */
#include "bringup.h"

#include <stdlib.h>
#include <string.h>

#include "ble.h"
#include "board_pins.h"
#include "bringup_eval.h"
#include "caliper_core.h"
#include "caliper_wifi.h"
#include "driver/gpio.h"
#include "driver/i2c_master.h"
#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "power.h"
#include "sdkconfig.h"
#include "sensor_cap.h"
#include "sensor_mag.h"
#include "ui.h"

#define OUT(...) s_io->out(__VA_ARGS__)

/* LIS2DW12 registers (power.c configures it: 12.5 Hz, low-power mode 1, +-2 g, wake-up on INT1) */
#define IMU_WHO_AM_I    0x0F
#define IMU_OUT_X_L     0x28
#define IMU_WAKE_UP_SRC 0x38
#define IMU_ALL_INT_SRC 0x3B
/* MAX17048 registers */
#define FG_VCELL   0x02
#define FG_SOC     0x04
#define FG_VERSION 0x08
#define FG_HIBRT   0x0A
#define FG_CONFIG  0x0C
#define FG_VRESET  0x18
#define FG_STATUS  0x1A

#define BACKLIGHT_RUN_PCT 70 /* app_main's BACKLIGHT_ON_PCT */
#define ANSWER_MS         60000

#if CONFIG_CALIPER_CHG_TS_ENABLE
#define TS_ENABLED true
#else
#define TS_ENABLED false
#endif

static const bu_io_t *s_io;
static int s_pass, s_fail;

static bool verdict(bool ok, const char *name, const char *detail)
{
    OUT("%s %s: %s\n", ok ? "PASS" : "FAIL", name, detail);
    if (ok) {
        s_pass++;
    } else {
        s_fail++;
    }
    return ok;
}

static bool ask_yn(const char *q)
{
    OUT("%s [y/n]\n", q);
    char l[16];
    for (;;) {
        if (!s_io->ask(l, sizeof(l), ANSWER_MS)) {
            OUT("(no answer)\n");
            return false;
        }
        if (l[0] == 'y' || l[0] == 'Y') {
            return true;
        }
        if (l[0] == 'n' || l[0] == 'N') {
            return false;
        }
        OUT("y or n\n");
    }
}

static int arg_int(int argc, char **argv, int i, int dflt)
{
    return argc > i ? atoi(argv[i]) : dflt;
}

static void wait_ms(uint32_t ms)
{
    core_activity(); /* no auto-off in the middle of a test */
    vTaskDelay(pdMS_TO_TICKS(ms));
}

/* ---- power: rails, I2C, charger, gauge ------------------------------------------------------ */

static bool t_rails(int argc, char **argv)
{
    int32_t ref = arg_int(argc, argv, 1, 0);
    power_status_t ps;
    power_get_last(&ps);
    OUT("VBAT %u mV (MAX17048 VCELL; meter: TP2), VBUS %s (BQ25180 VIN_PGOOD; meter: TP1), charge state %u%s, "
        "die %.1f C\n",
        ps.vcell_mv, ps.vbus ? "present" : "absent", ps.chg_stat, ps.chg_disabled ? " (charging disabled)" : "",
        (double)ps.die_c);
    OUT("no ADC on these, use the meter: VSYS TP3, +3V3 TP4 (implied: the MCU runs), +3V3_SNS TP5, +3V3_UI TP6\n");
    char d[200];
    bool ok = ps.charger_ok && ps.gauge_ok && ps.vcell_mv >= BU_FG_VCELL_MIN_MV && ps.vcell_mv <= BU_FG_VCELL_MAX_MV;
    int32_t diff = (int32_t)ps.vcell_mv - ref;
    if (ref > 0 && (diff > BU_FG_VCELL_TOL_MV || diff < -BU_FG_VCELL_TOL_MV)) {
        ok = false;
    }
    snprintf(d, sizeof(d), "charger %s, gauge %s, VBAT %u mV%s", ps.charger_ok ? "ok" : "MISSING",
             ps.gauge_ok ? "ok" : "MISSING", ps.vcell_mv, ref > 0 ? "" : " (no meter value given)");
    if (ref > 0) {
        size_t l = strlen(d);
        snprintf(d + l, sizeof(d) - l, ", %+ld mV vs meter (limit %d)", (long)diff, BU_FG_VCELL_TOL_MV);
    }
    return verdict(ok, "rails", d);
}

static bool t_i2c(int argc, char **argv)
{
    (void)argc;
    (void)argv;
    uint8_t found[BU_I2C_MAX];
    size_t n = 0;
    for (uint8_t a = BU_I2C_FIRST; a <= BU_I2C_LAST; a++) {
        if (i2c_master_probe(power_i2c_bus(), a, 20) == ESP_OK && n < BU_I2C_MAX) {
            found[n++] = a;
        }
    }
    char d[200] = "";
    size_t l = 0;
    for (size_t i = 0; i < n && l < sizeof(d); i++) {
        const char *nm = bu_i2c_name(found[i]);
        l += (size_t)snprintf(d + l, sizeof(d) - l, "%s0x%02x %s", i ? ", " : "", found[i], nm ? nm : "UNEXPECTED");
    }
    OUT("answered: %s\n", n ? d : "nothing");
    bu_i2c_result_t r;
    bool ok = bu_i2c_eval(found, n, &r);
    l = (size_t)snprintf(d, sizeof(d), "%u found", (unsigned)n);
    for (size_t i = 0; i < r.n_missing && l < sizeof(d); i++) {
        l += (size_t)snprintf(d + l, sizeof(d) - l, ", MISSING 0x%02x %s", r.missing[i], bu_i2c_name(r.missing[i]));
    }
    for (size_t i = 0; i < r.n_extra && l < sizeof(d); i++) {
        l += (size_t)snprintf(d + l, sizeof(d) - l, ", UNEXPECTED 0x%02x", r.extra[i]);
    }
    return verdict(ok, "i2c", d);
}

static bool t_bq(int argc, char **argv)
{
    (void)argc;
    (void)argv;
    uint8_t dump[BU_BQ_NREGS];
    if (power_diag_read(I2C_ADDR_BQ25180, 0x00, dump, sizeof(dump)) != ESP_OK) {
        return verdict(false, "bq", "no answer at 0x6A");
    }
    char d[220];
    size_t l = 0;
    for (size_t i = 0; i < sizeof(dump); i++) {
        l += (size_t)snprintf(d + l, sizeof(d) - l, " %02x", dump[i]);
    }
    OUT("registers 0x00-0x0C:%s\n", d);
    bool st = bu_bq_status(dump[0], dump[1], dump[2], TS_ENABLED, d, sizeof(d));
    OUT("status: %s\n", d);
    power_reg_t t[12];
    bu_reg_t w[12];
    size_t n = power_bq_table(t, 12);
    for (size_t i = 0; i < n; i++) {
        w[i] = (bu_reg_t){t[i].reg, t[i].val};
    }
    size_t bad = bu_regs_check(w, n, dump, sizeof(dump), d, sizeof(d));
    OUT("init table read-back: %s\n", d);
    snprintf(d, sizeof(d), "status %s, %u of %u init registers differ", st ? "ok" : "FAULT", (unsigned)bad, (unsigned)n);
    return verdict(st && !bad, "bq", d);
}

static esp_err_t fg16(uint8_t reg, uint16_t *v)
{
    uint8_t b[2] = {0, 0};
    esp_err_t err = power_diag_read(I2C_ADDR_MAX17048, reg, b, 2);
    *v = (uint16_t)((b[0] << 8) | b[1]);
    return err;
}

static bool t_fg(int argc, char **argv)
{
    bu_fg_regs_t r;
    uint16_t status = 0;
    esp_err_t err = fg16(FG_VERSION, &r.version);
    err |= fg16(FG_VCELL, &r.vcell);
    err |= fg16(FG_SOC, &r.soc);
    err |= fg16(FG_CONFIG, &r.config);
    err |= fg16(FG_HIBRT, &r.hibrt);
    err |= fg16(FG_VRESET, &r.vreset);
    err |= fg16(FG_STATUS, &status);
    if (err != ESP_OK) {
        return verdict(false, "fg", "no answer at 0x36");
    }
    OUT("CONFIG 0x%04x HIBRT 0x%04x VRESET 0x%04x STATUS 0x%04x\n", r.config, r.hibrt, r.vreset, status);
    char d[220];
    bool ok = bu_fg_eval(&r, arg_int(argc, argv, 1, 0), d, sizeof(d));
    return verdict(ok, "fg", d);
}

/* ---- IMU ------------------------------------------------------------------------------------ */

static bool imu_read(int32_t mg[3])
{
    uint8_t b[6];
    if (power_diag_read(I2C_ADDR_LIS2DW12, IMU_OUT_X_L, b, sizeof(b)) != ESP_OK) {
        return false;
    }
    for (int i = 0; i < 3; i++) {
        mg[i] = bu_imu_mg((int16_t)(b[2 * i] | (b[2 * i + 1] << 8)));
    }
    return true;
}

static void imu_clear_latch(void)
{
    uint8_t v;
    power_diag_read(I2C_ADDR_LIS2DW12, IMU_WAKE_UP_SRC, &v, 1);
    power_diag_read(I2C_ADDR_LIS2DW12, IMU_ALL_INT_SRC, &v, 1);
}

static bool t_imu_move(int secs)
{
    imu_clear_latch();
    wait_ms(100);
    if (!gpio_get_level(PIN_IMU_INT1)) {
        imu_clear_latch();
        wait_ms(200);
        if (!gpio_get_level(PIN_IMU_INT1)) {
            return verdict(false, "imu-move", "IMU_INT1 low after clearing the latch (held still?): INT1 stuck low");
        }
    }
    OUT("pick the board up and turn it over and back within %d s\n", secs);
    bu_imu_span_t s;
    bu_imu_span_init(&s);
    bool low = false;
    for (int t = 0; t < secs * 20; t++) {
        low |= !gpio_get_level(PIN_IMU_INT1);
        int32_t mg[3];
        if (imu_read(mg)) {
            bu_imu_span_feed(&s, mg);
        }
        wait_ms(50);
    }
    imu_clear_latch(); /* so the pickup wake works at the next sleep */
    char d[220];
    bool ok = bu_imu_move_eval(&s, low, d, sizeof(d));
    return verdict(ok, "imu-move", d);
}

static bool t_imu(int argc, char **argv)
{
    uint8_t who = 0;
    if (power_diag_read(I2C_ADDR_LIS2DW12, IMU_WHO_AM_I, &who, 1) != ESP_OK) {
        return verdict(false, "imu", "no answer at 0x19");
    }
    if (who != BU_IMU_WHO_AM_I) {
        char d[64];
        snprintf(d, sizeof(d), "WHO_AM_I 0x%02x (0x44 expected)", who);
        return verdict(false, "imu", d);
    }
    if (argc > 1 && !strcmp(argv[1], "move")) {
        return t_imu_move(arg_int(argc, argv, 2, 5));
    }
    int64_t sum[3] = {0};
    int n = 0;
    for (int i = 0; i < 8; i++) {
        int32_t mg[3];
        if (imu_read(mg)) {
            for (int k = 0; k < 3; k++) {
                sum[k] += mg[k];
            }
            n++;
        }
        wait_ms(100); /* ODR 12.5 Hz */
    }
    if (!n) {
        return verdict(false, "imu", "WHO_AM_I ok but the output registers do not read");
    }
    int32_t a[3] = {(int32_t)(sum[0] / n), (int32_t)(sum[1] / n), (int32_t)(sum[2] / n)};
    uint32_t norm = bu_imu_norm_mg(a[0], a[1], a[2]);
    char d[160];
    snprintf(d, sizeof(d), "WHO_AM_I 0x44, X %ld Y %ld Z %ld mg, |a| %lu mg (limit %d-%d), INT1 %s", (long)a[0],
             (long)a[1], (long)a[2], (unsigned long)norm, BU_IMU_G_MIN_MG, BU_IMU_G_MAX_MG,
             gpio_get_level(PIN_IMU_INT1) ? "high" : "low (latched wake-up)");
    return verdict(bu_imu_still_ok(norm), "imu", d);
}

/* ---- sensor rail, AS5311 ------------------------------------------------------------------- */

static bool t_sns(int argc, char **argv)
{
    if (argc > 1 && !strcmp(argv[1], "off")) {
        ui_test_pattern(false);
        power_backlight(0);
        ui_sleep();           /* LVGL stopped: nothing drives the panel any more */
        power_ui_lines_low(); /* no back-powering of +3V3_UI through the LCD / LED inputs */
        sensor_mag_power(false);
        OUT("SNS_PWR_EN low: +3V3_SNS (TP5) and +3V3_UI (TP6) should read < 0.1 V, +3V3 (TP4) unchanged\n");
        bool y = ask_yn("TP5 and TP6 below 0.1 V?");
        OUT("then 'bu sns on' and 'reboot' (the display needs a fresh start)\n");
        return verdict(y, "sns-off", y ? "operator: both rails off" : "operator: a rail stayed up (U5 / U6, R5)");
    }
    if (argc > 1 && !strcmp(argv[1], "on")) {
        mag_diag_t a, b;
        sensor_mag_diag(&a);
        sensor_mag_power(true);
        int t = 0;
        do {
            wait_ms(50);
            sensor_mag_diag(&b);
        } while (b.frames_ok == a.frames_ok && (t += 50) < 1000);
        bool frames = b.frames_ok != a.frames_ok;
        OUT("AS5311 %s after power-up; +3V3_SNS (TP5) and +3V3_UI (TP6) should equal +3V3 (TP4) within 20 mV\n",
            frames ? "answers" : "gives no valid frame");
        bool y = ask_yn("TP5 and TP6 within 20 mV of TP4?");
        OUT("'reboot' to bring the display back\n");
        char d[96];
        snprintf(d, sizeof(d), "AS5311 %s, operator: rails %s", frames ? "ok" : "NO FRAME", y ? "ok" : "NOT OK");
        return verdict(frames && y, "sns-on", d);
    }
    OUT("bu sns off | on\n");
    return false;
}

static int32_t lsb_um(int64_t lsb)
{
    return (int32_t)(lsb * 125 / 256); /* 488.28125 nm per LSB */
}

static bool t_mag_move(int secs)
{
    mag_diag_t d0, d;
    sensor_mag_diag(&d0);
    sensor_mag_xcheck_start();
    OUT("move the slider slowly (< 5 cm/s) back and forth over at least 4 mm for %d s\n", secs);
    for (int t = 1; t <= secs; t++) {
        wait_ms(1000);
        sensor_mag_diag(&d);
        OUT("%2d s: %lu frames, span %ld um, largest step %ld LSB\n", t, (unsigned long)d.xc.frames,
            (long)lsb_um(d.xc.max_u - d.xc.min_u), (long)d.xc.max_step);
    }
    sensor_mag_xcheck_stop();
    sensor_mag_diag(&d);
    as5311_xc_result_t r = as5311_xcheck_result(&d.xc);
    OUT("count %+lld (%+ld um), SSI %+lld LSB (%+ld um), worst |SSI - 4 count| %lld LSB (limit %d), "
        "|SSI + 4 count| %lld LSB\n",
        (long long)d.xc.count_d, (long)lsb_um(d.xc.count_d * AS5311_LSB_PER_COUNT), (long long)d.xc.ssi_u,
        (long)lsb_um(d.xc.ssi_u), (long long)d.xc.dev_p_max, AS5311_XC_TOL_LSB, (long long)d.xc.dev_m_max);
    OUT("travel %ld um, pole crossings %lu, index pulses %lu, slips %lu, jumps %lu\n", (long)lsb_um(d.xc.travel),
        (unsigned long)d.xc.crossings, (unsigned long)(d.idx_pulses - d0.idx_pulses),
        (unsigned long)(d.slips - d0.slips), (unsigned long)(d.jumps - d0.jumps));
    return verdict(r == AS5311_XC_OK, "mag-move", as5311_xcheck_str(r));
}

static bool t_mag(int argc, char **argv)
{
    if (argc > 1 && !strcmp(argv[1], "move")) {
        return t_mag_move(arg_int(argc, argv, 2, 15));
    }
    mag_diag_t a, b;
    sensor_mag_diag(&a);
    wait_ms(1000);
    sensor_mag_diag(&b);
    if (!b.powered) {
        return verdict(false, "mag", "sensor rail off ('bu sns on', then 'reboot')");
    }
    char d[200];
    bu_as5311_frame_text(b.last_raw, d, sizeof(d));
    OUT("last frame %s\n", d);
    OUT("MAG_INC_N %d MAG_DEC_N %d, PCNT %lld, index pulses %lu, slips %lu, jumps %lu\n",
        gpio_get_level(PIN_MAG_INC_N), gpio_get_level(PIN_MAG_DEC_N), (long long)b.pcnt,
        (unsigned long)b.idx_pulses, (unsigned long)b.slips, (unsigned long)b.jumps);
    bool ok = bu_as5311_eval(b.frames_ok - a.frames_ok, b.frames_bad - a.frames_bad, b.last_raw, d, sizeof(d));
    return verdict(ok, "mag", d);
}

/* ---- display, buttons, piezo, LED ----------------------------------------------------------- */

static bool t_lcd(int argc, char **argv)
{
    if (argc > 1 && !strcmp(argv[1], "off")) {
        ui_test_pattern(false);
        return true;
    }
    if (ui_test_pattern(true) != ESP_OK) {
        return verdict(false, "lcd", "display not up (ui_init failed: see the boot log)");
    }
    power_backlight(100);
    OUT("expect, landscape, FPC end on the left: a 1 px white frame on all four edges with a black gap,\n");
    OUT("8 bars left to right: white yellow cyan green magenta red blue black, 'TOP LEFT' top left,\n");
    OUT("'BR' bottom right, both readable (not mirrored); the backlight dims for 1 s, then returns\n");
    wait_ms(2000);
    power_backlight(10);
    wait_ms(1000);
    power_backlight(100);
    bool y = ask_yn("all as described?");
    ui_test_pattern(false);
    power_backlight(BACKLIGHT_RUN_PCT);
    return verdict(y, "lcd", y ? "operator: pattern, orientation and backlight ok"
                               : "operator: see docs/bringup.md B-8 for what each symptom means");
}

static uint8_t buttons_down(void)
{
    return (uint8_t)((!gpio_get_level(PIN_BTN_ZERO_N) ? 1u : 0u) | (!gpio_get_level(PIN_BTN_HOLD_N) ? 2u : 0u) |
                     (!gpio_get_level(PIN_BTN_MODE_N) ? 4u : 0u));
}

static bool t_btn(int argc, char **argv)
{
    int secs = arg_int(argc, argv, 1, 20);
    bu_btn_t b;
    uint32_t t0 = (uint32_t)(xTaskGetTickCount() * portTICK_PERIOD_MS);
    bu_btn_init(&b, buttons_down(), 0);
    if (b.stuck) {
        OUT("a button reads pressed before the test (mask 0x%x)\n", b.stuck);
    }
    OUT("press ZERO, HOLD and MODE once each, short presses (they also act on the UI), within %d s\n", secs);
    for (;;) {
        uint32_t t = (uint32_t)(xTaskGetTickCount() * portTICK_PERIOD_MS) - t0;
        uint8_t done = bu_btn_feed(&b, buttons_down(), t);
        for (int i = 0; i < BU_BTN_N; i++) {
            if (done & (1u << i)) {
                OUT("%s pressed (%lu ms)\n", bu_btn_names[i], (unsigned long)b.longest_ms[i]);
            }
        }
        if (bu_btn_all_pressed(&b) || t > (uint32_t)secs * 1000u) {
            break;
        }
        if ((t % 1000u) < 5u) {
            core_activity();
        }
        vTaskDelay(pdMS_TO_TICKS(5));
    }
    char d[220];
    bool ok = bu_btn_eval(&b, d, sizeof(d));
    return verdict(ok, "btn", d);
}

static bool t_beep(int argc, char **argv)
{
    (void)argc;
    (void)argv;
    power_beep(200);
    wait_ms(400);
    power_beep(200);
    wait_ms(300);
    bool y = ask_yn("two 4 kHz beeps heard?");
    return verdict(y, "beep", y ? "operator: heard" : "operator: silent (BZ50, Q51 gate on BUZZ / TP51, R56)");
}

static bool t_led(int argc, char **argv)
{
    (void)argc;
    (void)argv;
    static const uint8_t seq[4][3] = {{40, 0, 0}, {0, 40, 0}, {0, 0, 40}, {30, 30, 30}};
    for (int i = 0; i < 4; i++) {
        power_led(seq[i][0], seq[i][1], seq[i][2]);
        wait_ms(700);
    }
    power_led(0, 0, 0);
    bool y = ask_yn("RGB LED showed red, green, blue, white in that order?");
    return verdict(y, "led", y ? "operator: colours in order" : "operator: wrong or none (D50, RGB_DIN, +3V3_UI)");
}

/* ---- capacitive front-end ------------------------------------------------------------------- */

static bool t_cap(int argc, char **argv)
{
    bool scale = argc > 1 && !strcmp(argv[1], "scale");
    cap_diag_t a, b;
    sensor_cap_diag(&a);
    wait_ms(2000);
    sensor_cap_diag(&b);
    if (!b.running) {
        return verdict(false, "cap", "no burst ran: CONFIG_CALIPER_CAP_SENSOR off or sensor_cap_init failed (boot log)");
    }
    uint32_t bursts = b.bursts - a.bursts, valid = b.valid - a.valid;
    if (!bursts) {
        OUT("the cap task has stopped (50 bursts in a row without coupling: normal without the scale); its last "
            "burst:\n");
        bursts = b.bursts;
        valid = b.valid;
    }
    OUT("last burst I/Q fwd %.1f / %.1f rev %.1f / %.1f LSB, half-pitch fraction %.3f, late %lu, errors %lu\n",
        (double)b.fwd.i, (double)b.fwd.q, (double)b.rev.i, (double)b.rev.q, (double)b.frac, (unsigned long)b.late,
        (unsigned long)b.errors);
    OUT("DC %.0f LSB = about %.2f V at the ADC (uncalibrated, 12 dB); CAP_VREF on TP41 should read 1.65 V\n",
        (double)b.mean_lsb, (double)(b.mean_lsb * 3.1f / 4095.0f));
    char d[220];
    bool ok = bu_cap_eval(bursts, valid, b.mean_lsb, b.amp_fwd, b.amp_rev, scale, d, sizeof(d));
    return verdict(ok, scale ? "cap-scale" : "cap", d);
}

/* ---- radio ---------------------------------------------------------------------------------- */

static bool t_ble(int argc, char **argv)
{
    int secs = arg_int(argc, argv, 1, 10);
    int min_dbm = arg_int(argc, argv, 2, 0);
    ble_diag_t d;
    ble_diag(&d);
    OUT("BLE %s, advertising %s, address %02X:%02X:%02X:%02X:%02X:%02X, advertising TX %+d dBm, %d connection(s)\n",
        d.synced ? "up" : "NOT SYNCED", d.advertising ? "on" : "off", d.addr[5], d.addr[4], d.addr[3], d.addr[2],
        d.addr[1], d.addr[0], d.tx_adv_dbm, d.conns);
    if (!d.conns) {
        OUT("connect a phone (nRF Connect: 'PrettyCool Caliper', Connect) for the link RSSI; advertising RSSI is\n"
            "read on the phone's scanner\n");
    }
    long sum = 0;
    int n = 0, lo = 0, hi = -128;
    for (int t = 0; t < secs * 2; t++) {
        wait_ms(500);
        ble_diag(&d);
        if (d.conns && d.rssi[0] != 127) {
            sum += d.rssi[0];
            n++;
            lo = n == 1 || d.rssi[0] < lo ? d.rssi[0] : lo;
            hi = d.rssi[0] > hi ? d.rssi[0] : hi;
        }
    }
    char s[160];
    bool ok = d.synced && (d.advertising || d.conns);
    if (n) {
        long avg = sum / n;
        snprintf(s, sizeof(s), "link RSSI at the caliper avg %ld dBm (min %d, max %d, %d readings)%s", avg, lo, hi, n,
                 min_dbm ? (avg >= min_dbm ? ", above the limit" : ", BELOW the limit") : "");
        ok = ok && (!min_dbm || avg >= min_dbm);
    } else {
        snprintf(s, sizeof(s), "%s, no connection: link RSSI not measured", d.advertising ? "advertising" : "NOT advertising");
        ok = ok && !min_dbm;
    }
    return verdict(ok, "ble", s);
}

static bool t_wifi(int argc, char **argv)
{
    const char *want = argc > 1 ? argv[1] : NULL;
    int min_dbm = arg_int(argc, argv, 2, 0);
    cal_wifi_ap_t ap[12];
    size_t n = 0;
    OUT("scanning (about 3 s)...\n");
    esp_err_t err = caliper_wifi_scan(ap, 12, &n);
    if (err != ESP_OK) {
        return verdict(false, "wifi", err == ESP_ERR_INVALID_STATE ? "radio busy (setup AP or connecting): 'wifi off' first"
                                                                    : esp_err_to_name(err));
    }
    int rssi = -128;
    for (size_t i = 0; i < n; i++) {
        OUT("%2u  ch %2u  %4d dBm  %s\n", (unsigned)i + 1, ap[i].channel, ap[i].rssi, ap[i].ssid[0] ? ap[i].ssid : "(hidden)");
        if (want && rssi == -128 && !strcmp(ap[i].ssid, want)) {
            rssi = ap[i].rssi;
        }
    }
    char d[160];
    if (!want) {
        snprintf(d, sizeof(d), "%u networks, strongest %d dBm", (unsigned)n, n ? ap[0].rssi : -128);
        return verdict(n > 0, "wifi", d);
    }
    bool found = rssi != -128;
    snprintf(d, sizeof(d), "'%s' %s%s", want, found ? "found" : "NOT FOUND",
             found && min_dbm && rssi < min_dbm ? ", BELOW the limit" : "");
    if (found) {
        size_t l = strlen(d);
        snprintf(d + l, sizeof(d) - l, " at %d dBm", rssi);
    }
    return verdict(found && (!min_dbm || rssi >= min_dbm), "wifi", d);
}

/* ---- sleep, ship ---------------------------------------------------------------------------- */

static void t_sleep(int argc, char **argv)
{
    int delay = arg_int(argc, argv, 1, 10);
    OUT("deep sleep in %d s: unplug USB now (VBUS leaving after the sleep would wake it via CHG_INT_N)\n", delay);
    OUT("then read the supply current into VBAT: SPEC 3 target <= 35 uA (estimate 33 uA); a button wakes it\n");
    wait_ms((uint32_t)delay * 1000u);
    core_command(CORE_CMD_SLEEP, 0);
}

static bool t_ship(int argc, char **argv)
{
    (void)argc;
    (void)argv;
    power_status_t ps;
    power_get_last(&ps);
    esp_err_t err = power_ship_mode();
    if (err != ESP_OK) {
        return verdict(false, "ship", err == ESP_ERR_INVALID_STATE ? "no charger" : "SHIP_RST write failed");
    }
    OUT("%s: VSYS (TP3) and +3V3 (TP4) go to 0 V, the supply current into VBAT falls to a few uA. Plug USB to wake.\n",
        ps.vbus ? "ship mode pending: unplug USB" : "ship mode now");
    return verdict(true, "ship", "SHIP_RST written (EN_RST_SHIP = shutdown, wake on adapter)");
}

/* ---- dispatch ------------------------------------------------------------------------------- */

static void help(void)
{
    /* one line per OUT(): the console's out() formats into 256 bytes */
    static const char *const lines[] = {
        "bring-up checks (docs/bringup.md); each ends with PASS or FAIL:",
        "bu all                    rails i2c bq fg imu mag cap ble, then a summary",
        "bu rails [vbat_mv]        VBAT (gauge) vs the meter on TP2, VBUS, charge state",
        "bu i2c                    scan: exactly 0x19 LIS2DW12, 0x36 MAX17048, 0x6A BQ25180",
        "bu bq                     BQ25180 status + register dump vs the init table",
        "bu fg [vbat_mv]           MAX17048 version, VCELL, SOC, sleep settings",
        "bu imu | bu imu move [s]  LIS2DW12 WHO_AM_I + 1 g at rest | motion + INT1 wake-up",
        "bu sns off | on           SNS_PWR_EN: +3V3_SNS / +3V3_UI off and on (then reboot)",
        "bu mag | bu mag move [s]  AS5311 SSI frames + field | count vs SSI while sliding",
        "bu lcd [off]              colour bars, frame, orientation, backlight",
        "bu btn [s]                press each button",
        "bu beep | bu led          piezo | RGB LED",
        "bu cap [scale]            capacitive front-end: DC level, I/Q, amplitude",
        "bu ble [s] [min_dbm]      advertising, TX power, link RSSI (antenna check)",
        "bu wifi [ssid] [min_dbm]  scan with RSSI",
        "bu sleep [delay_s]        deep sleep for the current measurement",
        "bu ship                   BQ25180 ship mode (USB wakes it)",
    };
    for (size_t i = 0; i < sizeof(lines) / sizeof(lines[0]); i++) {
        OUT("%s\n", lines[i]);
    }
}

void bringup_cmd(const bu_io_t *io, char *args)
{
    s_io = io;
    char *argv[8];
    int argc = 0;
    char *save = NULL;
    for (char *t = strtok_r(args, " ", &save); t && argc < 8; t = strtok_r(NULL, " ", &save)) {
        argv[argc++] = t;
    }
    if (!argc || !strcmp(argv[0], "help")) {
        help();
        return;
    }
    const char *c = argv[0];
    if (!strcmp(c, "all")) {
        s_pass = s_fail = 0;
        char *none[1] = {NULL};
        char *ble_args[2] = {"ble", "2"};
        t_rails(0, none);
        t_i2c(0, none);
        t_bq(0, none);
        t_fg(0, none);
        t_imu(0, none);
        t_mag(0, none);
        t_cap(0, none);
        t_ble(2, ble_args);
        OUT("SUMMARY %d PASS, %d FAIL\n", s_pass, s_fail);
    } else if (!strcmp(c, "rails")) t_rails(argc, argv);
    else if (!strcmp(c, "i2c")) t_i2c(argc, argv);
    else if (!strcmp(c, "bq")) t_bq(argc, argv);
    else if (!strcmp(c, "fg")) t_fg(argc, argv);
    else if (!strcmp(c, "imu")) t_imu(argc, argv);
    else if (!strcmp(c, "sns")) t_sns(argc, argv);
    else if (!strcmp(c, "mag")) t_mag(argc, argv);
    else if (!strcmp(c, "lcd")) t_lcd(argc, argv);
    else if (!strcmp(c, "btn")) t_btn(argc, argv);
    else if (!strcmp(c, "beep")) t_beep(argc, argv);
    else if (!strcmp(c, "led")) t_led(argc, argv);
    else if (!strcmp(c, "cap")) t_cap(argc, argv);
    else if (!strcmp(c, "ble")) t_ble(argc, argv);
    else if (!strcmp(c, "wifi")) t_wifi(argc, argv);
    else if (!strcmp(c, "sleep")) t_sleep(argc, argv);
    else if (!strcmp(c, "ship")) t_ship(argc, argv);
    else help();
}
