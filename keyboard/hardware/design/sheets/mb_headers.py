"""Motherboard: debug, latency-rig and KVM headers, mounting holes and fiducials (SPEC §7.2-§7.5, §9).

* **J_SWD**, STDC14 (Samtec FTSH-107-01-L-DV-K, C5307809, a candidate), pins = nets.J_SWD_PINS (ST UM2448 Rev 5
  Table 6): 3 T_VCC = +3V3_MCU (the probe's sense input), 4 SWDIO, 6 SWCLK, 8 SWO, 12 NRST, 13 T_VCP_RX = CON_RX
  (into PA10), 14 T_VCP_TX = CON_TX (from PA9), 5 / 7 / 11 GND; 1, 2, 9, 10 not connected. Its SMT land is KiCad's
  generic 2 x 7 1.27 mm SMD header, not checked against Samtec's drawing (motherboard_parts docstring).
* **J_RIG**, 2 x 5, 2.54 mm, a **shrouded box header** (owner's decision D5 of 2026-11-27: a plain header plugs either
  way round; BOOMELE 2.54-2*5P box header, C5665, footprint Connector_IDC:IDC-Header_2x05_P2.54mm_Vertical, checked
  against BOOMELE's drawing in motherboard_parts), pin 1 at the triangle, pins = nets.J_RIG_PINS: 33 Ohm in series on
  the three outputs (RIG_MARK, SLOT_SYNC, USB_SOF; nets.J_RIG_SERIES), RIG_TRIG straight to PB10 (TIM2_CH3), RIG_INJ
  to the five JP_INJn, RIG_VREF = +3V3 through 1 k (a logic reference, not a supply). Probe pads on the MCU side of
  RIG_MARK, SLOT_SYNC and USB_SOF, and on RIG_INJ (SPEC §7.5).
* **SPI2**: the 100 k pull-downs on SLOT_SCK and SLOT_MOSI (nets.MCU_SIDE_PULLS, AN2606 §4.3; placed at the MCU
  pins on the board) and the bus's three probe pads.
* **J_KVM**, 2 x 6, 2.54 mm, a **shrouded box header** (D5 of 2026-11-27; BOOMELE 2.54-2*6P box header, C9136,
  Connector_IDC:IDC-Header_2x06_P2.54mm_Vertical), pins = nets.J_KVM_PINS, and its 5 V switch U_5V_KVM
  (TPS2553 from VSYS, EN_5V_KVM from U_EXP1 with a 100 k pull-down, R_ILIM 45.3 k: 519 / 577 / 644 mA, FAULT on
  SLOT_FAULT_N). +5V_KVM is an output only (SPEC §7.4). The KVM coupon itself is not part of this release.
* **H1-H4**: M3, 4 mm in from the motherboard's corners, on 10 mm standoffs; **H5-H9**: the coupons' M3 x 11 mm nylon
  spacers, one per slot at slot-origin + (4.0, 56.0) (SPEC §9; boards/coupon_common.py). All unplated.
* **FID1-FID3**: top-side fiducials, as the caliper.
"""

import nets
from sheets import motherboard_parts as mbp
from sheets import parts as P
from sheets.motherboard_parts import cap, res

PAGE = 6
POWER_NETS = mbp.POWER_NETS
INTERSHEET = mbp.INTERSHEET
SYMBOLS = mbp.SYMBOLS
footprints = mbp.footprints


def build(d):
    d.sheet("headers", "headers.kicad_sch", "Headers: SWD, latency rig, KVM; mounting")

    d.group("J_SWD: STDC14 (STLINK-V3), pins = nets.J_SWD_PINS (UM2448 Rev 5 Table 6)",
            "T_VCC (3) senses +3V3_MCU. VCP: 13 = the probe's TX into USART1_RX (PA10), 14 = USART1_TX (PA9).\n"
            "11 GNDDetect to GND. 1, 2 reserved ('do not connect on target'), 9 and 10 (JTAG only) open.",
            anchor="J_SWD")
    d.add("J_SWD", "Connector:Conn_ST_STDC14", "STDC14", mbp.FP["STDC14"],
          pins={str(p): net for p, net in nets.J_SWD_PINS.items()},
          datasheet="https://www.st.com/resource/en/user_manual/um2448-stlinkv3set-debuggerprogrammer-for-stm8-"
                    "and-stm32-stmicroelectronics.pdf",
          description="STDC14 debug connector, 2 x 7, 1.27 mm, SMD, keyed", fields=dict(mbp.PART["STDC14"]))

    d.group("J_RIG: latency rig, shrouded 2 x 5 box header, 2.54 mm (SPEC §7.3, D5), pins = nets.J_RIG_PINS",
            "33R in series on the outputs (RIG_MARK, SLOT_SYNC, USB_SOF) for the ribbon (up to about 150 mm).\n"
            "RIG_TRIG -> PB10 (TIM2_CH3 input capture). RIG_INJ -> JP_INJ1-5 (open by default, one slot at a time).\n"
            "RIG_VREF: +3V3 through 1k, a logic-level reference for the rig's buffers, not a supply.", anchor="J_RIG")
    pins = {}
    for p, net in nets.J_RIG_PINS.items():
        pins[str(p)] = nets.j_rig_pin_net(p)
    d.add("J_RIG", "Connector_Generic:Conn_02x05_Odd_Even", "RIG", mbp.FP["HDR2x5"], pins=pins,
          datasheet="https://www.lcsc.com/datasheet/C5665.pdf",
          description="Box header (shrouded, keyed), male, 2 x 5, 2.54 mm, vertical, through hole",
          fields=dict(mbp.PART["HDR2x5"]))
    for i, (net, (j_net, ohms)) in enumerate(nets.J_RIG_SERIES.items()):
        res(d, f"R{301 + i}", {33: "33"}[ohms], net, j_net)
    rail, ohms = nets.RIG_VREF
    res(d, "R304", {1000: "1k"}[ohms], rail, "RIG_VREF")
    mbp.testpoints(d, [("TP301", "RIG_MARK"), ("TP302", "SLOT_SYNC"), ("TP303", "USB_SOF"), ("TP304", "RIG_INJ")])

    d.group("SPI2: pull-downs and probe pads (SPEC §4.3, §5.2, §7.5)",
            "100k to GND on SLOT_SCK and SLOT_MOSI (nets.MCU_SIDE_PULLS; place them at PB13 / PB15): the ROM\n"
            "bootloader's SPI2 probe (AN2606 §4.3) sees a known level while every bus switch is open. About 33 uA\n"
            "each while driven high. Probe pads on the shared bus, the MCU side of the five bus switches.")
    for i, (net, (to, ohms)) in enumerate(sorted(nets.MCU_SIDE_PULLS.items())):
        res(d, f"R{305 + i}", {100e3: "100k"}[ohms], net, to)
    mbp.testpoints(d, [("TP305", "SLOT_SCK"), ("TP306", "SLOT_MISO"), ("TP307", "SLOT_MOSI")])

    d.group("J_KVM: optional KVM coupon, shrouded 2 x 6 box header, 2.54 mm (SPEC §7.4, D5), pins = nets.J_KVM_PINS",
            "+5V_KVM from U_5V_KVM (TPS2553, EN_5V_KVM from U_EXP1 P17, 100k pull-down; R_ILIM 45.3k: 519 / 577 /\n"
            "644 mA), an output only. UART4 to the MCU, I2C on mux ch5, KVM_RST_N / KVM_PRESENT_N on U_EXP2.\n"
            "The KVM coupon is not part of this release.", anchor="U_5V_KVM")
    d.add("J_KVM", "Connector_Generic:Conn_02x06_Odd_Even", "KVM", mbp.FP["HDR2x6"],
          pins={str(p): net for p, net in nets.J_KVM_PINS.items()},
          datasheet="https://www.lcsc.com/datasheet/C9136.pdf",
          description="Box header (shrouded, keyed), male, 2 x 6, 2.54 mm, vertical, through hole",
          fields=dict(mbp.PART["HDR2x6"]))
    mbp.tps2553(d, "U_5V_KVM", "VSYS", "EN_5V_KVM", "+5V_KVM", "KVM_ILIM")
    cap(d, "C310", "100n", "VSYS", "GND", near="U_5V_KVM.1")
    res(d, "R310", "45.3k", "KVM_ILIM", "GND")
    res(d, "R311", "100k", "EN_5V_KVM", "GND")
    cap(d, "C311", "1u", "+5V_KVM", "GND", near="J_KVM.1")

    d.group("Mounting holes and fiducials (SPEC §9)",
            "H1-H4: M3, 4 mm in from the corners (10 mm standoffs). H5-H9: one M3 x 11 mm nylon coupon spacer per\n"
            "slot, at slot-origin + (4.0, 56.0). All unplated. FID1-FID3: top-side fiducials.")
    for i in range(1, 10):
        P.mounting_hole(d, f"H{i}", "M3")
    P.fiducials(d, ("FID1", "FID2", "FID3"))
