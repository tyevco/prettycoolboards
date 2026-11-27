/*
 * The 13 INA226 monitors (SPEC §3.4), over raw I2C with the lib's arithmetic (tb/ina226.h). The devicetree
 * gives each node's bus, shunt and current LSB (generated from nets.INA226_RAILS and INA226_CURRENT_LSB_UA); the
 * generated map gives its rail name and id. Zephyr's ti,ina226 driver also binds these nodes; "tb ina drv"
 * reads through it as a cross-check. Callers hold tb_lock.
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#ifndef TB_MONITORS_H_
#define TB_MONITORS_H_

#include <stdbool.h>
#include <stdint.h>
#include <zephyr/drivers/i2c.h>

struct tb_mon {
	struct i2c_dt_spec bus;
	const struct device *drv; /* the Zephyr sensor device on the same node */
	uint32_t shunt_uohm, lsb_ua;
	uint16_t cal;
	int rail;         /* tb/rails.h id, or -1 (VSYS, +3V3_MCU, +3V3_USB) */
	const char *name; /* the rail */
};

struct tb_mon_reading {
	int err;
	int16_t shunt_raw, current_raw;
	uint16_t bus_raw, power_raw, me, config, cal;
	int32_t current_ua, shunt_current_ua, bus_mv, shunt_uv;
	uint32_t power_uw;
};

extern const int tb_mon_count;
const struct tb_mon *tb_mon_at(int i);

const struct tb_mon *tb_mon_for_rail(int rail);
const struct tb_mon *tb_mon_by_name(const char *name); /* a rail name, or an address "0x44" */
const struct tb_mon *tb_mon_vsys(void);

int tb_mon_reg_read(const struct tb_mon *m, uint8_t reg, uint16_t *val);
int tb_mon_reg_write(const struct tb_mon *m, uint8_t reg, uint16_t val);
/* Identify, write CAL, configuration, and Mask/Enable = LEN with no alert function (latching, none armed). */
int tb_mon_setup(const struct tb_mon *m, uint16_t config, uint16_t *mfr, uint16_t *die);
/* Current, bus, shunt and power; with_me also reads (and so clears) Mask/Enable. */
int tb_mon_read(const struct tb_mon *m, bool with_me, struct tb_mon_reading *r);
/* A latching Shunt Over-Limit at current_ua (0 = no alert function). */
int tb_mon_set_alert(const struct tb_mon *m, uint32_t current_ua);

/* The bring-up's default conversion: 16 averages of 1.1 ms on both, continuous, a result every 35.2 ms. */
#define TB_MON_CONFIG_DEFAULT 0x0527
/* A faster one for load steps: no averaging, 1.1 ms on both, a result every 2.2 ms. */
#define TB_MON_CONFIG_FAST 0x0127

#endif /* TB_MONITORS_H_ */
