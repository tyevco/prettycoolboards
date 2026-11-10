"""pcbgen.dead_branch: everything behind a dangling segment that carries nothing, and nothing that still connects."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

pcbnew = pytest.importorskip("pcbnew")
import pcbgen  # noqa: E402

MM = pcbnew.FromMM
TO = pcbnew.ToMM


def pt(x, y):
    return pcbnew.VECTOR2I(MM(x), MM(y))


class Net:
    def __init__(self):
        self.bb = pcbgen.BoardBuilder(copper_layers=4)
        self.b = self.bb.board
        self.bb.rules()
        self.net = pcbnew.NETINFO_ITEM(self.b, "SIG")
        self.b.Add(self.net)

    def pad(self, ref, x, y):
        fp = pcbnew.FOOTPRINT(self.b)
        fp.SetReference(ref)
        fp.SetPosition(pt(x, y))
        pad = pcbnew.PAD(fp)
        pad.SetNumber("1")
        pad.SetShape(pcbnew.PAD_SHAPE_RECT)
        pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        pad.SetLayerSet(pad.SMDMask())
        pad.SetSize(pcbnew.VECTOR2I(MM(0.5), MM(0.5)))
        pad.SetPosition(pt(x, y))
        pad.SetNet(self.net)
        fp.Add(pad)
        self.b.Add(fp)

    def seg(self, a, c, layer=pcbnew.F_Cu, locked=False):
        t = pcbnew.PCB_TRACK(self.b)
        t.SetStart(pt(*a))
        t.SetEnd(pt(*c))
        t.SetWidth(MM(0.2))
        t.SetLayer(layer)
        t.SetNet(self.net)
        t.SetLocked(locked)
        self.b.Add(t)
        return t

    def via(self, x, y):
        v = pcbnew.PCB_VIA(self.b)
        v.SetPosition(pt(x, y))
        v.SetWidth(pcbnew.F_Cu, MM(0.45))
        v.SetDrill(MM(0.2))
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetNet(self.net)
        self.b.Add(v)
        return v

    def branch(self, seg, open_end):
        # the segment is looked up again, as a caller that read it from a DRC report does: another proxy object
        again = [t for t in self.b.GetTracks() if t.m_Uuid.AsString() == seg.m_Uuid.AsString()][0]
        return {t.m_Uuid.AsString() for t in pcbgen.dead_branch(self.b, again, pt(*open_end))}


def ids(*items):
    return {t.m_Uuid.AsString() for t in items}


def test_follows_the_branch_through_a_via_back_to_the_fork():
    n = Net()
    n.pad("C1", 10, 10)
    n.pad("C2", 14, 10)
    n.seg((10, 10), (12, 10))               # the connection: pad - fork - pad
    n.seg((12, 10), (14, 10))
    s1 = n.seg((12, 10), (12, 11))          # the dead branch, from the fork
    s2 = n.seg((12, 11), (12.5, 11.5))
    v = n.via(12.5, 11.5)
    s3 = n.seg((12.5, 11.5), (13, 12), pcbnew.B_Cu)
    last = n.seg((13, 12), (13.5, 12), pcbnew.B_Cu)
    assert n.branch(last, (13.5, 12)) == ids(s1, s2, v, s3)


def test_stops_at_a_t_junction_on_another_segments_body():
    n = Net()
    n.pad("C1", 10, 10)
    n.pad("C2", 14, 10)
    n.seg((10, 10), (14, 10))               # one segment: the branch ends on its body
    s1 = n.seg((12, 10), (12, 11))
    last = n.seg((12, 11), (12, 12))
    assert n.branch(last, (12, 12)) == ids(s1)


def test_stops_at_a_pad_and_at_locked_copper():
    n = Net()
    n.pad("C1", 10, 10)
    n.pad("C2", 14, 10)
    n.seg((10, 10), (14, 10))
    n.pad("C3", 12, 12)                      # the dangling segment starts on a pad: what is behind the pad stays
    n.seg((12, 12), (12, 10))
    last = n.seg((12, 12), (13, 13))
    assert n.branch(last, (13, 13)) == set()
    m = Net()
    m.pad("C1", 10, 10)
    m.seg((10, 10), (12, 10), locked=True)  # a locked pre-route is never part of the branch
    last = m.seg((12, 10), (13, 10))
    assert m.branch(last, (13, 10)) == set()


def test_a_floating_chain_is_all_dead():
    n = Net()
    a = n.seg((10, 10), (11, 10))
    c = n.seg((11, 10), (12, 10))
    last = n.seg((12, 10), (13, 10))
    assert n.branch(last, (13, 10)) == ids(a, c)
