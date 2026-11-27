# boards: the Zephyr board `kbd_testbed_a`

> **Status (2026-11-27): generated and compiled; the board does not exist.** The rev A testbed motherboard is
> designed on paper ([SPEC](../../hardware/design/SPEC.md)); no PCB has been made. Everything here builds with
> Zephyr v4.5.0 and Ubuntu's arm-none-eabi GCC 13.2.1 (`gnuarmemb`, not the Zephyr SDK 1.0.1 that v4.5.0
> expects). Nothing has run on the hardware: not the clocks, the pin map, the runners or the OpenOCD config.

The out-of-tree Zephyr board for the testbed motherboard (STM32U5A5VJT6, LQFP100), target `kbd_testbed_a`
(qualified: `kbd_testbed_a/stm32u5a5xx`), as SPEC §8.1 proposes. Its data comes from the hardware contract,
[`keyboard/hardware/design/nets.py`](../../hardware/design/nets.py), through one generator.

## The generator

```sh
python3 keyboard/firmware/boards/gen_board.py            # write the generated files
python3 keyboard/firmware/boards/gen_board.py --check    # the contract check: exit 1 if a committed file is stale
python3 keyboard/firmware/boards/gen_board.py --check --diff
```

`--check` regenerates in memory from `nets.py` and compares byte for byte with the committed files, and also
fails if a hand-written board file is missing. Run it after any change to `nets.py`; it needs only Python 3 (it
reads `nets.py` with `runpy` and writes no bytecode). It first runs `nets.check()` and refuses an inconsistent
contract, and it stops with a message if `nets.py` loses something the board needs (a net, an expander pin, a
monitor) or if an expander output has no holding resistor in `nets.EXPANDER_RESET_STATE`.

| File (under `prettycool/kbd_testbed_a/`) | Generated | From |
|---|---|---|
| `board.yml`, `Kconfig.kbd_testbed_a` | yes | the SoC (`stm32u5a5xx`) |
| `Kconfig` | yes | selects `BOARD_EARLY_INIT_HOOK` for `board.c` |
| `Kconfig.defconfig` | yes | the init order of SPEC §8.4: I2C 50, TCA9535 52, TCA9548A root 53, channels 54, and the TCA9535 interrupt |
| `kbd_testbed_a_defconfig` | yes | console, MPU, GPIO |
| `kbd_testbed_a.dts` | yes | `nets.MCU_PINS`/`MCU_FUNC` (every pinctrl node), `EXPANDERS`, `INA226_RAILS` and `INA226_CURRENT_LSB_UA`, `SLOT_MCU`, `LANE_ADC`, `TYPEC`, the I2C maps, `SWITCH_TRIP`, the budgets; clocks per SPEC §8.1 |
| `kbd_testbed_a.yaml` | yes | twister metadata (`only_tags: prettycool`) |
| `board.cmake`, `support/openocd.cfg` | yes | STM32CubeProgrammer (default) and OpenOCD over an STLINK-V3 on J_SWD |
| `include/tb_board_map.h` | yes | the same map as plain C (below) |
| `sim/kbd_testbed_a_sim.overlay` | yes | the same nodes on native_sim's emulated controllers, for the bring-up's simulated board |
| `board.c`, `CMakeLists.txt` | **no** | UCPD dead-battery off at boot; the map header on the include path |
| `dts/bindings/*.yaml`, `dts/bindings/vendor-prefixes.txt` | **no** | `prettycool,coupon-slot`, `prettycool,kbd-testbed`, `prettycool,tusb320` |

### The independent check: `check_dts.py`

`--check` proves the committed files are what the generator makes from `nets.py` today; it cannot see a bug in the
generator itself, because both sides come from the same code (the decimal ADC unit addresses below were one).
`check_dts.py` shares no code with `gen_board.py`: it preprocesses the board dts with the host `cpp` as Zephyr's
`dts.cmake` does, parses it with Zephyr's own `dtlib`, decodes every pinmux cell, GPIO specifier, io-channel and
phandle, and compares each with `nets.py`, pin by pin.

```sh
source /root/zephyrproject/ENV.sh                                   # ZEPHYR_BASE: dtlib and the SoC dtsi
python3 keyboard/firmware/boards/check_dts.py --sim                 # the board dts and the native_sim overlay
python3 keyboard/firmware/boards/check_dts.py --dts <build>/zephyr/zephyr.dts   # a built app's merged tree
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider keyboard/firmware/boards   # its fault injection
```

It checks: every pinctrl entry (node name = `nets.MCU_FUNC`'s, decoded port, line and AF/analog mode, the right
peripheral); every GPIO specifier of the slot, testbed, LED and bus nodes (MCU pin through `MCU_PINS`, expander pin
through the expander's I2C address, `EXPANDER_I2C` and `EXPANDERS`; active level from the `_N` convention); every
lane (`io-channels`, `alt-adc-channels` against `LANE_ADC`/`SLOT_MCU`, a `channel@<hex>` child with that reg and
the converter's resolution); the I2C maps against `nets.i2c_buses()`; the expanders' and INA226s' properties, with
CAL computed as Zephyr's driver does and required to be at most 2048 (so the current register cannot clip below the
shunt's full scale) and to reach the switch's maximum trip; U_CC, the mux and its channels; the rules, trips and
budget numbers; that no enabled node's pinctrl claims a line that goes straight to a slot, SPI2 has no `cs-gpios`,
UART4 and the timers are off and the bus-recovery pins are open drain; that every MCU I/O net appears; and the clock
tree of SPEC §8.1 (HSE 16 MHz crystal, LSE off, PLL1 M 4 N 80 Q 2 R 2 = 160 MHz = `rcc` clock-frequency, the PHY
on `<STM32_SRC_HSE OTGHS_SEL(0)>`, the ADCs at 40 MHz). Result (2026-11-27): board 1075 checks, sim overlay 762,
none failing. `test_check_dts.py` applies 14 mutations to a copy of the dts (each must fail), and breaks
`gen_board.py` itself in a scratch tree with the old decimal unit addresses: `gen_board.py --check` passes there and
`check_dts.py` fails. It takes `nets.py` as the truth and says nothing about whether the hardware matches it.

Every generated file starts with a do-not-edit header and the **map hash**, the first 16 hex digits of SHA-256
over `nets.py` and `gen_board.py`. The firmware reports it (`@tb boot ... map=<hash>`), so a log says which
contract it was built from. Constants that SPEC gives and `nets.py` has no field for are at the top of
`gen_board.py`, each with its section: the clock tree, the ADC prescaler and acquisition times, the slot LDO's
300 mA, the 45 mA base load estimate, the KVM rail's trip window, the U_CC decide time.

## What the devicetree says

* **Clocks (SPEC §8.1):** HSE 16 MHz crystal (no bypass), PLL1 M 4 N 80 Q 2 R 2 = 160 MHz, prescalers 1, HSI48 on
  as on the Nucleo; **`clk_lse` stays disabled** (PC14 is S1_IRQ_N, PC15 LED_N, and with no crystal the LSE init
  waits forever). The HS PHY takes the HSE (`OTGHS_SEL(0)`, the SoC default).
* **Console and shell:** USART1 on PA9/PA10 (the STDC14's VCP pins), 115200.
* **I2C1** (400 kHz): U_EXP1-3 as `nxp,pca95xx` (`ngpios = <16>`, no PCAL features; U_EXP2 with
  `interrupt-gpios` = EXP_INT_N on PC13), the 13 `ti,ina226` nodes with `rshunt-micro-ohms` and
  `current-lsb-microamps` from nets.py, U_CC at 0x67 (`prettycool,tusb320`, its INT_N on U_EXP2 P14).
* **I2C4** (400 kHz): the TCA9548A at 0x70 with `reset-gpios` = MUX_RST_N and `i2c-mux-idle-disconnect`, and its
  eight channel nodes `mux_ch0`..`mux_ch7` (S1-S5, J_KVM, two test-pad channels).
* **SPI2** on PB13-PB15, **without `cs-gpios`** (below).
* **ADC1, ADC2, ADC4:** every lane is a channel on every converter that reaches its pin (`nets.LANE_ADC`): ADC1 and
  ADC2 IN1-IN17 at 14 bits, ADC4 IN1-IN4, IN9-IN11, IN15-IN20, IN22, IN23 at 12 bits; the kernel clock HCLK / 4 =
  40 MHz; acquisition 391 cycles (ADC1/2) and 814.5 (ADC4), slow enough for any lane source of SPEC §4.9. VREFINT
  (`vref1`) and the die temperature are enabled.
* **`testbed` node** (`prettycool,kbd-testbed`): the motherboard's own lines (SLOT_FAULT_N, PM_ALERT_N, VSYS_PG,
  S5_PG, USBC_INT_N, KVM lines, MUX_RST_N, SLOT_SYNC, RIG_MARK, RIG_TRIG), the board-level monitors, U_CC, the
  mux, and the budget constants.
* **`slots` / `slot1`..`slot5`** (`prettycool,coupon-slot`): per slot its four lanes (`io-channels`) and their
  alternates (`alt-adc-channels`), G0-G5, CS0_N/CS1_N, IRQ_N (S5: `irq-is-tim1-bkin`), PRESENT_N, the 3.3 V and
  5 V enables, the bus-switch enable, the LED, S5's breaker PG, its two monitors, its mux channel, its coupon rules
  and trip windows, and its rail ids.
* **Disabled on purpose:** UART4 (KVM: an idle-high TX would back-power an unpowered KVM coupon), TIM1, TIM2 and
  TIM8 (their pins are slot lines; an application enables `timersN` and `pwmN` in an overlay).
* **USB:** `zephyr_udc0: &usbotg_hs` with DM/DP and the SOF pin (the OTG core drives SOF only if enabled, which
  Zephyr v4.5.0 does not), `&otghs_phy` on.
* **Flash partitions:** as the Nucleo's (MCUboot-ready); without MCUboot an application links at 0x08000000.

### Choices that come from reading Zephyr v4.5.0, not from SPEC

| Choice | Why (source) |
|---|---|
| No `cs-gpios` on SPI2 | `spi_stm32.c:2279` calls `spi_context_cs_configure_all()` at init, which configures every listed CS `GPIO_OUTPUT_INACTIVE` (`spi_context.h:326-349`): high, into the coupons, while their slots are unpowered (SPEC §3.5 forbids driving a line into an unpowered slot). Each slot node lists its own CS lines and the application drives them |
| `Kconfig.defconfig` sets the TCA954x priorities | `i2c_tca954x.c` has `BUILD_ASSERT(CONFIG_I2C_TCA954X_CHANNEL_INIT_PRIO > CONFIG_I2C_TCA954X_ROOT_INIT_PRIO)` while `Kconfig.tca954x` defaults both to `I2C_INIT_PRIORITY`: **with its own defaults the driver does not build** (checked: "static assertion failed: I2C multiplexer channels must be initialized after their root"). The root must also come after U_EXP2 (its `reset-gpios`) |
| A gap at priority 51 | so an application can read the expanders' raw registers before the TCA9535 driver's init makes every pin an input (`gpio_pca95xx.c` `init_pins()` = `update_direction_regs(dev, 0xFFFF)`); the bring-up's warm-reset snapshot uses it |
| `board.c` disables the UCPD dead-battery Rd | `soc/st/stm32/stm32u5x/soc.c` does it only when no legacy USB device driver is built (`!IS_ENABLED(CONFIG_USB_DEVICE_DRIVER)`); the board does it for every application (SPEC §5.2: PA15 SLOT_SYNC and PB15 SLOT_MOSI) |
| ADC channel nodes `channel@a` .. | devicetree unit addresses are hex, and `ADC_DT_SPEC_GET` finds a channel with `DT_CHILD_BY_UNIT_ADDR_INT`. An earlier draft of this generator wrote `channel@10` for channel 10, which the lookup reads as 16: every lane on channel 10 and up would have failed `adc_channel_setup_dt()` (-ENOTSUP). The bring-up's simulated board found it |
| I2C `scl-gpios`/`sda-gpios` open drain | they are only for bus recovery (`i2c_recover_bus()`, which the bring-up calls at boot when a bus does not answer): Zephyr v4.5.0's `i2c_stm32_recover_bus()` configures them `GPIO_OUTPUT_HIGH` with the devicetree's flags (`drivers/i2c/i2c_stm32_common.c`), so without `GPIO_OPEN_DRAIN` it would drive SDA high push-pull against the target holding it low. The Nucleo's board file has the same pins without the flag |
| `vref-mv` on `adc12_common`/`adc4_common` | the v4.5.0 binding has it on the common node, not on `adc1` |
| `alt-adc-channels` is a plain array of triples | a second `phandle-array` with `specifier-space: io-channel` would share `io-channel-names` with `io-channels` (edtlib) |

## The C map, `include/tb_board_map.h`

For code that does not go through the devicetree: the bring-up's checks, the lib's tests, and later the scan
engine's register-level GPIO and ADC setup. It has every used MCU pin (`TB_PIN_<net>_PORT/_PIN/_LQFP` and a table
with function and mode), the EXTI lines, the rail ids (shared with `keyboard/firmware/lib/include/tb/rails.h`,
which the lib's tests check), every expander net (`TB_EXPNET_<net>_EXP/_PIN/_OUT/_ACTIVE_LOW/_SAFE_LEVEL`), the
restored expander registers (`TB_EXP_SAFE_OUTPUT`, `TB_EXP_SAFE_CONFIG`), the lane-to-converter map, the INA226
table with CAL computed as Zephyr's driver does, the coupon rules and trip windows, the budgets and the I2C
addresses. A board built with this app gets it on its include path (`CMakeLists.txt`).

## Build and flash

```sh
source /root/zephyrproject/ENV.sh     # this workspace: ZEPHYR_BASE, gnuarmemb
west build -b kbd_testbed_a $ZEPHYR_BASE/samples/hello_world -d <build> -- \
    -DBOARD_ROOT=$PWD/keyboard/firmware
west flash -d <build>                 # STM32CubeProgrammer over SWD; --runner openocd also configured
```

The bring-up app sets its own board root, so `west build -b kbd_testbed_a keyboard/firmware/bringup` needs no
`-DBOARD_ROOT`. Build results (2026-11-27): `hello_world` 18,960 B flash, 4,392 B RAM; the bring-up app below.

Twister knows the board with `-A keyboard/firmware/boards`. With Ubuntu's GCC, twister's default
warnings-as-errors fails every ARM build on Zephyr's own `include/zephyr/arch/arm/bit_rev.h:38` (implicit
`__rbit`, a toolchain/picolibc issue that `samples/hello_world` shows too); `--disable-warnings-as-errors` builds.

## Not verified

* That the clock tree, the PLL and the HS PHY run on this board (the Nucleo's settings, SPEC §8.1).
* The OpenOCD config (`stm32u5x.cfg` with an STLINK-V3 in `dapdirect_swd`), copied from the Nucleo's.
* `vref1`/`die_temp` read sensibly with VREF+ tied to VDDA (they are ST's calibrated channels).
* That `nxp,pca95xx` drives the TCA9535 as SPEC §8.4 reads it (no TCA9535 has been on a bus here; the simulated
  board's model of it is this repository's reading of SCPS201D).
