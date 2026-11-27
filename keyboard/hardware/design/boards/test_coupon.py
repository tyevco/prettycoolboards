"""Test coupon layout: standard coupon, 58 x 60 mm, 4 layers (boards/coupon_common.py has the shared geometry).

Floor plan (board mm, top view, the slot edge at y = 0):

* J1 on the bottom along the slot edge (coupon_common); the lane ladder R30-R34 right above the lane pins (AN0-AN3,
  x 17.6-25.2), one 1.00 k 0.1 % resistor between each pair of taps.
* The loads on the left, next to the rail pins (+5V x 4.9-7.4, +3V3 x 12.5): the +5V loads first (G3's three
  parallel 2512s stacked, G2's series row), the +3V3 loads above them (G1's stack, G0's row), each MOSFET at the end
  of its string with its drain toward it. The 11 x 2512 spread up to 1.4 W (G3 limited at the TPS2553's typical trip)
  over about 20 cm^2 of the left half (estimate).
* The logic on the right, next to the SPI / I2C / G-line pins (x 32.8-50.6): U1 (EEPROM) over SCL/SDA, U11 and U10
  over the SPI pins, the IRQ_N transistors over IRQ_N, the status LED near the top-right corner where it shows.
* The wire pads TP1-TP4 and the probe pads TP10-TP21 along the top edge, labelled on the silk.
"""

from boards import coupon_common as cc
from boards.geom import P

SIZE = cc.STANDARD
LAYERS, THICKNESS = cc.LAYERS, cc.THICKNESS
STACKUP = cc.STACKUP
RULES = cc.RULES
# the load strings carry up to 0.66 A (G1 unlimited) and 1.5 A (G3 unlimited, S5 only, which it must not be used on)
NETCLASSES = cc.NETCLASSES + [("Load", [f"LOAD{n}_{s}" for n in range(4) for s in "ABD"], 0.80, 0.20, 0.80, 0.40)]
GND_VIA = cc.GND_VIA
STITCH_PITCH = 3.0
ROUTE = True
CENTRE = (29.0, 30.0)
HIDE_REFS = ("H", "FID", "TP")              # the pads carry net labels on the silk instead

FAB_NOTES = [
    "**Test coupon (SPEC §10 step 7):** the loads on G0-G3 deliberately exceed the coupon rules (250 mA on +3V3, "
    "500 mA on +5V) to exercise the slot switches; **G3 (3.33 Ohm on +5V) is for S1-S4 only**: on S5 the 2 A "
    "breaker would let it draw 1.5 A, 2.5 W per 1 W resistor (sheets/test_coupon.py).",
    "**JP1 (WP)** is an open solder jumper: leave it open to write the descriptor EEPROM, then bridge it with solder "
    "to write-protect it.",
] + cc.FAB_NOTES

PROBE_PADS = ["AN0", "AN1", "AN2", "AN3", "SYNC", "INJ", "IRQ_N", "SCK", "MISO", "MOSI", "CS0_N", "CS1_N"]
PROBE_Y, PROBE_X0, PROBE_DX = 57.0, 28.0, 2.2

# x, y, KiCad orientation, side. SOT-23 at 180: drain (pin 3) toward -x, gate and source toward +x.
_FIXED = {
    # +5V current-limit load G3: three 10R in parallel, stacked; Q13 to the right
    "R22": (8.0, 13.0, 0.0), "R23": (8.0, 17.0, 0.0), "R24": (8.0, 21.0, 0.0), "Q13": (14.6, 17.0, 180.0),
    # +5V calibration load G2: three 10R in series, a row
    "R19": (6.0, 26.0, 0.0), "R20": (14.2, 26.0, 0.0), "R21": (22.4, 26.0, 0.0), "Q12": (28.6, 26.0, 180.0),
    # +3V3 current-limit load G1: two 10R in parallel, stacked
    "R17": (8.0, 32.0, 0.0), "R18": (8.0, 36.0, 0.0), "Q11": (14.6, 34.0, 180.0),
    # +3V3 calibration load G0: three 10R in series, a row
    "R14": (6.0, 42.0, 0.0), "R15": (14.2, 42.0, 0.0), "R16": (22.4, 42.0, 0.0), "Q10": (28.6, 42.0, 180.0),
    # lane ladder: pin 1 (the higher tap) toward +x, between the lane pins
    "R30": (16.3, 10.5, 180.0), "R31": (19.3, 10.5, 180.0), "R32": (22.3, 10.5, 180.0), "R33": (25.3, 10.5, 180.0),
    "R34": (28.3, 10.5, 180.0),
    # logic
    "U1": (41.0, 13.5, 0.0), "U11": (35.5, 19.0, 0.0), "U10": (45.0, 25.0, 0.0),
    "Q14": (49.0, 34.0, 180.0), "Q15": (43.0, 34.0, 180.0),
    "Q16": (47.0, 45.0, 180.0), "D10": (51.5, 49.0, 0.0),
}

# parts placed next to a pin: ref -> ("IC" or "IC.PAD", net, max distance mm)
PIN_ANCHORS = {
    "C1": ("J1.7", "+3V3", 6.0), "C2": ("J1.1", "+5V", 6.0),
    "C3": ("U1.8", "+3V3", 2.5), "R1": ("U1.7", "EE_WC", 3.0), "JP1": ("U1.7", "EE_WC", 5.0),
    "C10": ("U10.16", "+3V3", 2.5), "C11": ("U11.5", "+3V3", 2.5),
    "R10": ("Q10.1", "G0", 3.0), "R11": ("Q11.1", "G1", 3.0), "R12": ("Q12.1", "G2", 3.0), "R13": ("Q13.1", "G3", 3.0),
    "R25": ("Q14.3", "IRQ_N", 3.5), "R26": ("Q14.1", "G5", 3.0), "R27": ("Q15.1", "INJ", 3.0),
    "R29": ("Q16.1", "G4", 3.0), "R28": ("D10.2", "LED_A", 3.0),
}


def outline():
    return cc.outline(SIZE)


def fixed(comps):
    out = cc.fixed(comps, SIZE)
    out.update({r: (x, y, rot, "F") for r, (x, y, rot) in _FIXED.items() if r in comps})
    for i, net in enumerate(PROBE_PADS):
        out[f"TP{10 + i}"] = (PROBE_X0 + PROBE_DX * i, PROBE_Y, 0.0, "F")
    return out


def keepouts():
    return cc.keepouts(SIZE)


def build(bb, comps):
    import pcbnew
    cc.build(bb, SIZE, title="PrettyCool Keyboard rA TEST COUPON", ref_text="test coupon rA: loads, lanes, loopback")
    for i, net in enumerate(PROBE_PADS):
        dy = 1.7 if i % 2 == 0 else 2.9                       # two rows: the labels are wider than the pitch
        bb.text(pcbnew.F_SilkS, net.replace("_N", "#"), *P(PROBE_X0 + PROBE_DX * i, PROBE_Y - dy), 0.8)
    for (x, y), net in zip(cc.WIRE_PAD_XY, ("+3V3", "+5V", "GND", "GND")):
        bb.text(pcbnew.F_SilkS, net, *P(x, y - 2.4), 0.8)
    for ref, label in (("Q10", "G0 110mA"), ("Q11", "G1 LIM"), ("Q12", "G2 167mA"), ("Q13", "G3 LIM S1-S4")):
        x, y, _ = _FIXED[ref]
        bb.text(pcbnew.F_Fab, label, *P(x, y + 2.6), 0.8)


def post_fixed(bb, comps):
    """J1's pads on their slot positions (and the motherboard socket solved to the same positions)."""
    from boards.geom import bxy
    cc.check_mating()
    j1 = bb.footprints["J1"]
    assert j1.IsFlipped(), "J1 must be on the bottom"
    for p in j1.Pads():
        x, y = bxy(p)
        ex, ey = cc.pin_xy(int(p.GetNumber()))
        assert abs(x - ex) < 1e-3 and abs(y - ey) < 1e-3, f"J1 pad {p.GetNumber()} at {(x, y)}, want {(ex, ey)}"


def pours(bb):
    cc.pours(bb, SIZE)
