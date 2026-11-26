"""Concept geometry of the keyboard's key and control mechanisms (build123d), for the concept renders.

STATUS: concept sketch. Nothing here is designed, built or measured (keyboard/docs/concept.md). Every dimension
below is illustrative: round numbers near an MX-style switch (14 mm plate cutout, 4 mm travel) and near the
candidate parts concept.md names (TMAG5253, TMAG5170, MT6701CT, DRV8316, a 2804-class gimbal motor, a coin LRA).
None of it is a decision, and none of it has been checked against a datasheet drawing.

Each builder returns a list of render items, (name, solid, colour_key), in millimetres, Z up, with the top of the
key PCB (or of the thumb plate, for the wheel) at z = 0:

    he_key(press)                  Hall-effect key with a compliant TPU bottom stop (the aftertouch idea)
    shear_key(press, shift)        custom switch whose stem guide hangs on four flexure posts, over a TMAG5170
    thumb_wheel()                  haptic thumb wheel: gimbal motor, roller, encoder PCB, bracket, neighbour keys
    coil_key(step_cut, lift)       stock MX switch over a PCB with a generated two-layer spiral coil
    lra_mount()                    coin LRA in a cradle on printed flexure arms in the case floor

    python keyboard/hardware/concept/mechanism_models.py     # build each one, print volumes and z extents

The renders are drawn by render_mechanisms.py:

    python keyboard/hardware/concept/render_mechanisms.py
"""
import math

from build123d import (Box, Circle, Cylinder, Helix, Plane, Polygon, Pos, RectangleRounded, Rot, extrude, loft,
                       sweep)

# ---------------------------------------------------------------------------
# Illustrative constants (mm). Not decisions.
# ---------------------------------------------------------------------------
PCB_T = 1.6             # key PCB
PLATE_TOP = 5.0         # MX plate top above the PCB top
PLATE_T = 1.5
CUTOUT = 14.0           # MX plate cutout
TRAVEL = 4.0            # MX-style total travel
SQUASH_MAX = 0.5        # the compliant zone the concept talks about: about 0.2-0.5 mm past the hard travel
KEY_PITCH = 19.05

# Hall-effect key (rest positions; the stem moves down by `press`)
HE = dict(floor=(1.3, 1.8),       # housing floor bridge; the sensor sits in a pocket under it
          tpu=(5.0, 0.8),         # TPU stop: diameter, free thickness
          pole=(5.0, 6.6, 9.4),   # stem pole: diameter, bottom, top (rest)
          magnet=(4.0, 2.0, 6.9),  # magnet: diameter, height, bottom z (rest)
          slider=(7.4, 6.6, 9.4, 10.8),
          spring=(3.0, 0.35, 6),  # mean radius, wire, turns
          cross=(12.4, 16.2),
          cap_bottom=10.4, cap_top=17.6)

# Shear key (custom switch): a carrier cup hangs from the housing roof on four slender posts. The stem slides
# 4 mm inside the carrier; the carrier (with the stem and magnet) moves sideways when the posts bend.
SH = dict(post_r=4.9, post_d=0.7, carrier_od=8.2, carrier_id=6.6, carrier_z=(2.2, 11.6), flange_d=10.8,
          roof_hole=9.0, lateral=0.4,
          pole=(4.4, 6.8, 9.6), magnet=(4.0, 2.0, 7.0), slider=(6.4, 9.6, 11.0),
          spring=(2.8, 0.35, 6), cross=(12.2, 16.0), cap_bottom=10.8, cap_top=17.4)

# Thumb wheel: shaft along +X, axis WHEEL_Z below the thumb plate top (z = 0)
WHEEL_Z = -9.0
MOTOR_D, MOTOR_L = 28.0, 9.0      # 2804-class gimbal motor envelope (task brief: about 28 mm, 8-10 mm tall)
ROLLER_OD, ROLLER_W = 34.0, 10.0

# Printed coil
COIL = dict(r_in=2.25, pitch=0.25, trace=0.125, turns=5, cu=0.07, l2_z=-0.21)   # cu thickness drawn x2


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------
def box(x0, x1, y0, y1, z0, z1):
    return Pos((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2) * Box(x1 - x0, y1 - y0, z1 - z0)


def cbox(w, d, z0, z1, x=0.0, y=0.0):
    return box(x - w / 2, x + w / 2, y - d / 2, y + d / 2, z0, z1)


def zcyl(x, y, d, z0, z1):
    return Pos(x, y, (z0 + z1) / 2) * Cylinder(d / 2, z1 - z0)


def xcyl(y, z, d, x0, x1):
    return Pos((x0 + x1) / 2, y, z) * (Rot(0, 90, 0) * Cylinder(d / 2, x1 - x0))


def ycyl(x, z, d, y0, y1):
    return Pos(x, (y0 + y1) / 2, z) * (Rot(90, 0, 0) * Cylinder(d / 2, y1 - y0))


def rr_loft(w0, d0, r0, z0, w1, d1, r1, z1):
    """Ruled loft between two rounded rectangles (keycap and housing shells)."""
    return loft([Plane.XY.offset(z0) * RectangleRounded(w0, d0, r0),
                 Plane.XY.offset(z1) * RectangleRounded(w1, d1, r1)], ruled=True)


def spring(z0, z1, r_mean, wire, turns):
    """A helical compression spring between z0 and z1 (open ends)."""
    h = Helix(pitch=(z1 - z0) / turns, height=z1 - z0, radius=r_mean, center=(0, 0, z0))
    prof = Plane(origin=h.position_at(0), z_dir=h.tangent_at(0)) * Circle(wire / 2)
    return sweep(prof, path=h, is_frenet=True)


def arrow(p0, p1, d=0.7, head=2.2):
    """A solid arrow from p0 to p1 (shaft + cone), for push and press directions in 3D views."""
    from build123d import Cone, Vector
    a, b = Vector(*p0), Vector(*p1)
    v = b - a
    n = v.length
    hl = min(head, 0.45 * n)
    shaft = Pos(0, 0, (n - hl) / 2) * Cylinder(d / 2, n - hl)
    tip = Pos(0, 0, n - hl / 2) * Cone(d * 1.3, 0, hl)
    pl = Plane(origin=a, z_dir=v)
    return pl * (shaft + tip)


def arc_arrow(x, yz_centre, radius, a0, a1, d=0.8, head=2.6):
    """A curved solid arrow in the plane x = const, around yz_centre, from angle a0 to a1 (degrees, measured from
    +Y towards +Z): a rotation cue for the wheel."""
    from build123d import Cone, Vector
    y0, z0 = yz_centre
    sweep_deg = a1 - a0
    hl_deg = math.degrees(head / radius) * (1 if sweep_deg > 0 else -1)
    pts = []
    n = 24
    for i in range(n + 1):
        a = math.radians(a0 + (sweep_deg - hl_deg) * i / n)
        pts.append(Vector(x, y0 + radius * math.cos(a), z0 + radius * math.sin(a)))
    from build123d import Spline
    path = Spline(*pts)
    shaft = sweep(Plane(origin=pts[0], z_dir=path.tangent_at(0)) * Circle(d / 2), path=path)
    tip_dir = path.tangent_at(1)
    tip = Plane(origin=pts[-1], z_dir=tip_dir) * (Pos(0, 0, head / 2) * Cone(d * 1.3, 0, head))
    return shaft + tip


def half(s, keep="y+", at=0.0):
    """Cut a solid with a plane and keep one side, for cutaways."""
    big = 400.0
    sides = {"y+": box(-big, big, at, big, -big, big), "y-": box(-big, big, -big, at, -big, big),
             "x+": box(at, big, -big, big, -big, big), "x-": box(-big, at, -big, big, -big, big)}
    return s & sides[keep]


def keycap(z_bottom, z_socket, z_inner_top, top=(13.4, 14.6), inner_top=(12.2, 12.2), dish=True):
    """An MX-socket keycap: tapered shell, cross socket, a shallow cylindrical dish. z_socket is the bottom of
    the socket column, z_inner_top the underside of the top (where the stem's cross ends)."""
    z_top = z_inner_top + 1.4
    outer = rr_loft(18.2, 18.2, 1.6, z_bottom, top[0], top[1], 2.0, z_top)
    inner = rr_loft(16.0, 16.0, 1.0, z_bottom - 0.01, inner_top[0], inner_top[1], 1.0, z_inner_top)
    cap = outer - inner
    sock = zcyl(0, 0, 5.6, z_socket, z_inner_top + 0.05)
    sock -= cbox(4.2, 1.4, z_socket - 0.1, z_inner_top) + cbox(1.4, 4.2, z_socket - 0.1, z_inner_top)
    cap += sock
    if dish:
        cap -= ycyl(0, z_top + 40 - 0.5, 80, -20, 20)
    return cap


def mx_cross(z0, z1):
    return cbox(4.1, 1.3, z0, z1) + cbox(1.3, 4.1, z0, z1)


def sot23(z0=0.0):
    """SOT-23-class package (body 2.9 x 1.6 x 1.0 drawn) with gull-wing lead stubs."""
    body = cbox(2.9, 1.6, z0 + 0.1, z0 + 1.1)
    leads = None
    for x, s in ((-0.95, 1), (0.95, 1), (-0.95, -1), (0.0, -1), (0.95, -1)):
        lead = box(x - 0.2, x + 0.2, min(s * 0.8, s * 1.35), max(s * 0.8, s * 1.35), z0, z0 + 0.15)
        leads = lead if leads is None else leads + lead
    return body, leads


def vssop8(z0=0.0):
    """VSSOP-8-class package (TMAG5170): body 3 x 3 x 1, four leads a side."""
    body = cbox(3.0, 3.0, z0 + 0.1, z0 + 1.0)
    leads = None
    for i in range(4):
        y = -0.975 + 0.65 * i
        for s in (-1, 1):
            lead = box(min(s * 1.5, s * 2.45), max(s * 1.5, s * 2.45), y - 0.15, y + 0.15, z0, z0 + 0.15)
            leads = lead if leads is None else leads + lead
    return body, leads


def plate(z_top=PLATE_TOP, w=26.0):
    return cbox(w, w, z_top - PLATE_T, z_top) - cbox(CUTOUT, CUTOUT, z_top - PLATE_T - 1, z_top + 1)


def pcb(w=26.0):
    return cbox(w, w, -PCB_T, 0)


def mx_top_housing(z_base=PLATE_TOP, z_top=11.8, hole=6.2):
    """MX-style top housing: 15.6 square skirt on the plate, tapering to 12 at the top, hollow, with a stem hole."""
    outer = cbox(15.6, 15.6, z_base, z_base + 1.2) + rr_loft(15.6, 15.6, 0.6, z_base + 1.2, 12.0, 12.0, 1.5, z_top)
    inner = cbox(13.6, 13.6, z_base - 0.01, z_base + 1.0) + rr_loft(13.6, 13.6, 0.5, z_base + 1.0, 10.0, 10.0, 1.0,
                                                                     z_top - 1.0)
    return outer - inner - cbox(hole, hole, z_top - 1.5, z_top + 0.5)


# ---------------------------------------------------------------------------
# (1) Hall-effect key with a compliant bottom stop
# ---------------------------------------------------------------------------
def he_key(press=0.0):
    """press: stem travel from rest, 0 .. TRAVEL + SQUASH_MAX. Past TRAVEL the TPU stop compresses."""
    squash = max(0.0, press - TRAVEL)
    dz = -press
    f0, f1 = HE["floor"]
    tpu_d, tpu_t = HE["tpu"]
    pd, pz0, pz1 = HE["pole"]
    md, mh, mz = HE["magnet"]
    sw, sd, sz0, sz1 = HE["slider"]
    r_sp, wire, turns = HE["spring"]
    c0, c1 = HE["cross"]

    body, leads = sot23()
    bottom = cbox(13.9, 13.9, 0, PLATE_TOP) - cbox(11.9, 11.9, f1, PLATE_TOP + 0.01) - cbox(6.0, 6.0, -0.01, f0)
    stem = (zcyl(0, 0, pd, pz0, pz1) - zcyl(0, 0, md + 0.05, mz, mz + mh)) + cbox(sw, sd, sz0, sz1) \
        + cbox(5.0, 5.0, sz1, c0) + mx_cross(c0, c1)
    stem = Pos(0, 0, dz) * stem
    magnet = Pos(0, 0, dz) * zcyl(0, 0, md, mz, mz + mh)
    tpu = zcyl(0, 0, tpu_d, f1, f1 + tpu_t - squash)
    spr = spring(f1, sz0 + dz, r_sp, wire, turns)
    cap = Pos(0, 0, dz) * keycap(HE["cap_bottom"], c0 + 0.2, c1)
    return [
        ("pcb", pcb(), "pcb"),
        ("sensor", body, "sensor"),
        ("sensor leads", leads, "steel"),
        ("bottom housing", bottom, "case"),
        ("plate", plate(), "plate"),
        ("top housing", mx_top_housing(), "motor"),
        ("TPU stop", tpu, "tpu"),
        ("spring", spr, "spring"),
        ("stem", stem, "stem"),
        ("magnet", magnet, "magnet"),
        ("keycap", cap, "keycap"),
    ]


# ---------------------------------------------------------------------------
# (2) Shear key: stem guide hung on four flexure posts
# ---------------------------------------------------------------------------
def shear_housing():
    lower = cbox(13.9, 13.9, 0, PLATE_TOP) - cbox(12.3, 12.3, 1.8, PLATE_TOP + 0.01) - cbox(6.0, 6.0, -0.01, 1.3)
    outer = cbox(14.2, 14.2, PLATE_TOP, 6.0) + rr_loft(14.2, 14.2, 0.6, 6.0, 11.6, 11.6, 1.5, 11.4)
    inner = cbox(12.6, 12.6, PLATE_TOP - 0.01, 6.0) + rr_loft(12.6, 12.6, 0.5, 6.0, 9.6, 9.6, 1.0, 10.4)
    upper = outer - inner - zcyl(0, 0, SH["roof_hole"], 9.0, 12.0)
    return lower + upper


def shear_carrier(shift=(0.0, 0.0)):
    """The carrier cup and its flange; it moves sideways with the stem. The posts are drawn separately."""
    z0, z1 = SH["carrier_z"]
    cup = zcyl(0, 0, SH["carrier_od"], z0, z1) - zcyl(0, 0, SH["carrier_id"], z0 + 0.6, z1 - 0.6) \
        - zcyl(0, 0, 5.0, z1 - 0.7, z1 + 0.1)
    cup += zcyl(0, 0, SH["flange_d"], z0, z0 + 0.6)
    return Pos(shift[0], shift[1], 0) * cup


def shear_posts(shift=(0.0, 0.0)):
    """Four slender posts from the carrier flange up into the housing roof. With a shift they bend in an S
    (fixed-guided beam shape), so the carrier translates without tilting."""
    z0 = SH["carrier_z"][0] + 0.6
    z1 = 10.6
    out = None
    for ang in (0, 90, 180, 270):
        x = SH["post_r"] * math.cos(math.radians(ang))
        y = SH["post_r"] * math.sin(math.radians(ang))
        if shift == (0.0, 0.0):
            p = zcyl(x, y, SH["post_d"], z0 - 0.05, z1)
        else:
            from build123d import Spline, Vector
            pts = []
            for i in range(9):
                s = i / 8
                w = 1 - (3 * s * s - 2 * s ** 3)          # 1 at the carrier, 0 at the roof
                pts.append(Vector(x + shift[0] * w, y + shift[1] * w, z0 - 0.05 + s * (z1 - z0 + 0.05)))
            path = Spline(*pts)
            prof = Plane(origin=pts[0], z_dir=path.tangent_at(0)) * Circle(SH["post_d"] / 2)
            p = sweep(prof, path=path)
        out = p if out is None else out + p
    return out


def shear_key(press=0.0, shift=(0.0, 0.0)):
    """press: 0 .. TRAVEL (bottom-out on the carrier floor); shift: lateral (x, y) of carrier, stem and magnet."""
    dz = -press
    sx, sy = shift
    pd, pz0, pz1 = SH["pole"]
    md, mh, mz = SH["magnet"]
    sd, sz0, sz1 = SH["slider"]
    c0, c1 = SH["cross"]
    r_sp, wire, turns = SH["spring"]
    floor = SH["carrier_z"][0] + 0.6

    body, leads = vssop8()
    stem = (zcyl(0, 0, pd, pz0, pz1) - zcyl(0, 0, md + 0.05, mz, mz + mh)) + zcyl(0, 0, sd, sz0, sz1) \
        + zcyl(0, 0, 4.6, sz1, c0) + mx_cross(c0, c1)
    stem = Pos(sx, sy, dz) * stem
    magnet = Pos(sx, sy, dz) * zcyl(0, 0, md, mz, mz + mh)
    spr = Pos(sx, sy, 0) * spring(floor, sz0 + dz, r_sp, wire, turns)
    cap = Pos(sx, sy, dz) * keycap(SH["cap_bottom"], c0 + 0.2, c1)
    return [
        ("pcb", pcb(), "pcb"),
        ("TMAG5170", body, "sensor"),
        ("TMAG5170 leads", leads, "steel"),
        ("housing", shear_housing(), "motor"),
        ("plate", plate(), "plate"),
        ("carrier", shear_carrier(shift), "keycap_alt"),
        ("flexure posts", shear_posts(shift), "keycap_alt"),
        ("spring", spr, "spring"),
        ("stem", stem, "stem"),
        ("magnet", magnet, "magnet"),
        ("keycap", cap, "keycap_accent"),
    ]


# ---------------------------------------------------------------------------
# (3) Haptic thumb wheel module
# ---------------------------------------------------------------------------
def neighbour_key(x, y=0.0, z_plate=0.0, colour="keycap"):
    """A thumb key for scale: plain MX-style switch block and keycap (no internals)."""
    sw = cbox(13.9, 13.9, z_plate - 5.0, z_plate) + cbox(15.6, 15.6, z_plate, z_plate + 1.2) \
        + rr_loft(15.6, 15.6, 0.6, z_plate + 1.2, 12.0, 12.0, 1.5, z_plate + 6.8)
    cap = keycap(z_plate + 5.4, z_plate + 7.6, z_plate + 11.2)
    return [(f"switch {x:+.0f}", Pos(x, y, 0) * sw, "switch"), (f"keycap {x:+.0f}", Pos(x, y, 0) * cap, colour)]


def thumb_wheel():
    zc = WHEEL_Z
    # motor: stator base (x -2..0), bell (x 0..7) with the shaft fixed to the bell's front
    base = xcyl(0, zc, 16.0, -2.0, 0.0) + xcyl(0, zc, 8.0, -2.0, 5.8) - xcyl(0, zc, 6.0, -2.1, 5.9)
    stator = xcyl(0, zc, 23.0, 0.8, 5.8) - xcyl(0, zc, 8.0, 0.7, 5.9)
    windings = (xcyl(0, zc, 21.0, 0.2, 0.8) - xcyl(0, zc, 11.0, 0.1, 0.9)) + \
        (xcyl(0, zc, 21.0, 5.8, 6.4) - xcyl(0, zc, 11.0, 5.7, 6.5))
    bell = xcyl(0, zc, MOTOR_D, 0.0, 7.0) - xcyl(0, zc, MOTOR_D - 2.0, -0.1, 6.2)
    bell -= xcyl(0, zc, 4.0, 6.1, 7.1)
    rotor_mag = xcyl(0, zc, MOTOR_D - 2.0, 0.6, 6.0) - xcyl(0, zc, 24.0, 0.5, 6.1)
    bearings = (xcyl(0, zc, 6.0, -1.8, -0.4) - xcyl(0, zc, 4.0, -1.9, -0.3)) + \
        (xcyl(0, zc, 6.0, 4.2, 5.6) - xcyl(0, zc, 4.0, 4.1, 5.7))
    shaft = xcyl(0, zc, 4.0, -4.0, 7.0)
    # diametric magnet in a holder on the shaft's back end
    holder = xcyl(0, zc, 8.0, -4.6, -3.6) - xcyl(0, zc, 4.0, -3.7, -3.5)
    dmag = xcyl(0, zc, 6.0, -6.6, -4.6)
    # roller: printed hub over the bell, rubber tyre
    hub = xcyl(0, zc, ROLLER_OD - 3.0, 0.0, ROLLER_W) - xcyl(0, zc, MOTOR_D + 0.2, -0.1, 7.1)
    hub -= xcyl(0, zc, 5.0, 7.0, ROLLER_W + 0.1)
    tyre = xcyl(0, zc, ROLLER_OD, 0.6, ROLLER_W - 0.6) - xcyl(0, zc, ROLLER_OD - 3.0, 0.5, ROLLER_W - 0.5)
    # bracket: vertical plate behind the stator base, top flange under the thumb plate
    brk = box(-3.6, -2.0, -13.0, 13.0, -26.0, -1.5) + box(-12.0, -2.0, -13.0, 13.0, -3.1, -1.5)
    brk -= xcyl(0, zc, 9.5, -4.0, -1.0)
    screws = None
    for a in (45, 135, 225, 315):
        y, z = 8.0 * math.cos(math.radians(a)), zc + 8.0 * math.sin(math.radians(a))
        s = xcyl(y, z, 3.6, -4.6, -3.6)
        screws = s if screws is None else screws + s
    # encoder / driver board, parallel to the bracket: MT6701CT faces the magnet, DRV8316 on the back
    epcb = box(-10.2, -8.6, -12.0, 12.0, -24.0, -3.4)
    enc = box(-8.6, -7.1, -1.95, 1.95, zc - 2.45, zc + 2.45)          # SOP-8 body 4.9 x 3.9 x 1.5
    enc_leads = None
    for i in range(4):
        zl = zc - 1.905 + 1.27 * i
        for s in (-1, 1):
            ld = box(-8.6, -8.45, min(s * 1.95, s * 3.0), max(s * 1.95, s * 3.0), zl - 0.2, zl + 0.2)
            enc_leads = ld if enc_leads is None else enc_leads + ld
    drv = box(-11.1, -10.2, -2.5, 4.5, -21.5, -16.5)                    # VQFN 7 x 5 x 0.9
    passives = None
    for y, z in ((-4.5, -17.5), (-4.5, -20.0), (6.5, -18.0), (2.0, -13.0), (5.0, -13.0), (-3.0, -13.0)):
        p = box(-10.9, -10.2, y - 0.8, y + 0.8, z - 0.4, z + 0.4)
        passives = p if passives is None else passives + p
    conn = box(-13.5, -10.2, -11.5, -6.0, -23.5, -19.5)
    standoffs = xcyl(10.0, -21.0, 3.0, -8.6, -3.6) + xcyl(-10.0, -21.0, 3.0, -8.6, -3.6)
    # thumb plate with the wheel slot, and the thumb PCB cut away around the module
    xm = ROLLER_W / 2
    tplate = box(-36.0, 46.0, -16.0, 16.0, -1.5, 0.0) - box(xm - 7.0, xm + 7.0, -17.5, 17.5, -2.0, 0.5)
    tpcb = box(-36.0, -13.0, -16.0, 16.0, -6.6, -5.0) + box(18.0, 46.0, -16.0, 16.0, -6.6, -5.0)
    items = [
        ("thumb plate", tplate, "plate"),
        ("thumb PCB", tpcb, "pcb"),
        ("bracket", brk, "case_light"),
        ("bracket screws", screws, "steel"),
        ("stator base", base, "motor"),
        ("stator", stator, "steel"),
        ("windings", windings, "copper"),
        ("rotor bell", bell, "motor"),
        ("rotor magnets", rotor_mag, "magnet"),
        ("bearings", bearings, "steel"),
        ("shaft", shaft, "steel"),
        ("magnet holder", holder, "case_light"),
        ("diametric magnet", dmag, "highlight"),
        ("roller hub", hub, "keycap_alt"),
        ("tyre", tyre, "rubber"),
        ("encoder PCB", epcb, "pcb"),
        ("MT6701CT", enc, "ic"),
        ("MT6701CT leads", enc_leads, "steel"),
        ("DRV8316", drv, "ic"),
        ("passives", passives, "case_light"),
        ("connector", conn, "usb"),
        ("standoffs", standoffs, "steel"),
    ]
    items += neighbour_key(xm - 24.0) + neighbour_key(xm + 24.0)
    return items


# ---------------------------------------------------------------------------
# (4) Printed-coil key: stock MX switch over a generated spiral
# ---------------------------------------------------------------------------
def spiral_face(r_in, pitch, trace, turns, ccw=True, n_per_turn=96):
    """The outline of one spiral trace (an Archimedean band) as a face in XY."""
    n = int(turns * n_per_turn)
    outer, inner = [], []
    for i in range(n + 1):
        t = i / n_per_turn * 2 * math.pi
        r = r_in + pitch * t / (2 * math.pi)
        a = t if ccw else -t
        outer.append(((r + trace / 2) * math.cos(a), (r + trace / 2) * math.sin(a)))
        inner.append(((r - trace / 2) * math.cos(a), (r - trace / 2) * math.sin(a)))
    pts = outer + inner[::-1]
    area2 = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]))
    if area2 < 0:          # a clockwise outline would extrude towards -z
        pts = pts[::-1]
    return Polygon(*pts, align=None)


def coil_layers():
    """L1 (top) and L2 (inner) spirals joined by a via at their inner ends (on +X). L1 winds anticlockwise and L2
    clockwise going outwards, so one current runs the same way round in both and their fields add. Both end at
    +Y, where the leads leave (clear of the y = 0 section plane)."""
    c = COIL
    t1, t2 = c["turns"] + 0.25, c["turns"] - 0.25
    l1 = extrude(spiral_face(c["r_in"], c["pitch"], c["trace"], t1, ccw=True), c["cu"])
    l2 = Pos(0, 0, c["l2_z"]) * extrude(spiral_face(c["r_in"], c["pitch"], c["trace"], t2, ccw=False), c["cu"])
    via = zcyl(c["r_in"], 0, 0.3, c["l2_z"], c["cu"])
    w = c["trace"] / 2
    lead1 = box(-w, w, c["r_in"] + c["pitch"] * t1 - 0.06, 11.0, 0, c["cu"])
    lead2 = Pos(0, 0, c["l2_z"]) * box(-w, w, c["r_in"] + c["pitch"] * t2 - 0.06, 11.0, 0, c["cu"])
    return l1 + lead1, l2 + lead2 + via


def coil_key(step_cut=False, lift=0.0):
    """Stock MX (3-pin) switch over a PCB carrying the coil. step_cut removes the y<0 half of the switch and keycap
    and, in a patch of the x>0, y<0 quadrant, the top 0.21 mm of the PCB and the L1 copper, so L2 shows.
    lift raises the whole switch off the board (an exploded view)."""
    l1, l2 = coil_layers()
    board = pcb(24.0) - zcyl(0, 0, 4.0, -2, 1)                       # MX centre-post hole
    board -= zcyl(-3.81, 2.54, 1.5, -2, 1) + zcyl(2.54, 5.08, 1.5, -2, 1)
    # stock switch internals (illustrative)
    bottom = cbox(13.9, 13.9, 0, PLATE_TOP) - cbox(11.9, 11.9, 1.0, PLATE_TOP + 0.01)
    bottom += zcyl(0, 0, 3.9, -3.3, 0.0)                              # centre post into the PCB hole
    bottom += zcyl(0, 0, 4.2, 1.0, 3.0)                               # spring boss
    bottom -= zcyl(0, 0, 2.8, -2.6, 3.1)                              # bore for the stem pole
    pins = zcyl(-3.81, 2.54, 1.0, -3.3, 1.0) + zcyl(2.54, 5.08, 1.0, -3.3, 1.0)
    leaves = box(-4.6, -4.4, 0.8, 4.2, 1.0, 6.0) + box(-1.0, 3.0, 4.6, 4.8, 1.0, 6.0)
    stem = zcyl(0, 0, 2.6, 3.8, 7.5) + cbox(7.2, 5.6, 7.5, 10.8) + cbox(5.0, 5.0, 10.8, 12.4) + mx_cross(12.4, 16.2)
    spr = spring(1.0, 7.5, 2.5, 0.35, 6)
    cap = keycap(10.4, 12.6, 16.2)
    top = mx_top_housing()
    pl = plate(w=24.0)
    if step_cut:
        bottom, top, stem, cap, pl = (half(s, "y+") for s in (bottom, top, stem, cap, pl))
        quad = box(0, 5.0, -5.0, 0, -0.21 - 0.001, 1.0)
        board = board - quad
        l1 = l1 - quad
    # the switch stands on the top copper, so it sits one copper thickness up (plus any exploded-view lift)
    up = lift + COIL["cu"]
    bottom, pins, leaves, stem, spr, cap, top, pl = (Pos(0, 0, up) * s_ for s_ in
                                                     (bottom, pins, leaves, stem, spr, cap, top, pl))
    items = [
        ("pcb", board, "pcb"),
        ("coil L1", l1, "copper"),
        ("coil L2", l2, "copper"),
        ("pins", pins, "copper"),
        ("bottom housing", bottom, "case"),
        ("contact leaves", leaves, "copper"),
        ("plate", pl, "plate"),
        ("top housing", top, "switch"),
        ("spring (steel)", spr, "steel"),
        ("stem", stem, "stem"),
        ("keycap", cap, "keycap"),
    ]
    return items


# ---------------------------------------------------------------------------
# (5) LRA in a decoupled flexure pocket
# ---------------------------------------------------------------------------
def annular_sector(r0, r1, a0, a1, z0, z1, n=48):
    pts = [(r1 * math.cos(math.radians(a0 + (a1 - a0) * i / n)), r1 * math.sin(math.radians(a0 + (a1 - a0) * i / n)))
           for i in range(n + 1)]
    pts += [(r0 * math.cos(math.radians(a1 - (a1 - a0) * i / n)), r0 * math.sin(math.radians(a1 - (a1 - a0) * i / n)))
            for i in range(n + 1)]
    return Pos(0, 0, z0) * extrude(Polygon(*pts, align=None), z1 - z0)


LRA = dict(d=10.0, h=2.7, cradle_r=7.0, slot_r=9.6, arm=(7.6, 8.8), arm_z=(1.2, 2.4), floor=(0.0, 2.4))


def lra_mount():
    """A patch of case floor around the pocket, standing on TPU feet on a desk. The main PCB above is left out so
    the pocket can be seen; the flex tail rises towards it."""
    c = LRA
    f0, f1 = c["floor"]
    floor = box(-15.0, 15.0, -15.0, 15.0, f0, f1) - zcyl(0, 0, 2 * c["slot_r"], f0 - 1, f1 + 1)
    cradle = zcyl(0, 0, 2 * c["cradle_r"], 0.6, 3.6) - zcyl(0, 0, c["d"] + 0.3, 1.6, 3.7)
    arms = None
    a_in, a_out = c["arm"]
    z0, z1 = c["arm_z"]
    for k in range(3):
        a = 90 + 120 * k
        band = annular_sector(a_in, a_out, a, a + 95, z0, z1)
        stub_in = annular_sector(c["cradle_r"] - 0.2, a_in + 0.05, a, a + 8, z0, z1)
        stub_out = annular_sector(a_out - 0.05, c["slot_r"] + 0.3, a + 87, a + 95, z0, z1)
        arm = band + stub_in + stub_out
        arms = arm if arms is None else arms + arm
    lra = zcyl(0, 0, c["d"], 1.6, 1.6 + c["h"])
    top = 1.6 + c["h"]
    tail = box(3.0, 11.6, 2.0, 4.0, top, top + 0.2) + box(11.4, 11.6, 2.0, 4.0, top, 10.0)
    feet = None
    for x, y in ((-11.0, 0.0), (11.0, 0.0), (-11.0, 12.0), (11.0, 12.0)):
        f = zcyl(x, y, 6.0, -1.5, 0.0)
        feet = f if feet is None else feet + f
    desk = box(-17.0, 17.0, -8.0, 17.0, -2.5, -1.5)
    return [
        ("desk", desk, "case_light"),
        ("TPU feet", feet, "tpu"),
        ("case floor", floor, "case"),
        ("flexure arms", arms, "keycap_alt"),
        ("cradle", cradle, "keycap_alt"),
        ("coin LRA", lra, "lra"),
        ("flex tail", tail, "flex"),
    ]


if __name__ == "__main__":
    import time
    for name, fn in (("he_key", he_key), ("shear_key", shear_key), ("thumb_wheel", thumb_wheel),
                     ("coil_key", coil_key), ("lra_mount", lra_mount)):
        t = time.time()
        items = fn()
        print(f"{name}: {len(items)} items, {time.time() - t:.1f} s")
        for n, s, c in items:
            bb = s.bounding_box()
            print(f"   {n:18s} {c:14s} vol {s.volume:8.2f}  z {bb.min.Z:6.2f}..{bb.max.Z:6.2f}")
