"""Shared part helpers for every keyboard board: jellybean resistors and capacitors (one place to fix an LCSC code),
test points, mounting holes, fiducials, power flags and the common small parts.

Every LCSC code below was looked up in the JLC parts API on 2026-11-27 (stock and qty-1 price in the comment; stock
changes daily). "basic" = a JLC basic part (no extended-part fee); prefer these for passives. A board that needs a
value not listed adds it here, with its own lookup date, and a row in mpn/<board>.csv.
"""

R0402 = "Resistor_SMD:R_0402_1005Metric"
R0603 = "Resistor_SMD:R_0603_1608Metric"
R2512 = "Resistor_SMD:R_2512_6332Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
SOT23 = "Package_TO_SOT_SMD:SOT-23"
SOT23_5 = "Package_TO_SOT_SMD:SOT-23-5"
LED0603 = "LED_SMD:LED_0603_1608Metric"
TP = "TestPoint:TestPoint_Pad_D1.0mm"                         # probe pad, top copper, no part
TP_WIRE = "TestPoint:TestPoint_THTPad_D2.0mm_Drill1.0mm"     # solder a wire or hook a clip: external meter / load
FIDUCIAL = "Fiducial:Fiducial_1mm_Mask2mm"
HOLE_M3 = "MountingHole:MountingHole_3.2mm_M3"               # NPTH, no copper (a nylon spacer: SPEC §9)

UNIROYAL = "UNI-ROYAL"
SAMSUNG = "Samsung Electro-Mechanics"
FH = "FH (Guangdong Fenghua)"

# value -> (MPN, Manufacturer, LCSC, footprint). 0402 thick film is 1 %, 100 ppm/K, 62.5 mW.
RES = {
    "0R": ("0402WGF0000TCE", UNIROYAL, "C17168", R0402),          # basic, 12.35 M, $0.0012
    "22": ("0402WGF220JTCE", UNIROYAL, "C25092", R0402),          # basic, 6.47 M
    "47": ("0402WGF470JTCE", UNIROYAL, "C25118", R0402),          # extended (preferred), 1.24 M
    "100": ("0402WGF1000TCE", UNIROYAL, "C25076", R0402),         # basic, 9.34 M
    "470": ("0402WGF4700TCE", UNIROYAL, "C25117", R0402),         # basic, 2.15 M
    "1k": ("0402WGF1001TCE", UNIROYAL, "C11702", R0402),          # basic, 25.2 M
    "2.2k": ("0402WGF2201TCE", UNIROYAL, "C25879", R0402),        # basic, 4.03 M
    "3.3k": ("0402WGF3301TCE", UNIROYAL, "C25890", R0402),        # basic, 1.33 M
    "4.7k": ("0402WGF4701TCE", UNIROYAL, "C25900", R0402),        # basic, 11.9 M
    "5.1k": ("0402WGF5101TCE", UNIROYAL, "C25905", R0402),        # basic, 5.22 M
    "10k": ("0402WGF1002TCE", UNIROYAL, "C25744", R0402),         # basic, 31.6 M
    "22k": ("0402WGF2202TCE", UNIROYAL, "C25768", R0402),         # basic, 1.33 M
    "47k": ("0402WGF4702TCE", UNIROYAL, "C25792", R0402),         # basic, 4.78 M
    "100k": ("0402WGF1003TCE", UNIROYAL, "C25741", R0402),        # basic, 11.4 M
    "1M": ("0402WGF1004TCE", UNIROYAL, "C26083", R0402),          # basic, 3.11 M
    # precision: 0603 thin film, 0.1 %, 25 ppm/K, 100 mW (extended, 827 k, $0.028)
    "1k 0.1%": ("RT0603BRD071KL", "YAGEO", "C110776", R0603),
    # power: 2512 thick film, 1 %, 1 W, 400 ppm/K (extended, 173 k, $0.032). The 400 ppm/K matters when it runs hot:
    # about 2 % at 50 K of self-heating (estimate). Use it as a current step, not as a current reference.
    "10R 2512": ("25121WF100JT4E", UNIROYAL, "C47019", R2512),
}

# value -> (MPN, Manufacturer, LCSC, footprint)
CAP = {
    "100p C0G": ("0402CG101J500NT", FH, "C1546", C0402),        # basic, 50 V C0G, 2.55 M
    "1n": ("0402B102K500NT", FH, "C1523", C0402),               # basic, 50 V X7R, 3.58 M
    "100n": ("CL05B104KO5NNNC", SAMSUNG, "C1525", C0402),       # basic, 16 V X7R, 29.1 M
    "1u": ("CL05A105KA5NQNC", SAMSUNG, "C52923", C0402),        # basic, 25 V X5R, 11.3 M
    "4.7u": ("CL10A475KO8NNNC", SAMSUNG, "C19666", C0603),      # basic, 16 V X5R, 2.91 M
    "10u": ("CL10A106KP8NNNC", SAMSUNG, "C19702", C0603),       # basic, 10 V X5R, 10.6 M (3.3 V rails)
    "22u": ("CL10A226MQ8NRNC", SAMSUNG, "C59461", C0603),       # basic, 6.3 V X5R, 5.02 M (3.3 V rails only)
    "22u/25V": ("CL21A226MAQNNNE", SAMSUNG, "C45783", C0805),   # basic, 25 V X5R, 4.41 M (5 V rails)
}

# common small actives (JLC basic)
AO3400A = {"MPN": "AO3400A", "Manufacturer": "Alpha & Omega Semiconductor", "LCSC": "C20917"}   # 1.32 M, $0.078
LED_RED = {"MPN": "KT-0603R", "Manufacturer": "Hubei KENTO Elec", "LCSC": "C2286"}            # 8.48 M, $0.008


def _fields(mpn, mfr, lcsc):
    return {"MPN": mpn, "Manufacturer": mfr, "LCSC": lcsc}


def res(d, ref, value, a, b, **kw):
    """A resistor from RES between nets a (pin 1) and b (pin 2)."""
    mpn, mfr, lcsc, fp = RES[value]
    shown = value.split(" ")[0]
    return d.add(ref, "Device:R", shown, fp, pins={"1": a, "2": b}, fields=_fields(mpn, mfr, lcsc), **kw)


def cap(d, ref, value, a, b, **kw):
    """A capacitor from CAP between nets a (pin 1) and b (pin 2). near="U1.8" ties a decoupling cap to its pin."""
    mpn, mfr, lcsc, fp = CAP[value]
    return d.add(ref, "Device:C", value.split("/")[0].split(" ")[0], fp, pins={"1": a, "2": b},
                 fields=_fields(mpn, mfr, lcsc), **kw)


def nfet(d, ref, gate, drain, source="GND", **kw):
    """AO3400A N-MOSFET (SOT-23: 1 G, 2 S, 3 D; VGS(th) 0.65-1.45 V, RDS(on) < 48 mOhm at 2.5 V, AOS datasheet)."""
    return d.add(ref, "Transistor_FET:AO3400A", "AO3400A", SOT23, pins={"G": gate, "D": drain, "S": source},
                 fields=dict(AO3400A), **kw)


def led_red(d, ref, anode, cathode, **kw):
    """KT-0603R red LED (0603). Drawn with Device:LED_Small: Device:LED's emission arrows reach 0.76 mm past its K pin
    tip, so the wiring check (tools/schplace body box) counts every wire into K as crossing the body."""
    return d.add(ref, "Device:LED_Small", "red", LED0603, pins={"A": anode, "K": cathode}, fields=dict(LED_RED), **kw)


def testpoints(d, start, nets_, fp=TP, prefix="TP"):
    """One test pad per net, refs TP<start>... (not in the BOM)."""
    for i, net in enumerate(nets_, start=start):
        d.add(f"{prefix}{i}", "Connector:TestPoint", net, fp, pins={"1": net}, in_bom=False)


def mounting_hole(d, ref, value="M3", fp=HOLE_M3):
    """An unplated mounting hole (no pin, no net, not in the BOM)."""
    return d.add(ref, "Mechanical:MountingHole", value, fp, in_bom=False)


def fiducials(d, refs):
    for ref in refs:
        d.add(ref, "Mechanical:Fiducial", "Fiducial", FIDUCIAL, in_bom=False)


def power_flags(d, nets_, start=1):
    """PWR_FLAG on nets driven from off the board (ERC), schematic-only."""
    for i, net in enumerate(nets_, start=start):
        d.add(f"#FLG{i:02d}", "power:PWR_FLAG", "PWR_FLAG", "", pins={"1": net}, in_bom=False, on_board=False, rot=90)
