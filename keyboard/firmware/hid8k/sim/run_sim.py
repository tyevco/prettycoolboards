#!/usr/bin/env python3
"""Build and run the hid8k USB simulation, then judge its captured stream with the host tool.

For each variant it builds sim/ for native_sim/native/64 (or --target native_sim, 32-bit, which
needs gcc-multilib), runs it with a capture file and a CDC log, checks that the simulation's own
checks passed (its last line, "hid8k-sim: PASS ..."), and feeds the capture through
host/hid8k_analysis.py (sim_capture.py --expect) to check the verdict the variant's bus should
give.

  stock  high speed, Zephyr v4.5.0's own virtual host controller: 1 ms frames after the bus reset
  hs     high speed, the simulation's copy that keeps 125 us microframes (hs_fix.conf)
  fs     full speed (fs.overlay): what a full-speed-only port or hub does to the bench

Run from a Zephyr v4.5.0 environment (ZEPHYR_BASE set, west on PATH), for example:

  python3 keyboard/firmware/hid8k/sim/run_sim.py --build-dir /tmp/hid8k-sim
  python3 keyboard/firmware/hid8k/sim/run_sim.py --variant hs \
      --board-elf keyboard/firmware/build/hid8k/zephyr/zephyr.elf
  python3 keyboard/firmware/hid8k/sim/run_sim.py --target native_sim --build-dir /tmp/hid8k-sim32

It exits 0 only if every step of every variant passed. Nothing here measures hardware: see
README.md, "USB simulation".
"""

from __future__ import annotations

import argparse
import difflib
import os
import re
import subprocess
import sys
import time

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
VARIANTS = {
    "stock": {"extra": [], "expect": "1000"},
    "hs": {"extra": ["-DEXTRA_CONF_FILE=hs_fix.conf"], "expect": "125"},
    "fs": {"extra": ["-DEXTRA_DTC_OVERLAY_FILE=fs.overlay"], "expect": "fs"},
}
# The keyboard reports in each capture: the simulation presses the button once while capturing.
KBD_REPORTS = 2
RESULT = re.compile(r"^hid8k-sim: (PASS|FAIL): (\d+) checks, (\d+) failed, (\d+) known issues, "
                    r"(\d+) anomalies")


def run(cmd, log=None, env=None, timeout=None) -> int:
    print("$ " + " ".join(cmd), flush=True)
    if log is None:
        return subprocess.call(cmd, env=env, timeout=timeout)
    with open(log, "w", encoding="utf-8", newline="\n") as f:
        return subprocess.call(cmd, stdout=f, stderr=subprocess.STDOUT, env=env, timeout=timeout)


def driver_diff(out_path: str) -> str:
    """The simulation's driver copy against Zephyr's, written out in full; a one-line summary."""
    zephyr = os.path.join(os.environ["ZEPHYR_BASE"], "drivers", "usb", "uhc", "uhc_virtual.c")
    copy = os.path.join(HERE, "drivers", "uhc_virtual_hs.c")
    with open(zephyr, encoding="utf-8") as f:
        a = f.readlines()
    with open(copy, encoding="utf-8") as f:
        b = f.readlines()
    diff = list(difflib.unified_diff(a, b, zephyr, copy))
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(diff)
    added = sum(1 for ln in diff if ln.startswith("+") and not ln.startswith("+++"))
    removed = sum(1 for ln in diff if ln.startswith("-") and not ln.startswith("---"))
    return f"{added} lines added, {removed} removed against {zephyr} (full diff: {out_path})"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--build-dir", default=os.path.join(HERE, "..", "..", "build", "hid8k-sim"),
                   help="one sub-directory per variant (default keyboard/firmware/build/hid8k-sim)")
    p.add_argument("--variant", choices=("stock", "hs", "fs", "both", "all"), default="all",
                   help="both = stock and hs; all (default) = stock, hs and fs")
    p.add_argument("--target", choices=("native_sim/native/64", "native_sim"),
                   default="native_sim/native/64",
                   help="native_sim is 32-bit (gcc -m32: needs gcc-multilib)")
    p.add_argument("--no-build", action="store_true", help="reuse the existing builds")
    p.add_argument("--stream-s", type=int, default=3,
                   help="seconds of undisturbed stream to check and capture (default 3)")
    p.add_argument("--board-elf", help="also compare the descriptors in this board zephyr.elf "
                                       "with the simulation's (usb_descriptors_elf.py)")
    args = p.parse_args(argv)

    if "ZEPHYR_BASE" not in os.environ:
        print("ZEPHYR_BASE is not set: source the Zephyr environment first")
        return 2

    env = dict(os.environ, ZEPHYR_TOOLCHAIN_VARIANT="host")
    os.makedirs(args.build_dir, exist_ok=True)
    names = {"both": ["stock", "hs"], "all": ["stock", "hs", "fs"]}.get(args.variant,
                                                                      [args.variant])
    summary = []
    ok_all = True

    for name in names:
        v = VARIANTS[name]
        bdir = os.path.abspath(os.path.join(args.build_dir, name))
        steps = []

        if not args.no_build:
            rc = run(["west", "build", "-p", "always", "-b", args.target, HERE,
                      "-d", bdir, "--"] + v["extra"], log=bdir + ".build.log", env=env)
            steps.append(("build", rc == 0, f"log {bdir}.build.log"))
            if rc != 0:
                summary.append((name, steps))
                ok_all = False
                continue

        cap = os.path.join(bdir, "capture.bin")
        cdc = os.path.join(bdir, "cdc.log")
        for path in (cap, cdc):
            open(path, "wb").close()  # the simulation opens them, it cannot create them
        t0 = time.monotonic()
        run_log = os.path.join(bdir, "run.log")
        rc = run([os.path.join(bdir, "zephyr", "zephyr.exe"), f"--hid8k_capture={cap}",
                  f"--hid8k_cdc_log={cdc}", f"--hid8k_stream_s={args.stream_s}"],
                 log=run_log, timeout=3600)
        wall = time.monotonic() - t0
        last = None
        with open(run_log, encoding="utf-8", errors="replace") as f:
            for ln in f:
                if RESULT.match(ln):
                    last = ln.strip()
        steps.append(("simulation", rc == 0 and last is not None and last.startswith(
            "hid8k-sim: PASS"), f"{last or 'no result line'}; {wall:.0f} s wall; log {run_log}"))

        rc = run([sys.executable, "-B", os.path.join(HERE, "sim_capture.py"), cap,
                  "--cdc-log", cdc, "--expect", v["expect"], "--kbd-reports", str(KBD_REPORTS),
                  "--json", os.path.join(bdir, "analysis.json")],
                 log=os.path.join(bdir, "analysis.txt"))
        steps.append(("host analysis", rc == 0, f"{os.path.join(bdir, 'analysis.txt')}"))

        if name == "hs":
            steps.append(("driver copy", True, driver_diff(os.path.join(bdir, "uhc_virtual.diff"))))

        if args.board_elf:
            rc = run([sys.executable, "-B", os.path.join(HERE, "usb_descriptors_elf.py"),
                      "--compare", args.board_elf, os.path.join(bdir, "zephyr", "zephyr.exe")],
                     log=os.path.join(bdir, "descriptors.txt"))
            steps.append(("descriptors vs board", rc == 0,
                          os.path.join(bdir, "descriptors.txt")))

        ok_all &= all(ok for _, ok, _ in steps)
        summary.append((name, steps))

    print()
    for name, steps in summary:
        for step, ok, text in steps:
            print(f"{'ok  ' if ok else 'FAIL'} {name:<5} {step:<20} {text}")
    print(f"\nrun_sim: {'PASS' if ok_all else 'FAIL'}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
