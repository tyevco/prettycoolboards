/*
 * The test coupon's descriptor (format 1.0, a proposal), the C twin of tools/coupon_desc.py's test_coupon().
 * The lib's tests encode both and compare the bytes. The design it follows is
 * keyboard/hardware/design/sheets/test_coupon.py: a 5 x 499 ohm lane ladder (AN0..AN3 = 0.2..0.8 of +3V3,
 * R_src 399 / 599 / 599 / 399 ohm), loads G0 30 ohm (+3V3), G1 5 ohm (+3V3, current limit), G2 30 ohm (+5V),
 * G3 3.33 ohm (+5V, current limit, never on S5), the LED on G4, the IRQ_N test on G5, the '165 loopback on SPI.
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include <string.h>

#include "tb/desc.h"

void tb_desc_test_coupon(struct tb_desc *d, uint32_t serial)
{
	static const uint16_t expect[4] = {13107, 26214, 39322, 52429}; /* 0.2, 0.4, 0.6, 0.8 in Q16 */
	static const uint16_t r_src[4] = {399, 599, 599, 399};
	static const struct {
		uint8_t gline, rail, kind;
		uint16_t r_mohm;
		uint8_t slots;
	} loads[4] = {
		{0, 0, 0, 30000, TB_DESC_ALL_SLOTS},
		{1, 0, 1, 5000, TB_DESC_ALL_SLOTS},
		{2, 1, 0, 30000, TB_DESC_ALL_SLOTS},
		{3, 1, 1, 3333, 0x0F}, /* never on S5 */
	};

	tb_desc_init(d);
	d->type = TB_COUPON_TEST;
	d->rev = 'A';
	d->serial = serial;
	d->i3v3_ma = 120;
	d->i5v_ma = 170;
	d->c3v3_uf = 10;
	d->c5v_uf = 22;
	strcpy(d->name, "test coupon A");
	for (int k = 0; k < 4; k++) {
		d->lane[k].present = true;
		d->lane[k].flags = TB_LANE_F_USED | TB_LANE_F_RATIOMETRIC;
		d->lane[k].r_src_ohm = r_src[k];
		d->lane[k].cload_pf = 0;
		d->lane[k].expect_q16 = expect[k];
		d->lane[k].tol_q16 = 655; /* 1 % */
	}
	for (int g = 0; g < 4; g++) {
		d->gline_role[g] = TB_G_LOAD;
		d->gline_arg[g] = (uint8_t)g;
	}
	d->gline_role[4] = TB_G_LED;
	d->gline_role[5] = TB_G_IRQ_TEST;
	d->n_i2c = 1;
	d->i2c[0].addr = 0x50;
	d->i2c[0].kind = TB_I2C_EEPROM;
	d->n_spi = 1;
	d->spi[0].cs = 0;
	d->spi[0].mode = 3;
	d->spi[0].max_hz = 1000000;
	for (int i = 0; i < 4; i++) {
		d->load[i].present = true;
		d->load[i].gline = loads[i].gline;
		d->load[i].rail = loads[i].rail;
		d->load[i].kind = loads[i].kind;
		d->load[i].r_mohm = loads[i].r_mohm;
		d->load[i].slot_mask = loads[i].slots;
	}
}
