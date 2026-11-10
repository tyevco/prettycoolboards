#!/usr/bin/env python3
"""Generate the PrettyCool Caliper PCBs (slider + scale) from the KiCad netlists.

usage: python3 caliper/hardware/design/layout.py [--board slider|scale] [--route] [--minutes N] [--attempts N]
                                                 [--finish | --complete | --resume]
       python3 caliper/hardware/design/layout.py --board slider --rework [--rip NET,...] [--minutes N]
                                                 (keep the routing of the unchanged nets, see rework())

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
import json
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

# test pads by proximity (x 22.5 + 2.54 i): sensor and UI in the middle, the rails at the right end next to the charger
# cluster (a VBUS pad at x 22.5 dragged a 0.3 mm trace across the board)
# TP22 (D+) and TP23 (D-) sit at the east end of the lower row, on the two sides of the USB pair's 45-degree leg
# (preroute_usb_pair): D+ taps TP22 with a 2.7 mm stub, D- runs through TP23. None = an empty grid spot.
# 2026-11-09 slim housing: J2 moved to the bottom over x 21.2..27.0, y 21.6..28.2 (its courtyard), where TP20 / TP21
# (y 25.14) and TP30 / TP31 (y 22.6) were: they moved to a third row, y 30.22 (the same 2.54 grid), x 32.66..40.28,
# below the buttons and clear of the mechanics' ledge (y >= 32.6)
TP_ROW1 = [None, None, None, None, "TP50", "TP51", "TP7", "TP4", "TP2", "TP3", "TP1"]
TP_ROW2 = [None, None, "TP32", "TP40", "TP41", "TP42", "TP5", "TP6", "TP22", None, "TP23"]
TP_ROW3 = [None, None, None, None, "TP20", "TP21", "TP30", "TP31"]
TP_ROWS = ((TP_ROW1, 25.14), (TP_ROW2, 22.6), (TP_ROW3, 30.22))
# H1's lid tube (2026-11-09 slim housing): the lid's Ø4.4 tube ends 0.1 mm above the board around H1, in place of the
# old Ø3.8 screw head, so a Ø4.6 circle round H1 stays free of top-side parts (check_h1_tube)
H1_XY, H1_TUBE_D = (18.75, 24.0), 4.6


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
        # 2026-11-09 slim housing (owner decision): J2 on the BOTTOM, hanging into the battery pocket's J2 bay (board
        # x 21.5..27.6, y 22.4..35.1), mating face toward +y (the top edge), signal pads toward -y (pad row y 22.9,
        # pin 1 VBAT_RAW at x 23.6). Body x 22.1..26.1, y 23.2..27.5, 2.95 below the board; the mated plug x 21.9..26.3,
        # y 27.5..32.1. Was (24.5, 30.6) rot 180 on top, mouth over the top edge (plug relief past y 34 in the housing).
        # >= 6.3 mm in plan from the antenna area, >= 0.9 mm from H1's boss
        "J2": (24.1, 24.9, 0.0, "B"),
        # RT1 2.2 left of SPEC's (24.5, 26.5) (over the cell) so the reverse-polarity FET Q1 sits where J2 pin 1 was
        # on top (drain pad 3 up); since J2 went to the bottom, both sit over it (preroute_vbat_raw)
        "RT1": (22.3, 26.75, 0.0, "F"),
        "Q1": (25.1, 25.1, 90.0, "F"),
        # the gauge's VBAT cap between Q1 and U4's VBAT pins 2/3 (x 28.61)
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
        # D1 (TVS) on the VBUS trunk (2026-11-08 phase-4 review: J1's A9/B4 pads reached U2 without passing it):
        # turned 180 so its VBUS pad 1 faces east, where both J1 feeds land on it and the run to C1 / U2 leaves it
        # (preroute_vbus). Below J1's courtyard (y >= 21.16), left of C1
        "D1": (52.7, 19.95, 180.0, "F"),
        # BTN_HOLD_N debounce cap: was left at (53.72, 19.6) by the placer's fallback, now D1's spot
        "C53": (51.3, 23.0, 0.0, "F"),
        # BQ25180 caps fixed where the placer had put them: the VBUS / VBAT / VSYS pre-routes are drawn to these pads
        "C1": (56.8993, 19.1936, 0.0, "F"), "C2": (59.9, 16.6, 90.0, "F"), "C3": (58.2683, 13.8556, 0.0, "F"),
        "R1": (53.4, 23.7, 90.0, "F"), "R2": (53.4, 29.0, 90.0, "F"),
        # U4 (fuel gauge) by the battery connector J2, not in the charger cluster (SPEC lists it there): its CELL/VDD
        # pins sense VBAT at the cell's connector, its I2C / ALRT lines stay short, and the cluster has no room to let
        # them out (the electrode ring blocks In2/B.Cu up to x 52.4)
        "U4": (29.6, 27.2, 0.0, "F"), "U5": (52.2, 4.6, 90.0, "F"), "U6": (53.0, 12.9, 90.0, "F"),
        # U6's own input cap (review 2026-11-08: C5 was 12.5 mm away by copper): under pins 1 (+3V3) / 2 (GND),
        # clear of U6's and U3's courtyards
        "C13": (52.25, 10.3, 0.0, "F"),
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
        # CAP_RX anti-alias RC (3.9k / 100p) at the ADC pin (review 2026-11-08: it sat at U40, 40 mm of track from
        # GPIO1): bottom, under the module, below C23, beside GPIO1's escape via (2.0, 24.25); R85 pad 2 (CAP_RX)
        # and C44 pad 1 (CAP_RX) face the via. 0.2 mm from every other net (the Analog class), 0.5 mm tall
        "R85": (3.3, 24.25, 180.0, "B"), "C44": (3.3, 23.25, 0.0, "B"),
        # FID3 (SPEC 60.5, 32.8) would sit inside J1's courtyard (it reaches y 31.9 over x 54-63): top middle instead
        "FID1": (2.0, 1.5, 0.0, "F"), "FID2": (60.5, 1.2, 0.0, "F"), "FID3": (33.0, 27.6, 0.0, "F"),
        "E40": (SEED_FC[0], SEED_FC[1], 0.0, "B"),
    }
    for i in range(8):                       # the TX ladder: one column per phase under its seed finger
        P_[f"R7{i}"] = (LADDER_X(i), R7_Y, 90.0, "F")
        P_[f"R6{i}"] = (LADDER_X(i), R6_Y, 90.0, "F")
    for row, y in TP_ROWS:
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
    # gate resistor of the battery reverse-polarity P-FET Q1 (fixed over J2, which is on the bottom)
    "R10": ("Q1", "BATFET_G", 2.5),
    # load switches
    # (C8 / C10 are fixed next to U5 in slider_fixed)
    "C9": ("U5", "SNS_CT", 2.5), "R5": ("U5", "SNS_PWR_EN", 3.5),
    "C11": ("U6", "UI_CT", 2.5), "C12": ("U6", "+3V3_UI", 2.5),
    # capacitive front-end around U40
    "C40": ("U40", "CAP_RX_IN", 3.0), "R81": ("U40", "CAP_RX_IN", 3.5),
    "C42": ("U40", "+3V3_SNS", 2.5), "R82": ("U40", "CAP_VDIV", 3.5), "R83": ("U40", "CAP_VDIV", 3.5),
    "C41": ("U40", "CAP_VDIV", 3.5), "R84": ("U40", "CAP_AMP_OUT", 3.5), "C43": ("U40", "CAP_AMP_OUT", 5.0),
    # (R85 / C44 are fixed at the ESP32's GPIO1 in slider_fixed)
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

    def vbus_preroute(X, Y):       # preroute_vbus(): x 54.15 from J1's A4 pad down to D1, x 57.65 from A9
        x, y = B(X, Y)
        return (53.75 <= x <= 54.55 and 19.8 <= y <= 24.4) or (57.2 <= x <= 58.1 and 20.6 <= y <= 28.0)

    def power_preroute(X, Y):      # preroute_vbat() / preroute_vsys(): the F.Cu ends near U2, C2, C3, C4
        x, y = B(X, Y)
        return ((55.3 <= x <= 61.4 and 12.1 <= y <= 13.2) or (60.3 <= x <= 61.4 and 12.1 <= y <= 16.4)
                or (57.5 <= x <= 59.3 and 13.9 <= y <= 16.3))

    return [("F", via_band), ("F", tx_array), ("F", rx_feed), ("F", usb_preroute), ("F", vbus_preroute),
            ("F", power_preroute)]


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
    if "J2" in fps:      # bottom side; a bottom part is mirrored, so pin 1 (VBAT_RAW) is the -x one of the pair
        assert fps["J2"].IsFlipped(), "J2 must be on the bottom (SPEC §2.1)"
        p1, p2 = pad_xy(fps["J2"], "1"), pad_xy(fps["J2"], "2")
        assert abs(p1[1] - 22.9) < 0.01 and p1[0] < p2[0], f"J2 pins at {p1} / {p2}, want the row at y 22.9, pin 1 -x"
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


def check_h1_tube(board):
    """SPEC §2.1: no top-side courtyard inside the Ø4.6 circle round H1 (the lid's Ø4.4 tube ends 0.1 mm above the
    board there). Returns the clearance (mm) from the circle to the nearest top-side courtyard."""
    c, r = V(*H1_XY), MM(H1_TUBE_D / 2)
    best = float("inf")
    for fp in board.GetFootprints():
        if fp.GetReference() == "H1" or fp.IsFlipped():
            continue
        cy = fp.GetCourtyard(pcbnew.F_CrtYd)
        if cy.OutlineCount() == 0:
            continue
        assert not cy.Collide(c, r), f"{fp.GetReference()}'s courtyard enters the Ø{H1_TUBE_D} circle round H1"
        best = min(best, TO(int(math.sqrt(cy.SquaredDistance(c)))) - H1_TUBE_D / 2)
    return best


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
            # past the other line of the pair (centre 0.32 away, USB_W wide), 0.03 spare
            off = MM(USB_W / 2 + clearance + 0.2 + USB_W + USB_GAP + 0.03)
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
    bb.text(pcbnew.B_SilkS, "BAT+ J2", *P(24.1, 20.9), 0.8, mirror=True)   # J2 (bottom) is the cell, pin 1 BAT+
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
    # In2 GND along CAP_LP1's B.Cu and In2 stretches (see CAP_LP1_SHIELD)
    cap_lp1_ref_zone(bb)


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
                   # CAP_RX (GPIO1, ADC) and the long run to its filter's first stage (review 2026-11-08)
                   analog_nets=("CAP_RX", "CAP_LP1"),
                   gnd_fanout=True, route=True, edge=0.25, stitch_pitch=2.5, stackup="slider",
                   # USBLC6-2SC6: I/O1 (pins 1/6) and I/O2 (3/4) are one conductor inside the part. As jumper pad
                   # groups KiCad's connectivity knows it, so no router joins the two pads around the part again
                   # (the 2026-11-08 re-route had added such a bypass on each USB line)
                   jumper_pads={"U1": (("1", "6"), ("3", "4"))}),
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


def netclasses(bb, cfg, allnets):
    """The board's net classes and their net patterns, set on the board and returned as a spec for
    write_project_netclasses(): KiCad 10 keeps them in the project (.kicad_pro), and pcbnew's SaveBoard does not
    write the project of a board built in memory, so the next load would bring back the old classes."""
    rules = cfg["rules"]
    clr = rules["clearance"]
    v, vd = rules["via"], rules["via_drill"]
    pick = lambda names: [n for n in allnets if net_short(n) in names]  # noqa: E731
    spec = [  # name, nets, track, clearance, via, drill, (diff pair width, gap)
        ("Power", pick(cfg["power_nets"]), cfg["power_track"], clr, 0.5, 0.25, None),
        ("Supply", pick(cfg["light_power"]), 0.2, clr, v, vd, None),
        ("Ground", pick(("GND",)), cfg["power_track"], clr, 0.5, 0.25, None),
        ("Rail3V3", pick(cfg.get("rail_nets", ())), 0.2, clr, v, vd, None),
        # 90-ohm differential geometry for the JLC04101H-3313 stack (see USB_W and docs/electronics.md §7.1)
        ("USB", pick(("USB_DP", "USB_DM")), USB_W, USB_S, v, vd, (USB_W, USB_GAP)),
        # the ADC line and its filter: 0.2 mm (2x the default) from every other net (0.3 would not cross the electrode
        # via field), and the GND pour follows it at 0.25
        ("Analog", pick(cfg.get("analog_nets", ())), 0.15, 0.2, v, vd, None),
    ]
    spec = [s_ for s_ in spec if s_[1]]
    bb.board.GetDesignSettings().m_NetSettings.ClearNetclassPatternAssignments()
    for name, nets_, track, c, via, drill, dp in spec:
        bb.netclass(name, nets_, track=track, clearance=c, via=via, via_drill=drill)
        if dp:
            nc = bb.board.GetDesignSettings().m_NetSettings.GetNetClassByName(name)
            nc.SetDiffPairWidth(MM(dp[0]))
            nc.SetDiffPairGap(MM(dp[1]))
    return spec


def write_project_netclasses(pro, spec):
    """Put the net classes of `spec` (netclasses()) into the project file, replacing the classes of those names and
    every net pattern."""
    with open(pro, encoding="utf-8") as f:
        d = json.load(f)
    ns = d.setdefault("net_settings", {})
    classes = ns.setdefault("classes", [])
    base = dict(next((c for c in classes if c.get("name") == "Default"), {}))
    for name, nets_, track, c, via, drill, dp in spec:
        e = next((x for x in classes if x.get("name") == name), None)
        if e is None:
            e = dict(base)
            classes.append(e)
        e.update({"name": name, "track_width": track, "clearance": c, "via_diameter": via, "via_drill": drill})
        if dp:
            e.update({"diff_pair_width": dp[0], "diff_pair_gap": dp[1]})
    ns["netclass_patterns"] = [{"netclass": name, "pattern": n} for name, nets_, *_ in spec for n in sorted(nets_)]
    with open(pro, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2)
        f.write("\n")


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
    nc_spec = netclasses(bb, cfg, allnets)
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
        print(f"[slider] H1 lid tube: nearest top-side courtyard {check_h1_tube(bb.board):.2f} mm outside the "
              f"Ø{H1_TUBE_D} circle")
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
        preroute_vbat(bb)
        preroute_vbat_raw(bb)
        preroute_vsys(bb)
        preroute_cap_rx(bb)
        preroute_cap_lp1(bb)
        print(f"[slider] CAP_LP1 shield: {cap_lp1_shield_keepouts(bb)} rule areas")
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
    write_project_netclasses(out.replace(".kicad_pcb", ".kicad_pro"), nc_spec)
    bb.save(out)
    set_layer_types(out, cfg["layers"])
    if cfg.get("stackup") == "slider":
        set_stackup(out, SLIDER_STACKUP)
    if cfg.get("jumper_pads"):
        set_jumper_pads(out, cfg["jumper_pads"])
    return out


# --------------------------------------------------------------------------- pre-routes
# USB pair: 0.16 mm tracks 0.32 mm apart (0.16 mm gap) = 89 ohm differential as an edge-coupled microstrip over its
# reference plane on JLC04101H-3313's 0.0994 mm 3313 prepreg (er 4.1), 35 um copper, 15 um mask, JLC's 17.8 um etch:
# hwtools sicalc 2D field solve, 2026-11-08 (0.14 / 0.18 gave 96.7 ohm). The pair runs on B.Cu over its In2 GND strip,
# the same structure as F.Cu over In1 in this symmetric stack. The class clearance (0.15) is below the 0.16 gap.
USB_W, USB_S, USB_GAP = 0.16, 0.15, 0.16


# DSBGA ball lands (0.23 NSMD, mask opening r 0.14): track width inside the opening, and where the wider neck starts
BGA_PAD_TRACE_MAX, BGA_NECK_IN = 0.15, 0.27


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
    # (first leg, rest, via, neck width, rest width). IN / SYS / BAT carry the 0.5 A Wi-Fi peaks (review 2026-11-08):
    # 0.25 mm necks (0.16 mm from the neighbouring 0.23 mm balls at 0.4 mm pitch; 0.15 mm inside the ball's mask
    # opening, BGA_PAD_TRACE_MAX) and 0.30 / 0.25 mm beyond. BAT's
    # first outer leg stays 0.25 so it keeps 0.125 mm from SYS's 0.30 run 0.4 mm above it
    power_routes = {
        "A2": ((0, -neck), [(0, -0.45)], False, 0.25, 0.3),
        "B2": ((neck, 0), [(1.05, 0)], False, 0.25, 0.3),
        "C2": ((neck, 0), [(0.35, 0)], False, 0.25, 0.25),
        "D2": ((0, neck), [(0, 0.6)], True, 0.12, 0.2),
    }
    for k, (first, rest, via, w_neck, w_rest) in power_routes.items():
        if w_neck > BGA_PAD_TRACE_MAX:
            # inside the ball's mask opening (r 0.14) the track stays at most 2/3 of the 0.23 pad (TI's DSBGA land
            # rule for NSMD pads: a wider trace widens the wetted land and pulls the joint off-centre; review
            # 2026-11-09: the 0.25 necks were wider than the pad). The wide part starts BGA_NECK_IN out, where its
            # round end stays clear of the opening (0.27 - 0.125 = 0.145 > 0.14)
            f = BGA_NECK_IN / neck
            inner = (first[0] * f, first[1] * f)
            add(k, [inner], BGA_PAD_TRACE_MAX)
            x0, y0 = Pp[k]
            Pp[k + "_i"] = (x0 + MM(inner[0] * col[0] + inner[1] * row[0]), y0 + MM(inner[0] * col[1] + inner[1] * row[1]))
            pads[k + "_i"] = pads[k]
            add(k + "_i", [(first[0] - inner[0], first[1] - inner[1])], w_neck)
        else:
            add(k, [first], w_neck)
        x0, y0 = Pp[k]
        Pp[k + "_n"] = (x0 + MM(first[0] * col[0] + first[1] * row[0]), y0 + MM(first[0] * col[1] + first[1] * row[1]))
        pads[k + "_n"] = pads[k]
        add(k + "_n", rest, w_rest, via)
    # BAT's diagonal toward its via array (preroute_vbat), 0.30
    x, y = Pp["C2_n"]
    Pp["C2_m"] = (x + MM(0.35 * col[0]), y + MM(0.35 * col[1]))
    pads["C2_m"] = pads["C2"]
    add("C2_m", [(0.45, 0.45)], 0.3)


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


def pad_xy(fp, num=None, net=None):
    """Board-mm position of a footprint's pad, by number or by (short) net name."""
    for p in fp.Pads():
        if (num is not None and p.GetNumber() == num) or (net is not None and net_short(p.GetNetname()) == net):
            return bxy(p)
    raise KeyError(f"{fp.GetReference()} has no pad {num or net}")


def add_path(board, pts, layer, net, width):
    for a_, c_ in zip(pts, pts[1:]):
        add_track(board, a_, c_, layer, net, width)


def add_vias(board, pts, net, dia=0.5, drill=0.25):
    for p in pts:
        add_via(board, p, net, dia, drill)


# Copper sheet resistance (mOhm per square) for the resistance budget in the docstrings: 35 um outer (1 oz finished),
# 15.2 um inner (0.5 oz), rho 17.2 nOhm m at 25 C.
RS_OUTER, RS_INNER = 0.49, 1.13


def preroute_vbus(bb):
    """Locked VBUS from J1 through the TVS D1 to C1 and U2 IN (review 2026-11-08: J1's A9/B4 pads reached U2 along
    x 57.5 without passing D1, which hung off the A4/B9 run). D1 sits with its VBUS pad 1 east, and both feeds end on
    that pad: A4/B9 down x 54.15 (0.40 mm: J1's A1/B12 GND pads are at x >= 54.53, R1 at x <= 53.72), A9/B4 east
    under the receptacle, down x 57.65 (0.50 mm: between the shell tab at x <= 57.22 and the peg hole) and west along
    y 21.0 to it. The run on to C1 (0.60) and U2's IN ball (0.50) leaves pad 1 on its own, so no copper path from J1
    to U2 skips the TVS. U1's VBUS pin (ESD reference) and TP1 are left to the routers."""
    fps = bb.footprints
    if not all(r in fps for r in ("J1", "C1", "D1", "U2")):
        return
    net = bb.net("VBUS")
    b = bb.board
    j1 = fps["J1"]
    a4, a9 = pad_xy(j1, "A4"), pad_xy(j1, "A9")
    c1 = pad_xy(fps["C1"], net="VBUS")
    d1 = pad_xy(fps["D1"], net="VBUS")
    d1_gnd = pad_xy(fps["D1"], net="GND")
    assert d1[0] > d1_gnd[0] + 2.0, "D1's VBUS pad must face east (toward J1 / C1)"
    u2_in = pad_xy(fps["U2"], "A2")
    xa, xb, yb = 54.15, 57.65, 21.0
    # A4/B9: the horizontal 0.1 below the pad centre keeps 0.2 mm from USB_CC1's via at (54.2, 24.55)
    add_path(b, [(a4[0], a4[1] - 0.1), (xa, a4[1] - 0.1), (xa, yb), (xa, d1[1] + 0.25)], pcbnew.F_Cu, net, 0.40)
    # A9/B4: east 0.75, 45 degrees down under the shell (clear of the B5 pad and the peg at (56.7, 29.39))
    add_path(b, [a9, (a9[0] + 0.75, a9[1]), (xb, a9[1] - (xb - a9[0] - 0.75)), (xb, yb), (xa + 0.55, yb),
                 (xa + 0.55, d1[1] + 0.25)], pcbnew.F_Cu, net, 0.50)
    # D1 pad 1 -> C1 -> U2 IN (the BGA escape ends 0.8 above the ball)
    add_path(b, [d1, c1], pcbnew.F_Cu, net, 0.60)
    add_path(b, [c1, (u2_in[0], u2_in[1] + 0.8)], pcbnew.F_Cu, net, 0.50)


def preroute_vbat(bb):
    """Locked VBAT trunk Q1 -> U2 BAT / C3 (review 2026-11-08: a 0.30 mm track over F.Cu, B.Cu and 0.5 oz In2 with
    three single-via layer changes, ~0.09 ohm). Q1's source pad and C7 on F.Cu, 3 vias (0.5/0.25) to a 2.0 mm B.Cu
    riser up to a 2.1 mm B.Cu band along the top edge (y 31.5-33.6, under the mechanical ledge: copper under mask
    only), with a 1.3 mm F.Cu strip in parallel over x 28-48.6 (2 x 2 vias at each end), a 1.9 mm B.Cu riser down
    x 58.4 between J1's two shell tabs, 4 vias up beside U2, and F.Cu to C3 and the BAT ball's escape; band and right
    riser doubled on In2. About 15 mOhm from Q1's source pad to the BAT ball (t/rnet-style network estimate,
    docs/electronics.md §7.13). The B.Cu riser above Q1 crosses the signal lines that ran across it; they go round
    on the other layers (rework)."""
    fps = bb.footprints
    if not all(r in fps for r in ("Q1", "U2", "C3", "C7")):
        return
    net = bb.net("VBAT")
    b = bb.board
    q1s = pad_xy(fps["Q1"], net="VBAT")
    c3 = pad_xy(fps["C3"], net="VBAT")
    c7 = pad_xy(fps["C7"], net="VBAT")
    # Q1 end: source pad -> 3 vias -> C7
    qv = [(26.75, 24.75), (27.35, 24.75), (27.95, 24.75)]
    add_path(b, [q1s, (26.45, q1s[1]), qv[0], qv[1], qv[2]], pcbnew.F_Cu, net, 0.6)
    add_path(b, [qv[1], c7], pcbnew.F_Cu, net, 0.4)
    add_vias(b, qv, net)
    add_path(b, [qv[0], qv[2]], pcbnew.B_Cu, net, 0.6)
    # B.Cu: riser, top band, riser down to U2. The band and the right riser have a 0.5 oz In2 copy under them (nothing
    # has to cross them: the band is the board's top edge, the riser runs under J1 between its shell tabs), tied in
    # by every via array on the way
    xq, yt, xr, yr = 27.35, 32.55, 58.4, 16.2
    # the riser: 1.6 mm at x 27.55 (x 26.75..28.35; was 2.0 at 27.35), 0.25 mm clear of J2's +x fitting nail on the
    # bottom since 2026-11-09 (x 25.3..26.5), the right edge where it was
    add_path(b, [(27.55, 25.3), (27.55, yt)], pcbnew.B_Cu, net, 1.6)
    add_path(b, [(xq, 24.75), (xq, 25.3)], pcbnew.B_Cu, net, 0.6)
    for lay in (pcbnew.B_Cu, pcbnew.In2_Cu):
        add_path(b, [(xq, yt), (xr, yt)], lay, net, 2.1)
        add_path(b, [(xr, yt), (xr, yr)], lay, net, 1.9)
    # F.Cu strip in parallel with the top band, between J2's fitting nail and D50
    sv0 = [(28.4, 32.65), (28.4, 33.25), (29.0, 32.65), (29.0, 33.25)]
    sv1 = [(48.0, 32.65), (48.0, 33.25), (48.6, 32.65), (48.6, 33.25)]
    add_path(b, [(28.4, 32.95), (48.6, 32.95)], pcbnew.F_Cu, net, 1.3)
    add_vias(b, sv0 + sv1, net)
    # U2 end: 4 vias between the BAT escape, C2 and C3
    uv = [(58.25, 15.35), (58.85, 15.35), (58.25, 15.95), (58.85, 15.95)]
    add_vias(b, uv, net)
    for lay in (pcbnew.B_Cu, pcbnew.In2_Cu):
        add_path(b, [(xr, yr), (58.55, 15.65)], lay, net, 1.0)
    add_path(b, [(58.55, 15.75), (58.55, 15.35)], pcbnew.F_Cu, net, 0.9)
    add_path(b, [(58.45, 15.35), (c3[0] + 0.41, c3[1] + 0.39)], pcbnew.F_Cu, net, 0.6)
    add_path(b, [(c3[0] + 0.41, c3[1] + 0.39), c3], pcbnew.F_Cu, net, 0.6)


VBAT_RAW_VIA = (23.6, 21.6)


def preroute_vbat_raw(bb):
    """J2 pin 1 -> Q1 drain, 0.60 mm (the pads' width) instead of the 0.30 mm Power class. J2 is on the bottom since
    2026-11-09 with Q1 above it on top: B.Cu from pin 1 (23.6, 22.9) straight down (away from CAP_LP1's In2 stretch,
    which passes 1.1 mm above the pad centre: the stub stays out of its B.Cu shield band) to a via at (23.6, 21.6),
    then F.Cu at 45 degrees and up x 25.1 between Q1's gate and source pads into the drain pad."""
    fps = bb.footprints
    if not all(r in fps for r in ("J2", "Q1")):
        return
    net = bb.net("VBAT_RAW")
    j2, q1d = pad_xy(fps["J2"], net="VBAT_RAW"), pad_xy(fps["Q1"], net="VBAT_RAW")
    v = VBAT_RAW_VIA
    assert abs(j2[0] - v[0]) < 0.01, f"J2 pin 1 at {j2}: the VBAT_RAW via column assumes x {v[0]}"
    add_path(bb.board, [j2, v], pcbnew.B_Cu, net, 0.6)
    add_vias(bb.board, [v], net)
    add_path(bb.board, [v, (q1d[0], v[1] + (q1d[0] - v[0])), q1d], pcbnew.F_Cu, net, 0.6)


def preroute_vsys(bb):
    """Locked VSYS from U2 SYS to C2, then 0.80 mm to C4 and U3 VIN / EN (review 2026-11-08: 0.30 mm throughout).
    SYS's escape (0.30) passes over C2's two pads and drops into pad 1; the trunk leaves pad 1 down the east side,
    runs west along y 12.65 between C3 / C4 and into C4's pad 1, then 0.60 / 0.25 into U3 pin 10 and 0.20 to pin 1."""
    fps = bb.footprints
    if not all(r in fps for r in ("U2", "C2", "C4", "U3")):
        return
    net = bb.net("VSYS")
    b = bb.board
    c2, c4 = pad_xy(fps["C2"], net="VSYS"), pad_xy(fps["C4"], net="VSYS")
    u3_vin, u3_en = pad_xy(fps["U3"], "10"), pad_xy(fps["U3"], "1")
    sys_end = (58.8, 16.6)                                   # preroute_bga_escape's B2 run ends here
    add_path(b, [sys_end, (59.5, 16.6), (c2[0], 16.2), c2], pcbnew.F_Cu, net, 0.3)
    add_path(b, [c2, (60.9, c2[1] - 1.0), (60.9, 13.25), (60.3, 12.65), (56.2, 12.65), c4], pcbnew.F_Cu, net, 0.8)
    add_path(b, [c4, (u3_vin[0], u3_vin[1] + 0.35)], pcbnew.F_Cu, net, 0.6)
    add_path(b, [(u3_vin[0], u3_vin[1] + 0.35), u3_vin], pcbnew.F_Cu, net, 0.25)
    add_path(b, [u3_en, u3_vin], pcbnew.F_Cu, net, 0.2)


def preroute_cap_rx(bb):
    """GPIO1's escape via -> R85 pad 2 -> C44 pad 1 on B.Cu (the anti-alias RC under the module, slider_fixed)."""
    fps = bb.footprints
    if not all(r in fps for r in ("R85", "C44", "U10")):
        return
    net = _elnet(bb, "CAP_RX")
    r85, c44 = pad_xy(fps["R85"], net="CAP_RX"), pad_xy(fps["C44"], net="CAP_RX")
    gpio1 = pad_xy(fps["U10"], net="CAP_RX")
    via = (gpio1[0] + 1.15, gpio1[1])                      # escape_module()'s via
    assert r85[0] < pad_xy(fps["R85"], net="CAP_LP1")[0], "R85's CAP_RX pad must face the escape via (west)"
    add_path(bb.board, [via, r85, c44], pcbnew.B_Cu, net, 0.2)


# CAP_LP1: the long run from the RC's first stage at U40 (R84 / C43) to R85 under the module (review 2026-11-08), pre-
# routed: the grid router, given the Analog class's wider clearance, could not cross the electrode via field and took
# a 120 mm detour. The upper half follows the corridor the routers had found for CAP_RX (B.Cu under the module, an In2
# hop before Q1 instead of the squeeze between Q1's pads, In2 between the In1 GND plane and B.Cu to TP42's column);
# the lower half is F.Cu over the In1 plane, down to U40's filter. The Analog class keeps 0.2 mm from other nets.
CAP_LP1_PATH = [
    # under the module, past the right column's RGB_DIN escape via, over H1's pad, up between R20 / C22 and H1
    ("B", [(4.6, 24.70), (16.0, 26.35), (17.3, 27.0), (18.75, 26.95)]),
    ("via", (18.75, 26.95)),
    ("F", [(18.75, 26.95), (20.6, 26.6)]),
    ("via", (20.6, 26.6)),
    ("In2", [(20.6, 26.6), (27.575, 21.275), (31.0, 21.425), (31.6, 21.7), (35.75, 21.8)]),
    ("via", (35.75, 21.8)),
    ("B", [(35.75, 21.8), (35.2, 22.6)]),                          # TP42
    # down between the USB strip's stitching vias (x 34.75 / 36.75) and R57, west under the guard ring's vias, then
    # across the electrode via field along the channel between two phase staircases (parallel to them, 1.47 mm from
    # either), down between the inner guard's and the ring's stitching vias at x 38.9, to R84 / C43 west of R80
    ("F", [(35.75, 21.8), (35.75, 18.4), (33.9, 18.4), (33.9, 16.75), (38.91, 13.2), (38.91, 8.75), (38.0, 8.75),
           (37.37, 8.1)]),
    ("F", [(38.91, 8.75), (40.6, 8.75), (41.13, 8.2)]),
]


def preroute_cap_lp1(bb):
    fps = bb.footprints
    if not all(r in fps for r in ("R85", "R84", "C43")):
        return
    net = _elnet(bb, "CAP_LP1")
    b = bb.board
    r85, r84, c43 = (pad_xy(fps[r], net="CAP_LP1") for r in ("R85", "R84", "C43"))
    layers = {"F": pcbnew.F_Cu, "B": pcbnew.B_Cu, "In2": pcbnew.In2_Cu}
    for kind, pts in CAP_LP1_PATH:
        if kind == "via":
            add_via(b, pts, net)
        else:
            add_path(b, pts, layers[kind], net, 0.15)
    add_path(b, [r85, CAP_LP1_PATH[0][1][0]], pcbnew.B_Cu, net, 0.15)
    add_path(b, [(37.37, 8.1), r84], pcbnew.F_Cu, net, 0.15)
    add_path(b, [(41.13, 8.2), c43], pcbnew.F_Cu, net, 0.15)


# CAP_LP1 shield (hwtools sicalc xtalk scan with design/xtalk-cap.yaml, 2026-11-09). The two inner-board stretches
# of CAP_LP1 were the victims of every digital line over 1 mV (the CAP_RX budget): BTN_MODE_N 20.4 mV (15 mm on B.Cu
# right over the In2 stretch), BOOT_N 4.4 (In2, beside it), RGB_DIN 3.7 / IMU_INT2 3.2 / I2C_SDA 3.0 (B.Cu, beside the
# B.Cu stretch at the module's right edge), BUZZ_D 1.8 (B.Cu over In2). F.Cu over the solid In1 plane needs nothing;
# B.Cu and In2 are 0.1 mm apart and In2 has no GND plane of its own, so each of the two stretches gets:
#  * its own layer: no other track within CAP_LP1_SHIELD_HALF of the centre line (two rule-area strips, one each
#    side, from CAP_LP1_SHIELD_OWN out), so no same-layer line runs closer than ~0.85 mm edge to edge;
#  * the neighbouring layer (In2 under the B.Cu stretch, B.Cu over the In2 stretch): no track along it in the same
#    band, but with crossing windows (CAP_LP1_WINDOW wide every CAP_LP1_PIECE) so other nets still cross at right
#    angles (a crossing couples over ~0.2 mm, a parallel run over its whole length);
#  * GND copper: an In2 GND zone over both bands (pours_slider: the In2 stretch becomes a stripline with GND beside
#    it, the B.Cu stretch a microstrip over In2 GND) and the B.Cu GND pour, which the rule areas leave free, over the
#    In2 stretch; tied to In1 by GND vias along both edges (cap_lp1_stitch, after routing).
# The ends of a band stop short where CAP_LP1's own copper sits on the guarded layer (the TP42 stub on B.Cu) or where
# other parts' locked copper is (R85 / C44 / C23 at the start of the B.Cu stretch).
CAP_LP1_SHIELD_HALF, CAP_LP1_SHIELD_OWN = 1.0, 0.3
CAP_LP1_WINDOW, CAP_LP1_PIECE = 0.8, 1.6
# (own layer, neighbouring layer, own-strip trims (start, end), neighbour-band trims (start, end)) per stretch, mm of
# path length
CAP_LP1_SHIELD = {"B": ("B.Cu", "In2.Cu", (0.95, 0.0), (0.0, 0.0)),
                  "In2": ("In2.Cu", "B.Cu", (0.0, 0.0), (0.0, 1.3))}


def cap_lp1_runs(board):
    """The B.Cu and In2 stretches of CAP_LP1 as board-mm polylines: {"B": [...], "In2": [...]}."""
    fp = board.FindFootprintByReference("R85")
    runs = {}
    for kind, pts in CAP_LP1_PATH:
        if kind in CAP_LP1_SHIELD and kind not in runs:
            runs[kind] = list(pts)
    if fp is not None:
        runs["B"] = [pad_xy(fp, net="CAP_LP1")] + runs["B"]
    return runs


def _path_len(path):
    return sum(math.hypot(c[0] - a[0], c[1] - a[1]) for a, c in zip(path, path[1:]))


def _path_at(path, s):
    """Point and unit direction at arc length s along a polyline."""
    for a, c in zip(path, path[1:]):
        L = math.hypot(c[0] - a[0], c[1] - a[1])
        if s <= L or c == path[-1]:
            t = min(max(s / L, 0.0), 1.0) if L else 0.0
            return (a[0] + (c[0] - a[0]) * t, a[1] + (c[1] - a[1]) * t), ((c[0] - a[0]) / L, (c[1] - a[1]) / L)
        s -= L
    raise ValueError("empty path")


def _trim_path(path, s0, s1):
    """The part of a polyline from arc length s0 to (length - s1)."""
    L = _path_len(path)
    if s0 <= 0 and s1 <= 0:
        return list(path)
    a, _ = _path_at(path, s0)
    c, _ = _path_at(path, L - s1)
    out, acc = [a], 0.0
    for p, q in zip(path, path[1:]):
        acc += math.hypot(q[0] - p[0], q[1] - p[1])
        if s0 < acc < L - s1:
            out.append(q)
    return out + [c]


def _polyset(pts):
    ps = pcbnew.SHAPE_POLY_SET()
    ps.NewOutline()
    for p in pts:
        v = V(*p)
        ps.Append(v.x, v.y)
    return ps


def _band(path, d, round_ends=False):
    """Board-mm polyline buffered by d (flat ends unless round_ends; round joins) as a SHAPE_POLY_SET (page IU)."""
    out = pcbnew.SHAPE_POLY_SET()
    for a, c in zip(path, path[1:]):
        L = math.hypot(c[0] - a[0], c[1] - a[1])
        if L < 1e-6:
            continue
        nx, ny = -(c[1] - a[1]) / L * d, (c[0] - a[0]) / L * d
        out.BooleanAdd(_polyset([(a[0] + nx, a[1] + ny), (c[0] + nx, c[1] + ny), (c[0] - nx, c[1] - ny),
                                 (a[0] - nx, a[1] - ny)]))
    joints = path[1:-1] + ([path[0], path[-1]] if round_ends else [])
    for x, y in joints:
        out.BooleanAdd(_polyset([(x + d * math.cos(math.radians(k * 15)), y + d * math.sin(math.radians(k * 15)))
                                 for k in range(24)]))
    return out


def _outlines_mm(ps):
    """Page-mm point lists of the outlines of a SHAPE_POLY_SET (no holes expected)."""
    res = []
    for i in range(ps.OutlineCount()):
        assert ps.HoleCount(i) == 0, "CAP_LP1 shield polygon with a hole"
        ch = ps.Outline(i)
        res.append([(TO(ch.CPoint(k).x), TO(ch.CPoint(k).y)) for k in range(ch.PointCount())])
    return res


def _project(path, pt):
    """(arc length, distance) of the point of a polyline nearest to pt."""
    best, acc = (0.0, float("inf")), 0.0
    for a, c in zip(path, path[1:]):
        dx, dy = c[0] - a[0], c[1] - a[1]
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((pt[0] - a[0]) * dx + (pt[1] - a[1]) * dy) / L2))
        d = math.hypot(pt[0] - a[0] - t * dx, pt[1] - a[1] - t * dy)
        if d < best[1]:
            best = (acc + t * math.sqrt(L2), d)
        acc += math.sqrt(L2)
    return best


def _cut_window(ps, path, s, width):
    """Subtract from ps a rectangle across the polyline, `width` long along it, centred at arc length s."""
    (x, y), (ux, uy) = _path_at(path, s)
    hw, hl = width / 2, CAP_LP1_SHIELD_HALF + 0.3
    ps.BooleanSubtract(_polyset([(x + ux * hw - uy * hl, y + uy * hw + ux * hl),
                                 (x - ux * hw - uy * hl, y - uy * hw + ux * hl),
                                 (x - ux * hw + uy * hl, y - uy * hw - ux * hl),
                                 (x + ux * hw + uy * hl, y + uy * hw - ux * hl)]))


def cap_lp1_shield_keepouts(bb):
    """The rule areas of the CAP_LP1 shield (see CAP_LP1_SHIELD). Returns the number of areas."""
    if "R85" not in bb.footprints:
        return 0
    lay = {"B.Cu": pcbnew.B_Cu, "In2.Cu": pcbnew.In2_Cu}
    # the module's right-column escape vias that land in the B.Cu stretch's band get a window on both layers, so
    # their line can leave them at right angles instead of the escape being dead (on the In2 stretch a window let
    # I2C_SDA out of U60's escape via under CAP_AMP_OUT: those escapes stay closed); a pad of another net on a
    # guarded layer (the B.Cu test pads over the In2 stretch) gets a channel out of the band on its far side
    vias = [bxy(t) for t in bb.board.GetTracks() if t.Type() == pcbnew.PCB_VIA_T
            and net_short(t.GetNetname()) not in ("CAP_LP1", "GND")]
    pads = [(p.GetLayerSet(), bxy(p), TO(max(p.GetBoundingBox().GetWidth(), p.GetBoundingBox().GetHeight())))
            for fp in bb.board.GetFootprints() for p in fp.Pads()
            if net_short(p.GetNetname()) not in ("CAP_LP1", "GND", "")]
    n = 0
    for kind, path in cap_lp1_runs(bb.board).items():
        own, nbr, (o0, o1), (n0, n1) = CAP_LP1_SHIELD[kind]
        # own layer: the band minus a round-ended inner band = one strip each side
        p = _trim_path(path, o0, o1)
        strips = _band(p, CAP_LP1_SHIELD_HALF)
        strips.BooleanSubtract(_band(p, CAP_LP1_SHIELD_OWN, round_ends=True))
        # neighbouring layer: the whole band, cut by crossing windows
        q = _trim_path(path, n0, n1)
        band = _band(q, CAP_LP1_SHIELD_HALF)
        L, s = _path_len(q), CAP_LP1_PIECE
        while s < L - CAP_LP1_WINDOW:
            _cut_window(band, q, s + CAP_LP1_WINDOW / 2, CAP_LP1_WINDOW)
            s += CAP_LP1_PIECE + CAP_LP1_WINDOW
        for v in (vias if kind == "B" else []):
            for ps, pp in ((strips, p), (band, q)):
                sv, d = _project(pp, v)
                if d < CAP_LP1_SHIELD_HALF + 0.25 and 0.0 < sv < _path_len(pp):
                    _cut_window(ps, pp, sv, CAP_LP1_WINDOW)
        for ls, xy, size in pads:
            for layer, ps, pp in ((own, strips, p), (nbr, band, q)):
                if not ls.Contains(lay[layer]):
                    continue
                sv, d = _project(pp, xy)
                if not (1e-3 < d < CAP_LP1_SHIELD_HALF + size / 2 and 0.0 < sv < _path_len(pp)):
                    continue
                # a channel from the pad's near edge (or from CAP_LP1_SHIELD_OWN, for a pad over the trace's edge: TP31)
                # straight out of the band, away from CAP_LP1
                (x0, y0), _ = _path_at(pp, sv)
                nx, ny = (xy[0] - x0) / d, (xy[1] - y0) / d
                a, c, hw = max(d - size / 2 - 0.15, CAP_LP1_SHIELD_OWN), CAP_LP1_SHIELD_HALF + 0.5, size / 2 + 0.15
                ps.BooleanSubtract(_polyset([(x0 + nx * a - ny * hw, y0 + ny * a + nx * hw),
                                             (x0 + nx * c - ny * hw, y0 + ny * c + nx * hw),
                                             (x0 + nx * c + ny * hw, y0 + ny * c - nx * hw),
                                             (x0 + nx * a + ny * hw, y0 + ny * a - nx * hw)]))
        for layer, ps, tag in ((own, strips, "SIDE"), (nbr, band, "CROSS")):
            for pts in _outlines_mm(ps):
                bb.keepout([lay[layer]], pts, tracks=True, vias=False, pads=False, pours=False,
                           name=f"CAP_LP1_{tag}_{layer.split('.')[0].upper()}")
                n += 1
    return n


def cap_lp1_ref_zone(bb):
    """In2 GND copper along both shielded stretches of CAP_LP1 (pours_slider)."""
    runs = cap_lp1_runs(bb.board)
    if "B" not in runs or bb.board.FindFootprintByReference("R85") is None:
        return
    ps = _band(runs["B"], CAP_LP1_SHIELD_HALF)
    ps.BooleanAdd(_band(runs["In2"], CAP_LP1_SHIELD_HALF))
    for pts in _outlines_mm(ps):
        bb.zone("GND", [pcbnew.In2_Cu], pts, priority=2, clearance=0.2, name="CAP_LP1_REF_IN2")


def cap_lp1_stitch(b, pitch=1.6, off=0.62, clearance=0.15):
    """GND vias along both edges of CAP_LP1's B.Cu / In2 stretches, inside the shield band, so the In2 GND zone and
    the B.Cu pour there are tied to In1 every ~1.6 mm. A candidate clears every other-net item on every layer."""
    gnd = b.FindNet("GND")
    if gnd is None or b.FindFootprintByReference("R85") is None:
        return 0
    code = gnd.GetNetCode()
    runs = cap_lp1_runs(b)
    items = [t for t in b.GetTracks() if t.GetNetCode() != code]
    pads = [p for fp in b.GetFootprints() for p in fp.Pads()]
    holes = [t.GetPosition() for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T] + \
            [p.GetPosition() for p in pads if p.GetDrillSize().x > 0]
    no_via = [z for z in b.Zones() if z.GetIsRuleArea() and z.GetDoNotAllowVias()]
    plane = next(z for z in b.Zones() if z.GetZoneName() == "GND_PLANE")
    r = MM(0.2)
    band = pcbnew.SHAPE_POLY_SET()
    for path in runs.values():
        band.BooleanAdd(_band(path, CAP_LP1_SHIELD_HALF))
    placed = [t.GetPosition() for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T and t.GetNetCode() == code
              and band.Contains(t.GetPosition())]
    n0 = len(placed)
    for path in runs.values():
        L, s = _path_len(path), 0.0
        while s <= L:
            (x, y), (ux, uy) = _path_at(path, s)
            s += 0.2
            for side in (-1, 1):
                pt = V(x - side * uy * off, y + side * ux * off)
                if any((pt - q).EuclideanNorm() < MM(pitch) for q in placed):
                    continue
                if not plane.Outline().Contains(pt) or any(z.Outline().Collide(pt, r + MM(clearance)) for z in no_via):
                    continue
                if any(it.HitTest(pt, r + max(MM(clearance), it.GetOwnClearance(it.GetLayer()))) for it in items):
                    continue
                if any(p.GetNetCode() != code and p.HitTest(pt, r + MM(clearance)) for p in pads):
                    continue
                if any(p.GetNetCode() == code and p.GetAttribute() in (pcbnew.PAD_ATTRIB_SMD, pcbnew.PAD_ATTRIB_CONN)
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
                     # split at (42.82, 19.92), where TP22's stub joins, so the stub's end meets a segment end
                     (42.82, 19.92), (46.95, 24.05), (46.95, 27.0), (47.4, 27.45), (47.85, 27.45)],
               "tp": [(42.82, 19.92), (42.82, 22.6)],
               "F": [(47.85, 27.45), (48.05, 27.25), (49.062, 27.25)],
               "via": (47.85, 27.45)},
    "USB_DM": {"B": [(7.85, 15.95), (8.282, 15.518), (8.944, 15.518), (9.175, 15.749), (9.175, 18.217), (9.088, 18.305),
                     (9.088, 18.75), (9.714, 19.376), (13.228, 19.376), (13.492, 19.64), (14.855, 19.64), (15.248, 19.247),
                     # 45-degree leg 0.32 mm from D+'s (was 0.30 at 0.14 mm tracks)
                     (42.5995, 19.247), (45.9525, 22.6), (47.9, 22.6), (48.175, 23.097)],
               "tp": [],
               # via -> between R53's pads -> U1 pin 3 (the router's path, now locked)
               "F": [(48.175, 23.097), (48.2, 23.122), (48.2, 24.49), (49.062, 25.35)],
               "via": (48.175, 23.097)},
}
# J1 -> U1, straight past U1's pads (review 2026-11-08: the routers had added a second path on each line around U1,
# D+ on In2 from J1's via (53.58, 27.25) to the climb via, D- from TP23 to U1 pin 4). D+ leaves J1's B6 via on F.Cu
# straight into pin 6; D- leaves the corner of preroute_usb's F.Cu U behind J1's pads into pin 4. Inside U1 pins 6/1
# and 4/3 are one conductor, so each line passes the clamp with no branch.
USB_J1_U1 = {"USB_DP": [(53.58, 27.25), (51.338, 27.25)],
             "USB_DM": [(52.58, 25.75), (52.18, 25.35), (51.338, 25.35)]}


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
        pts = USB_J1_U1.get(name, [])
        for a_, c_ in zip(pts, pts[1:]):
            add_track(b, a_, c_, pcbnew.F_Cu, net, USB_W)
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
        print(f"[{board}] CAP_LP1 shield: {cap_lp1_stitch(b)} GND vias")
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


# The ordered slider stack: JLCPCB JLC04101H-3313 (4 layers, 1.0 mm, 3313 prepreg), the one ORDER-NOTES names.
# Prepreg 3313 (RC 57 %) 0.0994 mm, er 4.1 (JLC's impedance tables; the hwtools run assumed the same); outer copper
# 35 um, inner 15.2 um (JLC's finished 0.5 oz); mask 15 um, er 3.8. JLC publishes the core of this construction only
# inside its order / impedance pages; it is set here so the stack adds up to 1.0 mm (FR-4, er 4.6). Nothing on this
# board depends on the core: every controlled line is an outer layer over its neighbouring plane through the prepreg.
SLIDER_STACKUP = [
    ("F.SilkS", "Top Silk Screen", None, None, None),
    ("F.Paste", "Top Solder Paste", None, None, None),
    ("F.Mask", "Top Solder Mask", 0.015, None, 3.8),
    ("F.Cu", "copper", 0.035, None, None),
    ("dielectric 1", "prepreg", 0.0994, "3313 RC57%", 4.1),
    ("In1.Cu", "copper", 0.0152, None, None),
    ("dielectric 2", "core", 0.6708, "FR4", 4.6),
    ("In2.Cu", "copper", 0.0152, None, None),
    ("dielectric 3", "prepreg", 0.0994, "3313 RC57%", 4.1),
    ("B.Cu", "copper", 0.035, None, None),
    ("B.Mask", "Bottom Solder Mask", 0.015, None, 3.8),
    ("B.Paste", "Bottom Solder Paste", None, None, None),
    ("B.SilkS", "Bottom Silk Screen", None, None, None),
]
SLIDER_STACK_ID = "JLC04101H-3313"


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


def set_stackup(path, items):
    """Write the fab stack-up into the board's (setup) (the board had none, so KiCad, sicalc and pcbroute fell back to
    KiCad's default stack: the USB pair read 125 ohm there). pcbnew keeps it through every later load / save."""
    with open(path, encoding="utf-8") as f:
        s = f.read()
    i = s.find("(setup")
    if i < 0:
        raise RuntimeError("no (setup) in " + path)
    j = s.find("(stackup", i)
    end = _sexpr_end(s, i)
    if 0 <= j < end:                                   # replace an existing one
        s = s[:j].rstrip(" \t") + stackup_sexpr(items).lstrip("\t") + s[_sexpr_end(s, j):]
    else:
        nl = s.index("\n", i)
        s = s[:nl + 1] + stackup_sexpr(items) + "\n" + s[nl + 1:]
    total = sum(t for _, _, t, _, _ in items if t)
    s = re.sub(r"\(general\s*\(thickness [0-9.]+\)", f"(general\n\t\t(thickness {total:g})", s, count=1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(s)
    return total


def set_jumper_pads(path, groups):
    """Give footprint instances jumper pad groups (KiCad 9+: pads joined inside the part), written into the board
    file text (pcbnew's Python API only reads them). pcbnew keeps them through later loads and saves."""
    with open(path, encoding="utf-8") as f:
        s = f.read()
    for ref, grp in groups.items():
        i = s.find(f'(property "Reference" "{ref}"')
        j = s.rfind("(footprint ", 0, i)
        if i < 0 or j < 0:
            continue
        end = _sexpr_end(s, j)
        fp = s[j:end]
        fp = re.sub(r"\s*\(jumper_pad_groups(?:\s*\([^()]*\))*\s*\)", "", fp)
        k = fp.find("(duplicate_pad_numbers_are_jumpers")
        if k < 0:
            k = fp.find("(attr")
        text = "(jumper_pad_groups " + " ".join("(" + " ".join(f'"{p}"' for p in g) + ")" for g in grp) + ")\n\t\t"
        fp = fp[:k] + text + fp[k:]
        s = s[:j] + fp + s[end:]
    with open(path, "w", encoding="utf-8") as f:
        f.write(s)


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


# --------------------------------------------------------------------------- rework: keep the routing, redo some nets
# A fresh route of the whole slider does not reliably close on KiCad 10 (§7.12 of docs/electronics.md: Freerouting ran
# VBUS through the CC2 gap, CHG_INT_N found no way out of the DSBGA). A layout change therefore re-places and re-draws
# the pre-routes from this script (the regeneration), keeps the routed copper of every net it did not change, and
# routes only what is open: `layout.py --board slider --rework [--rip NET,...]`.
def _xy_key(p, q=1000):
    return (round(p.x / q), round(p.y / q))


def _copper_key(t):
    if t.Type() == pcbnew.PCB_VIA_T:
        return ("via", t.GetNetname(), _xy_key(t.GetPosition()), round(t.GetWidth(pcbnew.F_Cu) / 1000),
                round(t.GetDrillValue() / 1000))
    ends = tuple(sorted((_xy_key(t.GetStart()), _xy_key(t.GetEnd()))))
    return ("trk", t.GetNetname(), t.GetLayer(), ends, round(t.GetWidth() / 1000))


def changed_parts(src, new):
    """Refs that are new, or moved / turned / flipped, between two boards; and their nets (short names)."""
    old = {fp.GetReference(): fp for fp in src.GetFootprints()}
    refs, nets = [], set()
    for fp in new.GetFootprints():
        o = old.get(fp.GetReference())
        same = o is not None and (o.GetPosition() - fp.GetPosition()).EuclideanNorm() < 1000 and \
            abs(o.GetOrientationDegrees() - fp.GetOrientationDegrees()) < 0.01 and o.IsFlipped() == fp.IsFlipped()
        if same and all(net_short(p.GetNetname()) == net_short(q.GetNetname())
                        for p, q in zip(sorted(o.Pads(), key=lambda p: p.GetNumber()),
                                        sorted(fp.Pads(), key=lambda p: p.GetNumber()))):
            continue
        refs.append(fp.GetReference())
        nets |= {net_short(p.GetNetname()) for p in fp.Pads() if p.GetNetname()}
        if o is not None:
            nets |= {net_short(p.GetNetname()) for p in o.Pads() if p.GetNetname()}
    return refs, nets


def transplant_routing(out, src, rip):
    """Copy the routed tracks / vias of `src` onto the freshly generated board `out`, except those of the nets in
    `rip` (short names) and the locked signal copper the generator no longer draws (a changed pre-route). Locked GND
    copper (fan-outs, stitching) is kept. Returns the UUIDs of the copied items."""
    b, o = pcbnew.LoadBoard(out), pcbnew.LoadBoard(src)
    # the finished board pruned the escape stubs / vias its routing did not use (prune_dangling), and the routers
    # used that room: on an unchanged net the old board's copper is the reference, so drop the regenerated locked
    # copper it does not have
    old_keys = {_copper_key(t) for t in o.GetTracks()}
    pruned = 0
    for t in list(b.GetTracks()):
        n = net_short(t.GetNetname())
        if t.IsLocked() and n not in rip and n != "GND" and _copper_key(t) not in old_keys:
            b.Delete(t)
            pruned += 1
    have = {_copper_key(t) for t in b.GetTracks()}
    new_vias = [t.GetPosition() for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T]
    added, skipped, stale = [], 0, 0
    for t in o.GetTracks():
        name = t.GetNetname()
        if net_short(name) in rip or name.startswith("unconnected-") or not name:
            skipped += 1
            continue
        if _copper_key(t) in have:
            continue
        # locked copper of an unchanged net that the generator no longer draws: an old pre-route, or router copper
        # that stayed locked; copied unlocked, so the clean-up removes it if nothing uses it
        relock = t.IsLocked() and net_short(name) == "GND"
        if t.Type() == pcbnew.PCB_VIA_T and any((t.GetPosition() - v).EuclideanNorm() < MM(0.1) for v in new_vias):
            stale += 1
            continue
        net = b.FindNet(name)
        if net is None:
            skipped += 1
            continue
        if t.Type() == pcbnew.PCB_VIA_T:
            n = pcbnew.PCB_VIA(b)
            n.SetPosition(t.GetPosition())
            n.SetWidth(t.GetWidth(pcbnew.F_Cu))
            n.SetDrill(t.GetDrillValue())
        elif t.Type() == pcbnew.PCB_ARC_T:
            n = pcbnew.PCB_ARC(b)
            n.SetStart(t.GetStart())
            n.SetMid(t.GetMid())
            n.SetEnd(t.GetEnd())
            n.SetWidth(t.GetWidth())
            n.SetLayer(t.GetLayer())
        else:
            n = pcbnew.PCB_TRACK(b)
            n.SetStart(t.GetStart())
            n.SetEnd(t.GetEnd())
            n.SetWidth(t.GetWidth())
            n.SetLayer(t.GetLayer())
        n.SetNet(net)
        n.SetLocked(relock)
        b.Add(n)
        added.append(n.m_Uuid.AsString())
    pcbnew.SaveBoard(out, b)
    print(f"[rework] copied {len(added)} routed items, {skipped} on re-done nets, {stale} old vias on a new one; "
          f"{pruned} regenerated escape items the old board had pruned left out")
    return set(added)


def transplant_step(board, src, rip_extra, res):
    """Child process of rework(): which parts changed, which nets to re-do, copy the rest of the routing."""
    out = pcb_path(board)
    b, o = pcbnew.LoadBoard(out), pcbnew.LoadBoard(src)
    refs, nets = changed_parts(o, b)
    big = {net_short(n.GetNetname()) for n in b.GetNetsByName().values()
           if sum(1 for fp in b.GetFootprints() for p in fp.Pads() if p.GetNetCode() == n.GetNetCode()) > 10}
    rip = (nets - big - {"GND", ""}) | set(rip_extra)
    print(f"[rework] parts new / moved: {', '.join(sorted(refs, key=refnum)) or 'none'}")
    print(f"[rework] nets re-done: {', '.join(sorted(rip))}")
    del b, o
    kept = transplant_routing(out, src, rip)
    pcbgen.unique_uuids(out)
    b = pcbnew.LoadBoard(out)
    ids = {t.m_Uuid.AsString() for t in b.GetTracks()}
    gone = geometric_conflicts(b, kept & ids)
    pcbnew.SaveBoard(out, b)
    ids -= gone
    print(f"[rework] removed {len(gone)} old items overlapping the new placement / pre-routes")
    with open(res, "w", encoding="utf-8") as f:
        json.dump({"refs": refs, "rip": sorted(rip), "kept": sorted(kept & ids)}, f)


def geometric_conflicts(b, kept):
    """Delete the copied items whose copper comes closer than the clearance to a new (regenerated) item of another
    net: a pad, a pre-route. Bounding boxes first, then pcbnew's shape collision. Returns the deleted UUIDs."""
    tracks = list(b.GetTracks())
    new = [t for t in tracks if t.m_Uuid.AsString() not in kept]
    old = [t for t in tracks if t.m_Uuid.AsString() in kept]
    obst = new + [p for fp in b.GetFootprints() for p in fp.Pads()]
    grow = MM(0.6)

    def box(it):
        r = it.GetBoundingBox()
        return r.GetX(), r.GetY(), r.GetRight(), r.GetBottom()

    ob = [(box(o), o) for o in obst]
    cu = [pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu]
    gone = set()
    for t in old:
        x0, y0, x1, y1 = box(t)
        layers = cu if t.Type() == pcbnew.PCB_VIA_T else [t.GetLayer()]
        hit = False
        for (a0, b0, a1, b1), o in ob:
            if a1 < x0 - grow or a0 > x1 + grow or b1 < y0 - grow or b0 > y1 + grow:
                continue
            if o.GetNetCode() == t.GetNetCode():
                continue
            for lay in layers:
                if not o.IsOnLayer(lay):
                    continue
                # a via / through-hole pad has no copper on an inner layer it does not connect to
                if any(it.Type() in (pcbnew.PCB_VIA_T, pcbnew.PCB_PAD_T) and not it.FlashLayer(lay) for it in (t, o)):
                    continue
                clr = max(t.GetOwnClearance(lay), o.GetOwnClearance(lay))
                if t.GetEffectiveShape(lay).Collide(o.GetEffectiveShape(lay), clr - MM(0.001)):
                    hit = True
                    break
            if hit:
                break
        if hit:
            gone.add(t.m_Uuid.AsString())
            b.Delete(t)
    return gone


def drop_conflicts(out, kept, rounds=20):
    """Delete the copied (old) items that DRC finds in a violation with the new placement / pre-routes, until none is
    left. A violation among new items only is a generator error and stops the rework."""
    for _ in range(rounds):
        bad, _, _ = finish_route.drc_uuids(out)
        hit = bad & kept
        if not hit:
            fresh = bad - kept
            if fresh:
                rpt, counts = drc(out)
                raise SystemExit(f"[rework] DRC errors among the regenerated items ({counts}); see {rpt}")
            return
        b = pcbnew.LoadBoard(out)
        nets = set()
        for t in list(b.GetTracks()):
            if t.m_Uuid.AsString() in hit:
                nets.add(net_short(t.GetNetname()))
                b.Delete(t)
        pcbnew.SaveBoard(out, b)
        kept -= hit
        print(f"[rework] removed {len(hit)} old items in conflict (nets: {', '.join(sorted(nets))})")


def drop_vias_in_new_pads(out, kept, refs, tol=2000):
    """Old (copied) same-net vias that an SMD pad of a new / moved part now covers: DRC allows them, but an open via in
    a pad wicks the solder (pcbgen.fanout_vias never puts one there). Seen 2026-11-09: J2 moved onto the GND fan-out
    vias of R10 and C7, inside its fitting nails. Deletes them with the copied tracks that end on them and returns the
    (ref, pad) pairs those tracks served, to be fanned out again."""
    b = pcbnew.LoadBoard(out)
    smd = (pcbnew.PAD_ATTRIB_SMD, pcbnew.PAD_ATTRIB_CONN)
    newpads = [p for fp in b.GetFootprints() if fp.GetReference() in refs for p in fp.Pads() if p.GetAttribute() in smd]
    tracks = list(b.GetTracks())
    vias = [t for t in tracks if t.Type() == pcbnew.PCB_VIA_T and t.m_Uuid.AsString() in kept
            and any(p.GetNetCode() == t.GetNetCode() and p.HitTest(t.GetPosition(), t.GetWidth(pcbnew.F_Cu) // 2)
                    for p in newpads)]
    if not vias:
        return set()
    doomed, refan = list(vias), set()
    allpads = [p for fp in b.GetFootprints() for p in fp.Pads()]
    for t in tracks:
        if t.Type() != pcbnew.PCB_TRACE_T or t.m_Uuid.AsString() not in kept:
            continue
        for v in vias:
            if t.GetNetCode() != v.GetNetCode():
                continue
            ends = (t.GetStart(), t.GetEnd())
            near = [k for k, e in enumerate(ends) if (e - v.GetPosition()).EuclideanNorm() < tol]
            if not near:
                continue
            doomed.append(t)
            far = ends[1 - near[0]]
            refan |= {(p.GetParentFootprint().GetReference(), p.GetNumber()) for p in allpads
                      if p.GetNetCode() == t.GetNetCode() and p.IsOnLayer(t.GetLayer()) and p.HitTest(far)}
            break
    for t in doomed:
        kept.discard(t.m_Uuid.AsString())
        b.Delete(t)
    pcbnew.SaveBoard(out, b)
    print(f"[rework] removed {len(vias)} old vias inside a new / moved part's pad (and {len(doomed) - len(vias)} "
          f"tracks to them); fanning out again: {sorted(refan)}")
    return refan


def snapshot_locked(path):
    """The locked copper (pre-routes, fan-outs) as plain data, to put back whatever a router changed."""
    b = pcbnew.LoadBoard(path)
    out = []
    for t in b.GetTracks():
        if not t.IsLocked():
            continue
        if t.Type() == pcbnew.PCB_VIA_T:
            out.append(("via", t.GetNetname(), (t.GetPosition().x, t.GetPosition().y), t.GetWidth(pcbnew.F_Cu),
                        t.GetDrillValue()))
        elif t.Type() == pcbnew.PCB_TRACE_T:
            out.append(("trk", t.GetNetname(), (t.GetStart().x, t.GetStart().y), (t.GetEnd().x, t.GetEnd().y),
                        t.GetWidth(), t.GetLayer()))
    return out


def restore_locked(path, snap):
    """Put back locked copper that a router dropped or altered (Freerouting re-writes every wire on import)."""
    b = pcbnew.LoadBoard(path)
    have = {_copper_key(t) for t in b.GetTracks()}
    n = 0
    for item in snap:
        net = b.FindNet(item[1])
        if item[0] == "via":
            t = pcbnew.PCB_VIA(b)
            t.SetPosition(pcbnew.VECTOR2I(*item[2]))
            t.SetWidth(item[3])
            t.SetDrill(item[4])
        else:
            t = pcbnew.PCB_TRACK(b)
            t.SetStart(pcbnew.VECTOR2I(*item[2]))
            t.SetEnd(pcbnew.VECTOR2I(*item[3]))
            t.SetWidth(item[4])
            t.SetLayer(item[5])
        t.SetNet(net)
        if _copper_key(t) in have:
            continue
        t.SetLocked(True)
        b.Add(t)
        n += 1
    pcbnew.SaveBoard(path, b)
    return n


def lock_for_freerouting(path):
    """Lock every unlocked track / via (Freerouting keeps protected wires) and return their keys to unlock later."""
    b = pcbnew.LoadBoard(path)
    keys = set()
    for t in b.GetTracks():
        if not t.IsLocked():
            keys.add(_copper_key(t))
            t.SetLocked(True)
    pcbnew.SaveBoard(path, b)
    return keys


def unlock_after_freerouting(path, keys, snap=None):
    """Unlock what was locked only for Freerouting: the items in `keys`, or (with `snap`, the locked copper from
    before) everything that is not one of the original locked items (Freerouting splits and rewrites wires, so a key
    match alone misses some)."""
    b = pcbnew.LoadBoard(path)
    keep = None
    if snap is not None:
        keep = set()
        for item in snap:
            if item[0] == "via":
                keep.add(("via", item[1], _xy_key(pcbnew.VECTOR2I(*item[2])), round(item[3] / 1000), round(item[4] / 1000)))
            else:
                ends = tuple(sorted((_xy_key(pcbnew.VECTOR2I(*item[2])), _xy_key(pcbnew.VECTOR2I(*item[3])))))
                keep.add(("trk", item[1], item[5], ends, round(item[4] / 1000)))
    n = 0
    for t in b.GetTracks():
        if not t.IsLocked():
            continue
        k = _copper_key(t)
        if (keep is not None and k not in keep) or (keep is None and k in keys):
            t.SetLocked(False)
            n += 1
    pcbnew.SaveBoard(path, b)
    return n


def rework(board, minutes, rip_extra=(), src=None, freerouting=True):
    out = pcb_path(board)
    # the source board is staged next to the project with a copy of its .kicad_pro: pcbnew loads a board's project
    # with it, and a board without one (a copy elsewhere) gets default rules (0.5 mm min via ...), which then leak
    # into the DRC runs of this process
    stage = os.path.join(project_dir(board), project_name(board) + "-rework-src.kicad_pcb")
    if src and os.path.abspath(src) != os.path.abspath(stage):
        shutil.copyfile(src, stage)
    elif not os.path.exists(stage):
        shutil.copyfile(out, stage)
    else:   # an unfinished rework left its source (the board on disk is that run's partial result)
        print(f"[rework] reusing the routing source an unfinished rework left: {stage} (delete it, or pass "
              f"--rework-from, to start from the board on disk)")
    src = stage
    print(f"[rework] routing source: {src}")
    # generate() in a child process: a process that built a board in memory has pcbnew's default project attached
    # to the boards it loads afterwards (default rules and net classes in every DSN / DRC / router run of it)
    subprocess.run([sys.executable, os.path.abspath(__file__), "--board", board, "--place-only"], check=True)
    # (after generate, so both projects carry the same, new rules)
    shutil.copyfile(out.replace(".kicad_pcb", ".kicad_pro"), stage.replace(".kicad_pcb", ".kicad_pro"))
    # the old board is only ever loaded in a child process: pcbnew keeps the projects of every board a process loaded,
    # and the DRC runs below (which save a copy with its project) then picked up the wrong rules
    res = out + ".transplant.json"
    subprocess.run([sys.executable, os.path.abspath(__file__), "--board", board, "--transplant-from", src,
                    "--rip", ",".join(rip_extra), "--transplant-out", res], check=True)
    with open(res, encoding="utf-8") as f:
        t = json.load(f)
    os.remove(res)
    refs, kept = t["refs"], set(t["kept"])
    drop_conflicts(out, kept)
    refan = drop_vias_in_new_pads(out, kept, refs)
    # GND vias for the pads of the new / moved parts (the rest keep their fan-out), and for the pads whose fan-out via
    # a new / moved part's pad now covers
    b = pcbnew.LoadBoard(out)
    pads = [p for fp in b.GetFootprints() for p in fp.Pads()
            if (fp.GetReference() in refs or (fp.GetReference(), p.GetNumber()) in refan)
            and net_short(p.GetNetname()) == "GND" and p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD]
    done, left = pcbgen.fanout_vias(b, "GND", pads=pads)
    pcbnew.SaveBoard(out, b)
    print(f"[rework] GND fan-out: {done} pads, {len(left)} without room")
    drop = ("GND",) + tuple(str(n) for n in b.GetNetsByName().keys() if "CAP_EL_" in str(n))
    _, counts = drc(out)
    print(f"[rework] before routing: {counts.get('[unconnected_items]', 0)} unconnected")
    if freerouting and counts.get("[unconnected_items]", 0):
        snap = snapshot_locked(out)
        keys = lock_for_freerouting(out)
        backup = out + ".pre-freerouting"
        shutil.copyfile(out, backup)
        ok = route(out, minutes, drop_nets=drop)
        n = unlock_after_freerouting(out, keys, snap) if ok else 0
        if ok:
            print(f"[rework] {restore_locked(out, snap)} locked pre-route items put back after Freerouting")
        _, counts = drc(out)
        print(f"[rework] Freerouting: {counts.get('[unconnected_items]', 0)} unconnected; {n} of {len(keys)} items "
              f"unlocked again")
        if not ok or n < len(keys) * 0.95:
            print("[rework] Freerouting did not keep the routing intact: back to the board before it")
            shutil.copyfile(backup, out)
            unlock_after_freerouting(out, keys)
        os.remove(backup)
    left = None
    for _ in range(3):
        _, counts = drc(out)
        left = counts.get("[unconnected_items]", 0)
        if left:
            complete_routing(board, out)
        add_pours(board, out)
        finish(board, out)
        _, counts = drc(out)
        left = counts.get("[unconnected_items]", 0)
        if not left:
            break
    print(f"[rework] {left} unconnected")
    if not left:
        for ext in (".kicad_pcb", ".kicad_pro", ".kicad_prl"):
            if os.path.exists(stage.replace(".kicad_pcb", ext)):
                os.remove(stage.replace(".kicad_pcb", ext))
    return left


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
    ap.add_argument("--rework", action="store_true",
                    help="regenerate placement + pre-routes, keep the routing of every unchanged net, route the rest")
    ap.add_argument("--rip", default="", help="--rework: more nets (short names, comma separated) to re-route")
    ap.add_argument("--rework-from", help="--rework: the routed board to keep the copper of (default: the board on "
                                          "disk, copied to <board>-rework-src.kicad_pcb first; an unfinished rework's "
                                          "copy is reused). A changed pre-route on a net needs that net in --rip: the "
                                          "old board's copper of an unripped net wins")
    ap.add_argument("--no-freerouting", action="store_true", help="--rework: grid router only")
    ap.add_argument("--transplant-from", help=argparse.SUPPRESS)
    ap.add_argument("--transplant-out", help=argparse.SUPPRESS)
    a = ap.parse_args()
    for board in BOARDS:
        if a.board and board != a.board:
            continue
        cfg = BOARDS[board]
        out = pcb_path(board)
        if a.transplant_from:
            transplant_step(board, a.transplant_from, [n for n in a.rip.split(",") if n], a.transplant_out)
            continue
        if a.rework:
            rework(board, a.minutes, [n for n in a.rip.split(",") if n], a.rework_from, not a.no_freerouting)
            report(board, out)
            continue
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
