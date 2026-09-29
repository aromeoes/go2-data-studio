// @vitest-environment happy-dom
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { VoiceCapture } from "./voice";
let voice: VoiceCapture,
  stop: ReturnType<typeof vi.fn>,
  valid = true;
let callbacks: any;
let amplitude = 0.1;
class Recorder {
  static isTypeSupported() {
    return true;
  }
  state = "inactive";
  ondataavailable?: (event: { data: Blob }) => void;
  onstop?: () => void;
  start() {
    this.state = "recording";
  }
  stop() {
    this.state = "inactive";
    queueMicrotask(() => {
      this.ondataavailable?.({ data: new Blob(["sound"]) });
      this.onstop?.();
    });
  }
}
beforeEach(() => {
  vi.useFakeTimers();
  valid = true;
  amplitude = 0.1;
  stop = vi.fn();
  const track = { stop, onended: null };
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: {
      getUserMedia: vi.fn(async () => ({
        getTracks: () => [track],
        getAudioTracks: () => [track],
      })),
    },
  });
  vi.stubGlobal("MediaRecorder", Recorder);
  vi.stubGlobal(
    "AudioContext",
    class {
      state = "running";
      async resume() {}
      async close() {
        this.state = "closed";
      }
      createAnalyser() {
        return {
          fftSize: 32,
          getFloatTimeDomainData: (a: Float32Array) => a.fill(amplitude),
        };
      }
      createMediaStreamSource() {
        return { connect: vi.fn() };
      }
    },
  );
  vi.spyOn(document, "hasFocus").mockReturnValue(true);
  vi.spyOn(document, "hidden", "get").mockReturnValue(false);
  callbacks = {
    begin: vi.fn(async () => 7),
    valid: () => valid,
    release: vi.fn(),
    submit: vi.fn(async () => {}),
    update: vi.fn(),
  };
  voice = new VoiceCapture(callbacks);
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => ({ text: "what do you see?" }),
    })),
  );
});
afterEach(() => {
  voice.cancel();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
it("pauses before opening microphone, release transcribes once and submits through HumanCLI", async () => {
  await voice.start();
  expect(callbacks.begin.mock.invocationCallOrder[0]).toBeLessThan(
    (navigator.mediaDevices.getUserMedia as any).mock.invocationCallOrder[0],
  );
  await vi.advanceTimersByTimeAsync(300);
  voice.finish();
  voice.finish();
  await vi.advanceTimersByTimeAsync(1);
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(callbacks.submit).toHaveBeenCalledWith("what do you see?", 7);
  expect(stop).toHaveBeenCalled();
  expect(voice.phase).toBe("idle");
  expect(callbacks.release).not.toHaveBeenCalled();
});
it("cancels pending microphone permission and stops the late stream", async () => {
  let resolve: any;
  (navigator.mediaDevices.getUserMedia as any).mockReturnValue(
    new Promise((r) => (resolve = r)),
  );
  const started = voice.start();
  await Promise.resolve();
  voice.finish();
  resolve({ getTracks: () => [{ stop }] });
  await started;
  expect(stop).toHaveBeenCalled();
  expect(fetch).not.toHaveBeenCalled();
  expect(callbacks.release).toHaveBeenCalledWith(7);
});
it("cancellation while acquiring the lease releases only that lease when it arrives", async () => {
  let resolve: any;
  callbacks.begin.mockReturnValue(new Promise((r) => (resolve = r)));
  const started = voice.start();
  voice.cancel();
  resolve(9);
  await started;
  expect(callbacks.release).toHaveBeenCalledWith(9);
  expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled();
});
it("silence and maximum duration never submit instructions", async () => {
  amplitude = 0;
  await voice.start();
  await vi.advanceTimersByTimeAsync(300);
  voice.finish();
  expect(fetch).not.toHaveBeenCalled();
  await voice.start();
  await vi.advanceTimersByTimeAsync(30000);
  expect(voice.phase).toBe("idle");
  expect(fetch).not.toHaveBeenCalled();
});
it("a late transcript after cancellation cannot execute", async () => {
  let resolve: any;
  (fetch as any).mockReturnValue(new Promise((r) => (resolve = r)));
  await voice.start();
  await vi.advanceTimersByTimeAsync(300);
  voice.finish();
  await vi.advanceTimersByTimeAsync(1);
  voice.cancel();
  resolve({ ok: true, json: async () => ({ text: "walk forward" }) });
  await vi.advanceTimersByTimeAsync(1);
  expect(callbacks.submit).not.toHaveBeenCalled();
});
it("control handoff and focus loss invalidate a late transcript", async () => {
  let resolve: any;
  (fetch as any).mockReturnValue(new Promise((r) => (resolve = r)));
  await voice.start();
  await vi.advanceTimersByTimeAsync(300);
  voice.finish();
  await vi.advanceTimersByTimeAsync(1);
  valid = false;
  resolve({ ok: true, json: async () => ({ text: "walk forward" }) });
  await vi.advanceTimersByTimeAsync(1);
  expect(callbacks.submit).not.toHaveBeenCalled();
  expect(voice.phase).toBe("idle");
});
it("network errors release the lease and leave an actionable message", async () => {
  (fetch as any).mockResolvedValue({
    ok: false,
    json: async () => ({ detail: "OpenAI rejected the API key." }),
  });
  await voice.start();
  await vi.advanceTimersByTimeAsync(300);
  voice.finish();
  await vi.advanceTimersByTimeAsync(1);
  expect(callbacks.release).toHaveBeenCalledWith(7);
  expect(callbacks.update).toHaveBeenLastCalledWith(
    "idle",
    "OpenAI rejected the API key.",
  );
});
