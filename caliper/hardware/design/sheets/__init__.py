"""Schematic sheet modules, grouped per board (KiCad project), in page order.

Each module defines:
    SHEET = (name, filename, title)
    SYMBOLS = [dict(name=..., pins=[(number, name, etype, side), ...], ref="U",
                    footprint="lib:fp", datasheet="url", description="...")]   # optional custom symbols
    def footprints(fpgen, lib_dir): ...                                         # optional custom footprints
    def build(d): ...                                                           # adds the sheet's parts
"""

PROJECTS: dict[str, list[str]] = {
    "slider": ["power", "mcu", "sensor_mag", "sensor_cap", "ui", "imu"],
    "scale": ["scale"],
}
SHEETS = [s for v in PROJECTS.values() for s in v]
