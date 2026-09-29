// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { BackupControl } from "./Cloud";
(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

async function fixture(backup?: any, error?: string) {
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const api = error ? vi.fn().mockRejectedValue(new Error(error)) : vi.fn().mockResolvedValue({});
  const action = async (_: string, fn: () => Promise<unknown>) => { await fn(); };
  await act(async () => root.render(<BackupControl
    segment={{ id: "segment123", created: 1700000000, status: "closed", backup } as any}
    spaceName="Office" cloud={{ configured: true } as any}
    api={api} action={action} pending={false}
  />));
  const button = (text: string) => [...host.querySelectorAll("button")].find(b => b.textContent?.includes(text))!;
  const click = async (text: string) => act(async () => button(text).click());
  const close = async () => { await act(async () => root.unmount()); host.remove(); };
  return { host, api, click, close };
}

it("asks for a dataset name before uploading and sends the edited name", async () => {
  const f = await fixture();
  await f.click("Upload dataset");
  expect(f.api).not.toHaveBeenCalled();
  expect(f.host.querySelector("dialog")?.open).toBe(true);
  const input = f.host.querySelector("input")!;
  expect(input.value).toContain("Office");
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "West wing morning");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await f.click("Start upload");
  expect(f.api).toHaveBeenCalledWith("/cloud/uploads/segment123", { name: "West wing morning" });
  expect(f.host.querySelector("dialog")).toBeNull();
  await f.close();
});

it("cancels naming without starting an upload", async () => {
  const f = await fixture();
  await f.click("Upload dataset");
  await f.click("Cancel");
  expect(f.api).not.toHaveBeenCalled();
  expect(f.host.querySelector("dialog")).toBeNull();
  await f.close();
});

it("resumes an existing named upload without offering to rename it", async () => {
  const f = await fixture({ status: "paused", name: "West wing", upload_id: "cloud123" });
  await f.click("Resume upload");
  expect(f.api).toHaveBeenCalledWith("/cloud/uploads/segment123");
  expect(f.host.textContent).toContain("West wing");
  expect(f.host.querySelector("dialog")).toBeNull();
  await f.close();
});

it("keeps the naming dialog open and shows upload errors inside it", async () => {
  const f = await fixture(undefined, "Sign in again");
  await f.click("Upload dataset");
  await f.click("Start upload");
  expect(f.host.querySelector("dialog")?.open).toBe(true);
  expect(f.host.querySelector('[role="alert"]')?.textContent).toBe("Sign in again");
  await f.close();
});
