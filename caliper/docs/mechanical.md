# Mechanical design (rev A printed, rev B machined)

**Status: designed, not built or tested.** Every number below comes out of the model, the
calculation scripts and the FEA in [`caliper/hardware/mechanical/`](../hardware/mechanical/README.md).
None of it has been measured on a part yet. Items marked **(TVP)** are assumptions to verify on
the prototype; section 13 collects them.

* **Architecture of record:** [SPEC](../hardware/design/SPEC.md) sections 2, 2.1, 2.2 and 7, and the
  decisions D2–D5 in section 10. SPEC wins on any disagreement. The model follows the SPEC outline,
  holes and placement; section 3 lists the few places where the mechanics add detail SPEC leaves open.
* **Model:** [`params.py`](../hardware/mechanical/params.py) holds every dimension.
  [`models.py`](../hardware/mechanical/models.py) builds exact B-rep solids with build123d 0.13
  (OpenCascade). `run_all.sh` regenerates the board extraction, STLs, STEPs, drawings, clash report,
  calculations and renders in about four minutes (WSL, the dial-me-spinner venv).
* **Real board:** [`extract_board_parts.py`](../hardware/mechanical/extract_board_parts.py) reads the routed
  `caliper/hardware/kicad/slider/prettycool-caliper-slider.kicad_pcb` (KiCad 9 `pcbnew`) into
  [`board_parts.json`](../hardware/mechanical/board_parts.json): the Edge.Cuts outline with the end tabs,
  the five holes, 104 part envelopes (Fab outline × datasheet height), plus the four SMT standoffs,
  the H1 screw head and the mated JST plug.
* **Calculations:** [`calcs.py`](../hardware/mechanical/calcs.py) writes everything quoted here to
  [`calcs_output.txt`](../hardware/mechanical/calcs_output.txt). The FEA uses the `print-stress` solver
  (linear tets): the moving jaw in [`fea_jaw.py`](../hardware/mechanical/fea_jaw.py), and the whole slider
  body plus the board in [`fea_slider.py`](../hardware/mechanical/fea_slider.py).
* **Interference check:** [`clash_check.py`](../hardware/mechanical/clash_check.py) intersects the B-rep
  solids exactly, 6063 pairs, against the **routed board**. It writes
  [`clash_report.txt`](../hardware/mechanical/clash_report.txt). The result is in section 12.

---

## 1. Concept

| | |
|---|---|
| ![assembly](../hardware/mechanical/renders/assembly.png) | ![exploded](../hardware/mechanical/renders/exploded.png) |
| Assembly at reading 60 mm, with the routed board | Exploded along z: front shell and caps up; battery door, battery and back gib down |
| ![slider, front shell off](../hardware/mechanical/renders/slider_open.png) | ![board in the housing](../hardware/mechanical/renders/board_fit.png) |
| Slider with the front shell removed | Front view, lid off: the routed board, its end tabs clamped in the two towers |
| ![back](../hardware/mechanical/renders/assembly_back.png) | ![jaws closed](../hardware/mechanical/renders/jaws_closed.png) |
| Back: the closed back web over the beam, the battery door, the two back-plunger holes | Jaws closed (R = 0), seen from the front: the inside jaws cross above the beam |

Coordinates used everywhere (model, drawings, this page): **x** runs along the beam, with x = 0 at the
fixed jaw's measuring face. **y** runs across it, with y = 0 at the beam's lower (jaw-side)
**reference edge**, which is also the slider board's y (SPEC 2.1). **z** runs through it, with z = 0 at
the beam's front face and the back face at z = −4. The slider is built in its own frame u = x − R,
where R is the reading; board x = u − 8.

| Part | Rev A | Rev B |
|---|---|---|
| Beam | ground flat stock 20 × 4 × 250, O1 (preferred) or 1.4301, two pockets, five holes, one M2 tapped stop hole | same, to drawing PCC-M-02 |
| Fixed jaw | printed PA-CF block clamping the beam end with 2 × M3 + 2 × Ø3 dowels; **prints front face down** | 6061-T6 or tool steel |
| Slider body | printed **PAHT-CF**, with an unfilled-PA modifier volume near the antenna (PETG for fit trials). A closed tunnel round the beam with a 3.2 mm back web; the outside and inside moving jaws are integral; the board's end tabs are clamped in the two towers | CNC 6061-T6, drawing PCC-M-01 |
| Front shell | printed lid: landscape display window and bezel ribs, button holes, hex-key access to the pad screws, pockets for the tab-clamp screw heads, piezo port, LED light pipe | printed (RF) |
| Battery door | printed; a 2.0 flange in a rebate in the body's back face plus a 1.2 plug down to the cell. **Replaces the old back cover** | printed |
| Gibs | brass C360: back gib, Y gib, reference strip, 4 front pads | same |
| Depth rod | **omitted in rev A** (section 8) | open |

Key numbers (from `params.py`, `calcs_output.txt` and the FEA outputs):

| Quantity | Value |
|---|---|
| Housing envelope | **76.9 × 52.0 × 16.0 mm**; the thumb-roller rim at u 78.0 from the jaw face, 0.6 proud of the end face (SPEC 7: ≤ 78 × 52 × 16 with the roller) |
| Travel | 0–150 mm, hard stop at 151 (an M2 socket-head screw in the beam, removable) |
| Capacitive gap | 0.150 nominal; **±0.029 RSS, ±0.064 worst** after the tab-clamp bedding |
| AS5311 gap | 0.300 nominal; **±0.034 RSS, ±0.097 worst** after the per-unit shim, inside the SPEC window of ±0.10 |
| Sliding force | **3.9 N** at μ 0.15 (oiled brass on ground steel), 5.2 N at μ 0.20; was 8.0 N |
| Moving-jaw flex at the tip, 5 N | PETG 15 µm, PA-CF 6.1 µm, 6061 0.3 µm (beam theory); FEA 14.3 / 5.8 / 0.4 µm |
| Back web under the back preload | 1.7 µm at the plunger seat (FEA); the old back cover bent 0.6–1.1 mm |
| Masses (solid) | beam 124 g, slider body 32 g PA-CF / 76 g 6061, back gib 9 g |

## 2. Stack-up and sections

![section through the AS5311](../hardware/mechanical/renders/section.png)

![section detail: gaps](../hardware/mechanical/renders/section_gaps.png)

![section through the left tab clamp](../hardware/mechanical/renders/section_clamp.png)

The sections are exact `section()` cuts of the solids from `render.py`, at R = 0: x = 39 through the
AS5311, and x = 4.5 through the left tower's two tab clamps.

| z (mm) | Item | Source |
|---|---|---|
| +6.8 | front-shell top (button caps +0.6 above) | `Z_LID` |
| +5.4 | front-shell underside = body front face. The display glass is glued here, 1.6 thick, down to +3.8 | display 31.0 × 17.6 × 1.6, landscape |
| +5.0 … +6.0 | tab-clamp screw heads: 0.4 in a body counterbore, 0.6 in a pocket in the lid underside | M2 × 4 low head |
| +3.65 | tab-clamp ceiling: 0.2 epoxy over a 0.3 shim washer on the standoff | `CLAMP_CEIL_Z` |
| +1.15 … +3.15 | SMT M2 standoffs on the tab holes | SPEC D3 |
| +1.15 | board top. Tallest part: J1 USB-C at 3.30 → +4.45 (limit 4.2 above the board); under the glass, SW20 at 2.0 (limit 2.6) | SPEC 2.1 |
| **+0.15** | **board bottom = capacitive electrodes** | SPEC 7 cap gap 0.15 |
| 0.00 | beam front face; scale PCB face flush (pocket 0.85 = 0.80 PCB + 0.05 467MP) | SPEC 7 |
| −0.95 | AS5311 package face (A nominal 1.10; JEDEC MO-153 range 0.85–1.20) | |
| **−1.25** | **tape face**: 0.30 below the AS5311 | SPEC 4.1 |
| −2.00 | tape-channel floor (0.60 tape + 0.05 adhesive + 0.10 Kapton shim for a nominal package; 0–0.35 per unit) | SPEC D2 |
| −4.00 | beam back face; back gib 1.2 thick, down to −5.2 | |
| −5.4 | tunnel back = back-web inside face = battery-pocket floor | `Z_WEB_IN` |
| −8.6 | body back face (print bed) = battery-door outside face | `Z_BACK` |

Across the beam (y): reference strip at y −1…0 under the lower edge; front-pad lands at y 0…1.9 and
17.55…20; **tape channel at y 1.9…10.1** (8.2 wide; the AS5311's 6.4 mm lead span runs inside it with
0.9 each side); a 0.35 land; **scale pocket at y 10.45…17.55**; Y gib at y 20…21 on the upper edge.

The board sits 0.15 above the beam over its whole lower band, so nothing on its bottom may cross the
beam except inside the tape channel. The real board meets that rule (section 12). The housing
touches the beam front face **only at its two end towers** (u 0.5…7.6 and 70.4…77.4), beyond the
board's body. The board's end tabs reach into those towers.

## 3. Alignment with SPEC

The first model's deviations DEV-1 to DEV-5 are all closed. They became SPEC D2 (tape, channel),
D3 (tabs instead of the three upper-band holes), D4 (landscape display, placement, USB-C y 26.5) and
D5 (scale x 14.5). The model now uses the SPEC numbers. Where SPEC leaves a choice to the mechanics,
the model does this:

| SPEC says | The mechanics chose |
|---|---|
| D3: the four clamp faces coplanar within 0.03; "faced washers, insert faces, or the rev B machined tower" | **Bedded shim washers**: each clamp face is a 2.2 × 4.0 × 0.3 washer bedded in epoxy while the board lies on 0.150 shim foil on the beam's lands. The clamp faces then copy the beam face, not a bridged printed surface (sections 5 and 7) |
| D3: H1 is a support, "printed low and shimmed" | H1 boss printed 0.1 low and shimmed with Kapton; M2 tapped in the print for the nylon screw (no brass insert, which would sit 4 mm from the antenna) |
| Open item: support under the button band over the battery | A **button-band ledge** (u 37…65.5, y 32.6…34.4) cantilevered from the cavity wall under the board's top edge, shimmed to contact (section 5) |
| D4: the right Y plunger and the lock move out of the battery pocket | Both Y plungers (u 14, 24) and the lock (u 19) now sit **left** of the pocket. They pass under the antenna, so each pushes the gib through a **Ø2 GFRP rod**; the springs, screws and inserts sit at y ≥ 41 (section 4) |
| D4 / 7: no metal or carbon fibre within 5 mm of the antenna | Checked in plan for every metal item (section 12). The body region u 6.4…28.55, y 24.5…39 prints in **unfilled PA** through a slicer modifier (`stl/slider_body_rf_modifier.stl`). The PA-CF moving inside jaw is 4.70 mm in plan from the antenna, inside the 5 mm: an open RF risk (section 12) |
| 7: lead channel + JST plug relief past the top edge, sound port, light pipe | Plug relief at u 29.5…36.5, y 33.6…41, open into the battery pocket; Ø1.5 piezo port at u 48, y 24.3; Ø2.0 light pipe at u 59.5, y 32 |
| 2.1: lid end ribs x 16.15…17.5 and 48.5…49.85 | Those two, plus a rib along the glass's top edge (y 18.8…20.15) to locate it in y, inside SPEC's 2.6 mm zone |

Two choices are the mechanics' own and are not SPEC items:

* **Slim USB-C cable.** The cable-overmold relief is now 10.6 × 6.0, kept above the beam tunnel
  (y ≥ 21.2). The first relief (12.4 × 6.6) cut the right tower's front part off from the upper body.
  The cable's overmold must be ≤ 10.4 × 5.8 (TVP).
* **The inside jaws moved in z** so that each prints on its own part's bed with no support (section 8):
  the moving one is at z −8.6…−6.2, the fixed one at −6.0…+2.5. The tips still cross with a 0.2 mm
  gap. A bore must still be at least ~2.6 mm deep for both tips to engage (inserted back face first),
  the same as before.

Placement deviations reported by the layout track (U4, the TX ladder, FID3, U1, module x 7.85, J2 y
30.6, J50 y 7.5, SW20 rotation, C8/C10/C30) are all in the extracted envelope. None of them clashes
with the housing.

## 4. How the slider locates on the beam

![FEA, body under the preloads](../hardware/mechanical/renders/fea_body.png)

Five brass contacts and three spring loads:

* **Y (across the beam):** the brass **reference strip** (1.0 × 3 × 76.9, glued into the lower rail)
  rides on the beam's lower edge, which is reference edge E. Two **Y plungers** at **u 14 and 24** push
  the brass **Y gib** onto the upper edge, which pulls the strip up onto edge E. Each plunger is:
  * an M2 set screw in a heat-set insert at the top face (y 46…49);
  * a spring (y 41…46), the only metal moving part;
  * a **Ø2 GFRP rod**, which carries the push past the antenna down to the gib.

  The bores run at z −2.3, 0.6 mm under the cavity floor. The 5 N measuring force at the jaw tip
  (y −37) and the thumb's drive force form a couple that lifts the strip's left end. Moving both
  plungers left raised their lever about the strip's right end from 81.5 to **116.8 mm**. Keeping the
  strip seated now needs **≥ 2.4 N each** with the roller drive and ≥ 3.1 N for a push on the end face
  (calcs §2). The design value is **4.0 N each**, a 1.64× / 1.30× margin (6 N before).

  Trade-off: nothing on the right end resists a moment of the other sense. A −y push on the
  slider's right end above **1.9 N** lifts the strip there while it lasts. No measuring load makes
  that moment: outside and inside measurements both lift the left end.
* **Z (through the beam), position:** four brass **front pads** (4 × 1.5 or 2.0 × 1.0) ride on the
  beam's front lands (y 0.2…1.7 and 17.8…19.8) under the two towers. Each sits under an **M2 set
  screw** in an insert, reached through Ø2.0 holes in the front shell. They set the tower height. The
  board height is then fixed by the tab-clamp bedding (section 7), and the screws are only a trim.
* **Z, preload (review fix a):** the brass **back gib** (1.2 × 14 × 64) is pushed onto the beam's
  back face by two spring plungers. They now sit in the **body's 3.2 mm back web**, which closes the
  tunnel behind the beam and ties the lower rail to the upper body. They are at **(u 14, y 5) and
  (64, 5)**, **2.5 N each**. The first model put them in a back cover screwed only at y 44: a 34 mm
  cantilever that bent 0.6–1.1 mm in PA-CF and used up the plungers' travel. FEA of the whole body
  (`fea_slider.py`, PA-CF, both preloads) gives **1.7 µm** at the plunger seats, and 0.1 µm at the
  tab-clamp ceilings. The reactions balance the loads (9.43 N). Stress is under 0.25 MPa (utilisation
  ≈ 0 in the figure). Moving the plungers from y 10 to y 5 raised their lever to the upper pad line
  from 8.8 to 13.8 mm. A button press (2.5 N at y 31) now needs ≥ 1.1 N each. A grip on the battery
  bay above **3.3 N at the top edge** lifts the lower pads while it lasts; the gaps then open, they
  never close.
* **Locking screw:** an M3 knurled thumb screw in an M3 insert at the top face, at **u 19**, pushes a
  third GFRP rod onto the Y gib. Its head stands 4 mm above the top face.
* **Thumb roller:** a printed Ø7 hub with an NBR O-ring (ID 6 × 0.8) on a Ø2 pin, rolling on the
  beam's upper edge with 0.15 mm squeeze. The rim is at **u 78.0**, 0.6 proud of the right end face,
  below the USB-C. The axle hole now runs through to the USB relief, so the pin can be pushed out.

**Sliding force (review fix c).** Every preload acts on two faces, so F = 2 × (2 P_back + 2 P_Y) × μ:

| Preloads | Normal load | μ 0.12 | μ 0.15 | μ 0.20 |
|---|---|---|---|---|
| First model: back 4 N, Y 6 N | 20 N | 4.8 N | 6.0 N | 8.0 N |
| **Now: back 2.5 N, Y 4.0 N** | 13 N | 3.1 N | **3.9 N** | 5.2 N |

The target is 2–5 N, as for a commercial caliper. μ 0.12–0.15 is brass on ground steel with a light
oil film; dry brass on steel is 0.3–0.35, so keep the beam oiled. The lower preloads cost no seating
margin, because both levers grew. The plunger set screws trim the force on the bench (0.4 mm per
turn). The O-ring's rolling resistance is not included (TVP).

The outside jaw is 11.0 thick (z −8.6…+2.4, on the print bed). Its centre is 1.1 mm off the beam's
mid-plane, so the 5 N measuring force puts a 5.5 N·mm twist into the guide, which is small.

## 5. Board support (SPEC D3)

* **Tab clamps (Z datum).** The board's end tabs (x −6…0 and 62…68, y 2.5…16.5) sit in pockets in
  the towers (u 1.8…8 and 70…76.2, y 2.3…16.7), open to the tunnel below. On each of H2–H5 an SMT
  M2 standoff (2.0 tall) rises into a Ø4.4 pocket. An **M2 × 4 low-head screw** from the tower's front
  face pulls it up against a **2.2 × 4.0 × 0.3 shim washer bedded in epoxy** under a printed clamp
  plate 1.35 mm thick. The screw tip ends inside the board, never below it.
* **Bedding instead of printed faces.** A downward printed clamp face is a bridged surface (±0.1).
  So the washers are bedded while the board lies on 0.150 mm shim foil on the beam's ground lands
  (section 7). The four clamp faces then sit in the plane of beam face D, and the open-loop ±0.10
  clamp-height term drops out of the stack (section 6).
* **H1** (18.75, 24): a nylon M2 screw into a boss printed 0.1 low and shimmed to contact. It is
  tightened last, and the board must not move more than 0.01 when it is.
* **Button-band ledge.** HOLD and MODE sit over the battery pocket, with no body under the board.
  The FEA of the board (`fea_slider.py`) used the real outline and tabs, clamped at the four
  standoffs, resting on H1, with 3 N on one switch at a time. It gives these deflections:

  | 3 N on | Without the ledge: button / electrode band / AS5311 | With the ledge |
  |---|---|---|
  | ZERO | 46 / 19 / 6 µm | 0.5 / 0.7 / 0.5 µm |
  | HOLD | 92 / 35 / 8 µm | 0.5 / 1.0 / 0.8 µm |
  | MODE | 129 / **42** / 12 µm | 0.5 / 1.0 / 0.6 µm |

  Without support, a MODE press closed the capacitive gap by 28 %. The ledge runs under the board's
  top edge (u 37…65.5, y 32.6…34.4), where the board's bottom is plain solder mask. It is printed
  0.05 low and shimmed to contact like H1. The FEA treats it as rigid; its own compliance as a
  printed 1.8 mm cantilever adds about 6 µm under the full 3 N. Linear tets are stiff in plate
  bending, so the board results are corrected ×1.75. A cantilever strip meshed the same way in the
  same run calibrates that factor.

## 6. Gap stack-up

From `calcs.py` §5 and §6:

| Gap | Open loop | After the bedding and the per-unit shim (section 7) | Window |
|---|---|---|---|
| capacitive 0.15 | ±0.165 RSS, ±0.34 worst: **can't be built open loop** (scale FR4 ±0.08, printed clamp face and tower ±0.10 each) | **±0.029 RSS, ±0.064 worst**: the electrodes never touch | experimental; touching is the only hard limit |
| AS5311 0.30 | ±0.187 RSS: **outside** (package height alone is ±0.175) | **±0.034 RSS, ±0.097 worst: inside** | 0.20–0.40 (SPEC 4.1) |

The board-height terms after the bedding are:

| Term | Value | Notes |
|---|---|---|
| shim foil | ±0.005 | TVP: measure the foil |
| beam face flatness | ±0.010 | |
| board flatness residual | ±0.015 | half the SPEC 0.03 band; every board is inspected |
| epoxy cure shrinkage | ±0.004 | |
| clamp-seat creep | ±0.010 | PA-CF, TVP |
| thermal of the clamp chain, ±10 K | < 0.001 | |
| tower movement under a ±20 % preload drift | < 0.001 | FEA |

Their RSS is ±0.022, against ±0.04 with the first model's bosses, set screws and an unsupported
7–24 mm overhang. The first model's AS5311 worst case (±0.13) was outside the window. This one is
just inside. The firmware field check (section 7, step 7) still accepts or rejects each unit.

## 7. Setting the gaps (assembly procedure)

1. **Before fitting the board:** micrometer the board + AS5311 stack beside the package, which gives
   the seated height A to ±0.005. Check the board's lower band (y 0…20, tabs included) on a surface
   plate and reject a board more than 0.03 out of flat (SPEC D3 fab note).
2. **Bond the scale and the tape** with 3M 467MP. Depth-gauge the tape face and the scale face below
   beam face D at 5 points along the travel. Predict the AS5311 gap = 0.15 + 2.00 − 0.05 − tape − shim − A,
   and lay 0–0.35 mm of Kapton shim (0.025 steps) under the tape until it predicts 0.30. Unshimmed,
   the tallest package (A max 1.20) gets 0.30. A shim only raises the tape, so every shorter package
   can be corrected.
3. **Assemble the slider on the beam:** reference strip, front pads, Y gib, back gib, GFRP rods,
   springs and set screws. Set the preloads to Y 4 N and back 2.5 N (TVP: by turns from contact, once
   the spring rates are known). Slide it on from the beam's right end, with the stop screw out. Set the
   four pad screws so the tower undersides sit about 0.1 over the beam.
4. **Bed the clamp washers:**
   * With the lid off, lay four strips of **0.150 steel shim foil** on the beam's ground lands
     (y 0.2…1.7 and 17.8…19.8) under the board's two ends.
   * Lower the board, with its standoffs reflowed on, onto them. The tabs go into the tower pockets.
   * Check the gap between each standoff and its pocket ceiling with feelers: 0.05–0.35.
   * Put a dab of slow structural epoxy on each shim washer's top face and wax the four clamp screws.
   * Fit the screws **finger-loose**, put a ~50 g weight on the board centre and cure 24 h.
5. **Clamp and check:** tighten the clamp screws lightly (TVP: 0.05 N·m) and slide the foil out. With a
   dial indicator (2 µm) on a base standing on the beam face, read the board top at three points over
   the electrodes. Board bottom = indicator − board thickness must be 0.150 ± 0.010 at all three. Trim
   with the four pad screws (M2 × 0.4: 0.1 mm = 90°), lock them with Loctite 222, and re-bed if a
   corner is out.
6. **H1 and the ledge:** shim the H1 boss and the button-band ledge with Kapton until each just
   touches (a 0.02 feeler drags). Fit the nylon H1 screw last; the indicator at H1 must not move more
   than 0.01.
7. **Check in firmware** at R = 0, 75 and 150:
   * AS5311 MagINCn and MagDECn both high (field in range);
   * SSI status OCF set, COF and LIN clear;
   * the capacitive RX amplitude varies by less than ±30 %.

   Record everything in the [bring-up](bringup.md) log. Fit the stop screw (Loctite 222).

## 8. Parts, print settings and orientation

Bambu P2S, 0.4 mm nozzle, 0.20 mm layers, textured PEI plate. PAHT-CF needs the hardened nozzle and
filament dried at 80 °C for 8 h. The body's RF modifier prints in unfilled PAHT from a second AMS
slot; PAHT and PAHT-CF bond. Every printed part was run through the `bambu-p2s` printability check
(`printcheck.py`) on the exported print-pose STLs, and every STL is watertight (trimesh):

| Part | File | Material | Pose | Settings | Printability check |
|---|---|---|---|---|---|
| Slider body | [`stl/slider_body.stl`](../hardware/mechanical/stl/slider_body.stl) + [`rf_modifier`](../hardware/mechanical/stl/slider_body_rf_modifier.stl) | **PAHT-CF**; the modifier in PAHT (PETG for fit trials) | back face down | 6 walls, 40 % gyroid, solid jaws | FAIL without supports. **Paint-on supports in three places:** (1) the roller-slot roof (7 mm); (2) the battery-pocket ceiling over y 34…48 (14 mm, the plug relief breaks its bridge), from the build plate through the door rebate; (3) the tower undersides beside the tab pockets (3.3 and 4.5 mm strips), standing on the back web inside the tunnel and pulled out through the tunnel ends. The 22 mm tunnel-roof bridges at the towers WARN as before. **The inside jaw no longer needs support** |
| Fixed jaw | [`stl/fixed_jaw.stl`](../hardware/mechanical/stl/fixed_jaw.stl) | PA-CF | **front face down** (was back face down) | 6 walls, 60 % infill | the beam-slot roof flags as a 5.6 mm cantilever. It is bridged 20 mm between both side walls, as before. **The inside jaw no longer needs support** |
| Front shell | [`stl/front_shell.stl`](../hardware/mechanical/stl/front_shell.stl) | PETG | top face down (textured) | 4 walls, 100 % | PASS |
| Battery door | [`stl/battery_door.stl`](../hardware/mechanical/stl/battery_door.stl) | PETG | outside face down (textured) | 4 walls, 100 % | PASS |
| Button cap × 3 | [`stl/button_cap.stl`](../hardware/mechanical/stl/button_cap.stl) | PETG | flange down | 100 % | PASS |
| Thumb roller | [`stl/thumb_roller.stl`](../hardware/mechanical/stl/thumb_roller.stl) | PETG | flat | 100 % | PASS |

**Inside jaws (review fix d).** Each inside jaw now starts on its own part's print bed. The moving one
spans z −8.6…−6.2 on the slider's back face. The fixed one spans −6.0…+2.5, reaching the fixed jaw's
front face, which now goes on the bed. So both 14 mm overhangs are gone, with no split part and
nothing glued. The other two FAILs in the first model (the roller-slot roof and, now, the pocket and
tower strips) are short and non-functional faces, so they get specified supports rather than a split
part.

Clearances: sliding parts get 0.15–0.20 per side (`CLR_SLIDE`); the brass gibs and pads float in
0.10–0.15 pockets. Heat-set inserts are M2 × 3 in Ø3.2 holes and M3 × 4 in Ø4.0; thread-forming screws
go into Ø1.7 pilots. The STEP of every part is in [`step/`](../hardware/mechanical/step/), in assembly
pose, plus [`step/caliper_assembly.step`](../hardware/mechanical/step/caliper_assembly.step) (40 named
solids at R = 0).

![parts in print pose](../hardware/mechanical/renders/parts.png)

**Depth rod:** omitted in rev A. The back face carries the back gib and its web, and the right tower
holds the roller, the USB relief, a tab clamp and two pad screws.

## 9. Calculation results (summary)

**Jaw deflection** (calcs §1; FEA in `fea_jaw_output.txt`, figure `renders/fea_jaw.png`). The jaw is
11.0 thick (it grew from 7.8 when the body's back face moved to the print-bed plane), 20 wide to
y −8, and tapers to 3.5 at the tip, y −40. It is printed back face down, so it bends in the layer
plane. Interlayer stress is 0.10 MPa (FEA), so strength is not the issue; stiffness is.

| Body | Tip contact (y −37), 5 N: beam theory | FEA, tip | Per N | 2–8 N thumb spread |
|---|---|---|---|---|
| PETG | 15.1 µm | 14.3 µm (datasheet E; ÷0.85 → 16.8) | 3.0 µm/N | **18 µm** |
| PA-CF | 6.1 µm | 5.8 µm | 1.2 µm/N | **7.3 µm** |
| 6061-T6 | 0.3 µm | 0.4 µm | 0.06 µm/N | 0.4 µm |

The fixed jaw (PA-CF) adds about the same again.

**Thermal** (calcs §4, error after zeroing, per 10 K, worst of two bounds). The board is now clamped
at both tabs, so the AS5311 (exactly midway between them) moves with the body over 39 mm rather than
over 11 mm of body plus FR4. Results: PETG body on O1 24 µm, PA-CF on O1 9.1 µm, 6061 on O1 6.3 µm.
A 1.4301 beam adds 0.7 µm/K at 150 mm against steel workpieces. Zero after warm-up.

**Preloads, sliding force, back web:** section 4. **Board under a button press:** section 5.

## 10. Rev B machining

* **[`drawings/slider_body_b.pdf`](../hardware/mechanical/drawings/slider_body_b.pdf)** (PCC-M-01)
  and `step/slider_body_b.step`: the body in 6061-T6, stress-relieved plate, clear anodise with the
  channel and jaw face masked. Tapped M2 × 0.4 and M3 holes replace the inserts and pilots.
  * Datums: A = jaw measuring face, B = channel lower face (reference-strip seat), C = tower underside.
  * The gib and lock bores (u 14 / 19 / 24, z −2.3) are at ±0.02 from A.
  * The tab-clamp faces are machined coplanar within 0.02, with no bedding.
  * **The 6061 body needs a non-metal window** under and beside the antenna (u 3.1…29, y 24.5…39):
    machine it open and bond in a printed or POM insert (SPEC D4).
* **[`drawings/beam_pockets.pdf`](../hardware/mechanical/drawings/beam_pockets.pdf)** (PCC-M-02) and
  `step/beam_pockets.step`:
  * Rough both pockets and all holes 0.2 under.
  * **Tap the M2 stop hole before hardening.**
  * Harden O1 to 58–60 HRC (1.4301: stress-relieve only).
  * Grind face D and edge E.
  * Only then finish the pockets from D and the holes.
  * Edge E straight 0.01 over any 150; face D flat 0.01/150.
* **Jaw faces:** flat 0.005 and parallel 0.01, reached by lapping the two jaws together, then checked
  against gauge blocks at three heights. The optional hardened jaw insert (2.0 × 6 × 34, 1.2379/D2 or
  carbide) is unchanged.

## 11. Hardware BOM

| Item | Qty | Spec / source |
|---|---|---|
| Beam | 1 | ground flat stock 20 × 4, O1 (1.2510 "gauge plate") or 1.4301, cut to 250 (TVP: exact SKU) |
| Magnetic tape | 172 mm | ams AS5000-MS10-H075-100 or a generic 2 mm pole-pair tape, slit to 8.0 mm, ≤ 0.60 thick with backing (width and thickness TVP) |
| Adhesive transfer tape | – | 3M 467MP (0.05) for the tape and the scale |
| Kapton shim | – | 0.025 mm sheet: 0–14 layers under the tape; strips for the H1 boss and the button ledge |
| Steel shim foil 0.150 | 4 strips | assembly tool for the bedding (step 4); reused |
| Brass C360 | – | 1.2 × 14 × 64 (back gib), 1.0 × 3 × 60 (Y gib), 1.0 × 3 × 76.9 (reference strip), 1.0 sheet for 4 pads |
| SMT M2 standoff, 2.0 tall, OD ≤ 4.0 | 4 | PEM SMTSO-M2-2ET class, on H2–H5 (schematics track picks the LCSC part; else hand-fitted) |
| Shim washer 2.2 × 4.0 × 0.3 | 4 | precision shim washer (e.g. MISUMI); bedded in slow structural epoxy |
| M2 × 4 low head (k ≤ 1.0) | 4 | tab clamps |
| Nylon M2 × 5 pan head | 1 | H1 |
| Heat-set inserts M2 × 3 | 10 | in the body: 4 pad screws, 2 Y plungers, 2 lid (upper), 2 back plungers |
| Heat-set insert M3 × 4 | 1 | lock |
| Thread-forming screw for plastics, 2.2 × 5 countersunk (WN 1452 / PT K20 class) | 4 | 2 lid (towers), 2 battery door |
| M2 × 6 countersunk | 2 | lid, upper corners |
| M2 set screws, cup point | 8 | 4 × M2 × 4 (front pads), 2 × M2 × 3 (Y plungers), 2 × M2 × 2 (back plungers) |
| Compression springs | 4 | Y: ~4 N at ~1 mm, OD ≤ 2.0; back: ~2.5 N at ~1 mm, OD ≤ 1.5 (it passes through the M2 insert) (TVP: stock parts, e.g. Lee Spring LC series) |
| GFRP rod Ø2 | 3 | 2 × 20 mm (Y plungers), 1 × 24 mm (lock); glass-fibre, non-conductive |
| M3 × 6 knurled thumb screw | 1 | lock |
| M2 × 6 socket head ISO 4762 | 1 | end stop, Loctite 222 |
| Steel pin Ø2 × 6 m6 | 1 | roller axle |
| Dowel pins Ø3 × 10 m6 | 2 | fixed jaw |
| M3 × 10 socket/button head + M3 nut | 2 + 2 | fixed jaw (block 11.1 thick) |
| O-ring NBR ID 6.0 × 0.8 | 1 | thumb-roller tyre |
| Epoxy | – | clamp washers (slow structural); reference strip in the rail; display glass to the lid ribs (or B-7000) |
| USB-C cable | – | overmold ≤ 10.4 × 5.8 mm (TVP) |

## 12. Clash check with the routed board

From `clash_report.txt`. The board envelope comes from `board_parts.json`, extracted from
`caliper/hardware/kicad/slider/prettycool-caliper-slider.kicad_pcb`.

* **6063 intersections, 0 not clear.** The only overlap is the intended one: the O-ring tyre
  squeezed 0.15 onto the beam.
  * **Board vs housing:** the board with its tabs, the 104 part envelopes, the four standoffs, the H1
    screw head and the mated JST plug, against the body, lid, door, caps, roller, gibs, pads, GFRP rods,
    display, battery, lock and the clamp hardware. All clear.
  * **Travel:** the slider and the board against the beam, fixed jaw, tape, scale and stop screw at
    R = 0, 75 and 151. All clear; the right end face meets the stop-screw head at R = 151.0.
  * **Slider-internal pairs:** all clear.
* **Gaps and board rules: all OK.**
  * AS5311 (U30 as placed) to tape: 0.300 at nominal A with the nominal shim, B-rep 0.200 at A max.
  * Electrodes to scale: 0.150.
  * AS5311 leads 0.9 inside the channel walls.
  * The bottom window (x 20…41) stays over the tape channel from R = 0 to 151.
  * Bottom parts over the beam band are only U30, C30, C31, inside the window, ≤ 1.30.
  * Tallest top parts: SW20 at 2.00 under the glass (limit 2.6), J1 at 3.30 elsewhere (limit 4.2).
  * No parts in the antenna keep-out; H1–H5 all have their boss or standoff room.
* **Body walls:** no cut feature breaks into another, and no web is under 0.4 mm. Local webs under
  the 1.2 mm wall rule:

  | Web between | Thickness |
  |---|---|
  | tab pocket / pad pocket | 0.45 |
  | tab clamps / pad inserts | 0.55 |
  | door pilot / battery pocket | 0.75 |
  | pad insert / USB relief | 0.80 |
  | H1 pilot / Y bore | 0.85 |
  | pad screw / tunnel | 0.90 |
  | tab clamps / lid pilot | 0.94 |

* **RF (SPEC D4): every metal item is ≥ 5 mm from the antenna area in plan.** The antenna area is
  taken where the layout placed the module (U10 origin x 7.85, so the antenna spans board x 0.15…15.55;
  the SPEC table's x 8.3 gave 0.6…16.0). The closest are the battery cell (6.45), the J2 plug (6.75),
  J2 (6.95), the Y-plunger springs and screws (7.5), the Y gib (8.5) and the beam (9.5). **The PA-CF
  moving inside jaw is 4.70 mm in plan (8.73 mm in 3D, behind the beam plane): inside the 5 mm, so
  the clash check flags it RISK.** It was 5.02 mm against the SPEC module position; the module moved
  0.45 mm toward it in layout. Options: print that jaw in unfilled PA, or accept it as a range-test
  item (SPEC §7 already lists the jaw as an RF risk). The 3.03 cm³ of body within 5 mm prints in
  unfilled PA through the modifier.

The first model's two findings are gone with the new placement: MODE cap × USB-C, and U_MCU × SW_MODE.

## 13. Risks and things to verify

1. **The bedding procedure is new and untested.** Things to verify: epoxy bed thickness and
   shrinkage, that the foil comes out cleanly, and the clamp-seat creep in PA-CF under the screw
   (±0.01 assumed). If it fails, the fallback is per-unit shim washers under each clamp face
   (0.025 steps), measured with the indicator.
2. **Holding the 0.3 mm AS5311 gap** still needs the per-unit A measurement and tape shim. The worst
   case (±0.097) is only just inside the window, so the firmware field check decides each unit.
   Board flatness (≤ 0.03, inspected) and the tape thickness along its length are TVP.
3. **Jaw accuracy with a printed body:** PETG flexes 18 µm at the tip over a 2–8 N thumb spread;
   PA-CF 7 µm per jaw. Judge rev A on PA-CF parts, measured near the jaw root.
4. **Springs:** 4 N and 2.5 N in about 1 mm, OD ≤ 2.0 / ≤ 1.5, are not sourced (TVP). The sliding
   force is 3.9 N only with the beam oiled (μ 0.15); 5.2 N at μ 0.20.
5. **Yaw at the right end:** a −y push above 1.9 N on the slider's right end lifts the reference strip
   there (section 4); measuring loads never do.
6. **Supports** are still needed in three non-functional places on the body (section 8). The roller
   roof and the tower strips are inside the part, so check that the supports come out.
7. **Antenna:** the clearance is SPEC D4's 5 mm (not Espressif's 15). The modifier volume, the GFRP
   rods and the nylon H1 screw keep metal and carbon away, except the PA-CF moving inside jaw at
   4.70 mm in plan (section 12). The RF range test at bring-up decides.
8. **Slim USB-C cable** (≤ 10.4 × 5.8 overmold) is a usage constraint (TVP: check common cables).
9. **Tape:** the ams strip's width and thickness are unconfirmed. A magnetic (O1) beam under the tape
   may change the field the AS5311 sees (TVP: check MagINC/MagDEC on both beam materials).
10. **Fixed-jaw bolts:** the block is 11.1 thick. An M3 × 10 engages the nut by ~1.4 mm; an M3 × 12
    would stand 0.9 proud of the back. TVP: an M3 × 11 cut from a 12, or a deeper nut trap.
11. **Inside-jaw usage:** the moving inside jaw is now the back one. For a shallow bore, insert the
    jaws back face first (about 2.6 mm of depth for both tips, as before).

## 14. Change record

**Phase 3 (mechanics against the routed board), 2026-11-08.**
* `params.py` now follows the SPEC outline (tabs), holes, placement and the D2/D4/D5 numbers.
  A test checks it against `nets.SLIDER_OUTLINE` / `SLIDER_HOLES` / `SLIDER_KEEPOUTS`.
* The extractor reads the real board: aux origin, outline, standoffs, H1 head, JST plug.
* The clash check gained the wall and RF sections. Result: 0 clashes.
* **(a)** back cover → body back web + battery door;
* **(b)** tab clamps with bedded washers, H1 low and shimmed, button-band ledge; the new bow and clamp
  terms are in the stack;
* **(c)** plungers rebalanced, 8.0 → 3.9 N;
* **(d)** both inside jaws print on their beds, the fixed jaw prints front face down, and the remaining
  supports are specified;
* **(e)** the end face moved to 77.4 (roller rim at 78.0); the stop is an M2 screw; the gib/lock bores
  sit 0.6 under the cavity floor and moved left of the battery;
* **(f)** the FEA figure KeyError is fixed (the saved array now carries `eb` / `names` / `layers`). The
  jaw FEA was re-run, and a body + board FEA was added.
* Tests: 33 pass. 13 STLs are watertight. Drawings regenerated.

**Phase 2 review** (earlier):
* tape channel 1.90 → 2.00;
* yaw preload with the drive couple;
* the AS5311 worst case corrected;
* the beam-drawing process order fixed;
* found but not fixed then, and fixed now: the back cover, the unsupported lower band, the roller
  length, the stop pin.
