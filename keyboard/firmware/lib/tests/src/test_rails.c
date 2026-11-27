/*
 * Rail numbering: the lib's enum against the generated board map.
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include <string.h>
#include <zephyr/ztest.h>

#include "tb/rails.h"
#include "tb_board_map.h"

BUILD_ASSERT(TB_RAIL_ID_P3V3_S1 == TB_RAIL_3V3_S1 && TB_RAIL_ID_P3V3_S5 == TB_RAIL_3V3_S5);
BUILD_ASSERT(TB_RAIL_ID_P5V_S1 == TB_RAIL_5V_S1 && TB_RAIL_ID_P5V_S5 == TB_RAIL_5V_S5);
BUILD_ASSERT(TB_RAIL_ID_P5V_KVM == TB_RAIL_5V_KVM && TB_RAIL_ID_COUNT == TB_RAIL_COUNT);
BUILD_ASSERT(TB_NUM_SLOTS == TB_SLOTS);

ZTEST(tb_rails, test_slot_mapping)
{
	for (int s = 1; s <= TB_SLOTS; s++) {
		zassert_equal(tb_rail_slot(tb_rail_3v3(s)), s);
		zassert_equal(tb_rail_slot(tb_rail_5v(s)), s);
		zassert_true(tb_rail_is_3v3(tb_rail_3v3(s)));
		zassert_false(tb_rail_is_3v3(tb_rail_5v(s)));
		zassert_equal(tb_slot_rail_mask(s),
			      TB_RAIL_BIT(tb_rail_3v3(s)) | TB_RAIL_BIT(tb_rail_5v(s)));
	}
	zassert_equal(tb_rail_slot(TB_RAIL_5V_KVM), 0);
	zassert_equal(tb_rail_slot(TB_RAIL_COUNT), -1);
	zassert_equal(tb_rail_3v3(0), -1);
	zassert_equal(tb_rail_5v(6), -1);
	zassert_equal(tb_slot_rail_mask(0), 0);
	zassert_false(TB_RAIL_MASK_TPS2553 & TB_RAIL_BIT(TB_RAIL_5V_S5));
}

ZTEST(tb_rails, test_names_round_trip)
{
	for (int r = 0; r < TB_RAIL_COUNT; r++) {
		zassert_equal(tb_rail_from_name(tb_rail_name(r)), r);
	}
	zassert_equal(tb_rail_from_name("+12V"), -1);
	zassert_equal(strcmp(tb_rail_name(99), "?"), 0);
}

/* The generated INA226 table names the rails the way the lib does. */
ZTEST(tb_rails, test_board_map_rail_names)
{
	static const struct {
		uint8_t addr;
		const char *rail;
		uint32_t shunt_uohm, lsb_ua, cal;
		int rail_id;
		uint32_t rule_ma, tmin, ttyp, tmax;
	} ina[] = TB_INA226_TABLE;
	int found = 0;

	for (size_t i = 0; i < ARRAY_SIZE(ina); i++) {
		if (ina[i].rail_id >= 0) {
			zassert_equal(tb_rail_from_name(ina[i].rail), ina[i].rail_id, "%s", ina[i].rail);
			found++;
		}
	}
	zassert_equal(found, 2 * TB_SLOTS);
}

ZTEST_SUITE(tb_rails, NULL, NULL, NULL, NULL, NULL);
