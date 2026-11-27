#!/usr/bin/env python3
"""hid8k_measure: read the hid8k firmware's vendor stats reports and judge the 8 kHz run.

Opens the vendor collection (usage page 0xFF00) of the hid8k device by VID/PID, reads for
--duration seconds (default 600), then writes a JSON result and prints a one-screen summary with
PASS/FAIL against the criteria in README.md. Optionally keeps the firmware's CDC ACM console open
and logged during the run (--cdc), in normal or heavy traffic mode, as the test procedure asks.

Backends:
  hidapi  (default on Windows and macOS) the 'hid' Python package (pyhidapi, ctypes) or the
          'hidapi' package (cython-hidapi); both import as "hid".
  hidraw  (default on Linux) reads /dev/hidrawN directly; no Python package needed.

The analysis lives in hid8k_analysis.py (pure functions, covered by pytest).

VID/PID 1209:0001 is the pid.codes test PID: not unique, for private bench testing only.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import gc
import glob
import json
import multiprocessing as mp
import os
import platform
import sys
import time
from typing import Optional

import hid8k_analysis as ha

DEFAULT_VID = 0x1209
DEFAULT_PID = 0x0001
EDGE_MARGIN_S = 1.0


def _int(s: str) -> int:
    return int(s, 0)


# ----------------------------------------------------------------------------- Linux sysfs


def _read(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="ascii", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return None


def linux_usb_info(vid: int, pid: int) -> list:
    """Bus speed and the HID interrupt IN endpoint's bInterval, from /sys/bus/usb/devices."""
    found = []
    for dev in sorted(glob.glob("/sys/bus/usb/devices/*")):
        if _read(os.path.join(dev, "idVendor")) != f"{vid:04x}":
            continue
        if _read(os.path.join(dev, "idProduct")) != f"{pid:04x}":
            continue
        info = {"sysfs": dev, "speed_mbps": _read(os.path.join(dev, "speed")),
                "serial": _read(os.path.join(dev, "serial")),
                "product": _read(os.path.join(dev, "product")), "hid_in_endpoints": []}
        for intf in sorted(glob.glob(dev + ":*")):
            if _read(os.path.join(intf, "bInterfaceClass")) != "03":
                continue
            for ep in sorted(glob.glob(os.path.join(intf, "ep_*"))):
                if (_read(os.path.join(ep, "type")) == "Interrupt"
                        and _read(os.path.join(ep, "direction")) == "in"):
                    info["hid_in_endpoints"].append({
                        "endpoint": os.path.basename(ep),
                        "bInterval": _read(os.path.join(ep, "bInterval")),
                        "interval": _read(os.path.join(ep, "interval")),
                        "wMaxPacketSize": _read(os.path.join(ep, "wMaxPacketSize")),
                    })
        found.append(info)
    return found


def find_hidraw(vid: int, pid: int) -> list:
    """hidraw nodes whose HID_ID matches, and whether their report descriptor has the vendor page."""
    out = []
    want = f"{vid:08X}:{pid:08X}"
    for node in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        uevent = _read(os.path.join(node, "device", "uevent")) or ""
        hid_id = next((ln.split("=", 1)[1] for ln in uevent.splitlines()
                       if ln.startswith("HID_ID=")), "")
        if not hid_id.upper().endswith(want):
            continue
        try:
            with open(os.path.join(node, "device", "report_descriptor"), "rb") as f:
                rdesc = f.read()
        except OSError:
            rdesc = b""
        out.append({"path": "/dev/" + os.path.basename(node),
                    "vendor_page": b"\x06\x00\xff" in rdesc})
    return out


# ----------------------------------------------------------------------------- HID sources


class HidrawSource:
    """Linux: read the hidraw node directly (each read returns one report, report ID first)."""

    name = "hidraw"

    def __init__(self, path: str):
        import select  # noqa: PLC0415  (Linux-only path)

        self.path = path
        self.fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        self.poll = select.poll()
        self.poll.register(self.fd, select.POLLIN)

    def read(self, timeout_ms: int) -> bytes:
        try:
            return os.read(self.fd, 64)
        except BlockingIOError:
            if not self.poll.poll(timeout_ms):
                return b""
            try:
                return os.read(self.fd, 64)
            except BlockingIOError:
                return b""

    def close(self) -> None:
        os.close(self.fd)


class HidapiSource:
    """hidapi through either Python binding (both import as "hid")."""

    name = "hidapi"

    def __init__(self, path: bytes):
        import hid  # noqa: PLC0415

        self.path = path
        if hasattr(hid, "device"):  # 'hidapi' (cython-hidapi): read(max_length, timeout_ms) -> list
            self.dev = hid.device()
            self.dev.open_path(path)
            self._read = lambda t: bytes(self.dev.read(64, t))
            self.binding = "hidapi (cython-hidapi)"
        else:  # 'hid' (pyhidapi): hid.Device(path=...), read(size, timeout) -> bytes
            self.dev = hid.Device(path=path)
            self._read = lambda t: self.dev.read(64, t)
            self.binding = "hid (pyhidapi)"

    def read(self, timeout_ms: int) -> bytes:
        data = self._read(timeout_ms)
        return bytes(data) if data else b""

    def close(self) -> None:
        self.dev.close()


def hidapi_candidates(vid: int, pid: int, usage_page: int) -> list:
    import hid  # noqa: PLC0415

    devs = hid.enumerate(vid, pid)
    vendor = [d for d in devs if d.get("usage_page") == usage_page]
    # Older hidapi on Linux reports usage_page 0 for every interface: fall back to the interface.
    return vendor or devs


def open_source(args) -> object:
    backend = args.backend
    if backend == "auto":
        backend = "hidraw" if sys.platform.startswith("linux") else "hidapi"
    if backend == "hidraw":
        if args.path:
            return HidrawSource(args.path)
        nodes = find_hidraw(args.vid, args.pid)
        if not nodes:
            raise SystemExit(f"no hidraw node for {args.vid:04x}:{args.pid:04x} (is it plugged "
                             "in, enumerated, and is the udev rule installed?)")
        nodes.sort(key=lambda n: not n["vendor_page"])
        return HidrawSource(nodes[0]["path"])
    if args.path:
        return HidapiSource(args.path.encode())
    cands = hidapi_candidates(args.vid, args.pid, args.usage_page)
    if not cands:
        raise SystemExit(f"hidapi found no {args.vid:04x}:{args.pid:04x} device")
    return HidapiSource(cands[0]["path"])


# ----------------------------------------------------------------------------- CDC logger


def cdc_logger(port: str, seconds: float, mode: str, log_path: str, results, ready) -> None:
    """Separate process: keep the CDC console open, set the mode, log everything it sends."""
    try:
        import serial  # noqa: PLC0415  (pyserial)
    except ImportError:
        results.put({"error": "pyserial is not installed (pip install pyserial)"})
        ready.set()
        return
    out = {"port": port, "mode": mode, "log": log_path, "bytes": 0, "stats_lines": 0,
           "fill_lines": 0, "last_stats_line": None}
    try:
        ser = serial.Serial(port, 115200, timeout=0.2)
    except Exception as exc:  # noqa: BLE001  (report any open failure to the parent)
        out["error"] = f"cannot open {port}: {exc}"
        results.put(out)
        ready.set()
        return
    ser.write(b"\r\nreset\r\n" + (b"heavy\r\n" if mode == "heavy" else b"normal\r\n"))
    ser.flush()
    ready.set()
    t0 = time.monotonic()
    pending = b""
    with open(log_path, "wb") as log:
        while time.monotonic() - t0 < seconds:
            chunk = ser.read(65536)
            if not chunk:
                continue
            log.write(chunk)
            out["bytes"] += len(chunk)
            pending += chunk
            *lines, pending = pending.split(b"\n")
            for ln in lines:
                if ln.startswith(b"hid8k t="):
                    out["stats_lines"] += 1
                    out["last_stats_line"] = ln.decode("ascii", "replace").strip()
                elif ln.startswith(b"~fill"):
                    out["fill_lines"] += 1
    if mode == "heavy":
        ser.write(b"normal\r\n")
        ser.flush()
    ser.close()
    out["seconds"] = time.monotonic() - t0
    out["bytes_per_s"] = out["bytes"] / out["seconds"] if out["seconds"] else 0.0
    results.put(out)


# ----------------------------------------------------------------------------- main


def write_csv(path: str, rec: ha.Recorder) -> None:
    with open(path, "w", encoding="ascii", newline="\n") as f:
        f.write("arrival_ns,seq,t_submit,done_seq,t_done,submit_cost,kbd_count,fn_done,flags\n")
        for row in zip(rec.arrival_ns, rec.seq, rec.t_submit, rec.done_seq, rec.t_done,
                       rec.submit_cost, rec.kbd_count, rec.fn_done, rec.flags):
            f.write(",".join(str(v) for v in row) + "\n")


def list_devices(args) -> int:
    if sys.platform.startswith("linux"):
        print("hidraw:", json.dumps(find_hidraw(args.vid, args.pid), indent=1))
        print("usb:", json.dumps(linux_usb_info(args.vid, args.pid), indent=1))
    try:
        import hid  # noqa: PLC0415

        for d in hid.enumerate(args.vid, args.pid):
            print({k: d.get(k) for k in ("path", "usage_page", "usage", "interface_number",
                                         "product_string", "serial_number")})
    except ImportError:
        print("(no hid/hidapi Python package: hidapi listing skipped)")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--vid", type=_int, default=DEFAULT_VID)
    p.add_argument("--pid", type=_int, default=DEFAULT_PID)
    p.add_argument("--usage-page", type=_int, default=ha.VENDOR_USAGE_PAGE)
    p.add_argument("--duration", type=float, default=600.0, help="seconds to read (default 600)")
    p.add_argument("--warmup", type=float, default=1.0,
                   help="seconds of reports to discard first (stale queued reports)")
    p.add_argument("--backend", choices=("auto", "hidapi", "hidraw"), default="auto")
    p.add_argument("--path", help="device path (hidraw node, or hidapi path)")
    p.add_argument("--out", help="JSON result path (default hid8k_<UTC time>.json)")
    p.add_argument("--csv", help="also write every recorded report to this CSV")
    p.add_argument("--cdc", metavar="PORT", help="CDC console port to hold open and log")
    p.add_argument("--cdc-mode", choices=("normal", "heavy"), default="normal")
    p.add_argument("--cdc-log", help="CDC log path (default next to the JSON)")
    p.add_argument("--label", default="", help="free text stored in the JSON (host, port, hub...)")
    p.add_argument("--min-duration", type=float, default=ha.Criteria.min_duration_s)
    p.add_argument("--min-rate", type=float, default=ha.Criteria.min_rate)
    p.add_argument("--max-p999-us", type=float, default=ha.Criteria.max_p999_us)
    p.add_argument("--list", action="store_true", help="list matching devices and exit")
    args = p.parse_args(argv)

    if args.list:
        return list_devices(args)

    started = _dt.datetime.now(_dt.timezone.utc)
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    out_path = args.out or f"hid8k_{stamp}.json"
    criteria = ha.Criteria(min_duration_s=args.min_duration, min_rate=args.min_rate,
                           max_p999_us=args.max_p999_us)

    cdc_proc = cdc_results = None
    if args.cdc:
        cdc_log = args.cdc_log or os.path.splitext(out_path)[0] + "_cdc.log"
        cdc_results = mp.Queue()
        ready = mp.Event()
        cdc_proc = mp.Process(target=cdc_logger, daemon=True,
                              args=(args.cdc, args.duration + args.warmup + EDGE_MARGIN_S + 2.0,
                                    args.cdc_mode,
                                    cdc_log, cdc_results, ready))
        cdc_proc.start()
        ready.wait(10.0)
        time.sleep(0.5)  # let the firmware apply reset / mode before the HID window opens

    src = open_source(args)
    usb_info = linux_usb_info(args.vid, args.pid) if sys.platform.startswith("linux") else []
    rec = ha.Recorder(warmup_s=args.warmup)
    print(f"reading {getattr(src, 'path', '?')!r} via {src.name} for {args.duration:.0f} s "
          f"(+{args.warmup:.1f} s warm-up)...", flush=True)

    clock = time.perf_counter_ns
    # One second of margin, so the window after warm-up is not a hair short of --duration.
    end_ns = clock() + int((args.duration + args.warmup + EDGE_MARGIN_S) * 1e9)
    timeouts = 0
    reader_error = None
    gc.disable()  # a collector pause longer than ~8 ms would overflow the OS report buffer
    try:
        while True:
            data = src.read(100)
            now = clock()
            if data:
                rec.add(data, now)
            else:
                timeouts += 1
            if now >= end_ns:
                break
    except KeyboardInterrupt:
        reader_error = "interrupted by the operator"
        print("interrupted: analysing what was read", flush=True)
    except Exception as exc:  # noqa: BLE001  (unplug, reset: any binding's read error)
        reader_error = f"read failed: {type(exc).__name__}: {exc}"
        print(f"{reader_error}: analysing what was read", flush=True)
    finally:
        gc.enable()
        try:
            src.close()
        except Exception:  # noqa: BLE001  (a vanished device may not close cleanly)
            pass

    cdc = None
    if cdc_proc is not None:
        try:
            cdc = cdc_results.get(timeout=15.0)
        except Exception:  # noqa: BLE001
            cdc = {"error": "CDC logger did not report"}
        cdc_proc.join(5.0)

    result = ha.analyze(rec, criteria, cdc, reader_error)
    result["meta"] = {
        "tool": "hid8k_measure.py",
        "started_utc": started.isoformat(),
        "label": args.label,
        "vid_pid": f"{args.vid:04x}:{args.pid:04x}",
        "backend": src.name,
        "binding": getattr(src, "binding", None),
        "path": str(getattr(src, "path", "")),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "requested_duration_s": args.duration,
        "warmup_s": args.warmup,
        "read_timeouts": timeouts,
        "linux_usb": usb_info,
        "cdc": cdc,
        "criteria": vars(criteria),
    }

    header = [f"hid8k_measure {result['meta']['vid_pid']} via {src.name} "
              f"{result['meta']['path']}  ({result['meta']['platform']})"]
    for u in usb_info:
        eps = ", ".join(f"bInterval {e['bInterval']} ({e['interval']})"
                        for e in u["hid_in_endpoints"])
        header.append(f"sysfs: speed {u['speed_mbps']} Mb/s, HID interrupt IN {eps or 'none'}")
    if cdc:
        header.append("cdc: " + (cdc.get("error") or
                                 f"{cdc['mode']}, {cdc['bytes_per_s'] / 1e3:.1f} kB/s read, "
                                 f"{cdc['stats_lines']} stats lines, log {cdc['log']}"))
    if not cdc and not args.cdc:
        header.append("cdc: not opened by this tool (keep a terminal logging it, see README)")

    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(result, f, indent=1, default=str)
        f.write("\n")
    if args.csv:
        write_csv(args.csv, rec)

    print(ha.format_summary(result, header))
    print(f"result: {out_path}")
    return {"PASS": 0, "FAIL": 1}.get(result["verdict"], 2)


if __name__ == "__main__":
    sys.exit(main())
