// The pin list is read before the first paint and decides what the rail shows,
// so the thing worth pinning down is what it does with input it did not write:
// an older build's list, a hand-edited preference, a since-deleted agent.
//
// `clean` is pure, so this needs no DOM — matching the rest of the suite.

import { describe, expect, it } from 'vitest';

import { AGENTS } from './platform';
import { MAX_PINNED_AGENTS, clean } from './pins';

const real = AGENTS.map((agent) => agent.slug);

describe('clean', () => {
  it('keeps agents that exist, in the order given', () => {
    expect(clean([real[2], real[0]])).toEqual([real[2], real[0]]);
  });

  it('drops a slug for an agent that no longer exists', () => {
    expect(clean([real[0], 'high-intent', real[1]])).toEqual([real[0], real[1]]);
  });

  it('cuts to the ceiling, so the rail cannot grow back into a list', () => {
    expect(clean(real)).toHaveLength(MAX_PINNED_AGENTS);
  });

  it('drops duplicates rather than drawing one agent twice', () => {
    expect(clean([real[0], real[0], real[1]])).toEqual([real[0], real[1]]);
  });

  it('survives anything that is not a list of strings', () => {
    for (const junk of [null, undefined, 'xray', 42, {}, [1, 2], [null]]) {
      expect(clean(junk)).toEqual([]);
    }
  });
});
