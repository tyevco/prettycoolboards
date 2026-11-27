/*
 * Fault and alert classification scenarios (SPEC §3.1, §3.5, §8.4).
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include <string.h>
#include <zephyr/ztest.h>

#include "tb/trip.h"
#include "tb_board_map.h"

static struct tb_trip_cfg cfg;
static struct tb_trip_snapshot s;
static struct tb_trip_result r;

static void before(void *f)
{
	static const uint32_t trip[TB_RAIL_COUNT][3] = TB_RAIL_TRIP_MA;

	ARG_UNUSED(f);
	tb_trip_cfg_defaults(&cfg);
	for (int i = 0; i < TB_RAIL_COUNT; i++) {
		cfg.trip_min_ma[i] = trip[i][0];
	}
	memset(&s, 0, sizeof(s));
	s.vsys_pg = true;
	s.s5_pg = true;
	for (int i = 0; i < TB_RAIL_COUNT; i++) {
		s.rail[i].monitored = i != TB_RAIL_5V_KVM;
		s.rail[i].valid = s.rail[i].monitored;
	}
	s.vsys.monitored = s.vsys.valid = true;
	s.vsys.current_ua = 60000;
	s.vsys_limit_ma = 500;
}

static void power(int rail, int32_t ua, int32_t mv)
{
	s.on |= TB_RAIL_BIT(rail);
	s.rail[rail].current_ua = ua;
	s.rail[rail].bus_mv = mv;
}

static bool has(uint8_t kind, int rail)
{
	for (int i = 0; i < r.n; i++) {
		if (r.f[i].kind == kind && (rail < 0 || r.f[i].rail == rail)) {
			return true;
		}
	}
	return false;
}

ZTEST(tb_trip, test_quiet)
{
	power(TB_RAIL_3V3_S1, 1500, 3290);
	tb_trip_classify(&cfg, &s, &r);
	zassert_equal(r.n, 0);
	zassert_equal(r.off, 0);
	zassert_false(r.shed_one || r.all_off);
}

ZTEST(tb_trip, test_vsys_pg_low)
{
	power(TB_RAIL_3V3_S1, 1500, 3290);
	power(TB_RAIL_5V_S5, 500000, 4900);
	s.vsys_pg = false;
	tb_trip_classify(&cfg, &s, &r);
	zassert_true(has(TB_F_VSYS_PG_LOW, -1));
	zassert_true(r.all_off);
	zassert_equal(r.off, s.on);
}

ZTEST(tb_trip, test_coupon_pulled_while_powered)
{
	power(TB_RAIL_3V3_S2, 1500, 3290);
	power(TB_RAIL_5V_S2, 1000, 4950);
	s.absent = 1u << 1;
	tb_trip_classify(&cfg, &s, &r);
	zassert_true(has(TB_F_COUPON_REMOVED, -1));
	zassert_equal(r.f[0].slot, 2);
	zassert_equal(r.off, tb_slot_rail_mask(2));
}

ZTEST(tb_trip, test_s5_breaker)
{
	power(TB_RAIL_3V3_S5, 1500, 3290);
	power(TB_RAIL_5V_S5, 0, 20);
	s.s5_pg = false;
	s.settling = TB_RAIL_BIT(TB_RAIL_5V_S5);
	tb_trip_classify(&cfg, &s, &r);
	zassert_false(has(TB_F_S5_BREAKER, -1), "not while the breaker is starting");
	s.settling = 0;
	tb_trip_classify(&cfg, &s, &r);
	zassert_true(has(TB_F_S5_BREAKER, TB_RAIL_5V_S5));
	zassert_true(r.off & TB_RAIL_BIT(TB_RAIL_5V_S5));
	zassert_false(r.off & TB_RAIL_BIT(TB_RAIL_3V3_S5), "the 3.3 V rail stays");
}

ZTEST(tb_trip, test_fault_attributed_by_current)
{
	power(TB_RAIL_3V3_S1, 1500, 3290);
	power(TB_RAIL_3V3_S3, 290000, 3100);   /* at the TPS2553's typical trip */
	power(TB_RAIL_5V_S3, 20000, 4950);
	s.fault_low = true;
	tb_trip_classify(&cfg, &s, &r);
	zassert_true(has(TB_F_SWITCH_LIMIT, TB_RAIL_3V3_S3));
	zassert_false(has(TB_F_SWITCH_LIMIT, TB_RAIL_3V3_S1));
	zassert_equal(r.off, tb_slot_rail_mask(3), "its 5 V goes with it: 0x%x", r.off);
}

ZTEST(tb_trip, test_fault_attributed_by_sag)
{
	power(TB_RAIL_3V3_S1, 30000, 3290);
	power(TB_RAIL_5V_S1, 100000, 3900);    /* limiting into a capacitor, the INA226 averaging */
	s.fault_low = true;
	tb_trip_classify(&cfg, &s, &r);
	zassert_true(has(TB_F_SWITCH_LIMIT, TB_RAIL_5V_S1));
	zassert_equal(r.off, TB_RAIL_BIT(TB_RAIL_5V_S1));
}

ZTEST(tb_trip, test_fault_unattributed_and_kvm)
{
	power(TB_RAIL_3V3_S1, 1500, 3290);
	power(TB_RAIL_3V3_S5, 1500, 3290);
	power(TB_RAIL_5V_S5, 300000, 4900);
	s.fault_low = true;
	tb_trip_classify(&cfg, &s, &r);
	zassert_true(has(TB_F_FAULT_UNATTRIBUTED, -1));
	zassert_equal(r.off, TB_RAIL_BIT(TB_RAIL_3V3_S1) | TB_RAIL_BIT(TB_RAIL_3V3_S5) | TB_RAIL_BIT(TB_RAIL_5V_S5),
		      "every TPS2553 rail, and S5's 5 V with its 3.3 V");
	s.on |= TB_RAIL_BIT(TB_RAIL_5V_KVM);
	tb_trip_classify(&cfg, &s, &r);
	zassert_true(has(TB_F_FAULT_KVM, TB_RAIL_5V_KVM));
	zassert_equal(r.off, TB_RAIL_BIT(TB_RAIL_5V_KVM), "the unmeasured rail is the suspect");
}

ZTEST(tb_trip, test_alerts)
{
	power(TB_RAIL_3V3_S1, 130000, 3250);
	power(TB_RAIL_5V_S1, 1000, 4950);
	s.alert_low = true;
	s.rail[TB_RAIL_3V3_S1].alert = true;
	tb_trip_classify(&cfg, &s, &r);
	zassert_true(has(TB_F_ALERT, TB_RAIL_3V3_S1));
	zassert_equal(r.off, tb_slot_rail_mask(1));
	s.rail[TB_RAIL_3V3_S1].alert = false;
	tb_trip_classify(&cfg, &s, &r);
	zassert_true(has(TB_F_ALERT_UNATTRIBUTED, -1), "already read, or a monitor that is off");
	zassert_equal(r.off, 0);
}

ZTEST(tb_trip, test_vsys_over_budget)
{
	power(TB_RAIL_3V3_S1, 1500, 3290);
	s.vsys.current_ua = 600000;
	tb_trip_classify(&cfg, &s, &r);
	zassert_true(has(TB_F_VSYS_OVER, -1));
	zassert_true(r.shed_one);
	s.vsys.current_ua = 60000;
	s.alert_low = true;
	s.vsys.alert = true;
	tb_trip_classify(&cfg, &s, &r);
	zassert_true(r.shed_one, "the 0x40 alert alone");
	zassert_false(has(TB_F_ALERT_UNATTRIBUTED, -1));
}

ZTEST(tb_trip, test_dead_sag_live)
{
	power(TB_RAIL_3V3_S2, 0, 12);
	power(TB_RAIL_3V3_S3, 1500, 2900);
	s.rail[TB_RAIL_3V3_S4].bus_mv = 2100;      /* off, but fed: back-powering or a stuck switch */
	s.settling = TB_RAIL_BIT(TB_RAIL_3V3_S2);
	tb_trip_classify(&cfg, &s, &r);
	zassert_false(has(TB_F_RAIL_DEAD, TB_RAIL_3V3_S2), "still settling");
	s.settling = 0;
	tb_trip_classify(&cfg, &s, &r);
	zassert_true(has(TB_F_RAIL_DEAD, TB_RAIL_3V3_S2));
	zassert_true(has(TB_F_RAIL_SAG, TB_RAIL_3V3_S3));
	zassert_true(has(TB_F_RAIL_LIVE_OFF, TB_RAIL_3V3_S4));
	zassert_equal(r.off, TB_RAIL_BIT(TB_RAIL_3V3_S2), "a sag and a live rail are reported only");
}

ZTEST(tb_trip, test_monitor_lost)
{
	power(TB_RAIL_5V_S4, 1000, 4950);
	power(TB_RAIL_3V3_S4, 1000, 3290);
	s.rail[TB_RAIL_3V3_S4].valid = false;
	tb_trip_classify(&cfg, &s, &r);
	zassert_true(has(TB_F_MONITOR_LOST, TB_RAIL_3V3_S4));
	zassert_equal(r.off, tb_slot_rail_mask(4));
}

ZTEST_SUITE(tb_trip, NULL, NULL, before, NULL, NULL);
