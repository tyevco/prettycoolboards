"""Parser and session driver for the bring-up shell protocol (../PROTOCOL.md), for a bench harness and the tests.

    from tb_proto import Session
    with Session.sim("/path/to/zephyr.exe") as s:        # the simulated board (native_sim)
        s.setup()
        r = s.cmd("tb budget")
        print(r.done["rc"], r.one("budget")["limit_ma"])
    with Session.serial("/dev/ttyACM1") as s: ...         # the real board's CDC ACM or USART1 port (pyserial)

A record is everything from the first "@tb " (or "@sim ") in a line to its end; a prompt or VT100 escapes may
come before it. Values stay strings except where int() works (decimal or 0x hex).

SPDX-License-Identifier: Apache-2.0
"""
import queue
import re
import subprocess
import threading
import time

ESC = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
KV = re.compile(r'([a-z0-9_]+)=("[^"]*"|\S+)')
MARKERS = ("@tb ", "@sim ")


def _value(v):
    if v.startswith('"') and v.endswith('"'):
        return v[1:-1]
    try:
        return int(v, 0)
    except ValueError:
        return v


def parse(line):
    """'... @tb rail rail=+3V3_S1 on=1' -> ('tb', 'rail', {'rail': '+3V3_S1', 'on': 1}); None if not a record."""
    line = ESC.sub("", line).rstrip("\r\n")
    at = min((line.find(m) for m in MARKERS if m in line), default=-1)
    if at < 0:
        return None
    body = line[at + 1:]
    space, _, rest = body.partition(" ")
    rec, _, rest = rest.partition(" ")
    if not re.fullmatch(r"[a-z_]+", rec):
        return None
    return space, rec, {k: _value(v) for k, v in KV.findall(rest)}


class Result:
    def __init__(self, records, events, done):
        self.records = records      # [(record, fields)] of this command, in order
        self.events = events        # [fields] of "@tb ev" lines seen while it ran
        self.done = done            # the fields of "@tb done" (or "@sim done")

    def all(self, rec):
        return [f for r, f in self.records if r == rec]

    def one(self, rec):
        found = self.all(rec)
        if len(found) != 1:
            raise AssertionError(f"expected one {rec!r} record, got {len(found)}: {self.records}")
        return found[0]

    @property
    def ok(self):
        return self.done is not None and self.done.get("rc") == 0


class Session:
    """Line-oriented driver over any byte stream with readline() and write()."""

    def __init__(self, reader, writer, closer=None):
        self._w = writer
        self._close = closer
        self._q = queue.Queue()
        self.raw = []                # every line read, for debugging
        self.events = {}             # seq -> fields, every event seen so far
        threading.Thread(target=self._pump, args=(reader,), daemon=True).start()

    def _pump(self, reader):
        for raw in iter(reader.readline, b""):
            self._q.put(raw.decode("utf-8", "replace"))
        self._q.put(None)

    @classmethod
    def sim(cls, exe, args=()):
        p = subprocess.Popen([exe, "--uart_stdinout", *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT)

        def close():
            p.kill()
            p.wait(5)
        return cls(p.stdout, lambda b: (p.stdin.write(b), p.stdin.flush()), close)

    @classmethod
    def serial(cls, port, baud=115200):
        import serial  # pyserial, only for real ports
        s = serial.Serial(port, baud, timeout=0.2)

        class R:
            @staticmethod
            def readline():
                while True:
                    line = s.readline()
                    if line:
                        return line
        return cls(R, s.write, s.close)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if self._close:
            self._close()

    def send(self, line):
        self._w((line + "\r\n").encode())

    def _next(self, deadline):
        left = deadline - time.monotonic()
        if left <= 0:
            return None
        try:
            return self._q.get(timeout=left)
        except queue.Empty:
            return None

    def wait_for(self, rec, timeout=5.0, **match):
        """Read until a record (or event, rec='ev') with these fields; return its fields or raise."""
        deadline = time.monotonic() + timeout
        while True:
            line = self._next(deadline)
            if line is None:
                raise TimeoutError(f"no {rec} {match}")
            self.raw.append(line)
            p = parse(line)
            if p is None:
                continue
            _space, r, f = p
            if r == "ev":
                self.events[f.get("seq")] = f
            if r == rec and all(f.get(k) == v for k, v in match.items()):
                return f

    def setup(self, boot_timeout=5.0):
        """Wait for the boot event, then turn off echo, colours, VT100 and the prompt."""
        self.wait_for("ev", timeout=boot_timeout, kind="boot")
        for c in ("shell echo off", "shell colors off", "shell vt100 off", "shell prompt off"):
            self.send(c)
        time.sleep(0.3)

    def cmd(self, line, timeout=5.0):
        """Run one command; return its records up to its done line."""
        words = line.split()
        space = "sim" if words[0] == "sim" else "tb"
        name = words[1] if len(words) > 1 else words[0]
        self.send(line)
        deadline = time.monotonic() + timeout
        records, events = [], []
        while True:
            raw = self._next(deadline)
            if raw is None:
                raise TimeoutError(f"{line!r}: no done line; got {records}")
            self.raw.append(raw)
            p = parse(raw)
            if p is None:
                continue
            sp, rec, f = p
            if rec == "ev":
                self.events[f.get("seq")] = f
                events.append(f)
            elif rec == "done" and sp == space and f.get("cmd") == name:
                return Result(records, events, f)
            else:
                records.append((rec, f))
