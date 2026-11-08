"""Generate simple box symbols for parts missing from the KiCad libraries."""

from __future__ import annotations

from sexpr import Q, dumps

PITCH = 2.54
PIN_LEN = 2.54


def _font():
    return ["effects", ["font", ["size", 1.27, 1.27]]]


def _hidden():
    return ["effects", ["font", ["size", 1.27, 1.27]], ["hide", "yes"]]


def box_symbol(name, pins, ref="U", footprint="", datasheet="", description="", keywords="", min_width=12.7):
    """pins: list of (number, name, etype, side) with side in L/R/T/B.

    Pins sharing the same name AND side on one connection point are stacked
    (e.g. multiple GND pads): give the extras etype 'passive' and they are hidden.
    """
    sides = {s: [p for p in pins if p[3] == s] for s in "LRTB"}

    def uniq(lst):
        seen, out = set(), []
        for p in lst:
            if p[1] in seen:
                continue
            seen.add(p[1])
            out.append(p)
        return out

    rows = max(len(uniq(sides["L"])), len(uniq(sides["R"])), 1)
    cols = max(len(uniq(sides["T"])), len(uniq(sides["B"])), 1)
    longest = max([len(p[1]) for p in pins] + [4])
    width = max(min_width, (cols + 1) * PITCH, round((longest * 1.27 * 2 + 5.08) / PITCH) * PITCH)
    width = round(width / (2 * PITCH)) * 2 * PITCH
    height = round(((rows + 1) * PITCH) / (2 * PITCH) + 0.49) * 2 * PITCH
    hw, hh = width / 2, height / 2

    body = [
        "rectangle", ["start", -hw, hh], ["end", hw, -hh],
        ["stroke", ["width", 0.254], ["type", "default"]], ["fill", ["type", "background"]],
    ]
    pin_items = []

    def place(side):
        lst = sides[side]
        names = []
        for p in lst:
            if p[1] not in names:
                names.append(p[1])
        n = len(names)
        for i, nm in enumerate(names):
            if side in "LR":
                y = round((n - 1) / 2 * PITCH - i * PITCH, 4)
                x = -hw - PIN_LEN if side == "L" else hw + PIN_LEN
                ang = 0 if side == "L" else 180
            else:
                x = round(-(n - 1) / 2 * PITCH + i * PITCH, 4)
                y = hh + PIN_LEN if side == "T" else -hh - PIN_LEN
                ang = 270 if side == "T" else 90
            same = [p for p in lst if p[1] == nm]
            for k, p in enumerate(same):
                item = ["pin", p[2] if k == 0 else "passive", "line", ["at", x, y, ang], ["length", PIN_LEN]]
                if k > 0:
                    item.append(["hide", "yes"])
                item += [["name", Q(p[1]), _font()], ["number", Q(str(p[0])), _font()]]
                pin_items.append(item)

    for s in "LRTB":
        place(s)

    sym = [
        "symbol", Q(name), ["pin_names", ["offset", 1.016]],
        ["exclude_from_sim", "no"], ["in_bom", "yes"], ["on_board", "yes"],
        ["property", Q("Reference"), Q(ref), ["at", -hw, hh + 1.27, 0], ["effects", ["font", ["size", 1.27, 1.27]], ["justify", "left", "bottom"]]],
        ["property", Q("Value"), Q(name), ["at", -hw, -hh - 1.27, 0], ["effects", ["font", ["size", 1.27, 1.27]], ["justify", "left", "top"]]],
        ["property", Q("Footprint"), Q(footprint), ["at", 0, 0, 0], _hidden()],
        ["property", Q("Datasheet"), Q(datasheet or "~"), ["at", 0, 0, 0], _hidden()],
        ["property", Q("Description"), Q(description), ["at", 0, 0, 0], _hidden()],
        ["property", Q("ki_keywords"), Q(keywords), ["at", 0, 0, 0], _hidden()],
        ["symbol", Q(f"{name}_0_1"), body],
        ["symbol", Q(f"{name}_1_1")] + pin_items,
        ["embedded_fonts", "no"],
    ]
    return sym


def write_library(path, symbols):
    lib = ["kicad_symbol_lib", ["version", "20241209"], ["generator", Q("dial_me_spinner_symgen")],
           ["generator_version", Q("9.0")]] + symbols
    with open(path, "w", encoding="utf-8") as f:
        f.write(dumps(lib) + "\n")
