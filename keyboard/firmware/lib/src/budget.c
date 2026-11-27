/*
 * VSYS power budget (SPEC §3.2, §3.5, §8.4). See tb/budget.h.
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include <string.h>

#include "tb/budget.h"

static uint32_t min_u32(uint32_t a, uint32_t b)
{
	return a < b ? a : b;
}

void tb_budget_init(struct tb_budget *b, const struct tb_budget_cfg *cfg)
{
	memset(b, 0, sizeof(*b));
	b->cfg = *cfg;
	b->usb = TB_USB_UNCONFIGURED;
	b->src = TB_SRC_PENDING;
	b->next_seq = 1;
}

bool tb_budget_bench_active(const struct tb_budget *b)
{
	return b->bench_ma != 0;
}

uint32_t tb_budget_source_ma(const struct tb_budget *b)
{
	if (tb_budget_bench_active(b)) {
		return min_u32(b->bench_ma, b->cfg.vsys_max_ma);
	}
	if (b->usb == TB_USB_UNCONFIGURED) {
		return b->cfg.unconfigured_ma;
	}
	if ((unsigned)b->src >= TB_SRC_COUNT) {
		return b->cfg.src_ma[TB_SRC_UNREADABLE];
	}
	return min_u32(b->cfg.src_ma[b->src], b->cfg.vsys_max_ma);
}

uint32_t tb_budget_limit_ma(const struct tb_budget *b)
{
	uint32_t ma = tb_budget_source_ma(b);

	return b->override_ma != 0 ? min_u32(ma, b->override_ma) : ma;
}

uint32_t tb_budget_used_ma(const struct tb_budget *b)
{
	uint32_t ma = b->cfg.base_ma;

	for (int r = 0; r < TB_RAIL_COUNT; r++) {
		if (b->on & TB_RAIL_BIT(r)) {
			ma += b->declared_ma[r];
		}
	}
	return ma;
}

uint32_t tb_budget_ldo_used_ma(const struct tb_budget *b)
{
	uint32_t ma = 0;

	for (int r = TB_RAIL_3V3_S1; r <= TB_RAIL_3V3_S5; r++) {
		if (b->on & TB_RAIL_BIT(r)) {
			ma += b->declared_ma[r];
		}
	}
	return ma;
}

bool tb_budget_may_power(const struct tb_budget *b)
{
	return tb_budget_bench_active(b) || b->usb == TB_USB_CONFIGURED;
}

static enum tb_refusal state_check(const struct tb_budget *b)
{
	if (tb_budget_bench_active(b)) {
		return TB_BUDGET_OK;
	}
	if (b->usb == TB_USB_SUSPENDED) {
		return TB_REFUSE_SUSPENDED;
	}
	if (b->usb != TB_USB_CONFIGURED) {
		return TB_REFUSE_UNCONFIGURED;
	}
	return TB_BUDGET_OK;
}

enum tb_refusal tb_budget_check(const struct tb_budget *b, int rail, uint32_t declared_ma)
{
	enum tb_refusal r;

	if (!tb_rail_valid(rail)) {
		return TB_REFUSE_BAD_RAIL;
	}
	r = state_check(b);
	if (r != TB_BUDGET_OK) {
		return r;
	}
	if (b->on & TB_RAIL_BIT(rail)) {
		return TB_REFUSE_ALREADY_ON;
	}
	if (declared_ma > b->cfg.rule_ma[rail]) {
		return TB_REFUSE_RULE;
	}
	if (!tb_rail_is_3v3(rail) && rail != TB_RAIL_5V_KVM) {
		int slot = tb_rail_slot(rail);

		if (!(b->on & TB_RAIL_BIT(tb_rail_3v3(slot)))) {
			return TB_REFUSE_ORDER;
		}
	}
	if (tb_budget_used_ma(b) + declared_ma > tb_budget_limit_ma(b)) {
		return TB_REFUSE_VSYS;
	}
	if (tb_rail_is_3v3(rail) && tb_budget_ldo_used_ma(b) + declared_ma > b->cfg.slot_ldo_ma) {
		return TB_REFUSE_LDO;
	}
	return TB_BUDGET_OK;
}

enum tb_refusal tb_budget_enable(struct tb_budget *b, int rail, uint32_t declared_ma)
{
	enum tb_refusal r = tb_budget_check(b, rail, declared_ma);

	if (r != TB_BUDGET_OK) {
		return r;
	}
	b->on |= TB_RAIL_BIT(rail);
	b->declared_ma[rail] = declared_ma;
	b->seq[rail] = b->next_seq++;
	return TB_BUDGET_OK;
}

enum tb_refusal tb_budget_redeclare(struct tb_budget *b, int rail, uint32_t declared_ma)
{
	uint32_t old;
	enum tb_refusal r;

	if (!tb_rail_valid(rail)) {
		return TB_REFUSE_BAD_RAIL;
	}
	if (!(b->on & TB_RAIL_BIT(rail))) {
		return TB_REFUSE_ORDER;
	}
	old = b->declared_ma[rail];
	if (declared_ma <= old) {
		b->declared_ma[rail] = declared_ma;
		return TB_BUDGET_OK;
	}
	/* Check the raise as an enable of the same rail would be checked. */
	b->on &= ~TB_RAIL_BIT(rail);
	r = tb_budget_check(b, rail, declared_ma);
	b->on |= TB_RAIL_BIT(rail);
	if (r == TB_BUDGET_OK) {
		b->declared_ma[rail] = declared_ma;
	}
	return r;
}

uint32_t tb_budget_off_mask(const struct tb_budget *b, int rail)
{
	uint32_t m;

	if (!tb_rail_valid(rail)) {
		return 0;
	}
	m = TB_RAIL_BIT(rail);
	if (tb_rail_is_3v3(rail)) {
		m |= TB_RAIL_BIT(tb_rail_5v(tb_rail_slot(rail)));
	}
	return m & b->on;
}

static uint32_t mark_off(struct tb_budget *b, uint32_t mask)
{
	mask &= b->on;
	for (int r = 0; r < TB_RAIL_COUNT; r++) {
		if (mask & TB_RAIL_BIT(r)) {
			b->declared_ma[r] = 0;
			b->seq[r] = 0;
		}
	}
	b->on &= ~mask;
	return mask;
}

uint32_t tb_budget_disable(struct tb_budget *b, int rail)
{
	return mark_off(b, tb_budget_off_mask(b, rail));
}

uint32_t tb_budget_usb_event(struct tb_budget *b, enum tb_usb_event ev, uint32_t value)
{
	switch (ev) {
	case TB_USB_EV_RESET:
	case TB_USB_EV_DISCONNECTED:
		b->usb = TB_USB_UNCONFIGURED;
		b->bench_ma = 0;
		return mark_off(b, b->on);
	case TB_USB_EV_CONFIGURED:
		if (value == 0) {
			b->usb = TB_USB_UNCONFIGURED;
			b->bench_ma = 0;
			return mark_off(b, b->on);
		}
		b->usb = TB_USB_CONFIGURED;
		if (tb_budget_bench_active(b)) {
			/* A host configured the device: the bench declaration no longer describes the source. */
			b->bench_ma = 0;
			return mark_off(b, b->on);
		}
		return tb_budget_fit(b);
	case TB_USB_EV_SUSPEND:
		if (tb_budget_bench_active(b)) {
			/* With no host the controller can report an idle bus as suspend: bench mode ignores it. */
			return 0;
		}
		if (b->usb == TB_USB_CONFIGURED) {
			b->usb = TB_USB_SUSPENDED;
		}
		return mark_off(b, b->on);
	case TB_USB_EV_RESUME:
		if (b->usb == TB_USB_SUSPENDED) {
			b->usb = TB_USB_CONFIGURED;
		}
		return 0;
	default:
		return 0;
	}
}

uint32_t tb_budget_set_source(struct tb_budget *b, enum tb_source src)
{
	b->src = ((unsigned)src < TB_SRC_COUNT) ? src : TB_SRC_UNREADABLE;
	return tb_budget_fit(b);
}

uint32_t tb_budget_set_override(struct tb_budget *b, uint32_t ma)
{
	b->override_ma = ma;
	return tb_budget_fit(b);
}

enum tb_refusal tb_budget_set_bench(struct tb_budget *b, uint32_t ma, uint32_t *shed)
{
	uint32_t off = 0;

	if (ma != 0 && b->usb != TB_USB_UNCONFIGURED) {
		if (shed != NULL) {
			*shed = 0;
		}
		return TB_REFUSE_STATE;
	}
	b->bench_ma = ma;
	if (ma == 0) {
		/* Leaving bench mode while unconfigured: nothing may stay powered. */
		off = b->usb == TB_USB_CONFIGURED ? tb_budget_fit(b) : mark_off(b, b->on);
	} else {
		off = tb_budget_fit(b);
	}
	if (shed != NULL) {
		*shed = off;
	}
	return TB_BUDGET_OK;
}

uint32_t tb_budget_set_base(struct tb_budget *b, uint32_t ma)
{
	b->cfg.base_ma = ma;
	return tb_budget_fit(b);
}

int tb_budget_next_victim(const struct tb_budget *b)
{
	int best = -1;
	uint32_t best_seq = 0;

	/* S5 first (SPEC §8.4): its 5 V (the motor), then its 3.3 V. */
	if (b->on & TB_RAIL_BIT(TB_RAIL_5V_S5)) {
		return TB_RAIL_5V_S5;
	}
	if (b->on & TB_RAIL_BIT(TB_RAIL_3V3_S5)) {
		return TB_RAIL_3V3_S5;
	}
	/* Then the reverse order of enabling. A slot's 5 V is always enabled after its 3.3 V, so it goes first. */
	for (int r = 0; r < TB_RAIL_COUNT; r++) {
		if ((b->on & TB_RAIL_BIT(r)) && b->seq[r] >= best_seq) {
			best = r;
			best_seq = b->seq[r];
		}
	}
	return best;
}

uint32_t tb_budget_fit(struct tb_budget *b)
{
	uint32_t off = 0;

	if (!tb_budget_may_power(b)) {
		return mark_off(b, b->on);
	}
	while (b->on != 0 && (tb_budget_used_ma(b) > tb_budget_limit_ma(b) ||
			      tb_budget_ldo_used_ma(b) > b->cfg.slot_ldo_ma)) {
		int v = tb_budget_next_victim(b);

		if (v < 0) {
			break;
		}
		off |= mark_off(b, tb_budget_off_mask(b, v));
	}
	return off;
}

enum tb_refusal tb_budget_check_peak(const struct tb_budget *b, int rail, uint32_t peak_ma, bool exclusive_ldo)
{
	enum tb_refusal r;
	uint32_t others;

	if (!tb_rail_valid(rail)) {
		return TB_REFUSE_BAD_RAIL;
	}
	r = state_check(b);
	if (r != TB_BUDGET_OK) {
		return r;
	}
	if (!(b->on & TB_RAIL_BIT(rail))) {
		return TB_REFUSE_ORDER;
	}
	others = tb_budget_used_ma(b) - b->declared_ma[rail];
	if (others + peak_ma > tb_budget_limit_ma(b)) {
		return TB_REFUSE_VSYS;
	}
	if (tb_rail_is_3v3(rail)) {
		uint32_t ldo_others = tb_budget_ldo_used_ma(b) - b->declared_ma[rail];

		if (exclusive_ldo) {
			for (int o = TB_RAIL_3V3_S1; o <= TB_RAIL_3V3_S5; o++) {
				if (o != rail && (b->on & TB_RAIL_BIT(o))) {
					return TB_REFUSE_OTHERS_ON;
				}
			}
		} else if (ldo_others + peak_ma > b->cfg.slot_ldo_ma) {
			return TB_REFUSE_LDO;
		}
	}
	return TB_BUDGET_OK;
}

const char *tb_refusal_str(enum tb_refusal r)
{
	switch (r) {
	case TB_BUDGET_OK: return "ok";
	case TB_REFUSE_BAD_RAIL: return "bad_rail";
	case TB_REFUSE_UNCONFIGURED: return "unconfigured";
	case TB_REFUSE_SUSPENDED: return "suspended";
	case TB_REFUSE_RULE: return "over_rule";
	case TB_REFUSE_VSYS: return "over_vsys_budget";
	case TB_REFUSE_LDO: return "over_slot_ldo";
	case TB_REFUSE_ORDER: return "order";
	case TB_REFUSE_ALREADY_ON: return "already_on";
	case TB_REFUSE_OTHERS_ON: return "other_3v3_rails_on";
	case TB_REFUSE_STATE: return "usb_configured";
	default: return "?";
	}
}

const char *tb_source_str(enum tb_source s)
{
	switch (s) {
	case TB_SRC_PENDING: return "pending";
	case TB_SRC_DEFAULT: return "default";
	case TB_SRC_1A5: return "1.5A";
	case TB_SRC_3A0: return "3.0A";
	case TB_SRC_ACCESSORY: return "accessory";
	case TB_SRC_NOT_ATTACHED: return "not_attached";
	case TB_SRC_UNREADABLE: return "unreadable";
	default: return "?";
	}
}

const char *tb_usb_state_str(enum tb_usb_state s)
{
	switch (s) {
	case TB_USB_UNCONFIGURED: return "unconfigured";
	case TB_USB_CONFIGURED: return "configured";
	case TB_USB_SUSPENDED: return "suspended";
	default: return "?";
	}
}
