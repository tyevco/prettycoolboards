"""Schematic placement + orthogonal wire routing for schgen: draw the circuit the way a person would.

The rule this module exists for (tools/README.md, "Wiring rule"): connected pins are joined by WIRES, so a reader
traces a connection by eye. Labels are only used for nets that leave the sheet (one global label per cluster),
as a name tag on an already-wired local net, and power symbols for power nets.

Pipeline, per sheet:
  1. Clusters. Every schgen group is a cluster; groups that share a local net are merged (a local net is never
     split across clusters, so it can always be wired), and a 1-2 pin part whose only signal net touches exactly
     one multi-pin part on the sheet moves into that part's cluster (pull-ups, test points: R4).
  2. Placement. The cluster's anchor (hint or the multi-pin part with most connected pins) is placed first. Each
     anchor pin gets a "block": a horizontal spine running away from the pin that carries the pin's satellites:
     shunts to a power net hang off it (pull-ups above, pull-downs / caps / switches below, power symbol right on
     the far pin), test points sit on it, a series part continues it (chains: dividers, RC filters, jumper +
     resistor), a multi-pin part met on the way becomes a sub-anchor with its own blocks, and it ends in the global
     label (intersheet net), a power symbol (decoupling: the caps are on the spine of the pin they serve, R2) or
     nothing. Local nets carry one local label as a name tag, on the wire. Blocks are stacked per side on their
     pin's row: a block that reaches into a neighbouring row (a test point, a pull-up) moves outward along its
     own wire until it clears the neighbours, and a test point may hang below the wire instead of above
     (stagger_side). Only when that would take more than STAGGER_LIMIT does the side fan out (fit_rows: exact,
     on the grid, few blocks moved). An up and a down shunt never share a spine point (no 4-way junctions), a
     power symbol on a sideways pin sits on a short stub, and the anchor's Reference/Value text is re-placed
     clear of its blocks and of the jog wires (place_fields).
     Parts bridging two placed nets (feedback R/C, a buck-boost inductor) are placed last, near both ends.
  3. Routing. Every connection is a wire drawn by a grid maze router (1.27 mm grid, Dijkstra with bend/crossing
     costs): no wire enters a symbol body, a text box or a foreign pin; a foreign wire may only be crossed
     straight at right angles (never at one of its corners/ends, which would connect it); wires leave pins
     straight where they can. Wires are split at every T so all connections are end-to-end, and a junction dot is
     added wherever 3+ wire ends / pins meet.

Nothing here falls back to a label: a connection that cannot be routed is reported as an error, and
schgen.Design.check() fails the build (R5).
"""

from __future__ import annotations

import heapq
import math

import symlib
from sexpr import find_all

G = 1.27            # routing / placement grid, mm
CW = 1.27           # advance of one 1.27 mm glyph (KiCad stroke font, capitals; conservative), mm
TH = 1.27           # text height, mm
CLR = 0.9           # minimum clearance between placed boxes, mm
DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1))
UNASSIGNED = "__UNASSIGNED__"


def sn(v: float) -> float:
    return round(round(v / G) * G, 4)


def gi(v: float) -> int:
    return int(round(v / G))


def _rot(u, v, r):
    c, s = round(math.cos(math.radians(r))), round(math.sin(math.radians(r)))
    return (u * c + v * s, -u * s + v * c)


def text_w(s: str) -> float:
    return max(1, len(s)) * CW


def gnd_like(net: str) -> bool:
    return "GND" in net.upper() or net.upper() in ("VSS", "0V")


# ---------------------------------------------------------------------------------------------- boxes

class Box:
    __slots__ = ("x0", "y0", "x1", "y1", "kind")

    def __init__(self, x0, y0, x1, y1, kind="body"):
        self.x0, self.x1 = (x0, x1) if x0 <= x1 else (x1, x0)
        self.y0, self.y1 = (y0, y1) if y0 <= y1 else (y1, y0)
        self.kind = kind

    def moved(self, dx, dy):
        return Box(self.x0 + dx, self.y0 + dy, self.x1 + dx, self.y1 + dy, self.kind)

    def hits(self, o, clr=CLR):
        return self.x0 < o.x1 + clr and o.x0 < self.x1 + clr and self.y0 < o.y1 + clr and o.y0 < self.y1 + clr

    def __repr__(self):
        return f"Box({self.x0:.2f},{self.y0:.2f},{self.x1:.2f},{self.y1:.2f},{self.kind})"


def bbox_of(boxes):
    boxes = list(boxes)
    if not boxes:
        return Box(0, 0, 0, 0)
    return Box(min(b.x0 for b in boxes), min(b.y0 for b in boxes), max(b.x1 for b in boxes), max(b.y1 for b in boxes))


class BoxIndex:
    """Bucketed boxes for fast overlap queries."""

    def __init__(self, boxes=(), cell=10.0):
        self.cell = cell
        self.b = {}
        for bx in boxes:
            self.add(bx)

    def _keys(self, bx):
        c = self.cell
        for i in range(int(math.floor((bx.x0 - CLR) / c)), int(math.floor((bx.x1 + CLR) / c)) + 1):
            for j in range(int(math.floor((bx.y0 - CLR) / c)), int(math.floor((bx.y1 + CLR) / c)) + 1):
                yield (i, j)

    def add(self, bx):
        for k in self._keys(bx):
            self.b.setdefault(k, []).append(bx)

    def hits(self, bx, clr=CLR):
        for k in self._keys(bx):
            for o in self.b.get(k, ()):
                if bx.hits(o, clr):
                    return True
        return False


# ---------------------------------------------------------------------------------------------- symbol geometry

class Slot:
    """One connection point of a symbol unit (stacked pins at one location share a slot)."""

    def __init__(self, idx, pin):
        self.idx = idx
        self.pins = [pin]
        self.sx, self.sy = pin.x, -pin.y                       # screen coords (y down), unrotated
        a = math.radians(pin.angle)
        self.ox, self.oy = round(-math.cos(a)), round(math.sin(a))   # outward (away from body), screen
        self.length = pin.length
        self.number = self.name = self.etype = ""


class Geo:
    def __init__(self, lib_id, unit):
        sym = symlib.get(lib_id)
        self.sym = sym
        self.slots: list[Slot] = []
        loc = {}
        for pin in sym.pins_for_unit(unit):
            k = (pin.x, pin.y)
            if k in loc:
                loc[k].pins.append(pin)
                continue
            s = Slot(len(self.slots), pin)
            loc[k] = s
            self.slots.append(s)
        for s in self.slots:
            rep = next((p for p in s.pins if not p.hidden), s.pins[0])
            s.number, s.name, s.etype = rep.number, rep.name, rep.etype
        pts = []
        for u in find_all(sym.sexp, "symbol"):
            try:
                un = int(str(u[1]).rsplit("_", 2)[-2])
            except ValueError:
                continue
            if un not in (0, unit):
                continue
            for g in u[2:]:
                if not isinstance(g, list) or g[0] not in ("rectangle", "polyline", "circle", "arc", "bezier", "text"):
                    continue
                if g[0] == "circle":
                    c = _sub(g, "center")
                    r = float(_sub(g, "radius")[1])
                    pts += [(float(c[1]) - r, float(c[2]) - r), (float(c[1]) + r, float(c[2]) + r)]
                    continue
                for key in ("start", "end", "mid", "at"):
                    p = _sub(g, key)
                    if p:
                        pts.append((float(p[1]), float(p[2])))
                pp = _sub(g, "pts")
                if pp:
                    pts += [(float(xy[1]), float(xy[2])) for xy in pp[1:]]
        if not pts:
            for s in self.slots:
                pts.append((s.sx - s.ox * s.length, -(s.sy - s.oy * s.length)))
        if not pts:
            pts = [(-0.6, -0.6), (0.6, 0.6)]
        xs = [p[0] for p in pts]
        ys = [-p[1] for p in pts]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        if x1 - x0 < 0.6:
            x0, x1 = (x0 + x1) / 2 - 0.3, (x0 + x1) / 2 + 0.3
        if y1 - y0 < 0.6:
            y0, y1 = (y0 + y1) / 2 - 0.3, (y0 + y1) / 2 + 0.3
        self.body = Box(x0, y0, x1, y1)


def _sub(node, head):
    for x in node:
        if isinstance(x, list) and x and x[0] == head:
            return x
    return None


_GEO: dict = {}


def geo(lib_id, unit) -> Geo:
    k = (lib_id, unit)
    if k not in _GEO:
        _GEO[k] = Geo(lib_id, unit)
    return _GEO[k]


def is_anchor_part(p) -> bool:
    """Parts that anchor a cluster: 3+ connection points, or a unit of a multi-unit IC (op-amp power unit)."""
    g = geo(p.lib_id, p.unit)
    return len(g.slots) >= 3 or (g.sym.unit_count > 1 and len(g.slots) >= 1)


def net_of(part, slot):
    for pin in slot.pins:
        for k in (pin.number, pin.name):
            if k in part.pins:
                return part.pins[k]
    return UNASSIGNED


# ---------------------------------------------------------------------------------------------- placed items

class Item:
    x = 0.0
    y = 0.0

    def move(self, dx, dy):
        self.x = round(self.x + dx, 4)
        self.y = round(self.y + dy, 4)


class PSym(Item):
    """A placed part (one unit)."""
    kind = "sym"

    def __init__(self, part, rot=0, mirror=False, text_side=1):
        self.part = part
        self.g = geo(part.lib_id, part.unit)
        self.rot, self.mirror = rot, mirror
        self.text_side = text_side
        self.x = self.y = 0.0
        self.nets = [net_of(part, s) for s in self.g.slots]
        self.fields = None
        self.layout_fields()

    def tf(self, u, v):
        if self.mirror:
            u = -u
        return _rot(u, v, self.rot)

    def tip_rel(self, i):
        s = self.g.slots[i]
        u, v = self.tf(s.sx, s.sy)
        return (round(u, 4), round(v, 4))

    def tip(self, i):
        u, v = self.tip_rel(i)
        return (round(self.x + u, 4), round(self.y + v, 4))

    def out(self, i):
        s = self.g.slots[i]
        u, v = self.tf(s.ox, s.oy)
        return (int(round(u)), int(round(v)))

    def body_rel(self):
        b = self.g.body
        pts = [self.tf(x, y) for x, y in ((b.x0, b.y0), (b.x1, b.y1))]
        return Box(pts[0][0], pts[0][1], pts[1][0], pts[1][1])

    def body(self):
        return self.body_rel().moved(self.x, self.y)

    def pinlines(self):
        out = []
        for i, s in enumerate(self.g.slots):
            tx, ty = self.tip(i)
            ox, oy = self.out(i)
            ix, iy = tx - ox * s.length, ty - oy * s.length
            out.append((tx, ty, ix, iy))
        return out

    def side(self, i):
        return {(-1, 0): "L", (1, 0): "R", (0, -1): "T", (0, 1): "B"}[self.out(i)]

    def nslots(self):
        return len(self.g.slots)

    # -- fields
    def layout_fields(self):
        """Reference / Value positions relative to the origin: list of (name, dx, dy, hjust)."""
        self.fields = next(f for ok, f in self.field_candidates() if ok)

    def field_candidates(self):
        """[(usable, fields)] in order of preference; fields = [(name, dx, dy, hjust)]."""
        p = self.part
        b = self.body_rel()
        n = self.nslots()
        ref, val = p.ref, p.value
        w = max(text_w(ref), text_w(val))
        cx = (b.x0 + b.x1) / 2
        cy = (b.y0 + b.y1) / 2
        outs = [self.out(i) for i in range(n)]
        if n == 2 and all(o[1] == 0 for o in outs) and outs[0] != outs[1]:      # horizontal 2-pin
            top = b.y0
            return [(True, [("Reference", cx, top - 1.5, "center"), ("Value", cx, b.y1 + 1.5, "center")])]
        elif n <= 2 and (n == 0 or all(o[0] == 0 for o in outs) or n == 1 or outs[0] == outs[-1]):
            if self.text_side >= 0:
                x, j = b.x1 + 0.9, "left"
            else:
                x, j = b.x0 - 0.9, "right"
            return [(True, [("Reference", x, cy - 1.0, j), ("Value", x, cy + 1.0, j)])]
        else:
            tops = [self.tip_rel(i)[0] for i in range(n) if outs[i] == (0, -1)]
            bots = [self.tip_rel(i)[0] for i in range(n) if outs[i] == (0, 1)]
            lefts = [i for i in range(n) if outs[i] == (-1, 0)]
            rights = [i for i in range(n) if outs[i] == (1, 0)]

            def clear(xs, a, c):
                return all(not (a - 1.3 <= x <= c + 1.3) for x in xs)
            y_ref, y_val = b.y0 - 3.0, b.y0 - 1.25
            cands = []
            cands.append((clear(tops, b.x0, b.x0 + w), [("Reference", b.x0, y_ref, "left"), ("Value", b.x0, y_val, "left")]))
            cands.append((clear(tops, b.x1 - w, b.x1), [("Reference", b.x1, y_ref, "right"), ("Value", b.x1, y_val, "right")]))
            if tops:
                xr = max(tops) + 2.54
                cands.append((True, [("Reference", xr, y_ref, "left"), ("Value", xr, y_val, "left")]))
            cands.append((not rights, [("Reference", b.x1 + 1.0, cy - 1.0, "left"), ("Value", b.x1 + 1.0, cy + 1.0, "left")]))
            cands.append((clear(bots, b.x0, b.x0 + w), [("Reference", b.x0, b.y1 + 1.25, "left"), ("Value", b.x0, b.y1 + 3.0, "left")]))
            cands.append((not lefts, [("Reference", b.x0 - 1.0, cy - 1.0, "right"), ("Value", b.x0 - 1.0, cy + 1.0, "right")]))
            # beside the bottom / top pins (Cluster.place_fields uses these when the blocks crowd the others)
            y_r2, y_v2 = b.y1 + 1.25, b.y1 + 3.0
            if bots:
                cands.append((True, [("Reference", max(bots) + 2.54, y_r2, "left"), ("Value", max(bots) + 2.54, y_v2, "left")]))
                cands.append((True, [("Reference", min(bots) - 2.54, y_r2, "right"), ("Value", min(bots) - 2.54, y_v2, "right")]))
            else:
                cands.append((True, [("Reference", b.x1, y_r2, "right"), ("Value", b.x1, y_v2, "right")]))
            if tops:
                cands.append((True, [("Reference", min(tops) - 2.54, y_ref, "right"), ("Value", min(tops) - 2.54, y_val, "right")]))
            cands.append((True, [("Reference", b.x0 - 1.3, y_ref, "right"), ("Value", b.x0 - 1.3, y_val, "right")]))
            return cands

    def field_boxes(self):
        out = []
        for name, dx, dy, j in self.fields:
            s = self.part.ref if name == "Reference" else self.part.value
            w = text_w(s)
            x = self.x + dx
            x0 = x if j == "left" else x - w if j == "right" else x - w / 2
            out.append(Box(x0, self.y + dy - 0.8, x0 + w, self.y + dy + 0.8, "text"))
        return out

    def boxes(self):
        out = [self.body()]
        for tx, ty, ix, iy in self.pinlines():
            # the pin line, excluding the tip itself
            ox, oy = (ix - tx), (iy - ty)
            ln = math.hypot(ox, oy) or 1
            sx, sy = tx + ox / ln * 0.6, ty + oy / ln * 0.6
            out.append(Box(min(sx, ix), min(sy, iy), max(sx, ix), max(sy, iy), "pin"))
        return out + self.field_boxes()


class PPow(Item):
    """A power symbol. `body` is the screen direction from its pin into its graphic."""
    kind = "pow"

    def __init__(self, net, lib_id, x, y, body=(0, -1)):
        self.net, self.lib_id = net, lib_id
        self.x, self.y = x, y
        self.bdir = body

    def tip(self, i=0):
        return (self.x, self.y)

    def boxes(self):
        bx, by = self.bdir
        w = text_w(self.net)
        if by != 0:
            body = Box(self.x - 1.3, self.y + by * 0.4, self.x + 1.3, self.y + by * 2.6)
            ty = self.y + by * 3.9
            txt = Box(self.x - w / 2, ty - 0.8, self.x + w / 2, ty + 0.8, "text")
        else:
            body = Box(self.x + bx * 0.4, self.y - 1.05, self.x + bx * 2.6, self.y + 1.05)
            tx = self.x + bx * 3.3
            txt = Box(tx, self.y - 0.8, tx + bx * w, self.y + 0.8, "text")
        return [body, txt]


class PLabel(Item):
    """A global label (kind 'global') or a local name tag (kind 'local'). `d` = direction the text runs."""
    kind = "label"

    def __init__(self, net, x, y, d, scope, shape="passive"):
        self.net, self.x, self.y, self.d, self.scope, self.shape = net, x, y, d, scope, shape

    def length(self):
        return text_w(self.net) + (3.2 if self.scope == "global" else 0.8)

    def tip(self, i=0):
        return (self.x, self.y)

    def boxes(self):
        L = self.length()
        dx, dy = self.d
        if self.scope == "global":
            if dy == 0:
                return [Box(self.x + dx * 0.5, self.y - 1.0, self.x + dx * L, self.y + 1.0, "text")]
            return [Box(self.x - 1.0, self.y + dy * 0.5, self.x + 1.0, self.y + dy * L, "text")]
        if dy == 0:     # text sits on top of the wire
            return [Box(self.x + dx * 0.4, self.y - 1.9, self.x + dx * L, self.y - 0.35, "text")]
        return [Box(self.x - 1.9, self.y + dy * 0.4, self.x - 0.35, self.y + dy * L, "text")]


class PNC(Item):
    kind = "nc"

    def __init__(self, x, y):
        self.x, self.y = x, y

    def boxes(self):
        return [Box(self.x - 0.6, self.y - 0.6, self.x + 0.6, self.y + 0.6, "nc")]


class Term:
    """A connection point of a routing group: (item, slot)."""
    __slots__ = ("item", "slot")

    def __init__(self, item, slot=0):
        self.item, self.slot = item, slot

    def point(self):
        return self.item.tip(self.slot)

    def is_pin(self):
        return self.item.kind in ("sym", "pow")

    def arrivals(self):
        """{move direction into this point: extra cost}, and the sides already used by the item."""
        it = self.item
        if it.kind == "sym":
            ox, oy = it.out(self.slot)
            perp = 1.0 if it.nslots() <= 2 else 6.0
            return {(-ox, -oy): 0.0, (oy, ox): perp, (-oy, -ox): perp}, {(-ox, -oy)}
        if it.kind == "pow":
            bx, by = it.bdir
            return {(bx, by): 0.0, (by, bx): 0.2, (-by, -bx): 0.2}, {(bx, by)}
        dx, dy = it.d
        if it.scope == "global":
            return {(dx, dy): 0.0}, {(dx, dy)}
        return {(dx, dy): 0.0, (-dx, -dy): 0.0}, set()


class Block:
    """A rigid set of placed items plus their connection groups."""

    def __init__(self):
        self.items: list = []
        self.conns: dict = {}          # group key -> [Term]
        self.extra: list[Box] = []     # reserved areas (spine wires, lanes)

    def add(self, it):
        self.items.append(it)
        return it

    def term(self, key, item, slot=0):
        self.conns.setdefault(key, []).append(Term(item, slot))

    def merge(self, o):
        self.items += o.items
        for k, v in o.conns.items():
            self.conns.setdefault(k, []).extend(v)
        self.extra += o.extra

    def move(self, dx, dy):
        dx, dy = sn(dx), sn(dy)
        for it in self.items:
            it.move(dx, dy)
        self.extra = [b.moved(dx, dy) for b in self.extra]

    def boxes(self):
        out = list(self.extra)
        for it in self.items:
            out += it.boxes()
        return out

    def bbox(self):
        return bbox_of(self.boxes())


def fit_rows(rows):
    """Rows for the blocks stacked on one side of a part. rows: [want_y, top, bottom] in pin order (top to
    bottom), top/bottom = the block's extent above/below its spine (multiples of G). Block k must sit at least
    bottom[k-1] + top[k] below block k-1.

    Exact on the G grid (dynamic programming, no rounding): minimises the weighted distance from each block's
    pin row plus a fixed cost per moved block. Small blocks (a label, a power symbol) are heavy, so they stay on
    their pin's row and the tall blocks give way; few blocks move, and a moved block moves as little as the
    neighbours allow. Returns the y of each block."""
    if not rows:
        return []
    W = [gi(r[0]) for r in rows]
    T = [int(round(r[1] / G)) for r in rows]
    B = [int(round(r[2] / G)) for r in rows]
    small = [T[k] + B[k] <= 2 for k in range(len(rows))]
    wt = [2.0 if s else 1.0 for s in small]
    pen = [12.0 if s else 6.0 for s in small]
    span = sum(T) + sum(B) + 2
    lo, hi = min(W) - span, max(W) + span
    n = hi - lo + 1
    INF = float("inf")
    C = [wt[0] * abs(lo + y - W[0]) + (pen[0] if lo + y != W[0] else 0.0) for y in range(n)]
    back = []
    for k in range(1, len(rows)):
        gap = B[k - 1] + T[k]
        pm, pa = [INF] * n, [-1] * n          # prefix minimum of C (and where) over y' <= y
        best, arg = INF, -1
        for y in range(n):
            if C[y] < best:
                best, arg = C[y], y
            pm[y], pa[y] = best, arg
        C2, bk = [INF] * n, [-1] * n
        for y in range(n):
            yp = y - gap
            if yp < 0 or pm[yp] == INF:
                continue
            Y = lo + y
            C2[y] = pm[yp] + wt[k] * abs(Y - W[k]) + (pen[k] if Y != W[k] else 0.0)
            bk[y] = pa[yp]
        C = C2
        back.append(bk)
    y = min(range(n), key=lambda v: (C[v], abs(lo + v - W[-1])))
    ys = [y]
    for bk in reversed(back):
        y = bk[y]
        ys.append(y)
    ys.reverse()
    return [round((lo + v) * G, 4) for v in ys]


def find_free(index: BoxIndex, blk: Block, cands, clr=CLR):
    """First offset in `cands` at which none of blk's boxes hit the index. Returns (dx, dy) or None."""
    boxes = blk.boxes()
    for dx, dy in cands:
        if not any(index.hits(b.moved(dx, dy), clr) for b in boxes):
            return dx, dy
    return None


def offsets(dirs, n=48, wx=1.0, wy=1.0):
    """Grid offsets sorted by weighted distance. dirs: allowed (sx, sy) sign sets, e.g. ((0,1),(-1,0,1))."""
    xs, ys = dirs
    out = []
    for i in range(n):
        for j in range(n):
            for sx in xs:
                for sy in ys:
                    if (i == 0 and sx != xs[0]) or (j == 0 and sy != ys[0]):
                        continue
                    if (sx == 0 and i) or (sy == 0 and j):
                        continue
                    out.append((wx * i + wy * j, sx * i * G, sy * j * G))
    out.sort(key=lambda t: (t[0], abs(t[2]), abs(t[1])))
    seen, res = set(), []
    for _, dx, dy in out:
        k = (round(dx, 3), round(dy, 3))
        if k not in seen:
            seen.add(k)
            res.append(k)
    return res


# ---------------------------------------------------------------------------------------------- cluster planning

class SheetNets:
    def __init__(self, design, sheet):
        self.d = design
        self.power = design.power_nets
        ns = design.net_sheets()
        forced = getattr(design, "intersheet", set())
        self.glob = {n for n, s in ns.items() if len(s) > 1} | set(forced)
        self.shapes = design.net_shapes

    def kind(self, net):
        if net in self.power:
            return "P"
        if net in self.glob:
            return "G"
        return "L"


def pid(p):
    return (p.ref, p.unit)


class Cluster:
    """Places one cluster. parts: list of schgen.Part; groups: list of schgen.Group (headers)."""

    def __init__(self, sheet, parts, groups, nets: SheetNets, anchor_hint=None, force_labels=()):
        self.sheet = sheet
        self.parts = parts
        self.groups = groups
        self.nets = nets
        self.anchor_hint = anchor_hint
        self.force_labels = set(force_labels)
        self.claimed: set = set()
        self.label_done: set = set()
        self.tag_done: set = set()
        self.bridges: list = []
        self.pk = 0
        self.slots = {}
        self.pnets = {}
        self.members: dict = {}
        for p in parts:
            g = geo(p.lib_id, p.unit)
            self.slots[pid(p)] = g.slots
            nl = [net_of(p, s) for s in g.slots]
            self.pnets[pid(p)] = nl
            for i, n in enumerate(nl):
                if n not in (None, UNASSIGNED) and n not in self.force_labels:
                    self.members.setdefault(n, []).append((p, i))
        self.decap_of: dict = {}       # (pid(anchor), slot) -> [parts]
        self._assign_decaps()
        self.errors: list[str] = []

    # -- helpers
    def kind(self, net):
        if net in self.force_labels:
            return "F"
        return self.nets.kind(net)

    def pin_label(self, blk, ps, j):
        """A label straight on a pin (only for force_labels nets: the old, label-only style)."""
        net = ps.nets[j]
        scope = "global" if self.nets.kind(net) == "G" else "local"
        lab = blk.add(PLabel(net, *ps.tip(j), ps.out(j), scope))
        k = self.pkey(net)
        blk.term(k, ps, j)
        blk.term(k, lab)

    def is_multi(self, p):
        return is_anchor_part(p)

    def conn_count(self, p):
        return sum(1 for n in self.pnets[pid(p)] if n not in (None, UNASSIGNED))

    def claim(self, p):
        self.claimed.add(pid(p))

    def is_claimed(self, p):
        return pid(p) in self.claimed

    def pkey(self, net):
        self.pk += 1
        return f"{net}#{self.pk}"

    def power_sym(self, net, x, y, body):
        lib = self.nets.d.power_lib(net)
        return PPow(net, lib, x, y, body)

    def _assign_decaps(self):
        multis = [p for p in self.parts if self.is_multi(p)]
        main = self.main_anchor()
        for p in self.parts:
            nl = self.pnets[pid(p)]
            if len(nl) != 2 or not all(n is not None and n in self.nets.power for n in nl):
                continue
            target = None
            hint = getattr(p, "near", None)
            if hint:
                ref, _, pin = hint.partition(".")
                for q in multis:
                    if q.ref != ref:
                        continue
                    for i, s in enumerate(self.slots[pid(q)]):
                        if self.pnets[pid(q)][i] in nl and (not pin or pin in (s.number, s.name) or
                                                           any(pin in (x.number, x.name) for x in s.pins)):
                            target = (q, i)
                            break
                    if target:
                        break
            if target is None:
                order = ([main] if main is not None else []) + [q for q in multis if q is not main]
                for q in order:
                    best = None
                    for i, s in enumerate(self.slots[pid(q)]):
                        n = self.pnets[pid(q)][i]
                        if n not in nl or gnd_like(n):
                            continue
                        ps = PSym(q)
                        score = (0 if s.etype == "power_in" else 1 if s.etype == "power_out" else 2,
                                 0 if ps.side(i) == "T" else 1)
                        if best is None or score < best[0]:
                            best = (score, i)
                    if best:
                        target = (q, best[1])
                        break
            if target:
                self.decap_of.setdefault((pid(target[0]), target[1]), []).append(p)

    def main_anchor(self):
        multis = [p for p in self.parts if self.is_multi(p)]
        if self.anchor_hint:
            for p in multis:
                if p.ref == self.anchor_hint:
                    return p
        if not multis:
            return None
        return max(multis, key=lambda p: (self.conn_count(p), -self.parts.index(p)))

    # -- layout primitives
    def orient2(self, p, i, want):
        """(rot) so that slot i of 2/1-pin part p points `want` (screen dir)."""
        for r in (0, 90, 180, 270):
            ps = PSym(p, r)
            if ps.out(i) == want:
                return r
        return None

    def shunt(self, p, i, up, dirx):
        """A shunt: slot i on the spine at (0,0); the rest of the part goes up (up=True) or down.
        Returns (PSym, width_left, width_right) relative to the connection x."""
        want = (0, 1) if up else (0, -1)
        away = (-want[0], -want[1])
        best = None
        for rr in (0, 180, 90, 270):
            ps = PSym(p, rr, text_side=dirx)
            sc = 0 if ps.out(i) == want else 6 if ps.out(i) == away else 2
            for j in range(ps.nslots()):
                if j != i:
                    o = ps.out(j)
                    sc += 0 if o == away else 5 if o == want else 1
            if best is None or sc < best[0]:
                best = (sc, ps)
        ps = best[1]
        tx, ty = ps.tip_rel(i)
        oy = ps.out(i)[1]
        dy = 0.0 if oy == (1 if up else -1) else (-2.54 if up else 2.54)
        ps.x, ps.y = sn(-tx), sn(dy - ty)
        # power symbols / NC on the far pins
        extra = []
        for j in range(ps.nslots()):
            if j == i:
                continue
            n = ps.nets[j]
            if n is None:
                extra.append(PNC(*ps.tip(j)))
            elif n in self.force_labels:
                extra.append(("label", j))
            elif n in self.nets.power:
                fx, fy = ps.tip(j)
                o = ps.out(j)
                body = self.natural(n, o)
                if body != o:
                    # the pin points sideways (e.g. a buzzer with both pins on one side): a symbol right on
                    # the tip would draw its graphic over the pin and its number, so it sits on a short stub
                    fx, fy = sn(fx + o[0] * 2.54), sn(fy + o[1] * 2.54)
                pw = self.power_sym(n, fx, fy, body)
                pw.slot = j
                extra.append(pw)
        return ps, extra

    @staticmethod
    def natural(net, out):
        """Power symbol body direction at a pin pointing `out`: GND hangs down, supplies point up, unless the
        pin points the opposite way (then the symbol follows the pin, as a person would draw it)."""
        nat = (0, 1) if gnd_like(net) else (0, -1)
        return out if out == (-nat[0], -nat[1]) else nat

    def far_power(self, blk, ps, skip):
        for it in skip:
            if isinstance(it, tuple):
                self.pin_label(blk, ps, it[1])
                continue
            blk.add(it)
            if it.kind == "pow":
                # the slot it serves (on the tip, or at the end of a stub)
                for j in range(ps.nslots()):
                    sl = getattr(it, "slot", None)
                    if (sl == j) if sl is not None else (ps.tip(j) == (it.x, it.y)):
                        k = self.pkey(it.net)
                        blk.term(k, ps, j)
                        blk.term(k, it)

    def label_shape(self, net, etype):
        shp = {"input": "input", "output": "output", "bidirectional": "bidirectional",
               "tri_state": "tri_state"}.get(etype, "passive")
        return self.nets.shapes.get(net, shp)

    # -- net blocks
    def net_block(self, net, d, etype="passive", want_label=True, lead=True):
        """Spine for `net` starting at (0,0) and running in x-direction d (+1/-1). lead: a pin sits at (0,0), so
        a wire arrives at the first column."""
        blk = Block()
        kind = self.kind(net)
        key = net
        mem = [(p, i) for p, i in self.members.get(net, []) if not self.is_claimed(p)]
        multis, twos, ones = [], [], []
        for p, i in mem:
            n = len(self.slots[pid(p)])
            if self.is_multi(p):
                if p not in multis:
                    multis.append(p)
            elif n == 2:
                twos.append((p, i))
            else:
                ones.append((p, i))
        ups, dns, series = [], [], []
        mids = {pid(q) for q in multis}
        for p, i in twos:
            m = self.pnets[pid(p)][1 - i]
            if m == net:
                dns.append((p, i))
            elif m is None or m in self.nets.power or m in self.force_labels:
                if m is not None and not gnd_like(m):
                    ups.append((p, i))
                else:
                    dns.append((p, i))
            elif any((self.is_claimed(q) or pid(q) in mids) for q, _ in self.members.get(m, []) if q is not p):
                self.bridges.append(p)
            else:
                series.append((p, i))
        for p, _ in twos + ones:
            self.claim(p)
        for q in multis:
            self.claim(q)
        ups += ones
        # label decisions
        label = None
        if kind == "G" and want_label and net not in self.label_done:
            # a sub-anchor that has another pin on this net carries the label on its far side
            defer = any(sum(1 for qq, _ in self.members[net] if qq is q) > 1 for q in multis)
            if not defer or net in self.force_labels:
                label = "end" if not (series or multis) else "tap"
                self.label_done.add(net)
        cursor = 1.27
        if kind == "L" and net not in self.tag_done:
            self.tag_done.add(net)
            lab = blk.add(PLabel(net, sn(d * cursor), 0.0, (d, 0), "local"))
            blk.term(key, lab)
            cursor = sn(cursor + lab.length() + 1.27)
        tapl = None
        if label == "tap":
            tapl = "label"
            ups = ups + [None]
        ncol = max(len(ups), len(dns))
        before = lead or kind == "L"     # a pin or the name tag sits before the first column
        has_after = bool(series or multis) or label == "end"
        for k in range(ncol):
            col = []
            if k < len(ups):
                col.append(("u", ups[k]))
            if k < len(dns):
                col.append(("d", dns[k]))
            placed = []
            for ud, ent in col:
                if ent is None:      # the label on a vertical tap
                    lab = PLabel(net, 0.0, -2.54, (0, -1), "global", self.label_shape(net, etype))
                    placed.append((lab, None, []))
                    continue
                p, i = ent
                ps, extra = self.shunt(p, i, ud == "u", d)
                placed.append((ps, i, extra))
            # an up and a down shunt on one spine point with wire on both sides would be a 4-way junction (a
            # cross with a dot, which a person avoids): the down one moves one step along, giving two T's
            wire_in = before or k > 0
            wire_out = has_after or k < ncol - 1
            shift = [0.0] * len(placed)
            if len(placed) == 2 and wire_in and wire_out:
                shift[1] = 2.54
            # column extent along the spine direction (f = d * x)
            back, fwd = 0.0, 0.0
            for (it, i, extra), s in zip(placed, shift):
                bb = bbox_of([b for b in it.boxes()] + [b for e in extra if not isinstance(e, tuple) for b in e.boxes()])
                f0, f1 = (bb.x0, bb.x1) if d > 0 else (-bb.x1, -bb.x0)
                back = max(back, -(f0 + s))
                fwd = max(fwd, f1 + s)
            cx = sn(cursor + back + 0.6)
            for (it, i, extra), s in zip(placed, shift):
                it.move(d * (cx + s), 0)
                for e in extra:
                    if not isinstance(e, tuple):
                        e.move(d * (cx + s), 0)
                blk.add(it)
                if i is None:
                    blk.term(key, it)
                else:
                    blk.term(key, it, i)
                    self.far_power(blk, it, extra)
            cursor = sn(cx + fwd + 1.9)
        conts = [("s", p, i) for p, i in series] + [("m", q, None) for q in multis]
        end = cursor
        if conts:
            first, rest = conts[0], conts[1:]
            sub = self.continuation(first, net, d)
            if sub is not None:
                sb, (tx, ty) = sub
                sb.move(d * (end + 1.27) - tx, -ty)
                # avoid what is already on the spine
                idx = BoxIndex(blk.boxes())
                off = find_free(idx, sb, [(d * dx, dy) for dx, dy in offsets(((1,), (0, 1, -1)), 40, 1.0, 1.6)])
                if off:
                    sb.move(*off)
                blk.merge(sb)
            for c in rest:
                sub = self.continuation(c, net, d)
                if sub is None:
                    continue
                sb, (tx, ty) = sub
                bb = blk.bbox()
                sb.move(d * 2.54 - tx, bb.y1 + 2.54 - sb.bbox().y0)
                idx = BoxIndex(blk.boxes())
                off = find_free(idx, sb, [(d * dx, dy) for dx, dy in offsets(((1,), (1, 0)), 40, 1.0, 1.0)])
                if off:
                    sb.move(*off)
                blk.merge(sb)
        elif label == "end":
            lab = blk.add(PLabel(net, sn(d * (cursor + 1.27)), 0.0, (d, 0), "global", self.label_shape(net, etype)))
            blk.term(key, lab)
            end = cursor + 1.27 + lab.length()
        if blk.items:
            blk.extra.append(Box(min(0, d * end), -0.3, max(0, d * end), 0.3, "spine"))
        return blk

    def continuation(self, c, net, d):
        """A series part or sub-anchor continuing the spine. Returns (Block, connection point) or None."""
        t, p, i = c
        if t == "s":
            r = self.orient2(p, i, (-d, 0))
            ps = PSym(p, r if r is not None else 0)
            blk = Block()
            blk.add(ps)
            blk.term(net, ps, i)
            j = 1 - i
            m = ps.nets[j]
            fx, fy = ps.tip(j)
            child = self.net_block(m, d)
            child.move(fx, fy)
            blk.merge(child)
            blk.term(m, ps, j)
            return blk, ps.tip(i)
        q = p
        slots = self.slots[pid(q)]
        cands = [k for k, n in enumerate(self.pnets[pid(q)]) if n == net]
        base = PSym(q)
        pick = None
        for k in cands:
            if base.out(k) == (-d, 0):
                pick, mirror = k, False
                break
        if pick is None:
            for k in cands:
                if base.out(k) == (d, 0):
                    pick, mirror = k, True
                    break
        if pick is None:
            pick, mirror = cands[0], False
        blk = self.anchor_block(q, conn=pick, mirror=mirror)
        a = blk.items[0]
        blk.term(net, a, pick)
        tx, ty = a.tip(pick)
        o = a.out(pick)
        if o[1] < 0:        # pin points up: hang the part below the spine end
            return blk, (tx, ty - 5.08)
        if o[1] > 0:
            return blk, (tx, ty + 5.08)
        return blk, (tx, ty)

    def power_block(self, net, decaps, d, entry_dir, sideways=False):
        """Power pin(s) with their decoupling caps on a spine, ending in the power symbol."""
        blk = Block()
        key = self.pkey(net)
        cursor = 1.27
        for p in decaps:
            self.claim(p)
            nl = self.pnets[pid(p)]
            i = 0 if nl[0] == net else 1
            other = nl[1 - i]
            ps, extra = self.shunt(p, i, not gnd_like(other) and gnd_like(net), d)
            bb = bbox_of(ps.boxes() + [b for e in extra if not isinstance(e, tuple) for b in e.boxes()])
            back, fwd = (-bb.x0, bb.x1) if d > 0 else (bb.x1, -bb.x0)
            cx = sn(cursor + back + 0.6)
            ps.move(d * cx, 0)
            for e in extra:
                if not isinstance(e, tuple):
                    e.move(d * cx, 0)
            blk.add(ps)
            blk.term(key, ps, i)
            self.far_power(blk, ps, extra)
            cursor = sn(cx + fwd + 1.9)
        body = (0, 1) if gnd_like(net) else (0, -1)
        if sideways and not decaps:
            body = (d, 0)
        px = sn(d * (cursor + 1.27)) if decaps else 0.0
        pw = blk.add(self.power_sym(net, px, 0.0, body))
        blk.term(key, pw)
        if decaps:
            blk.extra.append(Box(min(0, px), -0.3, max(0, px), 0.3, "spine"))
        return blk, key

    # -- anchors
    def anchor_block(self, a, conn=None, mirror=False):
        blk = Block()
        S = PSym(a, 0, mirror)
        self.claim(a)
        blk.add(S)
        n = S.nslots()
        sides = {"L": [], "R": [], "T": [], "B": []}
        for i in range(n):
            if i == conn:
                continue
            sides[S.side(i)].append(i)
        sides["L"].sort(key=lambda i: S.tip(i)[1])
        sides["R"].sort(key=lambda i: S.tip(i)[1])
        sides["T"].sort(key=lambda i: S.tip(i)[0])
        sides["B"].sort(key=lambda i: S.tip(i)[0])
        conn_side = S.side(conn) if conn is not None else None
        if conn is not None:      # keep the incoming lane free
            tx, ty = S.tip(conn)
            ox, oy = S.out(conn)
            if oy == 0:
                blk.extra.append(Box(tx, ty - 3.2, tx + ox * 40, ty + 3.2, "lane"))
        entries = {s: [] for s in sides}
        bx = S.body()
        for side, lst in sides.items():
            d = 1 if side == "R" else -1 if side == "L" else None
            k = 0
            while k < len(lst):
                i = lst[k]
                net = S.nets[i]
                if net == UNASSIGNED:
                    raise ValueError(f"{a.ref}: pin {S.g.slots[i].number} ({S.g.slots[i].name}) unassigned")
                if net is None:
                    blk.add(PNC(*S.tip(i)))
                    k += 1
                    continue
                if net in self.force_labels:
                    self.pin_label(blk, S, i)
                    k += 1
                    continue
                if d is None:
                    tx = S.tip(i)[0]
                    dd = 1 if tx >= (bx.x0 + bx.x1) / 2 else -1
                else:
                    dd = d
                if net in self.nets.power:
                    run = [i]
                    while k + len(run) < len(lst) and S.nets[lst[k + len(run)]] == net:
                        run.append(lst[k + len(run)])
                    k += len(run)
                    decaps = []
                    for j in run:
                        decaps += [p for p in self.decap_of.get((pid(a), j), []) if not self.is_claimed(p)]
                    if side in "TB" and not decaps:
                        o = S.out(run[0])
                        key = self.pkey(net)
                        if len(run) == 1:
                            pw = blk.add(self.power_sym(net, *S.tip(run[0]), o))
                        else:
                            x0, y0 = S.tip(run[0])
                            pw = blk.add(self.power_sym(net, x0 + o[0] * 2.54, y0 + o[1] * 2.54, o))
                        blk.term(key, pw)
                        for j in run:
                            blk.term(key, S, j)
                        continue
                    crowded = False
                    if not decaps:
                        hang = 1 if gnd_like(net) else -1
                        yref = S.tip(run[-1] if hang > 0 else run[0])[1]
                        for j in lst:
                            if j in run or S.nets[j] is None:
                                continue
                            dy = (S.tip(j)[1] - yref) * hang
                            if 0 < dy <= 5.1:
                                crowded = True
                    if not decaps:
                        # a power pin with nothing else on it: the symbol sits on a short stub at the pin
                        rep = run[-1] if gnd_like(net) else run[0]
                        x0, y0 = S.tip(rep)
                        body = (dd, 0) if crowded else self.natural(net, S.out(rep))
                        pw = blk.add(self.power_sym(net, sn(x0 + dd * 2.54), y0, body))
                        key = self.pkey(net)
                        blk.term(key, pw)
                        for j in run:
                            blk.term(key, S, j)
                        continue
                    sub, key = self.power_block(net, decaps, dd, S.out(run[0]), sideways=crowded)
                    entries[side].append((run, sub, key, net))
                    continue
                k += 1
                kind = self.kind(net)
                if (kind == "G" and net in self.label_done) or (kind == "L" and net in self.tag_done):
                    blk.term(net, S, i)
                    continue
                if kind == "G" and conn is not None and side == conn_side and \
                        any(self.is_claimed(q) for q, _ in self.members[net] if q is not a):
                    blk.term(net, S, i)
                    continue
                sub = self.net_block(net, dd, S.g.slots[i].etype)
                if not sub.items:
                    blk.term(net, S, i)
                    continue
                entries[side].append(([i], sub, net, net))
        index = BoxIndex(blk.boxes())
        corridors = []
        for side in ("L", "R"):
            self.stack_side(blk, S, side, entries[side], index, corridors)
        for side in ("T", "B"):
            self.stack_tb(blk, S, side, entries[side], index)
        self.place_fields(S, blk, corridors)
        return blk

    def place_fields(self, S, blk, corridors):
        """Re-pick the anchor's Reference/Value position now that its blocks are placed: the first candidate whose
        text is clear of every placed box and of the lanes where wires jog to moved blocks."""
        others = [b for it in blk.items if it is not S for b in it.boxes()] + list(blk.extra)
        others += [b for b in S.boxes() if b.kind != "text"]
        idx = BoxIndex(others + corridors)
        keep = S.fields
        for ok, fields in S.field_candidates():
            if not ok:
                continue
            S.fields = fields
            if not any(idx.hits(b, 0.5) for b in S.field_boxes()):
                return
        S.fields = keep

    STAGGER_LIMIT = 32.0     # mm a block may move outward along its spine to stay on its pin's row

    @staticmethod
    def _core(b):
        """A box inside the spine's own row band (the wire, a label, an in-line part)."""
        return b.y0 >= -1.35 and b.y1 <= 1.35

    @staticmethod
    def _flippable(sub):
        """A block whose only parts off the spine row are test points: they may hang below instead of above."""
        tps = [it for it in sub.items if it.kind == "sym" and it.nslots() == 1]
        if not tps:
            return []
        for it in sub.items:
            if it in tps:
                continue
            if not all(Cluster._core(b) for b in it.boxes()):
                return []
        return tps

    @staticmethod
    def _flip(tps):
        for it in tps:
            tx, ty = it.tip(0)
            it.rot = (it.rot + 180) % 360
            u, v = it.tip_rel(0)
            it.x, it.y = round(tx - u, 4), round(ty - v, 4)
            it.layout_fields()

    def stagger_side(self, blk, S, d, tipx, ents, rows, index):
        """Every block on its pin's row, the way a person draws a column of nets: a block that reaches into a
        neighbouring row (a test point, a pull-up) moves outward along its own wire until it clears the
        neighbours, and a test point may hang below the wire instead of above. Returns False (nothing changed)
        when some block would have to move more than STAGGER_LIMIT; stack_side then fans the rows out instead."""
        colx = sn(tipx + d * 2.54)
        n = len(ents)
        base, small, flips = [], [], []
        for k, (run, sub, key, net) in enumerate(ents):
            bb = sub.bbox()
            back = -bb.x0 if d > 0 else bb.x1
            base.append(sn(colx + d * max(0.0, back)))
            small.append(all(self._core(b) for b in sub.boxes()))
            flips.append(self._flippable(sub))

        def footprint(k, delta):
            x0 = base[k] + d * delta
            y = rows[k][0]
            bxs = [b.moved(x0, y) for b in ents[k][1].boxes()]
            lane = Box(tipx, y - 0.3, x0, y + 0.3, "lane")
            return bxs, lane

        def core_fp(k):
            bxs, lane = footprint(k, 0.0)
            return [b for b, b0 in zip(bxs, ents[k][1].boxes()) if self._core(b0)] + [lane]

        placed = {}                     # k -> (delta, flipped)
        order = [k for k in range(n) if small[k]] + [k for k in range(n) if not small[k]]
        flipped_now = set()
        ok_all = True
        for k in order:
            others = []
            for j in range(n):
                if j == k:
                    continue
                if j in placed:
                    bxs, lane = footprint(j, placed[j][0])
                    others += bxs + [lane]
                else:
                    others += core_fp(j)
            oidx = BoxIndex(others)
            best = None
            for fl in ((False, True) if flips[k] else (False,)):
                if fl:
                    self._flip(flips[k])
                    flipped_now.add(k)
                steps = int(self.STAGGER_LIMIT / G) + 1
                for s in range(steps):
                    delta = s * G
                    bxs, lane = footprint(k, delta)
                    if any(index.hits(b, 0.25) or oidx.hits(b, 0.25) for b in bxs):
                        continue
                    if index.hits(lane, 0.1) or oidx.hits(lane, 0.25):
                        continue
                    if best is None or delta < best[0]:
                        best = (delta, fl)
                    break
                if fl:
                    self._flip(flips[k])
                    flipped_now.discard(k)
            if best is None:
                ok_all = False
                break
            if best[1]:
                self._flip(flips[k])
                flipped_now.add(k)
            placed[k] = best
        if not ok_all:
            for k in flipped_now:
                self._flip(flips[k])
            return False
        for k, (run, sub, key, net) in enumerate(ents):
            sub.move(base[k] + d * placed[k][0], rows[k][0])
            for b in sub.boxes():
                index.add(b)
            blk.merge(sub)
            for j in run:
                blk.term(key, S, j)
        return True

    def stack_side(self, blk, S, side, ents, index, corridors):
        if not ents:
            return
        d = 1 if side == "R" else -1
        tips = [S.tip(i) for i in range(S.nslots()) if S.side(i) == side]
        tipx = max(t[0] for t in tips) if d > 0 else min(t[0] for t in tips)
        rows = []
        for run, sub, key, net in ents:
            ys = [S.tip(j)[1] for j in run]
            want = max(ys) if gnd_like(net) and net in self.nets.power else min(ys)
            bb = sub.bbox()
            top = math.ceil((max(0.0, -bb.y0) + 0.2) / G - 1e-6) * G
            bot = math.ceil((max(0.0, bb.y1) + 0.2) / G - 1e-6) * G
            rows.append([want, top, bot])
        if self.stagger_side(blk, S, d, tipx, ents, rows, index):
            return
        ys = fit_rows(rows)
        njog =sum(1 for k in range(len(rows)) if abs(ys[k] - rows[k][0]) > 0.01)
        # one vertical lane per moved block, 2 grid apart (wires 1 grid apart read as a bus and the router
        # avoids hugging them with odd hooks)
        colx = sn(tipx + d * (2.54 + 2 * G * njog))
        for r, y in zip(rows, ys):
            if abs(y - r[0]) > 0.01:      # the jog's wire runs here: keep the anchor's fields out of it
                corridors.append(Box(tipx, min(r[0], y) - 0.6, colx, max(r[0], y) + 0.6, "lane"))
        cands = offsets(((1,), (0, 1, -1)), 60, 1.0, 1.4)
        for (run, sub, key, net), y in zip(ents, ys):
            bb = sub.bbox()
            back = -bb.x0 if d > 0 else bb.x1
            sub.move(colx + d * max(0.0, back), y)
            off = find_free(index, sub, [(d * dx, dy) for dx, dy in cands], clr=0.25)
            if off is None:
                self.errors.append(f"{S.part.ref}: no room for the block of {net}")
                off = (0, 0)
            sub.move(*off)
            for b in sub.boxes():
                index.add(b)
            blk.merge(sub)
            for j in run:
                blk.term(key, S, j)

    def stack_tb(self, blk, S, side, ents, index):
        up = side == "T"
        for run, sub, key, net in ents:
            tx, ty = S.tip(run[0])
            bb = sub.bbox()
            if up:
                sub.move(tx, ty - 2.54 - max(0.0, bb.y1))
                cands = offsets(((0, 1, -1), (-1,)), 60, 1.6, 1.0)
            else:
                sub.move(tx, ty + 2.54 + max(0.0, -bb.y0))
                cands = offsets(((0, 1, -1), (1,)), 60, 1.6, 1.0)
            off = find_free(index, sub, cands)
            if off is None:
                self.errors.append(f"{S.part.ref}: no room for the block of {net}")
                off = (0, 0)
            sub.move(*off)
            for b in sub.boxes():
                index.add(b)
            blk.merge(sub)
            for j in run:
                blk.term(key, S, j)

    # -- the whole cluster
    def build(self):
        pieces = []
        main = self.main_anchor()
        if main is not None:
            pieces.append(self.anchor_block(main))
        while True:
            rest = [p for p in self.parts if self.is_multi(p) and not self.is_claimed(p)]
            if not rest:
                break
            q = max(rest, key=lambda p: (self.conn_count(p), -self.parts.index(p)))
            pieces.append(self.anchor_block(q))
        for p in self.parts:
            if self.is_claimed(p):
                continue
            nets = [n for n in self.pnets[pid(p)] if n not in (None, UNASSIGNED) and n not in self.nets.power]
            for n in nets:
                if any(not self.is_claimed(q) for q, _ in self.members.get(n, [])):
                    blk = self.net_block(n, 1, lead=False)
                    if blk.items:
                        pieces.append(blk)
                    break
        loose = Block()
        lx = 0.0
        for p in self.parts:
            if self.is_claimed(p):
                continue
            self.claim(p)
            b = self.loose_part(p)
            bb = b.bbox()
            b.move(lx - bb.x0, -bb.y0)
            loose.merge(b)
            lx = sn(lx + (bb.x1 - bb.x0) + 3.81)
        if loose.items:
            pieces.append(loose)
        out = Block()
        if pieces:
            first = pieces[0]
            fb = first.bbox()
            first.move(-fb.x0, -fb.y0)
            out.merge(first)
            width = max(fb.x1 - fb.x0, 90.0)
            x, y, row_h = 0.0, (fb.y1 - fb.y0) + 6.35, 0.0
            for pc in pieces[1:]:
                bb = pc.bbox()
                w, h = bb.x1 - bb.x0, bb.y1 - bb.y0
                if x > 0 and x + w > width:
                    x, y, row_h = 0.0, y + row_h + 5.08, 0.0
                pc.move(x - bb.x0, y - bb.y0)
                out.merge(pc)
                x = sn(x + w + 7.62)
                row_h = max(row_h, h)
        self.place_bridges(out)
        return out

    def loose_part(self, p):
        """A part with only power pins (or none): power symbols straight on its pins."""
        blk = Block()
        nl = self.pnets[pid(p)]
        n = len(nl)
        rot = p.rot if p.rot is not None else 0
        if n == 1 and nl[0] is not None:
            want = (0, 1) if gnd_like(nl[0]) else (0, -1)
            rot = self.orient2(p, 0, want) or 0
        elif n == 2 and all(x is not None for x in nl):
            sup = [i for i in range(2) if not gnd_like(nl[i])]
            if sup:
                rot = self.orient2(p, sup[0], (0, -1))
                rot = 0 if rot is None else rot
        ps = blk.add(PSym(p, rot))
        for i in range(n):
            net = nl[i]
            if net is None:
                blk.add(PNC(*ps.tip(i)))
            elif net in self.force_labels:
                self.pin_label(blk, ps, i)
            elif net in self.nets.power:
                pw = blk.add(self.power_sym(net, *ps.tip(i), ps.out(i)))
                k = self.pkey(net)
                blk.term(k, ps, i)
                blk.term(k, pw)
            else:
                lab = blk.add(PLabel(net, *ps.tip(i), ps.out(i), "global" if self.kind(net) == "G" else "local"))
                blk.term(net, ps, i)
                blk.term(net, lab)
        return blk

    def place_bridges(self, out):
        index = BoxIndex(out.boxes())
        for p in self.bridges:
            nl = self.pnets[pid(p)]
            ends = []
            for n in nl:
                ts = [t.point() for t in out.conns.get(n, [])]
                ends.append(ts)
            if not ends[0] or not ends[1]:
                self.errors.append(f"bridge {p.ref}: an end net has no placed connection")
                continue
            best = min(((a, b) for a in ends[0] for b in ends[1]),
                       key=lambda ab: abs(ab[0][0] - ab[1][0]) + abs(ab[0][1] - ab[1][1]))
            (ax, ay), (bx_, by_) = best
            horiz = abs(ax - bx_) >= abs(ay - by_)
            if horiz:
                want = (-1, 0) if ax <= bx_ else (1, 0)
            else:
                want = (0, -1) if ay <= by_ else (0, 1)
            r = self.orient2(p, 0, want)
            ps = PSym(p, r if r is not None else 0)
            blk = Block()
            blk.add(ps)
            cx, cy = sn((ax + bx_) / 2), sn((ay + by_) / 2)
            pc = ps.tip(0)
            pc2 = ps.tip(1)
            ps.x, ps.y = sn(cx - (pc[0] + pc2[0]) / 2), sn(cy - (pc[1] + pc2[1]) / 2)
            ps.layout_fields()
            if horiz:
                cands = offsets(((0, 1, -1), (-1, 1)), 60, 2.0, 1.0)
            else:
                cands = offsets(((-1, 1), (0, 1, -1)), 60, 1.0, 2.0)
            off = find_free(index, blk, cands, clr=1.5)
            if off is None:
                self.errors.append(f"bridge {p.ref}: no room")
                off = (0, 0)
            blk.move(*off)
            for b in blk.boxes():
                index.add(b)
            out.merge(blk)
            out.term(nl[0], ps, 0)
            out.term(nl[1], ps, 1)


# ---------------------------------------------------------------------------------------------- router

class RouteError(Exception):
    pass


class Router:
    BEND = 3.0
    CROSS = 6.0
    HUG = 1.5

    def __init__(self, blk: Block, margin=12):
        self.blk = blk
        self.blocked: set = set()
        self.soft: dict = {}
        self.term_owner: dict = {}     # cell -> group key (pins, labels, power pins)
        self.node_owner: dict = {}     # cell -> group key (wire ends / bends / T's)
        self.wire: dict = {}           # cell -> {key: set(sides)}
        self.used: dict = {}           # (cell) -> set(sides) for own-group terminals
        bb = blk.bbox()
        self.bx0, self.by0 = gi(bb.x0) - margin, gi(bb.y0) - margin
        self.bx1, self.by1 = gi(bb.x1) + margin, gi(bb.y1) + margin
        for it in blk.items:
            for b in it.boxes():
                if b.kind == "spine":
                    continue
                if b.kind == "text":      # keep wires a little away from text
                    b = Box(b.x0 - 0.5, b.y0 - 0.25, b.x1 + 0.5, b.y1 + 0.25, "text")
                self._rast(b)
        for b in blk.extra:
            pass
        self.terms = {}
        for key, ts in blk.conns.items():
            for t in ts:
                c = (gi(t.point()[0]), gi(t.point()[1]))
                if abs(t.point()[0] - c[0] * G) > 0.01 or abs(t.point()[1] - c[1] * G) > 0.01:
                    raise RouteError(f"terminal of {key} off grid at {t.point()}")
                if self.term_owner.get(c, key) != key:
                    raise RouteError(f"terminals of {key} and {self.term_owner[c]} share {t.point()}")
                self.term_owner[c] = key
                self.blocked.discard(c)
        for c in list(self.blocked):
            for dx, dy in DIRS:
                n = (c[0] + dx, c[1] + dy)
                if n not in self.blocked:
                    self.soft[n] = self.soft.get(n, 0) + 0.35

    def _rast(self, b: Box):
        for i in range(int(math.ceil(b.x0 / G - 1e-6)), int(math.floor(b.x1 / G + 1e-6)) + 1):
            for j in range(int(math.ceil(b.y0 / G - 1e-6)), int(math.floor(b.y1 / G + 1e-6)) + 1):
                self.blocked.add((i, j))

    def route_all(self, order=None):
        keys = list(self.blk.conns)
        if order:
            keys.sort(key=lambda k: (order.get(k, 1e9)))
        fails = []
        self.paths = {k: [] for k in keys}
        for k in keys:
            try:
                self.route_group(k)
            except RouteError as e:
                fails.append((k, str(e)))
        return fails

    def group_terms(self, key):
        cells = {}
        seen = set()
        for t in self.blk.conns[key]:
            if (id(t.item), t.slot) in seen:
                continue
            seen.add((id(t.item), t.slot))
            p = t.point()
            c = (gi(p[0]), gi(p[1]))
            arr, used = t.arrivals()
            if c in cells:
                a0, u0, pins, items = cells[c]
                arr = {k: v for k, v in arr.items() if k in a0}
                cells[c] = (arr, u0 | used, pins + (1 if t.is_pin() else 0), items + [t])
            else:
                cells[c] = (arr, used, 1 if t.is_pin() else 0, [t])
        for c, (arr, used, _, _) in cells.items():
            for u in used:
                arr.pop((-u[0], -u[1]), None)
        return cells

    def route_group(self, key):
        cells = self.group_terms(key)
        order = list(cells)
        tree = {order[0]}
        self.used_sides = getattr(self, "used_sides", {})
        for c in order:
            self.used_sides[c] = set(cells[c][1])
        todo = order[1:]
        while todo:
            def dist(c):
                return min(abs(c[0] - t[0]) + abs(c[1] - t[1]) for t in tree)
            todo.sort(key=dist)
            c = todo.pop(0)
            path = self.search(key, c, cells, tree)
            if path is None:
                path = self.search(key, c, cells, tree, wide=True)
            if path is None:
                raise RouteError(f"cannot wire {key}: {self.describe(cells[c][3])}")
            self.commit(key, path, cells, tree)

    def describe(self, terms):
        out = []
        for t in terms:
            it = t.item
            if it.kind == "sym":
                out.append(f"{it.part.ref}.{it.g.slots[t.slot].number}")
            elif it.kind == "pow":
                out.append(f"power {it.net}")
            else:
                out.append(f"label {it.net}")
        return ", ".join(out)

    def passable(self, key, c, e):
        """Cost of entering cell c moving e (None = not allowed), and whether c holds a foreign wire."""
        if c in self.blocked:
            return None, False
        own = self.term_owner.get(c)
        if own is not None:
            return None, False
        no = self.node_owner.get(c)
        if no is not None and no != key:
            return None, False
        w = self.wire.get(c)
        cross = False
        cost = 1.0 + self.soft.get(c, 0)
        if w:
            for k2, sides in w.items():
                if k2 == key:
                    return None, False
                perp = {(e[1], e[0]), (-e[1], -e[0])}
                if sides != perp:
                    return None, False
            cross = True
            cost += self.CROSS
        # discourage running right next to a foreign wire in parallel
        for s in ((e[1], e[0]), (-e[1], -e[0])):
            n = (c[0] + s[0], c[1] + s[1])
            wn = self.wire.get(n)
            if wn and any(k2 != key and (e in sd or (-e[0], -e[1]) in sd) for k2, sd in wn.items()):
                cost += self.HUG
        return cost, cross

    def arrival_ok(self, key, c, e, cells, tree):
        """Can a wire moving e end in tree cell c? Returns extra cost or None."""
        side = (-e[0], -e[1])
        used = self.used_sides.get(c, set())
        if side in used:
            return None
        if c in cells:
            arr = cells[c][0]
            if e not in arr:
                # a terminal already wired can take a T only from a free side, and only if not a label tag
                return None
            return arr[e] + (2.0 if used - set(cells[c][1]) else 0.0)
        # interior / corner of own wire
        if len(used) >= 3:
            return None
        return 1.0

    def search(self, key, src, cells, tree, wide=False):
        if wide:
            x0, y0, x1, y1 = self.bx0 - 20, self.by0 - 20, self.bx1 + 20, self.by1 + 20
        else:
            xs = [src[0]] + [t[0] for t in tree]
            ys = [src[1]] + [t[1] for t in tree]
            m = 14
            x0, y0, x1, y1 = min(xs) - m, min(ys) - m, max(xs) + m, max(ys) + m
            x0, y0, x1, y1 = max(x0, self.bx0), max(y0, self.by0), min(x1, self.bx1), min(y1, self.by1)
        arr, used, _, _ = cells[src]
        pq = []
        best = {}
        prev = {}
        cnt = 0
        for e_in, c0 in arr.items():
            e = (-e_in[0], -e_in[1])          # departure direction
            if e in self.used_sides.get(src, set()):
                continue
            n = (src[0] + e[0], src[1] + e[1])
            st = (n, e)
            if n in tree:
                ex = self.arrival_ok(key, n, e, cells, tree)
                if ex is not None:
                    return [src, n]
                continue
            cst, cross = self.passable(key, n, e)
            if cst is None:
                continue
            cst += c0
            if cst < best.get(st, 1e18):
                best[st] = cst
                prev[st] = None
                cnt += 1
                heapq.heappush(pq, (cst, cnt, st, cross))
        while pq:
            cost, _, st, cross = heapq.heappop(pq)
            if cost > best.get(st, 1e18) + 1e-9:
                continue
            c, e = st
            for e2 in DIRS:
                if e2 == (-e[0], -e[1]):
                    continue
                if cross and e2 != e:
                    continue
                n = (c[0] + e2[0], c[1] + e2[1])
                if not (x0 <= n[0] <= x1 and y0 <= n[1] <= y1):
                    continue
                bend = self.BEND if e2 != e else 0.0
                if bend and self.node_owner.get(c, key) != key:
                    continue
                if n in tree:
                    ex = self.arrival_ok(key, n, e2, cells, tree)
                    if ex is None:
                        continue
                    # done: reconstruct
                    path = [n, c]
                    s = st
                    while prev.get(s) is not None:
                        s = prev[s]
                        path.append(s[0])
                    path.append(src)
                    path.reverse()
                    # Dijkstra pops in cost order, but goal arrivals are not queued: accept the first one,
                    # its cost is within one step of optimal.
                    return path
                cst, cr = self.passable(key, n, e2)
                if cst is None:
                    continue
                nc = cost + cst + bend
                ns = (n, e2)
                if nc < best.get(ns, 1e18) - 1e-9:
                    best[ns] = nc
                    prev[ns] = st
                    cnt += 1
                    heapq.heappush(pq, (nc, cnt, ns, cr))
        return None

    def commit(self, key, path, cells, tree):
        # dedupe consecutive
        pts = [path[0]]
        for c in path[1:]:
            if c != pts[-1]:
                pts.append(c)
        for a, b in zip(pts, pts[1:]):
            e = (b[0] - a[0], b[1] - a[1])
            self.wire.setdefault(a, {}).setdefault(key, set()).add(e)
            self.wire.setdefault(b, {}).setdefault(key, set()).add((-e[0], -e[1]))
            self.used_sides.setdefault(a, set()).add(e)
            self.used_sides.setdefault(b, set()).add((-e[0], -e[1]))
        for k, c in enumerate(pts):
            first_last = k in (0, len(pts) - 1)
            bend = not first_last and (pts[k + 1][0] - c[0], pts[k + 1][1] - c[1]) != (c[0] - pts[k - 1][0], c[1] - pts[k - 1][1])
            if first_last or bend:
                self.node_owner[c] = key
            tree.add(c)
        self.paths[key].append(pts)

    # -- output
    def segments(self):
        """Per group: list of ((x0,y0),(x1,y1)) in mm, split at every T / pin; and junction points."""
        segs = {}
        junctions = []
        pin_cells = {}
        for key, ts in self.blk.conns.items():
            for t in {(id(t.item), t.slot): t for t in ts}.values():
                p = t.point()
                c = (gi(p[0]), gi(p[1]))
                if t.is_pin():
                    pin_cells[c] = pin_cells.get(c, 0) + 1
        brk = set()
        for c, kd in self.wire.items():
            for key, sides in kd.items():
                straight = sides in ({(1, 0), (-1, 0)}, {(0, 1), (0, -1)})
                if not straight or c in self.term_owner or c in pin_cells:
                    brk.add((c, key))
        for (c, key) in brk:
            for s in self.wire[c][key]:
                n = c
                while True:
                    n = (n[0] + s[0], n[1] + s[1])
                    if (n, key) in brk:
                        break
                a, b = (c, n) if c <= n else (n, c)
                segs.setdefault(key, set()).add((a, b))
        for c, kd in self.wire.items():
            for key, sides in kd.items():
                cnt = len(sides) + pin_cells.get(c, 0)
                if cnt >= 3:
                    junctions.append((round(c[0] * G, 4), round(c[1] * G, 4)))
        out = {}
        for key, ss in segs.items():
            out[key] = [((round(a[0] * G, 4), round(a[1] * G, 4)), (round(b[0] * G, 4), round(b[1] * G, 4)))
                        for a, b in sorted(ss)]
        # coincident pins with no wire (power symbol on a pin, two pins touching): junction if 3+
        for c, n in pin_cells.items():
            if c not in self.wire and n >= 3:
                junctions.append((round(c[0] * G, 4), round(c[1] * G, 4)))
        return out, sorted(set(junctions))


def _quality(r: Router, blk: Block):
    """Total drawing cost and per-group excess over the terminal MST (detours)."""
    total, excess = 0.0, {}
    for key, paths in r.paths.items():
        ln = bends = 0
        for pts in paths:
            ln += len(pts) - 1
            for k in range(1, len(pts) - 1):
                a, b, c = pts[k - 1], pts[k], pts[k + 1]
                if (b[0] - a[0], b[1] - a[1]) != (c[0] - b[0], c[1] - b[1]):
                    bends += 1
        cells = list({(gi(t.point()[0]), gi(t.point()[1])) for t in blk.conns[key]})
        mst, seen = 0, {cells[0]} if cells else set()
        rest = cells[1:]
        while rest:
            d, c = min((min(abs(c[0] - q[0]) + abs(c[1] - q[1]) for q in seen), c) for c in rest)
            mst += d
            seen.add(c)
            rest.remove(c)
        cost = ln + 3 * bends
        total += cost
        excess[key] = cost - mst
    total += 6 * sum(1 for kd in r.wire.values() if len(kd) > 1)
    return total, excess


def route(blk: Block, improve: int = 6):
    """Route every group of the block. Returns (segments by group, junctions, errors).

    Groups are routed shortest-first; then up to `improve` times the group with the largest detour is moved to
    the front and everything is rerouted, keeping the order whenever the total cost (length, bends, crossings)
    goes down. A group that cannot be routed is moved to the front and retried before giving up."""
    order = {}
    for k, ts in blk.conns.items():
        pts = [t.point() for t in ts]
        order[k] = (max(p[0] for p in pts) - min(p[0] for p in pts)) + (max(p[1] for p in pts) - min(p[1] for p in pts))
    best = None
    for attempt in range(4):
        r = Router(blk)
        fails = r.route_all(order)
        if not fails:
            best = (r, dict(order))
            break
        for k, _ in fails:
            order[k] = -1e6 - attempt
    if best is None:
        segs, junc = r.segments()
        return segs, junc, [m for _, m in fails]
    r, order = best
    cost, excess = _quality(r, blk)
    tried = set()
    for _ in range(improve):
        cands = [(v, k) for k, v in excess.items() if k not in tried and v > 4]
        if not cands:
            break
        _, k = max(cands)
        tried.add(k)
        o2 = dict(order)
        o2[k] = min(o2.values()) - 1
        r2 = Router(blk)
        if r2.route_all(o2):
            continue
        c2, e2 = _quality(r2, blk)
        if c2 < cost - 0.5:
            r, order, cost, excess = r2, o2, c2, e2
    segs, junc = r.segments()
    return segs, junc, []
