"""coupon_desc.h, the firmware's view of the descriptor: compiled on the host with gcc against Zephyr v4.5.0's own
subsys/crc/crc32_sw.c, run on images made by Python (good, corrupted, blank, foreign), and compared field by field
with descriptor.py; and compiled for Cortex-M33 (the STM32U5A5) so its static asserts hold on the target ABI."""

import os
import shutil
import struct
import subprocess

import pytest

import descriptor as D
from coupon_fixtures import good_desc

HERE = os.path.dirname(os.path.abspath(__file__))
COUPON = os.path.dirname(HERE)
ZEPHYR = os.environ.get("ZEPHYR_BASE", "/root/zephyrproject/zephyr")
CRC_SRC = os.path.join(ZEPHYR, "subsys", "crc", "crc32_sw.c")

needs_gcc = pytest.mark.skipif(not shutil.which("gcc") or not os.path.exists(CRC_SRC),
                               reason="host gcc or Zephyr's subsys/crc/crc32_sw.c not available")


@pytest.fixture(scope="module")
def desc_dump(tmp_path_factory):
    out = str(tmp_path_factory.mktemp("c") / "desc_dump")
    subprocess.run(["gcc", "-std=c11", "-Wall", "-Wextra", "-Wpedantic", "-Werror", "-I", COUPON,
                    "-I", os.path.join(HERE, "c", "shim"), os.path.join(HERE, "c", "desc_dump.c"), CRC_SRC,
                    "-o", out], check=True)
    return out


def dump(exe, img, tmp_path):
    p = tmp_path / "img.bin"
    p.write_bytes(img)
    out = subprocess.run([exe, str(p)], check=True, capture_output=True, text=True).stdout
    return dict(ln.split("=", 1) for ln in out.splitlines())


STATUS = {"size": -1, "blank": -2, "magic": -3, "version": -4, "length": -5, "crc": -6}


def _images():
    good = D.encode(good_desc())
    with open(os.path.join(COUPON, "descriptors", "test-coupon.json"), encoding="utf-8") as fh:
        import json
        tc = json.load(fh)
    tc["git"] = "ce1596470d81eff9"
    bad_crc = bytearray(good)
    bad_crc[0x41] ^= 0x10
    v2 = bytearray(good)
    v2[4] = 2
    ln = bytearray(good)
    ln[6] = 0x80
    struct.pack_into("<I", ln, 0xFC, D.crc32(bytes(ln[:0xFC])))
    return {"good": (good, 0), "test-coupon": (D.encode(tc), 0), "crc": (bytes(bad_crc), -6),
            "blank": (b"\xff" * 256, -2), "magic": (b"\0" * 256, -3), "version": (bytes(v2), -4),
            "length": (bytes(ln), -5), "size": (good[:100], -1)}


@needs_gcc
@pytest.mark.parametrize("name", list(_images()))
def test_c_reader_agrees_with_python(desc_dump, tmp_path, name):
    img, status = _images()[name]
    got = dump(desc_dump, img, tmp_path)
    assert int(got["status"]) == status
    try:
        D.check_image(img)
        assert status == 0
    except D.DescriptorError as e:
        assert STATUS[e.kind] == status
    if status:
        return
    f, _ = D._unflatten(D.LAYOUT, struct.unpack(D.STRUCT_FMT, img))
    assert got["fmt"] == f"{f['fmt_major']}.{f['fmt_minor']}" and int(got["length"]) == 256
    assert int(got["type"]) == f["coupon_type"] and got["rev"] == chr(f["coupon_rev"])
    assert int(got["slot_mask"], 16) == f["slot_mask"] and int(got["needs"], 16) == f["needs"]
    assert int(got["serial"]) == f["serial"] and int(got["date"]) == f["date"]
    assert int(got["uses"], 16) == f["uses"] and got["git"] == bytes(f["git_hash"]).hex()
    assert int(got["spi_max_khz"]) == f["spi_max_khz"] and int(got["i2c_max_khz"]) == f["i2c_max_khz"]
    for i, r in enumerate(f["rails"]):
        assert got[f"rail{i}"] == f"{r['typ_ma']},{r['max_ma']},{r['bulk_uf_x10']},{r['startup_ms']}"
    for i, x in enumerate(f["lanes"]):
        k, fl, s, u, rs, cl, off, gain = got[f"lane{i}"].split(",")
        assert [int(k), int(fl, 16), int(s), int(u), int(rs), int(cl)] == \
            [x["kind"], x["flags"], x["sites"], x["unit"], x["r_src_ohm"], x["cload_max_pf"]]
        assert float(off) == x["offset"] and float(gain) == x["gain"]
    for i, g in enumerate(f["glines"]):
        assert got[f"gline{i}"] == f"{g['role']},{g['arg']},0x{g['flags']:02X}"
    for i, dv in enumerate(f["devices"]):
        assert got[f"dev{i}"] == (f"0x{dv['part']:04X},{dv['bus']},0x{dv['addr']:02X},{dv['count']},{dv['irq']},"
                                  f"0x{dv['flags']:02X},{dv['spi_mode']}")
    assert got["ext"] == f"{f['ext_format']},0x{f['ext_flags']:02X},{bytes(f['ext']).hex()}"
    assert int(got["crc"], 16) == f["crc32"] == D.crc32(img[:0xFC])


@pytest.mark.skipif(not shutil.which("arm-none-eabi-gcc"), reason="arm-none-eabi-gcc not installed")
def test_header_compiles_for_cortex_m33(tmp_path):
    src = tmp_path / "t.c"
    src.write_text('#include "coupon_desc.h"\n'
                   "int check(const uint8_t *b) { return coupon_desc_validate(b, COUPON_DESC_SIZE); }\n"
                   "_Static_assert(sizeof(struct coupon_desc) == 256, \"size on the target\");\n")
    subprocess.run(["arm-none-eabi-gcc", "-mcpu=cortex-m33", "-mthumb", "-mfloat-abi=hard", "-mfpu=fpv5-sp-d16",
                    "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", COUPON, "-c", str(src), "-o",
                    str(tmp_path / "t.o")], check=True)


# ------------------------------------------------------------------------------- layout cross-check (byte for byte)
def _leaves(st, prefix=""):
    """Every leaf field of a Struct, in encoder order: (C member designator, [struct-module codes], size)."""
    for name, typ, count, _doc, _off, _size in st.fields:
        if isinstance(typ, D.Struct):
            for i in range(count):
                yield from _leaves(typ, f"{prefix}{name}[{i}]." if count > 1 else f"{prefix}{name}.")
        elif typ == "char":
            yield f"{prefix}{name}", [f"{count}s"], count
        else:
            code, size, _c = D._SCALAR[typ]
            for i in range(count):
                yield (f"{prefix}{name}[{i}]" if count > 1 else f"{prefix}{name}"), [code], size


def _python_positions():
    """(designator, offset, size) from struct.calcsize over the encoder's own format string: independent of the
    Struct class's offset arithmetic that the header's _Static_asserts are generated from."""
    out, codes = [], []
    for desig, cs, size in _leaves(D.LAYOUT):
        out.append((desig, struct.calcsize("<" + "".join(codes)), size))
        codes += cs
    assert "<" + "".join(codes) == D.STRUCT_FMT          # the leaves are exactly what encode() packs
    assert struct.calcsize(D.STRUCT_FMT) == D.SIZE
    return out


def _layout_c(target_rodata=False):
    pos = _python_positions()
    lines = ['#include "coupon_desc.h"', "#include <stdio.h>" if not target_rodata else "",
             "#define F(m) offsetof(struct coupon_desc, m), sizeof(((struct coupon_desc *)0)->m)"]
    vals = ", ".join(f"F({d})" for d, _o, _s in pos)
    if target_rodata:
        lines.append(f"__attribute__((section(\".coupon_layout\"), used)) const uint32_t coupon_layout[] = "
                     f"{{sizeof(struct coupon_desc), {vals}}};")
    else:
        lines += [f"static const unsigned long v[] = {{sizeof(struct coupon_desc), {vals}}};",
                  "int main(void) { for (unsigned i = 0; i < sizeof(v) / sizeof(v[0]); i++) "
                  "printf(\"%lu\\n\", v[i]); return 0; }"]
    return "\n".join(lines) + "\n", pos


def _compare(got, pos):
    assert got[0] == D.SIZE == 256, f"sizeof(struct coupon_desc) = {got[0]}"
    bad = []
    for i, (desig, off, size) in enumerate(pos):
        c_off, c_size = got[1 + 2 * i], got[2 + 2 * i]
        if (c_off, c_size) != (off, size):
            bad.append(f"{desig}: C offset {c_off} size {c_size}, encoder {off} size {size}")
    assert not bad, bad
    # every byte of the image belongs to exactly one leaf
    cover = sorted((off, size) for _d, off, size in pos)
    assert sum(s for _o, s in cover) == D.SIZE
    assert all(a[0] + a[1] == b[0] for a, b in zip(cover, cover[1:]))


@pytest.mark.skipif(not shutil.which("gcc"), reason="host gcc not installed")
def test_c_layout_equals_encoder_byte_for_byte(tmp_path):
    """sizeof and offsetof of all leaves (every array element and sub-struct member) of struct coupon_desc,
    compiled with the host gcc, equal the byte positions encode() writes them at."""
    src, pos = _layout_c()
    (tmp_path / "layout.c").write_text(src)
    exe = str(tmp_path / "layout")
    subprocess.run(["gcc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", COUPON, str(tmp_path / "layout.c"),
                    "-o", exe], check=True)
    got = [int(x) for x in subprocess.run([exe], check=True, capture_output=True, text=True).stdout.split()]
    assert len(got) == 1 + 2 * len(pos) and len(pos) >= 150
    _compare(got, pos)


@pytest.mark.skipif(not (shutil.which("arm-none-eabi-gcc") and shutil.which("arm-none-eabi-objcopy")),
                    reason="arm-none-eabi-gcc/objcopy not installed")
def test_c_layout_on_cortex_m33(tmp_path):
    """The same numbers as the target compiler computes them: compiled for Cortex-M33 (hard float, as the
    STM32U5A5 firmware), emitted as a const array into its own section and read back from the object file."""
    src, pos = _layout_c(target_rodata=True)
    (tmp_path / "layout.c").write_text(src)
    obj, raw = str(tmp_path / "layout.o"), str(tmp_path / "layout.bin")
    subprocess.run(["arm-none-eabi-gcc", "-mcpu=cortex-m33", "-mthumb", "-mfloat-abi=hard", "-mfpu=fpv5-sp-d16",
                    "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2", "-I", COUPON, "-c", str(tmp_path / "layout.c"),
                    "-o", obj], check=True)
    subprocess.run(["arm-none-eabi-objcopy", "-O", "binary", "-j", ".coupon_layout", obj, raw], check=True)
    data = open(raw, "rb").read()
    got = list(struct.unpack(f"<{len(data) // 4}I", data))
    assert len(got) == 1 + 2 * len(pos)
    _compare(got, pos)


def test_layout_check_catches_a_moved_field(tmp_path):
    """The comparison is not vacuous: a header whose gain and offset are swapped in coupon_desc_lane fails it."""
    if not shutil.which("gcc"):
        pytest.skip("host gcc not installed")
    hdr = open(os.path.join(COUPON, "coupon_desc.h"), encoding="utf-8").read()
    a = "\tfloat offset; /* 0x08"
    b = "\tfloat gain; /* 0x0C"
    i, j = hdr.index(a), hdr.index(b)
    la, lb = hdr[i:hdr.index("\n", i)], hdr[j:hdr.index("\n", j)]
    bad = hdr.replace(la, "@@A@@").replace(lb, la).replace("@@A@@", lb)
    bad = "\n".join(ln for ln in bad.splitlines() if "_Static_assert(offsetof(struct coupon_desc_lane" not in ln)
    (tmp_path / "coupon_desc.h").write_text(bad)
    src, pos = _layout_c()
    (tmp_path / "layout.c").write_text(src)
    exe = str(tmp_path / "layout")
    subprocess.run(["gcc", "-std=c11", "-I", str(tmp_path), str(tmp_path / "layout.c"), "-o", exe], check=True)
    got = [int(x) for x in subprocess.run([exe], check=True, capture_output=True, text=True).stdout.split()]
    with pytest.raises(AssertionError, match="lanes"):
        _compare(got, pos)
