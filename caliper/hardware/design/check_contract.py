#!/usr/bin/env python3
"""Check the generated slider netlist against the capture contract (nets.py).

usage: python3 caliper/hardware/design/check_contract.py [path/to/prettycool-caliper-slider.net]

Asserts that every nets.MCU_PINS entry matches the net on the ESP32-S3-MINI-1 pin of that name in the netlist
(None = the pin is unconnected), that no ESP32 pin is connected without being listed, and that every
nets.POWER_NETS / SLIDER_INTERSHEET net exists in the netlist. Exit code 1 on any mismatch.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, HERE)

import sexpr  # noqa: E402

import nets  # noqa: E402

DEFAULT_NET = os.path.join(HERE, "..", "kicad", "slider", "prettycool-caliper-slider.net")
MCU_VALUE_PREFIX = "ESP32-S3-MINI-1"
# The KiCad symbol names pads 23/24 after their USB function; nets.MCU_PINS uses the GPIO names.
PIN_ALIAS = {"USB_D-": "IO19", "USB_D+": "IO20"}


def _find(node, key):
    return [c for c in node[1:] if isinstance(c, list) and c and c[0] == key]


def _val(node, key):
    f = _find(node, key)
    return str(f[0][1]) if f else None


def load(path):
    with open(path, encoding="utf-8") as f:
        tree = sexpr.parse(f.read())
    comps = {}
    for c in _find(_find(tree, "components")[0], "comp"):
        comps[_val(c, "ref")] = _val(c, "value")
    pins = {}   # (ref, pinfunction) -> set(net names)
    all_nets = set()
    for n in _find(_find(tree, "nets")[0], "net"):
        name = _val(n, "name")
        short = name.rsplit("/", 1)[-1] if not name.startswith("unconnected-") else None
        if short:
            all_nets.add(short)
        for node in _find(n, "node"):
            key = (_val(node, "ref"), _val(node, "pinfunction") or _val(node, "pin"))
            pins.setdefault(key, set()).add(short)
    return comps, pins, all_nets


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_NET
    comps, pins, all_nets = load(path)
    mcus = [r for r, v in comps.items() if v and v.startswith(MCU_VALUE_PREFIX)]
    errs = []
    if len(mcus) != 1:
        print(f"expected one {MCU_VALUE_PREFIX}* part, found {mcus}")
        return 1
    u = mcus[0]
    seen = {}
    for (ref, func), netset in pins.items():
        if ref != u:
            continue
        name = PIN_ALIAS.get(func, func)
        seen.setdefault(name, set()).update(netset)
    for name, want in nets.MCU_PINS.items():
        got = seen.get(name)
        if got is None:
            errs.append(f"{u} pin {name}: not in the netlist")
            continue
        exp = {want}
        if got != exp:
            errs.append(f"{u} pin {name}: netlist {sorted(map(str, got))}, contract {want!r}")
    for name, got in seen.items():
        if name not in nets.MCU_PINS and got != {None}:
            errs.append(f"{u} pin {name}: connected to {sorted(map(str, got))} but not in nets.MCU_PINS")
    for net in list(nets.POWER_NETS) + list(nets.SLIDER_INTERSHEET):
        if net not in all_nets:
            errs.append(f"contract net {net} missing from the netlist")
    for e in errs:
        print("CONTRACT:", e)
    n = len(nets.MCU_PINS)
    print(f"{os.path.basename(path)}: {u} checked against {n} nets.MCU_PINS entries -> "
          + ("OK" if not errs else f"{len(errs)} mismatch(es)"))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
