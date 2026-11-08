/* measure: units, rounding, zero/hold, auto-hold, tolerance, statistics. Portable C. */
#include "measure.h"

#include <math.h>
#include <stdio.h>
#include <string.h>

/* ---- arithmetic ------------------------------------------------------------------------ */

int64_t meas_div_round(int64_t num, int64_t den)
{
    /* den > 0. Round half away from zero, symmetric for negatives. */
    if (num >= 0) {
        return (num + den / 2) / den;
    }
    return -((-num + den / 2) / den);
}

int64_t meas_counts_to_nm(int64_t counts)
{
    return meas_div_round(counts * MEAS_NM_PER_COUNT_NUM, MEAS_NM_PER_COUNT_DEN);
}

int64_t meas_lsb_to_nm(int64_t lsb)
{
    return meas_div_round(lsb * MEAS_NM_PER_LSB_NUM, MEAS_NM_PER_LSB_DEN);
}

int32_t meas_sat_i32(int64_t v)
{
    if (v > INT32_MAX) {
        return INT32_MAX;
    }
    if (v < INT32_MIN + 1) { /* INT32_MIN is reserved as "invalid" on the wire */
        return INT32_MIN + 1;
    }
    return (int32_t)v;
}

/* ---- display format -------------------------------------------------------------------- */

static int32_t pow10i(int e)
{
    int32_t r = 1;
    while (e-- > 0) {
        r *= 10;
    }
    return r;
}

meas_fmt_t meas_fmt_for(meas_unit_t unit, uint8_t mm_decimals)
{
    if (mm_decimals > 3) {
        mm_decimals = 3;
    }
    meas_fmt_t f = {.unit = unit, .decimals = mm_decimals};
    if (unit == MEAS_UNIT_INCH) {
        f.decimals = (uint8_t)(mm_decimals + 2);
        if (f.decimals < 2) {
            f.decimals = 2;
        }
    }
    return f;
}

/* nm per least-significant displayed digit */
static int32_t lsb_nm(const meas_fmt_t *fmt)
{
    if (fmt->unit == MEAS_UNIT_INCH) {
        uint8_t d = fmt->decimals > 5 ? 5 : fmt->decimals;
        return (int32_t)(MEAS_NM_PER_INCH / pow10i(d)); /* exact for d <= 5 */
    }
    uint8_t d = fmt->decimals > 3 ? 3 : fmt->decimals;
    return pow10i(6 - d);
}

int32_t meas_step_nm(const meas_fmt_t *fmt)
{
    int32_t lsb = lsb_nm(fmt);
    if (fmt->unit == MEAS_UNIT_INCH && fmt->decimals == 4) {
        return lsb * 5; /* 0.0005 in */
    }
    return lsb;
}

int32_t meas_round_nm(int32_t nm, const meas_fmt_t *fmt)
{
    int64_t step = meas_step_nm(fmt);
    return meas_sat_i32(meas_div_round(nm, step) * step);
}

int32_t meas_display_int(int32_t nm, const meas_fmt_t *fmt)
{
    int64_t step = meas_step_nm(fmt);
    int64_t mult = step / lsb_nm(fmt);
    return (int32_t)(meas_div_round(nm, step) * mult);
}

int meas_format(int32_t nm, const meas_fmt_t *fmt, char *buf, size_t n)
{
    int32_t v = meas_display_int(nm, fmt);
    uint8_t d = fmt->decimals;
    if (fmt->unit == MEAS_UNIT_INCH && d > 5) {
        d = 5;
    } else if (fmt->unit == MEAS_UNIT_MM && d > 3) {
        d = 3;
    }
    uint32_t mag = v < 0 ? (uint32_t)(-(int64_t)v) : (uint32_t)v;
    const char *sign = v < 0 ? "-" : "";
    int len;
    if (d == 0) {
        len = snprintf(buf, n, "%s%lu", sign, (unsigned long)mag);
    } else {
        uint32_t div = (uint32_t)pow10i(d);
        len = snprintf(buf, n, "%s%lu.%0*lu", sign, (unsigned long)(mag / div), (int)d,
                       (unsigned long)(mag % div));
    }
    if (len < 0 || (size_t)len >= n) {
        return -1;
    }
    return len;
}

const char *meas_unit_str(meas_unit_t unit)
{
    return unit == MEAS_UNIT_INCH ? "in" : "mm";
}

/* ---- zero and hold --------------------------------------------------------------------- */

void meas_zh_init(meas_zh_t *z)
{
    memset(z, 0, sizeof(*z));
}

void meas_zh_zero(meas_zh_t *z, int64_t raw_nm)
{
    z->zero_raw_nm = raw_nm;
    if (z->hold) {
        z->held_nm = 0;
    }
}

int32_t meas_zh_value(const meas_zh_t *z, int64_t raw_nm)
{
    return meas_sat_i32(raw_nm - z->zero_raw_nm);
}

int32_t meas_zh_shown(const meas_zh_t *z, int64_t raw_nm)
{
    return z->hold ? z->held_nm : meas_zh_value(z, raw_nm);
}

void meas_zh_set_hold(meas_zh_t *z, bool hold, int64_t raw_nm)
{
    if (hold && !z->hold) {
        z->held_nm = meas_zh_value(z, raw_nm);
    }
    z->hold = hold;
}

/* ---- auto-hold ------------------------------------------------------------------------- */

static int64_t absdiff(int32_t a, int32_t b)
{
    int64_t d = (int64_t)a - b;
    return d < 0 ? -d : d;
}

void meas_autohold_init(meas_autohold_t *a, int32_t band_nm, uint32_t still_ms, int32_t rearm_nm)
{
    memset(a, 0, sizeof(*a));
    a->band_nm = band_nm;
    a->still_ms = still_ms;
    a->rearm_nm = rearm_nm;
}

bool meas_autohold_update(meas_autohold_t *a, int32_t nm, uint32_t t_ms)
{
    if (!a->have_ref) {
        a->have_ref = true;
        a->ref_nm = nm;
        a->ref_t_ms = t_ms;
        a->fired_nm = nm; /* must move away first: no hold right after power-up */
        a->armed = false;
        return false;
    }
    if (!a->armed && absdiff(nm, a->fired_nm) > a->rearm_nm) {
        a->armed = true;
    }
    if (absdiff(nm, a->ref_nm) > a->band_nm) {
        a->ref_nm = nm;
        a->ref_t_ms = t_ms;
        return false;
    }
    if (a->armed && (uint32_t)(t_ms - a->ref_t_ms) >= a->still_ms) {
        a->armed = false;
        a->fired_nm = a->ref_nm;
        return true;
    }
    return false;
}

/* ---- tolerance ------------------------------------------------------------------------- */

static int64_t mag64(int32_t v)
{
    return v < 0 ? -(int64_t)v : (int64_t)v;
}

meas_tol_t meas_tol_check(const meas_profile_t *p, int32_t nm, int32_t *gauge)
{
    if (p == NULL || p->id == 0) {
        if (gauge) {
            *gauge = 0;
        }
        return MEAS_TOL_NONE;
    }
    int64_t dev = (int64_t)nm - p->nominal_nm;
    int64_t half = dev < 0 ? mag64(p->tol_minus_nm) : mag64(p->tol_plus_nm);
    int64_t g;
    if (dev == 0) {
        g = 0;
    } else if (half == 0) {
        g = dev < 0 ? -MEAS_GAUGE_CLAMP : MEAS_GAUGE_CLAMP;
    } else {
        g = meas_div_round(dev * MEAS_GAUGE_LIMIT, half);
        if (g > MEAS_GAUGE_CLAMP) {
            g = MEAS_GAUGE_CLAMP;
        } else if (g < -MEAS_GAUGE_CLAMP) {
            g = -MEAS_GAUGE_CLAMP;
        }
    }
    if (gauge) {
        *gauge = (int32_t)g;
    }
    /* Pass/fail is decided on the exact limits, not on the rounded gauge. */
    if (dev < -half) {
        return MEAS_TOL_FAIL_LOW;
    }
    if (dev > half) {
        return MEAS_TOL_FAIL_HIGH;
    }
    /* warn zone: |dev| > 80 % of the half-band, computed exactly */
    if (half > 0 && (dev < 0 ? -dev : dev) * 1000 > half * MEAS_GAUGE_WARN) {
        return MEAS_TOL_WARN;
    }
    return MEAS_TOL_PASS;
}

bool meas_tol_is_pass(meas_tol_t t)
{
    return t == MEAS_TOL_PASS || t == MEAS_TOL_WARN;
}

bool meas_tol_is_fail(meas_tol_t t)
{
    return t == MEAS_TOL_FAIL_LOW || t == MEAS_TOL_FAIL_HIGH;
}

/* ---- statistics ------------------------------------------------------------------------ */

void meas_stats_reset(meas_stats_t *s)
{
    memset(s, 0, sizeof(*s));
}

void meas_stats_add(meas_stats_t *s, int32_t nm)
{
    if (s->n == 0) {
        s->min = nm;
        s->max = nm;
    } else {
        if (nm < s->min) {
            s->min = nm;
        }
        if (nm > s->max) {
            s->max = nm;
        }
    }
    s->n++;
    double x = (double)nm;
    double delta = x - s->mean;
    s->mean += delta / (double)s->n;
    s->m2 += delta * (x - s->mean);
}

double meas_stats_stddev(const meas_stats_t *s)
{
    if (s->n < 2) {
        return 0.0;
    }
    double var = s->m2 / (double)(s->n - 1);
    return var > 0.0 ? sqrt(var) : 0.0;
}
