#!/usr/bin/env python3
"""Slider-board envelope for the clash check: the routed board, or the SPEC placeholder.

Builds the slider PCB (62 x 34 x 1.0 body + two 6 x 14 end tabs, SPEC 2 / D3) and one
box per component, in the slider frame (u = BOARD_U0 + board x, y = board y, z from params).

Source, in order of preference:
  1. board_parts.json, written by extract_board_parts.py from the routed .kicad_pcb
     (outline, holes, Fab outline x datasheet height per part, standoffs, mated plug), with the
     PENDING board changes applied over it (the housing is designed for them; see PENDING);
  2. otherwise PLACEHOLDER below: the SPEC 2.1 placement table (D4).

    python3 board_envelope.py      # list the envelope and run the board-rule check

clash_check.py intersects this envelope with the housing parts; spec_sanity() checks the
board-level rules the housing depends on (SPEC 2.1 height, bottom-side and antenna rules).
"""
import json
import os

from build123d import Box, Cylinder, Polygon, Pos, extrude

import params as P

HERE = os.path.dirname(os.path.abspath(__file__))
JSON = os.path.join(HERE, "board_parts.json")


def _sw(ref, x, y, note):
    w, d, h = P.BTN_SW
    return (ref, "T", x - w / 2, x + w / 2, y - d / 2, y + d / 2, h, note)


# (ref, side, x0, x1, y0, y1, height, note)  board coordinates, height from the board face
PLACEHOLDER = [
    ("U10", "T", P.MINI1["x0"], P.MINI1["x1"], P.MINI1["y0"], P.MINI1["y1"], P.MINI1["h"],
     "ESP32-S3-MINI-1 15.4x20.5x2.4 (+0.15 solder), top-left corner, antenna flush with the top edge"),
    ("J1", "T", P.USBC["x0"], P.USBC["x1"], P.USBC["y0"], P.USBC["y1"], P.USBC["h"],
     "USB-C HRO TYPE-C-31-M-12, right edge y 26.5, 1 mm overhang"),
    ("J50", "T", P.FPC_CONN["x0"], P.FPC_CONN["x1"], P.FPC_CONN["y0"], P.FPC_CONN["y1"], P.FPC_CONN["h"],
     "FH12-13S 0.5 mm FPC under the glass's -x end"),
    ("J2", "B", *P.J2_BODY, P.J2_H, "JST-SH 2p side entry, BOTTOM side, mouth +y (since 2026-11-09, SPEC 15 L1)"),
    ("J2_plug", "B", *P.J2_PLUG, P.J2_H, "mated plug, in the battery pocket"),
    ("BZ50", "T", 35.5, 44.5, 19.8, 28.8, 1.9, "PKMCS0909E"),
    ("U30", "B", P.AS_X - P.AS_BODY_X / 2, P.AS_X + P.AS_BODY_X / 2,
     P.AS_Y - P.AS_BODY_Y / 2, P.AS_Y + P.AS_BODY_Y / 2, P.AS_H_MAX, "TSSOP-20 body, A max 1.20"),
    ("C30", "B", 24.95, 26.05, 5.75, 6.25, 0.55, "0402 100 nF"),
    ("C31", "B", 35.95, 37.05, 5.75, 6.25, 0.55, "0402 1 uF"),
    _sw("SW50", *P.BUTTONS["ZERO"], "ZERO"), _sw("SW51", *P.BUTTONS["HOLD"], "HOLD"),
    _sw("SW52", *P.BUTTONS["MODE"], "MODE"),
] + [(f"H{i + 2}_standoff", "T", x - 2, x + 2, y - 2, y + 2, P.STANDOFF_H, "SMT M2 standoff")
     for i, (x, y) in enumerate(P.TAB_HOLES)]


def _rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _placeholder_outline():
    """Body + tabs as one polygon (no corner radii)."""
    (lx0, ly0, lx1, ly1), (rx0, ry0, rx1, ry1) = P.BOARD_TABS
    return [(0, 0), (P.BOARD_L, 0), (P.BOARD_L, ry0), (rx1, ry0), (rx1, ry1), (P.BOARD_L, ry1),
            (P.BOARD_L, P.BOARD_W), (0, P.BOARD_W), (0, ly1), (lx0, ly1), (lx0, ly0), (0, ly0)]


def _load():
    if os.path.exists(JSON):
        with open(JSON) as f:
            return json.load(f)
    return None


#: Board changes the housing is designed for but the routed board does not have yet.  While the extracted board still
#: shows the old part, load_parts() substitutes the new envelope and pending() reports it, so the clash check tests the
#: housing against the board as it will be.  Each: ref -> (old side, replacement rows, request), e.g. the 2026-11-09
#: slim-down's J2 move:
#:   "J2": ("T", [("J2", "B", *P.J2_BODY, P.J2_H, "..."), ("J2_plug", "B", *P.J2_PLUG, P.J2_H, "...")], "J2 to the bottom")
#: Empty since the board has that move (SPEC 15 L1, 2026-11-09): J2 and its plug are read from the routed board.
PENDING = {}


def _apply_pending(parts):
    """parts with every PENDING change applied; [(ref, request)] that were applied."""
    applied = []
    for ref, (old_side, rows, req) in PENDING.items():
        cur = [p for p in parts if p[0] == ref]
        if cur and cur[0][1] == old_side:
            parts = [p for p in parts if p[0] not in (ref, ref + "_plug")] + list(rows)
            applied.append((ref, req))
    return parts, applied


def pending():
    """[(ref, request)] of the board changes still pending (substituted in the envelope)."""
    d = _load()
    if not d:
        return []
    raw = [(p["ref"], p["side"]) for p in d["slider"]["parts"]]
    return _apply_pending(raw)[1]


def load_parts():
    """[(ref, side, x0, x1, y0, y1, h, note)] in board coordinates, and the source name.  PENDING board changes are
    applied over the extracted board."""
    d = _load()
    if d:
        out = []
        for p in d["slider"]["parts"]:
            x0, x1, y0, y1 = p["aabb"]
            out.append((p["ref"], p["side"], x0, x1, y0, y1, p["h"], p["note"] or p["fp"]))
        out, applied = _apply_pending(out)
        src = f"board_parts.json ({d['source']})"
        if applied:
            src += " + pending: " + ", ".join(r for r, _q in applied)
        return out, src
    return PLACEHOLDER, "PLACEHOLDER (SPEC 2.1 placement table)"


def outline():
    d = _load()
    if d and d["slider"].get("outline"):
        return [tuple(p) for p in d["slider"]["outline"]]
    return _placeholder_outline()


def holes():
    """[(ref, x, y)]"""
    d = _load()
    if d:
        return [(h["ref"], h["x"], h["y"]) for h in d["slider"]["holes"]]
    return [("H1", *P.H1)] + [(f"H{i + 2}", x, y) for i, (x, y) in enumerate(P.TAB_HOLES)]


def box(x0, x1, y0, y1, z0, z1):
    return Pos((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2) * Box(x1 - x0, y1 - y0, z1 - z0)


def board():
    pts = [(P.BOARD_U0 + x, y) for x, y in outline()]
    area2 = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]))
    if area2 < 0:
        pts = pts[::-1]
    s = Pos(0, 0, P.BOARD_Z0) * extrude(Polygon(*pts, align=None), P.BOARD_T)
    for _ref, x, y in holes():
        s -= Pos(P.BOARD_U0 + x, y, (P.BOARD_Z0 + P.BOARD_Z1) / 2) * Cylinder(P.BOARD_HOLE_D / 2, 2)
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
        if ref.endswith("_standoff") or ref.endswith("_screw"):
            s = Pos(u0 + (x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2) * Cylinder((x1 - x0) / 2, z1 - z0)
        else:
            s = box(u0 + x0, u0 + x1, y0, y1, z0, z1)
        out.append((ref, s, side, note))
    return out


def parts_solid():
    from build123d import Compound
    return Compound([s for _r, s, _side, _n in part_solids()])


def _overlap(a, b, m=0.0):
    return min(a[1], b[1]) - max(a[0], b[0]) > m + 1e-6 and min(a[3], b[3]) - max(a[2], b[2]) > m + 1e-6


def _inside(a, w):
    return a[0] >= w[0] - 1e-6 and a[1] <= w[2] + 1e-6 and a[2] >= w[1] - 1e-6 and a[3] <= w[3] + 1e-6


def spec_sanity():
    """Board-level rules the housing depends on (SPEC 2.1 / D2 / D3 / D4).  Returns [(status, text)], source."""
    parts, src = load_parts()
    res = []
    ch0, ch1 = P.TAPE_YC - P.TAPE_CH_W / 2, P.TAPE_YC + P.TAPE_CH_W / 2
    # 1. bottom side over the beam band: only inside the AS5311 window, <= 1.30, and inside the channel
    for ref, side, x0, x1, y0, y1, h, note in parts:
        if side != "B" or not (y0 < P.BEAM_W and y1 > 0):
            continue
        win = _inside((x0, x1, y0, y1), P.BOTTOM_WINDOW)
        in_ch = y0 >= ch0 + 0.3 and y1 <= ch1 - 0.3
        ok = win and in_ch and h <= P.BOTTOM_WINDOW_H + 1e-9
        res.append(("OK  " if ok else "FAIL",
                    f"bottom part {ref} over the beam band: x {x0:.2f}..{x1:.2f} y {y0:.2f}..{y1:.2f} h {h:.2f} "
                    f"(window x 20..41 y 2.4..9.6 {'in' if win else 'OUT'}, channel {'in' if in_ch else 'OUT'}, "
                    f"<= {P.BOTTOM_WINDOW_H})"))
    # 2. top-side height rules: <= 2.6 under the glass + ribs, <= 4.2 elsewhere
    worst = {}
    for ref, side, x0, x1, y0, y1, h, note in parts:
        if side != "T":
            continue
        lim = P.H_UNDER_GLASS if _overlap((x0, x1, y0, y1), (P.UNDER_GLASS[0], P.UNDER_GLASS[2],
                                                             P.UNDER_GLASS[1], P.UNDER_GLASS[3])) else P.H_ELSEWHERE
        if h > lim + 1e-9:
            res.append(("FAIL", f"top part {ref} h {h:.2f} > {lim} ({'under the glass' if lim < 4 else 'outside the glass'})"))
        worst[lim] = max(worst.get(lim, (0.0, "")), (h, ref))
    for lim, (h, ref) in sorted(worst.items()):
        res.append(("OK  " if h <= lim + 1e-9 else "FAIL",
                    f"tallest top part {'under the glass' if lim < 4 else 'elsewhere'}: {ref} {h:.2f} (limit {lim})"))
    # 1b. bottom side in the upper band (y > 20): only the module's decoupling / ADC filter exception (SPEC 2.1, h <= 0.55)
    #     and parts that hang into the battery pocket (J2 and its plug since 2026-11-09), clear of its walls
    mod_ex = (1.8, 4.4, 22.7, 27.0)
    b = P.BAT_POCKET
    pocket = (b["u0"] - P.BOARD_U0 + 0.3, b["u1"] - P.BOARD_U0 - 0.3, b["y0"] + 0.3, b["y1"] - 0.3)
    for ref, side, x0, x1, y0, y1, h, note in parts:
        if side != "B" or y1 <= P.BEAM_W:
            continue
        if _inside((x0, x1, y0, y1), (mod_ex[0], mod_ex[2], mod_ex[1], mod_ex[3])) and h <= 0.55 + 1e-9:
            where = "the module exception x 1.8..4.4, y 22.7..27.0, <= 0.55"
            ok = True
        else:
            cell = (P.BAT_U0 - P.BOARD_U0, P.BAT_U0 + P.BAT_L - P.BOARD_U0, b["y0"], b["y1"])
            over_cell = _overlap((x0, x1, y0, y1), cell)
            ok = _inside((x0, x1, y0, y1), (pocket[0], pocket[2], pocket[1], pocket[3])) and \
                (not over_cell or P.BOARD_Z0 - h >= P.Z_POCKET + P.BAT_T + 0.3)
            where = f"the battery pocket x {pocket[0]:.1f}..{pocket[1]:.1f}, y {pocket[2]:.1f}..{pocket[3]:.1f} (0.3 in)"
        res.append(("OK  " if ok else "FAIL", f"bottom part {ref} in the upper band: x {x0:.2f}..{x1:.2f} y {y0:.2f}..{y1:.2f} "
                    f"h {h:.2f} {'inside' if ok else 'NOT inside'} {where}"))
    for ref, req in pending():
        res.append(("PEND", f"board change request (not on the routed board yet; the envelope uses it): {req}"))
    # 3. antenna keep-out: no part on either side except the module itself
    ko = P.ANTENNA_KEEPOUT
    bad = [r for r, side, x0, x1, y0, y1, h, n in parts
           if r != "U10" and _overlap((x0, x1, y0, y1), (ko[0], ko[2], ko[1], ko[3]))]
    res.append(("OK  " if not bad else "FAIL", f"antenna keep-out x {ko[0]}..{ko[2]} y {ko[1]}..{ko[3]}: "
                f"{'no parts' if not bad else 'parts ' + ', '.join(bad)}"))
    # 4. holes: tab holes on the tabs, H1 with boss room clear of the beam / gib
    for ref, x, y in holes():
        if x < 0 or x > P.BOARD_L:
            on_tab = any(t[0] + 1.5 <= x <= t[2] - 1.5 and t[1] + 2.0 <= y <= t[3] - 2.0 for t in P.BOARD_TABS)
            res.append(("OK  " if on_tab else "FAIL", f"{ref} ({x}, {y}) on an end tab with standoff room: {on_tab}"))
        else:
            room = y - P.BOSS_D / 2 >= P.CH_Y1 + 0.5 - 1e-9
            res.append(("OK  " if room else "FAIL", f"{ref} ({x}, {y}) boss clear of the channel / Y gib "
                        f"(boss edge y {y - P.BOSS_D / 2:.2f} >= {P.CH_Y1 + 0.5:.2f}): {room}"))
        for r2, side, x0, x1, y0, y1, h, n in parts:
            if side == "T" and not r2.startswith(ref + "_") and x0 - 0.5 < x < x1 + 0.5 and y0 - 0.5 < y < y1 + 0.5:
                res.append(("FAIL", f"mounting hole {ref} is under top part {r2}"))
    # 5. top parts that overlap each other in plan (placement conflicts)
    tops = [p for p in parts if p[1] == "T"]
    for i, a in enumerate(tops):
        for b in tops[i + 1:]:
            if a[0].split("_")[0] == b[0].split("_")[0]:
                continue
            if _overlap(a[2:6], b[2:6], 0.05):
                res.append(("FAIL", f"top parts {a[0]} and {b[0]} overlap in plan (placement)"))
    return res, src


if __name__ == "__main__":
    parts, src = load_parts()
    print(f"slider-board envelope from {src}")
    for ref, side, x0, x1, y0, y1, h, note in parts:
        print(f"  {ref:<16}{side}  x {x0:6.2f}..{x1:6.2f}  y {y0:6.2f}..{y1:6.2f}  h {h:4.2f}  {note}")
    print("\nboard rules:")
    for st, txt in spec_sanity()[0]:
        print(f"  {st} {txt}")
