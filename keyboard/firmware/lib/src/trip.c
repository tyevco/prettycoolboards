/*
 * Fault and alert classification. See tb/trip.h.
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include <string.h>

#include "tb/trip.h"

void tb_trip_cfg_defaults(struct tb_trip_cfg *cfg)
{
	memset(cfg, 0, sizeof(*cfg));
	cfg->limit_pct = 80;
	cfg->uv_3v3_mv = 3000;
	cfg->uv_5v_mv = 4300;
	cfg->dead_mv = 500;
	cfg->live_mv = 1000;
	cfg->live_ua = 5000;
}

static void add(struct tb_trip_result *r, uint8_t kind, int rail, int slot, int32_t value)
{
	if (r->n >= TB_TRIP_MAX_FINDINGS) {
		r->truncated = true;
		return;
	}
	r->f[r->n].kind = kind;
	r->f[r->n].rail = (int8_t)rail;
	r->f[r->n].slot = (int8_t)slot;
	r->f[r->n].value = value;
	r->n++;
}

static int32_t uv_for(const struct tb_trip_cfg *cfg, int rail)
{
	return tb_rail_is_3v3(rail) ? cfg->uv_3v3_mv : cfg->uv_5v_mv;
}

void tb_trip_classify(const struct tb_trip_cfg *cfg, const struct tb_trip_snapshot *s, struct tb_trip_result *out)
{
	uint32_t on = s->on & TB_RAIL_MASK_ALL;
	uint32_t steady = on & ~s->settling;

	memset(out, 0, sizeof(*out));

	if (!s->vsys_pg) {
		add(out, TB_F_VSYS_PG_LOW, -1, 0, s->vsys.valid ? s->vsys.bus_mv : 0);
		out->all_off = true;
		out->off |= on;
	}

	for (int slot = 1; slot <= TB_SLOTS; slot++) {
		if ((s->absent & (1u << (slot - 1))) && (on & tb_slot_rail_mask(slot))) {
			add(out, TB_F_COUPON_REMOVED, -1, slot, 0);
			out->off |= on & tb_slot_rail_mask(slot);
		}
	}

	if ((steady & TB_RAIL_BIT(TB_RAIL_5V_S5)) && !s->s5_pg) {
		add(out, TB_F_S5_BREAKER, TB_RAIL_5V_S5, 5, 0);
		out->off |= TB_RAIL_BIT(TB_RAIL_5V_S5);
	}

	for (int r = 0; r < TB_RAIL_COUNT; r++) {
		const struct tb_rail_obs *o = &s->rail[r];

		if ((on & TB_RAIL_BIT(r)) && o->monitored && !o->valid) {
			add(out, TB_F_MONITOR_LOST, r, tb_rail_slot(r), 0);
			out->off |= TB_RAIL_BIT(r);
		}
	}

	if (s->fault_low) {
		uint32_t limiting = 0;

		for (int r = 0; r < TB_RAIL_COUNT; r++) {
			const struct tb_rail_obs *o = &s->rail[r];
			int64_t floor_ua = (int64_t)cfg->trip_min_ma[r] * 10 * cfg->limit_pct;

			if (!(on & TB_RAIL_MASK_TPS2553 & TB_RAIL_BIT(r)) || !o->monitored || !o->valid) {
				continue;
			}
			if ((cfg->trip_min_ma[r] != 0 && (int64_t)o->current_ua >= floor_ua) ||
			    ((steady & TB_RAIL_BIT(r)) && o->bus_mv < uv_for(cfg, r))) {
				limiting |= TB_RAIL_BIT(r);
				add(out, TB_F_SWITCH_LIMIT, r, tb_rail_slot(r), o->current_ua);
			}
		}
		if (limiting != 0) {
			out->off |= limiting;
		} else if (on & TB_RAIL_BIT(TB_RAIL_5V_KVM)) {
			add(out, TB_F_FAULT_KVM, TB_RAIL_5V_KVM, 0, 0);
			out->off |= TB_RAIL_BIT(TB_RAIL_5V_KVM);
		} else {
			/* Nothing reads at its limit (thermal cycling, a transient, a reverse-voltage event): every
			 * TPS2553 rail goes off, since the board cannot say which one it was. */
			add(out, TB_F_FAULT_UNATTRIBUTED, -1, 0, 0);
			out->off |= on & TB_RAIL_MASK_TPS2553;
		}
	}

	if (s->alert_low) {
		bool any = false;

		for (int r = 0; r < TB_RAIL_COUNT; r++) {
			const struct tb_rail_obs *o = &s->rail[r];

			if (o->monitored && o->valid && o->alert) {
				any = true;
				if (on & TB_RAIL_BIT(r)) {
					add(out, TB_F_ALERT, r, tb_rail_slot(r), o->current_ua);
					out->off |= TB_RAIL_BIT(r);
				}
			}
		}
		if (s->vsys.valid && s->vsys.alert) {
			any = true;
		}
		if (!any) {
			add(out, TB_F_ALERT_UNATTRIBUTED, -1, 0, 0);
		}
	}

	if (s->vsys.valid && (s->vsys.alert ||
			      (s->vsys_limit_ma != 0 && s->vsys.current_ua > (int32_t)(s->vsys_limit_ma * 1000u)))) {
		add(out, TB_F_VSYS_OVER, -1, 0, s->vsys.current_ua);
		out->shed_one = true;
	}

	for (int r = 0; r < TB_RAIL_COUNT; r++) {
		const struct tb_rail_obs *o = &s->rail[r];

		if (!o->monitored || !o->valid) {
			continue;
		}
		if ((steady & TB_RAIL_BIT(r)) && !(out->off & TB_RAIL_BIT(r))) {
			if (o->bus_mv < cfg->dead_mv) {
				add(out, TB_F_RAIL_DEAD, r, tb_rail_slot(r), o->bus_mv);
				out->off |= TB_RAIL_BIT(r);
			} else if (o->bus_mv < uv_for(cfg, r)) {
				add(out, TB_F_RAIL_SAG, r, tb_rail_slot(r), o->bus_mv);
			}
		} else if (!(on & TB_RAIL_BIT(r)) && (o->bus_mv > cfg->live_mv || o->current_ua > cfg->live_ua)) {
			add(out, TB_F_RAIL_LIVE_OFF, r, tb_rail_slot(r), o->bus_mv);
		}
	}

	/* A slot's 3.3 V never goes off before its 5 V (SPEC §3.5). */
	for (int slot = 1; slot <= TB_SLOTS; slot++) {
		if (out->off & TB_RAIL_BIT(tb_rail_3v3(slot))) {
			out->off |= on & TB_RAIL_BIT(tb_rail_5v(slot));
		}
	}
	out->off &= on;
}

const char *tb_finding_str(uint8_t kind)
{
	switch (kind) {
	case TB_F_VSYS_PG_LOW: return "vsys_pg_low";
	case TB_F_COUPON_REMOVED: return "coupon_removed";
	case TB_F_S5_BREAKER: return "s5_breaker";
	case TB_F_MONITOR_LOST: return "monitor_lost";
	case TB_F_SWITCH_LIMIT: return "switch_limit";
	case TB_F_FAULT_KVM: return "fault_kvm";
	case TB_F_FAULT_UNATTRIBUTED: return "fault_unattributed";
	case TB_F_ALERT: return "alert";
	case TB_F_ALERT_UNATTRIBUTED: return "alert_unattributed";
	case TB_F_VSYS_OVER: return "vsys_over";
	case TB_F_RAIL_DEAD: return "rail_dead";
	case TB_F_RAIL_SAG: return "rail_sag";
	case TB_F_RAIL_LIVE_OFF: return "rail_live_off";
	default: return "?";
	}
}
