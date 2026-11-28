"""Motherboard power tree (SPEC §3.1-§3.4): input breaker, VSYS shunt, always-on and slot LDOs, MCU/USB shunts.

* **U2**, TPS259474L circuit breaker (SPEC §3.5; TI SLVSFC9C): IN = VBUS, OUT = VSYS_IN.
  - R_ILM 1.00 k: I_LIM = 3334 / R_ILM = 3.33 A typ (Eq. 5; SPEC §3.1 gives 2.96 / 3.33 / 3.62 A).
  - OVLO: 383 k / 100 k from VBUS: 1.20 V x 483 / 100 = 5.80 V rising (SPEC §3.5's 5.8 V target; 1.183-1.223 V
    and 1 % resistors give about 5.67-5.95 V, *estimate*). At 23 V the pin sees 4.8 V, inside its 6.5 V rating.
  - EN/UVLO: 100 k / 39 k from VBUS: on above 1.20 x 139 / 39 = 4.28 V, off below 1.09 x 139 / 39 = 3.88 V (Eq. 1;
    a proposal, SPEC sets no UVLO). The divider keeps the pin at 6.4 V or less up to 23 V (its rating is 6.5 V).
  - dVdt 2.2 nF: slew 2000 / 2200 pF = 0.91 V/ms (Eq. 4), so VSYS reaches 5 V in about 5.5 ms and +3V3 is up within
    about 4 ms of the start, well inside U_CC's 25 ms VDD ramp (SPEC §3.8); inrush into the about 36 uF of VSYS
    bulk and decoupling (every slot switch off) is about 33 mA (*estimate*).
  - ITIMER 2.2 nF: 1.85 ms blanking above I_LIM before it latches off (Eq. 6, proposal).
  - PGTH from a 100 k / 44.2 k divider on VSYS_IN (owner's decision D4 of 2026-11-27, nets.INPUT_PGTH_DIVIDER; was
    100 k / 39 k): PG (VSYS_PG, 10 k to +3V3, into U_EXP2 P12) falls at 3.51 / 3.56 / 3.64 V and rises at
    3.86 / 3.91 / 3.99 V (SLVSFC9C §6.5 thresholds x 144.2 / 44.2; SPEC §3.1): "about to brown out".
  - VBUS carries 4.7 uF before U2 (USB 2.0: <= 10 uF).
* **VSYS shunt** 20 mOhm (INA226 0x40, the whole board after the breaker; full scale 4.10 A, LSB 125 uA).
* **Kelvin sense** (owner's decision D4 of 2026-11-27, SPEC §7.5): each INA226's IN+ / IN- are on its own sense pair
  (PM40_SENSE_P / _N ...), joined to the shunt's pads by the net ties NT<aa>P / NT<aa>N
  (motherboard_parts.ina226). 0x41 and 0x42 share +3V3 on their IN+ side, and each has its own tie, at R39's and at
  R40's pad.
* **U3**, AP2112K-3.3 (SPEC §3.1): VSYS -> +3V3, always on (EN tied to VIN). 1 uF in, 10 uF out (stable with 1 uF
  ceramics, Diodes DS39724). Feeds the INA226s, expanders, mux, U_CC, bus switches, LEDs and pull-ups.
* **+3V3_MCU**: +3V3 through 0.5 Ohm (INA226 0x41, 164 mA full scale, 5.0 uA LSB): the MCU's VDD pins and VBAT.
* **+3V3_USB**: +3V3 through 1 Ohm (INA226 0x42, 82 mA, 2.5 uA): VDDUSB only.
* **U4**, LDL1117S33R (SPEC §3.1): VSYS -> +3V3_SLOT, 1 uF in, 4.7 uF out (ST §6.2). Feeds the five slot 3.3 V
  switches, and +3V3A (VDDA, VREF+) through FB1, which is drawn at VDDA on the MCU sheet.
* Probe pads (SPEC §7.5): VSYS, +3V3, +3V3_SLOT, +3V3A, and a Kelvin pair across each shunt.
"""

import nets
from sheets import motherboard_parts as mbp
from sheets.motherboard_parts import cap, res

PAGE = 2
POWER_NETS = mbp.POWER_NETS
INTERSHEET = mbp.INTERSHEET
SYMBOLS = mbp.SYMBOLS
footprints = mbp.footprints


def build(d):
    d.sheet("power", "power.kicad_sch", "Power: input breaker, VSYS, +3V3, +3V3_SLOT, +3V3A, monitors")

    d.group("U2: TPS259474L input circuit breaker, 3.33 A (2.96 / 3.33 / 3.62 A), OVLO 5.8 V, latch-off",
            "R_ILM 1.00k (I_LIM = 3334 / R). OVLO 383k / 100k: 5.80 V. EN/UVLO 100k / 39k: on above 4.28 V.\n"
            "dVdt 2.2n: 0.9 V/ms, +3V3 up in about 4 ms (U_CC wants <= 25 ms). ITIMER 2.2n: 1.85 ms blanking.\n"
            "Above I_LIM for longer, or at once above 2 x I_LIM, it turns off and stays off until VBUS is cycled.\n"
            "PG -> VSYS_PG: PGTH 100k / 44.2k on VSYS_IN (D4), falls at 3.51-3.64 V. The firmware keeps the board\n"
            "under 2.8 A.",
            anchor="U2")
    mbp.tps259474(d, "U2", "VBUS", "VSYS_IN", "U2_UVLO", "U2_OVLO", "VSYS_PG", "U2_PGTH", "U2_DVDT", "U2_ILM",
                  "U2_ITIMER")
    cap(d, "C30", "4.7u/25V", "VBUS", "GND", near="U2.5")
    res(d, "R30", "100k", "VBUS", "U2_UVLO")
    res(d, "R31", "39k", "U2_UVLO", "GND")
    res(d, "R32", "383k", "VBUS", "U2_OVLO")
    res(d, "R33", "100k", "U2_OVLO", "GND")
    res(d, "R34", "1k", "U2_ILM", "GND")
    cap(d, "C31", "2.2n", "U2_ITIMER", "GND")
    cap(d, "C32", "2.2n", "U2_DVDT", "GND")
    top, bot = nets.INPUT_PGTH_DIVIDER                     # the owner's 100 k / 44.2 k (D4 of 2026-11-27)
    res(d, "R35", {100e3: "100k"}[top], "VSYS_IN", "U2_PGTH")
    res(d, "R36", {44.2e3: "44.2k"}[bot], "U2_PGTH", "GND")
    res(d, "R37", "10k", "+3V3", "VSYS_PG")

    d.group("VSYS: 20 mR shunt, INA226 0x40 (U_PM40): the whole board, full scale 4.10 A, LSB 125 uA",
            "IN+ / IN- on PM40_SENSE_P / _N, Kelvin: net ties NT40P / NT40N at R38's pads (D4, SPEC §7.5).\n"
            "ALERT -> PM_ALERT_N at the VSYS budget (SPEC §3.2, §8.4).",
            anchor="U_PM40")
    res(d, "R38", "20m", "VSYS_IN", "VSYS")
    mbp.ina226(d, 0x40, "VSYS_IN", "VSYS", "VSYS")
    cap(d, "C33", "100n", "+3V3", "GND", near="U_PM40.6")
    cap(d, "C34", "22u/25V", "VSYS", "GND", near="U_PM40.9")
    cap(d, "C35", "10u/25V", "VSYS", "GND", near="U_PM40.9")
    mbp.testpoints(d, [("TP30", "VSYS_IN"), ("TP31", "VSYS")])

    d.group("U3: AP2112K-3.3, VSYS -> +3V3 (always on, 600 mA)",
            "Monitors, expanders, mux, U_CC, bus switches, LEDs and pull-ups. EN tied to VIN. 1u in, 10u out.",
            anchor="U3")
    d.add("U3", "Regulator_Linear:AP2112K-3.3", "AP2112K-3.3TRG1", mbp.FP["SOT23_5"], datasheet=mbp.DS["AP2112"],
          pins={"VIN": "VSYS", "EN": "VSYS", "GND": "GND", "VOUT": "+3V3", "NC": None},
          fields=dict(mbp.PART["AP2112K"]))
    cap(d, "C36", "1u", "VSYS", "GND", near="U3.1")
    cap(d, "C37", "10u", "+3V3", "GND", near="U3.5")
    mbp.testpoints(d, [("TP32", "+3V3")])

    d.group("+3V3_MCU: 0.5R shunt, INA226 0x41 (U_PM41): VDD and VBAT, full scale 164 mA, LSB 5 uA",
            "Inferred (SPEC §3.3): the HS PHY's internal 1.1 V part is drawn through here too.\n"
            "Kelvin: NT41P / NT41N at R39's pads (IN+ on +3V3, IN- on +3V3_MCU), its own ties.",
            anchor="U_PM41")
    res(d, "R39", "0.5", "+3V3", "+3V3_MCU", near="U_PM41.8")
    mbp.ina226(d, 0x41, "+3V3", "+3V3_MCU", "+3V3_MCU")
    cap(d, "C38", "100n", "+3V3", "GND", near="U_PM41.6")
    mbp.testpoints(d, [("TP33", "+3V3"), ("TP34", "+3V3_MCU")])

    d.group("+3V3_USB: 1R shunt, INA226 0x42 (U_PM42): VDDUSB only, full scale 82 mA, LSB 2.5 uA",
            "Kelvin: NT42P / NT42N at R40's pads (IN+ on +3V3, IN- on +3V3_USB), its own ties.",
            anchor="U_PM42")
    res(d, "R40", "1R", "+3V3", "+3V3_USB", near="U_PM42.8")
    mbp.ina226(d, 0x42, "+3V3", "+3V3_USB", "+3V3_USB")
    cap(d, "C39", "100n", "+3V3", "GND", near="U_PM42.6")
    mbp.testpoints(d, [("TP35", "+3V3"), ("TP36", "+3V3_USB")])

    d.group("U4: LDL1117S33R, VSYS -> +3V3_SLOT (1.2 A, 60 uVrms); FB1 to +3V3A is on the MCU sheet",
            "+3V3_SLOT feeds the five slot 3.3 V switches; the firmware keeps their sum under 300 mA (about 0.5 W in\n"
            "the SOT-223, SPEC §3.2). +3V3A: ratiometric with the slot rails. 1u in, 4.7u out (ST §6.2).",
            anchor="U4")
    d.add("U4", "keyboard:LDL1117S33R", "LDL1117S33R", mbp.FP["SOT223"], datasheet=mbp.DS["LDL1117"],
          pins={"3": "VSYS", "2": "+3V3_SLOT", "1": "GND"}, fields=dict(mbp.PART["LDL1117"]))
    cap(d, "C40", "1u", "VSYS", "GND", near="U4.3")
    cap(d, "C41", "4.7u", "+3V3_SLOT", "GND", near="U4.2")
    mbp.testpoints(d, [("TP37", "+3V3_SLOT"), ("TP38", "+3V3A")])

    d.group("Power flags", "VSYS, +3V3_MCU and +3V3_USB are driven through a shunt (a passive part).")
    mbp.power_flags(d, 3, ["VSYS", "+3V3_MCU", "+3V3_USB"])
