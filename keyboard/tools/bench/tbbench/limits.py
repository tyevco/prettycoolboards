"""Pass/fail limits for the bench, each with where it comes from.

The board facts (monitor addresses, shunts, current LSBs, switch trip windows, the coupon rules, the expanders'
pins, the budget per USB-C advertisement) are read from nets.py, the contract SPEC and the firmware are both built
from, so a change there reaches the harness without an edit here. The windows that SPEC does not give are marked
"harness proposal" and are the first thing to revisit after the first boards are measured.

Sources quoted:
  SBOS547C (INA226, rev. August 2026, ti.com, SHA-256 c9b67f88...): shunt offset +/-10 uV max, bus offset +/-7.5 mV
    max, shunt and bus gain error 0.1 % max; "After all of the averaging has been completed, the final values ...
    are updated in the corresponding registers ... These values remain in the data output registers until the
    values are replaced by the next fully completed conversion results" (section 6.3.1).
  DS39724 Rev. 2-2 (AP2112, diodes.com, SHA-256 ef8d376f...): AP2112-3.3 VOUT 98.5 % to 101.5 % of 3.3 V at VIN 4.3 V,
    1 mA to 30 mA; load regulation -1 to 1 %/A.
  PROTOCOL.md and the firmware (keyboard/firmware/bringup): the self-test's own tolerances (lanes 1 %, converters
    3000 ppm, load steps 5 %, current limits 3 %), the slot rail floors (3.0 V and 4.3 V, src/slot.c) and the
    classifier's thresholds (lib/src/trip.c: switch_limit at 80 % of the minimum trip, rail_live_off above 1 V or
    5 mA). The harness re-applies them to the raw numbers, independently of the firmware's verdict.
"""

from __future__ import annotations

import os
import pathlib
import re
import runpy
from dataclasses import dataclass

HERE = pathlib.Path(__file__).resolve().parent
REPO = pathlib.Path(os.environ.get("TBBENCH_REPO") or HERE.parents[3])   # override: a copy outside the tree
NETS_PATH = REPO / "keyboard" / "hardware" / "design" / "nets.py"
MAP_HEADER = REPO / "keyboard" / "firmware" / "boards" / "prettycool" / "kbd_testbed_a" / "include" / "tb_board_map.h"
PCKC_TOOL = REPO / "keyboard" / "tools" / "coupon" / "descriptor.py"            # compiler v0's format ("PCKC")
PCKD_TOOL = REPO / "keyboard" / "firmware" / "lib" / "tools" / "coupon_desc.py"   # the bring-up firmware's ("PCKD")
GEN_BOARD = REPO / "keyboard" / "firmware" / "boards" / "gen_board.py"           # writes tb_board_map.h from nets.py

# --- INA226 (SBOS547C) --------------------------------------------------------------------------------------------
INA_SHUNT_OFFSET_V = 10e-6
INA_BUS_OFFSET_MV = 7.5
INA_GAIN = 0.001
INA_FULL_SCALE_V = 0.08192
INA_AVG = (1, 4, 16, 64, 128, 256, 512, 1024)
INA_CT_US = (140, 204, 332, 588, 1100, 2116, 4156, 8244)
SHUNT_TOLERANCE = 0.01          # harness proposal: SPEC gives the shunts' values, not their tolerance


def ina_period_ms(config):
    """How often an INA226 replaces its output registers under this configuration register value."""
    avg = INA_AVG[(config >> 9) & 7]
    vbus = INA_CT_US[(config >> 6) & 7]
    vsh = INA_CT_US[(config >> 3) & 7]
    mode = config & 7
    per = {7: vbus + vsh, 3: vbus + vsh, 5: vsh, 1: vsh, 6: vbus, 2: vbus}.get(mode, vbus + vsh)
    return avg * per / 1000.0


# --- regulators ---------------------------------------------------------------------------------------------------
AP2112_ACCURACY = 0.015         # DS39724 Rev. 2-2
AP2112_LOAD_REG_PER_A = 0.01
SLOT_3V3_NOMINAL_MV = 3300
SLOT_3V3_ACCURACY = 0.03        # harness proposal: the LDL1117's accuracy was not read (st.com unreachable)
SLOT_SERIES_OHM_MAX = 0.24 + 0.135 + 0.05   # shunt + TPS2553 135 mOhm max (SLVS841E via SPEC §3.1) + jumper (guess)
SLOT_5V_SERIES_OHM_MAX = {False: 0.1 + 0.135 + 0.02,   # S1-S4: the 0.1 ohm shunt, the TPS2553's 135 mOhm max
                          True: 0.020 + 0.045 + 0.02}    # S5: 20 mOhm, U5 (TPS259474L) at SPEC §3.6's 45 mOhm max
FW_MIN_3V3_MV = 3000            # src/slot.c MIN_3V3_MV, PROTOCOL.md low_3v3
FW_MIN_5V_MV = 4300             # src/slot.c MIN_5V_MV
VSYS_MV = (4500, 5500)          # harness proposal: USB 2.0's 4.75-5.25 V at the port, USB-C's 5.5 V maximum
                                # (SPEC §3.5), less the cable; a bench supply is set to 5.0 V
VDDA_MV = (3200, 3400)          # the firmware's vdda ok= window (src/cmds.c)

# --- currents -----------------------------------------------------------------------------------------------------
# Idle windows with no slot on. SPEC §3.2 estimates the base load at about 45 mA on VBUS and 32-58 mA on +3V3_MCU
# (with the HS PHY's 1.1 V part, an inference); the windows are wider on purpose (harness proposal).
IDLE_MA = {
    "VSYS": (10.0, 100.0),       # 100 mA: USB 2.0 before configuration (SPEC §3.2) - over it fails
    "+3V3_MCU": (10.0, 100.0),
    "+3V3_USB": (0.0, 30.0),     # 5.8 mA typ HS idle .. 13.5 mA transmit; 28 mA worst case (SPEC §3.3)
}
IDLE_DANGER_MA = {"VSYS": 200.0}   # harness proposal: 4 x the 45 mA estimate with nothing switched on
DANGER_FULL_SCALE = 0.95           # any monitor at 95 % of its full scale is treated as a short
LIVE_OFF_MV = 1000                 # lib/src/trip.c live_mv: an off rail reading more is back-powered
LIVE_OFF_UA = 5000                 # lib/src/trip.c live_ua
SWITCH_LIMIT_FRACTION = 0.80       # lib/src/trip.c limit_pct: the classifier's switch_limit floor
DECLARED_MARGIN = (1.10, 1000)     # current > declared x 1.10 + 1 mA: the coupon draws more than it declares

# --- the test coupon (keyboard/hardware/design/sheets/test_coupon.py) ---------------------------------------------
TEST_LANE_RATIOS = (0.2, 0.4, 0.6, 0.8)    # a 5 x 499 ohm ladder: AN0..AN3 = k/5 x +3V3 at the coupon
TEST_LANE_TOL = 0.01                        # PROTOCOL.md self-test: 1 % (lib/tools/coupon_desc.py TEST_LANE_TOL)
TEST_IDLE_UA_MAX = 10000                    # PROTOCOL.md self-test "idle": under 10 mA ...
TEST_IDLE_MV_MIN = 3000                     # ... at or above 3.0 V
AGREE_PPM = 3000                            # every other converter on a lane within 3000 ppm of the primary
LOAD_TOL = 0.05                             # load steps within 5 % of V / R
CLIMIT_TOL = 0.03                           # current-limit readings within the trip window +/- 3 %
RS_MOHM_PLAUSIBLE = (250, 600)              # harness proposal: SPEC §3.1's 0.24 ohm + 85-135 mOhm + the jumper
TEST_COUPON_SERIES_MOHM = 325               # what the native_sim model uses (sim/world.c), for the simulator
TEST_COUPON_SHEET = REPO / "keyboard" / "hardware" / "design" / "sheets" / "test_coupon.py"
# The INJ-to-lane path (owner's decision D7 of 2026-11-27; SPEC §4.7, §10 step 7): D11 + R40 (1 k) from INJ into the
# AN0 tap. These defaults are the sheet's DESCRIPTOR_FACTS["inj_lane"] (estimates, not measurements); inj_lane_facts()
# reads them from the sheet itself and tests/test_limits.py holds the two equal.
TEST_INJ_LIFT_V = (0.43, 0.58)              # AN0's lift with INJ high, over INJ 2.9-3.3 V, +3V3 3.2-3.4 V, R40 1 %
TEST_INJ_SHARES = (1.0, 0.75, 0.5, 0.25)    # AN0..AN3 move by these fractions of AN0's lift (the ladder above AN0)
INJ_LIFT_MARGIN = (0.02, 4)                 # harness proposal: the lift is a difference of two readings, each with
                                            # VDDA's error (VREFINT) and about 2 LSB of noise: 2 % and 4 LSB
INJ_SHARE_TOL = 0.02                        # harness proposal: the ladder's 0.1 % parts give the shares to 0.3 %
INJ_RETURN_LSB = 8                          # harness proposal: AN0 with INJ low again, against its reading before
INJ_BACKFEED_MV = 300                       # harness proposal: an off test-coupon rail above this after the INJ step
                                            # is fed through INJ (the sheet's estimate: 0.85-0.88 V, under the
                                            # firmware's 1 V live_mv)

# --- the coupons of rev A, in stages (owner's decision D1 of 2026-11-27, SPEC §1, §10) ----------------------------
A1_COUPONS = ("test", "hall")               # with the motherboard: released, ordered and brought up first
A2_COUPONS = ("tmr", "shear", "coil", "haptics")   # designed after A1; the KVM coupon is in neither stage
SPEC_STEP = {"test": "SPEC §10 step 7", "hall": "SPEC §10 step 8 (A1)"}
DESCRIPTOR_RECORDS = {                      # compiler v0's descriptor of record per coupon (keyboard/tools/coupon)
    "test": REPO / "keyboard" / "tools" / "coupon" / "descriptors" / "test-coupon.json",
    "hall": REPO / "keyboard" / "tools" / "coupon" / "descriptors" / "coupon-hall.json",
}

# --- VSYS on USB power (owner's decision D4 of 2026-11-27, SPEC §3.1, §3.6) -----------------------------------------
USBC_LOAD_LINE = (4.75, 0.25)               # V(J1) = 4.75 V - 0.25 ohm x I(J1): a legal source, a 3 A cable (§3.6)
U2_RON_MAX_OHM = 0.045                      # TPS259474L R_ON at its maximum (SPEC §3.6's load-line table)

# Event findings (PROTOCOL.md, Events) the harness stops on.
OVERCURRENT_FINDINGS = {"switch_limit", "s5_breaker", "alert", "alert_unattributed", "vsys_over",
                        "fault_unattributed", "fault_kvm"}
POWER_FINDINGS = {"vsys_pg_low"}             # the board's supply failed: every rail off
BACKPOWER_FINDINGS = {"rail_live_off"}       # an off rail reads a voltage or a current (SPEC §3.5)
DANGER_FINDINGS = OVERCURRENT_FINDINGS | POWER_FINDINGS | BACKPOWER_FINDINGS
DANGER_RAIL_OFF_REASONS = {"trip", "vsys_over_budget", "vsys_pg_low"}
DANGER_ERR_TOKENS = {"fault_3v3", "over_3v3", "fault_5v", "over_5v"}   # a rail's settling check saw a fault
LOW_ERR_TOKENS = {"low_3v3", "low_5v"}
DESC_FORMAT_ERRORS = ("crc", "magic", "version", "length", "record", "value", "duplicate", "full", "short")


@dataclass(frozen=True)
class Monitor:
    addr: int
    rail: str
    shunt_ohm: float
    rule_ma: float | None      # the coupon rule on that rail (SPEC §4.9), None for the board's own rails
    lsb_ua: int
    cal: int                   # CAL = 0.00512 / (LSB x R), rounded as Zephyr's driver rounds it (SPEC §3.4)

    @property
    def full_scale_ma(self):
        return INA_FULL_SCALE_V / self.shunt_ohm * 1000.0

    @property
    def switched(self):
        return self.rail.startswith(("+3V3_S", "+5V_S"))


class Limits:
    def __init__(self, nets_path=None):
        self.nets_path = pathlib.Path(nets_path or NETS_PATH)
        n = runpy.run_path(str(self.nets_path))
        self.nets = n
        self.rev = n["REV"]
        self.slots = tuple(n["SLOTS"])
        self.monitors = {}
        for addr, (rail, shunt, rule) in n["INA226_RAILS"].items():
            lsb = n["INA226_CURRENT_LSB_UA"][addr]
            self.monitors[addr] = Monitor(addr, rail, shunt, None if rule is None else rule * 1000.0, lsb,
                                          ina226_cal(lsb, shunt))
        self.by_rail = {m.rail: m for m in self.monitors.values()}
        self.trips_ma = {r: tuple(round(x * 1000) for x in t) for r, t in n["SWITCH_TRIP"].items()}
        self.expanders = {}
        refs = {v.split()[0]: a for a, v in n["EXPANDER_I2C"].items()}
        for ref, pins in n["EXPANDERS"].items():
            self.expanders[refs[ref]] = (ref, {p: net for p, net in pins.items() if net})
        self.mux_addr = next(iter(n["I2C_SLOT_UPSTREAM"]))
        self.cc_addr = n["typec_address"]()
        self.vsys_max_ma = round(n["VSYS_BUDGET_MAX"] * 1000)
        # rail ids of PROTOCOL.md's masks: bit 0-4 +3V3_S1-S5, 5-9 +5V_S1-S5, 10 +5V_KVM
        self.rail_ids = {**{f"+3V3_S{s}": s - 1 for s in self.slots}, **{f"+5V_S{s}": 4 + s for s in self.slots},
                         "+5V_KVM": 10}
        self.lane_adc = {s: [n["LANE_ADC"][n["SLOT_MCU"][s][f"AN{k}"]] for k in range(4)] for s in self.slots}
        self.slot_mcu = n["SLOT_MCU"]
        self.key_pin = n.get("SLOT_KEY_PIN")
        pg = n.get("vsys_pg_thresholds")
        self.vsys_pg = pg(0.01) if pg else None          # with both divider resistors 1 % off (E96 1 %, SPEC §3.1)
        self.vsys_shunt_ohm = n["INA226_RAILS"][0x40][1]
        inj = inj_lane_facts() or {}
        self.inj_lift_v = tuple(inj.get("lift_v", TEST_INJ_LIFT_V))
        also = inj.get("also_moves", {})
        self.inj_shares = (1.0, *(also.get(f"AN{k}", TEST_INJ_SHARES[k]) for k in (1, 2, 3)))

    # --- budget -------------------------------------------------------------------------------------------------
    def budget_ma(self, source, configured=True):
        """SPEC §3.2 / nets.vsys_budget: the VSYS budget for what U_CC reports ("pending" counts as Default)."""
        key = {"pending": "default", "not_attached": "not attached", "unreadable": "unreadable"}.get(source, source)
        if key not in self.nets["TYPEC_BUDGET"]:
            key = "default"
        return round(self.nets["vsys_budget"](key, configured) * 1000)

    # --- VSYS ---------------------------------------------------------------------------------------------------
    def vsys_load_line_mv(self, i_ma):
        """The lowest VSYS a legal USB-C source and cable give at this board current (SPEC §3.6, D4 of 2026-11-27):
        V(J1) = 4.75 V - 0.25 ohm x I, less U2 at its maximum R_ON and the 20 mohm VSYS shunt; the INA226 measures
        VSYS after both (arithmetic)."""
        v0, r_cable = USBC_LOAD_LINE
        return (v0 - i_ma / 1000.0 * (r_cable + U2_RON_MAX_OHM + self.vsys_shunt_ohm)) * 1000.0

    # --- per rail -----------------------------------------------------------------------------------------------
    @staticmethod
    def slot_of(rail):
        m = re.fullmatch(r"\+(3V3|5V)_S(\d)", rail)
        return int(m.group(2)) if m else None

    def rails_of(self, slot):
        return f"+3V3_S{slot}", f"+5V_S{slot}"

    def current_tolerance_ua(self, mon, i_ua):
        """How far an INA226 reading may sit from a reference meter: the shunt offset over R, the gain error, the
        shunt's tolerance (harness proposal) and two current LSBs."""
        return INA_SHUNT_OFFSET_V / mon.shunt_ohm * 1e6 + abs(i_ua) * (INA_GAIN + SHUNT_TOLERANCE) + 2 * mon.lsb_ua

    @staticmethod
    def bus_tolerance_mv(mv):
        return INA_BUS_OFFSET_MV + abs(mv) * INA_GAIN

    def always_on_window_mv(self, rail, i_ma):
        """+3V3_MCU and +3V3_USB: the AP2112K's 3.3 V +/- 1.5 % and its load regulation, less this shunt's drop at
        the measured current, widened by the INA226's bus error (DS39724, SBOS547C)."""
        mon = self.by_rail[rail]
        reg = 3300 * (AP2112_ACCURACY + AP2112_LOAD_REG_PER_A * 0.2)       # up to 200 mA on +3V3 (estimate)
        lo = 3300 - reg - i_ma * mon.shunt_ohm
        hi = 3300 + reg
        tol = self.bus_tolerance_mv(3300)
        return lo - tol, hi + tol

    def slot_3v3_window_mv(self, i_ma):
        lo = SLOT_3V3_NOMINAL_MV * (1 - SLOT_3V3_ACCURACY) - i_ma * SLOT_SERIES_OHM_MAX
        hi = SLOT_3V3_NOMINAL_MV * (1 + SLOT_3V3_ACCURACY)
        tol = self.bus_tolerance_mv(SLOT_3V3_NOMINAL_MV)
        return max(lo - tol, FW_MIN_3V3_MV), hi + tol

    def slot_5v_window_mv(self, slot, i_ma, vsys_mv):
        r = SLOT_5V_SERIES_OHM_MAX[slot == 5]
        tol = 2 * self.bus_tolerance_mv(5000)
        return max(vsys_mv - i_ma * r - tol, FW_MIN_5V_MV), vsys_mv + tol

    def danger_ma(self, rail, declared_ma=None):
        """The current above which an enabled switched rail counts as an over-current (stop the run): the
        classifier's switch_limit floor, or the coupon drawing clearly more than it declared."""
        trip_min = self.trips_ma.get(rail, (None,))[0]
        levels = []
        if trip_min:
            levels.append(trip_min * SWITCH_LIMIT_FRACTION)
        if declared_ma:
            levels.append(declared_ma * DECLARED_MARGIN[0] + DECLARED_MARGIN[1] / 1000.0)
        mon = self.by_rail.get(rail)
        if mon:
            levels.append(mon.full_scale_ma * DANGER_FULL_SCALE)
        return min(levels) if levels else None


def inj_lane_facts(path=TEST_COUPON_SHEET):
    """The test coupon sheet's DESCRIPTOR_FACTS["inj_lane"] (a dict literal), read with ast so the sheet's imports
    (the schematic toolchain) are not needed; None if the sheet or the entry is missing."""
    import ast  # noqa: PLC0415
    try:
        tree = ast.parse(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "DESCRIPTOR_FACTS" for t in node.targets) \
                and isinstance(node.value, ast.Dict):
            for k, v in zip(node.value.keys, node.value.values):
                if isinstance(k, ast.Constant) and k.value == "inj_lane":
                    try:
                        return ast.literal_eval(v)
                    except ValueError:
                        return None
    return None


def ina226_cal(lsb_ua, shunt_ohm):
    """CAL as Zephyr v4.5.0's ti,ina226 driver computes it, DIV_ROUND_CLOSEST(5120000000, LSB_uA x R_uohm) in
    integers (drivers/sensor/ti/ina2xx/ina226.c; the same as keyboard/firmware/boards/gen_board.py), so a value on
    a half rounds as the firmware's does, not as Python's round() (half to even)."""
    den = lsb_ua * round(shunt_ohm * 1e6)
    return (5120000000 + den // 2) // den


def map_hash_from_nets(nets_path=NETS_PATH, gen=GEN_BOARD):
    """The board map hash a firmware built from this nets.py would carry: gen_board.py's Map.hash(), sha256 of
    nets.py's bytes then gen_board.py's, first 16 hex digits. None if either file is missing."""
    import hashlib  # noqa: PLC0415
    try:
        return hashlib.sha256(pathlib.Path(nets_path).read_bytes() + pathlib.Path(gen).read_bytes()).hexdigest()[:16]
    except OSError:
        return None


def map_hash(path=MAP_HEADER):
    """The board map hash the firmware in this checkout is built with (gen_board.py output), or None."""
    try:
        m = re.search(r'#define TB_MAP_HASH "([0-9a-f]+)"', pathlib.Path(path).read_text())
    except OSError:
        return None
    return m.group(1) if m else None
