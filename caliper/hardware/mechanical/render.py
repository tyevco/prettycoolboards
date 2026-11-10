#!/usr/bin/env python3
"""PNG renders of the caliper from the B-rep model (matplotlib, no OpenSCAD / GPU).

    python3 render.py          # renders/{assembly,assembly_back,exploded,slider_open,board_fit,section,
                               #          section_gaps,section_clamp,jaws_closed,parts}.png

Each solid is tessellated by OpenCascade and drawn as a flat-shaded triangle
mesh (Lambert shading from one light).  matplotlib sorts triangles by mean depth,
which is a painter's algorithm, so a thin part seen exactly edge-on can show
through; the views below are chosen so that does not matter.
Sections are exact: section() cuts each solid with a plane and the faces are filled.
"""
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                                   # noqa: E402
import numpy as np                                                # noqa: E402
from matplotlib.patches import PathPatch                          # noqa: E402
from matplotlib.path import Path                                  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection          # noqa: E402

from build123d import Plane, Pos, section                         # noqa: E402

import models as M                                                # noqa: E402
import params as P                                                # noqa: E402
from export import COLOURS                                        # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "renders")
LIGHT = np.array([0.35, -0.45, 0.82])
LIGHT /= np.linalg.norm(LIGHT)


def mesh(solid, tol=0.15):
    v, t = solid.tessellate(tol, 0.3)
    v = np.array([(p.X, p.Y, p.Z) for p in v])
    return v, np.array(t, dtype=int)


def subdivide(tri, max_edge):
    """Split triangles 1 -> 4 until no edge exceeds max_edge.  OpenCascade meshes a
    big flat face with a few long slivers, and a long sliver sorts wrongly in a
    painter's algorithm; small triangles sort (almost) right."""
    for _ in range(8):
        e = np.max(np.stack([np.linalg.norm(tri[:, i] - tri[:, (i + 1) % 3], axis=1) for i in range(3)]), axis=0)
        big = e > max_edge
        if not big.any():
            break
        t = tri[big]
        a, b, c = t[:, 0], t[:, 1], t[:, 2]
        ab, bc, ca = (a + b) / 2, (b + c) / 2, (c + a) / 2
        new = np.concatenate([np.stack(x, 1) for x in ((a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca))])
        tri = np.concatenate([tri[~big], new])
    return tri


def draw(ax, items, tol=0.15, alpha=1.0, max_edge=2.5):
    polys, cols = [], []
    for _name, s, c in items:
        v, t = mesh(s, tol)
        if len(t) == 0:
            continue
        tri = subdivide(v[t], max_edge)
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
        shade = 0.35 + 0.65 * np.abs(n @ LIGHT)
        base = np.array(COLOURS.get(c, (0.5, 0.5, 0.5)))
        polys.append(tri)
        cols.append(np.clip(base[None, :] * shade[:, None], 0, 1))
    tri = np.concatenate(polys)
    col = np.concatenate(cols)
    pc = Poly3DCollection(tri, facecolors=col, edgecolors="none", alpha=alpha)
    ax.add_collection3d(pc)
    lo, hi = tri.reshape(-1, 3).min(0), tri.reshape(-1, 3).max(0)
    return lo, hi


def setup(lo, hi, elev, azim, size=(12, 6), roll=0):
    fig = plt.figure(figsize=size, dpi=130)
    ax = fig.add_subplot(111, projection="3d", proj_type="ortho")
    ax.view_init(elev=elev, azim=azim, roll=roll)
    return fig, ax


def finish(fig, ax, lo, hi, path, title=None):
    ax.set_xlim(lo[0], hi[0])
    ax.set_ylim(lo[1], hi[1])
    ax.set_zlim(lo[2], hi[2])
    ax.set_box_aspect(tuple(np.maximum(hi - lo, 1e-3)), zoom=1.0)
    ax.set_axis_off()
    if title:
        ax.set_title(title, fontsize=10)
    fig.subplots_adjust(0, 0, 1, 1)
    fig.savefig(path, bbox_inches="tight", pad_inches=0.05, facecolor="white")
    plt.close(fig)
    autocrop(path)
    print(os.path.relpath(path, HERE))


def autocrop(path, margin=12):
    """3D axes keep a square-ish canvas; trim the white border off the PNG."""
    from PIL import Image
    im = Image.open(path).convert("RGB")
    a = np.asarray(im)
    ink = np.where((a < 245).any(axis=2))
    if len(ink[0]) == 0:
        return
    y0, y1 = max(ink[0].min() - margin, 0), min(ink[0].max() + margin, a.shape[0])
    x0, x1 = max(ink[1].min() - margin, 0), min(ink[1].max() + margin, a.shape[1])
    im.crop((x0, y0, x1, y1)).save(path)


def view(items, path, elev, azim, size=(12, 6), title=None, tol=0.15):
    fig = plt.figure(figsize=size, dpi=130)
    ax = fig.add_subplot(111, projection="3d", proj_type="ortho")
    ax.view_init(elev=elev, azim=azim)
    lo, hi = draw(ax, items, tol)
    finish(fig, ax, lo, hi, path, title)


def exploded_items():
    """Slider exploded along z (front up, back down), fixed parts in place."""
    dz = {"front_shell": 26, "button_cap": 34, "display": 16, "board": 9, "board_parts": 9, "tab_clamp": 12,
          "battery_door": -26, "battery": -16, "back_gib": -12, "y_gib": 0, "ref_strip": 0, "plunger_hw": -20,
          "front_pad": 4, "thumb_roller": 0, "oring": 0, "lock_screw": 0, "pusher": 0, "slider_body": 0}
    dy = {"y_gib": 8, "ref_strip": -8, "thumb_roller": 14, "oring": 14, "lock_screw": 10, "pusher": 30}
    out = []
    for n, s, c in M.slider_group(60.0, with_hardware=True):
        key = next((k for k in dz if n.startswith(k)), None)
        out.append((n, Pos(0, dy.get(key, 0), dz.get(key, 0)) * s, c))
    out += [(n, s, c) for n, s, c in M.fixed_group()]
    return out


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------
def face_paths(face, plane_axes):
    """matplotlib Path (even-odd) of a planar face, in the 2 chosen global axes."""
    verts, codes = [], []
    for w in face.wires():
        pts = []
        for e in w.order_edges() if hasattr(w, "order_edges") else w.edges():
            n = 2 if e.geom_type.name == "LINE" else 24
            for t in np.linspace(0, 1, n):
                p = e.position_at(t)
                pts.append((getattr(p, plane_axes[0]), getattr(p, plane_axes[1])))
        if len(pts) < 3:
            continue
        verts += pts + [pts[0]]
        codes += [Path.MOVETO] + [Path.LINETO] * (len(pts) - 1) + [Path.CLOSEPOLY]
    return Path(verts, codes) if verts else None


def section_plot(items, x_cut, path, xlim=None, ylim=None, title="", notes=(), size=(9, 7)):
    plane = Plane.YZ.offset(x_cut)
    fig, ax = plt.subplots(figsize=size, dpi=140)
    for name, s, c in items:
        try:
            sec = section(s, plane)
        except Exception:      # noqa: BLE001
            continue
        for f in sec.faces():
            p = face_paths(f, ("Y", "Z"))
            if p is None:
                continue
            ax.add_patch(PathPatch(p, facecolor=COLOURS.get(c, (0.5, 0.5, 0.5)), edgecolor="k", lw=0.4))
    ax.set_aspect("equal")
    if xlim:
        ax.set_xlim(*xlim)
    if ylim:
        ax.set_ylim(*ylim)
    else:
        ax.autoscale_view()
    ax.set_xlabel("y (mm, from the beam's lower / reference edge)")
    ax.set_ylabel("z (mm, from the beam's front face)")
    ax.set_title(title, fontsize=10)
    ax.grid(True, lw=0.3, alpha=0.5)
    for x, y, t in notes:
        ax.annotate(t, (x, y), fontsize=7, xytext=(5, 5), textcoords="offset points",
                    arrowprops=dict(arrowstyle="-", lw=0.4))
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    print(os.path.relpath(path, HERE))


def main():
    os.makedirs(OUT, exist_ok=True)
    R = 60.0
    asm = M.assembly(R, with_hardware=True)
    view(asm, os.path.join(OUT, "assembly.png"), 52, -72, (13, 8),
         f"PrettyCool Caliper rev A, reading {R:g} mm (front)")
    view(asm, os.path.join(OUT, "assembly_back.png"), -50, 108, (13, 8), "back")
    view(exploded_items(), os.path.join(OUT, "exploded.png"), 30, -62, (13, 10), "exploded (slider along z)")
    sl = [i for i in M.slider_group(0, with_hardware=True) if not i[0].startswith(("front_shell",))]
    import board_envelope as BE
    src = BE.load_parts()[1].split(" (")[0]
    view(sl + [("beam", M.box(-5, 90, 0, 20, -4, 0), "steel")], os.path.join(OUT, "slider_open.png"),
         50, -70, (11, 8), f"slider with the front shell removed (board envelope from {src})")
    # the routed board in its cavity, seen from the front: tabs in the towers, parts, glass outline
    fit = [i for i in sl if not i[0].startswith(("button_cap", "display", "lock_screw"))]
    view(fit, os.path.join(OUT, "board_fit.png"), 90, -90, (11, 8),
         f"front view, lid off: board (from {src}) with its end tabs clamped in the towers")
    # stack-up section through the AS5311 (u = 8 + 31 = 39) at R = 0
    items = [(n, s, c) for n, s, c in M.assembly(0.0, with_hardware=True)]
    u_as = P.BOARD_U0 + P.AS_X
    section_plot(items, u_as, os.path.join(OUT, "section.png"), xlim=(-5, 39), ylim=(-10.5, 8.5),
                 title=f"Section x = {u_as:g} (through the AS5311), reading 0", size=(11, 4.2))
    section_plot(items, u_as, os.path.join(OUT, "section_gaps.png"), xlim=(-2.5, 22.5), ylim=(-6, 2.5),
                 title="Section x = 39, detail: tape channel, scale pocket, gibs and gaps",
                 notes=[(6, P.TAPE_TOP, f"tape top z {P.TAPE_TOP:+.2f}"),
                        (6, P.BOARD_Z0 - P.AS_H_MAX, "AS5311 (A max) face"),
                        (14, 0.0, f"scale face z 0, gap {P.CAP_GAP} to the electrodes"),
                        (10, -P.BEAM_T - P.BGIB_T, "back gib"),
                        (20.5, -2.0, "Y gib"), (-0.5, -2.0, "ref strip")], size=(11, 4.6))
    # section through the left tab clamp (u = 4.5): standoff, bedded washer, clamp screw, front pads, back web
    u_cl = P.BOARD_U0 + P.TAB_HOLES[0][0]
    section_plot(items, u_cl, os.path.join(OUT, "section_clamp.png"), xlim=(-4, 25), ylim=(-9.5, 7.6),
                 title=f"Section x = {u_cl:g} (left tower, tab clamps H2 / H3), reading 0",
                 notes=[(5.5, P.CLAMP_CEIL_Z, "bedded washer + clamp face"), (14.0, P.BOARD_Z1 + 1.0, "SMT standoff"),
                        (9.75, P.BOARD_Z0, "board end tab"), (10.0, P.Z_BACK + 1.0, "back web (3.2)"),
                        (0.95, 0.5, "front pad"), (18.8, 4.0, "pad set screw")], size=(11, 6))
    # end-stop and inside jaws at the closed position, front view
    view(M.assembly(0.0, with_hardware=True), os.path.join(OUT, "jaws_closed.png"), 90, -90, (8, 9),
         "jaws closed (front view, z toward the viewer)")
    # parts plate
    plate, x = [], 0.0
    for name, p in M.PARTS.items():
        if name in ("beam", "slider_body_b"):
            continue
        s = M.print_pose(name)
        bb = s.bounding_box()
        mat = {"PETG": "body", "PA-CF": "jaw", "brass": "brass"}.get(p.material, "steel")
        plate.append((name, Pos(x, 0, 0) * s, mat))
        x += bb.size.X + 6
    view(plate, os.path.join(OUT, "parts.png"), 35, -60, (14, 5), "printed and brass parts, print pose")
    return 0


if __name__ == "__main__":
    sys.exit(main())
