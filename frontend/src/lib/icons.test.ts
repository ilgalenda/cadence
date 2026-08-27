// The rail's own rule, made checkable.
//
// `Rail.astro` states it — *every path has its own icon* — and the three Paths
// rows broke it from the day they were written, all three hard-coding
// `icon: 'path'`. Collapsed, that is one glyph standing for three destinations
// and no way to tell them apart without hovering each in turn.
//
// A written rule is not an enforced one. `allNamed()` has carried the comment
// "used by the rail's own test" since it was added, and no such test existed.

import { describe, expect, it } from 'vitest';

import { AGENTS, LEARN, PATHS } from './platform';
import { ICONS, allNamed, icon } from './icons';

/** Every destination the rail draws, in the order it draws them. */
const RAIL_ROWS = [
  { name: 'Home', icon: 'home' },
  { name: 'Owl', icon: 'owl' },
  ...AGENTS.map((a) => ({ name: a.name, icon: a.icon })),
  ...PATHS.map((p) => ({ name: p.name, icon: p.icon })),
  ...LEARN.map((l) => ({ name: l.name, icon: l.icon })),
];

describe('the rail icon set', () => {
  it('draws every destination', () => {
    expect(allNamed(RAIL_ROWS.map((r) => r.icon))).toEqual([]);
  });

  it('gives every destination its own icon', () => {
    const byIcon = new Map<string, string[]>();
    for (const row of RAIL_ROWS) {
      byIcon.set(row.icon, [...(byIcon.get(row.icon) ?? []), row.name]);
    }
    const shared = [...byIcon].filter(([, rows]) => rows.length > 1);

    expect(shared).toEqual([]);
  });

  // Distinct *names* are not enough: two names can point at the same drawing,
  // which collapsed is the same defect wearing a different key.
  it('never draws one glyph under two names', () => {
    const byBody = new Map<string, string[]>();
    for (const [name, body] of Object.entries(ICONS)) {
      byBody.set(body, [...(byBody.get(body) ?? []), name]);
    }
    const aliases = [...byBody.values()].filter((names) => names.length > 1);

    expect(aliases).toEqual([]);
  });

  it('returns nothing for a name it does not have, rather than a stand-in', () => {
    expect(icon('not-an-icon')).toBe('');
  });
});
