/* orient: roll / pitch from gravity, relative yaw from the gyro, gyro bias at rest. Portable C. */
#include "orient.h"

#include <math.h>
#include <string.h>

#define RAD2DEG  57.29577951f
#define DEG2RAD  0.01745329252f
#define FACE_COS 0.8f /* an axis within acos(0.8) = 37 deg of vertical names the face */
#define REST_MIN_N 8u /* a rest window needs at least this many samples to mean anything */

/* ---- vectors ------------------------------------------------------------------------------- */

static orient_vec_t v3(float x, float y, float z)
{
    orient_vec_t v = {x, y, z};
    return v;
}

static orient_vec_t v_sub(orient_vec_t a, orient_vec_t b)
{
    return v3(a.x - b.x, a.y - b.y, a.z - b.z);
}

static orient_vec_t v_add(orient_vec_t a, orient_vec_t b)
{
    return v3(a.x + b.x, a.y + b.y, a.z + b.z);
}

static orient_vec_t v_scale(orient_vec_t a, float k)
{
    return v3(a.x * k, a.y * k, a.z * k);
}

static float v_dot(orient_vec_t a, orient_vec_t b)
{
    return a.x * b.x + a.y * b.y + a.z * b.z;
}

static orient_vec_t v_cross(orient_vec_t a, orient_vec_t b)
{
    return v3(a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x);
}

static float v_abs(orient_vec_t a)
{
    return sqrtf(v_dot(a, a));
}

static orient_vec_t v_min(orient_vec_t a, orient_vec_t b)
{
    return v3(a.x < b.x ? a.x : b.x, a.y < b.y ? a.y : b.y, a.z < b.z ? a.z : b.z);
}

static orient_vec_t v_max(orient_vec_t a, orient_vec_t b)
{
    return v3(a.x > b.x ? a.x : b.x, a.y > b.y ? a.y : b.y, a.z > b.z ? a.z : b.z);
}

/* every component of |a| at most lim */
static bool v_within(orient_vec_t a, float lim)
{
    return fabsf(a.x) <= lim && fabsf(a.y) <= lim && fabsf(a.z) <= lim;
}

static float clampf(float v, float lo, float hi)
{
    return v < lo ? lo : (v > hi ? hi : v);
}

/* ---- mounting ------------------------------------------------------------------------------ */

bool orient_mount_valid(const orient_mount_t *m)
{
    for (int i = 0; i < 3; i++) {
        int in_row = 0, in_col = 0;
        for (int j = 0; j < 3; j++) {
            int r = m->row[i][j], c = m->row[j][i];
            if (r < -1 || r > 1) {
                return false;
            }
            in_row += r != 0;
            in_col += c != 0;
        }
        if (in_row != 1 || in_col != 1) {
            return false;
        }
    }
    const int8_t (*a)[3] = m->row;
    int det = a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1]) - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0]) +
              a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]);
    return det == 1;
}

orient_vec_t orient_mount_apply(const orient_mount_t *m, orient_vec_t c)
{
    const int8_t (*a)[3] = m->row;
    return v3((float)a[0][0] * c.x + (float)a[0][1] * c.y + (float)a[0][2] * c.z,
              (float)a[1][0] * c.x + (float)a[1][1] * c.y + (float)a[1][2] * c.z,
              (float)a[2][0] * c.x + (float)a[2][1] * c.y + (float)a[2][2] * c.z);
}

/* ---- filter -------------------------------------------------------------------------------- */

void orient_cfg_default(orient_cfg_t *c)
{
    /* All TVP (see orient.h). Where the numbers come from, LSM6DSO DS12140 Rev 3 Table 2:
     * gyro RMS noise 75 mdps and accelerometer RMS noise 1.8 mg in low-power mode, zero-rate level
     * +-1 dps typ, +-0.010 dps/degC. */
    c->tau_s = 0.5f;
    c->acc_gate_g = 0.15f;
    c->steady_dps = 6.0f;          /* a hand holding the caliper on a part; not measured */
    c->steady_g = 0.06f;
    c->steady_ms = 300;
    c->rest_ms = 1000;
    c->rest_gyro_pp_dps = 1.0f;    /* 75 mdps RMS is ~0.4 dps peak-to-peak over 1 s: 2.5x margin */
    c->rest_acc_pp_g = 0.030f;     /* 1.8 mg RMS is ~10 mg peak-to-peak: 3x margin */
    c->bias_max_dps = 5.0f;        /* 5x the typical zero-rate level */
    c->bias_alpha = 0.25f;
    c->drift_unbiased_dps = 1.0f;  /* the typical zero-rate level, uncorrected */
    c->drift_biased_dps = 0.05f;   /* an estimate (a few degC of drift + the bias error), not measured */
}

void orient_init(orient_t *o, const orient_cfg_t *cfg)
{
    memset(o, 0, sizeof(*o));
    if (cfg) {
        o->cfg = *cfg;
    } else {
        orient_cfg_default(&o->cfg);
    }
    o->up = v3(0, 0, 1);
    o->yaw_unc_deg = 180.0f; /* nothing known until the first gravity reference */
}

void orient_zero_yaw(orient_t *o)
{
    o->yaw_deg = 0;
    o->yaw_unc_deg = 0;
}

/* The rest window: both sensors quiet (peak-to-peak) for rest_ms and the mean rate small enough to
 * be an offset. Uses the RAW gyro, so the bias is the window mean itself. A slow steady turn about
 * the vertical is indistinguishable from a bias (gravity does not change): bias_max_dps is the only
 * guard, which is why the yaw stays "relative, drifting" in the interface. */
static void rest_feed(orient_t *o, orient_vec_t g, orient_vec_t a, uint32_t dt_us)
{
    const orient_cfg_t *c = &o->cfg;
    /* A window only sees a jump from its second sample on. At rest the bias is known (it is the
     * mean of the windows so far), so a sample off it by more than the window's own limit ends the
     * rest at once, wherever in a window it falls. */
    if (o->at_rest && !v_within(v_sub(g, o->bias_dps), c->rest_gyro_pp_dps)) {
        o->at_rest = false;
        o->win_n = 0;
    }
    if (o->win_n == 0) {
        o->g_min = o->g_max = g;
        o->a_min = o->a_max = a;
        o->g_sum = v3(0, 0, 0);
        o->win_us = 0;
    } else {
        o->g_min = v_min(o->g_min, g);
        o->g_max = v_max(o->g_max, g);
        o->a_min = v_min(o->a_min, a);
        o->a_max = v_max(o->a_max, a);
        o->win_us += dt_us; /* n samples span n - 1 intervals */
    }
    o->g_sum = v_add(o->g_sum, g);
    o->win_n++;

    bool quiet = v_within(v_sub(o->g_max, o->g_min), c->rest_gyro_pp_dps) &&
                 v_within(v_sub(o->a_max, o->a_min), c->rest_acc_pp_g);
    if (!quiet) {
        o->at_rest = false; /* at once, and start looking for the next quiet second */
        o->win_n = 0;
        return;
    }
    if (o->win_us < c->rest_ms * 1000u) {
        return;
    }
    orient_vec_t mean = v_scale(o->g_sum, 1.0f / (float)o->win_n);
    bool rest = o->win_n >= REST_MIN_N && v_within(mean, c->bias_max_dps);
    if (rest) {
        o->bias_dps = o->bias_valid ? v_add(o->bias_dps, v_scale(v_sub(mean, o->bias_dps), c->bias_alpha)) : mean;
        o->bias_valid = true;
    }
    o->at_rest = rest;
    o->win_n = 0;
}

void orient_update(orient_t *o, orient_vec_t gyro_dps, orient_vec_t acc_g, uint32_t dt_us, bool gyro_clipped)
{
    const orient_cfg_t *c = &o->cfg;
    bool yaw_lost = gyro_clipped;
    if (dt_us > ORIENT_DT_MAX_US) {
        dt_us = ORIENT_DT_MAX_US;
        yaw_lost = true;
    }
    float dt = (float)dt_us * 1e-6f;
    o->n++;

    rest_feed(o, gyro_dps, acc_g, dt_us);

    orient_vec_t w = o->bias_valid ? v_sub(gyro_dps, o->bias_dps) : gyro_dps;
    float w_abs = v_abs(w);
    float a_abs = v_abs(acc_g);
    o->rate_dps = w;
    o->acc_abs_g = a_abs;
    bool acc_ok = a_abs > 0.5f && fabsf(a_abs - 1.0f) <= c->acc_gate_g;

    if (!o->valid) {
        if (acc_ok) {
            o->up = v_scale(acc_g, 1.0f / a_abs);
            o->valid = true;
            orient_zero_yaw(o);
        }
    } else {
        /* yaw: the turn about the vertical, before `up` moves */
        o->yaw_deg += v_dot(w, o->up) * dt;
        if (o->yaw_deg > 180.0f) {
            o->yaw_deg -= 360.0f;
        } else if (o->yaw_deg < -180.0f) {
            o->yaw_deg += 360.0f;
        }
        o->yaw_unc_deg += (o->bias_valid ? c->drift_biased_dps : c->drift_unbiased_dps) * dt;

        /* gyro: dv/dt = -w x v, i.e. `up` turns by -|w| dt about w (Rodrigues) */
        float th = w_abs * dt * DEG2RAD;
        if (th > 1e-9f) {
            orient_vec_t k = v_scale(w, 1.0f / w_abs);
            float s = sinf(th), co = cosf(th);
            orient_vec_t u = o->up;
            o->up = v_add(v_add(v_scale(u, co), v_scale(v_cross(k, u), -s)), v_scale(k, v_dot(k, u) * (1.0f - co)));
        }

        /* accelerometer: pull toward gravity while it is gravity */
        if (acc_ok) {
            orient_vec_t a_hat = v_scale(acc_g, 1.0f / a_abs);
            if (v_dot(o->up, a_hat) < 0.0f) {
                o->up = a_hat; /* more than 90 deg apart: tracking was lost (a gap, clipping); start over */
            } else {
                float alpha = dt / (c->tau_s + dt);
                o->up = v_add(o->up, v_scale(v_sub(a_hat, o->up), alpha));
            }
        }
        float n = v_abs(o->up);
        o->up = n > 1e-3f ? v_scale(o->up, 1.0f / n) : v3(0, 0, 1);
    }
    if (yaw_lost || o->yaw_unc_deg > 180.0f) {
        o->yaw_unc_deg = 180.0f;
    }

    /* steady: low rate and 1 g, continuously */
    if (o->valid && w_abs <= c->steady_dps && fabsf(a_abs - 1.0f) <= c->steady_g) {
        uint32_t lim = c->steady_ms * 1000u;
        o->steady_us = o->steady_us + dt_us > lim ? lim : o->steady_us + dt_us;
        o->steady = o->steady_us >= lim;
    } else {
        o->steady_us = 0;
        o->steady = false;
    }
}

static orient_face_t face_of(orient_vec_t up)
{
    if (up.z >= FACE_COS) return ORIENT_FACE_DISPLAY_UP;
    if (up.z <= -FACE_COS) return ORIENT_FACE_DISPLAY_DOWN;
    if (up.y >= FACE_COS) return ORIENT_FACE_TOP_UP;
    if (up.y <= -FACE_COS) return ORIENT_FACE_TOP_DOWN;
    if (up.x >= FACE_COS) return ORIENT_FACE_USB_UP;
    if (up.x <= -FACE_COS) return ORIENT_FACE_USB_DOWN;
    return ORIENT_FACE_TILTED;
}

const char *orient_face_name(orient_face_t f)
{
    switch (f) {
    case ORIENT_FACE_DISPLAY_UP:   return "display up";
    case ORIENT_FACE_DISPLAY_DOWN: return "display down";
    case ORIENT_FACE_TOP_UP:       return "top edge up";
    case ORIENT_FACE_TOP_DOWN:     return "top edge down";
    case ORIENT_FACE_USB_UP:       return "USB end up";
    case ORIENT_FACE_USB_DOWN:     return "USB end down";
    default:                       return "tilted";
    }
}

void orient_get(const orient_t *o, orient_out_t *out)
{
    memset(out, 0, sizeof(*out));
    out->valid = o->valid;
    out->up = o->up;
    /* pitch first: with the beam vertical (|up.x| -> 1) roll is the angle of a vanishing vector
     * and means nothing (gimbal lock); it stays finite, just noisy */
    out->pitch_deg = asinf(clampf(o->up.x, -1.0f, 1.0f)) * RAD2DEG;
    out->roll_deg = atan2f(o->up.y, o->up.z) * RAD2DEG;
    out->tilt_deg = acosf(clampf(o->up.z, -1.0f, 1.0f)) * RAD2DEG;
    out->yaw_deg = o->yaw_deg;
    out->yaw_unc_deg = o->yaw_unc_deg;
    out->rate_dps = o->rate_dps;
    out->rate_abs_dps = v_abs(o->rate_dps);
    out->acc_abs_g = o->acc_abs_g;
    out->steady = o->steady;
    out->at_rest = o->at_rest;
    out->bias_valid = o->bias_valid;
    out->bias_dps = o->bias_dps;
    out->face = o->valid ? face_of(o->up) : ORIENT_FACE_TILTED;
}

/* ---- display flip -------------------------------------------------------------------------- */

bool orient_flip_update(orient_flip_t *f, const orient_out_t *o, uint32_t dt_ms)
{
    bool want = f->flipped;
    if (o->valid) {
        if (o->up.y <= -ORIENT_FLIP_SIN) {
            want = true;
        } else if (o->up.y >= ORIENT_FLIP_SIN) {
            want = false;
        }
    }
    if (want == f->flipped) {
        f->pend_ms = 0;
        return false;
    }
    f->pend_ms += dt_ms;
    if (f->pend_ms < ORIENT_FLIP_HOLD_MS) {
        return false;
    }
    f->flipped = want;
    f->pend_ms = 0;
    return true;
}
