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

/*
 * Fine position (SPEC D1): the PCNT count (1953.125 nm) refined by the 12-bit SSI angle within
 * the pole (488.28125 nm). With the slip tracker locked, ssi = 4*dir*count + offset (mod 4096) up
 * to the sub-count part, so the residual r = wrap(ssi - expected(count)) is the SSI's correction
 * to the count and
 *     fine_lsb = 4 * count + dir * r       (SSI LSB, internal direction, 488.28125 nm each)
 * which is the SSI position unwrapped around the count: continuous across pole boundaries
 * (4095 -> 0) because the count supplies the pole and the wrap is taken on the difference.
 *
 * Consistency: |r| may legitimately reach the incremental outputs' 2-edge direction hysteresis
 * (datasheet §7.2, 8 LSB) plus up to one edge of lock phase (the offset is learned at an arbitrary
 * point inside a count) plus SSI jitter. Beyond AS5311_FINE_TOL_LSB the two disagree by more than
 * 2 edges (SPEC D1): the reading falls back to the count alone (fine_lsb = 4 * count) and is flagged.
 */
#define AS5311_FINE_TOL_LSB 12 /* 3 edges: 2 of hysteresis + 1 of lock phase; TVP */

typedef enum {
    AS5311_FINE_OK = 0,   /* SSI and count agree: fine_lsb is SSI-refined */
    AS5311_FINE_COARSE,   /* no usable SSI this sample (none read, bad frame, moving, not locked): count only */
    AS5311_FINE_MISMATCH, /* SSI and count disagree by more than the tolerance: count only, flag it */
} as5311_fine_status_t;

typedef struct {
    int64_t lsb;      /* position in SSI LSB, internal direction (4 per count) */
    int32_t residual; /* SSI - expected(count), wrapped, in LSB; 0 unless an SSI frame was used */
    as5311_fine_status_t status;
} as5311_fine_t;

/* ssi_ok: a valid frame taken while the count did not change (the comparison is meaningful). */
as5311_fine_t as5311_fine_combine(const as5311_slip_t *s, int64_t count, bool ssi_ok, uint16_t ssi_pos);

/*
 * Slip confirmation: a mismatch is only corrected (the count re-aligned to the SSI) after the same
 * correction was seen on AS5311_SLIP_CONFIRM consecutive still frames, so one bad (but parity-valid)
 * frame cannot shift the reading. Until then each mismatching reading is flagged and uses the count.
 */
#define AS5311_SLIP_CONFIRM 3

typedef struct {
    uint8_t n;  /* consecutive mismatching frames with the same correction */
    int32_t k;  /* that correction, in counts */
} as5311_mismatch_t;

void as5311_mismatch_init(as5311_mismatch_t *m);
/* Feed every combine result that used an SSI frame (status OK or MISMATCH; COARSE is ignored).
 * Returns the count correction to apply now (0 = none). */
int32_t as5311_mismatch_update(as5311_mismatch_t *m, const as5311_slip_t *s, const as5311_fine_t *f);

/*
 * PCNT wrap-race plausibility filter. The driver's count is hardware count + an accumulator that
 * its ISR bumps by the limit when the hardware counter hits a watch point and resets to 0. A read
 * that lands between the reset and the ISR (another core, or the ISR delayed) returns a value off
 * by the limit (here 30000 counts = 58.6 mm). A caliper can't move that far between two samples:
 * a step larger than max_step is held (the previous count is used); a jump that persists for
 * AS5311_JUMP_ACCEPT samples is accepted as real.
 *
 * Call as5311_jump_filter() once per sample. Re-reads inside one sample (waiting out the ISR) use
 * as5311_jump_plausible(), which changes nothing: the 2026-11-07 review found the driver calling
 * the filter on each re-read, so three reads 20 us apart already counted as "3 samples" and a race
 * that outlasted 40 us (the PCNT ISR held off on core 0, e.g. by a flash write) was accepted as a
 * 58.6 mm jump.
 */
#define AS5311_JUMP_ACCEPT 3

typedef struct {
    bool have;
    int64_t last;
    uint8_t rejects;
} as5311_jump_t;

void as5311_jump_init(as5311_jump_t *j);
/* Returns true if raw was accepted (*out = raw); false if it was held (*out = previous). */
bool as5311_jump_filter(as5311_jump_t *j, int64_t raw, int64_t max_step, int64_t *out);
/* Whether raw is within max_step of the last accepted count (always true before the first). */
bool as5311_jump_plausible(const as5311_jump_t *j, int64_t raw, int64_t max_step);

/*
 * Bring-up cross-check of the two outputs ("bu mag move", docs/bringup.md): the quadrature count
 * against the SSI position, unwrapped frame to frame on its own (no count involved), while the
 * slider is moved by hand over a few pole pairs. Feed every valid frame together with a count read
 * at the same sample, already multiplied by the firmware's SSI sign. A healthy sensor keeps
 *     ssi_unwrapped - 4 * (count - count0)
 * within the incremental hysteresis (2 edges = 8 LSB) plus one edge of read skew between the count
 * and the frame plus the lock tolerance: AS5311_XC_TOL_LSB. If instead ssi + 4 * count stays
 * there, the sign is wrong (SSI_SIGN in sensor_mag.c). The unwrap needs less than half a pole
 * pair (2048 LSB) between two frames: above AS5311_XC_MAX_STEP the run is refused as too fast.
 */
#define AS5311_XC_TOL_LSB  (AS5311_FINE_TOL_LSB + AS5311_LSB_PER_COUNT) /* 16 LSB = 7.8 um */
#define AS5311_XC_MAX_STEP 1536                       /* LSB per frame: 0.75 mm in one 10 ms sample */
#define AS5311_XC_MIN_SPAN AS5311_SSI_STEPS           /* at least one pole pair (2 mm) covered */

typedef enum {
    AS5311_XC_OK = 0,
    AS5311_XC_SHORT,    /* moved less than one pole pair: no verdict */
    AS5311_XC_FAST,     /* a step above AS5311_XC_MAX_STEP: the SSI unwrap is not trustworthy */
    AS5311_XC_INVERTED, /* the count runs against the SSI: flip SSI_SIGN */
    AS5311_XC_MISMATCH, /* neither sign fits: missed edges, noise, a bad A/B/SSI line */
} as5311_xc_result_t;

typedef struct {
    bool have;
    int64_t count0;
    uint16_t ssi_last;
    int64_t ssi_u;      /* SSI position unwrapped since the first frame, LSB */
    int64_t count_d;    /* count - count0 (counts) */
    int64_t dev_p_max;  /* max |ssi_u - 4 * count_d| */
    int64_t dev_m_max;  /* max |ssi_u + 4 * count_d| */
    int64_t min_u, max_u;
    int64_t travel;     /* sum of |step|, LSB */
    int32_t max_step;   /* largest |step| between two frames, LSB */
    uint32_t frames;
    uint32_t crossings; /* pole boundaries (4095 <-> 0) the SSI position crossed */
} as5311_xcheck_t;

void as5311_xcheck_init(as5311_xcheck_t *x);
void as5311_xcheck_feed(as5311_xcheck_t *x, int64_t count, uint16_t ssi_pos);
as5311_xc_result_t as5311_xcheck_result(const as5311_xcheck_t *x);
const char *as5311_xcheck_str(as5311_xc_result_t r);

#ifdef __cplusplus
}
#endif
