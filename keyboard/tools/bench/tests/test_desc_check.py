"""The host's descriptor check: PCKD (the firmware's format) and PCKC (compiler v0's), from tb desc dumps."""

import importlib.util

import pytest

from tbbench import desc_check
from tbbench import limits as L
from tbbench import simdev
from tbbench.protocol import parse_line

# The first two dump lines the firmware on native_sim printed for the test coupon (serial 1), 2026-11-27.
NATIVE_DUMP_HEAD = ("50434b440100a7000141000001000000", "7800aa000a001600010d746573742063")


def lib_tool():
    if not L.PCKD_TOOL.exists():
        pytest.skip("no keyboard/firmware/lib/tools/coupon_desc.py")
    spec = importlib.util.spec_from_file_location("cd_ext2", L.PCKD_TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_sim_image_is_the_firmware_libs():
    mod = lib_tool()
    for serial in (0, 1, 42, 0x12345678):
        assert simdev.pckd_test_coupon(serial) == mod.encode(mod.test_coupon(serial))
    img = simdev.pckd_test_coupon(1)
    assert img[:16].hex() == NATIVE_DUMP_HEAD[0] and img[16:32].hex() == NATIVE_DUMP_HEAD[1]


def test_valid_pckd():
    rep = desc_check.check(simdev.pckd_test_coupon(7))
    assert rep.valid and rep.format == "PCKD"
    f = rep.fields
    assert (f["type"], f["serial"], f["i3v3_ma"], f["i5v_ma"], f["length"]) == ("test", 7, 120, 170, 167)
    assert [f["lanes"][k]["expect_ppm"] for k in range(4)] == [199997, 399994, 600006, 800003], \
        "the firmware's tb_q16_to_ppm values (native_sim transcript)"
    assert f["lanes"][0]["tol_ppm"] == 9995
    assert f["loads"][3] == {"gline": 3, "rail": "+5V", "kind": "climit", "r_mohm": 3333, "slots": 0x0F}


@pytest.mark.parametrize("how,kind", [("crc", "crc"), ("blank", "blank"), ("magic", "magic"),
                                      ("version", "version")])
def test_damaged_images(how, kind):
    rep = desc_check.check(simdev.corrupt(simdev.pckd_test_coupon(1), how))
    assert not rep.valid and rep.kind == kind


def test_over_rule_image_is_valid_bytes():
    """A descriptor that breaks a coupon rule is still a valid image: the procedure judges the rule."""
    rep = desc_check.check(simdev.corrupt(simdev.pckd_test_coupon(1), "over_rule"))
    assert rep.valid and rep.fields["i3v3_ma"] == 300


def test_record_overrun():
    img = bytearray(simdev.pckd_test_coupon(1))
    img[25] = 200                                   # the name record's length runs past the end
    body = bytes(img[:-2])
    img[-2:] = desc_check.crc16_ccitt(body).to_bytes(2, "little")
    rep = desc_check.check(bytes(img))
    assert not rep.valid and rep.kind == "record"


def test_reassemble():
    recs = [parse_line(f"@tb desc_hex slot=1 off={o} data={d}") for o, d in ((16, "bb" * 16), (0, "aa" * 16))]
    img, problems = desc_check.reassemble(recs)
    assert img == b"\xaa" * 16 + b"\xbb" * 16 and not problems
    gap = [parse_line("@tb desc_hex slot=1 off=0 data=aa"), parse_line("@tb desc_hex slot=1 off=16 data=bb")]
    assert desc_check.reassemble(gap)[1], "a gap in the offsets is reported"


def test_pckc_full_and_partial():
    img = simdev.pckc_test_coupon()
    if img is None:
        pytest.skip("no keyboard/tools/coupon/descriptor.py")
    full = desc_check.check(img)
    assert full.format == "PCKC" and full.kind == "wrong_format" and not full.valid
    assert full.fields["type"] == "test" and full.fields["i3v3_ma"] == 120
    part = desc_check.check(img[:32])
    assert part.kind == "partial" and "CRC-32 cannot be checked" in " ".join(part.problems)
    bad = bytearray(img)
    bad[100] ^= 0xFF
    assert desc_check.check(bytes(bad)).kind == "crc"


def test_the_two_formats_disagree_on_the_test_coupon():
    """A finding for SPEC §11 #18: the two proposals describe the same coupon with different +5V currents."""
    img = simdev.pckc_test_coupon()
    if img is None:
        pytest.skip("no keyboard/tools/coupon/descriptor.py")
    pckc = desc_check.check(img).fields
    pckd = desc_check.check(simdev.pckd_test_coupon(0)).fields
    assert pckc["i3v3_ma"] == pckd["i3v3_ma"] == 120
    assert (pckc["i5v_ma"], pckd["i5v_ma"]) == (190, 170)


def test_host_readers_disagreeing_is_a_failure(tmp_path):
    lib_tool()
    fake = tmp_path / "coupon_desc.py"
    fake.write_text("def decode(b):\n    return {'type': 'test', 'serial': 99, 'i3v3_ma': 120, 'i5v_ma': 170,"
                    " 'length': 167, 'rev': 'A'}\n")
    rep = desc_check.check(simdev.pckd_test_coupon(1), pckd_tool=fake)
    assert not rep.valid and rep.kind == "host_disagree"


def test_missing_tools_are_not_fatal(tmp_path):
    rep = desc_check.check(simdev.pckd_test_coupon(1), pckd_tool=tmp_path / "none.py")
    assert rep.valid and rep.tools == ["tbbench.desc_check"]
    img = b"PCKC\x01\x00\x00\x01" + b"\0" * 24
    rep = desc_check.check(img, pckc_tool=tmp_path / "none.py")
    assert rep.format == "PCKC" and "not checked" in " ".join(rep.problems)


def test_unknown_and_empty():
    assert desc_check.check(b"").kind == "empty"
    assert desc_check.check(b"ABCD" + b"\0" * 28).format == "unknown"


def test_g_line_records_as_the_firmware_reads_them():
    """lib/src/desc.c TB_DESC_REC_GLINE: G0-G5 only (value), each once (duplicate); src/cmds.c prints each one with
    a role as desc_gline."""
    f = desc_check.parse_pckd(simdev.pckd_test_coupon(3))
    assert sorted(f["glines"]) == [0, 1, 2, 3, 4, 5] and f["glines"][4] == {"role": 6, "arg": 0}
    for glines, kind in (({6: (5, 0)}, "value"),):
        img = simdev.pckd_encode(1, 120, 170, glines=glines)
        with pytest.raises(desc_check.DescError) as e:
            desc_check.parse_pckd(img)
        assert e.value.kind == kind
    two = simdev.pckd_encode(1, 120, 170, glines={0: (5, 0)})
    head, rec = two[:24], two[24:-2]
    body = head[:6] + (len(two) + 5).to_bytes(2, "little") + head[8:] + rec + rec
    img = body + desc_check.crc16_ccitt(body).to_bytes(2, "little")
    with pytest.raises(desc_check.DescError) as e:
        desc_check.parse_pckd(img)
    assert e.value.kind == "duplicate"
