"""Slider board: AS5311 magnetic linear encoder (primary sensor). See SPEC.md §4.1.

Pinout: ams AS5311 datasheet Revision 1.13, Figure "Pin Configuration TSSOP-20" and Table 1 "Pin Descriptions":
   1 NC, 2 MagINCn (OD), 3 MagDECn (OD), 4 A, 5 B, 6 NC, 7 Index, 8 VSS, 9 Prog (to VSS), 10 NC, 11 NC,
  12 DO (SSI data, tri-state), 13 CLK (SSI clock, Schmitt), 14 CSn (pull-up ~50k; low enables A/B/Index),
  15 PWM, 16 NC, 17 NC, 18 VDD3V3 (LDO out), 19 VDD5V (supply), 20 NC.
  "Pins 1, 6, 10, 11, 16, 17 and 20 are for internal use and must not be connected."
  §7.7: "For 3.3V operation, the LDO must be bypassed by connecting VDD3V3 with VDD5V"; "A buffer capacitor of
  100nF is recommended in both cases close to pin VDD5V"; VDD3V3 "must always be buffered by a capacitor".
Package: TSSOP-20 4.4 x 6.5 mm, 0.65 mm pitch (KiCad Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm, pin 1 top-left, pins
1-10 down the left side and 11-20 up the right side, the standard JEDEC MO-153 numbering the datasheet uses).
"""

from sheets.parts import cap, res, testpoints

SHEET = ("sensor_mag", "sensor_mag.kicad_sch", "AS5311 magnetic encoder")

AS_DS = "https://ams-osram.com/products/sensor-solutions/position-sensors/ams-as5311-linear-position-sensor"
AS_FP = "Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm"

SYMBOLS = [
    dict(
        name="AS5311",
        ref="U",
        footprint=AS_FP,
        datasheet=AS_DS,
        description="High-resolution magnetic linear encoder, 2.0 mm pole pair, 12-bit SSI + A/B/Index, TSSOP-20",
        keywords="magnetic linear encoder position sensor ams",
        pins=[
            (19, "VDD5V", "power_in", "T"),
            (18, "VDD3V3", "power_in", "T"),
            (14, "CSn", "input", "L"),
            (13, "CLK", "input", "L"),
            (9, "Prog", "input", "L"),
            (12, "DO", "tri_state", "R"),
            (4, "A", "output", "R"),
            (5, "B", "output", "R"),
            (7, "Index", "output", "R"),
            (2, "MagINCn", "open_collector", "R"),
            (3, "MagDECn", "open_collector", "R"),
            (15, "PWM", "output", "R"),
            (8, "VSS", "power_in", "B"),
            (1, "NC1", "no_connect", "L"),
            (6, "NC6", "no_connect", "L"),
            (10, "NC10", "no_connect", "L"),
            (11, "NC11", "no_connect", "L"),
            (16, "NC16", "no_connect", "L"),
            (17, "NC17", "no_connect", "L"),
            (20, "NC20", "no_connect", "L"),
        ],
    ),
]


def build(d):
    d.sheet(*SHEET)

    d.group("AS5311 linear encoder (BOTTOM side, over the magnetic tape)",
            "Centred at (31, 6.0) on the bottom, long axis along X (beam axis), SPEC §2.1. Air gap 0.3 +/-0.1 mm to the tape.\n"
            "3.3 V operation: VDD5V and VDD3V3 both on +3V3_SNS (datasheet §7.7), 100n + 1u at pin 19.\n"
            "A/B -> PCNT (4x: 0.488 um/count), Index once per 2 mm pole pair, SSI (CSn/CLK/DO) for the 12-bit absolute\n"
            "position + OCF/COF/LIN/MagINC/MagDEC. CSn must be low for A/B/Index. Prog to VSS (no OTP in rev A). PWM unused.\n"
            "No copper pour, vias or magnetic parts in the tape window under the IC beyond what the bottom layer rules allow.")
    cap(d, "C30", "100n", "+3V3_SNS", "GND")
    cap(d, "C31", "1u", "+3V3_SNS", "GND")
    d.add("U30", "caliper:AS5311", "AS5311-ATST", AS_FP,
          pins={"VDD5V": "+3V3_SNS", "VDD3V3": "+3V3_SNS", "VSS": "GND", "Prog": "GND",
                "CSn": "MAG_CSN", "CLK": "MAG_CLK", "DO": "MAG_DO",
                "A": "MAG_A", "B": "MAG_B", "Index": "MAG_IDX",
                "MagINCn": "MAG_INC_N", "MagDECn": "MAG_DEC_N", "PWM": None,
                **{f"NC{n}": None for n in (1, 6, 10, 11, 16, 17, 20)}},
          fields={"MPN": "AS5311-ATST", "Manufacturer": "ams OSRAM", "LCSC": "C22459687",
                  "JLC": "LCSC stock was 80 pcs (2026-11): order early, else consign/hand-place"})

    d.group("Magnetic-field indicator pull-ups",
            "MagINCn / MagDECn are open drain (datasheet Table 1, §4.1): 10k to +3V3_SNS, so they read low (= 'alarm')\n"
            "when the sensor rail is off; the firmware only reads them with SNS_PWR_EN high.")
    res(d, "R30", "10k", "+3V3_SNS", "MAG_INC_N")
    res(d, "R31", "10k", "+3V3_SNS", "MAG_DEC_N")

    d.group("Test points", "Quadrature + index for a scope / logic analyser during bring-up")
    testpoints(d, 30, ["MAG_A", "MAG_B", "MAG_IDX"])
