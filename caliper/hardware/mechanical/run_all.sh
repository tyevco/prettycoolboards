#!/usr/bin/env bash
# Regenerate every mechanical output (WSL: build123d + matplotlib in ~/.venvs/dial-me-spinner).
#   bash caliper/hardware/mechanical/run_all.sh
# The jaw FEA (fea_jaw.py) runs on the Windows Python with the print-stress skill: `py fea_jaw.py`.
set -eu
cd "$(dirname "$0")"
PY=${PY:-$HOME/.venvs/dial-me-spinner/bin/python}
$PY -m pytest tests -q
$PY models.py
$PY export.py
$PY drawgen.py
$PY clash_check.py > /dev/null && head -12 clash_report.txt
$PY calcs.py > /dev/null && echo "calcs_output.txt written"
$PY render.py
