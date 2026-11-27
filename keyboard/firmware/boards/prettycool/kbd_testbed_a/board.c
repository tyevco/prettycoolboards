/*
 * kbd_testbed_a: early board init (hand-written).
 *
 * The rev A testbed motherboard is designed, not built: this has not run on hardware.
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include <zephyr/kernel.h>
#include <zephyr/platform/hooks.h>
#include <stm32_ll_pwr.h>

/*
 * UCPD dead-battery pull-downs off (SPEC §5.2, §8.4). After reset the UCPD's 5.1 kOhm Rd can switch onto PA15
 * and PB15 when PB5 and PB14 read high (DS13543 Rev 2 Table 27, note 4): on this board SLOT_SYNC and SLOT_MOSI.
 * Zephyr v4.5.0's soc.c does this only when no legacy USB device driver is built
 * (soc/st/stm32/stm32u5x/soc.c, "!IS_ENABLED(CONFIG_USB_DEVICE_DRIVER)"), so the board does it whatever the
 * application's USB stack. soc_early_init_hook() has already turned the PWR clock on.
 */
void board_early_init_hook(void)
{
	LL_PWR_DisableUCPDDeadBattery();
}
