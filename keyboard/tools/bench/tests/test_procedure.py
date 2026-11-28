"""The whole bring-up procedure against the simulated board: healthy, and with each injected fault.

Each test runs SPEC §10 steps 5-7 end to end (link, safe, boot, expanders, monitors, U_CC, USB, then every slot
with a coupon) and checks the verdict, the failed step and the check that names the fault. What this proves: the
harness's sequencing, its pass/fail arithmetic, its stop-on-danger path and its reports, against a model that
speaks the protocol. What it cannot: anything about the board; the model's numbers are placeholders.
"""

import pytest


def names(checks):
    return [c.name for c in checks]


# --- healthy -----------------------------------------------------------------------------------------------------
def test_healthy_usb_run(sim):
    s = sim(climit=True, meter=True, source="3.0A")
    run = s.go()
    assert run.verdict == "PASS (with warnings)", s.failed()
    assert s.failed() == {"monitors": "warn", "slot1.desc": "warn"}, \
        "the only warnings: the firmware's settle time and the two descriptor formats' +5V (README findings 1, 3)"
    assert names(s.checks("monitors", "warn")) == ["firmware settle time against the INA226 result period"]
    assert names(s.checks("slot1.desc", "warn")) == ["declared +5V as its descriptor of record"]
    assert s.checks("slot1.desc", "warn")[0].measured == "EEPROM 170, record 190"
    assert run.stop is None
    assert run.slots[1]["coupon_serial"] == 1 and run.slots[1]["series_mohm"] == 326
    assert run.slots[1]["climit3_ma"] == 292.0 and run.slots[1]["climit5_ma"] == 577.0
    assert not s.dev.on, "every rail off at the end"
    assert "tb selftest 1 all" in s.sent()


def test_healthy_bench_supply_run(sim):
    s = sim(usb="unconfigured", bench_build=True, power="bench", bench_ma=1000, console="uart", climit=True)
    run = s.go()
    assert run.verdict.startswith("PASS"), s.failed()
    assert "tb budget bench 1000" in s.sent()


def test_every_coupon_is_tested_one_slot_at_a_time(sim):
    s = sim(coupons={1: "test", 3: "test", 5: "test"}, climit=True)
    run = s.go()
    assert run.verdict.startswith("PASS"), s.failed()
    assert sorted(run.slots) == [1, 3, 5]
    assert s.max_slot_rails == 1, "one 3.3 V slot rail at a time (the slot LDO's 300 mA, SPEC §3.2)"
    st5 = {c.name: c for c in s.checks("slot5.selftest")}
    assert st5["climit5"].verdict == "skip" and st5["climit5"].measured == "never_on_s5"
    assert "loopback" in st5 and st5["loopback"].verdict == "pass", "7 patterns on S5 (G3 never driven)"


def test_declared_source_must_match(sim):
    s = sim(source="3.0A")
    s.cfg.source = "1.5A"
    run = s.go()
    assert run.verdict == "FAIL"
    assert "advertisement as the operator declared" in names(s.checks("typec", "fail"))
    s = sim(source="default")
    s.cfg.source = "typeA"
    assert s.go().verdict.startswith("PASS")


def test_host_configures_on_request(sim):
    s = sim(usb="unconfigured")
    run = s.go()
    assert run.verdict.startswith("PASS"), s.failed()
    assert ("confirm", "host") in [(k, key) for k, key, _t in s.op.asked]


def test_no_host_means_no_slot_power(sim):
    s = sim(usb="unconfigured", operator={"host": False})
    run = s.go()
    assert run.verdict == "FAIL" and run.stop["kind"] == "abort"
    assert not any(st.id.startswith("slot") for st in run.steps), "SPEC §3.2: no slot before configuration"
    assert not any(line.startswith("tb slot 1 on") for line in s.sent())


# --- the faults the task names -----------------------------------------------------------------------------------
def test_dead_rail(sim):
    s = sim("dead_rail=+3V3_S1")
    run = s.go()
    assert run.verdict == "FAIL" and run.stop is None
    assert s.step("slot1.on").status == "fail"
    diag = next(c for c in s.checks("slot1.on") if c.name == "diagnosis")
    assert "dead rail" in diag.detail and "JP_3V3_S1" in diag.detail
    assert s.step("slot1.selftest").status == "skipped"
    assert s.step("slot1.off").status == "pass" and s.step("final").status == "pass"


def test_missing_monitor(sim):
    s = sim("missing_monitor=0x44")
    run = s.go()
    assert run.verdict == "FAIL"
    assert "INA226 0x44 (+3V3_S1) identified" in names(s.checks("boot", "fail"))
    assert "INA226 0x44 (+3V3_S1) reads" in names(s.checks("monitors", "fail"))
    assert any(c.measured == "monitor" for c in s.checks("slot1.on", "fail"))


@pytest.mark.parametrize("addr,rail", [(0x40, "VSYS"), (0x41, "+3V3_MCU"), (0x4D, "+5V_S5")])
def test_other_missing_monitors(sim, addr, rail):
    s = sim(f"missing_monitor=0x{addr:02x}")
    assert s.go().verdict == "FAIL"
    assert f"INA226 0x{addr:02x} ({rail}) reads" in names(s.checks("monitors", "fail"))


def test_tripping_slot_stops_the_run(sim):
    s = sim("short=+3V3_S1:400")
    run = s.go()
    assert run.verdict == "STOPPED" and run.stop["kind"] == "danger" and run.stop["safe"] is True
    assert "slot1.on" in run.stop["reason"]
    assert s.step("slot1.on").status == "danger"
    assert all(st.status == "not_run" for st in run.steps if st.id in ("slot1.desc", "slot1.selftest", "final"))
    sent = s.sent()
    assert sent.index("tb safe", sent.index("tb slot 1 on")) > 0, "tb safe after the trip"
    assert not s.dev.on


def test_overcurrent_later_stops_on_the_event(sim):
    s = sim("late_load=+3V3_S1:3:400")
    run = s.go()
    assert run.verdict == "STOPPED"
    assert "event trip finding=switch_limit" in run.stop["reason"]


def test_overcurrent_event_found_by_replay_when_lines_are_lost(sim):
    """The trip happens during a plain reading (tb ina), its event line is lost, and the firmware turns the slot
    off. The harness must learn of it from the ring before it sends anything that powers the slot again: the
    self-test's power step calls tb_slot_on() on an off slot (src/coupon_test.c), so without the replay it would
    re-power a slot that has just tripped."""
    s = sim("late_load=+3V3_S1:3:400", "drop_events")
    run = s.go()
    assert run.verdict == "STOPPED" and "switch_limit" in run.stop["reason"]
    sent = s.sent()
    tr = s.session.transcript
    trip_at = next(i for i, (_ts, d, t) in enumerate(tr) if d == "<" and "finding=switch_limit" in t)
    asked = [t for _ts, d, t in tr[:trip_at] if d == ">"][-1]
    assert asked.startswith("tb ev "), f"the trip line came only from the ring, in reply to {asked!r}"
    after = [t for _ts, d, t in tr[trip_at:] if d == ">"]
    assert after[:1] == ["tb safe"], f"the first command after the replay that showed the trip: {after[:3]}"
    assert not any(line.startswith("tb selftest") for line in sent), "no self-test on a slot that tripped"
    assert run.stop["reason"].startswith("slot1.desc"), "seen as soon as tb desc found the slot off"


def test_power_commands_replay_the_ring_before_and_after(sim):
    s = sim()
    s.go()
    sent = s.sent()
    for i, line in enumerate(sent):
        if line.startswith(("tb slot 1 on", "tb selftest", "tb slot 1 off")):
            assert sent[i - 1].startswith("tb ev "), (line, sent[i - 1])
            assert sent[i + 1].startswith("tb ev "), (line, sent[i + 1])


@pytest.mark.parametrize("how,token", [("crc", "crc"), ("magic", "magic"), ("version", "version")])
def test_bad_descriptor(sim, how, token):
    s = sim(f"bad_descriptor=1:{how}")
    run = s.go()
    assert run.verdict == "FAIL" and run.stop is None
    fails = s.checks("slot1.on", "fail")
    assert any(c.measured == token for c in fails)
    host = next(c for c in fails if c.name == "host check of the dumped image")
    assert host.measured == ("unknown magic" if how == "magic" else f"PCKD {token}")
    assert "tb slot 1 on nodesc ma3=120" in s.sent() and "tb desc 1" in s.sent(), "dumped on the record's 120 mA"


def test_compiler_format_descriptor_is_named(sim):
    s = sim("bad_descriptor=1:pckc")
    s.go()
    host = next(c for c in s.checks("slot1.on") if c.name == "host check of the dumped image")
    assert host.measured.startswith("PCKC") and "SPEC §11 #18" in host.detail


def test_descriptor_over_the_rule(sim):
    s = sim("bad_descriptor=1:over_rule")
    s.go()
    assert any(c.measured == "over_3v3_rule" for c in s.checks("slot1.on", "fail"))


def test_blank_descriptor_without_and_with_writing(sim):
    s = sim("bad_descriptor=1:blank")
    assert s.go().verdict == "FAIL"
    assert "--write-descriptor" in next(c for c in s.checks("slot1.on", "fail")).detail
    s = sim("bad_descriptor=1:blank", write_descriptor=4242)
    run = s.go()
    assert run.verdict.startswith("PASS"), s.failed()
    assert run.slots[1]["coupon_serial"] == 4242
    assert "tb desc 1 write test serial=4242" in s.sent()


def test_wrong_divider(sim):
    s = sim("wrong_divider=1:2:0.55")
    run = s.go()
    assert run.verdict == "FAIL"
    lanes = {c.name: c for c in s.checks("slot1.lanes")}
    assert lanes["AN2 divider"].verdict == "fail" and lanes["AN0 divider"].verdict == "pass"
    assert lanes["AN2: firmware verdict == harness verdict"].verdict == "pass", "both see it"
    assert {c.name for c in s.checks("slot1.selftest", "fail")} >= {"lanes", "self-test result"}


def test_firmware_that_misjudges_a_lane_is_caught(sim):
    s = sim("wrong_divider=1:1:0.43", "lane_ok_bug")
    s.go()
    bad = names(s.checks("slot1.lanes", "fail"))
    assert "AN1 divider" in bad and "AN1: firmware verdict == harness verdict" in bad


def test_loopback(sim):
    s = sim("stuck_loopback=1:0x0100")
    s.go()
    lb = next(c for c in s.checks("slot1.selftest") if c.name == "loopback")
    assert lb.verdict == "fail" and "p0_rx" in lb.detail


# --- current limits ----------------------------------------------------------------------------------------------
def test_switch_limiting_too_high_is_dangerous(sim):
    s = sim("climit=+3V3_S1:400", climit=True)
    run = s.go()
    assert run.verdict == "STOPPED" and "climit3" in run.stop["reason"]


def test_switch_limiting_too_low_fails(sim):
    s = sim("climit=+3V3_S1:200", climit=True)
    run = s.go()
    assert run.verdict == "FAIL" and run.stop is None
    assert "climit3" in names(s.checks("slot1.selftest", "fail"))


def test_fault_line_stuck_is_dangerous_with_climit(sim):
    s = sim("fault_n_stuck", climit=True)
    run = s.go()
    assert run.verdict == "STOPPED"


def test_climit_needs_the_budget(sim):
    s = sim(source="default", climit=True)
    s.go()
    c = next(c for c in s.checks("slot1.selftest") if c.name == "climit5")
    assert c.verdict == "fail" and "budget" in c.detail


# --- the firmware's timing finding -------------------------------------------------------------------------------
def test_stale_first_reading_is_diagnosed_and_worked_around(sim):
    """README finding 1: the firmware's settle check reads a stale INA226 result. The harness proves the rail is
    fine with a fresh reading, then retries with the slot's monitors at 2.2 ms results, and restores them."""
    s = sim("stale_ina=+3V3_S1", climit=True)
    run = s.go()
    assert run.verdict == "PASS (with warnings)", s.failed()
    on = {c.name: c for c in s.checks("slot1.on")}
    assert on["slot on"].verdict == "warn" and on["slot on"].measured == "low_3v3"
    assert on["diagnosis"].verdict == "warn" and "stale INA226 result" in on["diagnosis"].detail
    assert on["retried with the monitors at 2.2 ms"].verdict == "pass"
    sent = s.sent()
    i = sent.index("tb ina cfg +3V3_S1 1 1100 1100 7")
    assert sent[i + 1] == "tb ina cfg +5V_S1 1 1100 1100 7"
    assert sent[i + 2].startswith("tb ev ") and sent[i + 3] == "tb slot 1 on", "the ring replayed, then the retry"
    assert "tb ina cfg +3V3_S1 16 1100 1100 7" in sent[i + 2:], "the default configuration is restored"
    assert s.step("slot1.selftest").status == "pass"


def test_stale_reading_without_the_workaround_fails(sim):
    s = sim("stale_ina=+3V3_S1", retry_stale=False)
    assert s.go().verdict == "FAIL"
    assert s.step("slot1.selftest").status == "skipped"


def test_a_dead_rail_is_not_retried(sim):
    s = sim("dead_rail=+3V3_S1")
    s.go()
    assert not any(line.startswith("tb ina cfg") for line in s.sent())


# --- the board around the slots -------------------------------------------------------------------------------------
def test_missing_u_exp1_aborts(sim):
    s = sim("missing_expander=0x20")
    run = s.go()
    assert run.verdict == "FAIL" and run.stop["kind"] == "abort" and "U_EXP1" in run.stop["reason"]


def test_missing_mux(sim):
    s = sim("missing_mux")
    s.go()
    assert "mux TCA9548A at 0x70" in names(s.checks("boot", "fail"))
    assert any(c.measured == "desc_bus" for c in s.checks("slot1.on", "fail"))


def test_missing_u_cc(sim):
    s = sim("cc_absent")
    run = s.go()
    assert "U_CC at 0x67" in names(s.checks("typec", "fail"))
    assert run.info["budget_ma"] == 500, "SPEC §3.2: no answer on I2C gives the Default level"


def test_base_load(sim):
    assert sim("vsys_idle_ma=150").go().verdict == "FAIL"
    run = sim("vsys_idle_ma=250").go()
    assert run.verdict == "STOPPED" and "VSYS idle current" in run.stop["reason"]


def test_back_powered_rail(sim):
    run = sim("live_off=+5V_S2:2000").go()
    assert run.verdict == "STOPPED" and "rail_live_off" in run.stop["reason"]


# --- the harness judges the raw numbers itself, not only the firmware's verdicts -------------------------------
def test_back_powered_rail_seen_without_the_classifier(sim):
    """The firmware's board service is stuck (no trip events): the harness's own reading of every off rail in the
    monitors step must still stop the run."""
    run = sim("live_off=+5V_S2:2000", "quiet_service").go()
    assert run.verdict == "STOPPED"
    assert run.stop["reason"].startswith("monitors: +5V_S2 off"), run.stop["reason"]
    assert run.stop["safe"] is False and run.stop["safe_detail"]["live"] == ["+5V_S2"], \
        "tb safe cannot turn off what back-powers a rail: the board is not called safe"


def test_coupon_drawing_more_than_it_declares(sim):
    """140 mA extra on +3V3_S1: about 141 mA against the test coupon's 120 mA declaration, under the switch's
    256 mA minimum trip (so the firmware's over_3v3 check passes it) and under the classifier's 80 % floor (so no
    trip event). Only the harness's declaration margin (120 x 1.1 + 1 = 133 mA) catches it."""
    run = sim("short=+3V3_S1:140", "quiet_service").go()
    assert run.verdict == "STOPPED"
    assert run.stop["reason"].startswith("slot1.on: +3V3_S1 current"), run.stop["reason"]


def test_wrong_cal(sim):
    """An INA226 holding another CAL than SPEC §3.4's (CAL = 0.00512 / (LSB x R)): its current register is off by
    the same factor. Both the boot report and every reading show it."""
    s = sim("wrong_cal=0x44:2000")
    run = s.go()
    assert run.verdict == "FAIL"
    assert "INA226 0x44 CAL" in names(s.checks("boot", "fail"))
    assert "0x44 CAL" in names(s.checks("monitors", "fail"))
    assert "INA226 0x45 CAL" not in names(s.checks("boot", "fail"))


def test_firmware_budget_not_nets(sim):
    """The firmware gives 3000 mA for a 1.5 A source (a budget table that is not nets.vsys_budget's)."""
    s = sim("budget_ma=3000", source="1.5A")
    run = s.go()
    assert run.verdict == "FAIL"
    assert "VSYS budget for the advertisement" in names(s.checks("typec", "fail"))
    assert "configured budget" in names(s.checks("usb", "fail"))


def test_firmware_budget_as_nets(sim):
    s = sim("budget_ma=1500", source="1.5A")
    assert s.go().verdict.startswith("PASS"), s.failed()


# --- protocol trouble --------------------------------------------------------------------------------------------
def test_noisy_console(sim):
    assert sim("noisy").go().verdict.startswith("PASS")


def test_a_command_without_done_line(sim):
    s = sim("hang=lanes")
    run = s.go()
    assert s.step("slot1.lanes").status == "error"
    assert s.step("slot1.selftest").status == "pass", "the session resynced and went on"
    assert run.verdict == "FAIL"


def test_a_power_command_without_done_line_stops(sim):
    run = sim("hang=slot").go()
    assert run.verdict == "STOPPED" and "state is unknown" in run.stop["reason"]


def test_safe_that_never_answers(sim):
    run = sim("short=+3V3_S1:400", "hang=safe").go()
    assert run.verdict == "STOPPED" and run.stop["safe"] is False and "REMOVE POWER" in run.stop["advice"]


def test_other_protocol_version(sim):
    run = sim("proto=2").go()
    assert run.verdict == "FAIL" and "protocol 2" in run.stop["reason"]
    assert len(run.steps) == 1


def test_board_map_from_another_checkout(sim):
    s = sim("map_hash=0000000000000000")
    assert s.go().verdict.startswith("PASS")
    assert "board map hash" in names(s.checks("link", "warn"))
    s = sim("map_hash=0000000000000000", strict_map=True)
    assert s.go().verdict == "FAIL"


def test_link_lost(sim):
    s = sim()
    real = s.dev.readline
    count = {"n": 0}

    def flaky():
        count["n"] += 1
        if count["n"] > 120:
            from tbbench.protocol import LinkLost
            raise LinkLost("unplugged")
        return real()
    s.dev.readline = flaky
    run = s.go()
    assert run.verdict == "STOPPED" and run.stop["kind"] == "link_lost" and "by hand" in run.stop["advice"]


# --- bench-only steps --------------------------------------------------------------------------------------------
def test_bench_mode_needs_a_bench_build(sim):
    run = sim(usb="unconfigured", power="bench", bench_ma=1000, console="uart").go()
    assert run.verdict == "FAIL" and "bench-supply build" in run.stop["reason"]


def test_nrst_restore(sim):
    s = sim(usb="unconfigured", bench_build=True, power="bench", bench_ma=1000, console="uart", nrst=True)
    run = s.go()
    assert run.verdict.startswith("PASS"), s.failed()
    nr = {c.name: c for c in s.checks("nrst")}
    assert nr["reset cause"].verdict == "pass" and nr["U_EXP1 kept its outputs through the reset"].verdict == "pass"
    assert nr["U_EXP1 was driving"].verdict == "pass"


def test_nrst_restore_failure(sim):
    s = sim("nrst_restore_fail", usb="unconfigured", bench_build=True, power="bench", bench_ma=1000,
            console="uart", nrst=True)
    run = s.go()
    assert run.verdict == "FAIL" and s.failed() == {"monitors": "warn", "nrst": "fail", "slot1.desc": "warn"}
    assert names(s.checks("nrst", "fail")) == ["U_EXP1 restored", "boot restore"]


def test_nrst_skipped_on_cdc(sim):
    s = sim(console="cdc", nrst=True)
    s.go()
    assert s.checks("nrst")[0].verdict == "skip"


def test_meter_disagreement(sim):
    s = sim(meter=True, operator={"meter_i_S1": 2.5})
    s.go()
    c = next(c for c in s.checks("slot1.meter") if c.name.startswith("+3V3_S1: INA226"))
    assert c.verdict == "fail"


def test_explicit_empty_slot_is_incomplete(sim):
    s = sim(slots=[2])
    run = s.go()
    assert run.verdict == "INCOMPLETE"
    assert s.step("slot2.on").checks[0].verdict == "skip"


def test_a_harness_bug_still_leaves_the_board_safe(sim, monkeypatch):
    s = sim()

    def boom(st, n):
        raise KeyError("a bug")
    monkeypatch.setattr(s.bench, "st_lanes", boom)
    run = s.go()
    assert run.verdict == "STOPPED" and run.stop["kind"] == "harness_error" and run.stop["safe"] is True
    assert "KeyError" in run.stop["reason"] and "Traceback" in run.stop["traceback"]
    assert not s.dev.on


def test_operator_interrupt_makes_the_board_safe(sim, monkeypatch):
    s = sim()

    def stop(st, n):
        raise KeyboardInterrupt
    monkeypatch.setattr(s.bench, "st_selftest", stop)
    run = s.go()
    assert run.verdict == "STOPPED" and run.stop["kind"] == "interrupted" and run.stop["safe"] is True
    assert not s.dev.on


def test_every_judged_reading_waits_for_two_fresh_results(limits):
    """SBOS547C: an INA226 changes its registers only when an averaged result is complete (35.2 ms here), so the
    harness sleeps two result periods before every reading it judges after a power change."""
    from .conftest import Sim
    s = Sim(limits)
    sleeps = []
    s.bench.sleep = sleeps.append
    s.go()
    assert sleeps and min(sleeps) >= 2 * 0.0352
    n_ina = sum(1 for line in s.sent() if line.startswith("tb ina "))
    assert len(sleeps) >= n_ina


def test_switch_stuck_on_is_not_called_safe(sim):
    """A switch that ignores its enable keeps +3V3_S1 live after tb slot 1 off. The harness's own read-back of the
    off rail stops the run, and tb safe is not taken as proof: the monitor still reads the rail live, so the report
    must say to remove power by hand, naming the rail."""
    run = sim("stuck_on=+3V3_S1", "quiet_service").go()
    assert run.verdict == "STOPPED"
    assert run.stop["reason"].startswith("slot1.off: +3V3_S1 is off"), run.stop["reason"]
    assert run.stop["safe"] is False and run.stop["safe_detail"]["live"] == ["+3V3_S1"]
    assert "REMOVE POWER NOW" in run.stop["advice"] and "+3V3_S1 still read live" in run.stop["advice"]


def test_stuck_switch_seen_by_the_classifier_too(sim):
    run = sim("stuck_on=+3V3_S1").go()
    assert run.verdict == "STOPPED" and "rail_live_off" in run.stop["reason"] and run.stop["safe"] is False


def test_safe_needs_every_switched_monitor(sim):
    """An abort with a switched rail's monitor silent: that rail cannot be read dead, so the board is not called
    safe (missing U_EXP1 aborts; tb safe's read-back fails too)."""
    s = sim("missing_expander=0x20")
    run = s.go()
    assert run.stop["kind"] == "abort" and run.stop["safe"] is False and "REMOVE POWER" in run.stop["advice"]
    s = sim("missing_monitor=0x49", usb="unconfigured", operator={"host": False})
    run = s.go()
    assert run.stop["kind"] == "abort" and run.stop["safe"] is False
    assert run.stop["safe_detail"]["unread"] == ["+5V_S1"] and "+5V_S1 did not answer" in run.stop["advice"]


def test_converters_that_disagree(sim):
    """ADC4 reads S1's AN2 5000 ppm off ADC1 (over the 3000 ppm agreement): the harness's own comparison names it."""
    s = sim("adc_disagree=1:2:4:5000")
    run = s.go()
    assert run.verdict == "FAIL"
    lanes = {c.name: c for c in s.checks("slot1.lanes")}
    assert lanes["AN2 on ADC4 agrees"].verdict == "fail" and lanes["AN2 on ADC2 agrees"].verdict == "pass"
    assert "lanes" in names(s.checks("slot1.selftest", "fail"))


def test_a_shortened_loopback_is_not_a_pass(sim):
    """The self-test runs 6 of its 8 patterns and calls the loopback passed: the pattern count fails it."""
    s = sim("short_loopback=1:6")
    s.go()
    lb = {c.name: c for c in s.checks("slot1.selftest")}
    assert lb["loopback"].verdict == "fail" and "6 patterns, 0 failed" in lb["loopback"].detail
    assert lb["loopback: firmware verdict == harness verdict"].verdict == "fail"


def test_firmware_descriptor_parser_that_disagrees(sim):
    """The firmware's desc record says +3V3 200 mA where the EEPROM's bytes say 120: the host's parse of the dumped
    bytes catches the firmware's parser."""
    s = sim("desc_parse_bug=1:i3v3_ma:200")
    s.go()
    bad = names(s.checks("slot1.desc", "fail"))
    assert "i3v3_ma: host == firmware" in bad and "serial: host == firmware" not in bad


def test_stale_generated_board_map(sim, monkeypatch):
    """The checkout's tb_board_map.h is older than nets.py: the harness says so, and still compares the firmware's
    hash with the one nets.py gives."""
    from tbbench import limits as L
    monkeypatch.setattr(L, "map_hash", lambda path=None: "0123456789abcdef")
    s = sim()
    s.go()
    warn = {c.name: c for c in s.checks("link", "warn")}
    assert "generated board map current" in warn and "board map hash" not in warn
    s = sim("map_hash=0123456789abcdef")
    s.go()
    c = next(c for c in s.checks("link") if c.name == "board map hash")
    assert c.verdict == "warn" and "stale header" in c.detail


# --- the review of 2026-11-28: every power-on judged, a declared coupon looked for -------------------------------
def test_a_late_over_draw_under_the_floor_is_stopped_by_the_alert(sim):
    """150 mA appearing after slot on: over the declaration's alert (133 mA), under the 205 mA switch_limit floor.
    The firmware's INA226 alert turns it off (seen on native_sim, 2026-11-28); the simulator models that alert."""
    run = sim("late_load=+3V3_S1:4:150").go()
    assert run.verdict == "STOPPED" and "finding=alert" in run.stop["reason"], run.stop
    assert run.stop["safe"] is True


def test_a_late_over_draw_is_seen_without_the_firmwares_alert(sim):
    """The same with the board service stuck: the harness's own reading before the self-test stops the run, and no
    self-test (loads, current limits) is sent to a slot that over-draws."""
    s = sim("late_load=+3V3_S1:4:150", "quiet_service")
    run = s.go()
    assert run.verdict == "STOPPED" and run.stop["reason"] == "slot1.selftest: +3V3_S1 current before the self-test"
    assert not any(x.startswith("tb selftest") for x in s.sent())


def test_an_over_draw_after_the_self_test_is_seen_in_tb_trips(sim):
    run = sim("late_load=+3V3_S1:9:150", "quiet_service").go()
    assert run.verdict == "STOPPED" and run.stop["reason"] == "slot1.trips: +3V3_S1 current (tb trips)", run.stop


def test_an_off_rail_feeding_backwards_is_live(sim):
    """-8 mA through an off rail's shunt (current flowing back from the coupon side). The firmware's classifier
    compares the signed current (lib/src/trip.c) and says nothing; the harness takes its magnitude."""
    run = sim("live_off_ua=+3V3_S2:-8000").go()
    assert run.verdict == "STOPPED" and run.stop["reason"].startswith("monitors: +3V3_S2 off"), run.stop
    assert run.stop["safe"] is False and run.stop["safe_detail"]["live"] == ["+3V3_S2"]


def test_a_refused_descriptor_is_dumped_on_its_records_current_and_judged(sim):
    s = sim("bad_descriptor=1:crc", "short=+3V3_S1:150", "quiet_service")
    run = s.go()
    assert run.verdict == "STOPPED" and run.stop["reason"] == "slot1.on: +3V3_S1 current for the descriptor dump"
    assert "tb slot 1 on nodesc ma3=120" in s.sent() and "tb desc 1" not in s.sent()


def test_the_keep_phase_of_a_descriptor_write_is_judged(sim):
    """+3V3 alone, the lines high-impedance: the only moment the harness can judge the coupon before tb slot on
    brings +5V up with +3V3. A blank test coupon that over-draws is stopped before its descriptor is written."""
    s = sim("short=+3V3_S1:150", "quiet_service", coupons={1: "blank"}, write_descriptor=7)
    run = s.go()
    assert run.verdict == "STOPPED"
    assert run.stop["reason"] == "slot1.on: +3V3_S1 current with +3V3 alone, before the write", run.stop
    assert not any(x.startswith("tb desc 1 write") for x in s.sent())


def test_the_nrst_test_judges_the_rail_before_the_reset(sim):
    s = sim("short=+3V3_S1:150", "quiet_service", usb="unconfigured", bench_build=True, power="bench",
            bench_ma=1000, console="uart", nrst=True)
    run = s.go()
    assert run.verdict == "STOPPED" and run.stop["reason"] == "nrst: +3V3_S1 current for the reset test", run.stop
    assert "nrst" not in [k for _kind, k, _t in s.op.asked]


def test_a_stop_in_the_stale_retry_goes_straight_to_tb_safe(sim):
    """The retry of finding 1 (monitors at 2.2 ms) over-draws: nothing but the event replay may come between it
    and tb safe (the monitors' configuration is not restored first)."""
    s = sim("stale_ina=+3V3_S1", "short=+3V3_S1:140")
    run = s.go()
    assert run.verdict == "STOPPED" and "finding=alert" in run.stop["reason"], run.stop
    sent = s.sent()
    retry = max(i for i, x in enumerate(sent) if x == "tb slot 1 on")
    assert [x for x in sent[retry + 1:] if not x.startswith("tb ev ")][0] == "tb safe", sent[retry:]


def test_a_declared_coupon_that_does_not_read_present_fails(sim):
    """--coupon 2=hall with S2 empty (or the coupon not seated): the run must not pass on S1 alone."""
    s = sim(coupons={1: "test"})
    s.cfg.coupons = {2: "hall"}
    run = s.go()
    assert run.verdict == "FAIL"
    assert [c.name for c in s.checks("slot2.on", "fail")] == ["the declared coupon reads present"]


def test_plus_5v_is_judged_against_vsys_as_it_reads_now(sim):
    """VSYS 60 mV lower than at the monitors step by the time S1 is on (a host port sharing its supply): +5V_S1
    follows it, and its window must too."""
    s = sim()
    orig = s.dev._command

    def command(line):
        if line == "tb slot 1 on":
            s.dev.f.vsys_drop_mv = 60
        orig(line)
    s.dev._command = command
    run = s.go()
    assert run.verdict.startswith("PASS"), s.failed()
    assert not s.checks("slot1.on", "fail")
