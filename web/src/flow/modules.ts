/**
 * Module catalog for the Start Session screen. Names are the real DimOS (or app)
 * module classes; icons and summaries say what each one does in plain terms.
 * First draft for review: the lists and wording are expected to change.
 */
import {
  Bot,
  Box,
  Camera,
  Compass,
  Database,
  Footprints,
  Gamepad2,
  Map,
  MapPin,
  Mic,
  PawPrint,
  Radar,
  Radio,
  Route,
  TriangleAlert,
  UserRound,
  Volume2,
  type LucideIcon,
} from "lucide-react";

export type ModuleDef = {
  /** Module class name as it appears in DimOS or in this app. */
  id: string;
  icons: LucideIcon[];
  summary: string;
  /** True for DimOS modules, false for modules this app adds. */
  official: boolean;
  /** Backend capabilities this module turns on. */
  capabilities: string[];
  requires: string[];
  /** Always part of a session; cannot be unselected. */
  required?: boolean;
  /** Short reason this module cannot run on this robot. Shown disabled. */
  unavailable?: string;
};

export type Blueprint = {
  id: "teleop" | "custom";
  name: string;
  summary: string;
  recommended?: boolean;
  /** Modules cannot be changed in a locked blueprint. */
  locked: boolean;
  modules: string[];
};

export type Embodiment = { modules: ModuleDef[]; blueprints: Blueprint[] };

const AGENT = "McpClient";
const PLANNER = "ReplanningAStarPlanner";

const go2Modules: ModuleDef[] = [
  { id: "GO2Connection", icons: [Camera, Radar], summary: "Camera, LiDAR and position from the Go2 over Wi-Fi.", official: true, capabilities: ["camera", "lidar"], requires: [], required: true },
  { id: "ControlGate", icons: [Gamepad2], summary: "Manual driving, with Stop and sensor checks.", official: false, capabilities: ["teleop"], requires: [], required: true },
  { id: "RelayBridgeModule", icons: [Radio], summary: "Streams camera, map and status to this app.", official: true, capabilities: [], requires: [], required: true },
  { id: "VoxelGridMapper", icons: [Box], summary: "Builds a 3D map of the space from LiDAR.", official: true, capabilities: ["mapping"], requires: ["GO2Connection"] },
  { id: "CostMapper", icons: [Map], summary: "Turns the 3D map into a 2D map of where the robot can go.", official: true, capabilities: ["mapping"], requires: ["VoxelGridMapper"] },
  { id: "ConsoleBridge", icons: [Database], summary: "Records sensor data to datasets on this device.", official: false, capabilities: ["recording"], requires: [] },
  { id: "UnitreeSkillContainer", icons: [PawPrint], summary: "Unitree actions such as stand up, sit and greet.", official: true, capabilities: [], requires: ["ControlGate"] },
  { id: PLANNER, icons: [Route], summary: "Plans routes through the map and replans around obstacles.", official: true, capabilities: ["navigation"], requires: ["CostMapper"] },
  { id: AGENT, icons: [Bot], summary: "HumanCLI: talk to the robot and let it use the skills below.", official: true, capabilities: ["humancli"], requires: [] },
  { id: "WavefrontFrontierExplorer", icons: [Compass], summary: "Autonomous exploration. Start it from HumanCLI.", official: true, capabilities: ["exploration"], requires: [PLANNER, AGENT] },
  { id: "PatrollingModule", icons: [Footprints], summary: "Patrols the mapped area. Start it from HumanCLI.", official: true, capabilities: [], requires: [PLANNER, AGENT] },
  { id: "NavigationSkillContainer", icons: [MapPin], summary: "Tag places by name and go back to them.", official: true, capabilities: [], requires: [PLANNER, AGENT] },
  { id: "PersonFollowSkillContainer", icons: [UserRound], summary: "Follow a person you describe.", official: true, capabilities: [], requires: [AGENT] },
  { id: "SpeakSkill", icons: [Volume2], summary: "Speak through the Go2 speaker.", official: true, capabilities: [], requires: [AGENT] },
  { id: "PushToTalk", icons: [Mic], summary: "Voice input to HumanCLI.", official: false, capabilities: ["voice"], requires: [AGENT] },
];

const NO_LIDAR = "No LiDAR";
const go2Only = (id: string, reason = "Go2 only") => ({
  ...go2Modules.find((m) => m.id === id)!,
  required: false,
  unavailable: reason,
});

const vectorModules: ModuleDef[] = [
  { id: "VectorConnection", icons: [Camera, Gamepad2], summary: "Camera and tread driving over Wi-Fi, with face recognition.", official: false, capabilities: ["camera", "teleop", "faces"], requires: [], required: true },
  { id: "RelayBridgeModule", icons: [Radio], summary: "Streams camera and status to this app.", official: true, capabilities: [], requires: [], required: true },
  { id: "VectorTelemetry", icons: [TriangleAlert], summary: "Cliff, fall, touch and proximity sensors, battery and temperature.", official: false, capabilities: [], requires: ["VectorConnection"] },
  { id: AGENT, icons: [Bot], summary: "HumanCLI: talk to Vector and let it use the skills below.", official: true, capabilities: ["humancli"], requires: [] },
  { id: "VectorSkills", icons: [Bot], summary: "Head, lift, speech and expressive animations.", official: false, capabilities: [], requires: [AGENT] },
  { id: "PushToTalk", icons: [Mic], summary: "Voice input to HumanCLI.", official: false, capabilities: ["voice"], requires: [AGENT] },
  go2Only("VoxelGridMapper", NO_LIDAR),
  go2Only("CostMapper", NO_LIDAR),
  go2Only(PLANNER, NO_LIDAR),
  go2Only("WavefrontFrontierExplorer", NO_LIDAR),
  go2Only("PatrollingModule", NO_LIDAR),
  go2Only("NavigationSkillContainer", NO_LIDAR),
  go2Only("ConsoleBridge", "Not on Vector yet"),
  go2Only("UnitreeSkillContainer"),
];

const required = (modules: ModuleDef[]) => modules.filter((m) => m.required).map((m) => m.id);

export const EMBODIMENTS: Record<"go2" | "vector", Embodiment> = {
  go2: {
    modules: go2Modules,
    blueprints: [
      {
        id: "teleop",
        name: "Teleop",
        summary: "Drive manually, map the space and record everything.",
        recommended: true,
        locked: true,
        modules: [...required(go2Modules), "VoxelGridMapper", "CostMapper", "ConsoleBridge", "UnitreeSkillContainer"],
      },
      { id: "custom", name: "Custom", summary: "Choose the modules for this session.", locked: false, modules: [] },
    ],
  },
  vector: {
    modules: vectorModules,
    blueprints: [
      {
        id: "teleop",
        name: "Teleop",
        summary: "Drive manually with the camera and all sensors.",
        recommended: true,
        locked: true,
        modules: [...required(vectorModules), "VectorTelemetry"],
      },
      { id: "custom", name: "Custom", summary: "Choose the modules for this session.", locked: false, modules: [] },
    ],
  },
};

export const embodiment = (kind?: string) => EMBODIMENTS[kind === "vector" ? "vector" : "go2"];

/** Selecting a module adds what it needs; removing one removes what depended on it. */
export function toggleModule(selected: string[], id: string, on: boolean, modules: ModuleDef[]) {
  const result = new Set(selected);
  const include = (key: string) => {
    if (result.has(key)) return;
    result.add(key);
    modules.find((m) => m.id === key)?.requires.forEach(include);
  };
  if (on) include(id);
  else if (!modules.find((m) => m.id === id)?.required) {
    result.delete(id);
    let changed = true;
    while (changed) {
      changed = false;
      for (const m of modules)
        if (result.has(m.id) && m.requires.some((r) => !result.has(r))) {
          result.delete(m.id);
          changed = true;
        }
    }
  }
  return modules.filter((m) => result.has(m.id) && !m.unavailable).map((m) => m.id);
}

export const capabilitiesOf = (ids: string[], modules: ModuleDef[]) => [
  ...new Set(modules.filter((m) => ids.includes(m.id)).flatMap((m) => m.capabilities)),
];

/** What the app connects with while the user picks a blueprint. */
export function baseProfile(kind?: string) {
  const { modules } = embodiment(kind);
  return { preset: "base", enabled: capabilitiesOf(required(modules), modules) };
}

export const requiredModules = (kind?: string) => required(embodiment(kind).modules);
