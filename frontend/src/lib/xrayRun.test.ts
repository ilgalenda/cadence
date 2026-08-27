// What the grounding control says about itself.
//
// Grounding decides *who the search looks for*, so how it describes itself is
// the difference between a person correcting a wrong vertical and never knowing
// there was one. One distinction carries most of that, and it is easy to lose:
//
//   * before a search, an empty grounding means "not derived **yet**" — there is
//     nothing wrong, nothing has been asked;
//   * after a search, an empty grounding means the model **did not recognise the
//     company**, so discovery ran with no vertical and no timing pain at all.
//     `test_xray_grounding.py` pins the backend side of this: an unrecognised
//     company must not have a vertical invented for it. The consequence is a
//     materially worse shortlist, and wording it like the harmless case would
//     bury the one signal that says so.
//
// The whole control was a `.ds-drawer`, closed by default, hidden below 72rem.
// These strings only started mattering once it was somewhere it could be read.

import { describe, expect, it } from 'vitest';

import { groundingSummary } from './xrayRun';

describe('groundingSummary', () => {
  it('reads a derived grounding back as the sentence it is', () => {
    expect(groundingSummary('capital markets', 'MiFID II clock sync', true, true))
      .toBe('capital markets · MiFID II clock sync');
  });

  it('keeps whichever half exists when only one was derived', () => {
    expect(groundingSummary('broadcast', '', true, true)).toBe('broadcast');
    expect(groundingSummary('', 'SMPTE 2110', true, true)).toBe('SMPTE 2110');
  });

  it('describes what will happen before a search has run', () => {
    expect(groundingSummary('', '', true, false)).toBe('derived from the name');
  });

  it('warns once a search has run and grounded on nothing', () => {
    expect(groundingSummary('', '', true, true)).toBe('nothing derived');
  });

  it('does not confuse "not yet" with "the model did not recognise it"', () => {
    // The two states look identical in the data and mean opposite things.
    expect(groundingSummary('', '', true, false))
      .not.toBe(groundingSummary('', '', true, true));
  });

  it('says where the grounding came from when it cannot be edited', () => {
    // A scored lead brings its own vertical and product fit from the verdict, so
    // there is nothing to correct — and offering a way in would be a control
    // that does nothing. It says the source instead, in both run states.
    expect(groundingSummary('', '', false, false)).toBe('from the scored lead');
    expect(groundingSummary('capital markets', 'x', false, true)).toBe('from the scored lead');
  });

  it('ignores whitespace, so a cleared field reads as cleared', () => {
    expect(groundingSummary('   ', '\t', true, true)).toBe('nothing derived');
  });
});
