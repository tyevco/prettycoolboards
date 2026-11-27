"""The tools themselves: the runner against closed-form answers, the design-value readers, and the contract's
numbers against the datasheet equations at the captured resistor values."""

import math
import os

import numpy as np
import pytest

import design
import spice


@pytest.mark.nospice
def test_parse_value():
    assert design.parse_value("47") == 47
    assert design.parse_value("1n C0G") == pytest.approx(1e-9)
    assert design.parse_value("2.2n") == pytest.approx(2.2e-9)
    assert design.parse_value("1.47k") == pytest.approx(1470)
    assert design.parse_value("10u/25V") == pytest.approx(1e-5)
    assert design.parse_value("20m") == pytest.approx(0.02)
    assert design.parse_value("1R") == 1
    assert design.parse_value("4k7") == pytest.approx(4700)
    assert design.parse_value("TPS2553") is None


@pytest.mark.nospice
def test_design_values_come_from_the_capture(board):
    """The lane RC and the breakers' parts are read from the generated netlist when it exists."""
    if not os.path.exists(design.MB_NETLIST):
        pytest.skip("motherboard netlist not generated yet")
    prov = design.provenance()
    # every capture value: a part renamed, removed or moved to another net must not fall back to the default quietly
    captured = {k: v for k, v in prov.items() if v.startswith(("netlist", "default"))}
    assert len(captured) >= 20, sorted(captured)
    fallen = {k: v for k, v in captured.items() if not v.startswith("netlist")}
    assert not fallen, f"capture values not found in the netlist (the benches used defaults): {fallen}"
    assert board["R_lane"] == 47.0 and board["C_lane"] == pytest.approx(1e-9)


@pytest.mark.nospice
def test_every_slot_switch_matches_the_simulated_one(board):
    """The benches simulate S1's TPS2553s and socket capacitors. S2-S5 must carry the same R_ILIM and capacitors
    (S5's 5 V rail is U5, with its own capacitor), or the slot results say nothing about them."""
    parts = design.slot_switch_parts()
    if not parts:
        pytest.skip("motherboard netlist not generated yet")
    bad = []
    for s, p in parts.items():
        if p["r_ilim3"] != board["r_ilim_3v3"] or p["c_3v3"] != pytest.approx(board["s3v3_socket_c"]):
            bad.append((s, "3V3", p["r_ilim3"], p["c_3v3"]))
        if s < 5 and (p["r_ilim5"] != board["r_ilim_5v"] or p["c_5v"] != pytest.approx(board["s5v_socket_c"])):
            bad.append((s, "5V", p["r_ilim5"], p["c_5v"]))
    assert not bad, f"slots that differ from S1: {bad}"


@pytest.mark.nospice
def test_spec_values_are_read_from_spec():
    """The SPEC figures the tests compare against are read from SPEC.md, not copied: the coupon bulk rule, the
    working-point sampling time and the keys tables."""
    design.spec_coupon_bulk()
    design.spec_adc_smp()
    design.spec_keys_tables()
    prov = design.provenance()
    for key in ("coupon_bulk", "adc_smp"):
        assert prov[key].startswith("SPEC.md"), f"{key}: {prov[key]}"
    assert "nothing found" not in prov["spec_keys"]


@pytest.mark.nospice
def test_contract_trips_match_the_datasheet_at_the_captured_resistors(board):
    """nets.SWITCH_TRIP (the contract) against SLVS841G Eqs. 1-3 and SLVSFC9C Eq. 5 at the netlist's R_ILIM/R_ILM:
    a resistor changed in the capture without the contract (or the reverse) fails here."""
    for key, r in (("trip_3v3", board["r_ilim_3v3"]), ("trip_5v", board["r_ilim_5v"])):
        want = design.tps2553_trip_from_r(r)
        assert board[key] == pytest.approx(want, abs=0.002), key
    for key, r in (("trip_s5", board["s5_r_ilm"]), ("trip_vsys", board["u2_r_ilm"])):
        want = design.tps25947_ilim(r)
        assert board[key] == pytest.approx(want, abs=0.011), key


@pytest.mark.nospice
def test_tps25947_interpolation_reproduces_the_table():
    for r, lo, ty, hi in design.TPS25947["ILIM_ROWS"]:
        got = design.tps25947_ilim(r)
        assert got[0] / got[1] == pytest.approx(lo / ty, rel=1e-9)
        assert got[2] / got[1] == pytest.approx(hi / ty, rel=1e-9)


@pytest.mark.nospice
def test_itimer_window_matches_the_capture_note(board):
    """mb_slots.py and mb_power.py say 2.2 nF gives 1.85 ms (Eq. 6, typ); the datasheet spread widens it."""
    lo, ty, hi = design.itimer_window(board["s5_c_itimer"])
    assert ty == pytest.approx(1.85e-3, rel=0.01)
    assert lo == pytest.approx(1.13e-3, rel=0.01) and hi == pytest.approx(3.19e-3, rel=0.01)


@pytest.mark.nospice
def test_table98_fit_is_what_the_readme_says():
    fit = design.adc_table98_fit()
    for n, (c, r0) in fit.items():
        assert 12e-12 < c < 17e-12, n
        assert 1.2e3 < r0 < 1.7e3, n
        assert 16e-9 < c * r0 < 23e-9, n            # the network's own time constant, tau0
    br = design.adc_brackets()
    assert br["T97"][1] == 5e-12 and 4.0e3 < br["T97"][0] < 5.0e3
    assert br["T98fit"][0] * br["T98fit"][1] == pytest.approx(br["T97"][0] * br["T97"][1])


@pytest.mark.nospice
def test_adc_values_against_ds13543():
    """The DS13543 Rev 2 numbers the lane bench uses (Tables 87, 97, 98), so an edit that drifts from the datasheet
    shows up here."""
    a = design.ADC
    assert a["C_ADC"] == 5e-12 and a["C_IO"] == 5e-12
    assert a["I_LKG"] == 500e-9 and a["I_LKG_FT_T"] == 300e-9     # TT_xx and FT_t I/Os, VIN <= VDD
    assert a["N_conv"] == 17 and a["t_LATR_cycles"] == 13
    assert a["SMP"] == (5, 6, 12, 20, 36, 68, 391, 814)
    assert design.TABLE98[14] == [(47, 142), (68, 145), (100, 170)]
    assert design.TABLE98[8][-1] == (10000, 830) and design.TABLE98[12][-1] == (470, 180)


def test_runner_rc_step_matches_closed_form():
    w = spice.run("V1 in 0 PWL(0 0 1n 3.3)\nR1 in a 47\nC1 a 0 1n", ["v(a)"], "tran 0.1n 2u 0 1n")
    tau = 47 * 1e-9
    for t in (0.1e-6, 0.3e-6, 0.5e-6):
        want = 3.3 * (1 - math.exp(-(t - 0.5e-9) / tau))
        assert abs(w.at("v(a)", t) - want) < 0.05 * design.LSB14, t


def test_runner_charge_sharing_conserves_charge():
    """The kickback mechanism: 5 pF at 3.3 V shared with 1 nF at 0 V through a switch settles at the charge
    balance, to well under a microvolt."""
    net = "\n".join([
        "Ca a 0 1n IC=0", "Cb b 0 5p IC=3.3", "Vg g 0 PWL(0 0 10n 0 11n 1)",
        "S1 a b g 0 sw", ".model sw SW(VT=0.5 VH=0.01 RON=1k ROFF=1e15)",
    ])
    w = spice.run(net, ["v(a)", "v(b)"], "tran 0.1n 300n 0 0.2n uic")
    want = 3.3 * 5e-12 / (1e-9 + 5e-12)
    assert w["v(a)"][-1] == pytest.approx(want, abs=1e-6)
    assert w["v(b)"][-1] == pytest.approx(want, abs=1e-6)


def test_settle_time_and_crossings():
    t = np.linspace(0, 10, 1001)
    e = np.exp(-t)
    assert spice.settle_time(t, e, math.exp(-5)) == pytest.approx(5.0, abs=0.01)
    assert spice.crossings(t, np.sin(t), 0.0)[0] == pytest.approx(math.pi, abs=0.01)
    assert spice.longest_run(t, (t > 2) & (t < 4)) == pytest.approx(2.0, abs=0.03)


@pytest.mark.nospice
def test_power_values_against_datasheets():
    """The datasheet constants the power benches use, as read on 2026-11-27 (SLVS841G §6.5, SLVSFC9C §6.5/§6.6/
    Eq. 4-6, SBASAI5E §6.3/§6.5, SLVSF16B §7.3, SLLSEQ8D, LDL1117 and AP2112 tables)."""
    t = design.TPS2553
    assert t["R_ON"] == (0.085, 0.135) and t["t_IOS"] == 2e-6 and t["deglitch"] == (3e-3, 7.5e-3, 11e-3)
    assert t["t_r_2v5"] == (0.7e-3, 1.0e-3) and t["t_r_6v5"] == (1.1e-3, 1.5e-3)
    assert [round(x * 1e3) for x in design.tps2553_ios(90.9)] == [258, 292, 331]      # SPEC §3.1, no R tolerance
    u = design.TPS25947
    assert u["R_ON"] == (0.0283, 0.045) and u["K_ILM"] == 3334.0 and u["K_dVdt"] == 2000.0
    assert u["I_ITIMER"] == (1.2e-6, 1.8e-6, 2.5e-6) and u["dV_ITIMER"] == (1.286, 1.51, 1.741)
    assert u["I_dVdt"] == (0.81e-6, 2.21e-6, 3.82e-6)
    assert u["V_UVLO_R"] == (1.183, 1.20, 1.223) and u["V_UVLO_F"] == (1.076, 1.09, 1.116)
    assert u["ILIM_ROWS"][2] == (1650, 1.800, 2.028, 2.200) and u["ILIM_ROWS"][3] == (750, 3.960, 4.452, 4.840)
    assert design.TMAG5253["R_OUT"] == 1.27 and design.TMAG5253["I_O"] == 1e-3 and design.TMAG5253["C_LOAD_MAX"] == 1e-9
    assert design.DRV8316["VM_MIN"] == 4.5 and design.DRV8316["UVLO_FALL"] == (4.1, 4.2, 4.3)
    assert design.TUSB320["VBUS_THR"] == (2.95, 3.3, 3.8)
    assert design.LDL1117["V_DROP_MAX"] == 0.600 and design.LDL1117["I_SC_MIN"] == 1.5
    assert design.AP2112K["V_DROP"][0.600] == (0.250, 0.400)
