# prettycoolboards

Open hardware boards designed as code. Schematics and PCBs are generated from Python into KiCad 10 by the shared
toolchain in `tools/` (see `tools/README.md`), gated by ERC, DRC and schematic parity. The mechanics are
build123d, and the docs are a VitePress site built from the repo root. One folder per board: `caliper/` holds
`hardware/`, `firmware/` (ESP-IDF) and `docs/`, and its companion web app lives in `public/caliper/app/`.

The caliper's architecture of record is `caliper/hardware/design/SPEC.md` plus `nets.py`. Read them before
changing the hardware.

## Toolchain commands

The hardware toolchain runs in **WSL** (Ubuntu-24.04), never on native Windows:

```sh
wsl -d Ubuntu-24.04 -- bash -lc 'cd /mnt/c/source/tyevco/prettycoolboards && <cmd>'
PY=$HOME/.venvs/dial-me-spinner/bin/python          # has pcbnew, numpy, scipy, matplotlib, pytest, build123d
$PY caliper/hardware/design/build.py --render       # schematics, wiring check, ERC, netlist, PDF + PNG per sheet
$PY caliper/hardware/design/build.py --board slider --only power --out /tmp/x --no-erc   # scratch build
$PY caliper/hardware/design/check_contract.py       # ESP32 pins in the netlist == nets.MCU_PINS
$PY caliper/hardware/design/layout.py [--route]     # PCB placement / routing / DRC (after build.py)
$PY caliper/hardware/design/release.py              # fab outputs; stops on DRC or schematic-parity errors
$PY -m pytest tools/tests -q                        # toolchain tests incl. the wiring rule
$PY tools/netlist_diff.py --strict-fields OLD.net NEW.net   # equivalence gate for any generator change
```

* KiCad **10.0.8** is the target, in WSL (the gates) and on native Windows (the GUI) alike; the boards moved from
  9.0.9 on 2026-11-08 (`caliper/docs/electronics.md` §7.12). A non-login shell does not set `FREEROUTING_JAR`, so
  export `FREEROUTING_JAR=/opt/freerouting/freerouting.jar` yourself.
* Open the generated projects in the KiCad GUI to look at them, but **do not save generated files from the GUI**:
  regenerate them with `build.py` / `layout.py` / `release.py`.
* Docs: `npm run docs:build` on **native Windows**.

## Hard rule: schematics are drawn with wires

Connected pins are joined by **wires** that a reader can follow by eye. The full rule (R1–R6) is in
`tools/README.md` under "Wiring rule". In short:

* A local net is wired, never connected only by labels. One local label may sit on the wire as a name tag.
* A decoupling cap is wired to the pin it serves. Power symbols hang off that wire.
* An intersheet net has **one** global label per cluster, wired to all of the cluster's pins on that net.
* Passives sit next to the pin they serve.
* Wires never cross a symbol body or overlap another net, text never overlaps, and every T has a junction dot.

`Design.check()` enforces it on the drawing, and `build.py` exits non-zero with the sheet, net and pins.
**There is no waiver and no label fallback.** If a connection cannot be drawn, fix the placer or add a placer
hint (`group(anchor=...)`, `add(near=...)`). Never fix it by changing connectivity or adding a label.

After any change to the schematic generator, prove that the netlists are unchanged with `tools/netlist_diff.py`,
then look at the rendered PNGs.

## Conventions

* **Do not hand-edit generated files**: `*/hardware/kicad/**` (`.kicad_sch`, `.kicad_pro`, `.net`, `lib/`,
  `render/`, `.kicad_pcb`), `*/hardware/fab/**`, and the firmware's generated pin header. Change the Python
  (sheet modules, `nets.py`, `layout.py`) and rebuild.
* Commit generated outputs together with the source change that produced them.
* Work goes straight to **`main`** and is pushed to `origin/main`. There are no feature branches or PRs. Push
  only after the gates pass: the wiring check, ERC (only the listed waivers), netlist parity, pytest, and the
  docs build.
* Docs pages must be honest about status: designed, not built or measured, until it has been.
* Line endings are LF (`.gitattributes`). The toolchain runs in WSL.
