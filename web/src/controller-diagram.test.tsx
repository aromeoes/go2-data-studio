// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { ControllerDiagram } from "./ControllerDiagram";
(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
it("shows live sticks, bumpers and analog triggers, then clears on release and disconnect", async () => {
  let next: FrameRequestCallback = () => {},
    connected = true;
  const axes = [0, 0, 0, 0],
    buttons = Array.from({ length: 17 }, () => ({ pressed: false, value: 0 }));
  vi.stubGlobal("requestAnimationFrame", (fn: FrameRequestCallback) => {
    next = fn;
    return 1;
  });
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
  vi.spyOn(document, "hasFocus").mockReturnValue(true);
  vi.spyOn(document, "hidden", "get").mockReturnValue(false);
  Object.defineProperty(navigator, "getGamepads", {
    configurable: true,
    value: () =>
      connected
        ? [{ connected: true, mapping: "standard", axes, buttons }]
        : [],
  });
  const host = document.createElement("div"),
    root = createRoot(host);
  const active = (label: string) =>
    host
      .querySelector(`[data-control="${label}"]`)
      ?.getAttribute("data-active");
  try {
    await act(async () => root.render(<ControllerDiagram />));
    await act(async () => next(0));
    expect(active("R1")).toBe("false");
    await act(async () => {
      axes[0] = 0.8;
      axes[3] = -0.7;
      buttons[5].pressed = true;
      buttons[7].value = 0.4;
      next(50);
    });
    for (const label of ["Left stick", "Right stick", "R1", "R2"])
      expect(active(label)).toBe("true");
    expect(
      host
        .querySelector('[data-control="Left stick"] .stick-thumb')
        ?.getAttribute("cx"),
    ).not.toBe("48");
    await act(async () => {
      axes.fill(0);
      buttons.forEach((b) => {
        b.pressed = false;
        b.value = 0;
      });
      next(100);
    });
    expect(active("R1")).toBe("false");
    expect(active("Left stick")).toBe("false");
    await act(async () => {
      connected = false;
      next(150);
    });
    expect(host.textContent).toContain("Press a controller button");
  } finally {
    await act(async () => root.unmount());
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    delete (navigator as any).getGamepads;
  }
});
