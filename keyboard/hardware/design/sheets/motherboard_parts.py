"""Parts, generated symbols and footprints shared by the motherboard's sheets (sheets/mb_*.py).

Not a sheet module (it does not match the "mb_*" glob of sheets/__init__.py). Every part here is a **candidate**
unless SPEC.md fixes it; the SPEC §2.1 parts keep their LCSC codes. Stock and qty-1 price are from the JLC parts API
on 2026-11-27 (they change daily); "basic" = a JLC basic part, "pref" = a JLC preferred extended part.

Pinouts read in the datasheets on 2026-11-27 (TI's own PDFs from ti.com, or the copy JLC hosts for the C-number):

* TPS259474LRPWR (TI SLVSFC9C, May 2026, Table 5-1; RPW0010A VQFN-HR): 1 EN/UVLO, 2 OVLO, 3 PG, 4 PGTH, 5 IN,
  6 OUT, 7 DVDT, 8 GND, 9 ILM, 10 ITIMER. No KiCad symbol or footprint: generated here, the land pattern from
  RPW0010A's "Example board layout" (page 73): pads 2/3 and 8/9 0.6 x 0.25 at x -/+0.9, y -/+0.225; the corner pads
  1, 4, 7, 10 L-shaped (a 0.6 x 0.3 lead at y -/+0.70 plus a 0.25-wide arm at x -/+0.725 out to y -/+1.2); IN (5)
  and OUT (6) 0.3 x 2.4 bars at x -0.25 and +0.25. Overall 2.4 x 2.4 (1.8 between the lead centres).
* TPS2553DBVR (TI SLVS841G, Oct 2026, Table 5-1, DBV): 1 IN, 2 GND, 3 EN (active high), 4 FAULT (open drain, active
  low), 5 ILIM, 6 OUT. No KiCad symbol: generated; footprint Package_TO_SOT_SMD:SOT-23-6.
* SN74CBTLV3125PWR (TI SCDS037K, July 2026, Figure 4-1, PW): 1 1OE, 2 1A, 3 1B, 4 2OE, 5 2A, 6 2B, 7 GND, 8 3B,
  9 3A, 10 3OE, 11 4B, 12 4A, 13 4OE, 14 VCC; OE low = A port to B port, high = disconnect (Table 7-1). No KiCad
  symbol: generated; footprint Package_SO:TSSOP-14_4.4x5mm_P0.65mm.
* LDL1117S33R (ST DS, Table 1, SOT-223): 1 GND, 2 VOUT, 3 VIN, the tab is VOUT. Generated symbol; footprint
  Package_TO_SOT_SMD:SOT-223-3_TabPin2 (tab = pad 2). 1 uF in, 4.7 uF out (its §6.2 "suggested combination").
* TPD4E05U06DQAR (TI, DQA0010A): channels on 1, 2, 4, 5; GND 3 and 8; 6, 7, 9, 10 "Not connected; Used for
  optional straight-through routing. Can be left floating or grounded" (TI SLVSBO7O, Table 4-2, read 2026-11-28). The
  layout routes each line straight through its pin pair (1-10, 2-9, 4-7, 5-6), so the NC pins carry the line's net:
  in the generated box each is a hidden passive pin stacked under its partner (the layout task's capture change of
  2026-11-28: with the NC pads on no net, the USB pair could reach pads 1 and 2 only by crossing itself or through
  vias). KiCad's symbol Power_Protection:TPD4E05U06DQA has the same pins but prints their names outside its body,
  under the Value text, so a generated box with the same pin numbers draws it. KiCad's USON-10_2.5x1.0mm_P0.5mm is not
  TI's land (0.55 x 0.3 pads at x +/-0.385), so the footprint is generated from DQA0010A's "Example board layout":
  0.565 x 0.2 pads (3 and 8: 0.565 x 0.4) at x -/+0.4175, 0.5 mm pitch.
* TUSB320LAIRWBR (TI SLLSEQ8D, pin map = nets.TYPEC_PINS): KiCad's Interface_USB:TUSB320 has the same 12 pin
  numbers and functions. Footprint Package_DFN_QFN:Texas_X2QFN-12_1.6x1.6mm_P0.4mm: its pads have TI's inner
  edges (RWB "Example board layout": 0.2 x 0.5 / 0.7 x 0.2) and run 0.15 mm further out than TI's (a toe
  extension; noted, kept).
* INA226AIDGSR (TI SBOS547C, Aug 2026, Table 4-1, DGS): 1 A1, 2 A0, 3 Alert, 4 SDA, 5 SCL, 6 VS, 7 GND, 8 VBUS,
  9 IN-, 10 IN+; KiCad's Sensor_Energy:INA226 matches. Footprint Package_SO:TSSOP-10_3x3mm_P0.5mm (1.45 x 0.3
  pads at x +/-2.15; TI's DGS0010A land is 1.45 x 0.3 at +/-2.2). Addresses: Table 6-2 (A1, A0 = GND, VS, SDA, SCL).
* TCA9535PWR (TI SCPS201F) and TCA9548APWR (TI SCPS207H): KiCad's Interface_Expansion symbols match Table 4-1 of
  each. TCA9535: "If port is unused, it must be tied to either VCC or GND through a resistor of moderate value
  (about 10kΩ)".
* AP2112K-3.3TRG1 (Diodes DS39724, SOT25): 1 VIN, 2 GND, 3 EN, 4 NC, 5 VOUT (KiCad's symbol matches).
* X322516MLB4SI (YXC YSX321SL sheet): pads 1 and 3 the crystal, 2 and 4 GND; C0 3 pF max, ESR 50 Ohm max at
  16-31 MHz; land 1.4 x 1.2 at +/-1.1, +/-0.85 = KiCad's Crystal_SMD_3225-4Pin_3.2x2.5mm.
* Samtec FTSH-107-01-L-DV-K (J_SWD): the copy JLC hosts for C5307809 is the through-hole FTSH sheet, and samtec.com
  refused the download (HTTP 403), so the SMT land is KiCad's PinHeader_2x07_P1.27mm_Vertical_SMD (2.4 x 0.74 at
  x +/-1.95), **not checked against Samtec's drawing**.

Parts the owner's decisions of 2026-11-27 add (D2-D6; SPEC §1, §2.1; JLC API on 2026-11-27, about 23:20 UTC):

* **J_RIG and J_KVM, shrouded box headers (D5)**: BOOMELE 2.54-2*5P box header, C5665 (181339 in stock, $0.1035),
  and 2.54-2*6P, C9136 (26811, $0.1198); one family, "简牛2.54-2xnP" (BOOMELE drawing, read from the copy JLC
  hosts): body (n x 2.54 + 7.6) +/-0.5 by 9.0 mm (20.3 x 9.0 for 2 x 5, 22.84 x 9.0 for 2 x 6), 8.8 mm above the
  board, 0.64 mm square brass gold-plated posts, 2 x n holes of 1.0 mm on a 2.54 mm grid, 1 A, 220 C for 10 s.
  KiCad's Connector_IDC:IDC-Header_2x05/2x06_P2.54mm_Vertical match it: 1.0 mm drills, 1.7 mm pads, pin 1 at
  (0, 0) and pin 2 at (2.54, 0) (the odd row one column, as Conn_02x05_Odd_Even), body 9.0 x 20.46 / 23.0 mm on
  F.Fab, the key notch on the pin-1 side. Pinouts unchanged (nets.J_RIG_PINS, nets.J_KVM_PINS); pin 1 at the
  triangle. They replace the unshrouded CJT A2541WV-2x5P / 2x6P (C225520 / C225521) of SPEC §2.1.
* **D3 series resistors**: UNI-ROYAL 0402WGF1000TCE, 100 Ohm 1 % 0402, C25076 (JLC basic, 9011609).
* **U2's PGTH bottom resistor (D4)**: UNI-ROYAL 0402WGF4422TCE, 44.2 kOhm 1 % 0402, 100 ppm/K, C25895 (21741,
  $0.0017).
* **The +3V3A damping leg (D4)**: UNI-ROYAL 0603WAF470LT5E, 0.47 Ohm 1 % 0603, 100 mW, +/-800 ppm/K, C23411 (99709,
  $0.0051), and the board's 10 uF 25 V X5R 0805, C15850 (basic, 9303473).
* **Kelvin sense (D4)**: every INA226's IN+ / IN- sit on its own sense pair (nets.ina226_sense_nets()), each joined to
  the shunt's power net by a net tie at the shunt's pad: KiCad's Device:NetTie_2 symbol (not in the BOM) and
  NetTie:NetTie-2_SMD_Pad0.5mm footprint (two 0.5 mm round pads 1.0 mm apart, bridged by copper, net_tie_pad_groups
  "1, 2", excluded from the BOM and the position file). Refs NT<aa>P (IN+ side) and NT<aa>N (IN- side), aa the
  INA226's address in hex. No 4-terminal shunt is used: the shunts stay stock 2-pad parts.
* **The slot key (D2)**: no key plug or 2 x 20 socket without contact 39 found at JLC (searches on 2026-11-27 by the
  decisions agent, and again here: "polarization key", "coding pin", "keying plug", "blanking plug 2.54",
  "polarizing plug", "female header key"), so socket pin 39 keeps its pad with no net and its hole is plugged by
  hand: an assembly note (SPEC §4.2).
"""

import nets
from sheets import parts as P

# ---------------------------------------------------------------------------------------------- refs
# SPEC names where SPEC gives one (U2-U5, U_CC, U_EXP1-3, U_MUX, U_BSn, J_SWD, J_RIG, J_KVM, JP_3V3_Sn, JP_INJn),
# and in the same style: U1 the MCU, U_PM<addr> the INA226 at that I2C address, U_3V3_Sn / U_5V_Sn / U_5V_KVM the
# TPS2553 switches, J_Sn the slot sockets, U_ESD the USB ESD array. The other refs are numbered by sheet: usb 1-29,
# power 30-99, mcu 100-199, io 200-299, headers 300-399, slot n 100 n + 400 (S1 500-599 ... S5 900-999).
MCU_REF = "U1"
INA_REF = {a: f"U_PM{a:02X}" for a in nets.INA226_RAILS}      # U_PM40 ... U_PM4D (the INA226 at that address)
SLOT_BASE = {n: 100 * n + 400 for n in nets.SLOTS}


def ina_ref(addr):
    return INA_REF[addr]


# ---------------------------------------------------------------------------------------------- passives
R0402, R0603, R0805, R1206 = P.R0402, P.R0603, "Resistor_SMD:R_0805_2012Metric", "Resistor_SMD:R_1206_3216Metric"
C0402, C0603, C0805, C1206 = P.C0402, P.C0603, P.C0805, "Capacitor_SMD:C_1206_3216Metric"
UNIROYAL, FH, YAGEO, SAMSUNG = P.UNIROYAL, P.FH, "YAGEO", P.SAMSUNG

# key -> (MPN, Manufacturer, LCSC, footprint, value shown). JLC API 2026-11-27: stock, qty-1 $.
RES = {k: (*v, k.split(" ")[0]) for k, v in P.RES.items()}
RES.update({
    # shunts (SPEC §3.4): low-TCR current-sense parts
    "20m": ("LR1206-21R020F4", "RALEC", "C154638", R1206, "20m"),            # 1 W alloy, 50 ppm/K; 3346, $0.107
    "0.1": ("HP05W3F100LT5E", UNIROYAL, "C270842", R0805, "0.1"),            # 1/3 W, 100 ppm/K; 2661, $0.033
    "0.24": ("HP05W3F240LT5E", UNIROYAL, "C7434086", R0805, "0.24"),         # 1/3 W, 100 ppm/K; 5165, $0.024
    "0.5": ("HP03W5F500LT5E", UNIROYAL, "C414986", R0603, "0.5"),            # 1/5 W, 100 ppm/K; 9064, $0.036
    "1R": ("HP03W5F100KT5E", UNIROYAL, "C2759448", R0603, "1"),              # 1/5 W, 100 ppm/K; 34538, $0.008
    # 1 % set resistors
    "90.9k": ("0402WGF9092TCE", UNIROYAL, "C26989", R0402, "90.9k"),         # TPS2553 3.3 V R_ILIM; 396726
    "45.3k": ("0402WGF4532TCE", UNIROYAL, "C26980", R0402, "45.3k"),         # TPS2553 5 V R_ILIM; 77444
    "1.47k": ("AC0402FR-071K47L", YAGEO, "C226852", R0402, "1.47k"),         # U5 R_ILM; 8389
    "383k": ("0402WGF3833TCE", UNIROYAL, "C45993", R0402, "383k"),           # U2 OVLO divider; 19755
    "39k": ("0402WGF3902TCE", UNIROYAL, "C25783", R0402, "39k"),             # pref; 498437
    "887k": ("ERJ2RKF8873X", "Panasonic", "C409935", R0402, "887k"),         # U_CC VBUS_DET; 100 V, 55629
    "200k": ("0402WGF2003TCE", UNIROYAL, "C25764", R0402, "200k"),           # basic; 3072202
    "33": ("0402WGF330JTCE", UNIROYAL, "C25105", R0402, "33"),               # basic; 3979677
    # the owner's decisions of 2026-11-27 (JLC 2026-11-27 ~23:20 UTC); "100" (C25076, basic) comes from parts.RES
    "44.2k": ("0402WGF4422TCE", UNIROYAL, "C25895", R0402, "44.2k"),         # U2 PGTH bottom (D4); 21741, $0.0017
    "0.47": ("0603WAF470LT5E", UNIROYAL, "C23411", R0603, "0.47"),           # +3V3A damping leg (D4); 99709, $0.0051
})

CAP = {k: (*v, k.split("/")[0].split(" ")[0]) for k, v in P.CAP.items()}
CAP.update({
    "1n C0G": ("0402CG102J500NT", FH, "C53547", C0402, "1n"),                # lane RC, 50 V C0G; 383338, $0.005
    "10p C0G": ("0402CG100J500NT", FH, "C1545", C0402, "10p"),               # HSE load; 170909, $0.005
    "2.2n": ("0402B222K500NT", FH, "C1531", C0402, "2.2n"),                  # pref, 50 V X7R; 726651
    "4.7n/1kV": ("1206B472K102NT", FH, "C9192", C1206, "4.7n"),              # shield RC, 1 kV X7R; 232123, $0.019
    "4.7u/25V": ("CL21A475KAQNNNE", SAMSUNG, "C1779", C0805, "4.7u"),        # basic, 25 V X5R; 2547152
    "10u/25V": ("CL21A106KAYNNNE", SAMSUNG, "C15850", C0805, "10u"),         # basic, 25 V X5R; 9116083
})


def _f(mpn, mfr, lcsc):
    return {"MPN": mpn, "Manufacturer": mfr, "LCSC": lcsc}


def res(d, ref, value, a, b, **kw):
    """A resistor from RES (this module's table: parts.RES plus the motherboard values) between nets a and b."""
    mpn, mfr, lcsc, fp, shown = RES[value]
    return d.add(ref, "Device:R", shown, fp, pins={"1": a, "2": b}, fields=_f(mpn, mfr, lcsc), **kw)


def cap(d, ref, value, a, b, **kw):
    """A capacitor from CAP between nets a (pin 1) and b (pin 2); near="U1.11" ties a decoupling cap to its pin."""
    mpn, mfr, lcsc, fp, shown = CAP[value]
    return d.add(ref, "Device:C", shown, fp, pins={"1": a, "2": b}, fields=_f(mpn, mfr, lcsc), **kw)


def testpoints(d, refs_nets):
    """[(ref, net)]: one probe pad each (not in the BOM)."""
    for ref, net in refs_nets:
        d.add(ref, "Connector:TestPoint", net, P.TP, pins={"1": net}, in_bom=False)


def power_flags(d, start, nets_):
    for i, net in enumerate(nets_, start=start):
        d.add(f"#FLG{i:02d}", "power:PWR_FLAG", "PWR_FLAG", "", pins={"1": net}, in_bom=False, on_board=False, rot=90)


# ---------------------------------------------------------------------------------------------- ICs and modules
TI = "Texas Instruments"
DS = {
    "TPS25947": "https://www.ti.com/lit/ds/symlink/tps25947.pdf",
    "TPS2553": "https://www.ti.com/lit/ds/symlink/tps2553.pdf",
    "INA226": "https://www.ti.com/lit/ds/symlink/ina226.pdf",
    "TCA9535": "https://www.ti.com/lit/ds/symlink/tca9535.pdf",
    "TCA9548A": "https://www.ti.com/lit/ds/symlink/tca9548a.pdf",
    "CBTLV3125": "https://www.ti.com/lit/ds/symlink/sn74cbtlv3125.pdf",
    "TUSB320LAI": "https://www.ti.com/lit/ds/symlink/tusb320lai.pdf",
    "TPD4E05U06": "https://www.ti.com/lit/ds/symlink/tpd4e05u06.pdf",
    "LDL1117": "https://www.st.com/resource/en/datasheet/ldl1117.pdf",
    "AP2112": "https://www.diodes.com/assets/Datasheets/AP2112.pdf",
}
PART = {   # SPEC §2.1 candidates (JLC 2026-11-27: stock, qty-1 $) and the parts this capture adds
    "MCU": _f("STM32U5A5VJT6", "STMicroelectronics", "C22455480"),       # 13, $19.10 (SPEC §1: reserve them)
    "TPS259474L": _f("TPS259474LRPWR", TI, "C2864845"),                  # 5790, $1.349
    "TPS2553": _f("TPS2553DBVR", TI, "C55266"),                          # 40382, $0.541
    "INA226": _f("INA226AIDGSR", TI, "C49851"),                          # 37646, $0.669
    "TCA9548A": _f("TCA9548APWR", TI, "C130026"),                        # 14604, $0.864
    "TCA9535": _f("TCA9535PWR", TI, "C130204"),                          # 11766, $1.283
    "CBTLV3125": _f("SN74CBTLV3125PWR", TI, "C406866"),                  # 1101, $0.544 (SPEC §11 #19)
    "AP2112K": _f("AP2112K-3.3TRG1", "Diodes Incorporated", "C51118"),   # 7887, $0.167
    "LDL1117": _f("LDL1117S33R", "STMicroelectronics", "C435835"),       # 43225, $0.488
    "XTAL": _f("X322516MLB4SI", "YXC Crystal Oscillators", "C13738"),    # basic, 399168, $0.088
    "USBC": _f("TYPE-C-31-M-12", "Korean Hroparts Elec", "C165948"),     # 402618, $0.187
    "TUSB320LAI": _f("TUSB320LAIRWBR", TI, "C132554"),                   # 4328, $1.308
    "TPD4E05U06": _f("TPD4E05U06DQAR", TI, "C138714"),                   # 28431, $0.084
    "SMF5.0A": _f("SMF5.0A", "Littelfuse", "C151296"),                   # 54967, $0.118
    "FERRITE": _f("BLM18PG221SN1D", "Murata Electronics", "C80165"),     # 164426, $0.015
    "SOCKET": _f("2.54-2*20P", "BOOMELE(Boom Precision Elec)", "C5124634"),   # 6382, $0.331
    "STDC14": _f("FTSH-107-01-L-DV-K", "Samtec", "C5307809"),            # 2369, $3.70
    # shrouded box headers (D5 of 2026-11-27); JLC lists the model with its description appended
    "HDR2x5": _f("2.54-2*5P", "BOOMELE(Boom Precision Elec)", "C5665"),      # box header; 181339, $0.1035
    "HDR2x6": _f("2.54-2*6P", "BOOMELE(Boom Precision Elec)", "C9136"),      # box header; 26811, $0.1198
    "HDR1x2": _f("HX PZ2.54-1x2P ZZ", "hanxia", "C32713268"),           # 119580, $0.016
    "BUTTON": _f("TS-1088-AR02016", "XUNPU", "C720477"),                 # basic, 698717, $0.051 (the caliper's)
}

FP = {
    "RPW": "keyboard:TI_RPW0010A_VQFN-HR-10_2x2mm_P0.5mm",
    "DQA": "keyboard:TI_DQA0010A_USON-10_2.5x1.0mm_P0.5mm",
    "SOT23_6": "Package_TO_SOT_SMD:SOT-23-6",
    "SOT23_5": "Package_TO_SOT_SMD:SOT-23-5",
    "SOT223": "Package_TO_SOT_SMD:SOT-223-3_TabPin2",
    "TSSOP10": "Package_SO:TSSOP-10_3x3mm_P0.5mm",
    "TSSOP14": "Package_SO:TSSOP-14_4.4x5mm_P0.65mm",
    "TSSOP24": "Package_SO:TSSOP-24_4.4x7.8mm_P0.65mm",
    "X2QFN12": "Package_DFN_QFN:Texas_X2QFN-12_1.6x1.6mm_P0.4mm",
    "LQFP100": "Package_QFP:LQFP-100_14x14mm_P0.5mm",
    "XTAL": "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm",
    "SOCKET": "Connector_PinSocket_2.54mm:PinSocket_2x20_P2.54mm_Vertical",
    "STDC14": "Connector_PinHeader_1.27mm:PinHeader_2x07_P1.27mm_Vertical_SMD",
    "HDR2x5": "Connector_IDC:IDC-Header_2x05_P2.54mm_Vertical",
    "HDR2x6": "Connector_IDC:IDC-Header_2x06_P2.54mm_Vertical",
    "NETTIE": "NetTie:NetTie-2_SMD_Pad0.5mm",
    "HDR1x2": "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
    "BUTTON": "Button_Switch_SMD:SW_SPST_TS-1088-xR020",
    "FERRITE": "Inductor_SMD:L_0603_1608Metric",
    "SMF": "Diode_SMD:D_SMF",
    "USBC": "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12",
    # rectangular pads, not the RoundedPad variant: tools/finish_route.py rasterises a custom-shape pad a little
    # larger than its copper, so a route could end beside it, unjoined (RIG_INJ at JP_INJ5, layout of 2026-11-28)
    "SJ": "Jumper:SolderJumper-2_P1.3mm_Open_Pad1.0x1.5mm",
}

SYMBOLS = [
    dict(name="TPS259474LRPW", ref="U", footprint=FP["RPW"], datasheet=DS["TPS25947"],
         description="2.7-23 V, 5.5 A, 28 mOhm eFuse, circuit breaker (latch-off), adjustable OVLO, power good, "
                     "true reverse-current blocking, VQFN-HR-10 2 x 2 mm (RPW)",
         keywords="efuse circuit breaker hot swap TI",
         pins=[(5, "IN", "power_in", "L"), (1, "EN/UVLO", "input", "L"), (2, "OVLO", "input", "L"),
               (7, "DVDT", "passive", "L"),
               (6, "OUT", "power_out", "R"), (3, "PG", "open_collector", "R"), (4, "PGTH", "input", "R"),
               (9, "ILM", "passive", "B"), (10, "ITIMER", "passive", "B"), (8, "GND", "power_in", "B")]),
    dict(name="TPS2553DBV", ref="U", footprint=FP["SOT23_6"], datasheet=DS["TPS2553"],
         description="Current-limited power switch, 2.5-6.5 V, 85 mOhm, adjustable limit 75-1300 mA, active-high "
                     "enable, open-drain fault, SOT-23-6",
         keywords="load switch current limit USB power TI",
         pins=[(1, "IN", "power_in", "L"), (3, "EN", "input", "L"),
               (6, "OUT", "power_out", "R"), (4, "~{FAULT}", "open_collector", "R"),
               (5, "ILIM", "passive", "B"), (2, "GND", "power_in", "B")]),
    dict(name="SN74CBTLV3125PW", ref="U", footprint=FP["TSSOP14"], datasheet=DS["CBTLV3125"],
         description="Quad FET bus switch, 2.3-3.6 V, 7 Ohm, Ioff, individual active-low OE, TSSOP-14",
         keywords="bus switch FET quad TI",
         pins=[(2, "1A", "passive", "L"), (5, "2A", "passive", "L"), (9, "3A", "passive", "L"),
               (12, "4A", "passive", "L"),
               (1, "~{1OE}", "input", "L"), (4, "~{2OE}", "input", "L"), (10, "~{3OE}", "input", "L"),
               (13, "~{4OE}", "input", "L"),
               (3, "1B", "passive", "R"), (6, "2B", "passive", "R"), (8, "3B", "passive", "R"),
               (11, "4B", "passive", "R"),
               (14, "VCC", "power_in", "T"), (7, "GND", "power_in", "B")]),
    # KiCad's Power_Protection:TPD4E05U06DQA prints its pin names outside the body, where every Value text lands on
    # them; this box keeps the same pins with the names inside (pin numbers as TI's DQA0010A).
    # The NC pins 10, 9, 7, 6 (not connected inside) are hidden passive pins stacked under 1, 2, 4, 5: the board
    # routes each line straight through its pin pair (TI's "optional straight-through routing", Table 4-2).
    dict(name="TPD4E05U06DQA", ref="U", footprint=FP["DQA"], datasheet=DS["TPD4E05U06"],
         description="4-channel ESD protection, 0.5 pF, 5.5 V, flow-through USON-10 (DQA): IO on 1, 2, 4, 5; "
                     "6, 7, 9, 10 not connected inside, used for straight-through routing (stacked here)",
         keywords="ESD TVS USB TI",
         pins=[(1, "D1+", "passive", "L"), (10, "D1+", "passive", "L"), (2, "D1-", "passive", "L"),
               (9, "D1-", "passive", "L"), (4, "D2+", "passive", "L"), (7, "D2+", "passive", "L"),
               (5, "D2-", "passive", "L"), (6, "D2-", "passive", "L"),
               (3, "GND", "power_in", "B"), (8, "GND", "passive", "B")]),
    dict(name="LDL1117S33R", ref="U", footprint=FP["SOT223"], datasheet=DS["LDL1117"],
         description="1.2 A low-dropout regulator, 3.3 V fixed, 60 uVrms, SOT-223 (tab = VOUT)",
         keywords="LDO regulator 3.3V ST",
         pins=[(3, "VIN", "power_in", "L"), (2, "VOUT", "power_out", "R"), (1, "GND", "power_in", "B")]),
]


def footprints(fpgen, lib_dir):
    """The two TI land patterns KiCad lacks (see the module docstring for the dimensions' source)."""
    pcbnew = fpgen.pcbnew
    name = FP["RPW"].split(":")[1]
    fp = fpgen.Footprint(name, "TI RPW0010A VQFN-HR-10, 2 x 2 mm, 0.5 mm pitch (TPS25947xxRPW). Land pattern from "
                         "TI's RPW0010A 'Example board layout' (SLVSFC9C p. 73): L-shaped corner pads 1, 4, 7, 10, "
                         "IN (5) and OUT (6) bars 0.3 x 2.4. " + DS["TPS25947"], "VQFN-HR RPW0010A TPS25947 eFuse")
    for num, sx, sy in (("1", -1, -1), ("4", -1, 1), ("10", 1, -1), ("7", 1, 1)):
        fp.smd(num, sx * 0.9, sy * 0.70, 0.6, 0.3)                # the lead
        fp.smd(num, sx * 0.725, sy * 1.0, 0.25, 0.4)               # the arm to the package edge (overlaps)
    for num, sx, sy in (("2", -1, -1), ("3", -1, 1), ("9", 1, -1), ("8", 1, 1)):
        fp.smd(num, sx * 0.9, sy * 0.225, 0.6, 0.25)
    fp.smd("5", -0.25, 0.0, 0.3, 2.4)
    fp.smd("6", 0.25, 0.0, 0.3, 2.4)
    fp.fab_rect(-1.0, -1.0, 1.0, 1.0)
    fp.line(pcbnew.F_Fab, -1.0, -0.6, -0.6, -1.0, 0.1)
    fp.pin1_dot(-1.5, -0.95)
    fp.courtyard_rect(-1.45, -1.45, 1.45, 1.45)
    fp.save(lib_dir)

    name = FP["DQA"].split(":")[1]
    fp = fpgen.Footprint(name, "TI DQA0010A USON-10, 2.5 x 1.0 mm, 0.5 mm pitch (TPD4E05U06DQA). Land pattern from "
                         "TI's DQA0010A 'Example board layout': 0.565 x 0.2 pads (3 and 8: 0.565 x 0.4) at "
                         "x -/+0.4175. " + DS["TPD4E05U06"], "USON DQA0010A TPD4E05U06 ESD")
    for i in range(5):
        y = -1.0 + 0.5 * i
        h = 0.4 if i == 2 else 0.2
        fp.smd(str(i + 1), -0.4175, y, 0.565, h)
        fp.smd(str(10 - i), 0.4175, y, 0.565, h)
    fp.fab_rect(-0.5, -1.25, 0.5, 1.25)
    fp.line(pcbnew.F_Fab, -0.5, -1.0, -0.25, -1.25, 0.1)
    fp.pin1_dot(-0.95, -1.35)
    fp.courtyard_rect(-1.0, -1.5, 1.0, 1.5)
    fp.save(lib_dir)


# ---------------------------------------------------------------------------------------------- nets
def slot_local_nets(n):
    """Slot n's nets that stay on its own sheet: the socket side of the lanes and of the bus switch, and INJ."""
    return {f"S{n}_AN{k}" for k in range(4)} | {f"S{n}_{s}" for s in ("SCK", "MISO", "MOSI", "SYNC", "INJ")}


_LOCAL = set().union(*(slot_local_nets(n) for n in nets.SLOTS))
# Drawn with global labels in every build (also a partial --only build): the contract's intersheet nets and every
# slot net that leaves its slot sheet (the MCU side of the lanes, G-lines, CS, IRQ, I2C channel, PRESENT_N).
INTERSHEET = list(nets.MOTHERBOARD_INTERSHEET) + [x for x in nets.SLOT_NETS if x not in _LOCAL]
POWER_NETS = list(nets.POWER_NETS)


def net_tie(d, ref, a, b, **kw):
    """A net tie (KiCad Device:NetTie_2, not in the BOM) joining net a (pin 1) to net b (pin 2) at one point."""
    return d.add(ref, "Device:NetTie_2", "Kelvin", FP["NETTIE"], pins={"1": a, "2": b}, in_bom=False,
                 description="Net tie: the Kelvin sense connection at a shunt's pad (not a BOM part)", **kw)


def ina226(d, addr, shunt_p, shunt_m, vbus, ref=None, **kw):
    """An INA226 at nets.INA226_RAILS[addr], A1/A0 strapped per its Table 6-2, on I2C1 with its ALERT on PM_ALERT_N,
    Kelvin-sensed (owner's decision D4, 2026-11-27; SPEC §7.5): IN+ (pin 10) and IN- (pin 9) sit on the monitor's own
    sense pair (nets.ina226_sense_nets(addr)), joined to the shunt's power nets shunt_p / shunt_m (which must be
    nets.INA226_SHUNT_NETS[addr]) by the net ties NT<aa>P and NT<aa>N at the shunt's pads."""
    if (shunt_p, shunt_m) != nets.INA226_SHUNT_NETS[addr]:
        raise ValueError(f"INA226 0x{addr:02X}: shunt nets {(shunt_p, shunt_m)} != nets.INA226_SHUNT_NETS "
                         f"{nets.INA226_SHUNT_NETS[addr]}")
    strap = ("GND", "+3V3", "I2C_PM_SDA", "I2C_PM_SCL")             # GND, VS, SDA, SCL
    k = addr - 0x40
    a1, a0 = strap[k // 4], strap[k % 4]
    sense_p, sense_m = nets.ina226_sense_nets(addr)
    part = d.add(ref or ina_ref(addr), "Sensor_Energy:INA226", "INA226", FP["TSSOP10"],
                 pins={"1": a1, "2": a0, "3": "PM_ALERT_N", "4": "I2C_PM_SDA", "5": "I2C_PM_SCL", "6": "+3V3",
                       "7": "GND", "8": vbus, "9": sense_m, "10": sense_p},
                 datasheet=DS["INA226"], fields=dict(PART["INA226"]), **kw)
    net_tie(d, kelvin_ref(addr, "P"), shunt_p, sense_p)
    net_tie(d, kelvin_ref(addr, "N"), shunt_m, sense_m)
    return part


def kelvin_ref(addr, side):
    """The net tie of INA226 `addr` on its IN+ ("P") or IN- ("N") side: NT40P ... (short, so that its reference fits
    beside the tie on the drawing)."""
    return f"NT{addr:02X}{side}"


def tps2553(d, ref, vin, en, out, ilim_net, **kw):
    return d.add(ref, "keyboard:TPS2553DBV", "TPS2553DBVR", FP["SOT23_6"],
                 pins={"1": vin, "2": "GND", "3": en, "4": "SLOT_FAULT_N", "5": ilim_net, "6": out},
                 datasheet=DS["TPS2553"], fields=dict(PART["TPS2553"]), **kw)


def tps259474(d, ref, vin, out, en, ovlo, pg, pgth, dvdt, ilm, itimer, **kw):
    return d.add(ref, "keyboard:TPS259474LRPW", "TPS259474LRPWR", FP["RPW"],
                 pins={"5": vin, "6": out, "1": en, "2": ovlo, "3": pg, "4": pgth, "7": dvdt, "8": "GND",
                       "9": ilm, "10": itimer},
                 datasheet=DS["TPS25947"], fields=dict(PART["TPS259474L"]), **kw)


def button(d, ref, value, a, b, description):
    return d.add(ref, "Switch:SW_Push", value, FP["BUTTON"], pins={"1": a, "2": b},
                 datasheet="https://www.lcsc.com/datasheet/C720477.pdf", description=description,
                 fields=dict(PART["BUTTON"]))


def led(d, ref, anode, cathode, **kw):
    return P.led_red(d, ref, anode, cathode, **kw)
