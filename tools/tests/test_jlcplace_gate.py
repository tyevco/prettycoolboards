"""jlcplace_gate: what blocks a release and what goes into ORDER-NOTES (no jlcplace run needed)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import jlcplace_gate as g  # noqa: E402


def _res(rows, findings=(), bom=(), checklist=(), rc=0):
    s = {"red": sum(r["verdict"] == "red" for r in rows), "yellow": sum(r["verdict"] == "yellow" for r in rows),
         "green": sum(r["verdict"] == "green" for r in rows), "verified": 0, "results": len(rows)}
    res = {"summary": s, "findings": list(findings), "bom": list(bom), "checklist": list(checklist),
           "results": rows, "rc": rc, "origin": {"note": "the Gerbers' (0, 0) is this CPL's origin"}}
    res["summary_line"] = g._summary_line(s)
    res["red"] = g.is_red(res)
    return res


def _row(ref, verdict, msg=""):
    return {"ref": ref, "lcsc": "C1", "layer": "top", "verdict": verdict, "messages": [msg] if msg else []}


def test_green_and_yellow_pass():
    res = _res([_row("R1", "green"), _row("BZ1", "yellow", "polarity decided by pad numbers only")])
    assert not res["red"]
    lines = g.order_lines(res, (0, 2, 1))
    assert "0 red, 1 yellow, 1 green" in lines[0] and "do not order" not in lines[0]
    assert any("yellow BZ1" in ln and "pad numbers only" in ln for ln in lines)


def test_red_row_blocks():
    res = _res([_row("U1", "red", "6 of 6 EasyEDA pads land on other nets")], rc=2)
    assert res["red"]
    assert g.problem_lines(res) == ["U1 (C1, top): 6 of 6 EasyEDA pads land on other nets"]
    assert "do not order" in g.order_lines(res, (0, 2, 1))[0]


def test_red_finding_blocks_even_with_green_rows():
    res = _res([_row("R1", "green")], findings=[{"status": "origin", "verdict": "red", "message": "origin mismatch"}])
    assert res["red"]
    assert g.problem_lines(res) == ["run (origin): origin mismatch"]


def test_yellow_finding_and_bom_notes_do_not_block():
    res = _res([_row("R1", "green")], findings=[{"status": "gerbers", "verdict": "yellow", "message": "no paste"}],
               bom=["JLC places C7519 from the BOM; the board says C2681320"])
    assert not res["red"]
    lines = g.order_lines(res, (0, 2, 1))
    assert any("yellow run (gerbers): no paste" in ln for ln in lines)
    assert any(ln.strip().startswith("* yellow BOM: JLC places C7519") for ln in lines)


def test_checklist_items_listed():
    item = {"category": "bottom reading", "ref": "U30", "refs": ["U30"], "lcsc": "C2", "layer": "bottom",
            "rotation": 0.0, "what": "pin 1 would sit on pad 11"}
    lines = g.order_lines(_res([_row("U30", "green")], checklist=[item]), (0, 2, 1))
    assert any("[ ] bottom reading: **U30**" in ln for ln in lines)
    lines = g.order_lines(_res([_row("R1", "green")]), (0, 2, 1))
    assert lines[-1].endswith("nothing to check")


def _rec(ref, verdict, status=None, source="db", found=True, msg=""):
    r = _row(ref, verdict, msg)
    r["easyeda"] = {"found": found}
    if status:
        r["correction"] = {"status": status, "source": source}
    return r


def test_auto_db_correction_may_not_hide_a_red_row():
    # jlcplace check --db accepts a renumbering onto other nets from a stored auto correction
    res_db = _res([_rec("U1", "green", "auto", msg="numbering accepted by the correction (auto): 1->4")])
    res_rec = _res([_rec("U1", "red", msg="EasyEDA pads land on other-numbered KiCad pads of other nets")], rc=2)
    assert not res_db["red"]
    g.add_cross_check(res_db, res_rec)
    assert res_db["red"]
    assert any("auto correction overrides" in p for p in g.problem_lines(res_db))


def test_human_decision_accepts_a_records_red_row():
    res_db = _res([_rec("SW1", "yellow", "manual", msg="numbering vouched for only by a manual decision")])
    res_rec = _res([_rec("SW1", "red", msg="numbering")], rc=2)
    g.add_cross_check(res_db, res_rec)
    assert not res_db["red"]
    assert any("accepted by a recorded decision: SW1" in ln for ln in g.order_lines(res_db, (0, 2, 1)))


def test_row_without_record_is_left_to_the_db_run():
    res_db = _res([_rec("R26", "green", "auto")])
    res_rec = _res([_rec("R26", "red", found=False, msg="not simulated")], rc=2)
    g.add_cross_check(res_db, res_rec)
    assert not res_db["red"]
