// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { usePushToTalk } from "./usePushToTalk";
import { VoiceCapture } from "./voice";
(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  delete (navigator as any).getGamepads;
});
it("R1 starts only on a fresh press and releases once; B cancels a pending clip", async () => {
  let next: FrameRequestCallback = () => {},
    r1 = true,
    b = false;
  const start = vi
    .spyOn(VoiceCapture.prototype, "start")
    .mockImplementation(async function (this: VoiceCapture) {
      this.run = { abort: new AbortController(), speechMs: 0 };
    });
  const finish = vi
    .spyOn(VoiceCapture.prototype, "finish")
    .mockImplementation(() => {});
  const cancel = vi.spyOn(VoiceCapture.prototype, "cancel");
  vi.stubGlobal("requestAnimationFrame", (fn: FrameRequestCallback) => {
    next = fn;
    return 1;
  });
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
  vi.spyOn(document, "hasFocus").mockReturnValue(true);
  vi.spyOn(document, "hidden", "get").mockReturnValue(false);
  Object.defineProperty(navigator, "getGamepads", {
    configurable: true,
    value: () => [
      {
        connected: true,
        mapping: "standard",
        id: "deck",
        index: 0,
        buttons: Array.from({ length: 6 }, (_, i) => ({
          pressed: i === 5 ? r1 : i === 1 ? b : false,
        })),
      },
    ],
  });
  function Harness() {
    usePushToTalk(
      {
        begin: async () => 1,
        valid: () => true,
        release: vi.fn(),
        submit: async () => {},
      },
      () => true,
    );
    return null;
  }
  const root = createRoot(document.createElement("div"));
  await act(async () => root.render(<Harness />));
  await act(async () => {
    next(0);
    next(16);
  });
  expect(start).not.toHaveBeenCalled();
  await act(async () => {
    r1 = false;
    next(32);
    r1 = true;
    next(48);
    next(64);
  });
  expect(start).toHaveBeenCalledTimes(1);
  await act(async () => {
    r1 = false;
    next(80);
    next(96);
  });
  expect(finish).toHaveBeenCalledTimes(2); // initial held release is harmless
  await act(async () => {
    b = true;
    next(112);
  });
  expect(cancel).toHaveBeenCalled();
  await act(async () => root.unmount());
});
