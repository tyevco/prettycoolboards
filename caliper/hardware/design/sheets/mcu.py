"""Slider board: ESP32-S3-MINI-1-N4R2 module, EN reset RC, BOOT button, strapping resistors. See SPEC.md §5.

Pinout: Espressif "ESP32-S3-MINI-1 & MINI-1U Datasheet" v1.7, Table "Pin Definitions" (pads 1-65; 23 = IO19/USB_D-,
24 = IO20/USB_D+, 39 TXD0 = GPIO43, 40 RXD0 = GPIO44, 41 IO45, 44 IO46, 45 EN, 1/2/42/43/46-65 GND).
KiCad 9's RF_Module:ESP32-S3-MINI-1 symbol matches pad for pad (it names pads 23/24 USB_D-/USB_D+, which
_PIN_ALIAS maps back to the IO19/IO20 keys of nets.MCU_PINS). Its default footprint is
RF_Module:ESP32-S2-MINI-1: the S2-MINI-1 and S3-MINI-1 share the 15.4 x 20.5 mm, 65-pad land pattern
(S3-MINI-1 datasheet §11.1 "PCB Land Pattern", Fig. 11-1). The KiCad footprint has NO antenna keep-out zone (and
its description wrongly says "external antenna"): the layout must add an all-layer copper keep-out at the antenna.

Peripheral circuit: datasheet Fig. 9-1 / §9 "Peripheral schematics": 22 uF + 0.1 uF at 3V3, EN RC delay
R = 10 kOhm / C = 1 uF. N4R2: 4 MB quad flash + 2 MB quad PSRAM, IO26 = PSRAM CS (not available).
"""

from nets import MCU_PINS
from sheets.parts import cap, res, testpoints

SHEET = ("mcu", "mcu.kicad_sch", "ESP32-S3 module")

MCU_SYM = "RF_Module:ESP32-S3-MINI-1"
MCU_FP = "RF_Module:ESP32-S2-MINI-1"

# nets.MCU_PINS keys that the KiCad symbol names differently (pad numbers, see module docstring)
_PIN_ALIAS = {"IO19": "23", "IO20": "24"}


def mcu_pins():
    return {_PIN_ALIAS.get(k, k): v for k, v in MCU_PINS.items()}


def build(d):
    d.sheet(*SHEET)

    d.group("ESP32-S3-MINI-1-N4R2 (4 MB flash, 2 MB PSRAM, PCB antenna)",
            "Pin map = nets.MCU_PINS (SPEC §5); caliper/hardware/design/check_contract.py checks the netlist against it.\n"
            "Antenna end on the top board edge (y = 34), hanging clear of the steel beam; copper keep-out on all layers\n"
            "under the antenna (Espressif HW design guidelines). EPAD + GND pads to the plane with a via array.\n"
            "N8R2 is not stocked at LCSC (2026-11); N4R2 C3013941 is. IO26 is the PSRAM CS: left unconnected.")
    d.add("U10", MCU_SYM, "ESP32-S3-MINI-1-N4R2", MCU_FP, pins=mcu_pins(),
          fields={"MPN": "ESP32-S3-MINI-1-N4R2", "Manufacturer": "Espressif Systems", "LCSC": "C3013941"})

    d.group("3V3 decoupling at the module",
            "Datasheet Fig. 9-1: 22u + 100n at pad 3. C21 100n + C23 10u (0402, 0.5 mm tall) on the BOTTOM, under pad 3,\n"
            "fed from its escape via, own GND vias (the housing floor is 0.75 mm below there, SPEC §2.1).\n"
            "C20 22u (0603, 0.8 mm) is the bulk on top below the module, fed through the In2 +3V3 pour.")
    cap(d, "C20", "22u", "+3V3", "GND", rot=270)
    cap(d, "C21", "100n", "+3V3", "GND", rot=0)
    cap(d, "C23", "10u/6.3V", "+3V3", "GND", rot=0)

    d.group("EN reset delay", "R 10k / C 1u (datasheet §9). EN pad on a test point for a manual reset.")
    res(d, "R20", "10k", "+3V3", "MCU_EN")
    cap(d, "C22", "1u", "MCU_EN", "GND")

    d.group("BOOT (GPIO0 strap)",
            "10k pull-up: SPI boot. Hold SW20 during reset/USB plug-in for the ROM download mode.\n"
            "Normally flashed over USB-Serial-JTAG without the button; SW20 is the recovery path.")
    res(d, "R21", "10k", "+3V3", "BOOT_N")
    d.add("SW20", "Switch:SW_Push", "BOOT", "Button_Switch_SMD:SW_SPST_TS-1088-xR020",
          pins={"1": "BOOT_N", "2": "GND"},
          datasheet="https://www.lcsc.com/datasheet/C720477.pdf",
          description="Tactile switch SPST-NO 3.9x2.9x2.0 mm, SMD",
          fields={"MPN": "TS-1088-AR02016", "Manufacturer": "XUNPU", "LCSC": "C720477"})

    d.group("Strapping pull-downs",
            "GPIO45 = VDD_SPI select, must read 0 at reset (3.3 V flash): 100k on the BUZZ gate is on the ui sheet (R56).\n"
            "GPIO46 must be 0/float at reset: 100k on RGB_DIN is on the ui sheet (R55).\n"
            "GPIO3 (CHG_INT_N, 10k pull-up R8): JTAG-source strap, ignored while the JTAG_SEL eFuse is unburnt.")

    d.group("Test points", "EN, BOOT and the native USB pair for bring-up")
    testpoints(d, 20, ["MCU_EN", "BOOT_N", "USB_DP", "USB_DM"])
