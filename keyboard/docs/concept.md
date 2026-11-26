# Concept: features, decisions and the rev A testbed

The owner chose these features and decisions on 2026-11-25, from a researched shortlist ([research.md](research.md)).
**Nothing here is designed, built or measured.** Parts, stock figures and currents come from desk research on
2026-11-25. Recheck stock with `tools/lcsc_check.py` before designing around a part. Every figure is a candidate
until the testbed measures it.

## 1. What makes it different

Analog Hall-effect keys are no longer a differentiator. Wooting, Razer, SteelSeries, Keychron, Cherry and the ASUS
ROG Falcata all ship adjustable actuation, rapid trigger and 8 kHz polling, and libhmk does the same in open
firmware ([research §2](research.md#what-no-longer-differentiates)). The pitch has to come from what nobody
**combines**:

1. **Keys that point.** Push J or F sideways to move the cursor or scroll, with normal keycaps and no nub.
2. **Controls that change their feel to suit the task.** The thumb wheel ticks per line, stops hard at 0 and 100,
   and snaps to N slots, driven by per-app profiles that also set the haptics and lights.
3. **A keyboard that serves two computers at once.** Both wired, both enumerated, switched in one report interval.
4. **Firmware that explains itself.** It records why each key resolved as a tap or a hold, and it tunes the
   timings from your own misfires.
5. **Hardware as code, with gates.** One layout file generates the schematic, board, case and firmware. A release
   fails on a wiring, DRC, placement, latency or battery-life regression the way it fails on a DRC error today.

Each piece has prior art somewhere, listed honestly below. The integration, the openness and the gates are new.

## 2. Headline hardware

### 2.1 Shear keys

**What:** two to four keys (the index-finger home keys and the thumbs) also sense sideways push. With a pointing
layer held, they move the cursor or scroll, TrackPoint-style, without leaving the home row. Pressed straight down,
they type normally.

**Mechanism:** a 3-axis Hall sensor (TI **TMAG5170**, SPI, VSSOP-8) under each shear key reads the stem magnet's
X, Y and Z field. Z runs the normal analog press pipeline. X and Y, after removing the part that couples in from
the press, become a 2D vector. Stock MX stems wobble but have no centring force, so wobble is not a usable
pointing signal. This needs a **custom switch with a centring flexure stem** (build123d, printed or moulded), about
±0.3–0.5 mm of lateral travel.

**Prior art:** Expressive E Osmose senses lateral motion on every key, but on a music keyboard. Lenovo TrackPoint
and the Tex Shinobi point from a nub between G, H and B. Svalboard, DataHand and CharaChorder have multi-direction
keys that replace normal typing. Research: McPherson TouchKeys (CHI 2011), Buschek et al. (CHI 2018).
**New:** TrackPoint-style pointing on normal-feel typing keys, with any keycap and no nub.

**Risks:** typing strikes carry real lateral force, so an automatic "intent gate" will misfire. Plan on a held
pointing layer. Z-to-XY crosstalk changes with press depth, so calibration is a function of depth, not one matrix.
A ±0.3 mm isometric key suits pointing and scrolling but makes a poor gaming thumbstick. The custom switch needs
several mechanical revisions, and JLC does not assemble it.

**Stage:** rev A coupon (TMAG5170 sites under a stock stem and under a centring-stem prototype); rev B on 2–4 keys.

### 2.2 Generated keywell

**What:** a concave keywell (Kinesis Advantage / Glove80 shape) whose PCBs come straight from the build123d case,
fitted to your hand, and checked **in their bent shape** against the case.

**Mechanism:** rev B uses rigid 0.8 mm column boards (one per finger column, identical where possible so JLC
assembly is cheap) held at their poses by the case, joined to a main board. Rev C develops the columns into one
polyimide flex per half with FR4 stiffener islands under each key. Hall-effect keys suit this well: there are no
hot-swap sockets to fail on a curved board. The clash check runs on the folded state.

**Prior art:** YKB Skadi (2026) already ships an open Hall-effect keywell on bendable column PCBs (TMAG5253,
nRF5340, Zephyr). Cosmos generates keywell cases with column-flex and per-key PCBs, and fits them from a phone hand
scan. janaka, fmcraft and TheBigSkree have hand-drawn Dactyl flex PCBs. **New:** boards generated from the case
model and gated in their bent state (DRC, parity, jlcplace, clash) for any fitted geometry.

**Risks:** a splayed keywell is not one developable surface. Real designs end up as per-column strips joined at a
spine, as Skadi and Cosmos do. The Hall signal falls off steeply with gap, so each island must sit to about 0.1 mm.
JLC warns that steel stiffeners are slightly magnetic and should not be used with Hall sensors: use FR4. Flex
assembly cost and yield for about 40 islands per half are unknown until JLC quotes it.

**Stage:** rev B rigid columns; rev C flex.

### 2.3 Haptic thumb wheel

**What:** one thumb control whose feel changes with the task. It ticks once per line in the editor, jumps per diff
hunk, stops hard at volume 0 and 100, snaps to N slots for a game's weapon wheel, and spins free for long documents.

**Mechanism:** a low-cogging BLDC gimbal motor under a roller, a magnetic angle encoder on the shaft, and
field-oriented control (FOC) from the MCU. Detents, end stops and inertia are tables chosen by the context profile
(§3.3). Parts from the stock check: the TMC6300 driver had only 21 in stock at JLC, so the **DRV8316** (C5218861)
is the stocked alternative. For the encoder, the QFN MT6701 was out of stock, so the **MT6701CT** SOP-8
(C3202694) or the AS5047P. The motor, magnet and roller are fitted by hand.

**Prior art:** Peng Zhihui's HelloWord keyboard (2022, GPLv3) has a built-in FOC haptic knob on its own MCU and
battery. CNCDan's Hapticpad (2026) is a macropad with nearly this exact horizontal haptic wheel. SmartKnob and its
derivatives are standalone. Surface Dial gives per-app vibration ticks. **New:** a wheel in an ergonomic thumb
cluster, driven by the same declarative profiles as the rest of the board.

**Risks:** power. Strong detents peak at about 0.5–1 A on 5 V (*estimate*), and HelloWord needed its own battery
because the knob drew more than USB 2.0 could supply. So the wheel is wired-first, with an LRA-ticked capacitive
strip as the battery-mode stand-in (§3.3). Motor cogging limits how crisp the detents feel, and SmartKnob builders
report motor choice as the hard part. A wheel placed away from the home row may see little use.

**Stage:** rev A coupon (driver, encoder, motor; measure current and feel); rev B in the thumb cluster.

### 2.4 Analog from stock switches (printed coils)

**What:** analog travel with no magnets: a coil printed in the PCB copper under each key. The moonshot version reads
the compressing steel spring of a **stock** MX switch, so tactile and clicky switches become analog too.

**Mechanism:** the toolchain generates the spiral coils as footprints (`fpgen.py` already generates the caliper's
capacitive scale electrodes) and computes their inductance in Python. An inductance-to-digital converter reads
them (TI LDC1614-class, or Azoteq IQS9320). A design-of-experiments coupon carries about 20 coil variants (turns,
trace and space, layers, diameter).

**Prior art:** inductive keyboards ship: the Epomaker Magcore boards use PCB coils read by IQS9320s. Cherry showed
inductive switches at Computex 2025, reported in the Ducky One X. TI's TIDA-00509 is a coil keypad reference design.
Spring sensing has DIY proofs of concept (Hackaday 2018, Pawnerd). **New:** analog from unmodified stock switches,
if the signal holds up. It is unproven.

**Risks:** most of the spring sits several mm above the coil, and a forum report calls the spring signal strongly
non-linear, so it may only work as a threshold. Coils need copper-free layers under every key, which fights the
solid ground the Hall sensors want: it is a separate board variant, not a per-key option. The IQS9320 is QFN52 at
0.35 mm pitch, and DigiKey lists it as discontinued. The LDC1614 fallback costs about $0.5–1 per key
(*estimate*). Cherry describes its inductive approach as patented, so a freedom-to-operate check comes before
publishing a switch-plus-coil design.

**Stage:** rev A coil coupon only. Rev C if the coupon shows a usable spring signal; dropped if not.

## 3. Daily-driver features

### 3.1 Two-host KVM

**What:** plugged into a work laptop and a personal or gaming PC at the same time, plus BLE hosts. One key moves the
keyboard to the other machine in one report interval, with no re-enumeration and no reconnect.

**Mechanism:** two USB-C upstream ports, each with its own USB device controller that stays enumerated: the main
MCU's on host A, a small second MCU (CH32X035 full speed, or CH32V305 high speed) on host B, linked through a
digital isolator (ISO7721 or ADuM1201 class), the split DeskHop uses. Switching only changes which controller gets
the reports. Rev B can add a downstream port for a mouse (a MAX3421E-class USB host) or relay a BLE mouse instead.

**Prior art:** DeskHop (two RP2040s behind an isolator, a box), HID Remapper (dual RP2040, USB host), USB-C KVM
monitors, Logitech Easy-Switch (reconnects) and Flow (needs host software). **New:** inside the keyboard.

**Risks:** power topology comes first. With isolation, the keyboard side has no power when only host B is plugged
in, unless the battery or an isolated DC-DC feeds it. Without isolation, OR the two VBUS supplies and accept a
shared ground. A full-speed host-B controller caps that host at 1 kHz. USB host support in Zephyr is experimental.
Screen-edge mouse switching inherits DeskHop's documented OS problems (Windows multi-monitor, macOS). The generator
and DRC need an isolation slot and a creepage rule. Managed work laptops may block a composite device:
**per-host interface sets** help, where the work laptop sees a plain boot keyboard and the personal PC sees
everything.

**Stage:** rev A coupon only if it fits (dual upstream and isolator); rev B key-switched; rev B+ mouse passthrough.

### 3.2 Tap/hold flight recorder and tuner

**What:** record a typing session, then see every press on a timeline with the firmware's decision and the reason
("hold: another key went down at +142 ms"). Mark the misfires, and the tuner computes per-finger timings that would
have resolved them correctly.

**Mechanism:** an opt-in RAM ring buffer (about 12 B per event, so about 120 KB for 10 000 events) of key, µs
timestamps, analog samples and the hold-tap and combo decision trace. The tuner replays the recording through the
firmware's own decision code: first in Zephyr's `native_sim` on the PC, later compiled to WebAssembly in the web
app. It checks the result on held-out typing before it pushes the new timings.

**Prior art:** hrm-tuner (host-side logging for ZMK home-row mods), ZMK's debug logging and `native_sim` behaviour
tests (replay, but not from recordings), Keyboard Heaven's calibrator, KeyPath for Kanata. **New:** capture on the
device, with the firmware's reasons, and tuning by replay through the real code.

**Risks:** a recording of key positions with µs timing is a keylogger. It must be opt-in, held in RAM, expire on its
own, and never leave the device without explicit consent. The tuner can overfit to a few flagged misfires.

**Stage:** firmware; on the rev A testbed as soon as keys report.

### 3.3 Context-aware feel

**What:** per-app profiles that set the wheel's detents, the haptic ticks, the lights and the layers. When your AI
coding agent asks for approval, the wheel grows a notch ring: twist through the hunks, press to approve.

**Mechanism:** profiles are declarative files in the repo, schema-checked and unit-tested in CI like the hardware
gates, and editable in the web app. Context comes in three ways, cheapest first. (1) **Standard HID:** enumerate
the wheel as a Windows Radial Controller (the Surface Dial usage, with its haptic output) and the LRAs as a HID
haptic controller, so Windows gives per-app dial menus and ticks with nothing installed. (2) The web app over
WebHID or Web Bluetooth. (3) An optional small host agent for the foreground app, CI state or agent prompts.
Feedback: a DRV2605L haptic driver (C527464) and a coin LRA per half, with a small, user-tested vocabulary (tick,
double tick, long buzz), plus a capacitive strip on the MCU's touch pins with LRA-synthesised detents as the
low-power wheel.

**Prior art:** QMKonnect, auto_layers and komokana switch layers by app. Surface Dial and the Logitech MX Master 4
give per-app haptics. DRV2605L haptics on home-row-mod holds exist in DIY ZMK builds. **New:** one tested profile
drives detents, haptics and lights together.

**Risks:** a host agent is a privacy and maintenance burden, so lean on standard HID first. WebHID works only in
Chromium. Reading game state can trip anti-cheat. People learn only 3–5 haptic patterns reliably. LRA buzz is
audible on a hard desk.

**Stage:** rev A LRA coupon; firmware and profiles from rev A; full use in rev B.

### 3.4 Per-finger analog tuning and load budget

**What:** the keyboard learns how each finger presses, sets each key's actuation point and rapid-trigger
sensitivity to match (shallower for the pinkies, deeper for keys that collect accidental grazes), and shows the load
each finger carried, with nothing leaving the device.

**Mechanism:** firmware keeps per-key aggregates (press depth, peak velocity, bottom-out ratio, resting
pre-travel) from the analog sensing. An adaptation loop learns, then **freezes**, so muscle memory is not undermined.
A fixed competitive profile turns adaptation off. Related, from the research: **switch fingerprinting** (identify a
hot-swapped switch from its field-versus-travel curve, so actuation in mm stays true on mixed switches) and
**common-mode reference sensors** (two to four Hall sites with no switch, plus thermistors, to subtract stray fields
and temperature drift).

**Prior art:** SteelSeries Protection Mode (global accidental-press rejection), adaptive touch targets on phone
keyboards, Razer Synapse and WhatPulse heatmaps, libhmk's manual per-key actuation. **New:** closed-loop per-key
adaptation on analog mechanical keys.

**Risks:** "finger load" is not validated against injury outcomes, so the docs must say designed, not validated.
Keystroke dynamics are biometric: store per-key aggregates, never sequences or inter-key timing.

**Stage:** firmware; data collection on the rev A coupons.

## 4. Toolchain showcase

### 4.1 Keyboard compiler

**What:** edit one layout file and get the wired schematic, the routed board, the case and plate, the firmware
matrix, pin header, physical layout and keymap, and the docs, all regenerated and consistent with each other.

**Mechanism:** a layout source holds each key's 3D pose, sensor type, finger and scan slot, and drives the existing
generators (`schgen`, `pcbgen`, build123d, the firmware header). New work: a grid placement mode in `schplace`, so a
key array with no anchor IC still passes R1–R6, and a pose-driven placer in place of a hand-written `layout.py`.
**Cross-domain contract checks**, generalised from `check_contract.py`:

* the netlist's MCU pins equal the firmware pin header,
* PCB switch centres equal the case cutouts and the firmware's physical layout, within 0.05 mm,
* the scan map in the netlist equals the one in firmware,
* a **keycap clearance gate**: real keycap solids swept from rest to bottom-out at every pose, checked against each
  other, the case and tall parts, with a tolerance pass. This reuses `clash_check.py`.

CI runs the same gates on every fork: wiring check, ERC, DRC, schematic parity, the jlcplace placement simulation,
the clash and keycap checks, the firmware build and tests, and the docs build.

**Prior art:** Ergogen (outlines, cases and an un-routed PCB, no schematic), kicad-kbplacer (placement and simple
matrix routing, a label-wired schematic), Cosmos (cases and firmware for its own fixed PCBs, open-core). The Corney
Island CI already runs Ergogen, Freerouting and DRC to Gerbers on push. **New:** a readable wired schematic, ERC and
parity, the jlcplace gate (wrong rotations of sockets and reverse-mount LEDs in JLC's placement file are a classic
keyboard fab failure), and the cross-domain checks.

**Risks:** the toolchain is not parametric yet. The caliper's `layout.py` is about 3 000 lines of board-specific
placement and pre-routes. Freerouting has no documented seed option, so routes may not reproduce: commit routed
boards and re-check them in CI, and re-route only when the layout changes.

**Stage:** v0 in rev A (it generates the coupons); full in rev B.

### 4.2 Latency and battery gates

**What:** every firmware release carries measured press-to-report latency (p50 and p99) per mode, and a battery-life
estimate from the bill of materials. A regression fails the release.

**Mechanism:** *latency:* a generated rig board injects a stimulus at a sensor's ADC node through a test pad (or a
coil next to the sensor, or a solenoid on a real key) and timestamps the HID report, acting as the USB host. The
keyboard exposes per-stage timing (capture, decision, queue, transmit) and a marker GPIO. A high-speed USB sniffer
(Cynthion or ataradov's usb-sniffer) checks 8 kHz microframes. Note that row/column contact injection, as in a
digital matrix, does not apply to analog keys. *Battery:* a per-state current table for every BOM line, next to
`mpn-map.csv`, combined with the firmware's declared duty cycle (scan rate, BLE interval, sleep policy, LEDs, split
link), gives battery life and worst-case latency. The figure stays *designed* until a measured current log replaces
it.

**Prior art:** RTINGS and LTT Labs measure latency with a solenoid and a USB analyzer. Michael Stapelberg measured
QMK. joelspadin's keyboard-latency-tester injects electrically across one switch. The ZMK Power Profiler estimates
battery life, for nice!nano-class boards and not tied to a BOM. **New:** gating releases on both.

**Risks:** BLE latency depends on the host's stack and OS, so publish it per host. A full-speed USB host quantises
timing to about 1 ms, so a fine p99 gate needs many strikes or a high-speed host.

**Stage:** rev A (the testbed's purpose includes measuring these); then on every firmware release.

### 4.3 Sensing testbed

**What:** rev A itself: a motherboard plus coupons that compare the sensing methods side by side under the same
switches, with the raw data published as an open dataset (noise floor, drift with temperature, crosstalk, latency,
current).

**Prior art:** ThereminGoat's force curves (a huge open set, but mechanical only), and vendor blog comparisons of HE
and TMR without raw data. **New:** an open, measured comparison across sensing methods.

**Stage:** rev A. See §7.

### 4.4 Fit to your hand

**What:** S/M/L presets (from anthropometric percentiles) or your hand measurements set the column stagger, splay
and thumb-arc geometry, and out comes a JLC-assembled board and case that fit you.

**Mechanism:** a parameter mapping into the compiler (§4.1). Rev C adds a phone-photo capture: ArUco fiducials on the
case (the caliper already prints ArUco inlays, [mechanical §16](../../caliper/docs/mechanical.md#_16-aruco-markers-on-the-jaws-2026-11-15))
let the web app measure both halves' pose, and a hand tracker estimates wrist angle against the under-30° extension
target from the ergonomics literature (Rempel, Keir & Bach 2008).

**Prior art:** Cosmos fits a keywell from a phone hand scan, but for its own fixed PCBs. Ergogen users hand-tune
stagger and splay in YAML. Squeezebox, FCS42S and key-yack's magnetic columns are passive adjustable rigs. **New:**
a fitted, gated, JLC-assembled board per user.

**Risks:** nobody has validated the mapping from hand measurements to stagger and splay, and a wrong fit is worse
than a standard Corne. Each unique board pays JLC's setup and extended-part fees (tens of USD per design,
*estimate*). Camera wrist angles are likely only ±5–10° (*estimate*) and must be checked against a goniometer.

**Stage:** presets in rev B; phone capture in rev C.

## 5. Platform: let the testbed decide

The owner's decision: the rev A testbed measures the sensors' real current, and the battery-budget gate (§4.2) picks
the rev B chip. The candidates, from the research:

| Chip | For | Against |
|---|---|---|
| **Artery AT32F405** (rev A testbed) | On-chip high-speed USB PHY. Artery's own magnetic-keyboard reference design and libhmk reach 8 kHz polling and 16 kHz scanning on it | No radio. LCSC/JLC stock not checked |
| **Nordic nRF54LM20A** | High-speed USB (Nordic says 8 kHz HID), BLE 6, 4 Mbps proprietary link for a split or dongle, low BLE current | The 66-GPIO part is a 0.35 mm-pitch CSP (HDI board). The QFN52 (32 GPIO) was still sampling. Nordic says 8 kHz USB plus the proprietary link together are CPU-bound |
| nRF52840 / nRF54L15 | Mature in Zephyr, months on a charge | Full-speed USB: 1 kHz |
| Espressif ESP32-S31 | High-speed USB, stays in ESP-IDF | Preliminary datasheet; weaker BLE power than Nordic |
| WCH CH585 | BLE 5.4 plus high- and full-speed USB, stocked at LCSC, cheap | Weaker open-source ecosystem |
| ESP32-S3 (the caliper's) | Familiar, gated sheets exist | Full-speed USB only (1 kHz cap); BLE HID current in the mA range |

Whatever wins, prefer a pre-certified radio module if one is stocked: a bare-chip RF design (matching network,
50 Ω feed) would be a first for this toolchain. High-speed USB needs 90 Ω pairs on JLC's controlled-impedance stack,
pre-routed, because Freerouting is not impedance-aware.

## 6. Firmware: custom on Zephyr

Owner decision: **custom firmware on Zephyr**, with ZMK-compatible keymap files where possible. ZMK mainline has no
analog keys and no USB host, and this board needs both, plus haptics, a second USB controller and the flight
recorder. Patching ZMK would mean carrying those changes forever. Zephyr covers the Nordic, Artery and ESP32
candidates. The hold-tap and combo logic is kept free of hardware calls, so the same code runs in `native_sim` for
the recorder's replay and the CI tests, and later in WebAssembly for the web app. The caliper's ESP-IDF firmware stays
as it is.

## 7. Rev A testbed

A **motherboard plus plug-in coupons**. Each coupon is generated by compiler v0, so rev A also proves the compiler.

| Board | Carries | Measures / proves |
|---|---|---|
| Motherboard | AT32F405 (high-speed USB), USB-C, power and charging (from the caliper's power sheets), coupon connectors with analog and SPI lanes, test pads and a marker GPIO for the latency rig, current-sense points per coupon | 8 kHz scanning, per-coupon current, the latency gate's hooks |
| Hall-effect coupon | TMAG5253 per key (enable-gated, outputs high-impedance when off), compliant-stop aftertouch sites, two switch-free reference sensors and thermistors | Noise, drift, the bottom-out knee, a shared-bus topology at 1 and 8 kHz |
| TMR coupon | The same keys on a TMR sensor | Hall-effect against TMR on noise and current |
| Shear coupon | TMAG5170 under a stock stem and under a centring-stem prototype | The lateral signal and press crosstalk |
| Coil coupon | About 20 generated coil variants under stock MX switches and slug-stem switches, read by an LDC1614-class converter | Whether a stock spring gives a usable analog signal |
| Haptics coupon | DRV8316 + MT6701CT + gimbal motor; DRV2605L + LRA; a capacitive strip on touch pins | Wheel current and detent feel, LRA localisation and noise |
| Latency rig | A generated board that injects at a sensor node and is the USB host for the report | Press-to-report p50/p99 per mode |

The two-host KVM path (second USB controller and isolator) goes on its own coupon if the motherboard's connector can
carry it. Otherwise it waits for rev B.

**Rev A is done when:** each coupon has a measured current and noise figure in the docs, the coil coupon says yes or
no to stock-spring sensing, the shear coupon says whether a centring stem gives a usable pointing signal, the wheel
coupon has a measured peak and average current, the battery gate picks a rev B chip from measured numbers, and the
compiler has generated and gated every coupon.

## 8. Conflicts the testbed has to settle

| Conflict | Why | Settled by |
|---|---|---|
| Coils against Hall sensors | Coils need copper-free layers under each key, and the Hall analog buses want solid ground | Separate coupons, then a board variant if coils win |
| Wheel against battery | 0.5–1 A detent peaks (*estimate*) against a LiPo budget | Wheel coupon current; wheel full-strength when wired, a capacitive strip with LRA ticks on battery |
| 8 kHz against battery | Fresh 8 kHz reports need sensors on nearly all the time; an enable-gated bus only allows one sensor per column at a time | Hall and TMR coupon currents at 1 and 8 kHz; 8 kHz likely wired-only |
| KVM power | With isolation, the keyboard needs power from whichever host is present | A power design on the KVM coupon |
| Keywell against flex | A splayed keywell does not unroll into one flat sheet | Rigid columns in rev B, flex only after the bent-state gate works |
| Magnetometer against magnets | The caliper's compass idea fails next to 60 switch magnets, so splay can't be sensed on board | Phone-photo fiducials (§4.4) |

## 9. Open questions

* The working name, and whether the folder stays `keyboard/`.
* Which layout format the compiler reads: its own Python, or Ergogen or KLE input for compatibility.
* Hot-swap magnetic switches on rev B (a plate-mount HE ecosystem: Gateron, Lekker, TTC, Kailh) or socketless.
* How many shear keys: two index keys plus the thumbs, or all eight home keys.
* Wi-Fi: the caliper's research leans towards dropping it. The keyboard's companion app works over USB and BLE.
