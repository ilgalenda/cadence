import { describe, expect, it } from 'vitest';
import { tipPlacement } from './tip';

const rect = (left: number, top: number, width: number, height: number) =>
  ({ left, top, width, height, right: left + width, bottom: top + height } as DOMRect);

const VIEWPORT = { width: 1200, height: 800 };
const PILL = { width: 100, height: 20 };

describe('tipPlacement', () => {
  it('sits above the trigger when there is headroom', () => {
    // Trigger 20px tall at y=400 → pill bottom edge 8px above it.
    expect(tipPlacement(rect(500, 400, 20, 20), PILL, VIEWPORT).top).toBe(372);
  });

  it('flips below the trigger when the pill would not fit above', () => {
    // This is the Owl rail case: a 20px button at the very top of a scroller.
    expect(tipPlacement(rect(60, 4, 20, 20), PILL, VIEWPORT).top).toBe(32);
  });

  it('flips at the exact boundary rather than clipping by a pixel', () => {
    // Headroom of exactly GAP + pill height stays above; one less flips.
    expect(tipPlacement(rect(500, 36, 20, 20), PILL, VIEWPORT).top).toBe(8);
    expect(tipPlacement(rect(500, 35, 20, 20), PILL, VIEWPORT).top).toBe(63);
  });

  it('centres the pill on its trigger', () => {
    expect(tipPlacement(rect(500, 400, 20, 20), PILL, VIEWPORT).left).toBe(460);
  });

  it('clamps against the left edge instead of going off-screen', () => {
    expect(tipPlacement(rect(4, 400, 20, 20), PILL, VIEWPORT).left).toBe(8);
  });

  it('clamps against the right edge instead of going off-screen', () => {
    expect(tipPlacement(rect(1180, 400, 20, 20), PILL, VIEWPORT).left).toBe(1092);
  });

  it('keeps the start of a label wider than the window', () => {
    // Rightmost would be negative here; the left edge wins so the label reads
    // from its beginning rather than its middle.
    expect(tipPlacement(rect(100, 400, 20, 20), { width: 1400, height: 20 }, VIEWPORT).left).toBe(8);
  });
});
