# Hardware generator toolchain

The KiCad project in `hardware/kicad/` is **generated** from Python, so the
circuit is reviewable as code and can be regenerated after every change.
Open the generated project in KiCad 9 to inspect it, hand-tune the
layout, or continue the design by hand.

| Module | What it does |
|---|---|
| `sexpr.py` | Minimal S-expression reader/writer for KiCad files |
| `symlib.py` | Loads KiCad library symbols (flattening `extends`) and exposes pin geometry |
| `symgen.py` | Builds simple box symbols for parts missing from the KiCad libraries |
| `schgen.py` | Writes hierarchical `.kicad_sch` sheets. Every pin gets a short wire stub ending in a net label, global label or power symbol, and parts are auto-placed in titled groups |
| `pcbgen.py` | Builds a `.kicad_pcb` from the KiCad netlist through the `pcbnew` API: footprints linked to symbols, outline, zones, keepouts, fills, and Specctra DSN/SES I/O for Freerouting |
| `fab.py` | Gerbers, drill files, and the JLCPCB BOM |
| `jlc_cpl.py` | JLCPCB CPL: per-LCSC-part rotation/origin corrections fitted to the EasyEDA footprints, and a simulation of JLC's placement of every row that stops the release if a pad lands off copper (`tests/test_jlc_cpl.py`) |

## Requirements

* KiCad 9 (`kicad-cli` and the `pcbnew` Python module), with the stock symbol and footprint libraries
* Java 21 + [Freerouting](https://github.com/freerouting/freerouting) 2.1.x (optional, for autorouting)
* Python 3.10+

## Flow

```
design/*.py  ──schgen──▶  kicad/*.kicad_sch  ──kicad-cli──▶  netlist
                                                           │
                       placement.py ──pcbgen──▶  kicad/*.kicad_pcb ──DSN──▶ Freerouting ──SES──▶ routed board
                                                                                                │
                                                                         kicad-cli ERC/DRC ◀────┘──▶ fab outputs
```

ERC and DRC run through `kicad-cli` on every build, and their reports are
written next to the outputs.
