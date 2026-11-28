"""Run every bench, write the plots to keyboard/sim/plots/, and print the results table the README carries.

    /root/.venvs/kbd/bin/python keyboard/sim/run_all.py            # all benches, plots, table (about 2 minutes)
    /root/.venvs/kbd/bin/python keyboard/sim/run_all.py --no-plots

The numbers are simulations of datasheet-based models. None of them is a measurement.
"""

import argparse
import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bench_input  # noqa: E402
import bench_lane  # noqa: E402
import bench_slot  # noqa: E402
import bench_vdda  # noqa: E402
import design  # noqa: E402
import spice  # noqa: E402

LSB = design.LSB14


def _ms(x):
    return "none" if x is None else f"{x * 1e3:.2f} ms"


def vdda_rows(v):
    """Rows for bench 4, the +3V3A branch (SPEC §3.7, owner decision D4)."""
    out = []
    cap, leg = v["compare"]["captured"], v["compare"].get("leg", {})
    out.append(f"| VDDA | +3V3_SLOT to +3V3A peaking, as captured (FB1 0.1 / 0.5 / 2 µH) | risks.md EL-5: resonance "
               f"at 76-196 kHz | {' / '.join(f'{cap[l]['peak_db']:+.1f} dB at {cap[l]['f_peak'] / 1e3:.0f} kHz' for l in (0.1e-6, 0.5e-6, 2e-6))} "
               "| **resonates in the scan's band** |")
    if leg:
        out.append(f"| VDDA | The same with the leg (0.47 Ω + 10 µF); whole bracket; capacitor at 47 % | D4: damp it | "
                   f"{' / '.join(f'{leg[l]['peak_db']:+.1f} dB' for l in (0.1e-6, 0.5e-6, 2e-6))}; worst "
                   f"{v['bracket_leg']['peak_db']:+.1f} dB; {v['bracket_leg_derated']['peak_db']:+.1f} dB | holds (≤ 3 dB) |")
    for opt, label in (("captured_2uH", "as captured, FB1 2 µH"), ("leg_2uH", "with the leg, FB1 2 µH"),
                       ("r1", "1 Ω in place of FB1"), ("r2p2", "2.2 Ω in place of FB1")):
        if f"burst_{opt}" in v:
            out.append(f"| VDDA | VREF+ swing inside a scan window from the ADCs' 2.66 mA, {label} | – | "
                       f"{v[f'burst_{opt}']['pp_lsb']:.1f} LSB at mid-scale | "
                       f"{'holds (≤ 3 LSB)' if v[f'burst_{opt}']['pp_lsb'] <= 3 else '**exceeds 3 LSB**'} |")
    return out


def table(lane, slot, inp, vdda=None):
    b = design.board()
    th = bench_input.thresholds()
    rows = []

    def row(area, what, spec, sim, verdict):
        rows.append(f"| {area} | {what} | {spec} | {sim} | {verdict} |")

    ts = lane["smp_spec"]
    kf = lane["kick_stiff_1n_fast"]["err_lsb_at_smp"]
    row("Lane", f"Kickback error after SPEC's {ts} cycles, TMAG5253 source, 1 nF, SPEC's assumption (a 7 ns "
        "switch: 5 pF, 1.4 kΩ)", "0.14 LSB", f"{kf[ts]:.2f} LSB", "agrees (< ½ LSB)")
    k = lane["kick_stiff_1n_T97"]["err_lsb_at_smp"]
    row("Lane", f"The same with Table 97's 5 pF behind the time constant Table 98 implies (R_ADC "
        f"{bench_lane.adc_model('T97')[0] / 1e3:.1f} kΩ)", "0.14 LSB",
        f"{k[ts]:.2f} LSB at {ts} cycles, {k[20]:.3f} at 20", f"**exceeds ½ LSB at {ts} cycles**" if k[ts] >= 0.5
        else "agrees")
    k98 = lane["kick_stiff_1n_T98fit"]["err_lsb_at_smp"]
    row("Lane", "The same with all 14 pF of Table 98's single-RC fit kicking back (upper bound)", "not considered",
        f"{k98[ts]:.2f} LSB at {ts} cycles, {k98[20]:.3f} at 20", f"**exceeds ½ LSB at {ts} cycles**"
        if k98[ts] >= 0.5 else "agrees")
    k1 = lane["kick_r1k_1n_T97"]
    row("Lane", f"1 kΩ source: error at {ts} cycles; time to ½ LSB; error at 391 cycles",
        "≈ 62 LSB; ≈ 5.4 µs; fine", f"{k1['err_lsb_at_smp'][ts]:.0f} LSB; {k1['settle_half_lsb'] * 1e6:.2f} µs; "
        f"{k1['err_lsb_at_smp'][391]:.3f} LSB", "agrees")
    k6 = lane["kick_stiff_680p_T97"]
    row("Lane", f"680 pF alternative: worst kickback step at the pin; error after {ts} cycles",
        "≈ 24 mV (3.3 V × 5/685)", f"{k6['pin_step_lsb'] * LSB * 1e3:.1f} mV; {k6['err_lsb_at_smp'][ts]:.3f} LSB",
        "agrees (SPEC's figure is the instantaneous bound)")
    kb, kb98 = lane["kick_buf22_1n_T97"]["err_lsb_at_smp"], lane["kick_buf22_1n_T98fit"]["err_lsb_at_smp"]
    row("Lane", f"Hall coupon as captured (OPA2365 + 22 Ω): kickback after {ts} / 20 cycles (T97; 14 pF bound)",
        "coupon notes: ≈ 1 / 0.06 LSB", f"{kb[ts]:.2f} / {kb[20]:.2f} LSB; {kb98[ts]:.1f} / {kb98[20]:.2f} LSB",
        f"**needs 20 cycles, not SPEC's {ts}**")
    s = lane["step_stiff_1n"]["settle_half_lsb"]
    row("Lane", "Select step 0 → 3.3 V to ½ LSB, TMAG5253 as specified (1.27 Ω)", "t_RC ≈ 0.49 µs",
        f"{s * 1e6:.2f} µs", "agrees")
    s = lane["step_limited_1n"]["settle_half_lsb"]
    row("Lane", "The same if the TMAG5253 can source only its rated ±1 mA", "stiff (0.49 µs)",
        f"{s * 1e6:.2f} µs", "**unsupported by the datasheet** (needs up to 70 mA)")
    s0, s1 = lane["step_r1k_1n"]["settle_half_lsb"], lane["step_r1k_1n_cc"]["settle_half_lsb"]
    row("Lane", "Select step, 1 kΩ source; with 190 pF on the coupon side", "t_RC ≈ 10.9 µs",
        f"{s0 * 1e6:.1f} µs; {s1 * 1e6:.1f} µs", "agrees; **+18 % with coupon-side C**")
    leak_lsb = design.ADC["I_LKG"] * 1e9
    for key, what, spec in (
            ("scan_stiff_ts_fast", f"Scan, 8 steps × 4 lanes, TMAG5253, {ts} cycles, worst residual, SPEC's "
             "assumption (7 ns switch)", "< ½ LSB"),
            ("scan_stiff_ts", f"Scan, TMAG5253, {ts} cycles, T97 bracket", "< ½ LSB"),
            ("scan_stiff_ts_T98", f"Scan, TMAG5253, {ts} cycles, 14 pF upper bound", "< ½ LSB"),
            ("scan_stiff_20", "Scan, TMAG5253, 20 cycles, T97 bracket", "< ½ LSB"),
            ("scan_stiff_20_T98", "Scan, TMAG5253, 20 cycles, 14 pF upper bound", "< ½ LSB"),
            ("scan_limited_ts", f"Scan, TMAG5253 clamped at ±1 mA, {ts} cycles", "< ½ LSB"),
            ("scan_buf22_ts", f"Scan, Hall coupon's buffered lane (22 Ω), {ts} cycles", f"§6.2 working point is {ts} "
             "cycles"),
            ("scan_buf22_20", "Scan, Hall coupon's buffered lane (22 Ω), 20 cycles", "< ½ LSB"),
            ("scan_r1k_ts", f"Scan, 1 kΩ, {ts} cycles", "≈ 62 LSB"),
            ("scan_r1k_391_cc", "Scan, 1 kΩ, 391 cycles, 190 pF coupon side", "< ½ LSB"),
            ("scan_r1k_391_leak", f"Scan, 1 kΩ, 391 cycles, pin leakage {leak_lsb:.0f} nA (DS13543 Table 87, TT pin)",
             "< ½ LSB")):
        e = lane[key]["max_abs_lsb"]
        ok = (e < 0.5) == ("r1k_ts" not in key)
        verdict = "agrees" if ok else (f"**a {e:.1f} LSB offset outside SPEC's budget**" if "leak" in key else
                                       "**disagrees**")
        row("Lane", what, spec, f"max {e:.2f} LSB", verdict)

    for rail, nm in (("3v3", "+3V3_Sn"), ("5v", "+5V_Sn")):
        for load in ("none", "r", "cc"):
            for ios in ("min", "typ"):
                d = slot[f"en_{rail}_{load}_{ios}_nosoft"]
                v = "FAULT at min deglitch" if d["fault_min_deglitch"] else "no FAULT"
                lname = {"none": "bulk only", "r": "bulk + R at rule", "cc": "bulk + constant I at rule"}[load]
                row("Slot", f"{nm} enable, {d['c_bulk'] * 1e6:.0f} µF, {lname}, I_OS {ios}, no soft start",
                    "never limited or tripped within the rules", f"{d['t_lim'] * 1e3:.2f} ms in limit",
                    v if not d["fault_min_deglitch"] else f"**{v}**")
    d = slot["en_3v3_none_max_nosoft"]
    row("Slot", "VDDA dip when another slot's 3.3 V rail enables (no soft start, I_OS max)", "not considered",
        f"{d['vdda_dip'] * 1e3:.0f} mV ({d['vdda_dip_midscale_lsb']:.0f} LSB at mid-scale)",
        "**new**: do not switch rails during a run")
    for key, what in (("s5_detents_typ", "S5, 1 A detent peaks, 5.0 V source, 0.1 Ω cable"),
                      ("s5_detents_worst", "S5, 1 A detents, 4.75 V source, 0.25 Ω cable, R_ON max"),
                      ("s5_rule_board_only", "S5 at its 2 A rule, 4.75 V at J1 (no cable), R_ON max"),
                      ("s5_rule_ceiling_worst", "S5 at 2 A with the board at 2.8 A, 4.75 V, 0.25 Ω cable")):
        d = slot[key]
        vmin = d["v_coupon_min"]
        verdict = "above DRV8316 VM 4.5 V" if vmin >= 4.5 else (
            "**below VM min 4.5 V**" if vmin >= design.DRV8316["UVLO_FALL"][2] else "**below DRV8316 UVLO (4.3 V max)**")
        if key == "s5_rule_board_only":
            verdict = "agrees with SPEC; " + verdict
        row("S5", what, "4.3-4.5 V at the coupon from 4.75 V, plus the cable" if "rule" in key else "–",
            f"{vmin:.2f} V min at the coupon", verdict)
    d0, d1 = slot["s5_rule_ilim_min"], slot["s5_rule_ilim_min_rtol"]
    row("S5", "2.0 A steady (the rule) at U5's I_LIM min, without / with R_ILM's 1 %",
        "trip min 2.01 A > 2 A rule", f"{d0['ilim_a']:.3f} A: {'trips' if d0['u5_trip_t'] else 'holds'}; "
        f"{d1['ilim_a']:.3f} A: {'trips after ' + _ms(d1['u5_trip_t']) if d1['u5_trip_t'] else 'holds'}",
        "**latches off** with R_ILM 1 % high" if d1["u5_trip_t"] else "holds")
    lo, ty, hi = design.itimer_window(b["s5_c_itimer"])
    d = slot["s5_burst_short_min_itimer"]
    row("S5", f"2.6 A for {0.9 * lo * 1e3:.2f} ms, shortest ITIMER", f"blanking {lo * 1e3:.2f}-{hi * 1e3:.2f} ms",
        "holds" if d["u5_trip_t"] is None else f"trips after {_ms(d['u5_trip_t'])}", "agrees")
    d = slot["s5_burst_long_max_itimer"]
    row("S5", f"2.6 A for {1.2 * hi * 1e3:.2f} ms, longest ITIMER", "latches off after the blanking time",
        _ms(d["u5_trip_t"]), "agrees")
    d = slot["s5_short"]
    row("S5", "10 A short on the coupon", "fast trip at 2 × I_LIM", f"trips after {_ms(d['u5_trip_t'])}, "
        f"peak {d['i_s5_max']:.1f} A", "agrees")

    for c in ("min", "typ", "max"):
        d = inp[f"startup_{c}"]
        row("Input", f"+3V3 ramp (10 % to 3.0 V), I_dVdt {c}", "within 25 ms (U_CC VDD)",
            f"{d['t_3v3_ramp'] * 1e3:.1f} ms; inrush {d['i_inrush'] * 1e3:.0f} mA", "agrees")
    for key in sorted(k for k in inp if k.startswith("ceiling_")):
        d = inp[key]
        if d["u2_uvlo_off"]:
            verdict = "**U2 UVLO: turns off and chatters**" if d["u2_on_at_step"] else "**U2 never on**"
        else:
            notes = (["VSYS_PG may fall"] if d["margin_pg"] < 0 else []) + \
                ([f"UVLO margin only {d['margin_uvlo'] * 1e3:.0f} mV"] if d["margin_uvlo"] < 0.05 else [])
            verdict = f"**{'; '.join(notes)}**" if notes else "holds"
        vsys = f"VSYS {d['vsys_min']:.2f} V" if not d["u2_uvlo_off"] else "VSYS cycling (load-model artifact)"
        row("Input", f"2.8 A ceiling, {d['v_src']:.2f} V source, {d['r_cable']:.3f} Ω cable",
            "board runs at the ceiling", f"VBUS {d['vbus_min']:.2f} V, {vsys}; UVLO margin "
            f"{d['margin_uvlo'] * 1e3:+.0f} mV, U_CC {d['margin_ucc'] * 1e3:+.0f} mV", verdict)
    row("Input", "Largest cable at 2.8 A from 4.75 V before U2's UVLO (max threshold, 1 % divider)", "not stated",
        f"{bench_input.max_cable() * 1e3:.0f} mΩ round trip ({bench_input.max_cable(r_tol=0) * 1e3:.0f} mΩ with "
        "exact resistors)", "a compliant 3 A cable is 250 mΩ")
    hdr = ["| Area | Case | SPEC says | Simulated | Verdict |", "|---|---|---|---|---|"]
    rows += vdda_rows(vdda) if vdda else []
    keys = ["", "| SPEC §6.3 one-slot table, keys per slot for t_settle = | " +
            " | ".join(f"{t} µs" for t in (1, 5, 10, 20, 25, 45, 50)) + " |", "|---" * 8 + "|"]
    for label, tab in bench_lane.keys_with_simulated_settling(lane).items():
        keys.append(f"| {label} | " + " | ".join(f"{v[2]} ({v[0] * 1e6:.1f} µs)" for v in tab.values()) + " |")
    tab = bench_lane.sampling_table(adcs=("fast", "T97", "T98fit"))
    smp = ["", "| Declared R_src (Ω) | " + " | ".join(f"{r:g}" for r in tab) + " |", "|---" * (1 + len(tab)) + "|"]
    for adc, label in (("fast", "min. sampling cycles, SPEC's assumption (5 pF, 7 ns switch)"),
                       ("T97", "min. sampling cycles, T97 (5 pF behind Table 98's time constant)"),
                       ("T98fit", "min. sampling cycles, 14 pF upper bound")):
        smp.append(f"| {label} | " + " | ".join(str(v[adc]) for v in tab.values()) + " |")
    return "\n".join(hdr + rows + keys + smp), th


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-plots", action="store_true")
    a = ap.parse_args()
    print(f"# {spice.version()}", file=sys.stderr)
    lane = bench_lane.run_all()
    slot = bench_slot.run_all()
    inp = bench_input.run_all()
    vdda = bench_vdda.run_all()
    md, th = table(lane, slot, inp, vdda)
    print(md)
    print()
    print("Provenance of the design values:")
    for k, v in sorted(design.provenance().items()):
        print(f"* {k}: {v}")
    if not a.no_plots:
        import plots
        for p in (plots.lane_kickback(lane), plots.lane_step(lane), plots.lane_scan(lane), plots.slot_enable(slot),
                  plots.slot_vdda(slot), plots.s5_droop(slot), plots.s5_breaker(slot), plots.input_startup(inp),
                  plots.input_ceiling(inp, th), plots.vdda_damping(vdda)):
            print("wrote", os.path.relpath(p, design.REPO), file=sys.stderr)


if __name__ == "__main__":
    main()
