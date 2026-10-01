/**
 * In-browser stand-in for the Python backend and the robot runtime.
 * Mock mode only: nothing here talks to a robot, DimOS Cloud or the network.
 * Timings and failure cases come from the scenario so flows can be rehearsed.
 */
import type { Grid, Item, NavigationInfo, State, Stats } from "../types";
import type { SavedRobot, SessionProfile } from "../SessionSetup";
import {
  ACCOUNT,
  CONSOLE_URL,
  GO2_CATALOG,
  STORAGE_ROOT,
  VECTOR_CATALOG,
  firstRun,
  returningUser,
  vectorReadings,
} from "./fixtures";
import { AGENT_CAPABILITIES, UNITREE_ACTIONS } from "./generated";
import * as world from "./world";

export type Scenario = {
  /** Data on the device at launch. */
  start: "returning" | "first-run";
  account: "signed-in" | "signed-out";
  /** Which saved robots answer on the network. */
  network: "go2" | "both" | "none";
  /** Seconds from Connect until the robot is online. */
  connectSeconds: number;
  /** Seconds the runtime takes to rebuild after Start session. */
  sessionSeconds: number;
  agentConfigured: boolean;
};

export const DEFAULT_SCENARIO: Scenario = {
  start: "returning",
  account: "signed-in",
  network: "go2",
  connectSeconds: 4,
  sessionSeconds: 4,
  agentConfigured: true,
};

export class MockError extends Error {
  constructor(
    message: string,
    public status = 409,
  ) {
    super(message);
  }
}

const LEGACY: SessionProfile = {
  preset: "legacy",
  enabled: GO2_CATALOG.capabilities.map((c) => c.id),
};
const PREVIEW: SessionProfile = { preset: "preview", enabled: ["camera"] };
const PRIVATE_IP =
  /^(10\.\d{1,3}|192\.168|172\.(1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}$/;
const NAV_PHASES: Record<string, [string, string]> = {
  paused: ["Navigation paused", "Choose Explore or HumanCLI to move autonomously."],
  teleop: ["Manual driving", "You are in control. Navigation is idle."],
  planning: ["Choosing a destination", "Looking for the next reachable goal."],
  route_ready: ["Following route", "Driving to the selected destination."],
  arrived: ["Arrived", "Reached the destination."],
  no_path: ["No reachable destination", "Nothing left to explore in the space seen so far."],
};
const uid = () => Math.random().toString(16).slice(2, 10);
const zeroStats = (): Stats => ({
  physical_bytes: 0,
  duration: 0,
  gb_per_min: 0,
  streams: {
    lidar: { bytes: 0, count: 0, poses: 0, gaps_over_1s: 0 },
    color_image: { bytes: 0, count: 0, poses: 0, gaps_over_1s: 0 },
    odom: { bytes: 0, count: 0, poses: 0, gaps_over_1s: 0 },
  },
});

type Route = {
  points: number[][];
  purpose: "explore" | "patrol" | "place" | "relative";
  label: string;
};
type Place = { name: string; space: string; x: number; y: number; frame: number };

export class MockBackend {
  /** Set to 0 in tests so simulated request latency resolves immediately. */
  latency = 1;
  onLeaveTeleop = () => {};
  onReset = () => {};

  robots: SavedRobot[] = [];
  spaces: Item[] = [];
  sessions: Item[] = [];
  segments: Item[] = [];
  maps: Item[] = [];
  events: State["events"] = [];

  connection = "offline";
  error: string | null = null;
  robotId: string | null = null;
  kind: "go2" | "vector" = "go2";
  ip = "";
  replay = false;
  profile: SessionProfile = LEGACY;
  mode = "idle";
  epoch = 1;

  pose: world.Pose = { ...world.START };
  velocity = { vx: 0, vy: 0, wz: 0 };
  battery = 78;
  frozen = false;
  estop = false;
  /** Movement toggle: the robot stays in place while true. */
  hold = false;
  failNextUpload = false;
  failNextMap = false;

  session: Item | null = null;
  segment: Item | null = null;
  cloud!: NonNullable<State["cloud"]>;
  agent!: State["agent"];

  private timers: { at: number; run: () => void }[] = [];
  private generation = 0;
  private last = 0;
  private recoverAt = 0;
  private frozenAt = 0;
  private lastHeartbeat = 0;
  private known = world.emptyMap();
  private grid?: Grid;
  private mappedAt = 0;
  private sensors: Record<string, { received: number; count: number }> = {};
  private sent = 0;
  private speed = 0;
  private yawRate = 0;
  private stopReason?: string;
  private route: Route | null = null;
  private planAt = 0;
  private navPhase = "planning";
  private navEvents: NavigationInfo["events"] = [];
  private patrol = false;
  private lastStats: Stats | null = null;
  private uploadProgress = 0;
  private uploadPhaseUntil = 0;
  private places: Place[] = [];
  private frame = 0;
  private agentSpace = "";
  private skill = { active: null as string | null, phase: "idle", message: "No skill running." };
  private eventId = 0;
  private loadingUntil = 0;
  private selectedModules: string[] = [];
  private agentExplore = false;

  constructor(
    public scenario: Scenario = DEFAULT_SCENARIO,
    private clock: () => number = () => Date.now() / 1000,
  ) {
    this.reset();
  }

  // ---------------------------------------------------------------- scenario

  /** Returns the device to its launch state for the chosen scenario. */
  reset() {
    const now = this.clock();
    const seed = this.scenario.start === "first-run" ? firstRun() : returningUser(now);
    Object.assign(this, structuredClone(seed));
    this.events = [];
    this.timers = [];
    this.generation++;
    this.connection = "offline";
    this.error = null;
    this.robotId = null;
    this.replay = false;
    this.profile = LEGACY;
    this.mode = "idle";
    this.epoch = 1;
    this.session = this.segment = null;
    this.lastStats = null;
    this.places = [];
    this.battery = 78;
    this.frozen = this.estop = this.failNextUpload = this.failNextMap = false;
    this.last = now;
    this.cloud = {
      configured: false,
      account: null,
      login: null,
      error: null,
      active_segment: null,
      console_url: CONSOLE_URL,
      quota: null,
    };
    if (this.scenario.account === "signed-in") this.approveLogin();
    this.agent = {
      busy: false,
      messages: [],
      conversation_id: uid(),
      engine: "dimos-mcp",
      model: {
        provider: "openai",
        model: "gpt-4.1-mini",
        base_url: "",
        configured: this.scenario.agentConfigured,
        vision: true,
        error: null,
      },
    };
    this.resetRuntime();
    this.onReset();
  }

  setScenario(patch: Partial<Scenario>) {
    this.scenario = { ...this.scenario, ...patch };
    if (patch.account === "signed-in") this.approveLogin();
    if (patch.account === "signed-out") this.signOut();
    if (patch.agentConfigured !== undefined && this.agent.model)
      this.agent.model.configured = patch.agentConfigured;
    if (patch.start) this.reset();
  }

  approveLogin() {
    this.cloud.configured = true;
    this.cloud.account = { ...ACCOUNT };
    this.cloud.login = null;
    this.cloud.error = null;
    this.cloud.quota ??= { used_total: 3.1e9, pct: 6, state: "ok" };
  }

  expireLogin() {
    if (this.cloud.login) this.cloud.login.expires_at = this.clock() - 1;
  }

  signOut() {
    this.cloud.configured = false;
    this.cloud.account = this.cloud.login = this.cloud.quota = null;
  }

  /** Wi-Fi loss while connected. The runtime restarts when the robot returns. */
  dropConnection(seconds = 8) {
    if (this.connection !== "online") return;
    this.leaveControl();
    this.closeSegment("interrupted");
    this.connection = "reconnecting";
    this.error = this.notResponding();
    this.recoverAt = this.clock() + seconds;
    this.event("Connection lost. Retrying.");
  }

  freezeSensors(on: boolean) {
    this.frozen = on;
    this.frozenAt = this.clock();
  }

  // ------------------------------------------------------------------- clock

  private after(seconds: number, run: () => void) {
    this.timers.push({ at: this.clock() + seconds, run });
  }

  private wait(seconds: number) {
    return this.latency
      ? new Promise<void>((done) => setTimeout(done, seconds * 1000 * this.latency))
      : Promise.resolve();
  }

  private event(message: string) {
    this.events.unshift({ id: ++this.eventId, ts: this.clock(), message });
    this.events.length = Math.min(this.events.length, 50);
  }

  private enabled(capability: string) {
    return this.profile.enabled.includes(capability);
  }

  private get robotName() {
    return this.kind === "vector" ? "Vector" : "Go2";
  }

  private reachable() {
    const network = this.scenario.network;
    return network === "both" || (network === "go2" && this.kind === "go2");
  }

  private notResponding() {
    return `${this.robotName} is not responding at ${this.ip}. Retrying; check whether DHCP changed its IP address.`;
  }

  /** Advances the simulation. Called on an interval by the page, or directly by tests. */
  tick() {
    const now = this.clock();
    const dt = Math.max(0, Math.min(0.25, now - this.last));
    this.last = now;
    const due = this.timers.filter((t) => t.at <= now);
    this.timers = this.timers.filter((t) => t.at > now);
    due.forEach((t) => t.run());
    this.tickUpload(now, dt);
    if (this.connection === "reconnecting" && (this.replay || this.reachable()) && now >= this.recoverAt)
      this.goOnline();
    if (this.connection !== "online") return;
    if (this.frozen) {
      if (now - this.frozenAt > 10 && this.mode !== "idle")
        this.leaveControl(
          "Control stopped because position, LiDAR, or map data is missing or over 10 seconds old",
        );
    } else {
      for (const [key, on] of [
        ["odom", true],
        ["lidar", this.kind === "go2" && this.enabled("lidar")],
        ["color_image", this.enabled("camera")],
      ] as const)
        if (on) this.sensors[key] = { received: now, count: (this.sensors[key]?.count || 0) + 1 };
    }
    if (this.mode !== "idle" && now - this.lastHeartbeat > 3)
      this.leaveControl("Control lease expired. Take control again to continue.");
    this.battery = Math.max(1, this.battery - dt * 0.01);
    this.move(now, dt);
    if (this.kind === "go2" && this.enabled("mapping") && !this.frozen && now - this.mappedAt > 0.5) {
      this.mappedAt = now;
      if (world.reveal(this.known, this.pose) || !this.grid)
        this.grid = {
          width: world.WIDTH,
          height: world.HEIGHT,
          resolution: world.RES,
          origin: world.ORIGIN,
          cells: Array.from(this.known),
          known_m2: world.knownArea(this.known),
          received: now,
        };
    }
    if (this.segment?.stats) this.grow(this.segment.stats, dt);
  }

  private grow(stats: Stats, dt: number) {
    const add = (key: string, bytes: number, hz: number) => {
      const s = stats.streams[key];
      s.bytes += bytes * dt;
      s.count += hz * dt;
      s.poses = s.count;
    };
    if (this.enabled("lidar")) add("lidar", 2.4e6, 10);
    if (this.enabled("camera")) add("color_image", 1.4e6, 15);
    add("odom", 4e4, 20);
    stats.duration += dt;
    stats.physical_bytes = Object.values(stats.streams).reduce((n, s) => n + s.bytes, 0);
    stats.gb_per_min = stats.physical_bytes / 1e9 / Math.max(stats.duration / 60, 1 / 60);
  }

  // ------------------------------------------------------------------ motion

  setVelocity(vx: number, vy: number, wz: number) {
    this.velocity = { vx, vy, wz };
  }

  private move(now: number, dt: number) {
    const before = this.pose;
    let { x, y, yaw } = before;
    const halted = this.estop || this.frozen || this.hold;
    const autonomous =
      !halted && (this.mode === "explore" || this.mode === "agent" || this.replay);
    if (this.mode === "teleop" && !halted) {
      const { vx, vy, wz } = this.velocity;
      const nx = x + (vx * Math.cos(yaw) - vy * Math.sin(yaw)) * dt;
      const ny = y + (vx * Math.sin(yaw) + vy * Math.cos(yaw)) * dt;
      // Slide along walls instead of stopping dead.
      if (!world.isBlocked(nx, y)) x = nx;
      if (!world.isBlocked(x, ny)) y = ny;
      yaw += wz * dt;
      if (vx || vy || wz) this.sent++;
    } else if (autonomous) {
      if (!this.route && now >= this.planAt) this.plan();
      const target = this.route?.points[0];
      if (target) {
        const dx = target[0] - x,
          dy = target[1] - y;
        const distance = Math.hypot(dx, dy);
        let turn = Math.atan2(dy, dx) - yaw;
        turn = Math.atan2(Math.sin(turn), Math.cos(turn));
        yaw += Math.sign(turn) * Math.min(Math.abs(turn), 1.4 * dt);
        if (Math.abs(turn) < 0.6) {
          const stride = Math.min(distance, 0.45 * dt);
          x += Math.cos(yaw) * stride;
          y += Math.sin(yaw) * stride;
        }
        this.sent++;
        if (distance < 0.12) {
          this.route!.points.shift();
          if (!this.route!.points.length) this.arrive();
        }
      }
    }
    this.speed = dt ? Math.hypot(x - before.x, y - before.y) / dt : 0;
    this.yawRate = dt ? (yaw - before.yaw) / dt : 0;
    if (x !== before.x || y !== before.y || yaw !== before.yaw) this.pose = { x, y, yaw };
  }

  private navEvent(code: string, text: string) {
    const last = this.navEvents[0];
    if (last?.code === code) last.count++;
    else this.navEvents.unshift({ code, text, ts: this.clock(), count: 1, source: "planner" });
    this.navEvents.length = Math.min(this.navEvents.length, 8);
  }

  private plan() {
    const exploring = this.mode === "explore" || this.replay || this.agentExplore;
    if (!exploring && !this.patrol) return;
    const points = exploring
      ? world.routeToUnknown(this.pose, this.known)
      : world.routeToPatrol(this.pose, this.known, this.sent) ||
        world.routeToPatrol(this.pose, this.known, -1);
    if (!points) {
      this.navPhase = "no_path";
      this.planAt = this.clock() + 5;
      this.navEvent("no_path", NAV_PHASES.no_path[1]);
      return;
    }
    this.route = { points, purpose: exploring ? "explore" : "patrol", label: "" };
    this.navPhase = "route_ready";
    this.navEvent("planning", exploring ? "Exploration selected a new goal." : "Patrol selected a new goal.");
  }

  private arrive() {
    const route = this.route!;
    this.route = null;
    this.navPhase = "arrived";
    this.navEvent("arrived", "Arrived at goal.");
    this.planAt = this.clock() + 1;
    if (route.purpose === "place" || route.purpose === "relative") {
      const text = route.purpose === "place" ? `Arrived at ${route.label}.` : "Move complete.";
      this.skill = { active: null, phase: "done", message: text };
      this.say("assistant", text);
    }
  }

  /** Ends any control mode without latching Emergency stop. */
  private leaveControl(reason?: string) {
    const wasTeleop = this.mode === "teleop";
    if (this.mode !== "idle") {
      this.mode = "idle";
      this.epoch++;
    }
    this.stopReason = reason;
    this.velocity = { vx: 0, vy: 0, wz: 0 };
    this.cancelSkills(reason ? "Cancelled: control stopped." : "");
    if (wasTeleop) this.onLeaveTeleop();
  }

  private cancelSkills(message: string) {
    const running = !!this.route || this.patrol || this.agentExplore || this.skill.phase === "running";
    this.route = null;
    this.patrol = false;
    this.agentExplore = false;
    this.agent.busy = false;
    if (running && message) this.skill = { active: null, phase: "idle", message };
  }

  // -------------------------------------------------------------- connection

  private resetRuntime() {
    this.pose = { ...world.START };
    this.known = world.emptyMap();
    this.grid = undefined;
    this.sensors = {};
    this.route = null;
    this.patrol = false;
    this.navEvents = [];
    this.navPhase = "planning";
    this.velocity = { vx: 0, vy: 0, wz: 0 };
    this.stopReason = undefined;
    this.skill = { active: null, phase: "idle", message: "No skill running." };
    this.frame++;
    this.sent = 0;
  }

  private startRuntime(seconds: number) {
    const generation = ++this.generation;
    this.connection = "connecting";
    this.error = null;
    this.resetRuntime();
    this.after(seconds, () => {
      if (generation !== this.generation) return;
      if (this.replay || this.reachable()) return this.goOnline();
      this.connection = "reconnecting";
      this.error = this.notResponding();
      this.recoverAt = 0;
    });
  }

  private goOnline() {
    if (this.connection === "reconnecting") this.resetRuntime();
    this.connection = "online";
    this.error = null;
    this.lastHeartbeat = this.clock();
    this.event(this.replay ? "Replay started" : `${this.robotName} connected`);
    if (this.session && !this.segment) this.newSegment();
  }

  private connect(body: { ip?: string; robot_id?: string; segment_id?: string; profile?: SessionProfile }) {
    if (this.connection !== "offline") throw new MockError("Disconnect the current session first");
    if (body.segment_id) {
      const segment = this.find(this.segments, body.segment_id, "Recording");
      if (["recording", "importing"].includes(segment.status))
        throw new MockError("Save the recording before replaying it");
      this.replay = true;
      this.kind = "go2";
      this.robotId = null;
      this.profile = LEGACY;
      this.startRuntime(2);
      return { ok: true };
    }
    const saved = body.robot_id ? this.robots.find((r) => r.id === body.robot_id) : null;
    if (body.robot_id && !saved) throw new MockError("Saved robot not found");
    const ip = saved?.ip || body.ip || "";
    if (!PRIVATE_IP.test(ip)) throw new MockError("Enter Go2's private IP address on your Wi-Fi");
    this.replay = false;
    this.ip = ip;
    this.kind = (saved?.kind as "go2" | "vector") || "go2";
    this.robotId = saved?.id || null;
    this.profile = body.profile
      ? { preset: body.profile.preset, enabled: [...body.profile.enabled] }
      : this.kind === "vector"
        ? { ...saved!.profile }
        : saved
          ? PREVIEW
          : LEGACY;
    this.selectedModules = [];
    this.hold = false;
    if (!this.spaces.length) this.createSpace("Starting space");
    this.mode = "idle";
    this.estop = false;
    this.event(`Connecting to ${saved?.name || ip}`);
    this.startRuntime(this.scenario.connectSeconds);
    return { ok: true };
  }

  private disconnect() {
    if (!this.replay && this.connection === "online" && this.mode !== "idle")
      throw new MockError("Stop movement before disconnecting");
    if (this.session) this.stopRecording();
    this.leaveControl();
    this.generation++;
    this.connection = "offline";
    this.error = null;
    this.replay = false;
    this.profile = LEGACY;
    this.selectedModules = [];
    this.hold = false;
    this.event("Disconnected");
    return { ok: true };
  }

  private applyProfile(body: { robot_id: string | null; preset: string; enabled: string[] }) {
    if ((body.robot_id ?? null) !== this.robotId)
      throw new MockError("The selected robot changed. Reopen Session setup.");
    const catalog = this.kind === "vector" ? VECTOR_CATALOG : GO2_CATALOG;
    if (!catalog.presets.some((p) => p.id === body.preset)) throw new MockError("Unknown session preset");
    for (const id of body.enabled) {
      const capability = catalog.capabilities.find((c) => c.id === id);
      if (!capability) throw new MockError("Unknown capability");
      const missing = capability.requires.filter((r) => !body.enabled.includes(r));
      if (missing.length) throw new MockError(`${capability.name} requires ${missing.join(", ")}`);
    }
    if (this.connection !== "online") throw new MockError("Wait for the connection before starting a session");
    if (this.mode !== "idle" || this.session)
      throw new MockError("Pause movement and save the recording before changing the session");
    this.profile = { preset: body.preset, enabled: [...body.enabled] };
    const saved = this.robots.find((r) => r.id === this.robotId);
    if (saved) saved.profile = { ...this.profile };
    this.agent.messages = [];
    this.event(`Session started: ${catalog.presets.find((p) => p.id === body.preset)!.name}`);
    this.startRuntime(this.scenario.sessionSeconds);
    return { ok: true, profile: this.profile };
  }

  /**
   * Adds modules to the running session without reconnecting the robot.
   * Proposed API for the new flow; the Python backend does not have it yet.
   */
  private addModules(body: { robot_id: string | null; preset: string; enabled: string[]; modules: string[] }) {
    if ((body.robot_id ?? null) !== this.robotId) throw new MockError("The selected robot changed. Go back and choose it again.");
    this.requireOnline();
    const catalog = this.kind === "vector" ? VECTOR_CATALOG : GO2_CATALOG;
    for (const id of body.enabled) {
      const capability = catalog.capabilities.find((c) => c.id === id);
      if (!capability) throw new MockError(`${id} is not available on ${this.robotName}`);
      const missing = capability.requires.filter((r) => !body.enabled.includes(r));
      if (missing.length) throw new MockError(`${capability.name} requires ${missing.join(", ")}`);
    }
    this.profile = { preset: body.preset, enabled: [...body.enabled] };
    this.selectedModules = [...body.modules];
    this.loadingUntil = this.clock() + 2.5;
    this.event(`Session started with ${body.modules.length} modules`);
    return { ok: true, profile: this.profile };
  }

  createSpace(name: string) {
    const space: Item = {
      id: uid(),
      name,
      created: this.clock(),
      status: "ready",
      folder: `${STORAGE_ROOT}/${name.toLowerCase().replace(/\W+/g, "-")}`,
    };
    this.spaces.unshift(space);
    return space;
  }

  private saveRobot(body: Partial<SavedRobot>, id?: string) {
    const name = (body.name || "").trim(),
      serial = (body.serial || "").trim(),
      kind = body.kind || "go2";
    if (!name || name.length > 80) throw new MockError("Enter a robot name (up to 80 characters)");
    if (!PRIVATE_IP.test(body.ip || "")) throw new MockError("Enter the robot's private IPv4 address");
    if (kind === "vector" && !serial) throw new MockError("Enter the Vector serial number");
    if (this.robots.some((r) => r.id !== id && (r.ip === body.ip || (serial && r.serial === serial))))
      throw new MockError("This robot is already saved");
    if (id && this.connection !== "offline" && this.robotId === id)
      throw new MockError("Disconnect this robot before editing its connection");
    const catalog = kind === "vector" ? VECTOR_CATALOG : GO2_CATALOG;
    const preset = catalog.presets[kind === "vector" ? 1 : 0];
    const robot: SavedRobot = {
      ...(id ? this.find(this.robots, id, "Saved robot") : { id: uid(), profile: { preset: preset.id, enabled: [...preset.enabled] } }),
      name,
      ip: body.ip!,
      serial,
      kind,
      ...(kind === "vector" ? { sdk_config: body.sdk_config || "" } : {}),
    } as SavedRobot;
    this.robots = [...this.robots.filter((r) => r.id !== robot.id), robot];
    return robot;
  }

  // ----------------------------------------------------------------- control

  private requireOnline() {
    if (this.connection !== "online") throw new MockError(`${this.robotName} disconnected`);
  }

  private changeMode(mode: string) {
    this.requireOnline();
    const capability = { teleop: "teleop", explore: "exploration", agent: "humancli" }[mode];
    if (mode !== "idle" && !capability) throw new MockError("Unknown control mode");
    if (capability && !this.enabled(capability))
      throw new MockError(
        `${GO2_CATALOG.capabilities.find((c) => c.id === capability)?.name} is disabled in this session`,
      );
    if (mode !== "idle" && this.estop) throw new MockError("Release Emergency stop before selecting a mode");
    const wasTeleop = this.mode === "teleop";
    this.cancelSkills("Cancelled: control mode changed.");
    this.mode = mode;
    this.epoch++;
    this.velocity = { vx: 0, vy: 0, wz: 0 };
    this.stopReason = undefined;
    this.lastHeartbeat = this.clock();
    this.planAt = 0;
    this.navPhase = "planning";
    if (wasTeleop && mode !== "teleop") this.onLeaveTeleop();
    return { ok: true, epoch: this.epoch, mode };
  }

  private stop() {
    const moving = this.mode !== "idle";
    this.leaveControl();
    if (!moving) this.epoch++;
    if (this.connection === "online") this.estop = true;
    this.event("Stop requested");
    return { ok: true };
  }

  // --------------------------------------------------------------- recording

  private find<T extends { id: string }>(items: T[], id: string, what: string) {
    const item = items.find((x) => x.id === id);
    if (!item) throw new MockError(`${what} not found`, 404);
    return item;
  }

  private newSegment() {
    const session = this.session!;
    const n = this.segments.filter((s) => s.parent === session.id).length + 1;
    this.segment = {
      id: uid(),
      parent: session.id,
      created: this.clock(),
      status: "recording",
      folder: session.folder,
      path: `${session.folder}/segment-${String(n).padStart(3, "0")}.db`,
      stats: zeroStats(),
    };
    this.segments.unshift(this.segment);
  }

  private closeSegment(status: string) {
    if (!this.segment) return;
    this.segment.status = status;
    this.lastStats = this.segment.stats || null;
    this.segment = null;
  }

  private startRecording(spaceId: string) {
    this.requireOnline();
    if (!this.enabled("recording")) throw new MockError("Recording is disabled in this session");
    if (this.session) throw new MockError("A recording is already in progress");
    const space = this.find(this.spaces, spaceId, "Space");
    this.session = {
      id: uid(),
      parent: space.id,
      created: this.clock(),
      status: "recording",
      folder: `${space.folder}/session-${this.sessions.filter((s) => s.parent === space.id).length + 1}`,
      source: this.replay ? "replay" : "robot",
    };
    this.sessions.unshift(this.session);
    this.newSegment();
    this.event(`Recording started in ${space.name}`);
    return { ok: true };
  }

  private stopRecording() {
    if (!this.session) throw new MockError("No recording in progress");
    this.closeSegment("closed");
    this.session.status = "closed";
    this.session = null;
    this.event("Recording saved");
    return { ok: true };
  }

  private generateMap(body: { segment_id: string; voxel?: number }) {
    const segment = this.find(this.segments, body.segment_id, "Recording");
    if (segment.status === "recording") throw new MockError("Save the recording before generating its map");
    const folder = `${segment.folder}/maps/${this.maps.filter((m) => m.parent === segment.id).length + 1}`;
    const map: Item = { id: uid(), parent: segment.id, created: this.clock(), status: "queued", voxel: body.voxel || 0.1, folder };
    this.maps.unshift(map);
    const fail = this.failNextMap;
    this.failNextMap = false;
    this.after(1, () => {
      if (map.status === "queued") map.status = "running";
    });
    this.after(9, () => {
      if (map.status !== "running") return;
      if (fail) {
        map.status = "failed";
        map.error = "Map generation failed: too few LiDAR frames have a matching pose.";
        map.log = "map.log";
        return;
      }
      Object.assign(map, {
        status: "ready",
        map_path: `${folder}/map.pc2.lcm`,
        rerun_path: `${folder}/map.rrd`,
        log: "map.log",
        quality: {
          lidar_frames: Math.round(segment.stats?.streams.lidar?.count || 0),
          lidar_pose_fraction: 1,
          lidar_gaps_over_1s: 0,
        },
      });
      this.event("Map ready");
    });
    return { ok: true, id: map.id };
  }

  // ------------------------------------------------------------------- cloud

  private upload(id: string, body: { name?: string }) {
    if (!this.cloud.configured || this.cloud.login) throw new MockError("Connect DimOS Cloud before uploading");
    if (this.cloud.active_segment) throw new MockError("Another upload is in progress");
    const segment = this.find(this.segments, id, "Recording");
    if (!["closed", "interrupted"].includes(segment.status)) throw new MockError("Save the recording first");
    const previous = segment.backup;
    const size = segment.stats?.physical_bytes || 0;
    this.uploadProgress = previous?.percent || 0;
    segment.backup = {
      name: body.name || previous?.name,
      status: "preparing",
      percent: Math.floor(this.uploadProgress),
      size,
      uploaded_bytes: (size * this.uploadProgress) / 100,
      upload_id: previous?.upload_id || `upl_${uid()}`,
      owner_id: this.cloud.account?.id,
      error: null,
    };
    this.cloud.active_segment = id;
    this.uploadPhaseUntil = this.clock() + 1.5;
    return { ok: true };
  }

  private tickUpload(now: number, dt: number) {
    const segment = this.segments.find((s) => s.id === this.cloud.active_segment);
    const backup = segment?.backup;
    if (!backup) return;
    if (backup.status === "preparing" && now >= this.uploadPhaseUntil) backup.status = "uploading";
    else if (backup.status === "uploading") {
      this.uploadProgress = Math.min(100, this.uploadProgress + (dt * 100) / 12);
      backup.percent = Math.floor(this.uploadProgress);
      backup.uploaded_bytes = ((backup.size || 0) * this.uploadProgress) / 100;
      if (this.failNextUpload && this.uploadProgress >= 60) {
        this.failNextUpload = false;
        backup.status = "failed";
        backup.error = "Upload interrupted. Check the connection and resume.";
        this.cloud.active_segment = null;
      } else if (this.uploadProgress >= 100) {
        backup.status = "verifying";
        this.uploadPhaseUntil = now + 1.5;
      }
    } else if (backup.status === "verifying" && now >= this.uploadPhaseUntil) {
      backup.status = "complete";
      backup.verified_at = now;
      this.cloud.active_segment = null;
      if (this.cloud.quota) this.cloud.quota.used_total += backup.size || 0;
      this.event(`Backed up: ${backup.name || segment!.id}`);
    }
  }

  // ------------------------------------------------------------------- agent

  private say(role: string, text: string) {
    this.agent.messages.push({ role, text, ts: this.clock() });
  }

  private instruct(body: { text: string; epoch: number; space_id?: string | null }) {
    this.requireOnline();
    if (this.mode !== "agent" || body.epoch !== this.epoch)
      throw new MockError("Enable HumanCLI before sending an instruction.");
    if (!this.agent.model?.configured) throw new MockError("Configure a model in HumanCLI settings first.");
    if (this.agent.busy) throw new MockError("Wait for HumanCLI to finish.");
    this.agentSpace = body.space_id || "";
    this.say("user", body.text);
    this.agent.busy = true;
    const epoch = this.epoch;
    this.after(1.2, () => {
      if (!this.agent.busy || this.epoch !== epoch) return;
      this.agent.busy = false;
      this.say("assistant", this.respond(body.text.trim()));
    });
    return { ok: true };
  }

  /** Scripted answers. Keywords stand in for the real model and DimOS tools. */
  private respond(text: string) {
    const lower = text.toLowerCase();
    const tool = (name: string, detail: string) => this.say("tool", `${name}(${detail})`);
    if (this.kind === "vector") return "Scripted reply in mock mode. Vector skills are not simulated.";
    const missing = (module: string) =>
      this.selectedModules.length && !this.selectedModules.includes(module)
        ? `${module} is not part of this session's blueprint.`
        : "";
    let match = text.match(/(?:remember|tag|save) this (?:as|place as) (.+?)[.!]?$/i);
    if (match && missing("NavigationSkillContainer")) return missing("NavigationSkillContainer");
    if (match) {
      if (!this.agentSpace) return "Select a space before tagging a location.";
      const name = match[1].trim();
      tool("tag_location", `name="${name}"`);
      this.places = this.places.filter((p) => p.name.toLowerCase() !== name.toLowerCase() || p.space !== this.agentSpace);
      this.places.push({ name, space: this.agentSpace, x: this.pose.x, y: this.pose.y, frame: this.frame });
      this.skill = { active: null, phase: "done", message: `Saved "${name}".` };
      return `Saved "${name}" at the current position.`;
    }
    if (/which places|list (the )?(places|locations)|what places/.test(lower)) {
      tool("list_locations", "");
      const places = this.places.filter((p) => p.space === this.agentSpace);
      return places.length
        ? "Tagged places: " + places.map((p) => `${p.name}${p.frame === this.frame ? "" : " (tag again)"}`).join(", ") + "."
        : "No places are tagged in this space yet.";
    }
    if (/\bstop\b/.test(lower)) {
      tool(this.patrol ? "stop_patrol" : "stop_navigation", "");
      this.cancelSkills("");
      this.skill = { active: null, phase: "idle", message: "Stopped." };
      return "Stopped. Go2 is holding position.";
    }
    if (/explor/.test(lower)) {
      if (!this.enabled("exploration")) return "WavefrontFrontierExplorer is not part of this session's blueprint.";
      tool("begin_exploration", "");
      this.patrol = false;
      this.agentExplore = true;
      this.route = null;
      this.planAt = 0;
      this.skill = { active: "begin_exploration", phase: "running", message: "Exploring unmapped areas." };
      return "Exploring. I will keep driving to unmapped areas until you say stop.";
    }
    if (/patrol/.test(lower)) {
      if (!this.enabled("navigation")) return "Navigation is disabled in this session.";
      if (missing("PatrollingModule")) return missing("PatrollingModule");
      tool("start_patrol", "");
      this.patrol = true;
      this.route = null;
      this.planAt = 0;
      this.skill = { active: "start_patrol", phase: "running", message: "Patrolling the mapped area." };
      return "Patrol started. I will keep choosing goals in the mapped area until you say stop.";
    }
    match = text.match(/^(?:go|navigate|walk|take me) to (?:the )?(.+?)[.!]?$/i);
    if (match) {
      if (missing("NavigationSkillContainer")) return missing("NavigationSkillContainer");
      const name = match[1].trim();
      const place = this.places.find((p) => p.space === this.agentSpace && p.name.toLowerCase() === name.toLowerCase());
      tool("navigate_with_text", `query="${name}"`);
      if (!place) return `I have no place called "${name}". Tag it first with "Remember this as ${name}".`;
      if (place.frame !== this.frame)
        return "This place belongs to an earlier connection. Tag it again in this session before navigating.";
      const points = world.routeTo(this.pose, place.x, place.y);
      if (!points) return `Already at ${place.name}.`;
      this.patrol = false;
      this.route = { points, purpose: "place", label: place.name };
      this.navPhase = "route_ready";
      this.skill = { active: "navigate_with_text", phase: "running", message: `Navigating to ${place.name}.` };
      return `Heading to ${place.name}.`;
    }
    match = lower.match(/(\d+(?:\.\d+)?)\s*(?:m\b|meter|metre)/);
    if (match && /(walk|move|go|back|forward)/.test(lower)) {
      const meters = Math.min(3, Number(match[1])) * (/back/.test(lower) ? -1 : 1);
      tool("move_relative", `forward=${meters}`);
      let reach = 0;
      for (let d = 0.1; d <= Math.abs(meters); d += 0.1) {
        const s = Math.sign(meters) * d;
        if (world.isBlocked(this.pose.x + Math.cos(this.pose.yaw) * s, this.pose.y + Math.sin(this.pose.yaw) * s)) break;
        reach = s;
      }
      if (!reach) return "The way is blocked. I did not move.";
      this.patrol = false;
      this.route = {
        points: [[this.pose.x + Math.cos(this.pose.yaw) * reach, this.pose.y + Math.sin(this.pose.yaw) * reach]],
        purpose: "relative",
        label: "",
      };
      this.navPhase = "route_ready";
      return `Moving ${Math.abs(reach).toFixed(1)} m ${reach < 0 ? "backward" : "forward"}.`;
    }
    if (/follow/.test(lower) && missing("PersonFollowSkillContainer")) return missing("PersonFollowSkillContainer");
    if (/follow/.test(lower)) {
      tool("follow_person", `query="${text}"`);
      this.skill = { active: "follow_person", phase: "error", message: "No person matching the description is in view." };
      return "I could not find that person in the camera view. (Person following is not simulated.)";
    }
    match = text.match(/^say:?\s+(.+)$/i);
    if (match && missing("SpeakSkill")) return missing("SpeakSkill");
    if (match) {
      tool("speak", `text="${match[1]}"`);
      this.skill = { active: "speak", phase: "done", message: "Audio upload acknowledged by Go2." };
      return `Sent "${match[1]}" to the Go2 speaker.`;
    }
    if (/what (do|can) you see|describe/.test(lower)) {
      if (!this.enabled("camera")) return "The camera is disabled in this session.";
      tool("camera_view", "");
      return "I see an indoor room with a wall ahead and open floor to the left. (Scripted answer in mock mode.)";
    }
    return 'Scripted reply in mock mode. Try "Remember this as reception", "Go to reception", "Start patrolling this area", "Walk 1 meter forward", "Say: hello" or "Stop".';
  }

  // ---------------------------------------------------------------- snapshot

  private modules() {
    if (this.kind === "vector")
      return [...VECTOR_CATALOG.required_modules, ...(this.enabled("humancli") ? ["VectorSkills"] : [])];
    return [
      ...GO2_CATALOG.required_modules,
      ...["mapping", "navigation", "exploration"].flatMap((id) =>
        this.enabled(id) ? GO2_CATALOG.capabilities.find((c) => c.id === id)!.modules : [],
      ),
    ];
  }

  private navigation(now: number): NavigationInfo {
    const active =
      this.mode === "explore" || (this.mode === "agent" && (!!this.route || this.patrol || this.agentExplore));
    const phase = active ? this.navPhase : this.mode === "teleop" ? "teleop" : "paused";
    const [title, detail] = NAV_PHASES[phase];
    return {
      phase,
      title,
      detail,
      warnings: this.frozen
        ? [{ code: "stale", text: "Sensor data is stale. Movement is on hold.", ts: now, source: "control" }]
        : [],
      events: this.navEvents,
    };
  }

  private telemetry(): State["telemetry"] {
    const now = this.clock();
    const go2 = this.kind === "go2";
    return {
      sensors: this.sensors,
      battery: go2 ? { percent: Math.round(this.battery), received: this.frozen ? this.frozenAt : now } : undefined,
      vector: go2 ? undefined : (vectorReadings(now) as State["telemetry"]["vector"]),
      map: go2 && this.enabled("mapping") ? this.grid : undefined,
      pose: go2 ? this.pose : undefined,
      path: this.route ? [[this.pose.x, this.pose.y], ...this.route.points] : undefined,
      navigation: go2 && this.enabled("navigation") ? this.navigation(now) : undefined,
      recording: { dropped: 0, errors: 0 },
      control: {
        estop: this.estop,
        stop_reason: this.stopReason,
        ownership: go2 ? undefined : this.estop ? "stopped" : this.mode === "idle" ? "native" : "app",
        nav_received: this.sent,
        nav_forwarded: this.sent,
      },
      motion: { sent: this.sent, observed_speed: this.speed, observed_yaw_rate: this.yawRate },
      skills:
        go2 && this.enabled("humancli")
          ? {
              ...this.skill,
              places: this.places
                .filter((p) => p.space === this.agentSpace)
                .map((p) => ({ name: p.name, usable: p.frame === this.frame })),
            }
          : null,
    };
  }

  private tools() {
    const needs: Record<string, string> = {
      tag_location: "NavigationSkillContainer",
      list_locations: "NavigationSkillContainer",
      navigate_with_text: "NavigationSkillContainer",
      start_patrol: "PatrollingModule",
      stop_patrol: "PatrollingModule",
      follow_person: "PersonFollowSkillContainer",
      stop_following: "PersonFollowSkillContainer",
      speak: "SpeakSkill",
      start_exploration: "WavefrontFrontierExplorer",
      start_recording: "ConsoleBridge",
      save_recording: "ConsoleBridge",
    };
    const chosen = this.selectedModules;
    return AGENT_CAPABILITIES.filter((t) => !chosen.length || !needs[t.name] || chosen.includes(needs[t.name]));
  }

  /** The /api/state payload. */
  snapshot(): State {
    const online = this.connection === "online";
    return {
      robot_id: this.robotId,
      robot_kind: this.kind,
      profile: this.profile,
      modules: this.modules(),
      connection: this.connection,
      error: this.error,
      ip: this.ip,
      replay: this.replay,
      mode: this.mode,
      epoch: this.epoch,
      disk_free: 214e9,
      storage_root: STORAGE_ROOT,
      dimos_sha: "c1c3cdc9d2ee54ca72259465688395699d7d99a2",
      session: this.session,
      segment: this.segment,
      stats: this.segment?.stats || this.lastStats,
      spaces: this.spaces,
      sessions: this.sessions,
      segments: this.segments,
      maps: this.maps,
      events: this.events,
      cloud: this.cloud,
      telemetry: online ? this.telemetry() : {},
      loading_modules: this.clock() < this.loadingUntil,
      selected_modules: this.selectedModules,
      hold: this.hold,
      agent: {
        ...this.agent,
        capabilities: this.kind === "go2" && this.enabled("humancli") ? this.tools() : [],
        vision: {
          configured: !!this.agent.model?.configured,
          enabled: !!this.agent.model?.vision,
          model: this.agent.model?.model || "",
        },
      },
      vector_services:
        this.kind === "vector" && this.connection !== "offline"
          ? { state: "running", message: "Local wire-pod services are running (simulated).", voice_ready: true }
          : undefined,
    };
  }

  /** What the DimOS SDK session would deliver. Null until the robot is online. */
  live(): State | null {
    return this.connection === "online" ? this.snapshot() : null;
  }

  // ------------------------------------------------------------------ routes

  /** HTTP-shaped entry point used by the fetch override. */
  async http(method: string, path: string, body: unknown) {
    try {
      return { status: 200, json: await this.handle(method, path, (body || {}) as any) };
    } catch (error) {
      if (error instanceof MockError) return { status: error.status, json: { detail: error.message } };
      throw error;
    }
  }

  /** SDK-shaped entry point: commands reject with the backend's message. */
  command(path: string, body: unknown) {
    return this.handle("POST", path, (body || {}) as any);
  }

  private async handle(method: string, path: string, body: any): Promise<unknown> {
    let m: RegExpMatchArray | null;
    switch (path) {
      case "/state":
        return this.snapshot();
      case "/setup":
        return {
          ...GO2_CATALOG,
          robots: this.robots,
          supported_robots: ["go2", "vector"],
          embodiments: { go2: GO2_CATALOG, vector: VECTOR_CATALOG },
        };
      case "/robots/availability": {
        await this.wait(0.9);
        const network = this.scenario.network;
        return Object.fromEntries(
          this.robots.map((r) => [
            r.id,
            network === "both" || (network === "go2" && r.kind === "go2") ? "reachable" : "unreachable",
          ]),
        );
      }
      case "/robots":
        return this.saveRobot(body);
      case "/unitree/actions":
        return { source: "DimOS UnitreeSkillContainer", actions: UNITREE_ACTIONS };
      case "/connect":
        return this.connect(body);
      case "/session/modules":
        return this.addModules(body);
      case "/hold":
        this.requireOnline();
        this.hold = !!body.on;
        if (this.hold) this.leaveControl();
        return { ok: true, hold: this.hold };
      case "/cloud/signout":
        this.signOut();
        return { ok: true };
      case "/disconnect":
        return this.disconnect();
      case "/session/profile":
        return this.applyProfile(body);
      case "/mode":
        return this.changeMode(body.mode);
      case "/heartbeat": {
        const ok = this.connection === "online" && this.mode !== "idle" && body.epoch === this.epoch;
        if (ok) this.lastHeartbeat = this.clock();
        return { ok };
      }
      case "/release":
        if (this.connection !== "online") return { ok: false };
        if (body.epoch === this.epoch) this.leaveControl();
        return { ok: true };
      case "/stop":
        return this.stop();
      case "/clear":
        this.requireOnline();
        this.estop = false;
        return { ok: true };
      case "/posture/stand":
      case "/posture/lie":
        this.requireOnline();
        await this.wait(1.5);
        this.event(path.endsWith("stand") ? "Go2 stood up" : "Go2 lay down");
        return { ok: true };
      case "/vector/personality":
        this.requireOnline();
        return { ok: true };
      case "/unitree/action": {
        this.requireOnline();
        if (this.kind !== "go2") throw new MockError("Connect Go2 before running Unitree actions");
        if (!this.enabled("teleop")) throw new MockError("Manual driving is disabled in this session");
        if (this.mode !== "idle") throw new MockError("Pause movement before running a Unitree action");
        const action = UNITREE_ACTIONS.find((a) => a.name === body.name);
        if (!action?.available || body.confirmed !== body.name) throw new MockError("This action cannot be run");
        await this.wait(1.2);
        this.event(`Action ${body.name} acknowledged by Go2`);
        return { ok: true, message: `${body.name} acknowledged by Go2.` };
      }
      case "/record/start":
        return this.startRecording(body.space_id);
      case "/record/stop":
        return this.stopRecording();
      case "/spaces": {
        const name = (body.name || "").trim();
        if (!name) throw new MockError("Enter a space name");
        return this.createSpace(name);
      }
      case "/import": {
        const space = this.find(this.spaces, body.space_id, "Space");
        if (!/\.db$/.test(body.path || "")) throw new MockError("Choose a DimOS .db recording");
        const session: Item = { id: uid(), parent: space.id, created: this.clock(), status: "closed", folder: `${space.folder}/import-${uid()}`, source: "import" };
        const stats = zeroStats();
        this.grow(stats, 240);
        this.sessions.unshift(session);
        this.segments.unshift({ id: uid(), parent: session.id, created: this.clock(), status: "closed", folder: session.folder, path: body.path, stats });
        return { ok: true };
      }
      case "/maps":
        return this.generateMap(body);
      case "/cloud/login":
        this.cloud.login = { url: `${CONSOLE_URL}/device?code=MOCK-7Q4K`, code: "MOCK-7Q4K", expires_at: this.clock() + 900 };
        this.cloud.error = null;
        return { ok: true };
      case "/cloud/refresh":
        if (!this.cloud.configured) throw new MockError("Connect DimOS Cloud first");
        await this.wait(0.7);
        return { ok: true };
      case "/agent":
        return this.instruct(body);
      case "/agent/conversation":
        this.agent.messages = [];
        this.agent.busy = false;
        this.agent.conversation_id = uid();
        return { ok: true };
      case "/agent/cancel":
        this.agent.busy = false;
        return { ok: true };
      case "/agent/config":
        this.agent.model = {
          provider: body.provider,
          model: body.model,
          base_url: body.base_url || "",
          vision: !!body.vision,
          configured: !!body.api_key || !!this.agent.model?.configured,
          error: null,
        };
        return { ok: true };
      case "/agent/transcribe":
        throw new MockError("Voice transcription is not simulated. Type the instruction instead.");
    }
    if ((m = path.match(/^\/robots\/([^/]+)$/))) return this.saveRobot(body, m[1]);
    if ((m = path.match(/^\/spaces\/([^/]+)\/rename$/))) {
      const name = (body.name || "").trim();
      if (!name) throw new MockError("Enter a space name");
      return Object.assign(this.find(this.spaces, m[1], "Space"), { name });
    }
    if ((m = path.match(/^\/segments\/([^/]+)\/delete$/))) {
      if (!body.confirmed) throw new MockError("Confirm permanent deletion of the recording and its generated maps");
      const segment = this.find(this.segments, m[1], "Recording");
      this.segments = this.segments.filter((s) => s !== segment);
      this.maps = this.maps.filter((x) => x.parent !== segment.id);
      return { ok: true };
    }
    if ((m = path.match(/^\/maps\/([^/]+)\/cancel$/))) {
      this.find(this.maps, m[1], "Map").status = "cancelled";
      return { ok: true };
    }
    if ((m = path.match(/^\/cloud\/uploads\/([^/]+)\/pause$/))) {
      const backup = this.find(this.segments, m[1], "Recording").backup;
      if (backup && this.cloud.active_segment === m[1]) {
        backup.status = "paused";
        this.cloud.active_segment = null;
      }
      return { ok: true };
    }
    if ((m = path.match(/^\/cloud\/uploads\/([^/]+)$/))) return this.upload(m[1], body);
    if ((m = path.match(/^\/open\/([^/]+)\/([^/]+)$/))) {
      this.event(`Opened ${m[2]} in the file manager (simulated)`);
      return { ok: true };
    }
    throw new MockError(`Mock backend has no handler for ${method} ${path}`, 404);
  }
}
