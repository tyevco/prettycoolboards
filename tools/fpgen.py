"""Generate simple footprints for parts missing from the KiCad libraries.

Example:
    fp = Footprint("PKMCS0909E", "Murata 9x9 mm piezo transducer, 2 SMD pads")
    fp.smd("1", -3.6, 0, 1.6, 2.0)
    fp.smd("2", 3.6, 0, 1.6, 2.0)
    fp.courtyard_rect(-4.75, -4.75, 4.75, 4.75)
    fp.fab_rect(-4.5, -4.5, 4.5, 4.5)
    fp.silk_rect(-4.6, -4.6, 4.6, 4.6)
    fp.save(LIB_DIR)   # LIB_DIR = .../dial_spinner.pretty
"""

from __future__ import annotations

import os

import pcbnew

MM = pcbnew.FromMM


def _v(x, y):
    return pcbnew.VECTOR2I(MM(x), MM(y))


class Footprint:
    def __init__(self, name: str, descr: str = "", tags: str = "", smd: bool = True):
        self.fp = pcbnew.FOOTPRINT(None)
        self.fp.SetFPIDAsString(name)
        self.name = name
        self.fp.SetLibDescription(descr)
        self.fp.SetKeywords(tags)
        self.fp.SetAttributes(pcbnew.FP_SMD if smd else pcbnew.FP_THROUGH_HOLE)
        ref = self.fp.Reference()
        ref.SetLayer(pcbnew.F_SilkS)
        val = self.fp.Value()
        val.SetLayer(pcbnew.F_Fab)

    def _pad(self, num, x, y, w, h, shape, attrib, layers, drill=None, rot=0.0, rr=0.25):
        p = pcbnew.PAD(self.fp)
        p.SetNumber(str(num))
        p.SetAttribute(attrib)
        p.SetShape(pcbnew.PAD_SHAPE_ROUNDRECT if shape == "roundrect" else
                   pcbnew.PAD_SHAPE_CIRCLE if shape == "circle" else
                   pcbnew.PAD_SHAPE_OVAL if shape == "oval" else pcbnew.PAD_SHAPE_RECT)
        if shape == "roundrect":
            p.SetRoundRectRadiusRatio(rr)
        p.SetSize(_v(w, h))
        if drill:
            p.SetDrillSize(_v(drill, drill) if not isinstance(drill, tuple) else _v(*drill))
        ls = pcbnew.LSET()
        for l in layers:
            ls.AddLayer(l)
        p.SetLayerSet(ls)
        p.SetPosition(_v(x, y))
        p.SetFPRelativePosition(_v(x, y))
        p.SetOrientationDegrees(rot)
        self.fp.Add(p)
        return p

    def smd(self, num, x, y, w, h, shape="roundrect", rot=0.0, paste=True, layer="F"):
        cu, mask, pst = (pcbnew.F_Cu, pcbnew.F_Mask, pcbnew.F_Paste) if layer == "F" else \
            (pcbnew.B_Cu, pcbnew.B_Mask, pcbnew.B_Paste)
        layers = [cu, mask] + ([pst] if paste else [])
        return self._pad(num, x, y, w, h, shape, pcbnew.PAD_ATTRIB_SMD, layers, rot=rot)

    def tht(self, num, x, y, size, drill, shape="circle"):
        self.fp.SetAttributes(pcbnew.FP_THROUGH_HOLE)
        layers = [pcbnew.F_Cu, pcbnew.B_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.F_Mask, pcbnew.B_Mask]
        p = self._pad(num, x, y, size, size, shape, pcbnew.PAD_ATTRIB_PTH, layers, drill=drill)
        ls = pcbnew.LSET.AllCuMask()
        ls.AddLayer(pcbnew.F_Mask)
        ls.AddLayer(pcbnew.B_Mask)
        p.SetLayerSet(ls)
        return p

    def npth(self, x, y, drill):
        layers = [pcbnew.F_Cu, pcbnew.B_Cu, pcbnew.F_Mask, pcbnew.B_Mask]
        return self._pad("", x, y, drill, drill, "circle", pcbnew.PAD_ATTRIB_NPTH, layers, drill=drill)

    def _rect(self, layer, x0, y0, x1, y1, width):
        s = pcbnew.PCB_SHAPE(self.fp)
        s.SetShape(pcbnew.SHAPE_T_RECT)
        s.SetStart(_v(x0, y0))
        s.SetEnd(_v(x1, y1))
        s.SetLayer(layer)
        s.SetWidth(MM(width))
        self.fp.Add(s)

    def line(self, layer, x0, y0, x1, y1, width=0.12):
        s = pcbnew.PCB_SHAPE(self.fp)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(_v(x0, y0))
        s.SetEnd(_v(x1, y1))
        s.SetLayer(layer)
        s.SetWidth(MM(width))
        self.fp.Add(s)

    def circle(self, layer, cx, cy, r, width=0.12):
        s = pcbnew.PCB_SHAPE(self.fp)
        s.SetShape(pcbnew.SHAPE_T_CIRCLE)
        s.SetCenter(_v(cx, cy))
        s.SetEnd(_v(cx + r, cy))
        s.SetLayer(layer)
        s.SetWidth(MM(width))
        self.fp.Add(s)

    def courtyard_rect(self, x0, y0, x1, y1):
        self._rect(pcbnew.F_CrtYd, x0, y0, x1, y1, 0.05)

    def fab_rect(self, x0, y0, x1, y1):
        self._rect(pcbnew.F_Fab, x0, y0, x1, y1, 0.1)

    def silk_rect(self, x0, y0, x1, y1):
        self._rect(pcbnew.F_SilkS, x0, y0, x1, y1, 0.12)

    def pin1_dot(self, x, y):
        self.circle(pcbnew.F_SilkS, x, y, 0.15, 0.3)

    def save(self, lib_dir):
        io = pcbnew.PCB_IO_MGR.PluginFind(pcbnew.PCB_IO_MGR.KICAD_SEXP)
        if not os.path.isdir(lib_dir):
            os.makedirs(lib_dir)
        ref = self.fp.Reference()
        bb = self.fp.GetBoundingBox(False)
        ref.SetPosition(pcbnew.VECTOR2I(0, bb.GetTop() - MM(1.0)))
        self.fp.Value().SetPosition(pcbnew.VECTOR2I(0, bb.GetBottom() + MM(1.0)))
        io.FootprintSave(lib_dir, self.fp)
        return os.path.join(lib_dir, self.name + ".kicad_mod")
