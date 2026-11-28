"""The run's record: report.json, report.md and transcript.log, one directory per run."""

import json

from tbbench import report


def test_report_files(sim, tmp_path):
    s = sim(board_serial="MB-A-007", climit=True)
    run = s.go()
    d1 = report.write(run, tmp_path, s.session.transcript)
    d2 = report.write(run, tmp_path, s.session.transcript)
    assert d1 != d2 and d1.parent == d2.parent == tmp_path / "MB-A-007", "runs never overwrite each other"
    j = json.loads((d1 / "report.json").read_text())
    assert j["board_serial"] == "MB-A-007" and j["verdict"] == run.verdict
    assert j["harness"]["protocol"] == 1 and "git_commit" in j["harness"] and "git_dirty" in j["harness"]
    assert j["firmware"]["fw"] == "bringup" and j["slots"]["1"]["coupon_serial"] == 1
    assert {s["id"] for s in j["steps"]} >= {"link", "boot", "slot1.selftest", "final"}
    md = (d1 / "report.md").read_text()
    assert md.startswith("# Bench run: board MB-A-007") and f"**Verdict: {run.verdict}**" in md
    assert "| S1 | test A | 1 |" in md and "326 mOhm" in md
    log = (d1 / "transcript.log").read_text()
    assert "> tb selftest 1 all" in log and "< @tb done cmd=selftest rc=0" in log
    for f in ("report.json", "report.md", "transcript.log"):
        assert b"\r\n" not in (d1 / f).read_bytes(), f"{f}: LF line endings"


def test_stopped_report_says_so(sim, tmp_path):
    s = sim("short=+3V3_S1:400")
    run = s.go()
    md = (report.write(run, tmp_path, s.session.transcript) / "report.md").read_text()
    assert "**Verdict: STOPPED**" in md and "tb safe confirmed every rail off: yes" in md and "DANGER" in md


def test_git_state_outside_a_checkout(tmp_path):
    assert report.git_state(tmp_path) == (None, None)


def test_unsafe_serial_is_a_safe_directory(sim, tmp_path):
    s = sim(board_serial="../../etc x")
    d = report.write(s.go(), tmp_path, s.session.transcript)
    assert d.parent.parent == tmp_path and "/" not in d.parent.name and d.parent.name != ".."


def test_report_pins_what_it_judged_with(sim, tmp_path, limits):
    """git cannot describe an untracked harness or a --nets from elsewhere: the report carries SHA-256s of both."""
    import hashlib
    s = sim()
    j = json.loads((report.write(s.go(), tmp_path, s.session.transcript) / "report.json").read_text())
    h = j["harness"]
    assert h["nets"] == "keyboard/hardware/design/nets.py"
    p = limits.nets_path
    assert h["nets_sha256"] == hashlib.sha256(p.name.encode() + b"\0" + p.read_bytes() + b"\0").hexdigest()
    assert len(h["sources_sha256"]) == 64 and h["git_dirty_ignores"] == "untracked files"
    assert j["config"]["nets_path"] == str(p)


def test_other_nets_is_recorded(sim, tmp_path, limits):
    import shutil
    from tbbench import limits as L
    other = tmp_path / "nets.py"
    shutil.copy(limits.nets_path, other)
    with other.open("a") as f:
        f.write("\n# a local edit\n")
    from .conftest import Sim
    s = Sim(L.Limits(other))
    j = json.loads((report.write(s.go(), tmp_path / "out", s.session.transcript) / "report.json").read_text())
    assert j["harness"]["nets"] == str(other) and j["harness"]["nets_sha256"] != report.sha256_of([limits.nets_path])


def test_free_text_cannot_break_the_tables(sim, tmp_path):
    s = sim(board_serial="MB|A\n001", notes="line one\nline | two", operator_name="a|b")
    md = (report.write(s.go(), tmp_path, s.session.transcript) / "report.md").read_text()
    assert "| Notes | line one line / two |" in md and "| Operator | a/b |" in md
    assert "| Board serial | MB/A 001 |" in md


def test_report_carries_the_a1_facts(sim, tmp_path):
    s = sim(coupons={1: "test", 2: "hall"}, inj=True)
    s.cfg.coupons = {2: "hall"}
    run = s.go()
    d = report.write(run, tmp_path, s.session.transcript)
    j = json.loads((d / "report.json").read_text())
    assert j["slots"]["1"]["inj_lift_mv"] > 400 and j["slots"]["2"]["coupon_declared"] == "hall"
    assert j["slots"]["1"]["descriptor_record"]["valid"] is True
    md = (d / "report.md").read_text()
    assert "| Coupons declared | S2=hall (others: test)" in md and "| valid |" in md
    assert f"| {j['slots']['1']['inj_lift_mv']:.4g} mV |" in md
