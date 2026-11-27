/*
 * Simulated board: U_CC, a TUSB320LAI register model (TI SLLSEQ8D Tables 7-12). Writes other than the
 * INTERRUPT_STATUS clear are counted as violations of SPEC §8.4 ("never written") and ignored.
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#define DT_DRV_COMPAT prettycool_tusb320

#include <zephyr/device.h>
#include <zephyr/drivers/emul.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/drivers/i2c_emul.h>

#include "sim.h"

static uint8_t ptr;
uint32_t sim_cc_violations;

/* No driver binds U_CC; the emulator needs a device for its node. */
DEVICE_DT_INST_DEFINE(0, NULL, NULL, NULL, NULL, POST_KERNEL, 99, NULL);

static uint8_t reg(uint8_t r)
{
	static const uint8_t id[8] = {'0', '2', '3', 'B', 'S', 'U', 'T', 0};

	if (r < 8) {
		return id[r];
	}
	switch (r) {
	case 0x08:
		return (uint8_t)(sim.cc_mode << 4);
	case 0x09:
		return (uint8_t)((sim.cc_attach << 6) | 0x20 | (sim.cc_int ? 0x10 : 0));
	case 0xA0:
		return 0x02;
	default:
		return 0;
	}
}

static int cc_transfer(const struct emul *target, struct i2c_msg *msgs, int num_msgs, int addr)
{
	ARG_UNUSED(target);
	ARG_UNUSED(addr);
	if (sim.cc_absent) {
		return -EIO;
	}
	for (int i = 0; i < num_msgs; i++) {
		struct i2c_msg *m = &msgs[i];

		if (!(m->flags & I2C_MSG_READ)) {
			if (m->len >= 1) {
				ptr = m->buf[0];
			}
			for (uint32_t k = 1; k < m->len; k++, ptr++) {
				if (ptr == 0x09 && (m->buf[k] & 0x10)) {
					sim.cc_int = false; /* RCU: a 1 clears INTERRUPT_STATUS */
				} else {
					sim_cc_violations++;
				}
			}
		} else {
			for (uint32_t k = 0; k < m->len; k++) {
				m->buf[k] = reg(ptr++);
			}
		}
	}
	sim_update();
	return 0;
}

static const struct i2c_emul_api cc_api = {.transfer = cc_transfer};

static int cc_emul_init(const struct emul *target, const struct device *parent)
{
	ARG_UNUSED(target);
	ARG_UNUSED(parent);
	return 0;
}

EMUL_DT_INST_DEFINE(0, cc_emul_init, NULL, NULL, &cc_api, NULL);
