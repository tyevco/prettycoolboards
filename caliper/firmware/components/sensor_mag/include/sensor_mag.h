/*
 * sensor_mag: the AS5311 magnetic linear encoder (primary sensor).
 *   - quadrature A/B -> PCNT, 4x decoding, overflow accumulation (1024 counts per 2 mm pole pair,
 *     1953.125 nm per count; the SSI position is 4096 steps per pole pair)
 *   - SSI (CSn/CLK/DO, 18 bits) for the absolute in-pole position and the field status
 *   - index pulses (one per 2 mm) as a second slip check
 *   - power gating of +3V3_SNS through SNS_PWR_EN
 *   - count recovery after deep sleep from the in-pole position (valid if moved < 1 mm)
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "as5311_proto.h"
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    int64_t count;        /* absolute quadrature count (sensor origin) */
    int64_t raw_nm;       /* count converted to nm */
    bool ssi_valid;       /* this reading included a good SSI frame */
    uint16_t ssi_pos;
    as5311_field_t field;
    int32_t slip;         /* SSI vs count residual in SSI LSB (4 per count; 0 if no SSI this time) */
    uint32_t slips;       /* corrections applied since power-up */
    bool ok;              /* usable: powered, field not BAD, recent SSI frames valid */
} mag_reading_t;

esp_err_t sensor_mag_init(void);           /* powers the sensor and starts counting */
esp_err_t sensor_mag_power(bool on);
/* do_ssi: also read the SSI frame (about 40 us) and run the slip check. */
esp_err_t sensor_mag_read(mag_reading_t *out, bool do_ssi);
/* Saves the count and in-pole position to RTC memory; call right before deep sleep. */
void sensor_mag_prepare_sleep(void);

#ifdef __cplusplus
}
#endif
