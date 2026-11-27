/*
 * Simulated board: the TCA9548A's control register (one byte; bit n = channel n).
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#define DT_DRV_COMPAT ti_tca9548a

#include <zephyr/device.h>
#include <zephyr/drivers/emul.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/drivers/i2c_emul.h>

#include "sim.h"

static int mux_transfer(const struct emul *target, struct i2c_msg *msgs, int num_msgs, int addr)
{
	ARG_UNUSED(target);
	ARG_UNUSED(addr);
	for (int i = 0; i < num_msgs; i++) {
		if (msgs[i].len == 0) {
			continue;
		}
		if (msgs[i].flags & I2C_MSG_READ) {
			msgs[i].buf[0] = sim.mux_ctrl;
		} else {
			sim.mux_ctrl = msgs[i].buf[msgs[i].len - 1];
		}
	}
	return 0;
}

static const struct i2c_emul_api mux_api = {.transfer = mux_transfer};

static int mux_emul_init(const struct emul *target, const struct device *parent)
{
	ARG_UNUSED(target);
	ARG_UNUSED(parent);
	return 0;
}

EMUL_DT_INST_DEFINE(0, mux_emul_init, NULL, NULL, &mux_api, NULL);
