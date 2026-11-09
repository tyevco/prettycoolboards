#!/usr/bin/env python3
"""Extract the routed slider board into the mechanical model.

    python3 extract_board_parts.py [path/to/slider.kicad_pcb]     # needs KiCad 10 pcbnew (WSL)

Adapted from dial-me-spinner/hardware/mechanical/extract_board_parts.py.  Writes
board_parts.json, which board_envelope.py prefers over its SPEC placeholder, so
`clash_check.py` tests the board as it is actually laid out.

Frame: board coordinates of SPEC 2.1 (origin at the lower-left corner of the 62 x 34
body, +y up = beam y).  The origin is the board's drill/place (aux) origin, which
layout.py sets there; if it is unset, the lower-left corner of the body is found from
Edge.Cuts (the leftmost edge point below the tabs, y < 2.4).

What is written
  outline   the Edge.Cuts contour (body + end tabs, arcs as the layout wrote them),
            chained into one closed polygon
  holes     every MountingHole footprint: ref, x, y
  parts     one axis-aligned box per footprint with a body: its F.Fab/B.Fab outline
            (courtyard shrunk 0.25 if it has no Fab outline), extruded by a height from
            HEIGHTS.  Plus the items that are not footprints but sit on the board:
              * the SMT M2 standoff on each tab hole (H2-H5, SPEC D3), 4.0 x 2.0
              * the nylon screw head on H1
              * the mated JST-SH plug in front of J2's mouth (side entry)
Heights are datasheet maxima where known; the ones tagged "verify" are assumptions.
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
    (r"MountingHole|TestPoint|Fiducial|Tag-Connect|NetTie|Electrode", None, "no body"),
    (r"ESP32-S[23]-MINI|ESP32S3.*MINI", 2.55, "Espressif MINI-1: 2.40 +/-0.10 + solder"),
    (r"TSSOP-20|AS5311", 1.20, "JEDEC MO-153 A max"),
    (r"USB_C|TYPE-C|USB-C", 3.30, "HRO TYPE-C-31-M-12: 3.26"),
    (r"FH12|FPC|FFC|0\.5K-AX", 2.00, "0.5 mm FPC (HDGC 0.5K-AX-13PWB / Hirose FH12): 2.0"),
    (r"JST_SH|SM02B-SRSS", 2.95, "JST SH side entry"),
    (r"TS-1088.*R020", 2.00, "XKB TS-1088-xR020: 2.0"),
    (r"SW_.*3x4|TS-1088|SKRP|SW_SPST", 2.50, "tact, verify"),
    (r"LGA-12|LIS2DW12", 1.00, "ST LGA-12 2x2x0.7, +solder"),
    (r"WSON|DSBGA|BQ25180|YBG", 0.65, "DSBGA 0.625 max"),
    (r"VSON|DLA0010A", 1.00, "TI VSON-HR 1.0 max"),
    (r"TDFN|DFN-8|MAX17048", 0.80, ""),
    (r"QFN|VQFN|TPS63802", 1.00, ""),
    (r"SOT-23-5|SOT-23-6", 1.45, "DBV max"),
    (r"SOT-23", 1.15, ""),
    (r"SOT-563|SOT-363|SC-70", 1.10, ""),
    (r"MSOP|VSSOP|OPA", 1.10, ""),
    (r"LED.*2020|WS2812.*2020|SK6805", 0.90, "2020 RGB LED"),
    (r"PKMCS0909", 1.90, "Murata PKMCS0909E: 1.9"),
    (r"Buzzer|Piezo|MLT|CMT", 3.00, "SMD piezo, verify"),
    (r"L_Murata_DFE201610", 1.00, "Murata DFE201610P: 1.0 max"),
    (r"L_.*(2016|2012|1608)|IND", 1.00, "inductor, verify"),
    (r"D_SMF", 1.10, "SMF (SOD-123F) 1.1 max"),
    (r"C_0402", 0.55, "0402 MLCC max"),
    (r"R_0402", 0.40, ""),
    (r"C_0603", 0.90, ""),
    (r"R_0603", 0.50, ""),
    (r"C_0805", 1.45, ""),
    (r"SOD-523|SOD-323", 0.80, ""),
]

# Bodies that are not footprints (SPEC 2.1 / D3), added per hole or per part.
STANDOFF = dict(d=4.0, h=2.0, note="SMT M2 standoff, PEM SMTSO-M2-2ET class (SPEC D3), on the tab's top pad")
H1_HEAD = dict(d=3.8, h=1.4, note="nylon M2 pan head (SPEC 2.1 H1)")
JST_PLUG = dict(w=4.4, depth=4.6, h=2.95, note="mated JST SHR-02V-S plug + crimp, verify")


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


def chain(segs, tol=1e-3):
    """Join (start, end) segments into one closed polygon [(x, y), ...]."""
    segs = [list(s) for s in segs]
    poly = [segs[0][0], segs[0][1]]
    segs = segs[1:]
    while segs:
        tail = poly[-1]
        for i, (a, b) in enumerate(segs):
            if math.dist(a, tail) < tol:
                poly.append(b)
                break
            if math.dist(b, tail) < tol:
                poly.append(a)
                break
        else:
            raise ValueError(f"Edge.Cuts is not one closed contour (open at {tail})")
        segs.pop(i)
    if math.dist(poly[0], poly[-1]) < tol:
        poly.pop()
    return poly


def main(argv):
    import pcbnew
    path = find_board(argv)
    b = pcbnew.LoadBoard(path)
    mm = pcbnew.ToMM

    # --- outline in page coordinates, then the origin ---------------------------------
    segs = []
    for d in b.GetDrawings():
        if d.GetLayerName() != "Edge.Cuts":
            continue
        st = d.GetShape()
        if st == pcbnew.SHAPE_T_SEGMENT:
            segs.append(((mm(d.GetStart().x), mm(d.GetStart().y)), (mm(d.GetEnd().x), mm(d.GetEnd().y))))
        elif st == pcbnew.SHAPE_T_ARC:
            c, r = d.GetCenter(), mm(d.GetRadius())
            a0, a1 = math.radians(d.GetArcAngleStart().AsDegrees()), math.radians(d.GetArcAngle().AsDegrees())
            n = max(4, int(abs(a1) / math.radians(10)))
            pts = [(mm(c.x) + r * math.cos(a0 + a1 * k / n), mm(c.y) + r * math.sin(a0 + a1 * k / n)) for k in range(n + 1)]
            segs += list(zip(pts, pts[1:]))
        elif st == pcbnew.SHAPE_T_RECT:
            s, e = d.GetStart(), d.GetEnd()
            q = [(mm(s.x), mm(s.y)), (mm(e.x), mm(s.y)), (mm(e.x), mm(e.y)), (mm(s.x), mm(e.y))]
            segs += list(zip(q, q[1:] + q[:1]))
    poly_page = chain(segs)
    ao = b.GetDesignSettings().GetAuxOrigin()
    ox, oy = mm(ao.x), mm(ao.y)
    yb = max(p[1] for p in poly_page)
    if abs(ox) < 1e-6 and abs(oy) < 1e-6:          # aux origin unset: body lower-left from the outline
        oy = yb
        ox = min(p[0] for p in poly_page if oy - p[1] < 2.4)
        origin_src = "Edge.Cuts (aux origin unset)"
    else:
        origin_src = "aux origin"

    def w(x, y):
        return (x - ox, oy - y)

    def wv(p):
        return w(mm(p.x), mm(p.y))

    outline = [[round(v, 4) for v in w(*p)] for p in poly_page]

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
                pts += [wv(ol.CPoint(i)) for i in range(ol.PointCount())]
        elif st == pcbnew.SHAPE_T_CIRCLE:
            c, r = wv(it.GetCenter()), mm(it.GetRadius())
            pts += [(c[0] + r * math.cos(a), c[1] + r * math.sin(a)) for a in [k * math.pi / 8 for k in range(16)]]
        else:
            s, e = wv(it.GetStart()), wv(it.GetEnd())
            pts += [s, e]
            if st == pcbnew.SHAPE_T_RECT:
                pts += [(s[0], e[1]), (e[0], s[1])]
        return pts

    parts, holes = [], []
    for fp in sorted(b.GetFootprints(), key=lambda f: f.GetReference()):
        fpname = str(fp.GetFPID().GetLibItemName())
        ref = fp.GetReference()
        if "MountingHole" in fpname:
            hx, hy = wv(fp.GetPosition())
            holes.append(dict(ref=ref, x=round(hx, 3), y=round(hy, 3)))
            if hx < 0 or hx > 62:      # tab hole: SMT standoff on the top pad
                r = STANDOFF["d"] / 2
                parts.append(dict(ref=f"{ref}_standoff", value="SMT M2 standoff", fp="(not a footprint)", side="T",
                                  aabb=[round(hx - r, 3), round(hx + r, 3), round(hy - r, 3), round(hy + r, 3)],
                                  h=STANDOFF["h"], note=STANDOFF["note"]))
            else:                       # H1: nylon screw head
                r = H1_HEAD["d"] / 2
                parts.append(dict(ref=f"{ref}_screw", value="nylon M2", fp="(not a footprint)", side="T",
                                  aabb=[round(hx - r, 3), round(hx + r, 3), round(hy - r, 3), round(hy + r, 3)],
                                  h=H1_HEAD["h"], note=H1_HEAD["note"]))
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
        side = "B" if fp.IsFlipped() else "T"
        parts.append(dict(ref=ref, value=fp.GetValue(), fp=fpname, side=side,
                          aabb=[round(q, 3) for q in aabb], h=h, note=note))
        if re.search(r"JST_SH", fpname):
            # mated plug: in front of the mouth.  The mouth faces the side the body extends least
            # from the footprint origin (side entry: the pads are at the back).
            cx, cy = wv(fp.GetPosition())
            mouth = max(((aabb[3] - cy), "+y"), ((cy - aabb[2]), "-y"), ((aabb[1] - cx), "+x"), ((cx - aabb[0]), "-x"))
            rot = round(fp.GetOrientationDegrees()) % 360
            # KiCad JST SH horizontal: mouth toward board -y at 0 deg; rotation is CCW seen from the top
            m = {0: "-y", 90: "+x", 180: "+y", 270: "-x"}.get(rot, mouth[1])
            pw, pd = JST_PLUG["w"] / 2, JST_PLUG["depth"]
            mx = (aabb[0] + aabb[1]) / 2
            my = (aabb[2] + aabb[3]) / 2
            box = {"+y": [mx - pw, mx + pw, aabb[3], aabb[3] + pd], "-y": [mx - pw, mx + pw, aabb[2] - pd, aabb[2]],
                   "+x": [aabb[1], aabb[1] + pd, my - pw, my + pw], "-x": [aabb[0] - pd, aabb[0], my - pw, my + pw]}[m]
            parts.append(dict(ref=f"{ref}_plug", value="JST SHR-02V-S", fp="(mated plug)", side=side,
                              aabb=[round(q, 3) for q in box], h=JST_PLUG["h"], note=f"{JST_PLUG['note']}, mouth {m}"))
    out = {"source": os.path.relpath(path, HERE).replace("\\", "/"), "origin": origin_src,
           "slider": {"outline": outline, "holes": holes, "parts": parts}}
    with open(os.path.join(HERE, "board_parts.json"), "w", newline="\n") as f:
        json.dump(out, f, indent=1)
        f.write("\n")
    xs, ys = [p[0] for p in outline], [p[1] for p in outline]
    unk = [p["ref"] for p in parts if "UNKNOWN" in p["note"]]
    print(f"{path}: origin from the {origin_src}; outline {len(outline)} points, "
          f"x {min(xs):.2f}..{max(xs):.2f}, y {min(ys):.2f}..{max(ys):.2f}")
    print(f"  {len(parts)} envelopes, holes {[h['ref'] for h in holes]}; unknown heights: {unk}")
    print("now run: python3 clash_check.py")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
