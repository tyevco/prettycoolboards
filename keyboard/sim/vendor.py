"""TI's TPS2553 PSpice transient model as a cross-check of the behavioural `powermodels.tps2553`.

TI SLVM425B, "TPS2553 Unencrypted PSpice Transient Model Package", from https://www.ti.com/lit/zip/slvm425. Its
library header reads "(C) Copyright 2011 Texas Instruments Incorporated. All rights reserved ... This model is
designed as an aid for customers of Texas Instruments ... provided solely on an 'as is' basis". It is therefore
fetched into a local cache (never into this repository) and used there:

    python keyboard/sim/vendor.py fetch      # download, check the SHA-256, unpack, patch

ngspice runs it in PSpice compatibility mode (`set ngbehavior=psa`) once three of its logic-gate subcircuits are
patched: PSpice reads `&`, `|` and `^` inside IF() as boolean AND, OR and XOR, while ngspice reads `^` as a power
and the AND/OR need `&&`/`||`. Unpatched, the XNOR that checks EN's polarity never passes and the switch never turns
on. The patch rewrites those three expressions only, in the cached copy.

The TPS25947 model (SLVMDJ6A) is an encrypted library and is not used.
"""

import hashlib
import io
import os
import sys
import urllib.request
import zipfile

import numpy as np

URL = "https://www.ti.com/lit/zip/slvm425"
SHA256 = "615c68db56115e44fda07a3d871ea2d29f8890ebc26c4b90374291d003417f0e"   # SLVM425B.ZIP, fetched 2026-11-27
CACHE = os.environ.get("KBDSIM_CACHE", os.path.join(os.path.expanduser("~"), ".cache", "kbdsim"))
LIB = os.path.join(CACHE, "tps2553_trans_ngspice.lib")
MEMBER = "TPS2553_PSPICE_TRANS/tps2553_trans.lib"


def available():
    return os.path.exists(LIB)


def _patch(text):
    pairs = [
        ("{{IF(V(A) > {VTHRESH}  ^  \n+ V(B) > {VTHRESH},{VSS},{VDD})}}",
         "{{IF((V(A) > {VTHRESH}) != \n+ (V(B) > {VTHRESH}),{VSS},{VDD})}}"),
        ("{{IF(V(A) > {VTHRESH}  &  \n+ V(B) > {VTHRESH},{VDD},{VSS})}}",
         "{{IF((V(A) > {VTHRESH})  &&  \n+ (V(B) > {VTHRESH}),{VDD},{VSS})}}"),
        ("{{IF(V(A) > {VTHRESH}  |  \n+ V(B) > {VTHRESH},{VDD},{VSS})}}",
         "{{IF((V(A) > {VTHRESH})  ||  \n+ (V(B) > {VTHRESH}),{VDD},{VSS})}}"),
    ]
    text = text.replace("\r\n", "\n")
    for old, new in pairs:
        if old not in text:
            raise RuntimeError("the TI model no longer matches the expected text; re-check the patch")
        text = text.replace(old, new)
    return text


def fetch(url=URL):
    os.makedirs(CACHE, exist_ok=True)
    with urllib.request.urlopen(url, timeout=60) as r:
        blob = r.read()
    digest = hashlib.sha256(blob).hexdigest()
    if digest != SHA256:
        raise RuntimeError(f"SLVM425 changed: SHA-256 {digest}, expected {SHA256}. Read the new model before "
                           "trusting it, then update SHA256 here.")
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        name = next(n for n in z.namelist() if n.endswith(MEMBER))
        text = z.read(name).decode("latin-1")
    with open(LIB, "w", newline="\n") as f:
        f.write(_patch(text))
    return LIB


def enable_into(c_load, load="cc", i_load=0.25, r_ilim=90.9e3, vin=3.3, t_stop=14e-3):
    """TI's model: VIN up first, EN at 0.5 ms, into c_load and a load. Returns Waves with v(out), i(vin), v(fault)."""
    import spice
    if load == "cc":
        ld = f"Bload out 0 I = {i_load}*(0.5*(1+tanh((v(out)-1.0)/0.1)))"
    elif load == "r":
        ld = f"Rload out 0 {vin / i_load:.6g}"
    else:
        ld = "Rload out 0 1e6"
    net = "\n".join([
        f".include {LIB}",
        f"Vin in 0 PWL(0 0 10u 0 60u {vin})",
        f"Ven en 0 PWL(0 0 500u 0 501u {vin})",
        f"Rilim ilim 0 {r_ilim:.6g}",
        "Rflt fault in 10k",
        "X1 in 0 en 0 fault ilim out TPS2553_TRANS",
        f"Cload out 0 {c_load:.6g}",
        ld,
    ])
    return spice.run(net, ["v(out)", "i(vin)", "v(fault)"], f"tran 1u {t_stop} 0 1u", options=".options reltol=1e-4",
                     psa=True)


def limit_time(w, i_os_fraction=0.97):
    """Time the TI model spends at its current limit: the input current within 3 % of its plateau maximum."""
    i = -w["i(vin)"]
    imax = float(np.max(i))
    return imax, float(np.sum(np.diff(w.scale)[(i[:-1] > i_os_fraction * imax)]))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "fetch":
        print("fetched and patched:", fetch())
    else:
        print(__doc__)
