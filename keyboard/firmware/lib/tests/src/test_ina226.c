/*
 * INA226 arithmetic against the datasheet's worked example (SBOS547 §7.5.1) and the SPEC §3.4 figures.
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include <zephyr/ztest.h>

#include "tb/ina226.h"
#include "tb_board_map.h"

struct ina_row {
	uint8_t addr;
	const char *rail;
	uint32_t shunt_uohm, lsb_ua, cal;
	int rail_id;
	uint32_t rule_ma, tmin, ttyp, tmax;
};
static const struct ina_row ina[] = TB_INA226_TABLE;

/* SBOS547 §7.5.1: 2 mOhm, Current_LSB 1 mA -> CAL 2560; shunt register 8000 (20 mV) -> current 10000 (10 A);
 * bus register 9584 -> 11.98 V; power register 4792 -> 119.8 W. */
ZTEST(tb_ina226, test_datasheet_example)
{
	zassert_equal(tb_ina226_cal(1000, 2000), 2560);
	zassert_equal(tb_ina226_expected_current_raw(8000, 2560), 10000);
	zassert_equal(tb_ina226_shunt_nv(8000), 20000000);
	zassert_equal(tb_ina226_current_ua(10000, 1000), 10000000);
	zassert_equal(tb_ina226_shunt_current_ua(8000, 2000), 10000000);
	zassert_equal(tb_ina226_bus_uv(9584), 11980000);
	zassert_equal(tb_ina226_power_uw(4792, 1000), 119800000);
}

/* SPEC §3.4: CAL 1939 on the slot 3.3 V monitors (11 uA), 2048 on VSYS, +3V3_MCU, +5V_S1-S5, 1707 on +3V3_USB;
 * and 10 uA on 0.24 ohm would give CAL 2133 and clip at about 328 mA, below the switch's 335 mA maximum. */
ZTEST(tb_ina226, test_spec_cal_values)
{
	zassert_equal(tb_ina226_cal(11, 240000), 1939);
	zassert_equal(tb_ina226_cal(125, 20000), 2048);
	zassert_equal(tb_ina226_cal(5, 500000), 2048);
	zassert_equal(tb_ina226_cal(25, 100000), 2048);
	zassert_equal(tb_ina226_cal(3, 1000000), 1707);
	zassert_equal(tb_ina226_cal(10, 240000), 2133);
	zassert_equal(tb_ina226_current_clip_ua(10), 327670);
	zassert_false(tb_ina226_lsb_covers_full_scale(10, 240000));
	zassert_true(tb_ina226_lsb_covers_full_scale(11, 240000));
	zassert_equal(tb_ina226_min_lsb_ua(240000), 11);
	zassert_equal(tb_ina226_min_lsb_ua(1000000), 3);
	zassert_equal(tb_ina226_full_scale_ua(240000), 341333);
	zassert_equal(tb_ina226_full_scale_ua(20000), 4096000);
}

/* Every monitor of the generated map: its LSB covers its shunt's full scale, the generator's CAL equals the
 * lib's (Zephyr's driver formula), and its switch's maximum trip is inside the full scale (nets.check()). */
ZTEST(tb_ina226, test_board_map_monitors)
{
	zassert_equal(ARRAY_SIZE(ina), TB_INA226_COUNT);
	for (size_t i = 0; i < ARRAY_SIZE(ina); i++) {
		const struct ina_row *r = &ina[i];

		zassert_true(tb_ina226_lsb_covers_full_scale(r->lsb_ua, r->shunt_uohm), "%s", r->rail);
		zassert_equal(tb_ina226_cal(r->lsb_ua, r->shunt_uohm), r->cal, "%s", r->rail);
		zassert_true(r->tmax * 1000u <= tb_ina226_full_scale_ua(r->shunt_uohm), "%s", r->rail);
		zassert_true(r->tmax * 1000u <= tb_ina226_current_clip_ua(r->lsb_ua), "%s", r->rail);
		if (r->rule_ma != 0) {
			zassert_true(r->tmin > r->rule_ma, "%s: trip min above the rule", r->rail);
		}
	}
}

ZTEST(tb_ina226, test_config)
{
	uint32_t avg, vb, vs;
	enum tb_ina226_mode mode;

	tb_ina226_config_decode(TB_INA226_CONFIG_POR, &avg, &vb, &vs, &mode);
	zassert_equal(avg, 1);
	zassert_equal(vb, 1100);
	zassert_equal(vs, 1100);
	zassert_equal(mode, TB_INA226_MODE_BOTH_CONT);
	zassert_equal(tb_ina226_config(1, 1100, 1100, TB_INA226_MODE_BOTH_CONT),
		      TB_INA226_CONFIG_POR & TB_INA226_CONFIG_MASK);
	zassert_equal(tb_ina226_config(16, 1100, 1100, TB_INA226_MODE_BOTH_CONT), 0x0527);
	zassert_equal(tb_ina226_config(1, 140, 140, TB_INA226_MODE_SHUNT_CONT), 0x0005);
	zassert_equal(tb_ina226_config(3, 1100, 1100, TB_INA226_MODE_BOTH_CONT), -1);
	zassert_equal(tb_ina226_config(1, 1000, 1100, TB_INA226_MODE_BOTH_CONT), -1);
	zassert_equal(tb_ina226_sample_period_us(0x0127), 2200);
	zassert_equal(tb_ina226_sample_period_us(0x0527), 35200);
	zassert_equal(tb_ina226_sample_period_us(0x0005), 140);
	zassert_equal(tb_ina226_sample_period_us(0x0003), 0);
	/* SPEC §3.4: one rail at 140 us shunt-only */
	zassert_equal(tb_ina226_sample_period_us((uint16_t)tb_ina226_config(1, 140, 140, TB_INA226_MODE_SHUNT_CONT)),
		      140);
}

ZTEST(tb_ina226, test_alert_limits)
{
	/* the 2.8 A VSYS ceiling on the 20 mOhm shunt */
	zassert_equal(tb_ina226_sol_limit(2800000, 20000), 22400);
	zassert_equal(tb_ina226_sol_current_ua(22400, 20000), 2800000);
	/* 250 mA on a 0.24 ohm slot shunt */
	zassert_equal(tb_ina226_sol_limit(250000, 240000), 24000);
	/* rounded up: never below the asked current */
	zassert_equal(tb_ina226_sol_limit(1, 240000), 1);
	zassert_true(tb_ina226_sol_current_ua(tb_ina226_sol_limit(123457, 240000), 240000) >= 123457);
	zassert_equal(tb_ina226_sol_limit(10000000, 1000000), 0x7FFF);
	zassert_equal(tb_ina226_bul_limit(3000), 2400);
}

ZTEST(tb_ina226, test_signs_and_coupon_voltage)
{
	zassert_equal(tb_ina226_current_ua(-2, 11), -22);
	zassert_equal(tb_ina226_shunt_current_ua(-96, 240000), -1000);
	zassert_equal(tb_ina226_bus_uv(0xFFFF), 0x7FFF * 1250u);
	/* SPEC §3.1: 250 mA through 0.24 ohm + 85 mOhm drops about 81 mV */
	zassert_equal(tb_ina226_coupon_mv(3300, 250000, 325), 3219);
	zassert_equal(tb_ina226_coupon_mv(3300, 10000, 325), 3297);
	zassert_equal(tb_ina226_cal(0, 240000), 0);
	zassert_equal(tb_ina226_cal(1, 1), TB_INA226_CAL_MAX);
}

ZTEST_SUITE(tb_ina226, NULL, NULL, NULL, NULL, NULL);
