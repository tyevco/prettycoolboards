#!/usr/bin/env python3
"""Feed a report stream captured by the USB simulation through host/hid8k_analysis.py.

The simulation (hid8k-sim, --hid8k_capture=FILE) writes every HID report of its undisturbed stream
as 80-byte records: u64 arrival time in ns (simulated, at the host class's completion callback),
u16 length, 6 reserved bytes, then the report (zero padded to 64). This script gives each one to
the host tool's Recorder exactly as hid8k_measure.py gives it a report read from hidraw or
hidapi, and runs the same analyze(). So it proves the host tool parses and judges what the
firmware actually sends (its report layout, sequence numbers, cycle stamps, counters and flags),
not only the synthetic reports its unit tests build.

With --expect, it also checks the verdict the simulated bus should give:

  125   high speed, 125 us microframes (sim built with hs_fix.conf): every criterion but the 600 s
        duration passes, so the gate verdict is INCOMPLETE with only "duration" failed, and with
        --min-duration shortened to the capture it is PASS, strict PASS.
  1000  high speed, 1 ms frames (Zephyr's own virtual host controller): the stream is 1000
        reports/s, so device_rate, host_rate and device_p999 fail, nothing else does, and strict
        fails on the late counter.
  fs    full speed (sim built with fs.overlay): as 1000, and high_speed fails too: the summary
        must say "FULL speed", the bench's first failure signature.

In every case the keyboard reports the capture holds (--kbd-reports, the simulation presses the
button once while capturing) must be the ones the stats reports' kbd_count accounts for, with
no sequence gap: the host tool must not count them as lost reports.

What it cannot show: anything about real timing. Simulated code takes no time, so the submit cost
is 0 cycles, every interval is exactly one frame, and the host arrival times are the host
stack's completion callbacks, not user-space reads.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "host"))
sys.dont_write_bytecode = True  # no __pycache__ in the source tree

import hid8k_analysis as ha  # noqa: E402

RECORD = struct.Struct("<QH6x64s")
assert RECORD.size == 80

STATS_LINE = re.compile(rb"^hid8k t=(\d+)s ")


def read_capture(path: str):
    """Yield (arrival_ns, report bytes) from a capture file."""
    with open(path, "rb") as f:
        data = f.read()
    if len(data) % RECORD.size:
        raise ValueError(f"{path}: {len(data)} bytes is not a whole number of 80-byte records")
    for off in range(0, len(data), RECORD.size):
        arrival_ns, length, report = RECORD.unpack_from(data, off)
        if not 1 <= length <= 64:
            raise ValueError(f"{path}: record at {off} has length {length}")
        yield arrival_ns, report[:length]


def cdc_lines_in(path: str, t_first_s: float, t_last_s: float) -> dict:
    """The CDC logger's result (hid8k_measure.py's format) for the stats lines stamped inside the
    capture's device-uptime span: what a host reading the console during the run would count."""
    n = 0
    last = None
    with open(path, "rb") as f:
        for raw in f.read().split(b"\n"):
            m = STATS_LINE.match(raw)
            if m and t_first_s < int(m.group(1)) <= t_last_s:
                n += 1
                last = raw.decode("ascii", "replace").strip()
    return {"mode": "normal", "stats_lines": n, "last_stats_line": last, "log": path}


def load(path: str) -> ha.Recorder:
    # No warm-up: the simulation starts capturing once the stream is steady.
    rec = ha.Recorder(warmup_s=0.0)
    for arrival_ns, report in read_capture(path):
        rec.add(report, arrival_ns)
    return rec


def expectations(result_gate: dict, result_short: dict, period: str,
                 kbd_reports: int = None) -> list:
    """Failures of the expected verdicts for this bus ("125", "1000" or "fs"; empty: as
    expected)."""
    period = str(period)
    bad = []

    def want(cond, text):
        if not cond:
            bad.append(text)

    gate_failed = set(result_gate.get("failed", []))
    short_failed = set(result_short.get("failed", []))
    host = result_short.get("host", {}).get("sequence", {})
    want(result_short.get("bad_reports") == 0, "no bad reports")
    want(result_short.get("high_speed") is (period != "fs"),
         "every report says " + ("full speed" if period == "fs" else "high speed"))
    want(host.get("gaps") == 0 and host.get("duplicates") == 0 and host.get("out_of_order") == 0,
         "no sequence gaps, duplicates or reordering")
    seen = result_short.get("keyboard_reports_seen")
    want(host.get("keyboard_reports") == seen and host.get("keyboard_mismatch") == 0,
         f"the keyboard reports on the wire ({seen}) are the ones kbd_count accounts for "
         f"({host.get('keyboard_reports')}, {host.get('keyboard_mismatch')} mismatches)")
    if kbd_reports is not None:
        want(seen == kbd_reports, f"{kbd_reports} keyboard reports in the capture (got {seen})")
    if period == "125":
        want(result_gate.get("verdict") == "INCOMPLETE" and gate_failed == {"duration"},
             "gate criteria: INCOMPLETE, only the 600 s duration failed")
        want(result_short.get("verdict") == "PASS", "short criteria: PASS")
        want(result_short.get("strict") == "PASS", "short criteria: strict PASS")
        rate = result_short["device"]["completion_rate_per_s"]
        want(abs(rate - 8000.0) < 1.0, f"device rate 8000/s (got {rate:.3f})")
        p999 = result_short["device"]["intervals_us"]["p999"]
        want(p999 == 125.0, f"device p99.9 125 us (got {p999})")
    else:
        fails = {"device_rate", "host_rate", "device_p999"}
        if period == "fs":
            fails.add("high_speed")
        want(result_short.get("verdict") == "FAIL", "short criteria: FAIL")
        want(short_failed == fails,
             f"only {', '.join(sorted(fails))} fail (got {sorted(short_failed)})")
        want(result_short.get("strict") == "FAIL", "strict FAIL (the late counter rose)")
        rate = result_short["device"]["completion_rate_per_s"]
        want(abs(rate - 1000.0) < 1.0, f"device rate 1000/s (got {rate:.3f})")
    return bad


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("capture", help="the file the simulation wrote with --hid8k_capture")
    p.add_argument("--cdc-log", help="the file the simulation wrote with --hid8k_cdc_log")
    p.add_argument("--min-duration", type=float, default=None,
                   help="duration criterion for the second analysis (default: the capture's "
                        "length less 10 ms)")
    p.add_argument("--expect", choices=("125", "1000", "fs"), default=None,
                   help="check the verdicts this bus should give: 125 or 1000 (us, high speed) "
                        "or fs (full speed)")
    p.add_argument("--kbd-reports", type=int, default=None,
                   help="with --expect: the keyboard reports the capture must hold")
    p.add_argument("--json", help="write both results here")
    args = p.parse_args(argv)

    rec = load(args.capture)
    if len(rec) < 2 or rec.first is None or rec.last is None:
        print(f"{args.capture}: fewer than two stats reports")
        return 1
    cdc = None
    if args.cdc_log:
        cdc = cdc_lines_in(args.cdc_log, rec.first.uptime_ms / 1e3, rec.last.uptime_ms / 1e3)
    span_s = (rec.arrival_ns[-1] - rec.arrival_ns[0]) / 1e9
    min_dur = args.min_duration if args.min_duration is not None else max(0.0, span_s - 0.01)

    gate = ha.analyze(rec, ha.Criteria(), cdc)
    short = ha.analyze(rec, ha.Criteria(min_duration_s=min_dur), cdc)
    header = [f"capture {args.capture}: {len(rec):,} stats reports, {span_s:.4f} s simulated"]
    print(ha.format_summary(gate, header + ["--- gate criteria (as on the bench) ---"]))
    print()
    print(ha.format_summary(short, [f"--- the same with min_duration_s = {min_dur:.3f} ---"]))

    if args.json:
        with open(args.json, "w", encoding="ascii", newline="\n") as f:
            json.dump({"gate": gate, "short": short}, f, indent=1)
            f.write("\n")

    if args.expect is not None:
        bad = expectations(gate, short, args.expect, args.kbd_reports)
        print()
        if bad:
            for b in bad:
                print(f"EXPECTATION FAILED: {b}")
            return 1
        what = "a full-speed bus" if args.expect == "fs" else f"a {args.expect} us frame"
        print(f"expectations for {what}: all met")
    return 0


if __name__ == "__main__":
    sys.exit(main())
