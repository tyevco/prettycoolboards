/*
 * AS5311 protocol helpers: the 18-bit SSI frame, the field-strength status, and the logic that
 * ties the absolute 12-bit in-pole position to the PCNT quadrature count (slip detection and
 * recovery after the sensor was power-gated). Portable C.
 *
 * SSI frame, MSB first (AS5311 datasheet rev 1.12 §7.3, Figure 6):
 *   D11..D0 (12-bit position in the 2 mm pole pair), OCF, COF, LIN, MagINC, MagDEC, PAR
 *   PAR = even parity over bits 1..17, i.e. the whole 18-bit frame has even parity.
 *   CLK must be HIGH at the falling edge of CSn: with CLK low the first 12 bits are the field
 *   magnitude instead of the position.
 *
 * Resolutions (datasheet Table 8 and §7.1): the SSI position has 4096 steps per 2.0 mm pole pair
 * (488.28125 nm), but the incremental A/B outputs give only 256 pulses per channel = 1024 edges
 * per pole pair, so the 4x-decoded PCNT count is 1953.125 nm. One count = 4 SSI LSB.
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define AS5311_FRAME_BITS      18
#define AS5311_SSI_STEPS       4096 /* SSI LSB per 2.0 mm pole pair */
#define AS5311_COUNTS_PER_POLE 1024 /* quadrature edges (PCNT 4x counts) per pole pair */
#define AS5311_LSB_PER_COUNT   (AS5311_SSI_STEPS / AS5311_COUNTS_PER_POLE) /* 4 */

typedef struct {
    uint16_t pos; /* 0..4095 */
    bool ocf;     /* offset compensation finished: must be 1 */
    bool cof;     /* CORDIC overflow: must be 0 */
    bool lin;     /* linearity alarm */
    bool mag_inc;
    bool mag_dec;
    bool parity_ok;
} as5311_frame_t;

typedef enum {
    AS5311_FIELD_OK = 0,
    AS5311_FIELD_MARGINAL, /* MagINC = MagDEC = 1, LIN = 0: YELLOW range (~3.4..54.5 mT), slightly reduced accuracy */
    AS5311_FIELD_BAD,      /* MagINC = MagDEC = LIN = 1: RED range, not recommended */
} as5311_field_t;

void as5311_decode(uint32_t raw18, as5311_frame_t *f);
uint32_t as5311_encode(const as5311_frame_t *f); /* for tests; computes the parity bit */
bool as5311_frame_valid(const as5311_frame_t *f); /* parity, OCF = 1, COF = 0 */
as5311_field_t as5311_field(const as5311_frame_t *f);

/* (a - b) in SSI LSB, wrapped into [-2048, 2047] */
int32_t as5311_wrap_diff(uint16_t a, uint16_t b);

/* Count -> in-pole position in SSI LSB (0, 4, 8 ... 4092), with the direction sign (+1/-1)
 * applied to the count. */
uint16_t as5311_count_phase(int64_t count, int dir);

/* SSI LSB -> counts, rounded to nearest (halves away from zero). */
int32_t as5311_lsb_to_counts(int32_t lsb);

/*
 * Slip tracker: at lock, records the offset between the SSI position and the quadrature
 * count's phase. Afterwards the residual should stay within the incremental hysteresis
 * (2 counts = 8 LSB, datasheet §7.2) plus the SSI jitter; a larger residual means the counter
 * missed edges (too fast, noise) or the SSI read was bad.
 */
typedef struct {
    bool locked;
    int32_t offset; /* ssi - phase(count), wrapped, in SSI LSB */
    int dir;
} as5311_slip_t;

void as5311_slip_init(as5311_slip_t *s, int dir);
void as5311_slip_lock(as5311_slip_t *s, int64_t count, uint16_t ssi_pos);
/* Residual in SSI LSB (ssi - expected), wrapped to [-2048, 2047]. 0 until locked. */
int32_t as5311_slip_residual(const as5311_slip_t *s, int64_t count, uint16_t ssi_pos);
/* The count correction (to add to the count) for a residual, in counts. */
int32_t as5311_slip_correction(const as5311_slip_t *s, int32_t residual_lsb);

/*
 * After the sensor was powered off (deep sleep), the quadrature count is lost. If the slider
 * moved less than +-1 mm (half a pole pair) while off, the count is recovered (to the nearest
 * count) from the stored count and the stored/now SSI positions.
 */
int64_t as5311_recover_count(int64_t stored_count, uint16_t ssi_stored, uint16_t ssi_now, int dir);

#ifdef __cplusplus
}
#endif
