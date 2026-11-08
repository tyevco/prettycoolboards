"""Invariants of the caliper model.  ~/.venvs/dial-me-spinner/bin/python -m pytest caliper/hardware/mechanical/tests -q"""
import os
import sys

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "..", "design"))
import models as M      # noqa: E402
import nets             # noqa: E402  (SPEC data: outline, holes, keep-outs)
import params as P      # noqa: E402


def test_gaps_nominal():
    assert P.BOARD_Z0 == pytest.approx(P.CAP_GAP)
    assert P.BOARD_Z0 - P.AS_H_NOM - P.TAPE_TOP == pytest.approx(P.MAG_GAP)
    # A max still leaves the lower limit of the SPEC window (shims only ever raise the tape)
    assert P.BOARD_Z0 - P.AS_H_MAX - P.TAPE_TOP >= P.MAG_GAP - P.MAG_GAP_TOL - 1e-9


def test_shim_can_always_correct_the_gap():
    floor = -P.TAPE_CH_DEPTH
    for A, shim in ((P.AS_H_MAX, 0.0), (P.AS_H_NOM, P.TAPE_SHIM_NOM), (P.AS_H_MIN, P.TAPE_SHIM_MAX)):
        tape_top = floor + shim + P.TAPE_ADH + P.TAPE_T
        assert P.BOARD_Z0 - A - tape_top == pytest.approx(P.MAG_GAP)
    assert P.TAPE_SHIM_NOM >= 0


def test_bands_do_not_overlap():
    tape_hi = P.TAPE_YC + P.TAPE_CH_W / 2
    scale_lo = P.SCALE_Y0 - (P.SCALE_POCKET_W - P.SCALE_W) / 2
    assert scale_lo - tape_hi >= 0.3
    assert P.TAPE_YC - P.TAPE_CH_W / 2 >= 1.5


def test_as5311_in_channel():
    ch0, ch1 = P.TAPE_YC - P.TAPE_CH_W / 2, P.TAPE_YC + P.TAPE_CH_W / 2
    assert P.AS_Y - P.AS_LEAD_Y / 2 - ch0 >= 0.5 and ch1 - (P.AS_Y + P.AS_LEAD_Y / 2) >= 0.5


def test_params_match_spec_contract():
    """params.py mirrors nets.SLIDER_OUTLINE / SLIDER_HOLES / SLIDER_KEEPOUTS and SPEC D2/D5."""
    o = nets.SLIDER_OUTLINE
    assert o["body"] == (0.0, 0.0, P.BOARD_L, P.BOARD_W)
    assert [tuple(t) for t in o["tabs"]] == [tuple(t) for t in P.BOARD_TABS]
    assert o["flatness_mm"] == P.BOARD_FLATNESS
    holes = {r: (x, y) for r, x, y, _role in nets.SLIDER_HOLES}
    assert holes["H1"] == P.H1
    assert [holes[f"H{i}"] for i in (2, 3, 4, 5)] == P.TAB_HOLES
    k = nets.SLIDER_KEEPOUTS
    assert k["antenna_all_layers"] == P.ANTENNA_KEEPOUT
    assert k["bottom_parts_allowed"] == P.BOTTOM_WINDOW
    assert k["under_glass_max_2p6"] == P.UNDER_GLASS
    assert P.SCALE_X0 == 14.5 and P.TAPE_W == 8.0 and P.TAPE_CH_DEPTH == pytest.approx(2.0)
    assert (P.BAT_POCKET["u0"], P.BAT_POCKET["u1"]) == (29.5, 65.5)


def test_envelope_spec7():
    x, y, z = P.HOUSING_SIZE
    assert x <= 78.0 + 1e-9 and y <= 52.0 + 1e-9 and z <= 16.0 + 1e-9
    assert P.ROLLER_RIM_U <= 78.0 + 1e-9          # SPEC 7 counts the roller, from the jaw face
    assert P.ROLLER_RIM_U > P.H_U1 + 0.3            # and it still stands proud of the end face


def test_beam_depth_left():
    assert P.BEAM_T - P.TAPE_CH_DEPTH >= 2.0 - 1e-9


@pytest.mark.parametrize("name", list(M.PARTS))
def test_parts_valid(name):
    s = M.build(name)
    assert s.is_valid and s.volume > 0


def test_walls_printable():
    assert P.BAT_POCKET["y0"] - P.CH_Y1 >= P.WALL_MIN - 1e-9
    assert P.H_Y1 - P.BAT_POCKET["y1"] >= P.WALL_MIN - 1e-9
    # tab pockets leave >= WALL_MIN to the housing end faces
    assert P.BOARD_U0 + P.BOARD_TABS[0][0] - P.TAB_POCKET_CLR_U - P.H_U0 >= P.WALL_MIN - 1e-9
    assert P.H_U1 - (P.BOARD_U0 + P.BOARD_TABS[1][2] + P.TAB_POCKET_CLR_U) >= P.WALL_MIN - 1e-9


def test_gib_bores_stay_under_the_cavity_floor():
    """Review fix e: the lock bore broke 0.3 mm into the cavity floor."""
    assert P.CAV_FLOOR - (P.GIB_Z + max(P.PLUNGER_BORE_D, P.LOCK_BORE_D) / 2) >= 0.6 - 1e-9
    # and the bores push the gib inside its height
    assert P.YGIB["z0"] < P.GIB_Z < P.YGIB["z1"]


def test_gib_bores_clear_battery_and_roller():
    """D4 moved the battery pocket to u 29.5..65.5: every y bore (with its top insert) lies left of it."""
    for u in P.YGIB_PLUNGERS_U + [P.LOCK_U]:
        assert u + P.INSERT_M3_D / 2 + P.WALL_MIN <= P.BAT_POCKET["u0"] + 1e-9
        assert u - P.INSERT_M3_D / 2 >= P.STEP_U1


def test_rf_metal_above_pusher_top():
    """Metal of the Y plungers / lock (springs, screws, inserts) keeps >= 5 mm from the antenna in plan."""
    assert P.PUSHER_TOP_Y - P.ANTENNA[3] >= P.RF_CLEAR - 1e-9
    assert P.H_Y1 - P.INSERT_M3_L - P.ANTENNA[3] >= P.RF_CLEAR - 1e-9


def test_tab_clamp_stack():
    assert P.CLAMP_CEIL_Z == pytest.approx(P.BOARD_Z1 + P.STANDOFF_H + P.CLAMP_WASHER_T + P.EPOXY_GAP)
    # printed clamp plate between the ceiling and the head counterbore
    assert P.CLAMP_CBORE_Z - P.CLAMP_CEIL_Z >= 1.2 - 1e-9
    # the head fits the body counterbore + the lid pocket, with lid material above
    assert P.CLAMP_CBORE_Z + P.CLAMP_HEAD_K <= P.Z_LID_IN + P.LID_HEAD_POCKET + 1e-9
    assert P.Z_LID - (P.Z_LID_IN + P.LID_HEAD_POCKET) >= 0.6 - 1e-9
    # an M2 x 4 from the head seat ends inside the board (never below it: 0.15 over the beam)
    tip = P.CLAMP_CBORE_Z - 4.0
    assert P.BOARD_Z0 < tip < P.BOARD_Z1 + 1e-9


def test_parts_under_the_glass_clear_the_bezel():
    assert P.BOARD_Z1 + P.H_UNDER_GLASS <= P.Z_LID_IN - P.DISP_T - 0.05 + 1e-9


@pytest.mark.parametrize("R", [0.0, P.RANGE + P.OVERTRAVEL])
def test_slider_clears_beam_and_fixed_jaw(R):
    body = M.Pos(R, 0, 0) * M.slider_body()
    for other in (M.beam(), M.fixed_jaw(), M.stop_screw()):
        inter = body & other
        assert inter is None or inter.volume < 1e-3


def test_stop_position():
    # the right end face meets the screw head exactly at RANGE + OVERTRAVEL
    assert M.stop_x() - P.STOP_D / 2 == pytest.approx(P.RANGE + P.OVERTRAVEL + P.H_U1)
    assert M.stop_x() + P.STOP_D / 2 < P.BEAM_X1


def test_inside_jaws_print_on_their_beds_and_cross():
    """Review fix d: the moving inside jaw starts on the slider's bed (z_min), the fixed one on the
    fixed jaw's bed (it prints front face down, z_max); the two cross with a z gap."""
    assert P.IJ_MOVING_Z[0] == pytest.approx(M.slider_body().bounding_box().min.Z)
    assert P.IJ_FIXED_Z[1] == pytest.approx(M.fixed_jaw().bounding_box().max.Z)
    assert P.IJ_FIXED_Z[0] - P.IJ_MOVING_Z[1] >= 0.15
    assert M.PARTS["fixed_jaw"].orient == (180, 0, 0)


def test_extrusions_go_up():
    fj = M.fixed_jaw().bounding_box()
    assert fj.min.Z == pytest.approx(P.FJ_Z0) and fj.max.Z == pytest.approx(P.FJ_Z1)
    sb = M.slider_body().bounding_box()
    assert sb.min.Z == pytest.approx(P.Z_BACK) and sb.max.Z == pytest.approx(P.Z_LID_IN)


def test_body_prints_flat():
    """Nothing hangs below the body's back face (the first back-web draft had bosses there)."""
    s = M.print_pose("slider_body")
    assert s.bounding_box().min.Z == pytest.approx(0.0)
    assert M.slider_body().bounding_box().min.Z == pytest.approx(P.Z_BACK)


def test_sliding_force_in_target():
    mu = 0.15
    F = 2 * (2 * P.P_BACK + 2 * P.P_Y) * mu
    assert 2.0 <= F <= 5.0


def test_yaw_preload_margin():
    lever = sum(P.H_U1 - u for u in P.YGIB_PLUNGERS_U)
    p_end = P.JAW_FORCE * (37.0 + 35.0) / lever
    assert P.P_Y / p_end >= 1.25


def test_rf_carbon_filled_jaws_clear_the_antenna():
    """SPEC D4: the PA-CF moving inside jaw (relieved root flank) and the fixed jaw at R = 0 keep
    >= RF_CLEAR from the antenna area in plan; the relief leaves the measuring tip alone."""
    a = P.ANTENNA
    ant = M.box(P.bu(a[0]), P.bu(a[2]), a[1], a[3], -60, 60)
    jaw = M.prism(M.moving_inside_jaw_pts(), *P.IJ_MOVING_Z)
    assert jaw.distance_to(ant) >= P.RF_CLEAR - 1e-6
    assert M.fixed_jaw().distance_to(ant) >= P.RF_CLEAR - 1e-6
    pts = M.moving_inside_jaw_pts()
    for p in [(-P.IJ_TIP_W, P.IJ_TIP_Y1), (0, P.IJ_TIP_Y1), (0, P.IJ_TIP_Y0), (-P.IJ_TIP_W, P.IJ_TIP_Y0)]:
        assert p in pts
    # the scallop stays shallow, and the root is not narrower than the phase-3 one
    old = M.prism(P.moving_inside_jaw_outline(rf_relief=False), *P.IJ_MOVING_Z)
    assert (old - jaw).volume <= (jaw - old).volume


def test_fixed_jaw_bolt_engages_the_nut():
    """The M3 x 10 from the front face runs through the whole nut, ends under the back face, and the
    trap floor keeps a web over the beam slot."""
    end = P.FJ_Z1 - P.FJ_SCREW_L
    seat = P.FJ_Z0 + P.FJ_NUT_TRAP_DEPTH
    assert seat - end >= P.NUT_M3_M - 1e-9                 # full nut engaged (nominal)
    assert end - P.FJ_Z0 >= 0.5                             # not proud of the back face
    assert seat - P.NUT_M3_M >= P.FJ_Z0 + 0.5               # nut fully inside the trap
    assert -P.BEAM_T - 0.05 - seat >= 0.8                   # web between trap floor and beam slot
    fj = M.fixed_jaw()
    assert fj.is_valid
