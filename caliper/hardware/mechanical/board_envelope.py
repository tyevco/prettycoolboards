#!/usr/bin/env python3
"""Slider-board envelope for the clash check -- a placeholder until the layout exists.

Builds the slider PCB (62 x 34 x 1.0, SPEC 2.1) and one box per tall component,
in the slider frame (u = BOARD_U0 + board x, y = board y, z from params).

Source of the parts, in order of preference:
  1. board_parts.json, written by extract_board_parts.py from the routed
     .kicad_pcb (Fab outline x datasheet height, the dial-me-spinner pattern);
  2. otherwise PLACEHOLDER below: the SPEC 2.1 positions where SPEC gives one,
     and an assumption (tagged "assumed") where it does not.

    python3 board_envelope.py      # list the envelope and run the SPEC sanity check

clash_check.py intersects this envelope with the housing parts.
"""
import json
import os

from build123d import Box, Pos

import params as P

HERE = os.path.dirname(os.path.abspath(__file__))
JSON = os.path.join(HERE, "board_parts.json")

# (ref, side, x0, x1, y0, y1, height, note)  board coordinates, height from the board face
PLACEHOLDER = [
    ("U_MCU", "T", P.MINI1["x0"], P.MINI1["x1"], P.MINI1["y0"], P.MINI1["y1"], P.MINI1["h"],
     "ESP32-S3-MINI-1 15.4x20.5x2.4 (+0.15 solder), antenna at y 34 (SPEC); x assumed"),
    ("J_USB", "T", P.USBC["x0"], P.USBC["x1"], P.USBC["y0"], P.USBC["y1"], P.USBC["h"],
     "USB-C top-mount 16p, right edge (SPEC), y 26.5 (DEV-4), 1 mm overhang"),
    ("J_FPC", "T", P.FPC_CONN["x0"], P.FPC_CONN["x1"], P.FPC_CONN["y0"], P.FPC_CONN["y1"], P.FPC_CONN["h"],
     "13p 0.5 mm FPC, under the glass's FPC end; assumed"),
    ("J_BAT", "T", 9.0, 15.0, 20.0, 24.25, 2.95, "JST-SH 2p side entry SM02B-SRSS; assumed (top: no room below)"),
    ("U_AS5311", "B", P.AS_X - P.AS_BODY_X / 2, P.AS_X + P.AS_BODY_X / 2,
     P.AS_Y - P.AS_BODY_Y / 2, P.AS_Y + P.AS_BODY_Y / 2, P.AS_H_MAX, "TSSOP-20 body, A max 1.20"),
    ("U_AS5311_leads", "B", P.AS_X - P.AS_BODY_X / 2, P.AS_X + P.AS_BODY_X / 2,
     P.AS_Y - P.AS_LEAD_Y / 2, P.AS_Y + P.AS_LEAD_Y / 2, 0.45, "gull-wing leads + fillets"),
    ("C_AS1", "B", P.AS_X - 6.0, P.AS_X - 5.0, P.AS_Y - 0.25, P.AS_Y + 0.25, 0.55, "0402 100 nF; assumed"),
    ("C_AS2", "B", P.AS_X + 5.0, P.AS_X + 6.0, P.AS_Y - 0.25, P.AS_Y + 0.25, 0.55, "0402 1 uF; assumed"),
] + [(f"SW_{k}", "T", x - P.BTN_SW[0] / 2, x + P.BTN_SW[0] / 2, y - P.BTN_SW[1] / 2, y + P.BTN_SW[1] / 2,
      P.BTN_SW[2], "3x4x2.5 top tact (SPEC x; y assumed)") for k, (x, y) in P.BUTTONS.items()]

# Electrode zones (copper only, no height) from SPEC 2.1, for the bottom-layer rule
ELECTRODES = [("TX", 11.0, 51.0, 12.5, 17.5), ("RX", 11.0, 51.0, 10.6, 11.8)]


def load_parts():
    """[(ref, side, x0, x1, y0, y1, h, note)] in board coordinates."""
    if os.path.exists(JSON):
        with open(JSON) as f:
            d = json.load(f)
        out = []
        for p in d["slider"]["parts"]:
            x0, x1, y0, y1 = p["aabb"]
            out.append((p["ref"], p["side"], x0, x1, y0, y1, p["h"], p["note"] or p["fp"]))
        return out, "board_parts.json"
    return PLACEHOLDER, "PLACEHOLDER (SPEC 2.1 + assumptions)"


def box(x0, x1, y0, y1, z0, z1):
    return Pos((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2) * Box(x1 - x0, y1 - y0, z1 - z0)


def holes():
    if os.path.exists(JSON):
        with open(JSON) as f:
            return json.load(f)["slider"]["holes"]
    return P.BOARD_HOLES


def board():
    from build123d import Cylinder
    u0 = P.BOARD_U0
    s = box(u0, u0 + P.BOARD_L, 0, P.BOARD_W, P.BOARD_Z0, P.BOARD_Z1)
    for x, y in holes():
        s -= Pos(u0 + x, y, (P.BOARD_Z0 + P.BOARD_Z1) / 2) * Cylinder(P.BOARD_HOLE_D / 2, 2)
    return s


def part_solids():
    """[(ref, solid, side, note)] in the slider frame."""
    parts, _src = load_parts()
    u0 = P.BOARD_U0
    out = []
    for ref, side, x0, x1, y0, y1, h, note in parts:
        if side == "T":
            z0, z1 = P.BOARD_Z1, P.BOARD_Z1 + h
        else:
            z0, z1 = P.BOARD_Z0 - h, P.BOARD_Z0
        out.append((ref, box(u0 + x0, u0 + x1, y0, y1, z0, z1), side, note))
    return out


def parts_solid():
    from build123d import Compound
    return Compound([s for _r, s, _side, _n in part_solids()])


def _overlap(a, b):
    return min(a[1], b[1]) - max(a[0], b[0]) > 1e-6 and min(a[3], b[3]) - max(a[2], b[2]) > 1e-6


def spec_sanity():
    """Board-level checks the housing depends on.  Returns [(status, text)]."""
    parts, src = load_parts()
    res = []
    ch0, ch1 = P.TAPE_YC - P.TAPE_CH_W / 2, P.TAPE_YC + P.TAPE_CH_W / 2
    for ref, side, x0, x1, y0, y1, h, note in parts:
        if side != "B":
            continue
        over_beam = y0 < P.BEAM_W and y1 > 0
        if not over_beam:
            continue
        inside = y0 >= ch0 + 0.3 and y1 <= ch1 - 0.3
        hmax = P.BOTTOM_CHANNEL_MAX_H if inside else P.CAP_GAP - 0.05
        if ref.startswith("U_AS5311") and not ref.endswith("leads"):
            continue        # the AS5311 is the gap item itself; checked in clash_check
        ok = h <= hmax
        res.append(("OK  " if ok else "FAIL",
                    f"bottom part {ref} over the beam: h {h:.2f} <= {hmax:.2f} "
                    f"({'inside the tape channel' if inside else 'outside the channel, under the 0.15 gap'})"))
    # top-side parts that overlap each other in plan (placement conflicts)
    tops = [p for p in parts if p[1] == "T"]
    for i, a in enumerate(tops):
        for b in tops[i + 1:]:
            if _overlap(a[2:6], b[2:6]):
                res.append(("FAIL", f"top parts {a[0]} and {b[0]} overlap in plan (placement)"))
    for x, y in holes():
        if y - P.BOSS_D / 2 < P.CH_Y1 + 0.5:
            res.append(("FAIL", f"mounting hole ({x}, {y}) has no boss room: over the beam / gib"))
        for a in tops:
            if a[2] - 1.0 < x < a[3] + 1.0 and a[4] - 1.0 < y < a[5] + 1.0:
                res.append(("FAIL", f"mounting hole ({x}, {y}) is under top part {a[0]}"))
    return res, src


if __name__ == "__main__":
    parts, src = load_parts()
    print(f"slider-board envelope from {src}")
    for ref, side, x0, x1, y0, y1, h, note in parts:
        print(f"  {ref:<16}{side}  x {x0:6.2f}..{x1:6.2f}  y {y0:6.2f}..{y1:6.2f}  h {h:4.2f}  {note}")
    print("\nSPEC sanity:")
    for st, txt in spec_sanity()[0]:
        print(f"  {st} {txt}")
