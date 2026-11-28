"""Host-side check of a coupon descriptor that the firmware dumped with "tb desc <n>" (desc_hex records).

Two formats are proposed for the same M24C02 image (SPEC §4.6, §11 #18, not settled on 2026-11-27):
  * "PCKD": the bring-up firmware's (keyboard/firmware/lib/include/tb/desc.h): a 24-byte header, TLV records,
    CRC-16/CCITT-FALSE. This is what the firmware reads and what "tb desc <n> write test" writes.
  * "PCKC": compiler v0's (keyboard/tools/coupon/descriptor.py, DESCRIPTOR.md): a fixed 256-byte layout, CRC-32.
    keyboard/tools/coupon/make_eeprom.py writes it. The bring-up firmware refuses it (status=magic).
The harness checks either: PCKD with its own reader (cross-checked with lib/tools/coupon_desc.py when that file is
present), PCKC with descriptor.py when present. A PCKC image dumped by the firmware is only its first 32 bytes
(src/descio.c reads more only for a PCKD length), so its CRC cannot be checked from a dump.

Whatever the EEPROM holds, the coupon also has a descriptor of record: compiler v0's JSON for that board
(keyboard/tools/coupon/descriptors/<board>.json). record() validates it through descriptor.py itself (JSON ->
encode -> check_image -> decode, every field and the CRC-32) and hands back the facts the bench compares the
coupon's EEPROM with (type, revision, rails, lanes): the descriptor the coupon should carry, checked by the tool
that defines it.
"""

from __future__ import annotations

import importlib.util
import pathlib
import struct
import sys
from dataclasses import dataclass, field

from . import limits as L

PCKD_MAGIC, PCKC_MAGIC = b"PCKD", b"PCKC"
PCKD_HEADER = 24
TYPES = {0: "none", 1: "test", 2: "hall", 3: "tmr", 4: "shear", 5: "coil", 6: "haptics", 7: "kvm"}
REC_LEN = {1: None, 2: 10, 3: 3, 4: 2, 5: 6, 6: 1, 7: 7, 8: 6}   # PCKD record type -> fixed length (NAME: 1-32)


class DescError(ValueError):
    def __init__(self, kind, msg):
        self.kind = kind
        super().__init__(f"{kind}: {msg}")


def crc16_ccitt(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def reassemble(hex_records):
    """[desc_hex Record] -> (bytes, [problem]). Offsets must run 0, 16, 32 ... without a gap."""
    out, problems = bytearray(), []
    for r in sorted(hex_records, key=lambda r: r.get("off", 0)):
        off, data = r.get("off"), str(r.get("data", ""))
        if off != len(out):
            problems.append(f"desc_hex off={off} where {len(out)} was expected")
        try:
            out += bytes.fromhex(data)
        except ValueError:
            problems.append(f"desc_hex off={off}: not hex")
    return bytes(out), problems


def parse_pckd(img):
    """The PCKD checks tb/desc.h's reader makes, and the fields the harness compares with the firmware's."""
    if len(img) < 8:
        raise DescError("short", f"{len(img)} bytes")
    if img[:8] == b"\xff" * 8:
        raise DescError("blank", "erased EEPROM")
    if img[:4] != PCKD_MAGIC:
        raise DescError("magic", f"magic {img[:4]!r}")
    if img[4] != 1:
        raise DescError("version", f"major {img[4]}")
    length = struct.unpack_from("<H", img, 6)[0]
    if not PCKD_HEADER + 2 <= length <= 256:
        raise DescError("length", f"length {length}")
    if length > len(img):
        raise DescError("short", f"length {length}, {len(img)} bytes read")
    want = struct.unpack_from("<H", img, length - 2)[0]
    got = crc16_ccitt(img[:length - 2])
    if want != got:
        raise DescError("crc", f"stored 0x{want:04x}, computed 0x{got:04x}")
    (_maj, minor, _l, typ, rev, flags, serial, i3, i5, c3, c5) = struct.unpack_from("<BBHBBHIHHHH", img, 4)
    if not ord("A") <= rev <= ord("Z"):
        raise DescError("value", f"revision byte 0x{rev:02x}")
    f = {"format": "PCKD", "major": 1, "minor": minor, "length": length, "type": TYPES.get(typ, f"type{typ}"),
         "rev": chr(rev), "flags": flags, "serial": serial, "i3v3_ma": i3, "i5v_ma": i5, "c3v3_uf": c3,
         "c5v_uf": c5, "lanes": {}, "glines": {}, "loads": {}, "name": "", "unknown": 0}
    pos, end = PCKD_HEADER, length - 2
    while pos < end:
        if pos + 2 > end:
            raise DescError("record", f"record header at {pos} runs past {end}")
        kind, rlen = img[pos], img[pos + 1]
        v = img[pos + 2:pos + 2 + rlen]
        if pos + 2 + rlen > end:
            raise DescError("record", f"record 0x{kind:02x} at {pos} runs past {end}")
        if kind in REC_LEN and REC_LEN[kind] is not None and rlen != REC_LEN[kind]:
            raise DescError("record", f"record 0x{kind:02x} length {rlen}")
        if kind == 1:
            if not 1 <= rlen <= 32 or any(c < 0x20 or c > 0x7E for c in v):
                raise DescError("value", "name")
            f["name"] = v.decode("ascii")
        elif kind == 2:
            k, fl, rs, cl, ex, tol = struct.unpack("<BBHHHH", v)
            if k > 3 or k in f["lanes"]:
                raise DescError("value" if k > 3 else "duplicate", f"lane {k}")
            f["lanes"][k] = {"flags": fl, "r_src_ohm": rs, "cload_pf": cl, "expect_ppm": q16_ppm(ex),
                             "tol_ppm": q16_ppm(tol)}
        elif kind == 3:                         # lib/src/desc.c TB_DESC_REC_GLINE: G0-G5, once each
            g, role, arg = v
            if g > 5:
                raise DescError("value", f"G-line {g}")
            if g in f["glines"]:
                raise DescError("duplicate", f"G-line {g}")
            if role:
                f["glines"][g] = {"role": role, "arg": arg}
        elif kind == 7:
            k, g, rail, lk, r, sl = struct.unpack("<BBBBHB", v)
            if k > 3 or g > 5 or rail > 1 or lk > 1 or r == 0 or k in f["loads"]:
                raise DescError("value", f"load {k}")
            f["loads"][k] = {"gline": g, "rail": "+5V" if rail else "+3V3", "kind": "climit" if lk else "cal",
                             "r_mohm": r, "slots": sl or 0x1F}
        elif kind not in REC_LEN and kind != 0:
            f["unknown"] += 1
        pos += 2 + rlen
    return f


def q16_ppm(q):
    """The firmware's tb_q16_to_ppm(): Q16 fraction -> ppm, rounded."""
    return (q * 1_000_000 + 32768) >> 16


def _load_tool(path, name):
    if not path.exists():
        return None
    sys.dont_write_bytecode = True          # never leave __pycache__ in another tool's directory
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:  # noqa: BLE001  (a broken tool must not stop the bench)
        return None
    return mod


@dataclass
class DescReport:
    format: str                    # "PCKD", "PCKC", "blank", "unknown", "none"
    valid: bool
    kind: str = ""                 # the failed check, as a token (crc, magic, ...)
    fields: dict = field(default_factory=dict)
    problems: list = field(default_factory=list)
    tools: list = field(default_factory=list)   # which host readers checked it

    def as_dict(self):
        return {"format": self.format, "valid": self.valid, "kind": self.kind, "fields": self.fields,
                "problems": self.problems, "tools": self.tools}


def check(img, pckd_tool=L.PCKD_TOOL, pckc_tool=L.PCKC_TOOL):
    """Identify and validate an image. Never raises: the report says what was found."""
    if not img:
        return DescReport("none", False, "empty", problems=["no desc_hex bytes"])
    if all(b == 0xFF for b in img):
        return DescReport("blank", False, "blank", problems=["every byte read is 0xFF: an unwritten EEPROM"])
    magic = bytes(img[:4])
    if magic == PCKD_MAGIC:
        rep = DescReport("PCKD", True, tools=["tbbench.desc_check"])
        try:
            rep.fields = parse_pckd(img)
        except DescError as e:
            return DescReport("PCKD", False, e.kind, problems=[str(e)], tools=rep.tools)
        tool = _load_tool(pathlib.Path(pckd_tool), "tbbench_ext_coupon_desc")
        if tool is not None:
            rep.tools.append("keyboard/firmware/lib/tools/coupon_desc.py")
            try:
                d = tool.decode(bytes(img))
            except ValueError as e:
                rep.valid, rep.kind = False, str(e)
                rep.problems.append(f"coupon_desc.py refuses an image this reader accepts: {e}")
            else:
                for k in ("type", "serial", "i3v3_ma", "i5v_ma", "length", "rev"):
                    if d.get(k) != rep.fields.get(k):
                        rep.valid, rep.kind = False, "host_disagree"
                        rep.problems.append(f"{k}: coupon_desc.py {d.get(k)!r}, this reader {rep.fields.get(k)!r}")
        return rep
    if magic == PCKC_MAGIC:
        rep = DescReport("PCKC", False, "magic", tools=[],
                         problems=["a PCKC (compiler v0, keyboard/tools/coupon/descriptor.py) image: the bring-up "
                                   "firmware reads only PCKD (SPEC §11 #18 has to pick one format)"])
        major, minor = img[4], img[5]
        length = struct.unpack_from("<H", img, 6)[0] if len(img) >= 8 else None
        rep.fields = {"format": "PCKC", "major": major, "minor": minor, "length": length}
        tool = _load_tool(pathlib.Path(pckc_tool), "tbbench_ext_descriptor")
        if tool is None:
            rep.problems.append("keyboard/tools/coupon/descriptor.py not found: the PCKC image was not checked")
            return rep
        rep.tools.append("keyboard/tools/coupon/descriptor.py")
        if len(img) < tool.SIZE:
            rep.kind = "partial"
            rep.problems.append(f"only {len(img)} of {tool.SIZE} bytes were dumped (the firmware stops after the "
                                "header of a format it does not read): the CRC-32 cannot be checked")
            return rep
        try:
            tool.check_image(bytes(img))
            d = tool.decode(bytes(img))
        except tool.DescriptorError as e:
            rep.kind = e.kind
            rep.problems.append(str(e))
            return rep
        rep.fields.update({"type": d.get("type"), "serial": d.get("serial"), "rev": d.get("rev"),
                           "i3v3_ma": d.get("rails", {}).get("+3V3", {}).get("max_ma"),
                           "i5v_ma": d.get("rails", {}).get("+5V", {}).get("max_ma")})
        rep.kind = "wrong_format"          # valid PCKC, but not what this firmware reads
        return rep
    return DescReport("unknown", False, "magic", problems=[f"unknown magic {magic!r}"])


@dataclass
class Record:
    """A coupon's descriptor of record, as descriptor.py reads it."""
    kind: str
    path: str
    valid: bool
    facts: dict = field(default_factory=dict)
    problems: list = field(default_factory=list)

    def as_dict(self):
        return {"kind": self.kind, "path": self.path, "valid": self.valid, "facts": self.facts,
                "problems": self.problems}


def record(kind, records=None, pckc_tool=L.PCKC_TOOL):
    """Validate compiler v0's descriptor of record for this coupon kind through descriptor.py; never raises."""
    path = (records or L.DESCRIPTOR_RECORDS).get(kind)
    if path is None:
        return Record(kind, "", False, problems=[f"no descriptor of record for a {kind!r} coupon"])
    path = pathlib.Path(path)
    rec = Record(kind, str(path), False)
    tool = _load_tool(pathlib.Path(pckc_tool), "tbbench_ext_descriptor_rec")
    if tool is None:
        rec.problems.append(f"{pckc_tool} not found or not importable")
        return rec
    if not path.exists():
        rec.problems.append(f"{path} not found")
        return rec
    try:
        d = tool.load_json(str(path))
        if d.get("git") == "auto":
            d["git"] = "0" * 40                 # make_eeprom.py fills it from git; a placeholder for the check
        img = tool.encode(d)
        tool.check_image(img)
        x = tool.decode(img)
    except Exception as e:  # noqa: BLE001  (descriptor.py's DescriptorError, or a JSON error)
        rec.problems.append(f"descriptor.py refuses it: {e}")
        return rec
    rails = x.get("rails", {})
    lanes = {}
    for name, ln in (x.get("lanes") or {}).items():
        if isinstance(ln, dict) and ln.get("kind", "unused") != "unused":
            lanes[name] = {"kind": ln.get("kind"), "unit": ln.get("unit"), "r_src_ohm": ln.get("r_src_ohm")}
    ext = x.get("ext") or {}
    rec.valid = True
    rec.facts = {"type": x.get("type"), "rev": x.get("rev"), "placeholder": bool(d.get("placeholder")),
                 "i3v3_ma": (rails.get("+3V3") or {}).get("max_ma"), "i5v_ma": (rails.get("+5V") or {}).get("max_ma"),
                 "lanes": lanes, "ratios": ext.get("ratio") if ext.get("format") == "reference_ratios" else None,
                 "bytes": len(img)}
    return rec
