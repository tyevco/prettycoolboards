/*
 * The board service thread (SPEC §8.4): applies USB state changes to the budget, reads U_EXP2 on EXP_INT_N
 * and on a poll (the PCA95XX driver "cannot reliably detect short-pulse interrupts", its Kconfig help says, so
 * the poll is the backstop), reads U_CC when it interrupts, classifies faults and alerts (tb/trip.h) and switches
 * rails off. It never prints: it posts events (events.h).
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include <string.h>

#include <zephyr/drivers/gpio.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/atomic.h>
#include <zephyr/logging/log.h>

#include "board.h"
#include "events.h"
#include "monitors.h"
#include "service.h"
#include "tb/ina226.h"
#include "tb/trip.h"
#include "typec.h"

LOG_MODULE_REGISTER(tb_service, LOG_LEVEL_INF);

enum msg_type {
	MSG_USB = 1,
	MSG_KICK,
};

struct svc_msg {
	uint8_t type;
	uint8_t ev;
	uint32_t value;
};

K_MSGQ_DEFINE(svc_q, sizeof(struct svc_msg), 16, 4);

static uint32_t period_ms = CONFIG_BRINGUP_MON_PERIOD_MS;
static uint32_t vsys_alert_ma;
static uint16_t last_inputs;
static bool have_inputs;
static struct gpio_callback exp_cb;
/* last time a finding was posted, per kind and rail (rate limit of repeated reports) */
static int64_t last_post[TB_F_RAIL_LIVE_OFF + 1][TB_RAIL_COUNT + 1];

#define REPOST_MS 5000

void tb_service_usb(enum tb_usb_event ev, uint32_t value)
{
	struct svc_msg m = {.type = MSG_USB, .ev = (uint8_t)ev, .value = value};

	if (k_msgq_put(&svc_q, &m, K_NO_WAIT) != 0) {
		LOG_ERR("service queue full: USB event %d lost", ev);
	}
}

/* At most one kick waits in the queue: a chattering EXP_INT_N, or kicks piling up while a long self-test step
 * holds tb_lock, must never fill it and make a USB reset or suspend message fail to enqueue. */
static atomic_t kick_queued;

void tb_service_kick(void)
{
	struct svc_msg m = {.type = MSG_KICK};

	if (atomic_cas(&kick_queued, 0, 1) && k_msgq_put(&svc_q, &m, K_NO_WAIT) != 0) {
		atomic_clear(&kick_queued);
	}
}

uint32_t tb_service_period_ms(void)
{
	return period_ms;
}

void tb_service_set_period(uint32_t ms)
{
	period_ms = CLAMP(ms, 10u, 2000u);
	tb_service_kick();
}

static void exp_handler(const struct device *dev, struct gpio_callback *cb, uint32_t pins)
{
	ARG_UNUSED(dev);
	ARG_UNUSED(cb);
	ARG_UNUSED(pins);
	tb_service_kick();
}

static const struct gpio_dt_spec *exp2_inputs(int i)
{
	static const struct gpio_dt_spec *const list[] = {
		&tb_sig.slot_fault, &tb_sig.pm_alert, &tb_sig.vsys_pg, &tb_sig.s5_pg,
		&tb_sig.usbc_int, &tb_sig.kvm_present,
	};

	if (i < (int)ARRAY_SIZE(list)) {
		return list[i];
	}
	i -= ARRAY_SIZE(list);
	return i < TB_SLOTS ? &tb_slots[i].present : NULL;
}

static void setup_interrupts(void)
{
	uint32_t pins = 0;
	const struct gpio_dt_spec *s;

	for (int i = 0; (s = exp2_inputs(i)) != NULL; i++) {
		if (gpio_pin_configure_dt(s, GPIO_INPUT) == 0 &&
		    gpio_pin_interrupt_configure_dt(s, GPIO_INT_EDGE_BOTH) == 0) {
			pins |= BIT(s->pin);
		}
	}
	gpio_init_callback(&exp_cb, exp_handler, pins);
	if (gpio_add_callback(tb_sig.exp[TB_EXP_EXP2_INDEX], &exp_cb) != 0) {
		LOG_WRN("no U_EXP2 interrupt callback: polling only");
	}
}

static void post_finding(const struct tb_finding *f)
{
	int k = f->kind <= TB_F_RAIL_LIVE_OFF ? f->kind : 0;
	int r = f->rail >= 0 ? f->rail : TB_RAIL_COUNT;
	int64_t now = k_uptime_get();

	if (last_post[k][r] != 0 && now - last_post[k][r] < REPOST_MS) {
		return;
	}
	last_post[k][r] = now;
	tb_ev("kind=trip finding=%s rail=%s slot=%d value=%d", tb_finding_str(f->kind),
	      f->rail >= 0 ? tb_rail_name(f->rail) : "-", f->slot, f->value);
}

void tb_trip_cfg_board(struct tb_trip_cfg *cfg)
{
	static const uint32_t trip[TB_RAIL_COUNT][3] = TB_RAIL_TRIP_MA;

	tb_trip_cfg_defaults(cfg);
	for (int r = 0; r < TB_RAIL_COUNT; r++) {
		cfg->trip_min_ma[r] = trip[r][0];
	}
}

int tb_snapshot(struct tb_trip_snapshot *s, uint16_t *inputs, bool all_rails)
{
	bool test = tb.test_rails != 0 && k_uptime_get() < tb.test_until_ms;
	const struct tb_mon *vm = tb_mon_vsys();
	struct tb_mon_reading rd;
	uint16_t in;
	int err;

	memset(s, 0, sizeof(*s));
	err = tb_exp2_inputs(&in);
	if (err != 0) {
		return err;
	}
	*inputs = in;
	s->on = tb.budget.on;
	for (int r = 0; r < TB_RAIL_COUNT; r++) {
		if (tb_rail_settling(r)) {
			s->settling |= TB_RAIL_BIT(r);
		}
	}
	s->fault_low = tb_pin_active(in, &tb_sig.slot_fault);
	s->alert_low = tb_pin_active(in, &tb_sig.pm_alert);
	s->vsys_pg = tb_pin_active(in, &tb_sig.vsys_pg);
	s->s5_pg = tb_pin_active(in, &tb_sig.s5_pg);
	for (int slot = 1; slot <= TB_SLOTS; slot++) {
		if (!tb_pin_active(in, &tb_slots[slot - 1].present)) {
			s->absent |= BIT(slot - 1);
		}
	}
	s->vsys_limit_ma = tb_budget_limit_ma(&tb.budget);
	for (int r = 0; r < TB_RAIL_COUNT; r++) {
		const struct tb_mon *m = tb_mon_for_rail(r);
		bool want = (s->on & TB_RAIL_BIT(r)) || s->fault_low || s->alert_low || all_rails;

		s->rail[r].monitored = m != NULL;
		if (m == NULL || !want) {
			continue;
		}
		if (tb_mon_read(m, s->alert_low, &rd) == 0) {
			s->rail[r].valid = true;
			s->rail[r].current_ua = rd.current_ua;
			s->rail[r].bus_mv = rd.bus_mv;
			s->rail[r].alert = (rd.me & TB_INA226_ME_AFF) != 0;
		}
	}
	if (vm != NULL && tb_mon_read(vm, s->alert_low, &rd) == 0) {
		s->vsys.monitored = s->vsys.valid = true;
		s->vsys.current_ua = rd.current_ua;
		s->vsys.bus_mv = rd.bus_mv;
		s->vsys.alert = (rd.me & TB_INA226_ME_AFF) != 0;
	}
	if (test) {
		/* A self-test drives these rails into their limits on purpose (coupon_test.c). */
		for (int r = 0; r < TB_RAIL_COUNT; r++) {
			if (tb.test_rails & TB_RAIL_BIT(r)) {
				s->rail[r].alert = false;
			}
		}
		s->fault_low = false;
	}
	return 0;
}

void tb_apply_trip(const struct tb_trip_result *res)
{
	for (int i = 0; i < res->n; i++) {
		post_finding(&res->f[i]);
	}
	if (res->all_off) {
		(void)tb_rails_off(TB_RAIL_MASK_ALL, "vsys_pg_low");
		return;
	}
	if (res->off != 0) {
		(void)tb_rails_off(res->off, "trip");
		tb.faults_handled++;
	}
	if (res->shed_one) {
		int v = tb_budget_next_victim(&tb.budget);

		if (v >= 0) {
			(void)tb_rails_off(tb_budget_off_mask(&tb.budget, v), "vsys_over_budget");
			tb.faults_handled++;
		}
	}
}

static void update_vsys_alert(void)
{
	uint32_t ma = tb_budget_limit_ma(&tb.budget);
	const struct tb_mon *vm = tb_mon_vsys();

	/* INA226 0x40's ALERT sits at the VSYS budget (SPEC §3.2, §8.4). */
	if (vm != NULL && ma != vsys_alert_ma && tb_mon_set_alert(vm, ma * 1000u) == 0) {
		vsys_alert_ma = ma;
		tb_ev("kind=budget limit_ma=%u used_ma=%u source=%s usb=%s", ma, tb_budget_used_ma(&tb.budget),
		      tb_source_str(tb.budget.src), tb_usb_state_str(tb.budget.usb));
	}
}

static void handle_usb(enum tb_usb_event ev, uint32_t value)
{
	uint32_t off = tb_budget_usb_event(&tb.budget, ev, value);
	static const char *const names[] = {"reset", "configured", "suspend", "resume", "disconnected"};

	tb_ev("kind=usb event=%s value=%u state=%s", ev < ARRAY_SIZE(names) ? names[ev] : "?", value,
	      tb_usb_state_str(tb.budget.usb));
	tb_apply_budget_off(off, "usb");
}

static void handle_typec(uint16_t in)
{
	bool decided_now = false;
	struct tb_cc_read r;
	int64_t age = k_uptime_get() - tb.boot_ms;

	if (!tb.cc_decided) {
		/* U_CC answers only t_I2C_EN (100 ms max) after its VDD is up: retry until the decide time. */
		if (tb_cc_read(&r, true) == 0) {
			tb.cc_decided = tb.cc_ok = decided_now = true;
		} else if (age >= TB_TUSB320_DECIDE_MS) {
			tb.cc_decided = decided_now = true;
			tb.cc_ok = false;
			r.src = TB_SRC_UNREADABLE;
		} else {
			return;
		}
	} else if (tb.cc_ok && tb_pin_active(in, &tb_sig.usbc_int)) {
		if (tb_cc_read(&r, true) != 0) {
			r.src = TB_SRC_UNREADABLE;
		}
	} else {
		return;
	}
	tb.cc_r08 = r.r08;
	tb.cc_r09 = r.r09;
	tb.cc_rev = r.rev;
	if (decided_now || r.src != tb.budget.src) {
		uint32_t off = tb_budget_set_source(&tb.budget, r.src);

		tb_ev("kind=cc source=%s ok=%d csr08=0x%02x csr09=0x%02x", tb_source_str(r.src), tb.cc_ok, r.r08,
		      r.r09);
		tb_apply_budget_off(off, "source");
	}
}

static void poll_once(void)
{
	struct tb_trip_snapshot snap;
	struct tb_trip_result res;
	struct tb_trip_cfg cfg;
	uint16_t in = 0;
	bool all = (tb.polls % 10) == 0; /* off rails too, once a second at the default period */

	tb.polls++;
	if (tb_snapshot(&snap, &in, all) != 0) {
		static int64_t last;

		if (k_uptime_get() - last > REPOST_MS) {
			last = k_uptime_get();
			tb_ev("kind=error what=exp2_read");
		}
		return;
	}
	if (have_inputs) {
		for (int slot = 1; slot <= TB_SLOTS; slot++) {
			const struct gpio_dt_spec *p = &tb_slots[slot - 1].present;

			if (tb_pin_level(in, p) != tb_pin_level(last_inputs, p)) {
				tb_ev("kind=present slot=%d present=%d", slot, tb_pin_active(in, p));
			}
		}
	}
	for (int slot = 1; slot <= TB_SLOTS; slot++) {
		WRITE_BIT(tb.present, slot - 1, tb_pin_active(in, &tb_slots[slot - 1].present));
	}
	last_inputs = in;
	have_inputs = true;

	handle_typec(in);
	tb_trip_cfg_board(&cfg);
	tb_trip_classify(&cfg, &snap, &res);
	tb_apply_trip(&res);
	update_vsys_alert();
}

static void service(void *a, void *b, void *c)
{
	struct svc_msg m;

	ARG_UNUSED(a);
	ARG_UNUSED(b);
	ARG_UNUSED(c);
	setup_interrupts();
	for (;;) {
		int got = k_msgq_get(&svc_q, &m, K_MSEC(period_ms));

		k_mutex_lock(&tb_lock, K_FOREVER);
		while (got == 0) {
			if (m.type == MSG_USB) {
				handle_usb((enum tb_usb_event)m.ev, m.value);
			} else if (m.type == MSG_KICK) {
				atomic_clear(&kick_queued); /* the poll below covers it */
			}
			got = k_msgq_get(&svc_q, &m, K_NO_WAIT);
		}
		poll_once();
		k_mutex_unlock(&tb_lock);
	}
}

K_THREAD_DEFINE(tb_service_tid, 3072, service, NULL, NULL, NULL, 5, 0, SYS_FOREVER_MS);

void tb_service_start(void)
{
	k_thread_start(tb_service_tid);
}
