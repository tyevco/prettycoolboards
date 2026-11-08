/*
 * Host unit tests for the portable firmware modules:
 *   measure (units, rounding, hold, auto-hold, tolerance, stats), logrec (pack, ring), gatt_codec,
 *   settings (JSON), csv, buttons, hid_keymap, as5311_proto, cap_demod.
 * Build: see test/host/CMakeLists.txt (or `make -C test/host`).
 */
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "as5311_proto.h"
#include "buttons.h"
#include "caliper_gatt.h"
#include "cap_demod.h"
#include "csv.h"
#include "gatt_codec.h"
#include "hid_keymap.h"
#include "logrec.h"
#include "measure.h"
#include "settings.h"
#include "tiny_test.h"

int tt_failures = 0;
int tt_checks = 0;
const char *tt_current = "";

static const char *fmt(int32_t nm, meas_unit_t u, uint8_t mm_dec)
{
    static char buf[4][24];
    static int i;
    i = (i + 1) & 3;
    meas_fmt_t f = meas_fmt_for(u, mm_dec);
    if (meas_format(nm, &f, buf[i], sizeof(buf[i])) < 0) {
        strcpy(buf[i], "<overflow>");
    }
    return buf[i];
}

/* ---- measure: conversion and rounding ------------------------------------------------- */

static void test_counts_to_nm(void)
{
    CHECK_EQ_INT(meas_counts_to_nm(0), 0);
    /* AS5311 incremental: 1024 counts per 2 mm pole pair = 1953.125 nm per count */
    CHECK_EQ_INT(meas_counts_to_nm(1), 1953);     /* 1953.125 */
    CHECK_EQ_INT(meas_counts_to_nm(2), 3906);     /* 3906.25 */
    CHECK_EQ_INT(meas_counts_to_nm(4), 7813);     /* 7812.5: half away from zero */
    CHECK_EQ_INT(meas_counts_to_nm(-4), -7813);
    CHECK_EQ_INT(meas_counts_to_nm(-1), -1953);
    CHECK_EQ_INT(meas_counts_to_nm(-3), -5859);   /* -5859.375 */
    CHECK_EQ_INT(meas_counts_to_nm(1024), 2000000); /* one pole pair = 2 mm exactly */
    CHECK_EQ_INT(meas_counts_to_nm(76800), 150000000); /* 150 mm */
    CHECK_EQ_INT(meas_counts_to_nm(-76800), -150000000);
    /* intermediates are int64: a count far beyond the beam still converts without overflow */
    CHECK_EQ_INT(meas_counts_to_nm(1100000000LL), 2148437500000LL);
    /* the symmetric rounding: f(-x) == -f(x) for a sweep */
    int sym_ok = 1;
    for (int64_t c = -5000; c <= 5000; c++) {
        if (meas_counts_to_nm(-c) != -meas_counts_to_nm(c)) {
            sym_ok = 0;
        }
    }
    CHECK(sym_ok);
    CHECK_EQ_INT(meas_sat_i32(5000000000LL), INT32_MAX);
    CHECK_EQ_INT(meas_sat_i32(-5000000000LL), INT32_MIN + 1); /* INT32_MIN stays "invalid" */
}

static void test_mm_rounding(void)
{
    CHECK_EQ_STR(fmt(0, MEAS_UNIT_MM, 2), "0.00");
    CHECK_EQ_STR(fmt(12344999, MEAS_UNIT_MM, 2), "12.34");
    CHECK_EQ_STR(fmt(12345000, MEAS_UNIT_MM, 2), "12.35");  /* half rounds away from zero */
    CHECK_EQ_STR(fmt(-12345000, MEAS_UNIT_MM, 2), "-12.35");
    CHECK_EQ_STR(fmt(-12344999, MEAS_UNIT_MM, 2), "-12.34");
    CHECK_EQ_STR(fmt(-4999, MEAS_UNIT_MM, 2), "0.00");      /* no "-0.00" */
    CHECK_EQ_STR(fmt(-5000, MEAS_UNIT_MM, 2), "-0.01");
    CHECK_EQ_STR(fmt(5000, MEAS_UNIT_MM, 2), "0.01");
    CHECK_EQ_STR(fmt(-50000, MEAS_UNIT_MM, 2), "-0.05");
    CHECK_EQ_STR(fmt(150000000, MEAS_UNIT_MM, 2), "150.00");
    CHECK_EQ_STR(fmt(-150000000, MEAS_UNIT_MM, 2), "-150.00");
    CHECK_EQ_STR(fmt(1234567, MEAS_UNIT_MM, 3), "1.235");
    CHECK_EQ_STR(fmt(1250000, MEAS_UNIT_MM, 1), "1.3");
    CHECK_EQ_STR(fmt(-1250000, MEAS_UNIT_MM, 1), "-1.3");
    CHECK_EQ_STR(fmt(999995000, MEAS_UNIT_MM, 2), "1000.00"); /* carry into a new digit */

    meas_fmt_t f = meas_fmt_for(MEAS_UNIT_MM, 2);
    CHECK_EQ_INT(meas_step_nm(&f), 10000);
    CHECK_EQ_INT(meas_round_nm(12345000, &f), 12350000);
    CHECK_EQ_INT(meas_round_nm(-12345000, &f), -12350000);
    CHECK_EQ_INT(meas_display_int(12344999, &f), 1234);
    char small[4];
    CHECK_EQ_INT(meas_format(12345000, &f, small, sizeof(small)), -1); /* buffer too small */
}

static void test_inch_display(void)
{
    meas_fmt_t f = meas_fmt_for(MEAS_UNIT_INCH, 2);
    CHECK_EQ_INT(f.decimals, 4);
    CHECK_EQ_INT(meas_step_nm(&f), 12700); /* 0.0005 in */
    CHECK_EQ_STR(fmt(25400000, MEAS_UNIT_INCH, 2), "1.0000");
    CHECK_EQ_STR(fmt(12700, MEAS_UNIT_INCH, 2), "0.0005");
    CHECK_EQ_STR(fmt(6349, MEAS_UNIT_INCH, 2), "0.0000");
    CHECK_EQ_STR(fmt(6350, MEAS_UNIT_INCH, 2), "0.0005");  /* half step rounds up */
    CHECK_EQ_STR(fmt(-6350, MEAS_UNIT_INCH, 2), "-0.0005");
    CHECK_EQ_STR(fmt(-6349, MEAS_UNIT_INCH, 2), "0.0000");
    CHECK_EQ_STR(fmt(12345000, MEAS_UNIT_INCH, 2), "0.4860"); /* 0.48602 in */
    CHECK_EQ_STR(fmt(150000000, MEAS_UNIT_INCH, 2), "5.9055"); /* 5.90551 in */
    CHECK_EQ_STR(fmt(-150000000, MEAS_UNIT_INCH, 2), "-5.9055");
    CHECK_EQ_STR(fmt(19050, MEAS_UNIT_INCH, 2), "0.0010");    /* 0.00075 in: 1.5 steps -> 2 */
    /* every displayed inch value is a multiple of 5 in the last digit */
    int all5 = 1;
    for (int32_t nm = -300000; nm <= 300000; nm += 77) {
        if (meas_display_int(nm, &f) % 5 != 0) {
            all5 = 0;
        }
    }
    CHECK(all5);
    CHECK_EQ_STR(fmt(25400000, MEAS_UNIT_INCH, 1), "1.000");
    CHECK_EQ_STR(fmt(254, MEAS_UNIT_INCH, 3), "0.00001");
    CHECK_EQ_STR(meas_unit_str(MEAS_UNIT_INCH), "in");
    CHECK_EQ_STR(meas_unit_str(MEAS_UNIT_MM), "mm");
}

/* ---- measure: zero, hold, auto-hold ---------------------------------------------------- */

static void test_zero_hold(void)
{
    meas_zh_t z;
    meas_zh_init(&z);
    CHECK_EQ_INT(meas_zh_value(&z, 1234567), 1234567);
    meas_zh_zero(&z, 1234567);
    CHECK_EQ_INT(meas_zh_value(&z, 1234567), 0);
    CHECK_EQ_INT(meas_zh_value(&z, 1000000), -234567); /* negative after zeroing */
    meas_zh_set_hold(&z, true, 2234567);
    CHECK_EQ_INT(meas_zh_shown(&z, 9999999), 1000000);  /* held */
    meas_zh_set_hold(&z, true, 5000000);                 /* already holding: unchanged */
    CHECK_EQ_INT(meas_zh_shown(&z, 0), 1000000);
    meas_zh_set_hold(&z, false, 0);
    CHECK_EQ_INT(meas_zh_shown(&z, 2234567), 1000000);
    CHECK_EQ_INT(meas_zh_shown(&z, 1234567), 0);
}

static void test_autohold(void)
{
    meas_autohold_t a;
    meas_autohold_init(&a, 5000, 800, 100000);
    int fires = 0;
    uint32_t t = 0;
    for (; t < 1000; t += 10) {
        fires += meas_autohold_update(&a, (int32_t)(t % 3) * 1000, t); /* still at power-up */
    }
    CHECK_EQ_INT(fires, 0); /* no hold before the jaws have moved */
    /* move to 25 mm, then sit with +-2 um jitter */
    uint32_t fired_at = 0;
    for (; t < 3000; t += 10) {
        int32_t nm = 25000000 + (int32_t)((t / 10) % 5) * 1000 - 2000;
        if (meas_autohold_update(&a, nm, t)) {
            fires++;
            fired_at = t;
        }
    }
    CHECK_EQ_INT(fires, 1);
    CHECK_EQ_INT(fired_at, 1800);
    /* moving by less than the re-arm distance and settling again does not fire */
    for (; t < 5000; t += 10) {
        fires += meas_autohold_update(&a, 25050000, t);
    }
    CHECK_EQ_INT(fires, 1);
    /* moving away and settling fires again */
    for (; t < 7000; t += 10) {
        fires += meas_autohold_update(&a, 40000000, t);
    }
    CHECK_EQ_INT(fires, 2);
}

/* ---- measure: tolerance ---------------------------------------------------------------- */

static void test_tolerance(void)
{
    meas_profile_t p = {.id = 7, .nominal_nm = 10000000, .tol_minus_nm = 20000, .tol_plus_nm = 30000};
    int32_t g;
    CHECK_EQ_INT(meas_tol_check(&p, 10000000, &g), MEAS_TOL_PASS);
    CHECK_EQ_INT(g, 0);
    CHECK_EQ_INT(meas_tol_check(&p, 9980000, &g), MEAS_TOL_WARN); /* lower limit is inclusive */
    CHECK_EQ_INT(g, -1000);
    CHECK_EQ_INT(meas_tol_check(&p, 9979999, &g), MEAS_TOL_FAIL_LOW);
    CHECK_EQ_INT(meas_tol_check(&p, 10030000, &g), MEAS_TOL_WARN); /* upper limit is inclusive */
    CHECK_EQ_INT(g, 1000);
    CHECK_EQ_INT(meas_tol_check(&p, 10030001, &g), MEAS_TOL_FAIL_HIGH);
    CHECK_EQ_INT(meas_tol_check(&p, 10015000, &g), MEAS_TOL_PASS);
    CHECK_EQ_INT(g, 500);
    CHECK_EQ_INT(meas_tol_check(&p, 9984000, &g), MEAS_TOL_PASS); /* exactly 80 %: still green */
    CHECK_EQ_INT(meas_tol_check(&p, 9983999, &g), MEAS_TOL_WARN);
    CHECK_EQ_INT(meas_tol_check(&p, 10060000, &g), MEAS_TOL_FAIL_HIGH);
    CHECK_EQ_INT(g, MEAS_GAUGE_CLAMP);
    CHECK_EQ_INT(meas_tol_check(&p, -150000000, &g), MEAS_TOL_FAIL_LOW);
    CHECK_EQ_INT(g, -MEAS_GAUGE_CLAMP);
    CHECK(meas_tol_is_pass(MEAS_TOL_WARN) && !meas_tol_is_fail(MEAS_TOL_WARN));
    CHECK(meas_tol_is_fail(MEAS_TOL_FAIL_LOW) && !meas_tol_is_pass(MEAS_TOL_FAIL_HIGH));

    /* a negative tol_minus means the same as its magnitude */
    meas_profile_t pn = p;
    pn.tol_minus_nm = -20000;
    CHECK_EQ_INT(meas_tol_check(&pn, 9980000, NULL), MEAS_TOL_WARN);
    CHECK_EQ_INT(meas_tol_check(&pn, 9979999, NULL), MEAS_TOL_FAIL_LOW);

    /* negative nominal (a step/depth below the zero) */
    meas_profile_t neg = {.id = 2, .nominal_nm = -5000000, .tol_minus_nm = 10000, .tol_plus_nm = 10000};
    CHECK_EQ_INT(meas_tol_check(&neg, -5010000, NULL), MEAS_TOL_WARN);
    CHECK_EQ_INT(meas_tol_check(&neg, -5010001, NULL), MEAS_TOL_FAIL_LOW);
    CHECK_EQ_INT(meas_tol_check(&neg, -4990001, NULL), MEAS_TOL_WARN);
    CHECK_EQ_INT(meas_tol_check(&neg, -4989999, NULL), MEAS_TOL_FAIL_HIGH);

    /* one-sided: +0 / -0.05 */
    meas_profile_t one = {.id = 3, .nominal_nm = 6000000, .tol_minus_nm = 50000, .tol_plus_nm = 0};
    CHECK_EQ_INT(meas_tol_check(&one, 6000000, &g), MEAS_TOL_PASS);
    CHECK_EQ_INT(meas_tol_check(&one, 6000001, &g), MEAS_TOL_FAIL_HIGH);
    CHECK_EQ_INT(g, MEAS_GAUGE_CLAMP);

    /* no profile */
    meas_profile_t none = {0};
    CHECK_EQ_INT(meas_tol_check(&none, 123, &g), MEAS_TOL_NONE);
    CHECK_EQ_INT(meas_tol_check(NULL, 123, &g), MEAS_TOL_NONE);

    /* rounding before the check (the firmware compares the displayed value): 9.97951 mm shows
     * 9.98 mm and passes, although the raw value is below the limit */
    meas_fmt_t f = meas_fmt_for(MEAS_UNIT_MM, 2);
    CHECK_EQ_INT(meas_tol_check(&p, meas_round_nm(9979510, &f), NULL), MEAS_TOL_WARN);
    CHECK_EQ_INT(meas_tol_check(&p, meas_round_nm(9974999, &f), NULL), MEAS_TOL_FAIL_LOW);
}

/* ---- measure: stats -------------------------------------------------------------------- */

static void test_stats(void)
{
    meas_stats_t s;
    meas_stats_reset(&s);
    CHECK_EQ_INT(s.n, 0);
    CHECK_NEAR(meas_stats_stddev(&s), 0.0, 0.0);
    meas_stats_add(&s, -42);
    CHECK_EQ_INT(s.min, -42);
    CHECK_EQ_INT(s.max, -42);
    CHECK_NEAR(meas_stats_stddev(&s), 0.0, 0.0);

    /* textbook: 2,4,4,4,5,5,7,9 -> mean 5, sample sd = sqrt(32/7) */
    meas_stats_reset(&s);
    int v[] = {2, 4, 4, 4, 5, 5, 7, 9};
    for (int i = 0; i < 8; i++) {
        meas_stats_add(&s, v[i]);
    }
    CHECK_NEAR(s.mean, 5.0, 1e-12);
    CHECK_NEAR(meas_stats_stddev(&s), sqrt(32.0 / 7.0), 1e-12);
    CHECK_EQ_INT(s.min, 2);
    CHECK_EQ_INT(s.max, 9);

    /* Welford vs a two-pass naive computation, on a large offset (150 mm) with small scatter,
     * where the one-pass sum-of-squares formula loses precision. */
    meas_stats_reset(&s);
    enum { N = 5000 };
    static int32_t x[N];
    srand(12345);
    long double sum = 0;
    for (int i = 0; i < N; i++) {
        x[i] = 149990000 + (rand() % 20001) - 10000 + ((i & 1) ? -3 : 3);
        sum += x[i];
        meas_stats_add(&s, x[i]);
    }
    long double mean = sum / N, ss = 0;
    int32_t mn = x[0], mx = x[0];
    for (int i = 0; i < N; i++) {
        ss += (x[i] - mean) * (x[i] - mean);
        if (x[i] < mn) mn = x[i];
        if (x[i] > mx) mx = x[i];
    }
    double sd = (double)sqrtl(ss / (N - 1));
    CHECK_EQ_INT(s.n, N);
    CHECK_NEAR(s.mean, (double)mean, 1e-6);
    CHECK_NEAR(meas_stats_stddev(&s), sd, sd * 1e-9);
    CHECK_EQ_INT(s.min, mn);
    CHECK_EQ_INT(s.max, mx);

    /* naive E[x^2]-E[x]^2 in float shows why Welford is used (not asserted on a specific value) */
    float fs = 0, fss = 0;
    for (int i = 0; i < N; i++) {
        fs += (float)x[i];
        fss += (float)x[i] * (float)x[i];
    }
    double naive_var = ((double)fss - (double)fs * fs / N) / (N - 1);
    printf("    (float one-pass variance %.3g vs true %.3g)\n", naive_var, sd * sd);
}

/* ---- logrec ---------------------------------------------------------------------------- */

static void test_logrec_pack(void)
{
    logrec_t r = {.seq = 0x04030201u, .unix_s = 1700000000u, .value_nm = -2, .unit = 1, .flags = 0x23,
                  .profile_id = 0xBEEF};
    uint8_t b[LOGREC_SIZE];
    logrec_pack(&r, b);
    const uint8_t exp[16] = {0x01, 0x02, 0x03, 0x04, 0x00, 0xF1, 0x53, 0x65,
                             0xFE, 0xFF, 0xFF, 0xFF, 0x01, 0x23, 0xEF, 0xBE};
    CHECK(memcmp(b, exp, 16) == 0);
    logrec_t u;
    logrec_unpack(b, &u);
    CHECK_EQ_INT(u.seq, r.seq);
    CHECK_EQ_INT(u.unix_s, r.unix_s);
    CHECK_EQ_INT(u.value_nm, r.value_nm);
    CHECK_EQ_INT(u.unit, r.unit);
    CHECK_EQ_INT(u.flags, r.flags);
    CHECK_EQ_INT(u.profile_id, r.profile_id);

    /* round trip of extremes */
    logrec_t e = {.seq = 0xFFFFFFFEu, .unix_s = 0xFFFFFFFFu, .value_nm = INT32_MIN, .unit = 0, .flags = 0xFF,
                  .profile_id = 0};
    logrec_pack(&e, b);
    logrec_unpack(b, &u);
    CHECK(u.seq == e.seq && u.unix_s == e.unix_s && u.value_nm == e.value_nm && u.flags == 0xFF);

    logrec_t m = logrec_end_marker();
    logrec_pack(&m, b);
    CHECK(b[0] == 0xFF && b[1] == 0xFF && b[2] == 0xFF && b[3] == 0xFF && b[4] == 0 && b[15] == 0);
}

static void test_ring_wraparound(void)
{
    ring_t r;
    ring_init(&r, 4, 1);
    CHECK_EQ_INT(ring_count(&r), 0);
    CHECK_EQ_INT(ring_oldest(&r), 1);
    CHECK(!ring_contains(&r, 1));
    for (uint32_t s = 1; s <= 6; s++) {
        CHECK_EQ_INT(ring_append(&r), s);
    }
    CHECK_EQ_INT(ring_count(&r), 4);
    CHECK_EQ_INT(ring_oldest(&r), 3);
    CHECK_EQ_INT(ring_slot(&r, 1), 0);
    CHECK_EQ_INT(ring_slot(&r, 4), 3);
    CHECK_EQ_INT(ring_slot(&r, 5), 0); /* overwrote seq 1 */
    CHECK_EQ_INT(ring_slot(&r, 6), 1);
    CHECK(!ring_contains(&r, 2));
    CHECK(ring_contains(&r, 3));
    CHECK(ring_contains(&r, 6));
    CHECK(!ring_contains(&r, 7));
    CHECK_EQ_INT(ring_first_from(&r, 0), 3);
    CHECK_EQ_INT(ring_first_from(&r, 5), 5);
    CHECK_EQ_INT(ring_first_from(&r, 100), 7);

    ring_clear(&r);
    CHECK_EQ_INT(ring_count(&r), 0);
    CHECK_EQ_INT(ring_oldest(&r), 7);
    CHECK(!ring_contains(&r, 6));
    CHECK_EQ_INT(ring_append(&r), 7); /* numbering continues after a clear */
    CHECK_EQ_INT(ring_slot(&r, 7), 2);
    CHECK_EQ_INT(ring_count(&r), 1);

    /* restore after reboot */
    ring_restore(&r, 4, 7, 9);
    CHECK_EQ_INT(r.next_seq, 10);
    CHECK_EQ_INT(ring_oldest(&r), 7);
    CHECK_EQ_INT(ring_count(&r), 3);
    ring_restore(&r, 4, 7, 5); /* only stale slots from before the clear */
    CHECK_EQ_INT(r.next_seq, 7);
    CHECK_EQ_INT(ring_count(&r), 0);
    ring_restore(&r, 4, 1, 0); /* empty log */
    CHECK_EQ_INT(r.next_seq, 1);

    /* long run: slot mapping is a bijection over the last `capacity` seqs */
    ring_init(&r, 100, 1);
    for (int i = 0; i < 12345; i++) {
        ring_append(&r);
    }
    int seen[100] = {0};
    for (uint32_t s = ring_oldest(&r); s < r.next_seq; s++) {
        seen[ring_slot(&r, s)]++;
    }
    int ok = 1;
    for (int i = 0; i < 100; i++) {
        ok &= seen[i] == 1;
    }
    CHECK(ok);
    CHECK_EQ_INT(ring_count(&r), 100);
}

/* ---- gatt codec ------------------------------------------------------------------------ */

static void test_gatt_live(void)
{
    gatt_live_t l = {.value_nm = 12345000, .cap_nm = CALIPER_CAP_INVALID, .unit = CALIPER_UNIT_INCH,
                     .flags = CALIPER_FLAG_HOLD | CALIPER_FLAG_CHARGING, .active_profile_id = 0xBEEF};
    CHECK_EQ_INT(CALIPER_LIVE_LEN, 12);
    CHECK_EQ_INT(CALIPER_LIVE_OFF_PROFILE, 10);
    uint8_t b[CALIPER_LIVE_LEN];
    memset(b, 0xAA, sizeof(b));
    gatt_live_pack(&l, b);
    const uint8_t exp[12] = {0xA8, 0x5E, 0xBC, 0x00, 0x00, 0x00, 0x00, 0x80, 0x01, 0x21, 0xEF, 0xBE};
    CHECK(memcmp(b, exp, 12) == 0);
    gatt_live_t u;
    memset(&u, 0x55, sizeof(u));
    CHECK_EQ_INT(gatt_live_unpack(b, 12, &u), 0);
    CHECK(u.value_nm == l.value_nm && u.cap_nm == INT32_MIN && u.unit == 1 && u.flags == 0x21);
    CHECK_EQ_INT(u.active_profile_id, 0xBEEF);
    /* a 10-byte LIVE (pre-extension firmware) has no profile id; bytes past 12 are ignored */
    memset(&u, 0x55, sizeof(u));
    CHECK_EQ_INT(gatt_live_unpack(b, 10, &u), 0);
    CHECK(u.value_nm == l.value_nm && u.flags == 0x21);
    CHECK_EQ_INT(u.active_profile_id, CALIPER_PROFILE_ID_NONE);
    uint8_t longer[14];
    memcpy(longer, b, 12);
    longer[12] = 0x12;
    longer[13] = 0x34;
    CHECK_EQ_INT(gatt_live_unpack(longer, sizeof(longer), &u), 0);
    CHECK_EQ_INT(u.active_profile_id, 0xBEEF);
    CHECK_EQ_INT(gatt_live_unpack(b, 9, &u), -1);
    /* no profile: the id is 0 on the wire */
    l.active_profile_id = CALIPER_PROFILE_ID_NONE;
    gatt_live_pack(&l, b);
    CHECK(b[10] == 0 && b[11] == 0);
    CHECK_EQ_INT(CALIPER_FLAG_REZERO, 0x40);
    CHECK_EQ_INT(CALIPER_FLAG_HOLD, 0x01);
    CHECK_EQ_INT(CALIPER_FLAG_TOL_PASS, 0x02);
    CHECK_EQ_INT(CALIPER_FLAG_TOL_FAIL, 0x04);
    CHECK_EQ_INT(CALIPER_FLAG_SENSOR_ERR, 0x08);
    CHECK_EQ_INT(CALIPER_FLAG_CAP_VALID, 0x10);
    CHECK_EQ_INT(CALIPER_FLAG_CHARGING, 0x20);
}

static void test_gatt_uuid(void)
{
    /* 7c0a0003-5e1f-4b8a-9c3d-2f6a1e0c7b11, LSB first */
    const uint8_t u[16] = {CALIPER_UUID128_BYTES(CALIPER_UUID_COMMAND)};
    const uint8_t exp[16] = {0x11, 0x7b, 0x0c, 0x1e, 0x6a, 0x2f, 0x3d, 0x9c,
                             0x8a, 0x4b, 0x1f, 0x5e, 0x03, 0x00, 0x0a, 0x7c};
    CHECK(memcmp(u, exp, 16) == 0);
}

static void test_gatt_cmd(void)
{
    gatt_cmd_t c;
    uint8_t z[] = {0x01};
    CHECK_EQ_INT(gatt_cmd_parse(z, 1, &c), GATT_CMD_OK);
    CHECK_EQ_INT(c.op, CALIPER_OP_ZERO);
    uint8_t zl[] = {0x01, 0x00};
    CHECK_EQ_INT(gatt_cmd_parse(zl, 2, &c), GATT_CMD_ERR_LEN);
    CHECK_EQ_INT(gatt_cmd_parse(z, 0, &c), GATT_CMD_ERR_LEN);
    uint8_t unit[] = {0x04, 0x01};
    CHECK_EQ_INT(gatt_cmd_parse(unit, 2, &c), GATT_CMD_OK);
    CHECK_EQ_INT(c.arg, 1);
    uint8_t badunit[] = {0x04, 0x02};
    CHECK_EQ_INT(gatt_cmd_parse(badunit, 2, &c), GATT_CMD_ERR_VALUE);
    uint8_t lr[] = {0x10, 0x78, 0x56, 0x34, 0x12};
    CHECK_EQ_INT(gatt_cmd_parse(lr, 5, &c), GATT_CMD_OK);
    CHECK_EQ_INT(c.arg, 0x12345678);
    CHECK_EQ_INT(gatt_cmd_parse(lr, 4, &c), GATT_CMD_ERR_LEN);
    uint8_t sp[] = {0x20, 0x34, 0x12};
    CHECK_EQ_INT(gatt_cmd_parse(sp, 3, &c), GATT_CMD_OK);
    CHECK_EQ_INT(c.arg, 0x1234);
    uint8_t st[] = {0x30, 0x00, 0xF1, 0x53, 0x65};
    CHECK_EQ_INT(gatt_cmd_parse(st, 5, &c), GATT_CMD_OK);
    CHECK_EQ_INT(c.arg, 1700000000u);
    uint8_t bad[] = {0x99};
    CHECK_EQ_INT(gatt_cmd_parse(bad, 1, &c), GATT_CMD_ERR_OPCODE);
    uint8_t ops[] = {0x02, 0x03, 0x11};
    for (int i = 0; i < 3; i++) {
        CHECK_EQ_INT(gatt_cmd_parse(&ops[i], 1, &c), GATT_CMD_OK);
    }
    /* build/parse round trip */
    gatt_cmd_t in = {.op = CALIPER_OP_LOG_READ, .arg = 42}, out;
    uint8_t buf[8];
    size_t n = gatt_cmd_build(&in, buf, sizeof(buf));
    CHECK_EQ_INT(n, 5);
    CHECK_EQ_INT(gatt_cmd_parse(buf, n, &out), GATT_CMD_OK);
    CHECK_EQ_INT(out.arg, 42);
}

static void test_gatt_profile(void)
{
    meas_profile_t p = {.id = 0x0102, .nominal_nm = 25000000, .tol_minus_nm = 10000, .tol_plus_nm = -1};
    strcpy(p.name, "Bearing 6201 ID!"); /* exactly 16 chars: no NUL on the wire */
    uint8_t b[CALIPER_PROFILE_LEN];
    gatt_profile_pack(&p, b);
    CHECK(b[0] == 0x02 && b[1] == 0x01);
    CHECK(b[2] == 0x40 && b[3] == 0x78 && b[4] == 0x7D && b[5] == 0x01); /* 25,000,000 */
    CHECK(b[10] == 0xFF && b[13] == 0xFF);
    CHECK(memcmp(b + 14, "Bearing 6201 ID!", 16) == 0);
    meas_profile_t u;
    gatt_profile_unpack(b, &u);
    CHECK_EQ_INT(u.id, p.id);
    CHECK_EQ_INT(u.nominal_nm, p.nominal_nm);
    CHECK_EQ_INT(u.tol_minus_nm, p.tol_minus_nm);
    CHECK_EQ_INT(u.tol_plus_nm, p.tol_plus_nm);
    CHECK_EQ_STR(u.name, "Bearing 6201 ID!");
    meas_profile_t s = {.id = 5};
    strcpy(s.name, "M6");
    gatt_profile_pack(&s, b);
    CHECK(b[14] == 'M' && b[15] == '6' && b[16] == 0 && b[29] == 0); /* NUL padded */
    CHECK(!gatt_profile_is_delete(&s));
    meas_profile_t del = {.id = 5};
    CHECK(gatt_profile_is_delete(&del));

    CHECK_EQ_INT(gatt_log_records_per_notify(23), 1);
    CHECK_EQ_INT(gatt_log_records_per_notify(185), 11);
    CHECK_EQ_INT(gatt_log_records_per_notify(247), 15);
    CHECK_EQ_INT(gatt_log_records_per_notify(0), 1);
}

/* ---- settings -------------------------------------------------------------------------- */

static void test_settings_json(void)
{
    settings_t s;
    settings_defaults(&s);
    char js[SETTINGS_JSON_MAX + 1];
    int n = settings_to_json(&s, js, sizeof(js));
    CHECK(n > 0);
    CHECK_EQ_STR(js, "{\"name\":\"PrettyCool Caliper\",\"wifi_ssid\":\"\",\"mqtt_url\":\"\",\"http_post_url\":\"\","
                     "\"auto_off_s\":300,\"hid_suffix\":\"\\n\",\"decimals\":2}");

    const char *w = "{ \"wifi_ssid\": \"shop\", \"wifi_pass\": \"hunter2hunter2\", \"decimals\": 3,"
                    " \"hid_suffix\": \"\\t\", \"future_key\": true, \"other\": null, \"x\": 1.5 }";
    CHECK_EQ_INT(settings_from_json(&s, w, strlen(w)), SETTINGS_OK);
    CHECK_EQ_STR(s.wifi_ssid, "shop");
    CHECK_EQ_STR(s.wifi_pass, "hunter2hunter2");
    CHECK_EQ_INT(s.decimals, 3);
    CHECK_EQ_STR(s.hid_suffix, "\t");
    n = settings_to_json(&s, js, sizeof(js));
    CHECK(n > 0 && strstr(js, "wifi_pass") == NULL && strstr(js, "hunter2") == NULL); /* write-only */
    CHECK(strstr(js, "\"hid_suffix\":\"\\t\"") != NULL);

    settings_t before = s;
    const char *bad[] = {
        "{\"decimals\":4}",
        "{\"decimals\":\"2\"}",
        "{\"decimals\":2.5}",
        "{\"auto_off_s\":5}",
        "{\"hid_suffix\":\"x\"}",
        "{\"mqtt_url\":\"http://nope\"}",
        "{\"http_post_url\":\"ftp://nope\"}",
        "{\"wifi_pass\":\"short\"}",
        "{\"name\":\"this name is far too long for it\"}",
        "{\"name\":true}",
        "{\"name\":\"ok\", \"decimals\":9}", /* all-or-nothing: name must not change either */
        "{\"name\":\"ok\"",
        "[1,2]",
        "{\"a\":{\"b\":1}}",
        "{\"name\":\"bad\\q\"}",
        "{\"name\":\"ok\"} trailing",
    };
    for (size_t i = 0; i < sizeof(bad) / sizeof(bad[0]); i++) {
        int rc = settings_from_json(&s, bad[i], strlen(bad[i]));
        if (rc == SETTINGS_OK) {
            printf("    accepted bad input: %s\n", bad[i]);
        }
        CHECK(rc != SETTINGS_OK);
    }
    CHECK(memcmp(&s, &before, sizeof(s)) == 0);

    const char *ok2 = "{\"auto_off_s\":0,\"hid_suffix\":\"\",\"name\":\"Caf\\u00e9 \\\"Q\\\"\"}";
    CHECK_EQ_INT(settings_from_json(&s, ok2, strlen(ok2) + 1), SETTINGS_OK); /* trailing NUL ok */
    CHECK_EQ_STR(s.name, "Caf\xc3\xa9 \"Q\"");
    CHECK_EQ_INT(s.auto_off_s, 0);
    CHECK_EQ_STR(s.hid_suffix, "");
    n = settings_to_json(&s, js, sizeof(js));
    CHECK(strstr(js, "\"name\":\"Caf\xc3\xa9 \\\"Q\\\"\"") != NULL);
    /* the serialised form parses back to the same settings */
    settings_t again;
    settings_defaults(&again);
    strcpy(again.wifi_pass, s.wifi_pass);
    CHECK_EQ_INT(settings_from_json(&again, js, (size_t)n), SETTINGS_OK);
    CHECK(memcmp(&again, &s, sizeof(s)) == 0);

    /* the 240-byte limit: long values together are rejected */
    settings_defaults(&s);
    char big[400];
    snprintf(big, sizeof(big),
             "{\"name\":\"%s\",\"wifi_ssid\":\"%s\",\"mqtt_url\":\"mqtt://%s\",\"http_post_url\":\"http://%s\"}",
             "AAAAAAAAAAAAAAAAAAAA", "SSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSS",
             "mmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmm",
             "hhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhh");
    CHECK_EQ_INT(settings_from_json(&s, big, strlen(big)), SETTINGS_ERR_TOOBIG);
    CHECK_EQ_STR(s.name, "PrettyCool Caliper");

    /* key/value interface (web form, CLI) */
    CHECK_EQ_INT(settings_set_kv(&s, "decimals", "1"), SETTINGS_OK);
    CHECK_EQ_INT(s.decimals, 1);
    CHECK(settings_set_kv(&s, "decimals", "1x") != SETTINGS_OK);
    CHECK_EQ_INT(settings_set_kv(&s, "hid_suffix", "tab"), SETTINGS_OK);
    CHECK_EQ_STR(s.hid_suffix, "\t");
    CHECK_EQ_INT(settings_set_kv(&s, "hid_suffix", "none"), SETTINGS_OK);
    CHECK_EQ_STR(s.hid_suffix, "");
    CHECK_EQ_INT(settings_set_kv(&s, "mqtt_url", "mqtt://10.0.0.2"), SETTINGS_OK);

    /* wifi_pass: 8..63 printable ASCII, or exactly 64 hex digits (the raw PSK); "" clears */
    settings_defaults(&s);
    char psk[80];
    memset(psk, 'a', 63);
    psk[63] = 0;
    CHECK_EQ_INT(settings_set_kv(&s, "wifi_pass", psk), SETTINGS_OK); /* 63-char passphrase */
    memset(psk, 'F', 64);
    psk[64] = 0;
    psk[10] = '0';
    CHECK_EQ_INT(settings_set_kv(&s, "wifi_pass", psk), SETTINGS_OK); /* 64 hex = PSK */
    CHECK_EQ_INT(strlen(s.wifi_pass), 64);
    psk[10] = 'g';
    CHECK_EQ_INT(settings_set_kv(&s, "wifi_pass", psk), SETTINGS_ERR_VALUE); /* 64, not hex */
    CHECK_EQ_INT(settings_set_kv(&s, "wifi_pass", "tab\there!"), SETTINGS_ERR_VALUE); /* control char */
    CHECK_EQ_INT(settings_set_kv(&s, "wifi_pass", "caf\xc3\xa9" "caf\xc3\xa9"), SETTINGS_ERR_VALUE); /* not ASCII */
    CHECK_EQ_INT(settings_set_kv(&s, "wifi_pass", "with spaces ok"), SETTINGS_OK);
    CHECK_EQ_INT(settings_set_kv(&s, "wifi_pass", ""), SETTINGS_OK);
    CHECK_EQ_STR(s.wifi_pass, "");
    /* a 32-byte SSID is legal (the station code copies it without a terminator) */
    CHECK_EQ_INT(settings_set_kv(&s, "wifi_ssid", "SSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSS"), SETTINGS_OK);
    CHECK_EQ_INT(strlen(s.wifi_ssid), 32);

    char dec[32];
    settings_url_decode(dec, sizeof(dec), "a+b%2Fc%3d%zz%", 15);
    CHECK_EQ_STR(dec, "a b/c=%zz%");
}

/* ---- csv ------------------------------------------------------------------------------- */

static void test_csv(void)
{
    csv_civil_t c;
    csv_civil_from_unix(0, &c);
    CHECK(c.year == 1970 && c.month == 1 && c.day == 1 && c.hour == 0);
    csv_civil_from_unix(951782400u, &c); /* 2000-02-29 */
    CHECK(c.year == 2000 && c.month == 2 && c.day == 29);
    csv_civil_from_unix(1700000000u, &c);
    CHECK(c.year == 2023 && c.month == 11 && c.day == 14 && c.hour == 22 && c.min == 13 && c.sec == 20);
    csv_civil_from_unix(0xFFFFFFFFu, &c);
    CHECK(c.year == 2106 && c.month == 2 && c.day == 7 && c.hour == 6 && c.min == 28 && c.sec == 15);

    char line[96];
    logrec_t r = {.seq = 12, .unix_s = 1700000000u, .value_nm = 12345000, .unit = 0,
                  .flags = CALIPER_FLAG_HOLD | CALIPER_FLAG_TOL_PASS, .profile_id = 3};
    CHECK(csv_line(&r, 2, true, line, sizeof(line)) > 0);
    CHECK_EQ_STR(line, "12,1700000000,2023-11-14T22:13:20Z,12.35,mm,HP,3\r\n");
    r.unit = 1;
    r.unix_s = 0;
    r.flags = CALIPER_FLAG_TOL_FAIL | CALIPER_FLAG_SENSOR_ERR;
    r.value_nm = -25400000;
    CHECK(csv_line(&r, 2, false, line, sizeof(line)) > 0);
    CHECK_EQ_STR(line, "12,,-1.0000,in,FE,3\r\n");
    CHECK(csv_header(true, line, sizeof(line)) > 0);
    CHECK_EQ_STR(line, "seq,unix_s,utc,value,unit,flags,profile\r\n");
    char tiny[8];
    CHECK_EQ_INT(csv_line(&r, 2, true, tiny, sizeof(tiny)), -1);

    /* REZERO is exported ('Z'), after the others */
    r.flags = CALIPER_FLAG_HOLD | CALIPER_FLAG_TOL_PASS | CALIPER_FLAG_TOL_FAIL | CALIPER_FLAG_SENSOR_ERR |
              CALIPER_FLAG_REZERO;
    r.unit = 0;
    r.value_nm = 1000;
    CHECK(csv_line(&r, 3, false, line, sizeof(line)) > 0);
    CHECK_EQ_STR(line, "12,,0.001,mm,HPFEZ,3\r\n");

    /* the widest possible line fits CSV_LINE_MAX */
    logrec_t w = {.seq = 0xFFFFFFFEu, .unix_s = 0xFFFFFFFFu, .value_nm = INT32_MIN, .unit = 1, .flags = 0xFF,
                  .profile_id = 0xFFFF};
    char big[CSV_LINE_MAX];
    int lw = csv_line(&w, 3, true, big, sizeof(big));
    CHECK(lw > 0 && lw < CSV_LINE_MAX);
    w.unit = 0;
    lw = csv_line(&w, 3, true, big, sizeof(big));
    CHECK(lw > 0 && lw < CSV_LINE_MAX);

    /* csv_pack: whole lines only, never skips a record, and the rest goes in the next call. The old
     * export loop dropped the records of a batch that did not fit its 1 KiB buffer. */
    logrec_t recs[16];
    for (int i = 0; i < 16; i++) {
        recs[i] = w;
        recs[i].seq = 4000000000u + (uint32_t)i;
    }
    char out[1024];
    size_t used = 0, done = 0, lines = 0, total_bytes = 0;
    int calls = 0;
    while (done < 16) {
        size_t k = csv_pack(recs + done, 16 - done, 3, true, out, sizeof(out), &used);
        CHECK(k > 0);
        CHECK_EQ_INT(strlen(out), used);
        for (size_t b = 0; b < used; b++) {
            lines += out[b] == '\n';
        }
        total_bytes += used;
        done += k;
        calls++;
        if (k == 0) {
            break;
        }
    }
    CHECK_EQ_INT(lines, 16);
    CHECK_EQ_INT(done, 16);
    CHECK(calls >= 2); /* 16 widest lines do not fit 1 KiB */
    CHECK_EQ_INT(total_bytes, 16 * (size_t)lw);
    /* a buffer with no room for even one line formats nothing (and says so) */
    CHECK_EQ_INT(csv_pack(recs, 16, 3, true, tiny, sizeof(tiny), &used), 0);
    CHECK_EQ_INT(used, 0);
}

/* ---- buttons --------------------------------------------------------------------------- */

static btn_event_t run_btn(btn_sm_t *b, uint8_t mask, uint32_t *t, uint32_t dur, btn_event_t *last)
{
    btn_event_t first = {BTN_EV_NONE, 0};
    for (uint32_t e = 0; e < dur; e += 5) {
        btn_event_t ev = btn_update(b, mask, *t);
        if (ev.type != BTN_EV_NONE) {
            if (first.type == BTN_EV_NONE) {
                first = ev;
            }
            if (last) {
                *last = ev;
            }
        }
        *t += 5;
    }
    return first;
}

static void test_buttons(void)
{
    btn_sm_t b;
    btn_init(&b);
    uint32_t t = 1000;
    btn_event_t ev;
    ev = run_btn(&b, 0, &t, 100, NULL);
    CHECK_EQ_INT(ev.type, BTN_EV_NONE);
    ev = run_btn(&b, BTN_ZERO, &t, 150, NULL);
    CHECK_EQ_INT(ev.type, BTN_EV_NONE); /* nothing while held briefly */
    ev = run_btn(&b, 0, &t, 100, NULL);
    CHECK_EQ_INT(ev.type, BTN_EV_SHORT);
    CHECK_EQ_INT(ev.mask, BTN_ZERO);

    /* contact bounce: one short press only */
    int shorts = 0;
    for (int i = 0; i < 4; i++) {
        btn_event_t e1 = run_btn(&b, BTN_MODE, &t, 5, NULL);
        btn_event_t e2 = run_btn(&b, 0, &t, 5, NULL);
        shorts += (e1.type == BTN_EV_SHORT) + (e2.type == BTN_EV_SHORT);
    }
    ev = run_btn(&b, BTN_MODE, &t, 200, NULL);
    shorts += ev.type == BTN_EV_SHORT;
    ev = run_btn(&b, 0, &t, 100, NULL);
    shorts += ev.type == BTN_EV_SHORT;
    CHECK_EQ_INT(shorts, 1);

    /* long press fires once while held, and no short on release */
    uint32_t t0 = t;
    btn_event_t lp = {BTN_EV_NONE, 0};
    for (uint32_t e = 0; e < 1500; e += 5) {
        btn_event_t x = btn_update(&b, BTN_HOLD, t);
        if (x.type != BTN_EV_NONE && lp.type == BTN_EV_NONE) {
            lp = x;
            CHECK(t - t0 >= BTN_LONG_MS && t - t0 <= BTN_LONG_MS + BTN_DEBOUNCE_MS + 10);
        } else {
            CHECK_EQ_INT(x.type, BTN_EV_NONE);
        }
        t += 5;
    }
    CHECK_EQ_INT(lp.type, BTN_EV_LONG);
    CHECK_EQ_INT(lp.mask, BTN_HOLD);
    ev = run_btn(&b, 0, &t, 100, NULL);
    CHECK_EQ_INT(ev.type, BTN_EV_NONE);

    /* combo ZERO+MODE */
    ev = run_btn(&b, BTN_ZERO | BTN_MODE, &t, 1700, NULL);
    CHECK_EQ_INT(ev.type, BTN_EV_COMBO);
    CHECK_EQ_INT(ev.mask, BTN_ZERO | BTN_MODE);
    ev = run_btn(&b, BTN_ZERO, &t, 50, NULL); /* releasing one at a time: no extra event */
    CHECK_EQ_INT(ev.type, BTN_EV_NONE);
    ev = run_btn(&b, 0, &t, 100, NULL);
    CHECK_EQ_INT(ev.type, BTN_EV_NONE);

    /* a quick two-button tap is ignored (neither short nor combo) */
    ev = run_btn(&b, BTN_ZERO | BTN_HOLD, &t, 300, NULL);
    CHECK_EQ_INT(ev.type, BTN_EV_NONE);
    ev = run_btn(&b, 0, &t, 100, NULL);
    CHECK_EQ_INT(ev.type, BTN_EV_NONE);
}

/* ---- hid ------------------------------------------------------------------------------- */

static void test_hid(void)
{
    uint8_t mod, use;
    CHECK(hid_ascii_to_key('1', &mod, &use) && use == 0x1E && mod == 0);
    CHECK(hid_ascii_to_key('9', &mod, &use) && use == 0x26);
    CHECK(hid_ascii_to_key('0', &mod, &use) && use == 0x27);
    CHECK(hid_ascii_to_key('.', &mod, &use) && use == 0x37);
    CHECK(hid_ascii_to_key('-', &mod, &use) && use == 0x2D);
    CHECK(hid_ascii_to_key('\n', &mod, &use) && use == 0x28);
    CHECK(hid_ascii_to_key('\t', &mod, &use) && use == 0x2B);
    CHECK(hid_ascii_to_key('M', &mod, &use) && use == 0x10 && mod == HID_MOD_LSHIFT);
    CHECK(!hid_ascii_to_key('\x01', &mod, &use));
    uint8_t rep[16][8];
    size_t n = hid_build_reports("-1.5\n", rep, 16);
    CHECK_EQ_INT(n, 10);
    CHECK(rep[0][2] == 0x2D && rep[1][2] == 0 && rep[2][2] == 0x1E && rep[4][2] == 0x37 && rep[8][2] == 0x28);
    n = hid_build_reports("12345678", rep, 5); /* truncated to whole pairs */
    CHECK_EQ_INT(n, 4);
}

/* ---- as5311 ---------------------------------------------------------------------------- */

static void test_as5311_frame(void)
{
    as5311_frame_t f = {.pos = 0xABC, .ocf = 1, .cof = 0, .lin = 0, .mag_inc = 0, .mag_dec = 1};
    uint32_t raw = as5311_encode(&f);
    as5311_frame_t d;
    as5311_decode(raw, &d);
    CHECK_EQ_INT(d.pos, 0xABC);
    CHECK(d.ocf && !d.cof && !d.lin && !d.mag_inc && d.mag_dec && d.parity_ok);
    CHECK(as5311_frame_valid(&d));
    CHECK_EQ_INT(as5311_field(&d), AS5311_FIELD_OK);
    /* every single-bit error is caught by the parity */
    int caught = 0;
    for (int bit = 0; bit < 18; bit++) {
        as5311_decode(raw ^ (1u << bit), &d);
        caught += !d.parity_ok;
    }
    CHECK_EQ_INT(caught, 18);
    /* an all-ones frame (DO stuck high, or the sensor unpowered with a pull-up) is rejected */
    as5311_decode(0x3FFFF, &d);
    CHECK(!as5311_frame_valid(&d));
    as5311_decode(0, &d); /* all zeros: parity even, but OCF = 0 */
    CHECK(!as5311_frame_valid(&d));
    f.mag_inc = 1;
    f.mag_dec = 1;
    f.lin = 1;
    as5311_decode(as5311_encode(&f), &d);
    CHECK_EQ_INT(as5311_field(&d), AS5311_FIELD_BAD);
    f.lin = 0;
    as5311_decode(as5311_encode(&f), &d);
    CHECK_EQ_INT(as5311_field(&d), AS5311_FIELD_MARGINAL);
    /* bit order: D11 is the first bit clocked out (bit 17) */
    as5311_decode(1u << 17, &d);
    CHECK_EQ_INT(d.pos, 0x800);
}

static void test_as5311_tracking(void)
{
    CHECK_EQ_INT(as5311_wrap_diff(10, 4090), 16);
    CHECK_EQ_INT(as5311_wrap_diff(4090, 10), -16);
    CHECK_EQ_INT(as5311_wrap_diff(2048, 0), -2048);
    /* phase is in SSI LSB: 1 count = 4 LSB, 1024 counts per pole pair */
    CHECK_EQ_INT(as5311_count_phase(-1, 1), 4092);
    CHECK_EQ_INT(as5311_count_phase(-1, -1), 4);
    CHECK_EQ_INT(as5311_count_phase(1024, 1), 0);
    CHECK_EQ_INT(as5311_count_phase(1025, 1), 4);
    CHECK_EQ_INT(as5311_lsb_to_counts(0), 0);
    CHECK_EQ_INT(as5311_lsb_to_counts(1), 0);
    CHECK_EQ_INT(as5311_lsb_to_counts(2), 1);
    CHECK_EQ_INT(as5311_lsb_to_counts(-2), -1);
    CHECK_EQ_INT(as5311_lsb_to_counts(-5), -1);
    CHECK_EQ_INT(as5311_lsb_to_counts(-6), -2);

    for (int dir = -1; dir <= 1; dir += 2) {
        as5311_slip_t s;
        as5311_slip_init(&s, dir);
        CHECK_EQ_INT(as5311_slip_residual(&s, 100, 200), 0); /* not locked */
        as5311_slip_lock(&s, 1000, 1234);
        int ok = 1;
        for (int64_t c = -20000; c <= 20000; c += 37) {
            uint16_t ssi = (uint16_t)(((int32_t)as5311_count_phase(c, dir) + s.offset) & 4095);
            ok &= as5311_slip_residual(&s, c, ssi) == 0;
            ok &= as5311_slip_residual(&s, c, (uint16_t)((ssi + 6) & 4095)) == 6;
            ok &= as5311_slip_residual(&s, c, (uint16_t)((ssi - 9) & 4095)) == -9;
            /* the counter missed k edges: the true count is c + k; the correction recovers k */
            for (int k = -7; k <= 7; k += 7) {
                uint16_t ssi_true = (uint16_t)(((int32_t)as5311_count_phase(c + k, dir) + s.offset) & 4095);
                int32_t r = as5311_slip_residual(&s, c, ssi_true);
                ok &= as5311_slip_correction(&s, r) == k;
            }
        }
        CHECK(ok);
    }
    /* 4000 -> 100 LSB is +196 LSB = +49 counts */
    CHECK_EQ_INT(as5311_recover_count(10000, 4000, 100, 1), 10049);
    CHECK_EQ_INT(as5311_recover_count(10000, 100, 4000, 1), 9951);
    CHECK_EQ_INT(as5311_recover_count(10000, 4000, 100, -1), 9951);
    CHECK_EQ_INT(as5311_recover_count(-5, 7, 7, 1), -5);
    CHECK_EQ_INT(as5311_recover_count(0, 0, 2047, 1), 512); /* just under 1 mm */
}

/* ---- AS5311 fine position (SSI-refined count) ------------------------------------------ */

/* A model of the sensor: the true position x in SSI LSB (488.28125 nm). The quadrature count steps
 * every 4 LSB at a hardware phase ph (0..3) and lags by `hyst` counts after a reversal; the SSI is
 * (dir * x + c0) mod 4096 plus jitter. */
typedef struct {
    int dir;
    int32_t c0;
    int ph;
    int hyst;
    int64_t count;
} mag_model_t;

static int64_t floor_div4(int64_t v)
{
    return v >= 0 ? v / 4 : -((-v + 3) / 4);
}

static void model_move(mag_model_t *m, int64_t x)
{
    /* backlash: the count stays within [ideal - hyst, ideal], so it lags by up to `hyst` counts
     * depending on the direction of travel */
    int64_t ideal = floor_div4(x - m->ph);
    if (m->count < ideal - m->hyst) {
        m->count = ideal - m->hyst;
    }
    if (m->count > ideal) {
        m->count = ideal;
    }
}

static uint16_t model_ssi(const mag_model_t *m, int64_t x, int jitter)
{
    int64_t v = (int64_t)m->dir * x + m->c0 + jitter;
    return (uint16_t)(((v % 4096) + 4096) % 4096);
}

static void test_as5311_fine(void)
{
    CHECK_EQ_INT(meas_lsb_to_nm(1), 488);     /* 488.28125 */
    CHECK_EQ_INT(meas_lsb_to_nm(2), 977);     /* 976.5625 */
    CHECK_EQ_INT(meas_lsb_to_nm(4), 1953);    /* one count, = meas_counts_to_nm(1) */
    CHECK_EQ_INT(meas_lsb_to_nm(-1), -488);
    CHECK_EQ_INT(meas_lsb_to_nm(4096), 2000000);         /* one pole pair */
    CHECK_EQ_INT(meas_lsb_to_nm(307200), 150000000);     /* 150 mm */
    CHECK_EQ_INT(meas_lsb_to_nm(-307200), -150000000);
    CHECK_EQ_INT(meas_lsb_to_nm(4 * 76801), meas_counts_to_nm(76801));

    /* not locked, or no usable frame: the count alone */
    as5311_slip_t s;
    as5311_slip_init(&s, 1);
    as5311_fine_t f = as5311_fine_combine(&s, 100, true, 1234);
    CHECK(f.status == AS5311_FINE_COARSE && f.lsb == 400 && f.residual == 0);
    as5311_slip_lock(&s, 100, 1234);
    f = as5311_fine_combine(&s, 100, false, 1236);
    CHECK(f.status == AS5311_FINE_COARSE && f.lsb == 400);
    f = as5311_fine_combine(&s, 100, true, 1236);
    CHECK(f.status == AS5311_FINE_OK && f.lsb == 402 && f.residual == 2);
    f = as5311_fine_combine(&s, 100, true, 1234 + AS5311_FINE_TOL_LSB);
    CHECK(f.status == AS5311_FINE_OK && f.lsb == 400 + AS5311_FINE_TOL_LSB);
    f = as5311_fine_combine(&s, 100, true, 1234 + AS5311_FINE_TOL_LSB + 1); /* > 3 edges */
    CHECK(f.status == AS5311_FINE_MISMATCH && f.lsb == 400 && f.residual == AS5311_FINE_TOL_LSB + 1);
    f = as5311_fine_combine(&s, 100, true, (uint16_t)(1234 - AS5311_FINE_TOL_LSB - 1));
    CHECK(f.status == AS5311_FINE_MISMATCH && f.lsb == 400);

    /* pole-boundary wrap: SSI 4094 -> 1 while the count crosses into the next pole */
    as5311_slip_init(&s, 1);
    as5311_slip_lock(&s, 1023, 4092); /* count phase 4092, offset 0 */
    f = as5311_fine_combine(&s, 1023, true, 4094);
    CHECK(f.status == AS5311_FINE_OK && f.lsb == 4094);
    f = as5311_fine_combine(&s, 1023, true, 1); /* count not yet stepped: residual +5 across the wrap */
    CHECK(f.status == AS5311_FINE_OK && f.lsb == 4097 && f.residual == 5);
    f = as5311_fine_combine(&s, 1024, true, 1);
    CHECK(f.status == AS5311_FINE_OK && f.lsb == 4097 && f.residual == 1);
    f = as5311_fine_combine(&s, 1024, true, 4095); /* back again, count lagging */
    CHECK(f.status == AS5311_FINE_OK && f.lsb == 4095 && f.residual == -1);
    /* same with the SSI running against the count (SSI_SIGN = -1) */
    as5311_slip_init(&s, -1);
    as5311_slip_lock(&s, 0, 2);
    f = as5311_fine_combine(&s, 0, true, 4095); /* SSI 2 -> 4095 is +3 LSB for dir -1 */
    CHECK(f.status == AS5311_FINE_OK && f.lsb == 3);
    f = as5311_fine_combine(&s, -1, true, 6); /* SSI up 4 = one count down */
    CHECK(f.status == AS5311_FINE_OK && f.lsb == -4);

    /* full sweep over 3 poles and back, both SSI directions, every hardware phase, 2 counts of
     * hysteresis and +-1 LSB of SSI jitter: the fine position tracks x - x0 to the jitter, across
     * every pole boundary, and is never flagged */
    for (int dir = -1; dir <= 1; dir += 2) {
        for (int ph = 0; ph < 4; ph++) {
            mag_model_t m = {.dir = dir, .c0 = 3000 + 37 * ph, .ph = ph, .hyst = 2};
            int64_t x0 = 4096 * 2 + 4090 - 3 * ph; /* start just below a pole boundary */
            m.count = floor_div4(x0 - ph);
            as5311_slip_init(&s, dir);
            as5311_slip_lock(&s, m.count, model_ssi(&m, x0, 0));
            int64_t base = as5311_fine_combine(&s, m.count, true, model_ssi(&m, x0, 0)).lsb;
            int ok = 1, flagged = 0;
            int64_t max_err = 0;
            int64_t x = x0;
            for (int step = 0; step < 2 * 3 * 4096; step++) {
                x += step < 3 * 4096 ? 1 : -1;
                model_move(&m, x);
                int jit = (step % 3) - 1;
                as5311_fine_t g = as5311_fine_combine(&s, m.count, true, model_ssi(&m, x, jit));
                flagged += g.status != AS5311_FINE_OK;
                int64_t err = (g.lsb - base) - (x - x0);
                if (err < 0) err = -err;
                if (err > max_err) max_err = err;
                ok &= err <= 2; /* lock-time jitter (0) + this frame's jitter (1), +1 for rounding */
            }
            CHECK(ok);
            CHECK_EQ_INT(flagged, 0);
            CHECK(max_err <= 1);
        }
    }

    /* recovery after a deep sleep with the stored offset: the fine position carries on */
    for (int dir = -1; dir <= 1; dir += 2) {
        mag_model_t m = {.dir = dir, .c0 = 777, .ph = 1, .hyst = 0};
        int64_t x = 50000;
        m.count = floor_div4(x - m.ph);
        as5311_slip_init(&s, dir);
        as5311_slip_lock(&s, m.count, model_ssi(&m, x, 0));
        int64_t before = as5311_fine_combine(&s, m.count, true, model_ssi(&m, x, 0)).lsb;
        uint16_t ssi_stored = model_ssi(&m, x, 0);
        int ok = 1;
        for (int d = -2000; d <= 2000; d += 7) { /* < 1 mm while asleep, across pole boundaries */
            uint16_t ssi_now = model_ssi(&m, x + d, 0);
            int64_t cnt = as5311_recover_count(m.count, ssi_stored, ssi_now, dir);
            as5311_slip_t chk = {.locked = true, .offset = s.offset, .dir = dir};
            as5311_fine_t g = as5311_fine_combine(&chk, cnt, true, ssi_now);
            ok &= g.status == AS5311_FINE_OK && g.lsb - before == d;
        }
        CHECK(ok);
    }
}

static void test_as5311_mismatch(void)
{
    for (int dir = -1; dir <= 1; dir += 2) {
        as5311_slip_t s;
        as5311_slip_init(&s, dir);
        as5311_slip_lock(&s, 1000, 2000);
        as5311_mismatch_t mm;
        as5311_mismatch_init(&mm);
        /* the counter missed 5 edges: true count 1005 */
        uint16_t ssi_true = (uint16_t)((2000 + 4 * dir * 5 + 4096) % 4096);
        as5311_fine_t f = as5311_fine_combine(&s, 1000, true, ssi_true);
        CHECK(f.status == AS5311_FINE_MISMATCH && f.lsb == 4000); /* count alone */
        CHECK_EQ_INT(as5311_mismatch_update(&mm, &s, &f), 0);
        CHECK_EQ_INT(as5311_mismatch_update(&mm, &s, &f), 0);
        CHECK_EQ_INT(as5311_mismatch_update(&mm, &s, &f), 5); /* confirmed on the 3rd frame */
        f = as5311_fine_combine(&s, 1005, true, ssi_true);
        CHECK(f.status == AS5311_FINE_OK && f.lsb == 4020);
        CHECK_EQ_INT(as5311_mismatch_update(&mm, &s, &f), 0);

        /* one bad (but parity-valid) frame between good ones never shifts the count */
        as5311_mismatch_init(&mm);
        as5311_fine_t bad = as5311_fine_combine(&s, 1005, true, (uint16_t)((ssi_true + 400) % 4096));
        as5311_fine_t good = as5311_fine_combine(&s, 1005, true, ssi_true);
        CHECK(bad.status == AS5311_FINE_MISMATCH);
        int total = 0;
        for (int i = 0; i < 10; i++) {
            total += as5311_mismatch_update(&mm, &s, &bad);
            total += as5311_mismatch_update(&mm, &s, &bad);
            total += as5311_mismatch_update(&mm, &s, &good);
        }
        CHECK_EQ_INT(total, 0);
        /* COARSE frames (moving, no SSI) neither confirm nor reset */
        as5311_fine_t coarse = {.lsb = 0, .residual = 0, .status = AS5311_FINE_COARSE};
        as5311_mismatch_init(&mm);
        CHECK_EQ_INT(as5311_mismatch_update(&mm, &s, &bad), 0);
        CHECK_EQ_INT(as5311_mismatch_update(&mm, &s, &coarse), 0);
        CHECK_EQ_INT(as5311_mismatch_update(&mm, &s, &bad), 0);
        CHECK(as5311_mismatch_update(&mm, &s, &bad) != 0);
        /* different corrections each time (noise, not a slip) never confirm */
        as5311_mismatch_init(&mm);
        total = 0;
        for (int i = 0; i < 12; i++) {
            int32_t off = (i % 2) ? 60 : -60;
            as5311_fine_t n = as5311_fine_combine(&s, 1005, true, (uint16_t)((ssi_true + off + 4096) % 4096));
            total += as5311_mismatch_update(&mm, &s, &n) != 0;
        }
        CHECK_EQ_INT(total, 0);
    }
}

static void test_pcnt_jump_filter(void)
{
    as5311_jump_t j;
    as5311_jump_init(&j);
    int64_t out = -1;
    CHECK(as5311_jump_filter(&j, 29990, 15000, &out) && out == 29990); /* first read is taken */
    CHECK(as5311_jump_filter(&j, 29999, 15000, &out) && out == 29999);
    /* the wrap race: the hardware counter reset to 0 but the ISR has not added 30000 yet */
    CHECK(!as5311_jump_filter(&j, 1, 15000, &out) && out == 29999);
    CHECK(as5311_jump_filter(&j, 30001, 15000, &out) && out == 30001); /* the re-read */
    CHECK(as5311_jump_filter(&j, 30001 + 15000, 15000, &out)); /* exactly max_step is plausible */
    /* the other way, from below -30000 */
    as5311_jump_init(&j);
    CHECK(as5311_jump_filter(&j, -29995, 15000, &out));
    CHECK(!as5311_jump_filter(&j, -2, 15000, &out) && out == -29995);
    CHECK(as5311_jump_filter(&j, -30002, 15000, &out) && out == -30002);
    /* a jump that persists is real (accepted on the AS5311_JUMP_ACCEPT-th read) */
    as5311_jump_init(&j);
    CHECK(as5311_jump_filter(&j, 0, 15000, &out));
    CHECK(!as5311_jump_filter(&j, 40000, 15000, &out) && out == 0);
    CHECK(!as5311_jump_filter(&j, 40000, 15000, &out) && out == 0);
    CHECK(as5311_jump_filter(&j, 40000, 15000, &out) && out == 40000);
    CHECK(as5311_jump_filter(&j, 40010, 15000, &out) && out == 40010);
    /* a plausible read resets the reject streak */
    CHECK(!as5311_jump_filter(&j, 0, 15000, &out));
    CHECK(as5311_jump_filter(&j, 40011, 15000, &out));
    CHECK(!as5311_jump_filter(&j, 0, 15000, &out));
    CHECK(!as5311_jump_filter(&j, 0, 15000, &out) && out == 40011);

    /* re-reads inside one sample go through as5311_jump_plausible(), which must not count as
     * samples: a race that is still there after any number of re-reads is held this sample */
    as5311_jump_init(&j);
    CHECK(as5311_jump_plausible(&j, 123456, 15000)); /* nothing accepted yet */
    CHECK(as5311_jump_filter(&j, 29999, 15000, &out));
    for (int i = 0; i < 10; i++) {
        CHECK(!as5311_jump_plausible(&j, 1, 15000));
    }
    CHECK(as5311_jump_plausible(&j, 29999 + 15000, 15000));
    CHECK(as5311_jump_plausible(&j, 29999 - 15000, 15000));
    CHECK(!as5311_jump_filter(&j, 1, 15000, &out) && out == 29999); /* sample 1 of the stuck race */
    CHECK(!as5311_jump_filter(&j, 1, 15000, &out) && out == 29999); /* sample 2 */
    CHECK(as5311_jump_filter(&j, 1, 15000, &out) && out == 1);      /* sample 3: believed */
}

/* ---- capacitive demod ------------------------------------------------------------------ */

#define CAP_SPS   2 /* ADC samples per drive step */
#define CAP_STEPS 8 /* steps per cycle */
#define CAP_K     16 /* cycles per direction */
#define CAP_SPC   (CAP_SPS * CAP_STEPS)

/* Synthesises a capture: `delay` samples before the drive starts, K cycles forward, K reverse.
 * Coupling model: phase n couples (1 + cos(theta - 2 pi n / 8)) into the receiver. */
static size_t synth(uint16_t *buf, size_t max, double theta, int delay, double amp, unsigned seed)
{
    size_t n = (size_t)delay + 2u * CAP_K * CAP_SPC + 16u;
    if (n > max) {
        n = max;
    }
    srand(seed);
    for (size_t i = 0; i < n; i++) {
        int32_t step = 0;
        if ((int)i >= delay) {
            int32_t k = (int32_t)((i - (size_t)delay) / CAP_SPS);
            step = k < CAP_K * CAP_STEPS ? k : -k;
        }
        uint8_t pat = cap_pattern(step);
        double v = 0;
        for (int p = 0; p < 8; p++) {
            if (pat & (1u << p)) {
                v += 1.0 + cos(theta - 2.0 * M_PI * p / 8.0);
            }
        }
        double noise = ((rand() % 2001) - 1000) / 1000.0 * 2.0; /* +-2 LSB */
        buf[i] = (uint16_t)lround(1000.0 + amp * v + noise);
    }
    return n;
}

static float measure_frac(double theta, int delay, unsigned seed, float *amp_out)
{
    static uint16_t buf[1024];
    synth(buf, 1024, theta, delay, 120.0, seed);
    size_t w = (CAP_K - 4) * CAP_SPC;
    size_t f0 = 2 * CAP_SPC, r0 = (size_t)CAP_K * CAP_SPC + 2 * CAP_SPC;
    cap_iq_t f = cap_demod_iq(buf + f0, w, CAP_SPC, f0);
    cap_iq_t r = cap_demod_iq(buf + r0, w, CAP_SPC, r0);
    if (amp_out) {
        *amp_out = cap_iq_amplitude(f);
    }
    return cap_half_pitch_fraction(f, r);
}

static double wrap_half(double x)
{
    x -= floor(x + 0.5);
    return x;
}

static void test_cap_pattern(void)
{
    CHECK_EQ_INT(cap_pattern(0), 0x0F);
    CHECK_EQ_INT(cap_pattern(1), 0x1E);
    CHECK_EQ_INT(cap_pattern(4), 0xF0);
    CHECK_EQ_INT(cap_pattern(7), 0x87);
    CHECK_EQ_INT(cap_pattern(-1), 0x87);
    CHECK_EQ_INT(cap_pattern(8), 0x0F);
}

static void test_cap_demod(void)
{
    float amp;
    float ref = measure_frac(0.3, 0, 1, &amp);
    CHECK(amp > 50.0f);
    /* independent of the unknown drive/ADC delay */
    int delays[] = {1, 3, 7, 11, 16};
    for (int i = 0; i < 5; i++) {
        float f = measure_frac(0.3, delays[i], 2u + (unsigned)i, NULL);
        CHECK_NEAR(wrap_half(f - ref), 0.0, 0.003);
    }
    /* linear in position: theta moves by d -> fraction moves by -d / pi (half pitch period) */
    for (double th = 0.0; th < 2.0 * M_PI; th += 0.37) {
        float f = measure_frac(th, 5, 99, NULL);
        double expect = ref - (th - 0.3) / M_PI;
        CHECK_NEAR(wrap_half(f - expect), 0.0, 0.003);
    }
    /* no signal -> tiny amplitude (the firmware marks CAP invalid) */
    static uint16_t flat[512];
    for (int i = 0; i < 512; i++) {
        flat[i] = (uint16_t)(2000 + (i % 3));
    }
    cap_iq_t z = cap_demod_iq(flat, 256, CAP_SPC, 0);
    CHECK(cap_iq_amplitude(z) < 2.0f);
}

static void test_cap_unwrap(void)
{
    cap_unwrap_t u;
    cap_unwrap_init(&u);
    CHECK_EQ_INT(cap_unwrap_update(&u, 0.95f), 2413000);
    CHECK_EQ_INT(cap_unwrap_update(&u, 0.05f), 2667000); /* crossed upward */
    CHECK_EQ_INT(cap_unwrap_update(&u, 0.30f), 3302000);
    CHECK_EQ_INT(cap_unwrap_update(&u, 0.90f), 2286000); /* crossed back down */
    CHECK_EQ_INT(cap_unwrap_update(&u, 0.60f), 1524000);
    CHECK_EQ_INT(cap_unwrap_update(&u, 0.20f), 508000);
    CHECK_EQ_INT(cap_unwrap_update(&u, 0.80f), -508000); /* below the start */
}

int main(void)
{
    printf("caliper firmware host tests\n");
    RUN(test_counts_to_nm);
    RUN(test_mm_rounding);
    RUN(test_inch_display);
    RUN(test_zero_hold);
    RUN(test_autohold);
    RUN(test_tolerance);
    RUN(test_stats);
    RUN(test_logrec_pack);
    RUN(test_ring_wraparound);
    RUN(test_gatt_live);
    RUN(test_gatt_uuid);
    RUN(test_gatt_cmd);
    RUN(test_gatt_profile);
    RUN(test_settings_json);
    RUN(test_csv);
    RUN(test_buttons);
    RUN(test_hid);
    RUN(test_as5311_frame);
    RUN(test_as5311_tracking);
    RUN(test_as5311_fine);
    RUN(test_as5311_mismatch);
    RUN(test_pcnt_jump_filter);
    RUN(test_cap_pattern);
    RUN(test_cap_demod);
    RUN(test_cap_unwrap);
    printf("%d checks, %d failures\n", tt_checks, tt_failures);
    return tt_failures ? 1 : 0;
}
