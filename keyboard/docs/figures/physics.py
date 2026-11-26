#!/usr/bin/env python3
"""Model-estimate figures for the keyboard concept: the sensing and haptics physics, as 2D matplotlib plots.

STATUS: CONCEPT. Nothing in keyboard/ is designed, built or measured (keyboard/docs/concept.md). Every figure here is
computed from a simple, stated model with illustrative parameters. Each one is a MODEL ESTIMATE, NOT A MEASUREMENT,
and each image says so. The geometry is the illustrative geometry of the concept renders
(keyboard/hardware/concept/mechanism_models.py), not a design, and the parts are the candidates concept.md names.
The rev A testbed (concept.md section 7) is where real numbers come from.

Run from the repo root (the interpreter needs numpy, scipy, matplotlib and Pillow):

    PY=/path/to/venv/bin/python
    $PY keyboard/docs/figures/physics.py                  # all six figures
    $PY keyboard/docs/figures/physics.py he shear         # a subset: he, neighbour, shear, coil, haptic, latency

It writes keyboard/docs/figures/phys_*.png and prints the model cross-checks. It runs in a few seconds.

The figures and their models
----------------------------

phys_he_field_vs_travel.png: field at a Hall sensor under a switch magnet, against key travel.
    Model: the exact on-axis field of a uniformly, axially magnetised cylinder (radius R, length L, remanence Br)
    at a distance z from its near face:
        Bz(z) = Br/2 * [ (z + L) / sqrt((z + L)^2 + R^2)  -  z / sqrt(z^2 + R^2) ]
    and its derivative dBz/dz = Br/2 * [ R^2 / ((z + L)^2 + R^2)^1.5  -  R^2 / (z^2 + R^2)^1.5 ].
    Assumptions: a point sensor on the magnet's axis; relative permeability 1 (NdFeB is about 1.05); no steel,
    no neighbouring magnets, no stray field; 20 C (NdFeB loses about 0.1 % of Br per kelvin).
    Parameters (illustrative): Br = 1.25 T (about N38-N40 grade); magnet A diameter 4 mm x 2 mm (the size in the
    concept renders), magnet B diameter 3 mm x 3 mm; 6.3 mm from the magnet face to the Hall element at rest
    (magnet face 6.9 mm above the PCB as in the concept render, element about 0.6 mm above the PCB); 4.0 mm of
    travel to the hard stop, then 0.5 mm of compliant zone (the concept's 0.2-0.5 mm aftertouch idea).
    Sensor ranges drawn: about +/-40, +/-80 and +/-160 mT, taken as the full-scale options of TMAG5253 variants.
    They are not checked against the datasheet here: check the datasheet.

phys_he_neighbour_field.png: the field a Hall key's sensor picks up from its neighbours' magnets.
    Model: the Biot-Savart sheet-current model below (exact off-axis), superposed: the sensor reads its own
    magnet's field plus each neighbour's. Same magnet A, Br and gaps as above; neighbours at the MX pitch of
    19.05 mm (row or column), 26.9 mm (diagonal) and 38.1 mm (two keys away), all magnetised the same way up.
    The equivalent travel error divides a neighbour's field change by this key's own gradient dBz/dtravel.
    Not modelled: steel (a steel plate or case would change this a lot), the stem and housing, tolerances. Earth's
    field (about 0.025-0.065 mT in total, depending on location) is drawn for scale only.

phys_shear_field.png: lateral field at a 3-axis sensor under a shear key's magnet.
    Model: the magnet is replaced by its equivalent surface current. A uniform axial magnetisation M = Br/mu0 is
    equivalent to an azimuthal sheet current K = M on the side wall (the end faces carry none). The field at the
    sensor is the Biot-Savart sum over that sheet: 48 Gauss-Legendre loops along the height times 256 segments
    per loop. Cross-checks printed on every run: the on-axis Bz against the exact formula above, and the small-offset
    slope dBx/ds against the near-axis expansion B_rho = -(rho/2) dBz/dz.
    Assumptions: as above, plus a point sensor at the element position, the magnet moved rigidly by the press
    (depth d) and the lateral push (offset s, along x), with no tilt.
    Parameters (illustrative): Br = 1.25 T, magnet diameter 4 mm x 2 mm, 6.5 mm from the magnet face to the element
    at rest (the concept render's shear key), press depth 0-4 mm, lateral offset +/-0.5 mm (concept 2.1 says about
    +/-0.3-0.5 mm). The sensor is the candidate TMAG5170.

phys_coil_inductance.png: planar spiral inductance against turns.
    Model: the modified Wheeler expression (Mohan, del Mar Hershenson, Boyd and Lee, IEEE JSSC 34(10), 1999):
        L1 = K1 * mu0 * n^2 * d_avg / (1 + K2 * rho),  d_avg = (d_out + d_in) / 2,
        rho = (d_out - d_in) / (d_out + d_in),  d_in = d_out - 2 n w - 2 (n - 1) s
    with the octagonal coefficients K1 = 2.25, K2 = 3.55 standing in for a round spiral. A series stack of N equal
    layers with one coupling factor k between every pair of layers is L = N * L1 * (1 + (N - 1) k).
    Assumption, rough: k = 0.7, with a band from 0.45 to 0.9. A concentric-loop estimate (Maxwell's mutual
    inductance of coaxial loops, printed on every run) gives about 0.85-0.9 for layers 0.2 mm apart (a 4-layer
    board's outer pair) and 0.4-0.6 for layers 1.5 mm apart (the two sides of a 1.6 mm board). The same loop model
    also checks the single-layer Wheeler figure (within about 5 %).
    Assumptions: a lone coil in free space, no switch spring or slug above it, no ground copper, no keep-outs for
    the switch's pins (a stock MX switch's pins sit inside a 10-14 mm coil, so a real layout must route around
    them), DC inductance (no skin or proximity effect, no self-resonance).
    Parameters (illustrative): trace and space 0.127 mm each, outer diameters 10, 12 and 14 mm, inner diameter
    kept at 4.5 mm or more to clear the MX centre-post hole, 1, 2 and 4 layers.

phys_haptic_profiles.png: the thumb wheel's detent profiles as torque against angle.
    These are firmware tables, not physics: illustrative profiles of the kind concept 2.3 describes (per-line
    ticks, hard end stops at 0 and 100, N slots, free spin). The torque axis is a fraction of the profile's full
    scale. The real torque depends on the motor (cogging, torque constant), the driver's current limit and the FOC
    tuning, none of which is chosen or tested.
    Profiles: ticks every 12 degrees at 0.35 of full scale (a sine); 0 to 100 over 270 degrees with light ticks every
    10 units and end walls that reach full scale within 4 degrees; 8 slots of 45 degrees, each a spring that
    saturates at 0.8 of full scale 8 degrees from the slot and snaps over at the midpoint (blended over 1 degree);
    free spin with a damping torque of 0.03 of full scale per rev/s.

phys_polling_latency.png: the wait that scanning and reporting add, at 1 kHz and 8 kHz.
    Arithmetic, not a measurement: a press at a uniformly random time waits for the next scan, then for the next
    report. The wait for a periodic event of interval T is uniform on [0, T), with mean T/2. So:
        locked scan (the scan runs just before each report): mean T/2 = 0.5 ms at 1 kHz, 0.0625 ms at 8 kHz;
        free-running scan (scan and report phases unrelated): mean T/2 + T/2 = 1.0 ms and 0.125 ms.
    Percentiles: a uniform wait has p50 = T/2 and p99 = 0.99 T; the sum of two (a triangle on [0, 2T)) has
    p50 = T and p99 = (2 - sqrt(0.02)) T. The curves are sampled (200 000 presses, fixed seed) and the samples are
    checked against these values. Not included: sensor settling and conversion, the firmware's own processing,
    the USB host stack, the OS and the display. 8 kHz reports need high-speed USB (125 us microframes); a
    full-speed device is polled at most every 1 ms.
"""
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt                                     # noqa: E402
import numpy as np                                                  # noqa: E402
from matplotlib.patches import FancyArrowPatch, Rectangle           # noqa: E402
from matplotlib.ticker import FuncFormatter                         # noqa: E402
from scipy.special import ellipe, ellipk                            # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
MU0 = 4e-7 * np.pi

# ---------------------------------------------------------------------------------------------------------------
# Style: one quiet palette for every figure (categorical slots 1-3 and the blue ramp of the dataviz reference
# palette; text in ink colours, never in a series colour)
# ---------------------------------------------------------------------------------------------------------------
INK = "#191919"
INK2 = "#666666"
GRID = "#e7e7e7"
AXIS = "#c2c2c2"
C1, C2, C3 = "#257de0", "#f47230", "#00b894"        # blue, orange, aqua
RAMP = ["#84b9f3", "#519ced", "#2370cd", "#1757ac", "#0e3d7e"]   # light -> dark, for an ordered parameter
SHADE = "#f2f2f2"
STAMP_RED = "#8c1a1a"
DPI = 150
NOTE_LINE_IN = 0.168          # height of one note line (8 pt, line spacing 1.5), inches

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 9,
    "axes.labelsize": 9.5,
    "axes.labelcolor": INK2,
    "axes.titlesize": 10.5,
    "axes.titlecolor": INK,
    "xtick.color": INK2,
    "ytick.color": INK2,
    "xtick.labelsize": 8.5,
    "ytick.labelsize": 8.5,
    "legend.fontsize": 8.5,
    "legend.frameon": False,
    "lines.solid_capstyle": "round",
    "lines.solid_joinstyle": "round",
})
BOX = dict(boxstyle="square,pad=0.15", fc="white", ec="none")     # behind text that sits on gridlines
LEAD = dict(arrowstyle="-", lw=0.6, color=INK2)                    # leader line from a label to its mark


def style(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(AXIS)
        ax.spines[s].set_linewidth(0.8)
    ax.tick_params(length=3, width=0.6)
    ax.grid(True, color=GRID, lw=0.6)
    ax.set_axisbelow(True)


def panel_title(ax, text):
    ax.set_title(text, loc="left", pad=8, fontsize=10.5, color=INK)


def margins(fig, note_lines):
    """gridspec top and bottom (figure fractions) that leave room for the title block and the note."""
    w, h = fig.get_size_inches()
    return 1 - 1.12 / h, (0.36 + note_lines * NOTE_LINE_IN + 0.72) / h


def frame(fig, title, subtitle, note, stamp):
    """Title and subtitle above the plots, the model note below them, and the status stamp on its own line at the
    bottom right. Positions are in inches from the figure edges so they hold for any figure size."""
    w, h = fig.get_size_inches()
    fig.text(0.18 / w, 1 - 0.16 / h, title, ha="left", va="top", fontsize=14, color=INK, weight="bold")
    fig.text(0.18 / w, 1 - 0.47 / h, subtitle, ha="left", va="top", fontsize=9.5, color=INK2)
    fig.text(0.18 / w, 0.34 / h, note, ha="left", va="bottom", fontsize=8, color=INK2, linespacing=1.5)
    fig.text(1 - 0.12 / w, 0.08 / h, stamp, ha="right", va="bottom", fontsize=8.5, color=STAMP_RED,
             weight="bold")


def dot(ax, x, y, colour, size=6.5, z=5):
    """End-dot / marker: filled with the series colour, with a ring in the surface colour."""
    ax.plot(x, y, "o", ms=size, mfc=colour, mec="white", mew=1.6, zorder=z, clip_on=False)


def plain_log(ax, axis="y"):
    fmt = FuncFormatter(lambda v, _: f"{v:g}")
    (ax.yaxis if axis == "y" else ax.xaxis).set_major_formatter(fmt)


def save(fig, name):
    """Write the PNG, then store it as a 256-colour palette image (flat colours and anti-aliased lines survive this
    unchanged to the eye, at about half the size)."""
    from PIL import Image
    path = os.path.join(HERE, name)
    fig.savefig(path, dpi=DPI, facecolor="white")
    plt.close(fig)
    im = Image.open(path).convert("RGB").quantize(colors=256, method=Image.Quantize.MEDIANCUT,
                                                  dither=Image.Dither.NONE)
    im.save(path, optimize=True)
    kb = os.path.getsize(path) / 1024
    print(f"  wrote {path}  ({kb:.0f} KB)")
    return path


MODEL_STAMP = "MODEL ESTIMATE: simple model, not measured"

# ---------------------------------------------------------------------------------------------------------------
# Magnet field models
# ---------------------------------------------------------------------------------------------------------------
BR = 1.25            # T, remanence (about N38-N40)


def bz_axis(z, R, L, Br=BR):
    """Exact on-axis field (T) of an axially magnetised cylinder, z (mm) from the near face."""
    return Br / 2 * ((z + L) / np.hypot(z + L, R) - z / np.hypot(z, R))


def dbz_dz_axis(z, R, L, Br=BR):
    """d Bz / dz on the axis (T per mm); negative: the field falls with distance."""
    return Br / 2 * (R ** 2 / ((z + L) ** 2 + R ** 2) ** 1.5 - R ** 2 / (z ** 2 + R ** 2) ** 1.5)


def sheet_field(pts, R, L, Br=BR, nz=48, nphi=256):
    """B (T) at points pts (P, 3) in mm, for a cylinder with its axis on z, faces at z = 0 and z = L, magnetised +z.
    Biot-Savart over the equivalent side-wall sheet current K = Br / mu0 (so mu0 K = Br and, with all lengths in mm,
    B = Br / (4 pi) * sum(w dz  dl x r / |r|^3) comes out in tesla)."""
    t, w = np.polynomial.legendre.leggauss(nz)
    zk, wk = (t + 1) * L / 2, w * L / 2
    phi = (np.arange(nphi) + 0.5) * 2 * np.pi / nphi
    c, s = np.cos(phi), np.sin(phi)
    src = np.stack([np.broadcast_to(R * c, (nz, nphi)), np.broadcast_to(R * s, (nz, nphi)),
                    np.broadcast_to(zk[:, None], (nz, nphi))], -1).reshape(-1, 3)
    dl = (np.stack([-s, c, np.zeros_like(c)], -1) * R * 2 * np.pi / nphi)[None, :, :] * wk[:, None, None]
    dl = dl.reshape(-1, 3)
    pts = np.atleast_2d(pts)
    out = np.zeros((len(pts), 3))
    for i in range(0, len(pts), 32):
        r = pts[i:i + 32, None, :] - src[None, :, :]
        r3 = np.linalg.norm(r, axis=-1, keepdims=True) ** 3
        out[i:i + 32] = (np.cross(np.broadcast_to(dl, r.shape), r) / r3).sum(1)
    return out * Br / (4 * np.pi)


# ---------------------------------------------------------------------------------------------------------------
# (1) Hall-effect key: Bz against travel
# ---------------------------------------------------------------------------------------------------------------
HE_GAP_REST = 6.3     # mm, magnet face to Hall element at rest (illustrative)
HE_TRAVEL = 4.0       # mm to the hard stop
HE_SQUASH = 0.5       # mm of compliant zone past the hard stop
HE_R, HE_L = 2.0, 2.0  # magnet A
HE_MAGNETS = [  # label, radius, length, colour
    ("Magnet A: ø4 × 2 mm (as in the concept renders)", HE_R, HE_L, C1),
    ("Magnet B: ø3 × 3 mm", 1.5, 3.0, C2),
]
HE_RANGES = (40, 80, 160)     # mT, TMAG5253 variants: check the datasheet


def fig_he_field():
    x = np.linspace(0, HE_TRAVEL + HE_SQUASH, 901)
    fig = plt.figure(figsize=(12, 6.5))
    top, bottom = margins(fig, 4)
    gs = fig.add_gridspec(1, 2, left=0.058, right=0.985, top=top, bottom=bottom, wspace=0.2)
    axa, axb = fig.add_subplot(gs[0]), fig.add_subplot(gs[1])
    for ax in (axa, axb):
        style(ax)
        ax.axvspan(HE_TRAVEL, HE_TRAVEL + HE_SQUASH, color=SHADE, lw=0, zorder=0)
        ax.axvline(HE_TRAVEL, color=AXIS, lw=0.9, zorder=1)
        ax.set_xlim(0, HE_TRAVEL + HE_SQUASH)
        ax.set_xlabel("key travel from rest (mm)")
        ax.set_xticks(np.arange(0, 4.51, 0.5))

    # sensor ranges (reference lines, labelled at the left, clear of the curves' steep end)
    for r in HE_RANGES:
        axa.axhline(r, color=INK2, lw=0.9, ls=(0, (5, 3)), zorder=1)
        axa.text(0.05, r + 2.0, f"±{r} mT range", fontsize=8, color=INK2, va="bottom")
    axa.text(0.05, 178, "Candidate full-scale ranges, TMAG5253 variants (check the datasheet)",
             fontsize=8, color=INK2, va="top", style="italic")

    summary = []
    for label, R, L, col in HE_MAGNETS:
        g = HE_GAP_REST - x
        B = bz_axis(g, R, L) * 1e3
        G = -dbz_dz_axis(g, R, L) * 1e3 * 0.01        # mT per 0.01 mm of travel
        axa.plot(x, B, color=col, lw=2.0, label=label, zorder=3)
        axb.plot(x, G, color=col, lw=2.0, label=label, zorder=3)
        for r in HE_RANGES:                           # where the curve leaves each range
            if B[-1] > r:
                dot(axa, np.interp(r, B, x), r, col, size=6)
        dot(axa, x[-1], B[-1], col, size=6)
        i_bo = np.argmin(abs(x - HE_TRAVEL))
        summary.append((label, B[0], B[i_bo], B[-1], G[0], G[i_bo], G[-1],
                        [np.interp(r, B, x) if B[-1] > r else None for r in HE_RANGES]))

    # annotations (magnet A, selectively)
    _, b0, bbo, bend, g0, gbo, gend, cross = summary[0]
    axa.annotate(f"A at rest: {b0:.0f} mT", (0, b0), xytext=(0.55, 30), fontsize=8, color=INK, arrowprops=LEAD)
    axa.annotate(f"A at the hard stop: {bbo:.0f} mT", (HE_TRAVEL, bbo), xytext=(2.3, 112), fontsize=8, color=INK,
                 arrowprops=LEAD)
    axa.annotate(f"A leaves the ±80 mT range at {cross[1]:.1f} mm,\nbefore the stop: that range clips",
                 (cross[1], 80), xytext=(1.0, 89), fontsize=8, color=INK, arrowprops=LEAD, va="bottom")
    axa.text(HE_TRAVEL + HE_SQUASH / 2, 6, "compliant\nzone", ha="center", va="bottom", fontsize=8, color=INK2)
    axa.set_ylim(0, 180)
    axa.set_ylabel("Bz at the Hall element (mT)")
    panel_title(axa, "(a) Field at the sensor")
    axa.legend(loc="upper left", bbox_to_anchor=(0.0, 0.89))

    noise = 0.1     # mT, an assumed noise floor for the conversion below
    axb.annotate(f"A at rest: {g0:.3f} mT per 0.01 mm\n(0.1 mT of noise ≈ {noise / g0 * 10:.0f} µm "
                 "of travel)", (0, g0), xytext=(0.35, 0.40), fontsize=8, color=INK, arrowprops=LEAD)
    axb.annotate(f"A at the hard stop: {gbo:.2f} mT per 0.01 mm, {gbo / g0:.0f}× steeper\n"
                 f"(0.1 mT of noise ≈ {noise / gbo * 10:.1f} µm of travel)",
                 (HE_TRAVEL, gbo), xytext=(1.2, 0.80), fontsize=8, color=INK, arrowprops=LEAD)
    axb.text(HE_TRAVEL + HE_SQUASH / 2, 0.02, "compliant\nzone", ha="center", va="bottom", fontsize=8, color=INK2)
    axb.set_ylim(0, 1.1)
    axb.set_ylabel("field change per 0.01 mm of travel (mT)")
    panel_title(axb, "(b) Gradient: where a given noise floor resolves the finest travel")
    axb.legend(loc="upper left")

    frame(fig, "Hall-effect key: field at the sensor against key travel",
          "Model estimate, not measured. The field rises steeply near the stop, so resolution is best there, and "
          "the magnet, gap and sensor range have to be chosen together.",
          "Model: exact on-axis field of an axially magnetised cylinder, Bz(z) = Br/2 [ (z+L)/√((z+L)²+R²)"
          " − z/√(z²+R²) ], z from the magnet face to a point sensor on the axis.\n"
          f"Parameters (illustrative, not decisions): Br = {BR} T (about N38–N40), {HE_GAP_REST} mm from magnet "
          f"face to Hall element at rest, {HE_TRAVEL:.0f} mm to the hard stop, then a {HE_SQUASH} mm compliant zone "
          "(concept §2.1, §7).\n"
          "Not modelled: steel nearby, neighbouring keys' magnets, stray fields, temperature (NdFeB loses about "
          "0.1 % of Br per K), magnet tolerances, tilt.\n"
          "The noise-to-travel figures assume a 0.1 mT noise floor, only to show the scale. The sensor ranges are "
          "approximate and unchecked: check the TMAG5253 datasheet.",
          MODEL_STAMP)
    print("  he: " + "; ".join(f"{s[0].split(':')[0]}: rest {s[1]:.1f} mT, stop {s[2]:.1f} mT, end {s[3]:.1f} mT, "
                              f"gradient {s[4]:.3f} -> {s[5]:.3f} mT/0.01 mm" for s in summary))
    return save(fig, "phys_he_field_vs_travel.png")


# ---------------------------------------------------------------------------------------------------------------
# (2) Hall-effect key: field from the neighbours' magnets
# ---------------------------------------------------------------------------------------------------------------
PITCH = 19.05
NEIGHBOURS = (("row or column neighbour, 19.05 mm", PITCH, RAMP[4]),
              ("diagonal neighbour, 26.9 mm", PITCH * np.sqrt(2), RAMP[2]),
              ("two keys away, 38.1 mm", 2 * PITCH, RAMP[0]))


def fig_neighbour():
    t = np.linspace(0, HE_TRAVEL + HE_SQUASH, 46)
    fig = plt.figure(figsize=(12, 6.3))
    top, bottom = margins(fig, 4)
    gs = fig.add_gridspec(1, 2, left=0.058, right=0.985, top=top, bottom=bottom, wspace=0.2)
    axa, axb = fig.add_subplot(gs[0]), fig.add_subplot(gs[1])
    own_x = np.linspace(0, HE_TRAVEL + HE_SQUASH, 451)
    own_grad = -dbz_dz_axis(HE_GAP_REST - own_x, HE_R, HE_L) * 1e3 * 1e-3      # mT per um of own travel
    rows = []
    for ax in (axa, axb):
        style(ax)
        ax.axvspan(HE_TRAVEL, HE_TRAVEL + HE_SQUASH, color=SHADE, lw=0, zorder=0)
        ax.axvline(HE_TRAVEL, color=AXIS, lw=0.9, zorder=1)
        ax.set_xlim(0, HE_TRAVEL + HE_SQUASH)
        ax.set_xticks(np.arange(0, 4.51, 0.5))
    for label, rho, col in NEIGHBOURS:
        pts = np.stack([np.full_like(t, rho), np.zeros_like(t), -(HE_GAP_REST - t)], -1)
        bz = sheet_field(pts, HE_R, HE_L)[:, 2] * 1e3
        dB = abs(bz - bz[0])
        axa.plot(t, dB, color=col, lw=2.0, label=label)
        dot(axa, t[-1], dB[-1], col, size=6)
        axa.text(t[-1] - 0.06, dB[-1], f"{dB[-1]:.3f}", ha="right", va="bottom", fontsize=8, color=INK)
        err = dB[-1] / own_grad                                                   # um of own travel
        axb.plot(own_x, err, color=col, lw=2.0, label=label)
        rows.append((label, bz[0], dB[-1], err[0], err[np.argmin(abs(own_x - HE_TRAVEL))]))
    axa.axhspan(0.025, 0.065, color=C3, alpha=0.12, lw=0)
    axa.text(3.92, 0.047, "for scale: Earth's field,\n0.025–0.065 mT in total", fontsize=8, color=INK,
             ha="right", va="center", linespacing=1.4)
    axa.set_ylim(0, 0.2)
    axa.text(HE_TRAVEL + HE_SQUASH / 2, 0.196, "compliant\nzone", ha="center", va="top", fontsize=8, color=INK2)
    axb.text(HE_TRAVEL + HE_SQUASH / 2, 280, "compliant\nzone", ha="center", va="top", fontsize=8, color=INK2)
    axa.set_xlabel("the neighbour's travel (mm)")
    axa.set_ylabel("change in this key's Bz (mT)")
    axa.legend(loc="upper left")
    axa.text(0.08, 0.113, f"At rest the neighbours already add an offset\n(row neighbour −{-rows[0][1]:.2f} mT), "
             "which calibration removes.\nThe reading falls as a neighbour is pressed:\nits return flux opposes "
             "this key's field.", ha="left", va="bottom", fontsize=8, color=INK, linespacing=1.4)
    panel_title(axa, "(a) Field change at this key's sensor as a neighbour is pressed")

    axb.set_yscale("log")
    plain_log(axb)
    axb.grid(True, which="minor", color=GRID, lw=0.35)
    axb.axhline(100, color=INK2, lw=0.9, ls=(0, (5, 3)))
    axb.text(0.05, 108, "for scale: 0.1 mm", fontsize=8, color=INK2, va="bottom")
    r0 = rows[0]
    axb.annotate(f"{r0[3]:.0f} µm near the top", (0, r0[3]), xytext=(0.45, 55), fontsize=8, color=INK,
                 arrowprops=LEAD, bbox=BOX)
    axb.annotate(f"{r0[4]:.1f} µm at the hard stop", (HE_TRAVEL, r0[4]), xytext=(2.55, 20), fontsize=8,
                 color=INK, arrowprops=LEAD, bbox=BOX)
    axb.set_ylim(0.02, 300)
    axb.set_xlabel("this key's own travel (mm)")
    axb.set_ylabel("equivalent travel error of this key (µm, log scale)")
    axb.legend(loc="lower left")
    panel_title(axb, "(b) The same change read as travel (neighbour fully pressed)")

    frame(fig, "Hall-effect key: what a pressed neighbour does to this key's reading",
          "Model estimate, not measured. A fully pressed neighbour shifts a resting key's reading by about 30 µm "
          "of equivalent travel; near the stop the effect is small.",
          "Model: Biot-Savart over each magnet's equivalent side-wall sheet current (exact off-axis), superposed. "
          f"Same magnet A (ø4 × 2 mm, Br = {BR} T) and gaps as the field-against-travel figure;\n"
          "neighbours at the MX pitch of 19.05 mm, all magnetised the same way up. Equivalent travel error = the "
          "neighbour's field change divided by this key's own gradient at its current travel.\n"
          "Not modelled: steel (a steel plate or case would change this a lot), stems and housings, tolerances, "
          "the sensor's own noise. Several neighbours pressed at once add up.\n"
          "Geometry illustrative, not a design. Concept §3.4's switch-free reference sensors target stray "
          "fields and drift; neighbour presses need their own correction or a check on the coupon.",
          MODEL_STAMP)
    for r in rows:
        print(f"  neighbour: {r[0]}: offset at rest {r[1]:.3f} mT, change when pressed {r[2]:.3f} mT, "
              f"equivalent {r[3]:.1f} um at rest / {r[4]:.2f} um at the stop")
    return save(fig, "phys_he_neighbour_field.png")


# ---------------------------------------------------------------------------------------------------------------
# (3) Shear key: lateral field against offset at several depths (Biot-Savart)
# ---------------------------------------------------------------------------------------------------------------
SH_R, SH_L = 2.0, 2.0      # mm, magnet diameter 4 x 2 (the concept render's shear key)
SH_GAP_REST = 6.5          # mm, magnet face to the 3-axis element at rest
SH_DEPTHS = (0.0, 1.0, 2.0, 3.0, 4.0)
SH_SMAX = 0.5


def shear_points(s, d):
    """Sensor position in the magnet's frame, for a magnet pushed by +s (x) and pressed by d."""
    s, d = np.broadcast_arrays(np.asarray(s, float), np.asarray(d, float))
    return np.stack([-s.ravel(), np.zeros(s.size), -(SH_GAP_REST - d).ravel()], -1)


def fig_shear():
    s = np.linspace(-SH_SMAX, SH_SMAX, 41)
    S, D = np.meshgrid(s, SH_DEPTHS)
    B = sheet_field(shear_points(S, D), SH_R, SH_L).reshape(*S.shape, 3) * 1e3      # mT
    Bx, Bz = B[..., 0], B[..., 2]

    # cross-checks: on-axis Bz against the exact formula, slope against the near-axis expansion
    exact = bz_axis(SH_GAP_REST - np.array(SH_DEPTHS), SH_R, SH_L) * 1e3
    i0 = len(s) // 2
    err_bz = np.max(abs(Bz[:, i0] - exact) / exact)
    dd = np.linspace(0, 4, 41)
    ds = 0.01
    bp = sheet_field(shear_points(np.full_like(dd, ds), dd), SH_R, SH_L)[:, 0]
    bm = sheet_field(shear_points(np.full_like(dd, -ds), dd), SH_R, SH_L)[:, 0]
    slope = (bp - bm) / (2 * ds) * 1e3 * 0.1                  # mT per 0.1 mm of offset
    near_axis = -0.5 * dbz_dz_axis(SH_GAP_REST - dd, SH_R, SH_L) * 1e3 * 0.1
    err_slope = np.max(abs(slope - near_axis) / near_axis)
    print(f"  shear: Biot-Savart on-axis Bz vs exact formula, worst relative error {err_bz:.1e}; "
          f"dBx/ds vs near-axis expansion, worst {err_slope:.1e}")
    print(f"  shear: Bz at rest {exact[0]:.1f} mT, at 4 mm {exact[-1]:.1f} mT; "
          f"slope {slope[0]:.2f} -> {slope[-1]:.2f} mT per 0.1 mm")

    fig = plt.figure(figsize=(12, 9.2))
    top, bottom = margins(fig, 5)
    gs = fig.add_gridspec(2, 2, left=0.058, right=0.985, top=top, bottom=bottom, wspace=0.2, hspace=0.36)
    axs = fig.add_subplot(gs[0, 0])
    axb = fig.add_subplot(gs[0, 1])
    axc = fig.add_subplot(gs[1, 0])
    axd = fig.add_subplot(gs[1, 1])

    # (a) geometry sketch, to scale
    ax = axs
    ax.set_aspect("equal")
    ax.add_patch(Rectangle((-6.5, -2.1), 13, 1.6, fc="#2e7d4f", ec="none"))
    ax.text(-6.3, -1.3, "PCB", va="center", fontsize=8, color="white")
    ax.add_patch(Rectangle((-1.5, -0.5), 3.0, 1.0, fc="#222226", ec="none"))
    ax.plot(0, 0, "o", ms=4, mfc="white", mec="white")
    ax.annotate("TMAG5170 (candidate),\nelement at the origin", (0.3, 0.05), xytext=(2.2, 0.15), fontsize=8,
                color=INK, arrowprops=LEAD, va="bottom")
    g0 = SH_GAP_REST
    ax.add_patch(Rectangle((-SH_R, g0), 2 * SH_R, SH_L, fc="none", ec=INK2, lw=1.0, ls=(0, (4, 2))))
    ax.text(SH_R + 0.3, g0 + SH_L / 2, "magnet at rest", va="center", fontsize=8, color=INK2)
    dsk, ssk = 3.0, 0.5
    ax.add_patch(Rectangle((-SH_R + ssk, g0 - dsk), 2 * SH_R, SH_L, fc="#8c8c96", ec="#55555c", lw=0.8))
    ax.text(ssk, g0 - dsk + SH_L / 2, "N↑", ha="center", va="center", fontsize=8, color="white")
    ax.text(SH_R + ssk + 0.3, g0 - dsk + SH_L / 2, f"pressed d = {dsk:.0f} mm,\npushed s = {ssk} mm",
            va="center", fontsize=8, color=INK)
    ax.add_patch(FancyArrowPatch((-3.2, g0), (-3.2, g0 - dsk), arrowstyle="-|>", mutation_scale=10, lw=1.0,
                                 color=INK2))
    ax.text(-3.4, g0 - dsk / 2, "d", ha="right", va="center", fontsize=9, color=INK)
    ax.plot([-SH_R, -3.4], [g0, g0], color=AXIS, lw=0.6)
    ax.plot([-SH_R + ssk, -3.4], [g0 - dsk, g0 - dsk], color=AXIS, lw=0.6)
    ytop = g0 - dsk + SH_L + 0.3
    ax.add_patch(FancyArrowPatch((0, ytop), (ssk, ytop), arrowstyle="-|>", mutation_scale=8, lw=1.0,
                                 color=INK2, shrinkA=0, shrinkB=0))
    ax.text(-0.15, ytop, "s", ha="right", va="center", fontsize=9, color=INK)
    ax.plot([0, 0], [-0.4, 9.2], color=AXIS, lw=0.6, ls=(0, (2, 2)))
    # the field vector at the sensor for the sketched case (Bx exaggerated for display)
    b = sheet_field(shear_points(ssk, dsk), SH_R, SH_L)[0]
    scale = 1.8 / b[2]
    tip = (b[0] * scale * 6, b[2] * scale)
    ax.add_patch(FancyArrowPatch((0, 0), tip, arrowstyle="-|>", mutation_scale=9, lw=1.4, color=C2, zorder=6,
                                 shrinkA=0, shrinkB=0))
    ax.annotate(f"B at the sensor:\nBz {b[2] * 1e3:.0f} mT, Bx {b[0] * 1e3:.1f} mT\n(Bx drawn 6× here)",
                (tip[0] * 0.8, tip[1] * 0.8), xytext=(-6.3, 1.9), fontsize=8, color=INK, arrowprops=LEAD,
                va="center", linespacing=1.3)
    ax.set_xlim(-6.5, 6.5)
    ax.set_ylim(-2.3, 9.2)
    ax.set_xlabel("x (mm)")
    ax.set_ylabel("z (mm)")
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    for sp in ("left", "bottom"):
        ax.spines[sp].set_color(AXIS)
    ax.tick_params(length=3, width=0.6)
    panel_title(ax, "(a) Geometry, to scale (illustrative)")

    # (b) Bx against offset, one line per depth; end labels on the extremes only
    style(axb)
    for k, d in enumerate(SH_DEPTHS):
        axb.plot(s, Bx[k], color=RAMP[k], lw=2.0, label=f"pressed {d:.0f} mm")
        dot(axb, s[-1], Bx[k, -1], RAMP[k], size=5.5)
    for k in (0, len(SH_DEPTHS) - 1):
        axb.text(s[-1] + 0.02, Bx[k, -1], f"{Bx[k, -1]:.1f} mT", va="center", fontsize=8, color=INK)
    axb.axhline(0, color=AXIS, lw=0.8)
    axb.set_xlim(-SH_SMAX, SH_SMAX + 0.14)
    axb.set_xticks(np.arange(-0.4, 0.41, 0.2))
    axb.set_xlabel("lateral offset of the magnet, s (mm)")
    axb.set_ylabel("Bx at the sensor (mT)")
    axb.legend(loc="upper left", title="press depth d", title_fontsize=8.5, alignment="left")
    i3 = np.argmin(abs(s - 0.3))
    axb.text(0.98, 0.04, f"The same 0.3 mm push reads {Bx[0, i3]:.2f} mT at rest\n"
             f"and {Bx[-1, i3]:.1f} mT at 4 mm: {Bx[-1, i3] / Bx[0, i3]:.0f}× apart",
             transform=axb.transAxes, ha="right", va="bottom", fontsize=8, color=INK)
    panel_title(axb, "(b) Lateral field against push, at five press depths")

    # (c) sensitivity against depth
    style(axc)
    axc.plot(dd, slope, color=C1, lw=2.0, label="Biot-Savart over the surface current (numerical)")
    axc.plot(dd[::4], near_axis[::4], "o", ms=5, mfc="white", mec=INK2, mew=1.0,
             label="check: near-axis expansion, ½ |dBz/dz|")
    dot(axc, dd[0], slope[0], C1, size=6)
    dot(axc, dd[-1], slope[-1], C1, size=6)
    axc.annotate(f"{slope[0]:.2f} mT per 0.1 mm at rest", (dd[0], slope[0]), xytext=(0.3, 0.95), fontsize=8,
                 color=INK, arrowprops=LEAD, bbox=BOX)
    axc.annotate(f"{slope[-1]:.2f} mT per 0.1 mm at 4 mm,\n{slope[-1] / slope[0]:.0f}× the value at rest",
                 (dd[-1], slope[-1]), xytext=(2.05, 2.2), fontsize=8, color=INK, arrowprops=LEAD, bbox=BOX)
    axc.set_xlim(0, 4.05)
    axc.set_ylim(0, 3.0)
    axc.set_xlabel("press depth d (mm)")
    axc.set_ylabel("Bx sensitivity near s = 0 (mT per 0.1 mm)")
    axc.legend(loc="upper left")
    panel_title(axc, "(c) Sensitivity to a push rises steeply with depth")

    # (d) Bx / Bz against offset
    style(axd)
    ratio = Bx / Bz
    for k, d in enumerate(SH_DEPTHS):
        axd.plot(s, ratio[k], color=RAMP[k], lw=2.0, label=f"pressed {d:.0f} mm")
        dot(axd, s[-1], ratio[k, -1], RAMP[k], size=5.5)
    for k in (0, len(SH_DEPTHS) - 1):
        axd.text(s[-1] + 0.02, ratio[k, -1], f"{ratio[k, -1]:.3f}", va="center", fontsize=8, color=INK)
    axd.axhline(0, color=AXIS, lw=0.8)
    axd.set_xlim(-SH_SMAX, SH_SMAX + 0.14)
    axd.set_xticks(np.arange(-0.4, 0.41, 0.2))
    axd.set_xlabel("lateral offset of the magnet, s (mm)")
    axd.set_ylabel("Bx / Bz (ratio)")
    axd.legend(loc="upper left", title="press depth d", title_fontsize=8.5, alignment="left")
    axd.text(0.98, 0.04, f"Dividing by Bz shrinks the spread from {Bx[-1, i3] / Bx[0, i3]:.0f}× to "
             f"{ratio[-1, i3] / ratio[0, i3]:.1f}×,\nbut does not remove it", transform=axd.transAxes,
             ha="right", va="bottom", fontsize=8, color=INK)
    panel_title(axd, "(d) Normalised by Bz: closer, still depth-dependent")

    frame(fig, "Shear key: lateral field at a 3-axis sensor against push and press depth",
          "Model estimate, not measured. The same sideways push reads very differently at each press depth, so "
          "the pointing calibration has to be a function of depth (concept §2.1).",
          "Model: the magnet's uniform axial magnetisation replaced by its equivalent side-wall sheet current "
          "K = Br/μ₀, field summed by Biot-Savart (48 loops × 256 segments).\n"
          f"Checked against the exact on-axis formula (worst error {err_bz:.0e}) and the near-axis expansion "
          f"Bρ = −(ρ/2) dBz/dz (worst error {err_slope:.0e}).\n"
          f"Parameters (illustrative, not decisions): Br = {BR} T, magnet ø4 × 2 mm, {SH_GAP_REST} mm "
          "from magnet face to the element at rest, press 0–4 mm, lateral offset ±0.5 mm "
          "(concept §2.1: about ±0.3–0.5 mm).\n"
          "Point sensor, rigid magnet, no tilt, no steel, no neighbouring magnets, no stray field; the sensor's "
          "ranges and noise are not modelled.\n"
          "A real stem also tilts as it is pushed, and the sensor sits slightly off-centre: both add a "
          "press-dependent Bx that the calibration has to remove.",
          MODEL_STAMP)
    return save(fig, "phys_shear_field.png")


# ---------------------------------------------------------------------------------------------------------------
# (4) Printed coil: inductance against turns
# ---------------------------------------------------------------------------------------------------------------
CO_W, CO_S = 0.127, 0.127     # mm, trace and space
CO_DIN_MIN = 4.5              # mm, inner diameter kept clear of the MX centre-post hole
CO_ODS = ((10.0, C1), (12.0, C2), (14.0, C3))
CO_LAYERS = (1, 2, 4)
K1, K2 = 2.25, 3.55           # modified Wheeler, octagonal (a stand-in for a round spiral)
K_MID, K_LO, K_HI = 0.7, 0.45, 0.9


def wheeler(n, d_out, w=CO_W, s=CO_S):
    """Modified Wheeler inductance (H) of one planar spiral layer, n turns, outer diameter d_out (mm)."""
    d_in = d_out - 2 * n * w - 2 * (n - 1) * s
    d_avg = (d_out + d_in) / 2
    rho = (d_out - d_in) / (d_out + d_in)
    return K1 * MU0 * n ** 2 * d_avg * 1e-3 / (1 + K2 * rho), d_in


def stack(L1, N, k):
    return L1 * N * (1 + (N - 1) * k)


def max_turns(d_out):
    return int((d_out - CO_DIN_MIN + CO_S) // (2 * (CO_W + CO_S)))


def loop_mutual(a, b, h):
    """Maxwell's mutual inductance (H) of two coaxial circular loops, radii a, b and spacing h (m)."""
    m = 4 * a * b / ((a + b) ** 2 + h ** 2)
    k = np.sqrt(m)
    return MU0 * np.sqrt(a * b) * ((2 / k - k) * ellipk(m) - 2 / k * ellipe(m))


def loop_model_k(d_out, n, h_mm, w=CO_W, s=CO_S, t=0.035):
    """Coupling between two identical spiral layers h_mm apart, each modelled as n concentric loops.
    Each loop's self-inductance uses the thin-ring formula with a rectangular trace's mean distance 0.2235 (w + t).
    Also returns the loop model's single-layer L, as a check on the Wheeler figure."""
    r = (d_out / 2 - w / 2 - np.arange(n) * (w + s)) * 1e-3
    ring = MU0 * r * (np.log(8 * r / (0.2235 * (w + t) * 1e-3)) - 2)
    A, Bm = np.meshgrid(r, r)
    off = ~np.eye(n, dtype=bool)
    L_self = ring.sum() + loop_mutual(A[off], Bm[off], 0.0).sum()
    M = loop_mutual(A, Bm, h_mm * 1e-3).sum()
    return M / L_self, L_self


def fig_coil():
    for d_out in (10.0, 14.0):          # cross-checks, printed
        n = max_turns(d_out)
        kk = [loop_model_k(d_out, n, h)[0] for h in (0.2, 1.07, 1.5)]
        Lw = wheeler(n, d_out)[0]
        Ll = loop_model_k(d_out, n, 0.2)[1]
        print(f"  coil: OD {d_out:.0f} mm, {n} turns: Wheeler {Lw * 1e6:.2f} uH, concentric loops "
              f"{Ll * 1e6:.2f} uH; loop-model k at 0.2 / 1.07 / 1.5 mm = " + " / ".join(f"{k:.2f}" for k in kk))

    fig = plt.figure(figsize=(12, 6.3))
    top, bottom = margins(fig, 4)
    gs = fig.add_gridspec(1, 3, left=0.058, right=0.985, top=top, bottom=bottom, wspace=0.08)
    axes = [fig.add_subplot(gs[0])]
    axes += [fig.add_subplot(gs[i], sharey=axes[0]) for i in (1, 2)]
    for ax, N in zip(axes, CO_LAYERS):
        style(ax)
        ax.set_yscale("log")
        ax.grid(True, which="minor", color=GRID, lw=0.35)
        for d_out, col in CO_ODS:
            n = np.arange(1, max_turns(d_out) + 1)
            L1 = np.array([wheeler(i, d_out)[0] for i in n]) * 1e6
            if N > 1:
                ax.fill_between(n, stack(L1, N, K_LO), stack(L1, N, K_HI), color=col, alpha=0.13, lw=0)
            Ln = stack(L1, N, K_MID)
            ax.plot(n, Ln, color=col, lw=2.0, label=f"outer diameter {d_out:.0f} mm")
            dot(ax, n[-1], Ln[-1], col, size=6)
            ax.text(n[-1] + 0.6, Ln[-1], f"{Ln[-1]:.1f} µH", va="center", fontsize=8, color=INK)
        ax.set_xlim(0, 23)
        ax.set_xticks(range(0, 21, 5))
        ax.set_xlabel("turns per layer")
        if N == 1:
            panel_title(ax, "(a) 1 layer")
            ax.set_ylabel("inductance (µH, log scale)")
        else:
            panel_title(ax, f"({'bc'[N // 2 - 1]}) {N} layers in series, k = {K_MID} (band {K_LO}–{K_HI})")
            plt.setp(ax.get_yticklabels(), visible=False)
    axes[0].set_ylim(0.01, 100)
    plain_log(axes[0])
    axes[0].legend(loc="upper left")
    axes[0].text(0.97, 0.04, "Each line ends where the inner\ndiameter reaches 4.5 mm", transform=axes[0].transAxes,
                 ha="right", va="bottom", fontsize=8, color=INK2)
    axes[2].text(0.97, 0.04, "Shaded: the same coil with k from\n0.45 (layers far apart) to 0.9 (close)",
                 transform=axes[2].transAxes, ha="right", va="bottom", fontsize=8, color=INK2)

    frame(fig, "Printed coil: inductance against turns, diameter and layers",
          "Model estimate, not measured. Inductance climbs fast with turns until the spiral fills in; layers in "
          "series multiply it, by how much depends on their coupling.",
          "Model: modified Wheeler, L = K1 μ₀ n² d_avg / (1 + K2 ρ) (Mohan et al., IEEE JSSC "
          f"1999), octagonal K1 = {K1}, K2 = {K2} as a stand-in for a round spiral. N layers in series: "
          "L = N L1 (1 + (N−1) k).\n"
          f"Assumption, rough: the same k between every pair of layers, k = {K_MID} (band {K_LO}–{K_HI}). A "
          "concentric-loop estimate gives about 0.85–0.9 for layers 0.2 mm apart and 0.4–0.6 for layers "
          "1.5 mm apart.\n"
          f"Parameters (illustrative): trace and space {CO_W} mm, outer diameter 10, 12, 14 mm, inner diameter "
          f"≥ {CO_DIN_MIN} mm. A lone coil in free space at DC: no spring or slug above it, no ground copper.\n"
          "No self-resonance, and no keep-outs for the switch pins (a stock MX switch's pins sit inside a 10–14 "
          "mm coil). The rev A coil coupon (concept §2.4) measures the real values.",
          MODEL_STAMP)
    return save(fig, "phys_coil_inductance.png")


# ---------------------------------------------------------------------------------------------------------------
# (5) Haptic wheel: illustrative detent profiles (firmware tables)
# ---------------------------------------------------------------------------------------------------------------
def tick_profile(th, period=12.0, amp=0.35):
    return -amp * np.sin(2 * np.pi * th / period)


def stops_profile(th, span=270.0, tick_every=27.0, tick_amp=0.10, wall_deg=4.0):
    t = np.where((th >= 0) & (th <= span), -tick_amp * np.sin(2 * np.pi * th / tick_every), 0.0)
    t = np.where(th < 0, np.clip(-th / wall_deg, 0, 1), t)
    t = np.where(th > span, -np.clip((th - span) / wall_deg, 0, 1), t)
    return t


def slots_profile(th, n=8, amp=0.8, ramp=8.0, blend=1.0):
    """A spring into the nearest slot that saturates `ramp` degrees out and snaps over at the midpoint."""
    p = 360.0 / n
    u = (th + p / 2) % p - p / 2                       # offset from the nearest slot, degrees
    t = -amp * np.clip(u / ramp, -1, 1)
    return t * np.clip((p / 2 - abs(u)) / blend, 0, 1)


def fig_haptic():
    fig = plt.figure(figsize=(12, 8.4))
    top, bottom = margins(fig, 3)
    gs = fig.add_gridspec(2, 2, left=0.065, right=0.985, top=top, bottom=bottom, wspace=0.16, hspace=0.42)
    ax = [fig.add_subplot(gs[i // 2, i % 2]) for i in range(4)]
    for a in ax:
        style(a)
        a.axhline(0, color=AXIS, lw=0.9, zorder=1)
        a.set_ylim(-1.12, 1.62)          # headroom so each panel's header sits above the data
        a.set_yticks([-1, -0.5, 0, 0.5, 1])
    for a in (ax[0], ax[2]):
        a.set_ylabel("torque (fraction of full scale)")

    # (a) per-line ticks
    th = np.linspace(-3, 63, 1200)
    ax[0].plot(th, tick_profile(th), color=C1, lw=2.0)
    for i, x0 in enumerate(range(0, 61, 12)):
        dot(ax[0], x0, 0, C1, size=6)
        ax[0].text(x0, -0.5, f"line {i + 1}", ha="center", va="top", fontsize=8, color=INK)
    ax[0].annotate("", (12, 0.55), (24, 0.55), arrowprops=dict(arrowstyle="<->", lw=0.8, color=INK2))
    ax[0].text(18, 0.6, "12° per line", ha="center", va="bottom", fontsize=8, color=INK)
    ax[0].text(0.5, 0.97, "light, evenly spaced ticks; the torque always pulls toward the nearest line",
               transform=ax[0].transAxes, ha="center", va="top", fontsize=8, color=INK2, bbox=BOX)
    ax[0].set_xlim(-3, 63)
    ax[0].set_xticks(range(0, 61, 12))
    ax[0].set_xlabel("wheel angle (degrees)")
    panel_title(ax[0], "(a) Editor: one tick per line")

    # (b) hard end stops at 0 and 100
    th = np.linspace(-40, 310, 2400)
    ax[1].axvspan(-40, 0, color=SHADE, lw=0, zorder=0)
    ax[1].axvspan(270, 310, color=SHADE, lw=0, zorder=0)
    ax[1].plot(th, stops_profile(th), color=C2, lw=2.0)
    ax[1].text(-20, -0.55, "wall", ha="center", fontsize=8, color=INK2)
    ax[1].text(290, 0.55, "wall", ha="center", fontsize=8, color=INK2)
    for x0, lab, y in ((0, "volume 0", 0.3), (270, "volume 100", -0.3)):
        ax[1].annotate(lab, (x0, 0), xytext=(x0 + (16 if x0 == 0 else -16), y), fontsize=8, color=INK,
                       ha="left" if x0 == 0 else "right", arrowprops=LEAD)
        dot(ax[1], x0, 0, C2, size=6)
    ax[1].text(0.5, 0.97, "full-scale torque within 4° past each end;\nlight ticks every 10 units between",
               transform=ax[1].transAxes, ha="center", va="top", fontsize=8, color=INK2, bbox=BOX)
    ax[1].set_xlim(-40, 310)
    ax[1].set_xticks([0, 54, 108, 162, 216, 270])
    ax[1].set_xlabel("wheel angle (degrees; 2.7° per unit)")
    panel_title(ax[1], "(b) Volume: hard stops at 0 and 100")

    # (c) N slots
    th = np.linspace(-6, 366, 6000)
    ax[2].plot(th, slots_profile(th), color=C3, lw=2.0)
    for i in range(9):
        dot(ax[2], i * 45, 0, C3, size=6)
        ax[2].text(i * 45, -0.92, f"slot {i % 8 + 1}", ha="center", va="top", fontsize=8, color=INK)
    ax[2].text(0.5, 0.97, "8 slots, 45° apart: a spring into each slot, saturating 8° out;\n"
               "it snaps over to the next slot at each midpoint (the vertical jumps)",
               transform=ax[2].transAxes, ha="center", va="top", fontsize=8, color=INK2, bbox=BOX)
    ax[2].set_xlim(-8, 368)
    ax[2].set_xticks(range(0, 361, 45))
    ax[2].set_xlabel("wheel angle (degrees)")
    panel_title(ax[2], "(c) Game weapon wheel: N slots (here 8)")

    # (d) free spin with light damping: torque against speed, not angle
    w = np.linspace(-4, 4, 200)
    ax[3].plot(w, -0.03 * w, color=C1, lw=2.0)
    ax[3].axvline(0, color=AXIS, lw=0.9, zorder=1)
    ax[3].text(0.5, 0.97, "no detents: the torque does not depend on angle at all,\nonly a light drag "
               "against speed (0.03 of full scale per rev/s)", transform=ax[3].transAxes, ha="center", va="top",
               fontsize=8, color=INK2, bbox=BOX)
    ax[3].set_xlim(-4, 4)
    ax[3].set_xlabel("wheel speed (revolutions per second)")
    panel_title(ax[3], "(d) Long documents: free spin (note: against speed, not angle)")

    frame(fig, "Haptic thumb wheel: four detent profiles",
          "Illustrative profiles, not measured: firmware tables picked by the context profile (concept §2.3, "
          "§3.3), not physics. Positive torque turns the wheel toward larger angles.",
          "Torque is a fraction of the profile's full scale. What full scale means in mN·m depends on the "
          "motor (torque constant, cogging), the driver's current limit and the FOC tuning, none of which is "
          "chosen or tested.\n"
          "Dots mark the stable rest points (torque zero, pulling back from both sides). Shapes are illustrative: "
          "a sine for ticks, a saturating spring for slots, a steep linear wall for the end stops.\n"
          "Peak current follows the torque command: concept §2.3 estimates 0.5–1 A peaks on 5 V for "
          "strong detents (an estimate), which is why the wheel is wired-first.",
          "ILLUSTRATIVE PROFILES: firmware tables, not measured")
    return save(fig, "phys_haptic_profiles.png")


# ---------------------------------------------------------------------------------------------------------------
# (6) Polling latency: arithmetic of the scan and report waits
# ---------------------------------------------------------------------------------------------------------------
P99_TRI = 2 - np.sqrt(0.02)      # p99 of the sum of two uniform [0, 1) waits


def fig_latency():
    rng = np.random.default_rng(20261125)
    n = 200_000
    cases = []          # label, colour, linestyle, samples (ms), T, (mean, p50, p99) exact
    for rate, T, col in ((1, 1.0, C1), (8, 0.125, C2)):
        u1, u2 = rng.random(n), rng.random(n)
        cases.append((f"{rate} kHz, scan locked to the report", col, "-", u1 * T, T, (T / 2, T / 2, 0.99 * T)))
        cases.append((f"{rate} kHz, free-running scan", col, (0, (4, 2.5)), (u1 + u2) * T, T, (T, T, P99_TRI * T)))
    for label, _c, _l, x, T, exact in cases:
        sim = (x.mean(), *np.percentile(x, [50, 99]))
        worst = max(abs(a - b) / b for a, b in zip(sim, exact))
        print(f"  latency: {label}: mean / p50 / p99 = " + " / ".join(f"{v:.4g}" for v in exact)
              + f" ms; sampled within {worst:.1%}")

    fig = plt.figure(figsize=(12, 8.6))
    top, bottom = margins(fig, 3)
    gs = fig.add_gridspec(2, 2, left=0.058, right=0.985, top=top, bottom=bottom, height_ratios=[1.0, 1.0],
                          width_ratios=[1.2, 1.0], hspace=0.42, wspace=0.14)
    axt = fig.add_subplot(gs[0, :])
    axc = fig.add_subplot(gs[1, 0])
    axtab = fig.add_subplot(gs[1, 1])

    # (a) timing diagram
    tp = 0.30       # the example press (ms)
    lanes = [  # y, label, interval, phase, colour, kind
        (4.2, "1 kHz scan, every 1 ms", 1.0, 0.80, C1, "scan"),
        (3.4, "1 kHz report (USB poll)", 1.0, 0.0, C1, "report"),
        (1.6, "8 kHz scan, every 0.125 ms", 0.125, 0.10, C2, "scan"),
        (0.8, "8 kHz report (USB poll)", 0.125, 0.0, C2, "report"),
    ]
    t_end = 1.5
    for y, label, T, ph, col, kind in lanes:
        axt.plot([0, t_end], [y, y], color=AXIS, lw=0.8, zorder=1)
        ts = np.arange(ph, t_end - 1e-9, T)
        h = 0.2 if kind == "scan" else 0.28
        axt.vlines(ts, y - h, y + h, color=col, lw=1.6 if kind == "scan" else 2.6, zorder=3)
        axt.text(-0.025, y, label, ha="right", va="center", fontsize=8.5, color=INK)
    axt.plot([tp, tp], [0.25, 4.95], color=INK, lw=1.0, ls=(0, (3, 2)), zorder=2)
    axt.text(tp - 0.01, 5.0, "a press at a random time (here 0.30 ms)", ha="right", va="bottom", fontsize=8.5,
             color=INK)

    def arrow(y, t0, t1):
        axt.add_patch(FancyArrowPatch((t0, y), (t1, y), arrowstyle="-|>", mutation_scale=8, lw=1.1, color=INK,
                                      shrinkA=0, shrinkB=0, zorder=4))

    # 1 kHz: next scan at 0.80, next report at 1.00
    arrow(4.65, tp, 0.80)
    axt.text(0.55, 4.73, "waits 0.50 ms for the next scan", ha="center", va="bottom", fontsize=8, color=INK)
    axt.plot([0.80, 0.80], [3.4, 4.2], color=INK2, lw=0.7, ls=(0, (1, 1.5)))
    arrow(2.95, 0.80, 1.00)
    axt.text(1.03, 2.95, "then 0.20 ms for the report:\n0.70 ms in all for this press", ha="left", va="center",
             fontsize=8, color=INK)
    # 8 kHz: next scan at 0.35, next report at 0.375
    arrow(2.05, tp, 0.35)
    axt.text(0.38, 2.05, "waits 0.05 ms for the next scan", ha="left", va="center", fontsize=8, color=INK)
    axt.plot([0.35, 0.35], [0.8, 1.6], color=INK2, lw=0.7, ls=(0, (1, 1.5)))
    arrow(0.3, 0.35, 0.375)
    axt.text(0.40, 0.3, "then 0.025 ms for the report: 0.075 ms in all", ha="left", va="center", fontsize=8,
             color=INK)
    axt.set_xlim(-0.01, t_end)
    axt.set_ylim(0.05, 5.35)
    axt.set_yticks([])
    for sp in ("top", "right", "left"):
        axt.spines[sp].set_visible(False)
    axt.spines["bottom"].set_color(AXIS)
    axt.tick_params(length=3, width=0.6)
    axt.set_xticks(np.arange(0, 1.51, 0.25))
    axt.set_xlabel("time (ms)")
    pos = axt.get_position()
    axt.set_position([0.19, pos.y0, 0.795, pos.height])        # room on the left for the lane labels
    axt.set_title("(a) One press: it waits for the next scan, then for the next report", loc="left", pad=8,
                  fontsize=10.5, color=INK, x=-0.165)

    # (b) cumulative distribution of the added wait
    style(axc)
    axc.set_xscale("log")
    for label, col, ls, x, T, (mean, p50, p99) in cases:
        xs = np.sort(x)
        p = np.arange(1, n + 1) / n
        k = slice(None, None, 200)
        axc.plot(xs[k], p[k], color=col, lw=2.0, ls=ls, label=label)
        dot(axc, p99, 0.99, col, size=5.5)
    axc.axhline(0.5, color=AXIS, lw=0.8)
    axc.axhline(0.99, color=AXIS, lw=0.8)
    axc.text(2.4, 0.515, "p50", fontsize=8, color=INK2, va="bottom", ha="right")
    axc.text(0.0022, 0.975, "p99 (dots)", fontsize=8, color=INK2, va="top")
    axc.set_xlim(0.002, 2.5)
    axc.set_ylim(0, 1.02)
    axc.set_xticks([0.002, 0.01, 0.0625, 0.125, 0.5, 1, 2])
    axc.set_xticklabels(["0.002", "0.01", "0.0625", "0.125", "0.5", "1", "2"])
    axc.set_xlabel("added wait (ms, log scale)")
    axc.set_ylabel("fraction of presses that wait less")
    axc.legend(loc="upper left", bbox_to_anchor=(0.0, 0.9))
    panel_title(axc, "(b) Added wait over 200 000 random presses")

    # (c) the arithmetic, as a table
    axtab.axis("off")
    axtab.set_title("(c) The arithmetic (exact; the samples agree)", loc="left", pad=8, fontsize=10.5, color=INK)
    head = ("", "T (ms)", "mean (ms)", "p50 (ms)", "p99 (ms)")
    colx = (0.06, 0.53, 0.67, 0.82, 0.96)
    y = 0.95
    for c_i, cell in enumerate(head):
        axtab.text(colx[c_i], y, cell, transform=axtab.transAxes, fontsize=8.5, color=INK2,
                   ha="left" if c_i == 0 else "center", va="top")
    axtab.plot([0, 1], [y - 0.075, y - 0.075], transform=axtab.transAxes, color=AXIS, lw=0.8)
    y -= 0.11
    for label, col, ls, x, T, (mean, p50, p99) in cases:
        rate, how = label.split(", ")
        cells = (f"{rate}\n{how}", f"{T:g}", f"{mean:g}", f"{p50:g}", f"{p99:.3g}")
        for c_i, cell in enumerate(cells):
            axtab.text(colx[c_i], y, cell, transform=axtab.transAxes, fontsize=8.5, color=INK,
                       ha="left" if c_i == 0 else "center", va="top", linespacing=1.3,
                       weight="bold" if c_i == 2 else "normal")
        axtab.plot([0.0, 0.045], [y - 0.03, y - 0.03], transform=axtab.transAxes, color=col, lw=2.0, ls=ls)
        y -= 0.135
    axtab.plot([0, 1], [y + 0.005, y + 0.005], transform=axtab.transAxes, color=AXIS, lw=0.8)
    axtab.text(0.0, y - 0.035,
               "A wait for a periodic event of interval T, at a random moment,\n"
               "is uniform on [0, T): mean T/2, p50 T/2, p99 0.99 T.\n"
               "Half an interval: 1 ms / 2 = 0.5 ms at 1 kHz; 0.125 ms / 2 = 0.0625 ms at 8 kHz.\n"
               "A free-running scan adds a second half-interval:\n"
               "mean T, p50 T, p99 (2 − √0.02) T ≈ 1.86 T.",
               transform=axtab.transAxes, fontsize=8.5, color=INK, va="top", linespacing=1.55)

    frame(fig, "Polling: the wait that scanning and reporting add, 1 kHz against 8 kHz",
          "Arithmetic, not a measurement. Each periodic step a press waits for adds half its interval on average, "
          "so 8 kHz cuts the wait 8×.",
          "Assumptions: presses uniformly random in time; scan and report strictly periodic; 'locked' means the "
          "scan runs just before each report, 'free-running' means their phases are unrelated.\n"
          "Not included: sensor settling and conversion, the firmware's own processing, the USB host stack, the "
          "OS and the display, which the latency gate (concept §4.2) measures end to end.\n"
          "8 kHz reports need high-speed USB (125 µs microframes); a full-speed device is polled at most "
          "every 1 ms. Curves: 200 000 sampled presses, fixed seed.",
          "ARITHMETIC: not a measurement")
    return save(fig, "phys_polling_latency.png")


FIGURES = {"he": fig_he_field, "neighbour": fig_neighbour, "shear": fig_shear, "coil": fig_coil,
           "haptic": fig_haptic, "latency": fig_latency}


def main(argv):
    names = argv or list(FIGURES)
    bad = [n for n in names if n not in FIGURES]
    if bad:
        sys.exit(f"unknown figure(s) {bad}; choose from {list(FIGURES)}")
    for n in names:
        print(f"{n}:")
        FIGURES[n]()


if __name__ == "__main__":
    main(sys.argv[1:])
