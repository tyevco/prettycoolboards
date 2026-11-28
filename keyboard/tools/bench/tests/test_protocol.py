"""The protocol parser and session: PROTOCOL.md's line format, completion, timeouts and events."""

import importlib.util

import pytest

from tbbench import limits as L
from tbbench import simdev
from tbbench.protocol import CommandTimeout, Session, command_name, parse_line, parse_value
from tbbench.transport import SimTransport

TB_PROTO = L.REPO / "keyboard" / "firmware" / "bringup" / "host" / "tb_proto.py"


class Scripted:
    """A transport that answers each written command from a table: line -> [lines]."""

    def __init__(self, table, boot=()):
        self.table = table
        self.out = list(boot)
        self.written = []

    def write(self, data):
        for line in data.decode().split("\r\n"):
            if line:
                self.written.append(line)
                self.out += self.table.get(line, [])

    def readline(self, timeout):
        return self.out.pop(0) if self.out else None


def test_values():
    assert parse_value("12") == 12 and parse_value("-19") == -19 and parse_value("0x5449") == 0x5449
    assert parse_value("+3V3_S1") == "+3V3_S1" and parse_value('"test coupon A"') == "test coupon A"
    assert parse_value("256/292/335") == "256/292/335" and parse_value("3.0A") == "3.0A"


def test_record_after_prompt_and_escapes():
    r = parse_line("\x1b[1;32mtb:uart> \x1b[m\x1b[9D\x1b[J@tb ev seq=1 t_ms=0 kind=boot restore_ok=1\r\n")
    assert (r.space, r.name, r["seq"], r["kind"]) == ("tb", "ev", 1, "boot")
    assert list(r.fields) == ["seq", "t_ms", "kind", "restore_ok"], "key order is kept"


def test_quoted_name_and_unknown_keys():
    r = parse_line('@tb desc slot=1 status=ok len=167 name="test coupon A" slots=0x1f newkey=7')
    assert r["name"] == "test coupon A" and r["slots"] == 0x1F and r["newkey"] == 7


def test_lines_without_records():
    for line in ("[00:00:01.234,000] <wrn> tb_main: board init incomplete", "tb:uart> ", "", "*** Booting Zephyr",
                 "  info      : firmware, map and protocol version", "@tb Bad record=1", "@tbx info"):
        assert parse_line(line) is None, line


def test_sim_space():
    r = parse_line("@sim done cmd=source rc=0")
    assert r.space == "sim" and r.name == "done" and r["cmd"] == "source"


def test_command_names():
    assert command_name("tb budget bench 1000") == ("tb", "budget")
    assert command_name("sim usb configured") == ("sim", "usb")


def test_agrees_with_the_firmware_hosts_parser():
    """keyboard/firmware/bringup/host/tb_proto.py is the firmware side's parser: both must read lines the same."""
    if not TB_PROTO.exists():
        pytest.skip("no tb_proto.py")
    spec = importlib.util.spec_from_file_location("tb_proto_ext", TB_PROTO)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    dev = simdev.SimDevice(faults=simdev.parse_fault("noisy"))
    s = Session(SimTransport(dev))
    s.sync()
    for c in ("tb boot", "tb exp", "tb ina", "tb cc", "tb slot 1 on", "tb desc 1", "tb lanes 1", "tb selftest 1 all",
              "tb trips", "tb ev 1", "tb slot 9"):
        s.cmd(c)
    lines = [t for _ts, d, t in s.transcript if d == "<"]
    lines += ['@tb desc slot=1 status=ok name="a b c" x=1', "garbage", "\x1b[J@tb done cmd=x rc=-22 err=usage"]
    assert len(lines) > 100
    for line in lines:
        mine, theirs = parse_line(line), mod.parse(line)
        if theirs is None:
            assert mine is None, line
        else:
            assert (mine.space, mine.name, mine.fields) == theirs, line


def test_cmd_collects_records_events_and_done():
    t = Scripted({"tb rail +5V_KVM on 10": ["@tb ev seq=4 t_ms=1 kind=rail_on rail=+5V_KVM declared_ma=10\r\n",
                                            "@tb rail rail=+5V_KVM on=1 declared_ma=10 fault=0\r\n",
                                            "@tb done cmd=rail rc=0\r\n"]})
    s = Session(t)
    r = s.cmd("tb rail +5V_KVM on 10")
    assert r.ok and r.one("rail")["on"] == 1 and [e["seq"] for e in r.events] == [4]
    assert [e["kind"] for e in s.take_events()] == ["rail_on"] and s.take_events() == []


def test_done_must_match_space_and_command():
    t = Scripted({"tb usb": ["@sim done cmd=usb rc=0\r\n", "@tb done cmd=budget rc=0\r\n",
                             "@tb usb state=configured config=1 speed=hs\r\n", "@tb done cmd=usb rc=0\r\n"]})
    r = Session(t).cmd("tb usb")
    assert r.one("usb")["speed"] == "hs", "neither @sim done nor another command's done ends tb usb"


def test_rc_zero_with_err_is_success():
    """The firmware prints err= with rc=0 (tb slot <n> on keep on a blank EEPROM): rc decides (PROTOCOL.md says
    err is absent on success; README finding)."""
    t = Scripted({"tb slot 2 on keep": ["@tb done cmd=slot rc=0 err=blank\r\n"]})
    r = Session(t).cmd("tb slot 2 on keep")
    assert r.ok and r.err == "blank"


def test_timeout_then_resync_drops_the_stale_done_line():
    dev = simdev.SimDevice(faults=simdev.parse_fault("hang=lanes"))
    s = Session(SimTransport(dev))
    s.sync()
    with pytest.raises(CommandTimeout):
        s.cmd("tb lanes 1")
    assert s.desynced
    r = s.cmd("tb usb")
    assert r.ok and not s.desynced and r.one("usb")


def test_events_gaps_and_replay():
    dev = simdev.SimDevice(faults=simdev.parse_fault("drop_events"))
    s = Session(SimTransport(dev))
    s.sync()
    assert s.events == {}, "no live event line arrives"
    s.cmd("tb slot 1 on")
    r = s.replay_events()
    assert r.one("ev_dump")["replayed"] >= 3
    assert sorted(s.events) == list(range(1, max(s.events) + 1)) and not s.missing_seqs()
    assert {e["kind"] for e in s.events.values()} >= {"boot", "rail_on", "slot"}


def test_duplicate_events_are_counted_once():
    s = Session(SimTransport(simdev.SimDevice()))
    s.sync()
    s.cmd("tb ev 1")
    s.cmd("tb ev 1")
    seqs = [e["seq"] for e in s.take_events()]
    assert seqs == sorted(set(seqs))
