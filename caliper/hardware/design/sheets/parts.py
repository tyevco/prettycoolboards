"""Shared footprints and BOM fields for the jellybean parts (one place to fix an LCSC code)."""

R0402 = "Resistor_SMD:R_0402_1005Metric"
R0603 = "Resistor_SMD:R_0603_1608Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
SOT23 = "Package_TO_SOT_SMD:SOT-23"
TP = "TestPoint:TestPoint_Pad_D1.0mm"

SAMSUNG = "Samsung Electro-Mechanics"
UNIROYAL = "UNI-ROYAL"

# value -> (MPN, Manufacturer, LCSC)
RES = {
    "0R": ("0402WGF0000TCE", UNIROYAL, "C17168"),
    "100": ("0402WGF1000TCE", UNIROYAL, "C25076"),
    "390": ("0402WGF3900TCE", UNIROYAL, "C25109"),
    "1k": ("0402WGF1001TCE", UNIROYAL, "C11702"),
    "2.2k": ("0402WGF2201TCE", UNIROYAL, "C25879"),
    "3.9k": ("0402WGF3901TCE", UNIROYAL, "C51721"),
    "4.7k": ("0402WGF4701TCE", UNIROYAL, "C25900"),
    "5.1k": ("0402WGF5101TCE", UNIROYAL, "C25905"),
    "10k": ("0402WGF1002TCE", UNIROYAL, "C25744"),
    "91k": ("0402WGF9102TCE", UNIROYAL, "C4147"),
    "100k": ("0402WGF1003TCE", UNIROYAL, "C25741"),
    "511k": ("0402WGF5113TCE", UNIROYAL, "C64042"),
    "1M": ("0402WGF1004TCE", UNIROYAL, "C26083"),
    "10M": ("0402WGF1005TCE", UNIROYAL, "C26082"),
}
CAP = {
    "10p C0G": ("0402CG100J500NT", "FH (Guangdong Fenghua)", "C1545", C0402),
    "100p C0G": ("0402CG101J500NT", "FH (Guangdong Fenghua)", "C1546", C0402),
    "1n": ("0402B102K500NT", "FH (Guangdong Fenghua)", "C1523", C0402),
    "100n": ("CL05B104KO5NNNC", SAMSUNG, "C1525", C0402),
    "1u": ("CL05A105KA5NQNC", SAMSUNG, "C52923", C0402),
    "4.7u": ("CL10A475KO8NNNC", SAMSUNG, "C19666", C0603),
    "10u/6.3V": ("CL05A106MQ5NUNC", SAMSUNG, "C15525", C0402),    # 0402 X5R, 0.5 mm tall (bottom side)
    "10u": ("CL10A106KP8NNNC", SAMSUNG, "C19702", C0603),
    "22u": ("CL10A226MQ8NRNC", SAMSUNG, "C59461", C0603),
    "10u/25V": ("CL10A106MA8NRNC", SAMSUNG, "C96446", C0603),
    "2.2u/25V": ("CC0805KKX7R8BB225", "YAGEO", "C277470", C0805),
}


def res(d, ref, value, a, b, fp=R0402, **kw):
    mpn, mfr, lcsc = RES[value]
    return d.add(ref, "Device:R", value, fp, pins={"1": a, "2": b},
                 fields={"MPN": mpn, "Manufacturer": mfr, "LCSC": lcsc}, **kw)


def cap(d, ref, value, a, b, **kw):
    mpn, mfr, lcsc, fp = CAP[value]
    return d.add(ref, "Device:C", value, fp, pins={"1": a, "2": b},
                 fields={"MPN": mpn, "Manufacturer": mfr, "LCSC": lcsc}, **kw)


def testpoints(d, start, nets_):
    for i, net in enumerate(nets_, start=start):
        d.add(f"TP{i}", "Connector:TestPoint", net, TP, pins={"1": net}, in_bom=False)
