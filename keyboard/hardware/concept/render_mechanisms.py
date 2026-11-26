"""Concept renders of the keyboard's key and control mechanisms: labelled 3D cutaways and exact sections.

STATUS: concept sketch. Nothing in keyboard/ is designed, built or measured (keyboard/docs/concept.md). The
geometry in mechanism_models.py is illustrative, the parts are the candidates concept.md names, and every image
carries the "CONCEPT SKETCH" stamp from render_lib.

Run from the repo root with a Python that has build123d 0.13, matplotlib, numpy and Pillow:

    python keyboard/hardware/concept/render_mechanisms.py              # everything (a minute or two)
    python keyboard/hardware/concept/render_mechanisms.py he coil      # some: he shear wheel coil lra glb

Writes keyboard/hardware/concept/renders/mech_*.png and models/mech_shear_key.glb, models/mech_thumb_wheel.glb.

3D views are flat-shaded triangle meshes (render_lib); labels sit in columns beside the picture with leader lines
to their parts. Sections cut each solid with a plane and fill the faces, so they are exact for the model (which is
itself only a sketch).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import matplotlib                                                  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt                                    # noqa: E402
import numpy as np                                                 # noqa: E402
from matplotlib.lines import Line2D                                # noqa: E402
from matplotlib.patches import PathPatch                           # noqa: E402
from matplotlib.transforms import IdentityTransform                # noqa: E402
from mpl_toolkits.mplot3d import proj3d                            # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection           # noqa: E402

from build123d import Plane, section                               # noqa: E402

import mechanism_models as M                                       # noqa: E402
import render_lib as R                                             # noqa: E402

OUT = os.path.join(HERE, "renders")
MODELS = os.path.join(HERE, "models")
DPI = 130
HI = R.colour("highlight")
INK = (0.15, 0.15, 0.15)
LEAD = (0.35, 0.35, 0.38)
BOX = dict(boxstyle="round,pad=0.25", fc="white", ec=(0.70, 0.70, 0.72), lw=0.6)
MAX_PNG = 440_000
F = 10            # label font (pt): 18 px at 130 dpi, about 8 px at the docs column width for a 1500 px image


# ---------------------------------------------------------------------------
# Shared drawing helpers (built on render_lib's mesh / subdivide / colour)
# ---------------------------------------------------------------------------
def draw_group(ax, items, tol, max_edge, zorder):
    """One depth-sorted Poly3DCollection per group, so a group can be forced in front of another
    (thin copper on a board defeats a painter's sort otherwise)."""
    polys, cols = [], []
    for _name, s, c in items:
        v, t = R.mesh(s, tol)
        if len(t) == 0:
            continue
        tri = R.subdivide(v[t], max_edge)
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
        shade = 0.35 + 0.65 * np.abs(n @ R.LIGHT)
        polys.append(tri)
        cols.append(np.clip(R.colour(c)[None, :] * shade[:, None], 0, 1))
    tri = np.concatenate(polys)
    col = np.concatenate(cols)
    ax.add_collection3d(Poly3DCollection(tri, facecolors=col, edgecolors=col, linewidths=0.25, zorder=zorder))
    pts = tri.reshape(-1, 3)
    return pts.min(0), pts.max(0), pts


def spread(want, heights, lo, hi, pad=4.0):
    """Move label centres (px) apart so no two overlap, staying near where they want to be."""
    want = np.asarray(want, float)
    h = np.asarray(heights, float)
    order = np.argsort(-want)
    y = want.copy()
    for k in range(1, len(order)):
        i, j = order[k], order[k - 1]
        y[i] = min(y[i], y[j] - (h[i] + h[j]) / 2 - pad)
    if len(order):
        y[order[-1]] = max(y[order[-1]], lo + h[order[-1]] / 2)
    for k in range(len(order) - 2, -1, -1):
        i, j = order[k], order[k + 1]
        y[i] = max(y[i], y[j] + (h[i] + h[j]) / 2 + pad)
    if len(order) and y[order[0]] + h[order[0]] / 2 > hi:
        y -= y[order[0]] + h[order[0]] / 2 - hi
    return y


def callouts(fig, ax, anchors_px, labels, x_left, x_right, font, ylo, yhi, to_data):
    """Labels in a left and a right column, leader lines to their anchors. anchors_px: display coords;
    labels: (text, side) with side 'L' or 'R'; to_data maps display px -> the axes' data coords for annotate."""
    line_px = font * DPI / 72 * 1.25
    for side in ("L", "R"):
        idx = [i for i, (_t, s) in enumerate(labels) if s == side]
        if not idx:
            continue
        hs = [line_px * (labels[i][0].count("\n") + 1) + 8 for i in idx]
        ys = spread([anchors_px[i][1] for i in idx], hs, ylo, yhi)
        for i, y in zip(idx, ys):
            text = labels[i][0]
            ax_, ay_ = anchors_px[i]
            tx = x_left if side == "L" else x_right
            ax.annotate(text, xy=to_data((ax_, ay_)), xycoords="data", xytext=to_data((tx, y)), textcoords="data",
                        ha="right" if side == "L" else "left", va="center", fontsize=font, color=INK, bbox=BOX,
                        zorder=50, annotation_clip=False,
                        arrowprops=dict(arrowstyle="-", color=LEAD, lw=0.7, shrinkA=0, shrinkB=0,
                                        relpos=(1.0, 0.5) if side == "L" else (0.0, 0.5)))
            fig.add_artist(Line2D([ax_], [ay_], marker="o", ms=3.2, color=LEAD, mec="white", mew=0.6,
                                  transform=IdentityTransform(), zorder=60))


def view3d(path, groups, elev, azim, labels=(), tags=(), size=(11, 7.5), zoom=0.72, tol=0.05, max_edge=1.0,
           font=F, gap=36, roll=0, finish=True, title=None):
    """Shaded orthographic view with callout columns.
    groups: list of item lists, drawn back to front in that order (each depth-sorted inside).
    labels: (text, (x, y, z), 'L' | 'R');  tags: (text, (x, y, z), dx_px, dy_px) placed next to a point."""
    fig = plt.figure(figsize=size, dpi=DPI)
    ax = fig.add_axes([0, 0, 1, 1], projection="3d", proj_type="ortho")
    ax.view_init(elev=elev, azim=azim, roll=roll)
    ax.computed_zorder = False
    los, his, pts = [], [], []
    for z, items in enumerate(groups):
        lo, hi, p = draw_group(ax, items, tol, max_edge, zorder=z + 1)
        los.append(lo)
        his.append(hi)
        pts.append(p[:: max(1, len(p) // 30000)])
    lo, hi = np.min(los, 0), np.max(his, 0)
    ax.set_xlim(lo[0], hi[0])
    ax.set_ylim(lo[1], hi[1])
    ax.set_zlim(lo[2], hi[2])
    ax.set_box_aspect(tuple(np.maximum(hi - lo, 1e-3)), zoom=zoom)
    ax.set_axis_off()
    fig.canvas.draw()
    proj = ax.get_proj()

    def to_px(p):
        x2, y2, _ = proj3d.proj_transform(np.atleast_1d(p[0]), np.atleast_1d(p[1]), np.atleast_1d(p[2]), proj)
        return ax.transData.transform(np.column_stack([x2, y2]))

    def to_data(px):
        return tuple(ax.transData.inverted().transform(px))

    allp = np.concatenate(pts)
    disp = to_px(allp.T)
    bx0, by0 = disp.min(0)
    bx1, by1 = disp.max(0)
    H = fig.bbox.height
    anchors = [to_px(p)[0] for _t, p, _s in labels]
    callouts(fig, ax, anchors, [(t, s) for t, _p, s in labels], bx0 - gap, bx1 + gap, font,
             max(by0 - 40, 10), min(by1 + 40, H - 10), to_data)
    for text, p, dx, dy in tags:
        x, y = to_px(p)[0]
        ax.annotate(text, xy=to_data((x + dx, y + dy)), xycoords="data", ha="center", va="center",
                    fontsize=font + 1, color=HI * 0.75, fontweight="bold", zorder=55, annotation_clip=False)
    save(fig, path, title, finish)


def save(fig, path, title=None, finish=True):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fig.savefig(path, dpi=DPI, facecolor="white")
    plt.close(fig)
    if finish:
        R.autocrop(path, title=title)
        shrink(path)
        print(os.path.relpath(path, os.getcwd()), os.path.getsize(path) // 1024, "KB")
    else:
        crop(path)


def crop(path, margin=12):
    """Trim the white border (no title or stamp: for panels of a composite)."""
    from PIL import Image
    im = Image.open(path).convert("RGB")
    a = np.asarray(im)
    ink = np.where((a < 245).any(axis=2))
    y0, y1 = max(ink[0].min() - margin, 0), min(ink[0].max() + margin, a.shape[0])
    x0, x1 = max(ink[1].min() - margin, 0), min(ink[1].max() + margin, a.shape[1])
    im.crop((x0, y0, x1, y1)).save(path)


def shrink(path, limit=MAX_PNG):
    """Keep a PNG under the size budget: palette-quantise it if it is too big."""
    from PIL import Image
    if os.path.getsize(path) <= limit:
        return
    im = Image.open(path).convert("RGB")
    im.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(path, optimize=True)


def compose(path, panels, title, captions=(), gap=40):
    """Stack cropped panel PNGs top to bottom (centred), each with a caption above it and a thin rule between
    them, then title + stamp (render_lib). Stacked, not side by side, so the composite stays about 1400-1500 px
    wide and its callouts can still be read at the docs column width (~688 px)."""
    from PIL import Image, ImageDraw
    ims = [Image.open(p).convert("RGB") for p in panels]
    w = max(i.width for i in ims)
    cap_px = max(17, round(w * 9 / 688))          # about 9 px at the docs column width
    ft = R._font(cap_px)
    cap_h = int(cap_px * 1.9) if captions else 0
    h = sum(i.height for i in ims) + cap_h * len(ims) + gap * (len(ims) - 1)
    out = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(out)
    y = 0
    for k, im in enumerate(ims):
        if k:
            yl = y - gap // 2
            d.line([(int(w * 0.03), yl), (int(w * 0.97), yl)], fill=(210, 210, 214), width=2)
        if captions:
            d.text((w // 2, y + 2), captions[k], fill=(60, 60, 60), font=ft, anchor="mt")
        out.paste(im, ((w - im.width) // 2, y + cap_h))
        y += cap_h + im.height + gap
    out.save(path)
    for p in panels:
        os.remove(p)
    R.autocrop(path, title=title)
    shrink(path)
    print(os.path.relpath(path, os.getcwd()), os.path.getsize(path) // 1024, "KB", Image.open(path).size)


def px_rect(fig, x0, y0, w, h):
    """A figure-fraction rect from pixels (measured from the figure's bottom left)."""
    W, H = fig.bbox.width, fig.bbox.height
    return [x0 / W, y0 / H, w / W, h / H]


def px_axes(fig, x0, y0, w, h, **kw):
    """An axes placed in pixels rather than figure fractions."""
    return fig.add_axes(px_rect(fig, x0, y0, w, h), **kw)


# --- 2D sections --------------------------------------------------------------
def face_path(face, axes):
    """matplotlib Path of a planar face in two global axes. Like render_lib.face_paths, but each wire's edges are
    chained end to start (and flipped where needed): a lofted keycap's section otherwise draws as a zig-zag."""
    from matplotlib.path import Path
    verts, codes = [], []
    for w in face.wires():
        segs = []
        for e in w.edges():
            n = 2 if e.geom_type.name == "LINE" else 28
            segs.append([(getattr(q, axes[0]), getattr(q, axes[1])) for q in (e.position_at(t)
                                                                               for t in np.linspace(0, 1, n))])
        if not segs:
            continue
        chain = segs.pop(0)
        if segs:      # orient the first edge towards whichever edge continues it
            d_end = min(min(np.hypot(*np.subtract(chain[-1], s_[0])), np.hypot(*np.subtract(chain[-1], s_[-1])))
                        for s_ in segs)
            d_start = min(min(np.hypot(*np.subtract(chain[0], s_[0])), np.hypot(*np.subtract(chain[0], s_[-1])))
                          for s_ in segs)
            if d_start < d_end:
                chain = chain[::-1]
        while segs:
            end = chain[-1]
            best = min(range(len(segs)), key=lambda k: min(np.hypot(*np.subtract(end, segs[k][0])),
                                                            np.hypot(*np.subtract(end, segs[k][-1]))))
            sg = segs.pop(best)
            if np.hypot(*np.subtract(end, sg[-1])) < np.hypot(*np.subtract(end, sg[0])):
                sg = sg[::-1]
            chain += sg[1:]
        if len(chain) < 3:
            continue
        verts += chain + [chain[0]]
        codes += [Path.MOVETO] + [Path.LINETO] * (len(chain) - 1) + [Path.CLOSEPOLY]
    return Path(verts, codes) if verts else None


def fill_section(ax, items, plane, axes, lw=0.45, alpha=1.0):
    for _name, s, c in items:
        try:
            sec = section(s, plane)
        except Exception:      # noqa: BLE001
            continue
        for f in sec.faces():
            p = face_path(f, axes)
            if p is not None:
                ax.add_patch(PathPatch(p, facecolor=R.colour(c), edgecolor="k", lw=lw, alpha=alpha))


def section_axes(fig, rect, items, plane, axes, xlim, ylim, xlabel=None, ylabel=None, font=F):
    ax = fig.add_axes(rect)
    fill_section(ax, items, plane, axes)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.grid(True, lw=0.3, alpha=0.45, zorder=0)
    ax.set_axisbelow(True)
    ax.tick_params(labelsize=font - 1)
    ax.set_xlabel(xlabel or f"{axes[0].lower()} (mm)", fontsize=font)
    ax.set_ylabel(f"{axes[1].lower()} (mm)" if ylabel is None else ylabel, fontsize=font)
    return ax


def label2d(fig, ax, labels, left_px=52, right_px=14, font=F, ylim=None):
    """labels: (text, (x, y), 'L' | 'R') in data coords. The columns sit left_px left of the axes (clear of the
    tick labels) and right_px right of it; ylim (data) limits the band the labels may use."""
    fig.canvas.draw()
    T = ax.transData
    bb = ax.get_window_extent()
    anchors = [T.transform(p) for _t, p, _s in labels]
    lo, hi = ylim or ax.get_ylim()
    y0 = T.transform((0, lo))[1]
    y1 = T.transform((0, hi))[1]
    callouts(fig, ax, anchors, [(t, s) for t, _p, s in labels], bb.x0 - left_px, bb.x1 + right_px, font,
             y0 + 4, y1 - 4, lambda px: tuple(T.inverted().transform(px)))


def dim(ax, x, y0, y1, text, side="R", font=F, colour=None, axis="v", ext=None, tx=0.5):
    """A dimension arrow between y0 and y1 at x (axis 'v'), or between x0=y0 and x1=y1 at height x ('h').
    tx: how far (mm) the text of a vertical dimension sits from its arrow."""
    c = HI if colour is None else colour
    if axis == "v":
        a, b = (x, y0), (x, y1)
        t = (x + (tx if side == "R" else -tx), (y0 + y1) / 2)
        ha, va = ("left" if side == "R" else "right"), "center"
    else:
        a, b = (y0, x), (y1, x)
        t = ((y0 + y1) / 2, x + (0.4 if side == "R" else -0.4))
        ha, va = "center", ("bottom" if side == "R" else "top")
    ax.annotate("", xy=b, xytext=a, arrowprops=dict(arrowstyle="<|-|>", color=c, lw=1.1, mutation_scale=9,
                                                    shrinkA=0, shrinkB=0), zorder=40)
    if text:
        ax.text(*t, text, ha=ha, va=va, fontsize=font, color=c * 0.8 if hasattr(c, "__mul__") else c, zorder=41,
                fontweight="bold", bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.85))
    for e in (ext or ()):
        ax.plot(*e, color=c, lw=0.6, ls=(0, (3, 2)), zorder=39)


def push(ax, p0, p1, text, font=F, offset=(0, 0), ha="center", va="center"):
    ax.annotate("", xy=p1, xytext=p0, arrowprops=dict(arrowstyle="-|>", color=HI, lw=2.4, mutation_scale=18,
                                                      shrinkA=0, shrinkB=0), zorder=45)
    ax.text(p0[0] + offset[0], p0[1] + offset[1], text, ha=ha, va=va, fontsize=font, color=HI * 0.8,
            fontweight="bold", zorder=46)


def note(fig, text, y_px=14, font=F):
    """An italic grey note centred at the bottom of the figure, y_px above its lower edge."""
    fig.text(0.5, y_px / fig.bbox.height, text, ha="center", va="bottom", fontsize=font, color=(0.35, 0.35, 0.35),
             style="italic", linespacing=1.35)


# ---------------------------------------------------------------------------
# (1) Hall-effect key
# ---------------------------------------------------------------------------
UNCUT = {"spring", "magnet", "TPU stop", "sensor", "sensor leads", "pcb", "TMAG5170", "TMAG5170 leads",
         "spring (steel)"}


def cutaway(items, keep="y+", uncut=UNCUT):
    return [(n, s if n in uncut else M.half(s, keep), c) for n, s, c in items]


def he_cutaway():
    items = cutaway(M.he_key(0.0))
    labels = [
        ("keycap (any MX-stem cap)", (-6.0, 0.0, 16.8), "L"),
        ("stem", (-2.05, 0.0, 14.0), "L"),
        ("top housing", (-6.6, 0.0, 8.0), "L"),
        ("plate", (-10.0, 0.0, 4.6), "L"),
        ("bottom housing", (-6.4, 0.0, 2.5), "L"),
        ("PCB", (-9.0, -6.0, -0.8), "L"),
        ("cylindrical magnet in the stem\n(axially magnetised)", (0.0, -1.95, 8.2), "R"),
        ("spring", (3.0, -0.6, 5.0), "R"),
        ("compliant TPU bottom stop\n(the aftertouch idea)", (2.2, -1.0, 2.5), "R"),
        ("TMAG5253-class Hall sensor\n(SOT-23) on the PCB,\nunder the magnet", (1.2, -0.7, 1.05), "R"),
    ]
    view3d(os.path.join(OUT, "mech_he_key_cutaway.png"), [items], elev=18, azim=-62, labels=labels,
           size=(11, 8), zoom=0.78, max_edge=0.8,
           title="Hall-effect key with a compliant bottom stop: half-section (concept)")


def he_section():
    """Two rows: at rest (top), pressed into the TPU (bottom), with a zoom on the squeeze beside the bottom row."""
    from matplotlib.patches import Rectangle
    rest = M.he_key(0.0)
    press = 4.3
    sq = press - M.TRAVEL
    down = M.he_key(press)
    H = 1420
    fig = plt.figure(figsize=(1440 / DPI, H / DPI), dpi=DPI)
    pl = Plane.XZ
    xl, yl = (-12.5, 15.0), (-1.6, 18.6)
    ppm = 24.0                                      # px per mm in both rows
    aw, ah = (xl[1] - xl[0]) * ppm, (yl[1] - yl[0]) * ppm
    x0 = 400
    a1 = section_axes(fig, px_rect(fig, x0, H - 100 - ah, aw, ah), rest, pl, ("X", "Z"), xl, yl, ylabel="")
    a2 = section_axes(fig, px_rect(fig, x0, 210, aw, ah), down, pl, ("X", "Z"), xl, yl, ylabel="")
    # the z unit goes at the top of each axis, clear of the callouts and the zoom
    # the rest row's callouts sit on the left, so its z ticks go on the right, where nothing else is
    a1.yaxis.tick_right()
    a1.text(xl[1], yl[1] + 0.35, "z (mm)", ha="center", va="bottom", fontsize=F - 1)
    a2.text(xl[0], yl[1] + 0.35, "z (mm)", ha="center", va="bottom", fontsize=F - 1)
    a1.set_title("at rest", fontsize=12, pad=26)
    a2.set_title(f"pressed {press:.1f} mm: 4.0 mm to the stop, then {sq:.1f} mm into the TPU", fontsize=12, pad=26)
    top = M.HE["cap_top"]
    dim(a1, 11.0, top, top - M.TRAVEL, "4.0 mm\ntravel", side="R",
        ext=[((5.0, 11.6), (top, top)), ((8.2, 11.6), (top - M.TRAVEL, top - M.TRAVEL))])
    mz = M.HE["magnet"][2]
    dim(a1, 0.0, 1.1, mz, f"{mz - 1.1:.1f} mm", side="R")
    dim(a2, 0.0, 1.1, mz - press, "", side="R")
    push(a2, (0, top - press + 3.4), (0, top - press + 0.4), "press", offset=(0, 0.8), font=F + 1)
    lab_rest = [
        ("keycap", (-7.4, 15.0), "L"),
        ("stem", (-1.2, 14.6), "L"),
        ("top housing", (-6.8, 8.0), "L"),
        ("magnet", (-1.5, 7.6), "L"),
        ("spring", (-3.0, 4.97), "L"),
        ("plate", (-10.0, 4.3), "L"),
        ("bottom housing", (-6.4, 3.0), "L"),
        ("TPU stop", (-1.9, 2.2), "L"),
        ("Hall sensor (SOT-23)", (-1.0, 0.6), "L"),
        ("PCB", (-8.0, -0.8), "L"),
    ]
    label2d(fig, a1, lab_rest, left_px=26)
    lab_down = [
        ("spring compressed", (3.0, 4.0), "R"),
        (f"magnet-sensor gap {mz - press - 1.1:.1f} mm\n(was {mz - 1.1:.1f} mm at rest): the\n"
         "field keeps rising through\nthe squeeze", (2.0, 3.4), "R"),
        ("stem lands on the\nTPU stop at 4.0 mm", (2.45, M.HE["pole"][1] - press + 0.05), "R"),
        (f"TPU squeezed {sq:.1f} mm (shown)\ninto an illustrative compliant\nzone (the sketch's choice)\n"
         "that would carry aftertouch", (1.4, 2.0), "R"),
    ]
    label2d(fig, a2, lab_down, ylim=(-1.6, 12.5))
    # zoomed inset of the squeeze, left of the pressed row (its labels are on the right), linked by a pink box
    zx, zy = (-3.4, 3.4), (0.9, 3.3)
    a2.add_patch(Rectangle((zx[0], zy[0]), zx[1] - zx[0], zy[1] - zy[0], fill=False, ec=HI, lw=1.1, zorder=35))
    iw = 330.0
    k = iw / (zx[1] - zx[0]) / ppm
    ih = iw * (zy[1] - zy[0]) / (zx[1] - zx[0])
    ins = px_axes(fig, 22, 210 + (2.1 - yl[0]) * ppm - ih / 2 + 40, iw, ih)
    fill_section(ins, down, pl, ("X", "Z"), lw=0.6)
    ins.set_xlim(*zx)
    ins.set_ylim(*zy)
    ins.set_aspect("equal", adjustable="box")
    ins.set_xticks([])
    ins.set_yticks([])
    for sp in ins.spines.values():
        sp.set_edgecolor(HI)
        sp.set_linewidth(1.1)
    tz = M.HE["floor"][1] + M.HE["tpu"][1]
    ins.axhline(tz, color=HI, lw=1.0, ls=(0, (3, 2)))
    ins.text(-3.3, tz + 0.05, "free TPU top", ha="left", va="bottom", fontsize=F - 1, color=HI * 0.8,
             bbox=dict(boxstyle="round,pad=0.1", fc="white", ec="none", alpha=0.85))
    ins.annotate("", xy=(-2.75, tz - sq), xytext=(-2.75, tz), arrowprops=dict(arrowstyle="-|>", color=HI, lw=1.2,
                                                                           mutation_scale=8, shrinkA=0, shrinkB=0))
    ins.set_title(f"zoom ({k:.0f}x) on the pink box:\nthe {sq:.1f} mm squeeze", fontsize=F)
    note(fig, "Concept geometry, not a design: an MX-style 14 mm switch with 4 mm travel. Dimensions in "
         f"mm.\nThe {mz - 1.1:.1f} mm gap runs from the magnet to the top of the sensor package. The stop's "
         "stiffness and the\nfield-versus-squeeze curve are unknowns for the rev A coupon.", y_px=12)
    save(fig, os.path.join(OUT, "mech_he_key_section.png"),
         title="Hall-effect key: exact section through the stem (y = 0)")


# ---------------------------------------------------------------------------
# (2) Shear key
# ---------------------------------------------------------------------------
def shear_cut_items(press=0.0, shift=(0.0, 0.0)):
    out = []
    for n, sol, c in M.shear_key(press, shift):
        if n == "flexure posts":
            sol = M.half(sol, "y+", at=-1.0)      # keep the two posts on the cut plane whole, drop the front one
        elif n not in UNCUT:
            sol = M.half(sol, "y+")
        out.append((n, sol, c))
    return out


def shear_cutaway():
    items = shear_cut_items()
    arrows = [
        ("Z", M.arrow((0, 0, 26.0), (0, 0, 18.6), d=0.9, head=2.6), "highlight"),
        ("X", M.arrow((-19.5, 0, 14.5), (-10.2, 0, 14.5), d=0.9, head=2.6), "highlight"),
        ("Y", M.arrow((21.0, -12.0, 21.0), (21.0, 2.0, 21.0), d=0.9, head=2.6), "highlight"),
    ]
    labels = [
        ("keycap (shear keys get an accent colour)", (-6.2, 0.0, 16.6), "L"),
        ("stem: slides 4 mm inside the carrier", (-1.2, 0.0, 13.3), "L"),
        ("roof hole = hard sideways stop\n(0.4 mm gap all round)", (-4.4, 0.0, 10.9), "L"),
        ("housing (custom, printed or moulded)", (-6.3, 0.0, 7.0), "L"),
        ("plate", (-10.5, 0.0, 4.5), "L"),
        ("PCB", (-9.5, -6.0, -0.8), "L"),
        ("4 flexure posts: hang the carrier from the roof,\nbend in an S so it can shift about \u00b10.3-0.5 mm,\n"
         "stay stiff along their length for the press", (4.9, 0.0, 6.5), "R"),
        ("carrier cup (moves sideways with the stem)", (3.9, 0.0, 9.5), "R"),
        ("spring (inside the carrier)", (2.8, -0.5, 5.0), "R"),
        ("magnet: moves with X, Y and Z", (0.6, -1.9, 8.0), "R"),
        ("TMAG5170 3-axis Hall sensor (VSSOP-8)\nreads Bx, By, Bz under the magnet", (1.4, -1.0, 0.9), "R"),
    ]
    tags = [("Z press", (0, 0, 26.0), 0, 14), ("X push", (-19.5, 0, 14.5), -6, 14),
            ("Y push", (21.0, -12.0, 21.0), 44, -14)]
    view3d(os.path.join(OUT, "mech_shear_key_cutaway.png"), [items, arrows], elev=20, azim=-58, labels=labels,
           tags=tags, size=(12, 8.6), zoom=0.74, max_edge=0.8,
           title="Shear key: a stem guide hung on flexure posts over a 3-axis Hall sensor (concept)")


def shear_section():
    """Two rows: at rest and pushed sideways (top row, side by side), the plan section (bottom row)."""
    lat = M.SH["lateral"]
    rest = M.shear_key(0.0)
    pushed = M.shear_key(0.0, (lat, 0.0))
    W, H = 1500, 1450
    fig = plt.figure(figsize=(W / DPI, H / DPI), dpi=DPI)
    pl = Plane.XZ
    xl, yl = (-12.5, 12.5), (-1.6, 23.4)
    ppm = 19.0
    aw, ah = (xl[1] - xl[0]) * ppm, (yl[1] - yl[0]) * ppm
    y1 = H - 85 - ah
    a1 = section_axes(fig, px_rect(fig, 250, y1, aw, ah), rest, pl, ("X", "Z"), xl, yl, ylabel="")
    a2 = section_axes(fig, px_rect(fig, 250 + aw + 78, y1, aw, ah), pushed, pl, ("X", "Z"), xl, yl, ylabel="")
    # callouts on the outer sides; the shared z scale is read between the two panels, on the pushed one
    a1.tick_params(labelleft=False)
    a2.text(xl[0], yl[1] + 0.4, "z (mm)", ha="center", va="bottom", fontsize=F - 1)
    a1.set_title("at rest (section y = 0)", fontsize=12, pad=26)
    a2.set_title(f"pushed +X to the stop ({lat:.1f} mm, true scale)", fontsize=12, pad=26)
    top = M.SH["cap_top"]
    push(a1, (0, top + 4.6), (0, top + 0.4), "Z press:\ntypes as usual", offset=(0.7, -0.6), ha="left",
         va="top", font=F + 1)
    dim(a1, 10.0, top, top - M.TRAVEL, "4.0 mm", side="R",
        ext=[((5.0, 10.6), (top, top)), ((8.0, 10.6), (top - M.TRAVEL, top - M.TRAVEL))])
    push(a2, (-12.0, 15.0), (-8.9 + lat, 15.0), "X push", offset=(0.1, 1.2), ha="left", font=F + 1)
    lab1 = [
        ("keycap", (-6.6, 15.5), "L"),
        ("stem (slides 4 mm)", (-1.0, 13.0), "L"),
        ("roof hole\n(side stop)", (-4.6, 11.0), "L"),
        ("carrier cup", (-3.7, 9.0), "L"),
        ("magnet", (-1.2, 8.0), "L"),
        ("flexure post\n(1 of 4)", (-4.9, 6.5), "L"),
        ("spring", (-2.8, 5.63), "L"),
        ("housing", (-6.6, 3.5), "L"),
        ("TMAG5170", (-1.0, 0.55), "L"),
        ("PCB", (-8.0, -0.8), "L"),
    ]
    label2d(fig, a1, lab1, left_px=26)
    lab2 = [
        ("gap closed on this\nside: the hard stop", (4.5, 10.9), "R"),
        (f"magnet {lat:.1f} mm off\ncentre: Bx changes\nat the sensor", (0.6 + lat, 8.4), "R"),
        ("posts bend in an S;\nthe carrier shifts\nwithout tilting", (4.9 + lat * 0.5, 6.4), "R"),
    ]
    label2d(fig, a2, lab2, ylim=(2.0, 21.0))
    a2.axvline(0, color=HI, lw=0.8, ls=(0, (4, 3)), zorder=30)
    a2.text(0.25, -1.3, "rest centre", fontsize=F - 1, color=HI * 0.8, ha="left", va="bottom", zorder=31,
            bbox=dict(boxstyle="round,pad=0.1", fc="white", ec="none", alpha=0.85))
    # plan section through the magnet (the spring is drawn as its mean circle: a level cut through a helix
    # gives a misleading crescent)
    zc = 8.0
    plan = [it for it in rest if it[0] != "spring"]
    pw = 21.0 * 27.0
    a3 = section_axes(fig, px_rect(fig, 420, 175, pw, pw), plan, Plane.XY.offset(zc), ("X", "Y"), (-10.5, 10.5),
                      (-10.5, 10.5))
    a3.set_title(f"plan section at z = {zc:.0f} mm (through the magnet)", fontsize=12, pad=10)
    from matplotlib.patches import Circle, Rectangle
    a3.add_patch(Circle((0, 0), M.SH["spring"][0], fill=False, ec=R.colour("spring") * 0.75, lw=1.6,
                        ls=(0, (1.5, 1.5)), zorder=18))
    a3.add_patch(Rectangle((-1.5, -1.5), 3.0, 3.0, fill=False, ec=(0.1, 0.1, 0.1), lw=1.0, ls=(0, (3, 2)),
                           zorder=20))
    a3.add_patch(Circle((0, 0), lat, fill=False, ec=HI, lw=1.4, zorder=25))
    push(a3, (-10.0, 0), (-7.4, 0), "X", offset=(0.3, 0.9), ha="left", font=F + 1)
    push(a3, (0, -10.0), (0, -6.9), "Y", offset=(0.6, 0.4), ha="left", font=F + 1)
    lab3 = [
        ("flexure posts (4)", (0.0, 4.9), "R"),
        ("carrier cup", (3.0, 2.6), "R"),
        ("spring (dotted:\nits mean circle)", (2.6, 0.92), "R"),
        ("stem pole and magnet", (1.0, 0.6), "R"),
        (f"red circle: where the magnet\ncentre can go (\u00b1{lat:.1f} mm,\nthe roof-hole stop)",
         (lat * 0.7, -lat * 0.7), "R"),
        ("dashed: TMAG5170 below\n(z 0-1 mm)", (1.5, -1.2), "R"),
        ("housing", (6.2, -3.5), "R"),
    ]
    label2d(fig, a3, lab3, right_px=18)
    note(fig, "Concept geometry, not a design. The post size, the sideways stiffness, and the X/Y signal "
         "after\nremoving press crosstalk are what the rev A shear coupon would measure.", y_px=14)
    save(fig, os.path.join(OUT, "mech_shear_key_section.png"),
         title="Shear key: exact sections, at rest, pushed sideways, and in plan")


def shear_glb():
    R.export_glb(M.shear_key(0.0), os.path.join(MODELS, "mech_shear_key.glb"), tol=0.06)
    print("models/mech_shear_key.glb", os.path.getsize(os.path.join(MODELS, "mech_shear_key.glb")) // 1024, "KB")


# ---------------------------------------------------------------------------
# (3) Haptic thumb wheel
# ---------------------------------------------------------------------------
def wheel_front_panel(path):
    items = []
    for n, sol, c in M.thumb_wheel():
        if n in ("thumb plate", "thumb PCB", "roller hub", "tyre"):
            sol = M.half(sol, "y+")
        items.append((n, sol, c))
    xm = M.ROLLER_W / 2
    rot = [("rotation", M.arc_arrow(xm, (0.0, M.WHEEL_Z), M.ROLLER_OD / 2 + 3.0, 62, 118), "highlight")]
    labels = [
        ("thumb key (for scale)", (-19.0, -6.0, 12.0), "L"),
        ("thumb plate (front\nhalf cut away)", (-24.0, 8.0, 0.0), "L"),
        ("encoder board: MT6701CT\nor AS5047P (candidate), on\nthe face towards the motor",
         (-9.4, -11.0, -22.0), "L"),
        ("bracket", (-2.8, -12.0, -24.0), "L"),
        ("roller, front half cut away:\nprinted hub, rubber tyre", (8.5, 0.0, -24.5), "R"),
        ("BLDC gimbal motor (not chosen;\n2804-class in this sketch): its\nouter rotor carries the roller",
         (4.0, -9.0, -18.5), "R"),
        ("thumb key (for scale)", (29.0, -6.0, 12.0), "R"),
    ]
    tags = [("detents, end stops and free\nspin, set by the profile",
             (xm, 0.0, M.WHEEL_Z + M.ROLLER_OD / 2 + 3.0), 0, 48)]
    view3d(path, [items, rot], elev=22, azim=-64, labels=labels, tags=tags, size=(11, 8.5), zoom=0.74,
           max_edge=2.0, tol=0.08, finish=False)


def wheel_rear_panel(path):
    skip = ("thumb plate", "thumb PCB")
    items = [it for it in M.thumb_wheel() if it[0] not in skip and not it[0].startswith(("switch", "keycap"))]
    labels = [
        ("bracket flange (screws\nunder the thumb plate)", (-7.0, 6.0, -1.5), "L"),
        ("encoder board, back face", (-10.2, 9.0, -8.0), "L"),
        ("DRV8316 motor driver\n(QFN, candidate)", (-11.1, 1.0, -19.0), "R"),
        ("connector to the\nmain board", (-13.5, -8.5, -21.5), "R"),
        ("roller (printed hub,\nrubber tyre)", (5.0, 12.0, 3.0), "R"),
        ("decoupling parts\n(illustrative)", (-10.9, 6.5, -18.0), "L"),
        ("standoff to the bracket", (-6.0, 10.0, -21.0), "L"),
    ]
    view3d(path, [items], elev=24, azim=146, labels=labels, size=(10, 8.0), zoom=0.72, max_edge=2.0, tol=0.08,
           finish=False)


def wheel_3d():
    """Top: the module in the thumb cluster, from the front. Bottom: the module alone, from behind."""
    a = os.path.join(OUT, "_wheel_a.png")
    b = os.path.join(OUT, "_wheel_b.png")
    wheel_front_panel(a)
    wheel_rear_panel(b)
    compose(os.path.join(OUT, "mech_thumb_wheel.png"), [a, b],
            "Haptic thumb wheel module between two thumb keys (concept)",
            captions=["top: in the thumb cluster, from the front (plate and roller cut away)",
                      "bottom: the module alone, from behind"])


def wheel_section():
    items = M.thumb_wheel()
    W, H = 1500, 810
    fig = plt.figure(figsize=(W / DPI, H / DPI), dpi=DPI)
    zc = M.WHEEL_Z
    xl, yl = (-30.0, 40.0), (-27.5, 14.0)
    ppm = 13.5
    aw, ah = (xl[1] - xl[0]) * ppm, (yl[1] - yl[0]) * ppm
    ax = section_axes(fig, px_rect(fig, 300, H - 70 - ah, aw, ah), items, Plane.XZ, ("X", "Z"), xl, yl, ylabel="")
    ax.text(xl[0], yl[1] + 0.5, "z (mm)", ha="center", va="bottom", fontsize=F - 1)   # clear of the callouts
    ax.axhline(zc, color=(0.3, 0.3, 0.3), lw=0.6, ls=(0, (8, 3, 2, 3)), zorder=30)
    ax.text(39.5, zc + 0.3, "shaft axis", fontsize=F - 1, color=(0.3, 0.3, 0.3), ha="right", va="bottom")
    labels = [
        ("thumb key (for scale)", (-19.0, 10.5), "L"),
        ("thumb plate", (-27.0, -0.75), "L"),
        ("thumb PCB (cut back)", (-27.0, -5.8), "L"),
        ("bracket", (-2.8, -22.0), "L"),
        ("encoder board", (-9.4, -18.0), "L"),
        ("DRV8316 driver\n(QFN, candidate)", (-10.65, -19.0), "L"),
        ("encoder IC: MT6701CT\nor AS5047P (candidate)", (-7.8, zc + 1.5), "L"),
        ("diametric magnet\non the shaft", (-5.6, zc - 2.0), "L"),
        ("bearings (2)", (-1.1, zc + 2.5), "L"),
        ("rubber tyre", (5.0, 7.6), "R"),
        ("printed roller hub", (9.0, 5.5), "R"),
        ("rotor bell (outer rotor)", (3.5, zc + 13.5), "R"),
        ("rotor magnets", (3.0, zc + 12.5), "R"),
        ("stator core", (3.3, zc + 8.0), "R"),
        ("windings", (6.1, zc - 7.0), "R"),
        ("stator base / hub", (-1.0, zc - 6.0), "R"),
        ("shaft", (3.0, zc + 0.0), "R"),
        ("thumb key (for scale)", (29.0, 10.5), "R"),
    ]
    label2d(fig, ax, labels, left_px=56, right_px=16)
    note(fig, "Concept geometry, not a design. The motor is not chosen: the sketch draws a 2804-class "
         "gimbal motor,\nwith magnet and roller fitted by hand (concept \u00a72.3); the board parts are the "
         "stocked candidates.\nDetent strength, cogging and current are rev A unknowns.", y_px=14)
    save(fig, os.path.join(OUT, "mech_thumb_wheel_section.png"),
         title="Haptic thumb wheel: exact section through the shaft (y = 0), concept")


def wheel_glb():
    R.export_glb(M.thumb_wheel(), os.path.join(MODELS, "mech_thumb_wheel.glb"), tol=0.04)
    print("models/mech_thumb_wheel.glb", os.path.getsize(os.path.join(MODELS, "mech_thumb_wheel.glb")) // 1024, "KB")


# ---------------------------------------------------------------------------
# (4) Printed-coil key
# ---------------------------------------------------------------------------
COIL_LIFT = 11.0


def coil_3d_panel(path):
    lift = COIL_LIFT
    items = M.coil_key(step_cut=True, lift=lift)
    board = [it for it in items if it[0] == "pcb"]
    l1 = [it for it in items if it[0] == "coil L1"][0]
    l2 = [it for it in items if it[0] == "coil L2"][0]
    # the copper group is drawn over the board and under everything else; L2 only where it is peeled open
    copper = [("coil L1", l1[1], "copper"),
              ("coil L2", l2[1] & M.box(0, 5.0, -5.0, 0, -1, 1), "copper")]
    rest = [it for it in items if it[0] not in ("pcb", "coil L1", "coil L2")]
    labels = [
        ("keycap", (-6.0, 0.0, 16.8 + lift), "L"),
        ("stock MX switch (3-pin),\ncut in half and lifted\n11 mm off the board", (-6.6, 0.0, 9.0 + lift), "L"),
        ("contact leaves: it still\nswitches as before", (-4.5, 2.5, 4.0 + lift), "L"),
        ("spiral on L1 (top copper)", (-2.43, -2.43, 0.07), "L"),
        ("MX centre-post hole", (-1.4, -1.4, 0.0), "L"),
        ("PCB: no copper pour\nunder the coil", (-9.0, -8.0, 0.0), "L"),
        ("steel spring:\nthe coil's target", (2.5, -0.3, 5.0 + lift), "R"),
        ("plate", (10.0, 8.0, 5.0 + lift), "R"),
        ("leads to an inductance-\nto-digital converter\n(LDC1614-class)", (0.0, 8.0, 0.07), "R"),
        ("the same spiral on L2:\nL1 and 0.2 mm of prepreg\npeeled off here", (2.4, -1.7, -0.14), "R"),
    ]
    view3d(path, [board, copper, rest], elev=40, azim=-64, labels=labels, size=(10.5, 10), zoom=0.80,
           max_edge=0.7, tol=0.03, finish=False)


def coil_section_panel(path):
    """The exact section (left) and a zoom on the copper (right), side by side under the 3D panel."""
    from matplotlib.patches import Rectangle
    items = M.coil_key(step_cut=False)
    W, H = 1460, 600
    fig = plt.figure(figsize=(W / DPI, H / DPI), dpi=DPI)
    xl, yl = (-5.2, 5.2), (-1.8, 8.2)
    ppm = 42.0
    ax = section_axes(fig, px_rect(fig, 190, 75, (xl[1] - xl[0]) * ppm, (yl[1] - yl[0]) * ppm), items, Plane.XZ,
                      ("X", "Z"), xl, yl, ylabel="")
    # the callouts sit on the left, so the z ticks go on the right and the dimension texts beyond them
    ax.yaxis.tick_right()
    ax.text(xl[1], yl[1] + 0.15, "z (mm)", ha="center", va="bottom", fontsize=F - 1)
    ax.set_title("exact section at y = 0", fontsize=12, pad=24)
    cu = M.COIL["cu"]
    dim(ax, 4.7, cu, 1.0 + cu, "1 mm", side="R", ext=[((3.4, 5.0), (1.0 + cu, 1.0 + cu))], tx=1.45)
    dim(ax, 4.0, 1.0 + cu, 7.5 + cu, "spring:\n1-7.5 mm\nabove L1", side="R",
        ext=[((2.9, 4.3), (7.5 + cu, 7.5 + cu))], tx=2.15)
    labels = [
        ("stem pole", (-0.6, 5.5), "L"),
        ("spring wire\n(steel)", (-2.5, 4.1), "L"),
        ("housing\nfloor", (-4.0, 0.5), "L"),
        ("centre post", (-1.7, -1.0), "L"),
        ("PCB (FR4)", (-4.0, -1.0), "L"),
    ]
    label2d(fig, ax, labels, left_px=48, right_px=14)
    zx, zz = (1.95, 3.85), (-0.42, 0.26)
    ax.add_patch(Rectangle((zx[0], zz[0]), zx[1] - zx[0], zz[1] - zz[0], fill=False, ec=HI, lw=1.0, zorder=35))
    zw, zx0 = 390.0, 845.0
    zh = zw * (zz[1] - zz[0]) / (zx[1] - zx[0])
    z2 = section_axes(fig, px_rect(fig, zx0, 260, zw, zh), items, Plane.XZ, ("X", "Z"), zx, zz, ylabel="z (mm)")
    for sp in z2.spines.values():
        sp.set_edgecolor(HI)
    z2.set_title("zoom on the copper (pink box, left)", fontsize=F + 1, pad=8)
    labels2 = [                  # one column, right of the zoom, clear of its z ticks
        ("housing floor", (3.5, 0.2), "R"),
        ("L1 turns (top copper)", (2.53, 0.035), "R"),
        ("via, L1 to L2", (2.25, -0.07), "R"),
        ("L2 turns (inner layer)", (2.53, -0.175), "R"),
        ("prepreg / core", (3.6, -0.3), "R"),
    ]
    label2d(fig, z2, labels2, right_px=14, ylim=(-0.62, 0.48))
    fig.text((zx0 + zw / 2) / W, 130 / H, "copper drawn 70 \u00b5m thick (exaggerated);\ntrace and space 0.125 mm",
             ha="center", va="top", fontsize=F, color=(0.35, 0.35, 0.35), style="italic", linespacing=1.35)
    save(fig, path, finish=False)


def coil_key():
    """Top: the exploded 3D cutaway. Bottom: the exact section and a zoom on the copper."""
    a = os.path.join(OUT, "_coil_a.png")
    b = os.path.join(OUT, "_coil_b.png")
    coil_3d_panel(a)
    coil_section_panel(b)
    compose(os.path.join(OUT, "mech_coil_key.png"), [a, b],
            "Printed-coil key: a generated spiral under a stock MX switch (concept, unproven)",
            captions=["top: exploded cutaway, the switch lifted off its coil",
                      "bottom: assembled, the gap the coil has to read across"])


# ---------------------------------------------------------------------------
# (5) LRA mount
# ---------------------------------------------------------------------------
def lra_3d_panel(path):
    keep_whole = {"desk", "flex tail"}
    items = [(n, sol if n in keep_whole else M.half(sol, "y+"), c) for n, sol, c in M.lra_mount()]
    labels = [
        ("flex tail, up to the haptic\ndriver (DRV2605L, on the\nmain PCB above)", (11.6, 3.0, 8.5), "R"),
        ("coin LRA, about 10 mm\nacross and 2.7 mm thick\n(cut in half)", (2.0, 0.0, 3.6), "R"),
        ("slot all round the cradle", (9.2, 2.0, 2.4), "R"),
        ("case floor (printed)", (13.0, 1.0, 2.4), "R"),
        ("cradle, printed\nwith the case", (-2.5, 0.0, 1.1), "L"),
        ("flexure arm: the only\npath from cradle to case", (-8.2, 0.3, 2.4), "L"),
        ("TPU foot", (-11.0, 0.0, -0.8), "L"),
        ("desk", (-12.0, -6.0, -1.5), "L"),
    ]
    view3d(path, [items], elev=38, azim=-64, labels=labels, size=(11, 8.0), zoom=0.82, max_edge=1.0, tol=0.04,
           finish=False)


def lra_plan_panel(path):
    c = M.LRA
    items = [it for it in M.lra_mount() if it[0] in ("case floor", "flexure arms", "cradle", "coin LRA")]
    W, H = 1200, 860
    fig = plt.figure(figsize=(W / DPI, H / DPI), dpi=DPI)
    zc = 0.5 * (c["arm_z"][0] + c["arm_z"][1])
    pw = 25.0 * 26.0
    ax = section_axes(fig, px_rect(fig, 400, 90, pw, pw), items, Plane.XY.offset(zc), ("X", "Y"), (-12.5, 12.5),
                      (-12.5, 12.5), ylabel="")
    # every callout sits on the left, so the y ticks and the unit go on the right
    ax.yaxis.tick_right()
    ax.text(12.5, 12.9, "y (mm)", ha="center", va="bottom", fontsize=F - 1)
    ax.set_title(f"plan section at z = {zc:.1f} mm, through the arms", fontsize=12, pad=24)
    labels = [
        ("coin LRA", (-2.0, -2.0), "L"),
        ("cradle", (-5.2, -4.0), "L"),
        ("case floor", (-11.0, 11.5), "L"),
        ("three flexure arms,\neach about 95\u00b0 of\narc (illustrative)",
         (8.2 * np.cos(np.radians(150)), 8.2 * np.sin(np.radians(150))), "L"),
        ("arm root in the floor", (9.5 * np.cos(np.radians(184)), 9.5 * np.sin(np.radians(184))), "L"),
        ("slot (air)", (9.2 * np.cos(np.radians(200)), 9.2 * np.sin(np.radians(200))), "L"),
        ("arm root in the cradle", (7.2 * np.cos(np.radians(94)), 7.2 * np.sin(np.radians(94))), "L"),
    ]
    label2d(fig, ax, labels, left_px=48, right_px=14)
    save(fig, path, finish=False)


def lra_mount():
    """Top: a half-section of the pocket in 3D. Bottom: the suspension in plan."""
    a = os.path.join(OUT, "_lra_a.png")
    b = os.path.join(OUT, "_lra_b.png")
    lra_3d_panel(a)
    lra_plan_panel(b)
    compose(os.path.join(OUT, "mech_lra_mount.png"), [a, b],
            "Coin LRA in a decoupled flexure pocket in the case floor (concept, untested)",
            captions=["top: half-section of the pocket (main PCB above not drawn)",
                      "bottom: the suspension in plan"])


# ---------------------------------------------------------------------------
JOBS = {"he": (he_cutaway, he_section), "shear": (shear_cutaway, shear_section),
        "wheel": (wheel_3d, wheel_section), "coil": (coil_key,), "lra": (lra_mount,), "glb": (shear_glb, wheel_glb)}

if __name__ == "__main__":
    want = sys.argv[1:] or list(JOBS)
    for k in want:
        for fn in JOBS[k]:
            fn()
