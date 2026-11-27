"""The input (SPEC §3.1, §3.2, §3.5, §3.8): start-up, and the 2.8 A ceiling through a USB cable."""

import pytest

import bench_input
import design

COMPLIANT = f"ceiling_{design.USB['R_CABLE_TYPEC_3A']:.3f}"


@pytest.mark.parametrize("corner", ["min", "typ", "max"])
def test_3v3_rises_within_ucc_vdd_ramp(inp, corner):
    """SPEC §3.5/§3.8: U2's dV/dt start must bring +3V3 (U_CC's VDD) up within 25 ms, at any I_dVdt."""
    r = inp[f"startup_{corner}"]
    assert r["u2_on"]
    assert r["t_3v3_ramp_99"] is not None and r["t_3v3_ramp_99"] < 25e-3


@pytest.mark.parametrize("corner", ["min", "typ", "max"])
def test_startup_inrush_below_input_ilim(inp, board, corner):
    r = inp[f"startup_{corner}"]
    assert not r["u2_tripped"]
    assert r["i_inrush"] < design.tps25947_ilim(board["u2_r_ilm"], 0.01)[0]
    assert r["v_vsys_final"] > 4.9


@pytest.mark.nospice
def test_ceiling_below_input_breaker_with_resistor_tolerance(board):
    """SPEC §3.1: the 2.8 A ceiling sits below the input breaker's minimum, here with R_ILM's 1 % as well."""
    assert board["vsys_budget_max"] < design.tps25947_ilim(board["u2_r_ilm"], 0.01)[0]


@pytest.mark.nospice
def test_vbus_capacitance_within_usb_inrush_limit(board):
    """SPEC §3.5: no more than 10 uF on VBUS before the breaker."""
    assert board["c_vbus"] <= 10e-6


def test_ceiling_compliant_cable_keeps_u2_on(inp):
    """At 2.8 A from a 4.75 V source through a 3 A Type-C cable at its IR-drop limit, U2 is on before the step and
    stays on: VBUS at J1 stays above U2's UVLO falling threshold (pin maximum, divider at its 1 % corner) and above
    U_CC's VBUS detection threshold."""
    r = inp[COMPLIANT]
    assert r["u2_on_at_step"]
    assert not r["u2_uvlo_off"] and not r["u2_tripped"]
    assert r["margin_uvlo"] > 0
    assert r["margin_ucc"] > 0.2


@pytest.mark.xfail(strict=True, reason="with U2's EN/UVLO divider (100 k / 39 k, 1 %) at its corner the falling "
                   "threshold at VBUS is up to 4.035 V; at 2.8 A through a compliant 3 A cable from 4.75 V, VBUS at J1 "
                   "is 4.049 V: 14 mV of margin (72 mV with exact resistors), none left for contact wear or a source "
                   "that sags on the step")
def test_ceiling_compliant_cable_uvlo_margin_50mv(inp):
    assert inp[COMPLIANT]["margin_uvlo"] > 0.05


@pytest.mark.xfail(strict=True, reason="U2's PG divider (100 k / 39 k on VSYS_IN, the same as the UVLO divider) "
                   "falls at up to 3.98 V (4.035 V with 1 % resistors); at 2.8 A through a compliant cable from 4.75 V, "
                   "VSYS_IN is about 3.92 V, so VSYS_PG (a status input on U_EXP2 P12) can deassert while the board "
                   "runs")
def test_ceiling_compliant_cable_keeps_vsys_pg(inp):
    assert inp[COMPLIANT]["margin_pg"] > 0


@pytest.mark.xfail(strict=True, reason="a 0.3 Ohm cable is beyond Type-C's limit for a 3 A cable; at 2.8 A from "
                   "4.75 V, VBUS at J1 falls to about 3.9 V, below U2's UVLO, and U2 turns off and on repeatedly")
def test_ceiling_0p3_ohm_cable_keeps_u2_on(inp):
    assert not inp["ceiling_0.300"]["u2_uvlo_off"]


def test_ceiling_short_cable_has_margin(inp):
    r = inp["ceiling_0.100"]
    assert r["u2_on_at_step"]
    assert not r["u2_uvlo_off"] and r["margin_uvlo"] > 0.3 and r["margin_pg"] > 0.2
    assert r["v3v3_min"] > 3.2


def test_sim_matches_the_dc_arithmetic(inp):
    """The transient's steady state agrees with Ohm's law (dc_table) to 15 mV: the models add no hidden drop."""
    rows = {(round(x["v_src"], 2), round(x["r_cable"], 3)): x for x in bench_input.dc_table()}
    r = inp["ceiling_0.100"]
    want = rows[(4.75, 0.1)]
    assert r["vbus_end"] == pytest.approx(want["vbus"], abs=0.015)
    assert r["vsys_end"] == pytest.approx(want["vsys"], abs=0.015)
