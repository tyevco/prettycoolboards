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
| Power | 1S LiPo, 501230 class: **Renata ICP501230PS-03** (with protection circuit; 135 mAh typ / 130 min; ≤ 5.4 × 12.5 × 31.5 mm including it; 1C = 135 mA continuous / 2C = 270 mA pulse discharge; 0.5C standard / 1C max charge, CC/CV to 4.2 V). Slim housing, owner decision 2026-11-09: was a 402535, ~500 mAh. On JST-SH 2-pin J2 (board bottom, §2.1; an SHR-02V-S plug crimped on the cell's AWG30 leads). USB-C (USB 2.0 device) charging at **70 mA** (0.52C; firmware `CONFIG_CALIPER_CHARGE_MA`, range ≤ 135 mA = 1C; was 250 mA). On battery (no VBUS) the firmware keeps the cell inside its 2C pulse rating: Wi-Fi TX capped at 10 dBm, and no Wi-Fi below a 3.50 V cell reading (off below 3.40 V) (§3) |
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
copper under solder mask, nothing proud of it. Bottom in y 22…34: flat test pads only (no parts; the battery
pocket is below), **except J2 and under the module**. **J2** (the cell's JST-SH receptacle) is on the bottom since
2026-11-09 (slim housing, owner decision): footprint origin (24.1, 24.9), body x 22.1…26.1, y 23.2…27.5, **2.95 mm
tall below the board**, mating face toward +y; it and the mated plug (x 21.9…26.3, y 27.5…32.1) hang into the
battery pocket's J2 bay (board x 21.5…27.6, y 22.4…35.1), ≥ 6.3 mm in plan from the antenna area and ≥ 0.9 mm from
H1's boss. Under the module (x 1.8…4.4, y 22.7…27.0, left of the battery pocket) sit the module's
100 nF + 10 µF decoupling C21 / C23 and the ADC input's RC filter R85 / C44, 0402, ≤ 0.55 mm tall against the
0.75 mm housing-floor gap there (§12, §13). The extension of this exception from y 24.8 down to y 22.7 for R85 / C44
(§13 R5) was **accepted by the owner on 2026-11-09** (§11).

**Placement table (D4).** Centre coordinates in board mm; rotation in degrees as seen from the top, 0 = the
footprint's own orientation; the layout script may move a part ≤ 1 mm without a SPEC change if every rule here
still holds (the mechanics re-run `clash_check.py` on the extracted envelope). **The positions below are the routed
rev A board (2026-11-08, §11)**; where layout moved a part more than 1 mm from the first-draft table, the old value
is given in the notes.

| Ref | Part | Side | x | y | Rot / orientation | Envelope, notes |
|---|---|---|---|---|---|---|
| U10 | ESP32-S3-MINI-1-N4R2 | top | 7.85 | 24.25 | 0: antenna end toward +y | footprint origin (draft 8.3); outline x 0.15…15.55, y 14.0…34.0 (antenna area y 29.5…34.0 flush with the top edge, the top-left corner); h 2.55. Not under the glass |
| — | Antenna keep-out | all 4 layers | | | | **x 0…21.0, y 29.0…34.0: no copper (pads, tracks, vias, zones), no parts, either side.** The footprint has none: layout draws it as a rule area. As routed, the rule area starts at y 29.2: a pour edge in y 29.0…29.2 and the module's own pads are the only copper in x 0…21, y 29.0…34 (§11). See "Antenna" below |
| J50 | 13p 0.5 mm FPC, 2.0 tall, HDGC 0.5K-AX-13PWB (C2911931), bottom contact | top | 21.5 | 7.5 | contact row along y at x 23.35, opening toward −x; **pin 1 at y 10.5 (the +y end), pin 13 at y 4.5** | under the glass's −x end: the panel tail leaves the glass at x 17.5 and folds back under it into J50 (TVP: tail length of the bought panel). Land drawn from the vendor drawing (§12). **Tail orientation:** the fold turns the tail over, so the tail's contacts must face the viewer (the display side) when the panel lies flat, face up, tail toward −x; the fold keeps y, so the tail's pin 1 must be on its +y side (toward the buttons) |
| — | Display glass (on the lid, not the board) | — | 33.0 | 10.0 | landscape, FPC at the −x end | glass 31.0 × 17.6 × 1.6: x 17.5…48.5, y 1.2…18.8; active area 24.91 × 14.86, centre (34.45, 10.0) (shifted 1.45 away from the FPC end, TVP); lid end ribs x 16.15…17.5 and 48.5…49.85 |
| J1 | USB-C HRO TYPE-C-31-M-12, top-mount | top | 59.3 | 26.5 | opening toward +x | shell x 55.65…63.0 (1.0 mm past the edge), y 22.03…30.97, h 3.26 (mechanics DEV-4: y 26.5) |
| U1, D1 | USBLC6-2SC6, SMF5.0A | top | 50.2 / 52.7 | 26.3 / 19.95 | D1 180: VBUS pad 1 east | within 5 mm of J1's pads (draft: both at (53.0, 24.0) in x 50.5…55.0, y 21.0…27.0). U1 sits on the USB pair, which runs on B.Cu along y 19.2…19.6 over an In2 GND strip; D1 (moved from (51.3, 22.0), §13) sits on the VBUS trunk: both J1 VBUS pad pairs land on its pad 1, the run to C1 / U2 leaves from it |
| SW50 | ZERO, TS-1088 3.9 × 2.9 × 2.0 | top | 31.0 | 31.0 | 0 | cap stem Ø3.5 at slider u 39 |
| SW51 | HOLD/SEND | top | 38.5 | 31.0 | 0 | u 46.5. The mechanics' x 18.5 (DEV-5) only kept the cap off the old portrait glass; with the landscape glass that x is inside the antenna clearance, so it moves here (the cap still clears the glass rib, y ≥ 28 vs ≤ 20.15) |
| SW52 | MODE | top | 46.0 | 31.0 | 0 | u 54; courtyard x ≤ 49, clear of J1 (x ≥ 53.7) and the antenna |
| D50 | WS2812B-2020 RGB LED | top | 51.5 | 32.0 | 0 | light pipe in the lid at u 59.5 |
| J2 | JST-SH SM02B-SRSS-TB, 2.95 tall | **bottom** | 24.1 | 24.9 | 0 (flipped): mating face toward +y (the top edge), signal pads toward −y | footprint origin; pad row y 22.9, **pin 1 (VBAT_RAW) x 23.6**, pin 2 (GND) x 24.6; fitting nails (GND) x 22.3 / 25.9, y 26.8. Body x 22.1…26.1, y 23.2…27.5, 2.95 below the board; mated plug x 21.9…26.3, y 27.5…32.1, both in the battery pocket's J2 bay (bottom-side rule above). Courtyard x 21.2…27.0. Pin 1 reaches Q1's drain on top through a via at (23.6, 21.6) (§3). Was top (24.5, 30.6), rot 180, mouth over the top edge with a plug relief past y 34 in the housing (moved 2026-11-09 for the slim housing) |
| RT1 | 10 k NTC (TS) | top | 22.3 | 26.75 | | over J2 (bottom) and the cell's lead end (draft 24.5, 26.5: moved for Q1) |
| Q1, R10 | AO3401A battery reverse-polarity P-FET, 10 k gate resistor | top | 25.1 / 22.5 | 25.1 / 23.5 | Q1 90: drain pad up | §3. Q1 sits over J2 (bottom); VBAT_RAW runs from J2 pin 1 (23.6, 22.9) down to a via at (23.6, 21.6) and on F.Cu up between Q1's gate and source pads into the drain pad (25.1, 26.04) |
| BZ50 | PKMCS0909E piezo, 1.9 tall | top | 40.0 | 24.3 | 0 | courtyard x 34.75…45.25, y 19.55…29.05; sound port in the lid at u 48 |
| U60 | LIS2DW12 | top | 30.0 | 23.5 | | ≥ 15 mm from L1 |
| U2, U3, L1, U5, U6, C1–C6, C8–C13, R3–R5 | charger / buck-boost / rail-switch cluster | top | 56.0 | 11.0 | | inside x 50.5…61.5, y 2.5…20.5 (not under the glass; ≤ 4.2), except C8 (51.3, 1.55) and C10 (49.75, 5.5), held ≤ 2 mm from U5 and up to 0.95 outside the box. L1 and the U3 switch nodes ≥ 10 mm from U40 and the RX feed |
| U4, C7 | MAX17048 fuel gauge + its VBAT cap | top | 29.6 / 27.37 | 27.2 / 26.3 | C7 90 | beside J2 (draft: in the cluster above); C7 left of U4's VBAT pins 2/3 |
| R6–R9 | I2C pull-ups (R6, R7, **2.2 k**) and the CHG_INT_N / FG_ALRT_N pull-ups (R8, R9) | top | 5.1…9.0 | 3.7…5.8 | | below the module, left of the glass (draft: in the cluster) |
| C21, C23 | module 100 nF / 10 µF, 0402 (0.5 mm) | **bottom** | 3.1 | 26.5 / 25.3 | 0; +3V3 pad toward x 2.6 | under the module, either side of pad 3's escape via (2.0, 25.95): their +3V3 pads are 1.9 mm from pad 3 (0.85, 25.95). Pad 3 is 0.45 mm from the left edge and the antenna keep-out is above it, so the top has no closer spot (§12) |
| R85, C44 | CAP_RX anti-alias RC (3.9 k / 100 pF C0G), 0402 (0.5 mm) | **bottom** | 3.3 | 24.25 / 23.25 | R85 180, C44 0: their CAP_RX pads toward x 2.8 | under the module below C23, beside GPIO1's escape via (2.0, 24.25): the RC sits at the ADC input and the long run is CAP_LP1 (§13; they were at U40, 40 mm of track from GPIO1) |
| C13 | U6 (+3V3_UI switch) input cap, 1 µF 0402 | top | 52.25 | 10.3 | 0 | under U6's VIN / GND pins (§13) |
| C20 | module 22 µF bulk, 0603 | top | ≈ 2.75 | ≈ 5.5 | | below the module, about 20 mm from pad 3, fed through the In2 +3V3 pour (the bulk; the 100 n / 10 µ above do the local decoupling) |
| U30 | AS5311 TSSOP-20 | **bottom** | 31.0 | 6.0 | long axis along X | body x 27.75…34.25, leads y 2.8…9.2, A ≤ 1.20 |
| C30, C31 (AS5311 100 nF, 1 µF) | 0402 | **bottom** | 35.45 / 36.5 | 8.6 / 6.0 | (C30 draft: 25.5, 6.0, 8.1 mm from the VDD pins) | inside the channel window above; the MagINC/MagDEC pull-ups and TP30–32 go on top |
| E40 + comb | electrodes | **bottom copper** | 31.0 | 14.2 | | §2.2 table: x 10.68…51.32, y 10.35…18.05 incl. guard |
| U40, R80, AFE passives | TLV9062 charge amplifier | top | 42.0 | 5.0 | | under the glass (1.1 tall); RX feed via into the RX strip at x ≈ 42 |
| R60–R67, R70–R77 | TX jumpers + series R | top | 2.3…9.65 | 8.0 / 10.4 | 90 | two rows at 1.05 pitch, x 1.8…10.2, y 7…11.2 (draft: x 3.5…16, y 2.5…12), left of the glass, below U10; TX phases feed the comb at its −x end |
| SW20 | BOOT, TS-1088 | top | 27.0 | 15.7 | 90 | under the glass, no cap: used with the lid (and glass) off |
| R50, Q50, R51 | backlight | top | 27.0 / 28.1 / 28.7 | 7.4 / 3.6 / 7.0 | | under the glass, beside J50 (draft: 25.5, 4.0) |
| Q51, R56, R57 | piezo driver | top | 47.35 / 46.2 / 33.7 | 20.4 / 23.7 / 19.5 | | Q51 and R56 right of BZ50, R57 at its left (draft: 40.0, 18.0) |
| TP1–7, TP20–23, TP30–32, TP40–42, TP50–51 | 19 × Ø1.0 test pads | **bottom** | 27.58…47.9 | 22.6 / 25.14 / 30.22 | x 22.5 + 2.54 i, three rows | bench bring-up with the board out of the housing; nothing in the antenna keep-out, on the H1 pad, in J2's courtyard or under the mechanics' ledge (y ≥ 32.6). y 25.14: TP50, TP51, TP7, TP4, TP2, TP3, TP1 (x 32.66…47.9); y 22.6: TP32, TP40, TP41, TP42, TP5, TP6, TP22 (USB, x 42.82), TP23 (USB, x 47.9) from x 27.58; **y 30.22: TP20 MCU_EN, TP21 BOOT_N, TP30 MAG_A, TP31 MAG_B at x 32.66 / 35.2 / 37.74 / 40.28** (moved 2026-11-09 from x 22.5 / 25.04 of the two lower rows, where J2 now is) |
| H1 | M2 plated hole, Ø4.4 pad | both | 18.75 | 24.0 | | **nylon** M2 × 10 flat-head screw (5 mm from the antenna corner) from the lid's top face through the lid's Ø4.4 tube and the board into a body boss (u 26.75); since 2026-11-09 it is also the lid's upper fastening. Support only, see "Board support". **Top side: a Ø4.6 circle round H1 stays free of parts** (2026-11-09: the lid's Ø4.4 tube ends 0.1 mm above the board there, in place of the old Ø3.8 screw head; `layout.py` `check_h1_tube` checks the courtyards, nearest 0.6 mm outside it). Bottom: J2's nearest nail pad edge is 0.75 mm from the pad |
| H2, H3 | tab clamp holes | tab | −3.5 | 5.5 / 14.0 | | Ø2.2 plated (GND), top pad Ø4.4 for an SMT M2 standoff; bottom: no exposed copper (0.15 above the beam) |
| H4, H5 | tab clamp holes | tab | 65.5 | 5.5 / 14.0 | | as H2/H3 (H5 is in the schematic since §12) |
| FID1–3 | fiducials, Ø1 / mask Ø2 | top | (2.0, 1.5), (60.5, 1.2), (33.0, 27.6) | | | outside the antenna keep-out and every courtyard (FID3 draft (60.5, 32.8) was inside J1's courtyard) |

**Antenna (D4).** The ESP32-S3-MINI-1's PCB antenna is the module's top 4.5 mm (the footprint's Fab "Keepout
Area"). Espressif's guideline (ESP32-S3-MINI-1 datasheet land pattern and the ESP32-S3 hardware design
guidelines, "positioning a module on a base board"; the KiCad footprint courtyard encodes it as 15 mm on each
side and beyond the antenna) is: antenna at the board edge, nothing conductive under it on any layer, and
≥ 15 mm of clearance around it. Rev A: the antenna area sits flush with the top edge in the **top-left corner**
(board edges on two sides), with the all-layer keep-out above under it and 5.0 mm to its right (x 16…21). 15 mm
sideways does not fit a 62 mm board that also carries a USB-C and three buttons along the same edge: that is a
recorded deviation, to be checked by an RSSI/range test at bring-up. Every metal part keeps ≥ 5 mm in plan from
the antenna area: the LiPo (the battery pocket moves to board x ≥ 21.5, D4/§7; the cell itself starts 12 mm away),
J2 and its plug (6.3 mm), the USB-C (39 mm away), the H1 screw (nylon), the SMT standoffs. The beam's upper edge is
9.5 mm below the antenna. Since 2026-11-09 the firmware also caps Wi-Fi TX at 10 dBm for the small cell (§3), about
10 dB less link margin than at full power: the bring-up range test covers both.

**Board support (D3).** The **Z datum is the four tab clamps H2–H5**: each carries an SMT M2 threaded standoff
(2.0 mm tall, OD ≤ 4.0 mm, soldered on the top pad; PEM SMTSO-M2-2ET class, **fitted by hand**: no LCSC/JLC part
fits, §12), and an M2 screw from the tower's top face pulls the standoff's top face up against a
clamp face in the tower (the left tower spans u 0.5…7.6, the right u 70.4…77.4 (the roller rim reaches u 78.0); the tabs sit at u 2…8 and
70…76, y 2.5…16.5, which keeps them 0.65 mm clear of the front-pad pockets and the pad set-screw inserts).
These four points sit at the ends of the sensor band, 3.5 mm and 12 mm from the AS5311 and electrode rows.
The four clamp faces must be coplanar within 0.03 mm (the mechanics choose how: faced brass washers, insert
faces, or the rev B machined tower). **H1** in the upper band is a support against button and cable loads, not a
datum: it must not pull the board out of the tab plane by more than 0.01 mm (the boss is printed low and shimmed;
with the lid off, a ~3 N press at H1 moves the board ≤ 0.01 mm on a dial indicator, docs/mechanical.md §7 step 6).
Since 2026-11-09 its nylon M2 × 10 screw comes from the lid and also holds the lid's upper part; the lid's Ø4.4 tube
ends 0.1 mm above the board, so the screw does not clamp the board against the boss. The mechanics' upper-band holes
(3, 24.5) and (3, 31) are now under the MINI-1, and (59, 32.6) has its Ø4.4 pad crossing the top edge and its
screw head over the USB-C, so all three are replaced by H1 and the tabs. No other upper-band hole fits: the
battery pocket has no body under the board, and the USB-C fills the right end above y 22.

**Battery**: a 501230-class protected cell (reference Renata ICP501230PS-03, 135 mAh, ≤ 5.4 × 12.5 × 31.5 mm; §1) in
the housing pocket behind the board's upper band (not on the beam), on J2. **Slim housing (2026-11-09, owner
decision):** it replaces the 402535 (~500 mAh, 4 × 25 × 35), so the housing ends just above the board. The pocket is
**u 29.5…67.6 (board x 21.5…59.6), y 22.4…35.1**, floor z −7.0 (was u 29.5…65.5, y 22.4…48); the cell lies at
u 35.6…67.1, ≥ 12 mm from the antenna (D4), with 1.0 mm of thickness swelling room under the button ledge. J2 moves
to the bottom (above) so the receptacle, the plug and the cell leads stay inside the pocket's J2 bay (u 29.5…35.6,
board x 21.5…27.6) instead of passing the top edge.

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
                                     └─ BAT → VBAT (MAX17048 CELL/VDD) ─ Q1 P-FET (reverse polarity) ─ VBAT_RAW ─ LiPo (JST-SH J2)
+3V3 ─ TPS22917 load switch U5 (SNS_PWR_EN) → +3V3_SNS (AS5311, capacitive front-end op-amp + VREF)
+3V3 ─ TPS22917 load switch U6 (SNS_PWR_EN) → +3V3_UI  (ST7789 VDD, WS2812B-2020-V6 RGB LED)
+3V3 ─ 15 Ω ─ backlight LED (LEDA/LEDK) ─ low-side AO3400A (LCD_BL, PWM)   (≈ 20 mA at the panel's VF 3.0 V / 20 mA rating)
```
- **+3V3_UI** (added during capture): the ST7789 still draws 15 + 5 µA typ in sleep-in mode (DM-TFT114-397 §5.3)
  and a WS2812 draws standby current, so both are switched off in deep sleep. There is no free GPIO, so U6 shares
  SNS_PWR_EN with U5: both rails are on whenever the caliper is awake. Both switches tie QOD to VOUT (fast discharge)
  and use a 1 nF CT for a slow ramp. Before switching off, the firmware drives every signal into those rails low
  (MAG_CSN/MAG_CLK, LCD_*, RGB_DIN) so nothing back-powers through ESD diodes.
- **Battery reverse-polarity protection (Q1, added 2026-11-08, §12):** a P-MOSFET "ideal diode" in the cell's
  BAT+ lead: **AO3401A** (Alpha & Omega, LCSC C15127, JLC **Basic**, SOT-23), drain to J2 pin 1 (net VBAT_RAW), source
  to VBAT, gate to GND through R10 10 k. With a correct cell the body diode conducts first, then VGS = −VBAT turns the
  channel on; it conducts both ways, so the BQ25180 charges through it. A reversed cell leaves VGS = 0 (off, VDS −4.2 V
  against −30 V, IDSS ≤ 1 µA). VGS max is ±12 V and the gate never sees more than the cell (≤ 4.4 V), so there is **no
  zener**. The BQ25180 BAT pin, C3 and the MAX17048 CELL/VDD stay on the protected VBAT side.
  Datasheet (AO3401A Rev 3.1, Dec 2023): RDS(on) ≤ 60 mΩ at VGS −4.5 V (47 typ), ≤ 85 mΩ at −2.5 V (60 typ), ×1.5 at
  TJ 125 °C; VGS(th) −0.5…−1.3 V; RθJA ≤ 125 °C/W.
  **At 0.5 A** (the Wi-Fi peak from a low cell) and a 3.0 V cell (VGS ≈ −3.0 V; the −2.5 V maximum is used as the
  bound): drop **≤ 43 mV** (≈ 28 mV typical), dissipation **≤ 21 mW** (≈ 14 mW typical), ≈ 3 °C rise; ≤ 64 mV /
  32 mW at TJ 125 °C. At a full cell (VGS −4.2 V) ≤ 30 mV / 15 mW. Charging at 70 mA (250 mA before 2026-11-09):
  ≤ 6 mV / 0.4 mW; the charger regulates VBAT at its own pin, so in CC the cell sits up to 6 mV lower and in CV the drop fades with the current.
  The fuel gauge reads the cell through Q1, so under load it reads up to the same drop low (TVP).
  **Board copper on top of Q1 (pre-routed 2026-11-08, §13; estimate, not measured):** VBAT runs from Q1's source to
  U2 BAT / C3 as a locked trunk: Q1's source pad on F.Cu, 3 vias, a 1.6 mm B.Cu riser (2.0 mm until 2026-11-09: it
  now keeps 0.25 mm from J2's nail on the bottom) to a 2.1 mm B.Cu band along
  the top edge (a 1.3 mm F.Cu strip in parallel over x 28…48.6), a 1.9 mm B.Cu riser down x 58.4 between J1's shell
  tabs (band and riser doubled on 0.5 oz In2), 4 vias beside U2, F.Cu to C3 and the BAT ball (0.25 mm neck, 0.15 mm inside the ball's mask opening).
  Resistor-network estimate from the board copper (35 µm outer, 15.2 µm inner, 20 µm via plating): **≈ 12 mΩ** Q1 →
  BAT ball (was ≈ 0.095 Ω as a 0.30 mm track with three single-via layer changes), ≈ 6 mV at 0.5 A on top of Q1's
  ≤ 43 mV. J2 → Q1 (VBAT_RAW, 0.60 mm): ≈ 2 mΩ with J2 on top; with J2 on the bottom (2026-11-09) 1.3 mm of B.Cu,
  one 0.5 / 0.25 via (≈ 1 mΩ) and 5.1 mm of F.Cu, ≈ 6 mΩ (≈ 3 mV at 0.5 A; estimate). The whole system current takes this path when
  USB is absent.
  **Reversed cell with USB present:** the charger tries to charge; VBAT cannot rise above |VGS(th)| (≈ 0.5–1.3 V)
  before Q1 turns on into the reversed cell, which keeps VBAT below the BQ25180's VBATSC (1.6–2.0 V), so it stays in
  trickle charge at IBATSC ≈ 8 mA (SLUSE99C) and times out on its precharge safety timer. Q1 then dissipates
  ≈ 8 mA × (4.2 + ~1) V ≈ 40 mW in its linear region: harmless. SYS still runs from USB. Not tested (TVP).
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
  dial-me-spinner `docs/firmware.md §13.1`. /INT goes to CHG_INT_N. `IBAT_OCP` = 1 A, its reset value (CHARGECTRL1 0x52; was 1.5 A):
  a fault limit, not the cell's 2C rating. Not 500 mA (SLUSE99C Table 8-15): an uncapped Wi-Fi burst from a low cell
  (0.42–0.49 A) comes within a few percent of it, and 4–7 trips in 2 s latch the BATFET off until USB is plugged in
  (§8.3.7.5). Charge (since 2026-11-09, for the 135 mAh cell, §1): ICHG **70 mA** (0.52C; ICHG_CTRL 0x22), ITERM 10 % =
  7 mA, precharge 2 × ITERM = 14 mA (CHARGECTRL0 0x20), VBATREG 4.20 V, 6 h safety timer; the input limit is unchanged
  (100 mA until enumerated, then 500 mA). The cell's 2C (270 mA) pulse rating is kept by the firmware: Wi-Fi TX capped
  at 10 dBm (`CONFIG_ESP_PHY_MAX_WIFI_TX_POWER`; ≈ 0.21–0.29 A from the cell, *estimate*) and, without VBUS, no Wi-Fi
  below a 3.50 V cell reading (`CONFIG_CALIPER_WIFI_MIN_MV`; off below 3.40 V); BLE stays at 9 dBm
  (docs/firmware.md §12.6). Not measured (TVP: VBAT on a scope during a Wi-Fi sync at 3.5 V, no BAT_OCP or BUVLO flag).
- **TS (D8):** RT1, a 10 k B3435 NTC (Murata NCP15XH103F03RC, C77131) from TS/MR to GND, is **populated** (it is
  in the BOM and the netlist: net CHG_TSMR = U2 D1 + RT1 pin 1), and the firmware **enables TS** (IC_CTRL 0x97 with
  TS_EN, TS_CONTROL 0x90 = HOT 50 °C / COLD 3 °C; `CONFIG_CALIPER_CHG_TS_ENABLE` defaults to y). RT1 reads the
  board, not the cell itself: since 2026-11-09 (J2 on the bottom) it sits over the pocket's J2 bay and the cell's lead
  end, not over the cell (TVP: compare with a thermocouple on the pouch while charging; moving RT1 to x ≥ 28 would put
  it over the cell).
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
  SENSOR_ERR and falls back to the count alone for that reading if they disagree by more than **12 SSI LSB = 3
  edges**: the 2-edge hysteresis plus up to 1 edge of lock phase, `AS5311_FINE_TOL_LSB`, TVP; a literal 2-edge limit
  would flag correct readings at direction reversals. A slip is corrected only after the same correction on 3
  still frames in a row; the SSI is read on every 100 Hz sample). Internal resolution is therefore **0.488 µm** (488.28125 nm); the display shows 0.01 mm. The
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
  high while (n − step) mod 8 < 4) at **≈ 5 kHz rotation**: the S3 ADC samples at APB/32/integer, so 80 kS/s asked
  for is really 80 645 S/s; the firmware steps every 2 sample periods (24.8 µs, 5.04 kHz) at the rate it reads back.
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
| I2C (GPIO13 SDA / GPIO14 SCL, **2.2 k** to +3V3, 400 kHz; §12) | BQ25180 (0x6A), MAX17048 (0x36), LIS2DW12 (**0x19, SA0 high**) | SA0 has an internal pull-up that cannot be disconnected: a grounded SA0 (0x18) burns 60–170 µA |
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
- **Battery pocket (D4; slim housing 2026-11-09):** u 29.5…67.6 (board x 21.5…59.6), y 22.4…35.1, floor z −7.0 (a
  flat 1.6 mm door flush in the back face, two nylon M2 screws). The cell (≤ 5.4 × 12.5 × 31.5) lies at u 35.6…67.1,
  12 mm from the antenna, 1.0 mm under the button ledge. J2 (bottom side), its plug and the leads are in the J2 bay
  u 29.5…35.6, ≥ 6.3 mm from the antenna. Both Y-gib plungers (u 14, 24) and the lock (u 19) sit left of that span
  and push through Ø2 GFRP rods under the antenna. The plunger springs sit at the bottom of the bores (y 22.0…24.4,
  5.15 mm from the antenna); the set screws and the lock thumb screw are nylon M3 in threads tapped in the print (the
  top face is 2.4 mm above the antenna area, so no metal there). A battery door replaces the back cover (§11). Was
  u 29.5…65.5, y 22.4…48, with the plunger metal at y ≥ 41.
- **RF (D4):** within 5 mm of the antenna area (board x 0.15…15.55, y 29.5…34 with the module as placed; slider u 8.15…23.55) nothing metal and
  nothing carbon-filled. The fasteners there are non-metal: the H1 screw (nylon; since 2026-11-09 it also holds the lid)
  and the nylon Y-plunger, lock and battery-door screws (the Y springs sit at the bottom of their bores, 5.15 mm away).
  In rev A that means the PA-CF body is opened under and beside the antenna (or the body
  is printed in unfilled PA/PETG), and the PA-CF moving inside jaw keeps 5.15 mm in plan from the antenna area: since its stiffening (below)
  its root runs under the antenna corner, and the part of it within 5.15 mm prints in unfilled PA through the same modifier (it was first an
  R 5.15 relief arc on the old 2.4 mm plate's flank, after a 4.70 mm clash check RISK; docs/mechanical.md §12). In rev B the 6061 body needs a
  non-metal window there and the front shell must be printed.
- **Moving inside jaw (2026-11-08):** stiffened from a 2.4 mm plate (≈ 9.5 µm/N on PA-CF at the measuring face) to **≈ 2.0 µm/N** (FEA with
  the local body, datasheet E; 2.3 with the 0.85 FDM knock-down, so at the 2 µm/N target, not under it; PETG 4.1): the measuring face (u 0, y 31…37), the tip's z (−8.6…−6.2) and its 3.0 mm end width are unchanged; the tip
  tapers to 4.0 mm at its base, a shoulder block fills u −4…6.4 under it up to y 31, and a full-height gusset (z −8.6…+2.4) fills the part
  the fixed inside jaw never reaches (0.4 mm clear). With the fixed inside jaw stiffened too (below), an inside reading over a 2–8 N touch
  moves ≈ 19 µm with both PA-CF inside jaws (22 µm with the 0.85 FDM knock-down; both jaws with their local bodies). Designed, not built or
  measured; detail in docs/mechanical.md §9.
- **Fixed inside jaw (2026-11-09):** stiffened from ≈ 2.2 µm/N on PA-CF at the measuring face (FEA with the fixed block's top part; 1.7
  with a rigid root) to **≈ 1.1 µm/N** (0.94 with a rigid root; 1.3 with the 0.85 FDM knock-down; PETG 2.8). The measuring face (x 0,
  y 31…37), the tip's 3.0 mm width over its whole 6 mm, its z (−6.0…+2.5, 0.2 mm over the moving tip) and its right flank are unchanged.
  A shoulder block fills x −18…0 under the face up to y 31, and a full-depth gusset (z −8.6…+2.5) fills it left of x −4.4, where the
  moving inside jaw never reaches (0.4 mm clear). No tip taper: the tip's right edge is 5.15 mm from the antenna area at R = 0, so the
  minimum gap is unchanged. It misses the ≤ 1.0 µm/N goal by 0.13 once the block's give is counted. Designed, not built or measured;
  detail in docs/mechanical.md §9.
- The slider housing straddles the beam: printed PETG/PA-CF in rev A, CNC 6061 in rev B. Brass gibs with
  M2 set screws + springs set the 0.3 mm (magnetic) and 0.15 mm (capacitive) gaps. The fixed jaw is
  bolted and dowelled to the beam end. The moving jaw is part of the slider housing.
- Housing outside: ≤ 78 × 39.5 × 16 mm, including the thumb wheel/roller (was ≤ 78 × 52 × 16 until the 2026-11-09
  slim housing; as modelled 76.9 × 39.2 × 16.0 plus the roller rim to u 78.0). The inside-jaw tips reach 0.6 mm above
  the top face and the lock knob 4 mm, as appendages. Outside shape: R 3.4 / R 3.0 plan radii at the top corners, a
  1.2 × 45° bevel round the body's back face (sharp at the jaw roots and the step), a 0.8 × 45° bevel round the lid's
  top edge; no taper (docs/mechanical.md §3).

## 8. Firmware contract (detail in `docs/firmware.md`)
- The BLE GATT service UUIDs and the characteristic layout are defined once in
  `caliper/firmware/main/proto/caliper_gatt.h` and mirrored in **`public/caliper/app/protocol.js`** (the web app
  lives in `public/caliper/app/`, published with the docs site; the empty `caliper/app/` was removed) (D7).
- **Advertising:** the advertisement or the scan response carries the complete **128-bit service UUID**
  (`7c0a0001-5e1f-4b8a-9c3d-2f6a1e0c7b11`); the app's chooser filters on it. Rev A puts it in the scan response.
- **LIVE (D6, extended to v3 2026-11-07 for the capture modes):** **20 bytes**
  `{i32 value_nm, i32 cap_nm, u8 unit, u8 flags, u16 active_profile_id, u8 capture, u8 capture_state,
  u16 capture_n, i32 capture_aux_nm}`, one notification at the default ATT_MTU of 23. `active_profile_id` 0 = none.
  `value_nm` is always the **shown** value: the capture result when frozen, the running extreme while a SWEEP is
  in contact, else the live (or held) value, so an old reader shows the right number; a frozen capture also sets
  HOLD. `capture`: bits 0..3 mode (0 LIVE, 1 SETTLE, 2 SWEEP, **3 SET reserved**), bits 4..5 sweep selection
  (0 auto, 1 min, 2 max). `capture_state`: bits 0..2 state (0 idle, 1 armed, 2 in contact / settling, 3 frozen,
  4 aborted by a sensor error), bits 4..5 which extreme `value_nm` is (0 n/a, 1 MIN, 2 MAX). `capture_n`: samples
  in the capture (saturating 65535). `capture_aux_nm`: SWEEP the other extreme (R = |value − aux|), SETTLE the
  window's standard deviation, `INT32_MIN` = n/a. Readers accept **10, 12 or 20 bytes** (10 = before the profile
  id; 12 = before the capture modes: no capture UI) and ignore anything past 20. Reasons: the profile id, because a
  profile chosen on the caliper was invisible to the app; the capture block, so a client can show and set the
  capture without old clients seeing anything but the right value.
- **Flags** (LIVE and the log record use the same bit meanings): bit 0 HOLD, 1 TOL_PASS, 2 TOL_FAIL, 3 SENSOR_ERR,
  4 CAP_VALID, 5 CHARGING, 6 REZERO (the zero could not be carried across a sleep/reset; cleared by ZERO); bit 7 free.
- **Log record:** `{u32 seq, u32 unix_s, i32 value_nm, u8 unit_kind, u8 flags, u16 profile_id}` = 16 bytes. Byte 12
  as stored: **bit 0 unit**, bits 1..3 **kind** (0 plain/live/hand hold, 1 SETTLE median, 2 SWEEP min, 3 SWEEP max),
  bit 4 SET member and bit 5 first of a set (**reserved**, never set yet), bits 6..7 0. Records stored before the
  kind existed have bits 1..7 = 0. **A plain LOG_READ (len 5) sends bit 0 only**, because existing readers
  compare byte 12 with the inch value and would read an extended byte as mm; the **6-byte LOG_READ** with opts
  bit 0 sends the whole byte. After LOG_READ the records come packed in notifications; the **end marker**
  (seq = 0xFFFFFFFF, 12 zero bytes) is sent **in a notification of its own**, so a reader never has to split a
  packet at the marker.
- **COMMAND opcodes** (length includes the opcode): 0x01 ZERO (1; also clears and re-arms the capture), 0x02
  HOLD_TOGGLE (1; in a capture mode it freezes a running capture, clears and re-arms a frozen one, else holds the
  live value by hand), 0x03 RECORD_NOW (1), 0x04 SET_UNIT (2), **0x05 SET_CAPTURE (3: u8 mode 0..2, u8 sweep
  selection 0..2; persisted; mode 3 SET or a value out of range → 0x80)**, **0x06 CAPTURE_RESET (1)**, 0x10
  LOG_READ (5: u32 from_seq; **or 6: u32 from_seq, u8 opts**, opts bit 0 = the whole unit_kind byte, other bits 0
  or 0x80), 0x11 LOG_CLEAR (1), 0x20 SELECT_PROFILE (3), 0x30 SET_TIME (5). Feature detection: firmware without the
  capture modes sends a 12-byte LIVE, answers 0x05/0x06 with 0x06 and a 6-byte LOG_READ with 0x0D; a client sends
  the new forms only to a caliper whose LIVE is 20 bytes.
- **Capture semantics** (designed, not bench-tested; parameters and the reasoning in `docs/firmware.md`
  "Capture modes"): **SETTLE** freezes the median of the last 32 samples (320 ms at 100 Hz) once the reading has
  stayed within a 10 µm span for 0.8 s after a move of more than 0.5 mm, and releases when the jaws move 0.5 mm
  away. **SWEEP** starts when the jaws stop (≤ 20 µm span over 100 ms after a 0.5 mm move), keeps the persisted
  MIN and MAX (a value must hold for 2 samples) of the samples within ±1 mm of the contact reference, and freezes
  50 ms after the reading leaves that gate (lift-off), with the departure taken back out. An exit on the side a
  rock or a bore sweep goes, within 2 mm, must also stay out for 1 s, because a wide sweep of a small bore leaves
  the gate and comes back. A sensor error or a confirmed count-slip correction aborts it. AUTO shows MIN when the
  jaws closed onto the part and MAX when they opened. It suits ODs and single bores; bores in a row need MAX, and
  depth and steps need MIN. **Tolerance** is judged on the shown value rounded to the
  display step: the median for SETTLE, the selected extreme for SWEEP (live while in contact, final when frozen),
  never the other extreme.

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
  unpaired write is refused by the stack (ESP-IDF v5.4.2 NimBLE source: 0x05 Insufficient Authentication with no
  bond, 0x0F Insufficient Encryption when bonded but not yet re-encrypted; not yet seen on air) and the
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
| D6 | GATT clarifications (magnitudes, upsert, delete, 16 max, id 0, end marker alone, error codes, encrypted SETTINGS write, partial update, field limits, decimals, LOG flags, UUID in the scan response) and **LIVE = 12 bytes** with `u16 active_profile_id` (readers accept 10 or 12); extended to **20 bytes (v3)** for the capture modes on 2026-11-07 (§8) | These were implemented one way in the firmware and guessed in the app; the app could not see a profile chosen on the caliper | §8, caliper_gatt.h, protocol.js |
| D7 | The app lives in `public/caliper/app/` | the empty `caliper/app/` was removed | §8 |
| D8 | RT1 (10 k NTC on TS) **populated**, firmware **TS enabled**; IMU_INT1 is push-pull, active-low, latched with **no pull** on the net | Checked in the netlist and the firmware defaults; a pull on a push-pull line would only waste current, and ext1 ANY_LOW needs every wake line active low | §3, §5 |
| D9 | Sleep target **≤ 35 µA** everywhere | the buck-boost's Iq and divider alone exceed the first-draft figure | §3, docs |

## 11. As-built reconciliation (2026-11-08, after layout, mechanics and firmware phase 3)
Designed, not built: nothing below has been fabricated or measured. This records what the routed boards, the
mechanics and the firmware now do where they differ from the first-draft sections above (which are updated in place).

* **Placement (§2.1).** The table now gives the routed positions. Moves over 1 mm: U1/D1 (USB pair re-route), U4 + C7
  beside J2, R6–R9 below the module, the TX ladder R60–R77 to x 1.8…10.2, C30 next to the AS5311's VDD pins (still in
  the D2 window), C8/C10 held ≤ 2 mm from U5, R50/Q50/R51, Q51/R56/R57, FID3 out of J1's courtyard, TP22/TP23 to the
  y 22.6 row. Moves ≤ 1 mm: U10 origin x 7.85, J50 y 7.5, J2 y 30.6, SW20 rotated 90 at y 15.7.
* **Antenna.** With U10 at x 7.85 the antenna area is x 0.15…15.55; the mechanics' `params.ANTENNA` follows it. The
  PA-CF moving inside jaw was then 4.70 mm in plan from it (clash check RISK; 5.02 against the draft position); since
  2026-11-08 its root flank is relieved round the antenna corner and it is 5.15 mm away (docs/mechanical.md §12).
  The keep-out rule area on the board starts at y 29.2, not 29.0.
* **Open layout items:** USB D+/D- are a B.Cu pair with part of their length not directly over a plane (full-speed
  only). The module decoupling, H5, the SMT standoff part and the J50 land were closed on 2026-11-08 (§12). From
  the hwtools run on the re-routed board (2026-11-08), fixed the same day (§13): the long, thin VBAT run, U6's missing
  input capacitor, the VBUS feed that skipped D1, CAP_RX's long run with its filter at the far end, the missing
  stack-up, the bypass around U1 on each USB line. Still open: backlight up to ≈ 31 mA through R50 15 Ω at the
  VF-min / +3V3-max corner against a 20 mA typical rating (R50 18–22 Ω or a firmware duty cap; owner decision).
* **Owner decision (2026-11-09): ACCEPTED** the extended under-module bottom-side exception (§2.1): R85 / C44 (CAP_RX
  anti-alias RC, 0402, 0.5 mm tall) on the bottom under the module, which takes the exception's lower edge from
  y 24.8 (C21 / C23 only, §12 H4) to **y 22.7** (x 1.8…4.4 unchanged). The mechanics clear it (0.5 mm in the 0.75 mm
  housing-floor gap; clash check 0 not clear, §13 gates).
* **Mechanics (§7):** closed back web over the beam with the back plungers (u 14 and 64, y 5, 2.5 N each); Y plungers
  u 14 / 24 (4 N each) and the lock u 19 left of the battery pocket; housing end face u 77.4, roller rim u 78.0; the
  end stop is an M2×6 socket screw in a tapped hole; tab clamps use 0.3 mm shim washers bedded in epoxy on 0.150 mm
  foil; a shimmed ledge under the board's top edge at board x 29…57.5, y 32.6…34 (keep it free of bottom parts, test
  pads and exposed copper; the VBAT band runs under it, under mask with tented vias, so the shim keeps at least one Kapton layer); inside jaws in z: moving −8.6…−6.2, fixed −6.0…+2.5 (the fixed jaw's shoulder gusset left of x −4.4 runs full depth, −8.6…+2.5). Detail in docs/mechanical.md.
* **Firmware (§4, §8):** D1 tolerance 12 LSB / 3 edges (§4.1); cap drive 5.04 kHz at 80 645 S/s (§4.2); the cap
  reading is aligned to the magnetic reading at its first valid burst after boot and whole 2.54 mm slips are
  corrected against it (no cap zero is kept across sleep); LIVE flag bit 6 REZERO; CSV flags `H P F E Z`; on-flash
  log layout v2 (`log.hdr` + 4 KB `logNNN.bin` segments, docs/firmware.md). These are design choices the owner may
  revisit after bring-up.

## 12. Hardware changes after phase 3 (2026-11-08)
Designed, not built. Each item is in the schematics (`sheets/*.py`), the routed board and the docs.

| # | Change | Why / numbers |
|---|---|---|
| H1 | **Battery reverse-polarity P-FET Q1** (AO3401A, C15127, JLC Basic) between J2 pin 1 (VBAT_RAW) and VBAT, gate to GND through R10 10 k, no zener | User decision. §3: ≤ 43 mV / ≤ 21 mW at 0.5 A (VGS −3.0 V, 85 mΩ max bound); conducts both ways for charging; the charger BAT pin and the MAX17048 stay on VBAT. Q1 at (25.1, 25.1) under J2 pin 1; RT1 moved to (22.3, 26.75), C7 to (27.37, 26.3) |
| H2 | **I2C pull-ups R6/R7 4.7 k → 2.2 k** (C25879, Basic) | 400 kHz with ≈ 110 pF: rise (30→70 %) 0.847 RC = 205 ns (4.7 k: 438 ns > 300 ns). Sink at VOL 0.4 V ≤ 1.4 mA, inside fast mode's 3 mA and the devices' VOL ratings (ESP32-S3 0.1 VDD at 28 mA; BQ25180 0.4 V at 5 mA; MAX17048 0.4 V at 4 mA; LIS2DW12 per I2C fast mode) |
| H3 | **J50 land = the C2911931 vendor drawing** (own footprint `caliper:HDGC_0.5K-AX-13PWB_1x13-1MP_P0.50mm_Horizontal`): contacts 0.30 × 1.25 at 0.5 mm, nails 2.00 × 3.00 at x ±4.54, 2.325 behind the contact row | The KiCad FH12 land put the part's nails 1.3 mm off copper. No genuine FH12-13S (C5700671) or Amphenol F32R 13-pin is stocked at LCSC/JLC. EasyEDA's land agrees on the contacts and nail x; its nails sit 0.37 mm nearer the row and still land on this land. Same origin/orientation as the FH12 footprint (contact row at x 23.35 on the board). Pin 1 at y 10.5; the panel tail must have its contacts on the viewer side and pin 1 on +y before the fold (§2.1) |
| H4 | **Module decoupling under pad 3 on the bottom:** C21 100 nF moved there, C23 10 µF 0402 (C15525, 0.5 mm) added; C20 22 µF stays on top below the module as bulk | C21/C23 +3V3 pads 1.9 mm from pad 3 (C21 was 22.4 mm away on top; C20 stays 20.5 mm). Bottom-side exception in §2.1: x 1.8…4.4, y 24.8…27.0, outside the beam band (y 0…20), the antenna rule area (y ≥ 29.2) and the battery pocket (x ≥ 21.5); 0.55 mm max against the 0.75 mm housing-floor gap. The module has no bottom-side keep-out other than its antenna |
| H5 | **E40 pins renamed** TX0…TX7 / RX → PHASE0…PHASE7 / RCV (they were already passive) | hwtools boardcheck reads a pin named TXn as a UART transmitter: it flagged E40.TX6 against U10 TXD0 (GPIO43) through R66/R76 as output-to-output (SERIAL_DIRECTION_WIRING). Gone after the rename. E40 stays excluded from the BOM and the position files (symbol `in_bom no`, footprint attributes exclude-from-BOM + exclude-from-pos) |
| H6 | **H5 in the schematic** (power sheet, `MountingHole_2.2mm_M2_Pad_Via` on GND, linked to the board footprint) | parity: the board no longer carries a board-only part. **SMT M2 standoffs: fitted by hand.** The only LCSC M2 SMT nuts (SMTSO20x0CTJ, e.g. C2915626 M2 × 2, 34 k in stock) have a Ø5.6 base and land: on the 6 mm tab with the hole 2.5 mm from its outer edge they would overhang it, and they exceed the OD ≤ 4.0 the clamp faces assume |
| H7 | **Silk at the edge:** J1's shell outline (the receptacle overhangs the right edge by 1 mm) and the module outline at the left/top edge are clipped on the instances (`silk.clip_silk_at_edge`) | the four `silk_edge_clearance` warnings are gone; J1 now reports a `lib_footprint_mismatch` (local override) like U10 |

**Gates after these changes (2026-11-08):** `build.py` ERC clean apart from the two listed TPS22917 waivers, wiring
check passing; `check_contract.py` OK (`nets.MCU_PINS` unchanged), firmware `gen_pins.py --check` up to date. The
slider was re-placed and re-routed from scratch (`layout.py --route --minutes 8 --attempts 1`: Freerouting left 87
open, the grid router closed them, then `--finish`). KiCad 9.0.9 DRC + schematic parity: **0 errors, 0 unconnected,
0 parity**; warnings are 7 `lib_footprint_mismatch` (intended local overrides: E40, U10, J1, H2–H5); KiCad 10.0.8
agrees (0 errors; 10 warnings, the same plus its own FID1–3 library versions). `release.py` passes for both boards
and the slider package is **no longer review-only**: every CPL row, J50 included, lands on copper in the JLC
placement simulation. Mechanics re-extracted (101 part envelopes plus the 4 standoffs, the H1 screw and the JST plug: 107) and `clash_check.py`: 0 clashes. Release gate
added the same day: `release.py` now writes the CPL with jlcplace (`jlcplace cpl`, corrections in
`design/jlcplace-db/`) and refuses on any red row of `jlcplace check` (docs: assembly §6). jlcplace 0.2.1: slider
101 rows, 0 red, 1 yellow (BZ50 polarity: a preview item), 100 green; scale 0 rows, 0 red.

**KiCad 10.0.8 (2026-11-08, same day):** the toolchain and both boards moved from KiCad 9.0.9 to 10.0.8 with no
design change: the netlists are identical (the library renamed J1's shield pin S1 → SH), the committed routed
boards were only re-saved (copper, pads and nets identical, J1's four shield pads renumbered to SH), the Gerbers are
geometrically identical and the jlcplace result is unchanged. Evidence: docs/electronics.md §7.12.

## 13. Phase-4 review fixes (2026-11-08)
Designed, not built. Found by the hwtools run on the routed board and the phase-4 review (§11); each fix is in the
generators (`sheets/*.py`, `layout.py`, `tools/`) and on the reworked board (`layout.py --rework`: the routing of
every unchanged net kept). Numbers are calculations on the board files (docs/electronics.md §7.13), not measurements.

| # | Change | Before → after |
|---|---|---|
| R1 | **VBAT trunk** Q1 → U2 BAT / C3 pre-routed (§3): 2.0 / 2.1 / 1.9 mm B.Cu along the top edge and down between J1's shell tabs, In2 and F.Cu copper in parallel where nothing has to cross, 3–4 vias per layer change; J2 → Q1 0.60 mm | Q1 → BAT ≈ 95 → ≈ 12 mΩ (≈ 48 → 6 mV at 0.5 A); J2 → Q1 4 → 2 mΩ |
| R2 | **VSYS** U2 SYS → C2 → C4 → TPS63802 VIN pre-routed (0.80 mm trunk) | ≈ 21 → ≈ 12 mΩ |
| R3 | **C13** 1 µF 0402 at U6 VIN (C52923, Basic), placed under its VIN / GND pins | U6 had no input cap of its own (C5 12.5 mm away) |
| R4 | **D1 on the VBUS trunk**: D1 (52.7, 19.95) 180°, both J1 VBUS pad pairs land on its pad, the run to C1 / U2 IN leaves from it | J1's A9/B4 no longer reaches U2 without passing the TVS |
| R5 | **CAP_RX filter at the ADC**: R85 / C44 on the bottom under the module beside GPIO1 (§2.1 bottom exception now y 22.7…27.0); the long run is CAP_LP1 (pre-routed, Analog net class 0.2 mm); TP42 on CAP_LP1 | CAP_RX copper 60 → 2.9 mm; sicalc crosstalk into CAP_RX worst 11 → 0.14 mV (1 mV budget) |
| R6 | **Stack-up JLC04101H-3313** written into the board (3313 prepreg 0.0994 mm, εr 4.1) and named in ORDER-NOTES; USB pair 0.16 / 0.16 mm gap | USB Zdiff ≈ 97 → ≈ 89 Ω (90 Ω target) |
| R7 | **USB through U1**: J1 → U1 pre-routed straight; U1's I/O pins as jumper pad groups (1/6, 3/4) so no router adds a bypass | the loop round U1 on each line is gone |
| R8 | Schematic packing: the power sheet fits A3 (was a half-empty A2) | |

Open: R50 is drawn ≈ 45 mm of wire from J50 on the UI sheet. (CAP_LP1 itself ran broadside to BTN_MODE_N for
5.7 mm, sicalc upper bound 20 mV: closed on 2026-11-09, §14.)

**Gates after these changes (2026-11-08):** wiring check and ERC as before; DRC + schematic parity 0 / 0 / 0 (7
`lib_footprint_mismatch`, 2 `track_dangling` warnings); `release.py` passes for both boards; jlcplace slider 102 rows,
0 red, 0 yellow, 102 green; `check_contract.py` OK; firmware pin tables up to date; mechanics extract + clash check
0 clashes. Evidence: docs/electronics.md §7.13.

## 14. CAP_LP1 crosstalk shield (2026-11-09)
Designed, not built. Numbers are hwtools `sicalc xtalk` calculations on the board file (config
`design/xtalk-cap.yaml`), not measurements; detail and evidence in docs/electronics.md §7.14.

| # | Change | Before → after |
|---|---|---|
| S1 | **Shielded corridor for CAP_LP1's B.Cu and In2 stretches** (`layout.py` `CAP_LP1_SHIELD`; the pre-route `CAP_LP1_PATH` unchanged): no other track within 1.0 mm of the centre line on the stretch's own layer, none along it on the neighbouring layer (0.8 mm crossing windows every 1.6 mm), an In2 GND zone over both stretches plus the B.Cu GND pour over the In2 one, GND vias along both edges | CAP_LP1 worst aggressor **BTN_MODE_N 20.4 → 0.88 mV** (1 mV budget); BOOT_N 4.4 → 0.03, RGB_DIN 3.7 → not coupled, IMU_INT2 3.2 → 0.64, I2C_SDA 3.0 → 0.14, BUZZ_D 1.8 → not coupled. CAP_AMP_OUT 0.65 → 0.15, CAP_RX 0.14 (unchanged). Over-budget pairs on the board 10 → 3 |
| S2 | Re-routed round the corridors with `layout.py --rework` (no part moved): the button, I2C, IMU, LCD_BL, RGB_DIN, BOOT_N, CAP_TX and CAP_AMP_OUT lines that ran in them; USB, VBUS, VBAT, VSYS and CAP_RX copper as before, every pre-route locked | BTN_MODE_N 77 → 111 mm, I2C_SCL 107 → 74 mm, LCD_BL 55 → 39 mm, the others within ±12 mm. Still over sicalc's 10 mV USB budget: MAG_A → D+ 25.5 mV in the slot where I2C_SCL was (22.4 mV) |

The §2.1 under-module bottom-side exception for R85 / C44 (y 22.7) was accepted by the owner the same day (§11).

**Gates (2026-11-09):** DRC + schematic parity 0 / 0 / 0 (7 `lib_footprint_mismatch` warnings); `release.py` PASS,
jlcplace slider 102 rows, 0 red, 0 yellow, 102 green; `check_contract.py` OK; `tools/tests` 19 passed; mechanics
extract + clash check 0 not clear (part envelopes identical to the committed extract).

## 15. Slim-housing board changes (2026-11-09)
Designed, not built. The owner chose the slimmest housing (77 × 52 × 16 mm → about 38 mm tall): a ≈ 12.5 mm-wide
1S cell (501230 class, ≈ 135 mAh) behind the board's upper band, the housing ending just above the board. The board
changes it needs (`layout.py`; the schematic only had its notes updated, the netlist is identical):

| # | Change | Why / numbers |
|---|---|---|
| L1 | **J2 to the bottom side**, footprint origin (24.1, 24.9), mating face +y, pad row y 22.9 (pin 1 VBAT_RAW x 23.6, pin 2 GND x 24.6), nails x 22.3 / 25.9 (§2.1 bottom-side exception) | the receptacle, the plug and the cell leads stay in the battery pocket's J2 bay (x 21.5…27.6) instead of passing the top edge, which the shorter housing has no room for. Mechanics: 6.86 mm (J2) / 6.35 mm (plug) in plan from the antenna area, inside the pocket by 0.3 mm |
| L2 | **VBAT_RAW** J2 pin 1 → Q1 drain re-drawn: B.Cu down to a via at (23.6, 21.6), F.Cu up between Q1's gate and source pads, 0.60 mm, locked | ≈ 2 → ≈ 6 mΩ (estimate). The B.Cu stub leaves the pad away from CAP_LP1's In2 stretch (its centre line passes 1.1 mm from the pad centre, 0.3 mm from its corner, on the next layer; the pad is DC battery copper) |
| L3 | **VBAT riser** 2.0 → 1.6 mm, x 26.75…28.35 (right edge unchanged) | 0.25 mm from J2's +x nail; ≈ +0.4 mΩ on the ≈ 12 mΩ trunk |
| L4 | **TP20 / TP21 / TP30 / TP31** to a third row, y 30.22, x 32.66 / 35.2 / 37.74 / 40.28 (same 2.54 grid) | their old spots (x 22.5 / 25.04, y 22.6 / 25.14) are under J2 |
| L5 | **H1 top-side Ø4.6 circle** kept free of parts, checked by `layout.py` (`check_h1_tube`: nearest courtyard 0.60 mm outside) | the lid's Ø4.4 tube ends 0.1 mm above the board there, in place of the old Ø3.8 screw head. No part moved |
| L6 | `layout.py --rework`: an old via that a moved part's SMD pad now covers is removed with its track and its pad fanned out again (`drop_vias_in_new_pads`) | R10's and C7's GND fan-out vias sat inside J2's nails; an open via in a pad wicks the solder |

Re-routed with `layout.py --rework --rip VBAT,VBAT_RAW --no-freerouting` (grid router; only J2 and the four test
pads moved): MCU_EN, BOOT_N, MAG_A, MAG_B, VBAT and VBAT_RAW re-done; the grid router also re-did short pieces of
BUZZ, BTN_ZERO_N, BTN_HOLD_N, BTN_MODE_N, I2C_SDA, IMU_INT1, IMU_INT2 and +3V3 that the new copper displaced. hwtools
`sicalc xtalk` (`design/xtalk-cap.yaml`): the analog victims stay under their 1 mV budget (worst CAP_LP1 ← BTN_MODE_N
0.88 mV, unchanged); over-budget pairs 3 → 3: the USB pair itself and, in the slot where MAG_A was (25.5 mV),
IMU_INT2 → D+ 26.9 mV against sicalc's 10 mV USB budget (full-speed USB, already open in §14).

**Gates (2026-11-09):** `build.py` wiring check + ERC as before (2 waived TPS22917 pin_to_pin), netlist IDENTICAL to
the previous one; DRC + schematic parity 0 / 0 / 0 (7 `lib_footprint_mismatch` warnings); `release.py` PASS for both
boards, jlcplace slider 102 rows, 0 red, 0 yellow, 102 green; `check_contract.py` OK; `tools/tests` 19 passed;
mechanics `run_all.sh`: extract from the routed board (J2 and its plug on the bottom, no pending substitution),
41 tests passed, clash check 0 not clear, 0 FAIL / 0 RISK, 0 BREAK / THIN.
