/* ASCII -> USB HID keyboard usage (US layout). Portable C. */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define HID_MOD_LSHIFT 0x02

/* Returns false for characters that have no key on a US keyboard. */
bool hid_ascii_to_key(char c, uint8_t *modifier, uint8_t *usage);

/* Builds the press/release report pairs for a string: out holds 8-byte boot-keyboard reports
 * {mod, 0, key, 0, 0, 0, 0, 0}, alternating press and all-up. Characters without a key are
 * skipped. Returns the number of reports written (at most max_reports). */
size_t hid_build_reports(const char *s, uint8_t (*out)[8], size_t max_reports);

#ifdef __cplusplus
}
#endif
