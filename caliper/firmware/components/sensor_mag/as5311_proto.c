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
