"""The harness against the bring-up firmware itself, built for native_sim (keyboard/firmware/bringup/sim).

    source /root/zephyrproject/ENV.sh
    west build -b native_sim/native/64 keyboard/firmware/bringup -d <build>
    TB_SIM_EXE=<build>/zephyr/zephyr.exe python -m pytest keyboard/tools/bench/tests -q

Skipped without that build. This is the test that keeps the harness honest about the real firmware's output: the
same procedure the bench will run, against the firmware's own code, its own register models and its own sim
world, plus PROTOCOL.md conformance of every record the firmware printed and a comparison of the simulator's
records with the firmware's. After every run the firmware's own rule checker ("sim state": no line driven into an
unpowered or turned coupon, no rail before configuration, ...) must have counted no violation. It still tests no
hardware.
"""

import pytest

from tbbench.prompts import ScriptedOperator
from tbbench.procedure import Bench, RunConfig
from tbbench.protocol import Session, parse_line
from tbbench.transport import ProcessTransport

from . import protocol_doc as P
from .conftest import NATIVE_EXE, Sim

pytestmark = pytest.mark.skipif(not NATIVE_EXE.exists(), reason=f"no native_sim build at {NATIVE_EXE}")


def native(limits, sim_cmds=(), source="3.0A", answers=None, **cfg):
    """A run against the firmware on native_sim. answers: prompt key -> fn(session) (a person's action in the
    firmware's sim world, e.g. "sim coupon 3 turned"). s.sim_flags: the world's "sim state" flags afterwards."""
    t = ProcessTransport([str(NATIVE_EXE), "--uart_stdinout"])
    s = Session(t)
    s.drain(quiet_s=0.5, max_s=5.0)
    s.cmd(f"sim source {source}")
    for c in sim_cmds:
        s.cmd(c)

    def host(_k, _t):
        s.cmd("sim usb configured")
        return True
    ops = {"host": host, **{k: (lambda f: lambda _k, _t: f(s))(f) for k, f in (answers or {}).items()}}
    cfg.setdefault("console", "sim")
    cfg.setdefault("board_serial", "NATIVE")
    try:
        run = Bench(s, limits, RunConfig(**cfg), ScriptedOperator(ops)).run()
        s.sim_flags = s.cmd("sim state").first("flags")
    finally:
        t.close()
    assert s.sim_flags is not None and s.sim_flags.get("rule_violations") == 0, \
        f"the firmware's sim world counted a violation: {s.sim_flags}"
    return run, s


def sim_cmd(line):
    return lambda s: s.cmd(line).ok


def failed(run):
    return {x.id: x.status for x in run.steps if x.status not in ("pass", "skipped")}


def test_healthy(limits):
    run, _s = native(limits, climit=True)
    assert run.verdict == "PASS (with warnings)", failed(run)
    assert failed(run) == {"monitors": "warn", "slot1.desc": "warn"}, "README findings 1 and 3"
    assert run.slots[1]["series_mohm"] == 326 and run.slots[1]["coupon_serial"] == 1
    m = {c.name: c for st in run.steps if st.id == "monitors" for c in st.checks}
    assert m["VSYS on or above the USB-C load line"].verdict == "pass"


def test_a1_hall_coupon_after_the_test_coupon(limits):
    """The firmware's own Hall coupon model (a PCKD descriptor, 30 mA) declared hall in S2: S1's test coupon runs
    first, then S2 with its descriptor read and judged against compiler v0's record, its lanes recorded."""
    run, _s = native(limits, ["sim coupon 2 hall"], coupons={2: "hall"})
    assert run.verdict == "PASS (with warnings)", failed(run)
    ids = [x.id for x in run.steps]
    assert ids.index("slot1.off") < ids.index("slot2.on") and "slot2.selftest" not in ids
    assert run.slots[2]["coupon_type"] == "hall" and run.slots[2]["coupon_serial"] == 102


def test_a1_hall_coupon_with_a_blank_eeprom(limits):
    """A blank EEPROM in a slot declared hall: the firmware powers it on the descriptor of record's 45 mA (nodesc)
    and drives its lines only after the rail checks; its rule checker sees nothing wrong."""
    run, s = native(limits, ["sim coupon 2 blank"], coupons={2: "hall"})
    assert run.verdict == "PASS (with warnings)", failed(run)
    assert "tb slot 2 on nodesc ma3=45" in [t for _ts, d, t in s.transcript if d == ">"]


def test_turned_coupon_is_refused_without_a_line_driven(limits):
    """risks.md EL-2's test on the firmware itself: the test coupon in S3 turned 180 degrees (the key plug missing).
    The firmware must refuse it (desc_bus) and drive no line into it; the sim world's rule checker is the scope."""
    def driven(s):
        return s.cmd("sim state").first("flags").get("rule_violations") != 0
    run, _s = native(limits, power="bench", bench_ma=1000, turned_test=3,
                     answers={"turned_in_S3": sim_cmd("sim coupon 3 turned"),
                              "turned_out_S3": sim_cmd("sim coupon 3 none"), "turned_scope_S3": driven})
    assert run.verdict.startswith("PASS"), failed(run)
    c = {x.name: x for st in run.steps if st.id == "turned" for x in st.checks}
    assert c["the firmware refuses the turned coupon"].measured == "desc_bus"
    assert c["no slot line driven into the turned coupon"].verdict == "pass"
    assert c["tb safe after the bus error (MUX_RST_N pulsed, I2C4 free)"].verdict == "pass"


def test_a_turned_coupon_left_in(limits):
    run, _s = native(limits, ["sim coupon 1 turned"])
    assert run.verdict == "FAIL"
    on = [c for st in run.steps if st.id == "slot1.on" for c in st.checks]
    assert any(c.measured == "desc_bus" and c.verdict == "fail" for c in on)


def test_inj_cannot_be_driven_on_native_sim(limits):
    """The firmware's sim world keeps JP_INJ open (sim/world.c), so INJ never rises there: the harness's INJ step
    finds no lift, as it would on a board with D11 or R40 missing. The step's arithmetic on real records."""
    run, _s = native(limits, inj=True, answers={"inj_S1": lambda s: True, "inj_off_S1": lambda s: True})
    c = {x.name: x for st in run.steps if st.id == "slot1.inj" for x in st.checks}
    assert c["AN0 lift with INJ high"].verdict == "fail" and abs(c["AN0 lift with INJ high"].measured) < 5
    assert c["AN0 back to its reading before INJ"].verdict == "pass"


def test_bench_supply(limits):
    run, _s = native(limits, power="bench", bench_ma=1000, climit=True)
    assert run.verdict.startswith("PASS"), failed(run)


def test_overload_stops_and_everything_is_off(limits):
    run, s = native(limits, ["sim load +3V3_S1 400"])
    assert run.verdict == "STOPPED" and run.stop["safe"] is True, run.stop
    assert "slot1.on" in run.stop["reason"]


def test_blank_eeprom_is_written(limits):
    run, _s = native(limits, ["sim coupon 1 blank"], write_descriptor=42, loads=False)
    desc = next(x for x in run.steps if x.id == "slot1.desc")
    assert desc.status == "warn" and run.slots[1]["coupon_serial"] == 42
    assert [c.name for c in desc.checks if c.verdict != "pass"] == ["declared +5V as its descriptor of record"]
    # The firmware's sim world models a "blank" coupon without its ladder, loads or loopback even after the
    # descriptor is written (sim/world.c: sim_test_coupon_powered() is SIM_TEST only), so lanes and the
    # self-test fail here although the descriptor flow passed. A recommendation in the README, not asserted.


def test_coupon_in_another_slot(limits):
    run, _s = native(limits, ["sim coupon 1 none", "sim coupon 4 test"])
    assert run.verdict.startswith("PASS"), failed(run)
    assert list(run.slots) == [4]


def test_empty_board(limits):
    run, _s = native(limits, ["sim coupon 1 none"])
    assert run.verdict == "INCOMPLETE" and not run.slots


def test_firmware_records_follow_protocol_and_match_the_simulator(limits):
    run, s = native(limits, climit=True)
    fw = [r for r in (parse_line(t) for _ts, d, t in s.transcript if d == "<") if r is not None and r.space == "tb"]
    tmpl = P.templates()
    bad = {P.conforms(r, tmpl) for r in fw} - {None}
    assert not bad, sorted(bad)
    sim = Sim(limits, climit=True)
    sim.go()
    simrecs = [r for r in (parse_line(t) for _ts, d, t in sim.session.transcript if d == "<") if r is not None]
    fw_keys = {}
    for r in fw:
        fw_keys.setdefault(r.name, set()).add(tuple(r.fields))
    drift = set()
    for r in simrecs:
        if r.name in fw_keys and r.name not in ("ev", "step", "done") and tuple(r.fields) not in fw_keys[r.name]:
            drift.add((r.name, tuple(r.fields)))
    assert not drift, f"the simulator prints records the firmware prints differently: {sorted(drift)}"


def test_a_late_over_draw_is_turned_off_by_the_firmwares_alert(limits):
    """150 mA appearing after slot on, under the 205 mA switch_limit floor: the firmware's INA226 alert
    (src/board.c tb_rail_alert_ua(), declared x 1.1 + 1 mA) turns the slot off and the harness stops. The
    simulator models the same alert (tests/test_procedure.py); this holds it to the firmware."""
    run, _s = native(limits, inj=True, answers={"inj_S1": sim_cmd("sim load +3V3_S1 150"),
                                                "inj_off_S1": lambda s: True})
    assert run.verdict == "STOPPED" and run.stop["safe"] is True
    assert run.stop["reason"].startswith("slot1.inj: event trip finding=alert"), run.stop["reason"]


# The same command script on the firmware and on tbbench.simdev (the review of 2026-11-28): the done line (rc and
# err) and every record with its keys in order must agree, command by command. Events are left out: the firmware
# prints them from its own thread, so they land in a later command's output (the harness replays the ring).
DIFF_SCRIPT = [
    "tb info", "tb boot", "tb safe", "tb usb", "tb cc", "tb budget", "tb budget override 1000",
    "tb budget override off", "tb budget base 45", "tb budget bench 500", "tb budget foo 1", "tb budget override",
    "tb budget override abc", "tb budget base off", "tb ina", "tb ina all", "tb ina +3V3_S1", "tb ina 0x44",
    "tb ina vsys", "tb ina cfg +3V3_S1 16 1100 1100 7", "tb ina cfg all 3 1100 1100 7",
    "tb ina cfg +3V3_S1 16 1100 1100", "tb ina alert +3V3_S1 100", "tb ina alert +3V3_S1 off",
    "tb ina alert nope 100", "tb ina drv +3V3_S1", "tb ina drv nope", "tb exp", "tb rail +3V3_S1 on 100",
    "tb rail +3V3_S1 on 100", "tb rail +3V3_S1 off", "tb rail +3V3_S2 on 100", "tb rail +5V_S1 on 100",
    "tb rail +3V3_S1 on 300", "tb rail foo on 1", "tb rail +3V3_S1 bar", "tb rail +3V3_S1 on abc",
    "tb rail 3v3_s1 off", "tb slot", "tb slot 1", "tb slot 1 on", "tb slot 1 on", "tb desc 1", "tb lanes 1",
    "tb lanes", "tb lanes 9", "tb trips", "tb slot 1 off", "tb desc 1", "tb slot 2 on", "tb slot 9",
    "tb slot 1 on nodesc", "tb slot 1 on nodesc ma3=50", "tb slot 1 off", "tb slot 1 on probe=100",
    "tb slot 1 off", "tb slot 1 bogus", "tb selftest 1", "tb selftest 1 loads", "tb selftest 1 all",
    "tb selftest 2", "tb selftest x", "tb slot 1 on", "tb desc 1 write test serial=5",
    "tb desc 1 write test serial=5 force", "tb desc 1 write", "tb desc 1 foo", "tb slot 1 off", "tb trips apply",
    "tb mon", "tb mon period 100", "tb mon period", "tb mon x y", "tb ev abc",
    "@coupon 2 hall", "tb slot 2 on", "tb desc 2", "tb lanes 2", "tb selftest 2", "tb slot 2 off",
    "@coupon 2 blank", "tb slot 2 on", "tb slot 2 on keep", "tb desc 2", "tb slot 2 off",
    "@coupon 3 turned", "tb slot 3 on", "tb desc 3", "tb slot 3", "tb safe",
    "@load +3V3_S1 400", "tb slot 1 on", "@load +3V3_S1 off",
    "tb info extra", "tb nonsense", "tb slot 1 on a b c d e", "tb safe"]


def _script(session, special):
    from tbbench.protocol import CommandTimeout
    out = []
    for line in DIFF_SCRIPT:
        if line.startswith("@"):
            special(line[1:].split())
            continue
        try:
            r = session._cmd(line, 10.0 if "selftest" in line else 2.0)
            out.append((line, (r.rc, r.err), [(x.name, tuple(x.fields)) for x in r.records]))
        except CommandTimeout as e:
            out.append((line, "no done line", [(x.name, tuple(x.fields)) for x in e.partial]))
            session.drain(quiet_s=0.3)
    return out


def test_the_simulator_answers_every_command_as_the_firmware(limits):
    from tbbench import simdev
    from tbbench.transport import SimTransport
    t = ProcessTransport([str(NATIVE_EXE), "--uart_stdinout"])
    s = Session(t)
    try:
        s.drain(quiet_s=0.5, max_s=5.0)
        for c in ("", "shell echo off", "shell colors off", "shell vt100 off", "shell prompt off"):
            s.send(c)
            s.drain(quiet_s=0.1)
        for c in ("sim source 3.0A", "sim usb configured"):
            s.cmd(c)

        def nspecial(w):
            s.cmd(f"sim {w[0]} {w[1]} {w[2]}")
            s.drain(quiet_s=0.2)
        fw = _script(s, nspecial)
        flags = s.cmd("sim state").first("flags")
    finally:
        t.close()
    dev = simdev.SimDevice(limits, bench_build=True)        # sim.conf builds the bench-supply option in
    ss = Session(SimTransport(dev))
    ss.drain()

    def sspecial(w):
        if w[0] == "coupon":
            dev.insert(int(w[1]), w[2])
        elif w[2] == "off":
            dev.f.short_ma.pop(w[1], None)
        else:
            dev.f.short_ma[w[1]] = float(w[2])
        ss.drain()
    sim = _script(ss, sspecial)
    drift = [(a[0], a[1:], b[1:]) for a, b in zip(fw, sim) if a != b]
    assert not drift, "\n".join(f"{line}\n  firmware {f}\n  sim      {m}" for line, f, m in drift)
    assert flags.get("rule_violations") == 0, flags
