// The vocabulary's acceptance bar.
//
// Three of these functions decide what colour a row is and one decides what a
// total appears to cover, so they are tested against the cases that would be
// misleading rather than merely wrong.

import { describe, expect, it } from 'vitest';

import {
  coverageNote,
  counterTiles,
  dueMark,
  localToday,
  money,
  progress,
  shortMoney,
  statusMark,
  touchesFired,
  type Counters,
  type RowStatus,
} from './outbound';

const COUNTERS: Counters = {
  targets: 51,
  touches: 15,
  target_touches: 750,
  in_sequence: 15,
  replies: 2,
  target_replies: 35,
  calls: 2,
  target_calls: 20,
  qualified: 1,
  target_qualified: 6,
  qualified_value_gbp: 20_000,
  total_value_gbp: 250_000,
  unpriced: 0,
  uncomposed: 10,
  goal_gbp: 100_000,
};

const touches = (fired: boolean[]) =>
  fired.map((f, i) => ({ index: i + 1, label: `Touch ${i + 1}`, fired: f, at: '', actor: '' }));

describe('money', () => {
  it('is unpriced rather than zero when there is no figure', () => {
    expect(money(null)).toBe('unpriced');
    expect(money(0)).toBe('£0');
  });

  it('groups thousands', () => {
    expect(money(1_000)).toBe('£1,000');
  });
});

describe('shortMoney', () => {
  it('reads in millions above a million', () => {
    expect(shortMoney(250_000)).toBe('£250k');
  });

  it('reads in thousands below one', () => {
    expect(shortMoney(340_130)).toBe('£340k');
  });

  it('keeps small figures exact', () => {
    expect(shortMoney(995)).toBe('£995');
  });
});

describe('progress', () => {
  it('is zero rather than NaN when nothing is targeted', () => {
    expect(progress(3, 0)).toBe(0);
  });

  it('clamps a target that has been passed', () => {
    expect(progress(40, 35)).toBe(1);
  });
});

describe('dueMark', () => {
  const today = '2026-09-04';

  it('marks a working account whose touch is late', () => {
    const spec = dueMark({ status: 'sequencing', next_due: '2026-08-20' }, today);
    expect(spec?.label).toBe('overdue');
    expect(spec?.className).toContain('ds-mark--fault');
  });

  it('marks one owed today more softly', () => {
    expect(dueMark({ status: 'sequencing', next_due: today }, today)?.label).toBe('due today');
  });

  it('does not mark an account that has never been touched', () => {
    // It is not late on a touch; it has not begun, and its group says so. On the
    // first real list this rule was the difference between four red pills and
    // thirty-four.
    expect(dueMark({ status: 'not_started', next_due: '2026-08-20' }, today)).toBeNull();
  });

  it('says nothing about one not yet due', () => {
    expect(dueMark({ status: 'sequencing', next_due: '2026-10-01' }, today)).toBeNull();
  });

  it('never marks an account that has replied as late', () => {
    // It is waiting on a person, not on a sequence. A red pill here would make
    // "late" mean "old" and the colour would stop being worth looking at.
    for (const status of ['replied', 'meeting', 'qualified', 'dead'] as RowStatus[]) {
      expect(dueMark({ status, next_due: '2026-08-20' }, today)).toBeNull();
    }
  });

  it('says nothing when no date was ever set', () => {
    expect(dueMark({ status: 'sequencing', next_due: '' }, today)).toBeNull();
  });
});

describe('statusMark', () => {
  it('gives every status a mark', () => {
    const statuses: RowStatus[] = [
      'not_started', 'sequencing', 'replied', 'meeting', 'qualified', 'dead',
    ];
    for (const status of statuses) {
      expect(statusMark(status).label).toBeTruthy();
      expect(statusMark(status).className).toContain('ds-mark');
    }
  });

  it('reserves the locked mark for qualified', () => {
    expect(statusMark('qualified').className).toContain('ds-mark--locked');
    expect(statusMark('sequencing').className).not.toContain('ds-mark--locked');
  });
});

describe('touchesFired', () => {
  it('counts only what was sent', () => {
    expect(touchesFired({ touches: touches([true, true, false, false, false]) })).toBe(2);
  });
});

describe('counterTiles', () => {
  it('reads the funnel in the order it runs', () => {
    expect(counterTiles(COUNTERS).map((t) => t.key)).toEqual([
      'targets', 'touches', 'in_sequence', 'replies', 'calls', 'qualified', 'qualified_value',
    ]);
  });

  it('says what each figure is measured against', () => {
    const touchTile = counterTiles(COUNTERS).find((t) => t.key === 'touches')!;
    expect(touchTile.value).toBe('15');
    expect(touchTile.against).toBe('of 750');
    expect(touchTile.fraction).toBeCloseTo(15 / 750);
  });

  it('omits the goal where none is set', () => {
    const tiles = counterTiles({ ...COUNTERS, target_touches: 0 });
    const touchTile = tiles.find((t) => t.key === 'touches')!;
    expect(touchTile.against).toBe('');
    expect(touchTile.fraction).toBe(0);
  });

  it('reads qualified value against the goal, not against the total', () => {
    const tile = counterTiles(COUNTERS).find((t) => t.key === 'qualified_value')!;
    expect(tile.value).toBe('£20k');
    expect(tile.against).toBe('of £100k');
  });
});

describe('coverageNote', () => {
  it('names the accounts whose figure cannot be repriced', () => {
    // This list has ten. A total that reads as complete over them is the whole
    // failure this sentence exists to prevent.
    const note = coverageNote(COUNTERS);
    expect(note).toContain('£250,000');
    expect(note).toContain('all 51 accounts');
    expect(note).toContain('10 carry a figure with no recorded composition');
  });

  it('names accounts carrying no figure at all separately', () => {
    const note = coverageNote({ ...COUNTERS, unpriced: 3, uncomposed: 0 });
    expect(note).toContain('across 48 of 51');
    expect(note).toContain('3 carry no figure at all');
  });

  it('says both when both are true', () => {
    const note = coverageNote({ ...COUNTERS, unpriced: 3, uncomposed: 10 });
    expect(note).toContain('no figure at all');
    expect(note).toContain('cannot be repriced');
  });

  it('claims completeness only when it is complete', () => {
    const note = coverageNote({ ...COUNTERS, unpriced: 0, uncomposed: 0 });
    expect(note).toBe('£250,000 across all 51 accounts.');
  });
});

describe('localToday', () => {
  it('is the local date, not the UTC one', () => {
    // 23:30 on 4 September in a zone two hours ahead is still the 4th locally,
    // and 21:30 UTC. Reading the UTC date would be right here and wrong twelve
    // hours later, so the assertion is that it tracks the local calendar.
    const at = new Date(2026, 8, 4, 23, 30);
    expect(localToday(at)).toBe('2026-09-04');
  });
});
