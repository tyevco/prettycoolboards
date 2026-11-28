#!/usr/bin/env python3
"""Fault injection: does a test fail when the firmware breaks a rule? Each mutation below is a plausible bug in
the bring-up firmware or the lib. For each one this script copies keyboard/firmware (bringup, lib, boards) and
nets.py into a scratch tree, applies the mutation there (the repository is never touched), builds the simulated
board, runs host/test_sim.py (and the lib's ztest cases for a lib mutation), and reports which tests failed and
what the SPEC §3.5 rule monitor of sim/world.c saw.

    source /root/zephyrproject/ENV.sh
    python3 keyboard/firmware/bringup/sim/mutate.py <scratch dir>                 # every mutation, ~1 min each
    python3 keyboard/firmware/bringup/sim/mutate.py <scratch dir> hw_off_no_bus_open suspend_keeps_rails
    python3 keyboard/firmware/bringup/sim/mutate.py <scratch dir> --without-monitor   # the same, the monitor off

Exit status 1 if a mutation survives (no test fails), 0 if every one is caught. --without-monitor shows what the
rule monitor adds: run that way, the sequencing mutations (bus switch, slot lines, 5 V order) survive the other
tests. Results of 2026-11-27 are in ../README.md. This proves the tests can fail; it proves nothing about the
hardware.
"""
import argparse
import os
import pathlib
import re
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
FW = HERE.parents[1]
REPO = FW.parents[1]

# name: [(file under keyboard/firmware, old text, new text)], what it breaks
MUTATIONS = {
    "hw_off_no_bus_open": ([("bringup/src/board.c", "\t\tif (off3 || off5) {\n\t\t\t(void)tb_slot_bus(slot, false);\n"
                             "\t\t}\n", "")], "rails go down with the bus switch closed"),
    "hw_off_no_lines_idle": ([("bringup/src/board.c", "\t\t\t(void)tb_slot_lines(slot, false);\n"
                               "\t\t\t(void)tb_mux_deselect();\n", "\t\t\t(void)tb_mux_deselect();\n")],
                             "CS lines left driven high into a slot whose rails went off"),
    "hw_off_3v3_before_5v": ([("bringup/src/board.c",
                               "\t\tif (off5 || off3) {\n\t\t\t(void)gpio_pin_set_dt(&h->en5, 0);\n\t\t}\n"
                               "\t\tif (off3) {\n\t\t\t(void)gpio_pin_set_dt(&h->en3, 0);",
                               "\t\tif (off3) {\n\t\t\t(void)gpio_pin_set_dt(&h->en3, 0);\n\t\t}\n"
                               "\t\tif (off5 || off3) {\n\t\t\t(void)gpio_pin_set_dt(&h->en5, 0);\n\t\t}\n"
                               "\t\tif (off3) {")], "+3V3 switched off before +5V"),
    "cs_high_before_power": ([("bringup/src/board.c",
                               "\t\terr |= cfg(&h->cs[i], powered ? GPIO_OUTPUT_INACTIVE : GPIO_DISCONNECTED);",
                               "\t\terr |= cfg(&h->cs[i], GPIO_OUTPUT_INACTIVE);")],
                             "chip selects driven high into unpowered slots"),
    "restore_leaves_bus_closed": ([("bringup/src/board.c",
                                    "\t\terr |= cfg(&tb_slots[slot - 1].busen, GPIO_OUTPUT_INACTIVE);",
                                    "\t\terr |= cfg(&tb_slots[slot - 1].busen, GPIO_OUTPUT_ACTIVE);")],
                                  "the boot restore closes every bus switch"),
    "lines_before_descriptor": ([("bringup/src/slot.c", "\tres->on3 = true;\n",
                                  "\tres->on3 = true;\n\t(void)tb_slot_lines(slot, true);\n")],
                                "the slot's lines driven before its descriptor is read (risks.md EL-2)"),
    "no_present_check": ([("bringup/src/board.c", "\tif (slot >= 1 && !(tb.present & BIT(slot - 1))) {\n"
                           "\t\treturn -ENODEV;", "\tif (0) {\n\t\treturn -ENODEV;")],
                         "a slot powered with no coupon in it"),
    "bus_before_5v_no_reopen": ([("bringup/src/slot.c", "\t(void)tb_slot_lines(slot, true);\n\n\tif (tb.budget.on",
                                  "\t(void)tb_slot_lines(slot, true);\n\t(void)tb_slot_bus(slot, true);\n\n"
                                  "\tif (tb.budget.on"),
                                 ("bringup/src/board.c", "\tif (slot >= 1 && (tb.bus_closed & BIT(slot - 1))) {\n"
                                  "\t\t/* SPEC", "\tif (0) {\n\t\t/* SPEC")],
                                "the bus switch closed before +5V comes up"),
    "suspend_keeps_rails": ([("lib/src/budget.c", "\t\tif (b->usb == TB_USB_CONFIGURED) {\n"
                              "\t\t\tb->usb = TB_USB_SUSPENDED;\n\t\t}\n\t\treturn mark_off(b, b->on);",
                              "\t\tif (b->usb == TB_USB_CONFIGURED) {\n\t\t\tb->usb = TB_USB_SUSPENDED;\n\t\t}\n"
                              "\t\treturn 0;")], "USB suspend leaves the rails on"),
    "reset_keeps_configured": ([("lib/src/budget.c", "\tcase TB_USB_EV_RESET:\n\tcase TB_USB_EV_DISCONNECTED:\n"
                                 "\t\tb->usb = TB_USB_UNCONFIGURED;\n",
                                 "\tcase TB_USB_EV_RESET:\n\tcase TB_USB_EV_DISCONNECTED:\n")],
                               "a bus reset does not return to the unconfigured 100 mA"),
    "disconnect_keeps_rails": ([("lib/src/budget.c", "\tcase TB_USB_EV_RESET:\n\tcase TB_USB_EV_DISCONNECTED:\n",
                                 "\tcase TB_USB_EV_DISCONNECTED:\n\t\treturn 0;\n\tcase TB_USB_EV_RESET:\n")],
                               "VBUS removal leaves the rails on"),
    "power_while_unconfigured": ([("lib/src/budget.c", "\tif (b->usb != TB_USB_CONFIGURED) {\n"
                                   "\t\treturn TB_REFUSE_UNCONFIGURED;\n\t}\n", "")],
                                 "slot power before SET_CONFIGURATION"),
    "override_raises": ([("lib/src/budget.c", "\treturn b->override_ma != 0 ? min_u32(ma, b->override_ma) : ma;",
                          "\treturn b->override_ma != 0 ? b->override_ma : ma;")], "an override raises the budget"),
}
NO_MONITOR = ("bringup/host/test_sim.py", '        assert flags["rule_violations"] == 0',
              '        assert True or flags["rule_violations"] == 0')


def tree(root):
    if root.exists():
        shutil.rmtree(root)
    for d in ("bringup", "lib", "boards"):
        # copy without metadata: fresh mtimes, so the build recompiles what a previous mutation changed
        shutil.copytree(FW / d, root / "keyboard" / "firmware" / d, copy_function=shutil.copy,
                        ignore=shutil.ignore_patterns("__pycache__", "build"))
    design = root / "keyboard" / "hardware" / "design"
    design.mkdir(parents=True)
    shutil.copy(REPO / "keyboard" / "hardware" / "design" / "nets.py", design / "nets.py")
    shutil.copytree(REPO / "keyboard" / "hardware" / "design" / "sheets", design / "sheets",
                    copy_function=shutil.copy, ignore=shutil.ignore_patterns("__pycache__"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("scratch", type=pathlib.Path)
    ap.add_argument("names", nargs="*", help=f"a subset of: {', '.join(MUTATIONS)}")
    ap.add_argument("--without-monitor", action="store_true")
    args = ap.parse_args(argv)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    root, build, libbuild = args.scratch / "tree", args.scratch / "sim", args.scratch / "lib"
    survived = []
    for name in args.names or MUTATIONS:
        edits, what = MUTATIONS[name]
        if args.without_monitor:
            edits = edits + [NO_MONITOR]
        tree(root)
        for f, old, new in edits:
            p = root / "keyboard" / "firmware" / f
            src = p.read_text()
            if old not in src:
                sys.exit(f"mutate: {name}: the mutation no longer applies to {f}")
            p.write_text(src.replace(old, new, 1))
        b = subprocess.run(["west", "build", "-p", "auto", "-b", "native_sim/native/64",
                            str(root / "keyboard" / "firmware" / "bringup"), "-d", str(build)],
                           capture_output=True, text=True, env=env)
        if b.returncode != 0:
            print(f"[{name}] does not build:\n{b.stdout[-1500:]}")
            survived.append(name)
            continue
        t = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                            str(root / "keyboard" / "firmware" / "bringup" / "host")], capture_output=True,
                           text=True, env=dict(env, TB_SIM_EXE=str(build / "zephyr" / "zephyr.exe")))
        failed = sorted({ln.split("::")[1].split(" ")[0] for ln in t.stdout.splitlines()
                         if ln.startswith(("FAILED", "ERROR")) and "::" in ln})
        # pytest also echoes the assertion's source line, whose f-string reads "rule broken: {flags[...]}": skip it
        seen = sorted({m.group(1) for m in re.finditer(r"rule broken: ([^\s{]\S*)", t.stdout)})
        lib_fail = []
        if any(f.startswith("lib/") for f, _o, _n in edits):
            lb = subprocess.run(["west", "build", "-p", "auto", "-b", "native_sim/native/64",
                                 str(root / "keyboard" / "firmware" / "lib" / "tests"), "-d", str(libbuild)],
                                capture_output=True, text=True, env=env)
            if lb.returncode == 0:
                o = subprocess.run([str(libbuild / "zephyr" / "zephyr.exe")], capture_output=True, text=True,
                                   timeout=300)
                lib_fail = [ln.split()[2] for ln in o.stdout.splitlines() if ln.strip().startswith("FAIL - ")]
        caught = t.returncode != 0 or lib_fail
        if not caught:
            survived.append(name)
        print(f"[{name}] {'CAUGHT' if caught else 'SURVIVED'} ({what}): sim tests failed {failed or 'none'}; "
              f"rule monitor saw {seen or 'nothing'}; lib ztest failed {lib_fail or 'none'}")
    if survived:
        print(f"mutate: {len(survived)} survived: {', '.join(survived)}")
    return 1 if survived else 0


if __name__ == "__main__":
    sys.exit(main())
