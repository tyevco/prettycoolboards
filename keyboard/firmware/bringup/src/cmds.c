/*
 * The shell commands, "tb <command> ...", on both shells (USART1 and CDC ACM). The protocol, every record and
 * every error token: ../PROTOCOL.md. Each command ends with exactly one "@tb done cmd=<cmd> rc=<rc> [err=..]".
 *
 * Rule: take tb_lock, do the work into locals, release, then print (board.h).
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include <errno.h>
#include <stdlib.h>
#include <string.h>

#include <zephyr/drivers/sensor.h>
#include <zephyr/kernel.h>
#include <zephyr/shell/shell.h>
#include <zephyr/sys/reboot.h>
#include <zephyr/version.h>

#include "board.h"
#include "coupon_test.h"
#include "descio.h"
#include "events.h"
#include "lanes.h"
#include "monitors.h"
#include "out.h"
#include "service.h"
#include "slot.h"
#include "tb/ina226.h"
#include "tb/selftest.h"
#include "tb/trip.h"
#include "tb/tusb320.h"
#include "typec.h"
#include "usb.h"

#define LOCK()   k_mutex_lock(&tb_lock, K_FOREVER)
#define UNLOCK() k_mutex_unlock(&tb_lock)

/* --- argument helpers ------------------------------------------------------------------------------------------ */

static bool parse_u32(const char *s, uint32_t *v)
{
	char *end;
	unsigned long x;

	if (s == NULL || *s == '\0') {
		return false;
	}
	x = strtoul(s, &end, 0);
	if (*end != '\0') {
		return false;
	}
	*v = (uint32_t)x;
	return true;
}

/* "key=value" among argv[from..]: true and *v if present and numeric. */
static bool arg_kv(size_t argc, char **argv, size_t from, const char *key, uint32_t *v)
{
	size_t kl = strlen(key);

	for (size_t i = from; i < argc; i++) {
		if (strncmp(argv[i], key, kl) == 0 && argv[i][kl] == '=') {
			return parse_u32(&argv[i][kl + 1], v);
		}
	}
	return false;
}

static bool arg_flag(size_t argc, char **argv, size_t from, const char *flag)
{
	for (size_t i = from; i < argc; i++) {
		if (strcmp(argv[i], flag) == 0) {
			return true;
		}
	}
	return false;
}

/* "+3V3_S1", "3v3_s1", "+5V_KVM" ... -> rail id, or -1. */
static int parse_rail(const char *s)
{
	for (int r = 0; r < TB_RAIL_COUNT; r++) {
		const char *n = tb_rail_name(r) + 1;
		const char *q = s[0] == '+' ? s + 1 : s;

		while (*n != '\0' && *q != '\0' && (*n | 0x20) == (*q | 0x20)) {
			n++;
			q++;
		}
		if (*n == '\0' && *q == '\0') {
			return r;
		}
	}
	return -1;
}

static int parse_slot(const char *s)
{
	uint32_t v;

	return parse_u32(s, &v) && v >= 1 && v <= TB_SLOTS ? (int)v : -1;
}

/* --- records shared by several commands -------------------------------------------------------------------- */

struct budget_view {
	struct tb_budget b;
	bool bench_build;
};

static void budget_view(struct budget_view *v)
{
	LOCK();
	v->b = tb.budget;
	UNLOCK();
	v->bench_build = IS_ENABLED(CONFIG_BRINGUP_BENCH_SUPPLY);
}

static void print_budget(const struct shell *sh)
{
	struct budget_view v;

	budget_view(&v);
	tbo(sh, "budget usb=%s source=%s may_power=%d limit_ma=%u used_ma=%u base_ma=%u ldo_used_ma=%u ldo_ma=%u "
		"max_ma=%u override_ma=%u bench_ma=%u bench_build=%d",
	    tb_usb_state_str(v.b.usb), tb_source_str(v.b.src), tb_budget_may_power(&v.b), tb_budget_limit_ma(&v.b),
	    tb_budget_used_ma(&v.b), v.b.cfg.base_ma, tb_budget_ldo_used_ma(&v.b), v.b.cfg.slot_ldo_ma,
	    v.b.cfg.vsys_max_ma, v.b.override_ma, v.b.bench_ma, v.bench_build);
	for (int r = 0; r < TB_RAIL_COUNT; r++) {
		if (v.b.on & TB_RAIL_BIT(r)) {
			tbo(sh, "budget_rail rail=%s declared_ma=%u seq=%u", tb_rail_name(r), v.b.declared_ma[r],
			    v.b.seq[r]);
		}
	}
}

static void print_reading(const struct shell *sh, const struct tb_mon *m, const struct tb_mon_reading *r)
{
	if (r->err != 0) {
		tbo(sh, "ina addr=0x%02x rail=%s ok=0 err=%s", m->bus.addr, m->name, tb_errno_str(r->err));
		return;
	}
	tbo(sh, "ina addr=0x%02x rail=%s ok=1 current_ua=%d shunt_current_ua=%d bus_mv=%d shunt_uv=%d power_uw=%u "
		"config=0x%04x cal=%u cal_expect=%u lsb_ua=%u shunt_uohm=%u me=0x%04x aff=%d",
	    m->bus.addr, m->name, r->current_ua, r->shunt_current_ua, r->bus_mv, r->shunt_uv, r->power_uw, r->config,
	    r->cal, m->cal, m->lsb_ua, m->shunt_uohm, r->me, (r->me & TB_INA226_ME_AFF) != 0);
}

static void print_restore(const struct shell *sh, const struct tb_restore_report *rep)
{
	for (int i = 0; i < TB_EXP_COUNT; i++) {
		tbo(sh, "restore exp=%d out=0x%04x cfg=0x%04x ok=%d", i + 1, rep->out[i], rep->cfg[i], rep->exp_ok[i]);
	}
	tbo(sh, "restore mux=0x%02x mux_err=%d ok=%d", rep->mux_ctrl, rep->mux_err, rep->ok);
}

/* --- commands ------------------------------------------------------------------------------------------------ */

static int cmd_info(const struct shell *sh, size_t argc, char **argv)
{
	ARG_UNUSED(argc);
	ARG_UNUSED(argv);
	tbo(sh, "info fw=bringup proto=%d board=kbd_testbed_a map=%s nets_rev=%s nets_date=%s zephyr=%s uptime_ms=%u "
		"bench_build=%d tim1=%d settle_ms=%d period_ms=%u",
	    TB_PROTO_VERSION, TB_MAP_HASH, TB_MAP_NETS_REV, TB_MAP_NETS_DATE, KERNEL_VERSION_STRING,
	    k_uptime_get_32(), IS_ENABLED(CONFIG_BRINGUP_BENCH_SUPPLY), DT_NODE_HAS_STATUS_OKAY(DT_NODELABEL(pwm1)),
	    CONFIG_BRINGUP_SETTLE_MS, tb_service_period_ms());
	return tb_done(sh, "info", 0, NULL);
}

struct line_ctx {
	const struct shell *sh;
};

static void shell_line(void *ctx, const char *s)
{
	tbo(((struct line_ctx *)ctx)->sh, "%s", s);
}

static int cmd_boot(const struct shell *sh, size_t argc, char **argv)
{
	struct line_ctx c = {.sh = sh};

	ARG_UNUSED(argc);
	ARG_UNUSED(argv);
	tb_boot_report(shell_line, &c);
	return tb_done(sh, "boot", 0, NULL);
}

static int cmd_safe(const struct shell *sh, size_t argc, char **argv)
{
	struct tb_restore_report rep;
	int err;

	ARG_UNUSED(argc);
	ARG_UNUSED(argv);
	LOCK();
	err = tb_restore(&rep);
	UNLOCK();
	tb_ev("kind=restore ok=%d", rep.ok);
	print_restore(sh, &rep);
	return tb_done(sh, "safe", err ? err : (rep.ok ? 0 : -EIO), rep.ok ? NULL : "readback");
}

static int cmd_usb(const struct shell *sh, size_t argc, char **argv)
{
	struct budget_view v;

	ARG_UNUSED(argc);
	ARG_UNUSED(argv);
	budget_view(&v);
	tbo(sh, "usb state=%s config=%u speed=%s", tb_usb_state_str(v.b.usb), tb_usb_config_value(),
	    v.b.usb == TB_USB_UNCONFIGURED ? "none" : (tb_usb_high_speed() ? "hs" : "fs"));
	return tb_done(sh, "usb", 0, NULL);
}

static int cmd_cc(const struct shell *sh, size_t argc, char **argv)
{
	struct tb_cc_read r;
	bool decided, ok;
	int err;

	ARG_UNUSED(argc);
	ARG_UNUSED(argv);
	LOCK();
	err = tb_cc_read(&r, false);
	decided = tb.cc_decided;
	ok = tb.cc_ok;
	UNLOCK();
	if (r.err != 0) {
		tbo(sh, "cc present=0 decided=%d err=%s", decided, tb_errno_str(r.err));
		return tb_done(sh, "cc", r.err, NULL);
	}
	tbo(sh, "cc present=1 id_ok=%d id=%02x%02x%02x%02x%02x%02x%02x%02x rev=0x%02x csr08=0x%02x csr09=0x%02x "
		"csr0a=0x%02x attached=%s mode=%u source=%s int=%d decided=%d usable=%d",
	    r.id_ok, r.id[0], r.id[1], r.id[2], r.id[3], r.id[4], r.id[5], r.id[6], r.id[7], r.rev, r.r08, r.r09,
	    r.r0a, tb_tusb320_attach_str(tb_tusb320_attached(r.r09)), tb_tusb320_current_mode(r.r08),
	    tb_source_str(r.src), r.int_pending, decided, ok);
	return tb_done(sh, "cc", err, r.id_ok ? NULL : "not_tusb320");
}

static int cmd_budget(const struct shell *sh, size_t argc, char **argv)
{
	uint32_t ma = 0, off = 0;
	int rc = 0;
	const char *err = NULL;

	if (argc >= 3) {
		bool clear = strcmp(argv[2], "off") == 0;

		if (!clear && !parse_u32(argv[2], &ma)) {
			return tb_done(sh, "budget", -EINVAL, "usage");
		}
		LOCK();
		if (strcmp(argv[1], "override") == 0) {
			off = tb_budget_set_override(&tb.budget, clear ? 0 : ma);
			tb_apply_budget_off(off, "override");
		} else if (strcmp(argv[1], "base") == 0 && !clear) {
			off = tb_budget_set_base(&tb.budget, ma);
			tb_apply_budget_off(off, "base");
		} else if (strcmp(argv[1], "bench") == 0) {
			if (!IS_ENABLED(CONFIG_BRINGUP_BENCH_SUPPLY)) {
				rc = -ENOTSUP;
				err = "not_built";
			} else {
				enum tb_refusal r = tb_budget_set_bench(&tb.budget, clear ? 0 : ma, &off);

				if (r != TB_BUDGET_OK) {
					rc = -EPERM;
					err = tb_refusal_str(r);
				}
				tb_apply_budget_off(off, "bench");
			}
		} else {
			rc = -EINVAL;
			err = "usage";
		}
		UNLOCK();
		if (rc == 0) {
			tb_ev("kind=budget_set what=%s ma=%u shed=0x%03x", argv[1], clear ? 0 : ma, off);
			tb_service_kick();
		}
	} else if (argc == 2) {
		return tb_done(sh, "budget", -EINVAL, "usage");
	}
	print_budget(sh);
	if (off != 0) {
		tbo(sh, "shed mask=0x%03x", off);
	}
	return tb_done(sh, "budget", rc, err);
}

static int cmd_ina(const struct shell *sh, size_t argc, char **argv)
{
	struct tb_mon_reading r;
	const struct tb_mon *m;

	if (argc >= 2 && strcmp(argv[1], "cfg") == 0) {
		uint32_t avg, vb, vs, mode;
		int32_t c;
		int err = 0;

		if (argc != 7 || !parse_u32(argv[3], &avg) || !parse_u32(argv[4], &vb) || !parse_u32(argv[5], &vs) ||
		    !parse_u32(argv[6], &mode)) {
			return tb_done(sh, "ina", -EINVAL, "usage");
		}
		c = tb_ina226_config(avg, vb, vs, (enum tb_ina226_mode)mode);
		if (c < 0) {
			return tb_done(sh, "ina", -EINVAL, "bad_config");
		}
		LOCK();
		for (int i = 0; i < tb_mon_count; i++) {
			m = tb_mon_at(i);
			if (strcmp(argv[2], "all") == 0 || m == tb_mon_by_name(argv[2])) {
				err |= tb_mon_reg_write(m, TB_INA226_REG_CONFIG, (uint16_t)c);
			}
		}
		UNLOCK();
		tbo(sh, "ina_cfg target=%s config=0x%04x period_us=%u", argv[2], (unsigned)c,
		    tb_ina226_sample_period_us((uint16_t)c));
		return tb_done(sh, "ina", err ? -EIO : 0, NULL);
	}
	if (argc >= 2 && strcmp(argv[1], "alert") == 0) {
		uint32_t ma = 0;
		int err;

		if (argc != 4 || (m = tb_mon_by_name(argv[2])) == NULL ||
		    (strcmp(argv[3], "off") != 0 && !parse_u32(argv[3], &ma))) {
			return tb_done(sh, "ina", -EINVAL, "usage");
		}
		LOCK();
		err = tb_mon_set_alert(m, ma * 1000u);
		UNLOCK();
		tbo(sh, "ina_alert rail=%s limit_ma=%u limit_raw=%u", m->name, ma,
		    ma ? tb_ina226_sol_limit(ma * 1000u, m->shunt_uohm) : 0);
		return tb_done(sh, "ina", err, NULL);
	}
	if (argc >= 2 && strcmp(argv[1], "drv") == 0) {
		struct sensor_value cur, bus;
		int err;

		if (argc != 3 || (m = tb_mon_by_name(argv[2])) == NULL) {
			return tb_done(sh, "ina", -EINVAL, "usage");
		}
		if (!device_is_ready(m->drv)) {
			return tb_done(sh, "ina", -ENODEV, "driver_not_ready");
		}
		LOCK();
		err = sensor_sample_fetch(m->drv);
		err = err ? err : sensor_channel_get(m->drv, SENSOR_CHAN_CURRENT, &cur);
		err = err ? err : sensor_channel_get(m->drv, SENSOR_CHAN_VOLTAGE, &bus);
		UNLOCK();
		if (err == 0) {
			tbo(sh, "ina_drv rail=%s current_ua=%d bus_mv=%d", m->name, cur.val1 * 1000000 + cur.val2,
			    bus.val1 * 1000 + bus.val2 / 1000);
		}
		return tb_done(sh, "ina", err, NULL);
	}
	for (int i = 0; i < tb_mon_count; i++) {
		m = tb_mon_at(i);
		if (argc >= 2 && strcmp(argv[1], "all") != 0 && m != tb_mon_by_name(argv[1])) {
			continue;
		}
		LOCK();
		(void)tb_mon_read(m, false, &r);
		UNLOCK();
		print_reading(sh, m, &r);
	}
	return tb_done(sh, "ina", 0, NULL);
}

static int cmd_exp(const struct shell *sh, size_t argc, char **argv)
{
	static const char *const names[TB_EXP_COUNT][16] = TB_EXP_NET_NAMES;
	uint16_t in[TB_EXP_COUNT], out[TB_EXP_COUNT], pol[TB_EXP_COUNT], cfg[TB_EXP_COUNT];
	int err[TB_EXP_COUNT];

	ARG_UNUSED(argc);
	ARG_UNUSED(argv);
	LOCK();
	for (int i = 0; i < TB_EXP_COUNT; i++) {
		/* Reading the input port clears the TCA9535's INT; the service re-reads on its next poll. */
		err[i] = tb_exp_read(i, 0x00, &in[i]);
		err[i] |= tb_exp_read(i, 0x02, &out[i]);
		err[i] |= tb_exp_read(i, 0x04, &pol[i]);
		err[i] |= tb_exp_read(i, 0x06, &cfg[i]);
	}
	UNLOCK();
	for (int i = 0; i < TB_EXP_COUNT; i++) {
		tbo(sh, "exp exp=%d addr=0x%02x ok=%d in=0x%04x out=0x%04x pol=0x%04x cfg=0x%04x", i + 1,
		    tb_sig.exp_addr[i], err[i] == 0, in[i], out[i], pol[i], cfg[i]);
		if (err[i] != 0) {
			continue;
		}
		for (int p = 0; p < 16; p++) {
			if (names[i][p] != NULL) {
				bool o = !((cfg[i] >> p) & 1u);

				tbo(sh, "net name=%s exp=%d pin=P%d%d dir=%s level=%d", names[i][p], i + 1, p / 8, p % 8,
				    o ? "out" : "in", (int)(((o ? out[i] : in[i]) >> p) & 1u));
			}
		}
	}
	return tb_done(sh, "exp", 0, NULL);
}

static int cmd_rail(const struct shell *sh, size_t argc, char **argv)
{
	enum tb_refusal why = TB_BUDGET_OK;
	uint32_t ma, off = 0;
	int rail, err = 0;
	struct tb_mon_reading r;
	bool fault = false;

	if (argc < 3 || (rail = parse_rail(argv[1])) < 0) {
		return tb_done(sh, "rail", -EINVAL, "usage");
	}
	if (strcmp(argv[2], "on") == 0) {
		if (argc != 4 || !parse_u32(argv[3], &ma)) {
			return tb_done(sh, "rail", -EINVAL, "usage");
		}
		LOCK();
		err = tb_rail_on(rail, ma, &why);
		if (err == 0) {
			err = tb_rail_settle(rail, &r, &fault);
		}
		UNLOCK();
		if (err == -ENODEV) {
			return tb_done(sh, "rail", err, "not_present");
		}
		if (why != TB_BUDGET_OK) {
			return tb_done(sh, "rail", -EPERM, tb_refusal_str(why));
		}
		if (err == 0 && tb_mon_for_rail(rail) != NULL) {
			print_reading(sh, tb_mon_for_rail(rail), &r);
		}
		tbo(sh, "rail rail=%s on=1 declared_ma=%u fault=%d", tb_rail_name(rail), ma, fault);
		return tb_done(sh, "rail", err, NULL);
	}
	if (strcmp(argv[2], "off") == 0) {
		LOCK();
		off = tb_rails_off(TB_RAIL_BIT(rail), "operator");
		UNLOCK();
		tbo(sh, "rail rail=%s on=0 off_mask=0x%03x", tb_rail_name(rail), off);
		return tb_done(sh, "rail", 0, NULL);
	}
	return tb_done(sh, "rail", -EINVAL, "usage");
}

static void print_slot(const struct shell *sh, int slot)
{
	const struct tb_slot_hw *h = tb_slot_hw(slot);
	struct tb_desc d;
	int derr;
	bool present, on3, on5, bus;

	LOCK();
	present = tb.present & BIT(slot - 1);
	on3 = tb.budget.on & TB_RAIL_BIT(h->rail3);
	on5 = tb.budget.on & TB_RAIL_BIT(h->rail5);
	bus = tb.bus_closed & BIT(slot - 1);
	d = tb.desc[slot - 1];
	derr = tb.desc_err[slot - 1];
	UNLOCK();
	if (derr == TB_DESC_OK) {
		tbo(sh, "slot slot=%d present=%d on3=%d on5=%d bus=%d desc=ok type=%s rev=%c serial=%u i3v3_ma=%u "
			"i5v_ma=%u",
		    slot, present, on3, on5, bus, tb_coupon_type_str(d.type), d.rev, d.serial, d.i3v3_ma, d.i5v_ma);
	} else {
		tbo(sh, "slot slot=%d present=%d on3=%d on5=%d bus=%d desc=%s", slot, present, on3, on5, bus,
		    derr == 1 ? "none" : derr == TB_DESCIO_BUS_ERR ? "bus_error" : tb_desc_err_str(derr));
	}
}

static int cmd_slot(const struct shell *sh, size_t argc, char **argv)
{
	int slot;

	if (argc == 1) {
		for (int s = 1; s <= TB_SLOTS; s++) {
			print_slot(sh, s);
		}
		return tb_done(sh, "slot", 0, NULL);
	}
	slot = parse_slot(argv[1]);
	if (slot < 0) {
		return tb_done(sh, "slot", -EINVAL, "usage");
	}
	if (argc >= 3 && strcmp(argv[2], "on") == 0) {
		struct tb_slot_on_opts o = {.use_desc = !arg_flag(argc, argv, 3, "nodesc"),
					    .keep_blank = arg_flag(argc, argv, 3, "keep")};
		struct tb_slot_on_result res;
		int err;

		if (!o.use_desc && !arg_kv(argc, argv, 3, "ma3", &o.ma3)) {
			return tb_done(sh, "slot", -EINVAL, "usage");
		}
		(void)arg_kv(argc, argv, 3, "ma5", &o.ma5);
		(void)arg_kv(argc, argv, 3, "probe", &o.probe_ma);
		LOCK();
		err = tb_slot_on(slot, &o, &res);
		UNLOCK();
		tbo(sh, "slot_on slot=%d on3=%d on5=%d bus=%d i3_ua=%d v3_mv=%d i5_ua=%d v5_mv=%d fault=%d desc=%s "
			"ma3=%u ma5=%u",
		    slot, res.on3, res.on5, res.bus, res.r3.current_ua, res.r3.bus_mv, res.r5.current_ua, res.r5.bus_mv,
		    res.fault, res.desc == 1 ? "none" : res.desc == TB_DESCIO_BUS_ERR ? "bus_error"
										 : tb_desc_err_str(res.desc),
		    res.ma3, res.ma5);
		print_slot(sh, slot);
		return tb_done(sh, "slot", err, res.err);
	}
	if (argc >= 3 && strcmp(argv[2], "off") == 0) {
		LOCK();
		tb_slot_off(slot, "operator");
		UNLOCK();
		print_slot(sh, slot);
		return tb_done(sh, "slot", 0, NULL);
	}
	if (argc == 2) {
		print_slot(sh, slot);
		return tb_done(sh, "slot", 0, NULL);
	}
	return tb_done(sh, "slot", -EINVAL, "usage");
}

static void print_desc(const struct shell *sh, int slot, const struct tb_desc *d)
{
	tbo(sh, "desc slot=%d status=ok len=%u major=%u minor=%u type=%s rev=%c flags=0x%04x serial=%u i3v3_ma=%u "
		"i5v_ma=%u c3v3_uf=%u c5v_uf=%u name=\"%s\" slots=0x%02x i2c=%u spi=%u cal=%u unknown=%u",
	    slot, d->length, d->major, d->minor, tb_coupon_type_str(d->type), d->rev, d->flags, d->serial, d->i3v3_ma,
	    d->i5v_ma, d->c3v3_uf, d->c5v_uf, d->name, d->slot_mask, d->n_i2c, d->n_spi, d->n_cal, d->n_unknown);
	for (int k = 0; k < 4; k++) {
		if (d->lane[k].present) {
			tbo(sh, "desc_lane slot=%d lane=%d flags=0x%02x r_src_ohm=%u cload_pf=%u expect_ppm=%u tol_ppm=%u",
			    slot, k, d->lane[k].flags, d->lane[k].r_src_ohm, d->lane[k].cload_pf,
			    tb_q16_to_ppm(d->lane[k].expect_q16), tb_q16_to_ppm(d->lane[k].tol_q16));
		}
	}
	for (int g = 0; g < 6; g++) {
		if (d->gline_role[g] != 0) {
			tbo(sh, "desc_gline slot=%d line=G%d role=%u arg=%u", slot, g, d->gline_role[g], d->gline_arg[g]);
		}
	}
	for (int i = 0; i < TB_DESC_MAX_LOADS; i++) {
		if (d->load[i].present) {
			tbo(sh, "desc_load slot=%d load=%d line=G%u rail=%s kind=%s r_mohm=%u slots=0x%02x", slot, i,
			    d->load[i].gline, d->load[i].rail ? "+5V" : "+3V3", d->load[i].kind ? "climit" : "cal",
			    d->load[i].r_mohm, d->load[i].slot_mask);
		}
	}
}

static void print_hex(const struct shell *sh, int slot, const uint8_t *raw, size_t len)
{
	for (size_t off = 0; off < len; off += 16) {
		char hex[33];
		size_t n = MIN((size_t)16, len - off);

		for (size_t i = 0; i < n; i++) {
			static const char digits[] = "0123456789abcdef";

			hex[2 * i] = digits[raw[off + i] >> 4];
			hex[2 * i + 1] = digits[raw[off + i] & 0xF];
		}
		hex[2 * n] = '\0';
		tbo(sh, "desc_hex slot=%d off=%u data=%s", slot, (unsigned)off, hex);
	}
}

static int cmd_desc(const struct shell *sh, size_t argc, char **argv)
{
	static uint8_t raw[TB_DESC_MAX_LEN];
	struct tb_desc d;
	size_t len = 0;
	int slot, err;
	bool on3;

	if (argc < 2 || (slot = parse_slot(argv[1])) < 0) {
		return tb_done(sh, "desc", -EINVAL, "usage");
	}
	LOCK();
	on3 = tb.budget.on & TB_RAIL_BIT(tb_slot_hw(slot)->rail3);
	UNLOCK();
	if (!on3) {
		return tb_done(sh, "desc", -EACCES, "slot_off");
	}
	if (argc >= 4 && strcmp(argv[2], "write") == 0 && strcmp(argv[3], "test") == 0) {
		uint32_t serial = 0;
		bool force = arg_flag(argc, argv, 4, "force");
		int n, cur;

		(void)arg_kv(argc, argv, 4, "serial", &serial);
		tb_desc_test_coupon(&d, serial);
		LOCK();
		cur = tb_descio_load(slot, raw, sizeof(raw), &len);
		if (cur == TB_DESC_OK && !force) {
			UNLOCK();
			return tb_done(sh, "desc", -EEXIST, "already_written");
		}
		n = tb_desc_encode(&d, raw, sizeof(raw));
		err = n < 0 ? -EINVAL : tb_descio_write(slot, raw, (size_t)n);
		if (err == 0) {
			cur = tb_descio_load(slot, raw, sizeof(raw), &len);
			err = cur == TB_DESC_OK ? 0 : -EIO;
		}
		d = tb.desc[slot - 1];
		UNLOCK();
		if (err == 0) {
			print_desc(sh, slot, &d);
			tb_ev("kind=desc_written slot=%d serial=%u", slot, serial);
		}
		return tb_done(sh, "desc", err, err == -EIO ? "verify" : NULL);
	}
	if (argc != 2) {
		return tb_done(sh, "desc", -EINVAL, "usage");
	}
	LOCK();
	err = tb_descio_load(slot, raw, sizeof(raw), &len);
	d = tb.desc[slot - 1];
	UNLOCK();
	print_hex(sh, slot, raw, len);
	if (err == TB_DESCIO_BUS_ERR) {
		tbo(sh, "desc slot=%d status=bus_error", slot);
		return tb_done(sh, "desc", -EIO, "bus_error");
	}
	if (err != TB_DESC_OK) {
		tbo(sh, "desc slot=%d status=%s", slot, tb_desc_err_str(err));
		return tb_done(sh, "desc", -ENOENT, tb_desc_err_str(err));
	}
	print_desc(sh, slot, &d);
	return tb_done(sh, "desc", 0, NULL);
}

static int cmd_lanes(const struct shell *sh, size_t argc, char **argv)
{
	int first = 1, last = TB_SLOTS, bad = 0;
	int32_t vdda = 0;
	int verr;

	if (argc >= 2) {
		first = last = parse_slot(argv[1]);
		if (first < 0) {
			return tb_done(sh, "lanes", -EINVAL, "usage");
		}
	}
	LOCK();
	verr = tb_vdda_mv(&vdda);
	UNLOCK();
	tbo(sh, "vdda mv=%d ok=%d", vdda, verr == 0 && vdda >= 3200 && vdda <= 3400);
	for (int slot = first; slot <= last; slot++) {
		struct tb_desc d;
		bool on3;
		int32_t prim[4] = {0};
		unsigned pbits[4] = {0};

		LOCK();
		on3 = tb.budget.on & TB_RAIL_BIT(tb_slot_hw(slot)->rail3);
		d = tb.desc[slot - 1];
		if (tb.desc_err[slot - 1] != TB_DESC_OK) {
			memset(&d, 0, sizeof(d));
		}
		UNLOCK();
		for (int k = 0; k < 4; k++) {
			uint8_t adc, ch;
			int err;

			LOCK();
			err = tb_lane_read(slot, k, &prim[k], &pbits[k], &adc, &ch);
			UNLOCK();
			if (err != 0) {
				bad++;
				tbo(sh, "lane slot=%d lane=%d adc=%u ch=%u ok=0 err=%s", slot, k, adc, ch, tb_errno_str(err));
				continue;
			}
			if (on3 && d.lane[k].present && d.lane[k].expect_q16 != 0) {
				uint32_t exp = tb_q16_to_ppm(d.lane[k].expect_q16);
				int32_t e;
				bool ok = tb_lane_check((uint32_t)prim[k], pbits[k], exp, tb_q16_to_ppm(d.lane[k].tol_q16),
							&e);

				bad += !ok;
				tbo(sh, "lane slot=%d lane=%d adc=%u ch=%u bits=%u code=%d ratio_ppm=%u state=%s "
					"expect_ppm=%u err_ppm=%d ok=%d",
				    slot, k, adc, ch, pbits[k], prim[k], tb_lane_ratio_ppm((uint32_t)prim[k], pbits[k]),
				    tb_lane_state((uint32_t)prim[k], pbits[k]) == TB_LANE_MID ? "mid"
				    : tb_lane_state((uint32_t)prim[k], pbits[k]) == TB_LANE_LOW ? "low" : "high",
				    exp, e, ok);
			} else {
				tbo(sh, "lane slot=%d lane=%d adc=%u ch=%u bits=%u code=%d ratio_ppm=%u state=%s powered=%d",
				    slot, k, adc, ch, pbits[k], prim[k], tb_lane_ratio_ppm((uint32_t)prim[k], pbits[k]),
				    tb_lane_state((uint32_t)prim[k], pbits[k]) == TB_LANE_MID ? "mid"
				    : tb_lane_state((uint32_t)prim[k], pbits[k]) == TB_LANE_LOW ? "low" : "high",
				    on3);
			}
		}
		for (int i = 0;; i++) {
			uint8_t lane, adc, ch;
			int32_t code, diff;
			unsigned bits;
			bool ok;
			int err;

			if (tb_slot_alt(slot, i, &lane, &adc, &ch) != 0) {
				break;
			}
			LOCK();
			err = tb_adc_read(adc, ch, &code, &bits);
			UNLOCK();
			if (err != 0) {
				bad++;
				tbo(sh, "lane_alt slot=%d lane=%u adc=%u ch=%u ok=0 err=%s", slot, lane, adc, ch,
				    tb_errno_str(err));
				continue;
			}
			ok = tb_lanes_agree((uint32_t)code, bits, (uint32_t)prim[lane], pbits[lane], 3000, &diff);
			/* agreement is only a check where the lane is driven (a powered coupon) */
			bad += on3 && !ok;
			tbo(sh, "lane_alt slot=%d lane=%u adc=%u ch=%u bits=%u code=%d diff_ppm=%d agree=%d powered=%d",
			    slot, lane, adc, ch, bits, code, diff, ok, on3);
		}
	}
	return tb_done(sh, "lanes", bad ? -EIO : 0, bad ? "check" : NULL);
}

static int cmd_selftest(const struct shell *sh, size_t argc, char **argv)
{
	struct tb_st_opts o;
	int slot;

	if (argc < 2 || (slot = parse_slot(argv[1])) < 0) {
		return tb_done(sh, "selftest", -EINVAL, "usage");
	}
	o.loads = arg_flag(argc, argv, 2, "loads") || arg_flag(argc, argv, 2, "all");
	o.climit = arg_flag(argc, argv, 2, "climit") || arg_flag(argc, argv, 2, "all");
	o.force = arg_flag(argc, argv, 2, "force");
	return tb_done(sh, "selftest", tb_selftest_run(sh, slot, &o), NULL);
}

static int cmd_trips(const struct shell *sh, size_t argc, char **argv)
{
	struct tb_trip_snapshot s;
	struct tb_trip_result res;
	struct tb_trip_cfg cfg;
	bool apply = arg_flag(argc, argv, 1, "apply");
	uint16_t in = 0;
	int err;

	LOCK();
	err = tb_snapshot(&s, &in, true);
	if (err == 0) {
		tb_trip_cfg_board(&cfg);
		tb_trip_classify(&cfg, &s, &res);
		if (apply) {
			tb_apply_trip(&res);
		}
	}
	UNLOCK();
	if (err != 0) {
		return tb_done(sh, "trips", err, "exp2_read");
	}
	tbo(sh, "trips exp2=0x%04x on=0x%03x fault=%d alert=%d vsys_pg=%d s5_pg=%d absent=0x%02x vsys_ua=%d findings=%u "
		"off=0x%03x shed_one=%d all_off=%d applied=%d",
	    in, s.on, s.fault_low, s.alert_low, s.vsys_pg, s.s5_pg, s.absent, s.vsys.current_ua, res.n, res.off,
	    res.shed_one, res.all_off, apply);
	for (int i = 0; i < res.n; i++) {
		tbo(sh, "trip finding=%s rail=%s slot=%d value=%d", tb_finding_str(res.f[i].kind),
		    res.f[i].rail >= 0 ? tb_rail_name(res.f[i].rail) : "-", res.f[i].slot, res.f[i].value);
	}
	for (int r = 0; r < TB_RAIL_COUNT; r++) {
		if (s.rail[r].valid) {
			tbo(sh, "trip_rail rail=%s on=%d current_ua=%d bus_mv=%d aff=%d", tb_rail_name(r),
			    (s.on & TB_RAIL_BIT(r)) != 0, s.rail[r].current_ua, s.rail[r].bus_mv, s.rail[r].alert);
		}
	}
	return tb_done(sh, "trips", 0, NULL);
}

static int cmd_mon(const struct shell *sh, size_t argc, char **argv)
{
	uint32_t polls, faults, ms;

	if (argc == 3 && strcmp(argv[1], "period") == 0) {
		if (!parse_u32(argv[2], &ms)) {
			return tb_done(sh, "mon", -EINVAL, "usage");
		}
		tb_service_set_period(ms);
	} else if (argc != 1) {
		return tb_done(sh, "mon", -EINVAL, "usage");
	}
	LOCK();
	polls = tb.polls;
	faults = tb.faults_handled;
	UNLOCK();
	tbo(sh, "mon period_ms=%u polls=%u faults_handled=%u ev_next=%u", tb_service_period_ms(), polls, faults,
	    tb_ev_next_seq());
	return tb_done(sh, "mon", 0, NULL);
}

static int cmd_ev(const struct shell *sh, size_t argc, char **argv)
{
	uint32_t since = 0;

	if (argc >= 2 && !parse_u32(argv[1], &since)) {
		return tb_done(sh, "ev", -EINVAL, "usage");
	}
	tbo(sh, "ev_dump since=%u next=%u replayed=%d", since, tb_ev_next_seq(), tb_ev_dump(sh, since));
	return tb_done(sh, "ev", 0, NULL);
}

static int cmd_reboot(const struct shell *sh, size_t argc, char **argv)
{
	struct tb_restore_report rep;

	ARG_UNUSED(argc);
	ARG_UNUSED(argv);
	LOCK();
	(void)tb_restore(&rep);
	UNLOCK();
	tb_done(sh, "reboot", 0, NULL);
	k_msleep(50);
	sys_reboot(SYS_REBOOT_WARM);
	return 0;
}

SHELL_STATIC_SUBCMD_SET_CREATE(
	sub_tb,
	SHELL_CMD_ARG(info, NULL, "firmware, map and protocol version", cmd_info, 1, 0),
	SHELL_CMD_ARG(boot, NULL, "the boot report: reset cause, expanders and mux before and after restore", cmd_boot,
		      1, 0),
	SHELL_CMD_ARG(safe, NULL, "every rail off, bus switches open, mux deselected (always allowed)", cmd_safe, 1, 0),
	SHELL_CMD_ARG(usb, NULL, "USB state", cmd_usb, 1, 0),
	SHELL_CMD_ARG(cc, NULL, "read U_CC (TUSB320LAI): the source's advertisement", cmd_cc, 1, 0),
	SHELL_CMD_ARG(budget, NULL, "[override <mA>|off] [bench <mA>|off] [base <mA>]", cmd_budget, 1, 2),
	SHELL_CMD_ARG(ina, NULL, "[<rail>|<0xaddr>|all] | cfg <rail|all> <avg> <vbus_us> <vsh_us> <mode> | "
				 "alert <rail> <mA>|off | drv <rail>",
		      cmd_ina, 1, 6),
	SHELL_CMD_ARG(exp, NULL, "the three TCA9535s, raw and by net", cmd_exp, 1, 0),
	SHELL_CMD_ARG(rail, NULL, "<rail> on <declared mA> | <rail> off", cmd_rail, 3, 1),
	SHELL_CMD_ARG(slot, NULL, "[<n> [on [probe=<mA>] [keep] | on nodesc ma3=<mA> [ma5=<mA>] | off]]", cmd_slot,
		      1, 5),
	SHELL_CMD_ARG(desc, NULL, "<n> [write test [serial=<n>] [force]]", cmd_desc, 2, 4),
	SHELL_CMD_ARG(lanes, NULL, "[<n>]: every lane on every converter, VDDA", cmd_lanes, 1, 1),
	SHELL_CMD_ARG(selftest, NULL, "<n> [loads] [climit] [all] [force]: the test coupon", cmd_selftest, 2, 4),
	SHELL_CMD_ARG(trips, NULL, "[apply]: classify a fresh snapshot (and act on it)", cmd_trips, 1, 1),
	SHELL_CMD_ARG(mon, NULL, "[period <ms>]: the board service", cmd_mon, 1, 2),
	SHELL_CMD_ARG(ev, NULL, "[<since seq>]: replay events", cmd_ev, 1, 1),
	SHELL_CMD_ARG(reboot, NULL, "safe state, then a warm reboot", cmd_reboot, 1, 0),
	SHELL_SUBCMD_SET_END);

SHELL_CMD_REGISTER(tb, &sub_tb, "PrettyCool testbed bring-up (keyboard/firmware/bringup/PROTOCOL.md)", NULL);
