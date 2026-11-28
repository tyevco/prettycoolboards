/*
 * Simulated board: "sim ..." commands that change the world the firmware sees (see ../README.md, "Simulated
 * board"). Their records start with "@sim ", never "@tb ", so a harness cannot mistake them for the firmware's.
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include <stdlib.h>
#include <string.h>

#include <zephyr/shell/shell.h>

#include "board.h"
#include "service.h"
#include "sim.h"

extern uint32_t sim_cc_violations;

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

static int done(const struct shell *sh, const char *cmd, int rc)
{
	shell_fprintf(sh, SHELL_NORMAL, "@sim done cmd=%s rc=%d\n", cmd, rc);
	return rc;
}

static int cmd_coupon(const struct shell *sh, size_t argc, char **argv)
{
	static const char *const kinds[] = {"none", "test", "blank", "hall", "turned"}; /* enum sim_coupon_kind */
	int slot = atoi(argv[1]);

	ARG_UNUSED(argc);
	if (slot < 1 || slot > TB_SLOTS) {
		return done(sh, "coupon", -EINVAL);
	}
	for (int k = 0; k < (int)ARRAY_SIZE(kinds); k++) {
		if (strcmp(argv[2], kinds[k]) == 0) {
			sim_set_coupon(slot, (enum sim_coupon_kind)k);
			tb_service_kick();
			return done(sh, "coupon", 0);
		}
	}
	return done(sh, "coupon", -EINVAL);
}

static int cmd_source(const struct shell *sh, size_t argc, char **argv)
{
	const char *s = argv[1];

	ARG_UNUSED(argc);
	sim.cc_absent = strcmp(s, "absent") == 0;
	if (strcmp(s, "none") == 0) {
		sim.cc_attach = 0;
	} else if (strcmp(s, "accessory") == 0) {
		sim.cc_attach = 3;
	} else if (!sim.cc_absent) {
		sim.cc_attach = 2;
		sim.cc_mode = strcmp(s, "3.0A") == 0 ? 3 : strcmp(s, "1.5A") == 0 ? 1 : 0;
	}
	sim.cc_int = true; /* any RU field change raises INT_N (SLLSEQ8D Table 9) */
	sim_update();
	tb_service_kick();
	return done(sh, "source", 0);
}

static int cmd_usb(const struct shell *sh, size_t argc, char **argv)
{
	const char *e = argv[1];

	ARG_UNUSED(argc);
	/* The host's state as the rule monitor sees it (sim.h), set before the firmware hears of it. */
	if (strcmp(e, "reset") == 0) {
		sim.usb_configured = sim.usb_suspended = false;
		tb_service_usb(TB_USB_EV_RESET, 0);
	} else if (strcmp(e, "configured") == 0) {
		sim.usb_configured = true;
		sim.usb_suspended = false;
		tb_service_usb(TB_USB_EV_CONFIGURED, 1);
	} else if (strcmp(e, "deconfigured") == 0) {
		sim.usb_configured = false;
		tb_service_usb(TB_USB_EV_CONFIGURED, 0);
	} else if (strcmp(e, "suspend") == 0) {
		sim.usb_suspended = true;
		tb_service_usb(TB_USB_EV_SUSPEND, 0);
	} else if (strcmp(e, "resume") == 0) {
		sim.usb_suspended = false;
		tb_service_usb(TB_USB_EV_RESUME, 0);
	} else if (strcmp(e, "disconnected") == 0) {
		/* USBD_MSG_VBUS_REMOVED: on the real board VBUS is also its supply, so this is the moment before the
		 * board loses power (or a VBUS glitch it survives) */
		sim.usb_configured = sim.usb_suspended = false;
		tb_service_usb(TB_USB_EV_DISCONNECTED, 0);
	} else {
		return done(sh, "usb", -EINVAL);
	}
	sim.usb_change_ms = k_uptime_get();
	return done(sh, "usb", 0);
}

static int cmd_load(const struct shell *sh, size_t argc, char **argv)
{
	int r = parse_rail(argv[1]);

	ARG_UNUSED(argc);
	if (r < 0) {
		return done(sh, "load", -EINVAL);
	}
	sim.extra_ua[r] = strcmp(argv[2], "off") == 0 ? 0 : (uint32_t)atoi(argv[2]) * 1000u;
	sim_update();
	tb_service_kick();
	return done(sh, "load", 0);
}

static int cmd_pg(const struct shell *sh, size_t argc, char **argv)
{
	ARG_UNUSED(argc);
	sim.vsys_pg_low = atoi(argv[1]) == 0;
	sim_update();
	tb_service_kick();
	return done(sh, "pg", 0);
}

static int cmd_state(const struct shell *sh, size_t argc, char **argv)
{
	ARG_UNUSED(argc);
	ARG_UNUSED(argv);
	sim_update();
	for (int r = 0; r < TB_RAIL_COUNT; r++) {
		shell_fprintf(sh, SHELL_NORMAL, "@sim rail rail=%s on=%d ua=%d mv=%d limiting=%d extra_ua=%u\n",
			      tb_rail_name(r), sim.on[r], sim.ua[r], sim.mv[r], sim.limiting[r], sim.extra_ua[r]);
	}
	for (int s = 1; s <= TB_SLOTS; s++) {
		shell_fprintf(sh, SHELL_NORMAL, "@sim slot slot=%d coupon=%d\n", s, sim.coupon[s - 1]);
	}
	for (int e = 0; e < 3; e++) {
		shell_fprintf(sh, SHELL_NORMAL, "@sim exp exp=%d out=0x%04x cfg=0x%04x in=0x%04x int=%d\n", e + 1,
			      sim.exp[e].out, sim.exp[e].cfg, sim_exp_inputs(e), sim.exp[e].int_pending);
	}
	shell_fprintf(sh, SHELL_NORMAL,
		      "@sim flags vsys_ua=%d fault_n=%d alert_n=%d s5_latched=%d mux=0x%02x bus_slot=%d cc_attach=%u "
		      "cc_mode=%u cc_int=%d cc_violations=%u updates=%u rule_violations=%u first_violation=%s\n",
		      sim.vsys_ua, sim.fault_n, sim.alert_n, sim.s5_latched, sim.mux_ctrl, sim_bus_slot(),
		      sim.cc_attach, sim.cc_mode, sim.cc_int, sim_cc_violations, sim.updates, sim_rule_violations,
		      sim_rule_violations ? sim_first_violation : "none");
	return done(sh, "state", 0);
}

SHELL_STATIC_SUBCMD_SET_CREATE(
	sub_sim,
	SHELL_CMD_ARG(coupon, NULL, "<n> none|test|blank|hall|turned (turned: the key plug missing)", cmd_coupon, 3,
		      0),
	SHELL_CMD_ARG(source, NULL, "none|default|1.5A|3.0A|accessory|absent (U_CC; raises its INT)", cmd_source, 2,
		      0),
	SHELL_CMD_ARG(usb, NULL, "reset|configured|deconfigured|suspend|resume|disconnected", cmd_usb, 2, 0),
	SHELL_CMD_ARG(load, NULL, "<rail> <mA>|off: extra current on a rail", cmd_load, 3, 0),
	SHELL_CMD_ARG(pg, NULL, "0|1: VSYS_PG", cmd_pg, 2, 0),
	SHELL_CMD_ARG(state, NULL, "the model", cmd_state, 1, 0),
	SHELL_SUBCMD_SET_END);

SHELL_CMD_REGISTER(sim, &sub_sim, "Simulated board (native_sim only)", NULL);
