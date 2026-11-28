#!/usr/bin/env python3
"""Fabrication and review outputs for a PrettyCool Keyboard rev A board, into keyboard/hardware/fab/<board>/.

usage: python keyboard/hardware/design/release.py --board NAME [--refit-jlc] [--force]

Outputs: gerbers.zip (+ gerbers/), drill + map, the JLCPCB BOM and CPL (the CPL written and checked by jlcplace), a
vendor-neutral BOM (the JLC BOM joined with mpn/<board>.csv; refused if a line has no row) and KiCad's own placement
file for other assemblers, ORDER-NOTES.md (the ordering condition at the top), the jlcplace preview checklist
(jlcplace-checklist.md) and review report (jlcplace-report.html, git-ignored: it draws EasyEDA pad outlines), the
schematic PDF, board PDFs (per side and per copper layer), 3D renders (top / bottom) and the DRC/parity report.

Gates (each refuses the package; --force writes a REVIEW-ONLY package instead, marked as such in ORDER-NOTES.md and
in a REVIEW-ONLY.txt next to it):

1. kicad-cli DRC with schematic parity must report no error.
2. jlcplace (tools/jlcplace_gate.py, >= 0.2.1): `jlcplace cpl` writes the CPL from the Gerbers' (0, 0) with the
   corrections stored in keyboard/hardware/design/jlcplace-db/, then `jlcplace check` simulates JLC's placement of
   every row with JLC's own EasyEDA footprints over gerbers.zip, with the BOM. Any red row or red run finding refuses
   the package. A second check without the database cross-checks the stored corrections against the EasyEDA records.
   --refit-jlc (network) runs `jlcplace fetch` and `jlcplace fit --db` first, for new or changed parts.

Warning, not a gate: any drill under 0.3 mm (vias and pad holes) is printed and listed in ORDER-NOTES.md (SPEC §9,
the owner's decision D5 of 2026-11-27; risks.md SF-3: small holes cost extra and can hold an order).

A part that is DNP in the schematic and carries a "Fit" field (the coupons' keyed slot header J1, D2 of 2026-11-27)
is bought and fitted by hand: it stays out of the JLC BOM and CPL, and release.py adds it to the vendor-neutral BOM
(from mpn/<board>.csv like every other line) and lists it in ORDER-NOTES.md. A board without one is unaffected.

Every text output is written with LF line endings, the JLC BOM and CPL included (tools/fab.py and jlcplace write
them CRLF; release.py rewrites them, and changes nothing else in them).

Board-specific order notes come from the board module (boards/<board>.py FAB_NOTES, and for a coupon the shared
notes of boards/coupon_common.py). Adapted from caliper/hardware/design/release.py.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HW = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(HW))
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, HERE)

import fab  # noqa: E402
import jlcplace_gate as jlcp  # noqa: E402

from build import project_name  # noqa: E402
from layout import board_module, cfg  # noqa: E402
from sheets import PROJECTS  # noqa: E402

JLC_DB = os.path.join(HERE, "jlcplace-db")       # jlcplace correction database (derived numbers only), committed
MPN_DIR = os.path.join(HERE, "mpn")
# The date the gates ran, for the status line of ORDER-NOTES.md: today (UTC), or $KBD_RELEASE_DATE (YYYY-MM-DD) to
# reproduce an earlier package byte for byte. It was a constant 2026-11-27 until a release ran past midnight.
RELEASE_DATE = os.environ.get("KBD_RELEASE_DATE") or datetime.datetime.now(datetime.timezone.utc).date().isoformat()

# The owner's ordering condition (2026-11-27): the KiCad projects, Gerbers, BoMs and enclosures are made now, but the
# two conditions of SPEC §1 gate ORDERING boards. Written at the top of every ORDER-NOTES.md. Condition 1 follows the
# owner's decision D6 of 2026-11-27 (SPEC §1, §2.1, §11 #1): ST's store is the purchase route and the owner buys.
ORDER_CONDITION = (
    "> **Do not order yet.** On 2026-11-27 the owner asked for everything needed to build rev A now, and moved the "
    "two conditions of SPEC §1 from capture to ordering: boards are ordered only once (1) **the MCUs are in hand**: "
    "STM32U5A5VJT6, or the pin-compatible STM32U599VJT6 or STM32U595VJT6 (not the -Q parts), bought by the owner from "
    "ST's own store (the owner's decision D6 of 2026-11-27; no agent buys anything), and (2) **8 kHz HID is proven on "
    "the NUCLEO-U5A5ZJ-Q** with Zephyr's `usbd` (bInterval 1, rate and jitter measured for at least 10 minutes on "
    "Windows and Linux with CDC logging active). Both are open. If either fails, the NXP i.MX RT1021 is the fallback "
    "and the testbed is redrawn for it (keyboard/hardware/design/SPEC.md §1).")


def kicad_cli():
    return os.environ.get("KICAD_CLI", "kicad-cli")


def kicad_version():
    r = subprocess.run([kicad_cli(), "version"], capture_output=True, text=True)
    return r.stdout.strip() or "?"


MODELS_TAG = "10.0.8"
MODELS_URL = "https://gitlab.com/kicad/libraries/kicad-packages3D/-/raw/{tag}/{path}"


def model_dir(pcb):
    """KiCad's 3D model library for the renders: $KICAD10_3DMODEL_DIR if it exists, else a per-user cache that gets
    the models this board uses from kicad-packages3D at the KiCad tag (network; a model that cannot be fetched is
    left out of the render, with a warning). Nothing from it is committed."""
    env = os.environ.get("KICAD10_3DMODEL_DIR")
    if env and os.path.isdir(env):
        return env
    import urllib.request
    import pcbnew
    cache = os.path.join(os.path.expanduser("~"), ".cache", "kicad-3dmodels", MODELS_TAG)
    names = {m.m_Filename for fp in pcbnew.LoadBoard(pcb).GetFootprints() for m in fp.Models()}
    for name in sorted(names):
        if not name.startswith("${KICAD10_3DMODEL_DIR}/"):
            continue
        rel = name.split("/", 1)[1]
        dst = os.path.join(cache, rel)
        if os.path.exists(dst):
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            with urllib.request.urlopen(MODELS_URL.format(tag=MODELS_TAG, path=rel), timeout=60) as r:
                data = r.read()
            with open(dst, "wb") as f:
                f.write(data)
        except Exception as e:  # noqa: BLE001 - a render without a model is still a render
            print(f"WARN: 3D model {rel} not fetched ({e}); it is missing from the renders")
    return cache


def render3d(pcb, png, side, zoom=1.0, size=(1600, 1200), models=None):
    cmd = [kicad_cli(), "pcb", "render", "-o", png, "--width", str(size[0]), "--height", str(size[1]), "--side", side,
           "--background", "opaque", "--quality", "high", "--zoom", str(zoom), pcb]
    if shutil.which("xvfb-run"):
        cmd = ["xvfb-run", "-a"] + cmd
    env = dict(os.environ, KICAD10_3DMODEL_DIR=models) if models else None
    r = subprocess.run(cmd, capture_output=True, timeout=900, text=True, env=env)
    if r.returncode != 0 or not os.path.exists(png):
        print(f"WARN: render {side} failed: {r.stderr.strip()[-300:]}")
    return png


def board_pdf(pcb, pdf, layers):
    subprocess.run([kicad_cli(), "pcb", "export", "pdf", "--layers", ",".join(layers), "--mode-single",
                    "--include-border-title", "-o", pdf, pcb], capture_output=True)
    return pdf


def sync_fields(pcb, net):
    """Copy value/DNP and every symbol field from the netlist onto the board footprints (hidden)."""
    import pcbnew
    import pcbgen
    comps, _ = pcbgen.load_netlist(net)
    b = pcbnew.LoadBoard(pcb)
    changed = 0
    for fp in b.GetFootprints():
        c = comps.get(fp.GetReference())
        if not c:
            continue
        if fp.GetValue() != c["value"]:
            fp.SetValue(c["value"])
            changed += 1
        dnp = "dnp" in c["props"] or bool(c["fields"].get("DNP"))
        if fp.IsDNP() != dnp:
            fp.SetDNP(dnp)
            changed += 1
        for k, v in c["fields"].items():
            if k not in ("Reference", "Value", "Footprint") and pcbgen.set_field_hidden(fp, k, v):
                changed += 1
    if changed:
        pcbnew.SaveBoard(pcb, b)
    return changed


def to_lf(path):
    """Rewrite a text file with LF line endings (the repository's, .gitattributes). tools/fab.jlc_bom writes the JLC
    BOM with the csv module's CRLF and `jlcplace cpl` writes the CPL with CRLF; the caliper's committed copies are
    LF only because git normalises them. Returns True if anything changed."""
    if not os.path.exists(path):
        return False
    with open(path, "rb") as f:
        data = f.read()
    lf = data.replace(b"\r\n", b"\n")
    if lf != data:
        with open(path, "wb") as f:
            f.write(lf)
    return lf != data


MIN_DRILL_MM = 0.30          # SPEC §9 (owner's decision D5 of 2026-11-27; risks.md SF-3): warn on any smaller drill


def small_drills(pcb, limit=MIN_DRILL_MM):
    """Every drilled hole under `limit` mm (vias, and pad holes on either axis of a slot): [(what, drill mm)], and the
    smallest drill on the board as (what, drill mm). JLC charges extra for small holes and they can hold an order
    (risks.md SF-3), so release.py warns; it does not refuse."""
    import pcbnew
    b = pcbnew.LoadBoard(pcb)
    holes = []
    for t in b.GetTracks():
        if t.Type() == pcbnew.PCB_VIA_T:
            holes.append((f"via {t.GetNetname() or '(no net)'}", pcbnew.ToMM(t.GetDrillValue())))
    for fp in b.GetFootprints():
        for p in fp.Pads():
            d = p.GetDrillSize()
            if d.x > 0 and d.y > 0:
                holes.append((f"{fp.GetReference()}.{p.GetNumber() or '?'}", pcbnew.ToMM(min(d.x, d.y))))
    small = sorted((h for h in holes if h[1] < limit - 1e-6), key=lambda h: (h[1], h[0]))
    smallest = min(holes, key=lambda h: h[1]) if holes else None
    return small, smallest


def gate(pcb, out):
    """DRC + schematic parity, errors only. Returns (ok, report path, summary line)."""
    rpt = os.path.join(out, "drc-parity.rpt")
    r = subprocess.run([kicad_cli(), "pcb", "drc", "--schematic-parity", "--severity-error",
                        "--exit-code-violations", "-o", rpt, pcb], capture_output=True, text=True)
    summary = [ln.strip() for ln in open(rpt, encoding="utf-8") if ln.startswith("** Found")]
    return r.returncode == 0, rpt, "; ".join(summary)


def hand_fitted(pcb, net):
    """Parts the assembler does not place but that are bought and fitted by hand: DNP in the schematic with a "Fit"
    field (sheets/coupon_common.py: the keyed slot header J1, D2 of 2026-11-27). [(ref, comp, side)] in ref order."""
    import pcbnew
    import pcbgen
    comps, _ = pcbgen.load_netlist(net)
    sides = {fp.GetReference(): ("bottom" if fp.IsFlipped() else "top") for fp in pcbnew.LoadBoard(pcb).GetFootprints()}
    return [(r, c, sides.get(r, "?")) for r, c in sorted(comps.items(), key=lambda kv: fab._refkey(kv[0]))
            if c["footprint"] and ("dnp" in c["props"] or c["fields"].get("DNP")) and c["fields"].get("Fit")]


def generic_bom(board, out, proj, hand=()):
    """Vendor-neutral BOM: the JLC BOM joined with mpn/<board>.csv (LCSC code -> manufacturer part, distributor
    numbers, note), then the hand-fitted parts (`hand`, from hand_fitted(): not in JLC's BOM, still to be bought).
    Refuses if a line has no row."""
    path_map = os.path.join(MPN_DIR, f"{board}.csv")
    if not os.path.exists(path_map):
        raise SystemExit(f"generic BOM: {path_map} is missing (one row per LCSC code of the board)")
    with open(path_map, encoding="utf-8") as f:
        mp = {r["LCSC"]: r for r in csv.DictReader(ln for ln in f if not ln.startswith("#"))}
    side = {}
    cpl_path = os.path.join(out, f"{proj}-CPL-JLCPCB.csv")
    if os.path.exists(cpl_path):
        with open(cpl_path, encoding="utf-8") as f:
            side = {r["Designator"]: r["Layer"].lower() for r in csv.DictReader(f)}
    rows, missing = [], []
    with open(os.path.join(out, f"{proj}-BOM-JLCPCB.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            m = mp.get(r["LCSC Part #"])
            if m is None:
                missing.append(f"{r['Designator']} ({r['LCSC Part #'] or 'no LCSC code'})")
                continue
            refs = r["Designator"].split(",")
            rows.append({"Designator": r["Designator"], "Qty": r["Qty"], "Value": r["Comment"],
                         "Footprint": r["Footprint"], "Side": "/".join(sorted({side.get(x, "?") for x in refs})),
                         "Manufacturer": m["Manufacturer"], "MPN": m["MPN"], "DigiKey": m["DigiKey"],
                         "Mouser": m["Mouser"], "LCSC": r["LCSC Part #"], "Note": m["Note"]})
    for ref, c, sd in hand:
        code = c["fields"].get("LCSC", "")
        m = mp.get(code)
        if m is None:
            missing.append(f"{ref} ({code or 'no LCSC code'}, hand-fitted)")
            continue
        rows.append({"Designator": ref, "Qty": 1, "Value": c["value"], "Footprint": c["footprint"].split(":")[-1],
                     "Side": sd, "Manufacturer": m["Manufacturer"], "MPN": m["MPN"], "DigiKey": m["DigiKey"],
                     "Mouser": m["Mouser"], "LCSC": code,
                     "Note": f"NOT IN THE JLC BOM/CPL (DNP for the assembler), fitted by hand after assembly: "
                             f"{c['fields']['Fit']}; " + m["Note"]})
    if missing:
        raise SystemExit(f"generic BOM: no {os.path.basename(path_map)} row for {', '.join(missing)}")
    path = os.path.join(out, f"{proj}-BOM-generic.csv")
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return path, len(rows)


def jlc_gate(board, pcb, out, tmp, proj, force, refit):
    """Write the CPL with jlcplace and run `jlcplace check` over gerbers.zip. Returns (ok, ORDER-NOTES lines)."""
    ver = jlcp.version()
    gerbers = os.path.join(out, "gerbers.zip")
    report = os.path.join(out, "jlcplace-report.html")
    checklist = os.path.join(out, "jlcplace-checklist.md")
    bom = os.path.join(out, f"{proj}-BOM-JLCPCB.csv")
    cpl = os.path.join(out, f"{proj}-CPL-JLCPCB.csv")
    os.makedirs(JLC_DB, exist_ok=True)
    if refit:
        try:
            print(f"[{board}] jlcplace fetch + fit --db (network)")
            jlcp.refit(pcb, JLC_DB, bom)
        except jlcp.JlcplaceError as e:
            print(f"WARN: [{board}] could not refit the jlcplace database: {e}")
    red_cpl, text = jlcp.write_cpl(pcb, cpl, bom=bom, gerbers=gerbers, db=JLC_DB, force=force)
    if red_cpl and not force:
        raise SystemExit(f"[{board}] jlcplace cpl: red rows, no CPL written (use --force for a review-only "
                         f"package):\n{text.strip()}")
    to_lf(cpl)                                   # jlcplace writes CRLF; the repository is LF (checked as written)
    res = jlcp.check(pcb, cpl, os.path.join(tmp, "jlcplace.json"), bom=bom, gerbers=gerbers, db=JLC_DB,
                     report=report, checklist=checklist)
    # the same CPL from the EasyEDA records alone: a stored auto correction may not turn a red row green
    jlcp.add_cross_check(res, jlcp.check(pcb, cpl, os.path.join(tmp, "jlcplace-records.json"), bom=bom,
                                         gerbers=gerbers))
    print(f"[{board}] jlcplace {'.'.join(map(str, ver))}: {res['summary_line']}")
    for p in jlcp.problem_lines(res):
        print(f"  RED {p}")
    if res["red"] and not force:
        raise SystemExit(f"[{board}] jlcplace check: red (see {report}); refusing to write the package "
                         "(use --force for a review-only package)")
    return not res["red"], jlcp.order_lines(res, ver)


def order_notes(board, mod, pcb, net, path, review_only, jlc_lines, gate_line, small=(), hand=()):
    import pcbnew
    import pcbgen
    comps, _ = pcbgen.load_netlist(net)
    b = pcbnew.LoadBoard(pcb)
    dnp = sorted((r for r, c in comps.items() if "dnp" in c["props"] or c["fields"].get("DNP")), key=fab._refkey)
    excluded = sorted((r for r, c in comps.items() if "exclude_from_bom" in c["props"] and c["footprint"]),
                      key=fab._refkey)
    bottom = sorted((fp.GetReference() for fp in b.GetFootprints()
                     if fp.IsFlipped() and not fp.GetAttributes() & pcbnew.FP_EXCLUDE_FROM_POS_FILES
                     and not fp.IsDNP()), key=fab._refkey)
    tht = sorted((fp.GetReference() for fp in b.GetFootprints()
                  if fp.GetAttributes() & pcbnew.FP_THROUGH_HOLE and not fp.GetAttributes() & pcbnew.FP_EXCLUDE_FROM_BOM
                  and not fp.IsDNP()), key=fab._refkey)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"# Order notes: {os.path.basename(pcb)}\n\n")
        f.write(ORDER_CONDITION + "\n\n")
        f.write("(generated by keyboard/hardware/design/release.py; do not edit)\n\n")
        if review_only:
            f.write("> **REVIEW-ONLY PACKAGE: do not order.** It was written with `--force`: the DRC/parity gate or "
                    "the jlcplace placement gate did not pass (see below and drc-parity.rpt).\n\n")
        f.write(f"**Status:** captured, laid out, routed and gated (ERC/DRC/parity/jlcplace) on {RELEASE_DATE}; "
                "not built, not measured.\n\n")
        f.write(f"* DRC/parity gate (kicad-cli {kicad_version()}, errors only): {gate_line}\n")
        f.write(f"* Do not place (DNP): {', '.join(dnp) or 'none'}\n")
        f.write(f"* Not assembled, not in BOM/CPL: {', '.join(excluded) or 'none'}\n")
        f.write(f"* Bottom-side placements ({len(bottom)}): {', '.join(bottom) or 'none'}\n")
        f.write(f"* Through-hole parts in the BOM ({len(tht)}): {', '.join(tht) or 'none'}\n")
        if hand:                                    # only when there is one: other boards keep their notes as before
            f.write(f"* **Fitted by hand after assembly** (DNP for the assembler, not in the JLC BOM or CPL; bought "
                    f"separately, listed in the vendor-neutral BOM): "
                    + "; ".join(f"{r} ({c['fields'].get('LCSC', '')}, {c['value']}, {sd}): {c['fields']['Fit']}"
                                for r, c, sd in hand) + "\n")
        if small:                                   # only when there is one: a board without keeps its notes as before
            sizes = sorted({round(d, 3) for _w, d in small})
            f.write(f"* **Drills under {MIN_DRILL_MM:.2f} mm ({len(small)}: "
                    f"{', '.join(f'{d:g} mm' for d in sizes)}; {', '.join(w for w, _d in small[:8])}"
                    f"{' ...' if len(small) > 8 else ''}):** JLC charges extra for small holes and they can hold an "
                    "order (SPEC §9, risks.md SF-3); use 0.60 / 0.30 mm vias unless the board needs smaller.\n")
        for ln in jlc_lines:
            f.write(ln + "\n")
        for note in cfg(mod, "FAB_NOTES", []):
            f.write(f"* {note}\n")
    return path


def release(board, force=False, refit=False):
    mod = board_module(board)
    kdir = os.path.join(HW, "kicad", board)
    proj = project_name(board)
    pcb = os.path.join(kdir, proj + ".kicad_pcb")
    sch = os.path.join(kdir, proj + ".kicad_sch")
    if not os.path.exists(pcb):
        raise SystemExit(f"{pcb} not found: run build.py and layout.py --route for {board} first")
    out = os.path.join(HW, "fab", board)
    os.makedirs(out, exist_ok=True)
    for name in os.listdir(out):           # empty the folder (a shell sitting in it would make rmdir fail)
        p = os.path.join(out, name)
        if os.path.isdir(p) and not os.path.islink(p):
            shutil.rmtree(p)
        else:
            os.remove(p)
    tmp = os.path.join(out, ".tmp")
    os.makedirs(tmp)
    # a fresh netlist from the schematic, kept out of the project (the committed .net belongs to the schematic track)
    net = os.path.join(tmp, proj + ".net")
    subprocess.run([kicad_cli(), "sch", "export", "netlist", "-o", net, sch], check=True, capture_output=True)
    print(f"[{board}] synced {sync_fields(pcb, net)} footprint fields from the schematic")
    ok, rpt, gate_line = gate(pcb, out)
    print(f"[{board}] DRC/parity gate: {'PASS' if ok else 'FAIL'} ({gate_line})")
    review_only = not ok
    if not ok and not force:
        raise SystemExit(f"DRC/parity violations in {pcb} - see {rpt}; refusing to write fab outputs "
                         "(use --force for a review-only package)")
    small, smallest = small_drills(pcb)
    if small:
        print(f"WARN: [{board}] {len(small)} drill(s) under {MIN_DRILL_MM:.2f} mm (SPEC §9, D5 of 2026-11-27): "
              + ", ".join(f"{w} {d:g} mm" for w, d in small[:12]) + (" ..." if len(small) > 12 else ""))
    else:
        print(f"[{board}] drills: none under {MIN_DRILL_MM:.2f} mm"
              + (f" (smallest {smallest[1]:g} mm, {smallest[0]})" if smallest else ""))
    fab.gerbers(pcb, out, mod.LAYERS)
    fab.jlc_bom(net, os.path.join(out, f"{proj}-BOM-JLCPCB.csv"))
    to_lf(os.path.join(out, f"{proj}-BOM-JLCPCB.csv"))   # tools/fab.py writes CRLF (csv default); keep tools/ as is
    try:
        try:
            jlc_ok, jlc_lines = jlc_gate(board, pcb, out, tmp, proj, force, refit)
        except jlcp.JlcplaceError as e:
            if not force:
                raise SystemExit(f"[{board}] jlcplace could not run: {e} (use --force for a review-only package)")
            jlc_ok, jlc_lines = False, [f"* **jlcplace placement gate did not run:** {e}"]
    except SystemExit:
        with open(os.path.join(out, "REVIEW-ONLY.txt"), "w") as f:
            f.write("INCOMPLETE: release.py was refused by the jlcplace placement gate. Do not order. "
                    "Fix the red rows (see jlcplace-report.html) and release again.\n")
        raise
    review_only = review_only or not jlc_ok
    hand = hand_fitted(pcb, net)
    gpath, n = generic_bom(board, out, proj, hand)
    fab.pos_csv(pcb, os.path.join(out, f"{proj}-pos-generic.csv"))
    jlc_lines = list(jlc_lines) + [
        f"* **Other assemblers:** `{os.path.basename(gpath)}` ({n} lines: manufacturer parts from "
        f"`keyboard/hardware/design/mpn/{board}.csv`) and `{proj}-pos-generic.csv` (KiCad's placement file: "
        "library-zero rotations, not JLC's)."]
    order_notes(board, mod, pcb, net, os.path.join(out, "ORDER-NOTES.md"), review_only, jlc_lines, gate_line, small,
                hand)
    if review_only:
        with open(os.path.join(out, "REVIEW-ONLY.txt"), "w") as f:
            f.write("REVIEW-ONLY package written with --force: do not order. See ORDER-NOTES.md.\n")
    subprocess.run([kicad_cli(), "sch", "export", "pdf", "-o", os.path.join(out, f"{proj}-schematic.pdf"), sch],
                   capture_output=True)
    cu = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"] if mod.LAYERS == 4 else ["F.Cu", "B.Cu"]
    board_pdf(pcb, os.path.join(out, f"{proj}-top.pdf"), ["F.Cu", "F.Silkscreen", "F.Fab", "Edge.Cuts"])
    board_pdf(pcb, os.path.join(out, f"{proj}-bottom.pdf"), ["B.Cu", "B.Silkscreen", "B.Fab", "Edge.Cuts"])
    for layer in cu:
        board_pdf(pcb, os.path.join(out, f"{proj}-{layer.replace('.', '_')}.pdf"), [layer, "Edge.Cuts"])
    zoom, size = cfg(mod, "RENDER", (1.0, (1600, 1200)))
    models = model_dir(pcb)
    render3d(pcb, os.path.join(out, f"{proj}-3d-top.png"), "top", zoom, size, models)
    render3d(pcb, os.path.join(out, f"{proj}-3d-bottom.png"), "bottom", zoom, size, models)
    shutil.rmtree(tmp)
    return out, review_only


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", required=True, choices=sorted(PROJECTS))
    ap.add_argument("--force", action="store_true", help="write a review-only package even if a gate fails")
    ap.add_argument("--refit-jlc", dest="refit", action="store_true",
                    help="jlcplace fetch (network) + fit --db: store corrections for new or changed parts")
    a = ap.parse_args()
    out, review = release(a.board, a.force, a.refit)
    print(f"[{a.board}] ->", out, "(REVIEW ONLY)" if review else "")


if __name__ == "__main__":
    main()
