"""What every rev A coupon carries (SPEC §2, §4.1-§4.6, §4.9, §9): the slot sheet.

    from sheets import coupon_common as cc
    POWER_NETS, INTERSHEET = cc.POWER_NETS, cc.INTERSHEET
    def build(d):
        cc.slot_sheet(d, unused=("INJ", "SYNC"), rails=("+3V3",))   # the slot header, EEPROM, post, fiducials
        d.sheet("sensors", "sensors.kicad_sch", "...")              # the coupon's own sheets; refs from 10 up
        ...

The coupon side of the slot (nets as the coupon sees them):

* **J1, the male 2 x 20 header, 2.54 mm** (owner's decision D2), pin for pin `nets.SLOT_PINS`. On the coupon the nets
  are slot-local: `+5V`, `+3V3`, `GND` and the signal names (`AN0` ... `G5`); PRESENT_N (pin 32) is **strapped to
  GND** (a strap, not a resistor: SPEC §4.6) and RSV (pin 39) is not connected. A signal the coupon does not use is
  passed in `unused` and its pin left unconnected (no-connect flag), so it never becomes a one-pin net.
  Part (a candidate, SPEC §2.1): HanElectricity 2541WV-2x20P (LCSC C25503140; 1516 in stock at JLC, $0.138 on
  2026-11-27): 2 x 20, 2.54 mm pitch and row spacing, 0.64 mm square brass pins, gold, 6.00 mm mating length,
  2.54 mm plastic, 3.0 mm tail, Ø1.0 mm PCB holes (its drawing 2541WV-2xXXP, rev A 2015-05-03), so KiCad's
  `PinHeader_2x20_P2.54mm_Vertical` (Ø1.0 drill, 1.7 mm pad) is its land. **It is mounted on the coupon's bottom
  side**, body down, pins down into the motherboard socket (SPEC §9: coupon underside 11 mm above the motherboard =
  8.5 mm socket + the header's 2.54 mm plastic). The motherboard's socket and the mating check are in
  boards/coupon_common.py.
* **U1, the descriptor EEPROM**, 2 kbit at 0x50 on the slot's own I2C channel (SPEC §4.5, §4.6): ST M24C02-WMN6TP
  (LCSC C7562, 216,993 in stock at JLC, $0.125 on 2026-11-27; the SPEC's candidate). SO8N pinout from ST's datasheet
  (DocID024020 Rev 2, Figure 2): 1 E0, 2 E1, 3 E2, 4 VSS, 5 SDA, 6 SCL, 7 WC, 8 VCC; KiCad's
  `Memory_EEPROM:M24C02-WMN` has the same numbers. E2-E0 to GND: device select 1010 000 = 0x50 (Table 2). VCC from
  the slot's +3V3 (2.5-5.5 V for the -W grade), 100 nF at pin 8 (§2.6.1: "10 nF to 100 nF close to the VCC/VSS
  pins"). **No SCL/SDA pull-ups on the coupon**: the slot's 4.7 k pull-ups to +3V3_Sn sit on the motherboard
  (SPEC §3.3, §4.2, nets.SLOT_PATH), and a coupon pulls up to nothing but its own +3V3 (SPEC §4.9).
* **Write control (WC)**: "Write operations are enabled when WC is either driven low or left floating" and inhibited
  when it is high (§2.4); its input impedance is 15-70 kOhm below 0.3 VCC and over 500 kOhm above 0.7 VCC
  (Table 10). Default here: **writable**, WC held low by 100 k (R1), so the bench firmware can write the descriptor
  that compiler v0 generates (SPEC §4.6); **bridge JP1 (WC to +3V3) to write-protect** it once written. Bridged,
  R1 costs 33 uA on the coupon's +3V3. `wp="gnd"` ties WC to GND instead (always writable), `wp=<net>` drives it
  from a coupon net (a spare G-line, say).
* **Bulk capacitance** at the header: 10 uF on +3V3 (C1) and 22 uF / 25 V on +5V (C2), inside the coupon rules'
  47 uF and 100 uF (SPEC §4.9).
* **Wire pads** TP1 +3V3, TP2 +5V, TP3/TP4 GND (Ø2.0 mm pad, Ø1.0 mm drill): an external meter or electronic load
  can be soldered or clipped on (bring-up, SPEC §10).
* **H1, the M3 support post** (SPEC §9: one M3 x 11 mm nylon spacer at the corner opposite the header): an unplated
  Ø3.2 mm hole; its position is in boards/coupon_common.py. **FID1-FID3**: fiducials on the top side, as the caliper.

Reference designators 1-9 (J1, U1, C1-C3, R1, JP1, TP1-TP4, H1, FID1-FID3, #FLG01-#FLG03) belong to this sheet;
a coupon's own parts start at 10.
"""

import nets
from sheets.parts import TP_WIRE, cap, fiducials, mounting_hole, power_flags, res, testpoints

POWER_NETS = ["GND", "+3V3", "+5V"]
# every slot signal the coupon can use, by its slot-local name (PRESENT_N is a GND strap, RSV not connected)
SIGNALS = [s for s in nets.SLOT_SIGNALS if s != "PRESENT_N"]
INTERSHEET = list(SIGNALS)

HEADER = {"ref": "J1", "symbol": "Connector_Generic:Conn_02x20_Odd_Even",
          "footprint": "Connector_PinHeader_2.54mm:PinHeader_2x20_P2.54mm_Vertical",
          "fields": {"MPN": "2541WV-2x20P", "Manufacturer": "HanElectricity", "LCSC": "C25503140"},
          "datasheet": "https://www.lcsc.com/datasheet/lcsc_datasheet_2407041454_HanElectricity-2541WV-2x20P_C25503140.pdf",
          "description": "Pin header, male, 2 x 20, 2.54 mm, vertical, through hole, 6.0 mm mating, 2.54 mm plastic, "
                         "3.0 mm tail; mounted on the coupon's bottom side"}
EEPROM = {"ref": "U1", "symbol": "Memory_EEPROM:M24C02-WMN", "footprint": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
          "fields": {"MPN": "M24C02-WMN6TP", "Manufacturer": "STMicroelectronics", "LCSC": "C7562"},
          "datasheet": "https://www.lcsc.com/datasheet/lcsc_datasheet_1809061818_STMicroelectronics-M24C02-WMN6TP_C7562.pdf"}
EEPROM_ADDR = 0x50
REFS = {"header": "J1", "eeprom": "U1", "hole": "H1", "fiducials": ("FID1", "FID2", "FID3"),
        "wire_pads": ("TP1", "TP2", "TP3", "TP4")}


def coupon_net(signal):
    """The coupon-side net of a slot-local signal: '+5V', '+3V3', 'GND', None (RSV) or the signal's own name."""
    if signal in ("GND", "PRESENT_N"):           # PRESENT_N: tied to GND on every coupon (SPEC §4.6)
        return "GND"
    if signal == "RSV":
        return None
    return signal


def header_pins(unused=(), rails=("+3V3", "+5V")):
    """J1 pin number -> coupon net (None = not connected), from nets.SLOT_PINS."""
    bad = set(unused) - set(SIGNALS)
    if bad:
        raise ValueError(f"unused: {sorted(bad)} are not slot signals (PRESENT_N is always strapped to GND)")
    out = {}
    for pin, sig, _dir, _note in nets.SLOT_PINS:
        net = coupon_net(sig)
        if sig in unused or (sig in ("+3V3", "+5V") and sig not in rails):
            net = None
        out[str(pin)] = net
    return out


def slot_sheet(d, unused=(), rails=("+3V3", "+5V"), wp="jumper", bulk_3v3="10u", bulk_5v="22u/25V",
               wire_pads=True, hole=True):
    """Draw the slot sheet every coupon carries. Returns the J1 pin map."""
    d.sheet("slot", "slot.kicad_sch", "Slot header, descriptor EEPROM, mounting")
    pins = header_pins(unused, rails)

    d.group("J1: slot header, male 2 x 20, 2.54 mm (on the BOTTOM side)",
            "Pinout = keyboard/hardware/design/nets.py SLOT_PINS (SPEC §4.2), seen from the coupon: odd pins one row,\n"
            "even pins the other; a GND opposite every lane. PRESENT_N (32) is strapped to GND, RSV (39) is open.\n"
            "Mounted on the bottom, pins down into the motherboard's 8.5 mm socket (SPEC §9). Not hot-plugged.",
            anchor="J1")
    d.add(HEADER["ref"], HEADER["symbol"], "SLOT", HEADER["footprint"], pins=pins, datasheet=HEADER["datasheet"],
          description=HEADER["description"], fields=dict(HEADER["fields"]))
    if "+3V3" in rails and bulk_3v3:
        cap(d, "C1", bulk_3v3, "+3V3", "GND", near="J1.7")
    if "+5V" in rails and bulk_5v:
        cap(d, "C2", bulk_5v, "+5V", "GND", near="J1.1")

    d.group(f"U1: descriptor EEPROM, M24C02 at 0x{EEPROM_ADDR:02X} (slot I2C channel)",
            "E2-E0 = GND -> 0x50 (SPEC §4.6). Powered from the slot's +3V3; no pull-ups here (4.7k on the motherboard).\n"
            + ("WC: 100k to GND = writable; bridge JP1 (WC to +3V3) to write-protect the descriptor once written."
               if wp == "jumper" else f"WC = {wp}."), anchor="U1")
    wc = {"jumper": "EE_WC", "gnd": "GND"}.get(wp, wp)
    d.add(EEPROM["ref"], EEPROM["symbol"], "M24C02-WMN6TP", EEPROM["footprint"],
          pins={"E0": "GND", "E1": "GND", "E2": "GND", "VSS": "GND", "VCC": "+3V3", "SDA": "SDA", "SCL": "SCL",
                "~{WC}": wc},
          datasheet=EEPROM["datasheet"], fields=dict(EEPROM["fields"]))
    cap(d, "C3", "100n", "+3V3", "GND", near="U1.8")
    if wp == "jumper":
        res(d, "R1", "100k", "EE_WC", "GND")
        d.add("JP1", "Jumper:SolderJumper_2_Open", "WP", "Jumper:SolderJumper-2_P1.3mm_Open_RoundedPad1.0x1.5mm",
              pins={"1": "EE_WC", "2": "+3V3"}, in_bom=False,
              description="Solder jumper, open: bridge to write-protect the descriptor EEPROM")

    if wire_pads:
        d.group("Wire pads: rails and ground",
                "For an external meter or an electronic load at bring-up (SPEC §10), e.g. the S5 breaker's 2 A trip.")
        testpoints(d, 1, [r for r in ("+3V3", "+5V") if r in rails] + ["GND", "GND"], fp=TP_WIRE)

    d.group("Mounting post and fiducials",
            "H1: M3 support post (one M3 x 11 mm nylon spacer, SPEC §9), unplated. FID1-FID3: top-side fiducials.")
    if hole:
        mounting_hole(d, "H1", "M3")
    fiducials(d, REFS["fiducials"])

    d.group("Power flags", "The slot rails and GND come from the motherboard through J1.")
    power_flags(d, list(rails) + ["GND"])
    return pins
