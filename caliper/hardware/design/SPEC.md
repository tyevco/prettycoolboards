# PrettyCool Caliper — SPEC (architecture of record, rev A)

This is the contract that the schematics (`sheets/*.py`), the layout (`layout.py`), the mechanics
(`hardware/mechanical/`) and the firmware (`firmware/`) implement. The net names and the pin map
live in [nets.py](nets.py). If anything here changes, update `nets.py` and this file first.

## 1. Product

| | |
|---|---|
| Range | 0–150 mm, outside / inside / depth / step |
| Resolution shown | 0.01 mm / 0.0005 in (the internal resolution is the AS5311's 0.488 µm) |
| Target accuracy | ±0.03 mm (rev A has a printed body; the electronics aren't the limit) |
| Sensors | **Primary:** AS5311 magnetic linear encoder over 2.0 mm-pole magnetic tape. **Experimental:** capacitive 8-phase transmitter / reflector scale |
| MCU / radio | ESP32-S3-MINI-1 (N4R2 or N8R2; the schematic picks the LCSC-stocked one), PCB antenna. BLE 5 (HID keyboard + GATT) and 2.4 GHz Wi-Fi |
| Display | 1.14 in 240×135 ST7789 IPS, 13-pin 0.5 mm FPC, white LED backlight |
| UI | 3 buttons: ZERO, HOLD/SEND, MODE. RGB status LED, piezo |
| IMU | LIS2DW12 (wake on pickup, auto-off, orientation) |
| Power | 1S LiPo 402535 (~500 mAh) on JST-SH 2-pin. USB-C (USB 2.0 device) charging at 250 mA |
| Storage | Readings in LittleFS on the module flash; exported as CSV over USB MSC, Wi-Fi or BLE |

## 2. Boards

| Board | Size | Stack | Notes |
|---|---|---|---|
| `slider` | 62 × 34 mm (outline may be notched by the mechanics) | 4-layer, 1.0 mm, ENIG | Everything electronic |
| `scale` | 200 × 7 mm | 2-layer, 0.8 mm, ENIG, no solder mask on the electrode face | Passive capacitive scale bonded into the beam |

### 2.1 Slider board placement (board origin = lower-left, +Y up, viewed from the top / display side)
- The **beam axis** is along X. The beam's front face lies under the board's lower band, **y = 0…20 mm**.
  The band above it, **y = 20…34**, sits clear of the beam.
- **ESP32-S3-MINI-1** on top, with the antenna end at the top edge (y = 34) and the antenna hanging clear
  of the steel beam. Copper keep-out on all layers under the antenna, per the Espressif guidelines.
- **AS5311** (TSSOP-20) on the **bottom**, centred at (x = 31, y = 6.0), long axis along X, over the
  magnetic tape track. The tape centre is 6.0 mm from the beam's lower edge.
- **Capacitive transmitter electrode array** on the **bottom copper**: a strip at y = 12.5…17.5,
  x = 11…51 (40 mm long, 8 phases, pitch 0.635 mm, a repeat every 5.08 mm), with the receive electrode as a
  1.2 mm strip below it at y = 10.6…11.8. Bottom mask is opened over the electrodes. Nothing else may
  go on the bottom layer in y = 9…19 apart from the electrodes and their guard ground.
- **Display**: the 0.5 mm 13-pin FPC connector on top, beside the module. The glass sits over y ≈ 4…30
  on a printed bezel and is glued to the housing, not the board.
- **USB-C** (mid-mount or top-mount, USB 2.0 16-pin) on the **right edge** (x = 62), y ≈ 26.
- **Buttons** on top along the upper edge band: ZERO (x≈8), HOLD/SEND (x≈20), MODE (x≈54). Use
  side-actuated or 3×4 mm top tact switches; the mechanics pick the caps.
- **Battery**: a 402535 cell in the housing pocket behind the board (not on the beam), on a JST-SH 2-pin.
- Mounting: 4 × M2 plated holes at (3, 3), (59, 3), (3, 31), (59, 31) (the mechanics may move them).

### 2.2 Scale board
- 200 × 7 mm, front copper only for the pattern. The back copper is a solid ground plane, which faces the beam.
- **Reflector pattern** (front): a column of isolated copper rectangles, pitch **5.08 mm**, each with a
  **2.54 mm wide** "T" (the reflector at y = 3.5…6.5) joined by a 0.3 mm neck to a coupler bar segment at
  y = 0.5…2.3. Electrode heights match the slider: the reflectors face the transmitter strip and the
  couplers face the receive electrode. Exact geometry goes in `sheets/scale.py` as board graphics;
  the board has no components.
- Two plated M2 holes and an edge fiducial at each end.

## 3. Power tree

```
USB-C VBUS ─ ESD/TVS ─ BQ25180 (VIN) ─┬─ SYS → VSYS ─┬─ TPS63802 buck-boost → +3V3 (ESP32, LCD, IMU, FG, LED)
                                     │               └─ (VSYS sense via MAX17048, which is on BAT)
                                     └─ BAT ─ LiPo (JST-SH), MAX17048 CELL
+3V3 ─ TPS22917 load switch (SNS_PWR_EN) → +3V3_SNS (AS5311, capacitive front-end op-amp + VREF)
+3V3 ─ low-side N-MOSFET (LCD_BL, PWM) ─ backlight LED (current-set resistor)
```
- Use a **buck-boost**, not an LDO: Wi-Fi TX peaks near 500 mA, and an LDO drops out below a ~3.6 V cell.
  TPS63802 (2 A, 11 µA Iq) or another LCSC-stocked buck-boost with ≥1 A out and ≤15 µA Iq.
- BQ25180: ILIM set by I2C. Ship mode is used in storage. The register init table follows
  dial-me-spinner `docs/firmware.md §13.1`. /INT goes to CHG_INT_N.
- Sleep budget target: ≤ 25 µA total (buck-boost Iq + BQ25180 + MAX17048 hibernate + LIS2DW12 wake
  mode + ESP32-S3 deep sleep).

## 4. Sensors

### 4.1 AS5311 (primary)
- Powered from +3V3_SNS (VDD5V and VDD3V3 tied, 3.3 V operation per datasheet) with 100 nF + 1 µF.
- **Quadrature A/B → ESP32 PCNT** (4× decoding: 0.488 µm/count). **Index** pulses once per 2 mm pole
  pair. The **SSI** (CSn/CLK/DO) reads the 12-bit absolute position within the pole and its status
  bits (OCF, COF, LIN, MagINC, MagDEC) for the field-strength check.
- MagINCn / MagDECn are open-drain: pulled up to +3V3_SNS, then read on MAG_INC_N / MAG_DEC_N.
- Prog pin is tied to VSS (no OTP programming in rev A).
- Air gap 0.3 mm ±0.1 between the IC's top surface and the tape. The mechanics hold it with gibs.

### 4.2 Capacitive front-end (experimental, isolatable)
- **TX:** 8 GPIO outputs (CAP_TX0…CAP_TX7). Each goes through a 0402 0 Ω jumper (`R_CAPTXn`, DNP-able) and a
  100 Ω series resistor to its electrode phase. Phase n connects to every 8th finger.
- **RX:** receive electrode → 0 Ω jumper (DNP-able) → a charge amplifier (a rail-to-rail CMOS op-amp with
  ≥10 MHz GBW, e.g. OPA376/OPA365 class, LCSC-stocked; feedback 10 pF ‖ 10 MΩ) biased at VREF = +3V3_SNS/2
  (divider + 1 µF, buffered by the 2nd half of a dual op-amp, or a separate one) → a 2nd-order RC/active
  low-pass at ~400 kHz → **CAP_RX** (ESP32 ADC1_CH0, GPIO1).
- The firmware drives the 8 phases (a dedicated-GPIO bundle) as a rotating square pattern at 25–100 kHz.
  The ADC samples are synchronously demodulated into I/Q, and atan2 gives the position within the 5.08 mm pitch.
- A guard ground pour surrounds the RX trace on all layers. No digital traces cross the front-end.

## 5. MCU pin map (ESP32-S3-MINI-1)

The authoritative copy is `nets.py: MCU_PINS`. The constraints behind it:
- Strapping pins: GPIO0 (BOOT button + 10 k pull-up), GPIO3 (CHG_INT_N, which may float high at
  boot; harmless while JTAG_SEL eFuse is unburnt), GPIO45 (must read **low** at reset, because VDD_SPI is 3.3 V;
  BUZZ gate with 100 k pull-down), GPIO46 (must be low or floating; RGB LED DIN, 100 k pull-down).
- USB: GPIO19 = D−, GPIO20 = D+. Native USB (TinyUSB composite CDC + MSC + HID, or USB-Serial-JTAG for
  flashing). 22 Ω series resistors are not needed (they're inside the S3); ESD at the connector.
- ADC: only ADC1 (GPIO1–10) works alongside Wi-Fi, so CAP_RX = GPIO1.
- Deep-sleep wake sources must be RTC GPIOs (GPIO0–21): IMU_INT1, the buttons, CHG_INT_N.
- Never use GPIO26 (the in-package PSRAM chip-select on R2 variants). GPIO27–32 aren't bonded out.
- The UART0 pins (GPIO43/44) are used as cap TX phases; the console is on USB.

## 6. Interfaces

| Bus | Devices | Notes |
|---|---|---|
| I2C (GPIO13 SDA / GPIO14 SCL, 4.7 k to +3V3, 400 kHz) | BQ25180 (0x6A), MAX17048 (0x36), LIS2DW12 (0x18, SA0 low) | |
| SPI2 (GPIO33 SCK / GPIO34 MOSI / GPIO35 CS / GPIO36 DC / GPIO37 RST) | ST7789 LCD | 40 MHz, write-only |
| AS5311 SSI (GPIO7 CLK / GPIO8 DO / GPIO9 CSn) | AS5311 | bit-banged or SPI3, ≤1 MHz |

## 7. Mechanical envelope (detail in `hardware/mechanical/`)
- **Beam:** ground flat stock **20 × 4 mm**, 250 mm long (O1 or 1.4301). The front face carries two bands
  measured from the beam's lower (jaw-side) edge: the **magnetic tape** (10 mm wide, centred at y = 6) in a
  0.6 mm pocket, and the **scale PCB** (7 mm wide, at y = 10.5…17.5) in a 0.8 mm pocket. Both end flush
  ±0.05 with the beam face. Mapped onto the slider board's y-coordinates, beam lower edge = board y 0.
- The slider housing straddles the beam: printed PETG/PA-CF in rev A, CNC 6061 in rev B. Brass gibs with
  M2 set screws + springs set the 0.3 mm (magnetic) and 0.15 mm (capacitive) gaps. The fixed jaw is
  bolted and dowelled to the beam end. The moving jaw is part of the slider housing.
- Housing outside: ≤ 78 × 52 × 16 mm, including the thumb wheel/roller.

## 8. Firmware contract (detail in `docs/firmware.md`)
- The BLE GATT service UUIDs and the characteristic layout are defined once in
  `firmware/main/proto/caliper_gatt.h` and mirrored in `app/`.
- Log record: `{u32 seq, u32 unix_s, i32 value_nm, u8 unit, u8 flags (hold/tol pass/fail), u16 profile_id}` = 16 bytes.
