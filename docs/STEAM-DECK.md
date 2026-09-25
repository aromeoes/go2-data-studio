# Steam Deck application

Go2 Data Studio 0.3.0 runs locally on a Steam Deck. The Electron application
includes Python 3.12.14, DimOS 0.0.14 at the pinned commit, CPU-only PyTorch 2.7.1,
Go2 connectivity and mapping dependencies, Deno 2.9.6 and its cached Web SDK relay.
No Mac connection is involved. The installed application occupies about 5.8 GB.

## Open and configure

Open **Go2 Data Studio** from Steam's Library under Non-Steam, or from the Desktop
Mode applications menu. Steam launch opens fullscreen and selects Controller.
It always starts disconnected with movement disabled. There is no automatic
connection or automatic stand-up command.

The Deck and Go2 need a mutually reachable network. Enter the Go2's current STA
Wi-Fi IP in the dashboard. Configure HumanCLI through Agent model and sign in to
DimOS Cloud on this device. Credentials and recordings from a Mac are not included
in the application. No credentials are needed for local replay and map generation.

The default installation is `~/Applications/go2-data-studio`. Recordings and
settings live in `~/.config/Go2 Data Studio/spaces`, outside the application.
Logs are in that folder's `logs` directory. Do not run multiple consoles against
the same robot or data directory.

## Controller

Use Steam Input's standard gamepad layout. Steam selected its built-in gamepad
FPS template during the installation test. Press a controller button once if the
browser has not exposed the controller yet. Touch and trackpad remain available.

| Input | Action |
| :--- | :--- |
| D-pad, while disarmed | Move focus; left/right changes a focused selector |
| A, while disarmed | Activate the focused control |
| Right stick, while disarmed | Scroll the page |
| Steam + X | Open Steam's keyboard for text entry |
| Left stick, while armed | Forward/backward and sideways translation |
| Right stick horizontal, while armed | Turn |
| LB held | Hold to drive; release requests zero motion |
| B | Request software stop |

Enable controls explicitly and release/center the controls before driving. Focus
loss, stale samples and suspend/resume disarm movement. These are software
controls, not an electrical emergency stop. Physical buttons, joystick response, text entry and sustained robot recording
still need operator testing on this Deck.
The implementation and replay checks do not establish physical safety or performance.

Save recording and use the guarded disconnect flow before quitting. For a physical
session, an operator must request lie-down and visually confirm support first.
The app guards normal quit and termination requests. Steam's force-stop, forced
sleep, power loss and SIGKILL cannot be intercepted reliably.

## Install another copy

Extract the Linux archive, then run `bash install-linux.sh`. It installs inside
the current user's home and creates a desktop entry. It refuses to replace an
existing app; close its session and preserve the old installation before replacing
it. Data stays outside the installation. SteamOS's read-only root is unchanged.

Add `~/Applications/go2-data-studio/launch.sh` as a non-Steam game with launch
option `--steam`, or use `desktop/install-steam.py` from the source repository
with ValvePython `vdf==3.4` installed. Exit Steam first. The helper backs up any
existing shortcuts, preserves other entries and uses the active auto-login profile.
Artwork is under the installation's `artwork` folder.

The launcher excludes Steam's overlay preload and alternate library paths from
Electron: those caused a Chromium GPU-process startup crash on this Deck. Steam
Input variables remain intact. This app does not depend on Steam's injected overlay.

The launcher also replaces Steam's injected GTK text-input module with `simple`
for this app. This addresses doubled characters in Electron on the Deck while
preserving an explicitly selected non-Steam input method. See the
[matching upstream report](https://github.com/Heroic-Games-Launcher/HeroicGamesLauncher/issues/4250).
The September 25 launcher patch was applied to the installed app after the
original 0.3.0 archive was created; rebuild from current source to include it.


## Build

Build natively on Linux x86_64, with uv 0.12.19 and Node 24.21.0 in PATH. The
validated host was SteamOS 3.8.16. Its system libturbojpeg.so.0 and libportaudio.so.2
are copied into the runtime. It still depends on the host's graphics, audio and
standard Linux libraries; compatibility with arbitrary Linux distributions is
not claimed. Allow at least 20 GB for the environment, runtime and package.

Run `bash desktop/build-linux.sh` from a fresh source tree. It uses the checked-in
309-package version lock, isolated Python and Zig for PyAudio, the pinned DimOS
GitHub archive, and a frozen Deno dependency graph. No framework checkout is read
or modified. The build manifest records runtime versions and archive hashes.
The consolidated script captures the successful build steps; package download
hash pinning and CI builds remain release work.

The result is `desktop/dist/linux-unpacked`. Put that directory in an archive as
`app/`, alongside `desktop/install-linux.sh`. Keep generated binaries, recordings
and credentials out of Git. Dependency licenses remain in the shipped runtime;
Electron's notices remain in the application directory. Updates are currently
manual. The existing Mac installation is independent of this Linux build.

## Validation on 2026-09-24 and 2026-09-25

* 103 backend tests passed against the packaged runtime and application source.
* 22 frontend tests and 6 desktop tests passed on the Deck.
* The relocated installed Electron app loaded in an isolated replay-only profile
  in about 7.6 seconds, with no horizontal overflow at 1280 by 800. WebTransport
  was available; Node integration in the renderer was absent.
* An eight-frame synthetic SQLite recording generated an exported PointCloud2
  map and a Rerun inspection file on CPU.
* The complete DimOS replay pipeline reached online. Quitting was refused while
  replay was active, then succeeded after the guarded stop/disconnect flow.
* Steam launched the installed app in Desktop Mode and Gaming Mode. The
  Gamescope window was 1280 by 800; the bundled backend and relay ran and the
  dashboard polled successfully while disconnected.
* Steam exposed a virtual Xbox-compatible controller. No person pressed its
  physical controls during these checks. Gamepad behavior was tested with mocks.

No physical robot connection or motion was requested. Long recording performance,
thermals, battery consumption and physical controls need a supervised check.
