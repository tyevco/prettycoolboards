/*
 * Log records (16 bytes, the same layout on flash and in the GATT LOG stream) and the
 * ring-log index arithmetic. Portable C.
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define LOGREC_SIZE    16
#define LOGREC_END_SEQ 0xFFFFFFFFu /* stream terminator; never assigned to a reading */

typedef struct {
    uint32_t seq;      /* 1, 2, 3, ... (0 = empty slot) */
    uint32_t unix_s;   /* 0 if the clock was never set */
    int32_t value_nm;  /* zeroed magnetic value as shown (held value if holding) */
    uint8_t unit;      /* 0 mm, 1 inch: the unit shown when it was recorded (byte 12 bit 0) */
    uint8_t flags;     /* CALIPER_FLAG_* bits (HOLD, TOL_PASS, TOL_FAIL, SENSOR_ERR, ...) */
    uint16_t profile_id;
    uint8_t kind;      /* CALIPER_LOG_KIND_* (byte 12 bits 1..3); 0 in records stored before it existed */
    uint8_t set_bits;  /* byte 12 bits 4..5 (CALIPER_LOG_SET_*), reserved: 0 */
} logrec_t;

/* Byte 12 = unit | kind << 1 | set_bits (caliper_gatt.h CALIPER_LOG_*). The flash keeps the whole
 * byte; the LOG stream masks it for the plain LOG_READ (gatt_log_record_pack). */
void logrec_pack(const logrec_t *r, uint8_t out[LOGREC_SIZE]);
void logrec_unpack(const uint8_t in[LOGREC_SIZE], logrec_t *r);
const char *logrec_kind_str(uint8_t kind); /* "", "settle", "min", "max" (CSV / text) */
logrec_t logrec_end_marker(void);

/*
 * Ring of `capacity` slots. Sequence numbers increase forever; seq s lives in slot
 * (s - 1) % capacity. A clear does not reset the numbering: it moves base_seq up to next_seq,
 * so an app that synchronises incrementally (LOG_READ from its last seq + 1) never sees a
 * reused number.
 */
typedef struct {
    uint32_t capacity;
    uint32_t base_seq; /* the first seq that is valid (>= 1) */
    uint32_t next_seq; /* the seq the next append gets */
} ring_t;

void ring_init(ring_t *r, uint32_t capacity, uint32_t base_seq);
uint32_t ring_slot(const ring_t *r, uint32_t seq);
uint32_t ring_oldest(const ring_t *r);  /* oldest seq still stored (== next_seq if empty) */
uint32_t ring_count(const ring_t *r);
bool ring_contains(const ring_t *r, uint32_t seq);
uint32_t ring_append(ring_t *r);        /* returns the seq assigned */
void ring_clear(ring_t *r);
/* First seq >= from that is stored, or next_seq if none (from 0 means "from the oldest"). */
uint32_t ring_first_from(const ring_t *r, uint32_t from);
/* Rebuild next_seq after boot from the largest valid seq found in the slots (0 if none). */
void ring_restore(ring_t *r, uint32_t capacity, uint32_t base_seq, uint32_t max_seq_found);

#ifdef __cplusplus
}
#endif
