"""Scale board: the passive capacitive reflector scale bonded into the beam. See SPEC.md §2.2.

The board has no electronics. Its reflector pattern (front copper: isolated "T" reflectors at 5.08 mm pitch, each
joined by a 0.3 mm neck to a coupler bar segment) and its solid back-copper ground are drawn by the layout script
as board copper/graphics, not as parts. This sheet only carries what the layout needs as footprints:
two plated M2 holes (back ground plane to the beam / housing) and an edge fiducial at each end.
"""

TITLE = "PrettyCool Caliper capacitive scale"
POWER_NETS = ["GND"]

SHEET = ("scale", "scale.kicad_sch", "Capacitive scale (passive)")


def build(d):
    d.sheet(*SHEET)

    d.group("Mounting (plated M2, back-copper ground)",
            "One hole at each end, clear of the 150 mm measuring range. The pads tie the back ground plane to the\n"
            "beam through the screws, so the scale's reference is the beam potential, as the slider's guard ground is.")
    for i in (1, 2):
        d.add(f"H{i}", "Mechanical:MountingHole_Pad", "M2", "MountingHole:MountingHole_2.2mm_M2_Pad_Via",
              pins={"1": "GND"}, in_bom=False)

    d.group("Fiducials", "One per end (front side), for the reflector-pattern inspection and any later assembly")
    for i in (1, 2):
        d.add(f"FID{i}", "Mechanical:Fiducial", "Fiducial", "Fiducial:Fiducial_1mm_Mask2mm", in_bom=False)

    d.group("Power flag", "GND has no driver on a passive board")
    d.add("#FLG01", "power:PWR_FLAG", "PWR_FLAG", "", pins={"1": "GND"}, in_bom=False, on_board=False, rot=90)
