/*
 * The USB device: CDC ACM for the shell, bus-powered, bMaxPower 500 mA (SPEC §3.2). Its state changes go to
 * the board service, which applies the budget rules (SPEC §3.2, §8.4).
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#ifndef TB_USB_H_
#define TB_USB_H_

#include <errno.h>
#include <stdbool.h>
#include <stdint.h>

#if defined(CONFIG_BRINGUP_USB)
int tb_usb_init(void);
bool tb_usb_high_speed(void);
uint8_t tb_usb_config_value(void);
#else
static inline int tb_usb_init(void)
{
	return -ENOTSUP;
}
static inline bool tb_usb_high_speed(void)
{
	return false;
}
static inline uint8_t tb_usb_config_value(void)
{
	return 0;
}
#endif

#endif /* TB_USB_H_ */
