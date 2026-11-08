"""Reference-designator placement on the silkscreen.

Each visible reference moves to the nearest spot around its footprint that clears every pad
(plus mask expansion), all other silk, the references placed before it and the board edge.
References that fit nowhere are hidden (they remain on the Fab layer drawings).
"""

from __future__ import annotations

import math

import pcbnew

MM = pcbnew.FromMM


def _mm_box(bb, grow=0.0):
    return (pcbnew.ToMM(bb.GetX()) - grow, pcbnew.ToMM(bb.GetY()) - grow,
            pcbnew.ToMM(bb.GetRight()) + grow, pcbnew.ToMM(bb.GetBottom()) + grow)


def _hit(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _edge_points(board, step=0.2):
    pts = []
    for d in board.GetDrawings():
        if d.GetLayer() != pcbnew.Edge_Cuts or not isinstance(d, pcbnew.PCB_SHAPE):
            continue
        poly = pcbnew.SHAPE_POLY_SET()
        d.TransformShapeToPolygon(poly, pcbnew.Edge_Cuts, 0, MM(0.01), pcbnew.ERROR_INSIDE)
        for i in range(poly.OutlineCount()):
            o = poly.Outline(i)
            n = o.PointCount()
            for k in range(n):
                p, q = o.CPoint(k), o.CPoint((k + 1) % n)
                x0, y0, x1, y1 = (pcbnew.ToMM(v) for v in (p.x, p.y, q.x, q.y))
                m = max(1, int(math.hypot(x1 - x0, y1 - y0) / step))
                pts += [(x0 + (x1 - x0) * j / m, y0 + (y1 - y0) * j / m) for j in range(m)]
    return pts


def _shape_boxes(d, grow):
    """Obstacle boxes for a silk drawing.  A circle blocks only along its ring: as one bounding box, a large guide
    circle (a panel outline) blocks every spot inside it and pushes free labels off the board."""
    if isinstance(d, pcbnew.PCB_SHAPE) and d.GetShape() == pcbnew.SHAPE_T_CIRCLE:
        c, r = d.GetCenter(), pcbnew.ToMM(d.GetRadius())
        cx, cy, w = pcbnew.ToMM(c.x), pcbnew.ToMM(c.y), pcbnew.ToMM(d.GetWidth()) / 2 + grow
        n = max(8, int(2 * math.pi * r / 0.5))
        return [(cx + r * math.cos(2 * math.pi * k / n) - w, cy + r * math.sin(2 * math.pi * k / n) - w,
                 cx + r * math.cos(2 * math.pi * k / n) + w, cy + r * math.sin(2 * math.pi * k / n) + w)
                for k in range(n)]
    return [_mm_box(d.GetBoundingBox(), grow)]


def _inside(box, outline):
    """Every corner of the box on the board (the edge test alone lets a label wander off it)."""
    return all(outline.Contains(pcbnew.VECTOR2I(MM(x), MM(y))) for x in box[0::2] for y in box[1::2])


def _edge_clear(box, pts, margin):
    x0, y0, x1, y1 = box
    for x, y in pts:
        dx = max(x0 - x, 0, x - x1)
        dy = max(y0 - y, 0, y - y1)
        if dx * dx + dy * dy < margin * margin:
            return False
    return True


def clip_footprint_silk(board, edge_pts, outline, margin=0.25):
    """Shorten footprint silk lines that run past (or too close to) the board edge, e.g. a connector overhanging
    the outline. Returns the number of lines changed."""
    def good(p):
        x, y = pcbnew.ToMM(p.x), pcbnew.ToMM(p.y)
        return outline.Contains(p) and _edge_clear((x, y, x, y), edge_pts, margin)

    n = 0
    for fp in board.GetFootprints():
        for g in list(fp.GraphicalItems()):
            if g.GetLayer() not in (pcbnew.F_SilkS, pcbnew.B_SilkS) or not isinstance(g, pcbnew.PCB_SHAPE) \
                    or g.GetShape() != pcbnew.SHAPE_T_SEGMENT:
                continue
            a, b = g.GetStart(), g.GetEnd()
            ga, gb = good(a), good(b)
            if ga and gb:
                continue
            if not ga and not gb:
                fp.Remove(g)
                n += 1
                continue
            inside, outside = (a, b) if ga else (b, a)
            for _ in range(30):  # bisect along the line for the last point that is still clear of the edge
                mid = pcbnew.VECTOR2I((inside.x + outside.x) // 2, (inside.y + outside.y) // 2)
                if good(mid):
                    inside = mid
                else:
                    outside = mid
            if ga:
                g.SetEnd(inside)
            else:
                g.SetStart(inside)
            n += 1
    return n


def place_refs(board, height=0.8, thickness=0.15, gap=0.15, mask=0.1, edge=0.3, max_off=3.0, hide=("H", "FID"),
               clip_silk=False):
    outline = pcbnew.SHAPE_POLY_SET()
    board.GetBoardPolygonOutlines(outline)
    edge_pts = _edge_points(board)
    if clip_silk:  # off by default: an edited footprint shows up as a library mismatch in DRC
        clip_footprint_silk(board, edge_pts, outline)
    sides = {"F": (pcbnew.F_SilkS, pcbnew.F_Cu), "B": (pcbnew.B_SilkS, pcbnew.B_Cu)}
    obstacles = {"F": [], "B": []}
    for side, (silk, cu) in sides.items():
        for fp in board.GetFootprints():
            for pad in fp.Pads():
                if pad.IsOnLayer(cu) or pad.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
                    obstacles[side].append(_mm_box(pad.GetBoundingBox(), mask + gap))
            for g in fp.GraphicalItems():
                if g.GetLayer() == silk:
                    obstacles[side].append(_mm_box(g.GetBoundingBox(), gap))
            for f in (fp.Value(),):
                if f.IsVisible() and f.GetLayer() == silk:
                    obstacles[side].append(_mm_box(f.GetBoundingBox(), gap))
        for d in board.GetDrawings():
            if d.GetLayer() == silk and not isinstance(d, pcbnew.PCB_TEXT):
                obstacles[side] += _shape_boxes(d, gap)
    # free board texts (labels, title) keep their spot if it is clear, else move to the nearest clear one
    for d in board.GetDrawings():
        if not isinstance(d, pcbnew.PCB_TEXT) or d.GetLayer() not in (pcbnew.F_SilkS, pcbnew.B_SilkS):
            continue
        side = "F" if d.GetLayer() == pcbnew.F_SilkS else "B"
        p0 = d.GetPosition()
        tb = _mm_box(d.GetBoundingBox())
        ox, oy = pcbnew.ToMM(p0.x), pcbnew.ToMM(p0.y)
        for r in [0.0] + [0.25 * k for k in range(1, 41)]:
            spot = None
            for k in range(max(1, int(2 * math.pi * r / 0.25))):
                a = 2 * math.pi * k / max(1, int(2 * math.pi * r / 0.25))
                dx, dy = r * math.cos(a), r * math.sin(a)
                box = (tb[0] + dx, tb[1] + dy, tb[2] + dx, tb[3] + dy)
                if not any(_hit(box, o) for o in obstacles[side]) and _edge_clear(box, edge_pts, edge)                         and _inside(box, outline):
                    spot = (dx, dy, box)
                    break
            if spot:
                d.SetPosition(pcbnew.VECTOR2I(MM(ox + spot[0]), MM(oy + spot[1])))
                obstacles[side].append(spot[2])
                break
        else:
            obstacles[side].append(tb)
    moved = hidden = 0
    # big parts first: they have the fewest good spots
    fps = sorted(board.GetFootprints(), key=lambda f: -f.GetBoundingBox(False).GetArea())
    for fp in fps:
        ref = fp.Reference()
        if not ref.IsVisible():
            continue
        if fp.GetReference().startswith(hide):
            ref.SetVisible(False)
            continue
        side = "B" if fp.IsFlipped() else "F"
        silk = sides[side][0]
        ref.SetLayer(silk)
        ref.SetMirrored(side == "B")
        ref.SetTextSize(pcbnew.VECTOR2I(MM(height), MM(height)))
        ref.SetTextThickness(MM(thickness))
        ref.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
        ref.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
        body = [_mm_box(p.GetBoundingBox()) for p in fp.Pads()]
        body += [_mm_box(g.GetBoundingBox()) for g in fp.GraphicalItems() if g.GetLayer() == silk]
        if not body:
            continue
        bx0, by0 = min(b[0] for b in body), min(b[1] for b in body)
        bx1, by1 = max(b[2] for b in body), max(b[3] for b in body)
        cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
        wide = (bx1 - bx0) >= (by1 - by0)
        best = None
        for angle in ((0, 90) if wide else (90, 0)):
            ref.SetTextAngleDegrees(angle)
            ref.SetPosition(pcbnew.VECTOR2I(MM(cx), MM(cy)))
            tb = _mm_box(ref.GetBoundingBox())
            hw, hh = (tb[2] - tb[0]) / 2, (tb[3] - tb[1]) / 2
            off = gap
            while off <= max_off and best is None:
                cands = [(cx, by0 - off - hh), (cx, by1 + off + hh), (bx0 - off - hw, cy), (bx1 + off + hw, cy),
                         (bx0 - off - hw, by0 - off - hh), (bx1 + off + hw, by0 - off - hh),
                         (bx0 - off - hw, by1 + off + hh), (bx1 + off + hw, by1 + off + hh)]
                for x, y in cands:
                    box = (x - hw, y - hh, x + hw, y + hh)
                    if not outline.Contains(pcbnew.VECTOR2I(MM(x), MM(y))):
                        continue
                    if any(_hit(box, o) for o in obstacles[side]) or not _edge_clear(box, edge_pts, edge):
                        continue
                    best = (angle, x, y, box)
                    break
                off += 0.25
            if best:
                break
        if best is None:
            ref.SetVisible(False)
            hidden += 1
            continue
        angle, x, y, box = best
        ref.SetTextAngleDegrees(angle)
        ref.SetPosition(pcbnew.VECTOR2I(MM(x), MM(y)))
        obstacles[side].append(box)
        moved += 1
    return moved, hidden
