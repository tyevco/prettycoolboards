# caliper/hardware/mechanical

Parametric build123d (OpenCascade) model, calculations, clash check and part files for the
PrettyCool Caliper rev A (printed slider) and rev B (machined slider). Design notes, the gap
procedure, print settings and the hardware BOM: [`docs/mechanical.md`](../../docs/mechanical.md).

Everything runs in WSL with the dial-me-spinner venv (KiCad 10 pcbnew, build123d 0.13, matplotlib);
the FEA runs on the Windows Python with the `print-stress` skill:

```
bash caliper/hardware/mechanical/run_all.sh        # extract board, tests, models, STL/STEP, drawings, clash, calcs, renders (~3 min)
py fea_jaw.py; py fea_inside_jaw.py; py fea_slider.py   # Windows: FEA (inside jaw ~4 min, the others ~10 min), then rerun calcs.py
```

| Path | What |
|---|---|
| `params.py` | Every dimension, with its source. `TVP` = to verify on prototype. `python3 params.py` prints the derived stack. |
| `models.py` | The parts as exact solids, the part registry (material, process, print pose), the body's named cut features (`body_cuts`) and `assembly(R)` at reading R |
| `export.py` | `stl/*.stl` (binary, print pose, on the bed), `stl/slider_body_rf_modifier.stl` (slicer modifier: unfilled PA near the antenna) and `step/*.step` (assembly pose) per part, plus `step/caliper_assembly.step` (40 named, coloured solids at R = 0) |
| `drawgen.py` | Rev B: `step/{slider_body_b,beam_pockets}.step` and `drawings/*.{svg,dxf,pdf}` (A3, tolerances and process notes) |
| `extract_board_parts.py` | Reads `../kicad/slider/*.kicad_pcb` (KiCad 10 `pcbnew`) and writes `board_parts.json`: the Edge.Cuts outline (body + tabs), the holes, one box per part (Fab outline x datasheet height) plus the SMT standoffs, the H1 screw head and the mated JST plug |
| `board_envelope.py` | The slider-board envelope from `board_parts.json` (SPEC 2.1 placeholder without it) and the board rules the housing depends on (height zones, bottom window, antenna keep-out, holes) |
| `clash_check.py` | Exact B-rep intersections: board vs housing, slider vs beam / fixed jaw / tape / scale / stop at R = 0, 75, 151, slider-internal pairs; the sensor gaps; the webs between the body's cut features; metal and carbon-filled (PA-CF jaws) vs antenna (RF; FAIL / RISK) -> `clash_report.txt` |
| `calcs.py` | Jaw deflection, gib preloads, sliding force, back web, thermal error, gap stack-ups, AS5311 gap budget, board under a button press -> `calcs_output.txt` |
| `fea_jaw.py` | FEA of the moving outside jaw (print-stress solver, Windows Python) -> `fea_jaw_output.txt`, `renders/fea_jaw.png` |
| `fea_inside_jaw.py` | FEA of the moving inside jaw: the old 2.4 mm plate vs the stiffened jaw (shoulder block + gusset), rigid root and with the local body, PA-CF with the unfilled-PA zone near the antenna, PETG; plus the fixed inside jaw for the budget (Windows Python) -> `fea_inside_jaw_output.txt` |
| `fea_slider.py` | FEA of the whole body under both gib preloads, and of the board under a button press (with and without the button-band ledge) -> `fea_slider_output.txt`, `renders/fea_body.png` |
| `render.py` | `renders/*.png` (matplotlib, flat-shaded B-rep tessellation; exact sections) |
| `tests/test_mechanical.py` | Invariants: gaps, SPEC/nets contract, envelope, valid solids, walls, clamp stack, RF, print poses, sliding force, no slider/beam interference |

Status: **designed, not built or tested.** The clash check runs against the routed slider board
(`board_parts.json`); re-run `run_all.sh` whenever the layout changes.
