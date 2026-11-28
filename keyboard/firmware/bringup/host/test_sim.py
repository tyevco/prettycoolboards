"""The bring-up firmware against the simulated board (native_sim; ../sim/), through its shell protocol.

    keyboard/firmware/bringup/sim/run_tests.sh          # builds the simulated board, then runs this file
    TB_SIM_EXE=<build>/zephyr/zephyr.exe python3 -m pytest keyboard/firmware/bringup/host -q

What this proves: the firmware's sequencing, budget rules, fault handling, descriptor handling, self-test
arithmetic and protocol output, against register models of the parts built from the same nets.py. What it cannot:
anything about the hardware. The models are this repository's reading of the datasheets, and the physics are a few
lines of Ohm's law (sim/world.c). Every test starts a fresh simulated board.

SPDX-License-Identifier: Apache-2.0
"""
import os
import pathlib
import re
import runpy
import sys

import pytest

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from tb_proto import Session, parse  # noqa: E402

REPO = HERE.parents[3]
EXE = os.environ.get("TB_SIM_EXE", str(REPO / "keyboard" / "firmware" / "build" / "bringup-sim" / "zephyr" /
                                      "zephyr.exe"))
MAP = REPO / "keyboard" / "firmware" / "boards" / "prettycool" / "kbd_testbed_a" / "include" / "tb_board_map.h"
NETS = REPO / "keyboard" / "hardware" / "design" / "nets.py"
PROTOCOL = HERE.parent / "PROTOCOL.md"

pytestmark = pytest.mark.skipif(not pathlib.Path(EXE).exists(),
                                reason=f"no simulated board at {EXE}: run keyboard/firmware/bringup/sim/run_tests.sh")


def sim_flags(sess):
    return [f for r, f in sess.cmd("sim state").records if r == "flags"][0]


@pytest.fixture
def s():
    """A fresh simulated board. On the way out, the model's SPEC §3.5 rule monitor (sim/sim.h) must have seen no
    violation during the test: no +5V without +3V3, no bus switch closed, mux channel selected or slot line driven
    high into an unpowered slot, no rail on while the host has not configured the device."""
    with Session.sim(EXE) as sess:
        sess.setup()
        yield sess
        flags = sim_flags(sess)
        assert flags["rule_violations"] == 0, f"SPEC §3.5 rule broken: {flags['first_violation']} " \
                                              f"({flags['rule_violations']} in all)"


def configure(s, source="3.0A"):
    assert s.cmd(f"sim source {source}").ok
    assert s.cmd("sim usb configured").ok
    s.wait_for("ev", kind="usb", event="configured")


def test_boot_report(s):
    r = s.cmd("tb boot")
    assert r.ok
    boot = r.one("boot")
    hash_ = re.search(r'#define TB_MAP_HASH "([0-9a-f]+)"', MAP.read_text()).group(1)
    assert boot["map"] == hash_, "the firmware carries the generated map it was built with"
    assert boot["proto"] == 1
    assert boot["i2c1_bus"] == 0 and boot["i2c4_bus"] == 0, "both buses answered without a recovery"
    assert r.one("boot_restore")["ok"] == 1
    assert r.one("boot_mux")["post"] == 0
    inas = r.all("boot_ina")
    assert len(inas) == 13 and all(i["mfr"] == 0x5449 and i["err"] == 0 for i in inas)
    assert {i["rail"]: i["cal"] for i in inas}["+3V3_S1"] == 1939, "SPEC §3.4's CAL on the slot monitors"
    for e in r.all("boot_exp"):
        assert e["ok"] == 1 and e["por"] == 1


def test_no_slot_power_before_configuration(s):
    r = s.cmd("tb slot 1 on")
    assert r.done["rc"] < 0 and r.done["err"] == "unconfigured"
    assert s.cmd("tb budget").one("budget")["limit_ma"] == 100


def test_budget_follows_the_source_per_nets(s):
    nets = runpy.run_path(str(NETS))
    configure(s)
    for src, key in (("default", "default"), ("1.5A", "1.5A"), ("3.0A", "3.0A"), ("accessory", "accessory"),
                     ("none", "not attached")):
        assert s.cmd(f"sim source {src}").ok
        s.wait_for("ev", kind="cc")
        b = s.cmd("tb budget").one("budget")
        assert b["limit_ma"] == round(nets["vsys_budget"](key) * 1000), src


def test_discovery_and_selftest(s):
    configure(s)
    r = s.cmd("tb slot 1 on")
    assert r.ok, r.done
    on = r.one("slot_on")
    assert on["on3"] == on["on5"] == on["bus"] == 1 and on["ma3"] == 120 and on["ma5"] == 170
    st = s.cmd("tb selftest 1 all", timeout=20)
    steps = {f["name"]: f for f in st.all("step")}
    assert st.one("selftest")["result"] == "pass", steps
    assert set(steps) == {"power", "idle", "lanes", "loopback", "load3", "load5", "climit3", "climit5"}
    assert 290 <= steps["load3"]["rs_mohm"] <= 360, "the model's 325 mOhm, through 14-bit lanes"
    assert 256000 <= steps["climit3"]["i_ua"] <= 335000


def test_selftest_never_drives_g3_on_s5(s):
    configure(s)
    assert s.cmd("sim coupon 1 none").ok
    assert s.cmd("sim coupon 5 test").ok
    st = s.cmd("tb selftest 5 all", timeout=20)
    steps = {f["name"]: f for f in st.all("step")}
    assert steps["climit5"]["result"] == "skip" and steps["climit5"]["reason"] == "never_on_s5"
    assert st.one("selftest")["result"] == "pass"


def test_overload_is_switched_off(s):
    configure(s)
    assert s.cmd("tb slot 1 on").ok
    assert s.cmd("sim load +3V3_S1 400").ok
    trip = s.wait_for("ev", kind="trip")
    assert trip["finding"] in ("alert", "switch_limit") and trip["rail"] == "+3V3_S1"
    s.wait_for("ev", kind="rail_off", rail="+5V_S1")
    slot = s.cmd("tb slot 1").one("slot")
    assert slot["on3"] == 0 and slot["on5"] == 0


def test_switch_fault_without_alert(s):
    configure(s)
    # declared at the rule, so the firmware's alert (275 mA) sits above the switch's typical 292 mA? no: the
    # alert is capped under 95 % of the minimum trip (243 mA): the INA226 or the FAULT, whichever comes first
    assert s.cmd("tb slot 1 on nodesc ma3=250").ok
    assert s.cmd("sim load +3V3_S1 600").ok
    trip = s.wait_for("ev", kind="trip")
    assert trip["rail"] == "+3V3_S1"
    s.wait_for("ev", kind="rail_off", rail="+3V3_S1")


def test_empty_slot_is_never_powered(s):
    """SPEC §3.5: never power a slot while its PRESENT_N reads high (slot 2 is empty in the model)."""
    configure(s)
    assert s.cmd("tb slot 2 on").done["err"] == "not_present"
    assert s.cmd("tb rail +3V3_S2 on 10").done["err"] == "not_present"
    assert s.cmd("tb rail +5V_S2 on 10").done["err"] == "not_present"
    assert s.cmd("tb slot 2").one("slot")["on3"] == 0


def test_turned_coupon_is_refused_without_driving_it(s):
    """risks.md EL-2 with the slot key's plug missing (D2 of 2026-11-27 plugs socket hole 39, by hand): a coupon
    turned 180 degrees reads present (its GND on PRESENT_N), and its descriptor cannot be read (its GND on SCL). The
    firmware reads the descriptor before it drives any slot line (SPEC §4.6), so it turns the slot off without
    driving CS0_N into the coupon's GND or G0/G1 into its rail: the fixture's monitor (sim/sim.h) sees no line
    driven and no bus switch closed. The same coupon the right way round is identified and powered."""
    configure(s)
    assert s.cmd("sim coupon 2 turned").ok
    r = s.cmd("tb slot 2 on")
    assert r.done["rc"] < 0 and r.done["err"] == "desc_bus" and r.one("slot_on")["on3"] == 0
    assert s.cmd("tb slot 2").one("slot")["on3"] == 0
    assert s.cmd("sim coupon 2 test").ok
    on = s.cmd("tb slot 2 on").one("slot_on")
    assert on["on3"] == 1 and on["bus"] == 1 and on["desc"] == "ok"


def test_coupon_pulled_while_powered(s):
    configure(s)
    assert s.cmd("tb slot 1 on").ok
    assert s.cmd("sim coupon 1 none").ok
    s.wait_for("ev", kind="trip", finding="coupon_removed")
    assert s.cmd("tb slot 1").one("slot")["on3"] == 0


def test_usb_reset_and_suspend_shed_everything(s):
    configure(s)
    assert s.cmd("tb slot 1 on").ok
    assert s.cmd("sim usb suspend").ok
    s.wait_for("ev", kind="rail_off", rail="+3V3_S1", reason="usb")
    assert s.cmd("tb slot 1 on").done["err"] == "suspended"
    assert s.cmd("sim usb resume").ok
    s.wait_for("ev", kind="usb", event="resume")
    assert s.cmd("tb slot 1 on").ok
    assert s.cmd("sim usb reset").ok
    s.wait_for("ev", kind="rail_off", rail="+3V3_S1", reason="usb")
    assert s.cmd("tb budget").one("budget")["limit_ma"] == 100
    configure(s)
    assert s.cmd("tb slot 1 on").ok
    assert s.cmd("sim usb deconfigured").ok
    s.wait_for("ev", kind="usb", event="configured", value=0)
    assert s.cmd("tb slot 1").one("slot")["on3"] == 0, "SET_CONFIGURATION(0) leaves the device unconfigured"
    configure(s)
    assert s.cmd("tb slot 1 on").ok
    assert s.cmd("sim usb disconnected").ok
    s.wait_for("ev", kind="usb", event="disconnected")
    assert s.cmd("tb slot 1").one("slot")["on3"] == 0 and s.cmd("tb budget").one("budget")["limit_ma"] == 100


def test_source_drop_sheds_s5_first(s):
    configure(s)
    assert s.cmd("tb slot 1 on nodesc ma3=10 ma5=300").ok
    assert s.cmd("sim coupon 5 test").ok
    assert s.cmd("tb slot 5 on nodesc ma3=10 ma5=1500").ok
    assert s.cmd("sim source 1.5A").ok
    off = s.wait_for("ev", kind="rail_off")
    assert off["rail"] == "+5V_S5" and off["reason"] == "source"
    assert s.cmd("tb slot 1").one("slot")["on5"] == 1


def test_blank_descriptor_is_written_and_verified(s):
    configure(s)
    assert s.cmd("sim coupon 2 blank").ok
    r = s.cmd("tb slot 2 on")
    assert r.done["err"] == "blank" and r.one("slot_on")["on3"] == 0
    assert s.cmd("tb slot 2 on keep").one("slot_on")["on3"] == 1
    w = s.cmd("tb desc 2 write test serial=42")
    assert w.ok and w.one("desc")["serial"] == 42
    assert s.cmd("tb desc 2 write test").done["err"] == "already_written"


def test_slot_ldo_budget_and_probe(s):
    configure(s)
    assert s.cmd("tb slot 1 on").ok
    assert s.cmd("sim coupon 2 test").ok
    assert s.cmd("tb slot 2 on").done["err"] == "over_slot_ldo", "120 + the 250 mA rule > 300 mA"
    assert s.cmd("tb slot 2 on probe=20").ok
    assert s.cmd("sim coupon 3 test").ok
    assert s.cmd("tb slot 3 on probe=20").done["err"] == "over_slot_ldo", "3 x 120 mA > 300 mA"


def test_s5_breaker_latch(s):
    configure(s)
    assert s.cmd("sim coupon 5 test").ok
    assert s.cmd("tb slot 5 on").ok
    assert s.cmd("sim load +5V_S5 2500").ok
    s.wait_for("ev", kind="trip", finding="s5_breaker")
    slot = s.cmd("tb slot 5").one("slot")
    assert slot["on5"] == 0 and slot["on3"] == 1


def test_vsys_over_budget_sheds(s):
    configure(s, "default")
    assert s.cmd("tb budget override 400").ok
    assert s.cmd("tb rail +5V_KVM on 100").ok
    assert s.cmd("sim load +5V_KVM 500").ok
    s.wait_for("ev", kind="trip", finding="vsys_over")
    s.wait_for("ev", kind="rail_off", rail="+5V_KVM", reason="vsys_over_budget")


def test_bench_supply_mode(s):
    """SPEC §10 step 5 powers the slots from a bench supply with no USB host: the bench mode this firmware adds."""
    assert s.cmd("tb slot 1 on").done["err"] == "unconfigured"
    b = s.cmd("tb budget bench 1000")
    assert b.ok and b.one("budget")["limit_ma"] == 1000 and b.one("budget")["may_power"] == 1
    assert s.cmd("tb slot 1 on").ok
    assert s.cmd("tb budget bench 9000").one("budget")["limit_ma"] == 2800, "capped at the ceiling"
    assert s.cmd("sim usb configured").ok
    s.wait_for("ev", kind="rail_off", rail="+3V3_S1", reason="usb")
    assert s.cmd("tb budget bench 1000").done["err"] == "usb_configured"


def test_override_never_raises(s):
    configure(s, "1.5A")
    assert s.cmd("tb budget override 9000").one("budget")["limit_ma"] == 1500


def test_tusb320_only_ever_has_its_interrupt_cleared(s):
    configure(s)
    for src in ("1.5A", "default", "3.0A"):
        assert s.cmd(f"sim source {src}").ok
        s.wait_for("ev", kind="cc", source=src)
    flags = [f for r, f in s.cmd("sim state").records if r == "flags"][0]
    assert flags["cc_violations"] == 0 and flags["cc_int"] == 0


def test_lanes_without_and_with_a_coupon(s):
    r = s.cmd("tb lanes 1")
    assert all(f["powered"] == 0 for f in r.all("lane"))
    configure(s)
    assert s.cmd("tb slot 1 on").ok
    r = s.cmd("tb lanes 1")
    assert r.ok and all(f["ok"] == 1 for f in r.all("lane"))
    assert all(f["agree"] == 1 for f in r.all("lane_alt"))


def test_every_record_is_documented(s):
    """Every record the firmware printed in a busy session is listed in PROTOCOL.md."""
    documented = set(re.findall(r"^@tb ([a-z_]+)", PROTOCOL.read_text(), re.M))
    configure(s)
    for c in ("tb info", "tb boot", "tb usb", "tb cc", "tb budget", "tb ina", "tb ina +3V3_S1", "tb exp",
              "tb slot 1 on", "tb slot", "tb desc 1", "tb lanes 1", "tb selftest 1 all", "tb trips", "tb mon",
              "tb ev 1", "tb rail +5V_KVM on 10", "tb rail +5V_KVM off", "tb ina alert +3V3_S1 200",
              "tb ina cfg all 16 1100 1100 7", "tb ina drv +3V3_S1", "tb safe"):
        assert s.cmd(c, timeout=20).done is not None, c
    seen = set()
    for line in s.raw:
        p = parse(line)
        if p and p[0] == "tb":
            seen.add(p[1])
    undocumented = seen - documented - {"done"}
    assert not undocumented, f"records not in PROTOCOL.md: {sorted(undocumented)}"
