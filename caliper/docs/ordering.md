# Order checklist (rev A)

> **Status: rev A is designed, not built.** Nothing has been ordered, assembled or measured. Prices and stock below
> were read on **2026-11-09** and change every day. Anything marked **[unverified]** is not confirmed. Check it before
> paying. The settings behind this page are in [Assembly and ordering](assembly.md) and in the generated
> `caliper/hardware/fab/<board>/ORDER-NOTES.md`.

## 1. Order of operations

1. **Buy the display panel first** (§5). Check its drawing against the tail rule. If no panel fits, J50 / `PANEL_PINS`
   change before any PCB order.
2. **Re-check stock on the day you order:** U30 AS5311 at JLC (75 pcs on 2026-11-09) and the 25 extended parts (§4).
3. **Ask JLC about the flatness remark** before you pay (or put it in the order remark and wait for the engineering
   question). The board needs ≤ 0.03 mm bow/twist over y 0–20. Standard IPC class 2 would allow 0.55 mm.
4. **Order the slider PCBA and the scale PCB** together (§2, §3). Go through the placement preview (§6) **before**
   you confirm the PCBA, and record what it showed with `jlcplace confirm`.
5. **While JLC builds:** order the off-board parts (§5) and the beam steel. Print the parts. Fit the heat-set inserts.
6. **On arrival:** inspect for flatness, reflow the SMT standoffs, do the bench bring-up, then the mechanical
   assembly ([Assembly §4](assembly.md#_4-assembly-order), [Mechanical §7](mechanical.md#_7-setting-the-gaps-assembly-procedure)).

## 2. JLCPCB: slider, 4-layer PCB + PCBA

Upload `caliper/hardware/fab/slider/gerbers.zip`, `prettycool-caliper-slider-BOM-JLCPCB.csv` and
`prettycool-caliper-slider-CPL-JLCPCB.csv`.

| Option | Pick | Why |
|---|---|---|
| Layers / size | 4, 74 × 34 mm | |
| Thickness | **1.0 mm** | SPEC; the gap stack-up assumes it |
| Stack-up | **JLC04101H-3313** | Symmetric, and the USB pair impedance is computed on it (§2.1). If the form only offers a stack-up choice with impedance control on, set impedance control to Yes, enter USB_DP/USB_DM as 90 Ω differential, 0.16 mm traces / 0.16 mm gap on L4 referenced to L3. Reaching that form is **[unverified]** |
| Impedance control | **No** | Full-speed USB (12 Mb/s) does not need it |
| Surface finish | **ENIG** (1U″) | 0.4 mm-pitch DSBGA, LGA module, bare electrode copper. The ENIG-area surcharge starts above 30 % of the board area and is a few cents at this size |
| Via hole option | **0.2 mm hole** (not the free 0.3 mm option) | 432 vias have a 0.20 mm hole (394 × 0.40, 38 × 0.45 pad). JLC charges extra below 0.3 mm. Forum reports and a published order dataset say JLC adds a 4-wire Kelvin test for these vias and may send a supplement request after the order **[unverified amount]** |
| Via covering | Tented | Except the electrode finger vias, which are open on the bottom by design (ORDER-NOTES) |
| Mask / silk | green / white, both sides | |
| Copper | 1 oz outer, 0.5 oz inner (the stack's own) | |
| Remark | the flatness / electrode text from [Assembly §2](assembly.md#_2-jlcpcb-settings-slider-board) | |
| PCBA type | **Standard** | Economic can't build this board (§2.2) |
| Assembly side | **Both sides** | Bottom: U30, C30, C31 (beam band), C21, C23, R85, C44 (under the module) |
| Panel / rails | **Panel by JLCPCB, 1 × 2, edge rails on the long sides** | Standard PCBA needs edge rails, fiducials and ≥ 70 × 70 mm per piece. Remark: "no break-off tabs on the end tabs (x < 0, x > 62): they are clamp faces". Whether a nub left on the long edges fits the body has not been checked **[unverified]**: file any nub flush |
| Quantity | 5 boards (counted as panels on the form) | |
| Parts | JLC parts library, all 44 lines | U30 stock: §4 |

### 2.1 Stack-up check (2026-11-09)

JLC's [impedance page](https://jlcpcb.com/impedance) loads the 1.0 mm tables only from its interactive form, and those
could not be read from here. What could be confirmed:

* **Prepreg:** JLC's page gives 3313 prepreg εr **4.1** and core εr **4.6**, and its 1.6 mm 3313 stack (JLC04161H-3313)
  uses one 3313 sheet at **0.0994 mm** per side.
* **JLC04101H-3313 itself:** tscircuit's catalogue of JLC's stack templates
  ([jlc-4-layer-stackups.ts](https://github.com/tscircuit/jlcpcb-manufacturing-specs/blob/main/lib/stackups/jlc-4-layer-stackups.ts),
  2026-10-26) lists it as 3313 0.0994 mm / **core 0.70 mm** (NP-155F) / 3313 0.0994 mm, with 35 µm outer and 15.2 µm inner copper.
  The same family at 1.0 mm also has -1080, -2116 and -7628.
* **The board file** (`layout.py` `SLIDER_STACKUP`) carries the same prepreg and copper, and a core of 0.6708 mm at εr 4.6.
  The core is chosen to make the stack add up to 1.0 mm. It is 0.03 mm under the catalogue's 0.70 mm. JLC's own
  1.6 mm tables would give 0.665 mm, because they list the core without its copper. Either way the difference is a few
  hundredths of a millimetre.
* **USB pair:** an outer-layer pair over the plane right below it only sees the prepreg, and the prepreg is confirmed.
  Re-solved on 2026-11-09 (hwtools `sicalc solve --micro 0.0994 --er 4.1 --mask-t 0.015 --w 0.16 --s 0.16 --etch 0.0178`):
  **Zdiff 89.35 Ω**, the same as [Schematics and boards §7.1](electronics.md#_7-1-stack-up-and-rules-slider).
  **No stack-up change.**
* Do not pick the 7628 stack. With the same settings, its 0.2104 mm prepreg (εr 4.4) gives **109.5 Ω**. It also changes
  the In1/In2 crosstalk geometry the CAP_LP1 shield was checked on.

### 2.2 Why Standard PCBA, not Economic

From JLC's [PCBA capabilities](https://jlcpcb.com/capabilities/pcb-assembly-capabilities):

* Economic assembles **one side only**. The slider has 7 bottom parts.
* Economic's minimum BGA pitch is **0.5 mm**. U2 (BQ25180, DSBGA) is 0.4 mm.
* Economic builds **standard stack-ups only**, so JLC04101H-3313 is not available there.

The fallback is a single-sided Standard order: top only, with the seven bottom parts hand-soldered. It saves about
$34 (setup and stencil), but U30 is a 0.65 mm-pitch TSSOP-20 and four of the parts are 0402s under the module.

## 3. JLCPCB: scale, 2-layer PCB (no assembly)

`caliper/hardware/fab/scale/gerbers.zip`. Set 2 layers, 200 × 7 mm, **0.8 mm**, ENIG, quantity 5, single board (no
panel, no V-cut). The front has no solder mask by design. Silk is on the back only. The remark text is in
[Assembly §3](assembly.md#_3-jlcpcb-settings-scale-board) (38 floating copper islands are intended).

## 4. Rough cost (5 slider PCBAs + 5 scales)

The fees come from JLC's [PCBA price page](https://jlcpcb.com/help/article/pcb-assembly-price) (updated 2026-10-22).
The parts prices come from JLC's parts pages on 2026-11-09, at the quantity-5 price break.

| Line | Estimate | Basis |
|---|---|---|
| Parts, 5 boards | **≈ $136** (≈ $27 a board) | 44 BOM lines; the big items: AS5311 $12.64, ESP32-S3-MINI-1 $5.01, MAX17048 $2.01, BQ25180 $1.85 (each, at 1–9 pcs). Plus JLC's attrition on passives (a few $) |
| Feeder loading | ≈ $67 | Standard PCBA loads **every** line, basic and extended: 44 lines × $1.53 (the price page's Standard column, "$1.53 Basic/Extend"; $3.07 extended-only is the Economic rate). The page does not say the unit; per unique part is assumed **[unverified]**. 25 of the 44 lines are extended |
| Setup, double-sided | $51.12 | Standard |
| Stencil, double-sided | $16.42 | Standard |
| Placement | ≈ $3 | 380 joints a board (348 top, 32 bottom) × 5 × $0.0016 |
| X-ray (BGA, QFN and other leadless parts) | ≈ $8–21 | Charged per X-rayed component ("/pc"): $1.64 for 1–10 pcs, $0.82 for 11–50. Leadless parts on the slider: U2 DSBGA, U3 VSON, U4 TDFN, U10 module, U60 LGA = 5 a board, 25 for 5 boards ≈ $21 if JLC X-rays all of them; ≈ $8 if only one a board **[unverified]** |
| **PCBA subtotal** | **≈ $280–295** | |
| Slider PCB (4L, 1.0 mm, ENIG, 0.2 mm vias, panel) | **$40–130** | **[unverified]** range. The base price, the ENIG upgrade, the small-via / Kelvin-test charge and the panel all depend on JLC's live quote. JLC's 4-layer prices changed in August 2026 |
| Scale PCB (2L, 0.8 mm, ENIG, 200 × 7) | **$15–40** | **[unverified]** range, live quote |
| **Before shipping and tax** | **≈ $335–465** | |
| Shipping + US import | +$90–170 | Two published 2026 JLC 4-layer PCBA orders to the US paid $36–73 for DHL (duties paid) and $51–98 in duties and taxes ([tscircuit order dataset](https://github.com/tscircuit/jlcpcb-manufacturing-specs/tree/main/datasets/jlcpcb)). This is indicative only |

**AS5311 (U30):** JLC's [part page](https://jlcpcb.com/partdetail/C22459687) showed **75 in stock** on 2026-11-09, at
$12.64 (1–9) and $10.86 (10–29). That is down from 80 at LCSC on 2026-11-07. It is enough for 5 boards, but only
just. If it runs out:

* order U30 as DNP;
* buy AS5311-ATST (cut tape) or AS5311-ATSU (reel) from DigiKey or Mouser. DigiKey lists it as Active, and stock
  differs by region ([DigiKey](https://www.digikey.com/en/products/detail/ams-osram-usa-inc/AS5311-ATST/2529144)); about
  $11–14 each;
* hand-solder it. JLC's parts sourcing / consignment is a possible route **[unverified]**.

Other thin stock: TPS22917 (2,260), the piezo (2,496), J50 (2,784).

## 5. Off-board parts

Quantities are per caliper. Buy for two builds plus spares. Full mechanical BOM: [Mechanical §11](mechanical.md#_11-hardware-bom).

| ✓ | Item | Qty | Source | Check |
|---|---|---|---|---|
| ☐ | **LCD panel**, 1.14″ 240 × 135 IPS, ST7789, 13-pin 0.5 mm plug-in FPC, pin order as DM-TFT114-397 §3.1 | 1 (+1) | DisplayModule [DM-TFT114-397](https://www.displaymodule.com/products/1-14-inch-ips-display-240x135-with-spi) ($9.90). Its FPC pitch and type are not on the product page **[unverified]** | **Tail rule (SPEC §2.1):** 0.5 mm pitch, 0.3 mm-thick **plug-in** tail (not a solder tail), long enough to leave the glass at board x 17.5 and fold back under it into J50. Lay the panel flat, face up, tail toward −x. Then the tail's **contacts must be on the face (viewer) side** and its **pin 1 on the +y side** (toward the buttons): J50 is bottom-contact and the fold turns the tail over. Many 1.14″ 13-pin panels on the market have a 0.7 mm-pitch solder tail; those do not fit |
| ☐ | **LiPo 402535**, 1S, ~400–500 mAh, JST-SH 2-pin plug (SHR-02V-S) | 1 (+1) | Generic. No 402535 with an SH plug was found at a distributor **[unverified]**. Alternative: Jauch [LP402535JU](https://uk.farnell.com/jauch/lp402535ju/battery-rechargeable-380mah-3/dp/4145400) (380 mAh, bare leads) plus a pre-crimped SH lead | Outline ≤ 4.0 × 25 × 35 mm, including the protection board; the pocket is 36 mm long (board x 21.5–57.5). **Polarity:** J2 pin 1 = BAT+ (bottom silk "BAT+"). Measure every pack with a meter before plugging it in. Q1 blocks a reversed pack, but a reversed pack still does not run the board. The leads leave the cell's −x end |
| ☐ | **Magnetic tape**, 1.0 mm pole length (2.0 mm pole pair), rubber-bonded ferrite on 0.3 mm stainless | 172 mm | ams AS5000-MS10-H075-100 (not found at Mouser or DigiKey on 2026-11-09), or Dexter Magnetic's ams-matched multipole strip kits ([article](https://magneticsmag.com/multipole-magnet-evaluation-kits-for-ams-magnetic-position-sensors/)) **[unverified source]** | Slit to **8.0 mm** wide (it comes 10 mm wide). **≤ 0.60 mm** thick including the backing (SPEC §7 D2) **[unverified for any source]** |
| ☐ | **Beam**: ground flat stock 20 × 4 × 250, O1 (1.2510 gauge plate) or 1.4301 | 1 | Cromwell, Indexa O1 ground flat [4 mm × 500 range](https://cromwell.co.uk/shop/materials-maintenance-and-standard-parts/ground-flat-stock/precision-ground-flat-stock-o1-tool-steel-4mm-x-500mm/f/63502); the 20 mm width is **[unverified]** (UK) | Supplied annealed; rev B hardens it (Mechanical §10). Cut to 250 |
| ☐ | **Brass**, C360 | – | Metric flats or 1.0 / 1.2 sheet **[unverified source]** | 1.2 × 14 × 64 (back gib), 1.0 × 3 × 60 (Y gib), 1.0 × 3 × 76.9 (reference strip), 1.0 sheet for 4 pads. A model-shop CuZn37 flat is softer than C360 (a deviation) |
| ☐ | **Plungers** (built, not bought): compression springs, Ø2 GFRP rods, cup-point set screws | 4 springs, 3 rods, 8 set screws | Lee Spring LC series class **[unverified]**: Y ~4 N at ~1 mm, OD ≤ 2.0; back ~2.5 N at ~1 mm, OD ≤ 1.5. Set screws M2 × 4 (4), × 3 (2), × 2 (2) | Rates set the gib preloads (Mechanical §7 step 3) |
| ☐ | **SMT M2 standoffs** PEM SMTSO-M2-2ET (2.0 mm tall) | 4 (+4) | Mouser 153-SMTSO-M2-2ET (about $0.9–1.2 each, in stock in search snapshots) | Fitted **by hand** on H2–H5 (not in the JLC BOM). OD ≤ 4.0 on the 6 mm tab: check the drawing **[unverified]** |
| ☐ | **Screws** | | ISO metric | 4 × M2 × 4 low head (k ≤ 1.0), 1 × **nylon** M2 × 5 (H1, beside the antenna: no metal), 2 × M2 × 6 countersunk, 1 × M2 × 6 socket head, 4 × 2.2 × 5 thread-forming for plastic, 2 × M3 × 10 socket + 2 × M3 nut, 1 × M3 × 6 knurled thumb screw |
| ☐ | **Heat-set inserts** | 10 × M2 × 3, 1 × M3 × 4 | Brass inserts for Ø3.2 (M2) and Ø4.0 (M3) holes **[unverified brand fit]** | The holes in the print are Ø3.2 and Ø4.0 |
| ☐ | **Shim washers** 2.2 × 4.0 × 0.3, precision | 4 | MISUMI-type configurable shim ring **[unverified]** | Bedded in slow structural epoxy |
| ☐ | **Kapton** 0.025 mm sheet | 1 sheet | any polyimide 1 mil sheet | 0–14 layers under the tape, strips for the H1 boss and the ledge |
| ☐ | **Steel shim foil** 0.150 mm | 4 strips | any | Assembly tool, reusable |
| ☐ | **3M 467MP** transfer tape (0.05 mm) | 1 sheet | 3M distributors | Bonds the tape and the scale |
| ☐ | Pins: Ø2 × 6 m6 (roller axle), 2 × Ø3 × 10 m6 dowels; O-ring NBR 6.0 × 0.8 | | any | |
| ☐ | Epoxy (slow structural), Loctite 222 | | any | |
| ☐ | **Filament** | | Bambu Lab **PAHT-CF** (slider body, needs the hardened nozzle, dry 80 °C / 8 h); **PA-CF** (fixed jaw); an **unfilled PA** for the body's antenna modifier, e.g. Polymaker PolyMide CoPA **[unverified: that it bonds to PAHT-CF]**; PETG (shell, door, buttons, roller; PETG body for fit trials) | [Mechanical §8](mechanical.md#_8-parts-print-settings-and-orientation) |

## 6. The two placement-preview items

The preview checklist (`caliper/hardware/fab/slider/jlcplace-checklist.md`) lists two parts. Check them in JLC's
placement preview before you confirm the PCBA. The CPL you upload must be the committed one.

**U30, AS5311 (bottom, CPL row 31.0, 6.0, rot 0).** This settles how JLC reads bottom-side angles.

* Open the **bottom** view. JLC draws it **seen from below**, so it is the mirror image of KiCad's top view, and
  left/right swap.
* **Right:** the 20 leads sit on the 20 pads, with the package's long axis along the board. JLC's **pin-1 mark**
  is on the pad row **nearer the jaw-side edge** (board y 3.1, the edge away from the electrode comb). It is at the
  end of that row **next to C31 / C30**, the two 0402s beside the package (board x 33.9). In the seen-from-below view
  that corner is the lower-left.
* **Wrong:** the pin-1 mark at the **diagonally opposite** corner: the row next to the electrode comb, at the end away
  from C30/C31 (pad 11). That means JLC reads the bottom angle with an extra 180°, and every pin is on the wrong net.
  Rotate it 180° in the preview and count the key presses. A shift along the row is also wrong.
* The other six bottom parts are two-pad, non-polar parts. If U30 is right, the bottom reading is settled for all of them.

**BZ50, piezo (top, row 40.0, 24.3, rot 0).**

* **Right:** the 9 × 9 mm body is centred on its footprint and both terminals land on the two pads, one at board
  x 35.65 and one at x 44.35, on y 24.3.
* **Wrong:** turned 90° (the terminals off copper) or shifted.
* **Ignore any "+" or pin-1 mark.** The PKMCS0909E4000-R1 is non-polar, and either way round passes. This decision is
  already recorded (`--source manual`, 2026-11-08). The preview only confirms that it fits.

**Record it** (WSL, the dial-me-spinner venv). Use the exact CPL you uploaded:

```sh
cd /mnt/c/source/tyevco/prettycoolboards
jlcplace confirm caliper/hardware/kicad/slider/prettycool-caliper-slider.kicad_pcb --ref U30 --ref BZ50 \
  --db caliper/hardware/design/jlcplace-db --by <name> --source preview \
  --cpl caliper/hardware/fab/slider/prettycool-caliper-slider-CPL-JLCPCB.csv \
  --gerbers caliper/hardware/fab/slider/gerbers.zip
```

* If you moved a part, add the keys you pressed (`--space N`, `--right N`, `--up N`, relative to the uploaded row).
* If it was wrong and you could not fix it, add `--failed` and do not order. A U30 marked failed turns its row red, so
  the next `release.py` refuses until the correction is fixed.
* Commit `jlcplace-db/`. Re-run `release.py` so ORDER-NOTES shows them as verified.

## 7. Still unverified before ordering

* JLC's own 1.0 mm table for JLC04101H-3313 (the core thickness), and whether the stack-up can be chosen without
  impedance control.
* The live PCB prices, the small-via / Kelvin charge, and whether the flatness remark is accepted.
* The display panel's FPC (pitch, plug-in, contact side, pin 1, length).
* A LiPo 402535 with an SH plug and its polarity.
* A 2 mm pole-pair tape source with a thickness ≤ 0.60 mm.
* That mouse-bite nubs on the long edges clear the slider body.
