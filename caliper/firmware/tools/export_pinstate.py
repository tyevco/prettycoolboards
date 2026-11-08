#!/usr/bin/env python3
"""Export the pin plan (tools/pin_plan.py) as a hwtools pinstate.json (hwtools schema/README.md section 3).

    python tools/export_pinstate.py -o pinstate.json [--ref U10] [--modes RUN,SLEEP,SHIP,RESET]

pullaudit / boardcheck then compute the per-mode leakage with the firmware's pin states instead of
"unknown" (see docs/firmware.md "Pin plan and sleep leakage"):

    python -m pullaudit run --netir slider.netir.json --rails rails.yaml --pins pinstate.json --pads pads -o out/

Every state is `source: "assumed: ..."`: design intent from the plan (what the firmware applies), not a
pinsnap capture or a bench measurement. Pins are keyed by the KiCad symbol pin name of the
ESP32-S3-MINI-1 (nets.MCU_PINS keys: IO0..IO48, TXD0 = GPIO43, RXD0 = GPIO44), except IO19 / IO20,
which the symbol names USB_D- / USB_D+: those are keyed by pad number (23 / 24, sheets/mcu.py _PIN_ALIAS).

Mapping (plan -> pinstate): in -> in; out -> out + level; od -> out + od; hiz -> hiz; off -> hiz (the
pad is unpowered: pullaudit takes the supply-off state from rails.yaml anyway); periph -> its `io`
(in / out + idle level / od / analog). hold -> latched. Internal pulls carry the ESP32-S3 RPU / RPD
band [30k, 60k] (45 k typ, DS v2.2 Table 5-4; the band is hwtools' pads/ESP32-S3.yaml judgement);
the USB D+ pull-up is the PHY's 1.5 k (USB 2.0 RPU 900-1575 ohm, used as [1200, 1800]).
"""
import argparse
import hashlib
import json
import pathlib
import runpy
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pin_plan  # noqa: E402

PAD_ALIAS = {"IO19": "23", "IO20": "24"}  # caliper/hardware/design/sheets/mcu.py _PIN_ALIAS
PULL_OHM = [30000, 60000]
USB_PU_OHM = [1200, 1800]


def pin_keys(nets_path):
    """net -> the pinstate key of the ESP32-S3-MINI-1 pin carrying it."""
    mcu = runpy.run_path(str(nets_path))["MCU_PINS"]
    return {net: PAD_ALIAS.get(pin, pin) for pin, net in mcu.items() if net}


def state_json(p, mode):
    st = p["states"][mode]
    d = st["dir"]
    out = {}
    if d == "periph":
        io = st["io"] or "unknown"
        if io == "od":
            out.update(dir="out", od=True, out=st["level"] if st["level"] is not None else None)
        elif io == "out":
            out.update(dir="out", out=st["level"])
        else:
            out.update(dir=io)
    elif d == "od":
        out.update(dir="out", od=True, out=st["level"])
    elif d == "out":
        out.update(dir="out", out=st["level"])
    elif d == "off":
        out.update(dir="hiz")
    else:
        out.update(dir=d)
    out.setdefault("out", None)
    out["pull"] = st["pull"]
    if st["pull"] != "none":
        out["pull_ohm"] = USB_PU_OHM if p["net"] == "USB_DP" else PULL_OHM
    out["latched"] = bool(st["hold"])
    what = {"RESET": "ESP32-S3 DS v2.2 Table 2-1 'After Reset'", "RUN": "pin plan RUN (firmware applies it)",
            "SLEEP": "pin plan SLEEP (applied at deep-sleep entry)", "SHIP": "ESP32-S3 unpowered"}[mode]
    note = "; ".join(x for x in (p["owner"] if d == "periph" else "", st["note"]) if x)
    out["source"] = f"assumed: {what}" + (f"; {note}" if note else "")
    out["net"] = p["net"]  # informational (consumers ignore unknown keys)
    if st["wake"]:
        out["wake"] = "ext1 any-low"
    return out


# Not a GPIO, so not in the plan, but on U10: CHIP_PU has no internal pull (DS v2.2 Table 2-1 p. 16, no
# At-Reset setting; hwtools pads/ESP32-S3.yaml CHIP_PU internal_pull none); R20 10k / C22 1u hold it high.
EXTRA_U10 = {"EN": {"dir": "in", "out": None, "pull": "none", "latched": False,
                    "source": "assumed: CHIP_PU input, no internal pull (DS v2.2 Table 2-1)", "net": "MCU_EN"}}

# --peers: the other chips' pins on the MCU nets, from their datasheets as the firmware configures them
# (design intent, "assumed" like the rest). Without them pullaudit falls back to a generic CMOS guess for
# U2 / U4 / U30 / U60 / U1 and reports UNKNOWN_STATE on nets the plan alone settles. SHIP / RESET: none.
def _p(dir, out=None, note=""):
    return {"dir": dir, "out": out, "pull": "none", "latched": False, "source": f"assumed: {note}"}


def _od(note):
    return {"dir": "out", "od": True, "out": 1, "pull": "none", "latched": False, "source": f"assumed: {note}"}


_I2C_REL = "I2C target, bus idle (released; SDA / SCL are inputs between transactions)"
PEERS = {
    "RUN": {
        "U2": {"SDA": _p("in", note="BQ25180 " + _I2C_REL), "SCL": _p("in", note="BQ25180 " + _I2C_REL),
               "~{INT}": _od("BQ25180 /INT open drain, released (no event pending)")},
        "U4": {"SDA": _p("in", note="MAX17048 " + _I2C_REL), "SCL": _p("in", note="MAX17048 " + _I2C_REL),
               "~{ALRT}": _od("MAX17048 ALRT open drain, released (no alert)")},
        "U60": {"SDA/SDI/SDO": _p("in", note="LIS2DW12 " + _I2C_REL), "SCL/SPC": _p("in", note="LIS2DW12 " + _I2C_REL),
                "INT1": _p("out", 1, "LIS2DW12 INT1 push-pull active low (CTRL3 0x18), idle high"),
                "INT2": _p("out", 1, "LIS2DW12 INT2 push-pull active low, nothing routed: high")},
        "U30": {"A": _p("out", 1, "AS5311 A push-pull (level follows the position)"),
                "B": _p("out", 1, "AS5311 B push-pull (level follows the position)"),
                "Index": _p("out", 0, "AS5311 Index push-pull, low between index pulses"),
                "DO": _p("hiz", note="AS5311 DO tri-state while CSn is high (between SSI frames)"),
                "MagINCn": _od("AS5311 MagINCn open drain, released (field in range)"),
                "MagDECn": _od("AS5311 MagDECn open drain, released (field in range)")},
        "U1": {"I/O1": _p("hiz", note="USBLC6 ESD clamp, no DC path"), "I/O2": _p("hiz", note="USBLC6 ESD clamp")},
    },
    "SLEEP": {
        "U2": {"SDA": _p("in", note="BQ25180 " + _I2C_REL), "SCL": _p("in", note="BQ25180 " + _I2C_REL),
               "~{INT}": _od("BQ25180 /INT open drain, released (no event pending)")},
        "U4": {"SDA": _p("in", note="MAX17048 " + _I2C_REL), "SCL": _p("in", note="MAX17048 " + _I2C_REL),
               "~{ALRT}": _od("MAX17048 ALRT open drain, released (no alert)")},
        "U60": {"SDA/SDI/SDO": _p("in", note="LIS2DW12 " + _I2C_REL), "SCL/SPC": _p("in", note="LIS2DW12 " + _I2C_REL),
                "INT1": _p("out", 1, "LIS2DW12 INT1 push-pull active low, cleared before sleep: high"),
                "INT2": _p("out", 1, "LIS2DW12 INT2 push-pull active low, nothing routed: high")},
        "U1": {"I/O1": _p("hiz", note="USBLC6 ESD clamp, no DC path"), "I/O2": _p("hiz", note="USBLC6 ESD clamp")},
    },
}


def build(nets_path, ref, modes, firmware, peers=True):
    plan = pin_plan.load(nets_path)
    keys = pin_keys(nets_path)
    doc = {
        "pinstate_version": 0,
        "board": "PrettyCool Caliper slider board rev A",
        "firmware": firmware,
        "provenance": "assumed: exported from caliper/firmware/tools/pin_plan.py (design intent, not measured)",
        "modes": {},
    }
    for m in modes:
        u10 = {keys[p["net"]]: state_json(p, m) for p in plan}
        if m != "SHIP":
            u10.update(EXTRA_U10)
        doc["modes"][m] = {ref: u10}
        if peers:
            doc["modes"][m].update({r: dict(pins) for r, pins in PEERS.get(m, {}).items()})
    return doc


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-o", "--out", type=pathlib.Path, required=True)
    ap.add_argument("--nets", type=pathlib.Path, default=pin_plan.DEFAULT_NETS)
    ap.add_argument("--ref", default="U10", help="the ESP32-S3 module's reference (default U10)")
    ap.add_argument("--modes", default="RESET,RUN,SLEEP,SHIP")
    ap.add_argument("--no-peers", action="store_true", help="only U10 (no states for the other chips' pins)")
    ap.add_argument("--check", action="store_true", help="fail if --out differs from a fresh export")
    a = ap.parse_args()
    modes = [m.strip() for m in a.modes.split(",") if m.strip()]
    bad = [m for m in modes if m not in pin_plan.MODES]
    if bad:
        raise SystemExit(f"export_pinstate: unknown mode(s) {bad}; the plan has {list(pin_plan.MODES)}")
    plan_hash = hashlib.sha256(pathlib.Path(pin_plan.__file__).read_bytes()).hexdigest()[:16]
    doc = build(a.nets, a.ref, modes, f"caliper pin_plan.py@{plan_hash}", peers=not a.no_peers)
    text = json.dumps(doc, indent=1, sort_keys=False) + "\n"
    if a.check:
        cur = a.out.read_text(encoding="utf-8") if a.out.exists() else ""
        if cur != text:
            print(f"export_pinstate: {a.out} is stale; run: python tools/export_pinstate.py -o {a.out}",
                  file=sys.stderr)
            return 1
        print("export_pinstate: up to date")
        return 0
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(text, encoding="utf-8", newline="\n")
    n = sum(len(pins) for v in doc["modes"].values() for pins in v.values())
    print(f"export_pinstate: wrote {a.out} ({len(modes)} modes, {n} pin states, all 'assumed')")
    return 0


if __name__ == "__main__":
    sys.exit(main())
