"""Generate KiCad 10 hierarchical schematics from a Python netlist description.

The sheets are DRAWN, not just labelled: connected pins are joined by wires that a reader can follow by eye
(tools/README.md, "Wiring rule", R1-R6). schplace.py does the work:

  * every schgen group is a cluster (groups sharing a local net are merged); the cluster's anchor IC is placed
    first and each satellite part goes next to the pin it serves, oriented to face it (pull-ups, dividers,
    filters, series chains, decoupling caps on the pin they decouple);
  * every connection on a sheet is a routed orthogonal wire with junction dots at T's;
  * a net that leaves the sheet gets ONE global label per cluster, wired to all of the cluster's pins on it;
  * power nets end in power symbols; a local net carries one local label as a name tag, on its wire.

Design.check() verifies the drawing itself (R1-R3 + wire rules) and build.py fails on any error. There is no
label fallback and no waiver: a connection that cannot be drawn is an error.
"""

from __future__ import annotations

import json
import math
import os
import uuid as _uuid
from dataclasses import dataclass, field

import schplace
import sexpr
import symlib
from sexpr import Q

GRID = 1.27
STUB = 2.54
FONT = 1.27
CHAR_W = schplace.CW

# Net name -> power symbol lib_id. Nets not listed use a generic power symbol
# whose Value becomes the net name.
POWER_SYMBOLS = {
    "GND": "power:GND",
    "+3V3": "power:+3V3",
    "VBUS": "power:VBUS",
}
GENERIC_POWER = "power:VCC"

# Namespace prefix for the deterministic uuid5s of every schematic item. Each project sets its own
# (set_uuid_namespace) so two projects' sheets never share UUIDs.
UUID_NAMESPACE = "dial-me-spinner"
# KiCad 10 file format (eeschema 10.0.x writes version 20260306). The writer emits what KiCad 10 itself writes,
# so a load + save in KiCad 10 changes nothing but token order and formatting.
SCH_VERSION = "20260306"
GENERATOR_VERSION = "10.0"

PAPERS = [("A3", 420.0, 297.0), ("A2", 594.0, 420.0), ("A1", 841.0, 594.0), ("A0", 1189.0, 841.0)]


def set_uuid_namespace(ns: str) -> None:
    global UUID_NAMESPACE
    UUID_NAMESPACE = ns


def _uid(*parts) -> str:
    return str(_uuid.uuid5(_uuid.NAMESPACE_URL, UUID_NAMESPACE + "/" + "/".join(map(str, parts))))


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
    rot: int | None = None                       # orientation hint, used for parts with only power pins
    unit: int = 1
    dnp: bool = False
    in_bom: bool = True
    on_board: bool = True
    sheet: "Sheet" = None
    group: str = ""
    near: str | None = None                      # placer hint: "U60" or "U60.9": decouple this IC (pin)


@dataclass
class Group:
    title: str
    parts: list = field(default_factory=list)
    note: str = ""
    anchor: str | None = None                    # placer hint: ref of the cluster's anchor part


class Sheet:
    def __init__(self, design: "Design", name: str, filename: str, title: str = ""):
        self.design = design
        self.name = name
        self.filename = filename
        self.title = title or name
        self.groups: list[Group] = []
        self.notes: list[str] = []
        self.uuid = _uid("sheet", name)

    def group(self, title: str, note: str = "", anchor: str | None = None) -> Group:
        g = Group(title, [], note, anchor)
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
        self.intersheet: set[str] = set()          # nets drawn with global labels even if on one sheet
        self.forced_labels: set[str] = set()       # see force_labels()
        self.warnings: list[str] = []
        self._plans = None

    # ---- construction API -------------------------------------------------
    def sheet(self, name: str, filename: str, title: str = "") -> Sheet:
        s = Sheet(self, name, filename, title)
        self.sheets.append(s)
        self._cur_sheet = s
        self._cur_group = None
        self._plans = None
        return s

    def group(self, title: str, note: str = "", anchor: str | None = None) -> Group:
        self._cur_group = self._cur_sheet.group(title, note, anchor)
        return self._cur_group

    def add(self, ref, lib_id, value, footprint="", pins=None, **kw) -> Part:
        if self._cur_group is None:
            self.group("")
        p = Part(ref=ref, lib_id=lib_id, value=value, footprint=footprint, pins=dict(pins or {}), **kw)
        p.sheet = self._cur_sheet
        p.group = self._cur_group.title
        self._cur_group.parts.append(p)
        self._plans = None
        return p

    def power(self, *nets: str) -> None:
        self.power_nets.update(nets)

    def force_labels(self, *nets: str) -> None:
        """Draw these nets the old way: a label on every pin, no wires. This exists so the checker can be
        tested (tools/tests): check() rejects it for any local net (R1) and for more than one global label
        per cluster (R3). Never use it in a real design."""
        self.forced_labels.update(nets)
        self._plans = None

    def power_lib(self, net: str) -> str:
        return POWER_SYMBOLS.get(net, GENERIC_POWER)

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

    def net_kind(self, net: str) -> str:
        """'P' power, 'G' intersheet (global label), 'L' local (wired)."""
        if net in self.power_nets:
            return "P"
        if len(self.net_sheets().get(net, ())) > 1 or net in self.intersheet:
            return "G"
        return "L"

    def static_check(self) -> list[str]:
        """Refs unique, all visible pins assigned, nets with one pin."""
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

    def check(self) -> list[str]:
        """Static checks + lay out and route every sheet + verify the drawing (wiring rule R1-R3, R6 wires).

        Errors name the sheet, the net and the pins. Text-overlap findings go to self.warnings."""
        errs = self.static_check()
        if errs:
            return errs
        try:
            plans = self.plans()
        except (ValueError, schplace.RouteError) as e:
            return errs + [f"layout failed: {e}"]
        self.warnings = []
        for plan in plans:
            errs += plan.errors
            e, w = check_drawing(self, plan)
            errs += e
            self.warnings += w
        return errs

    def plans(self):
        if self._plans is None:
            self._plans = [SheetPlan(self, s) for s in self.sheets]
        return self._plans

    # ---- output -------------------------------------------------------------
    def write(self, outdir: str, extra_sym_libs: dict | None = None, extra_fp_libs: dict | None = None):
        os.makedirs(outdir, exist_ok=True)
        page = 2
        for plan in self.plans():
            sch = _emit_sheet(self, plan, page)
            with open(os.path.join(outdir, plan.sheet.filename), "w", encoding="utf-8") as f:
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
            "kicad_sch", ["version", SCH_VERSION], ["generator", Q("eeschema")], ["generator_version", Q(GENERATOR_VERSION)],
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
                ["stroke", ["width", 0.1524], ["type", "solid"]], ["fill", ["color", 0, 0, 0, 0]],
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
        return _k10(items)   # KiCad 10 drops the file-level (embedded_fonts no)

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


def _ds(v):
    """A datasheet as KiCad 10 stores it: KiCad 9's "~" (none) is written as ""."""
    return "" if not v or v == "~" else v


def _k10(node):
    """KiCad 10 property layout, in place: a hidden property carries (hide yes) itself, not inside its effects,
    followed by the (show_name no) (do_not_autoplace no) flags KiCad 10 always writes."""
    if isinstance(node, list):
        for child in node:
            _k10(child)
        if node and node[0] == "property" and not any(isinstance(c, list) and c and c[0] == "show_name"
                                                     for c in node):
            eff = next((c for c in node if isinstance(c, list) and c and c[0] == "effects"), None)
            hidden = eff is not None and ["hide", "yes"] in eff
            if hidden:
                eff.remove(["hide", "yes"])
            at = next((i for i, c in enumerate(node) if isinstance(c, list) and c and c[0] == "at"), None)
            pos = (at + 1) if at is not None else 3
            node[pos:pos] = ([["hide", "yes"]] if hidden else []) + [["show_name", "no"], ["do_not_autoplace", "no"]]
    return node


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


_rot = schplace._rot


def _dir_angle(dx, dy):
    """Screen direction vector -> KiCad text angle."""
    if dx > 0.5:
        return 0
    if dx < -0.5:
        return 180
    if dy < -0.5:
        return 90
    return 270


# ================================================================================================ sheet plan

class ClusterPlan:
    def __init__(self, groups, block, segs, juncs, errors):
        self.groups = groups
        self.block = block
        self.segs = segs          # group key -> [((x0,y0),(x1,y1))]
        self.juncs = juncs
        self.errors = errors
        self.ox = self.oy = 0.0   # page offset of the cluster's content
        self.frame = None         # (x0, y0, x1, y1) on the page
        self.header = []          # (kind, text, x, y)


class SheetPlan:
    """Clusters of one sheet, placed, routed and packed onto a page."""

    def __init__(self, design: Design, sheet: Sheet):
        self.d = design
        self.sheet = sheet
        self.errors: list[str] = []
        self.clusters: list[ClusterPlan] = []
        nets = schplace.SheetNets(design, sheet)
        self.nets = nets
        for groups, parts, hint in self._clusters(nets):
            if parts:
                c = schplace.Cluster(sheet, parts, groups, nets, hint, design.forced_labels)
                blk = c.build()
                segs, juncs, errs = schplace.route(blk)
                errs = c.errors + errs
            else:
                blk, segs, juncs, errs = schplace.Block(), {}, [], []
            self.errors += [f"sheet {sheet.name}: {e}" for e in errs]
            self.clusters.append(ClusterPlan(groups, blk, segs, juncs, errs))
        self._pack()

    def _clusters(self, nets):
        s = self.sheet
        groups = s.groups
        n = len(groups)
        parent = list(range(n))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        gof = {}
        for gi_, g in enumerate(groups):
            for p in g.parts:
                gof[(p.ref, p.unit)] = gi_
        forced = self.d.forced_labels
        by_net = {}
        for p in s.parts():
            for net in p.pins.values():
                if net is None or net in forced or nets.kind(net) != "L":
                    continue
                by_net.setdefault(net, []).append(gof[(p.ref, p.unit)])
        for gl in by_net.values():
            for g2 in gl[1:]:
                a, b = find(gl[0]), find(g2)
                if a != b:
                    parent[max(a, b)] = min(a, b)
        home = {k: find(v) for k, v in gof.items()}

        def nslots(p):
            return 3 if schplace.is_anchor_part(p) else len(schplace.geo(p.lib_id, p.unit).slots)
        members = {}
        for p in s.parts():
            for net in p.pins.values():
                if net is not None:
                    members.setdefault(net, []).append(p)
        has_multi = {}
        for p in s.parts():
            if nslots(p) >= 3:
                has_multi[home[(p.ref, p.unit)]] = True
        moved_from = {}
        for p in s.parts():
            k = (p.ref, p.unit)
            if nslots(p) >= 3 or has_multi.get(home[k]):
                continue
            sig = {n for n in p.pins.values() if n is not None and n not in self.d.power_nets and n not in forced}
            pw = [n for n in p.pins.values() if n is not None and n in self.d.power_nets]
            if not sig and len(pw) == 2 and nslots(p) == 2:
                # a decoupling cap in a group of its own: move it to the IC it decouples
                if p.near:
                    tgt = {(q.ref, q.unit) for q in s.parts() if q.ref == p.near.partition(".")[0] and nslots(q) >= 3}
                else:
                    tgt = {(q.ref, q.unit) for n in pw if not schplace.gnd_like(n)
                           for q in members.get(n, []) if nslots(q) >= 3}
                if len({t[0] for t in tgt}) == 1:
                    home[k] = home[sorted(tgt)[0]]
                continue
            if len(sig) != 1:
                continue
            net = next(iter(sig))
            multis = {(q.ref, q.unit) for q in members[net] if nslots(q) >= 3}
            if len(multis) == 1:
                q = next(iter(multis))
                moved_from.setdefault(gof[k], []).append(home[k])
                home[k] = home[q]
        roots = []
        for gi_ in range(n):
            r = find(gi_)
            if r not in roots:
                roots.append(r)
        out = []
        for r in roots:
            gs = []
            for gi_, g in enumerate(groups):
                parts_left = [p for p in g.parts if home[(p.ref, p.unit)] == r]
                stays = find(gi_) == r and (parts_left or not g.parts)
                dissolved = g.parts and all(home[(p.ref, p.unit)] != find(gi_) for p in g.parts)
                if stays and not (dissolved and not g.note):
                    gs.append(g)
                elif dissolved and g.note and home[(g.parts[0].ref, g.parts[0].unit)] == r:
                    gs.append(g)
            parts = [p for p in s.parts() if home[(p.ref, p.unit)] == r]
            hint = next((g.anchor for g in gs if g.anchor), None)
            if parts or gs:
                out.append((gs, parts, hint))
        return out

    def _pack(self):
        title_h, note_line = 4.0, 2.25
        frames = []
        for c in self.clusters:
            bb = c.block.bbox() if c.block.items else schplace.Box(0, 0, 0, 0)
            for ss in c.segs.values():
                for a, b in ss:
                    bb = schplace.Box(min(bb.x0, a[0], b[0]), min(bb.y0, a[1], b[1]),
                                      max(bb.x1, a[0], b[0]), max(bb.y1, a[1], b[1]))
            head = []
            y = 0.0
            hw = 0.0
            for g in c.groups:
                if g.title:
                    head.append(("title", g.title, y))
                    hw = max(hw, len(g.title) * 1.9)
                    y += title_h
                if g.note:
                    for line in g.note.split("\n"):
                        hw = max(hw, len(line) * 1.12)
                    head.append(("note", g.note, y))
                    y += note_line * (g.note.count("\n") + 1) + 1.0
            hh = y + (3.0 if c.block.items else 0.0)
            cw = (bb.x1 - bb.x0) if c.block.items else 0.0
            ch = (bb.y1 - bb.y0) if c.block.items else 0.0
            w = max(cw, hw, 30.0)
            h = hh + ch
            frames.append((c, bb, head, hh, w, h))
        margin_x, margin_y, gap = 15.24, 15.24, 10.16
        tb_h = 38.0

        def pack(page_w, page_h):
            usable_w = page_w - 2 * margin_x
            x, y, line_h = margin_x, margin_y, 0.0
            pos = []
            for c, bb, head, hh, w, h in frames:
                if x > margin_x and x + w > margin_x + usable_w:
                    x = margin_x
                    y += line_h + gap
                    line_h = 0.0
                pos.append((x, y))
                x += w + gap
                line_h = max(line_h, h)
            return pos, y + line_h
        def pack_ffdh(page_w, page_h):
            """First-fit decreasing height: tallest clusters first, each into the first row with room. Packs a
            sheet of many short groups and a few tall ones much tighter than the in-order rows."""
            usable_w = page_w - 2 * margin_x
            order = sorted(range(len(frames)), key=lambda k: -frames[k][5])
            rows = []                                   # [y, height, next x]
            pos = [None] * len(frames)
            for k in order:
                w, h = frames[k][4], frames[k][5]
                row = next((r for r in rows if r[2] + w <= margin_x + usable_w or r[2] == margin_x), None)
                if row is None:
                    y = (rows[-1][0] + rows[-1][1] + gap) if rows else margin_y
                    row = [y, h, margin_x]
                    rows.append(row)
                pos[k] = (row[2], row[0])
                row[2] += w + gap
            return pos, (rows[-1][0] + rows[-1][1]) if rows else margin_y

        tb_w = 115.0   # the title block (bottom right); a cluster may use the bottom band left of it

        def on_page(pos, pw, ph):
            for (c, bb, head, hh, w, h), (x, y) in zip(frames, pos):
                if x + w > pw - margin_x or y + h > ph - margin_y:
                    return False
                if y + h > ph - margin_y - tb_h and x + w > pw - margin_x - tb_w:
                    return False
            return True

        for paper, pw, ph in PAPERS:
            pos, bottom = pack(pw, ph)
            if all(f[4] <= pw - 2 * margin_x for f in frames) and bottom <= ph - margin_y - tb_h:
                break
            # the in-order rows do not fit this paper: try the tighter packing (whose last, shortest row may sit
            # left of the title block) before going up a size; the power sheet was an A2 more than half empty
            pos, bottom = pack_ffdh(pw, ph)
            if on_page(pos, pw, ph):
                break
            pos, bottom = pack(pw, ph)
        self.paper, self.page_w, self.page_h = paper, pw, ph
        for (c, bb, head, hh, w, h), (x, y) in zip(frames, pos):
            x, y = snap(x), snap(y)
            c.header = [(k, t, x, y + dy) for k, t, dy in head]
            c.frame = (snap(x - 2.54), snap(y - 2.54), snap(x + w + 2.54), snap(y + h + 2.54))
            if c.block.items:
                dx, dy = snap(x - bb.x0), snap(y + hh - bb.y0)
                c.block.move(dx, dy)
                c.segs = {k: [((a[0] + dx, a[1] + dy), (b[0] + dx, b[1] + dy)) for a, b in v] for k, v in c.segs.items()}
                c.segs = {k: [((round(a[0], 4), round(a[1], 4)), (round(b[0], 4), round(b[1], 4))) for a, b in v]
                          for k, v in c.segs.items()}
                c.juncs = [(round(x0 + dx, 4), round(y0 + dy, 4)) for x0, y0 in c.juncs]


# ================================================================================================ checks

def check_drawing(design: Design, plan: SheetPlan):
    """Verify the drawing of one sheet against the netlist and the wiring rule.

    Builds the wire connectivity of the drawing itself (labels do NOT connect anything here) and checks:
      R1  every local (single-sheet, non-power) net is one wired component holding all of its pins;
      R3  an intersheet net has exactly one global label per wired component, one per cluster;
      --  no component joins two nets (short), every power pin reaches a power symbol of its net;
      R6  no wire crosses a symbol body, no wire overlaps a wire of another net, no wire end lands on the
          middle of another wire (KiCad would connect it); text overlaps are returned as warnings.
    Returns (errors, warnings)."""
    errs, warns = [], []
    sname = plan.sheet.name
    kinds = {}

    def net_kind(n):
        if n not in kinds:
            kinds[n] = design.net_kind(n)
        return kinds[n]
    pts = {}                  # point -> list of (kind, net, desc, cluster index)

    def P(x, y):
        return (round(x, 3), round(y, 3))
    parent = {}

    def find(a):
        parent.setdefault(a, a)
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    segs = []
    bodies = []
    texts = []
    pin_tips = []
    for ci, c in enumerate(plan.clusters):
        for it in c.block.items:
            if it.kind == "sym":
                bodies.append((it.body(), f"{it.part.ref}"))
                for b in it.field_boxes():
                    texts.append((b, f"{it.part.ref} field"))
                for i, net in enumerate(it.nets):
                    tip = P(*it.tip(i))
                    desc = f"{it.part.ref}.{it.g.slots[i].number}"
                    find(tip)
                    pin_tips.append(tip)
                    if net is None:
                        continue
                    pts.setdefault(tip, []).append(("pin", net, desc, ci))
            elif it.kind == "pow":
                tip = P(it.x, it.y)
                find(tip)
                pts.setdefault(tip, []).append(("pow", it.net, f"power {it.net}", ci))
                pin_tips.append(tip)
                for b in it.boxes()[1:]:
                    texts.append((b, f"power {it.net}"))
            elif it.kind == "label":
                tip = P(it.x, it.y)
                find(tip)
                pts.setdefault(tip, []).append((it.scope, it.net, f"{it.scope} label {it.net}", ci))
                for b in it.boxes():
                    texts.append((b, f"label {it.net}"))
        for key, ss in c.segs.items():
            for a, b in ss:
                a, b = P(*a), P(*b)
                union(a, b)
                segs.append((a, b, key, ci))
    # T's must be split: a point strictly inside a segment is a hidden connection in KiCad
    ends = set()
    for a, b, _, _ in segs:
        ends.add(a)
        ends.add(b)
    allpts = ends | set(pts) | set(pin_tips)
    for a, b, key, ci in segs:
        if a[0] == b[0]:
            inside = [p for p in allpts if p[0] == a[0] and min(a[1], b[1]) < p[1] < max(a[1], b[1])]
        elif a[1] == b[1]:
            inside = [p for p in allpts if p[1] == a[1] and min(a[0], b[0]) < p[0] < max(a[0], b[0])]
        else:
            errs.append(f"{sname}: wire {a}-{b} ({key}) is not orthogonal")
            continue
        for p in inside:
            errs.append(f"{sname}: wire of {key} passes through a connection point at {p} "
                        f"({', '.join(x[2] for x in pts.get(p, [])) or 'wire end'})")
    # wire over body / overlapping wires of different groups
    for a, b, key, ci in segs:
        x0, x1 = sorted((a[0], b[0]))
        y0, y1 = sorted((a[1], b[1]))
        for bx, ref in bodies:
            xin = (x0 < bx.x1 - 0.01 and bx.x0 + 0.01 < x1) if x0 != x1 else (bx.x0 - 0.01 <= x0 <= bx.x1 + 0.01)
            yin = (y0 < bx.y1 - 0.01 and bx.y0 + 0.01 < y1) if y0 != y1 else (bx.y0 - 0.01 <= y0 <= bx.y1 + 0.01)
            if xin and yin:
                errs.append(f"{sname}: wire of {key} crosses the body of {ref}")
    hs = {}
    for a, b, key, ci in segs:
        if a[1] == b[1] and a[0] != b[0]:
            hs.setdefault(("h", a[1]), []).append((min(a[0], b[0]), max(a[0], b[0]), key))
        elif a[0] == b[0] and a[1] != b[1]:
            hs.setdefault(("v", a[0]), []).append((min(a[1], b[1]), max(a[1], b[1]), key))
    for line, lst in hs.items():
        lst.sort()
        for i in range(len(lst)):
            for j in range(i + 1, len(lst)):
                if lst[j][0] >= lst[i][1]:
                    break
                if _base(lst[i][2]) != _base(lst[j][2]):
                    errs.append(f"{sname}: wires of {lst[i][2]} and {lst[j][2]} overlap on {line}")
    # junction dots exactly where 3+ wire ends / pins meet (R6: a dot on every T, none elsewhere)
    deg = {}
    for a, b, _, _ in segs:
        deg[a] = deg.get(a, 0) + 1
        deg[b] = deg.get(b, 0) + 1
    for p, lst in pts.items():
        deg[p] = deg.get(p, 0) + sum(1 for e in lst if e[0] in ("pin", "pow"))
    for t in pin_tips:
        if t not in pts:
            deg[t] = deg.get(t, 0) + 1
    juncs = {P(*j) for c in plan.clusters for j in c.juncs}
    for p, n in deg.items():
        if n >= 3 and p not in juncs:
            errs.append(f"{sname}: missing junction dot at {p} ({n} connections)")
    for p in juncs:
        if deg.get(p, 0) < 3:
            errs.append(f"{sname}: junction dot at {p} joins only {deg.get(p, 0)} connections")
    # components
    comp = {}
    for p, lst in pts.items():
        for entry in lst:
            comp.setdefault(find(p), []).append(entry)
    pin_net_comps = {}
    for r, lst in comp.items():
        nets_here = {e[1] for e in lst}
        if len(nets_here) > 1:
            errs.append(f"{sname}: SHORT: one wired node joins {sorted(nets_here)}: "
                        f"{', '.join(e[2] for e in lst)}")
        for e in lst:
            if e[0] == "pin":
                pin_net_comps.setdefault(e[1], {}).setdefault(r, []).append(e)
    for net, comps in pin_net_comps.items():
        kind = net_kind(net)
        lists = list(comps.values())
        roots = list(comps)
        if kind == "L":
            if len(roots) > 1:
                groups = " | ".join(", ".join(e[2] for e in v) for v in lists)
                labelled = any(any(e[0] == "local" for e in comp[r]) for r in roots)
                how = "only through labels" if labelled else "not at all"
                errs.append(f"R1 sheet {sname}: local net {net} is not wired: pins [{groups}] are joined {how}")
            elif len([e for e in lists[0] if e[0] == "pin"]) < 2 and not any(e[0] == "local" for e in comp[roots[0]]):
                pass
        elif kind == "G":
            per_cluster = {}
            for r in roots:
                labs = [e for e in comp[r] if e[0] == "global" and e[1] == net]
                if len(labs) != 1:
                    errs.append(f"R3 sheet {sname}: intersheet net {net}: wired node with pins "
                                f"[{', '.join(e[2] for e in comp[r] if e[0] == 'pin')}] has {len(labs)} global labels "
                                f"(need exactly 1)")
                for e in labs:
                    per_cluster[e[3]] = per_cluster.get(e[3], 0) + 1
            for ci, nlab in per_cluster.items():
                if nlab > 1:
                    gs = plan.clusters[ci].groups
                    title = gs[0].title if gs else "?"
                    errs.append(f"R3 sheet {sname}: intersheet net {net} has {nlab} global labels in the cluster "
                                f"'{title}': wire its pins to one label")
        else:
            for r in roots:
                if not any(e[0] == "pow" and e[1] == net for e in comp[r]):
                    errs.append(f"{sname}: power pins [{', '.join(e[2] for e in comp[r] if e[0] == 'pin')}] "
                                f"of {net} reach no power symbol")
    # every connected pin must be connected to something
    for r, lst in comp.items():
        if len(lst) == 1 and lst[0][0] == "pin":
            errs.append(f"{sname}: pin {lst[0][2]} ({lst[0][1]}) is not connected to anything")
    # local labels: only as a name tag on a wired net (R1): a local label alone on a node is a label connection
    for r, lst in comp.items():
        for e in lst:
            if e[0] == "local" and net_kind(e[1]) == "L" and not any(x[0] == "pin" for x in lst):
                errs.append(f"R1 sheet {sname}: local label {e[1]} is not on a wire to any pin")
    # text overlaps (warnings)
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            if texts[i][0].hits(texts[j][0], clr=-0.15):
                warns.append(f"{sname}: text of {texts[i][1]} overlaps {texts[j][1]}")
    return errs, warns


def _base(key):
    return key.split("#")[0]


# ================================================================================================ emission

def _field_attrs(ps, hj):
    """Stored (angle, justify) for a horizontal, readable field on a placed symbol.

    KiCad stores field angle/justification in the symbol's frame and renders them through the symbol's
    orientation (flipping the justification when the text would run backwards)."""
    swap = ps.rot in (90, 270)
    ang = 90 if swap else 0
    u, v = (0, -1) if swap else (1, 0)
    if ps.mirror:
        u = -u
    ex, ey = _rot(u, v, ps.rot)
    if ex < 0 and hj in ("left", "right"):
        hj = "right" if hj == "left" else "left"
    return ang, hj


def _emit_sheet(d: Design, plan: SheetPlan, page: int):
    s = plan.sheet
    items = []
    lib_ids = set()
    pwr = [0]

    def text(t, x, y, uid, size=FONT, bold=False, italic=False):
        eff = ["effects", ["font", ["size", size, size]] + ([["bold", "yes"]] if bold else []) +
               ([["italic", "yes"]] if italic else []), ["justify", "left", "top"]]
        return ["text", Q(t), ["exclude_from_sim", "no"], ["at", snap(x), snap(y), 0], eff, ["uuid", Q(uid)]]
    for k, n in enumerate(s.notes):
        items.append(_text(n, 15.24, 8.0 + 6 * k, _uid(s.name, "note", k)))
    nlab, nwire = {}, {}
    for ci, c in enumerate(plan.clusters):
        for kind, t, x, y in c.header:
            if kind == "title":
                items.append(text(t, x, y, _uid(s.name, "gtitle", t), 2.0, bold=True))
            else:
                items.append(text(t, x, y, _uid(s.name, "gnote", t[:40], ci), 1.27, italic=True))
        if c.frame:
            x0, y0, x1, y1 = c.frame
            items.append(["rectangle", ["start", x0, y0], ["end", x1, y1],
                          ["stroke", ["width", 0.1], ["type", "dash"]], ["fill", ["type", "none"]],
                          ["uuid", Q(_uid(s.name, "frame", ci, c.groups[0].title if c.groups else ""))]])
        for it in c.block.items:
            if it.kind == "sym":
                lib_ids.add(it.part.lib_id)
                items.append(_emit_symbol(d, s, it))
            elif it.kind == "pow":
                lib_ids.add(it.lib_id)
                pwr[0] += 1
                items.append(_emit_power(d, s, it, page, pwr[0]))
            elif it.kind == "label":
                k = nlab[it.net] = nlab.get(it.net, 0) + 1
                items.append(_emit_label(d, s, it, _uid(s.name, "lbl", it.net, k)))
            elif it.kind == "nc":
                items.append(["no_connect", ["at", it.x, it.y], ["uuid", Q(_uid(s.name, "nc", it.x, it.y))]])
        for key in sorted(c.segs):
            for a, b in c.segs[key]:
                # numbered per sheet, not per cluster: a net drawn in two clusters of one sheet used to give two
                # wires the same uuid (KiCad renumbers them on load, so `sch upgrade` was not a no-op)
                k = nwire[key] = nwire.get(key, -1) + 1
                items.append(["wire", ["pts", ["xy", a[0], a[1]], ["xy", b[0], b[1]]],
                              ["stroke", ["width", 0], ["type", "default"]],
                              ["uuid", Q(_uid(s.name, "w", key, k))]])
        for (x, y) in c.juncs:
            items.append(["junction", ["at", x, y], ["diameter", 0], ["color", 0, 0, 0, 0],
                          ["uuid", Q(_uid(s.name, "j", x, y))]])
    lib_symbols = ["lib_symbols"] + [symlib.get(l).embedded() for l in sorted(lib_ids)]
    head = [
        "kicad_sch", ["version", SCH_VERSION], ["generator", Q("eeschema")], ["generator_version", Q(GENERATOR_VERSION)],
        ["uuid", Q(s.uuid)], ["paper", Q(plan.paper)], d._title_block(s.title), lib_symbols,
    ]
    return _k10(head + items)


def _emit_symbol(d: Design, s: Sheet, ps):
    p = ps.part
    sym = symlib.get(p.lib_id)
    ox, oy = ps.x, ps.y

    def prop(name, value, at, hide=False, just=None):
        eff = ["effects", ["font", ["size", FONT, FONT]]]
        if just:
            eff.append(["justify", just])
        if hide:
            eff.append(["hide", "yes"])
        return ["property", Q(name), Q(value), ["at"] + at, eff]
    fl = {}
    for name, dx, dy, hj in ps.fields:
        ang, j = _field_attrs(ps, hj)
        fl[name] = ([round(ox + dx, 4), round(oy + dy, 4), ang], None if j == "center" else j)
    uid = _uid(s.name, p.ref, p.unit)
    inst = ["symbol", ["lib_id", Q(p.lib_id)], ["at", ox, oy, ps.rot]]
    if ps.mirror:
        inst.append(["mirror", "y"])
    inst += [["unit", p.unit], ["body_style", 1],
             ["exclude_from_sim", "no"], ["in_bom", "yes" if p.in_bom else "no"],
             ["on_board", "yes" if p.on_board else "no"], ["in_pos_files", "yes"],
             ["dnp", "yes" if p.dnp else "no"],
             ["uuid", Q(uid)],
             prop("Reference", p.ref, fl["Reference"][0], just=fl["Reference"][1]),
             prop("Value", p.value, fl["Value"][0], just=fl["Value"][1]),
             prop("Footprint", p.footprint or sym.prop("Footprint"), [ox, oy, 0], hide=True),
             prop("Datasheet", _ds(p.datasheet or sym.prop("Datasheet")), [ox, oy, 0], hide=True),
             prop("Description", p.description or sym.prop("Description"), [ox, oy, 0], hide=True)]
    for k, v in p.fields.items():
        if v:
            inst.append(prop(k, str(v), [ox, oy, 0], hide=True))
    for pin in sym.pins:
        if pin.unit in (0, p.unit):
            inst.append(["pin", Q(pin.number), ["uuid", Q(_uid(uid, "pin", pin.number))]])
    inst.append(["instances", ["project", Q(d.project),
                               ["path", Q(f"/{d.root_uuid}/{s.uuid}"),
                                ["reference", Q(p.ref)], ["unit", p.unit]]]])
    return inst


def _emit_power(d: Design, s: Sheet, pw, page: int, n: int):
    lib_id = pw.lib_id
    sym = symlib.get(lib_id)
    x, y = pw.x, pw.y
    dx, dy = pw.bdir
    ang = _dir_angle(dx, dy)
    gnd_like = sym.pins[0].angle == 90 and sym.bbox()[1] < -0.5
    if pw.net == "GND" or gnd_like:
        rot = {270: 0, 0: 90, 90: 180, 180: 270}[ang]
    else:
        rot = {90: 0, 180: 90, 270: 180, 0: 270}[ang]
    ref = f"#PWR{page:02d}{n:03d}"
    vx, vy = dx * 3.3, dy * 3.3
    hj = ("left", "right") if rot != 90 else ("right", "left")
    vj = ("bottom", "top") if rot != 180 else ("top", "bottom")
    vjust = ["justify", hj[0]] if dx > 0.5 else ["justify", hj[1]] if dx < -0.5 else \
        ["justify", vj[0]] if dy < 0 else ["justify", vj[1]]
    uid = _uid(s.name, "pwr", pw.net, x, y)
    return [
        "symbol", ["lib_id", Q(lib_id)], ["at", x, y, rot], ["unit", 1], ["body_style", 1],
        ["exclude_from_sim", "no"], ["in_bom", "yes"], ["on_board", "yes"], ["in_pos_files", "yes"], ["dnp", "no"],
        ["uuid", Q(uid)],
        ["property", Q("Reference"), Q(ref), ["at", x, y, 0], ["effects", ["font", ["size", FONT, FONT]], ["hide", "yes"]]],
        ["property", Q("Value"), Q(pw.net), ["at", round(x + vx, 4), round(y + vy, 4), rot % 180],
         ["effects", ["font", ["size", FONT, FONT]], vjust]],
        ["property", Q("Footprint"), Q(""), ["at", x, y, 0], ["effects", ["font", ["size", FONT, FONT]], ["hide", "yes"]]],
        ["property", Q("Datasheet"), Q(""), ["at", x, y, 0], ["effects", ["font", ["size", FONT, FONT]], ["hide", "yes"]]],
        ["property", Q("Description"), Q(""), ["at", x, y, 0], ["effects", ["font", ["size", FONT, FONT]], ["hide", "yes"]]],
        ["pin", Q(sym.pins[0].number), ["uuid", Q(_uid(uid, "p"))]],
        ["instances", ["project", Q(d.project),
                       ["path", Q(f"/{d.root_uuid}/{s.uuid}"), ["reference", Q(ref)], ["unit", 1]]]],
    ]


def _emit_label(d: Design, s: Sheet, lab, uid):
    ang = _dir_angle(*lab.d)
    x, y = lab.x, lab.y
    if lab.scope == "global":
        gj = ["justify", "left"] if ang in (0, 90) else ["justify", "right"]
        return ["global_label", Q(lab.net), ["shape", lab.shape], ["at", x, y, ang], ["fields_autoplaced", "yes"],
                ["effects", ["font", ["size", FONT, FONT]], gj], ["uuid", Q(uid)],
                ["property", Q("Intersheetrefs"), Q("${INTERSHEET_REFS}"), ["at", x, y, ang],
                 ["effects", ["font", ["size", FONT, FONT]], gj, ["hide", "yes"]]]]
    just = ["justify", "left", "bottom"] if ang in (0, 90) else ["justify", "right", "bottom"]
    return ["label", Q(lab.net), ["at", x, y, ang], ["effects", ["font", ["size", FONT, FONT]], just], ["uuid", Q(uid)]]
