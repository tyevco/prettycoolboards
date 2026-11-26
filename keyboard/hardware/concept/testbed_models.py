#!/usr/bin/env python3
"""Illustrative model of the rev A sensing testbed: a motherboard, plug-in coupons and a latency rig (build123d).

What it builds (mm, Z up, the motherboard's top copper at z = 0, +Y away from the viewer's front edge, X right):

    motherboard   about 160 x 110 mm on four standoffs: the rev A MCU (STM32U5A5, the owner's pick of 2026-11-26,
                  drawn as its LQFP100 14 x 14 mm body with gull-wing leads at 0.5 mm), a 16 MHz HSE crystal beside it,
                  a USB-C port next to the MCU with a short high-speed pair drawn between them, reset and boot buttons,
                  a power and charging section, one mezzanine socket per coupon, injection and current-sense test pads,
                  and the latency rig's header (marker GPIO)
    coupons       each a small board on a 2 x 10 mezzanine header, 11 mm above the motherboard:
                    Hall-effect   4 keys over TMAG5253-class sensors, two switch-free reference sensors, thermistors
                    TMR           the same 4 keys over a TMR sensor (part not chosen)
                    shear         2 sites over TMAG5170s: a stock stem and a centring-stem prototype
                    coil DOE      20 generated spirals (coils.py) read by LDC1614-class converters, 2 stock switches
                    haptics       DRV8316 + MT6701CT + gimbal motor and roller; DRV2605L + coin LRA; a capacitive strip
                    KVM           optional (only if the connector can carry it): drawn as a ghost
    latency rig   a separate small board: host MCU and stimulus driver (parts not chosen), a USB-A host port cabled to
                  the motherboard's USB-C, a ribbon to the rig header, and a probe lead to an injection test pad

    PY=/path/to/venv/bin/python          # build123d 0.13, numpy
    $PY keyboard/hardware/concept/testbed_models.py      # build everything, print part counts and bounding boxes

The renders are drawn by render_testbed.py.

Status: CONCEPT SKETCH. Nothing in keyboard/ is designed, built or measured (keyboard/docs/concept.md section 7).
Every position and size below is an illustrative placeholder chosen to give a believable picture, not a decision: the
board size, the coupon footprints, the connector type (concept.md says only "coupon connectors with analog and SPI
lanes"), the mezzanine height, the parts' packages and the rig's parts. The parts named are the candidates in
concept.md, except the MCU: the STM32U5A5 (STM32U5A5VJT6, LQFP100) is the owner's rev A choice of 2026-11-26, and the
motherboard around it is not designed, built or measured. Its placement, the crystal's and the USB-C's, and the HS
pair's route are illustrative: which package side carries the USB pins (PA11/PA12) and the oscillator pins is not
checked, and 16 MHz is the HSE value on the NUCLEO-U5A5ZJ-Q, not a checked entry in the list of values the U5's HS PHY
accepts. Solder-mask colours only tell the coupons apart.
"""
import math
from dataclasses import dataclass, field

import numpy as np
from build123d import Box, Compound, Cone, Cylinder, Plane, Pos, RectangleRounded, Rot, loft

import coils as CO

# ---------------------------------------------------------------------------------------------------------------
# Illustrative constants (mm). Not decisions.
# ---------------------------------------------------------------------------------------------------------------
MB_W, MB_D = 160.0, 110.0      # motherboard
PCB_T = 1.6
STANDOFF = 10.0                # motherboard standoff height under the board
MEZZ = 11.0                    # coupon PCB bottom above the motherboard top (2 x 10 socket 8.5 + header spacer 2.5)
PITCH = 19.05

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
RIBBON = (0.70, 0.71, 0.74)
PROBE = (0.80, 0.14, 0.16)


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
        items.append((name + " pin 1", zcyl(x - w / 2 + 0.7, y + d / 2 - 0.7, 0.5, z0 + h, z0 + h + 0.02),
                      (0.6, 0.6, 0.6)))
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


def lqfp(name, x, y, z0, body=14.0, span=16.0, n_side=25, pitch=0.5, h=1.4, standoff=0.1):
    """LQFP-class package: a body with n_side gull-wing leads per side and a pin-1 dot. The defaults are an LQFP100
    14 x 14 mm at 0.5 mm pitch, 16 mm tip to tip, 1.4 mm body (the JEDEC MS-026 class outline, not a datasheet
    drawing)."""
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
    items.append((name + " pin 1", zcyl(x - body / 2 + 1.4, y + body / 2 - 1.4, 1.0, z0 + standoff + h,
                                        z0 + standoff + h + 0.02), (0.6, 0.6, 0.6)))
    return items


def sop(name, x, y, z0, body=(4.9, 3.9), n=4, pitch=1.27, h=1.5, rot=0, lead=1.05):
    """SOIC / SOP / MSOP / VSSOP-class gull-wing package. body = (along the pin rows, across)."""
    bl, bw = body
    leads = []
    for i in range(n):
        o = (i - (n - 1) / 2) * pitch
        for s in (-1, 1):
            y0, y1 = s * bw / 2, s * (bw / 2 + lead)
            if rot in (0, 180):
                leads.append(box(x + o - 0.2, x + o + 0.2, y + min(y0, y1), y + max(y0, y1), z0, z0 + 0.15))
            else:
                leads.append(box(x + min(y0, y1), x + max(y0, y1), y + o - 0.2, y + o + 0.2, z0, z0 + 0.15))
    w, d = _r(bl, bw, rot)
    return [(name, cbox(w, d, z0 + 0.1, z0 + h, x, y), "ic"), (name + " leads", comp(leads), "steel")]


def sot23(name, x, y, z0, rot=0):
    return sop(name, x, y, z0, body=(2.9, 1.6), n=3, pitch=0.95, h=1.1, rot=rot, lead=0.5)


def passive(name, x, y, z0, size=(1.6, 0.8), h=0.6, rot=0, colour=CAP):
    w, d = _r(size[0], size[1], rot)
    e = 0.3
    if rot in (0, 180):
        ends = comp([box(x - w / 2, x - w / 2 + e, y - d / 2, y + d / 2, z0, z0 + h + 0.02),
                     box(x + w / 2 - e, x + w / 2, y - d / 2, y + d / 2, z0, z0 + h + 0.02)])
    else:
        ends = comp([box(x - w / 2, x + w / 2, y - d / 2, y - d / 2 + e, z0, z0 + h + 0.02),
                     box(x - w / 2, x + w / 2, y + d / 2 - e, y + d / 2, z0, z0 + h + 0.02)])
    return [(name, cbox(w, d, z0, z0 + h, x, y), colour), (name + " ends", ends, "steel")]


def usb_c(name, x, y, z0, facing="-x"):
    """USB-C receptacle (mid-mount-ish envelope): shell 7.35 deep x 8.94 wide x 3.26 tall, the mouth at `facing`."""
    if facing == "-x":
        shell = box(x - 3.675, x + 3.675, y - 4.47, y + 4.47, z0, z0 + 3.26)
        mouth = box(x - 3.70, x - 3.66, y - 4.17, y + 4.17, z0 + 0.35, z0 + 2.91)
        tongue = box(x - 3.72, x - 3.70, y - 3.3, y + 3.3, z0 + 1.45, z0 + 1.85)
    else:  # "+x"
        shell = box(x - 3.675, x + 3.675, y - 4.47, y + 4.47, z0, z0 + 3.26)
        mouth = box(x + 3.66, x + 3.70, y - 4.17, y + 4.17, z0 + 0.35, z0 + 2.91)
        tongue = box(x + 3.70, x + 3.72, y - 3.3, y + 3.3, z0 + 1.45, z0 + 1.85)
    return [(name, shell, "usb"), (name + " mouth", mouth, DARK), (name + " tongue", tongue, "sensor")]


def usb_a(name, x, y, z0):
    """USB-A receptacle (host port), mouth facing +x: 14 deep x 13.1 wide x 5.7 tall."""
    shell = box(x - 7.0, x + 7.0, y - 6.55, y + 6.55, z0, z0 + 5.7)
    mouth = box(x + 6.96, x + 7.02, y - 6.0, y + 6.0, z0 + 0.5, z0 + 5.2)
    tongue = box(x + 7.02, x + 7.05, y - 5.6, y + 5.6, z0 + 2.9, z0 + 4.4)
    return [(name, shell, "usb"), (name + " mouth", mouth, DARK), (name + " tongue", tongue, WHITE_PLASTIC)]


def idc_header(name, x, y, z0, n=10, long_axis="y"):
    """Shrouded 2 x n box header (2.54 mm): 9.0 x (2.54 n + 7.6) x 9.1, hollow, with its pins."""
    L = 2.54 * n / 2 + 7.6
    if long_axis == "y":
        outer = box(x - 4.5, x + 4.5, y - L / 2, y + L / 2, z0, z0 + 9.1)
        inner = box(x - 3.2, x + 3.2, y - L / 2 + 1.2, y + L / 2 - 1.2, z0 + 1.5, z0 + 9.2)
        key = box(x - 4.6, x - 3.1, y - 2.2, y + 2.2, z0 + 1.5, z0 + 9.2)
    else:
        outer = box(x - L / 2, x + L / 2, y - 4.5, y + 4.5, z0, z0 + 9.1)
        inner = box(x - L / 2 + 1.2, x + L / 2 - 1.2, y - 3.2, y + 3.2, z0 + 1.5, z0 + 9.2)
        key = box(x - 2.2, x + 2.2, y - 4.6, y - 3.1, z0 + 1.5, z0 + 9.2)
    shroud = outer - inner - key
    pins = []
    for i in range(n // 2):
        o = (i - (n // 2 - 1) / 2) * 2.54
        for s in (-1.27, 1.27):
            px, py = (x + s, y + o) if long_axis == "y" else (x + o, y + s)
            pins.append(cbox(0.64, 0.64, z0 + 1.5, z0 + 7.5, px, py))
    return [(name, shroud, "sensor"), (name + " pins", comp(pins), GOLD)]


def idc_plug(name, x, y, z0, n=10, long_axis="y"):
    L = 2.54 * n / 2 + 4.5
    w, d = (6.0, L) if long_axis == "y" else (L, 6.0)
    return [(name, cbox(w, d, z0 + 1.6, z0 + 13.0, x, y), (0.16, 0.16, 0.18))]


def socket_2xn(name, x, y, z0, n=10, long_axis="y", h=8.5):
    """Female 2 x n socket (2.54 mm) for a coupon's mezzanine header, with its contact holes as dark squares."""
    L = 2.54 * n
    w, d = (5.08, L) if long_axis == "y" else (L, 5.08)
    body = cbox(w, d, z0, z0 + h, x, y)
    holes = []
    for i in range(n):
        o = (i - (n - 1) / 2) * 2.54
        for s in (-1.27, 1.27):
            px, py = (x + s, y + o) if long_axis == "y" else (x + o, y + s)
            holes.append(cbox(0.9, 0.9, z0 + h, z0 + h + 0.03, px, py))
    return [(name, body, "sensor"), (name + " contacts", comp(holes), DARK)]


def header_2xn(name, x, y, z_top, n=10, long_axis="y", spacer=2.5, pin=6.0):
    """Male 2 x n header under a coupon: spacer just under the board (z_top = the coupon's underside), pins below."""
    L = 2.54 * n
    w, d = (5.08, L) if long_axis == "y" else (L, 5.08)
    body = cbox(w, d, z_top - spacer, z_top, x, y)
    pins = []
    for i in range(n):
        o = (i - (n - 1) / 2) * 2.54
        for s in (-1.27, 1.27):
            px, py = (x + s, y + o) if long_axis == "y" else (x + o, y + s)
            pins.append(cbox(0.64, 0.64, z_top - spacer - pin, z_top - spacer, px, py))
    return [(name + " spacer", body, "sensor"), (name + " pins", comp(pins), GOLD)]


def jst2(name, x, y, z0, facing="-x"):
    """2-pin 2.0 mm wire-to-board header envelope (JST-PH class): 6.0 x 4.5 x 6.0, the mouth at `facing`."""
    if facing == "-x":
        body = box(x - 2.25, x + 2.25, y - 3.0, y + 3.0, z0, z0 + 6.0)
        mouth = box(x - 2.29, x - 2.24, y - 2.4, y + 2.4, z0 + 1.2, z0 + 5.4)
    else:  # "-y"
        body = box(x - 3.0, x + 3.0, y - 2.25, y + 2.25, z0, z0 + 6.0)
        mouth = box(x - 2.4, x + 2.4, y - 2.29, y - 2.24, z0 + 1.2, z0 + 5.4)
    return [(name, body, WHITE_PLASTIC), (name + " mouth", mouth, DARK)]


def inductor(name, x, y, z0, s=4.0, h=2.0):
    return [(name, cbox(s, s, z0, z0 + h, x, y), (0.30, 0.31, 0.34)),
            (name + " core", zcyl(x, y, s * 0.55, z0 + h, z0 + h + 0.02), (0.20, 0.20, 0.22))]


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


def screw_head(name, x, y, z0, d=4.5):
    return [(name, zcyl(x, y, d, z0, z0 + 1.6), "steel"),
            (name + " slot", cbox(d * 0.8, 0.5, z0 + 1.6, z0 + 1.62, x, y), DARK)]


def nylon_post(name, x, y, z0, z1, d=4.0):
    return [(name, zcyl(x, y, d, z0, z1), WHITE_PLASTIC)]


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
# Coupons. Local frame: the coupon's front-left corner at the origin, its PCB from z = 0 to PCB_T.
# ---------------------------------------------------------------------------------------------------------------
@dataclass
class Coupon:
    key: str
    title: str
    x0: float
    y0: float
    w: float
    d: float
    parts: list = field(default_factory=list)       # on the coupon (move with it)
    keys: list = field(default_factory=list)        # switches and keycaps (lifted further in the exploded view)
    header: tuple = (0.0, 0.0, "y")                 # mezzanine header centre (local) and long axis
    post: tuple = (0.0, 0.0)                        # support post (local)
    ghost: bool = False
    pcb_cut: object = None

    def pcb(self):
        if self.pcb_cut is None:
            return slab(0, self.w, 0, self.d, 0, PCB_T)
        b = box(0, self.w, 0, self.d, 0, PCB_T)
        if self.pcb_cut is not None:
            b = b - self.pcb_cut
        return b

    def items(self, lift=0.0, key_lift=0.0, with_keys=True, with_header=True):
        """World-frame items: the coupon at its slot, `lift` above its seated height, keys `key_lift` higher."""
        x0, y0, z0 = self.x0, self.y0, MEZZ + lift
        hx, hy, ax = self.header
        own = [(f"{self.title} PCB", self.pcb(), MASK[self.key])] + self.parts
        if with_header:
            own += header_2xn(f"{self.title} header", hx, hy, 0.0, long_axis=ax)
            own += nylon_post(f"{self.title} post", self.post[0], self.post[1], -MEZZ, 0.0)
        out = moved(own, x0, y0, z0)
        if with_keys:
            out += moved(self.keys, x0, y0, z0 + key_lift)
        return out

    def socket_items(self):
        """What stays on the motherboard: the coupon's socket and its post's footprint pad."""
        hx, hy, ax = self.header
        return socket_2xn(f"{self.title} socket", self.x0 + hx, self.y0 + hy, 0.0, long_axis=ax)

    def centre(self, z_extra=0.0, lift=0.0):
        return np.array([self.x0 + self.w / 2, self.y0 + self.d / 2, MEZZ + PCB_T + lift + z_extra])


T = PCB_T       # coupon top in its local frame


def _key_coupon(key, title, x0, y0, sensor_kind):
    """Hall-effect or TMR coupon: 2 x 2 keys, two switch-free reference sensors and two thermistors in front."""
    c = Coupon(key, title, x0, y0, 44.0, 50.0, header=(4.0, 29.5, "y"), post=(40.0, 6.0))
    cols, rows = (12.5, 12.5 + PITCH), (20.5, 20.5 + PITCH)
    k = 0
    for yy in rows:
        for xx in cols:
            k += 1
            if sensor_kind == "hall":
                c.parts += sot23(f"{title} TMAG5253 {k}", xx, yy, T)
            else:
                c.parts += qfn(f"{title} TMR sensor {k}", xx, yy, 2.5, T, h=0.75, dot=False)
            c.parts += passive(f"{title} C{k}", xx + 3.2, yy - 2.6, T, size=(1.0, 0.5), h=0.5)
            c.keys += mx_switch(f"{title} K{k}", xx, yy, T)
            c.keys += keycap(f"{title} K{k}", xx, yy, T)
    # the reference strip: no switch over these
    for i, xx in enumerate((7.0, 37.0)):
        if sensor_kind == "hall":
            c.parts += sot23(f"{title} reference sensor {i + 1}", xx, 5.5, T)
        else:
            c.parts += qfn(f"{title} reference sensor {i + 1}", xx, 5.5, 2.5, T, h=0.75, dot=False)
    for i, xx in enumerate((14.5, 29.5)):
        c.parts += passive(f"{title} thermistor {i + 1}", xx, 5.5, T, size=(1.6, 0.8), colour=RES)
    c.parts += qfn(f"{title} bus buffer", 22.0, 5.5, 3.0, T, h=0.8)
    return c


def hall_coupon(x0, y0):
    return _key_coupon("hall", "Hall-effect coupon", x0, y0, "hall")


def tmr_coupon(x0, y0):
    return _key_coupon("tmr", "TMR coupon", x0, y0, "tmr")


def shear_coupon(x0, y0):
    """Two TMAG5170 sites: a stock stem (front) and the centring-stem prototype (back), blue keycaps."""
    c = Coupon("shear", "Shear coupon", x0, y0, 28.0, 50.0, header=(4.0, 25.0, "y"), post=(24.0, 46.0))
    sites = ((14.0, 15.0, "stock"), (14.0, 36.5, "proto"))
    for i, (xx, yy, kind) in enumerate(sites):
        c.parts += sop(f"Shear coupon TMAG5170 {i + 1}", xx, yy, T, body=(3.0, 3.0), n=4, pitch=0.65, h=1.0,
                       lead=0.95)
        c.parts += passive(f"Shear coupon C{i + 1}", xx + 4.2, yy - 4.0, T, size=(1.0, 0.5), h=0.5)
        if kind == "stock":
            c.keys += mx_switch(f"Shear S{i + 1}", xx, yy, T)
        else:
            c.keys += centring_stem_switch(f"Shear S{i + 1}", xx, yy, T)
        c.keys += keycap(f"Shear S{i + 1}", xx, yy, T, colour="keycap_accent")
    return c


COIL_PITCH = (12.5, 12.0)
COIL_ORIGIN = (7.0, 7.0)
COIL_SWITCH_TAGS = ("B2", "B4")        # stock switches shown on two coils (illustrative)
COIL_LEAD_ANGLE = 0.0                  # the outer ends (and the leads) point to +x
COIL_LEAD = 1.3                        # lead stub beyond the outer turn


def coil_coupon(x0, y0, pts_per_turn=64):
    """20 generated spirals (coils.doe_layout) under black mask, five LDC1614-class converters, two stock switches.
    Only each coil's top copper layer is drawn in 3D; render_testbed.py draws every layer in its 2D view."""
    c = Coupon("coil", "Coil coupon", x0, y0, 72.0, 50.0, header=(66.0, 30.0, "y"), post=(4.0, 46.0))
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
    for i, yy in enumerate((6.0, 15.0, 24.0, 33.0, 42.0)):
        c.parts += qfn(f"LDC1614-class converter {i + 1}", 66.0, yy, 4.0, T, h=0.8)
        c.parts += passive(f"Coil coupon C{i + 1}", 66.0, yy + 3.4, T, size=(1.0, 0.5), h=0.5)
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


def haptics_coupon(x0, y0):
    c = Coupon("haptics", "Haptics coupon", x0, y0, 46.0, 50.0, header=(4.0, 30.0, "y"), post=(42.0, 47.0))
    c.parts += wheel_module(20.0, 32.0, T)
    c.parts += qfn("DRV8316", 30.0, 12.5, 7.0, T, d=5.0)        # VQFN-class 7 x 5
    c.parts += passive("DRV8316 C1", 34.5, 15.0, T, size=(1.6, 0.8), rot=90)
    c.parts += passive("DRV8316 C2", 36.6, 15.0, T, size=(1.6, 0.8), rot=90)
    # coin LRA and its driver
    c.parts.append(("coin LRA", zcyl(8.5, 34.0, 10.0, T, T + 2.7), "lra"))
    c.parts.append(("LRA flex tail", box(8.0, 9.0, 27.0, 29.5, T, T + 0.1), "flex"))
    c.parts += sop("DRV2605L", 8.5, 23.5, T, body=(3.0, 3.0), n=5, pitch=0.5, h=1.0, lead=0.8)
    # capacitive strip: six pads along the front edge, and a touch controller
    for i in range(6):
        xx = 4.5 + i * 6.6
        c.parts.append((f"touch pad {i + 1}", box(xx - 2.9, xx + 2.9, 2.0, 8.0, T, T + 0.03), GOLD))
    c.parts += qfn("touch controller", 16.0, 14.0, 3.0, T, h=0.8)
    return c


def kvm_coupon(x0, y0):
    """Optional: host-B controller (CH32X035 / CH32V305 class) and a digital isolator over an isolation slot."""
    c = Coupon("kvm", "KVM coupon", x0, y0, 30.0, 30.0, header=(24.0, 15.0, "y"), post=(4.0, 4.0), ghost=True)
    c.parts += usb_c("USB-C B", 3.0, 18.0, T, facing="-x")
    c.parts += qfn("host-B controller", 11.0, 9.0, 4.0, T)
    c.parts += sop("isolator", 18.0, 18.0, T, body=(4.9, 3.9), n=4, pitch=1.27, rot=90)
    c.pcb_cut = box(17.6, 18.4, 6.0, 30.5, -1.0, 3.0)
    for i, (xx, yy) in enumerate(((11.0, 14.0), (9.0, 22.0), (24.0, 6.0), (8.0, 4.0))):
        c.parts += passive(f"KVM C{i + 1}", xx, yy, T)
    return c


# ---------------------------------------------------------------------------------------------------------------
# Slots on the motherboard (illustrative)
# ---------------------------------------------------------------------------------------------------------------
def coupons():
    return [
        hall_coupon(38.0, 57.0),
        tmr_coupon(84.0, 57.0),
        shear_coupon(130.0, 57.0),
        coil_coupon(38.0, 3.0),
        haptics_coupon(112.0, 3.0),
        kvm_coupon(4.0, 4.0),
    ]


# injection and current-sense test pads: one INJ pad per coupon lane, a pair of I-sense pads per coupon
INJ_PADS = [(8.0 + 4.0 * i, 47.0) for i in range(6)]
ISENSE_PADS = [(7.0 + 4.0 * i + 1.6 * j, 41.0) for i in range(6) for j in (0, 1)]
RIG_HEADER = (31.5, 96.0)
USB_C_PORT = (2.675, 96.5)       # the motherboard's USB-C (x is the receptacle's centre), beside the MCU
MCU_XY = (15.5, 80.0)            # the STM32U5A5's centre: an LQFP100, 16 mm tip to tip
MCU_NAME = "STM32U5A5 (rev A MCU)"
HSE_XY = (3.4, 78.5)             # the 16 MHz HSE crystal, beside the MCU
# the USB high-speed pair from the USB-C to the MCU, kept short (centreline; which MCU pins it lands on is not checked)
HS_PAIR = [(USB_C_PORT[0] + 3.7, USB_C_PORT[1]), (10.6, USB_C_PORT[1]), (13.0, USB_C_PORT[1] - 2.4),
           (13.0, MCU_XY[1] + 8.1)]


def motherboard(with_sockets=True, cps=None):
    z = 0.0
    # holes are drawn as dark discs, not cut: a face with holes tessellates into long slivers that slow the renders
    items = [("motherboard PCB", slab(0, MB_W, 0, MB_D, -PCB_T, 0), MASK["mother"])]
    for i, x in enumerate((4.0, MB_W - 4.0)):
        for j, y in enumerate((4.0, MB_D - 4.0)):
            items += standoff_under(f"standoff {i}{j}", x, y, -PCB_T)
            items += screw_head(f"screw {i}{j}", x, y, z)
    # the rev A MCU (STM32U5A5, LQFP100) with its decoupling, the 16 MHz HSE crystal and its load capacitors, the
    # USB-C beside it with ESD and a short HS pair (copper under the mask), and the reset and boot buttons
    items += lqfp(MCU_NAME, MCU_XY[0], MCU_XY[1], z)
    for k, (dx, dy) in enumerate(((2.0, 9.4), (6.0, 9.4), (9.4, 4.0), (9.4, -3.0), (-3.0, -9.4), (4.0, -9.4),
                                  (-9.4, 6.0))):
        rot = 90 if abs(dx) > abs(dy) else 0
        items += passive(f"MCU C{k}", MCU_XY[0] + dx, MCU_XY[1] + dy, z, size=(1.0, 0.5), h=0.5, rot=rot)
    items += crystal("HSE crystal (16 MHz)", HSE_XY[0], HSE_XY[1], z)
    for k, dy in enumerate((-2.6, 2.6)):
        items += passive(f"HSE load C{k}", HSE_XY[0], HSE_XY[1] + dy, z, size=(1.0, 0.5), h=0.5)
    items += usb_c("USB-C", USB_C_PORT[0], USB_C_PORT[1], z, facing="-x")
    items += sot23("ESD array", 9.6, USB_C_PORT[1] + 3.7, z)
    centre = np.asarray(HS_PAIR)
    o = CO.band(centre, 0.75)
    n = len(centre)
    items.append(("USB HS pair copper", MeshSolid.merge([flat_band(o[:n], 0.4, z + 0.01),
                                                          flat_band(o[n:][::-1], 0.4, z + 0.01)]), (0.30, 0.68, 0.36)))
    items += tact("reset button", RIG_HEADER[0], 79.5, z)
    items += tact("boot button", RIG_HEADER[0], 73.0, z)
    # power and charging (from the caliper's power sheets; parts here are generic envelopes)
    items += jst2("battery connector", 2.25, 58.0, z, facing="-x")
    items += qfn("charger", 10.0, 62.0, 3.0, z, h=0.8)
    items += inductor("inductor", 17.0, 62.0, z)
    items += sot23("LDO", 24.5, 62.0, z)
    for k, (x, y) in enumerate(((10.0, 57.0), (14.0, 57.0), (21.0, 57.0), (27.5, 57.0), (29.0, 62.0),
                                (10.0, 66.5), (17.0, 66.5))):
        items += passive(f"power C{k}", x, y, z, size=(2.0, 1.25), h=0.9)
    # latency-rig hooks: the rig header (marker GPIO, trigger) and the test-pad field
    items += idc_header("rig header", RIG_HEADER[0], RIG_HEADER[1], z, long_axis="y")
    for k, (x, y) in enumerate(INJ_PADS):
        items += pad(f"INJ pad {k + 1}", x, y, z, d=1.8)
    for k, (x, y) in enumerate(ISENSE_PADS):
        items += pad(f"I-sense pad {k + 1}", x, y, z, d=1.3)
    for k in range(6):
        items += passive(f"shunt {k + 1}", 7.8 + 4.0 * k, 37.5, z, size=(2.0, 1.25), h=0.5, colour=RES)
    # coupon sockets
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
# Latency rig (a separate small board, left of the motherboard)
# ---------------------------------------------------------------------------------------------------------------
RIG = dict(x0=-118.0, x1=-62.0, y0=64.0, y1=114.0)
RIG_IDC = (-90.0, 100.0)
RIG_USB_A = (-69.0, USB_C_PORT[1])       # in line with the motherboard's USB-C, mouth facing +x
RIG_PROBE_CONN = (-76.0, 68.0)


def latency_rig():
    """The rig board: host MCU, stimulus driver and DAC (parts not chosen), a USB-A host port, the IDC header for the
    ribbon and a connector for the probe lead."""
    r = RIG
    z = 0.0
    items = [("rig PCB", slab(r["x0"], r["x1"], r["y0"], r["y1"], -PCB_T, 0), MASK["rig"])]
    for i, x in enumerate((r["x0"] + 4, r["x1"] - 4)):
        for j, y in enumerate((r["y0"] + 4, r["y1"] - 4)):
            items += standoff_under(f"rig standoff {i}{j}", x, y, -PCB_T)
            items += screw_head(f"rig screw {i}{j}", x, y, z)
    items += qfn("rig host MCU (not chosen)", -105.0, 92.0, 7.0, z)
    items += crystal("rig crystal", -105.0, 84.5, z)
    items += sop("rig stimulus driver (not chosen)", -90.0, 75.0, z, body=(4.9, 3.9))
    items += sop("rig DAC (not chosen)", -102.0, 75.0, z, body=(3.0, 3.0), n=4, pitch=0.65, h=1.0, lead=0.95)
    for k, (x, y) in enumerate(((-111.0, 92.0), (-99.0, 92.0), (-105.0, 98.0), (-84.0, 75.0), (-96.0, 75.0))):
        items += passive(f"rig C{k}", x, y, z, size=(1.6, 0.8), rot=90 if k < 2 else 0)
    items += usb_a("rig USB-A (host port)", RIG_USB_A[0], RIG_USB_A[1], z)
    items += idc_header("rig IDC header", RIG_IDC[0], RIG_IDC[1], z, long_axis="y")
    items += jst2("rig probe connector", RIG_PROBE_CONN[0], RIG_PROBE_CONN[1], z, facing="-y")
    items += tact("rig start button", -112.0, 108.0, z)
    return items


def rig_paths():
    """Centrelines (N, 3) of the USB cable, the ribbon and the probe lead (also used to place the callouts)."""
    ux, uy, zc = USB_C_PORT[0] - 3.675, USB_C_PORT[1], 1.63
    ax_, ay_, za = RIG_USB_A[0] + 7.0, RIG_USB_A[1], 2.85
    p0, p1 = np.array([ax_ + 19.0, ay_, za]), np.array([ux - 17.0, uy, zc])
    usb = bezier([p0, p0 + (14, -2, 0), (-33.0, 66.0, 2.0), p1 + (-14, -2, 0), p1], 64)
    a = np.array([RIG_IDC[0], RIG_IDC[1], 13.0])
    b = np.array([RIG_HEADER[0], RIG_HEADER[1], 13.0])
    rib = bezier([a, a + (0, 0, 34), b + (0, 0, 34), b], 80)
    px, py = INJ_PADS[0]
    c0 = np.array([RIG_PROBE_CONN[0], RIG_PROBE_CONN[1] - 2.3, 3.6])
    c1 = np.array([px, py, 18.0])
    lead = bezier([c0, c0 + (0, -24, 0), (-30.0, 30.0, 10.0), c1 + (-16, -6, 20), c1 + (0, 0, 8), c1], 80)
    return dict(usb=usb, ribbon=rib, lead=lead)


def rig_cables():
    """USB cable (USB-A plug at the rig, USB-C plug at the motherboard), the ribbon, the probe lead and the probe."""
    items = []
    paths = rig_paths()
    plug = (0.18, 0.18, 0.20)
    # USB-C plug into the motherboard's receptacle (its mouth at x = -1.0)
    ux, uy = USB_C_PORT[0] - 3.675, USB_C_PORT[1]
    zc = 1.63
    items.append(("USB-C plug", box(ux - 13.0, ux - 0.5, uy - 6.0, uy + 6.0, zc - 3.0, zc + 3.0), plug))
    items.append(("USB-C plug strain relief", xcyl(uy, zc, 4.2, ux - 17.0, ux - 13.0), plug))
    # USB-A plug into the rig's host port (its mouth at x = RIG x1)
    ax_, ay_ = RIG_USB_A[0] + 7.0, RIG_USB_A[1]
    za = 2.85
    items.append(("USB-A plug", box(ax_ + 0.5, ax_ + 15.0, ay_ - 8.0, ay_ + 8.0, za - 4.0, za + 4.0), plug))
    items.append(("USB-A plug strain relief", xcyl(ay_, za, 4.2, ax_ + 15.0, ax_ + 19.0), plug))
    items.append(("USB cable", tube(paths["usb"], 1.9), (0.22, 0.22, 0.24)))
    # ribbon: IDC plugs on both headers, the cable arching over between them
    items += idc_plug("rig IDC plug", RIG_IDC[0], RIG_IDC[1], 0.0)
    items += idc_plug("motherboard IDC plug", RIG_HEADER[0], RIG_HEADER[1], 0.0)
    rp = paths["ribbon"]
    items.append(("ribbon", ribbon(rp, (0, 1, 0), 12.7, 0.9), RIBBON))
    stripe = rp + (0, -6.0, 0.0)
    items.append(("ribbon pin-1 stripe", ribbon(stripe, (0, 1, 0), 0.9, 0.95), PROBE))
    # probe lead to INJ pad 1: a pen-style probe standing on the pad (how the rig reaches the pad is not decided)
    px, py = INJ_PADS[0]
    items.append(("probe tip", Pos(px, py, 1.25) * Cone(0.05, 0.9, 2.5), "steel"))
    items.append(("probe body", zcyl(px, py, 4.0, 2.5, 18.0), PROBE))
    items.append(("probe collar", zcyl(px, py, 5.0, 4.0, 6.0), plug))
    items.append(("probe lead", tube(paths["lead"], 0.9), PROBE))
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


def _main():
    import time
    t0 = time.time()
    items, ghost = assembly()
    lo, hi = _bbox(items)
    print(f"assembly: {len(items)} items, ghost {len(ghost)}, bbox {np.round(lo, 1)} .. {np.round(hi, 1)}")
    for c in coupons():
        print(f"  {c.title:22s} at ({c.x0:5.1f}, {c.y0:5.1f}) {c.w:4.0f} x {c.d:4.0f} mm, "
              f"{len(c.parts)} parts, {len(c.keys)} key items{'  (ghost: optional)' if c.ghost else ''}")
    rig = latency_rig() + rig_cables()
    lo, hi = _bbox(rig)
    print(f"latency rig + cables: {len(rig)} items, bbox {np.round(lo, 1)} .. {np.round(hi, 1)}")
    print(f"built in {time.time() - t0:.1f} s")


if __name__ == "__main__":
    _main()
