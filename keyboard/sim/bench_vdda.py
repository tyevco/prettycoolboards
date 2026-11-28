"""Bench 4: the +3V3A branch, VDDA and VREF+ behind FB1 (SPEC §3.1, §3.7; risks.md EL-5; owner decision D4).

The circuit, as captured (keyboard/hardware/kicad/motherboard netlist, read at run time):

    VSYS -> LDL1117 U4 -> +3V3_SLOT (C41 4.7 uF + five 100 nF at the TPS2553 inputs)
         -> FB1 BLM18PG221SN1D -> +3V3A (C108-C111: 2 x (100 nF + 1 uF) at VDDA and VREF+) -> the ADCs

Below a few MHz a ferrite bead is mostly an inductance, so FB1 and the 2.2 uF on +3V3A form a series LC with little
damping: risks.md EL-5 puts its resonance at 76-196 kHz, where the scan's eight select steps per 125 us frame put
64 kHz and its harmonics. This bench models the branch with the LDO's output impedance (the `ldo` model of
powermodels.py, fitted to LDL1117 Figure 27; ST publishes no SPICE model of the LDL1117 that was found, and st.com
was unreachable on 2026-11-27), and compares three ways to tame it:

* `captured`: FB1 and the 2.2 uF as captured, no damping;
* `leg`: the owner's first option (D4, 2026-11-27): a damping leg on +3V3A, a resistor in series with a capacitor to
  GND, at the values `nets.VDDA_DAMPING` names (0.47 ohm + 10 uF);
* `r1`, `r2p2`: the owner's second option, a resistor in place of FB1 (1 ohm or 2.2 ohm, with 10 uF more on +3V3A,
  as EL-5 proposed: "1-2.2 ohm plus more capacitance").

Two views:

* **AC** (small signal around the operating point): the transfer H(f) = V(+3V3A) / V(+3V3_SLOT), whose peak is the
  resonance's gain, and the impedance Z(f) that a current drawn at +3V3A sees (the ADCs' own current), from 1 kHz to
  10 MHz.
* **Transient**: (a) the ADCs start a scan window: ADC1, ADC2 and ADC4 draw their 2.5 Msps currents (DS13543 Table
  97 and Table 100, typ: 2 x (980 + 160) + 360 + 18 uA = 2.66 mA) for the 80 us scan window of SPEC §6.3; (b) the same
  current in eight 1.45 us conversion pulses per 125 us frame (the §6.3 step); (c) another slot's sensors switch on:
  a 10.4 mA step on +3V3_SLOT (four TMAG5253 at 2.6 mA typ, SBASAI5E, one gated select step at 1 kHz). Every
  disturbance is quoted as a ratiometric error at mid-scale in 14-bit LSB: a change dV of VREF+ moves the code of a
  mid-scale input by 2^13 x dV / 3.3 V.

The unknowns are bracketed, not guessed: FB1's low-frequency inductance is not published (Murata's spec sheet JENF243A
gives only 220 ohm +-25 % at 100 MHz and 0.10 ohm DC resistance, max), so L runs from 0.1 to 2 uH; the MLCCs lose
capacitance under DC bias (not read for these parts), so the leg's 10 uF also runs at 4.7 uF and the 2.2 uF on
+3V3A at 1.3 uF; the LDO's fitted output inductance runs at x0.5 and x2.

What it can catch: a filter whose resonance peaks inside the scan's band, or whose impedance turns the ADCs' own
current into a reference error, given these models. What it cannot: the bead's real L(f, I_DC) and loss, the LDO's
real loop (only its fitted output impedance), layout inductance, the ADC's real current waveform (only Table 97's
averages), the sensors' own supply rejection. Nothing here is measured: bring-up step 5 (SPEC §10) measures the
branch (risks.md EL-5's test).
"""

import numpy as np

import design
import powermodels as pm
import spice

F_SCAN = (64e3, 128e3, 192e3)          # Hz: risks.md EL-5's figures (eight steps spread over a frame). The scan of
                                       # SPEC §6.3 bunches its steps (3.3-52 us each) into the first 80 us, so it
                                       # excites the 8 kHz frame rate's harmonics and step rates of 19-300 kHz
L_BEAD = (0.1e-6, 0.3e-6, 0.5e-6, 1.0e-6, 2.0e-6)    # FB1's low-frequency inductance: not published, bracketed
R_BEAD_DC = 0.10                       # ohm, BLM18PG221SN1D DC resistance, max (Murata JENF243A, item 3)
C_DERATE = {"leg": 0.47, "c3v3a": 1.3e-6 / 2.2e-6}  # DC-bias brackets (assumed: not read for the chosen parts)
LDO_K = (0.5, 1.0, 2.0)                # x the LDO model's fitted output inductance (powermodels.ldo, Figure 27 fit)

# DS13543 Rev 2: Table 97 (ADC12, single-ended, 14 bits, fs 2.5 Msps): IDDA 980 uA, IDDV (VREF+) 160 uA typ, each;
# Table 100 (ADC4, fs 2.5 Msps): IDDA 360 uA, IDDV 18 uA typ. Their sum is a bound on the current that starts with a
# scan window (the working point converts slower than 2.5 Msps).
I_ADC = 2 * (980e-6 + 160e-6) + 360e-6 + 18e-6
I_ADC_STATIC = 2e-3                    # A: the DC load assumed on +3V3A at the operating point (its value barely matters)
T_SCAN = 80e-6                         # s: the scan window of SPEC §6.3
T_STEP_SPEC = 7.3e-6                   # s: SPEC §6.3's step at t_settle 5 us (8 steps, a 59 us scan)
T_CONV = 1.45e-6                       # s: one step's conversions, 2 x 0.725 us (SPEC §6.3)
I_SLOT_STEP = 4 * 2.6e-3               # A: four TMAG5253 switched on (2.6 mA typ at 3.3 V, SBASAI5E; SPEC §6.3)
LSB_MID = 3.3 / 2 ** 13                # V per LSB of a mid-scale ratiometric input
LDL1117_COUT_MAX = 22e-6               # F nominal: the right edge of LDL1117 Figures 20-21 (stability plan)

# Pass bars for the chosen damping (proposals; SPEC §3.7 gives the reasons). Peaking of 3 dB lets a disturbance
# through at up to 1.4 x; 1 ohm is ten times the bead's own DC resistance and a fifth of the undamped worst case.
PEAK_DB_MAX = 3.0                      # |H| peaking with the leg at its nominal values, whole L bracket
PEAK_DB_MAX_DERATED = 6.0              # the same with the leg's capacitor at 47 % (DC bias)
Z_MAX = 1.0                            # ohm, peak |Z| at +3V3A, nominal leg, whole L bracket
BURST_PP_MAX = 3.0                     # LSB at mid-scale: VREF+ swing inside a scan window from the ADCs' own
                                       # current (I_ADC), nominal leg, whole L bracket


def contract_leg():
    """(net, R ohm, C F) of the damping leg the contract names (nets.VDDA_DAMPING), or None."""
    return getattr(design.load_nets(), "VDDA_DAMPING", None)


def options():
    """name -> network keyword arguments. 'leg' takes its values from the contract."""
    leg = contract_leg()
    opts = {"captured": dict(series=("bead",))}
    if leg is not None:
        opts["leg"] = dict(series=("bead",), leg=(leg[2], leg[1]))
    opts["r1"] = dict(series=("r", 1.0), extra_c=10e-6)
    opts["r2p2"] = dict(series=("r", 2.2), extra_c=10e-6)
    return opts


def network(series=("bead",), l_bead=0.5e-6, r_dc=R_BEAD_DC, c_a=None, leg=None, extra_c=0.0, ldo_k=1.0,
            leg_scale=1.0, probe=None, sources=()):
    """The +3V3A branch as SPICE text. series: ('bead',) or ('r', ohm). leg: (C F, R ohm) from +3V3A to GND.
    probe: a node that gets a 1 A AC current source (AC analysis). sources: extra lines (transient stimuli)."""
    b = design.board()
    c_a = b["c_3v3a"] if c_a is None else c_a
    lines = [
        "Vsys vsys 0 5.0",
        pm.ldo("U4", "vsys", "slot", 3.3, design.LDL1117["V_DROP_MAX"] / 1.2, l_eq=0.4e-6 * ldo_k),
        pm.cap("Cslot", "slot", b["c_3v3_slot"]),
    ]
    if series[0] == "bead":
        lines += [f"Lfb slot fbx {l_bead:.6g}", f"Rfb fbx a {r_dc:.6g}"]
    else:
        lines += [f"Rfb slot a {series[1]:.6g}"]
    lines += [pm.cap("Ca", "a", c_a)]
    if extra_c:
        lines += [pm.cap("Cx", "a", extra_c)]
    if leg:
        c_leg, r_leg = leg
        lines += [f"Rd a dd {r_leg:.6g}", f"Cd dd 0 {c_leg * leg_scale:.6g}"]
    lines += [f"Radc a 0 {3.3 / I_ADC_STATIC:.6g}"]
    if probe:
        lines += [f"Iprobe 0 {probe} DC 0 AC 1"]
    lines += list(sources)
    return "\n".join(lines)


def ac(**kw):
    """H(f) = V(+3V3A)/V(+3V3_SLOT) and Z(f) at +3V3A, 1 kHz to 10 MHz. Returns a dict of curves and figures."""
    an = "ac dec 100 1k 10meg"
    w1 = spice.run(network(probe="slot", **kw), ["vr(a)", "vi(a)", "vr(slot)", "vi(slot)"], an)
    w2 = spice.run(network(probe="a", **kw), ["vr(a)", "vi(a)"], an)
    f = w1.scale
    h = (w1["vr(a)"] + 1j * w1["vi(a)"]) / (w1["vr(slot)"] + 1j * w1["vi(slot)"])
    z = w2["vr(a)"] + 1j * w2["vi(a)"]
    ih, iz = int(np.argmax(np.abs(h))), int(np.argmax(np.abs(z)))
    at = {fs: complex(np.interp(fs, f, h.real) + 1j * np.interp(fs, f, h.imag)) for fs in F_SCAN}
    return {"f": f, "H": h, "Z": z, "peak_db": float(20 * np.log10(np.abs(h[ih]))), "f_peak": float(f[ih]),
            "z_peak": float(np.abs(z[iz])), "f_zpeak": float(f[iz]), "z_dc": float(np.abs(z[0])),
            "h_scan": {fs: abs(v) for fs, v in at.items()}}


def _ipwl(name, node, points):
    """A PWL current source drawing from `node` to GND ([(t, A), ...]; repeated times nudged by 1 ps)."""
    return spice.pwl(points, name, kind="I").replace(f"I{name} {name} 0 ", f"I{name} {node} 0 ", 1)


def _tran(sources, t_stop, **kw):
    w = spice.run(network(sources=sources, **kw), ["v(a)", "v(slot)"], f"tran 20n {t_stop:.6g} 0 20n")
    return w


def adc_burst(t0=50e-6, **kw):
    """The ADCs draw I_ADC for one scan window. Returns the VREF+ swing inside the window after its first 2 us (what
    the lanes converted early and late disagree on), the shift at the window's end, and the waves."""
    src = [_ipwl("adc", "a", [(0, 0), (t0, 0), (t0 + 20e-9, I_ADC), (t0 + T_SCAN, I_ADC), (t0 + T_SCAN + 20e-9, 0)])]
    w = _tran(src, t0 + T_SCAN + 60e-6, **kw)
    t, va = w.scale, w["v(a)"]
    v0 = float(np.interp(t0 - 1e-6, t, va))
    win = (t >= t0 + 2e-6) & (t <= t0 + T_SCAN)
    return {"pp_lsb": float(np.ptp(va[win])) / LSB_MID, "shift_lsb": float(v0 - np.interp(t0 + T_SCAN, t, va)) / LSB_MID,
            "peak_lsb": float(np.max(np.abs(va[t >= t0] - v0))) / LSB_MID, "waves": w, "t0": t0, "v0": v0}


def adc_steps(t_step=T_STEP_SPEC, frames=4, **kw):
    """One slot's scan as SPEC §6.3 times it: eight select steps of t_step at the start of each 125 us frame, each
    ending in its conversions (T_CONV, then t_dma 0.4 us), during which the ADCs draw I_ADC. Returns the VREF+ swing
    across the last frame's sampling instants (the end of each conversion's 12-cycle sampling time, 0.3 us into
    each 0.725 us conversion) in LSB at mid-scale, and its mean shift from the idle level."""
    pts, t, samples = [(0.0, 0.0)], 20e-6, []
    for _ in range(frames):
        for k in range(8):
            a = t + (k + 1) * t_step - 0.4e-6 - T_CONV
            pts += [(a, 0.0), (a + 20e-9, I_ADC), (a + T_CONV, I_ADC), (a + T_CONV + 20e-9, 0.0)]
            samples += [a + 0.3e-6, a + 0.725e-6 + 0.3e-6]
        t += 125e-6
    src = [_ipwl("adc", "a", pts)]
    w = _tran(src, t + 10e-6, **kw)
    va = np.interp(samples[-16:], w.scale, w["v(a)"])
    v0 = float(np.interp(19e-6, w.scale, w["v(a)"]))
    return {"pp_lsb": float(np.ptp(va)) / LSB_MID, "shift_lsb": float(v0 - np.mean(va)) / LSB_MID, "waves": w,
            "t_step": t_step}


def slot_step(t0=50e-6, **kw):
    """Another slot's sensors switch on: I_SLOT_STEP on +3V3_SLOT. Returns the peak VREF+ excursion and the peak
    mismatch between +3V3_SLOT (the sensors' supply) and +3V3A (the reference), in LSB at mid-scale."""
    src = [_ipwl("slot", "slot", [(0, 0), (t0, 0), (t0 + 50e-9, I_SLOT_STEP)])]
    w = _tran(src, t0 + 150e-6, **kw)
    t, va, vs = w.scale, w["v(a)"], w["v(slot)"]
    m = t >= t0
    va0, vs0 = float(np.interp(t0 - 1e-6, t, va)), float(np.interp(t0 - 1e-6, t, vs))
    da, ds = va[m] - va0, vs[m] - vs0
    return {"vref_peak_lsb": float(np.max(np.abs(da))) / LSB_MID,
            "mismatch_peak_lsb": float(np.max(np.abs(da - ds))) / LSB_MID, "waves": w, "t0": t0}


def ldo_cout_nominal(opt):
    """Nominal capacitance on the LDL1117's output with an option fitted (the leg counted in full, a bound)."""
    b = design.board()
    kw = options()[opt]
    c = b["c_3v3_slot"] + b["c_3v3a"] + kw.get("extra_c", 0.0)
    if kw.get("leg"):
        c += kw["leg"][0]
    return c


def compare():
    """{option: {L or None: ac dict}} over the L bracket (the resistor options have no L)."""
    out = {}
    for name, kw in options().items():
        ls = L_BEAD if kw["series"][0] == "bead" else (None,)
        out[name] = {l: ac(**kw, **({"l_bead": l} if l else {})) for l in ls}
    return out


def bracket(opt="leg", leg_scale=1.0):
    """Worst peaking and |Z| of an option over L, the LDO's inductance and the +3V3A capacitors' derating."""
    kw = options()[opt]
    worst = {"peak_db": -99.0, "z_peak": 0.0}
    b = design.board()
    for l in L_BEAD:
        for k in LDO_K:
            for ca in (b["c_3v3a"], b["c_3v3a"] * C_DERATE["c3v3a"]):
                r = ac(**kw, l_bead=l, ldo_k=k, c_a=ca, leg_scale=leg_scale)
                if r["peak_db"] > worst["peak_db"]:
                    worst.update(peak_db=r["peak_db"], at_peak=(l, k, ca))
                if r["z_peak"] > worst["z_peak"]:
                    worst.update(z_peak=r["z_peak"], at_z=(l, k, ca))
    return worst


def run_all():
    r = {"compare": compare()}
    for name, kw in options().items():
        ls = (0.1e-6, 0.5e-6, 2e-6) if kw["series"][0] == "bead" else (None,)
        for l in ls:
            extra = {"l_bead": l} if l else {}
            tag = f"{name}_{l * 1e6:g}uH" if l else name
            r[f"burst_{tag}"] = adc_burst(**kw, **extra)
            r[f"steps_{tag}"] = adc_steps(**kw, **extra)
            r[f"steps3_{tag}"] = adc_steps(t_step=3.3e-6, **kw, **extra)
            r[f"slot_{tag}"] = slot_step(**kw, **extra)
    if "leg" in options():
        r["burst_leg_bracket"] = max(adc_burst(**options()["leg"], l_bead=l)["pp_lsb"] for l in L_BEAD)
        r["bracket_leg"] = bracket("leg")
        r["bracket_leg_derated"] = bracket("leg", leg_scale=C_DERATE["leg"])
    r["bracket_captured"] = bracket("captured")
    return r
