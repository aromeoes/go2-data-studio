import { useEffect, useRef, useState } from "react";
import { Compass, ScanLine, ZoomIn, ZoomOut } from "lucide-react";
import type { Grid, State } from "./types";
export function MapCanvas({
  grid,
  pose,
  path,
}: {
  grid?: Grid;
  pose?: State["telemetry"]["pose"];
  path?: number[][];
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [zoom, setZoom] = useState(1);
  const [offset, setOffset] = useState([0, 0]);
  const drag = useRef<number[] | null>(null);
  useEffect(() => {
    const c = canvas.current;
    if (!c) return;
    const render = () => {
      const bounds = c.getBoundingClientRect(),
        dpr = window.devicePixelRatio || 1;
      c.width = bounds.width * dpr;
      c.height = bounds.height * dpr;
      const ctx = c.getContext("2d")!;
      ctx.scale(dpr, dpr);
      const w = bounds.width,
        h = bounds.height;
      ctx.fillStyle = "#171e1a";
      ctx.fillRect(0, 0, w, h);
      ctx.strokeStyle = "#242f27";
      ctx.lineWidth = 1;
      for (let x = 0; x < w; x += 32) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, h);
        ctx.stroke();
      }
      for (let y = 0; y < h; y += 32) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(w, y);
        ctx.stroke();
      }
      if (!grid) return;
      const s = Math.min((w - 70) / grid.width, (h - 70) / grid.height) * zoom;
      const ox = (w - grid.width * s) / 2 + offset[0],
        oy = (h - grid.height * s) / 2 + offset[1];
      const bitmap = document.createElement("canvas");
      bitmap.width = grid.width;
      bitmap.height = grid.height;
      const bctx = bitmap.getContext("2d")!;
      const data = bctx.createImageData(grid.width, grid.height);
      for (let i = 0; i < grid.cells.length; i++) {
        const v = grid.cells[i];
        const p =
          ((grid.height - 1 - Math.floor(i / grid.width)) * grid.width +
            (i % grid.width)) *
          4;
        const col =
          v < 0
            ? [23, 30, 26, 0]
            : v === 0
              ? [59, 76, 61, 255]
              : v > 65
                ? [190, 215, 177, 255]
                : [104, 127, 100, 255];
        data.data.set(col, p);
      }
      bctx.putImageData(data, 0, 0);
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(bitmap, ox, oy, grid.width * s, grid.height * s);
      const point = (x: number, y: number) => [
        ox + ((x - grid.origin[0]) / grid.resolution) * s,
        oy + (grid.height - (y - grid.origin[1]) / grid.resolution) * s,
      ];
      if (path?.length) {
        ctx.strokeStyle = "#f0c478";
        ctx.lineWidth = 2;
        ctx.beginPath();
        path.forEach(([x, y], i) => {
          const p = point(x, y);
          if (i === 0) ctx.moveTo(p[0], p[1]);
          else ctx.lineTo(p[0], p[1]);
        });
        ctx.stroke();
      }
      if (pose) {
        const [x, y] = point(pose.x, pose.y);
        ctx.fillStyle = "#b5d9ad22";
        ctx.beginPath();
        ctx.arc(x, y, 22, 0, Math.PI * 2);
        ctx.fill();
        ctx.save();
        ctx.translate(x, y);
        ctx.rotate(-pose.yaw);
        ctx.fillStyle = "#e9f3e3";
        ctx.beginPath();
        ctx.moveTo(12, 0);
        ctx.lineTo(-7, -6);
        ctx.lineTo(-4, 0);
        ctx.lineTo(-7, 6);
        ctx.closePath();
        ctx.fill();
        ctx.restore();
      }
      ctx.fillStyle = "#a0aea2";
      ctx.font = "11px monospace";
      const meter = s / grid.resolution;
      ctx.fillRect(22, h - 26, meter, 2);
      ctx.fillText("1 m", 22, h - 34);
    };
    render();
    const obs = new ResizeObserver(render);
    obs.observe(c);
    return () => obs.disconnect();
  }, [grid, pose, path, zoom, offset]);
  return (
    <div className="map-surface">
      <canvas
        ref={canvas}
        aria-label="Occupancy map, robot position, and planned route"
        onPointerDown={(e) => {
          drag.current = [e.clientX - offset[0], e.clientY - offset[1]];
          e.currentTarget.setPointerCapture(e.pointerId);
        }}
        onPointerMove={(e) => {
          if (drag.current)
            setOffset([
              e.clientX - drag.current[0],
              e.clientY - drag.current[1],
            ]);
        }}
        onPointerUp={() => (drag.current = null)}
      />
      {!grid && (
        <div className="map-empty">
          <div className="radar">
            <ScanLine size={40} />
          </div>
          <h2>Your space starts here</h2>
          <p>
            Connect Go2 or replay a recording.
            <br />
            The map grows as you explore the space.
          </p>
          <span>LiDAR → occupancy map → navigation</span>
        </div>
      )}
      <div className="map-tools">
        <button
          aria-label="Zoom in"
          onClick={() => setZoom((v) => Math.min(8, v * 1.3))}
        >
          <ZoomIn size={17} />
        </button>
        <button
          aria-label="Zoom out"
          onClick={() => setZoom((v) => Math.max(0.25, v / 1.3))}
        >
          <ZoomOut size={17} />
        </button>
        <button
          aria-label="Center map"
          onClick={() => {
            setZoom(1);
            setOffset([0, 0]);
          }}
        >
          <Compass size={17} />
        </button>
      </div>
      <div className="map-legend">
        <span>
          <i className="swatch free" />
          Free
        </span>
        <span>
          <i className="swatch occupied" />
          Obstacle
        </span>
        <span>
          <i className="swatch unknown" />
          Unobserved
        </span>
      </div>
    </div>
  );
}
