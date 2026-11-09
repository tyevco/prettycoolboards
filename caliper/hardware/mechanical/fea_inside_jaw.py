#!/usr/bin/env python3
"""FEA of the printed inside jaws under the 5 N measuring force: each one before and after its stiffening.

Uses the `print-stress` skill's mesher and element formulation (linear tets; ~/.claude/skills/print-stress/
scripts), which run on the Windows Python on the design machine, not in the WSL venv:

    py fea_inside_jaw.py [size]          # -> fea_inside_jaw_output.txt   (~15 min)

Why: the RF-relieved 2.4 mm plate (params.moving_inside_jaw_outline()) deflected 8.0 um/N on PA-CF at the
measuring face, ~48 um over a 2-8 N thumb spread.  The stiffened jaw (params.py "Stiffening") keeps the measuring
face, tapers the tip's back edge to IJ_TIP_BASE_W at its base and fills a shoulder block under it, with a
full-height gusset where the fixed inside jaw never reaches.

Geometry: from params.py.  The plate spans IJ_MOVING_Z (on the slider's bed: the layers are normal to z, so
the jaw bends in the layer plane); the gusset Z_BACK..IJ_GUSSET_Z1.
FEA frame as fea_jaw.py: X' = assembly z, Y' = u (measuring direction), Z' = y (along the jaw).
Materials, per element: PA-CF (E 4.2 GPa) except within RF_CLEAR + IJ_RF_MARGIN of the antenna area in plan,
which prints in unfilled PA through the slicer modifier (E_PA = 1.5 GPa, TVP); or PETG throughout (fit trials).
Datasheet E, no FDM knock-down (as fea_jaw.py).
Supports, two cases:
  rigid root  - the faces where the jaw meets the body (the step top y = STEP_Y1 - 0.1 and the housing's left
                face u = STEP_U1) are fixed; the body behind them is taken as rigid (as the first run did);
  local body  - the jaw fused to the body around its root (u 0.5..14, y 15..36: the step over the beam tunnel,
                the 1.2 wall beside the board cavity, the back web; the RF-modifier box in unfilled PA), fixed
                only at the two cut faces y 15 and u 14.  This includes the root's own give.
Load: 5 N in -u (the bore wall pushing the tip toward the fixed jaw), spread over the measuring face u = 0,
y IJ_TIP_Y0..IJ_TIP_Y1.

The fixed inside jaw (second part, RESULT FIXED lines): the old triangle (params.fixed_inside_jaw_outline(False):
the 3 mm tip on a sloping left edge) vs the stiffened jaw (params.py "Fixed inside jaw stiffening": a shoulder
block under the face and a full-depth gusset where the moving jaw never reaches), rigid root and with the fixed
block's top part; PA-CF and PETG.  Its own comment block below gives the supports.
"""
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.expanduser("~/.claude/skills/print-stress/scripts"))
from occ import Model          # noqa: E402
from stlfea import Part        # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import params as P             # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
size = float(sys.argv[1]) if len(sys.argv) > 1 else 0.3
LOAD = P.JAW_FORCE
ZB = P.Z_BACK
z1 = P.IJ_MOVING_Z[1]
yb = P.STEP_Y1 - 0.1
NU = 0.36
E_CF, E_PA, E_PETG = 4200.0, 1500.0, 1700.0
A = P.ANTENNA
AU0, AU1, AY0, AY1 = P.bu(A[0]), P.bu(A[2]), A[1], A[3]
R_RF = P.RF_CLEAR + P.IJ_RF_MARGIN
BODY_U1, BODY_Y0, BODY_Y1 = 14.0, 15.0, 36.0


def d_antenna(u, y):
    du = np.maximum(np.maximum(AU0 - u, u - AU1), 0.0)
    dy = np.maximum(np.maximum(AY0 - y, y - AY1), 0.0)
    return np.hypot(du, dy)


def solve(Pt, Ee):
    """stlfea.Part.solve with a Young's modulus per element (same B matrices, loads and supports)."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.linalg import spsolve
    p, t = Pt.p, Pt.t
    nn, ne = len(p), len(t)
    lam, mu = NU / ((1 + NU) * (1 - 2 * NU)), 1 / (2 * (1 + NU))
    D = np.zeros((6, 6)); D[:3, :3] = lam; D[np.arange(3), np.arange(3)] += 2 * mu
    D[np.arange(3, 6), np.arange(3, 6)] = mu
    X = p[t]
    M = np.concatenate([np.ones((ne, 4, 1)), X], axis=2)
    Minv = np.linalg.inv(M)
    vol = np.abs(np.linalg.det(M)) / 6
    G = Minv[:, 1:, :]
    B = np.zeros((ne, 6, 12))
    for i in range(4):
        gx, gy, gz = G[:, 0, i], G[:, 1, i], G[:, 2, i]
        B[:, 0, 3 * i] = gx; B[:, 1, 3 * i + 1] = gy; B[:, 2, 3 * i + 2] = gz
        B[:, 3, 3 * i] = gy; B[:, 3, 3 * i + 1] = gx
        B[:, 4, 3 * i + 1] = gz; B[:, 4, 3 * i + 2] = gy
        B[:, 5, 3 * i] = gz; B[:, 5, 3 * i + 2] = gx
    Ke = np.einsum('eki,kl,elj,e->eij', B, D, B, vol * Ee)
    dof = (3 * t[:, :, None] + np.arange(3)).reshape(ne, 12)
    rows = np.repeat(dof, 12, axis=1).ravel(); cols = np.tile(dof, 12).ravel()
    K = coo_matrix((Ke.ravel(), (rows, cols)), shape=(3 * nn, 3 * nn)).tocsr()
    f = np.zeros(3 * nn)
    for m, Fv in Pt.loads:
        w = Pt.ba[m] / Pt.ba[m].sum()
        for k, fac in zip(np.where(m)[0], w):
            for v in Pt.bf[k]:
                f[3 * v:3 * v + 3] += Fv * fac / 3
    fixed = set()
    for nodes, dofs, _ in Pt.fixed:
        for d in dofs:
            fixed.update(3 * nodes + 'xyz'.index(d))
    fixed = np.array(sorted(fixed))
    free = np.setdiff1d(np.arange(3 * nn), fixed)
    u = np.zeros(3 * nn)
    u[free] = spsolve(K[free][:, free], f[free])
    Pt.u = u.reshape(-1, 3)
    eps = np.einsum('eij,ej->ei', B, u[dof])
    Pt.sig = (eps @ D.T) * Ee[:, None]
    Pt.vol = vol
    r = f - K @ u
    Pt.reaction = np.array([r[0::3].sum(), r[1::3].sum(), r[2::3].sum()])
    return Pt


def build(pieces, body):
    """pieces: [(plan outline (u, y), z0, z1)]; body: also fuse the slider body round the root."""
    M = Model()
    sol = [M.profile_yz(pts, a, b) for pts, a, b in pieces]
    if body:
        o = M.o                                       # FEA frame: X' = z, Y' = u, Z' = y
        blk = [M.box(ZB, P.H_U0, BODY_Y0, P.Z_LID_IN - ZB, P.STEP_U1 - P.H_U0, P.STEP_Y1 - BODY_Y0),
               M.box(ZB, P.STEP_U1, BODY_Y0, P.Z_LID_IN - ZB, BODY_U1 - P.STEP_U1, BODY_Y1 - BODY_Y0)]
        b = M.fuse(blk)
        tunnel = M.box(P.CH_Z0, -1, BODY_Y0 - 1, P.CH_Z1 - P.CH_Z0, BODY_U1 + 2, P.CH_Y1 - BODY_Y0 + 1)
        cavity = M.box(P.CAV_FLOOR, P.BOARD_U0 - 0.4, BODY_Y0 - 1, P.Z_LID_IN + 1 - P.CAV_FLOOR,
                       BODY_U1 + 2 - P.BOARD_U0, P.BOARD_W + 0.4 - BODY_Y0 + 1)
        b = M.cut(b, [tunnel, cavity])
        sol.append(b)
        o.synchronize()
    if len(sol) > 1:
        M.fuse(sol)
    fine = [((ZB, -P.IJ_TIP_W - 0.5, yb - 0.5, P.IJ_GUSSET_Z1 + 0.5, P.STEP_U1 + 0.5, P.IJ_TIP_Y1 + 0.5), size),
            ((ZB, -P.IJ_TIP_W - 0.5, P.IJ_TIP_Y0 - 1.0, z1 + 0.5, 0.5, P.IJ_TIP_Y1 + 0.5), min(size, 0.25))]
    return M.mesh(size=0.9 if body else size, fine=fine)


def run(pieces, body):
    p, t = build(pieces, body)
    cen = p[t].mean(1)                                # (z, u, y)
    in_rf = d_antenna(cen[:, 1], cen[:, 2]) < R_RF   # the jaw's modifier zone (round corners)
    if body:                                          # the body's modifier box, u >= STEP_U1 (models.rf_modifier)
        in_rf |= (cen[:, 1] > P.STEP_U1) & (cen[:, 1] < AU1 + P.RF_CLEAR) & \
            (cen[:, 2] > AY0 - P.RF_CLEAR) & (cen[:, 2] < AY1 + P.RF_CLEAR)
    out = {}
    for mat, Ee in (("PA-CF", np.where(in_rf, E_PA, E_CF)), ("PETG", np.full(len(t), E_PETG))):
        Pt = Part(None, mesh=(p, t))
        if body:
            nfix = Pt.fix(lambda C, N: ((np.abs(C[:, 2] - BODY_Y0) < 0.02) & (N[:, 2] < -0.9))
                          | ((np.abs(C[:, 1] - BODY_U1) < 0.02) & (N[:, 1] > 0.9)), "xyz")
        else:
            nfix = Pt.fix(lambda C, N: ((np.abs(C[:, 2] - yb) < 0.02) & (N[:, 2] < -0.9))
                          | ((np.abs(C[:, 1] - P.STEP_U1) < 0.02) & (N[:, 1] > 0.9)), "xyz")
        face = lambda C, N: (np.abs(C[:, 1]) < 0.02) & (N[:, 1] > 0.9) & \
            (C[:, 2] > P.IJ_TIP_Y0) & (C[:, 2] < P.IJ_TIP_Y1)
        nl, area = Pt.load(face, (0.0, -LOAD, 0.0))
        solve(Pt, Ee)
        nodes = np.unique(Pt.bf[face(Pt.bc, Pt.bn)])
        d_face = -float(Pt.u[nodes, 1].mean())
        tip = Pt.p[:, 2] > P.IJ_TIP_Y1 - 0.05
        d_tip = -float(Pt.u[tip, 1].mean())
        rep = Pt.report(layer_normal=(1, 0, 0), s_inter=20.0, s_in=45.0)
        out[mat] = (d_face, d_tip, rep, nfix, nl, area)
    return len(t), len(p), int(in_rf.sum()), out


block = P.moving_inside_jaw_block_outline()
gusset = P.moving_inside_jaw_gusset_outline()
variants = (("2.4 plate (RF-relieved, before)", [(P.moving_inside_jaw_outline(), ZB, z1)]),
            ("shoulder block, plate only", [(block, ZB, z1)]),
            ("as built: shoulder block + gusset", [(block, ZB, z1), (gusset, ZB, P.IJ_GUSSET_Z1)]))
lines = [__doc__.strip().splitlines()[0], "",
         f"load {LOAD:g} N in -u on the measuring face u 0, y {P.IJ_TIP_Y0:g}..{P.IJ_TIP_Y1:g}; plate {z1 - ZB:.1f} "
         f"thick (z {ZB:g}..{z1:g}); as built: tip {P.IJ_TIP_W:g} wide at y {P.IJ_TIP_Y1:g}, {P.IJ_TIP_BASE_W:g} at the "
         f"shoulder y {P.IJ_TIP_Y0:g}, gusset to z "
         f"{P.IJ_GUSSET_Z1:g}, {P.IJ_FIXED_CLR:g} clear of the fixed jaw's flank; mesh {size} mm on the jaw",
         f"PA-CF E {E_CF:g}, unfilled PA E {E_PA:g} (TVP) within {R_RF:g} mm of the antenna; PETG E {E_PETG:g} throughout",
         "layer normal = assembly z (body printed back face down): bending is in the layer plane", ""]
res = {}
for body in (False, True):
    for name, pieces in variants:
        t0 = time.time()
        nt, npn, nrf, out = run(pieces, body)
        key = (name, body)
        res[key] = out
        lines.append(f"{name} [{'local body' if body else 'rigid root'}]: {nt} tets / {npn} nodes, "
                     f"{nrf} tets in unfilled PA ({time.time() - t0:.0f} s)")
        for mat, (df, dt, rep, nfix, nl, area) in out.items():
            lines.append(f"  {mat:<6} deflection at the face {df * 1000:6.2f} um ({df / LOAD * 1000:5.2f} um/N), at the tip "
                         f"{dt * 1000:6.2f} um; von Mises {rep['von_mises']} MPa (SF in-layer {rep['SF_in_layer']}), "
                         f"interlayer {rep['interlayer_tension']}/{rep['interlayer_shear']} MPa; reaction "
                         f"{rep['reaction_N']} N (fixed facets {nfix}, load facets {nl}, {area:.1f} mm2)")
        lines.append("")
        print("\n".join(lines[-4:]), flush=True)
for body in (False, True):
    for mat in ("PA-CF", "PETG"):
        d0 = res[(variants[0][0], body)][mat][0]
        d1 = res[(variants[1][0], body)][mat][0]
        d2 = res[(variants[2][0], body)][mat][0]
        lines.append(f"RESULT {mat} {'body' if body else 'rigid'}: plate {d0 * 1000:.2f} um ({d0 / LOAD * 1000:.2f} um/N), "
                     f"block {d1 * 1000:.2f} um, as built {d2 * 1000:.2f} um ({d2 / LOAD * 1000:.2f} um/N, "
                     f"{d0 / d2:.1f}x stiffer)")

# The fixed inside jaw (the reading sees both jaws): the old triangle vs the stiffened jaw (params.py, fixed inside
# jaw stiffening).  All PA-CF (its right edge, x 3.0, is 5.15 mm from the antenna at R = 0); 5 N in +x on its
# measuring face x 0 (normal -x), y IJ_TIP_Y0..IJ_TIP_Y1.  Same frame: X' = z, Y' = x, Z' = y.
#   rigid root  - the jaw's root face on the fixed block top (y FJ_Y1 - 0.1) fixed;
#   local body  - the jaw fused to the fixed block's top part (x FJ_X0..FJ_X1, y FIX_BODY_Y0..FJ_Y1, full depth, less
#                 the beam slot, the M3 bolt bores with their nut traps and the dowel bores, all left empty), fixed only
#                 at the cut face y FIX_BODY_Y0.  The beam does not support the plates between y 15 and 20 and the
#                 dowels carry nothing, so this is the soft bound for the block's give.
FIX_BODY_Y0 = 15.0
FSIZE = 0.4
fz0, fz1 = P.IJ_FIXED_Z
fyb = P.FJ_Y1 - 0.1


def build_fixed(pieces, body):
    M = Model()
    sol = [M.profile_yz(pts, a, b) for pts, a, b in pieces]
    if body:
        b = M.box(P.FJ_Z0, P.FJ_X0, FIX_BODY_Y0, P.FJ_Z1 - P.FJ_Z0, P.FJ_X1 - P.FJ_X0, P.FJ_Y1 - FIX_BODY_Y0)
        fit = 0.05
        slot = M.box(-P.BEAM_T - fit, P.BEAM_X0 - fit, FIX_BODY_Y0 - 1, P.BEAM_T + 2 * fit, 20.0,
                     P.BEAM_W + fit - FIX_BODY_Y0 + 1)
        holes = []
        for x, y in P.FJ_BOLTS:
            holes.append(M.cyl_axis(P.FJ_Z0 - 1, x, y, P.FJ_Z1 - P.FJ_Z0 + 2, 0, 0, P.M3_CLR / 2))
            # the hex trap as a round of the same area
            holes.append(M.cyl_axis(P.FJ_Z0 - 0.01, x, y, P.FJ_NUT_TRAP_DEPTH + 0.01, 0, 0,
                                    P.FJ_NUT_TRAP_AF * np.sqrt(np.sqrt(3) / 2 / np.pi)))
        for x, y in P.FJ_DOWELS:
            holes.append(M.cyl_axis(P.FJ_Z0 - 1, x, y, P.FJ_Z1 - P.FJ_Z0 + 2, 0, 0, P.DOWEL_D / 2))
        sol.append(M.cut(b, [slot] + holes))
        M.o.synchronize()
    if len(sol) > 1:
        M.fuse(sol)
    fine = [((P.FJ_Z0 - 0.5, P.FIXED_IJ_SHOULDER_X0 - 0.5, fyb - 0.5, P.FJ_Z1 + 0.5, P.IJ_TIP_W + 0.5,
              P.IJ_TIP_Y1 + 0.5), FSIZE),
            ((fz0 - 0.5, -0.5, P.IJ_TIP_Y0 - 1.0, fz1 + 0.5, P.IJ_TIP_W + 0.5, P.IJ_TIP_Y1 + 0.5), min(size, 0.25))]
    return M.mesh(size=0.9 if body else FSIZE, fine=fine)


def run_fixed(pieces, body):
    p, t = build_fixed(pieces, body)
    out = {}
    for mat, E in (("PA-CF", E_CF), ("PETG", E_PETG)):
        Pt = Part(None, mesh=(p, t))
        y_fix = FIX_BODY_Y0 if body else fyb
        nfix = Pt.fix(lambda C, N: (np.abs(C[:, 2] - y_fix) < 0.02) & (N[:, 2] < -0.9), "xyz")
        face = lambda C, N: (np.abs(C[:, 1]) < 0.02) & (N[:, 1] < -0.9) & \
            (C[:, 2] > P.IJ_TIP_Y0) & (C[:, 2] < P.IJ_TIP_Y1)
        nl, area = Pt.load(face, (0.0, LOAD, 0.0))
        solve(Pt, np.full(len(t), E))
        nodes = np.unique(Pt.bf[face(Pt.bc, Pt.bn)])
        d = float(Pt.u[nodes, 1].mean())
        tip = Pt.p[:, 2] > P.IJ_TIP_Y1 - 0.05
        d_tip = float(Pt.u[tip, 1].mean())
        rep = Pt.report(layer_normal=(1, 0, 0), s_inter=20.0, s_in=45.0)
        out[mat] = (d, d_tip, rep, nfix, nl, area)
    return len(t), len(p), out


fvariants = (("old triangle (before)", [(P.fixed_inside_jaw_outline(False), fz0, fz1)]),
             ("shoulder block, plate only", [(P.fixed_inside_jaw_outline(), fz0, fz1)]),
             ("as built: shoulder block + gusset", [(P.fixed_inside_jaw_outline(), fz0, fz1),
                                                    (P.fixed_inside_jaw_gusset_outline(), P.FJ_Z0, fz1)]))
lines += ["", "Fixed inside jaw: the old triangle vs the stiffened jaw (shoulder block x "
          f"{P.FIXED_IJ_SHOULDER_X0:g}..0 up to y {P.IJ_TIP_Y0:g}, full-depth gusset z {P.FJ_Z0:g}..{fz1:g} left of x "
          f"{P.FIXED_IJ_GUSSET_X1:g}); plate z {fz0:g}..{fz1:g}, tip {P.IJ_TIP_W:g} wide; 5 N in +x on the face x 0, "
          f"y {P.IJ_TIP_Y0:g}..{P.IJ_TIP_Y1:g}; all PA-CF (or PETG); mesh {FSIZE} on the jaw, {min(size, 0.25)} at the tip",
          f"local body: the fixed block x {P.FJ_X0:g}..{P.FJ_X1:g}, y {FIX_BODY_Y0:g}..{P.FJ_Y1:g} with the beam slot, "
          "bolt bores, nut traps and dowel bores empty, fixed at the cut face only (soft bound)", ""]
fres = {}
for body in (False, True):
    for name, pieces in fvariants:
        t0 = time.time()
        nt, npn, out = run_fixed(pieces, body)
        fres[(name, body)] = out
        lines.append(f"FIXED {name} [{'local body' if body else 'rigid root'}]: {nt} tets / {npn} nodes "
                     f"({time.time() - t0:.0f} s)")
        for mat, (d, dt, rep, nfix, nl, area) in out.items():
            lines.append(f"  {mat:<6} deflection at the face {d * 1000:6.2f} um ({d / LOAD * 1000:5.2f} um/N), at the tip "
                         f"{dt * 1000:6.2f} um; von Mises {rep['von_mises']} MPa (SF in-layer {rep['SF_in_layer']}), "
                         f"interlayer {rep['interlayer_tension']}/{rep['interlayer_shear']} MPa; reaction "
                         f"{rep['reaction_N']} N (fixed facets {nfix}, load facets {nl}, {area:.1f} mm2)")
        lines.append("")
        print("\n".join(lines[-4:]), flush=True)
for body in (False, True):
    for mat in ("PA-CF", "PETG"):
        d0, d1, d2 = (fres[(fvariants[i][0], body)][mat][0] for i in range(3))
        lines.append(f"RESULT FIXED {mat} {'body' if body else 'rigid'}: before {d0 * 1000:.2f} um ({d0 / LOAD * 1000:.2f} um/N), "
                     f"block {d1 * 1000:.2f} um, as built {d2 * 1000:.2f} um ({d2 / LOAD * 1000:.2f} um/N, "
                     f"{d0 / d2:.1f}x stiffer)")
lines += ["", "Strength numbers are the skill's PETG book values (45 in-layer, 20 interlayer).",
          "Linear tets run ~5 % stiff; every variant is meshed the same way, so the comparison holds."]
txt = "\n".join(lines) + "\n"
with open(os.path.join(HERE, "fea_inside_jaw_output.txt"), "w", newline="\n") as f:
    f.write(txt)
print(txt)
