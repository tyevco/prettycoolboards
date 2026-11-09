/*
 * Host tests for the bring-up checks: components/bringup/bringup_eval.c (the pass/fail rules behind
 * the CLI "bu" commands) and the AS5311 count vs SSI cross-check in as5311_proto.c ("bu mag move").
 */
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "as5311_proto.h"
#include "board_pins.h"
#include "bringup_eval.h"
#include "tiny_test.h"

static void test_bu_i2c(void)
{
    const bu_i2c_dev_t *e;
    CHECK_EQ_INT(bu_i2c_expected(&e), 3);
    CHECK_EQ_STR(bu_i2c_name(0x19), "LIS2DW12");
    CHECK_EQ_STR(bu_i2c_name(0x36), "MAX17048");
    CHECK_EQ_STR(bu_i2c_name(0x6A), "BQ25180");
    CHECK(bu_i2c_name(0x50) == NULL);
    /* the table follows board_pins.h (nets.py) */
    CHECK_EQ_INT(I2C_ADDR_LIS2DW12, 0x19);
    CHECK_EQ_INT(I2C_ADDR_MAX17048, 0x36);
    CHECK_EQ_INT(I2C_ADDR_BQ25180, 0x6A);

    bu_i2c_result_t r;
    const uint8_t all[] = {0x6A, 0x19, 0x36}; /* any order */
    CHECK(bu_i2c_eval(all, 3, &r));
    CHECK_EQ_INT(r.n_missing, 0);
    CHECK_EQ_INT(r.n_extra, 0);

    const uint8_t no_gauge[] = {0x19, 0x6A};
    CHECK(!bu_i2c_eval(no_gauge, 2, &r));
    CHECK_EQ_INT(r.n_missing, 1);
    CHECK_EQ_INT(r.missing[0], 0x36);

    const uint8_t extra[] = {0x19, 0x36, 0x6A, 0x18, 0x18}; /* SA0 low would answer at 0x18 */
    CHECK(!bu_i2c_eval(extra, 5, &r));
    CHECK_EQ_INT(r.n_missing, 0);
    CHECK_EQ_INT(r.n_extra, 1); /* duplicates counted once */
    CHECK_EQ_INT(r.extra[0], 0x18);

    CHECK(!bu_i2c_eval(NULL, 0, &r)); /* bus dead: everything missing */
    CHECK_EQ_INT(r.n_missing, 3);

    /* a shorted bus ACKs everything: every extra is listed up to BU_I2C_MAX */
    uint8_t every[BU_I2C_LAST - BU_I2C_FIRST + 1];
    size_t n = 0;
    for (int a = BU_I2C_FIRST; a <= BU_I2C_LAST; a++) {
        every[n++] = (uint8_t)a;
    }
    CHECK(!bu_i2c_eval(every, n, &r));
    CHECK_EQ_INT(r.n_missing, 0);
    CHECK_EQ_INT(r.n_extra, BU_I2C_MAX);
}

static void test_bu_bq_status(void)
{
    char b[256];
    /* VIN good, CC charging, TS normal */
    CHECK(bu_bq_status(0x21, 0x00, 0x00, true, b, sizeof(b)));
    CHECK(strstr(b, "VIN good") != NULL);
    CHECK(strstr(b, "charge CC") != NULL);
    CHECK(strstr(b, "TS normal") != NULL);
    /* battery only, not charging, done / CV decode */
    CHECK(bu_bq_status(0x00, 0x00, 0x00, true, b, sizeof(b)));
    CHECK(strstr(b, "VIN absent") != NULL);
    CHECK(bu_bq_status(0x61, 0x00, 0x00, true, b, sizeof(b)));
    CHECK(strstr(b, "charge done") != NULL);
    CHECK(bu_bq_status(0x41, 0x00, 0x00, true, b, sizeof(b)));
    CHECK(strstr(b, "charge CV") != NULL);
    /* USB without a cell: BUVLO reported, not a failure; regulation loops listed */
    CHECK(bu_bq_status(0x15, 0x40, 0x00, true, b, sizeof(b)));
    CHECK(strstr(b, "BUVLO") != NULL);
    CHECK(strstr(b, "ILIM") != NULL);
    CHECK(strstr(b, "VINDPM") != NULL);
    /* faults */
    CHECK(!bu_bq_status(0x01, 0x80, 0x00, true, b, sizeof(b))); /* VIN OVP */
    CHECK(strstr(b, "over-voltage") != NULL);
    CHECK(!bu_bq_status(0x01, 0x04, 0x00, true, b, sizeof(b))); /* safety timer */
    CHECK(!bu_bq_status(0x81, 0x00, 0x00, true, b, sizeof(b))); /* TS open */
    CHECK(strstr(b, "RT1") != NULL);
    CHECK(bu_bq_status(0x81, 0x00, 0x00, false, b, sizeof(b)));  /* ... unless TS is disabled */
    CHECK(!bu_bq_status(0x01, 0x08, 0x00, true, b, sizeof(b))); /* TS_STAT 01: hot / cold */
    CHECK(bu_bq_status(0x01, 0x10, 0x00, true, b, sizeof(b)));  /* TS_STAT 10: cool, still charging */
    CHECK(strstr(b, "cool") != NULL);
    CHECK(!bu_bq_status(0x01, 0x00, 0x01, true, b, sizeof(b))); /* BAT_OCP flag */
    CHECK(bu_bq_status(0x01, 0x00, 0x84, true, b, sizeof(b)));  /* TS / VIN_OVP flags: history only */
    CHECK(strstr(b, "flags since last read: TS VIN_OVP") != NULL);
    /* a tiny buffer truncates without overrunning */
    char t[8];
    bu_bq_status(0x21, 0x00, 0x00, true, t, sizeof(t));
    CHECK_EQ_INT(strlen(t), 7);
}

static void test_bu_regs(void)
{
    uint8_t dump[BU_BQ_NREGS] = {0};
    dump[0x07] = 0x97;
    dump[0x03] = 0x46;
    dump[0x09] = 0x08;
    const bu_reg_t want[] = {{0x07, 0x97}, {0x03, 0x46}, {0x09, 0x08}};
    char b[160];
    CHECK_EQ_INT(bu_regs_check(want, 3, dump, sizeof(dump), b, sizeof(b)), 0);
    CHECK_EQ_STR(b, "3 registers as written");
    dump[0x07] = 0x17; /* TS_EN lost: a BQ reset or a failed write */
    CHECK_EQ_INT(bu_regs_check(want, 3, dump, sizeof(dump), b, sizeof(b)), 1);
    CHECK_EQ_STR(b, "0x07 = 0x17 (want 0x97)");
    const bu_reg_t beyond[] = {{0x0B, 0x90}, {0x20, 0x00}};
    CHECK_EQ_INT(bu_regs_check(beyond, 2, dump, sizeof(dump), b, sizeof(b)), 2);
    CHECK(strstr(b, "0x20 not read") != NULL);
}

static uint16_t vcell_raw(uint32_t mv)
{
    return (uint16_t)(mv * 1000000u / 78125u);
}

static void test_bu_fg(void)
{
    CHECK_EQ_INT(bu_fg_vcell_mv(vcell_raw(3700)), 3700);
    CHECK_EQ_INT(bu_fg_vcell_mv(0xFFFF), 5119); /* 65535 x 78.125 uV */
    bu_fg_regs_t r = {.version = 0x0012, .vcell = vcell_raw(3700), .soc = 0x3280, .config = 0x971C,
                      .hibrt = 0x8030, .vreset = 0x9700 | 0x0100};
    char b[256];
    CHECK(bu_fg_eval(&r, 0, b, sizeof(b)));
    CHECK(strstr(b, "VCELL 3700 mV") != NULL);
    CHECK(strstr(b, "SOC 50.5 %") != NULL);
    CHECK(bu_fg_eval(&r, 3712, b, sizeof(b))); /* the meter 12 mV higher (Q1 drop, gauge error) */
    CHECK(strstr(b, "-12 mV vs meter") != NULL);
    CHECK(!bu_fg_eval(&r, 3740, b, sizeof(b))); /* 40 mV off */
    bu_fg_regs_t x = r;
    x.version = 0x0000;
    CHECK(!bu_fg_eval(&x, 0, b, sizeof(b)));
    x = r;
    x.version = 0x0011;
    CHECK(bu_fg_eval(&x, 0, b, sizeof(b)));
    x = r;
    x.vcell = vcell_raw(2000); /* no cell: VDD collapsed */
    CHECK(!bu_fg_eval(&x, 0, b, sizeof(b)));
    x = r;
    x.vreset = 0x9600; /* Dis not set */
    CHECK(!bu_fg_eval(&x, 0, b, sizeof(b)));
    CHECK(strstr(b, "VRESET.Dis") != NULL);
    x = r;
    x.hibrt = 0xFFFF; /* left from a ship mode */
    CHECK(!bu_fg_eval(&x, 0, b, sizeof(b)));
    x = r;
    x.config = 0x979C; /* SLEEP */
    CHECK(!bu_fg_eval(&x, 0, b, sizeof(b)));
}

static void test_bu_imu(void)
{
    CHECK_EQ_INT(bu_imu_mg(0), 0);
    CHECK_EQ_INT(bu_imu_mg(16384), 1000);
    CHECK_EQ_INT(bu_imu_mg(-16384), -1000);
    CHECK_EQ_INT(bu_imu_mg(32767), 2000);
    CHECK_EQ_INT(bu_imu_mg(-32768), -2000);
    CHECK_EQ_INT(bu_imu_mg(16), 1); /* 0.98 mg rounds to 1 */
    CHECK_EQ_INT(bu_isqrt(0), 0);
    CHECK_EQ_INT(bu_isqrt(99), 9);
    CHECK_EQ_INT(bu_isqrt(1000000000000ULL), 1000000);
    CHECK_EQ_INT(bu_imu_norm_mg(0, 0, 1000), 1000);
    CHECK_EQ_INT(bu_imu_norm_mg(600, -800, 0), 1000);
    CHECK_EQ_INT(bu_imu_norm_mg(-2000, -2000, -2000), 3464);
    CHECK(bu_imu_still_ok(1000));
    CHECK(bu_imu_still_ok(BU_IMU_G_MIN_MG));
    CHECK(!bu_imu_still_ok(BU_IMU_G_MIN_MG - 1));
    CHECK(!bu_imu_still_ok(0));    /* output stuck at zero */
    CHECK(!bu_imu_still_ok(1300)); /* wrong full scale */

    bu_imu_span_t s;
    bu_imu_span_init(&s);
    CHECK_EQ_INT(bu_imu_span_max(&s), 0);
    const int32_t up[3] = {10, -20, 990}, over[3] = {-30, 15, -1005}, side[3] = {980, 0, 40};
    bu_imu_span_feed(&s, up);
    CHECK_EQ_INT(bu_imu_span_max(&s), 0);
    bu_imu_span_feed(&s, over);
    bu_imu_span_feed(&s, side);
    CHECK_EQ_INT(bu_imu_span_max(&s), 1995);
    CHECK_EQ_INT(s.n, 3);
    char b[256];
    CHECK(bu_imu_move_eval(&s, true, b, sizeof(b)));
    CHECK(!bu_imu_move_eval(&s, false, b, sizeof(b))); /* moved, but INT1 never fired */
    CHECK(strstr(b, "INT1") != NULL);
    bu_imu_span_t still;
    bu_imu_span_init(&still);
    const int32_t a1[3] = {0, 0, 1000}, a2[3] = {100, 50, 980};
    bu_imu_span_feed(&still, a1);
    bu_imu_span_feed(&still, a2);
    CHECK(!bu_imu_move_eval(&still, true, b, sizeof(b))); /* only nudged */
}

static void test_bu_buttons(void)
{
    bu_btn_t b;
    bu_btn_init(&b, 0, 0);
    CHECK_EQ_INT(bu_btn_feed(&b, 0, 10), 0);
    CHECK_EQ_INT(bu_btn_feed(&b, 1, 100), 0);    /* ZERO down */
    CHECK_EQ_INT(bu_btn_feed(&b, 1, 150), 0);
    CHECK_EQ_INT(bu_btn_feed(&b, 0, 180), 1);    /* released after 80 ms: a press */
    CHECK_EQ_INT(b.presses[0], 1);
    CHECK_EQ_INT(b.longest_ms[0], 80);
    CHECK_EQ_INT(bu_btn_feed(&b, 4, 200), 0);    /* MODE glitch of 10 ms */
    CHECK_EQ_INT(bu_btn_feed(&b, 0, 210), 0);
    CHECK_EQ_INT(b.glitches[2], 1);
    CHECK_EQ_INT(b.presses[2], 0);
    CHECK(!bu_btn_all_pressed(&b));
    char s[256];
    CHECK(!bu_btn_eval(&b, s, sizeof(s)));
    CHECK(strstr(s, "not every button") != NULL);
    bu_btn_feed(&b, 2, 300);
    CHECK_EQ_INT(bu_btn_feed(&b, 6, 320), 0); /* HOLD + MODE together */
    CHECK_EQ_INT(bu_btn_feed(&b, 4, 400), 2);  /* HOLD released: 100 ms */
    CHECK_EQ_INT(bu_btn_feed(&b, 0, 420), 4);  /* MODE released: 100 ms */
    CHECK(bu_btn_all_pressed(&b));
    CHECK(bu_btn_eval(&b, s, sizeof(s)));
    CHECK(strstr(s, "MODE 1 press (longest 100 ms) 1 glitch") != NULL);

    /* HOLD down from the start: stuck, and its release does not count as a press */
    bu_btn_init(&b, 2, 0);
    CHECK_EQ_INT(b.stuck, 2);
    CHECK_EQ_INT(bu_btn_feed(&b, 0, 500), 0);
    CHECK_EQ_INT(b.presses[1], 0);
    CHECK_EQ_INT(b.stuck, 0); /* it was released, so it is not stuck */
    bu_btn_feed(&b, 2, 600);
    CHECK_EQ_INT(bu_btn_feed(&b, 0, 700), 2);
    /* never released: still stuck at the end */
    bu_btn_init(&b, 1, 0);
    bu_btn_feed(&b, 1, 5000);
    CHECK(!bu_btn_eval(&b, s, sizeof(s)));
    CHECK(strstr(s, "down at the start: ZERO") != NULL);
}

static void test_bu_as5311(void)
{
    char b[256];
    as5311_frame_t f = {.pos = 2048, .ocf = true};
    CHECK_EQ_INT(bu_as5311_frame_text(as5311_encode(&f), b, sizeof(b)), 1);
    CHECK(strstr(b, "pos 2048 (1.000 mm) OCF 1 COF 0 LIN 0 INC 0 DEC 0 PAR ok: field OK") != NULL);
    uint32_t good = as5311_encode(&f);
    CHECK(bu_as5311_eval(100, 0, good, b, sizeof(b)));
    CHECK(bu_as5311_eval(99, 1, good, b, sizeof(b)));   /* 1 % */
    CHECK(!bu_as5311_eval(98, 2, good, b, sizeof(b)));  /* 2 % */
    CHECK(!bu_as5311_eval(30, 0, good, b, sizeof(b)));  /* too few frames */
    CHECK(!bu_as5311_eval(100, 0, good ^ 0x40u, b, sizeof(b))); /* parity broken */
    CHECK(strstr(b, "parity") != NULL);
    as5311_frame_t m = f;
    m.mag_inc = m.mag_dec = true; /* yellow */
    CHECK(!bu_as5311_eval(100, 0, as5311_encode(&m), b, sizeof(b)));
    CHECK(strstr(b, "marginal") != NULL);
    m.lin = true; /* red */
    CHECK(!bu_as5311_eval(100, 0, as5311_encode(&m), b, sizeof(b)));
    CHECK(strstr(b, "out of range") != NULL);
    as5311_frame_t n = f;
    n.ocf = false;
    CHECK_EQ_INT(bu_as5311_frame_text(as5311_encode(&n), b, sizeof(b)), 0);
    CHECK(strstr(b, "INVALID") != NULL);
    CHECK(!bu_as5311_eval(100, 0, 0x00000u, b, sizeof(b))); /* DO stuck low */
    CHECK(!bu_as5311_eval(100, 0, 0x3FFFFu, b, sizeof(b))); /* DO stuck high (no sensor) */
}

/* A synthetic slide: true position x (LSB) along a path, the SSI = (x + offset) mod 4096, the
 * quadrature count = floor((x - lag) / 4) with lag = the 2-edge direction hysteresis (8 LSB) after a
 * reversal, times sign. Returns the result. */
static int64_t floor4(int32_t v)
{
    return v >= 0 ? v / 4 : -((-v + 3) / 4);
}

static as5311_xc_result_t slide(const int32_t *path, int nseg, int32_t step, int sign, int32_t missed_at,
                                int32_t missed, as5311_xcheck_t *xo)
{
    as5311_xcheck_t x;
    as5311_xcheck_init(&x);
    const int32_t offset = 1234;
    int32_t pos = path[0], lag = 0, lost = 0;
    as5311_xcheck_feed(&x, sign * floor4(pos), (uint16_t)((pos + offset) & 4095)); /* at rest first */
    for (int s = 1; s < nseg; s++) {
        int32_t dir = path[s] > pos ? 1 : -1;
        lag = dir > 0 ? 0 : 8; /* counts trail the SSI by 2 edges going down */
        while (pos != path[s]) {
            int32_t d = path[s] - pos;
            pos += (d > step || d < -step) ? dir * step : d;
            if (missed && pos >= missed_at) {
                lost = missed; /* edges lost once (e.g. a glitch on A/B) */
            }
            int64_t count = floor4(pos - lag) - lost;
            as5311_xcheck_feed(&x, sign * count, (uint16_t)((pos + offset) & 4095));
        }
    }
    if (xo) {
        *xo = x;
    }
    return as5311_xcheck_result(&x);
}

static void test_as5311_xcheck(void)
{
    const int32_t path[] = {0, 12000, 3000, 9000};
    as5311_xcheck_t x;
    CHECK_EQ_INT(slide(path, 4, 37, 1, 0, 0, &x), AS5311_XC_OK);
    CHECK_EQ_INT(x.ssi_u, 9000);
    CHECK_EQ_INT(x.count_d, 2250);
    CHECK(x.dev_p_max <= 12);
    CHECK_EQ_INT(x.max_u - x.min_u, 12000);
    CHECK_EQ_INT(x.travel, 12000 + 9000 + 6000);
    CHECK_EQ_INT(x.max_step, 37);
    /* pole crossings of (x + 1234) mod 4096: up 1234..13234 crosses 4096, 8192, 12288; down to 4234
     * crosses 12288, 8192; up to 10234 crosses 8192 again */
    CHECK_EQ_INT(x.crossings, 6);
    /* the count counting the other way */
    CHECK_EQ_INT(slide(path, 4, 37, -1, 0, 0, NULL), AS5311_XC_INVERTED);
    /* 6 edges lost on the way: 24 LSB */
    CHECK_EQ_INT(slide(path, 4, 37, 1, 6000, 6, &x), AS5311_XC_MISMATCH);
    CHECK(x.dev_p_max >= 24);
    /* one edge lost stays inside the tolerance (it is a slip the firmware re-aligns, not a wiring fault) */
    CHECK_EQ_INT(slide(path, 4, 37, 1, 6000, 1, NULL), AS5311_XC_OK);
    /* too fast: 1600 LSB (0.78 mm) per 10 ms frame */
    CHECK_EQ_INT(slide(path, 4, 1600, 1, 0, 0, NULL), AS5311_XC_FAST);
    /* the limit itself is still fine */
    CHECK_EQ_INT(slide(path, 4, AS5311_XC_MAX_STEP, 1, 0, 0, NULL), AS5311_XC_OK);
    /* less than one pole pair */
    const int32_t shortp[] = {0, 3000, 500};
    CHECK_EQ_INT(slide(shortp, 3, 20, 1, 0, 0, NULL), AS5311_XC_SHORT);
    /* nothing fed */
    as5311_xcheck_init(&x);
    CHECK_EQ_INT(as5311_xcheck_result(&x), AS5311_XC_SHORT);
    CHECK(strstr(as5311_xcheck_str(AS5311_XC_INVERTED), "SSI_SIGN") != NULL);
    /* negative travel and the wrap at 0 */
    const int32_t neg[] = {0, -9000, 0};
    CHECK_EQ_INT(slide(neg, 3, 50, 1, 0, 0, &x), AS5311_XC_OK);
    CHECK_EQ_INT(x.min_u, -9000);
}

static void test_bu_cap(void)
{
    char b[256];
    CHECK(bu_cap_eval(50, 50, 2150.0f, 30.0f, 32.0f, true, b, sizeof(b)));
    CHECK(bu_cap_eval(50, 46, 2150.0f, 30.0f, 32.0f, true, b, sizeof(b)));   /* 92 % */
    CHECK(!bu_cap_eval(50, 40, 2150.0f, 30.0f, 32.0f, true, b, sizeof(b)));  /* 80 % */
    CHECK(!bu_cap_eval(50, 50, 2150.0f, 5.0f, 32.0f, true, b, sizeof(b)));   /* weak forward burst */
    CHECK(bu_cap_eval(50, 0, 2150.0f, 1.5f, 1.2f, false, b, sizeof(b)));     /* no scale: DC only */
    CHECK(!bu_cap_eval(50, 0, 4090.0f, 1.5f, 1.2f, false, b, sizeof(b)));    /* stuck at the rail */
    CHECK(strstr(b, "CAP_VREF") != NULL);
    CHECK(!bu_cap_eval(50, 0, 12.0f, 1.5f, 1.2f, false, b, sizeof(b)));      /* stuck at GND */
    CHECK(!bu_cap_eval(0, 0, 0.0f, 0.0f, 0.0f, false, b, sizeof(b)));
}

void bringup_tests(void)
{
    RUN(test_bu_i2c);
    RUN(test_bu_bq_status);
    RUN(test_bu_regs);
    RUN(test_bu_fg);
    RUN(test_bu_imu);
    RUN(test_bu_buttons);
    RUN(test_bu_as5311);
    RUN(test_as5311_xcheck);
    RUN(test_bu_cap);
}
