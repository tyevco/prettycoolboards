"""The descriptor format: frozen layout, round trips, every rejection, and agreement with nets.py and the docs."""

import json
import os
import struct
import zlib

import pytest

import descriptor as D
import nets

from coupon_fixtures import good_desc

COUPON = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESCS = sorted(os.path.join(COUPON, "descriptors", f) for f in os.listdir(os.path.join(COUPON, "descriptors")))

# Format 1.0, frozen: changing any of these is a format change (bump FORMAT_MAJOR, or FORMAT_MINOR for an
# addition in reserved space) and a firmware change.
FROZEN = {"magic": 0x00, "fmt_major": 0x04, "fmt_minor": 0x05, "length": 0x06, "coupon_type": 0x08,
          "coupon_rev": 0x09, "size_class": 0x0A, "default_slot": 0x0B, "slot_mask": 0x0C, "flags": 0x0D,
          "needs": 0x0E, "serial": 0x10, "date": 0x14, "git_hash": 0x18, "uses": 0x20, "spi_max_khz": 0x24,
          "i2c_max_khz": 0x26, "select_scheme": 0x28, "select_steps": 0x29, "select_settle_ns": 0x2A,
          "reserved0": 0x2C, "rails": 0x30, "lanes": 0x40, "glines": 0x80, "cs": 0x98, "devices": 0xA0,
          "ext_format": 0xD8, "ext_flags": 0xD9, "ext_reserved": 0xDA, "ext": 0xDC, "crc32": 0xFC}
FROZEN_SUB = {"coupon_desc_rail": (8, {"typ_ma": 0, "max_ma": 2, "bulk_uf_x10": 4, "startup_ms": 6}),
              "coupon_desc_lane": (16, {"kind": 0, "flags": 1, "sites": 2, "unit": 3, "r_src_ohm": 4,
                                        "cload_max_pf": 6, "offset": 8, "gain": 12}),
              "coupon_desc_gline": (4, {"role": 0, "arg": 1, "flags": 2}),
              "coupon_desc_cs": (4, {"role": 0, "device": 1, "flags": 2}),
              "coupon_desc_device": (8, {"part": 0, "bus": 2, "addr": 3, "count": 4, "irq": 5, "flags": 6,
                                         "spi_mode": 7})}
def test_layout_frozen():
    assert D.SIZE == 256 and D.LAYOUT.size == 256
    assert {f[0]: f[4] for f in D.LAYOUT.fields} == FROZEN
    for st in (D.RAIL, D.LANE, D.GLINE, D.CS, D.DEVICE):
        size, offs = FROZEN_SUB[st.cname]
        assert st.size == size
        got = {f[0]: f[4] for f in st.fields}
        for k, v in offs.items():
            assert got[k] == v, (st.cname, k)
    assert D.CRC_OFFSET == 0xFC == D.SIZE - 4


def test_crc_is_crc32_ieee():
    # the CRC-32/IEEE check value (the "123456789" test vector), which Zephyr's crc32_ieee() also gives
    assert D.crc32(b"123456789") == 0xCBF43926
    assert D.crc32(b"") == 0


def test_uses_order_matches_nets():
    want = ["+3V3", "+5V"] + [s for s in nets.SLOT_SIGNALS if s != "PRESENT_N"]
    assert D.USES == want, "USES is frozen for format 1; nets.SLOT_SIGNALS changed: a format change"


def test_slot_caps_match_nets():
    """SLOT_CAPS (what each slot offers) against nets.py: TIM8/TIM1 G-lines, 14-bit lanes, S5's rail, BKIN."""
    for n in nets.SLOTS:
        caps = D.SLOT_CAPS[n]["needs"]
        gl = [nets.SLOT_MCU[n].get(g) for g in ("G0", "G1", "G2", "G3")]
        pwm = all(p and "TIM" in nets.MCU_FUNC[p][0] for p in gl)
        assert ("pwm_g0_g3" in caps) == pwm, n
        tim1 = all(nets.SLOT_MCU[n].get(g) and "TIM1" in nets.MCU_FUNC[nets.SLOT_MCU[n][g]][0]
                   for g in ("G0", "G1", "G2", "G3", "G4", "G5"))
        assert ("tim1" in caps) == tim1, n
        fast45 = all(nets.SLOT_MCU[n].get(g) for g in ("G4", "G5"))
        assert ("fast_g4_g5" in caps) == fast45, n
        lanes14 = all(any(ch.startswith(("ADC1", "ADC2")) for ch in nets.LANE_ADC[nets.SLOT_MCU[n][a]])
                      for a in ("AN0", "AN1", "AN2", "AN3"))
        assert ("lanes_14bit" in caps) == lanes14, n
        rule5 = next(r[2] for r in nets.INA226_RAILS.values() if r[0] == f"+5V_S{n}")
        assert ("high_current_5v" in caps) == (rule5 > 0.5), n
        bkin = "BKIN" in nets.MCU_FUNC[nets.SLOT_MCU[n]["IRQ_N"]][0]
        assert ("bkin_on_irq" in caps) == bkin, n


def test_compatible_slots():
    assert D.compatible_slots("standard", []) == [1, 2, 3, 4, 5]
    assert D.compatible_slots("wide", []) == [4, 5]
    assert D.compatible_slots("standard", ["lanes_14bit"]) == [1, 2, 3, 4]
    assert D.compatible_slots("wide", ["tim1"]) == [5]
    assert D.compatible_slots("standard", ["pwm_g0_g3"]) == [4, 5]
    assert D.compatible_slots("wide", ["tim1", "lanes_14bit"]) == []
    assert D.compatible_slots("standard", ["exercises_current_limit"]) == [1, 2, 3, 4, 5]


def test_round_trip_fixture():
    d = good_desc()
    img = D.encode(d)
    assert len(img) == 256 and img[:4] == b"PCKC"
    k = D.decode(img)
    assert D.encode(k) == img                          # canonical -> the same bytes
    assert D.decode(D.encode(k)) == k                  # and back
    assert k["type"] == "hall" and k["slots"] == [1, 2, 3, 4, 5] and k["git"] == "0123456789abcdef"
    assert k["rails"]["+3V3"] == {"typ_ma": 10, "max_ma": 20, "bulk_uf": 10.2, "startup_ms": 1}
    assert k["lanes"]["AN0"]["gain"] == 100.0 and k["lanes"]["AN1"] == {"kind": "unused"}
    assert k["devices"][0] == {"part": "drv2605l", "bus": "i2c", "addr": "0x5A", "count": 1, "irq": "irq_n",
                               "flags": []}
    assert struct.unpack_from("<I", img, 0xFC)[0] == zlib.crc32(img[:0xFC])


def test_golden_bytes():
    """The fixture's image, byte for byte (checked by hand on 2026-11-27): a change here is a format change."""
    img = D.encode(good_desc())
    rows = {
        0x00: "50 43 4b 43 01 00 00 01 02 41 00 01 1f 00 00 00",   # PCKC 1.0 len 256, hall 'A' std S1 mask 1F
        0x10: "00 00 00 00 07 29 35 01 01 23 45 67 89 ab cd ef",   # serial 0, 20261127, git
        0x20: "07 e0 00 00 00 00 90 01 00 00 00 00 00 00 00 00",   # uses 0xE007, i2c 400 kHz
        0x30: "0a 00 14 00 66 00 01 00 05 00 1e 00 0a 00 00 00",   # +3V3 10/20 mA 10.2 uF 1 ms; +5V 5/30 mA 1 uF
        0x40: "01 09 01 01 0a 00 00 00 00 00 00 3f 00 00 c8 42",   # AN0 hall, ratiometric|bipolar, 10 ohm, 0.5, 100
        0xA0: "32 00 01 5a 01 01 00 00 10 00 03 01 01 00 00 00",   # DRV2605L i2c 0x5A irq_n; TMAG5253 analog AN0
    }
    for off, hexs in rows.items():
        assert img[off:off + 16].hex(" ") == hexs, hex(off)
    assert struct.unpack_from("<I", img, 0xFC)[0] == 0x298F4872


@pytest.mark.parametrize("path", DESCS, ids=os.path.basename)
def test_every_descriptor_round_trips(path):
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    assert d.get("board") == os.path.basename(path)[:-5]
    d["git"] = "ce1596470d81eff9"
    img = D.encode(d)
    k = D.decode(img)
    assert D.encode(k) == img
    assert ("placeholder" in k["flags"]) == bool(d.get("placeholder"))


def test_float32_rounding_is_canonical():
    d = good_desc()
    d["lanes"]["AN0"]["gain"] = 0.1                    # not exact in binary32
    k = D.canonical(d)
    assert k["lanes"]["AN0"]["gain"] == struct.unpack("<f", struct.pack("<f", 0.1))[0]
    assert D.canonical(k) == k


def test_site_map_packing():
    d = good_desc()
    d["ext"] = {"format": "site_map", "sites": [["key", "aftertouch", "reference", "thermistor"],
                                                ["empty", "key", "empty", "other"]]}
    img = D.encode(d)
    ext = img[0xDC:0xDC + 32]
    assert ext[0] == 0x21 and ext[1] == 0x43 and ext[2] == 0x10 and ext[3] == 0x50 and not any(ext[4:])
    assert D.decode(img)["ext"]["sites"] == d["ext"]["sites"]


def _corrupt(img, off, val):
    b = bytearray(img)
    b[off] = val
    return bytes(b)


def _recrc(img):
    b = bytearray(img)
    struct.pack_into("<I", b, 0xFC, zlib.crc32(bytes(b[:0xFC])))
    return bytes(b)


def test_crc_corruption_is_caught():
    img = D.encode(good_desc())
    for off in (0x10, 0x30, 0x47, 0xA0, 0xFB, 0xFC, 0xFF):
        with pytest.raises(D.DescriptorError) as e:
            D.decode(_corrupt(img, off, img[off] ^ 0x01))
        assert e.value.kind == "crc", off


def test_rejections():
    img = D.encode(good_desc())
    cases = [(b"\xff" * 256, "blank"), (img[:200], "size"), (b"XXXX" + img[4:], "magic"),
             (_corrupt(img, 4, 2), "version"), (_recrc(_corrupt(img, 6, 0x80)), "length"),
             (_recrc(_corrupt(img, 0x2C, 1)), "reserved"), (_recrc(_corrupt(img, 0x08, 0x77)), "field")]
    for raw, kind in cases:
        with pytest.raises(D.DescriptorError) as e:
            D.decode(raw)
        assert e.value.kind == kind, (kind, e.value)
    # a newer minor version may use reserved bytes: accepted
    newer = _recrc(_corrupt(_corrupt(img, 5, 1), 0x2C, 1))
    assert D.decode(newer)["format"] == "1.1"


def test_json_rejections_list_every_problem():
    d = good_desc()
    d.update({"type": "toaster", "rev": "a1", "sizee": 1, "serial": -1})
    d["rails"]["+3V3"]["max_ma"] = 70000
    d["lanes"]["AN0"]["kind"] = "laser"
    d["devices"].append({"part": "drv2605l", "bus": "i2c", "addr": "0x05"})
    with pytest.raises(D.DescriptorError) as e:
        D.encode(d)
    msg = str(e.value)
    for frag in ("type", "rev", "sizee", "serial", "max_ma", "laser", "0x05"):
        assert frag in msg, frag


def test_json_slot_checks():
    d = good_desc()
    d.update({"size": "wide", "default_slot": 4, "slots": [1, 4]})
    with pytest.raises(D.DescriptorError, match=r"slots \[1\] cannot take a wide coupon"):
        D.encode(d)
    d = good_desc()
    d.update({"size": "wide", "default_slot": 1})       # slots default to the compatible ones, [4, 5]
    with pytest.raises(D.DescriptorError, match=r"default_slot 1 is not in slots \[4, 5\]"):
        D.encode(d)
    d = good_desc()
    d.update({"slots": [2, 3], "default_slot": 1})
    with pytest.raises(D.DescriptorError, match="default_slot 1 is not in slots"):
        D.encode(d)
    d = good_desc()
    d.update({"needs": ["tim1"], "default_slot": 5, "slots": None})
    assert D.canonical(d)["slots"] == [5]              # a standard coupon fits the wide S5 (SPEC §2)
    d = good_desc()
    d.update({"needs": ["tim1", "lanes_14bit"], "default_slot": 5, "slots": [5]})
    with pytest.raises(D.DescriptorError, match="cannot take"):
        D.encode(d)
    d = good_desc()
    d.update({"size": "wide", "needs": ["tim1"], "default_slot": 5})
    assert D.canonical(d)["slots"] == [5]


def test_header_is_current():
    with open(D.HEADER_PATH, encoding="utf-8") as fh:
        assert fh.read() == D.c_header(), "coupon_desc.h is stale: run `python descriptor.py header`"


def test_doc_tables_are_current():
    assert D.doc_is_current(), "DESCRIPTOR.md tables are stale: run `python descriptor.py doc --write`"


def test_cli_encode_decode(tmp_path):
    src = tmp_path / "d.json"
    src.write_text(json.dumps(good_desc()))
    out = tmp_path / "d.bin"
    assert D.main(["encode", str(src), "-o", str(out)]) == 0
    back = tmp_path / "back.json"
    assert D.main(["decode", str(out), "-o", str(back)]) == 0
    assert json.loads(back.read_text()) == D.canonical(good_desc())
    bad = tmp_path / "bad.bin"
    bad.write_bytes(_corrupt(out.read_bytes(), 0x40, 0x55))
    assert D.main(["decode", str(bad)]) == 1


def test_newer_minor_may_use_new_enum_values():
    """DESCRIPTOR.md: a reader accepts a newer minor and ignores what it does not know, a new part ID included; a
    same-minor image with an undefined value is still refused."""
    img = bytearray(D.encode(good_desc()))
    struct.pack_into("<H", img, D.LAYOUT.offset("devices"), 0x0035)          # a part a 1.1 might add
    for minor, ok in ((1, True), (0, False)):
        img[5] = minor
        struct.pack_into("<I", img, D.CRC_OFFSET, D.crc32(bytes(img[:D.CRC_OFFSET])))
        if ok:
            assert D.decode(bytes(img))["devices"][0]["part"] == "unknown(53)"
        else:
            with pytest.raises(D.DescriptorError) as e:
                D.decode(bytes(img))
            assert e.value.kind == "field"


def test_firmware_lib_format_is_named():
    """keyboard/firmware/lib's tb/desc.h writes magic PCKD: refused, and said so, rather than called foreign."""
    with pytest.raises(D.DescriptorError) as e:
        D.check_image(b"PCKD" + bytes(252))
    assert e.value.kind == "magic" and "firmware/lib" in str(e.value)
