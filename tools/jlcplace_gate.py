"""Release gate around jlcplace (https://github.com/tyevco/jlcplace), the JLCPCB placement (CPL) checker.

jlcplace puts JLC's own EasyEDA footprint down exactly where each CPL row tells JLC to put it, over the Gerbers that
are ordered, and reports which KiCad pad and net every EasyEDA pad lands on (red: off copper, on another pin's net, a
pinout no rotation fixes, a polarity that needs a decision, a BOM part without a row, a CPL from another origin than
the Gerbers ...; yellow: probably fine, look in JLC's preview). The release flow calls it twice per board:

    jlcplace cpl   BOARD --db DB --bom BOM --gerbers GERBERS -o CPL          # write the rows (refuses on red)
    jlcplace check BOARD CPL --db DB --bom BOM --gerbers GERBERS \
                   --report jlcplace-report.html --checklist jlcplace-checklist.md --json ...

and refuses the package on any red row or red run finding. The yellow rows and the preview checklist are copied into
ORDER-NOTES.md by `order_lines()`. A second `jlcplace check` without --db cross-checks the stored corrections
against the EasyEDA records (`db_overrides()`): a stored auto correction may not turn a red row green.

Only `fetch` (and `refit()`, which calls it) uses the network: `cpl` and `check` read the EasyEDA record cache
(~/.cache/jlcplace) and the committed correction database (--db), which holds derived numbers only (rot, dx, dy,
verdicts, verifications), never EasyEDA geometry. The HTML report draws EasyEDA pad outlines (JLCEDA/EasyEDA Official
Library, https://lceda.cn/, https://easyeda.com): it is for your own review and is git-ignored, never published.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys

MIN_VERSION = (0, 2, 1)
RC_CLEAN, RC_YELLOW, RC_RED = 0, 1, 2


class JlcplaceError(RuntimeError):
    """jlcplace could not run (bad input, internal error, missing tool): not a verdict."""


def exe():
    """The jlcplace executable: $JLCPLACE, else next to this Python (the venv), else on PATH."""
    env = os.environ.get("JLCPLACE")
    if env:
        return env
    cand = os.path.join(os.path.dirname(sys.executable), "jlcplace")
    if os.path.exists(cand):
        return cand
    found = shutil.which("jlcplace")
    if found:
        return found
    raise JlcplaceError("jlcplace not found: `pip install -e ~/jlcplace` into this Python's venv, or set JLCPLACE")


def _run(args, timeout=1800):
    return subprocess.run([exe(), *args], capture_output=True, text=True, timeout=timeout)


def version():
    """'jlcplace 0.2.1' -> (0, 2, 1); refuses an older jlcplace than MIN_VERSION."""
    r = _run(["--version"], timeout=60)
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", r.stdout + r.stderr)
    if r.returncode != 0 or not m:
        raise JlcplaceError(f"jlcplace --version failed: {(r.stdout + r.stderr).strip()[-300:]}")
    v = tuple(int(x) for x in m.groups())
    if v < MIN_VERSION:
        raise JlcplaceError(f"jlcplace {'.'.join(map(str, v))} is older than {'.'.join(map(str, MIN_VERSION))}")
    return v


def _board_args(bom=None, gerbers=None, db=None):
    args = []
    if bom:
        args += ["--bom", bom]
    if gerbers:
        args += ["--gerbers", gerbers]
    if db:
        args += ["--db", db]
    return args


def refit(pcb, db, bom=None):
    """Download the EasyEDA records the cache lacks (network, rate-limited) and store fitted corrections in db.

    Verified and manual entries in db keep their numbers (jlcplace never refits over a verification)."""
    out = []
    r = _run(["fetch", pcb] + (["--bom", bom] if bom else []))
    out.append(r.stdout + r.stderr)
    if r.returncode not in (RC_CLEAN,):
        raise JlcplaceError(f"jlcplace fetch failed (exit {r.returncode}): {out[-1].strip()[-600:]}")
    r = _run(["fit", pcb, "--db", db, "-q"])
    out.append(r.stdout + r.stderr)
    if r.returncode not in (RC_CLEAN, RC_RED):  # a red fit is reported again, row by row, by cpl/check
        raise JlcplaceError(f"jlcplace fit failed (exit {r.returncode}): {out[-1].strip()[-600:]}")
    return "".join(out)


def write_cpl(pcb, out_csv, bom=None, gerbers=None, db=None, force=False):
    """`jlcplace cpl`: the rows written from the Gerbers' (0, 0). Returns (red, output); with red and not force, no
    file is written (jlcplace leaves an existing one unchanged, so the caller removes it first)."""
    if os.path.exists(out_csv):
        os.remove(out_csv)
    r = _run(["cpl", pcb, "-o", out_csv, "-q"] + _board_args(bom, gerbers, db) + (["--force"] if force else []))
    text = r.stdout + r.stderr
    if r.returncode not in (RC_CLEAN, RC_RED):
        raise JlcplaceError(f"jlcplace cpl failed (exit {r.returncode}): {text.strip()[-600:]}")
    return r.returncode == RC_RED, text


def check(pcb, cpl, json_path, bom=None, gerbers=None, db=None, report=None, checklist=None):
    """`jlcplace check`. Returns a dict: the JSON results plus 'rc', 'text' (the terminal summary), 'summary_line'
    and 'red' (True when anything is red: a row, or a finding about the whole run such as an origin mismatch)."""
    args = ["check", pcb, cpl, "--json", json_path] + _board_args(bom, gerbers, db)
    if report:
        args += ["--report", report]
    if checklist:
        args += ["--checklist", checklist]
    r = _run(args)
    text = r.stdout + r.stderr
    if r.returncode not in (RC_CLEAN, RC_YELLOW, RC_RED) or not os.path.exists(json_path):
        raise JlcplaceError(f"jlcplace check failed (exit {r.returncode}): {text.strip()[-600:]}")
    with open(json_path, encoding="utf-8") as f:
        res = json.load(f)
    res["rc"] = r.returncode
    res["text"] = text
    m = re.search(r"^\d+ results:.*$", text, re.M)
    res["summary_line"] = m.group(0).strip() if m else _summary_line(res.get("summary", {}))
    res["red"] = is_red(res)
    return res


HUMAN = ("manual", "preview-verified", "board-verified")


def db_overrides(res_db, res_records):
    """Cross-check of the database against the EasyEDA records.

    `check --db` simulates a row with the stored correction and accepts what that correction accepts. A stored *auto*
    correction (fitted, never looked at by a person) that disagrees with what the records fit now is not caught by
    it: jlcplace 0.2.1 then calls a row that puts pins on other nets green ("numbering accepted by the correction
    (auto)"). So the gate also checks the CPL without --db, and a row that is red there although its record was at
    hand must owe its --db verdict to a human decision (manual, preview- or board-verified); otherwise it is red.

    Returns (problems, accepted): one line each; accepted rows are listed in ORDER-NOTES."""
    by_ref = {r.get("ref"): r for r in res_db.get("results", [])}
    problems, accepted = [], []
    for r in res_records.get("results", []):
        if r.get("verdict") != "red" or not (r.get("easyeda") or {}).get("found"):
            continue  # not simulated without the record: the --db run is the only judge of that row
        d = by_ref.get(r.get("ref")) or {}
        corr = d.get("correction") or {}
        why = " / ".join(r.get("messages", []))
        if d.get("verdict") == "red":
            continue  # already red in the --db run
        if corr.get("source") == "db" and corr.get("status") in HUMAN:
            accepted.append(f"{r.get('ref')} ({r.get('lcsc')}): {corr.get('status')} decision in the database "
                            f"accepts a row the EasyEDA records alone call red: {why}")
        else:
            problems.append(f"{r.get('ref')} ({r.get('lcsc')}, {r.get('layer')}): the database's "
                            f"{corr.get('status', '?')} correction overrides the EasyEDA record's own fit, which calls "
                            f"this row red: {why} (refit: release.py --refit-jlc, or record a decision with "
                            "jlcplace confirm)")
    return problems, accepted


def add_cross_check(res_db, res_records):
    """Fold db_overrides() into the --db results: problems make the run red, accepted rows become notes."""
    problems, accepted = db_overrides(res_db, res_records)
    res_db["db_problems"], res_db["db_accepted"] = problems, accepted
    res_db["red"] = is_red(res_db)
    return res_db


def _summary_line(s):
    return (f"{s.get('results', 0)} results: {s.get('red', 0)} red, {s.get('yellow', 0)} yellow, "
            f"{s.get('green', 0)} green, {s.get('verified', 0)} verified")


def is_red(res):
    s = res.get("summary", {})
    return (res.get("rc") == RC_RED or s.get("red", 0) > 0 or s.get("worst") == "red" or bool(res.get("db_problems"))
            or any(f.get("verdict") == "red" for f in res.get("findings", []))
            or any(r.get("verdict") == "red" for r in res.get("results", [])))


def problem_lines(res):
    """The red run findings and red rows, one line each."""
    out = [f"run ({f.get('status')}): {f.get('message')}" for f in res.get("findings", []) if f.get("verdict") == "red"]
    for r in res.get("results", []):
        if r.get("verdict") == "red":
            out.append(f"{r.get('ref')} ({r.get('lcsc')}, {r.get('layer')}): {' / '.join(r.get('messages', []))}")
    out += res.get("db_problems", [])
    return out


def order_lines(res, tool_version, checklist_name="jlcplace-checklist.md"):
    """Markdown bullets for ORDER-NOTES.md: the gate's summary, the origin, every yellow row, BOM notes and the
    preview checklist (what only JLC's placement preview can settle)."""
    v = ".".join(map(str, tool_version))
    lines = [f"* **jlcplace {v} placement gate** (JLC's EasyEDA footprints put down at every CPL row, over gerbers.zip): "
             f"{res['summary_line']}" + (" - **RED: do not order.**" if res["red"] else "")]
    origin = (res.get("origin") or {}).get("note")
    if origin:
        lines.append(f"  * origin: {origin}")
    for p in problem_lines(res):
        lines.append(f"  * RED {p}")
    for f in res.get("findings", []):
        if f.get("verdict") != "red":
            lines.append(f"  * {f.get('verdict')} run ({f.get('status')}): {f.get('message')}")
    for r in res.get("results", []):
        if r.get("verdict") == "yellow":
            lines.append(f"  * yellow {r.get('ref')} ({r.get('lcsc')}, {r.get('layer')}): "
                         f"{' / '.join(r.get('messages', []))}")
    for a in res.get("db_accepted", []):
        lines.append(f"  * accepted by a recorded decision: {a}")
    if "db_problems" in res:
        lines.append("  * cross-check without the database (EasyEDA records alone): "
                     + ("every row the records call red is red here too, or a recorded decision accepts it"
                        if not res["db_problems"] else f"{len(res['db_problems'])} stored correction(s) disagree"))
    for b in res.get("bom", []):  # BOM inconsistencies are yellow (strings in the JSON)
        lines.append(f"  * yellow BOM: {b}")
    items = res.get("checklist", [])
    if items:
        lines.append(f"* **JLC placement preview checklist** ({len(items)} item{'s' if len(items) != 1 else ''}, "
                     f"also in {checklist_name}): open the order's placement preview and tick each part when it sits "
                     "on its pads with pin 1 / polarity where the board wants it")
        for it in items:
            refs = it.get("refs") or [it.get("ref")]
            more = f" (stands for {', '.join(refs)})" if len(refs) > 1 else ""
            lines.append(f"  * [ ] {it.get('category')}: **{it.get('ref')}**{more} ({it.get('lcsc')}, "
                         f"{it.get('layer')}, rot {it.get('rotation', 0):g}): {it.get('what')}")
    else:
        lines.append(f"* JLC placement preview checklist ({checklist_name}): nothing to check")
    return lines
