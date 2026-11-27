"""Tests for the reference descriptor encoder (run: python3 -m pytest keyboard/firmware/lib/tools -q).

They prove the encoder's arithmetic and its agreement with the hardware design's test coupon; the C parser's
agreement with this encoder is tested in keyboard/firmware/lib/tests (it decodes the vectors from --c-vectors).
Nothing here touches hardware.
"""
import pathlib
import struct
import sys

import pytest

sys.dont_write_bytecode = True   # never leave __pycache__ in keyboard/hardware (another workflow owns it)
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import coupon_desc as cd  # noqa: E402

DESIGN = HERE.parents[2] / "hardware" / "design"


def test_crc_check_value():
    assert cd.crc16_ccitt(b"123456789") == 0x29B1


def test_test_coupon_round_trip():
    blob = cd.encode(cd.test_coupon(serial=42))
    assert len(blob) <= 256
    d = cd.decode(blob)
    assert d["type"] == "test" and d["serial"] == 42 and d["rev"] == "A"
    assert d["i3v3_ma"] == 120 and d["i5v_ma"] == 170
    assert [d["lanes"][k]["expect_q16"] for k in range(4)] == [13107, 26214, 39322, 52429]
    assert d["loads"][3]["slots"] == 0x0F           # the 5 V current-limit load is never used on S5
    assert d["glines"][5] == ("irq_test", 0)


def test_lanes_match_hardware_design():
    if not (DESIGN / "sheets" / "test_coupon.py").exists():
        pytest.skip("no test coupon sheet module")
    sys.path.insert(0, str(DESIGN))
    try:
        from sheets import test_coupon as tc   # noqa: PLC0415
    except Exception as e:                      # the design tree may be mid-change in another workflow
        pytest.skip(f"cannot import the test coupon sheet: {e}")
    facts = tc.DESCRIPTOR_FACTS["lanes"]
    assert {int(k[2]): v for k, v in facts.items()} == cd.TEST_LANES
    assert tc.DESCRIPTOR_FACTS["type"] == "test"


@pytest.mark.parametrize("mutate,err", [
    (lambda b: b[:7], "short"),
    (lambda b: b"\xff" * 64, "blank"),
    (lambda b: b"XCKD" + b[4:], "magic"),
    (lambda b: b[:4] + bytes([2]) + b[5:], "version"),
    (lambda b: b[:-1] + bytes([b[-1] ^ 1]), "crc"),
])
def test_decode_rejects(mutate, err):
    blob = cd.encode(cd.test_coupon())
    with pytest.raises(ValueError, match=err):
        cd.decode(bytes(mutate(blob)))


def test_unknown_record_is_skipped():
    blob = bytearray(cd.encode({"type": "coil", "rev": "A", "i3v3_ma": 50, "i5v_ma": 0}))
    body = bytes(blob[:-2]) + bytes([0x7E, 2, 9, 9])
    body = body[:6] + struct.pack("<H", len(body) + 2) + body[8:]
    d = cd.decode(body + struct.pack("<H", cd.crc16_ccitt(body)))
    assert d["unknown"] == 1


def test_too_long_is_refused():
    d = cd.test_coupon()
    d["cal"] = [(k, k) for k in range(40)]
    with pytest.raises(ValueError, match="256"):
        cd.encode(d)


def test_c_vectors_render():
    text = cd.c_vectors()
    assert "vec_test_coupon" in text and "vec_unknown_record" in text
