/* orient: roll / pitch from gravity, relative yaw from the gyro, gyro bias at rest, and a magnetic
 * heading that holds the yaw once the gyro has drifted further than the compass is wrong. Portable C. */
#include "orient.h"

#include <math.h>
#include <string.h>

#define RAD2DEG  57.29577951f
#define DEG2RAD  0.01745329252f
#define FACE_COS 0.8f /* an axis within acos(0.8) = 37 deg of vertical names the face */
#define REST_MIN_N 8u /* a rest window needs at least this many samples to mean anything */
#define CMP_FIELD_COS 0.985f   /* a field within acos(0.985) = 10 deg of vertical points nowhere */
#define CMP_FRESH_US  300000u  /* a heading older than this is carried, not measured */
#define CMP_DT_MAX_US 1000000u /* a longer gap between compass samples counts as this */

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

/* an angle in degrees, into -180..180 */
static float wrap180(float a)
{
    while (a > 180.0f) {
        a -= 360.0f;
    }
    while (a < -180.0f) {
        a += 360.0f;
    }
    return a;
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
    /* The compass: guesses, every one (TVP). IIS2MDC DocID030986 Rev 1: 9 mG RMS noise in low-power
     * mode, 6 mG with the low-pass filter or offset cancellation, which is about 2 deg on a 20 uT
     * horizontal field. What the steel beam and the battery do to the field is not known at all. */
    c->cmp_abs_min_ut = ORIENT_COMPASS_MIN_UT;
    c->cmp_abs_max_ut = ORIENT_COMPASS_MAX_UT;
    c->cmp_ref_tol = 0.25f;
    c->cmp_dip_tol_deg = 10.0f;
    c->cmp_hold_ms = 1000;
    c->cmp_dip_tau_s = 20.0f;
    c->cmp_vert_cos = 0.9f;        /* the beam within 26 deg of vertical */
    c->cmp_rate_max_dps = 60.0f;   /* 6 deg per 10 Hz sample */
    c->cmp_tau_s = 3.0f;
    c->cmp_unc_deg = 15.0f;        /* soft iron is not calibrated out; not measured */
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
    /* the compass holds the yaw against the heading of this moment, if one is known */
    o->yaw_ref = o->hdg_lock && o->hdg_unc_deg < 180.0f;
    o->yaw_ref_deg = o->hdg_deg;
    o->yaw_floor_deg = o->hdg_unc_deg + o->cfg.cmp_unc_deg;
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
        if (o->hdg_lock) {
            /* the heading is clockwise, so it turns the other way; the gyro carries it no better */
            o->hdg_deg = wrap180(o->hdg_deg - v_dot(w, o->up) * dt);
            o->hdg_unc_deg += (o->bias_valid ? c->drift_biased_dps : c->drift_unbiased_dps) * dt;
        }

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
    if (yaw_lost || o->hdg_unc_deg > 180.0f) {
        o->hdg_unc_deg = 180.0f;
    }
    if (o->cmp_age_us <= CMP_FRESH_US) {
        o->cmp_age_us += dt_us;
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
    out->heading_unc_deg = o->hdg_lock ? o->hdg_unc_deg : 180.0f;
    out->heading_valid = o->cmp_ok && o->cmp_age_us <= CMP_FRESH_US && out->heading_unc_deg < 180.0f;
    float h = o->hdg_deg < 0.0f ? o->hdg_deg + 360.0f : o->hdg_deg;
    out->heading_deg = h < 360.0f ? h : 0.0f;
    out->field_disturbed = o->cmp_disturbed;
    out->field_abs_ut = o->field_abs_ut;
    out->dip_deg = o->dip_deg;
}

/* ---- compass ------------------------------------------------------------------------------- */

void orient_compass_span_feed(orient_compass_span_t *s, orient_vec_t raw_ut)
{
    s->min = s->have ? v_min(s->min, raw_ut) : raw_ut;
    s->max = s->have ? v_max(s->max, raw_ut) : raw_ut;
    s->have = true;
    s->n++;
}

bool orient_compass_span_cal(const orient_compass_span_t *s, orient_compass_cal_t *cal)
{
    orient_vec_t half = v_scale(v_sub(s->max, s->min), 0.5f);
    float ref = (half.x + half.y + half.z) / 3.0f;
    cal->off_ut = v_scale(v_add(s->max, s->min), 0.5f);
    cal->ref_ut = ref;
    return s->have && ref >= ORIENT_COMPASS_MIN_UT && ref <= ORIENT_COMPASS_MAX_UT &&
           v_within(v_sub(half, v3(ref, ref, ref)), ORIENT_COMPASS_SPAN_TOL * ref);
}

void orient_compass_set_cal(orient_t *o, const orient_compass_cal_t *cal)
{
    memset(&o->cmp_cal, 0, sizeof(o->cmp_cal));
    if (cal && cal->ref_ut > 0.0f) {
        o->cmp_cal = *cal;
    }
    o->field_abs_ut = o->dip_deg = o->dip_ref_deg = 0;
    o->dip_valid = o->cmp_disturbed = o->cmp_ok = false;
    o->cmp_ok_us = 0;
    o->hdg_lock = o->yaw_ref = false;
}

void orient_compass_update(orient_t *o, orient_vec_t raw_ut, uint32_t dt_us)
{
    const orient_cfg_t *c = &o->cfg;
    float ref = o->cmp_cal.ref_ut;
    if (!(ref > 0.0f) || !o->valid) {
        return;
    }
    if (dt_us > CMP_DT_MAX_US) {
        dt_us = CMP_DT_MAX_US;
    }
    float dt = (float)dt_us * 1e-6f;
    o->cmp_age_us = 0;
    o->cmp_ok = false;

    orient_vec_t b = v_sub(raw_ut, o->cmp_cal.off_ut);
    float b_abs = v_abs(b), b_up = 0;
    o->field_abs_ut = b_abs;

    /* plausible: the size of the Earth's field, the size it was calibrated at, the dip it has had */
    bool ok = b_abs >= c->cmp_abs_min_ut && b_abs <= c->cmp_abs_max_ut && fabsf(b_abs - ref) <= c->cmp_ref_tol * ref;
    if (ok) {
        b_up = v_dot(b, o->up);
        o->dip_deg = -asinf(clampf(b_up / b_abs, -1.0f, 1.0f)) * RAD2DEG;
        if (!o->dip_valid) {
            o->dip_ref_deg = o->dip_deg;
            o->dip_valid = true;
        }
        ok = fabsf(o->dip_deg - o->dip_ref_deg) <= c->cmp_dip_tol_deg;
        o->dip_ref_deg += (o->dip_deg - o->dip_ref_deg) * dt / (c->cmp_dip_tau_s + dt);
    }
    if (!ok) {
        o->cmp_disturbed = true;
        o->cmp_ok_us = 0;
        return;
    }
    uint32_t lim = c->cmp_hold_ms * 1000u;
    o->cmp_ok_us = o->cmp_ok_us + dt_us > lim ? lim : o->cmp_ok_us + dt_us;
    if (o->cmp_ok_us < lim) {
        return;
    }
    o->cmp_disturbed = false;

    /* With the beam or the field near vertical the heading is the angle of a vanishing vector, and
     * in a fast turn the sample is behind: not disturbed, just no heading. */
    if (fabsf(o->up.x) > c->cmp_vert_cos || fabsf(b_up) > CMP_FIELD_COS * b_abs ||
        v_abs(o->rate_dps) > c->cmp_rate_max_dps) {
        return;
    }
    /* north = the horizontal part of b, east = north x up; where +x lies between the two */
    float h = atan2f(b.y * o->up.z - b.z * o->up.y, b.x - b_up * o->up.x) * RAD2DEG;
    float a = dt / (c->cmp_tau_s + dt);
    o->cmp_ok = true;

    if (!o->hdg_lock || o->hdg_unc_deg >= 180.0f) {
        o->hdg_deg = h; /* nothing carried to weigh it against */
        o->hdg_unc_deg = c->cmp_unc_deg;
        o->hdg_lock = true;
    } else {
        o->hdg_deg = wrap180(o->hdg_deg + a * wrap180(h - o->hdg_deg));
        o->hdg_unc_deg += a * (c->cmp_unc_deg - o->hdg_unc_deg);
    }

    /* The yaw. heading + yaw = the heading at yaw 0, and the two headings in that are each good to
     * cmp_unc_deg: their sum is the floor the compass can hold yaw_unc_deg at. Below the floor the
     * yaw is the gyro's alone. */
    if (!o->yaw_ref) {
        if (o->yaw_unc_deg < 180.0f) {
            /* no heading was known when the yaw was zeroed: this one, turned back by the yaw, is it */
            o->yaw_ref_deg = wrap180(h + o->yaw_deg);
            o->yaw_floor_deg = o->yaw_unc_deg + 2.0f * c->cmp_unc_deg;
            o->yaw_ref = true;
        }
        return;
    }
    if (o->yaw_unc_deg > o->yaw_floor_deg) {
        float ya = o->yaw_unc_deg >= 180.0f ? 1.0f : a; /* a lost yaw: there is nothing to blend with */
        o->yaw_deg = wrap180(o->yaw_deg + ya * wrap180(o->yaw_ref_deg - h - o->yaw_deg));
        o->yaw_unc_deg += ya * (o->yaw_floor_deg - o->yaw_unc_deg);
    }
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
