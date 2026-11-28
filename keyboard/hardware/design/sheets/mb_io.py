"""Motherboard: the I/O expanders U_EXP1-U_EXP3, the slot I2C mux U_MUX and both buses' pull-ups (SPEC §3.4, §3.5,
§4.3, §4.5). Pin maps = nets.EXPANDERS; addresses = nets.EXPANDER_I2C and nets.I2C_SLOT_UPSTREAM.

* **U_EXP1-U_EXP3**, TCA9535PWR on I2C1 at 0x20 / 0x21 / 0x22 (A2-A0 = 000 / 001 / 010). No internal pull-ups and
  inputs after a power-on (SCPS201F), so each output's resting state is a resistor: EN_* 100 k pull-downs and
  BUSEN_N_* 10 k pull-ups on the slot sheets, S1-S4 G4/G5 100 k pull-downs on the slot sheets, MUX_RST_N 10 k up,
  KVM_RST_N 10 k down (the KVM coupon held in reset), the LEDs off (cathode to the pin). The unused U_EXP2 and
  U_EXP3 P15-P17 get 10 k to GND ("If port is unused, it must be tied to either VCC or GND through a resistor").
  Only U_EXP2's INT is used: EXP_INT_N (10 k to +3V3) on PC13; U_EXP1's and U_EXP3's INT are left open.
* **U_EXP2's inputs** with their pull-ups here: S1-S5_PRESENT_N and KVM_PRESENT_N (100 k, SPEC §4.3), SLOT_FAULT_N
  (every TPS2553 FAULT, 10 k), PM_ALERT_N (every INA226 ALERT, 10 k). VSYS_PG's and S5_PG's 10 k sit at their
  breakers, USBC_INT_N's 200 k at U_CC.
* **U_MUX**, TCA9548APWR at 0x70 (A2-A0 = 000) on I2C4: channels 0-4 = S1-S5 (4.7 k pull-ups on each slot sheet),
  5 = J_KVM (pull-ups on the KVM coupon), 6 and 7 to probe pads only (no pull-ups; channel 6 is U_CC's fallback
  home, SPEC §3.4). ~RESET = MUX_RST_N.
* **Pull-ups**: I2C1 (I2C_PM) and I2C4 (I2C_SLOT) 2.2 k to +3V3 (400 kHz; U_CC's 1.6 mA sink allows no stronger
  than about 1.8 k, SPEC §3.4). Probe pads on both buses and on the mux's channels 6 and 7 (SPEC §7.5).
"""

import nets
from sheets import motherboard_parts as mbp
from sheets.motherboard_parts import cap, res

PAGE = 4
POWER_NETS = mbp.POWER_NETS
INTERSHEET = mbp.INTERSHEET
SYMBOLS = mbp.SYMBOLS
footprints = mbp.footprints

EXP_ADDR = {v.split()[0]: k for k, v in nets.EXPANDER_I2C.items()}      # "U_EXP1" -> 0x20


def expander(d, ref, base):
    addr = EXP_ADDR[ref] - 0x20
    pins = {"A0": "+3V3" if addr & 1 else "GND", "A1": "+3V3" if addr & 2 else "GND",
            "A2": "+3V3" if addr & 4 else "GND", "SCL": "I2C_PM_SCL", "SDA": "I2C_PM_SDA",
            "VCC": "+3V3", "GND": "GND", "~{INT}": "EXP_INT_N" if ref == "U_EXP2" else None}
    spare = []
    for port, net in nets.EXPANDERS[ref].items():
        if net is None:
            net = f"{ref[2:]}_{port}"                 # EXP2_P15 ...: a 10k to GND (SCPS201F note 1)
            spare.append(net)
        pins[port] = net
    d.add(ref, "Interface_Expansion:TCA9535PWR", "TCA9535PWR", mbp.FP["TSSOP24"], pins=pins,
          datasheet=mbp.DS["TCA9535"], fields=dict(mbp.PART["TCA9535"]))
    cap(d, f"C{base}", "100n", "+3V3", "GND", near=f"{ref}.24")
    for i, net in enumerate(spare):
        res(d, f"R{base + 10 + i}", "10k", net, "GND")


def build(d):
    d.sheet("io", "io.kicad_sch", "I/O expanders, slot I2C mux, bus pull-ups")

    d.group("U_EXP1: TCA9535 at 0x20 (rail enables, bus-switch enables)",
            "Outputs only. EN_3V3_Sn / EN_5V_Sn / EN_5V_KVM: 100k pull-downs at the switches (rails off after a\n"
            "power-on); BUSEN_N_Sn: 10k pull-ups at the bus switches (open). The firmware declares every one\n"
            "GPIO_OUTPUT_INACTIVE, never a bare GPIO_OUTPUT (SPEC §8.4). INT not used.", anchor="U_EXP1")
    expander(d, "U_EXP1", 200)
    res(d, "R201", "2.2k", "+3V3", "I2C_PM_SCL")
    res(d, "R202", "2.2k", "+3V3", "I2C_PM_SDA")
    mbp.testpoints(d, [("TP201", "I2C_PM_SCL"), ("TP202", "I2C_PM_SDA")])

    d.group("U_EXP2: TCA9535 at 0x21 (PRESENT_N, faults, alerts, power-good, mux and KVM resets, U_CC interrupt)",
            "INT -> EXP_INT_N (10k to +3V3, PC13). SLOT_FAULT_N and PM_ALERT_N: wired-OR, 10k pull-ups here.\n"
            "PRESENT_N: 100k up. MUX_RST_N 10k up (mux running); KVM_RST_N 10k down (KVM coupon in reset).\n"
            "P15-P17 spare: 10k to GND.\n"
            "These states hold only after a power-on: an MCU reset leaves the outputs as they were (SPEC §3.5).",
            anchor="U_EXP2")
    expander(d, "U_EXP2", 210)
    res(d, "R203", "10k", "+3V3", "EXP_INT_N")
    res(d, "R204", "10k", "+3V3", "SLOT_FAULT_N")
    res(d, "R205", "10k", "+3V3", "PM_ALERT_N")
    res(d, "R206", "10k", "+3V3", "MUX_RST_N")
    res(d, "R207", "10k", "KVM_RST_N", "GND")
    res(d, "R208", "100k", "+3V3", "KVM_PRESENT_N")
    for n in nets.SLOTS:
        res(d, f"R{208 + n}", "100k", "+3V3", f"S{n}_PRESENT_N")

    d.group("U_EXP3: TCA9535 at 0x22 (S1-S4 G4/G5, slot LEDs)",
            "G4/G5: 100k pull-downs at the sockets (low into an unpowered slot). LED_Sn: the LED's cathode, lit when\n"
            "low. P15-P17 spare: 10k to GND. INT not used.", anchor="U_EXP3")
    expander(d, "U_EXP3", 220)

    d.group("U_MUX: TCA9548A at 0x70 on I2C4, one channel per slot (SPEC §4.5)",
            "ch0-ch4 = S1-S5 (4.7k pull-ups to each slot's +3V3 on its sheet), ch5 = J_KVM (pull-ups on the KVM\n"
            "coupon), ch6/ch7 = probe pads only. ~RESET = MUX_RST_N (10k up). Coupons must not use 0x70.\n"
            "Deselect a slot's channel before its rails go down (SPEC §3.5).", anchor="U_MUX")
    mux = {"A0": "GND", "A1": "GND", "A2": "GND", "~{RESET}": "MUX_RST_N", "SCL": "I2C_SLOT_SCL",
           "SDA": "I2C_SLOT_SDA", "VCC": "+3V3", "GND": "GND"}
    for ch in range(8):
        if ch < 5:
            sd, sc = f"S{ch + 1}_SDA", f"S{ch + 1}_SCL"
        elif ch == 5:
            sd, sc = "KVM_SDA", "KVM_SCL"
        else:
            sd, sc = f"MUX_SD{ch}", f"MUX_SC{ch}"
        mux[f"SD{ch}"], mux[f"SC{ch}"] = sd, sc
    d.add("U_MUX", "Interface_Expansion:TCA9548APWR", "TCA9548APWR", mbp.FP["TSSOP24"], pins=mux,
          datasheet=mbp.DS["TCA9548A"], fields=dict(mbp.PART["TCA9548A"]))
    cap(d, "C240", "100n", "+3V3", "GND", near="U_MUX.24")
    res(d, "R241", "2.2k", "+3V3", "I2C_SLOT_SCL")
    res(d, "R242", "2.2k", "+3V3", "I2C_SLOT_SDA")
    mbp.testpoints(d, [("TP241", "I2C_SLOT_SCL"), ("TP242", "I2C_SLOT_SDA"), ("TP243", "MUX_SC6"),
                       ("TP244", "MUX_SD6"), ("TP245", "MUX_SC7"), ("TP246", "MUX_SD7")])
