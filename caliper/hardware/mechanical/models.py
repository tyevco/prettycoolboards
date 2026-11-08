#!/usr/bin/env python3
"""Parametric B-rep model of the PrettyCool Caliper rev A (build123d / OpenCascade).

Every number comes from params.py; this file only says how the solids are put
together.  Parts are built in assembly coordinates (params.py docstring): the
beam and the fixed jaw in x, the slider parts in the slider frame u = x - R, so
`assembly(R)` just shifts the slider group by the reading R.

    python3 models.py          # build every part, print volume / mass / bbox

Parts (rev A unless noted):
    beam            ground flat stock, O1 or 1.4301; pockets, holes, tapped stop-screw hole
    fixed_jaw       printed PA-CF (rev B: 6061); outside + inside jaw, bolted + dowelled; prints front face down
    slider_body     printed PA-CF (PETG for fit trials); a closed tunnel round the beam with a 3.2 back
                    web, the moving jaws integral, the board's tab clamps in the two towers
    slider_body_b   rev B: the same body in 6061-T6, tapped holes instead of inserts
    front_shell     printed lid: landscape display window + bezel ribs, button holes, adjuster access
    battery_door    printed; closes the battery pocket in the body's back face (replaces the back cover)
    button_cap      printed (x3)
    thumb_roller    printed hub + NBR O-ring tyre
    back_gib, y_gib, ref_strip, front_pad   brass (C360) strips
"""
import math
from types import SimpleNamespace

from build123d import Box, Cone, Cylinder, Polygon, Pos, Rot, extrude

import params as P
from params import bu

RHO = {"steel": 7.85e-3, "brass": 8.50e-3, "6061": 2.70e-3, "PETG": 1.27e-3,
       "PA-CF": 1.17e-3, "FR4": 1.85e-3, "ferrite": 3.6e-3, "GFRP": 2.0e-3}   # g / mm^3


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


def csk_hole(x, y, z_face, d, d_head, depth, up=False):
    """Through hole with a 90 degree countersink of d_head at z_face, going `depth` into the part
    along -z (up=False: the face is a top face) or +z (up=True: the face is a bottom face)."""
    h = (d_head - d) / 2
    if not up:
        return zcyl(x, y, d, z_face - depth, z_face + 0.01) + \
            Pos(x, y, z_face - h / 2 + 0.005) * Cone(d / 2, d_head / 2, h + 0.01)
    return zcyl(x, y, d, z_face - 0.01, z_face + depth) + \
        Pos(x, y, z_face + h / 2 - 0.005) * Cone(d_head / 2, d / 2, h + 0.01)


def slider_footprint(z0, z1, u0=P.H_U0):
    """Plan shape of the slider housing: low step at the left, full height after."""
    return box(u0, P.H_U1, P.H_Y0, P.STEP_Y1, z0, z1) + \
        box(P.STEP_U1, P.H_U1, P.STEP_Y1 - 0.01, P.H_Y1, z0, z1)


# ---------------------------------------------------------------------------
# Beam
# ---------------------------------------------------------------------------
def beam():
    s = box(P.BEAM_X0, P.BEAM_X1, 0, P.BEAM_W, -P.BEAM_T, 0)
    # Tape channel (D2) and scale pocket, both closed-ended (end radius = cutter)
    y0, y1 = P.TAPE_YC - P.TAPE_CH_W / 2, P.TAPE_YC + P.TAPE_CH_W / 2
    s -= box(P.TAPE_X0 - 1, P.TAPE_X1 + 1, y0, y1, -P.TAPE_CH_DEPTH, 0.1)
    sy0 = P.SCALE_Y0 - (P.SCALE_POCKET_W - P.SCALE_W) / 2
    s -= box(P.SCALE_X0 - 0.5, P.SCALE_X0 + P.SCALE_L + 0.5, sy0, sy0 + P.SCALE_POCKET_W,
             -P.SCALE_POCKET_DEPTH, 0.1)
    for x, y in P.FJ_BOLTS:
        s -= zcyl(x, y, P.M3_CLR, -P.BEAM_T - 1, 1)
    for x, y in P.FJ_DOWELS:
        s -= zcyl(x, y, P.DOWEL_D, -P.BEAM_T - 1, 1)
    s -= zcyl(stop_x(), P.STOP_Y, P.M2_TAP, -P.BEAM_T - 1, 1)      # tapped M2 for the stop screw
    return s


def stop_x():
    """End-stop screw centre: the slider's right end face meets its head at R = RANGE + OVERTRAVEL."""
    return P.RANGE + P.OVERTRAVEL + P.H_U1 + P.STOP_D / 2


def stop_screw():
    """M2 x 6 socket-head cap screw: head proud of the front face, shank in the tapped beam hole."""
    return zcyl(stop_x(), P.STOP_Y, P.STOP_D, 0.0, P.STOP_PROUD) + \
        zcyl(stop_x(), P.STOP_Y, P.M2_TAP - 0.1, -P.BEAM_T, 0.01)


# ---------------------------------------------------------------------------
# Jaw outlines (XY polygons).  Moving jaws in u, fixed jaws in x; both measuring
# faces are at 0.
# ---------------------------------------------------------------------------
def outside_jaw_pts(sign):
    """sign +1: moving jaw (material at u >= 0); -1: fixed jaw (material at x <= 0)."""
    rx, ry = P.JAW_RELIEF
    y_root = P.H_Y0
    pts = [(P.H_U0, y_root), (P.H_U0, P.H_Y0 - ry), (0, P.H_Y0 - ry), (0, -P.JAW_L),
           (P.JAW_TIP_W, -P.JAW_L), (P.JAW_ROOT_W, -8.0), (P.JAW_ROOT_W, y_root)]
    return [(sign * x, y) for x, y in pts]


def moving_inside_jaw_pts():
    """Root flank relieved round the antenna corner (RF_CLEAR + IJ_RF_MARGIN), see params.py."""
    return P.moving_inside_jaw_outline()


def fixed_inside_jaw_pts():
    t0, t1, w = P.IJ_TIP_Y0, P.IJ_TIP_Y1, P.IJ_TIP_W
    yb = P.FJ_Y1 - 0.1
    return [(0, t1), (w, t1), (w, t0), (-0.6, 24.2), (-0.6, yb), (-12.0, yb), (0, t0)]


# ---------------------------------------------------------------------------
# Fixed jaw
# ---------------------------------------------------------------------------
def fixed_jaw(rev="A"):
    s = box(P.FJ_X0, P.FJ_X1, P.FJ_Y0, P.FJ_Y1, P.FJ_Z0, P.FJ_Z1)
    s += prism(outside_jaw_pts(-1), P.FJ_Z0, P.FJ_Z1)        # full block depth: prints flat either way
    s += prism(fixed_inside_jaw_pts(), *P.IJ_FIXED_Z)        # reaches the front face = the print bed
    fit = 0.05 if rev == "A" else 0.01
    s -= box(P.BEAM_X0 - fit, 1.0, -fit, P.BEAM_W + fit, -P.BEAM_T - fit, fit)
    for x, y in P.FJ_BOLTS:
        s -= zcyl(x, y, P.M3_CLR, P.FJ_Z0 - 1, P.FJ_Z1 + 1)
        # hex nut trap on the back (M3 nut 5.5 AF, 2.4 thick, seated 3.6 deep so the M3 x 10 passes
        # through it): faces up in the print pose
        s -= hex_prism(x, y, P.FJ_NUT_TRAP_AF, P.FJ_Z0 - 0.01, P.FJ_Z0 + P.FJ_NUT_TRAP_DEPTH)
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


def _pt_or_tap(rev, x, y, z_open, depth, direction=-1):
    """Pilot for a thread-forming screw (rev A) or a tapped M2 hole (rev B)."""
    d = P.PT_PILOT_D if rev == "A" else P.M2_TAP
    z_far = z_open + direction * depth
    return zcyl(x, y, d, min(z_open, z_far) - 0.01, max(z_open, z_far) + 0.01)


def tab_clamp_cuts():
    """Tower pockets for the board's end tabs, the standoffs + bedded washers, the clamp screws."""
    s = None
    for x0, y0, x1, y1 in P.BOARD_TABS:
        c = box(bu(x0) - P.TAB_POCKET_CLR_U, bu(x1) + P.TAB_POCKET_CLR_U, y0 - P.TAB_POCKET_CLR_Y,
                y1 + P.TAB_POCKET_CLR_Y, P.CH_Z1 - 0.2, P.TAB_POCKET_Z1)
        s = c if s is None else s + c
    for x, y in P.TAB_HOLES:
        u = bu(x)
        s += zcyl(u, y, P.STANDOFF_POCKET_D, P.TAB_POCKET_Z1 - 0.01, P.CLAMP_CEIL_Z)
        s += zcyl(u, y, P.M2_CLR, P.CLAMP_CEIL_Z - 0.01, P.Z_LID_IN + 0.1)
        s += zcyl(u, y, P.CLAMP_HEAD_D + 0.4, P.CLAMP_CBORE_Z, P.Z_LID_IN + 0.1)
    return s


def y_bores(rev="A"):
    """Y-gib plunger and lock bores along -y from the top face, with their inserts / taps at the top."""
    s = None
    for u, m in [(u, 2) for u in P.YGIB_PLUNGERS_U] + [(P.LOCK_U, 3)]:
        c = ycyl(u, P.GIB_Z, P.PLUNGER_BORE_D, P.CH_Y1 - 0.5, P.H_Y1 + 0.1)
        if rev == "A":
            d, L = (P.INSERT_M2_D, P.INSERT_M2_L) if m == 2 else (P.INSERT_M3_D, P.INSERT_M3_L)
        else:
            d, L = (P.M2_TAP, 4.0) if m == 2 else (P.M3_TAP, 5.0)
        c += ycyl(u, P.GIB_Z, d, P.H_Y1 - L, P.H_Y1 + 0.1)
        s = c if s is None else s + c
    return s


def body_cuts(rev="A"):
    """The slider body's cut features after the tunnel and the cavity, by name (the clash check
    measures the webs between them).  Each value is one solid (a union of the feature's cutters)."""
    zb, zf = P.Z_BACK, P.Z_LID_IN
    cuts = {}

    def add(name, solid):
        cuts[name] = solid if name not in cuts else cuts[name] + solid

    # end-tab clamps in the towers (SPEC D3)
    add("tab_clamps", tab_clamp_cuts())
    # H1 support boss pilot: M2 tapped in the print for a nylon screw
    hx, hy = P.H1
    top = P.BOARD_Z0 - P.H1_BOSS_LOW
    add("h1_pilot", zcyl(bu(hx), hy, P.M2_TAP, top - 4.0, top + 0.01))
    # battery pocket (cell z Z_WEB_IN .. +4, the door plug below it) and the door rebate in the back face
    b, d = P.BAT_POCKET, P.BAT_DOOR
    add("battery_pocket", box(b["u0"], b["u1"], b["y0"], b["y1"], zb + P.DOOR_T - 0.01, P.CAV_FLOOR + 0.01))
    add("door_rebate", box(d["u0"] - 0.1, d["u1"] + 0.1, d["y0"] - 0.1, P.H_Y1 + 1, zb - 1, zb + P.DOOR_T))
    for x, y in P.DOOR_SCREWS:
        add("door_pilots", _pt_or_tap(rev, x, y, zb + P.DOOR_T, 3.0, direction=+1))
    # battery-lead channel + JST plug relief past the board's top edge
    r = P.PLUG_RELIEF
    add("plug_relief", box(r["u0"], r["u1"], r["y0"], r["y1"], P.CAV_FLOOR - 0.01, zf + 1))
    # front pads: pocket + set-screw hole + insert from the lid side
    for u, y0, y1, ys in P.FPADS:
        add("pad_pockets", box(u - P.FPAD_LEN / 2 - 0.1, u + P.FPAD_LEN / 2 + 0.1, y0 - 0.15, y1 + 0.15,
                               -0.1, P.FPAD_T + 0.2))
        add("pad_screws", zcyl(u, ys, P.M2_TAP, P.FPAD_T, zf + 0.1))
        if rev == "A":
            add("pad_screws", _insert_or_tap(rev, u, ys, zf, P.INSERT_M2_L))
    # Y-gib plunger + lock bores (left of the battery pocket, GFRP pushers under the antenna)
    add("y_bores", y_bores(rev))
    # back-gib plungers in the back web: insert from the back face, bore through to the tunnel
    for u, y in P.BGIB_PLUNGERS:
        add("back_plungers", _insert_or_tap(rev, u, y, zb, P.INSERT_M2_L, direction=+1))
        add("back_plungers", zcyl(u, y, P.PLUNGER_BORE_D, zb - 0.01, P.Z_WEB_IN + 0.01))
    # thumb-roller slot + axle hole (through to the USB relief, so the pin can be pushed out)
    c = P.ROLLER_SLOT_CLR
    add("roller_slot", box(P.ROLLER_U - P.ROLLER_D / 2 - c, P.H_U1 + 1, P.BEAM_W, P.ROLLER_Y + P.ROLLER_D / 2 + c,
                           P.ROLLER_Z0 - c, P.ROLLER_Z1 + c))
    add("roller_axle", zcyl(P.ROLLER_U, P.ROLLER_Y, P.ROLLER_AXLE_D - (0.05 if rev == "A" else 0.0), zb - 0.1,
                            P.USBC_ZC - P.USB_PLUG_H / 2 + 0.2))
    # USB-C: receptacle opening through the 1.0 mm wall + cable-overmold relief
    add("usb", usb_cut())
    # lid screws
    for x, y, kind in P.LID_SCREWS:
        add("lid_screws", _pt_or_tap(rev, x, y, zf, 3.0) if kind == "pt"
            else _insert_or_tap(rev, x, y, zf, P.INSERT_M2_L + 0.5))
    return cuts


def tunnel_and_cavity():
    """The beam tunnel (closed at the back by the 3.2 web) and the board cavity (open to the lid,
    floor 0.75 under the board in the upper band)."""
    t = box(-1, P.H_U1 + 1, P.CH_Y0, P.CH_Y1, P.CH_Z0, P.CH_Z1)
    bu0, bu1 = P.BOARD_U0 - 0.4, P.BOARD_U0 + P.BOARD_L + 0.4
    return t + box(bu0, bu1, P.CH_Y0, P.BOARD_W + 0.4, P.CAV_FLOOR, P.Z_LID_IN + 1)


def slider_body(rev="A"):
    s = slider_footprint(P.Z_BACK, P.Z_LID_IN)
    s -= tunnel_and_cavity()
    hx, hy = P.H1                      # H1 support boss, printed 0.1 low and shimmed
    s += zcyl(bu(hx), hy, P.BOSS_D, P.CAV_FLOOR - 0.01, P.BOARD_Z0 - P.H1_BOSS_LOW)
    L = P.BTN_LEDGE                    # button-band ledge under the board's top edge, over the battery
    s += box(L["u0"], L["u1"], L["y0"], P.BOARD_W + 0.41, P.CAV_FLOOR, P.BOARD_Z0 - L["low"])
    for c in body_cuts(rev).values():
        s -= c
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


def rf_modifier():
    """Slicer modifier volume: body material within RF_CLEAR (plan) of the antenna area, to be printed in
    unfilled PA (PAHT) instead of PA-CF (SPEC D4).  The moving inside jaw (u < 6.4) stays PA-CF: its root
    flank is relieved round the antenna corner instead (params.IJ_RF_MARGIN), so it clears RF_CLEAR."""
    a = P.ANTENNA
    u0, u1 = max(bu(a[0]) - P.RF_CLEAR, P.STEP_U1), bu(a[2]) + P.RF_CLEAR
    return box(u0, u1, a[1] - P.RF_CLEAR, a[3] + P.RF_CLEAR, P.Z_BACK, P.Z_LID_IN) & slider_body()


# ---------------------------------------------------------------------------
# Front shell (lid) and battery door
# ---------------------------------------------------------------------------
def display_rect():
    """(u0, u1, y0, y1) of the display glass (landscape, SPEC D4)."""
    cx, cy = bu(P.DISP_CX), P.DISP_CY
    return cx - P.DISP_W / 2, cx + P.DISP_W / 2, cy - P.DISP_H / 2, cy + P.DISP_H / 2


def front_shell():
    z0, z1 = P.Z_LID_IN, P.Z_LID
    s = slider_footprint(z0, z1)
    cx, cy = bu(P.DISP_CX + P.DISP_AA_DX), P.DISP_CY
    m = P.DISP_WIN_MARGIN
    s -= box(cx - P.DISP_AA_W / 2 - m, cx + P.DISP_AA_W / 2 + m,
             cy - P.DISP_AA_H / 2 - m, cy + P.DISP_AA_H / 2 + m, z0 - 1, z1 + 1)
    # bezel: end ribs locate the glass in x, a rib along its top edge in y (glued to the lid underside).
    # SPEC 2.1 zone: x 16.15..49.85, y 1.2..20.15 (parts there <= 2.6 tall, top 3.75 < rib 3.80)
    u0, u1, y0, y1 = display_rect()
    zr = z0 - P.DISP_T
    s += box(u0 - P.DISP_RIB, u0, y0, y1, zr, z0 + 0.01)
    s += box(u1, u1 + P.DISP_RIB, y0, y1, zr, z0 + 0.01)
    s += box(u0 - P.DISP_RIB, u1 + P.DISP_RIB, y1, y1 + P.DISP_RIB, zr, z0 + 0.01)
    for bx, by in P.BUTTONS.values():
        s -= zcyl(bu(bx), by, P.CAP_HOLE_D, z0 - 1, z1 + 1)
    for u, _y0, _y1, ys in P.FPADS:
        s -= zcyl(u, ys, 2.0, z0 - 1, z1 + 1)           # hex-key access to the gap set screws
    for x, y, _k in P.LID_SCREWS:
        s -= csk_hole(x, y, z1, P.M2_CLR, 4.0, z1 - z0 + 0.1)
    for x, y in P.TAB_HOLES:                             # pockets for the tab-clamp screw heads
        s -= zcyl(bu(x), y, P.CLAMP_HEAD_D + 0.6, z0 - 0.01, z0 + P.LID_HEAD_POCKET)
    s -= zcyl(bu(P.PIEZO_PORT[0]), P.PIEZO_PORT[1], P.PIEZO_PORT_D, z0 - 1, z1 + 1)
    s -= zcyl(bu(P.LED_PIPE[0]), P.LED_PIPE[1], P.LED_PIPE_D, z0 - 1, z1 + 1)
    s -= usb_cut()
    return s


def battery_door():
    """2.0 flange in the body's back-face rebate + 1.2 plug that closes the pocket down to the cell."""
    d, b = P.BAT_DOOR, P.BAT_POCKET
    zb = P.Z_BACK
    s = box(d["u0"], d["u1"], d["y0"], P.H_Y1, zb, zb + P.DOOR_T)
    s += box(b["u0"] + 0.2, b["u1"] - 0.2, b["y0"] + 0.2, b["y1"] - 0.2, zb + P.DOOR_T - 0.01, P.Z_WEB_IN)
    for x, y in P.DOOR_SCREWS:
        s -= csk_hole(x, y, zb, P.M2_CLR, 4.0, P.DOOR_T + 0.1, up=True)
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
# Bought / reference items for the assembly view and the clash check
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
               P.Z_WEB_IN, P.Z_WEB_IN + P.BAT_T)


def pushers():
    """GFRP rods from the Y gib up to y PUSHER_TOP_Y (non-metallic under the antenna, SPEC D4)."""
    y0 = P.BEAM_W + P.YGIB_T
    out = [ycyl(u, P.GIB_Z, P.PUSHER_D, y0, P.PUSHER_TOP_Y) for u in P.YGIB_PLUNGERS_U]
    return out + [ycyl(P.LOCK_U, P.GIB_Z, P.PUSHER_D, y0, P.H_Y1 - P.INSERT_M3_L)]   # up to the M3 insert


def lock_screw():
    """M3 knurled thumb screw in the top insert; its tip pushes the GFRP lock rod."""
    s = ycyl(P.LOCK_U, P.GIB_Z, 2.5, P.H_Y1 - P.INSERT_M3_L + 0.05, P.H_Y1 + 1.0)
    s += ycyl(P.LOCK_U, P.GIB_Z, 6.0, P.H_Y1 + 1.0, P.H_Y1 + 4.0)   # knurled head
    return s


def plunger_hardware():
    """Steel set screws + springs of the two Y plungers (above PUSHER_TOP_Y) and the two back plungers."""
    out = [ycyl(u, P.GIB_Z, 1.5, P.PUSHER_TOP_Y + 0.5, P.H_Y1 - 0.2) for u in P.YGIB_PLUNGERS_U]
    out += [zcyl(u, y, 1.5, P.Z_BACK + 0.2, P.Z_WEB_IN - 0.05) for u, y in P.BGIB_PLUNGERS]
    return out


def tab_clamp_hardware():
    """Per tab hole: the bedded shim washer (on the standoff) and the low screw head."""
    out = []
    z_w = P.BOARD_Z1 + P.STANDOFF_H
    for x, y in P.TAB_HOLES:
        u = bu(x)
        out.append(zcyl(u, y, 4.0, z_w, z_w + P.CLAMP_WASHER_T) - zcyl(u, y, 2.2, z_w - 1, z_w + 1))
        out.append(zcyl(u, y, P.CLAMP_HEAD_D, P.CLAMP_CBORE_Z, P.CLAMP_CBORE_Z + P.CLAMP_HEAD_K))
    return out


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
def _p(name, build, material, process, qty=1, orient=None, notes=""):
    return SimpleNamespace(name=name, build=build, material=material, process=process, qty=qty,
                           orient=orient, notes=notes)


# orient: rotation (rx, ry, rz) that puts the part in its print / machining pose
PARTS = {p.name: p for p in (
    _p("beam", beam, "steel", "ground flat stock 20x4, mill pockets + drill/ream/tap", 1, (0, 0, 0),
       "O1 (hardened, ground) or 1.4301 ground flat; pockets per drawing beam_pockets"),
    _p("fixed_jaw", fixed_jaw, "PA-CF", "FDM, front face (z+) on the bed", 1, (180, 0, 0),
       "rev B: 6061-T6 or tool steel"),
    _p("slider_body", slider_body, "PA-CF", "FDM, back face (z-) on the bed", 1, (0, 0, 0),
       "PAHT-CF + unfilled-PA modifier near the antenna (or PETG for fit trials); 6 walls, 40 % gyroid; "
       "8 M2 + 1 M3 heat-set inserts, 4 thread-forming pilots"),
    _p("slider_body_b", slider_body_b, "6061", "CNC 3-axis, two setups", 1, (0, 0, 0),
       "rev B, see drawing slider_body_b (needs a non-metal window under the antenna, SPEC D4)"),
    _p("front_shell", front_shell, "PETG", "FDM, top face (z+) on the bed (textured PEI)", 1, (180, 0, 0)),
    _p("battery_door", battery_door, "PETG", "FDM, outside face (z-) on the bed (textured PEI)", 1, (0, 0, 0)),
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
           ("battery_door", T * battery_door(), "cover")]
    for k, (bx, by) in P.BUTTONS.items():
        out.append((f"button_cap_{k}", T * Pos(bu(bx), by, 0) * button_cap(), "cap"))
    out.append(("thumb_roller", T * Pos(P.ROLLER_U, P.ROLLER_Y, 0) * thumb_roller(), "cap"))
    out.append(("oring", T * Pos(P.ROLLER_U, P.ROLLER_Y, 0) * oring(), "rubber"))
    out += [("back_gib", T * back_gib(), "brass"), ("y_gib", T * y_gib(), "brass"),
            ("ref_strip", T * ref_strip(), "brass")]
    out += [(f"front_pad_{i}", T * p, "brass") for i, p in enumerate(front_pads())]
    names = [f"pusher_u{u:g}" for u in P.YGIB_PLUNGERS_U] + [f"pusher_lock_u{P.LOCK_U:g}"]
    out += [(n, T * p, "gfrp") for n, p in zip(names, pushers())]
    if with_hardware:
        import board_envelope
        out += [("board", T * board_envelope.board(), "pcb"),
                ("board_parts", T * board_envelope.parts_solid(), "parts"),
                ("display", T * display_module(), "glass"),
                ("battery", T * battery(), "battery"),
                ("lock_screw", T * lock_screw(), "steel")]
        out += [(f"tab_clamp_{i}", T * p, "steel") for i, p in enumerate(tab_clamp_hardware())]
        out += [(f"plunger_hw_{i}", T * p, "steel") for i, p in enumerate(plunger_hardware())]
    return out


def fixed_group():
    return [("beam", beam(), "steel"), ("fixed_jaw", fixed_jaw(), "jaw"),
            ("tape", tape(), "tape"), ("scale_pcb", scale_pcb(), "pcb"),
            ("stop_screw", stop_screw(), "steel")]


def assembly(R=0.0, with_hardware=True):
    return fixed_group() + slider_group(R, with_hardware)


if __name__ == "__main__":
    print(f"{'part':<15}{'material':<9}{'qty':>4}{'vol cm3':>9}{'mass g':>9}   bbox (mm)")
    for name, p in PARTS.items():
        s = p.build()
        bb = s.bounding_box()
        print(f"{name:<15}{p.material:<9}{p.qty:>4}{s.volume / 1000:>9.3f}{s.volume * RHO[p.material]:>9.2f}"
              f"   {bb.size.X:.2f} x {bb.size.Y:.2f} x {bb.size.Z:.2f}  valid={s.is_valid}")
