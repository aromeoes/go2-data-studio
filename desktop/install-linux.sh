#!/bin/bash
set -euo pipefail
source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
target_dir="$HOME/Applications/go2-data-studio"
if [[ -e "$target_dir" ]]; then
  echo "An installation already exists at $target_dir. Close its robot session and app before replacing it."
  exit 1
fi
mkdir -p "$HOME/Applications" "$HOME/.local/share/applications"
cp -a "$source_dir/app" "$target_dir"
chmod +x "$target_dir/launch.sh"
cat > "$HOME/.local/share/applications/go2-data-studio.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=DIMENSIONAL
Comment=Map, record and explore with a Unitree Go2
Exec="$target_dir/launch.sh"
Icon=$target_dir/icon.png
Terminal=false
Categories=Utility;
StartupWMClass=go2-data-studio
EOF
command -v update-desktop-database >/dev/null && update-desktop-database "$HOME/.local/share/applications" || true
printf 'Installed: %s\nOpen DIMENSIONAL from the applications menu.\n' "$target_dir"
