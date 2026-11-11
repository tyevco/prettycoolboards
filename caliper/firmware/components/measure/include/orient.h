/*
 * orient: which way the caliper is held, from a 6-axis IMU (gyroscope + accelerometer) and, as a
 * slow yaw reference, a compass. Portable C (no ESP-IDF includes); the LSM6DSO driver that feeds it
 * is components/power/imu.c, the IIS2MDC driver components/power/compass.c.
 *
 * Frame: the BOARD frame, right-handed.
 *   +x  along the beam, toward the USB end
 *   +y  toward the buttons / top edge, away from the jaws' beam edge
 *   +z  out of the display face
 * The driver maps the chip's axes into this frame with an orient_mount_t before calling in.
 *
 * What it tracks: the unit vector `up` (the direction opposite to gravity, in board coordinates).
 * An accelerometer at rest reads +1 g on the axis that points up, so `up` = a / |a| whenever the
 * caliper is not being accelerated. Between those moments the gyroscope carries it: a world-fixed
 * vector seen from a body turning at w obeys dv/dt = -w x v, integrated exactly (Rodrigues) per
 * sample. A complementary filter then pulls `up` toward the accelerometer direction with time
 * constant tau, but only while | |a| - 1 g | <= acc_gate (a shake or a swing is not gravity).
 *
 *   roll, pitch   ABSOLUTE (gravity is the reference), read off `up`.
 *   yaw           RELATIVE and it DRIFTS. It is the integral of the turn rate about the vertical
 *                 (w . up) since power-on or the last orient_zero_yaw(); yaw_unc_deg says how far
 *                 it may be off by now. Good for "turned about a quarter since I zeroed", not for a
 *                 heading. Without a calibrated compass nothing ties it to anything else.
 *   heading       only with a calibrated compass: the MAGNETIC heading of the beam, and a limit on
 *                 how far the yaw can drift (see "compass" below). It is the direction of the
 *                 field AT THE SENSOR, 11 mm from a steel beam and next to the battery: a
 *                 best-effort reference that can be tens of degrees from magnetic north and moves
 *                 with the slider. It is never true north.
 *   bias          the gyro's zero-rate level, learned whenever the caliper lies still for rest_ms
 *                 (both sensors quiet over the whole window) and subtracted from then on.
 *   steady        held still enough to read: low rate and |a| = 1 g for steady_ms. Looser and
 *                 quicker than "at rest" (a hand, not a table).
 *
 * Every threshold in orient_cfg_default() is a first guess from the datasheet noise figures, not a
 * measurement (TVP): tune them on the first board.
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    float x, y, z;
} orient_vec_t;

/* ---- chip -> board axis mapping ------------------------------------------------------------ */

/* board = row * chip: row[i][j] is the weight of chip axis j in board axis i. A mounting is a
 * signed permutation with determinant +1 (a rotation; -1 would be a mirror image and turn every
 * rotation backwards). */
typedef struct {
    int8_t row[3][3];
} orient_mount_t;

bool orient_mount_valid(const orient_mount_t *m);
orient_vec_t orient_mount_apply(const orient_mount_t *m, orient_vec_t chip);

/* ---- filter -------------------------------------------------------------------------------- */

#define ORIENT_DT_MAX_US 100000u /* a longer gap between samples: the turn in it is unknown */

typedef struct {
    float tau_s;              /* complementary filter time constant toward the accelerometer */
    float acc_gate_g;         /* the accelerometer is gravity while | |a| - 1 | <= this */
    float steady_dps;         /* "steady": |rate| at most this ... */
    float steady_g;           /* ... and | |a| - 1 | at most this ... */
    uint32_t steady_ms;       /* ... for this long */
    uint32_t rest_ms;         /* "at rest": the window both sensors must stay quiet over */
    float rest_gyro_pp_dps;   /* gyro peak-to-peak per axis inside the window */
    float rest_acc_pp_g;      /* accelerometer peak-to-peak per axis inside the window */
    float bias_max_dps;       /* a window mean beyond this is a slow turn or a fault, not a bias */
    float bias_alpha;         /* low-pass weight of a new window mean once a bias exists */
    float drift_unbiased_dps; /* yaw uncertainty growth before the first bias estimate */
    float drift_biased_dps;   /* ... and after it */
    /* the compass: when its field is believed, and what a believed heading is worth */
    float cmp_abs_min_ut;     /* the field is the Earth's while |B| is inside this window ... */
    float cmp_abs_max_ut;
    float cmp_ref_tol;        /* ... and within this fraction of the calibrated |B| ... */
    float cmp_dip_tol_deg;    /* ... and its dip within this of the dip learned so far ... */
    uint32_t cmp_hold_ms;     /* ... for this long without a break */
    float cmp_dip_tau_s;      /* how slowly the learned dip follows the measured one */
    float cmp_vert_cos;       /* no heading with the beam closer to vertical than acos(this) */
    float cmp_rate_max_dps;   /* ... or while turning faster than this (a 10 Hz sample lags) */
    float cmp_tau_s;          /* complementary filter time constant toward the compass */
    float cmp_unc_deg;        /* what a believed heading may still be off by (soft iron, currents) */
} orient_cfg_t;

void orient_cfg_default(orient_cfg_t *c);

/* ---- compass ------------------------------------------------------------------------------- */

/*
 * The field arrives in the board frame in microtesla, as measured. What becomes of it:
 *
 *   calibration   hard iron only: off_ut is subtracted. There is no soft-iron matrix, so what the
 *                 steel beam does to the field's direction stays in the heading.
 *   plausible?    |B| inside cmp_abs_min_ut..cmp_abs_max_ut AND within cmp_ref_tol of the
 *                 calibrated |B| AND the dip (the field's angle below the horizontal, from `up`)
 *                 within cmp_dip_tol_deg of the value learned so far, all for cmp_hold_ms. If not:
 *                 field_disturbed, no correction, and the gyro carries the heading and the yaw
 *                 exactly as it does without a compass. A disturbance of the right size and dip
 *                 passes, and so does one that lasts (the learned dip follows it with
 *                 cmp_dip_tau_s): nothing here can tell those from the Earth's field.
 *   heading       of board +x projected on the horizontal plane, clockwise from the horizontal
 *                 field seen from above (0 = +x toward magnetic north, 90 = east), 0..360. Not
 *                 taken with the beam or the field near vertical, or in a fast turn. The gyro
 *                 carries it between samples; a believed sample pulls it with cmp_tau_s.
 *   yaw           heading + yaw is constant, so the heading at the moment the yaw was zeroed says
 *                 what the yaw must be now, to within about twice cmp_unc_deg. While yaw_unc_deg
 *                 is below that floor the gyro is the better of the two and the yaw is NOT
 *                 touched; above it the yaw is pulled toward the compass with cmp_tau_s and
 *                 yaw_unc_deg comes down to the floor. After a lost yaw (clipping, a gap) it is set
 *                 from the compass at once.
 */
typedef struct {
    orient_vec_t off_ut; /* hard-iron offset */
    float ref_ut;        /* |B| with the offset removed; 0 = not calibrated: the compass is not used */
} orient_compass_cal_t;

#define ORIENT_COMPASS_MIN_UT   20.0f /* the Earth's field is about 25-65 uT */
#define ORIENT_COMPASS_MAX_UT   75.0f
#define ORIENT_COMPASS_SPAN_TOL 0.3f  /* each axis' half span within this fraction of their mean */

/* Hard-iron calibration by the minimum and maximum per axis while the caliper is turned through
 * every orientation: the offset is the middle of each span, |B| the mean half span. Noise widens
 * the spans, so |B| comes out a few percent high. Zero-initialise. */
typedef struct {
    bool have;
    orient_vec_t min, max;
    uint32_t n;
} orient_compass_span_t;

void orient_compass_span_feed(orient_compass_span_t *s, orient_vec_t raw_ut);
/* Fills cal either way (to print it). False, and cal must not be used: |B| outside
 * ORIENT_COMPASS_MIN_UT..MAX_UT, or an axis whose half span is off the mean by more than
 * ORIENT_COMPASS_SPAN_TOL (not turned all the way round, or iron that bends the field). */
bool orient_compass_span_cal(const orient_compass_span_t *s, orient_compass_cal_t *cal);

typedef enum {
    ORIENT_FACE_TILTED = 0,   /* no board axis within about 37 deg of vertical */
    ORIENT_FACE_DISPLAY_UP,   /* +z up: lying on its back */
    ORIENT_FACE_DISPLAY_DOWN, /* -z up */
    ORIENT_FACE_TOP_UP,       /* +y up: standing on the jaws' edge, buttons on top */
    ORIENT_FACE_TOP_DOWN,     /* -y up: upside down */
    ORIENT_FACE_USB_UP,       /* +x up: standing on end, USB at the top */
    ORIENT_FACE_USB_DOWN,     /* -x up */
} orient_face_t;

const char *orient_face_name(orient_face_t f);

typedef struct {
    orient_cfg_t cfg;
    bool valid;
    orient_vec_t up;       /* unit vector, board frame */
    orient_vec_t rate_dps; /* the last bias-corrected rate */
    float acc_abs_g;
    float yaw_deg, yaw_unc_deg;
    bool bias_valid;
    orient_vec_t bias_dps;
    bool steady;
    uint32_t steady_us;
    bool at_rest;
    /* the rest window */
    uint32_t win_us, win_n;
    orient_vec_t g_min, g_max, g_sum, a_min, a_max;
    uint32_t n; /* samples fed */
    /* the compass: all zero, and none of it ever changes, until a calibration is set */
    orient_compass_cal_t cmp_cal;
    float field_abs_ut;   /* the last |B|, offset removed */
    float dip_deg;        /* the last dip */
    bool dip_valid;
    float dip_ref_deg;    /* the learned dip */
    bool cmp_disturbed;   /* the field failed the magnitude or the dip test and has not held since */
    bool cmp_ok;          /* the last sample gave a heading */
    uint32_t cmp_ok_us;   /* how long the field has been plausible without a break */
    uint32_t cmp_age_us;  /* since the last compass sample */
    bool hdg_lock;        /* a heading has been taken: hdg_deg means something */
    float hdg_deg;        /* -180..180, carried by the gyro, pulled by the compass */
    float hdg_unc_deg;
    bool yaw_ref;         /* yaw_ref_deg means something */
    float yaw_ref_deg;    /* the heading at yaw = 0 */
    float yaw_floor_deg;  /* what the compass can hold yaw_unc_deg down to */
} orient_t;

typedef struct {
    bool valid;         /* a gravity reference has been seen: everything below means something */
    float roll_deg;     /* about the beam: 0 display up, +90 top edge up, -90 top edge down, +-180 display down */
    float pitch_deg;    /* the beam against the horizon: +90 USB end straight up, -90 straight down */
    float tilt_deg;     /* the display normal against vertical: 0 flat display up .. 180 display down */
    float yaw_deg;      /* relative, -180..180, counter-clockwise seen from above is positive; DRIFTS */
    float yaw_unc_deg;  /* how far yaw may have drifted since it was zeroed (0..180; 180 = unknown) */
    orient_vec_t up;
    orient_vec_t rate_dps; /* bias-corrected angular rate, board axes */
    float rate_abs_dps;
    float acc_abs_g;
    bool steady;
    bool at_rest;
    bool bias_valid;
    orient_vec_t bias_dps;
    orient_face_t face;
    /* the compass: false / 0 (heading_unc_deg 180) without a calibrated one */
    bool heading_valid;    /* taken from a plausible field just now; false: carried by the gyro, or unknown */
    float heading_deg;     /* MAGNETIC, in the distorted field at the sensor, 0..360 clockwise; NOT true north */
    float heading_unc_deg; /* how far heading_deg may be off (0..180; 180 = unknown) */
    bool field_disturbed;  /* not the calibrated Earth's field: steel, a magnet, a current */
    float field_abs_ut;    /* |B| with the hard-iron offset removed */
    float dip_deg;         /* the field below the horizontal (positive in the northern hemisphere) */
} orient_out_t;

void orient_init(orient_t *o, const orient_cfg_t *cfg); /* cfg NULL = orient_cfg_default() */
/* One sample: gyro in dps and accelerometer in g, both in the board frame, dt since the previous
 * sample. gyro_clipped: an axis sat at full scale, so the rate (and with it the yaw) is unknown.
 * A dt above ORIENT_DT_MAX_US is integrated as that maximum and also voids the yaw. */
void orient_update(orient_t *o, orient_vec_t gyro_dps, orient_vec_t acc_g, uint32_t dt_us, bool gyro_clipped);
void orient_get(const orient_t *o, orient_out_t *out);
void orient_zero_yaw(orient_t *o); /* yaw = 0, uncertainty = 0, from here */
/* The hard-iron calibration; NULL or ref_ut 0 = none, and the compass is ignored. orient_init()
 * clears it. Setting one starts the dip learning and the heading over. */
void orient_compass_set_cal(orient_t *o, const orient_compass_cal_t *cal);
/* One compass sample: the field in uT in the board frame, as measured, dt since the previous one.
 * Does nothing without a calibration or before the first gravity reference. */
void orient_compass_update(orient_t *o, orient_vec_t raw_ut, uint32_t dt_us);

/* ---- display flip -------------------------------------------------------------------------- */

#define ORIENT_FLIP_SIN     0.35f /* the top edge at least ~20 deg above / below the horizon */
#define ORIENT_FLIP_HOLD_MS 600u

typedef struct {
    bool flipped;
    uint32_t pend_ms;
} orient_flip_t;

/* Should the display be turned 180 deg? Flipped when the board's top edge points down (up.y <=
 * -ORIENT_FLIP_SIN), normal when it points up (>= +ORIENT_FLIP_SIN); in between (lying flat, or
 * standing on end) the current state is kept. A change must persist ORIENT_FLIP_HOLD_MS. Returns
 * true when f->flipped changed. */
bool orient_flip_update(orient_flip_t *f, const orient_out_t *o, uint32_t dt_ms);

#ifdef __cplusplus
}
#endif
