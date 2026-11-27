"""Plots of the benches' results (PNG, for the README). Every figure says what it simulates and that it is not a
measurement.

Style: one axis per panel (stacked panels share time instead of a second y-axis), at most three series per panel
in a fixed categorical order, thresholds as labelled grey dashes, recessive grid.
"""

import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

import design  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plots")
C = ["#257de0", "#f47230", "#00b894"]           # categorical slots 1-3 (blue, orange, aqua)
INK, INK2, GRID, REF = "#191919", "#666666", "#e6e6e6", "#8a8a8a"
NOTE = "Simulation of datasheet-based models (ngspice); not a measurement."

plt.rcParams.update({
    "font.size": 10.5, "axes.titlesize": 11.5, "axes.labelsize": 10.5, "axes.edgecolor": INK2,
    "axes.labelcolor": INK, "xtick.color": INK2, "ytick.color": INK2, "text.color": INK,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.spines.top": False,
    "axes.spines.right": False, "lines.linewidth": 2.0, "legend.frameon": False, "figure.dpi": 110,
    "savefig.dpi": 150, "savefig.bbox": "tight", "savefig.facecolor": "white",
})


def _title(ax, text):
    """The panel title, with the not-a-measurement note as a subtitle under it."""
    ax.set_title(text, loc="left", pad=20)
    ax.text(0, 1.015, NOTE, transform=ax.transAxes, fontsize=8.5, color=INK2, ha="left", va="bottom")


def _suptitle(fig, text):
    """A figure title above the panels and the note under it, placed in points so they never overlap."""
    from matplotlib.transforms import offset_copy
    fig.text(0.01, 1.0, text, transform=offset_copy(fig.transFigure, fig=fig, y=16, units="points"),
             fontsize=11.5, ha="left", va="bottom")
    fig.text(0.01, 1.0, NOTE, transform=offset_copy(fig.transFigure, fig=fig, y=3, units="points"),
             fontsize=8.5, color=INK2, ha="left", va="bottom")


def _save(fig, name):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name)
    fig.savefig(path)
    plt.close(fig)
    return path


def _hline(ax, y, label, xpos=0.99, va="bottom"):
    ax.axhline(y, color=REF, lw=1.2, ls="--", zorder=1)
    ax.annotate(label, xy=(xpos, y), xycoords=("axes fraction", "data"), ha="right", va=va, fontsize=9,
                color=INK2, xytext=(0, 2 if va == "bottom" else -2), textcoords="offset points")


def _vline(ax, x, label, ypos=0.98):
    ax.axvline(x, color=REF, lw=1.2, ls=":", zorder=1)
    ax.annotate(label, xy=(x, ypos), xycoords=("data", "axes fraction"), ha="left", va="top", fontsize=9,
                color=INK2, xytext=(3, 0), textcoords="offset points", rotation=90)


# ------------------------------------------------------------------------------------------------ lane
def lane_kickback(r):
    fig, ax = plt.subplots(figsize=(8.2, 4.6))
    series = [("kick_stiff_1n_fast", "TMAG5253, SPEC's assumption (5 pF, 7 ns switch)"),
              ("kick_stiff_1n_T97", "TMAG5253, T97 (5 pF behind Table 98's 22 ns)"),
              ("kick_r1k_1n_T97", "1 kΩ source, T97")]
    for (key, label), col in zip(series, C):
        d = r[key]
        t, e = d["t"], np.abs(d["err"]) / design.LSB14
        m = t > 5e-9
        ax.plot(t[m] * 1e6, np.maximum(e[m], 1e-3), color=col, label=label)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(0.05, 15)
    ax.set_ylim(1e-2, 1e5)
    _hline(ax, 0.5, "½ LSB (14 bit)", xpos=0.995)
    f = design.ADC["f_ADC"]
    for n in (12, 20, 391):
        _vline(ax, n / f * 1e6, f"{n} cycles")
    ax.set_xlabel("Sampling time (µs, f_ADC 40 MHz)")
    ax.set_ylabel("Sample error at the end of sampling (LSB)")
    _title(ax, "Lane kickback: 47 Ω + 1 nF, worst residual on C_ADC (3.3 V step)")
    ax.legend(loc="upper right", bbox_to_anchor=(0.9, 0.82), fontsize=9, frameon=True, facecolor="white",
              edgecolor="none", framealpha=1.0)
    return _save(fig, "lane_kickback.png")


def lane_step(r):
    fig, ax = plt.subplots(figsize=(8.2, 4.6))
    series = [("step_stiff_1n", "TMAG5253 as specified (1.27 Ω, no limit)"),
              ("step_limited_1n", "TMAG5253 clamped at ±1 mA (its rated IO)"),
              ("step_r1k_1n_cc", "1 kΩ source + 190 pF on the coupon side")]
    for (key, label), col in zip(series, C):
        d = r[key]
        e = np.abs(d["err"]) / design.LSB14
        ax.plot(d["t"] * 1e6, np.maximum(e, 1e-2), color=col, label=label)
    ax.set_yscale("log")
    ax.set_xscale("log")
    ax.set_xlim(0.02, 40)
    ax.set_ylim(0.05, 3e6)
    _hline(ax, 0.5, "½ LSB", xpos=0.995)
    _vline(ax, 0.502, "SPEC t_RC, stiff", ypos=0.55)
    _vline(ax, 10.89, "SPEC t_RC, 1 kΩ", ypos=0.55)
    ax.set_xlabel("Time after the select step (µs)")
    ax.set_ylabel("Lane error at the MCU pin (LSB)")
    _title(ax, "Lane settling after a full-scale select step (0 → 3.3 V), 47 Ω + 1 nF")
    ax.legend(loc="upper right", fontsize=9.5)
    return _save(fig, "lane_step.png")


def lane_scan(r):
    fig, ax = plt.subplots(figsize=(8.2, 4.4))
    ts = r["smp_spec"]
    series = [("scan_stiff_ts_fast", f"TMAG5253, {ts} cycles, SPEC's 7 ns switch"),
              ("scan_stiff_ts", f"TMAG5253, {ts} cycles, T97 (5 pF, 4.5 kΩ)"),
              ("scan_stiff_20", "TMAG5253, 20 cycles, T97 (all < 0.05 LSB)")]
    width = 0.27
    for k, ((key, label), col) in enumerate(zip(series, C)):
        conv = r[key]["convs"]
        x = np.arange(len(conv)) + (k - 1) * width
        ax.bar(x, [c["err_lsb"] for c in conv], width=width * 0.9, color=col, label=label)
    ax.axhspan(-0.5, 0.5, color="#f2f2f2", zorder=0)
    ax.annotate("±½ LSB", xy=(0.995, 0.5), xycoords=("axes fraction", "data"), ha="right", va="bottom",
                fontsize=9, color=INK2)
    ax.axhline(0, color=INK2, lw=0.8)
    ax.set_xlabel("Conversion in the scan (8 steps × 4 lanes; ADC1: AN0, AN1; ADC2: AN2, AN3)")
    ax.set_ylabel("Conversion error (LSB)")
    _title(ax, "One slot's scan with SPEC §6.3's step timing, alternating 0.2 / 3.1 V lanes")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), fontsize=9.5, ncol=3)
    ax.set_xlim(-0.8, 32)
    ax.set_ylim(-1.0, 1.0)
    return _save(fig, "lane_scan.png")


# ------------------------------------------------------------------------------------------------ slot
def slot_enable(r):
    fig, axes = plt.subplots(2, 2, figsize=(10, 6.2), sharex="col")
    for col, rail in enumerate(("3v3", "5v")):
        ai, av = axes[0, col], axes[1, col]
        for (load, label), c in zip((("none", "bulk only"), ("r", "bulk + resistor at the rule"),
                                     ("cc", "bulk + constant current at the rule")), C):
            d = r[f"en_{rail}_{load}_min_nosoft"]
            w = d["waves"]
            t = (w.scale - d["t_en"]) * 1e3
            ai.plot(t, w["i(VUm)"] * 1e3, color=c, label=label)
            av.plot(t, w["v(cpn)"], color=c, label=label)
        d = r[f"en_{rail}_none_min_nosoft"]
        _hline(ai, d["i_os"] * 1e3, f"I_OS min {d['i_os'] * 1e3:.0f} mA")
        dg = design.TPS2553["deglitch"]
        for ax in (ai, av):
            ax.axvspan(dg[0] * 1e3, dg[2] * 1e3, color="#f2f2f2", zorder=0)
        ai.annotate("FAULT deglitch 3-11 ms", xy=(dg[0] * 1e3, 0.97), xycoords=("data", "axes fraction"),
                    ha="left", va="top", fontsize=9, color=INK2, xytext=(4, 0), textcoords="offset points")
        bulk = d["c_bulk"] * 1e6
        ai.set_title(f"{'+3V3' if rail == '3v3' else '+5V'}_Sn: TPS2553 at I_OS min, no soft start, "
                     f"{bulk:.0f} µF", loc="left", fontsize=10.5)
        ai.set_xlim(-0.5, 25)
        ai.set_ylabel("Switch current (mA)")
        av.set_ylabel("Coupon rail (V)")
        av.set_xlabel("Time after EN (ms)")
        av.set_xlim(-0.5, 25)
        ai.set_ylim(0, d["i_os"] * 1e3 * 1.45)
    axes[1, 0].legend(loc="lower right", fontsize=9)
    fig.tight_layout()
    _suptitle(fig, "Enabling a coupon at SPEC §4.9's bulk limit: time in current limit against the FAULT deglitch")
    return _save(fig, "slot_enable.png")


def slot_vdda(r):
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2), sharey=True)
    for ax, (key, title, span) in zip(axes, (("en_3v3_none_max_nosoft", "I_OS max, no soft start", 0.04),
                                             ("en_3v3_none_min_typsoft", "I_OS min, typical soft start", 1.5))):
        d = r[key]
        w = d["waves"]
        t = (w.scale - d["t_en"]) * 1e3
        m = (t > -0.05 * span) & (t < span)
        ax.plot(t[m] * 1e3, (w["v(vin)"][m] - d["slot_v0"]) * 1e3, color=C[0], label="+3V3_SLOT")
        ax.plot(t[m] * 1e3, (w["v(vdda)"][m] - d["vdda_v0"]) * 1e3, color=C[1], label="+3V3A (VDDA, VREF+)")
        ax.set_title(f"{title}: VDDA dips {d['vdda_dip'] * 1e3:.0f} mV", loc="left", fontsize=10.5)
        ax.set_xlabel("Time after a slot's EN_3V3 (µs)")
    axes[0].set_ylabel("Change from before EN (mV)")
    axes[0].legend(loc="lower right", fontsize=9.5)
    fig.tight_layout()
    _suptitle(fig, "Another slot's 3.3 V enable, seen on the ADC reference (47 µF coupon; FB1's inductance "
                   "assumed 0.5 µH)")
    return _save(fig, "slot_vdda.png")


def s5_droop(r):
    fig, ax = plt.subplots(figsize=(8.6, 4.6))
    series = [("s5_detents_typ", "1 A detents; 5.0 V source, 0.1 Ω cable"),
              ("s5_detents_worst", "1 A detents; 4.75 V, 0.25 Ω cable, R_ON max"),
              ("s5_rule_ceiling_worst", "2 A (the rule), board at 2.8 A; 4.75 V, 0.25 Ω")]
    for (key, label), col in zip(series, C):
        d = r[key]
        w = d["waves"]
        t = (w.scale - d["t_motor"]) * 1e3
        m = t > -1
        ax.plot(t[m], (w["v(cpn)"] - w["v(cpng)"])[m], color=col, label=label)
    _hline(ax, design.DRV8316["VM_MIN"], "DRV8316 VM min 4.5 V")
    _hline(ax, design.DRV8316["UVLO_FALL"][2], "DRV8316 UVLO falling max 4.3 V", va="top")
    ax.set_xlabel("Time from the motor profile's start (ms)")
    ax.set_ylabel("Haptics coupon supply (V)")
    _title(ax, "S5: supply at the coupon under motor current (motor not chosen; profiles assumed)")
    ax.legend(loc="lower right", fontsize=9.5)
    ax.set_ylim(3.4, 5.1)
    return _save(fig, "s5_droop.png")


def s5_breaker(r):
    fig, axes = plt.subplots(2, 1, figsize=(8.6, 6), sharex=True)
    series = [("s5_burst_short_min_itimer", "2.6 A for 0.9 × t_ITIMER min, shortest timer"),
              ("s5_burst_long_max_itimer", "2.6 A for 1.2 × t_ITIMER max, longest timer"),
              ("s5_rule_ilim_min_rtol", "2.0 A steady, I_LIM min with R_ILM at +1 %")]
    for (key, label), col in zip(series, C):
        d = r[key]
        w = d["waves"]
        t = (w.scale - d["t_motor"] - 1e-3) * 1e3
        m = (t > -0.5) & (t < 8)
        axes[0].plot(t[m], w["i(VU5m)"][m], color=col, label=label)
        axes[1].plot(t[m], w["v(U5_it)"][m], color=col, label=label)
    t5 = design.TPS25947
    _hline(axes[1], t5["V_INT"][1] - t5["dV_ITIMER"][1], "trip threshold (typ)", va="top")
    axes[0].set_ylabel("U5 current (A)")
    axes[1].set_ylabel("ITIMER pin (V)")
    axes[1].set_xlabel("Time from the overload's start (ms)")
    axes[0].legend(loc="upper right", fontsize=9)
    axes[0].set_ylim(0, 3.6)
    fig.tight_layout()
    _suptitle(fig, "S5's circuit breaker U5 (TPS259474L): blanking timer and latch-off")
    return _save(fig, "s5_breaker.png")


# ------------------------------------------------------------------------------------------------ input
def input_startup(r):
    fig, ax = plt.subplots(figsize=(8.2, 4.4))
    for c, col in zip(("min", "typ", "max"), C):
        d = r[f"startup_{c}"]
        w = d["waves"]
        ax.plot(w.scale * 1e3, w["v(v3v3)"], color=col,
                label=f"+3V3, I_dVdt {c} ({d['sr'] / 1e3:.2f} V/ms): {d['t_3v3_ramp'] * 1e3:.1f} ms to 3.0 V")
    _vline(ax, 25.0, "U_CC VDD ramp limit, 25 ms")
    _hline(ax, 3.0, "3.0 V (U_CC with 3.3 V I2C)", xpos=0.75, va="top")
    ax.set_xlabel("Time after VBUS is applied (ms)")
    ax.set_ylabel("+3V3 (V)")
    ax.set_xlim(0, 30)
    _title(ax, "Start-up through U2's dV/dt soft start (C_dVdt 2.2 nF)")
    ax.legend(loc="lower right", fontsize=9.5)
    return _save(fig, "input_startup.png")


def input_ceiling(r, th):
    fig, axes = plt.subplots(2, 1, figsize=(8.6, 6.4), sharex=True)
    keys = sorted(k for k in r if k.startswith("ceiling_") and not k.startswith("ceiling_5v0"))
    for key, col in zip(keys, C):
        d = r[key]
        w = d["waves"]
        t = (w.scale - d["t_step"]) * 1e3
        m = t > -2
        axes[0].plot(t[m], w["v(vbus)"][m], color=col, label=f"{d['r_cable']:.2f} Ω round trip")
        axes[1].plot(t[m], w["v(vsys)"][m], color=col, label=f"{d['r_cable']:.2f} Ω round trip")
    _hline(axes[0], th["uvlo_fall"][2], f"U2 UVLO falling, max with 1 % divider ({th['uvlo_fall'][2]:.2f} V)", va="top")
    _hline(axes[0], th["ucc_vbus_thr"][2], f"U_CC VBUS_THR max ({th['ucc_vbus_thr'][2]:.1f} V)", xpos=0.6,
           va="top")
    _hline(axes[1], th["pg_fall"][2], f"VSYS_PG falling, max with 1 % divider ({th['pg_fall'][2]:.2f} V)")
    axes[0].set_ylabel("VBUS at J1 (V)")
    axes[1].set_ylabel("VSYS (V)")
    axes[1].set_xlabel("Time after the load steps to 2.8 A (ms)")
    axes[1].legend(loc="lower right", bbox_to_anchor=(1.0, 0.27), fontsize=9.5)
    axes[0].set_ylim(3.6, 5.1)
    axes[1].set_ylim(1.8, 5.1)
    fig.tight_layout()
    _suptitle(fig, "The 2.8 A ceiling from a 4.75 V source (R_ON max, highest thresholds)")
    return _save(fig, "input_ceiling.png")
