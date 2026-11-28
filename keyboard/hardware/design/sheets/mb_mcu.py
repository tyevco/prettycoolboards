"""Motherboard: the STM32U5A5VJT6 (SPEC §3.7, §5), its supply pins, HSE crystal, BOOT0, NRST and status LED.

* **U1**, STM32U5A5VJT6, LQFP100 (the owner's MCU; JLC C22455480, 13 in stock at $19.10 on 2026-11-27: SPEC §1's
  reservation gates ordering). KiCad 10.0.8's MCU_ST_STM32U5:STM32U5A5VJTx, every pin from nets.MCU_PINS through
  nets.KICAD_PIN_ALIAS (check_contract.py compares the netlist with the contract).
* **Supplies** (DS13543 Rev 2 Figure 23, SPEC §3.7): 100 nF at each of the five VDD pins plus 10 uF; VBAT tied to
  +3V3_MCU with 100 nF; VDDA and VREF+ on +3V3A, 100 nF + 1 uF each; VDDUSB on +3V3_USB, 100 nF + 1 uF; VCAP 4.7 uF
  X5R 16 V 0603 (ESR of a ceramic: milliohms, under the 20 mOhm asked; >= 10 V) and a probe pad.
* **HSE** (SPEC §5.2): 16 MHz crystal X322516MLB4SI (9 pF load, +/-10 ppm, ESR 50 Ohm max, C0 3 pF max: YXC sheet)
  with 10 pF C0G load capacitors: C_L = 10 / 2 + about 4 pF of stray ~ 9 pF (*estimate*). Oscillator margin per ST
  AN2867: gm_crit = 4 x ESR x (2 pi f)^2 x (C0 + C_L)^2 = 4 x 50 x (2 pi 16 MHz)^2 x (12 pF)^2 = 0.29 mA/V against
  the HSE's Gm_crit_max 1.5 mA/V (DS13543 Table 72): a margin of 5.2, at AN2867's minimum of 5 (*estimate* with the
  datasheet maxima). No series resistor (drive level not measured: bring-up item).
* **BOOT0** (PH3): 10 k pull-down and a button to +3V3_MCU (SPEC §5.2, §7.2). The ROM bootloader is entered from
  power-off: hold BOOT0, then plug in J1.
* **NRST**: 100 nF to GND, a reset button, J_SWD pin 12 (the pin's internal pull-up holds it high).
* **LED_N** (PC15, sink only): red LED from +3V3 through 1 k, about 1.4 mA (*estimate*), inside the 3 mA that
  PC13-PC15 may carry (SPEC §5.2). Its current stays off the +3V3_MCU shunt (SPEC §3.3).
* **SLOT_SCK, SLOT_MOSI**: their 100 k pull-downs (nets.MCU_SIDE_PULLS) are drawn on the headers sheet with the
  SPI2 probe pads; on the board they sit at PB13 / PB15.
* **FB1**, BLM18PG221SN1D (220 Ohm at 100 MHz): +3V3_SLOT -> +3V3A, the VDDA / VREF+ supply (SPEC §3.1), with
  the pins' 100 nF + 1 uF pairs as its filter capacitors. Placed next to VDDA.
* **The +3V3A damping leg** (owner's decision D4 of 2026-11-27; SPEC §3.7; nets.VDDA_DAMPING): R103 0.47 Ohm 1 %
  0603 (C23411) from +3V3A to VDDA_DAMP and C118 10 uF 25 V X5R 0805 (C15850) from VDDA_DAMP to GND, placed at FB1's
  +3V3A end. Picked with keyboard/sim's bench 4 (a model with the LDL1117's fitted output impedance): it removes the
  FB1 / VDDA-capacitor resonance (peaking at most +2.7 dB over FB1's 0.1-2 uH bracket, *estimate*) and keeps +3V3A's
  DC resistance at FB1's 0.1 Ohm. FB1 and C108-C111 stay.
* Probe pad: VCAP (SPEC §7.5); SPI2's are on the headers sheet.
"""

import nets
from sheets import motherboard_parts as mbp
from sheets.motherboard_parts import cap, res

PAGE = 3
POWER_NETS = mbp.POWER_NETS
INTERSHEET = mbp.INTERSHEET
SYMBOLS = mbp.SYMBOLS
footprints = mbp.footprints

VDD_PINS = (11, 28, 50, 75, 100)


def mcu_pins():
    """nets.MCU_PINS keyed by the KiCad symbol's pin names (nets.KICAD_PIN_ALIAS reversed)."""
    back = {v: k for k, v in nets.KICAD_PIN_ALIAS.items()}
    return {back.get(name, name): net for name, net in nets.MCU_PINS.items()}


def build(d):
    d.sheet("mcu", "mcu.kicad_sch", "MCU: STM32U5A5VJT6, supplies, HSE, BOOT0, NRST")
    u = mbp.MCU_REF
    d.group("U1: STM32U5A5VJT6 (LQFP100), pin map = nets.MCU_PINS (SPEC §5)",
            "OTG_HS on PA11/PA12 (the 90R pair, hand-routed, MCU rotated so pins 70/71 face J1: SPEC §7.1).\n"
            "No LSE: PC14 = S1_IRQ_N, PC15 = LED_N (sink only). PA15 / PB4 (JTDI / NJTRST) are SLOT_SYNC / RIG_MARK.\n"
            "Lanes: S<n>_AN<k>_ADC, the MCU side of each slot's 47R / 1n RC (the 1n sits at the pin, SPEC §4.3).\n"
            "PE15 = S5_IRQ_N is TIM1_BKIN: never gpio_pin_configure it (SPEC §5.3).", anchor=u)
    d.add(u, nets.KICAD_SYMBOL, nets.MCU, mbp.FP["LQFP100"], pins=mcu_pins(),
          datasheet="https://www.st.com/resource/en/datasheet/stm32u5a5vj.pdf", fields=dict(mbp.PART["MCU"]))

    d.group("Supply pins (DS13543 Figure 23)",
            "100n at every VDD pin + 10u; VBAT = +3V3_MCU with 100n (no backup cell). VDDA and VREF+ = +3V3A:\n"
            "+3V3_SLOT through FB1 (ratiometric with the slot rails, VREFBUF off), 100n + 1u each.\n"
            "VDDUSB = +3V3_USB, 100n + 1u.\n"
            "VCAP: 4.7u X5R (ESR < 20 mOhm at 3 MHz, >= 10 V), nothing else on it.")
    for i, pin in enumerate(VDD_PINS):
        cap(d, f"C{101 + i}", "100n", "+3V3_MCU", "GND", near=f"{u}.{pin}")
    cap(d, "C106", "10u", "+3V3_MCU", "GND", near=f"{u}.11")
    cap(d, "C107", "100n", "+3V3_MCU", "GND", near=f"{u}.6")
    d.add("FB1", "Device:FerriteBead_Small", "220R@100MHz", mbp.FP["FERRITE"], pins={"1": "+3V3_SLOT", "2": "+3V3A"},
          near=f"{u}.22", datasheet="https://www.murata.com/en-us/products/productdetail?partno=BLM18PG221SN1D",
          description="Ferrite bead 220 Ohm at 100 MHz, 1.4 A, 0603", fields=dict(mbp.PART["FERRITE"]))
    cap(d, "C108", "100n", "+3V3A", "GND", near=f"{u}.22")
    cap(d, "C109", "1u", "+3V3A", "GND", near=f"{u}.22")
    cap(d, "C110", "100n", "+3V3A", "GND", near=f"{u}.21")
    cap(d, "C111", "1u", "+3V3A", "GND", near=f"{u}.21")
    cap(d, "C112", "100n", "+3V3_USB", "GND", near=f"{u}.73")
    cap(d, "C113", "1u", "+3V3_USB", "GND", near=f"{u}.73")
    cap(d, "C114", "4.7u", "VCAP", "GND")
    mbp.testpoints(d, [("TP101", "VCAP")])

    leg, ohms, farads = nets.VDDA_DAMPING
    d.group("+3V3A damping leg: 0.47R + 10u to GND (owner's decision D4 of 2026-11-27, SPEC §3.7)",
            "Place at FB1's +3V3A end (SPEC §9). It damps the FB1 / VDDA-capacitor resonance (keyboard/sim bench 4:\n"
            "at most +2.7 dB over FB1's 0.1-2 uH, estimate) and leaves +3V3A's DC resistance at FB1's.")
    res(d, "R103", {0.47: "0.47"}[ohms], "+3V3A", leg)
    cap(d, "C118", {10e-6: "10u/25V"}[farads], leg, "GND")

    d.group("HSE: 16 MHz crystal (SPEC §5.2)",
            "X322516MLB4SI: 9 pF load, +/-10 ppm. 10p C0G each side (10 / 2 + ~4 pF stray). AN2867 margin 5.2\n"
            "(gm_crit 0.29 mA/V vs 1.5 mA/V, estimate). Keep the crystal and caps next to pins 12/13, GND guard.")
    d.add("Y101", "Device:Crystal_GND24", "16MHz", mbp.FP["XTAL"], pins={"1": "HSE_IN", "3": "HSE_OUT", "2": "GND"},
          datasheet="https://www.lcsc.com/datasheet/C13738.pdf",
          description="Crystal 16 MHz, 9 pF load, +/-10 ppm, ESR 50 Ohm max, 3.2 x 2.5 mm 4-pad",
          fields=dict(mbp.PART["XTAL"]))
    cap(d, "C115", "10p C0G", "HSE_IN", "GND")
    cap(d, "C116", "10p C0G", "HSE_OUT", "GND")

    d.group("BOOT0 and reset (SPEC §5.2, §7.2)",
            "BOOT0 (PH3): 10k pull-down; SW102 to +3V3_MCU. Enter the ROM bootloader from power-off (hold SW102, plug\n"
            "in J1): an MCU reset leaves the expanders and the mux as they were (SPEC §3.5).\n"
            "NRST: 100n, SW101 to GND, J_SWD pin 12.")
    res(d, "R101", "10k", "BOOT0", "GND")
    mbp.button(d, "SW102", "BOOT0", "+3V3_MCU", "BOOT0", "Tactile switch SPST-NO, SMD 3.9 x 2.9 mm: BOOT0")
    cap(d, "C117", "100n", "NRST", "GND")
    mbp.button(d, "SW101", "RESET", "NRST", "GND", "Tactile switch SPST-NO, SMD 3.9 x 2.9 mm: reset")

    d.group("Status LED (PC15 sinks it)", "From +3V3 (not +3V3_MCU, SPEC §3.3) through 1k: about 1.4 mA.")
    res(d, "R102", "1k", "+3V3", "LED_N_A")
    mbp.led(d, "D101", "LED_N_A", "LED_N")

    d.group("Power flags", "+3V3A is driven through FB1 (a passive part).")
    mbp.power_flags(d, 7, ["+3V3A"])
