/*
 * Host tests for components/measure/capture.c (SETTLE and SWEEP), on synthetic 100 Hz traces.
 *
 * The traces are analytic: a cylinder rocked between flat jaws l = 7.8 mm thick reads
 * w(t) = D / cos t + l |tan t| (a V-shaped minimum at t = 0), a bore swept across reads the chord
 * 2 sqrt(r^2 - y^2) (a rounded maximum at the centre), a depth rod tilted reads d / cos t. Every
 * sample is quantised to the 488.28125 nm SSI step, optionally with deterministic Gaussian jitter
 * (an LCG, so every host gives the same numbers). The pass bounds are derived from the geometry,
 * so a change to PERSIST, the gate or the refinement shows up as a failing bound, deliberately.
 */
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "capture.h"
#include "measure.h"
#include "tiny_test.h"

#define PI_D   3.14159265358979323846
#define LSB_NM 488.28125
#define DT_S   0.01
#define TR_MAX 8000
#define UM     1000.0
#define MM     1000000.0

static double rad(double deg)
{
    return deg * PI_D / 180.0;
}

/* ---- deterministic noise ---- */
static uint64_t s_lcg = 1;
static void lcg_seed(uint64_t s)
{
    s_lcg = s * 2862933555777941757ULL + 3037000493ULL;
}
static double lcg_u(void) /* (0, 1) */
{
    s_lcg = s_lcg * 6364136223846793005ULL + 1442695040888963407ULL;
    return ((double)(s_lcg >> 11) + 0.5) / 9007199254740992.0;
}
static double lcg_gauss(void)
{
    double u = lcg_u(), v = lcg_u();
    return sqrt(-2.0 * log(u)) * cos(2.0 * PI_D * v);
}

/* ---- traces ---- */
typedef struct {
    int32_t x[TR_MAX];
    uint8_t ok[TR_MAX];
    int n;
    double jitter_nm; /* Gaussian sigma added before quantising */
} trace_t;

static trace_t s_tr, s_tr2;

static int32_t quant(double nm)
{
    return (int32_t)meas_lsb_to_nm((int64_t)llround(nm / LSB_NM));
}

static void tr_reset(trace_t *t, double jitter_nm)
{
    t->n = 0;
    t->jitter_nm = jitter_nm;
}

static void tr_add(trace_t *t, double nm)
{
    if (t->n >= TR_MAX) {
        return;
    }
    double j = t->jitter_nm > 0 ? t->jitter_nm * lcg_gauss() : 0.0;
    t->x[t->n] = quant(nm + j);
    t->ok[t->n] = 1;
    t->n++;
}

static double tr_last(const trace_t *t)
{
    return t->n ? (double)t->x[t->n - 1] : 0.0;
}

static void tr_rest(trace_t *t, double nm, int samples)
{
    for (int i = 0; i < samples; i++) tr_add(t, nm);
}

/* constant-speed move from the last sample to `to` (mm/s), the last step landing on `to` */
static void tr_move(trace_t *t, double to, double mm_per_s)
{
    double from = tr_last(t), step = mm_per_s * MM * DT_S;
    int k = (int)ceil(fabs(to - from) / step);
    for (int i = 1; i <= k; i++) tr_add(t, from + (to - from) * i / k);
}

typedef struct {
    double D, l, th_deg, f, bias_deg, phase, secs;
} od_t;

static double od_x(const od_t *p, double tt)
{
    double th = rad(p->bias_deg) + rad(p->th_deg) * sin(2.0 * PI_D * p->f * tt + p->phase);
    return p->D / cos(th) + p->l * fabs(tan(th));
}

/* rest at D + 3 mm, close at 20 mm/s onto the part, rock, open at 20 mm/s by 3 mm, rest.
 * Returns the index of the first rocking sample; *rock_n gets the number of rocking samples. */
static int gen_od(trace_t *t, const od_t *p, int *rock_n)
{
    tr_rest(t, p->D + 3 * MM, 50);
    tr_move(t, od_x(p, 0), 20);
    int first = t->n;
    int n = (int)lround(p->secs / DT_S);
    for (int i = 0; i < n; i++) tr_add(t, od_x(p, i * DT_S));
    *rock_n = n;
    tr_move(t, tr_last(t) + 3 * MM, 20);
    tr_rest(t, tr_last(t), 50);
    return first;
}

/* ---- feeding ---- */
typedef struct {
    int done, contact, discard, abort_, release;
    int done_i;              /* trace index of the last DONE */
    meas_cap_result_t last;  /* the result right after the last DONE */
} evlog_t;

static uint32_t s_t0 = 1000;

static void feed(meas_capture_t *c, const trace_t *t, int from, int to, evlog_t *e)
{
    for (int i = from; i < to && i < t->n; i++) {
        meas_cap_ev_t ev = meas_cap_update(c, t->x[i], t->ok[i] != 0, s_t0 + (uint32_t)i * 10u);
        switch (ev) {
        case MEAS_CAPEV_DONE:
            e->done++;
            e->done_i = i;
            meas_cap_result(c, &e->last);
            break;
        case MEAS_CAPEV_CONTACT: e->contact++; break;
        case MEAS_CAPEV_DISCARD: e->discard++; break;
        case MEAS_CAPEV_ABORT: e->abort_++; break;
        case MEAS_CAPEV_RELEASE: e->release++; break;
        default: break;
        }
    }
}

static void cap_new(meas_capture_t *c, meas_cap_mode_t m, meas_sweep_sel_t sel, bool refine)
{
    meas_cap_cfg_t cfg;
    meas_cap_cfg_default(&cfg);
    cfg.refine = refine;
    meas_cap_init(c, &cfg, m, sel);
}

static int32_t trace_min(const trace_t *t, int from, int n)
{
    int32_t m = INT32_MAX;
    for (int i = from; i < from + n; i++) {
        if (t->x[i] < m) m = t->x[i];
    }
    return m;
}

/* The worst-case sampling error of the persisted MIN at a V cusp: l * dtheta/dt max * dt * P / 2. */
static double cusp_bound_nm(const od_t *p, int persist)
{
    double rate = p->l * rad(p->th_deg) * 2.0 * PI_D * p->f; /* nm/s at the cusp */
    return rate * DT_S * persist / 2.0;
}

/* ---- 1. OD rock, slow (0.5 deg, 0.5 Hz): DONE once after lift-off, MIN, bound, R, n ---------- */
static void test_cap_od_rock(void)
{
    meas_capture_t c;
    od_t p = {.D = 20 * MM, .l = 7.8 * MM, .th_deg = 0.5, .f = 0.5, .secs = 4.0};
    lcg_seed(1);
    tr_reset(&s_tr, 300.0);
    int rock_n, first = gen_od(&s_tr, &p, &rock_n);
    cap_new(&c, MEAS_CAP_SWEEP, MEAS_SWEEP_AUTO, false);
    evlog_t e = {0};
    feed(&c, &s_tr, 0, s_tr.n, &e);
    CHECK_EQ_INT(e.done, 1);
    CHECK_EQ_INT(e.contact, 1);
    CHECK(e.done_i > first + rock_n); /* after the lift-off, not before */
    CHECK_EQ_INT(e.last.which, -1);
    CHECK_EQ_INT(e.last.state, MEAS_CAPST_DONE);
    double err = e.last.value_nm - p.D;
    double bound = cusp_bound_nm(&p, 2) + 1 * UM;
    CHECK(err >= -LSB_NM / 2 && err <= bound);
    /* R against the analytic l tan(t) + D (1/cos(t) - 1) = 68.9 um */
    double r_an = p.l * tan(rad(p.th_deg)) + p.D * (1.0 / cos(rad(p.th_deg)) - 1.0);
    printf("    (OD 0.5 deg 0.5 Hz: MIN - D = %.0f nm, bound %.0f; R %ld nm vs %.0f analytic; n %lu of %d)\n", err,
           bound, (long)e.last.range_nm, r_an, (unsigned long)e.last.n, rock_n);
    CHECK_NEAR(e.last.range_nm, r_an, 0.10 * r_an);
    CHECK_EQ_INT(e.last.range_nm, e.last.other_nm - e.last.value_nm);
    /* approach and lift-off samples excluded */
    CHECK((int)e.last.n >= rock_n - 15 && (int)e.last.n <= rock_n + 15);
    /* the post-lift-off rest in the air did not replace or hide the result */
    meas_cap_result_t r;
    meas_cap_result(&c, &r);
    CHECK_EQ_INT(r.state, MEAS_CAPST_DONE);
    CHECK_EQ_INT(r.value_nm, e.last.value_nm);

    /* random rock phases and a tilt bias: the bound holds for all of them */
    int bad = 0;
    for (int k = 0; k < 40; k++) {
        lcg_seed(100 + (uint64_t)k);
        od_t q = p;
        q.bias_deg = (lcg_u() - 0.5) * 0.2;
        q.phase = lcg_u() * 2 * PI_D;
        tr_reset(&s_tr, 300.0);
        first = gen_od(&s_tr, &q, &rock_n);
        cap_new(&c, MEAS_CAP_SWEEP, MEAS_SWEEP_AUTO, false);
        evlog_t f = {0};
        feed(&c, &s_tr, 0, s_tr.n, &f);
        double ek = f.last.value_nm - q.D;
        if (f.done != 1 || f.last.which != -1 || ek < -LSB_NM / 2 || ek > cusp_bound_nm(&q, 2) + 1 * UM) {
            bad++;
            printf("  phase case %d: done %d which %d err %.0f nm\n", k, f.done, f.last.which, ek);
        }
    }
    CHECK_EQ_INT(bad, 0);
}

/* ---- 2. fast cusp (1 deg, 1 Hz = 8.6 um per sample), refinement, rounded bottom --------------- */
static void test_cap_fast_cusp(void)
{
    meas_capture_t c;
    od_t p = {.D = 20 * MM, .l = 7.8 * MM, .th_deg = 1.0, .f = 1.0, .secs = 4.0, .phase = 0.3};
    double bound = cusp_bound_nm(&p, 2) + 1 * UM; /* 9.6 um */
    lcg_seed(2);
    tr_reset(&s_tr, 300.0);
    int rock_n;
    gen_od(&s_tr, &p, &rock_n);
    cap_new(&c, MEAS_CAP_SWEEP, MEAS_SWEEP_AUTO, false);
    evlog_t e = {0};
    feed(&c, &s_tr, 0, s_tr.n, &e);
    CHECK_EQ_INT(e.done, 1);
    double err = e.last.value_nm - p.D;
    CHECK(err >= -LSB_NM / 2 && err <= bound);
    /* refinement on: the two flanks' lines meet at the cusp */
    cap_new(&c, MEAS_CAP_SWEEP, MEAS_SWEEP_AUTO, true);
    evlog_t g = {0};
    feed(&c, &s_tr, 0, s_tr.n, &g);
    CHECK_EQ_INT(g.done, 1);
    printf("    (OD 1 deg 1 Hz: persisted MIN - D = %.0f nm (bound %.0f), refined %ld nm)\n", err, bound,
           (long)(g.last.value_nm - (int32_t)p.D));
    CHECK(fabs(g.last.value_nm - p.D) <= 2 * UM);
    CHECK(g.last.value_nm <= e.last.value_nm); /* never above the persisted minimum */
    /* phases: the refined value stays within 2 um, and within [raw min - half a step, persisted] */
    int bad = 0;
    for (int k = 0; k < 20; k++) {
        lcg_seed(200 + (uint64_t)k);
        od_t q = p;
        q.phase = lcg_u() * 2 * PI_D;
        tr_reset(&s_tr, 300.0);
        int first = gen_od(&s_tr, &q, &rock_n);
        cap_new(&c, MEAS_CAP_SWEEP, MEAS_SWEEP_AUTO, true);
        evlog_t f = {0};
        feed(&c, &s_tr, 0, s_tr.n, &f);
        double ek = f.last.value_nm - q.D;
        if (f.done != 1 || fabs(ek) > 2 * UM ||
            f.last.value_nm < trace_min(&s_tr, first, rock_n) - cusp_bound_nm(&q, 1) - 1 * UM) {
            bad++;
            printf("  refine case %d: done %d err %.0f nm\n", k, f.done, ek);
        }
    }
    CHECK_EQ_INT(bad, 0);

    /* rounded bottom (a self-seating part: x = D + k t^2): refinement never goes below the raw
     * minimum (the samples do not form a V, so the fit is not used) */
    double kq = 136.0 * UM / (rad(1.0) * rad(1.0)); /* the same 136 um at full tilt */
    for (int v = 0; v < 2; v++) {
        lcg_seed(300 + (uint64_t)v);
        tr_reset(&s_tr, v ? 300.0 : 0.0);
        tr_rest(&s_tr, p.D + 3 * MM, 50);
        tr_move(&s_tr, p.D + kq * pow(rad(1.0) * sin(0.4), 2), 20);
        int first = s_tr.n;
        for (int i = 0; i < 400; i++) {
            double th = rad(1.0) * sin(2 * PI_D * i * DT_S + 0.4);
            tr_add(&s_tr, p.D + kq * th * th);
        }
        tr_move(&s_tr, tr_last(&s_tr) + 3 * MM, 20);
        tr_rest(&s_tr, tr_last(&s_tr), 50);
        cap_new(&c, MEAS_CAP_SWEEP, MEAS_SWEEP_AUTO, true);
        evlog_t f = {0};
        feed(&c, &s_tr, 0, s_tr.n, &f);
        CHECK_EQ_INT(f.done, 1);
        CHECK(f.last.value_nm >= trace_min(&s_tr, first, 400));
        CHECK(f.last.value_nm - p.D <= 2 * UM);
    }
}

/* ---- 3. ID sweep across a 12 mm bore: MAX ------------------------------------------------------ */
static double id_x(double D, double ymax, double f, double tt)
{
    double r = D / 2, y = ymax * sin(2 * PI_D * f * tt);
    return 2 * sqrt(r * r - y * y);
}

static void test_cap_id_sweep(void)
{
    meas_capture_t c;
    double D = 12 * MM;
    lcg_seed(3);
    tr_reset(&s_tr, 300.0);
    tr_rest(&s_tr, D - 3 * MM, 50);
    tr_move(&s_tr, id_x(D, 1 * MM, 0.5, 0), 20); /* inside jaws opening onto the bore */
    for (int i = 0; i < 400; i++) tr_add(&s_tr, id_x(D, 1 * MM, 0.5, i * DT_S));
    tr_move(&s_tr, tr_last(&s_tr) - 3 * MM, 20);
    tr_rest(&s_tr, tr_last(&s_tr), 50);
    cap_new(&c, MEAS_CAP_SWEEP, MEAS_SWEEP_AUTO, false);
    evlog_t e = {0};
    feed(&c, &s_tr, 0, s_tr.n, &e);
    CHECK_EQ_INT(e.done, 1);
    CHECK_EQ_INT(e.last.which, 1);
    printf("    (ID 12 mm: MAX - D = %ld nm, n %lu)\n", (long)(e.last.value_nm - (int32_t)D), (unsigned long)e.last.n);
    CHECK(fabs(e.last.value_nm - D) <= 2 * UM);

    /* the other extreme is the chord at the 1 mm offset: 2 sqrt(36 - 1) mm */
    CHECK(fabs(e.last.other_nm - 2 * sqrt(36.0 - 1.0) * MM) <= 3 * UM);
}

/* ---- depth: the rod approaches by opening, so AUTO says MAX (the documented caveat); MIN forced -- */
static void test_cap_depth(void)
{
    meas_capture_t c;
    double d = 20 * MM;
    lcg_seed(4);
    tr_reset(&s_tr, 300.0);
    tr_rest(&s_tr, d - 5 * MM, 50);
    tr_move(&s_tr, d / cos(rad(2.0)), 20);
    for (int i = 0; i < 300; i++) tr_add(&s_tr, d / cos(rad(2.0) * cos(2 * PI_D * 0.5 * i * DT_S)));
    tr_move(&s_tr, tr_last(&s_tr) - 5 * MM, 20);
    tr_rest(&s_tr, tr_last(&s_tr), 50);
    cap_new(&c, MEAS_CAP_SWEEP, MEAS_SWEEP_AUTO, false);
    evlog_t e = {0};
    feed(&c, &s_tr, 0, s_tr.n, &e);
    CHECK_EQ_INT(e.done, 1);
    CHECK_EQ_INT(e.last.which, 1); /* AUTO: opening = MAX, wrong for depth */
    CHECK(fabs(e.last.value_nm - d / cos(rad(2.0))) <= 2 * UM);
    /* the choice changes after the fact: both extremes were kept */
    meas_cap_set_sel(&c, MEAS_SWEEP_MIN);
    meas_cap_result_t r;
    meas_cap_result(&c, &r);
    CHECK_EQ_INT(r.which, -1);
    CHECK(fabs(r.value_nm - d) <= 2 * UM);
    CHECK_EQ_INT(r.other_nm, e.last.value_nm);
    CHECK_EQ_INT(r.range_nm, e.last.range_nm);
    /* forced MIN from the start gives the same */
    cap_new(&c, MEAS_CAP_SWEEP, MEAS_SWEEP_MIN, false);
    evlog_t f = {0};
    feed(&c, &s_tr, 0, s_tr.n, &f);
    CHECK_EQ_INT(f.done, 1);
    CHECK_EQ_INT(f.last.which, -1);
    CHECK_EQ_INT(f.last.value_nm, r.value_nm);
}

/* ---- 4. spikes: one sample is rejected by persistence, three are not (documented) -------------- */
static void test_cap_spike(void)
{
    meas_capture_t c;
    od_t p = {.D = 20 * MM, .l = 7.8 * MM, .th_deg = 0.5, .f = 0.5, .secs = 4.0};
    for (int width = 1; width <= 3; width += 2) {
        lcg_seed(5);
        tr_reset(&s_tr, 300.0);
        int rock_n, first = gen_od(&s_tr, &p, &rock_n);
        for (int i = 0; i < width; i++) {
            s_tr.x[first + 99 + i] -= 50000; /* at the cusp of t = 1 s */
        }
        cap_new(&c, MEAS_CAP_SWEEP, MEAS_SWEEP_AUTO, false);
        evlog_t e = {0};
        feed(&c, &s_tr, 0, s_tr.n, &e);
        CHECK_EQ_INT(e.done, 1);
        double err = e.last.value_nm - p.D;
        if (width == 1) {
            CHECK(err >= -LSB_NM / 2 && err <= cusp_bound_nm(&p, 2) + 1 * UM);
        } else {
            CHECK(err < -40 * UM); /* a 30 ms dip persists: it is taken as real */
        }
    }
}

/* ---- 5. sensor errors and a slip ---------------------------------------------------------------- */
static void test_cap_sensor(void)
{
    meas_capture_t c;
    od_t p = {.D = 20 * MM, .l = 7.8 * MM, .th_deg = 0.5, .f = 0.5, .secs = 4.0};
    lcg_seed(6);
    tr_reset(&s_tr, 300.0);
    int rock_n, first = gen_od(&s_tr, &p, &rock_n);
    /* one bad sample: ignored */
    s_tr2 = s_tr;
    s_tr2.ok[first + 100] = 0;
    s_tr2.x[first + 100] = 0;
    cap_new(&c, MEAS_CAP_SWEEP, MEAS_SWEEP_AUTO, false);
    evlog_t e = {0};
    feed(&c, &s_tr2, 0, s_tr2.n, &e);
    CHECK_EQ_INT(e.done, 1);
    CHECK_EQ_INT(e.abort_, 0);
    CHECK(e.last.value_nm - p.D <= cusp_bound_nm(&p, 2) + 1 * UM);
    /* six in a row: ABORT, nothing frozen; it stays aborted until the jaws leave and come back */
    s_tr2 = s_tr;
    for (int i = 0; i < 6; i++) s_tr2.ok[first + 100 + i] = 0;
    cap_new(&c, MEAS_CAP_SWEEP, MEAS_SWEEP_AUTO, false);
    evlog_t f = {0};
    feed(&c, &s_tr2, 0, first + 106, &f);
    CHECK_EQ_INT(f.abort_, 1);
    meas_cap_result_t r;
    meas_cap_result(&c, &r);
    CHECK_EQ_INT(r.state, MEAS_CAPST_ABORT);
    feed(&c, &s_tr2, first + 106, first + rock_n, &f);
    meas_cap_result(&c, &r);
    CHECK_EQ_INT(r.state, MEAS_CAPST_ABORT); /* still on the part: no new capture */
    CHECK_EQ_INT(f.done, 0);
    CHECK_EQ_INT(f.contact, 1);
    /* a pole slip (+2 mm for 3 samples, then back): outside the gate for less than exit_ms, ignored */
    s_tr2 = s_tr;
    for (int i = 0; i < 3; i++) s_tr2.x[first + 150 + i] += 2000000;
    cap_new(&c, MEAS_CAP_SWEEP, MEAS_SWEEP_AUTO, false);
    evlog_t g = {0};
    feed(&c, &s_tr2, 0, s_tr2.n, &g);
    CHECK_EQ_INT(g.done, 1);
    CHECK_EQ_INT(g.contact, 1);
    CHECK(g.last.value_nm - p.D <= cusp_bound_nm(&p, 2) + 1 * UM);
    CHECK(g.last.range_nm < 80 * UM); /* the slip samples are not in the statistics */
}

/* ---- 6. zero crossing: results shift exactly with the zero ------------------------------------- */
static void test_cap_zero_cross(void)
{
    meas_capture_t c;
    od_t p = {.D = 20 * MM, .l = 7.8 * MM, .th_deg = 0.5, .f = 0.5, .secs = 4.0};
    lcg_seed(7);
    tr_reset(&s_tr, 300.0);
    int rock_n;
    gen_od(&s_tr, &p, &rock_n);
    cap_new(&c, MEAS_CAP_SWEEP, MEAS_SWEEP_AUTO, false);
    evlog_t e = {0};
    feed(&c, &s_tr, 0, s_tr.n, &e);
    CHECK_EQ_INT(e.done, 1);
    /* zero 30 um above D: the rock crosses 0; then 1 mm above: all negative */
    const int32_t zeros[2] = {20030000, 21000000};
    for (int z = 0; z < 2; z++) {
        s_tr2 = s_tr;
        for (int i = 0; i < s_tr2.n; i++) s_tr2.x[i] -= zeros[z];
        cap_new(&c, MEAS_CAP_SWEEP, MEAS_SWEEP_AUTO, false);
        evlog_t f = {0};
        feed(&c, &s_tr2, 0, s_tr2.n, &f);
        CHECK_EQ_INT(f.done, 1);
        CHECK_EQ_INT(f.last.value_nm, e.last.value_nm - zeros[z]);
        CHECK_EQ_INT(f.last.other_nm, e.last.other_nm - zeros[z]);
        CHECK_EQ_INT(f.last.range_nm, e.last.range_nm);
        CHECK_EQ_INT(f.last.sd_nm, e.last.sd_nm);
        CHECK_EQ_INT(f.last.n, e.last.n);
    }
    CHECK(e.last.value_nm - 20030000 < 0 && e.last.other_nm - 20030000 > 0);
}

/* ---- 7. gate: a second diameter inside the gate is followed; outside it is a new contact -------- */
static void test_cap_gate(void)
{
    meas_capture_t c;
    od_t p1 = {.D = 20 * MM, .l = 7.8 * MM, .th_deg = 0.5, .f = 0.5, .secs = 2.0};
    for (int big = 0; big < 2; big++) {
        double step = big ? 1.5 * MM : 0.6 * MM;
        od_t p2 = p1;
        p2.D = p1.D - step;
        lcg_seed(8);
        tr_reset(&s_tr, 300.0);
        int rock_n;
        gen_od(&s_tr, &p1, &rock_n);
        s_tr.n -= 15 + 50; /* drop the lift-off: slide straight on to the second diameter */
        tr_move(&s_tr, od_x(&p2, 0), 5);
        for (int i = 0; i < 200; i++) tr_add(&s_tr, od_x(&p2, i * DT_S));
        tr_move(&s_tr, tr_last(&s_tr) + 3 * MM, 20);
        tr_rest(&s_tr, tr_last(&s_tr), 50);
        cap_new(&c, MEAS_CAP_SWEEP, MEAS_SWEEP_AUTO, false);
        evlog_t e = {0};
        feed(&c, &s_tr, 0, s_tr.n, &e);
        CHECK_EQ_INT(e.done, 1);
        CHECK(fabs(e.last.value_nm - p2.D) <= cusp_bound_nm(&p2, 2) + 1 * UM);
        if (big) {
            /* 1.5 mm: the first contact ended moving on in its own approach direction (closing), so
             * it is taken as a pause and discarded; the second diameter is a new contact */
            CHECK_EQ_INT(e.contact, 2);
            CHECK_EQ_INT(e.discard, 1);
            CHECK(e.last.range_nm < 100 * UM);
        } else {
            /* 0.6 mm: inside the gate, MIN follows it and R spans both (documented) */
            CHECK_EQ_INT(e.contact, 1);
            CHECK(e.last.range_nm > 600 * UM);
        }
    }
}

/* ---- 8. re-arm: jitter at rest never captures; after DONE the jaws must move and come back ------ */
static void test_cap_rearm(void)
{
    meas_capture_t c;
    lcg_seed(9);
    tr_reset(&s_tr, 0.0);
    for (int i = 0; i < 1000; i++) tr_add(&s_tr, 5 * MM + (lcg_u() - 0.5) * 6 * UM); /* +-3 um, 10 s */
    cap_new(&c, MEAS_CAP_SWEEP, MEAS_SWEEP_AUTO, false);
    evlog_t e = {0};
    feed(&c, &s_tr, 0, s_tr.n, &e);
    CHECK_EQ_INT(e.contact + e.done + e.discard, 0);
    meas_cap_result_t r;
    meas_cap_result(&c, &r);
    CHECK_EQ_INT(r.state, MEAS_CAPST_WAIT);

    /* a capture, frozen by hand while still on the part; resting on it captures nothing more */
    od_t p = {.D = 20 * MM, .l = 7.8 * MM, .th_deg = 0.5, .f = 0.5, .secs = 2.0};
    tr_reset(&s_tr, 300.0);
    tr_rest(&s_tr, p.D + 3 * MM, 50);
    tr_move(&s_tr, od_x(&p, 0), 20);
    int first = s_tr.n;
    for (int i = 0; i < 600; i++) tr_add(&s_tr, od_x(&p, i * DT_S));
    cap_new(&c, MEAS_CAP_SWEEP, MEAS_SWEEP_AUTO, false);
    evlog_t f = {0};
    feed(&c, &s_tr, 0, first + 200, &f);
    CHECK_EQ_INT(meas_cap_hold_press(&c), MEAS_CAP_HOLD_FREEZE);
    meas_cap_result(&c, &r);
    CHECK_EQ_INT(r.state, MEAS_CAPST_DONE);
    int32_t frozen = r.value_nm;
    feed(&c, &s_tr, first + 200, s_tr.n, &f);
    meas_cap_result(&c, &r);
    CHECK_EQ_INT(r.state, MEAS_CAPST_DONE);
    CHECK_EQ_INT(r.value_nm, frozen);
    CHECK_EQ_INT(f.contact, 1);

    /* lift-off, a pause in the air (no capture shown), more opening (still nothing), then back
     * onto a 15 mm part: a new contact, shown live, and frozen at the next lift-off */
    s_tr2 = s_tr;
    trace_t *t = &s_tr2;
    int a = t->n;
    tr_move(t, tr_last(t) + 2 * MM, 20);
    tr_rest(t, tr_last(t) + 0, 150);
    int pause_end = t->n;
    tr_move(t, tr_last(t) + 4 * MM, 20);
    tr_rest(t, tr_last(t), 100);
    od_t q = p;
    q.D = 15 * MM;
    tr_move(t, od_x(&q, 0), 20);
    int second = t->n;
    for (int i = 0; i < 300; i++) tr_add(t, od_x(&q, i * DT_S));
    tr_move(t, tr_last(t) + 3 * MM, 20);
    tr_rest(t, tr_last(t), 50);
    evlog_t g = {0};
    feed(&c, t, a, pause_end, &g);
    meas_cap_result(&c, &r);
    CHECK_EQ_INT(r.state, MEAS_CAPST_DONE);
    CHECK_EQ_INT(r.value_nm, frozen); /* the user can still read it */
    feed(&c, t, pause_end, second + 50, &g);
    meas_cap_result(&c, &r);
    CHECK_EQ_INT(r.state, MEAS_CAPST_RUN);
    CHECK_EQ_INT(g.contact, 1);
    CHECK_EQ_INT(g.done, 0); /* the air pauses never froze anything */
    feed(&c, t, second + 50, t->n, &g);
    CHECK_EQ_INT(g.done, 1);
    CHECK(fabs(g.last.value_nm - q.D) <= cusp_bound_nm(&q, 2) + 1 * UM);
}

/* ---- 9. SETTLE: median of the still window ------------------------------------------------------ */
static int32_t median_ref(const int32_t *x, int n)
{
    int32_t v[64];
    memcpy(v, x, (size_t)n * sizeof(int32_t));
    for (int i = 0; i < n; i++) { /* selection sort: independent of the code under test */
        for (int j = i + 1; j < n; j++) {
            if (v[j] < v[i]) {
                int32_t tmp = v[i];
                v[i] = v[j];
                v[j] = tmp;
            }
        }
    }
    if (n & 1) return v[n / 2];
    int64_t s = (int64_t)v[n / 2 - 1] + v[n / 2];
    return (int32_t)(s >= 0 ? (s + 1) / 2 : -((-s + 1) / 2));
}

static void test_cap_settle(void)
{
    meas_capture_t c;
    meas_cap_cfg_t cfg;
    meas_cap_cfg_default(&cfg);
    const int still_n = cfg.still_ms / cfg.sample_ms, win = cfg.settle_n;
    for (int glitch = 0; glitch < 2; glitch++) {
        lcg_seed(10);
        tr_reset(&s_tr, 0.0);
        tr_rest(&s_tr, 0, 50);
        tr_move(&s_tr, 25 * MM, 50);
        int still = s_tr.n;
        for (int i = 0; i < 500; i++) tr_add(&s_tr, 25 * MM + (lcg_u() - 0.5) * 8 * UM);
        int32_t orig = s_tr.x[still + 60];
        if (glitch) {
            s_tr.x[still + 60] += 40000;
        }
        cap_new(&c, MEAS_CAP_SETTLE, MEAS_SWEEP_AUTO, false);
        evlog_t e = {0};
        feed(&c, &s_tr, 0, s_tr.n, &e);
        CHECK_EQ_INT(e.done, 1);
        CHECK_EQ_INT(e.done_i, still - 1 + still_n - 1); /* the move's last sample is already at 25 mm */
        CHECK_EQ_INT(e.last.n, win);
        int32_t want = median_ref(&s_tr.x[e.done_i - win + 1], win);
        CHECK_EQ_INT(e.last.value_nm, want);
        if (glitch) {
            s_tr.x[still + 60] = orig;
            int32_t clean = median_ref(&s_tr.x[e.done_i - win + 1], win);
            CHECK(abs(e.last.value_nm - clean) <= (int)ceil(LSB_NM));
        }
        if (!glitch) {
            CHECK(e.last.sd_nm > 1000 && e.last.sd_nm < 3500); /* 8 um uniform: 2.3 um */
        }
    }
    /* a slow ramp (20 um/s) never fires */
    tr_reset(&s_tr, 0.0);
    tr_rest(&s_tr, 0, 50);
    tr_move(&s_tr, 25 * MM, 50);
    for (int i = 0; i < 1000; i++) tr_add(&s_tr, 25 * MM + i * 0.2 * UM);
    cap_new(&c, MEAS_CAP_SETTLE, MEAS_SWEEP_AUTO, false);
    evlog_t f = {0};
    feed(&c, &s_tr, 0, s_tr.n, &f);
    CHECK_EQ_INT(f.done, 0);
    /* still at power-up never fires; a release when the jaws open; fires again after the next move */
    tr_reset(&s_tr, 0.0);
    tr_rest(&s_tr, 3 * MM, 200);
    tr_move(&s_tr, 10 * MM, 50);
    tr_rest(&s_tr, 10 * MM, 100);
    tr_move(&s_tr, 10.3 * MM, 50); /* less than the re-arm distance: stays frozen */
    tr_rest(&s_tr, 10.3 * MM, 100);
    tr_move(&s_tr, 14 * MM, 50);
    tr_rest(&s_tr, 14 * MM, 100);
    cap_new(&c, MEAS_CAP_SETTLE, MEAS_SWEEP_AUTO, false);
    evlog_t g = {0};
    feed(&c, &s_tr, 0, s_tr.n, &g);
    CHECK_EQ_INT(g.done, 2);
    CHECK_EQ_INT(g.release, 1);
    CHECK_EQ_INT(g.last.value_nm, 14000000);
    /* a bad sample restarts the still window */
    tr_reset(&s_tr, 0.0);
    tr_rest(&s_tr, 0, 10);
    tr_move(&s_tr, 5 * MM, 50);
    int s0 = s_tr.n;
    tr_rest(&s_tr, 5 * MM, 200);
    s_tr.ok[s0 + 40] = 0;
    cap_new(&c, MEAS_CAP_SETTLE, MEAS_SWEEP_AUTO, false);
    evlog_t h = {0};
    feed(&c, &s_tr, 0, s_tr.n, &h);
    CHECK_EQ_INT(h.done, 1);
    CHECK_EQ_INT(h.done_i, s0 + 41 + still_n - 1);
}

/* ---- 10. accumulator: exact sums against a long-double reference; the gate extremes ------------ */
static void test_cap_acc(void)
{
    meas_acc_t a;
    meas_acc_reset(&a);
    CHECK_EQ_INT(meas_acc_mean_nm(&a), 0);
    CHECK_EQ_INT(meas_acc_sd_nm(&a), 0);
    lcg_seed(11);
    long double s = 0, s2 = 0;
    const int n = 1000000;
    static int32_t xs[1000000];
    for (int i = 0; i < n; i++) {
        xs[i] = 87654321 + (int32_t)llround((lcg_u() - 0.5) * 2e6);
        meas_acc_add(&a, xs[i]);
        s += xs[i];
    }
    long double mean = s / n;
    for (int i = 0; i < n; i++) s2 += (xs[i] - mean) * (xs[i] - mean);
    double sd = sqrt((double)(s2 / (n - 1)));
    CHECK_EQ_INT(a.n, n);
    CHECK(fabs(meas_acc_mean_nm(&a) - (double)mean) <= 1.0);
    CHECK(fabs(meas_acc_sd_nm(&a) - sd) <= 1.0);
    /* the gate extremes: +-1 mm about a first sample at -1 mm, i.e. |x - x0| = 2 mm, at the n limit */
    meas_acc_reset(&a);
    for (uint32_t i = 0; i < MEAS_ACC_N_MAX + 10u; i++) {
        meas_acc_add(&a, (i & 1u) ? 1000000 : -1000000);
    }
    CHECK_EQ_INT(a.n, MEAS_ACC_N_MAX);
    CHECK_EQ_INT(meas_acc_mean_nm(&a), 0);
    CHECK_EQ_INT(meas_acc_sd_nm(&a), 1000000);
    CHECK_EQ_INT(meas_acc_range_nm(&a), 2000000);
    /* median helper */
    int32_t v[6] = {5, -3, 9, 1, -3, 4};
    CHECK_EQ_INT(meas_median_i32(v, 5), 1);
    int32_t w[4] = {-2, -1, 7, 8};
    CHECK_EQ_INT(meas_median_i32(w, 4), 3); /* (-1 + 7) / 2 */
    int32_t u[2] = {-2, -1};
    CHECK_EQ_INT(meas_median_i32(u, 2), -2); /* -1.5 rounds away from zero */
}

/* ---- 11. units: the capture is unit-free nm; R is formatted from the exact nm difference -------- */
static void test_cap_units(void)
{
    /* the same trace, the display switched mid-capture: the capture never sees the unit */
    meas_capture_t c;
    od_t p = {.D = 20 * MM, .l = 7.8 * MM, .th_deg = 0.5, .f = 0.5, .secs = 3.0};
    lcg_seed(12);
    tr_reset(&s_tr, 300.0);
    int rock_n, first = gen_od(&s_tr, &p, &rock_n);
    cap_new(&c, MEAS_CAP_SWEEP, MEAS_SWEEP_AUTO, false);
    evlog_t e = {0};
    feed(&c, &s_tr, 0, s_tr.n, &e);
    cap_new(&c, MEAS_CAP_SWEEP, MEAS_SWEEP_AUTO, false);
    evlog_t f = {0};
    char buf[16];
    feed(&c, &s_tr, 0, first + 100, &f);
    meas_cap_result_t r;
    meas_cap_result(&c, &r);
    meas_fmt_t in = meas_fmt_for(MEAS_UNIT_INCH, 2);
    CHECK(meas_format(r.value_nm, &in, buf, sizeof(buf)) > 0); /* what the display does on a switch */
    feed(&c, &s_tr, first + 100, s_tr.n, &f);
    CHECK_EQ_INT(f.last.value_nm, e.last.value_nm);
    CHECK_EQ_INT(f.last.other_nm, e.last.other_nm);
    CHECK_EQ_INT(f.last.n, e.last.n);
    /* R takes one digit more than the reading: mm 3 decimals, inch 5 */
    meas_fmt_t mm_f = meas_fmt_for(MEAS_UNIT_MM, 2 + 1), in_f = meas_fmt_for(MEAS_UNIT_INCH, 2 + 1);
    CHECK_EQ_INT(mm_f.decimals, 3);
    CHECK_EQ_INT(in_f.decimals, 5);
    /* min 12.3454, max 12.3546 mm: round(max) - round(min) = 0.010, but R = 0.0092 -> "0.009" */
    int32_t mn = 12345400, mx = 12354600;
    int32_t naive = meas_round_nm(mx, &mm_f) - meas_round_nm(mn, &mm_f);
    CHECK_EQ_INT(naive, 10000);
    CHECK(meas_format(mx - mn, &mm_f, buf, sizeof(buf)) > 0);
    CHECK_EQ_STR(buf, "0.009");
    CHECK(meas_format(mx - mn, &in_f, buf, sizeof(buf)) > 0);
    CHECK_EQ_STR(buf, "0.00036"); /* 9200 nm = 0.000362 in */
}

/* ---- 14. HOLD / ZERO actions and button blanking ---------------------------------------------- */
static void test_cap_buttons(void)
{
    meas_capture_t c;
    od_t p = {.D = 20 * MM, .l = 7.8 * MM, .th_deg = 0.5, .f = 0.5, .secs = 3.0};
    lcg_seed(13);
    tr_reset(&s_tr, 300.0);
    int rock_n, first = gen_od(&s_tr, &p, &rock_n);
    cap_new(&c, MEAS_CAP_SWEEP, MEAS_SWEEP_AUTO, false);
    evlog_t e = {0};
    CHECK_EQ_INT(meas_cap_hold_press(&c), MEAS_CAP_HOLD_MANUAL); /* nothing yet: a plain hold */
    feed(&c, &s_tr, 0, first + 150, &e);
    meas_cap_result_t r;
    meas_cap_result(&c, &r);
    CHECK_EQ_INT(r.state, MEAS_CAPST_RUN);
    CHECK_EQ_INT(meas_cap_hold_press(&c), MEAS_CAP_HOLD_FREEZE);
    meas_cap_result(&c, &r);
    CHECK_EQ_INT(r.state, MEAS_CAPST_DONE);
    CHECK_EQ_INT(meas_cap_hold_press(&c), MEAS_CAP_HOLD_REARM);
    meas_cap_result(&c, &r);
    CHECK_EQ_INT(r.state, MEAS_CAPST_WAIT);
    /* ZERO (reset) mid-capture: back to waiting, nothing frozen, needs a move */
    cap_new(&c, MEAS_CAP_SWEEP, MEAS_SWEEP_AUTO, false);
    evlog_t f = {0};
    feed(&c, &s_tr, 0, first + 150, &f);
    meas_cap_reset(&c);
    feed(&c, &s_tr, first + 150, first + rock_n, &f);
    meas_cap_result(&c, &r);
    CHECK_EQ_INT(r.state, MEAS_CAPST_WAIT);
    CHECK_EQ_INT(f.contact, 1);
    /* SETTLE: HOLD while timing freezes the window so far; while waiting it is a manual hold */
    cap_new(&c, MEAS_CAP_SETTLE, MEAS_SWEEP_AUTO, false);
    tr_reset(&s_tr2, 0.0);
    tr_rest(&s_tr2, 0, 10);
    tr_move(&s_tr2, 7 * MM, 50);
    tr_rest(&s_tr2, 7 * MM, 30);
    evlog_t g = {0};
    feed(&c, &s_tr2, 0, s_tr2.n, &g);
    CHECK_EQ_INT(meas_cap_hold_press(&c), MEAS_CAP_HOLD_FREEZE);
    meas_cap_result(&c, &r);
    CHECK_EQ_INT(r.state, MEAS_CAPST_DONE);
    CHECK_EQ_INT(r.value_nm, 7000000);

    /* blanking: pressing a button pushes the reading 30 um down (the slider pads lift) from 50 ms
     * before the debounced edge until 100 ms after release; that never reaches the MIN */
    s_tr2 = s_tr;
    int press = first + 200;
    for (int i = press - 4; i < press + 30; i++) s_tr2.x[i] -= 30000;
    cap_new(&c, MEAS_CAP_SWEEP, MEAS_SWEEP_AUTO, false);
    evlog_t h = {0};
    feed(&c, &s_tr2, 0, press, &h);
    meas_cap_button(&c, true, s_t0 + (uint32_t)press * 10u, 50, 100);
    feed(&c, &s_tr2, press, press + 20, &h);
    meas_cap_button(&c, false, s_t0 + (uint32_t)(press + 20) * 10u, 50, 100);
    feed(&c, &s_tr2, press + 20, s_tr2.n, &h);
    CHECK_EQ_INT(h.done, 1);
    CHECK(h.last.value_nm - p.D >= -LSB_NM / 2 && h.last.value_nm - p.D <= cusp_bound_nm(&p, 2) + 1 * UM);
    /* without the blanking the dip would have been the minimum */
    cap_new(&c, MEAS_CAP_SWEEP, MEAS_SWEEP_AUTO, false);
    evlog_t k = {0};
    feed(&c, &s_tr2, 0, s_tr2.n, &k);
    CHECK(k.last.value_nm < p.D - 20 * UM);

    /* set_mode refuses SET (reserved) and bad values */
    CHECK(!meas_cap_set_mode(&c, MEAS_CAP_SET, MEAS_SWEEP_AUTO));
    CHECK(!meas_cap_set_mode(&c, MEAS_CAP_SWEEP, (meas_sweep_sel_t)3));
    CHECK_EQ_INT(c.mode, MEAS_CAP_SWEEP);
    CHECK(meas_cap_set_mode(&c, MEAS_CAP_LIVE, MEAS_SWEEP_MAX));
    meas_cap_result(&c, &r);
    CHECK_EQ_INT(r.state, MEAS_CAPST_IDLE);
    CHECK_EQ_INT(meas_cap_update(&c, 5, true, 0), MEAS_CAPEV_NONE);
}

/* ---- the ms clock wraps mid-capture ------------------------------------------------------------- */
static void test_cap_wrap(void)
{
    meas_capture_t c;
    od_t p = {.D = 20 * MM, .l = 7.8 * MM, .th_deg = 0.5, .f = 0.5, .secs = 3.0};
    lcg_seed(14);
    tr_reset(&s_tr, 300.0);
    int rock_n;
    gen_od(&s_tr, &p, &rock_n);
    cap_new(&c, MEAS_CAP_SWEEP, MEAS_SWEEP_AUTO, false);
    evlog_t e = {0};
    feed(&c, &s_tr, 0, s_tr.n, &e);
    uint32_t saved = s_t0;
    s_t0 = 0xFFFFFFFFu - 2000u;
    cap_new(&c, MEAS_CAP_SWEEP, MEAS_SWEEP_AUTO, true);
    evlog_t f = {0};
    feed(&c, &s_tr, 0, s_tr.n, &f);
    s_t0 = saved;
    CHECK_EQ_INT(f.done, 1);
    CHECK(f.last.value_nm <= e.last.value_nm);
    CHECK(f.last.value_nm >= p.D - 3 * UM);
}

/* ==== adversarial review (2026-11-07) =========================================================== */

/* The usual way onto an OD: open the jaws from nearly closed, hover over the part while lining it up,
 * close onto it, rock, open to release. With the hover less than the gate (1 mm) above the part, the
 * hover and the contact are one run, approached by OPENING, and the lift-off (opening) is in the
 * run's own approach direction: the old pause rule discarded the measurement, even with MIN forced. */
static int gen_hover_od(trace_t *t, const od_t *p, double hover_nm, int *rock_n)
{
    tr_rest(t, 2 * MM, 50);
    tr_move(t, p->D + hover_nm, 20);
    tr_rest(t, p->D + hover_nm, 50); /* 0.5 s lining up */
    tr_move(t, od_x(p, 0), 5);
    int first = t->n;
    int n = (int)lround(p->secs / DT_S);
    for (int i = 0; i < n; i++) tr_add(t, od_x(p, i * DT_S));
    *rock_n = n;
    tr_move(t, tr_last(t) + 3 * MM, 20);
    tr_rest(t, tr_last(t), 50);
    return first;
}

static void test_adv_hover_od(void)
{
    od_t p = {.D = 20 * MM, .l = 7.8 * MM, .th_deg = 0.5, .f = 0.5, .secs = 3.0};
    const double hovers[] = {0.4 * MM, 0.7 * MM, 0.95 * MM, 2 * MM};
    for (int h = 0; h < 4; h++) {
        for (int s = 0; s < 2; s++) {
            meas_capture_t c;
            lcg_seed(21);
            tr_reset(&s_tr, 300.0);
            int rock_n;
            gen_hover_od(&s_tr, &p, hovers[h], &rock_n);
            cap_new(&c, MEAS_CAP_SWEEP, s ? MEAS_SWEEP_MIN : MEAS_SWEEP_AUTO, false);
            evlog_t e = {0};
            feed(&c, &s_tr, 0, s_tr.n, &e);
            meas_cap_result_t r;
            meas_cap_result(&c, &r);
            CHECK_EQ_INT(r.state, MEAS_CAPST_DONE);
            CHECK_EQ_INT(r.which, -1);
            double err = r.value_nm - p.D;
            if (!(err >= -LSB_NM / 2 && err <= cusp_bound_nm(&p, 2) + 1 * UM)) {
                printf("    (hover %.2f mm, %s: state %d, MIN - D = %.0f nm)\n", hovers[h] / MM, s ? "MIN" : "AUTO",
                       (int)r.state, err);
            }
            CHECK(err >= -LSB_NM / 2 && err <= cusp_bound_nm(&p, 2) + 1 * UM);
        }
    }
}

/* The mirror for a bore: the jaws come down from a larger size, hover with the inside jaws closed below
 * the bore, then open onto it (within the gate), sweep, and close to withdraw. */
static void test_adv_hover_id(void)
{
    double D = 12 * MM;
    const double hovers[] = {0.4 * MM, 0.7 * MM, 0.95 * MM, 2 * MM};
    for (int h = 0; h < 4; h++) {
        for (int s = 0; s < 2; s++) {
            if (h == 3 && s == 0) {
                continue; /* AUTO with a hover outside the gate: the documented AUTO limitation (bores: MAX) */
            }
            meas_capture_t c;
            lcg_seed(22);
            tr_reset(&s_tr, 300.0);
            tr_rest(&s_tr, D + 3 * MM, 50);
            tr_move(&s_tr, D - hovers[h], 20);
            tr_rest(&s_tr, D - hovers[h], 50);
            tr_move(&s_tr, id_x(D, 1 * MM, 0.5, 0), 5);
            for (int i = 0; i < 300; i++) tr_add(&s_tr, id_x(D, 1 * MM, 0.5, i * DT_S));
            tr_move(&s_tr, tr_last(&s_tr) - 3 * MM, 20);
            tr_rest(&s_tr, tr_last(&s_tr), 50);
            cap_new(&c, MEAS_CAP_SWEEP, s ? MEAS_SWEEP_MAX : MEAS_SWEEP_AUTO, false);
            evlog_t e = {0};
            feed(&c, &s_tr, 0, s_tr.n, &e);
            meas_cap_result_t r;
            meas_cap_result(&c, &r);
            CHECK_EQ_INT(r.state, MEAS_CAPST_DONE);
            CHECK_EQ_INT(r.which, 1);
            if (fabs(r.value_nm - D) > 2 * UM) {
                printf("    (bore hover %.2f mm, %s: state %d, MAX - D = %.0f nm)\n", hovers[h] / MM, s ? "MAX" : "AUTO",
                       (int)r.state, r.value_nm - D);
            }
            CHECK(fabs(r.value_nm - D) <= 2 * UM);
        }
    }
}

/* A capture that ends moving on in its own approach direction with no excursion the other way is still a
 * pause (the builder's rule), also after the fix above: an air pause while closing onto a part 2 mm
 * further down, and an OD rocked +-1.5 deg that is then slid off axially while the jaws keep closing. */
static void test_adv_pause_kept(void)
{
    meas_capture_t c;
    od_t p = {.D = 20 * MM, .l = 7.8 * MM, .th_deg = 1.5, .f = 0.5, .secs = 3.0};
    lcg_seed(23);
    tr_reset(&s_tr, 300.0);
    tr_rest(&s_tr, 30 * MM, 50);
    tr_move(&s_tr, 22 * MM, 20);
    tr_rest(&s_tr, 22 * MM, 60); /* the pause in the air */
    tr_move(&s_tr, od_x(&p, 0), 20);
    int rock_first = s_tr.n;
    for (int i = 0; i < 300; i++) tr_add(&s_tr, od_x(&p, i * DT_S));
    tr_move(&s_tr, tr_last(&s_tr) + 3 * MM, 20);
    tr_rest(&s_tr, tr_last(&s_tr), 50);
    cap_new(&c, MEAS_CAP_SWEEP, MEAS_SWEEP_AUTO, false);
    evlog_t e = {0};
    feed(&c, &s_tr, 0, s_tr.n, &e);
    CHECK_EQ_INT(e.discard, 1);
    CHECK_EQ_INT(e.done, 1);
    CHECK(e.last.value_nm - p.D <= cusp_bound_nm(&p, 2) + 1 * UM);
    /* slid off axially, the jaws closing on: discarded, not frozen as a MAX */
    tr_reset(&s_tr, 300.0);
    tr_rest(&s_tr, 30 * MM, 50);
    tr_move(&s_tr, od_x(&p, 0), 20);
    for (int i = 0; i < 300; i++) tr_add(&s_tr, od_x(&p, i * DT_S));
    tr_move(&s_tr, tr_last(&s_tr) - 3 * MM, 20);
    tr_rest(&s_tr, tr_last(&s_tr), 50);
    cap_new(&c, MEAS_CAP_SWEEP, MEAS_SWEEP_AUTO, false);
    evlog_t f = {0};
    feed(&c, &s_tr, 0, s_tr.n, &f);
    CHECK_EQ_INT(f.done, 0);
    CHECK_EQ_INT(f.discard, 1);
    (void)rock_first;
}

/* A background candidate (the caliper put down open after an OD, an air pause) must never replace the
 * shown result through the 10-minute safety freeze; the user is still reading it. */
static void test_adv_background_max_run(void)
{
    meas_capture_t c;
    od_t p = {.D = 20 * MM, .l = 7.8 * MM, .th_deg = 0.5, .f = 0.5, .secs = 3.0};
    lcg_seed(24);
    tr_reset(&s_tr, 300.0);
    int rock_n;
    gen_od(&s_tr, &p, &rock_n);
    cap_new(&c, MEAS_CAP_SWEEP, MEAS_SWEEP_AUTO, false);
    evlog_t e = {0};
    feed(&c, &s_tr, 0, s_tr.n, &e);
    CHECK_EQ_INT(e.done, 1);
    int32_t shown = e.last.value_nm, rest = s_tr.x[s_tr.n - 1];
    uint32_t t = s_t0 + (uint32_t)s_tr.n * 10u;
    int done = 0;
    for (int i = 0; i < 61000; i++) { /* 610 s at rest */
        if (meas_cap_update(&c, rest + ((i & 7) == 0 ? 488 : 0), true, t) == MEAS_CAPEV_DONE) {
            done++;
        }
        t += 10u;
    }
    meas_cap_result_t r;
    meas_cap_result(&c, &r);
    CHECK_EQ_INT(done, 0);
    CHECK_EQ_INT(r.state, MEAS_CAPST_DONE);
    CHECK_EQ_INT(r.value_nm, shown);
    /* freezing a hidden candidate by hand (the public freeze) leaves the shown result too */
    meas_cap_freeze(&c);
    meas_cap_result(&c, &r);
    CHECK_EQ_INT(r.value_nm, shown);
}

/* A confirmed count-slip correction (sensor_mag re-aligns the count to the SSI) steps the reading:
 * the note says a slip aborts a running capture, and a SETTLE window restarts. */
static void test_adv_slip(void)
{
    meas_capture_t c;
    od_t p = {.D = 20 * MM, .l = 7.8 * MM, .th_deg = 0.5, .f = 0.5, .secs = 3.0};
    lcg_seed(25);
    tr_reset(&s_tr, 300.0);
    int rock_n, first = gen_od(&s_tr, &p, &rock_n);
    for (int i = first + 120; i < first + rock_n; i++) s_tr.x[i] -= 3906; /* a 2-count correction */
    cap_new(&c, MEAS_CAP_SWEEP, MEAS_SWEEP_AUTO, false);
    evlog_t e = {0};
    feed(&c, &s_tr, 0, first + 120, &e);
    CHECK_EQ_INT(meas_cap_slip(&c), MEAS_CAPEV_ABORT);
    meas_cap_result_t r;
    meas_cap_result(&c, &r);
    CHECK_EQ_INT(r.state, MEAS_CAPST_ABORT);
    feed(&c, &s_tr, first + 120, first + rock_n, &e);
    CHECK_EQ_INT(e.done, 0); /* still on the part: it stays aborted */
    meas_cap_result(&c, &r);
    CHECK_EQ_INT(r.state, MEAS_CAPST_ABORT);
    /* nothing running: nothing to drop */
    cap_new(&c, MEAS_CAP_SWEEP, MEAS_SWEEP_AUTO, false);
    CHECK_EQ_INT(meas_cap_slip(&c), MEAS_CAPEV_NONE);
    /* SETTLE: the still window restarts at the slip */
    cap_new(&c, MEAS_CAP_SETTLE, MEAS_SWEEP_AUTO, false);
    tr_reset(&s_tr, 0.0);
    tr_rest(&s_tr, 0, 10);
    tr_move(&s_tr, 5 * MM, 50);
    int s0 = s_tr.n;
    tr_rest(&s_tr, 5 * MM, 200);
    evlog_t f = {0};
    feed(&c, &s_tr, 0, s0 + 50, &f);
    CHECK_EQ_INT(meas_cap_slip(&c), MEAS_CAPEV_NONE);
    feed(&c, &s_tr, s0 + 50, s_tr.n, &f);
    CHECK_EQ_INT(f.done, 1);
    CHECK_EQ_INT(f.done_i, s0 + 50 + 80 - 1);
}

/* The accumulator with values far apart (an ok glitch in a SETTLE window can be anything): no signed
 * overflow (UBSan), the spread saturates instead of wrapping. */
static void test_adv_acc_extremes(void)
{
    meas_acc_t a;
    meas_acc_reset(&a);
    meas_acc_add(&a, INT32_MIN);
    meas_acc_add(&a, INT32_MAX);
    meas_acc_add(&a, INT32_MIN);
    CHECK_EQ_INT(a.n, 3);
    CHECK_EQ_INT(meas_acc_range_nm(&a), INT32_MAX);
    CHECK_EQ_INT(meas_acc_sd_nm(&a), INT32_MAX); /* the true sd is 2.48e9: saturated */
    CHECK(meas_acc_mean_nm(&a) < -715000000 && meas_acc_mean_nm(&a) > -716000000);
    /* SETTLE window at -2.1 km... (the int32 edge) with one tolerated glitch at the other edge */
    meas_capture_t c;
    cap_new(&c, MEAS_CAP_SETTLE, MEAS_SWEEP_AUTO, false);
    uint32_t t = 0;
    for (int i = 0; i < 20; i++, t += 10) meas_cap_update(&c, -2000000000 + i * 100000, true, t);
    int fired = 0;
    for (int i = 0; i < 100; i++, t += 10) {
        int32_t x = i == 50 ? 2140000000 : -1998000000;
        fired += meas_cap_update(&c, x, true, t) == MEAS_CAPEV_DONE;
    }
    CHECK_EQ_INT(fired, 1);
    meas_cap_result_t r;
    meas_cap_result(&c, &r);
    CHECK_EQ_INT(r.value_nm, -1998000000);
}

/* The whole OD trace near both int32 ends: every result shifts by exactly the offset. */
static void test_adv_int32_edges(void)
{
    meas_capture_t c;
    od_t p = {.D = 20 * MM, .l = 7.8 * MM, .th_deg = 0.5, .f = 0.5, .secs = 3.0};
    lcg_seed(26);
    tr_reset(&s_tr, 300.0);
    int rock_n;
    gen_od(&s_tr, &p, &rock_n);
    cap_new(&c, MEAS_CAP_SWEEP, MEAS_SWEEP_AUTO, true);
    evlog_t e = {0};
    feed(&c, &s_tr, 0, s_tr.n, &e);
    CHECK_EQ_INT(e.done, 1);
    const int32_t offs[2] = {2147483647 - 24000000, -2147483647 + 1000000};
    for (int k = 0; k < 2; k++) {
        s_tr2 = s_tr;
        for (int i = 0; i < s_tr2.n; i++) s_tr2.x[i] = (int32_t)((int64_t)s_tr2.x[i] + offs[k] - (k ? 0 : 0));
        cap_new(&c, MEAS_CAP_SWEEP, MEAS_SWEEP_AUTO, true);
        evlog_t f = {0};
        feed(&c, &s_tr2, 0, s_tr2.n, &f);
        CHECK_EQ_INT(f.done, 1);
        CHECK_EQ_INT((int64_t)f.last.value_nm - offs[k], e.last.value_nm);
        CHECK_EQ_INT((int64_t)f.last.other_nm - offs[k], e.last.other_nm);
        CHECK_EQ_INT(f.last.range_nm, e.last.range_nm);
        CHECK_EQ_INT(f.last.sd_nm, e.last.sd_nm);
    }
}

/* A +50 um one-sample glitch exactly at the cusp sample: persistence (P = 2) drops the pairs that
 * contain it, so the MIN comes from samples up to 2 away: at most 2.5 samples of slope high. */
static void test_adv_spike_up_at_cusp(void)
{
    od_t p = {.D = 20 * MM, .l = 7.8 * MM, .th_deg = 0.5, .f = 0.5, .secs = 3.0, .phase = 0.0};
    double slope = cusp_bound_nm(&p, 2); /* l theta' dt at P = 2 is one sample of slope */
    for (int k = 0; k < 2; k++) {
        meas_capture_t c;
        lcg_seed(27);
        tr_reset(&s_tr, 0.0); /* no jitter: the cusp sample is exactly at D */
        int rock_n, first = gen_od(&s_tr, &p, &rock_n);
        int cusp = first + 100; /* theta = 0 at t = 1 s */
        CHECK_EQ_INT(s_tr.x[cusp], quant(p.D));
        if (k) s_tr.x[cusp] += 50000;
        cap_new(&c, MEAS_CAP_SWEEP, MEAS_SWEEP_MIN, false);
        evlog_t e = {0};
        feed(&c, &s_tr, 0, s_tr.n, &e);
        CHECK_EQ_INT(e.done, 1);
        double err = e.last.value_nm - p.D;
        CHECK(err >= -LSB_NM / 2 && err <= (k ? 2.5 : 1.0) * slope + LSB_NM);
    }
}

/* A small bore swept wide: the chord leaves the 1 mm gate (a false lift-off). The MAX must survive. */
static void test_adv_small_bore_wide_sweep(void)
{
    meas_capture_t c;
    double D = 6 * MM;
    lcg_seed(28);
    tr_reset(&s_tr, 300.0);
    tr_rest(&s_tr, D - 3 * MM, 50);
    tr_move(&s_tr, id_x(D, 1.8 * MM, 0.25, 0), 20); /* 2.8 mm/s across: the centre is still a stop */
    for (int i = 0; i < 800; i++) tr_add(&s_tr, id_x(D, 1.8 * MM, 0.25, i * DT_S));
    tr_move(&s_tr, tr_last(&s_tr) - 3 * MM, 20);
    tr_rest(&s_tr, tr_last(&s_tr), 50);
    for (int s = 0; s < 2; s++) {
        cap_new(&c, MEAS_CAP_SWEEP, s ? MEAS_SWEEP_MAX : MEAS_SWEEP_AUTO, false);
        evlog_t e = {0};
        feed(&c, &s_tr, 0, s_tr.n, &e);
        meas_cap_result_t r;
        meas_cap_result(&c, &r);
        CHECK_EQ_INT(r.state, MEAS_CAPST_DONE);
        CHECK_EQ_INT(r.which, 1);
        CHECK(fabs(r.value_nm - D) <= 2 * UM);
    }
}

/* A short release (opening only 1.2 mm off an OD, closing 1.2 mm out of a bore, then holding still to
 * read): still a lift-off, frozen resume_ms after the exit, with the right extreme; then the next part. */
static void test_adv_short_release(void)
{
    meas_capture_t c;
    meas_cap_cfg_t cfg;
    meas_cap_cfg_default(&cfg);
    od_t p = {.D = 20 * MM, .l = 7.8 * MM, .th_deg = 0.5, .f = 0.5, .secs = 3.0};
    lcg_seed(30);
    tr_reset(&s_tr, 300.0);
    tr_rest(&s_tr, 25 * MM, 50);
    tr_move(&s_tr, od_x(&p, 0), 20);
    for (int i = 0; i < 300; i++) tr_add(&s_tr, od_x(&p, i * DT_S));
    tr_move(&s_tr, tr_last(&s_tr) + 1.2 * MM, 10);
    int out = s_tr.n;
    tr_rest(&s_tr, tr_last(&s_tr), 200);
    od_t q = p;
    q.D = 19.5 * MM; /* the next part, 0.5 mm smaller */
    tr_move(&s_tr, od_x(&q, 0), 10);
    for (int i = 0; i < 300; i++) tr_add(&s_tr, od_x(&q, i * DT_S));
    tr_move(&s_tr, tr_last(&s_tr) + 3 * MM, 20);
    tr_rest(&s_tr, tr_last(&s_tr), 50);
    cap_new(&c, MEAS_CAP_SWEEP, MEAS_SWEEP_AUTO, false);
    evlog_t e = {0};
    feed(&c, &s_tr, 0, out + 150, &e);
    CHECK_EQ_INT(e.done, 1);
    CHECK(e.done_i <= out + (int)(cfg.resume_ms / cfg.sample_ms) + 5);
    CHECK(e.last.value_nm - p.D <= cusp_bound_nm(&p, 2) + 1 * UM);
    CHECK(e.last.range_nm < 80 * UM); /* the slow release is not in R */
    feed(&c, &s_tr, out + 150, s_tr.n, &e);
    CHECK_EQ_INT(e.done, 2);
    CHECK(e.last.value_nm - q.D <= cusp_bound_nm(&q, 2) + 1 * UM && e.last.value_nm - q.D >= -LSB_NM / 2);
    /* a bore, released by closing 1.2 mm */
    double D = 12 * MM;
    tr_reset(&s_tr, 300.0);
    tr_rest(&s_tr, D - 3 * MM, 50);
    tr_move(&s_tr, id_x(D, 1 * MM, 0.5, 0), 20);
    for (int i = 0; i < 400; i++) tr_add(&s_tr, id_x(D, 1 * MM, 0.5, i * DT_S));
    tr_move(&s_tr, tr_last(&s_tr) - 1.2 * MM, 10);
    tr_rest(&s_tr, tr_last(&s_tr), 150);
    cap_new(&c, MEAS_CAP_SWEEP, MEAS_SWEEP_AUTO, false);
    evlog_t f = {0};
    feed(&c, &s_tr, 0, s_tr.n, &f);
    CHECK_EQ_INT(f.done, 1);
    CHECK_EQ_INT(f.last.which, 1);
    CHECK(fabs(f.last.value_nm - D) <= 2 * UM);
}

/* What the display shows while in contact equals what HOLD would freeze at that instant. */
static void test_adv_view_equals_freeze(void)
{
    od_t p = {.D = 20 * MM, .l = 7.8 * MM, .th_deg = 1.0, .f = 1.0, .secs = 3.0};
    lcg_seed(29);
    tr_reset(&s_tr, 300.0);
    int rock_n, first = gen_od(&s_tr, &p, &rock_n);
    for (int refine = 0; refine < 2; refine++) {
        static meas_capture_t c, d;
        cap_new(&c, MEAS_CAP_SWEEP, MEAS_SWEEP_AUTO, refine != 0);
        evlog_t e = {0};
        int bad = 0;
        for (int i = 0; i < first + rock_n; i++) {
            feed(&c, &s_tr, i, i + 1, &e);
            meas_cap_result_t r, q;
            meas_cap_result(&c, &r);
            if (r.state != MEAS_CAPST_RUN || (i % 7) != 0) continue;
            d = c;
            meas_cap_freeze(&d);
            meas_cap_result(&d, &q);
            bad += q.state != MEAS_CAPST_DONE || q.value_nm != r.value_nm || q.other_nm != r.other_nm || q.n != r.n;
        }
        CHECK_EQ_INT(bad, 0);
    }
}

void capture_tests(void);
void capture_tests(void)
{
    RUN(test_adv_hover_od);
    RUN(test_adv_hover_id);
    RUN(test_adv_pause_kept);
    RUN(test_adv_background_max_run);
    RUN(test_adv_slip);
    RUN(test_adv_acc_extremes);
    RUN(test_adv_int32_edges);
    RUN(test_adv_spike_up_at_cusp);
    RUN(test_adv_small_bore_wide_sweep);
    RUN(test_adv_short_release);
    RUN(test_adv_view_equals_freeze);
    RUN(test_cap_od_rock);
    RUN(test_cap_fast_cusp);
    RUN(test_cap_id_sweep);
    RUN(test_cap_depth);
    RUN(test_cap_spike);
    RUN(test_cap_sensor);
    RUN(test_cap_zero_cross);
    RUN(test_cap_gate);
    RUN(test_cap_rearm);
    RUN(test_cap_settle);
    RUN(test_cap_acc);
    RUN(test_cap_units);
    RUN(test_cap_buttons);
    RUN(test_cap_wrap);
}
