"""PROTOCOL.md read as data: its record templates, error tokens, event kinds and findings (for the conformance
tests of the simulator and of the firmware's own output)."""

import re

from tbbench import limits as L

PROTOCOL = L.REPO / "keyboard" / "firmware" / "bringup" / "PROTOCOL.md"


def text():
    return PROTOCOL.read_text(encoding="utf-8")


def templates():
    """record -> [(fixed keys in order, open)]: open when the template allows more keys ([...] or key=value ...)."""
    t = text()
    records = t.split("## Records", 1)[1].split("### Self-test steps", 1)[0]
    completion = t.split("## Completion", 1)[1].split("Error tokens:", 1)[0]
    events = t.split("## Events", 1)[1].split("| `kind=` |", 1)[0]
    out = {}
    for line in re.findall(r"^@tb (.+)$", records + completion + events, re.M):
        words = line.split()
        name, rest = words[0], words[1:]
        keys, open_ = [], False
        for w in rest:
            if w.startswith("[") or w in ("...", "key=value"):
                open_ = True
                break
            m = re.match(r"([a-z0-9_]+)=", w)
            if m:
                keys.append(m.group(1))
        out.setdefault(name, []).append((tuple(keys), open_))
    return out


def conforms(rec, tmpl):
    """None if the record matches one of its templates, else why not."""
    forms = tmpl.get(rec.name)
    if not forms:
        return f"record {rec.name!r} is not in PROTOCOL.md"
    keys = tuple(rec.fields)
    for fixed, open_ in forms:
        if keys == fixed or (open_ and keys[:len(fixed)] == fixed):
            return None
    return f"{rec.name}: keys {keys} match none of {[f for f, _ in forms]}"


def error_tokens():
    sect = text().split("Error tokens:", 1)[1].split("## Names", 1)[0]
    toks = set()
    for row in re.findall(r"^\| (.+?) \|", sect, re.M):
        toks |= set(re.findall(r"`([a-z0-9_]+)`", row))
    return toks


def event_kinds():
    sect = text().split("## Events", 1)[1]
    return set(re.findall(r"^\| `([a-z_]+)` \|", sect, re.M))


def findings():
    sect = text().split("Findings (`trip finding=`", 1)[1].split("##", 1)[0]
    return set(re.findall(r"`([a-z0-9_]+)`", sect)) - {"tb", "trip"}


def rail_off_reasons():
    m = re.search(r"\| `rail_off` \| `rail= reason=([^`]+)`", text())
    return set(m.group(1).replace("\\|", "|").split("|")) if m else set()
