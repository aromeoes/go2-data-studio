# Anki Vector

Vector and Go2 run separate DimOS blueprints. Only one saved robot session runs at
a time. The shared app, Web SDK relay, HumanCLI model configuration, camera viewer
and cloud library remain reusable. The Vector runtime never imports Go2's driver
or mapping pipeline.

## Modules and presets

* `VectorConnection`: wire-pod SDK transport, camera `Out[Image]`, local pose
  `Out[PoseStamped]`, sensor state stream, guarded differential drive and watchdog.
* `VectorTelemetry`: subscribes to sensor state and provides the dashboard snapshot.
* `VectorSkills`: DimOS `@skill` methods injected with `VectorActionSpec`, calling
  the guarded connection via RPC. The app's MCP tool schemas add the session epoch.
* Shared `ConsoleSDK` and DimOS RelayBridgeModule provide the existing Web SDK UI.

Drive enables camera, native faces and manual controls. Agent assistant adds
HumanCLI and voice. Preview observes the robot without taking behavior control.
No Vector mapping, exploration, map generation or recording capability is claimed.
The existing library can still show recordings made with Go2.

## Pairing and installation

Vector must already be paired with wire-pod. On the computer running DIMENSIONAL,
install the maintained SDK into the validated DimOS dependency environment:

```sh
uv pip install --python "$DIMOS_RUNTIME/.venv/bin/python" -e ".[vector]"
```

The desktop runtime build checks that SDK 0.8.1 is included. The Linux dependency
lock adds aiogrpc 1.8 and SDK 0.8.1 without replacing Go2 dependencies. Rebuild the
runtime and Electron bundle using the existing Mac or Linux build instructions.
Do not modify an installed live runtime or restart a connected Go2 to deploy this.

Use the SDK's wire-pod pairing flow, or securely transfer an existing pairing with
the owner's permission. Keep its config and certificate outside the source tree.
The config INI contains a section for the robot serial, with `name`, `cert`, `guid`
and optionally `ip`. `cert` must reference a file on this computer. Restrict config
permissions to the current user. Never commit or paste the authorization token.

Choose Add robot, Anki Vector, name, LAN IP, serial and local SDK configuration
path. The default path is `~/.anki_vector/sdk_config.ini`. Connect starts the
required Vector modules with movement idle; START adds the chosen blueprint's
modules (for example HumanCLI and VectorSkills) to the same connection.
There is no supported-surface checkbox for Vector.
Connection uses TLS with the robot certificate and the robot's own access token.
wire-pod remains your speech backend; it does not proxy the camera or tread control.

## Control and personality

SDK DEFAULT_PRIORITY retains mandatory physical reactions. Override priority is
never used. Teleop acquires app control. Keyboard W/S moves, A/D turns, and the
controller uses left-stick forward/back plus right-stick turn. Vector cannot
strafe. Treads are bounded at 120 mm/s. SDK angular input uses nominal 70 mm tread
spacing and is not a calibrated angular positioning command.

HumanCLI keeps native personality active between actions, acquiring control only
while executing them. This is necessary because SDK default priority suppresses
Vector's wake-word behavior. Vector can move under its native behaviors between
agent actions. Stop acquires/holds app control; it does not resume personality.
After clearing Stop, the operator can select a control mode or Resume personality.
Disconnecting returns the robot to native behavior.

Movement tools accept a single 3–50 cm forward/backward request per message. They
measure progress with local odometry, stop on changed pose origin or heading,
cliff/pickup/fall, stale state, expired lease, obstructed forward proximity or timeout.
They do not plan a route. There is no rear obstacle sensor; supervise backward
movement. The local watchdog cannot guarantee a physical stop after a network or
robot failure. Vector's own mandatory reactions remain enabled.

Head (-22 to 45 degrees), lift (0–1 normalized height), native speech and selected
animation triggers are available as skills. Expressive animations suppress tread
motion. Trigger availability depends on firmware. Tool acceptance is separate from
completion; check the action status shown in the UI or ask HumanCLI for status.

Native face names stay on Vector. `visible_faces` reads current onboard recognition;
`find_person` performs a bounded head-only scan for an already enrolled name. It
neither identifies people from photos nor roams around a room. Enroll names using
Vector's normal setup first. Selecting Camera does not add depth or Go2 mapping.

## Sensor contract

The panel reports combined cliff detection, proximity distance/quality/occlusion,
raw SDK accelerometer and gyro axes, touch boolean/raw value, battery voltage/level,
charging state, head angle, lift height and wheel speeds. It marks stale readings.
Individual cliff values, battery percentage and internal temperatures are not
exposed by this SDK and are explicitly unavailable. IMU readings retain SDK raw
units until units are verified against the paired firmware. Pose is local to its
reported origin, not a persistent map frame.

## Local Vector services and voice

The desktop app bundles wire-pod and its HumanCLI plugin for Apple Silicon macOS
and x64 Linux/Steam Deck. It runs as a private subprocess only during a physical
Vector session, including Preview and Drive. Disconnecting, switching to Go2, or
closing the backend stops that owned process. Replays never start it. SDK camera,
sensors and movement continue independently if voice services fail.

Vector's microphone follows this path:

```
Vector → local wire-pod audio decoder → app transcription → native wire-pod intent
                                                       → HumanCLI (Dimensional prefix)
```

The app reuses the existing OpenAI key in HumanCLI settings for transcription.
Internet is required for this transcription and cloud models. The key stays in the
app; wire-pod gets only a private token for the three restricted voice endpoints.
Deck/Mac push to talk still uses the existing app microphone route. SDK microphone
streaming is unfinished and is not used.

1. Stop other wire-pod instances, including an old server on another computer.
   Only one computer may advertise `escapepod.local` on the robot's LAN. Discovery
   conflicts appear in Vector controls and are retried without killing other services.
2. Connect a saved Vector. Local services start automatically, using its existing
   private pairing. No firmware flash, activation or factory reset is performed.
3. For agent requests, select Agent assistant, enable voice, and select HumanCLI.
   Say “Hey Vector”, then “Dimensional look up”. Keep the app active for its control
   heartbeat. Ordinary Vector commands retain native intent handling. Native
   personality and voice actions may move the robot.
4. The status below Vector controls reports startup, missing runtime, network
   conflicts, missing transcription key and transcription failures.

The old `wirepod-ssh.json` setting is ignored. No Dell, SSH, container runtime or
compiler is required on a user's Mac or Deck. Each computer needs its own private
SDK pairing files. Pairing data and jdocs remain under the app's private data folder,
outside packaged assets. Native face memories remain on the robot.

The robot-facing TLS endpoint is port 8084, for modern escape-pod firmware. The
wire-pod administrative interface is restricted to `127.0.0.1:18084`. Its optional
port-80 connection checker exposes only `/ok` and `/ok:80`, not administrative or
SDK routes. macOS can bind this port as the logged-in user. On Linux, if the OS
restricts ports below 1024, run the included `enable-vector-network.sh` once after
installation while the app is closed. It grants only `cap_net_bind_service` to the
wire-pod binary. Repeat after replacing that binary. Do not run Electron as root.

Each agent transcript is bound to robot serial, saved robot, conversation and
control epoch; it expires after eight seconds and is deduplicated. The plugin
never retries an uncertain submission. Disabling HumanCLI stops agent submission
while retaining native services. Replies appear in chat; ask HumanCLI to speak
when you want additional robot speech.

### Building the sidecar

Run `python3 desktop/build-wirepod.py` before packaging Electron. Build with Go
1.22.4 and the Opus development library on each target platform. The build fetches
wire-pod revision `347c45f7a4dba9adba7fa003c08248d301f19393`, applies the checked-in
integration patch, and builds server and plugin with identical flags/toolchain.
Mac links Opus statically; Linux includes its shared library with a relative rpath.
The app bundle contains public escape-pod TLS assets, language intents, license
notices and the modified corresponding source. It contains no user's credentials.

`python3 desktop/smoke-wirepod.py desktop/runtime/wirepod` checks TLS startup,
plugin loading, loopback administration and clean shutdown without advertising
or connecting to a robot. `VECTOR_WIREPOD_RUNTIME` can select a built sidecar for
development; packaged builds use `runtime/wirepod`.

## Validation status

Automated checks: 143 backend tests, 39 frontend tests, six desktop tests (one
Linux-only test skipped on Mac), and two wire-pod plugin tests. A real DimOS worker
smoke test exercises typed camera/pose streams and skill injection with synthetic
hardware:

```sh
PYTHONPATH=.:tests "$DIMOS_RUNTIME/.venv/bin/python" tests/vector_graph_smoke.py
```

Hardware verification covers an authenticated passive Vector connection, live
sensor telemetry through the application blueprint, charge level and charger
status, and clean shutdown. No app movement control was acquired. An initial direct
SDK camera check received 800 × 600 frames; later checks on the charger reported
streaming enabled but received no frames. Sleep is a hypothesis, not a verified
cause. Missing frames no longer block sensor data or disconnect. Camera RPC
cancellation is explicitly scoped around the SDK decoder and events, with a
regression test for a stream that never delivers its first frame.

The native local sidecar and plugin have passed isolated Mac startup/shutdown
checks, including TLS and administrative-listener isolation. Discovery correctly
detects the existing Dell host. The Linux sidecar passed the same checks in a clean container as an ordinary
user with privileged ports restricted. This is Linux runtime validation; Steam
Deck hardware deployment remains pending while that device is unreachable. Spoken
end-to-end interaction still needs an awake robot and an active HumanCLI session.

Camera streams with no frames for five seconds are closed and reopened locally.
Recovery never acquires motor control or toggles the global camera flag. Direct
connection avoids the former preview-to-preset rebuild and its relay expiration delay.


### Pairing recovery and camera startup

A rejected SDK token triggers one renewal attempt through Vector's official
`UserAuthentication` RPC, using the existing pairing and pinned robot certificate.
The renewed token stays in the private SDK INI. No activation, factory reset,
behavior control or motion is requested. If renewal fails, the dashboard reports
the pairing error instead of only reporting that the DimOS process exited.

Local wire-pod preserves `vic.AppTokens` alongside `botSdkInfo.json`, keeps existing
authorized tokens and other robots' documents, and never replaces a refreshed
wire-pod token with an older SDK token. Malformed authorization data is reported
rather than overwritten.

The camera waits up to 15 seconds for its first frame, then recovers a stream
that has stalled for 5 seconds. Stream cancellation drains its pending read before
closing the legacy SDK adapter.

The camera adapter explicitly sends `EnableImageStreaming(enable=True)` before
each `CameraFeed` subscription, as required by escape-pod firmware. Subscribing
alone can leave the stream open with no frames. This camera-only RPC does not
request behavior or motor control. Sensor telemetry includes `camera_stream`
status, retry count, decoded frame count and last-frame timestamp for diagnostics.


### Deck steering and response

Hold L1 with centered sticks to acquire Teleop. The left stick drives forward/back
and steers left/right. The right stick also turns when left-stick steering is
centered. Vector uses a linear stick response outside the 18% deadzone, a maximum
turn rate of 1.5 rad/s, and the existing 120 mm/s tread-speed limit. Go2 retains
its sideways movement and existing input curve. Releasing L1 still stops.

An obstacle or occluded front proximity sensor blocks forward commands while
keeping the Teleop lease available for deliberate reverse or in-place turning.
Cliff, pickup, falling, stale sensors and expired leases still stop the session.

Repeated L1 acquisition reuses SDK control only when Vector still reports it as
granted. Otherwise the normal default-priority acquisition is required. Native
reactions retain their priority. Telemetry `vector.control_transport` reports
command count, latest motor acknowledgement duration (`ack_ms`) and the latest
SDK acquisition duration (`acquire_ms`). Acknowledgement is acceptance, not proof
of physical movement or an end-to-end joystick latency measurement.
