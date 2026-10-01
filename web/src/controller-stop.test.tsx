// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { useControllerStop } from "./useControllerStop";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("B stops once per press in any mode and never fires while the app is unfocused", async () => {
  let next: FrameRequestCallback = () => {},
    held = false,
    focused = true;
  const stop = vi.fn();
  vi.stubGlobal("requestAnimationFrame", (fn: FrameRequestCallback) => {
    next = fn;
    return 1;
  });
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
  vi.spyOn(document, "hasFocus").mockImplementation(() => focused);
  vi.spyOn(document, "hidden", "get").mockReturnValue(false);
  Object.defineProperty(navigator, "getGamepads", {
    configurable: true,
    value: () => [
      {
        connected: true,
        mapping: "standard",
        index: 0,
        id: "test-controller",
        buttons: [{ pressed: false }, { pressed: held }],
      },
    ],
  });
  function Harness() {
    useControllerStop(() => true, stop);
    return null;
  }
  const root = createRoot(document.createElement("div"));
  await act(async () => root.render(<Harness />));
  await act(async () => {
    next(0);
    held = true;
    next(16);
    next(32);
  });
  expect(stop).toHaveBeenCalledTimes(1);
  await act(async () => {
    held = false;
    next(48);
    focused = false;
    held = true;
    next(64);
    focused = true;
    next(80);
  });
  expect(stop).toHaveBeenCalledTimes(1);
  await act(async () => {
    held = false;
    next(96);
    held = true;
    next(112);
  });
  expect(stop).toHaveBeenCalledTimes(2);
  await act(async () => root.unmount());
  delete (navigator as any).getGamepads;
});
