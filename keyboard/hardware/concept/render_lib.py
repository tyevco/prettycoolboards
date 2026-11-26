"""Shared helpers for the keyboard's concept renders (build123d B-rep -> PNG, matplotlib, no GPU).

Adapted from caliper/hardware/mechanical/render.py. Each solid is tessellated by OpenCascade and drawn as a
flat-shaded triangle mesh (Lambert shading from one light). matplotlib sorts triangles by mean depth (a painter's
algorithm), so long slivers are subdivided first; pick views where a thin part is not seen exactly edge-on.

Every image these helpers write carries a "concept sketch" stamp: nothing in keyboard/ is designed yet, and the
geometry is illustrative (see keyboard/docs/concept.md).

    items = [(name, solid, colour_key), ...]
    view(items, "renders/x.png", elev=35, azim=-60, title="...")
    section_plot(items, Plane.XZ, ("X", "Z"), "renders/x_section.png", ...)
    export_glb(items, "models/x.glb")
"""
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt                                   # noqa: E402
import numpy as np                                                # noqa: E402
from matplotlib.patches import PathPatch                          # noqa: E402
from matplotlib.path import Path                                  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection          # noqa: E402

STAMP = "CONCEPT SKETCH: illustrative geometry, not a design"
LIGHT = np.array([0.35, -0.45, 0.82])
LIGHT /= np.linalg.norm(LIGHT)

# one palette for every keyboard render (RGB 0..1)
COLOURS = {
    "case": (0.20, 0.22, 0.26),        # printed case, dark grey
    "case_light": (0.55, 0.58, 0.63),  # second case colour / plate
    "plate": (0.62, 0.64, 0.67),
    "pcb": (0.10, 0.45, 0.20),         # FR4 green
    "flex": (0.85, 0.55, 0.15),        # polyimide amber
    "copper": (0.80, 0.50, 0.25),
    "keycap": (0.88, 0.88, 0.86),
    "keycap_accent": (0.16, 0.38, 0.62),   # shear keys and other highlighted keys
    "keycap_alt": (0.92, 0.55, 0.15),      # thumb / modifier accent
    "switch": (0.12, 0.12, 0.14),
    "stem": (0.80, 0.20, 0.20),
    "magnet": (0.55, 0.55, 0.60),
    "sensor": (0.05, 0.05, 0.08),      # IC packages
    "ic": (0.05, 0.05, 0.08),
    "motor": (0.35, 0.36, 0.40),
    "roller": (0.25, 0.25, 0.28),
    "rubber": (0.10, 0.10, 0.10),
    "lra": (0.75, 0.70, 0.30),
    "battery": (0.70, 0.70, 0.75),
    "usb": (0.75, 0.76, 0.78),
    "steel": (0.62, 0.64, 0.67),
    "spring": (0.85, 0.80, 0.55),
    "tpu": (0.30, 0.65, 0.75),
    "highlight": (0.90, 0.20, 0.45),
}


def mesh(solid, tol=0.15):
    v, t = solid.tessellate(tol, 0.3)
    v = np.array([(p.X, p.Y, p.Z) for p in v])
    return v, np.array(t, dtype=int)


def subdivide(tri, max_edge):
    """Split triangles 1 -> 4 until no edge exceeds max_edge, so the depth sort is (almost) right."""
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


def colour(c):
    if isinstance(c, tuple):
        return np.array(c)
    return np.array(COLOURS.get(c, (0.5, 0.5, 0.5)))


def draw(ax, items, tol=0.15, alpha=1.0, max_edge=4.0):
    polys, cols = [], []
    for _name, s, c in items:
        v, t = mesh(s, tol)
        if len(t) == 0:
            continue
        tri = subdivide(v[t], max_edge)
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
        shade = 0.35 + 0.65 * np.abs(n @ LIGHT)
        polys.append(tri)
        cols.append(np.clip(colour(c)[None, :] * shade[:, None], 0, 1))
    tri = np.concatenate(polys)
    col = np.concatenate(cols)
    # edges in the face colour hide the anti-aliasing seams between triangles
    ax.add_collection3d(Poly3DCollection(tri, facecolors=col, edgecolors=col, linewidths=0.25, alpha=alpha))
    lo, hi = tri.reshape(-1, 3).min(0), tri.reshape(-1, 3).max(0)
    return lo, hi


def stamp(fig, text=STAMP):
    fig.text(0.995, 0.005, text, ha="right", va="bottom", fontsize=7, color=(0.55, 0.1, 0.1), alpha=0.85)


def _font(size):
    from matplotlib import font_manager
    from PIL import ImageFont
    return ImageFont.truetype(font_manager.findfont("DejaVu Sans"), size)


def stamp_sizes(width):
    """Title and stamp font sizes (px) for an image `width` px wide. The docs column shows images about 688 px wide,
    so both scale with the width: the stamp stays about 8 px tall there and the title about 11 px."""
    return max(20, width // 60), max(13, width // 86)


def autocrop(path, margin=16, title=None):
    """3D axes keep a square-ish canvas: trim the white border off the PNG, then add the title above the
    picture and the concept stamp below it (after the crop, so neither holds the border open). Both fonts, and
    the bands that hold them, grow with the cropped width (stamp_sizes)."""
    from PIL import Image, ImageDraw
    im = Image.open(path).convert("RGB")
    a = np.asarray(im)
    ink = np.where((a < 245).any(axis=2))
    if len(ink[0]) == 0:
        return
    y0, y1 = max(ink[0].min() - margin, 0), min(ink[0].max() + margin, a.shape[0])
    x0, x1 = max(ink[1].min() - margin, 0), min(ink[1].max() + margin, a.shape[1])
    im = im.crop((x0, y0, x1, y1))
    t_px, s_px = stamp_sizes(im.width)
    ft, fs = _font(t_px), _font(s_px)
    th = int(round(t_px * 1.7)) if title else 0
    sh = int(round(s_px * 1.7))
    tw = int(ImageDraw.Draw(im).textlength(title, font=ft)) + 24 if title else 0
    sw = int(ImageDraw.Draw(im).textlength(STAMP, font=fs)) + 16
    w = max(im.width, tw, sw)
    out = Image.new("RGB", (w, im.height + th + sh), "white")
    out.paste(im, ((w - im.width) // 2, th))
    d = ImageDraw.Draw(out)
    if title:
        d.text((w // 2, int(t_px * 0.3)), title, fill=(20, 20, 20), font=ft, anchor="mt")
    d.text((w - 8, out.height - int(s_px * 0.3)), STAMP, fill=(140, 25, 25), font=fs, anchor="rd")
    out.save(path, optimize=True)


def view(items, path, elev, azim, size=(12, 7), title=None, tol=0.15, roll=0, max_edge=4.0, notes=()):
    """Orthographic shaded view. notes = [(x, y, z, text), ...] drawn as 3D text labels."""
    fig = plt.figure(figsize=size, dpi=130)
    ax = fig.add_subplot(111, projection="3d", proj_type="ortho")
    ax.view_init(elev=elev, azim=azim, roll=roll)
    lo, hi = draw(ax, items, tol, max_edge=max_edge)
    for x, y, z, t in notes:
        ax.text(x, y, z, t, fontsize=8, color=(0.1, 0.1, 0.1), zorder=10,
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=(0.6, 0.6, 0.6), lw=0.5, alpha=0.9))
    ax.set_xlim(lo[0], hi[0])
    ax.set_ylim(lo[1], hi[1])
    ax.set_zlim(lo[2], hi[2])
    ax.set_box_aspect(tuple(np.maximum(hi - lo, 1e-3)), zoom=1.0)
    ax.set_axis_off()
    fig.subplots_adjust(0, 0, 1, 1)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fig.savefig(path, bbox_inches="tight", pad_inches=0.05, facecolor="white")
    plt.close(fig)
    autocrop(path, title=title)
    print(path)


def face_paths(face, axes):
    """matplotlib Path (even-odd) of a planar face, in the 2 chosen global axes, e.g. ("X", "Z")."""
    verts, codes = [], []
    for w in face.wires():
        pts = []
        for e in w.order_edges() if hasattr(w, "order_edges") else w.edges():
            n = 2 if e.geom_type.name == "LINE" else 24
            for t in np.linspace(0, 1, n):
                p = e.position_at(t)
                pts.append((getattr(p, axes[0]), getattr(p, axes[1])))
        if len(pts) < 3:
            continue
        verts += pts + [pts[0]]
        codes += [Path.MOVETO] + [Path.LINETO] * (len(pts) - 1) + [Path.CLOSEPOLY]
    return Path(verts, codes) if verts else None


def section_plot(items, plane, axes, path, xlim=None, ylim=None, title="", notes=(), arrows=(),
                 size=(9, 6), xlabel=None, ylabel=None):
    """Exact section: cut every solid with `plane` (a build123d Plane) and fill the faces.
    notes = [(x, y, text)], arrows = [(x0, y0, x1, y1, text)] in the two chosen axes (mm)."""
    from build123d import section
    fig, ax = plt.subplots(figsize=size, dpi=140)
    for _name, s, c in items:
        try:
            sec = section(s, plane)
        except Exception:      # noqa: BLE001
            continue
        for f in sec.faces():
            p = face_paths(f, axes)
            if p is not None:
                ax.add_patch(PathPatch(p, facecolor=colour(c), edgecolor="k", lw=0.4))
    ax.set_aspect("equal")
    if xlim:
        ax.set_xlim(*xlim)
    if ylim:
        ax.set_ylim(*ylim)
    if not (xlim and ylim):
        ax.autoscale_view()
    ax.set_xlabel(xlabel or f"{axes[0].lower()} (mm)")
    ax.set_ylabel(ylabel or f"{axes[1].lower()} (mm)")
    ax.set_title(title, fontsize=10)
    ax.grid(True, lw=0.3, alpha=0.5)
    for x, y, t in notes:
        ax.annotate(t, (x, y), fontsize=7, xytext=(6, 6), textcoords="offset points",
                    arrowprops=dict(arrowstyle="-", lw=0.4))
    for x0, y0, x1, y1, t in arrows:
        ax.annotate(t, (x1, y1), xytext=(x0, y0), fontsize=7, color=colour("highlight"),
                    arrowprops=dict(arrowstyle="->", lw=1.0, color=colour("highlight")))
    stamp(fig)
    fig.tight_layout()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    print(path)


def export_glb(items, path, tol=0.2):
    """One binary glTF with a coloured mesh per item (for the 3D gallery), written with trimesh-free plain numpy:
    positions + indices + a flat base colour per mesh, no normals (three.js computes flat shading)."""
    import json
    import struct
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    bin_chunks, buffer_views, accessors, meshes, nodes, materials = [], [], [], [], [], []
    offset = 0
    mat_index = {}

    def add_view(data, target):
        nonlocal offset
        pad = (-len(data)) % 4
        bin_chunks.append(data + b"\x00" * pad)
        buffer_views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(data), "target": target})
        offset += len(data) + pad
        return len(buffer_views) - 1

    for name, s, c in items:
        v, t = mesh(s, tol)
        if len(t) == 0:
            continue
        # glTF is Y-up; the models are Z-up: rotate -90 deg about X
        v = np.stack([v[:, 0], v[:, 2], -v[:, 1]], 1).astype(np.float32) / 1000.0   # mm -> m
        idx = t.astype(np.uint32).ravel()
        pv = add_view(v.tobytes(), 34962)
        iv = add_view(idx.tobytes(), 34963)
        accessors.append({"bufferView": pv, "componentType": 5126, "count": len(v), "type": "VEC3",
                          "min": v.min(0).tolist(), "max": v.max(0).tolist()})
        pa = len(accessors) - 1
        accessors.append({"bufferView": iv, "componentType": 5125, "count": len(idx), "type": "SCALAR"})
        ia = len(accessors) - 1
        key = c if isinstance(c, str) else str(c)
        if key not in mat_index:
            rgb = colour(c).tolist()
            materials.append({"name": key, "pbrMetallicRoughness": {"baseColorFactor": rgb + [1.0],
                                                                     "metallicFactor": 0.1, "roughnessFactor": 0.6}})
            mat_index[key] = len(materials) - 1
        meshes.append({"name": name, "primitives": [{"attributes": {"POSITION": pa}, "indices": ia,
                                                      "material": mat_index[key]}]})
        nodes.append({"name": name, "mesh": len(meshes) - 1})
    gltf = {"asset": {"version": "2.0", "generator": "keyboard/hardware/concept/render_lib.py"},
            "scene": 0, "scenes": [{"nodes": list(range(len(nodes)))}], "nodes": nodes, "meshes": meshes,
            "materials": materials, "accessors": accessors, "bufferViews": buffer_views,
            "buffers": [{"byteLength": offset}]}
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * ((-len(js)) % 4)
    binary = b"".join(bin_chunks)
    out = struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(binary))
    out += struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(binary), 0x004E4942) + binary
    with open(path, "wb") as f:
        f.write(out)
    print(path)
