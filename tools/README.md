# Hardware generator toolchain

The KiCad projects (`<project>/hardware/kicad/`) are **generated** from Python, so the
circuit is reviewable as code and can be regenerated after every change.
Open a generated project in KiCad 9 to inspect it. Do not hand-edit the generated files:
change the Python and rebuild.

| Module | What it does |
|---|---|
| `sexpr.py` | Minimal S-expression reader/writer for KiCad files |
| `symlib.py` | Loads KiCad library symbols (flattening `extends`) and exposes pin geometry |
| `symgen.py` | Builds simple box symbols for parts missing from the KiCad libraries |
| `schgen.py` | The schematic API (`Design` / `sheet` / `group` / `add`) and the writer of the hierarchical `.kicad_sch` sheets. `Design.check()` verifies the **drawing** against the wiring rule below |
| `schplace.py` | The placer and router behind `schgen`: clusters, anchor ICs, satellite parts placed next to the pin they serve, and an orthogonal grid maze router that draws every wire |
| `netlist_diff.py` | Proves two KiCad netlists are electrically identical (same nets, same `(ref, pin)` members, same component fields). It is the gate for any generator change |
| `pcbgen.py` | Builds a `.kicad_pcb` from the KiCad netlist through the `pcbnew` API: footprints linked to symbols, outline, zones, keepouts, fills, and Specctra DSN/SES I/O for Freerouting |
| `fab.py` | Gerbers, drill files, and the JLCPCB BOM |
| `jlc_cpl.py` | JLCPCB CPL: per-LCSC-part rotation/origin corrections fitted to the EasyEDA footprints, and a simulation of JLC's placement of every row that stops the release if a pad lands off copper |

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

## Requirements

* KiCad 9 (`kicad-cli` and the `pcbnew` Python module), with the stock symbol and footprint libraries
* poppler-utils (`pdftoppm`) for `--render`
* Java 21 + [Freerouting](https://github.com/freerouting/freerouting) 2.1.x (optional, for autorouting)
* Python 3.10+ (pytest for the tests)

## Flow

```
design/sheets/*.py ──schgen + schplace──▶ kicad/*.kicad_sch ──kicad-cli──▶ ERC, netlist, PDF/PNG
                         │                                          │
                         └── Design.check(): wiring rule R1-R6      │
                                                                    ▼
                        layout.py ──pcbgen──▶ kicad/*.kicad_pcb ──DSN──▶ Freerouting ──SES──▶ routed board
                                                                                                │
                                                     release.py: DRC + schematic parity ◀───────┘──▶ fab outputs
```

ERC and DRC run through `kicad-cli` on every build, and their reports are
written next to the outputs.
