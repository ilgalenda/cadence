// The decisions the tracker makes before it draws anything.
//
// Four are pure and all four are load-bearing: the filter decides which accounts
// exist, the grouping decides which a person sees first, and the trail's wording
// is the only place the record's history becomes readable. None needs a browser,
// and this repo has no jsdom on purpose (see `dom.test.ts`), so the DOM builders
// beside these are left to the screenshot pass — the same split `eventsView.test`
// makes.

import { describe, expect, it } from 'vitest';

import { campaignTabs, describe as say, formatStamp, groupRows, matches, NO_FILTERS, tabProgress } from './outboundView';
import type { Counters, TrackerRow, TrailEntry } from './outbound';

const row = (over: Partial<TrackerRow>): TrackerRow => ({
  id: 'x', tracker_id: 't', account: 'Meridian Towers', domain: '', segment: 'Neutral host',
  tier: 1, campaign: 'B-tdd', trigger_text: 'Multi-country scale', trigger_source: 'csv',
  geography: 'Spain/EU', target_roles: 'Group CTO', confidence: 'high',
  deal_lines: [{ shape: 'primary_quorum', quantity: 1 }], attach_support: true,
  fleet_insight_units: 0, value_est_gbp: 1_500, value_note: '', notes: '',
  procurement_route: '', status: 'not_started', next_due: '2026-09-20',
  touches: [1, 2, 3, 4, 5].map((i) => ({ index: i, label: `Touch ${i}`, fired: false, at: '', actor: '' })),
  history: [], ...over,
});

const entry = (over: Partial<TrailEntry>): TrailEntry => ({
  id: 'e', kind: 'touch', touch_index: 1, from_value: 'not_fired', to_value: 'fired',
  actor: 'sam', source: '', at: '2026-08-21T09:00:00+00:00', ...over,
});

describe('the filters', () => {
  it('lets everything through when nothing is set', () => {
    expect(matches(row({}), NO_FILTERS)).toBe(true);
  });

  it('filters on tier, campaign and status', () => {
    expect(matches(row({ tier: 2 }), { ...NO_FILTERS, tier: '1' })).toBe(false);
    expect(matches(row({}), { ...NO_FILTERS, campaign: 'A-jamming' })).toBe(false);
    expect(matches(row({}), { ...NO_FILTERS, status: 'qualified' })).toBe(false);
    expect(matches(row({}), { ...NO_FILTERS, tier: '1', campaign: 'B-tdd' })).toBe(true);
  });

  it('searches the account, segment, geography and trigger', () => {
    for (const query of ['meridian', 'neutral', 'spain', 'multi-country']) {
      expect(matches(row({}), { ...NO_FILTERS, query })).toBe(true);
    }
  });

  it('does not search the notes', () => {
    // They are long and they name competitors and other accounts, so matching
    // them returns rows that have nothing to do with the words typed.
    const noted = row({ notes: 'Qulsar is the timing incumbent to displace' });
    expect(matches(noted, { ...NO_FILTERS, query: 'qulsar' })).toBe(false);
  });

  it('ignores case and surrounding space', () => {
    expect(matches(row({}), { ...NO_FILTERS, query: '  MERIDIAN ' })).toBe(true);
  });
});

describe('the grouping', () => {
  const today = '2026-09-04';

  it('runs in the order the sequence runs', () => {
    const groups = groupRows([
      row({ id: 'a', status: 'qualified' }),
      row({ id: 'b', status: 'not_started' }),
      row({ id: 'c', status: 'sequencing' }),
    ], today);
    expect(groups.map((g) => g.key)).toEqual(['not_started', 'sequencing', 'qualified']);
  });

  it('drops the groups nothing is in', () => {
    const groups = groupRows([row({ status: 'sequencing' })], today);
    expect(groups).toHaveLength(1);
  });

  it('starts the closed-out group out of the way', () => {
    const groups = groupRows([row({ status: 'dead' })], today);
    expect(groups[0].collapsed).toBe(true);
  });

  it('leads each group with what is overdue', () => {
    // A stale mid-sequence account is the thing that costs a reply, so it comes
    // above a tier-1 account that is not yet owed anything.
    const groups = groupRows([
      row({ id: 'fresh', account: 'Fresh', tier: 1, status: 'sequencing', next_due: '2026-10-01' }),
      row({ id: 'stale', account: 'Stale', tier: 3, status: 'sequencing', next_due: '2026-08-20' }),
    ], today);
    expect(groups[0].rows.map((r) => r.account)).toEqual(['Stale', 'Fresh']);
  });

  it('breaks a tie on tier, then on name', () => {
    const groups = groupRows([
      row({ id: '1', account: 'Zeta', tier: 1, next_due: '' }),
      row({ id: '2', account: 'Alpha', tier: 2, next_due: '' }),
      row({ id: '3', account: 'Beta', tier: 1, next_due: '' }),
    ], today);
    expect(groups[0].rows.map((r) => r.account)).toEqual(['Beta', 'Zeta', 'Alpha']);
  });

  it('counts every row it was given', () => {
    const rows = [
      row({ id: 'a', status: 'sequencing' }),
      row({ id: 'b', status: 'sequencing' }),
      row({ id: 'c', status: 'dead' }),
    ];
    const total = groupRows(rows, today).reduce((n, g) => n + g.rows.length, 0);
    expect(total).toBe(rows.length);
  });
});

describe('the trail, in words', () => {
  it('says a touch was sent, and by whom', () => {
    expect(say(entry({}))).toBe('Touch 1 sent by sam');
  });

  it('distinguishes a retracted touch from one never sent', () => {
    expect(say(entry({ to_value: 'not_fired' }))).toBe('Touch 1 retracted by sam');
  });

  it('names both ends of a status move in words, not codes', () => {
    const moved = entry({ kind: 'status', from_value: 'not_started', to_value: 'sequencing' });
    expect(say(moved)).toBe('Not started → In sequence by sam');
  });

  it('carries the source where there is one', () => {
    expect(say(entry({ source: 'artefact import' }))).toContain('(artefact import)');
  });

  it('says what a figure moved from and to', () => {
    const repriced = entry({ kind: 'value', from_value: '1000', to_value: '1500', source: 'reprice' });
    expect(say(repriced)).toBe('Value 1000 → 1500 (reprice)');
  });

  it('reads an edit as what it set', () => {
    const edited = entry({ kind: 'edit', to_value: 'procurement_route=via reseller' });
    expect(say(edited)).toBe('procurement_route=via reseller by sam');
  });
});

describe('formatStamp', () => {
  it('is short, because a trail of full instants is unreadable', () => {
    expect(formatStamp('2026-08-21T09:00:00+00:00')).toMatch(/^2[01] Aug$/);
  });

  it('says nothing rather than "Invalid Date" when there is no stamp', () => {
    expect(formatStamp('')).toBe('—');
  });

  it('hands back anything it cannot parse', () => {
    expect(formatStamp('not a date')).toBe('not a date');
  });
});

describe('the campaign tabs', () => {
  const counters = (over: Partial<Counters> = {}): Counters => ({
    targets: 51, touches: 15, target_touches: 750, in_sequence: 15,
    replies: 2, target_replies: 35, calls: 2, target_calls: 20,
    qualified: 0, target_qualified: 6, qualified_value_gbp: 0,
    total_value_gbp: 250_000, unpriced: 0, uncomposed: 10, goal_gbp: 100_000,
    ...over,
  });

  const campaign = (id: string, name: string, over: Partial<Counters> = {}) =>
    ({ id, name, counters: counters(over) });

  it('draws a tab for a single campaign too', () => {
    // The strip is the campaign's identity band, not a switcher. Hiding it below
    // two gave the same page two header layouts depending on a count nobody is
    // thinking about.
    const tabs = campaignTabs([campaign('a', 'Q4 outbound')], 'a');
    expect(tabs.map((t) => t.name)).toEqual(['Q4 outbound']);
    expect(tabs[0].active).toBe(true);
  });

  it('draws nothing when there is no campaign at all', () => {
    expect(campaignTabs([], '')).toEqual([]);
  });

  it('gives every campaign a tab', () => {
    const tabs = campaignTabs(
      [campaign('a', 'Q4 outbound'), campaign('b', 'Nordic ORAN')], 'a',
    );
    expect(tabs.map((t) => t.name)).toEqual(['Q4 outbound', 'Nordic ORAN']);
  });

  it('marks exactly one tab active', () => {
    const tabs = campaignTabs(
      [campaign('a', 'A'), campaign('b', 'B'), campaign('c', 'C')], 'b',
    );
    expect(tabs.filter((t) => t.active).map((t) => t.id)).toEqual(['b']);
  });

  it('marks none active when the open campaign is not in the list', () => {
    // A remembered id whose campaign has since been deleted must not silently
    // become the first one on the strip.
    const tabs = campaignTabs([campaign('a', 'A'), campaign('b', 'B')], 'gone');
    expect(tabs.some((t) => t.active)).toBe(false);
  });
});

describe('what a tab says beyond its name', () => {
  const counters = (over: Partial<Counters>): Counters => ({
    targets: 51, touches: 0, target_touches: 750, in_sequence: 0,
    replies: 0, target_replies: 35, calls: 0, target_calls: 20,
    qualified: 0, target_qualified: 6, qualified_value_gbp: 0,
    total_value_gbp: 0, unpriced: 0, uncomposed: 0, goal_gbp: 100_000,
    ...over,
  });

  it('leads with qualified where there is any, because that is the goal', () => {
    expect(tabProgress(counters({ qualified: 3, in_sequence: 20 })))
      .toBe('3 qualified · 51 accounts');
  });

  it('falls back to what is in sequence, because that is what moves next', () => {
    expect(tabProgress(counters({ in_sequence: 15 }))).toBe('15 of 51 in sequence');
  });

  it('says a campaign has not started rather than showing two zeros', () => {
    expect(tabProgress(counters({}))).toBe('51 accounts, none started');
  });
});
