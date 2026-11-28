"""The +3V3A branch (SPEC §3.1, §3.7; risks.md EL-5; owner decision D4 of 2026-11-27): FB1 into the VDDA and VREF+
capacitors resonates, and the damping leg the contract names (nets.VDDA_DAMPING) is what tames it.

Removing the damping leg fails here three ways: from the contract (test_contract_names_the_damping_leg and every
model test, which take its values from nets.py), from the model's verdict (the bars below), and, once the motherboard
netlist carries the owner's decisions of 2026-11-27, from the capture (test_damping_leg_is_captured)."""

import pytest

import bench_vdda as bv
import design


@pytest.fixture(scope="module")
def vdda():
    return bv.run_all()


@pytest.mark.nospice
def test_contract_names_the_damping_leg():
    """D4: the contract names a damping leg on +3V3A (0.47 ohm + 10 uF, picked with this bench)."""
    leg = bv.contract_leg()
    assert leg is not None, "nets.VDDA_DAMPING is gone: the +3V3A branch is undamped again (risks.md EL-5)"
    net, ohms, farads = leg
    assert net and 0.33 <= ohms <= 0.68 and farads >= 10e-6, leg


@pytest.mark.nospice
def test_ldo_output_capacitance_within_its_stability_plan():
    """LDL1117 Figures 20-21: stable from 1 (5 V) or 3.3 uF (1.2 V) up to 22 uF nominal. Counting the leg's 10 uF in
    full (it sits behind FB1 and 0.47 ohm, so this is a bound), +3V3_SLOT's LDO stays inside the plan."""
    assert bv.ldo_cout_nominal("leg") <= bv.LDL1117_COUT_MAX


def test_undamped_branch_resonates_in_the_scan_band(vdda):
    """risks.md EL-5, reproduced with the LDO in the model: FB1 and the 2.2 uF peak by 6 dB or more at every bead
    inductance in the bracket, between about 75 and 320 kHz, where the scan's frame harmonics and step rates sit."""
    for l, r in vdda["compare"]["captured"].items():
        assert r["peak_db"] >= 6.0, (l, r["peak_db"])
        assert 50e3 < r["f_peak"] < 400e3, (l, r["f_peak"])
    assert vdda["bracket_captured"]["peak_db"] > bv.PEAK_DB_MAX_DERATED


def test_chosen_leg_removes_the_peaking(vdda):
    """With the contract's leg the peaking stays within 3 dB and |Z| at +3V3A within 1 ohm over the whole bracket
    (FB1 0.1-2 uH, the LDO's inductance x0.5-x2, the +3V3A capacitors at 1.3-2.2 uF)."""
    w = vdda["bracket_leg"]
    assert w["peak_db"] <= bv.PEAK_DB_MAX, w
    assert w["z_peak"] <= bv.Z_MAX, w


def test_chosen_leg_still_damps_with_its_capacitor_derated(vdda):
    """DC bias can take half a 10 uF MLCC's capacitance; at 47 % the leg still keeps the peaking within 6 dB, against
    up to 21 dB undamped."""
    assert vdda["bracket_leg_derated"]["peak_db"] <= bv.PEAK_DB_MAX_DERATED


def test_chosen_leg_keeps_the_adcs_own_current_off_the_reference(vdda):
    """The ADCs' current at the start of a scan window (2.66 mA, DS13543 Tables 97 and 100) moves VREF+ inside the
    window by at most 3 LSB at mid-scale with the leg, for any FB1 inductance in the bracket. Undamped it is up to
    about 10 LSB; a resistor in place of FB1 (the other option of D4) turns the same current into 5.6-12.7 LSB,
    because its 1-2.2 ohm sits at DC."""
    assert vdda["burst_leg_bracket"] <= bv.BURST_PP_MAX
    assert vdda["burst_captured_2uH"]["pp_lsb"] > bv.BURST_PP_MAX
    for opt in ("r1", "r2p2"):
        assert vdda[f"burst_{opt}"]["pp_lsb"] > bv.BURST_PP_MAX, opt
        assert vdda[f"burst_{opt}"]["pp_lsb"] > vdda["burst_leg_bracket"], opt


def test_chosen_leg_keeps_the_dc_path(vdda):
    """The leg leaves +3V3A's DC impedance at FB1's (0.1 ohm max), so VREF+ stays ratiometric with the slot rails at
    DC (SPEC §3.1); the resistor options put 1-2.2 ohm there."""
    for l, r in vdda["compare"]["leg"].items():
        assert r["z_dc"] < 0.12, (l, r["z_dc"])
    assert vdda["compare"]["r1"][None]["z_dc"] > 0.9


@pytest.mark.nospice
def test_damping_leg_is_captured():
    """Once the motherboard netlist carries the owner's decisions of 2026-11-27 (D3's socket-side nets are the
    marker), it must also carry the leg: one resistor from +3V3A to the contract's net and one capacitor from it to GND,
    at the contract's values. Before that recapture the test is an expected failure, reported, not silent."""
    leg = bv.contract_leg()
    assert leg is not None
    net, ohms, farads = leg
    got = design.vdda_leg_captured(net)            # fitted parts only: a leg marked DNP is no leg
    if got is None and design.predates_decisions_2026_11_27():
        pytest.xfail("the motherboard netlist predates the owner's decisions of 2026-11-27 (no D3 socket-side nets, "
                     "no +3V3A damping leg yet): the motherboard capture adds both")
    assert got is not None, f"the motherboard netlist has no damping leg on +3V3A ({net}): D4 requires one"
    assert got[0] == pytest.approx(ohms) and got[1] == pytest.approx(farads), got
