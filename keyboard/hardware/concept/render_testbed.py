#!/usr/bin/env python3
"""Concept renders of the rev A sensing testbed (keyboard/docs/concept.md section 7), from testbed_models and coils.

Writes (all in keyboard/hardware/concept/):
    renders/testbed_assembly.png      motherboard with every coupon plugged in, 3/4 view (the KVM coupon as a ghost)
    renders/testbed_exploded.png      the coupons lifted out of their sockets, the keys lifted off the key coupons
    renders/testbed_top.png           top view, a short label per coupon and per motherboard section
    renders/testbed_latency_rig.png   rig + motherboard + the Hall-effect coupon: USB link, ribbon, injection probe
    renders/testbed_coil_coupon.png   2D PCB-style view of the coil DOE coupon: 20 spirals from coils.py, every layer
    models/testbed_assembly.glb       the assembly (the optional KVM coupon left out)

Run from the repo root (about two minutes):

    PY=/path/to/venv/bin/python          # build123d 0.13, matplotlib, numpy, PIL
    $PY keyboard/hardware/concept/render_testbed.py [--only assembly,exploded,top,rig,coil,glb]

How it draws: render_lib's tessellation, palette and Lambert shading, rasterised here with a small numpy z-buffer
(supersampled, with outline edges from depth, normal and part changes) instead of a painter's sort, because the copper,
pads and contacts lie flat on the boards and a depth sort of whole triangles puts them behind the board. The labels
are matplotlib callouts placed in millimetres on the projected view. render_lib.autocrop adds the title and the
concept stamp to every image.

Status: CONCEPT SKETCH. Nothing in keyboard/ is designed, built or measured (keyboard/docs/concept.md). The geometry
is illustrative (testbed_models.py): board sizes, coupon footprints, the mezzanine connector and every position are
placeholders, the parts are the candidates concept.md names, and the coil parameters are an illustrative spread. Every
image carries the render_lib concept stamp.
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

DECAL_WORDS = ("pads", "contacts", "pin 1", "mouth", "tongue", "copper", "vias", "core", "slot", "INJ pad",
               "I-sense pad", "touch pad", "stripe", "holes")


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


def callout(ax, xy, text, xytext, ha="center", va="center", fs=10.5, color=INK, lw=0.8):
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


def note(ax, x, y, text, fs=9.5, ha="left", va="top", color=GREY):
    ax.text(x, y, text, ha=ha, va=va, fontsize=fs, color=color, zorder=20)


# ---------------------------------------------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------------------------------------------
def _cp(cps, key):
    return next(c for c in cps if c.key == key)


ASSY_VIEW = (32, -122)
EXPLODE_VIEW = (22, -122)
EXPLODE_LIFT = dict(hall=66.0, tmr=66.0, shear=66.0, coil=36.0, haptics=36.0, kvm=36.0)
EXPLODE_KEYS = 22.0
RIG_VIEW = (36, -124)
ZT = M.MEZZ + M.PCB_T          # a seated coupon's top surface


def fig_assembly():
    cps = M.coupons()
    items, ghost = M.assembly(cps=cps)
    cam = Camera(*ASSY_VIEW)
    lo, hi = bounds(cam, items + ghost)
    fr = Frame(cam, lo, hi, px_per_mm=8.0)
    img = render(fr, items, ghost)
    fig, ax = canvas(fr, img, pad=(40, 40, 10, 14))
    q = lambda p: P(cam, p)                                   # noqa: E731
    callout(ax, q((50.5, 96.55, ZT + 18)), "Hall-effect coupon", (-48, 102))
    callout(ax, q((96.5, 96.55, ZT + 18)), "TMR coupon", (22, 120))
    callout(ax, q((144, 93.5, ZT + 18)), "shear coupon", (98, 124))
    callout(ax, q((132, 8, ZT)), "haptics coupon", (150, 38))
    callout(ax, q((68, 6, ZT)), "coil DOE coupon", (62, 6))
    callout(ax, q((19, 20, ZT)), "KVM coupon (optional:\ndrawn as a ghost)", (-30, 2))
    callout(ax, q((-1, 94.5, 1.6)), "USB-C", (-66, 62))
    callout(ax, q((15, 79, 0.9)), "MCU (candidate AT32F405)", (-62, 24))
    callout(ax, q((29.5, 96, 9.1)), "latency-rig header", (-52, 80))
    u0, u1, v0, v1 = fr.extent()
    note(ax, u0 - 38, v0 - 4, "Solder-mask colours only tell the coupons apart. Board size, connector, coupon "
         "footprints and layout are illustrative, not decided.", fs=10)
    save(fig, "testbed_assembly.png", "Rev A testbed concept: motherboard with plug-in coupons, 3/4 view")


def fig_exploded():
    cps = M.coupons()
    items, ghost = M.assembly(lift=EXPLODE_LIFT, key_lift=EXPLODE_KEYS, cps=cps)
    cam = Camera(*EXPLODE_VIEW)
    lo, hi = bounds(cam, items + ghost)
    fr = Frame(cam, lo, hi, px_per_mm=6.8)
    keep = {}
    img = render(fr, items, ghost, keep=keep)
    fig, ax = canvas(fr, img, pad=(58, 74, 16, 18))
    q = lambda p: P(cam, p)                                   # noqa: E731
    # dashed guides from each coupon's header down to its socket, hidden where a part is in front of them
    for c in cps:
        hx, hy, _a = c.header
        lift = EXPLODE_LIFT[c.key]
        for run in visible_runs(fr, keep["r"], (c.x0 + hx, c.y0 + hy, 8.5),
                                (c.x0 + hx, c.y0 + hy, lift + M.MEZZ - 8.5)):
            ax.plot(run[:, 0], run[:, 1], ls=(0, (4, 3)), lw=1.1, color=HL, zorder=5)
    zb, zf = ZT + EXPLODE_LIFT["hall"], ZT + EXPLODE_LIFT["coil"]
    callout(ax, q((60, 62.5, zb)),
            "Hall-effect coupon: a TMAG5253 per key;\nreference sensors and thermistors in front", (-62, 118))
    callout(ax, q((50.5, 96.55, zb + EXPLODE_KEYS + 18)), "keys lifted off\n(switch + keycap)", (-52, 160))
    callout(ax, q((96.5, 96.55, zb + EXPLODE_KEYS + 18)), "TMR coupon: the same keys on a TMR sensor", (40, 186))
    callout(ax, q((144, 93.5, zb)), "shear coupon: TMAG5170 under a stock stem\nand under a centring-stem prototype",
            (150, 146))
    callout(ax, q((132, 8, zf)), "haptics coupon: DRV8316 + MT6701CT + gimbal\nmotor; DRV2605L + coin LRA; "
            "capacitive strip", (156, 56))
    callout(ax, q((45, 10, zf)), "coil DOE coupon: 20 generated spirals,\nLDC1614-class converters", (-62, 84))
    callout(ax, q((19, 19, zf)), "KVM coupon (optional,\nonly if the connector\ncan carry it)", (-74, 52))
    callout(ax, q((28, 19, 8.5)), "2 x 10 mezzanine socket per coupon\n(connector type not decided)", (-40, 4))
    u0, u1, v0, v1 = fr.extent()
    note(ax, u0 - 56, v0 - 6, "Back-row coupons lifted 66 mm, front-row 36 mm, keys a further 22 mm so the sensors "
         "show. Dashed: each coupon's header to its socket.", fs=10)
    save(fig, "testbed_exploded.png", "Rev A testbed concept: coupons lifted out of their sockets")


def fig_top():
    cps = M.coupons()
    items, ghost = M.assembly(cps=cps)
    cam = Camera(90, -90)
    lo, hi = bounds(cam, items + ghost)
    fr = Frame(cam, lo, hi, px_per_mm=9.0)
    img = render(fr, items, ghost, ghost_alpha=0.38)
    fig, ax = canvas(fr, img, pad=(70, 74, 30, 24))
    callout(ax, (60.0, 106.0), "Hall-effect: 4 keys on TMAG5253s,\n2 reference sensors, thermistors", (56, 124))
    callout(ax, (106.0, 106.0), "TMR: the same 4 keys\non a TMR sensor", (112, 124))
    callout(ax, (158.0, 82.0), "shear: TMAG5170 under\na stock stem (front) and\na centring-stem "
            "prototype (back)", (196, 92), ha="center")
    callout(ax, (150.0, 40.0), "haptics: gimbal motor\nand roller, DRV8316,\nMT6701CT encoder", (196, 50))
    callout(ax, (149.5, 6.0), "capacitive strip", (192, 12))
    callout(ax, (120.5, 37.0), "coin LRA + DRV2605L", (128, -14))
    callout(ax, (74.0, 3.0), "coil DOE: 20 generated spirals,\nLDC1614-class converters (U1-U5)", (68, -16))
    callout(ax, (19.0, 19.0), "KVM (optional, ghost):\nhost-B controller,\nisolator, USB-C B", (-34, 16))
    callout(ax, (1.0, 94.5), "USB-C", (-22, 104))
    callout(ax, M.MCU_XY, "MCU: candidate\nAT32F405", (-30, 84))
    callout(ax, (17.0, 62.0), "power + charging\n(caliper's power sheets)", (-34, 64))
    callout(ax, (16.0, 47.0), "injection (INJ) and\ncurrent-sense test pads", (-34, 44))
    callout(ax, (29.5, 105.0), "latency-rig header\n(marker GPIO)", (12, 124))
    note(ax, -66, -28, "Top view to scale: motherboard about 160 x 110 mm. The keycaps hide the key sensors (see the "
         "exploded view). Pale and dashed: the optional KVM coupon.", fs=10)
    save(fig, "testbed_top.png", "Rev A testbed concept: top view")


def fig_latency_rig():
    cps = M.coupons()
    hall = _cp(cps, "hall")
    items = M.motherboard(cps=cps) + hall.items() + M.latency_rig() + M.rig_cables()
    cam = Camera(*RIG_VIEW)
    lo, hi = bounds(cam, items)
    fr = Frame(cam, lo, hi, px_per_mm=5.8)
    img = render(fr, items)
    fig, ax = canvas(fr, img, pad=(8, 8, 74, 14))
    paths = M.rig_paths()
    q = lambda p: P(cam, p)                                   # noqa: E731
    u0, u1, v0, v1 = fr.extent()
    callout(ax, q((-105, 92, 0.9)), "latency rig: host MCU, stimulus\ndriver and DAC (parts not chosen)", (-150, 62))
    callout(ax, q(paths["ribbon"][30]), "ribbon to the rig header:\nmarker GPIO", (-62, 100))
    callout(ax, q(paths["usb"][30]), "USB cable: the rig is the USB host and\ntimestamps each HID report", (-106, -26))
    callout(ax, q(paths["lead"][36]), "probe lead (how the rig reaches\nthe pad is not decided)", (-36, -30))
    callout(ax, q((8, 47, 0.05)), "injection test pad (INJ) on the\ncoupon's analog lane (sensor ADC node)", (40, -14))
    callout(ax, q((60, 82, ZT + 18)), "Hall-effect coupon (under test);\nthe other coupons unplugged", (52, 104))
    # the measurement path, as a strip of boxes under the picture
    steps = ["rig steps the\ntest pad: t0", "sensor ADC node\non the analog lane", "MCU scan and\nkey decision",
             "HID report\nover USB", "rig (USB host)\ntimestamps it: t1"]
    xs = np.linspace(u0 + 6, u1 - 6, len(steps) + 1)
    yb = v0 - 48
    ax.text((u0 + u1) / 2, yb + 11, "Planned measurement path (concept.md section 4.2)", ha="center", va="bottom",
            fontsize=11, color=INK, weight="bold")
    for k, txt in enumerate(steps):
        xa, xb = xs[k] + 5, xs[k + 1] - 5
        ax.add_patch(FancyBboxPatch((xa, yb - 7), xb - xa, 14, boxstyle="round,pad=0.4,rounding_size=2",
                                    fc=(0.96, 0.96, 0.97), ec=(0.55, 0.55, 0.58), lw=0.9, zorder=10))
        ax.text((xa + xb) / 2, yb, txt, ha="center", va="center", fontsize=10.5, color=INK, zorder=11)
        if k:
            ax.annotate("", xy=(xa - 0.6, yb), xytext=(xs[k] - 4.4, yb),
                        arrowprops=dict(arrowstyle="-|>", lw=1.3, color=INK), zorder=11)
    ax.text((u0 + u1) / 2, yb - 11, "Latency = t1 - t0, to be published as p50 and p99 per mode. The marker GPIO "
            "splits it into capture, decision, queue and transmit. Nothing here is built or measured.",
            ha="center", va="top", fontsize=10, color=GREY)
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
    ppm, dpi = 17.0, 100
    W, D = 72.0, 50.0
    xl, yl = (-26.0, W + 34.0), (-11.0, D + 8.0)
    fig = plt.figure(figsize=((xl[1] - xl[0]) * ppm / dpi, (yl[1] - yl[0]) * ppm / dpi), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(*xl)
    ax.set_ylim(*yl)
    ax.set_aspect("equal")
    ax.set_axis_off()
    fs_mm = lambda mm: mm * ppm * 72 / dpi             # noqa: E731  font size (pt) for a text height in mm
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
        ax.text(cx, cy - coil.d_out / 2 - 0.35, coil.label(" · "), ha="center", va="top", fontsize=fs_mm(0.95),
                color=silk, zorder=12)
        ax.text(cx, cy, coil.tag, ha="center", va="center", fontsize=fs_mm(0.85), color=(0.72, 0.72, 0.72),
                zorder=12)
    # converters and the mezzanine header outline (underneath, dashed)
    for i, yy in enumerate((6.0, 15.0, 24.0, 33.0, 42.0)):
        ax.add_patch(Rectangle((64.0, yy - 2.0), 4.0, 4.0, fc=(0.02, 0.02, 0.02), ec=(0.6, 0.6, 0.6), lw=0.6,
                               zorder=6))
        ax.text(66.0, yy, f"U{i + 1}", ha="center", va="center", fontsize=fs_mm(0.8), color=silk, zorder=7)
    ax.add_patch(Rectangle((66.0 - 2.54, 30.0 - 12.7), 5.08, 25.4, fc="none", ec=(0.6, 0.6, 0.6), lw=0.7,
                           ls=(0, (3, 2)), zorder=5))
    # row and column headers
    for ri, row in enumerate(CO.ROWS):
        y = M.COIL_ORIGIN[1] + ri * M.COIL_PITCH[1]
        ax.text(-1.5, y, f"row {'ABCD'[ri]}\n{row['tag']}", ha="right", va="center", fontsize=fs_mm(1.1),
                color=INK, linespacing=1.25)
    for ci, w in enumerate(CO.TRACES):
        x = M.COIL_ORIGIN[0] + ci * M.COIL_PITCH[0]
        ax.text(x, D + 1.2, f"trace = space\n{w:g} mm", ha="center", va="bottom", fontsize=fs_mm(1.1), color=INK,
                linespacing=1.2)
    # the two coils that carry a stock switch in the 3D renders
    for coil, (cx, cy) in layout:
        if coil.tag in M.COIL_SWITCH_TAGS:
            ax.add_patch(Rectangle((cx - 7.0, cy - 7.0), 14.0, 14.0, fc="none", ec=(0.80, 0.80, 0.80), lw=0.9,
                                   ls=(0, (1.5, 1.5)), zorder=11))
    # legend on the right
    lx, ly = W + 3.0, D - 0.5
    ax.text(lx, ly, "Legend", fontsize=fs_mm(1.2), color=INK, weight="bold", va="top")
    rows = [("L1, top copper", "layer", 0), ("L2, seen through the board", "layer", 1), ("L3", "layer", 2),
            ("L4", "layer", 3), ("via", "via", None), ("MX centre-post hole", "hole", None),
            ("stock-MX pin positions", "pin", None), ("LDC1614-class converter", "ldc", None),
            ("mezzanine header (underneath)", "hdr", None), ("stock switch in the 3D renders", "sw", None)]
    for k, (txt, kind, li) in enumerate(rows):
        y = ly - 3.0 - 1.85 * k
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
        elif kind == "hdr":
            ax.add_patch(Rectangle((lx + 0.3, y - 0.7), 2.4, 1.4, fc="none", ec=(0.5, 0.5, 0.5), lw=0.7,
                                   ls=(0, (3, 2))))
        else:
            ax.add_patch(Rectangle((lx + 0.3, y - 0.7), 2.4, 1.4, fc="none", ec=(0.45, 0.45, 0.45), lw=0.8,
                                   ls=(0, (1.5, 1.5))))
        ax.text(lx + 4.0, y, txt, fontsize=fs_mm(0.95), color=INK, va="center")
    # inset: one 4-layer coil taken apart layer by layer
    demo = next((c, xy) for c, xy in layout if c.tag == "C3")[0]
    k_s, half = 1.75, 6.6
    layers, vias = CO.coil_layers(demo, (0.0, 0.0), pts_per_turn=180, end_angle=M.COIL_LEAD_ANGLE)
    ax.text(lx, 24.6, f"C3 layer by layer ({demo.label(' · ')})", fontsize=fs_mm(1.0), color=INK, weight="bold",
            va="bottom")
    centres = [(lx + half, 17.6), (lx + 3 * half + 1.4, 17.6), (lx + half, 3.6), (lx + 3 * half + 1.4, 3.6)]
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
                        arrowprops=dict(arrowstyle="-|>", color="white", lw=1.6, mutation_scale=15))
        edge = pcx + half - 0.4
        if li == 0:                        # the current enters at L1's outer end ...
            ax.annotate("", xy=tuple(pts[0]), xytext=(edge, pts[0][1]), zorder=7,
                        arrowprops=dict(arrowstyle="-|>", color="white", lw=1.6, mutation_scale=13))
        if li == len(layers) - 1:          # ... and leaves at the last layer's outer end
            ax.annotate("", xy=(edge, pts[-1][1]), xytext=tuple(pts[-1]), zorder=7,
                        arrowprops=dict(arrowstyle="-|>", color="white", lw=1.6, mutation_scale=13))
        end = " · in" if li == 0 else (" · out" if li == len(layers) - 1 else "")
        ax.text(pcx - half + 0.45, pcy + half - 0.4, f"L{li + 1}{end}", fontsize=fs_mm(0.85), color=silk, va="top",
                zorder=8)
    ax.text(lx, -3.4, "Mirrored spirals in series, joined by vias (gold). The\narrows follow the current: it turns "
            "the same way on\nevery layer, so the layers' fields add.", fontsize=fs_mm(0.9), color=GREY, va="top",
            linespacing=1.3)
    ax.text(-25.0, -3.0, "Label: turns · trace · layers (trace = space). Generated by coils.py (spiral, coil_layers, "
            "doe_layout); the parameters are an illustrative spread around a\nstock MX footprint, not checked against "
            "JLC's rules or the converter's range. Rows A to C fit between the MX centre post and its pins; row D is "
            "larger,\nfor the slug-stem sites, whose footprint is not designed. Leads leave to +x; the routing to the "
            "converters is not drawn. Nothing measured.", fontsize=fs_mm(0.95), color=GREY, va="top",
            linespacing=1.35)
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
