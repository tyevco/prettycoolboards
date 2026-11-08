#!/usr/bin/env python3
"""Produce fabrication + review outputs for each PrettyCool Caliper board into caliper/hardware/fab/<board>/.

usage: python3 caliper/hardware/design/release.py [--board slider|scale] [--refit-jlc] [--force]

Adapted from dial-me-spinner's hardware/design/release.py. Outputs: gerbers.zip (+ gerbers/), drill + map, the
JLCPCB BOM + CPL (slider only; the scale has no parts), ORDER-NOTES.md, the jlcplace preview checklist
(jlcplace-checklist.md) and review report (jlcplace-report.html, git-ignored: it draws EasyEDA pad outlines), schematic
PDF, board PDFs (per side and per copper layer), 3D renders (top/bottom) and the DRC/parity report the gate ran.

Gates (each refuses the package; --force writes a REVIEW-ONLY package instead, marked as such in ORDER-NOTES.md and in
a REVIEW-ONLY.txt next to it):

1. kicad-cli DRC with schematic parity must report no error.
2. jlcplace (github.com/tyevco/jlcplace, >= 0.2.1, tools/jlcplace_gate.py): `jlcplace cpl` writes the CPL from the
   Gerbers' (0, 0) with the corrections stored in caliper/hardware/design/jlcplace-db/, then `jlcplace check` simulates
   JLC's placement of every row with JLC's own EasyEDA footprints over gerbers.zip, with the BOM. Any red row or red
   run finding refuses the package. The yellow rows and the preview checklist go into ORDER-NOTES.md. A second check
   without the database cross-checks the stored corrections against the EasyEDA records: a row the records alone call
   red must be accepted by a human decision in the database (manual, preview- or board-verified), else it is red too.
   The scale (no parts) is checked with an empty CPL: nothing on it may need placing, and its Gerbers must be this
   board's.

The check reads the EasyEDA record cache (~/.cache/jlcplace) and the committed database; it downloads nothing.
--refit-jlc (network) runs `jlcplace fetch` for the board's and the BOM's LCSC codes and `jlcplace fit --db` to store
corrections for new or changed parts. Without it, a part missing from the database is fitted from the cache for this
run only (and a part with neither record nor correction is not simulated: red unless a two-pad non-polar part).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HW = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(HW))
sys.path.insert(0, os.path.join(REPO, "tools"))

import fab  # noqa: E402
import jlcplace_gate as jlcp  # noqa: E402

JLC_DB = os.path.join(HERE, "jlcplace-db")  # jlcplace correction database (derived numbers only), committed
LIB = "caliper"
BOARDS = {"slider": 4, "scale": 2}

# what JLC cannot read from the gerbers, written into each board's ORDER-NOTES.md
FAB_NOTES = {
    "slider": [
        "**PCB:** 4 layers, **1.0 mm** finished thickness, FR-4, **ENIG** (flat pads for the 0.4 mm-pitch DSBGA, "
        "the LGA module and the bare electrode copper), green mask, white silk, 1 oz outer / 0.5 oz inner copper.",
        "**Stack-up:** JLC's standard symmetric 1.0 mm 4-layer impedance stack (the layout assumed a ~0.1 mm L1-L2 "
        "prepreg; read the exact stack ID and dielectric thickness from JLC's impedance calculator when ordering). "
        "Symmetric is required by the flatness callout. L1 F.Cu signals, L2 In1 solid GND, L3 In2 +3V3 pour / signals "
        "/ electrode phase buses, L4 B.Cu sensors. **No impedance control** (it would buy nothing): USB_DP/USB_DM "
        "are full-speed USB (12 Mb/s); they run as a pair of 0.14 mm tracks with a 0.18 mm gap mostly on L4 over a GND strip on L3 "
        "(an L4-over-L3 pair, not the L1-over-L2 microstrip the 0.14 mm class width was estimated for), so there is "
        "no specified structure for JLC to tune (layout review 2026-11-08, docs/electronics.md §7.5).",
        "**Flatness callout (SPEC D3):** bow/twist <= 0.03 mm over y 0-20 mm (the beam band, x -6...68 incl. the end "
        "tabs), assembled board on a surface plate, 100 % inspected, reject above. IPC-6012 class 2 (0.75 %) would allow "
        "0.55 mm: put this in the order remark and agree it before ordering; it may need a quote.",
        "**Copper balance:** copper is poured on all four layers in the beam band (y 0-20) on purpose; do not remove it.",
        "**Vias:** 0.40/0.20 mm signal vias, 0.45-0.50/0.20-0.25 mm GND/power vias; tented on **both** sides "
        "(no via opening in either mask gerber). The exceptions are the 64 electrode finger vias and the RX feed via: "
        "they sit inside the bottom electrode mask apertures, so they are open on the bottom and tented on top (no "
        "plugging needed; epoxy-filled + capped is acceptable if JLC prefers).",
        "**Bottom side, beam band (y 0-20):** only U30 (AS5311) and C30/C31 are assembled there (<= 1.30 mm). The E40 "
        "electrode copper is bare (mask open per finger, no paste, no part).",
        "**Assembly:** both sides. Top = everything else; bottom = U30, C30, C31 (beam band) and C21, C23 (0402, under "
        "the module's 3V3 pad, upper band); nothing else is placed on the bottom (the 19 test pads are bare). If "
        "two-sided assembly is not wanted, these five can be hand-soldered (U30 is TSSOP-20, 0.65 mm pitch).",
        "**AS5311 supply:** U30 AS5311-ATST (LCSC C22459687) had only 80 pcs at LCSC on 2026-11-07. Check stock when "
        "ordering; if it is gone, order the board with U30 as DNP and consign/hand-fit the part (Mouser/DigiKey stock "
        "it as AS5311-ATST / AS5311-ATSU).",
        "**SMT M2 standoffs on H2-H5 (tab clamp holes, SPEC D3):** not in this BOM: fitted by hand (reflow or iron) on "
        "the top pads (PEM SMTSO-M2-2ET class, 2.0 mm tall, OD <= 4.0). The LCSC M2 SMT nuts (SMTSO20x0CTJ, e.g. "
        "C2915626) have a 5.6 mm base that overhangs the 6 mm tabs.",
        "**Not on the PCBA:** the LCD panel (plugs into J50 by hand), the LiPo (J2), the magnetic tape and the scale "
        "board.",
    ],
    "scale": [
        "**PCB:** 2 layers, **0.8 mm**, ENIG, 200 x 7 mm. **No solder mask on the front (F) side at all**: the whole "
        "front is one mask opening over the reflector pattern (bare ENIG copper is the electrode face). Back: solid "
        "copper under green mask, white silk on the back only.",
        "**No assembly.** No BOM, no CPL. Two Ø1.0 non-plated alignment holes (pin jig for bonding), two fiducials.",
        "**Front copper is 38 isolated islands (no net) by design**: tell JLC's DFM review the floating copper is intended "
        "(it is a passive capacitive reflector scale).",
        "**Flatness:** the scale is bonded flush into the beam pocket with 3M 467MP; ask for the standard bow/twist and "
        "inspect; the pocket and adhesive take up <= 0.05 mm.",
        "**Panelising:** 200 mm is inside JLC's standard size; order as a single board (no V-cut near the pattern).",
    ],
}


def kicad_cli():
    return os.environ.get("KICAD_CLI", "kicad-cli")


def render3d(pcb, png, side, zoom=1.0, size=(1600, 1000)):
    cmd = [kicad_cli(), "pcb", "render", "-o", png, "--width", str(size[0]), "--height", str(size[1]), "--side", side,
           "--background", "opaque", "--quality", "high", "--zoom", str(zoom), pcb]
    if shutil.which("xvfb-run"):
        cmd = ["xvfb-run", "-a"] + cmd
    r = subprocess.run(cmd, capture_output=True, timeout=900, text=True)
    if r.returncode != 0 or not os.path.exists(png):
        print(f"WARN: render {side} failed: {r.stderr.strip()[-300:]}")
    return png


def board_pdf(pcb, pdf, layers):
    subprocess.run([kicad_cli(), "pcb", "export", "pdf", "--layers", ",".join(layers), "--mode-single",
                    "--include-border-title", "-o", pdf, pcb], capture_output=True)
    return pdf


def sync_fields(pcb, net):
    """Copy value/MPN/LCSC/Manufacturer/DNP from the netlist onto the board footprints."""
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
        for k in ("MPN", "LCSC", "Manufacturer"):
            v = c["fields"].get(k)
            current = fp.GetFieldText(k) if fp.HasFieldByName(k) else None
            if v and current != v:
                fp.SetField(k, v)
                fld = fp.GetFieldByName(k)
                if fld:
                    fld.SetVisible(False)
                changed += 1
        if pcbgen.set_description(fp, c["fields"].get("Description")):
            changed += 1
        # KiCad 10's parity also compares Datasheet and custom fields (KiCad 9 does not): keep them in step too
        for k in ("Datasheet", "JLC"):
            if pcbgen.set_field_hidden(fp, k, c["fields"].get(k)):
                changed += 1
    if changed:
        pcbnew.SaveBoard(pcb, b)
    return changed


def gate(pcb, out):
    """DRC + schematic parity, errors only. Returns (ok, report path, summary line)."""
    rpt = os.path.join(out, "drc-parity.rpt")
    r = subprocess.run([kicad_cli(), "pcb", "drc", "--schematic-parity", "--severity-error",
                        "--exit-code-violations", "-o", rpt, pcb], capture_output=True, text=True)
    summary = [ln.strip() for ln in open(rpt, encoding="utf-8") if ln.startswith("** Found")]
    return r.returncode == 0, rpt, "; ".join(summary)


def order_notes(board, pcb, net, path, review_only, jlc_lines, gate_line):
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
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"# Order notes: {os.path.basename(pcb)}\n\n")
        f.write("(generated by caliper/hardware/design/release.py; do not edit)\n\n")
        if review_only:
            f.write("> **REVIEW-ONLY PACKAGE: do not order.** It was written with `--force`: the DRC/parity gate or "
                    "the jlcplace placement gate did not pass (see below and drc-parity.rpt).\n\n")
        f.write("Rev A is **designed, not built**: nothing here has been fabricated, assembled or measured.\n\n")
        f.write(f"* DRC/parity gate (kicad-cli 9, errors only): {gate_line}\n")
        f.write(f"* Do not place (DNP): {', '.join(dnp) or 'none'}\n")
        f.write(f"* Not assembled, not in BOM/CPL (copper / mechanical only): {', '.join(excluded) or 'none'}"
                + (" (E40 = the capacitive electrode comb: bare copper, no part)" if "E40" in excluded else "") + "\n")
        f.write(f"* Bottom-side placements ({len(bottom)}): {', '.join(bottom) or 'none'}\n")
        board_only = sorted(fp.GetReference() for fp in b.GetFootprints() if fp.GetAttributes() & pcbnew.FP_BOARD_ONLY)
        if board_only:
            f.write(f"* Board-only parts (no BOM): {', '.join(board_only)}\n")
        for ln in jlc_lines:
            f.write(ln + "\n")
        for note in FAB_NOTES.get(board, []):
            f.write(f"* {note}\n")
    return path


def jlc_gate(board, pcb, out, tmp, proj, force, refit):
    """Write the CPL with jlcplace (boards with parts) and run `jlcplace check` over gerbers.zip.

    Returns (ok, ORDER-NOTES lines). Refuses (SystemExit) on red unless force."""
    ver = jlcp.version()
    gerbers = os.path.join(out, "gerbers.zip")
    report = os.path.join(out, "jlcplace-report.html")
    checklist = os.path.join(out, "jlcplace-checklist.md")
    if board == "slider":
        bom = os.path.join(out, f"{proj}-BOM-JLCPCB.csv")
        cpl = os.path.join(out, f"{proj}-CPL-JLCPCB.csv")
        db = JLC_DB
        if refit:
            try:
                print(f"[{board}] jlcplace fetch + fit --db (network)")
                jlcp.refit(pcb, db, bom)
            except jlcp.JlcplaceError as e:
                print(f"WARN: [{board}] could not refit the jlcplace database: {e}")
        red_cpl, text = jlcp.write_cpl(pcb, cpl, bom=bom, gerbers=gerbers, db=db, force=force)
        if red_cpl and not force:
            raise SystemExit(f"[{board}] jlcplace cpl: red rows, no CPL written (use --force for a review-only "
                             f"package):\n{text.strip()}")
    else:
        # no parts: an empty CPL (kept out of the package) proves that nothing on the board needs placing and that
        # gerbers.zip is this board's, plotted from the aux origin
        bom, db = None, None
        cpl = os.path.join(tmp, f"{proj}-CPL-empty.csv")
        jlcp.write_cpl(pcb, cpl, gerbers=gerbers)
    res = jlcp.check(pcb, cpl, os.path.join(tmp, "jlcplace.json"), bom=bom, gerbers=gerbers, db=db,
                     report=report, checklist=checklist)
    if db:
        # the same CPL from the EasyEDA records alone: a stored auto correction may not turn a red row green
        jlcp.add_cross_check(res, jlcp.check(pcb, cpl, os.path.join(tmp, "jlcplace-records.json"), bom=bom,
                                             gerbers=gerbers))
    print(f"[{board}] jlcplace {'.'.join(map(str, ver))}: {res['summary_line']}")
    for p in jlcp.problem_lines(res):
        print(f"  RED {p}")
    if res["red"] and not force:
        raise SystemExit(f"[{board}] jlcplace check: red (see {report}); refusing to write the package "
                         "(use --force for a review-only package)")
    lines = jlcp.order_lines(res, ver)
    if board != "slider":
        lines.insert(1, "  * no parts, no CPL: checked with an empty CPL (not shipped), so nothing on the board needs "
                        "placing and gerbers.zip is this board's, plotted from the CPL origin")
    return not res["red"], lines


def release(board, force=False, refit=False):
    kdir = os.path.join(HW, "kicad", board)
    proj = f"prettycool-caliper-{board}"
    pcb = os.path.join(kdir, proj + ".kicad_pcb")
    sch = os.path.join(kdir, proj + ".kicad_sch")
    out = os.path.join(HW, "fab", board)
    # empty the folder rather than removing it: on a Windows mount a shell sitting in it makes rmdir fail
    os.makedirs(out, exist_ok=True)
    for name in os.listdir(out):
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
    fab.gerbers(pcb, out, BOARDS[board])
    if board == "slider":
        fab.jlc_bom(net, os.path.join(out, f"{proj}-BOM-JLCPCB.csv"))
    try:
        try:
            jlc_ok, jlc_lines = jlc_gate(board, pcb, out, tmp, proj, force, refit)
        except jlcp.JlcplaceError as e:
            if not force:
                raise SystemExit(f"[{board}] jlcplace could not run: {e} (use --force for a review-only package)")
            jlc_ok, jlc_lines = False, [f"* **jlcplace placement gate did not run:** {e}"]
    except SystemExit:
        # the gerbers (and BOM) are already written: mark the half-written folder so it is never ordered from
        with open(os.path.join(out, "REVIEW-ONLY.txt"), "w") as f:
            f.write("INCOMPLETE: release.py was refused by the jlcplace placement gate. Do not order. "
                    "Fix the red rows (see jlcplace-report.html) and release again.\n")
        raise
    review_only = review_only or not jlc_ok
    order_notes(board, pcb, net, os.path.join(out, "ORDER-NOTES.md"), review_only, jlc_lines, gate_line)
    if review_only:
        with open(os.path.join(out, "REVIEW-ONLY.txt"), "w") as f:
            f.write("REVIEW-ONLY package written with --force: do not order. See ORDER-NOTES.md.\n")
    subprocess.run([kicad_cli(), "sch", "export", "pdf", "-o", os.path.join(out, f"{proj}-schematic.pdf"), sch],
                   capture_output=True)
    cu = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"] if BOARDS[board] == 4 else ["F.Cu", "B.Cu"]
    board_pdf(pcb, os.path.join(out, f"{proj}-top.pdf"), ["F.Cu", "F.Silkscreen", "F.Fab", "Edge.Cuts"])
    board_pdf(pcb, os.path.join(out, f"{proj}-bottom.pdf"), ["B.Cu", "B.Silkscreen", "B.Fab", "Edge.Cuts"])
    for layer in cu:
        board_pdf(pcb, os.path.join(out, f"{proj}-{layer.replace('.', '_')}.pdf"), [layer, "Edge.Cuts"])
    zoom, size = (1.0, (1600, 1000)) if board == "slider" else (7.0, (2400, 300))
    render3d(pcb, os.path.join(out, f"{proj}-3d-top.png"), "top", zoom, size)
    render3d(pcb, os.path.join(out, f"{proj}-3d-bottom.png"), "bottom", zoom, size)
    shutil.rmtree(tmp)
    return out, review_only


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", choices=sorted(BOARDS))
    ap.add_argument("--force", action="store_true", help="write a review-only package even if a gate fails")
    ap.add_argument("--refit-jlc", "--update-offsets", dest="refit", action="store_true",
                    help="jlcplace fetch (network) + fit --db: store corrections for new or changed parts")
    a = ap.parse_args()
    for b in BOARDS:
        if a.board and b != a.board:
            continue
        out, review = release(b, a.force, a.refit)
        print(f"[{b}] ->", out, "(REVIEW ONLY)" if review else "")


if __name__ == "__main__":
    main()
