"""Pure analysis for the hid8k 8 kHz HID proof: parse stats reports, record them, and judge a run.

No I/O here: hid8k_measure.py does the device access and file writing, and the tests drive these
functions with synthetic data. The stats report layout mirrors ../src/hid8k_report.h; the test
suite checks that the two agree.

Timing sources, and what each can and cannot show:

* Device side: the firmware stamps each report with DWT cycle counts taken in its
  input_report_done callback (a transfer completed, i.e. the host controller acknowledged the
  report) and just before each submit. Completion-to-completion intervals from these stamps
  include the device's own software latency (an interrupt, the STM32 UDC driver thread, then the
  USB stack thread), not only bus timing.
* Host side: arrival times are taken in user space when a read returns. The host controller,
  its driver, the HID class driver and the OS scheduler batch and delay reports, so these
  intervals are NOT bus timing. Use usbmon/Wireshark on Linux, or a USB analyser, for that.
"""

from __future__ import annotations

import bisect
import math
import struct
from array import array
from collections import Counter, deque
from dataclasses import dataclass
from fractions import Fraction
from typing import Iterable, Iterator, Optional, Sequence

REPORT_ID_KBD = 1
REPORT_ID_STATS = 2
STATS_SIZE = 64
FORMAT = 1

FLAG_FN_VALID = 0x01
FLAG_CDC_HEAVY = 0x02
FLAG_HIGH_SPEED = 0x04

VENDOR_USAGE_PAGE = 0xFF00
VENDOR_USAGE = 0x01

NOMINAL_US = 125.0
LATE_US = 187.5  # 1.5 x 125 us, the firmware's "late" threshold
FN_MODULO = 1 << 14  # OTG_HS DSTS.FNSOF is 14 bits wide
U32 = 1 << 32

# (name, struct code); offsets follow from the packing ("<", no padding). Mirrors hid8k_report.h.
STATS_LAYOUT = (
    ("report_id", "B"),
    ("format", "B"),
    ("flags", "B"),
    ("depth", "B"),
    ("seq", "I"),
    ("t_submit", "I"),
    ("done_seq", "I"),
    ("t_done", "I"),
    ("submit_cost", "I"),
    ("refused", "I"),
    ("busy", "I"),
    ("late", "I"),
    ("kbd_count", "I"),
    ("cpu_hz", "I"),
    ("fn_done", "H"),
    ("fn_submit", "H"),
    ("max_interval", "I"),
    ("uptime_ms", "I"),
    ("cdc_bytes", "I"),
    ("cdc_dropped", "I"),
)
STATS_FIELDS = tuple(name for name, _ in STATS_LAYOUT)
_STATS = struct.Struct("<" + "".join(code for _, code in STATS_LAYOUT))
assert _STATS.size == STATS_SIZE


def layout_offsets() -> dict:
    """Byte offset of each stats field, for comparison with the firmware header."""
    offsets = {}
    pos = 0
    for name, code in STATS_LAYOUT:
        offsets[name] = pos
        pos += struct.calcsize("<" + code)
    return offsets


@dataclass(frozen=True)
class StatsReport:
    report_id: int
    format: int
    flags: int
    depth: int
    seq: int
    t_submit: int
    done_seq: int
    t_done: int
    submit_cost: int
    refused: int
    busy: int
    late: int
    kbd_count: int
    cpu_hz: int
    fn_done: int
    fn_submit: int
    max_interval: int
    uptime_ms: int
    cdc_bytes: int
    cdc_dropped: int


def parse_stats(data: bytes) -> StatsReport:
    """Parse one stats report (report ID byte first). Raises ValueError if it is not one."""
    if len(data) < STATS_SIZE:
        raise ValueError(f"stats report too short: {len(data)} bytes, want {STATS_SIZE}")
    if data[0] != REPORT_ID_STATS:
        raise ValueError(f"not a stats report: report ID {data[0]}")
    if data[1] != FORMAT:
        raise ValueError(f"unknown stats format {data[1]} (this tool reads format {FORMAT})")
    return StatsReport(*_STATS.unpack_from(data, 0))


def pack_stats(**fields_) -> bytes:
    """Build a stats report (for tests and simulators). Missing fields default to 0."""
    values = {name: 0 for name in STATS_FIELDS}
    values.update(report_id=REPORT_ID_STATS, format=FORMAT, depth=2, cpu_hz=160_000_000)
    for name, value in fields_.items():
        if name not in values:
            raise KeyError(name)
        values[name] = value
    out = []
    for name, code in STATS_LAYOUT:
        mask = (1 << (8 * struct.calcsize("<" + code))) - 1
        out.append(values[name] & mask)
    return _STATS.pack(*out)


def iter_unwrap(values: Iterable[int], modulo: int = U32) -> Iterator[int]:
    """Undo counter wrap-around: each step is taken as the signed difference nearest to zero."""
    acc = 0
    prev = None
    half = modulo // 2
    for v in values:
        if prev is None:
            acc = v
        else:
            d = (v - prev) % modulo
            if d >= half:
                d -= modulo
            acc += d
        yield acc
        prev = v


def unwrap(values: Iterable[int], modulo: int = U32) -> list:
    """List form of iter_unwrap()."""
    return list(iter_unwrap(values, modulo))


def counter_delta(first: int, last: int, modulo: int = U32) -> int:
    """Increase of a monotonic counter between two samples (it wraps at most once)."""
    return (last - first) % modulo


def nearest_rank(q: float, n: int) -> int:
    """1-based nearest rank of percentile q (0..100) in n values, computed exactly.

    Fraction(str(q)) keeps 99.9 as 999/10: in floating point 99.9 / 100 * 1000 is
    999.0000000000001, which would round the rank up by one.
    """
    return max(1, min(n, math.ceil(Fraction(str(q)) * n / 100)))


def percentile(sorted_values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile of an already sorted sequence (q in 0..100)."""
    n = len(sorted_values)
    if n == 0:
        return float("nan")
    return sorted_values[nearest_rank(q, n) - 1]


_EMPTY = {"n": 0, "min": None, "mean": None, "p50": None, "p99": None, "p999": None,
          "max": None}


def describe(values: Iterable[float]) -> dict:
    """n, min, mean, p50, p99, p99.9 and max of a set of values (nearest-rank percentiles)."""
    s = sorted(values)
    n = len(s)
    if n == 0:
        return dict(_EMPTY)
    return {
        "n": n,
        "min": s[0],
        "mean": math.fsum(s) / n,
        "p50": percentile(s, 50.0),
        "p99": percentile(s, 99.0),
        "p999": percentile(s, 99.9),
        "max": s[-1],
    }


def describe_counts(counts: Counter, scale: float = 1.0) -> dict:
    """describe() for values given as {value: count}, each value multiplied by scale.

    Exact (the same nearest-rank percentiles as describe()) and small in memory: a 600 s run has
    4.8 million intervals but only thousands of distinct cycle counts.
    """
    n = sum(counts.values())
    if n == 0:
        return dict(_EMPTY)
    keys = sorted(counts)
    ranks = {q: nearest_rank(q, n) for q in (50.0, 99.0, 99.9)}
    found = {}
    seen = 0
    total = 0
    for k in keys:
        c = counts[k]
        seen += c
        total += k * c
        for q, r in ranks.items():
            if q not in found and seen >= r:
                found[q] = k
    return {
        "n": n,
        "min": keys[0] * scale,
        "mean": total / n * scale,
        "p50": found[50.0] * scale,
        "p99": found[99.0] * scale,
        "p999": found[99.9] * scale,
        "max": keys[-1] * scale,
    }


def count_above(counts: Counter, limit: float) -> int:
    """How many values in {value: count} exceed limit."""
    return sum(c for v, c in counts.items() if v > limit)


@dataclass
class SequenceResult:
    received: int
    gaps: int  # places where reports are still missing at the end of the run
    missing: int  # reports never received
    duplicates: int  # a seq received again, whenever it first arrived
    out_of_order: int  # reports that arrived after a higher seq (late, not duplicates)
    kbd_reports: int  # keyboard reports (ID 1) the firmware sent in the span
    kbd_mismatch: int  # seq advanced by less than the keyboard count says: should never happen
    span: int  # seq numbers covered, first to last


class _Hole:
    """Stats reports missing between two received seqs: lo < seq < hi, `remaining` of them."""

    __slots__ = ("lo", "hi", "remaining", "late")

    def __init__(self, lo: int, hi: int, remaining: int):
        self.lo, self.hi, self.remaining = lo, hi, remaining
        self.late: set = set()


def sequence_check(seqs: Sequence[int], kbd_counts: Sequence[int],
                   max_holes: int = 4096) -> SequenceResult:
    """Find gaps, duplicates and reordering in the received stats reports.

    seq counts every report on the IN endpoint (IDs 1 and 2), so between two consecutive stats
    reports it advances by 1 plus the number of keyboard reports sent in between, which the
    kbd_count field tells. Anything more is reports the host did not deliver to this reader:
    a hole. A report that arrives after a higher seq fills its hole if it lies in one (it was
    late: out of order, and no longer missing), and is a duplicate otherwise (that seq had
    already arrived). Both inputs may wrap at 2^32. The newest max_holes holes are tracked; a
    late report older than all of them counts as out of order.
    """
    n = len(seqs)
    if n != len(kbd_counts):
        raise ValueError("seqs and kbd_counts differ in length")
    if n == 0:
        return SequenceResult(0, 0, 0, 0, 0, 0, 0, 0)
    gaps = missing = dups = ooo = mismatch = 0
    holes: deque = deque()  # ordered by lo (seqs only grow at the top)
    los: deque = deque()  # holes' lo values, for bisect
    forgotten = False  # holes dropped from the front
    pairs = zip(iter_unwrap(seqs), iter_unwrap(kbd_counts))
    s0, k0 = next(pairs)
    s_top, k_top = s0, k0  # the highest seq so far, and its keyboard count
    for s, k in pairs:
        d = s - s_top
        if d > 0:
            extra = d - 1 - (k - k_top)
            if extra > 0:
                gaps += 1
                missing += extra
                holes.append(_Hole(s_top, s, extra))
                los.append(s_top)
                if len(holes) > max_holes:
                    holes.popleft()
                    los.popleft()
                    forgotten = True
            elif extra < 0:
                mismatch += 1
            s_top, k_top = s, k
        elif d == 0:
            dups += 1
        else:
            i = bisect.bisect_left(los, s) - 1  # the last hole with lo < s
            hole = holes[i] if i >= 0 else None
            if hole is not None and s < hole.hi and s not in hole.late and hole.remaining > 0:
                hole.late.add(s)
                hole.remaining -= 1
                missing -= 1
                ooo += 1
                if hole.remaining == 0:
                    gaps -= 1
                    del holes[i]
                    del los[i]
            elif s < s0 or (forgotten and (not los or s < los[0])):
                ooo += 1  # older than anything tracked: cannot tell late from duplicate
            else:
                dups += 1
    return SequenceResult(
        received=n,
        gaps=gaps,
        missing=missing,
        duplicates=dups,
        out_of_order=ooo,
        kbd_reports=k_top - k0,
        kbd_mismatch=mismatch,
        span=s_top - s0 + 1,
    )


@dataclass
class DeviceIntervals:
    interval_counts: Counter  # {cycles: count}, completion-to-completion, consecutive only
    skipped_pairs: int  # pairs whose done_seq advanced by more than 1 (or went back)
    repeated: int  # pairs that report the same completion (queue priming, retries)
    completions: int  # done_seq advance over the run
    seconds: float  # device clock, first to last reported completion


def device_intervals(done_seqs: Sequence[int], t_dones: Sequence[int],
                     cpu_hz: int) -> DeviceIntervals:
    """Completion intervals from the firmware's stamps.

    Each stats report carries the seq and the cycle count of the latest completion when it was
    built. Where two consecutive received reports name consecutive completions, the difference of
    their stamps is one completion interval. Both inputs may wrap at 2^32.
    """
    n = len(done_seqs)
    if n != len(t_dones):
        raise ValueError("done_seqs and t_dones differ in length")
    if n < 2:
        return DeviceIntervals(Counter(), 0, 0, 0, 0.0)
    counts: Counter = Counter()
    skipped = repeated = 0
    pairs = zip(iter_unwrap(done_seqs), iter_unwrap(t_dones))
    d0, t0 = next(pairs)
    dp, tp = d0, t0
    for d, t in pairs:
        dseq = d - dp
        if dseq == 1:
            counts[t - tp] += 1
        elif dseq == 0:
            repeated += 1
        else:
            skipped += 1
        dp, tp = d, t
    return DeviceIntervals(
        interval_counts=counts,
        skipped_pairs=skipped,
        repeated=repeated,
        completions=dp - d0,
        seconds=(tp - t0) / float(cpu_hz),
    )


@dataclass
class FrameResult:
    available: bool
    unit: str  # "microframe", "frame" or "unknown"
    rate_per_s: Optional[float]  # FNSOF advance per device second
    span: int  # FNSOF advance, first to last reported completion
    completions: int
    missed: Optional[int]  # microframes without a completion (only when unit is microframe)


def frame_check(fn_dones: Sequence[int], done_seqs: Sequence[int], seconds: float,
                expected_per_s: float = 1e6 / NOMINAL_US) -> FrameResult:
    """Count microframes in which no report completed, from OTG_HS DSTS.FNSOF.

    The firmware reads the register in its completion callback (opt-in: CONFIG_HID8K_FRAME_NUMBER).
    Over the run, the frame counter's advance minus the completions' advance is the number of
    (micro)frames that had none. Callback latency moves the two end readings by about one each, so
    allow a tolerance of 2. Whether the 14-bit field counts 125 us microframes or 1 ms frames at high
    speed is taken from its measured rate, not assumed (RM0456 was not read for this).
    """
    if len(fn_dones) < 2 or seconds <= 0:
        return FrameResult(False, "unknown", None, 0, 0, None)
    fn = _first_last(iter_unwrap(fn_dones, FN_MODULO))
    ds = _first_last(iter_unwrap(done_seqs))
    span = fn[1] - fn[0]
    completions = ds[1] - ds[0]
    rate = span / seconds
    if abs(rate - expected_per_s) <= 0.01 * expected_per_s:
        unit = "microframe"
    elif abs(rate - expected_per_s / 8.0) <= 0.01 * expected_per_s / 8.0:
        unit = "frame"
    else:
        unit = "unknown"
    missed = span - completions if unit == "microframe" else None
    return FrameResult(True, unit, rate, span, completions, missed)


def _first_last(it: Iterable[int]) -> tuple:
    first = last = None
    for v in it:
        if first is None:
            first = v
        last = v
    return first, last


def host_interval_counts(arrival_ns: Sequence[int], bin_ns: int = 100) -> Counter:
    """{bin: count} of host arrival intervals, binned to bin_ns (default 0.1 us)."""
    counts: Counter = Counter()
    it = iter(arrival_ns)
    prev = next(it, None)
    for t in it:
        counts[(t - prev) // bin_ns] += 1
        prev = t
    return counts


class Recorder:
    """Keeps the fields the analysis needs from each stats report, compactly (35 B/report).

    Pure: give it each report's bytes and the host's arrival time in nanoseconds.
    """

    def __init__(self, warmup_s: float = 1.0):
        self.warmup_ns = int(warmup_s * 1e9)
        self.first_arrival_ns: Optional[int] = None
        self.seq = array("I")
        self.t_submit = array("I")
        self.done_seq = array("I")
        self.t_done = array("I")
        self.submit_cost = array("I")
        self.kbd_count = array("I")
        self.fn_done = array("H")
        self.flags = array("B")
        self.arrival_ns = array("q")
        self.first: Optional[StatsReport] = None
        self.last: Optional[StatsReport] = None
        self.discarded_warmup = 0
        self.kbd_reports_seen = 0
        self.other_reports = 0
        self.bad_reports = 0
        self.bad_examples: list = []

    def add(self, data: bytes, arrival_ns: int) -> None:
        if not data:
            return
        if self.first_arrival_ns is None:
            self.first_arrival_ns = arrival_ns
        rid = data[0]
        if rid == REPORT_ID_KBD:
            # Seen on Linux hidraw, which carries every report ID of the interface.
            self.kbd_reports_seen += 1
            return
        if rid != REPORT_ID_STATS:
            self.other_reports += 1
            return
        if arrival_ns - self.first_arrival_ns < self.warmup_ns:
            self.discarded_warmup += 1
            return
        try:
            r = parse_stats(bytes(data))
        except ValueError as exc:
            self.bad_reports += 1
            if len(self.bad_examples) < 5:
                self.bad_examples.append(str(exc))
            return
        if self.first is None:
            self.first = r
        self.last = r
        self.seq.append(r.seq)
        self.t_submit.append(r.t_submit)
        self.done_seq.append(r.done_seq)
        self.t_done.append(r.t_done)
        self.submit_cost.append(r.submit_cost)
        self.kbd_count.append(r.kbd_count)
        self.fn_done.append(r.fn_done)
        self.flags.append(r.flags)
        self.arrival_ns.append(arrival_ns)

    def __len__(self) -> int:
        return len(self.seq)


@dataclass
class Criteria:
    """Pass criteria (README, "Pass criteria"). Defaults are the gate's."""

    min_duration_s: float = 600.0
    min_rate: float = 7990.0  # reports/s, averaged over the run
    max_seq_gaps: int = 0
    max_duplicates: int = 0
    max_out_of_order: int = 0
    max_p999_us: float = 2 * NOMINAL_US  # device-side completion interval, 99.9th percentile
    max_refused: int = 0
    max_busy: int = 0
    fn_tolerance: int = 2  # strict check with frame numbers: end-reading tolerance
    min_cdc_lines_per_s: float = 0.9  # with --cdc: the stats lines (1/s by default) kept coming
    # Device clock sanity: the cycle-count span and the uptime span of the run must agree
    # within this fraction plus 10 ms (the uptime's millisecond steps). Both run from HCLK, so
    # a mismatch means the DWT counter stopped or cpu_hz is wrong, not jitter.
    max_clock_mismatch: float = 0.001


def _us(cycles: float, cpu_hz: int) -> float:
    return cycles * 1e6 / cpu_hz


def _scale(d: dict, f) -> dict:
    return {k: (f(v) if (k != "n" and v is not None) else v) for k, v in d.items()}


def analyze(rec: Recorder, criteria: Optional[Criteria] = None,
            cdc: Optional[dict] = None, reader_error: Optional[str] = None) -> dict:
    """Judge a recorded run. Returns a JSON-serialisable dict.

    cdc is the CDC logger's result (hid8k_measure.py --cdc): the lines and bytes the host read
    from the firmware's console during the run. Without it, CDC activity is not checked here.
    reader_error is set when reading stopped on an error (the device went away): the run fails.
    """
    c = criteria or Criteria()
    n = len(rec)
    result: dict = {
        "reports_received": n,
        "warmup_discarded": rec.discarded_warmup,
        "keyboard_reports_seen": rec.kbd_reports_seen,
        "other_reports": rec.other_reports,
        "bad_reports": rec.bad_reports,
        "bad_examples": list(rec.bad_examples),
        "reader_error": reader_error,
    }
    if n < 2 or rec.first is None or rec.last is None:
        result["verdict"] = "NO-DATA"
        result["strict"] = "UNKNOWN"
        result["criteria"] = []
        return result

    first, last = rec.first, rec.last
    cpu_hz = first.cpu_hz or 160_000_000
    host_seconds = (rec.arrival_ns[-1] - rec.arrival_ns[0]) / 1e9

    us_per_cycle = 1e6 / cpu_hz
    seq = sequence_check(rec.seq, rec.kbd_count)
    dev = device_intervals(rec.done_seq, rec.t_done, cpu_hz)
    dev_desc = describe_counts(dev.interval_counts, us_per_cycle)
    host_bins = host_interval_counts(rec.arrival_ns, 100)
    host_desc = describe_counts(host_bins, 0.1)
    cost = describe_counts(Counter(rec.submit_cost))

    flags_all = 0xFF
    flags_any = 0
    heavy = 0
    for f in rec.flags:
        flags_all &= f
        flags_any |= f
        heavy += 1 if f & FLAG_CDC_HEAVY else 0
    high_speed = bool(flags_all & FLAG_HIGH_SPEED)
    fn_ok = bool(flags_all & FLAG_FN_VALID)

    frames = (frame_check(rec.fn_done, rec.done_seq, dev.seconds) if fn_ok
              else FrameResult(False, "unknown", None, 0, 0, None))

    deltas = {
        name: counter_delta(getattr(first, name), getattr(last, name))
        for name in ("refused", "busy", "late", "kbd_count", "cdc_bytes", "cdc_dropped")
    }
    device_rate = dev.completions / dev.seconds if dev.seconds > 0 else 0.0
    host_rate = (n - 1) / host_seconds if host_seconds > 0 else 0.0
    device_uptime_s = counter_delta(first.uptime_ms, last.uptime_ms) / 1e3
    clock_diff_s = abs(dev.seconds - device_uptime_s)
    clock_limit_s = c.max_clock_mismatch * device_uptime_s + 0.01

    result.update({
        "cpu_hz": cpu_hz,
        "queue_depth": first.depth,
        "high_speed": high_speed,
        "frame_numbers": fn_ok,
        "cdc_mode": ("heavy" if heavy == n else "normal" if heavy == 0 else "mixed"),
        "cdc_heavy_fraction": heavy / n,
        "host_seconds": host_seconds,
        "device_seconds": dev.seconds,
        "device_uptime_seconds": device_uptime_s,
        "device_clock_mismatch_s": clock_diff_s,
        "device": {
            "completion_rate_per_s": device_rate,
            "completions": dev.completions,
            "intervals_us": dev_desc,
            "intervals_above_late_us": count_above(dev.interval_counts, LATE_US / us_per_cycle),
            "intervals_above_2x_us": count_above(dev.interval_counts,
                                                 2 * NOMINAL_US / us_per_cycle),
            "pairs_skipped": dev.skipped_pairs,
            "pairs_repeated": dev.repeated,
            "counter_deltas": deltas,
            "cdc_bytes_per_s": deltas["cdc_bytes"] / device_uptime_s if device_uptime_s else 0.0,
            "submit_cost_cycles": cost,
            "submit_cost_us": _scale(cost, lambda v: _us(v, cpu_hz)),
            "max_interval_since_reset_us": _us(last.max_interval, cpu_hz),
        },
        "host": {
            "receive_rate_per_s": host_rate,
            "sequence": {
                "received": seq.received,
                "span": seq.span,
                "gaps": seq.gaps,
                "missing": seq.missing,
                "duplicates": seq.duplicates,
                "out_of_order": seq.out_of_order,
                "keyboard_reports": seq.kbd_reports,
                "keyboard_mismatch": seq.kbd_mismatch,
            },
            "arrival_intervals_us": host_desc,
            "arrival_bin_us": 0.1,
            "arrivals_within_20us": sum(c for b, c in host_bins.items() if b < 200),
            "caveat": ("User-space arrival times: the host controller, its driver, the HID class "
                       "driver and the scheduler batch and delay reports. NOT bus timing; use "
                       "usbmon/Wireshark (Linux) or a USB analyser for that."),
        },
        "frames": {
            "available": frames.available,
            "unit": frames.unit,
            "rate_per_s": frames.rate_per_s,
            "span": frames.span,
            "completions": frames.completions,
            "missed_microframes": frames.missed,
        },
    })

    checks = []

    def check(name, ok, value, limit, text):
        checks.append({"name": name, "pass": bool(ok), "value": value, "limit": limit,
                       "text": text})

    check("duration", host_seconds >= c.min_duration_s, round(host_seconds, 3),
          c.min_duration_s, "run length (host clock, after warm-up) >= limit, s")
    check("reader", reader_error is None, reader_error or "ok", "ok",
          "the host read the device until the end of the run")
    check("device_clock", clock_diff_s <= clock_limit_s, round(clock_diff_s, 4),
          round(clock_limit_s, 4),
          "cycle-count span vs uptime span of the run, s (DWT running, cpu_hz right)")
    check("high_speed", high_speed, high_speed, True,
          "every report says the bus enumerated at high speed")
    check("device_rate", device_rate >= c.min_rate, round(device_rate, 2), c.min_rate,
          "completions per second on the device clock >= limit")
    check("host_rate", host_rate >= c.min_rate, round(host_rate, 2), c.min_rate,
          "stats reports received per second on the host clock >= limit")
    check("seq_gaps", seq.gaps <= c.max_seq_gaps and seq.kbd_mismatch == 0, seq.gaps,
          c.max_seq_gaps, "places where the host did not deliver reports to this reader")
    check("duplicates", seq.duplicates <= c.max_duplicates, seq.duplicates, c.max_duplicates,
          "the same report received twice")
    check("out_of_order", seq.out_of_order <= c.max_out_of_order, seq.out_of_order,
          c.max_out_of_order, "reports received out of order")
    p999 = dev_desc["p999"]
    check("device_p999", p999 is not None and p999 <= c.max_p999_us,
          None if p999 is None else round(p999, 3), c.max_p999_us,
          "device-side completion interval, 99.9th percentile, us")
    check("refused", deltas["refused"] <= c.max_refused, deltas["refused"], c.max_refused,
          "hid_device_submit_report calls that returned an error during the run")
    check("busy", deltas["busy"] <= c.max_busy, deltas["busy"], c.max_busy,
          "times the firmware could not submit (no free buffer, bus marked suspended)")
    if cdc is not None:
        lines = 0 if cdc.get("error") else int(cdc.get("stats_lines", 0))
        need = math.floor(c.min_cdc_lines_per_s * host_seconds)
        check("cdc_active", lines >= need, lines, need,
              "stats lines the host read from the CDC console during the run")
        if cdc.get("mode") == "heavy":
            check("cdc_heavy", result["cdc_mode"] == "heavy", result["cdc_mode"], "heavy",
                  "every report says heavy CDC traffic was on")
        result["cdc_checked"] = True
    else:
        result["cdc_checked"] = False
    result["criteria"] = checks

    failed = [x["name"] for x in checks if not x["pass"]]
    if not failed:
        result["verdict"] = "PASS"
    elif failed == ["duration"]:
        result["verdict"] = "INCOMPLETE"
    else:
        result["verdict"] = "FAIL"
    result["failed"] = failed

    # Strict: SPEC section 10's proposal, "no missed microframes in the run".
    if frames.available and frames.unit == "microframe" and frames.missed is not None:
        strict_ok = frames.missed <= c.fn_tolerance
        result["strict_basis"] = (f"frame numbers: {frames.missed} microframes without a "
                                  f"completion (tolerance {c.fn_tolerance})")
    else:
        strict_ok = deltas["late"] == 0
        result["strict_basis"] = (f"firmware late counter: {deltas['late']} completion intervals "
                                  f"> {LATE_US} us (can over-count: it includes the device's own "
                                  "callback latency)")
    result["strict"] = "PASS" if (strict_ok and result["verdict"] == "PASS") else (
        "FAIL" if not strict_ok else "UNKNOWN")
    return result


def _f(v, fmt="{:.1f}") -> str:
    return "-" if v is None else fmt.format(v)


def format_summary(result: dict, header: Sequence[str] = ()) -> str:
    """A one-screen text summary of analyze()'s result."""
    lines = list(header)
    lines.append(f"reports received {result.get('reports_received', 0):,}, warm-up discarded "
                 f"{result.get('warmup_discarded', 0)}, keyboard reports seen "
                 f"{result.get('keyboard_reports_seen', 0)}, bad {result.get('bad_reports', 0)}")
    if result.get("reader_error"):
        lines.append(f"reader  STOPPED: {result['reader_error']}")
    if result.get("verdict") == "NO-DATA":
        lines.append("VERDICT: NO-DATA (fewer than two stats reports received)")
        return "\n".join(lines)
    d, h, fr = result["device"], result["host"], result["frames"]
    iv, ha, sq = d["intervals_us"], h["arrival_intervals_us"], h["sequence"]
    cd = d["counter_deltas"]
    cost = d["submit_cost_cycles"]
    lines += [
        f"run {result['host_seconds']:.1f} s host / {result['device_seconds']:.1f} s device, "
        f"{'high' if result['high_speed'] else 'FULL'} speed, queue depth {result['queue_depth']}, "
        f"CDC mode {result['cdc_mode']} ({d['cdc_bytes_per_s'] / 1e3:.1f} kB/s queued, "
        f"{cd['cdc_dropped']} B dropped)",
        f"device  completions {d['completion_rate_per_s']:.2f}/s; interval us min {_f(iv['min'])} "
        f"mean {_f(iv['mean'], '{:.2f}')} p99 {_f(iv['p99'])} p99.9 {_f(iv['p999'])} "
        f"max {_f(iv['max'])}",
        f"        >187.5 us {d['intervals_above_late_us']}, >250 us {d['intervals_above_2x_us']}; "
        f"counters during run: late +{cd['late']} refused +{cd['refused']} busy +{cd['busy']} "
        f"kbd +{cd['kbd_count']}",
        f"        submit cost cycles min {_f(cost['min'], '{:.0f}')} mean "
        f"{_f(cost['mean'], '{:.0f}')} p99 {_f(cost['p99'], '{:.0f}')} max "
        f"{_f(cost['max'], '{:.0f}')} (us: mean {_f(d['submit_cost_us']['mean'], '{:.2f}')}, "
        f"max {_f(d['submit_cost_us']['max'], '{:.2f}')})",
        f"host    received {h['receive_rate_per_s']:.2f}/s; seq gaps {sq['gaps']} "
        f"({sq['missing']} missing), duplicates {sq['duplicates']}, out of order "
        f"{sq['out_of_order']}",
        f"        arrival interval us min {_f(ha['min'])} p50 {_f(ha['p50'])} p99 {_f(ha['p99'])} "
        f"p99.9 {_f(ha['p999'])} max {_f(ha['max'])}; {h['arrivals_within_20us']} within 20 us",
        "        (user-space arrival times are batched by the host stack: NOT bus timing)",
    ]
    if fr["available"]:
        lines.append(f"frames  FNSOF unit {fr['unit']} ({_f(fr['rate_per_s'], '{:.1f}')}/s), "
                     f"missed microframes {fr['missed_microframes']}")
    else:
        lines.append("frames  not available (CONFIG_HID8K_FRAME_NUMBER off: the USB stack does "
                     "not expose the frame number)")
    if not result.get("cdc_checked"):
        lines.append("cdc     NOT CHECKED by this tool: the run counts only if a terminal logged the "
                     "CDC console throughout")
    lines.append("criteria:")
    for x in result["criteria"]:
        lines.append(f"  {'PASS' if x['pass'] else 'FAIL'}  {x['name']:<13} {x['value']!s:>12} "
                     f"(limit {x['limit']})  {x['text']}")
    lines.append(f"VERDICT: {result['verdict']}" + (
        f" (failed: {', '.join(result['failed'])})" if result.get("failed") else ""))
    lines.append(f"strict (SPEC 10, no missed microframes): {result['strict']}: "
                 f"{result['strict_basis']}")
    return "\n".join(lines)
