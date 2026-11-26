#!/usr/bin/env python3
"""Concept renders of the rev B keyboard: the split keywell of the roadmap, from keyboard_models.py.

Writes (all in keyboard/hardware/concept/):
    renders/keyboard_assembly.png          both halves, 3/4 front view
    renders/keyboard_top.png               top view with short labels (shear keys, wheel, USB-C A/B, LRA)
    renders/keyboard_side.png              front elevation (tent); cuts in the middle and pinky columns (keywell arcs)
    renders/keyboard_half_exploded.png     left half, exploded along its tent normal
    renders/keyboard_internals.png         left half with the top shell, keycaps and switches removed
    renders/keyboard_fit_presets.png       S, M and L presets of the left half, top view, same scale
    renders/keyboard_keycap_clearance.png  the keycap-clearance gate on the thumb arc, and the tightest spot found
    models/keyboard_assembly.glb           both halves, every part
    models/keyboard_half_exploded.glb      the exploded left half

Run from the repo root (about 70 s; pass figure names, e.g. `top gate glb`, to redo only those):

    PY=/path/to/venv/bin/python          # build123d 0.13, matplotlib, numpy, PIL
    $PY keyboard/hardware/concept/render_keyboard.py

Status: CONCEPT SKETCH. Nothing in keyboard/ is designed, built or measured (keyboard/docs/concept.md). The geometry
is illustrative and parametric (keyboard_models.py), the parts are the candidates named in concept.md, and every
image carries the render_lib concept stamp. Clearances in the gate figure are computed on this sketch geometry; they
say nothing about a real board.
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import matplotlib                                                  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt                                    # noqa: E402
import numpy as np                                                 # noqa: E402
from build123d import Box, Plane, Pos, Vector, section             # noqa: E402
from matplotlib.collections import PolyCollection                  # noqa: E402
from matplotlib.patches import PathPatch                           # noqa: E402
from matplotlib.path import Path                                   # noqa: E402

import keyboard_models as KM                                       # noqa: E402
import render_lib as RL                                            # noqa: E402

OUT = os.path.join(HERE, "renders")
MODELS = os.path.join(HERE, "models")
MAX_PNG = 440_000
INK = (0.12, 0.12, 0.12)
HL = tuple(RL.COLOURS["highlight"])
WBOX = dict(boxstyle="round,pad=0.25", fc="white", ec=(0.65, 0.65, 0.65), lw=0.6)


# ---------------------------------------------------------------------------------------------------------------
# A 2D orthographic painter (render_lib's mesh and shading, drawn on a flat matplotlib axes so labels and
# dimension lines can be placed in millimetres)
# ---------------------------------------------------------------------------------------------------------------
def camera(elev=None, azim=None, eye=None, up_hint=(0, 0, 1)):
    """right, up, eye unit vectors. eye points from the scene toward the viewer (matplotlib's elev/azim)."""
    if eye is None:
        e, a = np.radians(elev), np.radians(azim)
        eye = np.array([np.cos(e) * np.cos(a), np.cos(e) * np.sin(a), np.sin(e)])
        right = np.array([-np.sin(a), np.cos(a), 0.0])
    else:
        eye = np.asarray(eye, float) / np.linalg.norm(eye)
        right = np.cross(up_hint, eye)
        right /= np.linalg.norm(right)
    up = np.cross(eye, right)
    return right, up, eye


def project(cam, p):
    p = np.atleast_2d(np.asarray(p, float))
    return np.stack([p @ cam[0], p @ cam[1]], -1)


def paint(ax, items, cam, max_edge=3.0, tol=0.15, alpha=1.0):
    tris, cols = [], []
    for _n, s, c in items:
        v, t = RL.mesh(s, tol)
        if len(t) == 0:
            continue
        tri = RL.subdivide(v[t], max_edge)
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
        shade = 0.35 + 0.65 * np.abs(n @ RL.LIGHT)
        tris.append(tri)
        cols.append(np.clip(RL.colour(c)[None, :] * shade[:, None], 0, 1))
    tri, col = np.concatenate(tris), np.concatenate(cols)
    order = np.argsort(tri.mean(1) @ cam[2])                  # far first
    tri, col = tri[order], col[order]
    p2 = np.stack([tri @ cam[0], tri @ cam[1]], -1)
    ax.add_collection(PolyCollection(p2, facecolors=col, edgecolors=col, linewidths=0.6, alpha=alpha))
    lo, hi = p2.reshape(-1, 2).min(0), p2.reshape(-1, 2).max(0)
    return lo, hi


def outline(ax, solid, cam, **kw):
    """Dashed silhouette (convex hull of the projected mesh) of a hidden part."""
    v, _t = RL.mesh(solid, 0.3)
    h = KM.hull2d(project(cam, v))
    h = np.vstack([h, h[:1]])
    ax.plot(h[:, 0], h[:, 1], **({"ls": "--", "lw": 1.0, "color": HL} | kw))
    return h


def callout(ax, xy, text, xytext, ha="left", va="center", color=INK, fs=9):
    ax.annotate(text, xy=xy, xytext=xytext, ha=ha, va=va, fontsize=fs, color=color, zorder=20,
                bbox=dict(boxstyle="round,pad=0.25", fc="white", ec=(0.65, 0.65, 0.65), lw=0.6),
                arrowprops=dict(arrowstyle="-", lw=0.7, color=(0.25, 0.25, 0.25), shrinkA=0, shrinkB=1))


def stacked(ax, rows, x, gap=14.0, ha="left", fs=9):
    """Callouts in one column at x, kept gap mm apart, in the order of their anchors' heights.
    rows = [(anchor_xy, text, colour)]."""
    rows = sorted(rows, key=lambda r: -r[0][1])
    ys = [r[0][1] for r in rows]
    for i in range(1, len(ys)):
        ys[i] = min(ys[i], ys[i - 1] - gap)
    for (p, t, c), y in zip(rows, ys):
        callout(ax, p, t, (x, y), ha=ha, color=c, fs=fs)


def frame(ax, lo, hi, pad=6.0):
    ax.set_xlim(lo[0] - pad, hi[0] + pad)
    ax.set_ylim(lo[1] - pad, hi[1] + pad)
    ax.set_aspect("equal")
    ax.set_axis_off()


def save(fig, name, title):
    path = os.path.join(OUT, name)
    os.makedirs(OUT, exist_ok=True)
    if len(fig.axes) == 1:                       # one drawing: let it fill the canvas
        fig.subplots_adjust(0.005, 0.005, 0.995, 0.995)
    fig.savefig(path, facecolor="white", bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)
    finish(path, title)


def finish(path, title):
    """render_lib's crop, title and concept stamp; then keep the PNG small."""
    RL.autocrop(path, title=title)
    shrink(path)
    print(os.path.relpath(path, HERE), f"{os.path.getsize(path) / 1000:.0f} kB")


def shrink(path):
    from PIL import Image
    if os.path.getsize(path) <= MAX_PNG:
        return
    im = Image.open(path).convert("RGB")
    im.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(path, optimize=True)
    if os.path.getsize(path) > MAX_PNG:
        w, h = im.size
        f = (MAX_PNG / os.path.getsize(path)) ** 0.5
        im = im.resize((int(w * f), int(h * f)), Image.LANCZOS)
        im.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(path, optimize=True)


def section2d(ax, items, plane, fill=True, lw=0.5, ls="-", ec="k", alpha=1.0, z=1):
    """Exact cut of each solid by `plane`, drawn in the plane's own (x, y) coordinates."""
    for _n, s, c in items:
        try:
            sec = section(s, plane)
        except Exception:      # noqa: BLE001
            continue
        for f in sec.faces():
            verts, codes = [], []
            for w in f.wires():
                pts = []
                for e in w.edges():
                    n = 2 if e.geom_type.name == "LINE" else 24
                    for t in np.linspace(0, 1, n):
                        q = plane.to_local_coords(e.position_at(t))
                        pts.append((q.X, q.Y))
                if len(pts) < 3:
                    continue
                verts += pts + [pts[0]]
                codes += [Path.MOVETO] + [Path.LINETO] * (len(pts) - 1) + [Path.CLOSEPOLY]
            if verts:
                ax.add_patch(PathPatch(Path(verts, codes), facecolor=RL.colour(c) if fill else "none",
                                       edgecolor=ec, lw=lw, ls=ls, alpha=alpha, zorder=z))


# ---------------------------------------------------------------------------------------------------------------
# Build once
# ---------------------------------------------------------------------------------------------------------------
def tf(m, p):
    return KM.pt(m, *p)


def build():
    t0 = time.time()
    hl, hr = KM.build_half("L", "M"), KM.build_half("R", "M")
    print(f"built M halves in {time.time() - t0:.0f} s")
    return hl, hr


VISIBLE = ("cap", "switch", "case", "floor", "wheel")
HIDDEN_NAMES = ("switch base", "gimbal motor", "encoder", "wheel bracket", "wheel shaft")


def visible(h):
    """What can be seen from outside: skip parts hidden inside the case (keeps the painter fast)."""
    return [(n, s, c) for n, s, c, g in h.parts if g in VISIBLE and not n.startswith(HIDDEN_NAMES)]


# ---------------------------------------------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------------------------------------------
def fig_assembly(hl, hr, ml, mr):
    """render_lib.view() fits a square-ish 3D box at a fixed zoom, which leaves this wide two-half view small, so it
    is drawn with the same tessellation and shading on the flat painter instead."""
    items = KM.moved(visible(hl), ml) + KM.moved(visible(hr), mr)
    fig, ax = plt.subplots(figsize=(16, 8.4), dpi=125)
    lo, hi = paint(ax, items, camera(38, -74), max_edge=3.0)
    frame(ax, lo, hi, pad=4)
    save(fig, "keyboard_assembly.png", "Rev B keyboard concept: split keywell, 3/4 front view (M preset)")


def fig_top(hl, hr, ml, mr):
    cam = camera(90, -90)
    fig, ax = plt.subplots(figsize=(15, 8.2), dpi=120)
    lo, hi = paint(ax, KM.moved(visible(hl), ml) + KM.moved(visible(hr), mr), cam, max_edge=4.0)
    P = lambda m, p: project(cam, tf(m, p))[0]          # noqa: E731

    def keyc(h, m, name):
        return P(m, h.key(name).m[:3, 3] + h.key(name).m[:3, 2] * (KM.CAP_REST + KM.CAP_H))

    callout(ax, keyc(hl, ml, "F"), "F: shear key", keyc(hl, ml, "F") + (-62, 66), ha="center")
    callout(ax, keyc(hr, mr, "J"), "J: shear key", keyc(hr, mr, "J") + (30, 62), ha="center")
    tl, tr = keyc(hl, ml, "T2"), keyc(hr, mr, "T2")
    wn = dict((n, s) for n, s, c, g in hl.parts)
    wc = P(ml, np.array(tuple(wn["wheel tyre"].center())))
    callout(ax, wc, "haptic thumb wheel", wc + (42, 30), ha="left")
    # hidden parts: dashed silhouettes
    for h, m, t, off in ((hl, ml, tl, (-34, -58)), (hr, mr, tr, (34, -58))):
        nm = dict((n, s) for n, s, c, g in h.parts)
        outline(ax, KM.moved([("lra", nm["LRA"], "lra")], m)[0][1], cam)
        callout(ax, t, "thumb shear key\n(dashed circle: the LRA,\ninside, under it)", t + off, ha="center")
    nm = dict((n, s) for n, s, c, g in hl.parts)
    for tag, off in (("A", (-6, 34)), ("B", (40, 22))):
        u = outline(ax, KM.moved([("u", nm[f"USB-C {tag}"], "usb")], ml)[0][1], cam)
        c = u.mean(0)
        callout(ax, c, f"USB-C {tag} (back wall)", c + off, ha="center")
    ax.text(0.5 * (lo[0] + hi[0]), lo[1] - 44, "Dashed: inside the case, seen through it.  Blue: the shear keys "
            "(F, J and one thumb key per half).  Orange: the one haptic wheel (which half: not decided).",
            ha="center", va="top", fontsize=9, color=(0.3, 0.3, 0.3))
    frame(ax, lo - (0, 50), hi + (0, 24), pad=10)
    save(fig, "keyboard_top.png", "Rev B keyboard concept: top view (M preset)")


def fig_side(hl, hr):
    """Top: both halves from the front, untwisted, with the tent angle. Below: cuts in two columns' planes."""
    fig = plt.figure(figsize=(15, 11.5), dpi=115)
    gs = fig.add_gridspec(2, 2, height_ratios=[0.62, 1.45], hspace=0.08, wspace=0.12)
    ax = fig.add_subplot(gs[0, :])
    cam = camera(0, -90)
    gap = 40.0
    ml, mr = KM.T(-gap / 2, 0, 0), KM.T(gap / 2, 0, 0)
    lo, hi = paint(ax, KM.moved(visible(hl), ml) + KM.moved(visible(hr), mr), cam, max_edge=4.0)
    ax.plot([lo[0] - 10, hi[0] + 10], [0, 0], color=(0.35, 0.35, 0.35), lw=1.2)
    ax.text(hi[0] + 8, -2.5, "desk", ha="right", va="top", fontsize=9, color=(0.35, 0.35, 0.35))
    for h, m, sgn in ((hl, ml, -1), (hr, mr, 1)):
        k = h.key("D" if h.side == "L" else "K")           # middle column home key: no row-curvature tilt
        o = KM.pt(m @ k.m)
        xd = (m @ k.m)[:3, 0] * sgn                         # along the row, toward the outer edge
        d = np.array([xd[0], xd[2]]) / np.linalg.norm([xd[0], xd[2]])
        a0 = np.array([o[0], o[2]])
        t1 = -a0[1] / d[1]                                  # where the tile's line meets the desk
        p0, p1 = a0 - d * 70, a0 + d * t1
        ax.plot([p0[0], p1[0]], [p0[1], p1[1]], ls="--", lw=1.1, color=HL)
        ax.plot([p1[0], p1[0] - sgn * 75], [0, 0], ls="-", lw=1.6, color=HL)
        ang = np.degrees(np.arctan2(abs(d[1]), abs(d[0])))
        th = np.radians(np.linspace(0, ang, 30))
        r = 62
        ax.plot(p1[0] - sgn * r * np.cos(th), r * np.sin(th), color=HL, lw=1.1)
        ax.text(p1[0] - sgn * (r + 6), 6, f"tent {ang:.0f}°", ha="right" if sgn > 0 else "left", va="bottom",
                fontsize=11, color=HL, bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.9))
    ax.text(0.5 * (lo[0] + hi[0]), hi[1] + 10, "Front elevation, halves untwisted and pushed together. Dashed: the "
            "plane of the middle column's home key; the inner (thumb) side is up.", ha="center", fontsize=9.5,
            color=(0.3, 0.3, 0.3))
    frame(ax, (lo[0] - 10, -6), (hi[0] + 10, hi[1] + 16), pad=4)
    ax.set_title("Tent: both halves from the front", fontsize=11.5)

    for i, (name, title) in enumerate((("K", "middle finger"), (";", "pinky"))):
        ax2 = fig.add_subplot(gs[1, i])
        k = hr.key(name)
        col = hr.info["cols"][k.col]
        m = k.m
        plane = Plane(origin=tuple(m[:3, 3]), x_dir=tuple(m[:3, 1]), z_dir=tuple(m[:3, 0]))
        items = [(n, s, c) for n, s, c, g in hr.parts if g in ("cap", "switch", "case", "floor", "board", "main",
                                                               "battery", "link")]
        section2d(ax2, items, plane, lw=0.4)
        # the desk where it crosses this (tilted) plane
        xd, yd = np.array(m[:3, 1]), np.array(m[:3, 2])
        desk = [(u, -(m[2, 3] + u * xd[2]) / yd[2]) for u in (-80.0, 80.0)]
        ax2.plot(*zip(*desk), color=(0.35, 0.35, 0.35), lw=1.2)
        dz = min(v for _u, v in desk)
        r = col["r"]
        th = np.radians(np.linspace(-col["alpha"] * 1.7, col["alpha"] * 1.7, 60))
        ax2.plot(r * np.sin(th), r - r * np.cos(th), ls="--", lw=1.0, color=HL)
        for row in (-1, 0, 1):
            a = np.radians(row * col["alpha"])
            ax2.plot([0, r * np.sin(a)], [r, r - r * np.cos(a)], ls=":", lw=0.8, color=HL)
        ax2.plot([0], [r], marker="+", ms=11, mew=1.5, color=HL)
        ax2.text(3, r + 1.5, f"flexion centre (sketch)\nR = {r:.0f} mm at the plate, {col['alpha']:.1f}° per row",
                 fontsize=8.5, color=HL, va="bottom")
        ka = np.radians(col["alpha"])
        cap_pt = (r * np.sin(ka) + 2.0, r - r * np.cos(ka) + 12.0)
        ax2.annotate("keycaps (rest)", xy=cap_pt, xytext=(cap_pt[0] + 14, cap_pt[1] + 16), fontsize=8.5,
                     arrowprops=dict(arrowstyle="-", lw=0.6))
        ax2.annotate("plate: top shell", xy=(r * np.sin(ka) + 11, r - r * np.cos(ka) + 2.0),
                     xytext=(cap_pt[0] + 14, cap_pt[1] - 2), fontsize=8.5, arrowprops=dict(arrowstyle="-", lw=0.6))
        bb = (r + KM.SW_BOT_H + 0.4)
        bp = (-bb * np.sin(ka * 0.6), r - bb * np.cos(ka * 0.6))
        ax2.annotate("column board: 0.8 mm,\nbent to the column's arc", xy=bp, xytext=(-66, bp[1] + 22),
                     fontsize=8.5, arrowprops=dict(arrowstyle="-", lw=0.6))
        ax2.text(-66, dz + 2.5, "desk", fontsize=8, color=(0.3, 0.3, 0.3))
        if name == "K":
            ax2.annotate("main board and MCU module", xy=(-8, dz + 7.0), xytext=(-62, dz + 13), fontsize=8.5,
                         arrowprops=dict(arrowstyle="-", lw=0.6))
        else:
            ax2.annotate("battery", xy=(-8, dz + 6.0), xytext=(-55, dz + 13), fontsize=8.5,
                         arrowprops=dict(arrowstyle="-", lw=0.6))
            ax2.text(-66, r - 6, "The pinky column is splayed, so this\nplane is not square to the desk.",
                     ha="left", va="top", fontsize=8.5, color=(0.3, 0.3, 0.3))
        ax2.set_xlim(-68, 62)
        ax2.set_ylim(dz - 4, r + 16)
        ax2.set_aspect("equal")
        ax2.set_xlabel("along the column (mm, + away from the typist)", fontsize=8.5)
        ax2.set_ylabel("along the home key's axis (mm)", fontsize=8.5)
        ax2.tick_params(labelsize=7.5)
        ax2.grid(True, lw=0.3, alpha=0.5)
        ax2.set_title(f"Keywell arc: cut in the {title} column's plane (right half)", fontsize=11)
    save(fig, "keyboard_side.png", "Rev B keyboard concept: tent and keywell curvature (M preset)")


def layer_labels(ax, cam, items_by_group, labels, x_text, side="right"):
    """One label per exploded layer, in a column beside the drawing, with a leader to the layer."""
    rows = []
    for g, text in labels:
        pts = []
        for _n, s, _c in items_by_group.get(g, []):
            v, _t = RL.mesh(s, 0.5)
            pts.append(project(cam, v))
        if not pts:
            continue
        p = np.concatenate(pts)
        yc = np.median(p[:, 1])
        near = p[np.abs(p[:, 1] - yc) < 4.0]
        if len(near) == 0:
            near = p
        anchor = near[np.argmax(near[:, 0])] if side == "right" else near[np.argmin(near[:, 0])]
        rows.append([anchor, yc, text])
    rows.sort(key=lambda r: -r[1])
    ys = [r[1] for r in rows]
    for i in range(1, len(ys)):                       # keep the text rows at least 13 mm apart
        ys[i] = min(ys[i], ys[i - 1] - 13.0)
    for (anchor, _yc, text), y in zip(rows, ys):
        callout(ax, anchor, text, (x_text, y), ha="left" if side == "right" else "right", fs=9)


def fig_exploded(hl):
    cam = camera(30, -112)
    fig, ax = plt.subplots(figsize=(15, 15), dpi=120)
    ex = []
    up = hl.info["up"]
    groups = {}
    for n, s, c, g in hl.parts:
        if n.startswith("standoff"):
            g = "main"
        sm = Pos(*(KM.EXPLODE.get(g, 0.0) * up)) * s
        ex.append((n, sm, c))
        groups.setdefault(g, []).append((n, sm, c))
    lo, hi = paint(ax, ex, cam, max_edge=3.5)
    labels = [("cap", "keycaps (blue: the shear keys F and the thumb home key)"),
              ("switch", "Hall-effect switches, socketless\n(teal: custom centring-stem switches under the shear "
                         "keys)"),
              ("case", "top shell: plate and walls (printed)"),
              ("board", "column boards (0.8 mm, bent to each arc) and a flat thumb board,\njoined by flex links"),
              ("wheel", "haptic wheel: roller, gimbal motor, MT6701CT encoder"),
              ("main", "main board: MCU module (chip not chosen), USB-C A and B,\nhost-B controller and isolator "
                       "(two-host KVM)"),
              ("battery", "LiPo battery (size not chosen) and coin LRA"),
              ("floor", "floor")]
    layer_labels(ax, cam, groups, labels, hi[0] + 20)
    frame(ax, lo, (hi[0] + 300, hi[1]), pad=6)
    save(fig, "keyboard_half_exploded.png", "Rev B keyboard concept: left half, exploded along the tent normal")


def fig_internals(hl):
    cam = camera(30, -36)
    fig, ax = plt.subplots(figsize=(16, 10), dpi=125)
    keep = ("floor", "board", "link", "main", "battery", "lra", "wheel")
    items = [(n, s, c) for n, s, c, g in hl.parts if g in keep]
    lo, hi = paint(ax, items, cam, max_edge=3.0)
    nm = dict((n, s) for n, s, c, g in hl.parts)
    P = lambda p: project(cam, p)[0]                     # noqa: E731

    def at(name, frac=(0.5, 0.5, 1.0)):
        b = nm[name].bounding_box()
        return P((b.min.X + frac[0] * b.size.X, b.min.Y + frac[1] * b.size.Y, b.min.Z + frac[2] * b.size.Z))
    rows = [("column board 4", (0.5, 0.5, 1.0), "column boards: one per column,\n0.8 mm, bent to the column's arc"),
            ("column board 0", (0.5, 0.5, 1.0), "inner index column's board"),
            ("battery", (0.3, 0.3, 1.0), "LiPo battery (size not chosen)"),
            ("link column 4", (0.5, 0.5, 0.5), "flex links from each column board\nto the main board"),
            ("LRA", (0.5, 0.5, 1.0), "coin LRA on the floor,\nunder the thumb home key"),
            ("USB-C B", (0.5, 1.0, 1.0), "USB-C A and B at the back wall\n(two-host KVM)"),
            ("MCU module", (0.5, 0.5, 1.0), "main board: MCU module\n(chip not chosen)"),
            ("digital isolator", (0.5, 0.5, 1.0), "host-B controller and isolator"),
            ("thumb board", (0.7, 0.5, 1.0), "thumb board (flat)"),
            ("wheel tyre", (0.5, 0.5, 1.0), "haptic wheel: roller, gimbal motor,\nMT6701CT encoder")]
    mid = 0.5 * (lo[0] + hi[0])
    pts = [(at(n, f), t, INK) for n, f, t in rows]
    stacked(ax, [r for r in pts if r[0][0] < mid], lo[0] - 14, gap=17.0, ha="right")
    stacked(ax, [r for r in pts if r[0][0] >= mid], hi[0] + 14, gap=17.0, ha="left")
    ax.text(mid, lo[1] - 12, "Top shell, keycaps and switches removed; seen from the front, inner (thumb) side. Hall "
            "sensors and passives are not modelled.", ha="center", va="top", fontsize=9.5, color=(0.3, 0.3, 0.3))
    frame(ax, (lo[0] - 112, lo[1] - 20), (hi[0] + 116, hi[1] + 4), pad=2)
    save(fig, "keyboard_internals.png", "Rev B keyboard concept: left half without its top shell")


def fig_fit(hm):
    halves = {"S": KM.build_half("L", "S"), "M": hm, "L": KM.build_half("L", "L")}
    cam = camera(90, -90)
    fig, ax = plt.subplots(figsize=(16, 6.4), dpi=120)
    ref = {p: h.key("F").m[:3, 3] for p, h in halves.items()}
    foot_m = None
    xs, step = 0.0, 232.0
    spans = {}
    glo, ghi = np.array([1e9, 1e9]), np.array([-1e9, -1e9])
    for p, h in halves.items():
        f = ref[p]
        m = KM.T(xs - f[0], -f[1], 0)
        items = KM.moved(visible(h), m)
        lo, hi = paint(ax, items, cam, max_edge=4.5)
        glo, ghi = np.minimum(glo, lo), np.maximum(ghi, hi)
        cx = 0.5 * (lo[0] + hi[0])
        b = h.parts[[n for n, *_ in h.parts].index("case floor")][1].bounding_box()
        spans[p] = (b.size.X, b.size.Y, max(s.bounding_box().max.Z for n, s, c, g in h.parts if g == "cap"))
        if p == "M":
            foot_m = [np.array([(e.position_at(t).X, e.position_at(t).Y) for e in fc.outer_wire().edges()
                                for t in np.linspace(0, 1, 6)]) + (-f[0], -f[1]) for fc in h.info["footprint"].faces()]
        cols = h.info["cols"]
        ax.text(cx, -118, f"{p}: scale {KM.PRESETS[p]:.2f}", ha="center", fontsize=12, weight="bold")
        ax.text(cx, -129, f"{spans[p][0]:.0f} × {spans[p][1]:.0f} mm, keycaps up to {spans[p][2]:.0f} mm",
                ha="center", fontsize=9.5, color=(0.25, 0.25, 0.25))
        ax.text(cx, -139, f"middle R {cols[2]['r']:.0f}, pinky R {cols[4]['r']:.0f}, thumb arc R "
                f"{h.info['thumb']['radius']:.0f} mm", ha="center", fontsize=9, color=(0.25, 0.25, 0.25))
        ax.plot([xs], [0], marker="+", ms=9, color=HL, zorder=30)
        xs += step
    for p in ("S", "L"):                                      # the M outline over S and L, aligned on F
        x0 = 0.0 if p == "S" else 2 * step
        for q in foot_m:
            qq = np.vstack([q, q[:1]]) + (x0, 0)
            ax.plot(qq[:, 0], qq[:, 1], color=HL, lw=1.1, alpha=0.85, zorder=25)
    xm = 0.5 * (glo[0] + ghi[0])
    ax.text(xm, 62, "+ = the F key, where the three are aligned.  Pink line: the M case outline drawn over S and L.",
            ha="center", fontsize=9.5, color=(0.3, 0.3, 0.3))
    ax.text(xm, -158, "Key pitch stays 19.05 mm; the scale acts on the column radii, stagger and the thumb arc. "
            "Illustrative: the hand-to-layout mapping is not validated (concept.md §4.4).", ha="center",
            fontsize=9.5, color=(0.3, 0.3, 0.3))
    ax.set_xlim(glo[0] - 6, ghi[0] + 6)
    ax.set_ylim(-164, 70)
    ax.set_aspect("equal")
    ax.set_axis_off()
    save(fig, "keyboard_fit_presets.png", "Rev B keyboard concept: fit presets S, M and L (left half, same scale)")


def _states(r):
    st = {0.0: "rest", 2.0: "mid", KM.TRAVEL: "bottom-out"}
    return st[r["da"]] if r["b"] in ("case", "wheel") else f"{st[r['da']]} / {st[r['db']]}"


def _row_text(r):
    st = {0.0: "rest", 2.0: "mid", KM.TRAVEL: "bottom-out"}
    other = r["b"] if r["b"] in ("case", "wheel", "wheel bracket") else f"{r['b']} ({st[r['db']]})"
    return f"{r['a']} ({st[r['da']]}) vs {other}"


def fig_gate(hl):
    t0 = time.time()
    rows = KM.clearance_gate(hl)
    print(f"keycap gate on the left half: {len(rows)} checks in {time.time() - t0:.0f} s; tightest "
          f"{rows[0]['a']} vs {rows[0]['b']} {rows[0]['d']:.2f} mm")
    margin = KM.GATE_MARGIN
    nm = dict((n, s) for n, s, c, g in hl.parts)
    th = hl.info["thumb"]
    thumb = [k for k in hl.keys if k.thumb]
    fig = plt.figure(figsize=(17, 11.8), dpi=110)
    gs = fig.add_gridspec(2, 2, height_ratios=[0.66, 1.0], hspace=0.16, wspace=0.42)

    # ---- (a) thumb arc seen square to the thumb plate: rest-state caps and every gap the gate checked ----
    ax = fig.add_subplot(gs[0, 0])
    n = th["plane"][:3, 2]
    cam = camera(eye=n, up_hint=(0, 1, 0))
    clip = None
    for poly in (hl.info["thumb_band"], hl.info.get("pad")):
        if poly is None:
            continue
        pr = KM.prism_down([np.asarray(q) + (0, 0, 40.0) for q in poly], 120.0)
        clip = pr if clip is None else clip + pr
    shell = nm["case top shell"] & clip
    items = [("shell", shell, "case_light")]
    items += [(f"cap {k.name}", k.cap(), "keycap_accent" if k.shear else "keycap") for k in thumb]
    items += [(x, nm[x], c) for x, c in (("wheel tyre", "keycap_alt"), ("wheel hub", "roller"))]
    lo, hi = paint(ax, items, cam, max_edge=2.5)
    tn = {k.name for k in thumb} | {"wheel"}
    cxy = th["plane"] @ KM.T(*th["centre"], 0)
    cpt = cxy[:3, 3]
    c2d = project(cam, cpt)[0]
    shown = [r for r in rows if r["a"] in tn and (r["b"] in tn or r["b"] == "wheel") and r["d"] < 10.0]
    lab = []
    for r in shown:
        a2, b2 = project(cam, r["pa"])[0], project(cam, r["pb"])[0]
        ax.plot([a2[0], b2[0]], [a2[1], b2[1]], color=HL, lw=2.5, zorder=10)
        lab.append(((a2 + b2) / 2, f"{r['a']} / {r['b']}: {r['d']:.2f} mm ({_states(r)})", INK))
    stacked(ax, lab, lo[0] - 8, gap=11.0, ha="right", fs=8.5)
    for k in thumb:
        c = project(cam, k.m[:3, 3] + k.m[:3, 2] * 14 + k.m[:3, 1] * 3)[0]
        ax.text(c[0], c[1], k.name, ha="center", va="center", fontsize=10, weight="bold",
                color="white" if k.shear else INK, zorder=12)
    frame(ax, (lo[0] - 75, lo[1] - 4), hi, pad=4)
    ax.set_title("(a) Thumb arc, square to the thumb plate: each gap at\nits tightest state (red: the closest points)",
                 fontsize=11)

    # ---- (b) the arc seen from its centre: caps at rest (shaded) and at bottom-out (dashed) ----
    ax = fig.add_subplot(gs[0, 1])
    ctr = np.mean([k.m[:3, 3] for k in thumb], 0)
    out = ctr - cpt
    out -= n * np.dot(out, n)
    out /= np.linalg.norm(out)
    cam = camera(eye=-out, up_hint=n)
    items = [(f"cap {k.name}", k.cap(), "keycap_accent" if k.shear else "keycap") for k in thumb]
    items += [(f"sw {k.name}", nm[f"switch {k.name}"], "tpu" if k.shear else "switch") for k in thumb]
    items += [(f"stem {k.name}", nm[f"stem {k.name}"], "stem") for k in thumb]
    items += [(x, nm[x], c) for x, c in (("wheel tyre", "keycap_alt"), ("wheel hub", "roller"))]
    lo, hi = paint(ax, items, cam, max_edge=2.0)
    for k in thumb:
        outline(ax, k.cap(KM.TRAVEL), cam, color=HL, lw=1.3)
        c = project(cam, k.m[:3, 3] + k.m[:3, 2] * (KM.CAP_REST + KM.CAP_H + 3))[0]
        ax.text(c[0], c[1], k.name, ha="center", va="bottom", fontsize=10, weight="bold", color=INK)
    plate = project(cam, [ctr + np.cross(n, out) * t for t in (-70, 70)])
    pz = project(cam, ctr)[0][1]
    ax.plot([lo[0] - 4, hi[0] + 4], [pz, pz], color=(0.35, 0.35, 0.35), lw=1.5)
    del plate
    ax.text(hi[0] + 4, pz - 1.2, "thumb plate (top shell)", ha="right", va="top", fontsize=8.5,
            color=(0.3, 0.3, 0.3))
    t2 = [k for k in thumb if k.shear][0]
    tw = project(cam, np.array(tuple(nm["wheel tyre"].center())))[0]
    callout(ax, tw, "wheel (axis toward the viewer)", (tw[0] + 30, lo[1] - 8), ha="center", fs=8.5)
    tops = [project(cam, k.m[:3, 3] + k.m[:3, 2] * (KM.CAP_REST + KM.CAP_H))[0] for k in thumb]
    tr = max(tops, key=lambda q: q[0])
    callout(ax, tr, "keycaps at rest (shaded)", (tr[0] - 30, hi[1] + 14), ha="center", fs=9)
    br = max(tops, key=lambda q: q[0]) - (0, KM.TRAVEL)
    callout(ax, br + (4.5, 0), f"bottom-out: {KM.TRAVEL:.1f} mm down, along each key's axis (dashed)",
            (br[0] + 4, hi[1] + 26), ha="center", color=HL, fs=9)
    ax.text(0.5 * (lo[0] + hi[0]), lo[1] - 18, f"Seen from the arc's centre, so the caps' inner corners face you: "
            f"that is where neighbours come closest\n(at rest: {min(r['d'] for r in shown):.2f} mm). On this sketch, "
            "pressing a cap only opens those gaps: each pair is tightest at rest.", ha="center", va="top", fontsize=8.5,
            color=(0.3, 0.3, 0.3))
    frame(ax, (lo[0] - 6, lo[1] - 36), (hi[0] + 8, hi[1] + 32), pad=2)
    ax.set_title("(b) The thumb arc from its centre: each keycap's travel\nfrom rest to bottom-out", fontsize=11)

    # ---- (c) the tightest spot on the half: an exact cut just in front of it ----
    ax = fig.add_subplot(gs[1, 0])
    r0 = rows[0]
    k = hl.key(r0["a"])
    m = k.m
    inv = np.linalg.inv(m)
    pal = KM.pt(inv, *r0["pa"])
    ycut = pal[1] - 2.0
    ex, ey, ez = m[:3, 0], m[:3, 1], m[:3, 2]
    plane = Plane(origin=tuple(KM.pt(m, 0, ycut, 0)), x_dir=tuple(ex), z_dir=tuple(-ey))
    near = [q for q in hl.keys if np.linalg.norm(q.m[:3, 3] - m[:3, 3]) < 26 and q is not k]
    shell = nm["case top shell"]
    items = [("case", shell, "case_light")]
    items += [(f"cap {q.name}", q.cap(), "keycap_accent" if q.shear else "keycap") for q in near]
    items += [(f"sw {q.name}", nm[f"switch {q.name}"], "switch") for q in near + [k]]
    items += [(f"stem {q.name}", nm[f"stem {q.name}"], "stem") for q in near + [k]]
    pressed = k.cap(r0["da"])
    items += [("pressed", pressed, "keycap")]
    section2d(ax, items, plane, lw=0.5)
    section2d(ax, [("rest", k.cap(0.0), "keycap")], plane, fill=False, ls="--", ec=HL, lw=1.3, z=5)
    d2, qa, qb = section(pressed, plane).distance_to_with_closest_points(section(shell, plane))
    qa, qb = plane.to_local_coords(qa), plane.to_local_coords(qb)
    ax.plot([qa.X, qb.X], [qa.Y, qb.Y], color=HL, lw=2.5, zorder=10)
    ax.plot([qa.X, qb.X], [qa.Y, qb.Y], "o", ms=4, color=HL, zorder=11)
    verdict = "below" if r0["d"] < margin else "above"
    ax.annotate(f"{d2:.2f} mm in this cut, 2 mm in front of {k.name}'s back edge;\n{r0['d']:.2f} mm at the back "
                f"corner itself: {verdict} the {margin:.1f} mm margin", xy=((qa.X + qb.X) / 2, (qa.Y + qb.Y) / 2),
                xytext=(-30.5, -10.8), fontsize=9.5, color=HL, va="bottom", zorder=20, bbox=WBOX,
                arrowprops=dict(arrowstyle="-", lw=0.8, color=HL))
    ax.annotate(f"{k.name} pressed to bottom-out", xy=(-3.0, KM.CAP_REST - KM.TRAVEL + 2.0),
                xytext=(-30, 19), fontsize=9, bbox=WBOX, arrowprops=dict(arrowstyle="-", lw=0.6))
    ax.annotate(f"{k.name} at rest (dashed)", xy=(-4.0, KM.CAP_REST + KM.CAP_H - 0.6), xytext=(-30, 23.5),
                fontsize=9, color=HL, bbox=WBOX, arrowprops=dict(arrowstyle="-", lw=0.6, color=HL))
    ax.annotate("web up to the index column,\nwhich sits higher (top shell)", xy=(qb.X + 0.6, qb.Y + 3.0),
                xytext=(qb.X + 5, qb.Y + 15), fontsize=9, bbox=WBOX, arrowprops=dict(arrowstyle="-", lw=0.6))
    ax.set_xlim(-32, 32)
    ax.set_ylim(-12, 27)
    ax.set_aspect("equal")
    ax.grid(True, lw=0.3, alpha=0.5)
    ax.tick_params(labelsize=7.5)
    ax.set_xlabel(f"across the rows at key {k.name} (mm)", fontsize=8.5)
    ax.set_ylabel(f"along {k.name}'s axis, from its plate (mm)", fontsize=8.5)
    ax.set_title(f"(c) The tightest spot the gate found: key {k.name} (middle column, top row),\nwhich sits "
                 "deeper than the index column beside it (exact cut)", fontsize=11)

    # ---- (d) the ranked list ----
    ax = fig.add_subplot(gs[1, 1])
    top = rows[:12][::-1]
    y = np.arange(len(top))
    vals = [r["d"] for r in top]
    cols = [HL if v < margin else (0.62, 0.64, 0.67) for v in vals]
    ax.barh(y, vals, height=0.62, color=cols, edgecolor="white", linewidth=2)
    for yi, r in zip(y, top):
        tag = "  below margin" if r["d"] < margin else ""
        ax.text(r["d"] + 0.03, yi, f"{r['d']:.2f} mm{tag}", va="center", fontsize=8.5, color=INK)
    ax.set_yticks(y)
    ax.set_yticklabels([_row_text(r) for r in top], fontsize=8.5)
    ax.axvline(margin, color=(0.3, 0.3, 0.3), lw=1.0, ls="--")
    ax.text(margin + 0.02, -0.75, f"illustrative margin {margin:.1f} mm", fontsize=8.5,
            color=(0.3, 0.3, 0.3), va="center")
    ax.set_ylim(-1.2, len(top) - 0.5)
    ax.set_xlim(0, max(vals) * 1.45)
    ax.set_xlabel("minimum clearance over rest / mid / bottom-out (mm)", fontsize=9)
    ax.tick_params(axis="x", labelsize=8)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    ax.grid(True, axis="x", lw=0.3, alpha=0.6)
    ax.set_axisbelow(True)
    ax.set_title(f"(d) The 12 tightest of {len(rows)} checks on the left half (keycap vs keycap,\ncase and wheel; "
                 "each cap at rest, mid travel and bottom-out)", fontsize=11)
    fig.text(0.5, 0.035, "Clearances are computed on the sketch geometry (keyboard_models.clearance_gate), not "
             "measured. Against the illustrative margin, a gate like the one concept.md §4.1 plans would flag E here "
             "(and I, its mirror, on the right half);\na design would raise the middle column or reshape the web.",
             ha="center", va="top", fontsize=9.5, color=(0.3, 0.3, 0.3))
    save(fig, "keyboard_keycap_clearance.png", "Rev B keyboard concept: keycap clearance gate (sketch, left half, M)")
    return rows


def export_models(hl, hr, ml, mr):
    os.makedirs(MODELS, exist_ok=True)
    items = KM.moved(hl.items(), ml) + KM.moved(hr.items(), mr)
    RL.export_glb(items, os.path.join(MODELS, "keyboard_assembly.glb"), tol=0.25)
    RL.export_glb(KM.exploded(hl), os.path.join(MODELS, "keyboard_half_exploded.glb"), tol=0.25)
    for f in ("keyboard_assembly.glb", "keyboard_half_exploded.glb"):
        print(f"models/{f} {os.path.getsize(os.path.join(MODELS, f)) / 1e6:.2f} MB")


def main():
    t0 = time.time()
    hl, hr = build()
    ml, mr = KM.place(hl), KM.place(hr)
    which = sys.argv[1:] or ["assembly", "top", "side", "exploded", "internals", "fit", "gate", "glb"]
    if "assembly" in which:
        fig_assembly(hl, hr, ml, mr)
    if "top" in which:
        fig_top(hl, hr, ml, mr)
    if "side" in which:
        fig_side(hl, hr)
    if "exploded" in which:
        fig_exploded(hl)
    if "internals" in which:
        fig_internals(hl)
    if "fit" in which:
        fig_fit(hl)
    if "gate" in which:
        fig_gate(hl)
    if "glb" in which:
        export_models(hl, hr, ml, mr)
    print(f"done in {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
