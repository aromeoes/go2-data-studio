# Go2 recording interruption investigation

Investigated 2026-09-21. No motion, posture, disconnect, or restart commands were issued during this investigation. The operator confirmed that the recording stopped and the robot stayed standing.

## Confirmed findings

- Recording segment: `88d2ea81e60b435a`, session `750bb3ec4eca4a6e`.
- Sensor samples stop at approximately 17:09:53 Argentina time. Supervisor reports "Robot position updates stopped arriving." at 17:10:10 and reports reconnection at 17:10:20.
- The supervisor initiates recovery when odometry is older than five seconds, once startup grace has elapsed. It stops the runtime, marks the current segment interrupted, clears motion authority, and reconnects. The event is written after termination, which can take twelve seconds.
- The file passes SQLite quick_check. It contains 246.17 seconds, 1.09 GB including sidecars, 1,900 LiDAR frames, 3,516 camera frames, and 4,605 odometry samples.
- No gaps over one second in LiDAR, camera, or odometry before the final interruption.
- Recorded timestamps show at most 9.3 ms between message timestamp and the writer's append call. This measures arrival/queue delay, not the full disk commit latency. No growing backlog is visible in these timestamps.
- The application caps forward/backward speed at 0.3 m/s, lateral speed at 0.2 m/s, and yaw at 0.5 rad/s in both Teleop and navigation.
- Recorded odometry during sustained Teleop reaches approximately 0.25 to 0.26 m/s. The last thirty-second windows average approximately 0.21 m/s including pauses. This is consistent with the configured speed cap.
- Exploration logs repeatedly report initial rotation, obstacle detection, stuck detection and replanning. These explain additional pauses during exploration but do not identify why odometry stopped later.
- Current post-reconnection measurements: 20/20 ping responses, approximately 8.9 ms mean; 132 dashboard reads with 29.5 ms median and 59.2 ms maximum latency, no errors. These measurements do not establish network conditions at the historical failure.
- Free storage is approximately 513 GB. No contemporaneous Python crash report was found.
- LiDAR stopped independently while other sensors remained fresh after reconnection. This coincided with the user's later posture operations; it is not sufficient evidence of the recording failure's cause.
- The user reports slowness in both modes and confirms the Unitree phone app was not connected simultaneously.

## What remains unproven

The precise cause of missing odometry is unknown. Existing logs cannot distinguish a Go2/WebRTC sensor interruption from a local processing or transport stall. There is no evidence that disk throughput caused this incident. A paired recording-on/off motion test has not been performed, so an additional recording-dependent slowdown is not ruled out.

## Diagnostics change

Patch: `go2-recording-diagnostics.patch`.

- Preserve the last writer counters, queue depth, dropped frames, and errors when a recording is interrupted.
- Save the last 90 status samples before recovery, including sensor ages, control lease state, motion commands, observed velocity, recorder state, and status RPC duration.
- Add connection-side sensor counters and publication timestamps, stream errors, WebRTC/ICE state, and outgoing channel buffer size to distinguish source failures from downstream silence.
- Store the interruption reason and diagnostic report path with the segment.
- Exclude camera frames, map cells, credentials, and prompts from diagnostic reports.

The changes do not change speed limits, safety timeouts, autonomous planning, or reconnection behavior. They diagnose the interruption; they are not a claimed fix for its unknown underlying cause.

The operator visually confirmed Go2 was lying down and supported and authorized activation. The guarded disconnect completed, and the application was restarted with diagnostics enabled. All 62 tests pass, lint passes, and the frontend builds. The dashboard displays the speed selector correctly. The user subsequently gave explicit approval to reconnect with movement idle. Reconnection succeeded: WebRTC connected, ICE completed, channel open, zero buffered bytes, and zero movement commands sent. Odometry, camera, and battery updates are fresh. After approximately thirty seconds, no decoded LiDAR frames had arrived at the source subscriber; no LiDAR stream error was reported. Go2 remained in idle mode. The absence of LiDAR frames is recorded as a current limitation, not attributed to a specific cause.

## Requested speed change

The user requested removal of the 0.3 m/s cap and asked for the framework default. Verified through the GitHub API at pinned commit c1c3cdc9d2ee54ca72259465688395699d7d99a2:

- Go2 keyboard Teleop default: 0.5 m/s, with a 0.5 slow multiplier and a 2.0 boost multiplier, from dimos/robot/unitree/keyboard_teleop.py.
- Navigation local planner nominal speed: 0.55 m/s, from dimos/navigation/replanning_a_star/local_planner.py.

Removed the x-axis clamp in the shared control gate and API validation. Teleop now selects 0.25, 0.5 (default), or 1.0 m/s before enabling controls. Navigation uses the upstream planner output. Lateral and yaw settings remain 0.2 m/s and 0.5 rad/s; nonfinite commands remain invalid, and command leases and stops remain active. No physical speed test was performed.


## LiDAR follow-up

On reconnection, the source received no decoded LiDAR frames while camera, odometry and battery remained live. Inspection found that the connection subscribed to compressed voxel data but did not explicitly enable LiDAR. Added an uppercase `ON` message on `rt/utlidar/switch` for every physical connection, repeated five times at 100 ms intervals, plus a subscription to `rt/utlidar/lidar_state`. Replay never sends these messages. No motor/posture commands are part of this sensor initialization.

Payload reference: [Unitree SDK2 LiDAR switch example](https://github.com/unitreerobotics/unitree_sdk2_python/blob/master/example/go2/high_level/go2_utlidar_switch.py). Subscription/retry reference: [driver maintainer's LiDAR client](https://github.com/legion1581/unitree_ui/blob/main/docs/lidar.md).

This startup correction did not by itself restore the missing compressed voxel stream. The sensor subsequently reported approximately 15 Hz cloud generation, error_state 0, and cloud_packet_loss_rate 0, while the application's compressed voxel frame count remained zero. This distinguishes sensor hardware operation from the missing processed mapping feed. It does not yet distinguish robot-side mapping output from WebRTC delivery/subscription failure. The operator opted to power-cycle Go2 before any standing test. All 65 tests pass.


## Operator power-cycle outcome

The operator powered Go2 off and on. Read-only monitoring observed the console transition from reconnecting to connecting to online automatically, without movement authority. Within approximately three seconds of going online, the bridge had received 25 LiDAR frames and a live map. Both LiDAR and odometry were approximately 0.46 seconds old at that sample. The new connection had sent zero movement commands. The sensor continued to report approximately 15.4 Hz, error_state 0 and zero cloud packet loss.

This demonstrates recovery of the processed mapping stream after the robot power cycle. It supports a robot-side mapping/session stall as a hypothesis but does not conclusively identify the underlying cause, nor establish that the earlier recording interruptions had the same cause. No standing or walking experiment was performed.
