"""Greedy placement of support parts around their anchor ICs on a pcbnew board.

Fixed parts (LED ring, sensors, connectors, ICs) are placed explicitly by the
caller. Every other footprint is assigned to the anchor it shares the most
pads/nets with (or an explicit anchor) and placed at the nearest free spot to
the anchor pad it connects to, on the anchor's side, avoiding courtyards,
keep-out shapes and the board edge.
"""

from __future__ import annotations

import math

import pcbnew

MM = pcbnew.FromMM
TO_MM = pcbnew.ToMM


def _bbox_mm(fp, margin=0.15):
    bb = fp.GetBoundingBox(False)
    return (TO_MM(bb.GetLeft()) - margin, TO_MM(bb.GetTop()) - margin,
            TO_MM(bb.GetRight()) + margin, TO_MM(bb.GetBottom()) + margin)


def _boxes_mm(fp, margin=0.15, cell=0.5):
    """Boxes covering a footprint for occupancy. A large part at an odd angle (the module at -55 deg) would block
    twice its area as one axis-aligned box, so its courtyard is covered by one box per 0.5 mm row instead."""
    ang = fp.GetOrientationDegrees() % 90.0
    if fp.GetPadCount() < 20 or min(ang, 90.0 - ang) < 0.5:
        return [_bbox_mm(fp, margin)]
    fp.BuildCourtyardCaches()
    poly = fp.GetCourtyard(pcbnew.B_CrtYd if fp.IsFlipped() else pcbnew.F_CrtYd)
    if poly.OutlineCount() == 0:
        return [_bbox_mm(fp, margin)]
    l, t, r, b = _bbox_mm(fp, 0.0)
    acc = MM(margin + cell * 0.71)  # a cell is kept when its centre is within margin + half its diagonal
    boxes = []
    y = t
    while y < b:
        xs = []
        x = l
        while x < r:
            if poly.Contains(pcbnew.VECTOR2I(MM(x + cell / 2), MM(y + cell / 2)), -1, acc):
                xs.append(x)
            x += cell
        if xs:
            boxes.append((min(xs) - margin, y - margin, max(xs) + cell + margin, y + cell + margin))
        y += cell
    return boxes or [_bbox_mm(fp, margin)]


def _overlap(a, b):
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


class Placer:
    def __init__(self, board, inside, keepouts=None, power_nets=("GND",)):
        """inside(x, y, side) -> bool: is the point a legal place on this side.

        keepouts: list of (side, predicate(x, y) -> bool[, allow(fp) -> bool]) regions that must stay empty
        (except for footprints the optional allow() exempts, e.g. low-profile parts).
        """
        self.board = board
        self.inside = inside
        self.keepouts = keepouts or []
        self.power_nets = set(power_nets)
        self.occupied = {"F": [], "B": []}
        # optional fp -> boxes override, for a part whose bounding box is mostly empty board (a shield's headers)
        self.boxes_for = None

    @staticmethod
    def side(fp):
        return "B" if fp.IsFlipped() else "F"

    def mark(self, fp):
        boxes = self.boxes_for(fp) if self.boxes_for else None
        for box in boxes or _boxes_mm(fp):
            self.occupied[self.side(fp)].append((fp.GetReference(), box))
        # through-hole / NPTH pads (e.g. Tag-Connect alignment holes) block the other side too
        if any(p.GetAttribute() != pcbnew.PAD_ATTRIB_SMD for p in fp.Pads()):
            other = "B" if self.side(fp) == "F" else "F"
            for p in fp.Pads():
                if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD:
                    continue
                bb = p.GetBoundingBox()
                self.occupied[other].append((fp.GetReference(), (TO_MM(bb.GetLeft()) - 0.4, TO_MM(bb.GetTop()) - 0.4,
                                                                  TO_MM(bb.GetRight()) + 0.4, TO_MM(bb.GetBottom()) + 0.4)))

    def free(self, fp):
        side = self.side(fp)
        box = _bbox_mm(fp)
        corners = [(box[0], box[1]), (box[2], box[1]), (box[0], box[3]), (box[2], box[3])]
        if not all(self.inside(x, y, side) for x, y in corners):
            return False
        for k in self.keepouts:  # (side, predicate) or (side, predicate, allow(fp)) for parts exempt from it
            kside, pred = k[0], k[1]
            if len(k) > 2 and k[2](fp):
                continue
            if kside in (side, "*") and any(pred(x, y) for x, y in corners + [((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)]):
                return False
        return not any(_overlap(box, b) for _, b in self.occupied[side])

    def place_near(self, fp, tx, ty, side, max_r=25.0, step=0.25, rotations=(0, 90)):
        if (side == "B") != fp.IsFlipped():
            fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
        r = 0.0
        while r <= max_r:
            n = max(1, int(2 * math.pi * r / step)) if r > 0 else 1
            for k in range(n):
                a = 2 * math.pi * k / n
                x, y = tx + r * math.cos(a), ty + r * math.sin(a)
                for rot in rotations:
                    fp.SetOrientationDegrees(rot)
                    fp.SetPosition(pcbnew.VECTOR2I(MM(x), MM(y)))
                    if self.free(fp):
                        self.mark(fp)
                        return True
            r += step
        return False

    def anchor_for(self, fp, anchors):
        """Pick the anchor sharing the most non-ground nets (ties: any net)."""
        nets = {p.GetNetname() for p in fp.Pads() if p.GetNetname()}
        best, score = None, (0, 0)
        for a in anchors:
            anets = {p.GetNetname() for p in a.Pads() if p.GetNetname()}
            common = nets & anets
            s = (len(common - self.power_nets), len(common))
            if s > score:
                best, score = a, s
        return best

    def target(self, fp, anchor):
        nets = {p.GetNetname() for p in fp.Pads() if p.GetNetname()}
        pads = [p for p in anchor.Pads() if p.GetNetname() in nets - self.power_nets] or \
               [p for p in anchor.Pads() if p.GetNetname() in nets] or list(anchor.Pads())
        xs = [TO_MM(p.GetPosition().x) for p in pads]
        ys = [TO_MM(p.GetPosition().y) for p in pads]
        return sum(xs) / len(xs), sum(ys) / len(ys)
