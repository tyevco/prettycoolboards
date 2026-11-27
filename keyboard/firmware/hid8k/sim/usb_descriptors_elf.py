#!/usr/bin/env python3
"""Print the USB descriptors a hid8k build carries, read straight out of its ELF.

Zephyr's usbd_hid and usbd_cdc_acm build their descriptors at compile time from the devicetree
node (subsys/usb/device_next/class/usbd_hid_macros.h, usbd_cdc_acm.c) into initialised data:
`hid_desc_0` (struct usbd_hid_descriptor, usbd_hid.c:46-57 in v4.5.0), `cdc_acm_desc_0`, and
hid8k's own `report_desc` (src/hid8k.c). This tool finds those symbols in the ELF's symbol table,
reads their initial bytes from the section that holds them, and prints each descriptor, so two
builds can be compared byte for byte:

  usb_descriptors_elf.py build/zephyr/zephyr.elf
  usb_descriptors_elf.py --compare before/zephyr.elf after/zephyr.elf   # exit 1 if they differ

Either way it exits 1 if any of the three symbols is missing from a file: two files that both
lack a descriptor have nothing to compare, so that is never reported as "identical".

It reads 32- and 64-bit little-endian ELF files (the Cortex-M33 board build and the native_sim
simulation), with no dependency outside the standard library.

What it shows is the descriptor templates, before the stack runs: the stack assigns the endpoint
addresses (0x81 in the template) and fills the HID descriptor's report length (0 here) when it
initialises the class. What a host actually reads is what the simulation's enumeration step
prints.
"""

from __future__ import annotations

import argparse
import struct
import sys

SYMBOLS = ("hid_desc_0", "cdc_acm_desc_0", "report_desc")

# struct usbd_hid_descriptor (Zephyr v4.5.0, usbd_hid.c:46-57): the members in order.
HID_MEMBERS = ("if0", "hid", "in_ep (full speed)", "hs_in_ep (high speed)", "out_ep",
               "hs_out_ep", "if0_1 (alternate)", "alt_hs_in_ep", "alt_hs_out_ep")


class Elf:
    def __init__(self, path: str):
        with open(path, "rb") as f:
            self.data = f.read()
        d = self.data
        if d[:4] != b"\x7fELF":
            raise ValueError(f"{path}: not an ELF file")
        if d[5] != 1:
            raise ValueError(f"{path}: not little-endian")
        self.is64 = d[4] == 2
        if self.is64:
            (self.shoff,) = struct.unpack_from("<Q", d, 0x28)
            self.shentsize, self.shnum, self.shstrndx = struct.unpack_from("<HHH", d, 0x3A)
        else:
            (self.shoff,) = struct.unpack_from("<I", d, 0x20)
            self.shentsize, self.shnum, self.shstrndx = struct.unpack_from("<HHH", d, 0x2E)
        self.sections = [self._section(i) for i in range(self.shnum)]

    def _section(self, i: int) -> dict:
        off = self.shoff + i * self.shentsize
        if self.is64:
            name, typ, _flags, addr, offset, size, link, _info, _align, entsize = \
                struct.unpack_from("<IIQQQQIIQQ", self.data, off)
        else:
            name, typ, _flags, addr, offset, size, link, _info, _align, entsize = \
                struct.unpack_from("<IIIIIIIIII", self.data, off)
        return {"name": name, "type": typ, "addr": addr, "offset": offset, "size": size,
                "link": link, "entsize": entsize}

    def symbols(self):
        """Yield (name, value, size, section index) for every symbol in .symtab."""
        for sec in self.sections:
            if sec["type"] != 2:  # SHT_SYMTAB
                continue
            strtab = self.sections[sec["link"]]
            ent = 24 if self.is64 else 16
            for k in range(sec["size"] // ent):
                off = sec["offset"] + k * ent
                if self.is64:
                    name, _info, _other, shndx, value, size = \
                        struct.unpack_from("<IBBHQQ", self.data, off)
                else:
                    name, value, size, _info, _other, shndx = \
                        struct.unpack_from("<IIIBBH", self.data, off)
                start = strtab["offset"] + name
                end = self.data.index(b"\0", start)
                yield self.data[start:end].decode("ascii", "replace"), value, size, shndx

    def symbol_bytes(self, wanted: str) -> list:
        """The initial bytes of every symbol with this name (there may be more than one)."""
        out = []
        for name, value, size, shndx in self.symbols():
            if name != wanted or size == 0 or not 0 < shndx < len(self.sections):
                continue
            sec = self.sections[shndx]
            if sec["type"] == 8:  # SHT_NOBITS (.bss): no initial bytes
                continue
            start = sec["offset"] + (value - sec["addr"])
            out.append(self.data[start:start + size])
        return out


def describe(d: bytes) -> str:
    """One line for one standard descriptor."""
    if len(d) < 2:
        return "?"
    t = d[1]
    if t == 4 and len(d) >= 9:
        return (f"interface {d[2]} alt {d[3]}, {d[4]} endpoint(s), "
                f"class {d[5]:02x}/{d[6]:02x}/{d[7]:02x}")
    if t == 5 and len(d) >= 7:
        kind = ("control", "isochronous", "bulk", "interrupt")[d[3] & 3]
        return (f"endpoint 0x{d[2]:02x} {kind} {'IN' if d[2] & 0x80 else 'OUT'}, "
                f"wMaxPacketSize {d[4] | d[5] << 8}, bInterval {d[6]}")
    if t == 0x21 and len(d) >= 9:
        return (f"HID {d[3]:x}.{d[2]:02x}, {d[5]} descriptor(s), type 0x{d[6]:02x} "
                f"length {d[7] | d[8] << 8} (filled in at run time)")
    if t == 0x0B and len(d) >= 8:
        return (f"interface association: interfaces {d[2]}..{d[2] + d[3] - 1}, "
                f"function {d[4]:02x}/{d[5]:02x}/{d[6]:02x}")
    if t == 0x24:
        return f"CDC class-specific interface descriptor, subtype 0x{d[2]:02x}"
    if t == 0:
        return "(empty: unused)"
    return f"descriptor type 0x{t:02x}"


def hexs(b: bytes) -> str:
    return " ".join(f"{x:02x}" for x in b)


def chain(blob: bytes, labels=None) -> list:
    """Walk concatenated descriptors by bLength."""
    lines = []
    i = 0
    k = 0
    while i < len(blob):
        n = blob[i]
        if n < 2 or i + n > len(blob):
            rest = blob[i:]
            if not any(rest):
                names = f" ({', '.join(labels[k:])})" if labels and k < len(labels) else ""
                lines.append(f"  {len(rest)} zero bytes: members this configuration does not "
                             f"use{names}")
            else:
                lines.append(f"  {hexs(rest)}  (not a descriptor)")
            break
        d = blob[i:i + n]
        label = f"{labels[k]}: " if labels and k < len(labels) else ""
        lines.append(f"  {hexs(d):<26} {label}{describe(d)}")
        i += n
        k += 1
    return lines


def report(path: str, missing: list = None) -> list:
    """The descriptor lines for one ELF; the names of symbols not found go into missing."""
    elf = Elf(path)
    lines = [f"{path} ({'ELF64' if elf.is64 else 'ELF32'})"]
    for sym in SYMBOLS:
        blobs = elf.symbol_bytes(sym)
        if not blobs:
            lines.append(f"{sym}: not found")
            if missing is not None:
                missing.append(sym)
            continue
        for blob in blobs:
            lines.append(f"{sym} ({len(blob)} bytes):")
            if sym == "report_desc":
                for j in range(0, len(blob), 16):
                    lines.append("  " + hexs(blob[j:j + 16]))
            else:
                lines.extend(chain(blob, HID_MEMBERS if sym == "hid_desc_0" else None))
    return lines


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("elf", nargs="+", help="zephyr.elf (or zephyr.exe for native_sim)")
    p.add_argument("--compare", action="store_true",
                   help="two ELF files: print both and exit 1 if the descriptors differ "
                        "or either file lacks one")
    args = p.parse_args(argv)

    if args.compare:
        if len(args.elf) != 2:
            p.error("--compare takes exactly two ELF files")
        miss_a, miss_b = [], []
        a, b = report(args.elf[0], miss_a), report(args.elf[1], miss_b)
        print("\n".join(a))
        print()
        print("\n".join(b))
        print()
        # Two builds that both lack a descriptor are not "identical": nothing was compared
        # (a renamed symbol in a later Zephyr, the wrong ELF, a stripped file).
        if miss_a or miss_b:
            print(f"descriptors MISSING: {', '.join(miss_a) or 'none'} in {args.elf[0]}; "
                  f"{', '.join(miss_b) or 'none'} in {args.elf[1]}: nothing to compare")
            return 1
        same = a[1:] == b[1:]
        if same:
            print("descriptors identical")
            return 0
        for la, lb in zip(a[1:], b[1:]):
            if la != lb:
                print(f"- {la}\n+ {lb}")
        if len(a) != len(b):
            print(f"(different number of lines: {len(a)} and {len(b)})")
        print("descriptors DIFFER")
        return 1

    missing = []
    for path in args.elf:
        print("\n".join(report(path, missing)))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
