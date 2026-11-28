"""SPEC section 10's bring-up order for stage A1 (steps 5 to 8), as checked steps against the bring-up firmware.

Rev A is brought up in two stages (the owner's decision D1 of 2026-11-27, SPEC §1, §10): A1 is the motherboard, the
test coupon and the Hall-effect coupon; A2 (haptics, coil, shear, TMR, the latency rig) comes later and has no
procedure here. The walk:

  link, safe       the firmware's identity and protocol version; every rail off (tb safe)
  boot             step 5: the boot report (expanders and mux restored, 13 monitors identified, CAL as SPEC §3.4)
  expanders        step 5: the three TCA9535s, their pins as nets.py names them, every output in its safe state
  monitors         step 5: the 13 INA226s at their addresses, idle currents and voltages, nothing live on an off
                   rail, VSYS against the USB-C load line (D4 of 2026-11-27)
  typec            step 5: U_CC (TUSB320LAI) and the source's advertisement, and the VSYS budget it gives (SPEC §3.2)
  usb              step 6: enumerated at high speed (CDC), or the bench-supply mode (USART only)
  nrst             step 5 (optional): rails on, NRST, the firmware puts every expander and the mux back (SPEC §3.5)
  turned           risks.md EL-2's test (optional, bench supply): the test coupon plugged in turned 180 degrees
                   before the key's plug is fitted; the firmware must refuse it without driving a line
  slot <n> ...     step 7, every slot with a test coupon first: the key (optional, D2), slot on without a trip, the
                   descriptor checked on the host and against its descriptor of record (descriptor.py), the lanes
                   against the test coupon's dividers, INJ into the AN0 lane (optional, D7), the self-test (loopback,
                   load steps, current limits), a meter cross-check (optional), no finding left, and the slot off
                   again with nothing live. Then step 8's Hall coupon (A1): slot on (on its descriptor of record if
                   the firmware cannot read its EEPROM), the descriptor, its lanes recorded, no finding, slot off
  final            tb safe and a last look at the event ring

Every reading is judged here from the raw numbers, against limits.py, besides the firmware's own verdict; a
disagreement between the two is a failure. The first DANGEROUS failure (any over-current, VSYS power-good lost, an
off rail that reads live, a command that changed power and never answered) stops the run: the harness sends
"tb safe", confirms every rail off, and marks the rest not run.
"""

from __future__ import annotations

import datetime
import time
from dataclasses import asdict, dataclass, field

from . import desc_check
from . import limits as L
from .protocol import CommandTimeout, LinkLost, ProtocolError

VERDICT_ORDER = {"pass": 0, "skip": 0, "info": 0, "warn": 1, "fail": 2, "error": 2, "danger": 3}


@dataclass
class Check:
    name: str
    verdict: str                 # pass | warn | fail | danger | info | skip
    measured: object = None
    limit: str = ""
    unit: str = ""
    ref: str = ""
    detail: str = ""


@dataclass
class Step:
    id: str
    title: str
    spec: str
    slot: int | None = None
    status: str = "not_run"      # pass | warn | fail | danger | error | skipped | not_run
    checks: list = field(default_factory=list)
    commands: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    elapsed_s: float = 0.0

    def add(self, name, verdict, measured=None, limit="", unit="", ref="", detail=""):
        c = Check(name, verdict, measured, limit, unit, ref, detail)
        self.checks.append(c)
        if verdict == "danger":
            raise DangerStop(f"{self.id}: {name}" + (f" ({detail})" if detail else ""), self)
        return c

    def check(self, name, ok, measured=None, limit="", unit="", ref="", detail="", bad="fail"):
        return self.add(name, "pass" if ok else bad, measured, limit, unit, ref, detail)

    def worst(self):
        """The step's status: its worst check. A step whose every check is a skip was skipped (an option asked for
        and not done: the run is then INCOMPLETE, not PASS); one of only info and skip checks passes."""
        bad = [c.verdict for c in self.checks if VERDICT_ORDER.get(c.verdict, 0) > 0]
        if not bad:
            return "skipped" if self.checks and all(c.verdict == "skip" for c in self.checks) else "pass"
        return max(bad, key=lambda v: VERDICT_ORDER[v])


class DangerStop(Exception):
    def __init__(self, reason, step=None):
        super().__init__(reason)
        self.reason, self.step = reason, step


class SkipSlot(Exception):
    """The rest of this slot's steps cannot run (the slot is off)."""


class AbortRun(Exception):
    """A prerequisite failed: nothing after this can be judged (not dangerous)."""


@dataclass
class RunConfig:
    power: str = "usb"               # usb: J1 on a host (CDC or USART); bench: a current-limited supply, USART only
    console: str = "cdc"             # cdc | uart | sim: which port the harness is on (NRST needs uart)
    bench_ma: int | None = None      # bench mode: the supply's current limit, mA
    source: str | None = None        # what the source advertises: default | 1.5A | 3.0A | typeA (None: not judged)
    slots: list | None = None        # slots to test; None = every slot whose PRESENT_N reads low
    coupon: str = "test"             # what is in a slot that `coupons` does not name (A1: test | hall)
    coupons: dict | None = None      # slot -> the coupon the operator plugged in there (test | hall)
    inj: bool = False                # D7: INJ into the test coupon's AN0 lane (the operator drives INJ from TP1)
    key_check: bool = False          # D2: the operator tries each test coupon turned 180 degrees (it must stay out)
    turned_test: int | None = None   # risks.md EL-2's test in this slot (bench supply, before the key plug is fitted)
    write_descriptor: int | None = None   # a serial: write the test coupon's descriptor if its EEPROM is blank
    loads: bool = True               # the self-test's load steps (30 ohm on +3V3 and +5V)
    climit: bool = False             # the current-limit steps: drive the switches into their limits on purpose
    meter: bool = False              # ask for meter readings to cross-check the monitors
    meter_tol_pct: float = 0.5       # the meter's own accuracy, % of reading
    nrst: bool = False               # SPEC §10 step 5's NRST-with-rails-on check (the operator presses NRST)
    strict_map: bool = False         # fail (not warn) if the firmware's board map is not this checkout's
    probe_ma: int | None = None      # tb slot <n> on probe=<mA>
    retry_stale: bool = True         # after a low_3v3 that a fresh reading shows was stale, retry at 2.2 ms results
    board_serial: str = "unknown"
    operator_name: str = ""
    port: str = ""
    notes: str = ""


@dataclass
class Run:
    started: str
    config: dict
    steps: list = field(default_factory=list)
    info: dict = field(default_factory=dict)
    stop: dict | None = None
    slots: dict = field(default_factory=dict)       # slot -> measured calibration and coupon identity
    events: list = field(default_factory=list)
    finished: str = ""
    verdict: str = ""

    def summary(self):
        counts = {}
        for s in self.steps:
            counts[s.status] = counts.get(s.status, 0) + 1
        return counts


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


class _Recorded:
    """The operator, with every prompt and its answer written into the current step's notes (the report then says
    what a person did at the bench, not only what the firmware printed)."""

    def __init__(self, op, bench):
        self._op, self._bench = op, bench

    def __getattr__(self, name):
        return getattr(self._op, name)

    def _note(self, key, answer):
        st = self._bench.step
        if st is not None:
            st.notes.append(f"operator, {key}: {answer}")
        return answer

    def confirm(self, key, text):
        a = self._op.confirm(key, text)
        return self._note(key, "done" if a else "skipped") == "done"

    def ask(self, key, text):
        a = self._op.ask(key, text)
        self._note(key, {True: "yes", False: "no", None: "skipped"}[a])
        return a

    def measure(self, key, text, unit):
        a = self._op.measure(key, text, unit)
        self._note(key, "skipped" if a is None else f"{a:g} {unit}")
        return a


class Bench:
    def __init__(self, session, limits=None, config=None, operator=None, sleep=time.sleep):
        from .prompts import NullOperator  # noqa: PLC0415
        self.s = session
        self.L = limits or L.Limits()
        self.cfg = config or RunConfig()
        self.op = _Recorded(operator or NullOperator(), self)
        self.sleep = sleep
        self.run_ = Run(now_utc(), {**asdict(self.cfg), "nets_path": str(self.L.nets_path)})
        self.present = []
        self.ina_period_s = L.ina_period_ms(0x4527) / 1000.0
        self.vsys_mv = 5000
        self.step = None
        self.safe_detail = {}

    # --- plumbing -------------------------------------------------------------------------------------------
    def cmd(self, line, timeout=None, power=False):
        """Run a command inside the current step; record it; check the events it brought in.

        A power command (one that may turn a rail on or off) replays the event ring before it and after it: a trip
        whose line was lost during an earlier command (PROTOCOL.md: a shell may miss event lines) must be known
        before power changes again, or the next command re-powers a slot the firmware has just tripped (the
        self-test's power step calls tb_slot_on() on an off slot, src/coupon_test.c). A command that finds its
        slot off (err=slot_off) replays too: an unexpected slot-off is what a lost trip looks like."""
        st = self.step
        if power:
            self.replay()
        st.commands.append(line)
        try:
            r = self.s.cmd(line, timeout)
        except CommandTimeout as e:
            if power:
                raise DangerStop(f"{st.id}: no answer to {line!r}, which changes power: the board's state is unknown",
                                 st) from e
            st.add(f"answer to {line!r}", "fail", detail=str(e), ref="PROTOCOL.md, Completion")
            raise
        self.check_events()
        if power or r.err == "slot_off":
            self.replay()
        return r

    def replay(self):
        try:
            self.s.replay_events()
        except CommandTimeout:
            self.step.add("tb ev (event replay)", "warn", detail="no answer")
        self.check_events()

    def check_events(self):
        for ev in self.s.take_events():
            self.run_.events.append(dict(ev.fields))
            kind = ev.get("kind")
            st = self.step
            if kind == "trip":
                fnd = ev.get("finding")
                where = f"{ev.get('rail')} slot {ev.get('slot')} value {ev.get('value')}"
                if fnd in L.DANGER_FINDINGS:
                    st.add(f"event trip finding={fnd}", "danger", measured=ev.get("value"), ref="PROTOCOL.md, Events",
                           detail=f"{where}: the firmware's classifier saw it")
                st.add(f"event trip finding={fnd}", "fail" if fnd != "rail_sag" else "warn", ev.get("value"),
                       ref="PROTOCOL.md, Events", detail=where)
            elif kind == "rail_off" and ev.get("reason") in L.DANGER_RAIL_OFF_REASONS:
                st.add(f"event rail_off {ev.get('rail')} reason={ev.get('reason')}", "danger",
                       ref="PROTOCOL.md, Events")
            elif kind == "rail_off" and ev.get("reason") == "usb":
                st.add(f"event rail_off {ev.get('rail')} reason=usb", "fail", ref="SPEC §3.2",
                       detail="the host reset, deconfigured or suspended the device: every slot rail went off")
            elif kind == "usb" and ev.get("event") in ("reset", "suspend", "disconnected"):
                st.add(f"event usb {ev.get('event')}", "warn", ref="SPEC §3.2, §8.4")
            elif kind == "error":
                st.add(f"event error what={ev.get('what')}", "fail", ref="PROTOCOL.md, Events")

    def settle(self):
        """Wait for two fresh INA226 results (SBOS547C: the registers change only when an averaged conversion is
        complete; the bring-up's default configuration completes one every 35.2 ms)."""
        self.sleep(2 * self.ina_period_s + 0.01)

    def fresh_ina(self, rail):
        self.settle()
        r = self.cmd(f"tb ina {rail}")
        rec = next((x for x in r.all("ina") if x.get("rail") == rail), None)
        if rec is not None and isinstance(rec.get("config"), int):
            self.ina_period_s = L.ina_period_ms(rec["config"]) / 1000.0
        return rec

    def run_step(self, sid, title, spec, fn, slot=None, *args):
        st = Step(sid, title, spec, slot)
        self.run_.steps.append(st)
        self.step = st
        t0 = time.monotonic()
        try:
            fn(st, *args)
            st.status = st.worst()
        except DangerStop:
            st.status = "danger"
            raise
        except SkipSlot as e:
            st.status = st.worst() if st.checks else "skipped"
            st.notes.append(str(e))
            raise
        except AbortRun:
            st.status = "fail"
            raise
        except CommandTimeout:
            st.status = "error"
        except ProtocolError as e:
            if isinstance(e, LinkLost):
                raise
            st.status = "error"
            st.notes.append(str(e))
        except BaseException as e:
            st.status = "error"
            st.notes.append(f"{type(e).__name__}: {e}")
            raise
        finally:
            st.elapsed_s = round(time.monotonic() - t0, 3)
        return st

    # --- the run --------------------------------------------------------------------------------------------
    def run(self):
        self.run_.config = {**asdict(self.cfg), "nets_path": str(self.L.nets_path)}   # as the run starts
        plan = [("link", "Link and firmware identity", "PROTOCOL.md", self.st_link),
                ("safe", "Every rail off (tb safe)", "SPEC §3.5, §8.4", self.st_safe),
                ("boot", "Boot report: expanders, mux and monitors restored", "SPEC §10 step 5, §3.5, §8.4",
                 self.st_boot),
                ("expanders", "TCA9535 expanders: pins and safe states", "SPEC §10 step 5, §3.5", self.st_exp),
                ("monitors", "INA226 monitors: presence and idle readings", "SPEC §10 step 5, §3.4", self.st_ina),
                ("typec", "U_CC: the source's advertisement and the VSYS budget", "SPEC §10 step 5, §3.2, §3.8",
                 self.st_typec),
                ("usb", "USB state, or the bench-supply mode", "SPEC §10 step 6, §3.2", self.st_usb)]
        if self.cfg.nrst:
            plan.append(("nrst", "NRST with rails on: the firmware restores the expanders", "SPEC §10 step 5, §3.5",
                         self.st_nrst))
        if self.cfg.turned_test:
            plan.append(("turned", f"S{self.cfg.turned_test}: a turned test coupon is refused, nothing driven",
                         "risks.md EL-2's test; SPEC §4.2, §4.6", self.st_turned))
        try:
            for sid, title, spec, fn in plan:
                self.run_step(sid, title, spec, fn)
            for slot in self.slots_to_test():
                self.run_slot(slot)
            self.run_step("final", "Final safe state and event ring", "SPEC §3.5", self.st_final)
        except DangerStop as e:
            self.emergency(e.reason)
        except AbortRun as e:
            safe = self.try_safe()
            self.run_.stop = {"kind": "abort", "reason": str(e), "safe": safe, "safe_detail": self.safe_detail}
            if not safe:
                self.run_.stop["advice"] = self._unsafe_advice()
        except LinkLost as e:
            self.run_.stop = {"kind": "link_lost", "reason": str(e), "safe": False,
                              "advice": "The link is gone: remove power by hand. The board's state is unknown."}
        except KeyboardInterrupt:
            safe = self.try_safe()
            self.run_.stop = {"kind": "interrupted", "reason": "the operator interrupted the run", "safe": safe,
                              "safe_detail": self.safe_detail,
                              "advice": "tb safe confirmed every rail off." if safe else self._unsafe_advice()}
        except Exception as e:  # noqa: BLE001  (a harness bug must still leave the board safe and a report)
            import traceback  # noqa: PLC0415
            safe = self.try_safe()
            self.run_.stop = {"kind": "harness_error", "reason": f"{type(e).__name__}: {e}", "safe": safe,
                              "safe_detail": self.safe_detail, "traceback": traceback.format_exc(),
                              "advice": "A bug in the harness stopped the run. " + (
                                  "tb safe confirmed every rail off." if safe else self._unsafe_advice())}
        self.finish()
        return self.run_

    def coupon_of(self, n):
        """The coupon the operator says is in slot n (A1: test or hall)."""
        return (self.cfg.coupons or {}).get(n, self.cfg.coupon)

    def slots_to_test(self):
        """The slots to walk, the test coupon's first (SPEC §10 step 7 checks every slot with the test coupon
        "before any sensor does"), then the Hall coupon's (step 8, A1); in slot order within each."""
        slots = list(self.cfg.slots) if self.cfg.slots else \
            sorted(set(self.present) | set(self.cfg.coupons or {}))     # a declared coupon is looked for
        order = {k: i for i, k in enumerate(L.A1_COUPONS)}
        return sorted(slots, key=lambda n: (order.get(self.coupon_of(n), len(order)), n))

    def slot_plan(self, n):
        kind = self.coupon_of(n)
        step = L.SPEC_STEP.get(kind, "SPEC §10 step 8")
        tag = f"S{n} ({kind} coupon)"
        steps = []
        if kind == "test" and self.cfg.key_check:
            steps.append((f"slot{n}.key", f"{tag}: the key keeps it out turned 180 degrees",
                          "SPEC §10 step 7, §4.2 (D2 of 2026-11-27)", self.st_key))
        steps += [(f"slot{n}.on", f"{tag}: slot on without a trip", f"{step}, §3.5, §8.4", self.st_slot_on),
                  (f"slot{n}.desc", f"{tag}: descriptor", "SPEC §4.6, §11 #18", self.st_desc)]
        if kind == "test":
            steps.append((f"slot{n}.lanes", f"{tag}: lanes against the test coupon's dividers", f"{step}, §4.3",
                          self.st_lanes))
            if self.cfg.inj:
                steps.append((f"slot{n}.inj", f"{tag}: INJ into the AN0 lane", f"{step}, §4.7 (D7 of 2026-11-27)",
                              self.st_inj))
            steps.append((f"slot{n}.selftest", f"{tag}: test-coupon self-test", f"{step}, §3.1", self.st_selftest))
        else:
            steps.append((f"slot{n}.lanes", f"{tag}: lanes read (recorded, not judged)", f"{step}, §4.3, §4.8",
                          self.st_lanes))
        if self.cfg.meter:
            steps.append((f"slot{n}.meter", f"{tag}: monitors against a meter", "SPEC §10 step 5, §3.3",
                          self.st_meter))
        steps.append((f"slot{n}.trips", f"{tag}: no finding left", "PROTOCOL.md, tb trips", self.st_trips))
        return steps

    def run_slot(self, n):
        steps = self.slot_plan(n)
        self.run_.slots.setdefault(n, {})["coupon_declared"] = self.coupon_of(n)
        try:
            for sid, title, spec, fn in steps:
                self.run_step(sid, title, spec, fn, n, n)
        except SkipSlot:
            for sid, title, spec, _fn in steps:
                if not any(s.id == sid for s in self.run_.steps):
                    st = Step(sid, title, spec, n, "skipped")
                    st.notes.append("skipped: an earlier step of this slot left it off")
                    self.run_.steps.append(st)
        finally_steps = (f"slot{n}.off", f"S{n} ({self.coupon_of(n)} coupon): slot off, nothing live", "SPEC §3.5",
                         self.st_slot_off)
        self.run_step(*finally_steps[:3], finally_steps[3], n, n)

    def emergency(self, reason):
        safe = self.try_safe()
        self.run_.stop = {"kind": "danger", "reason": reason, "safe": safe, "safe_detail": self.safe_detail,
                          "advice": ("The harness sent tb safe, read every enable back off and every switched "
                                     "rail's monitor dead." if safe else self._unsafe_advice())}
        done = {s.id for s in self.run_.steps}
        for sid in self._planned_after():
            if sid not in done:
                self.run_.steps.append(Step(sid, "not run: the run stopped on a dangerous failure", "", None,
                                            "not_run"))

    def _planned_after(self):
        out = []
        for n in self.slots_to_test():
            out += [sid for sid, *_rest in self.slot_plan(n)] + [f"slot{n}.off"]
        return out + ["final"]

    def try_safe(self):
        """tb safe, then proof: every enable reads off (tb slot) AND every switched rail's monitor reads it dead
        (tb ina all, two fresh results later). The enables alone are not proof: a switch that ignores its enable
        (a damaged TPS2553) leaves the rail live with EN low. A monitor that does not answer leaves its rail
        unconfirmed, so the board is not called safe. +5V_KVM has no monitor (SPEC §3.4): only its enable is read.
        True when confirmed; self.safe_detail says what was not."""
        self.safe_detail = {"live": [], "unread": [], "enables_on": []}
        for _ in range(3):
            try:
                r = self.s.cmd("tb safe", 5.0)
                if not r.ok:
                    continue
                sl = self.s.cmd("tb slot", 5.0)
                on = [x.get("slot") for x in sl.all("slot") if x.get("on3") != 0 or x.get("on5") != 0]
                self.safe_detail["enables_on"] = on
                if on or not sl.all("slot"):
                    continue
                self.settle()
                ina = {x.get("rail"): x for x in self.s.cmd("tb ina all", 5.0).all("ina")}
                live, unread = [], []
                for m in self.L.monitors.values():
                    if not m.switched:
                        continue
                    x = ina.get(m.rail)
                    if x is None or x.get("ok") != 1:
                        unread.append(m.rail)
                    elif x.get("bus_mv", 0) > L.LIVE_OFF_MV or abs(x.get("current_ua", 0)) > L.LIVE_OFF_UA:
                        live.append(m.rail)
                self.safe_detail.update(live=live, unread=unread)
                return not live and not unread
            except (CommandTimeout, LinkLost, ProtocolError):
                continue
        return False

    def _unsafe_advice(self):
        d = getattr(self, "safe_detail", {}) or {}
        why = []
        if d.get("live"):
            why.append(f"{', '.join(d['live'])} still read live with every enable off (a switch that ignores its "
                       "enable, or back-powering)")
        if d.get("unread"):
            why.append(f"the monitors of {', '.join(d['unread'])} did not answer, so those rails are unconfirmed")
        if d.get("enables_on"):
            why.append(f"slots {d['enables_on']} still report an enable on")
        return "REMOVE POWER NOW (unplug J1 or switch the supply off), then inspect the board. tb safe did not " \
            "confirm the board off" + (f": {'; '.join(why)}." if why else ".")

    def finish(self):
        self.run_.finished = now_utc()
        st = [s.status for s in self.run_.steps]
        if self.run_.stop and self.run_.stop["kind"] in ("danger", "link_lost", "interrupted", "harness_error"):
            self.run_.verdict = "STOPPED"
        elif self.run_.stop or any(x in ("fail", "error") for x in st):
            self.run_.verdict = "FAIL"
        elif any(x in ("skipped", "not_run") for x in st) or not self.slots_to_test():
            self.run_.verdict = "INCOMPLETE"
        else:
            self.run_.verdict = "PASS" if not any(x == "warn" for x in st) else "PASS (with warnings)"

    # --- steps: the motherboard ---------------------------------------------------------------------------------
    def st_link(self, st):
        st.commands.append("(sync: shell setup + tb info)")
        try:
            r = self.s.sync()
        except CommandTimeout as e:
            raise AbortRun("no answer to tb info: the wrong port or baud rate, the firmware not running, or another "
                           "program holding the port") from e
        info = r.first("info")
        self.run_.info = dict(info.fields)
        self.check_events()
        st.check("protocol version", info.get("proto") == 1, info.get("proto"), "1", ref="PROTOCOL.md")
        if info.get("proto") != 1:
            raise AbortRun(f"firmware speaks protocol {info.get('proto')}, this harness speaks 1")
        st.check("firmware", info.get("fw") == "bringup", info.get("fw"), "bringup")
        st.check("board", info.get("board") == "kbd_testbed_a", info.get("board"), "kbd_testbed_a", ref="SPEC §8.1")
        st.check("nets revision", info.get("nets_rev") == self.L.rev, info.get("nets_rev"), self.L.rev,
                 ref="nets.py REV", bad="warn")
        want = L.map_hash_from_nets(self.L.nets_path)       # what a build from the nets.py judged against carries
        header = L.map_hash()                               # what this checkout's generated header carries
        if want is not None and header is not None and header != want:
            st.add("generated board map current", "warn", header, want, ref="keyboard/firmware/boards/gen_board.py",
                   detail="tb_board_map.h is stale against nets.py (or --nets is another file): run gen_board.py "
                          "--check; firmware built from this checkout is built from the old map")
        if want is None and header is None:
            st.add("board map hash", "info", info.get("map"), detail="no nets.py or tb_board_map.h to compare with")
        else:
            st.check("board map hash", info.get("map") == (want or header), info.get("map"), want or header,
                     ref="gen_board.py Map.hash() of nets.py",
                     detail="the firmware was built from another nets.py than the one this run judges against"
                            + (" (it matches this checkout's stale header)" if info.get("map") == header != want
                               else ""),
                     bad="fail" if self.cfg.strict_map else "warn")
        if self.cfg.power == "bench":
            st.check("bench-supply build", info.get("bench_build") == 1, info.get("bench_build"), "1",
                     ref="PROTOCOL.md, tb budget bench", detail="build with -DCONFIG_BRINGUP_BENCH_SUPPLY=y")
            if info.get("bench_build") != 1:
                raise AbortRun("bench power needs a bench-supply build of the firmware")
        if isinstance(info.get("settle_ms"), int):
            st.add("firmware rail settling time", "info", info["settle_ms"], unit="ms",
                   detail="compare with the INA226 result period (monitors step)")

    def st_safe(self, st):
        r = self.cmd("tb safe", power=True)
        st.check("tb safe rc", r.ok, r.rc, "0", detail=r.err or "")
        for rec in r.all("restore"):
            what = f"exp {rec['exp']}" if "exp" in rec else "mux"
            st.check(f"restore {what} read back", rec.get("ok") == 1, rec.get("ok"), "1", ref="SPEC §3.5")
        if not r.all("restore"):
            st.add("restore records", "fail", 0, "4", ref="PROTOCOL.md, tb safe")

    def st_boot(self, st):
        r = self.cmd("tb boot")
        b = r.first("boot")
        if b is None:
            raise AbortRun("tb boot printed no boot record")
        for bus in ("i2c1_bus", "i2c4_bus"):
            v = b.get(bus)
            st.add(f"{bus} first answer", "pass" if v == 0 else "warn" if v == 1 else "fail", v, "0",
                   ref="PROTOCOL.md, Records", detail={1: "answered only after bus recovery"}.get(v, ""))
        st.add("reset cause", "info", b.get("reset"))
        exps = {rec.get("addr"): rec for rec in r.all("boot_exp")}
        for addr, (ref, _pins) in sorted(self.L.expanders.items()):
            rec = exps.get(addr)
            st.check(f"{ref} at 0x{addr:02x} answered", rec is not None and rec.get("err") == 0,
                     None if rec is None else rec.get("err"), "err=0", ref="SPEC §3.4")
            if rec is not None:
                st.check(f"{ref} restored", rec.get("ok") == 1, rec.get("ok"), "ok=1", ref="SPEC §3.5")
        mux = r.first("boot_mux")
        st.check(f"mux TCA9548A at 0x{self.L.mux_addr:02x}", mux is not None and mux.get("err") == 0 and
                 mux.get("post_err") == 0, None if mux is None else mux.get("err"), "err=0", ref="SPEC §4.5")
        if mux is not None:
            st.check("mux deselected after boot", mux.get("post") == 0, mux.get("post"), "0x00", ref="SPEC §8.4")
        inas = {rec.get("addr"): rec for rec in r.all("boot_ina")}
        for addr, m in sorted(self.L.monitors.items()):
            rec = inas.get(addr)
            ok = rec is not None and rec.get("err") == 0 and rec.get("mfr") == 0x5449 and rec.get("die") == 0x2260
            st.check(f"INA226 0x{addr:02x} ({m.rail}) identified", ok,
                     None if rec is None else f"err={rec.get('err')} mfr=0x{rec.get('mfr', 0):04x}",
                     "mfr 0x5449, die 0x2260", ref="SPEC §3.4; SBOS547C")
            if rec is not None:
                st.check(f"INA226 0x{addr:02x} CAL", rec.get("cal") == m.cal, rec.get("cal"), str(m.cal),
                         ref="SPEC §3.4 (CAL = 0.00512 / (LSB x R))")
        extra = sorted(set(inas) - set(self.L.monitors))
        if extra:
            st.add("monitors not in nets.py", "fail", [f"0x{a:02x}" for a in extra])
        br = r.first("boot_restore")
        st.check("boot restore", br is not None and br.get("ok") == 1, None if br is None else br.get("ok"), "ok=1",
                 ref="SPEC §8.4")

    def st_exp(self, st):
        r = self.cmd("tb exp")
        exps = {rec.get("addr"): rec for rec in r.all("exp")}
        nets = {rec.get("name"): rec for rec in r.all("net")}
        missing = []
        for addr, (ref, pins) in sorted(self.L.expanders.items()):
            rec = exps.get(addr)
            ok = rec is not None and rec.get("ok") == 1
            st.check(f"{ref} at 0x{addr:02x}", ok, None if rec is None else rec.get("ok"), "ok=1", ref="SPEC §3.4")
            if not ok:
                missing.append(ref)
                continue
            idx = rec.get("exp")
            for pin, net in pins.items():
                n = nets.get(net)
                if n is None or n.get("pin") != pin or n.get("exp") != idx:
                    st.add(f"{net} on {ref} {pin}", "fail", None if n is None else f"exp{n.get('exp')} {n.get('pin')}",
                           f"exp{idx} {pin}", ref="nets.py EXPANDERS",
                           detail="the firmware's pin map is not this checkout's nets.py")
        if "U_EXP1" in missing:
            raise AbortRun("U_EXP1 (every rail enable and bus switch) does not answer")
        safe = {"EN_": 0, "BUSEN_N_": 1, "LED_S": 1, "MUX_RST_N": 1, "KVM_RST_N": 0}
        for name, rec in nets.items():
            want = next((v for k, v in safe.items() if name.startswith(k) or name == k), None)
            if name.endswith(("_G4", "_G5")):
                want = 0
            if want is not None and rec.get("dir") == "out":
                st.check(f"{name} idle", rec.get("level") == want, rec.get("level"), str(want), ref="SPEC §3.5")
        for name in ("SLOT_FAULT_N", "PM_ALERT_N", "VSYS_PG"):
            rec = nets.get(name)
            if rec is not None:
                st.check(f"{name} idle", rec.get("level") == 1, rec.get("level"), "1", ref="SPEC §3.1, §3.4",
                         detail={"VSYS_PG": "the input breaker's power-good is low"}.get(name, "asserted at idle"))
        self.present = []
        for s in self.L.slots:
            rec = nets.get(f"S{s}_PRESENT_N")
            if rec is not None and rec.get("level") == 0:
                self.present.append(s)
        st.add("coupons present (PRESENT_N low)", "info", [f"S{s}" for s in self.present] or "none")
        for name in ("S5_PG", "USBC_INT_N", "KVM_PRESENT_N"):
            if name in nets:
                st.add(f"{name}", "info", nets[name].get("level"))

    def st_ina(self, st):
        self.settle()
        r = self.cmd("tb ina all")
        recs = {rec.get("addr"): rec for rec in r.all("ina")}
        for addr, m in sorted(self.L.monitors.items()):
            rec = recs.get(addr)
            if rec is None or rec.get("ok") != 1 or rec.get("rail") != m.rail:
                st.add(f"INA226 0x{addr:02x} ({m.rail}) reads", "fail",
                       None if rec is None else (rec.get("err") or rec.get("rail")), "ok=1", ref="SPEC §3.4")
                continue
            if isinstance(rec.get("config"), int):
                self.ina_period_s = L.ina_period_ms(rec["config"]) / 1000.0
            st.check(f"0x{addr:02x} CAL", rec.get("cal") == rec.get("cal_expect") == m.cal, rec.get("cal"), str(m.cal),
                     ref="SPEC §3.4")
            st.check(f"0x{addr:02x} current LSB", rec.get("lsb_ua") == m.lsb_ua, rec.get("lsb_ua"), str(m.lsb_ua),
                     unit="uA", ref="nets.py INA226_CURRENT_LSB_UA")
            ua, sua, mv = rec.get("current_ua", 0), rec.get("shunt_current_ua", 0), rec.get("bus_mv", 0)
            tol = 2 * m.lsb_ua + abs(sua) * 0.01 + 2.5 / m.shunt_ohm
            st.check(f"0x{addr:02x} current and shunt agree", abs(ua - sua) <= tol, ua - sua, f"+/-{tol:.0f}", "uA",
                     ref="PROTOCOL.md, Records (ina)")
            if ua >= m.full_scale_ma * L.DANGER_FULL_SCALE * 1000:
                st.add(f"{m.rail} current", "danger", ua / 1000, f"< {m.full_scale_ma * L.DANGER_FULL_SCALE:.0f}",
                       "mA", detail="at the monitor's full scale: a short")
            if m.switched:
                live = mv > L.LIVE_OFF_MV or abs(ua) > L.LIVE_OFF_UA
                st.check(f"{m.rail} off", not live, f"{mv} mV, {ua / 1000:.1f} mA",
                         f"<= {L.LIVE_OFF_MV} mV and <= {L.LIVE_OFF_UA / 1000:.0f} mA", ref="SPEC §3.5",
                         detail="an off rail reads live: something back-powers it", bad="danger")
                continue
            ma = ua / 1000.0
            lo, hi = L.IDLE_MA[m.rail]
            danger = L.IDLE_DANGER_MA.get(m.rail)
            if danger and ma >= danger:
                st.add(f"{m.rail} idle current", "danger", round(ma, 2), f"< {danger}", "mA",
                       ref="SPEC §3.2 (base load estimate 45 mA)", detail="nothing is switched on")
            if m.rail == "VSYS" and self.cfg.power == "usb":
                ref = "SPEC §3.2: USB 2.0 allows 100 mA before configuration"
            else:
                ref = "SPEC §3.2 estimates; harness proposal"
            st.check(f"{m.rail} idle current", lo <= ma <= hi, round(ma, 2), f"{lo}-{hi}", "mA", ref=ref)
            if m.rail == "VSYS":
                self.vsys_mv = mv
                st.check("VSYS voltage", L.VSYS_MV[0] <= mv <= L.VSYS_MV[1], mv, f"{L.VSYS_MV[0]}-{L.VSYS_MV[1]}",
                         "mV", ref="USB 2.0 VBUS at the port, USB-C 5.5 V max (SPEC §3.5); harness proposal")
                if self.cfg.power == "usb":
                    ll = self.L.vsys_load_line_mv(ma) - self.L.bus_tolerance_mv(mv)
                    st.check("VSYS on or above the USB-C load line", mv >= ll, mv, f">= {ll:.0f}", "mV",
                             ref="SPEC §3.6 (D4 of 2026-11-27): 4.75 V - 0.25 ohm x I at J1, less U2's 45 mOhm and "
                                 "the 20 mOhm shunt, less the INA226's bus error", bad="warn",
                             detail="the source or the cable is worse than a legal USB-C one: S5's motor margin and "
                                    "VSYS_PG's shrink (SPEC §3.1, §3.6); try another cable or source")
                if self.L.vsys_pg:
                    fall = self.L.vsys_pg["fall"][2] * 1000
                    st.add("VSYS above VSYS_PG's falling edge", "info", round(mv - fall), unit="mV",
                           ref="SPEC §3.1 (D4): VSYS_PG falls at 3.46-3.69 V with 1 % resistors "
                               "(nets.vsys_pg_thresholds; measured on VSYS_IN, before the shunt)")
            else:
                wlo, whi = self.L.always_on_window_mv(m.rail, ma)
                st.check(f"{m.rail} voltage", wlo <= mv <= whi, mv, f"{wlo:.0f}-{whi:.0f}", "mV",
                         ref="AP2112K +/-1.5 % (DS39724), INA226 bus error (SBOS547C), the shunt's drop")
        period = self.ina_period_s * 1000
        settle = self.run_.info.get("settle_ms")
        if isinstance(settle, int) and settle < period:
            st.add("firmware settle time against the INA226 result period", "warn", f"{settle} ms < {period:.1f} ms",
                   ref="SBOS547C 6.3.1; src/slot.c tb_rail_settle()",
                   detail="the firmware's after-enable check may read a result from before the rail came up; "
                          "a low_3v3 on slot on is retried and diagnosed by this harness")

    def st_typec(self, st):
        r = self.cmd("tb cc")
        cc = r.first("cc")
        source = None
        if cc is None or cc.get("present") != 1:
            st.add(f"U_CC at 0x{self.L.cc_addr:02x}", "fail", None if cc is None else cc.get("err"), "present=1",
                   ref="SPEC §3.8", detail="no TUSB320: the budget stays at the Default level (500 mA)")
        else:
            st.check("U_CC identity", cc.get("id_ok") == 1, cc.get("id"), "TUSB320", ref="SLLSEQ8D Table 7")
            st.check("U_CC decided", cc.get("decided") == 1, cc.get("decided"), "1", ref="SPEC §8.4 (200 ms)")
            source = cc.get("source")
            st.add("attached state", "pass" if cc.get("attached") == "attached_snk" else "warn", cc.get("attached"),
                   "attached_snk", ref="SPEC §3.8")
            st.add("advertisement read", "info", source)
            if self.cfg.source:
                want = {"typeA": "default"}.get(self.cfg.source, self.cfg.source)
                st.check("advertisement as the operator declared", source == want, source, want, ref="SPEC §3.8",
                         detail="a Type-A-to-C cable must read default; a 10 k Rp cable would read 3.0A (SPEC §3.8)")
        b = self.cmd("tb budget").first("budget")
        if b is None:
            st.add("budget record", "fail")
            return
        st.check("budget ceiling", b.get("max_ma") == self.L.vsys_max_ma, b.get("max_ma"), str(self.L.vsys_max_ma),
                 "mA", ref="SPEC §3.2, nets.VSYS_BUDGET_MAX")
        configured = b.get("usb") == "configured"
        want = self.L.budget_ma(b.get("source") or "default", configured)
        if b.get("bench_ma"):
            want = min(b["bench_ma"], self.L.vsys_max_ma)
        elif b.get("override_ma"):
            want = min(want, b["override_ma"])
        st.check("VSYS budget for the advertisement", b.get("limit_ma") == want, b.get("limit_ma"), str(want), "mA",
                 ref="SPEC §3.2, nets.vsys_budget")
        self.run_.info["budget_ma"] = b.get("limit_ma")
        self.run_.info["source"] = b.get("source")

    def st_usb(self, st):
        u = self.cmd("tb usb").first("usb")
        if self.cfg.power == "bench":
            st.check("no host on J1 in bench mode", u.get("state") == "unconfigured", u.get("state"), "unconfigured",
                     ref="PROTOCOL.md, tb budget bench")
            ma = self.cfg.bench_ma
            if not ma:
                raise AbortRun("bench power needs --bench-ma (the supply's current limit)")
            r = self.cmd(f"tb budget bench {ma}", power=True)
            b = r.first("budget")
            st.check("bench budget accepted", r.ok, r.rc, "0", detail=r.err or "")
            if b is not None:
                st.check("bench budget", b.get("limit_ma") == min(ma, self.L.vsys_max_ma), b.get("limit_ma"),
                         str(min(ma, self.L.vsys_max_ma)), "mA", ref="PROTOCOL.md (capped at 2800 mA)")
                st.check("slots may be powered", b.get("may_power") == 1, b.get("may_power"), "1")
            return
        if u.get("state") != "configured":
            if self.op.confirm("host", "Connect J1 to a USB host (high-speed port) and wait for it to enumerate"):
                for _ in range(10):
                    self.sleep(0.5)
                    u = self.cmd("tb usb").first("usb")
                    if u.get("state") == "configured":
                        break
        st.check("configured by a host", u.get("state") == "configured", u.get("state"), "configured",
                 ref="SPEC §3.2: no slot power before SET_CONFIGURATION")
        if u.get("state") != "configured":
            raise AbortRun("the device is not configured: no slot may be powered (SPEC §3.2)")
        if self.cfg.console == "sim":
            st.add("high speed", "info", u.get("speed"), "hs", detail="a simulated board has no USB PHY")
        else:
            st.check("high speed", u.get("speed") == "hs", u.get("speed"), "hs", ref="SPEC §7.1, §10 step 6")
        b = self.cmd("tb budget").first("budget")
        if b is not None:
            want = self.L.budget_ma(b.get("source") or "default", True)
            if b.get("override_ma"):
                want = min(want, b["override_ma"])
            st.check("configured budget", b.get("limit_ma") == want, b.get("limit_ma"), str(want), "mA",
                     ref="SPEC §3.2")
            self.run_.info["budget_ma"] = b.get("limit_ma")

    def st_nrst(self, st):
        if self.cfg.console == "cdc":
            st.add("console", "skip", "cdc", "uart", detail="NRST drops the CDC port: run this step on USART1")
            return
        slot = next(iter(self.present), None)
        if slot is None:
            st.add("a coupon to power", "skip", detail="needs a coupon in a slot (PRESENT_N low) to turn a rail on")
            return
        r = self.cmd(f"tb rail +3V3_S{slot} on 250", power=True)
        if not r.ok:
            st.add(f"+3V3_S{slot} on for the reset test", "fail", r.rc, detail=r.err or "")
            return
        self.run_.slots.setdefault(slot, {})
        self._judge_powered(st, slot, self._record_ma3(slot), "for the reset test")
        if not self.op.confirm("nrst", f"+3V3_S{slot} is on. Press the NRST button (reset) on the motherboard now"):
            self.cmd(f"tb rail +3V3_S{slot} off", power=True)
            st.add("NRST pressed", "skip", detail="the operator skipped it")
            return
        seen = self.s.drain(quiet_s=0.5, max_s=10.0)
        self.s.events.clear()
        self.s.take_events()
        for ev in [x for x in seen if x.name == "ev"]:
            self.s._note_event(ev)
        self.s.sync()
        self.check_events()
        if self.cfg.power == "bench" and self.cfg.bench_ma:
            self.cmd(f"tb budget bench {self.cfg.bench_ma}")
        r = self.cmd("tb boot")
        b = r.first("boot")
        st.check("reset cause", b is not None and "pin" in str(b.get("reset")), None if b is None else b.get("reset"),
                 "pin", ref="PROTOCOL.md, Records")
        e1 = next((x for x in r.all("boot_exp") if x.get("exp") == 1), None)
        if e1 is not None:
            st.check("U_EXP1 kept its outputs through the reset", e1.get("por") == 0, e1.get("por"), "por=0",
                     ref="SPEC §3.5 (TCA9535 has no reset pin)")
            st.check("U_EXP1 was driving", e1.get("driven", 0) != 0, f"0x{e1.get('driven', 0):04x}", "non-zero")
        for x in r.all("boot_exp"):
            st.check(f"U_EXP{x.get('exp')} restored", x.get("ok") == 1, x.get("ok"), "ok=1", ref="SPEC §8.4")
        br = r.first("boot_restore")
        st.check("boot restore", br is not None and br.get("ok") == 1, None if br is None else br.get("ok"), "ok=1")
        nets = {x.get("name"): x for x in self.cmd("tb exp").all("net")}
        on = [n for n, x in nets.items() if n.startswith("EN_") and x.get("level") == 1]
        st.check("every rail enable low after the reset", not on, on or "none", "none", ref="SPEC §3.5", bad="danger")

    def _present_now(self, st):
        """Read PRESENT_N again (tb exp) after the operator moved a coupon; refresh the slot list."""
        nets = {x.get("name"): x for x in self.cmd("tb exp").all("net")}
        self.present = [s for s in self.L.slots if (nets.get(f"S{s}_PRESENT_N") or {}).get("level") == 0]
        return nets

    def _turned_lines(self, n):
        pins = self.L.slot_mcu.get(n, {})
        return ", ".join(f"{s} ({pins[s]})" for s in ("CS0_N", "CS1_N", "G0", "G1") if s in pins)

    def st_turned(self, st):
        """risks.md EL-2's bring-up test: the test coupon plugged in turned 180 degrees (possible only before socket
        hole 39 is plugged), from a current-limited supply. Turned, PRESENT_N meets the coupon's GND (it reads
        present), +3V3_Sn meets its G0/G1 inputs and SCL its GND. The firmware must refuse the slot without
        driving CS0_N, CS1_N or G0-G5 (it reads the descriptor first, src/slot.c), and the bus must come back."""
        n = self.cfg.turned_test
        if self.cfg.power != "bench":
            st.add("bench supply", "skip", self.cfg.power, "bench",
                   detail="EL-2's test runs from a current-limited bench supply (--power bench)")
            return
        if n not in self.L.slots:
            st.add("slot", "fail", n, f"one of {self.L.slots}")
            return
        lines = self._turned_lines(n)
        if not self.op.confirm(
                f"turned_in_S{n}", f"Every slot is off (every LED dark). Plug the test coupon into S{n} TURNED 180 "
                f"degrees: possible only while S{n}'s hole 39 has no plug (risks.md EL-2's test). Put a scope on "
                f"{lines} at the MCU side, single trigger on any edge"):
            st.add("turned coupon plugged in", "skip", detail="the operator skipped it")
            return
        nets = self._present_now(st)
        st.add(f"S{n} PRESENT_N with the coupon turned", "info", (nets.get(f"S{n}_PRESENT_N") or {}).get("level"),
               "0 (its pin 9, GND, meets the socket's PRESENT_N)")
        r = self.cmd(f"tb slot {n} on", power=True)
        so = r.first("slot_on")
        if r.err in L.DANGER_ERR_TOKENS:
            st.add("slot on", "danger", r.err, detail="the switch faulted into the turned coupon")
        if r.ok:
            st.add("the firmware refuses the turned coupon", "danger", f"rc=0 desc={so and so.get('desc')}",
                   "refused", detail="the firmware took a turned coupon for a coupon and powered it")
        st.check("the firmware refuses the turned coupon", r.err in ("desc_bus", "bus_error"), r.err, "desc_bus",
                 ref="PROTOCOL.md, tb slot on; risks.md EL-2",
                 detail="refused for another reason than the EEPROM's silence")
        sl = self.cmd(f"tb slot {n}").first("slot")
        st.check(f"S{n} left off", sl is not None and not (sl.get("on3") or sl.get("on5") or sl.get("bus")),
                 None if sl is None else f"on3={sl.get('on3')} on5={sl.get('on5')} bus={sl.get('bus')}", "all 0",
                 bad="danger")
        rec = self.fresh_ina(f"+3V3_S{n}")
        if rec is not None and rec.get("ok") == 1:
            still = rec["bus_mv"] > L.LIVE_OFF_MV or abs(rec["current_ua"]) > L.LIVE_OFF_UA
            st.check(f"+3V3_S{n} dead", not still, f"{rec['bus_mv']} mV, {rec['current_ua']} uA",
                     f"<= {L.LIVE_OFF_MV} mV", bad="danger")
        self._recover_i2c4(st)
        seen = self.op.ask(f"turned_scope_S{n}", f"Did the scope see any of {lines} driven by the MCU (a high "
                           "level, or a low that is not the line's pull)?")
        if seen is None:
            st.add("no slot line driven into the turned coupon", "skip", detail="no scope answer")
        else:
            st.check("no slot line driven into the turned coupon", seen is False, "driven" if seen else "none",
                     "none", ref="risks.md EL-2; src/slot.c (the descriptor before the lines)",
                     detail="the firmware drives the slot's lines before it has read a descriptor")
        self.op.confirm(f"turned_out_S{n}", f"S{n} is off. Take the turned coupon out; plug it back the right way "
                        f"round (or leave S{n} empty)")
        self._present_now(st)

    def st_key(self, st, n):
        """SPEC §10 step 7 (D2 of 2026-11-27): turned 180 degrees, the test coupon's pin 2 meets the socket's
        plugged hole 39, so it does not go in. Done with the slot off."""
        sl = self.cmd(f"tb slot {n}").first("slot")
        if sl is None or sl.get("on3") or sl.get("on5"):
            st.add(f"S{n} off for the key check", "fail", None if sl is None else sl.get("on3"), "off")
            return
        stayed = self.op.ask(f"key_S{n}", f"S{n} is off (LED_S{n} dark). Take the test coupon out of S{n}, turn it "
                             f"180 degrees and try to push it in, without force. Did it stay out?")
        if stayed is None:
            st.add("a turned test coupon stays out", "skip", detail="no answer")
        else:
            st.check("a turned test coupon stays out", stayed, "stayed out" if stayed else "went in", "stays out",
                     ref="SPEC §4.2 (D2 of 2026-11-27): coupon pin 39 absent, socket hole 39 plugged",
                     detail="the key did not stop it: fit hole 39's plug (and check that the coupon's pin 39 was "
                            "pulled) before any coupon goes into this slot")
        self.op.confirm(f"key_back_S{n}", f"Pull it out if it went in, and plug the test coupon back into S{n} the "
                        "right way round (the SLOT EDGE / pin 1 silk over the socket's pin 1)")
        nets = self._present_now(st)
        rec = nets.get(f"S{n}_PRESENT_N")
        st.check(f"S{n} PRESENT_N low again", rec is not None and rec.get("level") == 0,
                 None if rec is None else rec.get("level"), "0")
        if n not in self.present:
            raise SkipSlot("no coupon in the slot after the key check")

    # --- steps: a slot --------------------------------------------------------------------------------------------
    def _slot_on_line(self, n, extra=""):
        nodesc = self.run_.slots.get(n, {}).get("nodesc_line")
        if nodesc:
            return nodesc
        probe = f" probe={self.cfg.probe_ma}" if self.cfg.probe_ma else ""
        return f"tb slot {n} on{probe}{extra}"

    def _nodesc_from_record(self, st, n, why):
        """Power a Hall coupon whose EEPROM the firmware cannot read (blank, or compiler v0's PCKC) on the currents
        its descriptor of record declares, through descriptor.py. Never after a bus error: a coupon whose EEPROM did
        not answer may be in turned 180 degrees, and nodesc drives the slot's lines once its rails pass."""
        rec = desc_check.record(self.coupon_of(n))
        self.run_.slots[n]["descriptor_record"] = rec.as_dict()
        st.check("descriptor of record valid (descriptor.py)", rec.valid, rec.path.split("keyboard/")[-1] or None,
                 "valid", ref="keyboard/tools/coupon/descriptor.py", detail="; ".join(rec.problems))
        if not rec.valid:
            raise SkipSlot("no valid descriptor of record to declare the coupon's currents from")
        i3, i5 = rec.facts.get("i3v3_ma") or 0, rec.facts.get("i5v_ma") or 0
        line = f"tb slot {n} on nodesc ma3={i3}" + (f" ma5={i5}" if i5 else "")
        st.add("powered on its descriptor of record", "warn", f"+3V3 {i3} mA, +5V {i5} mA",
               ref="keyboard/tools/coupon/descriptors via descriptor.py; PROTOCOL.md, tb slot <n> on nodesc",
               detail=f"the EEPROM gave {why}: the bring-up firmware reads only its own format (PCKD) and writes only "
                      "the test coupon's, so a Hall coupon cannot identify itself to it yet (README finding)")
        self.run_.slots[n]["nodesc_line"] = line
        return self.cmd(line, power=True)

    def st_slot_on(self, st, n):
        kind = self.coupon_of(n)
        r = self.cmd(self._slot_on_line(n), power=True)
        so = r.first("slot_on")
        if r.err == "blank" and self.cfg.write_descriptor is not None and kind == "test":
            st.add("descriptor EEPROM", "info", "blank", detail="writing the test coupon's descriptor")
            r2 = self.cmd(f"tb slot {n} on keep", power=True)
            if r2.ok:
                self._judge_powered(st, n, self._record_ma3(n), "with +3V3 alone, before the write")
            w = self.cmd(f"tb desc {n} write test serial={self.cfg.write_descriptor}", power=True)
            st.check("descriptor written and verified", w.ok, w.rc, "0", detail=w.err or "",
                     ref="PROTOCOL.md, tb desc write; test coupon ORDER-NOTES (JP1, WP, must be open to write)")
            self.cmd(f"tb slot {n} off", power=True)
            if not (r2.ok and w.ok):
                raise SkipSlot("the descriptor could not be written")
            r = self.cmd(self._slot_on_line(n), power=True)
            so = r.first("slot_on")
        if kind == "hall" and r.err in ("blank", *L.DESC_FORMAT_ERRORS):
            if r.err != "blank":
                self._dump_bad_descriptor(st, n, foreign_ok=True)
            r = self._nodesc_from_record(st, n, r.err)
            so = r.first("slot_on")
        err = r.err
        if err in L.DANGER_ERR_TOKENS:
            st.add("slot on", "danger", f"{err} (i3={so and so.get('i3_ua')} uA, i5={so and so.get('i5_ua')} uA)",
                   ref="PROTOCOL.md err tokens; SPEC §3.1", detail="the rail's switch limited or its current reached "
                   "the minimum trip right after enable: a short or an over-drawing coupon")
        if err == "not_present":
            if n in (self.cfg.coupons or {}):
                st.add("the declared coupon reads present", "fail", "PRESENT_N high", "low", ref="SPEC §4.2, §4.6",
                       detail=f"--coupon {n}={kind} says a coupon is in S{n}, but PRESENT_N reads high: not seated, "
                              "the wrong slot, or its PRESENT_N path open. It was not tested")
            else:
                st.add("coupon present", "skip", detail="PRESENT_N reads high")
            raise SkipSlot("no coupon in this slot")
        if err in L.LOW_ERR_TOKENS:
            diag = self._diagnose_low(st, n, err, so)
            if diag == "stale" and not self.cfg.retry_stale:
                st.add("slot powered", "fail", err, detail="the firmware refused a healthy rail (README finding 1); "
                       "without --no-retry-stale the harness retries with the monitors at 2.2 ms")
            if diag != "stale" or not self.cfg.retry_stale:
                raise SkipSlot(f"{err}: the slot is off")
            r = self._retry_fast(st, n)
            so, err = r.first("slot_on"), r.err
            if err in L.DANGER_ERR_TOKENS:
                st.add("slot on (retry)", "danger", err, detail="the switch faulted on the second enable")
            if not r.ok:
                raise SkipSlot(f"{err} on the retry: the slot is off")
        if err == "blank":
            st.add("descriptor", "fail", "blank", detail="an unwritten EEPROM: rerun with --write-descriptor SERIAL"
                   if kind == "test" else "an unwritten EEPROM")
            raise SkipSlot("blank descriptor")
        if err in L.DESC_FORMAT_ERRORS:
            st.add("descriptor accepted by the firmware", "fail", err, "ok", ref="tb/desc.h")
            self._dump_bad_descriptor(st, n)
            raise SkipSlot(f"descriptor {err}")
        if err in ("over_3v3_rule", "over_5v_rule", "slot_not_allowed", "wide_coupon"):
            st.add("descriptor within the coupon rules", "fail", err, ref="SPEC §4.9")
            raise SkipSlot(err)
        if err in ("unconfigured", "suspended", "over_vsys_budget", "over_slot_ldo", "order", "over_rule"):
            st.add("budget allowed the slot", "fail", err, ref="SPEC §3.2, §8.4",
                   detail={"over_slot_ldo": "another 3.3 V slot is on: try --probe-ma",
                           "over_vsys_budget": "a weak source: a 1.5 A or 3.0 A source, or a higher --bench-ma"}
                   .get(err, ""))
            raise SkipSlot(err)
        if err in ("monitor", "rail_3v3", "desc_bus"):
            st.add("slot on", "fail", err, detail={
                "monitor": "the rail's INA226 did not answer",
                "rail_3v3": "the rail enable did not answer (U_EXP1)",
                "desc_bus": "the descriptor EEPROM did not answer: the mux, the slot's I2C, or a coupon plugged in "
                            "turned 180 degrees (D2's key: hole 39's plug, the coupon's pin 39). The firmware "
                            "leaves the slot's lines high-impedance until a descriptor is read (PROTOCOL.md, tb slot "
                            "on)"}[err])
            if err == "desc_bus":
                self._recover_i2c4(st)
            raise SkipSlot(err)
        st.check("slot on rc", r.rc in (0, -11), r.rc, "0", detail=err or "")
        if so is None:
            raise SkipSlot("no slot_on record")
        st.check("no fault after enable", so.get("fault") == 0, so.get("fault"), "0", ref="SPEC §3.1")
        st.check("+3V3 on", so.get("on3") == 1, so.get("on3"), "1")
        st.check("bus switch closed after the rails", so.get("bus") == 1, so.get("bus"), "1", ref="SPEC §3.5")
        if self.run_.slots[n].get("nodesc_line"):
            st.add("descriptor", "info", so.get("desc"), detail="powered without one (nodesc), as declared above")
        else:
            st.check("descriptor", so.get("desc") == "ok", so.get("desc"), "ok", ref="SPEC §4.6")
        rail3, rail5 = self.L.rails_of(n)
        ma3, ma5 = so.get("ma3", 0), so.get("ma5", 0)
        rule3 = self.L.by_rail[rail3].rule_ma
        rule5 = self.L.by_rail[rail5].rule_ma
        st.check("declared +3V3 within the rule", ma3 <= rule3, ma3, f"<= {rule3:.0f}", "mA", ref="SPEC §4.9")
        st.check("declared +5V within the rule", ma5 <= rule5, ma5, f"<= {rule5:.0f}", "mA", ref="SPEC §4.9")
        if err:
            st.add("+5V", "fail", err, ref="PROTOCOL.md err tokens")
        if ma5 > 0:
            st.check("+5V on as the descriptor asks", so.get("on5") == 1, so.get("on5"), "1", ref="SPEC §3.5")
        self.run_.slots[n].update({"declared_3v3_ma": ma3, "declared_5v_ma": ma5})
        for rail, decl in ((rail3, ma3), (rail5, ma5 if so.get("on5") == 1 else 0)):
            if decl == 0 and rail == rail5:
                continue
            rec = self.fresh_ina(rail)
            if rec is None or rec.get("ok") != 1:
                st.add(f"{rail} reading", "fail", None if rec is None else rec.get("err"))
                continue
            ma, mv = rec["current_ua"] / 1000.0, rec["bus_mv"]
            dlim = self.L.danger_ma(rail, decl)
            st.check(f"{rail} current", ma < dlim, round(ma, 3), f"< {dlim:.1f}", "mA",
                     ref="the declaration (+10 % + 1 mA) and 80 % of the switch's minimum trip", bad="danger")
            if rail == rail3:
                lo, hi = self.L.slot_3v3_window_mv(ma)
                self.run_.slots[n]["idle_3v3_ua"] = rec["current_ua"]
                self.run_.slots[n]["idle_3v3_mv"] = mv
            else:
                v = self.fresh_ina("VSYS")      # VSYS now: the window is VSYS less the switch, +/- 2 bus errors
                if v is not None and v.get("ok") == 1:
                    self.vsys_mv = v["bus_mv"]
                lo, hi = self.L.slot_5v_window_mv(n, ma, self.vsys_mv)
            st.check(f"{rail} voltage", lo <= mv <= hi, mv, f"{lo:.0f}-{hi:.0f}", "mV",
                     ref="the firmware's floor (3.0 / 4.3 V) and harness proposal windows")

    def _diagnose_low(self, st, n, err, so):
        """low_3v3 / low_5v: tell a dead rail from a stale first reading. Returns "stale", "dead", "sag" or None.

        The firmware reads its monitor 20 ms after an enable (CONFIG_BRINGUP_SETTLE_MS), but under its default
        configuration (TB_MON_CONFIG_DEFAULT, 16 averages, a result every 35.2 ms) the INA226 replaces its registers
        only when an averaged result is complete (SBOS547C 6.3.1). At most 20 / 35.2 = 57 % of the averaged bus
        samples can postdate the enable, so a healthy 3.3 V rail reads 1.9 V or less there, whatever the phase:
        under the 3.0 V floor (README finding 1; arithmetic, not measured)."""
        rail = self.L.rails_of(n)[0 if err == "low_3v3" else 1]
        first = st.add("slot on", "fail", err, ref="src/slot.c MIN_3V3_MV / MIN_5V_MV",
                       detail=f"v3={so and so.get('v3_mv')} mV v5={so and so.get('v5_mv')} mV in the firmware's check")
        if err == "low_5v":
            return None
        r = self.cmd(f"tb rail {rail} on 250", power=True)
        if not r.ok:
            st.add("diagnosis: rail on again", "fail", r.err)
            return None
        rec = self.fresh_ina(rail)
        self.cmd(f"tb rail {rail} off", power=True)
        if rec is None or rec.get("ok") != 1:
            st.add("diagnosis", "fail", None if rec is None else rec.get("err"), detail="no fresh reading")
            return None
        mv, ua = rec["bus_mv"], rec["current_ua"]
        if ua / 1000.0 >= self.L.danger_ma(rail):
            st.add(f"diagnosis: {rail} current", "danger", ua / 1000.0, detail="a short behind the switch")
        if mv >= L.FW_MIN_3V3_MV:
            first.verdict = "warn"
            st.add("diagnosis", "warn", f"{mv} mV on a fresh reading",
                   ref="SBOS547C 6.3.1; src/slot.c, src/monitors.h (settle 20 ms, result every 35.2 ms)",
                   detail="the rail is fine: the firmware's settle check read a stale INA226 result (README finding "
                          "1, a firmware timing bug)")
            return "stale"
        if mv < 500:
            st.add("diagnosis", "fail", f"{mv} mV, {ua} uA",
                   detail="a dead rail: check JP_3V3_S%d (the meter jumper) is fitted, then the TPS2553 and its "
                          "enable" % n)
            return "dead"
        st.add("diagnosis", "fail", f"{mv} mV, {ua} uA", detail="a sagging rail: a heavy coupon or a weak switch")
        return "sag"

    def _retry_fast(self, st, n):
        """Work around finding 1: the slot's monitors at 2.2 ms results (tb ina cfg <rail> 1 1100 1100 7) for the
        firmware's settle check, then back to the bring-up default (16 averages, 35.2 ms)."""
        rails = self.L.rails_of(n)
        for rail in rails:
            self.cmd(f"tb ina cfg {rail} 1 1100 1100 7")
        # No finally: on a stop (or a lost link) nothing may come before tb safe, and a failed restore must never
        # replace the stop that is on its way out (the monitors' configuration does not matter once all is off)
        r = self.cmd(self._slot_on_line(n), power=True)
        for rail in rails:
            self.cmd(f"tb ina cfg {rail} 16 1100 1100 7")
        st.add("retried with the monitors at 2.2 ms", "pass" if r.ok else "fail", r.err or "ok",
               detail="tb ina cfg before tb slot on, restored after (README finding 1)")
        return r

    def _recover_i2c4(self, st):
        """After a descriptor read that got no answer: tb safe pulses MUX_RST_N, which frees I2C4 if a slot's SCL is
        held low through the selected channel (a coupon plugged in turned puts SCL on its GND; risks.md EL-2, FW-7).
        Every rail goes off with it; the harness tests one slot at a time, so none was meant to stay on."""
        r = self.cmd("tb safe", power=True)
        ok = r.ok and all(x.get("ok") == 1 for x in r.all("restore"))
        st.check("tb safe after the bus error (MUX_RST_N pulsed, I2C4 free)", ok, r.err or "ok", "restore ok",
                 ref="PROTOCOL.md, tb safe; risks.md FW-7",
                 detail="the mux or an expander did not read back: I2C4 may still be held low by the slot")

    def _dump_bad_descriptor(self, st, n, foreign_ok=False):
        """Power the slot without its descriptor (the EEPROM answered, so the coupon is the right way round) and
        check the bytes on the host. foreign_ok: a valid image in compiler v0's format (PCKC) is a warning, not a
        failure (a Hall coupon programmed with make_eeprom.py)."""
        ma3 = self._record_ma3(n)
        r = self.cmd(f"tb slot {n} on nodesc ma3={ma3}", power=True)
        if not r.ok:
            st.add("power for the descriptor dump", "fail", r.err)
            return
        self._judge_powered(st, n, ma3, "for the descriptor dump")
        d = self.cmd(f"tb desc {n}")
        img, problems = desc_check.reassemble(d.all("desc_hex"))
        rep = desc_check.check(img)
        self.run_.slots[n]["descriptor"] = rep.as_dict()
        foreign = foreign_ok and rep.format == "PCKC" and rep.kind in ("wrong_format", "partial")
        st.add("host check of the dumped image", "warn" if foreign else "fail" if not rep.valid else "info",
               f"{rep.format} {rep.kind}", detail="; ".join(problems + rep.problems))
        self.cmd(f"tb slot {n} off", power=True)

    def _record_ma3(self, n):
        """The +3V3 current the slot's declared coupon may draw: its descriptor of record's (descriptor.py), or the
        250 mA coupon rule when it has none."""
        rec = desc_check.record(self.coupon_of(n))
        return (rec.facts.get("i3v3_ma") or 250) if rec.valid else 250

    def _judge_powered(self, st, n, declared_ma, when):
        """+3V3_Sn from a fresh reading against a declaration, while the slot is powered outside tb slot <n> on's
        own checks (a descriptor write, a descriptor dump, the NRST test): over it is a dangerous stop."""
        rail = self.L.rails_of(n)[0]
        rec = self.fresh_ina(rail)
        if rec is None or rec.get("ok") != 1:
            st.add(f"{rail} reading {when}", "fail", None if rec is None else rec.get("err"))
            return None
        ma, dlim = rec["current_ua"] / 1000.0, self.L.danger_ma(rail, declared_ma)
        st.check(f"{rail} current {when}", ma < dlim, round(ma, 3), f"< {dlim:.1f}", "mA",
                 ref=f"declared {declared_ma} mA (+10 % + 1 mA) and 80 % of the switch's minimum trip", bad="danger")
        return rec

    def _judge_slot_rails(self, st, n, when):
        """The slot's enabled rails against the currents declared at slot on, from fresh readings, before a step
        that loads the slot: a coupon that starts to draw more than it declared after slot on stops the run here,
        whether or not the firmware's own INA226 alert caught it (that alert belongs to the firmware under test,
        and src/slot.c does not check that its write took)."""
        sl = self.cmd(f"tb slot {n}").first("slot")
        if sl is None:
            st.add(f"S{n} status {when}", "fail", detail="no slot record")
            return
        info = self.run_.slots.get(n, {})
        for rail, on_key, dkey in zip(self.L.rails_of(n), ("on3", "on5"), ("declared_3v3_ma", "declared_5v_ma")):
            if not sl.get(on_key):
                continue
            rec = self.fresh_ina(rail)
            if rec is None or rec.get("ok") != 1:
                st.add(f"{rail} reading {when}", "fail", None if rec is None else rec.get("err"))
                continue
            ma, dlim = rec["current_ua"] / 1000.0, self.L.danger_ma(rail, info.get(dkey))
            st.check(f"{rail} current {when}", ma < dlim, round(ma, 3), f"< {dlim:.1f}", "mA",
                     ref="the declaration at slot on (+10 % + 1 mA) and 80 % of the switch's minimum trip",
                     bad="danger")

    def _record_check(self, st, n):
        """The coupon's descriptor of record (compiler v0's JSON), validated by descriptor.py itself."""
        kind = self.coupon_of(n)
        rec = desc_check.record(kind)
        self.run_.slots[n]["descriptor_record"] = rec.as_dict()
        st.check("descriptor of record valid (descriptor.py)", rec.valid, rec.path.split("keyboard/")[-1] or kind,
                 "valid", ref="keyboard/tools/coupon/descriptor.py (encode, check_image, decode)",
                 detail="; ".join(rec.problems))
        return rec

    def st_desc(self, st, n):
        kind = self.coupon_of(n)
        record = self._record_check(st, n)
        r = self.cmd(f"tb desc {n}")
        img, problems = desc_check.reassemble(r.all("desc_hex"))
        for p in problems:
            st.add("desc_hex records", "fail", p)
        rep = desc_check.check(img)
        self.run_.slots[n]["descriptor"] = rep.as_dict()
        fw = r.first("desc")
        if self.run_.slots[n].get("nodesc_line"):
            st.add("the coupon's EEPROM", "warn", f"{rep.format} {rep.kind}".strip(), "PCKD",
                   ref="tb/desc.h; " + ", ".join(rep.tools),
                   detail="; ".join([*rep.problems, "the slot runs on its descriptor of record (slot on)"]))
            self.run_.slots[n].update({"coupon_type": f"{kind} (declared)", "coupon_serial": None})
            return
        st.check("host check", rep.valid, f"{rep.format} {rep.kind}".strip(), "valid PCKD",
                 ref="tb/desc.h; " + ", ".join(rep.tools), detail="; ".join(rep.problems))
        st.check("firmware parse", r.ok and fw is not None and fw.get("status") == "ok",
                 None if fw is None else fw.get("status"), "ok")
        if not rep.valid or fw is None or fw.get("status") != "ok":
            return
        h = rep.fields
        for k in ("type", "serial", "i3v3_ma", "i5v_ma", "rev"):
            st.check(f"{k}: host == firmware", h.get(k) == fw.get(k), f"host {h.get(k)}, fw {fw.get(k)}", "equal",
                     detail="the firmware's parser and the host's disagree")
        st.check("length: host == firmware", h.get("length") == fw.get("len"), h.get("length"), str(fw.get("len")))
        st.check("coupon type", h.get("type") == kind, h.get("type"), kind, ref="the operator's --coupon",
                 detail="the EEPROM names another coupon than the one declared in this slot" +
                        ("; an A2 coupon has no procedure in this release (SPEC §1, D1 of 2026-11-27)"
                         if h.get("type") in L.A2_COUPONS else ""))
        if record.valid:
            f = record.facts
            st.check("type as its descriptor of record", h.get("type") == f.get("type"), h.get("type"),
                     f.get("type"), ref=record.path.split("keyboard/")[-1])
            st.check("revision as its descriptor of record", h.get("rev") == f.get("rev"), h.get("rev"),
                     f.get("rev"), ref=record.path.split("keyboard/")[-1], bad="warn")
            for rail, key in (("+3V3", "i3v3_ma"), ("+5V", "i5v_ma")):
                st.check(f"declared {rail} as its descriptor of record", h.get(key) == (f.get(key) or 0),
                         f"EEPROM {h.get(key)}, record {f.get(key)}", "equal", "mA",
                         ref="tb/desc.h against keyboard/tools/coupon/descriptors (SPEC §11 #18)", bad="warn",
                         detail="the firmware's descriptor and compiler v0's declare different currents: the "
                                "firmware sets the rail's alert and budget from the EEPROM's (README finding 3)")
        for rail, key in (("+3V3", "i3v3_ma"), ("+5V", "i5v_ma")):
            rule = self.L.by_rail[f"{rail}_S{n}"].rule_ma
            st.check(f"declared {rail} within the rule", h.get(key, 0) <= rule, h.get(key), f"<= {rule:.0f}", "mA",
                     ref="SPEC §4.9")
        self.run_.slots[n].update({"coupon_type": h.get("type"), "coupon_serial": h.get("serial"),
                                   "coupon_rev": h.get("rev")})
        if kind == "test":
            for k, ratio in enumerate(L.TEST_LANE_RATIOS):
                ln = h["lanes"].get(k)
                ok = ln is not None and abs(ln["expect_ppm"] - ratio * 1e6) <= 100 and \
                    abs(ln["tol_ppm"] - L.TEST_LANE_TOL * 1e6) <= 100
                st.check(f"AN{k} expectation", ok, None if ln is None else f"{ln['expect_ppm']} +/- {ln['tol_ppm']}",
                         f"{ratio * 1e6:.0f} +/- {L.TEST_LANE_TOL * 1e6:.0f}", "ppm",
                         ref="sheets/test_coupon.py (the 5 x 499 ohm ladder)")

    def st_lanes(self, st, n):
        r = self.cmd(f"tb lanes {n}")
        v = r.first("vdda")
        if v is not None:
            st.check("VDDA from VREFINT", L.VDDA_MV[0] <= v.get("mv", 0) <= L.VDDA_MV[1], v.get("mv"),
                     f"{L.VDDA_MV[0]}-{L.VDDA_MV[1]}", "mV", ref="src/cmds.c")
        lanes = {x.get("lane"): x for x in r.all("lane")}
        readings = {}
        for k, ratio in enumerate(L.TEST_LANE_RATIOS):
            x = lanes.get(k)
            if x is None or "ratio_ppm" not in x:
                st.add(f"AN{k} read", "fail", None if x is None else x.get("err"))
                continue
            ppm, bits = x["ratio_ppm"], x.get("bits", 14)
            readings[k] = ppm
            if self.coupon_of(n) != "test":
                st.add(f"AN{k}", "info", ppm, unit="ppm", detail="no expectation without its coupon's procedure "
                       "(SPEC §10 step 8: the Hall coupon's own procedure is not written)")
                continue
            tol = L.TEST_LANE_TOL * 1e6 + 2 * 1e6 / (1 << bits)
            mine = abs(ppm - ratio * 1e6) <= tol
            st.check(f"AN{k} divider", mine, ppm, f"{ratio * 1e6:.0f} +/- {tol:.0f}", "ppm",
                     ref="the test coupon's ladder k/5 (sheets/test_coupon.py), 1 % (PROTOCOL.md)")
            if "ok" in x:
                st.check(f"AN{k}: firmware verdict == harness verdict", bool(x["ok"]) == mine, x["ok"], int(mine),
                         detail="the firmware judged this lane differently from the raw numbers")
            else:
                st.add(f"AN{k} firmware verdict", "warn", "none", detail="no descriptor expectation on the lane")
        for x in r.all("lane_alt"):
            if x.get("powered") != 1 or "diff_ppm" not in x:
                continue
            k, d = x.get("lane"), x.get("diff_ppm")
            mine = abs(d) <= L.AGREE_PPM
            st.check(f"AN{k} on ADC{x.get('adc')} agrees", mine, d, f"+/-{L.AGREE_PPM}", "ppm", ref="PROTOCOL.md")
            if bool(x.get("agree")) != mine:
                st.add(f"AN{k} ADC{x.get('adc')} firmware verdict", "fail", x.get("agree"), int(mine))
        self.run_.slots[n]["lanes_ppm"] = readings
        if v is not None and isinstance(v.get("mv"), int):
            self.run_.slots[n]["vdda_mv"] = v["mv"]

    def _lane_read(self, n):
        """tb lanes <n> -> ({lane: ratio_ppm}, VDDA mV, {lane: bits}); a lane that failed to read is left out."""
        r = self.cmd(f"tb lanes {n}")
        v = r.first("vdda")
        ppm, bits = {}, {}
        for x in r.all("lane"):
            if isinstance(x.get("ratio_ppm"), int):
                ppm[x.get("lane")] = x["ratio_ppm"]
                bits[x.get("lane")] = x.get("bits", 14)
        return ppm, (v.get("mv") if v is not None else None), bits

    def st_inj(self, st, n):
        """D7 of 2026-11-27: INJ into the AN0 ladder tap through D11 + R40 (sheets/test_coupon.py). INJ high lifts AN0
        by 0.43-0.58 V and AN1-AN3 by 3/4, 1/2, 1/4 of that; INJ low leaves every ratio alone. The motherboard
        reaches INJ only from J_RIG through JP_INJn (open by default), so on the bench the operator drives it, from
        the coupon's own +3V3 (TP1) by preference: that source cannot outlive the slot rail."""
        base = self.run_.slots[n].get("lanes_ppm") or {}
        vdda = self.run_.slots[n].get("vdda_mv")
        if len(base) != 4 or not vdda:
            st.add("baseline lanes", "skip", detail="the lanes step gave no reading of all four lanes and VDDA")
            return
        if not self.op.confirm(
                f"inj_S{n}", f"S{n} is powered (LED_S{n} lit). Drive the test coupon's INJ high: a clip lead from TP1 "
                f"(+3V3) to TP15 (INJ) on the coupon (or close JP_INJ{n} and drive J_RIG pin 9 at 3.3 V from a source "
                f"that is off whenever S{n} is off). Only while S{n} is powered: with the slot off INJ back-feeds the "
                f"coupon's +3V3"):
            st.add("INJ driven", "skip", detail="the operator skipped it")
            return
        self.run_.slots[n]["inj_driven"] = True
        hi, vdda_hi, bits = self._lane_read(n)
        if len(hi) != 4:
            st.add("lanes with INJ high", "fail", sorted(hi), "AN0-AN3")
        else:
            vd = vdda_hi or vdda
            lsb = vd / (1 << bits.get(0, 14))
            lift = {k: (hi[k] - base[k]) * vd / 1e6 for k in range(4)}
            lo_v, hi_v = self.L.inj_lift_v
            pct, n_lsb = L.INJ_LIFT_MARGIN
            lo, top = lo_v * 1000 * (1 - pct) - n_lsb * lsb, hi_v * 1000 * (1 + pct) + n_lsb * lsb
            self.run_.slots[n]["inj_lift_mv"] = round(lift[0], 1)
            st.check("AN0 lift with INJ high", lo <= lift[0] <= top, round(lift[0], 1), f"{lo:.0f}-{top:.0f}", "mV",
                     ref="sheets/test_coupon.py DESCRIPTOR_FACTS inj_lane (0.43-0.58 V, estimate); 2 % and 4 LSB "
                         "for two readings (harness proposal)",
                     detail="no lift: D11 or R40 missing or D11 reversed, or INJ not reached; too much: D11 shorted")
            if lift[0] > 10 * lsb:
                for k in (1, 2, 3):
                    share = lift[k] / lift[0]
                    want = self.L.inj_shares[k]
                    tol = L.INJ_SHARE_TOL + 2 * n_lsb * lsb / lift[0]
                    st.check(f"AN{k} follows AN0's lift", abs(share - want) <= tol, round(share, 4),
                             f"{want} +/- {tol:.3f}", ref="the ladder above AN0 (sheets/test_coupon.py)",
                             detail="the ladder above AN0 is not the 4 x 499 ohm the sheet draws, or a lane is "
                                    "swapped")
        self.op.confirm(f"inj_off_S{n}", f"Take the INJ lead off (or open JP_INJ{n}'s source); S{n} stays powered")
        low, _vd, bits = self._lane_read(n)
        x = low.get(0)
        tol = L.INJ_RETURN_LSB * 1e6 / (1 << bits.get(0, 14))
        back = x is not None and abs(x - base[0]) <= tol
        st.check("AN0 back to its reading before INJ", back, x, f"{base[0]} +/- {tol:.0f}", "ppm",
                 ref="sheets/test_coupon.py: INJ low leaves the ladder alone (D11 reverse-biased, under 10 uV)",
                 detail="INJ is still high (the lead is still on, or INJ is held high): the self-test is not run")
        if not back:
            self.run_.slots[n]["inj_left_high"] = True

    def st_selftest(self, st, n):
        if self.coupon_of(n) != "test":
            st.add("self-test", "skip", detail="only the test coupon has one")
            return
        if self.run_.slots[n].get("inj_left_high"):
            st.add("INJ low before the self-test", "fail", "high", "low",
                   detail="its loopback and lanes would fail with INJ high: take the INJ lead off and run again")
            return
        self._judge_slot_rails(st, n, "before the self-test")
        if self.cfg.loads and self.cfg.climit:
            opts = ["all"]
        else:
            opts = (["loads"] if self.cfg.loads else []) + (["climit"] if self.cfg.climit else [])
        r = self.cmd(f"tb selftest {n} {' '.join(opts)}".rstrip(), timeout=30.0, power=True)
        steps = {x.get("name"): x for x in r.all("step")}
        loads = {x.get("load"): x for x in self.cmd(f"tb desc {n}").all("desc_load")} if \
            ("load3" in steps or "load5" in steps) else {}
        rail3, rail5 = self.L.rails_of(n)
        for name, x in steps.items():
            res = x.get("result")
            if res == "skip":
                st.add(f"{name}", "skip", x.get("reason"), detail="not asked for" if not x.get("reason") else "")
                continue
            mine, detail, danger = None, "", False
            if name == "power":
                mine = res == "pass"
                detail = str(x.get("err") or "")
            elif name == "idle":
                mine = x.get("i_ua", 1e9) < L.TEST_IDLE_UA_MAX and x.get("bus_mv", 0) >= L.TEST_IDLE_MV_MIN
                detail = f"{x.get('i_ua')} uA at {x.get('bus_mv')} mV"
            elif name == "lanes":
                tol = L.TEST_LANE_TOL * 1e6 + 2 * 1e6 / (1 << 12)
                vals = [x.get(f"an{k}_ppm") for k in range(4)]
                mine = all(isinstance(v, int) and abs(v - ratio * 1e6) <= tol
                           for v, ratio in zip(vals, L.TEST_LANE_RATIOS)) and "disagree" not in x
                detail = f"{vals}"
            elif name == "loopback":
                want = 7 if n == 5 else 8
                mine = x.get("failed") == 0 and x.get("patterns") == want
                bad = {k: v for k, v in x.fields.items() if k.startswith("p") and k[1:2].isdigit()}
                detail = f"{x.get('patterns')} patterns, {x.get('failed')} failed" + (f": {bad}" if bad else "")
            elif name in ("load3", "load5"):
                ld = loads.get(0 if name == "load3" else 2)
                r_mohm = ld.get("r_mohm") if ld else 30000
                i0, i1, v1 = x.get("i0_ua"), x.get("i1_ua"), x.get("v1_mv")
                if None in (i0, i1, v1):
                    mine, detail = False, str(x.get("err") or "no readings")
                else:
                    expect = v1 * 1e6 / r_mohm
                    mine = abs((i1 - i0) - expect) <= expect * L.LOAD_TOL
                    detail = f"step {(i1 - i0) / 1000:.2f} mA, V/R {expect / 1000:.2f} mA"
                    if isinstance(x.get("expect_ua"), int):
                        st.check(f"{name} expect_ua arithmetic", abs(x["expect_ua"] - expect) <= expect * 0.01 + 2,
                                 x["expect_ua"], f"{expect:.0f}", "uA")
                if name == "load3" and isinstance(x.get("rs_mohm"), int):
                    rs = x["rs_mohm"]
                    self.run_.slots[n]["series_mohm"] = rs
                    lo, hi = L.RS_MOHM_PLAUSIBLE
                    st.check("slot series resistance (calibration)", lo <= rs <= hi, rs, f"{lo}-{hi}", "mOhm",
                             ref="SPEC §3.1 (0.24 ohm + the switch + the jumper)", bad="warn")
            elif name in ("climit3", "climit5"):
                rail = rail3 if name == "climit3" else rail5
                tmin, _ttyp, tmax = self.L.trips_ma[rail]
                i = x.get("i_ua")
                if i is None:
                    mine, detail = False, str(x.get("err") or "no reading")
                    if x.get("err") in ("over_vsys_budget", "over_slot_ldo"):
                        detail += ": the budget refused the test (a 1.5 A / 3.0 A source, or more --bench-ma)"
                else:
                    lo, hi = tmin * 1000 * (1 - L.CLIMIT_TOL), tmax * 1000 * (1 + L.CLIMIT_TOL)
                    mine = lo <= i <= hi and x.get("fault") == 1 and x.get("cleared") == 1
                    danger = i > hi or x.get("cleared") == 0
                    detail = (f"{i / 1000:.1f} mA in {lo / 1000:.0f}-{hi / 1000:.0f} mA, fault={x.get('fault')} "
                              f"cleared={x.get('cleared')}")
                    self.run_.slots[n][f"{name}_ma"] = round(i / 1000, 1)
                    if danger:
                        st.add(f"{name}: the switch limits", "danger", round(i / 1000, 1), f"<= {hi / 1000:.0f}", "mA",
                               ref="SPEC §3.1 trip window; nets.SWITCH_TRIP",
                               detail="the switch did not limit inside its window, or SLOT_FAULT_N did not clear")
            if mine is None:
                st.add(name, "pass" if res == "pass" else "fail", res, detail=detail)
                continue
            st.check(f"{name}", mine, res, "pass", ref="PROTOCOL.md, Self-test steps", detail=detail)
            if mine != (res == "pass"):
                st.add(f"{name}: firmware verdict == harness verdict", "fail", res, "pass" if mine else "fail",
                       detail="the firmware's verdict disagrees with the raw numbers")
        summ = r.first("selftest")
        st.check("self-test result", summ is not None and summ.get("result") == "pass",
                 None if summ is None else summ.get("result"), "pass")
        if "power" not in steps:
            st.add("self-test steps", "fail", 0, detail="no step records")

    def st_meter(self, st, n):
        rail3 = self.L.rails_of(n)[0]
        mon = self.L.by_rail[rail3]
        rec = self.fresh_ina(rail3)
        if rec is None or rec.get("ok") != 1:
            st.add("reading", "fail")
            return
        m_ma = self.op.measure(
            f"meter_i_S{n}", f"Meter on its mA range ACROSS JP_3V3_S{n}'s two pins first, then pull the jumper so the "
            f"current runs through the meter (never open the rail while S{n} is powered); the current. Refit the "
            f"jumper before you take the meter off", "mA")
        if m_ma is None:
            st.add("meter current", "skip", detail="no reading entered")
        else:
            ina_ua = rec["current_ua"]
            tol = self.L.current_tolerance_ua(mon, ina_ua) + abs(m_ma * 1000) * self.cfg.meter_tol_pct / 100
            st.check(f"{rail3}: INA226 against the meter", abs(ina_ua - m_ma * 1000) <= tol,
                     f"INA {ina_ua / 1000:.3f} mA, meter {m_ma:.3f} mA", f"+/-{tol / 1000:.3f}", "mA",
                     ref="SBOS547C offset and gain; the shunt's tolerance (1 %, assumed); the meter's",
                     detail="below about 100 uA the meter's figure is the one to use (SPEC §3.3)")
        m_v = self.op.measure(f"meter_v_S{n}", f"Meter on {rail3} at the coupon (TP or the header), volts", "V")
        if m_v is None:
            st.add("meter voltage", "skip", detail="no reading entered")
        else:
            mv = rec["bus_mv"]
            tol = self.L.bus_tolerance_mv(mv) + abs(m_v * 1000) * self.cfg.meter_tol_pct / 100 + \
                abs(rec["current_ua"]) / 1000 * 0.05
            st.check(f"{rail3}: bus voltage against the meter", abs(mv - m_v * 1000) <= tol,
                     f"INA {mv} mV, meter {m_v * 1000:.0f} mV", f"+/-{tol:.1f}", "mV", ref="SBOS547C")

    def st_trips(self, st, n):
        self.settle()                       # the snapshot after two fresh results: none from the self-test's loads
        r = self.cmd("tb trips")
        t = r.first("trips")
        if t is None:
            st.add("trips record", "fail", detail=r.err or "")
            return
        # tb trips' own reading of every monitored rail, judged here too (not only the firmware's findings)
        info = self.run_.slots.get(n, {})
        decl = dict(zip(self.L.rails_of(n), (info.get("declared_3v3_ma"), info.get("declared_5v_ma"))))
        for x in r.all("trip_rail"):
            rail, ua, mv = x.get("rail"), x.get("current_ua", 0), x.get("bus_mv", 0)
            if x.get("on") == 1:
                if rail not in decl:
                    st.add(f"{rail} on", "fail", 1, "0", detail=f"a rail outside S{n} is on during S{n}'s test")
                dlim = self.L.danger_ma(rail, decl.get(rail))
                if dlim is not None:
                    st.check(f"{rail} current (tb trips)", ua / 1000.0 < dlim, round(ua / 1000.0, 3),
                             f"< {dlim:.1f}", "mA", ref="the declaration at slot on (+10 % + 1 mA) and 80 % of the "
                             "switch's minimum trip", bad="danger")
            elif mv > L.LIVE_OFF_MV or abs(ua) > L.LIVE_OFF_UA:
                st.add(f"{rail} off (tb trips)", "danger", f"{mv} mV, {ua} uA",
                       f"<= {L.LIVE_OFF_MV} mV, <= {L.LIVE_OFF_UA} uA", ref="SPEC §3.5 (back-powering)")
        st.check("SLOT_FAULT_N clear", t.get("fault") == 0, t.get("fault"), "0", ref="SPEC §3.1")
        st.check("VSYS power-good", t.get("vsys_pg") == 1, t.get("vsys_pg"), "1", bad="danger")
        for f in r.all("trip"):
            fnd = f.get("finding")
            st.add(f"finding {fnd} {f.get('rail')}", "danger" if fnd in L.DANGER_FINDINGS else "fail", f.get("value"),
                   "no finding", ref="PROTOCOL.md, Findings")
        st.check("findings", t.get("findings") == 0, t.get("findings"), "0")

    def st_slot_off(self, st, n):
        if self.run_.slots.get(n, {}).get("inj_left_high"):
            self.op.confirm(f"inj_off_S{n}", f"INJ still reads high on S{n}: take the INJ lead off (or switch its "
                            f"source off) now, before S{n} goes off; with the slot off INJ back-feeds the coupon")
        r = self.cmd(f"tb slot {n} off", power=True)
        sl = r.first("slot")
        st.check("slot off", sl is not None and sl.get("on3") == 0 and sl.get("on5") == 0 and sl.get("bus") == 0,
                 None if sl is None else f"on3={sl.get('on3')} on5={sl.get('on5')} bus={sl.get('bus')}", "all 0",
                 ref="SPEC §3.5")
        for rail in self.L.rails_of(n):
            rec = self.fresh_ina(rail)
            if rec is None or rec.get("ok") != 1:
                st.add(f"{rail} reading", "fail")
                continue
            live = rec["bus_mv"] > L.LIVE_OFF_MV or abs(rec["current_ua"]) > L.LIVE_OFF_UA
            st.check(f"{rail} is off", not live, f"{rec['bus_mv']} mV, {rec['current_ua']} uA",
                     f"<= {L.LIVE_OFF_MV} mV, <= {L.LIVE_OFF_UA} uA", ref="SPEC §3.5 (back-powering)", bad="danger")
            if rail.startswith("+3V3") and self.run_.slots.get(n, {}).get("inj_driven"):
                st.check(f"{rail} not fed through INJ", rec["bus_mv"] <= L.INJ_BACKFEED_MV, rec["bus_mv"],
                         f"<= {L.INJ_BACKFEED_MV}", "mV", ref="sheets/test_coupon.py (0.85-0.88 V, estimate)",
                         detail="INJ is still driven with the slot off: it back-feeds the coupon's +3V3 through D11, "
                                "R40 and the ladder; take the lead off, switch the INJ source off")

    def st_final(self, st):
        self.replay()
        gaps = self.s.missing_seqs()
        st.check("every event seen", not gaps, gaps or "none", "none", ref="PROTOCOL.md, Events", bad="warn",
                 detail="the ring no longer holds them: the run may have missed a finding")
        r = self.cmd("tb safe", power=True)
        st.check("tb safe", r.ok, r.rc, "0", detail=r.err or "")
        sl = self.cmd("tb slot")
        on = [x.get("slot") for x in sl.all("slot") if x.get("on3") or x.get("on5")]
        st.check("every slot off", not on, on or "none", "none", ref="SPEC §3.5", bad="danger")
