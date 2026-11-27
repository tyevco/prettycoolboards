/*
 * INA226 monitors over raw I2C (see monitors.h).
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include <stdlib.h>
#include <string.h>

#include <zephyr/devicetree.h>
#include <zephyr/init.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/sys/byteorder.h>
#include <zephyr/sys/util.h>

#include "monitors.h"
#include "tb/ina226.h"
#include "tb/rails.h"
#include "tb_board_map.h"

struct map_row {
	uint8_t addr;
	const char *rail;
	uint32_t shunt_uohm, lsb_ua, cal;
	int rail_id;
	uint32_t rule_ma, tmin, ttyp, tmax;
};
static const struct map_row map[] = TB_INA226_TABLE;

#define MON_ENTRY(node)                                                                            \
	{                                                                                          \
		.bus = I2C_DT_SPEC_GET(node),                                                      \
		.drv = DEVICE_DT_GET(node),                                                        \
		.shunt_uohm = DT_PROP(node, rshunt_micro_ohms),                                    \
		.lsb_ua = DT_PROP(node, current_lsb_microamps),                                    \
	},

/* From the devicetree; rail, name and CAL are completed from the board map before the kernel starts. */
static struct tb_mon mons[] = {DT_FOREACH_STATUS_OKAY(ti_ina226, MON_ENTRY)};
const int tb_mon_count = ARRAY_SIZE(mons);
BUILD_ASSERT(ARRAY_SIZE(mons) == TB_INA226_COUNT, "the devicetree and the board map disagree on the monitors");

static int init_table(void)
{
	for (size_t i = 0; i < ARRAY_SIZE(mons); i++) {
		mons[i].rail = -1;
		mons[i].name = "?";
		for (size_t j = 0; j < ARRAY_SIZE(map); j++) {
			if (map[j].addr == mons[i].bus.addr) {
				mons[i].rail = map[j].rail_id;
				mons[i].name = map[j].rail;
				break;
			}
		}
		mons[i].cal = tb_ina226_cal(mons[i].lsb_ua, mons[i].shunt_uohm);
	}
	return 0;
}

SYS_INIT(init_table, PRE_KERNEL_1, 0);

const struct tb_mon *tb_mon_at(int i)
{
	return (i >= 0 && i < tb_mon_count) ? &mons[i] : NULL;
}

const struct tb_mon *tb_mon_for_rail(int rail)
{
	for (int i = 0; i < tb_mon_count; i++) {
		if (mons[i].rail == rail && rail >= 0) {
			return &mons[i];
		}
	}
	return NULL;
}

const struct tb_mon *tb_mon_vsys(void)
{
	for (int i = 0; i < tb_mon_count; i++) {
		if (mons[i].bus.addr == TB_INA226_ADDR_VSYS) {
			return &mons[i];
		}
	}
	return NULL;
}

const struct tb_mon *tb_mon_by_name(const char *name)
{
	if (name == NULL) {
		return NULL;
	}
	if (name[0] == '0' && (name[1] == 'x' || name[1] == 'X')) {
		long a = strtol(name, NULL, 16);

		for (int i = 0; i < tb_mon_count; i++) {
			if (mons[i].bus.addr == a) {
				return &mons[i];
			}
		}
		return NULL;
	}
	for (int i = 0; i < tb_mon_count; i++) {
		const char *n = mons[i].name;
		const char *q = name;

		/* "+3V3_S1", "3v3_s1" and "3V3_S1" all match */
		if (*n == '+') {
			n++;
		}
		if (*q == '+') {
			q++;
		}
		while (*n != '\0' && *q != '\0' && (*n | 0x20) == (*q | 0x20)) {
			n++;
			q++;
		}
		if (*n == '\0' && *q == '\0') {
			return &mons[i];
		}
	}
	return NULL;
}

int tb_mon_reg_read(const struct tb_mon *m, uint8_t reg, uint16_t *val)
{
	uint8_t buf[2];
	int err = i2c_write_read_dt(&m->bus, &reg, 1, buf, sizeof(buf));

	if (err == 0) {
		*val = sys_get_be16(buf);
	}
	return err;
}

int tb_mon_reg_write(const struct tb_mon *m, uint8_t reg, uint16_t val)
{
	uint8_t buf[3] = {reg, (uint8_t)(val >> 8), (uint8_t)val};

	return i2c_write_dt(&m->bus, buf, sizeof(buf));
}

int tb_mon_setup(const struct tb_mon *m, uint16_t config, uint16_t *mfr, uint16_t *die)
{
	uint16_t a = 0, b = 0, cfg;
	int err;

	err = tb_mon_reg_read(m, TB_INA226_REG_MFR_ID, &a);
	err = err ? err : tb_mon_reg_read(m, TB_INA226_REG_DIE_ID, &b);
	if (mfr != NULL) {
		*mfr = a;
	}
	if (die != NULL) {
		*die = b;
	}
	if (err != 0) {
		return err;
	}
	if (a != TB_INA226_MFR_ID || b != TB_INA226_DIE_ID) {
		return -ENODEV;
	}
	err = tb_mon_reg_write(m, TB_INA226_REG_CAL, m->cal);
	err = err ? err : tb_mon_reg_write(m, TB_INA226_REG_CONFIG, config);
	err = err ? err : tb_mon_reg_write(m, TB_INA226_REG_ALERT_LIMIT, 0x7FFF);
	err = err ? err : tb_mon_reg_write(m, TB_INA226_REG_MASK_ENABLE, TB_INA226_ME_LEN);
	err = err ? err : tb_mon_reg_read(m, TB_INA226_REG_CONFIG, &cfg);
	if (err == 0 && (cfg & TB_INA226_CONFIG_MASK) != (config & TB_INA226_CONFIG_MASK)) {
		err = -EIO;
	}
	return err;
}

int tb_mon_read(const struct tb_mon *m, bool with_me, struct tb_mon_reading *r)
{
	uint16_t sh = 0, bus = 0, cur = 0, pw = 0;
	int err;

	memset(r, 0, sizeof(*r));
	err = tb_mon_reg_read(m, TB_INA226_REG_SHUNT, &sh);
	err = err ? err : tb_mon_reg_read(m, TB_INA226_REG_BUS, &bus);
	err = err ? err : tb_mon_reg_read(m, TB_INA226_REG_CURRENT, &cur);
	err = err ? err : tb_mon_reg_read(m, TB_INA226_REG_POWER, &pw);
	err = err ? err : tb_mon_reg_read(m, TB_INA226_REG_CONFIG, &r->config);
	err = err ? err : tb_mon_reg_read(m, TB_INA226_REG_CAL, &r->cal);
	if (err == 0 && with_me) {
		err = tb_mon_reg_read(m, TB_INA226_REG_MASK_ENABLE, &r->me);
	}
	r->err = err;
	if (err != 0) {
		return err;
	}
	r->shunt_raw = (int16_t)sh;
	r->current_raw = (int16_t)cur;
	r->bus_raw = bus;
	r->power_raw = pw;
	r->current_ua = tb_ina226_current_ua(r->current_raw, m->lsb_ua);
	r->shunt_current_ua = tb_ina226_shunt_current_ua(r->shunt_raw, m->shunt_uohm);
	r->shunt_uv = tb_ina226_shunt_nv(r->shunt_raw) / 1000;
	r->bus_mv = (int32_t)(tb_ina226_bus_uv(bus) / 1000u);
	r->power_uw = tb_ina226_power_uw(pw, m->lsb_ua);
	return 0;
}

int tb_mon_set_alert(const struct tb_mon *m, uint32_t current_ua)
{
	int err;

	if (current_ua == 0) {
		return tb_mon_reg_write(m, TB_INA226_REG_MASK_ENABLE, TB_INA226_ME_LEN);
	}
	err = tb_mon_reg_write(m, TB_INA226_REG_ALERT_LIMIT, tb_ina226_sol_limit(current_ua, m->shunt_uohm));
	return err ? err : tb_mon_reg_write(m, TB_INA226_REG_MASK_ENABLE, TB_INA226_ME_SOL | TB_INA226_ME_LEN);
}
