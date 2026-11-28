"""pytest setup for keyboard/tools/bench.

Run from the repository root:  python -m pytest keyboard/tools/bench/tests -q
Everything runs on the standard library and pytest. Optional: pyserial (the pty test), and the bring-up firmware
built for native_sim (tests/test_native_sim.py; TB_SIM_EXE=<build>/zephyr/zephyr.exe, see the README).
"""

import os
import pathlib
import sys

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent
BENCH = HERE.parent
if str(BENCH) not in sys.path:
    sys.path.insert(0, str(BENCH))

import pytest  # noqa: E402

from tbbench import limits as L  # noqa: E402
from tbbench import simdev  # noqa: E402
from tbbench.prompts import ScriptedOperator  # noqa: E402
from tbbench.procedure import Bench, RunConfig  # noqa: E402
from tbbench.protocol import Session  # noqa: E402
from tbbench.transport import SimTransport  # noqa: E402

REPO = BENCH.parents[2]
NATIVE_EXE = pathlib.Path(os.environ.get("TB_SIM_EXE", REPO / "keyboard" / "firmware" / "build" / "bringup-sim" /
                                         "zephyr" / "zephyr.exe"))


@pytest.fixture(scope="session")
def limits():
    return L.Limits()


class Sim:
    """A simulated bench: the device, the session, the operator and the finished run."""

    def __init__(self, limits, faults=(), coupons=None, source="3.0A", usb="configured", bench_build=False,
                 operator=None, **cfg):
        f = simdev.Faults()
        for spec in faults:
            simdev.parse_fault(spec, f)
        self.dev = simdev.SimDevice(limits, coupons=coupons, source=source, usb=usb, bench_build=bench_build,
                                    faults=f)
        self.max_slot_rails = 0
        self._wrap_rail_on()
        answers = simdev.operator_answers(self.dev, limits)
        if operator is not None:
            answers.update(operator)
        self.op = ScriptedOperator(answers)
        self.session = Session(SimTransport(self.dev))
        cfg.setdefault("console", "sim")
        cfg.setdefault("board_serial", "TEST-1")
        self.cfg = RunConfig(**cfg)
        self.bench = Bench(self.session, limits, self.cfg, self.op, sleep=lambda _s: None)
        self.run = None

    def _wrap_rail_on(self):
        orig = self.dev._rail_on

        def rail_on(rail, ma):
            rc = orig(rail, ma)
            n = sum(1 for r in self.dev.on if r.startswith("+3V3_S"))
            self.max_slot_rails = max(self.max_slot_rails, n)
            return rc
        self.dev._rail_on = rail_on

    def go(self):
        self.run = self.bench.run()
        return self.run

    def step(self, sid):
        return next(s for s in self.run.steps if s.id == sid)

    def checks(self, sid, verdict=None):
        return [c for c in self.step(sid).checks if verdict is None or c.verdict == verdict]

    def failed(self):
        return {s.id: s.status for s in self.run.steps if s.status not in ("pass", "skipped")}

    def sent(self):
        return [text for _t, d, text in self.session.transcript if d == ">"]


@pytest.fixture
def sim(limits):
    def make(*faults, **kw):
        return Sim(limits, faults, **kw)
    return make
