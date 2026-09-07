// The two decisions the requirement fields make before any DOM is touched.
//
// Both are pure and both are load-bearing: one decides which fields a travel
// leg shows, the other decides what a typed answer becomes. The drawing around
// them needs a browser and this suite deliberately has none — see `dom.test.ts`.

import { describe, expect, it } from 'vitest';

import { isRouted, toLeg, type TravelMode } from './eventsRequirements';

const MODES: TravelMode[] = [
  { key: 'flight', label: 'Flight', routed: true },
  { key: 'car', label: 'Car hire', routed: false },
];

describe('isRouted', () => {
  it('a journey shows where it runs from and to', () => {
    expect(isRouted('flight', MODES)).toBe(true);
  });

  it('a car hire does not', () => {
    expect(isRouted('car', MODES)).toBe(false);
  });

  it('a mode the backend added since this page loaded keeps its fields', () => {
    // A spare pair of fields is a smaller failure than a journey somebody
    // cannot say the destination of.
    expect(isRouted('ferry', MODES)).toBe(true);
  });
});

describe('toLeg', () => {
  const raw = { mode: 'flight', from: ' London ', to: 'Amsterdam', nights: '3' };

  it('trims what somebody typed', () => {
    expect(toLeg(raw).from).toBe('London');
  });

  it('reads nights as a number', () => {
    expect(toLeg(raw).nights).toBe(3);
  });

  it('an empty nights box means no nights, not NaN', () => {
    expect(toLeg({ ...raw, nights: '' }).nights).toBe(0);
  });

  it('a word in the nights box means no nights either', () => {
    // The field is a number input, but a paste gets past that on some browsers
    // and `NaN` reaching the request would be refused with nothing to point at.
    expect(toLeg({ ...raw, nights: 'a fortnight' }).nights).toBe(0);
  });

  it('a negative number of nights is none', () => {
    expect(toLeg({ ...raw, nights: '-2' }).nights).toBe(0);
  });

  it('half a night is a night, not a dehaldenl the backend has to round', () => {
    expect(toLeg({ ...raw, nights: '2.7' }).nights).toBe(2);
  });
});
