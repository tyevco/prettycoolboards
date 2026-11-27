/*
 * Simulated board: a TCA9535 register model (TI SCPS201D) for the nxp,pca95xx nodes. Registers 0/1 input,
 * 2/3 output, 4/5 polarity inversion, 6/7 configuration (1 = input); a command byte selects a register and data
 * then alternates between the two registers of its pair. Reading an input register clears INT.
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#define DT_DRV_COMPAT nxp_pca95xx

#include <zephyr/device.h>
#include <zephyr/drivers/emul.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/drivers/i2c_emul.h>

#include "board.h"
#include "sim.h"

struct exp_emul_data {
	int index;
	uint8_t ptr;
};

static uint8_t reg_read(int e, uint8_t reg)
{
	struct sim_exp *x = &sim.exp[e];
	uint16_t v;

	switch (reg & 0x6) {
	case 0x0:
		v = sim_exp_inputs(e);
		x->last_read = v;
		x->int_pending = false;
		break;
	case 0x2:
		v = x->out;
		break;
	case 0x4:
		v = x->pol;
		break;
	default:
		v = x->cfg;
		break;
	}
	return (reg & 1) ? (uint8_t)(v >> 8) : (uint8_t)v;
}

static void reg_write(int e, uint8_t reg, uint8_t val)
{
	struct sim_exp *x = &sim.exp[e];
	uint16_t *t = (reg & 0x6) == 0x2 ? &x->out : (reg & 0x6) == 0x4 ? &x->pol : (reg & 0x6) == 0x6 ? &x->cfg
												  : NULL;

	if (t == NULL) {
		return; /* the input registers are read only */
	}
	if (reg & 1) {
		*t = (uint16_t)((*t & 0x00FF) | ((uint16_t)val << 8));
	} else {
		*t = (uint16_t)((*t & 0xFF00) | val);
	}
}

static int exp_transfer(const struct emul *target, struct i2c_msg *msgs, int num_msgs, int addr)
{
	struct exp_emul_data *d = target->data;

	ARG_UNUSED(addr);
	sim_update();
	for (int i = 0; i < num_msgs; i++) {
		struct i2c_msg *m = &msgs[i];

		if (!(m->flags & I2C_MSG_READ)) {
			if (m->len < 1) {
				continue;
			}
			d->ptr = m->buf[0] & 7;
			for (uint32_t k = 1; k < m->len; k++) {
				reg_write(d->index, d->ptr, m->buf[k]);
				d->ptr ^= 1;
			}
		} else {
			for (uint32_t k = 0; k < m->len; k++) {
				m->buf[k] = reg_read(d->index, d->ptr);
				d->ptr ^= 1;
			}
		}
	}
	sim_update();
	return 0;
}

static const struct i2c_emul_api exp_api = {.transfer = exp_transfer};

static int exp_emul_init(const struct emul *target, const struct device *parent)
{
	struct exp_emul_data *d = target->data;
	static const uint8_t addrs[TB_EXP_COUNT] = TB_EXP_ADDRS;

	ARG_UNUSED(parent);
	for (int e = 0; e < TB_EXP_COUNT; e++) {
		if (addrs[e] == target->bus.i2c->addr) {
			d->index = e;
		}
	}
	return 0;
}

#define EXP_EMUL(n)                                                                                \
	static struct exp_emul_data exp_emul_data_##n;                                             \
	EMUL_DT_INST_DEFINE(n, exp_emul_init, &exp_emul_data_##n, NULL, &exp_api, NULL)

DT_INST_FOREACH_STATUS_OKAY(EXP_EMUL)
