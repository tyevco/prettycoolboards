"""Byte transports for the session: a real serial port (pyserial), a native_sim firmware process, an in-process
simulated device. Each offers write(bytes), readline(timeout) -> str | None (None: nothing within the timeout) and
close(); a closed port or an exited process raises protocol.LinkLost.
"""

from __future__ import annotations

import queue
import subprocess
import threading
import time

from .protocol import LinkLost


class SerialTransport:
    """The testbed's CDC ACM port (VID:PID 1209:0001) or USART1 through the STLINK-V3's virtual COM port, 115200 8N1
    (PROTOCOL.md, Transport). Needs pyserial (pip install pyserial)."""

    def __init__(self, port, baud=115200):
        try:
            import serial  # noqa: PLC0415  (only the real bench needs pyserial)
        except ImportError as e:     # pragma: no cover - depends on the machine
            raise SystemExit("pyserial is not installed: pip install pyserial") from e
        self._serial_mod = serial
        try:
            self.s = serial.serial_for_url(port, baudrate=baud, timeout=0.05, write_timeout=2.0)
        except (serial.SerialException, OSError) as e:
            raise LinkLost(f"cannot open {port}: {e}") from e
        self.port = port
        self._buf = b""

    def write(self, data):
        try:
            self.s.write(data)
            self.s.flush()
        except (self._serial_mod.SerialException, OSError) as e:
            raise LinkLost(f"{self.port}: {e}") from e

    def readline(self, timeout):
        end = time.monotonic() + timeout
        while True:
            nl = self._buf.find(b"\n")
            if nl >= 0:
                line, self._buf = self._buf[:nl + 1], self._buf[nl + 1:]
                return line.decode("utf-8", "replace")
            if time.monotonic() >= end:
                return None
            try:
                chunk = self.s.read(max(1, self.s.in_waiting or 1))
            except (self._serial_mod.SerialException, OSError) as e:
                raise LinkLost(f"{self.port}: {e}") from e
            self._buf += chunk

    def close(self):
        try:
            self.s.close()
        except Exception:  # noqa: BLE001  (closing a port that vanished)
            pass


class ProcessTransport:
    """The bring-up firmware built for native_sim (keyboard/firmware/bringup/sim), on stdin/stdout."""

    def __init__(self, argv):
        self.p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.q = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        for raw in iter(self.p.stdout.readline, b""):
            self.q.put(raw.decode("utf-8", "replace"))
        self.q.put(None)

    def write(self, data):
        try:
            self.p.stdin.write(data)
            self.p.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            raise LinkLost(f"native_sim process: {e}") from e

    def readline(self, timeout):
        try:
            line = self.q.get(timeout=max(timeout, 0.001))
        except queue.Empty:
            return None
        if line is None:
            self.q.put(None)
            raise LinkLost(f"native_sim process exited ({self.p.poll()})")
        return line

    def close(self):
        if self.p.poll() is None:
            self.p.kill()
        self.p.wait(5)


class SimTransport:
    """An in-process tbbench.simdev.SimDevice. Lines are produced when a command is written, so readline never has
    to wait: an empty queue is a timeout at once (tests of a hanging command run instantly)."""

    def __init__(self, device):
        self.dev = device

    def write(self, data):
        self.dev.write(data)

    def readline(self, timeout):
        return self.dev.readline()

    def close(self):
        pass
