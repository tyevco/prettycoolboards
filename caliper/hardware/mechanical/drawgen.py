#!/usr/bin/env python3
"""Rev B machining: STEP files and dimensioned drawings (SVG / DXF / PDF).

    python3 drawgen.py                  # step/<part>.step + drawings/<part>.{svg,dxf,pdf}
    python3 drawgen.py --only beam_pockets --no-pdf

Adapted from dial-me-spinner/hardware/mechanical/drawgen.py.  A CNC vendor quotes
from STEP and wants a drawing for everything a solid cannot carry: tolerances,
threads, geometric tolerances, finish and process notes.  Views are projected or
sectioned from the B-rep in models.py, so a view cannot drift from the part; only
the choice of dimensions is authored here.

Sheets
  slider_body_b   6061-T6 slider body (models.slider_body("B")): plan from the
                  front, section A-A through the AS5311 (u = 39), section B-B
                  through the left tower's front-pad screws
  beam_pockets    the beam's machining operations on ground 20 x 4 flat stock:
                  plan, section C-C through the pockets, the jaw-joint holes
"""
import argparse
import os
import shutil
import subprocess
import sys

from build123d import (Align, PageSize, Plane, Pos, Sketch, Text, Unit, export_step, scale,
                       section)
from build123d.drafting import Draft, ExtensionLine, TechnicalDrawing
from build123d.exporters import Drawing, ExportDXF, ExportSVG

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import models as MD                                          # noqa: E402
import params as P                                           # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DIA = "⌀"
DRAFT = Draft(font_size=2.2, font="DejaVu Sans", arrow_length=1.5, line_width=0.3,
              decimal_precision=2, extension_gap=1.2, pad_around_text=1.0, display_units=False)
NOTE_SIZE, NOTE_LEAD, LABEL_SIZE, SHEET_TEXT = 2.0, 2.7, 2.6, 3.0


def dim(value, tol=None, dia=False, fit=None, suffix=None, nd=2):
    """One label, formatted here (build123d drops tolerances once a label is given)."""
    s = f"{DIA if dia else ''}{value:.{nd}f}"
    if fit:
        s += f" {fit}"
    if tol is not None:
        s += f"  {tol[0]:+.2f}/{tol[1]:+.2f}" if tol[0] != -tol[1] else f" ±{tol[0]:.2f}"
    if suffix:
        s += f" {suffix}"
    return s


def _text(txt, x, y, size=NOTE_SIZE, align=(Align.MIN, Align.CENTER)):
    return Pos(x, y) * Text(txt, size, font="DejaVu Sans", align=align)


def _lines(lines, x, y, size=NOTE_SIZE, lead=NOTE_LEAD):
    s = Sketch()
    for i, ln in enumerate(lines):
        if ln:
            s += _text(ln, x, y - i * lead, size)
    return s


def below(d):
    return d


def above(d):
    return -d


def plan(solid, from_back=False):
    """Front (or back) projection: (visible lines, f(part u, part y) -> projected point)."""
    look = (0, 0, -1) if from_back else (0, 0, 1)
    lines = Drawing(solid, look_from=look, look_up=(0, 1, 0), with_hidden=False).visible_lines
    pb, sb = lines.bounding_box(), solid.bounding_box()
    sx = -1 if from_back else 1
    ox = pb.min.X - (sb.min.X if not from_back else -sb.max.X)
    oy = pb.min.Y - sb.min.Y
    return lines, (lambda a, b: (sx * a + ox, b + oy))


def yz_section(solid, x):
    """Section at x, laid flat: sheet x = part y, sheet y = part z."""
    pl = Plane.YZ.offset(x)
    return pl.to_local_coords(section(solid, pl))


def place(shape, centre, k=1.0, ref=(0.0, 0.0)):
    """Put `shape` on the sheet so that the shape point `ref` lands on `centre`, scaled k."""
    s = shape if k == 1.0 else scale(shape, k)
    return Pos(centre[0] - k * ref[0], centre[1] - k * ref[1]) * s


def mapper(centre, k=1.0, ref=(0.0, 0.0), proj=None):
    """Same transform as place(), for dimensions written in part coordinates."""
    def f(a, b):
        if proj is not None:
            a, b = proj(a, b)
        return (centre[0] + k * (a - ref[0]), centre[1] + k * (b - ref[1]))
    return f


def _frame(title, number, material, k_label, size=PageSize.A3):
    return TechnicalDrawing(designed_by="PrettyCool Caliper / hardware-as-code", page_size=size,
                            title=title, sub_title=f"{material}  rev B  {k_label}",
                            drawing_number=number, sheet_number=1, drawing_scale=1.0,
                            nominal_text_size=SHEET_TEXT, line_width=0.3)


def _vlabel(txt, x, y):
    return _text(txt, x, y, LABEL_SIZE, (Align.CENTER, Align.CENTER))


COMMON = ["GENERAL TOLERANCE ISO 2768-mK UNLESS STATED; DIMENSIONS IN MM.",
          "DO NOT SCALE THE DRAWING. BREAK SHARP EDGES 0.2 x 45 EXCEPT WHERE NOTED SHARP.",
          "STEP FILE IS THE MASTER FOR UNDIMENSIONED GEOMETRY."]


# ---------------------------------------------------------------------------
# Sheet 1: slider body, 6061-T6
# ---------------------------------------------------------------------------
def sheet_slider_body(solid):
    lines, proj = plan(solid)
    pc, k = (-115, 25), 1.5
    bb = solid.bounding_box()
    ref = proj((bb.min.X + bb.max.X) / 2, (bb.min.Y + bb.max.Y) / 2)
    Pp = mapper(pc, k, ref, proj)
    views = [place(lines, pc, k, ref)]
    faces = _frame("slider body", "PCC-M-01", "6061-T6 clear anodise", "plan 1.5:1, sections 2:1")

    # overall + datum dimensions in the plan (datum A = jaw face u 0, datum B = lower rail face y -1.0)
    faces += ExtensionLine(border=[Pp(0, -P.JAW_L), Pp(P.H_U1, -P.JAW_L)], offset=below(10), draft=DRAFT,
                           label=dim(P.H_U1, suffix="FROM JAW FACE A"))
    faces += ExtensionLine(border=[Pp(P.H_U1, P.H_Y0), Pp(P.H_U1, P.H_Y1)], offset=12, draft=DRAFT,
                           label=dim(P.H_Y1 - P.H_Y0))
    faces += ExtensionLine(border=[Pp(P.H_U1, -P.JAW_L), Pp(P.H_U1, P.H_Y0)], offset=12, draft=DRAFT,
                           label=dim(P.JAW_L + P.H_Y0, suffix="JAW"))
    for i, u in enumerate(P.YGIB_PLUNGERS_U + [P.LOCK_U]):
        faces += ExtensionLine(border=[Pp(0, P.H_Y1), Pp(u, P.H_Y1)], offset=above(6 + 7 * i), draft=DRAFT,
                               label=dim(u, tol=(0.02, -0.02)))
    faces += _vlabel("VIEW FROM THE FRONT (DISPLAY SIDE)  1.5:1", pc[0], Pp(0, -P.JAW_L)[1] - 22)

    # Section A-A through the AS5311 plane
    sa = yz_section(solid, P.BOARD_U0 + P.AS_X)
    ac, ka = (75, 85), 2.0
    S = mapper(ac, ka, (23.2, 0.0))
    views.append(place(sa, ac, ka, (23.2, 0.0)))
    faces += ExtensionLine(border=[S(P.CH_Y0, P.Z_COVER_IN), S(P.CH_Y1, P.Z_COVER_IN)], offset=below(10),
                           draft=DRAFT, label=dim(P.CH_Y1 - P.CH_Y0, tol=(0.02, 0.00), suffix="CHANNEL"))
    faces += ExtensionLine(border=[S(P.H_Y0, P.Z_COVER_IN), S(P.H_Y1, P.Z_COVER_IN)], offset=below(20),
                           draft=DRAFT, label=dim(P.H_Y1 - P.H_Y0))
    faces += ExtensionLine(border=[S(P.H_Y1, P.Z_COVER_IN), S(P.H_Y1, P.Z_LID_IN)], offset=10, draft=DRAFT,
                           label=dim(P.Z_LID_IN - P.Z_COVER_IN))
    faces += _vlabel(f"SECTION A-A  (u = {P.BOARD_U0 + P.AS_X:g})  2:1", ac[0], ac[1] + 22)

    # Section B-B through the left tower's front pads
    sb = yz_section(solid, P.FPADS[0][0])
    bc = (75, 22)
    T = mapper(bc, ka, (10.0, 0.0))
    views.append(place(sb, bc, ka, (10.0, 0.0)))
    faces += ExtensionLine(border=[T(P.FPADS[0][3], P.Z_LID_IN), T(P.FPADS[1][3], P.Z_LID_IN)],
                           offset=above(8), draft=DRAFT, label=dim(P.FPADS[1][3] - P.FPADS[0][3], tol=(0.02, -0.02)))
    faces += ExtensionLine(border=[T(P.CH_Y1, P.Z_COVER_IN), T(P.CH_Y1, P.CH_Z1)], offset=30, draft=DRAFT,
                           label=dim(P.CH_Z1 - P.Z_COVER_IN, tol=(0.02, 0.00)))
    faces += _vlabel(f"SECTION B-B  (u = {P.FPADS[0][0]:g}, FRONT-PAD SET SCREWS)  2:1", bc[0], bc[1] + 24)

    notes = ["MATERIAL 6061-T6, STRESS-RELIEVED PLATE. CLEAR ANODISE 10 um AFTER MACHINING;",
             "MASK THE CHANNEL FACES AND THE JAW MEASURING FACE.",
             "DATUM A: MOVING-JAW MEASURING FACE (u = 0).  DATUM B: CHANNEL LOWER FACE (REFERENCE-STRIP SEAT).",
             "DATUM C: CHANNEL FRONT FACE (TOWER UNDERSIDE).",
             "JAW MEASURING FACE: FLAT 0.005, PERPENDICULAR TO B WITHIN 0.01 -- AFTER LAPPING",
             "  WITH THE FIXED JAW CLOSED ON IT (PARALLEL 0.01 BETWEEN THE TWO JAWS), SEE MECHANICAL 9.",
             "GIB AND LOCK BORE POSITIONS (u 16.00 / 58.50 / 63.00) ±0.02 FROM A;",
             "FRONT-PAD SET-SCREW HOLES ±0.02 FROM B. ALL M2 HOLES TAPPED M2x0.4 6H, 4 DEEP;",
             "LOCK HOLE M3x0.5 6H. CHANNEL 22.20 +0.02/0 x 5.50 +0.02/0, FLOOR Ra 0.8.",
             "OPTIONAL: POCKET 2.0 DEEP IN THE JAW FACE FOR A HARDENED, GROUND JAW INSERT",
             "  (1.2379 / D2 60 HRC OR CARBIDE, 2.0 x 6 x 34), BONDED + 2 PINS, GROUND IN PLACE."]
    faces += _lines(COMMON + [""] + notes, -200, -88)
    return faces, views


# ---------------------------------------------------------------------------
# Sheet 2: beam pocket operations
# ---------------------------------------------------------------------------
def sheet_beam(solid):
    lines, proj = plan(solid)
    pc, k = (-5, 80), 1.5
    xm = (P.BEAM_X0 + P.BEAM_X1) / 2
    ref = proj(xm, 10.0)
    Pp = mapper(pc, k, ref, proj)
    views = [place(lines, pc, k, ref)]
    faces = _frame("beam: pocket operations", "PCC-M-02", "O1 or 1.4301 ground flat 20x4",
                   "plan 1.5:1, section 6:1")
    ch0, ch1 = P.TAPE_YC - P.TAPE_CH_W / 2, P.TAPE_YC + P.TAPE_CH_W / 2
    sy0 = P.SCALE_Y0 - (P.SCALE_POCKET_W - P.SCALE_W) / 2
    faces += ExtensionLine(border=[Pp(P.BEAM_X0, 0), Pp(P.BEAM_X1, 0)], offset=below(14), draft=DRAFT,
                           label=dim(P.BEAM_L))
    faces += ExtensionLine(border=[Pp(P.BEAM_X0, 0), Pp(0.0, 0)], offset=below(6), draft=DRAFT,
                           label=dim(-P.BEAM_X0, suffix="TO JAW FACE"))
    faces += ExtensionLine(border=[Pp(P.BEAM_X0, P.BEAM_W), Pp(P.TAPE_X0 - 1, P.BEAM_W)], offset=above(6),
                           draft=DRAFT, label=dim(P.TAPE_X0 - 1 - P.BEAM_X0, suffix="TAPE CH."))
    faces += ExtensionLine(border=[Pp(P.TAPE_X0 - 1, P.BEAM_W), Pp(P.TAPE_X1 + 1, P.BEAM_W)],
                           offset=above(14), draft=DRAFT, label=dim(P.TAPE_X1 - P.TAPE_X0 + 2))
    faces += ExtensionLine(border=[Pp(P.BEAM_X0, P.BEAM_W), Pp(P.SCALE_X0 - 0.5, P.BEAM_W)],
                           offset=above(22), draft=DRAFT, label=dim(P.SCALE_X0 - 0.5 - P.BEAM_X0, suffix="SCALE"))
    faces += ExtensionLine(border=[Pp(P.SCALE_X0 - 0.5, P.BEAM_W), Pp(P.SCALE_X0 + P.SCALE_L + 0.5, P.BEAM_W)],
                           offset=above(30), draft=DRAFT, label=dim(P.SCALE_L + 1))
    faces += ExtensionLine(border=[Pp(P.BEAM_X0, 0), Pp(MD.stop_x(), 0)], offset=below(22),
                           draft=DRAFT, label=dim(MD.stop_x() - P.BEAM_X0, tol=(0.05, -0.05), suffix=f"STOP {DIA}2 H7"))
    faces += _vlabel("VIEW ON THE FRONT FACE (DATUM D); LOWER EDGE y = 0 IS REFERENCE EDGE E  1.5:1", pc[0], pc[1] - 15 - 36)

    # Section C-C, 6:1, through both pockets at x = 100
    sc = yz_section(solid, 100.0)
    cc, kc = (70, -22), 6.0
    S = mapper(cc, kc, (10.0, -2.0))
    views.append(place(sc, cc, kc, (10.0, -2.0)))
    faces += ExtensionLine(border=[S(ch0, 0), S(ch1, 0)], offset=above(8), draft=DRAFT,
                           label=dim(P.TAPE_CH_W, tol=(0.05, 0.00)))
    faces += ExtensionLine(border=[S(sy0, 0), S(sy0 + P.SCALE_POCKET_W, 0)], offset=above(8), draft=DRAFT,
                           label=dim(P.SCALE_POCKET_W, tol=(0.05, 0.00)))
    faces += ExtensionLine(border=[S(0, 0), S(ch0, 0)], offset=above(18), draft=DRAFT, label=dim(ch0, tol=(0.02, -0.02)))
    faces += ExtensionLine(border=[S(0, 0), S(sy0, 0)], offset=above(28), draft=DRAFT, label=dim(sy0, tol=(0.02, -0.02)))
    faces += ExtensionLine(border=[S(ch0, -P.TAPE_CH_DEPTH), S(ch0, 0)], offset=-18, draft=DRAFT,
                           label=dim(P.TAPE_CH_DEPTH, tol=(0.02, -0.02)))
    faces += ExtensionLine(border=[S(sy0 + P.SCALE_POCKET_W, -P.SCALE_POCKET_DEPTH), S(sy0 + P.SCALE_POCKET_W, 0)], offset=34, draft=DRAFT,
                           label=dim(P.SCALE_POCKET_DEPTH, tol=(0.02, -0.02)))
    faces += ExtensionLine(border=[S(0, -P.BEAM_T), S(P.BEAM_W, -P.BEAM_T)], offset=below(8), draft=DRAFT,
                           label=dim(P.BEAM_W, suffix="GROUND"))
    faces += _vlabel("SECTION C-C (x = 100)  6:1", cc[0] - 95, cc[1])

    notes = [f"STOCK: GROUND FLAT 20 x 4 (h9/h11), {P.BEAM_L:g} LONG. O1 (1.2510) ANNEALED OR 1.4301.",
             "OPERATIONS: 1 ROUGH BOTH POCKETS 0.2 UNDER, DRILL ALL HOLES 0.2 UNDER;",
             "  2 O1: HARDEN + TEMPER 58-60 HRC.  1.4301: STRESS-RELIEVE ONLY;",
             "  3 SURFACE-GRIND FRONT FACE D, GRIND EDGE E (ALL LATER DEPTHS ARE FROM THIS D);",
             "  4 FINISH POCKETS FROM D, 2 MM FLAT END MILL, END RADIUS 1.0 (O1 HARD: CARBIDE HARD-MILL OR EDM);",
             "  5 FINISH HOLES (1.4301: REAM; O1 HARD: JIG-GRIND OR WIRE-EDM TO H7).",
             "EDGE E (y = 0): STRAIGHT 0.01 OVER ANY 150, 0.015 OVER THE LENGTH. FACE D FLAT 0.01 / 150.",
             "POCKET FLOORS PARALLEL TO D WITHIN 0.01; Ra 0.8.",
             f"JAW-JOINT HOLES: 2x {DIA}3.4 THRU AT x -12 (y 5, 15); 2x {DIA}3 H7 THRU AT x -5 (y 4, 16), ±0.02.",
             f"STOP PIN {DIA}2 H7 THRU AT y {P.STOP_Y:g}; PRESS A {DIA}2 m6 DOWEL, {P.STOP_PROUD:g} PROUD OF D.",
             "DEBURR POCKET EDGES WITHOUT ROUNDING FACE D (STONE FLAT)."]
    faces += _lines(COMMON + [""] + notes, -200, -50)
    return faces, views


SHEETS = {"slider_body_b": (MD.slider_body_b, sheet_slider_body),
          "beam_pockets": (MD.beam, sheet_beam)}


def write_drawing(name, faces, outlines, out, pdf=True):
    d = os.path.join(out, "drawings")
    os.makedirs(d, exist_ok=True)
    svg_path = os.path.join(d, f"{name}.svg")
    svg = ExportSVG(unit=Unit.MM, line_weight=0.25)
    svg.add_layer("sheet", fill_color=(0, 0, 0), line_color=(0, 0, 0))
    svg.add_layer("views", fill_color=None, line_color=(0, 0, 0), line_weight=0.35)
    svg.add_shape(faces, layer="sheet")
    svg.add_shape(outlines, layer="views")
    svg.write(svg_path)
    dxf_path = os.path.join(d, f"{name}.dxf")
    dxf = ExportDXF(unit=Unit.MM)
    dxf.add_layer("sheet")
    dxf.add_layer("views")
    dxf.add_shape(faces, layer="sheet")
    dxf.add_shape(outlines, layer="views")
    dxf.write(dxf_path)
    written = [svg_path, dxf_path]
    if pdf and shutil.which("rsvg-convert"):
        pdf_path = os.path.join(d, f"{name}.pdf")
        subprocess.run(["rsvg-convert", "-f", "pdf", "-o", pdf_path, svg_path], check=True)
        written.append(pdf_path)
    return written


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", action="append")
    ap.add_argument("--out", default=HERE)
    ap.add_argument("--no-pdf", action="store_true")
    a = ap.parse_args(argv)
    for name in a.only or list(SHEETS):
        build, sheet = SHEETS[name]
        solid = build()
        os.makedirs(os.path.join(a.out, "step"), exist_ok=True)
        step = os.path.join(a.out, "step", f"{name}.step")
        export_step(solid, step)
        faces, outlines = sheet(solid)
        for p in [step] + write_drawing(name, faces, outlines, a.out, pdf=not a.no_pdf):
            print(os.path.relpath(p, a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
