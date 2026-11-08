/*
 * store: persistent data.
 *   - reading log: a ring of 16-byte records (logrec.h) in LittleFS segment files of 256 records
 *     (one 4 KiB block each) plus a 16-byte header file; see store.c for why
 *   - tolerance profiles: a LittleFS file of 30-byte records (the GATT PROFILES layout)
 *   - settings and small state (unit, active profile, capture mode): NVS
 * All functions are thread-safe (one internal mutex).
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"
#include "logrec.h"
#include "measure.h"
#include "settings.h"

#ifdef __cplusplus
extern "C" {
#endif

#ifndef STORE_BASE_PATH
#define STORE_BASE_PATH "/fs"
#endif

esp_err_t store_init(void);
#ifdef STORE_HOST_TEST
esp_err_t store_test_reboot(uint32_t capacity); /* host tests: reopen the log as after a reboot */
#endif

/* ---- log ---- */
esp_err_t store_log_append(logrec_t *rec); /* assigns rec->seq */
bool store_log_get(uint32_t seq, logrec_t *out);
/* Reads up to max consecutive stored records starting at the first seq >= from_seq.
 * Returns the count; *next gets the seq to continue from. */
size_t store_log_read(uint32_t from_seq, logrec_t *out, size_t max, uint32_t *next);
uint32_t store_log_count(void);
uint32_t store_log_next_seq(void);
esp_err_t store_log_clear(void);

/* CSV export through a writer callback (HTTP chunks, a FAT file, the CDC console). */
typedef esp_err_t (*store_write_fn)(void *ctx, const char *buf, size_t len);
esp_err_t store_log_export_csv(bool with_utc, uint8_t mm_decimals, store_write_fn fn, void *ctx);

/* ---- profiles ---- */
size_t store_profiles_load(meas_profile_t *out, size_t max);
esp_err_t store_profiles_save(const meas_profile_t *p, size_t n);

/* ---- settings and state (NVS) ---- */
esp_err_t store_settings_load(settings_t *s); /* defaults where nothing is stored */
esp_err_t store_settings_save(const settings_t *s);

typedef struct {
    uint8_t unit;
    uint16_t profile_id;
    uint8_t capture;   /* CALIPER_CAPTURE_LIVE / _SETTLE / _SWEEP (default SETTLE) */
    uint8_t sweep_sel; /* CALIPER_SWEEP_* (default AUTO) */
} store_state_t;

esp_err_t store_state_load(store_state_t *st);
esp_err_t store_state_save(const store_state_t *st);

#ifdef __cplusplus
}
#endif
