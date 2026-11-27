# hid8k: the 8 kHz HID proof on the NUCLEO-U5A5ZJ-Q

> **Status (2026-11-27): written and compiled, not run.** The firmware builds for `nucleo_u5a5zj_q` with
> Zephyr v4.5.0 (commit 41d10b5) and Ubuntu's arm-none-eabi GCC 13.2.1 (`ZEPHYR_TOOLCHAIN_VARIANT=gnuarmemb`),
> **not** the Zephyr SDK 1.0.1 that v4.5.0 expects. It has **not run on hardware, and nothing has been measured**:
> no enumeration, no report rate, no jitter, no submit cost on the board. What has run is a **USB simulation**: the
> firmware's own USB code on Zephyr's native_sim against Zephyr's own USB host stack on its virtual bus, in
> simulated time ([USB simulation](#usb-simulation-native-sim): every check passes in its three variants, three
> known issues found). It proves the descriptors, the pacing logic, the report layout, the CDC console and the
> recovery paths as code; it says nothing about the STM32's timing, its USB driver or its PHY, and a simulated
> 8000 reports/s is not evidence that the board reaches it. The host tool's analysis has now read the
> simulation's real report stream as well as its synthetic tests. Every other figure below is either a build
> output or *arithmetic*, and is labelled as such.

## What it proves, and why

The rev A testbed's MCU, the STM32U5A5, was chosen on paper with two conditions attached before its schematic is
committed ([SPEC §1](../../hardware/design/SPEC.md#_1-purpose-and-what-rev-a-must-prove),
[mcu.md](../../docs/mcu.md#conditions-before-the-schematic-is-committed)). This is the firmware for the second:

> 8 kHz HID is proven on the NUCLEO-U5A5ZJ-Q with Zephyr's `usbd`: `in-polling-period-us = <125>`, bInterval 1,
> report rate and jitter measured for at least 10 minutes on Windows and Linux with CDC logging active.

Nobody has published 8 kHz HID on Zephyr's STM32 USB device driver (`udc_stm32`), and it is the first platform
risk in [mcu.md's bring-up risks](../../docs/mcu.md#bring-up-risks). If it fails, the NXP i.MX RT1021 is the
fallback and the SPEC is redrawn for it. The test also measures what each `hid_device_submit_report` call costs,
which sizes the last 25 µs of the testbed's 125 µs frame
([SPEC §6.3](../../hardware/design/SPEC.md#_6-3-per-step-arithmetic-estimate)), and it is bring-up step 2 of
[SPEC §10](../../hardware/design/SPEC.md#_10-bring-up-order). The USB contract it follows is
[SPEC §8.2](../../hardware/design/SPEC.md#_8-2-usb-at-8-khz). It does not measure press-to-report latency: that is
the latency rig's job ([concept §4.2](../../docs/concept.md#_4-2-latency-and-battery-gates)).

## What the firmware does

**USB device** (`src/usb_device.c`, after Zephyr's `samples/subsys/usb/common/sample_usbd_init.c`): the new device
stack (`device_next`) on `usbotg_hs` with its embedded high-speed PHY, a high-speed configuration (the one under
test) and the full-speed one the stack also builds, self-powered, bMaxPower 100 mA (a declaration, not a
measurement). Two functions:

| Function | Endpoints | Purpose |
|---|---|---|
| HID, one interface, no boot protocol | interrupt IN, wMaxPacketSize 64, **bInterval 1** at high speed (125 µs; 1 ms at full speed) | report ID 1: NKRO keyboard; report ID 2: vendor stats (usage page 0xFF00) |
| CDC ACM (two interfaces under an IAD) | notification IN, bulk IN/OUT | the console: one stats line per second, commands in |

The devicetree nodes are in `dts/hid8k_usb.dtsi`, which `boards/nucleo_u5a5zj_q.overlay` includes (and so does the
simulation, so both test the same node): `in-polling-period-us = <125>`, which `usbd_hid` encodes as
`USB_HS_INT_EP_INTERVAL(125)` = 1. `in-report-size = <64>` keeps wMaxPacketSize at 64, so `usbd_hid` uses its
simple interface with no alternate setting. The built descriptor bytes, read back from the ELF
(`keyboard/firmware/hid8k/sim/usb_descriptors_elf.py` on `keyboard/firmware/build/hid8k/zephyr/zephyr.elf`), are
`07 05 81 03 40 00 01` for the high-speed interrupt endpoint (address 0x81 before the stack assigns it, interrupt,
64 bytes, bInterval 1), and the report descriptor is 56 bytes. In the simulation the stack assigns the HID
endpoint 0x83 (the CDC ACM function, interfaces 0 and 1, takes 0x81 and 0x82, and the HID interface is number 2);
the STM32 driver's assignment is not checked.

**The keyboard report (ID 1)** is a modifier byte and a bitmap of usages 0x00–0xDF (30 bytes with the ID). It is
sent only when the Nucleo's blue USER button (`sw0`) changes state, and it presses **F24** (usage 0x73), a key
Windows and Linux accept and nothing acts on by default, so a 10-minute run never types into the host. Both
collections share the one interrupt endpoint, so a keyboard report takes the place of one stats report.

**The stats report (ID 2)**, 64 bytes on the wire including the ID, little-endian, layout in `src/hid8k_report.h`
(mirrored by `host/hid8k_analysis.py`, and a test checks they agree). The vendor collection is what hidapi opens:
on Windows the keyboard collection is held exclusively by the OS.

| Offset | Field | Meaning |
|---|---|---|
| 0 | report ID, format, flags, depth | 2; format 1; flags: frame number valid, heavy CDC mode, high speed; reports kept queued |
| 4 | `seq` | sequence number of this report; counts **every** report on the IN endpoint (IDs 1 and 2) |
| 8 | `t_submit` | DWT cycle count just before this report's `hid_device_submit_report` call |
| 12, 16 | `done_seq`, `t_done` | the latest completed report when this one was built, and the cycle count in its `input_report_done` callback |
| 20 | `submit_cost` | cycles taken by the previous `hid_device_submit_report` call |
| 24, 28 | `refused`, `busy` | submit calls that returned an error; times a submit was wanted but not made, because no report buffer was free or the bus was still marked suspended (both since boot) |
| 32 | `late` | completion intervals above 1.5 × 125 µs = 187.5 µs, since boot |
| 36 | `kbd_count` | keyboard reports sent, since boot (so the host can tell them from lost reports) |
| 40 | `cpu_hz` | the cycle counter's rate: 160 MHz on the Nucleo |
| 44, 46 | `fn_done`, `fn_submit` | the (micro)frame number at that completion and at this submit: only with `CONFIG_HID8K_FRAME_NUMBER=y`, else 0 |
| 48 | `max_interval` | the longest completion interval since the last `reset` command, cycles |
| 52 | `uptime_ms` | `k_uptime_get_32()` |
| 56, 60 | `cdc_bytes`, `cdc_dropped` | bytes queued to the CDC console, and dropped because its ring was full, since boot |

**The SOF or microframe number is not exposed by the stack.** The SOF event carries no number
(`udc_submit_sof_event()`, `drivers/usb/udc/udc_common.h:147-158`), the class callback `hid_device_ops.sof` takes
only the device (`include/zephyr/usb/class/usbd_hid.h:207`), and SOF events need `CONFIG_UDC_ENABLE_SOF`, whose
help warns of "a very high CPU load on high-speed controllers". The firmware therefore leaves `fn_done`/`fn_submit`
at 0. An opt-in, `CONFIG_HID8K_FRAME_NUMBER=y`, reads the OTG_HS core's `DSTS.FNSOF` field directly (outside the
stack, read-only) in the completion callback; the host tool then counts microframes that had no completion. Whether
that 14-bit field counts 125 µs microframes or 1 ms frames at high speed is not checked against RM0456, so the tool
decides from its measured rate (about 8000/s or 1000/s) and only counts misses in the first case.

### Why the stream is paced from `input_report_done`, not from a timer

The firmware submits reports from `usbd_hid`'s `input_report_done` callback and keeps **two** queued
(`CONFIG_HID8K_QUEUE_DEPTH`): one armed in the controller, one waiting behind it. Each completion means the host
took a report, so the callback hands one back.

* **It follows the host's clock.** The host polls the endpoint once per microframe on its own crystal. A device
  timer at 8 kHz runs on the Nucleo's crystal; the two differ by tens of ppm (*arithmetic*: 100 ppm is 0.8 reports
  per second), so a timer-paced stream either leaves microframes empty or backs up the queue, and a queue that
  slowly fills is latency that grows. A completion-paced stream cannot drift: it submits exactly as fast as the host
  takes.
* **The queue never runs dry or overflows.** `usbd_hid` sends from the caller's buffer and takes a `net_buf` from a
  small per-instance pool (`CONFIG_USBD_HID_IN_BUF_COUNT`, default 2); submitting faster than the bus drains returns
  `-ENOMEM`. Topping up on completion holds the number queued constant.
* **The second report takes the class callback and the submit out of the critical path.** When a transfer
  completes, the STM32 UDC driver's thread arms the next queued buffer itself (`handle_msg_data_in()`,
  `drivers/usb/udc/udc_stm32.c:774-828`) before the USB stack thread runs the class callback. With one report queued,
  the interrupt, the driver thread, the stack thread and the submit would all have to fit before the host's next
  poll; with two, the interrupt and the driver thread must. That thread still has to get the CPU: it and the stack
  thread are both cooperative, `K_PRIO_COOP(8)` (`udc_stm32.c:1693-1696`, `usbd_core.c:284-288`), so it waits for
  whatever cooperative thread is running when the interrupt fires to block or yield: the stack thread finishing a
  callback, or a system work queue item such as the CDC console's callback (cooperative at -1; the queue gives up
  the CPU after each item, `kernel/work.c:786-797`). Those runs are short by design (the CDC callback copies at most
  `CONFIG_HID8K_CDC_CHUNK` bytes), but their length on this chip is not measured: it is part of what the test
  finds out.
* **Completions are the delivered count.** An IN transfer completes on the device when the host controller
  acknowledges the data, so the device's completion count is the number of reports the host took off the bus.

The cost: the data in each report is about two completions old (250 µs) when it goes out. That does not matter for
this test. The testbed's scan engine locks its frame to SOF ([SPEC §6.1](../../hardware/design/SPEC.md#_6-1-the-engine-proposal))
and will want the freshest data in the report, which is a design question for later, not this proof.

**Suspend, and the refill kick.** While the stack has the bus marked suspended, `usbd_ep_enqueue()` refuses every IN
transfer with `-EPERM` (`subsys/usb/device_next/usbd_endpoint.c:145-149`), and the stack handles every completed
transfer on its list before the event it takes off its queue (`usbd_event_handler()`, `usbd_core.c:153-163`), so a
completion can be handled before a `RESUME` that came first. A refused submit is
normally retried at the next completion; if none is left outstanding, nothing would ever retry it and the stream
would stop for good. So the firmware does not submit while suspended (it counts that as `busy`), and a small work item, the **refill kick**,
restarts the queue when the stream is configured, not suspended and has nothing outstanding. The USB `RESUME`
message and the stats thread (once per log period) ask for it. It never adds to a queue that completions are
keeping full. The stats line counts the times it found the queue empty (`stall=`); in a good run that stays 0. A host
that stops polling without suspending (a closed reader on Linux, a slower bInterval) leaves two reports queued and
the stream simply resumes when polling does.

`usbd_hid` calls `input_report_done` *before* it frees the completed transfer's `net_buf`
(`subsys/usb/device_next/class/usbd_hid.c:135-143`), so the pool needs one buffer more than the reports kept queued:
`prj.conf` sets `CONFIG_USBD_HID_IN_BUF_COUNT=4` for a depth of 2, and a build assertion checks it.

### Firmware-side statistics and the CDC console

The callback also measures each completion-to-completion interval in DWT cycles and keeps a histogram of 12.5 µs
buckets from 0 to 500 µs plus an overflow bucket. Once per second (`CONFIG_HID8K_LOG_PERIOD_MS`) the stats thread
prints a line on the CDC ACM console, for example (format only, not a measurement):

```text
hid8k t=42s usb=cfg hs rate=8000.0/s int_us=118.4/125.0/131.6 late=0 hist[<100:0 100-150:7999 150-187.5:0 187.5-250:0 >=250:0] submit_cyc=402/431/1214 refused=0 busy=0 err=0 kbd=0 out=2 stall=0 cdc=normal q=12345 drop=0 pend=0
```

`rate` is completions per second on the device clock; `int_us` the interval min/avg/max; `late` the intervals
above 187.5 µs; `hist` the window's histogram in five bands; `submit_cyc` the submit cost min/avg/max in cycles;
`out` the reports queued on the endpoint (2 while streaming); `stall` the refill kicks that found the queue empty,
since boot; `q`, `drop` and `pend` the CDC bytes queued, dropped and waiting. The console drops whole lines when its
ring is full, never part of one. `NO-COMPLETIONS` at the end means the interface is configured but nothing completed
in the window (the host stopped polling, the bus is suspended, or the pipeline stalled). `CYCCNT-MISMATCH` means
the window measured by the DWT cycle counter disagrees with the kernel's uptime by more than 2 ms + 1 %: the counter
stopped or `cpu_hz` is wrong, and the timestamps of that window cannot be trusted. (The firmware checks at start-up
that the DWT has a cycle counter, and sets its enable bits again every period, in case a debug probe rewrote
`DEMCR`.) Every 10 s (`CONFIG_HID8K_HIST_PERIOD_S`) it also prints the cumulative histogram:
`hid8k hist since reset: n=... late=... max_us=... buckets(us:count) 112.5:... 125.0:...`.

Commands, one per line on the CDC console: `heavy` (start the filler traffic), `normal` (stop it), `reset` (clear
the cumulative histogram and the maximum), `hist` (print the histogram now), `help`. In **heavy** mode the firmware
also writes `CONFIG_HID8K_CDC_HEAVY_BPS` (default 100,000) bytes per second of numbered 64-byte filler lines
(`~fill 0000002a ......`), to load the CDC path while the HID stream runs. A line longer than 32 characters is never
taken as a command, so an echoing terminal cannot trigger one.

Boot messages, USB state changes, the stack's warnings and errors, and (at most once a second) a copy of the stats
line go to the board console, USART1 at 115200 8N1, which the Zephyr board documentation assigns to the console;
on this Nucleo it reaches the host through the ST-LINK's virtual COM port (the usual Nucleo-144 wiring, not checked
against ST's user manual here). So the ST-LINK console still reports if the USB link under test fails.

### Configuration

| Kconfig | Default | |
|---|---|---|
| `CONFIG_HID8K_USB_VID` / `_PID` | 0x1209 / 0x0001 | the [pid.codes](https://pid.codes/1209/0001/) test PID: for private testing only, not unique, never for a device that is sold or shipped. **Bench use only** |
| `CONFIG_HID8K_QUEUE_DEPTH` | 2 | reports kept queued (1–4); `CONFIG_USBD_HID_IN_BUF_COUNT` must be at least this + 1 |
| `CONFIG_HID8K_LOG_PERIOD_MS` | 1000 | stats line period (10–20,000 ms): shorter means more CDC traffic |
| `CONFIG_HID8K_HIST_PERIOD_S` | 10 | cumulative histogram period; 0 = only on `hist` |
| `CONFIG_HID8K_CDC_HEAVY_BPS` | 100000 | filler rate in heavy mode, bytes/s |
| `CONFIG_HID8K_CDC_HEAVY_AT_BOOT` | n | start in heavy mode |
| `CONFIG_HID8K_CDC_RING_SIZE` | 8192 | CDC transmit ring |
| `CONFIG_HID8K_CDC_CHUNK` | 512 | most bytes handed to the CDC class per callback run (that work queue is cooperative, so this bounds how long it can hold off the USB threads) |
| `CONFIG_HID8K_FRAME_NUMBER` | n | read `DSTS.FNSOF` directly, outside the stack (above) |
| `CONFIG_HID8K_PHY_TUNER2` | n | write the HS PHY's recommended `SYSCFG_OTGHSPHYTUNER2` values before `usbd_init()` (below) |
| `CONFIG_HID8K_MIRROR_TO_CONSOLE` | y | copy the stats line to the ST-LINK console, at most once a second |

**PHY tuning (`CONFIG_HID8K_PHY_TUNER2`).** RM0456 Rev 7 §15.2.3 (read in a third-party transcription, not ST's PDF;
[SPEC §8.2](../../hardware/design/SPEC.md#_8-2-usb-at-8-khz)) brings the HS PHY up as: its clocks on, CLKSEL, then
`SYSCFG_OTGHSPHYTUNER2` with COMPDISTUNE = 010 (disconnect threshold +5.9 %) and SQRXTUNE = 000 (squelch +15 %),
the values the RM and ST's LL header call recommended, then EN. Zephyr v4.5.0's `stm32_u5otghs_phy_enable()`
(`drivers/usb/common/stm32/phy_u5otghs.c:56-120`), which `udc_stm32_init()` calls from `usbd_init()`, writes CLKSEL
and EN but never TUNER2, and turns the PHY clock on only after EN. With the option, `main()` writes the two fields
through `LL_SYSCFG_SetOTGPHYDisconnectThresholdAdjustment()` and `LL_SYSCFG_SetOTGPHYSquelchThresholdAdjustment()`
(read-modify-write: TUNER2's bits 31:15 are reserved) before `usbd_init()`. It is off by default, so the default
build is what Zephyr does upstream. Either way the board console prints the register after `usbd_init()`, for
example `TUNER2 = 0x81cd06b1 (COMPDISTUNE 1, SQRXTUNE 3; Zephyr default, not written)` if the RM's reset value
0x81CD06B1 holds. Bring-up runs both (Test procedure, step 6); whether either matters on the bench is not known.

`prj.conf` and `boards/nucleo_u5a5zj_q.conf` also raise two event queues from their defaults,
`CONFIG_UDC_STM32_MAX_QMESSAGES` (8 to 32, in the board file, so `prj.conf` also builds for the simulation) and
`CONFIG_USBD_MAX_UDC_MSG` (10 to 32). If the STM32 driver's queue overruns, it drops a DataIn event
(`udc_stm32.c:759-772`, "UDC Message queue overrun"), which would leave the HID endpoint waiting for ever. The stack's
own queue keeps completed transfers on a list (`usbd_core.c:39-47`), so an overrun there delays a completion but does
not lose it; it can still lose a bus event such as a reset. Margin, not a measured need; a run with the defaults is a
useful extra.

## The bench

* A **NUCLEO-U5A5ZJ-Q**.
* A USB cable from the **ST-LINK** connector to the host: power, flashing and the board console.
* A second cable from the board's **user USB-C** connector (the OTG_HS port, PA11/PA12) to a **high-speed** port on
  the host: a USB 2.0 or USB 3 port on the machine itself, not through a full-speed hub, a KVM or a dock you have
  not checked. (Zephyr's board page lists "USB Type-C Sink device FS" among the features, but its "Using USB"
  section says high speed needs the HSE, which this Nucleo has with its jumpers set, and the board's devicetree
  enables the high-speed controller and PHY on PA11/PA12, with the PHY clocked from the 16 MHz HSE: `doc/index.rst`,
  "Using USB"; `drivers/usb/common/stm32/phy_u5otghs.c:80`. The enumeration speed the tool reports settles it.)
* A **Windows** 10 or 11 PC and a **Linux** PC, each with Python 3.9 or later.

## Build

From a Zephyr v4.5.0 workspace (`west init -m https://github.com/zephyrproject-rtos/zephyr --mr v4.5.0`, then
`west update`; this build needed only the `cmsis`, `cmsis_6`, `hal_stm32` and `picolibc` modules):

```sh
export ZEPHYR_BASE=/path/to/zephyrproject/zephyr
# The Zephyr SDK 1.0.1 is what v4.5.0 expects. This build used Ubuntu's gcc-arm-none-eabi instead:
export ZEPHYR_TOOLCHAIN_VARIANT=gnuarmemb GNUARMEMB_TOOLCHAIN_PATH=/usr
west build -p always -b nucleo_u5a5zj_q keyboard/firmware/hid8k -d keyboard/firmware/build/hid8k
# variants, for example the frame-number opt-in:
west build -p always -b nucleo_u5a5zj_q keyboard/firmware/hid8k -d keyboard/firmware/build/hid8k-fn \
  -- -DCONFIG_HID8K_FRAME_NUMBER=y
```

Build result (2026-11-27, the default configuration, with the TUNER2 option added): **FLASH 78,660 B** (1.88 % of
4 MB), **RAM 28,896 B** (1.13 % of 2,496 KB); `arm-none-eabi-size`: text 76,972, data 1,688, bss 27,175. Variants
with `CONFIG_HID8K_FRAME_NUMBER=y`, `CONFIG_HID8K_CDC_HEAVY_AT_BOOT=y` and `CONFIG_HID8K_LOG_PERIOD_MS=10`, and with
`CONFIG_HID8K_PHY_TUNER2=y` and `CONFIG_HID8K_FRAME_NUMBER=y` (FLASH 78,744 B), also build.
The app's own sources build with `-Wextra -Wshadow` and give no warnings. The only warning in the build is the toolchain's: `implicit declaration of function '__rbit'` from
`include/zephyr/arch/arm/bit_rev.h:38`, which Ubuntu's GCC 13.2 with picolibc raises in every file (Zephyr's
`samples/hello_world` shows it too). `-Wno-type-limits` is there because `-Wextra` would otherwise warn inside
Zephyr's own `include/zephyr/usb/usbd_msg.h:107`.

## Flash

The image is linked at 0x0800 0000 (no bootloader).

* `west flash -d keyboard/firmware/build/hid8k` uses the board's default runner, STM32CubeProgrammer, through the
  on-board ST-LINK (install STM32CubeProgrammer first). `--runner openocd` or `--runner pyocd` also work with the
  board's runner settings.
* Or open `keyboard/firmware/build/hid8k/zephyr/zephyr.hex` in STM32CubeProgrammer and program it over the ST-LINK.

After a reset the board console prints `hid8k: 8 kHz HID proof, USB 1209:0001 ...` and, once the host configures
the device, `hid8k: configuration 1, high speed`.

## Host setup

The host tool is `host/hid8k_measure.py` (Python 3). `host/hid8k_analysis.py` holds the analysis as pure functions;
`python3 -m pytest keyboard/firmware/hid8k/host -q` runs their tests.

**Windows.** `py -m pip install hidapi pyserial` (`hidapi` is cython-hidapi and bundles the hidapi library; the `hid`
package also works but needs the hidapi DLL installed). No driver: Windows binds its own HID and CDC ACM
(`usbser.sys`) drivers. The CDC console is the "USB Serial Device (COMn)" in Device Manager, not the
"STMicroelectronics STLink Virtual COM Port". To read the speed and bInterval, use a descriptor viewer such as
USB Device Tree Viewer: "Device Bus Speed: High" and, on the HID interrupt IN endpoint, `bInterval 0x01`.

**Linux.** The tool reads `/dev/hidrawN` directly by default (`--backend hidraw`), so it needs no HID package;
`pip install pyserial` for `--cdc`. Give your user access with the udev rule in `host/70-hid8k.rules`:

```sh
sudo cp keyboard/firmware/hid8k/host/70-hid8k.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger    # then replug the user USB cable
```

It grants hidraw, USB and tty access for 1209:0001 to the logged-in user (`TAG+="uaccess"`) and tells ModemManager to
leave the CDC port alone. Check that `cat /sys/module/usbhid/parameters/kbpoll` prints 0: usbhid replaces the
polling interval of any HID interface whose first collection is a keyboard with `kbpoll` when it is set
(`drivers/hid/usbhid/hid-core.c`, `usbhid_start()`, `case HID_GD_KEYBOARD`), and hid8k's first collection is its
keyboard; some gaming-keyboard guides set it. 1209:0001 is a shared test PID, so the rule also covers other test
devices that use it.
`ls -l /dev/serial/by-id/` tells the hid8k console (`...hid8k...-if01`) from the ST-LINK's. On Linux the tool also
reads the bus speed and the HID endpoint's bInterval from sysfs and prints them; `lsusb -v -d 1209:0001` shows them
too.

## Test procedure

Four runs of 10 minutes each, and the operator does not touch the board during them:

| Run | Host | CDC |
|---|---|---|
| 1 | Windows | normal: the stats line once a second |
| 2 | Windows | heavy: plus 100 kB/s of filler |
| 3 | Linux | normal |
| 4 | Linux | heavy |

1. Flash, connect both cables, and check the board console shows `configuration 1, high speed`.
2. Once, before the runs: press the USER button and check the host sees F24 (Linux: `evtest`; Windows: any key-event
   viewer), and that the CDC console prints stats lines (`kbd=1` after a press).
3. List the device: `python3 hid8k_measure.py --list`.
4. Run, from `keyboard/firmware/hid8k/host`:

   ```sh
   # Windows (PowerShell), run 1 and run 2
   py hid8k_measure.py --cdc COM7 --cdc-mode normal --label "win11, rear USB3 port" --out win_normal.json
   py hid8k_measure.py --cdc COM7 --cdc-mode heavy  --label "win11, rear USB3 port" --out win_heavy.json
   # Linux, run 3 and run 4
   python3 hid8k_measure.py --cdc /dev/ttyACM1 --cdc-mode normal --label "ubuntu 24.04, xhci" --out linux_normal.json
   python3 hid8k_measure.py --cdc /dev/ttyACM1 --cdc-mode heavy  --label "ubuntu 24.04, xhci" --out linux_heavy.json
   ```

   `--cdc` holds the CDC console open in a separate process for the whole run, sends `reset` and the mode, logs
   everything the firmware prints to `<out>_cdc.log`, and counts the stats lines it read. Without `--cdc`, keep a
   terminal logging the CDC console instead (on Linux run `stty -F /dev/ttyACM1 raw -echo` first, so the tty does
   not echo the output back); the tool then marks CDC as not checked.
5. Keep, per run: the JSON (it holds the verdict, every statistic and the criteria), the CDC log, the board console
   log, the host's OS and version, the USB port and controller, and the firmware's git commit.
6. Optional extras: the same with `CONFIG_HID8K_PHY_TUNER2=y` (the RM's PHY tuning, SPEC §8.2; record the TUNER2
   line from the board console), with `CONFIG_HID8K_FRAME_NUMBER=y` (exact count of empty microframes), with
   `CONFIG_UDC_STM32_MAX_QMESSAGES` and `CONFIG_USBD_MAX_UDC_MSG` back at their defaults, and with
   `CONFIG_HID8K_LOG_PERIOD_MS=10` (100 stats lines a second).

The tool reads for `--duration` (default 600) seconds after `--warmup` (default 1 s, which drops the reports that
sat queued before the reader opened), plus one second of margin. It stores about 35 bytes per report (about 170 MB
for 10 minutes, *arithmetic* and a synthetic benchmark) and analyses afterwards (about 4 s for 4.8 million synthetic
reports). `--csv` also writes every report for offline analysis.

**Timing caveat.** The tool's host-side arrival intervals are user-space timestamps taken when a read returns. The
host controller, its driver, the HID class driver and the scheduler batch and delay reports, so they are **not bus
timing**, and the summary says so. For bus-level truth, capture with usbmon and Wireshark on Linux
(`sudo modprobe usbmon`, then capture `usbmonN` for the device's bus; those timestamps are the kernel's URB
completions, closer to the bus but still software) or USBPcap on Windows, and for the bus itself a USB analyser
(the high-speed sniffers in [concept §4.2](../../docs/concept.md#_4-2-latency-and-battery-gates)).

## Pass criteria

A run **passes** when all of these hold (`host/hid8k_analysis.py`, `Criteria`; the limits can be changed on the
command line for experiments, not for the gate):

| # | Criterion | Limit | Why |
|---|---|---|---|
| 1 | run length after warm-up | ≥ 600 s | condition 2's "at least 10 minutes"; shorter gives INCOMPLETE |
| 2 | high speed in every report | yes | at full speed the interval is 1 ms |
| 3 | completions per second on the device clock, averaged over the run | ≥ 7,990 | at most 10 empty microframes per second (0.125 %) |
| 4 | stats reports received per second on the host clock | ≥ 7,990 | the host delivered them, not only the bus |
| 5 | sequence gaps, duplicates, out-of-order reports | 0, 0, 0 | every report the device sent reached the reader once, in order |
| 6 | device-side completion interval, 99.9th percentile | ≤ 250 µs (2 × 125 µs) | jitter bound |
| 7 | `refused` and `busy` increase during the run | 0, 0 | every submit was accepted |
| 8 | with `--cdc`: stats lines read from the CDC console | ≥ 0.9 per second of run | CDC logging was active; in heavy runs every report must also carry the heavy flag |
| 9 | the reader ran to the end | no read error | an unplug or reset mid-run fails the run (the tool still writes the JSON) |
| 10 | device clock: run length from the cycle stamps vs from `uptime_ms` | within 0.1 % + 10 ms | both run from HCLK; a mismatch means the DWT counter stopped or `cpu_hz` is wrong, so the timing above is void |

A **gap** is a place where stats reports never arrived. A report that arrives after a higher one is **out of order**
if it fills a gap (it is then no longer missing) and a **duplicate** if its seq had already arrived.

Plus a **strict** result for SPEC §10's proposal, "no missed microframes in the run": with
`CONFIG_HID8K_FRAME_NUMBER=y`, at most 2 microframes without a completion over the run (the tolerance covers the
two end readings); without it, the firmware's `late` counter must not rise. The `late` counter can over-count,
because the device's own callback latency (an interrupt, then two threads) is part of every measured interval, so a
strict FAIL on it alone is a reason to rerun with frame numbers, not a verdict.

SPEC §10 step 2 proposes "no missed microframes in the run" as the pass: that is the **strict** result, not the PASS
verdict. PASS is this tool's looser engineering bar (it allows up to 10 empty microframes a second on average).
Whether condition 2 closes on four strict PASSes, or on four PASSes with the strict results recorded beside them, is
the owner's decision; record both for every run.

## How a failure shows

| What you see | Likely meaning | Next |
|---|---|---|
| `fs` on the stats line, "FULL speed" in the summary, ~1000/s | enumerated at full speed (the simulation's full-speed variant shows this signature end to end) | another port or cable; no hub; check the sysfs speed (480) |
| ~4000, ~2000 or ~1000/s at high speed | the host uses a longer interval than bInterval 1 | read bInterval from the descriptors; check the host's HID driver |
| device rate under 8000/s, 250 µs entries in the histogram (`187.5-250`, `>=250`), `late` rising | microframes with no completion: either the device had no report armed in time, or the host did not poll that microframe (a host driver that resubmits its one interrupt request from the completion handler can miss a poll; Linux usbhid works that way, `drivers/hid/usbhid/hid-core.c`, whether it misses polls is not known) | compare normal and heavy runs, and both hosts; look at `submit_cyc` max; try depth 3; the frame-number build gives the exact count but cannot tell whose fault; only a bus analyser shows an IN token answered with NAK (device late) against no IN token (host) |
| `NO-COMPLETIONS` while configured, `out=2`, "UDC Message queue overrun" on the board console | a lost DataIn event: the endpoint stalled | the event queue sizes above; this is a driver-level fail |
| `stall` above 0 | the queue ran dry (a refused submit, or a completion handled while the bus was still marked suspended) and the refill kick restarted the stream | look at `err=` and the board console; the run already fails on `refused` or `busy` |
| `CYCCNT-MISMATCH`, or `device_clock` fails | the cycle counter stopped (a debug probe attached or detached?) or `cpu_hz` is wrong | power-cycle the board with no debugger session open and rerun |
| `refused` or `busy` rising, `err=-12` | the HID buffer pool ran out (the simulation shows it with the pool at the queue depth: one refusal per completion, `out=1`) | `CONFIG_USBD_HID_IN_BUF_COUNT` |
| a gap in the `~fill` numbering right after `hid8k mode=heavy`, `drop=1280` | the known heavy-mode start burst ([What the simulation found](#what-the-simulation-found)), not a CDC fault | nothing for the run: with `hid8k_measure.py --cdc-mode heavy` it happens within 100 ms of the command, inside the 1 s warm-up |
| device rate 8000/s and no late intervals, but host sequence gaps | the host lost reports after the bus: its HID buffer (64 reports with hidapi on Windows, 63 with Linux hidraw: about 8 ms at 8 kHz, see Not verified) overflowed while the reader stalled | rerun; on Linux the hidraw backend; a quieter host; usbmon to confirm the bus carried every report |
| `cdc_active` fails | the CDC console was not being read | check the port, `--cdc`, the terminal |

If the device side fails (rate, the histogram, stalls) and configuration does not fix it, record why: per
[SPEC §1](../../hardware/design/SPEC.md#_1-purpose-and-what-rev-a-must-prove) the i.MX RT1021 is then the fallback.

## USB simulation (native_sim)

> **Status (2026-11-27): runs and passes, in simulated time.** All three variants below: **182 checks (180 in the
> full-speed variant), 0 failed, 3 known issues, 0 anomalies**, 25.2 s simulated (1 to 60 s of wall time on the
> build machine, with other jobs running), for `native_sim/native/64` and for 32-bit `native_sim` alike. This
> proves code and arithmetic, not hardware: simulated code takes no time, and the bus is a message queue.

`sim/` builds the same four source files as the board (`src/main.c`, `src/hid8k.c`, `src/cdc_console.c`,
`src/usb_device.c`), with the board's `prj.conf` and the same HID and CDC ACM devicetree nodes
(`dts/hid8k_usb.dtsi`), for `native_sim/native/64` (and 32-bit `native_sim`). The device side is Zephyr's virtual
device controller (`drivers/usb/udc/udc_virtual.c`) on Zephyr's virtual bus under its virtual host controller
(`drivers/usb/uhc/uhc_virtual.c`), wired as Zephyr's own host test wires them (`tests/subsys/usb/host/boards/`). The
host side is **Zephyr's own USB host stack** (`subsys/usb/host`) with two small class drivers written for the test,
because v4.5.0 has no host HID or CDC ACM class (`subsys/usb/host/class/` holds a hub and a UVC driver, on main too):
`sim/src/host_hid.c` polls the HID interrupt endpoint and checks every report, `sim/src/host_cdc.c` reads and writes
the CDC console. The firmware's own `main()` runs, stats thread included; a cooperative test thread
(`sim/src/sim_main.c`) acts as the host and as the person at the bench. The button is a `gpio-keys` node on the
emulated GPIO, aliased `sw0` with `INPUT_KEY_0` like the Nucleo's.

The firmware changed only as far as sharing needed, and the board build did not change: `CONFIG_HID8K_SIM` (set only
by `sim/prj.conf`, `depends on ARCH_POSIX`) replaces the DWT cycle counter with `k_cycle_get_32()` (1 MHz on
native_sim) and stubs the PHY tuning; `CONFIG_HID8K_FRAME_NUMBER` and `CONFIG_HID8K_PHY_TUNER2` depend on it being
off; the HID and CDC nodes moved from the overlay into `dts/hid8k_usb.dtsi`; `CONFIG_UDC_STM32_MAX_QMESSAGES` moved
from `prj.conf` to `boards/nucleo_u5a5zj_q.conf`. Rebuilt for `nucleo_u5a5zj_q` before and after: **`zephyr.bin`
byte-identical** (SHA-256 `a5a73d0c35c1cf50…`), `autoconf.h` identical, `zephyr.dts` different only in its
"defined in" comments, and `sim/usb_descriptors_elf.py --compare` finds the descriptor bytes identical
(`hid_desc_0`, `cdc_acm_desc_0`, `report_desc`; the high-speed HID IN endpoint `07 05 81 03 40 00 01`). The same
tool finds the simulation's descriptor templates identical to the board's.

### What speed it simulates, exactly

* **The device enumerates at high speed.** The virtual device controller reports `UDC_BUS_SPEED_HS` when its node
  says `maximum-speed = "high-speed"` (`udc_virtual.c:371`) and connects as a high-speed device (`:384`), so `usbd`
  serves its high-speed configuration, the host stack records `USB_SPEED_SPEED_HS` and checks bMaxPacketSize0 = 64
  (`usbh_device.c`, `validate_device_mps0()`), and every stats report carries the high-speed flag.
* **Zephyr's own virtual host controller then polls once per 1 ms frame.** It starts its SOF timer at 125 µs when a
  high-speed device connects (`uhc_virtual.c:479`), but `uhc_vrt_bus_reset()`, `uhc_vrt_bus_resume()` and
  `uhc_vrt_sof_enable()` restart it at 1 ms (`:534`, `:543`, `:510`), and the host stack resets the bus as the
  first step of enumerating a root device (`usbh_device.c:532`). So bInterval 1 gives **1000 reports/s**. This is
  the default build ("stock"). The file is the same on Zephyr main (fetched 2026-11-27).
* **`hs_fix.conf` gives 125 µs microframes.** It builds `sim/drivers/uhc_virtual_hs.c` instead (with
  `CONFIG_UHC_VIRTUAL=n`): a copy of the v4.5.0 driver whose one change, marked `hid8k-sim`, restarts the timer at
  the period the connected device's speed calls for (30 lines added, 5 removed; `run_sim.py` writes the diff). With
  it the host polls every microframe: **8000 reports/s**.
* **`fs.overlay` makes the device full speed** (`maximum-speed = "full-speed"` on the virtual device controller),
  which is how a full-speed-only port, hub or cable looks to the firmware: it builds no high-speed configuration
  (`usb_device.c` warns "8 kHz is impossible"), the host polls once per 1 ms frame, and the test checks the failure
  signature the bench would see: `usb=cfg fs` on the stats line, the high-speed flag clear in every report, the
  device qualifier and other-speed requests refused, and the host tool's FAIL with "FULL speed".
* Either way there is no electrical, bit-level or bandwidth model, and code takes no simulated time, so every
  completion lands exactly on a frame tick and `submit_cyc` is 0. The 8000 reports/s of the `hs_fix.conf` build
  is the patched virtual host's microframe timer, not a property the firmware earned against a real bus.

### What it checks

| Step | What is forced or read | Checked |
|---|---|---|
| enumeration | the host stack enumerates; the test reads the descriptors again with its own requests | high speed (full speed in the `fs.overlay` variant); VID:PID and strings from Kconfig; bcdUSB 2.00; EF/02/01; bMaxPacketSize0 64; 3 interfaces, self-powered, 100 mA; HID interface 03/00/00 with one endpoint; HID 1.11 and a 56-byte report descriptor; **HID IN: interrupt, wMaxPacketSize 64, bInterval 1**; CDC IAD 02/02/00 with 512-byte bulk endpoints (64 at full speed); device qualifier; other-speed (full-speed) configuration: HID bInterval 1 (1 ms), bulk 64 (at full speed: both requests refused); the report descriptor parsed: ID 1 = 30 bytes in a Keyboard collection, ID 2 = 64 bytes in the 0xFF00/0x01 collection, the sizes `hid8k_report.h` declares; GET_REPORT for both IDs; SET_IDLE / GET_IDLE; SET_LINE_CODING and DTR as a terminal does |
| undisturbed stream, then one key press | `--hid8k_stream_s` seconds (default 3), then 1 s with one press and release; both captured | every report: ID, length, format, depth, `cpu_hz`, flags (the high-speed flag must match the enumerated speed); **seq continuous**; `seq - done_seq` = depth (the pacing); completion intervals and host arrival intervals exactly one frame; each report exactly depth × frame old when taken (250 µs at 125 µs: the README's "about two completions old", executed); `late`, `refused`, `busy`, `cdc_dropped` unchanged; the stats line (`usb=cfg hs`, `rate=`, `out=2`, no notes); in the press second: one F24-down and one key-up report among the stats reports, `kbd_count` +2, seq continuous |
| CDC commands | `help`, `hist`, `reset`, an unknown word, a 40-character line | the answers; the long line ignored; the stats window after a reset at most two periods long (a known issue, below) |
| heavy CDC | `heavy` for 2 s while streaming | the HID stream as above with the heavy flag; 3125 filler lines at 100 kB/s, numbered without a break, well formed; the drop at the switch no larger than the known start burst can make (1,792 B) and equal to the filler lines missing at the host |
| CDC not read | the host stops reading the CDC console (a closed port: Linux `cdc-acm` and Windows `usbser` read only while it is open), `help` and `heavy` sent, 1.5 s, then reading again and `normal` | the HID stream untouched (as above, heavy flag set) while about 150 kB are dropped; when reading resumes, every line that arrives is whole (no filler line of the wrong length, no line with another inside it, every stats line ending in its `pend=` field), the filler gaps within the bytes the firmware counted as dropped, the console recovers, and **every byte it queued since boot reached the host and nothing else** (the host's byte count at the end of the next stats line = its `q=` + the line) |
| button | press, release | one F24-down and one key-up report; `kbd_count` +2; seq continuous |
| host stops polling | no IN transfers for 2.2 s; the button pressed meanwhile | `NO-COMPLETIONS` with `out=2`; then seq continuous, the waiting F24 report arrives, no refusals; a press and release inside a stall is not reported |
| suspend, resume | `uhc_bus_suspend()`, 300 ms, `uhc_bus_resume()` | no reports while suspended; the firmware's state `susp` then `cfg`; seq continuous; `busy` unchanged |
| completions while marked suspended | SUSPEND, then SOFs again with no RESUME, for 1.2 s | the 2 queued reports complete, then nothing; `busy` +2; the stats thread's backstop kick does not act while suspended; RESUME's refill kick restarts the stream (`stall=` +1), seq continuous |
| unplug, replug as the Nucleo sees it | bus suspended, the device removed from the host, then a new high-speed connection (bus reset first) | re-enumeration; the stream restarts at the last seq + 1 + depth (the queued reports were cancelled, never sent); its first report names the last report the host received (cancelled reports not counted); no refusals |
| device-side detach, attach | `usbd_disable()` and `usbd_enable()` on the system work queue, as the firmware's VBUS path calls them | re-enumeration and the stream as above; the known issue below no worse than the reports that were queued (at most `depth` refused, the first report naming at most `depth` past the last one received) |
| final stream | 1 s | as the undisturbed stream |

The capture then goes through the **host tool** (`sim/sim_capture.py` feeds `host/hid8k_analysis.py`'s `Recorder`
and `analyze()`, exactly as `hid8k_measure.py` does, with a CDC result counted from the simulation's console log).
At 125 µs: every criterion but the 600 s duration passes (gate verdict INCOMPLETE, only `duration` failed), and with
the duration limit shortened to the capture it is **PASS and strict PASS**: 8000.00 completions/s, p99.9 125.0 µs,
31,998 stats reports and the 2 keyboard reports, no gaps (the keyboard reports' seqs accounted for through
`kbd_count`, as the tool must on Windows, where the reader never sees them). At 1 ms it is **FAIL on `device_rate`,
`host_rate` and `device_p999` only**, strict FAIL (the `late` counter rises every interval), which is what the tool
should say about a 1 kHz stream; at full speed the same plus `high_speed`, and the summary says "FULL speed".

Other runs, same day: queue depth 1 and 3 pass (the age becomes depth × frame). `CONFIG_HID8K_SIM_HOST_XFERS=2`
passes but shows the second host transfer never completing (below). In a scratch copy with the build assertion
removed and `CONFIG_USBD_HID_IN_BUF_COUNT=2` (= the depth), every refill was refused with -ENOMEM and the queue sat
at `out=1`: `usbd_hid`'s real code confirms the "depth + 1" rule.

**Deliberate breaks** (scratch copies of this folder, one fault each, the 125 µs build unless marked):

| Fault | Result |
|---|---|
| `in-polling-period-us = <1000>` (and `HID8K_NOMINAL_US` to match, as the build assertion requires) | FAIL: bInterval 4, 2000/s, 30 checks; the host tool's expectations fail too |
| the report descriptor declares 62 data bytes for ID 2, the firmware sends 63 | FAIL: "report ID 2 is 496 bits + ID = 63 bytes" |
| `done_seq` one too high in `record_completion()` | FAIL: pacing (every report "short"), 13 checks |
| the RESUME refill kick removed (`usb_device.c`) | FAIL: the stream does not restart after the suspend race, `stall=` stays 0 |
| keyboard reports do not take a seq | FAIL: seq anomalies in the host class; the host tool's `seq_gaps` (keyboard mismatch) |
| the host tool ignores `kbd_count` (`sequence_check()`) | FAIL in `sim_capture.py`: two gaps in the capture (caught only since the capture holds a key press) |
| `cdc_console_write()` writes part of a line when the ring is nearly full | FAIL: cut lines in the "CDC not read" step (caught only since that step exists) |
| the firmware always sets the high-speed flag (full-speed build) | FAIL: every report an anomaly (caught only since the full-speed variant exists) |
| the heavy-mode start burst made larger than the known issue | FAIL: the bound on the known burst |
| `tx_fill()` disables TX when the class takes nothing | **PASS**: that branch never runs (the console only fills when the class reports space), here or on the board |
| queue depth 1; the board-only `CPU_HZ` halved | **PASS**: the simulation cannot see either (no time passes; the board's clock code is not built) |

Earlier the same day (the simulation's first version): the suspended guard in `top_up()` removed (`busy`/`refused`),
the stale marking removed (the replug's first report named a cancelled completion), and a skipped seq were caught.

### What the simulation found

1. **Every switch to heavy mode drops 20 filler lines (1,280 bytes).** `main.c` zeroes `fill_owed_x1000` when the
   mode changes but not `last_tick`, so the first heavy tick owes the whole idle tick, up to 100 ms of filler at
   100 kB/s, 10,000 bytes at once (156 lines), into the 8,192-byte ring: 136 got in, the CDC callback taking some
   meanwhile, and 20 did not. On the board too the CPU fills the ring far faster than USB empties it. The
   firmware's `cdc_dropped` then stays at 1,280 for the boot, and the filler numbering has a gap. Not fixed here
   (this task changes no board behaviour); the fix is `last_tick = now;` in the mode-change branch. The simulation
   prints `KNOWN` while the burst is there and `ok ... (no longer seen)` once it is gone.
2. **`usbd_disable()` from the system work queue counts the cancelled reports as completions.** `usbd_disable()`
   runs `usbd_config_set(0)` in the caller's thread; `usbd_config_reset()` shuts the endpoints down before it
   disables the classes (`usbd_config.c:84`, `:90`); `usbd_ep_disable()` calls `k_yield()` after each dequeue
   (`usbd_endpoint.c:53`); and the stack's thread, `K_PRIO_COOP(8)` (priority -8), outranks the system work queue
   (-1). So the stack thread hands the cancelled reports to `input_report_done` before `iface_ready(false)` marks
   them stale: two bogus 0 µs completions, and the refill submits refused with -ENODEV (`refused` +2, `err=-19`).
   The bus-reset path is fine (it runs in the stack's own thread; the replug step checks it). **Not reachable on the
   Nucleo:** the firmware calls `usbd_disable()` only when `usbd_can_detect_vbus()` is true (`usb_device.c:91`),
   and `udc_stm32.c` never sets `caps.can_detect_vbus`. If a VBUS-sensing controller is used later, stop the
   stream (what `iface_ready(false)` does) before calling `usbd_disable()`. The simulation reports it as `KNOWN`.
3. The button is sampled as a level at each completion, so a press and release inside a polling stall is never sent.
   Fine for an F24 smoke test; the testbed's scan engine has to latch edges.
4. After a host stall, the reports that waited are delivered with data as old as the stall (2.2 s in the test) and
   seq continuous: only `t_submit` shows it. As designed, worth knowing for latency work.
5. The stats line truncates: 8000 completions in a window a few cycles over 1 s print as `rate=7999.9/s`.
6. **A `reset` skips the next regular stats line.** `main.c` prints a line at once for the reset, then advances
   `next_line` by a period as it does for a scheduled line, so the line that was due next is not printed and the
   following window runs up to two periods (1.9 s in the test: `hist[... 100-150:15200 ...]` in a "1 s" line). Its
   `rate=` is still right (it divides by the window's cycles), but its histogram and counts cover two periods, and
   `hid8k_measure.py`, which sends `reset` at the start of every run, gets one stats line fewer. The fix, if wanted:
   advance `next_line` only when the line was due (`now >= next_line`), not for a reset alone. The simulation reports
   it as `KNOWN`.

Each `KNOWN` line is bounded by a check: a fault of the same kind but worse (a larger drop at the heavy switch, more
reports miscounted at the detach, a window longer than two periods) is a FAIL, not a known issue.

**Limits of Zephyr v4.5.0's virtual controllers** (all unchanged on main, 2026-11-27):

* The 1 ms SOF period after a reset (above).
* bInterval is used as a raw count of frames (`uhc_common.c:132`, then `start_frame = frame_number + interval`,
  `uhc_virtual.c:232`), not 2^(bInterval-1) microframes as USB 2.0 §9.6.6 and Linux (`usb_fill_int_urb()`) read a
  high-speed interrupt endpoint's: right only for bInterval 1 and 2.
* One transfer per endpoint per frame, and only the scheduled one's start frame advances (`uhc_virtual.c:223-232`):
  a second interrupt transfer queued on the same endpoint misses its start frame and waits for the 16-bit frame
  counter to come round (65,536 frames). Measured with `CONFIG_HID8K_SIM_HOST_XFERS=2`: 3000 completions in slot 1,
  0 in slot 2. So a host that keeps several requests queued cannot be modelled; the test keeps one, as Linux usbhid
  does.
* A NAKed transfer is retried within the same frame, up to 16 transfer starts per frame (`uhc_virtual.c:27`, `:258`,
  `:377`); a real host controller schedules differently.
* The device side gets no SOF (`udc_virtual.c` never submits `UDC_EVT_SOF`), so the frame-number option cannot be
  simulated; no port model, so the replug is injected with `uhc_submit_event()` (the controller driver's internal
  call, `drivers/usb/uhc/uhc_common.h`).
* A bulk transfer completes within the frame it is scheduled in (the controller keeps sending its packets until it
  ends), so CDC throughput is not modelled: up to one of the host class's 2 kB reads per frame, at either speed.

**Limits of the simulation itself:**

* Code takes no time, so a report is always ready: **queue depth 1 passes** as depth 2 does, and the simulation
  cannot show that depth 2 is needed (or enough). That is a bench question.
* The cycle counter is Zephyr's 1 MHz one, so the firmware's 187.5 µs late threshold is 187 cycles and its 12.5 µs
  histogram bucket 12 cycles (the board's 160 MHz gives 30,000 and 2,000 exactly): the simulated histogram's edges
  are a few percent off the board's. Every simulated interval is a whole frame, so no result here depends on it.
* The board-only code is not built: the DWT cycle counter and its keep-alive, `CPU_HZ` from the RCC node, the
  frame-number read, the PHY tuning, `CONFIG_UDC_STM32_MAX_QMESSAGES`.

### What it can and cannot catch

It **can** catch: descriptor and configuration mistakes (speed, bInterval, wMaxPacketSize, class codes, the IAD,
report sizes against `hid8k_report.h`, strings, the other-speed configuration and its absence at full speed);
errors in the pacing, the sequence numbers (keyboard reports included), the report layout and flags (the
high-speed flag against the enumerated speed); buffer-pool mistakes in the interaction with `usbd_hid` (a pool
smaller than depth + 1); CDC command parsing, whole-line drops when the ring is full, filler numbering and byte
accounting (queued = received + dropped, exactly), and recovery after the host stops reading; the logic of the
recovery paths (host stops polling, suspend and resume, completions while marked suspended, the refill kick,
unplug and replug, device-side detach) and the thread interleavings that Zephyr's scheduler produces in them;
whether the host tool parses and judges the firmware's real report stream, keyboard reports included, at high
and full speed; and descriptor byte drift between two ELF builds (board or simulation, 32- or 64-bit).

It **cannot** show: anything about timing (CPU time is zero, every interval is exact, `submit_cyc` is 0, so a
simulated 8000/s says nothing about the board, and queue depth 1 passes too); the STM32 USB driver (`udc_stm32.c`:
its DataIn queue, FIFO allocation, interrupt latency, endpoint address assignment, the HAL); the HS PHY and TUNER2;
signal integrity, cables, hubs; real host controllers and OS HID stacks (xHCI scheduling, Windows' HID class,
hidraw buffering, usbhid's `kbpoll`); CDC throughput on a real bus; the board-only code (DWT, `CPU_HZ`, the
frame-number option, the PHY tuning); races that need a preemption point other than the ones this simulation's
scheduling hits. The virtual host also reads bInterval as a raw frame count (right only for bInterval 1 and 2 at
high speed) and retries NAKs within the same frame, unlike real host controllers.

### Commands

From a Zephyr v4.5.0 environment (as for the board build; the simulation needs the host's gcc, not the ARM one,
and only the `cmsis`, `cmsis_6`, `hal_stm32` and `picolibc` modules; 32-bit `native_sim` also needs
`gcc-multilib`):

```sh
# Everything: build the three variants, run them, check each capture with the host tool (exit 0 = all passed)
python3 keyboard/firmware/hid8k/sim/run_sim.py --build-dir keyboard/firmware/build/hid8k-sim \
  --board-elf keyboard/firmware/build/hid8k/zephyr/zephyr.elf    # optional: compare descriptors with the board's
python3 keyboard/firmware/hid8k/sim/run_sim.py --target native_sim --build-dir keyboard/firmware/build/hid8k-sim32

# By hand
export ZEPHYR_TOOLCHAIN_VARIANT=host
west build -p always -b native_sim/native/64 keyboard/firmware/hid8k/sim -d keyboard/firmware/build/hid8k-sim/stock
west build -p always -b native_sim/native/64 keyboard/firmware/hid8k/sim -d keyboard/firmware/build/hid8k-sim/hs \
  -- -DEXTRA_CONF_FILE=hs_fix.conf
west build -p always -b native_sim/native/64 keyboard/firmware/hid8k/sim -d keyboard/firmware/build/hid8k-sim/fs \
  -- -DEXTRA_DTC_OVERLAY_FILE=fs.overlay
: > cap.bin; : > cdc.log      # the simulation opens these files, it cannot create them
keyboard/firmware/build/hid8k-sim/hs/zephyr/zephyr.exe --hid8k_capture=$PWD/cap.bin --hid8k_cdc_log=$PWD/cdc.log
python3 keyboard/firmware/hid8k/sim/sim_capture.py cap.bin --cdc-log cdc.log --expect 125 --kbd-reports 2
# (the stock build: --expect 1000; the full-speed build: --expect fs)

# Zephyr's test runner, the three variants (add -p native_sim for the 32-bit target too)
west twister -T keyboard/firmware/hid8k/sim -p native_sim/native/64 --outdir /tmp/hid8k-twister

# The tools' own tests (no Zephyr needed), and the board-build descriptor check
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest keyboard/firmware/hid8k/sim -q -p no:cacheprovider
python3 keyboard/firmware/hid8k/sim/usb_descriptors_elf.py --compare before/zephyr.elf after/zephyr.elf
```

`usb_descriptors_elf.py` exits 1 if the descriptors differ **or if either file lacks one of the three symbols**: two
builds that both lack a descriptor have nothing to compare, and its first version called them "identical".

The executable also takes `--hid8k_stream_s=N` (seconds of captured stream) and Zephyr's native options
(`--help`). Its last line is `hid8k-sim: PASS: ...` or `FAIL`, and its exit status is 0 only on PASS. The test's
own lines go straight to stdout; the firmware's `printk()` lines (the board console: `hid8k: suspended`, the stats
line copy) go through Zephyr's deferred logging as on the board, so they can appear a little after the test lines
around them.

| File | |
|---|---|
| `sim/CMakeLists.txt`, `sim/Kconfig`, `sim/prj.conf`, `sim/hs_fix.conf` | the app: the firmware's sources and `prj.conf`, plus the host side |
| `sim/boards/native_sim_native_64.overlay`, `sim/boards/native_sim.overlay` | the virtual controllers at high speed, the button, `dts/hid8k_usb.dtsi` (64-bit; the 32-bit one includes it) |
| `sim/fs.overlay` | the full-speed variant |
| `sim/src/sim_main.c` | host bring-up before `main()`, the steps above, the results |
| `sim/src/host_hid.c`, `sim/src/host_cdc.c` | the host class drivers and their per-report checks |
| `sim/drivers/uhc_virtual_hs.c` | the virtual host controller with 125 µs microframes (`hs_fix.conf`) |
| `sim/sim_capture.py` | a capture through `host/hid8k_analysis.py`, with the verdicts each frame period should give |
| `sim/usb_descriptors_elf.py` | the descriptor bytes in an ELF (board or simulation), and a comparison |
| `sim/run_sim.py`, `sim/testcase.yaml` | the runner, and the twister entry |
| `sim/test_sim_tools.py` | tests for the two Python tools |

## Zephyr v4.5.0 facts this rests on

Read in the v4.5.0 tree (41d10b5), not guessed; paths are under `zephyr/`, except those that start with `modules/`
(the workspace's `modules/` folder).

| Fact | Where |
|---|---|
| `input_report_done` is the completion callback; without it `hid_device_submit_report` blocks | `include/zephyr/usb/class/usbd_hid.h:183-190`, `:225-240` |
| the callback runs before the completed `net_buf` is freed, and also for cancelled transfers (the error is not passed on) | `subsys/usb/device_next/class/usbd_hid.c:114-144` |
| submit sends from the caller's buffer (`net_buf_alloc_with_data`), `-ENOMEM` when the pool is empty, `-EACCES` when not enabled | `usbd_hid.c:595-613`, `:658-691`; pool size `Kconfig.hid:13-18` (default 2) |
| the class sets "enabled" before calling `iface_ready(true)`; endpoints are enabled before classes | `usbd_hid.c:497-516`; `subsys/usb/device_next/usbd_config.c:131-139` |
| bInterval from `in-polling-period-us`; MPS ≤ 64 keeps one interface | `usbd_hid_macros.h:94-102`, `:163-166`; `include/zephyr/usb/usb_ch9.h:678` |
| disabling an endpoint dequeues it; queued buffers return with `-ECONNABORTED` | `subsys/usb/device_next/usbd_endpoint.c:35-55`; `drivers/usb/udc/udc_stm32.c:1533-1565`; `drivers/usb/udc/udc_common.c:109-116` |
| the UDC thread arms the next queued IN buffer on completion; `ep_enqueue` arms only if idle | `udc_stm32.c:774-828`, `:511-545`, `:1505-1531` |
| no zero-length packet after a 64-byte report: the driver adds one only when the buffer's ZLP flag is set, which `usbd_hid` never sets | `udc_stm32.c:808-817`; `usbd_hid.c:595-613` |
| no DMA: `udc_stm32.c` never sets the HAL's `Init.dma_enable` (its handle is zero-initialised), so the HAL fills the TxFIFO from the interrupt and the report buffer is read until the transfer completes | `udc_stm32.c:1190-1197`; `modules/hal/stm32/stm32cube/stm32u5xx/drivers/src/stm32u5xx_hal_pcd.c:1209`, `:2260` |
| high speed: `usbotg_hs` is `st,stm32-otghs` with the embedded HS PHY, so the driver selects HS and sets `caps.hs`; `USBD_MAX_SPEED_HIGH` is the default for an HS-capable driver; the PHY's 16 MHz HSE reference is supported | `drivers/usb/common/stm32/stm32_usb_common.h:22`, `:35-40`; `udc_stm32.c:162-167`, `:1684-1685`; `subsys/usb/device_next/Kconfig:18-21`; `drivers/usb/common/stm32/phy_u5otghs.c:80`; `dts/arm/st/u5/stm32u5_usbotg_hs.dtsi` |
| the FIFO RAM fits: RxFIFO 170 words, EP0 16, the HID IN 32, the CDC notification IN 8, the CDC bulk IN 128: 354 of 1,024 (*arithmetic* from the allocator) | `udc_stm32.c:1023-1041`, `:1076-1077`; `usbd_cdc_acm.c:38` |
| completed transfers are kept on a list, so an overrun of the stack's queue cannot lose one; the stack thread handles the whole list before each event it takes off its queue | `subsys/usb/device_next/usbd_core.c:39-47`, `:153-163` |
| `usbd_ep_enqueue()` refuses IN transfers with `-EPERM` while suspended | `subsys/usb/device_next/usbd_endpoint.c:145-149` |
| a reset or new configuration shuts the endpoints down (cancelling their buffers) before the classes' `disable`, so the firmware marks its queued buffers stale in `iface_ready(false)` and ignores them when they come back | `subsys/usb/device_next/usbd_config.c:84-90`, `:106-140` |
| the DataIn interrupt posts to an 8-entry queue and drops on overrun | `udc_stm32.c:759-772`; `drivers/usb/udc/Kconfig.stm32` (`UDC_STM32_MAX_QMESSAGES`) |
| both USB threads are cooperative, `K_PRIO_COOP(8)` | `udc_stm32.c:1693-1696`; `subsys/usb/device_next/usbd_core.c:284-288` |
| SOF events carry no frame number and need `CONFIG_UDC_ENABLE_SOF` | `udc_common.h:147-158`; `usbd_core.c:108`; `drivers/usb/udc/Kconfig:44-48`; `usbd_hid.h:207` |
| CDC ACM's callback runs in a work queue (the system one by default, cooperative at -1), which gives up the CPU after each item (it yields if more work is pending, else it blocks); the class runs the callback again while TX is enabled and has space | `subsys/usb/device_next/class/usbd_cdc_acm.c:139-186`, `:1054-1110`; `kernel/Kconfig:535-539`; `kernel/work.c:786-797` |
| the ring buffer's claim API is deprecated in v4.5.0; `ring_buf_get_ptr`/`ring_buf_consume` replace it | `include/zephyr/sys/ring_buffer.h:661-700`, `lib/utils/Kconfig:39-42` |
| the sample USB Kconfig options are for in-tree samples only | `samples/subsys/usb/common/Kconfig.sample_usbd:4-7` |
| the Nucleo enables `usbotg_hs` and the HS PHY, the console is USART1, the default flash runner is STM32CubeProgrammer | `boards/st/nucleo_u5a5zj_q/nucleo_u5a5zj_q.dts`, `board.cmake` |
| `DSTS.FNSOF` is bits 21:8 of the OTG_HS device status register | `modules/hal/stm32/stm32cube/stm32u5xx/soc/stm32u5a5xx.h:22983-22985` |

## Not verified

* That the 8 kHz stream works at all on `udc_stm32`: the point of the test.
* The Nucleo's power-jumper default (the device is declared self-powered on that basis), the ST-LINK VCP wiring to
  USART1, and the user USB-C connector's wiring to PA11/PA12: from the board's devicetree and Zephyr's board page,
  not from ST's user manual.
* What `DSTS.FNSOF` counts at high speed (the tool infers it from the rate). RM0456 Rev 7 §73 (in the transcription)
  calls it only the "Frame number of the received SOF".
* Whether writing TUNER2 before EN, or the PHY clock coming on after EN as Zephyr orders it, makes any difference on
  the bench (`CONFIG_HID8K_PHY_TUNER2`); and the RM0456 text behind it was read in a transcription, not ST's PDF.
* The hosts' HID buffering, now read in their sources (2026-11-27) but not measured: hidapi on Windows sets the HID
  class driver's ring to 64 reports (`windows/hid.c`, `HidD_SetNumInputBuffers(device_handle, 64)`; Windows'
  default is 32 and its maximum 512, Microsoft's `HidD_SetNumInputBuffers` page), 8 ms at 8 kHz; Linux hidraw keeps
  a 64-slot ring per reader that holds 63 reports and drops the newest when full (`include/uapi/linux/hidraw.h:56`,
  `drivers/hid/hidraw.c`, `hidraw_report_event()`). So a reader that stalls for more than about 8 ms loses reports,
  which the tool counts as host sequence gaps. Linux usbhid does keep a single interrupt URB per interface and
  resubmits it from its completion handler (`drivers/hid/usbhid/hid-core.c`: one `urbin`, resubmitted in
  `hid_irq_in()`), and converts a high-speed bInterval as 2^(bInterval-1) microframes (`include/linux/usb.h`,
  `usb_fill_int_urb()`).
* That a debug probe can clear `DEMCR.TRCENA` when it attaches or detaches is from memory too; the firmware's
  keep-alive and the `device_clock` check are there in case it does.
* That both cooperative USB threads, and the system work queue, run briefly enough for the driver thread to arm the
  next report within a microframe: the design argues it, only the bench shows it.
* The build used Ubuntu's GCC, not the Zephyr SDK; a build with the SDK may differ.
