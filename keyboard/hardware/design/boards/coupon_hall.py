"""Hall-effect coupon layout: standard coupon, 58 x 60 mm, 4 layers (boards/coupon_common.py has the shared geometry;
the circuit is sheets/coupon_hall.py).

Floor plan (board mm, top view, origin at the lower-left corner, the slot edge at y = 0):

* **Key block**: four key sites on a 19.05 mm grid, 2 x 2, centred on x = 29.0: K1 (19.475, 26.525), K2 (38.525,
  26.525), K3 (19.475, 45.575), K4 (38.525, 45.575). Each TMAG5253 sits with its package centre (the Hall element,
  +-25 um) on its key's centre, the axis of the stem's magnet. The block's 2 x 2 keycap cells, x 9.95-48.05 and
  y 17.0-55.1, carry **no top-side part** except, at each key, the sensor, its 100 nF and (K1) the thermistor TH10,
  all within 3.0 mm of the key centre, at most 0.6 mm tall (X2SON 0.4 mm max, 0402 0.5 mm): the printed key fixture
  sits flat on the block with a pocket over each key centre. Tracks and tented vias run under it.
* **References**: REF1 (5.0, 36.05) in the left column, REF2 (53.0, 36.05) in the right one, 14.5 mm in x and 9.5 mm
  in y from the nearest key centres (17.3 mm); TH11 beside REF1. Closer than the 19.05 mm pitch (risks.md SE-2): a
  press moves the nearer reference by about -205 uT (*estimate*), and no place on this outline is far from every
  key (sheets/coupon_hall.py has the numbers), so the positions stay and the firmware treats a reference as common
  mode only while every key is at rest.
* **Fixture holes**: five M2 (2.2 mm, unplated): H10 (5.0, 22.0), H11 (53.0, 22.0), H12 (5.0, 50.0), H13 (53.0,
  50.0) in the side columns, and H14 (29.0, 36.05) between the four keys (3.6 mm from each MX housing corner). No
  copper within r 2.3 on any layer (an M2 screw head or washer, Ø 3.8-4.0 mm, may sit on either face).
* **Strip** between the header and the block (y 7.4-17.0): the lane buffers U12 by the lane pins (AN0-AN2 at
  x 17.6-22.7), with R19 (AN1's 22 Ohm) right above OUT B and the K1 lane pre-routed down to J1 pin 13, the mux
  U10 in the middle, the EEPROM U1 over its I2C pins (x 40.4), the G-line pull-downs over the G pins (x 45.5-50.6),
  R15 (G5's) fixed at (53.7, 9.0) above the key's place. The corner beside J1's pins 39 and 40 (x >= 52.0,
  y <= 7.9, `KEY_LABELS`) carries no part, so the key's X, "KEY" and "40" keep their places (`post_check()`).
  The enable latch U11 is in the right column between H11 and REF2, the probe pads TP10-TP13
  in the left column, TP14 (G3) at the strip's right end.
* **Pre-routed**: EN_K3 and EN_REF1, the latch's two longest enable lines (U11 in the right column to K3 and REF1 on
  the left), locked on B.Cu at y 33.0 and 31.8 with a via at each end (`preroute()`, `EN_ROUTES`); and the K1 direct
  lane, BUF1 (U12 OUT B and -IN B to R19) and AN1 from R19 down to J1 pin 13 and across to its probe pad TP11, both
  on B.Cu (`LANE1_*`); and the muxed lane AN0 from R18 (fixed, AN0 pad facing J1) to J1 pin 11 on F.Cu and to its
  probe pad TP10 under the strip on B.Cu (`LANE0_*`, review of 2026-11-28). The router lays the rest.
* J1, H1, the fiducials and the wire pads TP1-TP3 (+3V3, GND, GND) where every coupon has them (coupon_common). J1 is
  the keyed header (the owner's decision D2 of 2026-11-27): 39 pads, none at 39, with coupon_common's X and "KEY" on
  the top silk at pin 39's place (53.13, 5.27) and (53.13, 7.02), inside the header-tail keep-out, and this board's
  "39" beside the X (55.33, 5.27), above coupon_common's "40" (55.33, 2.73).

Heights for the fixture and the enclosure: top-side parts in the strip and columns <= 1.75 mm (SOIC-8); in the
key block <= 0.6 mm; the header's pin tails about 1.4 mm in y < 7.4; on the bottom only the header (2.54 mm plastic)
and the M2 screw heads if the fixture is screwed from below.
"""

import pcbnew

from boards import coupon_common as cc
from boards.geom import P, V, bxy, circle, rect
from boards.geom import poly_page as page

SIZE = cc.STANDARD
LAYERS, THICKNESS = cc.LAYERS, cc.THICKNESS
STACKUP = cc.STACKUP
RULES = cc.RULES
NETCLASSES = cc.NETCLASSES
GND_VIA = cc.GND_VIA
STITCH_PITCH = 3.0
ROUTE = True
CENTRE = (29.0, 12.0)
HIDE_REFS = ("H", "FID", "TP")
# Freerouting's optimizer off (layout.py OPTIMIZER_PASSES): on 2026-11-28 three attempts with it on (4, 8 and 12 min)
# left 37, 26 and 21 connections open after the import, and the grid router could not finish EN_K3 and EN_REF1 (the
# 2026-11-27 route, with it on, had left 4 and 2); coupon-haptics and the motherboard found the same
OPTIMIZER_PASSES = 0
# The two longest enable lines are pre-routed and locked (preroute()): with the optimizer on or off, Freerouting and the
# grid router left EN_K3 and EN_REF1 open on 2026-11-28 ("no path even with rip-up": the F.Cu round U11 closed their
# escapes), where the 2026-11-27 route had laid both on B.Cu. Static enables, so their length does not matter.
PROTECTED_NETS = ("EN_K3", "EN_REF1", "BUF1", "AN1", "AN0")   # locked pre-routes: never pruned as debris
PREROUTED_NETS = ("EN_K3", "EN_REF1", "BUF1", "AN1", "AN0")  # joined in full by preroute(): out of Freerouting's job
# The muxed lane AN0, pre-routed as AN1 is (review of 2026-11-28): left to Freerouting after R15 moved, its stub to the
# probe pad TP10 wrapped round J1's pins 5-10 (+3V3 and GND) on F.Cu, 31 mm for an 18 mm span (1.73x; 1.34x on the
# route before). Now R18 is fixed with AN0 (pad 2) at the bottom: R18.2 -> straight down and 45 degrees to J1 pin 11
# (F.Cu), and from R18.2 a F.Cu stub left to a via, B.Cu along y 8.04 and up x 5.0 to a via beside TP10, a F.Cu stub
# into TP10. Board mm: the lane's bend, the two vias, the B.Cu corner
LANE0_BEND_Y, LANE0_VIA, LANE0_CORNER, LANE0_TP_VIA = 7.49, (14.25, 8.04), (6.6, 8.04), (5.0, 16.0)
# The K1 direct lane (AN1), pre-routed so that its path is as short and as clean as the muxed lane's: U12 OUT B (7)
# and -IN B (6) linked over their pad toes and up into R19.1 (BUF1, all F.Cu), then R19.2 -> a via -> B.Cu straight
# down under U12 (the In1 GND plane between it and the F.Cu parts) to J1 pin 13 (AN1), and from the same via along
# B.Cu to a via beside the probe pad TP11 (left to Freerouting on 2026-11-28, that stub shorted AN1 to HALL_K1 at
# TP13: DRC caught it). Board mm: the link's y, the via, the bend above J1, TP11's via
LANE1_LINK_Y, LANE1_VIA, LANE1_BEND, LANE1_TP_VIA = 15.2, (20.6, 16.3), (20.6, 6.6), (8.6, 16.3)
EN_W, EN_VIA = 0.20, (0.60, 0.30)           # track width, via (mm): the coupon defaults
# board mm: each line's F.Cu stub from U11 to a via (A, C), its B.Cu run, a via (B, D) below the sensor's EN pad and a
# F.Cu stub up into it. The runs pass H14 at 2.95 mm (y 33.0) and 4.25 mm (y 31.8), outside its 2.3 mm copper keep-out
EN_ROUTES = {
    "EN_K3": dict(u11="6", sensor="U22", via_a=(48.6, None), run=[(48.6, 33.0), (None, 33.0)], via_b_dy=-1.325),
    "EN_REF1": dict(u11="9", sensor="U24", via_a=(None, 25.3), run=[(47.4, 25.3), (47.4, 31.8), (None, 31.8)],
                    via_b_dy=-1.3),
}
EN_KEEP = 1.0                               # placer keep-out round each pre-routed via (mm)

PITCH = 19.05
KEYS = {"K1": (19.475, 26.525), "K2": (38.525, 26.525), "K3": (19.475, 45.575), "K4": (38.525, 45.575)}
REFS_XY = {"REF1": (5.0, 36.05), "REF2": (53.0, 36.05)}
BLOCK = (KEYS["K1"][0] - PITCH / 2, KEYS["K1"][1] - PITCH / 2, KEYS["K4"][0] + PITCH / 2, KEYS["K4"][1] + PITCH / 2)
MX_HOUSING = 14.0                      # an MX housing's square below the plate, for the fab drawing only
POCKET = 3.0                           # parts allowed within this distance (x and y) of a key centre
SENSOR_REF = {"K1": "U20", "K2": "U21", "K3": "U22", "K4": "U23", "REF1": "U24", "REF2": "U25"}
SENSOR_CAP = {u: "C" + u[1:] for u in SENSOR_REF.values()}
# Sensors at rot 270: GND (2) top-left, VCC (1) top-right, EN (3) bottom-left, OUT (4) bottom-right, so the two
# signals leave downward and sideways, toward the strip, and the supply pair faces its capacitor above.
SENSOR_ROT = 270.0
CAP_OFF, CAP_ROT = (0.0, 1.5), 180.0   # 100 nF above the sensor: pad 1 (+3V3) over VCC, pad 2 over GND
TH_OFF = (-2.0, 1.5)                   # NTC left of the cap: pad 2 (GND) next to the cap's GND pad
HOLES = {"H10": (5.0, 22.0), "H11": (53.0, 22.0), "H12": (5.0, 50.0), "H13": (53.0, 50.0), "H14": (29.0, 36.05)}
HOLE_COPPER_R = 2.3
HOLE_PART_R = 2.8
PROBES = {"TP10": ("AN0", 3.6, 16.0), "TP11": ("AN1", 7.4, 16.0), "TP12": ("MUX", 3.6, 12.6),
          "TP13": ("K1", 7.4, 12.6), "TP14": ("G3", 53.2, 15.6)}

# x, y, KiCad orientation (board mm). TSSOP-16 at 270: pins 1-8 along the top, right to left; 9-16 along the bottom,
# left to right. SOIC-8 at 90: pins 1-4 along the bottom, left to right; 5-8 along the top, right to left.
_FIXED = {
    "U12": (19.0, 12.0, 90.0),      # OPA2365: OUT A (1) bottom-left, toward AN0; OUT B (7) on top, toward R19
    # R19 (22 Ohm, BUF1 -> AN1) right above U12's OUT B (7) and -IN B (6), pad 1 (BUF1) over pin 7: BUF1 and AN1 are
    # pre-routed (preroute(), LANE1). Left to the placer on 2026-11-28, R19 landed left of U12 behind C12 and
    # Freerouting took BUF1 27 mm round U12 and between J1's rows for a 5.6 mm span, and AN1 39 mm (17.5 mm span).
    # U12 sits 0.5 mm lower than on 2026-11-27 so that R19's courtyard clears U12's and stays out of the key block.
    "R19": (19.0, 16.3, 0.0),
    # R18 (22 Ohm, BUF0 -> AN0) left of U12's OUT A, turned so that pad 2 (AN0) faces J1 pin 11 and pad 1 (BUF0) U12
    # pin 1; AN0 is pre-routed from it (LANE0, preroute()). It is where the placer had put it, turned 180 degrees.
    "R18": (15.35, 8.55, 270.0),
    "U10": (29.5, 12.5, 270.0),     # TMUX1208: D (8) top-left toward U12, S1-S4 up toward the keys, A0/EN right
    "U1": (41.5, 12.5, 270.0),      # M24C02 right above its I2C pins (SDA 5, SCL 6 along the bottom)
    "U11": (53.0, 29.0, 0.0),       # SN74HC259, right column: Q0-Q3 face the keys, Q5 under REF2
    # R15 (G5's 100 k pull-down) above the key's place, clear of KEY_LABELS. Left to the placer (anchored 5 mm from
    # J1.38) it went to the board corner at (55.6, 2.7), 1.3 mm from the hand-soldered pin 40, where coupon_common's
    # "40" belongs, so the silk pass moved "40" up beside the key X (54.96, 4.69) and "KEY" 1 mm right (review of
    # 2026-11-28): the X then read as pin 40's. FID2's keep-clear (r 1.35 at (56, 9.5)) starts at x 54.65.
    "R15": (53.7, 9.0, 90.0),
}
# The key's silk (coupon_common.build(): X at pin 39 (53.13, 5.27), "KEY" at (53.13, 7.02), "40" at (55.33, 2.73))
# and the board corner beside pin 40 stay free of parts, so that the silk pass leaves those labels where they belong.
KEY_LABELS = (52.0, 7.9)                # no top-side part with x >= 52.0 and y <= 7.9

PIN_ANCHORS = {
    "C1": ("J1.7", "+3V3", 6.0),
    "C10": ("U10.13", "+3V3", 2.5), "C11": ("U11.16", "+3V3", 2.5), "C12": ("U12.8", "+3V3", 2.5),
    "R26": ("U12.3", "MUX_D", 4.0),     # R18 is fixed (_FIXED)
    "R20": ("U12.5", "HALL_K1", 3.5),
    "C16": ("U10.10", "TEMP1", 3.5), "C17": ("U10.9", "TEMP2", 3.5),
    "R16": ("U10.10", "TEMP1", 5.0), "R17": ("U10.9", "TEMP2", 5.0),
    "R10": ("J1.33", "G0", 5.0), "R11": ("J1.34", "G1", 5.0), "R12": ("J1.35", "G2", 5.0),
    "R13": ("J1.36", "G3", 5.0), "R14": ("J1.37", "G4", 5.0),     # R15 is fixed (_FIXED)
    "C3": ("U1.8", "+3V3", 2.5), "R1": ("U1.7", "EE_WC", 3.0), "JP1": ("U1.7", "EE_WC", 9.0),
}

FAB_NOTES = [
    "**Stage A1** (the owner's decision D1 of 2026-11-27, SPEC §1): released, ordered and brought up with the "
    "motherboard and the test coupon.",
    "**Hall-effect coupon (SPEC §4.8):** six TMAG5253BA4 (X2SON-4, 1.1 x 1.4 mm, 0.5 mm pitch) with their thermal "
    "pads soldered (TI: \"The pin must be soldered to the board for mechanical support\"); the pad is not connected. "
    "Check pin 1 (VCC) of each in JLC's placement preview: a sensor turned 180 degrees swaps VCC/GND with EN/OUT. "
    "EasyEDA has no record of C22452022 (TMAG5253BA4, 2026-11-27), so jlcplace could not simulate U20-U25: their "
    "CPL rotation is the one it fits for the same DMR package's EasyEDA footprint (C22401868, the BA3), recorded as a "
    "manual decision (jlcplace-db/C22452022.json). If JLC cannot place C22452022, the BA3 (C22401868, +-80 mT, same "
    "footprint, EasyEDA record present) is the fallback: then keep the magnet's peak field at the sensor under 80 mT.",
    "**R26 (0 Ohm) is do-not-place** on purpose: fitting it puts the mux output, unbuffered, onto lane AN2 (the lane-"
    "drive experiment of SPEC §11 #21).",
    "**JP1 (WP)** is an open solder jumper: leave it open to write the descriptor EEPROM, then bridge it to "
    "write-protect.",
    "**Finish:** ENIG (the X2SON's 0.5 mm pitch). Its nickel layer (a few um, ferromagnetic) sits under every "
    "sensor alike; its effect on the field is not quantified here (**unverified**). Keep magnets and steel tools "
    "away from the sensors while handling; no part on this coupon is ferromagnetic by design (no ferrite, no "
    "inductor).",
    "**TH10, TH11** (NTC thermistors, C77131) are not polarised: the preview checklist's polarity item for them is "
    "met in either orientation (recorded in jlcplace-db/C77131.json).",
    "**Copper:** +3V3 0.30 mm (class Rail3V3) plus the In2 +3V3 pour, every other net 0.20 mm (the coupon draws about "
    "25 mA typ, 41 mA max, estimates). Pre-routed and locked: the two static enable lines EN_K3 and EN_REF1 (B.Cu "
    "runs across the board from the latch U11), the K1 direct lane (U12 OUT B -> R19 -> J1 pin 13, AN1) and the "
    "muxed lane from R18 to J1 pin 11 (AN0), each with its probe-pad stub. "
    "0.15 mm clearance, vias 0.60 / 0.30 mm.",
    "**Key fixture:** five M2 unplated holes (2.2 mm) for the printed key fixture (keyboard/hardware/mechanical); no "
    "copper within 2.3 mm of them. Not on the PCBA: the fixture, its stems, springs, magnets and M2 screws.",
] + [n.replace("ENIG (HASL lead-free would do: the finest pitch is 0.65 mm)",
               "ENIG (the finest pitch is the TMAG5253's 0.5 mm)") for n in cc.FAB_NOTES]


def outline():
    return cc.outline(SIZE)


def _sensor_xy(name):
    return KEYS.get(name) or REFS_XY[name]


def fixed(comps):
    out = cc.fixed(comps, SIZE)
    out.update({r: (x, y, rot, "F") for r, (x, y, rot) in _FIXED.items()})
    for name, u in SENSOR_REF.items():
        x, y = _sensor_xy(name)
        out[u] = (x, y, SENSOR_ROT, "F")
        out[SENSOR_CAP[u]] = (x + CAP_OFF[0], y + CAP_OFF[1], CAP_ROT, "F")
    for th, site in (("TH10", "K1"), ("TH11", "REF1")):
        x, y = _sensor_xy(site)
        out[th] = (x + TH_OFF[0], y + TH_OFF[1], 0.0, "F")
    for h, (x, y) in HOLES.items():
        out[h] = (x, y, 0.0, "F")
    for tp, (_label, x, y) in PROBES.items():
        out[tp] = (x, y, 0.0, "F")
    return {r: v for r, v in out.items() if r in comps}


def keepouts():
    """The shared coupon keep-outs; the key block (no part outside the sensor pockets); the fixture holes; a clear
    ring round each reference sensor."""
    x0, y0, x1, y1 = BLOCK

    def block(x, y):            # the pockets' parts are all fixed: nothing else goes in the block
        return x0 <= x <= x1 and y0 <= y <= y1

    def slot_edge_text(x, y):   # coupon_common's "SLOT EDGE" silk at (29.0, 8.4)
        return 24.5 <= x <= 33.5 and y <= 9.0

    def holes(x, y):
        return any((x - hx) ** 2 + (y - hy) ** 2 < HOLE_PART_R ** 2 for hx, hy in HOLES.values())

    def refs(x, y):
        return any(abs(x - rx) <= POCKET and abs(y - ry) <= POCKET for rx, ry in REFS_XY.values())

    def en_vias(x, y):          # the pre-routed EN_K3 / EN_REF1 vias (preroute())
        return any(abs(x - vx) <= EN_KEEP and abs(y - vy) <= EN_KEEP
                   for vx, vy in _EN_VIAS + [LANE1_VIA, LANE1_TP_VIA, LANE0_VIA, LANE0_TP_VIA])

    def key_labels(x, y):       # the key's X, "KEY" and "40" beside J1's pins 39 and 40 (KEY_LABELS)
        return x >= KEY_LABELS[0] and y <= KEY_LABELS[1]

    return cc.keepouts(SIZE) + [("F", block), ("F", slot_edge_text), ("*", holes), ("F", refs), ("*", en_vias),
                                ("F", key_labels)]


def build(bb, comps):
    cc.build(bb, SIZE, title="PrettyCool Keyboard rA HALL COUPON", ref_text="Hall coupon rA: 4 keys, 2 refs, mux")
    cu = [pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu]
    for h, (x, y) in HOLES.items():
        bb.keepout(cu, page(circle(x, y, HOLE_COPPER_R, 36)), tracks=True, vias=True, pads=False, pours=True,
                   name=f"{h}_NO_COPPER")
    # documentation: the key block, each key's MX housing square and cell, the pockets, the sensor sites
    x0, y0, x1, y1 = BLOCK
    bb.polyline(pcbnew.F_Fab, page(rect(x0, y0, x1, y1)), 0.1, closed=True)
    for name, (kx, ky) in KEYS.items():
        h = MX_HOUSING / 2
        bb.polyline(pcbnew.F_Fab, page(rect(kx - h, ky - h, kx + h, ky + h)), 0.1, closed=True)
        bb.polyline(pcbnew.F_Fab, page(rect(kx - POCKET, ky - POCKET, kx + POCKET, ky + POCKET)), 0.1, closed=True)
        bb.text(pcbnew.F_SilkS, name, *P(kx + 4.0, ky + 4.0), 1.0)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):        # a cross marking the key centre, clear of pads
            bb.polyline(pcbnew.F_SilkS, page([(kx + 2.0 * dx, ky + 2.0 * dy), (kx + 3.0 * dx, ky + 3.0 * dy)]), 0.12,
                        closed=False)
    for name, (rx, ry) in REFS_XY.items():
        bb.text(pcbnew.F_SilkS, name, *P(rx, ry + 3.6), 0.8)
    bb.text(pcbnew.F_Fab, "KEY FIXTURE BLOCK: NO PARTS EXCEPT THE POCKETS", *P((x0 + x1) / 2, y0 + 1.0), 0.8)
    for tp, (label, x, y) in PROBES.items():
        bb.text(pcbnew.F_SilkS, label, *P(x, y + 1.6), 0.8)
    for (x, y), net in zip(cc.WIRE_PAD_XY, ("+3V3", "GND", "GND")):
        bb.text(pcbnew.F_SilkS, net, *P(x, y - 2.0), 0.8)
    # "39" beside the key's X, as coupon_common's "40" sits beside pin 40: it names the X's place and keeps the silk
    # pass from parking a reference designator there (on 2026-11-28 R13's landed beside the X, reading "x R13")
    kx, ky = cc.pin_xy(cc.KEY_PIN)
    bb.text(pcbnew.F_SilkS, str(cc.KEY_PIN), *P(kx + 2.2, ky), 0.8)


def post_fixed(bb, comps):
    """J1 on its slot positions, with no pad 39 (the key); every sensor centred on its site with VCC (pad 1) top-right
    and EN/OUT below; every sensor cap above its sensor with pad 1 (+3V3) over VCC."""
    cc.check_mating()
    fps = bb.footprints
    j1 = fps["J1"]
    assert j1.IsFlipped(), "J1 must be on the bottom"
    pads = {p.GetNumber() for p in j1.Pads()}
    assert pads == {str(n) for n in range(1, 41)} - {str(cc.KEY_PIN)}, \
        f"J1 must have pads 1-40 less the key pin {cc.KEY_PIN} (D2 of 2026-11-27): {sorted(pads, key=int)}"
    for p in j1.Pads():
        x, y = bxy(p)
        ex, ey = cc.pin_xy(int(p.GetNumber()))
        assert abs(x - ex) < 1e-3 and abs(y - ey) < 1e-3, f"J1 pad {p.GetNumber()} at {(x, y)}, want {(ex, ey)}"
    for name, u in SENSOR_REF.items():
        sx, sy = _sensor_xy(name)
        pads = {p.GetNumber(): (bxy(p), p.GetNetname()) for p in fps[u].Pads() if p.GetNumber()}
        (vx, vy), vnet = pads["1"]
        assert vnet == "+3V3" and vx > sx and vy > sy, f"{u}: pad 1 (VCC) not top-right on +3V3"
        (ox, oy), onet = pads["4"]
        assert onet.endswith("HALL_" + name) and ox > sx and oy < sy, f"{u}: pad 4 (OUT) not bottom-right"
        cx, cy = bxy(fps[u])
        assert abs(cx - sx) < 1e-3 and abs(cy - sy) < 1e-3, f"{u} not on its site"
        c = {p.GetNumber(): (bxy(p), p.GetNetname()) for p in fps[SENSOR_CAP[u]].Pads()}
        assert c["1"][1] == "+3V3" and c["1"][0][0] > c["2"][0][0] and c["1"][0][1] > vy, \
            f"{SENSOR_CAP[u]}: pad 1 (+3V3) not above VCC"


def _pad(fp, num):
    p = next(p for p in fp.Pads() if p.GetNumber() == num)
    return bxy(p), p.GetNetname()


def _via(board, xy, net):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(V(*xy))
    v.SetWidth(pcbnew.FromMM(EN_VIA[0]))
    v.SetDrill(pcbnew.FromMM(EN_VIA[1]))
    v.SetNet(net)
    v.SetLocked(True)
    board.Add(v)


def _path(board, pts, layer, net):
    for a, c in zip(pts, pts[1:]):
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(V(*a))
        t.SetEnd(V(*c))
        t.SetLayer(layer)
        t.SetWidth(pcbnew.FromMM(EN_W))
        t.SetNet(net)
        t.SetLocked(True)
        board.Add(t)


def _en_geometry(u11_xy, sensor_xy, r):
    """The pre-route of one enable line as (F.Cu stub at U11, B.Cu run, F.Cu stub at the sensor), board mm."""
    ax = r["via_a"][0] if r["via_a"][0] is not None else u11_xy[0]
    ay = r["via_a"][1] if r["via_a"][1] is not None else u11_xy[1]
    b = (sensor_xy[0], sensor_xy[1] + r["via_b_dy"])
    run = [(x if x is not None else b[0], y) for x, y in r["run"]]
    return [u11_xy, (ax, ay)], [(ax, ay)] + run + [b], [b, sensor_xy]


# The vias' places for the placer keep-out, from the fixed parts' pad positions (U11 at _FIXED, the sensors at their
# sites, rot 270): U11 pin 6 (50.137, 28.025) and pin 9 (55.863, 26.725); U22 pin 3 (18.7, 45.325) and U24 pin 3
# (4.225, 35.8). preroute() asserts that the pads are where these say.
_EN_PADS = {"EN_K3": ((50.137, 28.025), (18.7, 45.325)), "EN_REF1": ((55.863, 26.725), (4.225, 35.8))}
_EN_VIAS = [xy for n, (u, s) in _EN_PADS.items() for xy in (lambda g: (g[0][1], g[2][0]))(
    _en_geometry(u, s, EN_ROUTES[n]))]


def preroute(bb):
    """EN_K3 (U11 Q2 to U22's EN) and EN_REF1 (U11 Q4 to U24's EN), locked: a F.Cu stub from U11's pin to a via, a
    B.Cu run across the board under the key block, and a via below the sensor's EN pad with a F.Cu stub up into it
    (EN_ROUTES; why in the note above PROTECTED_NETS). The runs do not cross: EN_REF1 leaves U11 downward and runs at
    y 31.8, EN_K3 leaves it leftward, outside EN_REF1's riser at x 47.4, and runs at y 33.0. Then the K1 direct lane
    (LANE1, see its note): BUF1 and AN1 in full (R19, J1 pin 13, TP11); and the muxed lane (LANE0): AN0 in full
    (R18, J1 pin 11, TP10)."""
    fps, b = bb.footprints, bb.board
    for name, r in EN_ROUTES.items():
        (u_xy, u_net), (s_xy, s_net) = _pad(fps["U11"], r["u11"]), _pad(fps[r["sensor"]], "3")
        assert net_ok(u_net, name) and net_ok(s_net, name), f"{name}: U11.{r['u11']} on {u_net}, " \
            f"{r['sensor']}.3 on {s_net}"
        want_u, want_s = _EN_PADS[name]
        assert max(abs(u_xy[0] - want_u[0]), abs(u_xy[1] - want_u[1]), abs(s_xy[0] - want_s[0]),
                   abs(s_xy[1] - want_s[1])) < 0.01, f"{name}: pads moved ({u_xy}, {s_xy}): update _EN_PADS"
        top_u, bot, top_s = _en_geometry(u_xy, s_xy, r)
        net = bb.net(u_net)
        _path(b, top_u, pcbnew.F_Cu, net)
        _path(b, bot, pcbnew.B_Cu, net)
        _path(b, top_s, pcbnew.F_Cu, net)
        for xy in (bot[0], bot[-1]):
            _via(b, xy, net)
    # the K1 direct lane: BUF1 (U12.6, U12.7, R19.1) in full, and AN1 from R19.2 to J1.13
    (p7, n7), (p6, n6), (r1, nr1) = _pad(fps["U12"], "7"), _pad(fps["U12"], "6"), _pad(fps["R19"], "1")
    (r2, nr2), (j13, nj), (tp, ntp) = _pad(fps["R19"], "2"), _pad(fps["J1"], "13"), _pad(fps["TP11"], "1")
    assert all(net_ok(n, "BUF1") for n in (n7, n6, nr1)) and all(net_ok(n, "AN1") for n in (nr2, nj, ntp)), \
        (n7, n6, nr1, nr2, nj, ntp)
    assert tp[0] + 0.9 < LANE1_TP_VIA[0] and abs(tp[1] - LANE1_TP_VIA[1]) < 0.5, "TP11 moved: update LANE1_TP_VIA"
    assert p6[1] == p7[1] and p7[1] + 0.5 < LANE1_LINK_Y < r1[1] - 0.6 and r2[0] < LANE1_VIA[0] - 0.8, \
        "the K1 lane pre-route no longer fits U12 and R19 as placed: update LANE1_*"
    buf1, an1 = bb.net(n7), bb.net(nr2)
    _path(b, [p7, (p7[0], LANE1_LINK_Y), (p6[0], LANE1_LINK_Y), p6], pcbnew.F_Cu, buf1)
    _path(b, [(p7[0], LANE1_LINK_Y), r1], pcbnew.F_Cu, buf1)
    _path(b, [r2, LANE1_VIA], pcbnew.F_Cu, an1)
    _path(b, [LANE1_VIA, LANE1_BEND, j13], pcbnew.B_Cu, an1)
    _path(b, [LANE1_VIA, LANE1_TP_VIA], pcbnew.B_Cu, an1)
    _path(b, [LANE1_TP_VIA, tp], pcbnew.F_Cu, an1)
    for xy in (LANE1_VIA, LANE1_TP_VIA):
        _via(b, xy, an1)
    # the muxed lane AN0 in full: R18.2 -> J1.11, and R18.2 -> TP10 (LANE0, see its note)
    (a0, na0), (j11, nj11), (tp0, ntp0) = _pad(fps["R18"], "2"), _pad(fps["J1"], "11"), _pad(fps["TP10"], "1")
    (b0, nb0) = _pad(fps["R18"], "1")
    assert all(net_ok(n, "AN0") for n in (na0, nj11, ntp0)) and net_ok(nb0, "BUF0"), (na0, nj11, ntp0, nb0)
    bend = (a0[0], LANE0_BEND_Y)
    assert b0[1] > a0[1] + 0.8 and abs((j11[0] - bend[0]) - (bend[1] - j11[1])) < 0.02, \
        f"R18 or J1.11 moved ({a0}, {b0}, {j11}): update LANE0_*"
    assert abs(a0[1] - LANE0_VIA[1]) < 0.02 and a0[0] - LANE0_VIA[0] > 0.9 and LANE0_CORNER[1] == LANE0_VIA[1], \
        "R18.2 moved: update LANE0_VIA / LANE0_CORNER"
    assert abs(tp0[1] - LANE0_TP_VIA[1]) < 0.02 and LANE0_TP_VIA[0] - tp0[0] > 0.9, "TP10 moved: update LANE0_TP_VIA"
    an0 = bb.net(na0)
    _path(b, [a0, bend, j11], pcbnew.F_Cu, an0)
    _path(b, [a0, LANE0_VIA], pcbnew.F_Cu, an0)
    corner2 = (LANE0_TP_VIA[0], LANE0_CORNER[1] + (LANE0_CORNER[0] - LANE0_TP_VIA[0]))     # 45 degrees up to x 5.0
    _path(b, [LANE0_VIA, LANE0_CORNER, corner2, LANE0_TP_VIA], pcbnew.B_Cu, an0)
    _path(b, [LANE0_TP_VIA, tp0], pcbnew.F_Cu, an0)
    for xy in (LANE0_VIA, LANE0_TP_VIA):
        _via(b, xy, an0)


def net_ok(netname, short):
    return netname.split("/")[-1] == short


def post_check(path):
    """After routing (layout.py): the key's silk where coupon_common.build() puts it, "KEY" over the X at pin 39 and
    "40" beside pin 40, not moved by the silk pass; and no top-side part in KEY_LABELS. Returns a list of errors."""
    b = pcbnew.LoadBoard(path)
    errs = []
    want = {"KEY": (cc.pin_xy(cc.KEY_PIN)[0], cc.pin_xy(cc.KEY_PIN)[1] + 1.75),
            "40": (cc.pin_xy(40)[0] + 2.2, cc.pin_xy(40)[1]),
            str(cc.KEY_PIN): (cc.pin_xy(cc.KEY_PIN)[0] + 2.2, cc.pin_xy(cc.KEY_PIN)[1])}
    seen = {}
    for d in b.GetDrawings():
        if isinstance(d, pcbnew.PCB_TEXT) and d.GetLayer() == pcbnew.F_SilkS and d.GetText() in want:
            seen[d.GetText()] = bxy(d)
    for text, (wx, wy) in want.items():
        x, y = seen.get(text, (None, None))
        if x is None or abs(x - wx) > 0.05 or abs(y - wy) > 0.05:
            errs.append(f"silk '{text}' at {(x, y)}, want {(round(wx, 2), round(wy, 2))}: the key's corner is crowded")
    for fp in b.GetFootprints():
        if fp.IsFlipped() or fp.GetReference().startswith(("FID", "H")):
            continue
        x, y = bxy(fp)
        if x >= KEY_LABELS[0] and y <= KEY_LABELS[1]:
            errs.append(f"{fp.GetReference()} at {(round(x, 2), round(y, 2))} inside KEY_LABELS")
        ref = fp.Reference()
        rx, ry = bxy(ref)
        if ref.IsVisible() and ref.GetLayer() == pcbnew.F_SilkS and rx >= KEY_LABELS[0] - 1.0 and ry <= KEY_LABELS[1]:
            errs.append(f"{fp.GetReference()}'s reference at {(round(rx, 2), round(ry, 2))} beside the key's X")
    return errs


def pours(bb):
    cc.pours(bb, SIZE)
