#!/bin/bash
set -euo pipefail
app_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# Keep the host's controller/display environment. The backend separately removes
# injected Steam library paths so Python loads the bundled runtime.
# Steam's overlay injection can deadlock Chromium before Electron is ready.
# Keep Steam Input and display variables, but use the host libraries for this app.
unset LD_PRELOAD
if [[ -n "${SYSTEM_LD_LIBRARY_PATH:-}" ]]; then
  export LD_LIBRARY_PATH="$SYSTEM_LD_LIBRARY_PATH"
else
  unset LD_LIBRARY_PATH
fi
exec "$app_dir/go2-data-studio" "$@"
