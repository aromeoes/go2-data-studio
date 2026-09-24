# Go2 Data Studio

A local web application for connecting a Unitree Go2, recording spaces, generating maps, and backing up datasets to DimOS Cloud.

The custom interface uses the DimOS Web SDK. DimOS provides robot connectivity, mapping, A* navigation, frontier exploration, SQLite storage and the MCP agent behind HumanCLI. The upstream Cockpit interface is not launched.

## Desktop preview

An Electron development preview adds local backend management and analog controller input for standalone Mac and Steam Deck operation. It currently requires a separately installed DimOS runtime. See [desktop setup, validation and remaining release work](docs/DESKTOP.md).

## Features

* Teleoperation with W/S for forward/backward, A/D for turning, and Q/E for sideways movement.
* Switching between Teleop, autonomous exploration and HumanCLI, with control leases and sensor freshness checks.
* LiDAR, camera, odometry, transforms and camera calibration recording, organized into spaces and segments.
* Recording size, sensor health, battery and navigation status in the dashboard.
* Versioned map generation, quality statistics and Rerun inspection.
* DimOS Cloud upload progress, pause/resume and persistent backup status.
* HumanCLI with a configurable tool-capable model, including optional camera questions.

## Requirements

This is a source checkout application, initially developed and tested on macOS. Finder, Terminal launchers and local viewer integration are macOS-specific. Linux and Windows operation has not been validated.

You need:

* A separately installed DimOS checkout at revision `c1c3cdc9d2ee54ca72259465688395699d7d99a2` (version 0.0.14), with its working Python 3.12+ environment in `.venv`.
* The Go2 WebRTC driver and DimOS mapping, navigation, agent and web relay dependencies installed in that environment. This repository does not install or replace the framework.
* Node.js and npm to build the frontend, and Deno for the DimOS relay.
* A browser supporting the Web SDK's WebTransport connection.
* For physical use, a Go2 on the same reachable Wi-Fi network and an operator present.

The framework is pinned deliberately. Do not substitute a newer revision without validating the integration. See the [DimOS repository](https://github.com/dimensionalOS/dimos) for framework setup.

## Setup

Clone this repository alongside the configured runtime, or export its location:

```sh
export DIMOS_RUNTIME=/absolute/path/to/dimos-runtime
export GO2_SPACES="$HOME/Go2Spaces"
# Optional: use your own serial to rediscover this Go2 when its DHCP address changes.
export GO2_SERIAL=YOUR_GO2_SERIAL
cp .env.example .env
"$DIMOS_RUNTIME/.venv/bin/python" -m pip install -e .
cd web
npm ci
npm run build
cd ..
./start.sh
```

Fill in `ROBOT_IP` and, if required by your robot configuration, `UNITREE_AES_128_KEY` in `.env`. The IP can also be entered in the dashboard. Never commit the filled-in file. The default runtime location is the sibling `../dimos-runtime`; `start.sh` checks its revision before starting the application.

Open [the local dashboard](http://127.0.0.1:8780). Startup leaves the robot disconnected and does not request movement. HumanCLI's model configuration can be set through **Agent model** or the provider settings in `.env`. An API key is needed only for the provider you select; local Ollama does not require one. Camera requests require a vision-capable model and explicit enablement. See [HumanCLI](docs/HUMANCLI.md).

## Configuration

Export these deployment settings in the shell before starting. The application `.env` contains robot connection and HumanCLI settings; it does not configure the launcher options below.

| Variable | Default or purpose |
| :--- | :--- |
| `DIMOS_RUNTIME` | Sibling `../dimos-runtime`, containing `.venv` |
| `GO2_SPACES` | `~/Go2Spaces`, outside this source tree |
| `GO2_SERIAL` | Empty; set to your robot serial for targeted discovery |
| `GO2_ENV_FILE` | This application's `.env`; optional separate robot credential file |
| `GO2_SETUP_PORT` | `8780`, local dashboard |
| `GO2_RUNTIME_PORT` | `8781`, private runtime |
| `GO2_RELAY_PORT` | `8782`, Web SDK relay |
| `GO2_REPLAY_ONLY` | Set to `1` to reject physical connections |
| `DIMOS_API_KEY` | Optional Cloud credential override; otherwise sign in from the dashboard |

HumanCLI model environment variables take precedence over `.env`, then saved settings. Deployment credentials, recordings and generated maps belong outside Git. `vision.json`, `humancli.json`, `cloud-credentials.json` and relay credentials are private local files.

## Recording and maps

Create a space, connect the robot, wait for sensors, and start recording. Changing control modes keeps the recording session. Saving closes a segment; connection loss may mark a segment interrupted while preserving recorded data.

Generate a map from a saved segment while navigation is paused. Map jobs use DimOS commands and preserve separate versions. PointCloud2 output and Rerun inspection files can be opened from the application. Quality statistics report measured frame/pose coverage and gaps; they do not establish absolute map accuracy. Multi-segment map alignment and patrol configuration are not implemented.

Recordings use the official DimOS SqliteStore. The application currently owns the recording queue and segment lifecycle; replacing that adapter with the standard recorder is follow-up work.

## Cloud backups

Choose **Connect DimOS Cloud**, complete sign-in, then **Upload dataset** on a segment. The application snapshots the SQLite database, uploads through the official Cloud API, and downloads the stored object as a stream to verify its SHA-256 before marking it **Backed up**. Verification adds download traffic. Preparing the snapshot needs approximately one extra recording-size of disk space plus 1 GB headroom.

Uploads contain uncompressed recording databases, not generated maps. Local originals remain in place. Completed parts can be resumed, and backup badges are reconciled with the remote account and local data. The current HTTP client is custom; migrating to the official CloudData Python client is tracked in [follow-up work](docs/CHECKPOINT.md).

## Operating and restarting

Physical operation requires supervision. Before a planned disconnect or software restart, stop movement, have the operator request lie-down, visually confirm the robot is lying down and supported, save the recording and use the guarded disconnect flow. An API acknowledgment does not establish posture. See [AGENTS.md](AGENTS.md).

The Stop control is a software stop, not an electrical emergency stop. Network failure, firmware faults or power loss cannot guarantee a controlled posture. Do not automatically reconnect after a fall. Publishing this source does not validate unattended operation.

## Validation

Tests use mocks and replay; they do not move a physical robot:

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 "$DIMOS_RUNTIME/.venv/bin/python" -m pytest -q
"$DIMOS_RUNTIME/.venv/bin/python" -m ruff check go2_setup tests
python3 scripts/verify_sdk_vendor.py
cd web
npm test
npm run build
```

[Web SDK integration](docs/WEB-SDK.md), [HumanCLI validation](docs/HUMANCLI.md), and [historical validation notes](VALIDATION.md) describe the checks and their limits. Earlier validation entries describe earlier implementations and are retained as history.

## Third-party code

The official DimOS Web SDK and relay snapshot is retained under `vendor/dimos-web`, including its upstream license and provenance manifest. Cockpit source files are included in that unmodified snapshot but are not used as this application's frontend. Run `scripts/verify_sdk_vendor.py` to check the snapshot.
