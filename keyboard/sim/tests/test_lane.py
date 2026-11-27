"""Lane front end (SPEC §4.3, §6.2, §6.3, §11 #21): the margins SPEC's per-step arithmetic relies on.

The ADC brackets are design.adc_brackets(): `T97` (Table 97's 5 pF behind the internal time constant Table 98
supports) is the reference for pass/fail, `T98fit` (14 pF) an upper bound, `fast` (a 7 ns switch) SPEC's own
assumption. SPEC's working-point sampling time is read from SPEC.md (`lane["smp_spec"]`, 12 cycles on 2026-11-27),
so a SPEC change of t_s reaches these tests: the xfails below that name it turn into strict XPASS failures.
"""

import pytest

import bench_lane
import design

HALF = 0.5


def test_kickback_bound_matches_spec_arithmetic(lane):
    """SPEC §6.3: a step of up to 3.3 V x 5 pF / 1005 pF (82 LSB) at the pin. The simulated step is at most that
    (the 47 Ohm already supplies charge while R_ADC shares it)."""
    bound = 3.3 * 5 / 1005 / design.LSB14
    for key in ("kick_stiff_1n_T97", "kick_r1k_1n_T97", "kick_stiff_1n_fast"):
        assert lane[key]["pin_step_lsb"] <= bound * 1.01, key


def test_kickback_fast_switch_reproduces_spec(lane):
    """SPEC §6.3's 0.14 LSB after 12 cycles assumes the sampling switch adds nothing. With a 7 ns switch (`fast`)
    the sim gives about 0.24 LSB, under half an LSB: the sim reproduces SPEC under SPEC's own assumption."""
    assert lane["kick_stiff_1n_fast"]["err_lsb_at_smp"][12] < HALF
    # SPEC's own arithmetic: 82 LSB recovering through 47 Ohm x 1005 pF for 300 ns
    assert bench_lane.kickback_analytic(1e-9, 5e-12, 47.0, 12 / 40e6) == pytest.approx(0.14, abs=0.01)


@pytest.mark.xfail(strict=True, reason="DS13543 gives no R_ADC. Table 98's rows put the sampling network's own time "
                   "constant at 17-23 ns (design.adc_brackets); behind Table 97's 5 pF that is up to 4.5 kOhm, and "
                   "SPEC's working-point t_s of 12 cycles then leaves about 0.63 LSB on a stiff lane (SPEC: 0.14 LSB, "
                   "which assumes a switch of a few ns). 20 cycles leave 0.01 LSB")
def test_kickback_stiff_source_settles_at_spec_ts(lane):
    """SPEC §6.2/§6.3: the working-point t_s is enough for a stiff lane."""
    assert lane["kick_stiff_1n_T97"]["err_lsb_at_smp"][lane["smp_spec"]] < HALF


def test_kickback_stiff_source_settles_in_20_cycles(lane):
    """20 cycles (500 ns) clear half an LSB in every bracket, the 14 pF upper bound included."""
    for adc in ("T97", "T98fit"):
        assert lane[f"kick_stiff_1n_{adc}"]["err_lsb_at_smp"][20] < HALF, adc


def test_kickback_1k_source_numbers(lane):
    """SPEC §6.3: about 62 LSB at 300 ns, about 5.4 us to half an LSB, and the 391-cycle step is enough."""
    k = lane["kick_r1k_1n_T97"]
    assert k["err_lsb_at_smp"][12] == pytest.approx(62, rel=0.15)
    assert k["settle_half_lsb"] == pytest.approx(5.4e-6, rel=0.10)
    assert k["err_lsb_at_smp"][391] < HALF
    assert k["err_lsb_at_smp"][68] > HALF        # SPEC: the step below 391 cycles is not enough
    assert lane["kick_r1k_1n_T98fit"]["err_lsb_at_smp"][391] < HALF


def test_kickback_680p_alternative(lane):
    """SPEC §4.3: about 24 mV worst case, recovering through 47 Ohm with tau about 32 ns."""
    k = lane["kick_stiff_680p_T97"]
    assert k["pin_step_lsb"] * design.LSB14 <= 3.3 * 5 / 685 * 1.01
    assert k["err_lsb_at_smp"][lane["smp_spec"]] < HALF


@pytest.mark.xfail(strict=True, reason="the upper bracket (all 14 pF of Table 98's single-RC fit kicking back) leaves "
                   "about 1.8 LSB after SPEC's 12 cycles; 20 cycles leave 0.03 LSB")
def test_kickback_c14p_settles_at_spec_ts(lane):
    assert lane["kick_stiff_1n_T98fit"]["err_lsb_at_smp"][lane["smp_spec"]] < HALF


def test_select_step_stiff_within_t_rc(lane, board):
    """SPEC §6.3: t_RC = (R_src + 47) x 1 nF x ln(2^15) = 0.49 us from a stiff source."""
    t_rc = bench_lane.t_rc_spec(design.TMAG5253["R_OUT"], board["C_lane"], board["R_lane"])
    assert lane["step_stiff_1n"]["settle_half_lsb"] <= 1.03 * t_rc


def test_select_step_1k_within_t_rc(lane, board):
    t_rc = bench_lane.t_rc_spec(1e3, board["C_lane"], board["R_lane"])
    assert lane["step_r1k_1n"]["settle_half_lsb"] <= 1.03 * t_rc


@pytest.mark.xfail(strict=True, reason="SPEC §6.3's t_RC counts only the motherboard's 1 nF; capacitance on the "
                   "coupon side of a 1 kOhm source (sensor outputs, a mux, the trace: 190 pF in SPEC §4.3's own "
                   "estimate) adds about 18 %")
def test_select_step_1k_with_coupon_capacitance_within_t_rc(lane, board):
    t_rc = bench_lane.t_rc_spec(1e3, board["C_lane"], board["R_lane"])
    assert lane["step_r1k_1n_cc"]["settle_half_lsb"] <= 1.03 * t_rc


@pytest.mark.xfail(strict=True, reason="SPEC §6.3 treats the TMAG5253 as stiff. Its datasheet rates the output at "
                   "+/-1 mA continuous (SBASAI5E §6.3; §9 adds that the current 'must not exceed the IO "
                   "specification, including current going into an external ADC') and gives no peak current; a "
                   "full-scale step into 47 Ohm + 1 nF asks for up to 70 mA. Clamped at 1 mA the step takes about "
                   "3.6 us. Unverified either way until bring-up step 3 measures it (SPEC §10, §11 #21)")
def test_tmag5253_rated_drive_settles_within_t_rc(lane, board):
    t_rc = bench_lane.t_rc_spec(design.TMAG5253["R_OUT"], board["C_lane"], board["R_lane"])
    assert lane["step_limited_1n"]["settle_half_lsb"] <= 1.03 * t_rc


@pytest.mark.xfail(strict=True, reason="a whole one-slot scan at SPEC's 12 cycles, worst residual, alternating "
                   "full-range lanes: about 0.59 LSB with the T97 bracket (0.22 LSB with SPEC's fast-switch "
                   "assumption); see test_kickback_stiff_source_settles_at_spec_ts")
def test_scan_stiff_within_half_lsb_at_spec_ts(lane):
    assert lane["scan_stiff_ts"]["max_abs_lsb"] < HALF


def test_scan_stiff_within_half_lsb(lane):
    """A whole one-slot scan with SPEC's step timing at 20 cycles, worst residual, alternating full-range lanes, in
    both brackets; at SPEC's own t_s the scan holds under SPEC's fast-switch assumption and with random lanes and
    a held residual."""
    assert lane["scan_stiff_20"]["max_abs_lsb"] < HALF
    assert lane["scan_stiff_20_T98"]["max_abs_lsb"] < HALF
    assert lane["scan_stiff_ts_fast"]["max_abs_lsb"] < HALF
    assert lane["scan_stiff_ts_hold_random"]["max_abs_lsb"] < HALF


@pytest.mark.xfail(strict=True, reason="with the Table 98 upper bracket (14 pF) the scan at SPEC's 12 cycles is off "
                   "by about 1.7 LSB; see test_kickback_c14p_settles_at_spec_ts")
def test_scan_stiff_c14p_within_half_lsb(lane):
    assert lane["scan_stiff_ts_T98"]["max_abs_lsb"] < HALF


def test_scan_1k_needs_391_cycles(lane):
    """SPEC §6.3: a 1 kOhm lane is tens of LSB off at the working-point t_s and fine at 391 cycles."""
    assert lane["scan_r1k_ts"]["max_abs_lsb"] > 20
    assert lane["scan_r1k_391"]["max_abs_lsb"] < HALF
    assert lane["scan_r1k_391_cc"]["max_abs_lsb"] < HALF


@pytest.mark.xfail(strict=True, reason="pin leakage is not in SPEC's budget: DS13543 Table 87 allows up to 500 nA on a "
                   "TT pin (PA3, PA4, PA5 and PB0 are lanes: S2_AN3, S3_AN0, S3_AN1, S4_AN2) and 300 nA on an FT_t "
                   "pin, which through 1047 Ohm is a 2.6 LSB (1.6 LSB) offset at 14 bits; stable offsets "
                   "calibrate out, leakage that moves with temperature does not")
def test_scan_1k_with_pin_leakage_within_half_lsb(lane):
    assert lane["scan_r1k_391_leak"]["max_abs_lsb"] < HALF


def test_lane_values_are_the_contract(board):
    """The bench simulates the lane the netlist carries; SLOT_PATH in nets.py names the same values."""
    nets = design.load_nets()
    assert "47 ohm" in nets.SLOT_PATH["AN0"] and "1 nF" in nets.SLOT_PATH["AN0"]
    assert board["R_lane"] == 47.0 and board["C_lane"] == pytest.approx(1e-9)


@pytest.mark.nospice
def test_all_twenty_lanes_match_the_simulated_lane(board):
    """The benches simulate S1 AN0. Every other lane in the netlist must carry the same R and C, or the results
    say nothing about it."""
    lanes = design.lanes_all()
    if not lanes:
        pytest.skip("motherboard netlist not generated yet")
    bad = {k: v for k, v in lanes.items()
           if v[0] != board["R_lane"] or v[1] is None or abs(v[1] - board["C_lane"]) > 1e-15}
    assert not bad, f"lanes that differ from S1 AN0 ({board['R_lane']} Ohm, {board['C_lane']} F): {bad}"


@pytest.mark.nospice
def test_keys_table_reproduces_spec():
    """bench_lane.keys_table is SPEC §6.3's arithmetic; it reproduces each of SPEC's four key-count rows, as SPEC.md
    prints them today (design.spec_keys_tables reads them, so a SPEC edit is checked against the arithmetic)."""
    spec = design.spec_keys_tables()
    missing = {"one_slot", "lockstep", "1k", "1k_391"} - set(spec)
    assert not missing, f"SPEC §6.3 no longer has these in a form this test can read: {missing}; re-check by hand"
    ts = design.spec_adc_smp()
    stiff = bench_lane.t_rc_spec(design.TMAG5253["R_OUT"])
    one = bench_lane.keys_table(stiff, ts, t_settles=tuple(spec["one_slot"]))
    assert {k: v[2] for k, v in one.items()} == spec["one_slot"]
    lock = bench_lane.keys_table(stiff, ts, conv_per_adc=9, t_settles=tuple(spec["lockstep"]))
    assert {k: v[2] for k, v in lock.items()} == spec["lockstep"]
    r1k = bench_lane.t_rc_spec(1e3)
    assert {k: v[2] for k, v in bench_lane.keys_table(r1k, ts, t_settles=tuple(spec["1k"])).items()} == spec["1k"]
    assert {k: v[2] for k, v in bench_lane.keys_table(r1k, 391, t_settles=tuple(spec["1k_391"])).items()} == \
        spec["1k_391"]


def test_twenty_cycle_remedy_costs_no_keys(lane):
    """Raising t_s from SPEC's 12 to 20 cycles adds 0.4 us per step and changes no row of SPEC's one-slot table."""
    rows = bench_lane.keys_with_simulated_settling(lane)
    spec = rows[f"SPEC (t_RC formula, {lane['smp_spec']} cycles)"]
    remedy = rows["TMAG5253, 20 cycles (this tool's recommendation)"]
    assert {k: v[2] for k, v in remedy.items()} == {k: v[2] for k, v in spec.items()}


def test_hall_coupon_buffered_lane_needs_20_cycles(lane):
    """The Hall coupon as captured (coupon_hall.py: an OPA2365 follower through 22 Ohm) leaves about 2.4 LSB after
    SPEC's 12-cycle working point and clears half an LSB at 20 cycles with either C_ADC bracket. The coupon's own
    notes estimate 1 LSB and 0.06 LSB. So the firmware must take t_s from the descriptor's R_src (SPEC §4.9), or
    the working point moves to 20 cycles."""
    assert lane["kick_buf22_1n_T97"]["err_lsb_at_smp"][lane["smp_spec"]] > HALF
    assert lane["kick_buf22_1n_T97"]["err_lsb_at_smp"][20] < HALF
    assert lane["kick_buf22_1n_T98fit"]["err_lsb_at_smp"][20] < HALF
    assert lane["scan_buf22_20"]["max_abs_lsb"] < HALF


@pytest.mark.parametrize("r_src,cycles", [(1.27, 20), (22, 20), (100, 36), (1000, 391)])
def test_sampling_time_lookup(r_src, cycles):
    """bench_lane.min_sampling_cycles: the SMP step a declared R_src needs (T97 bracket, 1 nF lane, worst residual)."""
    assert bench_lane.min_sampling_cycles(r_src) == cycles
