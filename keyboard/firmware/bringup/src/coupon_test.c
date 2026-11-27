/*
 * The test-coupon self-test (SPEC §10 step 7; the coupon: keyboard/hardware/design/sheets/test_coupon.py).
 *
 * Steps, each under tb_lock, each printed after the lock is released ("@tb step ..."):
 *   power     the slot on with its descriptor (a test coupon), +5V off for the loopback
 *   idle      the +3V3 rail's idle current and voltage
 *   lanes     AN0..AN3 against the descriptor's ratios (0.2 .. 0.8 of +3V3), and every converter agreeing
 *   loopback  the '165 on SPI2 (mode 3): G0, G2, G3 (never on S5), G4, G5, SYNC read back, MOSI echoed eight
 *             clocks late, INJ low (JP_INJ open), IRQ_N low exactly while G5 is high. G1 is not driven here: it is
 *             the +3V3 current-limit load, tested on its own
 *   load3     (loads) G0's 30 ohm on +3V3: the current step against V / R, and the slot's series resistance from
 *             the lane ratios at the two currents (tb_series_mohm)
 *   load5     (loads) +5V on, G2's 30 ohm: the current step
 *   climit3   (climit) G1's 5 ohm on +3V3: the TPS2553 limits inside its trip window and SLOT_FAULT_N asserts and
 *             clears; every other 3.3 V slot rail must be off (the slot LDO's 300 mA, SPEC §3.2)
 *   climit5   (climit, S1-S4) G3's 3.33 ohm on +5V: the same on the 5 V switch; the VSYS budget must allow 644 mA
 *
 * The current-limit steps drive the switch into its limit on purpose: their monitor's alert is disarmed, the
 * service's attribution is suspended for those rails (tb.test_rails), and the lock is held until SLOT_FAULT_N has
 * cleared again.
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/spi.h>
#include <zephyr/kernel.h>

#include "board.h"
#include "coupon_test.h"
#include "events.h"
#include "lanes.h"
#include "monitors.h"
#include "out.h"
#include "slot.h"
#include "tb/ina226.h"
#include "tb/selftest.h"

#define TOL_LOAD_PCT   5   /* 1 % resistors, the MOSFET, the series drop, the 2512s' 400 ppm/K (estimate) */
#define TOL_CLIMIT_PCT 3   /* the shunt and the INA226 around SPEC §3.1's trip window (estimate) */
#define AGREE_PPM      3000
#define SPI_HZ         1000000

struct step {
	const char *name;
	const char *result; /* "pass", "fail", "skip" */
	char kv[160];
};

static const struct device *const spi = DEVICE_DT_GET(DT_NODELABEL(spi2));
static const struct spi_config spi_cfg = {
	.frequency = SPI_HZ,
	.operation = SPI_WORD_SET(8) | SPI_TRANSFER_MSB | SPI_OP_MODE_CONTROLLER | SPI_MODE_CPOL | SPI_MODE_CPHA,
};

static void kv(struct step *s, const char *fmt, ...)
{
	size_t n = strlen(s->kv);
	va_list ap;

	if (n >= sizeof(s->kv) - 1) {
		return;
	}
	va_start(ap, fmt);
	vsnprintf(&s->kv[n], sizeof(s->kv) - n, fmt, ap);
	va_end(ap);
}

static void print_step(const struct shell *sh, int slot, const struct step *s)
{
	tbo(sh, "step slot=%d name=%s result=%s%s%s", slot, s->name, s->result, s->kv[0] ? " " : "", s->kv);
}

static void g_set(const struct tb_slot_hw *h, uint8_t g)
{
	for (int k = 0; k < 6; k++) {
		if (k == 3 && h->n == 5) {
			continue; /* G3 is never driven on S5: its load would draw 1.5 A unlimited (the coupon's silk) */
		}
		(void)gpio_pin_set_dt(&h->g[k], (g >> k) & 1);
	}
	tb_sim_sync();
}

static int read_avg(const struct tb_mon *m, int n, int32_t *ua, int32_t *mv)
{
	struct tb_mon_reading r;
	int64_t sa = 0, sv = 0;

	for (int i = 0; i < n; i++) {
		int err = tb_mon_read(m, false, &r);

		if (err != 0) {
			return err;
		}
		sa += r.current_ua;
		sv += r.bus_mv;
		k_msleep(3); /* a fresh result every 2.2 ms with TB_MON_CONFIG_FAST */
	}
	*ua = (int32_t)(sa / n);
	*mv = (int32_t)(sv / n);
	return 0;
}

static int lanes_ppm(int slot, uint32_t ppm[4])
{
	for (int k = 0; k < 4; k++) {
		int64_t acc = 0;
		unsigned bits = 0;

		for (int i = 0; i < 4; i++) {
			int32_t code;
			uint8_t adc, ch;
			int err = tb_lane_read(slot, k, &code, &bits, &adc, &ch);

			if (err != 0) {
				return err;
			}
			acc += code;
		}
		ppm[k] = tb_lane_ratio_ppm((uint32_t)(acc / 4), bits);
	}
	return 0;
}

static int loopback_once(const struct tb_slot_hw *h, uint8_t g, bool sync, uint8_t tx, uint16_t *rx, bool *irq)
{
	uint8_t txb[2] = {tx, 0x00}, rxb[2] = {0, 0};
	const struct spi_buf tb_ = {.buf = txb, .len = 2}, rb = {.buf = rxb, .len = 2};
	const struct spi_buf_set ts = {.buffers = &tb_, .count = 1}, rs = {.buffers = &rb, .count = 1};
	int err;

	g_set(h, g);
	(void)gpio_pin_set_dt(&tb_sig.slot_sync, sync);
	tb_sim_sync();
	k_busy_wait(50);
	*irq = gpio_pin_get_dt(&h->irq) == 1;
	/* CS1_N low then high: SH/LD loads G0..G5, INJ, SYNC; then CS0_N low: clock enable and MISO driver */
	(void)gpio_pin_set_dt(&h->cs[1], 1);
	k_busy_wait(2);
	(void)gpio_pin_set_dt(&h->cs[1], 0);
	k_busy_wait(2);
	(void)gpio_pin_set_dt(&h->cs[0], 1);
	k_busy_wait(2);
	err = spi_transceive(spi, &spi_cfg, &ts, &rs);
	(void)gpio_pin_set_dt(&h->cs[0], 0);
	g_set(h, 0);
	(void)gpio_pin_set_dt(&tb_sig.slot_sync, 0);
	*rx = (uint16_t)(((uint16_t)rxb[0] << 8) | rxb[1]);
	return err;
}

static void step_lanes(int slot, struct step *s)
{
	const struct tb_desc *d = &tb.desc[slot - 1];
	uint32_t ppm[4];
	bool ok = true;

	s->name = "lanes";
	if (lanes_ppm(slot, ppm) != 0) {
		s->result = "fail";
		kv(s, "err=adc");
		return;
	}
	for (int k = 0; k < 4; k++) {
		uint32_t exp = tb_q16_to_ppm(d->lane[k].expect_q16);
		uint32_t tol = tb_q16_to_ppm(d->lane[k].tol_q16);
		int32_t err = (int32_t)ppm[k] - (int32_t)exp;
		bool l_ok = d->lane[k].present && exp != 0 && (err < 0 ? -err : err) <= (int32_t)tol;

		ok &= l_ok;
		kv(s, "an%d_ppm=%u an%d_err_ppm=%d ", k, ppm[k], k, err);
	}
	/* every other converter that reaches a lane agrees with its primary */
	for (int i = 0;; i++) {
		uint8_t lane, adc, ch;
		int32_t code;
		unsigned bits;
		int32_t diff;

		if (tb_slot_alt(slot, i, &lane, &adc, &ch) != 0) {
			break;
		}
		if (tb_adc_read(adc, ch, &code, &bits) != 0) {
			ok = false;
			kv(s, "alt_err=adc%u_%u ", adc, ch);
			continue;
		}
		diff = (int32_t)tb_lane_ratio_ppm((uint32_t)code, bits) - (int32_t)ppm[lane];
		if ((diff < 0 ? -diff : diff) > AGREE_PPM) {
			ok = false;
			kv(s, "disagree=an%u_adc%u diff_ppm=%d ", lane, adc, diff);
		}
	}
	s->result = ok ? "pass" : "fail";
}

static void step_loopback(int slot, struct step *s)
{
	static const struct {
		uint8_t g;
		bool sync;
		uint8_t tx;
	} pat[] = {
		{0x00, false, 0xA5}, {0x01, false, 0x5A}, {0x04, false, 0x3C}, {0x08, false, 0xC3},
		{0x10, false, 0x0F}, {0x20, false, 0xF0}, {0x00, true, 0x99}, {0x15, true, 0x66},
	};
	const struct tb_slot_hw *h = tb_slot_hw(slot);
	int fails = 0, runs = 0;

	s->name = "loopback";
	if (!device_is_ready(spi)) {
		s->result = "fail";
		kv(s, "err=spi");
		return;
	}
	for (size_t i = 0; i < ARRAY_SIZE(pat); i++) {
		uint8_t g = pat[i].g;
		uint16_t rx, want;
		bool irq;

		if (slot == 5 && (g & 0x08)) {
			continue;
		}
		if (loopback_once(h, g, pat[i].sync, pat[i].tx, &rx, &irq) != 0) {
			fails++;
			kv(s, "spi_err=%u ", (unsigned)i);
			continue;
		}
		runs++;
		want = tb_loopback_expect(g, false, pat[i].sync, pat[i].tx);
		if (rx != want || irq != ((g & 0x20) != 0)) {
			fails++;
			kv(s, "p%u_rx=0x%04x p%u_want=0x%04x p%u_irq=%d ", (unsigned)i, rx, (unsigned)i, want,
			   (unsigned)i, irq);
		}
	}
	kv(s, "patterns=%d failed=%d", runs, fails);
	s->result = fails == 0 && runs > 0 ? "pass" : "fail";
}

static void step_load(int slot, int rail, uint8_t gline, uint32_t r_mohm, struct step *s, bool lanes)
{
	const struct tb_mon *m = tb_mon_for_rail(rail);
	uint32_t p0[4] = {0}, p1[4] = {0};
	int32_t i0, i1, v0, v1, expect = 0, vref = TB_ADC_VREF_MV;
	const struct tb_slot_hw *h = tb_slot_hw(slot);
	int64_t rs_sum = 0;
	int rs_n = 0;
	bool ok;

	if (m == NULL || tb_mon_reg_write(m, TB_INA226_REG_CONFIG, TB_MON_CONFIG_FAST) != 0) {
		s->result = "fail";
		kv(s, "err=monitor");
		return;
	}
	k_msleep(5);
	(void)tb_vdda_mv(&vref);
	if (read_avg(m, 4, &i0, &v0) != 0 || (lanes && lanes_ppm(slot, p0) != 0)) {
		s->result = "fail";
		kv(s, "err=read");
		goto out;
	}
	(void)gpio_pin_set_dt(&h->g[gline], 1);
	tb_sim_sync();
	k_msleep(10);
	ok = read_avg(m, 4, &i1, &v1) == 0 && (!lanes || lanes_ppm(slot, p1) == 0);
	(void)gpio_pin_set_dt(&h->g[gline], 0);
	tb_sim_sync();
	if (!ok) {
		s->result = "fail";
		kv(s, "err=read");
		goto out;
	}
	ok = tb_load_step_ok(i0, i1, v1, r_mohm, TOL_LOAD_PCT, &expect);
	kv(s, "i0_ua=%d i1_ua=%d v1_mv=%d expect_ua=%d ", i0, i1, v1, expect);
	if (lanes) {
		/* The drop is the same fraction of every tap, but a tap's ADC quantization is not: weight each lane
		 * by its ratio (k + 1) / 5, i.e. by its signal. At 14 bits and a 1 % drop, AN0 alone resolves Rs to
		 * about 3 %, AN3 to about 1 % (arithmetic). */
		for (int k = 0; k < 4; k++) {
			int32_t rs;

			if (tb_series_mohm(p0[k], p1[k], i0, i1, (uint32_t)vref, &rs) == 0) {
				rs_sum += (int64_t)rs * (k + 1);
				rs_n += k + 1;
			}
		}
		if (rs_n > 0) {
			kv(s, "rs_mohm=%d vref_mv=%d", (int)(rs_sum / rs_n), vref);
		} else {
			kv(s, "rs_mohm=none");
		}
	}
	s->result = ok ? "pass" : "fail";
out:
	(void)tb_mon_reg_write(m, TB_INA226_REG_CONFIG, TB_MON_CONFIG_DEFAULT);
}

static void step_climit(int slot, int rail, uint8_t gline, const uint32_t trip[3], uint32_t declared_ma,
			struct step *s)
{
	const struct tb_mon *m = tb_mon_for_rail(rail);
	const struct tb_slot_hw *h = tb_slot_hw(slot);
	struct tb_mon_reading r;
	uint16_t in = 0, me = 0;
	bool fault_seen, fault_cleared = false, ok;
	int64_t until;

	if (m == NULL) {
		s->result = "fail";
		kv(s, "err=monitor");
		return;
	}
	(void)tb_mon_set_alert(m, 0);
	(void)tb_mon_reg_write(m, TB_INA226_REG_CONFIG, TB_MON_CONFIG_FAST);
	tb.test_rails = TB_RAIL_BIT(rail);
	tb.test_until_ms = k_uptime_get() + 200;
	(void)gpio_pin_set_dt(&h->g[gline], 1);
	tb_sim_sync();
	k_msleep(15); /* past the FAULT deglitch, 10 ms max (SLVS841E) */
	ok = tb_mon_read(m, false, &r) == 0;
	fault_seen = tb_exp2_inputs(&in) == 0 && tb_pin_active(in, &tb_sig.slot_fault);
	(void)gpio_pin_set_dt(&h->g[gline], 0);
	tb_sim_sync();
	until = k_uptime_get() + 40;
	while (k_uptime_get() < until) {
		k_msleep(2);
		if (tb_exp2_inputs(&in) == 0 && !tb_pin_active(in, &tb_sig.slot_fault)) {
			fault_cleared = true;
			break;
		}
	}
	(void)tb_mon_reg_read(m, TB_INA226_REG_MASK_ENABLE, &me); /* clears the latch */
	(void)tb_mon_reg_write(m, TB_INA226_REG_CONFIG, TB_MON_CONFIG_DEFAULT);
	(void)tb_mon_set_alert(m, tb_rail_alert_ua(rail, declared_ma));
	tb.test_rails = 0;
	ok = ok && tb_climit_ok(r.current_ua, trip, TOL_CLIMIT_PCT) && fault_seen && fault_cleared;
	kv(s, "i_ua=%d bus_mv=%d trip_ma=%u/%u/%u fault=%d cleared=%d", r.current_ua, r.bus_mv, trip[0], trip[1],
	   trip[2], fault_seen, fault_cleared);
	s->result = ok ? "pass" : "fail";
}

int tb_selftest_run(const struct shell *sh, int slot, const struct tb_st_opts *o)
{
	const struct tb_slot_hw *h = tb_slot_hw(slot);
	struct tb_slot_on_opts so = {.use_desc = true};
	struct tb_slot_on_result sr;
	int passed = 0, failed = 0, skipped = 0;
	struct step s;
	enum tb_refusal why;

#define BEGIN(n)                                                                                   \
	do {                                                                                       \
		memset(&s, 0, sizeof(s));                                                          \
		s.name = (n);                                                                      \
		k_mutex_lock(&tb_lock, K_FOREVER);                                                 \
	} while (0)
#define END()                                                                                      \
	do {                                                                                       \
		k_mutex_unlock(&tb_lock);                                                          \
		print_step(sh, slot, &s);                                                          \
		passed += s.result[0] == 'p';                                                      \
		failed += s.result[0] == 'f';                                                      \
		skipped += s.result[0] == 's';                                                     \
	} while (0)

	if (h == NULL) {
		return -EINVAL;
	}

	BEGIN("power");
	if (!(tb.budget.on & TB_RAIL_BIT(h->rail3)) || tb.desc_err[slot - 1] != TB_DESC_OK) {
		(void)tb_slot_on(slot, &so, &sr);
	}
	if (!(tb.budget.on & TB_RAIL_BIT(h->rail3)) || tb.desc_err[slot - 1] != TB_DESC_OK) {
		s.result = "fail";
		kv(&s, "err=%s", tb.desc_err[slot - 1] == TB_DESC_ERR_BLANK ? "blank_descriptor" : "slot_on");
	} else if (tb.desc[slot - 1].type != TB_COUPON_TEST && !o->force) {
		s.result = "fail";
		kv(&s, "err=not_a_test_coupon type=%s", tb_coupon_type_str(tb.desc[slot - 1].type));
	} else {
		s.result = "pass";
		/* The loopback drives G2/G3, the 5 V loads' gates: +5V off until the load5 step. */
		if (tb.budget.on & TB_RAIL_BIT(h->rail5)) {
			(void)tb_rails_off(TB_RAIL_BIT(h->rail5), "selftest");
		}
		if (!(tb.bus_closed & BIT(slot - 1))) {
			(void)tb_slot_bus(slot, true);
		}
		kv(&s, "serial=%u", tb.desc[slot - 1].serial);
	}
	END();
	if (failed) {
		goto done;
	}

	BEGIN("idle");
	{
		struct tb_mon_reading r;
		const struct tb_mon *m = tb_mon_for_rail(h->rail3);

		if (m == NULL || tb_mon_read(m, false, &r) != 0) {
			s.result = "fail";
			kv(&s, "err=monitor");
		} else {
			/* about 1.4 mA idle and 1.5 mA LED (the coupon's estimate): well under 10 mA */
			s.result = r.bus_mv >= 3000 && r.current_ua < 10000 ? "pass" : "fail";
			kv(&s, "i_ua=%d bus_mv=%d", r.current_ua, r.bus_mv);
		}
	}
	END();

	BEGIN("lanes");
	step_lanes(slot, &s);
	END();

	BEGIN("loopback");
	(void)tb_slot_lines(slot, true);
	step_loopback(slot, &s);
	END();

	BEGIN("load3");
	if (!o->loads) {
		s.result = "skip";
	} else {
		step_load(slot, h->rail3, 0, tb.desc[slot - 1].load[0].r_mohm ? tb.desc[slot - 1].load[0].r_mohm : 30000,
			  &s, true);
	}
	END();

	BEGIN("load5");
	if (!o->loads || tb.desc[slot - 1].i5v_ma == 0) {
		s.result = "skip";
	} else {
		int err5 = 0;

		if (!(tb.budget.on & TB_RAIL_BIT(h->rail5))) {
			/* SPEC §3.5: the bus switch open while a rail comes up, closed again once it is up */
			(void)tb_slot_bus(slot, false);
			err5 = tb_rail_on(h->rail5, tb.desc[slot - 1].i5v_ma, &why);
			if (err5 == 0) {
				k_msleep(CONFIG_BRINGUP_SETTLE_MS);
			}
			(void)tb_slot_bus(slot, true);
		}
		if (err5 != 0) {
			s.result = "fail";
			kv(&s, "err=%s", why != TB_BUDGET_OK ? tb_refusal_str(why) : "rail_5v");
		} else {
			step_load(slot, h->rail5, 2,
				  tb.desc[slot - 1].load[2].r_mohm ? tb.desc[slot - 1].load[2].r_mohm : 30000, &s, false);
		}
	}
	END();

	BEGIN("climit3");
	if (!o->climit) {
		s.result = "skip";
	} else {
		why = tb_budget_check_peak(&tb.budget, h->rail3, h->trip3_ma[2], true);
		if (why != TB_BUDGET_OK) {
			s.result = "fail";
			kv(&s, "err=%s", tb_refusal_str(why));
		} else {
			step_climit(slot, h->rail3, 1, h->trip3_ma, tb.budget.declared_ma[h->rail3], &s);
		}
	}
	END();

	BEGIN("climit5");
	if (!o->climit || slot == 5) {
		s.result = "skip";
		if (o->climit) {
			kv(&s, "reason=never_on_s5");
		}
	} else if (!(tb.budget.on & TB_RAIL_BIT(h->rail5))) {
		s.result = "skip";
		kv(&s, "reason=5v_off");
	} else {
		why = tb_budget_check_peak(&tb.budget, h->rail5, h->trip5_ma[2], false);
		if (why != TB_BUDGET_OK) {
			s.result = "fail";
			kv(&s, "err=%s", tb_refusal_str(why));
		} else {
			step_climit(slot, h->rail5, 3, h->trip5_ma, tb.budget.declared_ma[h->rail5], &s);
		}
	}
	END();

done:
	tbo(sh, "selftest slot=%d result=%s passed=%d failed=%d skipped=%d", slot, failed ? "fail" : "pass", passed,
	    failed, skipped);
	tb_ev("kind=selftest slot=%d result=%s failed=%d", slot, failed ? "fail" : "pass", failed);
	return failed ? -EIO : 0;
#undef BEGIN
#undef END
}
