"""finish_route.anchor_end: a track entered part-way along is split, and both halves keep their copper."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

pcbnew = pytest.importorskip("pcbnew")
import finish_route  # noqa: E402

MM = pcbnew.FromMM


def test_split_keeps_the_far_half():
    b = pcbnew.BOARD()
    net = pcbnew.NETINFO_ITEM(b, "VBAT")
    b.Add(net)
    t = pcbnew.PCB_TRACK(b)
    t.SetStart(pcbnew.VECTOR2I(MM(0), MM(0)))
    t.SetEnd(pcbnew.VECTOR2I(MM(10), MM(0)))
    t.SetWidth(MM(2.0))
    t.SetLayer(pcbnew.B_Cu)
    t.SetNet(net)
    t.SetLocked(True)
    b.Add(t)
    # a new track ends 0.3 mm off the trunk's centreline at x 4 (inside its copper)
    added = finish_route.anchor_end(b, net, pcbnew.VECTOR2I(MM(4), MM(0.3)), pcbnew.B_Cu, 0.3)
    segs = [x for x in b.GetTracks() if x.Type() == pcbnew.PCB_TRACE_T and x.GetWidth() == MM(2.0)]
    spans = sorted((pcbnew.ToMM(x.GetStart().x), pcbnew.ToMM(x.GetEnd().x)) for x in segs)
    assert spans == [(0.0, 4.0), (4.0, 10.0)]          # was [(0, 4), (4, 4)]: the far 6 mm vanished
    assert all(x.IsLocked() for x in segs)
    assert len(added) == 1 and pcbnew.ToMM(added[0].GetEnd().x) == 4.0
