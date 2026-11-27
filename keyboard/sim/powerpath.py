"""The motherboard's 5 V power path as one netlist (SPEC §3.1, §3.5, §3.6): source, cable, VBUS, the input breaker
U2, the VSYS shunt and bulk, the two LDOs, an optional extra VSYS load, and optionally S5's breaker U5, its shunt,
the socket contacts and a haptics coupon (bulk capacitor and a motor current profile).

The values come from design.board() (the contract and the generated netlist) and design.py's datasheet constants.
"""

import design
import powermodels as pm


def corner_values(corner="typ"):
    """Datasheet corners for the breakers and LDO. 'typ', or 'worst': R_ON max, the highest EN/UVLO thresholds, and
    U2's EN/UVLO divider at its 1 % corner that raises the threshold seen at VBUS (top resistor high, bottom low)."""
    t = design.TPS25947
    if corner == "typ":
        return {"r_on": t["R_ON"][0], "uvlo_r": t["V_UVLO_R"][1], "uvlo_f": t["V_UVLO_F"][1], "ap_rdrop": 0.125 / 0.3,
                "ldl_rdrop": 0.350 / 1.2, "r_tol": 0.0}
    return {"r_on": t["R_ON"][1], "uvlo_r": t["V_UVLO_R"][2], "uvlo_f": t["V_UVLO_F"][2], "ap_rdrop": 0.400 / 0.6,
            "ldl_rdrop": 0.600 / 1.2, "r_tol": design.R_TOL}


def build(v_src=5.0, r_cable=0.25, l_cable=None, t_src=0.1e-3, src_rise=0.1e-3, corner="typ", u2_ilim="typ",
          i_dvdt="typ", vsys_load=None, i_3v3=None, s5=None, t_en_u2=0.0):
    """Returns (netlist, vectors).

    vsys_load -- [(t, A)] extra constant-current load on VSYS (the other slots), or None.
    s5        -- dict(t_en, motor=[(t, A)], c_bulk, esr, ilim='typ'|'min'|'min_rtol'|'max', i_dvdt) or None.
    """
    b = design.board()
    cv = corner_values(corner)
    l_cable = design.ASSUMED["L_cable"] if l_cable is None else l_cable
    i_3v3 = design.ASSUMED["base_load"] if i_3v3 is None else i_3v3
    t = design.TPS25947
    lines = [
        f"Vsrc src 0 PWL(0 0 {t_src:.9g} 0 {t_src + src_rise:.9g} {v_src})",
        pm.cable("CB", "src", "vbus", r_cable, l_cable),
        pm.cap("C30", "vbus", b["c_vbus"]),
    ]
    # U2, the input breaker: EN/UVLO from the VBUS divider
    ilim_u2 = _ilim(b["u2_r_ilm"], u2_ilim)
    sr_u2 = _sr(b["u2_c_dvdt"], i_dvdt)
    ratio = 1.0 / design.divider_k(b["uvlo_top"], b["uvlo_bot"], cv["r_tol"])[2]
    lines.append(pm.tps259474("U2", "vbus", "vsys_in", t_en_u2, cv["r_on"], ilim_u2, sr_u2, b["u2_c_itimer"],
                              t["I_ITIMER"][1], t["dV_ITIMER"][1], uvlo=(ratio, cv["uvlo_r"], cv["uvlo_f"])))
    lines += [
        f"Rpgth2 vsys_in 0 {b['pgth_top'] + b['pgth_bot']:.6g}",       # U2's PGTH divider
        f"Rshvsys vsys_in vsys {b['shunt_vsys']}",
        pm.cap("Cvsys", "vsys", b["c_vsys"]),
        # U3 AP2112K -> +3V3 (the base load: MCU, monitors, logic)
        pm.ldo("U3", "vsys", "v3v3", 3.3, cv["ap_rdrop"], l_eq=0.4e-6, r_d=0.15),
        pm.cap("C3v3", "v3v3", b["c_3v3"] + b["c_3v3_mcu"]),
        f"R3v3load v3v3 0 {3.3 / i_3v3:.6g}",           # 45 mA at 3.3 V (a resistor: no current when unpowered)
        # U4 LDL1117 -> +3V3_SLOT (VDDA's 2 mA; slot 3.3 V loads come from the slot bench)
        pm.ldo("U4", "vsys", "vslot", 3.3, cv["ldl_rdrop"]),
        pm.cap("Cslot", "vslot", b["c_3v3_slot"]),
        f"Rslotload vslot 0 {3.3 / 0.002:.6g}",
    ]
    vectors = ["v(src)", "v(vbus)", "v(vsys_in)", "v(vsys)", "v(v3v3)", "v(vslot)", "i(VU2m)", "v(U2_ena)",
               "v(U2_trip)", "v(U2_it)"]
    if vsys_load:
        pts = " ".join(f"{a:.9g} {c:.9g}" for a, c in vsys_load)
        lines += [f"Vxl xl 0 PWL({pts})", "Bxload vsys 0 I = v(xl)*" + pm.step("v(vsys)-2.5", 0.2)]
    if s5:
        ilim_u5 = _ilim(b["s5_r_ilm"], s5.get("ilim", "typ"))
        sr_u5 = _sr(b["s5_c_dvdt"], s5.get("i_dvdt", "typ"))
        rc = design.ASSUMED["R_contact"] / 3
        lines += [
            pm.tps259474("U5", "vsys", "s5sw", s5["t_en"], cv["r_on"], ilim_u5, sr_u5, b["s5_c_itimer"],
                         t["I_ITIMER"][1], t["dV_ITIMER"][1]),
            f"Rpgth5 s5sw 0 {b['pgth_top'] + b['pgth_bot']:.6g}",       # U5's PGTH divider (the same values)
            f"Rshs5 s5sw s5m {b['shunt_s5']}",
            pm.cap("Csock5", "s5m", b["s5_socket_c"]),
            f"Rpin5 s5m cpn {rc:.6g}",
            f"Rgnd5 cpng 0 {rc:.6g}",
            pm.cap("Cbulk5", "cpn", s5.get("c_bulk", b["bulk_s5"]), esr=s5.get("esr", design.ASSUMED["ESR_bulk_s5"]),
                   ref="cpng"),
        ]
        pts = " ".join(f"{a:.9g} {c:.9g}" for a, c in s5["motor"])
        # the motor draws its profile once the rail is up (a driver in UVLO draws nothing)
        lines += [f"Vmot mot 0 PWL({pts})", "Bmotor cpn cpng I = v(mot)*" + pm.step("v(cpn)-v(cpng)-3.0", 0.1)]
        vectors += ["v(s5sw)", "v(s5m)", "v(cpn)", "v(cpng)", "i(VU5m)", "v(U5_trip)", "v(U5_it)", "v(mot)"]
    return "\n".join(lines), vectors


def _ilim(r_ilm, which):
    lo, ty, hi = design.tps25947_ilim(r_ilm)
    lo_t, _, hi_t = design.tps25947_ilim(r_ilm, 0.01)
    return {"typ": ty, "min": lo, "max": hi, "min_rtol": lo_t, "max_rtol": hi_t}[which]


def _sr(c_dvdt, which):
    lo, ty, hi = design.dvdt_slew(c_dvdt)
    return {"min": lo, "typ": ty, "max": hi}[which]
