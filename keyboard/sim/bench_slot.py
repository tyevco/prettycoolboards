"""Bench 2: slot power (SPEC §3.1, §3.5, §3.6, §4.9).

A. A TPS2553 slot switch enabling a coupon (3.3 V from the slot LDO, 5 V from VSYS): the soft start, the
   constant-current limit, R_DS(on), the INA226 shunt, the meter jumper and socket contacts, the motherboard's
   socket capacitor, and the coupon's bulk capacitance at SPEC §4.9's maximum with three kinds of load. Question:
   does enabling a coupon that keeps the rules keep the switch out of current limit for longer than its FAULT
   deglitch (3 ms minimum, SLVS841G)? On the 3.3 V rail the bench also records the dip on +3V3_SLOT and on +3V3A
   (VDDA and VREF+), which the other slots' lanes are converted against.

B. The haptics slot S5: the full power path (powerpath.py) with U5, a TPS259474L circuit breaker, and a motor
   current profile (concept §2.3 / §8: "Strong detents peak at about 0.5-1 A on 5 V (estimate)"; the peak width
   is not known, SPEC §3.6). Questions: the droop at the coupon against the DRV8316's supply limits, whether U5's
   circuit-breaker timer or fast trip fires, and what a 140 us INA226 conversion would report of a peak.

What it can catch: a rule, trip point, capacitor or timer value that puts a switch into FAULT or a breaker into
latch-off during a normal enable or a motor peak, given these models. What it cannot: thermal shutdown (no
thermal model), the TPS2553's real soft-start shape (the datasheet gives a rise time, not a curve), the motor's
real current (no motor is chosen), layout resistance and inductance, the coupon's own regulators.
"""

import numpy as np

import design
import powermodels as pm
import powerpath as pp
import spice


# ------------------------------------------------------------------------------------------------ A. TPS2553
def bulk_limit(rail, i_startup, t_deglitch=None):
    """The largest coupon bulk capacitance (F) that a TPS2553 at its minimum I_OS charges within the minimum FAULT
    deglitch while the coupon already draws i_startup (A): C = t_deglitch x (I_OS min - i_startup) / V_rail.

    A rule compiler v0 can check (SPEC §4.9 states only a capacitance). It ignores the soft start, which can only
    lower the charging current, and assumes a load that draws i_startup from about 1 V up, the worst case."""
    b = design.board()
    t_deglitch = design.TPS2553["deglitch"][0] if t_deglitch is None else t_deglitch
    i_os, v = (b["trip_3v3"][0], 3.3) if rail == "3v3" else (b["trip_5v"][0], 5.0)
    return max(0.0, t_deglitch * (i_os - i_startup) / v)


def tps2553_enable(rail="3v3", load="none", ios="min", soft="none", c_bulk=None, r_on="max", t_stop=30e-3,
                   l_ferrite=0.5e-6, other_slot_load=0.0, i_os_a=None, i_load=None):
    """Enable one slot rail into a coupon. Returns a dict of results and the waveforms.

    i_os_a overrides the limit in A (the vendor cross-check); i_load overrides the load current (default: the
    rail's coupon rule)."""
    b = design.board()
    t_en = 0.5e-3
    if rail == "3v3":
        v_rail, trip, shunt, rule = 3.3, b["trip_3v3"], b["shunt_3v3"], b["rule_3v3"]
        c_bulk = b["bulk_3v3"] if c_bulk is None else c_bulk
        c_sock, n_pins = b["s3v3_socket_c"], 2
    else:
        v_rail, trip, shunt, rule = 5.0, b["trip_5v"], b["shunt_5v"], b["rule_5v"]
        c_bulk = b["bulk_5v"] if c_bulk is None else c_bulk
        c_sock, n_pins = b["s5v_socket_c"], 3
    i_os = dict(zip(("min", "typ", "max"), trip))[ios] if i_os_a is None else i_os_a
    rule = rule if i_load is None else i_load
    ron = design.TPS2553["R_ON"][0 if r_on == "typ" else 1]
    t_r = {"none": 0.0, "typ": design.tps2553_rise(v_rail)[0], "max": design.tps2553_rise(v_rail)[1]}[soft]
    rc = design.ASSUMED["R_contact"]
    lines = ["Vsys vsys0 0 5.0"]
    if rail == "3v3":
        lines += [
            pm.ldo("U4", "vsys0", "vin", 3.3, design.LDL1117["V_DROP_MAX"] / 1.2),
            pm.cap("Cslot", "vin", b["c_3v3_slot"]),
            f"Lfb vin fb {l_ferrite}",            # FB1: DC resistance 0.10 Ohm max (Murata); L an assumption
            "Rfb fb vdda 0.10",
            pm.cap("Cvdda", "vdda", b["c_3v3a"]),
            "Rvdda vdda 0 1650",                   # VDDA's ADCs, about 2 mA
        ]
        if other_slot_load:
            lines.append(f"Rother vin 0 {3.3 / other_slot_load:.6g}")
    else:
        lines += ["Rsrcv vsys0 vin 0.065", pm.cap("Cvsys", "vin", b["c_vsys"])]
    lines += [
        pm.tps2553("U", "vin", "sw", t_en, ron, i_os, t_r, v_rail),
        f"Rsh sw m {shunt}",
        f"Rjp m j {rc if rail == '3v3' else 1e-4}",       # the meter jumper's shunt (3.3 V rails only)
        pm.cap("Csock", "j", c_sock),
        "Rina j 0 830e3",                                  # the INA226's VBUS input (SBOS547): a DC path to GND
        f"Rpins j cpn {rc / n_pins:.6g}",
        pm.cap("Cbulk", "cpn", c_bulk, esr=design.ASSUMED["ESR_bulk_ceramic"]),
    ]
    if load == "r":
        lines.append(f"Rload cpn 0 {v_rail / rule:.6g}")
    elif load == "cc":
        lines.append(f"Bload cpn 0 I = {rule}*{pm.step('v(cpn)-1.0', 0.05)}")
    elif load != "none":
        raise ValueError(load)
    vectors = ["v(vin)", "v(cpn)", "i(VUm)", "v(U_ctl)", "v(sw)"] + (["v(vdda)"] if rail == "3v3" else [])
    w = spice.run("\n".join(lines), vectors, f"tran 1u {t_stop} 0 2u", options=spice.POWER_OPTIONS)
    t, i = w.scale, w["i(VUm)"]
    in_lim = i >= 0.98 * i_os
    t_lim = spice.longest_run(t, in_lim)
    v_cpn = w["v(cpn)"]
    v_fin = float(v_cpn[-1])
    c90 = spice.crossings(t, v_cpn, 0.9 * v_fin)
    res = {
        "rail": rail, "load": load, "ios": ios, "soft": soft, "i_os": i_os, "c_bulk": c_bulk, "t_lim": t_lim,
        "i_peak": float(np.max(i)), "v_final": v_fin, "t_90": (c90[0] - t_en) if c90 else None,
        "fault_min_deglitch": t_lim > design.TPS2553["deglitch"][0],
        "fault_typ_deglitch": t_lim > design.TPS2553["deglitch"][1],
        "waves": w, "t_en": t_en,
    }
    if rail == "3v3":
        pre = t < t_en
        for node, key in (("v(vin)", "slot"), ("v(vdda)", "vdda")):
            v0 = float(np.mean(w[node][pre][-20:]))
            dip = v0 - float(np.min(w[node][t >= t_en]))
            res[f"{key}_dip"] = dip
            res[f"{key}_dip_midscale_lsb"] = dip / 3.3 * 2 ** 13     # a fixed input at mid-scale, 14-bit codes
            res[f"{key}_v0"] = v0
    return res


# ------------------------------------------------------------------------------------------------ B. S5
def motor_profile(kind, t0, **kw):
    """A coupon current profile [(t, A)] starting at t0 (the rail is up by then). Every number is an assumption
    standing in for an unchosen motor, except the 0.5-1 A peaks (concept §8's estimate) and the 2 A rule (§4.9)."""
    edge = kw.get("edge", 50e-6)
    base = kw.get("base", 0.1)
    pts = [(0.0, 0.0), (t0, 0.0), (t0 + edge, base)]
    if kind == "detents":
        pk, w, period, n = kw.get("pk", 1.0), kw.get("width", 2e-3), kw.get("period", 10e-3), kw.get("n", 4)
        for k in range(n):
            a = t0 + 1e-3 + k * period
            pts += [(a, base), (a + edge, pk), (a + w, pk), (a + w + edge, base)]
        pts.append((t0 + 1e-3 + n * period + 5e-3, base))
    elif kind == "steady":
        a = t0 + 1e-3
        pts += [(a, base), (a + edge, kw["amp"]), (a + kw.get("width", 20e-3), kw["amp"])]
    elif kind == "burst":
        a = t0 + 1e-3
        pts += [(a, base), (a + edge, kw["amp"]), (a + kw["width"], kw["amp"]), (a + kw["width"] + edge, base),
                (a + kw["width"] + 10e-3, base)]
    elif kind == "short":
        a = t0 + 1e-3
        pts += [(a, base), (a + 1e-6, kw.get("amp", 10.0)), (a + 2e-3, kw.get("amp", 10.0))]
    else:
        raise ValueError(kind)
    return pts


def ina226_view(t, i, t_conv=140e-6):
    """Block averages of i over consecutive t_conv windows: a stand-in for the INA226's fastest shunt-only
    conversion (its delta-sigma filter is not a boxcar; this shows only what averaging over 140 us does)."""
    edges = np.arange(t[0], t[-1], t_conv)
    out_t, out_i = [], []
    for a, c in zip(edges[:-1], edges[1:]):
        m = (t >= a) & (t < c)
        if np.count_nonzero(m) > 1:
            out_t.append((a + c) / 2)
            out_i.append(np.trapezoid(i[m], t[m]) / (t[m][-1] - t[m][0]))
    return np.array(out_t), np.array(out_i)


def s5_case(profile="detents", corner="typ", ilim="typ", itimer="typ", v_src=5.0, r_cable=0.1, other_load=0.0,
            t_stop=None, **kw):
    """S5 through the whole power path. other_load: the rest of VSYS's load (other slots), A, from 20 ms."""
    t_en, t_motor = 8e-3, 22e-3
    prof = motor_profile(profile, t_motor, **kw)
    t_stop = t_stop or (prof[-1][0] + 5e-3)
    s5 = dict(t_en=t_en, motor=prof, ilim=ilim, i_dvdt="typ")
    xl = [(0, 0), (20e-3, 0), (20.1e-3, other_load), (1, other_load)] if other_load else None
    net, vec = pp.build(v_src=v_src, r_cable=r_cable, corner=corner, i_dvdt="max", vsys_load=xl, s5=s5)
    if itimer != "typ":
        net = _itimer_corner(net, itimer)
    w = spice.run(net, vec, f"tran 1u {t_stop} 0 4u", options=spice.POWER_OPTIONS)
    t = w.scale
    m = t >= t_motor
    vc = w["v(cpn)"] - w["v(cpng)"]
    trip5 = spice.crossings(t, w["v(U5_trip)"], 0.5)
    trip2 = spice.crossings(t, w["v(U2_trip)"], 0.5)
    i5 = w["i(VU5m)"]
    ti, ii = ina226_view(t[m], i5[m])
    on_at_motor = bool(np.interp(t_motor, t, w["v(U2_ena)"]) > 0.5 and np.interp(t_motor, t, w["v(U5_trip)"]) < 0.5
                       and np.interp(t_motor, t, vc) > 4.0)
    uv_off = (not on_at_motor) or bool(np.min(w["v(U2_ena)"][t > 5e-3]) < 0.5)
    return {
        "profile": profile, "corner": corner, "ilim_corner": ilim, "itimer": itimer, "v_src": v_src,
        "r_cable": r_cable, "other_load": other_load,
        "v_coupon_min": float(np.min(vc[m])), "v_vsys_min": float(np.min(w["v(vsys)"][m])),
        "v_vbus_min": float(np.min(w["v(vbus)"][m])), "i_s5_max": float(np.max(i5[m])),
        "i_ina226_max": float(np.max(ii)) if len(ii) else None,
        "u5_trip_t": (trip5[0] - t_motor - 1e-3) if trip5 else None,
        "u2_trip_t": (trip2[0] - t_motor) if trip2 else None,
        "u2_uvlo_off": uv_off, "on_at_motor": on_at_motor,
        "ilim_a": pp._ilim(design.board()["s5_r_ilm"], ilim),
        "waves": w, "t_motor": t_motor, "ina": (ti, ii),
    }


def _itimer_corner(net, which):
    """Swap U5's ITIMER current and threshold for the shortest ('min') or longest ('max') blanking time."""
    t = design.TPS25947
    i_typ, dv_typ = t["I_ITIMER"][1], t["dV_ITIMER"][1]
    i_new, dv_new = (t["I_ITIMER"][2], t["dV_ITIMER"][0]) if which == "min" else (t["I_ITIMER"][0], t["dV_ITIMER"][2])
    out, done = [], set()
    for ln in net.split("\n"):
        if ln.startswith("BU5it"):
            new = ln.replace(f"-{i_typ:.6g}*", f"-{i_new:.6g}*")
            if new != ln:
                done.add("it")
            ln = new
        if ln.startswith("BU5tr"):
            v_int = t["V_INT"][1]
            new = ln.replace(f"{v_int - dv_typ}-v(U5_it)", f"{v_int - dv_new}-v(U5_it)")
            if new != ln:
                done.add("tr")
            ln = new
        out.append(ln)
    if done != {"it", "tr"}:      # a silent no-op would run the typical timer under the corner's name
        raise RuntimeError(f"ITIMER corner '{which}' did not apply (patched: {sorted(done)}); powermodels changed?")
    return "\n".join(out)


# ------------------------------------------------------------------------------------------------ summary
def run_all():
    r = {}
    b = design.board()
    for rail in ("3v3", "5v"):
        for load in ("none", "r", "cc"):
            for ios in ("min", "typ"):
                r[f"en_{rail}_{load}_{ios}_nosoft"] = tps2553_enable(rail, load, ios, "none")
            r[f"en_{rail}_{load}_min_typsoft"] = tps2553_enable(rail, load, "min", "typ")
    r["en_3v3_none_max_nosoft"] = tps2553_enable("3v3", "none", "max", "none")
    # S5
    r["s5_detents_typ"] = s5_case("detents", "typ", v_src=5.0, r_cable=0.1)
    r["s5_detents_worst"] = s5_case("detents", "worst", v_src=design.USB["V_SRC_MIN"],
                                    r_cable=design.USB["R_CABLE_TYPEC_3A"], other_load=0.0)
    r["s5_rule_ceiling_worst"] = s5_case("steady", "worst", amp=b["rule_s5"], width=20e-3,
                                         v_src=design.USB["V_SRC_MIN"], r_cable=design.USB["R_CABLE_TYPEC_3A"],
                                         other_load=b["vsys_budget_max"] - b["rule_s5"] - design.ASSUMED["base_load"])
    r["s5_rule_board_only"] = s5_case("steady", "worst", amp=b["rule_s5"], width=20e-3,
                                      v_src=design.USB["V_SRC_MIN"], r_cable=1e-3)
    r["s5_rule_ilim_min"] = s5_case("steady", "typ", ilim="min", amp=b["rule_s5"], width=20e-3)
    r["s5_rule_ilim_min_rtol"] = s5_case("steady", "typ", ilim="min_rtol", amp=b["rule_s5"], width=20e-3)
    lo, ty, hi = design.itimer_window(b["s5_c_itimer"])
    over = 2.6     # above I_LIM's maximum with the resistor's tolerance, below 2 x I_LIM's minimum
    r["s5_burst_short_min_itimer"] = s5_case("burst", "typ", itimer="min", amp=over, width=0.9 * lo)
    r["s5_burst_long_max_itimer"] = s5_case("burst", "typ", itimer="max", amp=over, width=1.2 * hi)
    r["s5_burst_long_typ"] = s5_case("burst", "typ", itimer="typ", amp=over, width=2 * hi)
    r["s5_short"] = s5_case("short", "typ", amp=10.0)
    return r
