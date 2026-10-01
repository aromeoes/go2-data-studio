import { AnalogInput, type Motion } from "./gamepad";
/** Adapter pinned to DimOS c1c3cdc. Browser robot traffic uses the SDK. */
import {
  connect,
  inflateCostmap,
  type Session,
  type CostmapValue,
} from "@dimos/sdk";
import { TeleopMachine, teleopHooks } from "@dimos/sdk/internal/teleop";
import type { State, Grid } from "./types";

export class RobotSDK {
  session: Session | null = null;
  machine: TeleopMachine | null = null;
  camera = "";
  /** Running totals for the live-stream indicator (frames and JPEG bytes received). */
  cameraFrames = 0;
  cameraBytes = 0;
  state: State | null = null;
  ready = false;
  error = "";
  onChange = () => {};
  onArmed = (_armed: boolean) => {};
  private analog = new AnalogInput();
  private analogHeld = false;
  private generation = 0;
  private lastStateAt = 0;
  private pending = new Map<
    string,
    {
      resolve: (value: any) => void;
      reject: (error: Error) => void;
      timer: ReturnType<typeof setTimeout>;
    }
  >();
  private cleanups: (() => void)[] = [];
  private map: Grid | undefined;
  private pose: State["telemetry"]["pose"];
  private client = crypto.randomUUID();

  async start() {
    const generation = ++this.generation;
    const response = await fetch("/api/sdk", { cache: "no-store" });
    if (!response.ok) throw Error("Could not load the DimOS SDK connection");
    const config = await response.json();
    if (generation !== this.generation) return;
    const session = (this.session = connect({ ...config, uiTickMs: 100 }));
    const hooks = teleopHooks(session);
    this.machine = new TeleopMachine(
      { maxLinear: 0.5, maxAngular: 0.5, boost: 1, publishHz: 15 },
      {
        control: (message) => hooks.control(message),
        datagram: (message) => {
          hooks.datagram(this.analog.map(message));
          if (this.analog.selected && this.analogHeld && this.analog.stale()) {
            queueMicrotask(() => this.disarm());
          }
        },
      },
    );
    this.cleanups.push(hooks.onMsg((msg) => this.machine?.onRelayMsg(msg)));
    this.cleanups.push(
      this.machine.subscribe(() =>
        this.onArmed(this.machine?.getSnapshot().phase === "armed"),
      ),
    );
    this.cleanups.push(
      session.status.subscribe(() => {
        const status = session.status.get();
        this.ready =
          status.transport.phase === "connected" &&
          !!status.manifest &&
          !!status.watchedRobot;
        this.error = status.lastError?.message || "";
        this.machine?.connectionChanged(this.ready);
        if (!this.ready) {
          this.state = null;
          this.map = undefined;
          this.pose = undefined;
          this.clearCamera();
          for (const [id, p] of this.pending) {
            clearTimeout(p.timer);
            p.reject(
              Error(
                "SDK connection lost. The command outcome is unknown; it was not retried.",
              ),
            );
            this.pending.delete(id);
          }
        }
        this.onChange();
      }),
    );
    const subscribe = (channel: string, callback: (value: any) => void) => {
      let version = -1;
      this.cleanups.push(
        session.subscribe(channel, (snapshot) => {
          if (!snapshot.slot || snapshot.slot.version === version) return;
          version = snapshot.slot.version;
          try {
            callback(snapshot.slot.value);
          } catch (error) {
            this.error = String(error);
            this.onChange();
          }
        }),
      );
    };
    subscribe("console_state", (value) => {
      this.state = JSON.parse(value) as State;
      this.lastStateAt = performance.now();
      if (this.state.mode !== "teleop") this.machine?.disarm("Mode changed");
      this.onChange();
    });
    subscribe("console_results", (value) => {
      const results = JSON.parse(value) as {
        id: string;
        value: any;
        error: string | null;
      }[];
      for (const result of results) {
        const p = this.pending.get(result.id);
        if (!p) continue;
        this.pending.delete(result.id);
        clearTimeout(p.timer);
        if (result.error) p.reject(Error(result.error));
        else p.resolve(result.value);
      }
    });
    subscribe("color_image", (value: Uint8Array) => {
      this.cameraFrames++;
      this.cameraBytes += value.byteLength;
      this.clearCamera();
      this.camera = URL.createObjectURL(
        new Blob([value as BlobPart], { type: "image/jpeg" }),
      );
      this.onChange();
    });
    subscribe("odom", (value) => {
      this.pose = value;
      this.onChange();
    });
    let mapVersion = 0;
    subscribe("global_costmap", (value: CostmapValue) => {
      const version = ++mapVersion;
      void inflateCostmap(value)
        .then((cells) => {
          if (
            version !== mapVersion ||
            generation !== this.generation ||
            !this.ready
          )
            return;
          const data = Array.from(cells, (n) => (n === 255 ? -1 : n));
          this.map = {
            width: value.w,
            height: value.h,
            resolution: value.res,
            origin: value.origin,
            cells: data,
            known_m2: data.filter((n) => n >= 0).length * value.res ** 2,
            received: Date.now() / 1000,
          };
          this.onChange();
        })
        .catch((error) => {
          this.error = `Map decode failed: ${error}`;
          this.onChange();
        });
    });
  }

  current(): State | null {
    if (
      !this.ready ||
      !this.state ||
      performance.now() - this.lastStateAt > 2000
    )
      return null;
    return {
      ...this.state,
      telemetry: { ...this.state.telemetry, map: this.map, pose: this.pose },
    };
  }

  async command(path: string, body: unknown = {}): Promise<any> {
    if (!this.ready || !this.session || !this.current())
      throw Error("DimOS SDK is not ready. Wait for the robot connection.");
    const id = crypto.randomUUID();
    const value = JSON.stringify({
      id,
      client: this.client,
      path,
      body,
      sent: Date.now() / 1000,
    });
    if (path === "/heartbeat") {
      await this.session.publish("console_heartbeat", value);
      return { ok: true };
    }
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(
          Error(
            "No command completion received. Outcome unknown; command was not retried.",
          ),
        );
      }, 30000);
      this.pending.set(id, { resolve, reject, timer });
      void this.session!.publish("console_command", value).catch((error) => {
        clearTimeout(timer);
        this.pending.delete(id);
        reject(error);
      });
    });
  }

  embodiment: "go2" | "vector" = "go2";

  get inputSource(): "keyboard" | "controller" {
    return this.analog.selected ? "controller" : "keyboard";
  }
  selectInput(source: "keyboard" | "controller") {
    this.disarm();
    this.analog.selected = source === "controller";
  }
  gamepad(value: Motion) {
    if (this.embodiment === "vector") value = { ...value, vy: 0 };
    if (!this.analog.selected || this.machine?.getSnapshot().phase !== "armed")
      return;
    this.analog.update(value);
    const moving = !!(value.vx || value.vy || value.wz);
    // A single held SDK motion key drives its existing 15 Hz scheduler. Only
    // nonzero motion datagrams are transformed; lease and zeroing stay upstream.
    if (moving && !this.analogHeld) this.machine.keyDown("KeyW");
    if (!moving && this.analogHeld) this.machine.keyUp("KeyW");
    this.analogHeld = moving;
  }
  arm(speed: number) {
    if (!this.ready || !this.machine) throw Error("DimOS SDK is disconnected");
    this.machine.config.maxLinear = speed;
    this.machine.config.maxAngular = this.embodiment === "vector" ? 1.5 : 0.5;
    this.machine.arm();
  }
  disarm() {
    this.analog.reset();
    this.analogHeld = false;
    this.machine?.disarm("Controls released");
  }
  keys(pressed: Set<string>) {
    if (this.analog.selected) return;
    const aliases: Record<string, string> = {
      ArrowUp: "w",
      ArrowDown: "s",
      ArrowLeft: "a",
      ArrowRight: "d",
    };
    const codes = new Set(
      [...pressed]
        .filter(
          (key) => this.embodiment !== "vector" || !["q", "e"].includes(key),
        )
        .map((key) => "Key" + (aliases[key] || key).toUpperCase()),
    );
    for (const code of ["KeyQ", "KeyW", "KeyE", "KeyA", "KeyS", "KeyD"]) {
      if (codes.has(code)) this.machine?.keyDown(code);
      else this.machine?.keyUp(code);
    }
  }
  private clearCamera() {
    if (this.camera) URL.revokeObjectURL(this.camera);
    this.camera = "";
  }
  close() {
    ++this.generation;
    this.disarm();
    this.cleanups.splice(0).forEach((fn) => fn());
    this.session?.close();
    this.session = null;
    this.ready = false;
    this.state = null;
    this.map = undefined;
    this.pose = undefined;
    this.clearCamera();
    for (const p of this.pending.values()) {
      clearTimeout(p.timer);
      p.reject(Error("Console closed"));
    }
    this.pending.clear();
  }
}
export const robot = new RobotSDK();
