/*
 * sensor_cap: the EXPERIMENTAL capacitive scale (SPEC.md §4.2).
 *
 * Isolated from sensor_mag on purpose: it has its own task, its own GPIOs and the ADC; any
 * failure here only makes LIVE.cap_nm read INT32_MIN (CAP_VALID clear). Nothing in the
 * magnetic path, the log or the tolerance logic depends on it.
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    bool valid;
    int64_t pos_nm;   /* unwrapped, relative to the first valid burst (zeroed by caliper_core) */
    float frac;       /* position within the half pitch, 0..1 */
    float amp_fwd;    /* demodulated amplitude, ADC LSB */
    float amp_rev;
    uint32_t bursts;
} cap_reading_t;

/* Call from a task on core 0 (the ADC DMA interrupt is allocated on the calling core and
 * must not sit on the core whose interrupts the drive loop masks). */
esp_err_t sensor_cap_init(void);
/* One forward + reverse burst (about 7 ms with interrupts masked on the calling core).
 * Call from a task pinned to core 1. */
esp_err_t sensor_cap_measure(cap_reading_t *out);
void sensor_cap_idle(void); /* all phases low */
void sensor_cap_deinit(void);

#ifdef __cplusplus
}
#endif
