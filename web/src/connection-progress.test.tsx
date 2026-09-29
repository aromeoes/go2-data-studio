// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { ConnectionProgress } from "./ConnectionProgress";
(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
it("shows elapsed wait and delayed-start guidance, then clears after connection", async () => {
  vi.useFakeTimers();
  const host = document.createElement("div"), root = createRoot(host);
  try {
    await act(async () => root.render(<ConnectionProgress connection="connecting" />));
    expect(host.textContent).toContain("Connecting to Go2");
    expect(host.textContent).toContain("20–30 seconds");
    await act(async () => vi.advanceTimersByTime(46000));
    expect(host.textContent).toContain("46s");
    expect(host.textContent).toContain("Still waiting");
    await act(async () => root.render(<ConnectionProgress connection="reconnecting" />));
    expect(host.textContent).toContain("Reconnecting to Go2");
    expect(host.querySelector(".connection-elapsed")?.textContent).toBe("0s");
    await act(async () => root.render(<ConnectionProgress connection="online" />));
    expect(host.textContent).toBe("");
    expect(vi.getTimerCount()).toBe(0);
  } finally {
    await act(async () => root.unmount());
    vi.useRealTimers();
  }
});
