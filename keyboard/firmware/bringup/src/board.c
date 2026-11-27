/*
 * The board service's hardware tables and sequences (see board.h). SPEC §3.5 and §8.4 are the rules.
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include <string.h>

#include <zephyr/devicetree.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/sys/util.h>
#include <zephyr/toolchain.h>

#include "board.h"
#include "events.h"
#include "monitors.h"
#include "tb/ina226.h"

LOG_MODULE_REGISTER(tb_board, LOG_LEVEL_INF);

#define TBN DT_NODELABEL(testbed)

/* TIM1 drives S5's G-lines and takes S5_IRQ_N as its break input only when an overlay enables it. */
#define TIM1_IN_USE DT_NODE_HAS_STATUS_OKAY(DT_NODELABEL(pwm1))

#define SLOT_HW(node)                                                                              \
	{                                                                                          \
		.n = DT_PROP(node, slot),                                                          \
		.lane = {ADC_DT_SPEC_GET_BY_IDX(node, 0), ADC_DT_SPEC_GET_BY_IDX(node, 1),         \
			 ADC_DT_SPEC_GET_BY_IDX(node, 2), ADC_DT_SPEC_GET_BY_IDX(node, 3)},        \
		.g = {GPIO_DT_SPEC_GET_BY_IDX(node, g_gpios, 0), GPIO_DT_SPEC_GET_BY_IDX(node, g_gpios, 1), \
		      GPIO_DT_SPEC_GET_BY_IDX(node, g_gpios, 2), GPIO_DT_SPEC_GET_BY_IDX(node, g_gpios, 3), \
		      GPIO_DT_SPEC_GET_BY_IDX(node, g_gpios, 4),                                   \
		      GPIO_DT_SPEC_GET_BY_IDX(node, g_gpios, 5)},                                  \
		.cs = {GPIO_DT_SPEC_GET_BY_IDX(node, cs_gpios, 0),                                 \
		       GPIO_DT_SPEC_GET_BY_IDX(node, cs_gpios, 1)},                                \
		.irq = GPIO_DT_SPEC_GET(node, irq_gpios),                                          \
		.irq_bkin = DT_PROP(node, irq_is_tim1_bkin),                                       \
		.present = GPIO_DT_SPEC_GET(node, present_gpios),                                  \
		.en3 = GPIO_DT_SPEC_GET(node, en_3v3_gpios),                                       \
		.en5 = GPIO_DT_SPEC_GET(node, en_5v_gpios),                                        \
		.busen = GPIO_DT_SPEC_GET(node, busen_gpios),                                      \
		.led = GPIO_DT_SPEC_GET(node, led_gpios),                                          \
		.pg5 = GPIO_DT_SPEC_GET_OR(node, pg_5v_gpios, {0}),                                \
		.i2c_ch = DEVICE_DT_GET(DT_PHANDLE(node, i2c_channel)),                            \
		.rule3_ma = DT_PROP(node, rule_3v3_milliamps),                                     \
		.rule5_ma = DT_PROP(node, rule_5v_milliamps),                                      \
		.trip3_ma = DT_PROP(node, trip_3v3_milliamps),                                     \
		.trip5_ma = DT_PROP(node, trip_5v_milliamps),                                      \
		.rail3 = DT_PROP(node, rail_3v3),                                                  \
		.rail5 = DT_PROP(node, rail_5v),                                                   \
	}

const struct tb_slot_hw tb_slots[TB_SLOTS] = {
	SLOT_HW(DT_NODELABEL(slot1)), SLOT_HW(DT_NODELABEL(slot2)), SLOT_HW(DT_NODELABEL(slot3)),
	SLOT_HW(DT_NODELABEL(slot4)), SLOT_HW(DT_NODELABEL(slot5)),
};

/* The alternate converter channels per slot: <lane adc channel> triples from the devicetree. */
#define ALT_TAB(node) DT_PROP_OR(node, alt_adc_channels, {0})
#define ALT_LEN(node) DT_PROP_LEN_OR(node, alt_adc_channels, 0)
static const uint8_t alt1[] = ALT_TAB(DT_NODELABEL(slot1));
static const uint8_t alt2[] = ALT_TAB(DT_NODELABEL(slot2));
static const uint8_t alt3[] = ALT_TAB(DT_NODELABEL(slot3));
static const uint8_t alt4[] = ALT_TAB(DT_NODELABEL(slot4));
static const uint8_t alt5[] = ALT_TAB(DT_NODELABEL(slot5));
static const uint8_t *const alt_tab[TB_SLOTS] = {alt1, alt2, alt3, alt4, alt5};
static const uint8_t alt_len[TB_SLOTS] = {
	ALT_LEN(DT_NODELABEL(slot1)), ALT_LEN(DT_NODELABEL(slot2)), ALT_LEN(DT_NODELABEL(slot3)),
	ALT_LEN(DT_NODELABEL(slot4)), ALT_LEN(DT_NODELABEL(slot5)),
};

const struct tb_signals tb_sig = {
	.exp_int = GPIO_DT_SPEC_GET(TBN, exp_int_gpios),
	.slot_fault = GPIO_DT_SPEC_GET(TBN, slot_fault_gpios),
	.pm_alert = GPIO_DT_SPEC_GET(TBN, pm_alert_gpios),
	.vsys_pg = GPIO_DT_SPEC_GET(TBN, vsys_pg_gpios),
	.s5_pg = GPIO_DT_SPEC_GET(TBN, s5_pg_gpios),
	.usbc_int = GPIO_DT_SPEC_GET(TBN, usbc_int_gpios),
	.kvm_present = GPIO_DT_SPEC_GET(TBN, kvm_present_gpios),
	.mux_rst = GPIO_DT_SPEC_GET(TBN, mux_rst_gpios),
	.kvm_rst = GPIO_DT_SPEC_GET(TBN, kvm_rst_gpios),
	.en_5v_kvm = GPIO_DT_SPEC_GET(TBN, en_5v_kvm_gpios),
	.slot_sync = GPIO_DT_SPEC_GET(TBN, slot_sync_gpios),
	.rig_mark = GPIO_DT_SPEC_GET(TBN, rig_mark_gpios),
	.rig_trig = GPIO_DT_SPEC_GET(TBN, rig_trig_gpios),
	.typec = I2C_DT_SPEC_GET(DT_PHANDLE(TBN, typec)),
	.mux = I2C_DT_SPEC_GET(DT_PHANDLE(TBN, slot_mux)),
	.exp = {DEVICE_DT_GET(DT_NODELABEL(u_exp1)), DEVICE_DT_GET(DT_NODELABEL(u_exp2)),
		DEVICE_DT_GET(DT_NODELABEL(u_exp3))},
	.exp_addr = TB_EXP_ADDRS,
	.i2c_pm = DEVICE_DT_GET(DT_NODELABEL(i2c1)),
	.ldo_ma = DT_PROP(TBN, slot_ldo_milliamps),
	.base_ma = DT_PROP(TBN, base_load_milliamps),
	.vsys_max_ma = DT_PROP(TBN, vsys_budget_max_milliamps),
	.vsys_unconf_ma = DT_PROP(TBN, vsys_budget_unconfigured_milliamps),
	.kvm_rule_ma = DT_PROP(TBN, kvm_rule_milliamps),
	.kvm_trip_ma = DT_PROP(TBN, kvm_trip_milliamps),
};

/* The devicetree and the generated map come from the same nets.py: check that they agree where both say. */
BUILD_ASSERT(DT_PROP(TBN, slot_ldo_milliamps) == TB_SLOT_LDO_MA);
BUILD_ASSERT(DT_PROP(TBN, vsys_budget_max_milliamps) == TB_VSYS_BUDGET_MAX_MA);
BUILD_ASSERT(DT_PROP(TBN, vsys_budget_unconfigured_milliamps) == TB_VSYS_BUDGET_UNCONFIGURED_MA);
BUILD_ASSERT(DT_REG_ADDR(DT_PHANDLE(TBN, typec)) == TB_I2C_ADDR_TUSB320);
BUILD_ASSERT(DT_REG_ADDR(DT_PHANDLE(TBN, slot_mux)) == TB_I2C_ADDR_MUX);
BUILD_ASSERT(DT_PROP(DT_NODELABEL(slot1), rail_3v3) == TB_RAIL_3V3_S1);
BUILD_ASSERT(DT_PROP(DT_NODELABEL(slot5), rail_5v) == TB_RAIL_5V_S5);

__weak void tb_sim_sync(void)
{
}

K_MUTEX_DEFINE(tb_lock);
struct tb_state tb;
struct tb_boot_snapshot tb_boot;

const struct tb_slot_hw *tb_slot_hw(int slot)
{
	return (slot >= 1 && slot <= TB_SLOTS) ? &tb_slots[slot - 1] : NULL;
}

bool tb_pin_level(uint16_t port, const struct gpio_dt_spec *s)
{
	return ((port >> s->pin) & 1u) != 0;
}

bool tb_pin_active(uint16_t port, const struct gpio_dt_spec *s)
{
	return tb_pin_level(port, s) != ((s->dt_flags & GPIO_ACTIVE_LOW) != 0);
}

int tb_exp_read(int exp, uint8_t reg, uint16_t *val)
{
	uint8_t buf[2];
	int err;

	if (exp < 0 || exp >= TB_EXP_COUNT) {
		return -EINVAL;
	}
	err = i2c_write_read(tb_sig.i2c_pm, tb_sig.exp_addr[exp], &reg, 1, buf, 2);
	if (err == 0) {
		*val = (uint16_t)(buf[0] | ((uint16_t)buf[1] << 8));
	}
	return err;
}

int tb_exp2_inputs(uint16_t *raw)
{
	gpio_port_value_t v = 0;
	int err = gpio_port_get_raw(tb_sig.exp[TB_EXP_EXP2_INDEX], &v);

	*raw = (uint16_t)v;
	return err;
}

int tb_mux_read(uint8_t *ctrl)
{
	return i2c_read_dt(&tb_sig.mux, ctrl, 1);
}

int tb_mux_deselect(void)
{
	/* The mux's own driver keeps a channel cache of 0 with idle-disconnect; writing 0 keeps it true. */
	uint8_t zero = 0;

	return i2c_write_dt(&tb_sig.mux, &zero, 1);
}

static int cfg(const struct gpio_dt_spec *s, gpio_flags_t f)
{
	if (s->port == NULL) {
		return 0;
	}
	if (!gpio_is_ready_dt(s)) {
		return -ENODEV;
	}
	return gpio_pin_configure_dt(s, f);
}

int tb_slot_lines(int slot, bool powered)
{
	const struct tb_slot_hw *h = tb_slot_hw(slot);
	int err = 0;

	if (h == NULL) {
		return -EINVAL;
	}
	for (int i = 0; i < 2; i++) {
		err |= cfg(&h->cs[i], powered ? GPIO_OUTPUT_INACTIVE : GPIO_DISCONNECTED);
	}
	for (int i = 0; i < 6; i++) {
		if (h->g[i].port == tb_sig.exp[TB_EXP_EXP3_INDEX]) {
			/* G4/G5 of S1-S4 on U_EXP3: driven low either way (SPEC §3.5 allows low into an unpowered
			 * slot), and the 100 k pull-downs hold them there after a reset. */
			err |= cfg(&h->g[i], GPIO_OUTPUT_INACTIVE);
		} else {
			err |= cfg(&h->g[i], powered ? GPIO_OUTPUT_INACTIVE : GPIO_DISCONNECTED);
		}
	}
	if (!(h->irq_bkin && TIM1_IN_USE)) {
		/* With TIM1 running, PE15 must stay TIM1_BKIN: never gpio_pin_configure() it (SPEC §5.3). */
		err |= cfg(&h->irq, powered ? GPIO_INPUT : GPIO_DISCONNECTED);
	}
	return err ? -EIO : 0;
}

int tb_slot_bus(int slot, bool closed)
{
	const struct tb_slot_hw *h = tb_slot_hw(slot);
	int err;

	if (h == NULL) {
		return -EINVAL;
	}
	err = gpio_pin_set_dt(&h->busen, closed ? 1 : 0);
	if (err == 0) {
		WRITE_BIT(tb.bus_closed, slot - 1, closed);
	}
	return err;
}

bool tb_rail_settling(int rail)
{
	return tb_rail_valid(rail) && (tb.budget.on & TB_RAIL_BIT(rail)) &&
	       k_uptime_get() - tb.on_since_ms[rail] < CONFIG_BRINGUP_SETTLE_MS;
}

static const struct gpio_dt_spec *en_of(int rail)
{
	int slot = tb_rail_slot(rail);

	if (rail == TB_RAIL_5V_KVM) {
		return &tb_sig.en_5v_kvm;
	}
	if (slot < 1) {
		return NULL;
	}
	return tb_rail_is_3v3(rail) ? &tb_slots[slot - 1].en3 : &tb_slots[slot - 1].en5;
}

/* Alert limit for a declared current: 10 % + 1 mA above it, kept under 95 % of the switch's minimum trip. */
uint32_t tb_rail_alert_ua(int rail, uint32_t declared_ma)
{
	static const uint32_t trip[TB_RAIL_COUNT][3] = TB_RAIL_TRIP_MA;
	uint32_t ua = declared_ma * 1100u + 1000u;
	uint32_t cap = trip[rail][0] * 950u;

	return MIN(ua, cap);
}

int tb_rail_on(int rail, uint32_t declared_ma, enum tb_refusal *why)
{
	const struct gpio_dt_spec *en = en_of(rail);
	const struct tb_mon *mon = tb_mon_for_rail(rail);
	int slot = tb_rail_slot(rail);
	enum tb_refusal r;
	int err;

	*why = TB_BUDGET_OK;
	if (en == NULL) {
		*why = TB_REFUSE_BAD_RAIL;
		return -EINVAL;
	}
	if (slot >= 1 && !(tb.present & BIT(slot - 1))) {
		return -ENODEV; /* PRESENT_N reads high: no coupon (SPEC §3.5) */
	}
	r = tb_budget_check(&tb.budget, rail, declared_ma);
	if (r != TB_BUDGET_OK) {
		*why = r;
		return -EPERM;
	}
	if (mon != NULL) {
		err = tb_mon_set_alert(mon, tb_rail_alert_ua(rail, declared_ma));
		if (err != 0) {
			return err; /* no monitor, no rail */
		}
	}
	if (slot >= 1 && (tb.bus_closed & BIT(slot - 1))) {
		/* SPEC §3.5: "close the slot's bus switch only after its rails are up". The caller closes it again
		 * once this rail has settled (tb_slot_on, the self-test). */
		err = tb_slot_bus(slot, false);
		if (err != 0) {
			return err;
		}
	}
	err = gpio_pin_set_dt(en, 1);
	if (err != 0) {
		return err;
	}
	(void)tb_budget_enable(&tb.budget, rail, declared_ma);
	tb.on_since_ms[rail] = k_uptime_get();
	if (slot >= 1 && tb_rail_is_3v3(rail)) {
		(void)gpio_pin_set_dt(&tb_slots[slot - 1].led, 1);
	}
	tb_ev("kind=rail_on rail=%s declared_ma=%u", tb_rail_name(rail), declared_ma);
	return 0;
}

static void hw_off(uint32_t mask, const char *reason)
{
	/* Per slot in SPEC §3.5's order: the bus switch open before either rail goes down ("open it before they go
	 * down"; it stays open until the slot is brought up again), the slot lines idle and the mux deselected when
	 * its 3.3 V goes, then 5 V, then 3.3 V. */
	for (int slot = TB_SLOTS; slot >= 1; slot--) {
		const struct tb_slot_hw *h = &tb_slots[slot - 1];
		bool off3 = mask & TB_RAIL_BIT(h->rail3);
		bool off5 = mask & TB_RAIL_BIT(h->rail5);

		if (off3 || off5) {
			(void)tb_slot_bus(slot, false);
		}
		if (off3) {
			(void)tb_slot_lines(slot, false);
			(void)tb_mux_deselect();
		}
		if (off5 || off3) {
			(void)gpio_pin_set_dt(&h->en5, 0);
		}
		if (off3) {
			(void)gpio_pin_set_dt(&h->en3, 0);
			(void)gpio_pin_set_dt(&h->led, 0);
			tb.desc_err[slot - 1] = 1; /* unpowered: the descriptor must be read again */
		}
	}
	if (mask & TB_RAIL_BIT(TB_RAIL_5V_KVM)) {
		(void)gpio_pin_set_dt(&tb_sig.en_5v_kvm, 0);
	}
	for (int r = 0; r < TB_RAIL_COUNT; r++) {
		if (mask & TB_RAIL_BIT(r)) {
			const struct tb_mon *mon = tb_mon_for_rail(r);

			if (mon != NULL) {
				(void)tb_mon_set_alert(mon, 0);
			}
			tb_ev("kind=rail_off rail=%s reason=%s", tb_rail_name(r), reason);
		}
	}
}

void tb_apply_budget_off(uint32_t mask, const char *reason)
{
	if (mask != 0) {
		hw_off(mask, reason);
	}
}

uint32_t tb_rails_off(uint32_t mask, const char *reason)
{
	uint32_t off = 0;

	mask &= TB_RAIL_MASK_ALL;
	for (int r = 0; r < TB_RAIL_COUNT; r++) {
		if (mask & TB_RAIL_BIT(r)) {
			off |= tb_budget_off_mask(&tb.budget, r);
		}
	}
	/* Switch off what the firmware believes is on, and also what it was asked to (a rail left on by a
	 * failed sequence is never "not on" for the hardware). */
	hw_off(off | mask, reason);
	for (int r = 0; r < TB_RAIL_COUNT; r++) {
		if (off & TB_RAIL_BIT(r)) {
			(void)tb_budget_disable(&tb.budget, r);
		}
	}
	return off | mask;
}

int tb_restore(struct tb_restore_report *rep)
{
	static const uint16_t safe_out[TB_EXP_COUNT] = TB_EXP_SAFE_OUTPUT;
	static const uint16_t safe_cfg[TB_EXP_COUNT] = TB_EXP_SAFE_CONFIG;
	static const uint16_t out_mask[TB_EXP_COUNT] = TB_EXP_OUTPUT_MASK;
	int err = 0;

	memset(rep, 0, sizeof(*rep));
	/* The mux first: a channel left on joins I2C4's pull-ups to an unpowered slot's (SPEC §3.5). */
	rep->mux_err = tb_mux_deselect();
	/* Slot lines idle, then every bus switch open, then the rails off, 5 V first. */
	for (int slot = 1; slot <= TB_SLOTS; slot++) {
		err |= tb_slot_lines(slot, false);
	}
	err |= cfg(&tb_sig.slot_sync, GPIO_OUTPUT_INACTIVE);
	err |= cfg(&tb_sig.rig_mark, GPIO_OUTPUT_INACTIVE);
	err |= cfg(&tb_sig.rig_trig, GPIO_INPUT);
	for (int slot = 1; slot <= TB_SLOTS; slot++) {
		err |= cfg(&tb_slots[slot - 1].busen, GPIO_OUTPUT_INACTIVE);
	}
	tb.bus_closed = 0;
	for (int slot = 1; slot <= TB_SLOTS; slot++) {
		err |= cfg(&tb_slots[slot - 1].en5, GPIO_OUTPUT_INACTIVE);
	}
	err |= cfg(&tb_sig.en_5v_kvm, GPIO_OUTPUT_INACTIVE);
	for (int slot = 1; slot <= TB_SLOTS; slot++) {
		err |= cfg(&tb_slots[slot - 1].en3, GPIO_OUTPUT_INACTIVE);
		err |= cfg(&tb_slots[slot - 1].led, GPIO_OUTPUT_INACTIVE);
	}
	/* The KVM coupon held in reset; the mux pulsed through its RESET and deselected again. */
	err |= cfg(&tb_sig.kvm_rst, GPIO_OUTPUT_ACTIVE);
	err |= cfg(&tb_sig.mux_rst, GPIO_OUTPUT_ACTIVE);
	k_busy_wait(10);
	err |= gpio_pin_set_dt(&tb_sig.mux_rst, 0);
	k_busy_wait(10);
	rep->mux_err |= tb_mux_deselect();
	rep->mux_err |= tb_mux_read(&rep->mux_ctrl);
	for (int r = 0; r < TB_RAIL_COUNT; r++) {
		(void)tb_budget_disable(&tb.budget, r);
	}

	/* Read every expander back and compare with the generated restore state. */
	rep->ok = err == 0 && rep->mux_err == 0 && rep->mux_ctrl == 0;
	for (int i = 0; i < TB_EXP_COUNT; i++) {
		int e = tb_exp_read(i, 0x02, &rep->out[i]);

		e |= tb_exp_read(i, 0x06, &rep->cfg[i]);
		rep->exp_ok[i] = e == 0 && rep->cfg[i] == safe_cfg[i] &&
				 (rep->out[i] & out_mask[i]) == (safe_out[i] & out_mask[i]);
		rep->ok &= rep->exp_ok[i];
		err |= e;
	}
	rep->err = err ? -EIO : 0;
	return rep->err;
}

static void budget_cfg(struct tb_budget_cfg *c)
{
	static const uint32_t rule[TB_RAIL_COUNT] = TB_RAIL_RULE_MA;

	memset(c, 0, sizeof(*c));
	c->unconfigured_ma = tb_sig.vsys_unconf_ma;
	c->vsys_max_ma = tb_sig.vsys_max_ma;
	c->slot_ldo_ma = tb_sig.ldo_ma;
	c->base_ma = tb_sig.base_ma;
	c->src_ma[TB_SRC_PENDING] = TB_TYPEC_BUDGET_DEFAULT_MA;
	c->src_ma[TB_SRC_DEFAULT] = TB_TYPEC_BUDGET_DEFAULT_MA;
	c->src_ma[TB_SRC_1A5] = TB_TYPEC_BUDGET_1A5_MA;
	c->src_ma[TB_SRC_3A0] = TB_TYPEC_BUDGET_3A0_MA;
	c->src_ma[TB_SRC_ACCESSORY] = TB_TYPEC_BUDGET_ACCESSORY_MA;
	c->src_ma[TB_SRC_NOT_ATTACHED] = TB_TYPEC_BUDGET_NOT_ATTACHED_MA;
	c->src_ma[TB_SRC_UNREADABLE] = TB_TYPEC_BUDGET_UNREADABLE_MA;
	memcpy(c->rule_ma, rule, sizeof(rule));
}

int tb_board_init(void)
{
	struct tb_budget_cfg c;
	uint16_t in;
	int err;

	for (int s = 0; s < TB_SLOTS; s++) {
		tb.desc_err[s] = 1;
	}
	budget_cfg(&c);
	tb_budget_init(&tb.budget, &c);
	tb.boot_ms = k_uptime_get();
	for (int i = 0; i < TB_EXP_COUNT; i++) {
		if (!device_is_ready(tb_sig.exp[i])) {
			LOG_ERR("U_EXP%d not ready", i + 1);
		}
	}
	err = tb_restore(&tb.restore);
	if (tb_exp2_inputs(&in) == 0) {
		for (int s = 1; s <= TB_SLOTS; s++) {
			WRITE_BIT(tb.present, s - 1, tb_pin_active(in, &tb_slots[s - 1].present));
		}
	}
	return err;
}

/* The alternate channels of a slot (lane, adc, channel), from the devicetree. */
int tb_slot_alt(int slot, int i, uint8_t *lane, uint8_t *adc, uint8_t *ch)
{
	if (slot < 1 || slot > TB_SLOTS || i < 0 || 3 * i + 2 >= alt_len[slot - 1]) {
		return -ENOENT;
	}
	*lane = alt_tab[slot - 1][3 * i];
	*adc = alt_tab[slot - 1][3 * i + 1];
	*ch = alt_tab[slot - 1][3 * i + 2];
	return 0;
}
