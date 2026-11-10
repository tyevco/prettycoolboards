/*
 * orient: which way the caliper is held, from a 6-axis IMU (gyroscope + accelerometer). Portable C
 * (no ESP-IDF includes); the LSM6DSO driver that feeds it is components/power/imu.c.
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
 *   yaw           RELATIVE and it DRIFTS: there is no magnetometer, so nothing ties it to north or
 *                 to anything else. It is the integral of the turn rate about the vertical (w . up)
 *                 since power-on or the last orient_zero_yaw(); yaw_unc_deg says how far it may be
 *                 off by now. Good for "turned about a quarter since I zeroed", not for a heading.
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
} orient_cfg_t;

void orient_cfg_default(orient_cfg_t *c);

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
} orient_out_t;

void orient_init(orient_t *o, const orient_cfg_t *cfg); /* cfg NULL = orient_cfg_default() */
/* One sample: gyro in dps and accelerometer in g, both in the board frame, dt since the previous
 * sample. gyro_clipped: an axis sat at full scale, so the rate (and with it the yaw) is unknown.
 * A dt above ORIENT_DT_MAX_US is integrated as that maximum and also voids the yaw. */
void orient_update(orient_t *o, orient_vec_t gyro_dps, orient_vec_t acc_g, uint32_t dt_us, bool gyro_clipped);
void orient_get(const orient_t *o, orient_out_t *out);
void orient_zero_yaw(orient_t *o); /* yaw = 0, uncertainty = 0, from here */

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
