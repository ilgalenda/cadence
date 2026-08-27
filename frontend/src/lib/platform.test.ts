// The launcher groups agents by stage, so a stage is not decoration — an agent
// without one has no section to appear in, and would simply vanish from the only
// page that lists all of them. TypeScript makes the field required; these make
// the *set* coherent, which the type cannot.

import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

import { AGENTS, LEARN, PATHS, STAGES } from './platform';

/**
 * The shipped app-mark tokens, read from the design system rather than restated
 * here. Each stage owns two — the tile's wash and the symbol's inlaid edge — and
 * the set owns one face, shared by all eleven marks.
 */
const declared = new Set(
  [...readFileSync(new URL('../design-system/tokens.css', import.meta.url), 'utf8')
    .matchAll(/--app-([a-z0-9-]+)\s*:/g)].map((match) => match[1]),
);
const FACE = 'face';
const declaredWashes = new Set([...declared].filter(
  (name) => name !== FACE && !name.endsWith('-edge'),
));
const declaredEdges = new Set([...declared]
  .filter((name) => name.endsWith('-edge'))
  .map((name) => name.replace(/-edge$/, '')));

describe('the agent registry', () => {
  it('gives every agent a stage the launcher renders', () => {
    const sections = new Set(STAGES.map((stage) => stage.id));
    const homeless = AGENTS.filter((agent) => !sections.has(agent.stage));

    expect(homeless.map((agent) => agent.name)).toEqual([]);
  });

  it('leaves no section empty, so the launcher never draws a bare heading', () => {
    const empty = STAGES.filter((stage) => !AGENTS.some((agent) => agent.stage === stage.id));

    expect(empty.map((stage) => stage.label)).toEqual([]);
  });

  it('accounts for every agent exactly once across the sections', () => {
    const placed = STAGES.flatMap((stage) => AGENTS.filter((agent) => agent.stage === stage.id));

    expect(placed).toHaveLength(AGENTS.length);
  });
});

describe('the platform registries', () => {
  // Slugs reach storage — a pinned agent is stored by slug — and the path runner
  // resolves by it, so a duplicate is two surfaces answering to one name.
  // `LearnSurface` has no slug: it is identified by where it goes.
  it('keeps slugs unique where a registry has them', () => {
    for (const registry of [AGENTS, PATHS]) {
      const slugs = registry.map((entry) => entry.slug);
      expect(new Set(slugs).size).toBe(slugs.length);
    }
  });

  it('never sends two rail rows to the same place', () => {
    const hrefs = [
      ...AGENTS.map((a) => a.href),
      ...PATHS.map((p) => `/work/paths/${p.slug}`),
      ...LEARN.map((l) => l.href),
    ];

    expect(new Set(hrefs).size).toBe(hrefs.length);
  });
});

// The launcher draws a mark in the colours of the stage it belongs to, keyed on
// the stage id: the tile takes `--app-<stage>` and the symbol's edge takes
// `--app-<stage>-edge`. A fourth stage added without both would render marks on
// no background, or with no edge to inlay them — so the three move together.
describe('the app-mark palette', () => {
  it('gives every stage a wash for its tile', () => {
    const unwashed = STAGES.filter((stage) => !declaredWashes.has(stage.id));

    expect(unwashed.map((stage) => stage.id)).toEqual([]);
  });

  it('gives every stage an edge for its symbols', () => {
    const unlit = STAGES.filter((stage) => !declaredEdges.has(stage.id));

    expect(unlit.map((stage) => stage.id)).toEqual([]);
  });

  it('declares no wash or edge for a stage that does not exist', () => {
    const ids = new Set(STAGES.map((stage) => stage.id));
    const orphans = [...declaredWashes, ...declaredEdges].filter((id) => !ids.has(id));

    expect(orphans).toEqual([]);
  });

  // The face is the set's, not a stage's: every mark shares it, and it is the
  // one token that flips on chrome. A per-stage face would mean three artworks.
  it('declares exactly one face for the whole set', () => {
    expect(declared.has(FACE)).toBe(true);
  });
});
