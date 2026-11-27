"""Test coupon: the calibration and loopback coupon of SPEC §10 step 7 ("resistive loads on each rail, fixed dividers
on the lanes, a descriptor EEPROM, an SPI loopback, PRESENT_N. It checks every slot and the monitors' accuracy before
any sensor does, and calibrates each slot's series resistance (§3.1)").

SPEC gives the test coupon those five lines only; the circuit below is this capture's design of them (a proposal,
not an owner decision). It fits any slot (S1-S5), standard size (58 x 60 mm), and carries no sensor.

**Loads (sheet "loads").** Four N-MOSFET (AO3400A) switched loads, each gate on a G-line with a 100 k pull-down, so an
undriven G-line leaves the load off. All loads are strings of one part, 10 Ohm 1 % 1 W 2512 (UNI-ROYAL
25121WF100JT4E, C47019), to spread the heat and keep one BOM line:

| G-line | Rail | Load | Current (at 3.30 / 5.00 V, *estimate*) | What it is for |
|---|---|---|---|---|
| G0 | +3V3 | 3 x 10 Ohm in series = 30 Ohm | 110 mA (113 mA at 3.37 V with 1 % parts), 0.12 W per resistor | a calibration step for the slot's 3.3 V INA226 (0.24 Ohm shunt, 341 mA full scale) and, with the lanes, the slot's series resistance. Under the TPS2553's 256 mA minimum trip (SPEC §3.1): it never limits |
| G1 | +3V3 | 2 x 10 Ohm in parallel = 5 Ohm | would be 660 mA: twice the TPS2553's 335 mA maximum trip, so the switch limits it (256 / 292 / 335 mA, SPEC §3.1) | the current-limit test: the INA226 reads the limit, SLOT_FAULT_N asserts. While limited, 0.17-0.28 W per resistor |
| G2 | +5V | 3 x 10 Ohm in series = 30 Ohm | 167 mA (185 mA at USB-C's 5.5 V maximum), 0.28 W per resistor | a calibration step for the slot's 5 V INA226 (0.1 Ohm, 819 mA full scale; S5: 0.02 Ohm, 4.1 A). Under the S1-S4 switches' 519 mA and S5's 2.01 A minimum trips: it never limits |
| G3 | +5V | 3 x 10 Ohm in parallel = 3.33 Ohm | would be 1.5 A: above the S1-S4 TPS2553's 644 mA maximum trip, so it limits (519 / 577 / 644 mA) | the 5 V current-limit test on S1-S4. While limited, 0.30-0.46 W per resistor. **Not on S5**: S5's breaker trips at 2.01-2.46 A, so G3 would draw the full 1.5 A, 2.5 W per 1 W resistor (the silk next to the load says so); S5's breaker is tested with an external load on the wire pads TP2 / TP3 (the +5V copper from J1 to TP2 is sized for it, boards/test_coupon.py) |

The current-limit loads deliberately exceed the coupon rules (250 mA on +3V3, 500 mA on +5V, SPEC §4.9): exercising
the slot switch is the test. The firmware runs them one at a time, briefly, and turns the rail off when
SLOT_FAULT_N asserts; while the TPS2553 limits, it dissipates (V_in - I_lim x R) x I_lim, about 0.5 W (G1) and
1.8 W (G3) at the typical trip, so it may cycle through its thermal shutdown (*estimate*). The 2512's 400 ppm/K
makes the loads current steps, not current references: the INA226 and an external meter (on the slot's meter jumper,
SPEC §3.3) measure the current. The G1 test also draws up to 335 mA from the slot LDO, whose budget is 300 mA for all
slots together (SPEC §3.2): other slots' 3.3 V rails stay off during it.

**Lanes (sheet "lanes").** One ladder of five 499 Ohm 0.1 % 25 ppm/K thin-film resistors (Viking Tech AR03BTCX4990,
C2889161) from the coupon's +3V3 to GND: AN0, AN1, AN2, AN3 = 0.2, 0.4, 0.6, 0.8 x V(+3V3 at the coupon),
ratiometric with the slot rail as SPEC §3.1 intends (VDDA and VREF+ come from the same slot LDO). Every lane a
different ratio, so a swapped or open lane shows. Source impedance R_src (Thevenin): 399 Ohm (AN0, AN3) and 599 Ohm
(AN1, AN2), inside the 1 kOhm that SPEC §4.9 / §6.2 give for ADC1/ADC2 at 14 bits (DS13543 Table 97; ADC4 takes
2.2 kOhm) and declared in the descriptor. They are still not stiff sources: each sample's 5 pF kickback on the lane's
1 nF recovers through R_src + 47 Ohm (tau 0.45-0.65 us), so the firmware reads them with a long sampling time
(SPEC §6.3). 1.32 mA. With a load on, the drop I x R_series between the slot LDO and the coupon lowers the coupon's
+3V3; the four taps measure it (and any shift of the coupon's ground, which moves the low taps more than the high
ones), and the firmware divides the change by the INA226's current step to get the slot's series resistance
(SPEC §3.1, §10 step 7).

**Loopback (sheet "loopback").** An SN74LV165A parallel-in shift register on the slot's SPI with a tri-state MISO
driver (SN74LVC1G125), both with I_off (partial power-down: no back-powering through their inputs when the slot rail
is off, TI datasheets):

* the parallel inputs read G0 (H, first out), G1, G2, G3, G4, G5, INJ and SYNC (A, last);
* CS1_N is the parallel load strobe (SH/LD low: load), CS0_N the clock inhibit and the MISO enable, SCK the clock,
  MOSI the serial input: after the eight sampled bits, MISO returns MOSI's bits eight clocks late;
* MISO is driven only while CS0_N is low and is high-impedance otherwise (SPEC §4.9: SPI2 is shared by the slots).
* **No floating inputs** (SCLS402R note 1: "All unused inputs of the device must be held at VCC or GND"): CS0_N and
  CS1_N have 100 k pull-ups to the coupon's +3V3, so an undriven chip select (an MCU pin still in its reset state
  after an NRST with the slot rails left on, SPEC §3.5) keeps MISO high-impedance and the register idle; SCK, MOSI
  and SYNC have 100 k pull-downs, because the slot's bus switch leaves them open while the coupon is already powered
  (SPEC §3.5: the switch closes only after the rails are up).

Firmware sequence (a proposal): CS1_N low then high (sample), CS0_N low, clock 16 bits, CS0_N high. Bits 15-8 = G0..G5,
INJ, SYNC; bits 7-0 = the first byte sent on MOSI. The '165 shifts on SCK's rising edge and G0 is on MISO before the
first edge, so the master samples on the rising edge: SPI mode 3 (CPOL 1, CPHA 1) or mode 0. Prefer mode 3: with
mode 0, CS0_N rising while SCK is low is itself a shift ("CLK INH must be changed to the high level only while CLK is
high", SCLS402R §8.1), harmless here only because every read starts with a load. The master's hold time on MISO
rests on the '165's and the '125's minimum propagation delays (1 ns each in the datasheets) plus the round trip
through the bus switch: check the read at the chosen SCK at bring-up (**unverified**). A dead CS1_N shows as a sample
that never changes.

**Reading the G-lines back switches the loads on.** G0-G3 drive the load gates, so a G-line loopback with G1 or G3
high runs a current-limit load. Read G3 with the slot's +5V off (its load then has no supply); read G1 in a pulse of
a few microseconds (G1 high, CS1_N strobe, G1 low: the coupon's 10 uF holds +3V3, about 66 mV per microsecond at
660 mA, *estimate*), or skip it, since G1's own load test shows the line works.

**IRQ_N** is open drain with its 10 k pull-up on the coupon (SPEC §4.9), pulled low by an N-MOSFET from G5 (a
firmware-driven interrupt test) and one from INJ (100 k pull-down): with the slot's JP_INJ closed, the latency rig's
stimulus reaches the MCU's EXTI through the coupon, a sensor-free path to calibrate the rig (SPEC §7.3).
**Status LED** D10 on G4 (through an N-MOSFET, from the coupon's +3V3: its 1.5 mA, *estimate*, is on the slot's
monitor, not the motherboard's).

Idle draw on +3V3 about 1.4 mA (the ladder's 1.32 mA, the logic's quiescent current; *estimate*), +1.5 mA with the
LED on, +0.33 mA while IRQ_N is low, +33 uA for each chip select held low (R35, R36). The pull-downs on SCK, MOSI
and SYNC load the MCU's drivers (33 uA each while high), not the coupon's rail.
"""

from sheets import coupon_common as cc
from sheets.parts import R0603, cap, led_red, nfet, res, testpoints

POWER_NETS = cc.POWER_NETS
INTERSHEET = cc.INTERSHEET
REV = "A"
DATE = "2026-11-27"

SR = {"MPN": "SN74LV165APWR", "Manufacturer": "Texas Instruments", "LCSC": "C201716"}       # 6957, $0.335
BUF = {"MPN": "SN74LVC1G125DBVR", "Manufacturer": "Texas Instruments", "LCSC": "C23654"}    # 181834, $0.068
SR_DS = "https://www.ti.com/lit/ds/symlink/sn74lv165a.pdf"       # SCLS402R: pinout Figure 5-1, PW package
BUF_DS = "https://www.ti.com/lit/ds/symlink/sn74lvc1g125.pdf"    # SCES223U: DBV 1 OE, 2 A, 3 GND, 4 Y, 5 VCC
# Lane ladder: Viking Tech AR03BTCX4990 = AR03 (0603, 1.55 x 0.80 mm), B 0.1 %, T reel, C 25 ppm/K, X 1/10 W, 499 Ohm
# (Viking AR series datasheet, part numbering). JLC parts API 2026-11-27: 32,200 in stock, $0.0376, extended.
LADDER = {"MPN": "AR03BTCX4990", "Manufacturer": "Viking Tech", "LCSC": "C2889161"}
LADDER_R = 499.0

# The facts the coupon's descriptor will carry once compiler v0 defines its format (SPEC §4.6, §11 #18).
DESCRIPTOR_FACTS = {
    "type": "test", "rev": REV,
    "rails": {"+3V3": "1.4 mA idle (estimate); loads switched by G0/G1", "+5V": "loads switched by G2/G3 only"},
    # (x V(+3V3 at the coupon), R_src ohm): a 5 x 499 ohm ladder, R_src = k (5 - k) / 5 x 499
    "lanes": {f"AN{k - 1}": (k / 5, round(k * (5 - k) / 5 * LADDER_R)) for k in range(1, 5)},
    "g_lines": {"G0": "+3V3 load 30 ohm", "G1": "+3V3 current-limit load 5 ohm", "G2": "+5V load 30 ohm",
                "G3": "+5V current-limit load 3.33 ohm (S1-S4 only; never driven on S5)", "G4": "status LED",
                "G5": "pulls IRQ_N low"},
    "s5_forbidden": ["G3"],
    "spi": "CS1_N = load, CS0_N = select: 8 bits G0..G5, INJ, SYNC, then MOSI delayed by 8 (mode 3, or mode 0)",
    "loopback_loads": "reading G1/G3 back runs their current-limit loads: G3 with +5V off, G1 in a short pulse",
    "irq": "IRQ_N low while G5 or INJ is high",
}


def _load(d, n, gate, rail, n_res, series, first_ref, note):
    """An AO3400A switched load: n_res x 10 Ohm 2512 in series (a chain) or in parallel, from rail to the drain."""
    q, rpd = f"Q{10 + n}", f"R{10 + n}"
    drain = f"LOAD{n}_D"
    title, _, detail = note.partition("\n")
    d.group(f"{gate}: {title}", detail, anchor=q)
    nfet(d, q, gate, drain)
    res(d, rpd, "100k", gate, "GND")
    refs = [f"R{first_ref + k}" for k in range(n_res)]
    if series:
        nodes = [rail] + [f"LOAD{n}_{chr(65 + k)}" for k in range(n_res - 1)] + [drain]
        for k, ref in enumerate(refs):
            res(d, ref, "10R 2512", nodes[k], nodes[k + 1])
    else:
        for ref in refs:
            res(d, ref, "10R 2512", rail, drain)
    return first_ref + n_res


def loads_sheet(d):
    d.sheet("loads", "loads.kicad_sch", "Calibration and current-limit loads")
    r = 14
    r = _load(d, 0, "G0", "+3V3", 3, True, r,
              "+3V3 calibration load, 3 x 10R in series = 30R (110 mA at 3.30 V)\n"
              "0.12 W per resistor. A current step for the slot's 3.3 V INA226 and the series-resistance calibration.")
    r = _load(d, 1, "G1", "+3V3", 2, False, r,
              "+3V3 current-limit test, 2 x 10R in parallel = 5R (660 mA if unlimited)\n"
              "Above the TPS2553's 335 mA maximum trip: the switch limits, the INA226 reads the limit. Short test only.")
    r = _load(d, 2, "G2", "+5V", 3, True, r,
              "+5V calibration load, 3 x 10R in series = 30R (167 mA at 5.00 V)\n"
              "0.28 W per resistor. A current step for the slot's 5 V INA226.")
    _load(d, 3, "G3", "+5V", 3, False, r,
          "+5V current-limit test, 3 x 10R in parallel = 3.33R (1.5 A if unlimited)\n"
          "S1-S4 only: above the TPS2553's 644 mA maximum trip. On S5 (2 A breaker) it is NOT limited: never drive G3 "
          "there.")


def loopback_sheet(d):
    d.sheet("loopback", "loopback.kicad_sch", "SPI, G-line, SYNC and INJ loopback; IRQ_N; status LED")
    d.group("U10 SN74LV165A: samples G0-G5, INJ, SYNC; MOSI loops through SER",
            "CS1_N = SH/LD (low: load), CS0_N = CLK INH (shift only while selected), SCK = CLK, MOSI = SER.\n"
            "H (first bit out) = G0 ... C = G5, B = INJ, A = SYNC. I_off: no back-powering when +3V3 is off.\n"
            "No floating inputs: 100k pull-ups on CS0_N / CS1_N (MISO off while undriven), 100k pull-downs on\n"
            "SCK / MOSI / SYNC (open while the slot's bus switch is open). SPI mode 3 (or 0), see the module.",
            anchor="U10")
    d.add("U10", "74xx:74HC165", "SN74LV165APWR", "Package_SO:TSSOP-16_4.4x5mm_P0.65mm", datasheet=SR_DS,
          pins={"~{PL}": "CS1_N", "CP": "SCK", "~{CE}": "CS0_N", "DS": "MOSI",
                "D7": "G0", "D6": "G1", "D5": "G2", "D4": "G3", "D3": "G4", "D2": "G5", "D1": "INJ", "D0": "SYNC",
                "Q7": "SR_QH", "~{Q7}": None, "VCC": "+3V3", "GND": "GND"},
          description="8-bit parallel-in serial-out shift register, 2-5.5 V, Ioff, TSSOP-16", fields=dict(SR))
    cap(d, "C10", "100n", "+3V3", "GND", near="U10.16")
    res(d, "R35", "100k", "+3V3", "CS0_N", near="U10.15")
    res(d, "R36", "100k", "+3V3", "CS1_N", near="U10.1")
    res(d, "R37", "100k", "SCK", "GND", near="U10.2")
    res(d, "R38", "100k", "MOSI", "GND", near="U10.10")
    res(d, "R39", "100k", "SYNC", "GND", near="U10.11")
    d.add("U11", "74xGxx:74LVC1G125", "SN74LVC1G125DBVR", "Package_TO_SOT_SMD:SOT-23-5", datasheet=BUF_DS,
          pins={"1": "CS0_N", "2": "SR_QH", "4": "MISO", "VCC": "+3V3", "GND": "GND"},
          description="Single bus buffer, 3-state (OE low = enabled), Ioff, SOT-23-5", fields=dict(BUF))
    cap(d, "C11", "100n", "+3V3", "GND", near="U11.5")

    d.group("IRQ_N: open drain, 10k pull-up on the coupon (SPEC §4.9); low while G5 or INJ is high",
            "Q15 from INJ: with the slot's JP_INJ closed the latency rig's stimulus reaches the MCU's EXTI.\n"
            "100k pull-downs keep both gates off while G5 / INJ float (JP_INJ is open by default).", anchor="Q14")
    res(d, "R25", "10k", "+3V3", "IRQ_N")
    nfet(d, "Q14", "G5", "IRQ_N")
    res(d, "R26", "100k", "G5", "GND")
    nfet(d, "Q15", "INJ", "IRQ_N")
    res(d, "R27", "100k", "INJ", "GND")

    d.group("Status LED D10 on G4", "From the coupon's +3V3 through 1k (about 1.5 mA, estimate), switched by Q16.",
            anchor="Q16")
    nfet(d, "Q16", "G4", "LED_K")
    res(d, "R29", "100k", "G4", "GND")
    res(d, "R28", "1k", "+3V3", "LED_A")
    led_red(d, "D10", "LED_A", "LED_K")


def _ladder(d, ref, a, b):
    """One 499 Ohm 0.1 % 25 ppm/K 0603 thin-film resistor of the lane ladder, pin 1 = the higher tap."""
    return d.add(ref, "Device:R", "499", R0603, pins={"1": a, "2": b}, fields=dict(LADDER),
                 description="Thin-film resistor, 499 Ohm, 0.1 %, 25 ppm/K, 1/10 W, 0603 (lane ladder)")


def lanes_sheet(d):
    d.sheet("lanes", "lanes.kicad_sch", "Ratiometric lane references and test pads")
    d.group("Lane ladder: 5 x 499R 0.1 % from +3V3; AN0..AN3 = 0.2 / 0.4 / 0.6 / 0.8 x +3V3",
            "Ratiometric with the slot LDO (VDDA, VREF+). R_src 399R (AN0, AN3), 599R (AN1, AN2): inside the\n"
            "1k of SPEC §4.9 / §6.2. 1.32 mA. Under a load the coupon's +3V3 drops: the slot's series resistance.")
    _ladder(d, "R30", "AN0", "GND")
    _ladder(d, "R31", "AN1", "AN0")
    _ladder(d, "R32", "AN2", "AN1")
    _ladder(d, "R33", "AN3", "AN2")
    _ladder(d, "R34", "+3V3", "AN3")

    d.group("Test pads", "Lanes, frame tick, rig stimulus, interrupt and the SPI loopback, for a scope or logic analyser.")
    testpoints(d, 10, ["AN0", "AN1", "AN2", "AN3", "SYNC", "INJ", "IRQ_N", "SCK", "MISO", "MOSI", "CS0_N", "CS1_N"])


def build(d):
    cc.slot_sheet(d)
    loads_sheet(d)
    loopback_sheet(d)
    lanes_sheet(d)
