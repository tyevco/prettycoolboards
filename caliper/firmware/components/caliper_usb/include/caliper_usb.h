/*
 * usb: native USB device.
 *   CONFIG_CALIPER_USB_TINYUSB = y: TinyUSB composite
 *     - CDC ACM: console (logs) + a line CLI ("help")
 *     - MSC: a small FAT partition ("msc") holding LOG.CSV, rewritten from the log whenever a
 *       host enumerates us (or on the CLI "export"). It is a copy: edits on the PC are discarded.
 *   CONFIG_CALIPER_USB_TINYUSB = n: USB-Serial-JTAG console + the same CLI (no MSC).
 */
#pragma once

#include <stdbool.h>

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

esp_err_t caliper_usb_init(void);
void caliper_usb_poll(void);   /* ~1 Hz: host attach detection, ILIM, MSC export on attach */
bool caliper_usb_host(void);   /* enumerated by a host */

/* internal */
void cli_start(void);
void cli_feed(const char *buf, size_t len); /* bytes from the console transport */
esp_err_t msc_init(void);
esp_err_t msc_export(void);

#ifdef __cplusplus
}
#endif
