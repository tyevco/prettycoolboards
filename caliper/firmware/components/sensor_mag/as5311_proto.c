/* AS5311 SSI frame and count/position bookkeeping. Portable C. */
#include "as5311_proto.h"

static int parity18(uint32_t v)
{
    v &= 0x3FFFFu;
    int p = 0;
    while (v) {
        p ^= (int)(v & 1u);
        v >>= 1;
    }
    return p;
}

void as5311_decode(uint32_t raw, as5311_frame_t *f)
{
    raw &= 0x3FFFFu;
    f->pos = (uint16_t)((raw >> 6) & 0x0FFFu);
    f->ocf = (raw >> 5) & 1u;
    f->cof = (raw >> 4) & 1u;
    f->lin = (raw >> 3) & 1u;
    f->mag_inc = (raw >> 2) & 1u;
    f->mag_dec = (raw >> 1) & 1u;
    f->parity_ok = parity18(raw) == 0; /* PAR = even parity of bits 1..17: frame parity even */
}

uint32_t as5311_encode(const as5311_frame_t *f)
{
    uint32_t raw = ((uint32_t)(f->pos & 0x0FFFu) << 6) | ((uint32_t)f->ocf << 5) | ((uint32_t)f->cof << 4) |
                   ((uint32_t)f->lin << 3) | ((uint32_t)f->mag_inc << 2) | ((uint32_t)f->mag_dec << 1);
    raw |= (uint32_t)parity18(raw);
    return raw;
}

bool as5311_frame_valid(const as5311_frame_t *f)
{
    return f->parity_ok && f->ocf && !f->cof;
}

as5311_field_t as5311_field(const as5311_frame_t *f)
{
    if (f->mag_inc && f->mag_dec) {
        return f->lin ? AS5311_FIELD_BAD : AS5311_FIELD_MARGINAL;
    }
    return AS5311_FIELD_OK;
}

int32_t as5311_wrap_diff(uint16_t a, uint16_t b)
{
    int32_t d = ((int32_t)a - (int32_t)b) & (AS5311_SSI_STEPS - 1);
    return d >= AS5311_SSI_STEPS / 2 ? d - AS5311_SSI_STEPS : d;
}

uint16_t as5311_count_phase(int64_t count, int dir)
{
    int64_t c = dir < 0 ? -count : count;
    /* two's complement mask = floor mod */
    return (uint16_t)((c & (AS5311_COUNTS_PER_POLE - 1)) * AS5311_LSB_PER_COUNT);
}

int32_t as5311_lsb_to_counts(int32_t lsb)
{
    const int32_t h = AS5311_LSB_PER_COUNT / 2;
    return lsb >= 0 ? (lsb + h) / AS5311_LSB_PER_COUNT : -((-lsb + h) / AS5311_LSB_PER_COUNT);
}

void as5311_slip_init(as5311_slip_t *s, int dir)
{
    s->locked = false;
    s->offset = 0;
    s->dir = dir < 0 ? -1 : 1;
}

void as5311_slip_lock(as5311_slip_t *s, int64_t count, uint16_t ssi_pos)
{
    s->offset = as5311_wrap_diff(ssi_pos, as5311_count_phase(count, s->dir));
    s->locked = true;
}

int32_t as5311_slip_residual(const as5311_slip_t *s, int64_t count, uint16_t ssi_pos)
{
    if (!s->locked) {
        return 0;
    }
    uint16_t expect =
        (uint16_t)(((int32_t)as5311_count_phase(count, s->dir) + s->offset) & (AS5311_SSI_STEPS - 1));
    return as5311_wrap_diff(ssi_pos, expect);
}

int32_t as5311_slip_correction(const as5311_slip_t *s, int32_t residual_lsb)
{
    /* ssi = LSB_PER_COUNT * dir * count + offset, so a count short by k gives a residual of 4 * dir * k */
    int32_t k = as5311_lsb_to_counts(residual_lsb);
    return s->dir < 0 ? -k : k;
}

int64_t as5311_recover_count(int64_t stored_count, uint16_t ssi_stored, uint16_t ssi_now, int dir)
{
    int32_t k = as5311_lsb_to_counts(as5311_wrap_diff(ssi_now, ssi_stored));
    return stored_count + (dir < 0 ? -k : k);
}

/* ---- fine position (SPEC D1) ------------------------------------------------------------- */

as5311_fine_t as5311_fine_combine(const as5311_slip_t *s, int64_t count, bool ssi_ok, uint16_t ssi_pos)
{
    as5311_fine_t f = {.lsb = count * AS5311_LSB_PER_COUNT, .residual = 0, .status = AS5311_FINE_COARSE};
    if (!s->locked || !ssi_ok) {
        return f;
    }
    int32_t r = as5311_slip_residual(s, count, ssi_pos);
    f.residual = r;
    if (r > AS5311_FINE_TOL_LSB || r < -AS5311_FINE_TOL_LSB) {
        f.status = AS5311_FINE_MISMATCH; /* count alone */
        return f;
    }
    f.lsb += s->dir < 0 ? -r : r;
    f.status = AS5311_FINE_OK;
    return f;
}

void as5311_mismatch_init(as5311_mismatch_t *m)
{
    m->n = 0;
    m->k = 0;
}

int32_t as5311_mismatch_update(as5311_mismatch_t *m, const as5311_slip_t *s, const as5311_fine_t *f)
{
    if (f->status == AS5311_FINE_COARSE) {
        return 0; /* no evidence either way */
    }
    if (f->status == AS5311_FINE_OK) {
        m->n = 0;
        return 0;
    }
    int32_t k = as5311_slip_correction(s, f->residual);
    /* the same slip, give or take one count of jitter at the rounding edge */
    if (m->n > 0 && (k - m->k > 1 || m->k - k > 1)) {
        m->n = 0;
    }
    m->k = k;
    if (++m->n >= AS5311_SLIP_CONFIRM) {
        m->n = 0;
        return k;
    }
    return 0;
}

/* ---- PCNT wrap-race filter ------------------------------------------------------------- */

void as5311_jump_init(as5311_jump_t *j)
{
    j->have = false;
    j->last = 0;
    j->rejects = 0;
}

bool as5311_jump_plausible(const as5311_jump_t *j, int64_t raw, int64_t max_step)
{
    int64_t d = raw - j->last;
    return !j->have || (d <= max_step && d >= -max_step);
}

bool as5311_jump_filter(as5311_jump_t *j, int64_t raw, int64_t max_step, int64_t *out)
{
    int64_t d = raw - j->last;
    if (!j->have || (d <= max_step && d >= -max_step) || ++j->rejects >= AS5311_JUMP_ACCEPT) {
        j->have = true;
        j->last = raw;
        j->rejects = 0;
        *out = raw;
        return true;
    }
    *out = j->last;
    return false;
}

/* ---- bring-up: SSI vs count cross-check ------------------------------------------------- */

void as5311_xcheck_init(as5311_xcheck_t *x)
{
    *x = (as5311_xcheck_t){0};
}

static int64_t abs64(int64_t v)
{
    return v < 0 ? -v : v;
}

void as5311_xcheck_feed(as5311_xcheck_t *x, int64_t count, uint16_t ssi_pos)
{
    ssi_pos &= AS5311_SSI_STEPS - 1;
    if (!x->have) {
        as5311_xcheck_init(x);
        x->have = true;
        x->count0 = count;
        x->ssi_last = ssi_pos;
        x->frames = 1;
        return;
    }
    int32_t step = as5311_wrap_diff(ssi_pos, x->ssi_last);
    int32_t at = (int32_t)x->ssi_last + step;
    if (at < 0 || at >= AS5311_SSI_STEPS) {
        x->crossings++;
    }
    x->ssi_last = ssi_pos;
    x->ssi_u += step;
    x->count_d = count - x->count0;
    x->travel += step < 0 ? -step : step;
    if ((step < 0 ? -step : step) > x->max_step) {
        x->max_step = step < 0 ? -step : step;
    }
    if (x->ssi_u < x->min_u) {
        x->min_u = x->ssi_u;
    }
    if (x->ssi_u > x->max_u) {
        x->max_u = x->ssi_u;
    }
    int64_t dp = abs64(x->ssi_u - AS5311_LSB_PER_COUNT * x->count_d);
    int64_t dm = abs64(x->ssi_u + AS5311_LSB_PER_COUNT * x->count_d);
    if (dp > x->dev_p_max) {
        x->dev_p_max = dp;
    }
    if (dm > x->dev_m_max) {
        x->dev_m_max = dm;
    }
    x->frames++;
}

as5311_xc_result_t as5311_xcheck_result(const as5311_xcheck_t *x)
{
    if (x->max_step > AS5311_XC_MAX_STEP) {
        return AS5311_XC_FAST;
    }
    if (!x->have || x->max_u - x->min_u < AS5311_XC_MIN_SPAN) {
        return AS5311_XC_SHORT;
    }
    if (x->dev_p_max <= AS5311_XC_TOL_LSB) {
        return AS5311_XC_OK;
    }
    if (x->dev_m_max <= AS5311_XC_TOL_LSB) {
        return AS5311_XC_INVERTED;
    }
    return AS5311_XC_MISMATCH;
}

const char *as5311_xcheck_str(as5311_xc_result_t r)
{
    switch (r) {
    case AS5311_XC_OK: return "count and SSI agree";
    case AS5311_XC_SHORT: return "moved less than 2 mm: move further";
    case AS5311_XC_FAST: return "moved too fast for the SSI unwrap: repeat slower";
    case AS5311_XC_INVERTED: return "count runs against the SSI: flip SSI_SIGN (sensor_mag.c)";
    case AS5311_XC_MISMATCH: return "count and SSI disagree: missed edges or a bad A/B/SSI line";
    }
    return "?";
}
