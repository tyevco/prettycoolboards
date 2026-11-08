/* CSV export of log records and a portable UTC calendar conversion. Portable C. */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "logrec.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    int year, month, day, hour, min, sec;
} csv_civil_t;

/* Unix seconds -> UTC calendar (proleptic Gregorian, valid for all uint32 values). */
void csv_civil_from_unix(uint32_t t, csv_civil_t *c);

/* Header line, "\r\n" terminated. with_utc adds an ISO-8601 column. */
int csv_header(bool with_utc, char *buf, size_t n);

/* One record, e.g. "12,1762500000,2025-11-07T07:20:00Z,12.34,mm,HP,3,min\r\n".
 * kind (the last column, added with the capture modes): "" plain, "settle", "min" or "max" (a SWEEP
 * extreme); appended at the end so readers that take the first seven columns are unaffected.
 * The value is formatted in the record's unit with mm_decimals (settings "decimals").
 * flags column: H hold, P pass, F fail, E sensor error, Z zero lost (CALIPER_FLAG_REZERO: the value
 * is relative to an origin set after a sleep/reset, not to the user's zero); "" if none.
 * unix_s 0 -> empty time. Returns the length or -1 if buf is too small. */
int csv_line(const logrec_t *r, uint8_t mm_decimals, bool with_utc, char *buf, size_t n);

/* The longest line csv_line() can produce (with_utc, every field at its widest), CRLF included. */
#define CSV_LINE_MAX 104


/* Formats as many of the n records as fit, whole lines only, into buf (n_buf bytes, NUL-terminated).
 * *used gets the bytes written. Returns the number of records formatted; the caller flushes buf
 * and calls again with the rest. Always formats at least one record when n_buf > CSV_LINE_MAX. */
size_t csv_pack(const logrec_t *recs, size_t n, uint8_t mm_decimals, bool with_utc, char *buf, size_t n_buf,
                size_t *used);

#ifdef __cplusplus
}
#endif
