#!/bin/zsh
set -eu
app_dir="${0:A:h}"
if curl -fsS http://127.0.0.1:8780/api/state >/dev/null 2>&1; then
  open http://127.0.0.1:8780
  exit 0
fi
"$app_dir/start.sh" &
app_pid=$!
trap 'kill -TERM "$app_pid" 2>/dev/null || true' INT TERM EXIT
for attempt in {1..30}; do
  if curl -fsS http://127.0.0.1:8780/api/state >/dev/null 2>&1; then
    open http://127.0.0.1:8780
    break
  fi
  sleep 1
done
wait "$app_pid"
