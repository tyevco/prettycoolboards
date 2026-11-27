#!/usr/bin/env python3
"""Make the descriptor EEPROM image of each coupon from its JSON (keyboard/tools/coupon/descriptors/<board>.json).

usage:
    python keyboard/tools/coupon/make_eeprom.py                       # every descriptor, serial 0
    python keyboard/tools/coupon/make_eeprom.py test-coupon --serial 1-4
    python keyboard/tools/coupon/make_eeprom.py --check build/eeprom/test-coupon-s0001.bin    # decode, verify
    options: --out DIR (default keyboard/tools/coupon/build/eeprom, git-ignored), --date YYYY-MM-DD,
             --git HASH|auto|none, --no-placeholder (refuse placeholder descriptors), --shell DEVICE,
             --kicad-dir DIR, --no-board-check (descriptor rules only)

For each board and serial it writes <board>-s<serial>.bin (the 256 raw bytes), .hex (Intel HEX, for a CH341A-class
programmer's software) and .json (the image decoded again: what the firmware will see). With --shell DEVICE it also
writes .shell: Zephyr eeprom-shell commands (`eeprom write DEVICE OFFSET b0 ... b15`, one 16-byte page each, the
M24C02's page) to paste into the board's console, if the firmware enables CONFIG_EEPROM_SHELL.

Before writing, it runs the coupon rules and refuses an image with a FAIL: the descriptor-only rules always (budgets
against SPEC §4.9 and the switch trip points, slot compatibility, I2C addresses, SPI and G-line roles), and, when the
board is generated under keyboard/hardware/kicad/<board>/, the netlist rules too (`uses`, R_src, the reference
ratios, bulk capacitance: the descriptor against the design it describes) and the board rules if pcbnew can be
imported (it says when it cannot). --no-board-check skips the generated files (a bench machine without them).

"git": "auto" in a JSON resolves to the last commit that touched keyboard/hardware/kicad/<board>/ or
keyboard/hardware/fab/<board>/ (read-only git); the git_dirty flag is set when either has uncommitted or untracked
changes, or when nothing there is committed yet (then the hash is HEAD's). A placeholder descriptor's image carries the placeholder flag, so the
firmware can show that its values are not a board's.

Status: images are produced and decoded on the host only; none has been written to an EEPROM.
"""

from __future__ import annotations

import argparse
import datetime
import glob
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True        # before the imports below: no __pycache__ in the tree
sys.path.insert(0, HERE)

import descriptor as D  # noqa: E402

DESC_DIR = os.path.join(HERE, "descriptors")
OUT_DIR = os.path.join(HERE, "build", "eeprom")
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))


def _git(*args):
    try:
        out = subprocess.run(["git", "-C", REPO, *args], check=True, capture_output=True, text=True, timeout=30)
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def resolve_git(board):
    """(hash, dirty) for a board's generated files (its KiCad project and its fab outputs); (None, True) without
    git."""
    paths = [f"keyboard/hardware/kicad/{board}", f"keyboard/hardware/fab/{board}"]
    h = _git("log", "-1", "--format=%H", "--", *paths)
    dirty = bool(_git("status", "--porcelain", "--", *paths))
    if not h:
        h, dirty = _git("rev-parse", "HEAD"), True
    return h, dirty


def _show(path):
    """A path as typed: relative when it is under the working directory, else absolute."""
    rel = os.path.relpath(path)
    return path if rel.startswith("..") else rel


def parse_serials(spec):
    out = []
    for part in str(spec).split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            out += list(range(int(a, 0), int(b, 0) + 1))
        elif part:
            out.append(int(part, 0))
    return out


def intel_hex(data, rec=16):
    lines = []
    for off in range(0, len(data), rec):
        chunk = data[off:off + rec]
        body = bytes([len(chunk), off >> 8 & 0xFF, off & 0xFF, 0]) + chunk
        lines.append(":" + body.hex().upper() + f"{(-sum(body)) & 0xFF:02X}")
    lines.append(":00000001FF")
    return "\n".join(lines) + "\n"


def read_intel_hex(text):
    mem = {}
    for ln in text.split():
        raw = bytes.fromhex(ln[1:])
        n, addr, typ = raw[0], raw[1] << 8 | raw[2], raw[3]
        if sum(raw) & 0xFF:
            raise ValueError(f"bad checksum in {ln}")
        if typ == 1:
            break
        for i, b in enumerate(raw[4:4 + n]):
            mem[addr + i] = b
    return bytes(mem[i] for i in range(len(mem)))


def shell_script(data, device):
    """Zephyr eeprom-shell commands, one M24C02 page (16 bytes) per command, aligned to pages."""
    out = [f"# {len(data)} bytes to {device}, {D.PAGE_SIZE}-byte pages (drivers/eeprom/eeprom_shell.c)"]
    for off in range(0, len(data), D.PAGE_SIZE):
        out.append(f"eeprom write {device} 0x{off:02X} " +
                   " ".join(f"0x{b:02X}" for b in data[off:off + D.PAGE_SIZE]))
    out.append(f"eeprom read {device} 0 {len(data)}")
    return "\n".join(out) + "\n"


def build(desc, board, serial=0, date=None, git=None):
    """A JSON descriptor -> (image bytes, the JSON as encoded). git: None = the JSON's ('auto' resolves)."""
    d = dict(desc)
    d["serial"] = serial
    if date:
        d["date"] = date
    g = git if git is not None else d.get("git", "auto")
    flags = [f for f in d.get("flags", []) if f != "git_dirty"]
    if str(g).lower() == "auto":
        h, dirty = resolve_git(board)
        d["git"] = h or ""
        if dirty:
            flags.append("git_dirty")
    elif str(g).lower() == "none":
        d["git"] = ""
    else:
        d["git"] = g
    d["flags"] = flags
    return D.encode(d), d


def _coupon(rules, board, desc, path, a):
    """The rules' Coupon for a board: its generated netlist (and board, with pcbnew) when they exist."""
    import coupon_model as M
    kdir = a.kicad_dir or M.KICAD_DIR
    net_path, pcb_path = M.board_files(board, kdir)
    if a.no_board_check or not os.path.exists(net_path):
        why = "--no-board-check" if a.no_board_check else f"not generated under {_show(kdir)}"
        return rules.Coupon(board, desc=desc, desc_path=path), f"descriptor rules only ({why})"
    net = M.read_netlist(net_path)
    board_m, geo, note = None, None, None
    if os.path.exists(pcb_path):
        try:
            geo = M.load_geometry()
            board_m = M.read_board(pcb_path, geo)
        except ImportError:
            note = "pcbnew is not importable here: netlist rules run, board rules do not"
    return rules.Coupon(board, net, board_m, desc, path, geo), note


def main(argv=None):
    ap = argparse.ArgumentParser(description="Make coupon descriptor EEPROM images")
    ap.add_argument("boards", nargs="*", help="board names (default: every descriptors/*.json)")
    ap.add_argument("--serial", default="0", help="serial number(s): 7, 1-4 or 1,3,9 (default 0: unassigned)")
    ap.add_argument("--out", default=OUT_DIR)
    ap.add_argument("--desc-dir", default=DESC_DIR)
    ap.add_argument("--date", help="YYYY-MM-DD written into the image (default: the JSON's date)")
    ap.add_argument("--today", action="store_true", help="use today's date")
    ap.add_argument("--git", help="commit hash, 'auto' (default: the JSON's) or 'none'")
    ap.add_argument("--no-placeholder", action="store_true", help="refuse descriptors marked placeholder")
    ap.add_argument("--shell", metavar="DEVICE", help="also write Zephyr eeprom-shell commands for DEVICE")
    ap.add_argument("--check", nargs="+", metavar="IMAGE", help="decode and verify images (.bin or .hex) instead")
    ap.add_argument("--kicad-dir", help="where the generated boards are (default keyboard/hardware/kicad)")
    ap.add_argument("--no-board-check", action="store_true",
                    help="run only the descriptor rules, not the generated netlist and board")
    a = ap.parse_args(argv)

    if a.check:
        bad = 0
        for path in a.check:
            with open(path, "rb") as fh:
                raw = fh.read()
            if path.endswith(".hex"):
                raw = read_intel_hex(raw.decode())
            try:
                d = D.decode(raw)
                print(f"{path}: OK, format {d['format']}, {d['type']} rev {d['rev']} serial {d['serial']}, "
                      f"git {d['git']}{' (dirty)' if 'git_dirty' in d['flags'] else ''}"
                      f"{', PLACEHOLDER' if 'placeholder' in d['flags'] else ''}")
            except D.DescriptorError as e:
                bad += 1
                print(f"{path}: {e}")
        return 1 if bad else 0

    import rules                                       # the descriptor-only rules (no KiCad needed)

    paths = ([os.path.join(a.desc_dir, f"{b}.json") for b in a.boards] if a.boards
             else sorted(glob.glob(os.path.join(a.desc_dir, "*.json"))))
    date = datetime.date.today().isoformat() if a.today else a.date
    serials = parse_serials(a.serial)
    os.makedirs(a.out, exist_ok=True)
    failed = 0
    rows = []
    for path in paths:
        board = os.path.splitext(os.path.basename(path))[0]
        if not os.path.exists(path):
            print(f"{board}: no descriptor {path}")
            failed += 1
            continue
        desc = D.load_json(path)
        c, note = _coupon(rules, board, desc, path, a)
        rep = rules.check(c) if c.net is not None else rules.Report(board)
        if c.net is None:
            rules.check_descriptor(c, rep)
        if note:
            print(f"{board}: {note}")
        fails = [(ru, det) for ru, res, det in rep.rows if res == "FAIL"]
        if fails:
            failed += 1
            print(f"{board}: REFUSED, the descriptor breaks the coupon rules:")
            for ru, det in fails:
                print(f"  {ru}: {det}")
            continue
        if a.no_placeholder and (desc.get("placeholder") or "placeholder" in (desc.get("flags") or [])):
            failed += 1
            print(f"{board}: REFUSED, the descriptor is marked placeholder (--no-placeholder)")
            continue
        for serial in serials:
            try:
                img, used = build(desc, board, serial, date, a.git)
            except D.DescriptorError as e:
                failed += 1
                print(f"{board}: {e}")
                break
            stem = os.path.join(a.out, f"{board}-s{serial:04d}")
            with open(stem + ".bin", "wb") as fh:
                fh.write(img)
            with open(stem + ".hex", "w", encoding="ascii", newline="\n") as fh:
                fh.write(intel_hex(img))
            with open(stem + ".json", "w", encoding="utf-8", newline="\n") as fh:
                fh.write(D.dump_json(D.decode(img)))
            if a.shell:
                with open(stem + ".shell", "w", encoding="ascii", newline="\n") as fh:
                    fh.write(shell_script(img, a.shell))
            crc = int.from_bytes(img[D.CRC_OFFSET:], "little")
            k = D.decode(img)
            rows.append((_show(stem + ".bin"), k["type"], k["rev"], serial, k["git"][:12],
                         ",".join(k["flags"]) or "-", f"0x{crc:08X}"))
    if rows:
        w = [max(len(str(r[i])) for r in rows + [("image", "type", "rev", "serial", "git", "flags", "crc")])
             for i in range(7)]
        hdr = ("image", "type", "rev", "serial", "git", "flags", "crc")
        print("  ".join(f"{h:<{w[i]}}" for i, h in enumerate(hdr)))
        for r in rows:
            print("  ".join(f"{str(v):<{w[i]}}" for i, v in enumerate(r)))
    print(f"{len(rows)} image(s) in {_show(a.out)}" + (f"; {failed} refused" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
