"""The manual steps before and around power-on (SPEC §10 steps 5-8, stage A1), which no firmware can check.

`bench.py checklist` prints them; `--format md --out FILE` writes a copy with blanks to fill in at the bench, to
keep with the run's report. Values marked "record" have no limit in SPEC: write down what you measure, and compare
the boards with each other. Thresholds marked "proposal" are this checklist's, not SPEC's. The figures that come
from nets.py (the key pin, the PGTH divider, the damping leg, the series resistors) are filled in from it.
"""

from __future__ import annotations

import runpy
from dataclasses import dataclass

from . import limits as L

_N = runpy.run_path(str(L.NETS_PATH))
KEY = _N["SLOT_KEY_PIN"]
PGTH_TOP, PGTH_BOT = (round(x / 1000, 1) for x in _N["INPUT_PGTH_DIVIDER"])
_PG = _N["vsys_pg_thresholds"]()["fall"]
DAMP_NET, DAMP_OHM, DAMP_F = _N["VDDA_DAMPING"]
SERIES_OHM = _N["SLOT_SERIES_OHMS"]
SERIES_PINS = [p for p, s, _d, _n in _N["SLOT_PINS"] if s in _N["SLOT_SERIES_SIGNALS"]]


def _k(x):
    return f"{x:g} k"


@dataclass(frozen=True)
class Item:
    id: str
    phase: str
    tool: str
    action: str
    expect: str
    ref: str


RAILS_OHMS = ["VBUS", "VSYS", "+3V3", "+3V3_MCU", "+3V3_USB", "+3V3_SLOT", "+3V3A", "VCAP",
              *[f"+3V3_S{n}" for n in range(1, 6)], *[f"+5V_S{n}" for n in range(1, 6)], "+5V_KVM"]

ITEMS = [
    # --- before any power -------------------------------------------------------------------------------------------
    Item("U1", "unpowered", "eyes, loupe or microscope",
         "Inspect the LQFP100 (0.5 mm pitch), U_CC (X2QFN-12, 0.4 mm pitch) and J1 for bridges and lifted pins; "
         "check pin 1 / polarity of U2 and U5 (TPS259474L), U3, U4, the 13 INA226s, the TCA9535s, the mux, the "
         "TPD4E05U06, the SMF5.0A (band to VBUS) and the LEDs.",
         "no bridge, every polarised part the right way round", "SPEC §2.1, §3.1"),
    Item("U2", "unpowered", "meter, ohms", "Resistance from each rail to GND (black lead on GND): "
         + ", ".join(RAILS_OHMS) + ".",
         "no short: record each value; below about 10 ohm is a short (proposal); compare the boards with each other",
         "SPEC §3.1"),
    Item("U3", "unpowered", "meter, ohms", "CC1 to GND and CC2 to GND at J1 (or the TPs at U_CC).",
         "about 4.1-6.1 kohm each: U_CC's dead-battery Rd (SLLSEQ8D R_CC_DB). About 2.5 kohm means the two 5.1 k "
         "Rd footprints are fitted, which makes a 3.0 A source read as 1.5 A", "SPEC §3.5, §3.8"),
    Item("U4", "unpowered", "eyes",
         "The meter jumpers JP_3V3_S1..S5 are fitted (each slot's +3V3 runs through one); the solder jumpers "
         "JP_INJ1..5 are open.",
         "5 jumpers fitted, 5 solder jumpers open. A missing JP_3V3_Sn shows later as a dead rail",
         "SPEC §3.3, §4.7"),
    Item("U4a", "unpowered", "eyes, a coupon",
         f"The slot key (D2 of 2026-11-27): every slot socket S1..S5 has its hole {KEY} plugged (a header pin cut "
         f"flush and pressed into contact {KEY}, not standing above the socket's top). Then, with nothing powered, "
         "try each A1 coupon turned 180 degrees in each socket, without force.",
         f"5 holes plugged; turned, a coupon's pin {41 - KEY} meets the plug and it does not go in. An unplugged hole "
         "lets a turned coupon in, where it reads present (risks.md EL-2). The powered check is bench.py run "
         "--key-check",
         "SPEC §4.2, §10 step 7; nets.SLOT_KEY_PIN"),
    Item("U4b", "unpowered", "eyes or meter, ohms",
         f"D4 of 2026-11-27: U2's PGTH divider is R35 {_k(PGTH_TOP)} over R36 {_k(PGTH_BOT)} (R36 was 39 k when "
         f"first captured: check its marking or the reel); the +3V3A damping leg R103 {DAMP_OHM:g} ohm and C118 "
         f"{DAMP_F * 1e6:g} uF (25 V, 0805) are fitted at FB1's +3V3A end.",
         f"R36 {_k(PGTH_BOT)}: VSYS_PG then falls at {_PG[0]:.2f}-{_PG[2]:.2f} V (exact parts). No harness check can "
         "see this divider: U2's own UVLO turns it off from J1 before VSYS_IN reaches that threshold",
         "SPEC §3.1, §3.7; nets.INPUT_PGTH_DIVIDER, nets.VDDA_DAMPING"),
    Item("U4c", "unpowered", "meter, ohms (optional)",
         f"D3 of 2026-11-27, on one slot: from socket pin {', '.join(map(str, SERIES_PINS))} (CS0_N, CS1_N, IRQ_N, "
         f"G0-G3; S5 also 37, 38) to the resistor's MCU-side pad.",
         f"{SERIES_OHM} ohm each (1 %); 0 ohm means a bridge, open means a missing part",
         "SPEC §4.3; nets.SLOT_SERIES"),
    Item("C1", "coupons, unpowered", "eyes",
         f"Each A1 coupon (test, Hall): J1 is on the BOTTOM side, has no pin {KEY} (pulled before soldering) and "
         f"its gap sits over the X on the silk.",
         f"no pin {KEY}; a full 40-pin header cannot mate with a plugged socket", "SPEC §4.2; ORDER-NOTES of each"),
    Item("C2", "coupons, unpowered", "eyes, meter",
         "Test coupon: D11 (1N4148W) has its cathode band (pad 1, INJ_AN0) away from the slot edge (D7's INJ path); "
         "JP1 (WP) is OPEN until the descriptor is written (bench.py run --write-descriptor SERIAL), then bridged. "
         "Hall coupon: R26 not fitted, JP1 open.",
         "as the ORDER-NOTES say. A reversed D11 shows as no AN0 lift in bench.py run --inj",
         "test coupon and coupon-hall ORDER-NOTES; sheets/test_coupon.py"),
    Item("U5", "unpowered", "meter, ohms",
         "U_CC's ADDR pull-up (4.7 k to +3V3) and VBUS_DET resistor (887 k to VBUS) are fitted with those values.",
         "4.7 k, 887 k. Without the ADDR pull-up U_CC answers at 0x47, the +3V3_S4 INA226's address", "SPEC §3.8"),
    Item("U6", "unpowered", "eyes", "Every coupon unplugged; no USB host on J1; BOOT0 not held.",
         "nothing in the slots for the first power-up", "SPEC §3.5, §5.2, §10 step 5"),
    Item("U7", "unpowered", "STLINK-V3", "Fit the STLINK-V3 to J_SWD (STDC14; mind the key) and open its virtual "
         "COM port at 115200 8N1. T_VCC (pin 3) is an input of the probe: it does not power the board.",
         "the VCP enumerates on the PC", "SPEC §7.2; UM2448 Table 6; PROTOCOL.md"),
    Item("U8", "unpowered", "-", "ESD: wrist strap on; the bench mat grounded. Scope grounds go to GND only (a scope "
         "ground is earth: clipping it to any other node shorts that node to earth).",
         "-", "general practice"),
    # --- first power ------------------------------------------------------------------------------------------------
    Item("P1", "first power", "bench supply",
         "Set the supply to 5.00 V with a current limit of about 150 mA (proposal: three times SPEC's 45 mA base-load "
         "estimate), output off. Feed J1 through a USB-C power breakout with NO host on the same cable: a supply and "
         "a host on one VBUS fight each other.",
         "5.00 V, 150 mA limit", "SPEC §3.2, §10 step 5"),
    Item("P2", "first power", "bench supply", "Turn the output on and watch the supply's current at once.",
         "tens of mA and steady (SPEC's estimate: about 45 mA). At the limit, or climbing: OFF at once", "SPEC §3.2"),
    Item("P3", "first power", "meter, volts", "At the test points: VBUS, VSYS, +3V3, +3V3_SLOT, +3V3A, VCAP.",
         "VSYS just under VBUS; +3V3 3.25-3.35 V (AP2112K +/-1.5 %, DS39724); +3V3_SLOT and +3V3A about 3.3 V "
         "(LDL1117: accuracy not read); VCAP: record", "SPEC §3.1, §3.7, §7.5"),
    Item("P4", "first power", "finger or IR thermometer", "After a minute: U2, U3, U4, the MCU, U_CC.",
         "nothing warm with no slot powered", "general practice"),
    Item("P5", "first power", "STLINK-V3", "Connect with STM32CubeProgrammer (SWD), read the device ID, flash the "
         "bring-up firmware (the bench-supply build for this phase), reset.",
         "the boot report on the VCP (@tb boot ...)", "SPEC §10 step 6; keyboard/firmware/bringup/README.md"),
    Item("P6", "first power", "tbbench", "Run: bench.py run --power bench --bench-ma 150 --console uart --port <VCP> "
         "--board-serial <S/N>. With no coupon plugged it checks the motherboard only and ends INCOMPLETE. Then power "
         "off, plug the test coupon into S1, raise the supply's limit to 1000 mA and run again with --bench-ma 1000 "
         "(discovery declares 250 mA; the 5 V current-limit test needs 644 mA plus the base load).",
         "the motherboard steps pass; then the slot steps", "this harness"),
    Item("P7", "first power", "tbbench, a clip lead",
         "Stage A1 in SPEC §10's order: the test coupon in every slot first (step 7: --write-descriptor SERIAL once, "
         "--key-check, --inj with a clip lead from the coupon's TP1 (+3V3) to TP15 (INJ) when asked, --climit, "
         "--meter), one slot after another; only then the Hall coupon (step 8: --coupon N=hall). Unplug and plug "
         "coupons only with every slot off (LED_Sn dark).",
         "each slot's steps pass with the test coupon before a sensor coupon goes in", "SPEC §1 (D1), §10"),
    Item("P8", "first power (optional)", "tbbench, scope",
         "risks.md EL-2's test, once, before the key plugs are fitted (or on one slot with its plug out): bench.py "
         "run --power bench --turned-test N, the test coupon plugged in turned when asked, a scope on the slot's "
         "CS0_N, CS1_N, G0 and G1 at the MCU.",
         "the firmware refuses the slot (desc_bus) and drives none of those lines; tb safe frees I2C4 afterwards",
         "risks.md EL-2; SPEC §4.6"),
    # --- scope work for U_CC (SPEC §10 step 5) ---------------------------------------------------------------------
    Item("S1", "U_CC, per source", "scope, 2-4 channels",
         "From an unpowered board, attach to a Default source, a 1.5 A source, a 3.0 A source and a Type-A port "
         "through a Type-A-to-C cable. Scope CC1, CC2 (TPs at U_CC) and VBUS through the power-up.",
         "Rd unbroken while U_CC's VDD rises (no dip of CC that lets the source drop VBUS); VBUS comes up once and "
         "stays", "SPEC §3.8, §11 #12"),
    Item("S2", "U_CC, per source", "scope", "+3V3's rise time at power-up.", "within 25 ms (TUSB320 VDD ramp)",
         "SPEC §3.8; SLLSEQ8D Pin Functions"),
    Item("S3", "U_CC, per source", "scope or logic analyser",
         "Time from +3V3 up to U_CC's first ACK on I2C1 (SDA/SCL TPs).",
         "100 ms or less (t_I2C_EN); the firmware waits 200 ms", "SPEC §3.8, §8.4; SLLSEQ8D §6.7"),
    Item("S4", "U_CC, per source", "tbbench", "For each source: bench.py run --source default|1.5A|3.0A|typeA ... "
         "(the harness reads tb cc and checks the budget).",
         "the advertisement as declared; Type-A-to-C reads default", "SPEC §3.2, §3.8"),
    Item("S5", "U_CC, per source", "a source that can change its advertisement",
         "While attached, make the source lower its advertisement (for example plug a second load into a shared "
         "charger); watch tb cc and the event log.",
         "record whether U_CC reports it (SPEC's open question) and how long it takes (tSinkAdj is 60 ms)",
         "SPEC §3.8; bringup README findings"),
    # --- later, with instruments the harness cannot read --------------------------------------------------------------
    Item("L1", "slots", "electronic load or the test coupon",
         "Each slot switch's trip point at 3.3 V and 5 V (the test coupon's climit steps do this; an electronic "
         "load ramped slowly cross-checks one slot).",
         "TPS2553 3.3 V 256-335 mA, 5 V 519-644 mA; S5 breaker 2.01-2.46 A (estimates)", "SPEC §3.1"),
    Item("L2", "slots", "meter in JP_3V3_Sn", "The INA226 readings against a meter (bench.py run --meter).",
         "within the INA226's offset and gain error plus the meter's", "SPEC §3.3"),
    Item("L3", "USB", "scope >= 2 GHz with a differential probe, or a compliance fixture",
         "High-speed eye at 480 Mb/s on J1.", "record; no harness check", "SPEC §7.1, §10 step 6"),
    Item("L4", "USB", "Nucleo first", "The 8 kHz HID test is hid8k's, on the Nucleo and then on this board.",
         "keyboard/firmware/hid8k/README.md", "SPEC §10 steps 2 and 6"),
    Item("L5", "slots", "scope, the test coupon in two slots",
         "+3V3A against the model (risks.md EL-5's test): switch a test-coupon load on S4 at 30-300 kHz (a G-line "
         "driven from a generator through a breakout, or the scan engine later), scope +3V3A at VDDA and read the "
         "ladder on another slot in lockstep.",
         "record the peak and its frequency; keyboard/sim bench 4 predicts the damping leg holds it within about "
         "2.7 dB (a model, not a measurement)", "SPEC §3.7, §10 step 7; risks.md EL-5"),
    Item("L6", "slots", "4-wire meter, electronic load",
         "The Kelvin-sensed shunts (D4, risks.md EL-6): tb ina VSYS against a 4-wire meter across the 20 mOhm shunt "
         "at 0.5, 1 and 2 A from an electronic load on a coupon's wire pads (TP2 +5V on the test coupon in S5).",
         "within the INA226's offset and gain error plus the shunt's; record", "SPEC §3.4, §7.5; risks.md EL-6"),
]


def render(fmt="text", phase=None):
    items = [i for i in ITEMS if phase in (None, i.phase)]
    out = []
    if fmt == "md":
        out += ["# Testbed bring-up: the manual checklist", "",
                "Board serial: ________   Date: ________   Operator: ________", "",
                "| # | Phase | Tool | Do | Expect | Measured / done | Source |", "|---|---|---|---|---|---|---|"]
        def cell(v):
            return v.replace("|", "\\|")          # a "|" inside a cell would split the row
        out += [f"| {i.id} | {i.phase} | {cell(i.tool)} | {cell(i.action)} | {cell(i.expect)} | | {cell(i.ref)} |"
                for i in items]
        out += ["", "Generated by keyboard/tools/bench (bench.py checklist). Nothing on this list has been done on a "
                "real board yet: the boards are designed, not built.", ""]
        return "\n".join(out)
    phase_now = None
    for i in items:
        if i.phase != phase_now:
            phase_now = i.phase
            out.append(f"\n== {phase_now.upper()} ==")
        out.append(f"[ ] {i.id}  ({i.tool})  {i.action}")
        out.append(f"        expect: {i.expect}")
        out.append(f"        source: {i.ref}")
    return "\n".join(out).lstrip("\n") + "\n"
