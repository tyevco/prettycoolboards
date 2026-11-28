"""The run's record: report.json (everything, for tools), report.md (for people), transcript.log (every line).

Each run goes into its own directory, <out>/<board serial>/<UTC timestamp>/, so runs never overwrite each other.
The record carries the board serial the operator typed, the coupon serials read from their descriptors, the
firmware's identity (tb info), and the git commit (and whether the checkout had local changes) of the harness and
the limits it judged against.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import pathlib
import re
import subprocess

from . import PROTOCOL_VERSION, __version__
from . import limits as L

MARK = {"pass": "pass", "warn": "WARN", "fail": "FAIL", "danger": "DANGER", "error": "ERROR", "skipped": "skipped",
        "not_run": "not run", "info": "info", "skip": "skip"}


def git_state(repo=L.REPO):
    """(commit, dirty) of the checkout, read-only; (None, None) outside a git checkout."""
    try:
        head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True,
                              timeout=10, check=True).stdout.strip()
        st = subprocess.run(["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=no"],
                            capture_output=True, text=True, timeout=10, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return None, None
    return head, bool(st.strip())


def sha256_of(paths):
    """One SHA-256 over these files' names and bytes (sorted), or None if one cannot be read. It pins what a run
    judged with even when git cannot: an untracked or locally changed file, a --nets from elsewhere."""
    h = hashlib.sha256()
    try:
        for p in sorted(pathlib.Path(x) for x in paths):
            h.update(p.name.encode() + b"\0" + p.read_bytes() + b"\0")
    except OSError:
        return None
    return h.hexdigest()


def harness_files():
    return sorted([*(L.HERE.glob("*.py")), L.HERE.parent / "bench.py"])


def _rel(p):
    try:
        return str(pathlib.Path(p).resolve().relative_to(L.REPO))
    except ValueError:
        return str(p)


def _safe(name):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(name)) or "unknown"


def to_dict(run, transcript=None):
    head, dirty = git_state()
    nets = run.config.get("nets_path") or str(L.NETS_PATH)
    d = {
        "harness": {"name": "tbbench", "version": __version__, "protocol": PROTOCOL_VERSION,
                    "git_commit": head, "git_dirty": dirty, "git_dirty_ignores": "untracked files",
                    "sources_sha256": sha256_of(harness_files()),
                    "nets": _rel(nets), "nets_sha256": sha256_of([nets])},
        "board_serial": run.config.get("board_serial"),
        "started": run.started, "finished": run.finished, "verdict": run.verdict, "stop": run.stop,
        "summary": run.summary(),
        "config": run.config,
        "firmware": run.info,
        "slots": {str(k): v for k, v in run.slots.items()},
        "steps": [dataclasses.asdict(s) for s in run.steps],
        "events": run.events,
        "honesty": "Readings judged by tbbench against limits from SPEC, nets.py and datasheets. Limits marked "
                   "'harness proposal' are not from SPEC. A simulated board's numbers are placeholders.",
    }
    if transcript is not None:
        d["transcript_lines"] = len(transcript)
    return d


def _fmt(v):
    """A table cell: no "|" (it would split the row) and no line break (it would end the table)."""
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.4g}"
    return " ".join(str(v).replace("|", "/").split())


def to_markdown(d):
    out = []
    w = out.append
    w(f"# Bench run: board {_fmt(d['board_serial'])}, {d['started']}")
    w("")
    w(f"**Verdict: {d['verdict']}**" + (f" (stopped: {d['stop']['reason']})" if d.get("stop") else ""))
    w("")
    if d.get("stop"):
        w(f"> {d['stop'].get('advice', '')}  ")
        w(f"> tb safe confirmed every rail off: {'yes' if d['stop'].get('safe') else 'NO'}")
        w("")
    fw = d.get("firmware") or {}
    h = d["harness"]
    cfg = d["config"]
    w("| | |")
    w("|---|---|")
    w(f"| Board serial | {_fmt(d['board_serial'])} |")
    w(f"| Harness | tbbench {h['version']}, protocol {h['protocol']}, git {h['git_commit'] or 'unknown'}"
      f"{' (local changes)' if h['git_dirty'] else ''}, sources sha256 {(h.get('sources_sha256') or '?')[:16]} |")
    w(f"| Judged against | {_fmt(h['nets'])}, sha256 {(h.get('nets_sha256') or '?')[:16]} |")
    w(f"| Firmware | {_fmt(fw.get('fw', '?'))} proto={_fmt(fw.get('proto', '?'))} map={_fmt(fw.get('map', '?'))} "
      f"nets_rev={_fmt(fw.get('nets_rev', '?'))} zephyr={_fmt(fw.get('zephyr', '?'))} "
      f"bench_build={_fmt(fw.get('bench_build', '?'))} |")
    w(f"| Power, console, port | {cfg.get('power')}, {cfg.get('console')}, {_fmt(cfg.get('port')) or '-'} |")
    w(f"| Source declared / read | {cfg.get('source') or '-'} / {fw.get('source', '-')}, budget "
      f"{fw.get('budget_ma', '-')} mA |")
    w(f"| Options | loads={cfg.get('loads')} climit={cfg.get('climit')} meter={cfg.get('meter')} "
      f"nrst={cfg.get('nrst')} inj={cfg.get('inj')} key_check={cfg.get('key_check')} "
      f"turned_test={cfg.get('turned_test') or '-'} |")
    decl = cfg.get("coupons") or {}
    w(f"| Coupons declared | {_fmt(', '.join(f'S{k}={v}' for k, v in sorted(decl.items())) or '-')} (others: "
      f"{_fmt(cfg.get('coupon'))}); stage A1 (SPEC §1, D1 of 2026-11-27) |")
    if cfg.get("operator_name"):
        w(f"| Operator | {_fmt(cfg['operator_name'])} |")
    if cfg.get("notes"):
        w(f"| Notes | {_fmt(cfg['notes'])} |")
    w(f"| Started, finished (UTC) | {d['started']}, {d['finished']} |")
    w("")
    w("## Steps")
    w("")
    w("| Step | Result | Failed or notable checks |")
    w("|---|---|---|")
    for s in d["steps"]:
        bad = [c for c in s["checks"] if c["verdict"] in ("fail", "danger", "warn")]
        note = "; ".join(f"{c['name']}: {_fmt(c['measured'])}" + (f" (want {_fmt(c['limit'])})" if c['limit'] else "")
                         for c in bad[:4])
        if len(bad) > 4:
            note += f"; and {len(bad) - 4} more"
        if not note and s["notes"]:
            note = "; ".join(s["notes"])
        w(f"| {s['id']}: {_fmt(s['title'])} | {MARK.get(s['status'], s['status'])} | {_fmt(note)} |")
    w("")
    if d["slots"]:
        w("## Per slot")
        w("")
        w("| Slot | Coupon | Serial | Idle +3V3 | Series R | Lanes (ppm of VREF+) | INJ lift on AN0 | "
          "climit3 / climit5 | Descriptor of record |")
        w("|---|---|---|---|---|---|---|---|---|")
        for k, v in sorted(d["slots"].items()):
            lanes = v.get("lanes_ppm") or {}
            rec = v.get("descriptor_record") or {}
            recs = "-" if not rec else ("valid" if rec.get("valid") else "INVALID") + \
                (" (powered on it: nodesc)" if v.get("nodesc_line") else "")
            w(f"| S{k} | {_fmt(v.get('coupon_type', '-'))} {_fmt(v.get('coupon_rev', ''))} | "
              f"{_fmt(v.get('coupon_serial', '-'))} | "
              f"{_fmt(v.get('idle_3v3_ua'))} uA at {_fmt(v.get('idle_3v3_mv'))} mV | "
              f"{_fmt(v.get('series_mohm'))} mOhm | {' / '.join(str(lanes[x]) for x in sorted(lanes))} | "
              f"{(_fmt(v['inj_lift_mv']) + ' mV') if v.get('inj_lift_mv') is not None else '-'} | "
              f"{_fmt(v.get('climit3_ma'))} / {_fmt(v.get('climit5_ma'))} mA | {_fmt(recs)} |")
        w("")
    w("## Every check")
    w("")
    for s in d["steps"]:
        w(f"### {s['id']}: {s['title']} ({MARK.get(s['status'], s['status'])})")
        w("")
        if s["spec"]:
            w(f"{s['spec']}. Commands: {', '.join('`' + c + '`' for c in s['commands']) or 'none'}.")
            w("")
        if s["checks"]:
            w("| Check | Verdict | Measured | Limit | Source |")
            w("|---|---|---|---|---|")
            for c in s["checks"]:
                unit = f" {c['unit']}" if c["unit"] and c["measured"] is not None else ""
                detail = f" ({c['detail']})" if c["detail"] and c["verdict"] != "pass" else ""
                w(f"| {_fmt(c['name'])} | {MARK.get(c['verdict'], c['verdict'])} | {_fmt(c['measured'])}{unit} | "
                  f"{_fmt(c['limit'])} | {_fmt(c['ref'])}{_fmt(detail)} |")
            w("")
        for n in s["notes"]:
            w(f"* {n}")
        if s["notes"]:
            w("")
    w("---")
    w("")
    w(d["honesty"])
    w("")
    return "\n".join(out)


def write(run, out_dir, transcript=None):
    """Write the run's three files; return the directory."""
    d = to_dict(run, transcript)
    stamp = run.started.replace(":", "").replace("+0000", "Z").replace("+00:00", "Z")
    base = pathlib.Path(out_dir) / _safe(d["board_serial"]) / _safe(stamp)
    n = 1
    target = base
    while target.exists():
        n += 1
        target = base.with_name(f"{base.name}-{n}")
    target.mkdir(parents=True)
    (target / "report.json").write_text(json.dumps(d, indent=2, default=str) + "\n", encoding="utf-8", newline="\n")
    (target / "report.md").write_text(to_markdown(d), encoding="utf-8", newline="\n")
    if transcript is not None:
        lines = [f"{t:10.4f} {direction} {text}" for t, direction, text in transcript]
        (target / "transcript.log").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return target
