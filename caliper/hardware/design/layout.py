#!/usr/bin/env python3
"""Generate the PrettyCool Caliper PCBs (slider + scale) from the KiCad netlists.

usage: python3 caliper/hardware/design/layout.py [--board slider|scale] [--route] [--minutes N] [--attempts N]
                                                 [--finish | --complete | --resume]

Adapted from dial-me-spinner's hardware/design/layout.py (same toolchain, repo-root tools/).

Coordinates: everything below is in **board mm** as SPEC §2.1 gives them: origin = the lower-left corner of the
62 x 34 slider body (the beam's lower, jaw-side edge is y = 0), +x along the beam, **+y up**, seen from the top.
KiCad's page has +y down; P() maps board -> page, B() back. The drill/place (aux) origin is the board origin, so the
CPL and the gerbers use board mm directly.

Slider (4 layers, 1.0 mm): F.Cu signals + parts, In1 solid GND plane, In2 +3V3 pour + signals + the 8 electrode
phase buses, B.Cu sensors (AS5311, electrode comb, guards) + signals. The parts SPEC §2.1 places are placed and locked
here; every other part is placed near its IC pin or in its SPEC cluster region by the greedy placer. The capacitive
electrode comb (64 fingers, 8 phases, the RX strip and the guards, SPEC §2.2) is drawn as copper on the E40 nets, so
connectivity and DRC check it like any other copper.

Scale (2 layers, 0.8 mm, 200 x 7): the reflector/coupler cells are no-net copper polygons on F.Cu (isolated by
design), the back is one solid GND zone, two Ø1.0 alignment holes, two fiducials.
"""

from __future__ import annotations

import argparse
import math
import os
import re
import shutil
import subprocess
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
HW = os.path.dirname(HERE)                                  # caliper/hardware
REPO = os.path.dirname(os.path.dirname(HW))                 # repo root
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, HERE)

import pcbnew  # noqa: E402

import finish_route  # noqa: E402
import pcbgen  # noqa: E402
import silk  # noqa: E402
from placer import Placer  # noqa: E402

import nets as contract  # noqa: E402

pcbgen.UUID_NAMESPACE = "prettycool-caliper"
OX, OY = 100.0, 100.0          # page position of the board origin (mm)
KICAD_DIR = os.path.join(HW, "kicad")
FREEROUTING = os.environ.get("FREEROUTING_JAR", "/opt/freerouting/freerouting.jar")
LIB = "caliper"
MM = pcbgen.MM
TO = pcbnew.ToMM


def P(x, y):
    """board mm (+y up) -> page mm (+y down)"""
    return OX + x, OY - y


def B(X, Y):
    """page mm -> board mm"""
    return X - OX, OY - Y


def V(x, y):
    """board mm -> VECTOR2I"""
    return pcbgen.vec(*P(x, y))


def bxy(item):
    """board-mm position of a pad / footprint / via"""
    p = item.GetPosition()
    return B(TO(p.x), TO(p.y))


def refnum(ref):
    m = re.match(r"[A-Za-z]+(\d+)", ref)
    return int(m.group(1)) if m else 0


def mpn(c):
    return (c["fields"].get("MPN") or c["value"] or "").upper()


def net_short(name):
    return name.split("/")[-1]


# --------------------------------------------------------------------------- footprint-local helpers (from dial-me-spinner)
_LIB_FP_CACHE = {}
_FP_LIBS = {}


def fp_lib_path(fp):
    fpid = fp.GetFPIDAsString()
    if ":" not in fpid:
        return None
    nick, name = fpid.split(":", 1)
    return _FP_LIBS.get(nick, os.path.join(pcbgen.FP_DIR, nick + ".pretty")), name


def _lib_fp(fp):
    key = fp.GetFPIDAsString()
    if key not in _LIB_FP_CACHE:
        path = fp_lib_path(fp)
        _LIB_FP_CACHE[key] = pcbnew.FootprintLoad(*path) if path else None
    return _LIB_FP_CACHE[key]


def local_map(fp):
    """Affine map (footprint-local mm -> PAGE mm) solved from the pads, so flips/rotations are exact."""
    import numpy as np
    ref = _lib_fp(fp)
    lib_pads, brd_pads = list(ref.Pads()), list(fp.Pads())
    xy = lambda p: (TO(p.GetPosition().x), TO(p.GetPosition().y))  # noqa: E731
    src, dst = [xy(a) for a in lib_pads], [xy(b) for b in brd_pads]
    A = np.c_[np.array(src), np.ones(len(src))]
    sol, *_ = np.linalg.lstsq(A, np.array(dst), rcond=None)
    return lambda x, y: tuple(float(v) for v in np.array([x, y, 1.0]) @ sol)


def local_dir_board(fp, lx, ly):
    """Unit direction in BOARD coordinates of the footprint-local vector (lx, ly)."""
    m = local_map(fp)
    x0, y0 = B(*m(0.0, 0.0))
    x1, y1 = B(*m(lx, ly))
    d = math.hypot(x1 - x0, y1 - y0)
    return (x1 - x0) / d, (y1 - y0) / d


def set_pad(pad, x, y, sx, sy):
    """Move/resize an instance pad (board mm)."""
    pad.SetPosition(V(x, y))
    try:
        pad.SetSize(pcbnew.F_Cu, pcbnew.VECTOR2I(MM(sx), MM(sy)))
    except TypeError:
        pad.SetSize(pcbnew.VECTOR2I(MM(sx), MM(sy)))


def add_track(board, a, b, layer, net, width, locked=True):
    """Track between two board-mm points."""
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(V(*a))
    t.SetEnd(V(*b))
    t.SetWidth(MM(width))
    t.SetLayer(layer)
    t.SetNet(net)
    t.SetLocked(locked)
    board.Add(t)
    return t


def add_via(board, at, net, dia=0.40, drill=0.20, locked=True):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(V(*at))
    v.SetWidth(MM(dia))
    v.SetDrill(MM(drill))
    v.SetNet(net)
    v.SetLocked(locked)
    board.Add(v)
    return v


def add_shape_seg(board, layer, a, b, width):
    s = pcbnew.PCB_SHAPE(board)
    s.SetShape(pcbnew.SHAPE_T_SEGMENT)
    s.SetStart(V(*a))
    s.SetEnd(V(*b))
    s.SetLayer(layer)
    s.SetWidth(MM(width))
    board.Add(s)
    return s


def add_poly(board, layer, pts, net=None, width=0.0, filled=True):
    """Filled polygon (board mm) on a layer: copper graphics (optionally with a net), mask openings, fab outlines."""
    s = pcbnew.PCB_SHAPE(board)
    s.SetShape(pcbnew.SHAPE_T_POLY)
    s.SetPolyPoints([V(*p) for p in pts])
    s.SetLayer(layer)
    s.SetWidth(MM(width))
    s.SetFilled(filled)
    if net is not None:
        s.SetNet(net)
    board.Add(s)
    return s


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def rounded_outline(corners, radii, n=8):
    """Polygon (board mm) through `corners` with each corner filleted by its radius (convex or concave)."""
    out = []
    m = len(corners)
    for i in range(m):
        p0, p1, p2 = corners[i - 1], corners[i], corners[(i + 1) % m]
        r = radii[i]
        if r <= 0:
            out.append(p1)
            continue
        u = (p0[0] - p1[0], p0[1] - p1[1])
        w = (p2[0] - p1[0], p2[1] - p1[1])
        lu, lw = math.hypot(*u), math.hypot(*w)
        u, w = (u[0] / lu, u[1] / lu), (w[0] / lw, w[1] / lw)
        a = (u[0] * r, u[1] * r)          # 90-degree corners only: tangent points are r along each edge
        b = (w[0] * r, w[1] * r)
        c = (p1[0] + a[0] + b[0], p1[1] + a[1] + b[1])   # fillet centre
        s = (p1[0] + a[0], p1[1] + a[1])
        e = (p1[0] + b[0], p1[1] + b[1])
        a0 = math.atan2(s[1] - c[1], s[0] - c[0])
        a1 = math.atan2(e[1] - c[1], e[0] - c[0])
        da = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
        for k in range(n + 1):
            t = a0 + da * k / n
            out.append((c[0] + r * math.cos(t), c[1] + r * math.sin(t)))
    return out


def poly_page(pts):
    return [P(x, y) for x, y in pts]


# --------------------------------------------------------------------------- slider geometry (SPEC §2.1 / §2.2, nets.py)
BODY = contract.SLIDER_OUTLINE["body"]
TABS = contract.SLIDER_OUTLINE["tabs"]
ANT = contract.SLIDER_KEEPOUTS["antenna_all_layers"]            # x 0..21, y 29..34
# The module's own top pad row (GND, pads 46-60 and corner pads 62/65) reaches board y 29.1; the antenna area itself
# starts at y 29.5. The all-layer rule area therefore starts at y 29.2 (0.1 above the pad copper), not 29.0.
ANT_Y0 = 29.2
BOT_WIN = contract.SLIDER_KEEPOUTS["bottom_parts_allowed"]      # x 20..41, y 2.4..9.6
GLASS = (17.5, 1.2, 48.5, 18.8)
GLASS_RIBS = contract.SLIDER_KEEPOUTS["under_glass_max_2p6"]
CLUSTER = (50.5, 2.5, 61.5, 20.5)                              # charger / buck-boost / gauge / rail switches

# electrodes (SPEC §2.2 table)
EL_X0, EL_PITCH, EL_N, EL_FW = 10.68, 0.635, 64, 0.30
EL_FY0, EL_FY1 = 13.55, 17.35
EL_RX = (10.68, 51.32, 11.05, 12.35)
EL_GUARD_IN = (9.98, 52.02, 12.65, 13.25)
EL_RING = (9.58, 52.42, 10.35, 18.05, 0.40)
EL_ROW0 = 13.75                     # seed-finger vias (k = 0..7): just below the module's bottom pad row (y 14.3)
EL_ROW_STEP = 0.45
# The TX ladder sits below the module, left of the comb: one column per phase at x LADDER_X(n), R7n (100R) over R6n
# (0R). Each seed via drops on F.Cu to y SEED_RUN_Y(n) and runs left to its column: seed n (x rising with n) turns at a
# lower height the further right it is, so no stub crosses another. With the ladder here, the TX lines from the
# module reach it down the left corridor instead of through the corner where the module's right pad column meets
# the electrode via field (the LCD lines need that corner).
R7_Y, R6_Y = 10.4, 8.0


def LADDER_X(n):
    return 2.3 + 1.05 * n


def SEED_RUN_Y(n):
    return 13.3 - 0.25 * n
RX_FEED = (42.0, 11.70)
SEED_FC = (EL_X0 + EL_FW / 2, (EL_FY0 + EL_FY1) / 2)           # finger 0 centre = E40 origin

# test pads by proximity (x 22.5 + 2.54 i): MCU / USB next to the module, sensor and UI in the middle, the rails at
# the right end next to the charger cluster (a VBUS pad at x 22.5 dragged a 0.3 mm trace across the board)
# TP22 (D+) and TP23 (D-) sit at the east end of the lower row, on the two sides of the USB pair's 45-degree leg
# (preroute_usb_pair): D+ taps TP22 with a 2.7 mm stub, D- runs through TP23. None = an empty grid spot.
TP_ROW1 = ["TP20", "TP21", None, None, "TP50", "TP51", "TP7", "TP4", "TP2", "TP3", "TP1"]
TP_ROW2 = ["TP30", "TP31", "TP32", "TP40", "TP41", "TP42", "TP5", "TP6", "TP22", None, "TP23"]


def finger_x(k):
    return EL_X0 + EL_PITCH * k + EL_FW / 2


def el_row(p):
    """In2 bus height of phase p: phase 7 lowest (13.75) ... phase 0 highest (16.90). Each bus starts at its seed via
    (finger p, y 13.75) and climbs at 45 degrees to its row before the next seed, so no two buses cross."""
    return EL_ROW0 + EL_ROW_STEP * (7 - p)


def finger_via(k):
    return finger_x(k), (EL_ROW0 if k < 8 else el_row(k % 8))


def slider_fixed(comps):
    """SPEC §2.1 placement table: ref -> (x, y, rot, side) in board mm. Deviations (all <= 1 mm, SPEC allows them
    while every rule still holds) are commented."""
    P_ = {
        # x 7.85 (SPEC 8.3): with the right pad column 0.45 further left, finger 8's via clears it (SPEC allows <= 1)
        "U10": (7.85, 24.25, 0.0, "F"),
        # 7.5 (SPEC 8.5): the upper MP pad would otherwise sit on the electrode via rows (y >= 13.55)
        "J50": (21.5, 7.5, 270.0, "F"),
        "J1": (59.3, 26.5, 90.0, "F"),
        "SW50": (31.0, 31.0, 0.0, "F"), "SW51": (38.5, 31.0, 0.0, "F"), "SW52": (46.0, 31.0, 0.0, "F"),
        "D50": (51.5, 32.0, 0.0, "F"),
        # 30.6 (SPEC 31.4): at 31.4 the front fitting-nail pads (MP) cross the top edge
        "J2": (24.5, 30.6, 180.0, "F"),
        # RT1 2.2 left of SPEC's (24.5, 26.5) (still beside J2, over the cell) so the reverse-polarity FET Q1 sits
        # right under J2 pin 1 (drain pad 3 up, toward it)
        "RT1": (22.3, 26.75, 0.0, "F"),
        "Q1": (25.1, 25.1, 90.0, "F"),
        # the gauge's VBAT cap between Q1 and U4's VBAT pins 2/3 (x 28.61), under J2's courtyard
        "C7": (27.37, 26.3, 90.0, "F"),
        "BZ50": (40.0, 24.3, 0.0, "F"),
        "U60": (30.0, 23.5, 0.0, "F"),
        "U30": (31.0, 6.0, 90.0, "B"),
        # C30 (100 nF) beside the VDD pins 18/19 (review 2026-11-08: at SPEC's x 25.5 it was 8.1 mm from them and 14.9 mm
        # of track); still inside the D2 bottom window (x 20..41, y 2.4..9.6). C31 (1 uF) stays at SPEC's 36.5
        "C30": (35.45, 8.6, 0.0, "B"), "C31": (36.5, 6.0, 0.0, "B"),
        "U40": (42.0, 5.0, 0.0, "F"),
        # rotated 90 (SPEC: no rotation given) so its pads clear the electrode via rows
        "SW20": (27.0, 15.7, 90.0, "F"),
        # U1 1.2 left of SPEC's 53.0 (its VBUS pin would sit under the D+/D- crossover behind J1's pads)
        "U1": (50.2, 26.3, 0.0, "F"),
        "D1": (51.3, 22.0, 90.0, "F"),
        "R1": (53.4, 23.7, 90.0, "F"), "R2": (53.4, 29.0, 90.0, "F"),
        # U4 (fuel gauge) by the battery connector J2, not in the charger cluster (SPEC lists it there): its CELL/VDD
        # pins sense VBAT at the cell's connector, its I2C / ALRT lines stay short, and the cluster has no room to let
        # them out (the electrode ring blocks In2/B.Cu up to x 52.4)
        "U4": (29.6, 27.2, 0.0, "F"), "U5": (52.2, 4.6, 90.0, "F"), "U6": (53.0, 12.9, 90.0, "F"),
        # U5 (TPS22917) input / output caps at its pins (review 2026-11-08: the pin-anchored placer could not find room
        # inside the SPEC cluster box and left them 6.5 / 7.0 mm away). C8 sits below U5 (y 1.55, 0.95 under the SPEC
        # cluster box's y 2.5; the 4.2 mm height rule still holds), GND pad next to U5's GND pin; C10 left of U5
        # (x 49.75, 0.75 left of the box), 1.5 mm from VOUT
        "C8": (51.3, 1.55, 0.0, "F"), "C10": (49.75, 5.5, 90.0, "F"),
        # RX jumper right under the RX feed via (pad 1 = CAP_EL_RX on top), pre-routed to it
        "R80": (RX_FEED[0], 9.6, 270.0, "F"),
        # TPS63802 feedback divider right at FB (pin 4, left side), away from the L1 switch nodes
        "R4": (52.4, 8.1, 90.0, "F"), "R3": (51.3, 8.1, 90.0, "F"),
        "U3": (55.0, 9.0, 0.0, "F"),
        "L1": (58.0, 9.0, 270.0, "F"),
        "C4": (56.6, 11.65, 0.0, "F"),
        "C5": (56.6, 6.35, 0.0, "F"), "C6": (56.6, 4.55, 0.0, "F"),
        "U2": (57.2, 16.4, 0.0, "F"),
        "H1": (18.75, 24.0, 0.0, "F"),
        "H2": (-3.5, 5.5, 0.0, "F"), "H3": (-3.5, 14.0, 0.0, "F"), "H4": (65.5, 5.5, 0.0, "F"),
        "H5": (65.5, 14.0, 0.0, "F"),
        # module decoupling on the BOTTOM under its 3V3 pad 3 (0.85, 25.95), either side of that pad's escape via
        # (2.0, 25.95): C21 100n above, C23 10u below, +3V3 pad (1) toward the via. 0402, 0.5 mm tall, in the upper
        # band where the housing floor is 0.75 mm below the board (SPEC §2.1); clear of the antenna rule area (y >= 29.2)
        "C21": (3.1, 26.5, 0.0, "B"), "C23": (3.1, 25.3, 0.0, "B"),
        # FID3 (SPEC 60.5, 32.8) would sit inside J1's courtyard (it reaches y 31.9 over x 54-63): top middle instead
        "FID1": (2.0, 1.5, 0.0, "F"), "FID2": (60.5, 1.2, 0.0, "F"), "FID3": (33.0, 27.6, 0.0, "F"),
        "E40": (SEED_FC[0], SEED_FC[1], 0.0, "B"),
    }
    for i in range(8):                       # the TX ladder: one column per phase under its seed finger
        P_[f"R7{i}"] = (LADDER_X(i), R7_Y, 90.0, "F")
        P_[f"R6{i}"] = (LADDER_X(i), R6_Y, 90.0, "F")
    for row, y in ((TP_ROW1, 25.14), (TP_ROW2, 22.6)):
        for i, ref in enumerate(row):
            if ref:
                P_[ref] = (22.5 + 2.54 * i, y, 0.0, "B")
    return {r: v for r, v in P_.items() if r in comps}


# Parts placed near one pin of an IC (decoupling, pull-ups, filters): ref -> (ic, net, max_r, region or None)
SLIDER_PIN_ANCHORS = {
    # USB-C CC pull-downs at the connector
    # BQ25180: IN / SYS / BAT caps at their balls
    "C1": ("U2", "VBUS", 2.5), "C2": ("U2", "VSYS", 2.5), "C3": ("U2", "VBAT", 3.0),
    # TPS63802 feedback divider at FB

    # gauge
    # gate resistor of the battery reverse-polarity P-FET Q1 (fixed under J2 pin 1)
    "R10": ("Q1", "BATFET_G", 2.5),
    # load switches
    # (C8 / C10 are fixed next to U5 in slider_fixed)
    "C9": ("U5", "SNS_CT", 2.5), "R5": ("U5", "SNS_PWR_EN", 3.5),
    "C11": ("U6", "UI_CT", 2.5), "C12": ("U6", "+3V3_UI", 2.5),
    # capacitive front-end around U40
    "C40": ("U40", "CAP_RX_IN", 3.0), "R81": ("U40", "CAP_RX_IN", 3.5),
    "C42": ("U40", "+3V3_SNS", 2.5), "R82": ("U40", "CAP_VDIV", 3.5), "R83": ("U40", "CAP_VDIV", 3.5),
    "C41": ("U40", "CAP_VDIV", 3.5), "R84": ("U40", "CAP_AMP_OUT", 3.5), "C43": ("U40", "CAP_AMP_OUT", 5.0),
    "R85": ("U40", "CAP_AMP_OUT", 5.0), "C44": ("U40", "CAP_AMP_OUT", 6.0),
    # display
    "C50": ("J50", "+3V3_UI", 3.0), "C51": ("J50", "+3V3_UI", 3.5),
    "C55": ("D50", "+3V3_UI", 3.0), "R55": ("D50", "RGB_DIN", 4.0),
    # IMU decoupling at VDD / VDD_IO
    "C60": ("U60", "+3V3", 2.5), "C62": ("U60", "+3V3", 2.5), "C61": ("U60", "+3V3", 3.5),
    # AS5311 pull-ups (top side, over the IC)
    "R30": ("U30", "MAG_INC_N", 6.0), "R31": ("U30", "MAG_DEC_N", 6.0),
}

# Parts placed near a point inside a region (board mm): ref -> (x, y, region box)
UPPER_MID = (25.0, 19.0, 34.6, 29.0)          # between the module support hole, the piezo and the buttons
BELOW_MODULE = (0.4, 2.7, 9.9, 6.8)             # below the TX ladder (FID1 keeps the corner)
SLIDER_REGION_PARTS = {
    # I2C / alert pull-ups below the module, next to the module pins they serve (the U60 corner is full)
    "R6": (7.0, 5.8, BELOW_MODULE), "R7": (8.6, 5.8, BELOW_MODULE),
    "R8": (7.0, 4.0, BELOW_MODULE), "R9": (8.6, 4.0, BELOW_MODULE),
    # module support: the 22u bulk below the module on top (the 100n / 10u sit under pad 3 on the bottom, fixed);
    # EN RC above H1
    "C20": (3.0, 5.5, BELOW_MODULE),
    "R20": (17.6, 28.0, (16.3, 26.3, 21.0, 29.1)), "C22": (19.6, 28.0, (16.3, 26.3, 21.0, 29.1)),
    "R21": (24.0, 15.5, (16.6, 13.0, 30.5, 20.5)),
    # backlight driver beside J50, under the glass
    "Q50": (26.6, 3.6, (24.6, 0.5, 30.0, 12.5)), "R50": (26.5, 6.6, (24.6, 0.5, 30.0, 12.5)),
    "R51": (28.6, 2.0, (24.6, 0.5, 30.0, 12.5)),
    # piezo driver
    "Q51": (40.0, 18.9, (34.0, 17.3, 46.0, 20.6)), "R56": (42.8, 18.8, (34.0, 17.3, 47.5, 20.6)),
    "R57": (37.4, 18.8, (34.0, 17.3, 47.5, 20.6)),
    # button pull-ups / debounce: right of the piezo, left of the USB ESD
    "R52": (46.8, 28.0, (45.3, 18.3, 48.0, 29.1)), "C52": (46.8, 26.7, (45.3, 18.3, 48.0, 29.1)),
    "R53": (46.8, 25.4, (45.3, 18.3, 48.0, 29.1)), "C53": (46.8, 24.1, (45.3, 18.3, 48.0, 29.1)),
    "R54": (46.8, 22.8, (45.3, 18.3, 48.0, 29.1)), "C54": (46.8, 21.5, (45.3, 18.3, 48.0, 29.1)),
}


def slider_inside(X, Y, side):
    """Legal part area (page coords in): the body only (the tabs carry the clamps), 0.4 mm from the edge, no part
    in the antenna keep-out, and nothing on the bottom except the fixed parts."""
    x, y = B(X, Y)
    if side == "B":
        return False
    if not (BODY[0] + 0.4 <= x <= BODY[2] - 0.4 and BODY[1] + 0.4 <= y <= BODY[3] - 0.4):
        return False
    if x <= ANT[2] + 0.2 and y >= ANT_Y0 - 0.2:
        return False
    return True


def slider_keepouts():
    def via_band(X, Y):            # the electrode via field on F.Cu (64 finger vias + guard stitching)
        x, y = B(X, Y)
        return 9.3 <= x <= 52.7 and 13.3 <= y <= 18.25

    def tx_array(X, Y):            # the R7/R6 ladder below the module and the seed stubs feeding it
        x, y = B(X, Y)
        return (1.7 <= x <= 10.3 and 7.0 <= y <= 13.6) or (1.7 <= x <= 15.6 and 11.3 <= y <= 13.6)

    def rx_feed(X, Y):
        x, y = B(X, Y)
        return math.hypot(x - RX_FEED[0], y - RX_FEED[1]) < 1.0

    def usb_preroute(X, Y):        # the locked D+/D- crossover behind J1's pads
        x, y = B(X, Y)
        return 52.2 <= x <= 55.4 and 24.6 <= y <= 28.4

    def vbus_preroute(X, Y):       # preroute_vbus(): x 54.2 from J1's A4 pad down to C1
        x, y = B(X, Y)
        return 53.75 <= x <= 54.65 and 19.8 <= y <= 24.4

    return [("F", via_band), ("F", tx_array), ("F", rx_feed), ("F", usb_preroute), ("F", vbus_preroute)]


def slider_outline_pts():
    (x0, y0, x1, y1) = BODY
    (lt, rt) = TABS
    c = [(x0, y0), (x1, y0), (x1, rt[1]), (rt[2], rt[1]), (rt[2], rt[3]), (x1, rt[3]), (x1, y1), (x0, y1),
         (x0, lt[3]), (lt[0], lt[3]), (lt[0], lt[1]), (x0, lt[1])]
    # 1 mm on the convex corners; 0.5 mm on the four concave tab roots (the router bit leaves a radius there anyway)
    r = [1.0, 1.0, 0.5, 1.0, 1.0, 0.5, 1.0, 1.0, 0.5, 1.0, 1.0, 0.5]
    return rounded_outline(c, r)


def slider_post_fixed(bb, comps, fixed):
    """Orientation checks for the connectors and the instance-level footprint edits SPEC needs."""
    fps = bb.footprints
    # opening directions (asserted, so a library change cannot silently turn a connector around)
    checks = {"J1": ((0.0, 4.0), (1, 0)), "J50": ((0.0, 4.0), (-1, 0)), "J2": ((0.0, 2.5), (0, 1))}
    for ref, ((lx, ly), want) in checks.items():
        if ref in fps:
            d = local_dir_board(fps[ref], lx, ly)
            assert abs(d[0] - want[0]) < 0.05 and abs(d[1] - want[1]) < 0.05, f"{ref} opens toward {d}, want {want}"
    for i in range(8):   # ladder resistors: pad 2 on top (toward the finger)
        for ref in (f"R7{i}", f"R6{i}"):
            if ref in fps:
                pd = {p.GetNumber(): bxy(p) for p in fps[ref].Pads()}
                assert pd["2"][1] > pd["1"][1], f"{ref} pad 2 is not on top"
    if "U30" in fps:   # long axis (the pad rows) along X
        xs = [bxy(p)[0] for p in fps["U30"].Pads()]
        assert max(xs) - min(xs) > 5.5, "U30 long axis is not along X"
    edit_module(fps.get("U10"))
    for ref in ("H2", "H3", "H4", "H5"):
        if ref in fps:
            tab_hole(fps[ref])


def edit_module(fp):
    """ESP32-S2/S3-MINI-1 library footprint: its 45 x 19.5 mm antenna rule area and its courtyard encode Espressif's
    15 mm clearance, which SPEC §2.1 (D4) deliberately does not have (5 mm, a recorded deviation). Replace them on this
    instance by the module body courtyard; the SPEC keep-out is a board rule area (build_slider)."""
    if fp is None:
        return
    for z in list(fp.Zones()):
        fp.Remove(z)
    for g in list(fp.GraphicalItems()):
        if g.GetLayer() in (pcbnew.F_CrtYd, pcbnew.B_CrtYd):
            fp.Remove(g)
    x, y = bxy(fp)
    r = pcbnew.PCB_SHAPE(fp)
    r.SetShape(pcbnew.SHAPE_T_RECT)
    r.SetStart(V(x - 8.0, y + 10.05))
    r.SetEnd(V(x + 8.0, y - 10.55))
    r.SetLayer(pcbnew.F_CrtYd)
    r.SetWidth(MM(0.05))
    fp.Add(r)


def tab_hole(fp):
    """SPEC §2.1: the tab holes carry an SMT standoff on the TOP pad; the tab bottom is 0.15 mm over the beam, so no
    exposed bottom copper: drop B.Mask from every pad of the instance (the copper stays, under mask)."""
    for p in fp.Pads():
        ls = p.GetLayerSet()
        ls.RemoveLayer(pcbnew.B_Mask)
        p.SetLayerSet(ls)


def place_e40(bb):
    """E40 on the bottom carries the whole electrode copper as pads of its nine nets: pads 1-8 (TX0..TX7) are fingers
    0-7 resized to the SPEC 0.30 x 3.80, 56 more pads with the same numbers are fingers 8-63 (phase k mod 8), and pad 9
    becomes the full RX strip (40.64 x 1.30, centre 3.75 below the finger centre). As pads they get their own mask
    apertures (no aperture spans two nets) and no paste, and no finger is a dangling track stub. The library seed
    still has the pre-D5 geometry (0.30 x 5.00, RX 5.08 x 1.20 3.8 away), so this instance differs from it."""
    fp = bb.footprints.get("E40")
    if fp is None:
        return
    pads = {p.GetNumber(): p for p in fp.Pads()}
    yc = (EL_FY0 + EL_FY1) / 2
    fh = EL_FY1 - EL_FY0
    for i in range(8):
        set_pad(pads[str(i + 1)], finger_x(i), yc, EL_FW, fh)
    for k in range(8, EL_N):
        src = pads[str(k % 8 + 1)]
        q = pcbnew.PAD(src)
        fp.Add(q)
        set_pad(q, finger_x(k), yc, EL_FW, fh)
        q.SetNet(src.GetNet())
    x0, x1, y0, y1 = EL_RX
    set_pad(pads["9"], (x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0)
    for g in list(fp.GraphicalItems()):
        if g.GetLayer() in (pcbnew.B_CrtYd, pcbnew.F_CrtYd, pcbnew.B_Fab, pcbnew.F_Fab):
            fp.Remove(g)
    rx0, rx1, ry0, ry1, _ = EL_RING
    r = pcbnew.PCB_SHAPE(fp)
    r.SetShape(pcbnew.SHAPE_T_RECT)
    r.SetStart(V(rx0 - 0.25, ry1 + 0.25))
    r.SetEnd(V(rx1 + 0.25, ry0 - 0.25))
    r.SetLayer(pcbnew.B_CrtYd)
    r.SetWidth(MM(0.05))
    fp.Add(r)
    fp.SetLocked(True)


def check_electrode_vias(board):
    """Every finger via must clear the top-side pads of the parts already placed (the module's bottom row and right
    column, SW20, J50) by 0.15 mm; the layout stops otherwise."""
    bad = []
    top = [(fp.GetReference(), p) for fp in board.GetFootprints() if not fp.IsFlipped()
           for p in fp.Pads() if p.IsOnLayer(pcbnew.F_Cu)]
    for k in range(EL_N):
        v = V(*finger_via(k))
        for ref, p in top:
            if p.HitTest(v, MM(0.20 + 0.15)):
                bad.append(f"finger {k} via {finger_via(k)} vs {ref}.{p.GetNumber()}")
    if bad:
        raise SystemExit("electrode vias collide with top pads:\n  " + "\n  ".join(bad))


def draw_electrodes(bb):
    """SPEC §2.2 comb: fingers and RX are E40 pads (place_e40); here the vias, the In2 phase buses, the F.Cu ladder
    stubs, the RX feed via and the GND guards.

    * one 0.40/0.20 via per finger: seeds (k < 8) at y 13.75, the others at their phase's bus row;
    * phase p's In2 bus starts at its seed via, climbs at 45 degrees to el_row(p) and runs under the comb to finger
      56 + p; phase 7 is the lowest bus and phase 0 the highest, so each new seed (one pitch to the right) finds the
      buses of the earlier ones already above it: no crossings, all on In2;
    * F.Cu: seed via down to SEED_RUN_Y(n), left to the ladder column, down into R7n pad 2; R7n pad 1 -> R6n pad 2;
    * RX feed via at x 42 (to R80 on the top);
    * inner guard (0.60) and the closed outer ring (0.40) as GND tracks on B.Cu."""
    b = bb.board
    fps = bb.footprints
    for k in range(EL_N):
        add_via(b, finger_via(k), _elnet(bb, f"CAP_EL_TX{k % 8}"))
    for p in range(8):
        nn = _elnet(bb, f"CAP_EL_TX{p}")
        x0, y0 = finger_via(p)
        yr = el_row(p)
        x1 = x0 + (yr - y0)
        if yr > y0:
            add_track(b, (x0, y0), (x1, yr), pcbnew.In2_Cu, nn, 0.15)
        add_track(b, (x1, yr), (finger_x(56 + p), yr), pcbnew.In2_Cu, nn, 0.15)
        r7, r6 = fps.get(f"R7{p}"), fps.get(f"R6{p}")
        if r7 is not None and r6 is not None:
            p7 = {q.GetNumber(): bxy(q) for q in r7.Pads()}
            p6 = {q.GetNumber(): bxy(q) for q in r6.Pads()}
            yr_ = SEED_RUN_Y(p)
            for a_, c_ in (((x0, y0), (x0, yr_)), ((x0, yr_), (p7["2"][0], yr_)), ((p7["2"][0], yr_), p7["2"])):
                add_track(b, a_, c_, pcbnew.F_Cu, nn, 0.12)
            add_track(b, p7["1"], p6["2"], pcbnew.F_Cu, _elnet(bb, f"CAP_TX{p}_J"), 0.15)
    add_via(b, RX_FEED, _elnet(bb, "CAP_EL_RX"))
    r80 = fps.get("R80")
    if r80 is not None:
        p1 = next(q for q in r80.Pads() if q.GetNumber() == "1")
        assert bxy(p1)[1] > bxy(r80)[1], "R80 pad 1 is not toward the RX feed via"
        add_track(b, bxy(p1), RX_FEED, pcbnew.F_Cu, _elnet(bb, "CAP_EL_RX"), 0.15)
    gnd = bb.net("GND")
    gx0, gx1, gy0, gy1 = EL_GUARD_IN
    rx0, rx1, ry0, ry1, rw = EL_RING
    cx0, cx1 = rx0 + rw / 2, rx1 - rw / 2
    cy0, cy1 = ry0 + rw / 2, ry1 - rw / 2
    for a, c in (((cx0, cy0), (cx1, cy0)), ((cx1, cy0), (cx1, cy1)), ((cx1, cy1), (cx0, cy1)), ((cx0, cy1), (cx0, cy0))):
        add_track(b, a, c, pcbnew.B_Cu, gnd, rw)
    add_track(b, (cx0, (gy0 + gy1) / 2), (cx1, (gy0 + gy1) / 2), pcbnew.B_Cu, gnd, gy1 - gy0)


# Router-only keep-outs (board mm): written into the Specctra DSN so Freerouting leaves In2 and B.Cu inside the
# electrode ring to the comb, its buses and the In2 GND guard (the GND zone fills there after routing). They are not
# board rule areas: a rule area would flag the comb's own copper.
# In2 under the USB pair's B.Cu run (preroute_usb_pair): a GND strip 0.6 mm wider than the pair on each side, from
# x 15 (east of the module's escape-via field) to x 46.6 (board mm polygon).
USB_REF_POLY = [(15.0, 18.647), (42.82, 18.647), (46.173, 22.0), (46.6, 22.0), (46.6, 24.549), (42.219, 20.168),
                (15.0, 20.168)]
# entries: (layer, (x0, y0, x1, y1)) rectangles or (layer, [(x, y), ...]) polygons
ROUTER_KEEPOUTS = [("In2.Cu", (EL_RING[0], EL_RING[2], EL_RING[1], EL_RING[3])),
                   ("B.Cu", (EL_RING[0], EL_RING[2], EL_RING[1], EL_RING[3])),
                   ("In2.Cu", USB_REF_POLY)]


def keepout_pts(shape):
    """Board-mm polygon of a ROUTER_KEEPOUTS shape."""
    if isinstance(shape, tuple) and len(shape) == 4 and not isinstance(shape[0], tuple):
        x0, y0, x1, y1 = shape
        return rect(x0, y0, x1, y1)
    return list(shape)


def usb_ref_stitch(b, pitch=2.0, clearance=0.16):
    """GND vias just outside the USB pair, inside USB_REF_POLY, so the In2 GND strip under the pair is tied to In1
    (and the outer pours) every ~2 mm along both edges. A candidate must clear every other-net item on every layer."""
    gnd = b.FindNet("GND")
    pair = [t for t in b.GetTracks() if net_short(t.GetNetname()) in USB_PAIR and t.IsLocked()
            and t.Type() != pcbnew.PCB_VIA_T and t.GetLayer() == pcbnew.B_Cu]
    poly = pcbnew.SHAPE_LINE_CHAIN()
    for p in USB_REF_POLY:
        poly.Append(V(*p))
    poly.SetClosed(True)
    items = [t for t in b.GetTracks() if t.GetNetCode() != gnd.GetNetCode()]
    pads = [p for fp in b.GetFootprints() for p in fp.Pads()]
    holes = [t.GetPosition() for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T] + \
            [p.GetPosition() for p in pads if p.GetDrillSize().x > 0]
    r = MM(0.2)
    placed = [t.GetPosition() for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T
              and t.GetNetCode() == gnd.GetNetCode() and poly.PointInside(t.GetPosition())]
    n0 = len(placed)
    for t in pair:
        a, c = t.GetStart(), t.GetEnd()
        L = (c - a).EuclideanNorm()
        if L < MM(0.5):
            continue
        ux, uy = (c.x - a.x) / L, (c.y - a.y) / L
        for side in (-1, 1):
            off = MM(0.07 + clearance + 0.2 + 0.30 + 0.03)  # past the other line of the pair (0.30), 0.03 spare
            n = int(L // MM(0.5))
            for k in range(n + 1):
                pt = pcbnew.VECTOR2I(int(a.x + ux * k * MM(0.5) - side * uy * off),
                                     int(a.y + uy * k * MM(0.5) + side * ux * off))
                if not poly.PointInside(pt) or any((pt - q).EuclideanNorm() < MM(pitch) for q in placed):
                    continue
                if any(it.HitTest(pt, r + MM(clearance)) for it in items):
                    continue
                if any(p.GetNetCode() != gnd.GetNetCode() and p.HitTest(pt, r + MM(clearance)) for p in pads):
                    continue
                if any(p.GetNetCode() == gnd.GetNetCode() and p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD
                       and p.HitTest(pt, r + MM(0.05)) for p in pads):
                    continue
                if any((pt - h).EuclideanNorm() < MM(0.45) for h in holes):
                    continue
                v = pcbnew.PCB_VIA(b)
                v.SetPosition(pt)
                v.SetWidth(MM(0.4))
                v.SetDrill(MM(0.2))
                v.SetNet(gnd)
                v.SetLocked(True)
                b.Add(v)
                placed.append(pt)
                holes.append(pt)
    return len(placed) - n0


def _elnet(bb, short):
    for name, ni in bb.nets.items():
        if net_short(name) == short:
            return ni
    raise KeyError(short)


def guard_stitch(bb, pitch=2.54):
    """GND vias along the guard ring and the inner guard (to In1/In2), only where the top side is free."""
    b = bb.board
    gnd = bb.net("GND")
    rx0, rx1, ry0, ry1, rw = EL_RING
    gx0, gx1, gy0, gy1 = EL_GUARD_IN
    cx0, cx1 = rx0 + rw / 2, rx1 - rw / 2
    pts = []
    x = cx0
    while x <= cx1 + 1e-6:
        pts += [(x, ry0 + rw / 2), (x, (gy0 + gy1) / 2), (x, ry1 - rw / 2)]
        x += pitch
    pts += [(cx0, 14.5), (cx0, 16.4), (cx1, 14.5), (cx1, 16.4)]
    top = [p for fp in b.GetFootprints() for p in fp.Pads() if p.IsOnLayer(pcbnew.F_Cu)]
    others = [t for t in b.GetTracks()]
    placed = 0
    for pt in pts:
        if pt[0] < 16.3 and pt[1] > 13.6:        # under the module: no vias there (its pads, the escape stubs)
            continue
        v = V(*pt)
        if any(p.GetNetname() != "GND" and p.HitTest(v, MM(0.2 + 0.15)) for p in top):
            continue
        if any(p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD and p.HitTest(v, MM(0.25)) for p in top):
            continue
        if any(t.GetNetname() != "GND" and t.HitTest(v, MM(0.2 + 0.12)) for t in others):
            continue
        add_via(b, pt, gnd)
        placed += 1
    return placed


def build_slider(bb, comps, nets):
    b = bb.board
    outline = slider_outline_pts()
    bb.polyline(pcbnew.Edge_Cuts, poly_page(outline), 0.1, closed=True)
    bb.edge_band_keepout(poly_page(outline), inset=0.3)
    ds = b.GetDesignSettings()
    ds.SetBoardThickness(MM(1.0))
    # SPEC antenna keep-out: all layers, no tracks / vias / pads / pours (parts: the module itself only)
    ant = rect(ANT[0] - 1.0, ANT_Y0, ANT[2], ANT[3] + 1.0)
    bb.keepout([pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu], poly_page(ant), tracks=True, vias=True,
               pads=True, pours=True, name="ANTENNA_KEEPOUT_ALL_LAYERS")
    # no pour of any net between the electrodes on B.Cu (the comb + guards are drawn explicitly)
    rx0, rx1, ry0, ry1, _ = EL_RING
    bb.keepout([pcbnew.B_Cu], poly_page(rect(rx0 - 0.05, ry0 - 0.05, rx1 + 0.05, ry1 + 0.05)), tracks=False,
               vias=False, pads=False, pours=True, name="ELECTRODES_NO_POUR")
    # (no track rule area over the electrodes: the closed GND ring keeps other nets out on B.Cu, and the In2 guard
    # copper drawn with the comb keeps them out on In2)
    # In1: solid GND plane (layer type power, so Freerouting keeps signals off it)
    bb.zone("GND", [pcbnew.In1_Cu], poly_page(slider_pour_outline()), priority=0, name="GND_PLANE")
    # fab documentation
    bb.polyline(pcbnew.F_Fab, poly_page(rect(*GLASS)), 0.1, closed=True)
    bb.text(pcbnew.F_Fab, "DISPLAY GLASS (on the lid)", *P(33.0, 19.6), 0.8)
    bb.polyline(pcbnew.F_Fab, poly_page(rect(ANT[0], ANT[1], ANT[2], ANT[3])), 0.1, closed=True)
    bb.text(pcbnew.F_Fab, "ANTENNA KEEP-OUT ALL LAYERS", *P(10.5, 33.0), 0.8)
    bb.polyline(pcbnew.B_Fab, poly_page(rect(BOT_WIN[0], 1.9, BOT_WIN[2], 10.1)), 0.1, closed=True)
    bb.text(pcbnew.B_Fab, "TAPE CHANNEL WINDOW", *P(30.5, 1.2), 0.8, mirror=True)
    bb.polyline(pcbnew.B_Fab, poly_page(rect(BODY[0], 0.0, BODY[2], 20.0)), 0.1, closed=True)
    bb.text(pcbnew.B_Fab, "BEAM BAND y 0-20: FLATNESS 0.03 mm", *P(31.0, 19.2), 0.8, mirror=True)
    # silk
    bb.text(pcbnew.F_SilkS, "PrettyCool Caliper slider rA", *P(9.0, 2.6), 0.8)
    bb.text(pcbnew.B_SilkS, "BAT+ J2", *P(24.5, 33.0), 0.8, mirror=True)
    bb.text(pcbnew.F_SilkS, "ZERO", *P(31.0, 33.3), 0.8)
    bb.text(pcbnew.F_SilkS, "HOLD", *P(38.5, 33.3), 0.8)
    bb.text(pcbnew.F_SilkS, "MODE", *P(46.0, 33.3), 0.8)


def slider_pour_outline():
    """Body + tabs, 0.3 mm inside the edge."""
    (x0, y0, x1, y1) = BODY
    (lt, rt) = TABS
    m = 0.3
    c = [(x0 + m, y0 + m), (x1 - m, y0 + m), (x1 - m, rt[1] + m), (rt[2] - m, rt[1] + m), (rt[2] - m, rt[3] - m),
         (x1 - m, rt[3] - m), (x1 - m, y1 - m), (x0 + m, y1 - m), (x0 + m, lt[3] - m), (lt[0] + m, lt[3] - m),
         (lt[0] + m, lt[1] + m), (x0 + m, lt[1] + m)]
    r = [0.7, 0.7, 0.8, 0.7, 0.7, 0.8, 0.7, 0.7, 0.8, 0.7, 0.7, 0.8]
    return rounded_outline(c, r)


def pours_slider(bb):
    """Outer and In2 pours (added after routing): GND on F.Cu and B.Cu; In2 = GND guard under the electrodes (and the
    AS5311 / RX front-end band), +3V3 everywhere else."""
    out = poly_page(slider_pour_outline())
    bb.zone("GND", [pcbnew.F_Cu], out, priority=0, clearance=0.25, name="GND_TOP")
    bb.zone("GND", [pcbnew.B_Cu], out, priority=0, clearance=0.25, name="GND_BOT")
    bb.zone("+3V3", [pcbnew.In2_Cu], out, priority=0, clearance=0.25, name="P3V3_IN2")
    rx0, rx1, ry0, ry1, _ = EL_RING
    bb.zone("GND", [pcbnew.In2_Cu], poly_page(rect(rx0, ry0, rx1, ry1)), priority=2, clearance=0.2,
            name="GND_GUARD_IN2")
    # reference plane for the USB pair's B.Cu run (preroute_usb_pair): GND on In2 right under it, tied to In1 by the
    # usb_ref_stitch() vias along both edges
    bb.zone("GND", [pcbnew.In2_Cu], poly_page(USB_REF_POLY), priority=1, clearance=0.2, name="USB_REF_IN2")


def add_fiducial_keepouts(bb):
    for ref in ("FID1", "FID2", "FID3"):
        fp = bb.footprints.get(ref)
        if fp is None:
            continue
        X, Y = TO(fp.GetPosition().x), TO(fp.GetPosition().y)
        bb.keepout([pcbnew.F_Cu], bb.circle_pts(X, Y, 1.35, 24), pads=False, pours=False, name=f"{ref}_KEEPCLEAR")


def place_rest_slider(bb, comps, fixed, placer):
    """Pin-anchored parts, then region parts, then anything left near the part it shares most nets with."""
    fps = bb.footprints
    base_inside = placer.inside
    done = set(fixed)

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

    # region parts that are anchors for others first (the load switches, the gauge)
    for ref in ("U4", "U5", "U6"):
        if ref in fps and ref not in done:
            x, y, box = SLIDER_REGION_PARTS[ref]
            if not with_region(box, lambda: placer.place_near(fps[ref], *P(x, y), "F", max_r=10)):
                print("WARN: could not place", ref)
            done.add(ref)
    for ref, (ic, netname, r) in SLIDER_PIN_ANCHORS.items():
        if ref not in fps or ref in done or ic not in fps:
            continue
        pads = [p for p in fps[ic].Pads() if net_short(p.GetNetname()) == netname]
        if not pads:
            print("WARN: no pad", ic, netname)
            continue
        X, Y = TO(pads[0].GetPosition().x), TO(pads[0].GetPosition().y)
        box = CLUSTER if ic in ("U2", "U3", "U5", "U6") else None
        if ic == "J1":
            box = (48.5, 19.0, 55.2, 30.0)
        if not with_region(box, lambda: placer.place_near(fps[ref], X, Y, "F", max_r=r)):
            if not with_region(box, lambda: placer.place_near(fps[ref], X, Y, "F", max_r=r + 6)):
                print(f"WARN: could not place {ref} near {ic} {netname}")
                continue
            print(f"WARN: {ref} is more than {r} mm from {ic} {netname}")
        done.add(ref)
    for ref, (x, y, box) in SLIDER_REGION_PARTS.items():
        if ref in fps and ref not in done:
            if not with_region(box, lambda: placer.place_near(fps[ref], *P(x, y), "F", max_r=8)):
                if not placer.place_near(fps[ref], *P(x, y), "F", max_r=15):
                    print("WARN: could not place", ref)
            done.add(ref)
    anchors = [fps[r] for r in done if r in fps]
    left = [r for r in fps if r in comps and r not in done]
    for ref in sorted(left, key=refnum):
        fp = fps[ref]
        a = placer.anchor_for(fp, anchors) or fps["U10"]
        tx, ty = placer.target(fp, a)
        if not placer.place_near(fp, tx, ty, "F", max_r=20):
            print("WARN: unplaced", ref)
        print(f"[slider] {ref} placed by net affinity next to {a.GetReference()} at {B(*map(TO, (fp.GetPosition().x, fp.GetPosition().y)))}")
        done.add(ref)


# --------------------------------------------------------------------------- scale board
SCALE_L, SCALE_Y0, SCALE_Y1 = 200.0, 10.5, 17.5
SCALE_CELL0, SCALE_PITCH, SCALE_CELLS = 3.48, 5.08, 38
SCALE_HOLES = ((1.5, 14.0), (198.5, 14.0))
SCALE_FIDS = ((1.5, 11.8), (198.5, 16.2))


def scale_fixed(comps):
    P_ = {}
    for i, (x, y) in enumerate(SCALE_HOLES, 1):
        P_[f"H{i}"] = (x, y, 0.0, "F")
    for i, (x, y) in enumerate(SCALE_FIDS, 1):
        P_[f"FID{i}"] = (x, y, 0.0, "F")
    return {r: v for r, v in P_.items() if r in comps}


def alignment_hole(fp, dia=1.0):
    """SPEC §2.2 (D5): the scale is bonded, no fasteners; the end holes are Ø1.0 non-plated pin-jig holes. The netlist
    still carries the old plated M2 footprint, so the instance is turned into an NPTH: the 8 via pads go, pad 1 becomes
    a Ø1.0 NPTH (no copper, net kept for parity)."""
    pads = list(fp.Pads())
    main = max(pads, key=lambda p: p.GetSizeX())
    for p in pads:
        if p is not main:
            fp.Remove(p)
    main.SetAttribute(pcbnew.PAD_ATTRIB_NPTH)
    main.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
    main.SetDrillSize(pcbnew.VECTOR2I(MM(dia), MM(dia)))
    try:
        main.SetSize(pcbnew.F_Cu, pcbnew.VECTOR2I(MM(dia), MM(dia)))
    except TypeError:
        main.SetSize(pcbnew.VECTOR2I(MM(dia), MM(dia)))
    ls = pcbnew.LSET()
    ls.AddLayer(pcbnew.F_Mask)
    ls.AddLayer(pcbnew.B_Mask)
    for lay in (pcbnew.F_Cu, pcbnew.B_Cu):
        ls.AddLayer(lay)
    main.SetLayerSet(ls)
    for g in list(fp.GraphicalItems()):
        if g.GetLayer() in (pcbnew.F_CrtYd, pcbnew.B_CrtYd, pcbnew.F_SilkS, pcbnew.B_SilkS, pcbnew.F_Fab,
                            pcbnew.B_Fab, pcbnew.Cmts_User):
            fp.Remove(g)
    x, y = bxy(fp)
    c = pcbnew.PCB_SHAPE(fp)
    c.SetShape(pcbnew.SHAPE_T_CIRCLE)
    c.SetCenter(V(x, y))
    c.SetEnd(V(x + 0.75, y))
    c.SetLayer(pcbnew.F_CrtYd)
    c.SetWidth(MM(0.05))
    fp.Add(c)


def scale_post_fixed(bb, comps, fixed):
    for ref in ("H1", "H2"):
        if ref in bb.footprints:
            alignment_hole(bb.footprints[ref])


def build_scale(bb, comps, nets):
    b = bb.board
    out = rect(0.0, SCALE_Y0, SCALE_L, SCALE_Y1)
    bb.polyline(pcbnew.Edge_Cuts, poly_page(out), 0.1, closed=True)
    b.GetDesignSettings().SetBoardThickness(MM(0.8))
    # reflector cells: one isolated "T" per cell, no net (SPEC §2.2 table)
    for n in range(SCALE_CELLS):
        c = SCALE_CELL0 + SCALE_PITCH * n + SCALE_PITCH / 2
        t = [(c - 2.29, 10.85), (c + 2.29, 10.85), (c + 2.29, 12.55), (c + 0.15, 12.55), (c + 0.15, 13.75),
             (c + 1.27, 13.75), (c + 1.27, 17.15), (c - 1.27, 17.15), (c - 1.27, 13.75), (c - 0.15, 13.75),
             (c - 0.15, 12.55), (c - 2.29, 12.55)]
        add_poly(b, pcbnew.F_Cu, t)
    # no solder mask on the electrode face: one aperture over the whole front
    add_poly(b, pcbnew.F_Mask, rect(0.0, SCALE_Y0, SCALE_L, SCALE_Y1))
    bb.text(pcbnew.B_SilkS, "PrettyCool Caliper scale rA  38 x 5.08  bond face", *P(100.0, 14.0), 1.0, mirror=True)
    bb.text(pcbnew.B_SilkS, "-x END", *P(12.0, 14.0), 1.0, mirror=True)


def pours_scale(bb):
    z = bb.zone("GND", [pcbnew.B_Cu], poly_page(rect(0.3, SCALE_Y0 + 0.3, SCALE_L - 0.3, SCALE_Y1 - 0.3)),
                priority=0, clearance=0.3, name="GND_BACK")
    # nothing on GND has copper any more (the holes are NPTH): keep the plane filled anyway
    z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_NEVER)


def scale_inside(X, Y, side):
    x, y = B(X, Y)
    return 0.3 <= x <= SCALE_L - 0.3 and SCALE_Y0 + 0.3 <= y <= SCALE_Y1 - 0.3


# --------------------------------------------------------------------------- board table
BOARDS = {
    "slider": dict(layers=4, fixed=slider_fixed, build=build_slider, post_fixed=slider_post_fixed,
                   pours=pours_slider, inside=slider_inside, keepouts=slider_keepouts, power_track=0.3,
                   # JLC 4-layer: 0.09/0.09 mm min, 0.15 mm min drill; the module LGA and the 0.4 mm DSBGA need fine rules
                   rules=dict(track=0.12, clearance=0.10, via=0.40, via_drill=0.20),
                   power_nets=("VBUS", "VSYS", "VBAT", "VBAT_RAW", "BB_L1", "BB_L2"),
                   # +3V3 reaches ~33 pads and has the In2 +3V3 pour in parallel: 0.20 mm (~0.7 A on 1 oz outer copper,
                   # the module peaks at ~0.36 A) in a class the grid router may rip up and re-route
                   rail_nets=("+3V3",),
                   light_power=("+3V3_SNS", "+3V3_UI", "LCD_LEDA", "LCD_LEDK"),
                   gnd_fanout=True, route=True, edge=0.25, stitch_pitch=2.5),
    "scale": dict(layers=2, fixed=scale_fixed, build=build_scale, post_fixed=scale_post_fixed,
                  pours=pours_scale, inside=scale_inside, keepouts=lambda: [], power_track=0.3,
                  rules=dict(track=0.2, clearance=0.2, via=0.6, via_drill=0.3), power_nets=(), light_power=(),
                  gnd_fanout=False, route=False, edge=0.3),
}


def project_dir(board):
    return os.path.join(KICAD_DIR, board)


def project_name(board):
    return f"prettycool-caliper-{board}"


def pcb_path(board):
    return os.path.join(project_dir(board), project_name(board) + ".kicad_pcb")


def generate(board, pours=True):
    cfg = BOARDS[board]
    pdir = project_dir(board)
    netpath = os.path.join(pdir, project_name(board) + ".net")
    comps, nets = pcbgen.load_netlist(netpath)
    libdir = os.path.join(pdir, "lib", LIB + ".pretty")
    _FP_LIBS[LIB] = libdir
    bb = pcbgen.BoardBuilder(cfg["layers"], {LIB: libdir} if os.path.isdir(libdir) else {})
    rules = cfg["rules"]
    bb.rules(edge=cfg["edge"], **rules)
    bb.set_origin(OX, OY)
    allnets = [n for n in nets if not n.startswith("unconnected-")]
    power = [n for n in allnets if net_short(n) in cfg["power_nets"]]
    light = [n for n in allnets if net_short(n) in cfg["light_power"]]
    clr = rules["clearance"]
    if power:
        bb.netclass("Power", power, track=cfg["power_track"], clearance=clr, via=0.5, via_drill=0.25)
    if light:
        bb.netclass("Supply", light, track=0.2, clearance=clr, via=rules["via"], via_drill=rules["via_drill"])
    gnd = [n for n in allnets if net_short(n) == "GND"]
    if gnd:
        bb.netclass("Ground", gnd, track=cfg["power_track"], clearance=clr, via=0.5, via_drill=0.25)
    rail = [n for n in allnets if net_short(n) in cfg.get("rail_nets", ())]
    if rail:
        bb.netclass("Rail3V3", rail, track=0.2, clearance=clr, via=rules["via"], via_drill=rules["via_drill"])
    usb = [n for n in allnets if net_short(n) in ("USB_DP", "USB_DM")]
    if usb:   # 90-ohm differential geometry for the JLC 4-layer 1.0 mm stack (see docs/electronics.md §7)
        bb.netclass("USB", usb, track=USB_W, clearance=USB_S, via=rules["via"], via_drill=rules["via_drill"])
    fixed_b = cfg["fixed"](comps)
    fixed = {r: (*P(x, y), rot, side) for r, (x, y, rot, side) in fixed_b.items()}
    bb.place_from_netlist(comps, nets, fixed, default=(*P(31.0, 40.0), 0.0, "F"))
    cfg["build"](bb, comps, nets)
    cfg["post_fixed"](bb, comps, fixed)
    if board == "slider":
        place_e40(bb)
        check_electrode_vias(bb.board)
        draw_electrodes(bb)
        print(f"[slider] {guard_stitch(bb)} guard stitching vias")
        add_fiducial_keepouts(bb)
        placer = Placer(bb.board, cfg["inside"], cfg["keepouts"](), power_nets=("GND",))
        for ref in fixed:
            if ref in bb.footprints:
                placer.mark(bb.footprints[ref])
        for fp in bb.board.GetFootprints():
            if fp.GetReference().startswith(("H", "FID")):
                placer.mark(fp)
        # the pre-placed vias and the BGA escape room block the placer too
        for t in bb.board.GetTracks():
            if t.Type() == pcbnew.PCB_VIA_T:
                X, Y = TO(t.GetPosition().x), TO(t.GetPosition().y)
                placer.occupied["F"].append(("via", (X - 0.35, Y - 0.35, X + 0.35, Y + 0.35)))
        u2 = bb.footprints.get("U2")
        if u2 is not None:
            X, Y = TO(u2.GetPosition().x), TO(u2.GetPosition().y)
            placer.occupied["F"].append(("U2_esc", (X - 1.6, Y - 1.6, X + 1.6, Y + 1.6)))
        place_rest_slider(bb, comps, fixed, placer)
        for ref, c in comps.items():
            if "BQ25180" in mpn(c):
                preroute_bga_escape(bb, ref)
        preroute_usb(bb)
        preroute_usb_pair(bb)
        print(f"[slider] USB pair: {usb_ref_stitch(bb.board)} GND vias along its In2 reference strip")
        print(f"[slider] module escape: {escape_module(bb)} pads given a via; J50 escape: {escape_j50(bb)}; "
              f"MAG bus: {preroute_mag(bb)} lines")
        power = ("VBAT", "VBUS", "VSYS", "+3V3_SNS", "+3V3_UI")
        right_col = escape_signal_pads(bb, "U10", lambda pd, xy: xy[0] > 14.5 and xy[1] > 15.0, max_dist=2.6)
        others = sum(escape_signal_pads(bb, r, lambda pd, xy: net_short(pd.GetNetname()) not in power)
                     for r in ("U60", "U4"))
        preroute_vbus(bb)
        # U1's VBUS pin sits between the D+/D- pins: give it a via so VBUS need not thread the pair
        others += escape_signal_pads(bb, "U1", lambda pd, xy: pd.GetNumber() == "5")
        print(f"[slider] signal escapes: module right column {right_col}, U60/U4 {others}")
        for ref in fixed:
            if ref in bb.footprints:
                bb.footprints[ref].SetLocked(True)
    if board == "slider":
        # J1's shell silk runs past the right edge (the receptacle overhangs it by 1 mm) and the module's outline
        # silk sits on the left / bottom edge band: clip those lines on the two instances (local override)
        print(f"[{board}] silk: {silk.clip_silk_at_edge(bb.board, ('J1', 'U10'))} J1/U10 outline lines clipped at the edge")
    moved, hidden = silk.place_refs(bb.board)
    print(f"[{board}] silk: {moved} references placed, {hidden} hidden (no room)")
    if pours:
        cfg["pours"](bb)
    out = pcb_path(board)
    bb.save(out)
    set_layer_types(out, cfg["layers"])
    return out


# --------------------------------------------------------------------------- pre-routes
USB_W, USB_S = 0.14, 0.15   # 90-ohm edge-coupled microstrip over In1 on a ~0.1 mm prepreg (docs/electronics.md §7)


def preroute_bga_escape(bb, ref):
    """Locked fan-out for the 2x4, 0.4 mm-pitch DSBGA charger (from dial-me-spinner): signals out of column 1, IN up
    out of row A, SYS and BAT sideways, GND out of row D into a via, so the autorouter starts outside the array."""
    fp = bb.footprints.get(ref)
    if fp is None:
        return
    pads = {p.GetNumber(): p for p in fp.Pads() if p.GetNumber()}
    if not all(k in pads for k in ("A1", "A2", "D1", "D2")):
        return
    Pp = {k: (p.GetPosition().x, p.GetPosition().y) for k, p in pads.items()}
    cx = (Pp["A2"][0] - Pp["A1"][0], Pp["A2"][1] - Pp["A1"][1])
    rx = (Pp["D1"][0] - Pp["A1"][0], Pp["D1"][1] - Pp["A1"][1])
    cl, rl = math.hypot(*cx), math.hypot(*rx)
    col = (cx[0] / cl, cx[1] / cl)
    row = (rx[0] / rl, rx[1] / rl)

    def add(pad, segs, width, via=False):
        x, y = Pp[pad]
        net = pads[pad].GetNet()
        for dc, dr in segs:
            nx = x + MM(dc * col[0] + dr * row[0])
            ny = y + MM(dc * col[1] + dr * row[1])
            t = pcbnew.PCB_TRACK(bb.board)
            t.SetStart(pcbnew.VECTOR2I(int(x), int(y)))
            t.SetEnd(pcbnew.VECTOR2I(int(nx), int(ny)))
            t.SetWidth(MM(width))
            t.SetLayer(pcbnew.F_Cu)
            t.SetNet(net)
            t.SetLocked(True)
            bb.board.Add(t)
            x, y = nx, ny
        if via:
            v = pcbnew.PCB_VIA(bb.board)
            v.SetPosition(pcbnew.VECTOR2I(int(x), int(y)))
            v.SetWidth(MM(0.45))
            v.SetDrill(MM(0.25))
            v.SetNet(net)
            v.SetLocked(True)
            bb.board.Add(v)

    neck = 0.35
    for k in ("A1", "B1", "C1", "D1"):
        add(k, [(-0.8, 0)], 0.12)
    power_routes = {
        "A2": ((0, -neck), [(0, -0.45)], False),
        "B2": ((neck, 0), [(1.05, 0)], False),
        "C2": ((neck, 0), [(0.35, 0), (0.45, 0.45)], False),
        "D2": ((0, neck), [(0, 0.6)], True),
    }
    for k, (first, rest, via) in power_routes.items():
        add(k, [first], 0.12)
        x0, y0 = Pp[k]
        Pp[k + "_n"] = (x0 + MM(first[0] * col[0] + first[1] * row[0]), y0 + MM(first[0] * col[1] + first[1] * row[1]))
        pads[k + "_n"] = pads[k]
        add(k + "_n", rest, 0.2, via)


def escape_module(bb):
    """Locked escape for the module's left column and bottom row (like a BGA fan-out): a short stub inward and a via
    per signal pad, so the routers start from vias they can take down to In2 / B.Cu and the left corridor (x < 9.5)
    instead of walling the pad rows in with F.Cu tracks. The left column sits 0.45 mm from the board edge, so it can
    only escape inward. Bottom-row pads left of the electrodes escape inward to y 15.95 (their nets - I2C, IMU,
    buttons, USB - head up and right), except SNS_PWR_EN, which goes down to the lower band (outward, y 13.45);
    those over the electrode bus fan (x >= 9.2) escape inward, up past it to y 18.6 (outside the In2 guard
    rectangle). The right column gets its escapes from escape_signal_pads()."""
    fp = bb.footprints.get("U10")
    if fp is None:
        return 0
    x0, y0 = bxy(fp)
    n = 0
    for pd in fp.Pads():
        name = net_short(pd.GetNetname())
        if not name or name == "GND" or name.startswith("unconnected"):
            continue
        px, py = bxy(pd)
        lx, ly = px - x0, py - y0
        if lx < -6.5:                                  # left column
            via = (px + 1.15, py)
        elif ly < -9.0 and px < 9.2:                   # bottom row, left of the electrode area
            # down (outward, below the module edge at y 13.95) only for the net that goes to the lower band
            via = (2.6, 13.75) if name == "SNS_PWR_EN" else (px, 15.95)   # 2.6: clear of the MAG bus (x <= 1.33)
        elif ly < -9.0:                                # bottom row over the bus fan
            via = (px, 18.6)
        else:
            continue
        net = pd.GetNet()
        add_track(bb.board, (px, py), via, pcbnew.F_Cu, net, 0.12 if name != "+3V3" else 0.3)
        add_via(bb.board, via, net)
        n += 1
    return n


def escape_j50(bb):
    """J50's contact row faces +x, into the busiest corner of the lower band (SW20, the electrode via field above,
    the backlight driver to the right). Its five LCD signal pads get a stub to the LEFT, under the connector body,
    and a via (staggered at x 22.15 / 21.55), so the routers can reach them on In2 / B.Cu from the left corridor."""
    fp = bb.footprints.get("J50")
    if fp is None:
        return 0
    n = 0
    for pd in fp.Pads():
        name = net_short(pd.GetNetname())
        if name not in ("LCD_MOSI", "LCD_SCK", "LCD_DC", "LCD_RST_N", "LCD_CS_N"):
            continue
        px, py = bxy(pd)
        vx = 22.15 if int(pd.GetNumber()) % 2 else 21.55
        add_track(bb.board, (px, py), (vx, py), pcbnew.F_Cu, pd.GetNet(), 0.12)
        add_via(bb.board, (vx, py), pd.GetNet())
        n += 1
    return n


def preroute_mag(bb):
    """Locked B.Cu bus for five AS5311 lines (MAG_A, MAG_B, MAG_IDX, MAG_CLK, MAG_DO): from the module's left-column
    escape vias (x 2.0) left to a vertical each along the left edge (A leftmost, the topmost source), down, and right
    along one row each to U30 on the bottom: A/B/IDX at y 1.4/1.65/1.9 into the lower pin row from below, CLK/DO at
    y 6.6/6.9 into the upper pin row from between the rows. A source higher on the module gets a vertical further
    left and a lower row, so nothing crosses. CSN, INC and DEC cannot join without a crossing; the routers take them.
    0.10 mm tracks at 0.22 mm pitch (JLC 4-layer minimum is 0.09)."""
    fps = bb.footprints
    if "U10" not in fps or "U30" not in fps:
        return 0
    src = {net_short(p.GetNetname()): bxy(p) for p in fps["U10"].Pads()}
    dst = {net_short(p.GetNetname()): bxy(p) for p in fps["U30"].Pads()}
    plan = [("MAG_A", 0.40, 1.40, "below"), ("MAG_B", 0.62, 1.65, "below"), ("MAG_IDX", 0.84, 1.90, "below"),
            ("MAG_CLK", 1.06, 6.60, "above"), ("MAG_DO", 1.28, 6.90, "above")]
    b = bb.board
    n = 0
    for name, xv, row, side in plan:
        if name not in src or name not in dst:
            continue
        vy = src[name][1]
        via = (src[name][0] + 1.15, vy)             # the escape via escape_module() put beside the pad
        tx, ty = dst[name]                          # both pin rows are entered from below (row < pad)
        net = _elnet(bb, name)
        pts = [via, (xv, vy), (xv, row), (tx, row), (tx, ty)]
        for a_, c_ in zip(pts, pts[1:]):
            add_track(b, a_, c_, pcbnew.B_Cu, net, 0.10)
        n += 1
    return n


def preroute_vbus(bb):
    """Locked 0.30 mm VBUS from J1's lower VBUS pad pair (A4/B9) down the strip between J1's shell tab and R1/C7 to
    the charger's input cap C1, with a branch to the TVS D1. That corner is tight enough (J1's shell tab, the CC
    pull-down, the gauge cap) that the routers kept failing it."""
    fps = bb.footprints
    if not all(r in fps for r in ("J1", "C1", "D1")):
        return
    net = bb.net("VBUS")
    a4 = bxy(next(p for p in fps["J1"].Pads() if p.GetNumber() == "A4"))
    c1 = bxy(next(p for p in fps["C1"].Pads() if net_short(p.GetNetname()) == "VBUS"))
    d1 = bxy(next(p for p in fps["D1"].Pads() if net_short(p.GetNetname()) == "VBUS"))
    x = 54.2                      # clear of J1's A1/B12 GND pads (x >= 54.53) under A4
    b = bb.board
    add_track(b, a4, (x, a4[1]), pcbnew.F_Cu, net, 0.3)
    add_track(b, (x, a4[1]), (x, d1[1]), pcbnew.F_Cu, net, 0.3)
    add_track(b, (x, d1[1]), c1, pcbnew.F_Cu, net, 0.3)
    add_track(b, (x, d1[1]), d1, pcbnew.F_Cu, net, 0.3)


# USB D+/D- from the module's escape vias to U1, as one locked pair (layout review 2026-11-08). The routers had run
# them as two independent tracks, 85 % on B.Cu and up to 4.7 mm apart (D+ above the test-pad rows, D- between them,
# crossing ~25 In2 signals broadside at 0.1 mm). Now they run together, 0.32 mm apart centre to centre (0.14 mm
# tracks, 0.18 mm gap: y 19.568 / 19.247), on B.Cu along y 19.2-19.6 just above the electrode ring, then up a
# 45-degree leg towards U1. D+ (with a stub to TP22) goes on north along x 46.95, climbs to F.Cu at (47.85, 27.45), west of U1 pin 1, and enters pin 1, so the ESD array
# is in the line's path (J1 -> pin 6 -> pin 1 -> module); U1's GND pin 2 keeps a way out between that climb and the
# part: a locked stub to the GND via (48.0, 26.5) (USB_U1_GND). D- runs through TP23 to the via (48.175, 23.097), from
# which the router reaches U1 pin 3. Under the 45-degree leg and the long run, In2 is a GND strip (USB_REF_POLY).
# The first stretch, under the module's escape-via field, is the router's earlier path frozen.
USB_PAIR = {
    "USB_DP": {"B": [(8.7, 15.95), (8.7, 18.938), (10.306, 20.544), (14.416, 20.544), (15.391, 19.568), (42.468, 19.568),
                     (46.95, 24.05), (46.95, 27.0), (47.4, 27.45), (47.85, 27.45)],
               "tp": [(42.82, 19.92), (42.82, 22.6)],
               "F": [(47.85, 27.45), (48.05, 27.25), (49.062, 27.25)],
               "via": (47.85, 27.45)},
    "USB_DM": {"B": [(7.85, 15.95), (8.282, 15.518), (8.944, 15.518), (9.175, 15.749), (9.175, 18.217), (9.088, 18.305),
                     (9.088, 18.75), (9.714, 19.376), (13.228, 19.376), (13.492, 19.64), (14.855, 19.64), (15.248, 19.247),
                     (42.571, 19.247), (45.924, 22.6), (47.9, 22.6), (48.175, 23.097)],
               "tp": [],
               "F": [],
               "via": (48.175, 23.097)},
}


USB_U1_GND = [(49.062, 26.3), (48.0, 26.5)]   # U1 pin 2 (GND) -> its via, between the D+ climb and U1


def preroute_usb_pair(bb):
    """Lay USB_PAIR down as locked copper (0.14 mm, the USB class width) and report any pad it would touch."""
    b = bb.board
    gnd = bb.net("GND")
    add_track(b, USB_U1_GND[0], USB_U1_GND[1], pcbnew.F_Cu, gnd, 0.2)
    add_via(b, USB_U1_GND[1], gnd)
    for name, legs in USB_PAIR.items():
        net = _elnet(bb, name)
        for key, layer in (("B", pcbnew.B_Cu), ("tp", pcbnew.B_Cu), ("F", pcbnew.F_Cu)):
            pts = legs[key]
            for a_, c_ in zip(pts, pts[1:]):
                add_track(b, a_, c_, layer, net, USB_W)
        add_via(b, legs["via"], net)
    bad = []
    for fp in b.GetFootprints():
        for pd in fp.Pads():
            if net_short(pd.GetNetname()) in USB_PAIR:
                continue
            for t in b.GetTracks():
                if net_short(t.GetNetname()) not in USB_PAIR or not t.IsLocked():
                    continue
                layers = (pcbnew.F_Cu, pcbnew.B_Cu) if t.Type() == pcbnew.PCB_VIA_T else (t.GetLayer(),)
                for lay in layers:
                    if pd.IsOnLayer(lay) and pd.GetEffectiveShape(lay).Collide(t.GetEffectiveShape(lay), MM(0.15)):
                        bad.append(f"{fp.GetReference()}.{pd.GetNumber()}")
    if bad:
        print("WARN: the USB pair pre-route touches pads:", sorted(set(bad)))


def escape_signal_pads(bb, ref, select=lambda pad, bxy_: True, max_dist=1.5):
    """A locked stub + via for each selected signal pad of `ref` (pcbgen.fanout_vias: the first spot within 1.5 mm
    that clears every other-net pad, track and via and the rule areas). For parts boxed in by their own passives
    (U60's 2 x 2 mm LGA among its caps and the I2C pull-ups) or by the electrode via field (the module's right
    column), so the routers can leave on In2 / B.Cu. A via the router ends up bypassing is pruned in finish()."""
    fp = bb.footprints.get(ref)
    if fp is None:
        return 0
    done = 0
    for pd in fp.Pads():
        name = net_short(pd.GetNetname())
        if not name or name in ("GND", "+3V3") or name.startswith("unconnected") or not select(pd, bxy(pd)):
            continue
        n, _ = pcbgen.fanout_vias(bb.board, pd.GetNetname(), pads=[pd], via=0.4, drill=0.2, track=0.12,
                                  clearance=0.12, max_dist=max_dist)
        done += n
    return done


def preroute_usb(bb):
    """Locked joins of the interleaved USB-C D+/D- pad pairs (A6/B6, A7/B7), as on dial-me-spinner's base board:
    D+ drops to two vias just behind its pads and is joined on B.Cu; D- is joined on F.Cu by a U behind those vias. The rest of the pair (to the ESD array and on to the module) is routed in the USB class."""
    fp = bb.footprints.get("J1")
    if fp is None:
        return
    pads = {p.GetNumber(): p for p in fp.Pads()}
    a6, a7, b6, b7 = (pads[k] for k in ("A6", "A7", "B6", "B7"))
    org, mid = fp.GetPosition(), a6.GetPosition()
    dx, dy = mid.x - org.x, mid.y - org.y
    rx, ry = b6.GetPosition().x - b7.GetPosition().x, b6.GetPosition().y - b7.GetPosition().y
    rl = math.hypot(rx, ry)
    rx, ry = rx / rl, ry / rl
    dot = dx * rx + dy * ry
    nx, ny = dx - dot * rx, dy - dot * ry
    nl = math.hypot(nx, ny)
    nx, ny = nx / nl, ny / nl

    def off(pad, back):
        p = pad.GetPosition()
        return pcbnew.VECTOR2I(int(p.x + nx * MM(back)), int(p.y + ny * MM(back)))

    def track(a, c, layer, net):
        t = pcbnew.PCB_TRACK(bb.board)
        t.SetStart(a)
        t.SetEnd(c)
        t.SetWidth(MM(0.15))
        t.SetLayer(layer)
        t.SetNet(net)
        t.SetLocked(True)
        bb.board.Add(t)

    def via(at, net):
        v = pcbnew.PCB_VIA(bb.board)
        v.SetPosition(at)
        v.SetWidth(MM(0.40))
        v.SetDrill(MM(0.20))
        v.SetNet(net)
        v.SetLocked(True)
        bb.board.Add(v)

    dp, dm = a6.GetNet(), a7.GetNet()
    back_pad = 0.5 + max(TO(a6.GetSize().y), TO(a6.GetSize().x)) / 2
    for pad in (a6, b6):
        v = off(pad, back_pad + 0.45)
        track(pad.GetPosition(), v, pcbnew.F_Cu, dp)
        via(v, dp)
    track(off(a6, back_pad + 0.45), off(b6, back_pad + 0.45), pcbnew.B_Cu, dp)
    far = back_pad + 1.45
    track(a7.GetPosition(), off(a7, far), pcbnew.F_Cu, dm)
    track(off(a7, far), off(b7, far), pcbnew.F_Cu, dm)
    track(off(b7, far), b7.GetPosition(), pcbnew.F_Cu, dm)


# --------------------------------------------------------------------------- routing flow (dial-me-spinner's)
def thermal_points(b):
    pts = []
    for fp in b.GetFootprints():
        if "BQ25180" in (fp.GetFieldText("MPN") if fp.HasField("MPN") else ""):
            for pad in fp.Pads():
                if pad.GetNumber() == "D2":
                    x, y = TO(pad.GetPosition().x), TO(pad.GetPosition().y)
                    pts += [(x + r * math.cos(math.radians(a)), y + r * math.sin(math.radians(a)))
                            for r in (0.9, 1.2, 1.5, 1.8) for a in range(0, 360, 20)]
    return pts


def enforce_keepouts(path):
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
    """Delete every unlocked via whose ring lands on an SMD/connector pad (the locked electrode vias sit in the E40
    seed fingers on purpose: the finger is the electrode, not a solder land)."""
    b = pcbnew.LoadBoard(path)
    pads = [p for fp in b.GetFootprints() for p in fp.Pads()
            if p.GetAttribute() in (pcbnew.PAD_ATTRIB_SMD, pcbnew.PAD_ATTRIB_CONN)
            and fp.GetReference() != "E40"]
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


def prune_dangling(path, rounds=6):
    removed = 0
    for _ in range(rounds):
        rpt, before = drc(path)
        before = before.get("[unconnected_items]", 0)
        spots = []
        kind = None
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
        b = pcbnew.LoadBoard(path)
        doomed = []
        for kind, x, y, layer, length in spots:
            p = pcbnew.VECTOR2I(MM(x), MM(y))
            for t in b.GetTracks():
                if t in doomed:          # locked escape stubs the router bypassed are dead copper too
                    continue
                # ... but never the locked USB pair: a moment where one end of it is open (mid-route) would otherwise
                # cascade, round by round, through the whole chain (seen in the 2026-11-08 review re-routes)
                if t.IsLocked() and net_short(t.GetNetname()) in USB_PAIR:
                    continue
                if kind == "via_dangling" and t.Type() == pcbnew.PCB_VIA_T and (t.GetStart() - p).EuclideanNorm() < 2000:
                    doomed.append(t)
                elif kind == "track_dangling" and t.Type() == pcbnew.PCB_TRACE_T and \
                        b.GetLayerName(t.GetLayer()) == layer and abs(TO(t.GetLength()) - length) < 0.002 and \
                        min((t.GetStart() - p).EuclideanNorm(), (t.GetEnd() - p).EuclideanNorm()) < 2000:
                    doomed.append(t)
        if not doomed:
            os.remove(backup)
            break
        for t in doomed:
            b.Delete(t)
        pcbnew.SaveBoard(path, b)
        pcbgen.refill(path)
        _, after = drc(path)
        if after.get("[unconnected_items]", 0) > before:
            shutil.copyfile(backup, path)
            os.remove(backup)
            break
        os.remove(backup)
        removed += len(doomed)
    return removed


def finish(board, path):
    b = pcbnew.LoadBoard(path)
    finish_route.anchor_all(b)
    dups, trimmed = pcbgen.dedupe_tracks(b), pcbgen.trim_dangling(b)
    # zero-length segments (left by anchor/trim): KiCad 10 reports one lying near another net's
    # track as tracks_crossing (an error); the copper at that point always belongs to the items that meet there
    zero = [t for t in b.GetTracks() if t.Type() == pcbnew.PCB_TRACE_T and t.GetLength() == 0]
    for t in zero:
        b.Delete(t)
    dups += len(zero)
    pcbnew.SaveBoard(path, b)
    b = pcbgen.refill(path)
    debris = pcbgen.remove_debris(b)
    pcbnew.SaveBoard(path, b)
    b = pcbgen.refill(path)
    if board == "slider":   # more ties for the USB pair's In2 GND strip, now that the routing is known
        print(f"[{board}] USB reference strip: {usb_ref_stitch(b)} more GND vias")
    stitched = pcbgen.stitch_vias(b, "GND", pitch=BOARDS[board].get("stitch_pitch", 3.0), via=0.45, drill=0.2,
                                  priority=thermal_points(b))
    moved, hidden = silk.place_refs(b)
    pcbnew.SaveBoard(path, b)
    pcbgen.refill(path)
    pruned = prune_dangling(path)
    print(f"[{board}] finish: {dups} duplicate tracks, {trimmed} stubs trimmed, {debris + pruned} debris items removed, "
          f"{stitched} GND stitching vias, {moved} references placed, {hidden} hidden")


def add_pours(board, path):
    bb = pcbgen.BoardBuilder.load(path)
    BOARDS[board]["pours"](bb)
    bb.save(path)


def set_layer_types(path, layers):
    if layers != 4:
        return
    with open(path, encoding="utf-8") as f:
        s = f.read()
    s, n = re.subn(r'\((\d+) "In1\.Cu" signal\)', r'(\1 "In1.Cu" power)', s)
    if not n and '"In1.Cu" power' not in s:
        raise RuntimeError("In1.Cu layer entry not found: the GND plane would be routed as a signal layer")
    with open(path, "w", encoding="utf-8") as f:
        f.write(s)


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


def dsn_plane_as_layer_rule(dsn, net="GND", layer="In1.Cu"):
    with open(dsn, encoding="utf-8") as f:
        s = f.read()
    s, n = re.subn(r"(\(layer %s\s*\(type )power\)" % re.escape(layer), r"\1signal)", s)
    if not n:
        return
    while (i := s.find(f"(plane {net} ")) >= 0:
        s = s[:i] + s[_sexpr_end(s, i):]
    others = [m for m in re.findall(r"\(layer (\S+)\s*\(type", s) if m != layer]
    out, pos = [], 0
    for m in re.finditer(r"\(class (\S+)", s):
        start = m.start()
        end = _sexpr_end(s, start)
        block = s[start:end]
        nets = re.findall(r'"[^"]*"|[^\s()]+', block[:block.index("(", 1)])[2:]
        if nets != [net]:
            c = block.index("(circuit") + len("(circuit")
            block = block[:c] + f"\n        (use_layer {' '.join(others)})" + block[c:]
        out += [s[pos:start], block]
        pos = end
    out.append(s[pos:])
    with open(dsn, "w", encoding="utf-8") as f:
        f.write("".join(out))


def dsn_drop_net(dsn, net="GND"):
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
        head, rest = block[:block.index("(", 1)], block[block.index("(", 1):]
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
        d = float(dia.group(1)) if dia else 500.0
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


def dsn_add_keepouts(dsn, pcb, rects):
    """Add (layer, (x0, y0, x1, y1) or [(x, y), ...] board mm) keep-outs to the DSN structure, as polygons. KiCad's
    DSN frame is page µm with y negated (checked: U30 at page (131, 94) mm is written `place U30 131000 -94000`)."""
    if not rects:
        return
    with open(dsn, encoding="utf-8") as f:
        s = f.read()
    assert "(resolution um" in s, "unexpected DSN units"
    sx, ox, oy = 1000.0, 0.0, 0.0                    # DSN x = 1000 * page_x, DSN y = -1000 * page_y
    out = []
    for layer, shape in rects:
        pts = [P(x, y) for x, y in keepout_pts(shape)]
        xy = " ".join(f"{ox + sx * X:.1f} {oy - sx * Y:.1f}" for X, Y in pts + pts[:1])
        out.append(f'    (keepout "" (polygon {layer} 0 {xy}))')
    st = s.find("(structure")
    end = _sexpr_end(s, st)
    s = s[:end - 1] + "\n".join(out) + "\n  )" + s[end:]
    with open(dsn, "w", encoding="utf-8") as f:
        f.write(s)


def route(path, minutes=30, threads=1, optimizer_passes=20, drop_nets=()):
    jar = FREEROUTING
    if not os.path.exists(jar):
        raise SystemExit(f"Freerouting jar not found ({jar}); set FREEROUTING_JAR")
    dsn = path.replace(".kicad_pcb", ".dsn")
    ses = path.replace(".kicad_pcb", ".ses")
    if os.path.exists(ses):
        os.remove(ses)
    pcbgen.export_dsn(path, dsn)
    dsn_plane_as_layer_rule(dsn)
    for n in drop_nets:
        dsn_drop_net(dsn, n)
    dsn_clearance_margin(dsn)
    dsn_add_keepouts(dsn, path, ROUTER_KEEPOUTS)
    with open(path.replace(".kicad_pcb", ".freerouting.log"), "w") as log:
        # Freerouting 2.1 can hang after its job timeout (seen here after an internal NullPointerException in the
        # maze search): give it the budget plus 10 minutes for the optimiser and the write-out, then kill it
        try:
            subprocess.run(["java", "-jar", jar, "-de", dsn, "-do", ses, "-mt", str(threads),
                            f"--router.job_timeout={minutes // 60:02d}:{minutes % 60:02d}:00",
                            f"--router.optimizer.max_passes={optimizer_passes}", "--gui.enabled=false"],
                           timeout=(minutes + 10) * 60, stdout=log, stderr=subprocess.STDOUT)
        except subprocess.TimeoutExpired:
            print("WARN: Freerouting did not finish in time and was killed")
    if not os.path.exists(ses):
        print(f"WARN: Freerouting produced no session file (see {path.replace('.kicad_pcb', '.freerouting.log')})")
        return False
    pcbgen.import_ses(path, ses, path)
    for f in (dsn, ses):
        os.remove(f)
    return True


def gnd_plane_fixup(path):
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
        more, left = pcbgen.fanout_vias(b, "GND", pads=left, via=0.4, drill=0.2, track=0.2, max_dist=3.0)
        done += more
    pcbnew.SaveBoard(path, b)
    pcbgen.refill(path)
    return done, left


def complete_routing(board, out):
    b = pcbnew.LoadBoard(out)
    pours = [z for z in b.Zones() if not z.GetIsRuleArea() and z.GetZoneName() != "GND_PLANE"]
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
    if board == "slider":
        # the grid router does not read the DSN keep-outs: give it a real (temporary) no-track area on In2 and
        # B.Cu over the electrode ring; enforce_keepouts() then clears any unlocked track that got in there
        shim = types.SimpleNamespace(board=b)
        for layer, shape in ROUTER_KEEPOUTS:
            lay = pcbnew.In2_Cu if layer == "In2.Cu" else pcbnew.B_Cu
            pcbgen.BoardBuilder.keepout(shim, [lay], poly_page(keepout_pts(shape)), tracks=True, vias=False,
                                        pads=False, pours=False, name=TEMP_KEEPOUT)
    pcbnew.SaveBoard(out, b)
    gone = enforce_keepouts(out)
    if gone:
        print(f"[{board}] removed {len(gone)} tracks/vias inside keep-outs: {sorted(set(gone))}")
    gone = remove_vias_in_pads(out)
    if gone:
        print(f"[{board}] removed {len(gone)} vias sitting on SMD/connector pads: {gone}")
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


TEMP_KEEPOUT = "ROUTER_ONLY_ELECTRODES"


def report(board, path):
    warn = {}
    rpt, counts = drc(path, warn)
    print(f"[{board}] DRC errors:", counts or "none", "| warnings:", warn or "none", "->", rpt)
    return counts, warn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", choices=sorted(BOARDS))
    ap.add_argument("--route", action="store_true")
    ap.add_argument("--minutes", type=int, default=20)
    ap.add_argument("--attempts", type=int, default=2)
    ap.add_argument("--finish", action="store_true")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--complete", action="store_true")
    ap.add_argument("--place-only", action="store_true", help="place and save without pours (no routing)")
    a = ap.parse_args()
    for board in BOARDS:
        if a.board and board != a.board:
            continue
        cfg = BOARDS[board]
        out = pcb_path(board)
        if a.finish:
            finish(board, out)
            report(board, out)
            continue
        if a.complete:
            for _ in range(3):
                complete_routing(board, out)
                add_pours(board, out)
                finish(board, out)
                _, counts = drc(out)
                if not counts.get("[unconnected_items]", 0):
                    break
            report(board, out)
            continue
        routing = a.route and cfg["route"]
        if not a.resume:
            out = generate(board, pours=not routing and not a.place_only)
            print(f"[{board}] placed ->", out)
        if routing or a.resume:
            drop = ("GND",) if cfg.get("gnd_fanout") else ()
            # the electrode nets are complete before routing (comb, buses, ladder stubs, R80 feed): hand them to the
            # router as obstacles only, or it spends its passes on the 73 E40 pins
            b0 = pcbnew.LoadBoard(out)
            drop += tuple(str(n) for n in b0.GetNetsByName().keys() if "CAP_EL_" in str(n))
            if cfg.get("gnd_fanout") and not a.resume:
                b = pcbnew.LoadBoard(out)
                done, left = pcbgen.fanout_vias(b, "GND")
                pcbnew.SaveBoard(out, b)
                pcbgen.refill(out)
                print(f"[{board}] GND fan-out: {done} pads, {len(left)} without room:",
                      [(p.GetParentFootprint().GetReference(), p.GetNumber()) for p in left])
            left = None
            for attempt in range(a.attempts):
                route(out, a.minutes * (attempt + 1), drop_nets=drop)
                _, counts = drc(out)
                left = counts.get("[unconnected_items]", 0)
                print(f"[{board}] route attempt {attempt + 1}: {left} unconnected")
                if not left:
                    break
            for _ in range(3):   # grid router for what Freerouting left; the clean-up can open a joint: repeat
                if left:
                    complete_routing(board, out)
                add_pours(board, out)
                finish(board, out)
                _, counts = drc(out)
                left = counts.get("[unconnected_items]", 0)
                if not left:
                    break
            print(f"[{board}] routed")
        report(board, out)


if __name__ == "__main__":
    main()
