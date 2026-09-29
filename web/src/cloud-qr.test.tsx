// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { CloudPanel } from "./Cloud";
(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
it("renders a local QR for device approval and removes it after expiry or login", async () => {
  const host = document.createElement("div"),
    root = createRoot(host);
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
  const render = async () =>
    act(async () =>
      root.render(
        <CloudPanel
          cloud={cloud}
          pending={false}
          action={vi.fn()}
          api={vi.fn()}
        />,
      ),
    );
  await render();
  expect(host.querySelector(".cloud-login-qr")?.tagName.toLowerCase()).toBe(
    "svg",
  );
  expect(host.querySelector("a")?.href).toBe(cloud.login.url);
  expect(host.querySelector("img")).toBeNull(); // no third-party QR service receives the login URL
  cloud.login.expires_at = 0;
  await render();
  expect(host.querySelector(".cloud-login-qr")).toBeNull();
  cloud.login = null;
  cloud.configured = true;
  cloud.account = { email: "deck@example.test" };
  await render();
  expect(host.textContent).toContain("deck@example.test");
  expect(host.querySelector(".cloud-login-qr")).toBeNull();
  await act(async () => root.unmount());
});
