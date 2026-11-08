"""Build a KiCad 9 board from a KiCad netlist using the pcbnew Python API.

Footprints are linked to their schematic symbols (KIID paths), so
"Update PCB from Schematic" in KiCad keeps working on the generated board.
"""

from __future__ import annotations

import math
import os
import subprocess

import pcbnew

import sexpr
from sexpr import find, find_all

MM = pcbnew.FromMM
_FP_CACHE = {}
FP_DIR = os.environ.get("KICAD9_FOOTPRINT_DIR", "/usr/share/kicad/footprints")


def vec(x, y):
    return pcbnew.VECTOR2I(MM(x), MM(y))


def load_netlist(path):
    n = sexpr.parse(open(path, encoding="utf-8").read())
    comps = {}
    for c in find_all(find(n, "components"), "comp"):
        ref = str(find(c, "ref")[1])
        fields = {}
        fl = find(c, "fields")
        if fl:
            for f in find_all(fl, "field"):
                name = str(find(f, "name")[1])
                fields[name] = str(f[2]) if len(f) > 2 else ""
        props = {}
        for p in find_all(c, "property"):
            v = find(p, "value")
            props[str(find(p, "name")[1])] = str(v[1]) if v else ""
        for k in ("MPN", "LCSC", "Manufacturer", "DNP"):
            if props.get(k) and not fields.get(k):
                fields[k] = props[k]
        sp = find(c, "sheetpath")
        comps[ref] = dict(
            ref=ref,
            value=str(find(c, "value")[1]),
            footprint=str(find(c, "footprint")[1]) if find(c, "footprint") else "",
            fields=fields,
            props=props,
            sheet_tstamps=str(find(sp, "tstamps")[1]),
            sheet_names=str(find(sp, "names")[1]),
            tstamp=str(find(c, "tstamps")[1]),
        )
    nets = {}
    for net in find_all(find(n, "nets"), "net"):
        name = str(find(net, "name")[1])
        nets[name] = [(str(find(nd, "ref")[1]), str(find(nd, "pin")[1])) for nd in find_all(net, "node")]
    return comps, nets


def export_netlist(sch_path, out_path):
    subprocess.run(["kicad-cli", "sch", "export", "netlist", "-o", out_path, sch_path],
                   check=True, capture_output=True)
    return out_path


class BoardBuilder:
    def __init__(self, copper_layers=4, extra_fp_libs: dict | None = None, board=None):
        if board is None:
            board = pcbnew.BOARD()
            board.SetCopperLayerCount(copper_layers)
        self.board = board
        self.fp_libs = dict(extra_fp_libs or {})
        self.footprints: dict[str, pcbnew.FOOTPRINT] = {fp.GetReference(): fp for fp in board.GetFootprints()}
        self.nets: dict[str, pcbnew.NETINFO_ITEM] = {}
        for name, ni in board.GetNetsByName().items():
            self.nets[str(name)] = ni

    @classmethod
    def load(cls, path, extra_fp_libs=None):
        return cls(extra_fp_libs=extra_fp_libs, board=pcbnew.LoadBoard(path))

    # -- design rules ---------------------------------------------------------
    def rules(self, track=0.15, clearance=0.15, via=0.45, via_drill=0.25, edge=0.3, hole_clear=0.2):
        ds = self.board.GetDesignSettings()
        ds.m_MinResolvedSpokes = 1
        ds.m_TrackMinWidth = MM(0.1)
        ds.m_MinClearance = MM(0.1)
        ds.m_ViasMinSize = MM(0.4)
        ds.m_MinThroughDrill = MM(0.2)
        ds.m_CopperEdgeClearance = MM(edge)
        ds.m_HoleClearance = MM(hole_clear)
        ns = ds.m_NetSettings
        nc = ns.GetDefaultNetclass()
        nc.SetTrackWidth(MM(track))
        nc.SetClearance(MM(clearance))
        nc.SetViaDiameter(MM(via))
        nc.SetViaDrill(MM(via_drill))
        return ds

    def netclass(self, name, nets, track, clearance=0.15, via=0.6, via_drill=0.3):
        ns = self.board.GetDesignSettings().m_NetSettings
        nc = pcbnew.NETCLASS(name)
        nc.SetTrackWidth(MM(track))
        nc.SetClearance(MM(clearance))
        nc.SetViaDiameter(MM(via))
        nc.SetViaDrill(MM(via_drill))
        ns.SetNetclass(name, nc)
        for n in nets:
            ns.SetNetclassPatternAssignment(n, name)

    # -- geometry ---------------------------------------------------------------
    def circle(self, layer, cx, cy, r, width=0.1):
        s = pcbnew.PCB_SHAPE(self.board)
        s.SetShape(pcbnew.SHAPE_T_CIRCLE)
        s.SetCenter(vec(cx, cy))
        s.SetEnd(vec(cx + r, cy))
        s.SetLayer(layer)
        s.SetWidth(MM(width))
        self.board.Add(s)
        return s

    def polyline(self, layer, pts, width=0.1, closed=True):
        seq = list(pts) + ([pts[0]] if closed else [])
        for (x0, y0), (x1, y1) in zip(seq, seq[1:]):
            s = pcbnew.PCB_SHAPE(self.board)
            s.SetShape(pcbnew.SHAPE_T_SEGMENT)
            s.SetStart(vec(x0, y0))
            s.SetEnd(vec(x1, y1))
            s.SetLayer(layer)
            s.SetWidth(MM(width))
            self.board.Add(s)

    def arc(self, layer, cx, cy, r, a0, a1, width=0.1):
        """Arc from angle a0 to a1 (degrees, CCW on screen with y down = clockwise math)."""
        s = pcbnew.PCB_SHAPE(self.board)
        s.SetShape(pcbnew.SHAPE_T_ARC)
        am = (a0 + a1) / 2
        p = lambda a: vec(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
        s.SetArcGeometry(p(a0), p(am), p(a1))
        s.SetLayer(layer)
        s.SetWidth(MM(width))
        self.board.Add(s)
        return s

    def text(self, layer, s, x, y, size=1.0, thickness=0.15, angle=0, mirror=False):
        t = pcbnew.PCB_TEXT(self.board)
        t.SetText(s)
        t.SetPosition(vec(x, y))
        t.SetLayer(layer)
        t.SetTextSize(pcbnew.VECTOR2I(MM(size), MM(size)))
        t.SetTextThickness(MM(thickness))
        t.SetTextAngleDegrees(angle)
        t.SetMirrored(mirror)
        self.board.Add(t)
        return t

    @staticmethod
    def circle_pts(cx, cy, r, n=72, a0=0.0, a1=360.0):
        return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
                 cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n)]

    def zone(self, net, layers, pts, priority=0, clearance=0.2, min_width=0.2, thermal_gap=0.3,
             spoke=0.3, name=""):
        z = pcbnew.ZONE(self.board)
        ls = pcbnew.LSET()
        for l in layers:
            ls.AddLayer(l)
        z.SetLayerSet(ls)
        if net:
            z.SetNet(self.net(net))
        z.SetAssignedPriority(priority)
        z.SetLocalClearance(MM(clearance))
        z.SetMinThickness(MM(min_width))
        z.SetThermalReliefGap(MM(thermal_gap))
        z.SetThermalReliefSpokeWidth(MM(spoke))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
        if name:
            z.SetZoneName(name)
        ol = z.Outline()
        ol.NewOutline()
        for x, y in pts:
            ol.Append(MM(x), MM(y))
        self.board.Add(z)
        return z

    def keepout(self, layers, pts, tracks=True, vias=True, pads=True, pours=True, footprints=False, name=""):
        z = pcbnew.ZONE(self.board)
        z.SetIsRuleArea(True)
        ls = pcbnew.LSET()
        for l in layers:
            ls.AddLayer(l)
        z.SetLayerSet(ls)
        z.SetDoNotAllowTracks(tracks)
        z.SetDoNotAllowVias(vias)
        z.SetDoNotAllowPads(pads)
        z.SetDoNotAllowCopperPour(pours)
        z.SetDoNotAllowFootprints(footprints)
        if name:
            z.SetZoneName(name)
        ol = z.Outline()
        ol.NewOutline()
        for x, y in pts:
            ol.Append(MM(x), MM(y))
        self.board.Add(z)
        return z

    def edge_band_keepout(self, outline_pts, inset=0.45, outset=1.0, name="EDGE_KEEPOUT"):
        """Rule area (no tracks/vias) in a band along the board edge, so autorouters keep clear."""
        base = pcbnew.SHAPE_POLY_SET()
        base.NewOutline()
        for x, y in outline_pts:
            base.Append(MM(x), MM(y))
        outer = pcbnew.SHAPE_POLY_SET(base)
        outer.Inflate(MM(outset), pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS, MM(0.01))
        inner = pcbnew.SHAPE_POLY_SET(base)
        inner.Inflate(-MM(inset), pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS, MM(0.01))
        outer.BooleanSubtract(inner)
        z = pcbnew.ZONE(self.board)
        z.SetIsRuleArea(True)
        z.SetLayerSet(pcbnew.LSET.AllCuMask())
        z.SetDoNotAllowTracks(True)
        z.SetDoNotAllowVias(True)
        z.SetDoNotAllowPads(False)
        z.SetDoNotAllowCopperPour(False)
        z.SetDoNotAllowFootprints(False)
        z.SetZoneName(name)
        ol = z.Outline()  # copy into the zone's own polygon set (SetOutline would take ownership)
        for i in range(outer.OutlineCount()):
            ol.NewOutline()
            chain = outer.Outline(i)
            for k in range(chain.PointCount()):
                pt = chain.CPoint(k)
                ol.Append(pt.x, pt.y)
            for h in range(outer.HoleCount(i)):
                ol.NewHole()
                hc = outer.Hole(i, h)
                for k in range(hc.PointCount()):
                    pt = hc.CPoint(k)
                    ol.Append(pt.x, pt.y, -1, h)
        self.board.Add(z)
        return z

    # -- nets & footprints ------------------------------------------------------
    def net(self, name):
        if name not in self.nets:
            ni = pcbnew.NETINFO_ITEM(self.board, name)
            self.board.Add(ni)
            self.nets[name] = ni
        return self.nets[name]

    def _lib_path(self, nick):
        if nick in self.fp_libs:
            return self.fp_libs[nick]
        return os.path.join(FP_DIR, nick + ".pretty")

    def load_footprint(self, fpid):
        """A fresh copy of a library footprint. The library copy is loaded once: FootprintLoad parses the whole
        .pretty directory and leaks memory on every call."""
        nick, name = fpid.split(":", 1)
        key = (self._lib_path(nick), name)
        if key not in _FP_CACHE:
            _FP_CACHE[key] = pcbnew.FootprintLoad(*key)
        if _FP_CACHE[key] is None:
            raise KeyError(f"footprint {fpid} not found")
        fp = pcbnew.FOOTPRINT(_FP_CACHE[key])
        fp.SetFPIDAsString(fpid)
        return fp

    def place_from_netlist(self, comps, nets, placement, default=(0.0, 0.0, 0.0, "F")):
        pin_net = {}
        for name, nodes in nets.items():
            for ref, pin in nodes:
                pin_net[(ref, pin)] = name
        for ref, c in sorted(comps.items()):
            if not c["footprint"]:
                continue
            fp = self.load_footprint(c["footprint"])
            fp.SetReference(ref)
            fp.SetValue(c["value"])
            fp.SetPath(pcbnew.KIID_PATH(c["sheet_tstamps"] + c["tstamp"]))
            fp.SetSheetname(c["sheet_names"].strip("/").split("/")[-1] if c["sheet_names"] != "/" else "")
            for k in ("MPN", "LCSC", "Manufacturer"):
                if c["fields"].get(k):
                    fp.SetField(k, c["fields"][k])
                    fld = fp.GetFieldByName(k)
                    if fld:
                        fld.SetVisible(False)
            if c["props"].get("dnp") is not None or c["fields"].get("DNP"):
                fp.SetDNP(True)
            if "exclude_from_bom" in c["props"]:
                fp.SetAttributes(fp.GetAttributes() | pcbnew.FP_EXCLUDE_FROM_BOM | pcbnew.FP_EXCLUDE_FROM_POS_FILES)
            self.board.Add(fp)
            x, y, rot, side = placement.get(ref, default)
            if side == "B":
                fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
            fp.SetPosition(vec(x, y))
            fp.SetOrientationDegrees(rot)
            for pad in fp.Pads():
                net = pin_net.get((ref, pad.GetNumber()))
                if net:
                    pad.SetNet(self.net(net))
            self.footprints[ref] = fp
        return self.footprints

    def board_only(self, fpid, ref, x, y, side="F"):
        """A footprint that exists only on the board (no schematic symbol): holes, fiducials."""
        fp = self.load_footprint(fpid)
        fp.SetReference(ref)
        fp.SetAttributes(fp.GetAttributes() | pcbnew.FP_BOARD_ONLY | pcbnew.FP_EXCLUDE_FROM_BOM
                         | pcbnew.FP_EXCLUDE_FROM_POS_FILES)
        self.board.Add(fp)
        if side == "B":
            fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
        fp.SetPosition(vec(x, y))
        self.footprints[ref] = fp
        return fp

    def mounting_hole(self, x, y, fpid="MountingHole:MountingHole_2.2mm_M2", ref="H"):
        return self.board_only(fpid, ref, x, y)

    def set_origin(self, x, y):
        """Drill/place (aux) origin, used for gerber and pick-and-place coordinates."""
        ds = self.board.GetDesignSettings()
        ds.SetAuxOrigin(vec(x, y))
        ds.SetGridOrigin(vec(x, y))

    def save(self, path, fill=True):
        """Save; zone filling only works on a board loaded from disk, so reload first."""
        self.board.SetFileName(path)
        pcbnew.SaveBoard(path, self.board)
        unique_uuids(path)
        if fill:
            refill(path)


def unique_uuids(path):
    """Give every repeated UUID in a saved board a fresh one. Footprints copied from a library keep the library's
    pad and graphic UUIDs, so every 0402 shares its pad UUIDs with every other; KiCad's DRC report then resolves a
    violating pad to the wrong part. Deterministic (uuid5 of the reference and position in the file)."""
    import uuid as _uuid
    lines = open(path).read().split("\n")
    seen, ref, changed = set(), "", 0
    for i, ln in enumerate(lines):
        st = ln.lstrip()
        if st.startswith('(property "Reference" "'):
            ref = st.split('"')[3]
        elif st.startswith('(uuid "'):
            u = st.split('"')[1]
            if u in seen:
                nu = str(_uuid.uuid5(_uuid.NAMESPACE_URL, f"dial-me-spinner/{os.path.basename(path)}/{ref}/{i}"))
                lines[i] = ln.replace(u, nu)
                u = nu
                changed += 1
            seen.add(u)
    if changed:
        with open(path, "w") as f:
            f.write("\n".join(lines))
    return changed


def refill(path):
    b = pcbnew.LoadBoard(path)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(path, b)
    return b


def export_dsn(pcb_path, dsn_path):
    """Specctra DSN for Freerouting.  KiCad exports every rule area as a full keepout, so the pour-only ones (no copper
    pour, tracks/vias/pads allowed, e.g. the antenna and magnet-track pour bands) are dropped from the in-memory board
    first; otherwise the router may not run tracks through them or reach pads inside them.  The file is not saved."""
    b = pcbnew.LoadBoard(pcb_path)
    for z in list(b.Zones()):
        if z.GetIsRuleArea() and z.GetDoNotAllowCopperPour() and not (
                z.GetDoNotAllowTracks() or z.GetDoNotAllowVias() or z.GetDoNotAllowPads()):
            b.Delete(z)
    if not pcbnew.ExportSpecctraDSN(b, dsn_path):
        raise RuntimeError("DSN export failed")


def import_ses(pcb_path, ses_path, out_path=None):
    b = pcbnew.LoadBoard(pcb_path)
    if not pcbnew.ImportSpecctraSES(b, ses_path):
        raise RuntimeError("SES import failed")
    dedupe_tracks(b)
    trim_dangling(b)
    out_path = out_path or pcb_path
    pcbnew.SaveBoard(out_path, b)
    refill(out_path)


def trim_dangling(b, tol=2000):
    """Cut a segment's open end back to the last T-junction on it (the router often joins a pre-routed
    stub part-way along instead of at its end)."""
    segs = [t for t in b.GetTracks() if t.Type() == pcbnew.PCB_TRACE_T]
    vias = [t for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T]
    trimmed = 0
    for t in segs:
        for end in ("start", "end"):
            p = t.GetStart() if end == "start" else t.GetEnd()
            q = t.GetEnd() if end == "start" else t.GetStart()
            net, layer = t.GetNetCode(), t.GetLayer()
            joined = any(o is not t and o.GetNetCode() == net and o.GetLayer() == layer and
                         ((o.GetStart() - p).EuclideanNorm() < tol or (o.GetEnd() - p).EuclideanNorm() < tol)
                         for o in segs)
            joined = joined or any(v.GetNetCode() == net and (v.GetStart() - p).EuclideanNorm() < tol for v in vias)
            joined = joined or any(pad.GetNetCode() == net and pad.IsOnLayer(layer) and pad.HitTest(p)
                                   for fp in b.GetFootprints() for pad in fp.Pads())
            if joined:
                continue
            # T-junctions: other segments' ends (or vias) lying on this segment
            seg = pcbnew.SEG(p, q)
            taps = [x for o in segs if o is not t and o.GetNetCode() == net and o.GetLayer() == layer
                    for x in (o.GetStart(), o.GetEnd()) if seg.Distance(x) < tol]
            taps += [v.GetStart() for v in vias if v.GetNetCode() == net and seg.Distance(v.GetStart()) < tol]
            if not taps:
                continue
            cut = min(taps, key=lambda x: (x - p).EuclideanNorm())
            if (cut - q).EuclideanNorm() < tol:
                continue
            n = max(2, int((cut - p).EuclideanNorm() / 50000))  # never cut away a pad the removed piece touches
            piece = [pcbnew.VECTOR2I(int(p.x + (cut.x - p.x) * k / n), int(p.y + (cut.y - p.y) * k / n)) for k in range(n)]
            if any(pad.GetNetCode() == net and pad.IsOnLayer(layer) and pad.HitTest(x, t.GetWidth() // 2)
                   for fp in b.GetFootprints() for pad in fp.Pads() for x in piece):
                continue
            if end == "start":
                t.SetStart(cut)
            else:
                t.SetEnd(cut)
            trimmed += 1
    return trimmed


def _zone_has(b, net, layer, pt):
    return any(z.GetNetCode() == net and z.IsOnLayer(layer) and z.HitTestFilledArea(layer, pt)
               for z in b.Zones() if not z.GetIsRuleArea())


def _end_connected(b, t, p, segs, vias, tol=2000):
    net, layer = t.GetNetCode(), t.GetLayer()
    if any(o is not t and o.GetNetCode() == net and o.GetLayer() == layer and
           ((o.GetStart() - p).EuclideanNorm() < tol or (o.GetEnd() - p).EuclideanNorm() < tol) for o in segs):
        return True
    if any(v.GetNetCode() == net and (v.GetStart() - p).EuclideanNorm() < tol for v in vias):
        return True
    if any(pad.GetNetCode() == net and pad.IsOnLayer(layer) and pad.HitTest(p)
           for fp in b.GetFootprints() for pad in fp.Pads()):
        return True
    return _zone_has(b, net, layer, p)


def remove_debris(b, tol=2000):
    """Zone-aware clean-up after routing + pour fill (run on a filled board, repeat until stable):
    unlocked segments that only retrace a locked segment (router copper laid over a locked BGA neck),
    unlocked spurs with an open end and no other copper on them, and unlocked vias that join < 2 items."""
    removed = 0
    for _ in range(10):
        segs = [t for t in b.GetTracks() if t.Type() == pcbnew.PCB_TRACE_T]
        vias = [t for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T]
        doomed = []
        locked = [t for t in segs if t.IsLocked()]
        for t in segs:
            if t.IsLocked():
                continue
            for lk in locked:
                if lk.GetNetCode() == t.GetNetCode() and lk.GetLayer() == t.GetLayer():
                    seg = pcbnew.SEG(lk.GetStart(), lk.GetEnd())
                    if seg.Distance(t.GetStart()) < tol and seg.Distance(t.GetEnd()) < tol:
                        doomed.append(t)
                        break
        for t in segs:
            if t.IsLocked() or t in doomed:
                continue
            for p, q in ((t.GetStart(), t.GetEnd()), (t.GetEnd(), t.GetStart())):
                if _end_connected(b, t, p, segs, vias, tol):
                    continue
                seg = pcbnew.SEG(p, q)
                taps = [x for o in segs if o is not t and o.GetNetCode() == t.GetNetCode() and o.GetLayer() == t.GetLayer()
                        for x in (o.GetStart(), o.GetEnd()) if seg.Distance(x) < tol and (x - p).EuclideanNorm() > tol]
                taps += [v.GetStart() for v in vias if v.GetNetCode() == t.GetNetCode() and seg.Distance(v.GetStart()) < tol]
                if not taps and not _end_connected(b, t, q, segs, vias, tol):
                    doomed.append(t)  # floating piece
                elif not taps:
                    doomed.append(t)  # spur: one end open, nothing on it
                break
        for v in vias:
            if v.IsLocked():
                continue
            p, net = v.GetStart(), v.GetNetCode()
            n = sum(1 for o in segs if o not in doomed and o.GetNetCode() == net and
                    ((o.GetStart() - p).EuclideanNorm() < tol or (o.GetEnd() - p).EuclideanNorm() < tol))
            n += sum(1 for lay in (pcbnew.F_Cu, pcbnew.B_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu)
                     if b.IsLayerEnabled(lay) and _zone_has(b, net, lay, p))
            if n < 2:
                doomed.append(v)
        if not doomed:
            break
        for t in doomed:
            b.Delete(t)
        removed += len(doomed)
    return removed


def stitch_vias(b, net_name="GND", pitch=3.0, via=0.5, drill=0.25, clearance=0.2, spacing=1.0,
                priority=(), max_vias=400):
    """Add GND stitching vias on a grid (plus any priority points first) wherever a through via fits:
    inside the filled pour of that net on both outer layers, clear of every other-net item on every layer."""
    net = b.GetNetInfo().GetNetItem(net_name)
    if net is None:
        return 0
    code = net.GetNetCode()
    cu = [lay for lay in (pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu) if b.IsLayerEnabled(lay)]
    tracks = [t for t in b.GetTracks()]
    pads = [p for fp in b.GetFootprints() for p in fp.Pads()]
    holes = [p for p in pads if p.GetDrillSize().x > 0]
    rv = MM(via / 2)
    placed = [v.GetStart() for v in tracks if v.Type() == pcbnew.PCB_VIA_T]
    bb = b.GetBoardEdgesBoundingBox()

    no_via = [z for z in b.Zones() if z.GetIsRuleArea() and z.GetDoNotAllowVias()]

    def ok(pt):
        for z in no_via:
            if z.Outline().Collide(pt, int(rv + MM(clearance))):
                return False
        for lay in (pcbnew.F_Cu, pcbnew.B_Cu):
            ring = [pt] + [pt + pcbnew.VECTOR2I(int(rv * math.cos(a)), int(rv * math.sin(a)))
                           for a in (k * math.pi / 4 for k in range(8))]
            if not all(_zone_has(b, code, lay, q) for q in ring):
                return False
        acc = rv + MM(clearance)
        for t in tracks:
            if t.GetNetCode() != code and any(t.IsOnLayer(lay) for lay in cu) and t.HitTest(pt, acc):
                return False
        for p in pads:
            if p.GetNetCode() != code and p.HitTest(pt, acc):
                return False
            if p.GetAttribute() in (pcbnew.PAD_ATTRIB_SMD, pcbnew.PAD_ATTRIB_CONN) and p.HitTest(pt, rv + MM(0.05)):
                return False
        for p in holes:  # hole-to-hole spacing applies to every net
            if (p.GetPosition() - pt).EuclideanNorm() < MM(drill / 2 + 0.25) + p.GetDrillSize().x // 2:
                return False
        return all((q - pt).EuclideanNorm() >= MM(spacing) for q in placed)

    added = 0
    pts = [vec(x, y) for x, y in priority]
    step = MM(pitch)
    y = bb.GetY() + step // 2
    while y < bb.GetBottom():
        x = bb.GetX() + step // 2
        while x < bb.GetRight():
            pts.append(pcbnew.VECTOR2I(int(x), int(y)))
            x += step
        y += step
    for pt in pts:
        if added >= max_vias or not ok(pt):
            continue
        v = pcbnew.PCB_VIA(b)
        v.SetPosition(pt)
        v.SetWidth(MM(via))
        v.SetDrill(MM(drill))
        v.SetNet(net)
        b.Add(v)
        placed.append(pt)
        tracks.append(v)
        added += 1
    return added


def fanout_vias(b, net_name="GND", pads=None, via=0.5, drill=0.25, track=0.25, clearance=0.15, max_dist=2.2,
                lock=True):
    """Give each SMD pad of the net (or just `pads`) a through via with a short track on the pad's layer, so the
    pad reaches the inner plane.  A pad that already has a same-net via within reach of its own edge gets only the
    track.  Each candidate spot is checked against every other-net pad, track and via on every layer it touches,
    the via/track rule areas and hole-to-hole spacing.  Returns (pads done, pads left without a spot)."""
    net = b.GetNetInfo().GetNetItem(net_name)
    if net is None:
        return 0, []
    code = net.GetNetCode()
    cu = [lay for lay in (pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu) if b.IsLayerEnabled(lay)]
    tracks = list(b.GetTracks())
    allpads = [pd for fp in b.GetFootprints() for pd in fp.Pads()]
    holes = [pd for pd in allpads if pd.GetDrillSize().x > 0]
    vias = [t for t in tracks if t.Type() == pcbnew.PCB_VIA_T]
    rules = [z for z in b.Zones() if z.GetIsRuleArea()]
    rv, hw, clr = MM(via / 2), MM(track / 2), MM(clearance)
    if pads is None:
        pads = [pd for pd in allpads if pd.GetNetCode() == code and pd.GetDrillSize().x == 0
                and (pd.IsOnLayer(pcbnew.F_Cu) or pd.IsOnLayer(pcbnew.B_Cu))]

    def via_ok(pt):
        for z in rules:
            if z.GetDoNotAllowVias() and z.Outline().Collide(pt, int(rv + clr)):
                return False
        acc = rv + clr
        for t in tracks:
            if t.GetNetCode() != code and t.HitTest(pt, acc):
                return False
        for pd in allpads:
            if pd.GetNetCode() != code and any(pd.IsOnLayer(lay) for lay in cu) and pd.HitTest(pt, acc):
                return False
            # no via ring on any SMD / connector pad, even of the same net: an open via in a pad wicks the solder
            if pd.GetAttribute() in (pcbnew.PAD_ATTRIB_SMD, pcbnew.PAD_ATTRIB_CONN) and pd.HitTest(pt, rv + MM(0.05)):
                return False
        for h in holes:  # drill-to-drill 0.25 mm, and via copper to a (NPTH) hole edge 0.25 mm
            if (h.GetPosition() - pt).EuclideanNorm() < max(MM(drill / 2), rv) + MM(0.25) + h.GetDrillSize().x // 2:
                return False
        for v in vias:
            if (v.GetStart() - pt).EuclideanNorm() < MM(drill / 2 + 0.25) + v.GetDrillValue() // 2:
                return False
        return True

    def seg_ok(a, c, layer, own):
        n = max(2, int((c - a).EuclideanNorm() / MM(0.05)))
        for k in range(1, n + 1):
            q = pcbnew.VECTOR2I(a.x + (c.x - a.x) * k // n, a.y + (c.y - a.y) * k // n)
            for z in rules:
                if z.GetDoNotAllowTracks() and z.IsOnLayer(layer) and z.Outline().Collide(q, int(hw + clr)):
                    return False
            for t in tracks:
                if t.GetNetCode() != code and t.IsOnLayer(layer) and t.HitTest(q, hw + clr):
                    return False
            for pd in allpads:
                if pd is not own and pd.GetNetCode() != code and pd.IsOnLayer(layer) and pd.HitTest(q, hw + clr):
                    return False
        return True

    def add_track(a, c, layer):
        t = pcbnew.PCB_TRACK(b)
        t.SetStart(a)
        t.SetEnd(c)
        t.SetWidth(MM(track))
        t.SetLayer(layer)
        t.SetNet(net)
        t.SetLocked(lock)
        b.Add(t)
        tracks.append(t)

    done, left = 0, []
    for pd in pads:
        layer = pcbnew.F_Cu if pd.IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu
        c0 = pd.GetPosition()
        reach = max(pd.GetSize().x, pd.GetSize().y) // 2
        # an existing same-net via close by: just connect to it
        near = sorted((v for v in vias if v.GetNetCode() == code),
                      key=lambda v: (v.GetStart() - c0).EuclideanNorm())
        if near and (near[0].GetStart() - c0).EuclideanNorm() <= reach + MM(1.0):
            # the via's copper must really overlap the pad (a narrow pad's half-length is not a radius)
            touching = pd.HitTest(near[0].GetStart(), near[0].GetWidth(pcbnew.F_Cu) // 2 - MM(0.02))
            if touching or seg_ok(c0, near[0].GetStart(), layer, pd):
                if not touching:
                    add_track(c0, near[0].GetStart(), layer)
                done += 1
                continue
        found = None
        d = reach + rv + clr
        while d <= reach + MM(max_dist) and not found:
            for k in range(24):
                a = 2 * math.pi * k / 24
                pt = c0 + pcbnew.VECTOR2I(int(d * math.cos(a)), int(d * math.sin(a)))
                if via_ok(pt) and seg_ok(c0, pt, layer, pd):
                    found = pt
                    break
            d += MM(0.1)
        if not found:
            left.append(pd)
            continue
        v = pcbnew.PCB_VIA(b)
        v.SetPosition(found)
        v.SetWidth(MM(via))
        v.SetDrill(MM(drill))
        v.SetNet(net)
        v.SetLocked(lock)
        b.Add(v)
        tracks.append(v)
        vias.append(v)
        add_track(c0, found, layer)
        done += 1
    return done, left


def dedupe_tracks(b):
    """Drop exact duplicate segments/vias (a re-route of an already routed board re-imports the old wiring)."""
    seen, dup = set(), []
    for t in b.GetTracks():
        s, e = t.GetStart(), t.GetEnd()
        ends = tuple(sorted(((s.x, s.y), (e.x, e.y))))
        via = t.Type() == pcbnew.PCB_VIA_T
        width = (t.GetWidth(pcbnew.F_Cu), t.GetDrillValue()) if via else t.GetWidth()
        key = (t.GetClass(), t.GetLayer(), t.GetNetCode(), width, ends)
        if key in seen:
            dup.append(t)
        else:
            seen.add(key)
    for t in dup:
        b.Delete(t)
    return len(dup)
