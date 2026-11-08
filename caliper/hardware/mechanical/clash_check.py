#!/usr/bin/env python3
"""Interference and gap check of the caliper model (build123d / OpenCascade booleans).

    python3 clash_check.py            # -> clash_report.txt

dial-me-spinner ran this check as OpenSCAD/CGAL intersections; here the model is
already B-rep, so each check is an exact `a & b` and its volume (0 = no clash;
face contact, such as a gib on the beam, has zero volume and counts as clear).

Checks
  board   the slider-board envelope (board_envelope.py: board_parts.json once the
          layout exists, the SPEC placeholder until then) vs every housing part
  travel  every slider part vs the beam, fixed jaw, tape, scale and stop pin at
          R = 0, 75 and RANGE + OVERTRAVEL (the stop)
  pair    slider-internal pairs (body / shell / cover / caps / roller / gibs / display / battery)
  gap     the AS5311 package face to the tape (target MAG_GAP), the electrode face
          to the scale (target CAP_GAP), and the AS5311 inside the tape channel
"""
import itertools
import os
import sys

import board_envelope as BE
import models as M
import params as P

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
    except Exception as e:     # noqa: BLE001  (report, don't hide)
        return float("nan")


#: Overlaps that are the design: the roller's O-ring tyre is squeezed 0.15 onto the
#: beam's upper edge (ROLLER_Y), which is what makes the roller drive the slider.
INTENDED = {("oring", "beam")}


def line(kind, a, b, v):
    st = "CLEAR" if v <= EPS else ("??   " if v != v else "CLASH")
    if st == "CLASH" and (a, b) in INTENDED:
        st = "INTND"
    tail = "" if v <= EPS else f"  overlap {v:.3f} mm^3"
    return st, f"{st}  {kind:<6} {a}  x  {b}{tail}"


def main():
    out = []
    parts = M.slider_group(0.0, with_hardware=False)
    housing = {n: s for n, s, _c in parts}
    housing["display"] = M.display_module()
    housing["battery"] = M.battery()
    housing["lock_screw"] = M.lock_screw()

    # 1. board envelope vs housing
    board_items = [("board", BE.board())] + [(r, s) for r, s, _side, _n in BE.part_solids()]
    for (bn, bs), (hn, hs) in itertools.product(board_items, housing.items()):
        out.append(line("board", bn, hn, vol(bs, hs)))

    # 2. travel: slider parts vs the fixed parts
    fixed = {n: s for n, s, _c in M.fixed_group()}
    for R in (0.0, 75.0, P.RANGE + P.OVERTRAVEL):
        moving = {n: s for n, s, _c in M.slider_group(R, with_hardware=False)}
        moving["display"] = M.Pos(R, 0, 0) * M.display_module()
        moving["battery"] = M.Pos(R, 0, 0) * M.battery()
        moving["board"] = M.Pos(R, 0, 0) * BE.board()
        for r, s, _side, _n in BE.part_solids():
            moving[r] = M.Pos(R, 0, 0) * s
        for (mn, ms), (fn, fs) in itertools.product(moving.items(), fixed.items()):
            out.append(line(f"R{R:g}", mn, fn, vol(ms, fs)))

    # 3. slider-internal pairs
    names = list(housing)
    for a, b in itertools.combinations(names, 2):
        out.append(line("pair", a, b, vol(housing[a], housing[b])))

    # 4. gaps
    gaps = []
    as_face = P.BOARD_Z0 - P.AS_H_NOM
    g_mag = as_face - P.TAPE_TOP
    g_cap = P.BOARD_Z0 - 0.0
    gaps.append(("OK  " if abs(g_mag - P.MAG_GAP) < 1e-6 else "FAIL",
                 f"AS5311 face (nominal A {P.AS_H_NOM}) to tape: {g_mag:.3f} mm (target {P.MAG_GAP}); "
                 f"over the package range A {P.AS_H_MIN}-{P.AS_H_MAX}: "
                 f"{P.BOARD_Z0 - P.AS_H_MAX - P.TAPE_TOP:.3f}-{P.BOARD_Z0 - P.AS_H_MIN - P.TAPE_TOP:.3f} mm "
                 f"with the nominal {P.TAPE_SHIM_NOM:.2f} shim; the per-unit shim "
                 f"(0-{P.TAPE_SHIM_MAX:.2f}) brings every package to {P.MAG_GAP}"))
    gaps.append(("OK  " if abs(g_cap - P.CAP_GAP) < 1e-6 else "FAIL",
                 f"electrode face to scale face: {g_cap:.3f} mm (target {P.CAP_GAP})"))
    # exact B-rep distance between the AS5311 body box and the tape, as modelled (A max)
    asb = [s for r, s, _side, _n in BE.part_solids() if r == "U_AS5311"]
    if asb:
        d = asb[0].distance_to(M.tape())
        gaps.append(("OK  " if d >= P.MAG_GAP - P.MAG_GAP_TOL - 1e-6 else "FAIL",
                     f"B-rep distance AS5311 (A max) to tape: {d:.3f} mm (>= {P.MAG_GAP - P.MAG_GAP_TOL:.2f})"))
    ch0, ch1 = P.TAPE_YC - P.TAPE_CH_W / 2, P.TAPE_YC + P.TAPE_CH_W / 2
    l0, l1 = P.AS_Y - P.AS_LEAD_Y / 2, P.AS_Y + P.AS_LEAD_Y / 2
    gaps.append(("OK  " if l0 - ch0 >= 0.5 and ch1 - l1 >= 0.5 else "FAIL",
                 f"AS5311 leads y {l0:.2f}..{l1:.2f} inside the channel {ch0:.2f}..{ch1:.2f} "
                 f"(side clearance {min(l0 - ch0, ch1 - l1):.2f}, need >= 0.5)"))
    for st, txt in BE.spec_sanity()[0]:
        gaps.append((st, "board  " + txt))

    clashes = [t for s, t in out if s not in ("CLEAR", "INTND")]
    n_bad = len(clashes)
    intended = sorted({t.split("overlap")[0].split(None, 2)[2] for s, t in out if s == "INTND"})
    if intended:
        clashes += ["(intended contact, not counted: " + "; ".join(i.strip() for i in intended) + ")"]
    src = BE.load_parts()[1]
    rep = [f"clash_check.py -- board envelope from {src}",
           f"{len(out)} intersections, {n_bad} not clear", ""]
    rep += ["== not clear =="] + (clashes or ["(none)"]) + [""]
    rep += ["== gaps and board rules =="] + [f"{s} {t}" for s, t in gaps] + [""]
    rep += ["== all =="] + sorted(t for _s, t in out)
    txt = "\n".join(rep) + "\n"
    with open(os.path.join(HERE, "clash_report.txt"), "w") as f:
        f.write(txt)
    print("\n".join(rep[:3 + len(clashes) + 3 + len(gaps) + 2]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
