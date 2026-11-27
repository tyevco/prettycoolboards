#!/usr/bin/env python3
"""Generate, route and gate the PrettyCool Keyboard rev A PCBs from their KiCad netlists.

usage: python keyboard/hardware/design/layout.py --board NAME [--route] [--minutes N] [--attempts N]
                                                 [--place-only | --resume | --complete | --finish]

The generic driver. Everything board-specific lives in boards/<board>.py (board name with - as _): the outline,
the fixed placements, keep-outs, zones, net classes, pre-routes and pours (see README.md, "How to add a board").
This driver:

1. loads keyboard/hardware/kicad/<board>/<project>.net (build.py writes it), places every footprint
   (tools/pcbgen.py), puts the board module's fixed parts where it says and locks them;
2. draws the outline, a 0.3 mm edge band the routers keep out of, the In1 GND plane (4-layer boards), then the
   board module's rule areas and documentation (`build`), and runs its checks (`post_fixed`);
3. places the other parts with tools/placer.py: first those the module anchors to a pin (`PIN_ANCHORS`) or a region
   (`REGIONS`), then each remaining part next to the placed IC it shares the most nets with, at the pads of those
   nets, on the top side;
4. with --route: fans every GND pad out to the In1 plane, exports a Specctra DSN (GND dropped, In1 a plane),
   runs Freerouting (--minutes, --attempts, each attempt longer), imports the session, completes what is left with
   tools/finish_route.py's grid router, adds the module's pours, cleans up (anchors, duplicates, dangling copper),
   stitches GND, and repeats the completion up to three times;
5. writes the .kicad_pcb, the net classes and rules into the .kicad_pro (KiCad 10 keeps them there), the stack-up,
   and runs kicad-cli DRC with schematic parity (<project>-drc.rpt). Exit code 1 on any DRC error.

Adapted from caliper/hardware/design/layout.py (its routing flow, not its board geometry). The caliper's --rework
(keep the routing of unchanged nets) is not ported yet: a keyboard board is regenerated and routed whole.

Coordinates in the board modules are board mm (boards/geom.py): origin at the lower-left corner, +y up, top view.
"""

from __future__ import annotations

import argparse
import importlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
HW = os.path.dirname(HERE)                                  # keyboard/hardware
REPO = os.path.dirname(os.path.dirname(HW))                 # repo root
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, HERE)

import pcbnew  # noqa: E402

import finish_route  # noqa: E402
import pcbgen  # noqa: E402
import silk  # noqa: E402
from placer import Placer  # noqa: E402

from boards.geom import OX, OY, MM, TO, B, P, dist_to_poly, inside_poly, poly_page  # noqa: E402
from build import project_name, uuid_namespace  # noqa: E402
from sheets import PROJECTS  # noqa: E402

KICAD_DIR = os.path.join(HW, "kicad")
FREEROUTING = os.environ.get("FREEROUTING_JAR", "/opt/freerouting/freerouting.jar")
LIB = "keyboard"
TEMP_KEEPOUT = "ROUTER_ONLY_KEEPOUT"
PLANE_ZONE = "GND_PLANE"


# --------------------------------------------------------------------------- board modules
def board_module(board):
    return importlib.import_module("boards." + board.replace("-", "_"))


def cfg(mod, name, default=None):
    return getattr(mod, name, default)


def project_dir(board):
    return os.path.join(KICAD_DIR, board)


def pcb_path(board):
    return os.path.join(project_dir(board), project_name(board) + ".kicad_pcb")


def refnum(ref):
    m = re.match(r"[A-Za-z]+(\d+)", ref)
    return int(m.group(1)) if m else 0


def net_short(name):
    return name.split("/")[-1]


def pad_xy(fp, num=None, net=None):
    """Board-mm position of a footprint's pad, by number or by net (short name)."""
    for p in fp.Pads():
        if (num is None or p.GetNumber() == num) and (net is None or net_short(p.GetNetname()) == net):
            return B(TO(p.GetPosition().x), TO(p.GetPosition().y))
    raise KeyError(f"{fp.GetReference()}: no pad {num} / {net}")


# --------------------------------------------------------------------------- net classes, rules, stack-up
def netclasses(bb, mod, allnets):
    """The board's net classes (module NETCLASSES: (name, nets by short name, track, clearance, via, drill)), set on
    the board and returned as a spec for write_project(): KiCad 10 keeps them in the project file."""
    spec = []
    for name, names, track, clr, via, drill in cfg(mod, "NETCLASSES", []):
        nets_ = [n for n in allnets if net_short(n) in names]
        if nets_:
            spec.append((name, nets_, track, clr, via, drill))
    bb.board.GetDesignSettings().m_NetSettings.ClearNetclassPatternAssignments()
    for name, nets_, track, clr, via, drill in spec:
        bb.netclass(name, nets_, track=track, clearance=clr, via=via, via_drill=drill)
    return spec


# The fields of a KiCad 10.0.8 net class besides name, widths, clearance and priority (as KiCad writes Default).
NETCLASS_FIELDS = {"bus_width": 12, "diff_pair_gap": 0.25, "diff_pair_via_gap": 0.25, "diff_pair_width": 0.2,
                   "line_style": 0, "microvia_diameter": 0.3, "microvia_drill": 0.1,
                   "pcb_color": "rgba(0, 0, 0, 0.000)", "schematic_color": "rgba(0, 0, 0, 0.000)",
                   "tuning_profile": "", "wire_width": 6}


def write_project(pro, mod, spec):
    """Write the Default class (module RULES), the net classes of `spec` with their net patterns, and the board's
    minimum rules into the project file. pcbnew's SaveBoard does not write the project of a board built in memory,
    and the next load would bring back the template's rules (caliper layout.write_project_netclasses, tools/README)."""
    with open(pro, encoding="utf-8") as f:
        d = json.load(f)
    rules = mod.RULES
    ns = d.setdefault("net_settings", {})
    # The schematic's project comes from KiCad's template, whose net_settings carry schema version 0: KiCad 10 then
    # drops every netclass pattern on the next LoadBoard (and SaveBoard writes them back empty), so every net routed
    # in the Default class. Version 5 is what KiCad 10.0.8 itself writes for the format below (review 2026-11-27).
    ns["meta"] = {"version": max(5, int(ns.get("meta", {}).get("version", 0)))}
    classes = ns.setdefault("classes", [])
    default = next((c for c in classes if c.get("name") == "Default"), None)
    if default is None:
        default = {"name": "Default"}
        classes.insert(0, default)
    default.update({"track_width": rules["track"], "clearance": rules["clearance"], "via_diameter": rules["via"],
                    "via_drill": rules["via_drill"]})
    keep = {"Default"} | {s[0] for s in spec}
    classes[:] = [c for c in classes if c.get("name") in keep]
    for name, nets_, track, c, via, drill in spec:
        e = next((x for x in classes if x.get("name") == name), None)
        if e is None:
            e = dict(default)
            classes.append(e)
        e.update({"name": name, "track_width": track, "clearance": c, "via_diameter": via, "via_drill": drill})
    # Every class complete, as KiCad 10 writes them: a class with a field missing is composed with the next class
    # down, Default, and the net's class name becomes "Rail,Default". finish_route's GetNetClassByName then finds
    # nothing and routes at Default's width and clearance, and the DSN class name carries the comma (review
    # 2026-11-27: the test coupon's +3V3 came out at 0.20 mm with 29 class-clearance errors).
    for e in classes:
        for k, v in NETCLASS_FIELDS.items():
            e.setdefault(k, v)
        e["priority"] = 2147483647 if e.get("name") == "Default" else -1
    ns["netclass_patterns"] = [{"netclass": name, "pattern": n} for name, nets_, *_ in spec for n in sorted(nets_)]
    ds = d.setdefault("board", {}).setdefault("design_settings", {})
    # No DRC check is ignored on a keyboard board: the five KiCad 10 leaves at "ignore" by default are turned on
    # (a footprint filter is a library hint, so its mismatch is a warning; the others are errors)
    ds.setdefault("rule_severities", {}).update({
        "missing_courtyard": "error", "track_not_centered_on_via": "error", "tuning_profile_track_geometries": "error",
        "footprint_type_mismatch": "error", "footprint_filters_mismatch": "warning"})
    r = ds.setdefault("rules", {})
    r.update({"min_clearance": 0.1, "min_track_width": 0.1, "min_via_diameter": 0.4,
              "min_through_hole_diameter": 0.2, "min_copper_edge_clearance": rules["edge"],
              "min_hole_clearance": 0.2, "min_resolved_spokes": 1})
    with open(pro, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2)
        f.write("\n")


def _sexpr_end(s, i):
    depth = 0
    for k in range(i, len(s)):
        if s[k] == "(":
            depth += 1
        elif s[k] == ")":
            depth -= 1
            if not depth:
                return k + 1
    raise ValueError("unbalanced s-expression")


def _class_head_end(block):
    """Index of the first "(" of a DSN (class ...) block that is not inside a quoted net name. KiCad names an
    unconnected pin's net "unconnected-(J1-Pin_19-Pad19)", so a plain block.index("(", 1) cut the class header inside
    a name; rebuilding the header then left an unbalanced quote that could swallow the class's circuit and rules
    (coupon-haptics, 2026-11-27)."""
    quoted = False
    for k in range(1, len(block)):
        if block[k] == '"':
            quoted = not quoted
        elif block[k] == "(" and not quoted:
            return k
    raise ValueError("no list in the class block")


def stackup_sexpr(items, finish="ENIG"):
    out = ["\t\t(stackup"]
    for name, typ, t, mat, er in items:
        s = f'\t\t\t(layer "{name}"\n\t\t\t\t(type "{typ}")'
        if t is not None:
            s += f"\n\t\t\t\t(thickness {t:g})"
        if mat is not None:
            s += f'\n\t\t\t\t(material "{mat}")'
        if er is not None:
            s += f"\n\t\t\t\t(epsilon_r {er:g})"
            if typ in ("prepreg", "core"):
                s += "\n\t\t\t\t(loss_tangent 0.02)"
        out.append(s + "\n\t\t\t)")
    out.append(f'\t\t\t(copper_finish "{finish}")\n\t\t\t(dielectric_constraints no)\n\t\t)')
    return "\n".join(out)


def set_stackup(path, items, finish="ENIG"):
    """Write the fab stack-up into the board's (setup); pcbnew keeps it through later loads and saves."""
    with open(path, encoding="utf-8") as f:
        s = f.read()
    i = s.find("(setup")
    if i < 0:
        raise RuntimeError("no (setup) in " + path)
    j = s.find("(stackup", i)
    end = _sexpr_end(s, i)
    if 0 <= j < end:
        s = s[:j].rstrip(" \t") + stackup_sexpr(items, finish).lstrip("\t") + s[_sexpr_end(s, j):]
    else:
        nl = s.index("\n", i)
        s = s[:nl + 1] + stackup_sexpr(items, finish) + "\n" + s[nl + 1:]
    total = sum(t for _, _, t, _, _ in items if t)
    s = re.sub(r"\(general\s*\(thickness [0-9.]+\)", f"(general\n\t\t(thickness {total:g})", s, count=1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(s)
    return total


def set_layer_types(path, layers):
    """In1 is the GND plane: layer type 'power', so Freerouting keeps signals off it."""
    if layers != 4:
        return
    with open(path, encoding="utf-8") as f:
        s = f.read()
    s, n = re.subn(r'\((\d+) "In1\.Cu" signal\)', r'(\1 "In1.Cu" power)', s)
    if not n and '"In1.Cu" power' not in s:
        raise RuntimeError("In1.Cu layer entry not found: the GND plane would be routed as a signal layer")
    with open(path, "w", encoding="utf-8") as f:
        f.write(s)


# --------------------------------------------------------------------------- placement
def _inside_fn(mod, outline, margin=0.5):
    sides = cfg(mod, "PART_SIDES", ("F",))

    def inside(X, Y, side):
        x, y = B(X, Y)
        return side in sides and inside_poly(x, y, outline) and dist_to_poly(x, y, outline) >= margin
    return inside


def _keepouts_page(mod):
    out = []
    for k in (mod.keepouts() if hasattr(mod, "keepouts") else []):
        side, pred = k[0], k[1]
        page_pred = (lambda pr: (lambda X, Y: pr(*B(X, Y))))(pred)
        out.append((side, page_pred) + tuple(k[2:]))
    return out


def place_rest(bb, comps, fixed, placer, mod):
    """Pin-anchored parts, region parts, then every other part next to the placed IC it shares most nets with."""
    fps = bb.footprints
    base_inside = placer.inside
    done = set(fixed)
    warn = []

    def with_region(box, fn):
        if box is None:
            return fn()
        x0, y0, x1, y1 = box

        def ins(X, Y, side):
            x, y = B(X, Y)
            return base_inside(X, Y, side) and x0 <= x <= x1 and y0 <= y <= y1
        placer.inside = ins
        try:
            return fn()
        finally:
            placer.inside = base_inside

    for ref, (anchor, netname, r) in cfg(mod, "PIN_ANCHORS", {}).items():
        ic, _, padnum = anchor.partition(".")
        if ref not in fps or ref in done or ic not in fps:
            continue
        pads = [p for p in fps[ic].Pads() if net_short(p.GetNetname()) == netname
                and (not padnum or p.GetNumber() == padnum)]
        if not pads:
            warn.append(f"no pad {anchor} on {netname} for {ref}")
            continue
        X, Y = TO(pads[0].GetPosition().x), TO(pads[0].GetPosition().y)
        if not placer.place_near(fps[ref], X, Y, "F", max_r=r):
            if not placer.place_near(fps[ref], X, Y, "F", max_r=r + 6):
                warn.append(f"could not place {ref} near {anchor} {netname}")
                continue
            warn.append(f"{ref} is more than {r} mm from {anchor} {netname}")
        done.add(ref)
    for ref, (x, y, box) in cfg(mod, "REGIONS", {}).items():
        if ref in fps and ref not in done:
            if not with_region(box, lambda: placer.place_near(fps[ref], *P(x, y), "F", max_r=10)):
                if not placer.place_near(fps[ref], *P(x, y), "F", max_r=20):
                    warn.append(f"could not place {ref}")
                    continue
            done.add(ref)
    left = [r for r in fps if r in comps and r not in done]
    for ref in sorted(left, key=lambda r: (re.sub(r"\d+", "", r), refnum(r))):
        fp = fps[ref]
        anchors = [fps[r] for r in done if r in fps and fps[r].GetPadCount() >= 3]
        a = placer.anchor_for(fp, anchors)
        if a is None:
            warn.append(f"{ref}: no anchor shares a net; placed near the board centre")
            tx, ty = P(*cfg(mod, "CENTRE", (25.0, 30.0)))
        else:
            tx, ty = placer.target(fp, a)
        if not placer.place_near(fp, tx, ty, "F", max_r=30):
            warn.append(f"unplaced {ref}")
            continue
        done.add(ref)
    return warn


def generate(board, pours=True):
    mod = board_module(board)
    pcbgen.UUID_NAMESPACE = uuid_namespace(board)
    pdir = project_dir(board)
    netpath = os.path.join(pdir, project_name(board) + ".net")
    if not os.path.exists(netpath):
        raise SystemExit(f"{netpath} not found: run build.py --board {board} first")
    comps, nets = pcbgen.load_netlist(netpath)
    libdir = os.path.join(pdir, "lib", LIB + ".pretty")
    bb = pcbgen.BoardBuilder(mod.LAYERS, {LIB: libdir} if os.path.isdir(libdir) else {})
    rules = dict(mod.RULES)
    bb.rules(**rules)
    bb.set_origin(OX, OY)
    bb.board.GetDesignSettings().SetBoardThickness(MM(cfg(mod, "THICKNESS", 1.6)))
    allnets = [n for n in nets if not n.startswith("unconnected-")]
    nc_spec = netclasses(bb, mod, allnets)
    fixed_b = mod.fixed(comps)
    fixed = {r: (*P(x, y), rot, side) for r, (x, y, rot, side) in fixed_b.items()}
    bb.place_from_netlist(comps, nets, fixed, default=(*P(-30.0, -30.0), 0.0, "F"))
    outline = mod.outline()
    bb.polyline(pcbnew.Edge_Cuts, poly_page(outline), 0.1, closed=True)
    bb.edge_band_keepout(poly_page(outline), inset=rules["edge"])
    if mod.LAYERS == 4 and cfg(mod, "GND_PLANE", True):
        inner = [(x, y) for x, y in outline]
        z = bb.zone("GND", [pcbnew.In1_Cu], poly_page(inner), priority=0, clearance=0.3, name=PLANE_ZONE)
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_NEVER)
    mod.build(bb, comps)
    if hasattr(mod, "post_fixed"):
        mod.post_fixed(bb, comps)
    placer = Placer(bb.board, _inside_fn(mod, outline), _keepouts_page(mod), power_nets=("GND",))
    for ref in fixed:
        if ref in bb.footprints:
            placer.mark(bb.footprints[ref])
    warn = place_rest(bb, comps, fixed, placer, mod)
    for w in warn:
        print(f"[{board}] WARN placement: {w}")
    if hasattr(mod, "preroute"):
        mod.preroute(bb)
    for ref in fixed:
        if ref in bb.footprints:
            bb.footprints[ref].SetLocked(True)
    moved, hidden = silk.place_refs(bb.board, hide=cfg(mod, "HIDE_REFS", ("H", "FID")))
    print(f"[{board}] silk: {moved} references placed, {hidden} hidden (no room)")
    if pours:
        mod.pours(bb)
    out = pcb_path(board)
    write_project(out.replace(".kicad_pcb", ".kicad_pro"), mod, nc_spec)
    bb.save(out)
    set_layer_types(out, mod.LAYERS)
    if cfg(mod, "STACKUP"):
        set_stackup(out, mod.STACKUP)
    return out


# --------------------------------------------------------------------------- DRC
def drc(path, warnings=None, kicad_cli="kicad-cli"):
    rpt = path.replace(".kicad_pcb", "-drc.rpt")
    subprocess.run([kicad_cli, "pcb", "drc", "--severity-all", "--schematic-parity", "-o", rpt, path],
                   capture_output=True)
    counts, kind = {}, None
    with open(rpt, encoding="utf-8") as f:
        for line in f:
            if line.startswith("["):
                kind = line.split("]")[0] + "]"
            elif kind and line.startswith("    ") and ("; error" in line or "; warning" in line):
                target = counts if "; error" in line else warnings
                if target is not None:
                    target[kind] = target.get(kind, 0) + 1
                kind = None
    return rpt, counts


def report(board, path):
    warn = {}
    rpt, counts = drc(path, warn)
    print(f"[{board}] DRC errors:", counts or "none", "| warnings:", warn or "none", "->", rpt)
    return counts, warn


# --------------------------------------------------------------------------- routing (the caliper's flow)
def dsn_plane_as_layer_rule(dsn, net="GND", layer="In1.Cu"):
    with open(dsn, encoding="utf-8") as f:
        s = f.read()
    s, n = re.subn(r"(\(layer %s\s*\(type )power\)" % re.escape(layer), r"\1signal)", s)
    if not n:
        return
    while (i := s.find(f"(plane {net} ")) >= 0:
        s = s[:i] + s[_sexpr_end(s, i):]
    # The plane layer's no-track rule area (coupon_common.build) is exported as a wire_keepout on it. Every routed
    # class is limited to the other layers below (use_layer), so it adds nothing for Freerouting, and Freerouting
    # 2.1.0 then placed no via at all (a via crosses that layer): coupon-haptics, 2026-11-27, 0 vias and 74 connections
    # left with it, vias placed without it. The rule area stays on the board for the grid router and DRC.
    while (i := s.find(f'(wire_keepout "" (polygon {layer} ')) >= 0:
        s = s[:i] + s[_sexpr_end(s, i):]
    others = [m for m in re.findall(r"\(layer (\S+)\s*\(type", s) if m != layer]
    out, pos = [], 0
    for m in re.finditer(r"\(class (\S+)", s):
        start = m.start()
        end = _sexpr_end(s, start)
        block = s[start:end]
        nets_ = re.findall(r'"[^"]*"|[^\s()]+', block[:_class_head_end(block)])[2:]
        if nets_ != [net]:
            c = block.index("(circuit") + len("(circuit")
            block = block[:c] + f"\n        (use_layer {' '.join(others)})" + block[c:]
        out += [s[pos:start], block]
        pos = end
    out.append(s[pos:])
    with open(dsn, "w", encoding="utf-8") as f:
        f.write("".join(out))


def dsn_drop_net(dsn, net="GND"):
    """Take a net out of the routing job: its wires and vias stay as keep-outs."""
    with open(dsn, encoding="utf-8") as f:
        s = f.read()
    m = re.search(r"\(net %s\s" % re.escape(net), s)
    if not m:
        return
    s = s[:m.start()] + s[_sexpr_end(s, m.start()):]
    out, pos = [], 0
    for m in re.finditer(r"\(class (\S+)", s):
        if m.start() < pos:
            continue
        end = _sexpr_end(s, m.start())
        block = s[m.start():end]
        cut = _class_head_end(block)
        head, rest = block[:cut], block[cut:]
        names = re.findall(r'"[^"]*"|[^\s()]+', head)[2:]
        if net in names:
            names = [n for n in names if n != net]
            block = (f"(class {m.group(1)} {' '.join(names)}\n      " + rest) if names else ""
        out += [s[pos:m.start()], block]
        pos = end
    out.append(s[pos:])
    s = "".join(out)
    layers = re.findall(r"\(layer (\S+)\s*\(type", s)
    keep = []
    for m in list(re.finditer(r"\(wire \(path (\S+) ([0-9.]+) ([^)]*)\)\s*\(net %s\)[^\n]*" % re.escape(net), s))[::-1]:
        keep.append(f'    (keepout "" (path {m.group(1)} {m.group(2)} {m.group(3)}))')
        s = s[:m.start()] + s[m.end():]
    for m in list(re.finditer(r'\(via "([^"]+)"\s+([-0-9.]+) ([-0-9.]+)\s*\(net %s\)[^\n]*' % re.escape(net), s))[::-1]:
        dia = re.search(r"Via\[[0-9]+-[0-9]+\]_([0-9.]+):", m.group(1))
        d = float(dia.group(1)) if dia else 600.0
        keep += [f'    (keepout "" (circle {lay} {d:g} {m.group(2)} {m.group(3)}))' for lay in layers]
        s = s[:m.start()] + s[m.end():]
    st = s.find("(structure")
    end = _sexpr_end(s, st)
    s = s[:end - 1] + "\n".join(keep) + "\n  )" + s[end:]
    with open(dsn, "w", encoding="utf-8") as f:
        f.write(s)


def dsn_clearance_margin(dsn, margin_um=10):
    with open(dsn, encoding="utf-8") as f:
        s = f.read()
    s = re.sub(r"\(clearance ([0-9.]+)\)", lambda m: f"(clearance {float(m.group(1)) + margin_um:g})", s)
    with open(dsn, "w", encoding="utf-8") as f:
        f.write(s)


def dsn_add_keepouts(dsn, rects):
    """Add (layer name, [(x, y), ...] board mm) keep-outs to the DSN structure as polygons (DSN = page um, y negated)."""
    if not rects:
        return
    with open(dsn, encoding="utf-8") as f:
        s = f.read()
    assert "(resolution um" in s, "unexpected DSN units"
    out = []
    for layer, pts in rects:
        pp = [P(x, y) for x, y in pts]
        xy = " ".join(f"{1000.0 * X:.1f} {-1000.0 * Y:.1f}" for X, Y in pp + pp[:1])
        out.append(f'    (keepout "" (polygon {layer} 0 {xy}))')
    st = s.find("(structure")
    end = _sexpr_end(s, st)
    s = s[:end - 1] + "\n".join(out) + "\n  )" + s[end:]
    with open(dsn, "w", encoding="utf-8") as f:
        f.write(s)


def route(path, mod, minutes=10, threads=1, optimizer_passes=20, drop_nets=("GND",)):
    if not os.path.exists(FREEROUTING):
        raise SystemExit(f"Freerouting jar not found ({FREEROUTING}); set FREEROUTING_JAR")
    dsn = path.replace(".kicad_pcb", ".dsn")
    ses = path.replace(".kicad_pcb", ".ses")
    if os.path.exists(ses):
        os.remove(ses)
    pcbgen.export_dsn(path, dsn)
    if mod.LAYERS == 4:
        dsn_plane_as_layer_rule(dsn)
    for n in drop_nets:
        dsn_drop_net(dsn, n)
        if not re.fullmatch(r'[^\s()"]+', n):        # KiCad quotes a net name with spaces in the DSN
            dsn_drop_net(dsn, f'"{n}"')
    dsn_clearance_margin(dsn)
    dsn_add_keepouts(dsn, cfg(mod, "ROUTER_KEEPOUTS", []))
    log = path.replace(".kicad_pcb", ".freerouting.log")
    with open(log, "w") as lf:
        # Freerouting 2.1 can hang after its job timeout: give it the budget plus 10 minutes, then kill it
        try:
            subprocess.run(["java", "-jar", FREEROUTING, "-de", dsn, "-do", ses, "-mt", str(threads),
                            f"--router.job_timeout={minutes // 60:02d}:{minutes % 60:02d}:00",
                            f"--router.optimizer.max_passes={optimizer_passes}", "--gui.enabled=false"],
                           timeout=(minutes + 10) * 60, stdout=lf, stderr=subprocess.STDOUT)
        except subprocess.TimeoutExpired:
            print("WARN: Freerouting did not finish in time and was killed")
    if not os.path.exists(ses):
        print(f"WARN: Freerouting produced no session file (see {log})")
        return False
    pcbgen.import_ses(path, ses, path)
    for f in (dsn, ses):
        os.remove(f)
    return True


def enforce_keepouts(path):
    """Delete unlocked tracks / vias inside a no-track / no-via rule area (the grid router does not read them all)."""
    b = pcbnew.LoadBoard(path)
    zones = [z for z in b.Zones() if z.GetIsRuleArea() and (z.GetDoNotAllowTracks() or z.GetDoNotAllowVias())]
    gone = []
    for t in list(b.GetTracks()):
        if t.IsLocked():
            continue
        via = t.Type() == pcbnew.PCB_VIA_T
        for z in zones:
            if via:
                if z.GetDoNotAllowVias() and any(z.IsOnLayer(lay) for lay in (pcbnew.F_Cu, pcbnew.B_Cu)) and \
                        z.Outline().Collide(t.GetPosition(), t.GetWidth(pcbnew.F_Cu) // 2):
                    break
            elif z.GetDoNotAllowTracks() and z.IsOnLayer(t.GetLayer()):
                a, c = t.GetStart(), t.GetEnd()
                n = max(1, int((c - a).EuclideanNorm() / MM(0.05)))
                if any(z.Outline().Collide(pcbnew.VECTOR2I(a.x + (c.x - a.x) * k // n, a.y + (c.y - a.y) * k // n),
                                           t.GetWidth() // 2) for k in range(n + 1)):
                    break
        else:
            continue
        gone.append(t.GetNetname())
        b.Delete(t)
    pcbnew.SaveBoard(path, b)
    return gone


def remove_vias_in_pads(path):
    """Delete every unlocked via whose ring lands on an SMD pad."""
    b = pcbnew.LoadBoard(path)
    pads = [p for fp in b.GetFootprints() for p in fp.Pads()
            if p.GetAttribute() in (pcbnew.PAD_ATTRIB_SMD, pcbnew.PAD_ATTRIB_CONN)]
    gone = []
    for v in list(b.GetTracks()):
        if v.Type() != pcbnew.PCB_VIA_T or v.IsLocked():
            continue
        hit = next((p for p in pads if p.HitTest(v.GetPosition(), v.GetWidth(pcbnew.F_Cu) // 2)), None)
        if hit is not None:
            gone.append(f"{net_short(v.GetNetname())}@{hit.GetParentFootprint().GetReference()}.{hit.GetNumber()}")
            b.Delete(v)
    pcbnew.SaveBoard(path, b)
    return gone


def prune_dangling(path, protected=(), rounds=6):
    """Remove dangling tracks / vias that DRC reports, whole dead branches first, keeping the board's connections."""
    removed = 0
    for _ in range(rounds):
        rpt, before = drc(path)
        before = before.get("[unconnected_items]", 0)
        spots, kind = [], None
        for line in open(rpt, encoding="utf-8"):
            if line.startswith("["):
                kind = line[1:].split("]")[0]
            elif kind in ("track_dangling", "via_dangling") and line.strip().startswith("@("):
                xy = line.split("@(")[1].split(")")[0].replace("mm", "").split(",")
                m = re.search(r" on (\S+), length ([0-9.]+) mm", line)
                spots.append((kind, float(xy[0]), float(xy[1]), m.group(1) if m else None,
                              float(m.group(2)) if m else None))
                kind = None
        if not spots:
            break
        backup = path + ".bak"
        shutil.copyfile(path, backup)
        doomed = []
        for whole_branch in (True, False):
            b = pcbnew.LoadBoard(path)
            doomed = []
            for kind, x, y, layer, length in spots:
                p = pcbnew.VECTOR2I(MM(x), MM(y))
                for t in b.GetTracks():
                    if t in doomed or (t.IsLocked() and net_short(t.GetNetname()) in protected):
                        continue
                    if kind == "via_dangling" and t.Type() == pcbnew.PCB_VIA_T and \
                            (t.GetStart() - p).EuclideanNorm() < 2000:
                        doomed.append(t)
                    elif kind == "track_dangling" and t.Type() == pcbnew.PCB_TRACE_T and \
                            b.GetLayerName(t.GetLayer()) == layer and abs(TO(t.GetLength()) - length) < 0.002 and \
                            min((t.GetStart() - p).EuclideanNorm(), (t.GetEnd() - p).EuclideanNorm()) < 2000:
                        doomed.append(t)
                        if whole_branch:
                            doomed += pcbgen.dead_branch(b, t, p)
            if not doomed:
                break
            gone = set()
            for t in doomed:
                if t.m_Uuid.AsString() not in gone:
                    gone.add(t.m_Uuid.AsString())
                    b.Delete(t)
            pcbnew.SaveBoard(path, b)
            pcbgen.refill(path)
            _, after = drc(path)
            if after.get("[unconnected_items]", 0) <= before:
                break
            shutil.copyfile(backup, path)
            doomed = []
        os.remove(backup)
        if not doomed:
            break
        removed += len(doomed)
    return removed


def gnd_plane_fixup(path):
    """A via to the In1 plane for every GND pad whose copper does not reach it yet."""
    b = pcbnew.LoadBoard(path)
    net = b.FindNet("GND")
    if net is None:
        return 0, []
    lonely = []
    for cl in finish_route.net_clusters(b, net.GetNetCode(), (pcbnew.In1_Cu,)):
        on_plane = any(isinstance(it, pcbnew.PAD) and it.GetAttribute() == pcbnew.PAD_ATTRIB_PTH or
                       not isinstance(it, pcbnew.PAD) and it.Type() == pcbnew.PCB_VIA_T for it in cl)
        if not on_plane:
            lonely += [it for it in cl if isinstance(it, pcbnew.PAD)]
    done, left = pcbgen.fanout_vias(b, "GND", pads=lonely) if lonely else (0, [])
    if left:
        more, left = pcbgen.fanout_vias(b, "GND", pads=left, via=0.45, drill=0.2, track=0.2, max_dist=3.0)
        done += more
    pcbnew.SaveBoard(path, b)
    pcbgen.refill(path)
    return done, left


def complete_routing(board, mod, out):
    """The grid router (tools/finish_route.py) for what Freerouting left open; pours come off first."""
    b = pcbnew.LoadBoard(out)
    pours = [z for z in b.Zones() if not z.GetIsRuleArea() and z.GetZoneName() != PLANE_ZONE]
    gnd_ends = {(p.x, p.y) for t in b.GetTracks() if t.GetNetname() == "GND" and t.Type() != pcbnew.PCB_VIA_T
                for p in (t.GetStart(), t.GetEnd())}
    bare = [t for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T and t.GetNetname() == "GND" and not t.IsLocked()
            and (t.GetPosition().x, t.GetPosition().y) not in gnd_ends]
    for z in pours:
        b.Delete(z)
    for v in bare:
        b.Delete(v)
    if pours or bare:
        print(f"[{board}] removed {len(pours)} pours and {len(bare)} stitching vias before routing")
    shim = types.SimpleNamespace(board=b)
    for layer, pts in cfg(mod, "ROUTER_KEEPOUTS", []):
        lay = {"F.Cu": pcbnew.F_Cu, "In1.Cu": pcbnew.In1_Cu, "In2.Cu": pcbnew.In2_Cu, "B.Cu": pcbnew.B_Cu}[layer]
        pcbgen.BoardBuilder.keepout(shim, [lay], poly_page(pts), tracks=True, vias=False, pads=False, pours=False,
                                    name=TEMP_KEEPOUT)
    pcbnew.SaveBoard(out, b)
    gone = enforce_keepouts(out)
    if gone:
        print(f"[{board}] removed {len(gone)} tracks/vias inside keep-outs: {sorted(set(gone))}")
    gone = remove_vias_in_pads(out)
    if gone:
        print(f"[{board}] removed {len(gone)} vias sitting on SMD pads: {gone}")
    if mod.LAYERS == 4:
        done, left = gnd_plane_fixup(out)
        if done or left:
            print(f"[{board}] GND plane fix-up: {done} pads given a via, {len(left)} without room")
    left = finish_route.finish(out, log=lambda m: print(f"[{board}] {m}", flush=True), max_rounds=40)
    print(f"[{board}] finish_route: {left} unconnected")
    b = pcbnew.LoadBoard(out)
    for z in [z for z in b.Zones() if z.GetZoneName() == TEMP_KEEPOUT]:
        b.Remove(z)
    pcbnew.SaveBoard(out, b)
    return left


def add_pours(board, mod, path):
    bb = pcbgen.BoardBuilder.load(path)
    mod.pours(bb)
    bb.save(path)


def finish(board, mod, path):
    b = pcbnew.LoadBoard(path)
    finish_route.anchor_all(b)
    dups, trimmed = pcbgen.dedupe_tracks(b), pcbgen.trim_dangling(b)
    zero = [t for t in b.GetTracks() if t.Type() == pcbnew.PCB_TRACE_T and t.GetLength() == 0]
    for t in zero:            # KiCad 10 reports a zero-length segment near another net as tracks_crossing
        b.Delete(t)
    dups += len(zero)
    pcbnew.SaveBoard(path, b)
    b = pcbgen.refill(path)
    debris = pcbgen.remove_debris(b)
    pcbnew.SaveBoard(path, b)
    b = pcbgen.refill(path)
    stitched = 0
    if mod.LAYERS == 4:
        v, d = cfg(mod, "GND_VIA", (0.6, 0.3))
        prio = mod.stitch_priority(b) if hasattr(mod, "stitch_priority") else []
        stitched = pcbgen.stitch_vias(b, "GND", pitch=cfg(mod, "STITCH_PITCH", 3.0), via=v, drill=d, priority=prio)
    moved, hidden = silk.place_refs(b, hide=cfg(mod, "HIDE_REFS", ("H", "FID")))
    pcbnew.SaveBoard(path, b)
    pcbgen.refill(path)
    pruned = prune_dangling(path, cfg(mod, "PROTECTED_NETS", ()))
    print(f"[{board}] finish: {dups} duplicate tracks, {trimmed} stubs trimmed, {debris + pruned} debris items removed, "
          f"{stitched} GND stitching vias, {moved} references placed, {hidden} hidden")


def route_board(board, mod, out, minutes, attempts, resume=False):
    drop = ("GND",) if mod.LAYERS == 4 else ()
    # PREROUTED_NETS (board module, short names): nets whose copper the module pre-routes and locks in full. They are
    # taken out of Freerouting's job like GND (their copper stays as keep-outs): a fixed wire that only passes over a
    # pad does not connect it in Freerouting's model, which then lays a second, Default-width route beside it.
    pre = set(cfg(mod, "PREROUTED_NETS", ()))
    if pre:
        names = {p.GetNetname() for fp in pcbnew.LoadBoard(out).GetFootprints() for p in fp.Pads()}
        drop += tuple(sorted(n for n in names if n and net_short(n) in pre))
    if mod.LAYERS == 4 and not resume:
        b = pcbnew.LoadBoard(out)
        v, d = cfg(mod, "GND_VIA", (0.6, 0.3))
        done, left = pcbgen.fanout_vias(b, "GND", via=v, drill=d)
        pcbnew.SaveBoard(out, b)
        pcbgen.refill(out)
        print(f"[{board}] GND fan-out: {done} pads, {len(left)} without room:",
              [(p.GetParentFootprint().GetReference(), p.GetNumber()) for p in left])
    left = None
    for attempt in range(attempts):
        route(out, mod, minutes * (attempt + 1), drop_nets=drop)
        _, counts = drc(out)
        left = counts.get("[unconnected_items]", 0)
        print(f"[{board}] route attempt {attempt + 1}: {left} unconnected")
        if not left:
            break
    for _ in range(3):   # grid router for what Freerouting left; the clean-up can open a joint: repeat
        if left:
            complete_routing(board, mod, out)
        add_pours(board, mod, out)
        finish(board, mod, out)
        _, counts = drc(out)
        left = counts.get("[unconnected_items]", 0)
        if not left:
            break
    print(f"[{board}] routed: {left} unconnected")
    return left


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", required=True, choices=sorted(PROJECTS))
    ap.add_argument("--route", action="store_true", help="route (Freerouting + grid router) and finish")
    ap.add_argument("--minutes", type=int, default=5, help="Freerouting budget of the first attempt")
    ap.add_argument("--attempts", type=int, default=2, help="Freerouting attempts (each one longer)")
    ap.add_argument("--place-only", action="store_true", help="place and save without pours (no routing)")
    ap.add_argument("--resume", action="store_true", help="route the board on disk again (no regeneration)")
    ap.add_argument("--complete", action="store_true", help="grid router + pours + finish on the board on disk")
    ap.add_argument("--finish", action="store_true", help="only the clean-up and pours on the board on disk")
    a = ap.parse_args()
    board = a.board
    mod = board_module(board)
    out = pcb_path(board)
    if a.finish:
        finish(board, mod, out)
    elif a.complete:
        for _ in range(3):
            complete_routing(board, mod, out)
            add_pours(board, mod, out)
            finish(board, mod, out)
            _, counts = drc(out)
            if not counts.get("[unconnected_items]", 0):
                break
    else:
        routing = (a.route or a.resume) and cfg(mod, "ROUTE", True)
        if not a.resume:
            out = generate(board, pours=not routing and not a.place_only)
            print(f"[{board}] placed ->", out)
        if routing:
            route_board(board, mod, out, a.minutes, a.attempts, resume=a.resume)
    counts, _ = report(board, out)
    return 1 if counts else 0


if __name__ == "__main__":
    sys.exit(main())
