"""The real-port path (pyserial) end to end, over a pseudo-terminal with the simulated board on its other side.

This exercises SerialTransport's byte handling (partial lines, CR LF, timeouts) as the bench will use it, on
Linux. It needs pyserial (pip install pyserial) and a POSIX pty; it is skipped otherwise. It does not test a USB
CDC ACM port or the STLINK-V3's VCP: their drivers, DTR handling and latency are not here.
"""

import os
import threading

import pytest

serial = pytest.importorskip("serial")
pty = pytest.importorskip("pty")

from tbbench import simdev  # noqa: E402
from tbbench.prompts import ScriptedOperator  # noqa: E402
from tbbench.procedure import Bench, RunConfig  # noqa: E402
from tbbench.protocol import Session  # noqa: E402
from tbbench.transport import SerialTransport  # noqa: E402


@pytest.mark.skipif(os.name != "posix", reason="needs a POSIX pty")
def test_full_run_over_a_pty(limits):
    master, slave = pty.openpty()
    import tty
    tty.setraw(slave)
    dev = simdev.SimDevice(limits)
    dev.out.clear()                         # the boot report went out before the port was opened
    stop = threading.Event()
    th = threading.Thread(target=simdev.serve_pty, args=(dev, master, stop), daemon=True)
    th.start()
    t = SerialTransport(os.ttyname(slave))
    try:
        s = Session(t)
        run = Bench(s, limits, RunConfig(console="uart", board_serial="PTY"), ScriptedOperator(),
                    sleep=lambda _s: None).run()
    finally:
        stop.set()
        t.close()
        os.close(master)
        os.close(slave)
    assert run.verdict == "PASS (with warnings)", {x.id: x.status for x in run.steps if x.status != "pass"}
