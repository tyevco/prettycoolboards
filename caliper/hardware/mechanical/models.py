#!/usr/bin/env python3
"""Parametric B-rep model of the PrettyCool Caliper rev A (build123d / OpenCascade).

Every number comes from params.py; this file only says how the solids are put
together.  Parts are built in assembly coordinates (params.py docstring): the
beam and the fixed jaw in x, the slider parts in the slider frame u = x - R, so
`assembly(R)` just shifts the slider group by the reading R.

    python3 models.py          # build every part, print volume / mass / bbox

Parts (rev A unless noted):
    beam            ground flat stock, O1 or 1.4301; pockets, holes, stop pin hole
    fixed_jaw       printed PA-CF (rev B: 6061); outside + inside jaw, bolted + dowelled
    slider_body     printed PETG or PA-CF; straddles the beam, moving jaws integral
    slider_body_b   rev B: the same body in 6061-T6, tapped holes instead of inserts
    front_shell     printed lid: display window + bezel ribs, button holes, adjuster access
    back_cover      printed; battery door, back-gib plunger bosses, roller axle seat
    button_cap      printed (x3)
    thumb_roller    printed hub + NBR O-ring tyre
    back_gib, y_gib, ref_strip, front_pad   brass (C360) strips
"""
import math
from types import SimpleNamespace

from build123d import Box, Cylinder, Polygon, Pos, Rot, extrude

import params as P

RHO = {"steel": 7.85e-3, "brass": 8.50e-3, "6061": 2.70e-3, "PETG": 1.27e-3,
       "PA-CF": 1.17e-3, "FR4": 1.85e-3, "ferrite": 3.6e-3}   # g / mm^3


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------
def box(x0, x1, y0, y1, z0, z1):
    return Pos((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2) * Box(x1 - x0, y1 - y0, z1 - z0)


def zcyl(x, y, d, z0, z1):
    return Pos(x, y, (z0 + z1) / 2) * Cylinder(d / 2, z1 - z0)


def ycyl(x, z, d, y0, y1):
    return Pos(x, (y0 + y1) / 2, z) * (Rot(90, 0, 0) * Cylinder(d / 2, y1 - y0))


def prism(pts, z0, z1):
    """Extrude an XY outline from z0 to z1.  The outline is made counter-clockwise first:
    build123d extrudes along the face normal, so a clockwise outline would go to -z."""
    area2 = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]))
    if area2 < 0:
        pts = pts[::-1]
    return Pos(0, 0, z0) * extrude(Polygon(*pts, align=None), z1 - z0)


def hex_prism(x, y, af, z0, z1):
    r = af / math.sqrt(3)
    pts = [(x + r * math.cos(math.radians(30 + 60 * i)), y + r * math.sin(math.radians(30 + 60 * i)))
           for i in range(6)]
    return prism(pts, z0, z1)


def csk_hole(x, y, z_top, d, d_head, depth):
    """Through hole along -z from z_top, 90 degree countersink of d_head."""
    from build123d import Cone
    h = (d_head - d) / 2
    return zcyl(x, y, d, z_top - depth, z_top + 0.01) + \
        Pos(x, y, z_top - h / 2 + 0.005) * Cone(d / 2, d_head / 2, h + 0.01)


def slider_footprint(z0, z1, u0=P.H_U0):
    """Plan shape of the slider housing: low step at the left, full height after."""
    return box(u0, P.H_U1, P.H_Y0, P.STEP_Y1, z0, z1) + \
        box(P.STEP_U1, P.H_U1, P.STEP_Y1 - 0.01, P.H_Y1, z0, z1)


def bu(bx):
    """Board x -> slider u."""
    return P.BOARD_U0 + bx


# ---------------------------------------------------------------------------
# Beam
# ---------------------------------------------------------------------------
def beam():
    s = box(P.BEAM_X0, P.BEAM_X1, 0, P.BEAM_W, -P.BEAM_T, 0)
    # Tape channel (DEV-2) and scale pocket, both closed-ended (end radius = cutter)
    y0, y1 = P.TAPE_YC - P.TAPE_CH_W / 2, P.TAPE_YC + P.TAPE_CH_W / 2
    s -= box(P.TAPE_X0 - 1, P.TAPE_X1 + 1, y0, y1, -P.TAPE_CH_DEPTH, 0.1)
    sy0 = P.SCALE_Y0 - (P.SCALE_POCKET_W - P.SCALE_W) / 2
    s -= box(P.SCALE_X0 - 0.5, P.SCALE_X0 + P.SCALE_L + 0.5, sy0, sy0 + P.SCALE_POCKET_W,
             -P.SCALE_POCKET_DEPTH, 0.1)
    for x, y in P.FJ_BOLTS:
        s -= zcyl(x, y, P.M3_CLR, -P.BEAM_T - 1, 1)
    for x, y in P.FJ_DOWELS:
        s -= zcyl(x, y, P.DOWEL_D, -P.BEAM_T - 1, 1)
    s -= zcyl(stop_x(), P.STOP_Y, P.STOP_D, -P.BEAM_T - 1, 1)
    return s


def stop_x():
    """End-stop pin centre: the slider's right end face meets it at R = RANGE + OVERTRAVEL."""
    return P.RANGE + P.OVERTRAVEL + P.H_U1 + P.STOP_D / 2


def stop_pin():
    return zcyl(stop_x(), P.STOP_Y, P.STOP_D, -P.BEAM_T, P.STOP_PROUD)


# ---------------------------------------------------------------------------
# Jaw outlines (XY polygons).  Moving jaws in u, fixed jaws in x; both measuring
# faces are at 0.
# ---------------------------------------------------------------------------
def outside_jaw_pts(sign):
    """sign +1: moving jaw (material at u >= 0); -1: fixed jaw (material at x <= 0)."""
    rx, ry = P.JAW_RELIEF
    y_root = P.H_Y0          # face-on to the rail: +0.1 would poke under the back cover (jaw is 8 thick)
    pts = [(P.H_U0, y_root), (P.H_U0, P.H_Y0 - ry), (0, P.H_Y0 - ry), (0, -P.JAW_L),
           (P.JAW_TIP_W, -P.JAW_L), (P.JAW_ROOT_W, -8.0), (P.JAW_ROOT_W, y_root)]
    return [(sign * x, y) for x, y in pts]


def moving_inside_jaw_pts():
    t0, t1, w = P.IJ_TIP_Y0, P.IJ_TIP_Y1, P.IJ_TIP_W
    yb = P.STEP_Y1 - 0.1
    return [(-w, t1), (0, t1), (0, t0), (P.STEP_U1, 24.6), (P.STEP_U1, yb), (1.5, yb), (-w, t0)]


def fixed_inside_jaw_pts():
    t0, t1, w = P.IJ_TIP_Y0, P.IJ_TIP_Y1, P.IJ_TIP_W
    yb = P.FJ_Y1 - 0.1
    return [(0, t1), (w, t1), (w, t0), (-0.6, 24.2), (-0.6, yb), (-12.0, yb), (0, t0)]


# ---------------------------------------------------------------------------
# Fixed jaw
# ---------------------------------------------------------------------------
def fixed_jaw(rev="A"):
    s = box(P.FJ_X0, P.FJ_X1, P.FJ_Y0, P.FJ_Y1, P.FJ_Z0, P.FJ_Z1)
    s += prism(outside_jaw_pts(-1), P.FJ_Z0, P.JAW_Z1)     # down to the block back face: prints flat
    s += prism(fixed_inside_jaw_pts(), *P.IJ_FIXED_Z)
    fit = 0.05 if rev == "A" else 0.01
    s -= box(P.BEAM_X0 - fit, 1.0, -fit, P.BEAM_W + fit, -P.BEAM_T - fit, fit)
    for x, y in P.FJ_BOLTS:
        s -= zcyl(x, y, P.M3_CLR, P.FJ_Z0 - 1, P.FJ_Z1 + 1)
        # hex nut trap on the back (M3 nut 5.5 AF, 2.4 thick)
        s -= hex_prism(x, y, 5.6, P.FJ_Z0 - 0.01, P.FJ_Z0 + 2.5)
    for x, y in P.FJ_DOWELS:
        s -= zcyl(x, y, P.DOWEL_D - (0.05 if rev == "A" else 0.0), P.FJ_Z0 - 1, P.FJ_Z1 + 1)
    return s


# ---------------------------------------------------------------------------
# Slider body (rev A printed, rev B machined)
# ---------------------------------------------------------------------------
def _insert_or_tap(rev, x, y, z_open, depth, direction=-1, m=2):
    """Hole for a heat-set insert (rev A) or a tapped hole (rev B), entering at z_open
    and going `depth` in `direction` (-1 = toward -z)."""
    d = (P.INSERT_M2_D if m == 2 else P.INSERT_M3_D) if rev == "A" else (P.M2_TAP if m == 2 else P.M3_TAP)
    z_far = z_open + direction * depth
    return zcyl(x, y, d, min(z_open, z_far) - 0.01, max(z_open, z_far) + 0.01)


def slider_body(rev="A"):
    zb, zf = P.Z_COVER_IN, P.Z_LID_IN
    s = slider_footprint(zb, zf)
    # beam channel, all along
    s -= box(-1, P.H_U1 + 1, P.CH_Y0, P.CH_Y1, zb - 1, P.CH_Z1)
    # board + component cavity (open to the lid); floor 0.75 under the board in the band
    bu0, bu1 = P.BOARD_U0 - 0.4, P.BOARD_U0 + P.BOARD_L + 0.4
    s -= box(bu0, bu1, P.CH_Y0, P.BOARD_W + 0.4, P.BOARD_Z0 - 0.75, zf + 1)
    # board bosses (screws from the board top into inserts / tapped holes)
    for bx, by in P.BOARD_HOLES:
        s += zcyl(bu(bx), by, P.BOSS_D, P.BOARD_Z0 - 1.0, P.BOARD_Z0)
        s -= _insert_or_tap(rev, bu(bx), by, P.BOARD_Z0, P.INSERT_M2_L + 0.5)
    # battery pocket, open to the back cover
    b = P.BAT_POCKET
    s -= box(b["u0"], b["u1"], b["y0"], b["y1"], zb - 1, P.BOARD_Z0 - 0.75)
    # front pads: pocket + set-screw hole + insert from the lid side
    for u, y0, y1, ys in P.FPADS:
        s -= box(u - P.FPAD_LEN / 2 - 0.1, u + P.FPAD_LEN / 2 + 0.1, y0 - 0.15, y1 + 0.15,
                 -0.1, P.FPAD_T + 0.2)
        s -= zcyl(u, ys, P.M2_TAP, P.FPAD_T, zf + 0.1)
        if rev == "A":
            s -= _insert_or_tap(rev, u, ys, zf, P.INSERT_M2_L)
    # Y-gib plunger bores and the locking-screw bore, along -y from the top face
    for u in P.YGIB_PLUNGERS_U:
        s -= ycyl(u, P.GIB_Z, P.PLUNGER_BORE_D if rev == "A" else P.M2_TAP, P.CH_Y1 - 0.5, P.H_Y1 + 0.1)
        if rev == "A":
            s -= ycyl(u, P.GIB_Z, P.INSERT_M2_D, P.H_Y1 - P.INSERT_M2_L, P.H_Y1 + 0.1)
    s -= ycyl(P.LOCK_U, P.GIB_Z, P.LOCK_BORE_D if rev == "A" else P.M3_TAP, P.CH_Y1 - 0.5, P.H_Y1 + 0.1)
    if rev == "A":
        s -= ycyl(P.LOCK_U, P.GIB_Z, P.INSERT_M3_D, P.H_Y1 - P.INSERT_M3_L, P.H_Y1 + 0.1)
    # thumb-roller slot + axle hole
    s -= box(P.ROLLER_U - P.ROLLER_D / 2 - 0.4, P.H_U1 + 1, P.BEAM_W, P.ROLLER_Y + P.ROLLER_D / 2 + 0.4,
             P.ROLLER_Z0 - 0.35, P.ROLLER_Z1 + 0.35)
    s -= zcyl(P.ROLLER_U, P.ROLLER_Y, P.ROLLER_AXLE_D - (0.05 if rev == "A" else 0.0), zb - 0.1,
              P.ROLLER_Z1 + 0.35)
    # USB-C: receptacle opening through the 1.0 mm wall + cable-overmold relief
    s -= usb_cut()
    # lid screws and back-cover screws
    for x, y in P.LID_SCREWS:
        s -= _insert_or_tap(rev, x, y, zf, P.INSERT_M2_L + 0.5)
    for x, y in P.COVER_SCREWS:
        s -= _insert_or_tap(rev, x, y, zb, P.INSERT_M2_L + 0.5, direction=+1)
    # jaws
    s += prism(outside_jaw_pts(+1), P.JAW_Z0, P.JAW_Z1)
    s += prism(moving_inside_jaw_pts(), *P.IJ_MOVING_Z)
    # fillets are left to the slicer / the machinist: the model keeps sharp edges so
    # that every face here is a datum the drawing can name.
    return s


def usb_cut():
    wall_u = P.BOARD_U0 + P.BOARD_L
    zc, yc = P.USBC_ZC, P.USBC_YC
    hole = box(wall_u - 0.5, wall_u + 1.6, yc - 4.65, yc + 4.65, zc - 1.8, zc + 1.8)
    relief = box(wall_u + 1.5, P.H_U1 + 1, yc - P.USB_PLUG_W / 2, yc + P.USB_PLUG_W / 2,
                 zc - P.USB_PLUG_H / 2, zc + P.USB_PLUG_H / 2)
    return hole + relief


def slider_body_b():
    return slider_body("B")


# ---------------------------------------------------------------------------
# Front shell (lid) and back cover
# ---------------------------------------------------------------------------
def display_rect():
    """(u0, u1, y0, y1) of the display glass."""
    cx, cy = bu(P.DISP_CX), P.DISP_CY
    return cx - P.DISP_W / 2, cx + P.DISP_W / 2, cy - P.DISP_H / 2, cy + P.DISP_H / 2


def front_shell():
    z0, z1 = P.Z_LID_IN, P.Z_LID
    s = slider_footprint(z0, z1)
    cx, cy = bu(P.DISP_CX), P.DISP_CY + P.DISP_AA_DY
    m = P.DISP_WIN_MARGIN
    s -= box(cx - P.DISP_AA_W / 2 - m, cx + P.DISP_AA_W / 2 + m,
             cy - P.DISP_AA_H / 2 - m, cy + P.DISP_AA_H / 2 + m, z0 - 1, z1 + 1)
    # bezel: two end ribs locate the glass (glued to the lid underside); the long
    # sides have no rib so the lid stays clear of the MINI-1 beside the glass.
    u0, u1, y0, y1 = display_rect()
    zr = z0 - P.DISP_T
    for ya, yb in ((y0 - 0.15 - 1.2, y0 - 0.15), (y1 + 0.15, y1 + 0.15 + 1.2)):
        s += box(u0 - 0.15, u1 + 0.15, ya, yb, zr, z0 + 0.01)
    for bx, by in P.BUTTONS.values():
        s -= zcyl(bu(bx), by, P.CAP_HOLE_D, z0 - 1, z1 + 1)
    for u, _y0, _y1, ys in P.FPADS:
        s -= zcyl(u, ys, 2.0, z0 - 1, z1 + 1)           # hex-key access to the gap set screws
    for x, y in P.LID_SCREWS:
        s -= csk_hole(x, y, z1, P.M2_CLR, 4.0, z1 - z0 + 0.1)
    s -= usb_cut()
    return s


def back_cover():
    z0, z1 = P.Z_BACK, P.Z_COVER_IN
    s = slider_footprint(z0, z1)
    for u, y in P.BGIB_PLUNGERS:
        s += zcyl(u, y, 5.0, z0 - P.COVER_BOSS_H, z0 + 0.01)
        s -= zcyl(u, y, P.INSERT_M2_D, z0 - P.COVER_BOSS_H - 0.01, z1 - 0.6)
        s -= zcyl(u, y, P.PLUNGER_BORE_D, z0, z1 + 0.01)
    for x, y in P.COVER_SCREWS:
        s -= zcyl(x, y, P.M2_CLR, z0 - 1, z1 + 1)
        s -= Pos(x, y, z0 + 0.45) * Cylinder(2.0, 0.9)    # head counterbore 0.9 (low head)
    s -= zcyl(P.ROLLER_U, P.ROLLER_Y, P.ROLLER_AXLE_D - 0.05, z0 + 0.6, z1 + 0.01)  # blind axle seat
    return s


# ---------------------------------------------------------------------------
# Small printed parts
# ---------------------------------------------------------------------------
def button_cap():
    """Assembly pose: centred on (0, 0); bottom 0.1 over the switch actuator."""
    sw_top = P.BOARD_Z1 + P.BTN_SW[2]
    fu, fy, _ = P.CAP_FLANGE
    z_bot = sw_top + 0.1
    s = box(-fu / 2, fu / 2, -fy / 2, fy / 2, z_bot, P.Z_LID_IN)
    s += zcyl(0, 0, P.CAP_STEM_D, P.Z_LID_IN - 0.01, P.Z_LID + 0.6)
    return s


def thumb_roller():
    """Assembly pose: centred on its axle."""
    z0, z1 = P.ROLLER_Z0, P.ROLLER_Z1
    flange = (z1 - z0 - 1.0) / 2
    s = zcyl(0, 0, P.ROLLER_D - 1.0, z0, z0 + flange)
    s += zcyl(0, 0, P.ROLLER_HUB_D - 0.0, z0 + flange - 0.01, z1 - flange + 0.01)
    s += zcyl(0, 0, P.ROLLER_D - 1.0, z1 - flange, z1)
    s -= zcyl(0, 0, P.ROLLER_AXLE_D + 0.15, z0 - 1, z1 + 1)
    return s


def oring():
    from build123d import Torus
    r_cs = 0.4
    return Pos(0, 0, (P.ROLLER_Z0 + P.ROLLER_Z1) / 2) * Torus(P.ROLLER_HUB_D / 2 + r_cs, r_cs)


# ---------------------------------------------------------------------------
# Brass
# ---------------------------------------------------------------------------
def back_gib():
    g = P.BGIB
    z1 = -P.BEAM_T
    s = box(g["u0"], g["u1"], g["y0"], g["y1"], z1 - P.BGIB_T, z1)
    for u, y in P.BGIB_PLUNGERS:     # 90 deg dimples locate it on the plunger tips
        s -= zcyl(u, y, 1.2, z1 - P.BGIB_T - 0.01, z1 - P.BGIB_T + 0.4)
    return s


def y_gib():
    g = P.YGIB
    s = box(g["u0"], g["u1"], P.BEAM_W, P.BEAM_W + P.YGIB_T, g["z0"], g["z1"])
    for u in P.YGIB_PLUNGERS_U + [P.LOCK_U]:
        s -= ycyl(u, P.GIB_Z, 1.2, P.BEAM_W + P.YGIB_T - 0.4, P.BEAM_W + P.YGIB_T + 0.01)
    return s


def ref_strip():
    return box(P.H_U0, P.H_U1, -P.REF_STRIP_T, 0, -3.5, -0.5)


def front_pad():
    """One pad at the origin footprint (u centred on 0, y from 0); see FPADS for each."""
    return box(-P.FPAD_LEN / 2, P.FPAD_LEN / 2, 0, 1.5, 0, P.FPAD_T)


def front_pads():
    out = []
    for u, y0, y1, _ys in P.FPADS:
        out.append(box(u - P.FPAD_LEN / 2, u + P.FPAD_LEN / 2, y0, y1, 0, P.FPAD_T))
    return out


# ---------------------------------------------------------------------------
# Bought / reference items for the assembly view
# ---------------------------------------------------------------------------
def tape():
    y0 = P.TAPE_YC - P.TAPE_W / 2
    return box(P.TAPE_X0, P.TAPE_X1, y0, y0 + P.TAPE_W, P.TAPE_TOP - P.TAPE_T, P.TAPE_TOP)


def scale_pcb():
    return box(P.SCALE_X0, P.SCALE_X0 + P.SCALE_L, P.SCALE_Y0, P.SCALE_Y0 + P.SCALE_W,
               -P.SCALE_T, 0)


def display_module():
    u0, u1, y0, y1 = display_rect()
    return box(u0, u1, y0, y1, P.Z_LID_IN - P.DISP_T, P.Z_LID_IN)


def battery():
    b = P.BAT_POCKET
    uc, yc = (b["u0"] + b["u1"]) / 2, (b["y0"] + b["y1"]) / 2
    return box(uc - P.BAT_L / 2, uc + P.BAT_L / 2, yc - P.BAT_W / 2, yc + P.BAT_W / 2,
               P.Z_COVER_IN, P.Z_COVER_IN + P.BAT_T)


def lock_screw():
    s = ycyl(P.LOCK_U, P.GIB_Z, 3.0, P.BEAM_W + P.YGIB_T, P.H_Y1 + 1.0)
    s += ycyl(P.LOCK_U, P.GIB_Z, 7.0, P.H_Y1 + 1.0, P.H_Y1 + 4.0)   # knurled head, M3 thumbscrew
    return s


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
def _p(name, build, material, process, qty=1, orient=None, notes=""):
    return SimpleNamespace(name=name, build=build, material=material, process=process, qty=qty,
                           orient=orient, notes=notes)


# orient: rotation (rx, ry, rz) that puts the part in its print / machining pose
PARTS = {p.name: p for p in (
    _p("beam", beam, "steel", "ground flat stock 20x4, mill pockets + drill/ream", 1, (0, 0, 0),
       "O1 (hardened, ground) or 1.4301 ground flat; pockets per drawing beam_pockets"),
    _p("fixed_jaw", fixed_jaw, "PA-CF", "FDM, back face (z-) on the bed", 1, (0, 0, 0),
       "rev B: 6061-T6 or tool steel"),
    _p("slider_body", slider_body, "PETG", "FDM, back face (z-) on the bed", 1, (0, 0, 0),
       "PETG or PA-CF; 6 walls, 40 % gyroid; 15 M2 + 1 M3 heat-set inserts"),
    _p("slider_body_b", slider_body_b, "6061", "CNC 3-axis, two setups", 1, (0, 0, 0),
       "rev B, see drawing slider_body_b"),
    _p("front_shell", front_shell, "PETG", "FDM, top face (z+) on the bed (textured PEI)", 1, (180, 0, 0)),
    _p("back_cover", back_cover, "PETG", "FDM, inside face (z+) on the bed", 1, (180, 0, 0)),
    _p("button_cap", button_cap, "PETG", "FDM, flange on the bed", 3, (0, 0, 0)),
    _p("thumb_roller", thumb_roller, "PETG", "FDM, flat", 1, (0, 0, 0)),
    _p("back_gib", back_gib, "brass", "C360 1.2 strip, saw + file, 2 dimples", 1, (0, 0, 0)),
    _p("y_gib", y_gib, "brass", "C360 1.0 strip", 1, (0, 0, 0)),
    _p("ref_strip", ref_strip, "brass", "C360 1.0 strip, glued in the lower rail", 1, (0, 0, 0)),
    _p("front_pad", front_pad, "brass", "C360 1.0 sheet, 4 x 1.5 / 2.0", 4, (0, 0, 0)),
)}


def build(name):
    return PARTS[name].build()


def print_pose(name, solid=None):
    """The part rotated into its print/machining pose and dropped onto z = 0."""
    s = solid if solid is not None else build(name)
    rx, ry, rz = PARTS[name].orient or (0, 0, 0)
    s = Rot(rx, ry, rz) * s
    bb = s.bounding_box()
    return Pos(-bb.min.X, -bb.min.Y, -bb.min.Z) * s


def slider_group(R=0.0, with_hardware=True):
    """[(name, solid, colour)] for the slider in assembly coordinates."""
    T = Pos(R, 0, 0)
    out = [("slider_body", T * slider_body(), "body"),
           ("front_shell", T * front_shell(), "shell"),
           ("back_cover", T * back_cover(), "cover")]
    for k, (bx, by) in P.BUTTONS.items():
        out.append((f"button_cap_{k}", T * Pos(bu(bx), by, 0) * button_cap(), "cap"))
    out.append(("thumb_roller", T * Pos(P.ROLLER_U, P.ROLLER_Y, 0) * thumb_roller(), "cap"))
    out.append(("oring", T * Pos(P.ROLLER_U, P.ROLLER_Y, 0) * oring(), "rubber"))
    out += [("back_gib", T * back_gib(), "brass"), ("y_gib", T * y_gib(), "brass"),
            ("ref_strip", T * ref_strip(), "brass")]
    out += [(f"front_pad_{i}", T * p, "brass") for i, p in enumerate(front_pads())]
    if with_hardware:
        import board_envelope
        out += [("board", T * board_envelope.board(), "pcb"),
                ("board_parts", T * board_envelope.parts_solid(), "parts"),
                ("display", T * display_module(), "glass"),
                ("battery", T * battery(), "battery"),
                ("lock_screw", T * lock_screw(), "steel")]
    return out


def fixed_group():
    return [("beam", beam(), "steel"), ("fixed_jaw", fixed_jaw(), "jaw"),
            ("tape", tape(), "tape"), ("scale_pcb", scale_pcb(), "pcb"),
            ("stop_pin", stop_pin(), "steel")]


def assembly(R=0.0, with_hardware=True):
    return fixed_group() + slider_group(R, with_hardware)


if __name__ == "__main__":
    print(f"{'part':<15}{'material':<9}{'qty':>4}{'vol cm3':>9}{'mass g':>9}   bbox (mm)")
    for name, p in PARTS.items():
        s = p.build()
        bb = s.bounding_box()
        print(f"{name:<15}{p.material:<9}{p.qty:>4}{s.volume / 1000:>9.3f}{s.volume * RHO[p.material]:>9.2f}"
              f"   {bb.size.X:.2f} x {bb.size.Y:.2f} x {bb.size.Z:.2f}  valid={s.is_valid}")
