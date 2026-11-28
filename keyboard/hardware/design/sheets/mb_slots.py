"""Motherboard: the five coupon slots S1-S5 (SPEC §3.1, §3.3-§3.6, §4), one sheet per slot, drawn by slot_sheet(n).

Per slot (refs 100 n + 400 ... and the SPEC names):

* **J_Sn**, the female 2 x 20, 2.54 mm socket (owner's decision D2 of 2026-11-26; part a candidate: BOOMELE
  2.54-2*20P, C5124634, 8.5 mm, 2.5 A per contact), pin for pin nets.SLOT_PINS through nets.slot_pin_net(n, pin).
  Footprint KiCad PinSocket_2x20_P2.54mm_Vertical (1.0 mm drills; the socket's 0.64 x 0.40 tails fit, see
  boards/coupon_common.py). 1 uF on each switched rail at the socket (10 uF on +5V_S5).
* **The key, pin 39** (owner's decision D2 of 2026-11-27; SPEC §4.2): KEY, no net. The socket keeps pad 39,
  unconnected, and its hole is plugged by hand at assembly (a header pin cut flush and pressed into contact 39, not
  standing above the socket's top): JLC listed no key plug and no 2 x 20 socket without contact 39 on 2026-11-27,
  so the plug is an assembly note, not a part.
* **The slot guard** (owner's decision D3 of 2026-11-27; SPEC §4.3; nets.SLOT_SERIES): 100 Ohm 1 % 0402 (C25076,
  basic) in series at the socket on CS0_N, CS1_N, IRQ_N and G0-G3, and on S5's G4/G5: R<b+31> ... in that order
  (S1 R531-R537, S5 R931-R939). The socket pin carries S<n>_<signal>_J (nets.socket_net()); the MCU side keeps
  S<n>_<signal>. Each sits next to its socket pin (within about 10 mm of the pad, SPEC §9).
* **Lanes AN0-AN3**: 47 Ohm in series, then 1 nF C0G to GND on the MCU side (S<n>_AN<k>_ADC). The capacitor is drawn
  on this sheet and is placed at the MCU pin by layout (SPEC §4.3: "at the MCU pin"). A probe pad on the socket side.
* **U_BSn**, SN74CBTLV3125 (SPEC §4.3): SCK, MOSI, SYNC from the shared SLOT_* nets to the slot, MISO back; all four
  ~OE on BUSEN_N_Sn (U_EXP1) with a 10 k pull-up: open after a power-on (SPEC §3.5). VCC from the always-on +3V3.
* **+3V3_Sn**: TPS2553 (EN_3V3_Sn, 100 k pull-down: off after a power-on) from +3V3_SLOT, R_ILIM 90.9 k 1 %
  (256 / 292 / 335 mA, SPEC §3.1), then the 0.24 Ohm shunt of INA226 0x43+n, then the meter jumper JP_3V3_Sn (a
  1 x 2 header: **the slot gets no 3.3 V until a jumper shunt is fitted**, SPEC §3.3), then the socket. The INA226
  reads VBUS at the socket side (+3V3_Sn), so its 830 kOhm VBUS load is in the reading (SPEC §3.3).
* **+5V_Sn**, S1-S4: TPS2553 from VSYS, R_ILIM 45.3 k 1 % (519 / 577 / 644 mA), 0.1 Ohm shunt, INA226 0x48+n.
  **S5**: U5, the second TPS259474L circuit breaker (SPEC §3.6): R_ILM 1.47 k (I_LIM = 3334 / R = 2.27 A typ,
  SLVSFC9C Eq. 5), C_ITIMER 2.2 nF (t = 1.51 V x 2.2 nF / 1.8 uA = 1.85 ms typ blanking, Eq. 6; the motor's peak
  width is unknown, SPEC §3.5: a proposal), C_dVdt 2.2 nF (about 0.9 V/ms, Eq. 4: 470 uF of coupon bulk charges at
  about 0.43 A, *estimate*), OVLO tied to GND (its active-low enable: VSYS is already behind U2's OVLO), PGTH from a
  100 k / 39 k divider on its output (PG above 4.28 V rising, 1.20 V x 139 / 39) and PG on S5_PG with a 10 k
  pull-up to +3V3; the 20 mOhm shunt of INA226 0x4D. Kelvin pads TP908 / TP909 (SPEC's TP_IS5+ / TP_IS5-) across
  it (SPEC §3.6).
* **I2C channel**: 4.7 k pull-ups to the slot's own +3V3_Sn on S<n>_SCL / S<n>_SDA (SPEC §4.2), to the mux.
* **PRESENT_N**: to U_EXP2, its 100 k pull-up to +3V3 drawn there (SPEC §4.3). **G4/G5** (S1-S4): 100 k
  pull-downs, from U_EXP3.
* **INJ**: solder jumper JP_INJn from RIG_INJ, open by default (SPEC §4.7), and a probe pad.
* **LED_Sn**: red LED from +3V3 through 1 k, cathode to U_EXP3 (lit while the expander pin is low: SPEC §3.5).
* **Kelvin sense** (owner's decision D4 of 2026-11-27; SPEC §7.5): both INA226s read their shunts through sense
  pairs of their own (PM<aa>_SENSE_P / _N), joined at the shunt's pads by net ties NT<aa>P / NT<aa>N
  (motherboard_parts.ina226).
* Probe pads (SPEC §7.5): the four lanes, INJ, and Kelvin pairs across both shunts.
"""

import nets
from sheets import motherboard_parts as mbp
from sheets.motherboard_parts import cap, res

PAGE = 5
POWER_NETS = mbp.POWER_NETS
INTERSHEET = mbp.INTERSHEET
SYMBOLS = mbp.SYMBOLS
footprints = mbp.footprints


def socket_pins(n):
    """Slot n's socket pin -> net: nets.slot_pin_net(), the D3 series resistors' socket side included; the key pin
    (39) has no net."""
    return {str(pin): nets.slot_pin_net(n, pin) for pin, _sig, _d, _note in nets.SLOT_PINS}


def series_resistors(n):
    """[(ref, signal, socket pin, socket-side net, MCU-side net, ohms)] of slot n's D3 series resistors."""
    b = mbp.SLOT_BASE[n]
    pin_of = {sig: pin for pin, sig, _d, _note in nets.SLOT_PINS}
    return [(f"R{b + 31 + i}", sig, pin_of[sig], sock, nets.slot_net(n, sig), ohms)
            for i, (sig, (sock, ohms)) in enumerate(nets.SLOT_SERIES[n].items())]


def slot_sheet(d, n):
    b = mbp.SLOT_BASE[n]
    J, BS = f"J_S{n}", f"U_BS{n}"
    sw3, ina3 = f"U_3V3_S{n}", mbp.ina_ref(0x43 + n)
    sw5, ina5 = (f"U_5V_S{n}" if n < 5 else "U5"), mbp.ina_ref(0x48 + n)
    v3, v5 = f"+3V3_S{n}", f"+5V_S{n}"
    sh3_hi, sh3_lo, sh5_hi = f"S{n}_3V3_SW", f"S{n}_3V3_M", f"S{n}_5V_SW"
    trip3 = nets.SWITCH_TRIP[v3]
    trip5 = nets.SWITCH_TRIP[v5]
    d.sheet(f"slot{n}", f"slot{n}.kicad_sch", f"Slot S{n}: socket, rails, monitors, bus switch, lanes")

    # ---- socket, lanes, I2C channel, identity, INJ
    role = {1: "Hall-effect", 2: "TMR", 3: "shear", 4: "coil (G0-G3 on TIM8)",
            5: "haptics (G0-G5 on TIM1, AN1-AN3 on ADC4, 2 A 5 V rail)"}[n]
    d.group(f"J_S{n}: slot S{n} socket, female 2 x 20, 2.54 mm (default coupon: {role})",
            "Pinout = nets.SLOT_PINS (SPEC §4.2): odd pins one row, even pins the other.\n"
            "KEY (39): no net; plug hole 39 by hand at assembly (no key plug stocked, D2 of 2026-11-27).\n"
            f"D3: 100R in series at the socket on CS0_N, CS1_N, IRQ_N, G0-G{5 if n == 5 else 3}; "
            f"S{n}_<sig>_J at the pin.\n"
            "Lanes: 47R in series, 1n C0G on the MCU side (place the 1n at the MCU pin, SPEC §4.3).\n"
            "SCL/SDA: 4.7k to the slot's own +3V3 (never back-powers a coupon). PRESENT_N: 100k up at U_EXP2.\n"
            "Coupons are not hot-plugged while LED_S" + str(n) + " is lit (SPEC §3.5).", anchor=J)
    d.add(J, "Connector_Generic:Conn_02x20_Odd_Even", "SLOT", mbp.FP["SOCKET"], pins=socket_pins(n),
          datasheet="https://www.lcsc.com/datasheet/C5124634.pdf",
          description="Socket, female, 2 x 20, 2.54 mm, vertical, through hole, 8.5 mm, 2.5 A per contact",
          fields=dict(mbp.PART["SOCKET"]))
    cap(d, f"C{b + 8}", "1u", v3, "GND", near=f"{J}.7")
    cap(d, f"C{b + 9}", "10u/25V" if n == 5 else "1u", v5, "GND", near=f"{J}.1")
    for ref, _sig, _pin, sock, mcu, ohms in series_resistors(n):
        res(d, ref, {100: "100"}[ohms], sock, mcu)
    for k in range(4):
        res(d, f"R{b + 21 + k}", "47", f"S{n}_AN{k}", f"S{n}_AN{k}_ADC")
        cap(d, f"C{b + 21 + k}", "1n C0G", f"S{n}_AN{k}_ADC", "GND")
    res(d, f"R{b + 25}", "4.7k", v3, f"S{n}_SCL")
    res(d, f"R{b + 26}", "4.7k", v3, f"S{n}_SDA")
    if n < 5:
        res(d, f"R{b + 28}", "100k", f"S{n}_G4", "GND")
        res(d, f"R{b + 29}", "100k", f"S{n}_G5", "GND")
    d.add(f"JP_INJ{n}", "Jumper:SolderJumper_2_Open", "INJ", mbp.FP["SJ"], pins={"1": "RIG_INJ", "2": f"S{n}_INJ"},
          in_bom=False, description="Solder jumper, open: bridge to send the latency rig's stimulus to this slot")
    mbp.testpoints(d, [(f"TP{b + k + 1}", f"S{n}_AN{k}") for k in range(4)] + [(f"TP{b + 5}", f"S{n}_INJ")])

    d.group(f"U_BS{n}: SN74CBTLV3125 bus switch, shared SPI2 and the frame tick",
            f"~OE = BUSEN_N_S{n} from U_EXP1, 10k pull-up: open after a power-on (SPEC §3.5). Close it only once the\n"
            "slot's rails are up, open it before they go down. VCC = always-on +3V3; Ioff isolates an unpowered\n"
            "coupon.",
            anchor=BS)
    d.add(BS, "keyboard:SN74CBTLV3125PW", "SN74CBTLV3125PWR", mbp.FP["TSSOP14"], datasheet=mbp.DS["CBTLV3125"],
          pins={"2": "SLOT_SCK", "3": f"S{n}_SCK", "5": "SLOT_MOSI", "6": f"S{n}_MOSI",
                "9": "SLOT_SYNC", "8": f"S{n}_SYNC", "12": "SLOT_MISO", "11": f"S{n}_MISO",
                "1": f"BUSEN_N_S{n}", "4": f"BUSEN_N_S{n}", "10": f"BUSEN_N_S{n}", "13": f"BUSEN_N_S{n}",
                "14": "+3V3", "7": "GND"},
          fields=dict(mbp.PART["CBTLV3125"]))
    cap(d, f"C{b + 1}", "100n", "+3V3", "GND", near=f"{BS}.14")
    res(d, f"R{b + 2}", "10k", "+3V3", f"BUSEN_N_S{n}")

    # ---- +3V3_Sn
    d.group(f"+3V3_S{n}: TPS2553 {sw3}, 0.24R shunt, INA226 0x{0x43 + n:02X} ({ina3}), meter jumper JP_3V3_S{n}",
            f"R_ILIM 90.9k 1 %: trip {trip3[0] * 1e3:.0f} / {trip3[1] * 1e3:.0f} / {trip3[2] * 1e3:.0f} mA "
            "(SLVS841 Eq. 1, SPEC §3.1). EN 100k pull-down: off after a power-on.\n"
            "Full scale 341 mA, LSB 10.4 uA (SPEC §3.4). FAULT -> SLOT_FAULT_N (all TPS2553s wired-OR).\n"
            f"JP_3V3_S{n}: fit a jumper shunt to power the slot; remove it to put a meter in series (SPEC §3.3).\n"
            f"Kelvin (D4): IN+ / IN- through net ties {mbp.kelvin_ref(0x43 + n, 'P')} / "
            f"{mbp.kelvin_ref(0x43 + n, 'N')} at R{b + 6}'s pads (SPEC §7.5).",
            anchor=ina3)
    mbp.tps2553(d, sw3, "+3V3_SLOT", f"EN_3V3_S{n}", sh3_hi, f"S{n}_ILIM3")
    cap(d, f"C{b + 3}", "100n", "+3V3_SLOT", "GND", near=f"{sw3}.1")
    res(d, f"R{b + 4}", "90.9k", f"S{n}_ILIM3", "GND")
    res(d, f"R{b + 5}", "100k", f"EN_3V3_S{n}", "GND")
    res(d, f"R{b + 6}", "0.24", sh3_hi, sh3_lo)
    mbp.ina226(d, 0x43 + n, sh3_hi, sh3_lo, v3)                # Kelvin: NT<aa>P / N at R<b+6>'s pads
    cap(d, f"C{b + 7}", "100n", "+3V3", "GND", near=f"{ina3}.6")
    d.add(f"JP_3V3_S{n}", "Jumper:Jumper_2_Open", "METER", mbp.FP["HDR1x2"], pins={"1": sh3_lo, "2": v3},
          datasheet="https://www.lcsc.com/datasheet/C32713268.pdf",
          description="Meter jumper: 1 x 2 pin header, 2.54 mm; closed by a jumper shunt (fitted by hand)",
          fields=dict(mbp.PART["HDR1x2"]))
    mbp.testpoints(d, [(f"TP{b + 6}", sh3_hi), (f"TP{b + 7}", sh3_lo)])

    # ---- +5V_Sn
    if n < 5:
        d.group(f"+5V_S{n}: TPS2553 {sw5}, 0.1R shunt, INA226 0x{0x48 + n:02X} ({ina5})",
                f"R_ILIM 45.3k 1 %: trip {trip5[0] * 1e3:.0f} / {trip5[1] * 1e3:.0f} / {trip5[2] * 1e3:.0f} mA "
                "(SPEC §3.1). EN 100k pull-down. Full scale 819 mA, LSB 25 uA (SPEC §3.4).\n"
                f"Kelvin (D4): IN+ / IN- through net ties {mbp.kelvin_ref(0x48 + n, 'P')} / "
                f"{mbp.kelvin_ref(0x48 + n, 'N')} at R{b + 13}'s pads (SPEC §7.5).", anchor=ina5)
        mbp.tps2553(d, sw5, "VSYS", f"EN_5V_S{n}", sh5_hi, f"S{n}_ILIM5")
        cap(d, f"C{b + 10}", "100n", "VSYS", "GND", near=f"{sw5}.1")
        res(d, f"R{b + 11}", "45.3k", f"S{n}_ILIM5", "GND")
        res(d, f"R{b + 12}", "100k", f"EN_5V_S{n}", "GND")
        res(d, f"R{b + 13}", "0.1", sh5_hi, v5)
    else:
        d.group(f"+5V_S5: TPS259474L circuit breaker U5 (2.01 / 2.27 / 2.46 A), 20 mR shunt, INA226 0x4D ({ina5})",
                "R_ILM 1.47k: I_LIM = 3334 / R_ILM (SLVSFC9C Eq. 5). C_ITIMER 2.2n: 1.85 ms blanking (Eq. 6), then it\n"
                "latches off until EN_5V_S5 goes low. C_dVdt 2.2n: about 0.9 V/ms. OVLO = GND (enabled; VSYS is\n"
                "behind U2). PGTH 100k / 39k: PG above 4.28 V -> S5_PG. Full scale 4.10 A, LSB 125 uA (SPEC §3.4).\n"
                "Kelvin pads TP908 / TP909 (SPEC's TP_IS5+ / TP_IS5-) across the shunt for a scope (SPEC §3.6).\n"
                "Kelvin (D4): IN+ / IN- through net ties NT4DP / NT4DN at R913's pads (SPEC §7.5).",
                anchor=ina5)
        mbp.tps259474(d, sw5, "VSYS", sh5_hi, "EN_5V_S5", "GND", "S5_PG", "S5_PGTH", "S5_DVDT", "S5_ILM",
                      "S5_ITIMER")
        cap(d, f"C{b + 10}", "1u", "VSYS", "GND", near=f"{sw5}.5")
        res(d, f"R{b + 11}", "1.47k", "S5_ILM", "GND")
        res(d, f"R{b + 12}", "100k", "EN_5V_S5", "GND")
        res(d, f"R{b + 13}", "20m", sh5_hi, v5)
        cap(d, f"C{b + 16}", "2.2n", "S5_ITIMER", "GND")
        cap(d, f"C{b + 17}", "2.2n", "S5_DVDT", "GND")
        res(d, f"R{b + 18}", "100k", sh5_hi, "S5_PGTH")
        res(d, f"R{b + 19}", "39k", "S5_PGTH", "GND")
        res(d, f"R{b + 20}", "10k", "+3V3", "S5_PG")
    mbp.ina226(d, 0x48 + n, sh5_hi, v5, v5)
    cap(d, f"C{b + 14}", "100n", "+3V3", "GND", near=f"{ina5}.6")
    mbp.testpoints(d, [(f"TP{b + 8}", sh5_hi), (f"TP{b + 9}", v5)])

    d.group(f"LED_S{n}: slot powered", f"Lit while U_EXP3 drives LED_S{n} low (rails on). 1k from +3V3: about 1.3 mA.")
    res(d, f"R{b + 30}", "1k", "+3V3", f"S{n}_LED_A")
    mbp.led(d, f"D{b + 1}", f"S{n}_LED_A", f"LED_S{n}")

    d.group("Power flags", "The slot rails are driven through a shunt and a jumper (passive parts).")
    mbp.power_flags(d, 10 + 2 * n, [v3, v5])


def build(d):
    for n in nets.SLOTS:
        slot_sheet(d, n)
