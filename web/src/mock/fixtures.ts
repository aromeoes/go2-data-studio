/** Static data for mock mode. Catalogs mirror go2_setup/profiles.py and go2_setup/vector/profiles.py. */
import type { Item } from "../types";
import type { SavedRobot, SetupCatalog } from "../SessionSetup";

type Catalog = Omit<SetupCatalog, "robots" | "embodiments">;

export const GO2_CATALOG: Catalog = {
  capabilities: [
    { id: "teleop", name: "Manual driving", detail: "Keyboard or controller driving.", requires: [], modules: ["SDK Teleop"] },
    { id: "camera", name: "Camera", detail: "Live camera and optional visual questions.", requires: [], modules: ["PassiveGo2Connection: camera"] },
    { id: "lidar", name: "LiDAR data", detail: "Receive LiDAR in this app. Does not switch off the robot's sensor.", requires: [], modules: ["PassiveGo2Connection: LiDAR"] },
    { id: "mapping", name: "Live mapping", detail: "Build the 3D map and 2D costmap.", requires: ["lidar"], modules: ["VoxelGridMapper", "CostMapper"] },
    { id: "navigation", name: "Navigation", detail: "Plan movement through mapped space.", requires: ["mapping"], modules: ["ReplanningAStarPlanner"] },
    { id: "exploration", name: "Autonomous exploration", detail: "Choose unexplored areas and navigate to them.", requires: ["navigation"], modules: ["ConsoleExplorer"] },
    { id: "recording", name: "Recording", detail: "Enable recording of selected sensors, position and transforms. Start recording separately.", requires: [], modules: ["ConsoleBridge: SessionWriter / SqliteStore"] },
    { id: "humancli", name: "HumanCLI", detail: "Chat with the robot using tools enabled in this session. Requires a configured model.", requires: [], modules: ["DimOS MCP agent worker (application service)"] },
    { id: "voice", name: "Voice input", detail: "Push to talk. Requires microphone access and configured OpenAI transcription.", requires: ["humancli"], modules: ["Audio capture / transcription (application service)"] },
  ],
  presets: [
    { id: "map-record", name: "Teleop + Recording", description: "Drive manually, map your space and record sensor data.", enabled: ["teleop", "camera", "lidar", "mapping", "recording"] },
    { id: "assistant", name: "Full mode agent", description: "All capabilities, including exploration, HumanCLI and voice.", enabled: ["teleop", "camera", "lidar", "mapping", "navigation", "exploration", "recording", "humancli", "voice"] },
  ],
  required_modules: ["PassiveGo2Connection", "ControlGate", "ConsoleBridge", "ConsoleSDK", "DimOS RelayBridgeModule"],
};

export const VECTOR_CATALOG: Catalog = {
  capabilities: [
    { id: "teleop", name: "Manual driving", detail: "Differential tread driving. No sideways motion.", requires: [], modules: ["VectorConnection: guarded tread control"] },
    { id: "camera", name: "Camera", detail: "Live RGB camera over the DimOS Web SDK.", requires: [], modules: ["VectorConnection: camera"] },
    { id: "faces", name: "Native face recognition", detail: "Read faces recognized by Vector. Names must already be enrolled on the robot.", requires: [], modules: ["VectorConnection: onboard vision"] },
    { id: "humancli", name: "HumanCLI", detail: "Bounded movement, head, lift, speech and expressive animations.", requires: [], modules: ["VectorSkills", "DimOS MCP agent worker"] },
    { id: "voice", name: "Voice input", detail: "Mac/Deck push to talk and paired wire-pod transcript input.", requires: ["humancli"], modules: ["Audio capture / wire-pod bridge"] },
  ],
  presets: [
    { id: "drive", name: "Drive", description: "Camera, sensors and manual tread controls.", enabled: ["teleop", "camera", "faces"] },
    { id: "assistant", name: "Agent assistant", description: "Talk to Vector, use native faces and expressive actions.", enabled: ["teleop", "camera", "faces", "humancli", "voice"] },
  ],
  required_modules: ["VectorConnection", "VectorTelemetry", "ConsoleSDK", "DimOS RelayBridgeModule"],
};

export const STORAGE_ROOT = "/home/deck/.config/Go2 Data Studio/spaces";
export const ACCOUNT = { email: "you@example.com", id: "mock-user-1" };
export const CONSOLE_URL = "https://console.dimensional.org";

const GB = 1e9;

function stats(bytes: number, minutes: number) {
  const clouds = Math.round(minutes * 60 * 10);
  return {
    physical_bytes: bytes,
    duration: minutes * 60,
    gb_per_min: bytes / GB / minutes,
    streams: {
      lidar: { bytes: bytes * 0.62, count: clouds, poses: clouds, gaps_over_1s: 0 },
      color_image: { bytes: bytes * 0.36, count: clouds * 1.5, poses: clouds * 1.5, gaps_over_1s: 0 },
      odom: { bytes: bytes * 0.02, count: clouds * 2, poses: clouds * 2, gaps_over_1s: 0 },
    },
  };
}

export type Seed = {
  robots: SavedRobot[];
  spaces: Item[];
  sessions: Item[];
  segments: Item[];
  maps: Item[];
};

/** A returning user: two saved robots, two spaces, a backed up recording and one pending. */
export function returningUser(now: number): Seed {
  const day = 86400;
  const apartment = `${STORAGE_ROOT}/apartment`;
  const office = `${STORAGE_ROOT}/office`;
  return {
    robots: [
      { id: "robot-go2", name: "My Go2", kind: "go2", ip: "10.15.9.58", serial: "", profile: { preset: "assistant", enabled: GO2_CATALOG.presets[1].enabled } },
      { id: "robot-vector", name: "Vector", kind: "vector", ip: "192.168.1.80", serial: "00e20145", sdk_config: "~/.anki_vector/sdk_config.ini", profile: { preset: "assistant", enabled: VECTOR_CATALOG.presets[1].enabled } },
    ],
    spaces: [
      { id: "space-office", name: "Office", created: now - 2 * day, status: "ready", folder: office },
      { id: "space-apartment", name: "Apartment", created: now - 6 * day, status: "ready", folder: apartment },
    ],
    sessions: [
      { id: "session-office-1", parent: "space-office", created: now - day, status: "closed", folder: `${office}/session-1`, source: "robot" },
      { id: "session-apartment-1", parent: "space-apartment", created: now - 5 * day, status: "closed", folder: `${apartment}/session-1`, source: "robot" },
    ],
    segments: [
      { id: "a41c9e77", parent: "session-office-1", created: now - day, status: "closed", folder: `${office}/session-1`, path: `${office}/session-1/segment-001.db`, stats: stats(1.84 * GB, 6.2) },
      {
        id: "7be20d13", parent: "session-apartment-1", created: now - 5 * day, status: "closed", folder: `${apartment}/session-1`, path: `${apartment}/session-1/segment-001.db`, stats: stats(3.1 * GB, 11.4),
        backup: { name: "Apartment full walkthrough", status: "complete", percent: 100, size: 3.1 * GB, uploaded_bytes: 3.1 * GB, upload_id: "upl_mock_1", owner_id: ACCOUNT.id, verified_at: now - 4 * day },
      },
    ],
    maps: [
      {
        id: "map-apartment-1", parent: "7be20d13", created: now - 4 * day, status: "ready", voxel: 0.1, folder: `${apartment}/session-1/maps/1`,
        map_path: `${apartment}/session-1/maps/1/map.pc2.lcm`, rerun_path: `${apartment}/session-1/maps/1/map.rrd`, log: "map.log",
        quality: { lidar_frames: 6840, lidar_pose_fraction: 1, lidar_gaps_over_1s: 0 },
      },
    ],
  };
}

/** A first launch: nothing saved yet. */
export const firstRun = (): Seed => ({
  robots: [],
  spaces: [{ id: "space-starting", name: "Starting space", created: Date.now() / 1000, status: "ready", folder: `${STORAGE_ROOT}/starting-space` }],
  sessions: [],
  segments: [],
  maps: [],
});

export const vectorReadings = (now: number) => ({
  received: now,
  cliff: { any_detected: false, individual: null },
  proximity: { distance_mm: 184, signal_quality: 0.82, found_object: true, unobstructed: false, lift_in_fov: false },
  imu: { accel: [0.1, -0.2, 9.8], gyro: [0, 0, 0], units: "m/s², rad/s" },
  touch: { detected: false, raw: 4610 },
  power: { volts: 3.92, level: "normal", charging: false, on_charger: false, received: now, percent: null },
  temperature: { head_c: 41, body_c: null, reason: "Body temperature is not exposed by the SDK." },
  head_deg: 12,
  lift_mm: 32,
  wheel_mmps: [0, 0],
  picked_up: false,
  falling: false,
  faces: [],
});
