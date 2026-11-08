# Schematics and boards

> **Status: rev A schematics captured, ERC clean (2 waived, listed below). Designed, not built or tested.**
> The boards are not laid out in this page's revision; layout, DRC and the fab outputs are added by the layout track.
> Every current, voltage and part choice here is a datasheet or catalogue figure, not a measurement.

The architecture of record is [SPEC](../hardware/design/SPEC.md); the net names, the ESP32 pin map and the I2C
addresses are in [`nets.py`](https://github.com/tyevco/prettycoolboards/blob/main/caliper/hardware/design/nets.py).
Why the big parts were chosen (and what lost) is in [Architecture](architecture.md).

## 1. How the schematic is made

The KiCad 9 projects are **generated from Python**, with the same toolchain as dial-me-spinner (vendored in
[`tools/`](https://github.com/tyevco/prettycoolboards/tree/main/tools)):

```
caliper/hardware/design/sheets/*.py ──build.py──▶ caliper/hardware/kicad/<board>/*.kicad_sch ──kicad-cli──▶ ERC, netlist, PDF
```

```sh
# in WSL (Ubuntu 24.04, KiCad 9.0.9)
python3 caliper/hardware/design/build.py --render      # both boards: schematic, ERC, netlist, PDF + PNG per sheet
python3 caliper/hardware/design/check_contract.py      # ESP32 pins in the netlist == nets.MCU_PINS
python3 tools/lcsc_check.py caliper/hardware/kicad/slider/prettycool-caliper-slider.net   # LCSC stock/type check
```

Every pin gets a short wire stub that ends in a label or a power symbol, and parts are auto-placed in titled,
annotated groups. Do not hand-edit the `.kicad_sch` files: change the sheet module and rebuild.

| Board | KiCad project | Sheets | Rendered schematic |
|---|---|---|---|
| `slider` | `caliper/hardware/kicad/slider/prettycool-caliper-slider.kicad_pro` | power, mcu, sensor_mag, sensor_cap, ui, imu | [PDF](https://github.com/tyevco/prettycoolboards/blob/main/caliper/hardware/kicad/slider/render/prettycool-caliper-slider-schematic.pdf) |
| `scale` | `caliper/hardware/kicad/scale/prettycool-caliper-scale.kicad_pro` | scale | [PDF](https://github.com/tyevco/prettycoolboards/blob/main/caliper/hardware/kicad/scale/render/prettycool-caliper-scale-schematic.pdf) |

Toolchain changes made for this project (backward compatible): the deterministic UUID namespace in `schgen.py`
and `pcbgen.py` is now settable (`schgen.set_uuid_namespace()`, `pcbgen.UUID_NAMESPACE`; the default is still
`dial-me-spinner`), and `symgen.write_library()` takes the generator name. The caliper uses `prettycool-caliper`.

## 2. ERC status

| Board | Result (kicad-cli 9.0.9, `--severity-all`) |
|---|---|
| slider | **0 unwaived**; 2 waived `pin_to_pin` |
| scale | **clean** |

Waivers (in `build.py`, reported as "waived", never dropped silently):

| Violation | Pins | Why it is intended |
|---|---|---|
| pin_to_pin (open collector ↔ power output) | U5 pins 5 (QOD), 6 (VOUT) | TPS22917 QOD tied straight to VOUT, the datasheet's second QOD option (SLVSDW8B Table 6-1): +3V3_SNS is actively discharged when the switch turns off |
| pin_to_pin | U6 pins 5, 6 | Same for +3V3_UI |

`check_contract.py` result: `U10 checked against 42 nets.MCU_PINS entries -> OK` (it was also checked to fail on a
deliberately swapped pin).

## 3. Slider board, sheet by sheet

Reference designators are grouped by sheet: power 1–19, mcu 20s, sensor_mag 30s, sensor_cap 40s/60s–80s, ui 50s, imu 60s
(U60/C60–C62).

### 3.1 power: USB-C, charger, 3V3, rails

| Ref | Part | LCSC | Notes |
|---|---|---|---|
| J1 | HRO TYPE-C-31-M-12, 16-pin USB 2.0 receptacle | C165948 | Right edge (x = 62, y ≈ 26). CC1/CC2 each 5.1 k to GND (R1, R2): sink only, 5 V default USB current |
| U1 | USBLC6-2SC6 | C7519 | ESD on D+/D−/VBUS, flow-through. Within 5 mm of J1 |
| D1 | SMF5.0A TVS | C151296 | VBUS surge (as dial-me-spinner) |
| U2 | BQ25180YBGR (I2C 0x6A) | C3682423 | Linear charger + power path, 250 mA charge set over I2C, ship mode for storage. Battery discharge limit `IBAT_OCP` resets to 1 A; keep it there (≈ 0.5 A Wi-Fi peaks from a low cell). IN 2.2 µF/25 V 0805 X7R, SYS 10 µF/25 V, BAT 4.7 µF (dial-me-spinner's values, which its SPICE suite checked for DC bias). /INT → CHG_INT_N. TS/MR: 10 k NTC RT1 (board temperature next to the battery connector; the datasheet's "no TS" option is a plain 10 k) |
| J2 | JST SM02B-SRSS-TB (SH 2-pin) | C160402 | 1 = BAT+, 2 = GND. **Check every pack's polarity**: hobby packs are not consistent |
| U3 | TPS63802DLAR buck-boost → +3V3 | C2845237 | 2 A, 11 µA Iq. EN = VSYS (always on), MODE = GND (power save), PG unused. TI typical application (SLVSEU9D Fig. 10-1): CIN 10 µF (C4), COUT 22 µF (C5) + 22 µF bulk (C6), feedback R3 511 k / R4 91 k → 3.31 V |
| L1 | Murata DFE201612E-R47M (0.47 µH, 5.5 A Isat) | C668312 | From TI's recommended list (Table 10-2). Footprint = KiCad's DFE201610P land (same 2016 body; the E part is 1.2 mm tall) |
| U4 | MAX17048G+T10 fuel gauge (0x36) | C2682616 | VDD = CELL = VBAT, CTG/QSTRT/EP to GND, 0.1 µF (C7). 3 µA hibernate. ALRT → FG_ALRT_N |
| U5 | TPS22917DBVR → +3V3_SNS | C2681320 | AS5311 + capacitive front-end. ON = SNS_PWR_EN (R5 100 k pull-down), CT 1 nF to VIN, QOD = VOUT |
| U6 | TPS22917DBVR → +3V3_UI | C2681320 | **Added during capture**: LCD logic VDD + RGB LED, also on SNS_PWR_EN (no GPIO is free) |
| R6, R7 | 4.7 k I2C pull-ups to +3V3 | C25900 | Always-on rail: the MAX17048's SCL/SDA have internal pull-downs and read a low bus as "disconnected" |
| R8, R9 | 10 k pull-ups on CHG_INT_N, FG_ALRT_N | C25744 | Open-drain interrupts |
| H1–H4, FID1–3 | M2 plated holes (GND), fiducials | – | Footprints only |
| TP1–TP7 | VBUS, VBAT, VSYS, +3V3, +3V3_SNS, +3V3_UI, GND | – | Bring-up |

Pinouts: BQ25180 from TI SLUSE99C Table 6-1 (and the YBG0008 land pattern, the footprint is copied from
dial-me-spinner); TPS63802 from SLVSEU9D Table 7-1, footprint drawn from the DLA0010A example board layout (p. 36:
pads 1–5 0.6 × 0.25 mm at x = −0.9, pads 6/7/9/10 0.9 × 0.25 mm at x = +0.75, GND pad 8 1.3 × 0.25 mm);
MAX17048 from the Maxim 19-6171 pin table (TDFN: 1 CTG, 2 CELL, 3 VDD, 4 GND, 5 ALRT, 6 QSTRT, 7 SCL, 8 SDA, EP).

### 3.2 mcu: ESP32-S3-MINI-1

| Ref | Part | LCSC | Notes |
|---|---|---|---|
| U10 | **ESP32-S3-MINI-1-N4R2** (4 MB quad flash, 2 MB quad PSRAM) | C3013941 | The N8R2 is not stocked at LCSC (searched 2026-11-07); the N8 (no PSRAM) is. KiCad's `RF_Module:ESP32-S3-MINI-1` symbol matches the Espressif pin table pad for pad; its footprint is `RF_Module:ESP32-S2-MINI-1`, the same 65-pad 15.4 × 20.5 mm land. That footprint has **no antenna keep-out zone** (its description also wrongly says "external antenna"): the layout must add the all-layer keep-out |
| C20, C21 | 22 µF + 100 nF at pad 3 | C59461, C1525 | Datasheet v1.7 Fig. 9-1 |
| R20, C22 | EN RC 10 k / 1 µF | C25744, C52923 | Datasheet §9: "R = 10 kΩ and C = 1 µF" |
| R21, SW20 | BOOT: 10 k pull-up on GPIO0, button to GND | C25744, C720477 | Recovery only; normal flashing uses USB-Serial-JTAG |

The pin map is exactly `nets.MCU_PINS` ([SPEC §5](../hardware/design/SPEC.md#_5-mcu-pin-map-esp32-s3-mini-1)).
The KiCad symbol names pads 23/24 `USB_D-`/`USB_D+`; the sheet maps the contract's `IO19`/`IO20` to them.
IO26 (the PSRAM chip select on R2 parts) has a no-connect flag. Strapping: GPIO45 has a 100 k pull-down on the BUZZ
gate (R56), GPIO46 a 100 k pull-down on RGB_DIN (R55), GPIO0 the BOOT pull-up, GPIO3 the CHG_INT_N pull-up (harmless
while the JTAG_SEL eFuse is unburnt).

### 3.3 sensor_mag: AS5311

| Ref | Part | LCSC | Notes |
|---|---|---|---|
| U30 | ams AS5311-ATST (TSSOP-20) | C22459687 | **80 pcs in stock** at LCSC on 2026-11-07, Extended, $12.63. Order it early; if it is gone, consign it or hand-place it |
| C30, C31 | 100 nF + 1 µF at VDD5V | C1525, C52923 | Datasheet §7.7 |
| R30, R31 | 10 k pull-ups to +3V3_SNS on MagINCn / MagDECn | C25744 | Open drain (Table 1) |
| TP30–32 | MAG_A, MAG_B, MAG_IDX | – | Scope / logic analyser |

Pinout from the ams datasheet Revision 1.13, Table 1 (checked pin by pin): 1 NC, 2 MagINCn, 3 MagDECn, 4 A, 5 B,
6 NC, 7 Index, 8 VSS, 9 Prog, 10 NC, 11 NC, 12 DO, 13 CLK, 14 CSn, 15 PWM, 16 NC, 17 NC, 18 VDD3V3, 19 VDD5V,
20 NC. "Pins 1, 6, 10, 11, 16, 17 and 20 are for internal use and must not be connected": they carry no-connect
flags, as does the unused PWM output. 3.3 V operation: VDD5V and VDD3V3 both on +3V3_SNS (§7.7, "the LDO must be
bypassed by connecting VDD3V3 with VDD5V"). Prog to VSS ("for factory programming only"). CSn has an internal
~50 k pull-up and must be low for the A/B/Index outputs. Supply current 16 mA typ, 21 mA max.

### 3.4 sensor_cap: capacitive front-end (experimental)

```
CAP_TXn ─ R6n 0R (DNP-able) ─ R7n 100R ─ CAP_EL_TXn (comb phase n)        n = 0…7
CAP_EL_RX ─ R80 0R (DNP-able) ─ CAP_RX_IN ─┬─ U40A − (C40 10p C0G ‖ R81 10M to CAP_AMP_OUT)
                                           U40A + = CAP_VREF (R82/R83 100k/100k + C41 1u, buffered by U40B)
CAP_AMP_OUT ─ R84 390R ─┬─ R85 3.9k ─┬─ CAP_RX (GPIO1, ADC1_CH0)
                       C43 1n       C44 100p C0G
```

* **Op-amp:** TLV9062IDGKR (C398356): dual, 10 MHz GBW, rail-to-rail in/out, 538 µA per amplifier, 1.8–5.5 V.
  It meets SPEC's "≥ 10 MHz GBW, RRIO CMOS" at $0.23. If the bandwidth turns out short, a 50 MHz RRIO dual such as
  the OPA2365 has the same pinout, but LCSC C130011 is the **SOIC-8** OPA2365AIDR, so it is not a footprint drop-in
  for the VSSOP-8 land (a VSSOP version would have to be sourced).
* **Feedback:** 10 pF ‖ 10 MΩ: the gain is −C<sub>coupling</sub>/10 pF and the DC path's corner is
  1/(2π·10 MΩ·10 pF) ≈ 1.6 kHz, far below the 25–100 kHz drive.
* **Low-pass:** two RC poles at 1/(2π·390 Ω·1 nF) ≈ 408 kHz and 1/(2π·3.9 kΩ·100 pF) ≈ 408 kHz; the second stage
  is 10× the impedance so it barely loads the first.
* **Isolation:** with R60–R67 and R80 left off, the experiment is fully disconnected from the ESP32 and the
  op-amp. The rail (+3V3_SNS) is shared with the AS5311, and the op-amp is always fitted.

**Electrodes in the schematic (the approach chosen):** the electrodes are bottom-layer copper, not parts. They are
drawn as one symbol, **E40** (`caliper:CAP_ELECTRODES`), with a footprint of *seed pads*, one per electrode net:
pads 1–8 are eight 0.30 × 5.00 mm fingers at 0.635 mm pitch (TX0…TX7, one 5.08 mm repeat), pad 9 is a
5.08 × 1.20 mm receive strip 3.8 mm below the comb centre (SPEC §2.1: comb y = 12.5…17.5, RX y = 10.6…11.8). The
layout script places E40 on the bottom at the start of the comb and draws the remaining 7 repeats and the full
40 mm RX strip as copper on the same nets. E40 is excluded from the BOM and the CPL. This keeps every electrode a
real net with a pad (ERC checks it, the netlist carries it to the board, DRC sees the copper on its net) without
net-tie footprints or ERC waivers.

### 3.5 ui: display, buttons, LED, piezo

**LCD panel pinout.** The 13-pin 1.14 in ST7789 glass is sold under many part numbers; the pin order used is the
DisplayModule **DM-TFT114-397** datasheet, §3.1 "Panel Pin Description" ([PDF](https://cdn.shopify.com/s/files/1/0264/7629/files/DM-TFT114-397_Datasheet.pdf)):

| Pin | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Panel | NC | NC | SDA | SCL | RS (D/C) | RESET | CS | GND | NC | VDD | LEDK | LEDA | GND |
| Net | – | – | LCD_MOSI | LCD_SCK | LCD_DC | LCD_RST_N | LCD_CS_N | GND | – | +3V3_UI | LCD_LEDK | LCD_LEDA | GND |

Same datasheet: VDD 2.4–3.3 V, 8 mA typ; sleep-in 15 + 5 µA typ; backlight 1 white LED, VF 2.9–3.1 V at 20 mA.

| Ref | Part | LCSC | Notes |
|---|---|---|---|
| J50 | 0.5K-AX-13PWB, 13 P 0.5 mm FPC, bottom contact, slide lock, 2.0 mm | C2911931 | 2784 in stock. Footprint is KiCad's Hirose FH12-13S-0.5SH (same class; the FH12 itself is out of stock at LCSC): **check against the C2911931 drawing before layout release** |
| C50, C51 | 1 µF + 100 nF at VDD | | |
| R50 | 15 Ω 0603, +3V3 → LEDA | C22810 | (3.31 V − VF) / 15 Ω ≈ 20 mA at VF 3.0 V (the panel's rated point), ≤ 27 mA at 2.9 V, ~14 mA at 3.1 V. Was 10 Ω at capture, which gave 31–41 mA (changed in review). Only ~0.3 V of headroom, so brightness follows VF and +3V3. Dim by PWM |
| Q50 | AO3400A, low side on LEDK, gate = LCD_BL | C20917 (Basic) | R51 100 k gate pull-down |
| SW50–52 | XUNPU TS-1088-AR02016 (3.9 × 2.9 × 2.0 mm) ZERO/HOLD/MODE | C720477 (Basic) | 100 k pull-up (R52–R54) + 100 nF (C52–C54) = 10 ms RC debounce; RTC GPIOs 17/18/21 wake from deep sleep |
| D50 | WS2812B-2020-V6 RGB LED | C52917434 | LCSC lists 3.3–5.3 V, so it runs on +3V3_UI with a 3.3 V DIN and no level shifter. R55 100 k pull-down (GPIO46 strap) |
| BZ50 | Murata PKMCS0909E4000-R1 piezo (4 kHz, external drive) | C910763 | +3V3 → BZ50 ‖ R57 1 k → Q51 (AO3400A) drain. R56 100 k gate pull-down holds GPIO45 (VDD_SPI strap) low at reset |

### 3.6 imu: LIS2DW12

U60 LIS2DW12TR (C189624) on the system I2C, always powered from +3V3 so it can wake the ESP32 on pickup (INT1 →
GPIO15, an RTC GPIO). 100 nF + 10 µF at VDD, 100 nF at VDD_IO. CS high (I2C), RES to GND.
**SA0 is tied high: address 0x19, not the 0x18 SPEC first asked for.** SDO/SA0 has an internal pull-up that cannot
be disconnected in I2C mode, so a grounded SA0 draws ~60–170 µA permanently (ST AN5038; dial-me-spinner measured
it as a bring-up fault signature). That alone would be several times the sleep budget. `nets.I2C_ADDR` and SPEC
§6 are updated.

## 4. Scale board

No electronics: two plated M2 holes on GND (H1, H2), two fiducials and a PWR_FLAG. The reflector pattern and the
back-copper ground plane are drawn by the layout script as copper/graphics (SPEC §2.2). The netlist exists so the
layout can import the holes and fiducials the same way as the slider.

## 5. BOM and sourcing

`tools/lcsc_check.py` against the JLCPCB catalogue on 2026-11-07: **45 BOM lines, 0 flagged** (every code
found, in stock, MPN matches). 20 lines are JLC **Basic**, 25 **Extended** (re-run after the review changed R50 to the Extended 15 Ω C22810).

| Line | LCSC | Type | Stock | $ (qty 1) |
|---|---|---|---|---|
| ESP32-S3-MINI-1-N4R2 | C3013941 | Extended | 7 487 | 5.00 |
| AS5311-ATST | C22459687 | Extended | **80** | 12.63 |
| BQ25180YBGR | C3682423 | Extended | 5 848 | 1.85 |
| MAX17048G+T10 | C2682616 | Extended | 22 821 | 2.01 |
| TPS63802DLAR | C2845237 | Extended | 23 909 | 0.91 |
| TPS22917DBVR (×2) | C2681320 | Extended | 3 637 | 0.37 |
| LIS2DW12TR | C189624 | Extended | 52 010 | 0.90 |
| TLV9062IDGKR | C398356 | Extended | 53 188 | 0.23 |
| WS2812B-2020-V6 | C52917434 | Extended | 740 820 | 0.09 |
| PKMCS0909E4000-R1 | C910763 | Extended | **535** | 1.10 |
| 0.5K-AX-13PWB FPC | C2911931 | Extended | 2 784 | 0.12 |
| AO3400A, TS-1088, 0402 R/C | various | Basic | > 100 k | < 0.09 |

**Parts that are not (reliably) on LCSC:** none is missing, but the **AS5311** has only 80 pieces at LCSC: if they
are gone when the order is placed, the part is consigned or hand-placed (the BOM field `JLC` says so). The LCD panel
itself is not a PCBA part: it plugs into J50 by hand.

## 6. Open risks (schematic)

* **LCD panel pitch / pin order.** The cited pinout comes from a module whose drawing shows a 0.7 mm *solder*
  tail; the board needs a panel with a 0.5 mm, 0.3 mm-thick plug-in tail in the same pin order. Buy the panel
  first and check its drawing; if it differs, change `PANEL_PINS` in `sheets/ui.py`.
* **FPC footprint** is the FH12 land, not the C2911931 vendor drawing (§3.5).
* **WS2812B-2020-V6** pin order and the 3.3 V minimum are from the LCSC listing and the WS2812B-2020 family; the V6
  datasheet could not be downloaded during capture.
* **Backlight headroom**: 3.31 V − 3.0 V VF leaves 0.3 V across 15 Ω + the FET; a 3.1 V LED gets ~14 mA, a 2.9 V
  one ≤ 27 mA. The panel's maximum LED current is not in the cited datasheet: check it on the bought panel.
* **Sleep current** is ≈ 33 µA (estimate), above SPEC's original 25 µA; SPEC is revised to ≤ 35 µA
  ([Architecture §5](architecture.md#_5-power-budget-and-battery-life)).
* **Ship mode** can only be left by plugging in USB (TS/MR is not wired to a button).
* **RX electrode ESD**: the receive strip is exposed copper under an open mask, connected through R80 straight to a
  high-impedance op-amp input. It faces the scale, not the user, but a discharge into the beam could reach it.
  Not protected in rev A (a TVS would add pF and leakage at the most sensitive node).
* **Back-powering**: the MAG_*, LCD_* and RGB_DIN lines go into switched rails; the firmware must drive them low
  before SNS_PWR_EN goes low.
* Nothing here has been simulated (the simulation track owns SPICE) or built.
