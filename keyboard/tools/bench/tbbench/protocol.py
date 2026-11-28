"""The bring-up shell protocol, version 1 (keyboard/firmware/bringup/PROTOCOL.md): a line parser and a session.

A machine-readable line holds "@tb <record> key=value ..." (or "@sim ..." from the simulated board's own commands).
A record starts at the first marker in a line and runs to its end; a prompt or VT100 escapes may come before it,
and every other line is ignored. Each "tb" command ends with exactly one "@tb done cmd=<command> rc=<int>
[err=<token>]", except a command the shell itself rejects, which prints usage text and no done line (so it times
out). Events ("@tb ev seq=<n> ...") may arrive in the middle of any command's output, may be missed, and are
replayed by "tb ev <since>"; the session keeps every event it has seen by sequence number.

This module is independent of keyboard/firmware/bringup/host/tb_proto.py on purpose (the harness must keep working
if that file moves); tests/test_protocol.py checks that the two parsers agree on a corpus of lines.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

ESC = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
KV = re.compile(r'([a-z0-9_]+)=("[^"]*"|\S+)')
RECORD_NAME = re.compile(r"[a-z_]+")
MARKERS = ("@tb ", "@sim ")
SETUP_COMMANDS = ("shell echo off", "shell colors off", "shell vt100 off", "shell prompt off")   # PROTOCOL.md

# Error numbers PROTOCOL.md lists for rc (negative errno), by name.
ERRNO = {-1: "EPERM", -2: "ENOENT", -5: "EIO", -11: "EAGAIN", -13: "EACCES", -17: "EEXIST", -19: "ENODEV",
         -22: "EINVAL", -134: "ENOTSUP", -116: "ETIMEDOUT", -16: "EBUSY", -28: "ENOSPC", -114: "EALREADY"}


class ProtocolError(Exception):
    """The device said something the protocol does not allow (or nothing at all)."""


class CommandTimeout(ProtocolError):
    """No done line for a command within its timeout."""

    def __init__(self, line, timeout, partial):
        self.line, self.timeout, self.partial = line, timeout, partial
        super().__init__(f"{line!r}: no done line within {timeout:.1f} s ({len(partial)} records before it)")


class LinkLost(ProtocolError):
    """The port closed, or the process behind it exited."""


def parse_value(v):
    """A value: a quoted string (name= only), an int (decimal or 0x hex, possibly negative) or a token."""
    if len(v) >= 2 and v.startswith('"') and v.endswith('"'):
        return v[1:-1]
    try:
        return int(v, 0)
    except ValueError:
        return v


@dataclass
class Record:
    space: str                   # "tb" or "sim"
    name: str                    # the record, e.g. "ina"
    fields: dict                 # key -> value, in the order printed
    line: str = ""               # the line it came from, escapes stripped

    def get(self, key, default=None):
        return self.fields.get(key, default)

    def __getitem__(self, key):
        return self.fields[key]

    def __contains__(self, key):
        return key in self.fields


def parse_line(line):
    """'... @tb rail rail=+3V3_S1 on=1' -> Record('tb', 'rail', {...}); None for a line without a record."""
    text = ESC.sub("", line).rstrip("\r\n")
    hits = [text.find(m) for m in MARKERS if m in text]
    if not hits:
        return None
    at = min(hits)
    body = text[at + 1:]
    space, _, rest = body.partition(" ")
    name, _, rest = rest.partition(" ")
    if not RECORD_NAME.fullmatch(name):
        return None
    return Record(space, name, {k: parse_value(v) for k, v in KV.findall(rest)}, text[at:])


@dataclass
class Result:
    line: str                                   # the command as sent
    records: list = field(default_factory=list)  # [Record] of this command, events excluded, in order
    events: list = field(default_factory=list)   # [Record] "ev" lines that arrived while it ran
    done: Record | None = None
    raw: list = field(default_factory=list)      # every line read while it ran
    elapsed_s: float = 0.0

    def all(self, name):
        return [r for r in self.records if r.name == name]

    def one(self, name):
        found = self.all(name)
        if len(found) != 1:
            raise ProtocolError(f"{self.line!r}: expected one {name!r} record, got {len(found)}")
        return found[0]

    def first(self, name):
        found = self.all(name)
        return found[0] if found else None

    @property
    def rc(self):
        return None if self.done is None else self.done.get("rc")

    @property
    def err(self):
        """The done line's err= token. PROTOCOL.md says it is absent on success, but the firmware prints it with
        rc=0 too (e.g. "tb slot <n> on keep" on a blank EEPROM: rc=0 err=blank); rc is the verdict."""
        return None if self.done is None else self.done.get("err")

    @property
    def ok(self):
        return self.rc == 0


def command_name(line):
    """'tb budget bench 1000' -> ('tb', 'budget'): the space and cmd= that its done line carries."""
    words = line.split()
    if not words:
        return None, None
    if words[0] in ("tb", "sim") and len(words) > 1:
        return words[0], words[1]
    return None, words[0]


class Session:
    """Commands and records over a Transport (tbbench.transport): readline(timeout) -> str | None, write(bytes).

    session.events holds every event seen (seq -> Record); session.take_events() hands out each new one once, in
    sequence order, for the procedure's danger checks."""

    def __init__(self, transport, default_timeout=5.0, clock=time.monotonic, transcript=None):
        self.t = transport
        self.default_timeout = default_timeout
        self.clock = clock
        self.transcript = transcript if transcript is not None else []   # (t_s, "<"|">", text)
        self.events = {}
        self._fresh = []
        self.desynced = True        # until sync() has seen a done line
        self.info = None
        self._t0 = clock()

    # --- lines ---------------------------------------------------------------------------------------------
    def _log(self, direction, text):
        self.transcript.append((round(self.clock() - self._t0, 4), direction, text.rstrip("\r\n")))

    def send(self, line):
        self._log(">", line)
        self.t.write((line + "\r\n").encode())

    def _readline(self, timeout):
        line = self.t.readline(max(timeout, 0.0))
        if line is not None:
            self._log("<", line)
        return line

    def _note_event(self, rec):
        seq = rec.get("seq")
        if isinstance(seq, int) and seq not in self.events:
            self.events[seq] = rec
            self._fresh.append(rec)

    def drain(self, quiet_s=0.15, max_s=2.0):
        """Read whatever is pending until the port has been quiet for quiet_s; returns the records seen."""
        seen = []
        end = self.clock() + max_s
        while self.clock() < end:
            line = self._readline(quiet_s)
            if line is None:
                break
            rec = parse_line(line)
            if rec is None:
                continue
            if rec.name == "ev":
                self._note_event(rec)
            seen.append(rec)
        return seen

    # --- commands ------------------------------------------------------------------------------------------
    def sync(self, attempts=3, timeout=3.0):
        """Bring the shell into the protocol's setup (echo, colours, VT100 and the prompt off) and prove the link
        with "tb info". Stale lines (a late done line from a timed-out command) are drained first.

        One line at a time, with a drain after each: Zephyr's serial shell backend keeps its input in a ring of
        CONFIG_SHELL_BACKEND_SERIAL_RX_RING_BUFFER_SIZE bytes (64 by default, subsys/shell/backends/
        Kconfig.backends, v4.5.0; the bring-up's prj.conf does not change it), and when the ring is full its RX
        handler reads the byte and drops it ("No space in the ring buffer - consume byte", shell_uart.c). The four
        setup lines and the empty one are 73 bytes: sent at once, as one USB packet on CDC ACM, their tail can be
        lost and the rest of the broken line joins the next command, the same way on every retry."""
        last = None
        for _ in range(attempts):
            self.drain()
            for c in ("", *SETUP_COMMANDS):
                self.send(c)
                self.drain(quiet_s=0.05, max_s=1.0)
            try:
                r = self._cmd("tb info", timeout)
            except CommandTimeout as e:
                last = e
                continue
            if r.done is not None and r.first("info") is not None:
                self.desynced = False
                self.info = r.first("info")
                return r
        raise last or ProtocolError("tb info: no answer")

    def cmd(self, line, timeout=None):
        if self.desynced and self.info is not None:
            self.sync()
        return self._cmd(line, self.default_timeout if timeout is None else timeout)

    def _cmd(self, line, timeout):
        space, name = command_name(line)
        start = self.clock()
        self.send(line)
        res = Result(line)
        deadline = start + timeout
        while True:
            raw = self._readline(deadline - self.clock())
            if raw is None:
                self.desynced = True
                res.elapsed_s = self.clock() - start
                raise CommandTimeout(line, timeout, res.records)
            res.raw.append(raw)
            rec = parse_line(raw)
            if rec is None:
                continue
            if rec.name == "ev":
                self._note_event(rec)
                res.events.append(rec)
            elif rec.name == "done" and rec.space == space and rec.get("cmd") == name:
                res.done = rec
                res.elapsed_s = self.clock() - start
                return res
            else:
                res.records.append(rec)

    # --- events ----------------------------------------------------------------------------------------------
    @property
    def next_seq(self):
        """The first sequence number not seen yet (events start at 1 at boot)."""
        return max(self.events, default=0) + 1

    def missing_seqs(self):
        if not self.events:
            return []
        top = max(self.events)
        return [s for s in range(1, top) if s not in self.events]

    def replay_events(self, timeout=None):
        """Ask the ring for every event from the oldest gap (or the next new one) on: a shell may miss event lines,
        and an unread CDC port can stall the printer for both shells (PROTOCOL.md, Events)."""
        gaps = self.missing_seqs()
        since = gaps[0] if gaps else self.next_seq
        return self.cmd(f"tb ev {since}", timeout)

    def take_events(self):
        out = sorted(self._fresh, key=lambda r: r.get("seq", 0))
        self._fresh = []
        return out
