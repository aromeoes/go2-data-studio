# Robots and session profiles

The setup flow is saved robot → passive connection → session preset → optional customization → explicit start. Go2 and Anki Vector have separate capability catalogs. Robot instances are stored separately from spaces and recordings.

## Presets

| Preset | Default capabilities |
| --- | --- |
| Teleop + Recording | Manual driving, camera, LiDAR data, live mapping, recording |
| Full mode agent | All capabilities, including navigation, autonomous exploration, recording, HumanCLI and voice |

Starting a preset enables capabilities. It never starts movement, exploration or recording. The operator selects Explore or Record separately. Full mode agent includes autonomous exploration; Teleop + Recording can add it through Customize. Last applied settings are saved per robot.

Customization is capability-based. Dependencies are added when enabling a dependent feature; removing a prerequisite removes its dependents and explains the change. The backend validates the entire selection independently. Required connection, control, telemetry and SDK modules cannot be removed.

## Actual runtime behavior

`profiles.py` defines the supported capability catalog. `runtime.build_blueprint()` compiles it into a real DimOS blueprint. Preview omits mapping and navigation modules. Teleop + Recording includes mapping but omits ReplanningAStarPlanner and ConsoleExplorer. Manual mapping can omit planner and explorer. Camera and LiDAR options control sensor consumption in PassiveGo2Connection; they never command physical LiDAR shutdown. Position updates remain required for control. Connection credentials still come from this installation's existing Go2 configuration.

ConsoleBridge remains present for telemetry. Its recording helper can only start when recording is enabled. Go2 recording contains enabled sensor streams, odometry, transforms, requested Teleop velocities and final output velocities, using DimOS SqliteStore. Recorded session metadata includes robot ID and profile. The common SDK channel manifest stays stable; disabled sensors produce no application frames. ControlGate independently rejects disabled motion modes.

HumanCLI and voice are application services, not separate blueprint checkboxes pretending to be DimOS modules. HumanCLI advertises and accepts only tools supported by the applied profile. Plain conversation does not require a map. Agent navigation still requires recent odometry, LiDAR and costmap data, and the normal control lease. Voice additionally requires microphone permission and configured OpenAI transcription.

## Reconfiguration

Module changes are staged, not hot-swapped. Applying them requires an online, idle connection and no active recording. Start session applies directly, with no posture validation. The existing guarded connection is closed, then a new runtime starts with the selected profile, remaining idle. Replay reconfiguration restarts the replay. Credentials are not included in saved profiles.

The first Connect starts a camera/status preview blueprint. Consequently the initial Start session also rebuilds the runtime. This is an explicit first-version limitation, avoiding unvalidated live module replacement.

An application restart does not automatically connect or move a robot. A transport reconnect within an existing session retains its capabilities but does not resume movement. Legacy raw-IP connection and replay API clients retain the former full profile for compatibility; the new saved-robot flow always connects in preview mode.

## Saved robots

`robots.json` lives in the private application data directory. An existing valid saved Go2 IP is imported once as My Go2. Add/Edit accepts a private IPv4 address and optional serial. Check availability tests the saved connection service with a bounded timeout. It reports Reachable, not authenticated identity or readiness for movement. This release does not add a general network scanning screen or simultaneous robot control.

## Validation

Tests cover actual DimOS blueprint composition without launching hardware, dependency rejection, robot migration/persistence, guarded profile application, backend capability enforcement, conditional agent tools, stale navigation input, and setup interactions. UI checks use an isolated mock server at 1280×800 and 800×600. Physical Go2 session rebuilds and sensor operation require operator acceptance testing after installation.

Go2 control allows a 10-second gap after the last position update (all active modes), LiDAR update or costmap update (exploration and agent navigation). Each required stream must have supplied an initial update. The connection supervisor uses the same 10-second position threshold. Controller release, page control leases, emergency Stop and transport failures retain their independent behavior.

Customize uses compact single-line capability labels. Descriptions and prerequisites are available in hover tooltips; dependency validation is unchanged. Older Drive profiles are migrated to Teleop + Recording with their selected capabilities preserved.
