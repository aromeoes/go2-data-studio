/** Shared pieces for the app screens. */
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Bot, LoaderCircle } from "lucide-react";
import { QRCodeSVG } from "qrcode.react";
import { robot } from "../sdk";
import type { State } from "../types";

// Control commands go over the DimOS SDK session when it is up, like the current app.
const SDK_PATHS = new Set(["/mode", "/heartbeat", "/release", "/stop", "/clear", "/agent", "/vector/personality", "/unitree/action", "/posture/stand", "/posture/lie"]);

export async function api<T = any>(path: string, data: unknown = {}): Promise<T> {
  if (SDK_PATHS.has(path) && robot.current()) return robot.command(path, data);
  const response = await fetch("/api" + path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Go2-Request": "1" },
    body: JSON.stringify(data),
  });
  const value = await response.json();
  if (!response.ok) throw Error(typeof value.detail === "string" ? value.detail : "Could not complete the action");
  return value;
}

export async function get<T = any>(path: string): Promise<T> {
  const response = await fetch("/api" + path, { cache: "no-store" });
  const value = await response.json();
  if (!response.ok) throw Error(typeof value.detail === "string" ? value.detail : "Request failed");
  return value;
}

export type Notify = (text: string, tone?: "info" | "error") => void;
type ToastItem = { id: number; text: string; tone: "info" | "error" };

export function useToasts() {
  const [items, setItems] = useState<ToastItem[]>([]);
  const next = useRef(0);
  const push = useCallback<Notify>((text, tone = "info") => {
    const id = ++next.current;
    setItems((list) => [...list.filter((t) => t.text !== text), { id, text, tone }].slice(-4));
    setTimeout(() => setItems((list) => list.filter((t) => t.id !== id)), tone === "error" ? 7000 : 4000);
  }, []);
  return { items, push };
}

export function Toasts({ items }: { items: ToastItem[] }) {
  return (
    <div className="toasts">
      {items.map((t) => (
        <div key={t.id} className={"toast " + t.tone} role={t.tone === "error" ? "alert" : "status"}>
          {t.text}
        </div>
      ))}
    </div>
  );
}

export const robotLabel = (kind?: string) => (kind === "vector" ? "Anki Vector" : "Unitree Go2");

/** Placeholder for the pixel-art robot picture that comes with the visual design. */
export function RobotPicture({ kind, large = false }: { kind?: string; large?: boolean }) {
  return (
    <div className={"robot-picture" + (large ? " large" : "")} aria-hidden="true">
      <Bot size={large ? 56 : 28} />
      <span>{kind === "vector" ? "Vector" : "Go2"}</span>
    </div>
  );
}

export function Spinner({ children }: { children?: ReactNode }) {
  return (
    <span className="spinner" role="status">
      <LoaderCircle size={18} className="spin" aria-hidden="true" />
      {children}
    </span>
  );
}

/** Seconds since `since` changed, for "Connecting… 12 s" style progress. */
export function useElapsed(active: boolean) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    setElapsed(0);
    if (!active) return;
    const began = Date.now();
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - began) / 1000)), 500);
    return () => clearInterval(id);
  }, [active]);
  return elapsed;
}

/** Frames per second and kilobytes per second of the camera stream, measured once a second. */
export function useStreamRate() {
  const [rate, setRate] = useState({ fps: 0, kbps: 0 });
  useEffect(() => {
    let frames = robot.cameraFrames,
      bytes = robot.cameraBytes;
    const id = setInterval(() => {
      setRate({ fps: robot.cameraFrames - frames, kbps: Math.round((robot.cameraBytes - bytes) / 1024) });
      frames = robot.cameraFrames;
      bytes = robot.cameraBytes;
    }, 1000);
    return () => clearInterval(id);
  }, []);
  return rate;
}

export const cameraLive = (state: State) => {
  const frame = state.telemetry.sensors?.color_image;
  return state.connection === "online" && !!robot.camera && !!frame && Date.now() / 1000 - frame.received < 4;
};

/**
 * Device sign-in: QR, code and link. Requests a code when none is valid and
 * renews it silently when it expires, so the screen stays the same.
 */
export function CloudCode({ cloud, notify }: { cloud: State["cloud"]; notify: Notify }) {
  const asked = useRef(0);
  const login = cloud?.login;
  const valid = !!login && login.expires_at > Date.now() / 1000;
  useEffect(() => {
    if (cloud?.configured || valid || Date.now() - asked.current < 5000) return;
    asked.current = Date.now();
    api("/cloud/login").catch((e) => notify(e.message, "error"));
  });
  return (
    <div className="cloud-code">
      <div className="qr">{valid ? <QRCodeSVG value={login!.url} size={168} marginSize={2} title="Scan to sign in" /> : <Spinner>Getting a code</Spinner>}</div>
      <div className="cloud-code-text">
        <span className="label">Your code</span>
        <strong className="code">{valid ? login!.code : "····-····"}</strong>
        <a className="button" href={valid ? login!.url : undefined} target="_blank" rel="noreferrer">
          Open link instead
        </a>
      </div>
    </div>
  );
}

export function Dialog({ label, children, onClose }: { label: string; children: ReactNode; onClose?: () => void }) {
  return (
    <div className="overlay" onClick={onClose}>
      <section role="dialog" aria-modal="true" aria-label={label} className="dialog" onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.key === "Escape" && onClose?.()}>
        {children}
      </section>
    </div>
  );
}

export const dialogOpen = () => !!document.querySelector('[aria-modal="true"]');

export const gb = (bytes = 0) => (bytes / 1e9).toFixed(2);
