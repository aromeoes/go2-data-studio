#!/bin/bash
# Optional one-time Linux permission for Vector's legacy port-80 connection check.
# Grants only privileged-port binding to the bundled wire-pod executable.
set -euo pipefail
binary="${1:-$HOME/Applications/go2-data-studio/resources/runtime/wirepod/wirepod}"
[[ "$(uname -s)" == Linux ]] || { echo 'Only required on Linux.'; exit 1; }
[[ -f "$binary" && ! -L "$binary" && -x "$binary" ]] || { echo 'Installed wire-pod executable not found.'; exit 1; }
command -v setcap >/dev/null || { echo 'Install the libcap tools for your distribution first.'; exit 1; }
sudo setcap cap_net_bind_service=+ep "$binary"
getcap "$binary"
