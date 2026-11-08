"""Finish the connections an autorouter leaves open: a grid A* router on a routed pcbnew board.

Freerouting tends to stall on the last few connections in a dense area (the module's two pad rows). This router
connects what is left, one connection at a time, on the signal layers with through vias:

* the copper of each net is split into connected clusters (pads, tracks, vias; GND vias and through-hole pads also
  join through the inner plane), and the clusters of a net are joined nearest-first;
* obstacles are rasterised on a fine grid: every other-net pad, track and via on the layer, grown by the net-class
  clearance + half the new track width + a grid margin; drilled holes (hole clearance, hole-to-hole for vias), the
  board edge (copper-to-edge clearance) and the track/via rule areas;
* the path is found with A* (8 directions per layer, a via changes layer at a cost), then pulled straight where the
  grid allows, and written back as tracks and vias in the net's class widths.

Every connection it adds is re-checked by KiCad's DRC through the caller (see `check_new`). A connection that DRC
rejects is removed and retried with a wider grid margin.
"""

from __future__ import annotations

import heapq
import json
import math
import os
import subprocess
import tempfile

import numpy as np
import pcbnew
from matplotlib.path import Path

MM = pcbnew.FromMM
TO_MM = pcbnew.ToMM


# --------------------------------------------------------------------------- geometry helpers
def _poly_arrays(ps):
    """SHAPE_POLY_SET -> list of (outline Nx2 array mm, [hole arrays])."""
    out = []
    for i in range(ps.OutlineCount()):
        def arr(chain):
            return np.array([(TO_MM(chain.CPoint(j).x), TO_MM(chain.CPoint(j).y)) for j in range(chain.PointCount())])
        holes = [arr(ps.Hole(i, h)) for h in range(ps.HoleCount(i))]
        out.append((arr(ps.Outline(i)), holes))
    return out


def _item_polys(item, layer):
    ps = pcbnew.SHAPE_POLY_SET()
    item.TransformShapeToPolygon(ps, layer, 0, MM(0.002), pcbnew.ERROR_OUTSIDE)
    return _poly_arrays(ps)


def _seg_dist(px, py, a, b):
    """Distance from points (px, py) to segment a-b (mm)."""
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return np.hypot(px - ax, py - ay)
    t = np.clip(((px - ax) * dx + (py - ay) * dy) / L2, 0.0, 1.0)
    return np.hypot(px - (ax + t * dx), py - (ay + t * dy))


class Grid:
    def __init__(self, x0, y0, x1, y1, g):
        self.g = g
        self.x0, self.y0 = x0, y0
        self.nx = int(math.ceil((x1 - x0) / g)) + 1
        self.ny = int(math.ceil((y1 - y0) / g)) + 1

    def xy(self, ix, iy):
        return float(self.x0 + int(ix) * self.g), float(self.y0 + int(iy) * self.g)

    def idx(self, x, y):
        return int(round((x - self.x0) / self.g)), int(round((y - self.y0) / self.g))

    def _window(self, xmin, ymin, xmax, ymax):
        ix0 = max(0, int(math.floor((xmin - self.x0) / self.g)))
        ix1 = min(self.nx - 1, int(math.ceil((xmax - self.x0) / self.g)))
        iy0 = max(0, int(math.floor((ymin - self.y0) / self.g)))
        iy1 = min(self.ny - 1, int(math.ceil((ymax - self.y0) / self.g)))
        return ix0, ix1, iy0, iy1

    def mark_polys(self, mask, polys, R, inside=True):
        """mask |= cells inside any polygon (if inside) or within R of its edges (each edge tested only over its own
        bounding box grown by R, so large polygons such as the board outline stay cheap)."""
        for outline, holes in polys:
            if len(outline) < 2:
                continue
            if inside and len(outline) >= 3:
                ix0, ix1, iy0, iy1 = self._window(outline[:, 0].min(), outline[:, 1].min(),
                                                  outline[:, 0].max(), outline[:, 1].max())
                if ix1 >= ix0 and iy1 >= iy0:
                    gx, gy = np.meshgrid(self.x0 + np.arange(ix0, ix1 + 1) * self.g,
                                         self.y0 + np.arange(iy0, iy1 + 1) * self.g)
                    pts = np.column_stack([gx.ravel(), gy.ravel()])
                    hit = Path(outline).contains_points(pts)
                    for h in holes:
                        if len(h) >= 3:
                            hit &= ~Path(h).contains_points(pts)
                    mask[iy0:iy1 + 1, ix0:ix1 + 1] |= hit.reshape(gx.shape)
            if R <= 0:
                continue
            for ring in [outline] + holes:
                n = len(ring)
                for k in range(n):
                    a, c = ring[k], ring[(k + 1) % n]
                    ix0, ix1, iy0, iy1 = self._window(min(a[0], c[0]) - R, min(a[1], c[1]) - R,
                                                      max(a[0], c[0]) + R, max(a[1], c[1]) + R)
                    if ix1 < ix0 or iy1 < iy0:
                        continue
                    gx, gy = np.meshgrid(self.x0 + np.arange(ix0, ix1 + 1) * self.g,
                                         self.y0 + np.arange(iy0, iy1 + 1) * self.g)
                    mask[iy0:iy1 + 1, ix0:ix1 + 1] |= _seg_dist(gx, gy, a, c) <= R

    def mark_circle(self, mask, cx, cy, r):
        ix0 = max(0, int(math.floor((cx - r - self.x0) / self.g)))
        ix1 = min(self.nx - 1, int(math.ceil((cx + r - self.x0) / self.g)))
        iy0 = max(0, int(math.floor((cy - r - self.y0) / self.g)))
        iy1 = min(self.ny - 1, int(math.ceil((cy + r - self.y0) / self.g)))
        if ix1 < ix0 or iy1 < iy0:
            return
        gx, gy = np.meshgrid(self.x0 + np.arange(ix0, ix1 + 1) * self.g, self.y0 + np.arange(iy0, iy1 + 1) * self.g)
        mask[iy0:iy1 + 1, ix0:ix1 + 1] |= np.hypot(gx - cx, gy - cy) <= r


# --------------------------------------------------------------------------- connectivity
def _is_via(t):
    return t.Type() == pcbnew.PCB_VIA_T


def net_clusters(b, netcode, plane_layers=()):
    """Connected clusters of a net's pads, tracks and vias. Items touching a zone of the net on one of
    `plane_layers` (vias, through-hole pads) join through it."""
    pads = [p for fp in b.GetFootprints() for p in fp.Pads() if p.GetNetCode() == netcode]
    trs = [t for t in b.GetTracks() if t.GetNetCode() == netcode]
    items = pads + trs
    parent = list(range(len(items)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    idx = {id(it): k for k, it in enumerate(items)}
    tol = MM(0.001)
    for t in trs:
        k = idx[id(t)]
        if _is_via(t):
            pts = [(t.GetPosition(), None)]
        else:
            pts = [(t.GetStart(), t.GetLayer()), (t.GetEnd(), t.GetLayer())]
        for pt, lay in pts:
            for p in pads:
                if (lay is None and (p.IsOnLayer(pcbnew.F_Cu) or p.IsOnLayer(pcbnew.B_Cu) or
                                     p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH)) or (lay is not None and p.IsOnLayer(lay)):
                    if p.HitTest(pt, tol):
                        union(k, idx[id(p)])
            for o in trs:
                if o is t:
                    continue
                if _is_via(o):
                    if o.HitTest(pt, tol):
                        union(k, idx[id(o)])
                elif lay is None or o.GetLayer() == lay:
                    if o.HitTest(pt, tol):
                        union(k, idx[id(o)])
    if plane_layers:
        planes = [z for z in b.Zones() if not z.GetIsRuleArea() and z.GetNetCode() == netcode
                  and any(z.IsOnLayer(lay) for lay in plane_layers)]
        if planes:
            members = [k for k, it in enumerate(items)
                       if (isinstance(it, pcbnew.PAD) and it.GetAttribute() == pcbnew.PAD_ATTRIB_PTH) or
                       (not isinstance(it, pcbnew.PAD) and _is_via(it))]
            for k in members[1:]:
                union(members[0], k)
    groups = {}
    for k, it in enumerate(items):
        groups.setdefault(find(k), []).append(it)
    return list(groups.values())


# --------------------------------------------------------------------------- router
class Router:
    def __init__(self, b, layers=(pcbnew.F_Cu, pcbnew.In2_Cu, pcbnew.B_Cu), via_layers=None, grid=0.025,
                 margin=0.6, via_cost_mm=1.2, plane_layers=(pcbnew.In1_Cu,), log=print):
        self.b = b
        self.layers = list(layers)
        self.via_layers = list(via_layers or [pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu])
        self.g = grid
        self.margin = margin  # in grid cells
        self.via_cost = via_cost_mm / grid
        self.plane_layers = plane_layers
        self.log = log
        self.max_expand = 2_500_000
        self.protect_classes = {"Power", "Ground", "Supply"}
        # never ripped: ground, the crystal, the USB and NFC pairs (their routing is length/pair sensitive)
        self.protect_nets = {"GND", "XL1", "XL2", "USB_DP", "USB_DM", "NFC1", "NFC2"}
        self.low_priority = ("TP_SPARE",)  # spare test pads may not rip other nets up
        self.rip_cost = 150.0  # per cell entered through rippable copper (x (1 + 3 x times the net was ripped))
        self.rip_history = {}  # net name -> times ripped (kept by finish() across rounds)
        self.rip_limit = 3
        ds = b.GetDesignSettings()
        self.hole_clr = TO_MM(ds.m_HoleClearance)
        self.hole2hole = TO_MM(ds.m_HoleToHoleMin)
        self.edge_clr = TO_MM(ds.m_CopperEdgeClearance)
        self.outline = pcbnew.SHAPE_POLY_SET()
        b.GetBoardPolygonOutlines(self.outline)
        self.added = []  # (netname, [uuids]) per connection
        self.ripped = set()

    def netclass(self, net):
        ns = self.b.GetDesignSettings().m_NetSettings
        nc = ns.GetNetClassByName(net.GetNetClassName())
        return TO_MM(nc.GetTrackWidth()), TO_MM(nc.GetClearance()), TO_MM(nc.GetViaDiameter()), TO_MM(nc.GetViaDrill())

    # ---- obstacle rasters
    def rippable(self, it):
        """Other-net copper the rip-up pass may remove: unlocked signal tracks and vias (not pads, not GND, not the
        power nets, not locked fan-out)."""
        if isinstance(it, pcbnew.PAD) or it.IsLocked():
            return False
        if self.rip_history.get(it.GetNetname(), 0) >= self.rip_limit:
            return False
        return it.GetNetClassName() not in self.protect_classes and \
            it.GetNetname().split("/")[-1] not in self.protect_nets

    def rasters(self, grid, netcode, w, clr, via_d, via_drill, margin=None, soft=False):
        """(blocked per layer, via blocked) — with soft=True also (soft per layer, soft via): cells blocked only
        by rippable copper."""
        m = (self.margin if margin is None else margin) * grid.g
        L = len(self.layers)
        blk = np.zeros((L, grid.ny, grid.nx), bool)
        vblk = np.zeros((grid.ny, grid.nx), bool)
        soft_nets = {}  # net name -> (track mask per layer, via mask)
        x0, y0 = grid.x0, grid.y0
        x1, y1 = grid.x0 + grid.nx * grid.g, grid.y0 + grid.ny * grid.g
        span = max(w / 2, via_d / 2) + clr + 1.0

        def near(bb):
            return not (TO_MM(bb.GetRight()) < x0 - span or TO_MM(bb.GetLeft()) > x1 + span or
                        TO_MM(bb.GetBottom()) < y0 - span or TO_MM(bb.GetTop()) > y1 + span)

        Rt, Rv = clr + w / 2 + m, clr + via_d / 2 + m
        copper = [p for fp in self.b.GetFootprints() for p in fp.Pads()] + list(self.b.GetTracks())
        for it in copper:
            if not near(it.GetBoundingBox()):
                continue
            other = it.GetNetCode() != netcode
            if isinstance(it, pcbnew.PAD) and it.GetDrillSize().x > 0:
                hx, hy = TO_MM(it.GetPosition().x), TO_MM(it.GetPosition().y)
                hr = TO_MM(max(it.GetDrillSize().x, it.GetDrillSize().y)) / 2
                grid.mark_circle(vblk, hx, hy, hr + self.hole2hole + via_drill / 2 + m)
                if it.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                    for k in range(L):
                        grid.mark_circle(blk[k], hx, hy, hr + self.hole_clr + w / 2 + m)
                    grid.mark_circle(vblk, hx, hy, hr + self.hole_clr + via_d / 2 + m)
            if not isinstance(it, pcbnew.PAD) and _is_via(it):
                hx, hy = TO_MM(it.GetPosition().x), TO_MM(it.GetPosition().y)
                grid.mark_circle(vblk, hx, hy, TO_MM(it.GetDrillValue()) / 2 + self.hole2hole + via_drill / 2 + m)
            if isinstance(it, pcbnew.PAD) and it.GetAttribute() in (pcbnew.PAD_ATTRIB_SMD, pcbnew.PAD_ATTRIB_CONN):
                for lay in (pcbnew.F_Cu, pcbnew.B_Cu):
                    if it.IsOnLayer(lay):
                        grid.mark_polys(vblk, _item_polys(it, lay), via_d / 2 + m)
            if not other:
                continue
            if soft and self.rippable(it):
                if it.GetNetname() not in soft_nets:
                    soft_nets[it.GetNetname()] = (np.zeros((L, grid.ny, grid.nx), bool), np.zeros((grid.ny, grid.nx), bool))
                tb, vb = soft_nets[it.GetNetname()]
            else:
                tb, vb = blk, vblk
            for k, lay in enumerate(self.layers):
                if it.IsOnLayer(lay):
                    polys = _item_polys(it, lay)
                    grid.mark_polys(tb[k], polys, Rt)
            for lay in self.via_layers:
                if it.IsOnLayer(lay) and not (isinstance(it, pcbnew.PAD) and lay in self.plane_layers):
                    grid.mark_polys(vb, _item_polys(it, lay), Rv)
        # other-net zones on the routing layers (pours); planes of other nets on via layers
        for z in self.b.Zones():
            if z.GetIsRuleArea():
                bbz = z.GetBoundingBox()
                if not near(bbz):
                    continue
                polys = _poly_arrays(z.Outline())
                for k, lay in enumerate(self.layers):
                    if z.GetDoNotAllowTracks() and z.IsOnLayer(lay):
                        grid.mark_polys(blk[k], polys, w / 2 + m)
                if z.GetDoNotAllowVias() and any(z.IsOnLayer(lay) for lay in self.via_layers):
                    grid.mark_polys(vblk, polys, via_d / 2 + m)
                continue
            if z.GetNetCode() == netcode:
                continue
            for k, lay in enumerate(self.layers):
                if z.IsOnLayer(lay) and z.HasFilledPolysForLayer(lay):
                    grid.mark_polys(blk[k], _poly_arrays(z.GetFilledPolysList(lay)), Rt)
        # board edge: outside the outline, or within the edge clearance of it
        edge_t = np.zeros((grid.ny, grid.nx), bool)
        edge_v = np.zeros((grid.ny, grid.nx), bool)
        polys = _poly_arrays(self.outline)
        inside = np.zeros((grid.ny, grid.nx), bool)
        grid.mark_polys(inside, polys, 0.0)
        grid.mark_polys(edge_t, polys, self.edge_clr + w / 2 + m, inside=False)
        grid.mark_polys(edge_v, polys, self.edge_clr + via_d / 2 + m, inside=False)
        for k in range(L):
            blk[k] |= ~inside | edge_t
        vblk |= ~inside | edge_v
        if soft:
            scost = np.zeros((L, grid.ny, grid.nx))
            svcost = np.zeros((grid.ny, grid.nx))
            for name, (tm, vm) in soft_nets.items():
                c = self.rip_cost * (1 + 3 * self.rip_history.get(name, 0))
                scost = np.maximum(scost, tm * c)
                svcost = np.maximum(svcost, vm * c)
            scost[blk] = 0
            svcost[vblk] = 0
            return blk, vblk, scost, svcost
        return blk, vblk

    def masks(self, grid, cluster, w, clr):
        """Per-layer cells covered by a cluster's copper (start or goal set) and its anchor points."""
        L = len(self.layers)
        mk = np.zeros((L, grid.ny, grid.nx), bool)
        pts = []
        for it in cluster:
            if isinstance(it, pcbnew.PAD):
                pts.append((TO_MM(it.GetPosition().x), TO_MM(it.GetPosition().y)))
            elif _is_via(it):
                pts.append((TO_MM(it.GetPosition().x), TO_MM(it.GetPosition().y)))
            else:
                pts += [(TO_MM(it.GetStart().x), TO_MM(it.GetStart().y)), (TO_MM(it.GetEnd().x), TO_MM(it.GetEnd().y))]
            for k, lay in enumerate(self.layers):
                if it.IsOnLayer(lay):
                    polys = _item_polys(it, lay)
                    # a new track end must lie inside the copper by more than a grid step
                    tmp = np.zeros((grid.ny, grid.nx), bool)
                    grid.mark_polys(tmp, polys, 0.0)
                    mk[k] |= tmp
        return mk, pts

    @staticmethod
    def reachable(free, vfree, start, goal):
        """Can any start cell reach any goal cell? Free space labelled per layer (8-connected), layers joined at the
        cells where a via fits. Cheap (scipy), so hopeless searches are skipped."""
        from scipy import ndimage
        L = free.shape[0]
        labels, off = [], 0
        for k in range(L):
            lab, n = ndimage.label(free[k], structure=np.ones((3, 3), int))
            labels.append(np.where(lab > 0, lab + off, 0))
            off += n
        parent = np.arange(off + 1)

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a
        for a in range(L):
            for c in range(a + 1, L):
                m = vfree & (labels[a] > 0) & (labels[c] > 0)
                if not m.any():
                    continue
                pairs = np.unique(np.stack([labels[a][m], labels[c][m]], axis=1), axis=0)
                for la, lc in pairs:
                    ra, rc = find(int(la)), find(int(lc))
                    if ra != rc:
                        parent[ra] = rc
        src = {find(int(labels[k][y, x])) for k, y, x in zip(*np.nonzero(start)) if labels[k][y, x]}
        return any(find(int(labels[k][y, x])) in src for k, y, x in zip(*np.nonzero(goal)) if labels[k][y, x])

    def astar(self, grid, blk, vblk, src, dst, dst_pts, sblk=None, svblk=None):
        L, ny, nx = blk.shape
        free = ~blk
        soft = sblk if sblk is not None else np.zeros(blk.shape)  # extra cost per cell (rippable copper)
        vsoft = svblk if svblk is not None else np.zeros(vblk.shape)
        start = src & free
        goal = dst & free
        if not start.any() or not goal.any():
            return None
        if not (start & goal).any() and not self.reachable(free, ~vblk, start, goal):
            return None
        gk, gy_, gx_ = np.nonzero(goal)
        bx0, bx1, by0, by1 = int(gx_.min()), int(gx_.max()), int(gy_.min()), int(gy_.max())

        def h(iy, ix):  # distance to the goal cells' bounding box (admissible, cheap)
            dx = bx0 - ix if ix < bx0 else (ix - bx1 if ix > bx1 else 0)
            dy = by0 - iy if iy < by0 else (iy - by1 if iy > by1 else 0)
            return math.hypot(dx, dy)

        N = L * ny * nx
        gs = np.full(N, np.inf, dtype=np.float64)
        prev = np.full(N, -1, dtype=np.int64)
        heap = []
        ks, ys, xs = np.nonzero(start)
        for k, y, x in zip(ks, ys, xs):
            i = (k * ny + y) * nx + x
            gs[i] = 0.0
            heapq.heappush(heap, (h(y, x), 0.0, i))
        dirs = [(0, 1, 1.0), (1, 0, 1.0), (0, -1, 1.0), (-1, 0, 1.0),
                (1, 1, 1.4142), (1, -1, 1.4142), (-1, 1, 1.4142), (-1, -1, 1.4142)]
        closed = np.zeros(N, bool)
        found = -1
        expanded = 0
        while heap:
            f, gcur, i = heapq.heappop(heap)
            expanded += 1
            if expanded > self.max_expand:
                break
            if closed[i]:
                continue
            closed[i] = True
            k, rem = divmod(i, ny * nx)
            y, x = divmod(rem, nx)
            if goal[k, y, x]:
                found = i
                break
            for dy, dx, c in dirs:
                yy, xx = y + dy, x + dx
                if 0 <= yy < ny and 0 <= xx < nx and free[k, yy, xx]:
                    j = (k * ny + yy) * nx + xx
                    ng = gcur + c + soft[k, yy, xx]
                    if ng < gs[j]:
                        gs[j] = ng
                        prev[j] = i
                        heapq.heappush(heap, (ng + h(yy, xx), ng, j))
            if not vblk[y, x]:
                for kk in range(L):
                    if kk != k and free[kk, y, x]:
                        j = (kk * ny + y) * nx + x
                        ng = gcur + self.via_cost + 8 * vsoft[y, x]
                        if ng < gs[j]:
                            gs[j] = ng
                            prev[j] = i
                            heapq.heappush(heap, (ng + h(y, x), ng, j))
        if found < 0:
            return None
        if prev[found] < 0:  # start cell is already a goal cell: overlapping copper without a shared anchor
            k, rem = divmod(found, ny * nx)
            y, x = divmod(rem, nx)
            for dy, dx, _ in dirs:
                yy, xx = y + dy, x + dx
                if 0 <= yy < ny and 0 <= xx < nx and free[k, yy, xx] and (start[k, yy, xx] or goal[k, yy, xx]):
                    return [(k, y, x), (k, yy, xx)]
            return None
        path = []
        i = found
        while i >= 0:
            k, rem = divmod(i, ny * nx)
            y, x = divmod(rem, nx)
            path.append((k, y, x))
            i = prev[i]
        return path[::-1]

    @staticmethod
    def _los(free_k, a, b):
        """Straight segment a-b (grid coords) stays on free cells (sampled every half cell)."""
        (y0, x0), (y1, x1) = a, b
        n = int(max(abs(y1 - y0), abs(x1 - x0)) * 2) + 1
        ys = np.rint(np.linspace(y0, y1, n + 1)).astype(int)
        xs = np.rint(np.linspace(x0, x1, n + 1)).astype(int)
        return bool(free_k[ys, xs].all())

    def simplify(self, path, blk):
        """Split by layer, pull each run straight where the free cells allow; returns [(layer_k, [(y, x)...])]."""
        runs = []
        for k, y, x in path:
            if runs and runs[-1][0] == k:
                runs[-1][1].append((y, x))
            else:
                runs.append((k, [(y, x)]))
        out = []
        for k, pts in runs:
            free_k = ~blk[k]
            keep = [pts[0]]
            i = 0
            while i < len(pts) - 1:
                j = len(pts) - 1
                while j > i + 1 and not self._los(free_k, pts[i], pts[j]):
                    j -= 1
                keep.append(pts[j])
                i = j
            out.append((k, keep))
        return out

    def route_pair(self, net, ca, cb, pad_mm=4.0, margin=None, ripup=False):
        """Route between two clusters. Returns the new items, or None. With ripup=True, rippable copper of other
        nets may be crossed; what the new route conflicts with is removed (self.ripped gets the victims' nets)."""
        w, clr, via_d, via_drill = self.netclass(net)
        # window: the smaller cluster's box grown by the gap to the other cluster's nearest anchor (a plane-sized
        # GND cluster or a long track would otherwise make it the whole board), then grown again if no path
        def box(cl):
            bbs = [it.GetBoundingBox() for it in cl]
            return (min(TO_MM(b_.GetLeft()) for b_ in bbs), min(TO_MM(b_.GetTop()) for b_ in bbs),
                    max(TO_MM(b_.GetRight()) for b_ in bbs), max(TO_MM(b_.GetBottom()) for b_ in bbs))
        bxa, bxb = box(ca), box(cb)
        area = lambda bx: (bx[2] - bx[0]) * (bx[3] - bx[1])  # noqa: E731
        small, other = (bxa, cb) if area(bxa) <= area(bxb) else (bxb, ca)
        # the other cluster's anchor nearest to the small cluster's box joins the window
        cx_, cy_ = (small[0] + small[2]) / 2, (small[1] + small[3]) / 2
        px, py = min(_anchors(other), key=lambda q: math.hypot(q[0] - cx_, q[1] - cy_))
        for padding in (pad_mm, pad_mm * 2.5):
            lo_x, lo_y = min(small[0], px) - padding, min(small[1], py) - padding
            hi_x, hi_y = max(small[2], px) + padding, max(small[3], py) + padding
            grid = Grid(lo_x, lo_y, hi_x, hi_y, self.g)
            src, _ = self.masks(grid, ca, w, clr)
            dst, dpts = self.masks(grid, cb, w, clr)
            if ripup:
                blk, vblk, sblk, svblk = self.rasters(grid, net.GetNetCode(), w, clr, via_d, via_drill, margin, soft=True)
                path = self.astar(grid, blk, vblk, src, dst, dpts, sblk, svblk)
                if path:
                    items = self.commit(net, grid, self.simplify(path, blk | (sblk > 0)), w, via_d, via_drill)
                    self.rip_conflicts(items, clr, margin)
                    return items
            else:
                blk, vblk = self.rasters(grid, net.GetNetCode(), w, clr, via_d, via_drill, margin)
                path = self.astar(grid, blk, vblk, src, dst, dpts)
                if path:
                    return self.commit(net, grid, self.simplify(path, blk), w, via_d, via_drill)
        return None

    def rip_conflicts(self, new_items, clr, margin=None):
        """Remove every rippable other-net track/via within clearance of the new items."""
        m = (self.margin if margin is None else margin) * self.g
        code = new_items[0].GetNetCode()
        victims = []
        for t in list(self.b.GetTracks()):
            if t.GetNetCode() == code or not self.rippable(t):
                continue
            for n in new_items:
                if _conflict(n, t, clr + m):
                    victims.append(t)
                    break
        names = sorted({t.GetNetname() for t in victims})
        # a small victim net (≤ 3 pads) goes whole, so it is re-routed clean; a larger one loses only the copper in
        # the way (its pieces are joined again by the next rounds)
        npads = {}
        for fp in self.b.GetFootprints():
            for pd in fp.Pads():
                npads[pd.GetNetname()] = npads.get(pd.GetNetname(), 0) + 1
        whole = {nm for nm in names if npads.get(nm, 0) <= 3}
        victim_ids = {t.m_Uuid.AsString() for t in victims}
        n = 0
        for t in list(self.b.GetTracks()):
            if self.rippable(t) and (t.GetNetname() in whole or t.m_Uuid.AsString() in victim_ids):
                self.b.Delete(t)
                n += 1
        for name in names:
            self.ripped.add(name)
            self.rip_history[name] = self.rip_history.get(name, 0) + 1
        self.log(f"    ripped up {n} items of {names}")

    def commit(self, net, grid, runs, w, via_d, via_drill):
        items = []
        for n, (k, pts) in enumerate(runs):
            lay = self.layers[k]
            for (ya, xa), (yb, xb) in zip(pts, pts[1:]):
                xa_, ya_ = grid.xy(xa, ya)
                xb_, yb_ = grid.xy(xb, yb)
                t = pcbnew.PCB_TRACK(self.b)
                t.SetStart(pcbnew.VECTOR2I(MM(xa_), MM(ya_)))
                t.SetEnd(pcbnew.VECTOR2I(MM(xb_), MM(yb_)))
                t.SetWidth(MM(w))
                t.SetLayer(lay)
                t.SetNet(net)
                self.b.Add(t)
                items.append(t)
            if n + 1 < len(runs):
                y, x = pts[-1]
                vx, vy = grid.xy(x, y)
                v = pcbnew.PCB_VIA(self.b)
                v.SetPosition(pcbnew.VECTOR2I(MM(vx), MM(vy)))
                v.SetWidth(MM(via_d))
                v.SetDrill(MM(via_drill))
                v.SetNet(net)
                self.b.Add(v)
                items.append(v)
        # anchor both ends the way a router would: at a pad, a via centre or a track end (a track entered part-way
        # along is split there), so the post-route clean-up does not take the joint for an open stub
        if runs:
            k0, pts0 = runs[0]
            k1, pts1 = runs[-1]
            for k, (y, x) in ((k0, pts0[0]), (k1, pts1[-1])):
                xx, yy = grid.xy(x, y)
                items += self._anchor(net, pcbnew.VECTOR2I(MM(xx), MM(yy)), self.layers[k], w, items)
        self.added.append((net.GetNetname(), [t.m_Uuid.AsString() for t in items]))
        return items

    def _anchor(self, net, pt, layer, w, new_items):
        return anchor_end(self.b, net, pt, layer, w, {t.m_Uuid.AsString() for t in new_items})

    def open_connections(self, skip=(), only=None):
        """[(net, cluster_a, cluster_b)] nearest-first between the clusters of every net with more than one
        (only the nets in `only`, when given: KiCad's own list of unconnected nets)."""
        todo = []
        for code, net in self.b.GetNetsByNetcode().items():
            if code == 0 or net.GetNetname() in skip or (only is not None and net.GetNetname() not in only):
                continue
            cl = net_clusters(self.b, code, self.plane_layers)
            if len(cl) < 2:
                continue
            # join the largest cluster with its nearest neighbour first (Prim's order)
            cl.sort(key=len, reverse=True)
            tree, rest = [cl[0]], cl[1:]
            while rest:
                best = min(((_dist(a, c), ai, ci) for ai, a in enumerate(tree) for ci, c in enumerate(rest)),
                           key=lambda t: t[0])
                _, ai, ci = best
                todo.append((net, tree[ai], rest[ci]))
                tree.append(rest.pop(ci))
        return todo


def anchor_end(b, net, pt, layer, w, exclude=()):
    """Extra copper so that a track end at `pt` joins its net at an anchor the post-route clean-up recognises: a pad
    (nothing to do), a via centre (a short track to it) or a track end (a track entered part-way along is split at
    the nearest point of its centreline, plus a short track to that point). Returns the new items."""
    code, tol = net.GetNetCode(), MM(0.002)
    for fp in b.GetFootprints():
        for pd in fp.Pads():
            if pd.GetNetCode() == code and pd.IsOnLayer(layer) and pd.HitTest(pt):
                return []
    olds = [t for t in b.GetTracks() if t.GetNetCode() == code and t.m_Uuid.AsString() not in exclude]

    def seg(a, c):
        t = pcbnew.PCB_TRACK(b)
        t.SetStart(a)
        t.SetEnd(c)
        t.SetWidth(MM(w) if isinstance(w, float) else w)
        t.SetLayer(layer)
        t.SetNet(net)
        b.Add(t)
        return t
    for o in olds:
        if o.Type() == pcbnew.PCB_VIA_T and o.HitTest(pt, 0):
            c = o.GetPosition()
            return [] if (c - pt).EuclideanNorm() <= tol else [seg(pt, c)]
    for o in olds:
        if o.Type() == pcbnew.PCB_VIA_T or o.GetLayer() != layer or not o.HitTest(pt, 0):
            continue
        a, c = o.GetStart(), o.GetEnd()
        if (a - pt).EuclideanNorm() <= tol or (c - pt).EuclideanNorm() <= tol:
            return []
        q = pcbnew.SEG(a, c).NearestPoint(pt)
        if (q - a).EuclideanNorm() <= tol or (q - c).EuclideanNorm() <= tol:
            end = a if (q - a).EuclideanNorm() <= tol else c
            return [seg(pt, end)]
        o.SetEnd(q)  # split the existing track at the joint
        tail = pcbnew.PCB_TRACK(b)
        tail.SetStart(q)
        tail.SetEnd(c)
        tail.SetWidth(o.GetWidth())
        tail.SetLayer(o.GetLayer())
        tail.SetNet(o.GetNet())
        tail.SetLocked(o.IsLocked())
        b.Add(tail)
        return [] if (q - pt).EuclideanNorm() <= tol else [seg(pt, q)]
    return []


def anchor_all(b):
    """Normalise every track joint on the board: a track end that only touches its net part-way along another
    track or off-centre in a via gets an anchor (anchor_end). Returns the number of joints fixed."""
    tol = MM(0.002)
    fixed = 0
    segs = [t for t in b.GetTracks() if t.Type() != pcbnew.PCB_VIA_T]
    for t in segs:
        for pt in (t.GetStart(), t.GetEnd()):
            code, layer = t.GetNetCode(), t.GetLayer()
            joined = False
            for o in b.GetTracks():
                if o.GetNetCode() != code or o.m_Uuid.AsString() == t.m_Uuid.AsString():
                    continue
                if o.Type() == pcbnew.PCB_VIA_T:
                    if (o.GetPosition() - pt).EuclideanNorm() <= tol:
                        joined = True
                        break
                elif o.GetLayer() == layer and ((o.GetStart() - pt).EuclideanNorm() <= tol or
                                                (o.GetEnd() - pt).EuclideanNorm() <= tol):
                    joined = True
                    break
            if joined:
                continue
            added = anchor_end(b, t.GetNet(), pt, layer, t.GetWidth(), {t.m_Uuid.AsString()})
            fixed += 1 if added else 0
    return fixed


def _seg_seg(a0, a1, b0, b1):
    """Distance between segments a0-a1 and b0-b1 (mm tuples)."""
    def pd(p, q0, q1):
        return float(_seg_dist(np.array(p[0]), np.array(p[1]), q0, q1))
    # segments intersect?
    def orient(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    o1, o2, o3, o4 = orient(a0, a1, b0), orient(a0, a1, b1), orient(b0, b1, a0), orient(b0, b1, a1)
    if (o1 > 0) != (o2 > 0) and (o3 > 0) != (o4 > 0):
        return 0.0
    return min(pd(a0, b0, b1), pd(a1, b0, b1), pd(b0, a0, a1), pd(b1, a0, a1))


def _geom(t):
    if _is_via(t):
        p = (TO_MM(t.GetPosition().x), TO_MM(t.GetPosition().y))
        return None, p, p, TO_MM(t.GetWidth(pcbnew.F_Cu)) / 2
    return (t.GetLayer(), (TO_MM(t.GetStart().x), TO_MM(t.GetStart().y)), (TO_MM(t.GetEnd().x), TO_MM(t.GetEnd().y)),
            TO_MM(t.GetWidth()) / 2)


def _conflict(a, b, clr):
    la, a0, a1, ra = _geom(a)
    lb, b0, b1, rb = _geom(b)
    if la is not None and lb is not None and la != lb:
        return False
    return _seg_seg(a0, a1, b0, b1) < ra + rb + clr


def _anchors(cluster):
    pts = []
    for it in cluster:
        if isinstance(it, pcbnew.PAD) or _is_via(it):
            pts.append((TO_MM(it.GetPosition().x), TO_MM(it.GetPosition().y)))
        else:
            pts += [(TO_MM(it.GetStart().x), TO_MM(it.GetStart().y)), (TO_MM(it.GetEnd().x), TO_MM(it.GetEnd().y))]
    return pts


def _centroid(cluster):
    p = np.array(_anchors(cluster))
    return float(p[:, 0].mean()), float(p[:, 1].mean())


def _dist(a, b):
    pa, pb = np.array(_anchors(a)), np.array(_anchors(b))
    d = np.hypot(pa[:, None, 0] - pb[None, :, 0], pa[:, None, 1] - pb[None, :, 1])
    return float(d.min())


def drc_uuids(path):
    """UUIDs of the items in every DRC violation (errors only) and the unconnected count."""
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "drc.json")
        # zones refilled first (on a copy), or new vias collide with the stale plane fill
        tmp = os.path.join(td, os.path.basename(path))
        b = pcbnew.LoadBoard(path)
        pcbnew.ZONE_FILLER(b).Fill(b.Zones())
        pcbnew.SaveBoard(tmp, b)
        subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--severity-error", "-o", out, tmp],
                       capture_output=True, text=True)
        d = json.load(open(out))
    bad = set()
    for v in d.get("violations", []):
        for it in v.get("items", []):
            bad.add(it.get("uuid"))
    open_nets = set()
    for u in d.get("unconnected_items", []):
        for it in u.get("items", []):
            desc = it.get("description", "")
            if "[" in desc and "]" in desc:
                open_nets.add(desc[desc.index("[") + 1:desc.index("]")])
    return bad, len(d.get("unconnected_items", [])), open_nets


def finish(path, log=print, grid=0.025, margin=0.6, skip=(), max_rounds=30, max_ripups=40):
    """Route every open connection of the board at `path` (in place). Returns the remaining unconnected count.

    Each round re-reads the board, routes every open connection it can without disturbing other nets, then checks
    the new copper with KiCad's DRC (zones refilled) and removes any connection DRC rejects; that net gets a wider
    grid margin next time. A round that routes nothing rips up: the first connection still without a path may
    cross unlocked signal copper of other nets, which is removed and re-routed in the following rounds."""
    import pcbgen
    pcbgen.unique_uuids(path)  # DRC reports resolve items by UUID
    net_margin = {}
    rip_history = {}
    ripups = 0
    _, remaining, open_nets = drc_uuids(path)
    for rnd in range(max_rounds):
        b = pcbnew.LoadBoard(path)
        r = Router(b, grid=grid, margin=margin, log=log)
        r.rip_history = rip_history
        todo = sorted(r.open_connections(skip=skip, only=open_nets), key=lambda t: _dist(t[1], t[2]))
        if not todo:
            if remaining:
                log(f"finish_route: KiCad reports {remaining} unconnected on {sorted(open_nets)}, "
                    "but no split clusters were found there")
            return remaining
        log(f"finish_route round {rnd + 1}: {len(todo)} open connections")
        routed, failed, ripped = 0, [], False
        for name in dict.fromkeys(n.GetNetname() for n, _, _ in todo):  # nets, nearest connection first
            for _ in range(200):
                conns = sorted(r.open_connections(skip=skip, only={name}), key=lambda t: _dist(t[1], t[2]))
                if not conns:
                    break
                net, ca, cb = conns[0]
                items = r.route_pair(net, ca, cb, margin=net_margin.get(name, margin))
                if not items:
                    failed.append((net, ca, cb))
                    break
                routed += 1
                log(f"  {name:32s} routed ({len(items)} items)")
        if not routed and failed and ripups < max_ripups:
            # spare test pads rip others up only after every other open connection has tried and failed
            low = lambda n: n.GetNetname().split("/")[-1].startswith(r.low_priority)  # noqa: E731
            for net, ca, cb in sorted(failed, key=lambda f: low(f[0])):
                name = net.GetNetname()
                items = r.route_pair(net, ca, cb, margin=net_margin.get(name, margin), ripup=True)
                if items:
                    ripups += 1
                    ripped = True
                    log(f"  {name:32s} routed by rip-up ({len(items)} items)")
                    break
                log(f"  {name:32s} no path even with rip-up")
        pcbnew.SaveBoard(path, b)
        bad, _, _ = drc_uuids(path)
        b = pcbnew.LoadBoard(path)
        byid = {t.m_Uuid.AsString(): t for t in b.GetTracks()}
        rejected = 0
        for name, ids in r.added:
            if any(i in bad for i in ids):
                for i in ids:
                    if i in byid:
                        b.Delete(byid.pop(i))
                rejected += 1
                net_margin[name] = net_margin.get(name, margin) + 0.6
                log(f"  DRC rejected the new {name} connection: removed (margin -> {net_margin[name]:.1f} cells)")
        pcbnew.SaveBoard(path, b)
        _, remaining, open_nets = drc_uuids(path)
        log(f"finish_route round {rnd + 1}: {remaining} unconnected ({routed} routed, {rejected} rejected"
            f"{', rip-up' if ripped else ''})")
        if remaining == 0 or (not routed and not ripped and not rejected):
            break
    return remaining
