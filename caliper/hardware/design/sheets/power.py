"""Slider board: USB-C input + ESD, BQ25180 charger / power path, LiPo connector, TPS63802 buck-boost -> +3V3,
MAX17048 fuel gauge, the two TPS22917 rail switches (+3V3_SNS, +3V3_UI), I2C pull-ups, mounting holes and
fiducials. See SPEC.md §3 and §6.

Pinouts were checked against the primary datasheets:
  * BQ25180YBGR (TI SLUSE99C, Fig. 6-1 / Table 6-1, YBG0008 land pattern pp. 52-54): A1 /INT, A2 IN, B1 SCL,
    B2 SYS, C1 SDA, C2 BAT, D1 TS/MR, D2 GND. Symbol and footprint are dial-me-spinner's (base.py), which were
    checked against the same pages. "For devices where the TS function is not needed, tie a 10-kΩ resistor to
    the TS pin" (SLUSE99C §8.3.6): here a 10k NTC reads the board temperature next to the battery connector.
  * TPS63802DLAR (TI SLVSEU9D, Table 7-1, DLA0010A VSON-HR): 1 EN, 2 MODE, 3 AGND, 4 FB, 5 PG, 6 VOUT, 7 L2,
    8 GND, 9 L1, 10 VIN. Land pattern from the DLA0010A "Example board layout" (p. 36): pads 1-5 0.6 x 0.25 at
    x = -0.9; pads 6, 7, 9, 10 0.9 x 0.25 at x = +0.75; pad 8 (GND) 1.3 x 0.25 centred at x = +0.55; 0.5 mm pitch.
    Typical application (Fig. 10-1): L = 0.47 uH, CIN 10 uF, COUT 22 uF, R1 511k / R2 91k for 3.3 V (VFB 500 mV,
    R2 <= 100k, Table 10-5).
  * MAX17048G+T10 (Maxim 19-6171, Pin/Bump Descriptions, TDFN 2x2): 1 CTG (GND), 2 CELL, 3 VDD (also the sense
    input on the MAX17048), 4 GND, 5 ALRT (open drain), 6 QSTRT (GND if unused), 7 SCL, 8 SDA, EP to GND.
    Fig. 14 application circuit: 0.1 uF on VDD. SCL/SDA have internal pull-downs (bus-disconnect detection), so
    the I2C pull-ups must stay on the always-on +3V3.
  * TPS22917DBVR (TI SLVSDW8B Table 6-1): 1 VIN, 2 GND, 3 ON, 4 CT (cap to VIN), 5 QOD, 6 VOUT.
  * HRO TYPE-C-31-M-12 / USBLC6-2SC6 / SMF5.0A: as dial-me-spinner base.py (same parts, same LCSC codes).
  * AO3401A (Alpha & Omega, Rev 3.1 Dec 2023, LCSC C15127, JLC Basic): SOT-23 1 G, 2 S, 3 D (KiCad
    Transistor_FET:AO3401A). VDS -30 V, VGS +-12 V; RDS(on) <= 60 mOhm at VGS -4.5 V (47 typ), <= 85 mOhm at -2.5 V
    (60 typ); VGS(th) -0.5...-1.3 V; RthJA 125 C/W max steady state. Battery reverse-polarity FET (SPEC §3).
"""

from sheets.parts import C0402, C0603, R0402, cap, res, testpoints

SHEET = ("power", "power.kicad_sch", "Power: USB-C, charger, 3V3, rails")

BQ_FP_NAME = "Texas_DSBGA-8_1.04x1.59mm_Layout2x4_P0.4mm_YBG0008"
BQ_FP = "caliper:" + BQ_FP_NAME
BQ_DS = "https://www.ti.com/lit/ds/symlink/bq25180.pdf"

BB_FP_NAME = "Texas_DLA0010A_VSON-HR-10_2x3mm_P0.5mm"
BB_FP = "caliper:" + BB_FP_NAME
BB_DS = "https://www.ti.com/lit/ds/symlink/tps63802.pdf"

FG_DS = "https://www.analog.com/media/en/technical-documentation/data-sheets/MAX17048-MAX17049.pdf"

SYMBOLS = [
    dict(
        name="BQ25180YBGR",
        ref="U",
        footprint=BQ_FP,
        datasheet=BQ_DS,
        description="I2C 1-cell 1 A linear charger with power path and ship mode, DSBGA-8 (YBG), I2C addr 0x6A",
        keywords="charger li-ion lipo power-path ship-mode",
        pins=[
            ("A2", "IN", "power_in", "T"),
            ("B1", "SCL", "input", "L"),
            ("C1", "SDA", "bidirectional", "L"),
            ("A1", "~{INT}", "open_collector", "L"),
            ("D1", "TS/MR", "bidirectional", "L"),
            ("B2", "SYS", "power_out", "R"),
            ("C2", "BAT", "power_out", "R"),
            ("D2", "GND", "power_in", "B"),
        ],
    ),
    dict(
        name="TPS63802DLA",
        ref="U",
        footprint=BB_FP,
        datasheet=BB_DS,
        description="2 A buck-boost converter, 1.3-5.5 V in, 11 uA Iq, VSON-HR-10 2x3 mm (DLA)",
        keywords="buck-boost dc-dc converter TI",
        pins=[
            (10, "VIN", "power_in", "L"),
            (1, "EN", "input", "L"),
            (2, "MODE", "input", "L"),
            (9, "L1", "passive", "T"),
            (7, "L2", "passive", "T"),
            (6, "VOUT", "power_out", "R"),
            (4, "FB", "input", "R"),
            (5, "PG", "open_collector", "R"),
            (3, "AGND", "power_in", "B"),
            (8, "GND", "power_in", "B"),
        ],
    ),
    dict(
        name="MAX17048G+T10",
        ref="U",
        footprint="Package_DFN_QFN:TDFN-8-1EP_2x2mm_P0.5mm_EP0.8x1.2mm",
        datasheet=FG_DS,
        description="1-cell ModelGauge fuel gauge, 3 uA hibernate, I2C addr 0x36, TDFN-8 2x2 mm",
        keywords="fuel gauge battery lipo I2C Maxim",
        pins=[
            (3, "VDD", "power_in", "T"),
            (2, "CELL", "input", "L"),
            (1, "CTG", "input", "L"),
            (6, "QSTRT", "input", "L"),
            (7, "SCL", "input", "R"),
            (8, "SDA", "bidirectional", "R"),
            (5, "~{ALRT}", "open_collector", "R"),
            (4, "GND", "power_in", "B"),
            (9, "EP", "passive", "B"),
        ],
    ),
]


def footprints(fpgen, lib_dir):
    pcbnew = fpgen.pcbnew

    # ---- BQ25180 YBG0008 (copied from dial-me-spinner base.py, TI SLUSE99C pp. 52-54)
    fp = fpgen.Footprint(
        BQ_FP_NAME,
        "Texas Instruments DSBGA-8 YBG0008-C01 (BQ25180YBGR), body 1.04x1.59 mm, 2x4 balls, 0.4 mm pitch, "
        "TI example land pattern: 0.23 mm NSMD copper, mask opening 0.025 per side, "
        "0.25 mm square R0.05 paste apertures for a 0.1 mm stencil. " + BQ_DS,
        "DSBGA YBG0008 BQ25180 BGA 0.4mm NSMD",
    )
    rows = (("A", -0.6), ("B", -0.2), ("C", 0.2), ("D", 0.6))   # top view: A1 top-left
    cols = (("1", -0.2), ("2", 0.2))
    for r, y in rows:
        for c, x in cols:
            p = fp.smd(r + c, x, y, 0.23, 0.23, shape="circle", paste=False)
            p.SetLocalSolderMaskMargin(pcbnew.FromMM(0.025))
            p.SetProperty(pcbnew.PAD_PROP_BGA)
            fp._pad("", x, y, 0.25, 0.25, "roundrect", pcbnew.PAD_ATTRIB_SMD, [pcbnew.F_Paste], rr=0.2)
    hw, hh = 0.52, 0.795
    fp.fab_rect(-hw, -hh, hw, hh)
    fp.line(pcbnew.F_Fab, -hw, -hh + 0.25, -hw + 0.25, -hh, 0.1)
    fp.silk_rect(-hw - 0.1, -hh - 0.1, hw + 0.1, hh + 0.1)
    fp.pin1_dot(-hw - 0.4, -hh - 0.25)
    fp.courtyard_rect(-1.02, -1.30, 1.02, 1.30)
    fp.save(lib_dir)

    # ---- TPS63802 DLA0010A (TI SLVSEU9D p. 36 "Example board layout"), top view, pin 1 top-left
    fp = fpgen.Footprint(
        BB_FP_NAME,
        "Texas Instruments DLA0010A VSON-HR-10, 2x3 mm body, 0.5 mm pitch, TI example land pattern "
        "(SLVSEU9D p. 36): pads 1-5 0.6x0.25 at x=-0.9; 6,7,9,10 0.9x0.25 at x=+0.75; 8 (GND) 1.3x0.25 at x=+0.55. "
        + BB_DS,
        "VSON-HR DLA0010A TPS63802 buck-boost",
    )
    ys = [-1.0, -0.5, 0.0, 0.5, 1.0]
    for i, y in enumerate(ys):
        fp.smd(str(i + 1), -0.9, y, 0.6, 0.25)
    for num, y in (("10", -1.0), ("9", -0.5), ("7", 0.5), ("6", 1.0)):
        fp.smd(num, 0.75, y, 0.9, 0.25)
    fp.smd("8", 0.55, 0.0, 1.3, 0.25)
    fp.fab_rect(-1.0, -1.5, 1.0, 1.5)
    fp.line(pcbnew.F_Fab, -1.0, -1.1, -0.6, -1.5, 0.1)
    fp.line(pcbnew.F_SilkS, -1.0, -1.62, 1.0, -1.62)
    fp.line(pcbnew.F_SilkS, -1.0, 1.62, 1.0, 1.62)
    fp.pin1_dot(-1.45, -1.45)
    fp.courtyard_rect(-1.45, -1.75, 1.45, 1.75)
    fp.save(lib_dir)


def build(d):
    d.sheet(*SHEET)

    d.group("USB-C input and protection",
            "HRO TYPE-C-31-M-12 (USB 2.0 device, sink only). Separate 5.1k Rd per CC pin; D+/D- pairs tied at the\n"
            "connector. USBLC6-2SC6 + SMF5.0A within 5 mm of J1, D+/D- routed through the ESD pads as a 90R pair.\n"
            "No series resistors on D+/D- (inside the ESP32-S3, SPEC §5). Right board edge, y 26.5 (SPEC §2.1).")
    res(d, "R1", "5.1k", "USB_CC1", "GND")
    res(d, "R2", "5.1k", "USB_CC2", "GND")
    d.add("J1", "Connector:USB_C_Receptacle_USB2.0_16P", "TYPE-C-31-M-12",
          "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12",
          pins={"A4": "VBUS", "A1": "GND", "SH": "GND",   # KiCad 10 library: the shield pin is SH (9: S1)
                "A5": "USB_CC1", "B5": "USB_CC2",
                "A6": "USB_DP", "B6": "USB_DP", "A7": "USB_DM", "B7": "USB_DM",
                "A8": None, "B8": None},
          fields={"MPN": "TYPE-C-31-M-12", "Manufacturer": "Korean Hroparts Elec", "LCSC": "C165948"})
    d.add("D1", "Diode:SMF5V0A", "SMF5.0A", "Diode_SMD:D_SMF", pins={"1": "VBUS", "2": "GND"}, rot=270,
          datasheet="https://www.littelfuse.com/assetdocs/tvs-diodes-smf-datasheet",
          description="200 W unidirectional TVS, 5.0 V VRWM, SOD-123FL (cathode = pin 1 to VBUS)",
          fields={"MPN": "SMF5.0A", "Manufacturer": "Littelfuse", "LCSC": "C151296"})
    d.add("U1", "Power_Protection:USBLC6-2SC6", "USBLC6-2SC6", "Package_TO_SOT_SMD:SOT-23-6",
          pins={"1": "USB_DP", "6": "USB_DP", "3": "USB_DM", "4": "USB_DM", "5": "VBUS", "2": "GND"},
          fields={"MPN": "USBLC6-2SC6", "Manufacturer": "STMicroelectronics", "LCSC": "C7519"})

    d.group("Charger and power path: BQ25180 (I2C 0x6A)",
            "ILIM / ICHG (70 mA) / SYS_REG / ship mode set over I2C: register init per dial-me-spinner docs/firmware.md §13.1.\n"
            "IN 2.2u/25V X7R 0805, SYS 10u/25V, BAT 4.7u: each within 1 mm of its ball and of the D2 GND ball.\n"
            "Ship mode exits only on a USB plug-in (TS/MR is not wired to a button in rev A).\n"
            "/INT -> CHG_INT_N (10k pull-up R8, GPIO3). RT1: 10k NTC next to J2 (board temperature, not the cell).")
    d.add("U2", "caliper:BQ25180YBGR", "BQ25180YBGR", BQ_FP,
          pins={"A2": "VBUS", "B2": "VSYS", "C2": "VBAT", "D2": "GND",
                "B1": "I2C_SCL", "C1": "I2C_SDA", "A1": "CHG_INT_N", "D1": "CHG_TSMR"},
          fields={"MPN": "BQ25180YBGR", "Manufacturer": "Texas Instruments", "LCSC": "C3682423"})
    cap(d, "C1", "2.2u/25V", "VBUS", "GND")
    cap(d, "C2", "10u/25V", "VSYS", "GND")
    cap(d, "C3", "4.7u", "VBAT", "GND")
    d.add("RT1", "Device:Thermistor_NTC", "10k B3435", R0402, pins={"1": "CHG_TSMR", "2": "GND"},
          datasheet="https://www.murata.com/en-us/products/productdetail?partno=NCP15XH103F03RC",
          fields={"MPN": "NCP15XH103F03RC", "Manufacturer": "Murata", "LCSC": "C77131"})

    d.group("LiPo connector J2 (~135 mAh 1S, JST-SH 2-pin) + reverse-polarity P-FET Q1",
            "Pin 1 = BAT+, pin 2 = GND. Pack leads are not standardised: check every pack's polarity anyway.\n"
            "Q1 AO3401A in the BAT+ lead: drain to J2, source to VBAT, gate to GND via R10. The body diode conducts for a\n"
            "correct cell, then VGS = -VBAT turns the channel on (both directions, so charging works). A reversed cell\n"
            "leaves VGS = 0: off. VGS max +-12 V vs 4.4 V: no zener. 0.5 A: <= 43 mV / 21 mW (85 mOhm max at VGS -2.5 V).\n"
            "J2 is on the bottom; it, the plug and the cell sit in the housing pocket behind the board (SPEC §2.1).", anchor="J2")
    d.add("J2", "Connector_Generic_MountingPin:Conn_01x02_MountingPin", "BATT",
          "Connector_JST:JST_SH_SM02B-SRSS-TB_1x02-1MP_P1.00mm_Horizontal",
          pins={"1": "VBAT_RAW", "2": "GND", "MP": "GND"},
          fields={"MPN": "SM02B-SRSS-TB(LF)(SN)", "Manufacturer": "JST", "LCSC": "C160402"})
    d.add("Q1", "Transistor_FET:AO3401A", "AO3401A", "Package_TO_SOT_SMD:SOT-23",
          pins={"D": "VBAT_RAW", "S": "VBAT", "G": "BATFET_G"},
          datasheet="https://www.aosmd.com/res/datasheets/AO3401A.pdf",
          fields={"MPN": "AO3401A", "Manufacturer": "Alpha & Omega Semiconductor", "LCSC": "C15127"})
    res(d, "R10", "10k", "BATFET_G", "GND")

    d.group("3V3 buck-boost: TPS63802 (VSYS 2.5-4.6 V -> +3V3, 2 A)",
            "Buck-boost, not an LDO: Wi-Fi TX peaks ~355 mA (module datasheet) and the cell falls below 3.4 V (SPEC §3).\n"
            "EN tied to VSYS (always on), MODE = GND (power save: 11 uA Iq), PG unused.\n"
            "R3/R4 = 511k/91k -> 3.31 V (VFB 0.5 V, TI Table 10-5); the divider draws 5.5 uA (R2 <= 100k rule).\n"
            "L1 DFE201612E-R47M (TI Table 10-2). CIN 10u + COUT 22u per Fig. 10-1, plus 22u bulk C6 for the RF bursts.\n"
            "Layout: VIN/VOUT caps and L1 on the same layer as U3, GND pad 8 to the plane with >= 2 vias.")
    cap(d, "C4", "10u", "VSYS", "GND")
    d.add("U3", "caliper:TPS63802DLA", "TPS63802DLAR", BB_FP,
          pins={"VIN": "VSYS", "EN": "VSYS", "MODE": "GND", "L1": "BB_L1", "L2": "BB_L2",
                "VOUT": "+3V3", "FB": "BB_FB", "PG": None, "AGND": "GND", "GND": "GND"},
          fields={"MPN": "TPS63802DLAR", "Manufacturer": "Texas Instruments", "LCSC": "C2845237"})
    d.add("L1", "Device:L", "0.47u", "Inductor_SMD:L_Murata_DFE201610P", pins={"1": "BB_L1", "2": "BB_L2"},
          datasheet="https://www.murata.com/en-us/products/productdetail?partno=DFE201612E-R47M%3DP2",
          description="0.47 uH 5.5 A (Isat) 26 mOhm power inductor, 2.0x1.6x1.2 mm (land = DFE201610P)",
          fields={"MPN": "DFE201612E-R47M=P2", "Manufacturer": "Murata", "LCSC": "C668312"})
    res(d, "R3", "511k", "+3V3", "BB_FB")
    res(d, "R4", "91k", "BB_FB", "GND")
    cap(d, "C5", "22u", "+3V3", "GND")
    cap(d, "C6", "22u", "+3V3", "GND")

    d.group("Fuel gauge: MAX17048 (I2C 0x36)",
            "Powered from the cell (VDD = CELL = VBAT, Fig. 14). CTG, QSTRT and EP to GND. 3 uA in hibernate.\n"
            "ALRT -> FG_ALRT_N (10k pull-up R9, GPIO2: low SOC / voltage alert).")
    cap(d, "C7", "100n", "VBAT", "GND")
    d.add("U4", "caliper:MAX17048G+T10", "MAX17048G+T10", "Package_DFN_QFN:TDFN-8-1EP_2x2mm_P0.5mm_EP0.8x1.2mm",
          pins={"VDD": "VBAT", "CELL": "VBAT", "CTG": "GND", "QSTRT": "GND", "SCL": "I2C_SCL", "SDA": "I2C_SDA",
                "~{ALRT}": "FG_ALRT_N", "GND": "GND", "EP": "GND"},
          fields={"MPN": "MAX17048G+T10", "Manufacturer": "Analog Devices (Maxim)", "LCSC": "C2682616"})

    d.group("Sensor rail +3V3_SNS: TPS22917 (SNS_PWR_EN)",
            "AS5311 (~16 mA) + capacitive front-end. Off in sleep. CT 1n to VIN (slew ~ms, no +3V3 droop);\n"
            "QOD tied to VOUT (internal R) so the rail discharges when off. R5 holds ON low while the ESP32 is in reset.\n"
            "Firmware: drive MAG_CSN / MAG_CLK low before SNS_PWR_EN goes low (no back-powering through the ESD diodes).")
    cap(d, "C8", "1u", "+3V3", "GND")
    d.add("U5", "Power_Management:TPS22917DBV", "TPS22917DBVR", "Package_TO_SOT_SMD:SOT-23-6",
          pins={"VIN": "+3V3", "GND": "GND", "ON": "SNS_PWR_EN", "CT": "SNS_CT", "QOD": "+3V3_SNS",
                "VOUT": "+3V3_SNS"},
          fields={"MPN": "TPS22917DBVR", "Manufacturer": "Texas Instruments", "LCSC": "C2681320"})
    cap(d, "C9", "1n", "SNS_CT", "+3V3")
    cap(d, "C10", "1u", "+3V3_SNS", "GND")
    res(d, "R5", "100k", "SNS_PWR_EN", "GND")

    d.group("UI rail +3V3_UI: TPS22917 (also on SNS_PWR_EN)",
            "LCD logic VDD (ST7789 sleep-in still draws 15+5 uA typ, DM-TFT114 §5.3) + WS2812 RGB LED: both off in deep sleep.\n"
            "Shares SNS_PWR_EN (no free GPIO): the rails are on together whenever the caliper is awake.\n"
            "C13 1u at VIN (pin 1): the switch's own input cap (C5 is 12.5 mm away by copper).\n"
            "Firmware: drive the LCD_* lines and RGB_DIN low before switching off.")
    cap(d, "C13", "1u", "+3V3", "GND", near="U6.1")
    d.add("U6", "Power_Management:TPS22917DBV", "TPS22917DBVR", "Package_TO_SOT_SMD:SOT-23-6",
          pins={"VIN": "+3V3", "GND": "GND", "ON": "SNS_PWR_EN", "CT": "UI_CT", "QOD": "+3V3_UI",
                "VOUT": "+3V3_UI"},
          fields={"MPN": "TPS22917DBVR", "Manufacturer": "Texas Instruments", "LCSC": "C2681320"})
    cap(d, "C11", "1n", "UI_CT", "+3V3")
    cap(d, "C12", "1u", "+3V3_UI", "GND")

    d.group("I2C + open-drain pull-ups (always-on +3V3)",
            "SDA/SCL 2.2k: BQ25180 0x6A, MAX17048 0x36, LSM6DSO 0x6B at 400 kHz (SPEC §6): ~205 ns rise (30-70 %)\n"
            "with ~110 pF (4.7k gave 438 ns > 300 ns); 1.3 mA sink at VOL 0.4 V (fast mode allows 3 mA).\n"
            "Must stay on the always-on rail: the MAX17048 reads a low bus as 'disconnected' and sleeps.")
    res(d, "R6", "2.2k", "+3V3", "I2C_SDA")
    res(d, "R7", "2.2k", "+3V3", "I2C_SCL")
    res(d, "R8", "10k", "+3V3", "CHG_INT_N")
    res(d, "R9", "10k", "+3V3", "FG_ALRT_N")

    d.group("Mounting holes and fiducials",
            "H1 (18.75, 24) support hole; H2-H5 tab clamp holes (-3.5, 5.5) (-3.5, 14) (65.5, 5.5) (65.5, 14), plated, to\n"
            "GND (SPEC §2.1). H2-H5 carry an SMT M2 standoff, fitted by hand (no LCSC part fits the 6 mm tab). 3 fiducials.")
    for i in range(1, 6):
        d.add(f"H{i}", "Mechanical:MountingHole_Pad", "M2", "MountingHole:MountingHole_2.2mm_M2_Pad_Via",
              pins={"1": "GND"}, in_bom=False)
    for i in range(1, 4):
        d.add(f"FID{i}", "Mechanical:Fiducial", "Fiducial", "Fiducial:Fiducial_1mm_Mask2mm", in_bom=False)

    d.group("Power flags and test points",
            "VBUS (USB-C) and GND are driven from outside the board.")
    d.add("#FLG01", "power:PWR_FLAG", "PWR_FLAG", "", pins={"1": "VBUS"}, in_bom=False, on_board=False, rot=90)
    d.add("#FLG02", "power:PWR_FLAG", "PWR_FLAG", "", pins={"1": "GND"}, in_bom=False, on_board=False, rot=90)
    testpoints(d, 1, ["VBUS", "VBAT", "VSYS", "+3V3", "+3V3_SNS", "+3V3_UI", "GND"])
