"""Run ngspice in batch mode and read back its waveforms.

The benches build plain SPICE netlists as text (resistors, capacitors, switches and B-sources only, so any
ngspice of version 36 or later runs them) and hand them to run(). run() appends a .control block that runs the
analysis and writes the requested vectors with `wrdata`, then parses the columns into numpy arrays.

This module proves nothing about hardware. It is the plumbing; tests/test_tooling.py checks it against closed-form
RC answers so that a broken runner or a too-loose tolerance shows up as a failing test, not as a quiet margin.
"""

import os
import re
import shutil
import subprocess
import tempfile

import numpy as np

NGSPICE = os.environ.get("NGSPICE", "ngspice")

# Tight tolerances: the lane bench resolves errors of a few microvolts (0.05 LSB at 14 bits is 10 uV of 3.3 V).
DEFAULT_OPTIONS = ".options reltol=1e-6 abstol=1e-15 vntol=1e-9 chgtol=1e-17 method=trap"
# The power benches resolve millivolts and milliamps over milliseconds; gear integration damps the switch edges.
POWER_OPTIONS = ".options reltol=1e-4 abstol=1e-9 vntol=1e-6 method=gear itl4=100"


class SpiceError(RuntimeError):
    pass


def available():
    """True if an ngspice binary is on the PATH (or named by $NGSPICE)."""
    return shutil.which(NGSPICE) is not None


def version():
    """ngspice's version string, e.g. 'ngspice-42'."""
    out = subprocess.run([NGSPICE, "--version"], capture_output=True, text=True, check=False).stdout
    m = re.search(r"ngspice-(\d+)", out)
    return f"ngspice-{m.group(1)}" if m else out.strip().splitlines()[0] if out.strip() else "unknown"


class Waves(dict):
    """Vector name -> numpy array, plus the scale under 'time' (or 'sweep' for a DC analysis)."""

    def at(self, name, t):
        """Linear interpolation of vector `name` at scale value(s) t."""
        return np.interp(t, self.scale, self[name])

    @property
    def scale(self):
        for key in ("time", "sweep", "frequency"):
            if key in self:
                return self[key]
        raise KeyError("no scale vector")

    def window(self, name, t0, t1):
        """The samples of `name` with t0 <= scale <= t1."""
        s = self.scale
        m = (s >= t0) & (s <= t1)
        return self[name][m]


def run(netlist, vectors, analysis, options=DEFAULT_OPTIONS, keep_dir=None, timeout=600, psa=False):
    """Simulate `netlist` (SPICE text, no .control and no .end) and return Waves.

    vectors  -- names as ngspice spells them in wrdata, e.g. 'v(lane)', 'i(vsrc)'.
    analysis -- an ngspice control-language analysis line, e.g. 'tran 1n 20u 0 1n' or 'dc iload 0 3 0.01'.
    keep_dir -- if given, the netlist and data files are left there (for debugging); otherwise a temp dir.
    psa      -- run in ngspice's PSpice compatibility mode (for vendor PSpice models; vendor.py).
    """
    if not available():
        raise SpiceError(f"{NGSPICE} not found: install ngspice (Ubuntu: apt-get install ngspice)")
    work = keep_dir or tempfile.mkdtemp(prefix="kbdsim_")
    os.makedirs(work, exist_ok=True)
    cir = os.path.join(work, "bench.cir")
    dat = os.path.join(work, "bench.dat")
    # an AC analysis writes its frequency as the scale; ask for real vectors (vr(x), vi(x) or vm(x)), which keep
    # wrdata's single-scale layout
    scale = {"dc": "sweep", "ac": "frequency"}.get(analysis.split()[0].lower(), "time")
    text = "\n".join([
        "* keyboard/sim bench",
        netlist.strip(),
        options,
        ".control",
        "set wr_singlescale",
        "set wr_vecnames",
        "option numdgt=12",
        analysis,
        f"wrdata {dat} " + " ".join(vectors),
        "quit",
        ".endc",
        ".end",
        "",
    ])
    with open(cir, "w", newline="\n") as f:
        f.write(text)
    if psa:   # ngspice reads .spiceinit from the working directory before it parses the netlist
        with open(os.path.join(work, ".spiceinit"), "w", newline="\n") as f:
            f.write("set ngbehavior=psa\n")
    try:
        proc = subprocess.run([NGSPICE, "-b", cir], capture_output=True, text=True, timeout=timeout, cwd=work)
        if not os.path.exists(dat):
            raise SpiceError(f"ngspice wrote no data (exit {proc.returncode}):\n{proc.stdout[-3000:]}\n"
                             f"{proc.stderr[-3000:]}")
        bad = [ln for ln in (proc.stdout + proc.stderr).splitlines()
               if re.search(r"(?i)(^error|timestep too small|simulation\(s\) aborted)", ln.strip())]
        if bad:
            raise SpiceError("ngspice reported:\n" + "\n".join(bad[:20]))
        data = np.loadtxt(dat, skiprows=1, ndmin=2)
        words = analysis.split()
        if words[0].lower() == "tran":       # a run that stopped early is a failure, whatever it printed
            t_stop = _si(words[2])
            if data[-1, 0] < t_stop * (1 - 1e-6):
                raise SpiceError(f"transient stopped at {data[-1, 0]:.6g} s of {t_stop:.6g} s")
    finally:
        if keep_dir is None:
            shutil.rmtree(work, ignore_errors=True)
    if data.shape[1] != len(vectors) + 1:
        raise SpiceError(f"expected {len(vectors) + 1} columns, got {data.shape[1]}")
    w = Waves()
    w[scale] = data[:, 0]
    for k, name in enumerate(vectors):
        w[name] = data[:, k + 1]
    return w


def _si(text):
    """'2u' -> 2e-6 (SPICE scale suffixes)."""
    m = re.fullmatch(r"([-+0-9.eE]+)(meg|[fpnumkgt])?", text.strip().lower())
    scale = {"f": 1e-15, "p": 1e-12, "n": 1e-9, "u": 1e-6, "m": 1e-3, "k": 1e3, "meg": 1e6, "g": 1e9, "t": 1e12}
    return float(m.group(1)) * (scale[m.group(2)] if m.group(2) else 1.0)


def pwl(points, name_pos, name_neg="0", kind="V"):
    """A PWL source line from [(t, value), ...]; repeated times are nudged by 1 ps so ngspice accepts them."""
    pts, last = [], -1.0
    for t, v in points:
        t = max(t, last + 1e-12)
        pts.append(f"{t:.12g} {v:.12g}")
        last = t
    return f"{kind}{name_pos} {name_pos} {name_neg} PWL(" + " ".join(pts) + ")"


def crossings(t, y, level):
    """Times at which y crosses `level` (linear interpolation between samples)."""
    s = np.sign(y - level)
    idx = np.nonzero(s[:-1] * s[1:] < 0)[0]
    return [t[i] + (level - y[i]) * (t[i + 1] - t[i]) / (y[i + 1] - y[i]) for i in idx]


def settle_time(t, err, tol, t_start=0.0):
    """First time >= t_start after which |err| stays within tol to the end of the record (None if never)."""
    m = t >= t_start
    t, err = t[m], np.abs(err[m])
    out = np.nonzero(err > tol)[0]
    if len(out) == 0:
        return float(t[0])
    if out[-1] == len(t) - 1:
        return None
    i = out[-1]
    # interpolate the last crossing of tol
    e0, e1 = err[i], err[i + 1]
    return float(t[i] + (e0 - tol) * (t[i + 1] - t[i]) / (e0 - e1)) if e0 != e1 else float(t[i + 1])


def longest_run(t, flag):
    """Longest contiguous time for which the boolean array `flag` is true (sample-to-sample)."""
    best = cur = 0.0
    for k in range(1, len(t)):
        if flag[k] and flag[k - 1]:
            cur += t[k] - t[k - 1]
            best = max(best, cur)
        else:
            cur = 0.0
    return best
