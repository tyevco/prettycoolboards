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
    CHECK_EQ_INT(bu_i2c_expected(&e), 4);
    CHECK_EQ_STR(bu_i2c_name(0x6B), "LSM6DSO");
    CHECK_EQ_STR(bu_i2c_name(0x36), "MAX17048");
    CHECK_EQ_STR(bu_i2c_name(0x6A), "BQ25180");
    CHECK_EQ_STR(bu_i2c_name(0x1E), "IIS2MDC");
    CHECK(bu_i2c_name(0x50) == NULL);
    /* the table follows board_pins.h (nets.py) */
    CHECK_EQ_INT(I2C_ADDR_LSM6DSO, 0x6B);
    CHECK_EQ_INT(I2C_ADDR_MAX17048, 0x36);
    CHECK_EQ_INT(I2C_ADDR_BQ25180, 0x6A);
    CHECK_EQ_INT(I2C_ADDR_IIS2MDC, 0x1E);

    bu_i2c_result_t r;
    const uint8_t all[] = {0x6A, 0x6B, 0x1E, 0x36}; /* any order */
    CHECK(bu_i2c_eval(all, 4, &r));
    CHECK_EQ_INT(r.n_missing, 0);
    CHECK_EQ_INT(r.n_extra, 0);

    const uint8_t no_gauge[] = {0x6B, 0x6A, 0x1E};
    CHECK(!bu_i2c_eval(no_gauge, 3, &r));
    CHECK_EQ_INT(r.n_missing, 1);
    CHECK_EQ_INT(r.missing[0], 0x36);

    /* U61 not populated (or not answering): the three chips of before are not enough any more */
    const uint8_t no_compass[] = {0x36, 0x6A, 0x6B};
    CHECK(!bu_i2c_eval(no_compass, 3, &r));
    CHECK_EQ_INT(r.n_missing, 1);
    CHECK_EQ_INT(r.missing[0], 0x1E);
    CHECK_EQ_INT(r.n_extra, 0);

    /* SA0 open or low: the LSM6DSO answers at 0x6A, on top of the BQ25180. The scan then shows
     * 0x6A alone with the IMU missing (docs/bringup.md) */
    const uint8_t sa0_low[] = {0x1E, 0x36, 0x6A};
    CHECK(!bu_i2c_eval(sa0_low, 3, &r));
    CHECK_EQ_INT(r.n_missing, 1);
    CHECK_EQ_INT(r.missing[0], 0x6B);
    CHECK_EQ_INT(r.n_extra, 0);

    const uint8_t extra[] = {0x6B, 0x36, 0x6A, 0x1E, 0x18, 0x18}; /* something that is not on the board */
    CHECK(!bu_i2c_eval(extra, 6, &r));
    CHECK_EQ_INT(r.n_missing, 0);
    CHECK_EQ_INT(r.n_extra, 1); /* duplicates counted once */
    CHECK_EQ_INT(r.extra[0], 0x18);

    CHECK(!bu_i2c_eval(NULL, 0, &r)); /* bus dead: everything missing */
    CHECK_EQ_INT(r.n_missing, 4);

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
    /* LSM6DSO: 0.061 mg/LSB at +-2 g (DS12140 Table 2) */
    CHECK_EQ_INT(BU_IMU_WHO_AM_I, 0x6C);
    CHECK_EQ_INT(bu_imu_mg(16393), 1000); /* 1 g = 1 / 0.000061 LSB */
    CHECK_EQ_INT(bu_imu_mg(-16393), -1000);
    CHECK_EQ_INT(bu_imu_mg(16384), 999);
    CHECK_EQ_INT(bu_imu_mg(32767), 1999);
    CHECK_EQ_INT(bu_imu_mg(-32768), -1999);
    CHECK_EQ_INT(bu_imu_mg(16), 1);  /* 0.976 mg rounds to 1 */
    CHECK_EQ_INT(bu_imu_mg(-8), 0);  /* -0.488 mg */
    CHECK_EQ_INT(bu_imu_mg(-9), -1); /* -0.549 mg: half away from zero */
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

/* n readings of a field of (x, y, z) nT with a few LSB of noise on each axis */
static void compass_feed(bu_gyro_stats_t *s, int n, int32_t x, int32_t y, int32_t z)
{
    bu_gyro_stats_init(s);
    for (int i = 0; i < n; i++) {
        int32_t v[3] = {x + 150 * (i % 3), y + 150 * (i % 2), z - 150 * (i % 4)};
        bu_gyro_stats_feed(s, v);
    }
}

static void test_bu_compass(void)
{
    /* 1.5 mgauss/LSB (ST iis2mdc_reg.c, iis2mdc_from_lsb_to_mgauss) = 150 nT/LSB */
    CHECK_EQ_INT(bu_compass_nt(0), 0);
    CHECK_EQ_INT(bu_compass_nt(1), 150);
    CHECK_EQ_INT(bu_compass_nt(-1), -150);
    CHECK_EQ_INT(bu_compass_nt(32767), 4915050);
    CHECK_EQ_INT(bu_compass_nt(-32768), -4915200);
    /* CFG_REG_A (60h): md bits 1:0, 00 continuous / 01 single / 10 power-down (iis2mdc_reg.h) */
    CHECK(bu_compass_running(0x90));  /* what compass.c writes awake */
    CHECK(!bu_compass_running(0x92)); /* and before deep sleep */
    CHECK(!bu_compass_running(0x91));
    CHECK(!bu_compass_running(0x03));
    CHECK_EQ_INT(BU_COMPASS_WHO_AM_I, 0x40);

    char b[240];
    bu_gyro_stats_t s;
    bu_gyro_stats_init(&s);
    CHECK(!bu_compass_eval(&s, b, sizeof(b))); /* nothing read */
    CHECK(strstr(b, "only 0 samples") != NULL);

    /* the Earth's field at mid latitudes, display up, USB end toward north: 20 uT north, 45 down */
    compass_feed(&s, 8, 20000, -300, -45000);
    CHECK(bu_compass_eval(&s, b, sizeof(b)));
    CHECK(strstr(b, "8 samples, X 20.1 Y -0.2 Z -45.2 uT, |B| 49.5 uT") != NULL);
    CHECK(strstr(b, "FAIL") == NULL);

    /* next to steel: several times the Earth's field still passes, this is not the plausibility
     * gate of the filter */
    compass_feed(&s, 8, 250000, -120000, 90000);
    CHECK(bu_compass_eval(&s, b, sizeof(b)));
    compass_feed(&s, 8, 0, 9000, 6000); /* 10.8 uT: the bottom of the window */
    CHECK(bu_compass_eval(&s, b, sizeof(b)));

    compass_feed(&s, 3, 20000, -300, -45000);
    CHECK(!bu_compass_eval(&s, b, sizeof(b)));
    CHECK(strstr(b, "only 3 samples") != NULL);

    /* a dead part: every reading the same (here 0) */
    bu_gyro_stats_init(&s);
    for (int i = 0; i < 8; i++) {
        const int32_t v[3] = {0, 0, 0};
        bu_gyro_stats_feed(&s, v);
    }
    CHECK(!bu_compass_eval(&s, b, sizeof(b)));
    CHECK(strstr(b, "no axis ever changed") != NULL);
    /* alive, but no field to speak of / far too much of it */
    compass_feed(&s, 8, 1500, -3000, 4500);
    CHECK(!bu_compass_eval(&s, b, sizeof(b)));
    CHECK(strstr(b, "|B| outside") != NULL);
    compass_feed(&s, 8, 900000, 500000, 0);
    CHECK(!bu_compass_eval(&s, b, sizeof(b)));
    CHECK(strstr(b, "|B| outside") != NULL);
    /* an axis at the rail, either way */
    compass_feed(&s, 8, 20000, -300, bu_compass_nt(32767));
    CHECK(!bu_compass_eval(&s, b, sizeof(b)));
    CHECK(strstr(b, "Z at full scale") != NULL);
    compass_feed(&s, 8, bu_compass_nt(-32768), -300, -45000);
    CHECK(!bu_compass_eval(&s, b, sizeof(b)));
    CHECK(strstr(b, "X at full scale") != NULL);
}

static void test_bu_gyro(void)
{
    /* CTRL2_G (11h): FS_G bits 3:2, FS_125 bit 1; DS12140 Table 2 G_So */
    CHECK_EQ_INT(bu_gyro_udps_per_lsb(0x30), 8750);  /* 52 Hz, +-250 dps */
    CHECK_EQ_INT(bu_gyro_udps_per_lsb(0x34), 17500); /* +-500 */
    CHECK_EQ_INT(bu_gyro_udps_per_lsb(0x38), 35000); /* +-1000: what imu.c writes */
    CHECK_EQ_INT(bu_gyro_udps_per_lsb(0x3C), 70000); /* +-2000 */
    CHECK_EQ_INT(bu_gyro_udps_per_lsb(0x32), 4375);  /* FS_125 */
    CHECK_EQ_INT(bu_gyro_udps_per_lsb(0x3E), 4375);  /* FS_125 wins over FS_G */
    CHECK(bu_gyro_running(0x38));
    CHECK(bu_gyro_running(0x10));
    CHECK(!bu_gyro_running(0x08)); /* a full scale set, ODR 0: powered down */
    CHECK_EQ_INT(bu_gyro_mdps(0, 0x38), 0);
    CHECK_EQ_INT(bu_gyro_mdps(1, 0x38), 35);
    CHECK_EQ_INT(bu_gyro_mdps(-1, 0x38), -35);
    CHECK_EQ_INT(bu_gyro_mdps(28571, 0x38), 999985); /* just under 1000 dps */
    CHECK_EQ_INT(bu_gyro_mdps(32767, 0x38), 1146845);
    CHECK_EQ_INT(bu_gyro_mdps(-32768, 0x3C), -2293760);
    CHECK_EQ_INT(bu_gyro_mdps(1, 0x32), 4);   /* 4.375 */
    CHECK_EQ_INT(bu_gyro_mdps(-1, 0x32), -4);
    CHECK_EQ_INT(bu_gyro_mdps(4, 0x32), 18);  /* 17.5 rounds away from zero */
    CHECK_EQ_INT(bu_gyro_mdps(-4, 0x32), -18);

    char b[320];
    bu_gyro_stats_t s;
    bu_gyro_stats_init(&s);
    CHECK_EQ_INT(bu_gyro_stats_mean(&s, 0), 0);
    CHECK(!bu_gyro_rest_eval(&s, b, sizeof(b))); /* nothing read */
    CHECK(strstr(b, "samples") != NULL);
    CHECK(!bu_gyro_turn_eval(&s, b, sizeof(b)));

    /* at rest: a 0.5 dps offset on X, a few LSB of noise (35 mdps steps at +-1000 dps) */
    for (int i = 0; i < 50; i++) {
        const int32_t v[3] = {490 + (i % 3) * 35, -105 + (i % 2) * 70, (i % 4) * 35 - 70};
        bu_gyro_stats_feed(&s, v);
    }
    CHECK_EQ_INT(s.n, 50);
    CHECK_EQ_INT(bu_gyro_stats_mean(&s, 0), 524); /* 490 + 35 * 49 / 50 = 524.3 */
    CHECK_EQ_INT(bu_gyro_stats_mean(&s, 1), -70);
    CHECK_EQ_INT(bu_gyro_stats_mean(&s, 2), -19); /* (-70 * 13 - 35 * 13 + 35 * 12) / 50 = -18.9 */
    CHECK(bu_gyro_rest_eval(&s, b, sizeof(b)));
    CHECK(strstr(b, "FAIL") == NULL);
    CHECK(!bu_gyro_turn_eval(&s, b, sizeof(b))); /* lying still is not a turn */
    CHECK(strstr(b, "FAIL") != NULL);

    /* too few samples */
    bu_gyro_stats_t few;
    bu_gyro_stats_init(&few);
    for (int i = 0; i < BU_GYRO_MIN_SAMPLES - 1; i++) {
        const int32_t v[3] = {i * 35, 0, 35};
        bu_gyro_stats_feed(&few, v);
    }
    CHECK(!bu_gyro_rest_eval(&few, b, sizeof(b)));

    /* powered down: the output registers hold one value */
    bu_gyro_stats_t dead;
    bu_gyro_stats_init(&dead);
    for (int i = 0; i < 50; i++) {
        const int32_t v[3] = {0, 0, 0};
        bu_gyro_stats_feed(&dead, v);
    }
    CHECK(!bu_gyro_rest_eval(&dead, b, sizeof(b)));
    CHECK(strstr(b, "powered down") != NULL);

    /* a zero-rate level beyond the limit, either sign */
    bu_gyro_stats_t off;
    bu_gyro_stats_init(&off);
    for (int i = 0; i < 50; i++) {
        const int32_t v[3] = {(i % 2) * 35, -(BU_GYRO_ZERO_MAX_MDPS + 100) + (i % 2) * 35, 0};
        bu_gyro_stats_feed(&off, v);
    }
    CHECK(!bu_gyro_rest_eval(&off, b, sizeof(b)));
    CHECK(strstr(b, "Y zero-rate") != NULL);
    CHECK(strstr(b, "X zero-rate") == NULL);
    /* exactly at the limit passes */
    bu_gyro_stats_t edge;
    bu_gyro_stats_init(&edge);
    for (int i = 0; i < 50; i++) {
        const int32_t v[3] = {BU_GYRO_ZERO_MAX_MDPS - 35 + (i % 3) * 35, 0, (i % 2) * 35};
        bu_gyro_stats_feed(&edge, v);
    }
    CHECK_EQ_INT(bu_gyro_stats_mean(&edge, 0), 2999); /* 2965 + 35 * 49 / 50 */
    CHECK(bu_gyro_rest_eval(&edge, b, sizeof(b)));

    /* moved during the rest check: reported as that, not as an offset */
    bu_gyro_stats_t moved;
    bu_gyro_stats_init(&moved);
    for (int i = 0; i < 50; i++) {
        const int32_t v[3] = {i == 20 ? 9000 : (i % 2) * 35, 0, 35 * (i % 3)};
        bu_gyro_stats_feed(&moved, v);
    }
    CHECK(!bu_gyro_rest_eval(&moved, b, sizeof(b)));
    CHECK(strstr(b, "not lying still") != NULL);
    CHECK(strstr(b, "zero-rate") == NULL);

    /* a turn about -Z (clockwise seen from the display side): the sign is in the text */
    bu_gyro_stats_t turn;
    bu_gyro_stats_init(&turn);
    for (int i = 0; i < 100; i++) {
        const int32_t v[3] = {(i % 5) * 700 - 1400, 2100 - (i % 7) * 700, i < 50 ? -i * 3500 : -(99 - i) * 3500};
        bu_gyro_stats_feed(&turn, v);
    }
    CHECK(bu_gyro_turn_eval(&turn, b, sizeof(b)));
    CHECK(strstr(b, "Z -171..+0") != NULL);
    CHECK(strstr(b, "FAIL") == NULL);
    /* 59 dps is not enough, 60 is, on any axis and either sign */
    bu_gyro_stats_t slow;
    bu_gyro_stats_init(&slow);
    const int32_t v59[3] = {0, BU_GYRO_TURN_MDPS - 1, 0}, vm60[3] = {-BU_GYRO_TURN_MDPS, 0, 0};
    bu_gyro_stats_feed(&slow, v59);
    CHECK(!bu_gyro_turn_eval(&slow, b, sizeof(b)));
    CHECK(strstr(b, "faster") != NULL);
    bu_gyro_stats_feed(&slow, vm60);
    CHECK(bu_gyro_turn_eval(&slow, b, sizeof(b)));
    /* truncation is safe */
    char tiny[8];
    bu_gyro_rest_eval(&moved, tiny, sizeof(tiny));
    CHECK(strlen(tiny) < sizeof(tiny));
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
    RUN(test_bu_gyro);
    RUN(test_bu_compass);
    RUN(test_bu_buttons);
    RUN(test_bu_as5311);
    RUN(test_as5311_xcheck);
    RUN(test_bu_cap);
}
