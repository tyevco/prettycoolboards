#!/usr/bin/env python3
"""The coupon descriptor: the 256-byte image in every coupon's 2 kbit EEPROM at 0x50 (SPEC §4.6), format 1.0.

usage:
    python descriptor.py encode IN.json [-o OUT.bin]     # JSON -> image (validates every field)
    python descriptor.py decode IN.bin [-o OUT.json]     # image -> canonical JSON (checks magic, version, CRC)
    python descriptor.py header [-o coupon_desc.h]       # the C header firmware parses the same layout with
    python descriptor.py header --check                  # exit 1 if coupon_desc.h is not what this file generates
    python descriptor.py doc [--check DESCRIPTOR.md]     # the layout and enum tables of DESCRIPTOR.md

The layout is defined once, in LAYOUT below; the encoder, the decoder, the C header and the tables in DESCRIPTOR.md
are all generated from it, and tests/test_descriptor.py freezes every offset. Little-endian throughout (the
STM32U5A5 is little-endian), floats are IEEE 754 binary32, and the CRC is CRC-32/IEEE (zlib.crc32, the same as
Zephyr v4.5.0's crc32_ieee() in subsys/crc/crc32_sw.c: reflected polynomial 0xEDB88320, initial value and final XOR
0xFFFFFFFF) over bytes 0 to length - 5, stored little-endian in the last four bytes.

Status: a format designed on paper (compiler v0, SPEC §11 #18). No coupon EEPROM has been written or read; the
round trips in tests/ prove the code and the arithmetic, not hardware.

This module has no dependency outside the Python standard library, so firmware-side and host-side tools can use it
alone. The coupon rules (what a descriptor may declare) live in rules.py; this file only says what the bytes mean.
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
HEADER_PATH = os.path.join(HERE, "coupon_desc.h")
DOC_PATH = os.path.join(HERE, "DESCRIPTOR.md")

FORMAT_MAJOR = 1               # a change that an older reader would misread: readers refuse another major
FORMAT_MINOR = 0               # additions in reserved space only: readers accept a newer minor and ignore them
MAGIC = b"PCKC"                # PrettyCool Keyboard Coupon
SIZE = 256                     # M24C02: 2 kbit = 256 bytes, one I2C address (ST DocID024020 Rev 2, Features)
I2C_ADDR = 0x50                # E2-E1-E0 = GND: device select 1010 000 (SPEC §4.6, §4.9)
PAGE_SIZE = 16                 # "Page size: 16 bytes"; a page write rolls over inside its page (DocID024020 §5.1.2)
WRITE_TIME_MS = 5              # tW, byte or page write, max (DocID024020 Features and AC tables)
BLANK_BYTE = 0xFF              # "delivered with all the memory array bits set to 1" (DocID024020 §6)


class DescriptorError(ValueError):
    """An image or a JSON descriptor that does not follow format 1. `kind` says which check failed."""

    def __init__(self, kind, problems):
        self.kind = kind
        self.problems = [problems] if isinstance(problems, str) else list(problems)
        super().__init__(f"{kind}: " + "; ".join(self.problems))


# --------------------------------------------------------------------------------------------------- enumerations
# name -> value. Frozen for format 1: a value is never reused or renumbered. New names may be added (a minor bump).
COUPON_TYPES = {"test": 1, "hall": 2, "tmr": 3, "shear": 4, "coil": 5, "haptics": 6, "kvm": 7}
SIZE_CLASSES = {"standard": 0, "wide": 1}      # SPEC §2: about 58 x 60 and 80 x 60 mm (boards/coupon_common.py)
SELECT_SCHEMES = {"none": 0, "binary": 1, "one_hot": 2, "addr_strap": 3, "chip_select": 4}
LANE_KINDS = {"unused": 0, "hall": 1, "tmr": 2, "reference": 3, "thermistor": 4, "current": 5, "angle": 6,
              "voltage": 7}
UNITS = {"ratio": 0, "mT": 1, "degC": 2, "A": 3, "deg": 4, "V": 5, "ohm": 6}
GLINE_ROLES = {"unused": 0, "sel": 1, "sel_en": 2, "cs": 3, "addr": 4, "pwm_high": 5, "pwm_low": 6, "enable": 7,
               "load": 8, "led": 9, "irq_test": 10, "input": 11}
CS_ROLES = {"unused": 0, "spi_cs": 1, "strobe": 2, "enable": 3}
BUSES = {"none": 0, "i2c": 1, "spi": 2, "analog": 3, "gpio": 4}
IRQS = {"none": 0, "irq_n": 1, "bkin": 2}
EXT_FORMATS = {"none": 0, "reference_ratios": 1, "site_map": 2}
SITE_KINDS = {"empty": 0, "key": 1, "aftertouch": 2, "reference": 3, "thermistor": 4, "other": 5}
PARTS = {                      # device part IDs (u16), for the firmware's driver choice
    "other": 0xFFFF,
    "m24c02": 0x0001,          # the descriptor EEPROM itself (implied, never listed in `devices`)
    "tmag5253": 0x0010, "tmag5170": 0x0011, "tmr_sensor": 0x0012, "ntc": 0x0013, "analog_mux": 0x0014,
    "ldc1614": 0x0020,
    "drv8316": 0x0030, "mt6701": 0x0031, "drv2605l": 0x0032, "touch_controller": 0x0033, "tca9535": 0x0034,
    "sn74lv165a": 0x0040,
}

# Bit sets: name -> bit position.
FLAGS = {"placeholder": 0, "git_dirty": 1}
NEEDS = {"pwm_g0_g3": 0, "tim1": 1, "high_current_5v": 2, "lanes_14bit": 3, "fast_g4_g5": 4,
         "exercises_current_limit": 5, "bkin_on_irq": 6}
# One bit per slot pin group the coupon connects, in this frozen order (nets.SLOT_SIGNALS without PRESENT_N, which
# every coupon straps to GND, after the two rails). tests/test_descriptor.py checks it against nets.py.
USES = ["+3V3", "+5V", "AN0", "AN1", "AN2", "AN3", "INJ", "SYNC", "SCK", "MISO", "MOSI", "CS0_N", "CS1_N", "SCL",
        "SDA", "IRQ_N", "G0", "G1", "G2", "G3", "G4", "G5"]
# Bits 22-31 of `uses` name no slot pin. Pin 39 has none either: it is the slot key (the owner's decision D2 of
# 2026-11-27, nets.SLOT_KEY_PIN; it was RSV), absent from every coupon, so no descriptor may claim it. A same-minor
# image with any of those bits set is refused (decode(strict=True)); tests check USES against nets.SLOT_PINS.
USES_MASK = (1 << len(USES)) - 1
LANE_FLAGS = {"ratiometric": 0, "multiplexed": 1, "buffered": 2, "bipolar": 3, "adc4_ok": 4}
GLINE_FLAGS = {"active_low": 0, "fast": 1, "pwm": 2, "exceeds_rule": 3, "not_on_s5": 4}
CS_FLAGS = {"active_high": 0}
DEV_FLAGS = {"polled": 0, "addr_selected": 1, "shares_lane": 2}
EXT_FLAG_BITS = {"measured": 0}

RAILS = ["+3V3", "+5V"]
LANES = ["AN0", "AN1", "AN2", "AN3"]
GLINES = ["G0", "G1", "G2", "G3", "G4", "G5"]
CSES = ["CS0_N", "CS1_N"]
MAX_DEVICES = 7
SPI_SELECTS = ["CS0_N", "CS1_N", *GLINES]        # an SPI device's `addr`: the index of its select line here
NO_DEVICE = 0xFF

# What each slot offers (SPEC §2 default assignment, §4.2 pin notes, §4.4 per-slot MCU map, §3.1 rails). The needs
# bits above are checked against it; tests/test_descriptor.py checks it against nets.py.
SLOT_CAPS = {
    1: {"size": "standard", "needs": {"lanes_14bit"}},
    2: {"size": "standard", "needs": {"lanes_14bit"}},
    3: {"size": "standard", "needs": {"lanes_14bit"}},
    4: {"size": "wide", "needs": {"lanes_14bit", "pwm_g0_g3"}},                       # G0-G3 on TIM8 CH1-CH4
    5: {"size": "wide", "needs": {"pwm_g0_g3", "tim1", "high_current_5v", "fast_g4_g5", "bkin_on_irq"}},
}
SIZE_FITS = {"standard": {"standard", "wide"}, "wide": {"wide"}}   # SPEC §2: any slot of its size or larger
ALWAYS_OK_NEEDS = {"exercises_current_limit"}


def compatible_slots(size, needs):
    """The slots a coupon of this size class and needs can be plugged into (SPEC §2, §4.4)."""
    return [n for n, cap in SLOT_CAPS.items()
            if cap["size"] in SIZE_FITS[size] and set(needs) - ALWAYS_OK_NEEDS <= cap["needs"]]


# --------------------------------------------------------------------------------------------------------- layout
class Struct:
    """A packed little-endian C struct: fields (name, type, count, doc). type is u8/u16/u32/f32/char or a Struct."""

    def __init__(self, cname, fields, doc=""):
        self.cname, self.doc = cname, doc
        self.fields = []
        off = 0
        for name, typ, count, fdoc in fields:
            size = (typ.size if isinstance(typ, Struct) else _SCALAR[typ][1]) * count
            self.fields.append((name, typ, count, fdoc, off, size))
            off += size
        self.size = off

    def offset(self, name):
        return next(f[4] for f in self.fields if f[0] == name)


_SCALAR = {"u8": ("B", 1, "uint8_t"), "u16": ("H", 2, "uint16_t"), "u32": ("I", 4, "uint32_t"),
           "f32": ("f", 4, "float"), "char": ("s", 1, "char")}

RAIL = Struct("coupon_desc_rail", [
    ("typ_ma", "u16", 1, "typical (mean) current the coupon draws from this rail, mA"),
    ("max_ma", "u16", 1, "the most it ever draws, mA: the budget the firmware reserves (SPEC §3.2)"),
    ("bulk_uf_x10", "u16", 1, "bulk capacitance on the rail at the header, in 0.1 uF (SPEC §4.9)"),
    ("startup_ms", "u8", 1, "time after the rail is up before the coupon's parts are ready, ms"),
    ("reserved", "u8", 1, "0"),
], "one per rail: [0] +3V3, [1] +5V")
LANE = Struct("coupon_desc_lane", [
    ("kind", "u8", 1, "lane kind (enum coupon_lane_kind); 0 = not connected"),
    ("flags", "u8", 1, "COUPON_LANE_F_* bits"),
    ("sites", "u8", 1, "sensors or sites read on this lane (one per select step)"),
    ("unit", "u8", 1, "physical unit of `value` (enum coupon_unit)"),
    ("r_src_ohm", "u16", 1, "source impedance seen by the lane, ohm, the coupon side only (SPEC §4.9); "
                            "0xFFFF = not known"),
    ("cload_max_pf", "u16", 1, "smallest rated load capacitance of the sources on the lane, pF; 0 = no limit"),
    ("offset", "f32", 1, "scaling: value = (code / full scale - offset) * gain (ratiometric: a fraction of VDDA)"),
    ("gain", "f32", 1, "scaling gain, unit per full scale"),
], "one per analog lane AN0-AN3")
GLINE = Struct("coupon_desc_gline", [
    ("role", "u8", 1, "enum coupon_gline_role"),
    ("arg", "u8", 1, "role argument: select bit, device index, PWM phase or load number"),
    ("flags", "u8", 1, "COUPON_GLINE_F_* bits"),
    ("reserved", "u8", 1, "0"),
], "one per G-line G0-G5")
CS = Struct("coupon_desc_cs", [
    ("role", "u8", 1, "enum coupon_cs_role"),
    ("device", "u8", 1, "index into devices[], 0xFF = none"),
    ("flags", "u8", 1, "COUPON_CS_F_* bits"),
    ("reserved", "u8", 1, "0"),
], "[0] CS0_N, [1] CS1_N")
DEVICE = Struct("coupon_desc_device", [
    ("part", "u16", 1, "enum coupon_part; 0 = empty entry"),
    ("bus", "u8", 1, "enum coupon_bus"),
    ("addr", "u8", 1, "I2C: 7-bit address; SPI: select line (0 CS0_N, 1 CS1_N, 2-7 G0-G5); analog: lane mask"),
    ("count", "u8", 1, "identical devices behind this entry (address-selected, or sensors on lanes)"),
    ("irq", "u8", 1, "enum coupon_irq"),
    ("flags", "u8", 1, "COUPON_DEV_F_* bits"),
    ("spi_mode", "u8", 1, "SPI mode 0-3 (CPOL, CPHA) for an SPI device; 0 otherwise"),
], "the coupon's devices other than the descriptor EEPROM")
LAYOUT = Struct("coupon_desc", [
    ("magic", "char", 4, "\"PCKC\""),
    ("fmt_major", "u8", 1, "format major version (1): a reader refuses any other"),
    ("fmt_minor", "u8", 1, "format minor version (0): a reader accepts a newer one"),
    ("length", "u16", 1, "bytes in the descriptor, CRC included (256)"),
    ("coupon_type", "u8", 1, "enum coupon_type"),
    ("coupon_rev", "u8", 1, "board revision, ASCII 'A'-'Z'"),
    ("size_class", "u8", 1, "enum coupon_size"),
    ("default_slot", "u8", 1, "the slot it is designed for, 1-5 (SPEC §2)"),
    ("slot_mask", "u8", 1, "bit n-1 set: the coupon may be used in slot n"),
    ("flags", "u8", 1, "COUPON_FLAG_* bits"),
    ("needs", "u16", 1, "COUPON_NEEDS_* bits: slot features beyond the common pinout"),
    ("serial", "u32", 1, "serial number of this coupon (0 = not assigned)"),
    ("date", "u32", 1, "the descriptor's date, yyyymmdd as a decimal number (the JSON's, or make_eeprom.py --today)"),
    ("git_hash", "u8", 8, "first 8 bytes of the git commit of the board's generated files"),
    ("uses", "u32", 1, "COUPON_USES_* bits: the slot pins the coupon connects"),
    ("spi_max_khz", "u16", 1, "highest SPI clock all of its SPI devices accept, kHz (0: no SPI)"),
    ("i2c_max_khz", "u16", 1, "highest I2C clock its I2C devices accept, kHz (the descriptor EEPROM: 400)"),
    ("select_scheme", "u8", 1, "enum coupon_select: how the G-lines pick the site a lane reads"),
    ("select_steps", "u8", 1, "select steps per scan frame (0: none)"),
    ("select_settle_ns", "u16", 1, "time from a select change to a settled lane, ns, coupon side only"),
    ("reserved0", "u32", 1, "0"),
    ("rails", RAIL, 2, "[0] +3V3, [1] +5V"),
    ("lanes", LANE, 4, "AN0-AN3"),
    ("glines", GLINE, 6, "G0-G5"),
    ("cs", CS, 2, "CS0_N, CS1_N"),
    ("devices", DEVICE, MAX_DEVICES, "up to 7 devices"),
    ("ext_format", "u8", 1, "enum coupon_ext: what ext[] holds"),
    ("ext_flags", "u8", 1, "COUPON_EXT_F_* bits"),
    ("ext_reserved", "u16", 1, "0"),
    ("ext", "u8", 32, "type-specific block (reference ratios, site map)"),
    ("crc32", "u32", 1, "CRC-32/IEEE of bytes 0x00-0xFB"),
], "the whole descriptor, 256 bytes")
assert LAYOUT.size == SIZE, LAYOUT.size
CRC_OFFSET = LAYOUT.offset("crc32")

_RESERVED = {"reserved0", "ext_reserved"}


def _fmt(st):
    out = ""
    for _name, typ, count, _doc, _off, _size in st.fields:
        if isinstance(typ, Struct):
            out += _fmt(typ) * count
        elif typ == "char":
            out += f"{count}s"
        else:
            out += _SCALAR[typ][0] * count
    return out


STRUCT_FMT = "<" + _fmt(LAYOUT)
assert struct.calcsize(STRUCT_FMT) == SIZE


def _flatten(st, values):
    """values: {field: value or [values] or [dicts]} -> flat tuple in struct order."""
    out = []
    for name, typ, count, _doc, _off, _size in st.fields:
        v = values[name]
        if isinstance(typ, Struct):
            for k in range(count):
                out.extend(_flatten(typ, v[k]))
        elif typ == "char":
            out.append(v)
        elif count == 1:
            out.append(v)
        else:
            out.extend(v)
    return out


def _unflatten(st, flat, pos=0):
    out = {}
    for name, typ, count, _doc, _off, _size in st.fields:
        if isinstance(typ, Struct):
            items = []
            for _ in range(count):
                item, pos = _unflatten(typ, flat, pos)
                items.append(item)
            out[name] = items
        elif typ == "char" or count == 1:
            out[name] = flat[pos]
            pos += 1
        else:
            out[name] = list(flat[pos:pos + count])
            pos += count
    return out, pos


def crc32(data):
    """CRC-32/IEEE as Zephyr's crc32_ieee() computes it (= zlib.crc32)."""
    return zlib.crc32(bytes(data)) & 0xFFFFFFFF


# ------------------------------------------------------------------------------------------------ JSON <-> fields
DOC_KEYS = {"board", "notes", "placeholder_fields", "ref", "name", "note", "source"}   # kept in JSON, never encoded


def _bits(names, table, what, problems):
    v = 0
    for n in names or []:
        if n not in table:
            problems.append(f"{what}: unknown name {n!r} (known: {', '.join(table)})")
            continue
        v |= 1 << table[n]
    return v


def _names(value, table):
    return [n for n, b in sorted(table.items(), key=lambda kv: kv[1]) if value >> b & 1]


def _enum(name, table, what, problems):
    if name not in table:
        problems.append(f"{what}: unknown {name!r} (known: {', '.join(table)})")
        return 0
    return table[name]


def _rev_enum(value, table, what, problems):
    for k, v in table.items():
        if v == value:
            return k
    if problems is not None:                       # None: a newer minor's image, whose new names are allowed
        problems.append(f"{what}: value {value} is not defined in format {FORMAT_MAJOR}.{FORMAT_MINOR}")
    return f"unknown({value})"


def _check_keys(obj, allowed, what, problems):
    if not isinstance(obj, dict):
        problems.append(f"{what}: expected an object, got {type(obj).__name__}")
        return False
    for k in obj:
        if k not in allowed and k not in DOC_KEYS and not k.startswith("_"):
            problems.append(f"{what}: unknown key {k!r}")
    return True


def _int(v, lo, hi, what, problems):
    if isinstance(v, bool) or not isinstance(v, int):
        problems.append(f"{what}: {v!r} is not an integer")
        return 0
    if not lo <= v <= hi:
        problems.append(f"{what}: {v} outside {lo}..{hi}")
        return min(max(v, lo), hi)
    return v


def _f32(v, what, problems):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        problems.append(f"{what}: {v!r} is not a finite number")
        return 0.0
    try:
        return struct.unpack("<f", struct.pack("<f", float(v)))[0]
    except OverflowError:
        problems.append(f"{what}: {v!r} does not fit a 32-bit float")
        return 0.0


def _date(s, problems):
    try:
        d = datetime.date.fromisoformat(str(s))
    except ValueError:
        problems.append(f"date: {s!r} is not YYYY-MM-DD")
        return 0
    return d.year * 10000 + d.month * 100 + d.day


def _git(s, problems):
    s = (s or "").strip().lower()
    if not s:
        return [0] * 8
    if any(c not in "0123456789abcdef" for c in s) or len(s) < 7:
        problems.append(f"git: {s!r} is not a hex commit hash of 7 or more digits (resolve 'auto' first)")
        return [0] * 8
    s = (s + "0" * 16)[:16]
    return list(bytes.fromhex(s))


def _defaults_lane():
    return {"kind": 0, "flags": 0, "sites": 0, "unit": 0, "r_src_ohm": 0, "cload_max_pf": 0, "offset": 0.0,
            "gain": 0.0}


def from_json(d):
    """A JSON descriptor (dict) -> the field values of LAYOUT. Raises DescriptorError listing every problem."""
    p = []
    top = {"format", "type", "rev", "size", "default_slot", "slots", "flags", "placeholder", "needs", "serial",
           "date", "git", "uses", "spi", "i2c", "select", "rails", "lanes", "glines", "cs", "devices", "ext"}
    _check_keys(d, top, "descriptor", p)
    if "format" in d and str(d["format"]).split(".")[0] != str(FORMAT_MAJOR):
        p.append(f"format: {d['format']!r} is not format {FORMAT_MAJOR}.x")
    f = {"magic": MAGIC, "fmt_major": FORMAT_MAJOR, "fmt_minor": FORMAT_MINOR, "length": SIZE,
         "reserved0": 0, "ext_reserved": 0, "crc32": 0}
    f["coupon_type"] = _enum(d.get("type"), COUPON_TYPES, "type", p)
    rev = str(d.get("rev", ""))
    if len(rev) != 1 or not "A" <= rev <= "Z":
        p.append(f"rev: {rev!r} is not one letter A-Z")
        rev = "A"
    f["coupon_rev"] = ord(rev)
    size = d.get("size", "standard")
    f["size_class"] = _enum(size, SIZE_CLASSES, "size", p)
    needs = list(d.get("needs", []))
    f["needs"] = _bits(needs, NEEDS, "needs", p)
    slots = d.get("slots")
    if slots is None:
        slots = compatible_slots(size, needs) if size in SIZE_FITS else []
    mask = 0
    for n in slots:
        if _int(n, 1, 5, "slots", p) == n:
            mask |= 1 << (n - 1)
    f["slot_mask"] = mask
    f["default_slot"] = _int(d.get("default_slot", 0), 1, 5, "default_slot", p)
    if mask and not mask >> (f["default_slot"] - 1) & 1:
        p.append(f"default_slot {f['default_slot']} is not in slots {sorted(slots)}")
    if size in SIZE_FITS:
        bad = sorted(set(slots) - set(compatible_slots(size, needs)))
        if bad:
            p.append(f"slots {bad} cannot take a {size} coupon with needs {sorted(needs)} (SPEC §2, §4.4)")
    flags = list(d.get("flags", []))
    if d.get("placeholder") and "placeholder" not in flags:
        flags.append("placeholder")
    f["flags"] = _bits(flags, FLAGS, "flags", p)
    f["serial"] = _int(d.get("serial", 0), 0, 0xFFFFFFFF, "serial", p)
    f["date"] = _date(d.get("date", "2000-01-01"), p)
    f["git_hash"] = _git(d.get("git", ""), p)
    uses = list(d.get("uses", []))
    f["uses"] = _bits(uses, {n: i for i, n in enumerate(USES)}, "uses", p)

    spi = d.get("spi", {})
    _check_keys(spi, {"max_khz"}, "spi", p)
    f["spi_max_khz"] = _int(spi.get("max_khz", 0), 0, 0xFFFF, "spi.max_khz", p)
    i2c = d.get("i2c", {})
    _check_keys(i2c, {"max_khz"}, "i2c", p)
    f["i2c_max_khz"] = _int(i2c.get("max_khz", 400), 0, 0xFFFF, "i2c.max_khz", p)
    sel = d.get("select", {})
    _check_keys(sel, {"scheme", "steps", "settle_ns"}, "select", p)
    f["select_scheme"] = _enum(sel.get("scheme", "none"), SELECT_SCHEMES, "select.scheme", p)
    f["select_steps"] = _int(sel.get("steps", 0), 0, 255, "select.steps", p)
    f["select_settle_ns"] = _int(sel.get("settle_ns", 0), 0, 0xFFFF, "select.settle_ns", p)

    rails = d.get("rails", {})
    _check_keys(rails, set(RAILS), "rails", p)
    f["rails"] = []
    for r in RAILS:
        x = rails.get(r, {})
        _check_keys(x, {"typ_ma", "max_ma", "bulk_uf", "startup_ms"}, f"rails.{r}", p)
        bulk = x.get("bulk_uf", 0)
        if isinstance(bulk, bool) or not isinstance(bulk, (int, float)) or not 0 <= bulk <= 6553.5:
            p.append(f"rails.{r}.bulk_uf: {bulk!r} outside 0-6553.5")
            bulk = 0
        f["rails"].append({"typ_ma": _int(x.get("typ_ma", 0), 0, 0xFFFF, f"rails.{r}.typ_ma", p),
                           "max_ma": _int(x.get("max_ma", 0), 0, 0xFFFF, f"rails.{r}.max_ma", p),
                           "bulk_uf_x10": int(round(bulk * 10)),
                           "startup_ms": _int(x.get("startup_ms", 0), 0, 255, f"rails.{r}.startup_ms", p),
                           "reserved": 0})

    lanes = d.get("lanes", {})
    _check_keys(lanes, set(LANES), "lanes", p)
    f["lanes"] = []
    for ln in LANES:
        x = lanes.get(ln, {"kind": "unused"})
        out = _defaults_lane()
        if _check_keys(x, {"kind", "flags", "sites", "unit", "r_src_ohm", "cload_max_pf", "offset", "gain"},
                       f"lanes.{ln}", p):
            out["kind"] = _enum(x.get("kind", "unused"), LANE_KINDS, f"lanes.{ln}.kind", p)
            if out["kind"]:
                out["flags"] = _bits(x.get("flags", []), LANE_FLAGS, f"lanes.{ln}.flags", p)
                out["sites"] = _int(x.get("sites", 1), 1, 255, f"lanes.{ln}.sites", p)
                out["unit"] = _enum(x.get("unit", "ratio"), UNITS, f"lanes.{ln}.unit", p)
                rs = x.get("r_src_ohm")
                out["r_src_ohm"] = 0xFFFF if rs is None else _int(rs, 0, 0xFFFE, f"lanes.{ln}.r_src_ohm", p)
                out["cload_max_pf"] = _int(x.get("cload_max_pf", 0), 0, 0xFFFF, f"lanes.{ln}.cload_max_pf", p)
                out["offset"] = _f32(x.get("offset", 0.0), f"lanes.{ln}.offset", p)
                out["gain"] = _f32(x.get("gain", 1.0), f"lanes.{ln}.gain", p)
            elif set(x) - {"kind"} - DOC_KEYS:
                p.append(f"lanes.{ln}: an unused lane carries no other fields")
        f["lanes"].append(out)

    devices = d.get("devices", [])
    if not isinstance(devices, list) or len(devices) > MAX_DEVICES:
        p.append(f"devices: at most {MAX_DEVICES} entries (the descriptor EEPROM is implied, not listed)")
        devices = list(devices)[:MAX_DEVICES] if isinstance(devices, list) else []
    f["devices"] = []
    for i, x in enumerate(devices):
        w = f"devices[{i}]"
        out = {"part": 0, "bus": 0, "addr": 0, "count": 0, "irq": 0, "flags": 0, "spi_mode": 0}
        if _check_keys(x, {"part", "bus", "addr", "count", "irq", "flags", "spi_mode"}, w, p):
            out["part"] = _enum(x.get("part"), PARTS, f"{w}.part", p)
            out["bus"] = _enum(x.get("bus", "none"), BUSES, f"{w}.bus", p)
            addr = x.get("addr", 0)
            if out["bus"] == BUSES["spi"] and isinstance(addr, str):
                addr = SPI_SELECTS.index(addr) if addr in SPI_SELECTS else -1
            if out["bus"] == BUSES["analog"] and isinstance(addr, list):
                bad = [a for a in addr if a not in LANES]
                if bad:
                    p.append(f"{w}.addr: {bad} are not lanes ({LANES})")
                addr = sum(1 << LANES.index(a) for a in addr if a in LANES)
            if isinstance(addr, str):
                try:
                    addr = int(addr, 0)
                except ValueError:
                    addr = -1
            out["addr"] = _int(addr, 0, 255, f"{w}.addr", p)
            if out["bus"] == BUSES["i2c"] and not 0x08 <= out["addr"] <= 0x77:
                p.append(f"{w}.addr: 0x{out['addr']:02X} is outside I2C's 0x08-0x77")
            if out["bus"] == BUSES["spi"] and out["addr"] >= len(SPI_SELECTS):
                p.append(f"{w}.addr: SPI select must be one of {SPI_SELECTS}")
            out["count"] = _int(x.get("count", 1), 1, 255, f"{w}.count", p)
            out["irq"] = _enum(x.get("irq", "none"), IRQS, f"{w}.irq", p)
            out["flags"] = _bits(x.get("flags", []), DEV_FLAGS, f"{w}.flags", p)
            if out["bus"] == BUSES["spi"]:
                out["spi_mode"] = _int(x.get("spi_mode", 0), 0, 3, f"{w}.spi_mode", p)
            elif "spi_mode" in x:
                p.append(f"{w}.spi_mode: only an SPI device has an SPI mode")
        f["devices"].append(out)
    while len(f["devices"]) < MAX_DEVICES:
        f["devices"].append({"part": 0, "bus": 0, "addr": 0, "count": 0, "irq": 0, "flags": 0, "spi_mode": 0})

    gl = d.get("glines", {})
    _check_keys(gl, set(GLINES), "glines", p)
    f["glines"] = []
    for g in GLINES:
        x = gl.get(g, {"role": "unused"})
        out = {"role": 0, "arg": 0, "flags": 0, "reserved": 0}
        if _check_keys(x, {"role", "arg", "flags"}, f"glines.{g}", p):
            out["role"] = _enum(x.get("role", "unused"), GLINE_ROLES, f"glines.{g}.role", p)
            out["arg"] = _int(x.get("arg", 0), 0, 255, f"glines.{g}.arg", p)
            out["flags"] = _bits(x.get("flags", []), GLINE_FLAGS, f"glines.{g}.flags", p)
        f["glines"].append(out)

    cs = d.get("cs", {})
    _check_keys(cs, set(CSES), "cs", p)
    f["cs"] = []
    for c in CSES:
        x = cs.get(c, {"role": "unused"})
        out = {"role": 0, "device": NO_DEVICE, "flags": 0, "reserved": 0}
        if _check_keys(x, {"role", "device", "flags"}, f"cs.{c}", p):
            out["role"] = _enum(x.get("role", "unused"), CS_ROLES, f"cs.{c}.role", p)
            dev = x.get("device")
            if dev is not None and not devices:
                p.append(f"cs.{c}.device: {dev} names a device, but `devices` is empty")
            out["device"] = NO_DEVICE if dev is None else _int(dev, 0, max(len(devices) - 1, 0),
                                                                f"cs.{c}.device", p)
            out["flags"] = _bits(x.get("flags", []), CS_FLAGS, f"cs.{c}.flags", p)
        f["cs"].append(out)

    ext = d.get("ext", {"format": "none"})
    f["ext_format"], f["ext_flags"], f["ext"] = 0, 0, [0] * 32
    if _check_keys(ext, {"format", "flags", "ratio", "tolerance", "sites"}, "ext", p):
        fmt = _enum(ext.get("format", "none"), EXT_FORMATS, "ext.format", p)
        f["ext_format"] = fmt
        f["ext_flags"] = _bits(ext.get("flags", []), EXT_FLAG_BITS, "ext.flags", p)
        if fmt == EXT_FORMATS["reference_ratios"]:
            ratio, tol = ext.get("ratio", []), ext.get("tolerance", [])
            if len(ratio) != 4 or len(tol) != 4:
                p.append("ext: reference_ratios takes ratio[4] and tolerance[4]")
            vals = [_f32(v, "ext.ratio", p) for v in (list(ratio) + [0.0] * 4)[:4]]
            vals += [_f32(v, "ext.tolerance", p) for v in (list(tol) + [0.0] * 4)[:4]]
            f["ext"] = list(struct.pack("<8f", *vals))
        elif fmt == EXT_FORMATS["site_map"]:
            sites = ext.get("sites", [])          # [step][lane] -> site kind name, up to 8 steps x 4 lanes
            if not isinstance(sites, list) or len(sites) > 8:
                p.append("ext.sites: at most 8 steps of 4 lanes")
                sites = []
            nib = [0] * 32
            for s, row in enumerate(sites):
                if not isinstance(row, list) or len(row) != 4:
                    p.append(f"ext.sites[{s}]: one site kind per lane AN0-AN3")
                    continue
                for ln, kind in enumerate(row):
                    nib[s * 4 + ln] = _enum(kind, SITE_KINDS, f"ext.sites[{s}][{ln}]", p)
            f["ext"] = [nib[2 * i] | nib[2 * i + 1] << 4 for i in range(16)] + [0] * 16
    if p:
        raise DescriptorError("json", p)
    return f


def to_json(f, newer_minor=False):
    """LAYOUT field values -> the canonical JSON descriptor (what decode() returns). newer_minor: the image is of a
    later minor version, which may use enum values this reader does not know; they decode as "unknown(N)"."""
    p = []
    if newer_minor:
        p = None
    d = {"format": f"{f['fmt_major']}.{f['fmt_minor']}",
         "type": _rev_enum(f["coupon_type"], COUPON_TYPES, "coupon_type", p),
         "rev": chr(f["coupon_rev"]) if 0x41 <= f["coupon_rev"] <= 0x5A else f"?{f['coupon_rev']}",
         "size": _rev_enum(f["size_class"], SIZE_CLASSES, "size_class", p),
         "default_slot": f["default_slot"],
         "slots": [n for n in range(1, 6) if f["slot_mask"] >> (n - 1) & 1],
         "flags": _names(f["flags"], FLAGS),
         "needs": _names(f["needs"], NEEDS),
         "serial": f["serial"]}
    y, md = divmod(f["date"], 10000)
    m, dd = divmod(md, 100)
    d["date"] = f"{y:04d}-{m:02d}-{dd:02d}"
    d["git"] = bytes(f["git_hash"]).hex()
    d["uses"] = [n for i, n in enumerate(USES) if f["uses"] >> i & 1]
    d["spi"] = {"max_khz": f["spi_max_khz"]}
    d["i2c"] = {"max_khz": f["i2c_max_khz"]}
    d["select"] = {"scheme": _rev_enum(f["select_scheme"], SELECT_SCHEMES, "select_scheme", p),
                   "steps": f["select_steps"], "settle_ns": f["select_settle_ns"]}
    d["rails"] = {r: {"typ_ma": x["typ_ma"], "max_ma": x["max_ma"], "bulk_uf": x["bulk_uf_x10"] / 10,
                      "startup_ms": x["startup_ms"]} for r, x in zip(RAILS, f["rails"])}
    d["lanes"] = {}
    for ln, x in zip(LANES, f["lanes"]):
        if x["kind"] == 0:
            d["lanes"][ln] = {"kind": "unused"}
            continue
        d["lanes"][ln] = {"kind": _rev_enum(x["kind"], LANE_KINDS, f"{ln}.kind", p),
                          "flags": _names(x["flags"], LANE_FLAGS), "sites": x["sites"],
                          "unit": _rev_enum(x["unit"], UNITS, f"{ln}.unit", p),
                          "r_src_ohm": None if x["r_src_ohm"] == 0xFFFF else x["r_src_ohm"],
                          "cload_max_pf": x["cload_max_pf"], "offset": x["offset"], "gain": x["gain"]}
    d["glines"] = {g: ({"role": "unused"} if x["role"] == 0 else
                       {"role": _rev_enum(x["role"], GLINE_ROLES, f"{g}.role", p), "arg": x["arg"],
                        "flags": _names(x["flags"], GLINE_FLAGS)}) for g, x in zip(GLINES, f["glines"])}
    d["cs"] = {c: ({"role": "unused"} if x["role"] == 0 else
                   {"role": _rev_enum(x["role"], CS_ROLES, f"{c}.role", p),
                    "device": None if x["device"] == NO_DEVICE else x["device"],
                    "flags": _names(x["flags"], CS_FLAGS)}) for c, x in zip(CSES, f["cs"])}
    d["devices"] = []
    for x in f["devices"]:
        if x["part"] == 0:
            continue
        bus = _rev_enum(x["bus"], BUSES, "device.bus", p)
        addr = x["addr"]
        if bus == "spi":
            addr = SPI_SELECTS[addr] if addr < len(SPI_SELECTS) else addr
        elif bus == "analog":
            addr = [ln for i, ln in enumerate(LANES) if addr >> i & 1]
        elif bus == "i2c":
            addr = f"0x{addr:02X}"
        dev = {"part": _rev_enum(x["part"], PARTS, "device.part", p), "bus": bus, "addr": addr,
               "count": x["count"], "irq": _rev_enum(x["irq"], IRQS, "device.irq", p),
               "flags": _names(x["flags"], DEV_FLAGS)}
        if bus == "spi":
            dev["spi_mode"] = x["spi_mode"]
        d["devices"].append(dev)
    fmt = _rev_enum(f["ext_format"], EXT_FORMATS, "ext_format", p)
    ext = {"format": fmt}
    if fmt != "none":
        ext["flags"] = _names(f["ext_flags"], EXT_FLAG_BITS)
    if fmt == "reference_ratios":
        vals = struct.unpack("<8f", bytes(f["ext"]))
        ext["ratio"], ext["tolerance"] = list(vals[:4]), list(vals[4:])
    elif fmt == "site_map":
        nib = [b >> s & 0xF for b in f["ext"][:16] for s in (0, 4)]
        rows = [[_rev_enum(nib[s * 4 + ln], SITE_KINDS, "site", p) for ln in range(4)] for s in range(8)]
        while rows and all(k == "empty" for k in rows[-1]):
            rows.pop()
        ext["sites"] = rows
    d["ext"] = ext
    if p:
        raise DescriptorError("field", p)
    return d


# Another proposal for the same EEPROM: keyboard/firmware/lib/include/tb/desc.h (magic "PCKD", a 24-byte header,
# TLV records, CRC-16/CCITT-FALSE). SPEC §11 #18 asks for one format; until the owner picks one, name it on sight.
OTHER_FORMATS = {b"PCKD": "the keyboard/firmware/lib descriptor (tb/desc.h), another proposal for this EEPROM: "
                          "this reader takes only PCKC (SPEC §11 #18 has to pick one)"}


# ------------------------------------------------------------------------------------------------ encode / decode
def encode(d):
    """JSON descriptor -> 256-byte image (bytes), CRC filled in."""
    f = from_json(d)
    raw = bytearray(struct.pack(STRUCT_FMT, *_flatten(LAYOUT, f)))
    struct.pack_into("<I", raw, CRC_OFFSET, crc32(raw[:CRC_OFFSET]))
    return bytes(raw)


def check_image(img):
    """Header, length and CRC checks a reader makes before trusting any field (DESCRIPTOR.md, "Reading").
    Returns (fmt_major, fmt_minor, length); raises DescriptorError(kind) with kind blank/size/magic/version/length/crc."""
    img = bytes(img)
    if len(img) < SIZE:
        raise DescriptorError("size", f"{len(img)} bytes, a format-1 image is {SIZE}")
    if all(b == BLANK_BYTE for b in img[:SIZE]):
        raise DescriptorError("blank", "every byte is 0xFF: an unwritten EEPROM")
    if img[:4] != MAGIC:
        other = OTHER_FORMATS.get(bytes(img[:4]))
        raise DescriptorError("magic", f"magic {img[:4]!r}, expected {MAGIC!r}" + (f": {other}" if other else ""))
    major, minor, length = img[4], img[5], struct.unpack_from("<H", img, 6)[0]
    if major != FORMAT_MAJOR:
        raise DescriptorError("version", f"format {major}.{minor}; this reader takes {FORMAT_MAJOR}.x")
    if length != SIZE:
        raise DescriptorError("length", f"length field {length}, format 1 is {SIZE}")
    want = struct.unpack_from("<I", img, length - 4)[0]
    got = crc32(img[:length - 4])
    if want != got:
        raise DescriptorError("crc", f"stored CRC 0x{want:08X}, computed 0x{got:08X}")
    return major, minor, length


def decode(img, strict=True):
    """256-byte image -> canonical JSON descriptor. strict: reserved bytes of a same-minor image must be zero."""
    major, minor, _length = check_image(img)
    flat = struct.unpack(STRUCT_FMT, bytes(img[:SIZE]))
    f, _ = _unflatten(LAYOUT, flat)
    if strict and minor <= FORMAT_MINOR:
        bad = [k for k in _RESERVED if k in f and f[k]]
        bad += [f"devices[{i}].spi_mode" for i, x in enumerate(f["devices"])
                if x["bus"] != BUSES["spi"] and x["spi_mode"]]
        bad += [f"devices[{i}] (empty entry)" for i, x in enumerate(f["devices"])
                if x["part"] == 0 and any(v for k, v in x.items() if k != "part")]
        for group in ("rails", "glines", "cs"):
            bad += [f"{group}[{i}].reserved" for i, x in enumerate(f[group]) if x.get("reserved")]
        if f["ext_format"] == EXT_FORMATS["site_map"] and any(f["ext"][16:]):
            bad.append("ext[16:] (site_map uses 16 bytes)")
        if f["ext_format"] == 0 and any(f["ext"]):
            bad.append("ext (format none)")
        if f["uses"] & ~USES_MASK:
            bad.append(f"uses bits 0x{f['uses'] & ~USES_MASK:08X} (no slot pin; pin 39, the slot key, has no bit)")
        if bad:
            raise DescriptorError("reserved", f"non-zero reserved bytes in a format {major}.{minor} image: {bad}")
    return to_json(f, newer_minor=minor > FORMAT_MINOR)


def canonical(d):
    """The canonical form of a JSON descriptor: what an image made from it decodes to."""
    return decode(encode(d))


# --------------------------------------------------------------------------------------------- C header generator
def _c_ident(name):
    return "".join(ch if ch.isalnum() else "_" for ch in name).upper().strip("_")


def _c_enum(tag, prefix, table, doc):
    lines = [f"/* {doc} */", f"enum {tag} {{"]
    for k, v in sorted(table.items(), key=lambda kv: kv[1]):
        lines.append(f"\t{prefix}_{_c_ident(k)} = 0x{v:X},")
    return lines + ["};", ""]


def _c_bits(prefix, table, doc):
    lines = [f"/* {doc} */"]
    for k, b in sorted(table.items(), key=lambda kv: kv[1]):
        lines.append(f"#define {prefix}_{_c_ident(k)} (1u << {b})")
    return lines + [""]


def _c_struct(st):
    lines = [f"/* {st.doc} */", f"struct {st.cname} {{"]
    for name, typ, count, doc, off, _size in st.fields:
        ctype = f"struct {typ.cname}" if isinstance(typ, Struct) else _SCALAR[typ][2]
        arr = f"[{count}]" if count > 1 else ""
        lines.append(f"\t{ctype} {name}{arr}; /* 0x{off:02X}: {doc} */")
    lines.append("} __attribute__((packed));")
    lines.append(f"_Static_assert(sizeof(struct {st.cname}) == {st.size}, \"{st.cname} size\");")
    for name, _typ, _count, _doc, off, _size in st.fields:
        lines.append(f"_Static_assert(offsetof(struct {st.cname}, {name}) == 0x{off:02X}, \"{st.cname}.{name}\");")
    return lines + [""]


def c_header():
    """The text of coupon_desc.h."""
    L = ["/*",
         " * coupon_desc.h: the PrettyCool Keyboard rev A coupon descriptor, format "
         f"{FORMAT_MAJOR}.{FORMAT_MINOR} (keyboard/tools/coupon/DESCRIPTOR.md).",
         " *",
         " * GENERATED by keyboard/tools/coupon/descriptor.py (`python descriptor.py header`). Do not edit: change the",
         " * LAYOUT in descriptor.py and regenerate. tests/test_c_header.py compiles this header on the host against",
         " * Zephyr's own crc32_sw.c and for Cortex-M33, and compares a C reader's view of an image with Python's.",
         " *",
         " * Little-endian, packed, floats are IEEE 754 binary32. Read the 256 bytes at offset 0 of the EEPROM at",
         " * 0x50 on the slot's I2C channel, call coupon_desc_validate(), then memcpy() into struct coupon_desc.",
         " * Status: designed on paper; no coupon EEPROM has been written or read.",
         " * SPDX-License-Identifier: Apache-2.0",
         " */",
         "",
         "#ifndef COUPON_DESC_H_",
         "#define COUPON_DESC_H_",
         "",
         "#include <stddef.h>",
         "#include <stdint.h>",
         "",
         "#if defined(__BYTE_ORDER__) && (__BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__)",
         "#error \"struct coupon_desc assumes a little-endian CPU\"",
         "#endif",
         "_Static_assert(sizeof(float) == 4, \"coupon_desc floats are IEEE 754 binary32\");",
         "",
         f"#define COUPON_DESC_MAGIC \"{MAGIC.decode()}\"",
         f"#define COUPON_DESC_FMT_MAJOR {FORMAT_MAJOR}",
         f"#define COUPON_DESC_FMT_MINOR {FORMAT_MINOR}",
         f"#define COUPON_DESC_SIZE {SIZE}",
         f"#define COUPON_DESC_CRC_OFFSET 0x{CRC_OFFSET:02X}",
         f"#define COUPON_DESC_I2C_ADDR 0x{I2C_ADDR:02X}",
         f"#define COUPON_DESC_PAGE_SIZE {PAGE_SIZE} /* M24C02 page; writes must not cross a page */",
         f"#define COUPON_DESC_WRITE_TIME_MS {WRITE_TIME_MS} /* tW max per page write */",
         f"#define COUPON_DESC_MAX_DEVICES {MAX_DEVICES}",
         f"#define COUPON_DESC_NO_DEVICE 0x{NO_DEVICE:02X}",
         ""]
    L += _c_enum("coupon_type", "COUPON_TYPE", COUPON_TYPES, "coupon_type")
    L += _c_enum("coupon_size", "COUPON_SIZE", SIZE_CLASSES, "size_class")
    L += _c_enum("coupon_select", "COUPON_SELECT", SELECT_SCHEMES, "select_scheme")
    L += _c_enum("coupon_lane_kind", "COUPON_LANE", LANE_KINDS, "lanes[].kind")
    L += _c_enum("coupon_unit", "COUPON_UNIT", UNITS, "lanes[].unit")
    L += _c_enum("coupon_gline_role", "COUPON_GLINE", GLINE_ROLES, "glines[].role")
    L += _c_enum("coupon_cs_role", "COUPON_CS", CS_ROLES, "cs[].role")
    L += _c_enum("coupon_bus", "COUPON_BUS", BUSES, "devices[].bus")
    L += _c_enum("coupon_irq", "COUPON_IRQ", IRQS, "devices[].irq")
    L += _c_enum("coupon_part", "COUPON_PART", PARTS, "devices[].part")
    L += _c_enum("coupon_ext", "COUPON_EXT", EXT_FORMATS, "ext_format")
    L += _c_enum("coupon_site", "COUPON_SITE", SITE_KINDS, "ext site_map nibbles: step s, lane l at nibble 4s+l, "
                                                          "low nibble first")
    L += _c_bits("COUPON_FLAG", FLAGS, "flags")
    L += _c_bits("COUPON_NEEDS", NEEDS, "needs")
    L += _c_bits("COUPON_USES", {n: i for i, n in enumerate(USES)}, "uses: one bit per slot pin group")
    L += _c_bits("COUPON_LANE_F", LANE_FLAGS, "lanes[].flags")
    L += _c_bits("COUPON_GLINE_F", GLINE_FLAGS, "glines[].flags")
    L += _c_bits("COUPON_CS_F", CS_FLAGS, "cs[].flags")
    L += _c_bits("COUPON_DEV_F", DEV_FLAGS, "devices[].flags")
    L += _c_bits("COUPON_EXT_F", EXT_FLAG_BITS, "ext_flags")
    L += ["/* rails[] and lanes[] indices */",
          "enum coupon_rail_index { COUPON_RAIL_3V3 = 0, COUPON_RAIL_5V = 1 };", ""]
    for st in (RAIL, LANE, GLINE, CS, DEVICE, LAYOUT):
        L += _c_struct(st)
    L += ["/* coupon_desc_validate() results */",
          "enum coupon_desc_status {",
          "\tCOUPON_DESC_OK = 0,",
          "\tCOUPON_DESC_E_SIZE = -1,    /* fewer than COUPON_DESC_SIZE bytes */",
          "\tCOUPON_DESC_E_BLANK = -2,   /* all 0xFF: an unwritten EEPROM */",
          "\tCOUPON_DESC_E_MAGIC = -3,   /* not a coupon descriptor */",
          "\tCOUPON_DESC_E_VERSION = -4, /* another major format version */",
          "\tCOUPON_DESC_E_LENGTH = -5,  /* length field is not COUPON_DESC_SIZE */",
          "\tCOUPON_DESC_E_CRC = -6,     /* CRC mismatch */",
          "};",
          "",
          "/* CRC-32/IEEE. On Zephyr v4.5.0 it is crc32_ieee() of <zephyr/sys/crc.h>, which needs CONFIG_CRC=y",
          " * (subsys/crc). Elsewhere, link an implementation with the same definition (zlib's crc32). */",
          "#ifdef __ZEPHYR__",
          "#include <zephyr/sys/crc.h>",
          "#else",
          "uint32_t crc32_ieee(const uint8_t *data, size_t len);",
          "#endif",
          "",
          "static inline uint16_t coupon_desc_le16(const uint8_t *p)",
          "{",
          "\treturn (uint16_t)(p[0] | (p[1] << 8));",
          "}",
          "",
          "static inline uint32_t coupon_desc_le32(const uint8_t *p)",
          "{",
          "\treturn (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);",
          "}",
          "",
          "/* The checks a reader makes before it trusts any field, in this order (DESCRIPTOR.md, \"Reading\"). */",
          "static inline int coupon_desc_validate(const uint8_t *buf, size_t len)",
          "{",
          "\tsize_t i;",
          "\tuint16_t length;",
          "",
          "\tif (len < COUPON_DESC_SIZE) {",
          "\t\treturn COUPON_DESC_E_SIZE;",
          "\t}",
          "\tfor (i = 0; i < COUPON_DESC_SIZE && buf[i] == 0xFFu; i++) {",
          "\t}",
          "\tif (i == COUPON_DESC_SIZE) {",
          "\t\treturn COUPON_DESC_E_BLANK;",
          "\t}",
          "\tif (buf[0] != 'P' || buf[1] != 'C' || buf[2] != 'K' || buf[3] != 'C') {",
          "\t\treturn COUPON_DESC_E_MAGIC;",
          "\t}",
          "\tif (buf[4] != COUPON_DESC_FMT_MAJOR) {",
          "\t\treturn COUPON_DESC_E_VERSION;",
          "\t}",
          "\tlength = coupon_desc_le16(&buf[6]);",
          "\tif (length != COUPON_DESC_SIZE) {",
          "\t\treturn COUPON_DESC_E_LENGTH;",
          "\t}",
          "\tif (crc32_ieee(buf, length - 4u) != coupon_desc_le32(&buf[length - 4u])) {",
          "\t\treturn COUPON_DESC_E_CRC;",
          "\t}",
          "\treturn COUPON_DESC_OK;",
          "}",
          "",
          "#endif /* COUPON_DESC_H_ */",
          ""]
    return "\n".join(L)


# ------------------------------------------------------------------------------------------------- doc generator
def _doc_rows(st, base=0, prefix=""):
    rows = []
    for name, typ, count, doc, off, size in st.fields:
        if isinstance(typ, Struct):
            rows.append((base + off, size, f"struct {typ.cname}[{count}]" if count > 1 else f"struct {typ.cname}",
                         prefix + name, f"{doc} ({typ.size} bytes each)" if count > 1 else doc))
        else:
            ctype = _SCALAR[typ][2] + (f"[{count}]" if count > 1 else "")
            rows.append((base + off, size, ctype, prefix + name, doc))
    return rows


def doc_tables():
    """The generated part of DESCRIPTOR.md: the layout, the sub-structs and every enum and bit set."""
    out = ["<!-- generated by descriptor.py doc: do not edit by hand -->", "",
           f"**Top level** (`struct {LAYOUT.cname}`, {LAYOUT.size} bytes)", "",
           "| Offset | Size | Type | Field | Meaning |", "|---|---|---|---|---|"]
    for off, size, ctype, name, doc in _doc_rows(LAYOUT):
        out.append(f"| 0x{off:02X} | {size} | `{ctype}` | `{name}` | {doc} |")
    for st in (RAIL, LANE, GLINE, CS, DEVICE):
        out += ["", f"**`struct {st.cname}`** ({st.size} bytes; {st.doc})", "",
                "| Offset | Size | Type | Field | Meaning |", "|---|---|---|---|---|"]
        for off, size, ctype, name, doc in _doc_rows(st):
            out.append(f"| +{off} | {size} | `{ctype}` | `{name}` | {doc} |")
    enums = [("coupon_type", COUPON_TYPES), ("size_class", SIZE_CLASSES), ("select_scheme", SELECT_SCHEMES),
             ("lanes[].kind", LANE_KINDS), ("lanes[].unit", UNITS), ("glines[].role", GLINE_ROLES),
             ("cs[].role", CS_ROLES), ("devices[].bus", BUSES), ("devices[].irq", IRQS), ("devices[].part", PARTS),
             ("ext_format", EXT_FORMATS), ("ext site_map kinds", SITE_KINDS)]
    out += ["", "**Enumerations** (JSON name = value)", "", "| Field | Values |", "|---|---|"]
    for what, table in enums:
        vals = ", ".join(f"`{k}` = 0x{v:X}" if v > 9 else f"`{k}` = {v}"
                         for k, v in sorted(table.items(), key=lambda kv: kv[1]))
        out.append(f"| `{what}` | {vals} |")
    bits = [("flags", FLAGS), ("needs", NEEDS), ("uses", {n: i for i, n in enumerate(USES)}),
            ("lanes[].flags", LANE_FLAGS), ("glines[].flags", GLINE_FLAGS), ("cs[].flags", CS_FLAGS),
            ("devices[].flags", DEV_FLAGS), ("ext_flags", EXT_FLAG_BITS)]
    out += ["", "**Bit sets** (JSON name = bit)", "", "| Field | Bits |", "|---|---|"]
    for what, table in bits:
        vals = ", ".join(f"`{k}` = {v}" for k, v in sorted(table.items(), key=lambda kv: kv[1]))
        out.append(f"| `{what}` | {vals} |")
    out += ["", "<!-- end of generated tables -->"]
    return "\n".join(out)


DOC_BEGIN, DOC_END = "<!-- layout:begin -->", "<!-- layout:end -->"


def doc_is_current(path=DOC_PATH):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if DOC_BEGIN not in text or DOC_END not in text:
        return False
    inner = text.split(DOC_BEGIN, 1)[1].split(DOC_END, 1)[0]
    return inner.strip() == doc_tables().strip()


def write_doc_tables(path=DOC_PATH):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    head, rest = text.split(DOC_BEGIN, 1)
    _, tail = rest.split(DOC_END, 1)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(head + DOC_BEGIN + "\n" + doc_tables() + "\n" + DOC_END + tail)


# ------------------------------------------------------------------------------------------------------------ CLI
def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def dump_json(d):
    return json.dumps(d, indent=2) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("encode", help="JSON descriptor -> 256-byte image")
    e.add_argument("json")
    e.add_argument("-o", "--out")
    dc = sub.add_parser("decode", help="image -> canonical JSON")
    dc.add_argument("image")
    dc.add_argument("-o", "--out")
    dc.add_argument("--lenient", action="store_true", help="accept non-zero reserved bytes")
    h = sub.add_parser("header", help="write the C header")
    h.add_argument("-o", "--out", default=HEADER_PATH)
    h.add_argument("--check", action="store_true", help="exit 1 if the header on disk is stale")
    dg = sub.add_parser("doc", help="print, check or write the DESCRIPTOR.md tables")
    dg.add_argument("--check", metavar="MD", nargs="?", const=DOC_PATH)
    dg.add_argument("--write", metavar="MD", nargs="?", const=DOC_PATH)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "encode":
            d = load_json(a.json)
            if str(d.get("git", "")).lower() == "auto":
                raise DescriptorError("json", "git is 'auto': make_eeprom.py resolves it; give a hash here")
            img = encode(d)
            if a.out:
                with open(a.out, "wb") as fh:
                    fh.write(img)
                print(f"{a.out}: {len(img)} bytes, CRC 0x{struct.unpack_from('<I', img, CRC_OFFSET)[0]:08X}")
            else:
                sys.stdout.write(img.hex() + "\n")
        elif a.cmd == "decode":
            with open(a.image, "rb") as fh:
                d = decode(fh.read(), strict=not a.lenient)
            text = dump_json(d)
            if a.out:
                with open(a.out, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(text)
            else:
                sys.stdout.write(text)
        elif a.cmd == "header":
            text = c_header()
            if a.check:
                with open(a.out, encoding="utf-8") as fh:
                    if fh.read() != text:
                        print(f"{a.out} is stale: run `python descriptor.py header`")
                        return 1
                print(f"{a.out} is current")
                return 0
            with open(a.out, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
            print(f"wrote {a.out}")
        elif a.cmd == "doc":
            if a.write:
                write_doc_tables(a.write)
                print(f"updated the tables in {a.write}")
            elif a.check:
                ok = doc_is_current(a.check)
                print(f"{a.check}: tables {'current' if ok else 'STALE: run `python descriptor.py doc --write`'}")
                return 0 if ok else 1
            else:
                print(doc_tables())
    except DescriptorError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
