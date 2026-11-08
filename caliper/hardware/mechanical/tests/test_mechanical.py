"""Invariants of the caliper model.  ~/.venvs/dial-me-spinner/bin/python -m pytest caliper/hardware/mechanical/tests -q"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import models as M      # noqa: E402
import params as P      # noqa: E402


def test_gaps_nominal():
    assert P.BOARD_Z0 == pytest.approx(P.CAP_GAP)
    assert P.BOARD_Z0 - P.AS_H_NOM - P.TAPE_TOP == pytest.approx(P.MAG_GAP)
    # A max still leaves the lower limit of the SPEC window (shims only ever raise the tape)
    assert P.BOARD_Z0 - P.AS_H_MAX - P.TAPE_TOP >= P.MAG_GAP - P.MAG_GAP_TOL - 1e-9


def test_shim_can_always_correct_the_gap():
    # A shim raises the tape, i.e. it can only close the gap.  So the unshimmed channel must give
    # >= MAG_GAP for the tallest package, and the shim range must reach the shortest one.
    floor = -P.TAPE_CH_DEPTH
    for A, shim in ((P.AS_H_MAX, 0.0), (P.AS_H_NOM, P.TAPE_SHIM_NOM), (P.AS_H_MIN, P.TAPE_SHIM_MAX)):
        tape_top = floor + shim + P.TAPE_ADH + P.TAPE_T
        assert P.BOARD_Z0 - A - tape_top == pytest.approx(P.MAG_GAP)
    assert P.TAPE_SHIM_NOM >= 0


def test_bands_do_not_overlap():
    tape_hi = P.TAPE_YC + P.TAPE_CH_W / 2
    scale_lo = P.SCALE_Y0 - (P.SCALE_POCKET_W - P.SCALE_W) / 2
    assert scale_lo - tape_hi >= 0.3          # a land between the two pockets
    assert P.TAPE_YC - P.TAPE_CH_W / 2 >= 1.5  # and to the reference edge (front pads ride on it)


def test_as5311_in_channel():
    ch0, ch1 = P.TAPE_YC - P.TAPE_CH_W / 2, P.TAPE_YC + P.TAPE_CH_W / 2
    assert P.AS_Y - P.AS_LEAD_Y / 2 - ch0 >= 0.5 and ch1 - (P.AS_Y + P.AS_LEAD_Y / 2) >= 0.5


def test_envelope_spec7():
    x, y, z = P.HOUSING_SIZE
    assert x <= 78.0 + 1e-9 and y <= 52.0 + 1e-9 and z <= 16.0 + 1e-9


def test_beam_depth_left():
    assert P.BEAM_T - P.TAPE_CH_DEPTH >= 2.0 - 1e-9


@pytest.mark.parametrize("name", list(M.PARTS))
def test_parts_valid(name):
    s = M.build(name)
    assert s.is_valid and s.volume > 0


def test_walls_printable():
    # thinnest designed wall: channel to battery pocket
    assert P.BAT_POCKET["y0"] - P.CH_Y1 >= P.WALL_MIN - 1e-9
    assert P.H_Y1 - P.BAT_POCKET["y1"] >= P.WALL_MIN - 1e-9


@pytest.mark.parametrize("R", [0.0, P.RANGE + P.OVERTRAVEL])
def test_slider_clears_beam_and_fixed_jaw(R):
    body = M.Pos(R, 0, 0) * M.slider_body()
    for other in (M.beam(), M.fixed_jaw(), M.stop_pin()):
        inter = body & other
        assert inter is None or inter.volume < 1e-3


def test_stop_pin_position():
    # the right end face meets the pin exactly at RANGE + OVERTRAVEL
    assert M.stop_x() - P.STOP_D / 2 == pytest.approx(P.RANGE + P.OVERTRAVEL + P.H_U1)


def test_extrusions_go_up():
    # regression: a clockwise outline used to extrude toward -z (fixed jaws ended up under the block)
    fj = M.fixed_jaw().bounding_box()
    assert fj.min.Z == pytest.approx(P.FJ_Z0) and fj.max.Z == pytest.approx(P.FJ_Z1)
    sb = M.slider_body().bounding_box()
    assert sb.min.Z == pytest.approx(P.Z_COVER_IN) and sb.max.Z == pytest.approx(P.Z_LID_IN)
