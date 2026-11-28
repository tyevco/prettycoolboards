"""A simulated testbed behind the bring-up shell protocol, with faults to inject: the harness's test double.

It speaks PROTOCOL.md version 1 the way the firmware does (record names, key order, rc and err tokens, events and
their ring), so the harness can be run end to end here: healthy, and with a dead rail, a missing monitor, a slot
that trips, a bad descriptor, a wrong divider and the other faults in `Faults`. tests/test_simdev.py holds it to
PROTOCOL.md's record templates, and tests/test_native_sim.py runs the same procedure against the firmware itself
on native_sim, so a drift between this model and the firmware shows up as a test failure there.

What it is not: a model of the hardware. Its physics are Ohm's law and the switches' trip windows from nets.py,
like the firmware's own native_sim world (keyboard/firmware/bringup/sim/world.c), and its numbers are placeholders.
"""

from __future__ import annotations

import struct
from collections import deque
from dataclasses import dataclass, field

from . import desc_check
from . import limits as L

# What a firmware built from this checkout's nets.py reports (gen_board.py's Map.hash(); overridable with the
# map_hash fault). Computed, not copied: a copied hash goes stale with every nets.py edit.
TB_MAP_HASH = L.map_hash_from_nets() or "0000000000000000"
TEST_SERIAL = 1
IDLE_TEST_UA = 1386                   # the native_sim model's test coupon idle draw on +3V3
HALL_UA = 30000                       # the native_sim model's Hall coupon (sim/world.c: 30 mA on +3V3)
TURNED_UA = 70                        # a turned coupon: +3V3_Sn into its G0/G1 inputs' 100 k pull-downs (estimate)
INJ_VF_V = 0.66                       # D11 at about 1.4 mA, between the 1N4148W's typical and maximum (estimate)
INJ_BACKFEED_MV = 870                 # sheets/test_coupon.py: INJ high with the slot off, 0.85-0.88 V (estimate)
KV_MAX = 159                          # src/coupon_test.c: struct step kv[160], kv() stops at sizeof - 1
BASE_MA = 45
ADC_BITS = {1: 14, 2: 14, 4: 12}


@dataclass
class Faults:
    dead_rails: set = field(default_factory=set)          # the switch never conducts: 0 V, 0 A
    missing_monitors: set = field(default_factory=set)    # INA226 addresses that never answer
    missing_expanders: set = field(default_factory=set)   # TCA9535 addresses that never answer
    missing_mux: bool = False
    cc_absent: bool = False                               # nothing at 0x67
    short_ma: dict = field(default_factory=dict)          # rail -> extra mA from the moment it turns on
    late_load_ma: dict = field(default_factory=dict)      # rail -> (commands after enable, extra mA)
    bad_descriptor: dict = field(default_factory=dict)    # slot -> crc|blank|magic|pckc|version|over_rule|serial
    lane_ratio: dict = field(default_factory=dict)        # (slot, lane) -> ratio of +3V3 (a wrong divider)
    stuck_loopback: dict = field(default_factory=dict)    # slot -> MISO bits stuck high (mask over 16 bits)
    climit_ma: dict = field(default_factory=dict)         # rail -> where its switch really limits
    vsys_idle_ma: float = BASE_MA
    mcu_ma: float = 40.0
    usb_ma: float = 6.0
    fault_n_stuck: bool = False                           # SLOT_FAULT_N held low
    stale_ina: set = field(default_factory=set)           # rails whose first reading after an enable is stale
    drop_events: bool = False                             # live event lines lost (the ring keeps them)
    noisy: bool = False                                   # prompts, VT100 escapes and log lines around records
    hang: set = field(default_factory=set)                # tb commands that never print their done line
    lane_ok_bug: bool = False                             # firmware says ok=1 whatever a lane reads
    proto: int = 1
    map_hash: str | None = None
    live_off_mv: dict = field(default_factory=dict)       # rail -> mV it reads while off (back-powering)
    live_off_ua: dict = field(default_factory=dict)       # rail -> uA it reads while off (negative: backwards)
    nrst_restore_fail: bool = False
    rs_mohm: int = L.TEST_COUPON_SERIES_MOHM
    wrong_cal: dict = field(default_factory=dict)         # INA226 address -> the CAL it really holds
    budget_ma: int | None = None                          # the firmware's configured VSYS budget, whatever U_CC says
    quiet_service: bool = False                           # the board service never runs: no trip events, no rail off
    stuck_on: set = field(default_factory=set)            # rails whose switch ignores EN once on (stays live after off)
    adc_disagree: dict = field(default_factory=dict)      # (slot, lane, adc) -> ppm that converter reads off by
    short_loopback: dict = field(default_factory=dict)    # slot -> loopback patterns the self-test runs (and passes)
    desc_parse_bug: dict = field(default_factory=dict)    # (slot, key) -> what the firmware's desc record says
    rx_ring: int = 0                                      # bytes the shell holds between reads; the rest are dropped
    inj_open: set = field(default_factory=set)            # slots whose INJ path is open (D11 or R40 missing): no lift
    inj_lift: dict = field(default_factory=dict)          # slot -> the lift in V that INJ high really gives
    inj_stuck: set = field(default_factory=set)           # slots whose INJ stays high whatever the operator does
    inj_tap: dict = field(default_factory=dict)           # slot -> the ladder tap (0-3) R40 really lands on
    inj_rig: dict = field(default_factory=dict)           # slot -> INJ from the rig at this voltage: it stays high
                                                          # with the slot off and back-feeds the coupon's +3V3
    no_key_plug: set = field(default_factory=set)         # slots whose socket hole 39 is not plugged
    lines_before_desc: bool = False                       # the old firmware: lines driven before the descriptor
    vsys_drop_mv: int = 0                                 # a source or cable worse than the USB-C load line


class Coupon:
    def __init__(self, kind, slot, serial=TEST_SERIAL):
        self.kind = kind                 # test | blank | hall | turned (the test coupon turned 180 degrees)
        self.eeprom = bytes([0xFF]) * 256
        if kind in ("test", "turned"):
            self.eeprom = pckd_test_coupon(serial).ljust(256, b"\xff")
        elif kind == "hall":
            # as the firmware's native_sim world writes it (sim/world.c sim_set_coupon: type hall, flags sensors,
            # serial 100 + slot, +3V3 40 mA, no lane records)
            self.eeprom = pckd_encode(type_=2, i3v3_ma=40, i5v_ma=0, flags=2, serial=100 + slot).ljust(256, b"\xff")


# --- the PCKD image (keyboard/firmware/lib/include/tb/desc.h), as lib/tools/coupon_desc.py encodes it -------------
def _q16(x):
    return min(0xFFFF, max(0, round(x * 65536)))


def pckd_encode(type_, i3v3_ma, i5v_ma, name="", lanes=None, glines=None, i2c=(), spi=(), loads=None, serial=0,
                rev="A", flags=0, c3v3_uf=0, c5v_uf=0, slots=None):
    recs = bytearray()

    def rec(kind, payload):
        recs.extend(bytes([kind, len(payload)]) + payload)

    if name:
        rec(1, name.encode("ascii"))
    for k, (flags_l, r_src, expect, tol) in sorted((lanes or {}).items()):
        rec(2, struct.pack("<BBHHHH", k, flags_l, r_src, 0, _q16(expect), _q16(tol)))
    for k, (role, arg) in sorted((glines or {}).items()):
        rec(3, bytes([k, role, arg]))
    for addr, kind in i2c:
        rec(4, bytes([addr, kind]))
    for cs, mode, hz in spi:
        rec(5, struct.pack("<BBI", cs, mode, hz))
    if slots is not None:
        rec(6, bytes([slots]))
    for k, (g, rail, kind, r_mohm, sl) in sorted((loads or {}).items()):
        rec(7, struct.pack("<BBBBHB", k, g, rail, kind, r_mohm, sl))
    length = desc_check.PCKD_HEADER + len(recs) + 2
    head = b"PCKD" + struct.pack("<BBHBBHIHHHH", 1, 0, length, type_, ord(rev), flags, serial, i3v3_ma, i5v_ma,
                                 c3v3_uf, c5v_uf)
    body = head + bytes(recs)
    return body + struct.pack("<H", desc_check.crc16_ccitt(body))


def pckd_test_coupon(serial=0):
    """The test coupon's descriptor: lib/tools/coupon_desc.py test_coupon() (tests check the bytes are equal)."""
    lanes = {k: (0x03, r, x, L.TEST_LANE_TOL) for k, (x, r) in enumerate(zip(L.TEST_LANE_RATIOS, (399, 599, 599, 399)))}
    return pckd_encode(1, 120, 170, name="test coupon A", lanes=lanes,
                       glines={0: (5, 0), 1: (5, 1), 2: (5, 2), 3: (5, 3), 4: (6, 0), 5: (7, 0)},
                       i2c=[(0x50, 1)], spi=[(0, 3, 1_000_000)],
                       loads={0: (0, 0, 0, 30000, 0), 1: (1, 0, 1, 5000, 0), 2: (2, 1, 0, 30000, 0),
                              3: (3, 1, 1, 3333, 0x0F)},
                       serial=serial, c3v3_uf=10, c5v_uf=22)


def corrupt(img, how, limits=None):
    img = bytearray(img)
    if how == "crc":
        img[30] ^= 0x01                     # a flipped bit inside the records
    elif how == "blank":
        img = bytearray(b"\xff" * 256)
    elif how == "magic":
        img[0:4] = b"XXXX"
    elif how == "version":
        img[4] = 2
        length = struct.unpack_from("<H", img, 6)[0]
        struct.pack_into("<H", img, length - 2, desc_check.crc16_ccitt(bytes(img[:length - 2])))
    elif how == "over_rule":                 # declares 300 mA on +3V3 (rule 250 mA), CRC fixed up
        struct.pack_into("<H", img, 16, 300)
        length = struct.unpack_from("<H", img, 6)[0]
        struct.pack_into("<H", img, length - 2, desc_check.crc16_ccitt(bytes(img[:length - 2])))
    elif how == "pckc":                      # compiler v0's format, what make_eeprom.py writes
        img = bytearray(pckc_test_coupon() or b"PCKC\x01\x00\x00\x01".ljust(256, b"\0"))
    return bytes(img)


def pckc_test_coupon():
    """keyboard/tools/coupon's image of descriptors/test-coupon.json, if that tool is present."""
    tool = desc_check._load_tool(L.PCKC_TOOL, "tbbench_ext_descriptor_sim")
    src = L.PCKC_TOOL.parent / "descriptors" / "test-coupon.json"
    if tool is None or not src.exists():
        return None
    try:
        d = tool.load_json(str(src))
        d["git"] = "0" * 40 if d.get("git") == "auto" else d.get("git")
        return tool.encode(d)
    except Exception:  # noqa: BLE001
        return None


class SimDevice:
    """Write commands to it, read its lines back (tbbench.transport.SimTransport)."""

    def __init__(self, limits=None, coupons=None, source="3.0A", usb="configured", bench_build=False,
                 faults=None, serials=None):
        self.L = limits or L.Limits()
        self.f = faults or Faults()
        self.source = source            # what U_CC reads: default | 1.5A | 3.0A | accessory | not_attached
        self.usb = usb                  # unconfigured | configured | suspended
        self.bench_build = bench_build
        self.bench_ma = 0
        self.override_ma = 0
        self.base_ma = BASE_MA
        self.out = deque()
        self.ring = []                  # (seq, t_ms, text)
        self.seq = 1
        self.t_ms = 0
        self.cmd_count = 0
        self.polls = 0
        self.reset_cause = "por"
        self.boot_pre = None
        self.rails = list(self.L.rail_ids)          # in id order
        self.on = {}                                # rail -> declared mA, insertion order = enable order
        self.on_since = {}                          # rail -> cmd_count at enable
        self.ever_on = set()                        # rails enabled at least once (for a switch stuck on)
        self.stale_pending = set()
        self.bus = set()
        self.desc_err = {s: 1 for s in self.L.slots}   # 1 = none read
        self.desc = {}
        self.coupons = {}
        serials = serials or {}
        for s, kind in (coupons if coupons is not None else {1: "test"}).items():
            if kind and kind != "none":
                c = Coupon(kind, s, serials.get(s, TEST_SERIAL))
                if s in self.f.bad_descriptor:
                    c.eeprom = corrupt(c.eeprom, self.f.bad_descriptor[s]).ljust(256, b"\xff")
                self.coupons[s] = c
        self.test_load = {}             # rail -> extra uA from a self-test load
        self.inj = {}                   # slot -> "tp1" (a lead from the coupon's +3V3) or a voltage (the rig's)
        self.lines = set()              # slots whose direct lines the firmware drives (CS high, G low)
        self.i2c4_jammed = None         # the slot whose turned coupon holds I2C4's SCL low through the mux
        self.violations = []            # what the real board would not survive, as native_sim's rule checker counts
        self._held = {}                 # slot -> the coupon the operator took out to turn
        self.ina_cfg = {}               # rail -> INA226 configuration register (default 0x4527: 16 x 2.2 ms)
        self._rx = b""                  # rx_ring: bytes written since the host last read, not processed yet
        self._line = ""                 # rx_ring: the shell's line buffer (a line without its end yet)
        self._boot(printk=True)

    # --- I/O --------------------------------------------------------------------------------------------------
    def write(self, data):
        if self.f.rx_ring:
            # Zephyr's serial shell backend: input waits in a ring until the shell thread runs; what does not fit
            # is read and dropped (shell_uart.c uart_rx_handle). Modelled crudely: the shell runs when the host
            # reads, so everything written between two reads must fit in the ring.
            self._rx = (self._rx + data)[:self.f.rx_ring]
            return
        self._lines(data.decode("utf-8", "replace"))

    def _lines(self, text):
        for line in text.replace("\r", "\n").split("\n"):
            line = line.strip()
            if line:
                self._command(line)

    def readline(self):
        if self._rx:
            text, self._rx = self._line + self._rx.decode("utf-8", "replace"), b""
            done, _sep, self._line = text.replace("\r", "\n").rpartition("\n")
            self._lines(done)
        return self.out.popleft() if self.out else None

    def _p(self, text):
        if self.f.noisy:
            self.out.append("[00:00:01.234,000] <inf> tb_main: a log line\r\n")
            self.out.append(f"\x1b[1;32mtb:uart> \x1b[m\x1b[9D\x1b[J@tb {text}\r\n")
        else:
            self.out.append(f"@tb {text}\r\n")

    def _done(self, cmd, rc, err=None):
        if cmd in self.f.hang:
            return rc
        if err is None and rc < 0:
            err = ERRNO_TOKEN.get(rc, "error")
        self._p(f"done cmd={cmd} rc={rc}" + (f" err={err}" if err is not None else ""))
        return rc

    def ev(self, text):
        seq = self.seq
        self.seq += 1
        self.ring.append((seq, self.t_ms, text))
        self.ring = self.ring[-64:]
        if not self.f.drop_events:
            self._p(f"ev seq={seq} t_ms={self.t_ms} {text}")

    # --- operator-side actions (the scripted operator calls these) -------------------------------------------------
    def host_configure(self):
        self.usb = "configured"
        self.ev("kind=usb event=configured value=1 state=configured")
        self._budget_event()

    def host_reset(self):
        self.usb = "unconfigured"
        self.ev("kind=usb event=reset value=0 state=unconfigured")
        self._off(list(self.on), "usb")
        self._budget_event()

    def insert(self, slot, kind):
        """The operator plugs a coupon in (kind) or pulls it (None). Hot-plugging a powered slot is a violation."""
        if f"+3V3_S{slot}" in self.on or f"+5V_S{slot}" in self.on:
            self.violations.append(f"S{slot}: coupon plugged or pulled while powered")
        if kind in (None, "none"):
            self.coupons.pop(slot, None)
        else:
            self.coupons[slot] = Coupon(kind, slot)
        self.desc_err[slot] = 1
        self.ev(f"kind=present slot={slot} present={int(slot in self.coupons)}")

    def try_turned(self, slot):
        """The operator takes the coupon out and tries to push it back turned 180 degrees: True if it stayed out
        (the key). Without the plug it goes in turned; put_back() restores the coupon the right way round."""
        if slot in self.f.no_key_plug:
            self.turn(slot)
            return False
        return True

    def turn(self, slot):
        """The coupon in this slot taken out and plugged back turned 180 degrees (the key plug missing)."""
        self._held.setdefault(slot, self.coupons.get(slot))
        self.insert(slot, "turned")

    def put_back(self, slot):
        """The coupon held by turn() plugged back the right way round."""
        if slot in self._held:
            c = self._held.pop(slot)
            self.insert(slot, None)
            if c is not None:
                self.coupons[slot] = c
                self.ev(f"kind=present slot={slot} present=1")

    def set_inj(self, slot, src):
        """INJ high from "tp1" (a lead from the coupon's own +3V3) or a voltage (the rig); None: the lead off."""
        if src is None:
            if slot not in self.f.inj_stuck:
                self.inj.pop(slot, None)
        else:
            self.inj[slot] = src

    def press_nrst(self):
        """NRST with rails on: the expanders keep their outputs (SPEC §3.5); the firmware must restore them."""
        self.boot_pre = {r: True for r in self.on}
        self.reset_cause = "pin"
        self.on.clear()
        self.bus.clear()
        self.ring, self.seq = [], 1
        self.desc_err = {s: 1 for s in self.L.slots}
        self.usb = "unconfigured" if self.usb != "configured" else "configured"
        self._boot(printk=True)

    # --- model --------------------------------------------------------------------------------------------------
    def _vsys_ua(self):
        return int(self.f.vsys_idle_ma * 1000 + sum(self._ua(r) for r in self.rails if self._live(r)))

    def _vsys_mv(self):
        return int(5000 - self.f.vsys_drop_mv - self._vsys_ua() / 1000 * 0.05)

    def _live(self, r):
        """The rail conducts: enabled, or its switch is stuck on since it was first enabled."""
        return r in self.on or (r in self.f.stuck_on and r in self.ever_on)

    def _demand_ua(self, r):
        if not self._live(r) or r in self.f.dead_rails:
            return 0
        s = self.L.slot_of(r)
        ua = 0
        c = self.coupons.get(s)
        if c and r.startswith("+3V3"):
            ua = {"test": IDLE_TEST_UA, "blank": IDLE_TEST_UA, "turned": TURNED_UA}.get(c.kind, HALL_UA)
            if c.kind == "test" and self.inj.get(s) == "tp1" and self._inj_works(s):
                ua += 1100                  # INJ's 1.4 mA from TP1, less the ladder's 0.27 mA (sheets/test_coupon.py)
        ua += self.test_load.get(r, 0)
        ua += int(self.f.short_ma.get(r, 0) * 1000)
        if r in self.f.late_load_ma:
            n, ma = self.f.late_load_ma[r]
            if self.cmd_count - self.on_since.get(r, 0) >= n:
                ua += int(ma * 1000)
        return ua

    def _limit_ua(self, r):
        if r in self.f.climit_ma:
            return int(self.f.climit_ma[r] * 1000)
        t = self.L.trips_ma.get(r)
        return t[1] * 1000 if t else 10**9

    def _ua(self, r):
        if not self._live(r) and r in self.f.live_off_ua:
            return self.f.live_off_ua[r]
        return min(self._demand_ua(r), self._limit_ua(r))

    def _limiting(self, r):
        return r in self.on and self._demand_ua(r) > self._limit_ua(r)

    def _mv(self, r):
        if not self._live(r):
            s = self.L.slot_of(r)
            c = self.coupons.get(s)
            if r.startswith("+3V3") and c is not None and c.kind == "test" and isinstance(self.inj.get(s), float):
                return INJ_BACKFEED_MV                      # INJ from the rig back-feeds the coupon (D11, R40, ladder)
            return self.f.live_off_mv.get(r, 0)
        if r in self.f.dead_rails:
            return 0
        if self._limiting(r):
            return int(self._ua(r) / 1000 * 5)           # into the load that pulls it into its limit (5 ohm)
        if r.startswith("+3V3"):
            return int(3300 - self._ua(r) / 1000 * self.f.rs_mohm / 1000)
        return int(self._vsys_mv() - self._ua(r) / 1000 * 0.2)

    def _alert_ua(self, r):
        """src/board.c tb_rail_alert_ua(): the rail monitor's latching alert for its declared current."""
        return min(self.on.get(r, 0) * 1100 + 1000, self.L.trips_ma[r][0] * 950)

    def _fault_n(self):
        return self.f.fault_n_stuck or any(self._limiting(r) for r in self.on)

    def _reading(self, mon, fresh=True):
        """(current_ua, bus_mv) an INA226 shows; None if it does not answer."""
        if mon.addr in self.f.missing_monitors:
            return None
        if not fresh and mon.rail in self.stale_pending:
            self.stale_pending.discard(mon.rail)
            if L.ina_period_ms(self.ina_cfg.get(mon.rail, 0x4527)) > 20:   # settle_ms: older than one result
                return 0, 0
        if mon.rail == "VSYS":
            return self._vsys_ua(), self._vsys_mv()
        if mon.rail == "+3V3_MCU":
            return int(self.f.mcu_ma * 1000), int(3300 - self.f.mcu_ma * 0.5)
        if mon.rail == "+3V3_USB":
            return int(self.f.usb_ma * 1000), int(3300 - self.f.usb_ma * 1.0)
        return self._ua(mon.rail), self._mv(mon.rail)

    def _ina_line(self, mon, fresh=True):
        rd = self._reading(mon, fresh)
        if rd is None:
            return f"ina addr=0x{mon.addr:02x} rail={mon.rail} ok=0 err=io"
        ua, mv = rd
        cal = self.f.wrong_cal.get(mon.addr, mon.cal)
        cur = round(ua * cal / mon.cal / mon.lsb_ua) * mon.lsb_ua     # the current register scales with CAL
        shunt_raw = round(ua * 1e-6 * mon.shunt_ohm / 2.5e-6)
        sh_ua = int(shunt_raw * 2.5 / mon.shunt_ohm)
        return (f"ina addr=0x{mon.addr:02x} rail={mon.rail} ok=1 current_ua={cur} shunt_current_ua={sh_ua} "
                f"bus_mv={mv} shunt_uv={int(shunt_raw * 2.5)} power_uw={int(cur * mv / 1000)} "
                f"config=0x{self.ina_cfg.get(mon.rail, 0x4527):04x} "
                f"cal={cal} cal_expect={mon.cal} lsb_ua={mon.lsb_ua} shunt_uohm={int(mon.shunt_ohm * 1e6)} "
                f"me=0x0000 aff=0")

    # --- budget -------------------------------------------------------------------------------------------------
    def _limit_ma(self):
        if self.bench_ma:
            return min(self.bench_ma, self.L.vsys_max_ma)
        if self.usb != "configured":
            return 100
        src = "unreadable" if self.f.cc_absent else self.source
        lim = self.f.budget_ma if self.f.budget_ma is not None else self.L.budget_ma(src, True)
        return min(lim, self.override_ma) if self.override_ma else lim

    def _may_power(self):
        return bool(self.bench_ma) or self.usb == "configured"

    def _used_ma(self):
        return self.base_ma + sum(self.on.values())

    def _ldo_ma(self):
        return sum(v for r, v in self.on.items() if r.startswith("+3V3"))

    def _budget_event(self):
        src = "unreadable" if self.f.cc_absent else self.source
        self.ev(f"kind=budget limit_ma={self._limit_ma()} used_ma={self._used_ma()} source={src} usb={self.usb}")

    def _refuse(self, rail, ma):
        if self.usb == "suspended":
            return "suspended"
        if not self._may_power():
            return "unconfigured"
        if rail in self.on:
            return "already_on"             # lib/src/budget.c tb_budget_check(), after the state checks
        rule = self.L.by_rail[rail].rule_ma if rail in self.L.by_rail else None
        if rule and ma > rule:
            return "over_rule"
        s = self.L.slot_of(rail)
        if rail.startswith("+5V_S") and f"+3V3_S{s}" not in self.on:
            return "order"
        if self._used_ma() - self.on.get(rail, 0) + ma > self._limit_ma():
            return "over_vsys_budget"
        if rail.startswith("+3V3") and self._ldo_ma() - self.on.get(rail, 0) + ma > 300:
            return "over_slot_ldo"
        return None

    # --- rails --------------------------------------------------------------------------------------------------
    def _rail_on(self, rail, ma):
        if 0x20 in self.f.missing_expanders:
            return -5
        s = self.L.slot_of(rail)
        if s in self.bus:
            self.bus.discard(s)             # SPEC §3.5: the bus switch open while a rail comes up
        self.on[rail] = ma
        self.on_since[rail] = self.cmd_count
        self.ever_on.add(rail)
        if rail in self.f.stale_ina:
            self.stale_pending.add(rail)
        self.ev(f"kind=rail_on rail={rail} declared_ma={ma}")
        self.t_ms += 20
        return 0

    def _off(self, rails, reason):
        for r in rails:
            s = self.L.slot_of(r)
            if s:
                self.bus.discard(s)
                if r.startswith("+3V3"):
                    self.lines.discard(s)
            self.on.pop(r, None)
            self.test_load.pop(r, None)
            self.ev(f"kind=rail_off rail={r} reason={reason}")

    def _slot_off(self, s, reason):
        self._off(self.L.rails_of(s), reason)
        self.desc_err[s] = 1
        self.lines.discard(s)

    def _drive_lines(self, s):
        self.lines.add(s)
        c = self.coupons.get(s)
        if c is not None and c.kind == "turned":
            self.violations.append(f"S{s}: CS0_N/CS1_N/G0-G5 driven into a turned coupon")

    # --- the board service, after each command ---------------------------------------------------------------------
    def _service(self):
        if self.f.quiet_service:
            return
        self.polls += 1
        fault = self._fault_n()             # lib/src/trip.c: switch_limit only while SLOT_FAULT_N is low
        for r in list(self.on):
            if r not in self.L.trips_ma or r not in self.on or not fault:
                continue
            ua = self._ua(r)
            floor = self.L.trips_ma[r][0] * 1000 * L.SWITCH_LIMIT_FRACTION
            if ua >= floor:
                s = self.L.slot_of(r)
                self.ev(f"kind=trip finding=switch_limit rail={r} slot={s} value={ua}")
                self._slot_off(s, "trip") if r.startswith("+3V3") else self._off([r], "trip")
        # Each enabled rail's INA226 alert, which the firmware sets just above the declared current
        # (src/board.c tb_rail_alert_ua(): declared x 1.1 + 1 mA, at most 95 % of the switch's minimum trip) and
        # its classifier reports as "alert" after switch_limit (lib/src/trip.c), turning that rail off (its 3.3 V
        # takes the 5 V with it). Without it a coupon that starts to draw more than it declared, under the
        # switch_limit floor, would go unseen here although the firmware turns it off.
        for r in list(self.on):
            mon = self.L.by_rail.get(r)
            if r not in self.on or mon is None or mon.addr in self.f.missing_monitors or r not in self.L.trips_ma:
                continue
            ua = self._ua(r)
            if ua > self._alert_ua(r):
                s = self.L.slot_of(r)
                self.ev(f"kind=trip finding=alert rail={r} slot={s} value={ua}")
                self._slot_off(s, "trip") if r.startswith("+3V3") else self._off([r], "trip")
        for r in self.rails:
            mv = self._mv(r)                # lib/src/trip.c: bus_mv > live_mv || current_ua > live_ua (signed)
            if r not in self.on and r in self.L.by_rail and (mv > L.LIVE_OFF_MV or self._ua(r) > L.LIVE_OFF_UA):
                self.ev(f"kind=trip finding=rail_live_off rail={r} slot={self.L.slot_of(r) or 0} value={mv}")

    # --- boot ---------------------------------------------------------------------------------------------------
    def _boot(self, printk):
        warm_fail = self.f.nrst_restore_fail and self.boot_pre is not None
        self.restore_ok = not warm_fail and not self.f.missing_expanders and not self.f.missing_mux
        if printk:
            for line in self._boot_lines():
                self._p(line)
        self.ev(f"kind=boot restore_ok={int(self.restore_ok)}")
        if not self.f.cc_absent:
            self.ev(f"kind=cc source={self.source} ok=1 csr08=0x{self._csr08():02x} csr09=0x{self._csr09():02x}")
        self._budget_event()

    def _boot_lines(self):
        h = self.f.map_hash or TB_MAP_HASH
        lines = [f"boot fw=bringup board=kbd_testbed_a map={h} nets_rev={self.L.rev} zephyr=4.5.0 "
                 f"reset={self.reset_cause} snapshot=1 proto={self.f.proto} i2c1_bus=0 i2c4_bus=0"]
        warm = self.boot_pre is not None
        for i, addr in enumerate(sorted(self.L.expanders), 1):
            miss = addr in self.f.missing_expanders
            err = -5 if miss else 0
            pre_cfg = 0x0000 if (warm and i == 1) else 0xFFFF
            pre_out = 0xFFFF
            driven = 0
            if warm and i == 1:
                pins = self.L.expanders[addr][1]
                en = [p for p, n in pins.items() if n.startswith("EN_") and "+" + n[3:] in self.boot_pre]
                driven = 0xFFFF
                pre_out = 0x7C00 | sum(1 << _pin_bit(p) for p in en)
            ok = 0 if miss or (warm and i == 1 and self.f.nrst_restore_fail) else 1
            post_out = pre_out if not ok else {1: 0x7C00, 2: 0xFDFF, 3: 0xFF00}[i]
            lines.append(f"boot_exp exp={i} addr=0x{addr:02x} err={err} pre_in=0x{pre_out:04x} pre_out=0x{pre_out:04x} "
                         f"pre_cfg=0x{pre_cfg:04x} por={0 if (warm and i == 1) else 1} driven=0x{driven:04x} "
                         f"post_out=0x{post_out:04x} post_cfg=0x{ {1: 0, 2: 0xFCFF, 3: 0xE000}[i]:04x} ok={ok}")
        merr = -5 if self.f.missing_mux else 0
        lines.append(f"boot_mux err={merr} pre=0x00 post=0x00 post_err={merr}")
        for addr in sorted(self.L.monitors):
            m = self.L.monitors[addr]
            miss = addr in self.f.missing_monitors
            lines.append(f"boot_ina addr=0x{addr:02x} rail={m.rail} err={-5 if miss else 0} "
                         f"mfr=0x{0 if miss else 0x5449:04x} die=0x{0 if miss else 0x2260:04x} "
                         f"cal={self.f.wrong_cal.get(addr, m.cal)}")
        lines.append(f"boot_restore ok={int(self.restore_ok)} err={0 if self.restore_ok else -5} board_err="
                     f"{0 if self.restore_ok else -5} lanes_err=0")
        return lines

    def _csr08(self):
        return {"default": 0x00, "1.5A": 0x10, "3.0A": 0x30}.get(self.source, 0x00)

    def _csr09(self):
        return {"not_attached": 0x00, "accessory": 0xC0}.get(self.source, 0xA0)

    # --- commands -----------------------------------------------------------------------------------------------
    def _command(self, line):
        words = line.split()
        if words[0] == "shell":
            if line not in ("shell echo off", "shell colors off", "shell vt100 off", "shell prompt off"):
                self.out.append(f"{words[1] if len(words) > 1 else 'shell'}: wrong parameter(s)\r\n")
            return
        if words[0] != "tb" or len(words) < 2:
            self.out.append(f"{words[0]}: command not found\r\n")
            return
        fn = getattr(self, "c_" + words[1], None)
        if fn is None or words[1] not in SHELL_ARGS:
            self.out.append("tb - PrettyCool testbed bring-up (keyboard/firmware/bringup/PROTOCOL.md)\r\n")
            return
        mand, opt = SHELL_ARGS[words[1]]
        if not mand <= len(words) - 1 <= mand + opt:
            # Zephyr's shell rejects the argument count itself: its usage text and no done line (PROTOCOL.md,
            # Completion), so the harness times out exactly as it would on the board
            self.out.append(f"{words[1]}: wrong parameter count\r\n")
            return
        self.cmd_count += 1
        self.t_ms += 10
        try:
            fn(words[2:])
        except _Usage:
            self._done(words[1], -22, "usage")
        self._service()

    def c_info(self, a):
        self._p(f"info fw=bringup proto={self.f.proto} board=kbd_testbed_a map={self.f.map_hash or TB_MAP_HASH} "
                f"nets_rev={self.L.rev} nets_date=2026-11-27 zephyr=4.5.0 uptime_ms={self.t_ms} "
                f"bench_build={int(self.bench_build)} tim1=0 settle_ms=20 period_ms=100")
        self._done("info", 0)

    def c_boot(self, a):
        for line in self._boot_lines():
            self._p(line)
        self._done("boot", 0)

    def c_safe(self, a):
        self._off(list(self.on), "operator")
        self.bus.clear()
        self.lines.clear()
        self.i2c4_jammed = None             # MUX_RST_N pulsed: every channel deselected
        ok = 1
        for i, addr in enumerate(sorted(self.L.expanders), 1):
            e_ok = int(addr not in self.f.missing_expanders)
            ok &= e_ok
            self._p(f"restore exp={i} out=0x{ {1: 0x7C00, 2: 0xFDFF, 3: 0xFF00}[i]:04x} "
                    f"cfg=0x{ {1: 0, 2: 0xFCFF, 3: 0xE000}[i]:04x} ok={e_ok}")
        merr = -5 if self.f.missing_mux else 0
        ok &= int(merr == 0)
        self.ev(f"kind=restore ok={ok}")
        self._p(f"restore mux=0x00 mux_err={merr} ok={ok}")
        self._done("safe", 0 if ok else -5, None if ok else "readback")

    def c_usb(self, a):
        speed = "none" if self.usb == "unconfigured" else "hs"
        self._p(f"usb state={self.usb} config={int(self.usb == 'configured')} speed={speed}")
        self._done("usb", 0)

    def c_cc(self, a):
        if self.f.cc_absent:
            self._p("cc present=0 decided=1 err=io")
            return self._done("cc", -5)
        att = {"not_attached": "not_attached", "accessory": "accessory"}.get(self.source, "attached_snk")
        mode = {"default": 0, "1.5A": 1, "3.0A": 3}.get(self.source, 0)
        self._p(f"cc present=1 id_ok=1 id=3032334253555400 rev=0x02 csr08=0x{self._csr08():02x} "
                f"csr09=0x{self._csr09():02x} csr0a=0x00 attached={att} mode={mode} source={self.source} int=0 "
                f"decided=1 usable=1")
        self._done("cc", 0)

    def _print_budget(self):
        src = "unreadable" if self.f.cc_absent else self.source
        self._p(f"budget usb={self.usb} source={src} may_power={int(self._may_power())} limit_ma={self._limit_ma()} "
                f"used_ma={self._used_ma()} base_ma={self.base_ma} ldo_used_ma={self._ldo_ma()} ldo_ma=300 "
                f"max_ma={self.L.vsys_max_ma} override_ma={self.override_ma} bench_ma={self.bench_ma} "
                f"bench_build={int(self.bench_build)}")
        for r in self.rails:
            if r in self.on:
                self._p(f"budget_rail rail={r} declared_ma={self.on[r]} seq={list(self.on).index(r) + 1}")

    def c_budget(self, a):
        rc, err = 0, None
        if len(a) == 1:
            return self._done("budget", -22, "usage")
        if len(a) >= 2:
            what, v = a[0], a[1]
            ma = 0 if v == "off" else _u32(v)
            if what == "override":
                self.override_ma = ma
            elif what == "base" and v != "off":
                self.base_ma = ma
            elif what == "bench":
                if not self.bench_build:
                    rc, err = -134, "not_built"
                elif self.usb == "configured":
                    rc, err = -1, "usb_configured"
                else:
                    self.bench_ma = min(ma, self.L.vsys_max_ma)
            else:
                rc, err = -22, "usage"
            if rc == 0:
                self.ev(f"kind=budget_set what={what} ma={ma} shed=0x000")
        self._print_budget()
        self._done("budget", rc, err)

    def _monitors_for(self, sel):
        mons = [self.L.monitors[a] for a in sorted(self.L.monitors)]
        if sel in (None, "all"):
            return mons
        s = sel.lower().lstrip("+")
        return [m for m in mons if m.rail.lower().lstrip("+") == s or f"0x{m.addr:02x}" == s]

    def c_ina(self, a):
        if a and a[0] == "cfg":
            if len(a) != 6:
                return self._done("ina", -22, "usage")
            avg, vb, vs, mode = (_u32(x) for x in a[2:6])
            try:
                if mode > 7:
                    raise ValueError(mode)
                cfg = 0x4000 | (L.INA_AVG.index(avg) << 9) | (L.INA_CT_US.index(vb) << 6) | \
                    (L.INA_CT_US.index(vs) << 3) | mode
            except ValueError:
                return self._done("ina", -22, "bad_config")
            for m in self._monitors_for(a[1]):
                self.ina_cfg[m.rail] = cfg
            # the firmware prints the value it writes; bit 14 reads back as 1 (0x0127 written, 0x4127 read)
            self._p(f"ina_cfg target={a[1]} config=0x{cfg & ~0x4000:04x} "
                    f"period_us={round(L.ina_period_ms(cfg) * 1000)}")
            return self._done("ina", 0)
        if a and a[0] == "alert":            # src/cmds.c: tb ina alert <rail> <mA>|off
            mons = self._monitors_for(a[1]) if len(a) == 3 and a[1] != "all" else []
            if len(mons) != 1:
                return self._done("ina", -22, "usage")
            ma = 0 if a[2] == "off" else _u32(a[2])
            m = mons[0]
            raw = min(0x7FFF, -(-ma * 1000 * int(m.shunt_ohm * 1e6) // 2_500_000)) if ma else 0
            self._p(f"ina_alert rail={m.rail} limit_ma={ma} limit_raw={raw}")
            return self._done("ina", 0)
        if a and a[0] == "drv":              # tb ina drv <rail>: the same monitor through Zephyr's driver
            mons = self._monitors_for(a[1]) if len(a) == 2 and a[1] != "all" else []
            if len(mons) != 1:
                return self._done("ina", -22, "usage")
            rd = self._reading(mons[0])
            if rd is None:
                return self._done("ina", -5)
            self._p(f"ina_drv rail={mons[0].rail} current_ua={rd[0]} bus_mv={rd[1]}")
            return self._done("ina", 0)
        for m in self._monitors_for(a[0] if a else None):
            self._p(self._ina_line(m, fresh=True))
        self._done("ina", 0)

    def _net_levels(self):
        lv = {}
        for s in self.L.slots:
            lv[f"EN_3V3_S{s}"] = int(f"+3V3_S{s}" in self.on)
            lv[f"EN_5V_S{s}"] = int(f"+5V_S{s}" in self.on)
            lv[f"BUSEN_N_S{s}"] = int(s not in self.bus)
            lv[f"S{s}_PRESENT_N"] = int(s not in self.coupons)
            lv[f"LED_S{s}"] = int(f"+3V3_S{s}" not in self.on)
            lv[f"S{s}_G4"] = lv[f"S{s}_G5"] = 0
        lv.update({"EN_5V_KVM": int("+5V_KVM" in self.on), "KVM_PRESENT_N": 1, "SLOT_FAULT_N": int(not self._fault_n()),
                   "PM_ALERT_N": 1, "MUX_RST_N": 1, "KVM_RST_N": 0, "VSYS_PG": 1,
                   "S5_PG": int("+5V_S5" in self.on), "USBC_INT_N": 1})
        return lv

    def c_exp(self, a):
        lv = self._net_levels()
        inputs = {"S1_PRESENT_N", "S2_PRESENT_N", "S3_PRESENT_N", "S4_PRESENT_N", "S5_PRESENT_N", "KVM_PRESENT_N",
                  "SLOT_FAULT_N", "PM_ALERT_N", "VSYS_PG", "S5_PG", "USBC_INT_N"}
        for i, addr in enumerate(sorted(self.L.expanders), 1):
            ref, pins = self.L.expanders[addr]
            if addr in self.f.missing_expanders:
                self._p(f"exp exp={i} addr=0x{addr:02x} ok=0 in=0x0000 out=0x0000 pol=0x0000 cfg=0x0000")
                continue
            word = sum(lv.get(n, 0) << _pin_bit(p) for p, n in pins.items())
            cfg = sum(1 << _pin_bit(p) for p, n in pins.items() if n in inputs)
            self._p(f"exp exp={i} addr=0x{addr:02x} ok=1 in=0x{word:04x} out=0x{word:04x} pol=0x0000 cfg=0x{cfg:04x}")
            for p in sorted(pins, key=_pin_bit):
                n = pins[p]
                self._p(f"net name={n} exp={i} pin={p} dir={'in' if n in inputs else 'out'} level={lv.get(n, 0)}")
        self._done("exp", 0)

    def _parse_rail(self, s):
        t = s.lower().lstrip("+")
        return next((r for r in self.rails if r.lower().lstrip("+") == t), None)

    def c_rail(self, a):
        rail = self._parse_rail(a[0]) if a else None
        if rail is None or len(a) < 2:
            return self._done("rail", -22, "usage")
        s = self.L.slot_of(rail)
        if a[1] == "on":
            if len(a) != 3:
                return self._done("rail", -22, "usage")
            ma = _u32(a[2])
            if s and s not in self.coupons:
                return self._done("rail", -19, "not_present")
            why = self._refuse(rail, ma)
            if why:
                return self._done("rail", -1, why)
            err = self._rail_on(rail, ma)
            if err:
                return self._done("rail", err)
            mon = self.L.by_rail.get(rail)
            if mon:
                self._p(self._ina_line(mon, fresh=False))
            self._p(f"rail rail={rail} on=1 declared_ma={ma} fault={int(self._fault_n())}")
            return self._done("rail", 0)
        if a[1] == "off":
            rails = [rail] + ([f"+5V_S{s}"] if rail.startswith("+3V3") else [])
            mask = sum(1 << self.L.rail_ids[r] for r in rails if r in self.on)
            self._off([r for r in rails if r in self.on], "operator")
            self._p(f"rail rail={rail} on=0 off_mask=0x{mask:03x}")
            return self._done("rail", 0)
        self._done("rail", -22, "usage")

    def _print_slot(self, s):
        present = int(s in self.coupons)
        on3, on5 = int(f"+3V3_S{s}" in self.on), int(f"+5V_S{s}" in self.on)
        bus = int(s in self.bus)
        if self.desc_err[s] == 0:
            d = self.desc[s]
            self._p(f"slot slot={s} present={present} on3={on3} on5={on5} bus={bus} desc=ok type={d['type']} "
                    f"rev={d['rev']} serial={d['serial']} i3v3_ma={d['i3v3_ma']} i5v_ma={d['i5v_ma']}")
        else:
            tok = "none" if self.desc_err[s] == 1 else self.desc_err[s]
            self._p(f"slot slot={s} present={present} on3={on3} on5={on5} bus={bus} desc={tok}")

    def _load_desc(self, s):
        """(raw bytes the firmware read, 0 or an error token). The mux missing reads as a bus error."""
        c = self.coupons[s]
        if self.f.missing_mux or self.i2c4_jammed is not None or c.kind == "turned":
            if c.kind == "turned":
                self.i2c4_jammed = s        # its SCL is on the coupon's GND: the selected channel holds I2C4 low
            self.desc_err[s] = "bus_error"
            return b"", "bus_error"
        img = c.eeprom
        n = 32
        if img[:4] == b"PCKD" and img[4] == 1:
            ln = struct.unpack_from("<H", img, 6)[0]
            if 26 <= ln <= 256:
                n = ln
        raw = img[:n]
        try:
            d = desc_check.parse_pckd(raw)
        except desc_check.DescError as e:
            self.desc_err[s] = e.kind
            return raw, e.kind
        self.desc[s], self.desc_err[s] = d, 0
        return raw, 0

    def c_slot(self, a):
        if not a:
            for s in self.L.slots:
                self._print_slot(s)
            return self._done("slot", 0)
        try:
            s = int(a[0])
        except ValueError:
            s = 0
        if s not in self.L.slots:
            return self._done("slot", -22, "usage")
        if len(a) == 1:
            self._print_slot(s)
            return self._done("slot", 0)
        if a[1] == "off":
            self._slot_off(s, "operator")
            self._print_slot(s)
            return self._done("slot", 0)
        if a[1] != "on":
            return self._done("slot", -22, "usage")
        opts, flags = {}, {x for x in a[2:] if "=" not in x}
        for x in a[2:]:                     # src/cmds.c arg_kv(): the first key=, numeric or not there at all
            k, eq, v = x.partition("=")
            if eq and k not in opts:
                try:
                    opts[k] = _u32(v)
                except _Usage:
                    opts[k] = None
        opts = {k: v for k, v in opts.items() if v is not None}
        if "nodesc" in flags and "ma3" not in opts:
            return self._done("slot", -22, "usage")
        res = {"on3": 0, "on5": 0, "bus": 0, "i3": 0, "v3": 0, "i5": 0, "v5": 0, "fault": 0, "desc": "none",
               "ma3": 0, "ma5": 0}
        rc, err = self._slot_on(s, opts, flags, res)
        self._p(f"slot_on slot={s} on3={res['on3']} on5={res['on5']} bus={res['bus']} i3_ua={res['i3']} "
                f"v3_mv={res['v3']} i5_ua={res['i5']} v5_mv={res['v5']} fault={res['fault']} desc={res['desc']} "
                f"ma3={res['ma3']} ma5={res['ma5']}")
        self._print_slot(s)
        self._done("slot", rc, err)

    def _settle(self, rail):
        mon = self.L.by_rail[rail]
        rd = self._reading(mon, fresh=False)
        return rd, int(self._fault_n())

    def _slot_on(self, s, opts, flags, res):
        r3, r5 = self.L.rails_of(s)
        rule3 = 250
        use_desc = "nodesc" not in flags
        if s not in self.coupons:
            return -19, "not_present"
        if r3 in self.on:
            rd = self._reading(self.L.by_rail[r3])
            res["i3"], res["v3"] = rd if rd else (0, 0)
        else:
            ma3 = min(int(opts.get("probe") or rule3), rule3) if use_desc else int(opts.get("ma3", 0))
            if not use_desc and "ma3" not in opts:
                return -22, "usage"
            why = self._refuse(r3, ma3)
            if why:
                return -1, why
            err = self._rail_on(r3, ma3)
            if err:
                return err, "rail_3v3"
            rd, fault = self._settle(r3)
            res["fault"] = fault
            if rd is None:
                self._slot_off(s, "3v3_check")
                return -5, "monitor"
            res["i3"], res["v3"] = rd
            trip_min = self.L.trips_ma[r3][0] * 1000
            if fault or rd[1] < L.FW_MIN_3V3_MV or rd[0] >= trip_min:
                self._slot_off(s, "3v3_check")
                return -5, "fault_3v3" if fault else "low_3v3" if rd[1] < L.FW_MIN_3V3_MV else "over_3v3"
        res["on3"] = 1
        if self.f.lines_before_desc and use_desc:
            self._drive_lines(s)            # the firmware before 2026-11-27 (risks.md EL-2)
        if use_desc:
            _raw, derr = self._load_desc(s)
            res["desc"] = "ok" if derr == 0 else derr
            if derr:
                if not ("keep" in flags and derr == "blank"):
                    self._slot_off(s, "no_descriptor")
                    res["on3"] = 0
                tok = "desc_bus" if derr == "bus_error" else derr
                return (0 if derr == "blank" and "keep" in flags else -2), tok
            d = self.desc[s]
            rule5 = 2000 if s == 5 else 500
            rule = "over_3v3_rule" if d["i3v3_ma"] > rule3 else "over_5v_rule" if d["i5v_ma"] > rule5 else None
            if rule:
                self._slot_off(s, rule)
                res["on3"] = 0
                return -1, rule
            res["ma3"], res["ma5"] = d["i3v3_ma"], d["i5v_ma"]
        else:
            res["ma3"], res["ma5"] = int(opts.get("ma3", 0)), int(opts.get("ma5", 0))
        self.on[r3] = res["ma3"]          # redeclared at what the descriptor says
        self._drive_lines(s)              # identified (or declared by the operator): now CS high, G low
        err_tok = None
        if r5 in self.on:
            res["on5"] = 1
            rd = self._reading(self.L.by_rail[r5])
            res["i5"], res["v5"] = rd if rd else (0, 0)
        elif res["ma5"] > 0:
            why = self._refuse(r5, res["ma5"])
            if why:
                err_tok = why
            else:
                self._rail_on(r5, res["ma5"])
                rd, fault = self._settle(r5)
                res["fault"] = fault
                if rd is None or fault or rd[1] < L.FW_MIN_5V_MV or rd[0] >= self.L.trips_ma[r5][0] * 1000:
                    self._off([r5], "5v_check")
                    err_tok = "monitor" if rd is None else "fault_5v" if fault else (
                        "low_5v" if rd[1] < L.FW_MIN_5V_MV else "over_5v")
                    if rd:
                        res["i5"], res["v5"] = rd
                else:
                    res["on5"] = 1
                    res["i5"], res["v5"] = rd
        self.bus.add(s)
        res["bus"] = 1
        self.ev(f"kind=slot slot={s} on3={res['on3']} on5={res['on5']} bus=1 desc={res['desc']}")
        return (-11, err_tok) if err_tok else (0, None)

    def _print_desc(self, s, d):
        d = {**d, **{k: v for (ds, k), v in self.f.desc_parse_bug.items() if ds == s}}
        self._p(f"desc slot={s} status=ok len={d['length']} major=1 minor={d['minor']} type={d['type']} rev={d['rev']} "
                f"flags=0x{d['flags']:04x} serial={d['serial']} i3v3_ma={d['i3v3_ma']} i5v_ma={d['i5v_ma']} "
                f"c3v3_uf={d['c3v3_uf']} c5v_uf={d['c5v_uf']} name=\"{d['name']}\" slots=0x1f i2c=1 spi=1 cal=0 "
                f"unknown={d['unknown']}")
        for k, ln in sorted(d["lanes"].items()):
            self._p(f"desc_lane slot={s} lane={k} flags=0x{ln['flags']:02x} r_src_ohm={ln['r_src_ohm']} "
                    f"cload_pf={ln['cload_pf']} expect_ppm={ln['expect_ppm']} tol_ppm={ln['tol_ppm']}")
        for g, gl in sorted(d.get("glines", {}).items()):    # src/cmds.c print_desc(): every G-line with a role
            self._p(f"desc_gline slot={s} line=G{g} role={gl['role']} arg={gl['arg']}")
        for k, ld in sorted(d["loads"].items()):
            self._p(f"desc_load slot={s} load={k} line=G{ld['gline']} rail={ld['rail']} kind={ld['kind']} "
                    f"r_mohm={ld['r_mohm']} slots=0x{ld['slots']:02x}")

    def c_desc(self, a):
        try:
            s = int(a[0])
        except (ValueError, IndexError):
            s = 0
        if s not in self.L.slots:
            return self._done("desc", -22, "usage")
        if f"+3V3_S{s}" not in self.on:
            return self._done("desc", -13, "slot_off")
        if len(a) >= 3 and a[1] == "write" and a[2] == "test":
            opts = dict(x.split("=", 1) for x in a[3:] if "=" in x)
            try:                            # arg_kv(): a serial that is not a number is no serial (0)
                opts["serial"] = str(_u32(opts.get("serial", "0")))
            except _Usage:
                opts["serial"] = "0"
            _raw, derr = self._load_desc(s)
            if derr == 0 and "force" not in a[3:]:
                return self._done("desc", -17, "already_written")
            serial = int(opts.get("serial", "0"), 0)
            self.coupons[s].eeprom = pckd_test_coupon(serial).ljust(256, b"\xff")
            _raw, derr = self._load_desc(s)
            if derr:
                return self._done("desc", -5, "verify")
            self._print_desc(s, self.desc[s])
            self.ev(f"kind=desc_written slot={s} serial={serial}")
            return self._done("desc", 0)
        if len(a) != 1:
            return self._done("desc", -22, "usage")
        raw, derr = self._load_desc(s)
        for off in range(0, len(raw), 16):
            self._p(f"desc_hex slot={s} off={off} data={raw[off:off + 16].hex()}")
        if derr == "bus_error":
            self._p(f"desc slot={s} status=bus_error")
            return self._done("desc", -5, "bus_error")
        if derr:
            self._p(f"desc slot={s} status={derr}")
            return self._done("desc", -2, derr)
        self._print_desc(s, self.desc[s])
        self._done("desc", 0)

    def _inj_works(self, s):
        return s not in self.f.inj_open

    def _inj_lift_v(self, s, tap=0):
        """The lift INJ high gives at the tap it enters (sheets/test_coupon.py: AN0, (V_INJ - VF - 0.2 V3) x
        399 / (399 + 1045) through R40 and the diode), or the inj_lift fault's value; 0 with INJ low or its path
        open. tap: the ladder tap it enters (the inj_tap fault), whose Thevenin resistance sets the lift."""
        src = self.inj.get(s)
        if src is None or not self._inj_works(s):
            return 0.0
        if s in self.f.inj_lift:
            return self.f.inj_lift[s]
        v3 = self._mv(f"+3V3_S{s}") / 1000.0
        v_inj = v3 if src == "tp1" else float(src)
        r_th = (tap + 1) * (4 - tap) / 5 * 499
        return max(0.0, (v_inj - INJ_VF_V - (tap + 1) / 5 * v3) * r_th / (r_th + 1045))

    def _inj_lane_v(self, s, k):
        """What INJ adds to lane k: the lift at its entry tap, spread through the ladder (to GND below, to the
        coupon's stiff +3V3 above)."""
        tap = self.f.inj_tap.get(s, 0)
        d = self._inj_lift_v(s, tap)
        return d * (k + 1) / (tap + 1) if k <= tap else d * (4 - k) / (4 - tap)

    def _lane_ratio(self, s, k):
        """The fraction of VREF+ a lane reads (VREF+ = VDDA = 3.3 V from the slot LDO)."""
        c = self.coupons.get(s)
        if f"+3V3_S{s}" not in self.on or c is None or c.kind in ("hall", "turned"):
            return 0.5 if c is None or f"+3V3_S{s}" not in self.on else 0.31 if c.kind == "hall" else 0.0
        ratio = self.f.lane_ratio.get((s, k), L.TEST_LANE_RATIOS[k])
        v = ratio * self._mv(f"+3V3_S{s}") / 3300.0
        if c.kind == "test":
            v += self._inj_lane_v(s, k) / 3.3
        return v

    @staticmethod
    def _code(ratio, bits):
        return max(0, min((1 << bits) - 1, int(ratio * (1 << bits))))

    @staticmethod
    def _ppm(code, bits):
        return code * 1_000_000 // (1 << bits)

    def c_lanes(self, a):
        if a and (not a[0].isdigit() or int(a[0]) not in self.L.slots):
            return self._done("lanes", -22, "usage")
        slots = [int(a[0])] if a else list(self.L.slots)
        self._p("vdda mv=3300 ok=1")
        bad = 0
        for s in slots:
            on3 = int(f"+3V3_S{s}" in self.on)
            d = self.desc.get(s) if self.desc_err.get(s) == 0 else None
            prim = {}
            for k, chans in enumerate(self.L.lane_adc[s]):
                adc, ch = _adc(chans[0])
                bits = ADC_BITS[adc]
                code = self._code(self._lane_ratio(s, k), bits)
                ppm = self._ppm(code, bits)
                prim[k] = ppm
                state = "low" if ppm < 10000 else "high" if ppm > 990000 else "mid"
                if on3 and d and k in d["lanes"]:
                    exp, tol = d["lanes"][k]["expect_ppm"], d["lanes"][k]["tol_ppm"]
                    e = ppm - exp
                    ok = abs(e) <= tol or self.f.lane_ok_bug
                    bad += not ok
                    self._p(f"lane slot={s} lane={k} adc={adc} ch={ch} bits={bits} code={code} ratio_ppm={ppm} "
                            f"state={state} expect_ppm={exp} err_ppm={e} ok={int(ok)}")
                else:
                    self._p(f"lane slot={s} lane={k} adc={adc} ch={ch} bits={bits} code={code} ratio_ppm={ppm} "
                            f"state={state} powered={on3}")
            for k, chans in enumerate(self.L.lane_adc[s]):
                for name in chans[1:]:
                    adc, ch = _adc(name)
                    bits = ADC_BITS[adc]
                    code = self._code(self._lane_ratio(s, k) + self.f.adc_disagree.get((s, k, adc), 0) / 1e6, bits)
                    diff = self._ppm(code, bits) - prim[k]
                    agree = abs(diff) <= L.AGREE_PPM
                    bad += on3 and not agree
                    self._p(f"lane_alt slot={s} lane={k} adc={adc} ch={ch} bits={bits} code={code} diff_ppm={diff} "
                            f"agree={int(agree)} powered={on3}")
        self._done("lanes", -5 if bad else 0, "check" if bad else None)

    def c_selftest(self, a):
        try:
            s = int(a[0])
        except (ValueError, IndexError):
            return self._done("selftest", -22, "usage")
        if s not in self.L.slots:
            return self._done("selftest", -22, "usage")
        opts = set(a[1:])
        loads = bool(opts & {"loads", "all"})
        climit = bool(opts & {"climit", "all"})
        r3, r5 = self.L.rails_of(s)
        steps = []

        def step(name, result, kv=""):
            steps.append(result)
            self._p(f"step slot={s} name={name} result={result}" + (f" {kv}" if kv else ""))

        # power
        if r3 not in self.on or self.desc_err.get(s) != 0:
            if s in self.coupons:
                self._slot_on(s, {}, set(), {"on3": 0, "on5": 0, "bus": 0, "i3": 0, "v3": 0, "i5": 0, "v5": 0,
                                             "fault": 0, "desc": "none", "ma3": 0, "ma5": 0})
        if r3 not in self.on or self.desc_err.get(s) != 0:
            step("power", "fail", "err=" + ("blank_descriptor" if self.desc_err.get(s) == "blank" else "slot_on"))
            return self._end_selftest(s, steps)
        d = self.desc[s]
        if d["type"] != "test" and "force" not in opts:
            step("power", "fail", f"err=not_a_test_coupon type={d['type']}")
            return self._end_selftest(s, steps)
        if r5 in self.on:
            self._off([r5], "selftest")
        self.bus.add(s)
        step("power", "pass", f"serial={d['serial']}")
        mon3 = self.L.by_rail[r3]
        rd = self._reading(mon3)
        if rd is None:
            step("idle", "fail", "err=monitor")
        else:
            step("idle", "pass" if rd[1] >= 3000 and rd[0] < 10000 else "fail", f"i_ua={rd[0]} bus_mv={rd[1]}")
        # lanes
        ok, kv = True, []
        ppm = {}
        for k in range(4):
            adc, _ch = _adc(self.L.lane_adc[s][k][0])
            bits = ADC_BITS[adc]
            ppm[k] = self._ppm(self._code(self._lane_ratio(s, k), bits), bits)
            exp, tol = d["lanes"][k]["expect_ppm"], d["lanes"][k]["tol_ppm"]
            ok &= abs(ppm[k] - exp) <= tol
            kv.append(f"an{k}_ppm={ppm[k]} an{k}_err_ppm={ppm[k] - exp}")
        for (ds, dk, dadc), dppm in sorted(self.f.adc_disagree.items()):
            if ds == s and abs(dppm) > L.AGREE_PPM:
                ok = False
                kv.append(f"disagree=an{dk}_adc{dadc} diff_ppm={dppm}")
                break
        step("lanes", "pass" if ok else "fail", " ".join(kv) + " ")
        # loopback
        pats = [(0x00, 0, 0xA5), (0x01, 0, 0x5A), (0x04, 0, 0x3C), (0x08, 0, 0xC3), (0x10, 0, 0x0F), (0x20, 0, 0xF0),
                (0x00, 1, 0x99), (0x15, 1, 0x66)]
        runs, fails, kv = 0, 0, ""
        inj = self.inj.get(s) is not None     # the '165's INJ input sees INJ whether or not D11's path is whole

        def add(text):                      # src/coupon_test.c kv(): a 160-byte buffer, the rest is lost
            nonlocal kv
            if len(kv) < KV_MAX:
                kv = (kv + text)[:KV_MAX]
        for i, (g, sync, tx) in enumerate(pats):
            if s == 5 and g & 0x08:
                continue
            if s in self.f.short_loopback and runs >= self.f.short_loopback[s]:
                break
            runs += 1
            want = loopback_expect(g, sync, tx)
            rx = loopback_expect(g, sync, tx, inj=inj) | self.f.stuck_loopback.get(s, 0)
            irq = bool(g & 0x20) or inj         # Q15 pulls IRQ_N low while INJ is high
            if rx != want or irq != bool(g & 0x20):
                fails += 1
                add(f"p{i}_rx=0x{rx:04x} p{i}_want=0x{want:04x} p{i}_irq={int(irq)} ")
        add(f"patterns={runs} failed={fails}")
        step("loopback", "pass" if fails == 0 else "fail", kv.strip())
        # load3
        if not loads:
            step("load3", "skip")
        else:
            i0 = self._ua(r3)
            rs = self.f.rs_mohm / 1000.0
            r_load = d["loads"][0]["r_mohm"] / 1000.0
            v_open = 3300 - i0 / 1000 * rs                      # mV with the idle draw only
            self.test_load[r3] = int(v_open / (r_load + rs) * 1000)   # uA through the 30 ohm load
            i1, v1 = self._ua(r3), self._mv(r3)
            self.test_load.pop(r3, None)
            expect = round(v1 * 1000 / r_load)
            good = abs((i1 - i0) - expect) <= expect * L.LOAD_TOL
            step("load3", "pass" if good else "fail",
                 f"i0_ua={i0} i1_ua={i1} v1_mv={v1} expect_ua={expect} rs_mohm={self.f.rs_mohm + 1} vref_mv=3300")
        # load5
        if not loads or d["i5v_ma"] == 0:
            step("load5", "skip")
        else:
            why = self._refuse(r5, d["i5v_ma"]) if r5 not in self.on else None
            if why:
                step("load5", "fail", f"err={why}")
            else:
                if r5 not in self.on:
                    self.bus.discard(s)
                    self._rail_on(r5, d["i5v_ma"])
                    self.bus.add(s)
                r_load = d["loads"][2]["r_mohm"] / 1000.0
                self.test_load[r5] = int(self._mv(r5) / r_load * 1000)
                i1, v1 = self._ua(r5), self._mv(r5)
                self.test_load.pop(r5, None)
                expect = round(v1 * 1000 / r_load)
                step("load5", "pass" if abs(i1 - expect) <= expect * L.LOAD_TOL else "fail",
                     f"i0_ua=0 i1_ua={i1} v1_mv={v1} expect_ua={expect} ")
        # climit3 / climit5
        for name, rail, active in (("climit3", r3, climit), ("climit5", r5, climit)):
            if not active:
                step(name, "skip")
                continue
            if name == "climit5" and s == 5:
                step(name, "skip", "reason=never_on_s5")
                continue
            if name == "climit5" and r5 not in self.on:
                step(name, "skip", "reason=5v_off")
                continue
            t = self.L.trips_ma[rail]
            if self._used_ma() - self.on.get(rail, 0) + t[2] > self._limit_ma():
                step(name, "fail", "err=over_vsys_budget")
                continue
            i = self._limit_ua(rail)
            lo, hi = t[0] * 1000 * (1 - L.CLIMIT_TOL), t[2] * 1000 * (1 + L.CLIMIT_TOL)
            good = lo <= i <= hi
            step(name, "pass" if good else "fail",
                 f"i_ua={i} bus_mv={int(i / 1000 * (5 if rail.startswith('+3V3') else 3.333))} "
                 f"trip_ma={t[0]}/{t[1]}/{t[2]} fault=1 cleared={int(not self.f.fault_n_stuck)}")
        self._end_selftest(s, steps)

    def _end_selftest(self, s, steps):
        p, f_, k = steps.count("pass"), steps.count("fail"), steps.count("skip")
        self._p(f"selftest slot={s} result={'fail' if f_ else 'pass'} passed={p} failed={f_} skipped={k}")
        self.ev(f"kind=selftest slot={s} result={'fail' if f_ else 'pass'} failed={f_}")
        self._done("selftest", -5 if f_ else 0)

    def c_trips(self, a):
        findings = []
        for r in self.rails:
            if r not in self.L.by_rail:
                continue
            ua, mv = self._ua(r), self._mv(r)
            if r in self.on:
                if ua >= self.L.trips_ma[r][0] * 1000 * L.SWITCH_LIMIT_FRACTION:
                    findings.append(("switch_limit", r, ua))
                elif mv < 500:
                    findings.append(("rail_dead", r, mv))
                elif mv < (L.FW_MIN_3V3_MV if r.startswith("+3V3") else L.FW_MIN_5V_MV):
                    findings.append(("rail_sag", r, mv))
            elif mv > L.LIVE_OFF_MV or ua > L.LIVE_OFF_UA:
                findings.append(("rail_live_off", r, mv))
        if self.f.fault_n_stuck:
            findings.append(("fault_unattributed", None, 0))
        on = sum(1 << self.L.rail_ids[r] for r in self.on)
        absent = sum(1 << (s - 1) for s in self.L.slots if s not in self.coupons)
        self._p(f"trips exp2=0xf5fe on=0x{on:03x} fault={int(self._fault_n())} alert=0 vsys_pg=1 "
                f"s5_pg={int('+5V_S5' in self.on)} absent=0x{absent:02x} vsys_ua={self._vsys_ua()} "
                f"findings={len(findings)} off=0x000 shed_one=0 all_off=0 applied=0")
        for kind, r, v in findings:
            self._p(f"trip finding={kind} rail={r or '-'} slot={(self.L.slot_of(r) or 0) if r else 0} value={v}")
        for r in self.rails:
            mon = self.L.by_rail.get(r)
            if mon and mon.addr not in self.f.missing_monitors:
                self._p(f"trip_rail rail={r} on={int(r in self.on)} current_ua={self._ua(r)} "
                        f"bus_mv={self._mv(r)} aff=0")
        self._done("trips", 0)

    def c_mon(self, a):
        if a and not (len(a) == 2 and a[0] == "period"):
            return self._done("mon", -22, "usage")
        if a:
            _u32(a[1])
        self._p(f"mon period_ms=100 polls={self.polls} faults_handled=0 ev_next={self.seq}")
        self._done("mon", 0)

    def c_ev(self, a):
        since = _u32(a[0]) if a else 0
        n = 0
        for seq, t, text in self.ring:
            if seq >= since:
                self._p(f"ev seq={seq} t_ms={t} {text}")
                n += 1
        self._p(f"ev_dump since={since} next={self.seq} replayed={n}")
        self._done("ev", 0)

    def c_reboot(self, a):
        self._done("reboot", 0)
        self.on.clear()
        self.bus.clear()
        self.ring, self.seq, self.reset_cause = [], 1, "software"
        self._boot(printk=True)


ERRNO_TOKEN = {-5: "io", -22: "inval", -1: "perm", -19: "nodev", -16: "busy", -13: "acces", -2: "noent",
               -116: "timedout", -11: "again", -134: "notsup", -28: "nospc", -17: "exist", -114: "already"}

# The firmware's shell registration, keyboard/firmware/bringup/src/cmds.c: SHELL_CMD_ARG(<name>, NULL, <help>,
# <handler>, <mandatory>, <optional>), where Zephyr counts the subcommand itself among the arguments. A line outside
# these counts never reaches the handler. tests/test_simdev.py reads cmds.c and holds this table equal to it.
SHELL_ARGS = {"info": (1, 0), "boot": (1, 0), "safe": (1, 0), "usb": (1, 0), "cc": (1, 0), "budget": (1, 2),
              "ina": (1, 6), "exp": (1, 0), "rail": (3, 1), "slot": (1, 5), "desc": (2, 4), "lanes": (1, 1),
              "selftest": (2, 4), "trips": (1, 1), "mon": (1, 2), "ev": (1, 1), "reboot": (1, 0)}


class _Usage(Exception):
    """An argument the firmware's handler refuses: rc=-22 err=usage (src/cmds.c)."""


def _u32(s):
    """src/cmds.c parse_u32(): the whole word as an unsigned number (decimal or 0x hex), else a usage error."""
    try:
        v = int(s, 0)
    except (TypeError, ValueError):
        raise _Usage(s) from None
    if v < 0:
        raise _Usage(s)
    return v


def _pin_bit(p):
    """'P00'..'P17' -> 0..15 (port 0 bits 0-7, port 1 bits 8-15)."""
    return int(p[1]) * 8 + int(p[2])


def _adc(name):
    """'ADC1_IN13' -> (1, 13)."""
    a, _, ch = name.partition("_IN")
    return int(a[3:]), int(ch)


def loopback_expect(g, sync, tx, inj=False):
    """What the test coupon's SN74LV165A returns (sheets/test_coupon.py): bits 15-8 = G0..G5, INJ, SYNC (G0 first
    out), bits 7-0 = the byte sent on MOSI, eight clocks late. G3 is never driven on S5 (handled by the caller)."""
    hi = 0
    for k in range(6):
        hi |= ((g >> k) & 1) << (7 - k)
    hi |= int(inj) << 1
    hi |= int(sync)
    return (hi << 8) | tx


# --- faults from the command line ("bench.py sim --fault NAME[=VALUE]") ------------------------------------------
FAULT_HELP = {
    "dead_rail=<rail>": "the rail's switch never conducts (0 V, 0 A): a missing JP_3V3_Sn, a dead TPS2553",
    "missing_monitor=<0xaddr>": "that INA226 never answers",
    "missing_expander=<0xaddr>": "that TCA9535 never answers",
    "missing_mux": "the TCA9548A never answers (every descriptor read fails)",
    "cc_absent": "nothing at 0x67 (U_CC missing or on the wrong address)",
    "short=<rail>:<mA>": "the coupon draws this much more on the rail from the moment it turns on (a slot that trips)",
    "late_load=<rail>:<commands>:<mA>": "the extra load appears that many commands after the rail turned on",
    "bad_descriptor=<slot>:<crc|blank|magic|version|over_rule|pckc>": "the coupon's EEPROM image is damaged",
    "wrong_divider=<slot>:<lane>:<ratio>": "a lane reads this fraction of +3V3 instead of k/5",
    "stuck_loopback=<slot>:<mask>": "MISO bits stuck high in the test coupon's loopback",
    "climit=<rail>:<mA>": "where the rail's switch really limits",
    "vsys_idle_ma=<mA>": "the board's base load",
    "fault_n_stuck": "SLOT_FAULT_N held low",
    "stale_ina=<rail>": "the first reading after an enable is stale (the INA226 averaging against settle_ms)",
    "drop_events": "live event lines are lost (the ring keeps them)",
    "noisy": "prompts, VT100 escapes and log lines around every record",
    "hang=<command>": "that tb command never prints its done line",
    "lane_ok_bug": "the firmware reports ok=1 for every lane whatever it reads",
    "proto=<n>": "the firmware speaks another protocol version",
    "map_hash=<hex>": "the firmware was built from another board map",
    "live_off=<rail>:<mV>": "an off rail reads this voltage (back-powered)",
    "live_off_ua=<rail>:<uA>": "an off rail reads this current; negative: flowing backwards through its shunt",
    "nrst_restore_fail": "after NRST the firmware fails to restore U_EXP1",
    "wrong_cal=<0xaddr>:<cal>": "that INA226 holds another CAL than SPEC §3.4's (its current register scales with it)",
    "budget_ma=<mA>": "the firmware's configured VSYS budget, whatever U_CC reports (a budget table not nets.py's)",
    "quiet_service": "the board service never runs: no trip events and no rail turned off by the firmware itself",
    "stuck_on=<rail>": "the rail's switch ignores its enable once on (a damaged TPS2553): live after off and tb safe",
    "adc_disagree=<slot>:<lane>:<adc>:<ppm>": "an alternate converter reads that lane this many ppm off the primary",
    "short_loopback=<slot>:<n>": "the self-test runs only n loopback patterns, and calls the loopback passed",
    "desc_parse_bug=<slot>:<key>:<value>": "the firmware's desc record says this, whatever the EEPROM's bytes say",
    "rx_ring=<bytes>": "the shell keeps only this much input between two reads and drops the rest (Zephyr: 64)",
    "inj_open=<slot>": "the test coupon's INJ-to-AN0 path is open (D11 or R40 missing, D7): INJ high lifts nothing",
    "inj_lift=<slot>:<V>": "INJ high lifts AN0 by this much (D11 shorted: about 0.75 V; the design: 0.43-0.58 V)",
    "inj_stuck=<slot>": "INJ stays high after the operator removes the lead",
    "inj_tap=<slot>:<tap>": "R40 lands on another ladder tap (0-3) than AN0's (a wrong net)",
    "inj_rig=<slot>:<V>": "INJ driven by the rig at V (JP_INJn closed): it stays high with the slot off (back-feed)",
    "no_key_plug=<slot>": "socket hole 39 is not plugged: the test coupon goes in turned 180 degrees (D2)",
    "lines_before_desc": "the firmware drives the slot's lines before its descriptor is read (risks.md EL-2)",
    "vsys_drop_mv=<mV>": "VSYS this much lower: a source or cable worse than the USB-C load line (SPEC §3.6)",
}


def parse_fault(spec, f=None):
    """'short=+3V3_S1:400' -> a Faults with that fault set (added to f if given)."""
    f = f or Faults()
    name, _, val = spec.partition("=")
    parts = val.split(":") if val else []
    try:
        if name == "dead_rail":
            f.dead_rails.add(parts[0])
        elif name == "missing_monitor":
            f.missing_monitors.add(int(parts[0], 0))
        elif name == "missing_expander":
            f.missing_expanders.add(int(parts[0], 0))
        elif name == "missing_mux":
            f.missing_mux = True
        elif name == "cc_absent":
            f.cc_absent = True
        elif name == "short":
            f.short_ma[parts[0]] = float(parts[1])
        elif name == "late_load":
            f.late_load_ma[parts[0]] = (int(parts[1]), float(parts[2]))
        elif name == "bad_descriptor":
            f.bad_descriptor[int(parts[0])] = parts[1]
        elif name == "wrong_divider":
            f.lane_ratio[(int(parts[0]), int(parts[1]))] = float(parts[2])
        elif name == "stuck_loopback":
            f.stuck_loopback[int(parts[0])] = int(parts[1], 0)
        elif name == "climit":
            f.climit_ma[parts[0]] = float(parts[1])
        elif name == "vsys_idle_ma":
            f.vsys_idle_ma = float(parts[0])
        elif name == "fault_n_stuck":
            f.fault_n_stuck = True
        elif name == "stale_ina":
            f.stale_ina.add(parts[0])
        elif name == "drop_events":
            f.drop_events = True
        elif name == "noisy":
            f.noisy = True
        elif name == "hang":
            f.hang.add(parts[0])
        elif name == "lane_ok_bug":
            f.lane_ok_bug = True
        elif name == "proto":
            f.proto = int(parts[0])
        elif name == "map_hash":
            f.map_hash = parts[0]
        elif name == "live_off":
            f.live_off_mv[parts[0]] = int(parts[1])
        elif name == "live_off_ua":
            f.live_off_ua[parts[0]] = int(parts[1])
        elif name == "nrst_restore_fail":
            f.nrst_restore_fail = True
        elif name == "wrong_cal":
            f.wrong_cal[int(parts[0], 0)] = int(parts[1], 0)
        elif name == "budget_ma":
            f.budget_ma = int(parts[0], 0)
        elif name == "quiet_service":
            f.quiet_service = True
        elif name == "stuck_on":
            f.stuck_on.add(parts[0])
        elif name == "adc_disagree":
            f.adc_disagree[(int(parts[0]), int(parts[1]), int(parts[2]))] = int(parts[3])
        elif name == "short_loopback":
            f.short_loopback[int(parts[0])] = int(parts[1])
        elif name == "rx_ring":
            f.rx_ring = int(parts[0])
        elif name == "inj_open":
            f.inj_open.add(int(parts[0]))
        elif name == "inj_lift":
            f.inj_lift[int(parts[0])] = float(parts[1])
        elif name == "inj_stuck":
            f.inj_stuck.add(int(parts[0]))
        elif name == "inj_tap":
            f.inj_tap[int(parts[0])] = int(parts[1])
        elif name == "inj_rig":
            f.inj_rig[int(parts[0])] = float(parts[1])
        elif name == "no_key_plug":
            f.no_key_plug.add(int(parts[0]))
        elif name == "lines_before_desc":
            f.lines_before_desc = True
        elif name == "vsys_drop_mv":
            f.vsys_drop_mv = int(parts[0])
        elif name == "desc_parse_bug":
            f.desc_parse_bug[(int(parts[0]), parts[1])] = int(parts[2], 0) if parts[2].lstrip("-").isdigit() \
                else parts[2]
        else:
            raise ValueError(f"unknown fault {name!r}")
    except (IndexError, ValueError) as e:
        raise ValueError(f"fault {spec!r}: {e}; see bench.py faults") from e
    return f


def serve_pty(dev, fd, stop, chunk=7):
    """Serve a SimDevice on a pty's master side until stop is set: what the harness writes goes to the simulator,
    its lines come back in small chunks (a real UART splits lines anywhere). bench.py serve-sim and the pty test."""
    import os  # noqa: PLC0415
    import select  # noqa: PLC0415
    buf = b""
    while not stop.is_set():
        r, _w, _x = select.select([fd], [], [], 0.1)
        if not r:
            continue
        try:
            data = os.read(fd, 4096)
        except OSError:
            return
        buf += data.replace(b"\r", b"\n")
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            if line.strip():
                dev.write(line + b"\n")
        out = "".join(iter(dev.readline, None)).encode()
        for i in range(0, len(out), chunk):
            os.write(fd, out[i:i + chunk])


def operator_answers(dev, limits):
    """What a person at the simulated bench does when the harness asks (tbbench.prompts.ScriptedOperator answers):
    plug the host in, press NRST, read the meter, drive INJ from TP1 and take the lead off, try the coupon turned,
    plug a coupon in turned and back. bench.py sim and tests/conftest.py share it."""
    def inj_on(n):
        def f(_k, _t):
            dev.set_inj(n, dev.f.inj_rig.get(n, "tp1"))
            return True
        return f

    def inj_off(n):
        def f(_k, _t):
            dev.set_inj(n, None)
            return True
        return f

    a = {"host": lambda k, t: dev.host_configure() or True,
         "nrst": lambda k, t: dev.press_nrst() or True}
    for n in limits.slots:
        a[f"meter_i_S{n}"] = (lambda n: lambda k, t: dev._ua(f"+3V3_S{n}") / 1000.0)(n)
        a[f"meter_v_S{n}"] = (lambda n: lambda k, t: dev._mv(f"+3V3_S{n}") / 1000.0)(n)
        a[f"inj_S{n}"] = inj_on(n)
        a[f"inj_off_S{n}"] = inj_off(n)
        a[f"key_S{n}"] = (lambda n: lambda k, t: dev.try_turned(n))(n)
        a[f"key_back_S{n}"] = (lambda n: lambda k, t: dev.put_back(n) or True)(n)
        a[f"turned_in_S{n}"] = (lambda n: lambda k, t: dev.turn(n) or True)(n)
        a[f"turned_out_S{n}"] = (lambda n: lambda k, t: dev.put_back(n) or True)(n)
        a[f"turned_scope_S{n}"] = (lambda n: lambda k, t: any(v.startswith(f"S{n}:") and "turned" in v
                                                              for v in dev.violations))(n)
    return a
