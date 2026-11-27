#!/usr/bin/env bash
# Build the simulated board (native_sim) and run the protocol tests against it (host/test_sim.py).
#   keyboard/firmware/bringup/sim/run_tests.sh [build-dir]       (default: keyboard/firmware/build/bringup-sim)
# Needs a Zephyr v4.5.0 workspace (ZEPHYR_BASE set, west on PATH) and Python 3 with pytest.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../../../.." && pwd)"
build="${1:-$repo/keyboard/firmware/build/bringup-sim}"
west build -p auto -b native_sim/native/64 "$repo/keyboard/firmware/bringup" -d "$build"
TB_SIM_EXE="$build/zephyr/zephyr.exe" PYTHONDONTWRITEBYTECODE=1 \
  python3 -m pytest -q -p no:cacheprovider "$repo/keyboard/firmware/bringup/host"
