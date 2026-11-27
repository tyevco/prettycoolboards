#!/usr/bin/env python3
"""Concept renders of the rev A sensing testbed (keyboard/docs/concept.md section 7, keyboard/hardware/design/SPEC.md),
from testbed_models and coils.

Writes (all in keyboard/hardware/concept/):
    renders/testbed_assembly.png      motherboard with every coupon plugged in, 3/4 view (the KVM coupon as a ghost)
    renders/testbed_exploded.png      the coupons lifted off their 2 x 20 sockets, the keys lifted off the key coupons
    renders/testbed_top.png           top view to scale, a short label per coupon, and the strip between the slot
                                      rows (MCU, USB-C, Type-C detect, J_RIG, J_SWD, test pads) at twice the scale
    renders/testbed_latency_rig.png   rig + motherboard + the Hall-effect coupon: USB link and the ribbon to J_RIG
    renders/testbed_coil_coupon.png   2D PCB-style view of the coil DOE coupon: 20 spirals from coils.py, every layer
    models/testbed_assembly.glb       the assembly (the optional KVM coupon left out)

Run from the repo root (a few minutes):

    PY=/path/to/venv/bin/python          # build123d 0.13, matplotlib, numpy, PIL
    $PY keyboard/hardware/concept/render_testbed.py [--only assembly,exploded,top,rig,coil,glb]

How it draws: render_lib's tessellation, palette and Lambert shading, rasterised here with a small numpy z-buffer
(supersampled, with outline edges from depth, normal and part changes) instead of a painter's sort, because the copper,
pads and contacts lie flat on the boards and a depth sort of whole triangles puts them behind the board. The labels
are matplotlib callouts placed in millimetres on the projected view. render_lib.autocrop adds the title and the
concept stamp to every image.

Status: CONCEPT SKETCH. Nothing in keyboard/ is built or measured, and the testbed SPEC is a draft on paper. The board
and coupon sizes are the SPEC's "about" figures and the slot rows follow its section 9; every position inside them
is this sketch's placeholder (testbed_models.py). The parts are the SPEC's candidates (the MCU is the owner's rev A
choice of 2026-11-26, the STM32U5A5, drawn as its LQFP100; the 2 x 20 slot connector, no charger on rev A and the
Type-C detect chip are the owner's decisions of the same day), and the coil parameters are an illustrative spread.
Every image carries the render_lib concept stamp.
"""
import argparse
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import matplotlib                                                  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt                                    # noqa: E402
import numpy as np                                                 # noqa: E402
from matplotlib.patches import Circle, FancyBboxPatch, PathPatch, Rectangle   # noqa: E402
from matplotlib.path import Path                                   # noqa: E402

import coils as CO                                                 # noqa: E402
import render_lib as RL                                            # noqa: E402
import testbed_models as M                                         # noqa: E402

OUT = os.path.join(HERE, "renders")
MODELS = os.path.join(HERE, "models")
MAX_PNG = 440_000
INK = (0.12, 0.12, 0.12)
GREY = (0.38, 0.38, 0.40)
HL = tuple(RL.COLOURS["highlight"])
FS = 14.0          # callout font (pt at 100 dpi = 19.4 px): its cap height about 7 px at the ~688 px docs column for a
FS_NOTE = 13.0     # 1350-1450 px image (Inter's caps are 0.73 em)

DECAL_WORDS = ("pads", "contacts", "pin 1", "mouth", "tongue", "copper", "vias", "core", "slot", "INJ pad",
               "I-sense pad", "touch pad", "stripe", "holes", "gull-wing")


# ---------------------------------------------------------------------------------------------------------------
# Camera and z-buffer rasteriser
# ---------------------------------------------------------------------------------------------------------------
class Camera:
    """Orthographic camera with matplotlib's elev / azim convention: eye points from the scene to the viewer."""

    def __init__(self, elev, azim):
        e, a = math.radians(elev), math.radians(azim)
        self.eye = np.array([math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)])
        self.right = np.array([-math.sin(a), math.cos(a), 0.0])
        self.up = np.cross(self.eye, self.right)

    def uv(self, p):
        p = np.atleast_2d(np.asarray(p, float))
        return np.stack([p @ self.right, p @ self.up], -1)


def _tris(items, tol):
    """All triangles of the items, with per-triangle shaded colour, normal, item index and decal flag."""
    tris, cols, nrm, owner, decal = [], [], [], [], []
    for k, it in enumerate(items):
        name, s, c = it[0], it[1], it[2]
        if isinstance(s, M.MeshSolid):
            v, t = s.v, s.t
        else:
            v, t = RL.mesh(s, tol)
        if len(t) == 0:
            continue
        tri = v[t]
        tris.append(tri)
        owner.append(np.full(len(tri), k))
        decal.append(np.full(len(tri), any(w in name for w in DECAL_WORDS)))
        cols.append(np.repeat(RL.colour(c)[None, :], len(tri), 0))
    return np.concatenate(tris), np.concatenate(cols), np.concatenate(owner), np.concatenate(decal)


def _subdivide(tri, cols, owner, decal, max_edge, proj=None):
    """Split triangles until no edge exceeds max_edge, keeping the per-triangle attributes in step. Longest-edge
    bisection (1 -> 2) rather than render_lib's 1 -> 4 split, so a sliver gets shorter without multiplying. With
    proj (a 3 x 2 matrix), edges are measured on the screen: only what the rasteriser's buckets need is split."""
    attrs = [cols, owner, decal]
    for _ in range(60):
        q = tri if proj is None else tri @ proj
        e = np.stack([np.linalg.norm(q[:, i] - q[:, (i + 1) % 3], axis=1) for i in range(3)], 1)
        k = np.argmax(e, 1)
        big = e[np.arange(len(e)), k] > max_edge
        if not big.any():
            break
        t, kk = tri[big], k[big]
        # rotate each triangle so that its longest edge runs from vertex 0 to vertex 1
        idx = (kk[:, None] + np.arange(3)[None, :]) % 3
        t = np.take_along_axis(t, idx[:, :, None], 1)
        a, b, c = t[:, 0], t[:, 1], t[:, 2]
        m = (a + b) / 2
        new = np.concatenate([np.stack((a, m, c), 1), np.stack((m, b, c), 1)])
        tri = np.concatenate([tri[~big], new])
        attrs = [np.concatenate([x[~big], x[big], x[big]]) for x in attrs]
    return (tri,) + tuple(attrs)


class Frame:
    """The pixel grid shared by every pass of one figure: mm extent in (u, v) and the supersampled scale."""

    def __init__(self, cam, lo, hi, px_per_mm, ss=3, margin=3.0):
        self.cam, self.s, self.ss = cam, px_per_mm * ss, ss
        self.u0, self.v1 = lo[0] - margin, hi[1] + margin
        self.W = int(math.ceil((hi[0] - lo[0] + 2 * margin) * px_per_mm)) * ss
        self.H = int(math.ceil((hi[1] - lo[1] + 2 * margin) * px_per_mm)) * ss
        self.u1 = self.u0 + self.W / self.s
        self.v0 = self.v1 - self.H / self.s

    def extent(self):
        return (self.u0, self.u1, self.v0, self.v1)


def rasterise(fr, items, tol=0.12):
    """z-buffer: returns depth (H, W), triangle index (H, W) and the triangle attribute arrays."""
    tri, col, owner, decal = _tris(items, tol)
    proj = np.stack([fr.cam.right, fr.cam.up], 1) * fr.s
    tri, col, owner, decal = _subdivide(tri, col, owner, decal, max_edge=40.0, proj=proj)
    cam = fr.cam
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    shade = 0.35 + 0.65 * np.abs(n @ RL.LIGHT)
    col = np.clip(col * shade[:, None], 0, 1)
    X = (tri @ cam.right - fr.u0) * fr.s          # (N, 3) pixel x
    Y = (fr.v1 - tri @ cam.up) * fr.s             # (N, 3) pixel y, down
    D = tri @ cam.eye                             # (N, 3) depth, larger = nearer
    area = (X[:, 1] - X[:, 0]) * (Y[:, 2] - Y[:, 0]) - (Y[:, 1] - Y[:, 0]) * (X[:, 2] - X[:, 0])
    ok = np.abs(area) > 1e-6
    x0 = np.floor(X.min(1)).astype(np.int64)
    x1 = np.floor(X.max(1)).astype(np.int64)
    y0 = np.floor(Y.min(1)).astype(np.int64)
    y1 = np.floor(Y.max(1)).astype(np.int64)
    size = np.maximum(x1 - x0, y1 - y0) + 1
    zbuf = np.full(fr.H * fr.W, -1e9)
    ibuf = np.full(fr.H * fr.W, -1, dtype=np.int64)
    idx_all = np.arange(len(tri))
    prev = 0
    for B in (2, 3, 4, 6, 8, 11, 16, 23, 32, 45, 64, 128, 256):
        sel = idx_all[ok & (size > prev) & (size <= B)]
        prev = B
        if len(sel) == 0:
            continue
        ox = np.tile(np.arange(B), B)
        oy = np.repeat(np.arange(B), B)
        chunk = max(1, 2_500_000 // (B * B))
        for c0 in range(0, len(sel), chunk):
            ii = sel[c0:c0 + chunk]
            px = x0[ii, None] + ox[None, :]
            py = y0[ii, None] + oy[None, :]
            fx, fy = px + 0.5, py + 0.5
            ax_, ay_, bx, by, cx, cy = (X[ii, 0:1], Y[ii, 0:1], X[ii, 1:2], Y[ii, 1:2], X[ii, 2:3], Y[ii, 2:3])
            inv = 1.0 / area[ii, None]
            wa = ((bx - fx) * (cy - fy) - (by - fy) * (cx - fx)) * inv
            wb = ((cx - fx) * (ay_ - fy) - (cy - fy) * (ax_ - fx)) * inv
            wc = 1.0 - wa - wb
            m = ((wa >= -1e-7) & (wb >= -1e-7) & (wc >= -1e-7) & (px <= x1[ii, None]) & (py <= y1[ii, None])
                 & (px >= 0) & (py >= 0) & (px < fr.W) & (py < fr.H))
            if not m.any():
                continue
            dep = (wa * D[ii, 0:1] + wb * D[ii, 1:2] + wc * D[ii, 2:3])[m]
            pix = (py * fr.W + px)[m]
            tid = np.broadcast_to(ii[:, None], m.shape)[m]
            order = np.lexsort((-dep, pix))
            ps = pix[order]
            first = np.r_[True, ps[1:] != ps[:-1]]
            u, d, t = ps[first], dep[order][first], tid[order][first]
            upd = d > zbuf[u]
            zbuf[u[upd]] = d[upd]
            ibuf[u[upd]] = t[upd]
    return dict(z=zbuf.reshape(fr.H, fr.W), i=ibuf.reshape(fr.H, fr.W), col=col, n=n, owner=owner, decal=decal)


def _edges(r, depth_jump=0.5, crease_deg=38.0):
    """Outline mask: part changes, depth jumps and creases (decals draw none), drawn on the nearer pixel."""
    i, z = r["i"], r["z"]
    bg = i < 0
    ii = np.where(bg, 0, i)
    own = np.where(bg, -1, r["owner"][ii])
    dec = np.where(bg, False, r["decal"][ii])
    nrm = r["n"][ii]
    e = np.zeros_like(bg)
    cc = math.cos(math.radians(crease_deg))
    for dy, dx in ((0, 1), (1, 0), (1, 1), (1, -1)):
        a = (slice(0, i.shape[0] - dy), slice(max(0, -dx), i.shape[1] - max(0, dx)))
        b = (slice(dy, None), slice(max(0, dx), i.shape[1] - max(0, -dx) if dx < 0 else None))
        if dx < 0:
            b = (slice(dy, None), slice(0, i.shape[1] + dx))
            a = (slice(0, i.shape[0] - dy), slice(-dx, None))
        oa, ob = own[a], own[b]
        both = ~bg[a] & ~bg[b]
        diff = (oa != ob) & ~(dec[a] | dec[b])
        jump = both & (np.abs(z[a] - z[b]) > depth_jump) & ~(dec[a] | dec[b])
        crease = both & (oa == ob) & (np.sum(nrm[a] * nrm[b], -1) < cc) & ~dec[a]
        edge = diff | jump | crease
        za = np.where(bg[a], -1e9, z[a])
        zb = np.where(bg[b], -1e9, z[b])
        mark_a = edge & (za >= zb)
        mark_b = edge & (zb > za)
        e[a] |= mark_a
        e[b] |= mark_b
    return e


def shade_image(fr, r, edge_col=0.22, background=(1.0, 1.0, 1.0)):
    i = r["i"]
    bg = i < 0
    img = r["col"][np.where(bg, 0, i)]
    img[bg] = background
    e = _edges(r)
    e2 = e.copy()
    e2[:, 1:] |= e[:, :-1]
    e2[1:, :] |= e[:-1, :]
    img[e2] = img[e2] * edge_col
    return img, e2


def visible_runs(fr, r, p0, p1, n=400, tol=0.5):
    """The parts of the 3D segment p0-p1 that the z-buffer r does not hide, as a list of (k, 2) arrays in (u, v)."""
    cam = fr.cam
    pts = np.linspace(np.asarray(p0, float), np.asarray(p1, float), n)
    u, v, d = pts @ cam.right, pts @ cam.up, pts @ cam.eye
    px = np.clip(((u - fr.u0) * fr.s).astype(int), 0, fr.W - 1)
    py = np.clip(((fr.v1 - v) * fr.s).astype(int), 0, fr.H - 1)
    vis = (r["i"][py, px] < 0) | (d >= r["z"][py, px] - tol)
    runs, cur = [], []
    for k in range(n):
        if vis[k]:
            cur.append((u[k], v[k]))
        elif cur:
            runs.append(np.array(cur))
            cur = []
    if cur:
        runs.append(np.array(cur))
    return [x for x in runs if len(x) > 2]


def render(fr, items, ghost=(), ghost_alpha=0.42, keep=None):
    """Shaded RGB image (supersampled) of the items; ghost items blended over where they are in front. keep (a dict)
    receives the scene's z-buffer as keep["r"], for depth-aware overlays."""
    r = rasterise(fr, items)
    if keep is not None:
        keep["r"] = r
    img, _e = shade_image(fr, r)
    if ghost:
        g = rasterise(fr, list(ghost))
        gimg, ge = shade_image(fr, g, edge_col=1.0)
        front = (g["i"] >= 0) & (g["z"] > r["z"])
        img[front] = img[front] * (1 - ghost_alpha) + gimg[front] * ghost_alpha
        yy, xx = np.mgrid[0:fr.H, 0:fr.W]
        dash = ((xx // (5 * fr.ss)) + (yy // (5 * fr.ss))) % 2 == 0
        line = ge & front & dash
        img[line] = (0.25, 0.27, 0.32)
    ss = fr.ss
    img = img.reshape(fr.H // ss, ss, fr.W // ss, ss, 3).mean((1, 3))
    return np.clip(img, 0, 1)


def bounds(cam, items, pad=0.0):
    pts = []
    for it in items:
        s = it[1]
        if isinstance(s, M.MeshSolid):
            pts.append(s.v)
        else:
            bb = s.bounding_box()
            pts.append(np.array([[x, y, z] for x in (bb.min.X, bb.max.X) for y in (bb.min.Y, bb.max.Y)
                                 for z in (bb.min.Z, bb.max.Z)]))
    uv = cam.uv(np.vstack(pts))
    return uv.min(0) - pad, uv.max(0) + pad


# ---------------------------------------------------------------------------------------------------------------
# Figure helpers
# ---------------------------------------------------------------------------------------------------------------
def canvas(fr, img, pad=(10, 10, 10, 10), px_per_mm=None):
    """A matplotlib figure showing the render at 1:1 pixels, with room (mm) for callouts: pad = (left, right, bottom,
    top). Returns fig, ax; ax data units are the view's millimetres."""
    ppm = px_per_mm or fr.s / fr.ss
    u0, u1, v0, v1 = fr.extent()
    xl = (u0 - pad[0], u1 + pad[1])
    yl = (v0 - pad[2], v1 + pad[3])
    wpx, hpx = (xl[1] - xl[0]) * ppm, (yl[1] - yl[0]) * ppm
    dpi = 100
    fig = plt.figure(figsize=(wpx / dpi, hpx / dpi), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.imshow(img, extent=fr.extent(), origin="upper", interpolation="lanczos", zorder=0)
    ax.set_xlim(*xl)
    ax.set_ylim(*yl)
    ax.set_aspect("equal")
    ax.set_axis_off()
    return fig, ax


def callout(ax, xy, text, xytext, ha="center", va="center", fs=FS, color=INK, lw=0.8):
    ax.annotate(text, xy=xy, xytext=xytext, ha=ha, va=va, fontsize=fs, color=color, zorder=20,
                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec=(0.62, 0.62, 0.62), lw=0.6),
                arrowprops=dict(arrowstyle="-", lw=lw, color=(0.22, 0.22, 0.22), shrinkA=0, shrinkB=0))
    ax.plot([xy[0]], [xy[1]], "o", ms=3.2, color=(0.22, 0.22, 0.22), zorder=21)


def save(fig, name, title):
    path = os.path.join(OUT, name)
    os.makedirs(OUT, exist_ok=True)
    fig.savefig(path, facecolor="white", dpi=100)
    plt.close(fig)
    RL.autocrop(path, title=title)
    shrink(path)
    print(f"{os.path.relpath(path, HERE)}  {os.path.getsize(path) / 1000:.0f} kB")


def shrink(path):
    from PIL import Image
    if os.path.getsize(path) <= MAX_PNG:
        return
    im = Image.open(path).convert("RGB")
    im.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(path, optimize=True)
    while os.path.getsize(path) > MAX_PNG:
        w, h = im.size
        f = max(0.8, (MAX_PNG / os.path.getsize(path)) ** 0.5)
        im = im.resize((int(w * f), int(h * f)), Image.LANCZOS)
        im.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(path, optimize=True)


def P(cam, p):
    return tuple(cam.uv(p)[0])


def note(ax, x, y, text, fs=FS_NOTE, ha="left", va="top", color=GREY):
    ax.text(x, y, text, ha=ha, va=va, fontsize=fs, color=color, zorder=20, linespacing=1.35)


# ---------------------------------------------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------------------------------------------
def _cp(cps, key):
    return next(c for c in cps if c.key == key)


ASSY_VIEW = (42, -150)
EXPLODE_VIEW = (24, -140)
EXPLODE_LIFT = dict(hall=70.0, tmr=70.0, shear=70.0, coil=22.0, haptics=22.0, kvm=22.0)
EXPLODE_KEYS = 22.0
RIG_VIEW = (36, -124)
ZT = M.MEZZ + M.PCB_T          # a seated coupon's top surface


def fig_assembly():
    cps = M.coupons()
    items, ghost = M.assembly(cps=cps)
    cam = Camera(*ASSY_VIEW)
    lo, hi = bounds(cam, items + ghost)
    fr = Frame(cam, lo, hi, px_per_mm=4.6)
    img = render(fr, items, ghost)
    fig, ax = canvas(fr, img, pad=(32, 36, 36, 10))
    q = lambda p: P(cam, p)                                   # noqa: E731
    hall, tmr, shear, coil, hap, kvm = (_cp(cps, k) for k in ("hall", "tmr", "shear", "coil", "haptics", "kvm"))
    callout(ax, q(hall.world(hall.w / 2 - M.PITCH, M.KEY_ROWS[1], 18)), "S1 Hall-effect coupon", (-136, 100))
    callout(ax, q(tmr.world(tmr.w / 2, M.KEY_ROWS[1], 18)), "S2 TMR coupon", (-112, 142))
    callout(ax, q(shear.world(*M.SHEAR_SITES[1][:2], 18)), "S3 shear coupon", (-48, 175))
    callout(ax, q(hap.world(65.5, 4.5)), "S5 haptics coupon", (94, 62))
    callout(ax, q(coil.world(34.0, 8.0)), "S4 coil DOE coupon", (40, -4))
    callout(ax, q(kvm.world(10.0, 30.0)), "KVM coupon on J_KVM\n(optional: a ghost)", (104, 136))
    callout(ax, q((-1.0, M.USB_C_PORT[1], 1.6)), "USB-C J1", (-100, 2))
    callout(ax, q((M.TYPEC_XY[0], M.TYPEC_XY[1], 0.4)), "Type-C current\ndetect (I2C)", (-124, 26))
    callout(ax, q((M.MCU_XY[0] - 7.9, M.USB_C_PORT[1] - 0.75, 1.0)), "STM32U5A5\n(rev A MCU)", (-56, -10))
    callout(ax, q((M.CELL_X0 + 4 * M.CELL_W + 4.2, 76.0, 8.3)), "power: input breaker,\nslot switches, 13 INA226-\n"
            "class monitors, LDOs", (66, 166))
    u0, u1, v0, v1 = fr.extent()
    note(ax, u0 - 30, v0 - 16, "Solder-mask colours only tell the coupons apart. Board and coupon sizes are the "
         "draft SPEC's (about 190 x 150,\n58 x 60 and 80 x 60 mm); the positions are this sketch's. No battery or "
         "charger on rev A.")
    save(fig, "testbed_assembly.png", "Rev A testbed concept: motherboard with plug-in coupons, 3/4 view")


def fig_exploded():
    cps = M.coupons()
    items, ghost = M.assembly(lift=EXPLODE_LIFT, key_lift=EXPLODE_KEYS, cps=cps)
    cam = Camera(*EXPLODE_VIEW)
    lo, hi = bounds(cam, items + ghost)
    fr = Frame(cam, lo, hi, px_per_mm=4.0)
    keep = {}
    img = render(fr, items, ghost, keep=keep)
    fig, ax = canvas(fr, img, pad=(66, 62, 42, 18))
    q = lambda p: P(cam, p)                                   # noqa: E731
    # dashed guides from each coupon's header down to its socket, hidden where a part is in front of them
    for c in cps:
        sx, sy = c.socket_xy()
        lift = EXPLODE_LIFT[c.key]
        for dx in (-22.0, 22.0):
            x = sx + dx * c.n / M.SLOT_N
            for run in visible_runs(fr, keep["r"], (x, sy, M.SOCKET_H), (x, sy, lift + M.MEZZ - M.SOCKET_H)):
                ax.plot(run[:, 0], run[:, 1], ls=(0, (4, 3)), lw=1.1, color=HL, zorder=5)
    hall, tmr, shear, coil, hap, kvm = (_cp(cps, k) for k in ("hall", "tmr", "shear", "coil", "haptics", "kvm"))
    lb, lf = EXPLODE_LIFT["hall"], EXPLODE_LIFT["coil"]
    u0, u1, v0, v1 = fr.extent()
    xl, xr = u0 - 30, u1 + 30
    callout(ax, q(hall.world(hall.w / 2 - M.PITCH, M.KEY_ROWS[1], 18 + EXPLODE_KEYS, lift=lb)),
            "keys lifted off\n(switch + keycap)", (xl, 166))
    callout(ax, q(hall.world(M.KEY_EEPROM_X, M.FRONT_Y, 1.5, lift=lb)), "S1 Hall-effect: a TMAG5253\nper key; "
            "reference sensors,\nthermistors, a decoder; the\ndescriptor EEPROM (SOIC-8)\nthat every coupon "
            "carries", (xl, 116))
    callout(ax, q(tmr.world(tmr.w / 2, M.KEY_ROWS[1], 18 + EXPLODE_KEYS, lift=lb)), "S2 TMR: the same keys\n"
            "on a TMR sensor", (-62, v1 + 8))
    callout(ax, q(shear.world(*M.SHEAR_SITES[1][:2], 18 + EXPLODE_KEYS, lift=lb)), "S3 shear: TMAG5170 under a\n"
            "stock stem and under a\ncentring-stem prototype", (52, v1 + 6))
    callout(ax, q(hap.world(M.ROLLER_X, M.WHEEL[1], 35, lift=lf)), "S5 haptics: DRV8316 and\nMT6701CT "
            "(candidates),\ngimbal motor; DRV2605L,\ncoin LRA; capacitive strip\non a touch controller", (xr, 150))
    callout(ax, q(kvm.world(10.0, 30.0, lift=lf)), "KVM coupon (optional),\non J_KVM, a 2 x 6 header", (xr, 112))
    callout(ax, q(hap.world(hap.post[0], hap.post[1], -M.PCB_T - 4.0, lift=lf)), "M3 nylon post,\none per coupon",
            (xr, 80))
    callout(ax, q(coil.world(34.0, 8.0, lift=lf)), "S4 coil DOE: 20 generated\nspirals, LDC1614-class\n"
            "converters", (18, v0 - 12))
    s1x, s1y = hall.socket_xy()
    callout(ax, q((s1x - 2.54 * (M.SLOT_N - 1) / 2, s1y - 2.54, M.SOCKET_H)), "2 x 20, 2.54 mm female\n"
            "through-hole socket per\nslot, 8.5 mm tall; a male\nheader on each coupon\n(owner's decision D2)",
            (xl, 14))
    note(ax, u0 - 64, v0 - 26, "Back-row coupons lifted 70 mm, front-row 22 mm, keys a further 22 mm so the "
         "sensors show.\nDashed: each coupon's header to its socket. Every part named is a candidate.")
    save(fig, "testbed_exploded.png", "Rev A testbed concept: coupons lifted out of their sockets")


# the strip detail in the top view: its left half, drawn at DETAIL_K times the main view's scale
DETAIL_X = (-2.0, 101.0)
DETAIL_Y = (61.0, 89.0)
DETAIL_K = 2.0
DETAIL_TOP = -72.0             # the detail's top edge, in the main view's millimetres


def fig_top():
    cps = M.coupons()
    items, ghost = M.assembly(cps=cps)
    cam = Camera(90, -90)
    lo, hi = bounds(cam, items + ghost)
    ppm = 4.5
    fr = Frame(cam, lo, hi, px_per_mm=ppm)
    img = render(fr, items, ghost, ghost_alpha=0.38)
    fig, ax = canvas(fr, img, pad=(64, 66, 190, 30))
    hall, tmr, shear, coil, hap, kvm = (_cp(cps, k) for k in ("hall", "tmr", "shear", "coil", "haptics", "kvm"))
    w2 = lambda c, x, y: (c.x0 + x, c.y0 + y)                 # noqa: E731
    # back row, above the board
    callout(ax, w2(hall, hall.w / 2 - M.PITCH, M.KEY_ROWS[1]), "S1 Hall-effect: 6 keys\non TMAG5253s, reference\n"
            "sensors, thermistors", (2, 172))
    callout(ax, w2(hall, *hall.post), "M3 nylon post,\none per coupon", (62, 168))
    callout(ax, w2(tmr, tmr.w / 2, M.KEY_ROWS[1]), "S2 TMR: the same\nkeys on a TMR sensor", (112, 170))
    callout(ax, w2(shear, *M.SHEAR_SITES[1][:2]), "S3 shear: TMAG5170\nunder a stock stem and\na centring-stem "
            "prototype", (178, 172))
    # front row, below the board
    callout(ax, w2(coil, *M.COIL_ORIGIN), "S4 coil DOE: 20 generated\nspirals, LDC1614-class\nconverters (U1-U5)",
            (0, -19))
    callout(ax, w2(hap, M.ROLLER_X, M.WHEEL[1]), "S5 haptics: gimbal motor\nand roller, DRV8316,\nMT6701CT "
            "(candidates)", (95, -19))
    callout(ax, w2(hap, *M.TOUCH_PADS[2]), "capacitive strip on an\nexternal touch controller", (152, -17))
    callout(ax, w2(hap, M.LRA_XY[0], M.LRA_XY[1] - 4.5), "coin LRA and\nDRV2605L", (222, 10))
    # right side
    callout(ax, w2(kvm, kvm.w / 2, 24.0), "J_KVM (2 x 6): the\noptional KVM coupon,\na ghost: host-B\n"
            "controller, isolator,\nUSB-C B", (222, 46))
    callout(ax, (M.CELL_X0 + 4 * M.CELL_W + 11.2, 83.6), "power, no charger (D1):\ninput breaker, two\n"
            "LDOs, a 3.3 V and a\n5 V switch per slot,\n13 INA226-class\nmonitors (VSSOP-10)", (222, 98))
    # left side: the header pins, and a bracket on the strip
    hx = hall.x0 + hall.header[0] - 2.54 * (M.SLOT_N - 1) / 2
    callout(ax, (hx, hall.y0 + hall.header[1] - 1.27), "2 x 20 header pins:\nthe slot connector\n(owner's D2)",
            (-32, 112))
    bx = -5.0
    ax.plot([bx + 1.5, bx, bx, bx + 1.5], [M.STRIP[0], M.STRIP[0], M.STRIP[1], M.STRIP[1]], color=GREY, lw=1.2,
            zorder=20)
    callout(ax, (bx, sum(M.STRIP) / 2), "the strip between the\nslot rows: its left half\nis drawn below, at "
            "twice\nthe scale", (-34, 72))
    # the strip detail: the motherboard alone (no coupons over it), at twice the scale
    dfr = Frame(cam, np.array([DETAIL_X[0], DETAIL_Y[0]]), np.array([DETAIL_X[1], DETAIL_Y[1]]),
                px_per_mm=ppm * DETAIL_K, margin=0.0)
    dimg = render(fr=dfr, items=M.motherboard(cps=cps))
    dw, dh = (DETAIL_X[1] - DETAIL_X[0]) * DETAIL_K, (DETAIL_Y[1] - DETAIL_Y[0]) * DETAIL_K
    dx0 = M.MB_W / 2 - dw / 2
    ax.imshow(dimg, extent=(dx0, dx0 + dw, DETAIL_TOP - dh, DETAIL_TOP), origin="upper", interpolation="lanczos",
              zorder=1)
    ax.add_patch(Rectangle((dx0, DETAIL_TOP - dh), dw, dh, fc="none", ec=(0.55, 0.55, 0.58), lw=0.9, zorder=2))
    D = lambda x, y: (dx0 + (x - DETAIL_X[0]) * DETAIL_K, DETAIL_TOP - (DETAIL_Y[1] - y) * DETAIL_K)  # noqa: E731
    ax.text(M.MB_W / 2, -33.0, "The strip's left half at twice the scale (the coupons over it left out)",
            ha="center", va="center", fontsize=FS + 0.5, color=INK, weight="bold", zorder=20)
    t2, t1 = -43.5, -61.0
    callout(ax, D(M.TYPEC_XY[0], M.TYPEC_XY[1] + 0.8), "Type-C current detect (I2C)\nU_CC, candidate TUSB320LAI",
            (D(M.TYPEC_XY[0], 0)[0], t2))
    callout(ax, D(M.MCU_XY[0] + 0.5, M.MCU_XY[1] + 6.0), "STM32U5A5 (rev A\nMCU), LQFP100;\nPA11/PA12 face J1",
            (D(M.MCU_XY[0] + 0.5, 0)[0] - 2.0, t1))
    callout(ax, D(M.RESET_XY[0], M.RESET_XY[1] + 1.0), "reset and\nBOOT0", (D(M.RESET_XY[0], 0)[0] - 2.0, t1))
    callout(ax, D(M.RIG_HEADER[0], M.RIG_HEADER[1] + 6.35), "J_RIG latency-rig\nheader, 2 x 5",
            (D(M.RIG_HEADER[0], 0)[0] + 2.0, t2))
    mx, my = M.LOGIC["I2C mux"]
    callout(ax, D(mx, my + 3.2), "I2C mux, three\nI/O expanders", (D(mx, 0)[0] + 2.0, t1))
    tx, ty = M.TEST_PADS[-3]
    callout(ax, D(tx, ty + 0.65), "test pads", (D(tx, 0)[0] + 6.0, t2))
    b1 = DETAIL_TOP - dh - 13.0
    callout(ax, D(2.0, 68.0), "USB-C J1, ESD\narray, VBUS TVS", (D(2.0, 0)[0] - 20.0, b1))
    callout(ax, D(14.0, M.USB_C_PORT[1]), "short 90 ohm pair,\nabout 10 mm", (D(14.0, 0)[0] + 6.0, b1))
    callout(ax, D(M.HSE_XY[0], M.HSE_XY[1] - 1.25), "16 MHz HSE\ncrystal", (D(M.HSE_XY[0], 0)[0], b1))
    callout(ax, D(M.SWD_XY[0], M.SWD_XY[1] - 4.5), "J_SWD: STDC14,\n2 x 7 at 1.27 mm", (D(M.SWD_XY[0], 0)[0], b1))
    jx, jy = M.INJ_JUMPERS[2]
    callout(ax, D(jx, jy - 0.75), "JP_INJ1-5 solder jumpers\n(open by default) to each\nslot's INJ pin",
            (D(jx, 0)[0] + 10.0, b1))
    note(ax, -62, b1 - 12, "Top view to scale: motherboard about 190 x 150 mm, standard coupons about 58 x 60 mm and "
         "wide ones about 80 x 60 mm, the sizes\nin the draft SPEC (section 2), which follow from the owner's 2 x 20 "
         "slot connector; layout sets the outlines. The rows follow\nSPEC section 9; the positions in them are this "
         "sketch's. The MCU, the owner's rev A choice, is drawn as its LQFP100\n(14 x 14 mm), turned so that "
         "PA11/PA12 (pins 70/71) face the USB-C; every other part named is a candidate. 16 MHz HSE:\nin the PHY's "
         "list (RM0456 Rev 7, read in a transcription; Zephyr agrees). The keycaps hide the key sensors (see the\n"
         "exploded view). Pale and dashed: the optional KVM coupon.")
    save(fig, "testbed_top.png", "Rev A testbed concept: top view")


def fig_latency_rig():
    cps = M.coupons()
    hall = _cp(cps, "hall")
    items = M.motherboard(cps=cps, closed_jumpers=(1,)) + hall.items() + M.latency_rig() + M.rig_cables()
    cam = Camera(*RIG_VIEW)
    lo, hi = bounds(cam, items)
    fr = Frame(cam, lo, hi, px_per_mm=4.0)
    img = render(fr, items)
    fig, ax = canvas(fr, img, pad=(4, 4, 86, 16))
    paths = M.rig_paths()
    q = lambda p: P(cam, p)                                   # noqa: E731
    u0, u1, v0, v1 = fr.extent()
    # the lower callouts in one row under the picture, in the order of their anchors, so no leaders cross
    yl = v0 - 14
    callout(ax, q((*M.RIG_MCU, 1.5)), "latency rig, 100 x 80 mm:\nhigh-speed USB host and\nstimulus drivers "
            "(parts\nnot chosen)", (u0 + 32, yl))
    callout(ax, q(paths["usb"][32]), "USB cable: the rig is\nthe USB host and time-\nstamps each HID report",
            (u0 + 120, yl))
    callout(ax, q((M.INJ_JUMPERS[0][0], M.INJ_JUMPERS[0][1] - 0.5, 0.3)), "JP_INJ1 closed: RIG_INJ\nreaches "
            "slot S1's INJ pin\n(all five open by default)", (u0 + 200, yl))
    callout(ax, q(paths["ribbon"][22]), "ribbon to J_RIG: marker,\ntrigger (t0), frame tick,\nUSB SOF, "
            "the INJ stimulus", (u0 + 80, v1 + 4))
    callout(ax, q(hall.world(hall.w / 2, M.KEY_ROWS[1], 18)), "Hall-effect coupon in S1\n(under test); the "
            "other\ncoupons unplugged", (u0 + 190, v1 + 4))
    # the measurement path, as a strip of boxes under the picture
    steps = ["rig drives INJ;\nits trigger edge: t0", "the coupon's stimulus\npoint on a lane",
             "MCU scan and\nkey decision", "HID report over\nUSB (marker GPIO)", "rig (USB host)\ntimestamps it: t1"]
    xs = np.linspace(u0 + 2, u1 - 2, len(steps) + 1)
    yb = v0 - 58
    ax.text((u0 + u1) / 2, yb + 12, "Planned measurement path (concept.md section 4.2, SPEC section 7.3)",
            ha="center", va="bottom", fontsize=FS + 0.5, color=INK, weight="bold")
    for k, txt in enumerate(steps):
        xa, xb = xs[k] + 5, xs[k + 1] - 5
        ax.add_patch(FancyBboxPatch((xa, yb - 8), xb - xa, 16, boxstyle="round,pad=0.4,rounding_size=2",
                                    fc=(0.96, 0.96, 0.97), ec=(0.55, 0.55, 0.58), lw=0.9, zorder=10))
        ax.text((xa + xb) / 2, yb, txt, ha="center", va="center", fontsize=FS, color=INK, zorder=11)
        if k:
            ax.annotate("", xy=(xa - 0.6, yb), xytext=(xs[k] - 4.4, yb),
                        arrowprops=dict(arrowstyle="-|>", lw=1.3, color=INK), zorder=11)
    ax.text((u0 + u1) / 2, yb - 12, "Latency = t1 - t0, to be published as p50 and p99 per mode. The marker GPIO "
            "splits it into\ncapture, decision, queue and transmit. Nothing here is built or measured.",
            ha="center", va="top", fontsize=FS_NOTE, color=GREY, linespacing=1.35)
    save(fig, "testbed_latency_rig.png", "Rev A testbed concept: latency rig, motherboard and one coupon")


# ---------------------------------------------------------------------------------------------------------------
# The coil DOE coupon, 2D (PCB view)
# ---------------------------------------------------------------------------------------------------------------
SUBSTRATE = (0.07, 0.09, 0.08)
LAYER_STYLE = [  # (colour, alpha) top to bottom: the top copper solid, lower layers seen through the board
    ((0.86, 0.55, 0.26), 1.0),
    ((0.30, 0.62, 0.86), 0.55),
    ((0.55, 0.80, 0.45), 0.45),
    ((0.80, 0.45, 0.80), 0.45),
]


def _poly(ax, pts, **kw):
    p = np.asarray(pts)
    codes = [Path.MOVETO] + [Path.LINETO] * (len(p) - 1) + [Path.CLOSEPOLY]
    ax.add_patch(PathPatch(Path(np.vstack([p, p[:1]]), codes), **kw))


def _draw_coil(ax, coil, centre, lead=M.COIL_LEAD, pts_per_turn=180):
    layers, vias = CO.coil_layers(coil, centre, pts_per_turn=pts_per_turn, end_angle=M.COIL_LEAD_ANGLE)
    # draw bottom-most first so the top copper sits on top
    for layer in sorted(layers, key=lambda L: -L.index):
        colr, alpha = LAYER_STYLE[min(layer.index, 3)]
        pts = layer.points
        if layer.index == 0:
            pts = np.vstack([pts[0] + (lead, 0.0), pts])
        elif layer.index == len(layers) - 1 and coil.layers > 1:
            pts = np.vstack([pts, pts[-1] + (lead, 0.0), pts[-1] + (lead, -1.0)])
        elif coil.layers == 1:
            pts = np.vstack([pts, (centre[0] + coil.r_out + lead, pts[-1][1]),
                             (centre[0] + coil.r_out + lead, centre[1] - 1.0)])
        _poly(ax, CO.band(pts, coil.trace), fc=colr, ec="none", alpha=alpha, zorder=3 + (3 - layer.index))
    for vx, vy, _l in vias:
        ax.add_patch(Circle((vx, vy), 0.275, fc=(0.86, 0.72, 0.36), ec="none", zorder=8))
        ax.add_patch(Circle((vx, vy), 0.125, fc=SUBSTRATE, ec="none", zorder=9))
    end = layers[0].points[0] + (lead, 0.0)
    for dy in (0.0, -1.0):
        ax.add_patch(Circle((end[0], end[1] + dy), 0.275, fc=(0.86, 0.72, 0.36), ec="none", zorder=8))
        ax.add_patch(Circle((end[0], end[1] + dy), 0.125, fc=SUBSTRATE, ec="none", zorder=9))


def fig_coil_coupon():
    """The coupon on top (row and column headers beside it), the legend and C3 taken apart layer by layer below it,
    then the notes: stacked, so the image stays about 1400 px wide and its text readable at the docs width."""
    import textwrap
    ppm, dpi = 16.0, 100
    W, D = M.WIDE
    xl, yl = (-12.5, W + 2.0), (-45.0, D + 6.5)
    fig = plt.figure(figsize=((xl[1] - xl[0]) * ppm / dpi, (yl[1] - yl[0]) * ppm / dpi), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(*xl)
    ax.set_ylim(*yl)
    ax.set_aspect("equal")
    ax.set_axis_off()
    # font size (pt) for a text height in mm, scaled up by the width the 80 mm coupon added over the old 72 mm
    # sketch, so the text stays as large when the docs show the image about 688 px wide
    fs_mm = lambda mm: mm * 1.09 * ppm * 72 / dpi      # noqa: E731
    ax.add_patch(FancyBboxPatch((0, 0), W, D, boxstyle="round,pad=0,rounding_size=1.5", fc=SUBSTRATE,
                                ec=(0.3, 0.3, 0.3), lw=1.0, zorder=1))
    silk = (0.93, 0.93, 0.90)
    layout = CO.doe_layout(M.COIL_PITCH, M.COIL_ORIGIN)
    for coil, (cx, cy) in layout:
        _draw_coil(ax, coil, (cx, cy))
        # stock-MX centre-post hole (non-plated)
        ax.add_patch(Circle((cx, cy), CO.MX_CENTRE_HOLE / 2, fc=(0.0, 0.0, 0.0), ec=(0.45, 0.45, 0.45), lw=0.6,
                            zorder=10))
        if coil.tag[0] in "ABC":
            for px, py in CO.MX_PINS:
                ax.add_patch(Circle((cx + px, cy + py), CO.MX_PIN_HOLE / 2, fc="none", ec=(0.75, 0.75, 0.75),
                                    lw=0.7, ls=(0, (2, 1.5)), zorder=10))
        # the column gives the trace and the row the layers, so each coil is labelled with its turns only
        ax.text(cx, cy - coil.d_out / 2 - 0.3, f"{coil.turns:g} turns", ha="center", va="top", fontsize=fs_mm(1.1),
                color=silk, zorder=12)
        ax.text(cx, cy, coil.tag, ha="center", va="center", fontsize=fs_mm(1.0), color=(0.72, 0.72, 0.72),
                zorder=12)
    # converters, the descriptor EEPROM, the M3 post, and the 2 x 20 slot header: its body underneath (dashed)
    # and its through-hole pads on top
    for i, (xx, yy) in enumerate(M.COIL_LDC):
        ax.add_patch(Rectangle((xx - 2.0, yy - 2.0), 4.0, 4.0, fc=(0.02, 0.02, 0.02), ec=(0.6, 0.6, 0.6), lw=0.6,
                               zorder=6))
        ax.text(xx, yy, f"U{i + 1}", ha="center", va="center", fontsize=fs_mm(1.0), color=silk, zorder=7)
    ex, ey = M.COIL_EEPROM
    ax.add_patch(Rectangle((ex - 1.95, ey - 2.45), 3.9, 4.9, fc=(0.02, 0.02, 0.02), ec=(0.6, 0.6, 0.6), lw=0.6,
                           zorder=6))
    ax.text(ex, ey, "ID", ha="center", va="center", fontsize=fs_mm(1.0), color=silk, zorder=7)
    px, py = (W - 3.5, 3.5)
    ax.add_patch(Circle((px, py), 1.6, fc=(0.0, 0.0, 0.0), ec=(0.75, 0.75, 0.75), lw=0.8, zorder=6))
    hx, hy = W / 2, D - M.HDR_IN
    L = 2.54 * M.SLOT_N
    ax.add_patch(Rectangle((hx - L / 2, hy - 2.54), L, 5.08, fc="none", ec=(0.6, 0.6, 0.6), lw=0.7, ls=(0, (3, 2)),
                           zorder=5))
    for k in range(M.SLOT_N):
        for s in (-1.27, 1.27):
            ax.add_patch(Circle((hx + (k - (M.SLOT_N - 1) / 2) * 2.54, hy + s), 0.75, fc=(0.86, 0.72, 0.36),
                                ec="none", zorder=6))
            ax.add_patch(Circle((hx + (k - (M.SLOT_N - 1) / 2) * 2.54, hy + s), 0.35, fc=SUBSTRATE, ec="none",
                                zorder=7))
    # row and column headers
    for ri, row in enumerate(CO.ROWS):
        y = M.COIL_ORIGIN[1] + ri * M.COIL_PITCH[1]
        body = textwrap.fill(row["tag"], width=10, break_on_hyphens=False)
        ax.text(-1.2, y, f"row {'ABCD'[ri]}\n{body}", ha="right", va="center", fontsize=fs_mm(1.2), color=INK,
                linespacing=1.2)
    for ci, w in enumerate(CO.TRACES):
        x = M.COIL_ORIGIN[0] + ci * M.COIL_PITCH[0]
        ax.text(x, D + 1.0, f"trace = space\n{w:g} mm", ha="center", va="bottom", fontsize=fs_mm(1.2), color=INK,
                linespacing=1.2)
    # the two coils that carry a stock switch in the 3D renders
    for coil, (cx, cy) in layout:
        if coil.tag in M.COIL_SWITCH_TAGS:
            ax.add_patch(Rectangle((cx - 7.0, cy - 7.0), 14.0, 14.0, fc="none", ec=(0.80, 0.80, 0.80), lw=0.9,
                                   ls=(0, (1.5, 1.5)), zorder=11))
    # legend, under the coupon on the left
    lx, ly = -10.5, -2.4
    ax.text(lx, ly, "Legend", fontsize=fs_mm(1.3), color=INK, weight="bold", va="top")
    rows = [("L1, top copper", "layer", 0), ("L2, seen through the board", "layer", 1), ("L3", "layer", 2),
            ("L4", "layer", 3), ("via", "via", None), ("MX centre-post hole", "hole", None),
            ("stock-MX pin positions", "pin", None), ("LDC1614-class converter", "ldc", None),
            ("2 x 20 slot header (body underneath)", "hdr", None), ("stock switch in the 3D renders", "sw", None),
            ("M3 post hole; ID: descriptor EEPROM", "post", None)]
    for k, (txt, kind, li) in enumerate(rows):
        y = ly - 3.2 - 2.25 * k
        if kind == "layer":
            colr, alpha = LAYER_STYLE[li]
            ax.add_patch(Rectangle((lx, y - 0.45), 3.0, 0.9, fc=colr, alpha=alpha, ec="none"))
        elif kind == "via":
            ax.add_patch(Circle((lx + 1.5, y), 0.42, fc=(0.86, 0.72, 0.36), ec="none"))
        elif kind == "hole":
            ax.add_patch(Circle((lx + 1.5, y), 0.75, fc="k", ec=(0.45, 0.45, 0.45), lw=0.6))
        elif kind == "pin":
            ax.add_patch(Circle((lx + 1.5, y), 0.7, fc="none", ec=(0.4, 0.4, 0.4), lw=0.8, ls=(0, (2, 1.5))))
        elif kind == "ldc":
            ax.add_patch(Rectangle((lx + 0.7, y - 0.75), 1.5, 1.5, fc=(0.02, 0.02, 0.02), ec=(0.5, 0.5, 0.5), lw=0.6))
        elif kind == "hdr":       # a short strip of pads in a dashed outline, like the header on the board
            ax.add_patch(Rectangle((lx + 0.1, y - 0.7), 2.8, 1.4, fc="none", ec=(0.5, 0.5, 0.5), lw=0.7,
                                   ls=(0, (3, 2))))
            for k in range(3):
                ax.add_patch(Circle((lx + 0.6 + 0.9 * k, y), 0.32, fc=(0.86, 0.72, 0.36), ec="none"))
        elif kind == "post":
            ax.add_patch(Circle((lx + 1.5, y), 0.75, fc="k", ec=(0.6, 0.6, 0.6), lw=0.7))
        else:                     # a square, like the switch footprints on the board
            ax.add_patch(Rectangle((lx + 0.75, y - 0.75), 1.5, 1.5, fc="none", ec=(0.45, 0.45, 0.45), lw=0.8,
                                   ls=(0, (1.5, 1.5))))
        ax.text(lx + 4.0, y, txt, fontsize=fs_mm(1.1), color=INK, va="center")
    # inset, under the coupon on the right: one 4-layer coil taken apart layer by layer, L1 to L4 left to right
    demo = next((c, xy) for c, xy in layout if c.tag == "C3")[0]
    k_s, half, gap = 1.75, 6.6, 1.3
    ix = W + 1.5 - 4 * 2 * half - 3 * gap
    layers, vias = CO.coil_layers(demo, (0.0, 0.0), pts_per_turn=180, end_angle=M.COIL_LEAD_ANGLE)
    ax.text(ix, ly, f"C3 layer by layer ({demo.label(' · ')})", fontsize=fs_mm(1.2), color=INK, weight="bold",
            va="top")
    pcy = ly - 2.2 - half
    centres = [(ix + half + k * (2 * half + gap), pcy) for k in range(4)]
    for li, (layer, (pcx, pcy)) in enumerate(zip(layers, centres)):
        ax.add_patch(FancyBboxPatch((pcx - half, pcy - half), 2 * half, 2 * half,
                                    boxstyle="round,pad=0,rounding_size=0.8", fc=SUBSTRATE, ec="none", zorder=1))
        pts = layer.points * k_s + (pcx, pcy)
        colr = LAYER_STYLE[li][0]
        _poly(ax, CO.band(pts, demo.trace * k_s), fc=colr, ec="none", zorder=3)
        ax.add_patch(Circle((pcx, pcy), CO.MX_CENTRE_HOLE / 2 * k_s, fc="k", ec=(0.45, 0.45, 0.45), lw=0.5,
                            zorder=4))
        for vx, vy, pair in vias:
            if li in pair:
                ax.add_patch(Circle((pcx + vx * k_s, pcy + vy * k_s), 0.45, fc=(0.86, 0.72, 0.36), ec="none",
                                    zorder=6))
        for frac in (0.25, 0.75):          # the current runs in the point order
            i = int(frac * (len(pts) - 14))
            ax.annotate("", xy=pts[i + 12], xytext=pts[i], zorder=7,
                        arrowprops=dict(arrowstyle="-|>", color="white", lw=1.6, mutation_scale=14))
        edge = pcx + half - 0.4
        if li == 0:                        # the current enters at L1's outer end ...
            ax.annotate("", xy=tuple(pts[0]), xytext=(edge, pts[0][1]), zorder=7,
                        arrowprops=dict(arrowstyle="-|>", color="white", lw=1.6, mutation_scale=12))
        if li == len(layers) - 1:          # ... and leaves at the last layer's outer end
            ax.annotate("", xy=(edge, pts[-1][1]), xytext=tuple(pts[-1]), zorder=7,
                        arrowprops=dict(arrowstyle="-|>", color="white", lw=1.6, mutation_scale=12))
        end = " · in" if li == 0 else (" · out" if li == len(layers) - 1 else "")
        ax.text(pcx - half + 0.45, pcy + half - 0.4, f"L{li + 1}{end}", fontsize=fs_mm(1.05), color=silk, va="top",
                zorder=8)
    ax.text(ix, pcy - half - 0.9, "Mirrored spirals in series, joined by vias (gold). The arrows\nfollow the "
            "current: it turns the same way on every layer,\nso the layers' fields add.", fontsize=fs_mm(1.1),
            color=GREY, va="top", linespacing=1.3)
    foot = ("Under each coil: its turns; each column has one trace (= space), each row one layer count and size. "
            "Generated by coils.py (spiral, coil_layers, doe_layout); the parameters are an illustrative spread "
            "around a stock MX footprint, not checked against JLC's rules or the converter's range. Rows A to C fit "
            "between the MX centre post and its pins; row D is larger, for the slug-stem sites, whose footprint is "
            "not designed. Leads leave to +x; the routing to the converters is not drawn. The outline is the draft "
            "SPEC's wide coupon (about 80 x 60 mm), with the 2 x 20 slot header along its back edge. Nothing measured.")
    ax.text(lx, ly - 3.2 - 2.25 * len(rows) - 0.2, textwrap.fill(foot, width=126), fontsize=fs_mm(1.1), color=GREY,
            va="top", linespacing=1.35)
    path = os.path.join(OUT, "testbed_coil_coupon.png")
    fig.savefig(path, facecolor="white", dpi=dpi)
    plt.close(fig)
    RL.autocrop(path, title="Rev A coil DOE coupon concept: 20 generated spiral variants (PCB view)")
    shrink(path)
    print(f"{os.path.relpath(path, HERE)}  {os.path.getsize(path) / 1000:.0f} kB")


def export_glb():
    items, _ghost = M.assembly()
    # the KVM coupon is optional and drawn only as a ghost in the PNGs, so it stays out of the 3D model
    plain = [(n, s, c) for (n, s, c, *_rest) in items]
    path = os.path.join(MODELS, "testbed_assembly.glb")
    RL.export_glb(plain, path, tol=0.25)
    print(f"  {os.path.getsize(path) / 1e6:.2f} MB")


FIGS = {"assembly": fig_assembly, "exploded": fig_exploded, "top": fig_top, "rig": fig_latency_rig,
        "coil": fig_coil_coupon, "glb": export_glb}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", default=",".join(FIGS), help="comma-separated: " + ", ".join(FIGS))
    a = ap.parse_args()
    for k in a.only.split(","):
        t0 = time.time()
        FIGS[k.strip()]()
        print(f"  ({k}: {time.time() - t0:.1f} s)")


if __name__ == "__main__":
    main()
