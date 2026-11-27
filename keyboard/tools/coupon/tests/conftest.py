"""pytest setup for keyboard/tools/coupon: import paths, and skips for what this machine lacks.

Run from the repository root:  python -m pytest keyboard/tools/coupon/tests -q
pcbnew (KiCad 10.0.8's Python module) is needed for the board tests; gcc and a Zephyr v4.5.0 tree for the C header
tests (ZEPHYR_BASE, default /root/zephyrproject/zephyr); everything else is the standard library.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
COUPON = os.path.dirname(HERE)
sys.dont_write_bytecode = True
sys.path.insert(0, COUPON)
if HERE not in sys.path:
    sys.path.append(HERE)          # after everything else: tools/tests has a conftest of its own

import pytest  # noqa: E402

import coupon_model  # noqa: E402,F401  (puts nets.py, boards/ and tools/sexpr.py on sys.path)

from coupon_fixtures import HAVE_PCBNEW  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: builds and runs a Zephyr application (about a minute)")


@pytest.fixture(scope="session")
def geometry():
    if not HAVE_PCBNEW:
        pytest.skip("pcbnew not importable")
    return coupon_model.load_geometry()
