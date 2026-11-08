/* CSV export. Portable C. */
#include "csv.h"

#include <stdio.h>

#include "caliper_gatt.h"
#include "measure.h"

void csv_civil_from_unix(uint32_t t, csv_civil_t *c)
{
    /* Howard Hinnant's civil_from_days */
    int64_t days = (int64_t)(t / 86400u);
    uint32_t rem = t % 86400u;
    c->hour = (int)(rem / 3600u);
    c->min = (int)((rem % 3600u) / 60u);
    c->sec = (int)(rem % 60u);
    int64_t z = days + 719468;
    int64_t era = (z >= 0 ? z : z - 146096) / 146097;
    int64_t doe = z - era * 146097;
    int64_t yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    int64_t y = yoe + era * 400;
    int64_t doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    int64_t mp = (5 * doy + 2) / 153;
    int64_t d = doy - (153 * mp + 2) / 5 + 1;
    int64_t m = mp < 10 ? mp + 3 : mp - 9;
    c->year = (int)(y + (m <= 2));
    c->month = (int)m;
    c->day = (int)d;
}

int csv_header(bool with_utc, char *buf, size_t n)
{
    int len = snprintf(buf, n, "%s", with_utc ? "seq,unix_s,utc,value,unit,flags,profile,kind\r\n"
                                              : "seq,unix_s,value,unit,flags,profile,kind\r\n");
    return (len < 0 || (size_t)len >= n) ? -1 : len;
}

int csv_line(const logrec_t *r, uint8_t mm_decimals, bool with_utc, char *buf, size_t n)
{
    meas_unit_t unit = r->unit == CALIPER_UNIT_INCH ? MEAS_UNIT_INCH : MEAS_UNIT_MM;
    meas_fmt_t fmt = meas_fmt_for(unit, mm_decimals);
    char val[16];
    if (meas_format(r->value_nm, &fmt, val, sizeof(val)) < 0) {
        return -1;
    }
    char flags[6];
    int fi = 0;
    if (r->flags & CALIPER_FLAG_HOLD) flags[fi++] = 'H';
    if (r->flags & CALIPER_FLAG_TOL_PASS) flags[fi++] = 'P';
    if (r->flags & CALIPER_FLAG_TOL_FAIL) flags[fi++] = 'F';
    if (r->flags & CALIPER_FLAG_SENSOR_ERR) flags[fi++] = 'E';
    if (r->flags & CALIPER_FLAG_REZERO) flags[fi++] = 'Z';
    flags[fi] = '\0';

    char utc[24] = "";
    if (with_utc && r->unix_s != 0) {
        csv_civil_t c;
        csv_civil_from_unix(r->unix_s, &c);
        snprintf(utc, sizeof(utc), "%04d-%02d-%02dT%02d:%02d:%02dZ", c.year, c.month, c.day, c.hour, c.min,
                 c.sec);
    }
    char unix_s[12] = "";
    if (r->unix_s != 0) {
        snprintf(unix_s, sizeof(unix_s), "%lu", (unsigned long)r->unix_s);
    }
    int len;
    if (with_utc) {
        len = snprintf(buf, n, "%lu,%s,%s,%s,%s,%s,%u,%s\r\n", (unsigned long)r->seq, unix_s, utc, val,
                       meas_unit_str(unit), flags, (unsigned)r->profile_id, logrec_kind_str(r->kind));
    } else {
        len = snprintf(buf, n, "%lu,%s,%s,%s,%s,%u,%s\r\n", (unsigned long)r->seq, unix_s, val,
                       meas_unit_str(unit), flags, (unsigned)r->profile_id, logrec_kind_str(r->kind));
    }
    return (len < 0 || (size_t)len >= n) ? -1 : len;
}

size_t csv_pack(const logrec_t *recs, size_t n, uint8_t mm_decimals, bool with_utc, char *buf, size_t n_buf,
                size_t *used)
{
    size_t u = 0, i = 0;
    if (n_buf) {
        buf[0] = '\0';
    }
    for (; i < n && u < n_buf; i++) {
        int l = csv_line(&recs[i], mm_decimals, with_utc, buf + u, n_buf - u);
        if (l < 0) {
            buf[u] = '\0'; /* this line did not fit: drop the partial text, the caller flushes */
            break;
        }
        u += (size_t)l;
    }
    *used = u;
    return i;
}
