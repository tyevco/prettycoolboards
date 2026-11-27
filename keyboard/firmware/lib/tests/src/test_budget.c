/*
 * The VSYS budget (SPEC §3.2, §3.5, §8.4) with the board map's numbers.
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include <string.h>
#include <zephyr/ztest.h>

#include "tb/budget.h"
#include "tb_board_map.h"

static struct tb_budget b;

static void cfg_from_map(struct tb_budget_cfg *c)
{
	static const uint32_t rule[TB_RAIL_COUNT] = TB_RAIL_RULE_MA;

	memset(c, 0, sizeof(*c));
	c->unconfigured_ma = TB_VSYS_BUDGET_UNCONFIGURED_MA;
	c->vsys_max_ma = TB_VSYS_BUDGET_MAX_MA;
	c->slot_ldo_ma = TB_SLOT_LDO_MA;
	c->base_ma = TB_BASE_LOAD_MA;
	c->src_ma[TB_SRC_PENDING] = TB_TYPEC_BUDGET_DEFAULT_MA;
	c->src_ma[TB_SRC_DEFAULT] = TB_TYPEC_BUDGET_DEFAULT_MA;
	c->src_ma[TB_SRC_1A5] = TB_TYPEC_BUDGET_1A5_MA;
	c->src_ma[TB_SRC_3A0] = TB_TYPEC_BUDGET_3A0_MA;
	c->src_ma[TB_SRC_ACCESSORY] = TB_TYPEC_BUDGET_ACCESSORY_MA;
	c->src_ma[TB_SRC_NOT_ATTACHED] = TB_TYPEC_BUDGET_NOT_ATTACHED_MA;
	c->src_ma[TB_SRC_UNREADABLE] = TB_TYPEC_BUDGET_UNREADABLE_MA;
	memcpy(c->rule_ma, rule, sizeof(rule));
}

static void before(void *f)
{
	struct tb_budget_cfg c;

	ARG_UNUSED(f);
	cfg_from_map(&c);
	tb_budget_init(&b, &c);
}

static void configure(enum tb_source src)
{
	tb_budget_usb_event(&b, TB_USB_EV_CONFIGURED, 1);
	tb_budget_set_source(&b, src);
}

/* SPEC §3.2's table (nets.vsys_budget). */
ZTEST(tb_budget, test_spec_table)
{
	zassert_equal(tb_budget_limit_ma(&b), 100, "unconfigured: USB 2.0's 100 mA");
	tb_budget_set_source(&b, TB_SRC_3A0);
	zassert_equal(tb_budget_limit_ma(&b), 100, "whatever the source advertises");
	tb_budget_usb_event(&b, TB_USB_EV_CONFIGURED, 1);
	zassert_equal(tb_budget_limit_ma(&b), 2800, "3.0 A capped at the ceiling");
	tb_budget_set_source(&b, TB_SRC_1A5);
	zassert_equal(tb_budget_limit_ma(&b), 1500);
	tb_budget_set_source(&b, TB_SRC_DEFAULT);
	zassert_equal(tb_budget_limit_ma(&b), 500);
	tb_budget_set_source(&b, TB_SRC_ACCESSORY);
	zassert_equal(tb_budget_limit_ma(&b), 500);
	tb_budget_set_source(&b, TB_SRC_NOT_ATTACHED);
	zassert_equal(tb_budget_limit_ma(&b), 500);
	tb_budget_set_source(&b, TB_SRC_UNREADABLE);
	zassert_equal(tb_budget_limit_ma(&b), 500);
	tb_budget_set_source(&b, TB_SRC_PENDING);
	zassert_equal(tb_budget_limit_ma(&b), 500, "before U_CC is read: the Default level");
	zassert_true(TB_VSYS_BUDGET_MAX_MA < 2960, "below the input breaker's minimum trip");
	zassert_true(TB_BASE_LOAD_MA < TB_VSYS_BUDGET_UNCONFIGURED_MA);
}

ZTEST(tb_budget, test_no_power_before_configuration)
{
	zassert_equal(tb_budget_enable(&b, TB_RAIL_3V3_S1, 10), TB_REFUSE_UNCONFIGURED);
	tb_budget_usb_event(&b, TB_USB_EV_CONFIGURED, 0);
	zassert_equal(tb_budget_enable(&b, TB_RAIL_3V3_S1, 10), TB_REFUSE_UNCONFIGURED, "SET_CONFIGURATION(0)");
	configure(TB_SRC_DEFAULT);
	zassert_equal(tb_budget_enable(&b, TB_RAIL_3V3_S1, 10), TB_BUDGET_OK);
	zassert_equal(tb_budget_enable(&b, TB_RAIL_3V3_S1, 10), TB_REFUSE_ALREADY_ON);
	zassert_equal(tb_budget_enable(&b, 42, 10), TB_REFUSE_BAD_RAIL);
}

ZTEST(tb_budget, test_order_rule_ldo_vsys)
{
	configure(TB_SRC_3A0);
	zassert_equal(tb_budget_enable(&b, TB_RAIL_5V_S1, 100), TB_REFUSE_ORDER, "3.3 V first");
	zassert_equal(tb_budget_enable(&b, TB_RAIL_3V3_S1, 251), TB_REFUSE_RULE, "250 mA rule");
	zassert_equal(tb_budget_enable(&b, TB_RAIL_3V3_S1, 100), TB_BUDGET_OK);
	zassert_equal(tb_budget_enable(&b, TB_RAIL_5V_S1, 501), TB_REFUSE_RULE, "500 mA rule on S1-S4");
	zassert_equal(tb_budget_enable(&b, TB_RAIL_5V_S1, 500), TB_BUDGET_OK);
	zassert_equal(tb_budget_enable(&b, TB_RAIL_3V3_S2, 100), TB_BUDGET_OK);
	zassert_equal(tb_budget_enable(&b, TB_RAIL_3V3_S3, 100), TB_BUDGET_OK);
	zassert_equal(tb_budget_ldo_used_ma(&b), 300);
	zassert_equal(tb_budget_enable(&b, TB_RAIL_3V3_S4, 1), TB_REFUSE_LDO, "slot LDO's 300 mA");
	zassert_equal(tb_budget_enable(&b, TB_RAIL_3V3_S5, 0), TB_BUDGET_OK, "a zero declaration fits");
	zassert_equal(tb_budget_enable(&b, TB_RAIL_5V_S5, 2001), TB_REFUSE_RULE, "S5's 2 A rule");
	/* 45 + 100 + 500 + 100 + 100 = 845; 845 + 1956 = 2801 > 2800 */
	zassert_equal(tb_budget_enable(&b, TB_RAIL_5V_S5, 1956), TB_REFUSE_VSYS);
	zassert_equal(tb_budget_enable(&b, TB_RAIL_5V_S5, 1955), TB_BUDGET_OK);
	zassert_equal(tb_budget_used_ma(&b), 2800);
}

ZTEST(tb_budget, test_default_source_limits_5v)
{
	configure(TB_SRC_DEFAULT);
	zassert_equal(tb_budget_enable(&b, TB_RAIL_3V3_S1, 250), TB_BUDGET_OK);
	/* 45 + 250 + 206 = 501 > 500 */
	zassert_equal(tb_budget_enable(&b, TB_RAIL_5V_S1, 206), TB_REFUSE_VSYS);
	zassert_equal(tb_budget_enable(&b, TB_RAIL_5V_S1, 205), TB_BUDGET_OK);
}

/* SPEC §8.4: when the budget falls, rails go off, S5 first, then the rest in the reverse order of enabling. */
ZTEST(tb_budget, test_shedding_order)
{
	uint32_t off;

	configure(TB_SRC_3A0);
	zassert_ok(tb_budget_enable(&b, TB_RAIL_3V3_S1, 100));
	zassert_ok(tb_budget_enable(&b, TB_RAIL_5V_S1, 400));
	zassert_ok(tb_budget_enable(&b, TB_RAIL_3V3_S2, 100));
	zassert_ok(tb_budget_enable(&b, TB_RAIL_3V3_S5, 50));
	zassert_ok(tb_budget_enable(&b, TB_RAIL_5V_S5, 1500));
	zassert_equal(tb_budget_used_ma(&b), 2195);

	off = tb_budget_set_source(&b, TB_SRC_1A5);
	zassert_equal(off, TB_RAIL_BIT(TB_RAIL_5V_S5), "S5's 5 V alone brings 2195 to 695");
	off = tb_budget_set_source(&b, TB_SRC_DEFAULT);
	zassert_equal(off, TB_RAIL_BIT(TB_RAIL_3V3_S5) | TB_RAIL_BIT(TB_RAIL_3V3_S2) | TB_RAIL_BIT(TB_RAIL_5V_S1),
		      "then S5's 3.3 V, then S2, then S1's 5 V: 0x%x", off);
	zassert_equal(b.on, TB_RAIL_BIT(TB_RAIL_3V3_S1));
	zassert_equal(tb_budget_used_ma(&b), 145);
}

ZTEST(tb_budget, test_disable_takes_5v)
{
	configure(TB_SRC_3A0);
	zassert_ok(tb_budget_enable(&b, TB_RAIL_3V3_S3, 10));
	zassert_ok(tb_budget_enable(&b, TB_RAIL_5V_S3, 10));
	zassert_equal(tb_budget_off_mask(&b, TB_RAIL_3V3_S3), tb_slot_rail_mask(3));
	zassert_equal(tb_budget_disable(&b, TB_RAIL_3V3_S3), tb_slot_rail_mask(3));
	zassert_equal(b.on, 0);
	zassert_equal(tb_budget_disable(&b, TB_RAIL_3V3_S3), 0);
}

ZTEST(tb_budget, test_usb_events)
{
	configure(TB_SRC_3A0);
	zassert_ok(tb_budget_enable(&b, TB_RAIL_3V3_S1, 10));
	zassert_ok(tb_budget_enable(&b, TB_RAIL_3V3_S2, 10));
	zassert_equal(tb_budget_usb_event(&b, TB_USB_EV_SUSPEND, 0), TB_RAIL_BIT(0) | TB_RAIL_BIT(1));
	zassert_equal(b.usb, TB_USB_SUSPENDED);
	zassert_equal(tb_budget_enable(&b, TB_RAIL_3V3_S1, 10), TB_REFUSE_SUSPENDED);
	tb_budget_usb_event(&b, TB_USB_EV_RESUME, 0);
	zassert_equal(b.on, 0, "nothing comes back on by itself");
	zassert_ok(tb_budget_enable(&b, TB_RAIL_3V3_S1, 10));
	zassert_equal(tb_budget_usb_event(&b, TB_USB_EV_RESET, 0), TB_RAIL_BIT(0));
	zassert_equal(tb_budget_limit_ma(&b), 100, "a bus reset leaves the device unconfigured");
	configure(TB_SRC_3A0);
	zassert_ok(tb_budget_enable(&b, TB_RAIL_3V3_S1, 10));
	zassert_equal(tb_budget_usb_event(&b, TB_USB_EV_CONFIGURED, 0), TB_RAIL_BIT(0));
	zassert_equal(b.usb, TB_USB_UNCONFIGURED);
}

/* The USB transitions test_usb_events leaves out: VBUS removed, a reset out of suspend, a reset in bench mode,
 * a resume that was never suspended, and a measured base load above the estimate. */
ZTEST(tb_budget, test_usb_edge_cases)
{
	uint32_t shed;

	configure(TB_SRC_1A5);
	zassert_ok(tb_budget_enable(&b, TB_RAIL_3V3_S1, 10));
	zassert_equal(tb_budget_usb_event(&b, TB_USB_EV_DISCONNECTED, 0), TB_RAIL_BIT(TB_RAIL_3V3_S1));
	zassert_equal(b.usb, TB_USB_UNCONFIGURED);
	zassert_equal(tb_budget_limit_ma(&b), 100, "VBUS gone: back to the unconfigured level");

	configure(TB_SRC_1A5);
	zassert_ok(tb_budget_enable(&b, TB_RAIL_3V3_S1, 10));
	tb_budget_usb_event(&b, TB_USB_EV_SUSPEND, 0);
	zassert_equal(tb_budget_usb_event(&b, TB_USB_EV_RESET, 0), 0, "already off");
	zassert_equal(b.usb, TB_USB_UNCONFIGURED, "a reset out of suspend leaves the device unconfigured");
	tb_budget_usb_event(&b, TB_USB_EV_RESUME, 0);
	zassert_equal(b.usb, TB_USB_UNCONFIGURED, "a resume does not configure");
	zassert_equal(tb_budget_enable(&b, TB_RAIL_3V3_S1, 10), TB_REFUSE_UNCONFIGURED);

	zassert_equal(tb_budget_set_bench(&b, 1000, &shed), TB_BUDGET_OK);
	zassert_ok(tb_budget_enable(&b, TB_RAIL_3V3_S2, 10));
	zassert_equal(tb_budget_usb_event(&b, TB_USB_EV_RESET, 0), TB_RAIL_BIT(TB_RAIL_3V3_S2),
		      "a host's reset ends bench mode");
	zassert_false(tb_budget_bench_active(&b));
	zassert_false(tb_budget_may_power(&b));

	configure(TB_SRC_DEFAULT);
	zassert_ok(tb_budget_enable(&b, TB_RAIL_3V3_S3, 200));
	zassert_ok(tb_budget_enable(&b, TB_RAIL_5V_S3, 200));
	/* 45 + 400 fits 500; a measured base of 150 mA does not: S3's 5 V goes, then 3.3 V would follow */
	zassert_equal(tb_budget_set_base(&b, 150), TB_RAIL_BIT(TB_RAIL_5V_S3));
	zassert_equal(tb_budget_used_ma(&b), 350);
	zassert_equal(tb_budget_set_base(&b, 400), TB_RAIL_BIT(TB_RAIL_3V3_S3));
	zassert_equal(b.on, 0);
}

ZTEST(tb_budget, test_override_lowers_only)
{
	configure(TB_SRC_1A5);
	tb_budget_set_override(&b, 1000);
	zassert_equal(tb_budget_limit_ma(&b), 1000);
	tb_budget_set_override(&b, 5000);
	zassert_equal(tb_budget_limit_ma(&b), 1500, "an override never raises the budget");
	zassert_ok(tb_budget_enable(&b, TB_RAIL_3V3_S1, 200));
	zassert_equal(tb_budget_set_override(&b, 200), TB_RAIL_BIT(TB_RAIL_3V3_S1), "45 + 200 > 200");
	tb_budget_set_override(&b, 0);
	zassert_equal(tb_budget_limit_ma(&b), 1500);
}

ZTEST(tb_budget, test_bench_mode)
{
	uint32_t shed;

	zassert_equal(tb_budget_set_bench(&b, 1000, &shed), TB_BUDGET_OK);
	zassert_true(tb_budget_may_power(&b));
	zassert_equal(tb_budget_limit_ma(&b), 1000);
	zassert_ok(tb_budget_enable(&b, TB_RAIL_3V3_S1, 200));
	zassert_ok(tb_budget_enable(&b, TB_RAIL_5V_S1, 500));
	zassert_equal(tb_budget_usb_event(&b, TB_USB_EV_SUSPEND, 0), 0, "an idle bus with no host");
	zassert_equal(b.on, TB_RAIL_BIT(TB_RAIL_3V3_S1) | TB_RAIL_BIT(TB_RAIL_5V_S1));
	zassert_equal(tb_budget_set_bench(&b, 9000, &shed), TB_BUDGET_OK);
	zassert_equal(tb_budget_limit_ma(&b), 2800, "capped at the ceiling");
	zassert_equal(tb_budget_set_bench(&b, 600, &shed), TB_BUDGET_OK);
	zassert_equal(shed, TB_RAIL_BIT(TB_RAIL_5V_S1), "45 + 200 + 500 > 600");
	/* A host appears: bench mode ends and every rail goes off. */
	zassert_equal(tb_budget_usb_event(&b, TB_USB_EV_CONFIGURED, 1), TB_RAIL_BIT(TB_RAIL_3V3_S1));
	zassert_false(tb_budget_bench_active(&b));
	zassert_equal(tb_budget_set_bench(&b, 1000, &shed), TB_REFUSE_STATE, "not while configured");
	tb_budget_usb_event(&b, TB_USB_EV_RESET, 0);
	zassert_equal(tb_budget_set_bench(&b, 1000, &shed), TB_BUDGET_OK);
	zassert_ok(tb_budget_enable(&b, TB_RAIL_3V3_S2, 10));
	zassert_equal(tb_budget_set_bench(&b, 0, &shed), TB_BUDGET_OK);
	zassert_equal(shed, TB_RAIL_BIT(TB_RAIL_3V3_S2), "leaving bench mode unconfigured: all off");
}

ZTEST(tb_budget, test_peak_checks)
{
	configure(TB_SRC_DEFAULT);
	zassert_ok(tb_budget_enable(&b, TB_RAIL_3V3_S1, 120));
	/* the test coupon's G1 load: up to 335 mA, the slot LDO's 300 mA waived only with the others off */
	zassert_equal(tb_budget_check_peak(&b, TB_RAIL_3V3_S1, 335, false), TB_REFUSE_LDO);
	zassert_equal(tb_budget_check_peak(&b, TB_RAIL_3V3_S1, 335, true), TB_BUDGET_OK);
	zassert_ok(tb_budget_enable(&b, TB_RAIL_3V3_S2, 5));
	zassert_equal(tb_budget_check_peak(&b, TB_RAIL_3V3_S1, 335, true), TB_REFUSE_OTHERS_ON);
	/* G3 on +5V: up to 644 mA, more than a Default source allows */
	zassert_ok(tb_budget_enable(&b, TB_RAIL_5V_S1, 170));
	zassert_equal(tb_budget_check_peak(&b, TB_RAIL_5V_S1, 644, false), TB_REFUSE_VSYS);
	tb_budget_set_source(&b, TB_SRC_1A5);
	zassert_equal(tb_budget_check_peak(&b, TB_RAIL_5V_S1, 644, false), TB_BUDGET_OK);
	zassert_equal(tb_budget_check_peak(&b, TB_RAIL_5V_S2, 644, false), TB_REFUSE_ORDER, "not on");
}

ZTEST(tb_budget, test_kvm_rail)
{
	configure(TB_SRC_1A5);
	zassert_ok(tb_budget_enable(&b, TB_RAIL_5V_KVM, 500), "no 3.3 V rail ahead of it");
	zassert_ok(tb_budget_enable(&b, TB_RAIL_3V3_S5, 10));
	zassert_equal(tb_budget_next_victim(&b), TB_RAIL_3V3_S5, "S5 first even when enabled last");
	tb_budget_disable(&b, TB_RAIL_3V3_S5);
	zassert_equal(tb_budget_next_victim(&b), TB_RAIL_5V_KVM);
}

ZTEST(tb_budget, test_redeclare)
{
	configure(TB_SRC_DEFAULT);
	/* discovery at the 250 mA rule, then the descriptor's 120 mA */
	zassert_ok(tb_budget_enable(&b, TB_RAIL_3V3_S1, 250));
	zassert_ok(tb_budget_redeclare(&b, TB_RAIL_3V3_S1, 120));
	zassert_equal(tb_budget_used_ma(&b), 165);
	zassert_ok(tb_budget_enable(&b, TB_RAIL_3V3_S2, 170));
	zassert_equal(tb_budget_redeclare(&b, TB_RAIL_3V3_S1, 140), TB_REFUSE_LDO, "120 + 170 + 20 > 300");
	zassert_equal(b.declared_ma[TB_RAIL_3V3_S1], 120, "a refused raise changes nothing");
	zassert_ok(tb_budget_redeclare(&b, TB_RAIL_3V3_S1, 130));
	zassert_equal(tb_budget_redeclare(&b, TB_RAIL_3V3_S1, 251), TB_REFUSE_RULE);
	zassert_equal(tb_budget_redeclare(&b, TB_RAIL_3V3_S3, 1), TB_REFUSE_ORDER, "not on");
	zassert_true(b.on & TB_RAIL_BIT(TB_RAIL_3V3_S1));
}

ZTEST(tb_budget, test_strings)
{
	for (int r = TB_BUDGET_OK; r <= TB_REFUSE_STATE; r++) {
		zassert_not_equal(strcmp(tb_refusal_str((enum tb_refusal)r), "?"), 0);
	}
	for (int s = 0; s < TB_SRC_COUNT; s++) {
		zassert_not_equal(strcmp(tb_source_str((enum tb_source)s), "?"), 0);
	}
}

ZTEST_SUITE(tb_budget, NULL, NULL, before, NULL, NULL);
