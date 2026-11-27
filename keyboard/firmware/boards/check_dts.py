#!/usr/bin/env python3
"""Check the kbd_testbed_a devicetree against nets.py pin by pin, independently of gen_board.py.

    source /root/zephyrproject/ENV.sh                      # ZEPHYR_BASE (dtlib and the SoC .dtsi files)
    python3 keyboard/firmware/boards/check_dts.py          # the board dts, preprocessed here with the host cpp
    python3 keyboard/firmware/boards/check_dts.py --dts <build>/zephyr/zephyr.dts   # a built app's merged tree
    python3 keyboard/firmware/boards/check_dts.py --sim    # also the native_sim overlay the simulated board uses
    python3 keyboard/firmware/boards/check_dts.py -v       # list every check, not only the failures

gen_board.py --check proves that the committed files are what the generator makes from nets.py today. It
cannot see a bug in the generator itself, because both sides come from the same code (the ADC unit-address
bug was one). This script shares no code with the generator: it parses the devicetree with Zephyr's own dtlib,
decodes every pinmux cell, GPIO specifier, io-channel and phandle, and compares each with what nets.py says
the hardware is. What it checks:

* every pinctrl entry of every node: the node name is nets.MCU_FUNC's for that pin, the decoded STM32_PINMUX
  port, line and mode agree with the name and with MCU_FUNC's AF or ANALOG mode, and the referencing peripheral
  is the one the name says (usart1_tx_pa9 under &usart1);
* every GPIO specifier of the slot, testbed and LED nodes: the controller and pin give the net the property
  stands for (an MCU pin through MCU_PINS, an expander pin through the expander's I2C address, EXPANDER_I2C and
  EXPANDERS), and the active level follows the net (_N active low; LED_S cathode to the pin, active low);
* every lane: io-channels and alt-adc-channels against LANE_ADC and SLOT_MCU, and each channel has a child
  node `channel@<hex>` with reg equal to the channel (Zephyr finds it by unit address);
* I2C: the addresses on I2C1 and I2C4 equal nets.i2c_buses(); the expanders' and the INA226s' properties; CAL
  computed as Zephyr v4.5.0's driver does (DIV_ROUND_CLOSEST) fits 15 bits and the current register reaches the
  shunt's full scale and the switch's maximum trip; U_CC's address and interrupt; the mux and its channels;
* the numbers the firmware reads from the tree: coupon rules, trip windows, the budget ceiling;
* safety: no enabled node's pinctrl claims a line that goes straight to a slot (CS, G, IRQ: SPEC §3.5), SPI2
  has no cs-gpios, UART4 and the timers are disabled, the I2C bus-recovery pins are open drain, and every MCU
  I/O net appears in the tree (or is listed as intentionally absent);
* clocks (SPEC §8.1): HSE 16 MHz crystal, no bypass, LSE not enabled, PLL1 from HSE with M 4 N 80 Q 2 R 2 and
  SYSCLK = rcc clock-frequency = 160 MHz, the OTG_HS PHY from the HSE, the ADCs' prescaler 4 (40 MHz, inside
  the 55 MHz maximum of SPEC §6.2).

It cannot check anything about the hardware: that the pins are soldered where nets.py says, that a driver does
with a property what its binding promises, or the clock tree's start-up. It also takes nets.py as the truth.
Exit status: 0 all checks pass, 1 a check fails, 2 the inputs could not be read.
"""
import argparse
import os
import pathlib
import re
import runpy
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
NETS = REPO / "keyboard" / "hardware" / "design" / "nets.py"
BOARD_DTS = HERE / "prettycool" / "kbd_testbed_a" / "kbd_testbed_a.dts"
SIM_OVERLAY = HERE / "prettycool" / "kbd_testbed_a" / "sim" / "kbd_testbed_a_sim.overlay"

# SPEC §8.1 / §5.2 / §6.2 (the clock tree the board must have), restated here on purpose, not imported.
SPEC_HSE_HZ = 16_000_000
SPEC_PLL1 = {"div-m": 4, "mul-n": 80, "div-q": 2, "div-r": 2}
SPEC_SYSCLK_HZ = 160_000_000
SPEC_ADC_PRESCALER = 4
ADC_FMAX_HZ = 55_000_000          # DS13543 Table 97 (SPEC §6.2): f_ADC up to 55 MHz
# STM32_PINMUX fields (include/zephyr/dt-bindings/pinctrl/stm32-pinctrl.h, v4.5.0)
PINMUX_MODE_MASK, PINMUX_LINE_SHIFT, PINMUX_PORT_SHIFT = 0x1F, 5, 9
PINMUX_ANALOG = 0x10
GPIO_ACTIVE_LOW = 1
GPIO_OPEN_DRAIN = 0x6             # GPIO_SINGLE_ENDED | GPIO_LINE_OPEN_DRAIN (dt-bindings/gpio/gpio.h)
# Nets that are on MCU pins but that the devicetree has no reason to name.
NOT_IN_DTS = {"SWDIO", "SWCLK", "SWO", "HSE_IN", "HSE_OUT", "BOOT0", "NRST"}
# pinctrl name prefix -> the label of the node that may use it
PERIPH_OF_PREFIX = {"tim1": "pwm1", "tim2": "pwm2", "tim8": "pwm8", "usb": "usbotg_hs"}


class Report:
    def __init__(self, verbose):
        self.verbose, self.fails, self.passes = verbose, [], 0

    def check(self, ok, what):
        if ok:
            self.passes += 1
            if self.verbose:
                print(f"  ok    {what}")
        else:
            self.fails.append(what)
            print(f"  FAIL  {what}")
        return ok


def zephyr_base():
    zb = os.environ.get("ZEPHYR_BASE")
    if not zb:
        sys.exit("check_dts: ZEPHYR_BASE is not set (source /root/zephyrproject/ENV.sh)")
    return pathlib.Path(zb)


def load_dtlib(zb):
    sys.path.insert(0, str(zb / "scripts" / "dts" / "python-devicetree" / "src"))
    sys.dont_write_bytecode = True
    from devicetree import dtlib   # noqa: E402
    return dtlib


def include_dirs(zb):
    hal = zb.parent / "modules" / "hal" / "stm32" / "dts"
    return [zb / "include", zb / "include" / "zephyr", zb / "dts" / "common", zb / "dts" / "arm", zb / "dts", hal]


def preprocess(zb, src, out, prefix=""):
    """The C preprocessor, as Zephyr's dts.cmake runs it (zephyr_dt_preprocess)."""
    with tempfile.NamedTemporaryFile("w", suffix=".dts", delete=False) as f:
        f.write(prefix)
        f.write(f'#include "{src}"\n')
        wrapper = f.name
    try:
        cmd = ["cpp", "-x", "assembler-with-cpp", "-nostdinc", "-undef", "-D__DTS__", "-P", "-E"]
        for d in include_dirs(zb):
            cmd += ["-isystem", str(d)]
        cmd += [wrapper, "-o", str(out)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(f"check_dts: preprocessing {src} failed:\n{r.stderr}")
    finally:
        os.unlink(wrapper)


def cells(prop):
    v = prop.value
    return [int.from_bytes(v[i:i + 4], "big") for i in range(0, len(v), 4)]


def label(node):
    return node.labels[0] if node.labels else node.path


def okay(node):
    st = node.props.get("status")
    return st is None or st.to_string() in ("okay", "ok")


class Contract:
    """What nets.py says, in the shapes the checks need (no gen_board.py code)."""

    def __init__(self, path):
        ns = runpy.run_path(str(path))
        probs = ns["check"]()
        if probs:
            sys.exit("check_dts: nets.check() fails:\n  " + "\n  ".join(probs))
        self.ns = ns
        self.mcu_pins = ns["MCU_PINS"]
        self.mcu_func = ns["MCU_FUNC"]
        self.slot_mcu = ns["SLOT_MCU"]
        self.lane_adc = ns["LANE_ADC"]
        self.expanders = ns["EXPANDERS"]
        self.exp_i2c = {a: d.split()[0] for a, d in ns["EXPANDER_I2C"].items()}
        self.ina = ns["INA226_RAILS"]
        self.ina_lsb = ns["INA226_CURRENT_LSB_UA"]
        self.trip = ns["SWITCH_TRIP"]
        self.buses = ns["i2c_buses"]()
        self.slots = list(ns["SLOTS"])
        self.pin_of_net = {}
        for pin, net in self.mcu_pins.items():
            if net and re.match(r"^P[A-H]\d", pin):
                self.pin_of_net[net] = pin
        # (adc, channel) -> pin
        self.adc_pin = {}
        for pin, chans in self.lane_adc.items():
            for c in chans:
                a, n = re.match(r"ADC(\d)_IN(\d+)$", c).groups()
                self.adc_pin[(int(a), int(n))] = pin
        self.exp_pin_net = {}
        for ref, pins in self.expanders.items():
            for pname, net in pins.items():
                m = re.match(r"^P([01])([0-7])$", pname)
                self.exp_pin_net[(ref, int(m.group(1)) * 8 + int(m.group(2)))] = net

    @staticmethod
    def pin_name(port_letter, num):
        return f"P{port_letter}{num}"

    def mcu_pin_full(self, short):
        """'PC14' -> 'PC14-OSC32_IN' (the name nets.py keys by)."""
        for p in self.mcu_pins:
            if p == short or p.startswith(short + "-"):
                return p
        return None

    def active_low(self, net):
        """nets.py's convention: an _N suffix (BUSEN_N_Sn carries it before the slot) is active low; the slot LEDs
        hang with their cathode on the expander pin (EXPANDER_RESET_STATE), so they are active low too."""
        return re.search(r"_N(_S\d)?$", net) is not None or net.startswith("LED_S")


class Checker:
    def __init__(self, dt, c, rep, kind):
        self.dt, self.c, self.rep, self.kind = dt, c, rep, kind
        self.seen_nets = set()

    # --- specifier decoding ---------------------------------------------------------------------------------
    def gpio_specs(self, prop):
        """[(controller node, pin, flags)] of a GPIO phandle-array (all controllers here have #gpio-cells 2)."""
        v, out, i = cells(prop), [], 0
        while i < len(v):
            ctl = self.dt.phandle2node[v[i]]
            n = ctl.props["#gpio-cells"].to_num()
            args = v[i + 1:i + 1 + n]
            out.append((ctl, args[0], args[1] if n > 1 else 0))
            i += 1 + n
        return out

    def adc_index(self, node):
        m = re.match(r"^adc(\d)$", label(node))
        return int(m.group(1)) if m else None

    def net_of_gpio(self, ctl, pin):
        """(net, where) for a controller/pin, through nets.py only."""
        m = re.match(r"^gpio([a-h])$", label(ctl))
        if m:
            full = self.c.mcu_pin_full(self.c.pin_name(m.group(1).upper(), pin))
            return (self.c.mcu_pins.get(full) if full else None), f"{full}"
        if "reg" in ctl.props and ctl.props.get("compatible") and \
                ctl.props["compatible"].to_string() == "nxp,pca95xx":
            addr = ctl.props["reg"].to_num()
            ref = self.c.exp_i2c.get(addr)
            if ref is None:
                return None, f"expander at 0x{addr:02x} unknown to nets.EXPANDER_I2C"
            return self.c.exp_pin_net.get((ref, pin)), f"{ref} P{pin // 8}{pin % 8}"
        return None, f"controller {ctl.path}"

    def check_gpio_prop(self, node, pname, expect_nets):
        prop = node.props.get(pname)
        if not self.rep.check(prop is not None, f"{label(node)}: {pname} present"):
            return
        specs = self.gpio_specs(prop)
        self.rep.check(len(specs) == len(expect_nets),
                       f"{label(node)}: {pname} has {len(specs)} entries, nets.py {len(expect_nets)}")
        for i, ((ctl, pin, flags), want) in enumerate(zip(specs, expect_nets)):
            net, where = self.net_of_gpio(ctl, pin)
            self.seen_nets.add(net)
            self.rep.check(net == want, f"{label(node)}: {pname}[{i}] = {where} is {net}, nets.py says {want}")
            low = bool(flags & GPIO_ACTIVE_LOW)
            self.rep.check(low == self.c.active_low(want),
                           f"{label(node)}: {pname}[{i}] ({want}) active-{'low' if low else 'high'}, expected "
                           f"active-{'low' if self.c.active_low(want) else 'high'}")

    # --- the checks -------------------------------------------------------------------------------------------
    def slots(self):
        root = self.dt.get_node("/slots")
        by_n = {}
        for node in root.nodes.values():
            by_n[node.props["slot"].to_num()] = node
        self.rep.check(sorted(by_n) == self.c.slots, f"slot nodes {sorted(by_n)} == nets.SLOTS {self.c.slots}")
        for n in self.c.slots:
            node = by_n.get(n)
            if node is None:
                continue
            sm = self.c.slot_mcu[n]
            self.check_gpio_prop(node, "g-gpios", [f"S{n}_G{g}" for g in range(6)])
            for g in range(6):     # G-lines on the MCU must be the MCU pin, the others on an expander
                spec = self.gpio_specs(node.props["g-gpios"])[g]
                on_mcu = label(spec[0]).startswith("gpio")
                self.rep.check(on_mcu == (f"G{g}" in sm),
                               f"slot{n}: G{g} on {'the MCU' if on_mcu else 'an expander'}, nets.SLOT_MCU "
                               f"{'has' if f'G{g}' in sm else 'lacks'} it")
            self.check_gpio_prop(node, "cs-gpios", [f"S{n}_CS0_N", f"S{n}_CS1_N"])
            self.check_gpio_prop(node, "irq-gpios", [f"S{n}_IRQ_N"])
            self.check_gpio_prop(node, "present-gpios", [f"S{n}_PRESENT_N"])
            self.check_gpio_prop(node, "en-3v3-gpios", [f"EN_3V3_S{n}"])
            self.check_gpio_prop(node, "en-5v-gpios", [f"EN_5V_S{n}"])
            self.check_gpio_prop(node, "busen-gpios", [f"BUSEN_N_S{n}"])
            self.check_gpio_prop(node, "led-gpios", [f"LED_S{n}"])
            bkin = "BKIN" in self.c.mcu_func.get(sm["IRQ_N"], ("",))[0]
            self.rep.check(("irq-is-tim1-bkin" in node.props) == bkin,
                           f"slot{n}: irq-is-tim1-bkin {'set' if 'irq-is-tim1-bkin' in node.props else 'unset'}, "
                           f"MCU_FUNC {sm['IRQ_N']} {'is' if bkin else 'is not'} TIM1_BKIN")
            if n == 5:
                self.check_gpio_prop(node, "pg-5v-gpios", ["S5_PG"])
            else:
                self.rep.check("pg-5v-gpios" not in node.props, f"slot{n}: no pg-5v-gpios (TPS2553 rail)")
            # lanes
            ioc = cells(node.props["io-channels"])
            prim = [(self.dt.phandle2node[ioc[i]], ioc[i + 1]) for i in range(0, len(ioc), 2)]
            self.rep.check(len(prim) == 4, f"slot{n}: four io-channels")
            names = node.props["io-channel-names"].to_strings()
            self.rep.check(names == ["AN0", "AN1", "AN2", "AN3"], f"slot{n}: io-channel-names AN0..AN3")
            for k, (adc, ch) in enumerate(prim):
                a = self.adc_index(adc)
                pin = self.c.adc_pin.get((a, ch))
                want = sm[f"AN{k}"]
                self.rep.check(pin == want, f"slot{n}: AN{k} = ADC{a} IN{ch} is {pin}, nets.SLOT_MCU {want}")
                first = self.c.lane_adc[want][0]
                self.rep.check(first == f"ADC{a}_IN{ch}",
                               f"slot{n}: AN{k} primary converter ADC{a}_IN{ch}, LANE_ADC first {first}")
                self.seen_nets.add(self.c.mcu_pins.get(want))
                self.adc_channel_node(adc, ch, f"slot{n} AN{k}")
            alt = cells(node.props["alt-adc-channels"]) if "alt-adc-channels" in node.props else []
            self.rep.check(len(alt) % 3 == 0, f"slot{n}: alt-adc-channels is triples")
            got = sorted((alt[i], alt[i + 1], alt[i + 2]) for i in range(0, len(alt) - 2, 3))
            want_alt = sorted((k, int(c[3]), int(c.split("_IN")[1])) for k in range(4)
                              for c in self.c.lane_adc[sm[f"AN{k}"]][1:])
            self.rep.check(got == want_alt, f"slot{n}: alt-adc-channels {got} == LANE_ADC alternates {want_alt}")
            for (k, a, ch) in got:
                adc = self.dt.label2node.get(f"adc{a}")
                if self.rep.check(adc is not None, f"slot{n}: alt ADC{a} node exists"):
                    self.adc_channel_node(adc, ch, f"slot{n} AN{k} alt")
            # monitors, mux channel, numbers
            for prop, rail in (("ina226-3v3", f"+3V3_S{n}"), ("ina226-5v", f"+5V_S{n}")):
                addr = node.props[prop].to_node().props["reg"].to_num()
                self.rep.check(self.c.ina.get(addr, ("?",))[0] == rail,
                               f"slot{n}: {prop} -> INA226 0x{addr:02x} ({self.c.ina.get(addr, ('?',))[0]}), "
                               f"expected {rail}")
            ch = node.props["i2c-channel"].to_node()
            self.rep.check(ch.props["reg"].to_num() == n - 1 and ch.parent.props["compatible"].to_string()
                           == "ti,tca9548a", f"slot{n}: i2c-channel is mux channel {n - 1}")
            for v, rail in (("3v3", f"+3V3_S{n}"), ("5v", f"+5V_S{n}")):
                rule = next(r[2] for r in self.c.ina.values() if r[0] == rail)
                self.rep.check(node.props[f"rule-{v}-milliamps"].to_num() == round(rule * 1000),
                               f"slot{n}: rule-{v}-milliamps == nets rule {rule} A")
                trip = [round(x * 1000) for x in self.c.trip[rail]]
                self.rep.check(node.props[f"trip-{v}-milliamps"].to_nums() == trip,
                               f"slot{n}: trip-{v}-milliamps == SWITCH_TRIP {trip}")
            self.rep.check(node.props["rail-3v3"].to_num() == n - 1 and node.props["rail-5v"].to_num() == 4 + n,
                           f"slot{n}: rail ids (tb/rails.h numbering)")

    def adc_channel_node(self, adc, ch, what):
        kids = [k for k in adc.nodes.values() if k.name.startswith("channel@")]
        hit = [k for k in kids if k.props.get("reg") and k.props["reg"].to_num() == ch]
        if not self.rep.check(len(hit) == 1, f"{what}: {label(adc)} has one channel node with reg {ch}"):
            return
        k = hit[0]
        self.rep.check(k.unit_addr == f"{ch:x}",
                       f"{what}: {label(adc)} {k.name}: unit address is hex of reg {ch} ({ch:x})")
        res = k.props["zephyr,resolution"].to_num()
        want = 12 if label(adc) == "adc4" else 14
        self.rep.check(res == want, f"{what}: {label(adc)} channel {ch} resolution {res}, expected {want}")

    def testbed(self):
        tb = self.dt.get_node("/testbed")
        known = set(self.c.pin_of_net) | {x for x in self.c.exp_pin_net.values() if x}
        for pname in sorted(p for p in tb.props if p.endswith("-gpios")):
            # "slot-fault-gpios" stands for SLOT_FAULT_N, "vsys-pg-gpios" for VSYS_PG
            base = pname[:-len("-gpios")].upper().replace("-", "_")
            want = base if base in known else base + "_N"
            self.rep.check(want in known, f"testbed: {pname} names a net of nets.py ({want})")
            self.check_gpio_prop(tb, pname, [want])
        for net in ("EXP_INT_N", "SLOT_FAULT_N", "PM_ALERT_N", "VSYS_PG", "S5_PG", "USBC_INT_N", "KVM_PRESENT_N",
                    "MUX_RST_N", "KVM_RST_N", "EN_5V_KVM", "SLOT_SYNC", "RIG_MARK", "RIG_TRIG"):
            prop = net.lower().replace("_", "-")
            prop = (prop[:-2] if prop.endswith("-n") else prop) + "-gpios"
            self.rep.check(prop in tb.props, f"testbed: {prop} present (the board service reads {net})")
        for prop, rail in (("ina226-vsys", "VSYS"), ("ina226-mcu", "+3V3_MCU"), ("ina226-usb", "+3V3_USB")):
            addr = tb.props[prop].to_node().props["reg"].to_num()
            self.rep.check(self.c.ina.get(addr, ("?",))[0] == rail, f"testbed: {prop} -> 0x{addr:02x} is {rail}")
        cc = tb.props["typec"].to_node()
        self.rep.check(cc.props["reg"].to_num() == self.c.ns["typec_address"](),
                       f"testbed: typec at 0x{cc.props['reg'].to_num():02x}")
        kvm = tb.props["kvm-i2c"].to_node()
        self.rep.check(kvm.props["reg"].to_num() == 5, "testbed: kvm-i2c is mux channel 5 (SPEC §4.5)")
        self.rep.check(tb.props["vsys-budget-max-milliamps"].to_num() == round(self.c.ns["VSYS_BUDGET_MAX"] * 1000),
                       "testbed: vsys-budget-max-milliamps == nets.VSYS_BUDGET_MAX")
        self.rep.check(tb.props["vsys-budget-unconfigured-milliamps"].to_num()
                       == round(self.c.ns["VSYS_BUDGET_UNCONFIGURED"] * 1000),
                       "testbed: vsys-budget-unconfigured-milliamps == nets.VSYS_BUDGET_UNCONFIGURED")
        self.rep.check(tb.props["vsys-trip-milliamps"].to_nums() == [round(x * 1000) for x in self.c.trip["VSYS"]],
                       "testbed: vsys-trip-milliamps == SWITCH_TRIP VSYS")
        self.rep.check(tb.props["vsys-budget-max-milliamps"].to_num() < tb.props["vsys-trip-milliamps"].to_nums()[0],
                       "testbed: the budget ceiling sits below the input breaker's minimum trip")

    def i2c(self):
        busmap = {"I2C_PM": "i2c1", "I2C_SLOT": "i2c4"}
        for bus, lab in busmap.items():
            node = self.dt.label2node[lab]
            kids = {k.props["reg"].to_num(): k for k in node.nodes.values() if "reg" in k.props}
            want = sorted(a for a, _ in self.c.buses[bus])
            have = sorted(kids)
            if self.kind == "sim" and bus == "I2C_SLOT":
                have = [a for a in have if kids[a].props["compatible"].to_string() != "prettycool,sim-eeprom"]
            self.rep.check(have == want, f"{lab}: device addresses {[hex(a) for a in have]} == nets {bus} "
                           f"{[hex(a) for a in want]}")
            for a, k in kids.items():
                self.rep.check(k.unit_addr == f"{a:x}", f"{lab}: {k.name} unit address is hex of reg 0x{a:02x}")
        i2c1 = self.dt.label2node["i2c1"]
        for k in i2c1.nodes.values():
            comp = k.props["compatible"].to_string()
            addr = k.props["reg"].to_num()
            if comp == "nxp,pca95xx":
                ref = self.c.exp_i2c.get(addr)
                self.rep.check(ref is not None, f"i2c1 0x{addr:02x}: an expander nets.EXPANDER_I2C knows")
                self.rep.check(k.props["ngpios"].to_num() == 16, f"{ref}: ngpios 16 (the binding defaults to 32)")
                for bad in ("has-pud", "has-interrupt-mask-reg"):
                    self.rep.check(bad not in k.props, f"{ref}: no {bad} (TCA9535 has no PCAL registers, SPEC §8.4)")
                has_int = "interrupt-gpios" in k.props
                owns_int = any((self.c.exp_pin_net.get((ref, i)) or "") in ("USBC_INT_N", "PM_ALERT_N", "SLOT_FAULT_N")
                               for i in range(16))
                self.rep.check(has_int == owns_int, f"{ref}: interrupt-gpios {'set' if has_int else 'unset'} "
                               f"(only on the expander with the interrupt inputs)")
                if has_int:
                    self.check_gpio_prop(k, "interrupt-gpios", ["EXP_INT_N"])
            elif comp == "ti,ina226":
                row = self.c.ina.get(addr)
                if not self.rep.check(row is not None, f"i2c1 0x{addr:02x}: an INA226 of nets.INA226_RAILS"):
                    continue
                rail, shunt, _rule = row
                uohm = k.props["rshunt-micro-ohms"].to_num()
                lsb = k.props["current-lsb-microamps"].to_num()
                self.rep.check(uohm == round(shunt * 1e6), f"INA226 0x{addr:02x} {rail}: rshunt {uohm} uohm == "
                               f"{shunt} ohm")
                self.rep.check(lsb == self.c.ina_lsb[addr], f"INA226 0x{addr:02x} {rail}: current LSB {lsb} uA "
                               f"== nets {self.c.ina_lsb[addr]}")
                den = lsb * uohm
                cal = (5120000000 + den // 2) // den      # Zephyr's DIV_ROUND_CLOSEST (ina226.c, v4.5.0)
                self.rep.check(0 < cal <= 0x7FFF, f"INA226 0x{addr:02x} {rail}: CAL {cal} fits 15 bits")
                # Current = Shunt x CAL / 2048 (SBOS547 Eq. 3): with CAL <= 2048 the current register stays
                # inside 15 bits for every shunt reading, up to the shunt register's own +32767 (81.9175 mV).
                self.rep.check(cal <= 2048, f"INA226 0x{addr:02x} {rail}: CAL {cal} <= 2048, so the current "
                               f"register cannot clip below the shunt's full scale")
                trip = self.c.trip.get(rail)
                if trip:
                    self.rep.check(32767 * lsb >= trip[2] * 1e6, f"INA226 0x{addr:02x} {rail}: current register "
                                   f"reaches the switch's maximum trip {trip[2]} A")
            elif comp == "prettycool,tusb320":
                self.rep.check(addr == self.c.ns["typec_address"](), f"U_CC at 0x{addr:02x}")
                self.check_gpio_prop(k, "int-gpios", [self.c.ns["TYPEC"]["int"]])
            else:
                self.rep.check(False, f"i2c1: unexpected device {k.path} ({comp})")
        mux = [k for k in self.dt.label2node["i2c4"].nodes.values()
               if k.props.get("compatible") and k.props["compatible"].to_string() == "ti,tca9548a"]
        if self.rep.check(len(mux) == 1, "i2c4: one TCA9548A"):
            m = mux[0]
            self.check_gpio_prop(m, "reset-gpios", ["MUX_RST_N"])
            regs = sorted(k.props["reg"].to_num() for k in m.nodes.values())
            self.rep.check(regs == list(range(8)), f"mux: channels {regs} == 0..7")
            for k in m.nodes.values():
                self.rep.check(k.unit_addr == f"{k.props['reg'].to_num():x}", f"mux: {k.name} unit address")

    def pinctrl(self, safety=True):
        """Every pinctrl-N entry of every node, decoded."""
        direct = set()
        for n in self.c.slots:
            for sig in ("CS0_N", "CS1_N", "IRQ_N", "G0", "G1", "G2", "G3", "G4", "G5"):
                if sig in self.c.slot_mcu[n]:
                    direct.add(self.c.slot_mcu[n][sig])
        claimed = {}
        for node in self.dt.node_iter():
            comp = node.props.get("compatible")
            if comp is not None and "swj-connector" in comp.to_strings():
                # the SoC's own SWJ pins; Zephyr applies them (to analog) only with CONFIG_PM and no CONFIG_DEBUG
                continue
            for pname, prop in node.props.items():
                if not re.match(r"^pinctrl-\d+$", pname):
                    continue
                for pc in prop.to_nodes():
                    name = pc.name
                    mux = pc.props["pinmux"].to_num()
                    port = chr(ord("A") + (mux >> PINMUX_PORT_SHIFT & 0x1F))
                    line = mux >> PINMUX_LINE_SHIFT & 0xF
                    mode = mux & PINMUX_MODE_MASK
                    full = self.c.mcu_pin_full(f"P{port}{line}")
                    where = f"{label(node)} {pname} {name}"
                    self.rep.check(name.endswith(f"_p{port.lower()}{line}"),
                                   f"{where}: pinmux decodes to P{port}{line}, the name agrees")
                    func = self.c.mcu_func.get(full)
                    if not self.rep.check(func is not None, f"{where}: P{port}{line} has an MCU_FUNC entry"):
                        continue
                    net = self.c.mcu_pins.get(full)
                    self.seen_nets.add(net)
                    lane = full in self.c.lane_adc
                    if lane:
                        ok_name = any(name == f"{c.lower()}_p{port.lower()}{line}" for c in self.c.lane_adc[full])
                        self.rep.check(ok_name, f"{where}: an ADC channel of LANE_ADC[{full}]")
                    else:
                        self.rep.check(name == func[2], f"{where}: MCU_FUNC[{full}] names {func[2]}")
                    want_mode = func[1]
                    if want_mode == "ANALOG":
                        self.rep.check(mode == PINMUX_ANALOG, f"{where}: analog mode ({net})")
                    else:
                        m = re.match(r"^AF(\d+)$", want_mode)
                        self.rep.check(m is not None and mode == int(m.group(1)),
                                       f"{where}: mode {mode:#x} == MCU_FUNC {want_mode} ({net})")
                    prefix = name.split("_")[0]
                    owner = PERIPH_OF_PREFIX.get(prefix, prefix)
                    self.rep.check(label(node) == owner, f"{where}: used by {label(node)}, the name says {owner}")
                    if okay(node) and (node.parent is None or okay(node.parent)):
                        if full in claimed and claimed[full] != label(node):
                            self.rep.check(False, f"{full}: claimed by enabled {claimed[full]} and {label(node)}")
                        claimed[full] = label(node)
                        if safety:
                            self.rep.check(full not in direct, f"{where}: enabled node does not drive the direct "
                                           f"slot line {full} ({net}) at init (SPEC §3.5)")

    def board_only(self):
        dt, rep = self.dt, self.rep
        # clocks (SPEC §8.1)
        hse = dt.label2node["clk_hse"]
        rep.check(okay(hse), "clk_hse enabled")
        rep.check(hse.props["clock-frequency"].to_num() == SPEC_HSE_HZ, "clk_hse 16 MHz (SPEC §5.2, §8.1)")
        rep.check("hse-bypass" not in hse.props, "clk_hse is a crystal, no hse-bypass (SPEC §5.2: DFU and PHY)")
        lse = dt.label2node["clk_lse"]
        rep.check(not okay(lse), "clk_lse not enabled (no LSE crystal; Zephyr waits for LSERDY forever, SPEC §8.1)")
        pll = dt.label2node["pll1"]
        rep.check(okay(pll), "pll1 enabled")
        rep.check(pll.props["clocks"].to_nodes()[0] is hse, "pll1 from clk_hse")
        vals = {k: pll.props[k].to_num() for k in SPEC_PLL1 if k in pll.props}
        rep.check(vals == SPEC_PLL1, f"pll1 {vals} == SPEC §8.1 {SPEC_PLL1}")
        rcc = dt.label2node["rcc"]
        rep.check(rcc.props["clocks"].to_nodes()[0] is pll, "rcc (SYSCLK) from pll1")
        if vals == SPEC_PLL1:
            sysclk = SPEC_HSE_HZ // vals["div-m"] * vals["mul-n"] // vals["div-r"]
            rep.check(sysclk == SPEC_SYSCLK_HZ == rcc.props["clock-frequency"].to_num(),
                      f"SYSCLK {sysclk} = rcc clock-frequency {rcc.props['clock-frequency'].to_num()} = 160 MHz")
        ahb = rcc.props["ahb-prescaler"].to_num()
        rep.check(ahb == 1, "AHB prescaler 1 (HCLK = SYSCLK: the ADC kernel clock, SPEC §6.2)")
        phy = dt.label2node["otghs_phy"]
        rep.check(okay(phy), "otghs_phy enabled")
        # the PHY's kernel clock: compare with STM32_SRC_HSE OTGHS_SEL(0) as the SoC header encodes it
        clk = cells(phy.props["clocks"])
        rep.check(len(clk) >= 6 and clk[4:6] == self.encoded_hse_otghs(),
                  f"otghs_phy kernel clock is <STM32_SRC_HSE OTGHS_SEL(0)> (SPEC §5.2: OTGHSSEL 00)")
        for lab in ("adc12_common", "adc4_common"):
            n = dt.label2node[lab]
            pre = n.props["st,adc-prescaler"].to_num()
            rep.check(pre == SPEC_ADC_PRESCALER and SPEC_SYSCLK_HZ // ahb // pre <= ADC_FMAX_HZ,
                      f"{lab}: prescaler {pre}, f_ADC {SPEC_SYSCLK_HZ // ahb // pre / 1e6:g} MHz <= 55 MHz")
        # buses and console
        ch = dt.get_node("/chosen")
        con = ch.props["zephyr,console"].to_path()
        rep.check(label(con) == "usart1", "console on usart1 (CON_TX/CON_RX, SPEC §8.3)")
        for lab in ("i2c1", "i2c4"):
            n = dt.label2node[lab]
            rep.check(n.props["clock-frequency"].to_num() == 400000, f"{lab} at 400 kHz (SPEC §3.4, §4.5)")
            prefix = "I2C_PM" if lab == "i2c1" else "I2C_SLOT"
            self.check_gpio_prop(n, "scl-gpios", [f"{prefix}_SCL"])
            self.check_gpio_prop(n, "sda-gpios", [f"{prefix}_SDA"])
            for pn in ("scl-gpios", "sda-gpios"):
                flags = self.gpio_specs(n.props[pn])[0][2]
                rep.check(flags & GPIO_OPEN_DRAIN == GPIO_OPEN_DRAIN,
                          f"{lab}: {pn} open drain (bus recovery drives them GPIO_OUTPUT_HIGH with these flags)")
        spi2 = dt.label2node["spi2"]
        rep.check("cs-gpios" not in spi2.props, "spi2 has no cs-gpios (the driver drives each CS high at init)")
        for lab in ("uart4", "timers1", "timers2", "timers8"):
            rep.check(not okay(dt.label2node[lab]), f"{lab} disabled (its pins are slot or KVM lines)")
        led = dt.label2node["status_led"]
        self.check_gpio_prop(led, "gpios", ["LED_N"])
        # every MCU I/O net appears somewhere
        missing = sorted(n for n in self.c.pin_of_net if n not in self.seen_nets and n not in NOT_IN_DTS)
        rep.check(not missing, f"every MCU I/O net is in the devicetree (missing: {missing})")

    def encoded_hse_otghs(self):
        zb = zephyr_base()
        with tempfile.TemporaryDirectory() as td:
            src = pathlib.Path(td) / "probe.dts"
            src.write_text("/dts-v1/;\n#include <zephyr/dt-bindings/clock/stm32u5_clock.h>\n"
                           "/ { probe = <STM32_SRC_HSE OTGHS_SEL(0)>; };\n")
            out = pathlib.Path(td) / "probe.pre"
            preprocess(zb, src, out)
            dt = load_dtlib(zb).DT(str(out))
            return cells(dt.root.props["probe"])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dts", type=pathlib.Path, help="a merged zephyr.dts from a build (default: the board dts)")
    ap.add_argument("--src", type=pathlib.Path, default=BOARD_DTS,
                    help="the board .dts to preprocess when --dts is not given (default: the generated one)")
    ap.add_argument("--nets", type=pathlib.Path, default=NETS)
    ap.add_argument("--sim", action="store_true", help="also check the native_sim overlay's slot, testbed and I2C "
                    "nodes against nets.py")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    zb = zephyr_base()
    dtlib = load_dtlib(zb)
    c = Contract(args.nets)
    total_fail = 0
    with tempfile.TemporaryDirectory() as td:
        targets = []
        if args.dts:
            targets.append(("board", args.dts))
        else:
            out = pathlib.Path(td) / "board.pre.dts"
            preprocess(zb, args.src.resolve(), out)
            targets.append(("board", out))
        if args.sim:
            out = pathlib.Path(td) / "sim.pre.dts"
            preprocess(zb, SIM_OVERLAY, out, prefix="/dts-v1/;\n")
            targets.append(("sim", out))
        for kind, path in targets:
            rep = Report(args.verbose)
            try:
                dt = dtlib.DT(str(path))
            except Exception as e:      # noqa: BLE001 - report any parse error as unreadable input
                print(f"check_dts: cannot parse {path}: {e}", file=sys.stderr)
                return 2
            print(f"check_dts: {kind} devicetree ({args.dts or (args.src if kind == 'board' else SIM_OVERLAY)})")
            ck = Checker(dt, c, rep, kind)
            ck.slots()
            ck.testbed()
            ck.i2c()
            if kind == "board":
                ck.pinctrl()
                ck.board_only()
            print(f"check_dts: {kind}: {rep.passes} checks pass, {len(rep.fails)} fail")
            total_fail += len(rep.fails)
    return 1 if total_fail else 0


if __name__ == "__main__":
    sys.exit(main())
