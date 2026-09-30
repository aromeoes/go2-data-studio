/** Simulated room for mock mode: occupancy truth, LiDAR reveal, routes and a camera view. */
export type Pose = { x: number; y: number; yaw: number };

export const RES = 0.1;
export const WIDTH = 140;
export const HEIGHT = 100;
export const ORIGIN = [-7, -5];
export const START: Pose = { x: -4.5, y: -3, yaw: 0.6 };

const index = (cx: number, cy: number) => cy * WIDTH + cx;
const cell = (x: number, y: number) => [
  Math.floor((x - ORIGIN[0]) / RES),
  Math.floor((y - ORIGIN[1]) / RES),
];
const center = (cx: number, cy: number) => [
  ORIGIN[0] + (cx + 0.5) * RES,
  ORIGIN[1] + (cy + 0.5) * RES,
];

function build() {
  const walls = new Uint8Array(WIDTH * HEIGHT);
  const box = (x0: number, y0: number, x1: number, y1: number) => {
    for (let cy = y0; cy <= y1; cy++)
      for (let cx = x0; cx <= x1; cx++) walls[index(cx, cy)] = 1;
  };
  box(0, 0, WIDTH - 1, 1);
  box(0, HEIGHT - 2, WIDTH - 1, HEIGHT - 1);
  box(0, 0, 1, HEIGHT - 1);
  box(WIDTH - 2, 0, WIDTH - 1, HEIGHT - 1);
  // Dividing wall with a doorway, a meeting table, two desks and a pillar.
  box(78, 0, 80, 38);
  box(78, 52, 80, HEIGHT - 1);
  box(30, 58, 52, 68);
  box(8, 84, 28, 92);
  box(100, 70, 126, 78);
  box(108, 20, 112, 24);
  return walls;
}

export const walls = build();

/** Cells the robot body cannot occupy: walls grown by the robot radius. */
export const blocked = (() => {
  const grown = new Uint8Array(WIDTH * HEIGHT);
  const radius = 3;
  for (let cy = 0; cy < HEIGHT; cy++)
    for (let cx = 0; cx < WIDTH; cx++) {
      if (!walls[index(cx, cy)]) continue;
      for (let dy = -radius; dy <= radius; dy++)
        for (let dx = -radius; dx <= radius; dx++) {
          const nx = cx + dx,
            ny = cy + dy;
          if (nx >= 0 && ny >= 0 && nx < WIDTH && ny < HEIGHT)
            grown[index(nx, ny)] = 1;
        }
    }
  return grown;
})();

export function isBlocked(x: number, y: number) {
  const [cx, cy] = cell(x, y);
  return (
    cx < 0 || cy < 0 || cx >= WIDTH || cy >= HEIGHT || !!blocked[index(cx, cy)]
  );
}

/** Distance to the first wall along a ray, in meters. */
export function cast(x: number, y: number, angle: number, max = 8) {
  const dx = Math.cos(angle) * 0.05,
    dy = Math.sin(angle) * 0.05;
  for (let d = 0; d < max; d += 0.05) {
    x += dx;
    y += dy;
    const [cx, cy] = cell(x, y);
    if (cx < 0 || cy < 0 || cx >= WIDTH || cy >= HEIGHT) return d;
    if (walls[index(cx, cy)]) return d;
  }
  return max;
}

export const emptyMap = () => new Int8Array(WIDTH * HEIGHT).fill(-1);

/** Marks what a LiDAR at this pose would observe. Returns true when the map changed. */
export function reveal(known: Int8Array, pose: Pose, range = 4.5) {
  let changed = false;
  for (let ray = 0; ray < 180; ray++) {
    const angle = (ray / 180) * Math.PI * 2;
    const dx = Math.cos(angle) * 0.05,
      dy = Math.sin(angle) * 0.05;
    let x = pose.x,
      y = pose.y;
    for (let d = 0; d < range; d += 0.05) {
      x += dx;
      y += dy;
      const [cx, cy] = cell(x, y);
      if (cx < 0 || cy < 0 || cx >= WIDTH || cy >= HEIGHT) break;
      const i = index(cx, cy);
      const value = walls[i] ? 100 : 0;
      if (known[i] !== value) {
        known[i] = value;
        changed = true;
      }
      if (value) break;
    }
  }
  return changed;
}

/** Breadth-first route over cells the robot can occupy. */
function search(
  from: Pose,
  accept: (i: number, cx: number, cy: number) => boolean,
) {
  const [sx, sy] = cell(from.x, from.y);
  const start = index(sx, sy);
  const parent = new Int32Array(WIDTH * HEIGHT).fill(-1);
  parent[start] = start;
  const queue = [start];
  for (let head = 0; head < queue.length; head++) {
    const i = queue[head];
    const cx = i % WIDTH,
      cy = Math.floor(i / WIDTH);
    if (i !== start && accept(i, cx, cy)) {
      const route: number[][] = [];
      for (let at = i; at !== start; at = parent[at])
        route.push(center(at % WIDTH, Math.floor(at / WIDTH)));
      route.reverse();
      // Keep every fifth point so the robot moves smoothly between waypoints.
      return route.filter((_, n) => n % 5 === 4 || n === route.length - 1);
    }
    for (const [dx, dy] of [
      [1, 0],
      [-1, 0],
      [0, 1],
      [0, -1],
    ]) {
      const nx = cx + dx,
        ny = cy + dy;
      if (nx < 0 || ny < 0 || nx >= WIDTH || ny >= HEIGHT) continue;
      const n = index(nx, ny);
      if (parent[n] !== -1 || blocked[n]) continue;
      parent[n] = i;
      queue.push(n);
    }
  }
  return null;
}

export function routeTo(from: Pose, x: number, y: number) {
  const [tx, ty] = cell(x, y);
  return search(from, (_, cx, cy) => cx === tx && cy === ty);
}

/** Nearest reachable cell that has not been observed yet. */
export function routeToUnknown(from: Pose, known: Int8Array) {
  return search(from, (i) => known[i] < 0);
}

/** A reachable, already observed cell a few meters away, for patrol. */
export function routeToPatrol(from: Pose, known: Int8Array, seed: number) {
  let count = 0;
  const skip = 150 + (seed % 7) * 90;
  return search(from, (i) => known[i] === 0 && ++count > skip);
}

export function knownArea(known: Int8Array) {
  let cells = 0;
  for (const v of known) if (v >= 0) cells++;
  return cells * RES * RES;
}

/** First-person view of the room, drawn by casting one ray per column. */
export function drawCamera(ctx: CanvasRenderingContext2D, pose: Pose) {
  const w = ctx.canvas.width,
    h = ctx.canvas.height;
  const ceiling = ctx.createLinearGradient(0, 0, 0, h / 2);
  ceiling.addColorStop(0, "#1b2420");
  ceiling.addColorStop(1, "#2b3932");
  ctx.fillStyle = ceiling;
  ctx.fillRect(0, 0, w, h / 2);
  const floor = ctx.createLinearGradient(0, h / 2, 0, h);
  floor.addColorStop(0, "#2a2f2a");
  floor.addColorStop(1, "#4a5248");
  ctx.fillStyle = floor;
  ctx.fillRect(0, h / 2, w, h / 2);
  const fov = 1.2,
    step = 3;
  for (let col = 0; col < w; col += step) {
    const offset = fov * (0.5 - col / w);
    const distance = cast(pose.x, pose.y, pose.yaw + offset, 9);
    const depth = Math.max(0.15, distance * Math.cos(offset));
    const height = Math.min(h, (h * 0.75) / depth);
    const shade = Math.max(40, 205 - depth * 24);
    ctx.fillStyle = `rgb(${shade * 0.78},${shade * 0.9},${shade * 0.74})`;
    ctx.fillRect(col, (h - height) / 2, step, height);
  }
  ctx.fillStyle = "rgba(0,0,0,.55)";
  ctx.fillRect(8, 8, 150, 20);
  ctx.fillStyle = "#e9f3e3";
  ctx.font = "11px monospace";
  ctx.fillText("SIMULATED CAMERA", 14, 22);
}
