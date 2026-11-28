/*
 * Slot power-up and coupon discovery (see slot.h).
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include <string.h>

#include <zephyr/kernel.h>

#include "board.h"
#include "descio.h"
#include "events.h"
#include "slot.h"

#define MIN_3V3_MV 3000
#define MIN_5V_MV  4300

int tb_rail_settle(int rail, struct tb_mon_reading *r, bool *fault)
{
	const struct tb_mon *m = tb_mon_for_rail(rail);
	uint16_t in = 0;
	int err;

	k_msleep(CONFIG_BRINGUP_SETTLE_MS);
	err = tb_exp2_inputs(&in);
	*fault = err == 0 && tb_pin_active(in, &tb_sig.slot_fault);
	if (m == NULL) {
		memset(r, 0, sizeof(*r));
		return err;
	}
	return err ? err : tb_mon_read(m, false, r);
}

void tb_slot_off(int slot, const char *reason)
{
	(void)tb_rails_off(tb_slot_rail_mask(slot), reason);
	tb.desc_err[slot - 1] = 1;
}

int tb_slot_on(int slot, const struct tb_slot_on_opts *o, struct tb_slot_on_result *res)
{
	const struct tb_slot_hw *h = tb_slot_hw(slot);
	static uint8_t raw[TB_DESC_MAX_LEN];
	size_t len;
	uint32_t ma3;
	int err;

	memset(res, 0, sizeof(*res));
	res->desc = 1;
	if (h == NULL) {
		res->err = "bad_slot";
		return -EINVAL;
	}
	/* +3V3 first, declared at the coupon rule until the descriptor says what the coupon draws. */
	ma3 = o->use_desc ? (o->probe_ma ? MIN(o->probe_ma, h->rule3_ma) : h->rule3_ma) : o->ma3;
	if (tb.budget.on & TB_RAIL_BIT(h->rail3)) {
		/* already on: report what it reads now */
		const struct tb_mon *m3 = tb_mon_for_rail(h->rail3);

		if (m3 != NULL) {
			(void)tb_mon_read(m3, false, &res->r3);
		}
	} else {
		err = tb_rail_on(h->rail3, ma3, &res->why3);
		if (err == -ENODEV) {
			res->err = "not_present";
			return err;
		}
		if (err != 0) {
			res->err = res->why3 != TB_BUDGET_OK ? tb_refusal_str(res->why3) : "rail_3v3";
			return err;
		}
		err = tb_rail_settle(h->rail3, &res->r3, &res->fault);
		if (err != 0 || res->fault || res->r3.bus_mv < MIN_3V3_MV ||
		    res->r3.current_ua >= (int32_t)(h->trip3_ma[0] * 1000u)) {
			tb_slot_off(slot, "3v3_check");
			res->err = err ? "monitor" : res->fault ? "fault_3v3" : res->r3.bus_mv < MIN_3V3_MV ? "low_3v3"
										      : "over_3v3";
			return err ? err : -EIO;
		}
	}
	res->on3 = true;
	/* The slot's direct lines (CS0_N, CS1_N, G0-G5, IRQ_N) stay high-impedance until the descriptor is read and
	 * checked (SPEC §4.6: "reads the descriptor, and only then configures anything else"; risks.md EL-2). The
	 * read needs only +3V3_Sn and the slot's mux channel. The key (D2 of 2026-11-27) keeps a turned coupon out of
	 * the socket, but only while hole 39 is plugged and the coupon's pin 39 pulled, two hand steps: a coupon
	 * that went in turned reads present (PRESENT_N on its GND), and is now refused without being driven. */

	if (o->use_desc) {
		res->desc = tb_descio_load(slot, raw, sizeof(raw), &len);
		if (res->desc != TB_DESC_OK) {
			if (!o->keep_blank) {
				tb_slot_off(slot, "no_descriptor");
				res->on3 = false;
			}
			res->err = res->desc == TB_DESCIO_BUS_ERR ? "desc_bus" : tb_desc_err_str(res->desc);
			return res->desc == TB_DESC_ERR_BLANK && o->keep_blank ? 0 : -ENOENT;
		}
		res->rule = tb_desc_check_slot(&tb.desc[slot - 1], slot, h->rule3_ma, h->rule5_ma);
		if (res->rule != NULL) {
			tb_slot_off(slot, res->rule);
			res->on3 = false;
			res->err = res->rule;
			return -EPERM;
		}
		res->ma3 = tb.desc[slot - 1].i3v3_ma;
		res->ma5 = tb.desc[slot - 1].i5v_ma;
	} else {
		res->ma3 = o->ma3;
		res->ma5 = o->ma5;
	}
	res->why3 = tb_budget_redeclare(&tb.budget, h->rail3, res->ma3);
	if (res->why3 != TB_BUDGET_OK) {
		tb_slot_off(slot, tb_refusal_str(res->why3));
		res->on3 = false;
		res->err = tb_refusal_str(res->why3);
		return -EPERM;
	}
	/* The firmware's over-current threshold follows the declared current (SPEC §3.4). */
	if (tb_mon_for_rail(h->rail3) != NULL) {
		(void)tb_mon_set_alert(tb_mon_for_rail(h->rail3), tb_rail_alert_ua(h->rail3, res->ma3));
	}
	/* Identified (or declared by the operator with nodesc): now the lines, CS high and G low (SPEC §3.5). */
	(void)tb_slot_lines(slot, true);

	if (tb.budget.on & TB_RAIL_BIT(h->rail5)) {
		const struct tb_mon *m5 = tb_mon_for_rail(h->rail5);

		res->on5 = true;
		if (m5 != NULL) {
			(void)tb_mon_read(m5, false, &res->r5);
		}
	} else if (res->ma5 > 0) {
		err = tb_rail_on(h->rail5, res->ma5, &res->why5);
		if (err != 0) {
			res->err = res->why5 != TB_BUDGET_OK ? tb_refusal_str(res->why5) : "rail_5v";
			/* +3V3 stays on: the coupon is identified, its 5 V does not fit now */
			goto bus;
		}
		err = tb_rail_settle(h->rail5, &res->r5, &res->fault);
		if (h->pg5.port != NULL) {
			uint16_t in = 0;

			if (tb_exp2_inputs(&in) == 0 && !tb_pin_active(in, &h->pg5)) {
				res->fault = true; /* S5's breaker latched off */
			}
		}
		if (err != 0 || res->fault || res->r5.bus_mv < MIN_5V_MV ||
		    res->r5.current_ua >= (int32_t)(h->trip5_ma[0] * 1000u)) {
			(void)tb_rails_off(TB_RAIL_BIT(h->rail5), "5v_check");
			res->err = err ? "monitor" : res->fault ? "fault_5v" : res->r5.bus_mv < MIN_5V_MV ? "low_5v"
										      : "over_5v";
			goto bus;
		}
		res->on5 = true;
	}
bus:
	/* The bus switch only after the rails are up (SPEC §3.5). */
	err = tb_slot_bus(slot, true);
	res->bus = err == 0;
	tb_ev("kind=slot slot=%d on3=%d on5=%d bus=%d desc=%s", slot, res->on3, res->on5, res->bus,
	      res->desc == 1 ? "none" : tb_desc_err_str(res->desc));
	return res->err != NULL ? -EAGAIN : 0;
}
