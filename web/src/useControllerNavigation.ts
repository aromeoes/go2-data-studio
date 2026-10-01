import { useEffect, useRef } from "react";

export function focusNext(direction: number) {
  const modal = document.querySelector('[role="dialog"], [role="alertdialog"], dialog[open]');
  const scope = modal || document;
  const controls = Array.from(
    scope.querySelectorAll<HTMLElement>(
      'button, a[href], input, textarea, select, [tabindex="0"]',
    ),
  ).filter(
    (element) =>
      !element.matches(':disabled, [aria-disabled="true"]') &&
      element.tabIndex >= 0 &&
      element.getClientRects().length > 0,
  );
  if (!controls.length) return;
  const current = controls.indexOf(document.activeElement as HTMLElement);
  const next =
    current < 0
      ? direction > 0
        ? 0
        : controls.length - 1
      : (current + direction + controls.length) % controls.length;
  controls[next].focus({ preventScroll: true });
  controls[next].scrollIntoView({ block: "nearest", inline: "nearest" });
}

function selectStep(direction: number) {
  const element = document.activeElement;
  if (!(element instanceof HTMLSelectElement) || element.disabled) return false;
  const options = Array.from(element.options).filter(
    (option) => !option.disabled,
  );
  const current = options.findIndex((option) => option.value === element.value);
  const next = options[(current + direction + options.length) % options.length];
  if (next) {
    element.value = next.value;
    element.dispatchEvent(new Event("change", { bubbles: true }));
  }
  return true;
}

/** UI navigation is disabled while armed; this hook never generates motion. */
export function useControllerNavigation(enabled: () => boolean) {
  const callback = useRef(enabled);
  callback.current = enabled;
  useEffect(() => {
    let frame = 0,
      previous: boolean[] | undefined,
      identity = "",
      last = performance.now();
    const poll = () => {
      const now = performance.now();
      const pad =
        navigator.getGamepads &&
        Array.from(navigator.getGamepads()).find(
          (p) => p?.connected && p.mapping === "standard",
        );
      const key = pad ? `${pad.index}:${pad.id}` : "";
      const pressed = pad ? pad.buttons.map((button) => button.pressed) : [];
      const active =
        callback.current() &&
        document.hasFocus() &&
        !document.hidden &&
        !pressed[4];
      if (pad && previous && key === identity && active && now - last < 200) {
        const edge = (index: number) => pressed[index] && !previous?.[index];
        if (edge(12)) focusNext(-1);
        else if (edge(13)) focusNext(1);
        else if (edge(14)) {
          if (!selectStep(-1)) focusNext(-1);
        } else if (edge(15)) {
          if (!selectStep(1)) focusNext(1);
        } else if (edge(0)) {
          if (!selectStep(1)) {
            const target = document.activeElement;
            if (
              target instanceof HTMLElement &&
              target.matches(
                "button:not(:disabled), a[href], input:not(:disabled)",
              )
            )
              target.click();
          }
        }
        const scroll = pad.axes[3];
        if (Number.isFinite(scroll) && Math.abs(scroll) > 0.25) {
          window.scrollBy(0, scroll * Math.min(now - last, 40) * 0.6);
        }
      }
      // Returning focus or enabling navigation never consumes a held button.
      previous = active && pad ? pressed : undefined;
      identity = key;
      last = now;
      frame = requestAnimationFrame(poll);
    };
    frame = requestAnimationFrame(poll);
    return () => cancelAnimationFrame(frame);
  }, []);
}
