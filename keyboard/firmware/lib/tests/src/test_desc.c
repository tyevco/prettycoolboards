/*
 * The coupon descriptor (format 1.0, a proposal): the C parser against the Python reference encoder
 * (keyboard/firmware/lib/tools/coupon_desc.py, run at build time), byte-exact re-encoding, and the errors.
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include <string.h>
#include <zephyr/ztest.h>

#include "tb/desc.h"
#include "tb/selftest.h"
#include "tb_desc_vectors.h"

static uint8_t buf[TB_DESC_MAX_LEN];

static void refresh_crc(uint8_t *p, size_t len)
{
	uint16_t crc = tb_crc16_ccitt(p, len - 2);

	p[len - 2] = (uint8_t)crc;
	p[len - 1] = (uint8_t)(crc >> 8);
}

ZTEST(tb_desc, test_crc_check_value)
{
	zassert_equal(tb_crc16_ccitt((const uint8_t *)"123456789", 9), 0x29B1);
}

ZTEST(tb_desc, test_python_test_coupon)
{
	struct tb_desc d;

	zassert_equal(tb_desc_parse(vec_test_coupon, sizeof(vec_test_coupon), &d), TB_DESC_OK);
	zassert_equal(d.type, TB_COUPON_TEST);
	zassert_equal(d.rev, 'A');
	zassert_equal(d.serial, 0x12345678);
	zassert_equal(d.i3v3_ma, 120);
	zassert_equal(d.i5v_ma, 170);
	zassert_equal(d.c3v3_uf, 10);
	zassert_equal(d.c5v_uf, 22);
	zassert_equal(strcmp(d.name, "test coupon A"), 0);
	zassert_equal(d.length, sizeof(vec_test_coupon));
	for (int k = 0; k < 4; k++) {
		zassert_true(d.lane[k].present);
		zassert_true(d.lane[k].flags & TB_LANE_F_RATIOMETRIC);
	}
	/* 0.2 / 0.4 / 0.6 / 0.8 of the coupon's +3V3, within a few ppm of Q16 rounding */
	zassert_within(tb_q16_to_ppm(d.lane[0].expect_q16), 200000, 10);
	zassert_within(tb_q16_to_ppm(d.lane[3].expect_q16), 800000, 10);
	zassert_equal(d.lane[1].r_src_ohm, 599);
	zassert_equal(d.lane[0].r_src_ohm, 399);
	zassert_equal(d.spi[0].mode, 3);
	zassert_equal(d.gline_role[0], TB_G_LOAD);
	zassert_equal(d.gline_role[4], TB_G_LED);
	zassert_equal(d.gline_role[5], TB_G_IRQ_TEST);
	zassert_equal(d.n_i2c, 1);
	zassert_equal(d.i2c[0].addr, 0x50);
	zassert_equal(d.n_spi, 1);
	zassert_equal(d.spi[0].max_hz, 1000000);
	zassert_true(d.load[1].present && d.load[1].kind == 1 && d.load[1].r_mohm == 5000);
	zassert_equal(d.load[3].slot_mask, 0x0F, "the 5 V current-limit load never runs on S5");
	zassert_equal(d.slot_mask, TB_DESC_ALL_SLOTS);
	zassert_equal(d.n_unknown, 0);
}

/* The C encoder reproduces the Python encoder's bytes. */
ZTEST(tb_desc, test_reencode_is_byte_exact)
{
	struct tb_desc d;
	int n;

	zassert_ok(tb_desc_parse(vec_test_coupon, sizeof(vec_test_coupon), &d));
	n = tb_desc_encode(&d, buf, sizeof(buf));
	zassert_equal(n, (int)sizeof(vec_test_coupon));
	zassert_mem_equal(buf, vec_test_coupon, sizeof(vec_test_coupon));
	zassert_ok(tb_desc_parse(vec_minimal_hall, sizeof(vec_minimal_hall), &d));
	n = tb_desc_encode(&d, buf, sizeof(buf));
	zassert_equal(n, (int)sizeof(vec_minimal_hall));
	zassert_mem_equal(buf, vec_minimal_hall, sizeof(vec_minimal_hall));
}

/* The C twin of the Python test coupon builder gives the same bytes. */
ZTEST(tb_desc, test_c_test_coupon_matches_python)
{
	struct tb_desc d;
	int n;

	tb_desc_test_coupon(&d, 0x12345678);
	n = tb_desc_encode(&d, buf, sizeof(buf));
	zassert_equal(n, (int)sizeof(vec_test_coupon));
	zassert_mem_equal(buf, vec_test_coupon, sizeof(vec_test_coupon));
}

ZTEST(tb_desc, test_unknown_record_skipped)
{
	struct tb_desc d;

	zassert_equal(tb_desc_parse(vec_unknown_record, sizeof(vec_unknown_record), &d), TB_DESC_OK);
	zassert_equal(d.type, TB_COUPON_COIL);
	zassert_equal(d.n_unknown, 1);
	zassert_equal(d.slot_mask, 0x18);
	zassert_true(d.flags & TB_DESC_F_WIDE);
}

ZTEST(tb_desc, test_errors)
{
	struct tb_desc d;
	size_t n = sizeof(vec_test_coupon);

	memset(buf, 0xFF, sizeof(buf));
	zassert_equal(tb_desc_parse(buf, sizeof(buf), &d), TB_DESC_ERR_BLANK);
	zassert_equal(tb_desc_parse(vec_test_coupon, 7, &d), TB_DESC_ERR_SHORT);
	zassert_equal(tb_desc_parse(vec_test_coupon, n - 1, &d), TB_DESC_ERR_SHORT);

	memcpy(buf, vec_test_coupon, n);
	buf[n - 1] ^= 1;
	zassert_equal(tb_desc_parse(buf, n, &d), TB_DESC_ERR_CRC);

	memcpy(buf, vec_test_coupon, n);
	buf[0] = 'X';
	zassert_equal(tb_desc_parse(buf, n, &d), TB_DESC_ERR_MAGIC);

	memcpy(buf, vec_test_coupon, n);
	buf[4] = 2;
	zassert_equal(tb_desc_parse(buf, n, &d), TB_DESC_ERR_VERSION);

	memcpy(buf, vec_test_coupon, n);
	buf[6] = 10;
	buf[7] = 0;
	zassert_equal(tb_desc_parse(buf, n, &d), TB_DESC_ERR_LENGTH);

	/* the first record (NAME) claims more bytes than there are */
	memcpy(buf, vec_test_coupon, n);
	buf[TB_DESC_HEADER_LEN + 1] = 250;
	refresh_crc(buf, n);
	zassert_equal(tb_desc_parse(buf, n, &d), TB_DESC_ERR_RECORD);

	/* a lane index of 4 */
	{
		struct tb_desc e;

		tb_desc_init(&e);
		e.type = TB_COUPON_HALL;
		e.lane[0].present = true;
		n = (size_t)tb_desc_encode(&e, buf, sizeof(buf));
		zassert_equal(buf[TB_DESC_HEADER_LEN], TB_DESC_REC_LANE);
		buf[TB_DESC_HEADER_LEN + 2] = 4;
		refresh_crc(buf, n);
		zassert_equal(tb_desc_parse(buf, n, &d), TB_DESC_ERR_VALUE);
		/* the same lane twice: append a copy of the record */
		buf[TB_DESC_HEADER_LEN + 2] = 0;
		memcpy(&buf[n - 2], &buf[TB_DESC_HEADER_LEN], 12);
		n += 12;
		buf[6] = (uint8_t)n;
		refresh_crc(buf, n);
		zassert_equal(tb_desc_parse(buf, n, &d), TB_DESC_ERR_DUP);
	}
}

ZTEST(tb_desc, test_encode_limits)
{
	struct tb_desc d;

	tb_desc_init(&d);
	d.type = TB_COUPON_TEST;
	d.rev = 'a';
	zassert_equal(tb_desc_encode(&d, buf, sizeof(buf)), TB_DESC_ERR_VALUE, "lower-case revision");
	d.rev = 'A';
	strcpy(d.name, "tab\there");
	zassert_equal(tb_desc_encode(&d, buf, sizeof(buf)), TB_DESC_ERR_VALUE, "non-printable name");
	d.name[0] = '\0';
	zassert_equal(tb_desc_encode(&d, buf, 20), TB_DESC_ERR_SPACE);
	d.n_cal = TB_DESC_MAX_CAL;
	d.n_i2c = TB_DESC_MAX_I2C;
	for (int i = 0; i < TB_DESC_MAX_I2C; i++) {
		d.i2c[i].addr = (uint8_t)(0x10 + i);
	}
	zassert_true(tb_desc_encode(&d, buf, sizeof(buf)) > 0);
	zassert_equal(tb_desc_encode(&d, buf, 60), TB_DESC_ERR_SPACE);
}

ZTEST(tb_desc, test_slot_rules)
{
	struct tb_desc d;

	zassert_ok(tb_desc_parse(vec_test_coupon, sizeof(vec_test_coupon), &d));
	for (int s = 1; s <= 5; s++) {
		zassert_is_null(tb_desc_check_slot(&d, s, 250, s == 5 ? 2000 : 500));
	}
	zassert_ok(tb_desc_parse(vec_unknown_record, sizeof(vec_unknown_record), &d));
	zassert_equal(strcmp(tb_desc_check_slot(&d, 1, 250, 500), "slot_not_allowed"), 0);
	d.slot_mask = TB_DESC_ALL_SLOTS;
	zassert_equal(strcmp(tb_desc_check_slot(&d, 2, 250, 500), "wide_coupon"), 0);
	zassert_is_null(tb_desc_check_slot(&d, 4, 250, 500));
	d.i3v3_ma = 251;
	zassert_equal(strcmp(tb_desc_check_slot(&d, 4, 250, 500), "over_3v3_rule"), 0);
	d.i3v3_ma = 10;
	d.i5v_ma = 501;
	zassert_equal(strcmp(tb_desc_check_slot(&d, 4, 250, 500), "over_5v_rule"), 0);
	zassert_is_null(tb_desc_check_slot(&d, 5, 250, 2000));
	zassert_equal(strcmp(tb_desc_check_slot(&d, 6, 250, 500), "bad_slot"), 0);
}

ZTEST_SUITE(tb_desc, NULL, NULL, NULL, NULL, NULL);
