/* GATT characteristic codecs. Portable C. */
#include "gatt_codec.h"

#include <string.h>

#include "le_bytes.h"

_Static_assert(CALIPER_LIVE_LEN == CALIPER_LIVE_LEN_V2, "LIVE is packed as the 12-byte contract");
_Static_assert(CALIPER_LIVE_OFF_PROFILE + 2 == CALIPER_LIVE_LEN_V2, "active_profile_id is the last field");

/* strnlen is POSIX, not ISO C11: a local one keeps this file portable under -std=c11. */
static size_t bounded_strlen(const char *s, size_t max)
{
    size_t n = 0;
    while (n < max && s[n] != '\0') {
        n++;
    }
    return n;
}

void gatt_live_pack(const gatt_live_t *l, uint8_t out[CALIPER_LIVE_LEN])
{
    le_put_i32(out + 0, l->value_nm);
    le_put_i32(out + 4, l->cap_nm);
    out[8] = l->unit;
    out[9] = l->flags;
    le_put_u16(out + CALIPER_LIVE_OFF_PROFILE, l->active_profile_id);
}

int gatt_live_unpack(const uint8_t *in, size_t len, gatt_live_t *l)
{
    if (len < CALIPER_LIVE_LEN_MIN) {
        return -1;
    }
    l->value_nm = le_get_i32(in + 0);
    l->cap_nm = le_get_i32(in + 4);
    l->unit = in[8];
    l->flags = in[9];
    l->active_profile_id =
        len >= CALIPER_LIVE_LEN_V2 ? le_get_u16(in + CALIPER_LIVE_OFF_PROFILE) : (uint16_t)CALIPER_PROFILE_ID_NONE;
    return 0;
}

static int expected_len(uint8_t op)
{
    switch (op) {
    case CALIPER_OP_ZERO:
    case CALIPER_OP_HOLD_TOGGLE:
    case CALIPER_OP_RECORD_NOW:
    case CALIPER_OP_LOG_CLEAR:
        return 1;
    case CALIPER_OP_SET_UNIT:
        return 2;
    case CALIPER_OP_SELECT_PROFILE:
        return 3;
    case CALIPER_OP_LOG_READ:
    case CALIPER_OP_SET_TIME:
        return 5;
    default:
        return -1;
    }
}

int gatt_cmd_parse(const uint8_t *buf, size_t len, gatt_cmd_t *out)
{
    if (len < 1) {
        return GATT_CMD_ERR_LEN;
    }
    int want = expected_len(buf[0]);
    if (want < 0) {
        return GATT_CMD_ERR_OPCODE;
    }
    if ((size_t)want != len) {
        return GATT_CMD_ERR_LEN;
    }
    out->op = buf[0];
    out->arg = 0;
    switch (want) {
    case 2:
        out->arg = buf[1];
        break;
    case 3:
        out->arg = le_get_u16(buf + 1);
        break;
    case 5:
        out->arg = le_get_u32(buf + 1);
        break;
    default:
        break;
    }
    if (out->op == CALIPER_OP_SET_UNIT && out->arg > CALIPER_UNIT_INCH) {
        return GATT_CMD_ERR_VALUE;
    }
    return GATT_CMD_OK;
}

size_t gatt_cmd_build(const gatt_cmd_t *c, uint8_t *out, size_t n)
{
    int want = expected_len(c->op);
    if (want < 0 || (size_t)want > n) {
        return 0;
    }
    out[0] = c->op;
    if (want == 2) {
        out[1] = (uint8_t)c->arg;
    } else if (want == 3) {
        le_put_u16(out + 1, (uint16_t)c->arg);
    } else if (want == 5) {
        le_put_u32(out + 1, c->arg);
    }
    return (size_t)want;
}

void gatt_profile_pack(const meas_profile_t *p, uint8_t out[CALIPER_PROFILE_LEN])
{
    le_put_u16(out + 0, p->id);
    le_put_i32(out + 2, p->nominal_nm);
    le_put_i32(out + 6, p->tol_minus_nm);
    le_put_i32(out + 10, p->tol_plus_nm);
    memset(out + 14, 0, CALIPER_PROFILE_NAME_LEN);
    size_t nl = bounded_strlen(p->name, CALIPER_PROFILE_NAME_LEN);
    memcpy(out + 14, p->name, nl);
}

void gatt_profile_unpack(const uint8_t in[CALIPER_PROFILE_LEN], meas_profile_t *p)
{
    p->id = le_get_u16(in + 0);
    p->nominal_nm = le_get_i32(in + 2);
    p->tol_minus_nm = le_get_i32(in + 6);
    p->tol_plus_nm = le_get_i32(in + 10);
    memcpy(p->name, in + 14, CALIPER_PROFILE_NAME_LEN);
    p->name[CALIPER_PROFILE_NAME_LEN] = '\0'; /* a full 16-byte name has no NUL on the wire */
}

int gatt_profile_is_delete(const meas_profile_t *p)
{
    return p->name[0] == '\0' && p->nominal_nm == 0 && p->tol_minus_nm == 0 && p->tol_plus_nm == 0;
}

size_t gatt_log_records_per_notify(uint16_t mtu)
{
    size_t payload = mtu > 3 ? (size_t)mtu - 3u : 0u;
    size_t n = payload / CALIPER_LOGREC_LEN;
    return n ? n : 1;
}
