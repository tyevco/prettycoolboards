"""JLCPCB pick-and-place: per-part rotation/origin corrections and the CPL writer.

JLC places every part with its own (EasyEDA/LCSC) footprint. Where that footprint's
zero orientation or origin differs from the KiCad one, a CPL that copies KiCad's
angle places the part rotated (often by 180°, which still fits the pads) or
offset. For each LCSC code this module fetches the EasyEDA footprint and fits its
pads to the KiCad library footprint by pad number. It then caches
{rotation α, origin (dx, dy) in KiCad footprint coordinates} in
hardware/design/jlc_offsets.json and writes the CPL with
  top:    angle = (θ + α) mod 360
  bottom: angle = (180 − θ + α) mod 360          (same convention as kicad-jlcpcb-tools)
and the JLC origin transformed onto the board.

Every CPL row is then checked by simulating JLC's placement: the EasyEDA pads (cached with the correction) are put down
at the row's point and angle, and each must land on KiCad copper, on the same-numbered pad wherever both footprints use
that number. A row that fails stops the release; "renumber_ok" in an entry accepts a part whose two numberings differ
by design (the tactile switch numbers its paired pads 1,1,2,2 in KiCad and 1-4 in EasyEDA).

Source of the EasyEDA data: JLCEDA/EasyEDA Official Library (https://lceda.cn/, https://easyeda.com), copyright
JLCEDA/EasyEDA; jlc_offsets.json carries the same notice.
"""

from __future__ import annotations

import csv
import json
import math
import os
import urllib.error
import urllib.request

import pcbnew

EE_URL = "https://easyeda.com/api/products/{code}/components?version=6.4.19.5"
EE_UNIT = 0.254  # EasyEDA canvas unit (10 mil) in mm
HERE = os.path.dirname(os.path.abspath(__file__))
OFFSETS = os.path.join(os.path.dirname(HERE), "design", "jlc_offsets.json")
_LIB_CACHE = {}


def _ee_pads(code):
    import time
    req = urllib.request.Request(EE_URL.format(code=code), headers={"User-Agent": "Mozilla/5.0 (dial-me-spinner jlc_cpl)"})
    for attempt in range(6):  # the EasyEDA API rate-limits with HTTP 403; back off and retry
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.load(r)
            if "result" not in d:
                raise LookupError(f"EasyEDA: {d.get('message', 'no result')} ({d.get('code', '?')})")
            d = d["result"]
            break
        except urllib.error.HTTPError as e:
            if e.code != 403 or attempt == 5:
                raise
            time.sleep(3 * (attempt + 1))
    time.sleep(0.7)
    ds = d["packageDetail"]["dataStr"]
    ox, oy = float(ds["head"]["x"]), float(ds["head"]["y"])
    pads = {}
    for s in ds["shape"]:
        if s.startswith("PAD~"):
            f = s.split("~")
            pads.setdefault(f[8], []).append(((float(f[2]) - ox) * EE_UNIT, (float(f[3]) - oy) * EE_UNIT))
    return d["packageDetail"].get("title", ""), pads


def _rot(p, a):
    a = math.radians(a)
    x, y = p
    return (x * math.cos(a) + y * math.sin(a), -x * math.sin(a) + y * math.cos(a))


def _centroid(pts):
    return (sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts))


def _lib_footprint(fp, lib_dirs):
    nick = str(fp.GetFPID().GetLibNickname())
    name = str(fp.GetFPID().GetLibItemName())
    path = lib_dirs.get(nick, f"/usr/share/kicad/footprints/{nick}.pretty")
    if (path, name) not in _LIB_CACHE:  # FootprintLoad re-parses the library and leaks: load each once
        _LIB_CACHE[(path, name)] = pcbnew.FootprintLoad(path, name)
    return _LIB_CACHE[(path, name)]


def fit(code, lib_fp):
    """Best rotation (0/90/180/270) and EE origin in KiCad-local mm, by pad-number fitting."""
    title, ep = _ee_pads(code)
    kp = {}
    for p in lib_fp.Pads():
        if p.GetNumber():
            v = p.GetPosition()
            kp.setdefault(p.GetNumber(), []).append((pcbnew.ToMM(v.x), pcbnew.ToMM(v.y)))
    common = [n for n in kp if n in ep]
    if len(common) < 2:
        return None
    K = {n: _centroid(kp[n]) for n in common}
    E = {n: _centroid(ep[n]) for n in common}
    best = None
    for a in (0, 90, 180, 270):
        Er = {n: _rot(E[n], a) for n in common}
        tx = sum(K[n][0] - Er[n][0] for n in common) / len(common)
        ty = sum(K[n][1] - Er[n][1] for n in common) / len(common)
        rms = math.sqrt(sum((K[n][0] - Er[n][0] - tx) ** 2 + (K[n][1] - Er[n][1] - ty) ** 2 for n in common) / len(common))
        if best is None or rms < best["rms"]:
            best = {"rot": a, "dx": round(tx, 3), "dy": round(ty, 3), "rms": round(rms, 3)}
    best.update(title=title, matched=len(common), kicad_pads=len(kp), ee_pads=len(ep),
                footprint=str(lib_fp.GetFPID().GetLibItemName()), ee=_ee_list(ep))
    return best


def _ee_list(ep):
    """EasyEDA pad centres as [[number, x, y], ...] (EasyEDA footprint origin, mm, y down) for the placement check."""
    return [[n, round(x, 4), round(y, 4)] for n in sorted(ep) for x, y in ep[n]]


def update_offsets(board_paths, lib_dirs, refresh=False):
    table = json.load(open(OFFSETS)) if os.path.exists(OFFSETS) else {}
    for path in board_paths:
        b = pcbnew.LoadBoard(path)
        for fp in b.GetFootprints():
            code = fp.GetFieldText("LCSC") if fp.HasFieldByName("LCSC") else ""
            if not code or fp.IsDNP():
                continue
            if code in table and "rot" in table[code] and not refresh:
                if "ee" not in table[code] and "ee_error" not in table[code]:  # older entries: add the pads only
                    try:
                        table[code]["ee"] = _ee_list(_ee_pads(code)[1])
                    except Exception as e:  # noqa: BLE001 — e.g. no EasyEDA footprint for the code
                        table[code]["ee_error"] = str(e)
                continue
            try:
                r = fit(code, _lib_footprint(fp, lib_dirs))
            except Exception as e:  # noqa: BLE001 — network or parse problem: record it
                r = {"error": str(e)}
            table[code] = r or {"error": "no common pads"}
    save_offsets(table)
    return table


def save_offsets(table):
    """Write the table with each part's EasyEDA pad list on one line."""
    tmp = {c: dict(e, ee=f"@@ee:{c}@@") if "ee" in e else e for c, e in sorted(table.items())}
    txt = json.dumps(tmp, indent=1)
    for c, e in table.items():
        if "ee" in e:
            txt = txt.replace(f'"@@ee:{c}@@"', json.dumps(e["ee"], separators=(",", ":")))
    with open(OFFSETS, "w") as f:
        f.write(txt + "\n")


def _local_to_board(fp, lx, ly):
    """Library-local point (mm) -> board (mm): rotate by the footprint orientation, mirroring local y on the bottom
    (KiCad flips top/bottom about the x axis). Exact for any footprint, including repeated pad numbers."""
    s_ = -1 if fp.IsFlipped() else 1
    rx, ry = _rot((lx, s_ * ly), fp.GetOrientationDegrees())
    pos = fp.GetPosition()
    return pcbnew.ToMM(pos.x) + rx, pcbnew.ToMM(pos.y) + ry


def _check_transform(fp, lib_fp):
    """Largest distance from a transformed library pad to the nearest board pad (proves _local_to_board for this part)."""
    worst = 0.0
    bp = [(pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y)) for p in fp.Pads()]
    for p in lib_fp.Pads():
        q = _local_to_board(fp, pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y))
        worst = max(worst, min(math.dist(q, b_) for b_ in bp))
    return worst


def simulate(fp, mid_xy_board, angle, ee):
    """Put the EasyEDA pads down the way JLC does at a CPL point/angle: top R(A)·e, bottom R(−A)·mirror_x(e) (the angle
    is seen from the bottom, X/Y stay in the top view). Returns [(ee_number, kicad_pad_number or None, distance mm)]."""
    out = []
    pads = [p for p in fp.Pads() if p.IsOnCopperLayer()]  # not paste-only apertures
    for num, ex, ey in ee:
        e = (-ex, ey) if fp.IsFlipped() else (ex, ey)
        rx, ry = _rot(e, -angle if fp.IsFlipped() else angle)
        q = (mid_xy_board[0] + rx, mid_xy_board[1] + ry)
        v = pcbnew.VECTOR2I(pcbnew.FromMM(q[0]), pcbnew.FromMM(q[1]))
        hits = [p for p in pads if p.HitTest(v)]  # coincident pads (USB-C A1/B12): prefer the same number
        hit = next((p for p in hits if p.GetNumber() == num), hits[0] if hits else None)
        near = min(math.dist(q, (pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y))) for p in pads)
        out.append((num, hit.GetNumber() if hit is not None else None, round(near, 3)))
    return out


def write_cpl(pcb_path, out_csv, lib_dirs, strict=True):
    table = json.load(open(OFFSETS)) if os.path.exists(OFFSETS) else {}
    b = pcbnew.LoadBoard(pcb_path)
    org = b.GetDesignSettings().GetAuxOrigin()
    ox, oy = pcbnew.ToMM(org.x), pcbnew.ToMM(org.y)
    rows, missing, problems, notes = [], [], [], []
    for fp in sorted(b.GetFootprints(), key=lambda f: f.GetReference()):
        attrs = fp.GetAttributes()
        if fp.IsDNP() or attrs & pcbnew.FP_EXCLUDE_FROM_POS_FILES or attrs & pcbnew.FP_EXCLUDE_FROM_BOM:
            continue
        code = fp.GetFieldText("LCSC") if fp.HasFieldByName("LCSC") else ""
        corr = table.get(code, {})
        if "rot" not in corr:
            missing.append(f"{fp.GetReference()} ({code or 'no LCSC'})")
            corr = {"rot": 0, "dx": 0.0, "dy": 0.0}
        th = fp.GetOrientationDegrees()
        bottom = fp.IsFlipped()
        ang = ((180 - th) if bottom else th) + corr["rot"]
        ang = round(ang % 360, 2)
        lib_fp = _lib_footprint(fp, lib_dirs)
        ref = fp.GetReference()
        if _check_transform(fp, lib_fp) > 0.005:
            problems.append(f"{ref}: library-to-board transform does not reproduce the board pads")
        x, y = _local_to_board(fp, corr.get("dx", 0.0), corr.get("dy", 0.0))
        mx, my = round(x - ox, 4) + 0.0, round(oy - y, 4) + 0.0  # + 0.0: no "-0.0000"
        rows.append([ref, f"{mx:.4f}mm", f"{my:.4f}mm", "Bottom" if bottom else "Top", f"{ang:g}"])
        if corr.get("ee"):  # simulate JLC's placement from the row exactly as written
            res = simulate(fp, (ox + mx, oy - my), ang, corr["ee"])
            off = [r for r in res if r[1] is None]
            if off:
                problems.append(f"{ref} ({code}): {len(off)}/{len(res)} JLC pads land off copper "
                                f"(nearest pad up to {max(r[2] for r in off):.2f} mm away)")
            knums = {p.GetNumber() for p in fp.Pads() if p.IsOnCopperLayer()}
            renum = sorted({f"{r[0]}->{r[1]}" for r in res if r[1] is not None and r[0] != r[1]})
            # a pad name both footprints use, landing on another pad: the part is turned or mirrored (a symmetric
            # package still lands on copper, so this is the only sign of e.g. a 180-degree SOT-23-6)
            swapped = sorted({f"{r[0]}->{r[1]}" for r in res if r[1] is not None and r[0] != r[1] and r[0] in knums})
            if swapped and not corr.get("renumber_ok"):
                problems.append(f"{ref} ({code}): JLC pads land on other-numbered KiCad pads: " + ", ".join(swapped[:8]))
            elif renum:
                notes.append(f"{ref} ({code}): JLC pad numbers land on differently numbered KiCad pads: "
                             + ", ".join(renum[:8]) + (" ..." if len(renum) > 8 else ""))
        elif "rot" in corr:
            notes.append(f"{ref} ({code}): no EasyEDA pad data, placement not simulated")
    if missing and strict:
        raise RuntimeError("no JLC rotation/origin correction for: " + ", ".join(missing))
    if problems and strict:
        raise RuntimeError("JLC placement check failed:\n  " + "\n  ".join(problems))
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        w.writerows(rows)
    return out_csv, missing, problems, notes
