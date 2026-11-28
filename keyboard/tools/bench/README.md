# bench: the bring-up harness for the testbed

> **Status (2026-11-28): written and tested against simulated boards only. No testbed exists, so this harness
> has never touched hardware, and no number in this directory is a measurement.** It is tested against its own
> simulated board (`tbbench/simdev.py`, 39 injectable faults) and against the bring-up firmware itself built for
> native_sim (`keyboard/firmware/bringup/sim`), whose own rule checker must count no violation after every run, and
> over a pseudo-terminal with pyserial: 223 tests. The simulator is held to the firmware command by command (the
> same 97-command script on both must give the same done lines and records, `tests/test_native_sim.py`) and to the
> firmware's shell registration in `src/cmds.c` (`tests/test_simdev.py`). `mutate.py` breaks 59 of the harness's
> own rules one at a time and checks that the tests fail for each (all 59 do, 2026-11-28). The tests prove the
> harness's sequencing, its arithmetic, its stop-on-danger path and its reports. They do not prove that a single
> limit below suits the real board.

`bench.py` walks SPEC §10's bring-up order for **stage A1** ([SPEC](../../hardware/design/SPEC.md#_10-bring-up-order);
the owner's decision D1 of 2026-11-27: the motherboard, the test coupon and the Hall-effect coupon first, A2 later)
on the testbed's console. It drives the bring-up firmware's shell protocol
([PROTOCOL.md](../../firmware/bringup/PROTOCOL.md), version 1), judges every reading against limits taken from SPEC,
`nets.py`, the coupon sheets and the datasheets, **stops on the first dangerous failure** and makes the board safe,
and writes a JSON and a Markdown report per run, with the board serial and the git commit. A checklist mode prints
the steps a person must do with a meter and a scope before power-on, which no firmware can check.

## What a run does

Motherboard (SPEC §10 steps 5 and 6), then every slot with a **test coupon** (step 7), one slot at a time, then
every slot with a **Hall coupon** (step 8, A1). The test coupon "checks every slot and the monitors' accuracy before
any sensor does" (SPEC §10 step 7), so its slots always run first, whatever order `--slots` names. A2's coupons
(haptics, coil, shear, TMR) have no procedure here: `--coupon` refuses them, and a descriptor that names one fails.

| Step | SPEC | Commands | Pass when (each also judged by the harness from the raw numbers) |
|---|---|---|---|
| `link` | PROTOCOL.md | shell setup, `tb info` | protocol 1, `fw=bringup`, `board=kbd_testbed_a`; nets revision as this checkout's; the board map hash as gen_board.py computes it from the nets.py judged against (warn, or fail with `--strict-map`), and a warning if this checkout's generated `tb_board_map.h` is stale against that nets.py; a bench-supply build for `--power bench` |
| `safe` | §3.5, §8.4 | `tb safe` | every expander and the mux read back their restored state |
| `boot` | §10 step 5, §3.5, §8.4 | `tb boot` | both I2C buses answered (a recovery is a warning); U_EXP1-3 at 0x20-0x22 answered and restored; the mux at 0x70 deselected; the 13 INA226s at SPEC §3.4's addresses identified (0x5449 / 0x2260) with SPEC §3.4's CAL; boot restore ok |
| `expanders` | §3.5 | `tb exp` | every pin named as `nets.EXPANDERS` names it; every EN_* low, BUSEN_N_* high, G4/G5 low, LEDs off, MUX_RST_N high, KVM_RST_N low; SLOT_FAULT_N, PM_ALERT_N and VSYS_PG high. Records which slots have a coupon (PRESENT_N low) |
| `monitors` | §3.4, §3.2, §3.6 | `tb ina all` | each monitor's CAL and LSB, current and shunt current within 2 LSB + 1 %; VSYS 10-100 mA and 4.5-5.5 V, and on USB power **on or above the USB-C load line** (4.75 V − 0.25 Ω × I at J1, less U2 and the shunt; D4 of 2026-11-27; a warning below it); its margin over VSYS_PG's falling edge (info); +3V3_MCU 10-100 mA, +3V3_USB 0-30 mA, both 3.3 V rails within the AP2112K's ±1.5 % less their shunt's drop; every switched rail off (at most 1 V and 5 mA) |
| `typec` | §3.2, §3.8 | `tb cc`, `tb budget` | U_CC present, identified, decided and attached; the advertisement as `--source` declares (a Type-A-to-C cable reads `default`); the VSYS budget is `nets.vsys_budget` of it (100 mA before configuration) and the ceiling 2800 mA |
| `usb` | §10 step 6 | `tb usb`, `tb budget [bench]` | configured at high speed (USB power), or unconfigured and the bench budget set (bench power) |
| `nrst` (`--nrst`) | §10 step 5, §3.5 | `tb rail +3V3_Sn on`, NRST by hand, `tb boot`, `tb exp` | `reset=pin`, U_EXP1 `por=0` with outputs driven, every expander restored, every enable low |
| `turned` (`--turned-test N`) | risks.md EL-2's test, §4.2, §4.6 | prompts, `tb exp`, `tb slot N on`, `tb slot N`, `tb ina`, `tb safe` | bench supply only, before hole 39's plug is fitted: the test coupon plugged in turned 180° reads present, and the firmware **refuses** it (`desc_bus`: its SCL meets the coupon's GND), leaves the slot off and dead, `tb safe` frees I2C4 (MUX_RST_N), and the operator's scope saw none of CS0_N, CS1_N, G0, G1 driven. A slot the firmware accepts is a dangerous stop |
| `slot<n>.key` (`--key-check`) | §10 step 7, §4.2 (D2) | prompts, `tb slot`, `tb exp` | with the slot off, the operator tries the test coupon turned 180°: it stays out (its pin 2 meets the plugged hole 39); then back in the right way round, PRESENT_N low again |
| `slot<n>.on` | §10 step 7 / 8, §3.5, §8.4 | `tb slot <n> on`, `tb ina` | no fault; +3V3 (and +5V if the descriptor asks) on, the bus switch closed; declared currents within the coupon rules; after two fresh INA226 results, the current under the declaration (+10 % + 1 mA) and under 80 % of the switch's minimum trip, the voltage in its window (+5V against VSYS read again then). A slot named by `--coupon` whose PRESENT_N reads high fails (the declared coupon was not tested); an undeclared empty slot is skipped. A slot whose EEPROM did not answer (`desc_bus`: the mux, its I2C, or a coupon in turned) is reported with that hint, never powered without a descriptor, and followed by `tb safe` to free I2C4. A **Hall coupon** whose EEPROM the firmware cannot read (blank, or compiler v0's PCKC) is powered with `nodesc` on the currents of its descriptor of record (`descriptors/coupon-hall.json` through `descriptor.py`), as a warning |
| `slot<n>.desc` | §4.6, §11 #18 | `tb desc <n>` | the coupon's descriptor of record valid **through `keyboard/tools/coupon/descriptor.py`** (JSON, encode, check_image, decode); the dumped bytes valid on the host; the firmware's fields equal the host's; the coupon type as declared and as its record; the revision and declared currents as its record (warnings: the two formats disagree today); declared currents within the rules; the test coupon's lane expectations 0.2/0.4/0.6/0.8 ± 1 % |
| `slot<n>.lanes` | §10 step 7, §4.3 | `tb lanes <n>` | VDDA 3.2-3.4 V; test coupon: AN0-AN3 at k/5 of VREF+ within 1 % + 2 LSB, the firmware's verdict equal to the harness's; every other converter within 3000 ppm. Hall coupon: recorded, not judged (its own procedure, SPEC §10 step 8, is not written), converters compared |
| `slot<n>.inj` (`--inj`) | §10 step 7, §4.7 (D7) | prompts, `tb lanes <n>` x 2 | the operator drives INJ high (a clip lead from the coupon's TP1, +3V3, to TP15, INJ); AN0 lifts by 0.43-0.58 V (the sheet's estimate, widened 2 % and 4 LSB for two readings), AN1-AN3 follow by 3/4, 1/2, 1/4 of that (± 0.02); with the lead off AN0 is back within 8 LSB of its reading before. INJ left high skips the self-test (a failure), and at slot off an INJ still driven from the rig shows as a back-fed coupon rail |
| `slot<n>.selftest` | §10 step 7, §3.1 | `tb slot <n>`, `tb ina`, `tb selftest <n> [loads] [climit]` | first the slot's enabled rails read again against their declarations (a dangerous stop, before any load or current limit is applied); then each step recomputed: idle under 10 mA at 3.0 V or more; lanes; loopback (8 patterns, 7 on S5); the G0/G2 load steps within 5 % of V/R; the current limits inside SPEC §3.1's window ± 3 % with SLOT_FAULT_N seen and cleared. Records the slot's series resistance (the SPEC §3.1 calibration) |
| `slot<n>.meter` (`--meter`) | §3.3 | prompts | the INA226 against a meter in JP_3V3_Sn, within the INA226's offset and gain, the shunt's tolerance and the meter's |
| `slot<n>.trips` | PROTOCOL.md | `tb trips` | after two fresh INA226 results: no finding, SLOT_FAULT_N clear, VSYS power-good, and the snapshot's own per-rail readings (`trip_rail`) judged here as well: an enabled rail under its declaration's danger level, every off rail dead (either sign of current) |
| `slot<n>.off` | §3.5 | `tb slot <n> off`, `tb ina` | both rails and the bus switch off; nothing live on the rails afterwards |
| `final` | §3.5 | `tb ev`, `tb safe`, `tb slot` | every event seen (no gap the ring lost), every slot off |

Slots run one at a time, so only one 3.3 V slot rail is ever on (the slot LDO's 300 mA, SPEC §3.2). **Before and
after** every command that may change power, and after any command that finds its slot unexpectedly off
(`err=slot_off`), the harness replays the event ring (`tb ev <first unseen>`): a shell can miss event lines, and an
unread CDC port can stall the event printer for both shells (PROTOCOL.md, Events). Replaying before matters: the
self-test's power step calls `tb_slot_on()` on a slot that is off (`src/coupon_test.c`), so a harness that learned
of a trip only afterwards would re-power the slot that had just tripped.

The shell setup goes one line at a time with a short drain after each: Zephyr's serial shell backend holds input
in a ring of `CONFIG_SHELL_BACKEND_SERIAL_RX_RING_BUFFER_SIZE` bytes, 64 in the board build, and when the ring is
full its RX handler reads each further byte and drops it ("No space in the ring buffer - consume byte",
`subsys/shell/backends/shell_uart.c`, v4.5.0). The four setup lines and an empty one are 73 bytes.

**It stops the run** on any over-current (a `trip` event of `switch_limit`, `s5_breaker`, `alert`,
`alert_unattributed`, `vsys_over`, `fault_unattributed` or `fault_kvm`; a `rail_off` for `trip`,
`vsys_over_budget` or `vsys_pg_low`; `tb slot` failing with `fault_3v3`, `over_3v3`, `fault_5v` or `over_5v`; a
reading over the declaration, over 80 % of a switch's minimum trip or at 95 % of a monitor's full scale, at slot
on, again before the self-test and in `tb trips`' snapshot, and wherever else the harness powers a slot: the +3V3-alone
phase of a descriptor write, the dump of a descriptor the firmware refused (declared at its descriptor of record's
current, not the 250 mA rule), the NRST test's rail; VSYS over 200 mA with nothing on; a current limit above its
window or SLOT_FAULT_N not clearing), on VSYS power-good lost,
on an off rail that reads live (back-powering, or a switch that ignores its enable), on a turned coupon the firmware
accepts, and when a command that changes power never answers. An off rail counts as live on a current in either
direction (5 mA), where the firmware's classifier compares the signed value (finding 17). It stops **before** it
enables anything else: the next rail is never asked for, and nothing but the event replay comes between the stop and
`tb safe`. It then sends `tb safe` (up to three times) and calls the board **safe only if**
every slot's enables read off (`tb slot`) **and**, two fresh INA226 results later, every switched rail's own monitor
reads it dead (at most 1 V and 5 mA, `tb ina all`). The enables alone are no proof: a damaged TPS2553 or a
back-powered rail stays live with EN low, and `tb safe`'s `restore` records check the expanders' registers, not the
rails. A monitor that does not answer leaves its rail unconfirmed, so the board is not called safe either (+5V_KVM
has no monitor: only its enable is read). It marks the rest of the run "not run", and the report says either that
the board was confirmed safe or **REMOVE POWER NOW**, naming the rails that still read live or could not be read. A
lost link says to remove power too.

A `low_3v3` on `slot on` is diagnosed, not just failed: the harness turns the rail on again with `tb rail`, waits
for two fresh INA226 results and reads it. A rail at 0 V is dead (check that JP_3V3_Sn is fitted first); a rail
that reads fine is the firmware's settle check reading a stale result (finding 1 below), and the harness retries with
the slot's monitors at 2.2 ms results. A descriptor the firmware refuses is dumped under a `nodesc` declaration
(only after the EEPROM answered: the coupon is then the right way round) and checked on the host, so the report says
what the EEPROM holds.

## Bench setup

* The motherboard, a test coupon (`keyboard/hardware/design/sheets/test_coupon.py`) and the Hall-effect coupon
  (`sheets/coupon_hall.py`), each coupon's J1 fitted by hand without pin 39, every socket's hole 39 plugged (the key,
  D2 of 2026-11-27: `bench.py checklist`).
* An STLINK-V3 (STLINK-V3SET or -MINIE) on J_SWD (STDC14), for flashing and for USART1 through its virtual COM port,
  115200 8N1.
* A current-limited bench supply (5.0 V, 0-1 A at least) and a USB-C power breakout to feed J1 for the first power.
* USB-C sources: one advertising Default, one 1.5 A, one 3.0 A (one that does not share its power between ports),
  and a Type-A port with a Type-A-to-C cable (SPEC §3.8, §10 step 5).
* A multimeter (and a meter for µA ranges for `--meter`, a Nordic PPK2 or Joulescope class instrument, SPEC §3.3),
  a scope with at least two channels for the U_CC power-up checks and the turned-coupon test, a clip lead for
  `--inj` (TP1 to TP15 on the test coupon), optionally an electronic load.
* A PC with Python 3.10 or later and pyserial: `pip install pyserial`. Nothing else outside the standard library
  (the descriptor of record is read by `keyboard/tools/coupon/descriptor.py`, standard library only).
* Firmware: the bring-up app's default build (USB) and its bench-supply build (`-DCONFIG_BRINGUP_BENCH_SUPPLY=y`),
  [keyboard/firmware/bringup/README.md](../../firmware/bringup/README.md).

**Ports.** On Linux the testbed's CDC ACM port (VID:PID 1209:0001) and the STLINK-V3's VCP are both
`/dev/ttyACM*`; use the stable names under `/dev/serial/by-id/`, and be in the `dialout` group (or add a udev rule).
On Windows both are COM ports (Device Manager names them). ModemManager 1.14 and later probes a `cdc_acm` port only
if its interface protocol claims AT commands (class 2, subclass 2, protocol 1-6, `src/mm-filter.c`, the "strict"
default policy since 1.14.0); Zephyr's CDC ACM sets `bInterfaceProtocol = 0`
(`subsys/usb/device_next/class/usbd_cdc_acm.c`, v4.5.0), so it is left alone. With an older ModemManager, or a
`legacy` filter policy, add `ENV{ID_MM_DEVICE_IGNORE}="1"` for 1209:0001 in a udev rule, or its AT probes land in
the shell. Close any terminal program on the port before a run, and never read it with `cat`: that leaves the tty
in cooked mode with ECHO on, and Linux echoes the board's output back into its shell as input.

## Commands

```sh
cd keyboard/tools/bench
python bench.py checklist                       # the manual steps (text); --format md --out FILE for a fillable copy
python bench.py run --help

# SPEC §10 step 5, first power: bench supply on J1, no host, coupons unplugged, USART1 through the STLINK's VCP
python bench.py run --power bench --bench-ma 150 --console uart --port /dev/serial/by-id/usb-STMicro...-if02 \
    --board-serial MB-A-001                     # the motherboard only: ends INCOMPLETE (no coupon), not FAIL
# step 7: the test coupon in S1, the supply's limit raised to 1 A; once per slot
python bench.py run --power bench --bench-ma 1000 --console uart --port ... --board-serial MB-A-001 \
    --write-descriptor 1 --key-check --inj --climit --meter --nrst
# risks.md EL-2's test, once, before S3's hole 39 is plugged (a scope on S3's CS0_N, CS1_N, G0, G1)
python bench.py run --power bench --bench-ma 1000 --console uart --port ... --board-serial MB-A-001 --turned-test 3
# step 8 (A1): the Hall coupon in S1, after the test coupon has been through every slot
python bench.py run --source 3.0A --port /dev/ttyACM0 --board-serial MB-A-001 --coupon 1=hall
# U_CC: once per source, from an unpowered board each time (scope work: see the checklist)
python bench.py run --source typeA --port /dev/ttyACM0 --board-serial MB-A-001 --slots 1
# step 6-7 on a USB host: CDC ACM, every slot with a coupon
python bench.py run --source 3.0A --port /dev/serial/by-id/usb-pid.codes_...-if00 --board-serial MB-A-001 --climit

# the same walk against the simulated board, with faults (bench.py faults lists them)
python bench.py sim --climit --inj --key-check --fault dead_rail=+3V3_S1
python bench.py sim --fault short=+3V3_S1:400            # exit status 2: stopped on a dangerous failure
python bench.py sim --coupons 1=test,2=hall --fault bad_descriptor=2:blank   # the Hall coupon on its record
python bench.py sim --power bench --turned-test 2 --fault lines_before_desc  # exit 1: lines driven into it
# against the bring-up firmware on native_sim
source /root/zephyrproject/ENV.sh
west build -b native_sim/native/64 ../../firmware/bringup -d /tmp/bringup-sim
python bench.py native-sim --exe /tmp/bringup-sim/zephyr/zephyr.exe --climit --sim-cmd "sim coupon 2 hall" \
    --coupon 2=hall

# rehearse a real run (POSIX): the simulated board on a pseudo-terminal, then "run" on it as on the bench
python bench.py serve-sim --fault stale_ina=+3V3_S1 &       # prints the pty, e.g. /dev/pts/3
python bench.py run --port /dev/pts/3 --board-serial REHEARSAL --console uart --meter

# the tests (from the repository root); the native_sim ones need TB_SIM_EXE or the build at
# keyboard/firmware/build/bringup-sim, the pty one needs pyserial
TB_SIM_EXE=/tmp/bringup-sim/zephyr/zephyr.exe PYTHONDONTWRITEBYTECODE=1 \
    python -m pytest -p no:cacheprovider keyboard/tools/bench/tests -q
# the tests of the tests: break each of 59 safety and judging rules in a scratch copy; every one must fail a test
python keyboard/tools/bench/mutate.py /tmp/tbbench-mutants          # about six minutes; prints "59 of 59 caught"
```

Options: `--slots 1,3` (default: every slot whose PRESENT_N reads low), `--coupon N=hall` (repeatable; every other
slot holds a test coupon), `--no-loads`, `--climit` (asks first: it drives each switch into its limit for 15 ms),
`--inj` (D7), `--key-check` (D2), `--turned-test N` (EL-2, bench supply), `--meter` and `--meter-tol-pct`,
`--nrst` (USART1 only: NRST drops the CDC port), `--probe-ma`, `--no-retry-stale` (finding 1),
`--write-descriptor SERIAL` (only when a test coupon's EEPROM is blank; JP1, WP, must be open), `--strict-map`,
`--nets` (judge against another nets.py), `--operator` (initials, optional), `--notes`, `--out`.

Exit status: 0 PASS (or PASS with warnings), 1 FAIL, 2 STOPPED, 3 INCOMPLETE (nothing failed, but steps were
skipped or no slot was tested).

## Reports

A hardware run writes `runs/<board serial>/<UTC time>/` here (`--out` elsewhere; `sim` and `native-sim` write to a
temporary directory unless `--out` is given): `report.json` (every check with its measured value, limit and
source, every prompt and the operator's answer, the firmware's `tb info`, the run's options and declared coupons,
the events, the board serial, the coupon serials read from their descriptors, each coupon's descriptor of record as
descriptor.py read it, the per-slot calibration and INJ lift, the harness's git commit and whether the checkout had
local changes), `report.md` (the same for people) and `transcript.log` (every line both ways, timestamped). A run
never overwrites another. Besides the git commit (and `git_dirty`, which ignores untracked files), the report
carries a SHA-256 of the harness's own sources and of the nets.py it judged against (the checkout's, or `--nets`), so
a run made with an uncommitted harness or a locally edited nets.py still says exactly what judged it. A run you want
to keep as evidence is committed with the docs page that cites it; until then every figure in the docs stays
*designed*.

## What it cannot check

* **Anything before the firmware runs**: shorts, solder bridges, part orientation (D11 on the test coupon among
  them), the jumpers, the Rd on CC, first power-up current. That is `bench.py checklist`, done by hand.
* **The key itself.** Whether hole 39 is plugged and each coupon's pin 39 pulled is a hand step; `--key-check`
  records what the operator saw, and the turned-coupon test records how the firmware behaves when the key is
  missing. Neither proves the plug stays in.
* **The series resistors (D3)**, other than that the lines still work through them (the self-test's loopback, load
  steps and IRQ_N): their value is a meter step (checklist U4c). The TIM1 and EXTI timing through them is not seen.
* **The PGTH divider (D4)**: VSYS_PG's falling edge (3.51-3.64 V) cannot be reached from J1, because U2's own UVLO
  (falling at 3.83-3.98 V on VBUS, SPEC §3.1) turns U2 off first; the harness reads VSYS_PG high and its margin, and
  the checklist reads R36. The **+3V3A damping leg** needs a scope (risks.md EL-5's test, checklist L5): VDDA and
  VREF+ are not monitored, and VDDA from VREFINT is a DC figure. The **Kelvin sense** pairs (EL-6) need a 4-wire
  meter at amps (checklist L6); `--meter` checks only the slot's +3V3 at its idle current.
* **Anything that needs an instrument**: rail ramps and U_CC's Rd hand-over during power-up (scope, SPEC §3.8), the
  time to U_CC's first I2C answer, the USB eye at 480 Mb/s, VCAP, +3V3_SLOT and +3V3A (no monitor), the S5 breaker's
  trip point (see finding 4), the 8 kHz HID rate (hid8k's own tool), whether the lines stayed quiet during the
  turned-coupon test (the operator's scope). `--meter` asks for readings; it cannot take them.
* **The monitors' absolute accuracy** without `--meter`: every current and voltage it judges comes through the
  INA226s it is testing. Shunt tolerance is assumed 1 % (SPEC does not give it).
* **Whether its limits are right.** Windows marked "harness proposal" in `tbbench/limits.py` (idle currents, the
  slot rails' ±3 %, VSYS 4.5-5.5 V, 200 mA idle danger, the series-resistance plausibility 250-600 mOhm, the INJ
  margins) are not in SPEC; the INJ lift is the sheet's estimate; the LDL1117's accuracy was not read (st.com
  unreachable). Revisit them after the first boards.
* **Timing.** It cannot see a glitch between two readings, a FAULT shorter than a poll, or how fast the firmware
  reacts to a trip; it sees what the firmware reports.
* **+3V3 before +5V inside one `tb slot <n> on`.** The firmware reads the descriptor, drives the lines, brings +5V up
  and closes the bus switch in that one command, so the harness reads +3V3 only after +5V is already on. Between the
  two, only the firmware's own settle check guards (SLOT_FAULT_N, 3.0 V, the switch's minimum trip, and the
  monitor's alert at the 250 mA discovery declaration). The harness judges +3V3 alone only in a descriptor write's
  `keep` phase.
* **The Hall coupon's sensors**: it powers the coupon (on its descriptor or its descriptor of record), checks its
  descriptor, current and voltage, and records its lanes, but has no procedure for the sensors yet (SPEC §10 step 8,
  SE-2's crosstalk matrix, SE-4's noise floor). **A2's coupons**: none.
* **INJ's and IRQ_N's own levels**: no command reports them (finding 13), so the INJ step reads the lane path only.
* **The USB stack's behaviour under a host**: enumeration, suspend and bus resets come from the real host only; the
  simulators inject the events.
* **Itself on hardware.** The simulated board is this harness's reading of PROTOCOL.md; the native_sim firmware is
  the firmware's reading of the datasheets. Both agree with each other (tests), and neither is a board. The native_sim
  world keeps JP_INJ open, so INJ is tested there only as a path that gives no lift. The simulator's `rx_ring` model
  of the shell's input ring is crude; it proves the harness never has more than one line in flight, not how the real
  scheduler behaves. Where the simulator still differs from the firmware (2026-11-28): it prints each event inside
  the command that caused it, where the firmware's printer thread often prints it during the next command (the
  harness replays the ring around every power command either way); it posts `budget` events only at boot and on USB
  changes; it models each rail's INA226 alert but not VSYS's (`vsys_over`).
* **+5V_KVM dead after `tb safe`**: it has no monitor (SPEC §3.4), so only its enable is read back.

## Findings for the other parts of the project

1. **The firmware's slot-on check reads a stale INA226 result, so `tb slot <n> on` should fail on a healthy rail
   every time** (bring-up firmware; an analysis from the datasheet, not a measurement; re-read 2026-11-28, still
   `settle_ms=20`). `tb_rail_settle()` waits `CONFIG_BRINGUP_SETTLE_MS` = 20 ms after an enable and reads the
   monitor, which runs `TB_MON_CONFIG_DEFAULT` (16 averages of 1.1 ms + 1.1 ms, a result every 35.2 ms,
   `src/monitors.h`), free-running. SBOS547C §6.3.1: "After all of the averaging has been completed, the final
   values ... are updated in the corresponding registers ... These values remain in the data output registers until
   the values are replaced by the next fully completed conversion results." So at the read at most 20 / 35.2 = 57 %
   of the averaged bus samples were taken after the enable: a 3.3 V rail reads at most about 1.9 V, under the 3.0 V
   floor whatever the phase, and the slot is switched off with `low_3v3`. native_sim's INA226 model converts
   instantly, so the firmware's own tests cannot see it. Remedies: write `TB_MON_CONFIG_FAST` (2.2 ms) for the
   settle and wait for CVRF, or settle at least two result periods (71 ms). **This harness works around it** (a fresh
   reading with `tb rail`, then a retry with the slot's monitors at 2.2 ms), records both attempts as warnings, and
   warns about the settle time in every run.
2. **`err=` with `rc=0`.** `tb_done()` prints the error token whenever one is given, so `tb slot <n> on keep` on a
   blank EEPROM ends `@tb done cmd=slot rc=0 err=blank` (seen on native_sim), where PROTOCOL.md says err is "absent
   on success". A harness must take rc as the verdict (this one does).
3. **Two descriptor formats for one EEPROM, and they disagree** (SPEC §11 #18). The firmware reads and writes `PCKD`
   (`keyboard/firmware/lib`), compiler v0's tools write `PCKC` (`keyboard/tools/coupon`): a coupon programmed by
   `make_eeprom.py` is refused by the bring-up firmware (`status=magic`). Every run now shows the content gap as a
   warning: the test coupon declares +5V 170 mA in PCKD and 190 mA in its record (`descriptors/test-coupon.json`,
   which counts USB-C's 5.5 V); the firmware's Hall descriptor (native_sim) +3V3 40 mA against the record's 45 mA.
   The firmware sets the rail's alert and budget from the EEPROM's figure. `tb desc <n>` dumps only 32 bytes of an
   image it cannot parse (`src/descio.c`), so a PCKC image's CRC-32 cannot be checked from a dump: a
   `tb desc <n> raw` that dumps all 256 bytes would let the bench tell a damaged image from a foreign one.
4. **SPEC §10 step 5's trip points cannot all be measured through the firmware.** The S1-S4 switches and every
   +3V3 are covered by the test coupon's `climit` steps. The S5 5 V breaker (2.01-2.46 A) has no path:
   `tb_rail_alert_ua()` caps the monitor's alert at 95 % of the minimum trip and the classifier turns a rail off at
   80 % of it (`lib/src/trip.c`), so an external load on the test coupon's TP2/TP3 is switched off before the breaker
   trips. Either a bench-build command that disarms both for one rail for a bounded time, or the breaker is measured
   on its own with a lab supply.
5. **The firmware's sim world forgets a written descriptor's coupon.** `sim/world.c`'s `sim_test_coupon_powered()`
   is true for `SIM_TEST` only, so a `blank` coupon whose descriptor `tb desc write test` has just written has no
   ladder, loads or loopback, and step 7's write-then-test flow fails on native_sim after the write (the descriptor
   part passes). The firmware is not at fault; the model is. It also keeps JP_INJ open, so the D7 path cannot be
   driven there.
6. **No board identity in the firmware.** `tb info` carries no MCU unique ID (Zephyr's `hwinfo_get_device_id()`), so
   a report ties to a board only through the serial the operator types. Adding `uid=` at the end of `info` (allowed
   by PROTOCOL.md's "new keys at the end") would let the harness record it.
7. **SPEC gives no voltage tolerance for the slot rails** or the base load; the harness uses proposals (above). A
   line in SPEC §3.1/§3.2 would make them limits of record.
8. **Using USART1 while a host has CDC ACM enumerated but closed** can stall the event printer for both shells
   (PROTOCOL.md). The harness copes by replaying the ring, but live events then arrive late; open the CDC port too,
   or run bench mode without a host.
9. **The firmware does not latch a tripped slot off.** After the classifier turns a slot off for `switch_limit`,
   nothing stops the next `tb slot <n> on`, `tb rail ... on` or `tb selftest <n>` from powering it again, so a host
   that missed the event line re-powers a short. This harness replays the ring before every power command; a
   firmware latch (refuse with `err=tripped` until `tb slot <n> off` or `tb safe` clears it) would protect any client.
10. **`tb safe` proves registers, not rails.** Its `restore` records read back the expanders and the mux; no record
    says the switched rails measured dead. A `live=<mask>` key at the end of `restore mux=...` would let any client
    trust `tb safe` alone. Until then this harness reads `tb ina all` itself.
11. **The shell's 64-byte input ring.** Both shells take `CONFIG_SHELL_BACKEND_SERIAL_RX_RING_BUFFER_SIZE`, 64 in the
    board build, with full-ring input dropped. This harness sends one line at a time; `host/tb_proto.py` `setup()`
    still sends its four setup lines back to back (re-read 2026-11-28). `=256` in the bring-up's `prj.conf` would
    remove the cliff for both. An analysis of Zephyr's source, not an observed loss.
12. **The A1 Hall coupon cannot identify itself to the bring-up firmware** (D1 meets SPEC §11 #18). The firmware
    reads only PCKD and `tb desc <n> write` writes only the test coupon's descriptor, while compiler v0's
    `make_eeprom.py` writes PCKC. So on bring-up day the Hall coupon reads `blank` (or `magic`), and this harness
    powers it with `nodesc` on its descriptor of record's 45 mA, a warning in every Hall run. A `tb desc <n> write
    hall` (or a raw write of an image the host built), or one format, would close it.
13. **No command reports INJ's or IRQ_N's level, and a failed loopback loses its count.** The INJ step can only
    read the lane path; the '165's INJ bit and IRQ_N through Q15 are visible only in the self-test's loopback, which
    then fails every pattern. And `src/coupon_test.c` keeps a step's keys in 160 bytes: with four failed patterns
    `failed=` is cut off, from the fifth `patterns=` too (37 bytes per failed pattern; the harness fails a loopback
    without its count, and the simulator reproduces the cut). A `tb slot <n> lines` record (CS, G, IRQ_N, the
    '165's last byte) would let the bench see
    both.
14. **The test coupon's lane tolerance is 1 % of full scale, not of the ratio.** `lib/tools/coupon_desc.py`
    `TEST_LANE_TOL = 0.01` ("1 % of the reference") becomes 10 000 ppm in `tb_lane_check()`, so AN0 (0.2) passes
    anywhere in 0.19-0.21, 5 % of its ratio, while PROTOCOL.md says "1 % of its ratio". The ladder itself is good to
    0.03-0.05 % (`descriptors/test-coupon.json`, ext.tolerance). This harness re-applies the firmware's figure; a
    tighter one needs the ADC's error budget, which was not re-read here.
15. **A turned coupon holds I2C4 through the mux** (risks.md EL-2, FW-7; the native_sim world models it as a NAK).
    After a descriptor read that got no answer, this harness sends `tb safe` (which pulses MUX_RST_N) before going
    on; the firmware's own slot-on path does not, and Zephyr's 500 ms I2C timeout still applies to the read.

16. **The firmware does not check that a slot's alert was re-set to its declaration** (bring-up firmware,
    `src/slot.c`). `tb_rail_on()` refuses a rail whose alert write fails ("no monitor, no rail"), but after the
    descriptor `tb_slot_on()` lowers the alert from the 250 mA discovery level to the declaration with
    `(void)tb_mon_set_alert(...)`. If that write fails, a coupon that draws more than it declares is turned off only
    at about 243 mA (95 % of the switch's minimum trip) or 205 mA (switch_limit). This harness now judges every
    enabled slot rail against its declaration itself, before the self-test and in `tb trips`.
17. **The classifier's live-off check is signed** (`lib/src/trip.c`: `current_ua > live_ua`). A current flowing
    backwards through an off rail's shunt (fed from the coupon side) is never `rail_live_off`, however large; only a
    voltage above 1 V is. This harness compares the magnitude (fault `live_off_ua`).
18. **The test coupon sheet quotes the firmware's live-off level as 500 mV** (`sheets/test_coupon.py`, the INJ
    back-feed note, "the firmware's 500 mV 'rail live while off' level"); `lib/src/trip.c` uses 1000 mV. The INJ
    back-feed it estimates (0.85-0.88 V) is therefore under the firmware's level, not over it; this harness flags it
    at 300 mV (`INJ_BACKFEED_MV`, a proposal).

## Review of 2026-11-28

An adversarial review ran every command above from a clean build and a clean tree, diffed the simulator against the
firmware's shell registration and against native_sim command by command, and broke the harness on purpose. What it
found and fixed:

* **A coupon that started to over-draw after slot on was never stopped by the harness itself.** Only the slot-on
  step judged a slot's current against its declaration; a later draw under the 205 mA switch_limit floor was left to
  the firmware's INA226 alert, which the simulator did not model, so the simulator let it through (FAIL, not
  STOPPED) while the firmware on native_sim stopped it. The simulator now models the alert, and the harness reads
  the slot's rails again before the self-test and judges `tb trips`' own per-rail readings.
* **A descriptor dump and a descriptor write powered the coupon without a reading.** The dump declared the 250 mA
  rule; both now use the coupon's descriptor of record and judge +3V3 while it is on, as does the NRST test.
* **A coupon declared with `--coupon` but not seated was silently left out** and the run could PASS on the other
  slots. It is now walked and fails.
* **The simulator crashed on non-numeric arguments, answered argument counts the shell rejects, accepted a rail
  already on, and lacked `ina_alert`, `ina_drv` and `desc_gline`**; it now follows `src/cmds.c` (tests hold its
  command table equal to the firmware's registration).
* Smaller: the stale-retry path restored the monitors' configuration before a stop reached `tb safe` (now none);
  +5V was judged against VSYS as read at the monitors step (now read again); S5's series resistance used 60 mOhm
  where SPEC §3.6 gives 45 mOhm; the host's PCKD reader skipped the G-line records' checks.

Checked and found right: every limit read from nets.py matches SPEC §3.1/§3.2/§3.4 (CAL, LSB, trip windows, budget
table), the classifier thresholds match `lib/src/trip.c` and `tb_rail_alert_ua()`, TP1 is +3V3 and TP15 is INJ in
the test coupon's netlist, the safety stop sends `tb safe` before anything else on every path tried, and no slot
after a stop is ever powered. st.com still fails (HTTP/2 INTERNAL_ERROR, HTTP/1.1 empty reply, LCSC's mirror 403,
2026-11-28), so the LDL1117's accuracy stays a proposal.

## Files

| File | What |
|---|---|
| `bench.py` | the command line |
| `tbbench/protocol.py` | PROTOCOL.md's line parser and the session (completion, timeouts and resync, the event ring) |
| `tbbench/transport.py` | pyserial, a native_sim process, the in-process simulator |
| `tbbench/limits.py` | every limit, with its source; board facts read from `nets.py`, the INJ figures from the test coupon's sheet, the stages of D1 and the descriptors of record |
| `tbbench/procedure.py` | the steps, the checks, the stop-on-danger path |
| `tbbench/desc_check.py` | the host's check of a dumped descriptor (PCKD, and PCKC through `keyboard/tools/coupon/descriptor.py`), and each coupon's descriptor of record through `descriptor.py` |
| `tbbench/report.py` | report.json, report.md, transcript.log |
| `tbbench/checklist.py` | the manual checklist |
| `tbbench/prompts.py` | prompts at the bench (console), scripted answers (tests); not `operator.py`, which would shadow the standard library module when `tbbench/` is on the path |
| `tbbench/simdev.py` | the simulated board, its faults, and what a person at the simulated bench does when asked |
| `tests/` | the procedure healthy and with every fault (`test_procedure.py`; the decisions of 2026-11-27 in `test_a1.py`), the simulator against PROTOCOL.md, the firmware's shell registration (`src/cmds.c`) and native_sim command by command, the parser against the firmware side's `tb_proto.py`, the firmware on native_sim, pyserial over a pty, the checklist's figures against nets.py and the sheets |
| `mutate.py` | the tests of the tests: each of 59 rules broken in a scratch copy must fail the suite |

Sources read for this directory: TI INA226 datasheet SBOS547C (revised August 2026, ti.com, SHA-256 c9b67f88...),
Diodes AP2112 DS39724 Rev. 2-2 (diodes.com, SHA-256 ef8d376f...), ModemManager `src/mm-filter.c` and
`src/mm-filter.h` (GitHub mirror of freedesktop's repository, main), ModemManager's "Port and device detection"
page, Zephyr v4.5.0's `subsys/shell/shell_cmds.c`, `subsys/shell/backends/Kconfig.backends`,
`subsys/shell/backends/shell_uart.c`, `include/zephyr/shell/shell_uart.h`, `drivers/sensor/ti/ina2xx/ina226.c`
(`INA226_DT_CAL`), `subsys/usb/device_next/class/usbd_cdc_acm.c` and `Kconfig.cdc_acm`, the `zephyr/.config` of a
`kbd_testbed_a` build of the bring-up (2026-11-27), and this repository's SPEC, nets.py, PROTOCOL.md, risks.md
(EL-2, EL-5, EL-6, FW-7), `sheets/test_coupon.py`, `sheets/coupon_hall.py`, `sheets/mb_power.py`, `sheets/mb_mcu.py`,
the test and Hall coupons' ORDER-NOTES, `keyboard/tools/coupon/descriptor.py` and its descriptors,
`keyboard/firmware/boards/gen_board.py` and the bring-up firmware's sources and sim world (re-read 2026-11-28).
