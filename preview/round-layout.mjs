export const SIZE = 466;
export const SAFE_RADIUS = 219;
export const HOME_TILES = [
  { x: 107, y: 145, w: 116, h: 108 },
  { x: 243, y: 145, w: 116, h: 108 },
  { x: 175, y: 267, w: 116, h: 108 },
];
export function safeWidth(y, height, margin = 14) {
  const radius = SIZE / 2 - margin;
  const dy = Math.max(Math.abs(y - SIZE / 2), Math.abs(y + height - SIZE / 2));
  return dy >= radius ? 0 : Math.floor(2 * Math.sqrt(radius ** 2 - dy ** 2));
}
export function insideCircle({ x, y, w, h }, margin = 14) {
  const radius = SIZE / 2 - margin;
  return [x, x + w].every(px => [y, y + h].every(py =>
    Math.hypot(px - SIZE / 2, py - SIZE / 2) <= radius + 1e-8));
}
