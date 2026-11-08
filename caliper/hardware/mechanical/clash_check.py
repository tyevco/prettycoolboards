#!/usr/bin/env python3
"""Interference, gap, wall and RF check of the caliper model (build123d / OpenCascade booleans).

    python3 clash_check.py            # -> clash_report.txt

dial-me-spinner ran this check as OpenSCAD/CGAL intersections; here the model is
already B-rep, so each check is an exact `a & b` and its volume (0 = no clash;
face contact, such as a gib on the beam, has zero volume and counts as clear).

Checks
  board   the slider-board envelope (board_envelope.py: board_parts.json from the routed
          .kicad_pcb, the SPEC placeholder without it) vs every housing part
  travel  every slider part + the board vs the beam, fixed jaw, tape, scale and stop screw
          at R = 0, 75 and RANGE + OVERTRAVEL (the stop)
  pair    slider-internal pairs (body / shell / door / caps / roller / gibs / pushers /
          display / battery / clamp hardware)
  gap     the AS5311 package face to the tape (target MAG_GAP), the electrode face to the
          scale (target CAP_GAP), the AS5311 inside the tape channel, the board rules
  wall    the web between every two cut features of the slider body (models.body_cuts):
          a pair that meets without being meant to is BREAK, a web under WALL_LOCAL_MIN is THIN
  rf      every metal item's plan distance to the antenna area (SPEC D4: >= 5 mm)
"""
import itertools
import os
import sys

import board_envelope as BE
import models as M
import params as P
from params import bu

HERE = os.path.dirname(os.path.abspath(__file__))
EPS = 1e-3      # mm^3


def vol(a, b):
    try:
        bb_a, bb_b = a.bounding_box(), b.bounding_box()
        if (bb_a.max.X < bb_b.min.X or bb_b.max.X < bb_a.min.X or bb_a.max.Y < bb_b.min.Y
                or bb_b.max.Y < bb_a.min.Y or bb_a.max.Z < bb_b.min.Z or bb_b.max.Z < bb_a.min.Z):
            return 0.0
        r = a & b
        return r.volume if r is not None else 0.0
    except Exception:     # noqa: BLE001  (report, don't hide)
        return float("nan")


#: Overlaps that are the design: the roller's O-ring tyre is squeezed 0.15 onto the
#: beam's upper edge (ROLLER_Y), which is what makes the roller drive the slider.
INTENDED = {("oring", "beam")}

#: Body cut features that are meant to open into each other (wall check).
JOINED = {frozenset(p) for p in [
    ("tunnel_cavity", "tab_clamps"), ("tunnel_cavity", "h1_pilot"), ("tunnel_cavity", "battery_pocket"),
    ("tunnel_cavity", "plug_relief"), ("tunnel_cavity", "pad_pockets"), ("tunnel_cavity", "y_bores"),
    ("tunnel_cavity", "back_plungers"), ("tunnel_cavity", "roller_slot"), ("tunnel_cavity", "usb"),
    ("battery_pocket", "plug_relief"), ("battery_pocket", "door_rebate"), ("door_rebate", "door_pilots"),
    ("pad_pockets", "pad_screws"), ("roller_slot", "roller_axle"), ("roller_axle", "usb"),
    ("roller_slot", "usb"), ("tunnel_cavity", "roller_axle"),
]}


def line(kind, a, b, v):
    st = "CLEAR" if v <= EPS else ("??   " if v != v else "CLASH")
    if st == "CLASH" and (a, b) in INTENDED:
        st = "INTND"
    tail = "" if v <= EPS else f"  overlap {v:.3f} mm^3"
    return st, f"{st}  {kind:<6} {a}  x  {b}{tail}"


def housing_parts():
    h = {n: s for n, s, _c in M.slider_group(0.0, with_hardware=False)}
    h["display"] = M.display_module()
    h["battery"] = M.battery()
    h["lock_screw"] = M.lock_screw()
    for i, s in enumerate(M.tab_clamp_hardware()):
        h[f"tab_clamp_{i}"] = s
    for i, s in enumerate(M.plunger_hardware()):
        h[f"plunger_hw_{i}"] = s
    return h


def inserts():
    """The brass heat-set inserts and steel pins that are not modelled as parts (RF check)."""
    out = {}
    for x, y, kind in P.LID_SCREWS:
        if kind == "insert":
            out[f"lid_insert_u{x:g}"] = M.zcyl(x, y, 3.6, P.Z_LID_IN - P.INSERT_M2_L, P.Z_LID_IN)
    for u, _y0, _y1, ys in P.FPADS:
        out[f"pad_insert_u{u:g}_y{ys:g}"] = M.zcyl(u, ys, 3.6, P.Z_LID_IN - P.INSERT_M2_L, P.Z_LID_IN)
    for u in P.YGIB_PLUNGERS_U:
        out[f"y_plunger_insert_u{u:g}"] = M.ycyl(u, P.GIB_Z, 3.6, P.H_Y1 - P.INSERT_M2_L, P.H_Y1)
    out[f"lock_insert_u{P.LOCK_U:g}"] = M.ycyl(P.LOCK_U, P.GIB_Z, 4.5, P.H_Y1 - P.INSERT_M3_L, P.H_Y1)
    for u, y in P.BGIB_PLUNGERS:
        out[f"back_plunger_insert_u{u:g}"] = M.zcyl(u, y, 3.6, P.Z_BACK, P.Z_BACK + P.INSERT_M2_L)
    out["roller_axle_pin"] = M.zcyl(P.ROLLER_U, P.ROLLER_Y, P.ROLLER_AXLE_D, P.Z_BACK + 0.5, P.ROLLER_Z1 + 0.3)
    for i, (x, y) in enumerate(P.DOOR_SCREWS):
        out[f"door_screw_{i}"] = M.zcyl(x, y, 2.2, P.Z_BACK, P.Z_BACK + P.DOOR_T + 3.0)
    return out


def wall_check():
    """[(status, text)] for every pair of body cut features closer than WALL_MIN."""
    cuts = {"tunnel_cavity": M.tunnel_and_cavity()}
    cuts.update(M.body_cuts("A"))
    res = []
    for (na, a), (nb, b) in itertools.combinations(cuts.items(), 2):
        try:
            d = a.distance_to(b)
        except Exception:      # noqa: BLE001
            d = float("nan")
        if d != d:
            res.append(("??  ", f"{na} / {nb}: distance failed"))
            continue
        if d >= P.WALL_MIN - 1e-6:
            continue
        joined = frozenset((na, nb)) in JOINED
        if d < 1e-4:
            res.append(("open" if joined else "BREAK", f"{na} / {nb}: {'meet (intended opening)' if joined else 'BREAK INTO EACH OTHER'}"))
        else:
            st = "THIN" if d < P.WALL_LOCAL_MIN - 1e-6 else "web "
            res.append((st, f"{na} / {nb}: web {d:.2f} mm (< WALL_MIN {P.WALL_MIN}; local minimum {P.WALL_LOCAL_MIN})"))
    return res


def rf_check(parts):
    """[(status, text)]: plan distance of each metal item to the antenna area (a tall prism)."""
    a = P.ANTENNA
    ant = M.box(bu(a[0]), bu(a[2]), a[1], a[3], -60, 60)
    metal = {n: s for n, s in parts.items()
             if n.startswith(("back_gib", "y_gib", "ref_strip", "front_pad", "lock_screw", "tab_clamp", "plunger_hw"))}
    metal.update(inserts())
    metal["beam"] = M.beam()
    metal["stop_screw"] = M.stop_screw()
    for r, s, _side, _n in BE.part_solids():
        if r.endswith("_standoff") or r in ("J1", "J2", "J2_plug"):
            metal[f"board:{r}"] = s
    metal["battery (cell)"] = M.battery()
    res = []
    for n, s in sorted(metal.items()):
        d = s.distance_to(ant)
        res.append(("OK  " if d >= P.RF_CLEAR - 1e-6 else "FAIL", f"{n}: {d:.2f} mm from the antenna area in plan"))
    res.sort(key=lambda t: float(t[1].split(": ")[1].split()[0]))
    # carbon-filled material
    jaw = M.prism(M.moving_inside_jaw_pts(), *P.IJ_MOVING_Z)
    ant3 = M.box(bu(a[0]), bu(a[2]), a[1], a[3], P.BOARD_Z1, P.BOARD_Z1 + 2.55)
    dj = jaw.distance_to(ant)
    res.append(("OK  " if dj >= P.RF_CLEAR - 1e-6 else "RISK", f"PA-CF moving inside jaw: {dj:.2f} mm in plan, "
                        f"{jaw.distance_to(ant3):.2f} mm in 3D from the antenna (it sits behind the beam plane)"))
    mod = M.rf_modifier()
    res.append(("OK  ", f"body within {P.RF_CLEAR:g} mm of the antenna: {mod.volume / 1000:.2f} cm^3, printed in unfilled PA "
                        "through the slicer modifier stl/slider_body_rf_modifier.stl"))
    return res


def main():
    out = []
    housing = housing_parts()

    # 1. board envelope vs housing
    board_items = [("board", BE.board())] + [(r, s) for r, s, _side, _n in BE.part_solids()]
    for (bn, bs), (hn, hs) in itertools.product(board_items, housing.items()):
        out.append(line("board", bn, hn, vol(bs, hs)))

    # 2. travel: slider parts vs the fixed parts
    fixed = {n: s for n, s, _c in M.fixed_group()}
    for R in (0.0, 75.0, P.RANGE + P.OVERTRAVEL):
        T = M.Pos(R, 0, 0)
        moving = {n: T * s for n, s in housing.items()}
        moving["board"] = T * BE.board()
        for r, s, _side, _n in BE.part_solids():
            moving[r] = T * s
        for (mn, ms), (fn, fs) in itertools.product(moving.items(), fixed.items()):
            out.append(line(f"R{R:g}", mn, fn, vol(ms, fs)))

    # 3. slider-internal pairs
    for a, b in itertools.combinations(list(housing), 2):
        out.append(line("pair", a, b, vol(housing[a], housing[b])))

    # 4. gaps and board rules
    gaps = []
    g_mag = P.BOARD_Z0 - P.AS_H_NOM - P.TAPE_TOP
    g_cap = P.BOARD_Z0 - 0.0
    gaps.append(("OK  " if abs(g_mag - P.MAG_GAP) < 1e-6 else "FAIL",
                 f"AS5311 face (nominal A {P.AS_H_NOM}) to tape: {g_mag:.3f} mm (target {P.MAG_GAP}); "
                 f"over the package range A {P.AS_H_MIN}-{P.AS_H_MAX}: "
                 f"{P.BOARD_Z0 - P.AS_H_MAX - P.TAPE_TOP:.3f}-{P.BOARD_Z0 - P.AS_H_MIN - P.TAPE_TOP:.3f} mm "
                 f"with the nominal {P.TAPE_SHIM_NOM:.2f} shim; the per-unit shim "
                 f"(0-{P.TAPE_SHIM_MAX:.2f}) brings every package to {P.MAG_GAP}"))
    gaps.append(("OK  " if abs(g_cap - P.CAP_GAP) < 1e-6 else "FAIL",
                 f"electrode face to scale face: {g_cap:.3f} mm (target {P.CAP_GAP})"))
    asb = [s for r, s, _side, _n in BE.part_solids() if r in ("U30", "U_AS5311")]
    if asb:
        d = asb[0].distance_to(M.tape())
        gaps.append(("OK  " if d >= P.MAG_GAP - P.MAG_GAP_TOL - 1e-6 else "FAIL",
                     f"B-rep distance AS5311 U30 (A max, as placed) to tape: {d:.3f} mm (>= {P.MAG_GAP - P.MAG_GAP_TOL:.2f})"))
    ch0, ch1 = P.TAPE_YC - P.TAPE_CH_W / 2, P.TAPE_YC + P.TAPE_CH_W / 2
    l0, l1 = P.AS_Y - P.AS_LEAD_Y / 2, P.AS_Y + P.AS_LEAD_Y / 2
    gaps.append(("OK  " if l0 - ch0 >= 0.5 and ch1 - l1 >= 0.5 else "FAIL",
                 f"AS5311 leads y {l0:.2f}..{l1:.2f} inside the channel {ch0:.2f}..{ch1:.2f} "
                 f"(side clearance {min(l0 - ch0, ch1 - l1):.2f}, need >= 0.5)"))
    # the tape channel must stay under the bottom-side window over the whole travel
    for R in (0.0, P.RANGE + P.OVERTRAVEL):
        x0, x1 = R + bu(P.BOTTOM_WINDOW[0]), R + bu(P.BOTTOM_WINDOW[2])
        ok = x0 >= P.TAPE_X0 - 1 and x1 <= P.TAPE_X1 + 1
        gaps.append(("OK  " if ok else "FAIL", f"bottom window x {x0:.1f}..{x1:.1f} over the tape channel "
                     f"x {P.TAPE_X0 - 1:g}..{P.TAPE_X1 + 1:g} at R {R:g}"))
    for st, txt in BE.spec_sanity()[0]:
        gaps.append((st, "board  " + txt))

    walls = wall_check()
    rf = rf_check(housing)

    clashes = [t for s, t in out if s not in ("CLEAR", "INTND")]
    n_bad = len(clashes)
    intended = sorted({t.split("overlap")[0].split(None, 2)[2] for s, t in out if s == "INTND"})
    if intended:
        clashes += ["(intended contact, not counted: " + "; ".join(i.strip() for i in intended) + ")"]
    src = BE.load_parts()[1]
    n_fail = sum(1 for s, _t in gaps + rf if s == "FAIL")
    n_wall = sum(1 for s, _t in walls if s in ("BREAK", "THIN"))
    rep = [f"clash_check.py -- board envelope from {src}",
           f"{len(out)} intersections, {n_bad} not clear; gap/board/RF rules: {n_fail} FAIL; "
           f"body webs: {n_wall} BREAK/THIN", ""]
    rep += ["== not clear =="] + (clashes or ["(none)"]) + [""]
    rep += ["== gaps and board rules =="] + [f"{s} {t}" for s, t in gaps] + [""]
    rep += ["== body walls (cut-feature pairs closer than WALL_MIN) =="] + [f"{s:<5} {t}" for s, t in walls] + [""]
    rep += ["== RF (SPEC D4) =="] + [f"{s} {t}" for s, t in rf] + [""]
    head_len = len(rep)
    rep += ["== all =="] + sorted(t for _s, t in out)
    txt = "\n".join(rep) + "\n"
    with open(os.path.join(HERE, "clash_report.txt"), "w", newline="\n") as f:
        f.write(txt)
    print("\n".join(rep[:head_len]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
