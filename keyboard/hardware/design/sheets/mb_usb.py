"""Motherboard: USB-C input J1, its ESD protection and the Type-C detect chip U_CC (SPEC §3.5, §3.8, §7.1).

* **J1**, HRO TYPE-C-31-M-12 (C165948, the caliper's part): D+ on A6/B6 and D- on A7/B7 joined at the connector,
  SBU unused, VBUS on A4 (A9, B4, B9 stacked), shield SH to GND through 1 MOhm || 4.7 nF 1 kV (SPEC §7.1, proposal).
* **D1**, SMF5.0A on VBUS (cathode, pin 1, to VBUS), as the caliper.
* **U_ESD**, TPD4E05U06DQAR: D+ (1), D- (2), CC1 (4), CC2 (5), flow-through over the NC pins 10, 9, 7, 6, which
  carry the same nets (TI: "Used for optional straight-through routing"; stacked under 1, 2, 4, 5 in the symbol, a
  capture change the layout needed on 2026-11-28) (SPEC §7.1: "on CC, between J1 and U_CC"). Whether its clamp protects U_CC's 6 V CC pins is SPEC §11 #16, open.
* **U_CC**, TUSB320LAI (owner's decision D3: a detect chip on I2C; this part a candidate), pins = nets.TYPEC_PINS
  (SLLSEQ8D): PORT and EN_N to GND (sink, always on), ID open, ADDR 4.7 k to +3V3 (I2C at 0x67), VBUS_DET through
  887 k 1 % from VBUS (ahead of the breaker), INT_N with its 200 k pull-up to +3V3 into U_EXP2 P14 (USBC_INT_N),
  SDA/SCL on I2C1, VDD from +3V3 with 100 nF at the pin.
* **R1, R2**: the two 5.1 k Rd footprints on CC1/CC2, **not fitted** (DNP): fitted beside U_CC they would halve its
  termination and misread a 3.0 A source as 1.5 A (SPEC §3.5, §3.8). They exist for a board built without U_CC.
* Probe pads on CC1, CC2 and USBC_INT_N (SPEC §7.5, §10 step 5). None on the USB pair.
"""

from sheets import motherboard_parts as mbp
from sheets.motherboard_parts import cap, res

PAGE = 1
POWER_NETS = mbp.POWER_NETS
INTERSHEET = mbp.INTERSHEET
SYMBOLS = mbp.SYMBOLS
footprints = mbp.footprints


def build(d):
    d.sheet("usb", "usb.kicad_sch", "USB-C input, ESD, Type-C detect")

    d.group("J1: USB-C (USB 2.0 high-speed device, sink only) and ESD",
            "D+/D- joined at J1, then the 90R pair through U_ESD to the MCU (PA12/PA11): hand-routed on L1 over the\n"
            "L2 ground, no vias, no stubs, no test points (SPEC §7.1). VBUS: SMF5.0A TVS; <= 10 uF before U2.\n"
            "Shield: 1M || 4.7n 1 kV to GND (proposal).", anchor="J1")
    d.add("J1", "Connector:USB_C_Receptacle_USB2.0_16P", "TYPE-C-31-M-12", mbp.FP["USBC"],
          pins={"A4": "VBUS", "A1": "GND", "SH": "USB_SHIELD", "A5": "USB_CC1", "B5": "USB_CC2",
                "A6": "USB_DP", "B6": "USB_DP", "A7": "USB_DM", "B7": "USB_DM", "A8": None, "B8": None},
          fields=dict(mbp.PART["USBC"]))
    res(d, "R3", "1M", "USB_SHIELD", "GND")
    cap(d, "C3", "4.7n/1kV", "USB_SHIELD", "GND")
    d.add("D1", "Diode:SMF5V0A", "SMF5.0A", mbp.FP["SMF"], pins={"1": "VBUS", "2": "GND"}, rot=270,
          datasheet="https://www.littelfuse.com/assetdocs/tvs-diodes-smf-datasheet",
          description="200 W unidirectional TVS, 5.0 V VRWM, SOD-123FL (cathode = pin 1 to VBUS)",
          fields=dict(mbp.PART["SMF5.0A"]))
    d.add("U_ESD", "keyboard:TPD4E05U06DQA", "TPD4E05U06DQAR", mbp.FP["DQA"], datasheet=mbp.DS["TPD4E05U06"],
          pins={"1": "USB_DP", "2": "USB_DM", "4": "USB_CC1", "5": "USB_CC2", "3": "GND", "8": "GND",
                "10": "USB_DP", "9": "USB_DM", "7": "USB_CC1", "6": "USB_CC2"},
          fields=dict(mbp.PART["TPD4E05U06"]))

    d.group("U_CC: TUSB320LAI USB Type-C detect, I2C1 at 0x67 (owner's decision D3; the part a candidate)",
            "Rd on CC1/CC2 powered or not (dead-battery Rd 4.1-6.1k). PORT = GND: sink only. EN_N = GND: always on.\n"
            "ADDR 4.7k to +3V3: I2C at 0x67 (low would be 0x47, INA226 +3V3_S4's). VBUS_DET 887k 1 % from VBUS.\n"
            "INT_N: 200k to +3V3, into U_EXP2 P14 (no MCU pin). Reads Default / 1.5 A / 3.0 A: the firmware's\n"
            "VSYS budget (SPEC §3.2, §8.4). R1/R2 5.1k Rd: NOT FITTED (they would halve U_CC's termination).",
            anchor="U_CC")
    d.add("U_CC", "Interface_USB:TUSB320", "TUSB320LAIRWBR", mbp.FP["X2QFN12"], datasheet=mbp.DS["TUSB320LAI"],
          pins={"1": "USB_CC1", "2": "USB_CC2", "3": "GND", "4": "CC_VBUS_DET", "5": "CC_ADDR", "6": "USBC_INT_N",
                "7": "I2C_PM_SDA", "8": "I2C_PM_SCL", "9": None, "10": "GND", "11": "GND", "12": "+3V3"},
          fields=dict(mbp.PART["TUSB320LAI"]))
    cap(d, "C4", "100n", "+3V3", "GND", near="U_CC.12")
    res(d, "R4", "887k", "VBUS", "CC_VBUS_DET")
    res(d, "R5", "4.7k", "+3V3", "CC_ADDR")
    res(d, "R6", "200k", "+3V3", "USBC_INT_N")
    res(d, "R1", "5.1k", "USB_CC1", "GND", dnp=True)
    res(d, "R2", "5.1k", "USB_CC2", "GND", dnp=True)
    mbp.testpoints(d, [("TP1", "USB_CC1"), ("TP2", "USB_CC2"), ("TP3", "USBC_INT_N")])

    d.group("Power flags", "VBUS and GND come from the USB-C cable.")
    mbp.power_flags(d, 1, ["VBUS", "GND"])
