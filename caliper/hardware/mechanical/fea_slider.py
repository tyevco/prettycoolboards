#!/usr/bin/env python3
"""FEA of the slider body under its gib preloads, and of the slider board under a button press.

Uses the `print-stress` skill's solver (linear tets; ~/.claude/skills/print-stress/scripts),
which runs on the Windows Python on the design machine, not in the WSL venv:

    py fea_slider.py [body_size] [board_size]      # -> fea_slider_output.txt, renders/fea_body.png

A. Body (step/slider_body.step, exported by export.py, the exact model): PA-CF.
   Supports: the four front-pad pocket ceilings (z), the reference-strip seat (y, x).
   Loads: the two back-gib plungers push the body away from the beam's back face
   (P_BACK each, -z, on their insert bores in the back web); the two Y plungers push it
   up (P_Y each, +y, on the M3 threads at the top face).  Reports the web deflection at the back
   plungers (preload held?), the z movement of the four tab-clamp ceilings (the board's
   Z datum) and the peak stresses with the print-layer check (layers normal to z).
B. Board (FR4, E 20 GPa; outline + tabs from board_parts.json, 1.0 thick): clamped on the
   four standoff footprints (top face, Dia 4.0), resting on the H1 boss (bottom face, Dia
   4.5, z only) and -- second set of runs -- on the button-band ledge under its top edge
   (params.BTN_LEDGE, z only), 3 N on each button's switch footprint in turn.  Reports the deflection at
   the button, the worst point of the electrode band and of the AS5311 footprint.
   Linear tets are stiff in plate bending at ~2 elements through 1 mm, so a cantilever strip
   meshed the same way calibrates a correction factor (theory / FEA), applied to B.
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.expanduser("~/.claude/skills/print-stress/scripts"))
import gmsh                    # noqa: E402
from occ import Model          # noqa: E402
from stlfea import Part        # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import params as P             # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
body_size = float(sys.argv[1]) if len(sys.argv) > 1 else 1.6
board_size = float(sys.argv[2]) if len(sys.argv) > 2 else 0.5
E_PACF, NU_PACF = 4200.0 * 0.85, 0.36       # calcs.py FDM knock-down
E_FR4, NU_FR4 = 20000.0, 0.15
PRESS = 3.0
LINES, RESULT = [], {}


def say(s=""):
    LINES.append(s)
    print(s)


def result(k, v):
    RESULT[k] = v
    LINES.append(f"RESULT {k} = {v:.4g}")


# ---------------------------------------------------------------------------
# A. body under the preloads
# ---------------------------------------------------------------------------
def body():
    step = os.path.join(HERE, "step", "slider_body.step")
    M = Model()
    M.o.importShapes(step)
    M.o.synchronize()
    fine = [((u - 6, -4, P.Z_BACK - 1, u + 6, 22, P.Z_LID_IN + 1), 0.7) for u in (4.5, 73.5)]
    fine += [((u - 4, y - 4, P.Z_BACK - 1, u + 4, y + 4, P.Z_WEB_IN + 1), 0.7) for u, y in P.BGIB_PLUNGERS]
    p, t = M.mesh(size=body_size, fine=fine)
    say(f"A. body mesh: {len(t)} tets, {len(p)} nodes (global {body_size}, fine 0.7 at the towers and back plungers)")
    B = Part(None, mesh=(p, t))

    def pad_ceiling(C, N):
        m = (np.abs(C[:, 2] - (P.FPAD_T + 0.2)) < 0.02) & (N[:, 2] < -0.9)
        inside = np.zeros(len(C), bool)
        for u, y0, y1, _ys in P.FPADS:
            inside |= (np.abs(C[:, 0] - u) < P.FPAD_LEN / 2 + 0.1) & (C[:, 1] > y0 - 0.15) & (C[:, 1] < y1 + 0.15)
        return m & inside
    seat = lambda C, N: (np.abs(C[:, 1] - P.CH_Y0) < 0.02) & (N[:, 1] > 0.9)            # noqa: E731
    n1 = B.fix(pad_ceiling, "z")
    n2 = B.fix(seat, "xy")
    say(f"   supports: pad ceilings {n1} facets (z), reference-strip seat {n2} facets (x, y)")
    for u, y in P.BGIB_PLUNGERS:
        sel = (lambda u, y: lambda C, N: (np.abs(np.hypot(C[:, 0] - u, C[:, 1] - y) - P.INSERT_M2_D / 2) < 0.08)
               & (C[:, 2] < P.Z_BACK + P.INSERT_M2_L) & (np.abs(N[:, 2]) < 0.3))(u, y)
        n, a = B.load(sel, (0.0, 0.0, -P.P_BACK))
        say(f"   back plunger u {u:g}: {P.P_BACK} N -z on {n} facets ({a:.1f} mm2)")
    for u in P.YGIB_PLUNGERS_U:
        # the nylon set screw's thread reacts on the M3 thread tapped in the print at the top face (2026-11-09)
        sel = (lambda u: lambda C, N: (np.abs(np.hypot(C[:, 0] - u, C[:, 2] - P.GIB_Z) - P.M3_TAP / 2) < 0.2)
               & (C[:, 1] > P.H_Y1 - P.Y_TAP_L) & (np.abs(N[:, 1]) < 0.3))(u)
        n, a = B.load(sel, (0.0, P.P_Y, 0.0))
        say(f"   Y plunger u {u:g}: {P.P_Y} N +y on {n} facets ({a:.1f} mm2)")
    B.solve(E=E_PACF, nu=NU_PACF)
    rep = B.report(layer_normal=(0, 0, 1), s_inter=20.0, s_in=45.0)
    tot = 2 * P.P_BACK + 2 * P.P_Y
    say(f"   reaction {rep['reaction_N']} N (applied {2 * P.P_BACK:g} N z, {2 * P.P_Y:g} N y); von Mises "
        f"{rep['von_mises']} MPa, interlayer {rep['interlayer_tension']}/{rep['interlayer_shear']} MPa, "
        f"SF in-layer {rep['SF_in_layer']}, interlayer {rep['SF_interlayer']}")
    result("body_reaction_N", float(np.linalg.norm(B.reaction)))
    if abs(np.linalg.norm(B.reaction) - np.hypot(2 * P.P_BACK, 2 * P.P_Y)) > 0.01 * tot:
        say("   WARNING: the reactions do not balance the loads -- this run is invalid")
    # web deflection at the back plungers: the loaded facets' mean z movement
    for u, y in P.BGIB_PLUNGERS:
        m = (np.abs(np.hypot(B.bc[:, 0] - u, B.bc[:, 1] - y) - P.INSERT_M2_D / 2) < 0.08) & (B.bc[:, 2] < P.Z_BACK + P.INSERT_M2_L)
        nodes = np.unique(B.bf[m])
        say(f"   back plunger u {u:g}: seat moves {B.u[nodes, 2].mean() * 1e3:+.2f} um in z")
    wp = max(abs(B.u[np.unique(B.bf[(np.abs(np.hypot(B.bc[:, 0] - u, B.bc[:, 1] - y) - P.INSERT_M2_D / 2) < 0.08)
                                      & (B.bc[:, 2] < P.Z_BACK + P.INSERT_M2_L)]), 2].mean()) for u, y in P.BGIB_PLUNGERS)
    result("web_plunger_um", wp * 1e3)
    # tab-clamp ceilings
    dz = []
    for x, y in P.TAB_HOLES:
        u = P.BOARD_U0 + x
        m = (np.abs(B.bc[:, 2] - P.CLAMP_CEIL_Z) < 0.02) & (B.bn[:, 2] < -0.9) & \
            (np.hypot(B.bc[:, 0] - u, B.bc[:, 1] - y) < P.STANDOFF_POCKET_D / 2)
        nodes = np.unique(B.bf[m])
        dz.append(B.u[nodes, 2].mean() if len(nodes) else np.nan)
        say(f"   clamp ceiling ({x:g}, {y:g}): {len(nodes)} nodes, dz {dz[-1] * 1e3:+.2f} um")
    result("clamp_dz_um", float(np.nanmax(np.abs(dz))) * 1e3)
    np.save(os.path.join(os.environ.get("TEMP", "/tmp"), "fea_body.npy"),
            dict(p=B.p, t=B.t, eb=np.zeros(len(B.t), int), sig=B.sig, u=B.u, names=["slider body"], layers=[(0, 0, 1.0)]),
            allow_pickle=True)


# ---------------------------------------------------------------------------
# B. board under a button press
# ---------------------------------------------------------------------------
def plate(pts, h):
    M = Model()
    o = M.o
    ps = [o.addPoint(x, y, 0.0) for x, y in pts]
    ls = [o.addLine(ps[i], ps[(i + 1) % len(ps)]) for i in range(len(ps))]
    s = o.addPlaneSurface([o.addCurveLoop(ls)])
    o.extrude([(2, s)], 0, 0, h)
    o.synchronize()
    return M


def calibrate(size):
    """Cantilever strip 40 x 6 x 1 (FR4), 1 N at the tip: theory / FEA."""
    L, w, h = 40.0, 6.0, P.BOARD_T
    M = plate([(0, 0), (L, 0), (L, w), (0, w)], h)
    p, t = M.mesh(size=size)
    S = Part(None, mesh=(p, t))
    S.fix(lambda C, N: (np.abs(C[:, 0]) < 0.01) & (N[:, 0] < -0.9), "xyz")
    S.load(lambda C, N: (np.abs(C[:, 0] - L) < 0.01) & (N[:, 0] > 0.9), (0, 0, -1.0))
    S.solve(E=E_FR4, nu=NU_FR4)
    fe = -S.u[S.p[:, 0] > L - 0.01, 2].mean()
    th = 1.0 * L ** 3 / (3 * E_FR4 * w * h ** 3 / 12) + 1.0 * L / (5 / 6 * E_FR4 / (2 * (1 + NU_FR4)) * w * h)
    say(f"   calibration: cantilever 40 x 6 x 1, {len(t)} tets: FEA {fe * 1e3:.1f} um, theory {th * 1e3:.1f} um "
        f"-> correction x{th / fe:.2f}")
    return th / fe


def board():
    d = json.load(open(os.path.join(HERE, "board_parts.json")))
    pts = [tuple(q) for q in d["slider"]["outline"]]
    area2 = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]))
    if area2 < 0:
        pts = pts[::-1]
    k = calibrate(board_size)
    result("tet_correction", k)
    M = plate(pts, P.BOARD_T)
    p, t = M.mesh(size=board_size)
    say(f"B. board mesh: {len(t)} tets, {len(p)} nodes (size {board_size}, outline from board_parts.json)")
    holes = {h["ref"]: (h["x"], h["y"]) for h in d["slider"]["holes"]}
    tabs = [holes[r] for r in ("H2", "H3", "H4", "H5")]
    h1 = holes["H1"]
    L = P.BTN_LEDGE
    ledge = (L["u0"] - P.BOARD_U0, L["u1"] - P.BOARD_U0, L["y0"], P.BOARD_W)
    for tag, use_ledge in (("noledge_", False), ("", True)):
        say(f"   -- {'with' if use_ledge else 'without'} the button-band ledge"
            + (f" (board x {ledge[0]:g}..{ledge[1]:g}, y {ledge[2]:g}..{ledge[3]:g})" if use_ledge else ""))
        press_runs(p, t, k, tabs, h1, ledge if use_ledge else None, tag)


def press_runs(p, t, k, tabs, h1, ledge, tag):
    zt = P.BOARD_T
    band = (9.58, 52.42, 10.35, 18.05)
    asw = (27.75, 34.25, 3.8, 8.2)
    worst = {"button": 0, "band": 0, "as": 0}
    for name, (bx, by) in P.BUTTONS.items():
        B = Part(None, mesh=(p, t))
        nfix = sum(B.fix((lambda x, y: lambda C, N: (np.abs(C[:, 2] - zt) < 0.01) & (N[:, 2] > 0.9)
                          & (np.hypot(C[:, 0] - x, C[:, 1] - y) < P.STANDOFF_OD / 2))(x, y), "xyz") for x, y in tabs)
        nh1 = B.fix(lambda C, N: (np.abs(C[:, 2]) < 0.01) & (N[:, 2] < -0.9)
                    & (np.hypot(C[:, 0] - h1[0], C[:, 1] - h1[1]) < P.BOSS_D / 2), "z")
        if ledge:
            nh1 += B.fix(lambda C, N: (np.abs(C[:, 2]) < 0.01) & (N[:, 2] < -0.9) & (C[:, 0] >= ledge[0])
                         & (C[:, 0] <= ledge[1]) & (C[:, 1] >= ledge[2]), "z")
        sw = P.BTN_SW
        nl, a = B.load(lambda C, N: (np.abs(C[:, 2] - zt) < 0.01) & (N[:, 2] > 0.9) & (np.abs(C[:, 0] - bx) < sw[0] / 2)
                       & (np.abs(C[:, 1] - by) < sw[1] / 2), (0, 0, -PRESS))
        B.solve(E=E_FR4, nu=NU_FR4)
        w = -B.u[:, 2] * k
        bot = np.abs(B.p[:, 2]) < 0.01
        inb = lambda r: bot & (B.p[:, 0] >= r[0]) & (B.p[:, 0] <= r[1]) & (B.p[:, 1] >= r[2]) & (B.p[:, 1] <= r[3])  # noqa: E731
        loaded = np.unique(B.bf[(np.abs(B.bc[:, 2] - zt) < 0.01) & (np.abs(B.bc[:, 0] - bx) < sw[0] / 2)
                                & (np.abs(B.bc[:, 1] - by) < sw[1] / 2)])
        wb, wband, was = w[loaded].mean(), np.abs(w[inb(band)]).max(), np.abs(w[inb(asw)]).max()
        say(f"   {name:<5} ({bx:g}, {by:g}) {PRESS:g} N on {nl} facets ({a:.1f} mm2), fixed {nfix} + H1 {nh1}: "
            f"button {wb * 1e3:6.1f} um, electrode band max |w| {wband * 1e3:5.1f} um, AS5311 max |w| {was * 1e3:5.1f} um "
            f"(reaction {np.round(B.reaction, 2).tolist()} N)")
        result(f"press_{tag}{name}_button_um", wb * 1e3)
        result(f"press_{tag}{name}_band_um", wband * 1e3)
        result(f"press_{tag}{name}_as_um", was * 1e3)
        worst = {"button": max(worst["button"], wb), "band": max(worst["band"], wband), "as": max(worst["as"], was)}
    result("press_N", PRESS)
    result(f"press_{tag}button_um", worst["button"] * 1e3)
    result(f"press_{tag}band_um", worst["band"] * 1e3)
    result(f"press_{tag}as_um", worst["as"] * 1e3)


if __name__ == "__main__":
    say(__doc__.strip().splitlines()[0])
    say()
    body()
    gmsh.clear()
    board()
    say()
    say("Linear-elastic, isotropic; printed parts solid (6 walls).  Body strengths are the skill's PETG book values")
    say("(PA-CF is stronger), so the safety factors are conservative.  FR4 treated as isotropic E 20 GPa.")
    with open(os.path.join(HERE, "fea_slider_output.txt"), "w", newline="\n") as f:
        f.write("\n".join(LINES) + "\n")
    import figs                # noqa: E402
    png = figs.exploded_map(os.path.join(os.environ.get("TEMP", "/tmp"), "fea_body.npy"),
                            os.path.join(HERE, "renders", "fea_body.png"),
                            title=f"Slider body, PA-CF: back + Y preloads ({P.P_BACK:g} / {P.P_Y:g} N each), utilisation",
                            az=-120, el=-35)
    print("figure:", os.path.relpath(png, HERE))
