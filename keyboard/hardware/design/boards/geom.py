"""Board-mm geometry shared by layout.py and the board modules.

Board mm: origin at the board's lower-left corner, +x right, **+y up**, seen from the top. KiCad's page has +y down:
P() maps board mm to page mm, B() back. The drill/place (aux) origin is the board origin, so the Gerbers and the CPL
use board mm directly.
"""

from __future__ import annotations

import math

import pcbnew

OX, OY = 100.0, 100.0          # page position of the board origin (mm)
MM = pcbnew.FromMM
TO = pcbnew.ToMM


def P(x, y):
    """board mm (+y up) -> page mm (+y down)"""
    return OX + x, OY - y


def B(X, Y):
    """page mm -> board mm"""
    return X - OX, OY - Y


def V(x, y):
    """board mm -> VECTOR2I"""
    X, Y = P(x, y)
    return pcbnew.VECTOR2I(MM(X), MM(Y))


def bxy(item):
    """board-mm position of a pad / footprint / via"""
    p = item.GetPosition()
    return B(TO(p.x), TO(p.y))


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def poly_page(pts):
    return [P(x, y) for x, y in pts]


def circle(cx, cy, r, n=48):
    return [(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n)) for k in range(n)]


def rounded_rect(x0, y0, x1, y1, r, n=8):
    """A rectangle with its four corners rounded to radius r (board mm, counter-clockwise)."""
    if r <= 0:
        return rect(x0, y0, x1, y1)
    out = []
    for cx, cy, a0 in ((x1 - r, y0 + r, -90), (x1 - r, y1 - r, 0), (x0 + r, y1 - r, 90), (x0 + r, y0 + r, 180)):
        for k in range(n + 1):
            a = math.radians(a0 + 90.0 * k / n)
            out.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return out


def inside_poly(x, y, pts):
    """Even-odd point-in-polygon test (board mm)."""
    c = False
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            c = not c
    return c


def dist_to_poly(x, y, pts):
    """Distance from a point to a closed polyline (board mm)."""
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
