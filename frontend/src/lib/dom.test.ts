// The lookup's whole contract is what it does when the element is *not* there,
// so that is what this pins.
//
// No jsdom: `el` touches exactly one thing on `document`, and the rest of this
// suite is deliberately DOM-free. A stub of that one method tests the contract
// without buying a browser environment to do it.

import { afterEach, describe, expect, it, vi } from 'vitest';

import { el } from './dom';

const withElements = (byId: Record<string, unknown>) => {
  vi.stubGlobal('document', { getElementById: (id: string) => byId[id] ?? null });
};

afterEach(() => vi.unstubAllGlobals());

describe('el', () => {
  it('returns the element when the page renders it', () => {
    const composer = { id: 'composer' };
    withElements({ composer });

    expect(el('composer')).toBe(composer);
  });

  it('throws, naming the id, when the element was retired from the markup', () => {
    withElements({});

    expect(() => el('crumb-sep')).toThrow('Missing required element #crumb-sep');
  });
});
