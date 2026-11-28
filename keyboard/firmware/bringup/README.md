# bringup: the testbed motherboard's bring-up firmware

> **Status (2026-11-28): written and compiled; never run on hardware, because the board does not exist yet.** It
> builds for `kbd_testbed_a` with Zephyr v4.5.0 and Ubuntu's arm-none-eabi GCC 13.2.1 (`gnuarmemb`, not the Zephyr
> SDK), with no warnings from its own sources. The same code also runs on a **simulated board** on native_sim
> (`sim/`): register models of the parts, built from the same `nets.py`, against which `host/test_sim.py` drives
> 21 scenarios through the shell protocol, each also checked by a SPEC §3.5 rule monitor in the model. That tests the firmware's logic and its protocol; it does not test
> the hardware, and no figure on this page is a measurement.

SPEC §10's bring-up steps 5-7 for the testbed motherboard
([SPEC](../../hardware/design/SPEC.md#_10-bring-up-order)) as shell commands on two consoles, USART1 (the J_SWD
STDC14's virtual COM port) and CDC ACM on J1. The commands, their records and their errors are in
**[PROTOCOL.md](PROTOCOL.md)**, the contract a bench harness drives; `host/tb_proto.py` parses it.

## Build

```sh
source /root/zephyrproject/ENV.sh      # ZEPHYR_BASE, gnuarmemb (this workspace)
# the board (the app sets BOARD_ROOT to keyboard/firmware; -DBOARD_ROOT=... also works)
west build -p always -b kbd_testbed_a keyboard/firmware/bringup -d keyboard/firmware/build/bringup
# with the bench-supply mode (SPEC §10 step 5 without a USB host; see below)
west build -p always -b kbd_testbed_a keyboard/firmware/bringup -d keyboard/firmware/build/bringup-bench \
    -- -DCONFIG_BRINGUP_BENCH_SUPPLY=y
# the simulated board, and its tests
keyboard/firmware/bringup/sim/run_tests.sh
# all three builds with twister (Ubuntu's GCC needs -W: Zephyr's own bit_rev.h warns on it, see ../boards)
python3 $ZEPHYR_BASE/scripts/twister -T keyboard/firmware/bringup -A keyboard/firmware/boards \
    -p kbd_testbed_a -p native_sim/native/64 -O <out> --disable-warnings-as-errors
```

Build result (2026-11-28, default configuration, with the descriptor read before the slot lines): **FLASH 161,628 B**
(3.9 % of 4 MB), **RAM 53,544 B** (2.1 % of 2,496 KB); `arm-none-eabi-size`: text 158,396, data 3,232, bss 50,301. The bench variant and the
simulated board build too. Build directories go under `keyboard/firmware/build/` (git-ignored).

Flash with `west flash -d <build>` (STM32CubeProgrammer over an STLINK-V3 on J_SWD; `--runner openocd` is
configured too). Not a single flash has been done: there is no board.

## What it does

**At boot** (`src/main.c`), in SPEC §3.5's order:

1. Before any expander driver (POST_KERNEL, priority 51, between I2C at 50 and the TCA9535 driver at 52): if I2C1
   or I2C4 does not answer its first transfer, clock it free with Zephyr's bus recovery and try once more (a reset
   in the middle of a read can leave a target holding SDA low, and then nothing on the bus, the rail enables
   included, could be restored; `boot` reports `i2c1_bus=`/`i2c4_bus=`); read
   every expander's input, output and configuration registers and the mux's control register into a snapshot,
   deselect the mux, and, if U_EXP1 is still driving after a warm reset, open the bus switches, then turn the 5 V
   enables off, then the 3.3 V ones.
2. `main()`: the restore (every slot line high-impedance, every bus switch open, every rail enable low, LEDs off,
   the KVM coupon held in reset, the mux pulsed through RESET and deselected), then everything read back against
   the generated restore state; the 13 INA226s identified (0x5449 / 0x2260), CAL and configuration written, INA226
   0x40's alert at the unconfigured 100 mA; the lanes' ADC channels; USB; the CDC shell; the board service.
3. The boot report on USART1 (`@tb boot ...`, also `tb boot` later): the reset cause, each expander before and
   after, the mux, each monitor. **SPEC §10 step 5's "the firmware restores them after an NRST reset with rails
   on"** is: rails on, NRST, `tb boot`: `reset=pin`, U_EXP1 `por=0` with its `driven` outputs, and `ok=1`
   everywhere after.

**The board service** (`src/service.c`, a thread): applies USB events to the budget (SPEC §3.2: nothing powered
before SET_CONFIGURATION, everything off on a bus reset, deconfiguration or suspend), reads U_CC once it answers
(up to 200 ms after boot, SPEC §8.4) and whenever its INT_N falls (clearing INTERRUPT_STATUS, the only U_CC write
the firmware ever makes), wakes on EXP_INT_N and also polls U_EXP2 every 100 ms (the driver's help warns it misses
short pulses), keeps INA226 0x40's alert at the budget, and classifies and acts on faults and alerts (`lib`'s
`tb/trip.h`): a coupon pulled while powered, a TPS2553 limiting (attributed by current or sag), the S5 breaker,
a monitor's latched alert, VSYS over budget (shed S5 first), a dead rail, a lost monitor. It never prints; it
posts events, which a printer thread copies to both shells and `tb ev` replays.

**Commands** (PROTOCOL.md has all of them): `tb info`, `boot`, `safe`, `usb`, `cc`, `budget [override|bench|base]`,
`ina [cfg|alert|drv]`, `exp`, `rail`, `slot`, `desc [write test]`, `lanes`, `selftest`, `trips`, `mon`, `ev`,
`reboot`.

**The slot power rules of SPEC §3.5, and where they live:**

| Rule | Where |
|---|---|
| no slot power before configuration, nor while suspended | `lib/src/budget.c` (`tb_budget_check`) |
| no slot power while PRESENT_N reads high | `tb_rail_on()` |
| +3V3 first, the descriptor, then +5V; the 5 V rail goes off before the 3.3 V | `lib` (`TB_REFUSE_ORDER`, `tb_budget_off_mask`), `src/slot.c`, `hw_off()` |
| the slot's direct lines (CS0_N, CS1_N, G0-G5, IRQ_N) configured only after a valid descriptor is read and checked (SPEC §4.6, risks.md EL-2; below) | `tb_slot_on()` in `src/slot.c` |
| the bus switch closes only after the rails are up, opens before they go down (either rail: a 5 V-only shed opens it too) | `tb_rail_on()` opens it before any rail comes up, `src/slot.c` and the self-test close it after, `hw_off()` opens it before any rail goes down |
| every MCU line into an unpowered slot high-impedance (CS lines are not the SPI driver's `cs-gpios`, which it would drive high) | `tb_slot_lines()`, the board dts |
| the mux deselected before rails go down (and `i2c-mux-idle-disconnect`) | `hw_off()`, the early snapshot, the board dts |
| the VSYS budget and the slot LDO's 300 mA, an override that only lowers | `lib/src/budget.c` |
| S5_IRQ_N (TIM1_BKIN) never `gpio_pin_configure()`d while TIM1 is enabled | `tb_slot_lines()` (`TIM1_IN_USE`) |
| U_CC: never DISABLE_TERM, MODE_SELECT, I2C_SOFT_RESET, DISABLE_RD_RP | `src/typec.c` through `tb_tusb320_write_allowed()` |

## The bench, step by step (a proposal for SPEC §10)

* **Step 5, power, from a current-limited 5 V supply with no USB host:** build with `CONFIG_BRINGUP_BENCH_SUPPLY=y`
  and work on USART1. `tb boot`, `tb ina` (VSYS, +3V3_MCU, +3V3_USB with no slot on), `tb budget bench <the
  supply's limit, mA>`, then per slot `tb rail +3V3_Sn on <mA>` / `tb rail +5V_Sn on <mA>` into dummy loads, `tb
  ina <rail>` against a meter, `tb trips`, `tb rail ... off`; the trip points with the test coupon's `climit`
  steps (step 7) or an external load. Then the NRST check above. Then U_CC on each source: `tb cc` (with a Type-A
  to C cable it should say `default`), scoping CC and VBUS as SPEC asks.
* **Step 6, the MCU and USB:** without bench mode; the host enumerates CDC ACM (`1209:0001`, the pid.codes test
  PID, bench only), `tb usb` says `configured` and `hs`. The 8 kHz test is hid8k's, not this app's.
* **Step 7, the test coupon:** `tb slot <n> on keep` (a blank EEPROM keeps +3V3 on), `tb desc <n> write test
  serial=<n>`, then `tb selftest <n> all` in each slot: lanes against 0.2/0.4/0.6/0.8, every converter on every
  lane agreeing, the SPI/G-line/SYNC loopback, IRQ_N, the G0/G2 load steps, the slot's series resistance
  (`rs_mohm`, SPEC §3.1's calibration), the G1 current limit and, on S1-S4, the G3 one.

## Simulated board (`sim/`)

```sh
keyboard/firmware/bringup/sim/run_tests.sh                     # build + 21 pytest scenarios (about 11 s)
python3 keyboard/firmware/bringup/sim/mutate.py <scratch>      # fault injection: each mutation must fail a test
west build -b native_sim/native/64 keyboard/firmware/bringup -d <b> && <b>/zephyr/zephyr.exe   # interactive: a pty
<b>/zephyr/zephyr.exe --uart_stdinout                          # or on stdin/stdout
```

The real `src/` and `lib/` code, on native_sim with `gen_board.py`'s overlay of the board's nodes on emulated
controllers (`zephyr,gpio-emul`, `zephyr,i2c-emul-controller`, `zephyr,spi-emul-controller`, `zephyr,adc-emul`),
and register models of the parts (`sim/emul_*.c`): the TCA9535 (SCPS201D's register pairs and INT), the INA226
(Eq. 3 and 4, the latched AFF), the TCA9548A, U_CC (TUSB320LAI's registers; any write but the INT clear is counted
as a violation), every coupon's M24C02 behind the mux, and the test coupon's '165 loopback. `sim/world.c` is the
board: rails from the expanders' enables, the test coupon's ladder, loads, LED and IRQ_N, the TPS2553s'
constant-current limit and 7.5 ms FAULT deglitch, S5's latching breaker, VSYS, PRESENT_N, U_CC's advertisement.
Extra commands (`sim coupon`, `sim source`, `sim usb`, `sim load`, `sim pg`, `sim state`; records start `@sim `)
change the world. USB is not simulated: `sim usb configured|deconfigured|reset|suspend|resume|disconnected` injects
the events the stack would deliver.

**The rule monitor** (`sim/world.c`, `check_rules()`): at every model update it checks the board's physical state,
as the expanders, the mux and the MCU's pins set it, against SPEC §3.5, independently of the firmware's own
bookkeeping: +5V without +3V3; a rail switched with its slot's bus switch closed; a rail switched on in an empty
slot; a bus switch closed, a mux channel selected, or a CS, G or IRQ line driven high into a slot whose +3V3 is off;
a CS or G line driven at either level, or the bus switch closed, on a slot holding a turned coupon (`sim coupon <n>
turned`, which the slot key of D2 stops unless the socket's hole 39 was left unplugged);
a rail switched on while the host (as the `sim usb` commands set it) has not configured the device, or still on
200 ms of native_sim time after it left that state (bench mode excepted). `sim state` prints the count and the first
violation, and every test's fixture asserts there were none.

**Fault injection** (`sim/mutate.py`, 2026-11-27; 2026-11-28): thirteen mutations of `src/` and `lib/`, each in a
scratch copy; each must make a test fail. With the rule monitor every one is caught. Without it
(`--without-monitor`) the sequencing mutations (the bus switch left closed as rails go down, CS lines left high,
3.3 V off before 5 V, CS driven before power, the bus switch closed before +5V, and since 2026-11-28 the lines
driven before the descriptor) pass every other test: before the monitor, the scenarios could not see them.

**What the review of 2026-11-27 found and fixed:** the rule monitor showed the firmware switching +5V with the bus
switch closed (the self-test's `power` and `load5` steps, and any 5 V-only shed such as S5 first), against SPEC
§3.5's "close the slot's bus switch only after its rails are up, open it before they go down"; the I2C buses had
no recovery from a target left holding SDA low by a warm reset; USB events shared the service's queue with
unbounded EXP_INT_N kicks, which could fill it while a self-test step held the lock and drop a reset or a suspend
(kicks now coalesce to one); and nothing tested an empty slot (`test_empty_slot_is_never_powered`) or a VBUS loss.

**What it caught** (now fixed): the board devicetree named ADC channel nodes with decimal unit addresses
(`channel@10`), which Zephyr's lookup reads as hex, so every lane on channel 10 and up would have failed to
configure on the real board; the series-resistance estimate, which the lanes' 14-bit quantization of a 1 % drop
limits to a few percent (now weighted by each lane's signal: 326 against the model's 325 mOhm); a stale report for
a slot that was already on; and the discovery limit below.

**What it cannot catch:** anything electrical or about timing on the real parts; the I2C bus itself (capacitance,
clock stretching, a stuck SDA: the bus-recovery path never runs in the model, whose emulated buses always answer);
the USB stack and the host; a warm reset (every test starts from a power-on model, so the early snapshot's
warm-reset branch is untested); the rule monitor's own reading of SPEC §3.5; driver behaviour the models do not reproduce (for
example the TCA9535 driver's interrupt worker is real, but the model's INT timing is not the part's); a dead CS1_N
(the loopback model samples at the transfer); the INA226's conversion time (the model converts instantly).

## Findings for SPEC (also in this workflow's report)

* **The descriptor before the lines (2026-11-28; risks.md EL-2, SPEC §4.6):** `tb_slot_on()` used to configure
  the slot's direct lines (CS0_N and CS1_N high, G0-G5 low, IRQ_N an input) as soon as +3V3_Sn was up, and read the
  descriptor after. It now reads and checks the descriptor first, as SPEC §4.6 words it ("reads the descriptor, and
  only then configures anything else"); the read needs only +3V3_Sn and the slot's mux channel. Why, with the slot
  key of D2 in place: the key works only while socket hole 39 is plugged and the coupon's pin 39 pulled, both by
  hand (JLC lists neither part), and a coupon that goes in turned reads present (PRESENT_N on its GND), so the
  order is what keeps CS0_N off its GND and G0/G1 off its rail. Cost: none found; during the read the lines are
  high-impedance, as they are with the slot off, and the bus switch is still open. What holds them then is the
  coupon: the A1 coupons put 100 k on every G and CS line they use (pull-downs on G, pull-ups on CS). SPEC §4.9 has
  no such rule; `keyboard/tools/coupon/rules.py` reports a coupon line without a pull (`slotlines.idle`, a WARN:
  the haptics coupon's G0-G5 go to DRV8316 inputs with no pull on the coupon). `test_turned_coupon_is_refused_without_driving_it` and the `lines_before_descriptor` mutation
  cover it. **Still open (not part of the decision):** a turned coupon holds the slot's SCL on its GND, which jams
  I2C4 while its mux channel is selected; the read then waits for Zephyr's 500 ms `I2C_TRANSFER_TIMEOUT_MS` and
  the deselect fails too, so recovering needs a MUX_RST_N pulse (U_EXP2 P10, on I2C1). The model NAKs instead of
  jamming. EL-2's `zephyr,transfer-timeout-ms` of about 20 ms on i2c4 and that recovery are proposals.
* **Discovery against the slot LDO:** declaring a slot at its 250 mA coupon rule until its descriptor is read means
  that with one coupon on (the test coupon declares 120 mA) a second slot cannot be discovered (120 + 250 > 300).
  The bring-up adds `probe=<mA>`, a lower discovery declaration guarded by the monitor's alert. SPEC could set a
  discovery current in the coupon rules (a coupon draws at most N mA until enabled) or let the firmware discover at
  the measured current.
* **Bench supply:** SPEC §10 step 5 powers the slot switches from a bench supply, but §3.5 forbids slot power before
  a host configures the device. `CONFIG_BRINGUP_BENCH_SUPPLY` adds an explicit operator mode, off by default.
* **A lowered Type-C advertisement has a deadline:** a sink must follow a change of the source's Rp within
  tSinkAdj, 60 ms max (Type-C specification Table 4-29, as Zephyr v4.5.0 quotes it in
  `include/zephyr/drivers/usb_c/usbc_tc.h`, `TC_T_SINK_ADJ_MAX_MS`; SPEC §8.4 leaves the value open). The service
  reacts at once to U_CC's INT_N through U_EXP2's interrupt, but its polling backstop runs every 100 ms
  (`CONFIG_BRINGUP_MON_PERIOD_MS`), longer than tSinkAdj; and whether U_CC reports such a change at all is SPEC
  §3.8's open question.
* **Event lines can be lost** on a busy or unread shell (Zephyr's shell drops a print it cannot lock), hence the
  event ring and `tb ev`.

## Not verified

* Everything about the hardware: the board has not been made.
* That a TPS2553's FAULT reaches U_EXP2 and the classifier as modelled; the thresholds (80 % of a minimum trip,
  3.0 V and 4.3 V sag) are proposals.
* The self-test's tolerances (lanes 1 %, load steps 5 %, current limits 3 % around SPEC §3.1's window) are
  estimates, and the SN74LV165A at 1 MHz in SPI mode 3 through the bus switch is the test coupon's proposal
  (its hold-time margin is **unverified**, `sheets/test_coupon.py`).
* The CDC ACM shell and the USART1 shell together on the real board.
