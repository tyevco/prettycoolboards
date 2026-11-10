/*
 * Bring-up checks: the pass/fail rules and decoders behind the CLI "bu" commands
 * (components/bringup/bringup.c, docs/bringup.md). Portable C, no ESP-IDF: test/host covers it.
 *
 * Every limit here is a first-board limit from SPEC / the datasheets, marked TVP in docs/bringup.md
 * where it is a typical value or an estimate: tighten them after the first good unit.
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ---- I2C scan ------------------------------------------------------------------------------ */

#define BU_I2C_FIRST 0x08 /* the 7-bit range a scan probes (0x00-0x07, 0x78-0x7F are reserved) */
#define BU_I2C_LAST  0x77
#define BU_I2C_MAX   16   /* devices a scan result keeps */

typedef struct {
    uint8_t addr;
    const char *name;
} bu_i2c_dev_t;

/* The devices the board must answer (board_pins.h, from nets.py): exactly these, nothing else. */
size_t bu_i2c_expected(const bu_i2c_dev_t **out);
const char *bu_i2c_name(uint8_t addr); /* NULL if not an expected device */

typedef struct {
    uint8_t missing[BU_I2C_MAX];
    size_t n_missing;
    uint8_t extra[BU_I2C_MAX];
    size_t n_extra;
} bu_i2c_result_t;

/* found: the addresses that ACKed (any order, duplicates ignored). True = exactly the expected set. */
bool bu_i2c_eval(const uint8_t *found, size_t n, bu_i2c_result_t *r);

/* ---- BQ25180 (SLUSE99C register map) ------------------------------------------------------- */

#define BU_BQ_NREGS 13 /* 0x00 STAT0 .. 0x0C MASK_ID */

/* Decodes STAT0 / STAT1 / FLAG0 into text. False on a fault: VIN over-voltage, a safety-timer fault,
 * a battery over-current flag, and with TS enabled TS open or TS hot/cold (charging suspended).
 * BUVLO (no cell or below 3.0 V) and the regulation-loop bits are reported, not failed. */
bool bu_bq_status(uint8_t stat0, uint8_t stat1, uint8_t flag0, bool ts_enabled, char *buf, size_t len);

typedef struct {
    uint8_t reg, val;
} bu_reg_t;

/* Compares dump[reg] (dump holds registers 0..dump_n-1) with each wanted value. Returns the number
 * of mismatches (a register outside the dump counts as one) and lists them in buf. */
size_t bu_regs_check(const bu_reg_t *want, size_t n, const uint8_t *dump, size_t dump_n, char *buf, size_t len);

/* ---- MAX17048 (Maxim 19-6171) ------------------------------------------------------------- */

#define BU_FG_VCELL_MIN_MV 2500
#define BU_FG_VCELL_MAX_MV 4500
#define BU_FG_VCELL_TOL_MV 30 /* vs a meter on TP2: gauge error + Q1 drop + meter (TVP) */

typedef struct {
    uint16_t version; /* 0x08 */
    uint16_t vcell;   /* 0x02, 78.125 uV/LSB */
    uint16_t soc;     /* 0x04, 1/256 % per LSB */
    uint16_t config;  /* 0x0C */
    uint16_t hibrt;   /* 0x0A */
    uint16_t vreset;  /* 0x18 */
} bu_fg_regs_t;

uint32_t bu_fg_vcell_mv(uint16_t raw);
/* vbat_ref_mv: the meter reading at TP2 (VBAT), 0 = none. False on a wrong VERSION, VCELL outside
 * 2.5-4.5 V or off the reference, or a register power_init should have set (VRESET.Dis = 1,
 * HIBRT = 0x8030, CONFIG.SLEEP = 0) left otherwise. */
bool bu_fg_eval(const bu_fg_regs_t *r, int32_t vbat_ref_mv, char *buf, size_t len);

/* ---- LSM6DSO accelerometer (ST DS12140 Rev 3) ---------------------------------------------- */

#define BU_IMU_WHO_AM_I   0x6C /* WHO_AM_I (0Fh), DS §9.11 */
#define BU_IMU_G_MIN_MG   850  /* |a| at rest: 1 g within the offset/sensitivity tolerance (TVP) */
#define BU_IMU_G_MAX_MG   1150
#define BU_IMU_MOVE_MG    500  /* the motion test: one axis must swing this much */

int32_t bu_imu_mg(int16_t raw); /* +-2 g full scale: 0.061 mg/LSB (DS Table 2, LA_So) */
uint32_t bu_isqrt(uint64_t v);
uint32_t bu_imu_norm_mg(int32_t x, int32_t y, int32_t z);
bool bu_imu_still_ok(uint32_t norm_mg);

typedef struct {
    bool have;
    int32_t min[3], max[3];
    uint32_t n;
} bu_imu_span_t;

void bu_imu_span_init(bu_imu_span_t *s);
void bu_imu_span_feed(bu_imu_span_t *s, const int32_t mg[3]);
int32_t bu_imu_span_max(const bu_imu_span_t *s); /* the largest per-axis swing, mg */
/* True if an axis swung BU_IMU_MOVE_MG and the wake-up interrupt pulled IMU_INT1 low. */
bool bu_imu_move_eval(const bu_imu_span_t *s, bool int1_low_seen, char *buf, size_t len);

/* ---- LSM6DSO gyroscope --------------------------------------------------------------------- */

/* The rest check. The datasheet gives the zero-rate level as +-1 dps TYPICAL (DS Table 2, G_TyOff)
 * and no maximum, so the limit is three times that (TVP: tighten it after the first boards). The
 * peak-to-peak limit only says "the board did not move": the noise is 75 mdps RMS (RnRMS). */
#define BU_GYRO_ZERO_MAX_MDPS 3000
#define BU_GYRO_STILL_PP_MDPS 2000
#define BU_GYRO_MIN_SAMPLES   10
/* The turn check: a wrist turn easily passes 100 dps; 60 dps is 20x the rest limit. */
#define BU_GYRO_TURN_MDPS     60000

/* Sensitivity in micro-dps per LSB from CTRL2_G (11h): FS_125 (bit 1) = +-125 dps, else FS_G (bits
 * 3:2) 00 / 01 / 10 / 11 = +-250 / 500 / 1000 / 2000 dps: 4.375 / 8.75 / 17.50 / 35 / 70 mdps/LSB
 * (DS Table 2, G_So; DS §9.13). */
uint32_t bu_gyro_udps_per_lsb(uint8_t ctrl2_g);
int32_t bu_gyro_mdps(int16_t raw, uint8_t ctrl2_g);
bool bu_gyro_running(uint8_t ctrl2_g); /* ODR_G (bits 7:4) != 0: not in power-down */

typedef struct {
    bool have;
    int32_t min[3], max[3];
    int64_t sum[3];
    uint32_t n;
} bu_gyro_stats_t;

void bu_gyro_stats_init(bu_gyro_stats_t *s);
void bu_gyro_stats_feed(bu_gyro_stats_t *s, const int32_t mdps[3]);
int32_t bu_gyro_stats_mean(const bu_gyro_stats_t *s, int axis);
/* The board lying still. False: too few samples, no axis ever changed (the gyroscope is powered
 * down or not updating: a live one shows noise), an axis moved more than BU_GYRO_STILL_PP_MDPS
 * (it was not lying still: repeat), or a mean beyond BU_GYRO_ZERO_MAX_MDPS. */
bool bu_gyro_rest_eval(const bu_gyro_stats_t *s, char *buf, size_t len);
/* The board being turned by hand. True if some axis reached BU_GYRO_TURN_MDPS either way. The text
 * lists the extremes of each axis with their signs, to check the axis mapping against the turn. */
bool bu_gyro_turn_eval(const bu_gyro_stats_t *s, char *buf, size_t len);

/* ---- buttons ------------------------------------------------------------------------------- */

#define BU_BTN_N      3
#define BU_BTN_MIN_MS 20 /* a press shorter than this is a glitch (the 100 k / 100 nF RC is 10 ms) */

typedef struct {
    uint8_t pressed;               /* last sample, bit i = button i down */
    uint8_t stuck;                 /* down at the start of the test */
    uint32_t t_down[BU_BTN_N];
    uint16_t presses[BU_BTN_N];    /* complete presses >= BU_BTN_MIN_MS */
    uint16_t glitches[BU_BTN_N];   /* lows shorter than that */
    uint32_t longest_ms[BU_BTN_N];
} bu_btn_t;

extern const char *const bu_btn_names[BU_BTN_N]; /* ZERO, HOLD, MODE (bits of buttons.h) */

void bu_btn_init(bu_btn_t *b, uint8_t pressed_now, uint32_t t_ms);
/* Returns the mask of buttons whose press completed (released) at this sample. */
uint8_t bu_btn_feed(bu_btn_t *b, uint8_t pressed, uint32_t t_ms);
bool bu_btn_all_pressed(const bu_btn_t *b);
bool bu_btn_eval(const bu_btn_t *b, char *buf, size_t len);

/* ---- AS5311 -------------------------------------------------------------------------------- */

#define BU_MAG_MIN_FRAMES 50  /* per second: the sensor task reads one per 10 ms sample */
#define BU_MAG_MAX_BAD_PPM 10000 /* 1 % bad frames */

/* "pos 1234 (0.603 mm) OCF 1 COF 0 LIN 0 INC 0 DEC 0 PAR ok: field OK" */
int bu_as5311_frame_text(uint32_t raw18, char *buf, size_t len);
/* frames_ok / frames_bad over the test window, the last frame. True: enough frames, <= 1 % bad, the
 * last one valid with the field in range (green). */
bool bu_as5311_eval(uint32_t frames_ok, uint32_t frames_bad, uint32_t last_raw, char *buf, size_t len);

/* ---- capacitive front-end ------------------------------------------------------------------ */

#define BU_CAP_MEAN_MIN 1700 /* ADC code of CAP_VREF (1.65 V) through the filter at 12 dB (TVP) */
#define BU_CAP_MEAN_MAX 2700
#define BU_CAP_VALID_MIN_PCT 90

/* with_scale: the scale board is fitted under the slider (then bursts must be valid). */
bool bu_cap_eval(uint32_t bursts, uint32_t valid, float mean_lsb, float amp_fwd, float amp_rev, bool with_scale,
                 char *buf, size_t len);

#ifdef __cplusplus
}
#endif
