"""Synthetic coupons for the rules tests: a small, correct coupon, and helpers that break one thing at a time.

* good_spec() -> a netlist spec {comps, nets}: J1 (the 2 x 20 header), U1 (M24C02 at 0x50, WC held low by R1, JP1
  to +3V3), the bulk and decoupling capacitors, a Hall sensor U10 on AN0, an I2C haptic driver U11 at 0x5A whose
  interrupt pulls IRQ_N (pull-up R2 to +3V3) and whose supply is +5V.
* good_desc() -> the matching descriptor JSON.
* write_net(path, spec): the spec as a KiCad 10 s-expression netlist (the format `kicad-cli sch export netlist`
  writes, version "E"), read back by coupon_model.read_netlist like a real one.
* write_board(path, spec, ...): a .kicad_pcb built with pcbnew from the same spec, with the outline, the header on
  the bottom at its slot position, the M3 post hole and a filled In1 GND plane; keyword arguments move or break one
  thing (size, header shift / rotation / side, hole position, a stray track, a part at the post, a bottom part).

Everything here is synthetic: it tests the checker's logic and its readers, not any real coupon.
"""

from __future__ import annotations

import copy
import os

import pytest

try:
    import pcbnew as _pcbnew  # noqa: F401
    HAVE_PCBNEW = True
except ImportError:
    HAVE_PCBNEW = False

needs_pcbnew = pytest.mark.skipif(not HAVE_PCBNEW, reason="pcbnew (KiCad 10 Python) not importable")

FP_DIR = os.environ.get("KICAD10_FOOTPRINT_DIR", "/usr/share/kicad/footprints")

HEADER_PINS = [(str(n), f"Pin_{n}", "passive") for n in range(1, 41)]
EEPROM_PINS = [("1", "E0", "input"), ("2", "E1", "input"), ("3", "E2", "input"), ("4", "VSS", "power_in"),
               ("5", "SDA", "bidirectional"), ("6", "SCL", "input"), ("7", "~{WC}", "input"), ("8", "VCC", "power_in")]
R_PINS = [("1", "~", "passive"), ("2", "~", "passive")]
SENSOR_PINS = [("1", "VCC", "power_in"), ("2", "OUT", "output"), ("3", "GND", "power_in")]
DRIVER_PINS = [("1", "VDD", "power_in"), ("2", "GND", "power_in"), ("3", "SDA", "bidirectional"),
               ("4", "SCL", "input"), ("5", "INT", "open_collector")]

FOOTPRINTS = {
    "J1": "Connector_PinHeader_2.54mm:PinHeader_2x20_P2.54mm_Vertical",
    "U1": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
    "R": "Resistor_SMD:R_0603_1608Metric", "C": "Capacitor_SMD:C_0603_1608Metric",
    "JP": "Jumper:SolderJumper-2_P1.3mm_Open_RoundedPad1.0x1.5mm",
    "U10": "Package_TO_SOT_SMD:SOT-23", "U11": "Package_TO_SOT_SMD:SOT-23-5",
    "H1": "MountingHole:MountingHole_3.2mm_M3",
}
# where write_board puts the parts (board mm, top side): away from the post, the header tails and each other
PLACES = {"U1": (41.0, 14.0), "R1": (46.0, 14.0), "JP1": (46.0, 18.0), "C1": (14.0, 11.0), "C3": (36.0, 14.0),
          "C10": (20.0, 16.0), "U10": (20.0, 20.0), "U11": (30.0, 25.0), "R2": (36.0, 25.0), "C11": (30.0, 30.0)}


def _comp(ref, lib, part, value, fp, pins, fields=None):
    return {"ref": ref, "lib": lib, "part": part, "value": value, "footprint": fp, "pins": pins,
            "fields": fields or {}}


def good_spec():
    comps = {
        "J1": _comp("J1", "Connector_Generic", "Conn_02x20_Odd_Even", "SLOT", FOOTPRINTS["J1"], HEADER_PINS),
        "U1": _comp("U1", "Memory_EEPROM", "M24C02-WMN", "M24C02-WMN6TP", FOOTPRINTS["U1"], EEPROM_PINS),
        "R1": _comp("R1", "Device", "R", "100k", FOOTPRINTS["R"], R_PINS),
        "JP1": _comp("JP1", "Jumper", "SolderJumper_2_Open", "WP", FOOTPRINTS["JP"], R_PINS),
        "C1": _comp("C1", "Device", "C", "10u", FOOTPRINTS["C"], R_PINS),
        "C3": _comp("C3", "Device", "C", "100n", FOOTPRINTS["C"], R_PINS),
        "C10": _comp("C10", "Device", "C", "100n", FOOTPRINTS["C"], R_PINS),
        "U10": _comp("U10", "Sensor_Magnetic", "TMAG5253", "TMAG5253", FOOTPRINTS["U10"], SENSOR_PINS),
        "U11": _comp("U11", "Driver_Haptic", "DRV2605L", "DRV2605L", FOOTPRINTS["U11"], DRIVER_PINS),
        "R2": _comp("R2", "Device", "R", "10k", FOOTPRINTS["R"], R_PINS),
        "C11": _comp("C11", "Device", "C", "1u", FOOTPRINTS["C"], R_PINS),
        "H1": _comp("H1", "Mechanical", "MountingHole", "M3", FOOTPRINTS["H1"], []),
    }
    nets = {
        "+5V": [("J1", "1"), ("J1", "2"), ("J1", "3"), ("U11", "1"), ("C11", "1")],
        "+3V3": [("J1", "7"), ("J1", "8"), ("U1", "8"), ("C1", "1"), ("C3", "1"), ("C10", "1"), ("U10", "1"),
                 ("JP1", "2"), ("R2", "1")],
        "GND": [("J1", str(p)) for p in (4, 5, 6, 9, 10, 12, 14, 16, 18, 21, 22, 26, 32, 40)]
        + [("U1", "1"), ("U1", "2"), ("U1", "3"), ("U1", "4"), ("R1", "2"), ("C1", "2"), ("C3", "2"), ("C10", "2"),
           ("U10", "3"), ("U11", "2"), ("C11", "2")],
        "AN0": [("J1", "11"), ("U10", "2")],
        "SCL": [("J1", "29"), ("U1", "6"), ("U11", "4")],
        "SDA": [("J1", "30"), ("U1", "5"), ("U11", "3")],
        "IRQ_N": [("J1", "31"), ("U11", "5"), ("R2", "2")],
        "/Slot/EE_WC": [("U1", "7"), ("R1", "1"), ("JP1", "1")],
    }
    used = {p for mem in nets.values() for r, p in mem if r == "J1"}
    for n in range(1, 41):
        if str(n) not in used:
            nets[f"unconnected-(J1-Pin_{n}-Pad{n})"] = [("J1", str(n))]
    return {"comps": comps, "nets": nets}


def good_desc():
    return {
        "board": "fixture", "type": "hall", "rev": "A", "size": "standard", "default_slot": 1,
        "needs": [], "serial": 0, "date": "2026-11-27", "git": "0123456789abcdef",
        "uses": ["+3V3", "+5V", "AN0", "SCL", "SDA", "IRQ_N"],
        "i2c": {"max_khz": 400},
        "rails": {"+3V3": {"typ_ma": 10, "max_ma": 20, "bulk_uf": 10.2, "startup_ms": 1},
                  "+5V": {"typ_ma": 5, "max_ma": 30, "bulk_uf": 1.0, "startup_ms": 0}},
        "lanes": {"AN0": {"kind": "hall", "unit": "mT", "flags": ["ratiometric", "bipolar"], "sites": 1,
                          "r_src_ohm": 10, "cload_max_pf": 0, "offset": 0.5, "gain": 100.0}},
        "devices": [{"part": "drv2605l", "bus": "i2c", "addr": "0x5A", "count": 1, "irq": "irq_n"},
                    {"part": "tmag5253", "bus": "analog", "addr": ["AN0"], "count": 1}],
        "ext": {"format": "none"},
    }


# ----------------------------------------------------------------------------------------------- spec edits
def clone(spec):
    return copy.deepcopy(spec)


def move_pin(spec, ref, pin, net):
    """Put (ref, pin) on `net` (None: unconnected), taking it off its old net."""
    for name in list(spec["nets"]):
        spec["nets"][name] = [m for m in spec["nets"][name] if m != (ref, str(pin))]
        if not spec["nets"][name]:
            del spec["nets"][name]
    if net is None:
        spec["nets"][f"unconnected-({ref}-Pad{pin})"] = [(ref, str(pin))]
    else:
        spec["nets"].setdefault(net, []).append((ref, str(pin)))
    return spec


def remove_comp(spec, ref):
    del spec["comps"][ref]
    for name in list(spec["nets"]):
        spec["nets"][name] = [m for m in spec["nets"][name] if m[0] != ref]
        if not spec["nets"][name]:
            del spec["nets"][name]
    return spec


def mark_dnp(spec, ref):
    """Mark a part DNP, as KiCad 10's netlist writes it: a `dnp` property with no value."""
    spec["comps"][ref]["fields"]["dnp"] = ""
    return spec


def add_comp(spec, ref, kind, value, pin_nets, lib="Device", part=None, pins=None):
    pins = pins or R_PINS
    spec["comps"][ref] = _comp(ref, lib, part or kind, value, FOOTPRINTS.get(kind, FOOTPRINTS["R"]), pins)
    for pin, net in pin_nets.items():
        spec["nets"].setdefault(net, []).append((ref, str(pin)))
    return spec


# ------------------------------------------------------------------------------------------------- netlist
def _q(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def write_net(path, spec):
    comps, nets = spec["comps"], spec["nets"]
    pin_type = {(c["ref"], num): typ for c in comps.values() for num, _nm, typ in c["pins"]}
    pin_name = {(c["ref"], num): nm for c in comps.values() for num, nm, _t in c["pins"]}
    L = ["(export", '\t(version "E")', "\t(design", '\t\t(tool "synthetic fixture")', "\t)", "\t(components"]
    for c in comps.values():
        L += ["\t\t(comp", f"\t\t\t(ref {_q(c['ref'])})", f"\t\t\t(value {_q(c['value'])})",
              f"\t\t\t(footprint {_q(c['footprint'])})", "\t\t\t(fields"]
        for k, v in c["fields"].items():
            L.append(f"\t\t\t\t(field (name {_q(k)}) {_q(v)})")
        L += ["\t\t\t)", f"\t\t\t(libsource (lib {_q(c['lib'])}) (part {_q(c['part'])}) (description \"\"))",
              "\t\t)"]
    L += ["\t)", "\t(libparts"]
    seen = set()
    for c in comps.values():
        key = (c["lib"], c["part"])
        if key in seen:
            continue
        seen.add(key)
        L += ["\t\t(libpart", f"\t\t\t(lib {_q(c['lib'])})", f"\t\t\t(part {_q(c['part'])})", "\t\t\t(pins"]
        for num, nm, typ in c["pins"]:
            L.append(f"\t\t\t\t(pin (num {_q(num)}) (name {_q(nm)}) (type {_q(typ)}))")
        L += ["\t\t\t)", "\t\t)"]
    L += ["\t)", "\t(nets"]
    for code, (name, mem) in enumerate(sorted(nets.items()), 1):
        L += ["\t\t(net", f"\t\t\t(code {_q(code)})", f"\t\t\t(name {_q(name)})", '\t\t\t(class "Default")']
        for ref, pin in mem:
            L.append(f"\t\t\t(node (ref {_q(ref)}) (pin {_q(pin)}) "
                     f"(pinfunction {_q(pin_name.get((ref, pin), '') + '_' + pin)}) "
                     f"(pintype {_q(pin_type.get((ref, pin), 'passive'))}))")
        L.append("\t\t)")
    L += ["\t)", ")", ""]
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(L))
    return path


# --------------------------------------------------------------------------------------------------- board
def write_board(path, spec, size=(58.0, 60.0), header_shift=(0.0, 0.0), header_rot=None, header_side="B",
                post_xy=None, stray_track=False, part_at_post=False, bottom_part=False, fill=True,
                pad_net_override=None):
    """Build a .kicad_pcb from the spec with pcbnew. Every keyword breaks one rule when set."""
    import pcbnew

    from boards import coupon_common as cc
    from boards.geom import V

    b = pcbnew.BOARD()
    b.SetCopperLayerCount(4)
    b.GetDesignSettings().SetBoardThickness(pcbnew.FromMM(1.6))
    nets = {}
    for name in spec["nets"]:
        if name.startswith("unconnected-"):
            continue
        ni = pcbnew.NETINFO_ITEM(b, name)
        b.Add(ni)
        nets[name] = ni
    pad_net = {m: n for n, mem in spec["nets"].items() for m in mem if not n.startswith("unconnected-")}
    pad_net.update(pad_net_override or {})
    w, h = size
    corners = [(0, 0), (w, 0), (w, h), (0, h)]
    for i in range(4):
        s = pcbnew.PCB_SHAPE(b)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetStart(V(*corners[i]))
        s.SetEnd(V(*corners[(i + 1) % 4]))
        s.SetWidth(pcbnew.FromMM(0.1))
        b.Add(s)
    b.GetDesignSettings().SetAuxOrigin(V(0, 0))

    def place(ref, fpid, x, y, rot=0.0, side="F"):
        lib, name = fpid.split(":", 1)
        fp = pcbnew.FootprintLoad(os.path.join(FP_DIR, lib + ".pretty"), name)
        fp.SetFPID(pcbnew.LIB_ID(lib, name))         # FootprintLoad leaves the library nickname empty
        fp.SetReference(ref)
        b.Add(fp)
        if side == "B":
            fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
        fp.SetPosition(V(x, y))
        fp.SetOrientationDegrees(rot)
        for p in fp.Pads():
            n = pad_net.get((ref, p.GetNumber()))
            if n in nets:
                p.SetNet(nets[n])
        return fp

    hx, hy, hrot, _side = cc.header_placement()
    place("J1", spec["comps"]["J1"]["footprint"], hx + header_shift[0], hy + header_shift[1],
          hrot if header_rot is None else header_rot, header_side)
    px, py = post_xy or cc.POST
    if "H1" in spec["comps"]:
        place("H1", FOOTPRINTS["H1"], px, py)
    for ref, c in spec["comps"].items():
        if ref in ("J1", "H1"):
            continue
        x, y = PLACES.get(ref, (25.0, 38.0 + 3 * (sum(map(ord, ref)) % 5)))
        place(ref, c["footprint"], x, y)
    if part_at_post:
        place("R99", FOOTPRINTS["R"], cc.POST[0] + 2.0, cc.POST[1] - 0.5)
    if bottom_part:
        place("C99", FOOTPRINTS["C"], 30.0, 40.0, side="B")
    if stray_track:
        t = pcbnew.PCB_TRACK(b)
        t.SetStart(V(cc.POST[0] + 1.5, cc.POST[1]))
        t.SetEnd(V(cc.POST[0] + 5.0, cc.POST[1]))
        t.SetWidth(pcbnew.FromMM(0.2))
        t.SetLayer(pcbnew.F_Cu)
        t.SetNet(nets["GND"])
        b.Add(t)
    # the In1 GND plane, kept 0.3 mm from the edge and clear of the post (as boards/coupon_common.py draws it)
    z = pcbnew.ZONE(b)
    z.SetLayer(pcbnew.In1_Cu)
    z.SetNet(nets["GND"])
    ol = z.Outline()
    ol.NewOutline()
    for x, y in [(0.3, 0.3), (w - 0.3, 0.3), (w - 0.3, h - 0.3), (0.3, h - 0.3)]:
        ol.Append(V(x, y))
    b.Add(z)
    ka = pcbnew.ZONE(b)
    ka.SetIsRuleArea(True)
    ka.SetLayerSet(pcbnew.LSET.AllCuMask())
    ka.SetDoNotAllowTracks(True)
    ka.SetDoNotAllowVias(True)
    ka.SetDoNotAllowZoneFills(True)
    ka.SetDoNotAllowPads(False)
    ka.SetDoNotAllowFootprints(False)
    import math
    kol = ka.Outline()
    kol.NewOutline()
    for k in range(36):
        a = 2 * math.pi * k / 36
        kol.Append(V(cc.POST[0] + cc.POST_COPPER_R * math.cos(a), cc.POST[1] + cc.POST_COPPER_R * math.sin(a)))
    b.Add(ka)
    if fill:
        b.BuildConnectivity()                         # the filler needs it, or the fill comes out empty
        pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(path, b)
    return path
