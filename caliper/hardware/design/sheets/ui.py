"""Slider board: 1.14in ST7789 IPS panel connector + backlight driver, buttons, RGB status LED, piezo. See SPEC.md §1, §2.1.

Panel pinout (13-pin FPC): DisplayModule DM-TFT114-397 datasheet (2020-02-27), §3.1 "Panel Pin Description" and the
§4.1 drawing table (1.14in, 135x240, ST7789V, 4-wire SPI), https://cdn.shopify.com/s/files/1/0264/7629/files/DM-TFT114-397_Datasheet.pdf :
   1 NC, 2 NC, 3 SDA, 4 SCL, 5 RS (= D/C), 6 RESET, 7 CS, 8 GND, 9 NC, 10 VDD, 11 LEDK, 12 LEDA, 13 GND.
   Backlight: 1 white LED, VF 3.0 V (2.9-3.1) at 20 mA. VDD 2.4-3.3 V, 8 mA typ; sleep-in 15 + 5 uA typ.
This is the common pin order of the 13-pin 1.14in ST7789 glass sold under many part numbers, but vendors differ:
check the pin order AND the tail pitch of the panel actually bought (DM's drawing shows a 0.7 mm solder tail; the
connector here needs a 0.5 mm-pitch, 0.3 mm-thick plug-in tail).

Connector: Hroparts-style 0.5K-AX-13PWB (LCSC C2911931): 13 pins, 0.5 mm, bottom contact, slide lock, 2.0 mm high.
The footprint used is KiCad's Hirose FH12-13S-0.5SH (same 0.5 mm / 13 + 2 MP class of land pattern; the FH12 itself is
not stocked at LCSC). Layout must check the pad/nail geometry against the C2911931 drawing before release.

WS2812B-2020-V6 (Worldsemi, LCSC C52917434): LCSC lists 3.3-5.3 V supply, so it runs from +3V3_UI with a 3.3 V DIN
(VIH 0.7 VDD). Pin order assumed identical to the WS2812B-2020 (KiCad LED:WS2812B-2020: 1 DOUT, 2 VSS, 3 DIN, 4 VDD);
the V6 datasheet was not retrievable during capture: verify before release.
"""

from sheets.parts import R0603, SOT23, cap, res, testpoints

SHEET = ("ui", "ui.kicad_sch", "Display, buttons, LED, piezo")

FPC_FP = "Connector_FFC-FPC:Hirose_FH12-13S-0.5SH_1x13-1MP_P0.50mm_Horizontal"
BTN_FP = "Button_Switch_SMD:SW_SPST_TS-1088-xR020"
BTN_FIELDS = {"MPN": "TS-1088-AR02016", "Manufacturer": "XUNPU", "LCSC": "C720477"}
FET_FIELDS = {"MPN": "AO3400A", "Manufacturer": "Alpha & Omega Semiconductor", "LCSC": "C20917"}

# FPC contact -> net (DM-TFT114-397 §3.1). None = no-connect.
PANEL_PINS = {
    1: None, 2: None,
    3: "LCD_MOSI",     # SDA (write-only SPI)
    4: "LCD_SCK",      # SCL
    5: "LCD_DC",       # RS
    6: "LCD_RST_N",    # RESET
    7: "LCD_CS_N",     # CS
    8: "GND",
    9: None,
    10: "+3V3_UI",     # VDD (logic + analog)
    11: "LCD_LEDK",    # backlight cathode -> Q50 drain
    12: "LCD_LEDA",    # backlight anode <- R50 <- +3V3
    13: "GND",
}


def build(d):
    d.sheet(*SHEET)

    d.group("LCD: 1.14in 240x135 ST7789 IPS, 13-pin 0.5 mm FPC (J50)",
            "Pin map: DM-TFT114-397 §3.1 (1 NC, 2 NC, 3 SDA, 4 SCL, 5 RS=D/C, 6 RESET, 7 CS, 8 GND, 9 NC, 10 VDD, 11 LEDK, 12 LEDA, 13 GND).\n"
            "SPI2 40 MHz write-only (SPEC §6). VDD from the switched +3V3_UI rail. 1u + 100n at pin 10.\n"
            "Beside the module on top; the glass is glued to the bezel, not the board (SPEC §2.1).\n"
            "Check the bought panel's pin order and 0.5 mm tail pitch before ordering (vendors differ).")
    cap(d, "C50", "1u", "+3V3_UI", "GND")
    cap(d, "C51", "100n", "+3V3_UI", "GND")
    d.add("J50", "Connector_Generic_MountingPin:Conn_01x13_MountingPin", "LCD_FPC", FPC_FP,
          pins={**{str(k): v for k, v in PANEL_PINS.items()}, "MP": "GND"},
          datasheet="https://www.lcsc.com/datasheet/C2911931.pdf",
          description="FFC/FPC connector 13P 0.5 mm, bottom contact, slide lock, 2.0 mm high",
          fields={"MPN": "0.5K-AX-13PWB", "Manufacturer": "Hroparts", "LCSC": "C2911931"})

    d.group("Backlight: low-side N-MOSFET on LCD_BL (PWM)",
            "+3V3 -> R50 15R -> LEDA, LEDK -> Q50 -> GND. 1 white LED, VF 3.0 V (2.9-3.1) at 20 mA.\n"
            "(3.31 V - VF) / 15R: 20 mA at VF 3.0, 27 mA max at 2.9, 14 mA at 3.1 (10R gave 31-41 mA).\n"
            "Headroom is only ~0.3 V, so brightness follows VF and the +3V3 tolerance; dim by PWM (LEDC, ~20 kHz).\n"
            "R51 100k holds the gate low while GPIO38 floats in reset.")
    d.add("R50", "Device:R", "15", R0603, pins={"1": "+3V3", "2": "LCD_LEDA"},
          fields={"MPN": "0603WAF150JT5E", "Manufacturer": "UNI-ROYAL", "LCSC": "C22810"})
    d.add("Q50", "Transistor_FET:AO3400A", "AO3400A", SOT23,
          pins={"G": "LCD_BL", "D": "LCD_LEDK", "S": "GND"}, fields=FET_FIELDS)
    res(d, "R51", "100k", "LCD_BL", "GND")

    d.group("Buttons: ZERO / HOLD-SEND / MODE (active low, RTC GPIOs 17/18/21 for deep-sleep wake)",
            "100k pull-up (no static current) + 100n to GND: 10 ms RC debounce; ext1 wake on any-low.\n"
            "TS-1088 3.9x2.9 mm top tact switches on the top edge band: ZERO x~8, HOLD x~20, MODE x~54 (SPEC §2.1).")
    for i, (net, name) in enumerate([("BTN_ZERO_N", "ZERO"), ("BTN_HOLD_N", "HOLD"), ("BTN_MODE_N", "MODE")]):
        res(d, f"R5{2 + i}", "100k", "+3V3", net)
        cap(d, f"C5{2 + i}", "100n", net, "GND")
        d.add(f"SW5{i}", "Switch:SW_Push", name, BTN_FP, pins={"1": net, "2": "GND"},
              datasheet="https://www.lcsc.com/datasheet/C720477.pdf",
              description="Tactile switch SPST-NO 3.9x2.9x2.0 mm, SMD", fields=BTN_FIELDS)

    d.group("RGB status LED: WS2812B-2020-V6 on +3V3_UI (GPIO46 = RGB_DIN)",
            "3.3-5.3 V part (LCSC C52917434), so no level shifter: DIN at 3.3 V logic = VDD. Off with +3V3_UI in sleep.\n"
            "R55 100k pull-down: GPIO46 is a strap (must be 0/float at reset). 100n at VDD.")
    cap(d, "C55", "100n", "+3V3_UI", "GND")
    d.add("D50", "LED:WS2812B-2020", "WS2812B-2020-V6", "LED_SMD:LED_WS2812B-2020_PLCC4_2.0x2.0mm",
          pins={"DIN": "RGB_DIN", "DOUT": None, "VDD": "+3V3_UI", "VSS": "GND"},
          fields={"MPN": "WS2812B-2020-V6", "Manufacturer": "Worldsemi", "LCSC": "C52917434"})
    res(d, "R55", "100k", "RGB_DIN", "GND")

    d.group("Piezo: Murata PKMCS0909E4000-R1 (4 kHz, external drive), low-side MOSFET on BUZZ (GPIO45)",
            "+3V3 -> BZ50 || R57 1k -> Q51 drain. LEDC square wave at ~4 kHz on the gate. R57 recharges the piezo\n"
            "while Q51 is off (3.3 mA only while Q51 conducts). R56 100k gate pull-down: GPIO45 is the VDD_SPI strap\n"
            "and must read 0 at reset (SPEC §5).")
    d.add("BZ50", "Device:Buzzer", "PKMCS0909E4000-R1", "Buzzer_Beeper:Buzzer_Murata_PKMCS0909E",
          pins={"1": "+3V3", "2": "BUZZ_D"},
          datasheet="https://www.murata.com/en-us/products/productdetail?partno=PKMCS0909E4000-R1",
          description="Murata 4 kHz SMD piezo sounder, external drive, 9x9x1.9 mm",
          fields={"MPN": "PKMCS0909E4000-R1", "Manufacturer": "Murata", "LCSC": "C910763"})
    res(d, "R57", "1k", "+3V3", "BUZZ_D")
    d.add("Q51", "Transistor_FET:AO3400A", "AO3400A", SOT23,
          pins={"G": "BUZZ", "D": "BUZZ_D", "S": "GND"}, fields=FET_FIELDS)
    res(d, "R56", "100k", "BUZZ", "GND")

    d.group("Test points", "")
    testpoints(d, 50, ["LCD_BL", "BUZZ"])
