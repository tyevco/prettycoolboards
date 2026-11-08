#!/usr/bin/env python3
"""Extract component envelopes from the routed slider board into the mechanical model.

    python3 extract_board_parts.py [path/to/slider.kicad_pcb]     # needs KiCad 9 pcbnew

Adapted from dial-me-spinner/hardware/mechanical/extract_board_parts.py.  Writes
board_parts.json, which board_envelope.py prefers over its SPEC placeholder, so
`clash_check.py` then tests the board as it is actually placed.

Default input: the first caliper/hardware/kicad/slider/*.kicad_pcb (the layout
agent's output; the path is a guess until the layout exists -- pass it explicitly
otherwise).

Each footprint becomes an axis-aligned box in **board coordinates** (SPEC 2.1:
origin at the board's lower-left corner, +y up, so y = beam y): its F.Fab/B.Fab
outline (courtyard shrunk 0.25 if it has no Fab outline), rotated, then boxed,
extruded by a height from HEIGHTS.  Heights are datasheet maxima where known; the
ones tagged "verify" are assumptions to verify on the prototype.
"""
import glob
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
KICAD = os.path.normpath(os.path.join(HERE, "..", "kicad"))

# (footprint-name regex, height mm, note).  First match wins.
HEIGHTS = [
    (r"MountingHole|TestPoint|Fiducial|Tag-Connect|NetTie", None, "no body"),
    (r"ESP32-S3-MINI|ESP32S3.*MINI", 2.55, "Espressif: 2.40 +/-0.10 + solder"),
    (r"TSSOP-20|AS5311", 1.20, "JEDEC MO-153 A max"),
    (r"USB_C|TYPE-C|USB-C", 3.30, "top-mount receptacle, verify the part"),
    (r"FPC|FFC|0\.5mm.*13|13P", 2.00, "0.5 mm FPC connector, verify"),
    (r"JST_SH|SM02B-SRSS", 2.95, "JST SH side entry"),
    (r"SW_.*3x4|TS-1088|SKRP|SW_SPST", 2.50, "3x4 tact, verify"),
    (r"LGA-12|LIS2DW12", 1.00, "ST LGA-12 2x2x0.7, +solder"),
    (r"WSON|DSBGA|BQ25180|YBG", 0.65, ""),
    (r"TDFN|DFN-8|MAX17048", 0.80, ""),
    (r"QFN|VQFN|TPS63802", 1.00, ""),
    (r"SOT-23-5|SOT-23-6", 1.45, ""),
    (r"SOT-23", 1.15, ""),
    (r"SOT-563|SOT-363|SC-70", 1.10, ""),
    (r"MSOP|VSSOP|OPA", 1.10, ""),
    (r"LED.*2020|WS2812.*2020|SK6805", 0.90, "2020 RGB LED"),
    (r"Buzzer|Piezo|MLT|CMT", 3.00, "SMD piezo, verify"),
    (r"L_.*(2016|2012|1608)|IND", 1.00, "inductor, verify"),
    (r"C_0402", 0.55, "0402 MLCC max"),
    (r"R_0402", 0.40, ""),
    (r"C_0603", 0.90, ""),
    (r"R_0603", 0.50, ""),
    (r"C_0805", 1.45, ""),
    (r"SOD-523|SOD-323", 0.80, ""),
]


def height_for(fpname):
    for rx, h, note in HEIGHTS:
        if re.search(rx, fpname, re.I):
            return h, note
    return 1.0, "UNKNOWN height, default 1.0"


def find_board(argv):
    if len(argv) > 1:
        return argv[1]
    hits = sorted(glob.glob(os.path.join(KICAD, "slider", "*.kicad_pcb")))
    if not hits:
        hits = sorted(glob.glob(os.path.join(KICAD, "**", "*slider*.kicad_pcb"), recursive=True))
    if not hits:
        sys.exit(f"no slider .kicad_pcb under {KICAD}; pass the path explicitly")
    return hits[0]


def main(argv):
    import pcbnew
    path = find_board(argv)
    b = pcbnew.LoadBoard(path)
    bb = b.GetBoardEdgesBoundingBox()
    x0 = pcbnew.ToMM(bb.GetX())
    yb = pcbnew.ToMM(bb.GetY() + bb.GetHeight())          # KiCad y grows down: lower edge = max y

    def w(p):
        return (pcbnew.ToMM(p.x) - x0, yb - pcbnew.ToMM(p.y))

    def shape_points(it):
        pts = []
        try:
            st = it.GetShape()
        except Exception:      # noqa: BLE001
            return pts
        if st == pcbnew.SHAPE_T_POLY:
            poly = it.GetPolyShape()
            for o in range(poly.OutlineCount()):
                ol = poly.Outline(o)
                pts += [w(ol.CPoint(i)) for i in range(ol.PointCount())]
        elif st == pcbnew.SHAPE_T_CIRCLE:
            c, r = w(it.GetCenter()), pcbnew.ToMM(it.GetRadius())
            pts += [(c[0] + r * math.cos(a), c[1] + r * math.sin(a)) for a in [k * math.pi / 8 for k in range(16)]]
        else:
            s, e = w(it.GetStart()), w(it.GetEnd())
            pts += [s, e]
            if st == pcbnew.SHAPE_T_RECT:
                pts += [(s[0], e[1]), (e[0], s[1])]
        return pts

    parts, holes = [], []
    for fp in b.GetFootprints():
        fpname = str(fp.GetFPID().GetLibItemName())
        if "MountingHole" in fpname:
            holes.append([round(v, 3) for v in w(fp.GetPosition())])
        h, note = height_for(fpname)
        if h is None:
            continue
        fab, crt = [], []
        for it in fp.GraphicalItems():
            if it.GetClass() in ("PCB_TEXT", "FP_TEXT", "PCB_FIELD"):
                continue
            ln = it.GetLayerName()
            if ln.endswith("Fab"):
                fab += shape_points(it)
            elif ln.endswith("CrtYd"):
                crt += shape_points(it)
        pts, shrink = (fab, 0.0) if len(fab) >= 3 else (crt, 0.25)
        if len(pts) < 3:
            continue
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        aabb = [min(xs) + shrink, max(xs) - shrink, min(ys) + shrink, max(ys) - shrink]
        parts.append(dict(ref=fp.GetReference(), value=fp.GetValue(), fp=fpname,
                          side="B" if fp.IsFlipped() else "T",
                          aabb=[round(q, 3) for q in aabb], h=h, note=note))
    out = {"source": os.path.relpath(path, HERE), "slider": {"parts": parts, "holes": holes}}
    with open(os.path.join(HERE, "board_parts.json"), "w") as f:
        json.dump(out, f, indent=1)
    unk = [p["ref"] for p in parts if "UNKNOWN" in p["note"]]
    print(f"{path}: {len(parts)} envelopes, {len(holes)} holes; unknown heights: {unk}")
    print("now run: python3 clash_check.py")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
