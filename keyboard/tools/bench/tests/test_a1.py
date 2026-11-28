"""The owner's decisions of 2026-11-27 as the harness walks them, against the simulated board.

D1: rev A in two stages; A1 = the motherboard, the test coupon and the Hall coupon, the test coupon's slots first.
D2: the slot key at pin 39 (a turned coupon must stay out; risks.md EL-2's test with the coupon in turned).
D4: VSYS against the USB-C load line, VSYS_PG's margin.
D7: INJ into the test coupon's AN0 lane.
Plus the descriptor checked against its descriptor of record through keyboard/tools/coupon/descriptor.py.

What these prove: the harness's sequencing, its arithmetic and its stop paths against a model of the protocol. Not
the board: the model's numbers are placeholders, and the INJ lift is the sheet's estimate.
"""

import pytest

from tbbench import desc_check
from tbbench import limits as L
from tbbench import simdev


def names(checks):
    return [c.name for c in checks]


def by_name(checks):
    return {c.name: c for c in checks}


BENCH = dict(usb="unconfigured", bench_build=True, power="bench", bench_ma=1000, console="uart")


# --- D1: A1 first, the test coupon's slots before the Hall coupon's ---------------------------------------------
def test_a1_order_test_coupon_slots_first(sim):
    s = sim(coupons={1: "hall", 2: "test", 4: "test"}, climit=True)
    s.cfg.coupons = {1: "hall"}
    run = s.go()
    assert run.verdict == "PASS (with warnings)", s.failed()
    order = [st.id.split(".")[0] for st in run.steps if st.id.startswith("slot")]
    assert list(dict.fromkeys(order)) == ["slot2", "slot4", "slot1"], "SPEC §10 step 7 before step 8"
    assert "slot1.selftest" not in [st.id for st in run.steps], "the Hall coupon has no self-test"
    assert s.step("slot1.on").spec.startswith("SPEC §10 step 8 (A1)")
    assert s.step("slot2.on").spec.startswith("SPEC §10 step 7")
    assert run.slots[1]["coupon_declared"] == "hall" and run.slots[1]["coupon_type"] == "hall"
    assert s.max_slot_rails == 1


def test_hall_coupon_with_a_firmware_descriptor(sim):
    """The firmware's own Hall descriptor (as its native_sim world writes it: +3V3 40 mA) against compiler v0's
    record (45 mA): read, judged, and the difference named."""
    s = sim(coupons={1: "hall"})
    s.cfg.coupons = {1: "hall"}
    run = s.go()
    assert run.verdict == "PASS (with warnings)", s.failed()
    d = by_name(s.checks("slot1.desc"))
    assert d["descriptor of record valid (descriptor.py)"].verdict == "pass"
    assert d["declared +3V3 as its descriptor of record"].verdict == "warn"
    assert d["declared +3V3 as its descriptor of record"].measured == "EEPROM 40, record 45"
    assert all(c.verdict == "info" for c in s.checks("slot1.lanes") if c.name.startswith("AN") and "agrees" not in
               c.name), "the Hall coupon's lanes are recorded, not judged"


def test_hall_coupon_with_a_blank_eeprom_runs_on_its_record(sim):
    """A1's Hall coupon arrives with a blank EEPROM and the firmware can write only the test coupon's descriptor:
    the harness powers it on the currents of its descriptor of record (descriptor.py), never writes a test
    descriptor onto it, and says so."""
    s = sim("bad_descriptor=1:blank", coupons={1: "hall"}, write_descriptor=7)
    s.cfg.coupons = {1: "hall"}
    run = s.go()
    assert run.verdict == "PASS (with warnings)", s.failed()
    sent = s.sent()
    assert "tb slot 1 on nodesc ma3=45" in sent
    assert not any("write test" in line for line in sent), "a test descriptor written onto a Hall coupon"
    on = by_name(s.checks("slot1.on"))
    assert on["powered on its descriptor of record"].verdict == "warn"
    assert on["descriptor of record valid (descriptor.py)"].verdict == "pass"
    assert by_name(s.checks("slot1.desc"))["the coupon's EEPROM"].verdict == "warn"
    assert run.slots[1]["descriptor_record"]["facts"]["i3v3_ma"] == 45


def test_hall_coupon_with_compiler_v0s_image(sim):
    """make_eeprom.py's PCKC image on a Hall coupon: the firmware refuses its magic; the dump is named (a warning,
    not a damaged image) and the coupon runs on its descriptor of record."""
    s = sim("bad_descriptor=1:pckc", coupons={1: "hall"})
    s.cfg.coupons = {1: "hall"}
    run = s.go()
    assert run.verdict == "PASS (with warnings)", s.failed()
    host = by_name(s.checks("slot1.on"))["host check of the dumped image"]
    assert host.verdict == "warn" and host.measured.startswith("PCKC")
    assert "tb slot 1 on nodesc ma3=45" in s.sent()


def test_hall_coupon_never_powered_on_its_record_after_a_bus_error(sim):
    """No answer from the EEPROM may be a coupon plugged in turned: nodesc would drive its lines. Never."""
    s = sim("missing_mux", coupons={1: "hall"})
    s.cfg.coupons = {1: "hall"}
    s.go()
    assert not any("nodesc" in line for line in s.sent())
    assert any(c.measured == "desc_bus" for c in s.checks("slot1.on", "fail"))


def test_a_coupon_that_is_not_the_declared_one(sim):
    s = sim()
    s.cfg.coupons = {1: "hall"}
    run = s.go()
    assert run.verdict == "FAIL"
    assert "coupon type" in names(s.checks("slot1.desc", "fail"))


def test_an_a2_coupon_is_named(sim):
    s = sim()
    s.dev.coupons[1].eeprom = simdev.pckd_encode(5, 100, 0, serial=3).ljust(256, b"\xff")
    run = s.go()
    assert run.verdict == "FAIL"
    c = by_name(s.checks("slot1.desc"))["coupon type"]
    assert c.verdict == "fail" and c.measured == "coil" and "A2 coupon" in c.detail


def test_descriptor_of_record_missing_fails(sim, monkeypatch, tmp_path):
    monkeypatch.setitem(L.DESCRIPTOR_RECORDS, "test", tmp_path / "nowhere.json")
    s = sim()
    s.go()
    c = by_name(s.checks("slot1.desc"))["descriptor of record valid (descriptor.py)"]
    assert c.verdict == "fail" and "not found" in c.detail


# --- the descriptor of record through descriptor.py -------------------------------------------------------------
def test_record_of_each_a1_coupon_is_valid():
    for kind in L.A1_COUPONS:
        rec = desc_check.record(kind)
        assert rec.valid, rec.problems
        assert rec.facts["type"] == kind and rec.facts["bytes"] == 256
    assert desc_check.record("test").facts["ratios"] == pytest.approx([0.2, 0.4, 0.6, 0.8], abs=1e-6)


def test_record_that_descriptor_py_refuses(tmp_path):
    import json
    d = json.loads(L.DESCRIPTOR_RECORDS["test"].read_text())
    d["rails"]["+3V3"]["max_ma"] = 70000            # out of descriptor.py's range for the field
    bad = tmp_path / "test-coupon.json"
    bad.write_text(json.dumps(d))
    rec = desc_check.record("test", records={"test": bad})
    assert not rec.valid and "descriptor.py refuses it" in rec.problems[0]
    assert not desc_check.record("coil").valid, "A2's coupons have no record in this harness"


# --- D7: INJ into the AN0 lane ------------------------------------------------------------------------------------
def test_inj_lifts_an0_and_the_taps_follow(sim):
    s = sim(inj=True)
    run = s.go()
    assert run.verdict == "PASS (with warnings)", s.failed()
    c = by_name(s.checks("slot1.inj"))
    assert c["AN0 lift with INJ high"].verdict == "pass" and 430 <= c["AN0 lift with INJ high"].measured <= 580
    for k in (1, 2, 3):
        assert c[f"AN{k} follows AN0's lift"].verdict == "pass"
    assert c["AN0 back to its reading before INJ"].verdict == "pass"
    assert run.slots[1]["inj_lift_mv"] == c["AN0 lift with INJ high"].measured
    sent = s.sent()
    assert sent.index("tb selftest 1 loads") > max(i for i, x in enumerate(sent) if x == "tb lanes 1"), \
        "the self-test after INJ is low again"
    asked = [k for _kind, k, _t in s.op.asked]
    assert asked.index("inj_S1") < asked.index("inj_off_S1")


@pytest.mark.parametrize("fault,why", [("inj_open=1", "no lift"), ("inj_lift=1:0.75", "D11 shorted")])
def test_inj_path_faults(sim, fault, why):
    s = sim(fault, inj=True)
    run = s.go()
    assert run.verdict == "FAIL", why
    assert names(s.checks("slot1.inj", "fail")) == ["AN0 lift with INJ high"]
    assert s.step("slot1.selftest").status == "pass", "INJ low again: the self-test still runs"


def test_inj_into_the_wrong_tap(sim):
    """R40 on the AN1 tap instead of AN0's (a wrong net): AN0 then rises by half of AN1's lift, and the taps above
    no longer follow AN0 by 3/4, 1/2, 1/4."""
    s = sim("inj_tap=1:1", inj=True)
    s.go()
    assert names(s.checks("slot1.inj", "fail")) == ["AN0 lift with INJ high", "AN1 follows AN0's lift",
                                                   "AN2 follows AN0's lift", "AN3 follows AN0's lift"]


def test_inj_left_high_skips_the_self_test(sim):
    s = sim("inj_stuck=1", inj=True)
    run = s.go()
    assert run.verdict == "FAIL"
    assert "AN0 back to its reading before INJ" in names(s.checks("slot1.inj", "fail"))
    assert names(s.checks("slot1.selftest", "fail")) == ["INJ low before the self-test"]
    assert not any(line.startswith("tb selftest") for line in s.sent())


def test_inj_from_the_rig_left_on_back_feeds_the_coupon(sim):
    s = sim("inj_stuck=1", "inj_rig=1:3.3", inj=True)
    s.go()
    asked = [k for _kind, k, _t in s.op.asked]
    assert asked.count("inj_off_S1") == 2, "asked again before the slot goes off"
    off = by_name(s.checks("slot1.off"))
    assert off["+3V3_S1 not fed through INJ"].verdict == "fail" and off["+3V3_S1 is off"].verdict == "pass", \
        "0.87 V: under the 1 V live level, caught by the INJ check only"


def test_inj_skipped(sim):
    s = sim(inj=True, operator={"inj_S1": False})
    run = s.go()
    assert s.checks("slot1.inj")[0].verdict == "skip" and s.step("slot1.inj").status == "skipped"
    assert run.verdict == "INCOMPLETE", "asked for and not done"


def test_simulated_loopback_with_inj_high_truncates_like_the_firmware(limits):
    """src/coupon_test.c keeps a step's keys in 160 bytes: with INJ high every pattern fails and patterns= is lost.
    The harness then has no pattern count, and fails the loopback (it never takes a missing count as zero)."""
    dev = simdev.SimDevice(limits)
    dev.host_configure()
    dev.write(b"tb slot 1 on\n")
    dev.set_inj(1, "tp1")
    dev.write(b"tb selftest 1\n")
    out = "".join(iter(dev.readline, None))
    lb = next(x for x in out.splitlines() if "name=loopback" in x)
    assert "result=fail" in lb and "patterns=" not in lb and len(lb.split("result=fail ")[1]) <= simdev.KV_MAX


# --- D2: the key ----------------------------------------------------------------------------------------------
def test_key_check_passes_with_the_plug(sim):
    s = sim(key_check=True)
    run = s.go()
    assert run.verdict == "PASS (with warnings)", s.failed()
    assert by_name(s.checks("slot1.key"))["a turned test coupon stays out"].verdict == "pass"
    assert s.step("slot1.key").spec.startswith("SPEC §10 step 7, §4.2")


def test_key_check_finds_a_missing_plug(sim):
    s = sim("no_key_plug=1", key_check=True)
    run = s.go()
    assert run.verdict == "FAIL"
    assert names(s.checks("slot1.key", "fail")) == ["a turned test coupon stays out"]
    assert s.step("slot1.selftest").status == "pass", "put back the right way round, the slot is still tested"
    assert not s.dev.violations


def test_a_turned_coupon_is_refused_and_the_bus_freed(sim):
    """The key plug missing and the coupon in turned: the firmware's slot on gets no EEPROM answer and refuses it;
    the harness pulses the mux reset (tb safe) so the next slot's descriptor read works."""
    s = sim(coupons={1: "turned", 2: "test"})
    run = s.go()
    assert run.verdict == "FAIL"
    on = s.checks("slot1.on", "fail")
    assert any(c.measured == "desc_bus" and "turned 180 degrees" in c.detail for c in on)
    assert by_name(s.checks("slot1.on"))["tb safe after the bus error (MUX_RST_N pulsed, I2C4 free)"].verdict == "pass"
    assert s.step("slot2.selftest").status == "pass", "I2C4 free again for S2"
    assert not s.dev.violations, s.dev.violations


def test_turned_test_healthy_firmware(sim):
    s = sim(turned_test=3, **BENCH)
    run = s.go()
    assert run.verdict == "PASS (with warnings)", s.failed()
    c = by_name(s.checks("turned"))
    assert c["the firmware refuses the turned coupon"].verdict == "pass"
    assert c["no slot line driven into the turned coupon"].verdict == "pass"
    assert c["S3 left off"].verdict == "pass"
    assert not s.dev.violations, s.dev.violations
    assert 3 not in s.dev.coupons, "the turned coupon taken out again (S3 was empty)"


def test_turned_test_catches_lines_driven_before_the_descriptor(sim):
    s = sim("lines_before_desc", turned_test=1, **BENCH)
    run = s.go()
    assert run.verdict == "FAIL"
    assert names(s.checks("turned", "fail")) == ["no slot line driven into the turned coupon"]


def test_turned_test_needs_the_bench_supply(sim):
    s = sim(turned_test=1)
    run = s.go()
    assert s.checks("turned")[0].verdict == "skip" and run.verdict == "INCOMPLETE"
    assert not any(k.startswith("turned_in") for _kind, k, _t in s.op.asked)


# --- D4: VSYS ---------------------------------------------------------------------------------------------------
def test_vsys_below_the_usb_c_load_line_warns(sim):
    s = sim("vsys_drop_mv=400")
    run = s.go()
    assert run.verdict == "PASS (with warnings)"
    m = by_name(s.checks("monitors"))
    assert m["VSYS on or above the USB-C load line"].verdict == "warn"
    assert m["VSYS voltage"].verdict == "pass", "4.6 V: inside the 4.5-5.5 V window, outside the load line"
    assert m["VSYS above VSYS_PG's falling edge"].verdict == "info"


def test_vsys_load_line_not_applied_on_a_bench_supply(sim):
    s = sim("vsys_drop_mv=400", **BENCH)
    s.go()
    assert "VSYS on or above the USB-C load line" not in names(s.checks("monitors"))


def test_a_record_of_another_coupon_is_caught(sim, monkeypatch):
    """The descriptor of record the harness finds for "test" describes a Hall coupon (a misfiled JSON): the EEPROM's
    type no longer matches it, even though it matches the operator's declaration."""
    monkeypatch.setitem(L.DESCRIPTOR_RECORDS, "test", L.DESCRIPTOR_RECORDS["hall"])
    s = sim()
    s.go()
    d = by_name(s.checks("slot1.desc"))
    assert d["coupon type"].verdict == "pass"
    assert d["type as its descriptor of record"].verdict == "fail"
