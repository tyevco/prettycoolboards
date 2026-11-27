# Coupon descriptor, format 1.0

> **Status (2026-11-27): a format designed on paper.** No coupon EEPROM has been written or read, and no coupon has
> been built. **A second, incompatible proposal exists** for the same EEPROM: `keyboard/firmware/lib/include/tb/desc.h`
> (magic `PCKD`, a 24-byte header, TLV records, CRC-16/CCITT-FALSE), with its own encoder. Firmware built on one
> refuses the other's images (`descriptor.py` names a `PCKD` image when it sees one). SPEC §11 #18 asks for one
> format: the owner has to pick, and the other side changes. The encoder, the decoder, the C header and the firmware-side check are tested against each other on
> the host, and through Zephyr v4.5.0's real `eeprom_at2x` driver with its EEPROM emulator on `native_sim`
> ([README.md](README.md#what-the-tests-prove)). That proves the code and the arithmetic, not an M24C02 on a coupon.

Every rev A coupon carries a 2 kbit descriptor EEPROM at 0x50 on its slot's own I2C channel
([SPEC §4.6](../../hardware/design/SPEC.md#_4-6-slot-identity)). The firmware powers the slot's +3V3, reads the
descriptor, and only then decides whether and how to use the coupon
([SPEC §8.4](../../hardware/design/SPEC.md#_8-4-board-services-and-the-coupon-driver-model)). This file is the format
SPEC §11 #18 asked compiler v0 to define. `descriptor.py` is its single source: the encoder, the decoder, the C
header `coupon_desc.h` and the tables at the end of this file are all generated from its `LAYOUT`, and
`tests/test_descriptor.py` freezes every offset.

## The EEPROM

ST M24C02-WMN6TP (LCSC C7562, the SPEC's candidate), read in ST's datasheet DocID024020 Rev 2 (September 2013,
the copy LCSC hosts):

| Fact | Datasheet | What the format and the firmware do with it |
|---|---|---|
| 2 Kbit, 256 bytes, one device address | Features: "2 Kbit (256 bytes) of EEPROM" | The descriptor is exactly 256 bytes, read in one sequential read from offset 0 |
| Address 1010 E2 E1 E0 | E2–E0 to GND: 0x50 (SPEC §4.9) | `rules.py` checks the straps from the netlist |
| "Page size: 16 bytes"; a page write past the page end rolls over to its start (§5.1.2) | | Writers send 16-byte, 16-aligned pages (Zephyr's driver splits at pages; `make_eeprom.py --shell` emits one page per command) |
| "Page Write within 5 ms" (tW max) | Features, AC tables | `timeout = <5>` in devicetree; the EEPROM NAKs while busy, so writers poll on ACK (§5.1.3) |
| WC high: "device select and address bytes are acknowledged, Data bytes are not acknowledged"; WC low or floating: writable (§2.4) | | A write to a protected coupon fails on a data NAK; `rules.py` requires WC to be held (§4.9's "WP handled") |
| Reads do not depend on WC (§5.2) | | Write-protected coupons are read normally |
| "delivered with all the memory array bits set to 1 (each byte contains FFh)" (§6) | | All-0xFF is reported as **blank**, not as a corrupt descriptor |
| VCC must stay valid "until the completion of the internal write cycle (tW)" (§2.6.1); rise no faster than 1 V/µs (§2.6.2) | | The firmware never turns a slot's +3V3 off within tW of a write (below); the slot switch's soft start is far slower than 1 V/µs |
| Read 1 mA max at 400 kHz, write 0.5 mA max during tW, standby 2 µA max at 2.5 V (DC tables) | | Negligible against a slot's budget |
| E2–E0: "When not connected (left floating), these inputs are read as low (0)" (§2.3); VIH 0.7 VCC (DC tables) | | Floating straps would still give 0x50, but SPEC §4.9 says tie them to GND and `rules.py` fails anything else |

## Design choices

* **A fixed layout, not a list of tagged records.** 256 bytes hold everything the firmware needs to decide whether a
  coupon may be powered and how to drive it, at fixed offsets a C struct can map. There is no parser to get wrong.
  Extensions go into reserved bytes (a minor version) or a new major version.
* **What it holds:** identity (type, revision, serial, the git commit of the board's generated files), where it may
  be plugged (size, slots, the slot features it needs), what it connects (`uses`, one bit per slot pin group), what
  it draws (per rail: typical, maximum, bulk capacitance, start-up time), what each lane carries and how to scale it,
  what each G-line and chip select does, its devices (bus, address or select, count, interrupt, SPI mode), and a
  32-byte type-specific block.
* **What it does not hold:** per-key maps beyond 8 × 4 sites, per-site calibration, and long text. Those belong to
  the firmware's coupon driver (keyed by type and revision) or to the host's records (keyed by serial). If a later
  coupon needs more on board, the path is a larger EEPROM with 16-bit addressing (a new major format), since an
  M24C04–M24C16 would take extra I2C addresses (0x51–0x57) on the coupon's channel.
* **The budget is `max_ma`.** The firmware reserves each rail's `max_ma` against the VSYS and slot-LDO budgets
  (SPEC §3.2) before it enables the rail, and sets the rail's INA226 alert there (SPEC §3.4). `typ_ma` is for the
  battery gate's expectations and the logs, never for admission.
* **Little-endian, packed, IEEE 754 binary32.** The STM32U5A5 is little-endian; `coupon_desc.h` refuses a big-endian
  build and asserts every offset at compile time.

## Versions and integrity

* `fmt_major` 1: a reader refuses any other major version (the layout may have moved). `fmt_minor` 0: a reader
  accepts a higher minor and ignores what it does not know; additions use reserved bytes only, which a minor-0
  writer leaves zero and a minor-0 reader in strict mode requires to be zero (`descriptor.decode(strict=True)`). A
  newer minor may also use enum values this reader does not know (a new part, a new lane kind): they decode as
  `unknown(N)`, while in an image of this reader's own minor they are an error.
* `length` is 256 for format 1. The CRC covers bytes 0 to `length` − 5 and sits in the last four bytes.
* **CRC-32/IEEE**: reflected polynomial 0xEDB88320, initial value and final XOR 0xFFFFFFFF, check value
  `crc32("123456789") = 0xCBF43926`. That is Python's `zlib.crc32` and Zephyr v4.5.0's `crc32_ieee()`
  (`subsys/crc/crc32_sw.c`), which `tests/test_c_header.py` compiles and runs against the Python encoder. In Zephyr
  v4.5.0 the CRC library is `subsys/crc` and needs `CONFIG_CRC=y`. A board that enables the STM32 CRC peripheral
  (`zephyr,crc` is chosen in `stm32u5.dtsi`, with the node disabled by default) gets `crc_hardware.c`'s version
  instead, which XORs the result for CRC32_IEEE in `drivers/crc/crc_stm32.c`; that path is not tested here.
* An enum value is never reused or renumbered. New names (a new part, a new lane kind) are a minor bump.

## Field meanings

The generated tables below give every byte. What the less obvious fields mean:

* **`slot_mask`, `default_slot`, `size_class`, `needs`.** A coupon fits a slot of its size or larger (SPEC §2: S1–S3
  standard, S4–S5 wide) that offers every bit of `needs` (`descriptor.SLOT_CAPS`, checked against `nets.py` by the
  tests): `pwm_g0_g3` (TIM8 on S4, TIM1 on S5), `tim1` and `bkin_on_irq` and `fast_g4_g5` and `high_current_5v`
  (S5 only), `lanes_14bit` (not S5, whose AN1–AN3 are on the 12-bit ADC4). `exercises_current_limit` says that some
  G-line deliberately switches a load above the coupon rules, to test the slot switch (the test coupon).
  `slot_mask` must be a subset of the compatible slots; the firmware refuses the coupon in any other slot.
* **`uses`.** One bit per slot pin group, in `descriptor.USES` order: the two rails, then every slot signal but
  PRESENT_N (always strapped). `rules.py` requires it to equal the header pins the netlist connects. The firmware
  powers +5V_S*n* only if bit 1 is set and drives only the lines listed.
* **Rails** (`rails[0]` +3V3, `rails[1]` +5V): `max_ma` is the budget, within SPEC §4.9's rule and below the switch's
  minimum trip in every allowed slot; `bulk_uf_x10` is the capacitance at the header, within 47 µF (+3V3), 100 µF
  (+5V) or 470 µF (+5V on S5); `startup_ms` is how long after the rail is up the coupon's parts become usable (the
  descriptor EEPROM itself needs none beyond a stable VCC).
* **Lanes.** `value = (code / full_scale − offset) × gain`, in `unit`, where `code / full_scale` is the fraction of
  VDDA (ratiometric lanes, `flags.ratiometric`, follow the slot's +3V3, SPEC §3.1). `sites` is how many sensors the
  lane reads over the select steps. `r_src_ohm` is the coupon-side source impedance (0xFFFF: not known), which sets
  the settling per select step, (R_src + 47 Ω) × 1 nF × ln 2^15 (SPEC §4.9); `cload_max_pf` is the smallest rated
  load capacitance of the lane's sources (0: no limit stated). `adc4_ok` says the lane is usable at 12 bits.
* **Select.** `select_scheme` says how the G-lines pick what the lanes read: `binary` (G-lines with role `sel` carry
  the step number, bit `arg`, and `sel_en` enables), `one_hot`, `addr_strap` (G-lines with role `addr` hold one
  device of an address-selected group at the low address: the coil coupon's LDC1614s, SPEC §4.5), `chip_select`.
* **G-lines** `role` / `arg`: `sel` bit number; `cs` and `enable` the device index; `addr` the unit within the
  address-selected device entry; `pwm_high` / `pwm_low` the phase (0–2); `load` the load number. Flags: `fast` (must
  be a direct MCU pin: G4/G5 are slow expander lines on S1–S4), `pwm` (needs a timer), `exceeds_rule` (a deliberate
  over-rule load), `not_on_s5` (never driven on S5, whose 2 A breaker would not limit it).
* **Chip selects** `cs[0]` CS0_N, `cs[1]` CS1_N: `spi_cs` (with the device it selects), `strobe` (a GPIO pulse, the
  test coupon's parallel load), `enable`.
* **Devices** (up to 7; the descriptor EEPROM is implied, never listed): `addr` is the 7-bit I2C address, or for SPI
  the select line (0 CS0_N, 1 CS1_N, 2–7 G0–G5), or for analog parts a lane mask. `count` identical parts share the
  entry (address-selected converters, or the sensors on the lanes). `irq`: `irq_n` (open drain on IRQ_N) or `bkin`
  (IRQ_N as S5's TIM1 break input, SPEC §5.3). `spi_mode` is per device, since one coupon may mix modes.
* **`ext`** (32 bytes, `ext_format`): `reference_ratios` holds four float32 expected lane ratios and four float32
  tolerances (the test coupon's ladder: 0.2, 0.4, 0.6, 0.8 × +3V3); `site_map` holds one 4-bit site kind per (step,
  lane), step *s* lane *l* at nibble 4*s* + *l*, low nibble first, for up to 8 steps × 4 lanes (16 bytes; the rest
  zero). `ext_flags.measured` marks values measured on the bench rather than designed.
* **`flags`**: `placeholder` (the values are not from a captured design: images of the not-yet-designed coupons carry
  it, and the firmware should say so), `git_dirty` (the board's files had uncommitted changes when the image was made,
  or none were committed yet).

## Reading (firmware)

In SPEC §8.4's order, once the host has configured the device and PRESENT_N reads low:

1. Reserve the coupon rule's 250 mA on the slot LDO and VSYS budgets: the coupon's real draw is not known until the
   descriptor is read. Power +3V3_S*n*, wait for the rail (its INA226 bus voltage, or the switch's turn-on time plus
   a margin), then select the slot's mux channel.
2. Read 256 bytes from offset 0 in one sequential read (the M24C02 auto-increments, DocID024020 §5.2).
3. `coupon_desc_validate()`: size, blank (all 0xFF: an unprogrammed coupon), magic, major version, length, CRC, in
   that order. On a CRC failure, read once more before refusing (a disturbed read is more likely than a corrupt
   EEPROM). Any failure: deselect, turn +3V3_S*n* off, release the reservation, and report the slot as "unknown
   coupon" (blank: "unprogrammed").
4. `memcpy` into `struct coupon_desc`. Refuse the coupon if this slot is not in `slot_mask`, if a `needs` bit is not
   in this slot's capabilities, or if `rails[].max_ma` does not fit what is left of the budgets; replace the 250 mA
   reservation with `rails[0].max_ma`.
5. Pick the coupon driver for `coupon_type` / `coupon_rev`; power +5V_S*n* only if `uses` has it; then the bus
   switch, as SPEC §3.5 orders. Log type, revision, serial and git with every battery-gate record (SPEC §8.5).

Zephyr v4.5.0 specifics, each checked in the v4.5.0 tree on 2026-11-27 (and the last three built and run on
`native_sim`, `tests/zephyr/`):

* One `atmel,at24` node per slot channel of the `ti,tca9548a` node:
  `compatible = "st,m24c02", "atmel,at24"; reg = <0x50>; size = <256>; pagesize = <16>; address-width = <8>;
  timeout = <5>;` (`dts/bindings/mtd/atmel,at24.yaml`, `atmel,at2x-base.yaml`).
* `eeprom_at2x_init()` only checks that the parent bus is ready (and configures `wp-gpios` if given); it never talks
  to the chip, so the five EEPROM devices are ready at boot with every slot unpowered. Built and run: all five ready
  with nothing on the bus.
* `eeprom_at24_read()` and `_write()` retry a NAK every millisecond until `timeout` ms have passed, then return the
  error. An absent, unpowered or busy coupon therefore costs at least `timeout` (5 ms) per call: on `native_sim`,
  whose tick is 10 ms, a read with nothing answering returned -EIO (-5) after 20 ms. (There is no TCA9548A emulator,
  so in that test the mux's own select write fails and the AT24 driver retries it; a real mux with an absent
  coupon fails at the EEPROM's NAK instead, under the same retry loop.) A write to a write-protected coupon fails
  the same way: WC high NAKs the data bytes, and the driver retries until `timeout`.
* **The TCA954x driver does not build with Zephyr's default init priorities.** `i2c_tca954x.c` has
  `BUILD_ASSERT(CONFIG_I2C_TCA954X_CHANNEL_INIT_PRIO > CONFIG_I2C_TCA954X_ROOT_INIT_PRIO, "I2C multiplexer channels must
  be initialized after their root")`, and both default to `I2C_INIT_PRIORITY` (50). Built on `native_sim`: it fails
  with that message, and builds with `CONFIG_I2C_TCA954X_ROOT_INIT_PRIO=51` and
  `CONFIG_I2C_TCA954X_CHANNEL_INIT_PRIO=52` (both still below `CONFIG_EEPROM_AT2X_INIT_PRIORITY`, 80).
* **Device names.** `DEVICE_DT_NAME()` is the node's `label` property if it has one, else its full name. Five EEPROM
  nodes `eeprom@50` share that name, and `device_get_binding()` (which the `eeprom` shell uses) returns the first
  device with a matching name, so only one of them can be reached by name. Built and run: an unlabelled node is
  named `eeprom@50`, and labelled ones (`label = "coupon-s2";` and so on) are found by their labels. The firmware's
  own code uses `DEVICE_DT_GET(DT_NODELABEL(...))` and is not affected; the shell and any name lookup are.
* The TCA954x driver caches the selected channel and skips the select write when it has not changed
  (`tca954x_set_channel()`). If the board service resets or reprograms the mux behind the driver's back (MUX_RST_N,
  SPEC §8.4), that cache is stale; `i2c-mux-idle-disconnect` makes every transfer select and then deselect, which
  keeps the hardware and the cache at "none" between transfers.

## Writing (bench)

* `make_eeprom.py` makes the image from `descriptors/<board>.json`, with the serial and the git commit of the board's
  KiCad and fab files (`.bin`, `.hex`, and with `--shell DEVICE` Zephyr `eeprom write` commands of one
  16-byte page each). Each line is `eeprom write DEVICE OFFSET` and 16 bytes, 20 tokens: exactly the shell's default
  `CONFIG_SHELL_ARGC_MAX` of 20, with no headroom (run on `native_sim` through Zephyr v4.5.0's own eeprom shell: all
  16 lines accepted and the image valid; a 17-byte line refused). DEVICE is the EEPROM's device name, so the slot's
  node needs a `label` (below). It refuses a descriptor that breaks the coupon rules (the netlist and board rules
  too when the board is generated: a descriptor its board contradicts), and with `--no-placeholder` one marked
  placeholder.
* Open the coupon's write-protect jumper (the test coupon's JP1), write, read back and compare (the Zephyr shell's
  `eeprom write` verifies by itself), then bridge the jumper.
* Keep the slot's +3V3 on for at least tW (5 ms) after the last page: VCC must stay valid until the write cycle ends
  (DocID024020 §2.6.1). Zephyr's driver returns from `eeprom_write()` before the cycle ends; its next access polls.
* An external programmer (a CH341A-class clip on the SOIC-8) takes the `.hex` or `.bin` with the coupon unplugged.
* In place, an unprogrammed (blank) coupon needs its +3V3 on while the console writes it, so the firmware's
  programming command (a proposal: none exists yet) powers +3V3_S*n* alone, under the 250 mA reservation of
  "Reading" step 1, never +5V_S*n*, and keeps every other line of the slot low.

## JSON form

`descriptors/<board>.json` is the human form, one per coupon board. `descriptor.py decode` returns the canonical
form (what the image carries). Enum and bit names are the strings in the tables below; `rails` and `lanes`, `glines`
and `cs` are objects keyed by `+3V3`/`+5V`, `AN0`–`AN3`, `G0`–`G5`, `CS0_N`/`CS1_N`; devices take `addr` as `"0x5A"`
(I2C), a select name such as `"CS0_N"` (SPI) or a list of lanes (analog). These keys are kept in the JSON and never
encoded: `board`, `notes`, `placeholder_fields`, `source`, and `ref`, `name`, `note` on any entry, and any key that
starts with `_`. `"placeholder": true` sets the placeholder flag. `"git": "auto"` is resolved by `make_eeprom.py`.
Any other unknown key is an error, so a typo is caught.

## Tables

<!-- layout:begin -->
<!-- generated by descriptor.py doc: do not edit by hand -->

**Top level** (`struct coupon_desc`, 256 bytes)

| Offset | Size | Type | Field | Meaning |
|---|---|---|---|---|
| 0x00 | 4 | `char[4]` | `magic` | "PCKC" |
| 0x04 | 1 | `uint8_t` | `fmt_major` | format major version (1): a reader refuses any other |
| 0x05 | 1 | `uint8_t` | `fmt_minor` | format minor version (0): a reader accepts a newer one |
| 0x06 | 2 | `uint16_t` | `length` | bytes in the descriptor, CRC included (256) |
| 0x08 | 1 | `uint8_t` | `coupon_type` | enum coupon_type |
| 0x09 | 1 | `uint8_t` | `coupon_rev` | board revision, ASCII 'A'-'Z' |
| 0x0A | 1 | `uint8_t` | `size_class` | enum coupon_size |
| 0x0B | 1 | `uint8_t` | `default_slot` | the slot it is designed for, 1-5 (SPEC §2) |
| 0x0C | 1 | `uint8_t` | `slot_mask` | bit n-1 set: the coupon may be used in slot n |
| 0x0D | 1 | `uint8_t` | `flags` | COUPON_FLAG_* bits |
| 0x0E | 2 | `uint16_t` | `needs` | COUPON_NEEDS_* bits: slot features beyond the common pinout |
| 0x10 | 4 | `uint32_t` | `serial` | serial number of this coupon (0 = not assigned) |
| 0x14 | 4 | `uint32_t` | `date` | the descriptor's date, yyyymmdd as a decimal number (the JSON's, or make_eeprom.py --today) |
| 0x18 | 8 | `uint8_t[8]` | `git_hash` | first 8 bytes of the git commit of the board's generated files |
| 0x20 | 4 | `uint32_t` | `uses` | COUPON_USES_* bits: the slot pins the coupon connects |
| 0x24 | 2 | `uint16_t` | `spi_max_khz` | highest SPI clock all of its SPI devices accept, kHz (0: no SPI) |
| 0x26 | 2 | `uint16_t` | `i2c_max_khz` | highest I2C clock its I2C devices accept, kHz (the descriptor EEPROM: 400) |
| 0x28 | 1 | `uint8_t` | `select_scheme` | enum coupon_select: how the G-lines pick the site a lane reads |
| 0x29 | 1 | `uint8_t` | `select_steps` | select steps per scan frame (0: none) |
| 0x2A | 2 | `uint16_t` | `select_settle_ns` | time from a select change to a settled lane, ns, coupon side only |
| 0x2C | 4 | `uint32_t` | `reserved0` | 0 |
| 0x30 | 16 | `struct coupon_desc_rail[2]` | `rails` | [0] +3V3, [1] +5V (8 bytes each) |
| 0x40 | 64 | `struct coupon_desc_lane[4]` | `lanes` | AN0-AN3 (16 bytes each) |
| 0x80 | 24 | `struct coupon_desc_gline[6]` | `glines` | G0-G5 (4 bytes each) |
| 0x98 | 8 | `struct coupon_desc_cs[2]` | `cs` | CS0_N, CS1_N (4 bytes each) |
| 0xA0 | 56 | `struct coupon_desc_device[7]` | `devices` | up to 7 devices (8 bytes each) |
| 0xD8 | 1 | `uint8_t` | `ext_format` | enum coupon_ext: what ext[] holds |
| 0xD9 | 1 | `uint8_t` | `ext_flags` | COUPON_EXT_F_* bits |
| 0xDA | 2 | `uint16_t` | `ext_reserved` | 0 |
| 0xDC | 32 | `uint8_t[32]` | `ext` | type-specific block (reference ratios, site map) |
| 0xFC | 4 | `uint32_t` | `crc32` | CRC-32/IEEE of bytes 0x00-0xFB |

**`struct coupon_desc_rail`** (8 bytes; one per rail: [0] +3V3, [1] +5V)

| Offset | Size | Type | Field | Meaning |
|---|---|---|---|---|
| +0 | 2 | `uint16_t` | `typ_ma` | typical (mean) current the coupon draws from this rail, mA |
| +2 | 2 | `uint16_t` | `max_ma` | the most it ever draws, mA: the budget the firmware reserves (SPEC §3.2) |
| +4 | 2 | `uint16_t` | `bulk_uf_x10` | bulk capacitance on the rail at the header, in 0.1 uF (SPEC §4.9) |
| +6 | 1 | `uint8_t` | `startup_ms` | time after the rail is up before the coupon's parts are ready, ms |
| +7 | 1 | `uint8_t` | `reserved` | 0 |

**`struct coupon_desc_lane`** (16 bytes; one per analog lane AN0-AN3)

| Offset | Size | Type | Field | Meaning |
|---|---|---|---|---|
| +0 | 1 | `uint8_t` | `kind` | lane kind (enum coupon_lane_kind); 0 = not connected |
| +1 | 1 | `uint8_t` | `flags` | COUPON_LANE_F_* bits |
| +2 | 1 | `uint8_t` | `sites` | sensors or sites read on this lane (one per select step) |
| +3 | 1 | `uint8_t` | `unit` | physical unit of `value` (enum coupon_unit) |
| +4 | 2 | `uint16_t` | `r_src_ohm` | source impedance seen by the lane, ohm, the coupon side only (SPEC §4.9); 0xFFFF = not known |
| +6 | 2 | `uint16_t` | `cload_max_pf` | smallest rated load capacitance of the sources on the lane, pF; 0 = no limit |
| +8 | 4 | `float` | `offset` | scaling: value = (code / full scale - offset) * gain (ratiometric: a fraction of VDDA) |
| +12 | 4 | `float` | `gain` | scaling gain, unit per full scale |

**`struct coupon_desc_gline`** (4 bytes; one per G-line G0-G5)

| Offset | Size | Type | Field | Meaning |
|---|---|---|---|---|
| +0 | 1 | `uint8_t` | `role` | enum coupon_gline_role |
| +1 | 1 | `uint8_t` | `arg` | role argument: select bit, device index, PWM phase or load number |
| +2 | 1 | `uint8_t` | `flags` | COUPON_GLINE_F_* bits |
| +3 | 1 | `uint8_t` | `reserved` | 0 |

**`struct coupon_desc_cs`** (4 bytes; [0] CS0_N, [1] CS1_N)

| Offset | Size | Type | Field | Meaning |
|---|---|---|---|---|
| +0 | 1 | `uint8_t` | `role` | enum coupon_cs_role |
| +1 | 1 | `uint8_t` | `device` | index into devices[], 0xFF = none |
| +2 | 1 | `uint8_t` | `flags` | COUPON_CS_F_* bits |
| +3 | 1 | `uint8_t` | `reserved` | 0 |

**`struct coupon_desc_device`** (8 bytes; the coupon's devices other than the descriptor EEPROM)

| Offset | Size | Type | Field | Meaning |
|---|---|---|---|---|
| +0 | 2 | `uint16_t` | `part` | enum coupon_part; 0 = empty entry |
| +2 | 1 | `uint8_t` | `bus` | enum coupon_bus |
| +3 | 1 | `uint8_t` | `addr` | I2C: 7-bit address; SPI: select line (0 CS0_N, 1 CS1_N, 2-7 G0-G5); analog: lane mask |
| +4 | 1 | `uint8_t` | `count` | identical devices behind this entry (address-selected, or sensors on lanes) |
| +5 | 1 | `uint8_t` | `irq` | enum coupon_irq |
| +6 | 1 | `uint8_t` | `flags` | COUPON_DEV_F_* bits |
| +7 | 1 | `uint8_t` | `spi_mode` | SPI mode 0-3 (CPOL, CPHA) for an SPI device; 0 otherwise |

**Enumerations** (JSON name = value)

| Field | Values |
|---|---|
| `coupon_type` | `test` = 1, `hall` = 2, `tmr` = 3, `shear` = 4, `coil` = 5, `haptics` = 6, `kvm` = 7 |
| `size_class` | `standard` = 0, `wide` = 1 |
| `select_scheme` | `none` = 0, `binary` = 1, `one_hot` = 2, `addr_strap` = 3, `chip_select` = 4 |
| `lanes[].kind` | `unused` = 0, `hall` = 1, `tmr` = 2, `reference` = 3, `thermistor` = 4, `current` = 5, `angle` = 6, `voltage` = 7 |
| `lanes[].unit` | `ratio` = 0, `mT` = 1, `degC` = 2, `A` = 3, `deg` = 4, `V` = 5, `ohm` = 6 |
| `glines[].role` | `unused` = 0, `sel` = 1, `sel_en` = 2, `cs` = 3, `addr` = 4, `pwm_high` = 5, `pwm_low` = 6, `enable` = 7, `load` = 8, `led` = 9, `irq_test` = 0xA, `input` = 0xB |
| `cs[].role` | `unused` = 0, `spi_cs` = 1, `strobe` = 2, `enable` = 3 |
| `devices[].bus` | `none` = 0, `i2c` = 1, `spi` = 2, `analog` = 3, `gpio` = 4 |
| `devices[].irq` | `none` = 0, `irq_n` = 1, `bkin` = 2 |
| `devices[].part` | `m24c02` = 1, `tmag5253` = 0x10, `tmag5170` = 0x11, `tmr_sensor` = 0x12, `ntc` = 0x13, `analog_mux` = 0x14, `ldc1614` = 0x20, `drv8316` = 0x30, `mt6701` = 0x31, `drv2605l` = 0x32, `touch_controller` = 0x33, `tca9535` = 0x34, `sn74lv165a` = 0x40, `other` = 0xFFFF |
| `ext_format` | `none` = 0, `reference_ratios` = 1, `site_map` = 2 |
| `ext site_map kinds` | `empty` = 0, `key` = 1, `aftertouch` = 2, `reference` = 3, `thermistor` = 4, `other` = 5 |

**Bit sets** (JSON name = bit)

| Field | Bits |
|---|---|
| `flags` | `placeholder` = 0, `git_dirty` = 1 |
| `needs` | `pwm_g0_g3` = 0, `tim1` = 1, `high_current_5v` = 2, `lanes_14bit` = 3, `fast_g4_g5` = 4, `exercises_current_limit` = 5, `bkin_on_irq` = 6 |
| `uses` | `+3V3` = 0, `+5V` = 1, `AN0` = 2, `AN1` = 3, `AN2` = 4, `AN3` = 5, `INJ` = 6, `SYNC` = 7, `SCK` = 8, `MISO` = 9, `MOSI` = 10, `CS0_N` = 11, `CS1_N` = 12, `SCL` = 13, `SDA` = 14, `IRQ_N` = 15, `G0` = 16, `G1` = 17, `G2` = 18, `G3` = 19, `G4` = 20, `G5` = 21 |
| `lanes[].flags` | `ratiometric` = 0, `multiplexed` = 1, `buffered` = 2, `bipolar` = 3, `adc4_ok` = 4 |
| `glines[].flags` | `active_low` = 0, `fast` = 1, `pwm` = 2, `exceeds_rule` = 3, `not_on_s5` = 4 |
| `cs[].flags` | `active_high` = 0 |
| `devices[].flags` | `polled` = 0, `addr_selected` = 1, `shares_lane` = 2 |
| `ext_flags` | `measured` = 0 |

<!-- end of generated tables -->
<!-- layout:end -->
