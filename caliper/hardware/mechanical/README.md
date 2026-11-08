# caliper/hardware/mechanical

Parametric build123d (OpenCascade) model, calculations, clash check and part files for the
PrettyCool Caliper rev A (printed slider) and rev B (machined slider). Design notes, the gap
procedure, print settings and the hardware BOM: [`docs/mechanical.md`](../../docs/mechanical.md).

Everything runs in WSL with the dial-me-spinner venv (build123d 0.13, matplotlib):

```
bash caliper/hardware/mechanical/run_all.sh        # tests, models, STL/STEP, drawings, clash, calcs, renders (~2 min)
```

| Path | What |
|---|---|
| `params.py` | Every dimension, with its source. `DEV-n` = deviation from SPEC, `TVP` = to verify on prototype. `python3 params.py` prints the derived stack. |
| `models.py` | The parts as exact solids, the part registry (material, process, print pose) and `assembly(R)` at reading R |
| `export.py` | `stl/*.stl` (binary, print pose, on the bed) and `step/*.step` (assembly pose) per part, plus `step/caliper_assembly.step` (25 named, coloured solids at R = 0) |
| `drawgen.py` | Rev B: `step/{slider_body_b,beam_pockets}.step` and `drawings/*.{svg,dxf,pdf}` (A3, tolerances and process notes) |
| `board_envelope.py` | The slider-board envelope (board + tall parts). Uses `board_parts.json` when it exists, else the SPEC 2.1 placeholder; also checks board-level rules the housing depends on |
| `extract_board_parts.py` | Ready for the layout: reads `../kicad/slider/*.kicad_pcb` (KiCad 9 `pcbnew`) and writes `board_parts.json` (Fab outline x datasheet height, board coordinates) |
| `clash_check.py` | Exact B-rep intersections: board envelope vs housing, slider vs beam / fixed jaw / tape / scale / stop at R = 0, 75, 151, slider-internal pairs, and the two sensor gaps -> `clash_report.txt` |
| `calcs.py` | Jaw deflection, gib preloads, sliding force, thermal error, gap stack-ups, AS5311 gap budget -> `calcs_output.txt` |
| `fea_jaw.py` | FEA of the moving jaw with the `print-stress` skill's solver (runs on the Windows Python: `py fea_jaw.py`) -> `fea_jaw_output.txt` |
| `render.py` | `renders/*.png` (matplotlib, flat-shaded B-rep tessellation; exact sections) |
| `tests/test_mechanical.py` | Invariants: gaps, band layout, envelope, valid solids, wall minimums, no slider/beam interference, extrusion direction |

Status: **designed, not built or tested.** The board envelope is a placeholder until the slider
layout exists; rerun `extract_board_parts.py` and `clash_check.py` when it does.
