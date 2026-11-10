"""Slider board: LSM6DSO 6-axis IMU (3-axis accelerometer + 3-axis gyroscope: wake on pickup, auto-off, orientation).
See SPEC.md §1, §6, §16.

Rev A first carried a LIS2DW12 (accelerometer only); the gyroscope was added on 2026-11-10 (owner request, SPEC §16).

Pinout: ST DS12140 Rev 3, Table 1 + Fig. 3 (bottom view; mirrored for the top view: pin 1 top left, 1-4 down the left,
5-7 along the bottom, 8-11 up the right, 12-14 along the top from right to left). Mode 1 (I2C slave only):
1 SDO/SA0, 2 SDx, 3 SCx, 4 INT1, 5 VDDIO, 6 GND, 7 GND, 8 VDD, 9 INT2, 10 OCS_Aux, 11 SDO_Aux, 12 CS, 13 SCL, 14 SDA.
KiCad Package_LGA:LGA-14_3x2.5mm_P0.5mm_LayoutBorder3x4y (drawn from the pin-compatible LSM6DS3TR-C) has the same pad
order. Axes (Fig. 3, top view, pin 1 top left): X to the right, Y up, Z out of the top; at 0 deg on the top side that
is chip X = board +x (along the beam), chip Y = board +y, chip Z = out of the display face.

Address: SA0 is tied HIGH -> 0x6B. SA0 low is 0x6A, which is the BQ25180's address on the same bus. Unlike the
LIS2DW12, SDO/SA0 here is an input WITHOUT a pull-up by default (Table 19; PIN_CTRL.SDO_PU_EN = 0), so the strap
costs no current either way.

Mode 1 straps (Table 1, Table 19): SDx / SCx to GND ("connect to VDDIO or GND"), CS to VDDIO (I2C), OCS_Aux and
SDO_Aux left unconnected but soldered. INT1 is an input with a pull-down until the firmware configures it and "must be
set to 0 or left unconnected during power-on" (Table 19 note 2): the IMU_INT1 net has no pull and GPIO15 is a
high-impedance input at reset, so the pull-down wins.
"""

from sheets.parts import C0402, cap

SHEET = ("imu", "imu.kicad_sch", "IMU (accelerometer + gyroscope)")

LSM_DS = "https://www.st.com/resource/en/datasheet/lsm6dso.pdf"
LSM_FP = "Package_LGA:LGA-14_3x2.5mm_P0.5mm_LayoutBorder3x4y"

SYMBOLS = [
    dict(
        name="LSM6DSO",
        ref="U",
        footprint=LSM_FP,
        datasheet=LSM_DS,
        description="6-axis IMU: 3-axis accelerometer + 3-axis gyroscope, I2C/SPI, 1.71-3.6 V, LGA-14 2.5x3x0.83 mm",
        keywords="accelerometer gyroscope MEMS IMU 6-axis I2C SPI ST",
        pins=[
            (8, "VDD", "power_in", "T"),
            (5, "VDDIO", "power_in", "L"),
            (12, "CS", "input", "L"),
            (1, "SDO/SA0", "input", "L"),
            (2, "SDx", "input", "L"),
            (3, "SCx", "input", "L"),
            (13, "SCL", "input", "R"),
            (14, "SDA", "bidirectional", "R"),
            (4, "INT1", "output", "R"),
            (9, "INT2", "output", "R"),
            (10, "OCS_Aux", "no_connect", "R"),
            (11, "SDO_Aux", "no_connect", "R"),
            (6, "GND", "power_in", "B"),
            (7, "GND", "power_in", "B"),
        ],
    ),
]


def build(d):
    d.sheet(*SHEET)

    d.group("6-axis IMU: LSM6DSO on the system I2C (addr 0x6B, SA0 high; 0x6A is the BQ25180)",
            "Always on (+3V3). Asleep: accelerometer only, ultra-low-power 12.5 Hz, gyroscope powered down (5.5 uA typ,\n"
            "AN5192 Table 9), wake-up interrupt while the ESP32 is in deep sleep. Awake: gyroscope on (0.30 mA at 52 Hz low-power).\n"
            "CS high = I2C. SA0 high (no internal pull-up by default). SDx / SCx to GND, OCS_Aux / SDO_Aux unconnected.\n"
            "INT1 -> IMU_INT1 (GPIO15, RTC: deep-sleep wake on pickup), INT2 -> IMU_INT2 (GPIO16). Push-pull, no pulls:\n"
            "INT1 must be low or floating while the IMU powers up (its own pull-down holds it).\n"
            "100n + 10u at VDD (pin 8), 100n at VDDIO (pin 5). Keep away from the buck-boost inductor.")
    cap(d, "C60", "100n", "GND", "+3V3", near="U60.8")      # near= is a placer hint only
    cap(d, "C61", "10u", "GND", "+3V3", near="U60.8")
    cap(d, "C62", "100n", "GND", "+3V3", near="U60.5")
    d.add("U60", "caliper:LSM6DSO", "LSM6DSOTR", LSM_FP,
          pins={"13": "I2C_SCL", "14": "I2C_SDA", "12": "+3V3", "1": "+3V3",
                "4": "IMU_INT1", "9": "IMU_INT2", "10": None, "11": None,
                "8": "+3V3", "5": "+3V3", "6": "GND", "7": "GND", "2": "GND", "3": "GND"},
          fields={"MPN": "LSM6DSOTR", "Manufacturer": "STMicroelectronics", "LCSC": "C2655100"})
