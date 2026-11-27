"""Bench 3: the input (SPEC §3.1, §3.2, §3.5, §3.8): VBUS through a cable, the input breaker U2, VSYS.

* Start-up: VBUS applied, U2's EN/UVLO divider, its dV/dt soft start at the minimum, typical and maximum dVdt
  charging current (0.81 / 2.21 / 3.82 uA, SLVSFC9C §6.5), VSYS's bulk, and +3V3 from the AP2112K. Question: does
  +3V3, which feeds U_CC's VDD, rise within the TUSB320LAI's 25 ms (SPEC §3.8), and does the inrush stay under
  U2's I_LIM?
* The 2.8 A ceiling (SPEC §3.2, nets.VSYS_BUDGET_MAX): the whole board stepped from its base load to 2.8 A, from a
  source at USB's 4.75 V minimum (USB 2.0 §7.2.2) through a cable of 0.1, 0.25 (a 3 A Type-C cable at its IR-drop
  limit: 250 mV of ground and 500 mV of VBUS drop at 3 A, Type-C R2.0 §4.4.1) and 0.3 Ohm round trip. Questions:
  VBUS at J1 against U2's UVLO falling threshold (the capture's 100 k / 39 k divider) and against U_CC's VBUS
  detection threshold (TUSB320LAI VBUS_THR, 3.8 V max); VSYS against U2's PG falling threshold; and the droop.

What it can catch: a divider, capacitor or ceiling that turns the board off, or keeps U_CC from powering in time,
for the sources and cables named. What it cannot: a real source's output impedance and current limit, connector
heating, the TUSB320's own behaviour (no model), the AP2112K's start-up foldback (50 mA typ at VOUT = 0).
"""

import numpy as np

import design
import powerpath as pp
import spice


def thresholds(r_tol=None):
    """U2's UVLO and PG thresholds referred to VBUS / VSYS_IN through the capture's dividers: dict of (min, typ, max).

    min and max combine the pin threshold's spread with the divider's resistor tolerance (default design.R_TOL, the
    capture's 1 % parts; SPEC §3.1 widens the TPS2553 trips for the same tolerance). typ is nominal."""
    r_tol = design.R_TOL if r_tol is None else r_tol
    b = design.board()
    t = design.TPS25947
    k_uv = design.divider_k(b["uvlo_top"], b["uvlo_bot"], r_tol)
    k_pg = design.divider_k(b["pgth_top"], b["pgth_bot"], r_tol)

    def refer(pin, k):
        return pin[0] * k[0], pin[1] * k[1], pin[2] * k[2]
    return {
        "uvlo_rise": refer(t["V_UVLO_R"], k_uv),
        "uvlo_fall": refer(t["V_UVLO_F"], k_uv),
        "pg_fall": refer(t["V_UVLO_F"], k_pg),     # PGTH has the same thresholds as EN/UVLO (§6.5)
        "ucc_vbus_thr": design.TUSB320["VBUS_THR"],
        "sink_disconnect_max": design.USB["V_SINK_DISCONNECT_MAX"],
        "r_tol": r_tol,
    }


def startup(i_dvdt="typ", v_src=5.0, r_cable=0.1, t_stop=40e-3):
    net, vec = pp.build(v_src=v_src, r_cable=r_cable, i_dvdt=i_dvdt)
    w = spice.run(net, vec, f"tran 1u {t_stop} 0 5u", options=spice.POWER_OPTIONS)
    t = w.scale
    v3 = w["v(v3v3)"]

    def first(y, lvl):
        c = spice.crossings(t, y, lvl)
        return c[0] if c else None

    a, b3, c3 = first(v3, 0.33), first(v3, 3.0), first(v3, 0.99 * 3.3)
    lo, ty, hi = design.dvdt_slew(design.board()["u2_c_dvdt"])
    return {
        "i_dvdt": i_dvdt, "sr": {"min": lo, "typ": ty, "max": hi}[i_dvdt],
        "t_3v3_ramp": (b3 - a) if (a and b3) else None,          # 10 % to 3.0 V (U_CC's I2C needs VDD > 3.0 V)
        "t_3v3_ramp_99": (c3 - a) if (a and c3) else None,
        "t_ena": first(w["v(U2_ena)"], 0.5),
        "u2_on": bool(w["v(U2_ena)"][-1] > 0.5),
        "i_inrush": float(np.max(w["i(VU2m)"])), "v_vsys_final": float(w["v(vsys)"][-1]),
        "u2_tripped": bool(np.max(w["v(U2_trip)"]) > 0.5),
        "waves": w,
    }


def ceiling(v_src=None, r_cable=None, corner="worst", i_total=None, t_step=15e-3, hold=15e-3, edge=50e-6):
    """Step the board from its base load to i_total (default nets.VSYS_BUDGET_MAX) at t_step and hold."""
    b = design.board()
    v_src = design.USB["V_SRC_MIN"] if v_src is None else v_src
    r_cable = design.USB["R_CABLE_TYPEC_3A"] if r_cable is None else r_cable
    i_total = b["vsys_budget_max"] if i_total is None else i_total
    extra = i_total - design.ASSUMED["base_load"] - 0.002
    load = [(0, 0), (t_step, 0), (t_step + edge, extra), (1, extra)]
    net, vec = pp.build(v_src=v_src, r_cable=r_cable, corner=corner, i_dvdt="max", vsys_load=load)
    w = spice.run(net, vec, f"tran 1u {t_step + hold} 0 5u", options=spice.POWER_OPTIONS)
    t = w.scale
    m = t >= t_step
    th = thresholds()
    vbus = w["v(vbus)"][m]
    vsys_in = w["v(vsys_in)"][m]
    # U2 must be on when the load steps (a divider that never lets it start must not pass as 'stays on'), and an
    # EN/UVLO level below 0.5 at any time after the step counts as off (not only a crossing)
    on_at_step = bool(np.interp(t_step, t, w["v(U2_ena)"]) > 0.5 and np.interp(t_step, t, w["v(vsys)"]) > 4.0)
    off = (not on_at_step) or bool(np.min(w["v(U2_ena)"][m]) < 0.5)
    res = {
        "v_src": v_src, "r_cable": r_cable, "i_total": i_total, "corner": corner,
        "vbus_min": float(np.min(vbus)), "vbus_end": float(vbus[-1]),
        "vsys_min": float(np.min(w["v(vsys)"][m])), "vsys_end": float(w["v(vsys)"][-1]),
        "vsys_in_min": float(np.min(vsys_in)),
        "u2_on_at_step": on_at_step, "u2_uvlo_off": off, "u2_tripped": bool(np.max(w["v(U2_trip)"]) > 0.5),
        "margin_uvlo": float(np.min(vbus)) - th["uvlo_fall"][2],     # against the highest falling threshold
        "margin_ucc": float(np.min(vbus)) - th["ucc_vbus_thr"][2],
        "margin_pg": float(np.min(vsys_in)) - th["pg_fall"][2],
        "v3v3_min": float(np.min(w["v(v3v3)"][m])),
        "waves": w, "t_step": t_step,
    }
    return res


def dc_table(i_total=None, sources=(4.75, 5.0), cables=(0.1, 0.25, 0.3), r_on=None):
    """The steady-state arithmetic the sim reproduces: VBUS at J1 and VSYS at i_total, per source and cable."""
    b = design.board()
    i_total = b["vsys_budget_max"] if i_total is None else i_total
    r_on = design.TPS25947["R_ON"][1] if r_on is None else r_on
    rows = []
    for vs in sources:
        for rc in cables:
            vbus = vs - i_total * rc
            rows.append({"v_src": vs, "r_cable": rc, "vbus": vbus, "vsys": vbus - i_total * (r_on + b["shunt_vsys"])})
    return rows


def max_cable(i_total=None, v_src=None, r_tol=None):
    """The largest round-trip cable resistance that keeps VBUS at J1 above U2's highest UVLO falling threshold
    (pin maximum and the divider at its 1 % corner unless r_tol says otherwise)."""
    b = design.board()
    i_total = b["vsys_budget_max"] if i_total is None else i_total
    v_src = design.USB["V_SRC_MIN"] if v_src is None else v_src
    return (v_src - thresholds(r_tol)["uvlo_fall"][2]) / i_total


def run_all():
    r = {}
    for c in ("min", "typ", "max"):
        r[f"startup_{c}"] = startup(c)
    for rc in (0.1, design.USB["R_CABLE_TYPEC_3A"], 0.3):
        r[f"ceiling_{rc:.3f}"] = ceiling(r_cable=rc)
    r["ceiling_5v0_0.250"] = ceiling(v_src=5.0, r_cable=design.USB["R_CABLE_TYPEC_3A"])
    return r
