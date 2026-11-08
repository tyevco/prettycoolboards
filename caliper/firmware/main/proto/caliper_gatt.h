/*
 * PrettyCool Caliper BLE GATT contract (rev A).
 *
 * This header is the single definition of the custom service (SPEC.md §8). The companion app
 * (caliper/app) mirrors it. It is plain C with no ESP-IDF includes so that the host tests and
 * the portable codec (components/measure/gatt_codec.c) can use it too.
 *
 * All integers are little-endian.
 *
 * Service  7c0a0001-5e1f-4b8a-9c3d-2f6a1e0c7b11
 *   LIVE     7c0a0002-...  read + notify, 10 bytes
 *   COMMAND  7c0a0003-...  write, u8 opcode + payload
 *   LOG      7c0a0004-...  notify, packed 16-byte records, terminated by seq = 0xFFFFFFFF
 *   SETTINGS 7c0a0005-...  read + write, UTF-8 JSON <= 240 bytes
 *   PROFILES 7c0a0006-...  read + write, 30-byte records
 */
#pragma once

#include <stdint.h>

/* 128-bit UUIDs, written as the 16 bytes in the order NimBLE's BLE_UUID128_INIT() expects
 * (least-significant byte first). The characteristic UUIDs differ only in the second 16-bit
 * group (bytes 12..13 here: 0x0001 = service, 0x0002.. = characteristics). */
#define CALIPER_UUID128_BYTES(lo16)                                                            \
    0x11, 0x7b, 0x0c, 0x1e, 0x6a, 0x2f, 0x3d, 0x9c, 0x8a, 0x4b, 0x1f, 0x5e, (uint8_t)((lo16) & 0xff), \
        (uint8_t)((lo16) >> 8), 0x0a, 0x7c

#define CALIPER_UUID_SVC      0x0001
#define CALIPER_UUID_LIVE     0x0002
#define CALIPER_UUID_COMMAND  0x0003
#define CALIPER_UUID_LOG      0x0004
#define CALIPER_UUID_SETTINGS 0x0005
#define CALIPER_UUID_PROFILES 0x0006

#define CALIPER_UUID_SVC_STR      "7c0a0001-5e1f-4b8a-9c3d-2f6a1e0c7b11"

/* LIVE: {i32 value_nm, i32 cap_nm, u8 unit, u8 flags} */
#define CALIPER_LIVE_LEN          10
#define CALIPER_CAP_INVALID       INT32_MIN

/* units */
#define CALIPER_UNIT_MM           0
#define CALIPER_UNIT_INCH         1

/* flags (LIVE.flags, and the log record flags use the same bits) */
#define CALIPER_FLAG_HOLD         (1u << 0)
#define CALIPER_FLAG_TOL_PASS     (1u << 1)
#define CALIPER_FLAG_TOL_FAIL     (1u << 2)
#define CALIPER_FLAG_SENSOR_ERR   (1u << 3)
#define CALIPER_FLAG_CAP_VALID    (1u << 4)
#define CALIPER_FLAG_CHARGING     (1u << 5)

/* COMMAND opcodes and their total write length (opcode byte included) */
#define CALIPER_OP_ZERO           0x01 /* len 1 */
#define CALIPER_OP_HOLD_TOGGLE    0x02 /* len 1 */
#define CALIPER_OP_RECORD_NOW     0x03 /* len 1 */
#define CALIPER_OP_SET_UNIT       0x04 /* len 2: u8 unit (0 mm, 1 inch) */
#define CALIPER_OP_LOG_READ       0x10 /* len 5: u32 from_seq */
#define CALIPER_OP_LOG_CLEAR      0x11 /* len 1 */
#define CALIPER_OP_SELECT_PROFILE 0x20 /* len 3: u16 profile id (0 = none) */
#define CALIPER_OP_SET_TIME       0x30 /* len 5: u32 unix seconds */

/* LOG record: {u32 seq, u32 unix_s, i32 value_nm, u8 unit, u8 flags, u16 profile_id} */
#define CALIPER_LOGREC_LEN        16
#define CALIPER_LOG_END_SEQ       0xFFFFFFFFu

/* SETTINGS */
#define CALIPER_SETTINGS_MAX_LEN  240

/* PROFILES: {u16 id, i32 nominal_nm, i32 tol_minus_nm, i32 tol_plus_nm, char name[16]} */
#define CALIPER_PROFILE_LEN       30
#define CALIPER_PROFILE_NAME_LEN  16
#define CALIPER_PROFILES_MAX      16 /* 16 x 30 = 480 bytes, under the 512-byte ATT value limit */

/* Standard services alongside the custom one */
#define CALIPER_UUID16_BAS        0x180F
#define CALIPER_UUID16_DIS        0x180A
#define CALIPER_UUID16_HID        0x1812
