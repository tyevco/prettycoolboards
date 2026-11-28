#!/usr/bin/env python3
"""Fault injection into the harness itself: each mutation below breaks one safety or judging rule, in a scratch
copy of this directory, and the test suite must fail for every one of them. A mutation that survives is a rule
the tests do not hold.

    python keyboard/tools/bench/mutate.py <scratch-dir>         (a minute or two; the native_sim tests are skipped)
"""

import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent

MUTATIONS = [
    ("an over-current error token is not dangerous", "tbbench/limits.py",
     'DANGER_ERR_TOKENS = {"fault_3v3", "over_3v3", "fault_5v", "over_5v"}', 'DANGER_ERR_TOKENS = {"over_5v"}'),
    ("trip events are not dangerous", "tbbench/limits.py",
     "DANGER_FINDINGS = OVERCURRENT_FINDINGS | POWER_FINDINGS | BACKPOWER_FINDINGS", "DANGER_FINDINGS = set()"),
    ("no event replay around power commands", "tbbench/procedure.py",
     [("        if power:\n            self.replay()\n        st.commands", "        st.commands"),
      ('        if power or r.err == "slot_off":\n            self.replay()\n', "")]),
    ("no replay before a power command (a lost trip re-powered)", "tbbench/procedure.py",
     "        if power:\n            self.replay()\n        st.commands", "        st.commands"),
    ("no replay after a power command", "tbbench/procedure.py",
     'if power or r.err == "slot_off":', 'if r.err == "slot_off":'),
    ("no replay when a slot is found off unexpectedly", "tbbench/procedure.py",
     'if power or r.err == "slot_off":', "if power:"),
    ("no tb safe on a dangerous stop", "tbbench/procedure.py",
     '                r = self.s.cmd("tb safe", 5.0)', '                r = self.s.cmd("tb usb", 5.0)'),
    ("lane tolerance ten times wider", "tbbench/procedure.py",
     "tol = L.TEST_LANE_TOL * 1e6 + 2 * 1e6 / (1 << bits)", "tol = 10 * L.TEST_LANE_TOL * 1e6"),
    ("the firmware's lane verdict trusted", "tbbench/procedure.py",
     "            mine = abs(ppm - ratio * 1e6) <= tol\n", "            mine = bool(x.get('ok', 1))\n"),
    ("off rails not checked for back-powering", "tbbench/procedure.py",
     "                live = mv > L.LIVE_OFF_MV or abs(ua) > L.LIVE_OFF_UA\n", "                live = False\n"),
    ("CAL not compared", "tbbench/procedure.py",
     "st.check(f\"INA226 0x{addr:02x} CAL\", rec.get(\"cal\") == m.cal,",
     "st.check(f\"INA226 0x{addr:02x} CAL\", True,"),
    ("descriptor CRC not checked on the host", "tbbench/desc_check.py",
     "    if want != got:\n        raise DescError(\"crc\"", "    if False:\n        raise DescError(\"crc\""),
    ("current limit above its window is not dangerous", "tbbench/procedure.py",
     "danger = i > hi or x.get(\"cleared\") == 0", "danger = False"),
    ("no settle wait before judged readings", "tbbench/procedure.py",
     "        self.sleep(2 * self.ina_period_s + 0.01)\n", "        pass\n"),
    ("a slot left on before the next one", "tbbench/procedure.py",
     "        self.run_step(*finally_steps[:3], finally_steps[3], n, n)\n", "        pass\n"),
    ("the budget not compared with nets.vsys_budget", "tbbench/procedure.py",
     'st.check("VSYS budget for the advertisement", b.get("limit_ma") == want,',
     'st.check("VSYS budget for the advertisement", True,'),
    ("a stale reading retried without proof", "tbbench/procedure.py",
     "        if mv >= L.FW_MIN_3V3_MV:\n            first.verdict", "        if True:\n            first.verdict"),
    ("a slot's current not judged against its declaration", "tbbench/procedure.py",
     'st.check(f"{rail} current", ma < dlim,', 'st.check(f"{rail} current", True,'),
    ("the advertisement not compared with the declared source", "tbbench/procedure.py",
     'st.check("advertisement as the operator declared", source == want,',
     'st.check("advertisement as the operator declared", True,'),
    ("an INA226's identity not checked at boot", "tbbench/procedure.py",
     'ok = rec is not None and rec.get("err") == 0 and rec.get("mfr") == 0x5449 and rec.get("die") == 0x2260',
     "ok = True"),
    ("a slot's rails not read back after off", "tbbench/procedure.py",
     '            live = rec["bus_mv"] > L.LIVE_OFF_MV or abs(rec["current_ua"]) > L.LIVE_OFF_UA\n',
     "            live = False\n"),
    ("tb safe taken as proof without reading the rails", "tbbench/procedure.py",
     "                return not live and not unread\n", "                return True\n"),
    ("a silent monitor counted as a dead rail", "tbbench/procedure.py",
     "                        unread.append(m.rail)\n", "                        pass\n"),
    ("a lane's converters not compared", "tbbench/procedure.py",
     "            mine = abs(d) <= L.AGREE_PPM\n", "            mine = True\n"),
    ("the loopback's pattern count not checked", "tbbench/procedure.py",
     'mine = x.get("failed") == 0 and x.get("patterns") == want', 'mine = x.get("failed") == 0'),
    ("the descriptor's fields not compared host against firmware", "tbbench/procedure.py",
     'st.check(f"{k}: host == firmware", h.get(k) == fw.get(k),', 'st.check(f"{k}: host == firmware", True,'),
    ("the setup lines sent in one burst (a 64-byte shell ring)", "tbbench/protocol.py",
     "                self.drain(quiet_s=0.05, max_s=1.0)\n", "                pass\n"),
    ("the board map judged against the header only, not nets.py", "tbbench/procedure.py",
     "want = L.map_hash_from_nets(self.L.nets_path)", "want = None"),
    ("CAL rounded half to even (not as Zephyr's driver)", "tbbench/limits.py",
     "    return (5120000000 + den // 2) // den\n", "    return round(5120000000 / den)\n"),
    ("a markdown cell's pipe not escaped (checklist)", "tbbench/checklist.py",
     'return v.replace("|", "\\\\|")', "return v"),
    # --- the owner's decisions of 2026-11-27 (D1, D2, D4, D7) and the descriptor of record ------------------------
    ("D7: AN0's lift with INJ high not judged", "tbbench/procedure.py",
     'st.check("AN0 lift with INJ high", lo <= lift[0] <= top,', 'st.check("AN0 lift with INJ high", True,'),
    ("D7: the taps' share of the lift not judged", "tbbench/procedure.py",
     "st.check(f\"AN{k} follows AN0's lift\", abs(share - want) <= tol,",
     "st.check(f\"AN{k} follows AN0's lift\", True,"),
    ("D7: the self-test run with INJ still high", "tbbench/procedure.py",
     '            self.run_.slots[n]["inj_left_high"] = True\n', "            pass\n"),
    ("D7: INJ back-feeding an off coupon not checked", "tbbench/procedure.py",
     'rec["bus_mv"] <= L.INJ_BACKFEED_MV,', "True,"),
    ("D1: a Hall coupon powered on its record after a bus error (it may be turned)", "tbbench/procedure.py",
     'if kind == "hall" and r.err in ("blank", *L.DESC_FORMAT_ERRORS):',
     'if kind == "hall" and r.err in ("blank", "desc_bus", *L.DESC_FORMAT_ERRORS):'),
    ("D1: the test coupon's descriptor written onto a Hall coupon", "tbbench/procedure.py",
     'self.cfg.write_descriptor is not None and kind == "test":', "self.cfg.write_descriptor is not None:"),
    ("D1: the Hall coupon's slots not after the test coupon's", "tbbench/procedure.py",
     "key=lambda n: (order.get(self.coupon_of(n), len(order)), n))", "key=lambda n: n)"),
    ("D2: I2C4 not freed after a bus error (a turned coupon holds SCL)", "tbbench/procedure.py",
     '            if err == "desc_bus":\n                self._recover_i2c4(st)\n', ""),
    ("D2: the operator's answer to the key check ignored", "tbbench/procedure.py",
     'st.check("a turned test coupon stays out", stayed,', 'st.check("a turned test coupon stays out", True,'),
    ("D2: lines driven into a turned coupon not judged", "tbbench/procedure.py",
     'st.check("no slot line driven into the turned coupon", seen is False,',
     'st.check("no slot line driven into the turned coupon", True,'),
    ("D4: VSYS not held to the USB-C load line", "tbbench/procedure.py",
     'st.check("VSYS on or above the USB-C load line", mv >= ll,',
     'st.check("VSYS on or above the USB-C load line", True,'),
    ("the descriptor of record's validity ignored", "tbbench/procedure.py",
     'st.check("descriptor of record valid (descriptor.py)", rec.valid, rec.path.split("keyboard/")[-1] or kind,',
     'st.check("descriptor of record valid (descriptor.py)", True, rec.path.split("keyboard/")[-1] or kind,'),
    ("the EEPROM's type not compared with its descriptor of record", "tbbench/procedure.py",
     'st.check("type as its descriptor of record", h.get("type") == f.get("type"),',
     'st.check("type as its descriptor of record", True,'),
    ("the EEPROM's declared currents not compared with the record", "tbbench/procedure.py",
     "h.get(key) == (f.get(key) or 0),", "True,"),
    ("descriptor.py's own check of the record skipped", "tbbench/desc_check.py",
     "        img = tool.encode(d)\n        tool.check_image(img)\n        x = tool.decode(img)\n",
     "        img = b''\n        x = d\n"),
    # --- the review of 2026-11-28: every power-on judged, a declared coupon looked for, the simulator as cmds.c -----
    ("the slot's currents not judged again before the self-test", "tbbench/procedure.py",
     '        self._judge_slot_rails(st, n, "before the self-test")\n', ""),
    ("tb trips' own per-rail readings not judged", "tbbench/procedure.py",
     'st.check(f"{rail} current (tb trips)", ua / 1000.0 < dlim,', 'st.check(f"{rail} current (tb trips)", True,'),
    ("a refused descriptor's dump powered without a judgement", "tbbench/procedure.py",
     '        self._judge_powered(st, n, ma3, "for the descriptor dump")\n', ""),
    ("the keep phase of a descriptor write not judged", "tbbench/procedure.py",
     '                self._judge_powered(st, n, self._record_ma3(n), "with +3V3 alone, before the write")\n',
     "                pass\n"),
    ("the NRST test's rail not judged before the reset", "tbbench/procedure.py",
     '        self._judge_powered(st, slot, self._record_ma3(slot), "for the reset test")\n', ""),
    ("a refused descriptor dumped at the 250 mA rule, not its record's current", "tbbench/procedure.py",
     '        return (rec.facts.get("i3v3_ma") or 250) if rec.valid else 250\n', "        return 250\n"),
    ("a declared coupon that does not read present only skipped", "tbbench/procedure.py",
     "            if n in (self.cfg.coupons or {}):\n", "            if False:\n"),
    ("the slots declared by --coupon not walked", "tbbench/procedure.py",
     "sorted(set(self.present) | set(self.cfg.coupons or {}))", "list(self.present)"),
    ("an off rail's current judged by its sign (back-feeding missed)", "tbbench/procedure.py",
     "                live = mv > L.LIVE_OFF_MV or abs(ua) > L.LIVE_OFF_UA\n",
     "                live = mv > L.LIVE_OFF_MV or ua > L.LIVE_OFF_UA\n"),
    ("the stale retry restores the monitors before a stop reaches tb safe", "tbbench/procedure.py",
     "        r = self.cmd(self._slot_on_line(n), power=True)\n        for rail in rails:\n"
     "            self.cmd(f\"tb ina cfg {rail} 16 1100 1100 7\")\n",
     "        try:\n            r = self.cmd(self._slot_on_line(n), power=True)\n        finally:\n"
     "            for rail in rails:\n                self.cmd(f\"tb ina cfg {rail} 16 1100 1100 7\")\n"),
    ("+5V judged against VSYS as it read at the monitors step", "tbbench/procedure.py",
     '                if v is not None and v.get("ok") == 1:\n                    self.vsys_mv = v["bus_mv"]\n',
     "                pass\n"),
    ("the simulator without the firmware's INA226 alert", "tbbench/simdev.py",
     "            if ua > self._alert_ua(r):\n", "            if False:\n"),
    ("the simulator answers argument counts the firmware's shell rejects", "tbbench/simdev.py",
     "        if not mand <= len(words) - 1 <= mand + opt:\n", "        if False:\n"),
    ("the host reads G-line records without the firmware's checks", "tbbench/desc_check.py",
     '            if g > 5:\n                raise DescError("value", f"G-line {g}")\n', ""),
]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(__doc__)
        return 2
    scratch = pathlib.Path(argv[0]).resolve()      # pytest runs with cwd=scratch: a relative path would double
    scratch.mkdir(parents=True, exist_ok=True)
    survived = []
    for name, rel, *edit in [("none (the baseline must pass)", None), *MUTATIONS]:
        pairs = edit[0] if edit and isinstance(edit[0], list) else [tuple(edit)] if edit else []
        work = scratch / "bench"
        if work.exists():
            shutil.rmtree(work)
        shutil.copytree(HERE, work, ignore=shutil.ignore_patterns("__pycache__", "runs"))
        if rel is not None:
            f = work / rel
            text = f.read_text()
            stale = [old for old, _new in pairs if text.count(old) != 1]
            if stale:
                print(f"STALE    {name}: a pattern is not in {rel} exactly once: {stale[0][:60]!r}")
                survived.append(name)
                continue
            for old, new in pairs:
                text = text.replace(old, new, 1)
            f.write_text(text)
        env = {"PYTHONDONTWRITEBYTECODE": "1", "PATH": "/usr/bin:/bin", "TB_SIM_EXE": "/nonexistent",
               "TBBENCH_REPO": str(HERE.parents[2])}
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", str(work / "tests")],
                           capture_output=True, text=True, env=env, cwd=str(scratch), timeout=600)
        caught = r.returncode != 0
        if rel is None:
            if caught:
                print("BASELINE FAILS: fix the tests before mutating\n" + r.stdout[-3000:])
                return 1
            print("baseline passes")
            continue
        print(f"{'caught ' if caught else 'SURVIVED'} {name}")
        if not caught:
            survived.append(name)
    print(f"\n{len(MUTATIONS) - len(survived)} of {len(MUTATIONS)} mutations caught")
    return 1 if survived else 0


if __name__ == "__main__":
    sys.exit(main())
