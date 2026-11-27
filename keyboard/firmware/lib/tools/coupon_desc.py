#!/usr/bin/env python3
"""Reference encoder and decoder for the coupon descriptor, format 1.0 (a PROPOSAL; see ../include/tb/desc.h).

SPEC §4.6 leaves the descriptor format to compiler v0 (§11 #18). This is the bring-up firmware's draft, kept in
step with the C parser in ../src/desc.c: the lib's tests decode what this script encodes (--c-vectors), and
test_coupon_desc.py checks the round trip here. Compiler v0 can take this over or replace it.

    python3 coupon_desc.py test --serial 7 --out test_coupon.bin   # the test coupon's descriptor
    python3 coupon_desc.py decode test_coupon.bin                   # print a descriptor as JSON
    python3 coupon_desc.py --c-vectors vectors.h                    # C test vectors for keyboard/firmware/lib/tests

The test coupon's descriptor follows keyboard/hardware/design/sheets/test_coupon.py (its DESCRIPTOR_FACTS and
docstring): the lane ladder, the four loads and their G-lines, the LED, the IRQ_N test line. The declared
currents are this script's reading of that design: +3V3 120 mA (about 1.4 mA idle, 1.5 mA LED and the G0 load's
110-113 mA, rounded up), +5V 170 mA (the G2 load's 167 mA); the current-limit loads G1 and G3 exceed them on purpose
and the self-test checks the budget for their peak separately.
"""
import argparse
import json
import struct
import sys

MAGIC = b"PCKD"
MAJOR, MINOR = 1, 0
HEADER = 24
MAX_LEN = 256

TYPES = {"none": 0, "test": 1, "hall": 2, "tmr": 3, "shear": 4, "coil": 5, "haptics": 6, "kvm": 7}
GROLES = {"unused": 0, "select": 1, "select_en": 2, "enable": 3, "addr": 4, "load": 5, "led": 6, "irq_test": 7,
          "pwm": 8, "reset": 9, "cs": 10}
I2C_KINDS = {"other": 0, "eeprom": 1, "ldc1614": 2, "drv2605l": 3, "expander": 4, "touch": 5}
F_WIDE, F_SENSORS = 1, 2
LANE_USED, LANE_RATIOMETRIC, LANE_BUFFERED = 1, 2, 4
REC = {"pad": 0, "name": 1, "lane": 2, "gline": 3, "i2c": 4, "spi": 5, "slots": 6, "load": 7, "cal": 8}


def crc16_ccitt(data: bytes) -> int:
    """CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF, no reflection, no final XOR (check '123456789' = 0x29B1)."""
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def q16(x: float) -> int:
    return min(0xFFFF, max(0, round(x * 65536)))


def encode(d: dict) -> bytes:
    """d: type, rev, flags, serial, i3v3_ma, i5v_ma, c3v3_uf, c5v_uf, name, lanes {k: {...}}, glines {k: (role,
    arg)}, i2c [(addr, kind)], spi [(cs, mode, hz)], slots (mask or None), loads {k: {...}}, cal [(key, value)]."""
    recs = bytearray()

    def rec(kind, payload):
        recs.extend(bytes([REC[kind], len(payload)]) + payload)

    if d.get("name"):
        name = d["name"].encode("ascii")
        if not 1 <= len(name) <= 32 or any(c < 0x20 or c > 0x7E for c in name):
            raise ValueError("name: 1-32 printable ASCII characters")
        rec("name", name)
    for k in sorted(d.get("lanes", {})):
        ln = d["lanes"][k]
        rec("lane", struct.pack("<BBHHHH", k, ln["flags"], ln["r_src_ohm"], ln.get("cload_pf", 0),
                                q16(ln["expect"]) if ln.get("expect") else 0, q16(ln.get("tol", 0))))
    for k in sorted(d.get("glines", {})):
        role, arg = d["glines"][k]
        rec("gline", bytes([k, GROLES[role], arg]))
    for addr, kind in d.get("i2c", []):
        rec("i2c", bytes([addr, I2C_KINDS[kind]]))
    for cs, mode, hz in d.get("spi", []):
        rec("spi", struct.pack("<BBI", cs, mode, hz))
    if d.get("slots") is not None:
        rec("slots", bytes([d["slots"]]))
    for k in sorted(d.get("loads", {})):
        ld = d["loads"][k]
        rec("load", struct.pack("<BBBBHB", k, ld["gline"], ld["rail"], ld["kind"], ld["r_mohm"],
                                ld.get("slots", 0)))
    for key, value in d.get("cal", []):
        rec("cal", struct.pack("<Hi", key, value))
    length = HEADER + len(recs) + 2
    if length > MAX_LEN:
        raise ValueError(f"descriptor is {length} bytes, more than the M24C02's {MAX_LEN}")
    rev = d.get("rev", "A")
    if len(rev) != 1 or not "A" <= rev <= "Z":
        raise ValueError("rev: one capital letter")
    head = MAGIC + struct.pack("<BBHBBHIHHHH", MAJOR, MINOR, length, TYPES[d["type"]], ord(rev),
                               d.get("flags", 0), d.get("serial", 0), d["i3v3_ma"], d["i5v_ma"],
                               d.get("c3v3_uf", 0), d.get("c5v_uf", 0))
    body = head + bytes(recs)
    return body + struct.pack("<H", crc16_ccitt(body))


def decode(buf: bytes) -> dict:
    """The inverse of encode(), with the C parser's checks. Raises ValueError with the C error token."""
    if len(buf) < 8:
        raise ValueError("short")
    if buf[:8] == b"\xff" * 8:
        raise ValueError("blank")
    if buf[:4] != MAGIC:
        raise ValueError("magic")
    if buf[4] != MAJOR:
        raise ValueError("version")
    length = struct.unpack_from("<H", buf, 6)[0]
    if not HEADER + 2 <= length <= MAX_LEN:
        raise ValueError("length")
    if length > len(buf):
        raise ValueError("short")
    if crc16_ccitt(buf[:length - 2]) != struct.unpack_from("<H", buf, length - 2)[0]:
        raise ValueError("crc")
    (_maj, minor, _l, typ, rev, flags, serial, i3, i5, c3, c5) = struct.unpack_from("<BBHBBHIHHHH", buf, 4)
    if not ord("A") <= rev <= ord("Z"):
        raise ValueError("value")
    out = {"major": MAJOR, "minor": minor, "length": length,
           "type": next((k for k, v in TYPES.items() if v == typ), "unknown"), "rev": chr(rev), "flags": flags,
           "serial": serial, "i3v3_ma": i3, "i5v_ma": i5, "c3v3_uf": c3, "c5v_uf": c5, "name": "", "lanes": {},
           "glines": {}, "i2c": [], "spi": [], "slots": 0x1F, "loads": {}, "cal": [], "unknown": 0}
    pos = HEADER
    end = length - 2
    while pos < end:
        if pos + 2 > end:
            raise ValueError("record")
        kind, rlen = buf[pos], buf[pos + 1]
        v = buf[pos + 2:pos + 2 + rlen]
        if pos + 2 + rlen > end:
            raise ValueError("record")
        if kind == REC["name"]:
            if not 1 <= rlen <= 32:
                raise ValueError("record")
            if out["name"]:
                raise ValueError("duplicate")
            if any(c < 0x20 or c > 0x7E for c in v):
                raise ValueError("value")
            out["name"] = v.decode("ascii")
        elif kind == REC["lane"]:
            if rlen != 10:
                raise ValueError("record")
            k, fl, rs, cl, ex, tol = struct.unpack("<BBHHHH", v)
            if k > 3:
                raise ValueError("value")
            if k in out["lanes"]:
                raise ValueError("duplicate")
            out["lanes"][k] = {"flags": fl, "r_src_ohm": rs, "cload_pf": cl, "expect_q16": ex, "tol_q16": tol}
        elif kind == REC["gline"]:
            if rlen != 3:
                raise ValueError("record")
            if v[0] > 5:
                raise ValueError("value")
            if v[0] in out["glines"]:
                raise ValueError("duplicate")
            out["glines"][v[0]] = (next((k for k, r in GROLES.items() if r == v[1]), v[1]), v[2])
        elif kind == REC["i2c"]:
            if rlen != 2:
                raise ValueError("record")
            if not 0x08 <= v[0] <= 0x77:
                raise ValueError("value")
            out["i2c"].append((v[0], v[1]))
        elif kind == REC["spi"]:
            if rlen != 6:
                raise ValueError("record")
            cs, mode, hz = struct.unpack("<BBI", v)
            if cs > 1 or mode > 3:
                raise ValueError("value")
            out["spi"].append((cs, mode, hz))
        elif kind == REC["slots"]:
            if rlen != 1:
                raise ValueError("record")
            if v[0] == 0 or v[0] & ~0x1F:
                raise ValueError("value")
            out["slots"] = v[0]
        elif kind == REC["load"]:
            if rlen != 7:
                raise ValueError("record")
            k, g, rail, lk, r, sl = struct.unpack("<BBBBHB", v)
            if k > 3 or g > 5 or rail > 1 or lk > 1 or r == 0 or sl & ~0x1F:
                raise ValueError("value")
            if k in out["loads"]:
                raise ValueError("duplicate")
            out["loads"][k] = {"gline": g, "rail": rail, "kind": lk, "r_mohm": r, "slots": sl or 0x1F}
        elif kind == REC["cal"]:
            if rlen != 6:
                raise ValueError("record")
            out["cal"].append(struct.unpack("<Hi", v))
        elif kind != REC["pad"]:
            out["unknown"] += 1
        pos += 2 + rlen
    return out


# The test coupon (keyboard/hardware/design/sheets/test_coupon.py). Lane ratios and R_src are DESCRIPTOR_FACTS'.
TEST_LANES = {0: (0.2, 399), 1: (0.4, 599), 2: (0.6, 599), 3: (0.8, 399)}   # 5 x 499 ohm ladder
TEST_LANE_TOL = 0.01          # 1 % of the reference: the 0.1 % ladder, the ADC, the drop under load (estimate)
TEST_SPI_HZ = 1_000_000       # a conservative bring-up clock; the SN74LV165A's f_max is not read here


def test_coupon(serial=0):
    return {
        "type": "test", "rev": "A", "flags": 0, "serial": serial, "i3v3_ma": 120, "i5v_ma": 170,
        "c3v3_uf": 10, "c5v_uf": 22, "name": "test coupon A",
        "lanes": {k: {"flags": LANE_USED | LANE_RATIOMETRIC, "r_src_ohm": r, "cload_pf": 0, "expect": x,
                      "tol": TEST_LANE_TOL} for k, (x, r) in TEST_LANES.items()},
        "glines": {0: ("load", 0), 1: ("load", 1), 2: ("load", 2), 3: ("load", 3), 4: ("led", 0),
                   5: ("irq_test", 0)},
        "i2c": [(0x50, "eeprom")],
        "spi": [(0, 3, TEST_SPI_HZ)],   # mode 3, the sheet's preference (mode 0 also reads)
        "loads": {0: {"gline": 0, "rail": 0, "kind": 0, "r_mohm": 30000},
                  1: {"gline": 1, "rail": 0, "kind": 1, "r_mohm": 5000},
                  2: {"gline": 2, "rail": 1, "kind": 0, "r_mohm": 30000},
                  3: {"gline": 3, "rail": 1, "kind": 1, "r_mohm": 3333, "slots": 0x0F}},   # never on S5
    }


def c_vectors():
    """A C header of test vectors for keyboard/firmware/lib/tests (generated at build time)."""
    good = encode(test_coupon(serial=0x12345678))
    minimal = encode({"type": "hall", "rev": "B", "i3v3_ma": 160, "i5v_ma": 0, "flags": F_SENSORS})
    unknown = bytearray(encode({"type": "coil", "rev": "A", "i3v3_ma": 50, "i5v_ma": 0, "flags": F_WIDE,
                                "slots": 0x18}))
    # splice an unknown record type (0x7E) before the CRC and fix length and CRC: a newer minor's field
    body = bytes(unknown[:-2]) + bytes([0x7E, 3, 1, 2, 3])
    body = body[:6] + struct.pack("<H", len(body) + 2) + body[8:]
    unknown = body + struct.pack("<H", crc16_ccitt(body))
    lines = ["/* GENERATED at build time by keyboard/firmware/lib/tools/coupon_desc.py --c-vectors. */",
             "#ifndef TB_DESC_VECTORS_H_", "#define TB_DESC_VECTORS_H_", "#include <stdint.h>", ""]
    for name, blob in (("test_coupon", good), ("minimal_hall", minimal), ("unknown_record", unknown)):
        lines.append(f"static const uint8_t vec_{name}[{len(blob)}] = {{")
        for i in range(0, len(blob), 16):
            lines.append("\t" + ", ".join(f"0x{b:02x}" for b in blob[i:i + 16]) + ",")
        lines.append("};")
    lines += ["", "#endif", ""]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--c-vectors", metavar="OUT", help="write C test vectors to OUT and exit")
    sub = ap.add_subparsers(dest="cmd")
    t = sub.add_parser("test", help="encode the test coupon's descriptor")
    t.add_argument("--serial", type=lambda s: int(s, 0), default=0)
    t.add_argument("--out", help="write the bytes here (default: hex on stdout)")
    dec = sub.add_parser("decode", help="decode a descriptor file")
    dec.add_argument("file")
    args = ap.parse_args(argv)
    if args.c_vectors:
        with open(args.c_vectors, "w", encoding="utf-8", newline="\n") as f:
            f.write(c_vectors())
        return 0
    if args.cmd == "test":
        blob = encode(test_coupon(args.serial))
        if args.out:
            with open(args.out, "wb") as f:
                f.write(blob)
        else:
            print(blob.hex())
        return 0
    if args.cmd == "decode":
        with open(args.file, "rb") as f:
            print(json.dumps(decode(f.read()), indent=2, default=str))
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
