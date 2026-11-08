/*
 * Byte-exact encoders/decoders for the custom GATT characteristics (caliper_gatt.h).
 * Portable C; the NimBLE glue in components/ble only moves bytes.
 */
#pragma once

#include <stddef.h>
#include <stdint.h>

#include "caliper_gatt.h"
#include "logrec.h"
#include "measure.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    int32_t value_nm;
    int32_t cap_nm; /* CALIPER_CAP_INVALID if invalid */
    uint8_t unit;
    uint8_t flags;
    uint16_t active_profile_id; /* CALIPER_PROFILE_ID_NONE (0) = none */
} gatt_live_t;

void gatt_live_pack(const gatt_live_t *l, uint8_t out[CALIPER_LIVE_LEN]);
/* Decodes a LIVE value of len bytes (>= CALIPER_LIVE_LEN_MIN; bytes past 12 are ignored). A 10-byte
 * value has no profile id: active_profile_id is then CALIPER_PROFILE_ID_NONE. Returns 0, or -1 if
 * len is too short. */
int gatt_live_unpack(const uint8_t *in, size_t len, gatt_live_t *l);

typedef struct {
    uint8_t op;
    uint32_t arg; /* unit, from_seq, profile id or unix time, by opcode */
} gatt_cmd_t;

#define GATT_CMD_OK          0
#define GATT_CMD_ERR_OPCODE  -1 /* unknown opcode */
#define GATT_CMD_ERR_LEN     -2 /* wrong length for the opcode */
#define GATT_CMD_ERR_VALUE   -3 /* e.g. SET_UNIT with a unit other than 0/1 */

int gatt_cmd_parse(const uint8_t *buf, size_t len, gatt_cmd_t *out);
/* Builds a command (used by the tests and by the USB CLI). Returns the length written. */
size_t gatt_cmd_build(const gatt_cmd_t *c, uint8_t *out, size_t n);

void gatt_profile_pack(const meas_profile_t *p, uint8_t out[CALIPER_PROFILE_LEN]);
void gatt_profile_unpack(const uint8_t in[CALIPER_PROFILE_LEN], meas_profile_t *p);
/* A record with an empty name and nominal = tol_minus = tol_plus = 0 deletes that id. */
int gatt_profile_is_delete(const meas_profile_t *p);

/* Records per LOG notification for a given ATT MTU (payload = MTU - 3), at least 1. */
size_t gatt_log_records_per_notify(uint16_t mtu);

#ifdef __cplusplus
}
#endif
