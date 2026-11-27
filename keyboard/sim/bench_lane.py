"""Bench 1: the analog lane front end (SPEC §4.3, §6.2, §6.3, §11 #21).

The circuit, per lane: a sensor (an ideal voltage behind its output model) -> the coupon-side capacitance (other
sensor outputs, a mux, the trace) -> 47 Ohm -> the lane capacitor (1 nF C0G, or the 680 pF alternative) and the
pin's own capacitance at the MCU pin -> the ADC's sampling switch R_ADC -> the sample-and-hold capacitor C_ADC.

Source models (none of them is a vendor model; TI publishes no SPICE model of the TMAG5253 that was found):

* `stiff`   the TMAG5253 as its datasheet describes it: 1.27 Ohm DC output resistance (SBASAI5E §6.5), no limit.
* `limited` the same, clamped at +/-1 mA, the datasheet's "Output continuous current" (§6.3). TI gives no peak or
            short-circuit current, so the truth lies between `stiff` and `limited`.
* `r1k`     a 1 kOhm source: SPEC's example of a slow lane (DS13543 Table 97's 1 kOhm maximum at 14 bits).

ADC models (design.adc_brackets(); DS13543 gives C_ADC but no R_ADC): `T97`, Table 97's 5 pF behind the slowest
internal time constant that Table 98's rows support (about 4.5 kOhm, tau0 22.5 ns), the reference for pass/fail;
`T98fit`, 14 pF with the same tau0 (all of the fitted capacitance kicks back), an upper bound; `fast`, 5 pF behind
1.4 kOhm (7 ns), SPEC §6.3's implicit assumption, kept to show where its 0.14 LSB comes from. The residual charge
on C_ADC before a sample is bracketed three ways: `worst` (the rail opposite the lane, SPEC's 3.3 V bound), `hold`
(C_ADC keeps the previous channel's sample), `zero`.

What it can catch: a lane RC, sampling time, scan timing or source impedance that leaves a conversion more than
half an LSB off, given these models. What it cannot: the sensor's real output stage (stability into the lane
capacitor, slew, its 15 kHz signal bandwidth), the SAR's real charge behaviour, layout parasitics, noise.
"""

import math

import numpy as np

import design
import spice

LSB = design.LSB14
VREF = 3.3
HALF_LSB = 0.5 * LSB


def _source_lines(k, model, r_src_kohm=1.0):
    s, p = f"s{k}", f"p{k}"
    if model == "stiff":
        return [f"Rsrc{k} {s} {p} {design.TMAG5253['R_OUT']}"]
    if model == "limited":
        i = design.TMAG5253["I_O"]
        r = design.TMAG5253["R_OUT"]
        # a smooth clamp (tanh) at +/-I_O: linear with R_OUT for small currents, so the solver sees no corner
        return [f"Bsrc{k} 0 {p} I = {i} * tanh((v({s})-v({p}))/({r}*{i}))", f"Cpo{k} {p} 0 1p"]
    if model == "r1k":
        return [f"Rsrc{k} {s} {p} {r_src_kohm * 1e3}"]
    if model == "buf22":
        return [f"Rsrc{k} {s} {p} {BUF22_R}"]
    raise ValueError(model)


# The Hall coupon's buffered lane (keyboard/hardware/design/sheets/coupon_hall.py, captured 2026-11-27): an OPA2365
# follower through 22 Ohm, declared R_src 22 Ohm. Modelled as an ideal source behind 22 Ohm: the op-amp's own output
# impedance, slew (25 V/us) and current limit are not modelled.
BUF22_R = 22.0


def r_source(model, r_src_kohm=1.0):
    return {"stiff": design.TMAG5253["R_OUT"], "limited": design.TMAG5253["R_OUT"], "r1k": r_src_kohm * 1e3,
            "buf22": BUF22_R}[model]


def adc_model(name):
    """(R_ADC, C_ADC) of a bracket from design.adc_brackets(): 'T97', 'T98fit' or 'fast'."""
    r, c, _ = design.adc_brackets()[name]
    return r, c


def build(lanes, n_adc, sensor_pwl, samples, resets, model="stiff", c_lane=1e-9, r_lane=47.0, c_coupon=0.0,
          adc="T97", leak=False, r_src_kohm=1.0):
    """A netlist for `lanes` lanes and `n_adc` ADCs.

    sensor_pwl[k] -- [(t, V)] for lane k's ideal sensor voltage.
    samples       -- [(adc j, lane k, t_on, t_off)] sampling windows.
    resets        -- [(adc j, t_on, t_off, V)] windows in which C_ADC is forced to V (the residual model).
    """
    r_adc, c_adc = adc_model(adc)
    lines = []
    for k in range(lanes):
        lines.append(spice.pwl(sensor_pwl[k], f"s{k}"))
        lines += _source_lines(k, model, r_src_kohm)
        if c_coupon > 0:
            lines.append(f"Ccp{k} p{k} 0 {c_coupon}")
        lines.append(f"Rlane{k} p{k} a{k} {r_lane}")
        lines.append(f"Clane{k} a{k} 0 {c_lane}")
        lines.append(f"Cio{k} a{k} 0 {design.ADC['C_IO']}")
        if leak:
            lines.append(f"Ilk{k} a{k} 0 {design.ADC['I_LKG']}")
    for j in range(n_adc):
        lines.append(f"Cadc{j} h{j} 0 {c_adc}")
        # one control signal per (adc, lane) pair
        for k in range(lanes):
            wins = [(t0, t1) for (jj, kk, t0, t1) in samples if jj == j and kk == k]
            if not wins:
                continue
            pts = [(0.0, 0.0)]
            for t0, t1 in sorted(wins):
                pts += [(t0, 0.0), (t0 + 1e-9, 1.0), (t1, 1.0), (t1 + 1e-9, 0.0)]
            lines.append(spice.pwl(pts, f"g{j}_{k}"))
            lines.append(f"S{j}_{k} a{k} h{j} g{j}_{k} 0 swadc")
        rw = [(t0, t1, v) for (jj, t0, t1, v) in resets if jj == j]
        if rw:
            gp, vp = [(0.0, 0.0)], [(0.0, rw[0][2])]
            for t0, t1, v in sorted(rw):
                gp += [(t0, 0.0), (t0 + 1e-9, 1.0), (t1, 1.0), (t1 + 1e-9, 0.0)]
                vp += [(t0 - 2e-9, vp[-1][1]), (t0 - 1e-9, v)]
            lines.append(spice.pwl(gp, f"gr{j}"))
            lines.append(spice.pwl(vp, f"vr{j}"))
            lines.append(f"Sr{j} h{j} vr{j} gr{j} 0 swrst")
    lines.append(f".model swadc SW(VT=0.5 VH=0.01 RON={r_adc} ROFF=1e13)")
    lines.append(".model swrst SW(VT=0.5 VH=0.01 RON=10 ROFF=1e13)")
    return "\n".join(lines)


# ------------------------------------------------------------------------------------------------ kickback
def kickback(model="stiff", c_lane=1e-9, adc="T97", c_coupon=0.0, v_lane=0.0, v_residual=VREF, t_window=15e-6,
             r_lane=None, r_src_kohm=1.0):
    """One sample: C_ADC starts at v_residual, the lane sits at v_lane; the switch stays closed for t_window.

    Returns dict: t (s from the start of sampling), err (V, C_ADC minus the ideal), the first-instant step on the
    pin, and the error at each sampling-time step of SPEC §6.2 at 40 MHz."""
    r_lane = design.board()["R_lane"] if r_lane is None else r_lane
    t0 = 1e-6
    net = build(1, 1, [[(0, v_lane), (1, v_lane)]], [(0, 0, t0, t0 + t_window)], [(0, 0.05e-6, t0 - 0.2e-6, v_residual)],
                model=model, c_lane=c_lane, c_coupon=c_coupon, adc=adc, r_lane=r_lane, r_src_kohm=r_src_kohm)
    w = spice.run(net, ["v(h0)", "v(a0)"], f"tran 0.2n {t0 + t_window} 0 1n")
    t = w.scale - t0
    m = t >= 0
    err = w["v(h0)"][m] - v_lane
    pin = w["v(a0)"][m] - v_lane
    tt = t[m]
    f = design.ADC["f_ADC"]
    at_smp = {n: float(np.interp(n / f, tt, err)) / LSB for n in design.ADC["SMP"] if n / f <= t_window}
    return {
        "t": tt, "err": err, "pin": pin,
        "pin_step_lsb": float(np.max(np.abs(pin))) / LSB,
        "settle_half_lsb": spice.settle_time(tt, err, HALF_LSB),
        "err_lsb_at_smp": at_smp,
    }


def kickback_analytic(c_lane, c_adc, r_total, t_s, v_step=VREF):
    """SPEC §6.3's arithmetic: step v_step * C_ADC / (C_lane + C_ADC), recovering with (R) x (C_lane + C_ADC)."""
    step = v_step * c_adc / (c_lane + c_adc)
    return step * math.exp(-t_s / (r_total * (c_lane + c_adc))) / LSB


# ------------------------------------------------------------------------------------------------ select step
def select_step(model="stiff", c_lane=1e-9, c_coupon=0.0, v0=0.0, v1=VREF, t_window=30e-6, r_lane=None):
    """The lane's response to a select step (a mux switching sensors) with no ADC load: time to half an LSB."""
    r_lane = design.board()["R_lane"] if r_lane is None else r_lane
    t0 = 0.5e-6
    net = build(1, 0, [[(0, v0), (t0, v0), (t0 + 1e-9, v1), (1, v1)]], [], [], model=model, c_lane=c_lane,
                c_coupon=c_coupon, r_lane=r_lane)
    w = spice.run(net, ["v(a0)"], f"tran 0.5n {t0 + t_window} 0 5n")
    t = w.scale - t0
    m = t >= 0
    err = w["v(a0)"][m] - v1
    return {"t": t[m], "err": err, "settle_half_lsb": spice.settle_time(t[m], err, HALF_LSB)}


def t_rc_spec(r_src, c_lane=1e-9, r_lane=47.0):
    """SPEC §6.3: t_RC = (R_src + 47 Ohm) x 1 nF x ln(2^15)."""
    return (r_src + r_lane) * c_lane * math.log(2 ** 15)


# ------------------------------------------------------------------------------------------------ scan
def scan_pattern(name, steps=8, seed=7):
    """Ideal sensor voltages [step][lane] for a 4-lane slot. 'alternate' is the worst case for both the select
    step and the channel-to-channel kickback; 'random' spans the linear range; 'rest' is every key near rest."""
    lo, hi = design.TMAG5253["V_LIN"]
    if name == "alternate":
        return [[lo if (s + k) % 2 == 0 else hi for k in range(4)] for s in range(steps)]
    if name == "random":
        rng = np.random.default_rng(seed)
        return [list(rng.uniform(lo, hi, 4)) for _ in range(steps)]
    if name == "rest":
        rng = np.random.default_rng(seed)
        return [list(1.65 + rng.uniform(-0.05, 0.05, 4)) for _ in range(steps)]
    raise ValueError(name)


def scan(model="stiff", pattern="alternate", smp=12, residual="worst", c_lane=1e-9, c_coupon=0.0, adc="T97",
         t_settle=0.0, t_rc=None, leak=False, steps=8):
    """One slot's scan per SPEC §6.1-§6.3: each step switches the four lanes at once, waits t_settle + t_RC, then
    the trigger latency, then ADC1 converts AN0, AN1 and ADC2 converts AN2, AN3 (dual simultaneous mode).

    t_rc defaults to SPEC's formula for this source. Returns the per-conversion errors in LSB and the timing."""
    f = design.ADC["f_ADC"]
    r_lane = design.board()["R_lane"]
    t_s = smp / f
    t_cv = design.ADC["N_conv"] / f
    t_latr = design.ADC["t_LATR_cycles"] / f
    t_rc = t_rc_spec(r_source(model), 1e-9, r_lane) if t_rc is None else t_rc
    t_step = t_settle + t_rc + t_latr + 2 * (t_s + t_cv) + 0.075e-6     # SPEC t_dma 0.4 us = t_LATR + select write
    vals = scan_pattern(pattern, steps)
    pre = 2e-6 if model != "r1k" else 15e-6
    pwl = [[(0, vals[0][k])] for k in range(4)]
    samples, resets, convs = [], [], []
    pairs = {0: (0, 1), 1: (2, 3)}           # ADC1: AN0 then AN1; ADC2: AN2 then AN3
    prev = {0: vals[-1][1], 1: vals[-1][3]}
    for s in range(steps):
        t0 = pre + s * t_step
        for k in range(4):
            pwl[k] += [(t0, pwl[k][-1][1]), (t0 + 1e-9, vals[s][k])]
        ts0 = t0 + t_settle + t_rc + t_latr
        for j, (ka, kb) in pairs.items():
            for n, k in enumerate((ka, kb)):
                a = ts0 + n * (t_s + t_cv)
                b = a + t_s
                if residual != "hold":
                    v_res = 0.0 if residual == "zero" else (VREF if vals[s][k] < VREF / 2 else 0.0)
                    resets.append((j, a - t_cv + 2 / f, a - 2 / f, v_res))
                samples.append((j, k, a, b))
                convs.append({"step": s, "adc": j, "lane": k, "t_end": b, "ideal": vals[s][k], "prev": prev[j]})
                prev[j] = vals[s][k]
    t_end = pre + steps * t_step + 1e-6
    for k in range(4):
        pwl[k].append((t_end + 1e-6, pwl[k][-1][1]))
    net = build(4, 2, pwl, samples, resets, model=model, c_lane=c_lane, c_coupon=c_coupon, adc=adc, leak=leak,
                r_lane=r_lane)
    w = spice.run(net, ["v(h0)", "v(h1)", "v(a0)", "v(a1)", "v(a2)", "v(a3)"], f"tran 0.5n {t_end} 0 2n")
    for c in convs:
        c["err_lsb"] = (float(w.at(f"v(h{c['adc']})", c["t_end"])) - c["ideal"]) / LSB
    errs = np.array([c["err_lsb"] for c in convs])
    return {"convs": convs, "max_abs_lsb": float(np.max(np.abs(errs))), "t_step": t_step, "t_scan": steps * t_step,
            "waves": w, "pre": pre}


# ------------------------------------------------------------------------------------------------ summary
def run_all():
    """Every lane result the tests and the README use. Scans run at SPEC §6.2's working-point sampling time, read
    from SPEC.md (keys ending in _ts), and at 20 cycles, the step this tool recommends."""
    b = design.board()
    c1, c680 = b["C_lane"], b["C_lane_alt"]
    ts = design.spec_adc_smp()
    r = {"smp_spec": ts}
    for model in ("stiff", "r1k"):
        for cl_name, cl in (("1n", c1), ("680p", c680)):
            for adc in ("T97", "T98fit"):
                r[f"kick_{model}_{cl_name}_{adc}"] = kickback(model, cl, adc, t_window=15e-6 if model == "r1k" else 3e-6)
    r["kick_stiff_1n_fast"] = kickback("stiff", c1, "fast", t_window=3e-6)
    r["kick_r1k_1n_fast"] = kickback("r1k", c1, "fast", t_window=15e-6)
    for model, cc in (("stiff", 0.0), ("limited", 0.0), ("r1k", 0.0), ("r1k", design.ASSUMED["C_coupon_lane"])):
        for cl_name, cl in (("1n", c1), ("680p", c680)):
            key = f"step_{model}_{cl_name}" + ("_cc" if cc else "")
            r[key] = select_step(model, cl, cc, t_window=40e-6 if model == "r1k" else 8e-6)
    r["kick_buf22_1n_T97"] = kickback("buf22", c1, "T97", t_window=3e-6)
    r["kick_buf22_1n_T98fit"] = kickback("buf22", c1, "T98fit", t_window=3e-6)
    r["step_buf22_1n"] = select_step("buf22", c1, t_window=8e-6)
    r["scan_buf22_ts"] = scan("buf22", "alternate", ts, "worst")
    r["scan_buf22_20"] = scan("buf22", "alternate", 20, "worst")
    r["scan_stiff_ts"] = scan("stiff", "alternate", ts, "worst")
    r["scan_stiff_ts_fast"] = scan("stiff", "alternate", ts, "worst", adc="fast")
    r["scan_stiff_ts_T98"] = scan("stiff", "alternate", ts, "worst", adc="T98fit")
    r["scan_stiff_ts_hold_random"] = scan("stiff", "random", ts, "hold")
    r["scan_stiff_20"] = scan("stiff", "alternate", 20, "worst")
    r["scan_stiff_20_T98"] = scan("stiff", "alternate", 20, "worst", adc="T98fit")
    r["scan_limited_ts"] = scan("limited", "alternate", ts, "worst")
    r["scan_r1k_ts"] = scan("r1k", "alternate", ts, "worst")
    r["scan_r1k_391"] = scan("r1k", "alternate", 391, "worst")
    r["scan_r1k_391_cc"] = scan("r1k", "alternate", 391, "worst", c_coupon=design.ASSUMED["C_coupon_lane"])
    r["scan_r1k_391_leak"] = scan("r1k", "rest", 391, "hold", leak=True)
    return r


# ------------------------------------------------------------------------------------------------ SPEC's table
# SPEC §6.3's keys-per-slot figures are read from SPEC.md at run time (design.spec_keys_tables()), so the test that
# reproduces them follows SPEC. As read on 2026-11-27: one slot {1: 32, 5: 32, 10: 24, 20: 12, 25: 8, 45: 4, 50: 4};
# all five slots in lockstep {1: 32, 5: 24, 10: 16, 25: 8, 50: 4}; R_src 1 kOhm {1: 20, 5: 16, 10: 12, 25: 8, 50: 4};
# and with 391 sampling cycles {1: 8, 5: 8, 10: 4, 25: 4, 50: 0}.


def keys_table(t_rc, smp=12, conv_per_adc=2, t_settles=(1, 5, 10, 20, 25, 45, 50), window=80e-6, max_steps=8,
               t_dma=0.4e-6):
    """SPEC §6.3's arithmetic: t_step = t_settle + t_RC + t_conv + t_dma; steps = min(8, window // t_step);
    keys = 4 x steps. Returns {t_settle_us: (t_step, steps, keys, scan_time)}."""
    f = design.ADC["f_ADC"]
    t_conv = conv_per_adc * (smp + design.ADC["N_conv"]) / f
    out = {}
    for ts in t_settles:
        t_step = ts * 1e-6 + t_rc + t_conv + t_dma
        steps = min(max_steps, int(window / t_step + 1e-9))
        out[ts] = (t_step, steps, 4 * steps, steps * t_step)
    return out


def keys_with_simulated_settling(lane_results):
    """SPEC's one-slot table again, with t_RC taken from the simulated settling instead of the formula: the
    TMAG5253 as specified at SPEC's working-point t_s and at 20 cycles, and clamped at its rated 1 mA."""
    ts = lane_results.get("smp_spec", design.spec_adc_smp())
    rows = {}
    for label, key, smp in ((f"SPEC (t_RC formula, {ts} cycles)", None, ts),
                            ("TMAG5253, 20 cycles (this tool's recommendation)", "step_stiff_1n", 20),
                            (f"TMAG5253 clamped at 1 mA, {ts} cycles", "step_limited_1n", ts)):
        t_rc = t_rc_spec(design.TMAG5253["R_OUT"]) if key is None else lane_results[key]["settle_half_lsb"]
        rows[label] = keys_table(t_rc, smp)
    return rows


# ------------------------------------------------------------------------------------------------ t_s lookup
def min_sampling_cycles(r_src, adc="T97", c_lane=1e-9):
    """The smallest of the ADC's sampling-time steps (SPEC §6.2, at 40 MHz) after which the worst-case kickback
    from a source of r_src Ohm is within half an LSB at 14 bits. A lookup the firmware (or compiler v0, from the
    descriptor's declared R_src) can use to pick SMPx per lane. None if even 814 cycles are not enough."""
    f = design.ADC["f_ADC"]
    t_win = max(design.ADC["SMP"]) / f * 1.02
    k = kickback("r1k", c_lane, adc, t_window=t_win, r_src_kohm=r_src / 1e3)
    for n in design.ADC["SMP"]:
        if abs(k["err_lsb_at_smp"].get(n, 1e9)) < 0.5:
            return n
    return None


def sampling_table(r_values=(1.27, 22, 47, 100, 220, 470, 1000, 2200), adcs=("T97", "T98fit")):
    """{r_src: {adc: cycles}}: min_sampling_cycles over a range of declared source impedances."""
    return {r: {a: min_sampling_cycles(r, a) for a in adcs} for r in r_values}
