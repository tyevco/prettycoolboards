#!/usr/bin/env python3
"""Check the motherboard's generated netlist against the capture contract (nets.py).

usage: python keyboard/hardware/design/check_contract.py [path/to/prettycool-keyboard-motherboard.net]

The MCU (the gate the caliper's check_contract.py also runs): for the one STM32U5A5VJT6 in the netlist, every
nets.MCU_PINS entry must match the net on the pin of that name (KiCad's symbol names five pins differently;
nets.KICAD_PIN_ALIAS maps them back), every pin's number must carry the name nets.LQFP100 gives it, no MCU pin may be
connected without being listed, and every nets.POWER_NETS and nets.MOTHERBOARD_INTERSHEET net must exist.

The rest of the contract, by reference designator (the SPEC names the sheets use):
* the three expanders U_EXP1-3 pin for pin nets.EXPANDERS, and their A2-A0 straps = nets.EXPANDER_I2C;
* the mux U_MUX at 0x70 (A2-A0 to GND), channel n-1 = S<n>'s SCL/SDA, channel 5 = KVM_SCL/KVM_SDA;
* U_CC pin for pin nets.TYPEC_PINS;
* the INA226 at every nets.INA226_RAILS address (U_PM<addr>): A1/A0 strapped to that address (SBOS547 Table 6-2),
  VBUS on the rail, and Kelvin sense (owner's decision D4, 2026-11-27; SPEC §7.5): IN+ (pin 10) and IN- (pin 9) on
  the monitor's own sense pair nets.ina226_sense_nets(addr), each sense net carrying only that pin and one net tie
  (Device:NetTie_2) whose other pin is on the shunt's power net (nets.INA226_SHUNT_NETS), and one resistor of the
  rail's shunt value across the two power nets;
* each slot socket J_S<n> pin for pin nets.slot_pin_net(): the D3 series resistors' socket-side nets included, and
  the key pin 39 present with no net (D2); every nets.SLOT_SERIES line as one resistor of its value between
  slot_net(n, signal) and its socket-side net, which carries nothing but that resistor and the socket pin (D3); the
  lanes' 47 ohm to S<n>_AN<k>_ADC and its 1 nF to GND; the bus switch U_BS<n> joining SLOT_<sig> to S<n>_<sig> for
  SCK, MISO, MOSI, SYNC with all four ~OE on BUSEN_N_S<n>;
* U2's power-good divider nets.INPUT_PGTH_DIVIDER (VSYS_IN - U2_PGTH - GND) and the +3V3A damping leg
  nets.VDDA_DAMPING (+3V3A - R - VDDA_DAMP - C - GND), both D4;
* J_SWD, J_RIG (through nets.J_RIG_SERIES) and J_KVM pin for pin; nets.MCU_SIDE_PULLS as resistors.
Exit code 1 on any mismatch.

With no argument and no motherboard netlist yet, it says so and exits 0 (the motherboard is not captured): the gate
applies from the first motherboard build on. Adapted from caliper/hardware/design/check_contract.py.
"""

from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, HERE)

import sexpr  # noqa: E402

import nets  # noqa: E402

DEFAULT_NET = os.path.join(HERE, "..", "kicad", "motherboard", "prettycool-keyboard-motherboard.net")
MCU_VALUE_PREFIX = nets.MCU            # "STM32U5A5VJT6"


def _find(node, key):
    return [c for c in node[1:] if isinstance(c, list) and c and c[0] == key]


def _val(node, key):
    f = _find(node, key)
    return str(f[0][1]) if f else None


_SI = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "m": 1e-3, "k": 1e3, "M": 1e6, "R": 1.0, "": 1.0}


def value_of(text):
    """'100' -> 100, '44.2k' -> 44200, '0.47' -> 0.47, '20m' -> 0.02, '1R' -> 1, '10u' -> 1e-5; None otherwise."""
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([pnumkMR]?)", (text or "").strip())
    return float(m.group(1)) * _SI[m.group(2)] if m else None


def same_value(text, want):
    got = value_of(text)
    return got is not None and abs(got - want) <= 1e-6 * abs(want)


LIBPART = {}        # ref -> (lib, part) of the last netlist load()


def load(path):
    with open(path, encoding="utf-8") as f:
        tree = sexpr.parse(f.read())
    comps = {_val(c, "ref"): _val(c, "value") for c in _find(_find(tree, "components")[0], "comp")}
    LIBPART.clear()
    for c in _find(_find(tree, "components")[0], "comp"):
        src = _find(c, "libsource")
        LIBPART[_val(c, "ref")] = (_val(src[0], "lib"), _val(src[0], "part")) if src else (None, None)
    pins = {}       # (ref, pin name) -> set(net names)
    numbers = {}    # (ref, pin number) -> pin name
    pin_net = {}    # (ref, pin number) -> net short name (None: unconnected)
    all_nets = set()
    for n in _find(_find(tree, "nets")[0], "net"):
        name = _val(n, "name")
        short = name.rsplit("/", 1)[-1] if not name.startswith("unconnected-") else None
        if short:
            all_nets.add(short)
        for node in _find(n, "node"):
            pin, func = _val(node, "pin"), _val(node, "pinfunction")
            # KiCad 10 writes pinfunction as "<pin name>_<pin number>"
            if func and pin and func.endswith("_" + pin):
                func = func[:-len(pin) - 1]
            ref = _val(node, "ref")
            pins.setdefault((ref, func or pin), set()).add(short)
            numbers[(ref, pin)] = func or pin
            pin_net[(ref, pin)] = short
    return comps, pins, numbers, pin_net, all_nets


def check_mcu(comps, pins, numbers, all_nets):
    errs = []
    mcus = [r for r, v in comps.items() if v and v.startswith(MCU_VALUE_PREFIX)]
    if len(mcus) != 1:
        return [f"expected one {MCU_VALUE_PREFIX}* part, found {mcus}"], None
    u = mcus[0]
    alias = nets.KICAD_PIN_ALIAS
    seen = {}
    for (ref, func), netset in pins.items():
        if ref == u:
            seen.setdefault(alias.get(func, func), set()).update(netset)
    for (ref, num), func in numbers.items():
        if ref == u and num.isdigit():
            want = nets.LQFP100.get(int(num))
            if alias.get(func, func) != want:
                errs.append(f"{u} pin {num}: the symbol calls it {func}, LQFP100 says {want}")
    for name, want in nets.MCU_PINS.items():
        got = seen.get(name)
        if got is None:
            errs.append(f"{u} pin {name}: not in the netlist")
        elif got != {want}:
            errs.append(f"{u} pin {name}: netlist {sorted(map(str, got))}, contract {want!r}")
    for name, got in seen.items():
        if name not in nets.MCU_PINS and got != {None}:
            errs.append(f"{u} pin {name}: connected to {sorted(map(str, got))} but not in nets.MCU_PINS")
    for net in list(nets.POWER_NETS) + list(nets.MOTHERBOARD_INTERSHEET):
        if net not in all_nets:
            errs.append(f"contract net {net} missing from the netlist")
    return errs, u


def check_board(comps, numbers, pin_net):
    """The non-MCU part of the contract (see the module docstring)."""
    errs = []
    by_name = {}                                          # (ref, pin name) -> pin number
    for (ref, num), name in numbers.items():
        by_name.setdefault((ref, name), num)

    def net(ref, pin):
        if (ref, str(pin)) not in pin_net:
            errs.append(f"{ref} pin {pin}: not in the netlist")
            return "?"
        return pin_net[(ref, str(pin))]

    def named(ref, name):
        num = by_name.get((ref, name))
        if num is None:
            errs.append(f"{ref}: no pin named {name}")
            return "?"
        return pin_net[(ref, num)]

    def expect(what, got, want):
        if got != want:
            errs.append(f"{what}: netlist {got!r}, contract {want!r}")

    def two_pin(value, a, b):
        """Refs of 2-pin parts of this value between nets a and b (either way round). value: the netlist's text, or
        a number compared with the text's value (value_of())."""
        out = []
        for ref, v in comps.items():
            if (ref, "1") not in pin_net or (ref, "3") in pin_net:
                continue
            if (v != value) if isinstance(value, str) else not same_value(v, value):
                continue
            if {pin_net.get((ref, "1")), pin_net.get((ref, "2"))} == {a, b}:
                out.append(ref)
        return out

    members = {}                                          # net -> {(ref, pin)}
    for (ref, num), nn in pin_net.items():
        if nn:
            members.setdefault(nn, set()).add((ref, num))

    # expanders: pin map and address straps
    lvl = {"GND": 0, "+3V3": 1}
    for ref, pinmap in nets.EXPANDERS.items():
        if ref not in comps:
            errs.append(f"{ref} missing")
            continue
        for port, want in pinmap.items():
            got = named(ref, port)
            if want is None:
                if got in nets.INTERSHEET or got in nets.POWER_NETS:
                    errs.append(f"{ref} {port}: spare in the contract but on {got}")
            else:
                expect(f"{ref} {port}", got, want)
        bits = [lvl.get(named(ref, a)) for a in ("A0", "A1", "A2")]
        addr = None if None in bits else 0x20 + bits[0] + 2 * bits[1] + 4 * bits[2]
        if nets.EXPANDER_I2C.get(addr, "").split()[:1] != [ref]:
            errs.append(f"{ref}: A2-A0 strap 0x{addr or 0:02X}, contract {nets.EXPANDER_I2C}")
        expect(f"{ref} SCL", named(ref, "SCL"), "I2C_PM_SCL")
        expect(f"{ref} SDA", named(ref, "SDA"), "I2C_PM_SDA")

    # the mux
    if "U_MUX" in comps:
        bits = [lvl.get(named("U_MUX", a)) for a in ("A0", "A1", "A2")]
        if bits != [0, 0, 0] or 0x70 not in nets.I2C_SLOT_UPSTREAM:
            errs.append(f"U_MUX: A2-A0 = {bits}, contract 0x70")
        expect("U_MUX SCL", named("U_MUX", "SCL"), "I2C_SLOT_SCL")
        expect("U_MUX SDA", named("U_MUX", "SDA"), "I2C_SLOT_SDA")
        expect("U_MUX ~RESET", named("U_MUX", "~{RESET}"), "MUX_RST_N")
        for n in nets.SLOTS:
            expect(f"U_MUX SC{n - 1}", named("U_MUX", f"SC{n - 1}"), f"S{n}_SCL")
            expect(f"U_MUX SD{n - 1}", named("U_MUX", f"SD{n - 1}"), f"S{n}_SDA")
        expect("U_MUX SC5", named("U_MUX", "SC5"), "KVM_SCL")
        expect("U_MUX SD5", named("U_MUX", "SD5"), "KVM_SDA")
    else:
        errs.append("U_MUX missing")

    # U_CC
    for pin, (name, want) in nets.TYPEC_PINS.items():
        expect(f"{nets.TYPEC['ref']} pin {pin} ({name})", net(nets.TYPEC["ref"], pin), want)

    # INA226s: address straps, rail, shunt
    strap = {"GND": 0, "+3V3": 1, "I2C_PM_SDA": 2, "I2C_PM_SCL": 3}
    for addr, (rail, shunt, _rule) in nets.INA226_RAILS.items():
        ref = f"U_PM{addr:02X}"
        if ref not in comps:
            errs.append(f"{ref} (INA226 0x{addr:02X}) missing")
            continue
        a1, a0 = strap.get(net(ref, 1)), strap.get(net(ref, 2))
        if a1 is None or a0 is None or 0x40 + 4 * a1 + a0 != addr:
            errs.append(f"{ref}: A1/A0 = {net(ref, 1)}/{net(ref, 2)} do not give 0x{addr:02X}")
        expect(f"{ref} VBUS", net(ref, 8), rail)
        expect(f"{ref} VS", net(ref, 6), "+3V3")
        expect(f"{ref} SDA", net(ref, 4), "I2C_PM_SDA")
        expect(f"{ref} SCL", net(ref, 5), "I2C_PM_SCL")
        expect(f"{ref} ALERT", net(ref, 3), "PM_ALERT_N")
        # Kelvin sense (D4): IN+ / IN- on the monitor's own sense nets, each joined to its shunt pad by one net tie
        sense = nets.ina226_sense_nets(addr)
        expect(f"{ref} IN+ (pin 10)", net(ref, 10), sense[0])
        expect(f"{ref} IN- (pin 9)", net(ref, 9), sense[1])
        power = nets.INA226_SHUNT_NETS[addr]
        for sn_, pw, pin in ((sense[0], power[0], "10"), (sense[1], power[1], "9")):
            others = sorted(members.get(sn_, set()) - {(ref, pin)})
            ties = [r for r, _p in others if LIBPART.get(r, (None, None))[1] == "NetTie_2"]
            if len(others) != 1 or len(ties) != 1:
                errs.append(f"{ref}: sense net {sn_} must carry only pin {pin} and one net tie, has {others}")
                continue
            tie = ties[0]
            far = {pin_net.get((tie, "1")), pin_net.get((tie, "2"))} - {sn_}
            if far != {pw}:
                errs.append(f"{ref}: net tie {tie} joins {sn_} to {sorted(map(str, far))}, contract {pw}")
        shunts = [r for r, v in comps.items() if {pin_net.get((r, "1")), pin_net.get((r, "2"))} == set(power)
                  and (r, "3") not in pin_net and LIBPART.get(r, (None, None))[1] == "R"]
        if len(shunts) != 1 or not same_value(comps[shunts[0]], shunt):
            errs.append(f"{ref}: shunt across {power} is {[(r, comps[r]) for r in shunts]}, contract {shunt} ohm")

    # slot sockets, lanes, bus switches
    for n in nets.SLOTS:
        j, bs = f"J_S{n}", f"U_BS{n}"
        for pin, sig, _d, _note in nets.SLOT_PINS:
            expect(f"{j} pin {pin} ({sig})", net(j, pin), nets.slot_pin_net(n, pin))
        # D2: the key pin is there (its pad stays) and carries no net; no slot net is named after it
        key = nets.SLOT_KEY_PIN
        if (j, str(key)) not in pin_net or pin_net[(j, str(key))] is not None:
            errs.append(f"{j} pin {key} (KEY): must be present and unconnected, netlist "
                        f"{pin_net.get((j, str(key)), 'missing')!r}")
        for sig in nets.NO_NET_SIGNALS:
            if f"S{n}_{sig}" in members:
                errs.append(f"S{n}: net S{n}_{sig} exists, but the key pin carries no net (D2)")
        # D3: one series resistor of the contract's value between the MCU side and the socket side of every
        # SLOT_SERIES line; the socket side carries only that resistor and the socket pin
        pin_of = {sig: pin for pin, sig, _d, _note in nets.SLOT_PINS}
        for sig, (sock, ohms) in nets.SLOT_SERIES[n].items():
            mcu = nets.slot_net(n, sig)
            rr = two_pin(float(ohms), mcu, sock)
            if len(rr) != 1:
                errs.append(f"S{n} {sig}: no single {ohms} ohm between {mcu} and {sock} ({rr})")
                continue
            want = {(j, str(pin_of[sig])), *((rr[0], p) for p in ("1", "2") if pin_net.get((rr[0], p)) == sock)}
            if members.get(sock, set()) != want:
                errs.append(f"S{n} {sig}: socket-side net {sock} carries {sorted(members.get(sock, set()))}, "
                            f"contract only {sorted(want)}")
            if (j, str(pin_of[sig])) in members.get(mcu, set()):
                errs.append(f"S{n} {sig}: the socket pin is on the MCU-side net {mcu}")
        for k in range(4):
            a, b = f"S{n}_AN{k}", nets.mcu_net(n, f"AN{k}")
            if len(two_pin("47", a, b)) != 1:
                errs.append(f"S{n} AN{k}: no single 47 ohm between {a} and {b}")
            if len(two_pin("1n", b, "GND")) != 1:
                errs.append(f"S{n} AN{k}: no single 1 nF from {b} to GND")
        for sig in nets.BUS_SWITCHED:
            a, b = nets.mcu_net(n, sig), nets.slot_net(n, sig)
            chans = {named(bs, f"{c}A"): named(bs, f"{c}B") for c in "1234"}
            if chans.get(a) != b:
                errs.append(f"{bs}: {a} is not switched to {b} ({chans})")
        for c in "1234":
            expect(f"{bs} ~{c}OE", named(bs, f"~{{{c}OE}}"), f"BUSEN_N_S{n}")
        if {net(f"JP_INJ{n}", 1), net(f"JP_INJ{n}", 2)} != {"RIG_INJ", nets.slot_net(n, "INJ")}:
            errs.append(f"JP_INJ{n} does not join RIG_INJ and S{n}_INJ")

    # D4: U2's power-good divider and the +3V3A damping leg
    top, bot = nets.INPUT_PGTH_DIVIDER
    for what, val, a, b_ in (("PGTH top", top, "VSYS_IN", "U2_PGTH"), ("PGTH bottom", bot, "U2_PGTH", "GND")):
        if len(two_pin(val, a, b_)) != 1:
            errs.append(f"U2 {what}: no single {val:g} ohm between {a} and {b_}")
    leg, ohms, farads = nets.VDDA_DAMPING
    rr = [r for r in two_pin(ohms, "+3V3A", leg) if LIBPART.get(r, (None, None))[1] == "R"]
    cc = [r for r in two_pin(farads, leg, "GND") if LIBPART.get(r, (None, None))[1] == "C"]
    if len(rr) != 1 or len(cc) != 1 or len(members.get(leg, ())) != 2:
        errs.append(f"+3V3A damping leg: want one {ohms:g} ohm +3V3A-{leg} and one {farads:g} F {leg}-GND and "
                    f"nothing else on {leg}; netlist R {rr}, C {cc}, {leg} {sorted(members.get(leg, ()))}")

    # headers
    for ref, table, fn in (("J_SWD", nets.J_SWD_PINS, None), ("J_KVM", nets.J_KVM_PINS, None),
                           ("J_RIG", nets.J_RIG_PINS, nets.j_rig_pin_net)):
        for pin, want in table.items():
            expect(f"{ref} pin {pin}", net(ref, pin), fn(pin) if fn else want)
    for sig, (j_net, ohms) in nets.J_RIG_SERIES.items():
        if len(two_pin({33: "33"}[ohms], sig, j_net)) != 1:
            errs.append(f"J_RIG: no single {ohms} ohm between {sig} and {j_net}")
    rail, ohms = nets.RIG_VREF
    if len(two_pin({1000: "1k"}[ohms], rail, "RIG_VREF")) != 1:
        errs.append(f"RIG_VREF: no single {ohms} ohm from {rail}")
    for n_, (to, ohms) in nets.MCU_SIDE_PULLS.items():
        if len(two_pin({100e3: "100k"}[ohms], n_, to)) != 1:
            errs.append(f"{n_}: no single {ohms:g} ohm pull to {to}")
    return errs


def main():
    explicit = len(sys.argv) > 1
    path = sys.argv[1] if explicit else DEFAULT_NET
    if not os.path.exists(path):
        if explicit:
            print(f"{path}: not found")
            return 1
        print(f"SKIP: {os.path.normpath(path)} does not exist yet (motherboard not captured)")
        return 0
    comps, pins, numbers, pin_net, all_nets = load(path)
    errs, u = check_mcu(comps, pins, numbers, all_nets)
    mcu_errs = len(errs)
    errs += check_board(comps, numbers, pin_net)
    for e in errs:
        print("CONTRACT:", e)
    print(f"{os.path.basename(path)}: {u} checked against {len(nets.MCU_PINS)} nets.MCU_PINS entries -> "
          + ("OK" if not mcu_errs else f"{mcu_errs} mismatch(es)"))
    n_series = sum(len(v) for v in nets.SLOT_SERIES.values())
    print(f"{os.path.basename(path)}: expanders, mux, U_CC, {len(nets.INA226_RAILS)} INA226s with Kelvin ties, "
          f"{len(nets.SLOTS)} slots (sockets with the pin {nets.SLOT_KEY_PIN} key, {n_series} series resistors, lanes, "
          f"bus switches), PGTH divider, +3V3A damping leg, J_SWD / J_RIG / J_KVM, MCU-side pulls -> "
          + ("OK" if len(errs) == mcu_errs else f"{len(errs) - mcu_errs} mismatch(es)"))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
