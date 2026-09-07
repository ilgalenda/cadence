// The events vocabulary.
//
// `readinessMark` is the one worth guarding: it decides what colour a row is, and
// the design system spends `--fault` on exactly one state. A mark that renders
// green for a breached deadline is worse than no mark at all, because a person
// reads it and stops looking.

import { describe, expect, it } from 'vitest';

import {
  addDays, countdown, decideMark, formatDay, formatWhen, localToday, money,
  progressMark, statusMark,
} from './events';

const show = (over: Partial<Parameters<typeof progressMark>[0]> = {}) => ({
  checklist_total: 27, outstanding: 9, ready: false, next_due: '2026-08-21', ...over,
});

describe('the progress mark', () => {
  // Cadence no longer tracks each line — the sheet does — so this says only
  // what it still knows: raised, how much is left, and whether a date has gone.
  it('spends the fault colour on a passed deadline and nothing else', () => {
    expect(progressMark(show(), '2026-08-25').className).toContain('--fault');
    expect(progressMark(show(), '2026-08-01').className).not.toContain('--fault');
  });

  it('counts what is left rather than naming a state', () => {
    expect(progressMark(show(), '2026-08-01').label).toBe('9 to do');
  });

  it('says ready only when the sheet says everything is done', () => {
    const done = progressMark(show({ outstanding: 0, ready: true }), '2026-08-25');
    expect(done.label).toBe('ready');
    expect(done.className).toContain('--locked');
  });

  it('distinguishes a show with no checklist from one that is finished', () => {
    expect(progressMark(show({ checklist_total: 0, outstanding: 0 })).label)
      .toBe('nothing raised');
  });
});

describe('the status mark', () => {
  it('marks only an approved event as committed', () => {
    const green = (['proposed', 'approved', 'declined', 'attended'] as const)
      .filter((s) => statusMark(s).className.includes('--locked'));

    expect(green).toEqual(['approved']);
  });
});

describe('the date range', () => {
  it('collapses a range inside one month', () => {
    expect(formatWhen('2026-09-11', '2026-09-14')).toBe('11–14 Sep 2026');
  });

  it('keeps both months when it straddles one', () => {
    expect(formatWhen('2026-10-30', '2026-11-02')).toBe('30 Oct – 2 Nov 2026');
  });

  it('shows a single day once', () => {
    expect(formatWhen('2026-10-06', '2026-10-06')).toBe('6 Oct 2026');
  });

  it('hands back what it was given rather than printing Invalid Date', () => {
    expect(formatWhen('soon', 'soon')).toBe('soon');
  });
});

describe('the countdown', () => {
  it('reads as a person would say it', () => {
    expect(countdown(9)).toBe('in 9 days');
    expect(countdown(1)).toBe('tomorrow');
    expect(countdown(0)).toBe('today');
  });

  it('says the past plainly instead of showing a minus sign', () => {
    expect(countdown(-1)).toBe('yesterday');
    expect(countdown(-40)).toBe('40 days ago');
  });
});

describe('money', () => {
  it('calls a zero-cost ticket free', () => {
    expect(money(0, 'GBP')).toBe('free');
  });

  it('distinguishes not knowing from costing nothing', () => {
    expect(money(null, 'GBP')).toBe('—');
  });
});

describe('a single day', () => {
  it('reads in the same voice as a range', () => {
    expect(formatDay('2026-08-28')).toBe('28 Aug 2026');
  });

  it('hands back what it was given rather than printing Invalid Date', () => {
    expect(formatDay('')).toBe('');
  });
});

describe('the decide-by mark', () => {
  // The decision is the first deadline an event has, so it earns the same three
  // states the material deadlines get — and the same restraint about red.
  it('turns red only once the decision is overdue', () => {
    expect(decideMark(-1)!.className).toContain('--fault');
    expect(decideMark(0)!.className).not.toContain('--fault');
  });

  it('warns inside a week', () => {
    expect(decideMark(7)!.className).toContain('--drift');
    expect(decideMark(8)!.className).not.toContain('--drift');
  });

  it('says how long is left, not a date', () => {
    expect(decideMark(12)!.label).toBe('decide in 12d');
  });

  it('shows nothing when no decide-by date was given', () => {
    expect(decideMark(null)).toBeNull();
  });
});

describe('localToday', () => {
  it('is the date where the reader is, not the UTC date', () => {
    // Every deadline here is a business date somebody in London or Geneva
    // typed. West of Greenwich the UTC day rolls over first, so a reader in
    // New York was told at 7pm that something was late a day before it was.
    const evening = new Date('2026-09-04T23:30:00Z');
    const offset = evening.getTimezoneOffset();
    const expected = new Date(evening.getTime() - offset * 60_000)
      .toISOString().slice(0, 10);
    expect(localToday(evening)).toBe(expected);
  });
});

describe('addDays', () => {
  it('walks whole dates, and over a month end', () => {
    expect(addDays('2026-08-28', 14)).toBe('2026-09-11');
  });

  it('does not drift across a daylight-saving change', () => {
    // Both ends are plain dates, so the arithmetic stays in dates.
    expect(addDays('2026-10-24', 7)).toBe('2026-10-31');
  });
});
