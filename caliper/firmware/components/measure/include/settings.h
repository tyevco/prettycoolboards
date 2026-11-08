/*
 * User settings and their JSON form (the SETTINGS characteristic, the web form, the CLI).
 * Portable C: a flat-object JSON reader/writer, no cJSON.
 *
 * Keys: name, wifi_ssid, wifi_pass (write-only), mqtt_url, http_post_url, auto_off_s,
 * hid_suffix ("\n" | "\t" | ""), decimals.
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define SETTINGS_NAME_MAX 20
#define SETTINGS_SSID_MAX 32
#define SETTINGS_PASS_MAX 64
#define SETTINGS_URL_MAX  64
#define SETTINGS_JSON_MAX 240 /* CALIPER_SETTINGS_MAX_LEN */

#define SETTINGS_AUTO_OFF_MIN 30
#define SETTINGS_AUTO_OFF_MAX 3600

typedef struct {
    char name[SETTINGS_NAME_MAX + 1];
    char wifi_ssid[SETTINGS_SSID_MAX + 1];
    char wifi_pass[SETTINGS_PASS_MAX + 1];
    char mqtt_url[SETTINGS_URL_MAX + 1];
    char http_post_url[SETTINGS_URL_MAX + 1];
    uint32_t auto_off_s; /* 0 = never, else 30..3600 */
    char hid_suffix[2];  /* "\n", "\t" or "" */
    uint8_t decimals;    /* mm digits 1..3 (inch shows two more) */
} settings_t;

#define SETTINGS_OK          0
#define SETTINGS_ERR_SYNTAX  -1
#define SETTINGS_ERR_VALUE   -2 /* a known key with a bad value / too long */
#define SETTINGS_ERR_TOOBIG  -3 /* the result would not serialise in 240 bytes */

void settings_defaults(settings_t *s);

/* Serialises every key except wifi_pass. Returns the length (no NUL counted), or -1 if it
 * does not fit in n - 1 bytes. */
int settings_to_json(const settings_t *s, char *buf, size_t n);

/* Merges the keys present in json into *s. All-or-nothing: on any error *s is unchanged.
 * Unknown keys are ignored. Also rejects a result whose JSON form exceeds 240 bytes. */
int settings_from_json(settings_t *s, const char *json, size_t len);

/* Sets one key from a text value (web form / CLI). Same validation; all-or-nothing. */
int settings_set_kv(settings_t *s, const char *key, const char *value);

/* application/x-www-form-urlencoded decoding ('+' -> ' ', %XX). Returns the decoded length;
 * dst always NUL-terminated (n >= 1). */
size_t settings_url_decode(char *dst, size_t n, const char *src, size_t src_len);

#ifdef __cplusplus
}
#endif
