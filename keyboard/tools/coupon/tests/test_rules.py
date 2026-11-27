"""The coupon rules on synthetic coupons: the good fixture passes, and each fixture with one thing wrong fails the
rule that is about it (wrong outline, wrong pin, missing EEPROM, missing PRESENT_N strap, over-budget current, and
the rest of SPEC §4.9). Netlist tests need no KiCad; board tests need pcbnew (KiCad 10.0.8).

These prove the checker's logic on fixtures, not any real coupon. test_generated_coupons runs it on whatever the
hardware workflow has generated under keyboard/hardware/kicad/ (skipped when nothing is there).
"""

import json
import os

import pytest

import coupon_model as M
import descriptor as D
import coupon_fixtures as F
import rules as R
from coupon_fixtures import needs_pcbnew


def run(tmp_path, spec=None, desc=None, board_kw=None, geometry=None, with_board=False):
    spec = spec or F.good_spec()
    netp = F.write_net(str(tmp_path / "c.net"), spec)
    board = None
    if with_board:
        pcbp = F.write_board(str(tmp_path / "c.kicad_pcb"), spec, **(board_kw or {}))
        board = M.read_board(pcbp, geometry)
    c = R.Coupon("fixture", M.read_netlist(netp), board, desc if desc is not None else F.good_desc(), None,
                 geometry)
    return R.check(c)


def results(rep):
    return {rule: rep.result(rule) for rule, _r, _d in rep.rows}


def detail(rep, rule):
    return " | ".join(d for ru, _r, d in rep.rows if ru == rule or ru.startswith(rule + "."))


# ----------------------------------------------------------------------------------------- netlist + desc
def test_good_fixture_passes_netlist_rules(tmp_path):
    rep = run(tmp_path)
    assert not rep.failed, rep.table()
    assert rep.result("eeprom.address") == "PASS" and rep.result("present_n") == "PASS"
    assert rep.result("uses") == "PASS" and rep.result("eeprom.wc") == "PASS"


def test_netlist_reader_reads_kicad_format(tmp_path):
    n = M.read_netlist(F.write_net(str(tmp_path / "c.net"), F.good_spec()))
    assert n.comps["U1"].pin_by_name("WC") == "7"            # '~{WC}' normalised
    assert n.net_of("J1", 39) is None and n.net_of("J1", 32) == "GND"
    assert n.find_net("EE_WC") == "/Slot/EE_WC"


def test_wrong_pin(tmp_path):
    """AN0's sensor wired to header pin 13 (AN1's pin) instead of 11."""
    spec = F.move_pin(F.move_pin(F.good_spec(), "J1", 11, None), "J1", 13, "AN0")
    rep = run(tmp_path, spec)
    assert rep.result("pins.net") == "FAIL" and "pin 13 (AN1) is on AN0" in detail(rep, "pins.net")
    assert rep.result("uses") == "FAIL"


def test_swapped_i2c_pins(tmp_path):
    spec = F.good_spec()
    spec["nets"]["SCL"] = [m if m != ("J1", "29") else ("J1", "30") for m in spec["nets"]["SCL"]]
    spec["nets"]["SDA"] = [m if m != ("J1", "30") else ("J1", "29") for m in spec["nets"]["SDA"]]
    rep = run(tmp_path, spec)
    assert rep.result("pins.net") == "FAIL" and rep.result("eeprom.bus") == "FAIL"


def test_missing_eeprom(tmp_path):
    rep = run(tmp_path, F.remove_comp(F.good_spec(), "U1"))
    assert rep.result("eeprom.present") == "FAIL" and rep.failed


def test_two_eeproms(tmp_path):
    spec = F.good_spec()
    F.add_comp(spec, "U2", "U1", "M24C02-WMN6TP", {"5": "SDA", "6": "SCL", "8": "+3V3", "4": "GND"},
               lib="Memory_EEPROM", part="M24C02-WMN", pins=F.EEPROM_PINS)
    rep = run(tmp_path, spec)
    assert rep.result("eeprom.present") == "FAIL"


def test_missing_present_n_strap(tmp_path):
    rep = run(tmp_path, F.move_pin(F.good_spec(), "J1", 32, None))
    assert rep.result("present_n") == "FAIL" and rep.failed


def test_present_n_on_a_resistor_is_not_a_strap(tmp_path):
    spec = F.move_pin(F.good_spec(), "J1", 32, "PRES")
    F.add_comp(spec, "R9", "R", "0R", {"1": "PRES", "2": "GND"})
    rep = run(tmp_path, spec)
    assert rep.result("present_n") == "FAIL"


def test_rsv_connected(tmp_path):
    rep = run(tmp_path, F.move_pin(F.good_spec(), "J1", 39, "GND"))
    assert rep.result("rsv") == "FAIL"


def test_gnd_pin_open(tmp_path):
    rep = run(tmp_path, F.move_pin(F.good_spec(), "J1", 12, None))
    assert rep.result("gnd_pins") == "FAIL"


def test_over_budget_current(tmp_path):
    d = F.good_desc()
    d["rails"]["+3V3"]["max_ma"] = 300
    rep = run(tmp_path, desc=d)
    assert rep.result("budget.+3V3") == "FAIL" and "250 mA rule" in detail(rep, "budget.+3V3")
    d = F.good_desc()
    d["rails"]["+5V"]["max_ma"] = 510
    rep = run(tmp_path, desc=d)
    assert rep.result("budget.+5V") == "FAIL"
    d = F.good_desc()
    d["rails"]["+3V3"].update({"typ_ma": 30, "max_ma": 20})
    assert run(tmp_path, desc=d).result("budget.+3V3") == "FAIL"


def test_high_current_5v_needs_s5(tmp_path):
    d = F.good_desc()
    d["rails"]["+5V"]["max_ma"] = 1500
    rep = run(tmp_path, desc=d)
    assert rep.result("needs") == "FAIL" and rep.result("budget.+5V") == "FAIL"
    d.update({"size": "standard", "needs": ["high_current_5v"], "default_slot": 5})
    rep = run(tmp_path, desc=d)
    assert rep.result("budget.+5V") == "PASS" and rep.result("slots") == "PASS"
    assert rep.result("budget.source") == "WARN"           # needs a 3.0 A source: 1500 + 20 > 1455 mA


def test_5v_drawn_but_not_declared(tmp_path):
    d = F.good_desc()
    d["uses"].remove("+5V")
    d["rails"]["+5V"] = {"typ_ma": 0, "max_ma": 0, "bulk_uf": 0, "startup_ms": 0}
    rep = run(tmp_path, desc=d)
    assert rep.result("rails.+5V") == "FAIL" and "U11" in detail(rep, "rails.+5V")
    assert rep.result("uses") == "FAIL"


def test_5v_declared_but_not_connected(tmp_path):
    spec = F.good_spec()
    for p in (1, 2, 3):
        F.move_pin(spec, "J1", p, None)
    rep = run(tmp_path, spec)
    assert rep.result("uses") == "FAIL" and "not connected" in detail(rep, "uses")


def test_rails_split(tmp_path):
    rep = run(tmp_path, F.move_pin(F.good_spec(), "J1", 3, None))
    assert rep.result("rails.+5V") == "FAIL"


def test_eeprom_address_strap(tmp_path):
    rep = run(tmp_path, F.move_pin(F.good_spec(), "U1", 1, "+3V3"))
    assert rep.result("eeprom.address") == "FAIL" and "0x51" in detail(rep, "eeprom.address")
    rep = run(tmp_path, F.move_pin(F.good_spec(), "U1", 3, None))
    assert rep.result("eeprom.address") == "FAIL"


def test_eeprom_on_5v(tmp_path):
    rep = run(tmp_path, F.move_pin(F.good_spec(), "U1", 8, "+5V"))
    assert rep.result("eeprom.power") == "FAIL"


@pytest.mark.parametrize("change,result", [
    ("float", "FAIL"), ("gnd", "PASS"), ("vcc", "FAIL"), ("gline", "PASS"), ("pullup_only", "WARN")])
def test_eeprom_write_control(tmp_path, change, result):
    spec = F.good_spec()
    if change == "float":
        F.remove_comp(F.remove_comp(spec, "R1"), "JP1")
        F.move_pin(spec, "U1", 7, None)
    elif change == "gnd":
        F.remove_comp(F.remove_comp(spec, "R1"), "JP1")
        F.move_pin(spec, "U1", 7, "GND")
    elif change == "vcc":
        F.remove_comp(F.remove_comp(spec, "R1"), "JP1")
        F.move_pin(spec, "U1", 7, "+3V3")
    elif change == "gline":
        F.remove_comp(F.remove_comp(spec, "R1"), "JP1")
        F.move_pin(spec, "J1", 38, "G5")
        F.move_pin(spec, "U1", 7, "G5")
    elif change == "pullup_only":
        F.remove_comp(F.remove_comp(spec, "R1"), "JP1")
        F.add_comp(spec, "R1", "R", "100k", {"1": "/Slot/EE_WC", "2": "+3V3"})
    d = F.good_desc()
    if change == "gline":
        d["uses"].append("G5")
        d["glines"] = {"G5": {"role": "enable", "arg": 0}}
    rep = run(tmp_path, spec, desc=d)
    assert rep.result("eeprom.wc") == result, detail(rep, "eeprom.wc")


def test_irq_n_needs_a_coupon_pullup(tmp_path):
    rep = run(tmp_path, F.remove_comp(F.good_spec(), "R2"))
    assert rep.result("irq_n") == "FAIL"


def test_pullup_to_5v(tmp_path):
    spec = F.good_spec()
    F.add_comp(spec, "R5", "R", "10k", {"1": "IRQ_N", "2": "+5V"})
    rep = run(tmp_path, spec)
    assert rep.result("pullups") == "FAIL" and "R5" in detail(rep, "pullups")


def test_i2c_pullups(tmp_path):
    spec = F.good_spec()
    F.add_comp(spec, "R6", "R", "4.7k", {"1": "SDA", "2": "+3V3"})
    rep = run(tmp_path, spec)
    assert rep.result("i2c.pullups") == "WARN" and "2350 ohm" in detail(rep, "i2c.pullups")
    spec = F.good_spec()
    F.add_comp(spec, "R6", "R", "4.7k", {"1": "SCL", "2": "+5V"})
    assert run(tmp_path, spec).result("i2c.pullups") == "FAIL"


def test_shorts(tmp_path):
    spec = F.move_pin(F.good_spec(), "J1", 13, "AN0")         # AN1's pin on AN0's net
    rep = run(tmp_path, spec)
    assert rep.result("shorts") == "FAIL"
    spec = F.move_pin(F.good_spec(), "J1", 27, "GND")         # CS0_N tied to GND
    assert run(tmp_path, spec).result("shorts") == "FAIL"


def test_lane_without_source(tmp_path):
    spec = F.remove_comp(F.good_spec(), "U10")
    F.add_comp(spec, "C20", "C", "1n", {"1": "AN0", "2": "GND"})
    rep = run(tmp_path, spec)
    assert rep.result("lanes.AN0.source") == "FAIL"


def test_lane_not_declared(tmp_path):
    d = F.good_desc()
    del d["lanes"]["AN0"]
    d["devices"] = d["devices"][:1]
    rep = run(tmp_path, desc=d)
    assert rep.result("lanes.AN0") == "FAIL"              # in `uses` with kind unused
    assert rep.result("lanes.AN0.declared") == "FAIL"


def test_lane_rsrc_and_cload(tmp_path):
    d = F.good_desc()
    d["lanes"]["AN0"]["r_src_ohm"] = 4700
    assert run(tmp_path, desc=d).result("lanes.AN0") == "WARN"
    d = F.good_desc()
    del d["lanes"]["AN0"]["r_src_ohm"]
    assert run(tmp_path, desc=d).result("lanes.AN0") == "FAIL"
    d = F.good_desc()
    d["lanes"]["AN0"]["cload_max_pf"] = 1000
    assert run(tmp_path, desc=d).result("lanes.AN0.cload") == "WARN"
    spec = F.good_spec()
    F.add_comp(spec, "C21", "C", "2.2n", {"1": "AN0", "2": "GND"})
    assert run(tmp_path, spec, desc=d).result("lanes.AN0.cload") == "FAIL"


def test_bulk_capacitance(tmp_path):
    spec = F.good_spec()
    F.add_comp(spec, "C30", "C", "47u", {"1": "+3V3", "2": "GND"})
    rep = run(tmp_path, spec)
    assert rep.result("bulk.+3V3") == "FAIL"
    d = F.good_desc()
    d["rails"]["+3V3"]["bulk_uf"] = 1.0
    assert run(tmp_path, desc=d).result("bulk.+3V3") == "WARN"
    d["rails"]["+3V3"]["bulk_uf"] = 50.0
    assert run(tmp_path, desc=d).result("bulk.+3V3.declared") == "FAIL"


@pytest.mark.parametrize("value,farads", [("10u", 10e-6), ("22u/25V", 22e-6), ("100n", 100e-9), ("4.7uF", 4.7e-6),
                                          ("2u2", 2.2e-6), ("1µF 16V", 1e-6), ("470p", 470e-12), ("DNP", None)])
def test_parse_cap(value, farads):
    got = R.parse_cap(value)
    assert (got is None and farads is None) or abs(got - farads) < farads * 1e-9


def test_i2c_address_rules(tmp_path):
    d = F.good_desc()
    d["devices"][0]["addr"] = "0x70"
    assert run(tmp_path, desc=d).result("i2c.addresses") == "FAIL"
    d["devices"][0]["addr"] = "0x50"
    assert run(tmp_path, desc=d).result("i2c.addresses") == "FAIL"
    d = F.good_desc()
    d["devices"].append({"part": "touch_controller", "bus": "i2c", "addr": "0x5A"})
    assert run(tmp_path, desc=d).result("i2c.addresses") == "FAIL"


def test_declared_devices_heuristic(tmp_path):
    d = F.good_desc()
    d["devices"] = d["devices"][1:]                          # the DRV2605L on SDA is not declared
    assert run(tmp_path, desc=d).result("devices.i2c") == "WARN"


def test_needs_from_roles(tmp_path):
    d = F.good_desc()
    d["uses"] += ["G0", "G4"]
    d["glines"] = {"G0": {"role": "pwm_high", "arg": 0, "flags": ["pwm", "fast"]},
                   "G4": {"role": "pwm_low", "arg": 1, "flags": ["pwm", "fast"]}}
    spec = F.good_spec()
    F.move_pin(spec, "J1", 33, "G0")
    F.move_pin(spec, "J1", 37, "G4")
    F.add_comp(spec, "U12", "U10", "DRV", {"1": "G0", "2": "G4"}, lib="x", part="DRV",
               pins=[("1", "IN1", "input"), ("2", "IN2", "input")])
    rep = run(tmp_path, spec, desc=d)
    assert rep.result("needs") == "FAIL" and "tim1" in detail(rep, "needs")


def test_missing_descriptor(tmp_path):
    netp = F.write_net(str(tmp_path / "c.net"), F.good_spec())
    rep = R.check(R.Coupon("fixture", M.read_netlist(netp), None, None))
    assert rep.result("desc") == "FAIL" and rep.failed


def test_shipped_descriptors_pass_descriptor_rules():
    """Every descriptors/*.json passes the descriptor-only rules (what make_eeprom.py checks)."""
    ddir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "descriptors")
    for f in sorted(os.listdir(ddir)):
        d = D.load_json(os.path.join(ddir, f))
        rep = R.Report(f)
        R.check_descriptor(R.Coupon(f[:-5], desc=d), rep)
        assert not rep.failed, rep.table()


# --------------------------------------------------------------------------------------------------- board
@needs_pcbnew
def test_good_fixture_passes_board_rules(tmp_path, geometry):
    rep = run(tmp_path, geometry=geometry, with_board=True)
    assert not rep.failed, rep.table()
    for rule in ("outline", "header.footprint", "header.side", "header.position", "pins.pcb", "pins.parity",
                 "post.hole", "post.copper", "post.parts", "keepouts", "ground_plane", "layers"):
        assert rep.result(rule) == "PASS", (rule, rep.table())


@needs_pcbnew
def test_wrong_outline(tmp_path, geometry):
    rep = run(tmp_path, geometry=geometry, with_board=True, board_kw={"size": (60.0, 60.0)})
    assert rep.result("outline") == "FAIL" and "60 x 60" in detail(rep, "outline")
    d = F.good_desc()
    d.update({"size": "wide", "default_slot": 4})
    rep = run(tmp_path, desc=d, geometry=geometry, with_board=True)
    assert rep.result("outline") == "FAIL" and "descriptor says wide" in detail(rep, "outline")


@needs_pcbnew
def test_header_moved(tmp_path, geometry):
    rep = run(tmp_path, geometry=geometry, with_board=True, board_kw={"header_shift": (0.5, 0.0)})
    assert rep.result("header.position") == "FAIL" and "shifted by (+0.500, +0.000)" in detail(rep, "header.position")


@needs_pcbnew
def test_header_rotated(tmp_path, geometry):
    rep = run(tmp_path, geometry=geometry, with_board=True, board_kw={"header_rot": 90.0})
    assert rep.result("header.position") == "FAIL" and "orientation" in detail(rep, "header.position")


@needs_pcbnew
def test_header_on_top(tmp_path, geometry):
    rep = run(tmp_path, geometry=geometry, with_board=True, board_kw={"header_side": "F"})
    assert rep.result("header.side") == "FAIL"


@needs_pcbnew
def test_board_pin_net_wrong_and_parity(tmp_path, geometry):
    rep = run(tmp_path, geometry=geometry, with_board=True,
              board_kw={"pad_net_override": {("J1", "32"): "AN0", ("J1", "11"): "GND"}})
    assert rep.result("pins.pcb") == "FAIL" and rep.result("pins.parity") == "FAIL"


@needs_pcbnew
def test_post_hole_moved(tmp_path, geometry):
    rep = run(tmp_path, geometry=geometry, with_board=True, board_kw={"post_xy": (6.0, 54.0)})
    assert rep.result("post.hole") == "FAIL" and "2.83 mm away" in detail(rep, "post.hole")


@needs_pcbnew
def test_post_hole_missing(tmp_path, geometry):
    rep = run(tmp_path, F.remove_comp(F.good_spec(), "H1"), geometry=geometry, with_board=True)
    assert rep.result("post.hole") == "FAIL"


@needs_pcbnew
def test_copper_at_post(tmp_path, geometry):
    rep = run(tmp_path, geometry=geometry, with_board=True, board_kw={"stray_track": True})
    assert rep.result("post.copper") == "FAIL" and "track on GND" in detail(rep, "post.copper")


@needs_pcbnew
def test_part_at_post(tmp_path, geometry):
    rep = run(tmp_path, geometry=geometry, with_board=True, board_kw={"part_at_post": True})
    assert rep.result("post.parts") == "FAIL" and rep.result("keepouts") == "FAIL"


@needs_pcbnew
def test_bottom_side_part(tmp_path, geometry):
    rep = run(tmp_path, geometry=geometry, with_board=True, board_kw={"bottom_part": True})
    assert rep.result("keepouts") == "FAIL" and "C99 (bottom)" in detail(rep, "keepouts")


@needs_pcbnew
def test_no_ground_plane(tmp_path, geometry):
    rep = run(tmp_path, geometry=geometry, with_board=True, board_kw={"fill": False})
    assert rep.result("ground_plane") == "WARN"


@needs_pcbnew
def test_cli_exit_codes(tmp_path, geometry):
    spec = F.good_spec()
    F.write_net(str(tmp_path / "c.net"), spec)
    F.write_board(str(tmp_path / "c.kicad_pcb"), spec)
    (tmp_path / "c.json").write_text(json.dumps(F.good_desc()))
    args = ["--net", str(tmp_path / "c.net"), "--pcb", str(tmp_path / "c.kicad_pcb"), "--desc",
            str(tmp_path / "c.json"), "--json", str(tmp_path / "out.json")]
    assert R.main(args) == 0
    out = json.loads((tmp_path / "out.json").read_text())
    assert out[0]["board"] == "fixture" and not out[0]["failed"]
    bad = F.good_desc()
    bad["rails"]["+3V3"]["max_ma"] = 400
    (tmp_path / "c.json").write_text(json.dumps(bad))
    assert R.main(args) == 1
    assert R.main(["--kicad-dir", str(tmp_path / "nothing")]) == 2


# ---------------------------------------------------------------------------------- the generated coupons
GENERATED = R.generated_coupons()


@needs_pcbnew
@pytest.mark.skipif(not GENERATED, reason="no coupon generated under keyboard/hardware/kicad/ yet")
@pytest.mark.parametrize("board", GENERATED)
def test_generated_coupons(board):
    """The real boards, as the hardware workflow generated them: no FAIL. (A placeholder descriptor's board would
    fail `uses` and friends until its descriptor is written from the captured design: that is the point.)"""
    c = R.load_coupon(board)
    rep = R.check(c)
    print(rep.table())
    if rep.failed and c.desc is not None and c.desc.get("placeholder"):
        pytest.xfail(f"{board}'s descriptor is still a placeholder: write descriptors/{board}.json from the "
                     "captured design (the rules CLI reports this as FAIL, as it should)")
    assert not rep.failed, rep.table(quiet=True)


def test_rules_agree_with_sheets_coupon_common():
    """rules.coupon_net() and its pin kinds equal the coupon sheet generator's header_pins()."""
    try:
        from sheets import coupon_common as sc
    except Exception as e:                                   # noqa: BLE001
        pytest.skip(f"sheets.coupon_common not importable: {e}")
    pins = sc.header_pins()
    for pin, (sig, kind) in R.PIN_KIND.items():
        want = "GND" if kind in ("gnd", "present") else (None if kind == "nc" else R.coupon_net(sig))
        assert pins[str(pin)] == want, pin


def test_mirror_pin():
    assert [R.mirror_pin(n) for n in (1, 2, 7, 8, 32, 39, 40)] == [40, 39, 34, 33, 9, 2, 1]


def test_reversed_coupon_reads_present(tmp_path):
    """Under SPEC §4.2's pinout a coupon turned 180 degrees reads as present (pin 32 meets its pin 9, GND)."""
    rep = run(tmp_path)
    assert rep.result("reversal") == "WARN" and "pin 9, on GND" in detail(rep, "reversal")
    # with pin 9 open on the coupon (a pinout where 9 is RSV), the turned coupon reads absent
    rep = run(tmp_path, F.move_pin(F.good_spec(), "J1", 9, None))
    assert rep.result("reversal") == "PASS"


def _ladder_spec(r_ohm="1k"):
    """The good fixture with a 5-resistor ladder from +3V3 to GND on AN0-AN3 instead of the Hall sensor."""
    spec = F.remove_comp(F.good_spec(), "U10")
    taps = ["GND", "AN0", "AN1", "AN2", "AN3", "+3V3"]
    for k, (pin, net) in enumerate(((13, "AN1"), (15, "AN2"), (17, "AN3"))):
        F.move_pin(spec, "J1", pin, net)
    for k in range(5):
        F.add_comp(spec, f"R{30 + k}", "R", r_ohm, {"1": taps[k + 1], "2": taps[k]})
    return spec


def _ladder_desc(rsrc):
    d = F.good_desc()
    d["uses"] += ["AN1", "AN2", "AN3"]
    d["devices"] = d["devices"][:1]
    d["lanes"] = {ln: {"kind": "reference", "unit": "ratio", "flags": ["ratiometric", "adc4_ok"], "sites": 1,
                       "r_src_ohm": r, "cload_max_pf": 0, "offset": 0.0, "gain": 1.0}
                  for ln, r in zip(("AN0", "AN1", "AN2", "AN3"), rsrc)}
    return d


def test_lane_thevenin_from_netlist(tmp_path):
    netp = F.write_net(str(tmp_path / "c.net"), _ladder_spec("1k"))
    c = R.Coupon("fixture", M.read_netlist(netp))
    c.header_ref = "J1"
    got = [R.lane_thevenin(c, ln)[0] for ln in ("AN0", "AN1", "AN2", "AN3")]
    assert [round(x, 6) for x in got] == [800.0, 1200.0, 1200.0, 800.0]     # k (5 - k) / 5 x 1 k
    assert R.lane_thevenin(c, "SDA")[0] is None                             # U1 and U11 drive it


def test_lane_rsrc_declared_against_netlist(tmp_path):
    rep = run(tmp_path, _ladder_spec("4k99"), desc=_ladder_desc([3992, 5988, 5988, 3992]))
    assert rep.result("lanes.AN0.rsrc") == "PASS" and rep.result("lanes.AN1.rsrc") == "PASS"
    rep = run(tmp_path, _ladder_spec("4k99"), desc=_ladder_desc([400, 5988, 9000, 3992]))
    assert rep.result("lanes.AN0.rsrc") == "FAIL" and rep.result("lanes.AN2.rsrc") == "WARN"
    rep = run(tmp_path)                                                     # the Hall sensor: not computable
    assert rep.result("lanes.AN0.rsrc") == "INFO"


def test_test_coupon_descriptor_matches_its_design():
    """descriptors/test-coupon.json against sheets/test_coupon.py DESCRIPTOR_FACTS (the captured design's own
    statement of its lanes, G-lines and S5 restriction): fails when the design moves and the JSON does not."""
    try:
        from sheets import test_coupon as tc
    except Exception as e:                                   # noqa: BLE001
        pytest.skip(f"sheets.test_coupon not importable: {e}")
    facts = tc.DESCRIPTOR_FACTS
    d = D.load_json(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "descriptors",
                                 "test-coupon.json"))
    assert d["type"] == facts["type"] and d["rev"] == facts["rev"]
    for i, (ln, (ratio, rsrc)) in enumerate(sorted(facts["lanes"].items())):
        assert d["lanes"][ln]["r_src_ohm"] == rsrc, ln
        assert abs(d["ext"]["ratio"][i] - ratio) < 1e-9, ln
    for g in facts.get("s5_forbidden", []):
        assert "not_on_s5" in d["glines"][g]["flags"], g
    assert set(facts["g_lines"]) == {g for g, x in d["glines"].items() if x["role"] != "unused"}


# ------------------------------------------------------------------------------- DNP parts (not fitted)
def test_dnp_only_lane_is_open_and_not_used(tmp_path):
    """A lane reached only by a DNP part is open as assembled: it is not 'used', so declaring it fails `uses`."""
    spec = F.move_pin(F.good_spec(), "J1", 13, "AN1")
    F.add_comp(spec, "R40", "R", "0R", {"1": "AN0", "2": "AN1"})
    F.mark_dnp(spec, "R40")
    rep = run(tmp_path, spec)
    assert rep.result("lanes.AN1.source") == "INFO" and "R40" in detail(rep, "lanes.AN1.source")
    assert rep.result("uses") == "PASS"                                     # AN1 not declared, and not used
    d = F.good_desc()
    d["uses"].append("AN1")
    d["lanes"]["AN1"] = dict(d["lanes"]["AN0"])
    rep = run(tmp_path, spec, desc=d)
    assert rep.result("uses") == "FAIL" and "only to DNP" in detail(rep, "uses")


def test_dnp_eeprom_fails(tmp_path):
    rep = run(tmp_path, F.mark_dnp(F.good_spec(), "U1"))
    assert rep.result("eeprom.present") == "FAIL" and "DNP" in detail(rep, "eeprom.present")


def test_dnp_irq_pullup_does_not_count(tmp_path):
    rep = run(tmp_path, F.mark_dnp(F.good_spec(), "R2"))
    assert rep.result("irq_n") == "FAIL"


def test_dnp_wc_pulldown_holds_nothing(tmp_path):
    rep = run(tmp_path, F.mark_dnp(F.good_spec(), "R1"))
    assert rep.result("eeprom.wc") == "FAIL"


def test_dnp_pullup_to_5v_warns(tmp_path):
    spec = F.good_spec()
    F.add_comp(spec, "R5", "R", "10k", {"1": "IRQ_N", "2": "+5V"})
    F.mark_dnp(spec, "R5")
    rep = run(tmp_path, spec)
    assert rep.result("pullups") == "WARN" and "R5" in detail(rep, "pullups")


def test_dnp_bulk_counts_only_if_fitted(tmp_path):
    spec = F.good_spec()
    F.add_comp(spec, "C30", "C", "47u", {"1": "+3V3", "2": "GND"})
    F.mark_dnp(spec, "C30")
    rep = run(tmp_path, spec)
    assert rep.result("bulk.+3V3") == "WARN" and "fitting the DNP" in detail(rep, "bulk.+3V3")


# ------------------------------------------------------------------- R_src behind an active source, ratios, CLoad
def _buffered_spec(r_series="330"):
    """The good fixture with the Hall sensor's output reaching AN0 through a series resistor."""
    spec = F.good_spec()
    F.move_pin(spec, "U10", 2, "HALL_OUT")
    F.add_comp(spec, "R41", "R", r_series, {"1": "HALL_OUT", "2": "AN0"})
    return spec


def test_rsrc_lower_bound_behind_an_active_source(tmp_path):
    """SPEC §4.9: R_src is the sensor's output plus anything in series. The netlist cannot give the sensor's output
    impedance, but the series resistor alone is a lower bound: a declaration below it fails."""
    spec = _buffered_spec("330")
    d = F.good_desc()
    d["lanes"]["AN0"]["r_src_ohm"] = 100
    rep = run(tmp_path, spec, desc=d)
    assert rep.result("lanes.AN0.rsrc") == "FAIL" and "at least 330 ohm" in detail(rep, "lanes.AN0.rsrc")
    d["lanes"]["AN0"]["r_src_ohm"] = 340
    rep = run(tmp_path, spec, desc=d)
    assert rep.result("lanes.AN0.rsrc") == "PASS" and "U10 taken as 0 ohm" in detail(rep, "lanes.AN0.rsrc")


def test_lane_network_bound_and_ratio(tmp_path):
    netp = F.write_net(str(tmp_path / "c.net"), _buffered_spec("330"))
    c = R.Coupon("fixture", M.read_netlist(netp))
    c.header_ref = "J1"
    assert R.lane_network(c, "AN0")[0] is None                               # an active source: no exact value
    low, ratio, why = R.lane_network(c, "AN0", active_as_ground=True)
    assert abs(low - 330) < 1e-6 and ratio is None and "U10" in why
    netp = F.write_net(str(tmp_path / "l.net"), _ladder_spec("1k"))
    c = R.Coupon("fixture", M.read_netlist(netp))
    c.header_ref = "J1"
    got = [R.lane_network(c, ln)[1] for ln in ("AN0", "AN1", "AN2", "AN3")]
    assert [round(x, 9) for x in got] == [0.2, 0.4, 0.6, 0.8]


def test_reference_ratios_against_the_ladder(tmp_path):
    d = _ladder_desc([800, 1200, 1200, 800])
    d["ext"] = {"format": "reference_ratios", "ratio": [0.2, 0.4, 0.6, 0.8], "tolerance": [0.002] * 4}
    rep = run(tmp_path, _ladder_spec("1k"), desc=d)
    assert all(rep.result(f"lanes.AN{i}.ratio") == "PASS" for i in range(4)), rep.table()
    spec = _ladder_spec("1k")
    spec["comps"]["R30"]["value"] = "100"                     # a ladder resistor changed, the descriptor not
    rep = run(tmp_path, spec, desc=d)
    assert rep.result("lanes.AN0.ratio") == "FAIL"


def test_cload_counts_the_motherboard_capacitor(tmp_path):
    d = F.good_desc()
    d["lanes"]["AN0"]["cload_max_pf"] = 2200
    assert run(tmp_path, desc=d).result("lanes.AN0.cload") == "PASS"
    spec = F.good_spec()
    F.add_comp(spec, "C21", "C", "150p", {"1": "AN0", "2": "GND"})
    d["lanes"]["AN0"]["cload_max_pf"] = 1100                  # 150 pF + 1 nF > 1.1 nF: over if the 1 nF counts
    assert run(tmp_path, spec, desc=d).result("lanes.AN0.cload") == "WARN"
    d["lanes"]["AN0"]["cload_max_pf"] = 100                   # the coupon's own 150 pF alone is over
    assert run(tmp_path, spec, desc=d).result("lanes.AN0.cload") == "FAIL"
    d["lanes"]["AN0"]["cload_max_pf"] = 0
    assert run(tmp_path, spec, desc=d).result("lanes.AN0.cload") == "INFO"


# ------------------------------------------------------------------- misinsertion, release gate, fleet
def test_other_misinsertions(tmp_path):
    rep = run(tmp_path)
    assert rep.result("misinsertion") == "INFO"                              # only the 180-degree case reads present
    spec = F.move_pin(F.good_spec(), "J1", 34, "GND")                        # G1 on GND: one column off reads present
    rep = run(tmp_path, spec)
    assert rep.result("misinsertion") == "WARN" and "one column toward pin 1" in detail(rep, "misinsertion")
    assert [R.MISINSERTIONS[k](32) for k in R.MISINSERTIONS] == [34, 30, 31, None, 11, 7]


def test_release_gate(tmp_path, geometry):
    if not F.HAVE_PCBNEW:
        pytest.skip("pcbnew not importable")
    spec = F.good_spec()
    netp = F.write_net(str(tmp_path / "c.net"), spec)
    pcbp = F.write_board(str(tmp_path / "c.kicad_pcb"), spec)
    board = M.read_board(pcbp, geometry)
    c = R.Coupon("fixture", M.read_netlist(netp), board, F.good_desc(), None, geometry)
    rep = R.check(c)
    R.release_gate(c, rep)
    assert rep.result("release.descriptor") == "PASS"
    d = F.good_desc()
    d["placeholder"] = True
    c = R.Coupon("fixture", M.read_netlist(netp), None, d, None, geometry)
    rep = R.check(c)
    assert not rep.failed                                                    # a placeholder is only a WARN ...
    R.release_gate(c, rep)
    assert rep.result("release.descriptor") == "FAIL" and rep.result("release.files") == "FAIL"   # ... until release
    (tmp_path / "c.json").write_text(json.dumps(d))
    args = ["--net", netp, "--pcb", pcbp, "--desc", str(tmp_path / "c.json")]
    assert R.main(args) == 0 and R.main(args + ["--release"]) == 1


def test_fleet_report(tmp_path):
    for slot, board in R.DEFAULT_SET.items():
        d = F.good_desc()
        d.update({"board": board, "size": "wide", "default_slot": 4, "needs": []})
        d["rails"]["+3V3"]["max_ma"] = 70
        (tmp_path / f"{board}.json").write_text(json.dumps(d))
    rep = R.fleet_report(str(tmp_path))
    assert rep.result("fleet.slot_ldo") == "WARN" and "350 mA" in detail(rep, "fleet.slot_ldo")
    assert rep.result("fleet.vsys") == "INFO"


# ------------------------------------------------------------------- the descriptors written from captured designs
@pytest.mark.parametrize("board,module", [("coupon-hall", "coupon_hall"), ("coupon-haptics", "coupon_haptics")])
def test_descriptor_matches_its_design(board, module):
    """descriptors/<board>.json against the captured design's own DESCRIPTOR_FACTS: fails when the design moves and
    the JSON does not (as the test coupon's test above)."""
    import importlib
    try:
        facts = importlib.import_module(f"sheets.{module}").DESCRIPTOR_FACTS
    except Exception as e:                                   # noqa: BLE001
        pytest.skip(f"sheets.{module} not importable: {e}")
    d = D.load_json(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "descriptors",
                                 f"{board}.json"))
    assert not d.get("placeholder") and d["type"] == facts["type"] and d["rev"] == facts["rev"]
    for ln, lf in facts["lanes"].items():
        if lf is None or not isinstance(lf.get("r_src_ohm"), (int, float)):
            assert d["lanes"].get(ln, {"kind": "unused"})["kind"] == "unused", ln
            continue
        assert lf["r_src_ohm"] <= d["lanes"][ln]["r_src_ohm"] <= lf["r_src_ohm"] + 1, ln
        if "cload_max_nF" in lf:
            assert d["lanes"][ln]["cload_max_pf"] == round(lf["cload_max_nF"] * 1000), ln
    used_g = {g for g, x in d["glines"].items() if x["role"] != "unused"}
    assert used_g == set(facts["g_lines"]), used_g
    if "bulk_uF" in facts:
        assert {r: d["rails"][r]["bulk_uf"] for r in facts["bulk_uF"]} == facts["bulk_uF"]
    if "i2c" in facts:
        want = {a for a in facts["i2c"] if a != D.I2C_ADDR}
        assert {int(x["addr"], 16) for x in d["devices"] if x["bus"] == "i2c"} == want
    if "spi" in facts:
        for i, cs in enumerate(("CS0_N", "CS1_N")):
            if cs in facts["spi"]:
                dev = d["devices"][d["cs"][cs]["device"]]
                assert dev["bus"] == "spi" and f"mode {dev['spi_mode']}" in facts["spi"][cs], cs


def test_push_pull_on_irq_n_or_miso_warns(tmp_path):
    """SPEC §4.9: IRQ_N open drain, MISO high-impedance when deselected; read from the symbols' pin types."""
    rep = run(tmp_path)
    assert rep.result("irq_n.drive") == "PASS"                              # U11 INT is open_collector
    spec = F.good_spec()
    spec["comps"]["U11"]["pins"] = [p if p[0] != "5" else ("5", "INT", "output") for p in F.DRIVER_PINS]
    assert run(tmp_path, spec).result("irq_n.drive") == "WARN"
    spec = F.move_pin(F.good_spec(), "J1", 24, "MISO")
    F.add_comp(spec, "U12", "U10", "SR", {"1": "MISO"}, lib="x", part="SR", pins=[("1", "QH", "output")])
    assert run(tmp_path, spec).result("miso.drive") == "WARN"
    spec["comps"]["U12"]["pins"] = [("1", "Y", "tri_state")]
    assert run(tmp_path, spec).result("miso.drive") == "PASS"
