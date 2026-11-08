#!/usr/bin/env python3
"""Export every part as STL (print pose) and STEP (assembly pose), plus the assembly STEP.

    python3 export.py                 # stl/*.stl, step/*.step, step/caliper_assembly.step
    python3 export.py --only slider_body

STL: binary, in the print / machining pose from models.PARTS[...].orient, dropped on
z = 0 -- drag straight onto the Bambu Studio plate.  The steel and brass parts get
an STL too, but only as a viewing mesh: order them from step/ and drawings/.

STEP: exact B-rep in assembly coordinates (so the parts open already placed), with
the assembly at reading R = 0 as one STEP with a named solid per part.
"""
import argparse
import os
import sys

from build123d import Color, Compound, export_step, export_stl

import models as M

HERE = os.path.dirname(os.path.abspath(__file__))

COLOURS = {"steel": (0.62, 0.64, 0.67), "jaw": (0.25, 0.25, 0.28), "body": (0.16, 0.38, 0.62),
           "shell": (0.20, 0.45, 0.72), "cover": (0.14, 0.30, 0.50), "cap": (0.92, 0.55, 0.15),
           "brass": (0.80, 0.65, 0.25), "rubber": (0.10, 0.10, 0.10), "pcb": (0.10, 0.45, 0.20),
           "parts": (0.35, 0.35, 0.38), "glass": (0.05, 0.05, 0.08), "battery": (0.70, 0.70, 0.75),
           "tape": (0.35, 0.20, 0.15)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", action="append")
    ap.add_argument("--no-assembly", action="store_true")
    a = ap.parse_args(argv)
    os.makedirs(os.path.join(HERE, "stl"), exist_ok=True)
    os.makedirs(os.path.join(HERE, "step"), exist_ok=True)
    for name in a.only or list(M.PARTS):
        s = M.build(name)
        stl = os.path.join(HERE, "stl", f"{name}.stl")
        export_stl(M.print_pose(name, s), stl, tolerance=0.01, angular_tolerance=0.1)
        step = os.path.join(HERE, "step", f"{name}.step")
        export_step(s, step)
        print(f"{name:<15} {os.path.getsize(stl) / 1024:7.0f} kB stl   {os.path.getsize(step) / 1024:7.0f} kB step")
    if not a.no_assembly and not a.only:
        kids = []
        for n, s, c in M.assembly(0.0, with_hardware=True):
            s.label = n
            s.color = Color(*COLOURS.get(c, (0.5, 0.5, 0.5)))
            kids.append(s)
        asm = Compound(children=kids, label="prettycool_caliper_revA_R0")
        path = os.path.join(HERE, "step", "caliper_assembly.step")
        export_step(asm, path)
        print(f"assembly: {len(kids)} solids, {os.path.getsize(path) / 1024:.0f} kB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
