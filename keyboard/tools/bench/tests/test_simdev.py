"""The simulated board is held to PROTOCOL.md, and the harness's tokens to the ones PROTOCOL.md defines.

If PROTOCOL.md changes a record, these tests fail until the simulator follows; tests/test_native_sim.py checks the
firmware itself the same way, so the simulator, the document and the firmware cannot drift apart unnoticed.
"""

import pytest

from tbbench import limits as L
from tbbench import simdev
from tbbench.protocol import parse_line

from . import protocol_doc as P

pytestmark = pytest.mark.skipif(not P.PROTOCOL.exists(), reason="no PROTOCOL.md")

SCENARIOS = [(), ("bad_descriptor=1:crc",), ("missing_monitor=0x44",), ("dead_rail=+3V3_S1",),
             ("short=+3V3_S1:400",), ("cc_absent",), ("missing_expander=0x22",), ("missing_mux",),
             ("wrong_divider=1:2:0.55",), ("stuck_loopback=1:0x0100",), ("stale_ina=+3V3_S1",),
             ("bad_descriptor=1:blank",), ("late_load=+3V3_S1:3:400",)]


def records_of(sim_obj):
    return [r for r in (parse_line(t) for _ts, d, t in sim_obj.session.transcript if d == "<") if r is not None]


@pytest.fixture(scope="module")
def all_records(limits):
    from .conftest import Sim
    recs = []
    for faults in SCENARIOS:
        s = Sim(limits, faults, climit=True, meter=True, write_descriptor=None)
        s.go()
        recs += records_of(s)
    s = Sim(limits, ("nrst_restore_fail",), coupons={1: "test", 3: "test", 5: "test"}, usb="unconfigured",
            bench_build=True, power="bench", bench_ma=1000, console="uart", nrst=True, climit=True)
    s.go()
    recs += records_of(s)
    for c in ("tb budget override 400", "tb rail +5V_KVM on 10", "tb budget", "tb rail +5V_KVM off", "tb rail x on 1",
              "tb reboot"):
        s.session.cmd(c)
    recs += records_of(s)
    return [r for r in recs if r.space == "tb"]


def test_every_record_matches_a_template(all_records):
    tmpl = P.templates()
    bad = {P.conforms(r, tmpl) for r in all_records} - {None}
    assert not bad, sorted(bad)
    names = {r.name for r in all_records}
    assert len(names) >= 30, f"the scenarios exercise most records: {sorted(names)}"


def test_every_error_token_is_documented(all_records):
    toks = {r.get("err") for r in all_records if r.name == "done" and r.get("err")}
    assert toks - P.error_tokens() == set(), toks
    assert {"fault_3v3", "low_3v3", "crc", "monitor", "blank", "desc_bus"} <= toks


def test_every_event_kind_is_documented(all_records):
    kinds = {r.get("kind") for r in all_records if r.name == "ev"}
    assert kinds - P.event_kinds() == set()
    finds = {r.get("finding") for r in all_records if r.name in ("trip",) or r.get("kind") == "trip"}
    assert finds - {None} - P.findings() == set()


def test_the_harness_tokens_exist_in_protocol():
    assert L.DANGER_ERR_TOKENS | L.LOW_ERR_TOKENS <= P.error_tokens()
    assert L.DANGER_FINDINGS <= P.findings()
    assert L.DANGER_RAIL_OFF_REASONS <= P.rail_off_reasons()


def test_sim_self_test_numbers_are_the_firmwares(limits):
    """The healthy simulator's self-test lands where the firmware on native_sim did (2026-11-27 transcript)."""
    from .conftest import Sim
    s = Sim(limits, climit=True)
    s.go()
    steps = {r["name"]: r for r in records_of(s) if r.name == "step"}
    assert steps["load3"]["rs_mohm"] == 326 and steps["idle"]["i_ua"] == 1386
    assert steps["climit3"]["trip_ma"] == "256/292/335" and steps["climit5"]["trip_ma"] == "519/577/644"
    assert steps["loopback"]["patterns"] == 8


def test_the_shell_rx_ring_model_loses_a_burst(limits):
    """The model behind rx_ring: 73 bytes of setup written at once into a 64-byte ring lose their tail, and the
    broken line swallows the next command (what the harness's old sync() would have met on CDC ACM)."""
    from tbbench.protocol import SETUP_COMMANDS
    dev = simdev.SimDevice(limits, faults=simdev.parse_fault("rx_ring=64"))
    while dev.readline():
        pass
    dev.write(b"\r\n" + b"".join(c.encode() + b"\r\n" for c in SETUP_COMMANDS))   # the old sync(): one burst,
    while dev.readline():                                                           # a drain,
        pass
    dev.write(b"tb info\r\n")                                                       # then tb info
    out = []
    while (line := dev.readline()) is not None:
        out.append(line)
    assert not any("@tb done cmd=info" in x for x in out), out
    assert any("wrong parameter" in x for x in out), out


def test_setup_line_by_line_survives_the_ring(sim):
    s = sim("rx_ring=64")
    assert s.go().verdict.startswith("PASS"), s.failed()


# --- the simulator against the firmware's shell registration (keyboard/firmware/bringup/src/cmds.c) -------------
CMDS_C = L.REPO / "keyboard" / "firmware" / "bringup" / "src" / "cmds.c"


def firmware_shell_args():
    """{subcommand: (mandatory, optional)} from cmds.c's SHELL_STATIC_SUBCMD_SET_CREATE(sub_tb, ...)."""
    import re
    text = CMDS_C.read_text(encoding="utf-8")
    block = text.split("SHELL_STATIC_SUBCMD_SET_CREATE(\n\tsub_tb,", 1)[1].split("SHELL_SUBCMD_SET_END", 1)[0]
    out = {}
    for m in re.finditer(r"SHELL_CMD_ARG\((\w+),\s*NULL,\s*(?:\"(?:[^\"\\]|\\.)*\"\s*)+,\s*(\w+),\s*(\d+),\s*(\d+)\)",
                         block):
        out[m.group(1)] = (int(m.group(3)), int(m.group(4)))
    return out


@pytest.mark.skipif(not CMDS_C.exists(), reason="no firmware sources")
def test_command_set_is_the_firmwares():
    """Every tb subcommand the firmware registers is simulated with the same argument counts, and the simulator
    answers nothing the firmware does not register."""
    fw = firmware_shell_args()
    assert len(fw) >= 17, fw
    assert simdev.SHELL_ARGS == fw
    handlers = {n[2:] for n in dir(simdev.SimDevice) if n.startswith("c_")}
    assert handlers == set(fw), (sorted(handlers - set(fw)), sorted(set(fw) - handlers))


def _dev_cmd(dev, line):
    while dev.readline() is not None:
        pass
    dev.write(line.encode() + b"\r\n")
    out = []
    while (x := dev.readline()) is not None:
        out.append(x)
    recs = [r for r in (parse_line(x) for x in out) if r is not None]
    done = next((r for r in recs if r.name == "done"), None)
    return recs, done


@pytest.mark.parametrize("line", ["tb info extra", "tb slot 1 on a b c d e", "tb rail +3V3_S1", "tb desc",
                                  "tb ev 1 2", "tb selftest"])
def test_a_wrong_argument_count_gets_no_done_line(limits, line):
    """PROTOCOL.md, Completion: the shell itself rejects the count (usage text, no done line), as on native_sim."""
    _recs, done = _dev_cmd(simdev.SimDevice(limits), line)
    assert done is None


@pytest.mark.parametrize("line,rc,err", [
    ("tb budget override abc", -22, "usage"), ("tb budget base off", -22, "usage"), ("tb ev abc", -22, "usage"),
    ("tb lanes 9", -22, "usage"), ("tb mon period", -22, "usage"), ("tb mon x y", -22, "usage"),
    ("tb rail +3V3_S1 on abc", -22, "usage"), ("tb ina alert nope 100", -22, "usage"),
    ("tb ina drv nope", -22, "usage"), ("tb ina cfg +3V3_S1 16 1100 1100 x", -22, "usage"),
    ("tb ina cfg all 3 1100 1100 7", -22, "bad_config"), ("tb slot 1 on nodesc", -22, "usage"),
    ("tb selftest 9", -22, "usage")])
def test_arguments_the_firmware_refuses(limits, line, rc, err):
    """What native_sim answered on 2026-11-28 (the review's differential run against src/cmds.c)."""
    recs, done = _dev_cmd(simdev.SimDevice(limits), line)
    assert done is not None and (done["rc"], done.get("err")) == (rc, err)
    assert [r.name for r in recs if r.name not in ("done", "ev")] in ([], ["budget"]), recs


def test_a_rail_already_on_is_refused(limits):
    dev = simdev.SimDevice(limits)
    _recs, done = _dev_cmd(dev, "tb rail +3V3_S1 on 100")
    assert done["rc"] == 0
    recs, done = _dev_cmd(dev, "tb rail +3V3_S1 on 100")
    assert (done["rc"], done.get("err")) == (-1, "already_on") and not [r for r in recs if r.name == "rail"]


def test_desc_prints_the_g_lines_and_refuses_stray_words(limits):
    dev = simdev.SimDevice(limits)
    _dev_cmd(dev, "tb slot 1 on")
    recs, done = _dev_cmd(dev, "tb desc 1")
    assert done["rc"] == 0 and [r["line"] for r in recs if r.name == "desc_gline"] == [f"G{g}" for g in range(6)]
    for line in ("tb desc 1 write", "tb desc 1 foo"):
        assert _dev_cmd(dev, line)[1].get("err") == "usage"


def test_ina_alert_and_drv_records(limits):
    dev = simdev.SimDevice(limits)
    recs, done = _dev_cmd(dev, "tb ina alert +3V3_S1 100")
    a = next(r for r in recs if r.name == "ina_alert")
    assert done["rc"] == 0 and a["limit_ma"] == 100 and a["limit_raw"] == 9600     # 100 mA x 0.24 ohm / 2.5 uV
    recs, _done = _dev_cmd(dev, "tb ina drv VSYS")
    assert next(r for r in recs if r.name == "ina_drv")["rail"] == "VSYS"


def test_the_rail_alert_turns_an_over_drawing_rail_off(limits):
    """src/board.c tb_rail_alert_ua(): declared x 1.1 + 1 mA. A coupon that starts to draw more than that, under
    the switch_limit floor, is turned off by the firmware with finding=alert (seen on native_sim, 2026-11-28)."""
    f = simdev.parse_fault("late_load=+3V3_S1:2:140")     # 141 mA: over 133 mA, under the 205 mA floor
    dev = simdev.SimDevice(limits, faults=f)
    _dev_cmd(dev, "tb slot 1 on")
    recs, _ = _dev_cmd(dev, "tb ina +3V3_S1")
    recs, _ = _dev_cmd(dev, "tb ina +3V3_S1")
    evs = [r for r in recs if r.name == "ev" and r.get("finding")]
    assert [e["finding"] for e in evs] == ["alert"] and "+3V3_S1" not in dev.on
