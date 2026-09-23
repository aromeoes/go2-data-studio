#!/bin/zsh
set -eu
app_dir="${0:A:h}"
export PYTHONPATH="$app_dir${PYTHONPATH:+:$PYTHONPATH}"
runtime_dir="${DIMOS_RUNTIME:-$app_dir/../dimos-runtime}"
data_dir="${GO2_SPACES:-$HOME/Go2Spaces}"
mkdir -p "$data_dir"
export NUMBA_CACHE_DIR="$data_dir/numba-cache"
export DIMOS_RUN_LOG_DIR="$data_dir/logs"
if [[ ! -x "$runtime_dir/.venv/bin/python" ]]; then
  print "DimOS environment missing at $runtime_dir. See README.md."
  exit 1
fi
expected_sha="c1c3cdc9d2ee54ca72259465688395699d7d99a2"
actual_sha="$(git -C "$runtime_dir" rev-parse HEAD)"
if [[ "$actual_sha" != "$expected_sha" ]]; then
  print "DimOS revision mismatch. Review the integration before operating the robot."
  exit 1
fi
cd "$app_dir"
exec "$runtime_dir/.venv/bin/python" -m go2_setup.api
