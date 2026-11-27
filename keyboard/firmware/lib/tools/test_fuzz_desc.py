"""Build tools/fuzz_desc.c with the host gcc under ASan and UBSan and run it (see the C file for what it checks).

    PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider keyboard/firmware/lib/tools

Skipped when no gcc with the sanitizers is on the host. FUZZ_DESC_ITERS sets the number of inputs (default 300000,
about a second; 3,000,000 were run on 2026-11-27 with none failing).
"""
import os
import pathlib
import shutil
import subprocess

import pytest

LIB = pathlib.Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("gcc") is None, reason="no host gcc")
def test_descriptor_parser_survives_fuzzing(tmp_path):
    exe = tmp_path / "fuzz_desc"
    cmd = ["gcc", "-std=c11", "-g", "-O1", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
           f"-I{LIB / 'include'}", str(LIB / "tools" / "fuzz_desc.c"), str(LIB / "src" / "desc.c"),
           str(LIB / "src" / "desc_test_coupon.c"), str(LIB / "src" / "rails.c"), "-o", str(exe)]
    b = subprocess.run(cmd, capture_output=True, text=True)
    if b.returncode != 0 and "sanitize" in b.stderr:
        pytest.skip("gcc without ASan/UBSan runtime: " + b.stderr[-200:])
    assert b.returncode == 0, b.stderr
    r = subprocess.run([str(exe), os.environ.get("FUZZ_DESC_ITERS", "300000")], capture_output=True, text=True,
                       timeout=600)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "iterations" in r.stdout and "parsed" in r.stdout, r.stdout
