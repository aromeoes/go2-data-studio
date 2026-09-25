# Mac application

Go2 Data Studio 0.2.1 includes Electron, the existing interface and DimOS Web SDK,
Python 3.12.13, pinned DimOS 0.0.14, installed robot/mapping/agent dependencies,
Deno 2.9.6, and cached relay dependencies. It runs locally on Apple Silicon.
It does not require a separate checkout, Python installation, Deno, Homebrew,
Node.js or terminal startup on the user's Mac.

## Install and launch

Open the DMG, drag Go2 Data Studio to Applications, then open the application.
Startup leaves the robot disconnected. Use the existing connection and control
flows in the dashboard. Hosted HumanCLI providers and Cloud backups still require
network access and their credentials; models are configured in Agent model.

This build is a local development distribution. Developer ID signing and Apple
notarization are not configured, and Intel Macs have not been validated. A
transfer to another Mac may require approval in macOS Privacy & Security. Do not
disable Gatekeeper globally. Distribution signing is separate from packaging.

Recordings and private settings live in
`~/Library/Application Support/Go2 Data Studio/spaces`. They are outside the
application bundle, so replacing the application does not overwrite them.
The Go2 Data Studio menu opens the data and log folders. The first desktop library
is separate from an existing browser application's library. Existing recordings
can be imported through the dashboard. Never point two running consoles at the
same data directory or robot.

The desktop's optional `robot.env` is located alongside `spaces`. Optional
`desktop.json` supports `data` and `robotEnv` absolute paths; change these while
the app is closed. API keys and robot credentials are never included in the DMG.
No runtime path is needed or saved for a packaged Mac application.

Application quit follows the guarded disconnect workflow. Save recordings,
request lie-down with the operator present, visually confirm support, and use
Disconnect before quitting. Closing the window does not bypass that guard.

## Build the embedded runtime

Build on Apple Silicon with the validated DimOS dependency environment. The
builder reads installed third-party distributions and the Python standalone
installation. DimOS itself is supplied from the exact upstream GitHub archive;
the development framework checkout is never copied or modified. The resulting
runtime is relocatable and has no editable-install links.

```sh
mkdir -p /tmp/go2-runtime-inputs
curl -fL https://api.github.com/repos/dimensionalOS/dimos/tarball/c1c3cdc9d2ee54ca72259465688395699d7d99a2 -o /tmp/go2-runtime-inputs/dimos.tar.gz
curl -fL https://github.com/denoland/deno/releases/download/v2.9.6/deno-aarch64-apple-darwin.zip -o /tmp/go2-runtime-inputs/deno.zip
"$DIMOS_RUNTIME/.venv/bin/python" desktop/build-runtime.py \
  --output desktop/runtime \
  --dimos-archive /tmp/go2-runtime-inputs/dimos.tar.gz \
  --deno-archive /tmp/go2-runtime-inputs/deno.zip \
  --turbojpeg /opt/homebrew/lib/libturbojpeg.dylib
python3 desktop/relocate-native.py desktop/runtime
curl -fL https://raw.githubusercontent.com/denoland/deno/v2.9.6/LICENSE.md -o desktop/runtime/DENO-LICENSE.md
DENO_DIR="$PWD/desktop/runtime/deno-cache" desktop/runtime/bin/deno cache \
  --frozen --node-modules-dir=none \
  --config vendor/dimos-web/deno.json vendor/dimos-web/relay/main.ts
cd web
npm ci
npm run build
cd ../desktop
npm ci
npm test
npm run package:mac
```

Use a fresh output directory for `build-runtime.py`. The build manifest records
Python/Deno versions, dependency versions, the DimOS commit and input archive
SHA-256 hashes. Native non-system library dependencies are copied and rewritten
to relative loader paths. Modified binaries receive local ad-hoc signatures;
these are not Developer ID signatures. Installed distribution license metadata,
the DimOS license and the Deno license are retained.

The initial runtime includes the validated environment's dependencies rather
than trimming it to a minimal set. Reducing installer size and producing locked
runtime inputs in CI remain follow-up work. The package build refuses a missing
or mismatched runtime. Runtime artifacts, installers, credentials and datasets
are git-ignored.

## Verified on 2026-09-24

* 103 backend tests passed using the packaged Python and application source.
* 20 frontend tests and 5 desktop lifecycle/runtime tests passed.
* The actual packaged Electron application started in an isolated replay-only
  profile with a minimal system PATH and no external runtime setting. It showed
  the disconnected dashboard in about five seconds and exited through the guard.
* WebTransport was available, renderer Node access was absent, and the inspected
  desktop layout had no horizontal overflow.
* Imports of the app, mapping, Go2 connection dependencies and agent dependencies
  loaded 962 native images with no libraries from Homebrew or a development tree.
* A synthetic eight-frame SQLite recording generated a PointCloud2 map and a
  Rerun inspection file using the packaged DimOS CLI on CPU.
* The relay dependency graph resolved with Deno's cached-only option.

Physical motion, sensors and prolonged recording require a separate supervised
hardware check. These packaging tests did not connect to or move a robot.
