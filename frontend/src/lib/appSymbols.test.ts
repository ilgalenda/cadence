// What can be checked about a symbol without rasterising it.
//
// The optical rules — ink coverage, the ink's bounding box, optical centring —
// need a renderer, and live in `scripts/check-symbols.mjs`, which is run while
// drawing rather than during a build. These are the structural rules, which are
// cheap and therefore checked every time: the canvas, the open geometry, and the
// single pen the whole set is drawn with.

import { describe, expect, it } from 'vitest';

import { APP_SYMBOLS, appSymbol } from './appSymbols';
import { AGENTS } from './platform';

const entries = Object.entries(APP_SYMBOLS);

describe('the app symbols', () => {
  it('draws one for every agent', () => {
    const missing = AGENTS.filter((agent) => !appSymbol(agent.slug));

    expect(missing.map((agent) => agent.slug)).toEqual([]);
  });

  it('draws none for an agent that does not exist', () => {
    const slugs = new Set(AGENTS.map((agent) => agent.slug));
    const orphans = entries.map(([slug]) => slug).filter((slug) => !slugs.has(slug));

    expect(orphans).toEqual([]);
  });

  it('returns nothing for an unknown slug, rather than a stand-in', () => {
    expect(appSymbol('not-an-agent')).toBe('');
  });

  it.each(entries)('%s is drawn on the 32 canvas', (_slug, markup) => {
    expect(markup).toContain('viewBox="0 0 32 32"');
  });

  // The pen, identical on all eleven. A per-symbol weight is how a set drifts
  // into looking like several hands; one pen makes that impossible.
  it.each(entries)('%s is drawn with the one pen', (_slug, markup) => {
    expect(markup).toContain('stroke-linejoin="round"');
    expect(markup).toContain('stroke-linecap="round"');
  });

  it('uses a single pen width across the whole set', () => {
    const widths = new Set(
      entries.map(([, markup]) => markup.match(/stroke-width="([\d.]+)"/)?.[1]),
    );

    expect([...widths]).toHaveLength(1);
  });

  // Open geometry, not filled mass. A filled bell and a filled envelope differ
  // only in outline; the set stopped being solid for exactly that reason.
  it.each(entries)('%s is drawn, not filled', (_slug, markup) => {
    expect(markup).toContain('fill="none"');
  });

  // Every symbol carries the optical transform, which is the evidence it went
  // through the measuring rig rather than being eyeballed.
  it.each(entries)('%s carries a solved optical transform', (_slug, markup) => {
    expect(markup).toMatch(/transform="translate\([-\d. ]+\) scale\([\d.]+\)/);
  });

  // ── The inlay ─────────────────────────────────────────────────────────────
  // A shipped mark is a charcoal face on a saturated edge. The structure is
  // checkable even though the optics are not: the same drawing repeated at
  // stepped offsets, the face last so it is painted on top, and the edge taking
  // its hue from the caller's stage rather than naming one of its own.

  it.each(entries)('%s inlays the face on a stepped edge', (_slug, markup) => {
    const offsets = [...markup.matchAll(/<g transform="translate\((\d\.\d\d) \1\)"/g)]
      .map((match) => match[1]);

    // Furthest first, so each copy is painted behind the one in front of it.
    expect(offsets).toEqual(['1.20', '0.90', '0.60', '0.30']);
  });

  it.each(entries)('%s carries exactly one face, drawn last', (_slug, markup) => {
    expect(markup.match(/data-face/g)).toHaveLength(1);
    // Everything after the face opens is the drawing and the closing tags.
    expect(markup.slice(markup.indexOf('data-face'))).not.toContain('--app-edge');
  });

  // One drawing serves all three stages: the edge reads a custom property the
  // tile sets. A symbol that named a stage's token could only ever be that
  // stage's, and would need re-emitting to sit anywhere else.
  it.each(entries)('%s takes its edge hue from the caller', (_slug, markup) => {
    expect(markup).toContain('stroke="rgb(var(--app-edge))"');
    expect(markup).toContain('stroke="rgb(var(--app-face))"');
    expect(markup).not.toMatch(/--app-(find|engage|learn)/);
  });

  // A filled detail belongs to the layer it sits in, or it drops out of the
  // inlay and reads as a speck floating on the rim.
  it.each(entries.filter(([, markup]) => markup.includes('currentColor')))(
    '%s keeps its filled detail inside the inlay',
    (_slug, markup) => {
      // A layer is a group that paints; the group inside it only positions.
      const layers = [...markup.matchAll(/<g [^>]*stroke="[^"]*"[^>]*>/g)];

      expect(layers).toHaveLength(5);
      for (const [layer] of layers) expect(layer).toContain('color="rgb(var(--app-');
    },
  );

  // Where the ink actually lands — coverage, safe area, centring — is not
  // checkable here. Path data mixes absolute coordinates with relative deltas and
  // arc radii, so reading the numbers out tells you nothing about the drawn
  // bounds; only rasterising does. That is `scripts/check-symbols.mjs`, and it is
  // where the optical rules are enforced.
});
