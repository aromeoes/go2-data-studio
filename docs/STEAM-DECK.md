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
| L1 / LB held | Take Teleop control from any mode; release stops and relinquishes the app lease |
| L2 / LT held with L1 | Forward boost up to 1.0 m/s at full stick; release L2 restores the selected speed |
| B | Request software stop |

With controller input selected, center the sticks and hold L1 to take Teleop
control. No Enable controls click is needed. A fresh L1 press clears a software
Stop latch before requesting Teleop; physical sensor checks still apply. Release
L1 to stop. Focus loss, stale samples and suspend/resume cancel the request and
require a new press after releasing L1. These are software
controls, not an electrical emergency stop. Physical buttons, joystick response, text entry and sustained robot recording
still need operator testing on this Deck.
The implementation and replay checks do not establish physical safety or performance.

Stop movement, save recording and use Disconnect before quitting.
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

## Unitree actions and map generation

Expand **Unitree actions** under Go2 controls to search the installed DimOS
`UnitreeSkillContainer` registry. Every registry entry is listed. The 30 name-only
commands can be submitted after pausing control and confirming the exact action.
The 10 parameterized entries remain visible with an explanation because the pinned
upstream dispatcher accepts only an action name. Actual support depends on firmware;
the UI reports rejection or missing acknowledgement, never inferred completion.
These actions are operator controls, not additional HumanCLI tools. They use the
same Web SDK command channel and do not run automatically on connection or restart.

A saved recording's **Generate map** action becomes **Pause & generate map** when
Teleop, HumanCLI or exploration is active. This explicitly pauses control first.
Recording and pending-action restrictions now include a visible explanation.
Cloud backup status is independent: map generation runs locally from the saved DB.


## HumanCLI skills and patrol demo

Full mode agent exposes DimOS tagging, named navigation, coverage patrol, person
following, and speech, in addition to recording and exploration. HumanCLI's info
button lists the enabled tools. Its skill status panel reports asynchronous
progress and failures.

To demonstrate patrol:

1. Connect Go2, start Full mode agent, and select your space.
2. Use Teleop to map a connected open area with several meters of clear floor.
3. Switch to HumanCLI. Say `Start patrolling this area`.
4. Watch the live destination and skill status. DimOS chooses coverage goals in
   the known area. Keep the control page active so its lease stays valid.
5. Say `Stop patrol`, switch to Teleop, or use Emergency stop.

To demonstrate names, say `Remember this as reception`, Teleop to a second clear
location, switch back to HumanCLI, and say `Go to reception`. Names persist on disk
in `named-places.sqlite`, scoped to a space and runtime frame. After reconnect,
old names are listed but cannot be used for movement until tagged again. Saved-map
relocalization and semantic object navigation are not integrated yet. A generated
or uploaded map does not automatically align a new connection's coordinates.

Person following reuses DimOS `PersonFollowSkillContainer` and `VisualServoing2D`,
with OpenCV CSRT replacing EdgeTAM because the Deck cannot run the upstream
CUDA/MPS-only tracker. Initial person selection uses DimOS OpenAI vision with the
existing HumanCLI key and vision setting. No GPU weights are downloaded. Only
one described person should be in view for a supervised demo. Tracking can lose
or switch targets; the app does not identify a person by name. Velocities go
through the existing control gate plus a short swept footprint check against
fresh camera, odometry, LiDAR and known free map cells. This is not certified
obstacle avoidance or an unattended following feature.

`Say welcome to the office` uses DimOS OpenAI TTS and `Go2AudioBridgeModule` on
the existing connection to the Go2 speaker. It needs an OpenAI key and compatible
Go2 audio hardware/firmware. The status confirms acknowledged audio upload, not
that anyone heard it. Push-to-talk still records the Deck/Mac microphone; the
Go2 microphone is not connected to HumanCLI.

The app hosts lifecycle adapters around the pinned DimOS skill methods, using its
existing planner and sensor bridge. It does not create another robot connection.
Mode changes, stop, lease loss and reconnect cancel skills. Delayed vision or
speech responses cannot restart movement. Coverage patrol keeps live replanning
enabled and reports a 90-second destination timeout rather than waiting forever.

Lateral Teleop currently has a 0.2 m/s cap in both the joystick mapping and backend.
The 18% dead zone and 1.5 input exponent mean half-stick requests about 0.05 m/s.
L2 boosts forward movement only. These limits are unchanged by the skill update.
