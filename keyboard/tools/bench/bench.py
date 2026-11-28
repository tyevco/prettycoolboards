#!/usr/bin/env python3
"""Bring-up bench harness for the PrettyCool Keyboard rev A testbed (README.md in this directory).

    bench.py checklist [--format text|md] [--out FILE]        the manual steps before and around power-on
    bench.py run --port PORT --board-serial SN [options]       the automated walk on the real board
    bench.py sim [--fault NAME=VALUE ...] [options]            the same walk against the simulated board
    bench.py native-sim --exe zephyr.exe [options]             the same walk against the firmware on native_sim
    bench.py serve-sim [--fault ...]                           the simulated board on a pty, to rehearse "run"
    bench.py faults                                            the simulator's faults

Exit status: 0 PASS (or PASS with warnings), 1 FAIL, 2 STOPPED on a dangerous failure, 3 INCOMPLETE.
Nothing here has run against hardware: no testbed exists yet (2026-11-28).
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from tbbench import checklist, report  # noqa: E402
from tbbench import limits as L  # noqa: E402
from tbbench import simdev  # noqa: E402
from tbbench.prompts import ConsoleOperator, ScriptedOperator  # noqa: E402
from tbbench.procedure import Bench, RunConfig  # noqa: E402
from tbbench.protocol import LinkLost, Session  # noqa: E402
from tbbench.transport import ProcessTransport, SerialTransport, SimTransport  # noqa: E402

EXIT = {"PASS": 0, "PASS (with warnings)": 0, "FAIL": 1, "STOPPED": 2, "INCOMPLETE": 3}
DEFAULT_OUT = HERE / "runs"


def slot_list(s):
    return [int(x) for x in s.split(",") if x.strip()]


def coupon_map(items):
    """["1=test", "2=hall"] or ["1=test,2=hall"] -> {1: "test", 2: "hall"} (A1's coupons only)."""
    out = {}
    for item in items or []:
        for x in item.split(","):
            if not x.strip():
                continue
            k, _, v = x.partition("=")
            if v not in L.A1_COUPONS:
                raise argparse.ArgumentTypeError(f"--coupon {x}: A1's coupons are {', '.join(L.A1_COUPONS)} "
                                                 "(A2's have no procedure in this release, SPEC §1)")
            out[int(k)] = v
    return out


def run_options(p):
    g = p.add_argument_group("the run")
    g.add_argument("--power", choices=("usb", "bench"), default="usb",
                   help="usb: J1 on a host; bench: a current-limited supply on J1, no host, USART1 only")
    g.add_argument("--bench-ma", type=int, help="bench mode: the supply's current limit (mA)")
    g.add_argument("--source", choices=("default", "1.5A", "3.0A", "typeA"),
                   help="what the USB-C source advertises (typeA: a Type-A port through a Type-A-to-C cable)")
    g.add_argument("--slots", type=slot_list, help="slots to test, e.g. 1,3 (default: every slot with a coupon)")
    g.add_argument("--coupon", action="append", metavar="SLOT=KIND",
                   help="what is plugged into a slot: test (default) or hall, e.g. --coupon 2=hall; repeatable. "
                        "The test coupon's slots run first (SPEC §10 step 7), then the Hall coupon's (step 8, A1)")
    g.add_argument("--inj", action="store_true",
                   help="INJ into the test coupon's AN0 lane (D7): the operator drives INJ from TP1 to TP15")
    g.add_argument("--key-check", action="store_true",
                   help="the operator tries each test coupon turned 180 degrees: the key must keep it out (D2)")
    g.add_argument("--turned-test", type=int, metavar="SLOT",
                   help="risks.md EL-2's test in this slot: the test coupon plugged in turned (before hole 39's plug "
                        "is fitted); bench supply only")
    g.add_argument("--write-descriptor", type=lambda v: int(v, 0), metavar="SERIAL",
                   help="if a test coupon's EEPROM is blank, write its descriptor with this serial")
    g.add_argument("--no-loads", action="store_true", help="skip the self-test's 30 ohm load steps")
    g.add_argument("--climit", action="store_true",
                   help="run the current-limit steps (drives each switch into its limit for 15 ms)")
    g.add_argument("--meter", action="store_true", help="ask for meter readings to cross-check the monitors")
    g.add_argument("--meter-tol-pct", type=float, default=0.5, help="the meter's accuracy, %% of reading")
    g.add_argument("--nrst", action="store_true", help="the NRST-with-rails-on check (USART1 console only)")
    g.add_argument("--probe-ma", type=int, help="discovery current for tb slot <n> on probe=<mA>")
    g.add_argument("--no-retry-stale", action="store_true",
                   help="do not work around a stale settle reading (README finding 1): fail the slot instead")
    g.add_argument("--strict-map", action="store_true", help="fail if the firmware's board map is not this checkout's")
    g.add_argument("--board-serial", default=None, help="the serial written on the motherboard")
    g.add_argument("--operator", default="", help="initials of the person at the bench (optional)")
    g.add_argument("--notes", default="", help="a note for the report")
    g.add_argument("--out", type=pathlib.Path, help="report directory")
    g.add_argument("--nets", type=pathlib.Path, help="another nets.py to judge against")
    g.add_argument("--quiet", action="store_true")


def config_from(a, console, port):
    return RunConfig(power=a.power, console=console, bench_ma=a.bench_ma, source=a.source, slots=a.slots,
                     coupons=coupon_map(a.coupon) or None, inj=a.inj, key_check=a.key_check,
                     turned_test=a.turned_test,
                     write_descriptor=a.write_descriptor, loads=not a.no_loads, climit=a.climit, meter=a.meter,
                     meter_tol_pct=a.meter_tol_pct, nrst=a.nrst, strict_map=a.strict_map, probe_ma=a.probe_ma,
                     retry_stale=not a.no_retry_stale,
                     board_serial=a.board_serial or "unknown", operator_name=a.operator, port=port, notes=a.notes)


def finish(a, run, session, out_dir):
    target = report.write(run, out_dir, session.transcript)
    if not a.quiet:
        print(f"\n{run.verdict}" + (f": {run.stop['reason']}" if run.stop else ""))
        if run.stop and run.stop.get("advice"):
            print(run.stop["advice"])
        for s in run.steps:
            if s.status not in ("pass", "skipped"):
                print(f"  {s.status:8} {s.id}: {s.title}")
        print(f"report: {target / 'report.md'}")
    return EXIT.get(run.verdict, 1)


def cmd_run(a):
    if not a.board_serial:
        print("--board-serial is required on the real bench (the serial written on the motherboard)", file=sys.stderr)
        return 1
    console = a.console
    if a.power == "bench" and console != "uart":
        print("--power bench runs on USART1 (--console uart, the STLINK-V3's VCP): with a supply on J1 there is no "
              "USB host, so there is no CDC port", file=sys.stderr)
        return 1
    op = ConsoleOperator()
    if a.climit and not a.yes and not op.confirm(
            "climit", "The current-limit steps drive each slot switch into its limit (about 0.5 W for 15 ms on "
            "+3V3, 1.8 W on +5V, estimates). Run them on a bench, with nothing else in the slots"):
        return 1
    try:
        t = SerialTransport(a.port, a.baud)
    except LinkLost as e:
        print(e, file=sys.stderr)
        return 1
    s = Session(t)
    try:
        run = Bench(s, L.Limits(a.nets), config_from(a, console, a.port), op).run()
    finally:
        t.close()
    return finish(a, run, s, a.out or DEFAULT_OUT)


def cmd_sim(a):
    f = simdev.Faults()
    for spec in a.fault or []:
        simdev.parse_fault(spec, f)
    coupons = dict(tuple(x.split("=")) for x in (a.coupons or "1=test").split(","))
    coupons = {int(k): v for k, v in coupons.items()}
    lim = L.Limits(a.nets)
    dev = simdev.SimDevice(lim, coupons=coupons, source="default" if a.source == "typeA" else (a.source or "3.0A"),
                           usb="unconfigured" if a.power == "bench" else "configured",
                           bench_build=a.power == "bench", faults=f)
    op = ScriptedOperator(simdev.operator_answers(dev, lim))
    s = Session(SimTransport(dev))
    if a.coupon is None:                # the operator declares what the simulated slots hold
        a.coupon = [f"{k}=hall" for k, v in coupons.items() if v == "hall"]
    if a.power == "bench" and not a.bench_ma:
        a.bench_ma = 1000
    a.board_serial = a.board_serial or "SIM-0001"
    run = Bench(s, lim, config_from(a, "sim", "simulated"), op, sleep=lambda _s: None).run()
    return finish(a, run, s, a.out or tempfile.mkdtemp(prefix="tbbench-sim-"))


def cmd_native_sim(a):
    t = ProcessTransport([str(a.exe), "--uart_stdinout"])
    s = Session(t)
    s.drain(quiet_s=0.5, max_s=5.0)

    def host(_k, _t):
        if a.source:
            s.cmd(f"sim source {'default' if a.source == 'typeA' else a.source}")
        s.cmd("sim usb configured")
        return True

    def sim_coupon(n, kind):
        def f(_k, _t):
            s.cmd(f"sim coupon {n} {kind}")
            return True
        return f
    answers = {"host": host}
    for n in L.Limits(a.nets).slots:      # the turned test and the key check move the coupon in the firmware's world
        answers[f"turned_in_S{n}"] = sim_coupon(n, "turned")
        answers[f"turned_out_S{n}"] = sim_coupon(n, "test")
    if a.source:
        s.cmd(f"sim source {'default' if a.source == 'typeA' else a.source}")
    for c in a.sim_cmd or []:
        s.cmd(c)
    a.board_serial = a.board_serial or "NATIVE-SIM"
    if a.power == "bench" and not a.bench_ma:
        a.bench_ma = 1000
    try:
        run = Bench(s, L.Limits(a.nets), config_from(a, "sim", str(a.exe)), ScriptedOperator(answers)).run()
    finally:
        t.close()
    return finish(a, run, s, a.out or tempfile.mkdtemp(prefix="tbbench-native-"))


def cmd_serve_sim(a):
    """The simulated board on a pseudo-terminal, for rehearsing a real run: bench.py run --port <the pty>."""
    import os  # noqa: PLC0415
    import pty  # noqa: PLC0415
    import threading  # noqa: PLC0415
    import tty  # noqa: PLC0415
    f = simdev.Faults()
    for spec in a.fault or []:
        simdev.parse_fault(spec, f)
    coupons = {int(k): v for k, v in (x.split("=") for x in (a.coupons or "1=test").split(","))}
    dev = simdev.SimDevice(L.Limits(), coupons=coupons, source=a.sim_source, usb=a.usb,
                           bench_build=a.usb == "unconfigured", faults=f)
    master, slave = pty.openpty()
    tty.setraw(slave)
    print(f"simulated testbed on {os.ttyname(slave)} (Ctrl-C to stop); for example:\n"
          f"  python bench.py run --port {os.ttyname(slave)} --board-serial REHEARSAL --console uart"
          + (" --power bench --bench-ma 1000" if a.usb == "unconfigured" else ""), flush=True)
    stop = threading.Event()
    try:
        simdev.serve_pty(dev, master, stop)
    except KeyboardInterrupt:
        stop.set()
    finally:
        os.close(master)
        os.close(slave)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("checklist", help="print the manual pre-power-on and bench steps")
    c.add_argument("--format", choices=("text", "md"), default="text")
    c.add_argument("--phase", help="only one phase (unpowered, first power, ...)")
    c.add_argument("--out", type=pathlib.Path, help="write to this file instead of stdout")
    r = sub.add_parser("run", help="the real board, over its CDC ACM or USART1 port")
    r.add_argument("--port", required=True, help="/dev/ttyACM0, COM5, ... (a pyserial URL also works)")
    r.add_argument("--baud", type=int, default=115200)
    r.add_argument("--console", choices=("cdc", "uart"), default="cdc", help="which shell the port reaches")
    r.add_argument("--yes", action="store_true", help="do not ask before the current-limit steps")
    run_options(r)
    sm = sub.add_parser("sim", help="the simulated board (tbbench.simdev)")
    sm.add_argument("--fault", action="append", help="NAME[=VALUE], repeatable; bench.py faults lists them")
    sm.add_argument("--coupons", help="slot=kind,... with kind test|blank|hall|turned (default 1=test): what the "
                                      "simulated slots hold; --coupon N=hall is declared for each hall")
    run_options(sm)
    ns = sub.add_parser("native-sim", help="the bring-up firmware itself on native_sim")
    ns.add_argument("--exe", type=pathlib.Path, required=True, help="the native_sim build's zephyr/zephyr.exe")
    ns.add_argument("--sim-cmd", action="append", help="a 'sim ...' command to send first, e.g. 'sim coupon 2 test'")
    run_options(ns)
    sv = sub.add_parser("serve-sim", help="the simulated board on a pseudo-terminal (POSIX), to rehearse a run")
    sv.add_argument("--fault", action="append", help="NAME[=VALUE], repeatable")
    sv.add_argument("--coupons", help="slot=kind,... (default 1=test)")
    sv.add_argument("--sim-source", default="3.0A", choices=("default", "1.5A", "3.0A", "accessory", "not_attached"))
    sv.add_argument("--usb", default="configured", choices=("configured", "unconfigured"),
                    help="unconfigured: a bench-supply build with no host (rehearse --power bench)")
    sub.add_parser("faults", help="list the simulator's faults")
    a = p.parse_args(argv)
    if a.cmd == "checklist":
        text = checklist.render(a.format, a.phase)
        if a.out:
            a.out.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8", newline="\n")
        else:
            print(text, end="")
        return 0
    if a.cmd == "faults":
        for k, v in simdev.FAULT_HELP.items():
            print(f"  {k:52} {v}")
        return 0
    return {"run": cmd_run, "sim": cmd_sim, "native-sim": cmd_native_sim, "serve-sim": cmd_serve_sim}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
