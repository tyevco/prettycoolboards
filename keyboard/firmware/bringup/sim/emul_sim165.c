/*
 * Simulated board: the test coupon's SN74LV165A + SN74LVC1G125 loopback on SPI2, on the slot whose bus switch is
 * closed. With that slot powered and its CS0_N driven low it returns G0..G5, INJ (0: JP_INJ open), SYNC as the
 * first byte and the bytes sent on MOSI one byte late; otherwise MISO floats (0xFF here). The parallel load is
 * taken at the transfer, not at the CS1_N strobe: a dead CS1_N would go unnoticed in this model.
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#define DT_DRV_COMPAT prettycool_sim_165

#include <string.h>

#include <zephyr/device.h>
#include <zephyr/drivers/emul.h>
#include <zephyr/drivers/spi.h>
#include <zephyr/drivers/spi_emul.h>

#include "board.h"
#include "sim.h"

DEVICE_DT_INST_DEFINE(0, NULL, NULL, NULL, NULL, POST_KERNEL, 99, NULL);

static int lb_io(const struct emul *target, const struct spi_config *config, const struct spi_buf_set *tx,
		 const struct spi_buf_set *rx)
{
	uint8_t out[16];
	size_t n = 0;
	int slot;

	ARG_UNUSED(target);
	ARG_UNUSED(config);
	sim_update();
	slot = sim_bus_slot();
	if (rx == NULL || rx->count == 0) {
		return 0;
	}
	n = MIN(rx->buffers[0].len, sizeof(out));
	memset(out, 0xFF, sizeof(out));
	if (slot != 0 && sim_test_coupon_powered(slot) && sim_mcu_out(&tb_slots[slot - 1].cs[0]) == 0) {
		uint8_t hi = 0;
		const uint8_t *t = (tx != NULL && tx->count > 0) ? tx->buffers[0].buf : NULL;

		for (int g = 0; g < 6; g++) {
			if (sim_gline(slot, g)) {
				hi |= (uint8_t)(0x80u >> g);
			}
		}
		if (sim_mcu_out(&tb_sig.slot_sync) == 1) {
			hi |= 0x01;
		}
		out[0] = hi;
		for (size_t k = 1; k < n; k++) {
			out[k] = t != NULL ? t[k - 1] : 0;
		}
	}
	if (rx->buffers[0].buf != NULL) {
		memcpy(rx->buffers[0].buf, out, n);
	}
	return 0;
}

static const struct spi_emul_api lb_api = {.io = lb_io};

static int lb_emul_init(const struct emul *target, const struct device *parent)
{
	ARG_UNUSED(target);
	ARG_UNUSED(parent);
	return 0;
}

EMUL_DT_INST_DEFINE(0, lb_emul_init, NULL, NULL, &lb_api, NULL);
