"""Slider board: experimental capacitive front-end (8-phase transmitter + charge-amplifier receiver). See SPEC.md §4.2.

TX: CAP_TXn (GPIO) -> R6n 0R jumper (DNP to isolate the experiment) -> R7n 100R series -> electrode phase n.
RX: receive electrode -> R80 0R jumper (DNP-able) -> charge amplifier U40A (TLV9062, 10 MHz GBW, RRIO CMOS) with
10 pF || 10 MOhm feedback, non-inverting input at VREF = +3V3_SNS / 2 (100k/100k + 1 uF, buffered by U40B)
-> 2nd-order RC low-pass (390R/1n + 3.9k/100p, both poles ~408 kHz) -> CAP_RX (GPIO1, ADC1_CH0).

The electrodes are copper on the bottom layer, not parts. They are drawn as one symbol, E40 ("CAP_ELECTRODES",
pins TX0..TX7 + RX), whose footprint holds one seed pad per net: eight 0.30 x 5.00 mm fingers at 0.635 mm pitch
(one 5.08 mm repeat of the transmitter comb) and a 5.08 x 1.20 mm receive strip 3.8 mm below the comb centre
(SPEC §2.1: TX strip y = 12.5...17.5, RX strip y = 10.6...11.8). Layout (layout.py) places E40 on the bottom
at the start of the comb and draws the remaining fingers and the full 40 mm RX strip as copper on the seed
pads' nets (phase n = every 8th finger). That keeps every electrode net a real, ERC-checked net with a pad,
without net ties. E40 is excluded from the BOM and the position files.

TLV9062IDGKR (TI SBOS799, VSSOP-8 "DGK" pinout): 1 OUT1, 2 IN1-, 3 IN1+, 4 V-, 5 IN2+, 6 IN2-, 7 OUT2, 8 V+
(= KiCad Amplifier_Operational:TLV9062 units A/B/C).
"""

from sheets.parts import R0402, cap, res, testpoints

SHEET = ("sensor_cap", "sensor_cap.kicad_sch", "Capacitive front-end (experimental)")

EL_SYM = "CAP_ELECTRODES"
EL_FP_NAME = "Caliper_CapTX_Electrode_Seed_8Phase_P0.635mm"
EL_FP = "caliper:" + EL_FP_NAME
OPA_FP = "Package_SO:VSSOP-8_3x3mm_P0.65mm"
OPA_DS = "https://www.ti.com/lit/ds/symlink/tlv9062.pdf"

SYMBOLS = [
    dict(
        name=EL_SYM,
        ref="E",
        footprint=EL_FP,
        datasheet="~",
        description="Capacitive scale electrodes (bottom copper): 8 transmitter phases + receive strip. "
                    "Seed pads only; layout draws the full comb on these nets. Not a BOM part.",
        keywords="electrode capacitive scale caliper",
        pins=[(i + 1, f"TX{i}", "passive", "L") for i in range(8)] + [(9, "RX", "passive", "R")],
    ),
]


def footprints(fpgen, lib_dir):
    pcbnew = fpgen.pcbnew
    fp = fpgen.Footprint(
        EL_FP_NAME,
        "Capacitive caliper electrode seed: one 5.08 mm repeat of the 8-phase transmitter comb (0.30 x 5.00 mm fingers "
        "at 0.635 mm pitch, pads 1-8 = TX0-TX7) and a 5.08 x 1.20 mm receive strip (pad 9) whose centre is 3.8 mm "
        "below the comb centre. Layout extends both to 40 mm in copper on the same nets. Origin = finger TX0 centre.",
        "capacitive electrode comb caliper",
    )
    pitch = 0.635
    for i in range(8):
        fp.smd(str(i + 1), round(i * pitch, 4), 0.0, 0.30, 5.00, shape="rect", paste=False)
    x_mid = round(3.5 * pitch, 4)
    fp.smd("9", x_mid, 3.8, 5.08, 1.20, shape="rect", paste=False)
    f = fp.fp
    f.SetAttributes(pcbnew.FP_SMD | pcbnew.FP_EXCLUDE_FROM_BOM | pcbnew.FP_EXCLUDE_FROM_POS_FILES)
    fp.fab_rect(-0.3, -2.6, round(7 * pitch + 0.3, 4), 4.5)
    fp.courtyard_rect(-0.5, -2.75, round(7 * pitch + 0.5, 4), 4.65)
    fp.save(lib_dir)


def build(d):
    d.sheet(*SHEET)

    d.group("TX phase isolation jumpers (0R, DNP to disconnect the experiment)",
            "Fit R60-R67 to drive the electrodes; leave them off and the eight GPIOs are free test pads.")
    for i in range(8):
        res(d, f"R6{i}", "0R", f"CAP_TX{i}", f"CAP_TX{i}_J")

    d.group("TX series resistors (100R: edge-rate limit, EMI, GPIO protection)",
            "Next to the comb, on the electrode side of the jumpers. Phase n drives every 8th finger (pitch 0.635 mm).")
    for i in range(8):
        res(d, f"R7{i}", "100", f"CAP_TX{i}_J", f"CAP_EL_TX{i}")

    d.group("Electrodes (bottom copper, E40 = seed pads; not a BOM part)",
            "Comb x = 11...51, y = 12.5...17.5; RX strip y = 10.6...11.8 (SPEC §2.1). Bottom mask open over both.\n"
            "Guard GND around the RX strip and the CAP_EL_RX trace on all layers; nothing else on the bottom in y = 9...19.")
    d.add("E40", "caliper:" + EL_SYM, "CAP_ELECTRODES", EL_FP,
          pins={**{f"TX{i}": f"CAP_EL_TX{i}" for i in range(8)}, "RX": "CAP_EL_RX"}, in_bom=False)

    d.group("RX jumper + charge amplifier (U40A)",
            "Q = C*V: Cf 10p C0G || Rf 10M (HPF corner 1.6 kHz, far below the 25-100 kHz drive). Output centred on VREF.\n"
            "Keep the CAP_RX_IN node tiny, guarded, no mask opening on it except at the electrode.")
    res(d, "R80", "0R", "CAP_EL_RX", "CAP_RX_IN")
    cap(d, "C40", "10p C0G", "CAP_RX_IN", "CAP_AMP_OUT")
    res(d, "R81", "10M", "CAP_RX_IN", "CAP_AMP_OUT")
    opa = {"MPN": "TLV9062IDGKR", "Manufacturer": "Texas Instruments", "LCSC": "C398356"}
    d.add("U40", "Amplifier_Operational:TLV9062", "TLV9062IDGKR", OPA_FP, unit=1, datasheet=OPA_DS,
          pins={"2": "CAP_RX_IN", "3": "CAP_VREF", "1": "CAP_AMP_OUT"}, fields=opa)

    d.group("VREF = +3V3_SNS / 2, buffered (U40B)",
            "100k/100k divider (16.5 uA, only while +3V3_SNS is on) filtered by C41 1u, unity-gain buffer U40B.\n"
            "The buffer output drives only U40A's + input (no capacitive load on the op-amp output).")
    res(d, "R82", "100k", "+3V3_SNS", "CAP_VDIV")
    res(d, "R83", "100k", "CAP_VDIV", "GND")
    cap(d, "C41", "1u", "CAP_VDIV", "GND")
    d.add("U40", "Amplifier_Operational:TLV9062", "TLV9062IDGKR", OPA_FP, unit=2, datasheet=OPA_DS,
          pins={"5": "CAP_VDIV", "6": "CAP_VREF", "7": "CAP_VREF"}, fields=opa)

    d.group("Op-amp supply", "100n at pin 8")
    cap(d, "C42", "100n", "+3V3_SNS", "GND")
    d.add("U40", "Amplifier_Operational:TLV9062", "TLV9062IDGKR", OPA_FP, unit=3, datasheet=OPA_DS,
          pins={"8": "+3V3_SNS", "4": "GND"}, fields=opa)

    d.group("2nd-order RC low-pass (~408 kHz per pole) -> CAP_RX (ADC1_CH0)",
            "390R/1n then 3.9k/100p C0G (second stage 10x the impedance, so it barely loads the first).\n"
            "Anti-alias + kills the op-amp's HF noise; the synchronous demodulation is done in firmware.")
    res(d, "R84", "390", "CAP_AMP_OUT", "CAP_LP1")
    cap(d, "C43", "1n", "CAP_LP1", "GND")
    res(d, "R85", "3.9k", "CAP_LP1", "CAP_RX")
    cap(d, "C44", "100p C0G", "CAP_RX", "GND")

    d.group("Test points", "Charge-amp output and VREF for scope probing")
    testpoints(d, 40, ["CAP_AMP_OUT", "CAP_VREF", "CAP_RX"])
