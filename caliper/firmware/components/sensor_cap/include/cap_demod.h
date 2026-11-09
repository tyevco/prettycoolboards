/*
 * EXPERIMENTAL capacitive-scale demodulator. Portable C (float).
 *
 * The 8 transmitter phases are driven with a rotating square pattern; the reflector couples a
 * signal to the receive electrode whose phase (relative to the drive) is the slider position
 * within one 5.08 mm pitch. The ADC (continuous mode) and the drive loop are not phase-locked
 * at start, so an unknown delay adds a constant phase. To cancel it, one burst runs the pattern
 * forward and then in reverse: the position phase changes sign, the delay phase does not, so
 *     2 * theta_pos = phase_reverse - phase_forward
 * which gives the position modulo half a pitch (2.54 mm). The unwrapper tracks whole half-pitches.
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define CAP_PITCH_NM      5080000L
#define CAP_HALF_PITCH_NM 2540000L
#define CAP_PHASES        8
#define CAP_MIN_AMP_LSB   8.0f /* a burst below this amplitude (ADC LSB) has no usable coupling */

typedef struct {
    float i;
    float q;
} cap_iq_t;

/* Single-bin DFT of n samples at `samples_per_cycle`, referenced to the absolute sample index
 * (abs_index0 is the index of s[0] in the capture), with the mean removed. */
cap_iq_t cap_demod_iq(const uint16_t *s, size_t n, float samples_per_cycle, size_t abs_index0);

float cap_iq_amplitude(cap_iq_t v);

/* Position within the half pitch, in [0, 1), from the forward and reverse I/Q. */
float cap_half_pitch_fraction(cap_iq_t fwd, cap_iq_t rev);

/* Drive pattern for a step: bit n set = phase n high. Phase n is high while
 * ((n - step) mod 8) < 4, i.e. half the phases high, rotating by one phase per step. */
uint8_t cap_pattern(int32_t step);

typedef struct {
    bool init;
    int64_t turns; /* whole half-pitches */
    float last_frac;
} cap_unwrap_t;

void cap_unwrap_init(cap_unwrap_t *u);
/* Unwraps a new fraction (assumes the slider moved < half of a half-pitch between calls).
 * Returns the position in nm relative to the first sample's half-pitch. */
int64_t cap_unwrap_update(cap_unwrap_t *u, float frac);

#ifdef __cplusplus
}
#endif
