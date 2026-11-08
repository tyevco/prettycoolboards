#!/usr/bin/env python3
"""FEA of the printed moving outside jaw under the 5 N measuring force.

Uses the `print-stress` skill's solver (linear tets, scikit-fem style assembly in
numpy; ~/.claude/skills/print-stress/scripts), which runs on the Windows Python on
the design machine, not in the WSL venv:

    py fea_jaw.py [size] [fine]          # -> fea_jaw_output.txt, renders/fea_jaw.png

Geometry comes from params.py (outside_jaw_pts in models.py, re-typed here so the
script does not need build123d).  FEA frame: X' = assembly z (jaw thickness),
Y' = assembly u (measuring direction), Z' = assembly y (along the jaw).
Boundary: the lower rail's channel face (y = -1.0, where the rail meets the rest of
the body) is fixed; the jaw root and 20 mm of rail are modelled.  The rail's own
attachment to the towers is taken as rigid -- see calcs.py for the analytic check.
Load: 5 N in +u (the workpiece pushing the jaw open), spread over the measuring
face from 2 to 8 mm above the tip (the worst usual contact).
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
size = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0
fine = float(sys.argv[2]) if len(sys.argv) > 2 else 0.4

rx, ry = P.JAW_RELIEF
y_root = P.H_Y0 + 0.1
jaw = [(P.H_U0, y_root), (P.H_U0, P.H_Y0 - ry), (0, P.H_Y0 - ry), (0, -P.JAW_L),
       (P.JAW_TIP_W, -P.JAW_L), (P.JAW_ROOT_W, -8.0), (P.JAW_ROOT_W, y_root)]
z0, z1 = P.JAW_Z0, P.JAW_Z1
M = Model()
# profile_yz(pts, x0, x1): pts in (Y', Z') = (u, y), extruded along X' = z
j = M.profile_yz(jaw, z0, z1)
rail = M.box(P.Z_COVER_IN, P.H_U0, P.H_Y0, P.Z_LID_IN - P.Z_COVER_IN, 20.0 - P.H_U0, -1.0 - P.H_Y0)
s = M.fuse([j, rail])
p, t = M.mesh(size=size, fine=[((z0 - 1, -1, -12, z1 + 1, P.JAW_ROOT_W + 1, 0), fine),
                               ((z0 - 1, -1, -P.JAW_L - 1, z1 + 1, 4, -P.JAW_L + 10), fine)])
print(f"mesh: {len(t)} tets, {len(p)} nodes (size {size}/{fine})")

LOAD = P.JAW_FORCE
res = {}
for mat, E, nu in (("PETG", 1700.0, 0.38), ("PA-CF (PAHT-CF)", 4200.0, 0.36), ("6061-T6", 68900.0, 0.33)):
    Pt = Part(None, mesh=(p, t))
    nfix = Pt.fix(lambda C, N: (np.abs(C[:, 2] + 1.0) < 0.02) & (N[:, 2] > 0.9), "xyz")
    face = lambda C, N: (np.abs(C[:, 1]) < 0.02) & (N[:, 1] < -0.9) & (C[:, 2] > -P.JAW_L + 2) & (C[:, 2] < -P.JAW_L + 8)
    nl, area = Pt.load(face, (0.0, LOAD, 0.0))
    Pt.solve(E=E, nu=nu)
    m = face(Pt.bc, Pt.bn)
    nodes = np.unique(Pt.bf[m])
    d_load = float(Pt.u[nodes, 1].mean())
    tip = Pt.p[:, 2] < -P.JAW_L + 0.05
    d_tip = float(Pt.u[tip, 1].mean())
    rep = Pt.report(layer_normal=(1, 0, 0), s_inter=20.0, s_in=45.0)
    res[mat] = (d_load, d_tip, rep, nfix, nl, area)
    if mat == "PETG":
        np.save(os.path.join(os.environ.get("TEMP", "/tmp"), "fea_jaw_petg.npy"), dict(p=Pt.p, t=Pt.t, sig=Pt.sig, u=Pt.u), allow_pickle=True)

lines = [__doc__.strip().splitlines()[0], "",
         f"mesh {len(t)} tets / {len(p)} nodes, global {size} mm, fine {fine} mm at the root and the tip",
         f"load {LOAD} N in +u on the measuring face, y {-P.JAW_L + 2:.0f}..{-P.JAW_L + 8:.0f}; "
         f"jaw {P.JAW_Z1 - P.JAW_Z0:.1f} thick, root {P.JAW_ROOT_W} wide, tip {P.JAW_TIP_W}",
         "layer normal = assembly z (body printed back face down): bending is in the layer plane", ""]
for mat, (dl, dt, rep, nfix, nl, area) in res.items():
    lines.append(f"{mat:<16} deflection at the load {dl * 1000:7.1f} um, at the tip {dt * 1000:7.1f} um; "
                 f"von Mises {rep['von_mises']} MPa (SF in-layer {rep['SF_in_layer']}), "
                 f"interlayer {rep['interlayer_tension']}/{rep['interlayer_shear']} MPa; "
                 f"reaction {rep['reaction_N']} N (fixed facets {nfix}, load facets {nl}, {area:.1f} mm2)")
lines += ["", "Strength numbers are the skill's PETG book values (45 in-layer, 20 interlayer);",
          "for 6061 the SF is meaningless (yield 275 MPa).  Linear tets run ~5 % stiff."]
txt = "\n".join(lines) + "\n"
open(os.path.join(HERE, "fea_jaw_output.txt"), "w").write(txt)
print(txt)
try:
    import figs
    os.makedirs(os.path.join(HERE, "renders"), exist_ok=True)
    figs.exploded_map(os.path.join(os.environ.get("TEMP", "/tmp"), "fea_jaw_petg.npy"), os.path.join(HERE, "renders", "fea_jaw.png"))
except Exception as e:          # noqa: BLE001
    print("figure skipped:", e)
