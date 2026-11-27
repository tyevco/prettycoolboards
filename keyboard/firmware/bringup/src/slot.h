/*
 * Powering a slot and discovering its coupon (SPEC §3.5, §4.6, §8.4): +3V3 first at the coupon rule, the
 * descriptor, its declared currents against the rules and budgets, +5V if it asks, then the bus switch.
 * Callers hold tb_lock (the sequence sleeps for the settling time, but never prints).
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#ifndef TB_SLOT_H_
#define TB_SLOT_H_

#include <stdbool.h>
#include <stdint.h>

#include "monitors.h"
#include "tb/budget.h"

struct tb_slot_on_opts {
	bool use_desc;     /* read the descriptor and take its currents */
	uint32_t ma3, ma5; /* without a descriptor: the declared currents (ma5 = 0: no 5 V) */
	uint32_t probe_ma; /* with a descriptor: +3V3's declaration until it is read (0 = the 250 mA coupon rule) */
	bool keep_blank;   /* a blank or unreadable descriptor keeps +3V3 on (to write one) */
};

struct tb_slot_on_result {
	const char *err;     /* a short token on failure */
	enum tb_refusal why3, why5;
	struct tb_mon_reading r3, r5;
	bool fault;          /* SLOT_FAULT_N after the settling time */
	int desc;            /* tb_desc_err, TB_DESCIO_BUS_ERR, or 1 = not read */
	const char *rule;    /* tb_desc_check_slot()'s token, or NULL */
	bool on3, on5, bus;
	uint32_t ma3, ma5;
};

int tb_slot_on(int slot, const struct tb_slot_on_opts *o, struct tb_slot_on_result *res);
void tb_slot_off(int slot, const char *reason);
/* After an enable: wait the settling time, then read the rail and SLOT_FAULT_N. */
int tb_rail_settle(int rail, struct tb_mon_reading *r, bool *fault);

#endif /* TB_SLOT_H_ */
