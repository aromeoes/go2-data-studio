import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Info } from "lucide-react";

type Capability = { name: string; example: string; detail: string };
export function HumanCLIHelp({ capabilities }: { capabilities: Capability[] }) {
  const id = useId();
  const anchor = useRef<HTMLButtonElement>(null);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );
  const [open, setOpen] = useState(false);
  const [placement, setPlacement] = useState({
    left: 16,
    top: 16,
    width: 330,
    maxHeight: 400,
  });
  const show = () => {
    clearTimeout(closeTimer.current);
    setOpen(true);
  };
  const leave = () => {
    closeTimer.current = setTimeout(() => setOpen(false), 120);
  };
  useEffect(() => () => clearTimeout(closeTimer.current), []);
  useLayoutEffect(() => {
    if (!open) return;
    const position = () => {
      const rect = anchor.current?.getBoundingClientRect();
      if (!rect) return;
      const width = Math.min(330, window.innerWidth - 32);
      const below = window.innerHeight - rect.bottom - 16;
      const above = below < 220 && rect.top > below;
      const maxHeight = Math.max(
        100,
        Math.min(window.innerHeight * 0.65, above ? rect.top - 16 : below),
      );
      setPlacement({
        width,
        maxHeight,
        left: Math.max(16, Math.min(rect.left, window.innerWidth - width - 16)),
        top: above ? Math.max(16, rect.top - maxHeight) : rect.bottom,
      });
    };
    position();
    window.addEventListener("resize", position);
    window.addEventListener("scroll", position, true);
    return () => {
      window.removeEventListener("resize", position);
      window.removeEventListener("scroll", position, true);
    };
  }, [open]);
  return (
    <span className="humancli-help" onMouseEnter={show} onMouseLeave={leave}>
      <button
        ref={anchor}
        type="button"
        aria-label="HumanCLI skills and commands"
        aria-describedby={open ? id : undefined}
        aria-expanded={open}
        onFocus={show}
        onBlur={() => setOpen(false)}
        onClick={show}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.stopPropagation();
            setOpen(false);
          }
        }}
      >
        <Info size={16} aria-hidden="true" />
      </button>
      {open &&
        createPortal(
          <span
            role="tooltip"
            id={id}
            className="humancli-tooltip"
            style={placement}
            onMouseEnter={show}
            onMouseLeave={leave}
          >
            <strong>HumanCLI skills &amp; commands</strong>
            {capabilities.length ? (
              capabilities.map((c) => (
                <span className="humancli-skill" key={c.name}>
                  <strong>{c.name}</strong>
                  <code>“{c.example}”</code>
                  <span>{c.detail}</span>
                </span>
              ))
            ) : (
              <span>
                Command information will be available after the server update.
              </span>
            )}
          </span>,
          document.body,
        )}
    </span>
  );
}
