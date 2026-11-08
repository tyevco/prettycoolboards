/*
 * PrettyCool Caliper BLE GATT contract (rev A).
 *
 * This header is the single definition of the custom service (SPEC.md §8). The companion app
 * (public/caliper/app/protocol.js) mirrors it. It is plain C with no ESP-IDF includes so that the host
 * tests and the portable codec (components/measure/gatt_codec.c) can use it too.
 *
 * All integers are little-endian.
 *
 * Service  7c0a0001-5e1f-4b8a-9c3d-2f6a1e0c7b11
 *   LIVE     7c0a0002-...  read + notify, 12 bytes (10 from firmware built before the extension)
 *   COMMAND  7c0a0003-...  write, u8 opcode + payload
 *   LOG      7c0a0004-...  notify, packed 16-byte records; the end marker (seq = 0xFFFFFFFF) is sent
 *                          in a notification of its own
 *   SETTINGS 7c0a0005-...  read + write (write needs an encrypted link), UTF-8 JSON <= 240 bytes
 *   PROFILES 7c0a0006-...  read + write, 30-byte records, per-record upsert
 *
 * Advertising: the advertisement or the scan response carries the complete 128-bit service UUID
 * (the app's Web Bluetooth chooser filters on it). Rev A puts it in the scan response.
 *
 * Contract clarifications (SPEC §8, 2026-11-07 reconciliation):
 *  - Tolerances are magnitudes: the band is nominal - |tol_minus| .. nominal + |tol_plus|, inclusive.
 *    Writers send them positive; readers ignore a sign.
 *  - A PROFILES write is a per-record upsert by id, applied all or nothing. A record with an empty name
 *    and nominal = tol_minus = tol_plus = 0 deletes that id (unknown id: no-op). At most
 *    CALIPER_PROFILES_MAX profiles are stored; a write that would exceed that is refused with
 *    CALIPER_ATT_ERR_VALUE and changes nothing. Profile id 0 (CALIPER_PROFILE_ID_NONE) means "no
 *    profile": it is never stored, a record with id 0 is refused, SELECT_PROFILE 0 clears the selection.
 *  - LOG record flags use the LIVE flag bit meanings (CALIPER_FLAG_*).
 *  - SETTINGS write = partial update: a key that is absent keeps its stored value (an absent wifi_pass
 *    keeps the stored password; "" clears it). Unknown keys are ignored. Any bad value rejects the
 *    whole write. Limits: CALIPER_SET_*. A read never contains wifi_pass.
 *  - "decimals" is the number of mm decimals; inch shows decimals + 2.
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

/* LIVE: {i32 value_nm, i32 cap_nm, u8 unit, u8 flags, u16 active_profile_id}
 * The contract is 12 bytes (CALIPER_LIVE_LEN_V2): active_profile_id (0 = none) was appended so a
 * client sees a profile chosen on the caliper itself. Readers accept >= 10 bytes and ignore bytes
 * past 12; a 10-byte LIVE (firmware built before the extension) means "active profile unknown".
 * gatt_live_pack() writes all 12 bytes; public/caliper/app/protocol.vectors.test.mjs holds vectors
 * generated from it. */
#define CALIPER_LIVE_LEN          CALIPER_LIVE_LEN_V2 /* what the firmware sends */
#define CALIPER_LIVE_LEN_MIN      10 /* readers accept this (pre-extension firmware) */
#define CALIPER_LIVE_LEN_V2       12 /* the contract */
#define CALIPER_LIVE_OFF_PROFILE  10 /* u16 active_profile_id */
#define CALIPER_CAP_INVALID       INT32_MIN

/* units */
#define CALIPER_UNIT_MM           0
#define CALIPER_UNIT_INCH         1

/* flags (LIVE.flags; the log record flags use the same bit meanings) */
#define CALIPER_FLAG_HOLD         (1u << 0)
#define CALIPER_FLAG_TOL_PASS     (1u << 1)
#define CALIPER_FLAG_TOL_FAIL     (1u << 2)
#define CALIPER_FLAG_SENSOR_ERR   (1u << 3)
#define CALIPER_FLAG_CAP_VALID    (1u << 4)
#define CALIPER_FLAG_CHARGING     (1u << 5)
/* The zero could not be carried across a deep sleep or reset (the AS5311 position was not
 * recovered), so the reading is relative to a new origin: press ZERO. Cleared by ZERO. Added
 * 2026-11-07 (firmware track); a client that does not know it ignores it. A log record taken meanwhile
 * carries it too (its value is relative to the new origin). */
#define CALIPER_FLAG_REZERO       (1u << 6)

/* COMMAND opcodes and their total write length (opcode byte included) */
#define CALIPER_OP_ZERO           0x01 /* len 1 */
#define CALIPER_OP_HOLD_TOGGLE    0x02 /* len 1 */
#define CALIPER_OP_RECORD_NOW     0x03 /* len 1 */
#define CALIPER_OP_SET_UNIT       0x04 /* len 2: u8 unit (0 mm, 1 inch) */
#define CALIPER_OP_LOG_READ       0x10 /* len 5: u32 from_seq */
#define CALIPER_OP_LOG_CLEAR      0x11 /* len 1 */
#define CALIPER_OP_SELECT_PROFILE 0x20 /* len 3: u16 profile id (0 = none) */
#define CALIPER_OP_SET_TIME       0x30 /* len 5: u32 unix seconds */

/* ATT error codes returned on writes (COMMAND, SETTINGS, PROFILES). Values as returned by
 * components/ble/ble_gatt.c; the app maps them to messages. */
#define CALIPER_ATT_ERR_OPCODE    0x06 /* Request Not Supported: unknown COMMAND opcode */
#define CALIPER_ATT_ERR_LEN       0x0D /* Invalid Attribute Value Length: wrong length for the opcode,
                                        * PROFILES not a non-zero multiple of 30 or > 16 records,
                                        * SETTINGS longer than 240 bytes or a result that would not fit */
#define CALIPER_ATT_ERR_AUTHEN    0x05 /* Insufficient Authentication, from the stack: SETTINGS written on an
                                        * unencrypted link by a peer that has no bond (no stored LTK).
                                        * Pair and retry. */
#define CALIPER_ATT_ERR_ENC       0x0F /* Insufficient Encryption, from the stack: the same write from a peer
                                        * that is bonded but has not re-encrypted the link yet. Confirmed in
                                        * ESP-IDF v5.4.2 NimBLE ble_att_svr_check_perms(); clients treat
                                        * 0x05 and 0x0F alike. */
#define CALIPER_ATT_ERR_VALUE     0x80 /* application error: bad argument (SET_UNIT not 0/1), a bad
                                        * SETTINGS value or JSON syntax, profile id 0, profile table full,
                                        * flash write failed */

/* LOG record: {u32 seq, u32 unix_s, i32 value_nm, u8 unit, u8 flags, u16 profile_id} */
#define CALIPER_LOGREC_LEN        16
#define CALIPER_LOG_END_SEQ       0xFFFFFFFFu /* sent alone, in the last notification of a LOG_READ */

/* SETTINGS (UTF-8 JSON object). Per-field limits; components/measure/include/settings.h must agree. */
#define CALIPER_SETTINGS_MAX_LEN  240
#define CALIPER_SET_NAME_MAX      20   /* bytes */
#define CALIPER_SET_SSID_MAX      32   /* bytes */
#define CALIPER_SET_PASS_MIN      8    /* bytes, unless "" (clears); write-only, never read back */
#define CALIPER_SET_PASS_MAX      64
#define CALIPER_SET_URL_MAX       64   /* mqtt_url: mqtt:// mqtts:// ws:// wss://; http_post_url: http:// https:// */
#define CALIPER_SET_AUTO_OFF_MIN  30   /* auto_off_s: 0 (never) or 30..3600, a JSON number */
#define CALIPER_SET_AUTO_OFF_MAX  3600
#define CALIPER_SET_DECIMALS_MIN  1    /* decimals: mm decimals 1..3, a JSON number; inch shows 2 more */
#define CALIPER_SET_DECIMALS_MAX  3
/* hid_suffix: "\n", "\t" or "" */

/* PROFILES: {u16 id, i32 nominal_nm, i32 tol_minus_nm, i32 tol_plus_nm, char name[16]}
 * tol_minus_nm / tol_plus_nm are magnitudes. name: UTF-8, NUL-padded (a full 16-byte name has no NUL). */
#define CALIPER_PROFILE_LEN       30
#define CALIPER_PROFILE_NAME_LEN  16
#define CALIPER_PROFILES_MAX      16 /* stored profiles and records per write: 16 x 30 = 480 bytes,
                                      * under the 512-byte ATT value limit */
#define CALIPER_PROFILE_ID_NONE   0  /* "no profile"; never stored */

/* Standard services alongside the custom one */
#define CALIPER_UUID16_BAS        0x180F
#define CALIPER_UUID16_DIS        0x180A
#define CALIPER_UUID16_HID        0x1812
