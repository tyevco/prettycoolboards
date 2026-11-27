"""Readers for a coupon's generated KiCad files, into the small models rules.py checks.

* read_netlist(path): the `kicad-cli sch export netlist` s-expression (build.py writes it) -> Netlist. Parsed with
  the repository's tools/sexpr.py, so it needs no KiCad.
* read_board(path, geometry): the .kicad_pcb, through pcbnew (KiCad 10.0.8) -> Board, in coupon board mm: origin at
  the outline's lower-left corner, +x right, +y up, top view (keyboard/hardware/design/boards/geom.py), which is
  where boards/coupon_common.py puts the slot edge (y = 0).
* load_geometry(): the slot's mechanical contract from keyboard/hardware/design/boards/coupon_common.py (the module
  the motherboard's sockets are placed with too), so a coupon is checked against the same numbers it mates with.

Status: tools for files that exist; nothing here has met hardware.
"""

from __future__ import annotations

import importlib
import math
import os
import re
import sys
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
KEYBOARD = os.path.dirname(os.path.dirname(HERE))
REPO = os.path.dirname(KEYBOARD)
DESIGN = os.path.join(KEYBOARD, "hardware", "design")
KICAD_DIR = os.path.join(KEYBOARD, "hardware", "kicad")
TOOLS = os.path.join(REPO, "tools")

sys.dont_write_bytecode = True       # never leave __pycache__ in the design tree this module imports from
for _p in (TOOLS, DESIGN):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def project_name(board):
    return f"prettycool-keyboard-{board}"       # keyboard/hardware/design/build.py project_name()


def board_files(board, kicad_dir=KICAD_DIR):
    """(netlist path, pcb path) of a generated board; either may not exist yet."""
    d = os.path.join(kicad_dir, board)
    return (os.path.join(d, project_name(board) + ".net"), os.path.join(d, project_name(board) + ".kicad_pcb"))


# ------------------------------------------------------------------------------------------------------- netlist
@dataclass
class Comp:
    ref: str
    value: str = ""
    footprint: str = ""
    lib: str = ""
    part: str = ""
    fields: dict = field(default_factory=dict)
    pins: dict = field(default_factory=dict)          # pin number -> (name, electrical type)

    @property
    def prefix(self):
        m = re.match(r"[A-Za-z#]+", self.ref)
        return m.group(0).upper() if m else ""

    @property
    def dnp(self):
        """Do not populate: KiCad 10's netlist writes `(property (name "dnp"))` for a symbol marked DNP. The part
        is on the schematic and in the nets, but not fitted on the assembled board."""
        return any(k.lower() == "dnp" for k in self.fields)

    def pin_by_name(self, *names):
        """The first pin whose (normalised) name is one of `names`."""
        want = {n.upper() for n in names}
        for num, (name, _t) in self.pins.items():
            if pin_name(name).upper() in want:
                return num
        return None


def pin_name(name):
    """'~{WC}' -> 'WC', 'SDA/OUT1' stays; KiCad's overbar markup removed."""
    return re.sub(r"~\{([^}]*)\}", r"\1", name or "").strip()


@dataclass
class Netlist:
    path: str
    comps: dict                                       # ref -> Comp
    nets: dict                                        # net name -> [(ref, pin)]
    pin_type: dict = field(default_factory=dict)      # (ref, pin) -> electrical type

    def __post_init__(self):
        self.pin_net = {m: n for n, mem in self.nets.items() for m in mem}

    def net_of(self, ref, pin):
        """The net on a pin, or None if the pin is not connected (KiCad's 'unconnected-(...)' or no net)."""
        n = self.pin_net.get((ref, str(pin)))
        if n is None or is_unconnected_name(n):
            return None
        return n

    def members(self, net):
        return list(self.nets.get(net, []))

    def others(self, net, exclude_refs=()):
        return [(r, p) for r, p in self.nets.get(net, []) if r not in exclude_refs]

    def fitted(self, ref):
        """True unless the part is marked DNP (an unknown ref counts as fitted)."""
        c = self.comps.get(ref)
        return c is None or not c.dnp

    def find_net(self, base):
        """The net named `base`, globally or as a sheet-local '/.../base' (None if absent or ambiguous)."""
        if base in self.nets:
            return base
        hits = [n for n in self.nets if net_base(n) == base]
        return hits[0] if len(hits) == 1 else None


def is_unconnected_name(name):
    return not name or name.startswith("unconnected-")


def net_base(name):
    """'/Sheet name/AN0' -> 'AN0' (a sheet-local label's name); global names unchanged."""
    return name.rsplit("/", 1)[-1] if name and name.startswith("/") else name


def read_netlist(path):
    import sexpr
    from sexpr import find, find_all

    with open(path, encoding="utf-8") as fh:
        root = sexpr.parse(fh.read())

    def val(node, key, default=""):
        x = find(node, key)
        return str(x[1]) if x and len(x) > 1 else default

    libparts = {}
    lp_root = find(root, "libparts")
    for lp in find_all(lp_root, "libpart") if lp_root else []:
        pins = {}
        pr = find(lp, "pins")
        for pn in find_all(pr, "pin") if pr else []:
            pins[val(pn, "num")] = (val(pn, "name"), val(pn, "type"))
        libparts[(val(lp, "lib"), val(lp, "part"))] = pins
    comps = {}
    for c in find_all(find(root, "components"), "comp"):
        ref = val(c, "ref")
        ls = find(c, "libsource")
        lib, part = (val(ls, "lib"), val(ls, "part")) if ls else ("", "")
        flds = find(c, "fields")
        fields = {str(find(f, "name")[1]): (str(f[2]) if len(f) > 2 else "") for f in find_all(flds, "field")} \
            if flds else {}
        for p in find_all(c, "property"):
            fields.setdefault(val(p, "name"), val(p, "value"))
        comps[ref] = Comp(ref, val(c, "value"), val(c, "footprint"), lib, part, fields,
                          dict(libparts.get((lib, part), {})))
    nets, ptype = {}, {}
    for n in find_all(find(root, "nets"), "net"):
        name = val(n, "name")
        mem = []
        for nd in find_all(n, "node"):
            ref, pin = val(nd, "ref"), val(nd, "pin")
            mem.append((ref, pin))
            ptype[(ref, pin)] = val(nd, "pintype")
            pf = val(nd, "pinfunction")
            if ref in comps and pin not in comps[ref].pins and pf:
                # no libpart pin table: KiCad 10 writes pinfunction as '<name>_<number>' for some symbols
                nm = pf[:-(len(pin) + 1)] if pf.endswith("_" + pin) else pf
                comps[ref].pins[pin] = (nm, val(nd, "pintype"))
        nets[name] = mem
    return Netlist(path, comps, nets, ptype)


# ---------------------------------------------------------------------------------------------------- geometry
@dataclass
class Geometry:
    """The slot's mechanical contract (boards/coupon_common.py)."""
    sizes: dict                                       # size class -> (w, h) mm
    header_fpid: str
    header_side: str                                  # 'B': the coupon's header is on the bottom
    pin_xy: object                                    # n -> (x, y) board mm
    post: tuple                                       # (x, y)
    post_drill: float
    post_copper_r: float
    post_part_r: float
    keepouts: object                                  # size -> [(side, predicate(x, y))]
    source: str = ""
    corner_r: float = 0.0


def load_geometry():
    """Geometry from keyboard/hardware/design/boards/coupon_common.py (needs pcbnew: that module imports it)."""
    cc = importlib.import_module("boards.coupon_common")
    return Geometry(sizes={"standard": tuple(cc.STANDARD), "wide": tuple(cc.WIDE)}, header_fpid=cc.HEADER_FP,
                    header_side="B", pin_xy=cc.pin_xy, post=tuple(cc.POST), post_drill=cc.POST_DRILL,
                    post_copper_r=cc.POST_COPPER_R, post_part_r=cc.POST_PART_R,
                    keepouts=lambda size: cc.keepouts(size), source=os.path.relpath(cc.__file__, REPO),
                    corner_r=getattr(cc, "CORNER_R", 0.0))


# --------------------------------------------------------------------------------------------------------- board
@dataclass
class Pad:
    number: str
    net: str                                          # '' or 'unconnected-(...)' when not connected
    x: float
    y: float
    drill: float                                      # mm, 0 for SMD
    npth: bool = False


@dataclass
class Footprint:
    ref: str
    fpid: str
    x: float
    y: float
    rot: float
    side: str                                         # 'F' or 'B'
    pads: list
    courtyard: list = field(default_factory=list)     # [[(x, y), ...], ...] board mm
    has_courtyard: bool = True


@dataclass
class Board:
    path: str
    outline: list                                     # [(x, y)] board mm, closed polygon
    outline_ok: bool
    width: float
    height: float
    copper_layers: int
    thickness: float
    footprints: dict                                  # ref -> Footprint
    aux_origin: tuple = (0.0, 0.0)                    # board mm
    post_copper: list = field(default_factory=list)   # [(distance mm, layer, what)] copper nearest the post
    gnd_plane: dict = field(default_factory=dict)     # layer -> fraction of the board area filled with GND
    unrouted: int = -1                                # pcbnew's unconnected count (-1: not computed)


def _poly_points(chain, to_board):
    return [to_board(chain.CPoint(i).x, chain.CPoint(i).y) for i in range(chain.PointCount())]


def read_board(path, geometry=None):
    """Load a .kicad_pcb with pcbnew. With a geometry, also measure the copper around its support post."""
    import pcbnew

    b = pcbnew.LoadBoard(path)
    ps = pcbnew.SHAPE_POLY_SET()
    ok = bool(b.GetBoardPolygonOutlines(ps, False)) and ps.OutlineCount() == 1
    TO = pcbnew.ToMM
    if ps.OutlineCount():
        raw = [(TO(ps.Outline(0).CPoint(i).x), TO(ps.Outline(0).CPoint(i).y))
               for i in range(ps.Outline(0).PointCount())]
    else:
        raw = []
    X0 = min((p[0] for p in raw), default=0.0)
    Y0 = max((p[1] for p in raw), default=0.0)

    def to_board(X, Y):                               # internal units (nm) -> coupon board mm
        return (round(TO(X) - X0, 4), round(Y0 - TO(Y), 4))

    outline = [(round(x - X0, 4), round(Y0 - y, 4)) for x, y in raw]
    w = max((p[0] for p in outline), default=0.0)
    h = max((p[1] for p in outline), default=0.0)
    fps = {}
    for fp in b.GetFootprints():
        side = "B" if fp.IsFlipped() else "F"
        pads = []
        for p in fp.Pads():
            x, y = to_board(p.GetPosition().x, p.GetPosition().y)
            drill = TO(p.GetDrillSize().x) if p.HasHole() else 0.0
            pads.append(Pad(str(p.GetNumber()), p.GetNetname(), x, y, round(drill, 4),
                            p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH))
        cy = fp.GetCourtyard(pcbnew.B_CrtYd if side == "B" else pcbnew.F_CrtYd)
        polys = [_poly_points(cy.Outline(i), to_board) for i in range(cy.OutlineCount())]
        has_cy = bool(polys)
        if not polys:                                 # no courtyard: the footprint's bounding box instead
            bb = fp.GetBoundingBox(False)
            x0, y0 = to_board(bb.GetLeft(), bb.GetBottom())
            x1, y1 = to_board(bb.GetRight(), bb.GetTop())
            polys = [[(x0, y0), (x1, y0), (x1, y1), (x0, y1)]]
        x, y = to_board(fp.GetPosition().x, fp.GetPosition().y)
        fps[fp.GetReference()] = Footprint(fp.GetReference(), fp.GetFPIDAsString(), x, y,
                                           round(fp.GetOrientationDegrees(), 3), side, pads, polys, has_cy)
    ds = b.GetDesignSettings()
    aux = to_board(ds.GetAuxOrigin().x, ds.GetAuxOrigin().y)
    board = Board(path, outline, ok, round(w, 4), round(h, 4), b.GetCopperLayerCount(),
                  round(TO(ds.GetBoardThickness()), 3), fps, aux)

    # GND fill on the inner layers (SPEC §2: analog coupons want a solid ground layer; §4.9 lanes over ground)
    area = ps.Area() if ps.OutlineCount() else 0.0
    for z in b.Zones():
        if z.GetIsRuleArea() or z.GetNetname() != "GND":
            continue
        for layer in z.GetLayerSet().Seq():
            name = b.GetLayerName(layer)
            if name.startswith("In") and area:
                filled = z.GetFilledPolysList(layer).Area()
                board.gnd_plane[name] = max(board.gnd_plane.get(name, 0.0), filled / area)

    if geometry is not None:
        px, py = geometry.post
        centre = pcbnew.VECTOR2I(pcbnew.FromMM(px + X0), pcbnew.FromMM(Y0 - py))
        found = []
        probe_r = pcbnew.FromMM(geometry.post_copper_r + 2.0)

        def dist_item(shape):
            # binary search on Collide(): the distance from the post centre to the shape, to 1 um
            if not shape.Collide(pcbnew.SHAPE_CIRCLE(centre, probe_r), 0):
                return None
            lo, hi = 0, probe_r
            while hi - lo > 1000:
                mid = (lo + hi) // 2
                if shape.Collide(pcbnew.SHAPE_CIRCLE(centre, max(mid, 1)), 0):
                    hi = mid
                else:
                    lo = mid
            return TO(hi)

        for t in b.GetTracks():
            for layer in t.GetLayerSet().CuStack():
                d = dist_item(t.GetEffectiveShape(layer))
                if d is not None:
                    kind = "via" if t.GetClass() == "PCB_VIA" else "track"
                    found.append((d, b.GetLayerName(layer), f"{kind} on {t.GetNetname() or 'no net'}"))
        post_refs = {r for r, f in fps.items()
                     if any(p.drill and math.hypot(p.x - px, p.y - py) < 0.5 for p in f.pads)}
        for fp in b.GetFootprints():
            if fp.GetReference() in post_refs:
                continue
            for p in fp.Pads():
                for layer in p.GetLayerSet().CuStack():
                    d = dist_item(p.GetEffectiveShape(layer))
                    if d is not None:
                        found.append((d, b.GetLayerName(layer), f"pad {fp.GetReference()}.{p.GetNumber()}"))
        for z in b.Zones():
            if z.GetIsRuleArea():
                continue
            for layer in z.GetLayerSet().Seq():
                fill = z.GetFilledPolysList(layer)
                if fill.OutlineCount() == 0:
                    continue
                if not fill.Collide(centre, probe_r):
                    continue
                lo, hi = 0, probe_r
                while hi - lo > 1000:
                    mid = (lo + hi) // 2
                    if fill.Collide(centre, max(mid, 1)):
                        hi = mid
                    else:
                        lo = mid
                found.append((TO(hi), b.GetLayerName(layer), f"zone {z.GetZoneName() or z.GetNetname()} fill"))
        board.post_copper = sorted(found)
    try:
        b.BuildConnectivity()
        board.unrouted = b.GetConnectivity().GetUnconnectedCount(False)
    except Exception:                                 # noqa: BLE001 - an optional report, never a gate
        board.unrouted = -1
    return board


# --------------------------------------------------------------------------------------------------- polygons
def inside(x, y, pts):
    c = False
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            c = not c
    return c


def sample_polygon(pts, step=0.1):
    """Points along a closed polygon's edges, every `step` mm, vertices included."""
    out = []
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        k = max(1, int(math.hypot(x1 - x0, y1 - y0) / step))
        out += [(x0 + (x1 - x0) * j / k, y0 + (y1 - y0) * j / k) for j in range(k)]
    return out


def dist_to_polygon(x, y, pts):
    """Distance from a point to a closed polygon (0 if inside)."""
    if pts and inside(x, y, pts):
        return 0.0
    best = float("inf")
    n = len(pts)
    for i in range(n):
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % n]
        dx, dy = bx - ax, by - ay
        L = dx * dx + dy * dy
        t = 0.0 if L == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / L))
        best = min(best, math.hypot(x - ax - t * dx, y - ay - t * dy))
    return best
