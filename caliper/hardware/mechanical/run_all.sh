#!/usr/bin/env bash
# Regenerate every mechanical output (WSL: KiCad 9 pcbnew + build123d + matplotlib in ~/.venvs/dial-me-spinner).
#   bash caliper/hardware/mechanical/run_all.sh
# The FEA runs on the Windows Python with the print-stress skill, after this script (it reads step/):
#   py fea_jaw.py          # moving jaw          -> fea_jaw_output.txt, renders/fea_jaw.png
#   py fea_slider.py       # body + board        -> fea_slider_output.txt, renders/fea_body.png
# then run `$PY calcs.py` again so calcs_output.txt quotes the new FEA numbers.
set -eu
cd "$(dirname "$0")"
PY=${PY:-$HOME/.venvs/dial-me-spinner/bin/python}
$PY extract_board_parts.py            # the routed slider board -> board_parts.json
$PY -m pytest tests -q
$PY models.py
$PY export.py
$PY drawgen.py
$PY clash_check.py > /dev/null && head -3 clash_report.txt
$PY calcs.py > /dev/null && echo "calcs_output.txt written"
$PY render.py
