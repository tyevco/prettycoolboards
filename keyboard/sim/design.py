"""The design values the benches simulate, each with where it came from.

Three kinds of value:

* **Contract values** come from `keyboard/hardware/design/nets.py` at run time (switch trip points, shunts,
  coupon rules, the VSYS budget ceiling), so a contract change reaches every bench and test.
* **Capture values** come from the generated motherboard netlist,
  `keyboard/hardware/kicad/motherboard/prettycool-keyboard-motherboard.net`, when it exists: the lane RC, the
  breakers' R_ILM, C_ITIMER and C_dVdt, the UVLO and PG dividers, the bulk and socket capacitors. A capture change
  reaches the benches on the next run. If the netlist is missing, or a part is not found in it, the value captured
  on 2026-11-27 is used and `provenance()` says so.
* **Datasheet values** are constants below, each with its document and table. Where a datasheet gives no number
  (the TMAG5253's peak output current, the STM32U5 ADC's switch resistance, a TPS2553's fastest soft start), the
  bench brackets it and says so; nothing here is a measurement.

Nothing in this module or the benches is measured. Every result is arithmetic on these values.

**What-if and fault injection.** Three environment variables point the benches at other copies of the inputs, so a
proposed capture, contract or SPEC can be simulated (and a deliberately broken one shown to fail) without touching
the repository: `KBDSIM_NETLIST` (a motherboard .net file), `KBDSIM_NETS` (a nets.py) and `KBDSIM_SPEC` (a SPEC.md).
`provenance()` names the file each value came from.
"""

import importlib.util
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
DESIGN_DIR = os.path.join(REPO, "keyboard", "hardware", "design")
MB_NETLIST = os.environ.get("KBDSIM_NETLIST") or os.path.join(
    REPO, "keyboard", "hardware", "kicad", "motherboard", "prettycool-keyboard-motherboard.net")
NETS_PY = os.environ.get("KBDSIM_NETS") or os.path.join(DESIGN_DIR, "nets.py")
SPEC_MD = os.environ.get("KBDSIM_SPEC") or os.path.join(DESIGN_DIR, "SPEC.md")

_PROV = {}


def _note(key, source):
    _PROV[key] = source


def provenance():
    """key -> where its value came from ('nets.py', 'netlist <ref>', 'default ...', or a datasheet)."""
    return dict(_PROV)


# ---------------------------------------------------------------------------------------------------- nets.py
def load_nets():
    """Import the contract module without writing __pycache__ into a directory this tool does not own."""
    old = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("kbd_nets", NETS_PY)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = old
    return mod


# ---------------------------------------------------------------------------------------------------- values
_SI = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3, "k": 1e3, "K": 1e3, "M": 1e6, "R": 1.0, "": 1.0}


def parse_value(text):
    """'47' -> 47, '1n C0G' -> 1e-9, '2.2n' -> 2.2e-9, '1.47k' -> 1470, '10u/25V' -> 1e-5, '20m' -> 0.02, '1R' -> 1,
    '4k7' -> 4700. None if it does not parse."""
    s = text.strip().split()[0].split("/")[0]
    m = re.fullmatch(r"(\d+)([pnuµmkKMR])(\d+)", s)           # 4k7 style
    if m:
        return float(f"{m.group(1)}.{m.group(3)}") * _SI[m.group(2)]
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(?:([pnuµmkKMR])?)(?:F|Ω|ohm)?", s)
    if not m:
        return None
    return float(m.group(1)) * _SI[m.group(2) or ""]


# ---------------------------------------------------------------------------------------------------- netlist
def _sexpr(text):
    """A minimal S-expression reader for KiCad netlists: nested lists of strings."""
    tokens = re.findall(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()"]+', text)
    stack, cur = [], []
    for tok in tokens:
        if tok == "(":
            stack.append(cur)
            cur = []
        elif tok == ")":
            done, cur = cur, stack.pop()
            cur.append(done)
        else:
            cur.append(tok[1:-1] if tok.startswith('"') else tok)
    return cur[0] if cur else []


def _field(node, key):
    for item in node[1:]:
        if isinstance(item, list) and item and item[0] == key:
            return item[1] if len(item) > 1 else None
    return None


class Netlist:
    """Components (ref -> value), the parts marked DNP, and nets (bare net name -> {(ref, pin)}) of a KiCad 'E'
    netlist."""

    def __init__(self, path):
        with open(path, encoding="utf-8") as f:
            tree = _sexpr(f.read())
        self.values, self.nets, self.pins, self.dnp = {}, {}, {}, set()
        for sec in tree[1:]:
            if not isinstance(sec, list):
                continue
            if sec[0] == "components":
                for comp in sec[1:]:
                    ref = _field(comp, "ref")
                    self.values[ref] = _field(comp, "value")
                    # KiCad 10 writes `(property (name "dnp"))` for a symbol marked do-not-populate: the part is in
                    # the netlist but not in the BOM or the CPL, so it is not on the assembled board
                    if any(isinstance(p, list) and p and p[0] == "property" and _field(p, "name") == "dnp"
                           for p in comp[1:]):
                        self.dnp.add(ref)
            elif sec[0] == "nets":
                for net in sec[1:]:
                    name = _field(net, "name").split("/")[-1]
                    nodes = set()
                    for item in net[1:]:
                        if isinstance(item, list) and item[0] == "node":
                            ref, pin = _field(item, "ref"), _field(item, "pin")
                            nodes.add((ref, pin))
                            self.pins.setdefault(ref, {})[pin] = name
                    self.nets.setdefault(name, set()).update(nodes)

    def two_pin(self, prefix, net_a, net_b):
        """Refs of the fitted two-pin parts (R..., C...) whose pins are on net_a and net_b. A part marked DNP is not
        on the assembled board, so it is never returned: a bench value or a contract check that finds only a DNP
        part finds nothing."""
        out = []
        for ref, pins in self.pins.items():
            if not ref.startswith(prefix) or len(pins) != 2 or ref in self.dnp:
                continue
            if set(pins.values()) == {net_a, net_b} or (net_a == net_b and list(pins.values()) == [net_a] * 2):
                out.append(ref)
        return sorted(out)

    def value(self, ref):
        return parse_value(self.values[ref])


_NETLIST = None


def netlist():
    """The motherboard netlist if it has been generated, else None."""
    global _NETLIST
    if _NETLIST is None and os.path.exists(MB_NETLIST):
        _NETLIST = Netlist(MB_NETLIST)
    return _NETLIST


def captured(key, prefix, net_a, net_b, default, combine="one"):
    """A part value from the netlist (the part between net_a and net_b), or `default` (as captured 2026-11-27).

    combine='one' expects exactly one part; 'sum' adds all of them (parallel capacitors)."""
    nl = netlist()
    if nl is not None:
        refs = nl.two_pin(prefix, net_a, net_b)
        vals = [nl.value(r) for r in refs]
        if refs and all(v is not None for v in vals) and (combine == "sum" or len(refs) == 1):
            src = f" in {MB_NETLIST}" if os.environ.get("KBDSIM_NETLIST") else ""
            _note(key, f"netlist {'+'.join(refs)} ({net_a}-{net_b}){src}")
            return sum(vals) if combine == "sum" else vals[0]
    _note(key, f"default {default:g} (capture of 2026-11-27; not found in the netlist)")
    return default


# ---------------------------------------------------------------------------------------------------- SPEC
def spec_coupon_bulk():
    """SPEC §4.9's bulk-capacitance rule: (+3V3 max, +5V max, S5 +5V max) in F, read from SPEC.md's text."""
    default = (47e-6, 100e-6, 470e-6)
    try:
        with open(SPEC_MD, encoding="utf-8") as f:
            text = f.read()
        m = re.search(r"at most (\d+(?:\.\d+)?) µF on \+3V3 and (\d+(?:\.\d+)?) µF on \+5V \(S5: (\d+(?:\.\d+)?) µF\)",
                      text)
        if m:
            _note("coupon_bulk", "SPEC.md §4.9 text")
            return tuple(float(x) * 1e-6 for x in m.groups())
    except OSError:
        pass
    _note("coupon_bulk", "default 47/100/470 uF (SPEC §4.9 as read 2026-11-27; pattern not found)")
    return default


def _spec_text():
    """SPEC.md with its whitespace collapsed (so a phrase that wraps across lines still matches), or ''."""
    try:
        with open(SPEC_MD, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def spec_adc_smp():
    """SPEC §6.2's working-point ADC sampling time in cycles ("t_s = 12 cycles (300 ns ..."), read from SPEC.md, so
    that a change of the working point reaches the lane tests (and an xfail that it closes turns into an XPASS)."""
    m = re.search(r"Working point used below:.*?t_s = (\d+) cycles", " ".join(_spec_text().split()))
    if m:
        _note("adc_smp", "SPEC.md §6.2 text (working point)")
        return int(m.group(1))
    _note("adc_smp", "default 12 cycles (SPEC §6.2 as read 2026-11-27; pattern not found)")
    return 12


def spec_keys_tables():
    """SPEC §6.3's keys-per-slot figures, read from SPEC.md: {'one_slot': {t_settle_us: keys}, 'lockstep': {...},
    '1k': {...}, '1k_391': {...}}. A table that cannot be found is missing from the dict (the test then fails and
    names it, so a reworded SPEC is re-checked rather than silently skipped)."""
    raw = _spec_text()
    out = {}
    one = {}
    for m in re.finditer(r"^\| (\d+) µs[^|\n]*\| [\d.]+ µs \| [^|\n]*\| (\d+) \|", raw, re.M):
        one[int(m.group(1))] = int(m.group(2))
    if one:
        out["one_slot"] = one
    text = " ".join(raw.split())
    five = (1, 5, 10, 25, 50)
    for key, pat in (("lockstep", r"giving ([\d /]+) keys per slot for the 1 / 5 / 10 / 25 / 50 µs rows"),
                     ("1k", r"cuts the one-slot table to ([\d /]+) keys \(the same five rows\)"),
                     ("1k_391", r"That leaves \*\*([\d /]+) keys\*\* for the five rows")):
        m = re.search(pat, text)
        if m:
            vals = [int(v) for v in m.group(1).split("/")]
            if len(vals) == len(five):
                out[key] = dict(zip(five, vals))
    _note("spec_keys", f"SPEC.md §6.3 text ({', '.join(sorted(out)) or 'nothing found'})")
    return out


# ---------------------------------------------------------------------------------------------------- datasheets
LSB14 = 3.3 / 2 ** 14        # 14-bit LSB at VREF+ = VDDA = 3.3 V (SPEC §3.7: VREF+ tied to VDDA)

ADC = {
    # STM32U5Axxx datasheet DS13543 Rev 2 (July 2023), Table 97 (ADC12) and Table 98, read from the copy JLC hosts
    # for C22455480.
    "C_ADC": 5e-12,          # Table 97, CADC "Internal sample-and-hold capacitor", typ 5 pF
    "C_IO": 5e-12,           # Table 87, CIO "I/O pin capacitance", typ 5 pF
    # Table 87, Ilkg max at VIN <= max(VDDxxx): 150 nA for plain FT_xx pins, 300 nA for FT_t, 500 nA for TT_xx.
    # Four lanes sit on TT pins (Table 27: PA3 TT_hav = S2_AN3, PA4 TT_ha = S3_AN0, PA5 TT_a = S3_AN1, PB0 TT_ha =
    # S4_AN2), so the worst lane leaks up to 500 nA; FT_t lanes (PA0, PA1, PB2, PC5) up to 300 nA.
    "I_LKG": 500e-9,
    "I_LKG_FT_T": 300e-9,
    "f_ADC": 40e6,           # SPEC §6.2 working point: HCLK 160 MHz / 4
    "N_conv": 17,            # Table 97: tCONV = ts + N + 3 cycles; N = 14
    "t_LATR_cycles": 13,     # Table 97: trigger latency 13 cycles at PRESC = 2 (/4)
    "SMP": (5, 6, 12, 20, 36, 68, 391, 814),   # SPEC §6.2 / RM0456 §33.4.13 sampling-time steps (cycles)
    # DS13543 gives no value for RADC (Figure 38 names it). adc_brackets() derives the sampling network from Table 98.
    "C_ADC_T98FIT": 14e-12,
    "R_ADC_FAST": 1.4e3,     # the 'fast' bracket's switch: 7 ns with 5 pF. Not consistent with Table 98 (see below)
}

# DS13543 Rev 2 Table 98, "Maximum RAIN for 14-bit ADC12", values without an external capacitor: (R_AIN, ns).
TABLE98 = {
    14: [(47, 142), (68, 145), (100, 170)],
    12: [(47, 135), (68, 135), (100, 140), (150, 145), (220, 150), (330, 155), (470, 180)],
    10: [(47, 128), (68, 130), (100, 132), (150, 134), (220, 140), (330, 146), (470, 160), (680, 176), (1000, 200),
         (1500, 240), (2200, 320)],
    8: [(47, 123), (68, 124), (100, 125), (150, 128), (220, 130), (330, 137), (470, 140), (680, 157), (1000, 178),
        (1500, 204), (2200, 250), (3300, 313), (4700, 400), (6800, 546), (10000, 830)],
}


def adc_table98_fit(resolutions=(8, 10, 12), tol_lsb=2):
    """Fit t_s = (R_AIN + R0) * C * ln(2^N / tol) to Table 98 per resolution. Returns {N: (C, R0)}."""
    import numpy as np
    out = {}
    for n in resolutions:
        r = np.array([a for a, _ in TABLE98[n]], float)
        t = np.array([b for _, b in TABLE98[n]], float) * 1e-9
        slope, icpt = np.polyfit(r, t, 1)
        k = np.log(2 ** n / tol_lsb)
        out[n] = (slope / k, icpt / slope)
    return out


def adc_brackets():
    """The ADC's sampling network, {name: (R_ADC, C_ADC, note)}. DS13543 gives C_ADC (5 pF, Table 97) and no R_ADC.

    Table 98's rows fix two things for a single-RC reading t_s = (R_AIN + R0) x C x ln(2^N / 2): the slope against
    R_AIN gives C (13-14 pF: more than C_ADC, so it lumps the pad and switch capacitances), and the intercept gives
    the network's own time constant tau0 = R0 x C, 17-23 ns across the 8-, 10- and 12-bit rows. With a 1 nF lane
    capacitor the pad capacitance no longer matters, but tau0 still limits how fast C_ADC recovers its share of the
    kickback. So:

    * 'T97'    C_ADC 5 pF (Table 97) behind R_ADC = tau0_max / 5 pF (about 4.5 kOhm): Table 97's capacitor at the
               slowest internal time constant Table 98 supports. The reference bracket for pass/fail.
    * 'T98fit' 14 pF behind tau0_max / 14 pF (about 1.6 kOhm): all the fitted capacitance kicks back. Upper bound.
    * 'fast'   5 pF behind 1.4 kOhm (tau 7 ns): the switch adds almost nothing, which is what SPEC §6.3's
               arithmetic assumes. It does not reproduce Table 98 (it would allow 8 bits at 47 Ohm in about 35 ns
               where the table asks 123 ns); it is kept only to show where SPEC's 0.14 LSB comes from.
    """
    fit = adc_table98_fit()
    tau0 = float(max(c * r0 for c, r0 in fit.values()))
    c97, c98 = ADC["C_ADC"], ADC["C_ADC_T98FIT"]
    return {
        "T97": (tau0 / c97, c97, f"C_ADC 5 pF (Table 97), R_ADC {tau0 / c97 / 1e3:.1f} kOhm (Table 98 tau0 "
                                 f"{tau0 * 1e9:.1f} ns)"),
        "T98fit": (tau0 / c98, c98, f"14 pF, {tau0 / c98 / 1e3:.2f} kOhm (Table 98 single-RC fit)"),
        "fast": (ADC["R_ADC_FAST"], c97, "5 pF, 1.4 kOhm (SPEC's assumption; not consistent with Table 98)"),
    }


TMAG5253 = {
    # TI TMAG5253 datasheet SBASAI5E (May 2023, revised April 2026), SHA-256 e3ddc027...
    "R_OUT": 1.27,           # §6.5 ROUT "DC output resistance", EN > VIH, typ 1.27 Ohm
    "I_O": 1e-3,             # §6.3 Recommended Operating Conditions: IO "Output continuous current" -1 to 1 mA
    "C_LOAD_MAX": 1e-9,      # §6.3 CLoad "Load capacitance on OUT pin" max 1 nF
    "V_LIN": (0.2, 3.1),     # linear range 0.2 V to VCC - 0.2 V at 3.3 V (SPEC §6.3 quoting §6.1-6.5)
    # Not given: a short-circuit or peak output current. The bench brackets it: unlimited, and clamped at +/-1 mA.
}

TPS2553 = {
    # TI TPS2552/TPS2553 datasheet SLVS841G (November 2008, revised October 2026), §6.5 Electrical Characteristics
    "R_ON": (0.085, 0.135),  # rDS(on) DBV package: 85 mOhm typ (25 C), 135 mOhm max (-40 to 125 C)
    "t_r_2v5": (0.7e-3, 1.0e-3),     # tr output rise time, VIN 2.5 V, CL 1 uF, RL 100 Ohm: typ, max (no min given)
    "t_r_6v5": (1.1e-3, 1.5e-3),     # tr at VIN 6.5 V: typ, max
    "t_IOS": 2e-6,           # response time to short circuit, typ
    "deglitch": (3e-3, 7.5e-3, 11e-3),  # FAULT deglitch, overcurrent: min, typ, max
}

TPS25947 = {
    # TI TPS25947xx datasheet SLVSFC9C (October 2020, revised May 2026). U2 and U5 are TPS259474L (circuit breaker,
    # latch-off): §4 Device Comparison Table; §7.3.5.2.
    "R_ON": (0.0283, 0.045),     # §6.5 RON: 28.2 mOhm typ at 12 V and 3 A (the front page says 28.3); 45 mOhm max
    "K_ILM": 3334.0,             # §7.3.5.2 Eq. 5: R_ILM = 3334 / I_LIM
    # §6.5 ILIM rows: (R_ILM, min, typ, max) A. The spread at R_ILM between rows is interpolated (SPEC §3.1).
    "ILIM_ROWS": [(6650, 0.425, 0.500, 0.575), (3320, 0.850, 1.007, 1.150), (1650, 1.800, 2.028, 2.200),
                  (750, 3.960, 4.452, 4.840), (549, 5.400, 6.068, 6.600)],
    "ISC_GAIN": 2.01,            # §6.5 ISCGain "Scalable Fast Trip Threshold (ISC) : ILIM Ratio" typ 201 %
    "t_SC": 500e-9,              # §6.6 tSC scalable fast-trip response time, typ
    "t_CB": 2e-6,                # §6.6 tCB circuit-breaker response time after ITIMER expiry, typ
    "V_INT": (2.3, 2.57, 2.72),  # §6.5 ITIMER internal pull-up voltage
    "R_ITIMER": 15e3,            # §6.5 ITIMER internal pull-up resistance, typ
    "I_ITIMER": (1.2e-6, 1.8e-6, 2.5e-6),     # §6.5 ITIMER discharge current while IOUT > ILIM
    "dV_ITIMER": (1.286, 1.51, 1.741),        # §6.5 ITIMER discharge differential voltage threshold
    "I_dVdt": (0.81e-6, 2.21e-6, 3.82e-6),    # §6.5 dVdt pin charging current
    "K_dVdt": 2000.0,            # §7.3.5.1 Eq. 4: C_dVdt [pF] = 2000 / SR [V/ms] (at the typical I_dVdt)
    "V_UVLO_R": (1.183, 1.20, 1.223),         # §6.5 EN/UVLO rising
    "V_UVLO_F": (1.076, 1.09, 1.116),         # §6.5 EN/UVLO falling (PGTH has the same two thresholds)
}

AP2112K = {
    # Diodes AP2112 datasheet DS39724 Rev. 2-2, AP2112-3.3 Electrical Characteristics (VIN 4.3 V)
    "V_OUT": 3.3,
    "V_DROP": {0.010: (0.005, 0.008), 0.300: (0.125, 0.200), 0.600: (0.250, 0.400)},   # I: (typ, max) V
    "I_SHORT": 0.050,        # Short Current Limit at VOUT = 0 V, typ (a foldback limit)
}

LDL1117 = {
    # ST LDL1117 datasheet DocID030319 Rev 3: Electrical Characteristics and Figure 27 (load transient)
    "V_OUT": 3.3,
    "V_DROP_MAX": 0.600,     # at 1.2 A, max
    "I_SC_MIN": 1.5,         # ISC "Output current" min 1.5 A
    "LOAD_REG": 0.005,       # 5 mV typ, 10 mA to 1.2 A
    # Figure 27 (typical, VIN 3.5 V, COUT 4.7 uF, 10 mA -> 1.2 A in 5 us): VOUT dips about 0.75 div at 100 mV/div,
    # about 75 mV, read by eye from the plot. The bench's LDO model is fitted to that one figure.
    "FIG27_DIP": 0.075,
}

DRV8316 = {
    # TI DRV8316 datasheet SLVSF16B (January 2021, revised April 2022), §7.3 and the protection table
    "VM_MIN": 4.5,                       # Recommended Operating Conditions, VVM min
    "UVLO_FALL": (4.1, 4.2, 4.3),        # VUVLO, VM falling: min, typ, max
}

TUSB320 = {
    # TI TUSB320LAI SLLSEQ8D: VBUS_THR "VBUS threshold range" 2.95 / 3.3 / 3.8 V (the VBUS_DET detect threshold)
    "VBUS_THR": (2.95, 3.3, 3.8),
}

USB = {
    # USB 2.0 Specification (usb_20.pdf in usb.org's usb_20_20250603.zip), §7.2.2 Voltage Drop Budget:
    # "The voltage supplied by high-powered hub ports is 4.75 V to 5.25 V"; VBUSD 125 mV and VGNDD 125 mV per cable.
    "V_SRC_MIN": 4.75,
    "V_SRC_NOM": 5.0,
    # USB Type-C Cable and Connector Specification Release 2.0 (August 2019), §4.4.1 IR Drop: "The maximum
    # allowable cable IR drop for ground ... shall be 250 mV and for VBUS shall be 500 mV through the cable to the
    # cable's maximum rated VBUS current capacity", including the mated contacts. For a 3 A cable: 167 + 83 mOhm.
    "R_CABLE_TYPEC_3A": 0.5 / 3.0 + 0.25 / 3.0,
    "R_CABLE_USB2_500MA": 0.125 / 0.5 + 0.125 / 0.5,   # USB 2.0 §7.2.2 at 500 mA: 0.5 Ohm round trip
    # Type-C R2.0 Table 4-3: vSinkDisconnect max 3.67 V (VBUS at 5 V)
    "V_SINK_DISCONNECT_MAX": 3.67,
}

# Assumptions with no document behind them, named so the README can list them.
ASSUMED = {
    "R_contact": 0.020,      # Ohm per 2.54 mm socket contact (the socket's datasheet gives no figure here)
    "L_cable": 1.0e-6,       # H, cable loop inductance for about 1 m of USB cable
    "C_coupon_lane": 190e-12,   # F on a lane's coupon side: SPEC §4.3's "about 870 pF in all" minus 680 pF
    "ESR_bulk_ceramic": 0.005,  # Ohm
    "ESR_bulk_s5": 0.030,    # Ohm, the haptics coupon's 470 uF (a polymer capacitor class figure)
    "base_load": 0.045,      # A on VSYS with no slot powered (SPEC §3.2 estimate)
}


def tps25947_ilim(r_ilm, r_tol=0.0):
    """(min, typ, max) trip current of a TPS25947 at R_ILM. typ = Eq. 5; min/max apply the interpolated relative
    spread of §6.5's rows; r_tol widens for the resistor (min at R(1 + r_tol), max at R(1 - r_tol))."""
    rows = sorted(TPS25947["ILIM_ROWS"])
    rel = []
    for r, lo, ty, hi in rows:
        rel.append((r, lo / ty, hi / ty))

    def interp(r):
        if r <= rel[0][0]:
            return rel[0][1:]
        for (r0, a0, b0), (r1, a1, b1) in zip(rel, rel[1:]):
            if r0 <= r <= r1:
                f = (r - r0) / (r1 - r0)
                return a0 + f * (a1 - a0), b0 + f * (b1 - b0)
        return rel[-1][1:]

    k = TPS25947["K_ILM"]
    lo_rel, _ = interp(r_ilm * (1 + r_tol))
    _, hi_rel = interp(r_ilm * (1 - r_tol))
    return (k / (r_ilm * (1 + r_tol)) * lo_rel, k / r_ilm, k / (r_ilm * (1 - r_tol)) * hi_rel)


def tps2553_ios(r_ilim_kohm):
    """(min, typ, max) I_OS in A from SLVS841G Eqs. 1-3, without the resistor's tolerance."""
    return (25230 / r_ilim_kohm ** 1.016 / 1e3, 23950 / r_ilim_kohm ** 0.977 / 1e3, 22980 / r_ilim_kohm ** 0.94 / 1e3)


def tps2553_rise(vin):
    """(typ, max) 10-90 % rise time at VIN, interpolated between SLVS841G's 2.5 V and 6.5 V rows."""
    f = (vin - 2.5) / 4.0
    lo, hi = TPS2553["t_r_2v5"], TPS2553["t_r_6v5"]
    return tuple(a + f * (b - a) for a, b in zip(lo, hi))


def itimer_window(c_itimer):
    """(min, typ, max) circuit-breaker blanking time, Eq. 6, from the datasheet's dV and I spreads (C exact)."""
    dv, i = TPS25947["dV_ITIMER"], TPS25947["I_ITIMER"]
    return dv[0] * c_itimer / i[2], dv[1] * c_itimer / i[1], dv[2] * c_itimer / i[0]


def dvdt_slew(c_dvdt):
    """(min, typ, max) output slew rate in V/s: Eq. 4 at the typical I_dVdt, scaled by I_dVdt's spread."""
    i = TPS25947["I_dVdt"]
    sr_typ = TPS25947["K_dVdt"] / (c_dvdt * 1e12) * 1e3          # V/ms -> V/s
    return sr_typ * i[0] / i[1], sr_typ, sr_typ * i[2] / i[1]


# ---------------------------------------------------------------------------------------------------- the design
def board():
    """Every design value a bench uses, from nets.py, the netlist or the capture defaults."""
    nets = load_nets()
    d = {}
    # lane RC (SPEC §4.3): the S1 AN0 lane stands for all twenty
    d["R_lane"] = captured("R_lane", "R", "S1_AN0", "S1_AN0_ADC", 47.0)
    d["C_lane"] = captured("C_lane", "C", "S1_AN0_ADC", "GND", 1e-9)
    d["C_lane_alt"] = 680e-12
    _note("C_lane_alt", "SPEC §4.3 alternative (680 pF C0G)")
    # slot switches: trip points from the contract
    d["trip_3v3"] = nets.SWITCH_TRIP["+3V3_S1"]
    d["trip_5v"] = nets.SWITCH_TRIP["+5V_S1"]
    d["trip_s5"] = nets.SWITCH_TRIP["+5V_S5"]
    d["trip_vsys"] = nets.SWITCH_TRIP["VSYS"]
    _note("trips", "nets.SWITCH_TRIP")
    rails = nets.INA226_RAILS
    d["shunt_3v3"], d["rule_3v3"] = rails[0x44][1], rails[0x44][2]
    d["shunt_5v"], d["rule_5v"] = rails[0x49][1], rails[0x49][2]
    d["shunt_s5"], d["rule_s5"] = rails[0x4D][1], rails[0x4D][2]
    d["shunt_vsys"] = rails[0x40][1]
    d["ina_fs"] = nets.INA226_FULL_SCALE_V
    _note("shunts", "nets.INA226_RAILS")
    d["vsys_budget_max"] = nets.VSYS_BUDGET_MAX
    _note("vsys_budget_max", "nets.VSYS_BUDGET_MAX")
    d["bulk_3v3"], d["bulk_5v"], d["bulk_s5"] = spec_coupon_bulk()
    # TPS2553 R_ILIM (for the resistor-tolerance view; the contract's trips already include 1 %)
    d["r_ilim_3v3"] = captured("r_ilim_3v3", "R", "S1_ILIM3", "GND", 90.9e3)
    d["r_ilim_5v"] = captured("r_ilim_5v", "R", "S1_ILIM5", "GND", 45.3e3)
    # S5 breaker U5
    d["s5_r_ilm"] = captured("s5_r_ilm", "R", "S5_ILM", "GND", 1.47e3)
    d["s5_c_itimer"] = captured("s5_c_itimer", "C", "S5_ITIMER", "GND", 2.2e-9)
    d["s5_c_dvdt"] = captured("s5_c_dvdt", "C", "S5_DVDT", "GND", 2.2e-9)
    d["s5_socket_c"] = captured("s5_socket_c", "C", "+5V_S5", "GND", 10e-6, combine="sum")
    d["s3v3_socket_c"] = captured("s3v3_socket_c", "C", "+3V3_S1", "GND", 1e-6, combine="sum")
    d["s5v_socket_c"] = captured("s5v_socket_c", "C", "+5V_S1", "GND", 1e-6, combine="sum")
    # input breaker U2
    d["u2_r_ilm"] = captured("u2_r_ilm", "R", "U2_ILM", "GND", 1.0e3)
    d["u2_c_itimer"] = captured("u2_c_itimer", "C", "U2_ITIMER", "GND", 2.2e-9)
    d["u2_c_dvdt"] = captured("u2_c_dvdt", "C", "U2_DVDT", "GND", 2.2e-9)
    d["uvlo_top"] = captured("uvlo_top", "R", "VBUS", "U2_UVLO", 100e3)
    d["uvlo_bot"] = captured("uvlo_bot", "R", "U2_UVLO", "GND", 39e3)
    d["pgth_top"] = captured("pgth_top", "R", "VSYS_IN", "U2_PGTH", 100e3)
    d["pgth_bot"] = captured("pgth_bot", "R", "U2_PGTH", "GND", 39e3)
    d["c_vbus"] = captured("c_vbus", "C", "VBUS", "GND", 4.7e-6, combine="sum")
    d["c_vsys"] = captured("c_vsys", "C", "VSYS", "GND", 34.4e-6, combine="sum")
    d["c_3v3"] = captured("c_3v3", "C", "+3V3", "GND", 12e-6, combine="sum")
    d["c_3v3_mcu"] = captured("c_3v3_mcu", "C", "+3V3_MCU", "GND", 10.6e-6, combine="sum")
    d["c_3v3_slot"] = captured("c_3v3_slot", "C", "+3V3_SLOT", "GND", 5.2e-6, combine="sum")
    d["c_3v3a"] = captured("c_3v3a", "C", "+3V3A", "GND", 2.2e-6, combine="sum")
    return d


# The capture's set resistors are 1 % parts (sheets/motherboard_parts.py: Uniroyal 0402WGF..., Yageo AC0402FR...).
# SPEC §3.1 widens the TPS2553 trips for it; the same tolerance moves U2's UVLO and PG thresholds.
R_TOL = 0.01


def divider_k(top, bot, r_tol=0.0):
    """(min, nom, max) of (top + bot) / bot, the factor from a pin threshold to the voltage it watches, with each
    resistor off by r_tol (max: top high and bottom low)."""
    lo = 1 + top * (1 - r_tol) / (bot * (1 + r_tol))
    hi = 1 + top * (1 + r_tol) / (bot * (1 - r_tol))
    return lo, 1 + top / bot, hi


def lanes_all():
    """{(slot, lane): (R ohm, C F)} for all twenty lanes in the netlist; None for a part that is not found.
    The benches simulate S1 AN0; this lets a test check that the other nineteen are the same."""
    nl = netlist()
    out = {}
    if nl is None:
        return out
    for s in range(1, 6):
        for k in range(4):
            rr = nl.two_pin("R", f"S{s}_AN{k}", f"S{s}_AN{k}_ADC")
            cc = nl.two_pin("C", f"S{s}_AN{k}_ADC", "GND")
            out[(s, k)] = (nl.value(rr[0]) if len(rr) == 1 else None, nl.value(cc[0]) if len(cc) == 1 else None)
    return out


def slot_switch_parts():
    """{slot: {'r_ilim3', 'r_ilim5', 'c_3v3', 'c_5v'}} from the netlist (S5 has no TPS2553 on 5 V: its r_ilim5 is
    None). The benches simulate S1's; a test checks the others against it."""
    nl = netlist()
    out = {}
    if nl is None:
        return out
    for s in range(1, 6):
        def one(prefix, a, b, combine="one"):
            refs = nl.two_pin(prefix, a, b)
            if not refs:
                return None
            vals = [nl.value(r) for r in refs]
            return sum(vals) if combine == "sum" else (vals[0] if len(vals) == 1 else None)
        out[s] = {"r_ilim3": one("R", f"S{s}_ILIM3", "GND"), "r_ilim5": one("R", f"S{s}_ILIM5", "GND"),
                  "c_3v3": one("C", f"+3V3_S{s}", "GND", "sum"), "c_5v": one("C", f"+5V_S{s}", "GND", "sum")}
    return out


def tps2553_trip_from_r(r_ohm, r_tol=0.01):
    """(min, typ, max) I_OS widened for the resistor tolerance (min at R + tol, max at R - tol), as SPEC §3.1."""
    lo = tps2553_ios(r_ohm * (1 + r_tol) / 1e3)[0]
    ty = tps2553_ios(r_ohm / 1e3)[1]
    hi = tps2553_ios(r_ohm * (1 - r_tol) / 1e3)[2]
    return lo, ty, hi


def vdda_leg_captured(net):
    """(R ohm, C F) of the +3V3A damping leg in the netlist: one resistor from +3V3A to `net` and one capacitor from
    `net` to GND (SPEC §3.7, nets.VDDA_DAMPING). None if the netlist has no such pair; no netlist: None as well."""
    nl = netlist()
    if nl is None:
        return None
    rr, cc = nl.two_pin("R", "+3V3A", net), nl.two_pin("C", net, "GND")
    if len(rr) != 1 or len(cc) != 1:
        return None
    _note("vdda_leg", f"netlist {rr[0]}+{cc[0]} (+3V3A-{net}-GND)")
    return nl.value(rr[0]), nl.value(cc[0])


def netlist_has_nets(names):
    """True if every named net is in the netlist (False without a netlist)."""
    nl = netlist()
    return nl is not None and all(n in nl.nets for n in names)


def predates_decisions_2026_11_27():
    """True when the motherboard netlist was captured before the owner's decisions of 2026-11-27 (or there is none):
    it has none of D3's socket-side nets (nets.SLOT_SERIES), the marker that the recapture carrying D2-D5 has
    happened. Any one of them present counts as recaptured, so a later capture that loses some is not excused.
    Tests that compare the capture with those decisions are expected failures only before it; once the netlist
    carries D3, a capture that disagrees with D4 (the PGTH divider, the +3V3A damping leg) is a plain failure."""
    nets = load_nets()
    nl = netlist()
    if nl is None or not hasattr(nets, "SLOT_SERIES"):
        return True
    return not any(sock in nl.nets for n in nets.SLOTS for sock, _ohms in nets.SLOT_SERIES[n].values())
