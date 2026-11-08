import os
import sys

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: builds a real board design (tens of seconds)")
