/*
 * TUSB320LAI decoding (SLLSEQ8D Tables 7-9) and its budget mapping (nets.TUSB320_CURRENT_MODE, TYPEC_BUDGET).
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include <zephyr/ztest.h>

#include "tb/tusb320.h"

#define CSR09(attach, intr) ((uint8_t)(((attach) << 6) | ((intr) ? 0x10 : 0) | 0x20))
#define CSR08(mode) ((uint8_t)((mode) << 4))

ZTEST(tb_tusb320, test_device_id)
{
	const uint8_t good[8] = {'0', '2', '3', 'B', 'S', 'U', 'T', 0};
	const uint8_t rev[8] = {0, 'T', 'U', 'S', 'B', '3', '2', '0'};
	const uint8_t ff[8] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

	zassert_true(tb_tusb320_id_ok(good));
	zassert_false(tb_tusb320_id_ok(rev), "the string is stored last character first");
	zassert_false(tb_tusb320_id_ok(ff));
}

ZTEST(tb_tusb320, test_source_mapping)
{
	/* Attached.SNK: 00 Default, 01 Medium, 10 audio charge-through (500 mA), 11 High */
	zassert_equal(tb_tusb320_source(CSR08(0), CSR09(2, 0)), TB_SRC_DEFAULT);
	zassert_equal(tb_tusb320_source(CSR08(1), CSR09(2, 0)), TB_SRC_1A5);
	zassert_equal(tb_tusb320_source(CSR08(2), CSR09(2, 0)), TB_SRC_DEFAULT);
	zassert_equal(tb_tusb320_source(CSR08(3), CSR09(2, 0)), TB_SRC_3A0);
	for (int mode = 0; mode < 4; mode++) {
		zassert_equal(tb_tusb320_source(CSR08(mode), CSR09(0, 0)), TB_SRC_NOT_ATTACHED);
		zassert_equal(tb_tusb320_source(CSR08(mode), CSR09(3, 0)), TB_SRC_ACCESSORY);
		zassert_equal(tb_tusb320_source(CSR08(mode), CSR09(1, 0)), TB_SRC_UNREADABLE);
	}
	/* CURRENT_MODE_ADVERTISE (bits 7:6) and ACCESSORY_CONNECTED (3:1) do not leak into the decode */
	zassert_equal(tb_tusb320_source(0xC0 | CSR08(1) | 0x0E, CSR09(2, 1)), TB_SRC_1A5);
}

ZTEST(tb_tusb320, test_interrupt_clear)
{
	uint8_t r09 = CSR09(2, 1) | 0x06 | 0x01; /* DRP_DUTY_CYCLE 11, DISABLE_UFP_ACCESSORY 1 */

	zassert_true(tb_tusb320_int_pending(r09));
	zassert_false(tb_tusb320_int_pending(CSR09(2, 0)));
	zassert_equal(tb_tusb320_int_clear_value(r09), r09, "bit 4 already set: write it back");
	zassert_equal(tb_tusb320_int_clear_value(0x27), 0x37, "keeps the writable fields, sets bit 4");
	zassert_true(tb_tusb320_write_allowed(TB_TUSB320_REG_CSR09, 0x37, 0x27));
	zassert_false(tb_tusb320_write_allowed(TB_TUSB320_REG_CSR09, 0x36, 0x27));
	zassert_false(tb_tusb320_write_allowed(TB_TUSB320_REG_CSR0A, 0x01, 0x27), "DISABLE_TERM");
	zassert_false(tb_tusb320_write_allowed(TB_TUSB320_REG_CSR0A, 0x08, 0x27), "I2C_SOFT_RESET");
	zassert_false(tb_tusb320_write_allowed(TB_TUSB320_REG_CSR45, 0x04, 0x27), "DISABLE_RD_RP");
	zassert_false(tb_tusb320_write_allowed(TB_TUSB320_REG_CSR08, 0x40, 0x27), "CURRENT_MODE_ADVERTISE");
}

ZTEST_SUITE(tb_tusb320, NULL, NULL, NULL, NULL, NULL);
