/*
 * hid8k: the CDC ACM console (log lines out, one-word commands in).
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#ifndef HID8K_CDC_CONSOLE_H_
#define HID8K_CDC_CONSOLE_H_

#include <stddef.h>
#include <stdint.h>

/* Called with each complete line received from the host, without its line ending. */
typedef void (*cdc_console_cmd_cb_t)(const char *line);

int cdc_console_init(cdc_console_cmd_cb_t cmd_cb);

/*
 * Queue bytes for the host, all or nothing: returns len, or 0 if the ring had no room for
 * all of them (then all are counted as dropped). Call from one thread only.
 */
size_t cdc_console_write(const char *data, size_t len);

/* Bytes queued and dropped since boot (both wrap at 2^32). */
uint32_t cdc_console_queued(void);
uint32_t cdc_console_dropped(void);

/* Bytes waiting in the ring for the host. */
uint32_t cdc_console_pending(void);

#endif /* HID8K_CDC_CONSOLE_H_ */
