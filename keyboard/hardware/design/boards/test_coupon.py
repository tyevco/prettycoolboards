"""Test coupon layout: standard coupon, 58 x 60 mm, 4 layers (boards/coupon_common.py has the shared geometry).

Floor plan (board mm, top view, the slot edge at y = 0):

* J1 on the bottom along the slot edge (coupon_common); the lane ladder R30-R34 right above the lane pins (AN0-AN3,
  x 17.6-25.2), one 499 Ohm 0.1 % resistor between each pair of taps.
* The loads on the left, next to the rail pins (+5V x 4.9-7.4, +3V3 x 12.5): the +5V loads first (G3's three
  parallel 2512s stacked, G2's series row), the +3V3 loads above them (G1's stack, G0's row), each MOSFET at the end
  of its string with its drain toward it. The 11 x 2512 spread up to 1.4 W (G3 limited at the TPS2553's typical trip)
  over about 20 cm^2 of the left half (estimate).
* The logic on the right, next to the SPI / I2C / G-line pins (x 32.8-50.6): U1 (EEPROM) over SCL/SDA, U11 and U10
  over the SPI pins with their input pulls (R35-R39), the IRQ_N transistors over IRQ_N, the status LED near the
  top-right corner where it shows.
* The wire pads TP1-TP4 and the probe pads TP10-TP21 along the top edge, labelled on the silk.

**Current paths (review 2026-11-27).** The first layout routed every rail at the Default 0.20 mm: the project file
lost its net classes (layout.write_project, fixed), so +5V ran 54 mm on 0.5 oz In2 at 0.20 mm, about 0.2 A for a
10 K rise (IPC-2221, estimate), under G3's 0.52-0.64 A limit test and far under the 2.0-2.5 A of the S5 breaker test
on the wire pads. A net class does not fix that on its own: Freerouting 2.1.0 lays every net at the DSN's default
width and ignores the class rules (tested 2026-11-27: the same job routed +3V3, class width 0.40 mm, at 0.20 mm, and
everything at 0.30 mm once only the default was raised), so a class width reaches only what tools/finish_route.py
lays. The paths whose current matters are pre-routed instead. Now:

* **+5V is pre-routed and locked on the outer layers** (`preroute`), so no router puts it on an inner layer: F.Cu
  1.5 mm from J1 pins 1-3 up past C2 and G3's three +5V pads to G2's first resistor (the load currents, at most
  0.64 A limited on S1-S4); B.Cu 2.0 mm from J1 pins 1-3 up the left edge and across to TP2 (the external-load path,
  about 3.9 A for a 10 K rise on 1 oz outer copper, IPC-2221 estimate, so the S5 breaker's 2.46 A maximum trip is
  carried; the test is short). G3's drain net LOAD3_D is pre-routed on F.Cu at 1.0 mm.
* **+3V3 and the other load strings are routed at the Default 0.20 mm.** They carry at most G1's 335 mA (the
  TPS2553's maximum trip): about 2 K over ambient on 1 oz outer copper (IPC-2221, estimate), and on In2 the track
  sits inside the +3V3 pour. The pour, not the tracks, carries most of the +3V3 current to the ladder and the loads.
* **In1 carries no track** (coupon_common's rule area): it is the solid GND plane under the lanes (SPEC §4.9).
"""

import pcbnew

from boards import coupon_common as cc
from boards.geom import P, V, bxy

SIZE = cc.STANDARD
LAYERS, THICKNESS = cc.LAYERS, cc.THICKNESS
STACKUP = cc.STACKUP
RULES = cc.RULES
# (name, nets, track, clearance, via, drill). Only the pre-routed nets get a class (their width, for an interactive
# edit; Freerouting ignores class rules, see above). Clearance stays the Default 0.15 mm: a class clearance above it
# is checked by DRC but not kept by Freerouting, so it only produces violations (29 in the first re-route).
NETCLASSES = [
    ("Rail5V", ["+5V"], 1.00, 0.15, 0.80, 0.40),
    ("Load", ["LOAD3_D"], 1.00, 0.15, 0.80, 0.40),
]
GND_VIA = cc.GND_VIA
STITCH_PITCH = 3.0
ROUTE = True
CENTRE = (29.0, 30.0)
HIDE_REFS = ("H", "FID", "TP")              # the pads carry net labels on the silk instead
PROTECTED_NETS = ("+5V", "LOAD3_D")         # the pre-routes are locked: never pruned as debris
PREROUTED_NETS = ("+5V", "LOAD3_D")         # joined in full by preroute(): out of Freerouting's job (layout.py)

FAB_NOTES = [
    "**Test coupon (SPEC §10 step 7):** the loads on G0-G3 deliberately exceed the coupon rules (250 mA on +3V3, "
    "500 mA on +5V) to exercise the slot switches; **G3 (3.33 Ohm on +5V) is for S1-S4 only**: on S5 the 2 A "
    "breaker would let it draw 1.5 A, 2.5 W per 1 W resistor (sheets/test_coupon.py; the silk next to the load "
    "says G3: S1-S4 ONLY).",
    "**JP1 (WP)** is an open solder jumper: leave it open to write the descriptor EEPROM, then bridge it with solder "
    "to write-protect it.",
    "**Copper for the loads:** +5V pre-routed on the outer layers (1.5 mm F.Cu to the loads, 2.0 mm B.Cu to the TP2 "
    "wire pad, for an external load up to the S5 breaker's 2.46 A maximum trip, briefly), G3's drain 1.0 mm F.Cu; "
    "+3V3 and the other load strings (335 mA at most) 0.20 mm with the In2 +3V3 pour; In1 carries no track "
    "(boards/test_coupon.py).",
] + cc.FAB_NOTES

PROBE_PADS = ["AN0", "AN1", "AN2", "AN3", "SYNC", "INJ", "IRQ_N", "SCK", "MISO", "MOSI", "CS0_N", "CS1_N"]
PROBE_Y, PROBE_X0, PROBE_DX = 57.0, 28.0, 2.2

# x, y, KiCad orientation, side. SOT-23 at 180: drain (pin 3) toward -x, gate and source toward +x.
_FIXED = {
    # +5V current-limit load G3: three 10R in parallel, stacked; Q13 to the right. Pad 1 (+5V) at x 5.04
    "R22": (8.0, 13.0, 0.0), "R23": (8.0, 17.0, 0.0), "R24": (8.0, 21.0, 0.0), "Q13": (14.6, 17.0, 180.0),
    # +5V bulk on the +5V trunk: pad 1 at (5.04, 8.8), pad 2 (GND) at (6.94, 8.8)
    "C2": (5.99, 8.8, 0.0),
    # +5V calibration load G2: three 10R in series, a row
    "R19": (6.0, 26.0, 0.0), "R20": (14.2, 26.0, 0.0), "R21": (22.4, 26.0, 0.0), "Q12": (28.6, 26.0, 180.0),
    # +3V3 current-limit load G1: two 10R in parallel, stacked
    "R17": (8.0, 32.0, 0.0), "R18": (8.0, 36.0, 0.0), "Q11": (14.6, 34.0, 180.0),
    # +3V3 calibration load G0: three 10R in series, a row
    "R14": (6.0, 42.0, 0.0), "R15": (14.2, 42.0, 0.0), "R16": (22.4, 42.0, 0.0), "Q10": (28.6, 42.0, 180.0),
    # lane ladder: pin 1 (the higher tap) toward +x, between the lane pins
    "R30": (16.3, 10.5, 180.0), "R31": (19.3, 10.5, 180.0), "R32": (22.3, 10.5, 180.0), "R33": (25.3, 10.5, 180.0),
    "R34": (28.3, 10.5, 180.0),
    # logic
    "U1": (41.0, 13.5, 0.0), "U11": (35.5, 19.0, 0.0), "U10": (45.0, 25.0, 0.0),
    "Q14": (49.0, 34.0, 180.0), "Q15": (43.0, 34.0, 180.0),
    "Q16": (47.0, 45.0, 180.0), "D10": (51.5, 49.0, 0.0),
}

# parts placed next to a pin: ref -> ("IC" or "IC.PAD", net, max distance mm)
PIN_ANCHORS = {
    "C1": ("J1.7", "+3V3", 6.0),
    "C3": ("U1.8", "+3V3", 2.5), "R1": ("U1.7", "EE_WC", 3.0), "JP1": ("U1.7", "EE_WC", 5.0),
    "C10": ("U10.16", "+3V3", 2.5), "C11": ("U11.5", "+3V3", 2.5),
    "R35": ("U10.15", "CS0_N", 3.5), "R36": ("U10.1", "CS1_N", 3.5), "R37": ("U10.2", "SCK", 3.5),
    "R38": ("U10.10", "MOSI", 3.5), "R39": ("U10.11", "SYNC", 3.5),
    "R10": ("Q10.1", "G0", 3.0), "R11": ("Q11.1", "G1", 3.0), "R12": ("Q12.1", "G2", 3.0), "R13": ("Q13.1", "G3", 3.0),
    "R25": ("Q14.3", "IRQ_N", 3.5), "R26": ("Q14.1", "G5", 3.0), "R27": ("Q15.1", "INJ", 3.0),
    "R29": ("Q16.1", "G4", 3.0), "R28": ("D10.2", "LED_A", 3.0),
}

# The pre-routed copper (board mm): +5V F.Cu trunk (J1.1 up x 4.87 to G2's R19 pad 1), +5V B.Cu riser to TP2
# (J1.1 up x 2.4, across y 49.0, up x 15.0), LOAD3_D bar on F.Cu (x 10.96, the three 2512 pad 2s, to Q13 pin 3).
TRUNK_X, TRUNK_W = 4.87, 1.5
RISER_X, RISER_Y, RISER_W = 2.4, 49.0, 2.0
LOAD3_X, LOAD3_W = 10.96, 1.0
G3_WARNING = ("G3: S1-S4 ONLY", 19.5, 21.6)        # silk next to G3's load (text, x, y)


def outline():
    return cc.outline(SIZE)


def fixed(comps):
    out = cc.fixed(comps, SIZE)
    out.update({r: (x, y, rot, "F") for r, (x, y, rot) in _FIXED.items() if r in comps})
    for i, net in enumerate(PROBE_PADS):
        out[f"TP{10 + i}"] = (PROBE_X0 + PROBE_DX * i, PROBE_Y, 0.0, "F")
    return out


def keepouts():
    """The shared coupon keep-outs, plus the F.Cu corridors of the pre-routes (no other part on them)."""
    def trunk(x, y):
        return (TRUNK_X - 1.3 <= x <= TRUNK_X + 1.3 and 5.0 <= y <= 24.0) or \
               (2.0 <= x <= TRUNK_X + 1.3 and 22.5 <= y <= 27.0)

    def load3(x, y):
        return (LOAD3_X - 0.9 <= x <= LOAD3_X + 0.9 and 12.0 <= y <= 22.0) or \
               (LOAD3_X <= x <= 14.2 and 16.2 <= y <= 17.8)

    return cc.keepouts(SIZE) + [("F", trunk), ("F", load3)]


def build(bb, comps):
    cc.build(bb, SIZE, title="PrettyCool Keyboard rA TEST COUPON", ref_text="test coupon rA: loads, lanes, loopback")
    for i, net in enumerate(PROBE_PADS):
        dy = 1.7 if i % 2 == 0 else 2.9                       # two rows: the labels are wider than the pitch
        bb.text(pcbnew.F_SilkS, net.replace("_N", "#"), *P(PROBE_X0 + PROBE_DX * i, PROBE_Y - dy), 0.8)
    for (x, y), net in zip(cc.WIRE_PAD_XY, ("+3V3", "+5V", "GND", "GND")):
        bb.text(pcbnew.F_SilkS, net, *P(x, y - 2.4), 0.8)
    for ref, label in (("Q10", "G0 110mA"), ("Q11", "G1 LIM"), ("Q12", "G2 167mA"), ("Q13", "G3 LIM S1-S4")):
        x, y, _ = _FIXED[ref]
        bb.text(pcbnew.F_Fab, label, *P(x, y + 2.6), 0.8)
    text, x, y = G3_WARNING
    bb.text(pcbnew.F_SilkS, text, *P(x, y), 0.8)


def post_fixed(bb, comps):
    """J1's pads on their slot positions (and the motherboard socket solved to the same positions)."""
    cc.check_mating()
    j1 = bb.footprints["J1"]
    assert j1.IsFlipped(), "J1 must be on the bottom"
    for p in j1.Pads():
        x, y = bxy(p)
        ex, ey = cc.pin_xy(int(p.GetNumber()))
        assert abs(x - ex) < 1e-3 and abs(y - ey) < 1e-3, f"J1 pad {p.GetNumber()} at {(x, y)}, want {(ex, ey)}"


def _pad(fp, num):
    p = next(p for p in fp.Pads() if p.GetNumber() == num)
    return bxy(p), p.GetNetname()


def _path(board, pts, layer, net, width):
    for a, c in zip(pts, pts[1:]):
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(V(*a))
        t.SetEnd(V(*c))
        t.SetLayer(layer)
        t.SetWidth(pcbnew.FromMM(width))
        t.SetNet(net)
        t.SetLocked(True)
        board.Add(t)


def preroute(bb):
    """Locked +5V on the outer layers and LOAD3_D on F.Cu (see the module docstring). Every +5V pad is joined here,
    so no router adds +5V copper (it would be free to use 0.5 oz In2)."""
    fps, b = bb.footprints, bb.board
    j1 = fps["J1"]
    (j1_1, n5), (j1_2, _), (j1_3, _) = _pad(j1, "1"), _pad(j1, "2"), _pad(j1, "3")
    net5 = bb.net("+5V")
    pads5 = {"C2": "1", "R22": "1", "R23": "1", "R24": "1", "R19": "1"}
    xy = {}
    for ref, num in pads5.items():
        xy[ref], name = _pad(fps[ref], num)
        assert name == "+5V", f"{ref}.{num} is on {name}, not +5V: the pre-route would short it"
    assert n5 == "+5V" and abs(j1_1[0] - TRUNK_X) < 1e-3, "J1 pin 1 is not where the +5V trunk starts"
    for layer in (pcbnew.F_Cu, pcbnew.B_Cu):            # J1 pins 1-3 joined on both outer layers
        _path(b, [j1_2, j1_1, j1_3], layer, net5, 1.2)
    # F.Cu trunk: J1.1 up through C2's and G3's +5V pad centres (a vertex on each), then left to G2's R19 pad 1
    r19 = xy["R19"]
    for ref in ("C2", "R22", "R23", "R24"):
        assert abs(xy[ref][0] - TRUNK_X) < 0.7, f"{ref} +5V pad is off the trunk"
    x24, y24 = xy["R24"]
    _path(b, [j1_1, xy["C2"], xy["R22"], xy["R23"], xy["R24"], (x24, y24 + 2.0), (r19[0], y24 + 2.0 + x24 - r19[0]),
              r19], pcbnew.F_Cu, net5, TRUNK_W)
    # B.Cu riser: J1.1 to the TP2 wire pad, clear of the M3 post (no copper within 3.0 of (4, 56))
    tp2, name = _pad(fps["TP2"], "1")
    assert name == "+5V"
    _path(b, [j1_1, (RISER_X, j1_1[1] + (j1_1[0] - RISER_X)), (RISER_X, RISER_Y), (tp2[0], RISER_Y), tp2],
          pcbnew.B_Cu, net5, RISER_W)
    # LOAD3_D: the three 2512 pad 2s and Q13's drain
    pads = [_pad(fps[r], "2") for r in ("R22", "R23", "R24")] + [_pad(fps["Q13"], "3")]
    assert len({n for _, n in pads}) == 1 and pads[0][1].endswith("LOAD3_D"), "LOAD3_D pads"
    netd = bb.net(pads[0][1])
    (r22, _), (r23, _), (r24, _), (q, _) = pads
    _path(b, [r22, r23, r24], pcbnew.F_Cu, netd, LOAD3_W)
    _path(b, [(LOAD3_X, q[1]), q], pcbnew.F_Cu, netd, LOAD3_W)


def pours(bb):
    cc.pours(bb, SIZE)
