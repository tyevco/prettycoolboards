"""Slot power (SPEC §3.1, §3.5, §3.6, §4.9): enabling coupons, and the haptics slot's breaker and droop."""

import pytest

import bench_slot
import design

DEGLITCH_MIN = design.TPS2553["deglitch"][0]


@pytest.mark.parametrize("rail", ["3v3", "5v"])
@pytest.mark.parametrize("load", ["none", "r"])
@pytest.mark.parametrize("ios", ["min", "typ"])
def test_enable_at_the_bulk_limit_stays_under_the_fault_deglitch(slot, rail, load, ios):
    """SPEC §3.1/§4.9: a coupon within its rules is never tripped; its bulk is 'charged at the switch's limit'.
    Bulk only, or with a resistive load at the rule: the switch leaves current limit before FAULT can assert."""
    r = slot[f"en_{rail}_{load}_{ios}_nosoft"]
    assert r["t_lim"] < DEGLITCH_MIN, f"{r['t_lim'] * 1e3:.2f} ms in current limit"


@pytest.mark.xfail(strict=True, reason="SPEC §4.9 limits bulk capacitance (47 uF on +3V3) but not what the coupon "
                   "draws while its rail rises. A load that takes its full 250 mA from about 1 V up leaves 6 mA of "
                   "the 256 mA minimum limit to charge 47 uF: about 17 ms in current limit, past the 3-11 ms FAULT "
                   "deglitch (SLVS841G). bench_slot.bulk_limit() gives a rule that holds")
def test_enable_3v3_constant_current_load_at_rule(slot):
    assert slot["en_3v3_cc_min_nosoft"]["t_lim"] < DEGLITCH_MIN


@pytest.mark.xfail(strict=True, reason="as for +3V3: on +5V_Sn, 100 uF and a constant 500 mA load against the 519 mA "
                   "minimum limit stay in current limit for about 20 ms (5 ms even at the typical limit)")
def test_enable_5v_constant_current_load_at_rule(slot):
    assert slot["en_5v_cc_typ_nosoft"]["t_lim"] < DEGLITCH_MIN


@pytest.mark.parametrize("rail,i_load", [("3v3", 0.15), ("3v3", 0.2), ("5v", 0.3)])
def test_bulk_limit_rule_is_where_fault_starts(rail, i_load):
    """bulk_limit(): a coupon at the limit enables without FAULT; at 1.6 x it would assert FAULT. The rule is
    conservative (it assumes the load draws from 0 V; the bench's load starts at 1 V), but not by much."""
    c = bench_slot.bulk_limit(rail, i_load)
    ok = bench_slot.tps2553_enable(rail, "cc", "min", "none", c_bulk=c, i_load=i_load)
    bad = bench_slot.tps2553_enable(rail, "cc", "min", "none", c_bulk=1.6 * c, i_load=i_load, t_stop=40e-3)
    assert ok["t_lim"] < DEGLITCH_MIN < bad["t_lim"]


def test_slot_rail_reaches_its_final_voltage(slot, board):
    """The INA226 shunt, R_DS(on) and contacts drop I x R; at the 250 mA rule the coupon sees about 3.2 V."""
    r = slot["en_3v3_r_min_nosoft"]
    drop = 3.3 - r["v_final"]
    assert 0.07 < drop < 0.12           # SPEC §3.1: 81-94 mV at 250 mA plus the jumper's contact


def test_s5_detents_typical(slot):
    """1 A detent peaks (concept §8's estimate) from a 5 V source on a short cable: no trip, the DRV8316 in range."""
    r = slot["s5_detents_typ"]
    assert r["on_at_motor"]
    assert r["u5_trip_t"] is None and r["u2_trip_t"] is None
    assert r["v_coupon_min"] >= design.DRV8316["VM_MIN"]


def test_s5_board_drop_at_2a_is_about_spec(slot):
    """SPEC §3.6: about 0.2 V from J1 to the S5 pins at 2 A (typical R_ON); the sim uses R_ON max (45 mOhm), so
    allow up to 0.3 V. Here J1 is the source (no cable)."""
    r = slot["s5_rule_board_only"]
    assert r["on_at_motor"]
    drop = design.USB["V_SRC_MIN"] - r["v_coupon_min"]
    assert 0.15 < drop < 0.32


@pytest.mark.xfail(strict=True, reason="SPEC §3.6 puts 4.3-4.5 V at the coupon from a 4.75 V source before the cable. "
                   "With a 3 A Type-C cable at its IR-drop limit (0.25 Ohm round trip) and the board at its 2.8 A "
                   "ceiling the coupon sees about 3.7 V, below the DRV8316's UVLO (4.1-4.3 V falling, SLVSF16B)")
def test_s5_rule_at_the_ceiling_keeps_the_drv8316_up(slot):
    assert slot["s5_rule_ceiling_worst"]["v_coupon_min"] >= design.DRV8316["UVLO_FALL"][2]


@pytest.mark.xfail(strict=True, reason="1 A detents from a 4.75 V source through 0.25 Ohm with R_ON max dip the coupon "
                   "to about 4.34 V: above the DRV8316's UVLO but below its 4.5 V recommended minimum")
def test_s5_detents_worst_source_within_drv8316_range(slot):
    assert slot["s5_detents_worst"]["v_coupon_min"] >= design.DRV8316["VM_MIN"]


def test_s5_rule_holds_at_the_contracts_minimum_trip(slot):
    """nets.SWITCH_TRIP['+5V_S5'] minimum 2.01 A is above the 2 A rule: a steady 2 A does not trip U5."""
    assert slot["s5_rule_ilim_min"]["on_at_motor"]
    assert slot["s5_rule_ilim_min"]["u5_trip_t"] is None


@pytest.mark.xfail(strict=True, reason="SPEC §3.1 widens the TPS2553 trips for a 1 % R_ILIM but not the TPS25947's: "
                   "with R_ILM 1.47 kOhm at +1 % and I_LIM at its interpolated minimum the trip is 1.994 A, below the "
                   "2 A rule, and a coupon at its rule latches U5 off after the blanking time")
def test_s5_rule_holds_with_r_ilm_tolerance(slot):
    assert slot["s5_rule_ilim_min_rtol"]["u5_trip_t"] is None


def test_s5_transient_shorter_than_the_blanking_passes(slot):
    """SPEC §3.5: U5's C_ITIMER lets motor peaks above I_LIM pass if shorter than the blanking time (shortest
    corner here: 1.13 ms)."""
    assert slot["s5_burst_short_min_itimer"]["on_at_motor"]
    assert slot["s5_burst_short_min_itimer"]["u5_trip_t"] is None


def test_s5_overload_longer_than_the_blanking_latches_off(slot, board):
    lo, _, hi = design.itimer_window(board["s5_c_itimer"])
    r = slot["s5_burst_long_max_itimer"]
    assert r["u5_trip_t"] is not None
    assert lo < r["u5_trip_t"] < hi * 1.15
    assert slot["s5_burst_long_typ"]["u5_trip_t"] is not None


def test_s5_short_trips_fast_and_spares_the_input(slot):
    """A 10 A short on the coupon with nothing else on VSYS: U5's fast trip (2 x I_LIM) acts and U2 stays on. The
    model latches U5 at the fast trip; the datasheet (SLVSFC9C §7.3.5.4) turns the FET back on after 30 us in a
    current-limited manner and latches only on thermal shutdown, so this holds only while the rest of the board
    leaves U2 room for U5's limit: see test_s5_short_at_the_ceiling_spares_the_input."""
    r = slot["s5_short"]
    assert r["on_at_motor"]
    assert r["u5_trip_t"] is not None and r["u5_trip_t"] < 200e-6
    assert r["u2_trip_t"] is None and not r["u2_uvlo_off"]


@pytest.mark.nospice
@pytest.mark.xfail(strict=True, reason="after a fast trip the TPS25947 'tries to turn the HFET back on after a short "
                   "de-glitch interval (30 us) in a current limited manner' and, if the fault persists, 'stays in "
                   "current limit ... and eventually enter[s] thermal shutdown' (SLVSFC9C §7.3.5.4). With S5 shorted "
                   "and the other slots at the rest of the 2.8 A budget, U2 then carries up to 2.48 A (U5's I_LIM max "
                   "with R_ILM's 1 %) + 0.8 A = 3.28 A, above its 2.93 A minimum, for as long as U5 takes to reach "
                   "thermal shutdown: several ms at 11 W (Figures 6-36 and 6-37, read by eye), longer than U2's 1.13-3.19 ms "
                   "blanking. "
                   "U2 would latch the whole board off. The foldback below VOUT 1.9 V lowers U5's current by an "
                   "amount the datasheet does not give, so this is unverified either way: a bring-up test")
def test_s5_short_at_the_ceiling_spares_the_input(board):
    i_u5_max = design.tps25947_ilim(board["s5_r_ilm"], design.R_TOL)[2]
    rest = board["vsys_budget_max"] - board["rule_s5"]
    assert i_u5_max + rest < design.tps25947_ilim(board["u2_r_ilm"], design.R_TOL)[0]


def test_s5_enable_inrush_stays_under_ilim(slot, board):
    """U5's dV/dt start into 470 uF + 10 uF stays below I_LIM, so start-up current limiting never engages."""
    w = slot["s5_detents_typ"]["waves"]
    t = w.scale
    m = (t > 7e-3) & (t < slot["s5_detents_typ"]["t_motor"])
    assert w["i(VU5m)"][m].max() < design.tps25947_ilim(board["s5_r_ilm"], 0.01)[0]
