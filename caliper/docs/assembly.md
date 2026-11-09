# Assembly and ordering

> **Status: rev A is designed, not built.** The order settings below come from the generated fab package
> (`caliper/hardware/fab/<board>/ORDER-NOTES.md`, written by `release.py`). Nothing has been ordered, assembled or
> measured; prices and stock are catalogue figures from 2026-11-07/08. See [SPEC](../hardware/design/SPEC.md) for the
> architecture of record and [Schematics and boards §7](electronics.md#_7-layout) for the layout and its DRC status.
>
> Both packages pass `release.py` (2026-11-08): the DRC/parity gate and the **jlcplace placement gate** (§6; slider
> 102 CPL rows after the 2026-11-08 phase-4 fixes: 0 red, 0 yellow, 102 green; scale: no parts, 0 red). The slider was review-only until J50 got the
> C2911931 vendor land (SPEC §12). Still designed, not built: buy the display panel and check it (§1), give the
> machine routing a hand review (§5) and work through the preview checklist (§6) before ordering.
>
> **The order itself** (the JLC options to pick, a rough price, the two preview items and the off-board parts with
> sources) is the one-page [Order checklist](ordering.md) (2026-11-09).

Rev A is two PCBs, a bought display panel, a LiPo cell, a magnetic tape and the printed/brass mechanics
([Mechanical design](mechanical.md)).

## 1. What to order

| Item | Source | Notes |
|---|---|---|
| Slider PCB + assembly | JLCPCB, `caliper/hardware/fab/slider/` (`gerbers.zip`, `*-BOM-JLCPCB.csv`, `*-CPL-JLCPCB.csv`) | §2 |
| Scale PCB (no assembly) | JLCPCB, `caliper/hardware/fab/scale/gerbers.zip` | §3 |
| AS5311-ATST encoder (U30) | in the JLC BOM (LCSC C22459687) | **only 80 pcs at LCSC on 2026-11-07, 75 in JLC's parts library on 2026-11-09** (USD 12.64 at 1–9; [Order checklist §4](ordering.md#_4-rough-cost-5-slider-pcbas-5-scales)). If they are gone, order the board with U30 DNP and buy AS5311-ATST (or -ATSU, reel) from Mouser/DigiKey; hand-solder it (TSSOP-20, 0.65 mm) |
| LCD panel | 1.14 in 240 × 135 ST7789 IPS, 13-pin 0.5 mm FPC, pin order as DisplayModule DM-TFT114-397 §3.1 | **buy it first** and check its drawing: the board needs a 0.5 mm-pitch, 0.3 mm-thick plug-in tail long enough to fold from the glass's −x end back under it into J50 (SPEC §2.1). J50 is **bottom contact** and the fold turns the tail over, so with the panel lying flat, face up, tail toward −x, the tail's contacts must be on the **face (viewer) side** and its pin 1 on the **+y side** (toward the buttons): J50 pin 1 is at board y 10.5, pin 13 at y 4.5. A different pin order needs `PANEL_PINS` changed in `sheets/ui.py` |
| LiPo cell | 402535, ~500 mAh, 1S, with a JST-SH 2-pin (SHR-02V-S) plug | lead polarity is not standardised: J2 pin 1 = BAT+ (marked on the bottom silk). Check every pack with a meter before plugging it in: Q1 (a P-FET in the BAT+ lead, SPEC §3) keeps a reversed pack from powering the board, but a reversed pack still does not work. The leads leave the cell's −x end and come over the board's top edge (mechanics: lead channel and plug relief) |
| Magnetic tape | ams **AS5000-MS10-H075-100** (2.0 mm pole pair) or a generic 2 mm pole-pair encoder tape | slit to **8.0 mm** wide, ≤ 0.60 mm thick with backing (SPEC §7, D2); 172 mm long |
| Adhesive | 3M 467MP transfer tape (0.05 mm) | tape and scale bonding |
| Kapton shim | 0.025 mm sheet | 0–0.35 mm per unit under the tape ([Mechanical §7](mechanical.md#_7-setting-the-gaps-assembly-procedure)) |
| SMT M2 standoffs | 4 × PEM SMTSO-M2-2ET class (2.0 mm tall, OD ≤ 4.0; Mouser/DigiKey) | for the tab clamp holes H2–H5 (SPEC D3). **Fitted by hand**, not in the JLC BOM: the only LCSC M2 SMT nuts (SMTSO20x0CTJ, e.g. C2915626 M2 × 2) have a Ø5.6 base, which overhangs the 6 mm tab (the hole is 2.5 mm from its outer edge) |
| Board clamp hardware | 4 × M2 × 4 low-head screws (tower into the standoffs), 4 × shim washers 2.2 × 4.0 × 0.3 bedded in slow structural epoxy, 4 strips of 0.150 mm steel shim foil (a reusable tool), 1 × **nylon** M2 × 5 for H1 | H1 sits 5 mm from the antenna: no metal screw there. Full mechanical BOM: [Mechanical §11](mechanical.md#_11-hardware-bom) |

## 2. JLCPCB settings: slider board

| Setting | Value |
|---|---|
| Layers | 4 |
| Dimensions | 74 × 34 mm (62 × 34 body plus two 6 × 14 mm end tabs) |
| Thickness | **1.0 mm** |
| Stack-up | **JLC04101H-3313**: JLC's symmetric 1.0 mm 4-layer construction with one 3313 prepreg (0.0994 mm, εr 4.1) between each outer and inner layer. The board file carries this stack (`layout.py` `SLIDER_STACKUP`) and `ORDER-NOTES.md` names it; select it in the order's stack-up option. Checked 2026-11-09 ([Order checklist §2.1](ordering.md#_2-1-stack-up-check-2026-11-09)): the prepreg and εr agree with JLC's impedance page; a third-party catalogue of JLC's templates gives the core as 0.70 mm against the board file's 0.6708 mm, which no line depends on; no stack-up change |
| Impedance control | **no**: USB_DP / USB_DM are full-speed (12 Mb/s), where it would buy nothing. The pair (0.16 mm tracks, 0.16 mm gap, mostly on L4 over an In2 GND strip, the same structure as L1 over L2 in this symmetric stack) is 89 Ω differential on JLC04101H-3313 by a 2D field solve ([Schematics and boards §7.1](electronics.md#_7-1-stack-up-and-rules-slider)) |
| Surface finish | **ENIG** (0.4 mm-pitch DSBGA, LGA module, bare electrode copper) |
| Copper | 1 oz outer, 0.5 oz inner |
| Min via | 0.40 / 0.20 mm (signal), 0.45–0.50 / 0.20–0.25 mm (power/GND). **Order the 0.2 mm via-hole option**, not the free 0.3 mm one (432 vias have a 0.20 mm drill): it costs extra and JLC is reported to add a 4-wire Kelvin test ([Order checklist §2](ordering.md#_2-jlcpcb-slider-4-layer-pcb-pcba)) |
| Mask / silk | green / white, both sides |
| Remark (paste into the order) | "Flatness: bow/twist ≤ 0.03 mm over the lower 20 mm band (y 0–20, incl. the end tabs), 100 % inspected, reject above. Copper is poured on all four layers there, wherever the routing leaves room, on purpose. Bottom electrode area: mask opened per finger, bare ENIG, no paste." IPC-6012 class 2 allows 0.75 % (0.55 mm here), so this needs JLC to agree (and may need a quote) |
| Assembly | **Standard** PCBA (Economic is one-sided, needs ≥ 0.5 mm BGA pitch against U2's 0.4 mm DSBGA, and takes standard stack-ups only), **both sides**, panelised by JLCPCB (1 × 2, edge rails on the long sides: Standard needs rails, fiducials and ≥ 70 × 70 mm; no break-off tabs on the end tabs, which are clamp faces): top = everything placed; bottom = U30, C30, C31 (beam band) and C21, C23, R85, C44 (0402, under the module: its 3V3 decoupling and the ADC input's RC filter). Alternatively order top-only and hand-solder the seven bottom parts |
| BOM / CPL | `prettycool-caliper-slider-BOM-JLCPCB.csv`, `prettycool-caliper-slider-CPL-JLCPCB.csv`. The CPL is written by `jlcplace cpl` from the Gerbers' (0, 0) with JLC's EasyEDA rotation/origin corrections (`caliper/hardware/design/jlcplace-db/`) and passes the jlcplace check: 102 rows, 0 red, 0 yellow, 102 green (§6; BZ50 is a recorded non-polar decision, but jlcplace 0.2.1 still lists it on the preview checklist). In JLC's placement preview, work through `jlcplace-checklist.md` (U30's bottom-side reading; BZ50 either way round) and still glance at every IC and connector |
| Not placed | E40 (the electrode comb is copper, not a part), the 19 test pads, H1–H5, the fiducials. DNP list: see `ORDER-NOTES.md` |

## 3. JLCPCB settings: scale board

| Setting | Value |
|---|---|
| Layers | 2 |
| Dimensions | 200 × 7 mm |
| Thickness | **0.8 mm** |
| Surface finish | **ENIG** |
| Solder mask | **front: none** (the whole front is one mask opening; the reflector copper is the electrode face). Back: green over the solid copper |
| Silk | back only |
| Assembly | none |
| Remark | "The front copper is 38 isolated islands with no net by design (passive capacitive reflector scale). No V-cut near the pattern." |

The two end holes are Ø1.0 mm **non-plated** alignment holes for a pin jig (SPEC D5: the scale is bonded with
467MP, no screws). The back plane is drawn as GND but nothing connects to it once the scale is bonded (no
fastener), so in rev A it floats; whether it should be tied to the beam (e.g. conductive adhesive) is a bring-up
question.

## 4. Assembly order

1. **Incoming inspection of the slider PCBA.** On a surface plate, check the lower band (y 0–20, tabs included):
   reject a board more than 0.03 mm out of flat. Micrometer the board thickness beside the AS5311 and the board +
   AS5311 stack (gives the seated package height A for the shim, [Mechanical §7](mechanical.md#_7-setting-the-gaps-assembly-procedure) step 1).
2. **Standoffs.** Solder the four SMT M2 standoffs on the H2–H5 top pads (paste + hot air, or iron), square to the
   board. Re-check flatness afterwards.
3. **Electrical bring-up on the bench**, before any mechanics: USB-C power, rails (TP1–TP7 on the bottom), flash
   over USB, display on J50 with the panel lying flat, battery on J2 (polarity checked; Q1 blocks a reversed pack,
   SPEC §3). See [Bring-up](bringup.md).
4. **Bond the scale and the tape** into the beam with 467MP (scale with the pin jig in its Ø1.0 holes), then shim
   the tape per [Mechanical §7](mechanical.md#_7-setting-the-gaps-assembly-procedure) step 2.
5. **Fold the display tail** from the glass's −x end back under the glass into J50; bond the glass to the lid ribs.
6. **Fit the board into the slider body** on the beam: tabs into the tower pockets, the four clamp washers bedded in
   epoxy while the board lies on 0.150 mm shim foil on the beam (these four clamps are the Z datum), then the H1 boss
   and the button-band ledge shimmed and the H1 nylon screw last, without pulling the board out of the tab plane
   (dial indicator, ≤ 0.01 mm). [Mechanical §7](mechanical.md#_7-setting-the-gaps-assembly-procedure) steps 3–6.
7. **Battery** into its pocket (board x 21.5–57.5, ≥ 5.5 mm from the antenna), leads through the channel, plug J2.
8. **Check the gaps** and the sensors in firmware ([Mechanical §7](mechanical.md#_7-setting-the-gaps-assembly-procedure) step 7), then close the lid.

## 5. Open items before an order

* **J50**: the land is now drawn from the C2911931 vendor drawing (SPEC §12). The vendor drawing and EasyEDA place
  the fitting nails 0.37 mm apart; the land covers both. Check the panel's tail orientation against J50 (§1).
* The DRC/parity status and the open layout risks are in [Schematics and boards §7](electronics.md#_7-layout).
  The routing is machine-made and dense: give it a hand review in KiCad before ordering.
* The new E40 / scale-hole footprints are not in the schematic yet (the board carries them as layout-side edits;
  SPEC D5). H5 is in the schematic; the SMT standoffs are hand-fitted (§1).
* AS5311 stock (above). The panel's tail length and pin order (buy it first).
* The live JLC quote: the small-via / Kelvin charge, whether the flatness remark is accepted, and whether a mouse-bite
  nub left on the long edges clears the slider body ([Order checklist §7](ordering.md#_7-still-unverified-before-ordering)).

## 6. jlcplace placement gate

JLC places every part with its own EasyEDA footprint, at the point and angle the CPL row gives, laid over the Gerbers
from their own (0, 0). A row that is right for KiCad's footprint can put JLC's part turned, shifted, on the wrong pins
or reversed. [jlcplace](https://github.com/tyevco/jlcplace) ([docs](https://tyevco.github.io/jlcplace/)) simulates
exactly that: it puts the EasyEDA pads down at every row over `gerbers.zip` and reports the KiCad pad and net each
one lands on. It also checks the LCSC part's pin names against the symbol's pin functions, polarity, the BOM against
the board and the CPL, the Gerbers' origin, and how the bottom-side rotation could be read.

**It is a release gate.** `release.py` runs it on every board after writing the Gerbers and the BOM; a package does
not count as done until it passes:

1. `jlcplace cpl` writes the slider CPL from the Gerbers' (0, 0), with the corrections stored in
   `caliper/hardware/design/jlcplace-db/` (one JSON file per LCSC code: derived numbers only, no EasyEDA geometry).
2. `jlcplace check` checks that CPL with the BOM over `gerbers.zip` and writes `jlcplace-checklist.md` and
   `jlcplace-report.html` into `fab/<board>/`.
3. **Any red row, or a red finding about the whole run (an origin mismatch, Gerbers that are not this board's), refuses
   the package.** `--force` writes a REVIEW-ONLY package instead. The yellow rows and the preview checklist are copied
   into `ORDER-NOTES.md`.
4. A second `jlcplace check` without the database cross-checks the stored corrections against the EasyEDA records. In
   a test with one stored correction turned 180° (U1, the USB ESD array), jlcplace 0.2.1 wrote that row and called it
   green with `--db` ("numbering accepted by the correction (auto)") although it put VBUS on GND; the records alone call
   it red. So a row the records call red is red for the gate unless a human decision in the database (manual, preview-
   or board-verified) accepts it.

The scale has no parts. It is checked with an empty CPL, which is not shipped: nothing on it may need placing, and
`gerbers.zip` must be this board's, plotted from the aux origin.

`jlcplace-report.html` draws the EasyEDA pad outlines (JLCEDA/EasyEDA Official Library). It is for your own review,
so it is git-ignored and never published. Open it locally after a release.

**Result 2026-11-08** (jlcplace 0.2.1, KiCad 10.0.8 board after the layout review: C13 added, R85/C44 on the bottom, BZ50 decided):

| Board | Rows | Red | Yellow | Green | Preview checklist |
|---|---|---|---|---|---|
| slider | 102 | 0 | 0 | 102 | U30 bottom-side reading; BZ50 still listed (non-polar, either way) |
| scale | 0 (no parts) | 0 | 0 | 0 | nothing (origin: the Gerbers' (0, 0) is the aux origin) |

* **BZ50** (C910763, piezo): every pad lands as the correction puts it, but EasyEDA's footprint draws no "+" and names
  no pins, so only the pad numbers decide which way round it goes. That does not matter: the PKMCS0909E4000-R1 is
  non-polar (a piezo diaphragm, driven both ways in Murata's own SPL test; no + or pin-1 mark on the part or in its
  drawings). This is recorded as a manual decision in the database (2026-11-08, `jlcplace confirm --source manual`),
  so the row is green; jlcplace 0.2.1 still prints the stored fit doubt on the checklist, where either orientation
  passes.
* **U30** (AS5311, bottom): green under the bottom-side reading every open tool uses (`jlc-2022`). JLC does not
  document how it reads a bottom-side angle; under either "+180" reading pin 1 would sit on pad 11. It is the only
  bottom part that depends on the reading: the other six (C21, C23, C30, C31, C44, R85) are non-polar two-pad parts.

Only BZ50 has a manual decision (above); nothing was red. After checking the preview, record what it showed in the
database, with the CPL that was uploaded, and commit it:

```sh
jlcplace confirm caliper/hardware/kicad/slider/prettycool-caliper-slider.kicad_pcb --ref BZ50 --ref U30     --db caliper/hardware/design/jlcplace-db --by <name> --source preview     --cpl caliper/hardware/fab/slider/prettycool-caliper-slider-CPL-JLCPCB.csv     --gerbers caliper/hardware/fab/slider/gerbers.zip
```

(add `--space/--right/--up N` with the keys pressed if a part had to be moved, or `--failed` if it was wrong).

**How to run it** (WSL, the `dial-me-spinner` venv, where jlcplace is installed editable from `~/jlcplace`):

```sh
cd /mnt/c/source/tyevco/prettycoolboards
PY=$HOME/.venvs/dial-me-spinner/bin/python
$PY caliper/hardware/design/release.py                   # both boards: DRC/parity gate, then the jlcplace gate
$PY caliper/hardware/design/release.py --refit-jlc       # after adding or changing an LCSC part (network):
                                                         #   jlcplace fetch + jlcplace fit --db jlcplace-db

# the same check by hand (it reads the record cache ~/.cache/jlcplace and downloads nothing)
cd caliper/hardware
jlcplace fetch kicad/slider/prettycool-caliper-slider.kicad_pcb --bom fab/slider/prettycool-caliper-slider-BOM-JLCPCB.csv
jlcplace check kicad/slider/prettycool-caliper-slider.kicad_pcb fab/slider/prettycool-caliper-slider-CPL-JLCPCB.csv     --bom fab/slider/prettycool-caliper-slider-BOM-JLCPCB.csv --gerbers fab/slider/gerbers.zip     --db design/jlcplace-db --report fab/slider/jlcplace-report.html --checklist fab/slider/jlcplace-checklist.md
```

Exit codes: 0 clean (yellow allowed), 2 red, 3 bad input, 4 a jlcplace bug. `release.py` refuses on 2, and on 3 or 4
too (the gate did not run).
