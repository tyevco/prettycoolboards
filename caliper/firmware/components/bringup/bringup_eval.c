/* Bring-up pass/fail rules and decoders. Portable C (test/host builds it). */
#include "bringup_eval.h"

#include <stdarg.h>
#include <stdio.h>

#include "as5311_proto.h"
#include "board_pins.h"
#include "cap_demod.h"

/* appends to a NUL-terminated buffer, truncating */
static void cat(char *buf, size_t len, const char *fmt, ...) __attribute__((format(printf, 3, 4)));
static void cat(char *buf, size_t len, const char *fmt, ...)
{
    if (!buf || !len) {
        return;
    }
    size_t used = 0;
    while (used < len && buf[used]) {
        used++;
    }
    if (used + 1 >= len) {
        return;
    }
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf + used, len - used, fmt, ap);
    va_end(ap);
}

static void clear(char *buf, size_t len)
{
    if (buf && len) {
        buf[0] = '\0';
    }
}

/* ---- I2C ----------------------------------------------------------------------------------- */

static const bu_i2c_dev_t s_i2c[] = {
    {I2C_ADDR_LSM6DSO, "LSM6DSO"},
    {I2C_ADDR_MAX17048, "MAX17048"},
    {I2C_ADDR_BQ25180, "BQ25180"},
    {I2C_ADDR_IIS2MDC, "IIS2MDC"},
};
#define N_I2C (sizeof(s_i2c) / sizeof(s_i2c[0]))

size_t bu_i2c_expected(const bu_i2c_dev_t **out)
{
    *out = s_i2c;
    return N_I2C;
}

const char *bu_i2c_name(uint8_t addr)
{
    for (size_t i = 0; i < N_I2C; i++) {
        if (s_i2c[i].addr == addr) {
            return s_i2c[i].name;
        }
    }
    return NULL;
}

static bool in_list(const uint8_t *a, size_t n, uint8_t v)
{
    for (size_t i = 0; i < n; i++) {
        if (a[i] == v) {
            return true;
        }
    }
    return false;
}

bool bu_i2c_eval(const uint8_t *found, size_t n, bu_i2c_result_t *r)
{
    r->n_missing = 0;
    r->n_extra = 0;
    for (size_t i = 0; i < N_I2C; i++) {
        if (!in_list(found, n, s_i2c[i].addr) && r->n_missing < BU_I2C_MAX) {
            r->missing[r->n_missing++] = s_i2c[i].addr;
        }
    }
    for (size_t i = 0; i < n; i++) {
        if (!bu_i2c_name(found[i]) && !in_list(r->extra, r->n_extra, found[i]) && r->n_extra < BU_I2C_MAX) {
            r->extra[r->n_extra++] = found[i];
        }
    }
    return r->n_missing == 0 && r->n_extra == 0;
}

/* ---- BQ25180 ------------------------------------------------------------------------------- */

/* SLUSE99C §8.6: STAT0 0x00, STAT1 0x01, FLAG0 0x02 */
#define ST0_TS_OPEN   0x80
#define ST0_CHG_SHIFT 5
#define ST0_ILIM      0x10
#define ST0_VDPPM     0x08
#define ST0_VINDPM    0x04
#define ST0_THERMREG  0x02
#define ST0_PGOOD     0x01
#define ST1_VIN_OVP   0x80
#define ST1_BUVLO     0x40
#define ST1_TS_SHIFT  3
#define ST1_SAFETY    0x04
#define FL0_TS_FAULT  0x80
#define FL0_VIN_OVP   0x04
#define FL0_BUVLO     0x02
#define FL0_BAT_OCP   0x01

bool bu_bq_status(uint8_t stat0, uint8_t stat1, uint8_t flag0, bool ts_enabled, char *buf, size_t len)
{
    static const char *const chg[4] = {"not charging", "CC", "CV", "done"};
    static const char *const ts[4] = {"normal", "HOT/COLD (charging suspended)", "cool (current reduced)",
                                      "warm (voltage reduced)"};
    clear(buf, len);
    bool ok = true;
    unsigned ts_stat = (unsigned)(stat1 >> ST1_TS_SHIFT) & 3u;
    cat(buf, len, "VIN %s, charge %s, TS %s", (stat0 & ST0_PGOOD) ? "good" : "absent",
        chg[(stat0 >> ST0_CHG_SHIFT) & 3u], ts_enabled ? ts[ts_stat] : "disabled");
    if (stat0 & (ST0_ILIM | ST0_VDPPM | ST0_VINDPM | ST0_THERMREG)) {
        cat(buf, len, ", active:%s%s%s%s", (stat0 & ST0_ILIM) ? " ILIM" : "", (stat0 & ST0_VDPPM) ? " VDPPM" : "",
            (stat0 & ST0_VINDPM) ? " VINDPM" : "", (stat0 & ST0_THERMREG) ? " TREG" : "");
    }
    if (stat1 & ST1_BUVLO) {
        cat(buf, len, ", BUVLO (no cell, or VBAT below 3.0 V)");
    }
    if (stat1 & ST1_VIN_OVP) {
        cat(buf, len, "; FAULT VIN over-voltage");
        ok = false;
    }
    if (stat1 & ST1_SAFETY) {
        cat(buf, len, "; FAULT safety timer");
        ok = false;
    }
    if (ts_enabled && (stat0 & ST0_TS_OPEN)) {
        cat(buf, len, "; FAULT TS open (RT1 missing or open)");
        ok = false;
    } else if (ts_enabled && ts_stat == 1) {
        cat(buf, len, "; FAULT TS hot/cold");
        ok = false;
    }
    if (flag0 & FL0_BAT_OCP) {
        cat(buf, len, "; FAULT battery over-current flag");
        ok = false;
    }
    if (flag0 & (FL0_TS_FAULT | FL0_VIN_OVP | FL0_BUVLO)) {
        cat(buf, len, "; flags since last read:%s%s%s", (flag0 & FL0_TS_FAULT) ? " TS" : "",
            (flag0 & FL0_VIN_OVP) ? " VIN_OVP" : "", (flag0 & FL0_BUVLO) ? " BUVLO" : "");
    }
    return ok;
}

size_t bu_regs_check(const bu_reg_t *want, size_t n, const uint8_t *dump, size_t dump_n, char *buf, size_t len)
{
    clear(buf, len);
    size_t bad = 0;
    for (size_t i = 0; i < n; i++) {
        if (want[i].reg >= dump_n) {
            cat(buf, len, "%s0x%02x not read", bad ? ", " : "", want[i].reg);
            bad++;
        } else if (dump[want[i].reg] != want[i].val) {
            cat(buf, len, "%s0x%02x = 0x%02x (want 0x%02x)", bad ? ", " : "", want[i].reg, dump[want[i].reg],
                want[i].val);
            bad++;
        }
    }
    if (!bad) {
        cat(buf, len, "%u registers as written", (unsigned)n);
    }
    return bad;
}

/* ---- MAX17048 ------------------------------------------------------------------------------ */

#define FG_HIBRT_POR    0x8030u
#define FG_CONFIG_SLEEP 0x0080u
#define FG_VRESET_DIS   0x0100u

uint32_t bu_fg_vcell_mv(uint16_t raw)
{
    return (uint32_t)((uint64_t)raw * 78125u / 1000000u); /* 78.125 uV/LSB (32 bits overflow above 4.29 V) */
}

bool bu_fg_eval(const bu_fg_regs_t *r, int32_t vbat_ref_mv, char *buf, size_t len)
{
    clear(buf, len);
    bool ok = true;
    uint32_t mv = bu_fg_vcell_mv(r->vcell);
    cat(buf, len, "VERSION 0x%04x, VCELL %lu mV, SOC %u.%u %%", r->version, (unsigned long)mv, r->soc >> 8,
        ((r->soc & 0xFFu) * 10u) >> 8);
    if ((r->version & 0xFFF0u) != 0x0010u) {
        cat(buf, len, "; FAIL version (0x001x expected)");
        ok = false;
    }
    if (mv < BU_FG_VCELL_MIN_MV || mv > BU_FG_VCELL_MAX_MV) {
        cat(buf, len, "; FAIL VCELL outside %d-%d mV", BU_FG_VCELL_MIN_MV, BU_FG_VCELL_MAX_MV);
        ok = false;
    }
    if (vbat_ref_mv > 0) {
        int32_t d = (int32_t)mv - vbat_ref_mv;
        cat(buf, len, ", %+ld mV vs meter", (long)d);
        if (d > BU_FG_VCELL_TOL_MV || d < -BU_FG_VCELL_TOL_MV) {
            cat(buf, len, "; FAIL more than %d mV off", BU_FG_VCELL_TOL_MV);
            ok = false;
        }
    }
    if (!(r->vreset & FG_VRESET_DIS)) {
        cat(buf, len, "; FAIL VRESET.Dis = 0 (power_init sets it: +1 uA in sleep)");
        ok = false;
    }
    if (r->hibrt != FG_HIBRT_POR) {
        cat(buf, len, "; FAIL HIBRT 0x%04x (0x8030 expected: ship-mode setting left over)", r->hibrt);
        ok = false;
    }
    if (r->config & FG_CONFIG_SLEEP) {
        cat(buf, len, "; FAIL CONFIG.SLEEP set");
        ok = false;
    }
    return ok;
}

/* ---- LSM6DSO accelerometer ----------------------------------------------------------------- */

int32_t bu_imu_mg(int16_t raw)
{
    /* 0.061 mg/LSB at +-2 g (DS12140 Table 2, LA_So): 16-bit two's complement, so 1 g = 16393 LSB
     * and full scale reads 1999 mg */
    int32_t v = (int32_t)raw * 61;
    return v >= 0 ? (v + 500) / 1000 : -((-v + 500) / 1000);
}

uint32_t bu_isqrt(uint64_t v)
{
    uint64_t r = 0, bit = (uint64_t)1 << 62;
    while (bit > v) {
        bit >>= 2;
    }
    while (bit) {
        if (v >= r + bit) {
            v -= r + bit;
            r = (r >> 1) + bit;
        } else {
            r >>= 1;
        }
        bit >>= 2;
    }
    return (uint32_t)r;
}

uint32_t bu_imu_norm_mg(int32_t x, int32_t y, int32_t z)
{
    int64_t s = (int64_t)x * x + (int64_t)y * y + (int64_t)z * z;
    return bu_isqrt((uint64_t)s);
}

bool bu_imu_still_ok(uint32_t norm_mg)
{
    return norm_mg >= BU_IMU_G_MIN_MG && norm_mg <= BU_IMU_G_MAX_MG;
}

void bu_imu_span_init(bu_imu_span_t *s)
{
    *s = (bu_imu_span_t){0};
}

void bu_imu_span_feed(bu_imu_span_t *s, const int32_t mg[3])
{
    for (int i = 0; i < 3; i++) {
        if (!s->have || mg[i] < s->min[i]) {
            s->min[i] = mg[i];
        }
        if (!s->have || mg[i] > s->max[i]) {
            s->max[i] = mg[i];
        }
    }
    s->have = true;
    s->n++;
}

int32_t bu_imu_span_max(const bu_imu_span_t *s)
{
    int32_t m = 0;
    for (int i = 0; s->have && i < 3; i++) {
        if (s->max[i] - s->min[i] > m) {
            m = s->max[i] - s->min[i];
        }
    }
    return m;
}

bool bu_imu_move_eval(const bu_imu_span_t *s, bool int1_low_seen, char *buf, size_t len)
{
    clear(buf, len);
    int32_t span = bu_imu_span_max(s);
    cat(buf, len, "%lu samples, swing X %ld Y %ld Z %ld mg, INT1 %s", (unsigned long)s->n,
        s->have ? (long)(s->max[0] - s->min[0]) : 0L, s->have ? (long)(s->max[1] - s->min[1]) : 0L,
        s->have ? (long)(s->max[2] - s->min[2]) : 0L, int1_low_seen ? "went low (wake-up)" : "stayed high");
    bool ok = span >= BU_IMU_MOVE_MG && int1_low_seen;
    if (span < BU_IMU_MOVE_MG) {
        cat(buf, len, "; FAIL largest swing %ld < %d mg (turn the board over)", (long)span, BU_IMU_MOVE_MG);
    }
    if (!int1_low_seen) {
        cat(buf, len, "; FAIL no wake-up interrupt on IMU_INT1");
    }
    return ok;
}

/* ---- LSM6DSO gyroscope --------------------------------------------------------------------- */

uint32_t bu_gyro_udps_per_lsb(uint8_t ctrl2_g)
{
    static const uint32_t fs_g[4] = {8750, 17500, 35000, 70000}; /* +-250 / 500 / 1000 / 2000 dps */
    return (ctrl2_g & 0x02) ? 4375 : fs_g[(ctrl2_g >> 2) & 0x03];
}

int32_t bu_gyro_mdps(int16_t raw, uint8_t ctrl2_g)
{
    int64_t v = (int64_t)raw * (int64_t)bu_gyro_udps_per_lsb(ctrl2_g);
    return (int32_t)(v >= 0 ? (v + 500) / 1000 : -((-v + 500) / 1000));
}

bool bu_gyro_running(uint8_t ctrl2_g)
{
    return (ctrl2_g & 0xF0) != 0;
}

void bu_gyro_stats_init(bu_gyro_stats_t *s)
{
    *s = (bu_gyro_stats_t){0};
}

void bu_gyro_stats_feed(bu_gyro_stats_t *s, const int32_t mdps[3])
{
    for (int i = 0; i < 3; i++) {
        if (!s->have || mdps[i] < s->min[i]) {
            s->min[i] = mdps[i];
        }
        if (!s->have || mdps[i] > s->max[i]) {
            s->max[i] = mdps[i];
        }
        s->sum[i] += mdps[i];
    }
    s->have = true;
    s->n++;
}

int32_t bu_gyro_stats_mean(const bu_gyro_stats_t *s, int axis)
{
    if (!s->n) {
        return 0;
    }
    int64_t v = s->sum[axis], n = (int64_t)s->n;
    return (int32_t)(v >= 0 ? (v + n / 2) / n : -((-v + n / 2) / n));
}

static int32_t abs32(int32_t v)
{
    return v < 0 ? -v : v;
}

bool bu_gyro_rest_eval(const bu_gyro_stats_t *s, char *buf, size_t len)
{
    static const char axis[3] = {'X', 'Y', 'Z'};
    clear(buf, len);
    int32_t mean[3], pp[3];
    bool flat = true;
    for (int i = 0; i < 3; i++) {
        mean[i] = bu_gyro_stats_mean(s, i);
        pp[i] = s->have ? s->max[i] - s->min[i] : 0;
        flat = flat && pp[i] == 0;
    }
    cat(buf, len, "%lu samples, mean X %ld Y %ld Z %ld mdps, p-p X %ld Y %ld Z %ld mdps", (unsigned long)s->n,
        (long)mean[0], (long)mean[1], (long)mean[2], (long)pp[0], (long)pp[1], (long)pp[2]);
    if (s->n < BU_GYRO_MIN_SAMPLES) {
        cat(buf, len, "; FAIL only %lu samples (< %d)", (unsigned long)s->n, BU_GYRO_MIN_SAMPLES);
        return false;
    }
    if (flat) {
        cat(buf, len, "; FAIL no axis ever changed: the gyroscope is powered down or not updating");
        return false;
    }
    bool ok = true;
    for (int i = 0; i < 3; i++) {
        if (pp[i] > BU_GYRO_STILL_PP_MDPS) {
            cat(buf, len, "; FAIL %c moved %ld mdps p-p (> %d): it was not lying still, repeat", axis[i], (long)pp[i],
                BU_GYRO_STILL_PP_MDPS);
            ok = false;
        } else if (abs32(mean[i]) > BU_GYRO_ZERO_MAX_MDPS) {
            cat(buf, len, "; FAIL %c zero-rate level %ld mdps (limit +-%d)", axis[i], (long)mean[i],
                BU_GYRO_ZERO_MAX_MDPS);
            ok = false;
        }
    }
    return ok;
}

bool bu_gyro_turn_eval(const bu_gyro_stats_t *s, char *buf, size_t len)
{
    clear(buf, len);
    int32_t peak = 0;
    for (int i = 0; s->have && i < 3; i++) {
        peak = abs32(s->min[i]) > peak ? abs32(s->min[i]) : peak;
        peak = abs32(s->max[i]) > peak ? abs32(s->max[i]) : peak;
    }
    cat(buf, len, "%lu samples, X %+ld..%+ld Y %+ld..%+ld Z %+ld..%+ld dps", (unsigned long)s->n,
        s->have ? (long)(s->min[0] / 1000) : 0L, s->have ? (long)(s->max[0] / 1000) : 0L,
        s->have ? (long)(s->min[1] / 1000) : 0L, s->have ? (long)(s->max[1] / 1000) : 0L,
        s->have ? (long)(s->min[2] / 1000) : 0L, s->have ? (long)(s->max[2] / 1000) : 0L);
    if (peak < BU_GYRO_TURN_MDPS) {
        cat(buf, len, "; FAIL largest rate %ld dps < %d dps (turn the board faster)", (long)(peak / 1000),
            BU_GYRO_TURN_MDPS / 1000);
        return false;
    }
    return true;
}

/* ---- IIS2MDC compass ----------------------------------------------------------------------- */

int32_t bu_compass_nt(int16_t raw)
{
    /* 1.5 mgauss/LSB (iis2mdc_reg.c, iis2mdc_from_lsb_to_mgauss), 1 mgauss = 100 nT: full scale
     * reads 4915 uT */
    return (int32_t)raw * 150;
}

bool bu_compass_running(uint8_t cfg_reg_a)
{
    return (cfg_reg_a & 0x03) == 0;
}

bool bu_compass_eval(const bu_gyro_stats_t *s, char *buf, size_t len)
{
    static const char axis[3] = {'X', 'Y', 'Z'};
    clear(buf, len);
    int32_t mean[3];
    bool flat = true;
    for (int i = 0; i < 3; i++) {
        mean[i] = bu_gyro_stats_mean(s, i);
        flat = flat && (!s->have || s->max[i] == s->min[i]);
    }
    uint32_t norm = bu_imu_norm_mg(mean[0], mean[1], mean[2]); /* nT in, nT out */
    cat(buf, len, "%lu samples, X %.1f Y %.1f Z %.1f uT, |B| %.1f uT (limit %d-%d)", (unsigned long)s->n,
        mean[0] / 1000.0, mean[1] / 1000.0, mean[2] / 1000.0, norm / 1000.0, BU_COMPASS_MIN_UT, BU_COMPASS_MAX_UT);
    if (s->n < BU_COMPASS_MIN_SAMPLES) {
        cat(buf, len, "; FAIL only %lu samples (< %d)", (unsigned long)s->n, BU_COMPASS_MIN_SAMPLES);
        return false;
    }
    if (flat) {
        cat(buf, len, "; FAIL no axis ever changed: the part is in power-down or not updating");
        return false;
    }
    bool ok = true;
    for (int i = 0; i < 3; i++) {
        if (s->max[i] >= BU_COMPASS_CLIP_NT || s->min[i] <= -BU_COMPASS_CLIP_NT) {
            cat(buf, len, "; FAIL %c at full scale: a magnet on the part, or a dead axis", axis[i]);
            ok = false;
        }
    }
    if (norm < BU_COMPASS_MIN_UT * 1000u || norm > BU_COMPASS_MAX_UT * 1000u) {
        cat(buf, len, "; FAIL |B| outside the window");
        ok = false;
    }
    return ok;
}

/* ---- buttons ------------------------------------------------------------------------------- */

const char *const bu_btn_names[BU_BTN_N] = {"ZERO", "HOLD", "MODE"};

void bu_btn_init(bu_btn_t *b, uint8_t pressed_now, uint32_t t_ms)
{
    *b = (bu_btn_t){0};
    b->pressed = pressed_now;
    b->stuck = pressed_now;
    for (int i = 0; i < BU_BTN_N; i++) {
        b->t_down[i] = t_ms;
    }
}

uint8_t bu_btn_feed(bu_btn_t *b, uint8_t pressed, uint32_t t_ms)
{
    uint8_t done = 0;
    for (int i = 0; i < BU_BTN_N; i++) {
        uint8_t bit = (uint8_t)(1u << i);
        bool was = (b->pressed & bit) != 0, now = (pressed & bit) != 0;
        if (!was && now) {
            b->t_down[i] = t_ms;
        } else if (was && !now && !(b->stuck & bit)) {
            uint32_t d = t_ms - b->t_down[i];
            if (d >= BU_BTN_MIN_MS) {
                b->presses[i]++;
                done |= bit;
                if (d > b->longest_ms[i]) {
                    b->longest_ms[i] = d;
                }
            } else {
                b->glitches[i]++;
            }
        } else if (was && !now) {
            b->stuck &= (uint8_t)~bit; /* released after starting down: count it from the next press */
        }
    }
    b->pressed = pressed & ((1u << BU_BTN_N) - 1u);
    return done;
}

bool bu_btn_all_pressed(const bu_btn_t *b)
{
    for (int i = 0; i < BU_BTN_N; i++) {
        if (!b->presses[i]) {
            return false;
        }
    }
    return true;
}

bool bu_btn_eval(const bu_btn_t *b, char *buf, size_t len)
{
    clear(buf, len);
    bool ok = true;
    for (int i = 0; i < BU_BTN_N; i++) {
        cat(buf, len, "%s%s %u press%s (longest %lu ms)", i ? ", " : "", bu_btn_names[i], b->presses[i],
            b->presses[i] == 1 ? "" : "es", (unsigned long)b->longest_ms[i]);
        if (b->glitches[i]) {
            cat(buf, len, " %u glitch%s", b->glitches[i], b->glitches[i] == 1 ? "" : "es");
        }
        if (!b->presses[i]) {
            ok = false;
        }
    }
    if (b->stuck) {
        cat(buf, len, "; FAIL down at the start:%s%s%s", (b->stuck & 1u) ? " ZERO" : "", (b->stuck & 2u) ? " HOLD" : "",
            (b->stuck & 4u) ? " MODE" : "");
        ok = false;
    }
    if (!ok && !b->stuck) {
        cat(buf, len, "; FAIL not every button pressed");
    }
    return ok;
}

/* ---- AS5311 -------------------------------------------------------------------------------- */

int bu_as5311_frame_text(uint32_t raw18, char *buf, size_t len)
{
    static const char *const field[3] = {"field OK", "field MARGINAL (yellow)", "field BAD (red)"};
    as5311_frame_t f;
    as5311_decode(raw18, &f);
    uint32_t um = (uint32_t)f.pos * 2000u / AS5311_SSI_STEPS; /* in-pole position, um */
    clear(buf, len);
    cat(buf, len, "0x%05lx pos %u (%lu.%03lu mm) OCF %d COF %d LIN %d INC %d DEC %d PAR %s: %s%s",
        (unsigned long)(raw18 & 0x3FFFFu), f.pos, (unsigned long)(um / 1000u), (unsigned long)(um % 1000u), f.ocf,
        f.cof, f.lin, f.mag_inc, f.mag_dec, f.parity_ok ? "ok" : "BAD", field[as5311_field(&f)],
        as5311_frame_valid(&f) ? "" : ", frame INVALID");
    return (int)as5311_frame_valid(&f);
}

bool bu_as5311_eval(uint32_t frames_ok, uint32_t frames_bad, uint32_t last_raw, char *buf, size_t len)
{
    clear(buf, len);
    uint32_t total = frames_ok + frames_bad;
    uint32_t ppm = total ? (uint32_t)((uint64_t)frames_bad * 1000000u / total) : 1000000u;
    as5311_frame_t f;
    as5311_decode(last_raw, &f);
    bool ok = true;
    cat(buf, len, "%lu frames, %lu bad", (unsigned long)total, (unsigned long)frames_bad);
    if (total < BU_MAG_MIN_FRAMES) {
        cat(buf, len, "; FAIL fewer than %d frames (sensor unpowered or the task stopped)", BU_MAG_MIN_FRAMES);
        ok = false;
    }
    if (ppm > BU_MAG_MAX_BAD_PPM) {
        cat(buf, len, "; FAIL more than 1 %% bad frames");
        ok = false;
    }
    if (!as5311_frame_valid(&f)) {
        cat(buf, len, "; FAIL last frame invalid (%s%s%s)", f.parity_ok ? "" : "parity ", f.ocf ? "" : "OCF=0 ",
            f.cof ? "COF=1" : "");
        ok = false;
    } else if (as5311_field(&f) != AS5311_FIELD_OK) {
        cat(buf, len, "; FAIL magnetic field %s: check the gap (mechanical.md §7)",
            as5311_field(&f) == AS5311_FIELD_BAD ? "out of range (red)" : "marginal (yellow)");
        ok = false;
    }
    return ok;
}

/* ---- capacitive ---------------------------------------------------------------------------- */

bool bu_cap_eval(uint32_t bursts, uint32_t valid, float mean_lsb, float amp_fwd, float amp_rev, bool with_scale,
                 char *buf, size_t len)
{
    clear(buf, len);
    bool ok = true;
    uint32_t pct = bursts ? (uint32_t)((uint64_t)valid * 100u / bursts) : 0u;
    cat(buf, len, "%lu bursts, %lu valid (%lu %%), DC %d LSB, amplitude fwd %.1f rev %.1f LSB", (unsigned long)bursts,
        (unsigned long)valid, (unsigned long)pct, (int)mean_lsb, (double)amp_fwd, (double)amp_rev);
    if (!bursts) {
        cat(buf, len, "; FAIL no burst ran");
        return false;
    }
    if (mean_lsb < (float)BU_CAP_MEAN_MIN || mean_lsb > (float)BU_CAP_MEAN_MAX) {
        cat(buf, len, "; FAIL DC level outside %d-%d LSB (CAP_VREF / U40 / R84-R85)", BU_CAP_MEAN_MIN, BU_CAP_MEAN_MAX);
        ok = false;
    }
    if (with_scale && (pct < BU_CAP_VALID_MIN_PCT || amp_fwd < CAP_MIN_AMP_LSB || amp_rev < CAP_MIN_AMP_LSB)) {
        cat(buf, len, "; FAIL with the scale fitted: < %d %% valid or amplitude < %.0f LSB", BU_CAP_VALID_MIN_PCT,
            (double)CAP_MIN_AMP_LSB);
        ok = false;
    }
    return ok;
}
