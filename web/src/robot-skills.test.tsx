// @vitest-environment happy-dom
import { createRoot } from "react-dom/client";
import React, { act } from "react";
import { expect, it } from "vitest";
import { RobotSkillStatus } from "./RobotSkillStatus";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

it("shows asynchronous skill errors and explains stale named places", async () => {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  await act(async () => root.render(<RobotSkillStatus state={{ active: null, phase: "error", message: "No clear destination", places: [{ name: "Reception", usable: false }] }} />));
  expect(container.querySelector('[role="status"]')?.textContent).toContain("No clear destination");
  expect(container.textContent).toContain("Reception: tag again after reconnect");
  expect(container.textContent).toContain("Stop patrol");
  await act(async () => root.unmount());
  container.remove();
});
