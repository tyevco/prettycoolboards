"""Faults injected into copies of the REAL generated coupons (keyboard/hardware/kicad/<board>/): each must FAIL the
rule that is about it. The synthetic fixtures (test_rules.py) prove the logic; these prove that the readers and the
rules work on what build.py and layout.py actually write (KiCad 10.0.8's netlist and board), and that a PASS on
the real boards is not a PASS by omission.

Each test copies the generated files into tmp_path and edits the copy (the netlist through tools/sexpr.py, the board
through pcbnew); nothing under keyboard/hardware/ is touched. Skipped for a board that is not generated yet.
"""

import copy
import json
import os

import pytest

import coupon_model as M
import rules as R
from coupon_fixtures import needs_pcbnew

COUPON = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _files(board):
    net, pcb = M.board_files(board)
    if not (os.path.exists(net) and os.path.exists(pcb)):
        pytest.skip(f"{board} is not generated under keyboard/hardware/kicad/")
    return net, pcb, os.path.join(COUPON, "descriptors", f"{board}.json")


def _edit_net(src, dst, fn):
    import sexpr
    with open(src, encoding="utf-8") as fh:
        root = sexpr.parse(fh.read())
    fn(root)
    with open(dst, "w", encoding="utf-8") as fh:
        fh.write(sexpr.dumps(root))
    return str(dst)


def _move_node(root, ref, pin, new_net):
    import sexpr
    ns = sexpr.find(root, "nets")
    for n in sexpr.find_all(ns, "net"):
        for nd in list(sexpr.find_all(n, "node")):
            if str(sexpr.find(nd, "ref")[1]) == ref and str(sexpr.find(nd, "pin")[1]) == str(pin):
                n.remove(nd)
                target = next((m for m in sexpr.find_all(ns, "net") if str(sexpr.find(m, "name")[1]) == new_net),
                              None)
                if target is None:
                    target = ["net", ["code", sexpr.Q("9999")], ["name", sexpr.Q(new_net)],
                              ["class", sexpr.Q("Default")]]
                    ns.append(target)
                target.append(nd)
                return
    raise KeyError((ref, pin))


def _set_value(root, ref, value):
    import sexpr
    for c in sexpr.find_all(sexpr.find(root, "components"), "comp"):
        if str(sexpr.find(c, "ref")[1]) == ref:
            sexpr.find(c, "value")[1] = sexpr.Q(value)
            return
    raise KeyError(ref)


def _add_cap(root, ref, value, net_a, net_b, like):
    import sexpr
    comps = sexpr.find(root, "components")
    proto = next(c for c in sexpr.find_all(comps, "comp") if str(sexpr.find(c, "ref")[1]) == like)
    c = copy.deepcopy(proto)
    sexpr.find(c, "ref")[1] = sexpr.Q(ref)
    sexpr.find(c, "value")[1] = sexpr.Q(value)
    comps.append(c)
    for n in sexpr.find_all(sexpr.find(root, "nets"), "net"):
        name = str(sexpr.find(n, "name")[1])
        for pin, want in (("1", net_a), ("2", net_b)):
            if name == want:
                n.append(["node", ["ref", sexpr.Q(ref)], ["pin", sexpr.Q(pin)], ["pintype", sexpr.Q("passive")]])


def _check(board, net=None, pcb=None, desc=None, geometry=None):
    n0, p0, d0 = _files(board)
    c = R.load_coupon(board, net_path=net or n0, pcb_path=pcb or p0, desc_path=desc or d0, geometry=geometry)
    return R.check(c)


def _desc(board, tmp_path, fn):
    _n, _p, d0 = _files(board)
    d = json.load(open(d0, encoding="utf-8"))
    fn(d)
    p = tmp_path / f"{board}.json"
    p.write_text(json.dumps(d))
    return str(p)


@needs_pcbnew
def test_unchanged_test_coupon_has_no_fail(geometry):
    rep = _check("test-coupon", geometry=geometry)
    assert not rep.failed, rep.table(quiet=True)


@needs_pcbnew
def test_present_n_strap_removed(tmp_path, geometry):
    n0, _p, _d = _files("test-coupon")
    net = _edit_net(n0, tmp_path / "f.net", lambda r: _move_node(r, "J1", 32, "/Slot/PRESENT_N_OPEN"))
    rep = _check("test-coupon", net=net, geometry=geometry)
    assert rep.result("present_n") == "FAIL" and rep.result("pins.parity") == "FAIL"


@needs_pcbnew
def test_eeprom_address_strap(tmp_path, geometry):
    n0, _p, _d = _files("test-coupon")
    net = _edit_net(n0, tmp_path / "f.net", lambda r: _move_node(r, "U1", 1, "+3V3"))
    assert _check("test-coupon", net=net, geometry=geometry).result("eeprom.address") == "FAIL"


@needs_pcbnew
def test_eeprom_write_control_tied_high(tmp_path, geometry):
    n0, _p, _d = _files("test-coupon")
    net = _edit_net(n0, tmp_path / "f.net", lambda r: _move_node(r, "U1", 7, "+3V3"))
    assert _check("test-coupon", net=net, geometry=geometry).result("eeprom.wc") == "FAIL"


@needs_pcbnew
def test_ladder_resistor_changed(tmp_path, geometry):
    """R30 499 -> 100 ohm with the descriptor unchanged: the reference ratio and the lane's R_src move."""
    n0, _p, _d = _files("test-coupon")
    net = _edit_net(n0, tmp_path / "f.net", lambda r: _set_value(r, "R30", "100"))
    rep = _check("test-coupon", net=net, geometry=geometry)
    assert rep.result("lanes.AN0.ratio") == "FAIL"


@needs_pcbnew
def test_lane_capacitor_over_cload(tmp_path, geometry):
    n0, _p, _d = _files("test-coupon")
    net = _edit_net(n0, tmp_path / "f.net", lambda r: _add_cap(r, "C99", "150p", "AN0", "GND", like="C3"))
    desc = _desc("test-coupon", tmp_path, lambda d: d["lanes"]["AN0"].update(cload_max_pf=100))
    assert _check("test-coupon", net=net, desc=desc, geometry=geometry).result("lanes.AN0.cload") == "FAIL"


@needs_pcbnew
def test_header_moved_on_the_board(tmp_path, geometry):
    import pcbnew
    _n, p0, _d = _files("test-coupon")
    b = pcbnew.LoadBoard(p0)
    j1 = b.FindFootprintByReference("J1")
    j1.SetPosition(j1.GetPosition() + pcbnew.VECTOR2I(pcbnew.FromMM(0.1), 0))
    pcb = str(tmp_path / "f.kicad_pcb")
    pcbnew.SaveBoard(pcb, b)
    rep = _check("test-coupon", pcb=pcb, geometry=geometry)
    assert rep.result("header.position") == "FAIL" and "+0.100" in " ".join(d for _r, _x, d in rep.rows)


@needs_pcbnew
def test_over_budget_declaration(tmp_path, geometry):
    desc = _desc("test-coupon", tmp_path, lambda d: d["rails"]["+3V3"].update(max_ma=300))
    assert _check("test-coupon", desc=desc, geometry=geometry).result("budget.+3V3") == "FAIL"


@needs_pcbnew
def test_haptics_rsrc_declared_below_its_series_resistor(tmp_path, geometry):
    """The placeholder this descriptor replaced declared 100 ohm on AN1-AN3, behind the design's 330 ohm."""
    desc = _desc("coupon-haptics", tmp_path, lambda d: d["lanes"]["AN1"].update(r_src_ohm=100))
    rep = _check("coupon-haptics", desc=desc, geometry=geometry)
    assert rep.result("lanes.AN1.rsrc") == "FAIL" and "at least 330 ohm" in " ".join(d for _r, _x, d in rep.rows)


@needs_pcbnew
def test_hall_lane_behind_a_dnp_part(tmp_path, geometry):
    """AN2 reaches only R26, which is DNP: declaring AN2 used fails `uses`."""
    def f(d):
        d["uses"].append("AN2")
        d["lanes"]["AN2"] = dict(d["lanes"]["AN0"])
    desc = _desc("coupon-hall", tmp_path, f)
    assert _check("coupon-hall", desc=desc, geometry=geometry).result("uses") == "FAIL"
