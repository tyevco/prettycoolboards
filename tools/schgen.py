"""Generate KiCad 9 hierarchical schematics from a Python netlist description.

Every pin is wired with a short stub ending in a net label (local label if the
net lives on one sheet, global label if it spans sheets) or a power symbol for
power nets. Parts are auto-placed in titled groups on each sheet.
"""

from __future__ import annotations

import json
import math
import os
import uuid as _uuid
from dataclasses import dataclass, field

import symlib
import sexpr
from sexpr import Q

GRID = 1.27
STUB = 2.54
FONT = 1.27
CHAR_W = 1.05  # approx advance of a 1.27 mm KiCad font glyph, mm

# Net name -> power symbol lib_id. Nets not listed use a generic power symbol
# whose Value becomes the net name.
POWER_SYMBOLS = {
    "GND": "power:GND",
    "+3V3": "power:+3V3",
    "VBUS": "power:VBUS",
}
GENERIC_POWER = "power:VCC"


def _uid(*parts) -> str:
    return str(_uuid.uuid5(_uuid.NAMESPACE_URL, "dial-me-spinner/" + "/".join(map(str, parts))))


def snap(v: float, g: float = GRID) -> float:
    return round(round(v / g) * g, 4)


@dataclass
class Part:
    ref: str
    lib_id: str
    value: str
    footprint: str = ""
    pins: dict = field(default_factory=dict)   # pin number/name -> net name (None = no-connect)
    fields: dict = field(default_factory=dict)  # extra properties: MPN, LCSC, Manufacturer, ...
    datasheet: str = ""
    description: str = ""
    rot: int | None = None
    unit: int = 1
    dnp: bool = False
    in_bom: bool = True
    on_board: bool = True
    sheet: "Sheet" = None
    group: str = ""


@dataclass
class Group:
    title: str
    parts: list = field(default_factory=list)
    note: str = ""


class Sheet:
    def __init__(self, design: "Design", name: str, filename: str, title: str = ""):
        self.design = design
        self.name = name
        self.filename = filename
        self.title = title or name
        self.groups: list[Group] = []
        self.notes: list[str] = []
        self.uuid = _uid("sheet", name)

    def group(self, title: str, note: str = "") -> Group:
        g = Group(title, [], note)
        self.groups.append(g)
        return g

    def parts(self):
        for g in self.groups:
            yield from g.parts


class Design:
    def __init__(self, project: str, title: str, rev: str, date: str, company: str = ""):
        self.project = project
        self.title = title
        self.rev = rev
        self.date = date
        self.company = company
        self.sheets: list[Sheet] = []
        self.root_notes: list[str] = []
        self.root_uuid = _uid("root")
        self._cur_group: Group | None = None
        self._cur_sheet: Sheet | None = None
        self.net_shapes: dict[str, str] = {}
        self.power_nets: set[str] = set(POWER_SYMBOLS)

    # ---- construction API -------------------------------------------------
    def sheet(self, name: str, filename: str, title: str = "") -> Sheet:
        s = Sheet(self, name, filename, title)
        self.sheets.append(s)
        self._cur_sheet = s
        self._cur_group = None
        return s

    def group(self, title: str, note: str = "") -> Group:
        self._cur_group = self._cur_sheet.group(title, note)
        return self._cur_group

    def add(self, ref, lib_id, value, footprint="", pins=None, **kw) -> Part:
        if self._cur_group is None:
            self.group("")
        p = Part(ref=ref, lib_id=lib_id, value=value, footprint=footprint, pins=dict(pins or {}), **kw)
        p.sheet = self._cur_sheet
        p.group = self._cur_group.title
        self._cur_group.parts.append(p)
        return p

    def power(self, *nets: str) -> None:
        self.power_nets.update(nets)

    # ---- analysis -----------------------------------------------------------
    def all_parts(self):
        for s in self.sheets:
            yield from s.parts()

    def net_sheets(self) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        for p in self.all_parts():
            for net in p.pins.values():
                if net is not None:
                    out.setdefault(net, set()).add(p.sheet.name)
        return out

    def check(self) -> list[str]:
        """Static checks: refs unique, all visible pins assigned, nets with one pin."""
        errs = []
        seen = {}
        for p in self.all_parts():
            key = (p.ref, p.unit)
            if key in seen:
                errs.append(f"duplicate ref {p.ref} unit {p.unit}")
            seen[key] = p
            sym = symlib.get(p.lib_id)
            assigned = set()
            for k in p.pins:
                try:
                    for pin in sym.pin(k):
                        assigned.add(pin.number)
                except KeyError as e:
                    errs.append(str(e) + f" (ref {p.ref})")
            locs = {}
            for pin in sym.pins_for_unit(p.unit):
                locs.setdefault((pin.x, pin.y), []).append(pin)
            for (x, y), group in locs.items():
                if not any(pin.number in assigned for pin in group):
                    errs.append(f"{p.ref}: pin {group[0].number} ({group[0].name}) unassigned")
        count: dict[str, int] = {}
        for p in self.all_parts():
            for net in p.pins.values():
                if net is not None:
                    count[net] = count.get(net, 0) + 1
        for net, n in count.items():
            if n < 2 and net not in self.power_nets:
                errs.append(f"net {net} has only one connection")
        return errs

    # ---- output -------------------------------------------------------------
    def write(self, outdir: str, extra_sym_libs: dict | None = None, extra_fp_libs: dict | None = None):
        os.makedirs(outdir, exist_ok=True)
        net_sheets = self.net_sheets()
        page = 2
        for s in self.sheets:
            sch = _SheetWriter(self, s, net_sheets, page).build()
            with open(os.path.join(outdir, s.filename), "w", encoding="utf-8") as f:
                f.write(sexpr.dumps(sch) + "\n")
            page += 1
        root = self._root()
        with open(os.path.join(outdir, self.project + ".kicad_sch"), "w", encoding="utf-8") as f:
            f.write(sexpr.dumps(root) + "\n")
        self._write_pro(outdir)
        if extra_sym_libs:
            _write_table(os.path.join(outdir, "sym-lib-table"), "sym_lib_table", extra_sym_libs)
        if extra_fp_libs:
            _write_table(os.path.join(outdir, "fp-lib-table"), "fp_lib_table", extra_fp_libs)

    def _title_block(self, title):
        return ["title_block", ["title", Q(title)], ["date", Q(self.date)], ["rev", Q(self.rev)],
                ["company", Q(self.company)]]

    def _root(self):
        items = [
            "kicad_sch", ["version", "20250114"], ["generator", Q("eeschema")], ["generator_version", Q("9.0")],
            ["uuid", Q(self.root_uuid)], ["paper", Q("A3")], self._title_block(self.title), ["lib_symbols"],
        ]
        cols = 3
        w, h = 90.0, 22.86
        for i, s in enumerate(self.sheets):
            x = 25.4 + (i % cols) * (w + 30.48)
            y = 40.64 + (i // cols) * (h + 22.86)
            items.append([
                "sheet", ["at", x, y], ["size", w, h],
                ["exclude_from_sim", "no"], ["in_bom", "yes"], ["on_board", "yes"], ["dnp", "no"],
                ["fields_autoplaced", "yes"],
                ["stroke", ["width", 0.1524], ["type", "solid"]], ["fill", ["color", 0, 0, 0, "0.0000"]],
                ["uuid", Q(s.uuid)],
                ["property", Q("Sheetname"), Q(s.title), ["at", x, round(y - 0.7116, 4), 0],
                 ["effects", ["font", ["size", 2.54, 2.54], ["bold", "yes"]], ["justify", "left", "bottom"]]],
                ["property", Q("Sheetfile"), Q(s.filename), ["at", x, round(y + h + 0.5846, 4), 0],
                 ["effects", ["font", ["size", 1.27, 1.27]], ["justify", "left", "top"]]],
                ["instances", ["project", Q(self.project), ["path", Q("/" + self.root_uuid), ["page", Q(str(i + 2))]]]],
            ])
        y_notes = 40.64 + ((len(self.sheets) + cols - 1) // cols) * (h + 22.86) + 5
        for k, note in enumerate(self.root_notes):
            items.append(_text(note, 25.4, y_notes, _uid("rootnote", k)))
            y_notes += 6 + 2.2 * note.count("\n")
        items.append(["sheet_instances", ["path", Q("/"), ["page", Q("1")]]])
        items.append(["embedded_fonts", "no"])
        return items

    def _write_pro(self, outdir):
        path = os.path.join(outdir, self.project + ".kicad_pro")
        with open("/usr/share/kicad/template/kicad.kicad_pro", encoding="utf-8") as f:
            pro = json.load(f)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                pro = json.load(f)
        pro["meta"]["filename"] = self.project + ".kicad_pro"
        pro["sheets"] = [[self.root_uuid, "Root"]] + [[s.uuid, s.title] for s in self.sheets]
        pro.update(getattr(self, "pro_overrides", {}))
        with open(path, "w", encoding="utf-8") as f:
            json.dump(pro, f, indent=2)
            f.write("\n")


def _write_table(path, head, libs):
    lines = [f"({head}", "  (version 7)"]
    for nick, uri in libs.items():
        lines.append(f'  (lib (name "{nick}")(type "KiCad")(uri "{uri}")(options "")(descr ""))')
    lines.append(")")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _text(s, x, y, uid, size=FONT):
    return ["text", Q(s), ["exclude_from_sim", "no"], ["at", x, y, 0],
            ["effects", ["font", ["size", size, size]], ["justify", "left", "top"]], ["uuid", Q(uid)]]


def _rot(u, v, r):
    c, s = round(math.cos(math.radians(r))), round(math.sin(math.radians(r)))
    return (u * c + v * s, -u * s + v * c)


def _dir_angle(dx, dy):
    """Screen direction vector -> KiCad text angle."""
    if dx > 0.5:
        return 0
    if dx < -0.5:
        return 180
    if dy < -0.5:
        return 90
    return 270


class _SheetWriter:
    def __init__(self, design: Design, sheet: Sheet, net_sheets, page: int):
        self.d = design
        self.s = sheet
        self.net_sheets = net_sheets
        self.page = page
        self.items: list = []
        self.lib_ids: set[str] = set()
        self.pwr_count = 0

    def label_len(self, net: str) -> float:
        return len(net) * CHAR_W + 3.0

    def part_rot(self, p: Part) -> int:
        if p.rot is not None:
            return p.rot
        sym = symlib.get(p.lib_id)
        pins = sym.pins_for_unit(p.unit)
        if len(pins) == 2 and all(pin.angle in (90, 270) for pin in pins):
            return 90  # lay 2-pin vertical passives horizontally
        return 0

    def extents(self, p: Part):
        """Bounding box of the part incl. stubs and labels, relative to its origin (screen coords)."""
        sym = symlib.get(p.lib_id)
        r = self.part_rot(p)
        x0, y0, x1, y1 = sym.bbox(p.unit)
        corners = [_rot(x, -y, r) for x, y in ((x0, y0), (x0, y1), (x1, y0), (x1, y1))]
        xs = [c[0] for c in corners]
        ys = [c[1] for c in corners]
        for pin in sym.pins_for_unit(p.unit):
            net = self.net_for(p, pin)
            px, py = _rot(pin.x, -pin.y, r)
            dx, dy = _rot(-math.cos(math.radians(pin.angle)), math.sin(math.radians(pin.angle)), r)
            ln = STUB + (self.label_len(net) if net else 0)
            if net in self.d.power_nets:
                ln = STUB + (3.3 + len(net) * CHAR_W if abs(dx) > 0.5 else 6.5)
            xs.append(px + dx * ln)
            ys.append(py + dy * ln)
            if net and abs(dx) < 0.5:  # vertical label: text extends sideways a little
                xs += [px - 1.5, px + 1.5]
        if len(sym.pins_for_unit(p.unit)) > 2:
            left, top = min(c[0] for c in corners), min(c[1] for c in corners)
            xs.append(left - max(len(p.value), len(p.ref)) * CHAR_W)
            ys.append(top - 5.0)
        return min(xs), min(ys) - 3.0, max(xs), max(ys) + 3.0

    def net_for(self, p: Part, pin):
        for k, net in p.pins.items():
            if k == pin.number or k == pin.name:
                return net
        # stacked hidden pins share a location with an assigned pin
        sym = symlib.get(p.lib_id)
        for other in sym.pins_for_unit(p.unit):
            if (other.x, other.y) == (pin.x, pin.y) and other is not pin:
                for k, net in p.pins.items():
                    if k == other.number or k == other.name:
                        return net
        return "__UNASSIGNED__"

    def build(self):
        layout = self.layout()
        for p, (ox, oy) in layout:
            self.emit_part(p, ox, oy)
        lib_symbols = ["lib_symbols"] + [symlib.get(l).embedded() for l in sorted(self.lib_ids)]
        head = [
            "kicad_sch", ["version", "20250114"], ["generator", Q("eeschema")], ["generator_version", Q("9.0")],
            ["uuid", Q(self.s.uuid)], ["paper", Q(self.paper)], self.d._title_block(self.s.title), lib_symbols,
        ]
        return head + self.items + [["embedded_fonts", "no"]]

    def layout(self):
        margin_x, margin_y = 15.24, 20.32
        gap = 5.08
        group_gap = 10.16
        max_w = 380.0
        # pick paper by total area
        blocks = []
        for gi, g in enumerate(self.s.groups):
            exts = [self.extents(p) for p in g.parts]
            # flow parts inside the group in rows of limited width
            gw_limit = max(120.0, max((e[2] - e[0]) for e in exts) if exts else 0)
            gw_limit = min(max_w, max(gw_limit, 170.0))
            rows, row, rw = [], [], 0.0
            for p, e in zip(g.parts, exts):
                w = e[2] - e[0]
                if row and rw + w > gw_limit:
                    rows.append(row); row, rw = [], 0.0
                row.append((p, e)); rw += w + gap
            if row:
                rows.append(row)
            gw = max((sum(e[2] - e[0] for _, e in r) + gap * (len(r) - 1)) for r in rows) if rows else 0
            gh = sum(max(e[3] - e[1] for _, e in r) for r in rows) + gap * max(0, len(rows) - 1)
            title_h = 8.0 + (2.2 * (g.note.count("\n") + 1) if g.note else 0)
            gw = max(gw, len(g.title) * 1.75, max((len(l) for l in g.note.split("\n")), default=0) * 1.0)
            blocks.append((g, rows, gw, gh + title_h, title_h))
        total_area = sum((b[2] + group_gap) * (b[3] + group_gap) for b in blocks)
        self.paper, page_w, page_h = ("A3", 420.0, 297.0)
        if total_area > 0.55 * 400 * 260:
            self.paper, page_w, page_h = ("A2", 594.0, 420.0)
        if total_area > 0.55 * 570 * 380:
            self.paper, page_w, page_h = ("A1", 841.0, 594.0)
        usable_w = page_w - 2 * margin_x
        x, y, line_h = margin_x, margin_y, 0.0
        placed = []
        if self.s.notes:
            for k, n in enumerate(self.s.notes):
                self.items.append(_text(n, margin_x, y, _uid(self.s.name, "note", k)))
                y += 4 + 2.2 * (n.count("\n") + 1)
            y += 4
        for g, rows, gw, gh, title_h in blocks:
            if x > margin_x and x + gw > margin_x + usable_w:
                x = margin_x
                y += line_h + group_gap
                line_h = 0.0
            if g.title:
                self.items.append(["text", Q(g.title), ["exclude_from_sim", "no"], ["at", snap(x), snap(y), 0],
                                   ["effects", ["font", ["size", 2.0, 2.0], ["bold", "yes"]], ["justify", "left", "top"]],
                                   ["uuid", Q(_uid(self.s.name, "gtitle", g.title))]])
            if g.note:
                self.items.append(["text", Q(g.note), ["exclude_from_sim", "no"], ["at", snap(x), snap(y + 4.0), 0],
                                   ["effects", ["font", ["size", 1.27, 1.27], ["italic", "yes"]], ["justify", "left", "top"]],
                                   ["uuid", Q(_uid(self.s.name, "gnote", g.title))]])
            cy = y + title_h
            for r in rows:
                cx = x
                rh = max(e[3] - e[1] for _, e in r)
                for p, e in r:
                    ox = snap(cx - e[0], 2.54)
                    oy = snap(cy - e[1], 2.54)
                    placed.append((p, (ox, oy)))
                    cx += (e[2] - e[0]) + gap
                cy += rh + gap
            # frame around group
            self.items.append(["rectangle", ["start", snap(x - 2.54), snap(y - 2.54)],
                               ["end", snap(x + gw + 2.54), snap(y + gh + 2.54)],
                               ["stroke", ["width", 0.1], ["type", "dash"]], ["fill", ["type", "none"]],
                               ["uuid", Q(_uid(self.s.name, "frame", g.title))]])
            x += gw + group_gap
            line_h = max(line_h, gh)
        return placed

    def emit_part(self, p: Part, ox: float, oy: float):
        sym = symlib.get(p.lib_id)
        self.lib_ids.add(p.lib_id)
        r = self.part_rot(p)
        x0, y0, x1, y1 = sym.bbox(p.unit)
        corners = [_rot(x, -y, r) for x, y in ((x0, y0), (x0, y1), (x1, y0), (x1, y1))]
        top = min(c[1] for c in corners)
        bot = max(c[1] for c in corners)
        right = max(c[0] for c in corners)
        two_pin = len(sym.pins_for_unit(p.unit)) <= 2
        horiz = two_pin and all(
            abs(_rot(math.cos(math.radians(pn.angle)), -math.sin(math.radians(pn.angle)), r)[0]) > 0.5
            for pn in sym.pins_for_unit(p.unit))
        if two_pin and horiz:
            ref_at = [ox, round(oy + top - 1.6, 4), r % 180]
            val_at = [ox, round(oy + bot + 1.6, 4), r % 180]
            ref_just = val_just = None
        elif two_pin:
            ref_at = [round(ox + right + 1.27, 4), round(oy - 1.27, 4), 0]
            val_at = [round(ox + right + 1.27, 4), round(oy + 1.27, 4), 0]
            ref_just = val_just = ["justify", "left" if r == 0 else "right"]
        else:
            left = min(c[0] for c in corners)
            ref_at = [round(ox + left, 4), round(oy + top - 3.3, 4), 0]
            val_at = [round(ox + left, 4), round(oy + top - 1.0, 4), 0]
            ref_just = ["justify", "right", "bottom"]
            val_just = ["justify", "right", "bottom"]

        def prop(name, value, at, hide=False, just=None):
            eff = ["effects", ["font", ["size", FONT, FONT]]]
            if just:
                eff.append(just)
            if hide:
                eff.append(["hide", "yes"])
            return ["property", Q(name), Q(value), ["at"] + at, eff]

        uid = _uid(self.s.name, p.ref, p.unit)
        inst = ["symbol", ["lib_id", Q(p.lib_id)], ["at", ox, oy, r], ["unit", p.unit],
                ["exclude_from_sim", "no"], ["in_bom", "yes" if p.in_bom else "no"],
                ["on_board", "yes" if p.on_board else "no"], ["dnp", "yes" if p.dnp else "no"],
                ["uuid", Q(uid)],
                prop("Reference", p.ref, ref_at, just=ref_just),
                prop("Value", p.value, val_at, just=val_just),
                prop("Footprint", p.footprint or sym.prop("Footprint"), [ox, oy, 0], hide=True),
                prop("Datasheet", p.datasheet or sym.prop("Datasheet") or "~", [ox, oy, 0], hide=True),
                prop("Description", p.description or sym.prop("Description"), [ox, oy, 0], hide=True)]
        for k, v in p.fields.items():
            if v:
                inst.append(prop(k, str(v), [ox, oy, 0], hide=True))
        for pin in sym.pins:
            if pin.unit in (0, p.unit):
                inst.append(["pin", Q(pin.number), ["uuid", Q(_uid(uid, "pin", pin.number))]])
        inst.append(["instances", ["project", Q(self.d.project),
                                   ["path", Q(f"/{self.d.root_uuid}/{self.s.uuid}"),
                                    ["reference", Q(p.ref)], ["unit", p.unit]]]])
        self.items.append(inst)

        done_locs = set()
        for pin in sym.pins_for_unit(p.unit):
            loc = (pin.x, pin.y)
            if loc in done_locs:
                continue
            done_locs.add(loc)
            net = self.net_for(p, pin)
            if net == "__UNASSIGNED__":
                raise ValueError(f"{p.ref}: pin {pin.number} ({pin.name}) unassigned")
            px, py = _rot(pin.x, -pin.y, r)
            px, py = round(ox + px, 4), round(oy + py, 4)
            if net is None:
                self.items.append(["no_connect", ["at", px, py], ["uuid", Q(_uid(uid, "nc", pin.number))]])
                continue
            dx, dy = _rot(-math.cos(math.radians(pin.angle)), math.sin(math.radians(pin.angle)), r)
            ex, ey = round(px + dx * STUB, 4), round(py + dy * STUB, 4)
            self.items.append(["wire", ["pts", ["xy", px, py], ["xy", ex, ey]],
                               ["stroke", ["width", 0], ["type", "default"]],
                               ["uuid", Q(_uid(uid, "wire", pin.number))]])
            self.emit_net_end(net, ex, ey, dx, dy, pin, _uid(uid, "lbl", pin.number))

    def emit_net_end(self, net, x, y, dx, dy, pin, uid):
        ang = _dir_angle(dx, dy)
        if net in self.d.power_nets:
            lib_id = POWER_SYMBOLS.get(net, GENERIC_POWER)
            self.lib_ids.add(lib_id)
            sym = symlib.get(lib_id)
            gnd_like = sym.pins[0].angle == 90 and sym.bbox()[1] < -0.5  # body below pin
            if net == "GND" or gnd_like:
                rot = {270: 0, 0: 90, 90: 180, 180: 270}[ang]
            else:
                rot = {90: 0, 180: 90, 270: 180, 0: 270}[ang]
            self.pwr_count += 1
            ref = f"#PWR{self.page:02d}{self.pwr_count:03d}"
            vx, vy = dx * 3.3, dy * 3.3
            # KiCad mirrors field justification with the symbol orientation
            hj = ("left", "right") if rot != 90 else ("right", "left")
            vj = ("bottom", "top") if rot != 180 else ("top", "bottom")
            vjust = ["justify", hj[0]] if dx > 0.5 else ["justify", hj[1]] if dx < -0.5 else \
                ["justify", vj[0]] if dy < 0 else ["justify", vj[1]]
            self.items.append([
                "symbol", ["lib_id", Q(lib_id)], ["at", x, y, rot], ["unit", 1],
                ["exclude_from_sim", "no"], ["in_bom", "yes"], ["on_board", "yes"], ["dnp", "no"],
                ["uuid", Q(uid)],
                ["property", Q("Reference"), Q(ref), ["at", x, y, 0], ["effects", ["font", ["size", FONT, FONT]], ["hide", "yes"]]],
                ["property", Q("Value"), Q(net), ["at", round(x + vx, 4), round(y + vy, 4), rot % 180], ["effects", ["font", ["size", FONT, FONT]], vjust]],
                ["property", Q("Footprint"), Q(""), ["at", x, y, 0], ["effects", ["font", ["size", FONT, FONT]], ["hide", "yes"]]],
                ["property", Q("Datasheet"), Q(""), ["at", x, y, 0], ["effects", ["font", ["size", FONT, FONT]], ["hide", "yes"]]],
                ["property", Q("Description"), Q(""), ["at", x, y, 0], ["effects", ["font", ["size", FONT, FONT]], ["hide", "yes"]]],
                ["pin", Q(sym.pins[0].number), ["uuid", Q(_uid(uid, "p"))]],
                ["instances", ["project", Q(self.d.project),
                               ["path", Q(f"/{self.d.root_uuid}/{self.s.uuid}"), ["reference", Q(ref)], ["unit", 1]]]],
            ])
            return
        multi = len(self.net_sheets.get(net, ())) > 1
        just = ["justify", "left", "bottom"] if ang in (0, 90) else ["justify", "right", "bottom"]
        if multi:
            shape = {"input": "input", "output": "output", "bidirectional": "bidirectional",
                     "tri_state": "tri_state"}.get(pin.etype, "passive")
            shape = self.d.net_shapes.get(net, shape)
            gj = ["justify", "left"] if ang in (0, 90) else ["justify", "right"]
            self.items.append([
                "global_label", Q(net), ["shape", shape], ["at", x, y, ang], ["fields_autoplaced", "yes"],
                ["effects", ["font", ["size", FONT, FONT]], gj], ["uuid", Q(uid)],
                ["property", Q("Intersheetrefs"), Q("${INTERSHEET_REFS}"), ["at", x, y, ang],
                 ["effects", ["font", ["size", FONT, FONT]], gj, ["hide", "yes"]]],
            ])
        else:
            self.items.append(["label", Q(net), ["at", x, y, ang],
                               ["effects", ["font", ["size", FONT, FONT]], just], ["uuid", Q(uid)]])
