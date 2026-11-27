/*
 * The simulated board's model (see sim.h). Numbers: SPEC §3.1 (series resistance, trip windows), the test
 * coupon (keyboard/hardware/design/sheets/test_coupon.py: loads, ladder, LED), SLVS841E (FAULT deglitch 7.5 ms
 * typical). A model, not a measurement.
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include <stdio.h>
#include <string.h>

#include <zephyr/drivers/adc.h>
#include <zephyr/drivers/adc/adc_emul.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/gpio/gpio_emul.h>
#include <zephyr/init.h>
#include <zephyr/kernel.h>

#include "board.h"
#include "sim.h"
#include "tb/desc.h"

struct sim_world sim = {
	/* the TCA9535's power-on state (SCPS201D): inputs, output register 0xFFFF */
	.exp = {{.out = 0xFFFF, .cfg = 0xFFFF, .last_read = 0xFFFF},
		{.out = 0xFFFF, .cfg = 0xFFFF, .last_read = 0xFFFF},
		{.out = 0xFFFF, .cfg = 0xFFFF, .last_read = 0xFFFF}},
	.cc_attach = 2, /* Attached.SNK */
	.cc_mode = 3,   /* a 3.0 A source */
};
static K_MUTEX_DEFINE(sim_lock);

#define SERIES_3V3_MOHM 325  /* 0.24 ohm shunt + 85 mOhm TPS2553 (SPEC §3.1), the jumper ignored */
#define SERIES_5V_MOHM  185  /* 0.1 ohm shunt + 85 mOhm */
#define SERIES_S5_MOHM  60   /* 20 mOhm shunt + 28 mOhm TPS259474L + contacts, about */
#define V3_MV 3300
#define V5_MV 5000
#define DEGLITCH_MS 8        /* SLVS841E: 7.5 ms typical */
#define BASE_UA 45000        /* SPEC §3.2's base load estimate */

static const char *const exp_names[TB_EXP_COUNT][16] = TB_EXP_NET_NAMES;
static const uint16_t safe_out[TB_EXP_COUNT] = TB_EXP_SAFE_OUTPUT;
static const uint32_t trip_ma[TB_RAIL_COUNT][3] = TB_RAIL_TRIP_MA;
static bool fault_asserted[TB_RAIL_COUNT];

/* An expander pin's physical level: its output if configured as one, else what its resistor holds it at. */
static int exp_level(int e, int pin)
{
	const struct sim_exp *x = &sim.exp[e];

	if (!((x->cfg >> pin) & 1u)) {
		return (x->out >> pin) & 1u;
	}
	return (safe_out[e] >> pin) & 1u;
}

static int exp_level_spec(const struct gpio_dt_spec *s)
{
	for (int e = 0; e < TB_EXP_COUNT; e++) {
		if (s->port == tb_sig.exp[e]) {
			return exp_level(e, s->pin);
		}
	}
	return -1;
}

int sim_mcu_out(const void *spec)
{
	const struct gpio_dt_spec *s = spec;
	gpio_flags_t f = 0;

	if (s->port == NULL) {
		return -1;
	}
	if (exp_level_spec(s) >= 0) {
		return exp_level_spec(s);
	}
	if (gpio_emul_flags_get(s->port, s->pin, &f) != 0 || !(f & GPIO_OUTPUT)) {
		return -1;
	}
	return gpio_emul_output_get(s->port, s->pin);
}

int sim_gline(int slot, int g)
{
	int v = sim_mcu_out(&tb_slots[slot - 1].g[g]);

	return v > 0 ? 1 : 0; /* undriven: the coupon's 100 k pull-downs */
}

int sim_bus_slot(void)
{
	for (int s = 1; s <= TB_SLOTS; s++) {
		if (exp_level_spec(&tb_slots[s - 1].busen) == 0) {
			return s;
		}
	}
	return 0;
}

bool sim_test_coupon_powered(int slot)
{
	return sim.coupon[slot - 1] == SIM_TEST && sim.on[tb_rail_3v3(slot)];
}

uint16_t sim_exp_inputs(int e)
{
	uint16_t v = 0;

	for (int p = 0; p < 16; p++) {
		const char *n = exp_names[e][p];
		int level;

		if (!((sim.exp[e].cfg >> p) & 1u)) {
			level = (sim.exp[e].out >> p) & 1u; /* an output reads back its own level */
		} else if (n == NULL) {
			level = 1;
		} else if (strstr(n, "_PRESENT_N") != NULL && n[0] == 'S') {
			level = sim.coupon[n[1] - '1'] == SIM_NONE;
		} else if (strcmp(n, "KVM_PRESENT_N") == 0) {
			level = 1;
		} else if (strcmp(n, "SLOT_FAULT_N") == 0) {
			level = sim.fault_n;
		} else if (strcmp(n, "PM_ALERT_N") == 0) {
			level = sim.alert_n;
		} else if (strcmp(n, "VSYS_PG") == 0) {
			level = !sim.vsys_pg_low;
		} else if (strcmp(n, "S5_PG") == 0) {
			level = sim.on[TB_RAIL_5V_S5] && !sim.s5_latched;
		} else if (strcmp(n, "USBC_INT_N") == 0) {
			level = !sim.cc_int;
		} else {
			level = exp_level(e, p);
		}
		v |= (uint16_t)(level << p);
	}
	return v ^ sim.exp[e].pol;
}

void sim_monitor(uint8_t addr, int32_t *ua, int32_t *mv)
{
	static const struct {
		uint8_t addr;
		const char *rail;
		uint32_t shunt_uohm, lsb_ua, cal;
		int rail_id;
		uint32_t rule_ma, tmin, ttyp, tmax;
	} map[] = TB_INA226_TABLE;

	*ua = 0;
	*mv = 0;
	if (addr == TB_INA226_ADDR_VSYS) {
		*ua = sim.vsys_ua;
		*mv = sim.vsys_mv;
		return;
	}
	if (addr == TB_INA226_ADDR_P3V3_MCU) {
		*ua = 40000;
		*mv = 3280;
		return;
	}
	if (addr == TB_INA226_ADDR_P3V3_USB) {
		*ua = 6000;
		*mv = 3294;
		return;
	}
	for (size_t i = 0; i < ARRAY_SIZE(map); i++) {
		if (map[i].addr == addr && map[i].rail_id >= 0) {
			*ua = sim.ua[map[i].rail_id];
			*mv = sim.mv[map[i].rail_id];
		}
	}
}

/* Drive an MCU input pin of the model, only while the firmware has it configured as an input. */
static void set_input(const struct gpio_dt_spec *s, int level)
{
	gpio_flags_t f = 0;

	if (gpio_emul_flags_get(s->port, s->pin, &f) == 0 && (f & GPIO_INPUT)) {
		(void)gpio_emul_input_set_dt(s, level);
	}
}

static void rail(int r, bool en, int64_t demand_ua, int32_t v_mv, int32_t series_mohm, int64_t now)
{
	bool was = sim.limiting[r];
	int64_t lim = (int64_t)trip_ma[r][1] * 1000; /* the typical trip */

	sim.on[r] = en;
	if (!en) {
		sim.ua[r] = 0;
		sim.mv[r] = 0;
		sim.limiting[r] = false;
	} else if (demand_ua > lim) {
		/* constant-current limiting into a resistive load: the voltage collapses with the overload */
		sim.limiting[r] = true;
		sim.ua[r] = (int32_t)lim;
		sim.mv[r] = (int32_t)((int64_t)v_mv * lim / demand_ua);
	} else {
		sim.limiting[r] = false;
		sim.ua[r] = (int32_t)demand_ua;
		sim.mv[r] = v_mv - (int32_t)(demand_ua * series_mohm / 1000000);
	}
	if (sim.limiting[r] && !was) {
		sim.limit_since_ms[r] = now;
	}
	if (!sim.limiting[r] && was) {
		sim.limit_end_ms[r] = now;
	}
	if (sim.limiting[r] && now - sim.limit_since_ms[r] >= DEGLITCH_MS) {
		fault_asserted[r] = true;
	} else if (!sim.limiting[r] && fault_asserted[r] && now - sim.limit_end_ms[r] >= DEGLITCH_MS) {
		fault_asserted[r] = false;
	}
}

uint32_t sim_rule_violations;
char sim_first_violation[64];
static bool was_on[TB_RAIL_COUNT];

static void violation(const char *fmt, int a, const char *b)
{
	if (sim_rule_violations++ == 0) {
		snprintf(sim_first_violation, sizeof(sim_first_violation), fmt, a, b);
	}
}

static bool host_allows_power(void)
{
	/* bench mode is the operator's declaration of a bench supply (SPEC §10 step 5), taken as given here */
	return (sim.usb_configured && !sim.usb_suspended) || tb_budget_bench_active(&tb.budget);
}

/* SPEC §3.5 on the physical state (see sim.h). */
static void check_rules(int64_t now)
{
	static const char *const gname[6] = {"G0", "G1", "G2", "G3", "G4", "G5"};

	for (int s = 1; s <= TB_SLOTS; s++) {
		const struct tb_slot_hw *h = &tb_slots[s - 1];
		bool en3 = exp_level_spec(&h->en3) == 1;
		bool en5 = exp_level_spec(&h->en5) == 1;
		bool bus = exp_level_spec(&h->busen) == 0;

		if (en5 && !en3) {
			violation("S%d:5v_on_3v3_off%s", s, "");
		}
		/* "close the slot's bus switch only after its rails are up, open it before they go down" */
		if (bus && (en3 != was_on[h->rail3] || en5 != was_on[h->rail5])) {
			violation("S%d:rail_switched_with_bus_closed%s", s, "");
		}
		/* "never power a slot ... while its PRESENT_N reads high" */
		if (sim.coupon[s - 1] == SIM_NONE && ((en3 && !was_on[h->rail3]) || (en5 && !was_on[h->rail5]))) {
			violation("S%d:rail_on_no_coupon%s", s, "");
		}
		if (en3) {
			continue;
		}
		if (bus) {
			violation("S%d:bus_closed_3v3_off%s", s, "");
		}
		if (sim.mux_ctrl & BIT(s - 1)) {
			violation("S%d:mux_on_3v3_off%s", s, "");
		}
		for (int i = 0; i < 2; i++) {
			if (sim_mcu_out(&h->cs[i]) == 1) {
				violation("S%d:%s_high_3v3_off", s, i ? "CS1_N" : "CS0_N");
			}
		}
		for (int g = 0; g < 6; g++) {
			if (sim_mcu_out(&h->g[g]) == 1) {
				violation("S%d:%s_high_3v3_off", s, gname[g]);
			}
		}
		if (sim_mcu_out(&h->irq) == 1) {
			violation("S%d:%s_high_3v3_off", s, "IRQ_N");
		}
	}
	for (int r = 0; r < TB_RAIL_COUNT; r++) {
		const struct gpio_dt_spec *en = r == TB_RAIL_5V_KVM ? &tb_sig.en_5v_kvm
					       : tb_rail_is_3v3(r) ? &tb_slots[tb_rail_slot(r) - 1].en3
								   : &tb_slots[tb_rail_slot(r) - 1].en5;
		bool on = exp_level_spec(en) == 1;

		if (on && !was_on[r] && !host_allows_power()) {
			violation("rail%d:%s_on_unconfigured", r, tb_rail_name(r));
		} else if (on && !host_allows_power() && now - sim.usb_change_ms > SIM_USB_GRACE_MS) {
			violation("rail%d:%s_still_on_after_usb", r, tb_rail_name(r));
		}
		was_on[r] = on;
	}
}


void sim_update(void)
{
	int64_t now = k_uptime_get();
	int64_t vsys = BASE_UA;
	bool fault = false;

	k_mutex_lock(&sim_lock, K_FOREVER);
	sim.updates++;
	check_rules(now);
	for (int s = 1; s <= TB_SLOTS; s++) {
		const struct tb_slot_hw *h = &tb_slots[s - 1];
		int r3 = h->rail3, r5 = h->rail5;
		bool en3 = exp_level_spec(&h->en3) == 1;
		bool en5 = exp_level_spec(&h->en5) == 1;
		int64_t d3 = sim.extra_ua[r3], d5 = sim.extra_ua[r5];

		if (en3 && sim.coupon[s - 1] == SIM_TEST) {
			d3 += 1400 + (sim_gline(s, 4) ? 1500 : 0);           /* ladder + logic, LED */
			d3 += sim_gline(s, 0) ? 3300000 / 30 : 0;             /* G0: 30 ohm */
			d3 += sim_gline(s, 1) ? 3300000 / 5 : 0;              /* G1: 5 ohm */
		} else if (en3 && sim.coupon[s - 1] != SIM_NONE) {
			d3 += sim.coupon[s - 1] == SIM_HALL ? 30000 : 1400;
		}
		if (en5 && en3 && sim.coupon[s - 1] == SIM_TEST) {
			d5 += sim_gline(s, 2) ? 5000000 / 30 : 0;             /* G2: 30 ohm */
			d5 += (s != 5 && sim_gline(s, 3)) ? 5000000 * 3 / 10 : 0; /* G3: 3.33 ohm */
		}
		rail(r3, en3, d3, V3_MV, SERIES_3V3_MOHM, now);
		sim.uv3[s - 1] = sim.on[r3] ? (sim.limiting[r3] ? sim.mv[r3] * 1000
						    : V3_MV * 1000 - (int32_t)(d3 * SERIES_3V3_MOHM / 1000))
					    : 0;
		if (s == 5) {
			/* S5's 5 V: a latching circuit breaker at 2.01 A minimum (SPEC §3.6) */
			if (!en5) {
				sim.s5_latched = false;
			} else if (d5 > (int64_t)trip_ma[r5][0] * 1000) {
				sim.s5_latched = true;
			}
			rail(r5, en5 && !sim.s5_latched, d5, V5_MV, SERIES_S5_MOHM, now);
			sim.on[r5] = en5;
		} else {
			rail(r5, en5, d5, V5_MV, SERIES_5V_MOHM, now);
		}
		vsys += sim.ua[r3] + sim.ua[r5];
	}
	rail(TB_RAIL_5V_KVM, exp_level_spec(&tb_sig.en_5v_kvm) == 1, sim.extra_ua[TB_RAIL_5V_KVM], V5_MV,
	     SERIES_5V_MOHM, now);
	vsys += sim.ua[TB_RAIL_5V_KVM];
	for (int r = 0; r < TB_RAIL_COUNT; r++) {
		fault |= (TB_RAIL_MASK_TPS2553 & TB_RAIL_BIT(r)) && fault_asserted[r];
	}
	sim.vsys_ua = (int32_t)vsys;
	sim.vsys_mv = V5_MV - (int32_t)(vsys * 48 / 1000000);
	sim.fault_n = !fault;
	sim.alert_n = !sim_ina_any_alert();

	/* the MCU's inputs: EXP_INT_N from U_EXP2 (a change since its last read), each slot's IRQ_N */
	{
		uint16_t in = sim_exp_inputs(TB_EXP_EXP2_INDEX);

		if (in != sim.exp[TB_EXP_EXP2_INDEX].last_read) {
			sim.exp[TB_EXP_EXP2_INDEX].int_pending = true;
		}
		set_input(&tb_sig.exp_int, sim.exp[TB_EXP_EXP2_INDEX].int_pending ? 0 : 1);
	}
	for (int s = 1; s <= TB_SLOTS; s++) {
		int level = 0;

		if (sim_test_coupon_powered(s)) {
			level = !sim_gline(s, 5); /* Q14 pulls IRQ_N low while G5 is high; INJ's jumper is open */
		} else if (sim.coupon[s - 1] != SIM_NONE && sim.on[tb_rail_3v3(s)]) {
			level = 1;
		}
		set_input(&tb_slots[s - 1].irq, level);
	}
	k_mutex_unlock(&sim_lock);
}

void tb_sim_sync(void)
{
	sim_update();
}

void sim_set_coupon(int slot, enum sim_coupon_kind kind)
{
	struct tb_desc d;

	sim.coupon[slot - 1] = kind;
	memset(sim.eeprom[slot - 1], 0xFF, sizeof(sim.eeprom[slot - 1]));
	if (kind == SIM_TEST) {
		tb_desc_test_coupon(&d, (uint32_t)slot);
		(void)tb_desc_encode(&d, sim.eeprom[slot - 1], sizeof(sim.eeprom[slot - 1]));
	} else if (kind == SIM_HALL) {
		tb_desc_init(&d);
		d.type = TB_COUPON_HALL;
		d.flags = TB_DESC_F_SENSORS;
		d.serial = 100u + (uint32_t)slot;
		d.i3v3_ma = 40;
		(void)tb_desc_encode(&d, sim.eeprom[slot - 1], sizeof(sim.eeprom[slot - 1]));
	}
	sim_update();
}

/* Lanes: the test coupon's ladder, 0.2 .. 0.8 of its +3V3; nothing else drives a lane in this model. The code
 * is computed exactly (not through whole millivolts), so the firmware sees only the ADC's own quantization. */
static int lane_raw(const struct device *dev, unsigned int chan, void *data, uint32_t *result)
{
	uintptr_t v = (uintptr_t)data;
	int slot = (int)((v >> 8) & 0xFF), lane = (int)(v & 0xFF), bits = (int)(v >> 16);
	int64_t uv;

	ARG_UNUSED(dev);
	ARG_UNUSED(chan);
	sim_update();
	if (!sim_test_coupon_powered(slot)) {
		*result = 0;
		return 0;
	}
	uv = (int64_t)sim.uv3[slot - 1] * (lane + 1) / 5;
	*result = (uint32_t)((uv << bits) / ((int64_t)TB_ADC_VREF_MV * 1000));
	return 0;
}

static const struct device *adc_dev(uint8_t n)
{
	switch (n) {
	case 1:
		return DEVICE_DT_GET(DT_NODELABEL(adc1));
	case 2:
		return DEVICE_DT_GET(DT_NODELABEL(adc2));
	default:
		return DEVICE_DT_GET(DT_NODELABEL(adc4));
	}
}

static int sim_init(void)
{
	for (int s = 1; s <= TB_SLOTS; s++) {
		uint8_t lane, adc, ch;

		for (int k = 0; k < 4; k++) {
			const struct adc_dt_spec *sp = &tb_slots[s - 1].lane[k];

			(void)adc_emul_raw_value_func_set(sp->dev, sp->channel_id, lane_raw,
							  (void *)(uintptr_t)((sp->resolution << 16) | (s << 8) | k));
		}
		for (int i = 0; tb_slot_alt(s, i, &lane, &adc, &ch) == 0; i++) {
			(void)adc_emul_raw_value_func_set(adc_dev(adc), ch, lane_raw,
							  (void *)(uintptr_t)((TB_ADC_RES_BITS(adc) << 16) | (s << 8) | lane));
		}
	}
	sim_set_coupon(1, SIM_TEST);
	return 0;
}

/* After the ADC, GPIO and I2C emulators, before main(). */
SYS_INIT(sim_init, APPLICATION, 0);
