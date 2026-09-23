# Web SDK integration

The console keeps its existing React design. Live robot data and browser robot commands use the official DimOS Web SDK, WebTransport relay and RelayBridgeModule. The Cockpit frontend is neither built nor served.

## Pinned upstream

Both Python runtime and browser SDK are pinned to DimensionalOS/dimos revision `c1c3cdc9d2ee54ca72259465688395699d7d99a2`. The official `web/` directory and LICENSE were downloaded from the GitHub API into `vendor/dimos-web`. `vendor/dimos-web-source.json` records SHA-256 checksums of all 133 upstream files. Run `python3 scripts/verify_sdk_vendor.py` to check them. No local framework checkout was modified.

Vite and TypeScript resolve `@dimos/sdk` and `@dimos/shared` to those unmodified sources. The built console bundles only its SDK imports. Upstream Cockpit sources are retained as part of the exact monorepo snapshot but are not imported by our frontend; the relay reports `cockpit=False`.

At this revision the SDK's Teleop machine is an internal export. `web/src/sdk.ts` is the single adaptation point. Upgrade the Python runtime and vendored SDK together, rerun the lease and replay checks, and replace that internal import when upstream provides a stable public Teleop API.

## Responsibilities

| Path | Responsibility |
| --- | --- |
| SDK `color_image`, `odom`, `global_costmap` | Native JPEG, pose and compressed occupancy-grid streams |
| SDK `tele_cmd_vel` | Exclusive Teleop lease, generation fencing, 15 Hz twist datagrams, 300 ms bridge watchdog |
| SDK `console_command`, `console_results` | Mode changes, posture, Stop, clear Stop and HumanCLI with correlated application completion |
| SDK `console_heartbeat` | Renew the application's mode/epoch guard without blocking behind posture commands |
| SDK `console_state` | Battery, navigation messages, path, recording metrics, catalog and agent transcript |
| Local application HTTP | Initial connection/disconnection, file catalog when offline, recording start/save, map jobs, Cloud uploads and secret configuration |
| Private runtime HTTP | Existing product orchestration and diagnostics inside the local backend |

Python's `cockpit()` authoring helper compiles the official bridge manifest. Its Teleop authoring object supplies the specialized protocol channel; presentation metadata is removed, leaving no panels or layout. This does not launch the Cockpit application.

Robot-side Unitree WebRTC, mapping, planning, recording, vision credentials and Cloud upload handling remain in their existing modules. This migration does not establish a fix for robot firmware or LiDAR stalls.

## Lifecycle and controls

The local application owns an authenticated relay on loopback port 8782. Robot and viewer tokens are separate, generated per application run, written to a 0600 file under the data directory and omitted from logs and command lines. The browser obtains only the viewer token through the same-origin application. Robot reconnection keeps the relay alive. Relay failure restarts only the relay, and the SDK and bridge reconnect to its fresh certificate and endpoint.

SDK delivery acknowledgement is not reported as command completion. Commands carry an id and creation time; expired commands and duplicate ids are rejected or ignored. Results return on the result channel. An unknown outcome is never automatically retried. Stop has a separate queue, and commands queued before Stop cannot re-enable motion. A second console cannot take an active application's control ownership. Existing epoch, sensor freshness, stop-latch and posture guards remain enforced.

The UI uses the SDK Teleop machine to handle lease acquisition, key release and disconnection. W/S move forward/back, Q/E strafe, A/D turn. Forward defaults to 0.5 m/s, with 0.25 and 1.0 selectable. Existing lateral and angular hardware bounds remain. No motion is resumed automatically after a browser or relay disconnect.

The SDK session is required for browser movement controls. Offline HTTP catalog access cannot silently become a movement fallback. Camera blobs are revoked on replacement, and map/pose/camera state is cleared on connection loss.

## Validation on 2026-09-22

- 71 Python tests and 5 frontend SDK adapter tests passed; Ruff and production build passed.
- Actual authenticated relay and Python bridge connected through WebTransport in the Codex browser.
- Camera, pose and growing occupancy map displayed in the existing UI.
- Teleop lease armed through the actual SDK and disarmed after replay ended.
- HumanCLI accepted `walk one meter backward`, returned its DimOS goal, then handed control to autonomous exploration. Planner commands and navigation messages appeared.
- Recording continued through mode changes. Saved test dataset: 0.50 GB, 856 LiDAR frames, about 1.8 minutes. SQLite quick_check returned `ok`; camera_info, color_image, lidar, odom and tf streams were present.
- Unit tests cover ungranted/refused leases, Q/E and A/D mapping, zero on release followed by silence, connection-loss disarm, mode and odometry guards, multiple viewers, command expiry/deduplication and urgent Stop.
- Testing used isolated ports 8790/8791/8792, temporary data, no vision or Cloud credentials, and `GO2_REPLAY_ONLY=1`, which rejects physical connections at both connect and process launch boundaries.

Physical walking, real battery readings and camera-to-OpenAI calls were not repeated during this migration. Cloud behavior is covered by the existing tests; no new cloud dataset was uploaded from the isolated environment.

## Run and activate

Build with `npm ci`, `npm run build` and `npm test` inside `web/`. Deno must be installed and its relay dependencies cached before offline use. Start with the existing `start.sh`; it verifies the pinned Python runtime revision. `GO2_RELAY_PORT` defaults to 8782 and may be overridden alongside application/runtime ports for isolated instances.

Use `GO2_REPLAY_ONLY=1` and a separate `GO2_SPACES` directory for replay testing. This flag blocks physical robot launches even if a connection is requested accidentally.

The physical application must only be restarted after following AGENTS.md: stop motion, have the operator confirm Go2 is lying down and supported (or confirm it is powered off), save any recording, and use guarded disconnect. Until that confirmation, keep the candidate isolated from the application on port 8780. Do not copy changed runtime files into its working directory while its supervisor may reconnect.
