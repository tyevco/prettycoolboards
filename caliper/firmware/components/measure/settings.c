/* Settings model and flat JSON reader/writer. Portable C. */
#include "settings.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

void settings_defaults(settings_t *s)
{
    memset(s, 0, sizeof(*s));
    strcpy(s->name, "PrettyCool Caliper");
    s->auto_off_s = 300;
    s->hid_suffix[0] = '\n';
    s->decimals = 2;
}

/* ---- writer ---------------------------------------------------------------------------- */

typedef struct {
    char *buf;
    size_t n;
    size_t len;
    bool overflow;
} wbuf_t;

static void w_ch(wbuf_t *w, char c)
{
    if (w->len + 1 < w->n) {
        w->buf[w->len] = c;
        w->buf[w->len + 1] = '\0';
    } else {
        w->overflow = true;
    }
    w->len++;
}

static void w_str(wbuf_t *w, const char *s)
{
    while (*s) {
        w_ch(w, *s++);
    }
}

static void w_json_string(wbuf_t *w, const char *s)
{
    static const char hex[] = "0123456789abcdef";
    w_ch(w, '"');
    for (; *s; s++) {
        unsigned char c = (unsigned char)*s;
        switch (c) {
        case '"': w_str(w, "\\\""); break;
        case '\\': w_str(w, "\\\\"); break;
        case '\n': w_str(w, "\\n"); break;
        case '\t': w_str(w, "\\t"); break;
        case '\r': w_str(w, "\\r"); break;
        case '\b': w_str(w, "\\b"); break;
        case '\f': w_str(w, "\\f"); break;
        default:
            if (c < 0x20) {
                w_str(w, "\\u00");
                w_ch(w, hex[c >> 4]);
                w_ch(w, hex[c & 15]);
            } else {
                w_ch(w, (char)c);
            }
        }
    }
    w_ch(w, '"');
}

static void w_key(wbuf_t *w, const char *key, bool first)
{
    if (!first) {
        w_ch(w, ',');
    }
    w_json_string(w, key);
    w_ch(w, ':');
}

static void w_uint(wbuf_t *w, unsigned long v)
{
    char tmp[16];
    snprintf(tmp, sizeof(tmp), "%lu", v);
    w_str(w, tmp);
}

int settings_to_json(const settings_t *s, char *buf, size_t n)
{
    if (n == 0) {
        return -1;
    }
    wbuf_t w = {.buf = buf, .n = n, .len = 0, .overflow = false};
    buf[0] = '\0';
    w_ch(&w, '{');
    w_key(&w, "name", true);
    w_json_string(&w, s->name);
    w_key(&w, "wifi_ssid", false);
    w_json_string(&w, s->wifi_ssid);
    w_key(&w, "mqtt_url", false);
    w_json_string(&w, s->mqtt_url);
    w_key(&w, "http_post_url", false);
    w_json_string(&w, s->http_post_url);
    w_key(&w, "auto_off_s", false);
    w_uint(&w, s->auto_off_s);
    w_key(&w, "hid_suffix", false);
    w_json_string(&w, s->hid_suffix);
    w_key(&w, "decimals", false);
    w_uint(&w, s->decimals);
    w_ch(&w, '}');
    if (w.overflow) {
        return -1;
    }
    return (int)w.len;
}

/* ---- validation ------------------------------------------------------------------------ */

static bool has_prefix(const char *s, const char *p)
{
    return strncmp(s, p, strlen(p)) == 0;
}

static int set_str(char *dst, size_t max, const char *v)
{
    if (strlen(v) > max) {
        return SETTINGS_ERR_VALUE;
    }
    strcpy(dst, v);
    return SETTINGS_OK;
}

static int apply_string(settings_t *s, const char *key, const char *v)
{
    if (strcmp(key, "name") == 0) {
        return set_str(s->name, SETTINGS_NAME_MAX, v);
    }
    if (strcmp(key, "wifi_ssid") == 0) {
        return set_str(s->wifi_ssid, SETTINGS_SSID_MAX, v);
    }
    if (strcmp(key, "wifi_pass") == 0) {
        size_t l = strlen(v);
        if (l != 0 && (l < 8 || l > SETTINGS_PASS_MAX)) { /* WPA2: 8..63 chars or 64 hex */
            return SETTINGS_ERR_VALUE;
        }
        return set_str(s->wifi_pass, SETTINGS_PASS_MAX, v);
    }
    if (strcmp(key, "mqtt_url") == 0) {
        if (v[0] && !has_prefix(v, "mqtt://") && !has_prefix(v, "mqtts://") && !has_prefix(v, "ws://") &&
            !has_prefix(v, "wss://")) {
            return SETTINGS_ERR_VALUE;
        }
        return set_str(s->mqtt_url, SETTINGS_URL_MAX, v);
    }
    if (strcmp(key, "http_post_url") == 0) {
        if (v[0] && !has_prefix(v, "http://") && !has_prefix(v, "https://")) {
            return SETTINGS_ERR_VALUE;
        }
        return set_str(s->http_post_url, SETTINGS_URL_MAX, v);
    }
    if (strcmp(key, "hid_suffix") == 0) {
        if (!(v[0] == '\0' || ((v[0] == '\n' || v[0] == '\t') && v[1] == '\0'))) {
            return SETTINGS_ERR_VALUE;
        }
        s->hid_suffix[0] = v[0];
        s->hid_suffix[1] = '\0';
        return SETTINGS_OK;
    }
    if (strcmp(key, "auto_off_s") == 0 || strcmp(key, "decimals") == 0) {
        return SETTINGS_ERR_VALUE; /* numbers must be JSON numbers */
    }
    return SETTINGS_OK; /* unknown key: ignored */
}

static int apply_number(settings_t *s, const char *key, long v)
{
    if (strcmp(key, "auto_off_s") == 0) {
        if (v != 0 && (v < SETTINGS_AUTO_OFF_MIN || v > SETTINGS_AUTO_OFF_MAX)) {
            return SETTINGS_ERR_VALUE;
        }
        s->auto_off_s = (uint32_t)v;
        return SETTINGS_OK;
    }
    if (strcmp(key, "decimals") == 0) {
        if (v < 1 || v > 3) {
            return SETTINGS_ERR_VALUE;
        }
        s->decimals = (uint8_t)v;
        return SETTINGS_OK;
    }
    if (strcmp(key, "name") == 0 || strcmp(key, "wifi_ssid") == 0 || strcmp(key, "wifi_pass") == 0 ||
        strcmp(key, "mqtt_url") == 0 || strcmp(key, "http_post_url") == 0 || strcmp(key, "hid_suffix") == 0) {
        return SETTINGS_ERR_VALUE;
    }
    return SETTINGS_OK;
}

static int check_size(const settings_t *s)
{
    char tmp[SETTINGS_JSON_MAX + 1];
    return settings_to_json(s, tmp, sizeof(tmp)) < 0 ? SETTINGS_ERR_TOOBIG : SETTINGS_OK;
}

typedef enum { KEY_UNKNOWN, KEY_STR, KEY_NUM } key_kind_t;

static key_kind_t key_kind(const char *key)
{
    static const char *const str_keys[] = {"name", "wifi_ssid", "wifi_pass", "mqtt_url", "http_post_url", "hid_suffix"};
    for (size_t i = 0; i < sizeof(str_keys) / sizeof(str_keys[0]); i++) {
        if (strcmp(key, str_keys[i]) == 0) {
            return KEY_STR;
        }
    }
    if (strcmp(key, "auto_off_s") == 0 || strcmp(key, "decimals") == 0) {
        return KEY_NUM;
    }
    return KEY_UNKNOWN;
}

/* ---- reader ---------------------------------------------------------------------------- */

typedef struct {
    const char *p;
    const char *end;
} rd_t;

static void skip_ws(rd_t *r)
{
    while (r->p < r->end && (*r->p == ' ' || *r->p == '\t' || *r->p == '\n' || *r->p == '\r')) {
        r->p++;
    }
}

static int hexval(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static bool read_hex4(rd_t *r, unsigned *out)
{
    if (r->end - r->p < 4) {
        return false;
    }
    unsigned v = 0;
    for (int i = 0; i < 4; i++) {
        int h = hexval(r->p[i]);
        if (h < 0) {
            return false;
        }
        v = (v << 4) | (unsigned)h;
    }
    r->p += 4;
    *out = v;
    return true;
}

typedef struct {
    char *buf;
    size_t n;
    size_t len;
    bool overflow;
} sbuf_t;

static void s_put(sbuf_t *b, unsigned char c)
{
    if (b->len + 1 < b->n) {
        b->buf[b->len++] = (char)c;
        b->buf[b->len] = '\0';
    } else {
        b->overflow = true;
    }
}

static void s_put_utf8(sbuf_t *b, unsigned cp)
{
    if (cp < 0x80) {
        s_put(b, (unsigned char)cp);
    } else if (cp < 0x800) {
        s_put(b, (unsigned char)(0xC0 | (cp >> 6)));
        s_put(b, (unsigned char)(0x80 | (cp & 0x3F)));
    } else if (cp < 0x10000) {
        s_put(b, (unsigned char)(0xE0 | (cp >> 12)));
        s_put(b, (unsigned char)(0x80 | ((cp >> 6) & 0x3F)));
        s_put(b, (unsigned char)(0x80 | (cp & 0x3F)));
    } else {
        s_put(b, (unsigned char)(0xF0 | (cp >> 18)));
        s_put(b, (unsigned char)(0x80 | ((cp >> 12) & 0x3F)));
        s_put(b, (unsigned char)(0x80 | ((cp >> 6) & 0x3F)));
        s_put(b, (unsigned char)(0x80 | (cp & 0x3F)));
    }
}

/* Reads a JSON string at r->p (which must be '"'). */
static bool read_string(rd_t *r, sbuf_t *out)
{
    if (r->p >= r->end || *r->p != '"') {
        return false;
    }
    r->p++;
    while (r->p < r->end) {
        unsigned char c = (unsigned char)*r->p++;
        if (c == '"') {
            return true;
        }
        if (c < 0x20) {
            return false;
        }
        if (c != '\\') {
            s_put(out, c);
            continue;
        }
        if (r->p >= r->end) {
            return false;
        }
        char e = *r->p++;
        switch (e) {
        case '"': s_put(out, '"'); break;
        case '\\': s_put(out, '\\'); break;
        case '/': s_put(out, '/'); break;
        case 'b': s_put(out, '\b'); break;
        case 'f': s_put(out, '\f'); break;
        case 'n': s_put(out, '\n'); break;
        case 'r': s_put(out, '\r'); break;
        case 't': s_put(out, '\t'); break;
        case 'u': {
            unsigned cp;
            if (!read_hex4(r, &cp)) {
                return false;
            }
            if (cp >= 0xD800 && cp <= 0xDBFF) {
                unsigned lo;
                if (r->end - r->p < 6 || r->p[0] != '\\' || r->p[1] != 'u') {
                    return false;
                }
                r->p += 2;
                if (!read_hex4(r, &lo) || lo < 0xDC00 || lo > 0xDFFF) {
                    return false;
                }
                cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
            } else if (cp >= 0xDC00 && cp <= 0xDFFF) {
                return false;
            }
            if (cp == 0) {
                return false; /* no embedded NULs */
            }
            s_put_utf8(out, cp);
            break;
        }
        default:
            return false;
        }
    }
    return false;
}

/* Integer only; a fraction or exponent is a value error for known keys. */
static int read_number(rd_t *r, long *out, bool *is_int)
{
    const char *start = r->p;
    if (r->p < r->end && *r->p == '-') {
        r->p++;
    }
    if (r->p >= r->end || *r->p < '0' || *r->p > '9') {
        return SETTINGS_ERR_SYNTAX;
    }
    long v = 0;
    bool big = false;
    while (r->p < r->end && *r->p >= '0' && *r->p <= '9') {
        if (v > 100000000L) {
            big = true;
        } else {
            v = v * 10 + (*r->p - '0');
        }
        r->p++;
    }
    *is_int = !big;
    if (r->p < r->end && (*r->p == '.' || *r->p == 'e' || *r->p == 'E')) {
        *is_int = false;
        r->p++;
        while (r->p < r->end && ((*r->p >= '0' && *r->p <= '9') || *r->p == '+' || *r->p == '-' ||
                                 *r->p == 'e' || *r->p == 'E' || *r->p == '.')) {
            r->p++;
        }
    }
    *out = (*start == '-') ? -v : v;
    return SETTINGS_OK;
}

static bool match_lit(rd_t *r, const char *lit)
{
    size_t l = strlen(lit);
    if ((size_t)(r->end - r->p) >= l && memcmp(r->p, lit, l) == 0) {
        r->p += l;
        return true;
    }
    return false;
}

int settings_from_json(settings_t *s, const char *json, size_t len)
{
    settings_t tmp = *s;
    rd_t r = {.p = json, .end = json + len};
    char key[24];
    char val[SETTINGS_PASS_MAX + 8];

    skip_ws(&r);
    if (r.p >= r.end || *r.p != '{') {
        return SETTINGS_ERR_SYNTAX;
    }
    r.p++;
    skip_ws(&r);
    if (r.p < r.end && *r.p == '}') {
        r.p++;
    } else {
        for (;;) {
            skip_ws(&r);
            sbuf_t kb = {.buf = key, .n = sizeof(key), .len = 0, .overflow = false};
            key[0] = '\0';
            if (!read_string(&r, &kb)) {
                return SETTINGS_ERR_SYNTAX;
            }
            skip_ws(&r);
            if (r.p >= r.end || *r.p != ':') {
                return SETTINGS_ERR_SYNTAX;
            }
            r.p++;
            skip_ws(&r);
            if (r.p >= r.end) {
                return SETTINGS_ERR_SYNTAX;
            }
            int rc = SETTINGS_OK;
            key_kind_t kind = kb.overflow ? KEY_UNKNOWN : key_kind(key);
            if (*r.p == '"') {
                sbuf_t vb = {.buf = val, .n = sizeof(val), .len = 0, .overflow = false};
                val[0] = 0;
                if (!read_string(&r, &vb)) {
                    return SETTINGS_ERR_SYNTAX;
                }
                if (kind == KEY_NUM || (kind == KEY_STR && vb.overflow)) {
                    rc = SETTINGS_ERR_VALUE;
                } else if (kind == KEY_STR) {
                    rc = apply_string(&tmp, key, val);
                }
            } else if (*r.p == '-' || (*r.p >= '0' && *r.p <= '9')) {
                long v;
                bool is_int;
                if (read_number(&r, &v, &is_int) != SETTINGS_OK) {
                    return SETTINGS_ERR_SYNTAX;
                }
                if (kind == KEY_STR || (kind == KEY_NUM && !is_int)) {
                    rc = SETTINGS_ERR_VALUE;
                } else if (kind == KEY_NUM) {
                    rc = apply_number(&tmp, key, v);
                }
            } else if (match_lit(&r, "true") || match_lit(&r, "false") || match_lit(&r, "null")) {
                if (kind != KEY_UNKNOWN) {
                    rc = SETTINGS_ERR_VALUE; /* literals are only skipped for unknown keys */
                }
            } else {
                return SETTINGS_ERR_SYNTAX; /* nested objects/arrays are not accepted */
            }
            if (rc != SETTINGS_OK) {
                return rc;
            }
            skip_ws(&r);
            if (r.p < r.end && *r.p == ',') {
                r.p++;
                continue;
            }
            if (r.p < r.end && *r.p == '}') {
                r.p++;
                break;
            }
            return SETTINGS_ERR_SYNTAX;
        }
    }
    skip_ws(&r);
    while (r.p < r.end && *r.p == '\0') { /* tolerate a trailing NUL from some BLE stacks */
        r.p++;
    }
    if (r.p != r.end) {
        return SETTINGS_ERR_SYNTAX;
    }
    int rc = check_size(&tmp);
    if (rc != SETTINGS_OK) {
        return rc;
    }
    *s = tmp;
    return SETTINGS_OK;
}

int settings_set_kv(settings_t *s, const char *key, const char *value)
{
    settings_t tmp = *s;
    int rc;
    if (strcmp(key, "auto_off_s") == 0 || strcmp(key, "decimals") == 0) {
        char *endp;
        long v = strtol(value, &endp, 10);
        if (*value == '\0' || *endp != '\0') {
            return SETTINGS_ERR_VALUE;
        }
        rc = apply_number(&tmp, key, v);
    } else if (strcmp(key, "hid_suffix") == 0) {
        /* the web form / CLI spell the suffix as a word */
        const char *v = value;
        if (strcmp(value, "enter") == 0 || strcmp(value, "\\n") == 0) {
            v = "\n";
        } else if (strcmp(value, "tab") == 0 || strcmp(value, "\\t") == 0) {
            v = "\t";
        } else if (strcmp(value, "none") == 0) {
            v = "";
        }
        rc = apply_string(&tmp, key, v);
    } else {
        rc = apply_string(&tmp, key, value);
    }
    if (rc == SETTINGS_OK) {
        rc = check_size(&tmp);
    }
    if (rc == SETTINGS_OK) {
        *s = tmp;
    }
    return rc;
}

size_t settings_url_decode(char *dst, size_t n, const char *src, size_t src_len)
{
    size_t o = 0;
    for (size_t i = 0; i < src_len && o + 1 < n; i++) {
        char c = src[i];
        if (c == '+') {
            c = ' ';
        } else if (c == '%' && i + 2 < src_len && hexval(src[i + 1]) >= 0 && hexval(src[i + 2]) >= 0) {
            c = (char)((hexval(src[i + 1]) << 4) | hexval(src[i + 2]));
            i += 2;
        }
        dst[o++] = c;
    }
    if (n) {
        dst[o] = '\0';
    }
    return o;
}
