export type SessionProfile = {
  preset: string;
  enabled: string[];
  kind?: string;
  modules?: string[];
};
export type SavedRobot = {
  id: string;
  name: string;
  kind: string;
  ip: string;
  serial: string;
  sdk_config?: string;
  profile: SessionProfile;
};
/** A module in the Start Session catalog served by the backend. */
export type ModuleDef = {
  id: string;
  icons: string[];
  summary: string;
  official: boolean;
  capabilities: string[];
  requires: string[];
  required?: boolean;
  unavailable?: string;
};
export type Blueprint = {
  id: "teleop" | "custom";
  name: string;
  summary: string;
  recommended: boolean;
  locked: boolean;
  modules: string[];
};
export type SessionCatalog = { modules: ModuleDef[]; blueprints: Blueprint[] };
export type SetupCatalog = {
  robots: SavedRobot[];
  sessions: Record<"go2" | "vector", SessionCatalog>;
};
export type Backup = {
  name?: string;
  filename?: string;
  status: string;
  percent?: number;
  uploaded_bytes?: number;
  size?: number;
  upload_id?: string;
  owner_id?: string;
  verified_at?: number;
  error?: string | null;
};
export type Item = {
  backup?: Backup;
  id: string;
  parent?: string;
  name?: string;
  created: number;
  status: string;
  folder: string;
  path?: string;
  stats?: Stats;
  source?: string;
  voxel?: number;
  error?: string;
  map_path?: string;
  rerun_path?: string;
  quality?: {
    lidar_frames: number;
    lidar_pose_fraction: number | null;
    lidar_gaps_over_1s: number;
  };
  log?: string;
};
export type Stats = {
  physical_bytes: number;
  duration: number;
  gb_per_min: number;
  streams: Record<
    string,
    { bytes: number; count: number; poses: number; gaps_over_1s: number }
  >;
};
export type Grid = {
  width: number;
  height: number;
  resolution: number;
  origin: number[];
  cells: number[];
  known_m2: number;
  received: number;
};
export type State = {
  vector_services?: { state: string; message: string; host?: string | null; voice_ready?: boolean };
  robot_id?: string | null;
  robot_kind?: "go2" | "vector";
  profile?: SessionProfile;
  /** Modules of the running session; null for sessions from before blueprints. */
  selected_modules?: string[] | null;
  /** True while START adds modules to the running connection. */
  loading_modules?: boolean;
  /** Movement toggle: the robot stays in place while true. */
  hold?: boolean;
  modules?: string[];
  cloud?: {
    configured: boolean;
    account: { email: string; id: string } | null;
    login: { url: string; code: string; expires_at: number } | null;
    error: string | null;
    active_segment: string | null;
    console_url: string;
    quota: { used_total: number; pct: number; state: string } | null;
  };
  connection: string;
  error: string | null;
  ip: string;
  replay: boolean;
  mode: string;
  epoch: number;
  disk_free: number;
  storage_root: string;
  dimos_sha: string;
  session: Item | null;
  segment: Item | null;
  stats: Stats | null;
  spaces: Item[];
  sessions: Item[];
  segments: Item[];
  maps: Item[];
  events: { id: number; ts: number; message: string }[];
  telemetry: {
    skills?: import("./RobotSkillStatus").RobotSkillState | null;
    vector?: import("./VectorSensors").VectorReadings;
    battery?: { percent: number | null; received: number | null };
    navigation?: NavigationInfo;
    map?: Grid;
    pose?: { x: number; y: number; yaw: number };
    path?: number[][];
    sensors?: Record<string, { received: number; count: number }>;
    recording?: { dropped: number; errors: number };
    control?: {
      estop: boolean;
      ownership?: string;
      action?: {
        name: string;
        status: string;
        error?: string;
        result?: { found?: boolean; message?: string };
      };
      stop_reason?: string;
      nav_received?: number;
      nav_forwarded?: number;
    };
    motion?: {
      sent: number;
      error?: string;
      observed_speed?: number;
      observed_yaw_rate?: number;
    };
  };
  agent: {
    model?: import("./HumanCLISettings").AgentModel;
    engine?: string;
    conversation_id?: string;
    capabilities?: { name: string; example: string; detail: string }[];
    vision?: { configured: boolean; enabled: boolean; model: string };
    busy: boolean;
    messages: { role: string; text: string; ts: number }[];
  };
};

export type NavigationInfo = {
  phase: string;
  title: string;
  detail: string;
  warnings: { code: string; text: string; ts: number; source: string }[];
  events: {
    code: string;
    text: string;
    ts: number;
    count: number;
    source: string;
  }[];
};
