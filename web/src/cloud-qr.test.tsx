// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { CloudCode } from "./app/ui";
(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
afterEach(() => vi.restoreAllMocks());

it("renders a local QR for device approval and asks for a new code when it expires", async () => {
  const host = document.createElement("div"),
    root = createRoot(host);
  const request = vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true, json: async () => ({}) } as Response);
  const cloud: any = {
    configured: false,
    account: null,
    login: {
      url: "https://console.dimensional.org/device?user_code=ABCD",
      code: "ABCD",
      expires_at: Date.now() / 1000 + 600,
    },
    console_url: "https://console.dimensional.org",
  };
  const render = async () => act(async () => root.render(<CloudCode cloud={cloud} notify={vi.fn()} />));
  await render();
  expect(host.querySelector(".qr svg title")?.textContent).toBe("Scan to sign in");
  expect(host.querySelector("a")?.href).toBe(cloud.login.url);
  expect(host.querySelector("img")).toBeNull(); // no third-party QR service receives the login URL
  expect(request).not.toHaveBeenCalled();
  cloud.login.expires_at = 0;
  await render();
  expect(host.querySelector(".qr svg title")).toBeNull();
  expect(request).toHaveBeenCalledWith("/api/cloud/login", expect.objectContaining({ method: "POST" }));
  await act(async () => root.unmount());
});
