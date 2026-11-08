#!/usr/bin/env python3
"""FEA of the printed moving inside jaw under the 5 N measuring force: phase-3 outline vs the RF-relieved one.

Uses the `print-stress` skill's solver (linear tets; ~/.claude/skills/print-stress/scripts),
which runs on the Windows Python on the design machine, not in the WSL venv:

    py fea_inside_jaw.py [size]          # -> fea_inside_jaw_output.txt

Why: the module moved 0.45 mm toward the jaw in layout and the jaw's root flank came to 4.70 mm
(plan) from the antenna, inside SPEC D4's 5 mm for carbon fill.  params.moving_inside_jaw_outline()
now relieves the flank on an R (RF_CLEAR + IJ_RF_MARGIN) arc round the antenna corner and starts the
root at the housing end face (u 0.5, was 1.5).  This run checks that the change costs no stiffness
at the measuring face.

Geometry: both outlines from params.py, extruded over IJ_MOVING_Z (2.4 thick, printed on the
slider's bed: the layers are normal to z, so the jaw bends in the layer plane).
FEA frame as fea_jaw.py: X' = assembly z, Y' = u (measuring direction), Z' = y (along the jaw).
Boundary: the faces where the jaw meets the body (the root edge y = STEP_Y1 - 0.1 and the side
u = STEP_U1 up to y 24.6) are fixed; the body behind them is taken as rigid.
Load: 5 N in -u (the bore wall pushing the tip toward the fixed jaw), spread over the measuring
face u = 0, y IJ_TIP_Y0..IJ_TIP_Y1.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.expanduser("~/.claude/skills/print-stress/scripts"))
from occ import Model          # noqa: E402
from stlfea import Part        # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import params as P             # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
size = float(sys.argv[1]) if len(sys.argv) > 1 else 0.22
LOAD = P.JAW_FORCE
z0, z1 = P.IJ_MOVING_Z
yb = P.STEP_Y1 - 0.1
MATS = (("PETG", 1700.0, 0.38), ("PA-CF (PAHT-CF)", 4200.0, 0.36))


def run(pts):
    M = Model()
    M.profile_yz(pts, z0, z1)
    p, t = M.mesh(size=size)
    out = {}
    for mat, E, nu in MATS:
        Pt = Part(None, mesh=(p, t))
        nfix = Pt.fix(lambda C, N: ((np.abs(C[:, 2] - yb) < 0.02) & (N[:, 2] < -0.9))
                      | ((np.abs(C[:, 1] - P.STEP_U1) < 0.02) & (N[:, 1] > 0.9)), "xyz")
        face = lambda C, N: (np.abs(C[:, 1]) < 0.02) & (N[:, 1] > 0.9) & \
            (C[:, 2] > P.IJ_TIP_Y0) & (C[:, 2] < P.IJ_TIP_Y1)
        nl, area = Pt.load(face, (0.0, -LOAD, 0.0))
        Pt.solve(E=E, nu=nu)
        nodes = np.unique(Pt.bf[face(Pt.bc, Pt.bn)])
        d_face = -float(Pt.u[nodes, 1].mean())
        tip = Pt.p[:, 2] > P.IJ_TIP_Y1 - 0.05
        d_tip = -float(Pt.u[tip, 1].mean())
        rep = Pt.report(layer_normal=(1, 0, 0), s_inter=20.0, s_in=45.0)
        out[mat] = (d_face, d_tip, rep, nfix, nl, area)
    return len(t), len(p), out


variants = (("phase 3 (straight flank, root from u 1.5)", P.moving_inside_jaw_outline(rf_relief=False)),
            (f"arc only (R {P.RF_CLEAR + P.IJ_RF_MARGIN:g} arc, root from u {P.IJ_ROOT_U0_OLD:g})",
             P.moving_inside_jaw_outline(root_u0=P.IJ_ROOT_U0_OLD)),
            (f"RF relief as built (R {P.RF_CLEAR + P.IJ_RF_MARGIN:g} arc, root from u {P.IJ_ROOT_U0:g})",
             P.moving_inside_jaw_outline()))
lines = [__doc__.strip().splitlines()[0], "",
         f"load {LOAD:g} N in -u on the measuring face u 0, y {P.IJ_TIP_Y0:g}..{P.IJ_TIP_Y1:g}; "
         f"jaw {z1 - z0:.1f} thick (z {z0:g}..{z1:g}), tip {P.IJ_TIP_W:g} wide; global mesh {size} mm",
         "layer normal = assembly z (body printed back face down): bending is in the layer plane", ""]
res = {}
for name, pts in variants:
    nt, npn, out = run(pts)
    res[name] = out
    lines.append(f"{name}: {nt} tets / {npn} nodes")
    for mat, (df, dt, rep, nfix, nl, area) in out.items():
        lines.append(f"  {mat:<16} deflection at the face {df * 1000:6.2f} um, at the tip {dt * 1000:6.2f} um; "
                     f"von Mises {rep['von_mises']} MPa (SF in-layer {rep['SF_in_layer']}), "
                     f"interlayer {rep['interlayer_tension']}/{rep['interlayer_shear']} MPa; "
                     f"reaction {rep['reaction_N']} N (fixed facets {nfix}, load facets {nl}, {area:.1f} mm2)")
    lines.append("")
(_a, ra), (_b, rb), (_c, rc) = res.items()
for mat, _E, _nu in MATS:
    da, db, dc = ra[mat][0], rb[mat][0], rc[mat][0]
    lines.append(f"RESULT {mat.split()[0]} face deflection: phase 3 {da * 1000:.2f} um, arc only {db * 1000:.2f} um "
                 f"({(db / da - 1) * 100:+.1f} %), as built {dc * 1000:.2f} um ({(dc / da - 1) * 100:+.1f} %); "
                 f"{dc / LOAD * 1000:.1f} um/N")
lines += ["", "Strength numbers are the skill's PETG book values (45 in-layer, 20 interlayer).",
          "Linear tets run ~5 % stiff; both variants are meshed the same way, so the comparison holds."]
txt = "\n".join(lines) + "\n"
with open(os.path.join(HERE, "fea_inside_jaw_output.txt"), "w", newline="\n") as f:
    f.write(txt)
print(txt)
