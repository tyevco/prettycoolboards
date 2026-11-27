/*
 * tb/budget.h: the VSYS power budget of the rev A testbed (SPEC §3.2, §3.5, §8.4).
 *
 * Plain C, no hardware dependency: the caller feeds it USB events, what U_CC (the Type-C detect chip) reports,
 * and the operator's settings, asks it before enabling a rail, and switches off every rail in each mask it
 * returns. The hardware sequence (bus switch, mux, 5 V before 3.3 V) is the caller's.
 *
 * The rules, from SPEC §3.2 and §8.4:
 *  - No slot rail is powered until the host has configured the device; a bus reset or SET_CONFIGURATION(0)
 *    returns to that state (every rail off, the budget at the unconfigured 100 mA). USB suspend turns every
 *    rail off too.
 *  - After configuration the budget is what U_CC reports (Default 500 mA, 1.5 A, 3.0 A capped at the 2.8 A
 *    ceiling; an accessory, "not attached", or no answer: 500 mA). Until U_CC has been read (PENDING), the
 *    Default level applies.
 *  - base load + the declared currents of every enabled rail <= the budget; the 3.3 V slot rails together
 *    <= the slot LDO's 300 mA; each declared current <= the rail's coupon rule.
 *  - +5V_Sn only while +3V3_Sn is on (SPEC §3.5: 3.3 V first, then the descriptor, then 5 V).
 *  - An operator override can lower the budget, never raise it.
 *  - When the budget falls below what is enabled, rails go off, S5 first, then the rest in the reverse order
 *    of enabling, until the others fit.
 *
 * One addition that SPEC does not have (the report recommends it): a **bench supply** mode for bring-up step 5
 * (SPEC §10: the slot switches into dummy loads from a current-limited 5 V supply, with no USB host). The
 * operator declares the supply's limit; it replaces "configured" and the U_CC reading, is capped at the 2.8 A
 * ceiling, can be entered only while no host has configured the device, and any USB reset or configuration
 * ends it (every rail off). The bring-up app builds it in only with CONFIG_BRINGUP_BENCH_SUPPLY.
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#ifndef TB_BUDGET_H_
#define TB_BUDGET_H_

#include <stdbool.h>
#include <stdint.h>

#include "tb/rails.h"

#ifdef __cplusplus
extern "C" {
#endif

enum tb_usb_state {
	TB_USB_UNCONFIGURED = 0, /* default, addressed, or deconfigured */
	TB_USB_CONFIGURED,
	TB_USB_SUSPENDED, /* configured, then suspended */
};

enum tb_usb_event {
	TB_USB_EV_RESET = 0,
	TB_USB_EV_CONFIGURED, /* value: the configuration; 0 = deconfigured */
	TB_USB_EV_SUSPEND,
	TB_USB_EV_RESUME,
	TB_USB_EV_DISCONNECTED,
};

/* What U_CC reports (nets.TYPEC_BUDGET's keys, plus PENDING before the first read). */
enum tb_source {
	TB_SRC_PENDING = 0,
	TB_SRC_DEFAULT,
	TB_SRC_1A5,
	TB_SRC_3A0,
	TB_SRC_ACCESSORY,
	TB_SRC_NOT_ATTACHED,
	TB_SRC_UNREADABLE,
	TB_SRC_COUNT,
};

enum tb_refusal {
	TB_BUDGET_OK = 0,
	TB_REFUSE_BAD_RAIL,
	TB_REFUSE_UNCONFIGURED, /* the host has not configured the device (and no bench mode) */
	TB_REFUSE_SUSPENDED,
	TB_REFUSE_RULE,         /* the declared current exceeds the rail's coupon rule */
	TB_REFUSE_VSYS,         /* base + enabled + this > the VSYS budget */
	TB_REFUSE_LDO,          /* the 3.3 V slot rails together > the slot LDO's budget */
	TB_REFUSE_ORDER,        /* +5V_Sn while +3V3_Sn is off */
	TB_REFUSE_ALREADY_ON,
	TB_REFUSE_OTHERS_ON,    /* a peak check that needs every other 3.3 V slot rail off */
	TB_REFUSE_STATE,        /* not allowed in this USB state (bench mode while configured) */
};

struct tb_budget_cfg {
	uint32_t unconfigured_ma;       /* USB 2.0 before configuration: 100 mA */
	uint32_t vsys_max_ma;           /* the ceiling below the input breaker's minimum trip: 2800 mA */
	uint32_t slot_ldo_ma;           /* the 3.3 V slot rails together: 300 mA */
	uint32_t base_ma;               /* the board itself with no slot powered (estimate, SPEC §3.2) */
	uint32_t src_ma[TB_SRC_COUNT];  /* per U_CC report, before the ceiling */
	uint32_t rule_ma[TB_RAIL_COUNT];
};

struct tb_budget {
	struct tb_budget_cfg cfg;
	enum tb_usb_state usb;
	enum tb_source src;
	uint32_t override_ma; /* 0 = none */
	uint32_t bench_ma;    /* 0 = off */
	uint32_t on;          /* enabled rails */
	uint32_t declared_ma[TB_RAIL_COUNT];
	uint32_t seq[TB_RAIL_COUNT];
	uint32_t next_seq;
};

void tb_budget_init(struct tb_budget *b, const struct tb_budget_cfg *cfg);

/* What the source allows: the unconfigured level, the bench limit, or U_CC's level capped at the ceiling. */
uint32_t tb_budget_source_ma(const struct tb_budget *b);
/* The budget in force: the source's, lowered by the override if one is set. The INA226 0x40 alert limit. */
uint32_t tb_budget_limit_ma(const struct tb_budget *b);
/* base + the declared currents of the enabled rails. */
uint32_t tb_budget_used_ma(const struct tb_budget *b);
uint32_t tb_budget_ldo_used_ma(const struct tb_budget *b);
/* May any rail be powered now (configured and not suspended, or bench mode)? */
bool tb_budget_may_power(const struct tb_budget *b);
bool tb_budget_bench_active(const struct tb_budget *b);

enum tb_refusal tb_budget_check(const struct tb_budget *b, int rail, uint32_t declared_ma);
enum tb_refusal tb_budget_enable(struct tb_budget *b, int rail, uint32_t declared_ma);
/* Change an enabled rail's declared current (after its descriptor is read): lowering always succeeds; raising is
 * checked as an enable would be. */
enum tb_refusal tb_budget_redeclare(struct tb_budget *b, int rail, uint32_t declared_ma);
/* Mark a rail off. Turning a 3.3 V slot rail off takes its 5 V rail with it. Returns the rails marked off. */
uint32_t tb_budget_disable(struct tb_budget *b, int rail);
/* The rails that must go off to turn `rail` off (its own bit, plus the slot's 5 V for a 3.3 V rail). */
uint32_t tb_budget_off_mask(const struct tb_budget *b, int rail);

/* Each returns the rails it marked off; the caller switches them off. */
uint32_t tb_budget_usb_event(struct tb_budget *b, enum tb_usb_event ev, uint32_t value);
uint32_t tb_budget_set_source(struct tb_budget *b, enum tb_source src);
/* ma = 0 clears the override. An override above the source's level has no effect (it can only lower). */
uint32_t tb_budget_set_override(struct tb_budget *b, uint32_t ma);
/* ma = 0 ends bench mode. Refused (TB_REFUSE_STATE) while a host has the device configured. */
enum tb_refusal tb_budget_set_bench(struct tb_budget *b, uint32_t ma, uint32_t *shed);
/* The base load, e.g. from INA226 0x40 with no slot powered. */
uint32_t tb_budget_set_base(struct tb_budget *b, uint32_t ma);

/* The next rail to shed: S5's rails first, then the others in the reverse order of enabling; -1 if none. */
int tb_budget_next_victim(const struct tb_budget *b);
/* Shed until base + enabled fits the budget (and the slot LDO). Returns the rails marked off. */
uint32_t tb_budget_fit(struct tb_budget *b);

/*
 * A brief peak on an enabled rail (a self-test load): would base + the others + peak fit the VSYS budget?
 * With exclusive_ldo the slot LDO's 300 mA is not applied to the peak (a test of a few tens of ms), but every
 * other 3.3 V slot rail must be off.
 */
enum tb_refusal tb_budget_check_peak(const struct tb_budget *b, int rail, uint32_t peak_ma, bool exclusive_ldo);

const char *tb_refusal_str(enum tb_refusal r);
const char *tb_source_str(enum tb_source s);
const char *tb_usb_state_str(enum tb_usb_state s);

#ifdef __cplusplus
}
#endif

#endif /* TB_BUDGET_H_ */
