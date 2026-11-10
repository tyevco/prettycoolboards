"""pcbgen.fanout_vias: the gap to another net's copper is that net's class clearance when it is the larger one."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

pcbnew = pytest.importorskip("pcbnew")
import pcbgen  # noqa: E402

MM = pcbnew.FromMM
TO = pcbnew.ToMM


def board_with_pad_and_track(track_x):
    bb = pcbgen.BoardBuilder(copper_layers=4)
    b = bb.board
    bb.rules()
    gnd, sig = pcbnew.NETINFO_ITEM(b, "GND"), pcbnew.NETINFO_ITEM(b, "SIG")
    b.Add(gnd)
    b.Add(sig)
    bb.netclass("Analog", ["SIG"], track=0.15, clearance=0.4)
    fp = pcbnew.FOOTPRINT(b)
    fp.SetReference("C1")
    fp.SetPosition(pcbnew.VECTOR2I(MM(10), MM(10)))
    pad = pcbnew.PAD(fp)
    pad.SetNumber("1")
    pad.SetShape(pcbnew.PAD_SHAPE_RECT)
    pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
    pad.SetLayerSet(pad.SMDMask())
    pad.SetSize(pcbnew.VECTOR2I(MM(0.5), MM(0.5)))
    pad.SetPosition(pcbnew.VECTOR2I(MM(10), MM(10)))
    pad.SetNet(gnd)
    fp.Add(pad)
    b.Add(fp)
    t = pcbnew.PCB_TRACK(b)        # an inner-layer track of the 0.4 mm class, beside the pad
    t.SetStart(pcbnew.VECTOR2I(MM(track_x), MM(5)))
    t.SetEnd(pcbnew.VECTOR2I(MM(track_x), MM(15)))
    t.SetWidth(MM(0.15))
    t.SetLayer(pcbnew.In2_Cu)
    t.SetNet(sig)
    b.Add(t)
    b.SynchronizeNetsAndNetClasses(True)       # a board built in memory resolves its class patterns only here
    return b, pad, t


def test_via_keeps_the_other_nets_class_clearance():
    # the first spot tried is 0.65 mm east of the pad centre (pad edge + via radius + 0.15): its copper would end
    # 0.2 mm from the track, which the flat 0.15 mm accepted (caliper slider 2026-11-10: DRC 0.18 mm against 0.2)
    track_x = 10.65 + 0.25 + 0.2 + 0.075
    b, pad, t = board_with_pad_and_track(track_x)
    assert t.GetNetClassName() == "Analog"
    done, left = pcbgen.fanout_vias(b, "GND", pads=[pad])
    assert (done, left) == (1, [])
    vias = [v for v in b.GetTracks() if v.Type() == pcbnew.PCB_VIA_T]
    assert len(vias) == 1
    gap = track_x - 0.075 - TO(vias[0].GetPosition().x) - TO(vias[0].GetWidth(pcbnew.F_Cu)) / 2
    assert gap >= 0.4 - 1e-3
