#!/usr/bin/env python3
"""Data figures from the keyboard desk research (2026-11-25): the sceptics' scores and the prior art.

STATUS: CONCEPT. Nothing in keyboard/ is designed, built or measured (keyboard/docs/concept.md). These figures
plot OPINION DATA from desk research, not measurements: each research area's sceptic gave every proposed idea a
1-10 score for worth building and rated its novelty, feasibility on this toolchain and daily-driver value. Four of
the five sceptics could not search the web (keyboard/docs/research.md, "How this was researched"), so some
"rare" novelty ratings may be generous. The prior-art matrix is a picture of what concept.md lists for each
feature, nothing more; "not found" means not found by that desk research.

Run from the repo root (the interpreter needs matplotlib, numpy and Pillow):

    PY=/path/to/venv/bin/python
    $PY keyboard/docs/figures/data.py                      # all three figures, from ideas.json
    $PY keyboard/docs/figures/data.py scores grid prior    # a subset
    $PY keyboard/docs/figures/data.py --rebuild-json RESEARCH.json   # re-trim ideas.json from the raw output

It writes keyboard/docs/figures/data_*.png in a few seconds.

The data
--------

ideas.json (committed next to this script) is the trimmed research output, so the figures rebuild without the
raw research file. One record per idea that a researcher proposed and a sceptic scored (54 in all; the ideas the
sceptics added themselves carry no score and are left out). Fields: lens (research area), name (as the researcher
wrote it), label (a short name, matching the names on research.md and concept.md), score (the sceptic's 1-10),
verdict (keep, keep_as_moonshot, demote, drop), novelty, feasibility, daily_driver_value (all the sceptic's
ratings), status, section (the concept.md section a picked or folded idea lives in) and, where needed, a note.

status is the owner's choice on 2026-11-25, by idea-name prefix (STATUS_RULE below):
    picked      one of the owner's twelve features, concept.md sections 2.1-4.4
    folded      supporting work folded into a picked feature (named in concept.md inside that feature)
    not picked  everything else (research.md, "Ideas we weighed and did not pick")
One deliberate exception: "One source for board, firmware and web app (live digital twin)" was on neither of the
owner's lists, but research.md does not list it as not picked, its sceptic said "keep it as foundation work", and
concept.md section 4.1 (one layout file regenerates the firmware matrix, physical layout, keymap and docs) covers
it. So STATUS_RULE counts it as "folded" into section 4.1, and its record says why. The script checks the counts
(12 picked, 7 folded, 35 not picked).

--rebuild-json reads the raw research output (results[].ideas.ideas and results[].verdicts.verdicts) and rewrites
ideas.json with the labels and status rule below.

The figures
-----------

data_idea_scores.png: every idea's sceptic score, one row per idea, grouped by research area and sorted by score.
    Marker colour and shape give the status; the right-hand column gives the sceptic's verdict.
data_novelty_feasibility.png: the sceptic's novelty rating against its feasibility rating, a 4 x 4 grid. Each cell
    gives its idea count and one dot per idea (coloured by status), and names the picked ideas.
data_prior_art_matrix.png: the twelve chosen features down the side; columns for where the closest prior art that
    concept.md names lives (commercial product, open project, research or patent) and what the research did not
    find (the part concept.md calls new). Filled from concept.md's "Prior art" and "New" lines, section by section.
"""

import json
import os
import sys
import textwrap
from collections import Counter

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt                                     # noqa: E402
from matplotlib.patches import FancyBboxPatch, Rectangle            # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
IDEAS_JSON = os.path.join(HERE, "ideas.json")
SOURCE_NOTE = "source: desk research 2026-11-25, sceptic scores"
SOURCE_NOTE_PRIOR = "source: desk research 2026-11-25, prior art as concept.md lists it (sections 2.1-4.4)"
STAMP = "DESK RESEARCH: opinions, not measurements"
STAMP_PRIOR = "DESK RESEARCH: as found, not exhaustive"

# ---------------------------------------------------------------------------------------------------------------
# Style: the quiet palette of physics.py (dataviz reference palette: categorical slots 1-2, text in ink colours,
# never in a series colour). Status is the only colour job: picked = slot 1 blue, folded = slot 2 orange, not
# picked = the de-emphasis grey. Shape repeats the status (circle, diamond, open circle) for colour-blind readers
# and print. The blue/orange pair validates (CVD dE 26.6, normal 35.2); orange is below 3:1 on white, so every
# mark carries a visible label or legend entry.
# ---------------------------------------------------------------------------------------------------------------
INK = "#191919"
INK2 = "#666666"
INK3 = "#9a9a9a"
GRID = "#e7e7e7"
AXIS = "#c2c2c2"
SHADE = "#f4f4f4"
TINT = "#eaf2fc"            # blue step 100 lightened: the "claimed new" column
STAMP_RED = "#8c1a1a"
C_PICKED, C_FOLDED, C_NOT = "#257de0", "#f47230", "#b4b4b4"
DPI = 150

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 9,
    "lines.solid_capstyle": "round",
    "lines.solid_joinstyle": "round",
})

LENSES = [
    ("sensing", "Switch and sensing"),
    ("input_feedback", "Extra input and feedback"),
    ("smarts", "MCU, connectivity and software"),
    ("ergo_form", "Ergonomics and form"),
    ("as_code", "Designed-as-code"),
]
STATUSES = ["picked", "folded", "not picked"]
STATUS_STYLE = {   # marker, face, edge, size (points), legend text
    "picked": ("o", C_PICKED, "white", 8.5, "picked: one of the owner's 12 features"),
    "folded": ("D", C_FOLDED, "white", 7.0, "folded into a picked feature"),
    "not picked": ("o", "white", C_NOT, 7.0, "not picked"),
}
VERDICT_TEXT = {"keep": "keep", "keep_as_moonshot": "keep as moonshot", "demote": "demote", "drop": "drop"}
NOVELTY = [("table_stakes", "table stakes"), ("common", "common"), ("niche_exists", "niche exists"),
           ("rare", "rare")]
FEASIBILITY = [("straightforward", "straightforward"), ("hard", "hard"), ("research_needed", "research needed"),
               ("impractical", "impractical")]

# ---------------------------------------------------------------------------------------------------------------
# Status rule and short labels (used by --rebuild-json; the committed ideas.json already carries them)
# ---------------------------------------------------------------------------------------------------------------
STATUS_RULE = {
    "picked": {   # prefix -> concept.md section
        "Shear keys": "2.1", "Generated keywell on flex": "2.2", "Haptic thumb wheel": "2.3",
        "Generated printed-coil": "2.4", "Twin-wire KVM": "3.1", "Behaviour flight recorder": "3.2",
        "Host-context engine": "3.3", "Adaptive analog ergonomics": "3.4", "One layout source": "4.1",
        "Latency as a release gate": "4.2", "A sensing testbed": "4.3", "Per-user fit": "4.4",
    },
    "folded": {   # prefix -> the picked feature's section it is folded into
        "Compliant-stop": "4.3",              # section 7: the Hall-effect coupon's compliant-stop aftertouch sites
        "Hybrid scanning core": "4.3",        # section 7: the Hall coupon's shared-bus topology at 1 and 8 kHz
        "Haptic vocabulary engine": "3.3",    # section 3.3: DRV2605L and a coin LRA per half, a small vocabulary
        "Adaptive-rate single-chip": "4.2",   # section 5: a candidate chip the battery-budget gate chooses between
        "Fork-to-fab": "4.1",                 # section 4.1: the same gates on every fork
        "Generated sensor geometry": "2.4",   # section 2.4: the generated coils and the ~20-variant coupon
        "One source for board": "4.1",        # see the module docstring: the documented exception
    },
}
FOLDED_NOTE = {
    "One source for board": ("The one documented exception to the prefix rule: research.md does not list it as "
                             "not picked, the sceptic said keep it as foundation work, and concept.md section 4.1 "
                             "covers it, so it is counted as folded into section 4.1."),
}
LABELS = {   # prefix -> short label (picked: the concept.md feature name; others: research.md's table names)
    # Switch and sensing
    "Travel + force fusion": "Load-cell plate fusing force with travel",
    "Compliant-stop": "Compliant-stop aftertouch",
    "Shear keys": "Shear keys",
    "Metrology-grade keys": "Differential dual-Hall per key",
    "Virtual tactility": "Haptic tick at the actuation point",
    "Generated printed-coil": "Analog from stock switches (printed coils)",
    "Adaptive analog ergonomics": "Per-finger analog tuning and load budget",
    "Hover and resting-hand": "Hover and resting-hand sensing",
    "Hybrid scanning core": "Hybrid scanning core (8 kHz Hall bus)",
    "A sensing testbed": "Sensing testbed with an open dataset",
    # Extra input and feedback
    "Haptic thumb wheel": "Haptic thumb wheel",
    "Haptic vocabulary engine": "Haptic vocabulary (an LRA per half)",
    "Generated capacitive thumb pad": "Generated 2D capacitive thumb trackpad",
    "Host-context engine": "Context-aware feel",
    "Force-tier solid-state": "Piezo force-tier thumb keys",
    "Touch-aware keycaps": "Touch-aware keycaps",
    "Ergonomic self-measurement": "IMU per half for tent and splay",
    "Sparse semantic lighting": "Semantic lighting from the keymap",
    "Memory-in-pixel": "Memory-LCD status strip",
    "Actuators as the speaker": "Actuators as a speaker",
    "Analog-force typing telemetry": "Force-based typing coaching",
    # MCU, connectivity and software
    "Twin-wire KVM": "Two-host KVM",
    "Keyboard authenticator": "Built-in FIDO2 authenticator",
    "On-device ergonomics telemetry": "On-device ergonomics telemetry",
    "Fit-to-you: typing data": "Typing data designs the next PCB",
    "Latency as a release gate": "Latency as a release gate",
    "Timestamped sub-millisecond": "Timestamped sub-ms wireless split",
    "One source for board": "One source for board, firmware and web app",
    "Behaviour flight recorder": "Tap/hold flight recorder and tuner",
    "Sandboxed on-device scripts": "Sandboxed WebAssembly scripts",
    "Adaptive-rate single-chip": "Adaptive-rate single chip (nRF54LM20A)",
    "Channel Sounding": "Channel Sounding walk-away lock",
    # Ergonomics and form
    "Pose-aware halves": "Pose-aware halves (sensed tent and tilt)",
    "Closed-loop motorized tenting": "Motorised tenting",
    "Sensed adjustable column rig": "Sensed adjustable column rig",
    "Generated keywell on flex": "Generated keywell",
    "Analog fingertip clusters": "Hall-effect 5-way fingertip clusters",
    "Geometry-aware strain analytics": "Strain analytics in mm and newtons",
    "Posture coach": "Capacitive palm rest and wrist ToF coach",
    "Sensed magnetic pod bus": "Magnetic pod bus for moving modules",
    "Programmable key force": "Electromagnetic per-key force",
    "Transforming body": "Transforming split / unibody / travel brick",
    # Designed-as-code
    "One layout source": "Keyboard compiler",
    "Fork-to-fab": "Fork-to-fab gated release",
    "Keyboard dyno": "Force, travel and latency dyno",
    "Per-unit calibration": "Per-unit calibration certificate",
    "Ergonomic Rule Check": "Ergonomic rule check as a gate",
    "Per-user fit": "Fit to your hand",
    "Unrolled keywell": "Exact per-user unrolled flex keywell",
    "Generated sensor geometry": "Generated coil geometry and test coupons",
    "Uniform feel by computation": "FEA-optimised flex cuts",
    "Telemetry-to-geometry loop": "Telemetry-to-geometry loop",
    "Strike-point sensing": "Strike-point sensing (3-axis Hall per key)",
    "Generated production test fixture": "Generated pogo-bed test fixture",
}
EXPECTED = {"picked": 12, "folded": 7, "not picked": 35}


def _match(name, table):
    hits = [p for p in table if name.startswith(p)]
    if len(hits) > 1:
        raise SystemExit(f"ambiguous prefix for {name!r}: {hits}")
    return hits[0] if hits else None


def rebuild_json(research_path):
    """Trim the raw research output into ideas.json (the scored ideas only, with the status rule applied)."""
    with open(research_path, encoding="utf-8") as f:
        raw = json.load(f)
    ideas = []
    for res in raw["results"]:
        lens = res["lens"]
        proposed = {i["name"] for i in res["ideas"]["ideas"]}
        for v in res["verdicts"]["verdicts"]:
            name = v["name"]
            if name not in proposed:
                raise SystemExit(f"verdict without a proposed idea: {name!r}")
            label_key = _match(name, LABELS)
            if label_key is None:
                raise SystemExit(f"no label for {name!r}")
            rec = {"lens": lens, "name": name, "label": LABELS[label_key], "score": v["score"],
                   "verdict": v["verdict"], "novelty": v["novelty"], "feasibility": v["feasibility"],
                   "daily_driver_value": v["daily_driver_value"], "status": "not picked", "section": None}
            for status in ("picked", "folded"):
                key = _match(name, STATUS_RULE[status])
                if key is not None:
                    rec["status"] = status
                    rec["section"] = STATUS_RULE[status][key]
                    if key in FOLDED_NOTE:
                        rec["note"] = FOLDED_NOTE[key]
            ideas.append(rec)
    out = {
        "source": "Keyboard desk research, 2026-11-25: five researchers proposed ideas, one sceptic per area "
                  "scored them. Opinions, not measurements. Four of the five sceptics could not search the web.",
        "fields": {
            "lens": "research area: " + ", ".join(f"{k} ({t})" for k, t in LENSES),
            "name": "the idea as the researcher named it",
            "label": "short name used in the figures and docs",
            "score": "the sceptic's 1-10 score for worth building",
            "verdict": "the sceptic's verdict: keep, keep_as_moonshot, demote, drop",
            "novelty": "the sceptic's rating: table_stakes, common, niche_exists, rare",
            "feasibility": "the sceptic's rating on this toolchain: straightforward, hard, research_needed, "
                           "impractical",
            "daily_driver_value": "the sceptic's rating: high, medium, low, gimmick",
            "status": "the owner's choice on 2026-11-25: picked (one of the 12 features in concept.md), folded "
                      "(supporting work folded into a picked feature), not picked",
            "section": "concept.md section of the picked feature, or of the feature a folded idea is part of",
        },
        "ideas": ideas,
    }
    with open(IDEAS_JSON, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
        f.write("\n")
    print(f"  wrote {IDEAS_JSON}  ({len(ideas)} ideas)")


def load_ideas():
    with open(IDEAS_JSON, encoding="utf-8") as f:
        ideas = json.load(f)["ideas"]
    counts = Counter(i["status"] for i in ideas)
    if dict(counts) != EXPECTED:
        raise SystemExit(f"status counts {dict(counts)} != expected {EXPECTED}")
    return ideas


# ---------------------------------------------------------------------------------------------------------------
# Shared drawing helpers. Every figure is drawn on one axes in inch coordinates (y grows downwards), so text and
# marks land where the layout says at any figure size.
# ---------------------------------------------------------------------------------------------------------------
def inch_canvas(w, h):
    fig = plt.figure(figsize=(w, h))
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, w)
    ax.set_ylim(h, 0)
    ax.axis("off")
    return fig, ax


def header(ax, w, title, subtitle_lines):
    ax.text(0.25, 0.22, title, ha="left", va="top", fontsize=14, color=INK, weight="bold")
    for k, line in enumerate(subtitle_lines):
        ax.text(0.25, 0.58 + 0.2 * k, line, ha="left", va="top", fontsize=9.5, color=INK2)


NOTE_PITCH = 0.18          # inches per note line


def footer_height(note_lines):
    return 0.42 + NOTE_PITCH * len(note_lines) + 0.12


def footer(ax, w, h, note_lines, source=SOURCE_NOTE, stamp=STAMP):
    """Note lines (secondary ink), then the source line, then the status stamp at the bottom right."""
    y = h - 0.42 - NOTE_PITCH * len(note_lines)
    for k, line in enumerate(note_lines):
        ax.text(0.25, y + NOTE_PITCH * k, line, ha="left", va="top", fontsize=8, color=INK2)
    ax.text(0.25, h - 0.3, source, ha="left", va="top", fontsize=8, color=INK2, style="italic")
    ax.text(w - 0.15, h - 0.12, stamp, ha="right", va="bottom", fontsize=8.5, color=STAMP_RED, weight="bold")


def marker(ax, x, y, status, scale=1.0, z=5):
    m, face, edge, size, _ = STATUS_STYLE[status]
    if status == "not picked":
        ax.plot(x, y, m, ms=size * scale, mfc=face, mec=edge, mew=1.6, zorder=z, clip_on=False)
    else:   # filled, with a ring in the surface colour
        ax.plot(x, y, m, ms=size * scale, mfc=face, mec=edge, mew=1.4, zorder=z, clip_on=False)


def legend_row(ax, x, y, statuses=STATUSES, gap=0.35):
    """A one-line legend: marker + text per status, laid out left to right (widths measured, not guessed)."""
    fig = ax.figure
    r = fig.canvas.get_renderer()
    for s in statuses:
        marker(ax, x + 0.07, y, s)
        t = ax.text(x + 0.2, y, STATUS_STYLE[s][4], ha="left", va="center", fontsize=9, color=INK)
        bb = t.get_window_extent(renderer=r)
        x += 0.2 + bb.width / fig.dpi + gap


def wrap_measured(ax, text, width_in, fontsize, **font):
    """textwrap.wrap at the widest character count whose longest line, as rendered, fits width_in inches."""
    fig = ax.figure
    rend = fig.canvas.get_renderer()
    n = max(8, int(width_in / (0.5 * fontsize / 72)))      # start a little wide of the average advance
    while True:
        lines = textwrap.wrap(text, n)
        widest = 0.0
        for line in lines:
            t = ax.text(0, 0, line, fontsize=fontsize, **font)
            widest = max(widest, t.get_window_extent(renderer=rend).width / fig.dpi)
            t.remove()
        if widest <= width_in or n <= 8:
            return lines
        n -= 1


def save(fig, name):
    """Write the PNG, then store it as a 256-colour palette image (flat colours survive this unchanged to the eye,
    at about half the size)."""
    from PIL import Image
    path = os.path.join(HERE, name)
    fig.savefig(path, dpi=DPI, facecolor="white")
    plt.close(fig)
    im = Image.open(path).convert("RGB").quantize(colors=256, method=Image.Quantize.MEDIANCUT,
                                                  dither=Image.Dither.NONE)
    im.save(path, optimize=True)
    print(f"  wrote {path}  ({os.path.getsize(path) / 1024:.0f} KB)")
    return path


# ---------------------------------------------------------------------------------------------------------------
# Figure 1: every idea's score, grouped by research area
# ---------------------------------------------------------------------------------------------------------------
def fig_scores(ideas):
    order = {s: k for k, s in enumerate(STATUSES)}
    groups = []
    for key, title in LENSES:
        rows = [i for i in ideas if i["lens"] == key]
        rows.sort(key=lambda i: (-i["score"], order[i["status"]], i["label"]))
        groups.append((title, rows))

    ROW, GROUP_HEAD, GROUP_GAP = 0.2, 0.44, 0.2
    TOP = 1.82                                   # below the title, subtitle and legend
    w = 9.6
    x_sec, x_label = 0.62, 3.95                  # section ref column (right-aligned), label column (right-aligned)
    x0, x1 = 4.2, 7.9                            # score 0 and score 10
    x_verdict = 8.12
    body = sum(GROUP_HEAD + ROW * len(r) for _, r in groups) + GROUP_GAP * (len(groups) - 1)
    note = [
        "Score: each research area's sceptic, 1-10, for worth building (novelty, feasibility on this toolchain,",
        "daily-driver value). One sceptic per area, so scores compare best within an area. Four of the five",
        "sceptics could not search the web. Ideas the sceptics added themselves carry no score and are not shown.",
        "§ = the concept.md section a picked idea became; → § = the feature a folded idea is part of.",
    ]
    h = TOP + 0.32 + body + 0.3 + footer_height(note)
    fig, ax = inch_canvas(w, h)

    picked = [i for i in ideas if i["status"] == "picked"]
    sevens = [i for i in ideas if i["score"] == 7]
    sub = [
        f"The sceptic's 1-10 score for each of the {len(ideas)} ideas the five researchers proposed, highest "
        "first in each area.",
        f"All {len(sevens)} ideas that scored 7 were picked. The owner also picked "
        f"{sum(i['score'] == 6 for i in picked)} that scored 6 and {sum(i['score'] == 5 for i in picked)} that "
        "scored 5",
        "(printed coils, a moonshot). No idea scored above 7.",
    ]
    header(ax, w, "The ideas we weighed, and the sceptic's scores", sub)
    legend_row(ax, 0.32, 1.42)

    def sx(score):
        return x0 + (x1 - x0) * score / 10

    def ticks(y, va):
        for s in range(0, 11):
            ax.text(sx(s), y, f"{s}", ha="center", va=va, fontsize=8.5, color=INK2)

    y = TOP + 0.32
    ticks(y - 0.08, "bottom")
    ax.text(x_verdict, y - 0.08, "sceptic's verdict", ha="left", va="bottom", fontsize=8.5, color=INK2)
    ax.text(x_label, y - 0.08, "score for worth building →", ha="right", va="bottom", fontsize=8.5,
            color=INK2)
    for gi, (title, rows) in enumerate(groups):
        n = Counter(i["status"] for i in rows)
        ax.text(0.25, y + 0.27, title, ha="left", va="center", fontsize=10.5, color=INK, weight="bold")
        tw = ax.texts[-1].get_window_extent(renderer=fig.canvas.get_renderer()).width / fig.dpi
        ax.text(0.25 + tw + 0.12, y + 0.275,
                f"{len(rows)} ideas: {n['picked']} picked, {n['folded']} folded, {n['not picked']} not picked",
                ha="left", va="center", fontsize=8.5, color=INK2)
        top = y + GROUP_HEAD - 0.06
        bottom = top + ROW * len(rows) + 0.02
        for s in range(0, 11):   # vertical grid hairlines, per group block
            ax.plot([sx(s), sx(s)], [top, bottom], color=GRID if s else AXIS, lw=0.7, zorder=1,
                    solid_capstyle="butt")
        for k, idea in enumerate(rows):
            yc = top + ROW * (k + 0.5) + 0.01
            st = idea["status"]
            weight = "bold" if st == "picked" else "normal"
            ax.text(x_label, yc, idea["label"], ha="right", va="center", fontsize=8.5,
                    color=INK if st != "not picked" else "#4a4a4a", weight=weight)
            if idea.get("section"):
                ref = f"§{idea['section']}" if st == "picked" else f"→ §{idea['section']}"
                ax.text(x_sec, yc, ref, ha="right", va="center", fontsize=8, color=INK2)
            stem = C_PICKED if st == "picked" else ("#f9b38f" if st == "folded" else "#dcdcdc")
            ax.plot([sx(0), sx(idea["score"])], [yc, yc], color=stem, lw=1.6 if st == "picked" else 1.2,
                    zorder=2)
            marker(ax, sx(idea["score"]), yc, st, z=4)
            ax.text(x_verdict, yc, VERDICT_TEXT[idea["verdict"]], ha="left", va="center", fontsize=8.5,
                    color=INK2)
        y = bottom + GROUP_GAP - 0.02
    ticks(y - GROUP_GAP + 0.06, "top")
    footer(ax, w, h, note)
    return save(fig, "data_idea_scores.png")


# ---------------------------------------------------------------------------------------------------------------
# Figure 2: novelty x feasibility
# ---------------------------------------------------------------------------------------------------------------
def fig_grid(ideas):
    x_axis_label = 0.25
    gx0 = 1.75                              # grid left edge
    # Column widths follow the text they hold, not the counts: the count is the number and the dots in a cell.
    col_w = {"table_stakes": 1.5, "common": 1.5, "niche_exists": 2.8, "rare": 2.8}
    col_x = {}
    x = gx0
    for nk, _ in NOVELTY:
        col_x[nk] = x
        x += col_w[nk]
    w = x + 0.25
    gy0 = 2.05                              # grid top edge (below the column headers)
    NAME_FS, NAME_LINE, NAME_GAP = 8.3, 0.155, 0.045
    note = [
        "Both axes are the sceptics' ratings, one sceptic per research area. Novelty is how much prior art the "
        "sceptic found or knew of;",
        "four of the five sceptics could not search the web, so some 'rare' ratings may be generous. Feasibility "
        "is on this toolchain",
        "(JLC assembly, LCSC stock, firmware, power). Each dot is one idea. Only the 12 picked ideas are named; "
        "research.md lists the rest.",
    ]
    fig, ax = inch_canvas(w, 20)            # a scratch canvas to measure the names on
    cells = {}
    for i in ideas:
        cells.setdefault((i["novelty"], i["feasibility"]), []).append(i)
    wrapped = {}
    for key, members in cells.items():
        members.sort(key=lambda i: (STATUSES.index(i["status"]), -i["score"], i["label"]))
        wrapped[key] = [wrap_measured(ax, f"{i['label']}\u00a0§{i['section']}", col_w[key[0]] - 0.45, NAME_FS)
                        for i in members if i["status"] == "picked"]
    plt.close(fig)

    def dot_rows(n):
        return (n - 1) // 10 + 1

    row_h = {}
    for fk, _ in FEASIBILITY:
        need = 0.62
        for nk, _ in NOVELTY:
            members = cells.get((nk, fk), [])
            if not members:
                continue
            names = wrapped[(nk, fk)]
            hgt = 0.25 + 0.2 * (dot_rows(len(members)) - 1) + 0.22
            if names:
                hgt += 0.08 + sum(len(n) * NAME_LINE + NAME_GAP for n in names)
            need = max(need, hgt + 0.12)
        row_h[fk] = max(need, 0.72)
    grid_h = sum(row_h.values())
    h = gy0 + grid_h + 0.42 + footer_height(note)
    fig, ax = inch_canvas(w, h)
    rend = fig.canvas.get_renderer()

    picked = [i for i in ideas if i["status"] == "picked"]
    n_rare = sum(1 for i in picked if i["novelty"] == "rare")
    sub = [
        f"Where the {len(ideas)} ideas sit on the sceptics' two ratings. Most ("
        f"{sum(i['novelty'] == 'niche_exists' for i in ideas)}) have some niche prior art; "
        f"{sum(i['novelty'] == 'rare' for i in ideas)} were rated rare.",
        f"The owner's 12 picks: {n_rare} rated rare and {len(picked) - n_rare} niche-exists; none rated table "
        "stakes or common, none impractical.",
    ]
    header(ax, w, "Novelty against feasibility, as the sceptics rated them", sub)
    legend_row(ax, 0.32, 1.3)

    def n_ideas(n):
        return f"{n} idea" + ("" if n == 1 else "s")

    col_tot = Counter(i["novelty"] for i in ideas)
    row_tot = Counter(i["feasibility"] for i in ideas)
    for nk, nt in NOVELTY:
        ax.text(col_x[nk] + col_w[nk] / 2, gy0 - 0.12, nt, ha="center", va="bottom", fontsize=10, color=INK,
                weight="bold")
    ax.text(col_x["niche_exists"], gy0 - 0.42, "novelty (the sceptic's rating), more novel to the right →",
            ha="center", va="bottom", fontsize=9, color=INK2)
    ax.text(x_axis_label, gy0 - 0.12, "feasibility\n(harder going down)", ha="left", va="bottom", fontsize=9,
            color=INK2, linespacing=1.3)

    y = gy0
    for fk, ft in FEASIBILITY:
        hh = row_h[fk]
        ax.text(gx0 - 0.15, y + 0.2, ft, ha="right", va="top", fontsize=10, color=INK, weight="bold")
        ax.text(gx0 - 0.15, y + 0.42, n_ideas(row_tot[fk]), ha="right", va="top", fontsize=8.5, color=INK2)
        for nk, _ in NOVELTY:
            cx0, cw = col_x[nk], col_w[nk]
            members = cells.get((nk, fk), [])
            pad = 0.04
            ax.add_patch(FancyBboxPatch((cx0 + pad, y + pad), cw - 2 * pad, hh - 2 * pad,
                                        boxstyle="round,pad=0,rounding_size=0.06",
                                        fc=SHADE if members else "white", ec="none" if members else GRID,
                                        lw=0.8, zorder=0))
            if not members:
                continue
            ax.text(cx0 + 0.16, y + 0.13, f"{len(members)}", ha="left", va="top", fontsize=15, color=INK,
                    weight="bold")
            nb = ax.texts[-1].get_window_extent(renderer=rend).width / fig.dpi
            dx0 = cx0 + 0.16 + nb + 0.18       # one dot per idea, rows of 10, right of the count
            for k, idea in enumerate(members):
                marker(ax, dx0 + 0.165 * (k % 10), y + 0.25 + 0.2 * (k // 10), idea["status"], scale=0.82)
            ny = y + 0.25 + 0.2 * (dot_rows(len(members)) - 1) + 0.3
            for lines in wrapped[(nk, fk)]:
                for li, line in enumerate(lines):
                    ax.text(cx0 + 0.3, ny, line, ha="left", va="top", fontsize=NAME_FS, color=INK)
                    if li == 0:
                        marker(ax, cx0 + 0.19, ny + 0.058, "picked", scale=0.62)
                    ny += NAME_LINE
                ny += NAME_GAP
        y += hh
    for nk, _ in NOVELTY:
        ax.text(col_x[nk] + col_w[nk] / 2, y + 0.08, n_ideas(col_tot[nk]), ha="center", va="top", fontsize=8.5,
                color=INK2)
    footer(ax, w, h, note)
    return save(fig, "data_novelty_feasibility.png")


# ---------------------------------------------------------------------------------------------------------------
# Figure 3: where the prior art lives, per chosen feature (from concept.md, sections 2.1-4.4)
# ---------------------------------------------------------------------------------------------------------------
# One row per chosen feature: (section, feature, commercial, open, research or patent, not found). Every entry is a
# name concept.md gives in that section's "Prior art" line, shortened; "not found" is its "New" line, shortened.
# "(unchecked)" marks what concept.md says came from the sceptic's memory and was not checked.
PRIOR_ART = [
    ("Headline hardware", [
        ("2.1", "Shear keys",
         ["Expressive E Osmose (lateral sensing per key, on a music keyboard)",
          "Lenovo TrackPoint, Tex Shinobi (a nub between G, H and B)",
          "Svalboard, DataHand, CharaChorder (multi-direction keys that replace typing)"],
         [],
         ["McPherson TouchKeys (CHI 2011)", "Buschek et al. (CHI 2018)"],
         "Pointing from normal-feel typing keys: any keycap, no nub"),
        ("2.2", "Generated keywell",
         ["TheBigSkree (generic flexible PCBs)"],
         ["YKB Skadi, 2026 (Hall-effect keywell on bendable column PCBs)",
          "Cosmos, open-core (keywell cases, column-flex PCBs)",
          "janaka's Dactyl flex, fmcraft's BastardKB flex (hand-drawn)"],
         [],
         "Boards generated from the case model, gated in their bent state"),
        ("2.3", "Haptic thumb wheel",
         ["Surface Dial (per-app vibration ticks)"],
         ["HelloWord, 2022 (FOC haptic knob in a keyboard)",
          "Hapticpad, 2026 (macropad with a haptic wheel)",
          "SmartKnob and derivatives (standalone)"],
         [],
         "A wheel in an ergonomic thumb cluster, driven by the board's profiles"),
        ("2.4", "Analog from stock switches (printed coils)",
         ["Epomaker Magcore (PCB coils, IQS9320 readers)",
          "Cherry inductive switches (Computex 2025)",
          "TI TIDA-00509 (coil keypad reference design)"],
         ["Spring-sensing DIY proofs of concept (Hackaday 2018, Pawnerd)"],
         ["Cherry calls its inductive approach patented"],
         "Analog from unmodified stock switches, if the signal holds up (unproven)"),
    ]),
    ("Daily driver", [
        ("3.1", "Two-host KVM",
         ["Logitech Easy-Switch (reconnects), Flow (host software)", "USB-C KVM monitors"],
         ["DeskHop (two RP2040s behind an isolator, a box)", "HID Remapper (dual RP2040, USB host)"],
         [],
         "Both hosts wired and enumerated at once, inside the keyboard"),
        ("3.2", "Tap/hold flight recorder and tuner",
         [],
         ["hrm-tuner (host-side logging for ZMK)",
          "ZMK debug logging, native_sim tests (unchecked)",
          "Keyboard Heaven's calibrator; KeyPath for Kanata"],
         [],
         "On-device capture with the firmware's reasons; tuning by replay through the real code"),
        ("3.3", "Context-aware feel",
         ["Surface Dial, Logitech MX Master 4 (per-app haptics)"],
         ["QMKonnect, auto_layers, komokana (layers by app)",
          "DRV2605L buzz on home-row-mod holds (DIY ZMK builds)"],
         [],
         "One tested profile drives detents, haptics and lights together"),
        ("3.4", "Per-finger analog tuning and load budget",
         ["SteelSeries Protection Mode (global accidental-press rejection)",
          "Phone keyboards' adaptive touch targets; Razer Synapse, WhatPulse heatmaps (unchecked)"],
         ["libhmk (manual per-key actuation)"],
         [],
         "Closed-loop per-key adaptation on analog mechanical keys"),
    ]),
    ("Toolchain showcase", [
        ("4.1", "Keyboard compiler",
         [],
         ["Ergogen (cases, un-routed PCB, no schematic)",
          "kicad-kbplacer (placement, label-wired schematic)",
          "Cosmos, open-core (cases, firmware, its own PCBs)",
          "Corney Island CI (Ergogen to Gerbers on push)"],
         [],
         "A readable wired schematic, ERC and parity, the jlcplace gate, cross-domain checks"),
        ("4.2", "Latency and battery gates",
         ["RTINGS, LTT Labs (solenoid and USB analyser)"],
         ["joelspadin's keyboard-latency-tester", "Michael Stapelberg's QMK latency measurements",
          "ZMK Power Profiler (not tied to a BOM)"],
         [],
         "Releases gated on measured latency and on battery life"),
        ("4.3", "Sensing testbed",
         ["Vendor blogs on Hall-effect against TMR (no raw data)"],
         ["ThereminGoat's force curves (mechanical only)"],
         [],
         "An open, measured comparison across sensing methods"),
        ("4.4", "Fit to your hand",
         [],
         ["Cosmos (keywell fitted from a phone hand scan, its own PCBs)",
          "Ergogen users hand-tune stagger and splay",
          "Squeezebox, FCS42S, key-yack (passive adjustable rigs)"],
         [],
         "A fitted, gated, JLC-assembled board per user"),
    ]),
]


def fig_prior(_ideas):
    cols = [  # (x left, width, header, sub-header)
        (0.25, 1.95, "Feature", "§ = concept.md section"),
        (2.25, 2.3, "Commercial product", "or vendor design"),
        (4.6, 2.3, "Open project", "or public write-up"),
        (6.95, 1.85, "Research or patent", ""),
        (8.85, 2.05, "Not found", "by this research: the new part"),
    ]
    w = cols[-1][0] + cols[-1][1] + 0.2
    FS = 8.3
    LINE = 0.152            # line pitch at FS, inches
    BLOCK_GAP = 0.05        # extra space between two entries in a cell
    note = [
        "Each entry is a name concept.md gives as prior art for that feature, shortened, in the column it fits. "
        "An empty cell means",
        "concept.md names nothing of that kind, not that nothing exists. 'Not found' means not found by this desk "
        "research, in which",
        "four of the five sceptics could not search the web. '(unchecked)' is concept.md's flag for the sceptic's "
        "unverified memory.",
    ]

    fig, ax = inch_canvas(w, 30)         # a scratch canvas: measure and wrap every cell first
    layout = []
    for gname, feats in PRIOR_ART:
        rows = []
        for sec, name, com, opn, res, new in feats:
            cells = [[wrap_measured(ax, it, wid - 0.36, FS) for it in items]
                     for items, (_, wid, *_r) in zip((com, opn, res), cols[1:4])]
            new_lines = wrap_measured(ax, new, cols[4][1] - 0.26, FS, style="italic")
            name_lines = wrap_measured(ax, name, cols[0][1] - 0.56, 8.8, weight="bold")
            cell_h = [sum(len(b) * LINE for b in c) + BLOCK_GAP * max(0, len(c) - 1) for c in cells]
            content = max([len(name_lines) * LINE, len(new_lines) * LINE] + cell_h)
            rows.append((sec, name_lines, cells, new_lines, content + 0.3))
        layout.append((gname, rows))
    plt.close(fig)

    TOP, HEAD, GHEAD = 1.32, 0.56, 0.36
    body = sum(GHEAD + sum(r[4] for r in rows) for _, rows in layout)
    h = TOP + HEAD + body + 0.3 + footer_height(note)
    fig, ax = inch_canvas(w, h)

    counts = [sum(bool(f[k]) for _, feats in PRIOR_ART for f in feats) for k in (2, 3, 4)]
    n_feat = sum(len(f) for _, f in PRIOR_ART)
    sub = [
        f"The closest prior art concept.md names for each of the {n_feat} chosen features, by where it lives: "
        f"commercial for {counts[0]}, open projects for {counts[1]},",
        f"research or patents for {counts[2]}. Every feature has prior art somewhere; the pitch is the part the "
        "research did not find (right-hand column).",
    ]
    header(ax, w, "Where the closest prior art lives, feature by feature", sub)

    table_bottom = TOP + HEAD + body
    y = TOP
    ax.add_patch(Rectangle((cols[4][0], y - 0.04), cols[4][1], table_bottom - y + 0.04, fc=TINT, ec="none",
                           zorder=0))
    for x, wid, title, subt in cols:
        ax.text(x + 0.1, y + 0.08, title, ha="left", va="top", fontsize=9.5, color=INK, weight="bold")
        if subt:
            ax.text(x + 0.1, y + 0.29, subt, ha="left", va="top", fontsize=8, color=INK2)
    y += HEAD
    ax.plot([0.25, w - 0.2], [y - 0.04, y - 0.04], color=AXIS, lw=0.9, solid_capstyle="butt")

    for gname, rows in layout:
        ax.text(0.25, y + 0.2, gname, ha="left", va="center", fontsize=10, color=INK2, weight="bold")
        y += GHEAD
        for sec, name_lines, cells, new_lines, rh in rows:
            ty = y + 0.15
            ax.text(cols[0][0] + 0.1, ty, f"§{sec}", ha="left", va="top", fontsize=8.5, color=INK2)
            for li, line in enumerate(name_lines):
                ax.text(cols[0][0] + 0.52, ty + li * LINE, line, ha="left", va="top", fontsize=8.8,
                        color=INK, weight="bold")
            for (x, wid, *_r), blocks in zip(cols[1:4], cells):
                if not blocks:
                    ax.text(x + 0.1, ty, "none named", ha="left", va="top", fontsize=FS, color="#b0b0b0")
                    continue
                ax.add_patch(FancyBboxPatch((x + 0.03, y + 0.06), wid - 0.08, rh - 0.12,
                                            boxstyle="round,pad=0,rounding_size=0.05", fc=SHADE, ec="none",
                                            zorder=0))
                yy = ty
                for b in blocks:
                    ax.plot(x + 0.15, yy + 0.058, "s", ms=3.4, mfc=C_PICKED, mec="none", zorder=3)
                    for line in b:
                        ax.text(x + 0.26, yy, line, ha="left", va="top", fontsize=FS, color=INK)
                        yy += LINE
                    yy += BLOCK_GAP
            for li, line in enumerate(new_lines):
                ax.text(cols[4][0] + 0.13, ty + li * LINE, line, ha="left", va="top", fontsize=FS, color=INK,
                        style="italic")
            y += rh
            ax.plot([0.25, w - 0.2], [y, y], color=GRID, lw=0.7, solid_capstyle="butt", zorder=1)
    footer(ax, w, h, note, source=SOURCE_NOTE_PRIOR, stamp=STAMP_PRIOR)
    return save(fig, "data_prior_art_matrix.png")


FIGURES = {"scores": fig_scores, "grid": fig_grid, "prior": fig_prior}


def main(argv):
    if argv[:1] == ["--rebuild-json"]:
        if len(argv) != 2:
            raise SystemExit("usage: data.py --rebuild-json RESEARCH.json")
        rebuild_json(argv[1])
        argv = []
    ideas = load_ideas()
    wanted = argv or list(FIGURES)
    for key in wanted:
        if key not in FIGURES:
            raise SystemExit(f"unknown figure {key!r}; choose from {', '.join(FIGURES)}")
        FIGURES[key](ideas)


if __name__ == "__main__":
    main(sys.argv[1:])
