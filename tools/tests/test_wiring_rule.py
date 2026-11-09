"""The wiring rule (tools/README.md, R1-R6) is enforced by schgen.Design.check().

Run in WSL (needs the KiCad 10 symbol libraries at /usr/share/kicad/symbols):
    $HOME/.venvs/dial-me-spinner/bin/python -m pytest tools/tests -q
"""

import copy
import os
import subprocess
import sys

import pytest

import schgen
import schplace

from conftest import REPO

needs_kicad = pytest.mark.skipif(not os.path.isdir("/usr/share/kicad/symbols"), reason="KiCad symbols not installed")


def small_design(intersheet=False):
    """Sheet 'a': an op-amp stage with a divider, a pull-up and a decoupling cap. Sheet 'b' (optional) shares
    SIG_OUT, so it becomes an intersheet net with one global label per cluster."""
    d = schgen.Design("t", "t", "A", "2026-01-01")
    d.power("GND", "+3V3")
    d.sheet("a", "a.kicad_sch", "A")
    d.group("stage")
    d.add("U1", "Amplifier_Operational:TLV9062", "TLV9062", unit=1, pins={"3": "MID", "2": "FB", "1": "SIG_OUT"})
    d.add("U1", "Amplifier_Operational:TLV9062", "TLV9062", unit=3, pins={"8": "+3V3", "4": "GND"})
    d.add("R1", "Device:R", "10k", pins={"1": "+3V3", "2": "MID"})
    d.add("R2", "Device:R", "10k", pins={"1": "MID", "2": "GND"})
    d.add("R3", "Device:R", "10k", pins={"1": "SIG_OUT", "2": "FB"})
    d.add("R4", "Device:R", "1k", pins={"1": "FB", "2": "GND"})
    d.add("C1", "Device:C", "100n", pins={"1": "+3V3", "2": "GND"})
    d.add("TP1", "Connector:TestPoint", "TP", pins={"1": "SIG_OUT"})
    if intersheet:
        d.sheet("b", "b.kicad_sch", "B")
        d.group("load")
        d.add("R9", "Device:R", "1k", pins={"1": "SIG_OUT", "2": "GND"})
    return d


@needs_kicad
def test_wired_design_passes():
    d = small_design()
    assert d.check() == []
    plan = d.plans()[0]
    nwires = sum(len(v) for c in plan.clusters for v in c.segs.values())
    assert nwires > 8
    # local nets carry exactly one local label each (a name tag), never one per pin
    labels = [it for c in plan.clusters for it in c.block.items if it.kind == "label"]
    names = [lb.net for lb in labels if lb.scope == "local"]
    assert sorted(names) == sorted(set(names))
    assert {"MID", "FB"} <= set(names)


@needs_kicad
def test_decoupling_cap_is_wired_to_its_pin():
    d = small_design()
    assert d.check() == []
    plan = d.plans()[0]
    c1 = next(it for c in plan.clusters for it in c.block.items if it.kind == "sym" and it.part.ref == "C1")
    u1c = next(it for c in plan.clusters for it in c.block.items if it.kind == "sym" and it.part.ref == "U1"
               and it.part.unit == 3)
    # C1's +3V3 pin and U1C's V+ pin are in the same routing group (wired, not just both on a +3V3 symbol)
    blk = plan.clusters[0].block
    vplus = u1c.nets.index("+3V3")
    grp = next(k for k, ts in blk.conns.items() if any(t.item is u1c and t.slot == vplus for t in ts))
    assert any(t.item is c1 for t in blk.conns[grp])


@needs_kicad
def test_label_only_local_net_fails_R1():
    d = small_design()
    d.force_labels("MID")              # the old generator's style: a label on every pin, no wire
    errs = d.check()
    r1 = [e for e in errs if e.startswith("R1")]
    assert r1, errs
    msg = r1[0]
    assert "sheet a" in msg and "MID" in msg
    for pin in ("U1.3", "R1.2", "R2.1"):
        assert pin in msg


@needs_kicad
def test_intersheet_net_gets_one_label_per_cluster():
    d = small_design(intersheet=True)
    assert d.check() == []
    plan = d.plans()[0]
    glob = [it for c in plan.clusters for it in c.block.items if it.kind == "label" and it.scope == "global"]
    assert [g.net for g in glob] == ["SIG_OUT"]


@needs_kicad
def test_two_labels_of_an_intersheet_net_in_one_cluster_fail_R3():
    d = small_design(intersheet=True)
    d.force_labels("SIG_OUT")
    errs = d.check()
    r3 = [e for e in errs if e.startswith("R3") and "SIG_OUT" in e]
    assert r3, errs
    assert any("sheet a" in e for e in r3)


@needs_kicad
def test_tampered_drawing_fails():
    """The check reads the drawing, not the design: delete the wires of a local net and it fails."""
    d = small_design()
    assert d.check() == []
    plan = d.plans()[0]
    c = plan.clusters[0]
    assert "FB" in c.segs
    del c.segs["FB"]
    c.juncs = []
    errs, _ = schgen.check_drawing(d, plan)
    assert any(e.startswith("R1") and "FB" in e for e in errs), errs


@needs_kicad
def test_short_is_detected():
    d = small_design()
    assert d.check() == []
    plan = d.plans()[0]
    c = plan.clusters[0]
    # join one FB pin to one MID pin with an extra wire
    pins = {}
    for it in c.block.items:
        if it.kind == "sym":
            for i, n in enumerate(it.nets):
                pins.setdefault(n, []).append(it.tip(i))
    a, b = pins["FB"][0], pins["MID"][0]
    c.segs.setdefault("X", []).extend([(a, (a[0], b[1])), ((a[0], b[1]), b)])
    errs, _ = schgen.check_drawing(d, plan)
    assert any("SHORT" in e or "passes through" in e for e in errs), errs


@needs_kicad
def test_no_label_fallback_when_unroutable():
    """A cluster that cannot be wired is an error, never a silent label."""
    d = small_design()
    plan = d.plans()[0]
    blk = plan.clusters[0].block
    # wall off one terminal completely
    t = blk.conns["FB"][0]
    x, y = t.point()
    blk.items.append(type("Wall", (), {"kind": "nc", "boxes": lambda self: [
        schplace.Box(x - 3, y - 3, x - 0.6, y + 3), schplace.Box(x + 0.6, y - 3, x + 3, y + 3),
        schplace.Box(x - 3, y - 3, x + 3, y - 0.6), schplace.Box(x - 3, y + 0.6, x + 3, y + 3)],
        "x": x, "y": y, "move": lambda self, dx, dy: None})())
    segs, juncs, errs = schplace.route(blk, improve=0)
    assert errs and "FB" in errs[0]


def _net(nets):
    body = " ".join(f'(net (code "{i}") (name "{n}") ' + " ".join(f'(node (ref "{r}") (pin "{p}"))' for r, p in m) + ")"
                    for i, (n, m) in enumerate(nets.items(), 1))
    comps = " ".join(f'(comp (ref "{r}") (value "1k") (footprint "R"))' for r in sorted({r for m in nets.values() for r, _ in m}))
    return f"(export (version \"E\") (components {comps}) (nets {body}))"


def test_netlist_diff(tmp_path):
    import netlist_diff
    a = tmp_path / "a.net"
    b = tmp_path / "b.net"
    a.write_text(_net({"/s/N1": [("R1", "1"), ("R2", "1")], "GND": [("R1", "2"), ("R2", "2")]}))
    b.write_text(_net({"/s/N1": [("R1", "1"), ("R2", "1")], "GND": [("R1", "2"), ("R2", "2")]}))
    assert netlist_diff.diff(str(a), str(b))[0] == []
    b.write_text(_net({"/s/N1x": [("R1", "1"), ("R2", "1")], "GND": [("R1", "2"), ("R2", "2")]}))
    errs, notes, _ = netlist_diff.diff(str(a), str(b))
    assert errs and "renamed" in errs[0]
    errs, notes, _ = netlist_diff.diff(str(a), str(b), allow_rename=True)
    assert errs == [] and notes
    b.write_text(_net({"/s/N1": [("R1", "1")], "GND": [("R1", "2"), ("R2", "2"), ("R2", "1")]}))
    errs, _, _ = netlist_diff.diff(str(a), str(b))
    assert errs


@needs_kicad
@pytest.mark.slow
def test_caliper_design_passes_the_check():
    """The real slider + scale designs pass the wiring rule (no KiCad CLI needed: check() only)."""
    sys.path.insert(0, os.path.join(REPO, "caliper", "hardware", "design"))
    code = ("import sys, build;"
            "mods=build.load_modules(build.PROJECTS['slider']); build.build_libraries(mods, sys.argv[1]);"
            "d=build.make_design('slider', mods); e=d.check(); print('\\n'.join(e)); sys.exit(1 if e else 0)")
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, "-c", code, tmp], cwd=os.path.join(REPO, "caliper", "hardware", "design"),
                           capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
