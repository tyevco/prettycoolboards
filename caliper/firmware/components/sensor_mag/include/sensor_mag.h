/*
 * sensor_mag: the AS5311 magnetic linear encoder (primary sensor).
 *   - quadrature A/B -> PCNT, 4x decoding, overflow accumulation (1024 counts per 2 mm pole pair,
 *     1953.125 nm per count), with a plausibility filter against the accumulator wrap race
 *   - SSI (CSn/CLK/DO, 18 bits) for the absolute in-pole position (4096 steps per pole pair) and the
 *     field status, read on every sample: the count is refined by the SSI to 488.28125 nm (SPEC D1)
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
    int64_t count;        /* absolute quadrature count (sensor origin), user direction */
    int64_t raw_nm;       /* position in nm, user direction: SSI-refined when fine == OK, else count only */
    as5311_fine_status_t fine;
    bool ssi_valid;       /* this reading included a good SSI frame */
    uint16_t ssi_pos;
    as5311_field_t field;
    int32_t slip;         /* SSI vs count residual in SSI LSB (4 per count; 0 if no SSI this time) */
    uint32_t slips;       /* confirmed corrections applied since power-up */
    uint32_t jumps;       /* PCNT reads rejected by the wrap-race filter since power-up */
    bool ok;              /* usable: powered, field not BAD, recent SSI frames valid, SSI and count agree */
} mag_reading_t;

/* Where the count origin came from at sensor_mag_init(). */
typedef enum {
    MAG_ORIGIN_NONE = 0,  /* no valid SSI frame at init: counting from an arbitrary origin, SENSOR_ERR */
    MAG_ORIGIN_COLD,      /* power-on or reset: a new origin (any zero from before is meaningless) */
    MAG_ORIGIN_LOST,      /* woke from deep sleep but the count could not be recovered: a new origin */
    MAG_ORIGIN_RECOVERED, /* woke from deep sleep and recovered the count from the saved pole position */
} mag_origin_t;

esp_err_t sensor_mag_init(void);           /* powers the sensor and starts counting */
mag_origin_t sensor_mag_origin(void);      /* valid after sensor_mag_init() */
esp_err_t sensor_mag_power(bool on);
/* do_ssi: also read the SSI frame (about 40 us), refine the count and run the slip check. */
esp_err_t sensor_mag_read(mag_reading_t *out, bool do_ssi);
/* Saves the count, the in-pole position and the SSI/count offset to RTC memory; call right
 * before deep sleep. */
void sensor_mag_prepare_sleep(void);

/* ---- bring-up diagnostics (the CLI "bu mag" commands) ---- */
typedef struct {
    uint32_t samples;    /* sensor_mag_read() calls */
    uint32_t frames_ok;  /* valid SSI frames (parity, OCF = 1, COF = 0) */
    uint32_t frames_bad;
    uint32_t last_raw;   /* the last SSI frame as read, 18 bits */
    int64_t pcnt;        /* the filtered PCNT count, no origin, no slip correction */
    uint32_t idx_pulses; /* MAG_IDX rising edges since power-up */
    uint32_t slips, jumps;
    bool powered;
    as5311_xcheck_t xc;  /* the count vs SSI cross-check while armed */
} mag_diag_t;
void sensor_mag_diag(mag_diag_t *out);
void sensor_mag_xcheck_start(void); /* clears and arms the cross-check (fed by the sensor task) */
void sensor_mag_xcheck_stop(void);

#ifdef __cplusplus
}
#endif
