"""Minimal S-expression reader/writer for KiCad files.

Atoms are kept as Python str. Quoted strings are wrapped in `Q` so they
round-trip with quotes; bare symbols/numbers stay plain `str`.
"""

from __future__ import annotations


class Q(str):
    """A quoted string atom."""


def parse(text: str):
    """Parse one top-level S-expression into nested lists."""
    pos = 0
    n = len(text)
    stack: list[list] = []
    root = None
    while pos < n:
        c = text[pos]
        if c in " \t\r\n":
            pos += 1
        elif c == "(":
            stack.append([])
            pos += 1
        elif c == ")":
            node = stack.pop()
            if stack:
                stack[-1].append(node)
            else:
                root = node
            pos += 1
        elif c == '"':
            pos += 1
            buf = []
            while True:
                ch = text[pos]
                if ch == "\\":
                    buf.append(text[pos + 1])
                    pos += 2
                elif ch == '"':
                    pos += 1
                    break
                else:
                    buf.append(ch)
                    pos += 1
            stack[-1].append(Q("".join(buf)))
        else:
            start = pos
            while pos < n and text[pos] not in " \t\r\n()":
                pos += 1
            stack[-1].append(text[start:pos])
    return root


def _atom(a) -> str:
    if isinstance(a, Q):
        return '"' + a.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'
    if isinstance(a, bool):
        return "yes" if a else "no"
    if isinstance(a, float):
        s = f"{a:.4f}".rstrip("0").rstrip(".")
        return "0" if s in ("-0", "") else s
    return str(a)


# Lists whose children are written on one line (short, leaf-ish nodes).
_INLINE = {"at", "xy", "size", "start", "end", "mid", "center", "length", "width", "type", "color",
           "offset", "thickness", "diameter", "uuid", "unit", "lib_id", "reference", "page",
           "in_bom", "on_board", "dnp", "exclude_from_sim", "fields_autoplaced", "mirror",
           "justify", "hide", "bold", "italic", "version", "generator", "generator_version",
           "paper", "convert", "radius", "pts_inline", "embedded_fonts", "in_pos_files",
           "duplicate_pin_numbers_are_jumpers", "extends", "power"}


def dumps(node, indent: int = 0) -> str:
    if not isinstance(node, list):
        return _atom(node)
    head = node[0] if node else ""
    simple = all(not isinstance(x, list) for x in node)
    if simple and (head in _INLINE or len(node) <= 4):
        return "(" + " ".join(_atom(x) for x in node) + ")"
    if head == "pts":
        return "(pts " + " ".join(dumps(x) for x in node[1:]) + ")"
    pad = "\t" * (indent + 1)
    parts = []
    line = "(" + " ".join(_atom(x) for x in _leading_atoms(node))
    rest = node[len(_leading_atoms(node)):]
    for child in rest:
        parts.append("\n" + pad + dumps(child, indent + 1))
    return line + "".join(parts) + "\n" + "\t" * indent + ")"


def _leading_atoms(node):
    out = []
    for x in node:
        if isinstance(x, list):
            break
        out.append(x)
    return out


def find(node, head):
    """First direct child list with the given head."""
    for x in node:
        if isinstance(x, list) and x and x[0] == head:
            return x
    return None


def find_all(node, head):
    return [x for x in node if isinstance(x, list) and x and x[0] == head]
