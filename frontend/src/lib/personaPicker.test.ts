// What the persona control says about itself.
//
// Two distinctions carry the whole meaning of this control, and both were got
// wrong before:
//
//   * choosing nothing is *not* zero personas — `Persona.md` is authoritative in
//     the prompt regardless, so an empty selection narrows nothing;
//   * a list that failed to load is *not* a vault with no personas in it, and
//     the two need different actions from whoever is reading.
//
// The second one cost a session: a stale server 404'd the endpoint, the fetch
// caught it and said nothing, and an empty list was indistinguishable from
// "there are none".

import { describe, expect, it } from 'vitest';

import { personaStatus, personaSummary } from './personaPicker';

describe('personaSummary', () => {
  it('says nothing is narrowed when nothing is chosen', () => {
    // Not "0 chosen": the search still has every configured persona in play.
    expect(personaSummary(24, 0, false)).toBe('24 · all considered');
  });

  it('counts the narrowing once there is one', () => {
    expect(personaSummary(24, 3, false)).toBe('24 · 3 chosen');
  });

  it('distinguishes a failed load from an empty vault', () => {
    expect(personaSummary(0, 0, true)).toBe('could not load');
    expect(personaSummary(0, 0, false)).toBe('none configured');
  });

  it('reports the failure even if something was added by hand first', () => {
    expect(personaSummary(1, 1, true)).toBe('could not load');
  });
});

describe('personaStatus', () => {
  it('is silent when the list loaded and has content', () => {
    expect(personaStatus(24, false)).toBe('');
  });

  it('explains a failed load, and says the search is unnarrowed', () => {
    const note = personaStatus(0, true);
    expect(note).toContain('could not be loaded');
    expect(note).toContain('nothing is being narrowed');
  });

  it('explains an empty vault differently, and names the file to fix', () => {
    const note = personaStatus(0, false);
    expect(note).toContain('Persona.md');
    expect(note).not.toContain('could not be loaded');
  });
});
