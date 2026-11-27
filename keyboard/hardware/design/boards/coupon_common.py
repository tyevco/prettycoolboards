"""Coupon layout shared by every coupon (SPEC §2, §4.1, §9): outlines, the slot header and its mating socket, the
support post, fiducials, keep-outs, the 4-layer stack and the pours.

Coordinates are board mm (boards/geom.py): origin at the coupon's lower-left corner, +x right, +y up, top view. The
**slot edge** is y = 0: the header runs along it. Every position below is relative to that corner, the same for
the standard and the wide coupon, so a standard coupon fits a wide slot (SPEC §2: any coupon fits any slot of its
size or larger) and the motherboard places one socket and one spacer per slot with the same offsets.

| What | Where (board mm) | Source |
|---|---|---|
| Standard coupon | 58.0 x 60.0, corners r 1.0 | SPEC §2 ("about 58 x 60"; layout sets it) |
| Wide coupon | 80.0 x 60.0, corners r 1.0 | SPEC §2 ("about 80 x 60") |
| Header pin 1 | (4.87, 5.27); pin 2k-1 at x = 4.87 + 2.54 (k-1), y = 5.27; pin 2k at the same x, y = 2.73 | centred on x = 29.0; the odd row (lanes, SPI, G-lines) inside, the even row (mostly GND) at the edge |
| Header body (bottom side) | x 3.60-54.40, y 1.50-6.50 | the 2541WV drawing: 50.8 x 5.0 |
| Support post (M3, Ø3.2 unplated) | (4.0, 56.0); no copper within r 3.0, no part within r 3.5 | SPEC §9: one M3 x 11 mm nylon spacer at the corner opposite the header |
| Fiducials | (2.0, 9.5), (W - 2.0, 9.5), (W - 2.0, 57.5) | top side, 1 mm copper / 2 mm mask, no copper within r 1.35 |
| Wire pads TP1-TP4 | (11.0, 56.5) ... (23.0, 56.5), 4 mm apart | +3V3, +5V, GND, GND |

**The header and the socket.** The coupon's header (KiCad `PinHeader_2x20_P2.54mm_Vertical`) sits on the coupon's
**bottom**, body down. The motherboard's socket (KiCad `PinSocket_2x20_P2.54mm_Vertical`; candidate BOOMELE
2.54-2*20P, LCSC C5124634, 8.5 mm, 2.5 A per contact, Ø1.1 mm holes in its drawing PY2.54-2*NA-8.5MM-Y, KiCad's
Ø1.0 drill taking its 0.64 x 0.40 mm tail) sits on the motherboard's **top**, under the coupon, with every pin n
at the same top-view position as the coupon's pin n. `header_placement()` and `socket_placement()` solve the
footprint position and rotation for that; `check_mating()` compares all 40 pads of both and fails on any difference
(run by layout.py on every coupon). Heights: socket 8.5 mm + the header's 2.54 mm plastic = 11.04 mm from the
motherboard's top to the coupon's underside (SPEC §9 says 11: 8.5 + 2.5). The header's mating pins are 6.00 mm, so
they do not bottom out in the 8.5 mm socket.

**Stack** (`STACKUP`): JLC's 4-layer 1.6 mm JLC04161H-7628 (7628 prepreg 0.2104 mm, er 4.4; core 1.065 mm; 1 oz
outer, 0.5 oz inner: JLC's published figures as remembered here, **unverified**; nothing on a coupon depends on them,
no impedance control is ordered). L1 F.Cu parts and signals, **L2 In1 solid GND**, L3 In2 +3V3 pour and signals, L4
B.Cu signals (and the header body). `build()` puts a no-track rule area over In1 (vias and the plane allowed), so no
router cuts the plane under the lanes (SPEC §4.9: "Route the lanes over a solid ground"); pass `in1_tracks=True` to
allow tracks there.

**Rules** (`RULES`, JLC 4-layer capability is 0.09 / 0.09 mm and a 0.15 mm drill): default track 0.20 mm,
clearance 0.15 mm, vias 0.60 / 0.30 mm (JLC's standard, no surcharge); +5V 0.80 mm and +3V3 0.30 mm (`NETCLASSES`:
a 0.30 mm track with 0.15 mm clearance still enters a 0.5 mm-pitch pin, which 0.80 mm could not), but only where
finish_route lays the track: Freerouting ignores class rules, so a path whose current matters is pre-routed;
copper 0.30 mm from the edge. The board-level DRC minimums (tools/pcbgen.py) are 0.10 mm track and clearance, 0.40 / 0.20 mm via.
"""

from __future__ import annotations

import os

import pcbnew

from boards.geom import TO, B, circle, rect, rounded_rect
from boards.geom import poly_page as page

STANDARD = (58.0, 60.0)
WIDE = (80.0, 60.0)
CORNER_R = 1.0
LAYERS = 4
THICKNESS = 1.6

PITCH = 2.54
HEADER_XC = 29.0                              # header centre, from the coupon's left edge (both sizes)
HEADER_X0 = round(HEADER_XC - 9.5 * PITCH, 4)  # 4.87: the pin 1 / pin 2 column
ROW_INNER, ROW_EDGE = 5.27, 2.73              # odd pins (signals) inside, even pins (mostly GND) at the edge
HEADER_BODY = (HEADER_XC - 25.4, 1.5, HEADER_XC + 25.4, 6.5)
HEADER_FP = "Connector_PinHeader_2.54mm:PinHeader_2x20_P2.54mm_Vertical"
SOCKET_FP = "Connector_PinSocket_2.54mm:PinSocket_2x20_P2.54mm_Vertical"
SOCKET_PART = {"MPN": "2.54-2*20P", "Manufacturer": "BOOMELE(Boom Precision Elec)", "LCSC": "C5124634",
               "note": "female 2 x 20, 2.54 mm, 8.5 mm, THT; 6382 in stock at JLC, $0.33 (2026-11-27)"}
HEADER_PART = {"MPN": "2541WV-2x20P", "Manufacturer": "HanElectricity", "LCSC": "C25503140",
               "note": "male 2 x 20, 2.54 mm, 6.0 mm mating, THT; 1516 in stock at JLC, $0.14 (2026-11-27)"}

POST = (4.0, 56.0)
POST_DRILL = 3.2
POST_COPPER_R = 3.0                           # no copper (tracks, vias, pours) on any layer
POST_PART_R = 3.5                             # no part: the spacer below, the screw head above
FID_KEEPOUT_R = 1.35
WIRE_PAD_XY = [(11.0, 56.5), (15.0, 56.5), (19.0, 56.5), (23.0, 56.5)]

RULES = dict(track=0.20, clearance=0.15, via=0.60, via_drill=0.30, edge=0.30)
# (name, nets by short name, track, clearance, via, drill)
# Until 2026-11-27 no class reached the board (layout.write_project wrote the project's net settings as schema
# version 0, which KiCad 10 discards), so every net routed at the Default 0.20 mm. With the classes in force, +3V3 at
# 0.80 mm could not enter a fine-pitch pin: it is 0.30 mm, enough for the 250 mA coupon rule. Clearances stay at the
# Default 0.15 mm. Freerouting 2.1.0 ignores class rules (it lays every net at the default width, tested on the test
# coupon), so a class width reaches only tracks that tools/finish_route.py lays, and a class clearance above the
# default only makes DRC errors: pre-route (locked, `preroute()`, `PREROUTED_NETS`) any path whose current matters.
NETCLASSES = [("Rail", ["+5V"], 0.80, 0.15, 0.80, 0.40), ("Rail3V3", ["+3V3"], 0.30, 0.15, 0.60, 0.30)]
GND_VIA = (0.60, 0.30)
IN2_POUR = "+3V3"

STACKUP = [
    ("F.SilkS", "Top Silk Screen", None, None, None),
    ("F.Paste", "Top Solder Paste", None, None, None),
    ("F.Mask", "Top Solder Mask", 0.015, None, 3.8),
    ("F.Cu", "copper", 0.035, None, None),
    ("dielectric 1", "prepreg", 0.2104, "7628 RC49%", 4.4),
    ("In1.Cu", "copper", 0.0152, None, None),
    ("dielectric 2", "core", 1.065, "FR4", 4.6),
    ("In2.Cu", "copper", 0.0152, None, None),
    ("dielectric 3", "prepreg", 0.2104, "7628 RC49%", 4.4),
    ("B.Cu", "copper", 0.035, None, None),
    ("B.Mask", "Bottom Solder Mask", 0.015, None, 3.8),
    ("B.Paste", "Bottom Solder Paste", None, None, None),
    ("B.SilkS", "Bottom Silk Screen", None, None, None),
]
STACK_ID = "JLC04161H-7628"


# Order notes every coupon shares (release.py writes them into ORDER-NOTES.md after the board's own).
FAB_NOTES = [
    f"**PCB:** 4 layers, 1.6 mm, FR-4, 1 oz outer / 0.5 oz inner copper, JLC's standard 4-layer stack "
    f"({STACK_ID}; no impedance control ordered), ENIG (HASL lead-free would do: the finest pitch is 0.65 mm), "
    "green mask, white silk. L2 (In1) is a solid GND plane (a no-track rule area keeps the routers off it), L3 (In2) "
    "a +3V3 pour.",
    "**Design rules used:** track 0.20 mm and clearance 0.15 mm by default (the board's own notes above give its "
    "wider, pre-routed paths); vias "
    "0.60 / 0.30 mm (JLC's standard via, no surcharge); copper >= 0.30 mm from the edge. JLC's 4-layer minimums are "
    "0.09 / 0.09 mm and a 0.15 mm hole: nothing here is near them.",
    "**J1, the slot header, is through-hole and mounted on the BOTTOM side** (body against the bottom, pins down; "
    "soldered on the top side). Either JLC fits it (JLC stocks the part, LCSC C25503140; check on the order form "
    "that JLC accepts a through-hole part with its body on the bottom), or order J1 as do-not-place and hand-solder "
    "it: 40 joints from the top, the body flat against the bottom, square with the edge. The two halves only mate "
    "if the header is on the bottom (boards/coupon_common.py check_mating()). The 2541WV drawing limits soldering "
    "to 220 C for 10 s (PBT body), below a lead-free wave's temperature, and a wave or selective nozzle from the "
    "bottom would meet the body: the joints are soldered on the top side.",
    "**The 2 x 20 header has no key.** Plug a coupon with its SLOT EDGE / pin 1 silk over the motherboard socket's "
    "pin 1 and its post hole over the slot's spacer; turned 180 degrees, +5V meets GND pins (the slot switch "
    "limits the current). Never hot-plug: the slot's LED must be off (SPEC §3.5).",
    "**Not on the PCBA:** the M3 x 11 mm nylon spacer and screw on H1 (SPEC §9), bought separately.",
    "**Assembly size:** 58 x 60 mm (standard coupon) or 80 x 60 mm (wide) is under the 70 x 70 mm minimum this "
    "repository's caliper notes give for JLC's Standard PCBA (not re-checked for this board): if the order form "
    "asks for it, order with JLC's edge rails, or panelise, or use Economic PCBA if it takes the parts.",
]


def pin_xy(n):
    """Top-view position (board mm) of slot pin n on the coupon, and of the socket pin it plugs into."""
    k = (n - 1) // 2
    return round(HEADER_X0 + PITCH * k, 4), (ROW_INNER if n % 2 else ROW_EDGE)


def outline(size=STANDARD):
    w, h = size
    return rounded_rect(0.0, 0.0, w, h, CORNER_R)


def fiducial_xy(size=STANDARD):
    w, h = size
    return [(2.0, 9.5), (w - 2.0, 9.5), (w - 2.0, h - 2.5)]


def _fp_dir(lib):
    return os.path.join(os.environ.get("KICAD10_FOOTPRINT_DIR", "/usr/share/kicad/footprints"), lib + ".pretty")


def _solve(fpid, side):
    """(x, y, rot) of the footprint origin (board mm) for which every pad n lands on pin_xy(n), placed the way
    pcbgen.place_from_netlist places it (flipped first if side == 'B', then positioned, then rotated)."""
    lib, name = fpid.split(":", 1)
    base = pcbnew.FootprintLoad(_fp_dir(lib), name)
    board = pcbnew.BOARD()                       # Flip() needs the footprint on a board
    for rot in (0.0, 90.0, 180.0, 270.0):
        fp = pcbnew.FOOTPRINT(base)
        board.Add(fp)
        if side == "B":
            fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
        fp.SetPosition(pcbnew.VECTOR2I(0, 0))
        fp.SetOrientationDegrees(rot)
        rel = {p.GetNumber(): (TO(p.GetPosition().x), -TO(p.GetPosition().y)) for p in fp.Pads()}
        tx, ty = pin_xy(1)
        dx, dy = tx - rel["1"][0], ty - rel["1"][1]
        err = max(abs(rel[n][0] + dx - pin_xy(int(n))[0]) + abs(rel[n][1] + dy - pin_xy(int(n))[1]) for n in rel)
        if err < 1e-4:
            return round(dx, 4), round(dy, 4), rot
    raise RuntimeError(f"{fpid} on side {side}: no rotation puts every pad on its slot position")


def header_placement():
    """The coupon's J1: (x, y, rot, 'B') in board mm."""
    return (*_solve(HEADER_FP, "B"), "B")


def socket_placement():
    """The motherboard's slot socket, relative to the slot's origin (the coupon's lower-left corner projected onto the
    motherboard, same axes): (x, y, rot, 'F')."""
    return (*_solve(SOCKET_FP, "F"), "F")


def check_mating():
    """Both halves solved: every one of the 40 pins at the same top-view position. Returns the two placements."""
    h, s = header_placement(), socket_placement()
    return h, s


def fixed(comps, size=STANDARD):
    """The placements every coupon shares: J1 (bottom), H1, FID1-FID3, the wire pads TP1-TP4."""
    out = {"J1": header_placement(), "H1": (*POST, 0.0, "F")}
    for i, (x, y) in enumerate(fiducial_xy(size), 1):
        out[f"FID{i}"] = (x, y, 0.0, "F")
    for i, (x, y) in enumerate(WIRE_PAD_XY, 1):
        out[f"TP{i}"] = (x, y, 0.0, "F")
    return {r: v for r, v in out.items() if r in comps}


def keepouts(size=STANDARD):
    """Placer keep-outs (side, predicate(x, y) in board mm): the header's pin tails on the top (they stand about
    1.4 mm out of a 1.6 mm board), the post, and the whole bottom (only J1 sits there; SPEC §9 allows <= 2 mm)."""
    x0, _, x1, _ = HEADER_BODY

    def header_tails(x, y):
        return x0 - 0.5 <= x <= x1 + 0.5 and y <= 7.4

    def post(x, y):
        return (x - POST[0]) ** 2 + (y - POST[1]) ** 2 < POST_PART_R ** 2

    return [("F", header_tails), ("*", post), ("B", lambda x, y: True)]


def build(bb, size=STANDARD, title="", ref_text="", in1_tracks=False):
    """Rule areas and documentation every coupon carries (layout.py draws the outline and the In1 GND plane).
    Unless `in1_tracks`, In1 gets a no-track rule area (vias, pads and the GND plane allowed): KiCad exports it to
    Freerouting as a wire keep-out, layout.py's clean-up deletes any track inside it, and DRC flags one."""
    cu = [pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu]
    bb.keepout(cu, page(circle(*POST, POST_COPPER_R, 36)), tracks=True, vias=True, pads=False, pours=True,
               name="POST_NO_COPPER")
    if not in1_tracks:
        w, h = size
        bb.keepout([pcbnew.In1_Cu], page(rect(0.0, 0.0, w, h)), tracks=True, vias=False, pads=False, pours=False,
                   name="IN1_PLANE_NO_TRACKS")
    for i, (x, y) in enumerate(fiducial_xy(size), 1):
        bb.keepout([pcbnew.F_Cu], page(circle(x, y, FID_KEEPOUT_R, 24)), pads=False, pours=True,
                   name=f"FID{i}_KEEPCLEAR")
    # documentation: the header body (bottom), its pin 1, the post
    bb.polyline(pcbnew.B_Fab, page(rect(*HEADER_BODY)), 0.1, closed=True)
    bb.text(pcbnew.B_Fab, "J1 SLOT HEADER (BOTTOM), BODY 50.8 x 5.0", *page([(HEADER_XC, 8.0)])[0], 0.8, mirror=True)
    x1, y1 = pin_xy(1)
    bb.text(pcbnew.F_SilkS, "1", *page([(x1 - 1.9, y1)])[0], 0.8)
    x40, y40 = pin_xy(40)
    bb.text(pcbnew.F_SilkS, "40", *page([(x40 + 2.2, y40)])[0], 0.8)
    bb.text(pcbnew.F_SilkS, "SLOT EDGE", *page([(HEADER_XC, 8.4)])[0], 0.8)
    if title:
        bb.text(pcbnew.F_SilkS, title, *page([(size[0] / 2, size[1] - 6.0)])[0], 1.0)
    if ref_text:
        bb.text(pcbnew.B_SilkS, ref_text, *page([(size[0] / 2, size[1] / 2)])[0], 1.0, mirror=True)


def pours(bb, size=STANDARD, in2=IN2_POUR):
    """GND on F.Cu and B.Cu, `in2` (default +3V3) on In2, all 0.3 mm inside the edge. The In1 GND plane is drawn
    before routing by layout.py."""
    w, h = size
    ol = page(rounded_rect(0.3, 0.3, w - 0.3, h - 0.3, max(CORNER_R - 0.3, 0.0)))
    bb.zone("GND", [pcbnew.F_Cu], ol, priority=0, clearance=0.25, name="GND_TOP")
    bb.zone("GND", [pcbnew.B_Cu], ol, priority=0, clearance=0.25, name="GND_BOT")
    if in2:
        bb.zone(in2, [pcbnew.In2_Cu], ol, priority=0, clearance=0.25, name=f"{in2.strip('+')}_IN2")


def board_xy(fp):
    """A footprint's position in board mm."""
    p = fp.GetPosition()
    return B(TO(p.x), TO(p.y))
