# Robots, blueprints and sessions

The app flow is: Onboarding (only when signed out) → Log into Dimensional or Stay
Local → Connect your robot → Start Session → Session. Go2 and Anki Vector have
separate module catalogs. Robot instances are stored separately from spaces and
recordings.

## One connection per session

Connect starts the runtime with only the required modules (Go2: `GO2Connection`,
`ControlGate`, `RelayBridgeModule`; Vector: `VectorConnection`,
`RelayBridgeModule`, `VectorTelemetry`). The camera is live while the user picks a
blueprint, but nothing can move: control modes, Unitree actions and posture
changes are refused until the session starts.

START (`POST /api/session/modules`) adds the selected modules to that same
connection. The supervisor records the new profile, then the runtime deploys only
the missing DimOS modules into its running coordinator (`/modules` on the
runtime), hands the profile to `ControlGate` and `ConsoleBridge` over RPC, and
creates HumanCLI skills. Loading runs in the background so telemetry keeps
flowing; `loading_modules` in the state reports it. Nothing is removed during a
session and the blueprint cannot change after it starts. A reconnect relaunches
the runtime with the full profile.

Verified on a recorded replay: six modules loaded in about 2 seconds in the same
runtime process, the live costmap appeared, and planner commands reached the
control gate.

## Blueprints and modules

`go2_setup/blueprints.py` is the catalog the UI shows: module ids are the DimOS
or app class names, with icons, a short description (shown as a tooltip), whether
the module is official DimOS or app-built, its dependencies, whether it is
required, and why it is unavailable on a robot.

| Blueprint | Modules |
| --- | --- |
| Teleop (recommended, fixed) | Required modules plus VoxelGridMapper, CostMapper, ConsoleBridge (recording) and UnitreeSkillContainer. No HumanCLI. |
| Custom | Any selection. Dependencies are added automatically; removing one removes its dependents. Required modules cannot be removed. |

Separate DimOS modules added at START: VoxelGridMapper, CostMapper,
ReplanningAStarPlanner and the frontier explorer (`ConsoleExplorer`). The others
are part of the base connection or app services: ConsoleBridge enables recording,
McpClient enables HumanCLI, PushToTalk enables voice, and the skill modules
(NavigationSkillContainer, PatrollingModule, PersonFollowSkillContainer,
SpeakSkill) decide which HumanCLI tools are offered. Exploration only runs from
HumanCLI.

Vector shows the Go2 mapping and navigation modules disabled ("No LiDAR").

Profiles saved before blueprints have no module list; they keep the capability
behavior they had.

## Movement toggle and Stop

`POST /api/hold` keeps the robot in place: the Go2 control gate forwards no teleop
or navigation velocity, and the Vector controller refuses tread driving and ends
a HumanCLI move. HumanCLI can still answer. Space on the keyboard and B on the
controller stop the robot and latch until Release stop.

## Saved robots

`robots.json` lives in the private application data directory. Connect your robot
checks saved robots on the network and offers the first one found for 15 seconds;
it never connects on its own. Add robot asks for the hardware, then its fields. A
recording can be replayed from the same screen, and a Go2 can be connected once
by IP without saving.

## Connecting to a Go2

- **Encryption key.** Go2 firmware 1.1.15 and newer refuses the LAN handshake
  without the robot's AES-128 key. Put `UNITREE_AES_128_KEY=<32 hex characters>`
  in the app's private `robot.env` (on a Mac:
  `~/Library/Application Support/Go2 Data Studio/robot.env`). It is read at
  startup, so restart the app after editing. Without it the runtime exits with
  `AesKeyRequiredError`.
- **AP mode** works: switch the Go2 to AP mode in the Unitree app (you choose the
  `GO2-XXXXXX` hotspot name and an 8-digit password), join that network, and use
  Connect once by IP with `192.168.12.1`. Cloud uploads and HumanCLI need
  internet, which the Go2's hotspot does not provide.
- **Office or guest Wi-Fi** often isolates devices from each other. The Go2 then
  shows up in the Unitree app (Bluetooth or Unitree's cloud) but never answers
  this app. Use AP mode, a phone hotspot, a private router, or the Go2's wired
  address `192.168.123.161`.
- **One app at a time.** Close the Unitree app before connecting; the Go2 rejects
  a second connection.

## Spaces

A new data directory starts with a space called "Starting space". Spaces are
chosen and renamed in the session sidebar; the recording bar shows the current
one.

## Validation

Backend tests cover the catalog rules, the add-only runtime contract, tool
filtering, the hold, sign out, the Starting space and the start flow. Frontend
tests cover onboarding, Start Session, always-on keyboard driving, the HumanCLI
takeover prompt, the movement toggle, recordings and HumanCLI. The full flow was
exercised in a browser against the real backend on a replay at 1280×800. On
2026-10-01 a supervised session on a physical Go2 over AP mode worked from the Mac
app. Vector and the Steam Deck build still need supervised testing.

Go2 control allows a 10-second gap after the last position update (all active
modes), LiDAR update or costmap update (exploration and agent navigation). The
connection supervisor uses the same 10-second position threshold.
