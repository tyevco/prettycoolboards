"""Shared fixtures: each bench runs once per session; every test reads its results.

Run from the repository root:

    PYTHONDONTWRITEBYTECODE=1 /root/.venvs/kbd/bin/python -m pytest keyboard/sim/tests -q -p no:cacheprovider

Tests marked xfail(strict=True) record a margin that SPEC relies on and that the simulation does not support
today; each names the reason. When a design change restores the margin the test passes, strict xfail reports
XPASS as a failure, and the marker must come off (with SPEC and the README updated). That way the suite stays
green on a known gap and still fails on any change, in either direction.
"""

import os
import sys

sys.dont_write_bytecode = True
SIM = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SIM not in sys.path:
    sys.path.insert(0, SIM)

import pytest  # noqa: E402

import spice  # noqa: E402


def pytest_collection_modifyitems(config, items):
    if spice.available():
        return
    skip = pytest.mark.skip(reason="ngspice is not installed (Ubuntu: apt-get install ngspice)")
    for item in items:
        if "nospice" not in item.keywords:
            item.add_marker(skip)


def pytest_configure(config):
    config.addinivalue_line("markers", "nospice: runs without ngspice")


@pytest.fixture(scope="session")
def board():
    import design
    return design.board()


@pytest.fixture(scope="session")
def lane():
    import bench_lane
    return bench_lane.run_all()


@pytest.fixture(scope="session")
def slot():
    import bench_slot
    return bench_slot.run_all()


@pytest.fixture(scope="session")
def inp():
    import bench_input
    return bench_input.run_all()
