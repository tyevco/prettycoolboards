/*
 * Simulated board: an INA226 register model (TI SBOS547) for the ti,ina226 nodes. The shunt and bus registers
 * come from the board model's rail current and voltage; Current = Shunt x CAL / 2048 (Eq. 3), Power =
 * Current x Bus / 20000 (Eq. 4); Mask/Enable's AFF with a latch (LEN) cleared by reading Mask/Enable or writing
 * Configuration. Conversions are instantaneous here (CVRF always set): the model has no conversion time.
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#define DT_DRV_COMPAT ti_ina226

#include <zephyr/device.h>
#include <zephyr/drivers/emul.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/drivers/i2c_emul.h>

#include "sim.h"
#include "tb/ina226.h"

struct ina_emul_data {
	uint8_t addr;
	uint32_t shunt_uohm;
	uint8_t ptr;
	uint16_t config, cal, me, limit;
	bool aff_latched;
};

#define MAX_INA 16
static struct ina_emul_data *all[MAX_INA];
static int n_all;

static int16_t shunt_raw(const struct ina_emul_data *d)
{
	int32_t ua, mv;
	int64_t lsb;

	sim_monitor(d->addr, &ua, &mv);
	lsb = (int64_t)ua * d->shunt_uohm / 2500000; /* uA x uohm = pV; 2.5 uV per LSB */
	return (int16_t)CLAMP(lsb, -32768, 32767);
}

static bool aff_now(const struct ina_emul_data *d)
{
	return (d->me & TB_INA226_ME_SOL) && shunt_raw(d) > (int16_t)d->limit;
}

bool sim_ina_any_alert(void)
{
	for (int i = 0; i < n_all; i++) {
		struct ina_emul_data *d = all[i];
		bool a = aff_now(d);

		if (a && (d->me & TB_INA226_ME_LEN)) {
			d->aff_latched = true;
		}
		if (a || d->aff_latched) {
			return true;
		}
	}
	return false;
}

static uint16_t reg_read(struct ina_emul_data *d, uint8_t reg)
{
	int32_t ua, mv;
	int16_t sh;
	int32_t cur;
	uint16_t bus;

	sim_monitor(d->addr, &ua, &mv);
	sh = shunt_raw(d);
	bus = (uint16_t)CLAMP(mv * 1000 / 1250, 0, 0x7FFF);
	cur = (int32_t)sh * d->cal / 2048;
	switch (reg) {
	case TB_INA226_REG_CONFIG:
		return d->config | 0x4000;
	case TB_INA226_REG_SHUNT:
		return (uint16_t)sh;
	case TB_INA226_REG_BUS:
		return bus;
	case TB_INA226_REG_POWER:
		return (uint16_t)CLAMP((int64_t)(cur < 0 ? -cur : cur) * bus / 20000, 0, 0xFFFF);
	case TB_INA226_REG_CURRENT:
		return (uint16_t)(int16_t)CLAMP(cur, -32768, 32767);
	case TB_INA226_REG_CAL:
		return d->cal;
	case TB_INA226_REG_MASK_ENABLE: {
		bool a = aff_now(d) || d->aff_latched;
		uint16_t v = (uint16_t)((d->me & 0xFC03) | (a ? TB_INA226_ME_AFF : 0) | TB_INA226_ME_CVRF);

		d->aff_latched = false;
		return v;
	}
	case TB_INA226_REG_ALERT_LIMIT:
		return d->limit;
	case TB_INA226_REG_MFR_ID:
		return TB_INA226_MFR_ID;
	case TB_INA226_REG_DIE_ID:
		return TB_INA226_DIE_ID;
	default:
		return 0;
	}
}

static void reg_write(struct ina_emul_data *d, uint8_t reg, uint16_t v)
{
	switch (reg) {
	case TB_INA226_REG_CONFIG:
		if (v & TB_INA226_CONFIG_RST) {
			d->config = TB_INA226_CONFIG_POR & 0x0FFF;
			d->cal = d->me = d->limit = 0;
		} else {
			d->config = v & 0x0FFF;
		}
		d->aff_latched = false;
		break;
	case TB_INA226_REG_CAL:
		d->cal = v & 0x7FFF;
		break;
	case TB_INA226_REG_MASK_ENABLE:
		d->me = v & 0xFC03;
		break;
	case TB_INA226_REG_ALERT_LIMIT:
		d->limit = v;
		break;
	default:
		break;
	}
}

static int ina_transfer(const struct emul *target, struct i2c_msg *msgs, int num_msgs, int addr)
{
	struct ina_emul_data *d = target->data;

	ARG_UNUSED(addr);
	sim_update();
	for (int i = 0; i < num_msgs; i++) {
		struct i2c_msg *m = &msgs[i];

		if (!(m->flags & I2C_MSG_READ)) {
			if (m->len >= 1) {
				d->ptr = m->buf[0];
			}
			if (m->len >= 3) {
				reg_write(d, d->ptr, (uint16_t)((m->buf[1] << 8) | m->buf[2]));
			}
		} else if (m->len >= 2) {
			uint16_t v = reg_read(d, d->ptr);

			m->buf[0] = (uint8_t)(v >> 8);
			m->buf[1] = (uint8_t)v;
		}
	}
	sim_update();
	return 0;
}

static const struct i2c_emul_api ina_api = {.transfer = ina_transfer};

static int ina_emul_init(const struct emul *target, const struct device *parent)
{
	struct ina_emul_data *d = target->data;

	ARG_UNUSED(parent);
	d->addr = (uint8_t)target->bus.i2c->addr;
	d->config = TB_INA226_CONFIG_POR & 0x0FFF;
	if (n_all < MAX_INA) {
		all[n_all++] = d;
	}
	return 0;
}

#define INA_EMUL(n)                                                                                \
	static struct ina_emul_data ina_emul_data_##n = {                                          \
		.shunt_uohm = DT_INST_PROP(n, rshunt_micro_ohms),                                  \
	};                                                                                         \
	EMUL_DT_INST_DEFINE(n, ina_emul_init, &ina_emul_data_##n, NULL, &ina_api, NULL)

DT_INST_FOREACH_STATUS_OKAY(INA_EMUL)
