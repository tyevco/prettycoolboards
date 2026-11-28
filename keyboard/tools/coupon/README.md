# Coupon tools (compiler v0)

> **Status (2026-11-28):** tools written and tested on synthetic fixtures, and run on the coupons generated so far
> (the test coupon, the Hall-effect coupon, the haptics and coil coupons), with faults injected into copies of them.
> They follow the owner's decisions of 2026-11-27: the slot key at pin 39 (D2), the 100 Ω on the slot's direct lines
> (D3) and the test coupon's INJ path (D7). **No coupon has been built, and no descriptor EEPROM has been written or
> read.** Every check here reads files: it proves the code and the arithmetic, not hardware.

[Concept §4.1](../../docs/concept.md#_4-1-keyboard-compiler) calls for a keyboard compiler whose v0 generates and
gates the rev A coupons. These are its coupon gates and its descriptor, against the architecture of record
([SPEC](../../hardware/design/SPEC.md) §2, §4.6 and §4.9) and the slot contract (`nets.py`,
`boards/coupon_common.py`):

| File | What |
|---|---|
| [`DESCRIPTOR.md`](DESCRIPTOR.md) | The descriptor format, 1.0: the 256 bytes of every coupon's M24C02 at 0x50, and how firmware reads and the bench writes them |
| `descriptor.py` | The format's single source: JSON to image and back, CRC, the C header, the tables in DESCRIPTOR.md |
| `coupon_desc.h` | Generated C header: packed structs with every offset asserted, enums, `coupon_desc_validate()` |
| `descriptors/<board>.json` | One descriptor per coupon board. `test-coupon`, `coupon-hall` and `coupon-haptics` from their captured designs (their currents are design estimates, listed in `placeholder_fields`); `coupon-tmr`, `coupon-shear` and `coupon-coil` are **placeholders** from SPEC §4.8's plan, flagged as such in every image made from them |
| `rules.py` | The coupon rules check: a coupon's netlist, board and descriptor against SPEC; a table per coupon, exit 1 on any FAIL |
| `make_eeprom.py` | EEPROM images per coupon and serial (`.bin`, Intel `.hex`, decoded `.json`, optional Zephyr shell commands) |
| `coupon_model.py` | Readers: the KiCad netlist (through `tools/sexpr.py`) and the board (through pcbnew) |
| `tests/` | pytest: fixtures with one thing wrong each, faults injected into copies of the real generated boards, the frozen format, the C header against the encoder byte for byte (host and Cortex-M33), a Zephyr `native_sim` app |

## Commands

From the repository root, with the toolchain venv (pcbnew, KiCad 10.0.8):

```sh
PY=/root/.venvs/kbd/bin/python          # the caliper's WSL equivalent is $HOME/.venvs/dial-me-spinner/bin/python
export PYTHONDONTWRITEBYTECODE=1        # pytest would otherwise leave tests/__pycache__ (git-ignored)
$PY keyboard/tools/coupon/rules.py                       # every generated coupon; exit 1 on a FAIL, 2 if none exists
$PY keyboard/tools/coupon/rules.py --release             # before ordering boards: also FAIL placeholders, unrouted
$PY keyboard/tools/coupon/rules.py --all --quiet         # also the coupons not generated yet, and the five together
$PY keyboard/tools/coupon/rules.py test-coupon --json /tmp/rules.json
$PY keyboard/tools/coupon/make_eeprom.py                 # images for every descriptor, serial 0, into build/eeprom/
$PY keyboard/tools/coupon/make_eeprom.py test-coupon --serial 1-4 --shell coupon-s1 --no-placeholder
$PY keyboard/tools/coupon/make_eeprom.py --check keyboard/tools/coupon/build/eeprom/test-coupon-s0001.bin
$PY keyboard/tools/coupon/descriptor.py decode IMAGE.bin           # what the firmware will see
$PY keyboard/tools/coupon/descriptor.py header                     # regenerate coupon_desc.h after a LAYOUT change
$PY keyboard/tools/coupon/descriptor.py doc --write                # and DESCRIPTOR.md's tables
$PY -m pytest keyboard/tools/coupon/tests -q -p no:cacheprovider -m "not slow"   # about 15 s
$PY -m pytest keyboard/tools/coupon/tests -q -p no:cacheprovider                  # + 4 native_sim builds, ~65 s more
```

`build/` is git-ignored. The slow tests need a Zephyr v4.5.0 workspace (`/root/zephyrproject`, `ENV.sh`; override
with `ZEPHYR_BASE` and `COUPON_ZEPHYR_ENV`); the C header tests need gcc and, for the Cortex-M33 compile,
arm-none-eabi-gcc. Tests skip what the machine lacks.

Run `rules.py` after `build.py` and `layout.py` have regenerated a coupon, and `rules.py --release` before
`release.py` and before boards are ordered: plain `rules.py` exits 0 for a coupon whose descriptor is still a
placeholder or whose board is half routed (both WARN), `--release` fails them. Then `make_eeprom.py --no-placeholder`
makes its images; it runs the netlist and board rules too when the board is generated, so a descriptor its board
contradicts is refused.

## The rules

Each row of the table is one rule. FAIL breaks SPEC or the slot contract; WARN is a judgement or a heuristic to look
at; INFO is a figure worth knowing; SKIP means an input is missing. Sources: N netlist, B board (pcbnew),
D descriptor.

| Rule | Src | Checks | Can catch | Cannot catch |
|---|---|---|---|---|
| `outline` | B | Edge.Cuts is one closed outline of a coupon size (58 × 60 or 80 × 60 mm, ±0.05) and the descriptor's size | a wrong or open outline, a size the descriptor contradicts | the corner radius, a notch inside the bounding box |
| `layers`, `ground_plane` | B | 4 copper layers, 1.6 mm; GND fills ≥ 80 % of In1 | a 2-layer coupon, a missing or broken ground plane | whether each lane runs over it (a heuristic) |
| `header.footprint`, `.side`, `.position` | B | the slot header footprint, on the bottom, every pad within 0.02 mm of `coupon_common.pin_xy(n)`; a uniform shift or a rotation is named | a moved, rotated, mirrored or top-side header: anything that would not mate with the socket `coupon_common` places | the part's real pin length, solder fillets |
| `pins.net`, `pins.pcb`, `pins.parity` | N, B | each header pin carries its own slot net (`nets.SLOT_PINS`) or none, on the board and in the netlist, and both agree | a swapped or shifted pin, a board not regenerated after a schematic change | a net named right but wired wrong behind the header (the other rules) |
| `gnd_pins`, `present_n`, `rails.*`, `shorts`, `stubs` | N | all 13 GND pins on GND, PRESENT_N strapped to GND, each rail's pins all or none, no two slot signals on one net and none tied to GND or a rail, no slot net that reaches nothing | a missing PRESENT_N strap (also one through a resistor), CS0_N tied to GND, a half-connected rail | the motor return actually using pins 4–6 |
| `key`, `key.pcb` | N, B | **the slot key** (the owner's decision D2 of 2026-11-27, SPEC §4.2, §4.9; it replaced the `rsv` rule): J1 has **no pin 39** in its symbol and **no pad 39** on the board, no net on 39, and **pin 2 present** (`nets.SLOT_KEY_NEVER_WITH`: keyed at 2 and 39 together, a coupon fits either way round) | a coupon drawn or laid out with the stock 40-pin header (it would hit the socket's plugged hole 39 and not go in), a net on pin 39, a header keyed at both 2 and 39 | whether the header's pin 39 is really pulled and the socket's hole really plugged (hand steps) |
| `reversal`, `reversal_if_unplugged`, `misinsertion` | N | what a wrongly plugged coupon does. Turned 180° (pin n meets pin 41 − n) its pin 2 meets the socket's plugged hole 39: PASS, it cannot go in; with the plug missing it would read as present (PRESENT_N on its pin 9, GND) and meet +3V3_S*n* on G1/G0 (INFO, `reversal_if_unplugged`). Of the six offsets (one column either way, one row either way, turned and one column off either way) the plug blocks the three that put a coupon pin on hole 39; the other three are checked for pin 32 on a coupon GND (WARN) | a coupon without pin 2 (the key no longer stops the half turn: WARN if it then reads present), a pinout that makes an unblocked misinsertion look present | whether the coupon's parts would actually pass current into the MCU pins (it depends on their inputs); whether the post or the socket body stops a misinsertion |
| `slotlines.idle` | N, D | each MCU-driven slot line the coupon uses (CS0_N, CS1_N, G0–G3, and G4/G5 in S5) has a resistor to a rail or GND on the coupon: the bring-up firmware leaves these lines high-impedance from +3V3_S*n* on until it has read and checked the descriptor (`bringup/src/slot.c`, risks.md EL-2), so only the coupon holds them then (WARN without one; SPEC §4.9 has no such rule) | a select or enable left floating at power-up | a part's own internal pull (not in the netlist): the haptics coupon's G0–G5 into the DRV8316 WARN for that reason |
| `slotlines.dc`, `.edges`, `.contention`, `.irq_n` | N, D | **the slot's direct lines through the motherboard's 100 Ω** (D3 of 2026-11-27, SPEC §4.3, `nets.SLOT_SERIES`: CS0_N, CS1_N, IRQ_N, G0–G3, and G4/G5 in S5) against what the coupon puts on them, in the descriptor's slots: the DC load of its fitted resistors (Thevenin to GND, +3V3, +5V), driven from 0 / 3.3 V through the 100 Ω and the MCU's driver (taken as 50 Ω, DS13543 Table 88 at 8 mA): the level at the coupon and the pin current, FAIL above the 8 mA at which Table 88 holds; a capacitor on such a line (WARN: SPEC §4.3's timing assumes about 40 pF behind the 100 Ω), with τ and the edge; an output-type pin on a line the MCU drives (WARN, contention up to 22 mA through 150 Ω); IRQ_N and G-lines of role `input` (INFO: the coupon's pull-up current does not flow through the 100 Ω) | a strong pull or load on a select (220 Ω to GND draws 8.9 mA), an RC filter on a PWM line, two drivers on a chip select | a part's own input current or capacitance (not in the netlist), a symbol whose pin type is wrong |
| `eeprom.*` | N | one M24C02-class EEPROM, SDA/SCL on pins 30/29, E2–E0 on GND (address computed), VCC on +3V3, a decoupling capacitor, WC held (resistor + jumper, GND, or a G-line; FAIL if floating or tied high) | a missing or second EEPROM, a wrong address, an EEPROM on +5V (its VIH of 0.7 VCC would sit above the 3.3 V pull-ups) | a different EEPROM part or footprint, the capacitor's placement |
| `i2c.pullups`, `pullups`, `irq_n`, `irq_n.drive`, `miso.drive` | N | no pull-up from a slot signal to anything but +3V3 (FAIL); SDA/SCL pull-ups on the coupon (WARN, the slot has 4.7 k); IRQ_N has a fitted pull-up on the coupon; the parts driving IRQ_N have open-collector pins and those driving MISO tri-state pins, by their symbols' electrical types (WARN otherwise) | a pull-up to +5V or a local rail (one named without a "+" and with no power-output pin is missed), a missing IRQ_N pull-up, a push-pull output on IRQ_N or MISO | a symbol whose pin type is wrong; whether a tri-state MISO really turns off with the coupon's selects high (SPEC §4.9) |
| `lanes.*` | N, D | each connected lane is declared and driven by a fitted part on the coupon (a lane only a DNP part reaches is open: INFO, and not "used"); a two-pin diode from INJ (the rig's stimulus, idle low or open at JP_INJ*n*) counts as open, so the test coupon's D7 path (D11 + R40 into AN0) leaves the idle lane's R_src and ratio checkable; R_src declared (WARN above DS13543's 1 kΩ, with the per-step settling time); for a lane only resistors drive, R_src recomputed from the netlist (Thevenin, every rail and GND as AC ground: FAIL if declared more than 3 % stiffer, WARN if more than 10 % softer) and its open-circuit ratio to +3V3 against `ext.reference_ratios` (FAIL outside the declared tolerance); for a lane an active part drives, a **lower bound** of R_src from the coupon's own resistors (every net an active pin touches taken as 0 Ω: FAIL if the declaration is below it); the lane's load, the motherboard's 1 nF plus the coupon's capacitors, against the declared CLoad (FAIL if the coupon's own exceed it, WARN if the 1 nF takes it to or over the rating, INFO if no CLoad is declared) | an open lane, a lane only a capacitor or a DNP part sits on, an undeclared lane, a stale R_src or reference ratio after a resistor change, an R_src declared below the series resistor behind a sensor or buffer, coupon capacitors over CLoad | a sensor's or buffer's own output impedance (only declared), its stability into the 1 nF, the capacitance of sensor outputs, a mux and traces |
| `uses`, `rails.+5V`, `rails.+3V3` | N, D | the descriptor's `uses` equals the connected pins (a pin whose only part is DNP counts as open); nothing fitted on +5V unless +5V current is declared | a +5V load with no budget, a declared pin left open | what a part actually draws |
| `budget.*` | D | each rail's `max_ma` within SPEC §4.9's rule and below `nets.SWITCH_TRIP`'s minimum in every allowed slot; typ ≤ max; which USB-C source the coupon needs | an over-budget declaration, 5 V above 500 mA outside S5 | whether the declaration is true (only a measurement can say) |
| `bulk.*` | N, D | the fitted capacitors on each rail at the header (values parsed) against SPEC §4.9 and the declaration; DNP ones as "if fitted" (WARN) | 47 µF + 10 µF on +3V3 | capacitance behind a resistor, a ferrite or a local regulator, or a value the parser cannot read (reported) |
| `post.*`, `keepouts` | B | the Ø3.2 mm hole at `coupon_common.POST`, no copper within r 3.0 mm on any layer (tracks, vias, pads, zone fills), no courtyard within r 3.5 mm; `coupon_common.keepouts()`: the header tails on top, the post, the bottom side | a moved or missing post, a pour or track at the post, a part on the bottom | part heights (SPEC §9's 2 mm bottom-side limit is enforced as no bottom part at all) |
| `slots`, `needs`, `i2c.*`, `spi`, `glines`, `devices.*` | D, N | slots compatible with the size and `needs` (`descriptor.SLOT_CAPS`); `needs` implied by the declared roles (PWM, TIM1, BKIN, 5 V current, 14-bit lanes); I2C addresses (not 0x70, not 0x50, no duplicate); SPI selects and roles agree; parts on SDA and SCK against the declared devices (WARN) | a PWM coupon allowed in S1, an I2C part at the mux's address, an SPI device on an unused select | a level shifter counted as a device (hence WARN) |
| `routed` | B | pcbnew's unrouted count (WARN) | an unrouted board | anything DRC checks: `layout.py` runs DRC |
| `release.*` | N, B, D | `--release` only: the descriptor is not a placeholder, the netlist and board exist, nothing is unrouted (FAIL otherwise) | a board about to be ordered with a placeholder descriptor or half routed | DRC, BoM and placement files (`release.py`'s gates) |
| `fleet.*` | D | `--all` only: the five default coupons (S1–S5) together, their +3V3 against the slot LDO's 300 mA and their sum against each USB-C source's VSYS budget (WARN, INFO; never a FAIL) | a set of declarations the firmware could not power at once | whether any of them is true |

DNP: a part KiCad marks "do not populate" (the netlist's `dnp` property) is in the nets but not on the assembled
board. The EEPROM, the WC resistor, the IRQ_N pull-up, lane sources, `uses`, +5V loads and bulk capacitance count
only fitted parts; a DNP pull-up to another rail is a WARN (fitting it would break SPEC §4.9).

The numbers and their sources are at the top of `rules.py`. The slot geometry is read from
`keyboard/hardware/design/boards/coupon_common.py`, the same module the motherboard's sockets are placed with, so a
coupon is checked against what it mates with; the slot pinout and trip points come from `nets.py`.

## What the tests prove

`tests/` (163 tests, 4 of them slow; on 2026-11-28: 159 passed and 4 expected failures, the coil and haptics boards generated before the key, each named; an A1 coupon, the test or Hall coupon, is never an expected failure):

* **Rules** on synthetic coupons (`tests/coupon_fixtures.py`: a KiCad-format netlist and a pcbnew-built board): a good
  coupon passes every rule, and fixtures with one thing wrong each fail theirs: wrong outline, header moved,
  rotated or on top, wrong pin, swapped I2C pins, missing EEPROM, two EEPROMs, missing PRESENT_N strap (and one
  through a 0 Ω resistor), a net on the key pin 39, the stock 40-pin header (symbol and footprint) and a header
  without pin 2, an open GND pin, over-budget current, 5 V drawn but undeclared, a split rail,
  wrong EEPROM straps or supply, every write-control case, missing IRQ_N pull-up, pull-ups to +5V, shorts, a lane
  with no source, a declared R_src that the netlist's resistors contradict, an R_src declared below the series
  resistor behind an active source, a reference ratio the ladder contradicts, too much bulk or lane capacitance
  (the coupon's own, and with the motherboard's 1 nF), DNP parts (an EEPROM, a pull-up, a WC resistor, a lane source,
  a bulk capacitor), I2C address clashes, needs implied by PWM roles, a turned coupon that the key stops (and one
  without pin 2 that it does not stop), the three offsets the key blocks, a one-column misinsertion that reads
  present, a strong load, a capacitor or a second driver on a slot line behind the 100 Ω, a used G-line with no pull
  on the coupon (it floats while the firmware reads the descriptor), a diode from INJ into a
  lane (open while the lane idles) against one from +3V3 (not), a `uses` bit for pin 39 or beyond the slot pins, the post hole moved or missing, copper or a part at
  the post, a bottom-side part, no ground plane, the release gate, the fleet sums; and the CLI's exit codes. Each new
  rule's tests were checked to fail with the rule reverted in memory.
* **Real boards** (`tests/test_real_boards.py`): faults injected into copies of the generated test, Hall and haptics
  coupons, each caught by its rule: PRESENT_N strap removed, EEPROM address strap, WC tied high, a ladder resistor
  changed, a lane capacitor over CLoad, the header moved 0.1 mm on the board, an over-budget declaration, haptics'
  R_src declared below its 330 Ω, a Hall lane behind a DNP part declared used, a pad 39 put back on the test
  coupon's J1, J1 pin 39 put on GND in the Hall coupon's netlist, 220 Ω from G0 to GND behind the 100 Ω; and the
  test coupon's D11 counted as open while INJ idles. On the generated boards themselves it requires no FAIL, and the
  A1 coupons (the owner's decision D1 of 2026-11-27: the test and Hall coupons, `coupon_fixtures.A1_COUPONS`) must be
  generated. Only an A2 board may be an expected failure that names itself: one generated before the key, whose J1
  still has pin 39 (today the coil and haptics coupons), or one whose descriptor is still a placeholder. An A1 coupon
  rebuilt with pin 39, or failing any other rule, fails the suite (checked by running the tests on a copy of the
  boards with the test coupon's J1 given a pin 39 again), and `descriptors/<board>.json` must agree with the design's own
  `DESCRIPTOR_FACTS`
  (`sheets/test_coupon.py`, `coupon_hall.py`, `coupon_haptics.py`: lanes, R_src, CLoad, G-lines, bulk, I2C
  addresses, SPI modes, the S5 restriction).
* **Descriptor**: every offset frozen; a golden image checked byte by byte; round trips of every shipped descriptor;
  CRC corruption at seven offsets; blank, foreign, short, other-version, bad-length, non-zero-reserved and
  unknown-enum images refused; a newer minor accepted, with enum values this reader does not know; the firmware
  lib's `PCKD` image named; JSON errors listed together; `USES` and `SLOT_CAPS` against `nets.py`; no `uses` bit for
  pin 39 (the key) and a same-minor image with a `uses` bit beyond the slot pins refused; the header and
  DESCRIPTOR.md's tables up to date.
* **C header**: compiled with `gcc -Wall -Wextra -Wpedantic -Werror` and linked with Zephyr v4.5.0's own
  `subsys/crc/crc32_sw.c`; a C reader of `struct coupon_desc` prints every field of eight images (good, the test
  coupon's, and six broken ones), which must equal Python's view; `sizeof` and `offsetof` of all 187 leaf fields
  (every array element and sub-struct member), compiled by the host gcc and by arm-none-eabi-gcc for Cortex-M33 (read
  back from the object file), equal the byte positions the encoder packs them at (Python's `struct.calcsize`), and a
  header with two fields swapped fails that comparison.
* **Zephyr on native_sim** (`tests/zephyr/`, slow): the test coupon's image written through Zephyr's `eeprom_at2x`
  driver into its AT24 emulator (which starts blank and is reported so), read back and validated with
  `crc32_ieee()`; a one-byte corruption caught; an unaligned write split at pages; the 16 lines `make_eeprom.py
  --shell` writes, run through Zephyr's own `eeprom` shell into the emulator, leaving a valid image, and a 17-byte
  line refused (16 bytes is exactly the shell's 20-argument limit); the TCA9548A with five EEPROMs at 0x50 behind
  it: all ready with nothing on the bus, their names, a read failing with nothing answering; and the mux not
  building with Zephyr's default init priorities (see DESCRIPTOR.md, "Reading"). Each `zephyr.exe` runs in its
  build directory (native_sim's simulated flash EEPROM writes `eeprom.bin` into the working directory).

They do not prove that an M24C02 behaves like the emulator (write time, page roll-over), that the TCA9548A routes
as the driver expects (no emulator: the "absent coupon" read fails at the mux select, not at an EEPROM's NAK), that
any declared current, impedance or capacitance is true, or that a coupon works.

## Adding a coupon

1. The hardware workflow adds its sheet and board modules and generates it (`build.py`, `layout.py`), with J1 from
   `sheets/coupon_common.py` and `boards/coupon_common.py`: the keyed header, no pin and no pad 39 (D2 of
   2026-11-27; `rules.py`'s `key` and `key.pcb`).
2. Write `descriptors/<board>.json` from the captured design: `uses` from its header pins, currents from its parts'
   datasheets (marked estimates until measured), each lane's R_src and CLoad, its devices. Remove `"placeholder"`.
3. Add the board to `test_descriptor_matches_its_design` in `tests/test_rules.py` if its sheet has
   `DESCRIPTOR_FACTS`.
4. `rules.py <board> --release`: no FAIL. Then `make_eeprom.py <board> --no-placeholder --serial N`.
