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
           font=9, gap=36, roll=0, finish=True, title=None):
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


def compose(path, panels, title, captions=(), gap=40, valign="center"):
    """Place cropped panel PNGs side by side, each with a caption above, then title + stamp (render_lib)."""
    from PIL import Image, ImageDraw
    ims = [Image.open(p).convert("RGB") for p in panels]
    ft = R._font(16)
    cap_h = 30 if captions else 0
    h = max(i.height for i in ims) + cap_h
    w = sum(i.width for i in ims) + gap * (len(ims) - 1)
    out = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(out)
    x = 0
    for k, im in enumerate(ims):
        y = cap_h + ((h - cap_h - im.height) // 2 if valign == "center" else 0)
        out.paste(im, (x, y))
        if captions:
            d.text((x + im.width // 2, 4), captions[k], fill=(60, 60, 60), font=ft, anchor="mt")
        x += im.width + gap
    out.save(path)
    for p in panels:
        os.remove(p)
    R.autocrop(path, title=title)
    shrink(path)
    print(os.path.relpath(path, os.getcwd()), os.path.getsize(path) // 1024, "KB")


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


def section_axes(fig, rect, items, plane, axes, xlim, ylim, xlabel=None, ylabel=None, font=9):
    ax = fig.add_axes(rect)
    fill_section(ax, items, plane, axes)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.grid(True, lw=0.3, alpha=0.45, zorder=0)
    ax.set_axisbelow(True)
    ax.tick_params(labelsize=font - 1)
    ax.set_xlabel(xlabel or f"{axes[0].lower()} (mm)", fontsize=font)
    ax.set_ylabel(ylabel or f"{axes[1].lower()} (mm)", fontsize=font)
    return ax


def label2d(fig, ax, labels, left_px=52, right_px=14, font=9, ylim=None):
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


def dim(ax, x, y0, y1, text, side="R", font=9, colour=None, axis="v", ext=None):
    """A dimension arrow between y0 and y1 at x (axis 'v'), or between x0=y0 and x1=y1 at height x ('h')."""
    c = HI if colour is None else colour
    if axis == "v":
        a, b = (x, y0), (x, y1)
        t = (x + (0.5 if side == "R" else -0.5), (y0 + y1) / 2)
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


def push(ax, p0, p1, text, font=9, offset=(0, 0), ha="center", va="center"):
    ax.annotate("", xy=p1, xytext=p0, arrowprops=dict(arrowstyle="-|>", color=HI, lw=2.4, mutation_scale=18,
                                                      shrinkA=0, shrinkB=0), zorder=45)
    ax.text(p0[0] + offset[0], p0[1] + offset[1], text, ha=ha, va=va, fontsize=font, color=HI * 0.8,
            fontweight="bold", zorder=46)


def note(fig, text, x=0.5, y=0.01, font=9):
    fig.text(x, y, text, ha="center", va="bottom", fontsize=font, color=(0.35, 0.35, 0.35), style="italic")


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
        ("TMAG5253-class Hall sensor\n(SOT-23) on the PCB, under the magnet", (1.2, -0.7, 1.05), "R"),
    ]
    view3d(os.path.join(OUT, "mech_he_key_cutaway.png"), [items], elev=18, azim=-62, labels=labels,
           size=(11, 8), zoom=0.78, max_edge=0.8,
           title="Hall-effect key with a compliant bottom stop: half-section (concept)")


def he_section():
    rest = M.he_key(0.0)
    press = 4.3
    sq = press - M.TRAVEL
    down = M.he_key(press)
    fig = plt.figure(figsize=(17, 8.6), dpi=DPI)
    pl = Plane.XZ
    xl, yl = (-12.5, 15.0), (-1.6, 18.6)
    a1 = section_axes(fig, [0.115, 0.10, 0.31, 0.82], rest, pl, ("X", "Z"), xl, yl)
    a2 = section_axes(fig, [0.495, 0.10, 0.31, 0.82], down, pl, ("X", "Z"), xl, yl)
    a1.set_ylabel("")
    a1.set_title("at rest", fontsize=11)
    a2.set_title(f"pressed {press:.1f} mm: 4.0 mm to the stop, then {sq:.1f} mm into the TPU", fontsize=11)
    top = M.HE["cap_top"]
    dim(a1, 11.0, top, top - M.TRAVEL, "4.0 mm\ntravel", side="R",
        ext=[((5.0, 11.6), (top, top)), ((8.2, 11.6), (top - M.TRAVEL, top - M.TRAVEL))])
    mz = M.HE["magnet"][2]
    dim(a1, 0.0, 1.1, mz, f"{mz - 1.1:.1f} mm", side="R", font=9)
    dim(a2, 0.0, 1.1, mz - press, "", side="R")
    push(a2, (0, top - press + 3.4), (0, top - press + 0.4), "press", offset=(0, 0.7), font=10)
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
    label2d(fig, a1, lab_rest)
    lab_down = [
        ("spring compressed", (3.0, 4.0), "R"),
        (f"magnet-sensor gap {mz - press - 1.1:.1f} mm\n(was {mz - 1.1:.1f} mm at rest): the field\n"
         "keeps rising through the squeeze", (2.0, 3.4), "R"),
        ("stem lands on the TPU stop at 4.0 mm", (2.45, M.HE["pole"][1] - press + 0.05), "R"),
        (f"TPU squeezed {sq:.1f} mm (shown): the\n0.2-0.5 mm compliant zone that\nwould carry aftertouch",
         (1.4, 2.0), "R"),
    ]
    label2d(fig, a2, lab_down, ylim=(-1.6, 10.5))
    # zoomed inset of the compliant zone, top right, above the labels
    fig.canvas.draw()
    bb = a2.get_position()
    zx, zy = (-3.4, 3.4), (0.9, 3.3)
    w = 0.165
    h = w * fig.get_figwidth() / fig.get_figheight() * (zy[1] - zy[0]) / (zx[1] - zx[0])
    ins = fig.add_axes([bb.x1 + 0.015, bb.y1 - h - 0.03, w, h])
    fill_section(ins, down, pl, ("X", "Z"), lw=0.6)
    ins.set_xlim(*zx)
    ins.set_ylim(*zy)
    ins.set_aspect("equal", adjustable="box")
    ins.set_xticks([])
    ins.set_yticks([])
    tz = M.HE["floor"][1] + M.HE["tpu"][1]
    ins.axhline(tz, color=HI, lw=1.0, ls=(0, (3, 2)))
    ins.text(-3.3, tz + 0.05, "free TPU top", ha="left", va="bottom", fontsize=8, color=HI * 0.8,
             bbox=dict(boxstyle="round,pad=0.1", fc="white", ec="none", alpha=0.85))
    ins.annotate("", xy=(-2.75, tz - sq), xytext=(-2.75, tz), arrowprops=dict(arrowstyle="-|>", color=HI, lw=1.2,
                                                                           mutation_scale=8, shrinkA=0, shrinkB=0))
    ins.set_title(f"zoom (2x): the {sq:.1f} mm squeeze", fontsize=9)
    note(fig, "Concept geometry, not a design: an MX-style 14 mm switch with 4 mm travel. Dimensions in mm. "
              "The stop's stiffness and the field-versus-squeeze curve are unknowns for the rev A coupon.",
         y=bb.y0 - 0.12)
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
            ("Y push", (21.0, -12.0, 21.0), 10, -14)]
    view3d(os.path.join(OUT, "mech_shear_key_cutaway.png"), [items, arrows], elev=20, azim=-58, labels=labels,
           tags=tags, size=(12, 8.6), zoom=0.74, max_edge=0.8,
           title="Shear key: a stem guide hung on flexure posts over a 3-axis Hall sensor (concept)")


def shear_section():
    lat = M.SH["lateral"]
    rest = M.shear_key(0.0)
    pushed = M.shear_key(0.0, (lat, 0.0))
    fig = plt.figure(figsize=(20.5, 8.6), dpi=DPI)
    pl = Plane.XZ
    xl, yl = (-12.5, 12.5), (-1.6, 23.4)
    a1 = section_axes(fig, [0.10, 0.10, 0.23, 0.80], rest, pl, ("X", "Z"), xl, yl)
    a2 = section_axes(fig, [0.355, 0.10, 0.23, 0.80], pushed, pl, ("X", "Z"), xl, yl)
    a1.set_ylabel("")
    a1.set_title("at rest (section y = 0)", fontsize=11)
    a2.set_title(f"pushed +X to the stop ({lat:.1f} mm, true scale)", fontsize=11)
    top = M.SH["cap_top"]
    push(a1, (0, top + 4.6), (0, top + 0.4), "Z press:\ntypes as usual", offset=(0.7, -0.6), ha="left",
         va="top", font=10)
    dim(a1, 10.0, top, top - M.TRAVEL, "4.0 mm", side="R",
        ext=[((5.0, 10.6), (top, top)), ((8.0, 10.6), (top - M.TRAVEL, top - M.TRAVEL))])
    push(a2, (-12.0, 15.0), (-8.9 + lat, 15.0), "X push", offset=(0.1, 1.1), ha="left", font=10)
    lab1 = [
        ("keycap", (-6.6, 15.5), "L"),
        ("stem (slides 4 mm)", (-1.0, 13.0), "L"),
        ("roof hole (side stop)", (-4.6, 11.0), "L"),
        ("carrier cup", (-3.7, 9.0), "L"),
        ("magnet", (-1.2, 8.0), "L"),
        ("flexure post (1 of 4)", (-4.9, 6.5), "L"),
        ("spring", (-2.8, 5.63), "L"),
        ("housing", (-6.6, 3.5), "L"),
        ("TMAG5170", (-1.0, 0.55), "L"),
        ("PCB", (-8.0, -0.8), "L"),
    ]
    label2d(fig, a1, lab1)
    # pushed panel: three notes in a row above the keycap
    kw = dict(fontsize=9, color=INK, bbox=BOX, ha="left", va="top", zorder=50,
              arrowprops=dict(arrowstyle="-", color=LEAD, lw=0.7))
    a2.annotate(f"magnet {lat:.1f} mm off\ncentre: Bx changes\nat the sensor", xy=(0.6 + lat, 8.4),
                xytext=(-12.1, 23.0), **kw)
    a2.annotate("posts bend in an S;\nthe carrier shifts\nwithout tilting", xy=(4.9 + lat * 0.5, 6.4),
                xytext=(-3.7, 23.0), **kw)
    a2.annotate("gap closed on\nthis side: the\nhard stop", xy=(4.5, 10.9), xytext=(5.0, 23.0), **kw)
    a2.axvline(0, color=HI, lw=0.8, ls=(0, (4, 3)), zorder=30)
    a2.text(0.25, -1.3, "rest centre", fontsize=8, color=HI * 0.8, ha="left", va="bottom", zorder=31,
            bbox=dict(boxstyle="round,pad=0.1", fc="white", ec="none", alpha=0.85))
    # plan section through the magnet (the spring is drawn as its mean circle: a level cut through a helix
    # gives a misleading crescent)
    zc = 8.0
    plan = [it for it in rest if it[0] != "spring"]
    a3 = section_axes(fig, [0.62, 0.12, 0.22, 0.72], plan, Plane.XY.offset(zc), ("X", "Y"), (-10.5, 10.5),
                      (-10.5, 10.5))
    a3.set_title(f"plan section at z = {zc:.0f} mm (through the magnet)", fontsize=11)
    from matplotlib.patches import Circle, Rectangle
    a3.add_patch(Circle((0, 0), M.SH["spring"][0], fill=False, ec=R.colour("spring") * 0.75, lw=1.6,
                        ls=(0, (1.5, 1.5)), zorder=18))
    a3.add_patch(Rectangle((-1.5, -1.5), 3.0, 3.0, fill=False, ec=(0.1, 0.1, 0.1), lw=1.0, ls=(0, (3, 2)),
                           zorder=20))
    a3.add_patch(Circle((0, 0), lat, fill=False, ec=HI, lw=1.4, zorder=25))
    push(a3, (-10.0, 0), (-7.4, 0), "X", offset=(0.3, 0.9), ha="left", font=10)
    push(a3, (0, -10.0), (0, -6.9), "Y", offset=(0.6, 0.4), ha="left", font=10)
    lab3 = [
        ("flexure posts (4)", (0.0, 4.9), "R"),
        ("carrier cup", (3.8, 1.5), "R"),
        ("spring (dotted: its mean circle)", (2.0, 1.98), "R"),
        ("stem pole and magnet", (1.0, 0.6), "R"),
        (f"red circle: where the magnet centre\ncan go (\u00b1{lat:.1f} mm, the roof-hole stop)",
         (lat * 0.7, -lat * 0.7), "R"),
        ("dashed: TMAG5170 below (z 0-1 mm)", (1.5, -1.2), "R"),
        ("housing", (6.9, -6.0), "R"),
    ]
    label2d(fig, a3, lab3, right_px=18)
    fig.canvas.draw()
    note(fig, "Concept geometry, not a design. The post size, the sideways stiffness, and the X/Y signal after "
              "removing press crosstalk are what the rev A shear coupon would measure.",
         y=a1.get_position().y0 - 0.11)
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
        ("thumb plate (front half cut away)", (-24.0, 8.0, 0.0), "L"),
        ("encoder board (MT6701CT on\nthe face towards the motor)", (-9.4, -11.0, -22.0), "L"),
        ("bracket", (-2.8, -12.0, -24.0), "L"),
        ("roller, front half cut away:\nprinted hub and rubber tyre", (8.5, 0.0, -24.5), "R"),
        ("2804-class gimbal motor: its outer\nrotor carries the roller (direct drive)", (4.0, -9.0, -18.5), "R"),
        ("thumb key (for scale)", (29.0, -6.0, 12.0), "R"),
    ]
    tags = [("detents, end stops and free\nspin, set by the profile",
             (xm, 0.0, M.WHEEL_Z + M.ROLLER_OD / 2 + 3.0), 0, 44)]
    view3d(path, [items, rot], elev=22, azim=-64, labels=labels, tags=tags, size=(12, 8.5), zoom=0.74,
           max_edge=2.0, tol=0.08, finish=False)


def wheel_rear_panel(path):
    skip = ("thumb plate", "thumb PCB")
    items = [it for it in M.thumb_wheel() if it[0] not in skip and not it[0].startswith(("switch", "keycap"))]
    labels = [
        ("bracket flange\n(screws under the thumb plate)", (-7.0, 6.0, -1.5), "L"),
        ("encoder board, back face", (-10.2, 9.0, -8.0), "L"),
        ("DRV8316 motor driver (QFN)", (-11.1, 1.0, -19.0), "R"),
        ("connector to the main board", (-13.5, -8.5, -21.5), "R"),
        ("roller (printed hub, rubber tyre)", (5.0, 12.0, 3.0), "R"),
        ("decoupling parts (illustrative)", (-10.9, 6.5, -18.0), "L"),
        ("standoff to the bracket", (-6.0, 10.0, -21.0), "L"),
    ]
    view3d(path, [items], elev=24, azim=146, labels=labels, size=(11, 8.5), zoom=0.72, max_edge=2.0, tol=0.08,
           finish=False)


def wheel_3d():
    a = os.path.join(OUT, "_wheel_a.png")
    b = os.path.join(OUT, "_wheel_b.png")
    wheel_front_panel(a)
    wheel_rear_panel(b)
    compose(os.path.join(OUT, "mech_thumb_wheel.png"), [a, b],
            "Haptic thumb wheel module between two thumb keys (concept)",
            captions=["in the thumb cluster, from the front (plate and roller cut away)",
                      "the module alone, from behind"])


def wheel_section():
    items = M.thumb_wheel()
    fig = plt.figure(figsize=(17, 8.4), dpi=DPI)
    zc = M.WHEEL_Z
    ax = section_axes(fig, [0.20, 0.09, 0.60, 0.84], items, Plane.XZ, ("X", "Z"), (-30.0, 40.0), (-27.5, 14.0))
    ax.axhline(zc, color=(0.3, 0.3, 0.3), lw=0.6, ls=(0, (8, 3, 2, 3)), zorder=30)
    ax.text(39.5, zc + 0.3, "shaft axis", fontsize=8, color=(0.3, 0.3, 0.3), ha="right", va="bottom")
    labels = [
        ("thumb key (for scale)", (-19.0, 10.5), "L"),
        ("thumb plate", (-27.0, -0.75), "L"),
        ("thumb PCB (cut back)", (-27.0, -5.8), "L"),
        ("bracket", (-2.8, -22.0), "L"),
        ("encoder board", (-9.4, -18.0), "L"),
        ("DRV8316 driver (QFN)", (-10.65, -19.0), "L"),
        ("MT6701CT encoder (SOP-8)", (-7.8, zc + 1.5), "L"),
        ("diametric magnet on the shaft", (-5.6, zc - 2.0), "L"),
        ("bearings (2)", (-1.1, zc + 2.5), "L"),
        ("rubber tyre", (5.0, 7.6), "R"),
        ("printed roller hub", (9.0, 3.0), "R"),
        ("rotor bell (outer rotor)", (3.5, zc + 13.5), "R"),
        ("rotor magnets", (3.0, zc + 12.5), "R"),
        ("stator core", (3.3, zc + 8.0), "R"),
        ("windings", (6.1, zc - 7.0), "R"),
        ("stator base / hub", (-1.0, zc - 6.0), "R"),
        ("shaft", (3.0, zc + 0.0), "R"),
        ("thumb key (for scale)", (29.0, 10.5), "R"),
    ]
    label2d(fig, ax, labels, left_px=56, right_px=16)
    fig.canvas.draw()
    note(fig, "Concept geometry, not a design. Motor, magnet and roller are fitted by hand (concept \u00a72.3); "
              "the board parts are the stocked candidates. Detent strength, cogging and current are rev A unknowns.",
         y=ax.get_position().y0 - 0.10)
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
        ("stock MX switch (3-pin), cut in half\nand lifted 11 mm off the board", (-6.6, 0.0, 9.0 + lift), "L"),
        ("contact leaves: it still\nswitches as before", (-4.5, 2.5, 4.0 + lift), "L"),
        ("spiral on L1 (top copper)", (-2.43, -2.43, 0.07), "L"),
        ("MX centre-post hole", (-1.4, -1.4, 0.0), "L"),
        ("PCB: no copper pour under the coil", (-9.0, -8.0, 0.0), "L"),
        ("steel spring: the coil's target", (2.5, -0.3, 5.0 + lift), "R"),
        ("plate", (10.0, 3.0, 5.0 + lift), "R"),
        ("leads to an inductance-to-digital\nconverter (LDC1614-class)", (0.0, 8.0, 0.07), "R"),
        ("the same spiral on L2: L1 and\n0.2 mm of prepreg peeled off here", (2.4, -1.7, -0.14), "R"),
    ]
    view3d(path, [board, copper, rest], elev=40, azim=-64, labels=labels, size=(12, 11), zoom=0.80,
           max_edge=0.7, tol=0.03, finish=False)


def coil_section_panel(path):
    from matplotlib.patches import Rectangle
    items = M.coil_key(step_cut=False)
    fig = plt.figure(figsize=(8.6, 9.0), dpi=DPI)
    ax = section_axes(fig, [0.25, 0.46, 0.50, 0.48], items, Plane.XZ, ("X", "Z"), (-5.2, 5.2), (-1.8, 8.2))
    ax.set_title("exact section at y = 0", fontsize=11)
    cu = M.COIL["cu"]
    dim(ax, 4.7, cu, 1.0 + cu, "1 mm", side="R", font=9, ext=[((3.4, 5.0), (1.0 + cu, 1.0 + cu))])
    dim(ax, 4.0, 1.0 + cu, 7.5 + cu, "spring:\n1-7.5 mm\nabove L1", side="R", font=9,
        ext=[((2.9, 4.3), (7.5 + cu, 7.5 + cu))])
    labels = [
        ("stem pole", (-0.6, 5.5), "L"),
        ("spring wire (steel)", (-2.5, 4.1), "L"),
        ("housing floor", (-4.0, 0.5), "L"),
        ("centre post", (-1.7, -1.0), "L"),
        ("PCB (FR4)", (-4.0, -1.0), "L"),
    ]
    label2d(fig, ax, labels, left_px=48, right_px=14)
    zx, zz = (1.95, 3.85), (-0.42, 0.26)
    ax.add_patch(Rectangle((zx[0], zz[0]), zx[1] - zx[0], zz[1] - zz[0], fill=False, ec=HI, lw=1.0, zorder=35))
    z2 = section_axes(fig, [0.25, 0.15, 0.50, 0.19], items, Plane.XZ, ("X", "Z"), zx, zz)
    z2.set_title("zoom on the copper (pink box above)", fontsize=10)
    z2.set_ylabel("")
    labels2 = [
        ("L1 turns (top copper)", (2.5, 0.035), "L"),
        ("L2 turns (inner layer)", (2.5, -0.175), "L"),
        ("via, L1 to L2", (2.25, -0.07), "R"),
        ("housing floor", (3.5, 0.2), "R"),
        ("prepreg / core", (3.6, -0.3), "R"),
    ]
    label2d(fig, z2, labels2, left_px=48, right_px=14)
    fig.text(0.5, 0.06, "copper drawn 70 \u00b5m thick (exaggerated); trace and space 0.125 mm",
             ha="center", va="bottom", fontsize=9, color=(0.35, 0.35, 0.35), style="italic")
    save(fig, path, finish=False)


def coil_key():
    a = os.path.join(OUT, "_coil_a.png")
    b = os.path.join(OUT, "_coil_b.png")
    coil_3d_panel(a)
    coil_section_panel(b)
    compose(os.path.join(OUT, "mech_coil_key.png"), [a, b],
            "Printed-coil key: a generated spiral under a stock MX switch (concept, unproven)",
            captions=["exploded cutaway: the switch lifted off its coil",
                      "assembled: the gap the coil has to read across"])


# ---------------------------------------------------------------------------
# (5) LRA mount
# ---------------------------------------------------------------------------
def lra_3d_panel(path):
    keep_whole = {"desk", "flex tail"}
    items = [(n, sol if n in keep_whole else M.half(sol, "y+"), c) for n, sol, c in M.lra_mount()]
    labels = [
        ("flex tail, up to the haptic driver\n(DRV2605L, on the main PCB above)", (11.6, 3.0, 8.5), "R"),
        ("coin LRA, about 10 mm across\nand 2.7 mm thick (cut in half)", (2.0, 0.0, 3.6), "R"),
        ("slot all round the cradle", (9.2, 2.0, 2.4), "R"),
        ("case floor (printed)", (12.0, 6.0, 2.4), "R"),
        ("cradle, printed with the case", (-6.6, 0.0, 3.0), "L"),
        ("flexure arm: the only path\nfrom cradle to case", (-8.2, 0.3, 2.4), "L"),
        ("TPU foot", (-11.0, 0.0, -0.8), "L"),
        ("desk", (-12.0, -6.0, -1.5), "L"),
    ]
    view3d(path, [items], elev=38, azim=-64, labels=labels, size=(12, 8.5), zoom=0.82, max_edge=1.0, tol=0.04,
           finish=False)


def lra_plan_panel(path):
    c = M.LRA
    items = [it for it in M.lra_mount() if it[0] in ("case floor", "flexure arms", "cradle", "coin LRA")]
    fig = plt.figure(figsize=(9.6, 8.0), dpi=DPI)
    zc = 0.5 * (c["arm_z"][0] + c["arm_z"][1])
    ax = section_axes(fig, [0.34, 0.10, 0.50, 0.80], items, Plane.XY.offset(zc), ("X", "Y"), (-12.5, 12.5),
                      (-12.5, 12.5))
    ax.set_ylabel("")
    ax.set_title(f"plan section at z = {zc:.1f} mm, through the arms", fontsize=11)
    labels = [
        ("coin LRA", (-2.0, -2.0), "L"),
        ("cradle", (-5.2, -4.0), "L"),
        ("case floor", (-11.0, 10.0), "L"),
        ("three flexure arms, each about\n95\u00b0 of arc (illustrative)",
         (8.2 * np.cos(np.radians(150)), 8.2 * np.sin(np.radians(150))), "L"),
        ("arm root in the floor", (9.5 * np.cos(np.radians(183)), 9.5 * np.sin(np.radians(183))), "L"),
        ("slot (air)", (9.2 * np.cos(np.radians(20)), 9.2 * np.sin(np.radians(20))), "R"),
        ("arm root in the cradle", (7.2 * np.cos(np.radians(334)), 7.2 * np.sin(np.radians(334))), "R"),
    ]
    label2d(fig, ax, labels, left_px=48, right_px=14)
    save(fig, path, finish=False)


def lra_mount():
    a = os.path.join(OUT, "_lra_a.png")
    b = os.path.join(OUT, "_lra_b.png")
    lra_3d_panel(a)
    lra_plan_panel(b)
    compose(os.path.join(OUT, "mech_lra_mount.png"), [a, b],
            "Coin LRA in a decoupled flexure pocket in the case floor (concept, untested)",
            captions=["half-section of the pocket (main PCB above not drawn)", "the suspension in plan"])


# ---------------------------------------------------------------------------
JOBS = {"he": (he_cutaway, he_section), "shear": (shear_cutaway, shear_section),
        "wheel": (wheel_3d, wheel_section), "coil": (coil_key,), "lra": (lra_mount,), "glb": (shear_glb, wheel_glb)}

if __name__ == "__main__":
    want = sys.argv[1:] or list(JOBS)
    for k in want:
        for fn in JOBS[k]:
            fn()
