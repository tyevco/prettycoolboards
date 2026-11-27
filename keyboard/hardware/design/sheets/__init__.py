"""Schematic sheet modules of the PrettyCool Keyboard rev A testbed, one KiCad project per board.

PROJECTS maps a board name (the --board argument of build.py, layout.py and release.py) to its title and its sheet
modules, in page order. A board whose modules do not exist yet is "not captured": build.py skips it when building
every board and refuses it when asked for it by name.

`sheets` is a list of module names under sheets/, or a glob such as "mb_*" (the motherboard: every sheets/mb_*.py,
ordered by the module's PAGE, then its name), so that a board agent adds a sheet module without editing this file.

Each module defines:
    def build(d): ...                      # adds its sheet(s) to the schgen Design (d.sheet / d.group / d.add)
    POWER_NETS = [...]                     # nets drawn with power symbols (build.py takes the union over modules)
    INTERSHEET = [...]                     # optional: nets drawn with global labels even when on one sheet
    SYMBOLS = [dict(name=..., pins=[(number, name, etype, side), ...], ref="U", footprint="lib:fp", ...)]
                                           # optional: generated symbols (symgen), library "keyboard"
    def footprints(fpgen, lib_dir): ...    # optional: generated footprints (fpgen), library "keyboard"
    SINGLE_PIN_NETS = [...]                # optional: nets allowed to have one connection (a test pad, say)
    REV, DATE, PAGE                        # optional: title-block revision and date; page order for globbed sheets

A coupon module calls sheets.coupon_common.slot_sheet(d, ...) first: the slot header, the descriptor EEPROM, the
mounting post and the fiducials every coupon carries (SPEC §2, §4). See keyboard/hardware/design/README.md.
"""

PROJECTS: dict[str, dict] = {
    "motherboard": {"title": "PrettyCool Keyboard rev A testbed motherboard", "sheets": "mb_*"},
    "test-coupon": {"title": "PrettyCool Keyboard rev A test coupon (calibration and loopback)",
                    "sheets": ["test_coupon"]},
    "coupon-hall": {"title": "PrettyCool Keyboard rev A Hall-effect coupon", "sheets": ["coupon_hall"]},
    "coupon-tmr": {"title": "PrettyCool Keyboard rev A TMR coupon", "sheets": ["coupon_tmr"]},
    "coupon-shear": {"title": "PrettyCool Keyboard rev A shear coupon", "sheets": ["coupon_shear"]},
    "coupon-coil": {"title": "PrettyCool Keyboard rev A coil coupon", "sheets": ["coupon_coil"]},
    "coupon-haptics": {"title": "PrettyCool Keyboard rev A haptics coupon", "sheets": ["coupon_haptics"]},
    "latency-rig": {"title": "PrettyCool Keyboard rev A latency rig", "sheets": ["latency_rig"]},
}
