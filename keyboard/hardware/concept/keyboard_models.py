#!/usr/bin/env python3
"""Illustrative parametric model of the rev B keyboard concept: a split, column-staggered keywell (build123d).

What it builds (mm, Z up, the desk at z = 0, +Y away from the typist, X to the typist's right):

    per half   6 finger columns x 3 rows at MX pitch, each column on an arc about the finger's flexion, with
               per-column stagger, splay and row curvature; a thumb arc of 4 keys (right half) or 3 keys plus the
               haptic thumb wheel (left half); keycaps and Hall-effect switch bodies (socketless, no hot-swap
               sockets); a 0.8 mm column board bent to each column's arc and a flat thumb board, joined by flex links
               to a main board (MCU module, battery; on the left half two USB-C ports for the two-host KVM, a
               host-B controller and an isolator); a coin LRA in the case near the thumb; a printed case tented
               about 18 deg, split into a top shell (plate and walls) and a floor.
    keycap gate  every keycap at rest and pressed to bottom-out, checked against its neighbours, the case and the
               wheel (the "keycap clearance gate" of concept.md section 4.1, here as a sketch).

    PY=/path/to/venv/bin/python          # build123d 0.13, numpy
    $PY keyboard/hardware/concept/keyboard_models.py      # build both halves (M preset), print parts, bboxes and
                                                          # the keycap-clearance summary

Status: CONCEPT SKETCH. Nothing in keyboard/ is designed, built or measured (keyboard/docs/concept.md). Every
number below is an illustrative constant chosen to give a believable picture, not a decision: stagger, splay, radii,
tent angle, part sizes and positions are placeholders until the rev B design. The S/M/L presets are a uniform
illustrative scale, not the anthropometric mapping concept.md section 4.4 plans (that mapping is not validated).
Parts are the candidates named in concept.md; the MCU is not chosen (the rev A testbed decides, concept.md section 5),
so it is drawn as a generic shielded module. Which half carries the one thumb wheel is not decided; the sketch puts it
on the left, next to the USB-C inputs that would power it (the wheel is wired-first, concept.md section 2.3). How the
halves link and how the right half charges are not decided, so no port is drawn on the right half.
"""
import math
from dataclasses import dataclass, field

import numpy as np
from build123d import (Axis, Box, Cylinder, Face, Location, Plane, Polygon, Pos, Rectangle, Rot, Wire, extrude,
                       loft, mirror, revolve, section)

# ---------------------------------------------------------------------------------------------------------------
# Constants (illustrative)
# ---------------------------------------------------------------------------------------------------------------
PITCH = 19.05            # MX key pitch
# key stack along each key's own axis, measured from the plate top
PLATE_T = 2.0            # printed plate = the top shell's roof (vertical thickness)
SW_TOP_W0, SW_TOP_W1, SW_TOP_H = 15.6, (11.2, 11.8), 5.8     # switch top housing: base, top, height
SW_BOT_W, SW_BOT_H = 13.8, 5.0                              # bottom housing below the plate (plate top to board)
STEM_W, STEM_H = 5.6, 3.4
CAP_W0, CAP_W1, CAP_H = 18.0, (12.6, 13.6), 7.4             # keycap: skirt, top (x, y), height
CAP_REST = 6.2           # keycap skirt above the plate at rest
TRAVEL = 4.0             # switch travel to bottom-out
BOARD_T, BOARD_W = 0.8, 15.5                                # column boards (concept.md section 2.2: 0.8 mm)
SKIRT_GAP = PITCH + 0.25 - CAP_W0   # 1.3 mm cap-to-cap at the skirt, at rest: MX pitch plus a little for the
#                                     curved rows; it sets the row and column angles
TILE_W = 18.6            # plate tile across a column; ruled webs fill the gap to the next column
RIM = 3.0                # plate rim beyond the outer keys
RIM_IN = 6.0             # wider rim on the inner (high, tented) side: tilted parts below the plate lean inward
WALL, FLOOR_T = 2.5, 2.5
Z_LOW = 13.0             # height of the lowest plate corner above the desk
TENT = 18.0              # deg, inner (thumb) side up
ROW_BETA = 4.5           # deg between neighbouring columns (row curvature, about the middle column)
HOLE = 14.0              # MX plate cut-out
SHEAR_HOME_COL = 1       # index column: F / J are its home keys

# canonical right half, inner index column first: finger, flexion radius at the plate, stagger dy, dz, splay (deg)
COLUMNS = [
    ("index (inner)", 82.0, 0.0, 0.5, 0.0, ("Y", "H", "N")),
    ("index", 82.0, 0.0, 0.0, 0.0, ("U", "J", "M")),
    ("middle", 90.0, 5.0, -2.5, 0.0, ("I", "K", ",")),
    ("ring", 84.0, 2.0, -1.0, 2.0, ("O", "L", ".")),
    ("pinky", 72.0, -9.0, 2.5, 5.0, ("P", ";", "/")),
    ("pinky (outer)", 72.0, -10.5, 3.5, 6.0, ("[", "'", "Sh")),
]
LEFT_LETTERS = [("T", "G", "B"), ("R", "F", "V"), ("E", "D", "C"), ("W", "S", "X"), ("Q", "A", "Z"),
                ("Tab", "Esc", "Sh")]

THUMB = dict(
    offset=(-9.6, -127.8),   # arc centre in plan, from the index home key
    radius=78.0,             # to the key centres
    phi0=93.0,               # first slot, deg CCW from +X (canonical right half)
    gap=1.2,                 # cap-to-cap gap at the inner corners, at rest (sets the slot step)
    dz=-12.0,                # thumb home plate below the index home plate (before tenting)
    tilt_x=8.0,              # thumb plane tilted toward the palm
    tilt_y=-8.0,             # and back against the tent
    home=1,                  # thumb home slot (the shear thumb key)
)
WHEEL = dict(d=24.0, w=11.0, axis_z=-7.0, motor_d=20.0, motor_l=9.0, slot_extra=3.0)   # deg extra for its slot
WHEEL_SLOT = 0           # left half: the wheel sits in the thumb slot nearest the fingers, beside the home key

PRESETS = {"S": 0.92, "M": 1.00, "L": 1.08}   # illustrative uniform scale on radii, stagger and thumb arc


# ---------------------------------------------------------------------------------------------------------------
# 4x4 pose helpers
# ---------------------------------------------------------------------------------------------------------------
def T(x=0.0, y=0.0, z=0.0):
    m = np.eye(4)
    m[:3, 3] = (x, y, z)
    return m


def _rot(axis, deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    m = np.eye(4)
    i, j = {"x": (1, 2), "y": (2, 0), "z": (0, 1)}[axis]
    m[i, i], m[i, j], m[j, i], m[j, j] = c, -s, s, c
    return m


def RX(d):
    return _rot("x", d)


def RY(d):
    return _rot("y", d)


def RZ(d):
    return _rot("z", d)


def about(p, r):
    p = np.asarray(p, float)
    return T(*p) @ r @ T(*(-p))


def pt(m, x=0.0, y=0.0, z=0.0):
    return (m @ np.array([x, y, z, 1.0]))[:3]


def loc(m):
    return Location(Plane(origin=tuple(m[:3, 3]), x_dir=tuple(m[:3, 0]), z_dir=tuple(m[:3, 2])))


MIRROR = np.diag([-1.0, 1.0, 1.0, 1.0])


def box(x0, x1, y0, y1, z0, z1):
    return Pos((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2) * Box(x1 - x0, y1 - y0, z1 - z0)


def ycyl(r, y0, y1, x=0.0, z=0.0):
    return Pos(x, (y0 + y1) / 2, z) * (Rot(90, 0, 0) * Cylinder(r, y1 - y0))


def strip(p0, p1, wdir, width, thick=0.3):
    """A thin flat strip (flex link) from p0 to p1, its width along wdir."""
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    d = p1 - p0
    n = np.linalg.norm(d)
    d /= n
    w = np.asarray(wdir, float) - d * np.dot(wdir, d)
    w /= np.linalg.norm(w)
    z = np.cross(d, w)
    mid = (p0 + p1) / 2
    return Location(Plane(origin=tuple(mid), x_dir=tuple(d), z_dir=tuple(z))) * Box(n + thick, width, thick)


def prism_down(pts, depth=260.0):
    """Planar 3D polygon -> solid swept straight down (world -Z). The case is a union of these."""
    f = Face(Wire.make_polygon([tuple(p) for p in pts], close=True))
    return extrude(f, amount=depth, dir=(0, 0, -1))


def hull2d(p):
    """Convex hull (Andrew's monotone chain) of 2D points, counter-clockwise."""
    p = sorted(map(tuple, p))

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, hi = [], []
    for q in p:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], q) <= 0:
            lo.pop()
        lo.append(q)
    for q in reversed(p):
        while len(hi) >= 2 and cross(hi[-2], hi[-1], q) <= 0:
            hi.pop()
        hi.append(q)
    return np.array(lo[:-1] + hi[:-1])


# ---------------------------------------------------------------------------------------------------------------
# Solids in a key's own frame (plate top centre at the origin, z along the key axis)
# ---------------------------------------------------------------------------------------------------------------
def keycap_solid():
    return loft([Pos(0, 0, CAP_REST) * Rectangle(CAP_W0, CAP_W0),
                 Pos(0, 0, CAP_REST + CAP_H) * Rectangle(*CAP_W1)])


def switch_top_solid():
    return loft([Rectangle(SW_TOP_W0, SW_TOP_W0), Pos(0, 0, SW_TOP_H) * Rectangle(*SW_TOP_W1)])


def switch_bottom_solid():
    return box(-SW_BOT_W / 2, SW_BOT_W / 2, -SW_BOT_W / 2, SW_BOT_W / 2, -SW_BOT_H, 0.0)


def stem_solid():
    return box(-STEM_W / 2, STEM_W / 2, -STEM_W / 2, STEM_W / 2, SW_TOP_H, SW_TOP_H + STEM_H)


@dataclass
class Key:
    name: str
    finger: str
    col: int                 # -1 for a thumb key
    row: int                 # +1 top (far), 0 home, -1 bottom; thumb: slot index
    m: np.ndarray            # pose: plate-top centre, z = press axis (half's world frame)
    tile: tuple              # plate tile (x0, x1, y0, y1) in the key frame
    shear: bool = False
    thumb: bool = False

    @property
    def axis(self):
        return self.m[:3, 2]

    def cap(self, depth=0.0):
        """Keycap solid pressed `depth` mm along its axis (0 = rest, TRAVEL = bottom-out)."""
        return loc(self.m @ T(0, 0, -depth)) * keycap_solid()


@dataclass
class Half:
    side: str
    preset: str
    keys: list = field(default_factory=list)
    parts: list = field(default_factory=list)       # (name, solid, colour, group)
    info: dict = field(default_factory=dict)

    def items(self, groups=None, skip=()):
        return [(n, s, c) for n, s, c, g in self.parts if (groups is None or g in groups) and g not in skip]

    def key(self, name):
        return next(k for k in self.keys if k.name == name)


# ---------------------------------------------------------------------------------------------------------------
# Key poses
# ---------------------------------------------------------------------------------------------------------------
def _finger_poses(s):
    beta = ROW_BETA
    rr = CAP_REST + (CAP_W0 + SKIRT_GAP) / (2 * math.sin(math.radians(beta) / 2))
    out = []
    for c, (finger, r0, dy, dz, splay, letters) in enumerate(COLUMNS):
        r = r0 * s
        alpha = math.degrees(2 * math.asin((CAP_W0 + SKIRT_GAP) / 2 / (r - CAP_REST)))
        length = 2 * r * math.tan(math.radians(alpha) / 2)           # tiles in a column share their edges
        rc = T(0, 0, rr) @ RY(-beta * (c - 2)) @ T(0, 0, -rr)

        def ar(row, r=r, alpha=alpha):
            return T(0, 0, r) @ RX(row * alpha) @ T(0, 0, -r)
        pivot = pt(rc @ ar(-1))
        sc = T(0, dy * s, dz * s) @ about(pivot, RZ(-splay))
        col = dict(c=c, finger=finger, r=r, alpha=alpha, length=length, frame=sc @ rc, keys=[])
        for row, name in zip((1, 0, -1), letters):
            x0, x1, y0, y1 = -TILE_W / 2, TILE_W / 2, -length / 2, length / 2
            if row == 1:
                y1 += RIM
            if row == -1:
                y0 -= RIM
            if c == 0:
                x0 -= RIM_IN
            if c == len(COLUMNS) - 1:
                x1 += RIM
            col["keys"].append(Key(name, finger, c, row, sc @ rc @ ar(row), (x0, x1, y0, y1),
                                   shear=(c == SHEAR_HOME_COL and row == 0)))
        out.append(col)
    return out


def _thumb_poses(s, index_home, wheel):
    t = THUMB
    rt = t["radius"] * s
    step = math.degrees(2 * math.asin((CAP_W0 / 2 + t["gap"] / 2) / (rt - CAP_W0 / 2)))
    cx, cy = index_home[0] + t["offset"][0] * s, index_home[1] + t["offset"][1] * s
    phis = [t["phi0"] + k * step for k in range(4)]
    if wheel:                        # the wheel takes slot 0, next to the thumb home key, with a little more room
        phis[0] -= WHEEL["slot_extra"]
    ph = math.radians(phis[t["home"]])
    home = (cx + rt * math.cos(ph), cy + rt * math.sin(ph), 0.0)
    plane = T(0, 0, index_home[2] + t["dz"] * s) @ about(home, RX(t["tilt_x"]) @ RY(t["tilt_y"]))
    slots = [plane @ T(cx, cy, 0) @ RZ(phi) @ T(rt, 0, 0) @ RZ(-90) for phi in phis]
    return dict(plane=plane, centre=(cx, cy), radius=rt, phis=phis, step=step, slots=slots)


# ---------------------------------------------------------------------------------------------------------------
# One half
# ---------------------------------------------------------------------------------------------------------------
def build_half(side="L", preset="M", case=True, verbose=False):
    """Build one half. side 'L' carries the wheel and the USB-C ports; 'R' has a fourth thumb key instead.
    Everything is built for the canonical right-hand geometry and mirrored for the left."""
    s = PRESETS[preset]
    wheel = side == "L"
    cols = _finger_poses(s)
    index_home = pt(cols[SHEAR_HOME_COL]["keys"][1].m)
    th = _thumb_poses(s, index_home, wheel)

    # thumb keys
    thumb_keys = []
    names = ["T1", "T2", "T3", "T4"]
    for k, m in enumerate(th["slots"]):
        if wheel and k == WHEEL_SLOT:
            continue
        thumb_keys.append(Key(names[k], "thumb", -1, k, m, (-12.8, 12.8, -12.8, 12.8),
                              shear=(k == THUMB["home"]), thumb=True))

    # tent about the outer edge, then lift so the lowest plate corner sits at Z_LOW and the inner edge at x = 0
    finger_keys = [k for c in cols for k in c["keys"]]
    all_m = [k.m for k in finger_keys] + th["slots"]
    corners = np.array([pt(m, x, y) for m in all_m for x in (-13, 13) for y in (-13, 13)])
    tent = about((corners[:, 0].max(), 0, 0), RY(TENT))
    tc = np.array([pt(tent, *p) for p in corners])
    world = T(-tc[:, 0].min(), 0, Z_LOW - tc[:, 2].min()) @ tent
    for k in finger_keys + thumb_keys:
        k.m = world @ k.m
    for c in cols:
        c["frame"] = world @ c["frame"]
    th["plane"] = world @ th["plane"]
    th["slots"] = [world @ m for m in th["slots"]]
    wheel_m = th["slots"][WHEEL_SLOT] if wheel else None

    h = Half(side, preset)
    h.keys = finger_keys + thumb_keys
    h.info.update(cols=cols, thumb=th, wheel_m=wheel_m, world=world, scale=s, tent=TENT,
                  up=world[:3, :3] @ np.array([0, 0, 1.0]))

    parts = []
    # keycaps and switches
    for k in h.keys:
        cap_c = "keycap_accent" if k.shear else "keycap"
        parts.append((f"cap {k.name}", k.cap(), cap_c, "cap"))
        hous = "tpu" if k.shear else "switch"
        lk = loc(k.m)
        parts.append((f"switch {k.name}", lk * switch_top_solid(), hous, "switch"))
        parts.append((f"switch base {k.name}", lk * switch_bottom_solid(), hous, "switch"))
        parts.append((f"stem {k.name}", lk * stem_solid(), "stem", "switch"))

    # column boards: 0.8 mm strips that follow each column's arc
    links = []
    for c in cols:
        r, a = c["r"], c["alpha"]
        rb = r + SW_BOT_H + BOARD_T / 2
        ext = math.degrees(6.5 / rb)
        span = 2 * (a + ext)
        prof = Plane.XZ * Pos(0, -rb) * Rectangle(BOARD_W, BOARD_T)
        strip_ = revolve(Rot(-(a + ext), 0, 0) * prof, Axis.X, span)
        f = c["frame"] @ T(0, 0, r)
        parts.append((f"column board {c['c']}", loc(f) * strip_, "pcb", "board"))
        # near the far end of the board (top-row end), underside: a flex link runs down from here
        end = f @ RX(a + ext - math.degrees(4.0 / rb)) @ T(0, 0, -(rb + BOARD_T / 2))
        c["board_end"] = pt(end)
        c["board_wdir"] = c["frame"][:3, 0]

    # thumb board: a flat arc band under the thumb keys
    tp = th["plane"] @ T(*th["centre"], 0)
    k0 = 1 if wheel else 0
    bo, bi = _band(th, k0, 3, half=8.5)
    hb = bo + bi[::-1]
    tb = loc(tp @ T(0, 0, -SW_BOT_H - BOARD_T)) * extrude(Polygon(*hb, align=None), BOARD_T)
    parts.append(("thumb board", tb, "pcb", "board"))
    phl = math.radians(th["phis"][k0] - 4.0)
    tb_end = pt(tp @ T(0, 0, -SW_BOT_H - BOARD_T), (th["radius"] + 2.0) * math.cos(phl),
                (th["radius"] + 2.0) * math.sin(phl))

    # ---- case top surface polygons (canonical right half, world frame) ----
    polys = []
    tile = {}
    for k in finger_keys:
        x0, x1, y0, y1 = k.tile
        tile[(k.col, k.row)] = {n: pt(k.m, x, y) for n, (x, y) in
                                dict(il=(x0, y0), ol=(x1, y0), oh=(x1, y1), ih=(x0, y1)).items()}
        polys.append([tile[(k.col, k.row)][n] for n in ("il", "ol", "oh", "ih")])
    for c in range(len(COLUMNS) - 1):            # ruled webs between columns, two triangles per row
        for row in (1, 0, -1):
            a, b = tile[(c, row)], tile[(c + 1, row)]
            polys.append([a["ol"], b["il"], b["ih"]])
            polys.append([a["ol"], b["ih"], a["oh"]])
    # thumb plate: one planar arc band over the thumb slots (and the wheel)
    band_out, band_in = _band(th, 0, 3)
    thull3 = [pt(tp, x, y) for x, y in band_out + band_in[::-1]]
    polys.append(thull3)
    # bridge from the inner columns' front edge to the part of the thumb band's far edge that faces it
    fa = [tile[(0, -1)]["il"], tile[(0, -1)]["ol"], tile[(1, -1)]["il"], tile[(1, -1)]["ol"], tile[(2, -1)]["il"]]
    fb = [pt(tp, x, y) for x, y in band_out[::-1]]
    fb = [p for p in fb if fa[0][0] - 6.0 <= p[0] <= fa[-1][0] + 6.0]
    polys += _bridge(fa, fb)

    h.info["polys"] = polys
    h.info["thumb_band"] = thull3

    # ---- main board, battery, LRA, USB, wheel module (canonical frame) ----
    back = tile[(1, 1)]                              # c0/c1 top-row back edge = the back wall over the main board
    y_wall = min(back["oh"][1], back["ih"][1], tile[(0, 1)]["ih"][1])
    x_in = max(tile[(0, 1)]["ih"][0], tile[(0, 0)]["il"][0], tile[(0, -1)]["il"][0])
    mb_x0, mb_x1 = x_in + WALL + 1.0, x_in + WALL + 1.0 + 60.0
    mb_y1 = y_wall - WALL - 0.4
    mb_y0 = mb_y1 - 40.0
    mb_z0 = FLOOR_T + 3.0
    mb_z1 = mb_z0 + 1.6
    h.info["mb"] = (mb_x0, mb_x1, mb_y0, mb_y1, mb_z0, mb_z1)
    parts.append(("main board", box(mb_x0, mb_x1, mb_y0, mb_y1, mb_z0, mb_z1), "pcb", "main"))
    for i, (x, y) in enumerate(((mb_x0 + 3, mb_y0 + 3), (mb_x1 - 3, mb_y0 + 3), (mb_x0 + 3, mb_y1 - 3),
                                (mb_x1 - 3, mb_y1 - 3))):              # standoffs from the floor
        parts.append((f"standoff {i + 1}", Pos(x, y, (FLOOR_T + mb_z0) / 2) * Cylinder(2.2, mb_z0 - FLOOR_T),
                      "case_light", "main"))
    # MCU module (chip not chosen): a shielded module
    mx, my = mb_x0 + 30.0, mb_y0 + 22.0
    parts.append(("MCU module", box(mx - 9, mx + 9, my - 12, my + 12, mb_z1, mb_z1 + 3.0), "steel", "main"))
    parts.append(("MCU module pcb", box(mx - 9.5, mx + 9.5, my - 13, my + 13, mb_z1, mb_z1 + 0.6), "ic", "main"))
    parts.append(("haptic driver (DRV2605L)", box(mb_x0 + 10, mb_x0 + 13, mb_y0 + 5, mb_y0 + 8, mb_z1, mb_z1 + 0.9),
                  "ic", "main"))
    usb = []
    if wheel:
        # two USB-C upstream ports (host A, host B) through the back wall, a host-B controller and an isolator
        for tag, ux in (("A", mb_x0 + 12.0), ("B", mb_x0 + 26.0)):
            body = box(ux - 4.47, ux + 4.47, y_wall - 0.3 - 7.35, y_wall - 0.3, mb_z1, mb_z1 + 3.26)
            parts.append((f"USB-C {tag}", body, "usb", "main"))
            usb.append((tag, ux, y_wall, mb_z1 + 1.63))
        parts.append(("host-B controller", box(mb_x0 + 22, mb_x0 + 26, mb_y1 - 15, mb_y1 - 11, mb_z1, mb_z1 + 0.9),
                      "ic", "main"))
        parts.append(("digital isolator", box(mb_x0 + 13.5, mb_x0 + 18.5, mb_y1 - 15.5, mb_y1 - 10.5, mb_z1,
                                              mb_z1 + 1.5), "ic", "main"))
        parts.append(("wheel driver (DRV8316)", box(mb_x0 + 4, mb_x0 + 11, mb_y0 + 12, mb_y0 + 17, mb_z1,
                                                    mb_z1 + 0.9), "ic", "main"))
    h.info["usb"] = usb
    # battery: a LiPo pouch on the floor under the ring and pinky columns (size not chosen)
    ring_home = pt(cols[3]["keys"][1].m)
    bx0, by0 = mb_x1 + 3.0, ring_home[1] - 22.0
    parts.append(("battery", box(bx0, bx0 + 30.0, by0, by0 + 38.0, FLOOR_T + 0.5, FLOOR_T + 6.0), "battery",
                  "battery"))
    h.info["battery"] = (bx0, bx0 + 30.0, by0, by0 + 38.0)
    # coin LRA on the floor under the thumb home key
    hk = th["slots"][THUMB["home"]]
    lp = pt(hk)
    lra = Pos(lp[0], lp[1] - 4.0, FLOOR_T + 1.75) * Cylinder(5.0, 3.5)
    parts.append(("LRA", lra, "lra", "lra"))
    h.info["lra"] = (lp[0], lp[1] - 4.0, FLOOR_T + 3.5)

    # flex links: each column board's far end, down, then across to the main board
    for c in cols:
        p0 = c["board_end"]
        zl = mb_z1 + 2.0 + 0.4 * c["c"]
        p1 = np.array([p0[0], p0[1], zl])
        tx = np.clip(p0[0], mb_x0 + 4, mb_x1 - 4)
        ty = np.clip(p0[1], mb_y0 + 4, mb_y1 - 4)
        p2 = np.array([tx, ty, zl])
        links.append((f"link column {c['c']}", strip(p0, p1, c["board_wdir"], 8.0), "flex", "link"))
        if np.linalg.norm(p2 - p1) > 1.0:
            links.append((f"link column {c['c']} run", strip(p1, p2, (0, 0, 1) if abs(p2[2] - p1[2]) > 1 else
                                                             np.cross(p2 - p1, (0, 0, 1)), 8.0), "flex", "link"))
        p3 = np.array([tx, ty, mb_z1 + 0.2])
        links.append((f"link column {c['c']} drop", strip(p2, p3, (1, 0, 0), 8.0), "flex", "link"))
    p0 = tb_end                    # thumb board: down, under the inner column's front key, to the main board
    p1 = np.array([p0[0], p0[1], mb_z1 + 2.0])
    via = tile[(0, -1)]["il"]                    # the inner column's front-inner corner
    pv = np.array([via[0] + 5.0, via[1] - 6.0, mb_z1 + 2.0])
    p2 = np.array([mb_x0 + 7.0, mb_y0 + 4.0, mb_z1 + 2.0])
    links.append(("link thumb board", strip(p0, p1, tp[:3, 0], 6.0), "flex", "link"))
    links.append(("link thumb board run", strip(p1, pv, np.cross(pv - p1, (0, 0, 1)), 6.0), "flex", "link"))
    links.append(("link thumb board run 2", strip(pv, p2, np.cross(p2 - pv, (0, 0, 1)), 6.0), "flex", "link"))
    links.append(("link thumb board drop", strip(p2, p2 - (0, 0, 1.8), (1, 0, 0), 6.0), "flex", "link"))
    parts += [(n, sol, col, g) for n, sol, col, g in links]

    wheel_cut = []
    if wheel:
        w = WHEEL
        lw = loc(wheel_m)
        rz = w["axis_z"]
        y0m, y1m = -w["w"] / 2 - 1.0 - w["motor_l"], -w["w"] / 2 - 1.0
        tyre = ycyl(w["d"] / 2, -w["w"] / 2, w["w"] / 2, z=rz) - ycyl(w["d"] / 2 - 2.5, -6, 6, z=rz)
        parts.append(("wheel tyre", lw * tyre, "keycap_alt", "wheel"))
        parts.append(("wheel hub", lw * ycyl(w["d"] / 2 - 2.5, -w["w"] / 2 + 0.5, w["w"] / 2 - 0.5, z=rz),
                      "roller", "wheel"))
        parts.append(("wheel shaft", lw * ycyl(1.5, y0m - 4.5, w["w"] / 2 + 3.0, z=rz), "steel", "wheel"))
        parts.append(("gimbal motor", lw * ycyl(w["motor_d"] / 2, y0m, y1m, z=rz), "motor", "wheel"))
        parts.append(("encoder magnet", lw * ycyl(3.0, y0m - 3.0, y0m - 0.5, z=rz), "magnet", "wheel"))
        parts.append(("encoder board", lw * box(-6.5, 6.5, y0m - 4.8, y0m - 3.8, rz - 6.5, rz + 5.0), "pcb", "wheel"))
        parts.append(("encoder (MT6701CT)", lw * box(-2.5, 2.5, y0m - 3.8, y0m - 3.2, rz - 2.0, rz + 2.0), "ic",
                      "wheel"))
        # two cheeks hang from the plate's underside and carry the axle
        brk = (box(-4, 4, w["w"] / 2 + 1.5, w["w"] / 2 + 3.5, rz - 4.0, -2.3)
               + box(-7, 7, y0m - 7.5, y0m - 5.5, rz - 7.5, -2.3))
        parts.append(("wheel bracket", lw * brk, "case_light", "wheel"))
        # pod over the motor and encoder, and the cuts for the roller and the motor
        pod = ycyl(w["motor_d"] / 2 + 2.8, y0m - 6.0, y1m + 0.5, z=rz) & box(-30, 30, -60, 60, -PLATE_T, 30)
        h.info["pod"] = lw * pod
        # a pad in the thumb plane under the whole wheel module, so the case encloses it
        pad = [pt(wheel_m, x, y) for x, y in ((-14.5, y0m - 13.0), (14.5, y0m - 13.0), (14.5, 12.8), (-14.5, 12.8))]
        polys.append(pad)
        h.info["pad"] = pad
        wheel_cut = [lw * box(-w["d"] / 2 - 1.0, w["d"] / 2 + 1.0, -w["w"] / 2 - 0.8, w["w"] / 2 + 0.8, -5, 30),
                     lw * ycyl(w["motor_d"] / 2 + 0.8, y0m - 5.3, y1m + 0.2, z=rz)]

    if case:
        shell, floor = _case(h, polys, wheel_cut, usb)
        parts.append(("case top shell", shell, "case_light", "case"))
        parts.append(("case floor", floor, "case", "floor"))
        # board outlines come from the case: trim each board to the cavity, 0.6 mm clear of the walls
        trim = Pos(0, 0, FLOOR_T / 2) * extrude(_erode(h.info["footprint"], WALL + 0.6), 300.0)
        parts = [(n, (sol & trim) if g == "board" else sol, c, g) for n, sol, c, g in parts]

    h.parts = parts
    if side == "L":
        _mirror_half(h)
    if verbose:
        print(f"half {side} {preset}: {len(h.keys)} keys, {len(h.parts)} parts")
    return h


def _band(th, k0, k1, half=12.8, step=4.0):
    """Outer and inner edge of an arc band over thumb slots k0..k1, in the thumb plane's frame (origin at the arc
    centre). Both run from slot k0 to slot k1."""
    rt = th["radius"]
    out = []
    for r in (rt + half, rt - half):
        d = math.degrees(math.atan(half / r))
        a0, a1 = th["phis"][k0] - d, th["phis"][k1] + d
        k = max(2, int(abs(a1 - a0) / step) + 1)
        out.append([(r * math.cos(math.radians(a)), r * math.sin(math.radians(a))) for a in np.linspace(a0, a1, k)])
    return out


def _bridge(a, chain):
    """Triangulate the strip between two 3D polylines that run the same way. Returns triangles; each becomes a
    prism in the case union."""
    tris, i, j = [], 0, 0
    while i < len(a) - 1 or j < len(chain) - 1:
        if i == len(a) - 1 or (j < len(chain) - 1 and
                               np.linalg.norm(a[i] - chain[j + 1]) < np.linalg.norm(a[i + 1] - chain[j])):
            tri = [a[i], chain[j], chain[j + 1]]
            j += 1
        else:
            tri = [a[i], chain[j], a[i + 1]]
            i += 1
        if np.linalg.norm(np.cross(tri[1] - tri[0], tri[2] - tri[0])) > 1.0:
            tris.append(tri)
    return tris


def _case(h, polys, wheel_cut, usb):
    prisms = [prism_down(p) for p in polys]
    if "pod" in h.info:
        prisms.append(h.info["pod"])
    outer = prisms[0].fuse(*prisms[1:]).clean()
    outer = outer & box(-500, 500, -500, 500, 0.0, 300.0)
    foot = section(outer, Plane.XY.offset(FLOOR_T / 2))
    inner_foot = _erode(foot, WALL)
    # the section sketch sits at z = FLOOR_T / 2: lift it to the floor top before extruding the cavity
    inner = (Pos(0, 0, -PLATE_T) * outer) & (Pos(0, 0, FLOOR_T / 2) * extrude(inner_foot, 300.0))
    cut = [inner]
    for k in h.keys:
        cut.append(loc(k.m) * box(-HOLE / 2, HOLE / 2, -HOLE / 2, HOLE / 2, -6.0, 1.0))
    cut += wheel_cut
    for _tag, ux, yw, uz in usb:
        cut.append(box(ux - 5.0, ux + 5.0, yw - 6.0, yw + 2.0, uz - 2.1, uz + 2.1))
    case = outer.cut(*cut)
    shell = case & box(-500, 500, -500, 500, FLOOR_T, 300.0)
    floor = case & box(-500, 500, -500, 500, -1.0, FLOOR_T)
    h.info["footprint"] = foot
    return shell, floor


def _erode(sk, d, n=16):
    """Inset a 2D region by d: the intersection of copies shifted by d in n directions (robust where a 2D wire
    offset fails on the many short edges of the case outline)."""
    out = sk
    for i in range(n):
        a = 2 * math.pi * i / n
        out = out & (Pos(d * math.cos(a), d * math.sin(a), 0) * sk)
    return out


def _mirror_half(h):
    h.parts = [(n, mirror(sol, Plane.YZ), c, g) for n, sol, c, g in h.parts]
    for k, letters in zip([k for k in h.keys if not k.thumb], [l for col in LEFT_LETTERS for l in col]):
        k.name = letters
    for k in h.keys:
        k.m = MIRROR @ k.m @ MIRROR
    # parts were named before the letters changed: rename caps/switches of finger keys
    ren = {}
    for col, left in zip(COLUMNS, LEFT_LETTERS):
        for a, b in zip(col[5], left):
            ren[a] = b
    h.parts = [(_rename(n, ren), sol, c, g) for n, sol, c, g in h.parts]
    i = h.info
    i["up"] = MIRROR[:3, :3] @ i["up"]
    if i.get("wheel_m") is not None:
        i["wheel_m"] = MIRROR @ i["wheel_m"] @ MIRROR
    i["thumb"]["slots"] = [MIRROR @ m @ MIRROR for m in i["thumb"]["slots"]]
    i["thumb"]["plane"] = MIRROR @ i["thumb"]["plane"] @ MIRROR
    for c in i["cols"]:
        c["frame"] = MIRROR @ c["frame"] @ MIRROR
    x0, x1, y0, y1, z0, z1 = i["mb"]
    i["mb"] = (-x1, -x0, y0, y1, z0, z1)
    b = i["battery"]
    i["battery"] = (-b[1], -b[0], b[2], b[3])
    i["lra"] = (-i["lra"][0], i["lra"][1], i["lra"][2])
    i["usb"] = [(t, -ux, yw, uz) for t, ux, yw, uz in i["usb"]]
    i["polys"] = [[p * np.array([-1, 1, 1]) for p in poly] for poly in i["polys"]]
    i["thumb_band"] = [p * np.array([-1, 1, 1]) for p in i["thumb_band"]]
    if "pad" in i:
        i["pad"] = [p * np.array([-1, 1, 1]) for p in i["pad"]]
    if "footprint" in i:
        i["footprint"] = mirror(i["footprint"], Plane.YZ)


def _rename(n, ren):
    head, _, tail = n.rpartition(" ")
    return f"{head} {ren[tail]}" if head and tail in ren and head in ("cap", "switch", "switch base", "stem") else n


# ---------------------------------------------------------------------------------------------------------------
# Placing the halves, exploding
# ---------------------------------------------------------------------------------------------------------------
YAW = 10.0          # each half turned toward the centre line (illustrative)
GAP = 45.0          # between the innermost points of the two halves


def place(h, yaw=YAW, gap=GAP):
    """World transform for a half on the desk: turned by yaw toward the centre line, inner edges gap apart."""
    sgn = 1.0 if h.side == "R" else -1.0
    r = RZ(sgn * yaw)
    pts = np.array([p for poly in h.info["polys"] for p in poly])
    rp = (r[:3, :3] @ pts.T).T
    dx = gap / 2 - rp[:, 0].min() if h.side == "R" else -gap / 2 - rp[:, 0].max()
    return T(dx, 0, 0) @ r


def moved(items, m):
    lc = loc(m)
    return [(n, lc * s, c) for n, s, c in items]


EXPLODE = {"cap": 215.0, "switch": 172.0, "case": 112.0, "board": 34.0, "link": 34.0, "wheel": 34.0, "main": 0.0,
           "battery": -24.0, "lra": -24.0, "floor": -46.0}


def exploded(h, gaps=EXPLODE):
    """Parts moved apart along the half's tent normal, layer by layer."""
    up = h.info["up"]
    out = []
    for n, s, c, g in h.parts:
        d = gaps.get(g, 0.0) * up
        out.append((n, Pos(*d) * s, c))
    return out


# ---------------------------------------------------------------------------------------------------------------
# Keycap clearance gate (sketch of concept.md section 4.1)
# ---------------------------------------------------------------------------------------------------------------
DEPTHS = (0.0, 2.0, TRAVEL)
GATE_MARGIN = 0.5        # illustrative pass margin for the sketch (stands in for print tolerance), not a chosen value


def _pairs(h, reach=27.0):
    ks = h.keys
    out = []
    for i, a in enumerate(ks):
        for b in ks[i + 1:]:
            if np.linalg.norm(a.m[:3, 3] - b.m[:3, 3]) < reach:
                out.append((a, b))
    return out


def clearance_gate(h, with_case=True, thumb_only=False):
    """Every neighbouring keycap pair at rest, mid travel and bottom-out (each cap independently), and every cap
    against the case top shell and the wheel at the same depths. Returns rows sorted tightest first:
    dict(a, b, da, db, d, pa, pb)."""
    rows = []
    for a, b in _pairs(h):
        if thumb_only and not (a.thumb or b.thumb):
            continue
        best = None
        for da in DEPTHS:
            ca = a.cap(da)
            for db in DEPTHS:
                d, pa, pb = ca.distance_to_with_closest_points(b.cap(db))
                if best is None or d < best["d"] - 1e-9:
                    best = dict(a=a.name, b=b.name, da=da, db=db, d=d, pa=np.array(tuple(pa)), pb=np.array(tuple(pb)))
        rows.append(best)
    named = {n: s for n, s, _c, _g in h.parts}
    others = []
    if with_case and "case top shell" in named:
        others.append(("case", named["case top shell"]))
    for n in ("wheel tyre", "wheel bracket"):
        if n in named:
            others.append((n.split()[0] if n == "wheel tyre" else n, named[n]))
    for k in h.keys:
        if thumb_only and not k.thumb:
            continue
        for oname, osol in others:
            best = None
            for da in DEPTHS:
                d, pa, pb = k.cap(da).distance_to_with_closest_points(osol)
                if best is None or d < best["d"] - 1e-9:
                    best = dict(a=k.name, b=oname, da=da, db=0.0, d=d, pa=np.array(tuple(pa)), pb=np.array(tuple(pb)))
            rows.append(best)
    rows.sort(key=lambda r: r["d"])
    return rows


def interference(h, groups=("board", "link", "main", "battery", "lra", "wheel")):
    """Volume (mm^3) each internal part shares with the case shell and floor: should be ~0."""
    named = [(n, s) for n, s, _c, g in h.parts if g in groups]
    case = [s for n, s, _c, g in h.parts if g in ("case", "floor")]
    out = []
    for n, s in named:
        v = sum((s & c).volume for c in case)
        if v > 0.5:
            out.append((n, v))
    return out


if __name__ == "__main__":
    import time
    t0 = time.time()
    for side in ("L", "R"):
        h = build_half(side, "M", verbose=True)
        bb = None
        for n, s, _c, g in h.parts:
            if g in ("case", "floor"):
                b = s.bounding_box()
                print(f"  {n:16s} x {b.min.X:7.1f}..{b.max.X:7.1f}  y {b.min.Y:7.1f}..{b.max.Y:7.1f}  "
                      f"z {b.min.Z:6.1f}..{b.max.Z:6.1f}  vol {s.volume / 1000:7.1f} cm3")
        print("  shear keys:", [k.name for k in h.keys if k.shear])
        bad = interference(h)
        print("  internal parts touching the case:", bad if bad else "none")
        rows = clearance_gate(h)
        print("  tightest keycap clearances (state: depth of a / b in mm):")
        for r in rows[:8]:
            print(f"    {r['a']:>4s} vs {r['b']:<12s} {r['d']:5.2f} mm   (a at {r['da']:.0f}, b at {r['db']:.0f})")
        print(f"  ({time.time() - t0:.1f} s)")
