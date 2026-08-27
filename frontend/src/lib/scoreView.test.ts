// The verdict's shaping, tested where it was actually wrong.
//
// The page shipped rendering `Object.entries(score_breakdown)` over what the
// scorer returns as a *list*, so the factor column printed `0`, `1` and the
// points column printed `[object Object]`. These pin the shape:
//
//   * a list of rows renders its labels, never its indices;
//   * a penalty keeps its minus sign, or the breakdown stops adding up to the
//     score printed above it;
//   * a field the model could not infer comes back as `""`, and an empty string
//     is not a fact;
//   * a verdict the model read nothing into does not earn a panel.
//
// No jsdom in this suite (see `dom.test.ts`), so only the pure half is covered
// here — which is the half that was broken.

import { describe, expect, it } from 'vitest';

import {
  describeThresholds, formatCap, formatDwell, formatPoints, gradeColour, hasRead,
  normaliseBreakdown, pagePath, readFacts, strengthMark, summariseSignal, type Lead,
} from './scoreView';

/** What `services/lead_scoring.py` actually returns: capped components. */
const breakdown = [
  { label: 'Intent', points: 38, max: 45, detail: 'reached a pricing page' },
  { label: 'Depth', points: 15.7, max: 30, detail: '165s on pages that matter' },
  { label: 'Breadth', points: 10, max: 15, detail: '2 page(s) of real interest' },
  { label: 'Friction', points: -5, max: -15, detail: 'homepage bounce under 10s' },
];

describe('normaliseBreakdown', () => {
  it('reads the rows of a list, not its indices', () => {
    expect(normaliseBreakdown(breakdown).map((row) => row.label))
      .toEqual(['Intent', 'Depth', 'Breadth', 'Friction']);
  });

  it('carries the evidence for each row', () => {
    expect(normaliseBreakdown(breakdown)[0].detail).toBe('reached a pricing page');
  });

  it('reads a page-type identifier as English', () => {
    expect(normaliseBreakdown([{ label: 'case_studies page', points: 6.5 }])[0].label)
      .toBe('case studies page');
  });

  it('drops a row with no label rather than rendering a blank one', () => {
    expect(normaliseBreakdown([{ points: 5 }, ...breakdown])).toHaveLength(4);
  });

  it('carries each component against its own ceiling', () => {
    expect(normaliseBreakdown(breakdown).map((row) => `${row.points}${row.cap}`))
      .toEqual(['38 / 45', '15.7 / 30', '10 / 15', '−5']);
  });

  it('returns nothing for a shape it does not recognise', () => {
    expect(normaliseBreakdown({ pricing_page: 8.5 })).toEqual([]);
    expect(normaliseBreakdown(undefined)).toEqual([]);
    expect(normaliseBreakdown([null, 'pricing'])).toEqual([]);
  });
});

describe('formatPoints', () => {
  it('keeps a penalty negative', () => {
    expect(formatPoints(-4)).toBe('−4');
  });

  // A contribution is shown against its own ceiling, which already says which way
  // it runs — a plus on top of that is noise.
  it('leaves a contribution unsigned', () => {
    expect(formatPoints(8.5)).toBe('8.5');
  });

  it('drops a trailing zero dehaldenl', () => {
    expect(formatPoints(3.0)).toBe('3');
  });

  it('says nothing rather than NaN when there is no number', () => {
    expect(formatPoints(undefined)).toBe('—');
    expect(formatPoints('warm')).toBe('—');
  });
});

describe('formatCap', () => {
  it('states the ceiling a component is measured against', () => {
    expect(formatCap(45)).toBe(' / 45');
  });

  // Friction has a floor, not a ceiling. "−5 / −15" reads as progress towards
  // something, which is exactly backwards.
  it('says nothing for a floor', () => {
    expect(formatCap(-15)).toBe('');
    expect(formatCap(0)).toBe('');
    expect(formatCap(undefined)).toBe('');
  });
});

describe('describeThresholds', () => {
  it('reads the bands the score arrived with', () => {
    expect(describeThresholds([
      { grade: 'A', min: 55 }, { grade: 'B', min: 30 }, { grade: 'C', min: null },
    ])).toBe('A ≥ 55 · B ≥ 30');
  });

  it('says nothing when the score did not carry them', () => {
    expect(describeThresholds(undefined)).toBe('');
    expect(describeThresholds([])).toBe('');
  });
});

describe('the page list', () => {
  it('reads a dwell the way a person would say it', () => {
    expect(formatDwell(45)).toBe('45s');
    expect(formatDwell(130)).toBe('2m 10s');
    expect(formatDwell(120)).toBe('2m');
    expect(formatDwell(0)).toBe('');
  });

  it('shows the path, since the host is always ours', () => {
    expect(pagePath('https://www.acme.example/hardware/open-time-server'))
      .toBe('/hardware/open-time-server');
    expect(pagePath('https://www.acme.example/')).toBe('/');
  });

  it('falls back to whatever it was given rather than dropping it', () => {
    expect(pagePath('not a url')).toBe('not a url');
    expect(pagePath(undefined)).toBe('');
  });
});

describe('readFacts', () => {
  it('skips what the model could not infer', () => {
    const lead: Lead = { role: 'Head of Infrastructure', product_fit: '', source: '   ' };

    expect(readFacts(lead)).toEqual([{ label: 'role', value: 'Head of Infrastructure' }]);
  });

  it('has nothing to show for a bare score', () => {
    expect(readFacts({ lead_score: 21, lead_grade: 'B' })).toEqual([]);
  });
});

describe('hasRead', () => {
  it('is false when the verdict is only the computed half', () => {
    expect(hasRead({ lead_score: 21, lead_grade: 'B', score_signals: [] })).toBe(false);
  });

  it('is true on reasoning alone, with no facts inferred', () => {
    expect(hasRead({ signal_strength_reasoning: 'Read pricing twice in a week.' })).toBe(true);
  });

  // The strength shows in the verdict band, so on its own it is not a panel's
  // worth of reading — counting it would open an empty one.
  it('is false when the strength is all the model returned', () => {
    expect(hasRead({ signal_strength: 'Hot' })).toBe(false);
  });
});

describe('the empty breakdown', () => {
  // The page drops the column headings on a zero count, so the count is the
  // contract, not just a convenience.
  it('normalises to no rows, so the caller knows to drop the headings', () => {
    expect(normaliseBreakdown([])).toHaveLength(0);
    expect(normaliseBreakdown([{ points: 5, max: 45 }])).toHaveLength(0);
  });
});

describe('summariseSignal', () => {
  it('folds a pasted signal onto one line', () => {
    expect(summariseSignal('/pricing 45s\n/case-studies 30s'))
      .toBe('/pricing 45s · /case-studies 30s');
  });

  it('closes up the blank lines a paste leaves behind', () => {
    expect(summariseSignal('/pricing 45s\n\n  \nAcme Bank · Stockholm'))
      .toBe('/pricing 45s · Acme Bank · Stockholm');
  });

  it('has nothing to say about nothing', () => {
    expect(summariseSignal('   ')).toBe('');
    expect(summariseSignal(undefined)).toBe('');
  });
});

describe('the sync vocabulary', () => {
  it('marks a hot lead locked and a cold one idle', () => {
    expect(strengthMark('Hot')).toBe('ds-mark ds-mark--locked');
    expect(strengthMark('Cold')).toBe('ds-mark ds-mark--idle');
  });

  it('falls back to idle rather than inventing a state', () => {
    expect(strengthMark('Scorching')).toBe('ds-mark ds-mark--idle');
    expect(strengthMark(undefined)).toBe('ds-mark ds-mark--idle');
  });

  // The grade and the model's strength sit side by side, so they share a palette:
  // agreement and disagreement are both meant to be visible at a glance.
  it('colours a grade the same way as the strength it corresponds to', () => {
    expect(gradeColour('A')).toBe('signal-locked');
    expect(gradeColour('B')).toBe('signal-drift');
    expect(gradeColour('C')).toBe('ink-muted');
    expect(gradeColour('—')).toBe('ink-muted');
  });
});
