/* Log record pack/unpack and ring-log indexing. Portable C. */
#include "logrec.h"

#include <string.h>

#include "le_bytes.h"

void logrec_pack(const logrec_t *r, uint8_t out[LOGREC_SIZE])
{
    le_put_u32(out + 0, r->seq);
    le_put_u32(out + 4, r->unix_s);
    le_put_i32(out + 8, r->value_nm);
    out[12] = r->unit;
    out[13] = r->flags;
    le_put_u16(out + 14, r->profile_id);
}

void logrec_unpack(const uint8_t in[LOGREC_SIZE], logrec_t *r)
{
    r->seq = le_get_u32(in + 0);
    r->unix_s = le_get_u32(in + 4);
    r->value_nm = le_get_i32(in + 8);
    r->unit = in[12];
    r->flags = in[13];
    r->profile_id = le_get_u16(in + 14);
}

logrec_t logrec_end_marker(void)
{
    logrec_t r;
    memset(&r, 0, sizeof(r));
    r.seq = LOGREC_END_SEQ;
    return r;
}

void ring_init(ring_t *r, uint32_t capacity, uint32_t base_seq)
{
    r->capacity = capacity ? capacity : 1;
    r->base_seq = base_seq ? base_seq : 1;
    r->next_seq = r->base_seq;
}

uint32_t ring_slot(const ring_t *r, uint32_t seq)
{
    return (seq - 1u) % r->capacity;
}

uint32_t ring_oldest(const ring_t *r)
{
    uint32_t stored = r->next_seq - r->base_seq;
    if (stored > r->capacity) {
        return r->next_seq - r->capacity;
    }
    return r->base_seq;
}

uint32_t ring_count(const ring_t *r)
{
    return r->next_seq - ring_oldest(r);
}

bool ring_contains(const ring_t *r, uint32_t seq)
{
    return seq >= ring_oldest(r) && seq < r->next_seq;
}

uint32_t ring_append(ring_t *r)
{
    uint32_t s = r->next_seq;
    /* 4e9 readings is beyond the product's life; stop short of the terminator anyway. */
    if (r->next_seq < LOGREC_END_SEQ - 1u) {
        r->next_seq++;
    }
    return s;
}

void ring_clear(ring_t *r)
{
    r->base_seq = r->next_seq;
}

uint32_t ring_first_from(const ring_t *r, uint32_t from)
{
    uint32_t oldest = ring_oldest(r);
    if (from < oldest) {
        return oldest;
    }
    if (from > r->next_seq) {
        return r->next_seq;
    }
    return from;
}

void ring_restore(ring_t *r, uint32_t capacity, uint32_t base_seq, uint32_t max_seq_found)
{
    ring_init(r, capacity, base_seq);
    if (max_seq_found >= r->base_seq && max_seq_found != LOGREC_END_SEQ) {
        r->next_seq = max_seq_found + 1u;
    }
}
