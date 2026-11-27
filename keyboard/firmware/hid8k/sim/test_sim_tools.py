"""Tests for the simulation's host-side tools (no Zephyr needed): the capture reader and its
expected verdicts (sim_capture.py) and the ELF descriptor printer (usb_descriptors_elf.py).

  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest keyboard/firmware/hid8k/sim -q -p no:cacheprovider

They prove the tools' parsing and logic on synthetic input; the simulation itself (run_sim.py)
is what feeds them real firmware output.
"""

import os
import struct
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "host"))

import hid8k_analysis as ha  # noqa: E402
import sim_capture  # noqa: E402
import usb_descriptors_elf as ude  # noqa: E402


def synthetic_capture(path, period_us, n=4000, depth=2, kbd_at=(), hs=True, count_kbd=True):
    """What the simulation writes for a stream with this frame period: one report per frame,
    a keyboard report (ID 1, 30 bytes) in the frames listed in kbd_at, a stats report in the
    others. Every report takes a seq; count_kbd=False is a firmware that forgets to count the
    keyboard reports in kbd_count."""
    late = 0
    kbd = 0
    with open(path, "wb") as f:
        for i in range(n):
            arrival_ns = (1_000_000 + i * period_us) * 1000
            if i > 0 and period_us > 187.5:
                late += 1
            if i in kbd_at:
                rep = bytes([ha.REPORT_ID_KBD]) + bytes(29)
                kbd += 1 if count_kbd else 0
            else:
                t_done = 1_000_000 + (i - depth) * period_us
                rep = ha.pack_stats(seq=1000 + i, done_seq=1000 + i - depth, t_done=t_done,
                                    t_submit=t_done, late=late, uptime_ms=t_done // 1000,
                                    kbd_count=kbd, cpu_hz=1_000_000,
                                    flags=ha.FLAG_HIGH_SPEED if hs else 0, depth=depth)
            f.write(sim_capture.RECORD.pack(arrival_ns, len(rep), rep))


def test_record_layout_matches_the_simulation():
    # host_hid.c: struct capture_rec { u64 arrival_ns; u16 len; u16; u32; u8 data[64]; }
    assert sim_capture.RECORD.size == 80


def test_capture_round_trip(tmp_path):
    p = tmp_path / "cap.bin"
    synthetic_capture(p, 125, n=10)
    recs = list(sim_capture.read_capture(str(p)))
    assert len(recs) == 10
    assert recs[1][0] - recs[0][0] == 125_000
    assert ha.parse_stats(recs[3][1]).seq == 1003


def test_truncated_capture_is_refused(tmp_path):
    p = tmp_path / "cap.bin"
    synthetic_capture(p, 125, n=3)
    with open(p, "ab") as f:
        f.write(b"\0" * 7)
    try:
        list(sim_capture.read_capture(str(p)))
    except ValueError:
        return
    raise AssertionError("a partial record was accepted")


def test_expectations_125us(tmp_path):
    p = tmp_path / "cap.bin"
    synthetic_capture(p, 125)
    assert sim_capture.main([str(p), "--expect", "125"]) == 0
    # The same stream judged as if it were the 1 ms one must not pass.
    assert sim_capture.main([str(p), "--expect", "1000"]) == 1


def test_expectations_1000us(tmp_path):
    p = tmp_path / "cap.bin"
    synthetic_capture(p, 1000, n=3000)
    assert sim_capture.main([str(p), "--expect", "1000"]) == 0
    assert sim_capture.main([str(p), "--expect", "125"]) == 1


def test_a_gap_breaks_the_expectation(tmp_path):
    p = tmp_path / "cap.bin"
    synthetic_capture(p, 125)
    data = bytearray(p.read_bytes())
    del data[80 * 100:80 * 101]  # one report lost
    p.write_bytes(bytes(data))
    assert sim_capture.main([str(p), "--expect", "125"]) == 1


def test_expectations_full_speed(tmp_path):
    p = tmp_path / "cap.bin"
    synthetic_capture(p, 1000, n=3000, hs=False)
    assert sim_capture.main([str(p), "--expect", "fs"]) == 0
    # A full-speed stream must not pass as the high-speed 1 ms one, nor the other way round.
    assert sim_capture.main([str(p), "--expect", "1000"]) == 1
    q = tmp_path / "cap_hs.bin"
    synthetic_capture(q, 1000, n=3000)
    assert sim_capture.main([str(q), "--expect", "fs"]) == 1


def test_keyboard_reports_accounted(tmp_path):
    p = tmp_path / "cap.bin"
    synthetic_capture(p, 125, kbd_at=(1000, 2500))
    assert sim_capture.main([str(p), "--expect", "125", "--kbd-reports", "2"]) == 0
    assert sim_capture.main([str(p), "--expect", "125", "--kbd-reports", "3"]) == 1


def test_uncounted_keyboard_reports_fail(tmp_path):
    # kbd_count not advanced: the host tool must see the seq gaps as lost reports.
    p = tmp_path / "cap.bin"
    synthetic_capture(p, 125, kbd_at=(1000, 2500), count_kbd=False)
    assert sim_capture.main([str(p), "--expect", "125", "--kbd-reports", "2"]) == 1


def test_cdc_lines_counted_inside_the_span(tmp_path):
    log = tmp_path / "cdc.log"
    log.write_bytes(b"".join(f"hid8k t={t}s usb=cfg hs rate=8000.0/s\r\n".encode()
                             for t in range(1, 8)) + b"~fill 00000001 ....\r\n")
    got = sim_capture.cdc_lines_in(str(log), 2.5, 5.0)
    # The window is (first, last]: the lines stamped t=3, 4 and 5; the filler line is not one.
    assert got["stats_lines"] == 3


def test_describe_endpoint_and_interface():
    assert ude.describe(bytes([7, 5, 0x81, 3, 0x40, 0, 1])) == \
        "endpoint 0x81 interrupt IN, wMaxPacketSize 64, bInterval 1"
    assert ude.describe(bytes([9, 4, 0, 0, 1, 3, 0, 0, 0])) == \
        "interface 0 alt 0, 1 endpoint(s), class 03/00/00"


def test_chain_labels_and_unused_tail():
    blob = bytes([9, 4, 0, 0, 1, 3, 0, 0, 0]) + bytes([7, 5, 0x81, 3, 0x40, 0, 1]) + bytes(7)
    lines = ude.chain(blob, ("if0", "in_ep", "out_ep"))
    assert "if0: interface 0" in lines[0]
    assert "in_ep: endpoint 0x81" in lines[1]
    assert "7 zero bytes" in lines[2] and "out_ep" in lines[2]


HID_BLOB = bytes([9, 4, 0, 0, 1, 3, 0, 0, 0, 7, 5, 0x81, 3, 0x40, 0, 1])
CDC_BLOB = bytes([8, 0x0B, 0, 2, 2, 2, 0, 0])
RDESC_BLOB = bytes([0x05, 0x01, 0x09, 0x06, 0xA1, 0x01, 0xC0])
ALL_SYMBOLS = (("hid_desc_0", HID_BLOB), ("cdc_acm_desc_0", CDC_BLOB), ("report_desc", RDESC_BLOB))


def _tiny_elf(path, is64, symbols=ALL_SYMBOLS):
    """A minimal little-endian ELF with .data holding the symbols and a .symtab naming them."""
    payload = b"".join(blob for _, blob in symbols)
    strtab = b"\0" + b"".join(name.encode() + b"\0" for name, _ in symbols)
    shstr = b"\0.data\0.symtab\0.strtab\0.shstrtab\0"
    addr = 0x20000000
    fmt = "<IBBHQQ" if is64 else "<IIIBBH"
    sym = struct.pack(fmt, 0, 0, 0, 0, 0, 0)
    name_off, value = 1, addr
    for name, blob in symbols:
        if is64:
            sym += struct.pack(fmt, name_off, 1, 0, 1, value, len(blob))
        else:
            sym += struct.pack(fmt, name_off, value, len(blob), 1, 0, 1)
        name_off += len(name) + 1
        value += len(blob)
    ehsize = 64 if is64 else 52
    off_data = ehsize
    off_sym = off_data + len(payload)
    off_str = off_sym + len(sym)
    off_shs = off_str + len(strtab)
    shoff = off_shs + len(shstr)
    shoff += (-shoff) % 8
    secs = [(0, 0, 0, 0, 0, 0, 0), (1, 1, addr, off_data, len(payload), 0, 0),
            (7, 2, 0, off_sym, len(sym), 3, 24 if is64 else 16),
            (15, 3, 0, off_str, len(strtab), 0, 0), (23, 3, 0, off_shs, len(shstr), 0, 0)]
    if is64:
        hdr = b"\x7fELF\x02\x01\x01" + bytes(9) + struct.pack(
            "<HHIQQQIHHHHHH", 1, 62, 1, 0, 0, shoff, 0, ehsize, 0, 0, 64, len(secs), 4)
        sh = b"".join(struct.pack("<IIQQQQIIQQ", n, t, 0, a, o, s, ln, 0, 1, e)
                      for n, t, a, o, s, ln, e in secs)
    else:
        hdr = b"\x7fELF\x01\x01\x01" + bytes(9) + struct.pack(
            "<HHIIIIIHHHHHH", 1, 40, 1, 0, 0, shoff, 0, ehsize, 0, 0, 40, len(secs), 4)
        sh = b"".join(struct.pack("<IIIIIIIIII", n, t, 0, a, o, s, ln, 0, 1, e)
                      for n, t, a, o, s, ln, e in secs)
    body = hdr + payload + sym + strtab + shstr
    body += bytes(shoff - len(body))
    path.write_bytes(body + sh)


def test_elf_symbol_bytes_32_and_64(tmp_path):
    for is64 in (False, True):
        p = tmp_path / f"t{64 if is64 else 32}.elf"
        _tiny_elf(p, is64)
        elf = ude.Elf(str(p))
        for name, blob in ALL_SYMBOLS:
            assert elf.symbol_bytes(name) == [blob]


def test_compare_identical_and_different(tmp_path):
    a = tmp_path / "a.elf"
    b = tmp_path / "b.elf"
    _tiny_elf(a, False)
    _tiny_elf(b, True)
    assert ude.main(["--compare", str(a), str(b)]) == 0
    data = bytearray(b.read_bytes())
    i = data.index(bytes([7, 5, 0x81, 3, 0x40, 0, 1]))
    data[i + 6] = 4  # bInterval 4
    b.write_bytes(bytes(data))
    assert ude.main(["--compare", str(a), str(b)]) == 1


def test_compare_refuses_missing_descriptors(tmp_path):
    # Two files that both lack a descriptor must not compare as "identical".
    a = tmp_path / "a.elf"
    b = tmp_path / "b.elf"
    only_hid = (("hid_desc_0", HID_BLOB),)
    _tiny_elf(a, False, only_hid)
    _tiny_elf(b, False, only_hid)
    assert ude.main(["--compare", str(a), str(b)]) == 1
    _tiny_elf(a, False)
    assert ude.main(["--compare", str(a), str(b)]) == 1
    assert ude.main([str(b)]) == 1
    assert ude.main([str(a)]) == 0
