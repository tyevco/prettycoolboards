# PrettyCool Caliper — SPEC (architecture of record, rev A)

This is the contract that the schematics (`sheets/*.py`), the layout (`layout.py`), the mechanics
(`hardware/mechanical/`) and the firmware (`firmware/`) implement. The net names and the pin map
live in [nets.py](nets.py). If anything here changes, update `nets.py` and this file first.

## 1. Product

| | |
|---|---|
| Range | 0–150 mm, outside / inside / depth / step |
| Resolution shown | 0.01 mm / 0.0005 in. Internal resolution **0.488 µm** (2 mm / 4096 = 488.28125 nm): the PCNT quadrature count (1.953125 µm) interpolated with the AS5311's 12-bit SSI position (§4.1) |
| Target accuracy | ±0.03 mm (rev A has a printed body; the electronics aren't the limit) |
| Sensors | **Primary:** AS5311 magnetic linear encoder over 2.0 mm-pole magnetic tape. **Experimental:** capacitive 8-phase transmitter / reflector scale |
| MCU / radio | ESP32-S3-MINI-1-**N4R2** (4 MB quad flash + 2 MB quad PSRAM; LCSC C3013941. The N8R2 is not stocked at LCSC), PCB antenna. BLE 5 (HID keyboard + GATT) and 2.4 GHz Wi-Fi |
| Display | 1.14 in 240×135 ST7789 IPS, 13-pin 0.5 mm FPC, white LED backlight. **Landscape**: the 31.0 mm long axis (240 px) along the beam (§2.1, D4) |
| UI | 3 buttons: ZERO, HOLD/SEND, MODE. RGB status LED, piezo |
| IMU | LIS2DW12 (wake on pickup, auto-off, orientation), I2C 0x19 (SA0 high) |
| Power | 1S LiPo 402535 (~500 mAh) on JST-SH 2-pin. USB-C (USB 2.0 device) charging at 250 mA |
| Storage | Readings in LittleFS on the module flash; exported as CSV over USB MSC, Wi-Fi or BLE |

## 2. Boards

| Board | Size | Stack | Notes |
|---|---|---|---|
| `slider` | **74 × 34 mm overall**: a 62 × 34 body (x 0…62) plus two 6 × 14 mm end tabs (x −6…0 and 62…68, y 2.5…16.5), §2.1 | 4-layer, 1.0 mm, ENIG, symmetric stack, copper poured on all layers in y 0…20 for balance | Everything electronic. **Flatness ≤ 0.03 mm over y 0…20 (x −6…68, tabs included)**, assembled board on a surface plate, 100 % inspected, reject above (fab note; IPC-6012 class 2's 0.75 % bow would allow 0.55 mm) |
| `scale` | 200 × 7 mm | 2-layer, 0.8 mm, ENIG, no solder mask on the electrode face | Passive capacitive scale bonded into the beam |

### 2.1 Slider board placement (board origin = lower-left of the 62 × 34 body, +Y up, viewed from the top / display side)

Board y = beam y (the beam's lower, jaw-side edge is y = 0). Board x = slider u − 8 (`params.BOARD_U0`).
The **beam axis** is along X. The beam's front face lies under the board's lower band, **y = 0…20 mm**, 0.15 mm
below the board bottom. The band above it, **y = 20…34**, sits clear of the beam (the Y gib and channel wall
reach y 21.2; the housing floor is 0.75 mm under the board bottom there).

**Height rules (top side, from the mechanics):** under the display glass and its lid ribs (x 16.15…49.85,
y 1.2…20.15) parts ≤ **2.6 mm**; everywhere else ≤ **4.2 mm** (lid underside at z 5.4, board top at z 1.15).

**Bottom-side rule (D2):** no bottom-side parts over the beam band (board y 0…20) except **the AS5311 and its
two decoupling capacitors, inside y 2.4…9.6 and x 20…41, ≤ 1.30 mm tall** (they run in the beam's tape channel,
y 1.9…10.1; x 20…41 is where the channel, beam x 28…200, stays under the board over the whole 0–151 mm travel),
and **the electrodes** (§2.2 table) with their guard copper. Everything else on the bottom over y 0…20 is
copper under solder mask, nothing proud of it. Bottom in y 22…34: flat test pads only (no parts; the battery is
1.55 mm below).

**Placement table (D4).** Centre coordinates in board mm; rotation in degrees as seen from the top, 0 = the
footprint's own orientation; the layout script may move a part ≤ 1 mm without a SPEC change if every rule here
still holds (the mechanics re-run `clash_check.py` on the extracted envelope).

| Ref | Part | Side | x | y | Rot / orientation | Envelope, notes |
|---|---|---|---|---|---|---|
| U10 | ESP32-S3-MINI-1-N4R2 | top | 8.3 | 24.25 | 0: antenna end toward +y | footprint origin; outline x 0.6…16.0, y 14.0…34.0 (antenna area y 29.5…34.0 flush with the top edge, the top-left corner); h 2.55. Not under the glass |
| — | Antenna keep-out | all 4 layers | | | | **x 0…21.0, y 29.0…34.0: no copper (pads, tracks, vias, zones), no parts, either side.** The footprint has none: layout draws it as a rule area. See "Antenna" below |
| J50 | 13p 0.5 mm FPC, 2.0 tall | top | 21.5 | 8.5 | contact row along y, opening toward −x | under the glass's −x end: the panel tail leaves the glass at x 17.5 and folds back under it into J50 (TVP: tail length of the bought panel) |
| — | Display glass (on the lid, not the board) | — | 33.0 | 10.0 | landscape, FPC at the −x end | glass 31.0 × 17.6 × 1.6: x 17.5…48.5, y 1.2…18.8; active area 24.91 × 14.86, centre (34.45, 10.0) (shifted 1.45 away from the FPC end, TVP); lid end ribs x 16.15…17.5 and 48.5…49.85 |
| J1 | USB-C HRO TYPE-C-31-M-12, top-mount | top | 59.3 | 26.5 | opening toward +x | shell x 55.65…63.0 (1.0 mm past the edge), y 22.03…30.97, h 3.26 (mechanics DEV-4: y 26.5) |
| U1, D1 | USBLC6-2SC6, SMF5.0A | top | 53.0 | 24.0 | | within 5 mm of J1's pads, x 50.5…55.0, y 21.0…27.0 |
| SW50 | ZERO, TS-1088 3.9 × 2.9 × 2.0 | top | 31.0 | 31.0 | 0 | cap stem Ø3.5 at slider u 39 |
| SW51 | HOLD/SEND | top | 38.5 | 31.0 | 0 | u 46.5. The mechanics' x 18.5 (DEV-5) only kept the cap off the old portrait glass; with the landscape glass that x is inside the antenna clearance, so it moves here (the cap still clears the glass rib, y ≥ 28 vs ≤ 20.15) |
| SW52 | MODE | top | 46.0 | 31.0 | 0 | u 54; courtyard x ≤ 49, clear of J1 (x ≥ 53.7) and the antenna |
| D50 | WS2812B-2020 RGB LED | top | 51.5 | 32.0 | 0 | light pipe in the lid at u 59.5 |
| J2 | JST-SH SM02B-SRSS-TB, 2.95 tall | top | 24.5 | 31.4 | mating face toward +y (the top edge) | courtyard x 21.6…27.4: 0.6 clear of the antenna keep-out. The cell's leads come up past the top edge from the cell's −x end (the mechanics add a lead channel and a plug relief beyond y 34) |
| RT1 | 10 k NTC (TS) | top | 24.5 | 26.5 | | next to J2, over the cell |
| BZ50 | PKMCS0909E piezo, 1.9 tall | top | 40.0 | 24.3 | 0 | courtyard x 34.75…45.25, y 19.55…29.05; sound port in the lid at u 48 |
| U60 | LIS2DW12 | top | 30.0 | 23.5 | | ≥ 15 mm from L1 |
| U2, U3, L1, U4, U5, U6, C1–C12, R3–R9 | charger / buck-boost / gauge / rail-switch cluster | top | 56.0 | 11.0 | | inside x 50.5…61.5, y 2.5…20.5 (not under the glass; ≤ 4.2). L1 and the U3 switch nodes ≥ 10 mm from U40 and the RX feed |
| U30 | AS5311 TSSOP-20 | **bottom** | 31.0 | 6.0 | long axis along X | body x 27.75…34.25, leads y 2.8…9.2, A ≤ 1.20 |
| C (AS5311 100 nF, 1 µF) | 0402 | **bottom** | 25.5 / 36.5 | 6.0 | | inside the channel window above; the MagINC/MagDEC pull-ups and TP30–32 go on top |
| E40 + comb | electrodes | **bottom copper** | 31.0 | 14.2 | | §2.2 table: x 10.68…51.32, y 10.35…18.05 incl. guard |
| U40, R80, AFE passives | TLV9062 charge amplifier | top | 42.0 | 5.0 | | under the glass (1.1 tall); RX feed via into the RX strip at x ≈ 42 |
| R60–R67, R70–R77 | TX jumpers + series R | top | 9.5 | 7.0 | | inside x 3.5…16, y 2.5…12 (left of the glass, below U10); TX phases feed the comb at its −x end |
| SW20 | BOOT, TS-1088 | top | 27.0 | 15.5 | | under the glass, no cap: used with the lid (and glass) off |
| R50, Q50, R51 | backlight | top | 25.5 | 4.0 | | under the glass, beside J50 |
| Q51, R56, R57 | piezo driver | top | 40.0 | 18.0 | | |
| TP1–7, TP20–23, TP30–32, TP40–42, TP50–51 | 19 × Ø1.0 test pads | **bottom** | 22.5…47.9 | 22.6 / 25.14 | 2.54 grid, two rows | bench bring-up with the board out of the housing; nothing in the antenna keep-out or on the H1 pad |
| H1 | M2 plated hole, Ø4.4 pad | both | 18.75 | 24.0 | | **nylon** M2 × 4 screw (5 mm from the antenna corner) into a body boss (u 26.75). Support only, see "Board support" |
| H2, H3 | tab clamp holes | tab | −3.5 | 5.5 / 14.0 | | Ø2.2 plated (GND), top pad Ø4.4 for an SMT M2 standoff; bottom: no exposed copper (0.15 above the beam) |
| H4, H5 | tab clamp holes | tab | 65.5 | 5.5 / 14.0 | | as H2/H3 |
| FID1–3 | fiducials, Ø1 / mask Ø2 | top | (2.0, 1.5), (60.5, 1.2), (60.5, 32.8) | | | outside the antenna keep-out and every courtyard |

**Antenna (D4).** The ESP32-S3-MINI-1's PCB antenna is the module's top 4.5 mm (the footprint's Fab "Keepout
Area"). Espressif's guideline (ESP32-S3-MINI-1 datasheet land pattern and the ESP32-S3 hardware design
guidelines, "positioning a module on a base board"; the KiCad footprint courtyard encodes it as 15 mm on each
side and beyond the antenna) is: antenna at the board edge, nothing conductive under it on any layer, and
≥ 15 mm of clearance around it. Rev A: the antenna area sits flush with the top edge in the **top-left corner**
(board edges on two sides), with the all-layer keep-out above under it and 5.0 mm to its right (x 16…21). 15 mm
sideways does not fit a 62 mm board that also carries a USB-C and three buttons along the same edge: that is a
recorded deviation, to be checked by an RSSI/range test at bring-up. Every metal part keeps ≥ 5 mm in plan from
the antenna area: the LiPo (the battery pocket moves to board x ≥ 21.5, D4/§7), J2, the USB-C (39 mm away), the
H1 screw (nylon), the SMT standoffs. The beam's upper edge is 9.5 mm below the antenna.

**Board support (D3).** The **Z datum is the four tab clamps H2–H5**: each carries an SMT M2 threaded standoff
(2.0 mm tall, OD ≤ 4.0 mm, reflow-soldered on the top pad; PEM SMTSO-M2-2ET class, the LCSC/JLC part to be chosen
by the schematics track), and an M2 screw from the tower's top face pulls the standoff's top face up against a
clamp face in the tower (the left tower spans u 0.5…7.6, the right u 70.4…78; the tabs sit at u 2…8 and
70…76, y 2.5…16.5, which keeps them 0.65 mm clear of the front-pad pockets and the pad set-screw inserts).
These four points sit at the ends of the sensor band, 3.5 mm and 12 mm from the AS5311 and electrode rows.
The four clamp faces must be coplanar within 0.03 mm (the mechanics choose how: faced brass washers, insert
faces, or the rev B machined tower). **H1** in the upper band is a support against button and cable loads, not a
datum: it is tightened last and must not pull the board out of the tab plane by more than 0.01 mm (dial
indicator, docs/mechanical.md §6 step 4; the boss is printed low and shimmed). The mechanics' upper-band holes
(3, 24.5) and (3, 31) are now under the MINI-1, and (59, 32.6) has its Ø4.4 pad crossing the top edge and its
screw head over the USB-C, so all three are replaced by H1 and the tabs. No other upper-band hole fits: the
battery pocket has no body under the board, and the USB-C fills the right end above y 22.

**Battery**: a 402535 cell in the housing pocket behind the board's upper band (not on the beam), on J2. The pocket
moves to **u 29.5…65.5 (board x 21.5…57.5)** so the cell is ≥ 5.5 mm from the antenna (D4).

### 2.2 Scale board and the electrode geometry
- 200 × 7 mm. Front copper (toward the slider) carries the pattern; the back copper is a solid ground plane
  (toward the pocket floor). No components.
- Bonded into the beam pocket with 3M 467MP, **no fasteners**: a screw head would stand above the beam face,
  which the slider towers clear by only 0.10 mm. The two end holes become **Ø1.0 non-plated alignment holes**
  at scale x 1.5 (centred in y) for a pin jig, plus an edge fiducial at each end (D5).
- The scale sits at beam x 14.5…214.5 (`params.SCALE_X0` moves 14.0 → 14.5 to centre the pattern on the
  electrode sweep).

**One coordinate table (D5).** y is beam y (= board y). Slider x is board x; scale x is measured from the
scale's own −x end (beam x = scale x + 14.5). The slider electrodes sweep beam x 18.68…59.32 at R = 0 and
169.68…210.32 at R = 151; the 38 scale cells cover beam x 17.98…211.02.

| Item | Board | Layer | x | y | Size / pitch |
|---|---|---|---|---|---|
| Scale PCB outline | scale | — | 0…200 | 10.5…17.5 | in the beam pocket y 10.45…17.55, flush ±0.05 |
| Scale copper keep-in | scale | F.Cu | 3.48…196.52 | 10.85…17.15 | 0.35 from the long edges |
| Cell *n* (n = 0…37) | scale | F.Cu | 3.48 + 5.08 n … + 5.08 | | one isolated T per cell |
| Coupler bar | scale | F.Cu | cell centre ± 2.29 | 10.85…12.55 | 4.58 wide (0.50 gap between cells), 1.70 tall |
| Neck | scale | F.Cu | cell centre ± 0.15 | 12.55…13.75 | 0.30 wide |
| Reflector | scale | F.Cu | cell centre ± 1.27 | 13.75…17.15 | 2.54 wide at 5.08 pitch, 3.40 tall |
| RX strip | slider | B.Cu, mask open | 10.68…51.32 | 11.05…12.35 | 1.30 tall: the coupler overlaps it by 0.20 on each side (y tolerance ±0.2) |
| Inner guard (GND) | slider | B.Cu | 9.98…52.02 | 12.65…13.25 | 0.60, 0.30 gaps to RX and TX; the scale neck crosses under it |
| TX fingers *k* (k = 0…63) | slider | B.Cu, mask open | 10.68 + 0.635 k … + 0.30 | 13.55…17.35 | 0.30 × 3.80 at 0.635 pitch, phase = k mod 8, 8 repeats of 5.08 = 40.64 mm (centred on x 31.0, the AS5311's x). The reflector lies inside the finger height with 0.20 on each side |
| Outer guard ring (GND) | slider | B.Cu | 9.58…52.42 | 10.35…10.75 and 17.65…18.05, closed at both ends | 0.40 wide, 0.30 gap |
| Guard under the electrodes | slider | In2 | 9.58…52.42 | 10.35…18.05 | solid GND except the phase bus and feed vias (layout's choice of layer for the 8 phase buses) |

E40's seed pads change with this table: fingers 0.30 × 3.80, RX 5.08 × 1.30, the RX centre 3.75 mm below the
finger centre (was 0.30 × 5.00 and 3.8 mm). Electrodes and couplers now overlap fully in y (before: RX y 10.6…11.8
against coupler 11.0…12.8, TX 12.5…17.5 against reflector 14.0…17.0).

## 3. Power tree

```
USB-C VBUS ─ ESD/TVS ─ BQ25180 (VIN) ─┬─ SYS → VSYS ─┬─ TPS63802 buck-boost → +3V3 (ESP32, LCD, IMU, FG, LED)
                                     │               └─ (VSYS sense via MAX17048, which is on BAT)
                                     └─ BAT ─ LiPo (JST-SH), MAX17048 CELL
+3V3 ─ TPS22917 load switch U5 (SNS_PWR_EN) → +3V3_SNS (AS5311, capacitive front-end op-amp + VREF)
+3V3 ─ TPS22917 load switch U6 (SNS_PWR_EN) → +3V3_UI  (ST7789 VDD, WS2812B-2020-V6 RGB LED)
+3V3 ─ 15 Ω ─ backlight LED (LEDA/LEDK) ─ low-side AO3400A (LCD_BL, PWM)   (≈ 20 mA at the panel's VF 3.0 V / 20 mA rating)
```
- **+3V3_UI** (added during capture): the ST7789 still draws 15 + 5 µA typ in sleep-in mode (DM-TFT114-397 §5.3)
  and a WS2812 draws standby current, so both are switched off in deep sleep. There is no free GPIO, so U6 shares
  SNS_PWR_EN with U5: both rails are on whenever the caliper is awake. Both switches tie QOD to VOUT (fast discharge)
  and use a 1 nF CT for a slow ramp. Before switching off, the firmware drives every signal into those rails low
  (MAG_CSN/MAG_CLK, LCD_*, RGB_DIN) so nothing back-powers through ESD diodes.
- Use a **buck-boost**, not an LDO: Wi-Fi TX peaks at 355 mA at 3.3 V (module datasheet Table 6-4; ≈ 0.5 A from a
  3.0 V cell with the rest of the load), and an LDO drops out below a ~3.6 V cell.
  TPS63802DLAR (2 A, 11 µA Iq; LCSC C2845237), L = 0.47 µH DFE201612E, feedback 511 k / 91 k (TI Table 10-5;
  R2 ≤ 100 k, so the divider costs 5.5 µA permanently).
- **MAX17048 in ship mode:** ship mode turns VSYS off, so +3V3 and the I2C pull-ups die while the MAX17048 stays
  on VBAT with SDA/SCL floating. Before writing SHIP_RST the firmware (`power_ship_mode`) sets HIBRT = 0xFFFF
  (always hibernate, 3 µA, the fallback), MODE.EnSleep = 1 and, without VBUS, CONFIG.SLEEP = 1: forced sleep,
  0.5 µA typ / 2 µA max, left only by CONFIG.SLEEP = 0 or POR (Maxim 19-6171 Rev 7: MODE 0x06 bit 13 Fig. 8
  p. 11; HIBRT 0x0A and CONFIG 0x0C bit 7 pp. 12; "Sleep Mode" p. 10; IDD0 p. 2). With VBUS present the BQ25180
  holds the ship request until the cable goes (SLUSE99C §8.3.11), so CONFIG.SLEEP is not set; EnSleep then
  lets the low bus (internal IPD pull-downs, tSLEEP 1.75–2.5 s) put it to sleep. `power_init` undoes all three
  at the next boot. Not measured (TVP).
- BQ25180: ILIM set by I2C. Ship mode is used in storage. The register init table follows
  dial-me-spinner `docs/firmware.md §13.1`. /INT goes to CHG_INT_N. Keep `IBAT_OCP` at its 1 A reset value or
  higher (SLUSE99C Table 8-15): the 500 mA setting would trip on the ≈ 0.5 A Wi-Fi peaks from a low cell.
- **TS (D8):** RT1, a 10 k B3435 NTC (Murata NCP15XH103F03RC, C77131) from TS/MR to GND, is **populated** (it is
  in the BOM and the netlist: net CHG_TSMR = U2 D1 + RT1 pin 1), and the firmware **enables TS** (IC_CTRL 0x97 with
  TS_EN, TS_CONTROL 0x90 = HOT 50 °C / COLD 3 °C; `CONFIG_CALIPER_CHG_TS_ENABLE` defaults to y). RT1 sits next to
  J2 over the cell, so it reads the board above the cell, not the cell itself (TVP: compare with a thermocouple on
  the pouch while charging).
- Sleep budget: the first-draft target is **not reachable** with this buck-boost: its Iq (11 µA) plus its
  feedback divider (5.5 µA) plus the ESP32-S3 deep sleep (~8 µA) already reach 24.5 µA. The target is **≤ 35 µA**
  (≈ 33 µA estimated: ESP32-S3 8 + TPS63802 11 + divider 5.5 + BQ25180 3 + MAX17048 hibernate 3 + LIS2DW12 ~1 +
  2 × TPS22917 off 0.02 + ≈ 2 conversion loss on the 3.3 V-side loads; the LCD and RGB LED are unpowered). The 3 µA
  figures need firmware settings: BQ25180 watchdog and push-button off (else 4 µA, SLUSE99C IQ_BAT), MAX17048
  `VRESET.Dis` = 1 (else 4 µA, 19-6171 IDD0). See docs/architecture.md for the budget and life estimate.

## 4. Sensors

### 4.1 AS5311 (primary)
- Powered from +3V3_SNS (VDD5V and VDD3V3 tied, 3.3 V operation per datasheet) with 100 nF + 1 µF.
- **Quadrature A/B → ESP32 PCNT** (4× decoding). The incremental outputs give 256 A/B pulses = **1024 edges per
  2 mm pole pair = 1.953125 µm/count** (datasheet RESinc 10 bit). **Index** pulses once per pole pair. The **SSI**
  (CSn/CLK/DO) reads the **12-bit** absolute position within the pole pair (4096 steps = **0.48828125 µm**) and its
  status bits (OCF, COF, LIN, MagINC, MagDEC) for the field-strength check.
- **Resolution decision (D1):** rev A combines the two. The PCNT count tracks motion between SSI reads and fixes
  the pole pair; the SSI word, read in the sensor loop, gives the position inside it. Position =
  pole pair × 2 mm + SSI × 2 mm / 4096, with the pole pair taken from the count (the firmware learns the fixed
  offset between the count's position in the pole pair and the SSI's top 10 bits at power-up, and flags
  SENSOR_ERR and falls back to the count alone if they drift apart by more than ±2 edges). Internal resolution is therefore **0.488 µm** (488.28125 nm); the display shows 0.01 mm. The
  firmware track implements it (`meas_counts_to_nm` + SSI fine part). This is resolution, not accuracy: the tape
  pitch error and the mechanics set the accuracy (§1).
- MagINCn / MagDECn are open-drain: pulled up to +3V3_SNS, then read on MAG_INC_N / MAG_DEC_N.
- Prog pin is tied to VSS (no OTP programming in rev A).
- Air gap 0.3 mm ±0.1 between the IC's top surface and the tape. The mechanics hold it with gibs and set it per
  unit with the tape shim (§7).

### 4.2 Capacitive front-end (experimental, isolatable)
- **TX:** 8 GPIO outputs (CAP_TX0…CAP_TX7). Each goes through a 0402 0 Ω jumper (**R60…R67**, DNP-able) and a
  100 Ω series resistor (**R70…R77**) to its electrode phase (net CAP_EL_TXn). Phase n connects to every 8th finger.
- **Electrodes in the schematic:** symbol/footprint **E40** (`caliper:CAP_ELECTRODES`, not in the BOM or the CPL)
  carries one seed pad per electrode net: pads 1–8 = TX0…TX7, eight **0.30 × 3.80 mm** fingers at 0.635 mm pitch (one
  5.08 mm repeat), pad 9 = RX, a **5.08 × 1.30 mm** strip whose centre is **3.75 mm** below the finger centre (§2.2
  table, D5). Layout places E40 on the bottom at the −x start of the comb (x 10.68) and draws the rest of the comb
  (8 repeats, 40.64 mm) and the RX strip as copper on the same nets.
- **RX:** receive electrode (CAP_EL_RX) → 0 Ω jumper **R80** (DNP-able) → charge amplifier U40A
  (**TLV9062IDGKR**, 10 MHz GBW RRIO CMOS, LCSC C398356; feedback 10 pF C0G ‖ 10 MΩ) biased at
  CAP_VREF = +3V3_SNS/2 (100 k/100 k + 1 µF, buffered by U40B) → 2nd-order RC low-pass 390 Ω/1 nF + 3.9 kΩ/100 pF
  (both poles ≈ 408 kHz) → **CAP_RX** (ESP32 ADC1_CH0, GPIO1).
- **Drive (D5):** the firmware drives the 8 phases (a dedicated-GPIO bundle) as a rotating square pattern (phase n
  high while (n − step) mod 8 < 4) at **5 kHz rotation**: one step every 25 µs, 2 ADC samples per step at 80 kS/s.
  The ESP32-S3 ADC1 in continuous mode tops out near 83 kS/s, so the earlier 25–100 kHz cannot be sampled. The
  charge amplifier (10 pF ‖ 10 MΩ, corner 1.6 kHz) and the ≈ 408 kHz RC filter pass 5 kHz (TVP: the amplifier's
  gain at 5 kHz on the prototype).
- **Position:** the ADC samples are synchronously demodulated into I/Q. Because the ADC and the drive loop start
  at an unknown relative delay, each burst runs the pattern forward and then in reverse and takes the phase
  difference, which cancels the delay but halves the range: the position is **resolved modulo half a pitch
  (2.54 mm)** and the whole half-pitches are **tracked** between bursts. Tracking needs < 1.27 mm of motion between
  bursts, i.e. a **≈ 25 mm/s tracking limit** at ≈ 20 bursts/s; faster motion corrupts the capacitive coarse count
  (not the fine part). It is re-zeroed from the magnetic reading on ZERO, so the experiment never sets the
  displayed value.
- A guard ground pour surrounds the RX trace on all layers. No digital traces cross the front-end.

## 5. MCU pin map (ESP32-S3-MINI-1)

The authoritative copy is `nets.py: MCU_PINS`. The constraints behind it:
- Strapping pins: GPIO0 (BOOT button + 10 k pull-up), GPIO3 (CHG_INT_N, which may float high at
  boot; harmless while JTAG_SEL eFuse is unburnt), GPIO45 (must read **low** at reset, because VDD_SPI is 3.3 V;
  BUZZ gate with 100 k pull-down), GPIO46 (must be low or floating; RGB LED DIN, 100 k pull-down).
- USB: GPIO19 = D−, GPIO20 = D+. Native USB (TinyUSB composite CDC + MSC + HID, or USB-Serial-JTAG for
  flashing). 22 Ω series resistors are not needed (they're inside the S3); ESD at the connector.
- ADC: only ADC1 (GPIO1–10) works alongside Wi-Fi, so CAP_RX = GPIO1.
- Deep-sleep wake sources must be RTC GPIOs (GPIO0–21): IMU_INT1, the buttons, CHG_INT_N. They share one ext1
  ANY_LOW mask, so every one of them is active low.
- **IMU_INT1 (D8):** the LIS2DW12 drives INT1 **push-pull, active low, latched** (CTRL3 = 0x18). The net is U60 pin 12
  → U10 IO15 only: no pull-up or pull-down on it (checked in the netlist), so nothing fights the push-pull driver,
  and the firmware enables no RTC pull on GPIO15. The LIS2DW12 is on the always-on +3V3, so INT1 keeps its level in
  deep sleep. Do not add a pull on IMU_INT1 or IMU_INT2.
- Never use GPIO26 (the in-package PSRAM chip-select on R2 variants). GPIO27–32 aren't bonded out.
- The UART0 pins (GPIO43/44) are used as cap TX phases; the console is on USB.
- **Pin plan (per-mode pad states):** the state of every GPIO above in RESET / RUN / SLEEP / SHIP (direction,
  level, internal pull, hold, wake, owning peripheral, the board circuit on the net) lives in the firmware,
  `firmware/tools/pin_plan.py`, which generates the table the firmware applies (sleep entry, boot) and is
  exported as a hwtools `pinstate.json` (`firmware/tools/export_pinstate.py`, committed copy
  `firmware/test/hwtools/pinstate.json`, every state "assumed") for the pullaudit / boardcheck leakage checks.
  A schematic change to a pull, a strap or a rail on an MCU net must be mirrored there (`ext` of that pin);
  docs/firmware.md "Pin plan and sleep leakage".

## 6. Interfaces

| Bus | Devices | Notes |
|---|---|---|
| I2C (GPIO13 SDA / GPIO14 SCL, 4.7 k to +3V3, 400 kHz) | BQ25180 (0x6A), MAX17048 (0x36), LIS2DW12 (**0x19, SA0 high**) | SA0 has an internal pull-up that cannot be disconnected: a grounded SA0 (0x18) burns 60–170 µA |
| SPI2 (GPIO33 SCK / GPIO34 MOSI / GPIO35 CS / GPIO36 DC / GPIO37 RST) | ST7789 LCD | 40 MHz, write-only. Panel pin order per DM-TFT114-397 §3.1; connector 0.5K-AX-13PWB (13 P, 0.5 mm, bottom contact) |
| AS5311 SSI (GPIO7 CLK / GPIO8 DO / GPIO9 CSn) | AS5311 | bit-banged or SPI3, ≤1 MHz |

## 7. Mechanical envelope (detail in `hardware/mechanical/`)
- **Beam:** ground flat stock **20 × 4 mm**, 250 mm long (O1 or 1.4301). The front face carries two bands
  measured from the beam's lower (jaw-side) edge (beam lower edge = board y 0):
  - **Magnetic tape (D2): 8.0 mm wide** (slit from stock; a 10 mm tape at y 1…11 would overlap the scale band),
    centred at **y = 6.0**, in a **2.00 mm-deep channel** (8.2 wide, y 1.9…10.1, beam x 28…200). The tape face is
    1.25 mm below the beam face for a nominal package, because the AS5311 (A 0.85–1.20) and the electrodes sit on
    the same flat board bottom, 0.15 above the beam face. The channel depth gives the **tallest** package
    (A 1.20) the 0.30 mm gap with no shim; every shorter package is brought to **0.30 mm** with a **0–0.35 mm
    Kapton shim under the tape, chosen per unit** (0.025 steps; nominal A 1.10 needs 0.10). A shim only raises the
    tape, which only closes the gap; that is why the depth is set by A max. 2.00 mm of steel remains under it.
  - **Scale PCB:** 7 × 0.8 mm at y 10.5…17.5 in a 0.85 mm pocket (0.80 PCB + 0.05 467MP), **flush ±0.05** with the
    beam face, beam x 14.5…214.5 (§2.2).
- **Board support (D3):** the housing clamps the slider board at the two end tabs (§2.1): each tower carries two
  clamp faces (coplanar within 0.03 mm) and two M2 screws from its top face into the SMT standoffs on H2–H5. Tab
  pockets in the towers: x u 2…8 and 70…76, y 2.5…16.5, open to the bottom, clear of the front-pad pockets.
- **Battery pocket (D4):** u 29.5…65.5 (board x 21.5…57.5), y 22.4…48: ≥ 5.5 mm from the antenna. The right Y-gib
  plunger (u 58.5) and the locking screw (u 63) move out of that span (mechanics' choice).
- **RF (D4):** within 5 mm of the antenna area (board x 0.6…16, y 29.5…34; slider u 8.6…24) nothing metal and
  nothing carbon-filled: in rev A that means the PA-CF body is opened under and beside the antenna (or the body
  is printed in unfilled PA/PETG), and the PA-CF moving inside jaw (2.2 mm from the antenna's −x end) is noted as an
  RF risk to check. In rev B the 6061 body needs a non-metal window there and the front shell must be printed.
- The slider housing straddles the beam: printed PETG/PA-CF in rev A, CNC 6061 in rev B. Brass gibs with
  M2 set screws + springs set the 0.3 mm (magnetic) and 0.15 mm (capacitive) gaps. The fixed jaw is
  bolted and dowelled to the beam end. The moving jaw is part of the slider housing.
- Housing outside: ≤ 78 × 52 × 16 mm, including the thumb wheel/roller.

## 8. Firmware contract (detail in `docs/firmware.md`)
- The BLE GATT service UUIDs and the characteristic layout are defined once in
  `caliper/firmware/main/proto/caliper_gatt.h` and mirrored in **`public/caliper/app/protocol.js`** (the web app
  lives in `public/caliper/app/`, published with the docs site; the empty `caliper/app/` was removed) (D7).
- **Advertising:** the advertisement or the scan response carries the complete **128-bit service UUID**
  (`7c0a0001-5e1f-4b8a-9c3d-2f6a1e0c7b11`); the app's chooser filters on it. Rev A puts it in the scan response.
- **LIVE (D6):** **12 bytes** `{i32 value_nm, i32 cap_nm, u8 unit, u8 flags, u16 active_profile_id}`;
  `active_profile_id` 0 = none. Readers accept **10 or 12 bytes** (10 = firmware from before this change: active
  profile unknown) and ignore anything past 12. Reason: a profile chosen on the caliper's own MODE menu was
  invisible to the app, which then judged readings against a stale band. Appending keeps old readers working.
- **Flags** (LIVE and the log record use the same bit meanings): bit 0 HOLD, 1 TOL_PASS, 2 TOL_FAIL, 3 SENSOR_ERR,
  4 CAP_VALID, 5 CHARGING.
- **Log record:** `{u32 seq, u32 unix_s, i32 value_nm, u8 unit, u8 flags, u16 profile_id}` = 16 bytes. After LOG_READ
  the records come packed in notifications; the **end marker** (seq = 0xFFFFFFFF, 12 zero bytes) is sent **in a
  notification of its own**, so a reader never has to split a packet at the marker.
- **COMMAND errors** (ATT error codes on the write response): **0x06** unknown opcode; **0x0D** wrong length for the
  opcode; **0x80** bad argument (e.g. SET_UNIT other than 0/1). PROFILES and SETTINGS writes use 0x0D for a bad
  length (PROFILES not a non-zero multiple of 30 or more than 16 records; SETTINGS over 240 bytes or a result that
  would not serialise in 240) and 0x80 for a bad value.
- **PROFILES:** a write is a **per-record upsert** by id, applied **all or nothing**. **Delete** = a record with an
  **empty name and nominal = tol_minus = tol_plus = 0** (deleting an unknown id is a no-op). **At most 16 profiles**
  are stored (`CALIPER_PROFILES_MAX`; also the most records per write); a write that would exceed it is refused
  (0x80) and changes nothing. **Profile id 0 = none**: never stored, a record with id 0 is refused (0x80),
  SELECT_PROFILE 0 clears the selection. **Tolerances are magnitudes**: band = nominal − |tol_minus| …
  nominal + |tol_plus|, inclusive; writers send them positive, readers ignore a sign.
- **SETTINGS:** UTF-8 JSON object ≤ 240 bytes. A **write needs an encrypted link** (it can carry `wifi_pass`): an
  unpaired write is refused by the stack (NimBLE: 0x05 Insufficient Authentication; 0x0F from some stacks) and the
  client pairs and retries. A write is a **partial update**: an absent key keeps its stored value (an absent
  `wifi_pass` keeps the stored password; `""` clears it); unknown keys are ignored; one bad value rejects the whole
  write. **Limits:** `name` ≤ 20 B; `wifi_ssid` ≤ 32 B; `wifi_pass` 8…64 B or `""` (write-only, never in a read);
  `mqtt_url` ≤ 64 B with `mqtt://`, `mqtts://`, `ws://` or `wss://`; `http_post_url` ≤ 64 B with `http://` or
  `https://`; `auto_off_s` a JSON number, 0 (never) or 30…3600; `hid_suffix` `"\n"`, `"\t"` or `""`; `decimals` a
  JSON number 1…3. **`decimals` applies to mm; inch shows two more** (2 → 0.01 mm / 0.0001 in). The defines are
  `CALIPER_SET_*` in caliper_gatt.h; `settings.h` must agree.

## 9. Capture changes log (rev A schematic, 2026-11-07)
Changes made while capturing the schematic (the reasons are in the sections above and in docs/electronics.md):
1. ESP32-S3-MINI-1-**N4R2** fixed (N8R2 not stocked at LCSC).
2. LIS2DW12 SA0 **high → 0x19** (was SA0 low / 0x18): `nets.I2C_ADDR` updated.
3. New switched rail **+3V3_UI** (U6, TPS22917, also on SNS_PWR_EN) for the LCD VDD and the RGB LED; added to
   `nets.POWER_NETS`.
4. Sleep budget target revised to **≤ 35 µA** (the buck-boost Iq + its divider made the first-draft figure unreachable).
5. Capacitive front-end reference designators and values fixed (R60–R67, R70–R77, R80–R85, U40, E40).
6. RGB LED is a WS2812B-2020-V6 (3.3–5.3 V per LCSC), on +3V3_UI with no level shifter.
7. Schematic review (2026-11-07): backlight series resistor R50 10 Ω → **15 Ω** (C22810), because 10 Ω drove the
   panel LED at 31–41 mA against its 20 mA rating; sleep-budget line items corrected (TPS22917 off current, the
   firmware conditions behind the 3 µA BQ25180 / MAX17048 figures, conversion loss); BQ25180 `IBAT_OCP` ≥ 1 A noted.
   No net, pin or address changed.

## 10. Contract reconciliation decisions (2026-11-07, after the phase 2 reviews)
Designed, not built: every number here is a design value until the prototype passes bring-up. Each decision is
detailed in the section named; this list gives the decision and its reason.

| # | Decision | Reason | Where |
|---|---|---|---|
| D1 | Internal resolution **0.488 µm**: PCNT coarse count (1024 edges per 2 mm = 1.953125 µm) combined with the 12-bit SSI fine position (2 mm / 4096 = 488.28125 nm) | 0.488 µm was quoted as the count, but it is the SSI step; interpolating keeps the stated figure with no hardware change, and the PCNT still tracks fast motion between SSI reads | §1, §4.1 |
| D2 | Tape **8 mm wide** (slit), centred y 6, in a **2.00 mm channel**, **0–0.35 mm Kapton shim per unit** for the 0.30 gap; scale pocket stays flush. No bottom parts over y 0…20 except the AS5311 + its 2 capacitors inside y 2.4…9.6, x 20…41, ≤ 1.30 tall, and the electrodes | A 10 mm tape overlaps the scale band; the AS5311 and the electrodes share the flat board bottom, so the tape must sit lower; a shim can only close the gap, so the channel is cut for A max | §2.1, §7 |
| D3 | Slider outline **74 × 34**: end **tabs** x −6…0 and 62…68, y 2.5…16.5, with **SMT M2 standoffs** on plated holes H2–H5 clamped by the towers as the **Z datum**; H1 (18.75, 24) the only upper-band hole (support only); **flatness ≤ 0.03 mm over y 0…20** | The lower band (AS5311, electrodes) was held only by bosses at y > 22, 7–24 mm away; nothing can go under the board over the beam (0.15 mm), so the tabs are pulled up from above; y 2.5…16.5 keeps them clear of the front pads | §2, §2.1, §7 |
| D4 | **Landscape display** (31 mm along X) over the beam band; **MINI-1 in the top-left corner**, antenna flush with the top edge, all-layer keep-out x 0…21, y 29…34; buttons ZERO / HOLD / MODE at x 31 / 38.5 / 46, y 31; USB-C right edge y 26.5; battery pocket moved to board x ≥ 21.5; full placement table | Portrait glass (y 1.5…32.5) left no room for the module, MODE and USB-C together (the clash check's U_MCU × SW_MODE and MODE cap × USB-C). Landscape frees the upper band and makes the digits ~1.8× wider. The battery behind the old module position (x 39…55) and a USB-C 1 mm from the antenna would have detuned it; the top-left corner keeps both away | §1, §2.1, §7 |
| D5 | Scale coupler/reflector bands aligned with the slider RX/TX (one coordinate table); scale pattern 38 cells centred on the electrode sweep (SCALE_X0 14.5); scale bonded, no screws; **5 kHz** rotation, position **modulo 2.54 mm**, tracked, **≈ 25 mm/s** limit | The bands only partly overlapped (RX 10.6…11.8 vs coupler 11.0…12.8); the ADC tops out near 83 kS/s; the forward/reverse burst that cancels the ADC delay halves the range | §2.2, §4.2 |
| D6 | GATT clarifications (magnitudes, upsert, delete, 16 max, id 0, end marker alone, error codes, encrypted SETTINGS write, partial update, field limits, decimals, LOG flags, UUID in the scan response) and **LIVE = 12 bytes** with `u16 active_profile_id` (readers accept 10 or 12) | These were implemented one way in the firmware and guessed in the app; the app could not see a profile chosen on the caliper | §8, caliper_gatt.h, protocol.js |
| D7 | The app lives in `public/caliper/app/` | the empty `caliper/app/` was removed | §8 |
| D8 | RT1 (10 k NTC on TS) **populated**, firmware **TS enabled**; IMU_INT1 is push-pull, active-low, latched with **no pull** on the net | Checked in the netlist and the firmware defaults; a pull on a push-pull line would only waste current, and ext1 ANY_LOW needs every wake line active low | §3, §5 |
| D9 | Sleep target **≤ 35 µA** everywhere | the buck-boost's Iq and divider alone exceed the first-draft figure | §3, docs |
