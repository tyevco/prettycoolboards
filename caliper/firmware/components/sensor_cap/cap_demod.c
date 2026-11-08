/* EXPERIMENTAL capacitive demodulation. Portable C. */
#include "cap_demod.h"

#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

cap_iq_t cap_demod_iq(const uint16_t *s, size_t n, float spc, size_t abs0)
{
    cap_iq_t r = {0.0f, 0.0f};
    if (n == 0 || spc <= 0.0f) {
        return r;
    }
    double mean = 0.0;
    for (size_t k = 0; k < n; k++) {
        mean += s[k];
    }
    mean /= (double)n;
    double w = 2.0 * M_PI / spc;
    double si = 0.0, sq = 0.0;
    for (size_t k = 0; k < n; k++) {
        double ph = w * (double)(abs0 + k);
        double x = (double)s[k] - mean;
        si += x * cos(ph);
        sq += x * sin(ph);
    }
    r.i = (float)(2.0 * si / (double)n);
    r.q = (float)(2.0 * sq / (double)n);
    return r;
}

float cap_iq_amplitude(cap_iq_t v)
{
    return sqrtf(v.i * v.i + v.q * v.q);
}

float cap_half_pitch_fraction(cap_iq_t fwd, cap_iq_t rev)
{
    double pf = atan2((double)fwd.q, (double)fwd.i);
    double pr = atan2((double)rev.q, (double)rev.i);
    double d = pr - pf; /* = 2 * theta_pos (mod 2 pi) */
    double frac = d / (2.0 * M_PI);
    frac -= floor(frac);
    if (frac >= 1.0) {
        frac = 0.0;
    }
    return (float)frac;
}

uint8_t cap_pattern(int32_t step)
{
    uint8_t m = 0;
    for (int n = 0; n < CAP_PHASES; n++) {
        if ((((n - step) % CAP_PHASES) + CAP_PHASES) % CAP_PHASES < CAP_PHASES / 2) {
            m |= (uint8_t)(1u << n);
        }
    }
    return m;
}

void cap_unwrap_init(cap_unwrap_t *u)
{
    u->init = false;
    u->turns = 0;
    u->last_frac = 0.0f;
}

int64_t cap_unwrap_update(cap_unwrap_t *u, float frac)
{
    if (!u->init) {
        u->init = true;
        u->turns = 0;
    } else {
        float d = frac - u->last_frac;
        if (d > 0.5f) {
            u->turns--;
        } else if (d < -0.5f) {
            u->turns++;
        }
    }
    u->last_frac = frac;
    return u->turns * CAP_HALF_PITCH_NM + (int64_t)llroundf(frac * (float)CAP_HALF_PITCH_NM);
}
