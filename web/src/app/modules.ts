/** Icons and selection rules for the module catalog served by /api/setup. */
import {
  AlertTriangle,
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
  UserRound,
  Volume2,
  type LucideIcon,
} from "lucide-react";
import type { ModuleDef } from "../types";

export const ICONS: Record<string, LucideIcon> = {
  agent: Bot,
  alert: AlertTriangle,
  camera: Camera,
  compass: Compass,
  database: Database,
  footprints: Footprints,
  gamepad: Gamepad2,
  lidar: Radar,
  map: Map,
  mic: Mic,
  paw: PawPrint,
  person: UserRound,
  pin: MapPin,
  relay: Radio,
  route: Route,
  speaker: Volume2,
  voxels: Box,
};

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

/** Sessions from before blueprints have no module list and allow everything they enable. */
export const hasModule = (selected: string[] | null | undefined, id: string) => !selected || selected.includes(id);
