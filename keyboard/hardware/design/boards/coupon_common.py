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

**The header and the socket.** The coupon's header (`HEADER_FP`: KiCad's `PinHeader_2x20_P2.54mm_Vertical` less
pad 39, `keyed_header()`) sits on the coupon's **bottom**, body down. The motherboard's socket (KiCad
`PinSocket_2x20_P2.54mm_Vertical`; candidate BOOMELE 2.54-2*20P, LCSC C5124634, 8.5 mm, 2.5 A per contact, Ø1.1 mm
holes in its drawing PY2.54-2*NA-8.5MM-Y, KiCad's Ø1.0 drill taking its 0.64 x 0.40 mm tail) sits on the
motherboard's **top**, under the coupon, with every pin n at the same top-view position as the coupon's pin n.
`header_placement()` and `socket_placement()` solve the footprint position and rotation for that; `check_mating()`
compares the header's 39 pads with the socket's 40, pad by pad, and fails on any difference (run by every coupon's
post_fixed()). Heights: socket 8.5 mm + the header's 2.54 mm plastic = 11.04 mm from the
motherboard's top to the coupon's underside (SPEC §9 says 11: 8.5 + 2.5). The header's mating pins are 6.00 mm, so
they do not bottom out in the 8.5 mm socket.

**The key** (the owner's decision D2 of 2026-11-27, SPEC §4.2, `nets.SLOT_KEY_PIN`). Pin 39 is absent from every
coupon: `HEADER_FP` (`keyboard:PinHeader_2x20_P2.54mm_Vertical`, written into each coupon's own library by
sheets/coupon_common.footprints()) is the stock land with pad 39 removed, an X on its silk where the pin was (on the
coupon's bottom, under the header body: the assembler's mark) and a note on its fab layer; `build()` puts an X and
"KEY" on the top silk at the same place. The header's pin 39 is pulled before soldering. The motherboard socket keeps
all 40 contacts, pin 39 with no net, its hole plugged. Turned 180 degrees about the header's centre, coupon pin p
lands on socket position 41 - p, so the coupon's pin 2 meets the plugged contact 39 and the coupon does not go in;
`check_mating()` checks that as well. The footprint keeps the stock name, in the "keyboard" library, so that
keyboard/tools/coupon/rules.py (which matches the header by name) finds it; `HEADER_FP_STOCK` is the stock one.

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

import nets
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
KEY_PIN = nets.SLOT_KEY_PIN                   # 39: absent on every coupon (D2 of 2026-11-27)
KEY_NEVER_WITH = nets.SLOT_KEY_NEVER_WITH     # 2: must stay a real pin, or the key works both ways round
HEADER_FP_STOCK = "Connector_PinHeader_2.54mm:PinHeader_2x20_P2.54mm_Vertical"
HEADER_FP = "keyboard:PinHeader_2x20_P2.54mm_Vertical"       # HEADER_FP_STOCK less pad 39 (keyed_header())
SOCKET_FP = "Connector_PinSocket_2.54mm:PinSocket_2x20_P2.54mm_Vertical"
SOCKET_PART = {"MPN": "2.54-2*20P", "Manufacturer": "BOOMELE(Boom Precision Elec)", "LCSC": "C5124634",
               "note": "female 2 x 20, 2.54 mm, 8.5 mm, THT; 6344 in stock at JLC, $0.33 (2026-11-28)"}
HEADER_PART = {"MPN": "2541WV-2x20P", "Manufacturer": "HanElectricity", "LCSC": "C25503140",
               "note": "male 2 x 20, 2.54 mm, 6.0 mm mating, THT; 506 in stock at JLC, $0.14 (2026-11-28); "
                       "pin 39 pulled before soldering (the slot key)"}
KEY_MARK = 0.6                                # half-length of the key mark's X arms, mm (silk, 0.15 mm lines)

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
    "**J1, the slot header, is keyed at pin 39 (the owner's decision D2 of 2026-11-27, SPEC §4.2) and fitted by "
    "hand: it is DNP for the assembler and in neither the JLC BOM nor the CPL.** The footprint has no pad and no hole "
    "at 39 (marked X on both silk layers), so a 2541WV-2x20P with all 40 pins does not go in, and jlcplace finds "
    "EasyEDA's pad 39 off copper (red). JLC listed no 2 x 20 header sold without pin 39 on 2026-11-27 (SPEC §4.2), "
    "so JLC cannot fit J1 as it comes (SPEC §11 #31). Buy it separately (LCSC C25503140, in the vendor-neutral BOM), "
    "pull pin 39 out of the header with pliers from the mating side, and solder it as below. Pin 39 is a corner "
    "pin: the inner row (away from the slot edge), at the end opposite pin 1, under the X. The header itself is "
    "symmetric, so pull any one corner pin and fit the header with the gap over the X; it goes in no other way "
    "round. This is the key's "
    "consequence; whether coupons then go as Economic PCBA is still the owner's open item (SPEC §11 #26, risk "
    "register recommendation 11, not decided). If a header sold without pin 39 is found, or JLC agrees to pull the "
    "pin, sheets/coupon_common.slot_sheet(header_dnp=False) puts J1 back in the JLC BOM and CPL.",
    "**J1 is through-hole and mounted on the BOTTOM side** (body against the bottom, pins down; soldered on the top "
    "side): 39 joints from the top, the body flat against the bottom, square with the edge. The two halves only "
    "mate if the header is on the bottom (boards/coupon_common.py check_mating()). The 2541WV drawing limits "
    "soldering to 220 C for 10 s (PBT body), below a lead-free wave's temperature, and a wave or selective nozzle "
    "from the bottom would meet the body: the joints are soldered on the top side. A 2 x 20 socket (the "
    "motherboard's, hole 39 plugged, with the slot's M3 spacer fitted, or a loose C5124634) holds the header square "
    "while its joints are soldered (risks.md SF-2).",
    "**Plugging a coupon in:** the SLOT EDGE / pin 1 silk over the motherboard socket's pin 1 and the post hole over "
    "the slot's spacer. Turned 180 degrees, the coupon's pin 2 meets the socket's plugged contact 39 and the coupon "
    "does not go in (the motherboard plugs hole 39; SPEC §4.2). Never hot-plug: the slot's LED must be off "
    "(SPEC §3.5).",
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


def keyed_header():
    """The coupon's slot header land (HEADER_FP), a new FOOTPRINT: KiCad 10.0.8's PinHeader_2x20_P2.54mm_Vertical
    with pad 39 removed (the key, D2 of 2026-11-27), an X on its F.SilkS where pad 39 was (the coupon's bottom silk,
    since J1 is flipped), "KEY 39" on its F.Fab, and the stock 3D model (which still draws 40 pins). Every other pad,
    the courtyard, silk and fab are the stock footprint's, so the mating geometry is unchanged."""
    lib, name = HEADER_FP_STOCK.split(":", 1)
    stock = pcbnew.FootprintLoad(_fp_dir(lib), name)
    if stock is None:
        raise RuntimeError(f"{HEADER_FP_STOCK} not found under {_fp_dir(lib)}")
    fp = pcbnew.FOOTPRINT(stock)
    key = next((p for p in fp.Pads() if p.GetNumber() == str(KEY_PIN)), None)
    if key is None:
        raise RuntimeError(f"{HEADER_FP_STOCK} has no pad {KEY_PIN} to remove")
    kx, ky = key.GetFPRelativePosition().x, key.GetFPRelativePosition().y
    fp.Remove(key)
    fp.SetFPIDAsString(HEADER_FP.split(":", 1)[1])
    fp.SetLibDescription(f"{stock.GetLibDescription()}; pad {KEY_PIN} removed: the rev A slot key (owner's decision "
                         f"D2 of 2026-11-27, keyboard SPEC §4.2); pull the header's pin {KEY_PIN} before soldering. "
                         f"Derived from KiCad 10.0.8 {HEADER_FP_STOCK} by boards/coupon_common.keyed_header()")
    fp.SetKeywords(f"{stock.GetKeywords()} keyed key pin{KEY_PIN}")
    d = pcbnew.FromMM(KEY_MARK)
    for (ax, ay), (bx, by) in (((-d, -d), (d, d)), ((-d, d), (d, -d))):
        seg = pcbnew.PCB_SHAPE(fp)
        seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
        seg.SetStart(pcbnew.VECTOR2I(kx + ax, ky + ay))
        seg.SetEnd(pcbnew.VECTOR2I(kx + bx, ky + by))
        seg.SetLayer(pcbnew.F_SilkS)
        seg.SetWidth(pcbnew.FromMM(0.15))
        fp.Add(seg)
    txt = pcbnew.PCB_TEXT(fp)
    txt.SetText(f"KEY {KEY_PIN}")
    txt.SetLayer(pcbnew.F_Fab)
    txt.SetPosition(pcbnew.VECTOR2I(kx - pcbnew.FromMM(2.6), ky))
    txt.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(0.8), pcbnew.FromMM(0.8)))
    txt.SetTextThickness(pcbnew.FromMM(0.12))
    fp.Add(txt)
    return fp


def _base(fpid):
    if fpid == HEADER_FP:
        return keyed_header()
    lib, name = fpid.split(":", 1)
    return pcbnew.FootprintLoad(_fp_dir(lib), name)


def _solve(fpid, side):
    """(x, y, rot) of the footprint origin (board mm) for which every pad n lands on pin_xy(n), placed the way
    pcbgen.place_from_netlist places it (flipped first if side == 'B', then positioned, then rotated)."""
    base = _base(fpid)
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


def _placed_pads(fpid, placement):
    """{pad number: top-view (x, y) board mm} of a footprint placed as pcbgen places it."""
    x, y, rot, side = placement
    board = pcbnew.BOARD()
    fp = pcbnew.FOOTPRINT(_base(fpid))
    board.Add(fp)
    if side == "B":
        fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
    fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(-y)))
    fp.SetOrientationDegrees(rot)
    return {p.GetNumber(): (round(TO(p.GetPosition().x), 4), round(-TO(p.GetPosition().y), 4)) for p in fp.Pads()}


def check_mating():
    """Both halves solved and checked pad by pad (top view, board mm), and the key (D2 of 2026-11-27):

    * the socket has all 40 contacts, each on pin_xy(n);
    * the coupon's header has every pad but 39, each on the socket contact of the same number;
    * turned 180 degrees about the header's centre, the header's pad p lands on socket contact 41 - p, and its pad 2
      (KEY_NEVER_WITH, a real pin) on the plugged contact 39: a turned coupon cannot go in.

    Raises AssertionError on any difference. Returns the two placements (header, socket)."""
    h, s = header_placement(), socket_placement()
    hp, sp = _placed_pads(HEADER_FP, h), _placed_pads(SOCKET_FP, s)
    want = {str(n) for n in range(1, 41)}
    assert set(sp) == want, f"socket pads {sorted(set(sp) ^ want, key=int)} differ from 1-40"
    assert set(hp) == want - {str(KEY_PIN)}, (f"header pads {sorted(set(hp) ^ (want - {str(KEY_PIN)}), key=int)} "
                                              f"differ from 1-40 less the key pin {KEY_PIN}")
    for n, (x, y) in sp.items():
        ex, ey = pin_xy(int(n))
        assert abs(x - ex) < 1e-3 and abs(y - ey) < 1e-3, f"socket pad {n} at {(x, y)}, want {(ex, ey)}"
    for n, (x, y) in hp.items():
        assert abs(x - sp[n][0]) < 1e-3 and abs(y - sp[n][1]) < 1e-3, f"header pad {n} at {(x, y)}, socket {sp[n]}"
    cx, cy = HEADER_XC, (ROW_INNER + ROW_EDGE) / 2
    for n, (x, y) in hp.items():                  # turned 180 degrees about the header's centre
        tx, ty = 2 * cx - x, 2 * cy - y
        m = 41 - int(n)
        assert abs(tx - sp[str(m)][0]) < 1e-3 and abs(ty - sp[str(m)][1]) < 1e-3, f"turned, pad {n} misses {m}"
    assert str(KEY_NEVER_WITH) in hp and 41 - KEY_NEVER_WITH == KEY_PIN, \
        f"turned, header pad {KEY_NEVER_WITH} must meet the plugged contact {KEY_PIN}"
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
    # the key (D2 of 2026-11-27): an X where pin 39 would be, and "KEY" above it, inside the header-tail keep-out
    # (no part sits there on any coupon); the footprint's own X marks the same place on the bottom silk
    kx, ky = pin_xy(KEY_PIN)
    for (ax, ay), (bx_, by_) in (((-1, -1), (1, 1)), ((-1, 1), (1, -1))):
        bb.polyline(pcbnew.F_SilkS, page([(kx + ax * KEY_MARK, ky + ay * KEY_MARK),
                                          (kx + bx_ * KEY_MARK, ky + by_ * KEY_MARK)]), 0.15)
    bb.text(pcbnew.F_SilkS, "KEY", *page([(kx, ky + 1.75)])[0], 0.8)
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
