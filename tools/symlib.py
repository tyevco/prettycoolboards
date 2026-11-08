"""Load KiCad symbols (flattening `extends`) and expose pin geometry."""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass

import sexpr
from sexpr import Q, find, find_all

KICAD_SYMBOL_DIR = os.environ.get("KICAD9_SYMBOL_DIR", "/usr/share/kicad/symbols")

_lib_cache: dict[str, list] = {}
_extra_libs: dict[str, str] = {}


def register_library(nickname: str, path: str) -> None:
    """Register a project symbol library (nickname -> .kicad_sym path)."""
    _extra_libs[nickname] = path
    _lib_cache.pop(nickname, None)


def _load_lib(nick: str) -> list:
    if nick not in _lib_cache:
        path = _extra_libs.get(nick) or os.path.join(KICAD_SYMBOL_DIR, nick + ".kicad_sym")
        with open(path, encoding="utf-8") as f:
            _lib_cache[nick] = sexpr.parse(f.read())
    return _lib_cache[nick]


def _raw_symbol(nick: str, name: str) -> list:
    for sym in find_all(_load_lib(nick), "symbol"):
        if sym[1] == name:
            return sym
    raise KeyError(f"symbol {nick}:{name} not found")


def _flatten(nick: str, name: str) -> list:
    sym = copy.deepcopy(_raw_symbol(nick, name))
    ext = find(sym, "extends")
    if not ext:
        return sym
    parent = _flatten(nick, ext[1])
    out = [x for x in parent if not (isinstance(x, list) and x and x[0] in ("property", "symbol"))]
    out[1] = Q(name)
    # child properties win; keep parent properties the child does not define
    child_props = {p[1]: p for p in find_all(sym, "property")}
    props = [child_props.pop(p[1], p) for p in find_all(parent, "property")] + list(child_props.values())
    units = []
    for u in find_all(parent, "symbol"):
        u = copy.deepcopy(u)
        suffix = u[1][len(parent[1]):]
        u[1] = Q(name + suffix)
        units.append(u)
    # insert props + units after the leading flags of the parent
    head = [x for x in out if not isinstance(x, list) or x[0] != "embedded_fonts"]
    tail = [x for x in out if isinstance(x, list) and x[0] == "embedded_fonts"]
    return head + props + units + tail


@dataclass
class Pin:
    number: str
    name: str
    etype: str
    x: float          # connection point, symbol coords (Y up)
    y: float
    angle: int        # direction from connection point into the body
    length: float
    unit: int
    hidden: bool


class Symbol:
    def __init__(self, lib_id: str):
        self.lib_id = lib_id
        nick, name = lib_id.split(":", 1)
        self.nick, self.name = nick, name
        self.sexp = _flatten(nick, name)
        self.pins: list[Pin] = []
        for u in find_all(self.sexp, "symbol"):
            unit = int(str(u[1]).rsplit("_", 2)[-2])
            for p in find_all(u, "pin"):
                at = find(p, "at")
                hidden = any(x == "hide" or (isinstance(x, list) and x[0] == "hide" and x[1:] == ["yes"]) for x in p)
                self.pins.append(Pin(
                    number=str(find(p, "number")[1]),
                    name=str(find(p, "name")[1]),
                    etype=str(p[1]),
                    x=float(at[1]), y=float(at[2]), angle=int(float(at[3])),
                    length=float(find(p, "length")[1]),
                    unit=unit, hidden=hidden,
                ))
        self.is_power = find(self.sexp, "power") is not None
        self.unit_count = max([p.unit for p in self.pins] + [1])

    def prop(self, key: str) -> str:
        for p in find_all(self.sexp, "property"):
            if p[1] == key:
                return str(p[2])
        return ""

    def pins_for_unit(self, unit: int) -> list[Pin]:
        return [p for p in self.pins if p.unit in (0, unit)]

    def bbox(self, unit: int = 1):
        """Approximate body bbox (symbol coords) from pins and graphics."""
        xs, ys = [], []
        for p in self.pins_for_unit(unit):
            xs.append(p.x); ys.append(p.y)
        for u in find_all(self.sexp, "symbol"):
            un = int(str(u[1]).rsplit("_", 2)[-2])
            if un not in (0, unit):
                continue
            for g in u[2:]:
                if not isinstance(g, list):
                    continue
                for key in ("start", "end", "center", "at"):
                    pt = find(g, key)
                    if pt and g[0] != "pin":
                        xs.append(float(pt[1])); ys.append(float(pt[2]))
                pts = find(g, "pts")
                if pts:
                    for xy in pts[1:]:
                        xs.append(float(xy[1])); ys.append(float(xy[2]))
        if not xs:
            return (-2.54, -2.54, 2.54, 2.54)
        return (min(xs), min(ys), max(xs), max(ys))

    def pin(self, key: str) -> list[Pin]:
        """Pins matching a number, or a unique pin name."""
        by_num = [p for p in self.pins if p.number == key]
        if by_num:
            return by_num
        by_name = [p for p in self.pins if p.name == key]
        if by_name:
            return by_name
        raise KeyError(f"{self.lib_id}: no pin {key!r}")

    def embedded(self) -> list:
        """The symbol as embedded in a schematic's lib_symbols."""
        s = copy.deepcopy(self.sexp)
        s[1] = Q(self.lib_id)
        return s


_sym_cache: dict[str, Symbol] = {}


def get(lib_id: str) -> Symbol:
    if lib_id not in _sym_cache:
        _sym_cache[lib_id] = Symbol(lib_id)
    return _sym_cache[lib_id]
