# Assembly and ordering

> **Status: rev A is designed, not built.** The order settings below come from the generated fab package
> (`caliper/hardware/fab/<board>/ORDER-NOTES.md`, written by `release.py`). Nothing has been ordered, assembled or
> measured; prices and stock are catalogue figures from 2026-11-07. See [SPEC](../hardware/design/SPEC.md) for the
> architecture of record and [Schematics and boards §7](electronics.md#_7-layout) for the layout and its DRC status.
>
> **Do not order the slider yet.** Its package is **review-only**: the JLC placement check found that the J50 part
> (C2911931, 0.5K-AX-13PWB) does not fit the Hirose FH12 footprint on the board (its fitting nails would land 1.3 mm
> off their pads). The scale package is released.

Rev A is two PCBs, a bought display panel, a LiPo cell, a magnetic tape and the printed/brass mechanics
([Mechanical design](mechanical.md)).

## 1. What to order

| Item | Source | Notes |
|---|---|---|
| Slider PCB + assembly | JLCPCB, `caliper/hardware/fab/slider/` (`gerbers.zip`, `*-BOM-JLCPCB.csv`, `*-CPL-JLCPCB.csv`) | §2 |
| Scale PCB (no assembly) | JLCPCB, `caliper/hardware/fab/scale/gerbers.zip` | §3 |
| AS5311-ATST encoder (U30) | in the JLC BOM (LCSC C22459687) | **only 80 pcs at LCSC on 2026-11-07.** If they are gone, order the board with U30 DNP and buy AS5311-ATST (or -ATSU, reel) from Mouser/DigiKey; hand-solder it (TSSOP-20, 0.65 mm) |
| LCD panel | 1.14 in 240 × 135 ST7789 IPS, 13-pin 0.5 mm FPC, pin order as DisplayModule DM-TFT114-397 §3.1 | **buy it first** and check its drawing: the board needs a 0.5 mm-pitch, 0.3 mm-thick plug-in tail long enough to fold from the glass's −x end back under it into J50 (SPEC §2.1). A different pin order needs `PANEL_PINS` changed in `sheets/ui.py` |
| LiPo cell | 402535, ~500 mAh, 1S, with a JST-SH 2-pin (SHR-02V-S) plug | lead polarity is not standardised: J2 pin 1 = BAT+ (marked on the bottom silk). Check every pack with a meter before plugging it in. The leads leave the cell's −x end and come over the board's top edge (mechanics: lead channel and plug relief) |
| Magnetic tape | ams **AS5000-MS10-H075-100** (2.0 mm pole pair) or a generic 2 mm pole-pair encoder tape | slit to **8.0 mm** wide, ≤ 0.60 mm thick with backing (SPEC §7, D2); 172 mm long |
| Adhesive | 3M 467MP transfer tape (0.05 mm) | tape and scale bonding |
| Kapton shim | 0.025 mm sheet | 0–0.35 mm per unit under the tape ([Mechanical §7](mechanical.md#_7-setting-the-gaps-assembly-procedure)) |
| SMT M2 standoffs | 4 × PEM SMTSO-M2-2ET class (2.0 mm tall, OD ≤ 4.0) | for the tab clamp holes H2–H5 (SPEC D3). **Not in the JLC BOM yet** (no LCSC part chosen by the schematic track): fit by hand |
| Board clamp hardware | 4 × M2 × 4 low-head screws (tower into the standoffs), 4 × shim washers 2.2 × 4.0 × 0.3 bedded in slow structural epoxy, 4 strips of 0.150 mm steel shim foil (a reusable tool), 1 × **nylon** M2 × 5 for H1 | H1 sits 5 mm from the antenna: no metal screw there. Full mechanical BOM: [Mechanical §11](mechanical.md#_11-hardware-bom) |

## 2. JLCPCB settings: slider board

| Setting | Value |
|---|---|
| Layers | 4 |
| Dimensions | 74 × 34 mm (62 × 34 body plus two 6 × 14 mm end tabs) |
| Thickness | **1.0 mm** |
| Stack-up | JLC's standard **symmetric** 1.0 mm 4-layer impedance stack. The layout assumed a ~0.1 mm L1–L2 prepreg; read the exact stack ID and dielectric from JLC's impedance calculator when ordering |
| Impedance control | **no** (layout review 2026-11-08). USB_DP / USB_DM are full-speed (12 Mb/s) and run as a 0.14 mm pair mostly on L4 (B.Cu) over an In2 GND strip, not as an L1-over-L2 microstrip, so the 90 Ω L1 estimate the class width came from does not describe them and there is nothing for JLC to tune. Full-speed USB tolerates this ([Schematics and boards §7.5](electronics.md#_7-5-routing-result-slider)) |
| Surface finish | **ENIG** (0.4 mm-pitch DSBGA, LGA module, bare electrode copper) |
| Copper | 1 oz outer, 0.5 oz inner |
| Min via | 0.40 / 0.20 mm (signal), 0.45–0.50 / 0.20–0.25 mm (power/GND) |
| Mask / silk | green / white, both sides |
| Remark (paste into the order) | "Flatness: bow/twist ≤ 0.03 mm over the lower 20 mm band (y 0–20, incl. the end tabs), 100 % inspected, reject above. Copper is poured on all four layers there, wherever the routing leaves room, on purpose. Bottom electrode area: mask opened per finger, bare ENIG, no paste." IPC-6012 class 2 allows 0.75 % (0.55 mm here), so this needs JLC to agree (and may need a quote) |
| Assembly | PCBA, **both sides**: top = everything placed; bottom = U30, C30, C31 only. Alternatively order top-only and hand-solder the three bottom parts |
| BOM / CPL | `prettycool-caliper-slider-BOM-JLCPCB.csv`, `prettycool-caliper-slider-CPL-JLCPCB.csv`. The CPL angles carry the JLC library corrections from `jlc_offsets.json` (42 parts); every row except J50 passes the placement simulation. Still check every IC and connector in JLC's placement preview |
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
   over USB, display on J50 with the panel lying flat, battery on J2 (polarity checked). See [Bring-up](bringup.md).
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

* **J50**: change the footprint to the C2911931 land, or the part to one that fits the FH12 land, then re-run
  `release.py` (the slider package is review-only until its CPL check passes).
* The DRC/parity status and the open layout risks are in [Schematics and boards §7](electronics.md#_7-layout).
  The routing is machine-made and dense: give it a hand review in KiCad before ordering.
* The SMT standoff, H5 and the new E40 / scale-hole footprints are not in the schematic yet (the board carries them
  as layout-side edits; SPEC D3/D5).
* AS5311 stock (above). The panel's tail length and pin order (buy it first).
