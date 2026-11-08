#!/usr/bin/env python3
"""Mechanical calculations for the PrettyCool Caliper rev A.

    python3 calcs.py            # -> calcs_output.txt (also printed)

 1. Jaw deflection under the measuring force: tapered-cantilever beam theory
    (bending + shear), printed PETG / PA-CF vs machined 6061, cross-checked
    against the FEA in fea_jaw.py (print-stress solver) when its output exists.
 2. Slider yaw under the measuring force: the Y-gib preload needed to keep the
    reference strip seated.
 3. Slider roll under a button / grip press: the back-gib preload needed to keep
    the front pads seated (that is what holds both sensor gaps), and the
    sliding force that preload costs.
 4. Thermal error: steel beam vs printed body vs workpiece.
 5. Gap stack-up: the 0.15 mm capacitive gap and the 0.30 mm AS5311 gap, before
    and after the per-unit set-screw adjustment.
 6. AS5311 gap budget against SPEC 0.3 +/- 0.1.

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

# 2. Yaw ------------------------------------------------------------------
head(2, "Slider yaw under the measuring force -> Y-gib preload")
arm = 37.0
lever = sum(P.H_U1 - u for u in P.YGIB_PLUNGERS_U)
P_Y = 6.0                                  # design Y-plunger force, N each (review fix: was 4)
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
say(f"Design: {P_Y:.0f} N each -> margin {P_Y / p_roll:.2f}x for the roller drive, "
    f"{P_Y / PMIN['thumb on the right end face, mid-height']:.2f}x for an end-face push.")
say("  (Review fix: the first version sized this on the jaw force alone, 2.27 N minimum, and set 4 N;")
say(f"   with the drive couple 4 N is only {4.0 / p_roll:.2f}x and below the end-face case.  Spring rate TVP.)")
say("While seated, the yaw stiffness is the strip on the rail (brass on 1.8 mm printed rail): "
    "elastic-foundation estimate < 0.1 um at the jaw tip -- negligible next to section 1.")

# 3. Roll / Z ---------------------------------------------------------------
head(3, "Slider roll under a press on the housing -> back-gib preload and sliding force")
y_lo, y_hi = P.FPADS[0][3], P.FPADS[1][3]
y_sp = P.BGIB_PLUNGERS[0][1]
for what, fy, Fp in (("ZERO/HOLD/MODE press (tact 1.6 N + finger)", 31.0, 2.5), ("grip on the battery bay", 40.0, 5.0)):
    m = Fp * (fy - y_hi)
    need = m / (2 * (y_hi - y_sp))
    say(f"{what}: {Fp} N at y {fy:.0f} -> {m:.0f} N.mm about the upper pad line (y {y_hi}); the back plungers at "
        f"y {y_sp} hold the lower pads down if P >= {need:.2f} N each")
P_back = 4.0
mu = 0.20
N_tot = 2 * P_back + 2 * P_Y
say(f"Design: back plungers {P_back} N each.  A press beyond {2 * P_back * (y_hi - y_sp) / (40 - y_hi):.1f} N at the top "
    f"edge (y 40) lifts the lower pads -- the reading is then wrong only while pressed (the gaps open, they do not close).")
say(f"Sliding force: normal loads {2 * P_back:.0f} N (back) + {2 * P_Y:.0f} N (Y) on brass/steel, mu ~{mu} (lightly oiled "
    f"0.12-0.2) -> 2 x {N_tot:.0f} x {mu} = {2 * N_tot * mu:.1f} N to push the slider.  Typical caliper: 2-5 N.")
say("(each preload acts on two faces, the plunger side and the reaction side, hence the factor 2.)")

say()
say("Back-cover check (review addition).  The back plungers sit in the back cover; their reaction")
say(f"({2 * P_back:.0f} N total) pushes the cover AWAY from the body.  Over the beam channel (y -1 .. 21.2) there is")
say("no body material behind the beam, and the cover's only screws are at y 44, so the cover carries the")
say("load as a cantilever from the screw line to the plungers:")
L_c = P.COVER_SCREWS[0][1] - P.BGIB_PLUNGERS[0][1]
t_c = P.COVER_T
COVER_DEFL = {}
for mat in ("PETG", "PA-CF"):
    E = MAT[mat][0]
    for b, n, note in ((P.H_U1 - P.H_U0, 2, "whole width carries both plungers (lower bound)"),
                       (20.0, 1, "a 20 mm strip per plunger (closer to real)")):
        I = b * t_c ** 3 / 12
        d = (n * P_back) * L_c ** 3 / (3 * E * I)
        COVER_DEFL[(mat, n)] = d
        say(f"  {mat:<6} t {t_c:.1f}, L {L_c:.0f}, b {b:4.1f}: deflection {d:5.2f} mm   {note}")
say("  -> the plungers' ~1 mm working travel goes into bending the cover: the back-gib preload (and so the")
say("     pad seating of section 3) is NOT held as designed.  Needs a cover fastener near y 0..20 (doc section 4).")

# 4. Thermal ---------------------------------------------------------------
head(4, "Thermal error (zeroed at T0, read at T0 + dT)")
u_as = P.BOARD_U0 + P.AS_X
u_boss = P.BOARD_U0 + P.BOARD_HOLES[0][0]
say(f"Chain from the moving-jaw face to the AS5311: {u_boss:.0f} mm of body (jaw face -> board boss at u {u_boss:.0f}) "
    f"+ {u_as - u_boss:.0f} mm of FR4 (boss -> AS5311 at u {u_as:.0f}).")
say("Fixed jaw: 5 mm of body from the dowels (x -5) to the face.  The tape is bonded to the beam (follows the steel).")
say(f"{'body':<9}{'beam':<8}{'slider um/K':>12}{'fixed um/K':>11}{'scale um/K @150':>17}{'total 10 K um':>14}")
for body in ("PETG", "PA-CF", "6061-T6"):
    a_b = MAT[body][2]
    fj = "PA-CF" if body != "6061-T6" else "6061-T6"
    for beam in ("O1", "1.4301"):
        a_s = ALPHA[beam]
        sl = (a_b * u_boss + ALPHA["FR4 (in-plane)"] * (u_as - u_boss) - a_s * u_as) * 1e3
        fx = (MAT[fj][2] - a_s) * 5 * 1e3
        sc = (a_s - ALPHA["steel workpiece"]) * 150 * 1e3
        say(f"{body:<9}{beam:<8}{sl:>12.3f}{fx:>11.3f}{sc:>17.3f}{(abs(sl) + abs(fx) + abs(sc)) * 10:>14.1f}")
say("Hand heat warms the slider 5-10 K within minutes (TVP); re-zero after handling.  The scale term is the classic")
say("one: a 1.4301 beam reads a steel part short by 0.7 um/K at 150 mm -- O1 matches steel workpieces.")
say("A printed body also creeps: PETG under the gib springs relaxes over days, which changes preload, not position")
say("(the gaps are set by brass pads on set screws), but a creeping boss moves the board: use PA-CF for the body.")

# 5. Gap stack-up ------------------------------------------------------------
head(5, "Gap stack-up (z, mm)")
say("Nominal chain (beam front face = 0):")
say(f"  board bottom (electrode face)        {P.BOARD_Z0:+.3f}   set by the 4 front-pad set screws")
say(f"  scale face                           {0.0:+.3f}   pocket {P.SCALE_POCKET_DEPTH:.2f} = PCB {P.SCALE_T} + adhesive {P.SCALE_ADH}")
say(f"  AS5311 face                          {P.BOARD_Z0 - P.AS_H_NOM:+.3f}   A nominal {P.AS_H_NOM}")
say(f"  tape face                            {P.TAPE_TOP:+.3f}   channel {P.TAPE_CH_DEPTH:.2f} deep - shim {P.TAPE_SHIM_NOM:.2f} (nominal A) - adhesive {P.TAPE_ADH} - tape {P.TAPE_T}")
say(f"  -> capacitive gap {P.BOARD_Z0:.3f}, magnetic gap {P.BOARD_Z0 - P.AS_H_NOM - P.TAPE_TOP:.3f}")


def stack(rows):
    wc = sum(abs(r[1]) for r in rows)
    rss = math.sqrt(sum(r[1] ** 2 for r in rows))
    for name, tol, note in rows:
        say(f"    {name:<50} +/-{tol:.3f}  {note}")
    say(f"    {'worst case':<50} +/-{wc:.3f}")
    say(f"    {'RSS':<50} +/-{rss:.3f}")
    return wc, rss


say("\n(a) Capacitive gap, NOT adjusted per unit (pads set to a fixed screw depth):")
cap_raw = stack([
    ("scale PCB thickness (FR4 0.8 +/-10 %)", P.SCALE_T_TOL, "JLC standard; 'tight' option +/-0.05"),
    ("scale adhesive 467MP", 0.01, "3M datasheet 0.05 nominal"),
    ("scale pocket depth", 0.02, "machined"),
    ("board bow over the 40 x 5 mm electrode area", 0.03, "0.075 % of 40 mm, a tenth of the IPC limit (TVP)"),
    ("printed boss height / pad pocket depth", 0.10, "FDM +/-0.1"),
    ("beam face flatness along travel", 0.01, "ground stock, drawing PCC-M-02"),
])
say("  -> the 0.15 gap cannot be built open-loop: worst case is larger than the gap itself.")
say("  (board thickness is not in this chain: the board bottom seats on the bosses.)")
say("\n(b) Capacitive gap AFTER the per-unit setting (dial indicator on the board top, 2 um, beam face as datum):")
BOARD_SET = [   # board-bottom height over the beam face after the setting (common to both gaps)
    ("indicator + board-thickness micrometer", 0.005, ""),
    ("board bow over the electrode area (unmeasured)", 0.03, "TVP: 0.075 %/40 mm; IPC-6012 limit = 0.30"),
    ("beam face flatness along travel", 0.01, ""),
    ("set-screw setting resolution (M2 x 0.4, 10 deg)", 0.011, "0.4 x 10/360"),
    ("thermal: 5.4 mm PETG tower, +/-10 K", 5.4 * 68e-6 * 10, ""),
    ("pad / body creep and wear (PETG, first months)", 0.02, "TVP; PA-CF ~half"),
]
say("  board-height terms (shared with the AS5311 gap):")
board_set = stack(BOARD_SET)
say("  plus the scale face:")
cap_set = stack(BOARD_SET + [
    ("scale thickness / flushness along its length", 0.02, "one PCB: thickness varies less than lot-to-lot (TVP)"),
])
say(f"  -> 0.15 +/- {cap_set[1]:.3f} RSS ({cap_set[0]:.3f} worst): the electrodes never touch at RSS, but the")
say("     signal swings ~+/-30 % with gap along the travel -- fine for the experimental phase-ratio readout.")
say("  CAUTION: the board is held only by bosses at y >= 24.5; its lower band (electrodes y 10.6-17.5, AS5311")
say("  at y 6) overhangs 7-24 mm with no support.  The +/-0.03 bow term is a tenth of the IPC-6012 class 2")
say("  limit (0.75 %, i.e. 0.30 over the 40 mm electrode length, twice the gap): flatness-check every slider")
say("  board over its lower band and reject boards worse than 0.03 mm, or the electrodes can touch the scale.")

# 6. AS5311 gap budget ---------------------------------------------------------
head(6, "AS5311 gap budget (SPEC 4.1: 0.30 +/- 0.10)")
say("(a) Open-loop (no measurement of the package or the tape):")
mag_raw = stack([
    ("AS5311 seated height A (0.85..1.20, JEDEC MO-153)", (P.AS_H_MAX - P.AS_H_MIN) / 2, "centre 1.025 vs model 1.10"),
    ("solder standoff", P.SOLDER_STANDOFF_TOL, ""),
    ("tape thickness", P.TAPE_T_TOL, "TVP; Dexter quotes +/-0.15 on its strips"),
    ("tape adhesive", P.TAPE_ADH_TOL, ""),
    ("channel depth", 0.02, "machined, from face D"),
    ("board height as set (5b board terms, RSS)", board_set[1], "the board height is set for the cap gap"),
])
say(f"  -> +/-{mag_raw[1]:.3f} RSS is {'inside' if mag_raw[1] <= P.MAG_GAP_TOL else 'OUTSIDE'} the +/-0.10 window.")
say("(b) With the per-unit measurement in assembly (mechanical 6): micrometer the board + AS5311 stack before")
say("    fitting (gives A to +/-0.005), depth-gauge the tape face below the beam face after bonding (+/-0.005),")
say(f"    and lay 0-{P.TAPE_SHIM_MAX:.2f} mm of Kapton shim (0.025 steps) under the tape so the predicted gap is 0.30.")
say(f"    The channel ({P.TAPE_CH_DEPTH:.2f} deep) gives 0.30 with NO shim at A max 1.20; a shim raises the tape,")
say(f"    so every shorter package can be corrected (A nominal 1.10 -> {P.TAPE_SHIM_NOM:.2f} shim, A min 0.85 -> "
    f"{P.TAPE_SHIM_MAX:.2f}).")
say("    [Review fix: the first channel (1.90) gave 0.20 unshimmed at A max, which a shim can only make smaller.]")
mag_rows = [
    ("A measured", 0.005, ""), ("tape face measured", 0.005, ""),
    ("shim step / 2", 0.0125, "0.025 steps"),
    ("tape thickness along the length", 0.02, "TVP"),
    ("channel depth along the length", 0.01, ""),
]
mag_set = stack(mag_rows + [("board height as set (5b board terms, RSS)", board_set[1], "")])
mag_wc = sum(r[1] for r in mag_rows) + board_set[0]
say(f"    {'true worst case (board terms worst case too)':<50} +/-{mag_wc:.3f}")
say(f"  -> 0.30 +/- {mag_set[1]:.3f} RSS: inside 0.2-0.4 ({P.MAG_GAP_TOL / mag_set[1]:.1f}x the RSS).")
say(f"     The true worst case, +/-{mag_wc:.3f}, is {'inside' if mag_wc <= P.MAG_GAP_TOL else 'OUTSIDE'} the window, "
    "so tolerancing does not")
say("     guarantee the gap; the firmware field check below accepts or rejects each unit.")
say("     [Review fix: the first version put the 5b RSS into this worst-case sum and reported 0.003 margin.]")
say("Field check in firmware: AS5311 MagINCn / MagDECn both high = field in range; the SSI status bits")
say("(OCF, COF, LIN) flag an out-of-range gap.  Bring-up records them at R = 0, 75, 150.")

# Summary numbers --------------------------------------------------------------
head(7, "Envelope")
say(f"Housing envelope (u, y, z): {P.HOUSING_SIZE[0]:.1f} x {P.HOUSING_SIZE[1]:.1f} x {P.HOUSING_SIZE[2]:.1f} mm "
    f"(SPEC 7: <= 78 x 52 x 16); thumb roller rim at u {P.ROLLER_U + P.ROLLER_D / 2:.1f} (0.6 proud of the end face).")
say(f"SPEC 7 counts the roller in the 78 mm: the rim reaches u {P.ROLLER_U + P.ROLLER_D / 2:.1f}, "
    f"{P.ROLLER_U + P.ROLLER_D / 2 - 78.0:.1f} mm over (measured from the jaw face u 0).")
say(f"Tape channel {P.TAPE_CH_DEPTH:.2f} deep leaves {P.BEAM_T - P.TAPE_CH_DEPTH:.2f} mm of steel under it "
    f"(cross-section area drops to {(1 - (P.TAPE_CH_W * P.TAPE_CH_DEPTH) / (P.BEAM_W * P.BEAM_T)) * 100:.0f} %; "
    "bending is not loaded in use).")

with open(os.path.join(HERE, "calcs_output.txt"), "w") as f:
    f.write("\n".join(OUT).lstrip() + "\n")
