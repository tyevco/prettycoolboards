"""Behavioural SPICE models of the power parts, every parameter from a datasheet (design.py cites each).

The benches use these models, not vendor models. TI's TPS25947 PSpice model (SLVMDJ6A) is an encrypted library
(`**$ENCRYPTED_LIB`) that ngspice cannot read. TI's TPS2553 model (SLVM425B, "Unencrypted PSpice Transient Model
Package") is plain text but "All rights reserved", so it is not copied into this repository: vendor.py fetches it
from ti.com into a local cache and uses it only to cross-check the `tps2553` model below (tests/test_vendor.py).
The models below are written from the datasheets' tables and equations, and they model only what the benches
need:

* `tps2553`   a soft-start ramp (the datasheet's 10-90 % rise time, or none: no minimum is specified), a
              constant-current limit at I_OS, and R_DS(on). The FAULT deglitch and the thermal cycling are judged
              after the run from the time spent in current limit; they do not act on the circuit.
* `tps259474` the TPS259474L circuit breaker: EN/UVLO with hysteresis (as a divider from its input when given),
              a dV/dt soft start set by C_dVdt and I_dVdt, active current limiting at I_LIM during start-up only,
              the ITIMER blanking timer (1.8 uA discharge above I_LIM, 15 kOhm pull-up to V_INT otherwise), the
              2 x I_LIM fast trip, latch-off, R_ON and true reverse-current blocking. Not modelled: thermal
              shutdown, OVLO, the PG deglitch, the I_LIM foldback below 1.9 V. The fast trip latches here at
              once; the datasheet (SLVSFC9C §7.3.5.4) turns the FET back on after 30 us "in a current limited
              manner" and, on a persistent fault, latches off only at thermal shutdown, so the model is
              optimistic about what a hard short costs the upstream breaker (tests/test_slot.py names the case).
* `ldo`       a regulator with dropout (as a resistance) and an output impedance fitted to one load-transient
              figure (LDL1117 Figure 27); used for both LDOs. It does not model PSRR, noise or current limit
              foldback (the AP2112K folds back to 50 mA typ at VOUT = 0, which a start-up into a heavy load could
              meet; the bench's start-up loads stay well below it).
* `cable`     the round-trip resistance and a loop inductance in the VBUS lead, so that the board's GND is the
              reference and VBUS at J1 is what the board sees.

The smooth min/max and tanh steps keep the Newton solver away from corners; their widths (1 mA, 1 mV) are far
below every margin the benches report.
"""

EPS_I = 1e-3     # A, smoothing width of current mins
EPS_V = 1e-3     # V, smoothing width of voltage mins


def smin(a, b, eps):
    """Smooth min; eps is a number or, for a limit that moves, an expression."""
    e2 = f"{eps * eps:.6g}" if isinstance(eps, (int, float)) else f"({eps})*({eps})"
    return f"(({a})+({b})-sqrt((({a})-({b}))*(({a})-({b}))+{e2}))/2"


def smax(a, b, eps):
    return f"(({a})+({b})+sqrt((({a})-({b}))*(({a})-({b}))+{eps * eps:.6g}))/2"


def step(x, width):
    """0 -> 1 as x goes through 0, over about +/- 2 width."""
    return f"(0.5*(1+tanh(({x})/{width:.6g})))"


def tps2553(n, vin, vout, t_en, r_on, i_os, t_r, v_final, t_ios=2e-6):
    """TPS2553 from node vin to node vout, enabled at t_en. t_r = 10-90 % rise time (0: no soft start).

    The limit itself ramps from 0 to I_OS over t_ios after EN: the datasheet says the device "ramps the output
    current to IOS" when enabled into a short (SLVS841G §8.3.1) and responds within tIOS = 2 us typ; without the
    ramp the solver would see an infinite di/dt, which the LDO's and the ferrite's inductance turn into a spike.

    Nodes: {n}_ctl (the soft-start reference), {n}_ilim (the limit), and the current through V{n}m."""
    sr = 1e9 if t_r <= 0 else 0.8 * v_final / t_r
    t_full = t_en + (v_final + 1.0) / sr
    return "\n".join([
        f"V{n}ramp {n}_ramp 0 PWL(0 0 {t_en:.9g} 0 {t_full:.9g} {v_final + 1.0:.9g})",
        f"V{n}ilim {n}_ilim 0 PWL(0 0 {t_en:.9g} 0 {t_en + t_ios:.9g} {i_os:.9g})",
        f"B{n}ctl {n}_ctl 0 V = {smin(f'v({vin})', f'v({n}_ramp)', EPS_V)}",
        # the smoothing width follows the limit (0.2 % of it), so the limit can start from zero
        f"B{n}sw {vin} {n}_o I = {smin(f'v({n}_ilim)', f'(v({n}_ctl)-v({n}_o))/{r_on}', f'0.002*v({n}_ilim)+1e-7')}",
        f"V{n}m {n}_o {vout} 0",
        f"C{n}o {n}_o 0 10p",
    ])


def tps259474(n, vin, vout, t_en, r_on, i_lim, sr, c_itimer, i_itimer, dv_itimer, v_int=2.57, r_itimer=15e3,
              isc_gain=2.01, uvlo=None, latch=True):
    """TPS259474L from vin to vout. sr = output slew rate in V/s (Eq. 4 with the chosen I_dVdt).

    uvlo = (ratio, v_rise, v_fall): an EN/UVLO divider from vin with that ratio; None: EN driven at t_en only.
    Nodes for the record: {n}_ena (enabled, 0/1), {n}_ss (soft-start reference), {n}_it (ITIMER), {n}_trip
    (latched trip, 0/1); the pass current is i(V{n}m)."""
    t_en = max(t_en, 1e-9)
    lines = [f"V{n}en {n}_enpin 0 PWL(0 0 {t_en:.9g} 0 {t_en + 1e-6:.9g} 1)"]
    if uvlo:
        ratio, vr, vf = uvlo
        lines += [
            f"E{n}uv {n}_uv 0 {vin} 0 {ratio:.9g}",
            f"S{n}uv {n}_enpin {n}_ena {n}_uv 0 sw_{n}_uvlo",
            # 10 Ohm on, 1 kOhm off, 10 nF: EN settles in 0.1 us on and 10 us off, never in one solver step
            f"R{n}ena {n}_ena 0 1e3",
            f"C{n}ena {n}_ena 0 10n",
            f".model sw_{n}_uvlo SW(VT={(vr + vf) / 2:.6g} VH={(vr - vf) / 2:.6g} RON=10 ROFF=1e12)",
        ]
    else:
        lines.append(f"R{n}ena {n}_enpin {n}_ena 1")
        lines.append(f"R{n}ena2 {n}_ena 0 1e6")
        lines.append(f"C{n}ena {n}_ena 0 1u")
    gate = f"({step(f'v({n}_ena)-0.5', 0.02)}*(1-{step(f'v({n}_trip)-0.5', 0.02)}))"
    startup = step(f"v({vin})-0.05-v({n}_ss)", 0.01)
    x = f"(({smin(f'v({n}_ss)', f'v({vin})', EPS_V)})-v({n}_o))/{r_on}"
    lines += [
        # soft start: charges at sr while enabled and not tripped, stops 0.2 V above the input, else discharges
        f"C{n}ss {n}_ss 0 1n",
        f"R{n}ss {n}_ss 0 1e9",
        f"B{n}ss 0 {n}_ss I = {gate}*{sr * 1e-9:.6g}*(1-{step(f'v({n}_ss)-v({vin})-0.2', 0.02)})"
        f" - (1-{gate})*v({n}_ss)/1e3",
        # pass element: limited at I_LIM only during start-up; never reverse
        f"B{n}sw {vin} {n}_o I = {gate}*{smax(0, f'{startup}*{smin(i_lim, x, EPS_I)}+(1-{startup})*{x}', EPS_I)}",
        f"V{n}m {n}_o {vout} 0",
        f"C{n}o {n}_o 0 10p",
        f"R{n}bl {n}_o 0 1e6",
        # ITIMER: discharged at I_ITIMER while the current exceeds I_LIM after start-up, else pulled up to V_INT
        f"C{n}it {n}_it 0 {c_itimer:.6g} IC={v_int}",
        f"B{n}it 0 {n}_it I = -{i_itimer:.6g}*{step(f'i(V{n}m)-{i_lim}', 2e-3)}*(1-{startup})"
        f" + (1-{step(f'i(V{n}m)-{i_lim}', 2e-3)}*(1-{startup}))*({v_int}-v({n}_it))/{r_itimer}",
        # latched trip: the ITIMER has fallen by dV (tCB about 2 us) or the current is above 2 x I_LIM (tSC 0.5 us)
        f"C{n}tr {n}_trip 0 1n",
        f"R{n}tr {n}_trip 0 1e12",
        f"B{n}tr 0 {n}_trip I = (0.25m*{step(f'{v_int - dv_itimer}-v({n}_it)', 0.005)}"
        f" + 1m*{step(f'i(V{n}m)-{isc_gain * i_lim}', 5e-3)}"
        f" + 1m*{step(f'v({n}_trip)-0.3', 0.02)})*(1-{step(f'v({n}_trip)-1', 0.05)})",   # regenerative: it latches
    ]
    if not latch:
        lines.append(f"R{n}trd {n}_trip 0 1e5")
    return "\n".join(lines)


def ldo(n, vin, vout, v_set, r_drop, l_eq=0.4e-6, r_d=0.15, r_o=0.004):
    """An LDO from vin to vout: V = min(v_set, vin - I x r_drop), then (l_eq || r_d) + r_o.

    l_eq and r_d default to the fit to LDL1117 Figure 27 (a 1 A step in 5 us dips 4.7 uF by about 75 mV)."""
    return "\n".join([
        # scaled by tanh(VIN / 0.3 V): zero at VIN = 0 (the smooth max would otherwise leave a millivolt tail that
        # biases VSYS at t = 0) and smooth, so the output follows the input up from 0 V and the output capacitors
        # charge at about the input's slew. An earlier version switched on in a step at VIN 0.5 V, which charged
        # them in a few tens of us and put a model-made spike (up to 0.27 A) into the start-up inrush. Below the
        # LDOs' minimum input neither datasheet says what the output does; this is an assumption.
        f"B{n}int {n}_int 0 V = {smax(0, smin(v_set, f'v({vin})-i(V{n}m)*{r_drop}', EPS_V), EPS_V)}"
        f"*tanh({smax(0, f'v({vin})', 0.01)}/0.3)",
        f"L{n}eq {n}_int {n}_x {l_eq}",
        f"R{n}d {n}_int {n}_x {r_d}",
        f"R{n}o {n}_x {n}_m {r_o}",
        f"V{n}m {n}_m {vout} 0",
        # the pass device's input current mirrors the output current
        f"B{n}in {vin} 0 I = i(V{n}m)",
    ])


def cable(n, src, vbus, r_round_trip, l_loop):
    """The USB cable: its round-trip resistance and loop inductance, both in the VBUS lead."""
    return "\n".join([f"R{n}c {src} {n}_x {r_round_trip:.6g}", f"L{n}c {n}_x {vbus} {l_loop:.6g}"])


def cap(n, node, c, esr=0.005, ref="0"):
    return f"C{n} {node} {n}_esr {c:.6g}\nR{n}esr {n}_esr {ref} {esr:.6g}"
