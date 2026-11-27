/*
 * bringup: the rev A testbed motherboard's bring-up firmware (SPEC §10 steps 5-7) for kbd_testbed_a.
 *
 * THE BOARD DOES NOT EXIST YET. This compiles; it has never run on hardware.
 *
 * Boot order:
 *  1. POST_KERNEL, priority 51 (after I2C1/I2C4 at 50, before the TCA9535 driver at 52; the board's
 *     Kconfig.defconfig sets the gap): snapshot every expander's input, output and configuration registers and
 *     the mux's control register, before any driver touches them, so the boot report can show what an NRST left
 *     behind (SPEC §3.5, §10 step 5). Then put the hardware in SPEC §3.5's order: the mux deselected first, then,
 *     after a warm reset that left U_EXP1 driving, its bus switches open and its 5 V enables off before its
 *     3.3 V enables. (The TCA9535 driver's init then makes every pin an input, which the pull resistors turn
 *     into the same safe state.) If a bus does not answer, it is clocked free first (bus_check(): a warm reset
 *     mid-read can leave a target holding SDA low).
 *  2. main(): the board service's restore (tb_restore: every output to its safe level, the mux pulsed through
 *     RESET and deselected, all read back), the 13 monitors, the lanes, USB (CDC ACM), the second shell, the
 *     board service thread. U_CC is read by the service once it answers (up to 200 ms, SPEC §8.4).
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include <stdio.h>
#include <string.h>

#include <zephyr/drivers/hwinfo.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/init.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/sys/printk.h>
#include <zephyr/version.h>

#include "board.h"
#include "cdc_shell.h"
#include "events.h"
#include "lanes.h"
#include "monitors.h"
#include "service.h"
#include "usb.h"

LOG_MODULE_REGISTER(tb_main, LOG_LEVEL_INF);

#define SNAPSHOT_PRIO 51
BUILD_ASSERT(CONFIG_I2C_INIT_PRIORITY < SNAPSHOT_PRIO, "the snapshot needs I2C1 and I2C4 up");
BUILD_ASSERT(CONFIG_GPIO_PCA95XX_INIT_PRIORITY > SNAPSHOT_PRIO,
	     "the snapshot must run before the TCA9535 driver resets every pin to an input (board Kconfig.defconfig)");
BUILD_ASSERT(CONFIG_I2C_TCA954X_ROOT_INIT_PRIO >= CONFIG_GPIO_PCA95XX_INIT_PRIORITY,
	     "the mux's reset-gpios is on U_EXP2");

struct tb_mon_boot {
	int err;
	uint16_t mfr, die;
};
static struct tb_mon_boot mon_boot[TB_INA226_COUNT];
static int board_err, lanes_err;

static int raw_read16(const struct device *bus, uint8_t addr, uint8_t reg, uint16_t *v)
{
	uint8_t b[2];
	int err = i2c_write_read(bus, addr, &reg, 1, b, 2);

	*v = (uint16_t)(b[0] | ((uint16_t)b[1] << 8));
	return err;
}

static int raw_write8(const struct device *bus, uint8_t addr, uint8_t reg, uint8_t v)
{
	uint8_t b[2] = {reg, v};

	return i2c_write(bus, b, 2, addr);
}

/*
 * A warm reset (NRST, the debugger, the watchdog) in the middle of a read can leave a target driving SDA low: it
 * waits for clocks the reset MCU will never send (SPEC §5.2), and every transfer on that bus then fails, including
 * the ones that turn the rails off. If the first transfer on a bus fails, clock the bus free with Zephyr's bus
 * recovery (CONFIG_I2C_BUS_RECOVERY; the board's scl-gpios/sda-gpios are open drain for it) and try once more.
 * Returns 0 if the bus answered at once, 1 if it answered after a recovery, or the error.
 */
static int bus_check(const struct device *bus, uint8_t addr, uint8_t reg, uint16_t *v)
{
	uint8_t b[2];
	int err = i2c_write_read(bus, addr, &reg, 1, b, 2);

	if (err == 0) {
		*v = (uint16_t)(b[0] | ((uint16_t)b[1] << 8));
		return 0;
	}
	if (!IS_ENABLED(CONFIG_I2C_BUS_RECOVERY) || i2c_recover_bus(bus) != 0) {
		return err;
	}
	err = i2c_write_read(bus, addr, &reg, 1, b, 2);
	if (err == 0) {
		*v = (uint16_t)(b[0] | ((uint16_t)b[1] << 8));
		return 1;
	}
	return err;
}

static int tb_early_snapshot(void)
{
	const struct device *i2c1 = DEVICE_DT_GET(DT_NODELABEL(i2c1));
	const struct device *i2c4 = DEVICE_DT_GET(DT_NODELABEL(i2c4));
	static const uint8_t addrs[TB_EXP_COUNT] = TB_EXP_ADDRS;
	uint32_t cause = 0;
	uint16_t dummy;

	if (IS_ENABLED(CONFIG_HWINFO) && hwinfo_get_reset_cause(&cause) == 0) {
		(void)hwinfo_clear_reset_cause();
	}
	tb_boot.reset_cause = cause;
	if (!device_is_ready(i2c1) || !device_is_ready(i2c4)) {
		return 0;
	}
	/* U_EXP1 first on I2C1 (it holds the rail enables); the mux, I2C4's only device, answers one byte */
	tb_boot.recover_i2c1 = bus_check(i2c1, addrs[TB_EXP_EXP1_INDEX], 0x06, &dummy);
	{
		uint8_t c;
		int e = i2c_read(i2c4, &c, 1, TB_I2C_ADDR_MUX);

		if (e != 0 && IS_ENABLED(CONFIG_I2C_BUS_RECOVERY) && i2c_recover_bus(i2c4) == 0) {
			e = i2c_read(i2c4, &c, 1, TB_I2C_ADDR_MUX);
			tb_boot.recover_i2c4 = e == 0 ? 1 : e;
		} else {
			tb_boot.recover_i2c4 = e;
		}
	}
	for (int i = 0; i < TB_EXP_COUNT; i++) {
		tb_boot.err[i] = raw_read16(i2c1, addrs[i], 0x00, &tb_boot.in[i]);
		tb_boot.err[i] |= raw_read16(i2c1, addrs[i], 0x02, &tb_boot.out[i]);
		tb_boot.err[i] |= raw_read16(i2c1, addrs[i], 0x06, &tb_boot.cfg[i]);
	}
	tb_boot.mux_err = i2c_read(i2c4, &tb_boot.mux_ctrl, 1, TB_I2C_ADDR_MUX);
	/* SPEC §3.5's order after a warm reset: the mux channel off before any rail goes down... */
	{
		uint8_t zero = 0;

		(void)i2c_write(i2c4, &zero, 1, TB_I2C_ADDR_MUX);
	}
	/* ...then, if U_EXP1 still drives its pins, the bus switches open and 5 V off before 3.3 V. */
	if (tb_boot.err[TB_EXP_EXP1_INDEX] == 0 && tb_boot.cfg[TB_EXP_EXP1_INDEX] != TB_EXP_POR_CONFIG) {
		uint16_t out = tb_boot.out[TB_EXP_EXP1_INDEX];
		uint16_t busen = BIT(TB_EXPNET_BUSEN_N_S1_PIN) | BIT(TB_EXPNET_BUSEN_N_S2_PIN) |
				 BIT(TB_EXPNET_BUSEN_N_S3_PIN) | BIT(TB_EXPNET_BUSEN_N_S4_PIN) |
				 BIT(TB_EXPNET_BUSEN_N_S5_PIN);
		uint16_t en5 = BIT(TB_EXPNET_EN_5V_S1_PIN) | BIT(TB_EXPNET_EN_5V_S2_PIN) | BIT(TB_EXPNET_EN_5V_S3_PIN) |
			       BIT(TB_EXPNET_EN_5V_S4_PIN) | BIT(TB_EXPNET_EN_5V_S5_PIN) |
			       BIT(TB_EXPNET_EN_5V_KVM_PIN);
		uint16_t en3 = BIT(TB_EXPNET_EN_3V3_S1_PIN) | BIT(TB_EXPNET_EN_3V3_S2_PIN) |
			       BIT(TB_EXPNET_EN_3V3_S3_PIN) | BIT(TB_EXPNET_EN_3V3_S4_PIN) |
			       BIT(TB_EXPNET_EN_3V3_S5_PIN);
		uint16_t step1 = (uint16_t)(out | busen);
		uint16_t step2 = (uint16_t)(step1 & ~en5);
		uint16_t step3 = (uint16_t)(step2 & ~en3);
		const uint16_t steps[3] = {step1, step2, step3};

		for (int k = 0; k < 3; k++) {
			/* port 1 (P10-P17) then port 0, each a single-byte write of its output register */
			(void)raw_write8(i2c1, addrs[TB_EXP_EXP1_INDEX], 0x03, (uint8_t)(steps[k] >> 8));
			(void)raw_write8(i2c1, addrs[TB_EXP_EXP1_INDEX], 0x02, (uint8_t)steps[k]);
		}
	}
	tb_boot.valid = true;
	return 0;
}

SYS_INIT(tb_early_snapshot, POST_KERNEL, SNAPSHOT_PRIO);

static void reset_tokens(uint32_t c, char *buf, size_t n)
{
	static const struct {
		uint32_t bit;
		const char *name;
	} t[] = {
		{RESET_PIN, "pin"}, {RESET_SOFTWARE, "software"}, {RESET_BROWNOUT, "brownout"},
		{RESET_POR, "por"}, {RESET_WATCHDOG, "watchdog"}, {RESET_DEBUG, "debug"},
		{RESET_SECURITY, "security"}, {RESET_LOW_POWER_WAKE, "lowpower"}, {RESET_CPU_LOCKUP, "lockup"},
		{RESET_PARITY, "parity"}, {RESET_PLL, "pll"}, {RESET_CLOCK, "clock"}, {RESET_HARDWARE, "hardware"},
		{RESET_USER, "user"}, {RESET_TEMPERATURE, "temperature"},
	};
	size_t used = 0;

	buf[0] = '\0';
	for (size_t i = 0; i < ARRAY_SIZE(t) && used < n; i++) {
		if (c & t[i].bit) {
			used += snprintf(&buf[used], n - used, "%s%s", used ? "," : "", t[i].name);
		}
	}
	if (used == 0) {
		snprintf(buf, n, "none");
	}
}

void tb_boot_report(void (*line)(void *ctx, const char *s), void *ctx)
{
	static const uint16_t out_mask[TB_EXP_COUNT] = TB_EXP_OUTPUT_MASK;
	char b[200], cause[64];

	reset_tokens(tb_boot.reset_cause, cause, sizeof(cause));
	snprintf(b, sizeof(b),
		 "boot fw=bringup board=kbd_testbed_a map=%s nets_rev=%s zephyr=%s reset=%s snapshot=%d proto=1 "
		 "i2c1_bus=%d i2c4_bus=%d",
		 TB_MAP_HASH, TB_MAP_NETS_REV, KERNEL_VERSION_STRING, cause, tb_boot.valid, tb_boot.recover_i2c1,
		 tb_boot.recover_i2c4);
	line(ctx, b);
	for (int i = 0; i < TB_EXP_COUNT; i++) {
		bool por = tb_boot.cfg[i] == TB_EXP_POR_CONFIG;
		/* outputs an NRST left driving, and whether any of them was on */
		uint16_t driven = (uint16_t)(~tb_boot.cfg[i] & out_mask[i]);

		snprintf(b, sizeof(b),
			 "boot_exp exp=%d addr=0x%02x err=%d pre_in=0x%04x pre_out=0x%04x pre_cfg=0x%04x por=%d "
			 "driven=0x%04x post_out=0x%04x post_cfg=0x%04x ok=%d",
			 i + 1, tb_sig.exp_addr[i], tb_boot.err[i], tb_boot.in[i], tb_boot.out[i], tb_boot.cfg[i],
			 por, driven, tb.restore.out[i], tb.restore.cfg[i], tb.restore.exp_ok[i]);
		line(ctx, b);
	}
	snprintf(b, sizeof(b), "boot_mux err=%d pre=0x%02x post=0x%02x post_err=%d", tb_boot.mux_err,
		 tb_boot.mux_ctrl, tb.restore.mux_ctrl, tb.restore.mux_err);
	line(ctx, b);
	for (int i = 0; i < tb_mon_count; i++) {
		const struct tb_mon *m = tb_mon_at(i);

		snprintf(b, sizeof(b), "boot_ina addr=0x%02x rail=%s err=%d mfr=0x%04x die=0x%04x cal=%u",
			 m->bus.addr, m->name, mon_boot[i].err, mon_boot[i].mfr, mon_boot[i].die, m->cal);
		line(ctx, b);
	}
	snprintf(b, sizeof(b), "boot_restore ok=%d err=%d board_err=%d lanes_err=%d", tb.restore.ok, tb.restore.err,
		 board_err, lanes_err);
	line(ctx, b);
}

static void printk_line(void *ctx, const char *s)
{
	ARG_UNUSED(ctx);
	printk("@tb %s\n", s);
}

int main(void)
{
	int err;

	k_mutex_lock(&tb_lock, K_FOREVER);
	err = board_err = tb_board_init();
	for (int i = 0; i < tb_mon_count; i++) {
		mon_boot[i].err = tb_mon_setup(tb_mon_at(i), TB_MON_CONFIG_DEFAULT, &mon_boot[i].mfr, &mon_boot[i].die);
	}
	/* INA226 0x40's ALERT at the unconfigured budget (SPEC §8.4); the service follows the budget. */
	if (tb_mon_vsys() != NULL) {
		(void)tb_mon_set_alert(tb_mon_vsys(), tb_budget_limit_ma(&tb.budget) * 1000u);
	}
	lanes_err = tb_lanes_init();
	err |= lanes_err;
	k_mutex_unlock(&tb_lock);

	tb_boot_report(printk_line, NULL);
	if (err != 0) {
		LOG_WRN("board init incomplete (%d): see the boot lines", err);
	}

	if (IS_ENABLED(CONFIG_BRINGUP_USB)) {
		err = tb_usb_init();
		if (err != 0) {
			LOG_ERR("USB init failed (%d): the USART1 shell still works", err);
		} else if (tb_cdc_shell_start() != 0) {
			LOG_ERR("CDC ACM shell not started");
		}
	}
	tb_service_start();
	tb_ev("kind=boot restore_ok=%d", tb.restore.ok);
	return 0;
}
