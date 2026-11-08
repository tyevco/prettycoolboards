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

/* One record, e.g. "12,1762500000,2025-11-07T07:20:00Z,12.34,mm,HP,3\r\n".
 * The value is formatted in the record's unit with mm_decimals (settings "decimals").
 * flags column: H hold, P pass, F fail, E sensor error ("" if none). unix_s 0 -> empty time.
 * Returns the length or -1 if buf is too small. */
int csv_line(const logrec_t *r, uint8_t mm_decimals, bool with_utc, char *buf, size_t n);

#ifdef __cplusplus
}
#endif
