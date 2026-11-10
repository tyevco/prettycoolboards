#!/usr/bin/env python3
"""Mechanical calculations for the PrettyCool Caliper rev A.

    python3 calcs.py            # -> calcs_output.txt (also printed)

 1. Jaw deflection under the measuring force: tapered-cantilever beam theory
    (bending + shear), printed PETG / PA-CF vs machined 6061, cross-checked
    against the FEA in fea_jaw.py (print-stress solver) when its output exists.
 2. Slider yaw under the measuring force: the Y-gib preload needed to keep the
    reference strip seated (plungers left of the battery pocket).
 3. Slider roll under a button / grip press: the back-gib preload needed to keep
    the front pads seated, the back web that carries it, and the sliding force
    the preloads cost (the trade-off table).
 4. Thermal error: steel beam vs printed body vs workpiece, board clamped at both tabs.
 5. Gap stack-up: the 0.15 mm capacitive gap and the 0.30 mm AS5311 gap, open loop
    and after the tab-clamp bedding (the new bow / clamp terms).
 6. AS5311 gap budget against SPEC 0.3 +/- 0.1.
 7. Envelope.
 8. Board under a button press (from fea_slider.py when its output exists).

Material data are typical datasheet values, cited inline; printed-part moduli
are knocked down 15 % for FDM (solid, 6 walls) -- TVP.
"""
import math
import os
import re

import params as P

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = []


def say(s=""):
    OUT.append(s)
    print(s)


def head(n, t):
    say()
    say(f"{n}. {t}")
    say("-" * (len(t) + 4))


# Materials ---------------------------------------------------------------
FDM_KD = 0.85
MAT = {
    # name: (E MPa, G MPa, alpha 1/K, source)
    "PETG": (1700 * FDM_KD, 1700 * FDM_KD / 2.76, 68e-6, "PETG E ~1.6-2.0 GPa, CTE 60-70 ppm/K (Bambu PETG HF / generic TDS)"),
    "PA-CF": (4200 * FDM_KD, 4200 * FDM_KD / 2.72, 30e-6, "Bambu PAHT-CF E(XY) 4.2 GPa; CTE XY ~25-40 ppm/K (fibre-aligned, TVP)"),
    "6061-T6": (68900, 26000, 23.6e-6, "ASM: E 68.9 GPa, G 26 GPa, CTE 23.6 ppm/K"),
}
ALPHA = {"O1": 11.0e-6, "1.4301": 16.0e-6, "FR4 (in-plane)": 16e-6, "steel workpiece": 11.5e-6}


# 1. Jaw deflection -------------------------------------------------------
def jaw_width(y):
    """Outside-jaw width in u at height y (params outline: 20 wide to y -8, then tapering to the tip)."""
    if y >= -8.0:
        return P.JAW_ROOT_W
    f = (y + 8.0) / (-P.JAW_L + 8.0)
    return P.JAW_ROOT_W + f * (P.JAW_TIP_W - P.JAW_ROOT_W)


def jaw_deflection(E, G, F, y_load, n=4000):
    """Tapered cantilever, root at the rail face y0, load F at y_load: bending + shear (kappa 5/6)."""
    t = P.JAW_Z1 - P.JAW_Z0
    y0 = P.H_Y0
    L = y0 - y_load
    db = ds = 0.0
    for i in range(n):
        s = (i + 0.5) / n * L            # distance from the root
        w = jaw_width(y0 - s)
        I, A = t * w ** 3 / 12, t * w
        m = F * (L - s)
        db += m * (L - s) / (E * I) * (L / n)
        ds += F / (5 / 6 * G * A) * (L / n)
    return db, ds


def fea_results():
    path = os.path.join(HERE, "fea_jaw_output.txt")
    if not os.path.exists(path):
        return None
    txt = open(path).read()
    res = {}
    for m in re.finditer(r"^(\S+).*?deflection at the load\s+([\d.]+) um, at the tip\s+([\d.]+) um", txt, re.M):
        res[m.group(1)] = (float(m.group(2)), float(m.group(3)))
    hdr = re.search(r"jaw ([\d.]+) thick, root ([\d.]+) wide, tip ([\d.]+)", txt)
    return res, hdr.groups() if hdr else None


head(1, "Outside-jaw deflection under the measuring force (beam theory)")
F = P.JAW_FORCE
say(f"Jaw: {P.JAW_Z1 - P.JAW_Z0:.1f} thick (z), {P.JAW_ROOT_W:.1f} wide (u) to y -8, tapering to {P.JAW_TIP_W} "
    f"at the tip y {-P.JAW_L:.0f}; root at the rail face y {P.H_Y0}.  F = {F} N in u.")
say("Printed bodies lie back face down, so the jaw bends in the layer plane (in-layer stiffness).")
say(f"{'material':<9}{'contact y':>10}{'bending um':>12}{'shear um':>10}{'total um':>10}{'um per N':>10}")
JAW = {}
for mat in ("PETG", "PA-CF", "6061-T6"):
    E, G, _a, _src = MAT[mat]
    for yl in (-37.0, -20.0, -6.0):
        b, s = jaw_deflection(E, G, F, yl)
        JAW[(mat, yl)] = b + s
        say(f"{mat:<9}{yl:>10.0f}{b * 1e3:>12.1f}{s * 1e3:>10.1f}{(b + s) * 1e3:>10.1f}{(b + s) * 1e3 / F:>10.2f}")
for mat in MAT:
    say(f"  {mat}: {MAT[mat][3]}")
fr = fea_results()
if fr:
    res, hdr = fr
    say(f"FEA cross-check (fea_jaw.py, print-stress solver, linear tets; jaw {hdr[0] if hdr else '?'} thick, "
        f"root {hdr[1] if hdr else '?'}; load spread over y -38..-32, so compare with y -37 / -35):")
    for k, (dl, dt) in res.items():
        say(f"  {k:<8} at the load {dl:6.1f} um, tip {dt:6.1f} um")
    say(f"  (the FEA uses the datasheet E without the {FDM_KD} FDM knock-down: scale it by 1/{FDM_KD} to compare)")
    if hdr and (abs(float(hdr[0]) - (P.JAW_Z1 - P.JAW_Z0)) > 0.01 or abs(float(hdr[1]) - P.JAW_ROOT_W) > 0.01):
        say("  NOTE: the FEA output is for a different jaw than params.py -- rerun `py fea_jaw.py`.")
say("What matters for accuracy is the force *variation*: a thumb gives 2-8 N, so the error band is")
for mat in ("PETG", "PA-CF", "6061-T6"):
    k = JAW[(mat, -37.0)] / F
    say(f"  {mat:<8} {k * 1e3:5.1f} um/N x 6 N spread = {k * 6e3:5.1f} um at the tip "
        f"({'inside' if k * 6 < 0.010 else 'NOT inside'} a 10 um share of the 30 um budget)")
say("Fixed jaw (printed PA-CF in rev A) has the same outline: add the same again for the closed loop.")
say("Mitigation in rev A: PA-CF body; measure near the jaw root; a constant-force (slip-clutch) roller is a rev B item.")

ij_path = os.path.join(HERE, "fea_inside_jaw_output.txt")
say()
say(f"Moving inside jaw (FEA only, fea_inside_jaw.py): tip {P.IJ_MOVING_Z[1] - P.IJ_MOVING_Z[0]:.1f} thick (z), "
    f"{P.IJ_TIP_W:g} wide at y {P.IJ_TIP_Y1:g} and {P.IJ_TIP_BASE_W:g} at y {P.IJ_TIP_Y0:g}, on a shoulder block with a "
    f"full-height gusset (to z {P.IJ_GUSSET_Z1:g}); {F:g} N in -u on the measuring face:")
IJ = {}
if os.path.exists(ij_path):
    ij = re.findall(r"^RESULT (\S+) (rigid|body): plate ([\d.]+) um \(([\d.]+) um/N\), block ([\d.]+) um, "
                    r"as built ([\d.]+) um \(([\d.]+) um/N, ([\d.]+)x stiffer\)", open(ij_path).read(), re.M)
    for mat, sup, d0, k0, d1, d2, k2, x in ij:
        IJ[(mat, sup)] = float(k2)
        say(f"  {mat:<6} {'rigid root' if sup == 'rigid' else 'with the local body':<20} 2.4 plate {float(k0):5.2f} um/N -> "
            f"as built {float(k2):5.2f} um/N ({x}x stiffer) = {float(k2) * 6:4.1f} um over a 6 N spread")
    say("  (datasheet E, no FDM knock-down; unfilled PA E 1.5 GPa (TVP) within 5.15 mm of the antenna.)")
    k = IJ.get(("PA-CF", "body"))
    if k is not None:
        say(f"  PA-CF with the local body: {k * 6:.1f} um over 2-8 N, "
            f"{'inside' if k * 6 <= 10.0 + 1e-9 else 'NOT inside'} a 10 um share of the 30 um budget"
            f"{'' if k <= 2.0 else ' (above the 2 um/N target)'}; /0.85 for the FDM knock-down: {k / FDM_KD * 6:.1f} um.")
    fx = re.findall(r"^RESULT FIXED (\S+) (rigid|body): before [\d.]+ um \(([\d.]+) um/N\), block [\d.]+ um, "
                    r"as built [\d.]+ um \(([\d.]+) um/N, ([\d.]+)x stiffer\)", open(ij_path).read(), re.M)
    FX = {}
    if fx:
        say(f"Fixed inside jaw (FEA, fea_inside_jaw.py): plate {P.IJ_FIXED_Z[1] - P.IJ_FIXED_Z[0]:.1f} thick, tip "
            f"{P.IJ_TIP_W:g} wide over its 6 mm, on a shoulder block x {P.FIXED_IJ_SHOULDER_X0:g}..0 up to y "
            f"{P.IJ_TIP_Y0:g} with a full-depth gusset left of x {P.FIXED_IJ_GUSSET_X1:g}; {F:g} N in +x on the face:")
        for mat, sup, k0, k2, x in fx:
            FX[(mat, sup)] = float(k2)
            say(f"  {mat:<6} {'rigid root' if sup == 'rigid' else 'with the local block':<21} old triangle {float(k0):5.2f} "
                f"um/N -> as built {float(k2):5.2f} um/N ({x}x stiffer) = {float(k2) * 6:4.1f} um over a 6 N spread")
        kf = FX.get(("PA-CF", "body"))
        if kf is not None:
            say(f"  PA-CF with the local block: {kf:.2f} um/N, {'at or under' if kf <= 1.0 + 1e-9 else 'above'} the 1.0 um/N "
                f"target; /0.85 for the FDM knock-down: {kf / FDM_KD:.2f} um/N.")
        if k is not None and kf is not None:
            kk = k + kf
            kr = IJ.get(("PA-CF", "rigid"), 0.0) + FX.get(("PA-CF", "rigid"), 0.0)
            say(f"  Inside reading, both jaws (PA-CF, local bodies): {kk:.2f} um/N -> {kk * 6:.1f} um over 2-8 N, "
                f"{kk / FDM_KD * 6:.1f} um with the FDM knock-down (rigid roots: {kr:.2f} um/N -> {kr * 6:.1f} um); "
                f"outside reading, both jaws: {2 * JAW[('PA-CF', -37.0)] / F * 6e3:.1f} um.")
else:
    say("  (fea_inside_jaw_output.txt missing: run `py fea_inside_jaw.py`)")



def fea_slider():
    """RESULT lines of fea_slider.py (body under the preloads, board under a button press)."""
    path = os.path.join(HERE, "fea_slider_output.txt")
    if not os.path.exists(path):
        return {}
    return {m.group(1): float(m.group(2)) for m in re.finditer(r"^RESULT (\S+) = ([-\d.eE+]+)", open(path).read(), re.M)}


FS = fea_slider()

# 2. Yaw ------------------------------------------------------------------
head(2, "Slider yaw under the measuring force -> Y-gib preload")
arm = 37.0
lever = sum(P.H_U1 - u for u in P.YGIB_PLUNGERS_U)          # strip lifts at its left end, pivots at u H_U1
lever_rev = sum(u - P.H_U0 for u in P.YGIB_PLUNGERS_U)      # the other sense: pivot at the left end
P_Y = P.P_Y
say(f"The workpiece pushes the moving jaw with F = {F} N (+x) at y -{arm:.0f}.  The equal and opposite drive")
say("force acts ABOVE the reference edge, so the two form a couple (the drive arm is not zero):")
say(f"{'drive applied at':<48}{'drive y':>8}{'M N.mm':>8}{'P min N':>9}")
PMIN = {}
for what, yd in (("thumb roller (friction drive at the beam edge)", P.BEAM_W),
                 ("thumb on the roller hub / axle", P.ROLLER_Y),
                 ("thumb on the right end face, mid-height", 35.0)):
    M_yaw = F * (arm + yd)
    PMIN[what] = M_yaw / lever
    say(f"{what:<48}{yd:>8.1f}{M_yaw:>8.0f}{PMIN[what]:>9.2f}")
say(f"(plunger levers about the strip's far end, u {P.H_U1}: sum {lever:.1f} mm; the strip lifts at its LEFT end.)")
p_roll = PMIN["thumb roller (friction drive at the beam edge)"]
p_end = PMIN["thumb on the right end face, mid-height"]
say(f"Design: {P_Y:.1f} N each at u {', '.join(f'{u:g}' for u in P.YGIB_PLUNGERS_U)} -> margin {P_Y / p_roll:.2f}x for "
    f"the roller drive, {P_Y / p_end:.2f}x for an end-face push.")
say("Review fix (D4 + sliding force): both plungers moved LEFT of the battery pocket (were u 16 / 58.5, sum")
say(f"  lever 81.5 mm, 6 N each).  The lever grows to {lever:.1f} mm, so {P_Y:.1f} N each keeps about the same")
say(f"  margin as 6 N did ({6.0 / (F * (arm + P.BEAM_W) / 81.5):.2f}x then, {P_Y / p_roll:.2f}x now) for a third less load.")
say("The other sense (strip lifting at its RIGHT end, pivot at the left end) has the short lever:")
F_lift = 2 * P_Y * (lever_rev / 2) / (P.H_U1 - P.H_U0)
say(f"  sum (u - {P.H_U0}) = {lever_rev:.1f} mm.  No measuring load makes that moment (outside and inside")
say("  measurements both lift the LEFT end), but a -y push on the slider's right end lifts the strip there")
say(f"  above F = 2 P (mean lever) / {P.H_U1 - P.H_U0:.1f} = {F_lift:.2f} N.  Trade-off accepted: a grip that")
say("  squeezes the slider's right end toward the jaws side (-y) with more than that tilts it while it lasts.")
say("While seated, the yaw stiffness is the strip on the rail (brass on 1.8 mm printed rail): "
    "elastic-foundation estimate < 0.1 um at the jaw tip -- negligible next to section 1.")

# 3. Roll / Z ---------------------------------------------------------------
head(3, "Slider roll under a press on the housing -> back-gib preload, back web, sliding force")
y_lo, y_hi = P.FPADS[0][3], P.FPADS[1][3]
y_sp = P.BGIB_PLUNGERS[0][1]
P_back = P.P_BACK
say(f"Back plungers at y {y_sp:g} (review fix: were y 10), lever {y_hi - y_sp:.1f} mm to the upper pad line y {y_hi}.")
NEED = {}
Y_GRIP = P.H_Y1 - 2.0       # a grip on the top edge (2026-11-09: the top face is at y 36.4, was 49.2; the old figure used y 40)
for what, fy, Fp in (("ZERO/HOLD/MODE press (tact 1.6 N + finger)", 31.0, 2.5), ("grip on the top edge", Y_GRIP, 5.0)):
    m = Fp * (fy - y_hi)
    need = m / (2 * (y_hi - y_sp))
    NEED[what] = need
    say(f"{what}: {Fp} N at y {fy:.0f} -> {m:.1f} N.mm about the upper pad line; the back plungers hold the lower "
        f"pads down if P >= {need:.2f} N each")
say(f"Design: back plungers {P_back} N each (was 4 N at y 10): margin {P_back / NEED['ZERO/HOLD/MODE press (tact 1.6 N + finger)']:.2f}x "
    f"for a button press.  A press beyond {2 * P_back * (y_hi - y_sp) / (Y_GRIP - y_hi):.1f} N at the top edge (y {Y_GRIP:.1f})")
say("lifts the lower pads -- the reading is then wrong only while pressed (the gaps open, they do not close).")
say()
say("Sliding force: every preload acts on two faces (the plunger side and the reaction side), brass on ground")
say("steel.  F = 2 x (2 P_back + 2 P_Y) x mu:")
N_tot = 2 * P_back + 2 * P_Y
N_old = 2 * 4.0 + 2 * 6.0
say(f"{'preloads':<34}{'N total':>8}{'mu 0.12':>9}{'mu 0.15':>9}{'mu 0.20':>9}")
for what, n in (("first model: back 4 N, Y 6 N", N_old), (f"now: back {P_back} N, Y {P_Y} N", N_tot)):
    say(f"{what:<34}{n:>8.1f}" + "".join(f"{2 * n * mu:>9.1f}" for mu in (0.12, 0.15, 0.20)))
say("Target 2-5 N (commercial calipers).  mu 0.12-0.15 is brass on ground steel with a light oil film, 0.20 the")
say("conservative value the first model used; dry brass on steel is 0.3-0.35 (keep the beam oiled).")
say(f"  -> {2 * N_tot * 0.15:.1f} N at mu 0.15 ({2 * N_tot * 0.20:.1f} N at 0.20), against {2 * N_old * 0.20:.1f} N before.")
say(f"  Trade-off: the lower back preload accepts a pad lift above {2 * P_back * (y_hi - y_sp) / (Y_GRIP - y_hi):.1f} N at the top edge (3.3 N at y 40")
say("  in the 52 mm housing; the lower top edge has a shorter lever), and the Y preload's margin stays above 1.3x; the")
say("  sliding force can be trimmed on the bench with the plunger set screws (0.4 mm per turn on the back plungers,")
say("  0.5 mm on the Y plungers' nylon M3).")
say("  O-ring roller rolling resistance is not included (TVP: measure; NBR at 0.15 squeeze is well under 0.5 N).")
say()
say("Back web (review fix a).  The back plungers now sit in the BODY's 3.2 back web, which closes the beam")
say("tunnel behind the beam and joins the lower rail to the upper body (the first model put them in a back cover")
say("screwed only at y 44: a 34 mm cantilever that bent 0.6-1.1 mm in PA-CF and lost the preload).")
t_w, L_w = P.WEB_T, P.CH_Y1 - P.CH_Y0
a_w = y_sp - P.CH_Y0
b_w = L_w - a_w
WEB = {}
for mat in ("PETG", "PA-CF"):
    E = MAT[mat][0]
    I = 20.0 * t_w ** 3 / 12
    d = P_back * a_w ** 3 * b_w ** 3 / (3 * E * I * L_w ** 3)       # fixed-fixed beam, point load
    WEB[mat] = d
    say(f"  {mat:<6} web {t_w:.1f} thick, span {L_w:.1f} (rail to upper body), load {P_back} N at {a_w:.1f} from the "
        f"rail, 20 mm strip: {d * 1e3:6.2f} um under the plunger")
if FS:
    say(f"  FEA (fea_slider.py, whole body from step/slider_body.step, PA-CF, both preloads): plunger seat moves "
        f"{FS.get('web_plunger_um', float('nan')):.2f} um relative to the pads; reaction check "
        f"{FS.get('body_reaction_N', float('nan')):.2f} N")
say("  -> the plunger travel (about 1 mm) is no longer used up by the housing: the preload is held as set.")

# 4. Thermal ---------------------------------------------------------------
head(4, "Thermal error (zeroed at T0, read at T0 + dT)")
u_as = P.BOARD_U0 + P.AS_X
u_cl = P.BOARD_U0 + P.TAB_HOLES[0][0]
u_cr = P.BOARD_U0 + P.TAB_HOLES[2][0]
say(f"The board is clamped at both end tabs (u {u_cl:g} and {u_cr:g}); the AS5311 sits at u {u_as:g}, "
    f"{'exactly' if abs(u_as - (u_cl + u_cr) / 2) < 0.01 else 'about'} midway.  FR4 (E 20 GPa, 34 mm2) is far stiffer")
say("than the printed towers in shear, so two bounds bracket the AS5311's position relative to the jaw face:")
say(f"  A: the board follows the left clamp:  {u_cl:g} mm of body + {u_as - u_cl:g} mm of FR4")
say(f"  B: the board stays centred between the clamps: {u_as:g} mm of body (the midpoint moves with the body)")
say("Fixed jaw: 5 mm of body from the dowels (x -5) to the face.  The tape is bonded to the beam (follows the steel).")
say(f"{'body':<9}{'beam':<8}{'A um/K':>8}{'B um/K':>8}{'fixed um/K':>11}{'scale um/K @150':>17}{'worst 10 K um':>14}")
for body in ("PETG", "PA-CF", "6061-T6"):
    a_b = MAT[body][2]
    fj = "PA-CF" if body != "6061-T6" else "6061-T6"
    for beam in ("O1", "1.4301"):
        a_s = ALPHA[beam]
        slA = (a_b * u_cl + ALPHA["FR4 (in-plane)"] * (u_as - u_cl) - a_s * u_as) * 1e3
        slB = (a_b * u_as - a_s * u_as) * 1e3
        fx = (MAT[fj][2] - a_s) * 5 * 1e3
        sc = (a_s - ALPHA["steel workpiece"]) * 150 * 1e3
        worst = (max(abs(slA), abs(slB)) + abs(fx) + abs(sc)) * 10
        say(f"{body:<9}{beam:<8}{slA:>8.3f}{slB:>8.3f}{fx:>11.3f}{sc:>17.3f}{worst:>14.1f}")
say("Hand heat warms the slider 5-10 K within minutes (TVP); re-zero after handling.  The scale term is the classic")
say("one: a 1.4301 beam reads a steel part short by 0.7 um/K at 150 mm -- O1 matches steel workpieces.")
say("Bound B is the realistic one for a stiff board in soft towers; the first model's chain (body to a boss at")
say("u 11, then FR4) no longer applies.  The difference between A and B is a reason to zero after warm-up.")

# 5. Gap stack-up ------------------------------------------------------------
head(5, "Gap stack-up (z, mm)")
say("Nominal chain (beam front face = 0):")
say(f"  board bottom (electrode face)        {P.BOARD_Z0:+.3f}   set by the tab clamps (bedded on 0.15 foil, section 6)")
say(f"  scale face                           {0.0:+.3f}   pocket {P.SCALE_POCKET_DEPTH:.2f} = PCB {P.SCALE_T} + adhesive {P.SCALE_ADH}")
say(f"  AS5311 face                          {P.BOARD_Z0 - P.AS_H_NOM:+.3f}   A nominal {P.AS_H_NOM}")
say(f"  tape face                            {P.TAPE_TOP:+.3f}   channel {P.TAPE_CH_DEPTH:.2f} deep - shim {P.TAPE_SHIM_NOM:.2f} (nominal A) - adhesive {P.TAPE_ADH} - tape {P.TAPE_T}")
say(f"  -> capacitive gap {P.BOARD_Z0:.3f}, magnetic gap {P.BOARD_Z0 - P.AS_H_NOM - P.TAPE_TOP:.3f}")
say(f"Board support (review fix b, SPEC D3): the board hangs from four SMT standoffs on its end tabs (u {u_cl:g} /"
    f" {u_cr:g}, y 5.5 / 14), 3.5-12 mm from the AS5311 and electrode rows, instead of bosses at y >= 24.5.")


def stack(rows):
    wc = sum(abs(r[1]) for r in rows)
    rss = math.sqrt(sum(r[1] ** 2 for r in rows))
    for name, tol, note in rows:
        say(f"    {name:<52} +/-{tol:.3f}  {note}")
    say(f"    {'worst case':<52} +/-{wc:.3f}")
    say(f"    {'RSS':<52} +/-{rss:.3f}")
    return wc, rss


# thermal of the clamp chain: pad (brass) + printed tower (pad pocket ceiling -> clamp ceiling) up,
# epoxy + washer + standoff (steel) down, FR4 thickness (z CTE ~60 ppm/K) down
tower = P.CLAMP_CEIL_Z - (P.FPAD_T + 0.2)
th = {}
for mat in ("PETG", "PA-CF"):
    th[mat] = 10 * abs(19e-6 * P.FPAD_T + MAT[mat][2] * tower - 60e-6 * P.EPOXY_GAP
                       - 12e-6 * (P.CLAMP_WASHER_T + P.STANDOFF_H) - 60e-6 * P.BOARD_T)
d_tower = FS.get("clamp_dz_um", 17.0) / 1000.0
say("\n(a) Capacitive gap, open loop (no per-unit work: printed clamp faces, no bedding):")
cap_raw = stack([
    ("scale PCB thickness (FR4 0.8 +/-10 %)", P.SCALE_T_TOL, "JLC standard; 'tight' option +/-0.05"),
    ("scale adhesive 467MP", 0.01, "3M datasheet 0.05 nominal"),
    ("scale pocket depth", 0.02, "machined"),
    ("board flatness over y 0..20 (inspected <= 0.03)", P.BOARD_FLATNESS / 2, "SPEC D3 fab note, half the band"),
    ("printed clamp face height (bridged, downward)", 0.10, "FDM +/-0.1"),
    ("front-pad pocket depth / tower height", 0.10, "FDM +/-0.1"),
    ("beam face flatness along travel", 0.01, "ground stock, drawing PCC-M-02"),
])
say("  -> the 0.15 gap cannot be built open-loop: the worst case is larger than the gap itself.")
say("\n(b) After the bedding (section 6: the board lies on 0.150 shim foil on the beam while the clamp washers")
say("    are bedded in epoxy; the clamp faces then copy the beam face, not the print):")
BOARD_SET = [   # board-bottom height over the beam face after the bedding (common to both gaps)
    ("shim foil thickness (steel shim stock 0.150)", 0.005, "+/-0.005 (TVP: measure the foil)"),
    ("beam face flatness along travel", 0.01, "drawing PCC-M-02"),
    ("board flatness residual (inspected <= 0.03)", P.BOARD_FLATNESS / 2, "SPEC D3; the foil holds the mean"),
    ("epoxy cure shrinkage (2 % of the 0.2 bed)", 0.02 * P.EPOXY_GAP, ""),
    ("thermal, clamp chain +/-10 K (PA-CF)", th["PA-CF"], f"pad + {tower:.2f} printed - washer/standoff/epoxy; PETG {th['PETG']:.4f}"),
    ("clamp-seat creep / relaxation (PA-CF)", 0.01, "TVP; PETG ~2x"),
    ("tower front under a +/-20 % preload drift", 0.2 * d_tower, f"{d_tower * 1e3:.1f} um at the clamp under the "
                                                                  f"design preload ({'FEA' if 'clamp_dz_um' in FS else 'estimate'})"),
]
say("  board-height terms (shared with the AS5311 gap):")
board_set = stack(BOARD_SET)
say("  plus the scale face:")
cap_set = stack(BOARD_SET + [
    ("scale thickness / flushness along its length", 0.02, "one PCB: thickness varies less than lot-to-lot (TVP)"),
])
say(f"  -> 0.15 +/- {cap_set[1]:.3f} RSS ({cap_set[0]:.3f} worst): the electrodes never touch, worst case included.")
say("     The first model (board on bosses at y >= 24.5, set by four set screws) had +/-0.044 RSS / 0.10 worst, with")
say("     an unsupported 7-24 mm overhang behind the 0.03 bow term.")
if "press_band_um" in FS:
    say(f"  Transient, not in the stack: a {FS.get('press_N', 3):.0f} N button press bends the board; with the button-band ledge")
    say(f"  the electrode band moves {FS['press_band_um']:.1f} um and the AS5311 {FS['press_as_um']:.1f} um (FEA, rigid ledge) plus the")
    say("  ledge's own few um (section 8); without the ledge it was "
        f"{FS.get('press_noledge_band_um', float('nan')):.0f} um.  It recovers when the button is released.")

# 6. AS5311 gap budget ---------------------------------------------------------
head(6, "AS5311 gap budget (SPEC 4.1: 0.30 +/- 0.10)")
say("(a) Open-loop (no measurement of the package or the tape; board height as bedded, 5b):")
mag_raw = stack([
    ("AS5311 seated height A (0.85..1.20, JEDEC MO-153)", (P.AS_H_MAX - P.AS_H_MIN) / 2, "centre 1.025 vs model 1.10"),
    ("solder standoff", P.SOLDER_STANDOFF_TOL, ""),
    ("tape thickness", P.TAPE_T_TOL, "TVP; Dexter quotes +/-0.15 on its strips"),
    ("tape adhesive", P.TAPE_ADH_TOL, ""),
    ("channel depth", 0.02, "machined, from face D"),
    ("board height as bedded (5b board terms, RSS)", board_set[1], ""),
])
say(f"  -> +/-{mag_raw[1]:.3f} RSS is {'inside' if mag_raw[1] <= P.MAG_GAP_TOL else 'OUTSIDE'} the +/-0.10 window.")
say("(b) With the per-unit measurement in assembly (mechanical 6): micrometer the board + AS5311 stack before")
say("    fitting (gives A to +/-0.005), depth-gauge the tape face below the beam face after bonding (+/-0.005),")
say(f"    and lay 0-{P.TAPE_SHIM_MAX:.2f} mm of Kapton shim (0.025 steps) under the tape so the predicted gap is 0.30.")
say(f"    The channel ({P.TAPE_CH_DEPTH:.2f} deep) gives 0.30 with NO shim at A max 1.20; a shim raises the tape,")
say(f"    so every shorter package can be corrected (A nominal 1.10 -> {P.TAPE_SHIM_NOM:.2f} shim, A min 0.85 -> "
    f"{P.TAPE_SHIM_MAX:.2f}).")
mag_rows = [
    ("A measured", 0.005, ""), ("tape face measured", 0.005, ""),
    ("shim step / 2", 0.0125, "0.025 steps"),
    ("tape thickness along the length", 0.02, "TVP"),
    ("channel depth along the length", 0.01, ""),
]
mag_set = stack(mag_rows + [("board height as bedded (5b board terms, RSS)", board_set[1], "")])
mag_wc = sum(r[1] for r in mag_rows) + board_set[0]
say(f"    {'true worst case (board terms worst case too)':<52} +/-{mag_wc:.3f}")
say(f"  -> 0.30 +/- {mag_set[1]:.3f} RSS: inside 0.2-0.4 ({P.MAG_GAP_TOL / mag_set[1]:.1f}x the RSS).")
say(f"     The true worst case, +/-{mag_wc:.3f}, is {'inside' if mag_wc <= P.MAG_GAP_TOL else 'OUTSIDE'} the window "
    "(the first model: +/-0.048 RSS, +/-0.13 worst, outside).")
say("Field check in firmware: AS5311 MagINCn / MagDECn both high = field in range; the SSI status bits")
say("(OCF, COF, LIN) flag an out-of-range gap.  Bring-up records them at R = 0, 75, 150.")

# 7. Envelope ------------------------------------------------------------------
head(7, "Envelope")
say(f"Housing envelope (u, y, z): {P.HOUSING_SIZE[0]:.1f} x {P.HOUSING_SIZE[1]:.1f} x {P.HOUSING_SIZE[2]:.1f} mm "
    f"(SPEC 7: <= 78 x 39.5 x 16 since the 2026-11-09 slim-down, was <= 78 x 52 x 16; roller included).")
say(f"Thumb roller rim at u {P.ROLLER_RIM_U:.1f} from the jaw face, {P.ROLLER_RIM_U - P.H_U1:.1f} proud of the end face "
    f"(review fix e: the end face moved 78.0 -> {P.H_U1}; the rim was at 78.6).")
say(f"The lock's knurled head stands {4.0:.0f} mm above the top face (like the jaws, an appendage outside the box).")
say(f"Tape channel {P.TAPE_CH_DEPTH:.2f} deep leaves {P.BEAM_T - P.TAPE_CH_DEPTH:.2f} mm of steel under it "
    f"(cross-section area drops to {(1 - (P.TAPE_CH_W * P.TAPE_CH_DEPTH) / (P.BEAM_W * P.BEAM_T)) * 100:.0f} %; "
    "bending is not loaded in use).")

# 8. Board under a button press -------------------------------------------------
head(8, "Board under a button press (board support check, SPEC D3 open item)")
say("The upper band is held only by H1 (18.75, 24); HOLD and MODE sit over the battery pocket, with no body under")
say("the board.  fea_slider.py solves the board (FR4, E 20 GPa, outline + tabs from board_parts.json) clamped at")
say("the four standoffs and resting on the H1 boss, 3 N on one switch footprint at a time; linear tets corrected")
say(f"x{FS.get('tet_correction', float('nan')):.2f} for bending (cantilever calibration in the same run):")
L = P.BTN_LEDGE
if FS:
    for tag, what in (("noledge_", "without a support under the button band"),
                      ("", f"with the button-band ledge (u {L['u0']:g}..{L['u1']:g}, y {L['y0']:g}..34.4, shimmed to contact; rigid in the FEA)")):
        say(f"  {what}:")
        for k in ("ZERO", "HOLD", "MODE"):
            if f"press_{tag}{k}_button_um" in FS:
                say(f"    {k:<5} at the button {FS[f'press_{tag}{k}_button_um']:6.1f} um, electrode band max "
                    f"{FS[f'press_{tag}{k}_band_um']:5.1f} um, AS5311 {FS[f'press_{tag}{k}_as_um']:5.1f} um")
    # the ledge is a printed cantilever, not rigid: add its own compliance
    E = MAT["PA-CF"][0]
    t_l, L_l, w_eff = P.BOARD_Z0 - L["low"] - P.CAV_FLOOR, P.BOARD_W + 0.4 - L["y0"], 10.0
    k_l = 3 * E * (w_eff * t_l ** 3 / 12) / L_l ** 3
    d_l = 3.0 / k_l
    say(f"  ledge compliance: {L_l:.1f} mm cantilever, {t_l:.2f} thick, ~{w_eff:g} mm engaged, PA-CF: {k_l:.0f} N/mm,"
        f" {d_l * 1e3:.1f} um under the full 3 N")
    say(f"  -> without the ledge the worst press (MODE) moved the electrode band {FS.get('press_noledge_band_um', float('nan')):.1f} um"
        f" toward the scale ({FS.get('press_noledge_band_um', 0) / 1.5:.0f} % of the 0.15 gap) and the button")
    say(f"     {FS.get('press_noledge_button_um', float('nan')):.0f} um; with it, about {FS.get('press_band_um', float('nan')):.1f} um + the ledge's"
        f" own {d_l * 1e3:.1f} um.  The ledge is kept.")
    say(f"  battery: cell top z {P.Z_POCKET + P.BAT_T:+.2f} (max envelope), {P.CAV_FLOOR - (P.Z_POCKET + P.BAT_T):.2f} below the ledge"
        " underside (swelling room); the board never reaches the cell.")
else:
    say("  (fea_slider_output.txt missing: run `py fea_slider.py`)")

# 9. Fixed-jaw bolts -----------------------------------------------------------
head(9, "Fixed-jaw bolts (M3 into a hex nut trap)")
end = P.FJ_Z1 - P.FJ_SCREW_L
seat = P.FJ_Z0 + P.FJ_NUT_TRAP_DEPTH
web = (-P.BEAM_T - 0.05) - seat
say(f"Block z {P.FJ_Z0:g}..{P.FJ_Z1:g} ({P.FJ_Z1 - P.FJ_Z0:.1f} thick); M3 x {P.FJ_SCREW_L:g}, head on the front face, "
    f"end at z {end:+.2f}.")
say(f"Nut trap {P.FJ_NUT_TRAP_AF} AF x {P.FJ_NUT_TRAP_DEPTH} deep from the back (was 2.5): nut seat z {seat:+.2f}, "
    f"nut ({P.NUT_M3_M} thick) to z {seat - P.NUT_M3_M:+.2f}.")
for m, L in ((P.NUT_M3_M, P.FJ_SCREW_L), (2.15, P.FJ_SCREW_L - 0.29), (P.NUT_M3_M, P.FJ_SCREW_L - 0.29)):
    e = P.FJ_Z1 - L
    say(f"  nut m {m:.2f}, screw {L:.2f} long: engaged {min(m, seat - e):.2f} of {m:.2f} mm "
        f"({min(m, seat - e) / 0.5:.1f} threads), screw end {e - P.FJ_Z0:.2f} under the back face")
say(f"  (ISO 4032 m 2.15-2.40; M3 x 10 length js15 +/-0.29.)  The old 2.5 deep trap engaged "
    f"{min(P.NUT_M3_M, P.FJ_Z0 + 2.5 - end):.2f} mm; an M3 x 12 would stand {P.FJ_Z0 - (P.FJ_Z1 - 12.0):.1f} proud of the back.")
say(f"Web between the trap floor and the beam slot (z {-P.BEAM_T - 0.05:+.2f}): {web:.2f} mm, in compression against the")
say("beam's back face (the nut clamps block-beam-block; nothing bends it).  It prints over the beam-slot bridge (section 8 of the docs).")

with open(os.path.join(HERE, "calcs_output.txt"), "w", newline="\n") as f:
    f.write("\n".join(OUT).lstrip() + "\n")
