import { test } from 'node:test';
import assert from 'node:assert/strict';
import { safeWidth, insideCircle, HOME_TILES, SAFE_RADIUS } from '../preview/round-layout.mjs';

test('rectangle width is constrained by both top and bottom circle chords', () => {
  for (let y = 14; y <= 422; y += 3) {
    const width = safeWidth(y, 30);
    assert(insideCircle({ x: 233 - width / 2, y, w: width, h: 30 }));
  }
});
test('top and bottom safe widths are symmetric', () => {
  assert.equal(safeWidth(60, 30), safeWidth(376, 30));
});
test('a band outside the safe circle has zero width', () => {
  assert.equal(safeWidth(0, 20), 0);
  assert.equal(safeWidth(440, 20), 0);
});
test('all three home touch targets fit with a 14 px circular margin', () => {
  assert.equal(SAFE_RADIUS, 219);
  assert.equal(HOME_TILES.length, 3);
  for (const box of HOME_TILES) {
    assert(box.w >= 48 && box.h >= 48);
    assert(insideCircle(box));
  }
});
test('rectangles on the invisible square corners are rejected', () => {
  assert.equal(insideCircle({ x: 10, y: 10, w: 80, h: 80 }), false);
});
