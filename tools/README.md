# Hardware generator toolchain

The KiCad projects (`<project>/hardware/kicad/`) are **generated** from Python, so the
circuit is reviewable as code and can be regenerated after every change.
Open a generated project in KiCad 10 to inspect it, but do not save the generated files from the GUI and do not
hand-edit them: change the Python and rebuild.

| Module | What it does |
|---|---|
| `sexpr.py` | Minimal S-expression reader/writer for KiCad files |
| `symlib.py` | Loads KiCad library symbols (flattening `extends`) and exposes pin geometry |
| `symgen.py` | Builds simple box symbols for parts missing from the KiCad libraries |
| `schgen.py` | The schematic API (`Design` / `sheet` / `group` / `add`) and the writer of the hierarchical `.kicad_sch` sheets. `Design.check()` verifies the **drawing** against the wiring rule below |
| `schplace.py` | The placer and router behind `schgen`: clusters, anchor ICs, satellite parts placed next to the pin they serve, and an orthogonal grid maze router that draws every wire |
| `netlist_diff.py` | Proves two KiCad netlists are electrically identical (same nets, same `(ref, pin)` members, same component fields). It is the gate for any generator change. `--pin-rename REF:OLD=NEW` maps a pin a library update renumbered (reported as a NOTE); a Datasheet of `~` (KiCad 9) equals an empty one (KiCad 10) |
| `pcbgen.py` | Builds a `.kicad_pcb` from the KiCad netlist through the `pcbnew` API: footprints linked to symbols, outline, zones, keepouts, fills, and Specctra DSN/SES I/O for Freerouting |
| `fab.py` | Gerbers, drill files, and the JLCPCB BOM (the CPL comes from jlcplace) |
| `jlcplace_gate.py` | The release gate around [jlcplace](https://github.com/tyevco/jlcplace): `jlcplace cpl` writes the JLCPCB CPL, `jlcplace check` simulates JLC's placement of every row with JLC's own EasyEDA footprints over the Gerbers, and the release refuses on any red row. Also turns the yellow rows and the preview checklist into ORDER-NOTES lines. Replaces the former `jlc_cpl.py` (see below) |

## Wiring rule

**This rule is non-negotiable.** Schematics are drawn the way a person draws them: connected pins are joined by
**wires**, so a reader traces a connection by eye instead of hunting for a matching label elsewhere on the page.

| | Rule | How the toolchain meets it | Enforced by `Design.check()` |
|---|---|---|---|
| R1 | A **local net** (all pins on one sheet, not a power net) is connected by drawn wires (orthogonal segments, junction dots), never by labels. A local label may only be an extra name tag on an already-wired net | Groups that share a local net are merged into one cluster and every connection is routed. Each local net carries one local label on its wire, which keeps the net names | **yes**: error `R1 sheet S: local net N is not wired: pins [..] are joined only through labels`. No waiver exists |
| R2 | **Power nets** (`nets.POWER_NETS`) may use power symbols, but a decoupling or bulk cap that serves an IC pin sits next to that pin and is **wired** to it. The power symbol hangs off that wire | Caps whose pins are both on power nets are assigned to the IC's supply pin (`near="U60.9"` overrides the choice) and placed on that pin's wire | yes: every power pin must reach a power symbol of its net |
| R3 | A net that **crosses sheets** gets a global label. Within each sheet, every pin of that net in a group/cluster is wired to **one** label | One global label per net per cluster, placed at the end of the pin's wire. All of the cluster's pins on the net are routed to it | **yes**: error `R3 sheet S: intersheet net N has k global labels in the cluster ..` or `.. wired node .. has 0 global labels` |
| R4 | Passives that serve one pin (pull-ups/downs, series resistors, divider legs, inductors, crystals, CC resistors, ESD) are placed next to that pin | Each anchor pin gets a "spine": shunts hang off it, series parts continue it, a part bridging two nets (feedback R/C, a buck-boost inductor) goes between them. A 1–2 pin part whose only signal net reaches one IC moves into that IC's cluster | by placement (reviewed on the renders) |
| R5 | The build fails on R1–R3 | `build.py` prints every `CHECK:` error and exits non-zero | `tools/tests/test_wiring_rule.py` |
| R6 | Readability: no wire across a symbol body, no wire overlapping a wire of another net, no overlapping text, a junction dot on every T | The router never enters bodies, text boxes or foreign pins. It crosses foreign wires only straight at right angles, never at their corners or ends. Wires are split at every T and dots are added where 3+ wire ends or pins meet. An up and a down shunt never share a point (no dot joins four wires), and a power symbol on a sideways pin sits on a short stub, clear of the pin | yes for wires across bodies, overlapping wires, wire ends on another wire's middle, and missing or extra dots. Text overlap is checked on the placer's text-size estimate and reported as a `READABILITY:` warning |

The check reads the drawing itself: it builds the wire connectivity from the emitted wires, pins and power
symbols, and it ignores labels. It then compares that against the netlist the sheet modules describe. A
drawing that a label-only generator would produce fails it, and so does any wire that shorts two nets.

There is **no label fallback**. When the router cannot draw a connection, `check()` reports
`sheet S: cannot wire N: pins ..`. The fix is a hint in the sheet module (see below) or a placer change, never a
label.

### Placer hints (the only thing a sheet module may add for layout)

Hints change where parts go on the drawing. They never change connectivity.

* `d.group(title, note, anchor="U10")` — the cluster's anchor part. The default is the multi-pin part with the
  most connected pins.
* `d.add(..., near="U60.9")` (also via `parts.cap()` / `parts.res()`) — the IC and pin a decoupling cap serves.
* `rot=` on a part with only power pins (flags, test points) is still honoured.

`Design.force_labels(*nets)` exists only so the tests can produce a label-only drawing. The check rejects it.

### Changing the generator: the equivalence gate

Any change to `schgen.py` / `schplace.py` must leave the netlists electrically identical:

```sh
cp <project>/hardware/kicad/<board>/*.net /tmp/before/                   # before the change
python3 <project>/hardware/design/build.py --render                      # after the change
python3 tools/netlist_diff.py --strict-fields /tmp/before/<p>.net <project>/hardware/kicad/<board>/<p>.net
python3 -m pytest tools/tests -q                                         # the wiring-rule tests
```

Then **look at the rendered PNGs** (`render/sheet-N.png`) and fix what does not read like a hand-drawn
schematic.

## KiCad 10

The toolchain targets **KiCad 10.0.8** (since 2026-11-08; it was written against 9.0.9). The writers emit KiCad 10
files: schematics `(version 20260306)`, symbol libraries `(version 20251024)`, generator version `10.0`, a hidden
property carrying `(hide yes)` itself, `(body_style 1)` / `(in_pos_files yes)` on every symbol instance, an empty
datasheet as `""` (KiCad 9 wrote `"~"`), no file-level `(embedded_fonts no)`. A `kicad-cli sch upgrade` of a generated
sheet changes only token order and formatting (checked on every sheet when the format moved), with one known
exception: on a multi-unit symbol (caliper U40, TLV9062) KiCad adds `(pin ... (uuid ...))` entries for the other
units' pins, which the writer does not emit. Wire UUIDs are numbered per sheet (a net drawn in two clusters of one
sheet used to give two wires the same UUID, which KiCad renumbers on load). Boards and footprints are written by
`pcbnew` itself (`(version 20260206)`).

What changed between KiCad 9 and 10 for this toolchain:

* pcbnew API: `PCB_IO_MGR.PluginFind` → `FindPlugin`; `FOOTPRINT.HasFieldByName` / `GetFieldByName` →
  `HasField` / `GetField` (returns `None` for a missing field); `ZONE.Get/SetDoNotAllowCopperPour` →
  `Get/SetDoNotAllowZoneFills`; `BOARD.GetBoardPolygonOutlines(outline)` needs the `aInferOutlineIfNecessary` flag
  (`True` keeps 9's behaviour).
* Netlist export: one token per line (format `E`), `pinfunction` is `<pin name>_<pin number>` (`"IO4_8"`; 9 wrote
  `"IO4"`), an empty datasheet is `""`, and each net's `(class ...)` is the net class the project's
  `netclass_patterns` assign (9 wrote `"Default"` for every net). Nothing in the toolchain reads the netlist's
  class, and `netlist_diff.py` ignores it; a build into an empty `--out` directory (no project patterns yet) still
  says `"Default"`.
* Schematic parity also compares custom symbol fields (`footprint_symbol_field_mismatch`): `pcbgen` (and caliper
  `release.py`'s `sync_fields`) copy every symbol field onto the footprint, hidden.
* Board file (`(version 20260206)`): no net table; pads, tracks and zones name their net as `(net "NAME")` (9:
  `(net N "NAME")` / `(net N)` plus a table), so a script that reads a `.kicad_pcb` as text must not look nets up by
  number (the toolchain goes through `pcbnew`). `(setup)` writes tenting as `(tenting (front yes) (back yes))` and
  adds `covering` / `plugging` / `capping` / `filling` (all `no`); the HPGL plot parameters are gone.
* pcbnew's `GetStart()` / `GetEnd()` return references to the item's own point (seen on 10.0.8; not checked on 9): copy them
  (`pcbnew.VECTOR2I(t.GetEnd())`) before a `SetStart()` / `SetEnd()` on the same item. `finish_route.anchor_end`
  did not, so every track the grid router joined part-way along lost its far part (a zero-length tail, then
  pruned as dangling), locked pre-routes included (fixed 2026-11-09, `tests/test_finish_route.py`).
* DRC: zero-length track segments next to another net are a `tracks_crossing` error; new rule keys in the project
  (`footprint_symbol_field_mismatch`, `missing_tuning_profile`, `track_not_centered_on_via`,
  `track_on_post_machined_layer`, `tuning_profile_track_geometries`); reports list the ignored checks.
* Libraries (10.0.8): `Connector:USB_C_Receptacle_USB2.0_16P` and the `USB_C_Receptacle_HRO_TYPE-C-31-M-12`
  footprint call the shield `SH` (9: `S1`), and that footprint's signal pads are rounded rectangles (9: rectangles);
  `TPS22917DBV` moved its pins; `Fiducial_1mm_Mask2mm` changed. A footprint already on a board keeps its 9.0 copy
  (`lib_footprint_mismatch`, a warning) until someone updates it from the library on purpose.
* Project file: the net classes and design rules live in the `.kicad_pro`. pcbnew's `SaveBoard` writes the project of a
  board it *loaded*, not of a `BOARD()` built in memory, and a process that built one in memory then attaches a default
  project to boards it loads later (0.5 mm minimum via, no net classes). So a generator writes its net classes into
  the `.kicad_pro` itself (caliper `layout.write_project_netclasses`), `finish_route.drc_uuids` runs DRC with the board's
  own `.kicad_pro`, and caliper's `layout.py --rework` loads the old board only in a child process.
* Jumper pad groups (KiCad 9+, `(jumper_pad_groups ("1" "6") ...)` in a footprint): pads joined inside the part, which
  connectivity, DRC and the routers then treat as connected. pcbnew's Python API can read but not set them, so caliper's
  `layout.set_jumper_pads` writes them into the board text (the USBLC6's I/O pins).
* The user library tables live in `~/.config/kicad/10.0/` (`cp /usr/share/kicad/template/{sym,fp}-lib-table`); the
  stock libraries are `${KICAD10_SYMBOL_DIR}` / `${KICAD10_FOOTPRINT_DIR}` (`/usr/share/kicad/...`).

## Requirements

* KiCad 10.0.8 (`kicad-cli` and the `pcbnew` Python module), with the stock symbol and footprint libraries
* poppler-utils (`pdftoppm`) for `--render`
* Java 21 + [Freerouting](https://github.com/freerouting/freerouting) 2.1.x (optional, for autorouting)
* Python 3.10+ (pytest for the tests)
* [jlcplace](https://github.com/tyevco/jlcplace) >= 0.2.1 in the same venv (the release gate; `pip install -e ~/jlcplace`)

## Flow

```
design/sheets/*.py ──schgen + schplace──▶ kicad/*.kicad_sch ──kicad-cli──▶ ERC, netlist, PDF/PNG
                         │                                          │
                         └── Design.check(): wiring rule R1-R6      │
                                                                    ▼
                        layout.py ──pcbgen──▶ kicad/*.kicad_pcb ──DSN──▶ Freerouting ──SES──▶ routed board
                                                                                                │
                                                     release.py: DRC + schematic parity ◀───────┘──▶ fab outputs
                                                                 │
                                         gerbers.zip + BOM ──jlcplace cpl──▶ CPL ──jlcplace check──▶ gate
```

ERC and DRC run through `kicad-cli` on every build, and their reports are
written next to the outputs.

## JLC placement gate (jlcplace)

**Required for every board's release.** A fab package does not count as done until
[jlcplace](https://github.com/tyevco/jlcplace) (>= 0.2.1, [docs](https://tyevco.github.io/jlcplace/)) has checked its
CPL: red rows block. `release.py` runs it through `jlcplace_gate.py`, after the DRC/parity gate and after writing
`gerbers.zip` and the BOM:

```sh
jlcplace cpl   BOARD --db DB --bom BOM --gerbers gerbers.zip -o CPL          # rows from the Gerbers' (0, 0); refuses on red
jlcplace check BOARD CPL --db DB --bom BOM --gerbers gerbers.zip     --report fab/<board>/jlcplace-report.html --checklist fab/<board>/jlcplace-checklist.md
```

* Any red row, or a red run finding (an origin mismatch between the CPL and the Gerbers, Gerbers that are not this
  board's), refuses the package; `--force` writes a REVIEW-ONLY one. A board without parts is checked with an empty
  CPL (nothing on it may need placing, and its Gerbers must match the board).
* A second `jlcplace check` without `--db` cross-checks the stored corrections against the EasyEDA records: a row the
  records call red is red for the gate unless a human decision in the DB (manual, preview- or board-verified) accepts
  it. jlcplace 0.2.1 alone lets a stored *auto* correction vouch for a row whose pins land on other nets.
* The yellow rows and the preview checklist go into `ORDER-NOTES.md`; `jlcplace-checklist.md` is the list to work
  through in JLC's placement preview.
* `DB` is the project's committed correction database (caliper: `caliper/hardware/design/jlcplace-db/`): derived
  numbers only (rot, dx, dy, verdicts, verifications). `release.py --refit-jlc` runs `jlcplace fetch` (network,
  rate-limited) and `jlcplace fit --db` after a part is added or changed. Record preview and datasheet decisions with
  `jlcplace confirm ... --db DB` and commit them.
* `jlcplace check` and `cpl` read the EasyEDA record cache (`~/.cache/jlcplace`) and download nothing.
* `jlcplace-report.html` (and `--overlay` images) draw EasyEDA pad outlines from the JLCEDA/EasyEDA Official Library:
  for local review only. They are git-ignored; never commit or publish them.
* Install: `pip install -e ~/jlcplace` into the venv that runs `release.py` (WSL: `~/.venvs/dial-me-spinner`).
  `jlcplace_gate.py` finds the executable next to that Python, else on `PATH`, or takes `$JLCPLACE`.

The former `jlc_cpl.py` (a pad-number fit and an "every pad on copper" simulation, with its EasyEDA-derived table
`jlc_offsets.json`) is retired: jlcplace wrote the same rows (to 0.5 µm, the same angles) on the caliper slider and
also checks nets, pin names, polarity, the Gerbers' origin, the BOM and the bottom-side reading.
