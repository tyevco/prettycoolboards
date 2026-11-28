"""The limits the harness judges with, against the tables of SPEC (as of 2026-11-27) and the other sources.

If nets.py changes, these tests say which SPEC table the harness now disagrees with; the harness itself follows
nets.py, so a failure here means SPEC, nets.py or this file needs a look, not the harness's code.
"""

import json

import pytest

from tbbench import limits as L


def test_monitors_as_spec_3_4(limits):
    want = {0x40: ("VSYS", 2048, 4096), 0x41: ("+3V3_MCU", 2048, 164), 0x42: ("+3V3_USB", 1707, 82),
            **{0x43 + n: (f"+3V3_S{n}", 1939, 341) for n in range(1, 6)},
            **{0x48 + n: (f"+5V_S{n}", 2048, 819 if n < 5 else 4096) for n in range(1, 6)}}
    assert set(limits.monitors) == set(want), "13 monitors at SPEC §3.4's addresses"
    for addr, (rail, cal, fs) in want.items():
        m = limits.monitors[addr]
        assert (m.rail, m.cal) == (rail, cal), hex(addr)
        assert abs(m.full_scale_ma - fs) / fs < 0.005, hex(addr)


def test_trip_windows_as_spec_3_1(limits):
    assert limits.trips_ma["+3V3_S1"] == (256, 292, 335)
    assert limits.trips_ma["+5V_S4"] == (519, 577, 644)
    assert limits.trips_ma["+5V_S5"] == (2010, 2270, 2460)
    assert limits.trips_ma["VSYS"] == (2960, 3330, 3620)


def test_budget_as_spec_3_2(limits):
    assert [limits.budget_ma(s) for s in ("default", "1.5A", "3.0A", "accessory", "not_attached", "unreadable")] == \
        [500, 1500, 2800, 500, 500, 500]
    assert limits.budget_ma("3.0A", configured=False) == 100
    assert limits.vsys_max_ma == 2800


def test_bus_addresses(limits):
    assert set(limits.expanders) == {0x20, 0x21, 0x22}
    assert limits.expanders[0x20][1]["P00"] == "EN_3V3_S1" and limits.expanders[0x21][1]["P14"] == "USBC_INT_N"
    assert limits.mux_addr == 0x70 and limits.cc_addr == 0x67


def test_rail_ids_as_protocol_masks(limits):
    assert limits.rail_ids["+3V3_S1"] == 0 and limits.rail_ids["+5V_S1"] == 5 and limits.rail_ids["+5V_KVM"] == 10


@pytest.mark.parametrize("config,ms", [(0x4527, 35.2), (0x0527, 35.2), (0x0127, 2.2), (0x4127, 2.2),
                                       (0x0125, 1.1), (0x0007, 0.28), (0x0FFF, 1024 * 16.488)])
def test_ina226_result_period(config, ms):
    assert L.ina_period_ms(config) == pytest.approx(ms)


def test_the_firmware_settle_is_shorter_than_a_result():
    """The finding behind the harness's settle wait: 20 ms (Kconfig BRINGUP_SETTLE_MS) < 35.2 ms (monitors.h)."""
    kconfig = (L.REPO / "keyboard" / "firmware" / "bringup" / "Kconfig")
    if not kconfig.exists():
        pytest.skip("no bring-up firmware")
    text = kconfig.read_text()
    i = text.index("config BRINGUP_SETTLE_MS")
    settle = int(text[i:i + 400].split("default", 1)[1].split()[0])
    assert settle < L.ina_period_ms(0x0527)


def test_test_coupon_lanes_agree_everywhere():
    """0.2 / 0.4 / 0.6 / 0.8: the harness, the firmware lib's encoder and compiler v0's descriptor JSON."""
    import importlib.util
    if L.PCKD_TOOL.exists():
        spec = importlib.util.spec_from_file_location("cd_ext", L.PCKD_TOOL)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert tuple(x for x, _r in mod.TEST_LANES.values()) == L.TEST_LANE_RATIOS
        assert mod.TEST_LANE_TOL == L.TEST_LANE_TOL
    j = L.PCKC_TOOL.parent / "descriptors" / "test-coupon.json"
    if j.exists():
        assert tuple(json.loads(j.read_text())["ext"]["ratio"]) == L.TEST_LANE_RATIOS


def test_windows(limits):
    lo, hi = limits.always_on_window_mv("+3V3_MCU", 40)
    assert 3200 < lo < 3240 and 3355 < hi < 3375
    lo, hi = limits.slot_3v3_window_mv(1.4)
    assert lo >= L.FW_MIN_3V3_MV and 3185 < lo < 3195 and hi < 3420
    assert limits.danger_ma("+3V3_S1", 120) == pytest.approx(133.0)
    assert limits.danger_ma("+3V3_S1") == pytest.approx(256 * 0.8)
    assert limits.danger_ma("+5V_S5", 1500) == pytest.approx(2010 * 0.8), "the classifier floor comes first"


def test_map_hash_reader(tmp_path):
    p = tmp_path / "m.h"
    p.write_text('#define TB_MAP_HASH "0123456789abcdef"\n')
    assert L.map_hash(p) == "0123456789abcdef"
    assert L.map_hash(tmp_path / "missing.h") is None


def test_cal_rounds_as_zephyr(limits):
    """Zephyr's DIV_ROUND_CLOSEST in integers, not round() on a float: equal for every monitor today, and a half
    rounds up (Python's round() would take it to the even neighbour)."""
    for m in limits.monitors.values():
        assert m.cal == L.ina226_cal(m.lsb_ua, m.shunt_ohm)
    assert L.ina226_cal(1, 0.000002) == 2560000000          # exact
    assert L.ina226_cal(2, 0.000001) == 2560000000
    assert L.ina226_cal(3, 0.000002) == 853333333            # 853333333.33 rounds down
    assert L.ina226_cal(1024, 0.000001) == 5000000           # exact: 5120000000 / 1024
    assert L.ina226_cal(4096, 0.000005) == 250000            # exact
    assert L.ina226_cal(1, 0.003072) == 1666667              # 1666666.67 rounds up
    # 5120000000 = 2^16 x 5^7, so LSB x R = 2^17 uA x uohm gives exactly 39062.5: Zephyr 39063, round() 39062
    assert L.ina226_cal(1, 0.131072) == 39063 and round(5120000000 / 131072) == 39062


def test_map_hash_from_nets_is_gen_board_s(limits):
    """The hash a firmware built from this nets.py carries equals what gen_board.py wrote into the header (they
    differ only if the header is stale; the generator's own --check says the same)."""
    want = L.map_hash_from_nets(limits.nets_path)
    if want is None or L.map_hash() is None:
        pytest.skip("no gen_board.py or header in this checkout")
    assert want == L.map_hash()


def test_inj_facts_are_the_test_coupon_sheets(limits):
    """The INJ-to-lane figures (D7) come from sheets/test_coupon.py's DESCRIPTOR_FACTS, read without importing the
    schematic toolchain; the fallback constants in limits.py must say the same."""
    facts = L.inj_lane_facts()
    assert facts is not None and facts["lane"] == "AN0"
    assert tuple(facts["lift_v"]) == L.TEST_INJ_LIFT_V == limits.inj_lift_v
    shares = (1.0, *(facts["also_moves"][f"AN{k}"] for k in (1, 2, 3)))
    assert shares == L.TEST_INJ_SHARES == limits.inj_shares
    assert L.inj_lane_facts(L.HERE / "missing.py") is None


def test_usb_c_load_line(limits):
    """SPEC §3.6: V(J1) = 4.75 V - 0.25 ohm x I, then U2 at 45 mOhm and the 20 mOhm shunt before the INA226."""
    assert limits.vsys_load_line_mv(0) == pytest.approx(4750)
    assert limits.vsys_load_line_mv(1000) == pytest.approx(4750 - 1000 * (0.25 + 0.045 + 0.020))
    assert limits.vsys_shunt_ohm == limits.nets["INA226_RAILS"][0x40][1] == 0.020


def test_vsys_pg_thresholds_follow_the_divider(limits):
    fall = limits.vsys_pg["fall"]
    assert limits.nets["INPUT_PGTH_DIVIDER"] == (100e3, 44.2e3)
    assert 3.45 < fall[0] < 3.47 and 3.68 < fall[2] < 3.70, "SPEC §3.1: 3.46-3.69 V with 1 % resistors"


def test_a1_and_a2_are_spec_s_stages(limits):
    assert set(L.A1_COUPONS) == {"test", "hall"}
    assert not set(L.A1_COUPONS) & set(L.A2_COUPONS)
    for kind in L.A1_COUPONS:
        assert L.DESCRIPTOR_RECORDS[kind].exists()
