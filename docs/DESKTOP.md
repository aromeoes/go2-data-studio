# Standalone desktop development preview

Goal: the Steam Deck or Mac independently runs the interface, DimOS, robot
connection, recording and mapping. There is no Deck-to-Mac pairing mode.

## Implemented in this milestone

* Electron host for the existing React interface, official Web SDK and local
  Python backend. The browser interface remains usable separately.
* Fresh authenticated local service per desktop process, separate ports, private
  desktop data directory and explicit runtime selection. The renderer has no
  Node integration and remains sandboxed with context isolation.
* Standard Gamepad input: left stick for translation, right stick horizontal for
  rotation, LB held to move, B to stop. A neutral/released state is required before
  motion. Dead zones and proportional response retain lateral and yaw limits.
* Analog input passes through the pinned SDK's existing lease and send cadence.
  The adapter changes nonzero twist values only; it preserves sequence numbers,
  stop messages and SDK-generated zeros. The upstream vendor snapshot is intact.
* Stale gamepad samples go to zero and disarm. Losing focus, suspending, resuming,
  or losing the renderer requests a software stop. Resume never arms movement.
* A planned application quit is refused while any robot/replay session or
  recording remains. The user must use the existing guarded disconnect flow.
  The backend then locks out new connections before acknowledging shutdown.
* Linux file-manager support and a compact landscape layout for 1280 x 800.

## Run the preview

Build the web application first. The desktop preview currently requires an
already-installed pinned DimOS checkout and its configured `.venv`, just as the
browser application does. It is not yet a self-contained runtime distribution.

```sh
cd web
npm ci
npm run build
cd ../desktop
npm ci
DIMOS_RUNTIME=/absolute/path/to/dimos-runtime npm start
```

If Electron's binary was not downloaded because your npm installation blocks
install scripts, explicitly permit the Electron installer under your local npm
policy before starting.

Without DIMOS_RUNTIME, a folder chooser asks for the installed checkout. The
selection is saved in the desktop application's private config directory.
Data defaults to that directory's `spaces` folder, avoiding the existing browser
application's data. The robot credential file defaults to `robot.env` beside
`desktop.json`. GO2_SPACES and GO2_ENV_FILE override those locations. Credentials
are never packaged into the application or exposed to the Electron renderer.

To test without hardware, export GO2_REPLAY_ONLY=1 and use a temporary GO2_SPACES
folder. No physical connection can then be launched. Replay does not establish
physical control performance.

Choose Controller in the Teleop input selector. Use Steam Input's standard
gamepad layout on Deck. A controller button press may be needed before the
browser exposes it. Touch/trackpad or keyboard still navigates the interface;
full D-pad interface navigation and Deck-specific gyro/back-button mappings are
not implemented in this milestone.

## Build and checks

```sh
cd desktop
npm test
npm run package:mac
# On a Linux build host:
npm run package:linux
```

The package commands produce unpacked desktop previews. They include the UI,
application backend source and vendored relay, but not Python or the DimOS native
dependency environment. They are not production installers. Apple Silicon is
currently the Mac package target; Intel support is not yet validated.

Backend tests cover the desktop session credential, guarded shutdown, prevention
of reconnect after shutdown acknowledgement and platform file-manager commands.
Frontend tests exercise neutral/deadman checks, invalid inputs, analog limits,
stale samples and the real SDK lease/zeroing behavior. Desktop tests ensure a
failed shutdown guard never signals the backend process.

## Required before a standalone release

1. Build relocatable, versioned DimOS/Python/relay runtime distributions for Linux
   x86-64 and macOS arm64. An existing development virtualenv cannot simply be
   copied into the application: interpreter links, entrypoint paths and native
   libraries must be validated after relocation.
2. Test directly on Steam Deck: standard Gamepad exposure in Desktop and Gaming
   modes, WebTransport, Wi-Fi connection, sustained recording, navigation latency,
   storage throughput, memory, temperatures and battery use. Do not assume its GPU
   accelerates the same mapping backend used on another machine.
3. Add installation and update handling, macOS signing/notarization, and test a
   SteamOS-compatible distribution such as Flatpak including required permissions.
4. Add complete controller navigation and on-screen keyboard behavior. Extend
   input mappings only after testing the built-in Deck controls.
5. Validate physical suspend/loss-of-link behavior with an operator. Idle sleep
   inhibition and software stop requests cannot guarantee safety during forced
   sleep, power loss or firmware faults. No automatic posture command is sent.

The application does not automatically restart a failed backend. If the desktop
process itself crashes, the backend may remain alive to avoid an unguarded robot
shutdown; existing control leases still expire. Recovery and service reattachment
need a dedicated guarded workflow before production release. Never kill a live
robot runtime as a deployment shortcut.

## Validation recorded on 2026-09-24

103 backend tests, 20 frontend tests and 3 desktop lifecycle tests passed. Ruff,
the frontend production build and upstream vendor verification passed. A hidden
Electron process launched the real backend and relay with replay-only enforcement,
no robot credentials and a fresh data folder. The interface loaded disconnected,
WebTransport and Gamepad APIs were present, Node was unavailable in the renderer,
and shutdown completed through the backend guard. This checks local application
startup, not physical controller behavior, mapping throughput or Go2 movement.

Unpacked Apple Silicon and Linux x86-64 previews were built successfully. The
Linux artifact has not been run on SteamOS. The compact controller panel was
inspected in Electron at 1280 x 800 using a simulated controller, with no
horizontal page overflow. Real hardware input remains unverified.
