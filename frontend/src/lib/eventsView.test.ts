// The two decisions the calendar makes before it draws anything.
//
// Both are pure and both are load-bearing: the grouping decides which rows a
// person sees first, and the mark decides what a row says it wants. Neither
// needs a browser, and this repo has no jsdom on purpose (see `dom.test.ts`).

import { describe, expect, it } from 'vitest';

import { groupEvents, oversight, stateMark } from './eventsView';
import type { EventRow } from './events';

const row = (over: Partial<EventRow>): EventRow => ({
  id: 'x', name: 'IBC', year: 2026, location: '', country: '',
  starts_on: '2026-09-11', ends_on: '2026-09-14', status: 'proposed',
  days_until: 9, days_to_decide: 4, decide_by: '2026-09-06', rationale: '',
  readiness: 'not_needed', attendee_count: 1, invited: 0, exhibiting: 0,
  demo_required: 0, demo_type: '', submission_deadline: null, exhibit_cost: null,
  exhibit_currency: 'GBP', quote_contact_name: '', quote_contact_email: '',
  decision_note: '', next_due: null, checklist_total: 0, outstanding: 0,
  ready: false, checked_at: null, ...over,
});

describe('the grouping', () => {
  it('leads with what needs a decision, then what we are committed to', () => {
    const groups = groupEvents([
      row({ id: 'a', status: 'approved' }),
      row({ id: 'b', status: 'proposed' }),
    ]);

    expect(groups.map((g) => g.key)).toEqual(['decide', 'going']);
  });

  it('puts declined and attended together, out of the way', () => {
    const groups = groupEvents([
      row({ id: 'a', status: 'declined' }),
      row({ id: 'b', status: 'attended' }),
    ]);

    expect(groups).toHaveLength(1);
    expect(groups[0].key).toBe('closed');
    expect(groups[0].collapsed).toBe(true);
    expect(groups[0].events).toHaveLength(2);
  });

  it('draws no empty headings', () => {
    expect(groupEvents([row({ status: 'proposed' })]).map((g) => g.key)).toEqual(['decide']);
    expect(groupEvents([])).toEqual([]);
  });
});

describe('the row mark', () => {
  // One clock per row. Two amber pills on one row leaves the reader working out
  // which of them is asking for something.
  it('shows the decision clock while a show is only proposed', () => {
    expect(stateMark(row({ status: 'proposed', days_to_decide: 4 })).label).toBe('decide in 4d');
  });

  it('shows the checklist once we have committed', () => {
    const behind = row({ status: 'approved', checklist_total: 27, outstanding: 9,
                         next_due: '2020-01-01' });
    expect(stateMark(behind).label).toBe('late');
  });

  it('falls back to the status when a proposal carries no decide-by date', () => {
    expect(stateMark(row({ status: 'proposed', days_to_decide: null })).label).toBe('proposed');
  });

  it('says only what a closed show is', () => {
    expect(stateMark(row({ status: 'declined' })).label).toBe('declined');
    expect(stateMark(row({ status: 'attended' })).label).toBe('attended');
  });
});


describe('oversight', () => {
  // All three states were wrong at once, which is why each has its own test.
  const TODAY = '2026-09-04';
  const approved = (over: Partial<EventRow>) =>
    row({ status: 'approved', ready: false, checklist_total: 18, ...over });

  it('an empty calendar is its own state, not an all-clear', () => {
    // "Every deadline is in hand" over nothing at all is a green light for a
    // claim nobody made — and it is the first thing anybody ever sees.
    const said = oversight([], TODAY);
    expect(said.label).toBe('Nothing on the calendar');
    expect(said.tone).toBe('ds-banner--idle');
  });

  it('a deadline months out does not count as close', () => {
    // This said "Deadlines are close" for a show six months away, and since
    // approving is what raises the checklist, every approved show qualified.
    const said = oversight([approved({ next_due: '2027-03-01' })], TODAY);
    expect(said.label).toBe('Nothing outstanding');
  });

  it('a deadline inside the fortnight does', () => {
    const said = oversight([approved({ next_due: '2026-09-10' })], TODAY);
    expect(said.tone).toBe('ds-banner--drift');
    expect(said.body).toContain('1 has work due soon');
  });

  it('a deadline that has passed is late, and outranks everything else', () => {
    const said = oversight([
      approved({ next_due: '2026-08-24' }),
      approved({ next_due: '2026-09-10' }),
    ], TODAY);
    expect(said.tone).toBe('ds-banner--fault');
    expect(said.label).toBe('Something is late');
  });

  it('a show that is ready asks for nothing', () => {
    const said = oversight([approved({ next_due: '2026-08-24', ready: true })], TODAY);
    expect(said.label).toBe('Nothing outstanding');
  });

  it('a proposal past its decide-by still needs a decision', () => {
    const said = oversight([row({ status: 'proposed', days_to_decide: -3 })], TODAY);
    expect(said.body).toContain('1 proposal needs a decision');
  });
});
