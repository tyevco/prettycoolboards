# PrettyCool Keyboard rev A: hardware as code

> **Status (2026-11-27):** the toolchain below generates, routes and gates every rev A board from Python. The
> **test coupon** is captured, laid out, routed and gated (ERC/DRC/parity/jlcplace) on 2026-11-27; not built, not
> measured. The **motherboard** schematic is captured and gated (wiring rule, ERC, `check_contract.py`) on
> 2026-11-27, with the owner's decisions D2-D6 of that evening in it ([below](#the-motherboard)); not laid out, not
> built, not measured. Every board is registered in `sheets/__init__.py`; `kicad/<board>/` and `fab/<board>/` show
> how far each has got. **No board is ordered** until the two conditions of
> [SPEC §1](SPEC.md#_1-purpose-and-what-rev-a-must-prove) are met (the MCUs in hand, bought by the owner from ST's
> store; 8 kHz HID proven on the Nucleo): every `ORDER-NOTES.md` says so at the top.

The architecture of record is [SPEC.md](SPEC.md) plus [nets.py](nets.py) (the motherboard's capture contract and the
slot pinout). The flow is the caliper's ([caliper/hardware/design](../../../caliper/hardware/design/)), on the shared
toolchain in [tools/](../../../tools/README.md), and the [wiring rule](../../../tools/README.md#wiring-rule) applies
without exception: no label fallback, no waiver.

## Commands

From the repository root. In the cloud container: `PY=/root/.venvs/kbd/bin/python` (pcbnew 10.0.8, jlcplace 0.2.1)
and `export FREEROUTING_JAR=/opt/freerouting/freerouting.jar`. On the owner's machine the same commands run in WSL
with `PY=$HOME/.venvs/dial-me-spinner/bin/python` (CLAUDE.md).

```sh
$PY keyboard/hardware/design/build.py --board test-coupon --render   # schematic, wiring check, ERC, netlist, PDF/PNG
$PY keyboard/hardware/design/build.py                                 # every captured board (the others are skipped)
$PY keyboard/hardware/design/build.py --board test-coupon --out /tmp/x --no-erc   # scratch build
$PY keyboard/hardware/design/layout.py --board test-coupon --route --minutes 4 --attempts 2   # place, route, DRC
$PY keyboard/hardware/design/layout.py --board test-coupon --place-only            # placement only, to look at
$PY keyboard/hardware/design/release.py --board test-coupon --refit-jlc            # fab package + jlcplace gate
$PY keyboard/hardware/design/check_contract.py      # motherboard netlist == nets.py (MCU pins and the rest, below)
$PY keyboard/hardware/design/nets.py                # the contract's own consistency check
$PY tools/netlist_diff.py --strict-fields OLD.net NEW.net   # equivalence gate after a generator change
```

`--refit-jlc` needs the network (EasyEDA records for new parts); without it `release.py` reads the jlcplace cache.
`release.py` fetches the 3D models a board uses from kicad-packages3D (tag 10.0.8) into `~/.cache/kicad-3dmodels/`
when `$KICAD10_3DMODEL_DIR` is not set (this container has no KiCad 3D library); nothing from there is committed.

## Gates

| Gate | Where | Pass |
|---|---|---|
| Wiring rule R1-R6 (`Design.check()`) | build.py | no `CHECK:` line |
| ERC (kicad-cli, all severities) | build.py | clean, or only the waivers listed with a reason in `build.py` `BOARD_ERC_WAIVERS[<board>]` |
| Netlist stability | build.py twice, then `tools/netlist_diff.py --strict-fields` | IDENTICAL |
| Capture contract (motherboard) | check_contract.py: the MCU pins, expanders, mux, U_CC, INA226 straps and Kelvin ties, sockets with the pin 39 key and the 37 series resistors, lanes, bus switches, PGTH divider, +3V3A damping leg, headers | OK |
| Coupon mating | layout.py (`boards/coupon_common.check_mating()`, every coupon) | all 40 header and socket pins at the same top-view position |
| DRC with schematic parity | layout.py, release.py | 0 errors; **no check ignored** (the five KiCad 10 leaves at "ignore" are turned on: four as errors, the footprint-filter check as a warning) |
| jlcplace (cpl + check + cross-check without the database) | release.py | no red row or red run finding; yellow rows and the preview checklist go into ORDER-NOTES.md |
| Caliper unaffected (after any `tools/**` change) | caliper build.py --out scratch, netlist_diff vs the committed .net, `pytest tools/tests` | IDENTICAL, passed |

## Folder plan

```
keyboard/hardware/
  design/
    SPEC.md, nets.py                 architecture of record, motherboard contract (slot pinout, MCU map)
    build.py                         schematics, all boards (--board NAME)
    layout.py                        PCB driver, all boards (--board NAME)
    release.py                       fab outputs (--board NAME)
    check_contract.py                motherboard netlist == nets.py (MCU pins via nets.KICAD_PIN_ALIAS, and the rest)
    sheets/__init__.py               PROJECTS: board -> title, sheet modules
    sheets/parts.py                  shared parts: R / C tables with LCSC basic parts, AO3400A, LED, pads, holes, fiducials
    sheets/coupon_common.py          the slot sheet every coupon carries (header, EEPROM, post, fiducials)
    sheets/mb_*.py                   motherboard sheets (globbed, ordered by PAGE)
    sheets/motherboard_parts.py      motherboard part tables, generated symbols and footprints, INA226 / switch helpers
    sheets/<board>.py                one module per other board (coupon_hall.py, latency_rig.py, test_coupon.py ...)
    boards/geom.py                   board-mm helpers (P, B, V, rect, rounded_rect, circle ...)
    boards/coupon_common.py          coupon outlines, header/socket placement and mating check, post, keep-outs, stack, pours
    boards/<board>.py                one layout module per board
    mpn/<board>.csv                  vendor-neutral MPN map, one row per LCSC code of the board
    jlcplace-db/<LCSC>.json          jlcplace corrections and recorded decisions (shared by all boards)
  kicad/<board>/                     GENERATED: project, sheets, lib/, render/, .net, erc.rpt, .kicad_pcb, -drc.rpt
  fab/<board>/                       GENERATED: release.py's package
  mechanical/                        build123d enclosures (mirror caliper/hardware/mechanical)
```

Board names: `motherboard`, `test-coupon`, `coupon-hall`, `coupon-tmr`, `coupon-shear`, `coupon-coil`,
`coupon-haptics`, `latency-rig`. Projects are `prettycool-keyboard-<board>`; every UUID is namespaced
`prettycool-keyboard/<board>`. Never hand-edit or save from the GUI anything under `kicad/` or `fab/`: change the
Python and rebuild, and commit the generated files with the change that made them.

## The motherboard

Captured on 2026-11-27 from SPEC.md and nets.py: ten sheets (`mb_usb` USB-C, ESD and U_CC; `mb_power` the input
breaker, LDOs and monitors; `mb_mcu`; `mb_io` expanders and mux; `mb_slots`, one sheet per slot S1-S5; `mb_headers`
SWD, rig, KVM, holes). Refs follow SPEC's names (U1, U2-U5, U_CC, U_EXP1-3, U_MUX, U_BSn, `U_PM<addr>`, J_Sn, J_SWD,
J_RIG, J_KVM, JP_3V3_Sn, JP_INJn), and the rest are numbered by sheet: usb 1-29, power 30-99, mcu 100-199, io
200-299, headers 300-399, slot n 100 n + 400 (S1 500-599 ... S5 900-999). Every part not fixed by SPEC is a
candidate, with its datasheet check and JLC stock in `sheets/motherboard_parts.py`. Gated: wiring rule clean, ERC
clean with no waiver, `check_contract.py` OK, netlist stable; **not laid out, not built, not measured**.

The owner's decisions of 2026-11-27 (SPEC §1) are in the capture, and `check_contract.py` holds each of them:

| Decision | What the schematic has |
|---|---|
| D2, the slot key | Socket pin 39 keeps its pad with no net (`nets.slot_pin_net()`). JLC lists no key plug and no 2 x 20 socket without contact 39, so hole 39 is plugged by hand at assembly (an assembly note, SPEC §4.2) |
| D3, the slot guard | 37 resistors of 100 ohm (C25076, basic) at the sockets on CS0_N, CS1_N, IRQ_N, G0-G3 and S5's G4/G5: `R<b+31>` ... (S1 R531-R537 ... S5 R931-R939). The socket pin is on `S<n>_<signal>_J`, the MCU side keeps `S<n>_<signal>` |
| D4, PGTH | R35 / R36 = 100 k / 44.2 k (C25895): VSYS_PG falls at 3.51-3.64 V |
| D4, +3V3A | The damping leg R103 0.47 ohm (C23411) + C118 10 uF 25 V (C15850) from +3V3A to GND, middle net VDDA_DAMP, at FB1's +3V3A end |
| D4, Kelvin | Every INA226's IN+ / IN- on its own pair (`PM<aa>_SENSE_P` / `_N`), joined to the shunt's power net by a net tie at the shunt's pad: KiCad `Device:NetTie_2`, footprint `NetTie:NetTie-2_SMD_Pad0.5mm`, refs `NT<aa>P` / `NT<aa>N` (26 ties, not in the BOM) |
| D5, headers | J_RIG and J_KVM are shrouded box headers: BOOMELE 2.54-2*5P (C5665) and 2.54-2*6P (C9136) on KiCad's `Connector_IDC:IDC-Header_2x05/2x06_P2.54mm_Vertical`; pinouts unchanged |
| D6, alternates | `mpn/motherboard.csv` lists STM32U599VJT6 (C18213037) and STM32U595VJT6 (C7938448) as U1's alternates, marked as not on the BOM |

What the layout must place by hand (SPEC §9; `boards/motherboard.py` is the layout task's): each series resistor
within about 10 mm of its socket pad; each net tie on its shunt's pad, the sense pair pre-routed from the pads' inner
edges; the damping leg at FB1's +3V3A end; the lane capacitors at the MCU's ADC pins; the USB pair to
`nets.USB_PAIR`.

## How to add a board

The board is already in `sheets/__init__.py` PROJECTS (title and module name), `build.py` BOARD_ERC_WAIVERS (an empty
list) and the board list above; a board agent only adds its own files:

1. **`sheets/<module>.py`** (the module name in PROJECTS; the motherboard: any number of `sheets/mb_*.py`, each
   with a `PAGE`). It defines `build(d)` and `POWER_NETS` (and `INTERSHEET`, `SYMBOLS`, `footprints()`,
   `SINGLE_PIN_NETS`, `REV`, `DATE` if needed; see the `sheets/__init__.py` docstring). Draw with the schgen API:
   `d.sheet(name, file, title)`, `d.group(title, note, anchor=...)`, `d.add(ref, lib_id, value, footprint,
   pins={pin: net}, fields={"MPN", "Manufacturer", "LCSC"}, near="U10.16")`, and the helpers of `sheets/parts.py`
   (`res`, `cap`, `nfet`, `led_red`, `testpoints`, `mounting_hole`, `fiducials`, `power_flags`).
   **A coupon** starts its `build(d)` with `coupon_common.slot_sheet(d, unused=(...), rails=(...))` and sets
   `POWER_NETS, INTERSHEET = cc.POWER_NETS, cc.INTERSHEET`. On the coupon the slot nets are slot-local:
   `+5V`, `+3V3`, `GND`, `AN0`-`AN3`, `INJ`, `SYNC`, `SCK`, `MISO`, `MOSI`, `CS0_N`, `CS1_N`, `SCL`, `SDA`,
   `IRQ_N`, `G0`-`G5` (PRESENT_N is strapped to GND by the slot sheet). Pass every signal the coupon does not use in
   `unused` (its header pin is left unconnected), and `rails=("+3V3",)` for a coupon without a 5 V load. The slot
   sheet owns refs 1-9 (J1, U1, C1-C3, R1, JP1, TP1-TP4, H1, FID1-FID3); start your own at 10.
2. **`boards/<module>.py`**, the layout module. Required: `LAYERS`, `RULES` (dict track, clearance, via, via_drill,
   edge), `outline()` (board-mm polygon), `fixed(comps)` (`{ref: (x, y, rot, "F"|"B")}` in board mm),
   `build(bb, comps)` (rule areas, plane splits, silk and fab text; the driver has already drawn the outline, the
   edge band and the In1 GND plane), `pours(bb)` (zones added after routing). Optional: `THICKNESS`, `STACKUP`,
   `NETCLASSES` (`(name, [net short names], track, clearance, via, drill)`), `keepouts()` (placer:
   `[(side "F"/"B"/"*", predicate(x, y))]`), `PIN_ANCHORS` (`{ref: ("U10" or "U10.16", net, max mm)}`), `REGIONS`
   (`{ref: (x, y, (x0, y0, x1, y1))}`), `post_fixed(bb, comps)` (assertions, instance edits), `preroute(bb)`
   (locked tracks such as a hand-routed pair), `ROUTER_KEEPOUTS` (`[(layer name, polygon)]` for Freerouting and the
   grid router), `GND_PLANE` (default True on 4 layers), `GND_VIA`, `STITCH_PITCH`, `PROTECTED_NETS` (locked
   pre-routes the dangling-copper clean-up must never touch), `PREROUTED_NETS` (nets `preroute()` joins in full:
   left out of Freerouting's job), `FANOUT_SKIP` (`("U10.2", ...)`: GND pads `preroute()` has already tied to the
   plane, which get no fan-out via), `OPTIMIZER_PASSES` (Freerouting's optimizer, default 20; 0 if its session file
   comes back with connections missing), `HIDE_REFS`, `PART_SIDES` (default top only), `ROUTE`,
   `CENTRE`, `FAB_NOTES` (ORDER-NOTES lines), `RENDER` (`(zoom, (w, h))`).
   **A coupon** re-uses `boards/coupon_common.py`: `SIZE = cc.STANDARD` (or `cc.WIDE`), `outline()` returns
   `cc.outline(SIZE)`, `fixed()` starts from `cc.fixed(comps, SIZE)` (J1, H1, FIDs, wire pads), `keepouts()`
   returns `cc.keepouts(SIZE)` (plus its own), `build()` calls `cc.build(bb, SIZE, title=...)`, `post_fixed()` calls
   `cc.check_mating()`, `pours()` calls `cc.pours(bb, SIZE)`, and it takes `LAYERS`, `THICKNESS`, `STACKUP`,
   `RULES`, `NETCLASSES`, `GND_VIA` and `FAB_NOTES` from `cc`. `boards/test_coupon.py` is the worked example.
3. **`mpn/<board>.csv`**: one row per LCSC code (LCSC, Manufacturer, MPN, DigiKey, Mouser, Note). release.py refuses
   a BOM line without a row.
4. Run build.py (look at every `render/sheet-N.png`), layout.py `--route` (look at the layers:
   `kicad-cli pcb export pdf --layers F.Cu,Edge.Cuts ...`), release.py `--refit-jlc`. A jlcplace red row is fixed at
   its cause (footprint, rotation, polarity from the datasheet), never with `--force`; a yellow row whose datasheet
   you read is recorded with `jlcplace confirm BOARD --ref R --cpl CPL --gerbers gerbers.zip --db
   keyboard/hardware/design/jlcplace-db --by "<role>" --source manual --note "<datasheet, section>"`.
5. Every part not fixed by SPEC is a **candidate**: say so in the sheet module's docstring, with its datasheet, its
   pinout check and its JLC stock and price on the day.

## The coupon geometry (`boards/coupon_common.py`)

Board mm, origin at the coupon's lower-left corner, +y up, top view; the slot edge is y = 0. The same for every
size, so a standard coupon fits a wide slot.

| What | Where |
|---|---|
| Standard / wide outline | 58.0 x 60.0 / 80.0 x 60.0 mm, corners r 1.0 |
| Header J1 (bottom side, `PinHeader_2x20_P2.54mm_Vertical`, rot 270 flipped) | pin 2k-1 at (4.87 + 2.54 (k-1), 5.27), pin 2k at (4.87 + 2.54 (k-1), 2.73): centred on x = 29.0; the odd row (lanes, SPI, G-lines) inside |
| Motherboard socket (top side, `PinSocket_2x20_P2.54mm_Vertical`, rot 90) | footprint origin at the slot's (4.87, 5.27), every pin under the coupon's pin of the same number (`cc.socket_placement()`) |
| Header body | x 3.60-54.40, y 1.50-6.50 (50.8 x 5.0); pin tails stand about 1.4 mm out of the top: no top-side part at y < 7.4 over it |
| M3 support post H1 | (4.0, 56.0), Ø3.2 unplated; no copper within r 3.0, no part within r 3.5 (the nylon spacer and the screw head) |
| Fiducials | (2.0, 9.5), (W - 2.0, 9.5), (W - 2.0, 57.5) |
| Wire pads TP1-TP4 | (11, 56.5), (15, 56.5), (19, 56.5), (23, 56.5): +3V3, +5V, GND, GND |
| Height | motherboard top to coupon underside 8.5 (socket) + 2.54 (header plastic) = 11.04 mm |

Stack: JLC04161H-7628, 4 layers, 1.6 mm (L1 parts, L2 solid GND, L3 +3V3 pour and signals, L4 signals); the
dielectric figures are JLC's as remembered, **unverified**, and nothing depends on them. `cc.build()` puts a no-track
rule area on In1 (vias and the plane allowed), so the plane under the lanes stays whole. Rules: 0.20 / 0.15 mm
default, net classes +5V 0.80 mm and +3V3 0.30 mm at the default 0.15 mm clearance (`cc.NETCLASSES`), vias
0.60 / 0.30 mm, 0.30 mm to the edge. A class width reaches only the tracks `tools/finish_route.py` lays: Freerouting
2.1.0 ignores class rules (below), and DRC does not flag a track narrower than its class. Pre-route any path whose
current matters (`preroute()`, locked) and name its nets in `PREROUTED_NETS`, as `boards/test_coupon.py` does.

## Known limitations

* The caliper's `layout.py --rework` (keep the routing of unchanged nets) is not ported: a keyboard board is
  regenerated and routed whole. Freerouting is not deterministic, so two routes of one board differ; the gates are
  what must hold.
* `Device:LED`'s emission arrows reach past its K pin, so the wiring check counts every wire into K as crossing
  the body; `sheets/parts.py` draws LEDs with `Device:LED_Small`.
* The 2 x 20 header is not keyed: a coupon turned 180 degrees plugs in (ORDER-NOTES warns; a key in the reserved
  pin 39 is an open item for the owner).
* Whether JLC fits a through-hole header whose body sits on the bottom is not confirmed: ORDER-NOTES gives the
  hand-solder alternative.
* Until 2026-11-27 no net class reached a routed board: `layout.write_project` left the project's `net_settings` at
  KiCad's template schema version 0, which KiCad 10 discards on the next load, so every net routed at the Default
  width (the first test coupon had its rails at 0.20 mm). It now writes version 5 and complete class entries (a
  partial class is composed with Default into a name such as `Rail,Default`, which finish_route could not look up);
  check a board's classes with `pcbnew.LoadBoard(pcb).FindNet(name).GetNetClassName()`.
* **Freerouting 2.1.0 ignores net class rules.** On the test coupon's DSN it laid +3V3 (class width 0.40 mm) and the
  load strings (0.80 mm) at the default 0.20 mm, and every net at 0.30 mm when only the DSN's default rule was raised
  (tested 2026-11-27). A class clearance above the default is then broken by Freerouting and reported by DRC. Keep
  class clearances at the default, and pre-route what must be wide (`PREROUTED_NETS` takes those nets out of
  Freerouting's job, as GND is; their locked copper stays as keep-outs).
