/**
 * The acceptance bar for the scored-lead handoff.
 *
 * This is the seam that closes the gap X-ray had when run by hand: the standalone
 * page could only ever be given a company name, so a lead that had just been
 * scored lost its verdict on the way over. The rules worth pinning are that the
 * payload survives the trip, that it is consumed exactly once, and that a
 * broken or storage-less environment degrades to "no handoff" instead of
 * throwing on a page that would otherwise work fine.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { offerScoredLead, takeScoredLead, type ScoredLead } from './handoff';

const KEY = 'cadence:handoff:scored-lead';

const VERDICT: ScoredLead = {
  company: 'Northgate Nordics',
  role: 'Head of Infrastructure',
  industry: 'Capital markets',
  product_fit: 'PTP grandmaster + GNSS',
  signal_strength: 'strong',
  score: 82,
};

/** A minimal in-memory sessionStorage, so tests do not need a real browser. */
function installStorage(): Map<string, string> {
  const store = new Map<string, string>();
  vi.stubGlobal('sessionStorage', {
    getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  });
  return store;
}

describe('scored-lead handoff', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it('carries the whole verdict across the trip, not just the company', () => {
    installStorage();
    offerScoredLead(VERDICT);

    // The product fit and signal are the point: they are what the discovery
    // prompt weights, and what a typed company name cannot supply.
    expect(takeScoredLead()).toEqual(VERDICT);
  });

  it('consumes the handoff once, so a reload does not re-apply a stale lead', () => {
    installStorage();
    offerScoredLead(VERDICT);

    expect(takeScoredLead()).not.toBeNull();
    expect(takeScoredLead()).toBeNull();
  });

  it('returns null when nothing was handed over', () => {
    installStorage();
    expect(takeScoredLead()).toBeNull();
  });

  it('rejects a verdict with no company — it cannot ground a company search', () => {
    const store = installStorage();
    store.set(KEY, JSON.stringify({ role: 'Head of Infrastructure', score: 40 }));

    expect(takeScoredLead()).toBeNull();
  });

  it('rejects a blank company rather than searching for an empty string', () => {
    const store = installStorage();
    store.set(KEY, JSON.stringify({ company: '   ', role: 'CTO' }));

    expect(takeScoredLead()).toBeNull();
  });

  it('discards a corrupted payload instead of wedging the page', () => {
    const store = installStorage();
    store.set(KEY, '{not json');

    expect(takeScoredLead()).toBeNull();
    // Cleared on the way out, so the bad value cannot fail every later visit.
    expect(store.has(KEY)).toBe(false);
  });

  it('degrades quietly when storage is unavailable', () => {
    vi.stubGlobal('sessionStorage', {
      getItem: () => { throw new Error('denied'); },
      setItem: () => { throw new Error('denied'); },
      removeItem: () => { throw new Error('denied'); },
    });

    // Private mode or a storage-blocking policy must not break the handoff
    // link or the receiving page — both simply fall back to company-only.
    expect(() => offerScoredLead(VERDICT)).not.toThrow();
    expect(takeScoredLead()).toBeNull();
  });
});
