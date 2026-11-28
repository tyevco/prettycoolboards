#!/usr/bin/env python3
"""Compiler v0's coupon rules check: a coupon's generated KiCad files and its descriptor against SPEC §2, §4 and
§4.9 (keyboard/hardware/design/SPEC.md), the slot contract in nets.py and the slot geometry in
boards/coupon_common.py.

usage:
    python keyboard/tools/coupon/rules.py                    # every generated coupon under keyboard/hardware/kicad/
    python keyboard/tools/coupon/rules.py test-coupon        # named boards
    python keyboard/tools/coupon/rules.py --all              # also list the coupons not generated yet (SKIP)
    python keyboard/tools/coupon/rules.py --net X.net --pcb X.kicad_pcb --desc X.json    # explicit files
    options: --kicad-dir DIR --desc-dir DIR --json OUT.json --quiet (only WARN and FAIL rows)

Per coupon it prints one row per rule: PASS, FAIL, WARN (a judgement or heuristic: look at it), INFO (a figure worth
knowing) or SKIP (an input is missing). Exit code 1 if any coupon has a FAIL (a missing descriptor is one), 2 if no
coupon could be checked at all.

What it reads: the netlist (keyboard/hardware/kicad/<board>/<project>.net) for connectivity, the board
(<project>.kicad_pcb, through pcbnew) for geometry, and the coupon's descriptor JSON
(keyboard/tools/coupon/descriptors/<board>.json) for what the coupon declares. See README.md for what each rule can
and cannot catch. Status: the checker is tested on synthetic fixtures (tests/) and run on the generated boards; no
coupon has been built, so nothing here is a measurement.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True        # before the imports below: no __pycache__ in the tree
sys.path.insert(0, HERE)

import coupon_model as M  # noqa: E402  (sets sys.path for nets.py, tools/sexpr.py, boards/)
import descriptor as D  # noqa: E402

import nets  # noqa: E402  keyboard/hardware/design/nets.py, the slot contract

DESC_DIR = os.path.join(HERE, "descriptors")

# Coupon boards (keyboard/hardware/design/sheets/__init__.py PROJECTS): every slot coupon. The motherboard and the
# latency rig are not coupons.
COUPON_BOARDS = ["test-coupon", "coupon-hall", "coupon-tmr", "coupon-shear", "coupon-coil", "coupon-haptics"]

# --- the rules' numbers, each with its source -----------------------------------------------------------------
SIZE_TOL = 0.05                # mm: outline against the size class (boards/coupon_common.py sets the exact sizes)
PIN_TOL = 0.02                 # mm: each header pad against its slot position (the socket is solved to 1e-4)
POST_TOL = 0.05                # mm: the post hole's position and drill
KEEP_TOL = 0.02                # mm: KiCad draws the post's rule area as a 36-gon inside r (3.0 x cos 5 deg = 2.989)
THICKNESS = (1.6, 0.05)        # mm, SPEC §2 (4-layer, 1.6 mm)
COPPER_LAYERS = 4              # SPEC §2: "analog coupons want a solid ground layer"
GND_PLANE_MIN = 0.80           # fraction of the outline filled with GND on In1 (a heuristic for "solid", SPEC §4.9)
RAIL_RULE_MA = {"+3V3": {n: 250 for n in nets.SLOTS},                      # SPEC §4.9
                "+5V": {n: (2000 if n == 5 else 500) for n in nets.SLOTS}}
BULK_RULE_UF = {"+3V3": {n: 47 for n in nets.SLOTS},                       # SPEC §4.9 (proposals)
                "+5V": {n: (470 if n == 5 else 100) for n in nets.SLOTS}}
SLOT_LDO_MA = 300              # SPEC §3.2: the 3.3 V slot LDO's total budget (all slots)
BASE_LOAD_MA = 45              # SPEC §3.2: the board's base load (estimate)
# SPEC §3.2's VSYS budget per USB-C advertisement after configuration, from nets.vsys_budget itself
SOURCE_BUDGETS_MA = [(label, round(nets.vsys_budget(adv) * 1000))
                     for label, adv in (("Default", "default"), ("1.5 A", "1.5A"), ("3.0 A", "3.0A"))]
DEFAULT_SOURCE_MA = SOURCE_BUDGETS_MA[0][1]
# A declared R_src may be at most this much stiffer than the coupon's own resistors make it: 1 % resistors plus
# rounding. The firmware samples for (R_src + 47) x 1 nF x ln 2^15; with the real tau k times longer the lane settles
# to only 15 / k bits (k = 1.1 already leaves 13.6 bits), so the old 10 % band was too loose for a 14-bit lane.
RSRC_TOL = 0.03
LANE_R_OHM = 47                # SPEC §4.3: the motherboard's series resistor on each lane
LANE_C_PF = 1000               # SPEC §4.3: the motherboard's lane capacitor, C0G at the MCU pin
ADC_R_MAX_OHM = 1000           # SPEC §4.9: DS13543 Table 97, 1 kOhm at most
SETTLE_BITS = 15               # SPEC §4.9: (R_src + 47) x 1 nF x ln 2^15 per select step
I2C_MUX_ADDR = 0x70            # SPEC §4.5: the TCA9548A, visible on every channel
SLOT_PULLUP_OHM = 4700         # SPEC §4.2: the slot's I2C pull-ups on the motherboard
EEPROM_RE = re.compile(r"(M24C02|24(AA|LC|C|CS|FC)02|AT24C02|CAT24C02|BR24\w*02|FT24C02|GT24C02)", re.I)
I2C_PASSIVE_PREFIXES = {"R", "C", "TP", "JP", "SJ", "J", "P", "FID", "H", "L", "FB", "D", "#FLG", "#PWR"}
PASSIVE_PREFIXES = {"R", "C", "TP", "JP", "SJ", "FID", "H", "L", "FB", "#FLG", "#PWR"}

PIN_KIND = {}                  # header pin -> (slot signal, kind) from nets.SLOT_PINS
for _pin, _sig, _dir, _note in nets.SLOT_PINS:
    PIN_KIND[_pin] = (_sig, {"pwr": "rail", "gnd": "gnd", "nc": "nc"}.get(_dir, "signal"))
PIN_KIND[32] = ("PRESENT_N", "present")
SIGNAL_PINS = {sig: pin for pin, (sig, kind) in PIN_KIND.items() if kind in ("signal", "present")}
RAIL_PINS = {"+5V": [p for p, (s, _k) in PIN_KIND.items() if s == "+5V"],
             "+3V3": [p for p, (s, _k) in PIN_KIND.items() if s == "+3V3"]}
GND_PINS = [p for p, (_s, k) in PIN_KIND.items() if k == "gnd"]
# The slot key (the owner's decision D2 of 2026-11-27; SPEC §4.2, §4.9; nets.SLOT_KEY_PIN): no pin 39 on any coupon
# (no pad, no net; the header's pin pulled before soldering) and socket hole 39 plugged. Turned 180 degrees, coupon
# pin 2 meets the plug, so pin 2 must stay a real pin (nets.SLOT_KEY_NEVER_WITH).
KEY_PIN = nets.SLOT_KEY_PIN
KEY_NEVER_WITH = nets.SLOT_KEY_NEVER_WITH

# The slot's direct lines (the owner's decision D3 of 2026-11-27; SPEC §4.3; nets.SLOT_SERIES): 100 ohm in series at
# each socket on CS0_N, CS1_N, IRQ_N, G0-G3 and S5's G4/G5, then straight to an MCU pin. The lanes keep their 47 ohm +
# 1 nF (LANE_R_OHM, LANE_C_PF: D3 puts no resistor on a lane; tests check nets.SLOT_SERIES against that).
SERIES_LINES = sorted({sig for n in nets.SLOTS for sig in nets.SLOT_SERIES[n]}, key=lambda s: SIGNAL_PINS[s])
MCU_VDD = 3.3                  # V: the MCU's VDD (+3V3_MCU), which its slot pins drive to
MCU_R_DRV = 50.0               # ohm: DS13543 Rev 2 Table 88, V_OH >= VDD - 0.4 V and V_OL <= 0.4 V at |I_IO| = 8 mA,
                               # so at most 50 ohm while within 8 mA (an estimate of the output driver)
MCU_I_SPEC_MA = 8.0            # mA: the |I_IO| at which Table 88 specifies those levels ("up to +-8 mA", §5.3.15)
IDLE_LOW_INPUTS = ("INJ",)     # slot inputs that idle low or open: INJ through JP_INJn, open by default (SPEC §4.7)
SLOT_LINE_C_PF = 40            # pF: SPEC §4.3's worst case behind the 100 ohm (socket, header, about 60 mm of coupon
                               # track, logic inputs): the figure its timing check (tau = 4 ns) is done for


def coupon_net(signal):
    """The coupon-side net name of a slot signal (keyboard/hardware/design/sheets/coupon_common.py): None for the
    key pin (nets.NO_NET_SIGNALS: 'KEY', formerly 'RSV')."""
    return "GND" if signal in ("GND", "PRESENT_N") else (None if signal in nets.NO_NET_SIGNALS else signal)


# ---------------------------------------------------------------------------------------------------- findings
class Report:
    def __init__(self, name):
        self.name = name
        self.rows = []                                # (rule, result, detail)

    def add(self, rule, result, detail=""):
        self.rows.append((rule, result, detail))

    def ok(self, rule, detail=""):
        self.add(rule, "PASS", detail)

    def fail(self, rule, detail):
        self.add(rule, "FAIL", detail)

    def warn(self, rule, detail):
        self.add(rule, "WARN", detail)

    def info(self, rule, detail):
        self.add(rule, "INFO", detail)

    def skip(self, rule, detail):
        self.add(rule, "SKIP", detail)

    def results(self, rule_prefix=""):
        return [r for rule, r, _d in self.rows if rule.startswith(rule_prefix)]

    def result(self, rule):
        """The worst result of the rows whose rule is `rule` (or starts with `rule.`)."""
        order = ["FAIL", "WARN", "SKIP", "INFO", "PASS"]
        got = [r for ru, r, _d in self.rows if ru == rule or ru.startswith(rule + ".")]
        return min(got, key=order.index) if got else None

    @property
    def failed(self):
        return any(r == "FAIL" for _ru, r, _d in self.rows)

    def table(self, quiet=False, width=118):
        rows = [r for r in self.rows if not quiet or r[1] in ("FAIL", "WARN")]
        w1 = max([len("Rule")] + [len(r[0]) for r in rows])
        head = f"{'Rule':<{w1}}  Result  Detail"
        out = [f"== {self.name}", head, "-" * min(width, max(len(head), 40))]
        dw = max(30, width - w1 - 10)
        for rule, res, det in rows:
            lines = textwrap.wrap(det, dw) or [""]
            out.append(f"{rule:<{w1}}  {res:<6}  {lines[0]}")
            out += [f"{'':<{w1}}  {'':<6}  {ln}" for ln in lines[1:]]
        n = {k: sum(1 for r in self.rows if r[1] == k) for k in ("FAIL", "WARN", "PASS", "INFO", "SKIP")}
        out.append(f"-> {self.name}: " + ", ".join(f"{v} {k}" for k, v in n.items() if v)
                   + ("  ** FAILED **" if self.failed else ""))
        return "\n".join(out)


# --------------------------------------------------------------------------------------------- value parsing
_SI = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "μ": 1e-6, "m": 1e-3, "": 1.0}


def parse_cap(value):
    """'10u', '22u/25V', '100n', '4.7uF', '2u2', '1µF 16V' -> farads; None if not a capacitance."""
    v = (value or "").strip().replace(",", ".")
    m = re.match(r"^(\d+)([pnuµμm])(\d+)", v)                 # RKM: 2u2, 4n7
    if m:
        return float(f"{m.group(1)}.{m.group(3)}") * _SI[m.group(2)]
    m = re.match(r"^(\d+(?:\.\d+)?)\s*([pnuµμm]?)F?(?![a-zA-Z])", v)
    if m:
        return float(m.group(1)) * _SI[m.group(2)]
    return None


def fmt_uf(f):
    return f"{f * 1e6:.3g} uF"


# ------------------------------------------------------------------------------------------------ the checks
class Coupon:
    """Everything the rules look at for one coupon. Any of net, board, desc may be None."""

    def __init__(self, name, net=None, board=None, desc=None, desc_path=None, geometry=None):
        self.name, self.net, self.board, self.desc, self.desc_path = name, net, board, desc, desc_path
        self.geometry = geometry
        self.canon = None                              # the descriptor as an image would carry it
        self.header_ref = None                         # J1 in the netlist
        self.eeprom = None

    # -- helpers on the netlist
    def header_in_net(self):
        n = self.net
        cands = [c for c in n.comps.values()             # 40 pins, or fewer with the key (D2: no pin 39)
                 if len(c.pins) in (38, 39, 40) or len({p for (r, p) in n.pin_net if r == c.ref}) in (38, 39, 40)]
        cands = [c for c in cands if c.prefix in ("J", "P", "CN")] or cands
        if len(cands) == 1:
            return cands[0].ref
        if "J1" in n.comps:
            return "J1"
        return cands[0].ref if cands else None

    def hpin_net(self, pin):
        return self.net.net_of(self.header_ref, pin)

    def header_pin_numbers(self):
        """The pin numbers the header's symbol has in the netlist (its pin table and its nodes), as ints."""
        h = self.net.comps.get(self.header_ref)
        nums = set(h.pins) if h else set()
        nums |= {p for (r, p) in self.net.pin_net if r == self.header_ref}
        return {int(p) for p in nums if str(p).isdigit()}

    def kind_of(self, ref):
        return self.net.comps[ref].prefix if ref in self.net.comps else ""

    def is_stub(self, netname):
        """A net with nothing on it but header pins."""
        return all(r == self.header_ref for r, _p in self.net.members(netname))

    def fitted_members(self, netname):
        """The net's members other than the header, without parts marked DNP (not fitted at assembly)."""
        return [(r, p) for r, p in self.net.members(netname) if r != self.header_ref and self.net.fitted(r)]

    def dnp_members(self, netname):
        return sorted({r for r, _p in self.net.members(netname) if r != self.header_ref and not self.net.fitted(r)})

    def two_pin(self, prefix, fitted=True):
        """(comp, [net, net]) for every two-pin part of this prefix (R, C, ...), fitted ones only by default."""
        for x in self.net.comps.values():
            if x.prefix == prefix and len(x.pins) == 2 and (not fitted or not x.dnp):
                yield x, [self.net.net_of(x.ref, p) for p in x.pins]

    def ac_grounds(self):
        """GND, +3V3 and every other rail: AC ground for a lane's source impedance."""
        return {"GND"} | self.rails() | {x for x in self.net.nets if M.net_base(x) == "+3V3"}

    def rails(self):
        """Nets that are power rails on the coupon, other than +3V3: +5V, '+'-named nets, power_out pins."""
        out = set()
        for name in self.net.nets:
            base = M.net_base(name)
            if base in ("+3V3", "GND"):
                continue
            if base.startswith("+") or any(self.net.pin_type.get(m) == "power_out" for m in self.net.nets[name]):
                out.add(name)
        return out


def check(c, report=None):
    """Run every rule that its inputs allow. Returns the Report."""
    r = report or Report(c.name)
    if c.desc is not None:
        check_descriptor(c, r)
    else:
        r.fail("desc", "no descriptor JSON for this coupon (every coupon carries a descriptor, SPEC §4.6): "
                       f"write {os.path.relpath(os.path.join(DESC_DIR, c.name + '.json'), M.REPO)}")
    if c.net is not None:
        check_netlist(c, r)
    else:
        r.skip("net", "no netlist: run keyboard/hardware/design/build.py --board " + c.name)
    if c.board is not None:
        check_board(c, r)
    else:
        r.skip("pcb", "no board read (not generated, or pcbnew not importable here): run "
                      "keyboard/hardware/design/layout.py --board " + c.name)
    if c.net is not None and c.canon is not None:
        check_declared(c, r)
    return r


# ---- the descriptor on its own (also what make_eeprom.py runs before it writes an image) ----------------------
def check_descriptor(c, r):
    d = c.desc
    try:
        dd = dict(d)
        if str(dd.get("git", "")).lower() == "auto":
            dd["git"] = "0" * 16                      # resolved by make_eeprom.py; not a rule
        c.canon = D.canonical(dd)
        r.ok("desc.format", f"encodes to a valid {D.SIZE}-byte format {D.FORMAT_MAJOR}.{D.FORMAT_MINOR} image "
                            "and decodes to the same fields")
    except D.DescriptorError as e:
        r.fail("desc.format", str(e))
        return
    k = c.canon
    ph = "placeholder" in k["flags"]
    if ph:
        fields = d.get("placeholder_fields", [])
        r.warn("desc.placeholder", "the descriptor is marked placeholder: its values are not from a captured "
                                   "design" + (f" (placeholder fields: {', '.join(fields)})" if fields else ""))
    elif d.get("placeholder_fields"):
        r.info("desc.placeholder", "estimated fields: " + ", ".join(d["placeholder_fields"]))
    if c.name and d.get("board") and d["board"] != c.name:
        r.fail("desc.board", f"the descriptor says board {d['board']!r}, checked as {c.name!r}")

    slots = k["slots"]
    comp = D.compatible_slots(k["size"], k["needs"])
    if not slots:
        r.fail("slots", "slot_mask is empty: the firmware would refuse every slot")
    elif set(slots) - set(comp):
        r.fail("slots", f"slots {sorted(set(slots) - set(comp))} cannot take a {k['size']} coupon with needs "
                        f"{k['needs']} (compatible: {comp})")
    elif k["default_slot"] not in slots:
        r.fail("slots", f"default slot S{k['default_slot']} is not in its slots {slots}")
    else:
        r.ok("slots", f"S{k['default_slot']} by default; fits {', '.join('S%d' % n for n in slots)} "
                      f"({k['size']}, needs {k['needs'] or 'nothing special'})")

    # needs implied by the declared roles (SPEC §4.2, §4.4: TIM8 on S4 G0-G3, TIM1 on S5 G0-G5, BKIN on S5 IRQ_N)
    implied = set()
    for i, g in enumerate(D.GLINES):
        x = k["glines"][g]
        fl = set(x.get("flags", []))
        if "pwm" in fl or x["role"] in ("pwm_high", "pwm_low"):
            implied.add("pwm_g0_g3" if i < 4 else "tim1")
            if x["role"] == "pwm_low" or i >= 4:
                implied.add("tim1")
        if "fast" in fl and i >= 4:
            implied.add("fast_g4_g5")
    if any(dv["irq"] == "bkin" for dv in k["devices"]):
        implied.add("bkin_on_irq")
    if k["rails"]["+5V"]["max_ma"] > RAIL_RULE_MA["+5V"][1]:
        implied.add("high_current_5v")
    for ln in ("AN1", "AN2", "AN3"):               # S5's AN1-AN3 are on the 12-bit ADC4 (SPEC §4.4)
        x = k["lanes"][ln]
        if x["kind"] != "unused" and "adc4_ok" not in x["flags"] and 5 in slots:
            implied.add("lanes_14bit")
    if any(g["role"] == "load" and "exceeds_rule" in g.get("flags", []) for g in k["glines"].values()):
        implied.add("exercises_current_limit")
    missing = sorted(implied - set(k["needs"]))
    extra = sorted(set(k["needs"]) - implied - {"lanes_14bit", "exercises_current_limit"})
    if missing:
        r.fail("needs", f"the declared roles need {missing}, which `needs` does not list (the slot check would "
                        "let it into a slot without them)")
    elif extra:
        r.warn("needs", f"`needs` lists {extra}, which no declared role uses (it narrows the slots for nothing)")
    else:
        r.ok("needs", ", ".join(k["needs"]) or "none")

    # current budgets against the coupon rules and the switches' trip points (SPEC §3.1, §4.9; nets.SWITCH_TRIP)
    for rail in D.RAILS:
        x = k["rails"][rail]
        used = rail in k["uses"]
        rule = f"budget.{rail}"
        if not used and rail == "+3V3":
            r.fail(rule, "+3V3 is not in `uses`: every coupon's descriptor EEPROM runs from it (SPEC §4.6)")
            continue
        if not used:
            if x["max_ma"] or x["typ_ma"]:
                r.fail(rule, f"{rail} is not in `uses` but declares {x['max_ma']} mA")
            else:
                r.ok(rule, f"{rail} not used")
            continue
        if x["max_ma"] == 0:
            r.fail(rule, f"{rail} is used but declares 0 mA: the firmware budgets with max_ma (SPEC §3.2, §4.9)")
            continue
        probs = []
        if x["typ_ma"] > x["max_ma"]:
            probs.append(f"typ {x['typ_ma']} mA > max {x['max_ma']} mA")
        for n in slots:
            lim = RAIL_RULE_MA[rail][n]
            trip = nets.SWITCH_TRIP[f"{rail}_S{n}"]
            if x["max_ma"] > lim:
                probs.append(f"S{n}: {x['max_ma']} mA > the {lim} mA rule")
            elif x["max_ma"] >= trip[0] * 1000:
                probs.append(f"S{n}: {x['max_ma']} mA reaches the switch's minimum trip {trip[0] * 1000:g} mA")
        if probs:
            r.fail(rule, "; ".join(probs))
        else:
            lim = min(RAIL_RULE_MA[rail][n] for n in slots)
            trip = min(nets.SWITCH_TRIP[f"{rail}_S{n}"][0] for n in slots) * 1000
            r.ok(rule, f"max {x['max_ma']} mA (typ {x['typ_ma']}) within the {lim} mA rule and below the "
                       f"{trip:g} mA minimum trip in every allowed slot")
    i3, i5 = k["rails"]["+3V3"]["max_ma"], k["rails"]["+5V"]["max_ma"]
    r.info("budget.vsys", f"this coupon alone reserves {i3 + i5} mA of VSYS ({i3} + {i5}); a Default USB-C source "
                          f"leaves about {DEFAULT_SOURCE_MA - BASE_LOAD_MA} mA after the base load (SPEC §3.2, "
                          f"estimate), and the slot LDO {SLOT_LDO_MA} mA for every slot's +3V3 together")
    fits = [name for name, ma in SOURCE_BUDGETS_MA if i3 + i5 <= ma - BASE_LOAD_MA]
    if not fits:
        r.fail("budget.source", f"{i3 + i5} mA exceeds even a 3.0 A source's {SOURCE_BUDGETS_MA[-1][1]} mA VSYS "
                                "ceiling less the base load (SPEC §3.2)")
    elif fits[0] != "Default":
        r.warn("budget.source", f"{i3 + i5} mA needs a source that advertises {fits[0]} or more: on a weaker one "
                                "the firmware refuses the coupon's rails (SPEC §3.2, §3.6)")

    # bulk capacitance against SPEC §4.9 (declared; the netlist's own sum is compared in check_declared)
    for rail in D.RAILS:
        bulk = k["rails"][rail]["bulk_uf"]
        lim = min(BULK_RULE_UF[rail][n] for n in slots) if slots else 0
        if bulk > lim:
            r.fail(f"bulk.{rail}.declared", f"declares {bulk:g} uF on {rail}, above the {lim} uF rule of "
                                            f"its slots (SPEC §4.9)")

    # I2C devices on the coupon's own channel (SPEC §4.5, §4.6)
    addrs = {}
    for i, dv in enumerate(k["devices"]):
        if dv["bus"] != "i2c":
            continue
        a = int(dv["addr"], 16)
        if a == I2C_MUX_ADDR:
            r.fail("i2c.addresses", f"devices[{i}] {dv['part']} at 0x70: the mux answers there on every channel")
        if a == D.I2C_ADDR:
            r.fail("i2c.addresses", f"devices[{i}] {dv['part']} at 0x50, the descriptor EEPROM's address")
        if a in addrs:
            r.fail("i2c.addresses", f"0x{a:02X} used by devices[{addrs[a]}] and devices[{i}]")
        addrs[a] = i
    if r.result("i2c.addresses") is None:
        r.ok("i2c.addresses", "descriptor at 0x50" + "".join(f", {k['devices'][i]['part']} 0x{a:02X}"
                                                             for a, i in sorted(addrs.items())) + "; none at 0x70")
    sel = [i for i, dv in enumerate(k["devices"]) if "addr_selected" in dv["flags"]]
    addr_lines = [g for g in D.GLINES if k["glines"][g]["role"] == "addr"]
    if len(sel) > 1:
        r.fail("i2c.addr_select", f"devices {sel} are all address-selected: format 1 allows one such entry")
    elif sel:
        n = k["devices"][sel[0]]["count"]
        if len(addr_lines) != n:
            r.fail("i2c.addr_select", f"{n} address-selected devices but {len(addr_lines)} G-lines with role addr")
    elif addr_lines:
        r.fail("i2c.addr_select", f"{addr_lines} have role addr but no device is address-selected")

    # SPI: devices, selects and the clock (SPEC §4.8, §4.9)
    spi_devs = [i for i, dv in enumerate(k["devices"]) if dv["bus"] == "spi"]
    uses_spi = {"SCK", "MISO", "MOSI"} & set(k["uses"])
    probs = []
    if spi_devs and not {"SCK", "MISO"} <= set(k["uses"]):
        probs.append("SPI devices declared but SCK/MISO not in `uses`")
    if uses_spi and not spi_devs:
        probs.append(f"uses {sorted(uses_spi)} but declares no SPI device")
    if spi_devs and k["spi"]["max_khz"] == 0:
        probs.append("SPI devices declared with spi.max_khz 0")
    for i in spi_devs:
        line = k["devices"][i]["addr"]
        if line not in k["uses"]:
            probs.append(f"devices[{i}] is selected by {line}, which is not in `uses`")
        if line in D.CSES and k["cs"][line]["role"] != "spi_cs":
            probs.append(f"devices[{i}] is selected by {line}, whose role is {k['cs'][line]['role']}")
        if line in D.GLINES and not (k["glines"][line]["role"] == "cs" and k["glines"][line].get("arg") == i):
            probs.append(f"devices[{i}] is selected by {line}, whose role is not cs with arg {i}")
    for cs in D.CSES:
        x = k["cs"][cs]
        if x["role"] != "unused" and cs not in k["uses"]:
            probs.append(f"{cs} has role {x['role']} but is not in `uses`")
        if x["role"] == "unused" and cs in k["uses"]:
            probs.append(f"{cs} is in `uses` with no role")
        if x["role"] in ("spi_cs", "strobe") and x.get("device") is None:
            probs.append(f"{cs} ({x['role']}) names no device")
    if probs:
        r.fail("spi", "; ".join(probs))
    elif spi_devs:
        r.ok("spi", f"{len(spi_devs)} device(s), up to {k['spi']['max_khz']} kHz, modes "
                    f"{sorted({k['devices'][i]['spi_mode'] for i in spi_devs})}; MISO must go high-impedance "
                    "while the coupon's selects are high (SPEC §4.9: not checkable here)")
    for g in D.GLINES:
        x = k["glines"][g]
        if x["role"] != "unused" and g not in k["uses"]:
            r.fail("glines", f"{g} has role {x['role']} but is not in `uses`")
        elif x["role"] == "unused" and g in k["uses"]:
            r.fail("glines", f"{g} is in `uses` with no role")
    if r.result("glines") is None and any(k["glines"][g]["role"] != "unused" for g in D.GLINES):
        r.ok("glines", ", ".join(f"{g} {k['glines'][g]['role']}" for g in D.GLINES
                                 if k["glines"][g]["role"] != "unused"))

    # lanes: what each declares (SPEC §4.9)
    for ln in D.LANES:
        x = k["lanes"][ln]
        rule = f"lanes.{ln}"
        if x["kind"] == "unused":
            if ln in k["uses"]:
                r.fail(rule, f"{ln} is in `uses` but its lane kind is unused")
            continue
        if ln not in k["uses"]:
            r.fail(rule, f"lane {ln} is declared ({x['kind']}) but not in `uses`")
            continue
        rs = x["r_src_ohm"]
        if rs is None:
            (r.warn if ph else r.fail)(rule, f"{ln}: R_src not declared (SPEC §4.9: declared in the descriptor)")
            continue
        tau = (rs + LANE_R_OHM) * LANE_C_PF * 1e-12
        step = tau * math.log(2 ** SETTLE_BITS)
        txt = (f"{ln} {x['kind']}: R_src {rs} ohm, settles to 15 bits in {step * 1e6:.2f} us per step "
               f"((R_src + {LANE_R_OHM}) x {LANE_C_PF} pF x ln 2^15, SPEC §4.9; arithmetic)")
        if rs > ADC_R_MAX_OHM:
            r.warn(rule, txt + f"; above DS13543 Table 97's {ADC_R_MAX_OHM} ohm: a slow lane, sampled with a "
                               "long sampling time (SPEC §6.3)")
        else:
            r.ok(rule, txt)
        if c.net is None and x["cload_max_pf"] and x["cload_max_pf"] <= LANE_C_PF:
            # descriptor only; with a netlist, check_declared adds the coupon's own lane capacitors to the 1 nF
            r.warn(f"{rule}.cload", f"{ln}: its sources are rated for {x['cload_max_pf']} pF and the "
                                    f"motherboard's lane capacitor alone is {LANE_C_PF} pF (SPEC §4.3, §11 #21: "
                                    "whether capacitance behind the 47 ohm counts is not stated)")


# ---- the netlist -----------------------------------------------------------------------------------------------
def check_netlist(c, r):
    n = c.net
    c.header_ref = c.header_in_net()
    if c.header_ref is None:
        r.fail("pins.net", "no 2 x 20 slot header (39 or 40 pins) in the netlist")
        return
    h = c.header_ref
    # every header pin against nets.SLOT_PINS (SPEC §4.2), coupon-side names (sheets/coupon_common.py)
    probs = []
    for pin, (sig, kind) in sorted(PIN_KIND.items()):
        got = n.net_of(h, pin)
        gb = M.net_base(got) if got else None
        if kind == "gnd" or kind == "present":
            continue                                   # own rules below
        if kind == "nc":
            continue
        want = coupon_net(sig)
        if got is None:
            continue                                   # an unused signal or rail: compared with `uses` later
        if gb != want:
            probs.append(f"pin {pin} ({sig}) is on {got}, expected {want} or not connected")
    if probs:
        r.fail("pins.net", "; ".join(probs))
    else:
        r.ok("pins.net", f"{h}: every signal and rail pin carries its own slot net or none (nets.SLOT_PINS)")
    bad = [p for p in GND_PINS if n.net_of(h, p) != "GND"]
    if bad:
        r.fail("gnd_pins", f"GND pins {bad} are on {[n.net_of(h, p) for p in bad]}: all 13 carry GND "
                           "(SPEC §4.2: a ground opposite every lane, the motor return on 4-6)")
    else:
        r.ok("gnd_pins", f"all {len(GND_PINS)} GND pins on GND")
    p32 = n.net_of(h, 32)
    if p32 != "GND":
        r.fail("present_n", f"pin 32 (PRESENT_N) is on {p32 or 'nothing'}: tie it to GND with a strap "
                            "(SPEC §4.6, §4.9), or the firmware never sees the coupon")
    else:
        others = [m for m in n.members("GND") if m[0] != h]
        r.ok("present_n", f"pin 32 strapped to GND ({len(others)} other GND connections)")
    _check_key(c, r)
    for rail, pins in RAIL_PINS.items():
        got = {n.net_of(h, p) for p in pins}
        if len(got) > 1:
            r.fail(f"rails.{rail}", f"pins {pins} are on {sorted(map(str, got))}: all or none")
    # shorts between slot pins: two signals on one net, or a signal on GND or a rail
    by_net = {}
    for pin, (sig, kind) in PIN_KIND.items():
        got = n.net_of(h, pin)
        if got is not None and kind in ("signal", "rail"):
            by_net.setdefault(got, set()).add(sig)
    probs = [f"{sorted(sigs)} share {net}" for net, sigs in by_net.items() if len(sigs) > 1]
    for pin, (sig, kind) in PIN_KIND.items():
        got = n.net_of(h, pin)
        if kind == "signal" and got is not None and (got == "GND" or got in c.rails() or M.net_base(got) == "+3V3"):
            probs.append(f"{sig} (pin {pin}) is tied to {got}")
    if probs:
        r.fail("shorts", "; ".join(probs))
    else:
        r.ok("shorts", "no two slot signals share a net, and none is tied to GND or a rail")
    _check_reversal(c, r)
    _check_slot_lines(c, r)
    stubs = [sig for sig, pin in SIGNAL_PINS.items()
             if sig != "PRESENT_N" and n.net_of(h, pin) and c.is_stub(n.net_of(h, pin))]
    if stubs:
        r.warn("stubs", f"{stubs} reach nothing on the coupon: leave unused pins unconnected (a no-connect flag)")

    # the descriptor EEPROM (SPEC §4.6, §4.9; ST DocID024020 Rev 2)
    ee = [x for x in n.comps.values() if EEPROM_RE.search(x.part or "") or EEPROM_RE.search(x.value or "")]
    if not ee:
        r.fail("eeprom.present", "no 2 kbit descriptor EEPROM (M24C02 class) in the netlist (SPEC §4.6)")
    elif len(ee) > 1:
        r.fail("eeprom.present", f"{len(ee)} EEPROMs ({', '.join(x.ref for x in ee)}): one descriptor per coupon")
    elif ee[0].dnp:
        r.fail("eeprom.present", f"{ee[0].ref} {ee[0].value} is marked DNP: the assembled coupon has no descriptor "
                                 "(SPEC §4.6)")
    if len(ee) == 1:
        e = c.eeprom = ee[0]
        if not e.dnp:
            r.ok("eeprom.present", f"{e.ref} {e.value}")
        pn = {nm: e.pin_by_name(*al) for nm, al in
              (("SDA", ("SDA",)), ("SCL", ("SCL",)), ("VCC", ("VCC", "VDD")), ("VSS", ("VSS", "GND")),
               ("WC", ("WC", "WP")), ("E0", ("E0", "A0")), ("E1", ("E1", "A1")), ("E2", ("E2", "A2")))}
        missing = [k for k, v in pn.items() if v is None]
        if missing:
            r.fail("eeprom.pins", f"{e.ref}: no pin named {missing} in its symbol")
        else:
            sda, scl = n.net_of(e.ref, pn["SDA"]), n.net_of(e.ref, pn["SCL"])
            hsda, hscl = c.hpin_net(SIGNAL_PINS["SDA"]), c.hpin_net(SIGNAL_PINS["SCL"])
            if sda is None or scl is None or sda != hsda or scl != hscl:
                r.fail("eeprom.bus", f"{e.ref} SDA/SCL on {sda}/{scl}, the header's pins 30/29 on {hsda}/{hscl}: "
                                     "the descriptor must sit on the slot's own I2C channel")
            else:
                r.ok("eeprom.bus", f"{e.ref} SDA/SCL on the slot's pins 30/29")
            bits, probs = 0, []
            for i, k in enumerate(("E0", "E1", "E2")):
                v = n.net_of(e.ref, pn[k])
                if v == "GND":
                    continue
                if v is not None and M.net_base(v) == "+3V3":
                    bits |= 1 << i
                else:
                    probs.append(f"{k} on {v or 'nothing'}")
            addr = 0x50 | bits
            if probs:
                r.fail("eeprom.address", f"{e.ref}: " + "; ".join(probs) + " (tie E2-E0 to GND, SPEC §4.9)")
            elif addr != D.I2C_ADDR:
                r.fail("eeprom.address", f"{e.ref} answers at 0x{addr:02X}: E2-E0 to GND puts it at 0x50 (SPEC §4.9)")
            else:
                r.ok("eeprom.address", f"{e.ref} E2-E0 on GND: 0x50")
            vcc, vss = n.net_of(e.ref, pn["VCC"]), n.net_of(e.ref, pn["VSS"])
            if vcc is None or M.net_base(vcc) != "+3V3" or vss != "GND":
                r.fail("eeprom.power", f"{e.ref} VCC on {vcc}, VSS on {vss}: power it from the slot's +3V3 (SPEC "
                                       "§4.6; at 5 V its VIH of 0.7 VCC would sit above the 3.3 V pull-ups)")
            else:
                caps = [x for x, ends in c.two_pin("C") if set(ends) == {vcc, "GND"}]
                r.ok("eeprom.power", f"{e.ref} on +3V3")
                if not caps:
                    r.warn("eeprom.decoupling", f"no capacitor between {vcc} and GND (DocID024020 §2.6.1: 10-100 nF "
                                                "close to VCC/VSS)")
            _check_wc(c, r, e, pn["WC"])
    # I2C pull-ups and the devices on the slot's channel
    hsda, hscl = c.hpin_net(SIGNAL_PINS["SDA"]), c.hpin_net(SIGNAL_PINS["SCL"])
    rails = c.rails()
    for sig, net in (("SDA", hsda), ("SCL", hscl)):
        if net is None:
            r.fail("i2c.bus", f"{sig} (pin {SIGNAL_PINS[sig]}) not connected: the descriptor needs the slot's I2C")
            continue
        for x, ends in c.two_pin("R", fitted=False):
            if net in ends:
                other = ends[1] if ends[0] == net else ends[0]
                if other in rails and x.dnp:
                    r.warn("i2c.pullups", f"{x.ref} (DNP) would pull {sig} up to {other} if fitted: a coupon pulls "
                                          "up to its own +3V3 only (SPEC §4.9)")
                elif x.dnp:
                    continue
                elif other in rails:
                    r.fail("i2c.pullups", f"{x.ref} pulls {sig} up to {other}: a coupon pulls up to its own +3V3 "
                                          "only (SPEC §4.9)")
                elif other and M.net_base(other) == "+3V3":
                    ohm = _parse_ohm(x.value)
                    par = f", {1 / (1 / ohm + 1 / SLOT_PULLUP_OHM):.0f} ohm with the slot's 4.7 k" if ohm else ""
                    r.warn("i2c.pullups", f"{x.ref} ({x.value}) pulls {sig} up on the coupon{par}: the slot "
                                          "already has 4.7 k to +3V3_Sn (SPEC §4.2)")
    if r.result("i2c.pullups") is None and hsda and hscl:
        r.ok("i2c.pullups", "no pull-ups on the coupon's SDA/SCL (the slot's 4.7 k serve)")
    # pull-ups from any slot signal to a rail other than +3V3 (SPEC §4.9)
    probs, dnp_probs = [], []
    for sig, pin in SIGNAL_PINS.items():
        net = c.hpin_net(pin)
        if net is None or sig in ("SDA", "SCL"):
            continue
        for x, ends in c.two_pin("R", fitted=False):
            if net in ends:
                other = ends[1] if ends[0] == net else ends[0]
                if other in rails:
                    (dnp_probs if x.dnp else probs).append(f"{x.ref} pulls {sig} to {other}")
    if probs:
        r.fail("pullups", "; ".join(probs) + " (SPEC §4.9: no pull-up to anything but the coupon's own +3V3)")
    elif dnp_probs:
        r.warn("pullups", "not fitted (DNP), but fitting it breaks SPEC §4.9: " + "; ".join(dnp_probs))
    else:
        r.ok("pullups", "no slot signal is pulled to a rail other than +3V3")
    irq = c.hpin_net(SIGNAL_PINS["IRQ_N"])
    if irq is not None:
        pu = [x.ref for x, ends in c.two_pin("R") if irq in ends and
              M.net_base(ends[1] if ends[0] == irq else ends[0]) == "+3V3"]
        if not pu:
            r.fail("irq_n", "IRQ_N is used but has no fitted pull-up to +3V3 on the coupon: the motherboard has "
                            "none (SPEC §3.5, §4.9: open drain, pull-up on the coupon)")
        else:
            r.ok("irq_n", f"IRQ_N pulled up on the coupon by {', '.join(pu)}")
    # SPEC §4.9: IRQ_N open drain; MISO high-impedance while the coupon's selects are high (SPI2 is shared). The
    # netlist knows only each pin's electrical type in its symbol, so a push-pull type is a WARN to look at.
    for sig, ok_types, why in (("IRQ_N", {"open_collector", "open_emitter", "passive"}, "open drain"),
                               ("MISO", {"tri_state", "passive"}, "high-impedance while deselected")):
        net = c.hpin_net(SIGNAL_PINS[sig])
        if net is None:
            continue
        drv = [(ref, p, n.pin_type.get((ref, p), "")) for ref, p in c.fitted_members(net)
               if c.kind_of(ref) not in PASSIVE_PREFIXES | {"Q", "D"}]
        bad = [f"{ref}.{p} ({t})" for ref, p, t in drv if t not in ok_types]
        rule = f"{sig.lower()}.drive"
        if bad:
            r.warn(rule, f"{sig} is driven by {', '.join(bad)}: SPEC §4.9 wants {why}; check the part (a symbol's pin "
                         "type can be wrong either way)")
        elif drv:
            r.ok(rule, f"{sig} drivers {', '.join(f'{ref}.{p} ({t})' for ref, p, t in drv)}: {why} by their "
                       "symbols' pin types")

    # lanes: a source on the coupon (from the netlist), counting only fitted parts
    for ln in D.LANES:
        net = c.hpin_net(SIGNAL_PINS[ln])
        if net is None:
            continue
        mem = c.fitted_members(net)
        srcs = sorted({ref for ref, p in mem if c.kind_of(ref) not in ("C", "TP", "FID", "H", "#FLG", "#PWR")})
        caps = sorted({ref for ref, p in mem if c.kind_of(ref) == "C"})
        dnp = c.dnp_members(net)
        if not mem and dnp:
            r.info(f"lanes.{ln}.source", f"{ln} reaches only {', '.join(dnp)}, not fitted (DNP): the lane is open "
                                         "as assembled, an option; it counts as not used")
        elif not srcs:
            r.fail(f"lanes.{ln}.source", f"{ln} reaches only {sorted({x for x, _ in mem}) or 'the header'}: no "
                                         "source drives the lane")
        else:
            r.ok(f"lanes.{ln}.source", f"{ln} driven by {', '.join(srcs)}" +
                 (f"; capacitors on the lane: {', '.join(caps)}" if caps else "") +
                 (f"; not fitted: {', '.join(dnp)}" if dnp else ""))


def _check_key(c, r):
    """The slot key (the owner's decision D2 of 2026-11-27; SPEC §4.2, §4.9): pin 39 absent from the coupon's header
    and unconnected, pin 2 present. The netlist shows the header's symbol; check_board() checks its footprint."""
    n, h = c.net, c.header_ref
    pins = c.header_pin_numbers()
    probs = []
    got = n.net_of(h, KEY_PIN)
    if got is not None:
        probs.append(f"pin {KEY_PIN} (KEY) is on {got}: the key pin carries no net")
    elif KEY_PIN in pins:
        probs.append(f"{h}'s symbol has a pin {KEY_PIN}: a coupon header with pin {KEY_PIN} hits the socket's plugged "
                     f"hole {KEY_PIN} and does not go in; draw it with sheets/coupon_common.py's keyed symbol (no pin "
                     f"{KEY_PIN}) and pull the header's pin {KEY_PIN}")
    if KEY_NEVER_WITH not in pins:
        probs.append(f"{h} has no pin {KEY_NEVER_WITH}: keyed at {KEY_NEVER_WITH} and {KEY_PIN} together, a coupon "
                     "fits either way round (they swap under a half turn, nets.SLOT_KEY_NEVER_WITH)")
    if probs:
        r.fail("key", "; ".join(probs) + " (SPEC §4.2, §4.9; D2 of 2026-11-27)")
    else:
        r.ok("key", f"pin {KEY_PIN} absent from {h} and unconnected (the key, D2 of 2026-11-27); pin {KEY_NEVER_WITH} "
                    f"present, so turned 180 degrees it meets the socket's plugged hole {KEY_PIN}")


def keyed_against(pins, f):
    """True when the socket's plugged hole 39 meets a pin the coupon has under the mapping f (slot pin -> coupon
    pin): the coupon cannot go in that way. `pins`: the coupon's header pin numbers."""
    cp = f(KEY_PIN)
    return cp is not None and cp in pins


def mirror_pin(n):
    """The coupon pin that motherboard pin n meets when the coupon is plugged in turned 180 degrees: a half turn about
    the header's centre maps column k to 19 - k and swaps the rows (pin n <-> 41 - n). With the key (D2 of 2026-11-27)
    the turned coupon's pin 2 meets the socket's plugged hole 39, so it does not go in."""
    return 41 - n


def _col_shift(k):
    def f(n):
        m = n + 2 * k
        return m if 1 <= m <= 40 else None
    return f


# Other ways a 2 x 20 header can go into a 2 x 20 socket (slot pin n -> the coupon pin it meets, None: none). Odd pins
# are one row, even pins the other, pin 2k-1 and 2k in column k (SPEC §4.2). With the key, a way is blocked when the
# plugged hole 39 meets a pin the coupon has (keyed_against).
MISINSERTIONS = {
    "one column toward pin 1": _col_shift(+1),         # slot pin n meets coupon pin n + 2; coupon pins 1-2 hang out
    "one column toward pin 40": _col_shift(-1),
    "one row over, odd row in the even row": lambda n: n - 1 if n % 2 == 0 else None,
    "one row over, even row in the odd row": lambda n: n + 1 if n % 2 == 1 else None,
    "turned 180 degrees and one column off (a)": lambda n: _col_shift(+1)(mirror_pin(n)),
    "turned 180 degrees and one column off (b)": lambda n: _col_shift(-1)(mirror_pin(n)),
}


def _reads_present(c, f):
    """(present, what): does the slot's PRESENT_N (pin 32) meet a coupon pin on GND under the mapping f?"""
    n, h = c.net, c.header_ref
    cp = f(32)
    net = n.net_of(h, cp) if cp else None
    what = f"pin 32 meets {'its pin %d (%s, %s)' % (cp, PIN_KIND[cp][0], net or 'open') if cp else 'nothing'}"
    return net == "GND", what


def _check_reversal(c, r):
    """What a coupon plugged in wrongly does. The firmware powers +3V3_Sn only when PRESENT_N reads low, so a way in
    matters when the slot's pin 32 meets a coupon pin on GND. With the key (D2 of 2026-11-27: socket hole 39 plugged)
    a way in is blocked when the plug meets a pin the coupon has: the half turn (its pin 2) and three of the six
    offsets. The rest are checked for PRESENT_N; and the half turn is also analysed as if the plug were missing (a
    hand step at assembly, SPEC §4.2), which the firmware answers by reading the descriptor before it drives a line
    (risks.md EL-2)."""
    n, h = c.net, c.header_ref
    pins = c.header_pin_numbers()
    present, absent, blocked = [], [], []
    for name, f in MISINSERTIONS.items():
        if keyed_against(pins, f):
            blocked.append(f"{name} (its pin {f(KEY_PIN)} meets the plug)")
            continue
        yes, what = _reads_present(c, f)
        (present if yes else absent).append(f"{name}: {what}")
    tail = ("" if not blocked else "; blocked by the key's plug in hole 39: " + "; ".join(blocked))
    if present:
        r.warn("misinsertion", "reads as present (PRESENT_N on a coupon GND, so the firmware would power +3V3_Sn): "
                               + "; ".join(present) + tail)
    else:
        r.info("misinsertion", "reads absent in every other misinsertion the key does not block ("
                               + ("; ".join(absent) or "none") + ")" + tail + ": the firmware powers nothing. Only "
                               "electrical: whether the post or the socket body stops these insertions is not "
                               "checked")
    m = mirror_pin(32)
    got = n.net_of(h, m)
    meets = [f"pin {p} ({PIN_KIND[p][0]}) meets the coupon's pin {mirror_pin(p)} "
             f"({n.net_of(h, mirror_pin(p)) or 'open'})" for p in RAIL_PINS["+3V3"]]
    own = [f"its +3V3 (pin {p}) meets the slot's {PIN_KIND[mirror_pin(p)][0]}" for p in RAIL_PINS["+3V3"]]
    core = (f"the slot's PRESENT_N (pin 32) meets its pin {m}, on {got}, so it reads as present. Powering +3V3_Sn to "
            "read the descriptor, the slot's " + "; ".join(meets) + "; " + "; ".join(own) + ": MCU pins rated 20 mA "
            "(DS13543 Rev 2 Table 31) behind a switch that limits at 256-335 mA (SPEC §3.1), and the slot's 100 ohm "
            "(D3). The bring-up firmware reads the descriptor before it drives a slot line (risks.md EL-2)")
    if keyed_against(pins, mirror_pin):
        r.ok("reversal", f"turned 180 degrees the coupon cannot go in: its pin {mirror_pin(KEY_PIN)} meets the "
                         f"socket's plugged hole {KEY_PIN} (the key, D2 of 2026-11-27; SPEC §4.2)")
        if got is not None:
            r.info("reversal_if_unplugged", f"turned 180 degrees with the socket's hole {KEY_PIN} left unplugged (a hand "
                                         "step), " + core)
        return
    if got is None:
        r.ok("reversal", f"turned 180 degrees, the slot's PRESENT_N (pin 32) meets the coupon's open pin {m}: the "
                         "firmware sees no coupon and powers nothing")
        return
    r.warn("reversal", f"the key does not stop this coupon turned 180 degrees (it has no pin {KEY_NEVER_WITH}): "
                       + core)


def _fmt_ohm(v):
    return f"{v / 1e3:g} k" if v >= 1e3 else f"{v:g} ohm"


def line_load(c, net):
    """The DC load the coupon puts on a slot line: (R_th ohm, V_th V, why) of its fitted resistors seen from the
    line, with every other part's pin taken as high-impedance (logic inputs) and capacitors open. GND is 0 V, a
    '+3V3' net 3.3 V, a '+5V' net 5.0 V. (inf, None, why) when no resistor reaches a known potential; (None, None,
    why) when one reaches a rail of unknown potential."""
    n, h = c.net, c.header_ref
    pot = {}
    for x in n.nets:
        b = M.net_base(x)
        if x == "GND":
            pot[x] = 0.0
        elif b == "+3V3":
            pot[x] = MCU_VDD
        elif b == "+5V":
            pot[x] = 5.0
        elif x in c.rails():
            pot[x] = None
    nodes, frontier, res = {net}, [net], {}
    while frontier:
        x = frontier.pop()
        for ref, _pin in n.members(x):
            comp = n.comps.get(ref)
            if ref == h or ref in res or not n.fitted(ref) or c.kind_of(ref) != "R" or comp is None \
                    or len(comp.pins) != 2:
                continue
            ohm = _parse_ohm(comp.value)
            ends = [n.net_of(ref, p_) for p_ in comp.pins]
            if ohm is None or None in ends:
                return None, None, f"{ref} ({comp.value}) not read"
            res[ref] = (ends[0], ends[1], max(ohm, 1e-3))
            for e in ends:
                if e in pot:
                    if pot[e] is None:
                        return None, None, f"{ref} to {e}, a rail of unknown potential"
                elif e not in nodes:
                    nodes.add(e)
                    frontier.append(e)
    if not any(e in pot for a_, b_, _o in res.values() for e in (a_, b_)):
        return math.inf, None, "no resistor to a rail or GND" if not res else "resistors reach no rail or GND"
    idx = {x: i for i, x in enumerate(sorted(nodes))}
    k = len(idx)
    g = [[0.0] * (k + 2) for _ in range(k)]            # G | 1 A into the line | the fixed potentials' currents
    for a_, b_, ohm in res.values():
        for p_, q in ((a_, b_), (b_, a_)):
            if p_ in idx:
                g[idx[p_]][idx[p_]] += 1 / ohm
                if q in idx:
                    g[idx[p_]][idx[q]] -= 1 / ohm
                else:
                    g[idx[p_]][k + 1] += pot[q] / ohm
    g[idx[net]][k] = 1.0
    for col in range(k):
        piv = max(range(col, k), key=lambda i: abs(g[i][col]))
        if abs(g[piv][col]) < 1e-15:
            return math.inf, None, "resistors reach no rail or GND from the line"
        g[col], g[piv] = g[piv], g[col]
        for i in range(k):
            if i != col and g[i][col]:
                f = g[i][col] / g[col][col]
                g[i] = [x_ - f * y_ for x_, y_ in zip(g[i], g[col])]
    i = idx[net]
    return g[i][k] / g[i][i], g[i][k + 1] / g[i][i], f"{', '.join(sorted(res))}"


def _check_slot_lines(c, r):
    """The slot's direct lines through the motherboard's 100 ohm (D3 of 2026-11-27; SPEC §4.3; nets.SLOT_SERIES),
    against what the coupon puts on them. SPEC §4.3's timing check assumes about 40 pF and logic inputs behind the
    resistor; this checks the coupon's side of that: the DC load the MCU drives through the MCU's driver and the
    100 ohm (levels at the coupon, the pin current), capacitors added to the line (the edge they make), and a coupon
    output on a line the MCU drives (contention). Arithmetic with the nominal resistors; estimates."""
    n, k = c.net, c.canon
    slots = (k["slots"] or list(nets.SLOTS)) if k else list(nets.SLOTS)
    dc, edges, contention, notes = [], [], [], []
    held, floating = [], []
    for sig in SERIES_LINES:
        net = c.hpin_net(SIGNAL_PINS[sig])
        if net is None or not c.fitted_members(net):
            continue
        series = sorted({nets.SLOT_SERIES[s_][sig][1] for s_ in slots if sig in nets.SLOT_SERIES[s_]})
        where = [s_ for s_ in slots if sig in nets.SLOT_SERIES[s_]]
        if not series:
            continue                                   # S1-S4's G4/G5 come from U_EXP3, with no series resistor
        rs = series[-1]
        on = sig if set(where) == set(slots) else f"{sig} (in {', '.join('S%d' % s_ for s_ in where)})"
        role = None
        if k and sig in D.GLINES:
            role = k["glines"][sig]["role"]
        if sig == "IRQ_N" or role == "input":
            # driven by the coupon into an MCU input: its pull-up and driver sit on the coupon side of the 100 ohm,
            # which carries only the pin's leakage (DS13543 Table 87, under 1 uA: under 0.1 mV)
            notes.append(f"{sig}: driven by the coupon into the MCU through {rs:g} ohm; its pull-up current does not "
                         "flow through the resistor, so the MCU pin sees the coupon's own low level (plus under "
                         "0.1 mV); the falling edge into the motherboard's ~20 pF is about 2 ns (SPEC §4.3)")
            continue
        rth, vth, why = line_load(c, net)
        if rth is None:
            dc.append((None, f"{on}: DC load not computed ({why})"))
        elif math.isinf(rth):
            dc.append((0.0, f"{on}: no resistive load"))
            floating.append(on)
        else:
            held.append(f"{on} ({_fmt_ohm(rth)} to {vth:.1f} V)")
            i_hi = (MCU_VDD - vth) / (rth + rs + MCU_R_DRV)
            i_lo = (0.0 - vth) / (rth + rs + MCU_R_DRV)
            v_hi = MCU_VDD - i_hi * (rs + MCU_R_DRV)
            v_lo = -i_lo * (rs + MCU_R_DRV)
            i_max = max(abs(i_hi), abs(i_lo))
            dc.append((i_max, f"{on}: {why}, {_fmt_ohm(rth)} to {vth:.1f} V: {round(v_hi, 3) + 0.0:.3f} / "
                              f"{round(v_lo, 3) + 0.0:.3f} V at the coupon, {i_max * 1e3:.2f} mA "
                              f"({i_max * rs * 1e3:.1f} mV across the {rs:g} ohm)"))
        grounds = c.ac_grounds()
        caps = [(x_.ref, parse_cap(x_.value) or 0.0) for x_, ends in c.two_pin("C")
                if net in ends and (ends[1] if ends[0] == net else ends[0]) in grounds]
        if caps:
            cpf = sum(v for _r, v in caps) * 1e12
            tau = (rs + MCU_R_DRV) * (cpf + SLOT_LINE_C_PF) * 1e-12
            edges.append(f"{on}: {', '.join(a_ for a_, _v in caps)} add {cpf:.0f} pF to SPEC §4.3's {SLOT_LINE_C_PF} "
                         f"pF: tau = {tau * 1e9:.1f} ns through {rs:g} + {MCU_R_DRV:g} ohm, a 10-90 % edge of "
                         f"{2.2 * tau * 1e9:.0f} ns (SPEC §4.3 checked 9 ns)")
        drv = [f"{ref}.{p_} ({n.pin_type.get((ref, p_), '')})" for ref, p_ in c.fitted_members(net)
               if n.pin_type.get((ref, p_), "") in ("output", "power_out", "open_collector", "open_emitter",
                                                    "tri_state")]
        if drv:
            contention.append(f"{on}: {', '.join(drv)} by its symbol's pin type, on a line the MCU drives; a stiff "
                              f"coupon driver against the MCU through {rs:g} ohm draws up to "
                              f"{MCU_VDD / (rs + MCU_R_DRV) * 1e3:.0f} mA (DS13543 Table 31: 20 mA per pin)")
    head = (f"driven through the socket's {nets.SLOT_SERIES_OHMS:g} ohm (D3) and the MCU's driver, taken as "
            f"{MCU_R_DRV:g} ohm (DS13543 Table 88 at 8 mA), from 0 / {MCU_VDD:g} V, in slots "
            f"{', '.join('S%d' % s_ for s_ in slots)} (estimates; high / low level at the coupon): ")
    if dc:
        over = [t for i_, t in dc if i_ is not None and i_ > MCU_I_SPEC_MA * 1e-3]
        unknown = [t for i_, t in dc if i_ is None]
        if over:
            r.fail("slotlines.dc", head + "; ".join(over) + f": above the {MCU_I_SPEC_MA:g} mA at which DS13543 "
                                                            "Table 88 specifies the MCU's output levels")
        elif unknown:
            r.warn("slotlines.dc", head + "; ".join(t for _i, t in dc))
        else:
            r.ok("slotlines.dc", head + "; ".join(t for _i, t in dc))
    if edges:
        r.warn("slotlines.edges", "; ".join(edges) + ": SPEC §4.3's '100 ohm limits no slot function' assumes no "
                                                     "capacitor on these lines; check the edge against the line's use")
    elif dc:
        r.ok("slotlines.edges", f"no capacitor on the MCU-driven slot lines: SPEC §4.3's {SLOT_LINE_C_PF} pF behind "
                                f"100 ohm (tau 4 ns, a 9 ns edge) holds as far as the netlist shows")
    if contention:
        r.warn("slotlines.contention", "; ".join(contention) + " (a symbol's pin type can be wrong either way)")
    # The bring-up firmware leaves these lines high-impedance from +3V3_Sn on until it has read and checked the
    # descriptor (bringup/src/slot.c, risks.md EL-2), so only the coupon holds them then. SPEC §4.9 has no rule for
    # it: reported, not failed.
    idle = ("the bring-up firmware leaves the slot's MCU-driven lines high-impedance from +3V3_Sn on until it has "
            "read and checked the descriptor (the settling time plus the read; bringup/src/slot.c, risks.md EL-2)")
    if floating:
        r.warn("slotlines.idle", f"{', '.join(floating)}: no resistor to a rail or GND on the coupon, so these inputs "
                                 f"float while {idle}; a pull (as the A1 coupons' 100 k) holds them, unless the part "
                                 "has its own (not in the netlist)")
    elif held:
        r.ok("slotlines.idle", f"every MCU-driven slot line the coupon uses has a pull on the coupon, which holds it "
                               f"while {idle}: {'; '.join(held)}")
    if notes:
        r.info("slotlines.irq_n", "; ".join(notes))


def lane_network(c, net, active_as_ground=False):
    """The lane's resistor network seen from the slot pin, as (R_th ohm, ratio, why).

    Every fitted resistor counts; capacitors, test points and DNP parts do not. GND and every rail are AC ground.
    R_th is the Thevenin resistance into the lane; ratio is its open-circuit voltage as a fraction of +3V3 (GND = 0,
    +3V3 = 1; None when another rail feeds it). When a fitted part other than a resistor drives the network (an active
    source: a sensor, a buffer, a mux), the netlist cannot give its output impedance: then R_th is None, unless
    active_as_ground, which treats every net such a part touches as AC ground. That makes R_th a LOWER BOUND of the
    real source impedance (grounding a node can only lower a resistive network's resistance, and any output
    impedance in the source only adds to it), and ratio None.

    A two-pin diode with one end on a slot input that idles low or open (IDLE_LOW_INPUTS: INJ, the latency rig's
    stimulus, open by default at JP_INJn, SPEC §4.7) does not conduct while the lane idles, so it counts as open:
    the test coupon's D11 from INJ into the AN0 tap (D7 of 2026-11-27). R_th and ratio are then the idle lane's;
    with INJ driven high the diode conducts and both move (the descriptor declares the idle values)."""
    n, h = c.net, c.header_ref
    rails = c.ac_grounds()
    fixed = {x: (0.0 if x == "GND" else 1.0 if M.net_base(x) == "+3V3" else None) for x in rails}
    nodes, frontier, res = {net}, [net], {}
    active, idle_open = [], set()
    idle_nets = {c.hpin_net(SIGNAL_PINS[s]) for s in IDLE_LOW_INPUTS} - {None}
    while frontier:
        x = frontier.pop()
        for ref, _pin in n.members(x):
            if ref == h or ref in res or ref in idle_open or not n.fitted(ref):
                continue
            kind = c.kind_of(ref)
            if kind in ("C", "TP", "FID", "H", "#FLG", "#PWR"):
                continue
            comp = n.comps.get(ref)
            if (kind == "D" and comp is not None and len(comp.pins) == 2
                    and {n.net_of(ref, p_) for p_ in comp.pins} & idle_nets):
                idle_open.add(ref)                     # a diode from INJ: reverse-biased or open while INJ idles
                continue
            if kind != "R" or comp is None or len(comp.pins) != 2:
                if not active_as_ground:
                    return None, None, f"{ref} drives it"
                active.append(ref)
                fixed.setdefault(x, None)              # an active pin's net: AC ground, potential unknown
                nodes.discard(x)
                continue
            ohm = _parse_ohm(comp.value)
            ends = [n.net_of(ref, p) for p in comp.pins]
            if ohm is None or None in ends:
                return None, None, f"{ref} ({comp.value}) not read"
            res[ref] = (ends[0], ends[1], max(ohm, 1e-3))  # a 0 ohm link: 1 mohm, so the network stays solvable
            for e in ends:
                if e not in fixed and e not in nodes:
                    nodes.add(e)
                    frontier.append(e)
    if net in fixed:                                    # an active pin sits on the lane itself: no bound
        return 0.0, None, f"{', '.join(sorted(set(active)))} on the lane itself"
    if not res:
        return None, None, "no resistor on the lane"
    idx = {x: i for i, x in enumerate(sorted(nodes))}
    k = len(idx)
    g = [[0.0] * (k + 2) for _ in range(k)]            # G | 1 A into the lane | the fixed potentials' currents
    unknown_rail = False
    for a, b, ohm in res.values():
        for p_, q in ((a, b), (b, a)):
            if p_ in idx:
                g[idx[p_]][idx[p_]] += 1 / ohm
                if q in idx:
                    g[idx[p_]][idx[q]] -= 1 / ohm
                elif fixed.get(q) is None:
                    unknown_rail = True
                else:
                    g[idx[p_]][k + 1] += fixed[q] / ohm
    g[idx[net]][k] = 1.0
    for col in range(k):                               # Gaussian elimination with partial pivoting
        piv = max(range(col, k), key=lambda i: abs(g[i][col]))
        if abs(g[piv][col]) < 1e-15:
            return None, None, "no resistive path to ground"
        g[col], g[piv] = g[piv], g[col]
        for i in range(k):
            if i != col and g[i][col]:
                f = g[i][col] / g[col][col]
                g[i] = [a - f * b for a, b in zip(g[i], g[col])]
    i = idx[net]
    rth = g[i][k] / g[i][i]
    ratio = None if (unknown_rail or active) else g[i][k + 1] / g[i][i]
    why = f"{len(res)} resistor{'s' if len(res) != 1 else ''}"
    if active:
        why += f", {', '.join(sorted(set(active)))} taken as 0 ohm"
    if idle_open:
        why += (f"; {', '.join(sorted(idle_open))} from {'/'.join(IDLE_LOW_INPUTS)} taken as open (the idle lane: "
                "the rig's stimulus low or its jumper open)")
    return rth, ratio, why


def lane_thevenin(c, net):
    """(R_th, why) of a lane only resistors drive; (None, why) when anything else drives it (lane_network)."""
    rth, _ratio, why = lane_network(c, net)
    return rth, why


def _parse_ohm(v):
    m = re.match(r"^(\d+(?:\.\d+)?)\s*([kKmMR]?)(\d*)", (v or "").strip())
    if not m:
        return None
    mult = {"k": 1e3, "K": 1e3, "M": 1e6, "m": 1e-3, "R": 1.0, "": 1.0}[m.group(2)]
    base = float(m.group(1) + ("." + m.group(3) if m.group(3) else ""))
    return base * mult


def _check_wc(c, r, e, wc_pin):
    n = c.net
    wc = n.net_of(e.ref, wc_pin)
    if wc is None:
        r.fail("eeprom.wc", f"{e.ref} WC is not connected: it floats (writable per DocID024020 §2.4, but held by "
                            "nothing); hold it low with a resistor and give it a jumper to +3V3, as "
                            "sheets/coupon_common.py does")
        return
    if wc == "GND":
        r.ok("eeprom.wc", f"{e.ref} WC on GND: always writable (it cannot be write-protected)")
        return
    if M.net_base(wc) == "+3V3":
        r.fail("eeprom.wc", f"{e.ref} WC tied to +3V3: always write-protected, so the descriptor can never be "
                            "written in place")
        return
    hdr = {M.net_base(c.hpin_net(p)) for p in SIGNAL_PINS.values() if c.hpin_net(p)}
    if M.net_base(wc) in hdr:
        r.ok("eeprom.wc", f"{e.ref} WC driven by the slot's {M.net_base(wc)}: the firmware sets write protection")
        return
    down = up = jump = None
    for x in n.comps.values():
        if x.dnp:                                      # a DNP resistor holds nothing
            continue
        ends = [n.net_of(x.ref, p) for p in x.pins]
        if wc not in ends or len(ends) != 2:
            continue
        other = ends[1] if ends[0] == wc else ends[0]
        ob = M.net_base(other) if other else None
        if x.prefix == "R" and other == "GND":
            down = x.ref
        elif x.prefix == "R" and ob == "+3V3":
            up = x.ref
        elif x.prefix in ("JP", "SJ", "J") and ob in ("+3V3", "GND"):
            jump = (x.ref, ob)
    if down and jump and jump[1] == "+3V3":
        r.ok("eeprom.wc", f"{e.ref} WC: {down} to GND (writable), bridge {jump[0]} to +3V3 to write-protect")
    elif up and jump and jump[1] == "GND":
        r.ok("eeprom.wc", f"{e.ref} WC: {up} to +3V3 (protected), bridge {jump[0]} to GND to write")
    elif down:
        r.ok("eeprom.wc", f"{e.ref} WC held low by {down}: writable, no write protection fitted")
    elif up:
        r.warn("eeprom.wc", f"{e.ref} WC held high by {up} with no jumper: write-protected, so the descriptor is "
                            "written only by overriding WC on the bench")
    else:
        r.fail("eeprom.wc", f"{e.ref} WC on {wc}, which nothing holds at a level (no resistor to GND or +3V3)")


# ---- the board ---------------------------------------------------------------------------------------------------
def check_board(c, r):
    b, g = c.board, c.geometry
    if g is None:
        r.skip("pcb", "no slot geometry (boards/coupon_common.py could not be imported)")
        return
    # outline (SPEC §2; boards/coupon_common.py STANDARD / WIDE)
    size = None
    if not b.outline_ok:
        r.fail("outline", "Edge.Cuts is not one closed outline")
    else:
        for name, (w, h) in g.sizes.items():
            if abs(b.width - w) <= SIZE_TOL and abs(b.height - h) <= SIZE_TOL:
                size = name
        want = c.canon["size"] if c.canon else None
        if size is None:
            r.fail("outline", f"{b.width:g} x {b.height:g} mm matches no coupon size "
                              + ", ".join(f"{k} {w:g} x {h:g}" for k, (w, h) in g.sizes.items())
                              + f" (+-{SIZE_TOL} mm; {g.source})")
        elif want and size != want:
            r.fail("outline", f"{b.width:g} x {b.height:g} mm is the {size} size; the descriptor says {want}")
        else:
            r.ok("outline", f"{b.width:g} x {b.height:g} mm: the {size} coupon")
        if abs(b.aux_origin[0]) > 0.01 or abs(b.aux_origin[1]) > 0.01:
            r.warn("outline.origin", f"the drill/place origin is at {b.aux_origin} from the outline's lower-left "
                                     "corner (boards/geom.py puts it there: the CPL and Gerbers use board mm)")
    if b.copper_layers != COPPER_LAYERS:
        r.warn("layers", f"{b.copper_layers} copper layers; SPEC §2 proposes 4 (a solid ground layer)")
    elif abs(b.thickness - THICKNESS[0]) > THICKNESS[1]:
        r.warn("layers", f"{b.thickness:g} mm thick; SPEC §2 proposes 1.6 mm")
    else:
        r.ok("layers", f"{b.copper_layers} layers, {b.thickness:g} mm")
    gnd = b.gnd_plane.get("In1.Cu", 0.0)
    if gnd < GND_PLANE_MIN:
        r.warn("ground_plane", f"GND fills {gnd:.0%} of In1.Cu (heuristic: at least {GND_PLANE_MIN:.0%}): route "
                               "the lanes over a solid ground (SPEC §4.9)")
    else:
        r.ok("ground_plane", f"GND fills {gnd:.0%} of In1.Cu")

    # the header (SPEC §4.1, boards/coupon_common.py: on the bottom, every pad on its slot position)
    hdrs = [f for f in b.footprints.values() if f.fpid == g.header_fpid]
    if not hdrs:                                       # the same footprint under another library nickname
        name = g.header_fpid.split(":", 1)[-1]
        hdrs = [f for f in b.footprints.values() if f.fpid.split(":", 1)[-1] == name]
        if hdrs:
            r.warn("header.library", f"{hdrs[0].ref} is {hdrs[0].fpid!r}, not {g.header_fpid!r}")
    if not hdrs:
        others = [f"{f.ref} {f.fpid}" for f in b.footprints.values() if len(f.pads) in (39, 40)]
        r.fail("header.footprint", f"no {g.header_fpid}" + (f" (39- or 40-pad footprints: {others})" if others else ""))
        return
    if len(hdrs) > 1:
        r.fail("header.footprint", f"{len(hdrs)} slot headers: {[f.ref for f in hdrs]}")
    hf = hdrs[0]
    r.ok("header.footprint", f"{hf.ref} {g.header_fpid}")
    if hf.side != g.header_side:
        r.fail("header.side", f"{hf.ref} is on the {'top' if hf.side == 'F' else 'bottom'}: the coupon's header "
                              "sits on the bottom, pins down into the motherboard socket (SPEC §9)")
    else:
        r.ok("header.side", f"{hf.ref} on the bottom")
    _check_key_pcb(r, hf, g)
    errs = []
    for p in hf.pads:
        try:
            ex, ey = g.pin_xy(int(p.number))
        except ValueError:
            continue
        errs.append((math.hypot(p.x - ex, p.y - ey), p.number, (p.x, p.y), (ex, ey)))
    worst = max(errs) if errs else (0, "", (0, 0), (0, 0))
    if worst[0] > PIN_TOL:
        d1 = [(p.x - g.pin_xy(int(p.number))[0], p.y - g.pin_xy(int(p.number))[1]) for p in hf.pads]
        uniform = max(abs(a - d1[0][0]) + abs(b_ - d1[0][1]) for a, b_ in d1) < PIN_TOL
        why = (f"every pad shifted by ({d1[0][0]:+.3f}, {d1[0][1]:+.3f}) mm" if uniform
               else "the pads are rotated or mirrored against the slot (orientation)")
        r.fail("header.position", f"pad {worst[1]} at {worst[2]}, slot position {worst[3]}: {why} "
                                  f"(+-{PIN_TOL} mm; pin_xy() of {g.source})")
    else:
        r.ok("header.position", f"all {len(errs)} pads on their slot positions (worst {worst[0] * 1000:.1f} um), "
                                f"so the coupon mates with the socket placed by {g.source}")
    # pad nets: against SLOT_PINS and against the netlist (parity)
    pnets = {p.number: (None if M.is_unconnected_name(p.net) else p.net) for p in hf.pads}
    probs = []
    for pin, (sig, kind) in PIN_KIND.items():
        got = pnets.get(str(pin))
        want = "GND" if kind in ("gnd", "present") else (None if kind == "nc" else coupon_net(sig))
        if kind in ("gnd", "present", "nc"):
            if got != want:
                probs.append(f"pad {pin} ({sig}) on {got}, expected {want}")
        elif got is not None and M.net_base(got) != want:
            probs.append(f"pad {pin} ({sig}) on {got}, expected {want} or none")
    if probs:
        r.fail("pins.pcb", "; ".join(probs))
    else:
        r.ok("pins.pcb", f"every header pad carries its slot net (PRESENT_N on GND, no pad or net at {KEY_PIN})")
    if c.net is not None and c.header_ref:
        diff = [f"pad {num}: board {pnets.get(num)}, netlist {c.net.net_of(c.header_ref, num)}"
                for num in sorted(pnets, key=lambda s: int(s) if s.isdigit() else 0)
                if pnets.get(num) != c.net.net_of(c.header_ref, num)]
        if diff:
            r.fail("pins.parity", "the board's header nets differ from the netlist (regenerate the board): "
                                  + "; ".join(diff[:6]) + (" ..." if len(diff) > 6 else ""))
        else:
            r.ok("pins.parity", "the board's header nets equal the netlist's")
    # the support post (SPEC §9; boards/coupon_common.py POST)
    px, py = g.post
    holes = [(f, p) for f in b.footprints.values() for p in f.pads
             if p.drill and abs(p.drill - g.post_drill) <= POST_TOL and math.hypot(p.x - px, p.y - py) <= POST_TOL]
    if not holes:
        near = sorted((math.hypot(p.x - px, p.y - py), f.ref, p.drill) for f in b.footprints.values()
                      for p in f.pads if p.drill >= 2.5)
        r.fail("post.hole", f"no {g.post_drill} mm hole at ({px:g}, {py:g})" +
               (f"; nearest large hole {near[0][1]} (dia {near[0][2]:g}) {near[0][0]:.2f} mm away" if near else "")
               + " (SPEC §9: one M3 support post at the corner opposite the header)")
    else:
        f, p = holes[0]
        r.ok("post.hole", f"{f.ref}: {p.drill:g} mm {'NPTH' if p.npth else 'plated'} hole at ({px:g}, {py:g})")
    cu = [x for x in b.post_copper if x[0] < g.post_copper_r - KEEP_TOL]
    if cu:
        r.fail("post.copper", f"copper inside r {g.post_copper_r} mm of the post: " +
               "; ".join(f"{w} on {layer} at {d:.2f} mm" for d, layer, w in cu[:5]))
    else:
        near = b.post_copper[0] if b.post_copper else None
        r.ok("post.copper", f"no copper within r {g.post_copper_r} mm" +
             (f" (nearest: {near[2]} on {near[1]}, {near[0]:.3f} mm)" if near else ""))
    post_refs = {f.ref for f, _p in holes}
    clash = []
    for f in b.footprints.values():
        if f.ref in post_refs:
            continue
        dmin = min((M.dist_to_polygon(px, py, poly) for poly in f.courtyard), default=float("inf"))
        if dmin < g.post_part_r - KEEP_TOL:
            clash.append(f"{f.ref} {dmin:.2f} mm")
    if clash:
        r.fail("post.parts", f"parts within r {g.post_part_r} mm of the post (the spacer and screw head): "
                             + ", ".join(clash))
    else:
        r.ok("post.parts", f"no part within r {g.post_part_r} mm of the post")
    # the placer's keep-outs (boards/coupon_common.keepouts): header tails on top, the post, the bottom side
    if size is not None:
        hits = []
        for f in b.footprints.values():
            if f.ref in post_refs or f is hf:
                continue
            pts = [pt for poly in f.courtyard for pt in M.sample_polygon(poly)]
            pts += [(f.x, f.y)]
            for side, pred in g.keepouts(g.sizes[size]):
                if side not in (f.side, "*"):
                    continue
                if any(pred(x, y) for x, y in pts):
                    hits.append(f"{f.ref} ({'bottom' if f.side == 'B' else 'top'})")
                    break
        if hits:
            r.fail("keepouts", f"in a slot keep-out (the header's pin tails on top, the post, or the bottom, which "
                               f"only the header uses; {g.source} keepouts()): {', '.join(sorted(set(hits)))}")
        else:
            r.ok("keepouts", "nothing in the header-tail, post or bottom-side keep-outs")
    if b.unrouted > 0:
        r.warn("routed", f"pcbnew counts {b.unrouted} unrouted connections (DRC reports them in full)")
    elif b.unrouted == 0:
        r.ok("routed", "no unrouted connection")


def _check_key_pcb(r, hf, g):
    """The key on the board (D2 of 2026-11-27): the header footprint has no pad 39 (no hole for the pulled pin) and
    a real pad 2."""
    numbers = {p.number for p in hf.pads}
    kprobs = []
    if str(KEY_PIN) in numbers:
        kprobs.append(f"{hf.ref} ({hf.fpid}) has a pad {KEY_PIN}: a header pin there hits the socket's plugged hole "
                      f"{KEY_PIN}; use boards/coupon_common.py's keyed footprint ({g.header_fpid}, no pad {KEY_PIN})")
    if str(KEY_NEVER_WITH) not in numbers:
        kprobs.append(f"{hf.ref} has no pad {KEY_NEVER_WITH}: keyed at {KEY_NEVER_WITH} and {KEY_PIN}, a coupon fits "
                      "either way round")
    if kprobs:
        r.fail("key.pcb", "; ".join(kprobs) + " (SPEC §4.2, §4.9)")
    else:
        r.ok("key.pcb", f"{hf.ref} has {len(hf.pads)} pads, none at {KEY_PIN} (the key), and pad {KEY_NEVER_WITH}")


# ---- the netlist against the descriptor ------------------------------------------------------------------------
def check_declared(c, r):
    n, k, h = c.net, c.canon, c.header_ref
    if h is None:
        return
    used = set()
    for grp in D.USES:
        pins = RAIL_PINS.get(grp) or [SIGNAL_PINS[grp]]
        # a pin counts as used when its net reaches a fitted part: a pin whose only other part is DNP is open
        if any(n.net_of(h, p) and c.fitted_members(n.net_of(h, p)) for p in pins):
            used.add(grp)
    decl = set(k["uses"])
    if used != decl:
        parts = []
        if used - decl:
            parts.append(f"connected but not in `uses`: {sorted(used - decl, key=D.USES.index)}")
        if decl - used:
            parts.append(f"in `uses` but not connected (or only to DNP parts): "
                         f"{sorted(decl - used, key=D.USES.index)}")
        r.fail("uses", "; ".join(parts) + " (the firmware powers and drives only what `uses` declares)")
    else:
        r.ok("uses", f"`uses` equals the connected slot pins ({len(used)} groups)")
    # +5V: nothing draws from it unless declared
    p5 = n.net_of(h, RAIL_PINS["+5V"][0])
    loads = sorted({ref for ref, _p in c.fitted_members(p5)}) if p5 else []
    if loads and ("+5V" not in decl or k["rails"]["+5V"]["max_ma"] == 0):
        r.fail("rails.+5V", f"{', '.join(loads)} on +5V, but the descriptor declares no +5V current: the firmware "
                            "would power +5V_Sn without a budget (SPEC §3.5, §4.9)")
    elif p5 and not loads:
        r.warn("rails.+5V", "+5V pins connected to a net with nothing fitted on it")
    elif loads:
        r.ok("rails.+5V", f"+5V feeds {', '.join(loads[:8])}{' ...' if len(loads) > 8 else ''}; declared "
                          f"{k['rails']['+5V']['max_ma']} mA")
    else:
        r.ok("rails.+5V", "+5V not connected, and none declared")
    p3 = n.net_of(h, RAIL_PINS["+3V3"][0])
    if p3 is None:
        r.fail("rails.+3V3", "+3V3 pins not connected: the descriptor EEPROM runs from them (SPEC §4.6)")
    else:
        r.ok("rails.+3V3", f"declared {k['rails']['+3V3']['max_ma']} mA")
    # bulk capacitance from the netlist (SPEC §4.9): fitted capacitors at the header; DNP ones as "if fitted"
    slots = k["slots"] or list(nets.SLOTS)
    for rail, net in (("+3V3", p3), ("+5V", p5)):
        if net is None:
            continue
        caps, unknown, dnp = [], [], []
        for x, ends in c.two_pin("C", fitted=False):
            if sorted(map(str, ends)) == sorted([net, "GND"]):
                v = parse_cap(x.value)
                if v is None:
                    unknown.append((x.ref, x.value))
                else:
                    (dnp if x.dnp else caps).append((x.ref, v))
        total = sum(v for _r, v in caps)
        lim = min(BULK_RULE_UF[rail][s] for s in slots) * 1e-6
        dec = k["rails"][rail]["bulk_uf"] * 1e-6
        txt = f"{fmt_uf(total)} on {rail} ({', '.join(f'{a} {fmt_uf(v)}' for a, v in caps) or 'none'})"
        if unknown:
            txt += f"; values not read: {unknown}"
        if dnp:
            txt += f"; not fitted: {', '.join(f'{a} {fmt_uf(v)}' for a, v in dnp)}"
        if total > lim * (1 + 1e-9):
            r.fail(f"bulk.{rail}", txt + f": above the {fmt_uf(lim)} rule (SPEC §4.9)")
        elif total + sum(v for _r, v in dnp) > lim * (1 + 1e-9):
            r.warn(f"bulk.{rail}", txt + f": fitting the DNP capacitors would exceed the {fmt_uf(lim)} rule")
        elif abs(total - dec) > max(0.1e-6, 0.1 * total):
            r.warn(f"bulk.{rail}", txt + f"; the descriptor declares {fmt_uf(dec)}")
        else:
            r.ok(f"bulk.{rail}", txt + f", within {fmt_uf(lim)}; declared {fmt_uf(dec)}")
    # lanes: declared against connected, R_src and the reference ratios against the resistors, and the lane's load
    ratios = None
    if k["ext"].get("format") == "reference_ratios":
        ratios = list(zip(k["ext"]["ratio"], k["ext"]["tolerance"]))
    for li, ln in enumerate(D.LANES):
        net = c.hpin_net(SIGNAL_PINS[ln])
        x = k["lanes"][ln]
        if net is None or not c.fitted_members(net):
            continue
        if x["kind"] == "unused":
            r.fail(f"lanes.{ln}.declared", f"{ln} is connected but the descriptor declares no lane")
            continue
        rs = x["r_src_ohm"]
        rth, ratio, why = lane_network(c, net)
        if rth is not None and rs is not None:
            txt = f"{ln}: the netlist's resistors give R_src {rth:.0f} ohm ({why}); the descriptor declares {rs}"
            if rs < rth * (1 - RSRC_TOL) - 1:
                r.fail(f"lanes.{ln}.rsrc", txt + ": declared stiffer than it is (the firmware would sample too "
                                                 "fast, SPEC §4.9)")
            elif rs > rth * 1.1 + 1:
                r.warn(f"lanes.{ln}.rsrc", txt + ": declared softer than it is (slower sampling than needed)")
            else:
                r.ok(f"lanes.{ln}.rsrc", txt)
        elif rth is None and rs is not None:
            low, _r, lwhy = lane_network(c, net, active_as_ground=True)
            if low and rs < low * (1 - RSRC_TOL) - 1:
                r.fail(f"lanes.{ln}.rsrc", f"{ln}: declared R_src {rs} ohm, but the coupon's resistors alone put at "
                                           f"least {low:.0f} ohm in the path ({lwhy}): declared stiffer than it can "
                                           "be (the firmware would sample too fast, SPEC §4.9)")
            elif low:
                r.ok(f"lanes.{ln}.rsrc", f"{ln}: declared R_src {rs} ohm; the coupon's resistors alone give at least "
                                         f"{low:.0f} ohm ({lwhy}); the active source's output impedance adds to "
                                         "that and is only declared")
            else:
                r.info(f"lanes.{ln}.rsrc", f"{ln}: R_src not computable from the netlist ({lwhy or why}); declared "
                                           f"{rs} ohm")
        if ratios is not None and ratio is not None:
            want, tol = ratios[li]
            txt = (f"{ln}: the resistors set {ratio:.4f} x +3V3; ext.reference_ratios declares {want:.4f} "
                   f"+- {tol:.4f}")
            if abs(ratio - want) > tol:
                r.fail(f"lanes.{ln}.ratio", txt + ": the firmware's reference check would flag a good coupon")
            else:
                r.ok(f"lanes.{ln}.ratio", txt)
        # the lane's load (SPEC §4.9): the motherboard's 1 nF behind 47 ohm plus the coupon's own capacitors from
        # the lane to any AC ground; sensor outputs, a mux and the traces add to it and are not in the netlist
        grounds = c.ac_grounds()
        caps = [(x_.ref, parse_cap(x_.value) or 0.0) for x_, ends in c.two_pin("C")
                if net in ends and (ends[1] if ends[0] == net else ends[0]) in grounds]
        cpf = sum(v for _r, v in caps) * 1e12
        total = LANE_C_PF + cpf
        cl = x["cload_max_pf"]
        ctxt = (f"{ln}: {cpf:.0f} pF of coupon capacitors" + (f" ({', '.join(a for a, _v in caps)})" if caps else "")
                + f" + the motherboard's {LANE_C_PF} pF = {total:.0f} pF")
        if cl and cpf > cl:
            r.fail(f"lanes.{ln}.cload", ctxt + f": the coupon's own capacitors exceed its sources' rated {cl} pF")
        elif cl and total >= cl:                       # sensor outputs and traces always add to it
            r.warn(f"lanes.{ln}.cload", ctxt + f", at or above the rated {cl} pF before the sensor outputs and "
                                               "traces, if the capacitance behind the 47 ohm counts (SPEC §4.3, "
                                               "§11 #21: not stated)")
        elif cl:
            r.ok(f"lanes.{ln}.cload", ctxt + f", within the rated {cl} pF (sensor outputs and traces not counted)")
        else:
            r.info(f"lanes.{ln}.cload", ctxt + "; the descriptor states no CLoad (0: no limit), so the source's "
                                               "stability into it is not checked (SPEC §4.9)")
    # I2C and SPI devices: declared against what the netlist puts on the slot's buses (a heuristic)
    for bus, sig in (("i2c", "SDA"), ("spi", "SCK")):
        net = c.hpin_net(SIGNAL_PINS[sig])
        found = set()
        if net:
            for ref, _p in c.fitted_members(net):
                if ref == (c.eeprom.ref if c.eeprom else None):
                    continue
                if c.kind_of(ref) not in I2C_PASSIVE_PREFIXES:
                    found.add(ref)
        want = sum(dv["count"] for dv in k["devices"] if dv["bus"] == bus)
        if len(found) != want:
            r.warn(f"devices.{bus}", f"{len(found)} part(s) on {sig} besides the descriptor "
                                     f"({', '.join(sorted(found)) or 'none'}), the descriptor declares {want} {bus} "
                                     "device(s) (a buffer or level shifter would also count)")
        elif want:
            r.ok(f"devices.{bus}", f"{want} {bus} device(s) on {sig}: {', '.join(sorted(found))}")


# ------------------------------------------------------------------------------------------------------ driver
def load_coupon(name, kicad_dir=M.KICAD_DIR, desc_dir=DESC_DIR, net_path=None, pcb_path=None, desc_path=None,
                geometry=None):
    np_, pp = M.board_files(name, kicad_dir)
    net_path = net_path or np_
    pcb_path = pcb_path or pp
    desc_path = desc_path or os.path.join(desc_dir, f"{name}.json")
    net = M.read_netlist(net_path) if os.path.exists(net_path) else None
    board = None
    if os.path.exists(pcb_path):
        try:
            if geometry is None:
                geometry = M.load_geometry()
            board = M.read_board(pcb_path, geometry)
        except ImportError:                            # no pcbnew here: the netlist and descriptor rules still run
            board = None
    desc = D.load_json(desc_path) if os.path.exists(desc_path) else None
    return Coupon(name, net, board, desc, desc_path, geometry)


def generated_coupons(kicad_dir=M.KICAD_DIR):
    return [b for b in COUPON_BOARDS if os.path.isdir(os.path.join(kicad_dir, b))]


def release_gate(c, r):
    """--release: what must also hold before a coupon's boards are ordered or its production images written. A
    placeholder descriptor, a missing netlist or board, or an unrouted board is then a FAIL, not a WARN or SKIP."""
    k = c.canon
    if c.desc is None or k is None:
        r.fail("release.descriptor", "no valid descriptor")
    elif "placeholder" in k["flags"]:
        r.fail("release.descriptor", "the descriptor is a placeholder: write it from the captured design")
    else:
        r.ok("release.descriptor", "not a placeholder" + (f" (estimates: {', '.join(c.desc['placeholder_fields'])})"
                                                          if c.desc.get("placeholder_fields") else ""))
    if c.net is None or c.board is None:
        r.fail("release.files", f"netlist {'found' if c.net else 'missing'}, board {'found' if c.board else 'missing'}"
                                ": release checks the generated files")
    elif c.board.unrouted != 0:
        r.fail("release.routed", f"pcbnew counts {c.board.unrouted} unrouted connections" if c.board.unrouted > 0
               else "pcbnew's connectivity could not be computed")
    else:
        r.ok("release.routed", "no unrouted connection (DRC is layout.py's and release.py's)")


# The default slot assignment (SPEC §2): the coupons the firmware may power together.
DEFAULT_SET = {1: "coupon-hall", 2: "coupon-tmr", 3: "coupon-shear", 4: "coupon-coil", 5: "coupon-haptics"}


def fleet_report(desc_dir=DESC_DIR):
    """The five default coupons together (SPEC §3.2): their +3V3 against the slot LDO's 300 mA, and their sum against
    each USB-C source's VSYS budget. The firmware refuses whatever does not fit (SPEC §3.2), so this says which
    sessions can run all five at once. INFO and WARN only: it is a plan, not a rule of SPEC §4.9."""
    r = Report("fleet: the default assignment S1-S5 together (SPEC §2, §3.2)")
    i3 = i5 = 0
    parts, ph = [], []
    for slot, board in DEFAULT_SET.items():
        p = os.path.join(desc_dir, board + ".json")
        if not os.path.exists(p):
            r.skip(f"fleet.S{slot}", f"no descriptor for {board}")
            continue
        try:
            k = D.canonical(dict(D.load_json(p), git=""))
        except D.DescriptorError as e:
            r.skip(f"fleet.S{slot}", f"{board}: {e}")
            continue
        a, b = k["rails"]["+3V3"]["max_ma"], k["rails"]["+5V"]["max_ma"]
        i3, i5 = i3 + a, i5 + b
        parts.append(f"S{slot} {board} {a}/{b}")
        if "placeholder" in k["flags"]:
            ph.append(board)
    note = f" (placeholders: {', '.join(ph)})" if ph else ""
    txt = f"+3V3 max {i3} mA in all ({'; '.join(parts)}, mA on +3V3/+5V){note}"
    if i3 > SLOT_LDO_MA:
        r.warn("fleet.slot_ldo", txt + f": above the slot LDO's {SLOT_LDO_MA} mA, so the firmware cannot power all "
                                       "five at once (SPEC §3.2)")
    else:
        r.ok("fleet.slot_ldo", txt + f", within the slot LDO's {SLOT_LDO_MA} mA")
    tot = BASE_LOAD_MA + i3 + i5
    fits = [name for name, ma in SOURCE_BUDGETS_MA if tot <= ma]
    msg = (f"base {BASE_LOAD_MA} + {i3} + {i5} = {tot} mA of VSYS for all five")
    if fits:
        r.info("fleet.vsys", msg + f": fits a source that advertises {fits[0]} or more{note}")
    else:
        r.warn("fleet.vsys", msg + f": above even the {SOURCE_BUDGETS_MA[-1][1]} mA ceiling{note}")
    return r


def main(argv=None):
    ap = argparse.ArgumentParser(description="Coupon rules check (compiler v0): SPEC §2, §4, §4.9")
    ap.add_argument("boards", nargs="*", help=f"coupon boards (default: every generated one of {COUPON_BOARDS})")
    ap.add_argument("--all", action="store_true", help="also report coupons not generated yet (as SKIP), and the "
                                                       "five default coupons together (fleet)")
    ap.add_argument("--release", action="store_true", help="also FAIL a placeholder descriptor, a missing netlist "
                                                           "or board, and an unrouted board (before ordering boards "
                                                           "or writing production images)")
    ap.add_argument("--kicad-dir", default=M.KICAD_DIR)
    ap.add_argument("--desc-dir", default=DESC_DIR)
    ap.add_argument("--net", help="explicit netlist (one board)")
    ap.add_argument("--pcb", help="explicit .kicad_pcb (one board)")
    ap.add_argument("--desc", help="explicit descriptor JSON (one board)")
    ap.add_argument("--json", help="write every row as JSON here")
    ap.add_argument("--quiet", action="store_true", help="print only WARN and FAIL rows")
    a = ap.parse_args(argv)
    boards = a.boards or (COUPON_BOARDS if a.all else generated_coupons(a.kicad_dir))
    if a.net or a.pcb or a.desc:
        if len(a.boards) > 1:
            ap.error("--net/--pcb/--desc take at most one board name")
        if not a.boards:
            name = D.load_json(a.desc).get("board") if a.desc and os.path.exists(a.desc) else None
            boards = [name or "coupon"]
    reports, checked = [], 0
    for name in boards:
        c = load_coupon(name, a.kicad_dir, a.desc_dir, a.net, a.pcb, a.desc)
        if c.net is None and c.board is None and not (a.net or a.pcb):
            rep = Report(name)
            rep.skip("board", f"not generated yet (no {os.path.relpath(os.path.join(a.kicad_dir, name), M.REPO)})")
            if c.desc is not None:
                check_descriptor(c, rep)
            if a.release:
                release_gate(c, rep)
            reports.append(rep)
            print(rep.table(a.quiet))
            print()
            continue
        checked += 1
        rep = check(c)
        if a.release:
            release_gate(c, rep)
        reports.append(rep)
        print(rep.table(a.quiet))
        print()
    if a.all:
        fl = fleet_report(a.desc_dir)
        print(fl.table(a.quiet))
        print()
    if a.json:
        with open(a.json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump([{"board": rp.name, "failed": rp.failed,
                        "rows": [{"rule": ru, "result": res, "detail": det} for ru, res, det in rp.rows]}
                       for rp in reports], fh, indent=1)
    failed = [rp.name for rp in reports if rp.failed and any(ru != "board" for ru, _r, _d in rp.rows)]
    gen = [rp.name for rp in reports if not any(ru == "board" and res == "SKIP" for ru, res, _d in rp.rows)]
    ph = [rp.name for rp in reports if any(ru == "desc.placeholder" and res == "WARN" for ru, res, _d in rp.rows)]
    print(f"coupon rules{' (release)' if a.release else ''}: {checked} generated coupon(s) checked "
          f"({', '.join(gen) or 'none'})" + (f"; FAILED: {', '.join(failed)}" if failed else "; no FAIL")
          + (f"; placeholder descriptors (not release-ready): {', '.join(ph)}" if ph and not a.release else ""))
    if checked == 0 and not failed:
        return 2
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
