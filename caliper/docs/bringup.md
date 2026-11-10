# Bring-up

> **Status: written, not run.** No board has been built, so every step below is a plan and every expected value
> comes from [SPEC](../hardware/design/SPEC.md), the schematics ([Schematics & boards](electronics.md)), the
> datasheets or the [architecture power budget](architecture.md#_5-power-budget-and-battery-life), not from a
> measurement. The `bu` commands it uses are in the firmware ([Firmware §10.1](firmware.md#_10-1-bring-up-commands-bu)),
> which builds and passes its host tests but has never run on a chip either.

This page takes a slider board from bare PCBA to a board that can go into the housing. The steps are numbered
**B-x** so [Assembly §4](assembly.md#_4-assembly-order) can gate on them: do them in order, each one assumes the
previous ones passed. Record every number in a per-unit log; B-17 is the summary checklist.

* **[TVP]** = *to verify on prototype*: the limit comes from a datasheet typical, an estimate or a model. Tighten it
  after the first good unit.
* "Meter" means a DMM on the named test pad, black lead on **TP7 (GND)**.
* Every firmware check prints its numbers and ends with one line `PASS <name>: ...` or `FAIL <name>: ...`. The
  interactive ones (display, piezo, LED, rails off/on) ask for a `y`/`n` typed on the console.

## Test pads

All 19 pads are Ø1.0 mm on the **bottom**, in three rows on a 2.54 mm grid (SPEC §2.1; x is board x, as seen from
the top: from below the rows read right to left). Since 2026-11-09 J2 (the battery connector) sits on the bottom at
x 22.1…26.1, so TP20, TP21, TP30 and TP31 moved from x 22.50 / 25.04 to the y 30.22 row.

| x (mm) | 27.58 | 30.12 | 32.66 | 35.20 | 37.74 | 40.28 | 42.82 | 45.36 | 47.90 |
|---|---|---|---|---|---|---|---|---|---|
| **y 30.22** | – | – | TP20 MCU_EN | TP21 BOOT_N | TP30 MAG_A | TP31 MAG_B | – | – | – |
| **y 25.14** | – | – | TP50 LCD_BL | TP51 BUZZ | TP7 GND | TP4 +3V3 | TP2 VBAT | TP3 VSYS | TP1 VBUS |
| **y 22.60** | TP32 MAG_IDX | TP40 CAP_AMP_OUT | TP41 CAP_VREF | TP42 CAP_LP1 | TP5 +3V3_SNS | TP6 +3V3_UI | TP22 USB_D+ | – | TP23 USB_D− |

There is no pad on the I2C lines, SNS_PWR_EN, the LCD lines or the AS5311 SSI lines: the firmware checks cover
them (B-7, B-11, B-12).

---

## B-0. Equipment

| Item | Use |
|---|---|
| DMM with a µA range and diode test | rails, resistances, sleep current (or the PPK2) |
| Bench supply 0–5 V, current limit settable to 10 mA | stands in for the cell on J2 (**it cannot sink current**, B-1) |
| 12 Ω / 2 W resistor (dummy load) and an 82 Ω one | across the bench supply's terminals whenever USB is in too (B-1 item 3) |
| µA meter with a bypass switch across it | sleep / ship current: closed while USB is in or the board boots |
| JST-SH 2-pin pigtail (SHR-02V-S + leads) | supply / meter into J2: pin 1 = BAT+ (VBAT_RAW), pin 2 = GND |
| Protected 1S LiPo: the caliper's own cell, Renata ICP501230PS-03 (135 mAh) or an equivalent ≤ 5.4 × 12.5 × 31.5 mm, with its SH plug crimped on; LiPo bag | charging (B-7.4) |
| USB-C cable to a PC, inline USB-C power meter | power, flashing, the console |
| Nordic PPK2 (optional) | sleep and ship currents in source mode (B-15, B-16) |
| Oscilloscope, 2 channels | MAG_A/B/IDX, CAP_LP1, LCD_BL, BUZZ |
| A 20–30 mm piece of the 2.0 mm-pole magnetic tape + 0.30 mm shim | AS5311 on the bench, before the beam (B-12) |
| The scale board, or the beam with the scale bonded | capacitive check (B-13) |
| Phone with nRF Connect; an **ESP32-S3-DevKitM-1** (same ESP32-S3-MINI-1 module, full antenna clearance) | RF reference (B-14) |

Terminal: any serial terminal on the console port (the TinyUSB CDC "Caliper console" once the firmware runs).
Type `bu help` for the command list.

## B-1. Ground rules

1. **Supplies per step:**

   | Step | Supply → where | Setting | Limit | Expected draw |
   |---|---|---|---|---|
   | B-4 first power, no firmware | bench → J2 pigtail | 3.70 V | 100 mA | 20–50 mA [TVP] |
   | B-5 USB, no firmware | PC USB (via the power meter) + bench on J2 | 5 V; 3.70 V | –; 100 mA | see B-5 |
   | B-6 on, firmware running | bench → J2 | 3.70 V | 150 mA | ≈ 56 mA idle awake (architecture §5) [TVP] |
   | B-7 with USB | real cell on J2, or bench + 12 Ω dummy load | 3.70 V | 600 mA | ≈ 70 mA into the cell / the load |
   | B-14 Wi-Fi scan | bench → J2 | 3.70 V (Wi-Fi refuses below 3.50 V without USB) | 600 mA | Wi-Fi peaks ≈ 0.2–0.3 A from the cell with the 10 dBm TX cap (SPEC §3) [TVP] |
   | B-15, B-16 sleep / ship | real cell, or bench + 12 Ω load → µA meter (bypass closed until asleep) → J2 | 3.70 V | 600 mA | ≤ 40 µA / ≤ 3 µA |

2. **Cold start on a bench "battery":** the BQ25180 only powers SYS from BAT alone above VBATPOR = 3.08 / 3.21 /
   3.46 V (min / typ / max, SLUSE99C). Always power up at **3.70 V**, then lower the voltage while it runs; once
   running, SYS stays up down to BUVLO (3.0 V).
3. **Bench supply on J2 together with USB:** the charger charges whatever is on BAT, and most bench supplies
   cannot sink: their voltage is pushed up. Before the firmware runs the charge current is the BQ25180 power-on
   default (small: an 82 Ω load across the supply, 45 mA, covers it [TVP]); once the firmware runs it is **70 mA**
   (≤ 77 mA with the ±10 % tolerance): use a real cell, or the **12 Ω / 2 W** load across the supply's terminals
   (308 mA at 3.7 V, so the supply always sources; the 82 Ω one also covers 70 mA, by a smaller margin). Never leave a µA meter in that path with USB in: the charge current flows back through it.
4. **Polarity:** check every pack: pin 1 = BAT+. Q1 blocks a reversed cell (SPEC §3, B-4.4), but don't rely on it.
5. **Display FPC:** fit or remove the panel only with the board unpowered. Lay the panel flat, glass up, with the
   tail toward −x (SPEC §2.1 J50 note: tail contacts facing up when the panel lies face up, pin 1 on +y).
6. Keep magnets and steel tools away from the AS5311 (bottom, x 20–41) except the tape coupon of B-12.

## B-2. Visual inspection

Under 10–20× magnification; ask JLC for X-ray images of the BQ25180 (8-ball WCSP) and the TPS63802 (DLA, 10 pins
plus the GND pad).

| Part | Check |
|---|---|
| U2 BQ25180 (WCSP) | X-ray: 8 balls, no bridges, no opens |
| U3 TPS63802, L1 | X-ray / side view: pads wetted, no bridge between the 0.25 mm-wide pads |
| U10 ESP32-S3-MINI-1 | castellations wetted; nothing under or within 5 mm of the antenna (top-left corner, x 0…21, y 29…34, both sides) |
| U30 AS5311 (bottom) | pin 1, TSSOP leads; C30 / C31 beside it; nothing else on the bottom over y 0…20 except the electrodes |
| D1 SMF5.0A, U1 USBLC6 | D1 cathode band to VBUS; U1 pin-1 mark matches the silk (turned 180° it clamps VBUS to GND) |
| Q1 AO3401A, R10 | Q1 drain pad under J2 pin 1 (SPEC §2.1: Q1 at 90°) |
| U4 MAX17048, U60 LSM6DSO, U40 TLV9062 | pin-1 marks; U4 exposed pad. U60 is an LGA: its 14 pads are underneath, so the firmware checks (B-7.1, B-10) are what proves the joints |
| D50 WS2812B-2020, BZ50, Q50, Q51 | orientation per silk |
| J50 FPC | bottom-contact part, latch present, no solder wicking into the contacts |
| J1 USB-C | shell tabs soldered; no bridge on the 0.5 mm signal row |
| C21, C23, R85, C44 (bottom, under the module) | present, ≤ 0.55 mm tall (SPEC §2.1) |
| Flux and solder balls | especially around U40 / C40 (10 pF ‖ 10 MΩ feedback: leakage shifts CAP_AMP_OUT) |

## B-3. Unpowered resistance checks

DMM ohms, red on the pad, black on TP7. Wait for the reading to settle (capacitors charge). A reading below the
"fail" column is a short or a reversed part: stop. Record the first good board's values; later boards within
±20 % [TVP].

| Pad | Expected | Fail if | What hangs there |
|---|---|---|---|
| TP1 VBUS | > 100 kΩ | < 1 kΩ | D1, U1, C1, U2 IN |
| TP2 VBAT | > 100 kΩ (record) | < 1 kΩ | U2 BAT, C3, U4 (VDD/CELL), Q1 source |
| TP3 VSYS | > 10 kΩ (record) | < 1 kΩ | U2 SYS, C4, U3 VIN/EN |
| TP4 +3V3 | > 1 kΩ, climbing (record) | < 100 Ω | U3 out + 511 k/91 k divider, module, IMU, gauge pull-ups, U5/U6 VIN, backlight |
| TP5 +3V3_SNS | > 1 kΩ (record) | < 100 Ω | AS5311, TLV9062, the CAP_VDIV divider (R82 + R83, 2 × 100 k) |
| TP6 +3V3_UI | > 1 kΩ (record) | < 100 Ω | ST7789 VDD (panel fitted), D50 |
| TP4 ↔ TP5, TP4 ↔ TP6 | > 1 kΩ | < 100 Ω | U5 / U6 off (ON pulled low by R5): a short = damaged switch |
| TP20 MCU_EN → TP4 | ≈ 10 kΩ | open / ≪ 10 k | R20 |
| TP21 BOOT_N → TP4 | ≈ 10 kΩ | open | R21 |
| TP50 LCD_BL | ≈ 100 kΩ | < 50 k / open | R51 gate pull-down |
| TP51 BUZZ | ≈ 100 kΩ | < 50 k / open | R56 gate pull-down (GPIO45 strap must read low at reset) |
| TP41 CAP_VREF | > 10 kΩ (record) | < 1 kΩ | U40B's output and U40A IN+ only: the R82 / R83 divider and C41 are on CAP_VDIV, behind U40B's input, which has no pad. A low reading is a short or a damaged U40 |

Diode test, red on TP7, black on each rail: 0.3–0.8 V (ESD and body diodes). 0.0x V is a short.

## B-4. First power-up from the bench "battery" (no firmware, no USB)

Panel fitted (B-1 item 5) or not; it is unpowered here either way. Bench supply 3.70 V, **100 mA** limit, into J2
through the pigtail.

**B-4.1 Current.** 20–50 mA [TVP]: the module runs its ROM (or whatever it shipped with; a blank module resets in a
loop), SNS_PWR_EN is held low by R5 so the AS5311, the op-amp, the panel logic and the LED are off, and the
backlight is off (R51). At the limit: power off, back to B-3.

**B-4.2 Rails.**

| Pad | Expected | Tolerance | If wrong |
|---|---|---|---|
| TP2 VBAT | 3.70 V (the supply minus Q1: < 10 mV at this current) | ±20 mV | open Q1 / J2: check the Q1 orientation |
| TP3 VSYS | ≈ VBAT (BATFET on) | VBAT − 50 mV … VBAT | 0 V: BQ25180 not up (VBATPOR, B-1 item 2; balls, B-2) |
| TP4 +3V3 | 3.31 V (511 k / 91 k, SPEC §3) | 3.25–3.37 V [TVP: FB accuracy + 1 % resistors] | 0 V: U3 / L1; wrong value: R3 / R4 |
| TP5 +3V3_SNS, TP6 +3V3_UI | < 0.1 V | | high: U5 / U6 ON not pulled low (R5) or a leaky switch |
| TP20 MCU_EN | ≈ 3.3 V (low for ~10 ms at power-up, R20 / C22) | | low: C22 shorted / reset held |
| TP21 BOOT_N | 3.3 V | | low: SW20 stuck |
| TP1 VBUS | < 0.1 V | | |
| TP50 LCD_BL, TP51 BUZZ | 0 V | | |

**B-4.3 Input range.** With the board running, lower the supply to 3.30 V, then 3.05 V, then raise it to 4.20 V:
TP4 stays 3.25–3.37 V throughout (buck-boost). Below ≈ 3.0 V the BQ25180 cuts SYS (BUVLO): that is expected.

**B-4.4 Reverse-polarity check (optional, Q1).** Supply off, pigtail reversed, 3.70 V, **10 mA** limit: the current
is < 10 µA (AO3401A IDSS ≤ 1 µA) and TP2 reads ≈ 0 V. Restore the polarity.

## B-5. USB without firmware

Bench supply off and disconnected (B-1 item 3) or left at 3.70 V with a 82 Ω dummy load across it (45 mA, more
than the charger's power-on default current [TVP]).

| Check | Expected | If wrong |
|---|---|---|
| TP1 VBUS | 4.75–5.25 V | D1 / U1 orientation, J1 |
| TP3 VSYS | ≈ 4.5 V: the BQ25180 power-on SYS_REG [TVP]; 4.4 V once the firmware sets it | |
| TP4 +3V3 | 3.25–3.37 V | |
| The PC sees "USB JTAG/serial debug unit" (USB-Serial-JTAG, ROM) | enumerates | D+/D− at TP22 / TP23: idle levels, the USB pair, U1 |

USB only, no cell: the MAX17048 is supplied from the charger's BAT pin, so the gauge may read about 4.2 V, a
sawtooth, or not answer [TVP]. Test the gauge with a cell or the bench supply on J2 (B-7).

## B-6. Flash the firmware and the boot log

Build and flash per [Firmware §13](firmware.md#_13-build-flash-test) over USB-Serial-JTAG
(`idf.py -p <port> flash monitor`; in WSL attach the port with `usbipd` first). If the chip will not enter download
mode: hold BOOT (SW20), short TP20 MCU_EN to TP7 briefly, release BOOT.

Supply: bench 3.70 V into J2 (150 mA limit) **or** USB alone, not both (B-1 item 3). With the panel fitted.

**Boot log** (USB-Serial-JTAG until TinyUSB takes the port; afterwards the CDC "Caliper console" carries it):

| Line | Expected | If not |
|---|---|---|
| `PrettyCool Caliper fw …, board rev A (pins ee472a43b6aab9d6), wake: power-on` | the pin hash of `nets.py` | wrong image |
| `power: BQ25180 ok, MAX17048 ok (0x001x), LSM6DSO ok` | all three ok | B-7.1 |
| `mag: AS5311 ok, pos …` or `mag: no valid SSI frame …` | without a magnet the field is out of range: either line is fine here | B-12 |
| `ui: display up` | | B-8 |
| `cap: capacitive scale enabled (EXPERIMENTAL), ADC 80645 S/s` | 80 645 S/s | B-13 |
| `app: running` | | a panic / reboot loop: the log above it |

Then TinyUSB enumerates a composite device: a CDC port ("Caliper console") and a small drive ("Caliper log").
The USB-Serial-JTAG port goes away; to flash again type `bootloader` on the console (Firmware §10).

**Current**, from the bench supply, display on, BLE advertising: ≈ 56 mA [TVP] (architecture §5: module 25,
AS5311 16, LCD 8, backlight 5, op-amp 1 mA; the LSM6DSO adds 0.3 mA with the gyroscope and the accelerometer
at 52 Hz in low-power mode, ST AN5192 Table 9, typical at 1.8 V). Above 100 mA: find the hot part (thermal camera / finger) before
going on.

`bu all` now runs the non-interactive checks in one go (B-7, B-10, B-12, B-13, B-14) and prints a summary. On a
bare board without the tape, `mag` fails; everything else should pass.

## B-7. Power path, I2C, charger, gauge

A real cell on J2 (polarity checked), or the bench supply at 3.70 V with the 12 Ω / 2 W load across its terminals
(B-1 item 3); USB attached for the console.

**B-7.1 I2C scan:** `bu i2c` → `PASS i2c: 3 found` (0x36 MAX17048, 0x6A BQ25180, 0x6B LSM6DSO, nothing else).

| Result | Meaning |
|---|---|
| 0x6B missing, 0x36 and 0x6A answer | the LSM6DSO's SA0 strap (U60 pin 1) is open or low: the chip then answers at **0x6A, on top of the BQ25180** ([electronics §3.6](electronics.md#_3-6-imu-lsm6dso)), so the scan cannot tell it from a missing chip, and `bu bq` may read nonsense. SA0 has no internal pull-up by default (DS12140 Table 19). Otherwise: U60 not soldered, or VDD / VDDIO (pins 8 / 5) missing |
| nothing answers | SDA / SCL shorted or open, R6 / R7 (2.2 k) missing, +3V3 not at the pull-ups |
| every address answers | SDA held low or shorted to SCL |
| 0x36 missing | U4 unpowered (it sits on VBAT, not +3V3: B-4.2 TP2) or the TDFN pad |

**B-7.2 Rails as the firmware sees them:** `bu rails <mV>` with the meter reading of TP2 in mV (e.g.
`bu rails 3702`). PASS: charger and gauge present, the gauge's VBAT within **±30 mV** of the meter [TVP: gauge
error + Q1 drop + meter]. The firmware has no ADC on VSYS or the 3.3 V rails: those are the meter readings of
B-4.2 (TP3–TP6), and +3V3 is implied by the MCU running.

**B-7.3 Charger:** `bu bq` prints the 13 registers, decodes STAT0 / STAT1 / FLAG0 and compares the registers with
the table the firmware wrote (Firmware §12.1). PASS: no fault, every init register as written.

| Field | Expected here | Meaning if not |
|---|---|---|
| IC_CTRL 0x07 | 0x97 | 0x17 / POR value: the write failed or the BQ25180 reset (watchdog?) |
| ICHG_CTRL 0x04 | 0x22 (70 mA); 0xA2 = charging disabled by the die-temperature guard | |
| TMR_ILIM 0x08 | 0xC9 before a host configures USB, 0xCD after (or 3 s of VBUS with no host) | |
| TS | normal at room temperature (RT1 10 k) | "TS open": RT1 missing / cracked; hot/cold: RT1 wrong value |
| VIN | good with USB, absent without | |
| BUVLO | shown with USB and no cell (expected), never with a cell above 3.1 V | |
| FAULT VIN over-voltage | never on a USB port (VBUS > 5.5 V) | the source, or a plug-in overshoot; re-plug and re-read |

**B-7.4 Charging** (a real cell, polarity checked, in a LiPo bag; meter in series in the J2 pigtail, 10 A range):
plug USB from a PC. `bu bq` reports `charge CC`; the cell current is **70 mA ±10 %** (63–77 mA; SLUSE99C ICHG_ACC,
specified from 40 mA) once the PC has configured the device (TMR_ILIM 0xCD); before that the 100 mA input limit
may leave less while the system runs (`active: ILIM`). `bu rails` VBAT rises slowly. Leave it to `charge done` once
(≈ 1–1.5 h from half charge, ≈ 2–2.5 h from empty [TVP]; it terminates at 7 mA) and check the cell at 4.20 V ±1 %. Unplug USB: the system continues from the cell without a reset.

**B-7.5 Gauge:** `bu fg <mV>` (TP2 reading). PASS: VERSION 0x001x, VCELL within ±30 mV of the meter, VRESET.Dis
set, HIBRT 0x8030, CONFIG.SLEEP clear (the firmware's settings: Firmware §12.2). SOC needs a few seconds after
power-up and a real cell to mean anything; on the bench supply it is whatever the model guesses.

## B-8. Display

`bu lcd` draws a test pattern over the UI, sets the backlight to 100 %, dims it to 10 % for 1 s, and asks.

Expected (landscape, the FPC end of the glass on the left): a 1 px **white frame on all four edges** with a 3–4 px
black gap inside; eight bars left to right **white, yellow, cyan, green, magenta, red, blue, black**; "TOP LEFT" at
the top left and "BR" at the bottom right, both readable.

| Symptom | Cause | Fix (all in `components/ui/ui_panel.c`) |
|---|---|---|
| backlight off | Q50 / R50 / LCD_BL; scope TP50: 20 kHz PWM | |
| backlight on, panel blank / white | panel not initialised: +3V3_UI (TP6), the FPC orientation (B-1 item 5), LCD_RST_N / CS / DC | |
| one edge of the frame missing, a strip of noise on the opposite edge | RAM offset wrong | `LCD_GAP_X` / `LCD_GAP_Y` (40 / 53 now; try 40 / 52, 52 / 40, 53 / 40) [TVP] |
| all colours inverted (white bar black) | the IPS inversion | `esp_lcd_panel_invert_color` |
| red and blue swapped | RGB / BGR order | `rgb_ele_order` |
| text mirrored, or "TOP LEFT" in another corner | rotation | `rotation.swap_xy / mirror_x / mirror_y` |
| colours wrong in a pattern of stripes | byte order | `swap_bytes` |

`bu lcd flip` shows the same pattern **turned 180°**, which is what the firmware does on its own when the caliper
is held with the button edge down (Firmware §7). Read it from the other side: the same complete frame, the same
bar order left to right, both labels readable. While either test runs the picture is pinned, so the IMU cannot turn
it under you.

| Symptom (only in `bu lcd flip`) | Cause | Fix |
|---|---|---|
| one edge of the frame missing, noise on the opposite edge | the turned RAM offset. The firmware derives it as 320 − 240 − `LCD_GAP_X` and 240 − 135 − `LCD_GAP_Y` (40 / 52 now) [TVP] | `LCD_GAP_X_TURN` / `LCD_GAP_Y_TURN` in `ui_panel.c`, after `bu lcd` itself passes |
| the picture is not turned | `ui_flip_poll` not reached: the UI refresh timer | |

Then the automatic flip, with the normal UI on screen: hold the caliper upright (buttons up), turn it over so the
buttons point down and hold it there. After about 0.6 s the reading turns to stay upright; turned back, it follows.
Lying flat on the bench it keeps whichever way it was. If it turns the **wrong** way round (upright only when held
upside down), the Y axis of the IMU is reversed: B-10 finds that. If it never turns, check `bu imu` (the
orientation line) and `CONFIG_CALIPER_UI_AUTO_FLIP`.

`bu lcd off` removes a pattern left on screen.

## B-9. Buttons, piezo, RGB LED

* `bu btn` → press ZERO, HOLD, MODE once each (short presses; they also act on the UI). PASS: each pressed once,
  none down at the start. A "glitch" count is a press shorter than 20 ms: the 100 k / 100 nF RC (10 ms) should leave
  none. A button down at the start: the switch or C52–C54 shorted.
* `bu beep` → two 4 kHz beeps (BZ50 resonance [TVP]). Silent: scope TP51 (4 kHz, 50 %), Q51, R57.
* `bu led` → red, green, blue, white, 0.7 s each. None: +3V3_UI (TP6), RGB_DIN, R55. Wrong colours: the
  WS2812 model in `outputs.c`.

## B-10. IMU: accelerometer and gyroscope

U60 is an LSM6DSO (SPEC §16). It sits on the top side at 0°, so the chip's axes are the board's: **+X** along the
beam toward the USB end, **+Y** toward the buttons (the top edge), **+Z** out of the display. The axis that points
up reads +1 g; a turn is positive when it is counter-clockwise seen from the tip of the axis. The directions come
from the datasheet's drawing and SPEC's placement: this step is what confirms them [TVP]. If one is wrong, the
only place to change is the mounting table at the top of `components/power/imu.c`.

* `bu imu` (board flat and still, display up) → WHO_AM_I 0x6C and |a| = **850–1150 mg** [TVP: offset + sensitivity
  tolerance], gravity on **+Z** (Z ≈ +1000 mg, X and Y near 0). The line above the verdict is the orientation the
  firmware derives (Firmware §12.2): `roll` and `pitch` near 0, `display up`, `steady`. Repeat it with the board
  standing on its jaw-side edge, buttons up: Y ≈ +1000 mg, `top edge up`, roll ≈ +90°; and on end with the USB
  connector up: X ≈ +1000 mg, `USB end up`, pitch ≈ +90°. 0 mg on all axes: the part is in power-down (the init
  failed: boot log).
* `bu imu move` → pick the board up and turn it over within 5 s. PASS: one axis swings ≥ 500 mg **and** IMU_INT1 went
  low (the wake-up interrupt that wakes the caliper on pickup). INT1 never low: GPIO15 / U60 INT1 (pin 4) routing,
  or the wake-up setup (MD1_CFG, TAP_CFG2). INT1 stuck low after clearing: the LSM6DSO has reset; its INT1 is then
  an input with a pull-down again until CTRL3_C is rewritten (Firmware §12.2), so reboot and repeat.
* `bu gyro` (board flat and **still** for 2 s) → the zero-rate level. PASS: the mean of each axis within
  **±3 dps** [TVP: the datasheet gives ±1 dps typical and no maximum] and no axis moving more than 2 dps
  peak-to-peak. `the gyroscope is powered down`: CTRL2_G was not written (boot log). `not lying still`: repeat
  without touching the bench. The line above the verdict is the filter's own bias estimate (it needs 1 s at rest)
  and the chip temperature.
* `bu gyro turn` → turn the board back and forth about one axis within 5 s. PASS: some axis reached **60 dps**.
  The verdict lists each axis' extremes with their signs: turn it counter-clockwise seen from the display side and
  Z must go positive; with the display facing you, tip the top edge toward and away from you and X changes; swing
  the USB end toward and away from you and Y changes. An axis that never moves: U60. The wrong axis or sign: the
  mounting table.

## B-11. Sensor rails (SNS_PWR_EN)

1. `bu sns off`: the firmware stops the display, drives the LCD / LED lines low and switches SNS_PWR_EN off. Meter
   TP5 and TP6: **< 0.1 V**, TP4 unchanged; answer `y`/`n`. A rail that stays up: U5 / U6, or a signal line
   back-powering the rail (the reading is then 1–2 V).
2. `bu sns on`: TP5 and TP6 equal TP4 within **20 mV** (TPS22917 RON × ≈ 25 mA [TVP]); the AS5311 answers again;
   answer `y`/`n`.
3. `reboot` (the display only comes back with a fresh start).

## B-12. AS5311

On the bench, before the beam: tape the magnetic-tape coupon to a 0.30 mm shim and hold it flat under the AS5311
(bottom, x ≈ 30), poles running along x (the beam axis), so the chip sees the gap it gets in the caliper
(Mechanical §7: 0.30 mm).

**B-12.1 Frames and field:** `bu mag` → one second of the sensor task's frames. PASS: ≥ 50 frames, ≤ 1 % bad,
the last frame valid (parity, OCF = 1, COF = 0) and the field **in range** (MagINC = MagDEC = 0, LIN = 0). It also
prints the MAG_INC_N / MAG_DEC_N pins: both high (1) when the field is in range (Mechanical §7 step 7; the pins are
the open-drain mirrors of the two bits [TVP]).

| Result | Meaning |
|---|---|
| no frames, `sensor rail off` | +3V3_SNS (B-11) |
| frames all bad, raw 0x3FFFF | DO stuck high: no sensor answering (rail, U30 soldering, MAG_DO) |
| raw 0x00000 | DO stuck low |
| parity errors now and then | SSI timing / noise on MAG_CLK / MAG_DO: scope them (500 kHz bursts every 10 ms) |
| field marginal (yellow) / out of range (red) | the gap: too far or too close (or no magnet). With the coupon: shim thickness |
| OCF = 0 for long | offset compensation never finished: supply, or no field |

**B-12.2 Count vs SSI:** `bu mag move` (15 s): slide the coupon **slowly** (under 5 cm/s) back and forth over at
least 4 mm. The quadrature count (PCNT) and the SSI position (unwrapped frame to frame on its own) are compared
the whole time. PASS: they agree within **16 LSB** (7.8 µm: the 2-edge hysteresis + one edge of read skew + the
lock tolerance; `AS5311_XC_TOL_LSB`) over at least one pole pair (2 mm) of travel.

| Result | Meaning / action |
|---|---|
| `moved too fast` | a step > 0.75 mm in one 10 ms sample: repeat slower |
| `moved less than 2 mm` | move further |
| `count runs against the SSI` | the SSI / count direction is the other way round: flip `SSI_SIGN` in `sensor_mag.c` (a TVP the code points to) |
| `count and SSI disagree` | missed edges or a bad line: scope TP30 / TP31 (MAG_A / MAG_B, square quadrature, no glitches), TP32 (MAG_IDX, one pulse per 2 mm) |

The printout also gives the pole crossings seen by the SSI and the index pulses counted in the same time: they
should be about equal [TVP: the index position within the pole and its hysteresis].

**In the caliper** (assembly step 8, [Mechanical §7](mechanical.md#_7-setting-the-gaps-assembly-procedure) step
7): `bu mag` at R = 0, 75 and 150 mm, field in range at all three; `bu mag move` over the first 20 mm; and the
direction: the reading must increase when the jaws open (else `CONFIG_CALIPER_MAG_DIR_INVERT`).

## B-13. Capacitive front-end (experimental)

**Without the scale:** `bu cap` → the DC level at the ADC and the last burst's raw I/Q. PASS: the DC level is
**1700–2700 LSB** [TVP: CAP_VREF 1.65 V through the filter, the uncalibrated 12 dB ADC]. Without coupling the
task stops itself after 50 empty bursts (2 s, logged): normal; the command then reports the last burst. Record the
amplitudes: that is the board's feed-through floor (should be well under 8 LSB, `CAP_MIN_AMP_LSB`) [TVP].

| Pad | Expected |
|---|---|
| TP41 CAP_VREF | 1.65 V ±2 % (+3V3_SNS / 2: R82 / R83 1 % on CAP_VDIV, buffered by U40B) |
| TP40 CAP_AMP_OUT | ≈ 1.65 V DC (the 10 MΩ feedback), bursts of ≈ 5 kHz every 40 ms when coupled |
| TP42 CAP_LP1 | as TP40 after 390 Ω / 1 nF |

**With the scale** (the scale board under the slider at the design gap, or in the beam): `bu cap scale` →
PASS: ≥ 90 % of the bursts valid and both amplitudes ≥ 8 LSB. In the caliper (Mechanical §7 step 7) the
amplitude should vary by less than ±30 % between R = 0, 75 and 150 [TVP]. With R60–R67 and R80 not fitted the
experiment is disconnected and `bu cap` only checks the op-amp's DC level.

## B-14. Radio: BLE and Wi-Fi RSSI (the antenna clearance deviation)

The module's PCB antenna gets **5 mm** of side clearance instead of Espressif's 15 mm (SPEC §2.1, "Antenna"):
a recorded deviation, checked here by comparing the caliper with an **ESP32-S3-DevKitM-1** (the same
ESP32-S3-MINI-1 module with full clearance) at the same spot. Flash the reference with the same firmware (it runs
without the peripherals and advertises with the same parameters [TVP]) or with ESP-IDF's NimBLE `bleprph` example.
`bu ble` prints the advertising TX power: use the same on the reference.

Setup: a room without people moving, the phone on a stand at **1.0 m** and then **3.0 m**, same height as the
board, line of sight. Each board on a non-metal stand, display up, the antenna corner (top left) toward the phone,
then turned 90°, 180°, 270°. Do it for the bare board on the bench, then again in the closed housing with the cell
fitted.

1. **Advertising RSSI on the phone:** nRF Connect scanner, the caliper ("PrettyCool Caliper"), the RSSI graph
   averaged over 10 s at each orientation. Same for the reference.
2. **Link RSSI at the caliper:** connect from nRF Connect, then `bu ble 10` → `link RSSI at the caliper avg …
   dBm` (20 readings). `bu ble 10 -70` fails below −70 dBm (pick the limit from the reference's reading).
3. **Wi-Fi:** `bu wifi` lists the networks with RSSI (strongest first); `bu wifi <ssid>` gives one access point's
   RSSI, `bu wifi <ssid> <min_dbm>` checks it. The same AP from the reference at the same spot (its scan example, or
   the same firmware's `bu wifi`). A scan measures reception only; the caliper transmits at most 10 dBm (the cap for
   the 135 mAh cell, SPEC §3), so also check that its web page loads at the 3 m spot. If the range is short and the
   battery peaks measure low, `CONFIG_ESP_PHY_MAX_WIFI_TX_POWER` is the knob (docs/firmware.md §12.6).

| Check | Pass [TVP] |
|---|---|
| caliper vs reference, each orientation, 1 m and 3 m, BLE and Wi-Fi | caliper no more than **6 dB** below the reference on average over the four orientations, and no orientation more than 10 dB below |
| in the housing with the cell vs bare | no more than 3 dB worse again |
| link at 10 m (phone in a pocket, through one wall) | stays connected, `bu ble` keeps reading |

6 dB halves the range in free space. If the caliper is worse, note at which orientations (the clearance is on the
board's right side, toward x 21): that is the input for rev B (antenna position, the battery pocket, the button
row).

## B-15. Deep-sleep current

Supply: a real cell (or the bench supply with the 12 Ω load across its terminals, B-1 item 3) → **µA meter with
its bypass switch closed** → J2. (A PPK2 in source mode can replace both once USB is out.)

1. Plug USB, type `bu sleep 15` (15 s delay), **unplug USB** within the delay (a VBUS change after the sleep
   would wake it through CHG_INT_N).
2. Once the display goes off, open the bypass and read the current after 10 s. Close the bypass before any wake
   (the boot current would overload the µA range).

**Expected: ≤ 40 µA** (SPEC §3 target; the estimate is ≈ 38 µA: ESP32-S3 8, TPS63802 Iq + divider 16.5, BQ25180 3,
MAX17048 3, LSM6DSO 5.5, 2 × TPS22917 0.02, conversion loss ≈ 2.2) [TVP]. The LSM6DSO figure is the
accelerometer alone at 12.5 Hz in ultra-low-power mode with the gyroscope powered down, typical at VDD 1.8 V
(AN5192 Table 9); the datasheet has no 3.3 V figure and nothing here is measured.

| Reading | Likely cause |
|---|---|
| ≈ 40 µA or a few µA above | the 4 µA defaults: BQ25180 push-button scan or MAX17048 VRESET.Dis (`bu bq`, `bu fg` before sleeping) |
| ≈ 0.3–0.6 mA | the LSM6DSO still in its awake mode with the gyroscope on (0.3 mA; the sleep log then shows `LSM6DSO sleep configuration failed`), or +3V3_SNS / +3V3_UI still on (next row) |
| ≈ 100–200 µA | a pull-up fighting a held pad (Firmware §12.5) |
| ≈ 0.3–1 mA | +3V3_SNS or +3V3_UI still on (meter TP5 / TP6: should be 0 V), a pad back-powering a rail |
| mA, display lit | not asleep: a wake source held low (button, IMU_INT1, CHG_INT_N); the boot log after a wake shows why |

3. **Wake sources:** a button press wakes it (log `wake: button`); picking it up wakes it (`wake: pickup`, IMU);
   plugging USB wakes it (`wake: usb`). If the log before sleeping says `IMU INT1 still low after clearing: pickup
   wake disabled for this sleep`, the board was moving while it went to sleep or the LSM6DSO has reset (B-10): the
   buttons and USB still wake it. After a pickup wake the reading continues (the count is recovered,
   Firmware §4) if the slider did not move more than ±1 mm while asleep.

## B-16. Ship mode

Same setup as B-15. With USB plugged, `bu ship`, then unplug USB: the BQ25180 enters ship (shutdown) mode once VBUS
is gone (with VBUS present the request waits). TP3 VSYS and TP4 +3V3 fall to 0 V.

**Expected: < 3 µA** from the supply [TVP]: BQ25180 shutdown 15 nA (SLUSE99C), MAX17048 forced sleep 0.5 µA typ /
2 µA max (19-6171; the firmware puts it there first), Q1 and the capacitors' leakage. A reading near 3–5 µA: the
gauge stayed in hibernate (the forced sleep write failed; `bu fg` after the next boot must show HIBRT 0x8030 again,
i.e. the firmware undid it). Plug USB: the board boots (`wake: power-on`).

## B-17. Per-unit checklist

| Step | Record | Pass |
|---|---|---|
| B-2 | visual, X-ray | clean |
| B-3 | TP1–TP6 resistances, TP20 / 21 / 50 / 51 / 41 | no short, within ±20 % of the first good board |
| B-4 | current at 3.70 V; TP2, TP3, TP4, TP5, TP6; TP4 at 3.05 V and 4.20 V | 20–50 mA; 3.25–3.37 V; TP5 / TP6 < 0.1 V |
| B-5 | TP1, TP3, TP4 on USB; enumeration | 4.75–5.25 V; ≈ 4.5 V; 3.25–3.37 V; enumerates |
| B-6 | boot log, awake current | three chips ok, display up, ADC 80 645 S/s; ≈ 56 mA |
| B-7 | `bu i2c`, `bu rails <mV>`, `bu bq`, `bu fg <mV>`; charge current; full-charge voltage | PASS ×4; 70 mA ±10 %; 4.20 V ±1 % |
| B-8 | `bu lcd`, `bu lcd flip`; the automatic flip by hand | PASS ×2; turns and turns back |
| B-9 | `bu btn`, `bu beep`, `bu led` | PASS ×3 |
| B-10 | `bu imu` in three positions, `bu imu move`, `bu gyro`, `bu gyro turn`; the axis signs | PASS ×4; +Z, +Y, +X up as described |
| B-11 | `bu sns off`, `bu sns on` | PASS ×2 |
| B-12 | `bu mag`, `bu mag move`; the SSI sign | PASS ×2 |
| B-13 | `bu cap` DC level and floor; TP41; `bu cap scale` | PASS; 1.65 V ±2 % |
| B-14 | BLE and Wi-Fi RSSI vs the reference, 4 orientations × 2 distances, bare and housed | ≤ 6 dB below on average |
| B-15 | sleep current; the three wake sources | ≤ 40 µA; all three wake |
| B-16 | ship current; USB wake | < 3 µA; boots |

After closing the housing, `bu all` is the quick regression (expect `SUMMARY 9 PASS, 0 FAIL` with the tape and the
scale in place, and the caliper lying still: `gyro` is one of the nine).

## Open [TVP] items

* Every limit marked [TVP] above, in particular: the first-power current, the +3V3 tolerance, the gauge-vs-meter
  ±30 mV, the 1 g band of the IMU, the gyroscope's ±3 dps zero-rate limit, the capacitive DC window and feed-through floor, the antenna's 6 dB, the sleep
  and ship currents.
* The AS5311 SSI direction (`SSI_SIGN`), the mag direction (`CONFIG_CALIPER_MAG_DIR_INVERT`), and whether the
  MagINCn / MagDECn pins mirror the SSI bits exactly.
* The display offsets (`LCD_GAP_X` / `_Y`) and orientation flags for the bought panel, and the turned offsets
  derived from them (40 / 52).
* The IMU: the sign of each axis against the board (B-10), the flip thresholds (≈ 20°, 0.6 s), the rest and
  steady thresholds of the orientation filter, and whether the 62.5 mg wake-up threshold picks the caliper up
  as readily as it did with the LIS2DW12 (the two chips filter the slope differently).
* The piezo frequency (4 kHz drive vs the BZ50 resonance), the WS2812 colour order.
* The BQ25180 behaviour with USB and no cell (the gauge's supply), and the power-on SYS_REG value.
* The reverse-polarity case with USB present (SPEC §3: not tested).
