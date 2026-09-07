// Where a bar lands on the year.
//
// A bar in the wrong month is invisible to every build gate and is exactly what
// an off-by-one produces, so the arithmetic is separated from the drawing and
// pinned here. No browser: this repo has no jsdom on purpose.

import { describe, expect, it } from 'vitest';

import { fraction, lane, markAt, pointer, progress } from './eventsTimeline';
import type { EventRow } from './events';

const row = (over: Partial<EventRow>): EventRow => ({
  id: 'x', name: 'IBC', year: 2026, location: '', country: '',
  starts_on: '2026-09-11', ends_on: '2026-09-14', status: 'approved',
  days_until: 9, days_to_decide: null, decide_by: null, rationale: '',
  attendee_count: 1, invited: 0, exhibiting: 0,
  demo_required: 0, demo_type: '', submission_deadline: null, exhibit_cost: null,
  exhibit_currency: 'GBP', quote_contact_name: '', quote_contact_email: '',
  decision_note: '', next_due: null, checklist_total: 0, outstanding: 0,
  ready: false, checked_at: null, ...over,
});

describe('a date on the track', () => {
  it('puts the first day of the year at the very start', () => {
    expect(fraction('2026-01-01', 2026)).toBe(0);
  });

  it('puts the last day just short of the end', () => {
    const at = fraction('2026-12-31', 2026)!;
    expect(at).toBeGreaterThan(0.99);
    expect(at).toBeLessThan(1);
  });

  it('puts midsummer near the middle', () => {
    expect(fraction('2026-07-02', 2026)).toBeCloseTo(0.5, 2);
  });

  it('clamps a date from another year to the nearest edge', () => {
    expect(fraction('2025-06-01', 2026)).toBe(0);
    expect(fraction('2027-06-01', 2026)).toBe(1);
  });

  it('counts the extra day in a leap year', () => {
    // February gains a day, so 1 March sits marginally further into a leap
    // year than into a common one — the year is longer, but March is pushed
    // back by more than the year grew.
    expect(fraction('2028-03-01', 2028)!).toBeGreaterThan(fraction('2026-03-01', 2026)!);
    expect(fraction('2028-12-31', 2028)!).toBeLessThan(1);
  });

  it('reads an unparseable date as nothing rather than NaN', () => {
    expect(fraction('soon', 2026)).toBeNull();
    expect(fraction(null, 2026)).toBeNull();
  });
});

describe('a show on the track', () => {
  it('sits where its dates put it', () => {
    const placed = lane('2026-09-11', '2026-09-14', 2026)!;
    expect(placed.left).toBeCloseTo(69.3, 0);
    expect(placed.width).toBeCloseTo(0.82, 1);
  });

  it('gives a one-day show a bar you can still see', () => {
    const placed = lane('2026-10-06', '2026-10-06', 2026)!;
    expect(placed.width).toBeGreaterThan(0);
  });

  it('stops at the edge when it runs past the year', () => {
    // A show crossing new year belongs on both tracks, ending at each edge
    // rather than overflowing it.
    const placed = lane('2026-12-28', '2027-01-04', 2026)!;
    expect(placed.left + placed.width).toBeLessThanOrEqual(100);
  });

  it('is nothing at all when the start date is unusable', () => {
    expect(lane('whenever', '2026-09-14', 2026)).toBeNull();
  });
});

describe('the deadline a row points at', () => {
  // The same rule the table's mark follows, so the two views never disagree
  // about what a show is waiting on.
  it('is the decision while the show is only proposed', () => {
    const point = pointer(row({ status: 'proposed', decide_by: '2026-08-20' }))!;
    expect(point).toMatchObject({ at: '2026-08-20', kind: 'decide' });
  });

  it('is the next checklist line owed once we have committed', () => {
    const point = pointer(row({ next_due: '2026-08-21', outstanding: 3 }))!;
    expect(point.at).toBe('2026-08-21');
    // Past today, so it reads as a breach rather than a warning.
    expect(point.kind).toBe('breached');
  });

  it('is nothing once the sheet says the show is ready', () => {
    expect(pointer(row({ next_due: '2026-08-21', ready: true }))).toBeNull();
  });

  it('is nothing when a committed show owes nothing', () => {
    expect(pointer(row({ next_due: null }))).toBeNull();
  });

  it('is nothing on a closed show', () => {
    expect(pointer(row({ status: 'declined', next_due: '2026-08-21' }))).toBeNull();
  });
});

describe('the progression', () => {
  it('is a count, not a colour', () => {
    expect(progress(row({ checklist_total: 27, outstanding: 24 }))).toBe('3 of 27 done');
  });

  it('says plainly when nothing has been raised', () => {
    expect(progress(row({ checklist_total: 0 }))).toBe('nothing raised yet');
  });
});

describe('a marker', () => {
  it('lands on the same fraction as the date it marks', () => {
    expect(markAt('2026-07-02', 2026)).toBeCloseTo(50, 0);
  });

  it('is nothing when there is no date', () => {
    expect(markAt(null, 2026)).toBeNull();
  });
});
