/*
 * capture: measurement-stabilising capture modes, portable C (no ESP-IDF includes).
 *
 *   SETTLE  the existing auto-hold, upgraded: once the reading has been still (span <= 10 um) for
 *           still_ms it freezes the MEDIAN of the last settle_n samples (32 = 320 ms at 100 Hz), not
 *           the first still sample. Released when the jaws move > rearm_nm away.
 *   SWEEP   min/max peak-hold while the jaws are on the part: arms when the jaws stop closing or
 *           opening (contact), tracks the persisted MIN and MAX of the samples inside +-gate_nm of
 *           the contact reference, freezes on lift-off (exit_ms outside the gate). The shown extreme
 *           is MIN or MAX: picked from the approach direction (closing = OD = MIN, opening = ID =
 *           MAX) or forced. Both are always kept, so the choice can change after the fact.
 *   SET     reserved for multi-point sets (contract value 3), not implemented.
 *
 * Why an extreme and not an average: jaw-to-part misalignment only ever adds to an OD reading
 * (w = D / cos t + l |tan t|: 7.8 mm jaws tilted 0.5 deg read 69 um high), so the true size is the
 * turning point of a rock, not its mean. caliper/docs/firmware.md "Capture modes" has the numbers.
 *
 * Everything is integer nm (shifted int64 sums, no float drift); the only floating point is the
 * final square root of the variance and the optional cusp line fit. Called once per sample (100 Hz)
 * from caliper_core with the zeroed magnetic value. Times are a free-running uint32 ms clock
 * (wrap-safe differences).
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ---- integer accumulator (shifted sums, exact) --------------------------------------------- */

/* Exact while the inputs stay within +-2 mm of the first sample (SWEEP's gate keeps them within
 * +-1 mm, a SETTLE window within 10 um bar two tolerated glitches): sd2 <= 4e12 * n then stays inside
 * int64 up to MEAS_ACC_N_MAX. Wilder inputs (a glitch at the other end of the int32 range) cannot
 * overflow: sd2 saturates, `sat` is set and the standard deviation reads INT32_MAX. */
#define MEAS_ACC_N_MAX 2000000u

typedef struct {
    uint32_t n;
    int32_t x0; /* first sample (the shift) */
    int64_t sd;  /* sum of (x - x0) */
    int64_t sd2; /* sum of (x - x0)^2, saturating at INT64_MAX */
    int32_t min, max;
    bool sat;    /* sd2 saturated */
} meas_acc_t;

void meas_acc_reset(meas_acc_t *a);
void meas_acc_add(meas_acc_t *a, int32_t nm);     /* ignored once n == MEAS_ACC_N_MAX */
int32_t meas_acc_mean_nm(const meas_acc_t *a);    /* x0 + the shifted mean rounded half away from zero; 0 if n == 0 */
int32_t meas_acc_sd_nm(const meas_acc_t *a);      /* sample sd (n - 1), rounded nm; 0 if n < 2; INT32_MAX if sat */
int32_t meas_acc_range_nm(const meas_acc_t *a);   /* max - min (saturated); 0 if n == 0 */

/* Sorts v[0..n) in place (insertion sort, n <= 64) and returns the median: the middle value, or
 * for even n the mean of the two middle values rounded half away from zero. 0 if n == 0. */
int32_t meas_median_i32(int32_t *v, size_t n);

/* ---- capture ------------------------------------------------------------------------------- */

typedef enum {
    MEAS_CAP_LIVE = 0,   /* no capture: the live value (HOLD freezes it by hand) */
    MEAS_CAP_SETTLE = 1, /* median of a still window, frozen with a beep */
    MEAS_CAP_SWEEP = 2,  /* min/max peak-hold while in contact */
    MEAS_CAP_SET = 3,    /* reserved (multi-point sets): not implemented, refused by set_mode */
    MEAS_CAP_MODES
} meas_cap_mode_t;

typedef enum { MEAS_SWEEP_AUTO = 0, MEAS_SWEEP_MIN = 1, MEAS_SWEEP_MAX = 2, MEAS_SWEEP_SELS } meas_sweep_sel_t;

/* What the display shows (meas_cap_result().state). Also the LIVE capture_state bits 0..2. */
typedef enum {
    MEAS_CAPST_IDLE = 0,  /* LIVE mode */
    MEAS_CAPST_WAIT = 1,  /* armed / waiting for contact or stillness: the live value is shown */
    MEAS_CAPST_RUN = 2,   /* SWEEP: in contact, the running extreme is shown. SETTLE: still, timing */
    MEAS_CAPST_DONE = 3,  /* a frozen result is shown */
    MEAS_CAPST_ABORT = 4, /* SWEEP: a sensor error dropped the capture (live value shown, "SENSOR") */
} meas_cap_state_t;

typedef enum {
    MEAS_CAPEV_NONE = 0,
    MEAS_CAPEV_CONTACT, /* SWEEP: a shown capture started */
    MEAS_CAPEV_DONE,    /* a new frozen result (beep) */
    MEAS_CAPEV_ABORT,   /* a shown capture was dropped by a sensor error */
    MEAS_CAPEV_RELEASE, /* SETTLE: the jaws moved away, the frozen result was released */
    MEAS_CAPEV_DISCARD, /* SWEEP: a shown capture was a pause, not a contact: the previous result is back */
} meas_cap_ev_t;

typedef struct {
    /* SETTLE */
    int32_t still_span_nm;    /* 10000: max - min of the still run (= +-5 um, the old auto-hold band) */
    uint16_t still_ms;        /* 800: still this long before it fires (500 is the bench candidate) */
    uint8_t settle_n;         /* 32: the median window, samples (<= MEAS_CAP_RING) */
    uint8_t settle_glitch;    /* 2: isolated single out-of-band samples tolerated per still run */
    /* SWEEP */
    int32_t contact_span_nm;  /* 20000 over contact_ms: the jaws stopped (< 200 um/s) */
    uint16_t contact_ms;      /* 100 */
    int32_t gate_nm;          /* 1000000: +-1 mm about the contact reference */
    uint16_t exit_ms;         /* 50: this long outside the gate = lift-off (see resume_ms) */
    uint16_t resume_ms;       /* 1000: an exit AGAINST the approach (the side a rock or a bore sweep
                               * goes) that stays within 2 x gate_nm is a lift-off only if the reading
                               * has not come back into the gate within this time: a wide sweep of a
                               * small bore drops the chord out of the gate and back */
    uint16_t min_run_ms;      /* 200: a shorter contact is a pause, discarded */
    uint8_t persist;          /* 2: an extreme must persist this many samples (1..MEAS_CAP_PERSIST_MAX) */
    uint16_t approach_ms;     /* 200: approach direction look-back before the still window */
    int32_t approach_nm;      /* 200000: a smaller look-back move is not an approach; also the least
                               * excursion that makes a run ending in its own approach direction a
                               * hover-then-contact rather than a pause in the air */
    int32_t leg_nm;           /* 500000: when the look-back is too short (the user was already rocking
                               * when the reading first stopped), the approach is the direction of the
                               * last move of at least this much (more than a sloppy rock) */
    int32_t depart_nm;        /* 20000: per sample (2 mm/s): faster departure samples are rolled back */
    uint8_t bad_max;          /* 5: more consecutive !ok samples abort a capture */
    uint32_t max_run_ms;      /* 600000: safety freeze */
    bool refine;              /* cusp refinement (line fit to both flanks). Off: bench first */
    int32_t refine_resid_nm;  /* 1500: largest fit residual for the refinement to be used */
    /* both */
    int32_t rearm_nm;         /* 500000: must move this far before the next capture */
    uint16_t sample_ms;       /* 10: the caller's sample period */
} meas_cap_cfg_t;

void meas_cap_cfg_default(meas_cap_cfg_t *c);

#define MEAS_CAP_RING        64 /* recent ok samples: contact window, approach look-back, SETTLE window */
#define MEAS_CAP_PEND        64 /* SWEEP: in-gate samples not yet committed (lift-off roll-back) */
#define MEAS_CAP_PERSIST_MAX 4
#define MEAS_CAP_FIT_SIDE    8  /* cusp refinement: samples kept on each side of the extreme */
#define MEAS_CAP_FIT_WIN     (2 * MEAS_CAP_FIT_SIDE - 1)

typedef struct {
    int32_t x;
    uint32_t t;
    uint8_t brk; /* a gap (out-of-gate or !ok sample) came before this one */
} meas_cap_smp_t;

typedef struct { /* the samples around one persisted extreme (cusp refinement) */
    int32_t x[MEAS_CAP_FIT_WIN];
    uint32_t t[MEAS_CAP_FIT_WIN];
    uint8_t n, need;
} meas_cap_fit_t;

typedef struct { /* the statistics of one SWEEP contact */
    meas_acc_t acc;
    bool have;            /* pmin/pmax valid */
    int32_t pmin, pmax;   /* persisted extremes */
    int32_t hist[MEAS_CAP_PERSIST_MAX];
    uint8_t hist_n;
    int32_t rx[MEAS_CAP_FIT_SIDE];
    uint32_t rt[MEAS_CAP_FIT_SIDE];
    uint8_t rn;
    meas_cap_fit_t fmin, fmax;
} meas_cap_run_t;

typedef struct { /* a frozen result */
    bool valid;
    int32_t min_nm, max_nm; /* SWEEP: persisted (or refined) extremes; SETTLE: window min / max */
    int32_t median_nm;      /* SETTLE */
    int32_t sd_nm;
    uint32_t n;
    int8_t approach;        /* SWEEP: -1 closing (OD), +1 opening (ID) */
} meas_cap_frozen_t;

typedef struct {
    meas_cap_cfg_t cfg;
    meas_cap_mode_t mode;
    meas_sweep_sel_t sel;
    /* recent ok samples */
    int32_t ring[MEAS_CAP_RING];
    uint8_t ring_n, ring_head;
    uint16_t ok_run;          /* consecutive ok samples in the ring */
    bool have_pos;
    int32_t last_nm;
    bool armed;
    int32_t arm_ref_nm;
    int32_t leg_anchor_nm;    /* the direction of the last move of >= leg_nm (zig-zag tracker) */
    int8_t leg_dir;           /* -1 closing, +1 opening, 0 none yet */
    /* SWEEP: the capture in progress */
    bool run, run_shown;
    int32_t ref_nm;
    int8_t approach;
    bool approach_known;
    int8_t last_approach;
    uint32_t run_samples;
    uint16_t out_n, bad_n;
    int8_t out_dir;
    bool susp;                /* out of the gate against the approach, waiting: lift-off or excursion */
    uint16_t susp_n;
    bool pend_brk;
    meas_cap_run_t st;        /* committed */
    meas_cap_smp_t pend[MEAS_CAP_PEND];
    uint8_t pend_n, pend_head;
    /* SWEEP: after a DONE, did the jaws come back (reverse against the lift-off direction)? */
    int8_t exit_dir;
    int32_t far_nm;
    bool reversed;
    bool aborted;
    /* SETTLE */
    uint16_t srun;
    int32_t smin, smax;
    uint8_t sglitch;
    bool sglitch_pend;
    /* the shown frozen result */
    meas_cap_frozen_t fz;
    /* button-press blanking */
    bool btn_down, blank_active;
    uint32_t blank_until;
} meas_capture_t;

typedef struct {
    meas_cap_state_t state;
    meas_cap_mode_t mode;
    int32_t value_nm;  /* the selected statistic: SWEEP the chosen extreme, SETTLE the median */
    int32_t other_nm;  /* SWEEP: the other extreme; else value_nm */
    int32_t min_nm, max_nm, range_nm, sd_nm;
    uint32_t n;
    int8_t which;      /* SWEEP: -1 MIN, +1 MAX; else 0 */
} meas_cap_result_t;

void meas_cap_init(meas_capture_t *c, const meas_cap_cfg_t *cfg, meas_cap_mode_t mode, meas_sweep_sel_t sel);
/* Changes mode and selection and resets the capture. Returns false (nothing changed) for SET or a
 * value out of range. */
bool meas_cap_set_mode(meas_capture_t *c, meas_cap_mode_t mode, meas_sweep_sel_t sel);
/* Changes only the SWEEP selection: a frozen or running result re-renders, nothing is lost. */
void meas_cap_set_sel(meas_capture_t *c, meas_sweep_sel_t sel);
/* Clears the result and re-arms (ZERO, HOLD on a frozen result): the next sample is the new
 * reference and the jaws must move rearm_nm from it before the next capture. */
void meas_cap_reset(meas_capture_t *c);
/* Freezes now (HOLD while a SWEEP is in contact, or while SETTLE is timing). A hidden SWEEP
 * candidate (a stop while an earlier result is on show) is dropped instead: the shown result stays. */
void meas_cap_freeze(meas_capture_t *c);

typedef enum {
    MEAS_CAP_HOLD_MANUAL = 0, /* nothing captured or running: the caller toggles a manual hold */
    MEAS_CAP_HOLD_FREEZE,     /* a running capture was frozen */
    MEAS_CAP_HOLD_REARM,      /* a frozen (or aborted) result was cleared and the capture re-armed */
} meas_cap_hold_t;
/* What HOLD short does in a capture mode; performs the freeze / re-arm itself. */
meas_cap_hold_t meas_cap_hold_press(meas_capture_t *c);

/* Button edges (debounced): while a button is down and for after_ms after it is released, samples
 * are ignored, and on the press the samples of the last before_ms are taken back out of a running
 * SWEEP: pressing the housing lifts the slider pads and moves the reading (calcs §3). */
void meas_cap_button(meas_capture_t *c, bool down, uint32_t t_ms, uint16_t before_ms, uint16_t after_ms);

meas_cap_ev_t meas_cap_update(meas_capture_t *c, int32_t zeroed_nm, bool ok, uint32_t t_ms);
/* The sensor applied a confirmed count-slip correction (the reading stepped): a running SWEEP is
 * aborted (MEAS_CAPEV_ABORT if it was shown), a SETTLE still window restarts. */
meas_cap_ev_t meas_cap_slip(meas_capture_t *c);
/* The shown result; valid in every state (the running values during RUN). */
void meas_cap_result(const meas_capture_t *c, meas_cap_result_t *out);

#ifdef __cplusplus
}
#endif
