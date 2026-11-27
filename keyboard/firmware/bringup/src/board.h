/*
 * The board service of the bring-up app: the hardware tables (from the kbd_testbed_a devicetree), the state
 * (budget, rails, slots, U_CC) and the sequences that change it (SPEC §3.5, §8.4).
 *
 * Locking: everything here that touches the hardware or tb_state runs with tb_lock held. Never print to a
 * shell with tb_lock held: a shell whose host does not read blocks the writer, and the board service must
 * always be able to switch rails off. Collect, unlock, then print.
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#ifndef TB_BOARD_H_
#define TB_BOARD_H_

#include <stdbool.h>
#include <stdint.h>

#include <zephyr/drivers/adc.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/kernel.h>

#include "tb/budget.h"
#include "tb/desc.h"
#include "tb/rails.h"
#include "tb_board_map.h"

struct tb_slot_hw {
	int n;
	struct adc_dt_spec lane[4];
	struct gpio_dt_spec g[6];
	struct gpio_dt_spec cs[2];
	struct gpio_dt_spec irq;
	bool irq_bkin;
	struct gpio_dt_spec present, en3, en5, busen, led;
	struct gpio_dt_spec pg5; /* port NULL when the 5 V rail has no power-good (S1-S4) */
	const struct device *i2c_ch;
	uint32_t rule3_ma, rule5_ma;
	uint32_t trip3_ma[3], trip5_ma[3];
	int rail3, rail5;
};

struct tb_signals {
	struct gpio_dt_spec exp_int, slot_fault, pm_alert, vsys_pg, s5_pg, usbc_int, kvm_present, mux_rst, kvm_rst,
		en_5v_kvm, slot_sync, rig_mark, rig_trig;
	struct i2c_dt_spec typec, mux;
	const struct device *exp[TB_EXP_COUNT];
	uint8_t exp_addr[TB_EXP_COUNT];
	const struct device *i2c_pm;
	uint32_t ldo_ma, base_ma, vsys_max_ma, vsys_unconf_ma, kvm_rule_ma;
	uint32_t kvm_trip_ma[3];
};

extern const struct tb_slot_hw tb_slots[TB_SLOTS];
extern const struct tb_signals tb_sig;

/* What the boot hook found in the expanders and the mux before the drivers touched them (main.c). */
struct tb_boot_snapshot {
	bool valid;
	int err[TB_EXP_COUNT];
	uint16_t in[TB_EXP_COUNT], out[TB_EXP_COUNT], cfg[TB_EXP_COUNT];
	int mux_err;
	uint8_t mux_ctrl;
	uint32_t reset_cause;
	/* per bus: 0 answered, 1 answered after a bus recovery, < 0 the error (main.c bus_check()) */
	int recover_i2c1, recover_i2c4;
};
extern struct tb_boot_snapshot tb_boot;

struct tb_restore_report {
	int err;
	uint16_t out[TB_EXP_COUNT], cfg[TB_EXP_COUNT];
	bool exp_ok[TB_EXP_COUNT];
	uint8_t mux_ctrl;
	int mux_err;
	bool ok;
};

struct tb_state {
	struct tb_budget budget;
	int64_t on_since_ms[TB_RAIL_COUNT];
	uint8_t present;   /* bit n-1: PRESENT_N of slot n reads low (a coupon) */
	uint8_t bus_closed; /* bit n-1: slot n's bus switch closed */
	struct tb_desc desc[TB_SLOTS];
	int desc_err[TB_SLOTS]; /* tb_desc_err, or 1 = not read */
	/* U_CC */
	bool cc_decided, cc_ok;
	uint8_t cc_r08, cc_r09, cc_rev;
	int64_t boot_ms;
	/* a test in progress: the service skips fault and alert attribution on these rails until test_until */
	uint32_t test_rails;
	int64_t test_until_ms;
	struct tb_restore_report restore;
	uint32_t polls, faults_handled;
};

extern struct k_mutex tb_lock;
extern struct tb_state tb;

/* Boot: budget, the expander and mux restore, the monitors, the slot lines. */
int tb_board_init(void);
/* Every rail off, bus switches open, MCU slot lines high-impedance, the mux deselected. */
int tb_restore(struct tb_restore_report *rep);
int tb_mux_deselect(void);
int tb_mux_read(uint8_t *ctrl);

/* Raw expander registers (two bytes from reg, little-endian port 0 first). */
int tb_exp_read(int exp, uint8_t reg, uint16_t *val);
/* U_EXP2's input port, through its driver (clears its INT). */
int tb_exp2_inputs(uint16_t *raw);
/* Physical level of a pin of an expander's port value, and whether it is active (flags applied). */
bool tb_pin_level(uint16_t port, const struct gpio_dt_spec *s);
bool tb_pin_active(uint16_t port, const struct gpio_dt_spec *s);

/* Enable one rail (budget, order, presence checked). why gets the refusal. A closed bus switch of the slot is
 * opened first (SPEC §3.5); the caller closes it again once the rail is up. */
int tb_rail_on(int rail, uint32_t declared_ma, enum tb_refusal *why);
/* Turn rails off in SPEC §3.5's order: bus switch open, slot lines idle, mux deselected, 5 V, then 3.3 V. Also
 * marks them off in the budget and posts a rail_off event per rail. Returns the rails switched off. */
uint32_t tb_rails_off(uint32_t mask, const char *reason);
/* A slot's MCU lines for a powered slot (CS high, G low, IRQ input) or an unpowered one (high-impedance). */
int tb_slot_lines(int slot, bool powered);
int tb_slot_bus(int slot, bool closed);
bool tb_rail_settling(int rail);
/* The monitor's alert for a declared current: 10 % + 1 mA above it, under 95 % of the switch's minimum trip. */
uint32_t tb_rail_alert_ua(int rail, uint32_t declared_ma);

/* Apply a rail mask the budget marked off (it already updated its own state). */
void tb_apply_budget_off(uint32_t mask, const char *reason);

const struct tb_slot_hw *tb_slot_hw(int slot);
/* A hook after the firmware drives a slot's G-line or SYNC directly: nothing on hardware; the simulated board
 * (sim/world.c) re-evaluates its model there, since an emulated GPIO output has no callback. */
void tb_sim_sync(void);

/* The boot report (main.c), one record per call of line(). */
void tb_boot_report(void (*line)(void *ctx, const char *s), void *ctx);
/* The i-th alternate converter channel of a slot's lanes (devicetree alt-adc-channels); -ENOENT past the end. */
int tb_slot_alt(int slot, int i, uint8_t *lane, uint8_t *adc, uint8_t *ch);

#endif /* TB_BOARD_H_ */
