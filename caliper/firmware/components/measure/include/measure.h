/*
 * measure: the caliper's core logic in portable C (no ESP-IDF includes).
 *
 * Units, rounding and formatting; zero and hold; auto-hold when the jaws are still;
 * tolerance profiles with pass/fail; running statistics (Welford). Compiled both into the
 * firmware and into the host tests (test/host).
 *
 * All lengths are integer nanometres (nm). 150 mm = 1.5e8 nm fits easily in int32_t.
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define MEAS_NM_PER_MM   1000000L
#define MEAS_NM_PER_INCH 25400000L

/* AS5311: 2.0 mm pole pair / 1024 quadrature edges (256 A/B pulses x4, datasheet rev 1.12 §7.1,
 * Table 8 "RESinc 10 bit") = 1953.125 nm per count = 15625/8 nm. (The 12-bit SSI is 4x finer.) */
#define MEAS_NM_PER_COUNT_NUM 15625
#define MEAS_NM_PER_COUNT_DEN 8
/* The 12-bit SSI step that the firmware interpolates the count with (SPEC D1): 2.0 mm / 4096 =
 * 488.28125 nm = 15625/32 nm, a quarter count. */
#define MEAS_NM_PER_LSB_NUM 15625
#define MEAS_NM_PER_LSB_DEN 32

typedef enum { MEAS_UNIT_MM = 0, MEAS_UNIT_INCH = 1 } meas_unit_t;

/* ---- arithmetic ------------------------------------------------------------------------ */

/* num / den rounded to nearest, halves away from zero. den must be > 0. */
int64_t meas_div_round(int64_t num, int64_t den);

/* Quadrature counts to nm, rounded to the nearest nm. */
int64_t meas_counts_to_nm(int64_t counts);

/* SSI-interpolated position (quarter counts, 488.28125 nm) to nm, rounded to the nearest nm. */
int64_t meas_lsb_to_nm(int64_t lsb);

/* Saturate to int32 (the GATT and log fields are i32). */
int32_t meas_sat_i32(int64_t v);

/* ---- display format -------------------------------------------------------------------- */

typedef struct {
    meas_unit_t unit;
    uint8_t decimals; /* digits after the point: mm 0..3, inch 2..5 */
} meas_fmt_t;

/* The settings key "decimals" is the mm digit count (1..3, default 2). Inch shows two more
 * digits (default 4, which uses the customary 0.0005 in step). */
meas_fmt_t meas_fmt_for(meas_unit_t unit, uint8_t mm_decimals);

/* Size of one display step in nm: mm/2 -> 10000 (0.01 mm), inch/4 -> 12700 (0.0005 in). */
int32_t meas_step_nm(const meas_fmt_t *fmt);

/* nm rounded to the display step (halves away from zero), still in nm. */
int32_t meas_round_nm(int32_t nm, const meas_fmt_t *fmt);

/* The displayed value as an integer of 10^-decimals units (e.g. 1234 for "12.34 mm"). */
int32_t meas_display_int(int32_t nm, const meas_fmt_t *fmt);

/* Formats the rounded value, e.g. "12.34", "-0.05", "0.4855". A value that rounds to zero
 * prints without a minus sign. Returns the string length, or -1 if buf is too small. */
int meas_format(int32_t nm, const meas_fmt_t *fmt, char *buf, size_t n);

const char *meas_unit_str(meas_unit_t unit); /* "mm" / "in" */

/* ---- zero and hold --------------------------------------------------------------------- */

typedef struct {
    int64_t zero_raw_nm; /* raw sensor position that reads 0 */
    bool hold;
    int32_t held_nm;
} meas_zh_t;

void meas_zh_init(meas_zh_t *z);
void meas_zh_zero(meas_zh_t *z, int64_t raw_nm);              /* the current position reads 0 */
int32_t meas_zh_value(const meas_zh_t *z, int64_t raw_nm);     /* zeroed live value */
int32_t meas_zh_shown(const meas_zh_t *z, int64_t raw_nm);     /* held value if holding */
void meas_zh_set_hold(meas_zh_t *z, bool hold, int64_t raw_nm);

/* ---- auto-hold ------------------------------------------------------------------------- */

/* Fires once when the value has moved by more than rearm_nm since the last firing and then
 * stayed inside +-band_nm for still_ms. */
typedef struct {
    int32_t band_nm;
    uint32_t still_ms;
    int32_t rearm_nm;
    bool have_ref;
    bool armed;
    int32_t ref_nm;
    uint32_t ref_t_ms;
    int32_t fired_nm;
} meas_autohold_t;

void meas_autohold_init(meas_autohold_t *a, int32_t band_nm, uint32_t still_ms, int32_t rearm_nm);
bool meas_autohold_update(meas_autohold_t *a, int32_t nm, uint32_t t_ms);

/* ---- tolerance profiles ---------------------------------------------------------------- */

#define MEAS_PROFILE_NAME_LEN 16

typedef struct {
    uint16_t id; /* 0 = no profile */
    int32_t nominal_nm;
    int32_t tol_minus_nm; /* magnitude; the sign is ignored (lower limit = nominal - |tol_minus|) */
    int32_t tol_plus_nm;  /* magnitude; upper limit = nominal + |tol_plus| */
    char name[MEAS_PROFILE_NAME_LEN + 1];
} meas_profile_t;

typedef enum {
    MEAS_TOL_NONE = 0,  /* no profile selected */
    MEAS_TOL_PASS,      /* inside, in the inner 80 % of the band */
    MEAS_TOL_WARN,      /* inside, but in the outer 20 % of either half (amber) */
    MEAS_TOL_FAIL_LOW,  /* below the lower limit (red) */
    MEAS_TOL_FAIL_HIGH, /* above the upper limit (red) */
} meas_tol_t;

#define MEAS_GAUGE_LIMIT 1000 /* gauge value at either tolerance limit */
#define MEAS_GAUGE_CLAMP 1500
#define MEAS_GAUGE_WARN  800

/* Limits are inclusive. gauge (may be NULL) gets the position in the band, piecewise linear:
 * -1000 at the lower limit, 0 at nominal, +1000 at the upper limit, clamped to +-1500. */
meas_tol_t meas_tol_check(const meas_profile_t *p, int32_t nm, int32_t *gauge);
bool meas_tol_is_pass(meas_tol_t t);
bool meas_tol_is_fail(meas_tol_t t);

/* ---- running statistics (Welford) ------------------------------------------------------ */

typedef struct {
    uint32_t n;
    double mean;
    double m2;
    int32_t min;
    int32_t max;
} meas_stats_t;

void meas_stats_reset(meas_stats_t *s);
void meas_stats_add(meas_stats_t *s, int32_t nm);
double meas_stats_stddev(const meas_stats_t *s); /* sample standard deviation (n-1); 0 if n < 2 */

#ifdef __cplusplus
}
#endif
