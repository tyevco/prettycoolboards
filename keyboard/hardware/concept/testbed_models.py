#!/usr/bin/env python3
"""Illustrative model of the rev A sensing testbed: a motherboard, plug-in coupons and a latency rig (build123d).

What it builds (mm, Z up, the motherboard's top copper at z = 0, +Y away from the viewer's front edge, X right). The
sizes and the arrangement follow the draft SPEC (keyboard/hardware/design/SPEC.md sections 2, 4.1, 7 and 9) and the
owner's decisions of 2026-11-26 (SPEC section 1: D1 no battery or charger on rev A, D2 a 2 x 20, 2.54 mm slot
connector, D3 a USB Type-C detect chip on I2C):

    motherboard   about 190 x 150 mm on four standoffs (M3 holes 4 mm in from the corners). Two rows of slots with
                  a strip between them (SPEC 9): S1-S3 (standard coupons) along the back, S4 and S5 (wide coupons)
                  and J_KVM along the front. Each slot is a 2 x 20, 2.54 mm female through-hole socket, 8.5 mm tall.
                  The strip carries, left to right: the USB-C (J1) on the left edge with its ESD array, VBUS TVS and
                  the Type-C detect chip (U_CC, an X2QFN-12-class body); the rev A MCU (STM32U5A5, drawn as its
                  LQFP100, turned so that PA11/PA12, pins 70/71, face J1) with a short high-speed pair from J1, the
                  16 MHz HSE crystal on PH0/PH1 (pins 12/13, the MCU's other side), the reset and BOOT0 buttons;
                  J_RIG (2 x 5, 2.54 mm) and J_SWD (STDC14, 2 x 7 at 1.27 mm); the I2C mux and three I/O
                  expanders; the test pads and the five JP_INJ solder jumpers; and the power section: the input breaker,
                  the two LDOs, and per slot a 3.3 V and a 5 V switch, two shunts, two INA226-class monitors
                  (VSSOP-10; 13 on the board with the VSYS, MCU and VDDUSB ones) and a meter jumper. One bus switch
                  per slot sits under its coupon, beside the socket. No battery connector and no charger (D1).
    coupons       each on a male 2 x 20 header, its underside 11 mm above the motherboard, held by the header and one
                  M3 nylon post at the far edge; each carries a descriptor EEPROM (SOIC-8):
                    Hall-effect   standard, 58 x 60: 6 keys over TMAG5253-class sensors, two switch-free reference
                                  sensors, two thermistors and a 3-to-8 decoder
                    TMR           standard: the same 6 keys over a TMR sensor (part not chosen)
                    shear         standard: 2 sites over TMAG5170s, a stock stem and a centring-stem prototype
                    coil DOE      wide, 80 x 60: 20 generated spirals (coils.py) read by LDC1614-class converters,
                                  2 stock switches
                    haptics       wide: DRV8316 + MT6701CT + gimbal motor and roller; DRV2605L + coin LRA; a
                                  capacitive strip on a touch controller; an I/O expander
                    KVM           optional, on J_KVM (2 x 6, 2.54 mm): drawn as a ghost, 20 x 40 mm here (the SPEC
                                  allows up to 50 x 40)
    latency rig   a separate 100 x 80 mm board: host MCU and stimulus drivers (parts not chosen), a USB-A host port
                  cabled to J1, and a 2 x 5 header with a ribbon to J_RIG, which carries the marker, trigger, frame
                  tick, SOF and the RIG_INJ stimulus (JP_INJ1 closed in the rig view takes RIG_INJ to slot S1)

    PY=/path/to/venv/bin/python          # build123d 0.13, numpy
    $PY keyboard/hardware/concept/testbed_models.py      # build everything, print part counts and bounding boxes

The renders are drawn by render_testbed.py.

Status: CONCEPT SKETCH. Nothing in keyboard/ is built or measured, and the SPEC is a draft on paper. The board and
coupon sizes are the SPEC's "about" figures (layout sets the exact outlines); the slot rows follow SPEC section 9;
every position inside them, the strip's arrangement, the coupons' contents and the rig's parts are this sketch's
illustrative placeholders, not a placement. Packages are generic classes (LQFP, VSSOP, SOT-23, TSSOP, X2QFN), not
datasheet drawings. The parts named are the SPEC's candidates, except the MCU (the owner's choice of 2026-11-26) and
the connector type (the owner's decision D2). The MCU's pin positions assume the LQFP's counter-clockwise numbering
and the SPEC's draft pin map. 16 MHz is in the U5 HS PHY's list of reference clocks (RM0456 Rev 7, read in a
third-party transcription; ST's HAL and Zephyr's PHY driver agree: SPEC 5.2, 11 #5, closed). Solder-mask colours only
tell the coupons apart.
"""
import math
import re
from dataclasses import dataclass, field

import numpy as np
from build123d import Box, Compound, Cylinder, Plane, Pos, RectangleRounded, Rot, loft

import coils as CO

# ---------------------------------------------------------------------------------------------------------------
# Constants (mm). The board and coupon sizes are the SPEC's "about" figures; everything else is illustrative.
# ---------------------------------------------------------------------------------------------------------------
MB_W, MB_D = 190.0, 150.0      # motherboard (SPEC 2: about 190 x 150 mm)
STD = (58.0, 60.0)             # standard coupon (about 58 x 60 mm)
WIDE = (80.0, 60.0)            # wide coupon (about 80 x 60 mm)
PCB_T = 1.6
STANDOFF = 10.0                # motherboard standoff height under the board (SPEC 9)
MEZZ = 11.0                    # coupon PCB bottom above the motherboard top (8.5 mm socket + 2.5 mm header spacer)
SOCKET_H = 8.5
SLOT_N = 20                    # 2 x 20 positions (owner's decision D2)
HDR_IN = 4.5                   # slot header centre, in from the coupon's strip-side edge
PITCH = 19.05
HOLES = ((4.0, 4.0), (MB_W - 4.0, 4.0), (4.0, MB_D - 4.0), (MB_W - 4.0, MB_D - 4.0))
STRIP = (62.0, 88.0)           # y range of the uncovered strip between the slot rows

MASK = {                       # solder-mask colours: only to tell the boards apart
    "mother": (0.10, 0.45, 0.20),
    "hall": (0.13, 0.30, 0.62),
    "tmr": (0.40, 0.24, 0.55),
    "shear": (0.62, 0.17, 0.17),
    "coil": (0.09, 0.10, 0.11),
    "haptics": (0.86, 0.86, 0.83),
    "kvm": (0.55, 0.58, 0.64),
    "rig": (0.85, 0.70, 0.16),
}
GOLD = (0.86, 0.70, 0.30)
CAP = (0.72, 0.60, 0.45)
RES = (0.10, 0.10, 0.11)
DARK = (0.04, 0.04, 0.05)
WHITE_PLASTIC = (0.90, 0.90, 0.88)
NYLON = (0.93, 0.92, 0.86)
RIBBON = (0.70, 0.71, 0.74)
STRIPE = (0.80, 0.14, 0.16)
LED = (0.98, 0.84, 0.36)
SOLDER = (0.80, 0.81, 0.83)


# ---------------------------------------------------------------------------------------------------------------
# A triangle mesh that quacks like a build123d shape (for cables, ribbons and copper drawn from polylines)
# ---------------------------------------------------------------------------------------------------------------
class _P:
    __slots__ = ("X", "Y", "Z")

    def __init__(self, x, y, z):
        self.X, self.Y, self.Z = x, y, z


class MeshSolid:
    """Vertices (N, 3) and triangles (M, 3). tessellate() returns what render_lib.mesh expects of a build123d shape,
    so these go through render_lib.export_glb too."""

    def __init__(self, v, t):
        self.v = np.asarray(v, float)
        self.t = np.asarray(t, int)

    def tessellate(self, _tol=None, _angular=None):
        return [_P(*p) for p in self.v], [tuple(int(i) for i in tri) for tri in self.t]

    def moved(self, dx, dy, dz):
        return MeshSolid(self.v + (dx, dy, dz), self.t)

    @staticmethod
    def merge(parts):
        vs, ts, n = [], [], 0
        for p in parts:
            vs.append(p.v)
            ts.append(p.t + n)
            n += len(p.v)
        return MeshSolid(np.vstack(vs), np.vstack(ts))


def move(shape, dx=0.0, dy=0.0, dz=0.0):
    if isinstance(shape, MeshSolid):
        return shape.moved(dx, dy, dz)
    return Pos(dx, dy, dz) * shape


def moved(items, dx=0.0, dy=0.0, dz=0.0):
    return [(it[0], move(it[1], dx, dy, dz)) + tuple(it[2:]) for it in items]


def bezier(ctrl, n=48):
    """Points on a Bezier curve through the control polygon `ctrl` (de Casteljau)."""
    c = np.asarray(ctrl, float)
    out = []
    for t in np.linspace(0, 1, n):
        p = c.copy()
        while len(p) > 1:
            p = (1 - t) * p[:-1] + t * p[1:]
        out.append(p[0])
    return np.array(out)


def _frames(path):
    p = np.asarray(path, float)
    tg = np.gradient(p, axis=0)
    tg /= np.linalg.norm(tg, axis=1, keepdims=True) + 1e-12
    a = np.array([0.0, 0.0, 1.0]) if abs(tg[0][2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    n = [np.cross(tg[0], a)]
    n[0] /= np.linalg.norm(n[0])
    for i in range(1, len(p)):            # parallel transport
        v = n[-1] - np.dot(n[-1], tg[i]) * tg[i]
        n.append(v / (np.linalg.norm(v) + 1e-12))
    n = np.array(n)
    b = np.cross(tg, n)
    return tg, n, b


def tube(path, r, k=12, caps=True):
    """A round cable along a 3D polyline."""
    p = np.asarray(path, float)
    _tg, n, b = _frames(p)
    th = np.linspace(0, 2 * np.pi, k, endpoint=False)
    ring = (np.cos(th)[None, :, None] * n[:, None, :] + np.sin(th)[None, :, None] * b[:, None, :]) * r
    v = (p[:, None, :] + ring).reshape(-1, 3)
    tris = []
    for i in range(len(p) - 1):
        for j in range(k):
            a0, a1 = i * k + j, i * k + (j + 1) % k
            b0, b1 = a0 + k, a1 + k
            tris += [(a0, a1, b1), (a0, b1, b0)]
    if caps:
        c0, c1 = len(v), len(v) + 1
        v = np.vstack([v, p[0], p[-1]])
        last = (len(p) - 1) * k
        for j in range(k):
            tris += [(c0, (j + 1) % k, j), (c1, last + j, last + (j + 1) % k)]
    return MeshSolid(v, tris)


def ribbon(path, wdir, width, thick):
    """A flat cable along a 3D polyline whose width stays as close to `wdir` as the path allows."""
    p = np.asarray(path, float)
    tg = np.gradient(p, axis=0)
    tg /= np.linalg.norm(tg, axis=1, keepdims=True) + 1e-12
    w = np.asarray(wdir, float)[None, :] - (tg @ np.asarray(wdir, float))[:, None] * tg
    w /= np.linalg.norm(w, axis=1, keepdims=True) + 1e-12
    nn = np.cross(tg, w)
    corners = [(+1, +1), (-1, +1), (-1, -1), (+1, -1)]
    v = np.concatenate([p + sw * w * width / 2 + sn * nn * thick / 2 for sw, sn in corners], 0)
    n = len(p)
    tris = []
    for c in range(4):
        c2 = (c + 1) % 4
        for i in range(n - 1):
            a0, a1, b0, b1 = c * n + i, c * n + i + 1, c2 * n + i, c2 * n + i + 1
            tris += [(a0, a1, b1), (a0, b1, b0)]
    for i in (0, n - 1):
        q = [c * n + i for c in range(4)]
        tris += [(q[0], q[1], q[2]), (q[0], q[2], q[3])]
    return MeshSolid(v, tris)


def flat_band(points, width, z):
    """A flat copper trace (single-sided strip) at height z along a 2D centreline."""
    p = np.asarray(points, float)
    o = CO.band(p, width)
    n = len(p)
    left, right = o[:n], o[n:][::-1]
    v = np.vstack([np.c_[left, np.full(n, z)], np.c_[right, np.full(n, z)]])
    tris = []
    for i in range(n - 1):
        tris += [(i, i + 1, n + i + 1), (i, n + i + 1, n + i)]
    return MeshSolid(v, tris)


def slab(x0, x1, y0, y1, z0, z1, step=6.0):
    """A box as a gridded triangle mesh (no slivers): used for the boards, whose faces are big and thin."""
    vs, ts = [], []

    def quad_grid(o, du, dv, nu, nv):
        n0 = sum(len(v) for v in vs)
        g = np.array([[o + du * (i / nu) + dv * (j / nv) for i in range(nu + 1)] for j in range(nv + 1)]).reshape(-1, 3)
        t = []
        for j in range(nv):
            for i in range(nu):
                a = j * (nu + 1) + i
                t += [(a, a + 1, a + nu + 2), (a, a + nu + 2, a + nu + 1)]
        vs.append(g)
        ts.append(np.array(t) + n0)

    lx, ly, lz = x1 - x0, y1 - y0, z1 - z0
    nx, ny, nz = max(1, int(math.ceil(lx / step))), max(1, int(math.ceil(ly / step))), 1
    X, Y, Z = np.array([lx, 0, 0]), np.array([0, ly, 0]), np.array([0, 0, lz])
    o = np.array([x0, y0, z0], float)
    quad_grid(o + Z, X, Y, nx, ny)          # top
    quad_grid(o, Y, X, ny, nx)              # bottom
    quad_grid(o, X, Z, nx, nz)              # front (y0)
    quad_grid(o + Y, Z, X, nz, nx)          # back (y1)
    quad_grid(o, Z, Y, nz, ny)              # left (x0)
    quad_grid(o + X, Y, Z, ny, nz)          # right (x1)
    return MeshSolid(np.vstack(vs), np.vstack(ts))


def disc(x, y, d, z, k=20):
    th = np.linspace(0, 2 * np.pi, k, endpoint=False)
    v = np.vstack([[x, y, z], np.c_[x + d / 2 * np.cos(th), y + d / 2 * np.sin(th), np.full(k, z)]])
    return MeshSolid(v, [(0, 1 + j, 1 + (j + 1) % k) for j in range(k)])


def ring(x, y, d0, d1, z, k=20):
    th = np.linspace(0, 2 * np.pi, k, endpoint=False)
    c, s = np.cos(th), np.sin(th)
    v = np.vstack([np.c_[x + d1 / 2 * c, y + d1 / 2 * s, np.full(k, z)],
                   np.c_[x + d0 / 2 * c, y + d0 / 2 * s, np.full(k, z)]])
    t = []
    for j in range(k):
        j1 = (j + 1) % k
        t += [(j, j1, k + j1), (j, k + j1, k + j)]
    return MeshSolid(v, t)


# ---------------------------------------------------------------------------------------------------------------
# Solid primitives
# ---------------------------------------------------------------------------------------------------------------
def box(x0, x1, y0, y1, z0, z1):
    return Pos((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2) * Box(x1 - x0, y1 - y0, z1 - z0)


def cbox(w, d, z0, z1, x=0.0, y=0.0):
    return box(x - w / 2, x + w / 2, y - d / 2, y + d / 2, z0, z1)


def zcyl(x, y, d, z0, z1):
    return Pos(x, y, (z0 + z1) / 2) * Cylinder(d / 2, z1 - z0)


def xcyl(y, z, d, x0, x1):
    return Pos((x0 + x1) / 2, y, z) * (Rot(0, 90, 0) * Cylinder(d / 2, x1 - x0))


def rr_loft(w0, d0, r0, z0, w1, d1, r1, z1, x=0.0, y=0.0):
    s = loft([Plane.XY.offset(z0) * RectangleRounded(w0, d0, r0),
              Plane.XY.offset(z1) * RectangleRounded(w1, d1, r1)], ruled=True)
    return Pos(x, y, 0) * s


def comp(shapes):
    shapes = [s for s in shapes if s is not None]
    return Compound(shapes) if len(shapes) > 1 else shapes[0]


def _r(w, d, rot):
    return (d, w) if rot in (90, 270) else (w, d)


# ---------------------------------------------------------------------------------------------------------------
# Packages and connectors (z0 = the board's top surface). Sizes are generic package classes, not datasheet drawings.
# ---------------------------------------------------------------------------------------------------------------
def qfn(name, x, y, w, z0, h=0.9, d=None, dot=True):
    """QFN-class body with its perimeter pads showing and a pin-1 dot."""
    d = d or w
    items = [(name, cbox(w, d, z0, z0 + h, x, y), "ic")]
    pads = []
    n = max(int(w / 0.5) - 2, 3)
    for i in range(n):
        o = (i - (n - 1) / 2) * 0.5
        pads += [cbox(0.25, 0.3, z0, z0 + 0.06, x + o, y - d / 2 - 0.1),
                 cbox(0.25, 0.3, z0, z0 + 0.06, x + o, y + d / 2 + 0.1)]
    m = max(int(d / 0.5) - 2, 3)
    for i in range(m):
        o = (i - (m - 1) / 2) * 0.5
        pads += [cbox(0.3, 0.25, z0, z0 + 0.06, x - w / 2 - 0.1, y + o),
                 cbox(0.3, 0.25, z0, z0 + 0.06, x + w / 2 + 0.1, y + o)]
    items.append((name + " pads", comp(pads), "steel"))
    if dot:
        r = min(0.5, w * 0.22)
        items.append((name + " pin 1", zcyl(x - w / 2 + max(0.7, r), y + d / 2 - max(0.7, r), r, z0 + h,
                                            z0 + h + 0.02), (0.6, 0.6, 0.6)))
    return items


def _gullwing(reach, zm, t=0.15, w=0.22):
    """One gull-wing lead as (vertices (4k, 3), triangles) in a local (r, s, z) frame: r outward from the body edge,
    s across the lead, z up from the board. It leaves the body at mid-height, bends down and ends in a flat foot."""
    prof = np.array([(-0.05, zm), (0.20, zm), (0.30, zm - 0.10), (0.40, t / 2 + 0.10), (0.50, t / 2),
                     (reach, t / 2)])
    o = CO.band(prof, t)
    k = len(prof)
    top, bot = o[:k], o[k:][::-1]
    v = np.vstack([np.c_[top[:, 0], np.full(k, -w / 2), top[:, 1]], np.c_[bot[:, 0], np.full(k, -w / 2), bot[:, 1]],
                   np.c_[top[:, 0], np.full(k, w / 2), top[:, 1]], np.c_[bot[:, 0], np.full(k, w / 2), bot[:, 1]]])
    A, B, C, D = 0, k, 2 * k, 3 * k
    tris = []
    for i in range(k - 1):
        for p, q in ((A, C), (B, D), (A, B), (C, D)):       # top, bottom and the two side faces
            tris += [(p + i, p + i + 1, q + i + 1), (p + i, q + i + 1, q + i)]
    for i in (0, k - 1):                                     # end caps
        tris += [(A + i, B + i, D + i), (A + i, D + i, C + i)]
    return v, np.array(tris)


def lqfp(name, x, y, z0, body=14.0, span=16.0, n_side=25, pitch=0.5, h=1.4, standoff=0.1, rot=0):
    """LQFP-class package: a body with n_side gull-wing leads per side and a pin-1 dot. The defaults are an LQFP100
    14 x 14 mm at 0.5 mm pitch, 16 mm tip to tip, 1.4 mm body (the JEDEC MS-026 class outline, not a datasheet
    drawing). rot = 0 puts pin 1 at the top-left corner (pins counted counter-clockwise from there, seen from above);
    rot = 180 turns the package, pin 1 to the bottom-right."""
    items = [(name, cbox(body, body, z0 + standoff, z0 + standoff + h, x, y), "ic")]
    lv, lt = _gullwing((span - body) / 2, standoff + h / 2)
    leads = []
    for i in range(n_side):
        s = (i - (n_side - 1) / 2) * pitch
        r, ss, z = lv[:, 0], lv[:, 1] + s, lv[:, 2] + z0
        for px, py in ((x + body / 2 + r, y + ss), (x - body / 2 - r, y + ss),
                       (x + ss, y + body / 2 + r), (x + ss, y - body / 2 - r)):
            leads.append(MeshSolid(np.c_[px, py, z], lt))
    items.append((name + " gull-wing leads", MeshSolid.merge(leads), "steel"))
    sx, sy = (-1, 1) if rot == 0 else (1, -1)
    items.append((name + " pin 1", zcyl(x + sx * (body / 2 - 1.4), y + sy * (body / 2 - 1.4), 1.0, z0 + standoff + h,
                                        z0 + standoff + h + 0.02), (0.6, 0.6, 0.6)))
    return items


def sop(name, x, y, z0, body=(4.9, 3.9), n=4, pitch=1.27, h=1.5, rot=0, lead=1.05):
    """SOIC / SOP / MSOP / VSSOP / TSSOP-class gull-wing package. body = (along the pin rows, across)."""
    bl, bw = body
    leads = []
    for i in range(n):
        o = (i - (n - 1) / 2) * pitch
        for s in (-1, 1):
            y0, y1 = s * bw / 2, s * (bw / 2 + lead)
            wl = min(0.4, pitch * 0.55)
            if rot in (0, 180):
                leads.append(box(x + o - wl / 2, x + o + wl / 2, y + min(y0, y1), y + max(y0, y1), z0, z0 + 0.15))
            else:
                leads.append(box(x + min(y0, y1), x + max(y0, y1), y + o - wl / 2, y + o + wl / 2, z0, z0 + 0.15))
    w, d = _r(bl, bw, rot)
    return [(name, cbox(w, d, z0 + 0.1, z0 + h, x, y), "ic"), (name + " leads", comp(leads), "steel")]


def sot23(name, x, y, z0, rot=0):
    return sop(name, x, y, z0, body=(2.9, 1.6), n=3, pitch=0.95, h=1.1, rot=rot, lead=0.5)


def vssop10(name, x, y, z0, rot=0):
    """MSOP / VSSOP-10 class (the INA226's DGS package class): 3 x 3 mm body, 0.5 mm pitch, 4.9 mm across the leads."""
    return sop(name, x, y, z0, body=(3.0, 3.0), n=5, pitch=0.5, h=1.0, rot=rot, lead=0.95)


def tssop(name, x, y, z0, pins, rot=0):
    """TSSOP class, 0.65 mm pitch, 4.4 mm body, 6.4 mm across the leads (TSSOP-14: 5.0 mm long, -24: 7.8 mm)."""
    return sop(name, x, y, z0, body=({14: 5.0, 16: 5.0, 24: 7.8}[pins], 4.4), n=pins // 2, pitch=0.65, h=1.1,
               rot=rot, lead=1.0)


def soic8(name, x, y, z0, rot=0):
    return sop(name, x, y, z0, body=(4.9, 3.9), n=4, pitch=1.27, h=1.5, rot=rot, lead=1.05)


def sot223(name, x, y, z0):
    """SOT-223 class: 6.5 x 3.5 mm body, the wide tab to +y, three leads to -y."""
    leads = [box(x - 1.5, x + 1.5, y + 1.75, y + 3.4, z0, z0 + 0.2)]
    for dx in (-2.3, 0.0, 2.3):
        leads.append(box(x + dx - 0.35, x + dx + 0.35, y - 3.4, y - 1.75, z0, z0 + 0.2))
    return [(name, cbox(6.5, 3.5, z0 + 0.1, z0 + 1.7, x, y), "ic"), (name + " leads", comp(leads), "steel")]


def passive(name, x, y, z0, size=(1.6, 0.8), h=0.6, rot=0, colour=CAP):
    w, d = _r(size[0], size[1], rot)
    e = min(0.3, size[0] * 0.25)
    if rot in (0, 180):
        ends = comp([box(x - w / 2, x - w / 2 + e, y - d / 2, y + d / 2, z0, z0 + h + 0.02),
                     box(x + w / 2 - e, x + w / 2, y - d / 2, y + d / 2, z0, z0 + h + 0.02)])
    else:
        ends = comp([box(x - w / 2, x + w / 2, y - d / 2, y - d / 2 + e, z0, z0 + h + 0.02),
                     box(x - w / 2, x + w / 2, y + d / 2 - e, y + d / 2, z0, z0 + h + 0.02)])
    return [(name, cbox(w, d, z0, z0 + h, x, y), colour), (name + " ends", ends, "steel")]


def c0402(name, x, y, z0, rot=0, colour=CAP):
    return passive(name, x, y, z0, size=(1.0, 0.5), h=0.5, rot=rot, colour=colour)


def usb_c(name, x, y, z0, facing="-x"):
    """USB-C receptacle (mid-mount-ish envelope): shell 7.35 deep x 8.94 wide x 3.26 tall, the mouth at `facing`."""
    shell = box(x - 3.675, x + 3.675, y - 4.47, y + 4.47, z0, z0 + 3.26)
    if facing == "-x":
        mouth = box(x - 3.70, x - 3.66, y - 4.17, y + 4.17, z0 + 0.35, z0 + 2.91)
        tongue = box(x - 3.72, x - 3.70, y - 3.3, y + 3.3, z0 + 1.45, z0 + 1.85)
    else:  # "+x"
        mouth = box(x + 3.66, x + 3.70, y - 4.17, y + 4.17, z0 + 0.35, z0 + 2.91)
        tongue = box(x + 3.70, x + 3.72, y - 3.3, y + 3.3, z0 + 1.45, z0 + 1.85)
    return [(name, shell, "usb"), (name + " mouth", mouth, DARK), (name + " tongue", tongue, "sensor")]


def usb_a(name, x, y, z0):
    """USB-A receptacle (host port), mouth facing +x: 14 deep x 13.1 wide x 5.7 tall."""
    shell = box(x - 7.0, x + 7.0, y - 6.55, y + 6.55, z0, z0 + 5.7)
    mouth = box(x + 6.96, x + 7.02, y - 6.0, y + 6.0, z0 + 0.5, z0 + 5.2)
    tongue = box(x + 7.02, x + 7.05, y - 5.6, y + 5.6, z0 + 2.9, z0 + 4.4)
    return [(name, shell, "usb"), (name + " mouth", mouth, DARK), (name + " tongue", tongue, WHITE_PLASTIC)]


def _grid(x, y, rows, n, pitch, axis):
    """Pin centres of a rows x n array along `axis`, centred on (x, y)."""
    pts = []
    for i in range(n):
        o = (i - (n - 1) / 2) * pitch
        for j in range(rows):
            s = (j - (rows - 1) / 2) * pitch
            pts.append((x + o, y + s) if axis == "x" else (x + s, y + o))
    return pts


def pin_header(name, x, y, z0, rows=2, n=5, pitch=2.54, axis="x", body_h=2.5, pin_up=6.0, pin_w=0.64):
    """Unshrouded male pin header standing on a board: an insulator `body_h` tall, the pins `pin_up` above it."""
    L, W = pitch * n, pitch * rows + (0.9 if pitch < 2 else 0.0)
    w, d = (L, W) if axis == "x" else (W, L)
    pins = [cbox(pin_w, pin_w, z0 + body_h, z0 + body_h + pin_up, px, py)
            for px, py in _grid(x, y, rows, n, pitch, axis)]
    return [(name, cbox(w, d, z0, z0 + body_h, x, y), "sensor"), (name + " pins", comp(pins), GOLD)]


def idc_plug(name, x, y, z0, n=5, axis="y", h=9.0):
    """2 x n IDC ribbon socket pushed onto a pin header whose insulator top is at z0."""
    L = 2.54 * n + 5.0
    w, d = (6.0, L) if axis == "y" else (L, 6.0)
    return [(name, cbox(w, d, z0, z0 + h, x, y), (0.16, 0.16, 0.18))]


def socket_2xn(name, x, y, z0, n=SLOT_N, long_axis="x", h=SOCKET_H):
    """Female 2 x n socket (2.54 mm, through-hole) on the motherboard, its contact holes drawn as dark squares."""
    L = 2.54 * n
    w, d = (5.08, L) if long_axis == "y" else (L, 5.08)
    body = cbox(w, d, z0, z0 + h, x, y)
    holes = [cbox(0.9, 0.9, z0 + h, z0 + h + 0.03, px, py) for px, py in _grid(x, y, 2, n, 2.54, long_axis)]
    return [(name, body, "sensor"), (name + " contacts", comp(holes), DARK)]


def socket_under(name, x, y, z_top, n=6, long_axis="x", h=SOCKET_H):
    """Female 2 x n socket hanging under a coupon (z_top = the coupon's underside), contact holes at its bottom."""
    L = 2.54 * n
    w, d = (5.08, L) if long_axis == "y" else (L, 5.08)
    body = cbox(w, d, z_top - h, z_top, x, y)
    holes = [cbox(0.9, 0.9, z_top - h - 0.03, z_top - h, px, py) for px, py in _grid(x, y, 2, n, 2.54, long_axis)]
    return [(name, body, "sensor"), (name + " contacts", comp(holes), DARK)]


def header_2xn(name, x, y, z_top, n=SLOT_N, long_axis="x", spacer=2.5, pin=6.0):
    """Male 2 x n header under a coupon: spacer just under the board (z_top = the coupon's underside), pins below."""
    L = 2.54 * n
    w, d = (5.08, L) if long_axis == "y" else (L, 5.08)
    body = cbox(w, d, z_top - spacer, z_top, x, y)
    pins = [cbox(0.64, 0.64, z_top - spacer - pin, z_top - spacer, px, py)
            for px, py in _grid(x, y, 2, n, 2.54, long_axis)]
    return [(name + " spacer", body, "sensor"), (name + " pins", comp(pins), GOLD)]


def header_joints(name, x, y, z_top, n=SLOT_N, long_axis="x", rows=2, pitch=2.54):
    """The through-hole joints of a header as seen on the board's top: a pad per pin and the pin's tail."""
    pts = _grid(x, y, rows, n, pitch, long_axis)
    pads = MeshSolid.merge([disc(px, py, 1.55, z_top + 0.03, k=14) for px, py in pts])
    tails = comp([cbox(0.64, 0.64, z_top, z_top + 1.0, px, py) for px, py in pts])
    return [(name + " pads", pads, GOLD), (name + " tails", tails, GOLD)]


def jumper(name, x, y, z0, axis="x"):
    """A 1 x 2 meter jumper: a 2.54 mm header with a shunt cap pushed on (closed)."""
    w, d = (5.08, 2.54) if axis == "x" else (2.54, 5.08)
    cw, cd = (5.0, 2.4) if axis == "x" else (2.4, 5.0)
    return [(name + " header", cbox(w, d, z0, z0 + 2.5, x, y), "sensor"),
            (name + " cap", cbox(cw, cd, z0 + 2.5, z0 + 8.3, x, y), (0.16, 0.16, 0.18))]


def solder_jumper(name, x, y, z0, closed=False):
    """Two half pads (open by default); closed, a solder bridge joins them."""
    halves = comp([box(x - 1.15, x - 0.15, y - 0.75, y + 0.75, z0, z0 + 0.04),
                   box(x + 0.15, x + 1.15, y - 0.75, y + 0.75, z0, z0 + 0.04)])
    items = [(name + " pads", halves, GOLD)]
    if closed:
        items.append((name + " solder bridge", box(x - 1.0, x + 1.0, y - 0.55, y + 0.55, z0, z0 + 0.35), SOLDER))
    return items


def crystal(name, x, y, z0):
    return [(name + " base", cbox(3.2, 2.5, z0, z0 + 0.3, x, y), CAP),
            (name, cbox(3.0, 2.3, z0 + 0.3, z0 + 0.8, x, y), "steel")]


def tact(name, x, y, z0):
    return [(name, cbox(4.0, 4.0, z0, z0 + 1.0, x, y), "steel"),
            (name + " button", zcyl(x, y, 2.4, z0 + 1.0, z0 + 1.5), DARK)]


def pad(name, x, y, z0, d=1.5, colour=GOLD):
    return [(name, disc(x, y, d, z0 + 0.03), colour)]


def standoff_under(name, x, y, z_board_bottom, h=STANDOFF, d=5.0):
    return [(name, zcyl(x, y, d, z_board_bottom - h, z_board_bottom), "steel")]


def screw_head(name, x, y, z0, d=5.5, colour="steel"):
    return [(name, zcyl(x, y, d, z0, z0 + 1.6), colour),
            (name + " slot", cbox(d * 0.8, 0.5, z0 + 1.6, z0 + 1.62, x, y), DARK)]


def nylon_post(name, x, y, z0, z1, d=5.0):
    return [(name, zcyl(x, y, d, z0, z1), NYLON)]


# ---------------------------------------------------------------------------------------------------------------
# Keys (switch bottom on the coupon top, z0)
# ---------------------------------------------------------------------------------------------------------------
def mx_switch(tag, x, y, z0, stem="stem", housing="switch"):
    """Generic PCB-mount MX-style switch: bottom housing, top housing, stem. Not any one product."""
    bottom = cbox(13.9, 13.9, z0, z0 + 5.0, x, y)
    top = comp([cbox(15.6, 15.6, z0 + 5.0, z0 + 6.0, x, y),
                rr_loft(15.6, 15.6, 0.6, z0 + 6.0, 11.6, 11.6, 1.5, z0 + 11.6, x, y)])
    st = comp([cbox(5.6, 5.6, z0 + 11.6, z0 + 12.6, x, y), cbox(4.1, 1.3, z0 + 12.6, z0 + 16.0, x, y),
               cbox(1.3, 4.1, z0 + 12.6, z0 + 16.0, x, y)])
    return [(f"{tag} switch base", bottom, housing), (f"{tag} switch top", top, housing), (f"{tag} stem", st, stem)]


def centring_stem_switch(tag, x, y, z0):
    """Sketch of the custom centring-stem prototype: a carrier on four slender flexure posts (concept.md 2.1)."""
    base = cbox(15.6, 15.6, z0, z0 + 2.0, x, y)
    posts = comp([zcyl(x + 5.0 * sx, y + 5.0 * sy, 1.2, z0 + 2.0, z0 + 10.0) for sx in (-1, 1) for sy in (-1, 1)])
    roof = cbox(13.4, 13.4, z0 + 10.0, z0 + 11.0, x, y) - zcyl(x, y, 9.0, z0 + 9.9, z0 + 11.1)
    carrier = zcyl(x, y, 8.2, z0 + 3.0, z0 + 11.6)
    st = comp([zcyl(x, y, 5.6, z0 + 11.6, z0 + 12.6), cbox(4.1, 1.3, z0 + 12.6, z0 + 16.0, x, y),
               cbox(1.3, 4.1, z0 + 12.6, z0 + 16.0, x, y)])
    return [(f"{tag} proto base", base, "tpu"), (f"{tag} flexure posts", posts, "tpu"),
            (f"{tag} proto roof", roof, "tpu"), (f"{tag} carrier", carrier, "case_light"), (f"{tag} stem", st, "stem")]


def keycap(tag, x, y, z0, colour="keycap"):
    """Simple solid keycap (no dish): 18.2 square skirt at z0 + 10.4, 13 x 14 top at z0 + 18.0."""
    return [(f"{tag} keycap", rr_loft(18.2, 18.2, 1.6, z0 + 10.4, 13.0, 14.0, 2.0, z0 + 18.0, x, y), colour)]


# ---------------------------------------------------------------------------------------------------------------
# Coupons. Local frame: the coupon's front-left corner at the origin, its PCB from z = 0 to PCB_T. Each coupon's
# slot header runs along its strip-side edge (the front edge in the back row, the back edge in the front row), and
# its M3 nylon post stands at a corner of the far edge.
# ---------------------------------------------------------------------------------------------------------------
@dataclass
class Coupon:
    key: str
    title: str
    slot: str
    x0: float
    y0: float
    w: float
    d: float
    parts: list = field(default_factory=list)       # on the coupon (move with it)
    keys: list = field(default_factory=list)        # switches and keycaps (lifted further in the exploded view)
    header: tuple = (0.0, 0.0, "x")                 # slot header centre (local) and long axis
    n: int = SLOT_N                                 # positions per row
    post: tuple = (0.0, 0.0)                        # support post (local)
    ghost: bool = False
    female: bool = False                            # True: a female socket on the coupon over a male header (J_KVM)
    pcb_cut: object = None

    def pcb(self):
        if self.pcb_cut is None:
            return slab(0, self.w, 0, self.d, 0, PCB_T)
        return box(0, self.w, 0, self.d, 0, PCB_T) - self.pcb_cut

    def items(self, lift=0.0, key_lift=0.0, with_keys=True, with_header=True):
        """World-frame items: the coupon at its slot, `lift` above its seated height, keys `key_lift` higher."""
        x0, y0, z0 = self.x0, self.y0, MEZZ + lift
        hx, hy, ax = self.header
        px, py = self.post
        own = [(f"{self.title} PCB", self.pcb(), MASK[self.key])] + self.parts
        own += header_joints(f"{self.title} header", hx, hy, PCB_T, n=self.n, long_axis=ax)
        own += screw_head(f"{self.title} post screw", px, py, PCB_T, d=5.0, colour=NYLON)
        if with_header:
            if self.female:
                own += socket_under(f"{self.title} socket", hx, hy, 0.0, n=self.n, long_axis=ax)
            else:
                own += header_2xn(f"{self.title} header", hx, hy, 0.0, n=self.n, long_axis=ax)
            own += nylon_post(f"{self.title} post", px, py, -MEZZ, 0.0)
        out = moved(own, x0, y0, z0)
        if with_keys:
            out += moved(self.keys, x0, y0, z0 + key_lift)
        return out

    def socket_xy(self):
        hx, hy, _ax = self.header
        return self.x0 + hx, self.y0 + hy

    def socket_items(self):
        """What stays on the motherboard: the slot's female socket, or J_KVM's male header."""
        hx, hy, ax = self.header
        x, y = self.x0 + hx, self.y0 + hy
        if self.female:
            return pin_header(f"J_KVM ({self.title})", x, y, 0.0, rows=2, n=self.n, axis=ax)
        return socket_2xn(f"{self.slot} socket ({self.title})", x, y, 0.0, n=self.n, long_axis=ax)

    def centre(self, z_extra=0.0, lift=0.0):
        return np.array([self.x0 + self.w / 2, self.y0 + self.d / 2, MEZZ + PCB_T + lift + z_extra])

    def world(self, lx, ly, z_extra=0.0, lift=0.0):
        """A point given in the coupon's local frame, in world coordinates (z above the coupon's top)."""
        return np.array([self.x0 + lx, self.y0 + ly, MEZZ + PCB_T + lift + z_extra])


T = PCB_T       # coupon top in its local frame
KEY_ROWS = (25.0, 25.0 + PITCH)        # key coupon rows (local y), behind the front strip
FRONT_Y = 11.5                         # the key coupons' front strip (reference sensors, thermistors, decoder, EEPROM)
KEY_EEPROM_X = 21.0                    # the descriptor EEPROM's x on the key coupons (local)


def _key_coupon(key, title, slot, x0, y0, sensor_kind):
    """Hall-effect or TMR coupon: 3 x 2 keys, and in front two switch-free reference sensors, two thermistors, the
    3-to-8 select decoder and the descriptor EEPROM."""
    w, d = STD
    c = Coupon(key, title, slot, x0, y0, w, d, header=(w / 2, HDR_IN, "x"), post=(w - 4.5, d - 3.5))
    cols = (w / 2 - PITCH, w / 2, w / 2 + PITCH)
    k = 0
    for yy in KEY_ROWS:
        for xx in cols:
            k += 1
            if sensor_kind == "hall":
                c.parts += sot23(f"{title} TMAG5253 {k}", xx, yy, T)
            else:
                c.parts += qfn(f"{title} TMR sensor {k}", xx, yy, 2.5, T, h=0.75, dot=False)
            c.parts += c0402(f"{title} C{k}", xx + 3.2, yy - 2.6, T)
            c.keys += mx_switch(f"{title} K{k}", xx, yy, T)
            c.keys += keycap(f"{title} K{k}", xx, yy, T)
    # the front strip: no switch over these
    for i, xx in enumerate((5.5, w - 5.5)):
        if sensor_kind == "hall":
            c.parts += sot23(f"{title} reference sensor {i + 1}", xx, FRONT_Y, T)
        else:
            c.parts += qfn(f"{title} reference sensor {i + 1}", xx, FRONT_Y, 2.5, T, h=0.75, dot=False)
    for i, xx in enumerate((12.5, w - 12.5)):
        c.parts += passive(f"{title} thermistor {i + 1}", xx, FRONT_Y, T, size=(1.6, 0.8), colour=RES)
    c.parts += soic8(f"{title} descriptor EEPROM", KEY_EEPROM_X, FRONT_Y, T)
    c.parts += tssop(f"{title} 3-to-8 decoder", 32.0, FRONT_Y, T, 16)
    c.parts += c0402(f"{title} C EEPROM", 26.2, FRONT_Y, T, rot=90)
    c.parts += c0402(f"{title} C decoder", 37.2, FRONT_Y, T, rot=90)
    return c


def hall_coupon(x0, y0):
    return _key_coupon("hall", "Hall-effect coupon", "S1", x0, y0, "hall")


def tmr_coupon(x0, y0):
    return _key_coupon("tmr", "TMR coupon", "S2", x0, y0, "tmr")


SHEAR_SITES = ((17.0, 33.0, "stock"), (41.0, 33.0, "proto"))


def shear_coupon(x0, y0):
    """Two TMAG5170 sites side by side: a stock stem (left) and the centring-stem prototype (right), blue keycaps."""
    w, d = STD
    c = Coupon("shear", "Shear coupon", "S3", x0, y0, w, d, header=(w / 2, HDR_IN, "x"), post=(w - 4.5, d - 3.5))
    for i, (xx, yy, kind) in enumerate(SHEAR_SITES):
        c.parts += sop(f"Shear coupon TMAG5170 {i + 1}", xx, yy, T, body=(3.0, 3.0), n=4, pitch=0.65, h=1.0,
                       lead=0.95)
        c.parts += c0402(f"Shear coupon C{i + 1}", xx + 4.2, yy - 4.0, T)
        if kind == "stock":
            c.keys += mx_switch(f"Shear S{i + 1}", xx, yy, T)
        else:
            c.keys += centring_stem_switch(f"Shear S{i + 1}", xx, yy, T)
        c.keys += keycap(f"Shear S{i + 1}", xx, yy, T, colour="keycap_accent")
    c.parts += soic8("Shear coupon descriptor EEPROM", w / 2, FRONT_Y, T)
    c.parts += c0402("Shear coupon C EEPROM", w / 2 + 5.2, FRONT_Y, T, rot=90)
    for i, xx in enumerate((12.0, 46.0)):
        c.parts += c0402(f"Shear coupon R ALERT {i + 1}", xx, FRONT_Y, T, colour=RES)
    return c


COIL_PITCH = (12.5, 12.0)
COIL_ORIGIN = (9.0, 8.0)
COIL_SWITCH_TAGS = ("B2", "B4")        # stock switches shown on two coils (illustrative)
COIL_LEAD_ANGLE = 0.0                  # the outer ends (and the leads) point to +x
COIL_LEAD = 1.3                        # lead stub beyond the outer turn
COIL_LDC = [(72.0, 10.0 + 9.0 * i) for i in range(5)]   # the five LDC1614-class converters (local)
COIL_EEPROM = (72.5, 53.5)


def coil_coupon(x0, y0, pts_per_turn=64):
    """20 generated spirals (coils.doe_layout) under black mask, five LDC1614-class converters, two stock switches.
    Only each coil's top copper layer is drawn in 3D; render_testbed.py draws every layer in its 2D view."""
    w, d = WIDE
    c = Coupon("coil", "Coil coupon", "S4", x0, y0, w, d, header=(w / 2, d - HDR_IN, "x"), post=(w - 3.5, 3.5))
    zc = T + 0.015
    copper, vias = [], []
    for coil, (cx, cy) in CO.doe_layout(COIL_PITCH, COIL_ORIGIN):
        layers, vv = CO.coil_layers(coil, (cx, cy), pts_per_turn=pts_per_turn, end_angle=COIL_LEAD_ANGLE)
        top = layers[0].points
        lead_end = top[0] + (COIL_LEAD, 0.0)
        copper.append(flat_band(np.vstack([lead_end, top]), coil.trace, zc))
        for vx, vy, _l in vv:
            vias.append(ring(vx, vy, 0.25, 0.55, zc + 0.003, k=12))
        # the lead pair leaves to +x and drops to the converters through vias (routing not drawn)
        vias.append(ring(lead_end[0], lead_end[1], 0.25, 0.55, zc + 0.003, k=12))
        vias.append(ring(lead_end[0], lead_end[1] - 1.0, 0.25, 0.55, zc + 0.003, k=12))
        if coil.tag in COIL_SWITCH_TAGS:
            c.keys += mx_switch(f"Coil {coil.tag}", cx, cy, T)
    c.parts.append(("coil copper (top layer)", MeshSolid.merge(copper), "copper"))
    c.parts.append(("coil vias", MeshSolid.merge(vias), GOLD))
    # MX centre-post holes, drawn as dark discs (not cut, as for the motherboard)
    holes = [disc(cx, cy, MX_HOLE_D, zc + 0.006, k=28) for coil, (cx, cy) in CO.doe_layout(COIL_PITCH, COIL_ORIGIN)
             if coil.tag not in COIL_SWITCH_TAGS]
    c.parts.append(("MX centre-post holes", MeshSolid.merge(holes), DARK))
    for i, (xx, yy) in enumerate(COIL_LDC):
        c.parts += qfn(f"LDC1614-class converter {i + 1}", xx, yy, 4.0, T, h=0.8)
        c.parts += c0402(f"Coil coupon C{i + 1}", xx, yy + 3.4, T)
    c.parts += soic8("Coil coupon descriptor EEPROM", COIL_EEPROM[0], COIL_EEPROM[1], T, rot=90)
    return c


MX_HOLE_D = CO.MX_CENTRE_HOLE


def wheel_module(ax0, ay, top, axis_h=18.0):
    """Gimbal motor with a roller over its bell, axis along +X, on a printed bracket, with the encoder PCB behind
    (MT6701CT facing a diametric magnet on the shaft). Simplified from mechanism_models.thumb_wheel."""
    zc = top + axis_h
    x = ax0
    items = []
    epcb = box(x, x + 1.6, ay - 8.0, ay + 8.0, top, zc + 8.0)
    enc = box(x + 1.6, x + 3.1, ay - 1.95, ay + 1.95, zc - 2.45, zc + 2.45)
    items += [("encoder PCB", epcb, MASK["mother"]), ("MT6701CT", enc, "ic")]
    items.append(("encoder right-angle header", box(x - 2.6, x, ay - 5.1, ay + 5.1, top, top + 2.5), "sensor"))
    items.append(("diametric magnet", xcyl(ay, zc, 6.0, x + 3.6, x + 5.6), "highlight"))
    items.append(("shaft", xcyl(ay, zc, 4.0, x + 5.0, x + 19.0), "steel"))
    bx = x + 6.0
    brk = box(bx, bx + 1.8, ay - 13.0, ay + 13.0, top, zc + 10.0) + box(bx - 5.0, bx + 6.8, ay - 13.0, ay + 13.0,
                                                                         top, top + 1.6)
    brk -= xcyl(ay, zc, 6.0, bx - 0.1, bx + 2.0)
    items.append(("motor bracket", brk, "case_light"))
    mx = bx + 1.8
    items.append(("stator base", xcyl(ay, zc, 16.0, mx, mx + 2.0), "motor"))
    items.append(("rotor bell", xcyl(ay, zc, 28.0, mx + 2.0, mx + 9.0), "motor"))
    hub = xcyl(ay, zc, 31.0, mx + 2.0, mx + 12.0) - xcyl(ay, zc, 28.2, mx + 1.9, mx + 9.1)
    items.append(("roller hub", hub, "keycap_alt"))
    items.append(("roller tyre", xcyl(ay, zc, 34.0, mx + 2.6, mx + 11.4) - xcyl(ay, zc, 30.0, mx + 2.5, mx + 11.5),
                  "rubber"))
    return items


WHEEL = (4.0, 33.0)            # haptics coupon: the encoder board's x and the motor axis's y (local)
ROLLER_X = WHEEL[0] + 14.8     # the roller's centre along x (local)
LRA_XY = (68.0, 24.0)
TOUCH_PADS = [(29.0 + 6.0 * i, 5.0) for i in range(6)]


def haptics_coupon(x0, y0):
    w, d = WIDE
    c = Coupon("haptics", "Haptics coupon", "S5", x0, y0, w, d, header=(w / 2, d - HDR_IN, "x"), post=(w - 3.5, 3.5))
    c.parts += wheel_module(WHEEL[0], WHEEL[1], T)
    c.parts += qfn("DRV8316", 34.0, 31.0, 7.0, T, d=5.0)        # VQFN-class 7 x 5
    c.parts += passive("DRV8316 C1", 38.8, 35.0, T, size=(1.6, 0.8), rot=90)
    c.parts += passive("DRV8316 C2", 40.8, 35.0, T, size=(1.6, 0.8), rot=90)
    c.parts += qfn("haptics I/O expander", 34.0, 43.0, 3.0, T, h=0.8)
    c.parts += soic8("Haptics coupon descriptor EEPROM", 46.0, 43.0, T)
    # coin LRA and its driver
    c.parts.append(("coin LRA", zcyl(LRA_XY[0], LRA_XY[1], 10.0, T, T + 2.7), "lra"))
    c.parts.append(("LRA flex tail", box(LRA_XY[0] - 0.5, LRA_XY[0] + 0.5, LRA_XY[1] + 5.0, LRA_XY[1] + 7.5, T,
                                         T + 0.1), "flex"))
    c.parts += sop("DRV2605L", LRA_XY[0], LRA_XY[1] + 11.5, T, body=(3.0, 3.0), n=5, pitch=0.5, h=1.0, lead=0.8)
    # capacitive strip: six pads along the front edge, and a touch controller
    for i, (xx, yy) in enumerate(TOUCH_PADS):
        c.parts.append((f"touch pad {i + 1}", box(xx - 2.6, xx + 2.6, yy - 3.0, yy + 3.0, T, T + 0.03), GOLD))
    c.parts += qfn("touch controller", 44.0, 14.0, 3.0, T, h=0.8)
    return c


KVM_SIZE = (20.0, 40.0)        # the SPEC allows the KVM coupon up to 50 x 40 mm; this sketch's is smaller


def kvm_coupon(x0, y0):
    """Optional: host-B controller (CH32X035 / CH32V305 class) and a digital isolator over an isolation slot, on a
    female socket over J_KVM (a 2 x 6 male header on the motherboard)."""
    w, d = KVM_SIZE
    c = Coupon("kvm", "KVM coupon", "J_KVM", x0, y0, w, d, header=(w / 2, d - HDR_IN, "x"), n=6, post=(4.0, 4.0),
               ghost=True, female=True)
    c.parts += usb_c("USB-C B", w - 3.675 + 1.0, 12.0, T, facing="+x")
    c.parts += qfn("host-B controller", 7.5, 11.0, 4.0, T)
    c.parts += soic8("isolator", w / 2, 22.0, T)
    c.pcb_cut = box(2.5, w - 2.5, 21.6, 22.4, -1.0, 3.0)
    for i, (xx, yy) in enumerate(((7.5, 15.5), (4.0, 27.0), (16.0, 27.0), (7.5, 29.0))):
        c.parts += passive(f"KVM C{i + 1}", xx, yy, T)
    return c


# ---------------------------------------------------------------------------------------------------------------
# Slots on the motherboard (SPEC 9: S1-S3 along the back, S4, S5 and J_KVM along the front, a strip between)
# ---------------------------------------------------------------------------------------------------------------
def coupons():
    return [
        hall_coupon(7.0, 88.0),
        tmr_coupon(66.0, 88.0),
        shear_coupon(125.0, 88.0),
        coil_coupon(7.0, 2.0),
        haptics_coupon(88.0, 2.0),
        kvm_coupon(169.0, 22.0),
    ]


# The strip (y 62-88), left to right. Positions are this sketch's, not a placement.
USB_C_PORT = (2.675, 71.25)      # J1 (x is the receptacle's centre; its mouth at x = -1), on the left edge
MCU_XY = (24.5, 75.0)            # the STM32U5A5's centre: an LQFP100, 16 mm tip to tip, turned 180 degrees
MCU_NAME = "STM32U5A5 (rev A MCU)"
MCU_ROT = 180                    # PA11/PA12 (pins 70/71) at y = 71.0 / 71.5 on the left side, facing J1
HSE_XY = (36.2, 74.75)           # the 16 MHz HSE crystal, beside PH0/PH1 (pins 12/13) on the MCU's right side
ESD_XY = (10.5, 71.25)           # TPD4E05U06-class ESD array on the pair (and on CC1/CC2)
TYPEC_XY = (9.5, 81.0)           # U_CC, the USB Type-C detect chip (X2QFN-12 class, 1.6 x 1.6 mm), on I2C1
TVS_XY = (14.5, 85.5)            # VBUS TVS (SOD-123FL class), with the VBUS bulk below it
RESET_XY, BOOT_XY = (42.5, 81.0), (42.5, 68.5)
RIG_HEADER = (50.0, 75.0)        # J_RIG, 2 x 5 at 2.54 mm
SWD_XY = (57.5, 75.0)            # J_SWD, STDC14: 2 x 7 at 1.27 mm
LOGIC = {"I2C mux": (67.0, 82.5), "I/O expander 1": (76.5, 82.5), "I/O expander 2": (67.0, 67.5),
         "I/O expander 3": (76.5, 67.5)}
INJ_JUMPERS = [(85.0 + 3.0 * i, 64.5) for i in range(5)]       # JP_INJ1-5, open by default
INJ_PADS = [(85.0 + 3.0 * i, 67.3) for i in range(5)]
TEST_PADS = [(85.0 + 2.4 * i, 76.0 + 3.0 * j) for j in range(3) for i in range(6)]
BREAKER_XY = (102.5, 84.0)       # input breaker U2 (VQFN-10 class, 2 x 2 mm)
LDO_SLOT_XY = (106.5, 66.5)      # +3V3_SLOT LDO (SOT-223 class)
LDO_3V3_XY = (106.0, 75.5)       # +3V3 always-on LDO (SOT-23-5 class)
CELL_X0, CELL_W = 118.0, 14.0    # one power cell per slot, S1 to S5 left to right
# the USB high-speed pair from J1 to the MCU, straight and short (centreline)
HS_PAIR = [(USB_C_PORT[0] + 3.675, USB_C_PORT[1]), (MCU_XY[0] - 8.0, USB_C_PORT[1])]


def _cell(n, z, closed=False):
    """Slot n's power cell: a 3.3 V and a 5 V switch with their limit resistors, a shunt and an INA226-class monitor
    per rail with Kelvin test pads, a meter jumper on the 3.3 V rail and the slot LED. S5's 5 V switch is a second
    breaker (VQFN class) on a bigger shunt."""
    cx = CELL_X0 + CELL_W * (n - 1)
    it = []
    it += sot23(f"S{n} 3V3 switch", cx + 2.3, 84.0, z)
    it += c0402(f"S{n} 3V3 limit R", cx + 2.3, 81.3, z, colour=RES)
    it += passive(f"S{n} 3V3 shunt", cx + 6.6, 84.0, z, size=(3.2, 1.6), h=0.55, colour=RES)
    it += vssop10(f"S{n} 3V3 INA226", cx + 11.2, 83.6, z)
    it += c0402(f"S{n} 3V3 INA226 C", cx + 11.2, 80.2, z)
    if n == 5:
        it += qfn("S5 5V breaker", cx + 2.3, 66.0, 2.0, z, h=0.75)
        it += passive("S5 5V shunt", cx + 6.6, 66.6, z, size=(6.3, 3.2), h=0.6, rot=90, colour=RES)
    else:
        it += sot23(f"S{n} 5V switch", cx + 2.3, 66.0, z)
        it += passive(f"S{n} 5V shunt", cx + 6.6, 66.0, z, size=(3.2, 1.6), h=0.55, colour=RES)
    it += c0402(f"S{n} 5V limit R", cx + 2.3, 68.9, z, colour=RES)
    it += vssop10(f"S{n} 5V INA226", cx + 11.2, 66.4, z)
    it += c0402(f"S{n} 5V INA226 C", cx + 11.2, 69.8, z)
    for k, (px, py) in enumerate(((cx + 5.4, 81.9), (cx + 7.8, 81.9), (cx + 5.0, 71.0), (cx + 8.2, 71.0))):
        it += pad(f"S{n} Kelvin pad {k + 1}", px, py, z, d=0.9)
    it += jumper(f"S{n} meter jumper", cx + 4.2, 76.0, z)
    it += passive(f"S{n} LED", cx + 10.4, 76.0, z, size=(1.6, 0.8), h=0.55, colour=LED)
    return it


def motherboard(with_sockets=True, cps=None, closed_jumpers=()):
    z = 0.0
    # holes are drawn as screw heads, not cut: a face with holes tessellates into long slivers that slow the renders
    items = [("motherboard PCB", slab(0, MB_W, 0, MB_D, -PCB_T, 0), MASK["mother"])]
    for i, (x, y) in enumerate(HOLES):
        items += standoff_under(f"standoff {i}", x, y, -PCB_T)
        items += screw_head(f"screw {i}", x, y, z)
    # USB-C J1 with the ESD array on the pair and CC lines, the VBUS TVS and bulk, and the Type-C detect chip with
    # its four passives (VDD 100 nF, ADDR 4.7 k, INT_N 200 k, VBUS_DET 887 k)
    items += usb_c("USB-C", USB_C_PORT[0], USB_C_PORT[1], z, facing="-x")
    items += qfn("USB ESD array", ESD_XY[0], ESD_XY[1], 1.0, z, h=0.55, d=2.5, dot=False)
    items += passive("VBUS TVS", TVS_XY[0], TVS_XY[1], z, size=(3.6, 1.8), h=1.0, colour="ic")
    items += passive("VBUS C", TVS_XY[0], TVS_XY[1] - 3.0, z, size=(2.0, 1.25), h=0.9)
    items += qfn("Type-C detect U_CC", TYPEC_XY[0], TYPEC_XY[1], 1.6, z, h=0.4)
    for k, (dx, dy) in enumerate(((-2.1, 0.0), (2.1, 0.0), (-2.1, -2.6), (2.1, -2.6))):
        items += c0402(f"U_CC passive {k + 1}", TYPEC_XY[0] + dx, TYPEC_XY[1] + dy, z, rot=90,
                       colour=CAP if k == 0 else RES)
    centre = np.asarray(HS_PAIR)
    items.append(("USB HS pair copper", MeshSolid.merge([flat_band(centre + (0.0, s), 0.3, z + 0.01)
                                                         for s in (-0.3, 0.3)]), (0.30, 0.68, 0.36)))
    # the rev A MCU (STM32U5A5, LQFP100) with its decoupling, VCAP and the VDDA filter, and the 16 MHz HSE crystal
    # with its load capacitors
    items += lqfp(MCU_NAME, MCU_XY[0], MCU_XY[1], z, rot=MCU_ROT)
    for k, (x, y) in enumerate(((19.0, 84.6), (22.0, 84.6), (28.0, 84.6), (31.0, 84.6), (19.0, 65.4),
                                (22.0, 65.4), (27.0, 65.4), (30.0, 65.4))):
        items += c0402(f"MCU C{k}", x, y, z)
    items += passive("VCAP C", 34.6, 81.6, z, size=(2.0, 1.25), h=0.9, rot=90)
    items += passive("VDDA ferrite", 33.9, 66.6, z, size=(1.6, 0.8), h=0.6, rot=90, colour=(0.22, 0.22, 0.24))
    items += crystal("HSE crystal (16 MHz)", HSE_XY[0], HSE_XY[1], z)
    for k, dy in enumerate((-1.15, 1.15)):
        items += c0402(f"HSE load C{k}", HSE_XY[0] + 2.9, HSE_XY[1] + dy, z)
    items += tact("reset button", RESET_XY[0], RESET_XY[1], z)
    items += tact("BOOT0 button", BOOT_XY[0], BOOT_XY[1], z)
    # J_RIG (latency rig) and J_SWD (STDC14)
    items += pin_header("J_RIG rig header", RIG_HEADER[0], RIG_HEADER[1], z, rows=2, n=5, axis="y")
    items += pin_header("J_SWD (STDC14)", SWD_XY[0], SWD_XY[1], z, rows=2, n=7, pitch=1.27, axis="y", body_h=1.5,
                        pin_up=1.6, pin_w=0.4)
    # test pads, and the JP_INJ solder jumpers (open by default) with a pad on each slot's INJ
    for k, (x, y) in enumerate(INJ_JUMPERS):
        items += solder_jumper(f"JP_INJ{k + 1}", x, y, z, closed=(k + 1) in closed_jumpers)
    for k, (x, y) in enumerate(INJ_PADS):
        items += pad(f"INJ pad {k + 1}", x, y, z, d=1.3)
    for k, (x, y) in enumerate(TEST_PADS):
        items += pad(f"test pad {k + 1}", x, y, z, d=1.3)
    # the I2C mux and the three I/O expanders (TSSOP-24 class)
    for name, (x, y) in LOGIC.items():
        items += tssop(name, x, y, z, 24)
    # power, no charger and no battery (D1): the input breaker with its VSYS shunt and monitor, the bulk, the two
    # LDOs, the MCU's and VDDUSB's shunts and monitors, then one cell per slot
    items += qfn("input breaker U2", BREAKER_XY[0], BREAKER_XY[1], 2.0, z, h=0.75)
    items += c0402("U2 C dVdT", BREAKER_XY[0], BREAKER_XY[1] - 2.4, z)
    items += c0402("U2 C ITIMER", BREAKER_XY[0] - 2.0, BREAKER_XY[1], z, rot=90)
    items += passive("VSYS shunt", 108.2, 84.2, z, size=(6.3, 3.2), h=0.6, colour=RES)
    items += vssop10("VSYS INA226", 114.6, 84.0, z)
    items += passive("VSYS bulk", 101.6, 76.0, z, size=(3.2, 2.5), h=1.6, rot=90)
    items += sop("+3V3 LDO", LDO_3V3_XY[0], LDO_3V3_XY[1], z, body=(2.9, 1.6), n=3, pitch=0.95, h=1.1, lead=0.5)
    items += passive("+3V3_MCU shunt", 110.0, 75.5, z, size=(2.0, 1.25), h=0.5, rot=90, colour=RES)
    items += vssop10("+3V3_MCU INA226", 114.6, 75.5, z)
    items += sot223("+3V3_SLOT LDO", LDO_SLOT_XY[0], LDO_SLOT_XY[1], z)
    items += passive("+3V3_USB shunt", 111.6, 67.0, z, size=(2.0, 1.25), h=0.5, rot=90, colour=RES)
    items += vssop10("+3V3_USB INA226", 114.6, 66.6, z)
    for n in range(1, 6):
        items += _cell(n, z)
    # under the coupons (parts there stay under 6 mm, SPEC 9): each slot's bus switch beside its socket, and the
    # KVM's 5 V switch beside J_KVM
    for c in (cps or coupons()):
        sx, sy = c.socket_xy()
        if c.female:
            items += sot23("KVM 5V switch", sx - 6.0, sy - 6.0, z)
        else:
            items += tssop(f"{c.slot} bus switch", sx, sy + (7.0 if sy > MB_D / 2 else -7.0), z, 14)
    if with_sockets:
        for c in (cps or coupons()):
            items += c.socket_items()
    return items


def assembly(lift=0.0, key_lift=0.0, cps=None, keep=None):
    """(solid items, ghost items). lift: one height for every coupon, or {coupon key: height}. keep: the coupon keys
    to include (default: all)."""
    cps = cps or coupons()
    items = motherboard(cps=cps)
    ghost = []
    for c in cps:
        if keep is not None and c.key not in keep:
            continue
        h = lift.get(c.key, 0.0) if isinstance(lift, dict) else lift
        (ghost if c.ghost else items).extend(c.items(lift=h, key_lift=key_lift))
    return items, ghost


# ---------------------------------------------------------------------------------------------------------------
# Latency rig (a separate 100 x 80 mm board, SPEC 2, left of the motherboard)
# ---------------------------------------------------------------------------------------------------------------
RIG = dict(x0=-160.0, x1=-60.0, y0=36.0, y1=116.0)
RIG_IDC = (-70.0, 104.0)                 # the rig's 2 x 5 header for the ribbon
RIG_USB_A = (-66.0, USB_C_PORT[1])       # in line with J1, its mouth 1 mm past the rig's edge, facing +x
RIG_MCU = (-122.0, 84.0)


def latency_rig():
    """The rig board: high-speed USB host MCU, stimulus drivers and a DAC (parts not chosen), a USB-A host port and
    the 2 x 5 header for the ribbon to J_RIG."""
    r = RIG
    z = 0.0
    items = [("rig PCB", slab(r["x0"], r["x1"], r["y0"], r["y1"], -PCB_T, 0), MASK["rig"])]
    for i, x in enumerate((r["x0"] + 4, r["x1"] - 4)):
        for j, y in enumerate((r["y0"] + 4, r["y1"] - 4)):
            items += standoff_under(f"rig standoff {i}{j}", x, y, -PCB_T)
            items += screw_head(f"rig screw {i}{j}", x, y, z)
    items += lqfp("rig host MCU (not chosen)", RIG_MCU[0], RIG_MCU[1], z, body=10.0, span=12.0, n_side=16)
    items += crystal("rig crystal", RIG_MCU[0], RIG_MCU[1] - 10.0, z)
    items += soic8("rig stimulus driver 1 (not chosen)", -98.0, 58.0, z)
    items += soic8("rig stimulus driver 2 (not chosen)", -86.0, 58.0, z)
    items += vssop10("rig DAC (not chosen)", -110.0, 58.0, z)
    for k, (x, y) in enumerate(((-130.0, 84.0), (-114.0, 84.0), (-122.0, 92.0), (-92.0, 64.0), (-104.0, 64.0),
                                (-80.0, 64.0))):
        items += passive(f"rig C{k}", x, y, z, size=(1.6, 0.8), rot=90 if k < 2 else 0)
    items += usb_a("rig USB-A (host port)", RIG_USB_A[0], RIG_USB_A[1], z)
    items += pin_header("rig header", RIG_IDC[0], RIG_IDC[1], z, rows=2, n=5, axis="y")
    items += tact("rig start button", -152.0, 108.0, z)
    return items


IDC_Z = 2.5                              # the IDC sockets sit on the headers' insulators
IDC_H = 9.0


def rig_paths():
    """Centrelines (N, 3) of the USB cable and the ribbon (also used to place the callouts)."""
    ux, uy, zc = USB_C_PORT[0] - 3.675, USB_C_PORT[1], 1.63
    ax_, ay_, za = RIG_USB_A[0] + 7.0, RIG_USB_A[1], 2.85
    p0, p1 = np.array([ax_ + 19.0, ay_, za]), np.array([ux - 17.0, uy, zc])
    usb = bezier([p0, p0 + (12, -4, 0), (-30.0, 44.0, 2.0), p1 + (-12, -4, 0), p1], 64)
    zt = IDC_Z + IDC_H
    a = np.array([RIG_IDC[0], RIG_IDC[1], zt])
    b = np.array([RIG_HEADER[0], RIG_HEADER[1], zt])
    rib = bezier([a, a + (0, 0, 30), b + (0, 0, 30), b], 80)
    return dict(usb=usb, ribbon=rib)


def rig_cables():
    """USB cable (USB-A plug at the rig, USB-C plug in J1), and the ribbon on IDC sockets at both headers."""
    items = []
    paths = rig_paths()
    plug = (0.18, 0.18, 0.20)
    # USB-C plug into J1 (its mouth at x = -1.0)
    ux, uy = USB_C_PORT[0] - 3.675, USB_C_PORT[1]
    zc = 1.63
    items.append(("USB-C plug", box(ux - 13.0, ux - 0.5, uy - 6.0, uy + 6.0, zc - 3.0, zc + 3.0), plug))
    items.append(("USB-C plug strain relief", xcyl(uy, zc, 4.2, ux - 17.0, ux - 13.0), plug))
    # USB-A plug into the rig's host port
    ax_, ay_ = RIG_USB_A[0] + 7.0, RIG_USB_A[1]
    za = 2.85
    items.append(("USB-A plug", box(ax_ + 0.5, ax_ + 15.0, ay_ - 8.0, ay_ + 8.0, za - 4.0, za + 4.0), plug))
    items.append(("USB-A plug strain relief", xcyl(ay_, za, 4.2, ax_ + 15.0, ax_ + 19.0), plug))
    items.append(("USB cable", tube(paths["usb"], 1.9), (0.22, 0.22, 0.24)))
    # ribbon: IDC sockets on both 2 x 5 headers, the cable arching over between them
    items += idc_plug("rig IDC socket", RIG_IDC[0], RIG_IDC[1], IDC_Z)
    items += idc_plug("J_RIG IDC socket", RIG_HEADER[0], RIG_HEADER[1], IDC_Z)
    rp = paths["ribbon"]
    items.append(("ribbon", ribbon(rp, (0, 1, 0), 12.7, 0.9), RIBBON))
    stripe = rp + (0, -6.0, 0.0)
    items.append(("ribbon pin-1 stripe", ribbon(stripe, (0, 1, 0), 0.9, 0.95), STRIPE))
    return items


# ---------------------------------------------------------------------------------------------------------------
def _bbox(items):
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
    for it in items:
        s = it[1]
        if isinstance(s, MeshSolid):
            v = s.v
        else:
            bb = s.bounding_box()
            v = np.array([[bb.min.X, bb.min.Y, bb.min.Z], [bb.max.X, bb.max.Y, bb.max.Z]])
        lo, hi = np.minimum(lo, v.min(0)), np.maximum(hi, v.max(0))
    return lo, hi


def _footprints(items, z_max=6.0):
    """(name, x0, x1, y0, y1, z1) of each solid on the motherboard (its z range starting near the board's top)."""
    out = []
    for it in items:
        lo, hi = _bbox([it])
        out.append((it[0], lo[0], hi[0], lo[1], hi[1], hi[2]))
    return out


def check(verbose=True):
    """Sketch-level checks: coupons inside the board and apart, clear of the corner screws; strip parts inside the
    strip; parts under a coupon at most 6 mm tall (SPEC 9); no two motherboard parts' outlines overlapping."""
    cps = coupons()
    probs = []
    rects = [(c.title, c.x0, c.x0 + c.w, c.y0, c.y0 + c.d) for c in cps]
    for t, x0, x1, y0, y1 in rects:
        if x0 < 0 or y0 < 0 or x1 > MB_W or y1 > MB_D:
            probs.append(f"{t} outside the board")
        for hx, hy in HOLES:
            dx = max(x0 - hx, 0.0, hx - x1)
            dy = max(y0 - hy, 0.0, hy - y1)
            if math.hypot(dx, dy) < 2.75:
                probs.append(f"{t} covers the corner screw at ({hx:g}, {hy:g})")
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            a, b = rects[i], rects[j]
            if a[1] < b[2] and b[1] < a[2] and a[3] < b[4] and b[3] < a[4]:
                probs.append(f"{a[0]} overlaps {b[0]}")
    mb = motherboard(cps=cps)
    skip = ("motherboard PCB", "standoff", "screw", "pads", "leads", "ends", "pin 1", "pins", "contacts", "mouth",
            "tongue", "copper", "slot", "cap", "base", "button")
    fps = [f for f in _footprints(mb) if not any(s in f[0] for s in skip)]
    for name, x0, x1, y0, y1, z1 in fps:
        under = [t for t, cx0, cx1, cy0, cy1 in rects if x0 < cx1 and cx0 < x1 and y0 < cy1 and cy0 < y1]
        if under and z1 > 6.0 + 1e-6 and "socket" not in name and "J_KVM" not in name:
            probs.append(f"{name} is {z1:.1f} mm tall under {under[0]}")
    for i in range(len(fps)):
        for j in range(i + 1, len(fps)):
            a, b = fps[i], fps[j]
            if a[1] < b[2] - 0.05 and b[1] < a[2] - 0.05 and a[3] < b[4] - 0.05 and b[3] < a[4] - 0.05:
                probs.append(f"{a[0]} overlaps {b[0]}")
    if verbose:
        print("check:", "ok" if not probs else "")
        for p in probs:
            print("  " + p)
    return probs


def _main():
    import time
    t0 = time.time()
    items, ghost = assembly()
    lo, hi = _bbox(items)
    print(f"assembly: {len(items)} items, ghost {len(ghost)}, bbox {np.round(lo, 1)} .. {np.round(hi, 1)}")
    for c in coupons():
        print(f"  {c.slot:5s} {c.title:22s} at ({c.x0:5.1f}, {c.y0:5.1f}) {c.w:4.0f} x {c.d:4.0f} mm, "
              f"{len(c.parts)} parts, {len(c.keys)} key items{'  (ghost: optional)' if c.ghost else ''}")
    names = [it[0] for it in motherboard()]
    print(f"  INA226-class monitors: {sum(1 for n in names if n.endswith('INA226'))}, rail switches: "
          f"{sum(1 for n in names if re.fullmatch(r'(S\d (3V3|5V)|KVM 5V) (switch|breaker)', n))} (with the KVM's), "
          f"input breaker: "
          f"{sum(1 for n in names if n == 'input breaker U2')}, LDOs: {sum(1 for n in names if n.endswith('LDO'))}, "
          f"bus switches: {sum(1 for n in names if n.endswith('bus switch'))}")
    rig = latency_rig() + rig_cables()
    lo, hi = _bbox(rig)
    print(f"latency rig + cables: {len(rig)} items, bbox {np.round(lo, 1)} .. {np.round(hi, 1)}")
    check()
    print(f"built in {time.time() - t0:.1f} s")


if __name__ == "__main__":
    _main()
