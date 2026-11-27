# bringup shell protocol, version 1

The machine-readable interface of the testbed bring-up firmware (`keyboard/firmware/bringup`), for a bench
harness and for people. **Status (2026-11-27): written against firmware that compiles for `kbd_testbed_a`; the
board does not exist, so no line below has come from hardware.** The same firmware runs on a simulated board
(native_sim, `sim/`), and `host/test_sim.py` drives it through this protocol, including a check that every record
it prints is listed on this page. The records are what the source prints (`src/cmds.c`, `src/coupon_test.c`,
`src/main.c`, `src/service.c`); where this page and the source disagree, the source is right and this page has a
bug. `host/tb_proto.py` is a parser and session driver a harness can use.

## Transport

Two shells run the same commands:

| Port | Where | Prompt | Notes |
|---|---|---|---|
| USART1, 115200 8N1 | J_SWD (STDC14) pins 13/14, an STLINK-V3's virtual COM port (SPEC §7.2) | `tb:uart> ` | Always there, also before USB works (bring-up steps 5 and 6). The boot report is printed here with `printk` |
| CDC ACM | the USB device on J1, VID:PID `1209:0001` (the pid.codes test PID: bench use only) | `tb:cdc> ` | Only once a host has enumerated the board |

A command is one line, `tb <command> [args]`, ended by `\r` or `\n`. Each shell also offers Zephyr's own commands
(`help`, `shell ...`, `i2c ...`, `kernel ...`); the harness uses only `tb`.

**Set the shell up first** (Zephyr v4.5.0 built-ins), on each port the harness drives:

```text
shell echo off
shell colors off
shell vt100 off
shell prompt off
```

Until then (and on a terminal that keeps them on) a prompt or VT100 escapes may precede a record on its line.

## Line format

Every machine-readable line starts with `@tb `:

```text
@tb <record> key=value key=value ...
```

* `<record>` is `[a-z_]+`. Keys are `[a-z0-9_]+`; a unit is a key suffix: `_ma`, `_ua`, `_mv`, `_uv`, `_ms`,
  `_us`, `_ppm`, `_mohm`, `_uohm`, `_uf`, `_pf`, `_uw`.
* A value is a decimal integer (may be negative), a hex integer with `0x`, a token `[A-Za-z0-9_.+/,-]+`, or, for
  `name=` only, a double-quoted string without quotes inside.
* Lines end with `\r\n`. **A record starts at the first `@tb ` in a line and runs to its end**; ignore every line
  without one (Zephyr log lines such as `[00:00:01.234,000] <wrn> ...`, help text). Strip `ESC [ ... letter`
  sequences first: an event printed while the shell shows its prompt is wrapped in them (`ESC[9D ESC[J`) until
  `shell vt100 off`, and the boot events come before any setup command. An event line can arrive in the middle of
  a command's output.
* New keys may be added at the end of a record in a later firmware; a parser must ignore keys it does not know.
  The protocol version is `proto=` in `tb info` and in the boot record.

## Completion

Every `tb` command prints its records and then exactly one completion line:

```text
@tb done cmd=<command> rc=<int> [err=<token>]
```

* `rc=0`: done. `rc<0`: a negative errno (`-1` EPERM, `-2` ENOENT, `-5` EIO, `-11` EAGAIN, `-13` EACCES,
  `-17` EEXIST, `-19` ENODEV, `-22` EINVAL, `-134` ENOTSUP, ...). `err=` says why in a token (table below); it is
  absent on success.
* A test command (`selftest`, `lanes`) runs to its end and reports its verdict in records; `rc` is `-5` (EIO) if
  any check failed.
* A command that the shell itself rejects (wrong argument count) prints Zephyr's usage text and **no** `@tb done`
  line: the harness should time out (2 s is plenty for everything but `selftest`, which takes about 1 s, and `desc
  write`, about 200 ms).

Error tokens:

| Token | Meaning |
|---|---|
| `usage` | arguments not understood |
| `unconfigured` | no host has configured the device (SPEC §3.2: no slot is powered before that), and no bench mode |
| `suspended` | the bus is suspended: every rail is off and none may come on |
| `over_rule` | the declared current exceeds the rail's coupon rule (250 mA on +3V3, 500 mA on +5V, S5 2 A; SPEC §4.9) |
| `over_vsys_budget` | base load + enabled rails + this one > the VSYS budget |
| `over_slot_ldo` | the 3.3 V slot rails together > the slot LDO's 300 mA (SPEC §3.2) |
| `order` | +5V_Sn while +3V3_Sn is off, or a peak check on a rail that is off |
| `already_on`, `bad_rail`, `bad_slot` | as named |
| `other_3v3_rails_on` | a +3V3 current-limit test needs every other 3.3 V slot rail off |
| `usb_configured` | bench mode asked for while a host has the device configured |
| `not_present` | PRESENT_N reads high: no coupon in the slot |
| `not_built` | the firmware was built without the option (bench mode: `CONFIG_BRINGUP_BENCH_SUPPLY`) |
| `fault_3v3`, `low_3v3`, `over_3v3`, `fault_5v`, `low_5v`, `over_5v` | a rail's check after its settling time failed: SLOT_FAULT_N (or S5_PG) asserted, the bus voltage under 3.0 V / 4.3 V, or the current at the switch's minimum trip. The rail was switched off again |
| `monitor`, `rail_3v3`, `rail_5v` | the rail's INA226 or its enable did not answer |
| `blank`, `crc`, `magic`, `version`, `length`, `record`, `value`, `duplicate`, `full`, `short` | the descriptor (format: `keyboard/firmware/lib/include/tb/desc.h`) |
| `desc_bus`, `bus_error` | the descriptor EEPROM did not answer |
| `slot_not_allowed`, `wide_coupon`, `over_3v3_rule`, `over_5v_rule` | the descriptor breaks a coupon rule for this slot |
| `slot_off` | `desc` needs the slot's +3V3 on |
| `already_written`, `verify` | `desc write`: a valid descriptor is there (add `force`), or the read-back differs |
| `not_tusb320` | something answered at 0x67 that is not a TUSB320 |
| `readback` | `safe`: an expander or the mux did not read back its restored state |
| `exp2_read` | U_EXP2 could not be read |
| `check` | `lanes`: a lane failed its check |
| `driver_not_ready`, `bad_config` | `ina drv`, `ina cfg` |
| `io`, `inval`, `perm`, `nodev`, `busy`, `acces`, `noent`, `timedout`, `again`, `notsup`, `nospc`, `exist`, `already`, `error` | the errno, when nothing more specific applies |

## Names

* **Slots** `1`-`5`. **Rails**: `+3V3_S1` ... `+3V3_S5`, `+5V_S1` ... `+5V_S5`, `+5V_KVM`. A command accepts them
  without the `+` and in any case (`3v3_s1`). Monitors also answer to `VSYS`, `+3V3_MCU`, `+3V3_USB` and to their
  address (`0x44`).
* **Rail masks** (`off_mask=`, `shed`, `on=`) are hex bit masks of rail ids: bit 0-4 = +3V3_S1-S5, bit 5-9 =
  +5V_S1-S5, bit 10 = +5V_KVM.
* **USB states**: `unconfigured`, `configured`, `suspended`. **Sources** (what U_CC reports): `pending` (not read
  yet: the Default level applies), `default`, `1.5A`, `3.0A`, `accessory`, `not_attached`, `unreadable`.

## Commands

| Command | Does | Records |
|---|---|---|
| `tb info` | firmware identity | `info` |
| `tb boot` | the boot report again | `boot`, `boot_exp` x3, `boot_mux`, `boot_ina` x13, `boot_restore` |
| `tb safe` | every rail off, bus switches open, slot lines high-impedance, mux pulsed and deselected, all read back (always allowed) | `restore` x4 |
| `tb usb` | USB state | `usb` |
| `tb cc` | read U_CC (never writes) | `cc` |
| `tb budget` | the VSYS budget | `budget`, `budget_rail` per enabled rail |
| `tb budget override <mA>\|off` | lower the budget (never raises it, SPEC §8.4) | as `tb budget`, plus `shed` if rails went off |
| `tb budget bench <mA>\|off` | bench-supply mode (only with `CONFIG_BRINGUP_BENCH_SUPPLY`; only while unconfigured; any USB reset or configuration ends it) | as above |
| `tb budget base <mA>` | set the base load the budget counts | as above |
| `tb ina [<rail>\|<0xaddr>\|all]` | read monitors | `ina` per monitor |
| `tb ina cfg <rail>\|all <avg> <vbus_us> <vsh_us> <mode>` | INA226 configuration (avg 1, 4, 16 ... 1024; times 140, 204, 332, 588, 1100, 2116, 4156, 8244; mode 0-7) | `ina_cfg` |
| `tb ina alert <rail> <mA>\|off` | a latching shunt over-limit alert | `ina_alert` |
| `tb ina drv <rail>` | the same monitor through Zephyr's `ti,ina226` driver, a cross-check | `ina_drv` |
| `tb exp` | the three TCA9535s, raw and by net | `exp` x3, `net` per used pin |
| `tb rail <rail> on <declared mA>` | one rail on (presence, budget, order checked), then read after the settling time. The slot's bus switch is opened first if it was closed (SPEC §3.5) and left open: `tb slot <n> on` closes it again | `ina`, `rail` |
| `tb rail <rail> off` | that rail off (a 3.3 V rail takes its slot's 5 V with it); the slot's bus switch opens first and stays open | `rail` |
| `tb slot` / `tb slot <n>` | slot status | `slot` per slot |
| `tb slot <n> on [probe=<mA>] [keep]` | SPEC §8.4's discovery: +3V3 declared at the 250 mA rule (or `probe=`, lower) until the descriptor is read, check, descriptor, its rules, its currents, +5V if it asks, then the bus switch. `keep` leaves +3V3 on when the descriptor is blank (to write one). On a slot already on it reports its state | `slot_on`, `slot` |
| `tb slot <n> on nodesc ma3=<mA> [ma5=<mA>]` | the same without a descriptor (a breakout on jumper leads), with the operator's declared currents | `slot_on`, `slot` |
| `tb slot <n> off` | the slot off | `slot` |
| `tb desc <n>` | read and parse the descriptor (+3V3 must be on) | `desc_hex` per 16 bytes, `desc` (or `desc status=<err>`), `desc_lane`, `desc_gline`, `desc_load` |
| `tb desc <n> write test [serial=<n>] [force]` | write the test coupon's descriptor (format 1.0, a proposal) and verify it | `desc`, ... |
| `tb lanes [<n>]` | every lane on its primary converter and on every other one that reaches its pin; VDDA from VREFINT | `vdda`, `lane` x4 per slot, `lane_alt` per alternate |
| `tb selftest <n> [loads] [climit] [all] [force]` | the test-coupon self-test (SPEC §10 step 7) | `step` per step, `selftest` |
| `tb trips [apply]` | classify a fresh snapshot of every rail and flag; `apply` also acts on it | `trips`, `trip` per finding, `trip_rail` per monitor read |
| `tb mon [period <ms>]` | the board service (poll period 10-2000 ms) | `mon` |
| `tb ev [<since>]` | replay the event ring from sequence number `since` | `ev` lines, `ev_dump` |
| `tb reboot` | `safe`, then a warm reboot (prints `done` first) | - |

## Records

Keys in order. `ok=1`/`0` is a pass/fail of that record's own check. In `boot`, `i2c1_bus=` and `i2c4_bus=` say how
each bus answered the first transfer after reset: `0` at once, `1` only after the firmware clocked it free with
Zephyr's bus recovery (a target left holding SDA low by a reset in the middle of a read), a negative errno if it
never answered (then nothing on that bus, the rail enables included, could be restored).

```text
@tb info fw=bringup proto=1 board=kbd_testbed_a map=<hash16> nets_rev=<rev> nets_date=<date> zephyr=<ver> uptime_ms=<n> bench_build=0|1 tim1=0|1 settle_ms=<n> period_ms=<n>
@tb boot fw=bringup board=kbd_testbed_a map=<hash16> nets_rev=<rev> zephyr=<ver> reset=<causes> snapshot=0|1 proto=1 i2c1_bus=<n> i2c4_bus=<n>
@tb boot_exp exp=1..3 addr=0x20.. err=<n> pre_in=0x.... pre_out=0x.... pre_cfg=0x.... por=0|1 driven=0x.... post_out=0x.... post_cfg=0x.... ok=0|1
@tb boot_mux err=<n> pre=0x.. post=0x.. post_err=<n>
@tb boot_ina addr=0x.. rail=<name> err=<n> mfr=0x5449 die=0x2260 cal=<n>
@tb boot_restore ok=0|1 err=<n> board_err=<n> lanes_err=<n>
@tb restore exp=1..3 out=0x.... cfg=0x.... ok=0|1
@tb restore mux=0x.. mux_err=<n> ok=0|1
@tb usb state=<usb> config=<n> speed=hs|fs|none
@tb cc present=1 id_ok=0|1 id=<16 hex> rev=0x.. csr08=0x.. csr09=0x.. csr0a=0x.. attached=not_attached|attached_src|attached_snk|accessory mode=0..3 source=<source> int=0|1 decided=0|1 usable=0|1
@tb cc present=0 decided=0|1 err=<errno token>
@tb budget usb=<usb> source=<source> may_power=0|1 limit_ma=<n> used_ma=<n> base_ma=<n> ldo_used_ma=<n> ldo_ma=300 max_ma=2800 override_ma=<n> bench_ma=<n> bench_build=0|1
@tb budget_rail rail=<rail> declared_ma=<n> seq=<n>
@tb shed mask=0x...
@tb ina addr=0x.. rail=<name> ok=1 current_ua=<n> shunt_current_ua=<n> bus_mv=<n> shunt_uv=<n> power_uw=<n> config=0x.... cal=<n> cal_expect=<n> lsb_ua=<n> shunt_uohm=<n> me=0x.... aff=0|1
@tb ina addr=0x.. rail=<name> ok=0 err=<errno token>
@tb ina_cfg target=<rail|all> config=0x.... period_us=<n>
@tb ina_alert rail=<name> limit_ma=<n> limit_raw=<n>
@tb ina_drv rail=<name> current_ua=<n> bus_mv=<n>
@tb exp exp=1..3 addr=0x.. ok=0|1 in=0x.... out=0x.... pol=0x.... cfg=0x....
@tb net name=<net> exp=1..3 pin=P00..P17 dir=in|out level=0|1
@tb rail rail=<rail> on=1 declared_ma=<n> fault=0|1
@tb rail rail=<rail> on=0 off_mask=0x...
@tb slot slot=<n> present=0|1 on3=0|1 on5=0|1 bus=0|1 desc=ok type=<type> rev=<A-Z> serial=<n> i3v3_ma=<n> i5v_ma=<n>
@tb slot slot=<n> present=0|1 on3=0|1 on5=0|1 bus=0|1 desc=none|bus_error|<desc error>
@tb slot_on slot=<n> on3=0|1 on5=0|1 bus=0|1 i3_ua=<n> v3_mv=<n> i5_ua=<n> v5_mv=<n> fault=0|1 desc=ok|none|bus_error|<desc error> ma3=<n> ma5=<n>
@tb desc_hex slot=<n> off=<n> data=<hex, up to 32 digits>
@tb desc slot=<n> status=ok len=<n> major=1 minor=<n> type=<type> rev=<A-Z> flags=0x.... serial=<n> i3v3_ma=<n> i5v_ma=<n> c3v3_uf=<n> c5v_uf=<n> name="<text>" slots=0x.. i2c=<n> spi=<n> cal=<n> unknown=<n>
@tb desc slot=<n> status=<desc error|bus_error>
@tb desc_lane slot=<n> lane=0..3 flags=0x.. r_src_ohm=<n> cload_pf=<n> expect_ppm=<n> tol_ppm=<n>
@tb desc_gline slot=<n> line=G0..G5 role=<n> arg=<n>
@tb desc_load slot=<n> load=0..3 line=G<k> rail=+3V3|+5V kind=cal|climit r_mohm=<n> slots=0x..
@tb vdda mv=<n> ok=0|1
@tb lane slot=<n> lane=0..3 adc=1|2|4 ch=<n> bits=14|12 code=<n> ratio_ppm=<n> state=low|mid|high powered=0|1
@tb lane slot=<n> lane=0..3 adc=<n> ch=<n> bits=<n> code=<n> ratio_ppm=<n> state=<..> expect_ppm=<n> err_ppm=<n> ok=0|1
@tb lane slot=<n> lane=<k> adc=<n> ch=<n> ok=0 err=<errno token>
@tb lane_alt slot=<n> lane=<k> adc=<n> ch=<n> bits=<n> code=<n> diff_ppm=<n> agree=0|1 powered=0|1
@tb step slot=<n> name=<step> result=pass|fail|skip [key=value ...]
@tb selftest slot=<n> result=pass|fail passed=<n> failed=<n> skipped=<n>
@tb trips exp2=0x.... on=0x... fault=0|1 alert=0|1 vsys_pg=0|1 s5_pg=0|1 absent=0x.. vsys_ua=<n> findings=<n> off=0x... shed_one=0|1 all_off=0|1 applied=0|1
@tb trip finding=<finding> rail=<rail|-> slot=<n> value=<n>
@tb trip_rail rail=<rail> on=0|1 current_ua=<n> bus_mv=<n> aff=0|1
@tb mon period_ms=<n> polls=<n> faults_handled=<n> ev_next=<n>
@tb ev_dump since=<n> next=<n> replayed=<n>
```

* `boot_exp`: `pre_*` are the expander's registers read **before** any driver touched them, so after an NRST with
  rails on, `por=0` and `driven` shows the output pins that were still driven; `post_*` are after the restore.
  The bring-up test of SPEC §10 step 5 ("the firmware restores them after an NRST reset with rails on") is: rails
  on, NRST, then `tb boot`: `reset=pin`, `por=0` on U_EXP1, `ok=1` on every expander and `boot_restore ok=1`.
* `reset=` is a comma list of `pin`, `software`, `brownout`, `por`, `watchdog`, `debug`, `security`, `lowpower`,
  `lockup`, `parity`, `pll`, `clock`, `hardware`, `user`, `temperature`, or `none` (Zephyr's hwinfo).
* **Discovery and the slot LDO:** with one coupon on, a second one's discovery at the 250 mA rule can exceed the
  slot LDO's 300 mA and is refused (`over_slot_ldo`); `probe=<mA>` declares less until the descriptor is read,
  and the monitor's alert, set just above the declaration, switches the slot off if the coupon draws more.
* `ina`: `current_ua` is the current register times the LSB (it depends on CAL); `shunt_current_ua` is the shunt
  register over the shunt resistance, independent of CAL. They agree within an LSB or two when CAL is right.
* `lane`: `ratio_ppm` is the code over 2^bits, a fraction of VREF+ (= VDDA, from the slot LDO). On the test coupon
  the lanes are 0.2/0.4/0.6/0.8 of the coupon's +3V3. `state` is `low` below 1 % of full scale, `high` above 99 %.
  An unpowered slot's lanes float on their 1 nF: their values mean nothing, and `lane_alt agree=` is only a check
  where `powered=1`.

### Self-test steps (`step name=`)

| Step | Keys | Pass when |
|---|---|---|
| `power` | `serial=` or `err=blank_descriptor\|slot_on\|not_a_test_coupon type=` | +3V3 on, a test coupon's descriptor (or `force`); +5V switched off for the loopback |
| `idle` | `i_ua= bus_mv=` | +3V3 at or above 3.0 V and under 10 mA |
| `lanes` | `an<k>_ppm= an<k>_err_ppm=` x4, `disagree=an<k>_adc<n> diff_ppm=` | each lane within the descriptor's tolerance (1 %) of its ratio; every other converter within 3000 ppm |
| `loopback` | `patterns= failed=`, per failed pattern `p<i>_rx= p<i>_want= p<i>_irq=` | every pattern reads back G0..G5, INJ = 0, SYNC and the MOSI echo; IRQ_N low exactly with G5 |
| `load3` | `i0_ua= i1_ua= v1_mv= expect_ua= rs_mohm= vref_mv=` | the G0 step within 5 % of V/30 ohm; `rs_mohm` is the slot's series resistance (SPEC §3.1), reported, not judged |
| `load5` | `i0_ua= i1_ua= v1_mv= expect_ua=` or `err=` | the G2 step within 5 % of V/30 ohm |
| `climit3` | `i_ua= bus_mv= trip_ma=<min>/<typ>/<max> fault= cleared=` or `err=` | the current inside the trip window (± 3 %), SLOT_FAULT_N seen and cleared |
| `climit5` | as `climit3`, or `reason=never_on_s5\|5v_off` (skip) | as `climit3` on the 5 V switch (S1-S4 only) |

`load3`/`load5` run with `loads` or `all`, `climit3`/`climit5` with `climit` or `all`. A `power` failure ends the
test. The `climit` steps drive a TPS2553 into its limit for 15 ms (about 0.5 W in the switch for G1, 1.8 W for G3,
*estimate*); run them on a bench, one slot at a time.

## Events

The board service posts asynchronous events to a ring (64 entries) and a printer copies each to both shells:

```text
@tb ev seq=<n> t_ms=<uptime> kind=<kind> key=value ...
```

`seq` increases by one per event from 1 at boot. **A shell may miss an event line** (the printer gives up a line
when the shell is busy, and an unread CDC port blocks it); `tb ev <since>` replays what the ring still holds, so
a harness tracks the last `seq` it saw and asks for the rest after each command.

| `kind=` | Keys | When |
|---|---|---|
| `boot` | `restore_ok=` | once, after main() |
| `usb` | `event=reset\|configured\|suspend\|resume\|disconnected value= state=` | every USB state change |
| `budget` | `limit_ma= used_ma= source= usb=` | the VSYS budget (and INA226 0x40's alert) changed |
| `budget_set` | `what=override\|bench\|base ma= shed=` | an operator setting |
| `cc` | `source= ok= csr08= csr09=` | U_CC decided (at most 200 ms after boot) or its advertisement changed |
| `present` | `slot= present=` | a PRESENT_N edge |
| `rail_on` | `rail= declared_ma=` | a rail enabled |
| `rail_off` | `rail= reason=operator\|trip\|usb\|source\|override\|bench\|base\|vsys_over_budget\|vsys_pg_low\|3v3_check\|5v_check\|no_descriptor\|selftest\|<rule>` | a rail disabled, and why |
| `slot` | `slot= on3= on5= bus= desc=` | `slot on` finished |
| `trip` | `finding= rail= slot= value=` | the classifier found something (the same finding on the same rail at most every 5 s) |
| `restore` | `ok=` | `tb safe` |
| `desc_written` | `slot= serial=` | `desc write` verified |
| `selftest` | `slot= result= failed=` | a self-test ended |
| `error` | `what=exp2_read` | U_EXP2 unreadable (at most every 5 s) |

Findings (`trip finding=`, `tb/trip.h`): `vsys_pg_low` (every rail off), `coupon_removed`, `s5_breaker`,
`monitor_lost`, `switch_limit`, `fault_kvm`, `fault_unattributed` (every TPS2553 rail off), `alert`,
`alert_unattributed`, `vsys_over` (the budget's next victim off: S5 first), `rail_dead`, `rail_sag` (reported
only), `rail_live_off` (reported only: an off rail that reads a voltage or a current).

## A bench session (illustrative, not a recorded run)

```text
> tb info
@tb info fw=bringup proto=1 board=kbd_testbed_a map=... nets_rev=A-testbed ...
@tb done cmd=info rc=0
> tb budget
@tb budget usb=configured source=3.0A may_power=1 limit_ma=2800 used_ma=45 ...
@tb done cmd=budget rc=0
> tb slot 1 on
@tb ev seq=7 t_ms=5210 kind=rail_on rail=+3V3_S1 declared_ma=250
@tb slot_on slot=1 on3=1 on5=1 bus=1 i3_ua=2950 v3_mv=3296 i5_ua=12 v5_mv=4980 fault=0 desc=ok ma3=120 ma5=170
@tb slot slot=1 present=1 on3=1 on5=1 bus=1 desc=ok type=test rev=A serial=7 i3v3_ma=120 i5v_ma=170
@tb done cmd=slot rc=0
> tb selftest 1 all
@tb step slot=1 name=power result=pass serial=7
...
@tb selftest slot=1 result=pass passed=8 failed=0 skipped=0
@tb done cmd=selftest rc=0
```

The numbers above are placeholders that show the format; none was measured.
