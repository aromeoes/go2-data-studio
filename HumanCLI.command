#!/bin/zsh
set -eu
app_dir="${0:A:h}"
export PYTHONPATH="$app_dir${PYTHONPATH:+:$PYTHONPATH}"
exec "${DIMOS_RUNTIME:-$app_dir/../dimos-runtime}/.venv/bin/python" -m go2_setup.humancli
