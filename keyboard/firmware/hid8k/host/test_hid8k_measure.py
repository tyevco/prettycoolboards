"""Tests for hid8k_measure's plumbing, with fake devices (no hardware, no hid package needed)."""

from __future__ import annotations

import json
import queue
import sys
import threading
import types

import hid8k_analysis as ha
import hid8k_measure as hm
from test_hid8k_analysis import synth


class FakeSource:
    name = "fake"
    path = "fake0"

    def __init__(self, stream):
        self.it = iter([d for d, _ in stream])

    def read(self, timeout_ms):
        return next(self.it, b"")

    def close(self):
        pass


def run_main(monkeypatch, tmp_path, stream, *extra):
    monkeypatch.setattr(hm, "open_source", lambda args: FakeSource(stream))
    monkeypatch.setattr(hm, "linux_usb_info", lambda vid, pid: [])
    out = tmp_path / "result.json"
    csv = tmp_path / "reports.csv"
    rc = hm.main(["--duration", "0.3", "--warmup", "0", "--min-duration", "0", "--out", str(out),
                  "--csv", str(csv), *extra])
    return rc, json.loads(out.read_text()), csv.read_text().splitlines()


def test_main_pass(monkeypatch, tmp_path, capsys):
    rc, res, rows = run_main(monkeypatch, tmp_path, synth(4000))
    assert rc == 0 and res["verdict"] == "PASS"
    assert res["meta"]["backend"] == "fake" and res["meta"]["vid_pid"] == "1209:0001"
    assert rows[0].startswith("arrival_ns,seq") and len(rows) == 4001
    assert "VERDICT: PASS" in capsys.readouterr().out


def test_main_fail_exit_code(monkeypatch, tmp_path):
    rc, res, _ = run_main(monkeypatch, tmp_path, synth(4000, drop={1000}))
    assert rc == 1 and res["verdict"] == "FAIL"


def test_main_device_lost_still_writes_a_fail(monkeypatch, tmp_path):
    stream = synth(4000)

    class Unplugged(FakeSource):
        def __init__(self, st):
            super().__init__(st[:2000])
            self.n = 0

        def read(self, timeout_ms):
            self.n += 1
            if self.n > 2000:
                raise OSError(19, "No such device")
            return super().read(timeout_ms)

    monkeypatch.setattr(hm, "open_source", lambda args: Unplugged(stream))
    monkeypatch.setattr(hm, "linux_usb_info", lambda vid, pid: [])
    out = tmp_path / "result.json"
    rc = hm.main(["--duration", "5", "--warmup", "0", "--min-duration", "0", "--out", str(out)])
    res = json.loads(out.read_text())
    assert rc == 1 and res["verdict"] == "FAIL" and "reader" in res["failed"]
    assert "No such device" in res["reader_error"] and res["reports_received"] == 2000


def test_hidapi_source_cython_binding(monkeypatch):
    report = ha.pack_stats(seq=5)

    class Device:  # cython-hidapi style: hid.device(), open_path, read -> list of int
        def open_path(self, path):
            self.path = path

        def read(self, n, timeout_ms=0):
            return list(report)

        def close(self):
            pass

    monkeypatch.setitem(sys.modules, "hid", types.SimpleNamespace(device=Device))
    src = hm.HidapiSource(b"p")
    assert src.read(10) == report and src.binding.startswith("hidapi")


def test_hidapi_source_pyhidapi_binding(monkeypatch):
    report = ha.pack_stats(seq=6)

    class Device:  # pyhidapi ('hid' package) style: hid.Device(path=...), read -> bytes
        def __init__(self, path=None):
            self.path = path

        def read(self, size, timeout=None):
            return report

        def close(self):
            pass

    monkeypatch.setitem(sys.modules, "hid", types.SimpleNamespace(Device=Device))
    src = hm.HidapiSource(b"p")
    assert src.read(10) == report and src.binding.startswith("hid (pyhidapi)")


def test_cdc_logger_counts_lines(monkeypatch, tmp_path):
    chunks = [b"hid8k t=1s usb=cfg hs rate=8000.0/s\r\n~fill 000", b"00000 ....\r\n",
              b"hid8k t=2s usb=cfg hs rate=8000.0/s\r\n"]
    written = []

    class Serial:
        def __init__(self, port, baud, timeout):
            self.chunks = list(chunks)

        def write(self, data):
            written.append(data)

        def flush(self):
            pass

        def read(self, n):
            return self.chunks.pop(0) if self.chunks else b""

        def close(self):
            pass

    monkeypatch.setitem(sys.modules, "serial", types.SimpleNamespace(Serial=Serial))
    results = queue.Queue()
    ready = threading.Event()
    log = tmp_path / "cdc.log"
    hm.cdc_logger("COMX", 0.2, "heavy", str(log), results, ready)
    out = results.get_nowait()
    assert ready.is_set()
    assert out["stats_lines"] == 2 and out["fill_lines"] == 1
    assert out["bytes"] == sum(len(c) for c in chunks) == log.stat().st_size
    assert out["last_stats_line"].startswith("hid8k t=2s")
    assert b"heavy" in written[0] and b"reset" in written[0] and written[-1] == b"normal\r\n"
