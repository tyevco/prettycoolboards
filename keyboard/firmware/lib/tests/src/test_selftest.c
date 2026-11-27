/*
 * Lane and test-coupon arithmetic (SPEC §3.1, §10 step 7), on a model of the coupon.
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include <zephyr/ztest.h>

#include "tb/selftest.h"

ZTEST(tb_selftest, test_ratios)
{
	int32_t err;

	zassert_equal(tb_lane_ratio_ppm(3277, 14), 200012);
	zassert_equal(tb_lane_ratio_ppm(16384, 14), 1000000);
	zassert_equal(tb_lane_ratio_ppm(0, 12), 0);
	zassert_equal(tb_lane_ratio_ppm(1, 0), 0);
	zassert_equal(tb_q16_to_ppm(13107), 199997);
	zassert_equal(tb_q16_to_ppm(65535), 999985);
	zassert_true(tb_lane_check(3277, 14, 200000, 10000, &err));
	zassert_equal(err, 12);
	zassert_false(tb_lane_check(3500, 14, 200000, 10000, &err));
	/* the same lane on a 14-bit and a 12-bit converter */
	zassert_true(tb_lanes_agree(6554, 14, 1638, 12, 2000, &err));
	zassert_equal(err, 122);
	zassert_equal(tb_lane_state(100, 14), TB_LANE_LOW);
	zassert_equal(tb_lane_state(8000, 14), TB_LANE_MID);
	zassert_equal(tb_lane_state(16300, 14), TB_LANE_HIGH);
}

/* The coupon model: tap = k (VREF - I Rs); ratio = tap / VREF. */
static uint32_t model_ppm(uint32_t k_ppm, int32_t i_ua, uint32_t rs_mohm, uint32_t vref_mv)
{
	int64_t drop_ppm = (int64_t)i_ua * rs_mohm / vref_mv; /* uA x mOhm / mV = ppm of VREF */

	return (uint32_t)((int64_t)k_ppm * (1000000 - drop_ppm) / 1000000);
}

ZTEST(tb_selftest, test_series_resistance)
{
	const uint32_t ks[4] = {200000, 400000, 600000, 800000};
	int32_t rs;

	/* 350 mOhm (0.24 ohm shunt + about 85 mOhm switch + jumper), idle 1.4 mA, G0 load 110 mA more */
	for (int i = 0; i < 4; i++) {
		uint32_t r0 = model_ppm(ks[i], 1400, 350, 3300);
		uint32_t r1 = model_ppm(ks[i], 111400, 350, 3300);

		zassert_ok(tb_series_mohm(r0, r1, 1400, 111400, 3300, &rs));
		zassert_within(rs, 350, 3, "lane %d: %d mOhm", i, rs);
	}
	zassert_equal(tb_series_mohm(800000, 790000, 1000, 1000, 3300, &rs), -1, "no current step");
	zassert_equal(tb_series_mohm(790000, 800000, 1000, 111000, 3300, &rs), -1, "ratio rose");
}

ZTEST(tb_selftest, test_loopback)
{
	struct tb_loopback lb;

	zassert_equal(tb_loopback_expect(0x01, false, false, 0xA5), 0x80A5, "G0 is the first bit out");
	zassert_equal(tb_loopback_expect(0x20, false, false, 0x00), 0x0400, "G5");
	zassert_equal(tb_loopback_expect(0, true, false, 0x00), 0x0200, "INJ");
	zassert_equal(tb_loopback_expect(0, false, true, 0x5A), 0x015A, "SYNC is the last of the eight");
	for (unsigned g = 0; g < 64; g++) {
		for (int x = 0; x < 4; x++) {
			uint16_t w = tb_loopback_expect((uint8_t)g, x & 1, x & 2, (uint8_t)(g * 7));

			tb_loopback_decode(w, &lb);
			zassert_equal(lb.g, g);
			zassert_equal(lb.inj, (bool)(x & 1));
			zassert_equal(lb.sync, (bool)(x & 2));
			zassert_equal(lb.echo, (uint8_t)(g * 7));
		}
	}
}

ZTEST(tb_selftest, test_loads)
{
	const uint32_t trip_3v3[3] = {256, 292, 335};
	int32_t exp;

	/* G0: 30 ohm on +3V3 */
	zassert_true(tb_load_step_ok(1400, 111400, 3300, 30000, 5, &exp));
	zassert_equal(exp, 110000);
	zassert_false(tb_load_step_ok(1400, 51400, 3300, 30000, 5, &exp), "half the load: an open resistor");
	/* G2: 30 ohm on +5V */
	zassert_true(tb_load_step_ok(0, 165000, 4980, 30000, 5, &exp));
	zassert_false(tb_load_step_ok(0, 1, 3300, 0, 5, &exp));
	/* G1 into the TPS2553's limit */
	zassert_true(tb_climit_ok(292000, trip_3v3, 3));
	zassert_true(tb_climit_ok(249000, trip_3v3, 3));
	zassert_false(tb_climit_ok(248000, trip_3v3, 3));
	zassert_false(tb_climit_ok(346000, trip_3v3, 3));
	zassert_false(tb_climit_ok(660000, trip_3v3, 3), "unlimited: the switch did not limit");
}

ZTEST_SUITE(tb_selftest, NULL, NULL, NULL, NULL, NULL);
