"""Tests for hid8k_analysis (synthetic data only: nothing here has been measured on hardware)."""

from __future__ import annotations

import os
import random
import re
from collections import Counter

import pytest

import hid8k_analysis as ha

HERE = os.path.dirname(os.path.abspath(__file__))
HEADER = os.path.join(HERE, "..", "src", "hid8k_report.h")

CPU_HZ = 160_000_000
PERIOD = CPU_HZ // 8000  # 20000 cycles = 125 us
U32 = 1 << 32


def synth(n_positions, *, depth=2, start_seq=0, start_t=0, period=PERIOD, kbd_at=(),
          drop=(), dup=(), missed_after=(), jitter=0, seed=1, flags=ha.FLAG_HIGH_SPEED,
          fn_start=None, refused=0, busy=0, late=0, arrival_step_ns=125_000, cpu_hz=CPU_HZ,
          header_cpu_hz=None):
    """Simulate the firmware's stats stream as the host would receive it.

    Endpoint positions p = 0..n-1 carry seq start_seq + p; positions in kbd_at are keyboard
    reports, the rest stats reports. The report at position p is built at the completion of
    position p - depth. Completion c happens at start_t + c * period (+ jitter), plus one extra
    period for every c' in missed_after with c' < c (a microframe without a completion).
    cpu_hz is the clock the cycle stamps count; header_cpu_hz, if given, is what the reports
    claim instead (a firmware with the wrong clock constant). Returns a list of (bytes, arrival_ns).
    """
    rnd = random.Random(seed)
    kbd_at = set(kbd_at)
    missed = Counter(missed_after)  # a value listed twice: two microframes missed there
    t_comp = []
    shift = 0
    for c in range(n_positions):
        shift += period * missed[c - 1]
        t_comp.append(start_t + c * period + shift + (rnd.randint(-jitter, jitter) if jitter else 0))
    out = []
    kbd = 0
    arrival = 1_000_000_000
    stats_index = 0
    for p in range(n_positions):
        if p in kbd_at:
            kbd += 1
            continue
        c = p - depth
        done_seq = start_seq + c if c >= 0 else start_seq
        t_done = t_comp[c] if c >= 0 else start_t
        missed_before = sum(k for m, k in missed.items() if m < c) if c >= 0 else 0
        fn = 0 if fn_start is None else (fn_start + max(c, 0) + missed_before) % ha.FN_MODULO
        data = ha.pack_stats(
            flags=flags | (ha.FLAG_FN_VALID if fn_start is not None else 0),
            depth=depth,
            seq=start_seq + p,
            t_submit=t_done + 300,
            done_seq=done_seq,
            t_done=t_done,
            submit_cost=400 + (stats_index % 7),
            kbd_count=kbd,
            refused=refused,
            busy=busy,
            late=late,
            fn_done=fn,
            uptime_ms=(t_done // (cpu_hz // 1000)),
            cpu_hz=header_cpu_hz or cpu_hz,
        )
        stats_index += 1
        arrival += arrival_step_ns
        if p in drop:
            continue
        out.append((data, arrival))
        if p in dup:
            out.append((data, arrival + 1_000))
    return out


def record(stream, warmup_s=0.0):
    rec = ha.Recorder(warmup_s=warmup_s)
    for data, t in stream:
        rec.add(data, t)
    return rec


def fields(stream, name):
    return [getattr(ha.parse_stats(d), name) for d, _ in stream]


# ------------------------------------------------------------------ layout and parsing


def test_layout_matches_firmware_header():
    text = open(HEADER, encoding="ascii").read()
    defs = dict(re.findall(r"#define\s+(HID8K_\w+)\s+\(?(0x[0-9A-Fa-f]+|\d+)U?", text))
    num = {k: int(v, 0) for k, v in defs.items()}
    offsets = ha.layout_offsets()
    for name, off in offsets.items():
        key = "HID8K_OFF_" + name.upper()
        if name == "report_id":
            key = "HID8K_OFF_ID"
        assert num[key] == off, (name, num[key], off)
    assert num["HID8K_STATS_SIZE"] == ha.STATS_SIZE
    assert num["HID8K_FORMAT"] == ha.FORMAT
    assert num["HID8K_REPORT_ID_STATS"] == ha.REPORT_ID_STATS
    assert num["HID8K_REPORT_ID_KBD"] == ha.REPORT_ID_KBD
    assert num["HID8K_FLAG_FN_VALID"] == ha.FLAG_FN_VALID
    assert num["HID8K_FLAG_CDC_HEAVY"] == ha.FLAG_CDC_HEAVY
    assert num["HID8K_FLAG_HIGH_SPEED"] == ha.FLAG_HIGH_SPEED
    assert num["HID8K_VENDOR_USAGE_PAGE"] == ha.VENDOR_USAGE_PAGE
    assert num["HID8K_LATE_US_X10"] == int(ha.LATE_US * 10)
    assert num["HID8K_NOMINAL_US"] == ha.NOMINAL_US


def test_pack_parse_roundtrip():
    data = ha.pack_stats(flags=7, depth=3, seq=0xFFFFFFFF, t_submit=123, done_seq=0xFFFFFFFD,
                         t_done=U32 - 1, submit_cost=999, refused=1, busy=2, late=3,
                         kbd_count=4, fn_done=0x3FFF, fn_submit=5, max_interval=6,
                         uptime_ms=7, cdc_bytes=8, cdc_dropped=9)
    assert len(data) == 64 and data[0] == 2 and data[1] == ha.FORMAT
    r = ha.parse_stats(data)
    assert (r.seq, r.done_seq, r.t_done, r.fn_done, r.cdc_dropped) == (
        0xFFFFFFFF, 0xFFFFFFFD, U32 - 1, 0x3FFF, 9)
    assert r.cpu_hz == CPU_HZ and r.depth == 3 and r.flags == 7


def test_parse_rejects_other_reports():
    good = ha.pack_stats(seq=1)
    with pytest.raises(ValueError):
        ha.parse_stats(good[:63])
    with pytest.raises(ValueError):
        ha.parse_stats(bytes([1]) + good[1:])
    with pytest.raises(ValueError):
        ha.parse_stats(good[:1] + bytes([ha.FORMAT + 1]) + good[2:])


# ------------------------------------------------------------------ unwrap and stats helpers


def test_unwrap_32bit_forward_and_back():
    assert ha.unwrap([U32 - 2, U32 - 1, 0, 1]) == [U32 - 2, U32 - 1, U32, U32 + 1]
    assert ha.unwrap([5, 3, 4]) == [5, 3, 4]
    assert ha.unwrap([1, U32 - 1]) == [1, -1]


def test_unwrap_14bit():
    vals = [16380, 16382, 0, 2, 16383 & 5]
    assert ha.unwrap(vals, ha.FN_MODULO) == [16380, 16382, 16384, 16386, 16389]


def test_counter_delta_wraps():
    assert ha.counter_delta(U32 - 3, 2) == 5
    assert ha.counter_delta(10, 10) == 0


def test_describe_counts_equals_describe():
    rnd = random.Random(7)
    vals = [rnd.choice([19990, 20000, 20000, 20010, 25000, 40000]) for _ in range(5000)]
    a = ha.describe(vals)
    b = ha.describe_counts(Counter(vals))
    assert a == b
    assert ha.describe([]) == ha.describe_counts(Counter())


def test_percentile_nearest_rank():
    s = list(range(1, 1001))
    assert ha.percentile(s, 50) == 500
    assert ha.percentile(s, 99) == 990
    assert ha.percentile(s, 99.9) == 999
    assert ha.percentile(s, 100) == 1000


# ------------------------------------------------------------------ sequence checks


def test_sequence_perfect():
    st = synth(1000)
    r = ha.sequence_check(fields(st, "seq"), fields(st, "kbd_count"))
    assert (r.gaps, r.missing, r.duplicates, r.out_of_order) == (0, 0, 0, 0)
    assert r.received == 1000 and r.span == 1000


def test_sequence_gaps_counted():
    st = synth(1000, drop={100, 500, 501, 502})
    r = ha.sequence_check(fields(st, "seq"), fields(st, "kbd_count"))
    assert r.gaps == 2 and r.missing == 4 and r.duplicates == 0


def test_sequence_duplicate():
    st = synth(200, dup={50})
    r = ha.sequence_check(fields(st, "seq"), fields(st, "kbd_count"))
    assert r.duplicates == 1 and r.gaps == 0 and r.received == 201


def test_sequence_wraparound():
    st = synth(1000, start_seq=U32 - 300)
    seqs = fields(st, "seq")
    assert min(seqs) < 1000 < U32 - 1000 < max(seqs)  # it really wraps
    r = ha.sequence_check(seqs, fields(st, "kbd_count"))
    assert (r.gaps, r.duplicates, r.out_of_order, r.span) == (0, 0, 0, 1000)


def test_sequence_gap_across_wraparound():
    st = synth(1000, start_seq=U32 - 300, drop={300})  # the report with seq 0
    r = ha.sequence_check(fields(st, "seq"), fields(st, "kbd_count"))
    assert r.gaps == 1 and r.missing == 1


def test_keyboard_reports_are_not_gaps():
    st = synth(1000, kbd_at={100, 400})
    r = ha.sequence_check(fields(st, "seq"), fields(st, "kbd_count"))
    assert (r.gaps, r.missing, r.kbd_reports, r.kbd_mismatch) == (0, 0, 2, 0)
    assert r.received == 998


def test_keyboard_report_next_to_a_drop():
    st = synth(1000, kbd_at={100}, drop={101})
    r = ha.sequence_check(fields(st, "seq"), fields(st, "kbd_count"))
    assert r.gaps == 1 and r.missing == 1 and r.kbd_reports == 1


def test_out_of_order():
    st = synth(100)
    st[10], st[11] = st[11], st[10]
    r = ha.sequence_check(fields(st, "seq"), fields(st, "kbd_count"))
    # A swap is one late report, not a gap: the report that seemed missing arrived.
    assert (r.out_of_order, r.gaps, r.missing, r.duplicates) == (1, 0, 0, 0)


def test_duplicate_of_an_older_report_is_a_duplicate():
    st = synth(100)
    st.insert(20, st[10])  # seq 10 again, after seq 19
    r = ha.sequence_check(fields(st, "seq"), fields(st, "kbd_count"))
    assert (r.duplicates, r.out_of_order, r.gaps, r.missing) == (1, 0, 0, 0)


def test_late_report_fills_part_of_a_gap():
    st = synth(1000, drop={500, 502})
    late = synth(1000)[501]
    st = [x for x in st if ha.parse_stats(x[0]).seq != 501]  # 500, 501 and 502 missing
    st.insert(600, late)  # 501 turns up late
    r = ha.sequence_check(fields(st, "seq"), fields(st, "kbd_count"))
    assert (r.gaps, r.missing, r.out_of_order, r.duplicates) == (1, 2, 1, 0)
    st.insert(700, late)  # and once more: now a duplicate
    r = ha.sequence_check(fields(st, "seq"), fields(st, "kbd_count"))
    assert (r.gaps, r.missing, r.out_of_order, r.duplicates) == (1, 2, 1, 1)


def test_late_report_across_wraparound():
    st = synth(1000, start_seq=U32 - 300)
    st[300], st[301] = st[301], st[300]  # seq 0 arrives after seq 1
    r = ha.sequence_check(fields(st, "seq"), fields(st, "kbd_count"))
    assert (r.out_of_order, r.gaps, r.missing, r.duplicates) == (1, 0, 0, 0)


def test_late_report_older_than_the_tracked_holes():
    st = synth(1000, drop={100, 200, 300})
    st.append(synth(1000)[100])  # 100 arrives at the very end
    seqs, kbd = fields(st, "seq"), fields(st, "kbd_count")
    r = ha.sequence_check(seqs, kbd, max_holes=1)  # only the hole at 300 is remembered
    assert (r.out_of_order, r.duplicates) == (1, 0)
    r = ha.sequence_check(seqs, kbd)
    assert (r.out_of_order, r.duplicates, r.gaps, r.missing) == (1, 0, 2, 2)


# ------------------------------------------------------------------ device-side timing


def test_device_intervals_perfect_and_wrap():
    st = synth(2000, start_t=U32 - 5 * PERIOD)
    t = fields(st, "t_done")
    assert t[0] > t[-1]  # the cycle counter wraps inside the run
    dev = ha.device_intervals(fields(st, "done_seq"), t, CPU_HZ)
    assert dict(dev.interval_counts) == {PERIOD: 1997}
    assert dev.repeated == 2  # the two priming reports name the same (initial) completion
    assert dev.completions == 1997
    assert dev.seconds == pytest.approx(1997 * 125e-6)


def test_device_intervals_skip_nonconsecutive():
    st = synth(1000, drop={500})
    dev = ha.device_intervals(fields(st, "done_seq"), fields(st, "t_done"), CPU_HZ)
    assert dev.skipped_pairs == 1
    assert sum(dev.interval_counts.values()) == 995  # 998 pairs - 2 repeated - 1 skipped


def test_missed_microframe_shows_as_long_interval():
    st = synth(1000, missed_after={600})
    dev = ha.device_intervals(fields(st, "done_seq"), fields(st, "t_done"), CPU_HZ)
    assert dev.interval_counts[2 * PERIOD] == 1
    assert ha.count_above(dev.interval_counts, ha.LATE_US * CPU_HZ / 1e6) == 1


# ------------------------------------------------------------------ frame numbers


def test_frame_check_counts_missed_microframes_across_wrap():
    st = synth(40000, fn_start=16000, missed_after={1000, 30000})
    seconds = ha.device_intervals(fields(st, "done_seq"), fields(st, "t_done"), CPU_HZ).seconds
    fr = ha.frame_check(fields(st, "fn_done"), fields(st, "done_seq"), seconds)
    assert fr.unit == "microframe" and fr.missed == 2


def test_frame_check_unit_frame():
    # a counter that advances once per 8 completions (1 ms frames)
    n = 8000
    fn = [(c // 8) % ha.FN_MODULO for c in range(n)]
    ds = list(range(n))
    fr = ha.frame_check(fn, ds, seconds=(n - 1) * 125e-6)
    assert fr.unit == "frame" and fr.missed is None


# ------------------------------------------------------------------ whole-run analysis

SHORT = ha.Criteria(min_duration_s=1.0)


def test_analyze_perfect_run_passes():
    res = ha.analyze(record(synth(12000, jitter=800)), SHORT)
    assert res["verdict"] == "PASS", res["failed"]
    assert res["device"]["completion_rate_per_s"] == pytest.approx(8000, rel=1e-3)
    assert res["host"]["receive_rate_per_s"] == pytest.approx(8000, rel=1e-3)
    assert res["strict"] == "PASS"
    assert res["high_speed"] is True
    # +-800 cycles of jitter at each end: intervals within 125 +- 10 us
    assert 125 < res["device"]["intervals_us"]["p999"] <= 135


def test_analyze_passes_across_cycle_counter_wrap():
    # DWT CYCCNT wraps every 26.8 s at 160 MHz: a 10-minute run wraps it 22 times.
    res = ha.analyze(record(synth(12000, start_t=U32 - 3000 * PERIOD)), SHORT)
    assert res["verdict"] == "PASS", res["failed"]
    assert res["device_clock_mismatch_s"] < 0.002


def test_analyze_short_run_is_incomplete():
    res = ha.analyze(record(synth(12000)), ha.Criteria())
    assert res["verdict"] == "INCOMPLETE" and res["failed"] == ["duration"]


def test_analyze_gap_fails():
    res = ha.analyze(record(synth(12000, drop={5000})), SHORT)
    assert res["verdict"] == "FAIL" and "seq_gaps" in res["failed"]
    assert res["host"]["sequence"]["missing"] == 1


def test_analyze_duplicate_fails():
    res = ha.analyze(record(synth(12000, dup={42})), SHORT)
    assert "duplicates" in res["failed"]


def test_analyze_full_speed_fails():
    res = ha.analyze(record(synth(12000, flags=0)), SHORT)
    assert "high_speed" in res["failed"]


def test_analyze_slow_rate_fails():
    # 1 kHz: what a full-speed (1 ms) interrupt endpoint would give
    res = ha.analyze(record(synth(2000, period=CPU_HZ // 1000, arrival_step_ns=1_000_000)), SHORT)
    assert {"device_rate", "host_rate", "device_p999"} <= set(res["failed"])


def test_analyze_p999_fails_on_many_long_intervals():
    # 24 places in 12000 completions (0.2 %) where two microframes in a row had no completion,
    # i.e. 375 us intervals. A single missed microframe gives exactly 250 us, which the
    # p99.9 <= 250 us criterion still allows (the strict check is the one that catches it).
    places = list(range(100, 12000, 500))
    res = ha.analyze(record(synth(12000, missed_after=places + places)), SHORT)
    assert "device_p999" in res["failed"]
    assert res["device"]["intervals_above_2x_us"] == len(places)
    assert res["device"]["intervals_above_late_us"] == len(places)
    assert res["device"]["intervals_us"]["max"] == pytest.approx(375.0)


def test_analyze_few_missed_microframes_pass_but_strict_fails():
    res = ha.analyze(record(synth(12000, fn_start=0, missed_after={3000})), SHORT)
    assert res["verdict"] == "PASS"
    assert res["frames"]["missed_microframes"] == 1
    assert res["strict"] == "PASS"  # within the end tolerance of 2
    res = ha.analyze(record(synth(12000, fn_start=0, missed_after={3000, 6000, 9000})), SHORT)
    assert res["strict"] == "FAIL"


def test_analyze_counters_are_deltas():
    st = synth(12000, refused=7, busy=1, late=3)  # constant: nothing happened during the run
    res = ha.analyze(record(st), SHORT)
    assert res["verdict"] == "PASS"
    data, t = st[-1]
    r = ha.parse_stats(data)
    bumped = ha.pack_stats(**{**r.__dict__, "refused": r.refused + 1, "seq": r.seq + 1,
                              "done_seq": r.done_seq + 1, "t_done": r.t_done + PERIOD})
    res = ha.analyze(record(st + [(bumped, t + 125_000)]), SHORT)
    assert "refused" in res["failed"]


def test_device_times_use_the_reported_clock():
    # A 100 MHz build: 12500 cycles per 125 us. The tool must scale by the cpu_hz field.
    res = ha.analyze(record(synth(12000, cpu_hz=100_000_000, period=12_500)), SHORT)
    assert res["verdict"] == "PASS", res["failed"]
    assert res["cpu_hz"] == 100_000_000
    assert res["device"]["intervals_us"]["p50"] == pytest.approx(125.0)
    assert res["device"]["completion_rate_per_s"] == pytest.approx(8000, rel=1e-3)


def test_device_clock_mismatch_fails():
    # The reports claim 80 MHz while the stamps count 160 MHz: every time would be doubled.
    res = ha.analyze(record(synth(12000, header_cpu_hz=80_000_000)), SHORT)
    assert "device_clock" in res["failed"]
    assert res["device_clock_mismatch_s"] == pytest.approx(1.5, rel=0.01)


def test_stopped_cycle_counter_fails():
    st = synth(12000)
    frozen = []
    for data, t in st:
        r = ha.parse_stats(data)
        frozen.append((ha.pack_stats(**{**r.__dict__, "t_done": 12345}), t))
    res = ha.analyze(record(frozen), SHORT)
    assert "device_clock" in res["failed"] and "device_rate" in res["failed"]


def test_reader_error_fails():
    res = ha.analyze(record(synth(12000)), SHORT, reader_error="read failed: OSError: [Errno 19]")
    assert res["verdict"] == "FAIL" and "reader" in res["failed"]
    assert "STOPPED" in ha.format_summary(res)


def test_recorder_warmup_and_other_reports():
    st = synth(12000)
    kbd = bytes([1] + [0] * 29)
    rec = ha.Recorder(warmup_s=0.5)
    rec.add(kbd, st[0][1])
    for data, t in st:
        rec.add(data, t)
    rec.add(bytes([9, 9]), st[-1][1])
    rec.add(ha.pack_stats(seq=1)[:1] + bytes([99]) + bytes(62), st[-1][1])
    assert rec.kbd_reports_seen == 1 and rec.other_reports == 1 and rec.bad_reports == 1
    assert rec.discarded_warmup == 4000  # 0.5 s at 8 kHz
    assert len(rec) == 8000


def test_no_data():
    res = ha.analyze(ha.Recorder(), SHORT)
    assert res["verdict"] == "NO-DATA"
    assert "NO-DATA" in ha.format_summary(res)


def test_summary_mentions_verdict_and_caveat():
    res = ha.analyze(record(synth(12000)), SHORT)
    text = ha.format_summary(res, ["header line"])
    assert text.splitlines()[0] == "header line"
    assert "VERDICT: PASS" in text
    assert "NOT bus timing" in text
    assert len(text.splitlines()) <= 30


def test_cdc_criteria():
    rec = record(synth(12000, flags=ha.FLAG_HIGH_SPEED | ha.FLAG_CDC_HEAVY))
    ok = ha.analyze(rec, SHORT, {"mode": "heavy", "stats_lines": 2, "bytes": 1})
    assert ok["verdict"] == "PASS" and ok["cdc_checked"] and ok["cdc_mode"] == "heavy"
    silent = ha.analyze(rec, SHORT, {"mode": "heavy", "stats_lines": 0})
    assert "cdc_active" in silent["failed"]
    broken = ha.analyze(rec, SHORT, {"error": "cannot open COM9", "mode": "normal"})
    assert "cdc_active" in broken["failed"]
    normal_flags = ha.analyze(record(synth(12000)), SHORT, {"mode": "heavy", "stats_lines": 2})
    assert "cdc_heavy" in normal_flags["failed"]
    unchecked = ha.analyze(rec, SHORT)
    assert unchecked["cdc_checked"] is False
    assert "NOT CHECKED" in ha.format_summary(unchecked)
