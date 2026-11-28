"""The manual checklist (bench.py checklist)."""

from tbbench import checklist


def test_items_are_complete_and_unique():
    ids = [i.id for i in checklist.ITEMS]
    assert len(ids) == len(set(ids))
    for i in checklist.ITEMS:
        assert i.action and i.expect and i.ref and i.tool, i.id


def test_the_checks_spec_asks_for_before_and_at_power_on():
    text = checklist.render("text")
    for must in ("CC1 to GND", "JP_3V3_S1..S5", "current limit", "25 ms", "t_I2C_EN", "Type-A-to-C",
                 "NO host on the same cable", "Every coupon unplugged", "VCAP"):
        assert must in text, must


def test_markdown_has_blanks():
    md = checklist.render("md")
    assert md.startswith("# Testbed bring-up: the manual checklist")
    assert "| Measured / done |" in md and md.count("\n| U") >= 8
    assert "not built" in md


def test_phase_filter():
    t = checklist.render("text", "unpowered")
    assert "UNPOWERED" in t and "FIRST POWER" not in t


def test_the_numbers_it_quotes_are_nets_py_s(limits):
    """The checklist is prose, so its figures are typed in; this ties each one to nets.py, so a change to the
    contract fails here instead of leaving the bench sheet behind."""
    text = checklist.render("text")
    t = limits.trips_ma
    assert f"3.3 V {t['+3V3_S1'][0]}-{t['+3V3_S1'][2]} mA" in text
    assert f"5 V {t['+5V_S1'][0]}-{t['+5V_S1'][2]} mA" in text
    assert f"S5 breaker {t['+5V_S5'][0] / 1000:.2f}-{t['+5V_S5'][2] / 1000:.2f} A" in text
    assert f"needs {t['+5V_S1'][2]} mA plus the base load" in text
    assert f"the {len(limits.monitors)} INA226s" in text
    tusb = limits.nets["TUSB320_ADDR"]
    assert limits.cc_addr == tusb["VDD"] == 0x67
    assert limits.monitors[tusb["GND"]].rail == "+3V3_S4", "the address U_CC takes with ADDR low"
    assert "answers at 0x47, the +3V3_S4 INA226's address" in text
    for s in limits.slots:
        assert f"+3V3_S{s}" in text and f"+5V_S{s}" in text


def test_markdown_rows_keep_their_columns():
    """Seven columns per row: a "|" inside a cell (S4's "default|1.5A|...") is escaped, or it splits the row."""
    import re
    rows = [r for r in checklist.render("md").splitlines() if r.startswith("| ")]
    assert len(rows) == len(checklist.ITEMS) + 1
    for r in rows:
        assert len(re.findall(r"(?<!\\)\|", r)) == 8, r


def test_the_decisions_of_2026_11_27_are_on_the_list(limits):
    """D2's key, D3's series resistors, D4's divider and damping leg, D7's diode and INJ lead, D1's order."""
    text = checklist.render("text")
    key = limits.nets["SLOT_KEY_PIN"]
    for must in (f"hole {key} plugged", f"no pin {key}", "R36 44.2 k", "R103 0.47 ohm", "C118 10 uF",
                 "100 ohm each", "D11 (1N4148W)", "TP1 (+3V3) to TP15 (INJ)", "--key-check", "--turned-test",
                 "the test coupon in every slot first", "--coupon N=hall", "EL-5", "EL-6"):
        assert must in text, must


def test_the_refs_it_names_are_the_sheets(limits):
    """The checklist names R35/R36 and R103/C118 by reference: hold them to the sheets that place them."""
    design = limits.nets_path.parent / "sheets"
    power = (design / "mb_power.py").read_text()
    mcu = (design / "mb_mcu.py").read_text()
    assert 'res(d, "R35"' in power and 'res(d, "R36"' in power and "INPUT_PGTH_DIVIDER" in power
    assert "R103 0.47 Ohm" in mcu and "C118 10 uF" in mcu
    sheet = (design / "test_coupon.py").read_text()
    assert 'd.add("D11", "Diode:1N4148W"' in sheet and '"INJ", "IRQ_N"' in sheet
    assert 'testpoints(d, 10, ["AN0", "AN1", "AN2", "AN3", "SYNC", "INJ"' in sheet, "TP15 is INJ (10 + 5)"
