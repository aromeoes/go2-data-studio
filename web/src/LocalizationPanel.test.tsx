// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, it, expect, vi } from "vitest";
import { LocalizationPanel } from "./LocalizationPanel";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe("localization controls", () => {
  it("shows progress and blocks selection during movement", async () => {
    const host = document.createElement("div");
    const root = createRoot(host);
    const onSelect = vi.fn();
    await act(async () => root.render(<LocalizationPanel maps={[]} selected="saved" connection="online"
      state={{status: "verifying", message: "Verifying alignment (2/3)", fitness: .91, rmse: .04}}
      disabled onSelect={onSelect} />));
    expect(host.textContent).toContain("Verifying alignment (2/3)");
    expect(host.textContent).toContain("Overlap 91%");
    expect(host.querySelector("select")?.disabled).toBe(true);
    expect(host.querySelector("button")?.disabled).toBe(true);
    await act(async () => root.unmount());
  });
  it("does not claim localization while disconnected and lets the user return to live mapping", async () => {
    const host = document.createElement("div"); const root = createRoot(host); const onSelect = vi.fn();
    await act(async () => root.render(<LocalizationPanel maps={[]} selected="saved" connection="offline"
      state={{status: "localized"}} disabled={false} onSelect={onSelect} />));
    expect(host.textContent).toContain("Waiting for connection");
    const select = host.querySelector("select")!;
    await act(async () => { select.value = ""; select.dispatchEvent(new Event("change", {bubbles:true})); });
    expect(onSelect).toHaveBeenCalledWith(null);
    await act(async () => root.unmount());
  });
});
