#!/bin/bash
# Run on SteamOS/Linux x86_64 with uv 0.12.19 and Node 24 installed in PATH.
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
build_dir="${GO2_BUILD_DIR:-$HOME/.cache/go2-data-studio-build}"
[[ "$(uname -sm)" == 'Linux x86_64' ]] || { echo 'Build on Linux x86_64.'; exit 1; }
command -v uv >/dev/null
command -v npm >/dev/null
[[ ! -e "$repo_dir/desktop/runtime" ]] || { echo 'Use a fresh source tree without desktop/runtime.'; exit 1; }
mkdir -p "$build_dir/inputs" "$build_dir/include"
uv venv --python 3.12.14 "$build_dir/dependencies"
uv venv --python 3.12.14 "$build_dir/compiler"
uv pip install --python "$build_dir/compiler/bin/python" ziglang==0.13.0
curl -fL https://raw.githubusercontent.com/PortAudio/portaudio/v19.7.0/include/portaudio.h -o "$build_dir/include/portaudio.h"
export CC="$build_dir/compiler/lib/python3.12/site-packages/ziglang/zig cc"
export LDSHARED="$CC -shared"
export CFLAGS="-I$build_dir/include"
export LDFLAGS='-L/usr/lib'
# The lock records the tested environment, including upstream dependency overrides.
# Avoid re-resolving those overrides from DimOS wheel metadata.
uv pip install --python "$build_dir/dependencies/bin/python" --no-deps \
  --index https://download.pytorch.org/whl/cpu --index-strategy unsafe-best-match \
  -r "$repo_dir/desktop/linux-requirements.lock"
curl -fL https://api.github.com/repos/dimensionalOS/dimos/tarball/c1c3cdc9d2ee54ca72259465688395699d7d99a2 -o "$build_dir/inputs/dimos.tar.gz"
curl -fL https://github.com/denoland/deno/releases/download/v2.9.6/deno-x86_64-unknown-linux-gnu.zip -o "$build_dir/inputs/deno.zip"
cd "$repo_dir"
"$build_dir/dependencies/bin/python" desktop/build-runtime.py \
  --output desktop/runtime --dimos-archive "$build_dir/inputs/dimos.tar.gz" \
  --deno-archive "$build_dir/inputs/deno.zip" --turbojpeg /usr/lib/libturbojpeg.so.0
cp -L /usr/lib/libportaudio.so.2 desktop/runtime/lib/libportaudio.so.2
curl -fL https://raw.githubusercontent.com/denoland/deno/v2.9.6/LICENSE.md -o desktop/runtime/DENO-LICENSE.md
DENO_DIR="$PWD/desktop/runtime/deno-cache" desktop/runtime/bin/deno cache \
  --frozen --node-modules-dir=none --config vendor/dimos-web/deno.json vendor/dimos-web/relay/main.ts
(cd web && npm ci && npm test && npm run build)
(cd desktop && npm ci && npm test && npm run package:linux)
cp desktop/launch-linux.sh desktop/dist/linux-unpacked/launch.sh
chmod +x desktop/dist/linux-unpacked/launch.sh
cp desktop/assets/icon.png desktop/dist/linux-unpacked/icon.png
cp -a desktop/assets/steam desktop/dist/linux-unpacked/artwork
printf 'Built: %s/desktop/dist/linux-unpacked\n' "$repo_dir"
