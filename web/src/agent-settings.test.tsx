// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { HumanCLISettings } from "./HumanCLISettings";

it("switching provider clears credentials and image consent, and saves the selected model", async () => {
  (globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const save = vi.fn().mockResolvedValue(undefined);
  await act(async () =>
    root.render(
      <HumanCLISettings
        config={{
          provider: "openai",
          model: "gpt-4.1-mini",
          base_url: "",
          vision: true,
          configured: true,
        }}
        save={save}
        pending={false}
      />,
    ),
  );
  const provider = host.querySelector("select")!;
  await act(async () => {
    provider.value = "ollama";
    provider.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(host.querySelector('[aria-label="HumanCLI API key"]')).toBeNull();
  expect(
    (host.querySelector('[type="checkbox"]') as HTMLInputElement).checked,
  ).toBe(false);
  const input = host.querySelector(
    '[aria-label="HumanCLI model"]',
  ) as HTMLInputElement;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, "local-model");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () =>
    host
      .querySelector("form")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })),
  );
  expect(save).toHaveBeenCalledWith({
    provider: "ollama",
    model: "local-model",
    api_key: "",
    base_url: "",
    vision: false,
  });
  await act(async () => root.unmount());
  host.remove();
});
