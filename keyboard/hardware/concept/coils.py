#!/usr/bin/env python3
"""Planar spiral coils as polylines: a small generator that later boards can reuse for coil footprints and drawings.

What it gives (mm, radians, numpy only):

    Coil(turns, trace, space, r_in, layers=1, sides=0)   one coil spec: copper width and gap, the centreline radius
                                                         of the innermost turn, the number of stacked layers, and
                                                         the outline (0 = circular, 4 = square, 6, 8 = polygonal)
    spiral(r_in, pitch, turns, ...)                      the centreline of one Archimedean (or polygonal) spiral
    coil_layers(coil, centre)                            one Layer per copper layer, wound so that a current in the
                                                         series stack circulates the same way on every layer, plus
                                                         the vias that join them
    band(points, width)                                  the closed outline of a trace of that width
    trace_length(points)                                 copper length along a centreline
    current_sheet_inductance(coil)                       one layer's inductance from the current-sheet expression
                                                         (Mohan, Hershenson, Boyd and Lee, IEEE JSSC 1999): a simple
                                                         model of a coil in free space, no target, not measured
    doe_variants(), doe_layout()                         the about-20-variant set sketched for the rev A coil coupon
                                                         (keyboard/docs/concept.md sections 2.4 and 7)

    PY=/path/to/venv/bin/python
    $PY keyboard/hardware/concept/coils.py          # print the DOE set: turns, trace, layers, OD, length, model L

Status: CONCEPT TOOL. Nothing in keyboard/ is designed, built or measured (keyboard/docs/concept.md). The geometry
is exact for the parameters given, but the DOE parameters are illustrative: they are a plausible spread of turns,
trace and space, layers and diameter around a stock MX switch's footprint, not a decision, and nobody has checked
them against JLC's capabilities or an LDC1614-class converter's limits. The inductance helper is a textbook model
for a lone coil; the spring or slug above it, the other layers' mutual inductance and the board are not in it.

The stock MX numbers used for the DOE's keep-outs are the common MX PCB footprint (a 4.0 mm centre-post hole, pins
at (-3.81, 2.54) and (2.54, 5.08) mm from the centre, y away from the typist). The pad clearance is illustrative.
"""
import math
from dataclasses import dataclass

import numpy as np

MU0 = 4e-7 * math.pi

# MX footprint (common public values), mm, y away from the typist
MX_CENTRE_HOLE = 4.0
MX_PINS = ((-3.81, 2.54), (2.54, 5.08))
MX_PIN_HOLE = 1.5


@dataclass(frozen=True)
class Coil:
    """One planar coil. r_in is the centreline radius (or apothem, for a polygon) where the innermost turn starts;
    each turn steps out by pitch = trace + space. layers copies the spiral onto that many copper layers, in series."""
    turns: float
    trace: float
    space: float
    r_in: float
    layers: int = 1
    sides: int = 0
    tag: str = ""

    @property
    def pitch(self):
        return self.trace + self.space

    @property
    def r_out(self):
        """Centreline radius (apothem) where the outermost turn ends."""
        return self.r_in + self.turns * self.pitch

    @property
    def d_in(self):
        """Inner copper diameter (inner edge of the first turn)."""
        return 2 * (self.r_in - self.trace / 2)

    @property
    def d_out(self):
        """Outer copper diameter (outer edge of the last turn)."""
        return 2 * (self.r_out + self.trace / 2)

    def label(self, sep=" / "):
        t = f"{self.turns:g} t"
        w = f"{self.trace:.3f}".rstrip("0").rstrip(".") + " mm"
        n = f"{self.layers} L"
        return sep.join((t, w, n))


@dataclass
class Layer:
    index: int          # 0 = top copper
    points: np.ndarray  # (N, 2) centreline, in the order the current runs through the series stack
    ccw: bool           # winding sense of the spiral going outwards


def spiral(r_in, pitch, turns, ccw=True, end_angle=-math.pi / 2, sides=0, pts_per_turn=96, centre=(0.0, 0.0)):
    """Centreline of one spiral from the inner end outwards, as an (N, 2) array.

    The radius grows by `pitch` per turn. ccw=True winds anticlockwise going outwards (seen from the top). The whole
    spiral is turned so that its outer end lies at `end_angle` (default: -y, towards the typist, where the leads
    leave). sides=0 gives a smooth Archimedean spiral; sides=n >= 3 gives a polygonal spiral whose apothem grows by
    `pitch` per turn, with straight edges between corners (a square spiral for n = 4)."""
    total = 2 * math.pi * turns
    sgn = 1.0 if ccw else -1.0
    start = end_angle - sgn * total
    if sides == 0:
        n = max(int(math.ceil(turns * pts_per_turn)), 8)
        t = np.linspace(0.0, total, n + 1)
        r = r_in + pitch * t / (2 * math.pi)
        a = start + sgn * t
        pts = np.stack([r * np.cos(a), r * np.sin(a)], 1)
    else:
        step = 2 * math.pi / sides
        # corners sit half a side away from the side centres; the spiral starts and ends at a side centre
        k = np.arange(0, int(math.floor((total - step / 2) / step)) + 1)
        tc = step / 2 + k * step
        tc = tc[tc < total]
        t = np.concatenate([[0.0], tc, [total]])
        apo = r_in + pitch * t / (2 * math.pi)
        rad = apo.copy()
        rad[1:-1] = apo[1:-1] / math.cos(step / 2)            # a corner lies further out than the side centre
        a = start + sgn * t
        pts = np.stack([rad * np.cos(a), rad * np.sin(a)], 1)
    return pts + np.asarray(centre, float)


def coil_layers(coil, centre=(0.0, 0.0), pts_per_turn=96, end_angle=-math.pi / 2):
    """The copper of a series-stacked coil: a list of Layer and a list of via positions [(x, y, (layer_a, layer_b))].

    The current enters the top layer at its outer end and runs inward, drops through a via at the inner end, runs
    outward on the next layer, drops through a via at the outer end, and so on. Neighbouring layers are mirror-image
    spirals, so the current circulates the same way round on all of them and their fields add. A single-layer coil
    still needs a way out of its inner end: a via to the next layer, from where the return runs straight out (that
    return is the second entry when layers == 1)."""
    cx, cy = centre
    layers, vias = [], []
    for i in range(coil.layers):
        ccw = (i % 2 == 0)
        pts = spiral(coil.r_in, coil.pitch, coil.turns, ccw=ccw, end_angle=end_angle, sides=coil.sides,
                     pts_per_turn=pts_per_turn, centre=centre)
        inward = (i % 2 == 0)                      # top layer: outer end first, running inward
        layers.append(Layer(i, pts[::-1] if inward else pts, ccw))
        if i < coil.layers - 1:
            p = pts[0] if inward else pts[-1]      # inner end after an inward layer, outer end after an outward one
            vias.append((float(p[0]), float(p[1]), (i, i + 1)))
    if coil.layers == 1:
        p_in = layers[0].points[-1]
        vias.append((float(p_in[0]), float(p_in[1]), (0, 1)))
        # return on the next layer, straight out past the outer turn along end_angle
        r_end = coil.r_out + coil.pitch + coil.trace
        q = np.array([cx + r_end * math.cos(end_angle), cy + r_end * math.sin(end_angle)])
        mid = np.array([p_in[0], q[1]]) if abs(math.sin(end_angle)) > 0.5 else np.array([q[0], p_in[1]])
        layers.append(Layer(1, np.array([p_in, mid, q]), True))
    return layers, vias


def band(points, width):
    """Closed outline (M, 2) of a trace of `width` around an open centreline, with mitred joints (square ends)."""
    p = np.asarray(points, float)
    d = np.diff(p, axis=0)
    seg = d / (np.linalg.norm(d, axis=1, keepdims=True) + 1e-12)
    nrm = np.stack([-seg[:, 1], seg[:, 0]], 1)
    vn = np.vstack([nrm[:1], nrm[:-1] + nrm[1:], nrm[-1:]])
    vn /= np.linalg.norm(vn, axis=1, keepdims=True) + 1e-12
    # mitre length, limited so a sharp corner does not spike
    cosh = np.ones(len(p))
    cosh[1:-1] = np.clip(np.sum(vn[1:-1] * nrm[:-1], 1), 0.35, 1.0)
    off = vn * (width / 2 / cosh)[:, None]
    left, right = p + off, p - off
    return np.vstack([left, right[::-1]])


def trace_length(points):
    p = np.asarray(points, float)
    return float(np.sum(np.linalg.norm(np.diff(p, axis=0), axis=1)))


# current-sheet coefficients c1..c4 (Mohan et al. 1999, table 2); circle from the same paper
_SHEET = {0: (1.00, 2.46, 0.00, 0.20), 4: (1.27, 2.07, 0.18, 0.13), 6: (1.09, 2.23, 0.00, 0.17),
          8: (1.07, 2.29, 0.00, 0.19)}


def current_sheet_inductance(coil):
    """Inductance (H) of ONE layer of the coil in free space, from the current-sheet expression
    L = mu0 n^2 d_avg c1 / 2 (ln(c2 / rho) + c3 rho + c4 rho^2). A simple model, not measured. The mutual
    inductance between stacked layers, the target above the coil and the board are not included."""
    c1, c2, c3, c4 = _SHEET.get(coil.sides, _SHEET[0])
    d_out, d_in = coil.d_out, coil.d_in
    d_avg = (d_out + d_in) / 2 / 1000.0
    rho = (d_out - d_in) / (d_out + d_in)
    n = coil.turns
    return MU0 * n * n * d_avg * c1 / 2 * (math.log(c2 / rho) + c3 * rho + c4 * rho * rho)


# ---------------------------------------------------------------------------------------------------------------
# The rev A coil coupon's DOE (illustrative)
# ---------------------------------------------------------------------------------------------------------------
TRACES = (0.10, 0.125, 0.15, 0.20, 0.25)    # trace = space, mm (illustrative spread)
INNER_EDGE = 2.25        # inner copper edge: 0.25 mm outside the 4.0 mm MX centre-post hole (illustrative)
MX_OUTER_EDGE = 3.40     # outer copper edge that stays clear of the MX pin pads (illustrative clearance)
LARGE_OUTER_EDGE = 4.50  # the larger-diameter row (9 mm OD): for the slug-stem sites, whose footprint is not designed
ROWS = (
    dict(layers=1, outer=MX_OUTER_EDGE, sides=0, tag="1 layer, inside the MX pins"),
    dict(layers=2, outer=MX_OUTER_EDGE, sides=0, tag="2 layers, inside the MX pins"),
    dict(layers=4, outer=MX_OUTER_EDGE, sides=0, tag="4 layers, inside the MX pins"),
    dict(layers=2, outer=LARGE_OUTER_EDGE, sides=0, tag="2 layers, 9 mm OD (slug-stem sites)"),
)


def _fit_turns(trace, space, outer_edge, inner_edge=INNER_EDGE, step=0.25):
    """Most turns (in quarter turns) whose copper fits between the two edges."""
    pitch = trace + space
    room = outer_edge - inner_edge - trace           # centreline travel available
    return max(math.floor(room / pitch / step) * step, step)


def doe_variants():
    """Four rows (layers and diameter) by five columns (trace = space): 20 coils."""
    out = []
    for ri, row in enumerate(ROWS):
        for ci, w in enumerate(TRACES):
            turns = _fit_turns(w, w, row["outer"])
            out.append(Coil(turns=turns, trace=w, space=w, r_in=INNER_EDGE + w / 2, layers=row["layers"],
                            sides=row["sides"], tag=f"{'ABCD'[ri]}{ci + 1}"))
    return out


def doe_layout(pitch=(12.5, 12.0), origin=(7.0, 7.0)):
    """[(coil, (x, y))] on the coupon: row A at the front (smallest y), columns left to right by trace."""
    out = []
    for k, c in enumerate(doe_variants()):
        ri, ci = divmod(k, len(TRACES))
        out.append((c, (origin[0] + ci * pitch[0], origin[1] + ri * pitch[1])))
    return out


def _main():
    print(f"{'tag':4} {'turns':>6} {'trace':>6} {'layers':>6} {'OD mm':>6} {'Cu mm':>7} {'L1 uH (model)':>14}")
    for c in doe_variants():
        lay, _v = coil_layers(c)
        cu = sum(trace_length(layer.points) for layer in lay[:c.layers])
        print(f"{c.tag:4} {c.turns:6g} {c.trace:6.3f} {c.layers:6d} {c.d_out:6.2f} {cu:7.1f} "
              f"{current_sheet_inductance(c) * 1e6:14.3f}")
    print("L1: one layer, current-sheet model in free space (Mohan et al. 1999). A simple model, not measured.")


if __name__ == "__main__":
    _main()
