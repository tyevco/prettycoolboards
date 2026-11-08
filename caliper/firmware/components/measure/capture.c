/* capture: SETTLE (median of a still window) and SWEEP (min/max peak-hold in contact). Portable C. */
#include "capture.h"

#include <math.h>
#include <stdint.h>
#include <string.h>

#include "measure.h"

/* ---- accumulator --------------------------------------------------------------------------- */

void meas_acc_reset(meas_acc_t *a)
{
    memset(a, 0, sizeof(*a));
}

void meas_acc_add(meas_acc_t *a, int32_t nm)
{
    if (a->n >= MEAS_ACC_N_MAX) {
        return;
    }
    if (a->n == 0) {
        a->x0 = nm;
        a->min = nm;
        a->max = nm;
    } else {
        if (nm < a->min) a->min = nm;
        if (nm > a->max) a->max = nm;
    }
    int64_t d = (int64_t)nm - a->x0;
    a->n++;
    a->sd += d; /* |d| < 2^32, n <= 2e6: < 2^53 */
    /* |d| <= 2^32 - 1, so d^2 fits uint64; saturate rather than overflow the int64 sum */
    uint64_t ad = (uint64_t)(d < 0 ? -d : d), dd = ad * ad;
    if (a->sat || dd > (uint64_t)(INT64_MAX - a->sd2)) {
        a->sat = true;
        a->sd2 = INT64_MAX;
    } else {
        a->sd2 += (int64_t)dd;
    }
}

int32_t meas_acc_mean_nm(const meas_acc_t *a)
{
    if (a->n == 0) {
        return 0;
    }
    return meas_sat_i32((int64_t)a->x0 + meas_div_round(a->sd, (int64_t)a->n));
}

int32_t meas_acc_sd_nm(const meas_acc_t *a)
{
    if (a->n < 2) {
        return 0;
    }
    if (a->sat) {
        return INT32_MAX;
    }
    /* (n - 1) var = sd2 - sd^2 / n, with sd = q n + r so nothing overflows (q^2 n <= sd^2 / n <= sd2):
     * sd^2 / n = q^2 n + 2 q r + r^2 / n. Exact but for the fraction of r^2 / n (< 1 nm^2). */
    int64_t n = (int64_t)a->n;
    int64_t q = a->sd / n, r = a->sd % n;
    int64_t num = a->sd2 - q * q * n - 2 * q * r - (r * r) / n;
    if (num <= 0) {
        return 0;
    }
    double sd = sqrt((double)num / (double)(n - 1));
    return meas_sat_i32((int64_t)(sd + 0.5));
}

int32_t meas_acc_range_nm(const meas_acc_t *a)
{
    return a->n ? meas_sat_i32((int64_t)a->max - a->min) : 0;
}

int32_t meas_median_i32(int32_t *v, size_t n)
{
    if (n == 0) {
        return 0;
    }
    for (size_t i = 1; i < n; i++) {
        int32_t k = v[i];
        size_t j = i;
        while (j > 0 && v[j - 1] > k) {
            v[j] = v[j - 1];
            j--;
        }
        v[j] = k;
    }
    if (n & 1u) {
        return v[n / 2];
    }
    return meas_sat_i32(meas_div_round((int64_t)v[n / 2 - 1] + v[n / 2], 2));
}

/* ---- configuration ------------------------------------------------------------------------- */

void meas_cap_cfg_default(meas_cap_cfg_t *c)
{
    memset(c, 0, sizeof(*c));
    c->still_span_nm = 10000;
    c->still_ms = 800;
    c->settle_n = 32;
    c->settle_glitch = 2;
    c->contact_span_nm = 20000;
    c->contact_ms = 100;
    c->gate_nm = 1000000;
    c->exit_ms = 50;
    c->resume_ms = 1000;
    c->min_run_ms = 200;
    c->persist = 2;
    c->approach_ms = 200;
    c->approach_nm = 200000;
    c->leg_nm = 500000;
    c->depart_nm = 20000;
    c->bad_max = 5;
    c->max_run_ms = 600000;
    c->refine = false;
    c->refine_resid_nm = 1500;
    c->rearm_nm = 500000;
    c->sample_ms = 10;
}

static uint32_t ms_to_n(const meas_cap_cfg_t *c, uint32_t ms)
{
    uint32_t p = c->sample_ms ? c->sample_ms : 10;
    uint32_t n = (ms + p - 1) / p;
    return n ? n : 1;
}

static int64_t absd(int64_t v)
{
    return v < 0 ? -v : v;
}

static int8_t sgn(int64_t v)
{
    return (int8_t)(v < 0 ? -1 : 1);
}

/* ---- the recent-sample ring ---------------------------------------------------------------- */

static void ring_push(meas_capture_t *c, int32_t x)
{
    c->ring[c->ring_head] = x;
    c->ring_head = (uint8_t)((c->ring_head + 1u) % MEAS_CAP_RING);
    if (c->ring_n < MEAS_CAP_RING) {
        c->ring_n++;
    }
}

/* k = 0 is the newest sample */
static int32_t ring_back(const meas_capture_t *c, unsigned k)
{
    return c->ring[(c->ring_head + MEAS_CAP_RING - 1u - k) % MEAS_CAP_RING];
}

/* ---- SWEEP: running statistics ------------------------------------------------------------- */

static void run_clear(meas_cap_run_t *s)
{
    memset(s, 0, sizeof(*s));
    meas_acc_reset(&s->acc);
}

static void fit_snapshot(meas_cap_fit_t *f, const meas_cap_run_t *s)
{
    f->n = 0;
    for (uint8_t i = 0; i < s->rn; i++) {
        f->x[f->n] = s->rx[i];
        f->t[f->n] = s->rt[i];
        f->n++;
    }
    f->need = MEAS_CAP_FIT_SIDE - 1;
}

static void fit_append(meas_cap_fit_t *f, int32_t x, uint32_t t)
{
    if (f->need && f->n < MEAS_CAP_FIT_WIN) {
        f->x[f->n] = x;
        f->t[f->n] = t;
        f->n++;
        f->need--;
    }
}

static void run_push(meas_cap_run_t *s, const meas_cap_smp_t *p, uint8_t persist)
{
    meas_acc_add(&s->acc, p->x);
    fit_append(&s->fmin, p->x, p->t);
    fit_append(&s->fmax, p->x, p->t);
    /* recent samples, oldest first */
    if (s->rn == MEAS_CAP_FIT_SIDE) {
        memmove(s->rx, s->rx + 1, (MEAS_CAP_FIT_SIDE - 1) * sizeof(s->rx[0]));
        memmove(s->rt, s->rt + 1, (MEAS_CAP_FIT_SIDE - 1) * sizeof(s->rt[0]));
        s->rn--;
    }
    s->rx[s->rn] = p->x;
    s->rt[s->rn] = p->t;
    s->rn++;
    /* persistence: MIN = min over i of max(x[i-P+1..i]), MAX = max over i of min(...) */
    if (p->brk) {
        s->hist_n = 0;
    }
    if (s->hist_n == persist) {
        memmove(s->hist, s->hist + 1, (size_t)(persist - 1) * sizeof(s->hist[0]));
        s->hist_n--;
    }
    s->hist[s->hist_n++] = p->x;
    if (s->hist_n < persist) {
        return;
    }
    int32_t hi = s->hist[0], lo = s->hist[0];
    for (uint8_t i = 1; i < s->hist_n; i++) {
        if (s->hist[i] > hi) hi = s->hist[i];
        if (s->hist[i] < lo) lo = s->hist[i];
    }
    if (!s->have || hi < s->pmin) {
        s->pmin = hi;
        fit_snapshot(&s->fmin, s);
    }
    if (!s->have || lo > s->pmax) {
        s->pmax = lo;
        fit_snapshot(&s->fmax, s);
    }
    s->have = true;
}

/* Least-squares line y = a + b t over the points; returns the largest |residual|. */
static double line_fit(const double *t, const double *y, int n, double *a, double *b)
{
    double st = 0, sy = 0, stt = 0, sty = 0;
    for (int i = 0; i < n; i++) {
        st += t[i];
        sy += y[i];
        stt += t[i] * t[i];
        sty += t[i] * y[i];
    }
    double den = n * stt - st * st;
    if (n < 2 || den == 0.0) {
        *a = 0;
        *b = 0;
        return 1e30;
    }
    *b = (n * sty - st * sy) / den;
    *a = (sy - *b * st) / n;
    double worst = 0;
    for (int i = 0; i < n; i++) {
        double r = fabs(y[i] - (*a + *b * t[i]));
        if (r > worst) worst = r;
    }
    return worst;
}

/*
 * Cusp refinement: an ideal V (flat jaws rocked across a cylinder) is sampled on both flanks; a
 * line through each flank meets at the true turning point, which the samples straddle. s = +1
 * refines a minimum, -1 a maximum (values negated). Returns false when the samples do not look
 * like a V (too few points, a residual over refine_resid_nm: a rounded, self-seating bottom or a
 * glitch), and the persisted extreme is used unchanged. The result is clamped to
 * [raw extreme - half a sample at the fitted slope, persisted extreme].
 */
static bool refine_extreme(const meas_cap_fit_t *f, int s, int32_t persisted, const meas_cap_cfg_t *cfg,
                           int32_t *out)
{
    if (f->n < 6) {
        return false;
    }
    double y[MEAS_CAP_FIT_WIN], t[MEAS_CAP_FIT_WIN];
    int m = 0;
    for (int i = 0; i < f->n; i++) {
        y[i] = (double)s * f->x[i];
        t[i] = (double)(int32_t)(f->t[i] - f->t[0]);
        if (y[i] < y[m]) m = i;
    }
    if (m == 0 || m == f->n - 1) {
        return false;
    }
    const double near = 50000.0; /* flank points within 50 um of the extreme */
    double best_err = 1e30, best_y = 0, best_slope = 0;
    for (int split = 0; split < 2; split++) {
        int le = split == 0 ? m : m - 1; /* last index of the left flank */
        int lb = le;
        while (lb > 0 && y[lb - 1] - y[m] <= near && le - lb < MEAS_CAP_FIT_SIDE - 2) lb--;
        int rb = le + 1, re = rb;
        while (re < f->n - 1 && y[re + 1] - y[m] <= near && re - rb < MEAS_CAP_FIT_SIDE - 2) re++;
        int nl = le - lb + 1, nr = re - rb + 1;
        if (nl < 3 || nr < 3) {
            continue;
        }
        double al, bl, ar, br;
        double el = line_fit(t + lb, y + lb, nl, &al, &bl);
        double er = line_fit(t + rb, y + rb, nr, &ar, &br);
        if (!(bl < 0 && br > 0)) {
            continue;
        }
        double err = el > er ? el : er;
        if (err > cfg->refine_resid_nm || err >= best_err) {
            continue;
        }
        double tc = (ar - al) / (bl - br);
        if (tc < t[le] || tc > t[le + 1]) {
            continue; /* the lines must meet between the two flanks */
        }
        best_err = err;
        best_y = al + bl * tc;
        best_slope = fmin(-bl, br);
    }
    if (best_err >= 1e30) {
        return false;
    }
    double lo = y[m] - best_slope * (cfg->sample_ms ? cfg->sample_ms : 10) / 2.0;
    double hi = (double)s * persisted;
    if (best_y < lo) best_y = lo;
    if (best_y > hi) best_y = hi;
    *out = meas_sat_i32((int64_t)llround(s * best_y));
    return true;
}

static void run_extremes(const meas_cap_run_t *s, const meas_cap_cfg_t *cfg, int32_t *mn, int32_t *mx)
{
    *mn = s->have ? s->pmin : s->acc.min;
    *mx = s->have ? s->pmax : s->acc.max;
    if (cfg->refine && s->have) {
        int32_t v;
        if (refine_extreme(&s->fmin, +1, s->pmin, cfg, &v)) *mn = v;
        if (refine_extreme(&s->fmax, -1, s->pmax, cfg, &v)) *mx = v;
    }
}

/* ---- SWEEP: the pending FIFO (samples not yet committed, so a lift-off can be taken back) ---- */

static meas_cap_smp_t *pend_at(meas_capture_t *c, unsigned i) /* 0 = oldest */
{
    return &c->pend[(c->pend_head + i) % MEAS_CAP_PEND];
}

static void pend_commit_oldest(meas_capture_t *c)
{
    run_push(&c->st, pend_at(c, 0), c->cfg.persist);
    c->pend_head = (uint8_t)((c->pend_head + 1u) % MEAS_CAP_PEND);
    c->pend_n--;
}

static void pend_push(meas_capture_t *c, int32_t x, uint32_t t)
{
    if (c->pend_n == MEAS_CAP_PEND) {
        pend_commit_oldest(c);
    }
    meas_cap_smp_t *p = pend_at(c, c->pend_n);
    p->x = x;
    p->t = t;
    p->brk = c->pend_brk ? 1u : 0u;
    c->pend_brk = false;
    c->pend_n++;
}

static void pend_commit_all(meas_capture_t *c)
{
    while (c->pend_n) {
        pend_commit_oldest(c);
    }
}

/* The committed statistics plus the pending samples: what the display shows while in contact. */
static void run_view(const meas_capture_t *c, meas_cap_run_t *v)
{
    *v = c->st;
    for (unsigned i = 0; i < c->pend_n; i++) {
        run_push(v, &c->pend[(c->pend_head + i) % MEAS_CAP_PEND], c->cfg.persist);
    }
}

/* ---- lifecycle ----------------------------------------------------------------------------- */

static void clear_state(meas_capture_t *c)
{
    c->ring_n = 0;
    c->ring_head = 0;
    c->ok_run = 0;
    c->have_pos = false;
    c->leg_dir = 0;
    c->armed = false;
    c->run = false;
    c->run_shown = false;
    c->out_n = 0;
    c->bad_n = 0;
    c->susp = false;
    c->pend_n = 0;
    c->pend_head = 0;
    c->pend_brk = false;
    c->reversed = false;
    c->aborted = false;
    c->srun = 0;
    c->sglitch = 0;
    c->sglitch_pend = false;
    c->fz.valid = false;
    run_clear(&c->st);
}

void meas_cap_init(meas_capture_t *c, const meas_cap_cfg_t *cfg, meas_cap_mode_t mode, meas_sweep_sel_t sel)
{
    memset(c, 0, sizeof(*c));
    if (cfg) {
        c->cfg = *cfg;
    } else {
        meas_cap_cfg_default(&c->cfg);
    }
    meas_cap_cfg_t *k = &c->cfg;
    if (k->sample_ms == 0) k->sample_ms = 10;
    if (k->persist < 1) k->persist = 1;
    if (k->persist > MEAS_CAP_PERSIST_MAX) k->persist = MEAS_CAP_PERSIST_MAX;
    if (k->settle_n < 1) k->settle_n = 1;
    if (k->settle_n > MEAS_CAP_RING) k->settle_n = MEAS_CAP_RING;
    if (k->leg_nm <= 0) k->leg_nm = k->rearm_nm > 0 ? k->rearm_nm : 500000;
    if (ms_to_n(k, k->contact_ms) + ms_to_n(k, k->approach_ms) > MEAS_CAP_RING) {
        k->approach_ms = (uint16_t)((MEAS_CAP_RING - ms_to_n(k, k->contact_ms)) * k->sample_ms);
    }
    c->mode = MEAS_CAP_LIVE;
    c->sel = MEAS_SWEEP_AUTO;
    if (!meas_cap_set_mode(c, mode, sel)) {
        clear_state(c);
    }
}

bool meas_cap_set_mode(meas_capture_t *c, meas_cap_mode_t mode, meas_sweep_sel_t sel)
{
    if ((unsigned)mode >= MEAS_CAP_MODES || mode == MEAS_CAP_SET || (unsigned)sel >= MEAS_SWEEP_SELS) {
        return false;
    }
    c->mode = mode;
    c->sel = sel;
    clear_state(c);
    return true;
}

void meas_cap_set_sel(meas_capture_t *c, meas_sweep_sel_t sel)
{
    if ((unsigned)sel < MEAS_SWEEP_SELS) {
        c->sel = sel;
    }
}

void meas_cap_reset(meas_capture_t *c)
{
    clear_state(c);
}

/* ---- SWEEP --------------------------------------------------------------------------------- */

static meas_cap_ev_t sweep_finish(meas_capture_t *c, bool lift_off)
{
    bool shown = c->run_shown;
    c->run = false;
    c->run_shown = false;
    if (lift_off) {
        /* take the lift-off back out: samples still inside the gate but already leaving fast */
        while (c->pend_n >= 2) {
            const meas_cap_smp_t *a = pend_at(c, c->pend_n - 2u), *b = pend_at(c, c->pend_n - 1u);
            if (((int64_t)b->x - a->x) * c->out_dir > c->cfg.depart_nm) {
                c->pend_n--;
            } else {
                break;
            }
        }
    }
    pend_commit_all(c);
    /* Moving on in its own approach direction: the jaws were stopped in the air, not on a part (a part
     * blocks that direction, so a real contact lifts off the other way) ... unless the run first came
     * back the other way: the stop was a hover over the part (lining it up within the gate) and the
     * contact was made from the other side. Then the run is a contact approached the other way. A
     * rock or a bore sweep moves the mean far less than approach_nm from the stop. */
    bool pause = false;
    if (lift_off && c->approach_known && c->out_dir == c->approach) {
        int64_t back = ((int64_t)c->ref_nm - meas_acc_mean_nm(&c->st.acc)) * c->approach;
        if (c->st.acc.n > 0 && back >= c->cfg.approach_nm) {
            c->approach = (int8_t)-c->approach;
        } else {
            pause = true;
        }
    }
    bool brief = c->st.acc.n < ms_to_n(&c->cfg, c->cfg.min_run_ms) || !c->st.have;
    /* A background candidate (the jaws had not come back since the shown result's lift-off) is a
     * pause in the air after that lift-off, or the real contact after an air pause that was taken
     * for one. The two are mirror images in the position signal; the tie goes to the kind being
     * measured: closing onto a part (OD) for AUTO and MIN, opening into a bore for MAX. */
    int8_t prefer = (int8_t)(c->sel == MEAS_SWEEP_MAX ? 1 : -1);
    bool unwanted = !shown && lift_off && !(c->approach_known && c->approach == prefer);
    /* a hidden candidate is only ever decided at its own lift-off: the safety freeze (or a direct
     * meas_cap_freeze) never replaces the result the user is reading */
    bool hidden_freeze = !shown && !lift_off;
    if (pause || unwanted || hidden_freeze || (lift_off && brief) || c->st.acc.n == 0) {
        c->armed = true; /* still moving: the next stop is a candidate */
        return shown ? MEAS_CAPEV_DISCARD : MEAS_CAPEV_NONE;
    }
    meas_cap_frozen_t *f = &c->fz;
    f->valid = true;
    run_extremes(&c->st, &c->cfg, &f->min_nm, &f->max_nm);
    f->median_nm = meas_acc_mean_nm(&c->st.acc);
    f->sd_nm = meas_acc_sd_nm(&c->st.acc);
    f->n = c->st.acc.n;
    f->approach = c->approach;
    c->last_approach = c->approach;
    c->exit_dir = (int8_t)(lift_off ? c->out_dir : -c->approach);
    c->far_nm = c->last_nm;
    c->reversed = false;
    c->aborted = false;
    c->armed = false;
    c->arm_ref_nm = c->ref_nm;
    return MEAS_CAPEV_DONE;
}

/* A sensor error or a slip during a run: nothing from it is frozen or kept on show. */
static meas_cap_ev_t sweep_abort(meas_capture_t *c)
{
    bool shown = c->run_shown;
    c->run = false;
    c->run_shown = false;
    c->armed = false; /* sticky: the jaws must leave and come back for a new capture */
    c->arm_ref_nm = c->last_nm;
    if (shown) {
        c->aborted = true;
        c->fz.valid = false; /* never freeze or keep showing a value next to a sensor error */
        return MEAS_CAPEV_ABORT;
    }
    return MEAS_CAPEV_NONE;
}

static meas_cap_ev_t sweep_start(meas_capture_t *c, uint32_t t_ms)
{
    const meas_cap_cfg_t *k = &c->cfg;
    unsigned cn = ms_to_n(k, k->contact_ms);
    int32_t w[MEAS_CAP_RING];
    for (unsigned i = 0; i < cn; i++) {
        w[i] = ring_back(c, cn - 1u - i); /* oldest first */
    }
    int32_t tmp[MEAS_CAP_RING];
    memcpy(tmp, w, cn * sizeof(w[0]));
    c->ref_nm = meas_median_i32(tmp, cn);
    /* approach: the move over approach_ms before the still window */
    unsigned back = cn - 1u + ms_to_n(k, k->approach_ms);
    if (back > c->ring_n - 1u) {
        back = c->ring_n - 1u;
    }
    int64_t d = (int64_t)c->ref_nm - ring_back(c, back);
    if (absd(d) >= k->approach_nm) {
        c->approach_known = true;
        c->approach = sgn(d);
    } else if (c->leg_dir != 0) {
        /* the reading first stopped mid-rock (no flat at a fast V cusp: the stop is a turning point
         * 0.25 s or more after the contact), so the look-back saw only the rock: use the last move
         * longer than any rock */
        c->approach_known = true;
        c->approach = c->leg_dir;
    } else {
        c->approach_known = false;
        c->approach = (int8_t)(c->last_approach ? c->last_approach : -1);
    }
    c->run = true;
    c->run_shown = !c->fz.valid || c->reversed;
    c->run_samples = cn;
    c->out_n = 0;
    c->bad_n = 0;
    c->susp = false;
    c->pend_n = 0;
    c->pend_head = 0;
    c->pend_brk = false;
    run_clear(&c->st);
    for (unsigned i = 0; i < cn; i++) {
        pend_push(c, w[i], t_ms - (uint32_t)((cn - 1u - i) * k->sample_ms));
    }
    if (c->run_shown) {
        c->aborted = false;
        return MEAS_CAPEV_CONTACT;
    }
    return MEAS_CAPEV_NONE;
}

static meas_cap_ev_t sweep_update(meas_capture_t *c, int32_t x, bool ok, uint32_t t_ms)
{
    const meas_cap_cfg_t *k = &c->cfg;
    if (!ok) {
        c->ok_run = 0;
        if (c->run) {
            c->run_samples++;
            c->pend_brk = true;
            if (++c->bad_n > k->bad_max) {
                return sweep_abort(c);
            }
        }
        return MEAS_CAPEV_NONE;
    }
    c->bad_n = 0;
    ring_push(c, x);
    if (c->ok_run < 0xFFFFu) {
        c->ok_run++;
    }
    c->last_nm = x;
    if (!c->have_pos) {
        c->have_pos = true;
        c->arm_ref_nm = x; /* must move away first: nothing is captured where it started */
        c->leg_anchor_nm = x;
    }
    /* zig-zag: the anchor follows the reading in the current direction; a move of leg_nm back the
     * other way is a new leg */
    if (c->leg_dir != 0 && ((int64_t)x - c->leg_anchor_nm) * c->leg_dir > 0) {
        c->leg_anchor_nm = x;
    } else if (absd((int64_t)x - c->leg_anchor_nm) >= k->leg_nm) {
        c->leg_dir = sgn((int64_t)x - c->leg_anchor_nm);
        c->leg_anchor_nm = x;
    }
    if (!c->armed && absd((int64_t)x - c->arm_ref_nm) > k->rearm_nm) {
        c->armed = true;
    }
    if (c->fz.valid && !c->reversed) {
        if (((int64_t)x - c->far_nm) * c->exit_dir > 0) {
            c->far_nm = x;
        } else if (((int64_t)c->far_nm - x) * c->exit_dir >= k->rearm_nm) {
            c->reversed = true; /* came back towards a part */
        }
    }
    if (c->run) {
        c->run_samples++;
        int64_t dx = (int64_t)x - c->ref_nm;
        if (absd(dx) <= k->gate_nm) {
            c->out_n = 0;
            c->susp = false; /* back in the gate: that was an excursion (a wide sweep), not a lift-off */
            pend_push(c, x, t_ms);
            if ((uint64_t)c->run_samples * k->sample_ms >= k->max_run_ms) {
                return sweep_finish(c, false);
            }
        } else {
            c->pend_brk = true;
            if (!c->susp) {
                c->out_n++;
                c->out_dir = sgn(dx);
                if (c->out_n >= ms_to_n(k, k->exit_ms)) {
                    if (c->approach_known && c->out_dir == c->approach) {
                        return sweep_finish(c, true); /* on the way it came: decided now (pause / hover) */
                    }
                    c->susp = true;
                    c->susp_n = 0;
                }
            } else if (c->susp_n < 0xFFFFu) {
                c->susp_n++;
            }
            if (c->susp && (absd(dx) > 2 * (int64_t)k->gate_nm || c->susp_n >= ms_to_n(k, k->resume_ms))) {
                return sweep_finish(c, true);
            }
        }
        return MEAS_CAPEV_NONE;
    }
    unsigned cn = ms_to_n(k, k->contact_ms);
    if (c->armed && c->ok_run >= cn) {
        int32_t lo = x, hi = x;
        for (unsigned i = 1; i < cn; i++) {
            int32_t v = ring_back(c, i);
            if (v < lo) lo = v;
            if (v > hi) hi = v;
        }
        if ((int64_t)hi - lo <= k->contact_span_nm) {
            return sweep_start(c, t_ms);
        }
    }
    return MEAS_CAPEV_NONE;
}

/* ---- SETTLE -------------------------------------------------------------------------------- */

static void settle_fire(meas_capture_t *c)
{
    unsigned n = c->cfg.settle_n;
    if (n > c->srun) n = c->srun;
    if (n > c->ring_n) n = c->ring_n;
    if (n == 0) {
        return;
    }
    int32_t w[MEAS_CAP_RING];
    meas_acc_t a;
    meas_acc_reset(&a);
    for (unsigned i = 0; i < n; i++) {
        w[i] = ring_back(c, i);
        meas_acc_add(&a, w[i]);
    }
    meas_cap_frozen_t *f = &c->fz;
    f->valid = true;
    f->median_nm = meas_median_i32(w, n);
    f->min_nm = a.min;
    f->max_nm = a.max;
    f->sd_nm = meas_acc_sd_nm(&a);
    f->n = n;
    f->approach = 0;
    c->armed = false;
    c->arm_ref_nm = f->median_nm;
    c->srun = 0;
}

static meas_cap_ev_t settle_update(meas_capture_t *c, int32_t x, bool ok)
{
    const meas_cap_cfg_t *k = &c->cfg;
    if (!ok) {
        c->srun = 0; /* never fire on a window with a bad sample in it */
        return MEAS_CAPEV_NONE;
    }
    ring_push(c, x);
    c->last_nm = x;
    if (!c->have_pos) {
        c->have_pos = true;
        c->arm_ref_nm = x; /* must move away first: no hold right after power-up */
    }
    if (c->fz.valid) {
        if (absd((int64_t)x - c->fz.median_nm) > k->rearm_nm) {
            c->fz.valid = false; /* the jaws opened again: release */
            c->armed = true;
            c->srun = 0;
            return MEAS_CAPEV_RELEASE;
        }
        return MEAS_CAPEV_NONE;
    }
    if (!c->armed && absd((int64_t)x - c->arm_ref_nm) > k->rearm_nm) {
        c->armed = true;
    }
    if (c->srun == 0) {
        c->smin = c->smax = x;
        c->srun = 1;
        c->sglitch = 0;
        c->sglitch_pend = false;
    } else {
        int32_t lo = x < c->smin ? x : c->smin, hi = x > c->smax ? x : c->smax;
        if ((int64_t)hi - lo <= k->still_span_nm) {
            c->smin = lo;
            c->smax = hi;
            c->sglitch_pend = false;
            if (c->srun < 0xFFFFu) c->srun++;
        } else if (!c->sglitch_pend && c->sglitch < k->settle_glitch) {
            c->sglitch_pend = true; /* one odd sample: keep timing, the median ignores it */
            c->sglitch++;
            if (c->srun < 0xFFFFu) c->srun++;
        } else {
            c->smin = c->smax = x; /* moving: the still run restarts here */
            c->srun = 1;
            c->sglitch = 0;
            c->sglitch_pend = false;
        }
    }
    if (c->armed && c->srun >= ms_to_n(k, k->still_ms)) {
        settle_fire(c);
        return MEAS_CAPEV_DONE;
    }
    return MEAS_CAPEV_NONE;
}

/* ---- public -------------------------------------------------------------------------------- */

void meas_cap_freeze(meas_capture_t *c)
{
    if (c->mode == MEAS_CAP_SWEEP && c->run) {
        sweep_finish(c, false);
    } else if (c->mode == MEAS_CAP_SETTLE && !c->fz.valid && c->srun > 0) {
        settle_fire(c);
    }
}

meas_cap_hold_t meas_cap_hold_press(meas_capture_t *c)
{
    meas_cap_result_t r;
    meas_cap_result(c, &r);
    switch (r.state) {
    case MEAS_CAPST_RUN:
        meas_cap_freeze(c);
        return MEAS_CAP_HOLD_FREEZE;
    case MEAS_CAPST_DONE:
    case MEAS_CAPST_ABORT:
        meas_cap_reset(c);
        return MEAS_CAP_HOLD_REARM;
    default:
        return MEAS_CAP_HOLD_MANUAL;
    }
}

void meas_cap_button(meas_capture_t *c, bool down, uint32_t t_ms, uint16_t before_ms, uint16_t after_ms)
{
    if (down) {
        c->btn_down = true;
        if (c->run) {
            uint32_t from = t_ms - before_ms;
            while (c->pend_n > 0 && (int32_t)(pend_at(c, c->pend_n - 1u)->t - from) >= 0) {
                c->pend_n--;
            }
            c->pend_brk = true;
        }
    } else {
        c->btn_down = false;
        c->blank_active = true;
        c->blank_until = t_ms + after_ms;
    }
}

meas_cap_ev_t meas_cap_update(meas_capture_t *c, int32_t zeroed_nm, bool ok, uint32_t t_ms)
{
    if (c->mode != MEAS_CAP_SETTLE && c->mode != MEAS_CAP_SWEEP) {
        return MEAS_CAPEV_NONE;
    }
    if (c->btn_down) {
        return MEAS_CAPEV_NONE;
    }
    if (c->blank_active) {
        if ((int32_t)(t_ms - c->blank_until) < 0) {
            return MEAS_CAPEV_NONE;
        }
        c->blank_active = false;
        c->ok_run = 0; /* a contact window must not straddle the gap */
    }
    return c->mode == MEAS_CAP_SETTLE ? settle_update(c, zeroed_nm, ok) : sweep_update(c, zeroed_nm, ok, t_ms);
}

meas_cap_ev_t meas_cap_slip(meas_capture_t *c)
{
    c->ok_run = 0; /* a contact window must not straddle the step */
    if (c->mode == MEAS_CAP_SETTLE) {
        c->srun = 0; /* the still window restarts on the corrected position */
        return MEAS_CAPEV_NONE;
    }
    if (c->mode == MEAS_CAP_SWEEP && c->run) {
        return sweep_abort(c);
    }
    return MEAS_CAPEV_NONE;
}

void meas_cap_result(const meas_capture_t *c, meas_cap_result_t *out)
{
    memset(out, 0, sizeof(*out));
    out->mode = c->mode;
    out->value_nm = out->other_nm = c->last_nm;
    if (c->mode == MEAS_CAP_SETTLE) {
        if (c->fz.valid) {
            out->state = MEAS_CAPST_DONE;
            out->value_nm = out->other_nm = c->fz.median_nm;
            out->min_nm = c->fz.min_nm;
            out->max_nm = c->fz.max_nm;
            out->range_nm = meas_sat_i32((int64_t)c->fz.max_nm - c->fz.min_nm);
            out->sd_nm = c->fz.sd_nm;
            out->n = c->fz.n;
        } else {
            out->state = c->armed && c->srun >= ms_to_n(&c->cfg, c->cfg.contact_ms) ? MEAS_CAPST_RUN : MEAS_CAPST_WAIT;
            out->n = c->srun;
        }
        return;
    }
    if (c->mode != MEAS_CAP_SWEEP) {
        out->state = MEAS_CAPST_IDLE;
        return;
    }
    int8_t approach;
    if (c->run && c->run_shown) {
        meas_cap_run_t v;
        run_view(c, &v);
        out->state = MEAS_CAPST_RUN;
        run_extremes(&v, &c->cfg, &out->min_nm, &out->max_nm);
        out->sd_nm = meas_acc_sd_nm(&v.acc);
        out->n = v.acc.n;
        approach = c->approach;
    } else if (c->fz.valid) {
        out->state = MEAS_CAPST_DONE;
        out->min_nm = c->fz.min_nm;
        out->max_nm = c->fz.max_nm;
        out->sd_nm = c->fz.sd_nm;
        out->n = c->fz.n;
        approach = c->fz.approach;
    } else {
        out->state = c->aborted ? MEAS_CAPST_ABORT : MEAS_CAPST_WAIT;
        return;
    }
    out->which = (int8_t)(c->sel == MEAS_SWEEP_MIN ? -1 : c->sel == MEAS_SWEEP_MAX ? 1 : approach);
    out->value_nm = out->which < 0 ? out->min_nm : out->max_nm;
    out->other_nm = out->which < 0 ? out->max_nm : out->min_nm;
    out->range_nm = meas_sat_i32((int64_t)out->max_nm - out->min_nm);
}
