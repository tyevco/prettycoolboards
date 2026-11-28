/*
 * Simulated board: every coupon's M24C02 at 0x50, behind the slot mux. It answers for the slot whose channel is
 * selected, and only while that slot's +3V3 is on and a coupon is in it (else no ACK). Page writes wrap within
 * their 16-byte page (ST DocID024020 §5.1.2); the write cycle is instantaneous here.
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#define DT_DRV_COMPAT prettycool_sim_eeprom

#include <zephyr/device.h>
#include <zephyr/drivers/emul.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/drivers/i2c_emul.h>

#include "sim.h"

static uint8_t ptr;

DEVICE_DT_INST_DEFINE(0, NULL, NULL, NULL, NULL, POST_KERNEL, 99, NULL);

static int selected_slot(void)
{
	for (int ch = 0; ch < TB_SLOTS; ch++) {
		if (sim.mux_ctrl & BIT(ch)) {
			return ch + 1;
		}
	}
	return 0;
}

static int ee_transfer(const struct emul *target, struct i2c_msg *msgs, int num_msgs, int addr)
{
	int slot = selected_slot();

	ARG_UNUSED(target);
	ARG_UNUSED(addr);
	sim_update();
	/* SIM_TURNED: the slot's SCL meets the turned coupon's GND, so nothing on the channel answers (sim.h) */
	if (slot == 0 || sim.coupon[slot - 1] == SIM_NONE || sim.coupon[slot - 1] == SIM_TURNED ||
	    !sim.on[tb_rail_3v3(slot)]) {
		return -EIO;
	}
	for (int i = 0; i < num_msgs; i++) {
		struct i2c_msg *m = &msgs[i];

		if (!(m->flags & I2C_MSG_READ)) {
			if (m->len >= 1) {
				ptr = m->buf[0];
			}
			for (uint32_t k = 1; k < m->len; k++) {
				sim.eeprom[slot - 1][ptr] = m->buf[k];
				ptr = (uint8_t)((ptr & 0xF0) | ((ptr + 1) & 0x0F));
			}
		} else {
			for (uint32_t k = 0; k < m->len; k++) {
				m->buf[k] = sim.eeprom[slot - 1][ptr++];
			}
		}
	}
	return 0;
}

static const struct i2c_emul_api ee_api = {.transfer = ee_transfer};

static int ee_emul_init(const struct emul *target, const struct device *parent)
{
	ARG_UNUSED(target);
	ARG_UNUSED(parent);
	return 0;
}

EMUL_DT_INST_DEFINE(0, ee_emul_init, NULL, NULL, &ee_api, NULL);
