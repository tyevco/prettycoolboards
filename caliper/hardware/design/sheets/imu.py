"""Slider board: LIS2DW12 accelerometer (wake on pickup, auto-off, orientation). See SPEC.md §1, §6.

Pinout: ST DS11811 Rev 8, Table 1 + Fig. 6 (top view): 1 SCL/SPC, 2 CS, 3 SDO/SA0, 4 SDA/SDI/SDO, 5 NC, 6 GND, 7 RES,
8 GND, 9 VDD, 10 VDD_IO, 11 INT2, 12 INT1. KiCad Package_LGA:LGA-12_2x2mm_P0.5mm has the same pad order.
Symbol copied from dial-me-spinner sensors.py (checked against the same table there).

Address: SA0 is tied HIGH -> 0x19. SPEC rev A first asked for SA0 low (0x18), but SDO/SA0 has an internal pull-up
that cannot be disconnected in I2C mode (ST AN5038, "pin status"), so grounding it costs ~60-170 uA forever
(dial-me-spinner docs/bringup.md, measured fault signature). That alone would be 2-7x the whole sleep budget.
"""

from sheets.parts import C0402, cap

SHEET = ("imu", "imu.kicad_sch", "Accelerometer")

LIS_DS = "https://www.st.com/resource/en/datasheet/lis2dw12.pdf"

SYMBOLS = [
    dict(
        name="LIS2DW12",
        ref="U",
        footprint="Package_LGA:LGA-12_2x2mm_P0.5mm",
        datasheet=LIS_DS,
        description="Ultra-low-power 3-axis accelerometer, I2C/SPI, 1.62-3.6 V, LGA-12 2x2x0.7 mm",
        keywords="accelerometer MEMS IMU I2C SPI ST",
        pins=[
            (9, "VDD", "power_in", "T"),
            (10, "VDD_IO", "power_in", "L"),
            (2, "CS", "input", "L"),
            (3, "SDO/SA0", "input", "L"),
            (7, "RES", "input", "L"),
            (1, "SCL/SPC", "input", "R"),
            (4, "SDA/SDI/SDO", "bidirectional", "R"),
            (12, "INT1", "output", "R"),
            (11, "INT2", "output", "R"),
            (5, "NC", "no_connect", "R"),
            (6, "GND", "power_in", "B"),
            (8, "GND", "power_in", "B"),
        ],
    ),
]


def build(d):
    d.sheet(*SHEET)

    d.group("Accelerometer: LIS2DW12 on the system I2C (addr 0x19, SA0 high)",
            "Always on (+3V3): wake-up / 6D / activity interrupts while the ESP32 is in deep sleep (~1 uA in low-power wake mode).\n"
            "CS high = I2C. SA0 high (never ground it: internal pull-up, see module docstring). RES to GND.\n"
            "INT1 -> IMU_INT1 (GPIO15, RTC: deep-sleep wake on pickup), INT2 -> IMU_INT2 (GPIO16). Push-pull, no pull-ups.\n"
            "100n + 10u at VDD (pin 9), 100n at VDD_IO (pin 10). Keep away from the buck-boost inductor.")
    cap(d, "C60", "100n", "GND", "+3V3")
    cap(d, "C61", "10u", "GND", "+3V3")
    cap(d, "C62", "100n", "GND", "+3V3")
    d.add("U60", "caliper:LIS2DW12", "LIS2DW12TR", "Package_LGA:LGA-12_2x2mm_P0.5mm",
          pins={"1": "I2C_SCL", "4": "I2C_SDA", "2": "+3V3", "3": "+3V3",
                "12": "IMU_INT1", "11": "IMU_INT2", "5": None,
                "9": "+3V3", "10": "+3V3", "6": "GND", "8": "GND", "7": "GND"},
          fields={"MPN": "LIS2DW12TR", "Manufacturer": "STMicroelectronics", "LCSC": "C189624"})
