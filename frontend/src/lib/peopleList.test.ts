// The judgements the people list makes, tested without a DOM.
//
// `createPeopleList` needs a browser and this repo has no jsdom on purpose (see
// `dom.test.ts`), so the decisions about how people are grouped and labelled are
// pure functions. The grouping is the load-bearing one: it is what replaced a
// numeric "Fit" column and a warning banner with three headings.

import { describe, expect, it } from 'vitest';

import {
  autoEnrichTargets, confidenceOf, enrichPayload, groupPeople, isProfileUrl,
} from './peopleList';

const at = (path: string, name = 'Someone') =>
  ({ full_name: name, recommended_path: path });

describe('groupPeople', () => {
  it('orders groups by what you can do with the person', () => {
    const groups = groupPeople([
      at('campaign_context', 'Erik'),
      at('linkedin_direct', 'Annika'),
      at('email_enrichment', 'Marta'),
    ]);

    expect(groups.map((g) => g.title)).toEqual([
      'Ready to approach', 'Found, needs an email', 'Context only',
    ]);
  });

  it('drops groups nobody is in, rather than showing an empty heading', () => {
    const groups = groupPeople([at('linkedin_direct'), at('linkedin_direct')]);

    expect(groups).toHaveLength(1);
    expect(groups[0].people).toHaveLength(2);
  });

  it('collapses context-only, and explains why on the heading', () => {
    // This is what replaced the drift banner: the heading is the warning, so
    // there is nothing to read twice.
    const [group] = groupPeople([at('campaign_context')]);

    expect(group.collapsed).toBe(true);
    expect(group.note).toContain('inferred, not confirmed');
  });

  it('leaves the approachable groups open and unannotated', () => {
    const groups = groupPeople([at('linkedin_direct'), at('email_enrichment')]);

    expect(groups.every((g) => !g.collapsed)).toBe(true);
    expect(groups.every((g) => !g.note)).toBe(true);
  });

  it('still shows people a signal sweep returned, which carry no path', () => {
    // `detect()` does not set `recommended_path` — those people would otherwise
    // vanish from a screen that only renders known groups.
    const groups = groupPeople([{ full_name: 'Sofia' }, at('linkedin_direct')]);

    expect(groups.map((g) => g.title)).toEqual(['Ready to approach', 'Found']);
    expect(groups[1].people).toHaveLength(1);
  });

  it('never drops or duplicates anyone', () => {
    const people = [
      at('linkedin_direct', 'A'), at('campaign_context', 'B'), { full_name: 'C' },
      at('email_enrichment', 'D'), at('nonsense_path', 'E'),
    ];
    const seen = groupPeople(people).flatMap((g) => g.people);

    expect(seen).toHaveLength(5);
    expect(new Set(seen.map((p) => p.full_name)).size).toBe(5);
  });

  it('has nothing to show for nobody', () => {
    expect(groupPeople([])).toEqual([]);
  });
});

describe('confidenceOf', () => {
  it('maps the three levels onto the sync vocabulary', () => {
    expect(confidenceOf({ confidence: 'high' })).toEqual({ label: 'high', mark: 'ds-mark--locked' });
    expect(confidenceOf({ confidence: 'medium' })).toEqual({ label: 'medium', mark: 'ds-mark--drift' });
    expect(confidenceOf({ confidence: 'low' })).toEqual({ label: 'low', mark: 'ds-mark--idle' });
  });

  it('treats a missing or unknown confidence as the lowest', () => {
    // The backend coerces anything unrecognised to "low" before it ships, but a
    // saved shortlist predates that guarantee and still has to render.
    expect(confidenceOf({})).toEqual({ label: 'low', mark: 'ds-mark--idle' });
    expect(confidenceOf({ confidence: 'PROBABLY' }).mark).toBe('ds-mark--idle');
  });

  it('is case-insensitive, because the model has capitalised it before', () => {
    expect(confidenceOf({ confidence: 'High' }).mark).toBe('ds-mark--locked');
  });
});

// ── Who an automatic reveal is allowed to spend on ──────────────────────────
//
// These two decide where Lusha credit goes now that an email is bought without
// anybody pressing anything. Both exclusions are money, not tidiness.

describe('isProfileUrl', () => {
  it('accepts a real profile', () => {
    expect(isProfileUrl('https://www.linkedin.com/in/annika-lindqvist')).toBe(true);
    expect(isProfileUrl('https://linkedin.com/in/x')).toBe(true);
  });

  it('rejects the URLs that are not a person', () => {
    // canon: these reach Lusha as a match key and "both waste credit and
    // corrupt dedupe". The backend only docks two actionability points for them,
    // which reorders a row and never stops it being enriched.
    expect(isProfileUrl('https://www.linkedin.com/search/results/people/?keywords=northgate')).toBe(false);
    expect(isProfileUrl('https://www.linkedin.com/company/northgate/')).toBe(false);
    expect(isProfileUrl('https://www.linkedin.com/pub/dir/Annika/Lindqvist')).toBe(false);
    expect(isProfileUrl('https://www.linkedin.com/jobs/view/123')).toBe(false);
  });

  it('rejects anything that is not LinkedIn, and anything absent', () => {
    expect(isProfileUrl('https://northgate.com/team/annika')).toBe(false);
    expect(isProfileUrl('')).toBe(false);
    expect(isProfileUrl('   ')).toBe(false);
    expect(isProfileUrl(undefined)).toBe(false);
    expect(isProfileUrl(null)).toBe(false);
    expect(isProfileUrl(42)).toBe(false);
  });

  it('is case-insensitive, because a returned URL is not normalised', () => {
    expect(isProfileUrl('HTTPS://WWW.LINKEDIN.COM/IN/X')).toBe(true);
    expect(isProfileUrl('https://www.LinkedIn.com/Company/Northgate/')).toBe(false);
  });
});

describe('autoEnrichTargets', () => {
  const person = (o: Record<string, any>) => ({
    full_name: 'A', recommended_path: 'linkedin_direct',
    linkedin_url: 'https://www.linkedin.com/in/a', ...o,
  });

  it('takes a confirmed profile with no email yet', () => {
    expect(autoEnrichTargets([person({})])).toHaveLength(1);
  });

  it('never re-buys an address the record already carries', () => {
    // The rule this module has always held: details already on the record were
    // paid for once already. A reopened shortlist must not cost twice.
    expect(autoEnrichTargets([person({ _email: 'a@b.com' })])).toHaveLength(0);
  });

  it('skips a search URL, which would buy a credit against a search page', () => {
    expect(autoEnrichTargets([
      person({ linkedin_url: 'https://www.linkedin.com/search/results/people/?q=x' }),
    ])).toHaveLength(0);
  });

  it('skips context-only people, whose profile was inferred not confirmed', () => {
    // Nobody approaches them — the group heading says so — so an address for
    // them is spend on a row that exists to be read.
    expect(autoEnrichTargets([person({ recommended_path: 'campaign_context' })])).toHaveLength(0);
  });

  it('still takes someone with no profile URL but a known company domain', () => {
    // A name plus a domain is a match key the provider can work with; it is the
    // corrupt key that had to be excluded, not the missing one.
    expect(autoEnrichTargets([
      person({ linkedin_url: '', company_domain: 'northgate.com', recommended_path: 'email_enrichment' }),
    ])).toHaveLength(1);
  });

  it('takes nobody when there is no key at all', () => {
    expect(autoEnrichTargets([person({ linkedin_url: '', company_domain: '' })])).toHaveLength(0);
  });

  it('preserves order, because the enrich response is joined on position', () => {
    const a = person({ full_name: 'A' });
    const b = person({ full_name: 'B' });
    const c = person({ full_name: 'C', _email: 'c@x.com' });
    expect(autoEnrichTargets([a, c, b]).map((p) => p.full_name)).toEqual(['A', 'B']);
  });
});

describe('enrichPayload', () => {
  it('drops a search URL, keeping the person and their usable key', () => {
    const person = {
      full_name: 'Petra Nyman', company: 'Northgate', company_domain: 'northgate.com',
      linkedin_url: 'https://www.linkedin.com/search/results/people/?keywords=northgate',
    };
    const sent = enrichPayload(person);
    expect(sent).not.toHaveProperty('linkedin_url');
    // The half that can still match is untouched.
    expect(sent.full_name).toBe('Petra Nyman');
    expect(sent.company_domain).toBe('northgate.com');
  });

  it('leaves a real profile URL alone — it is the best key there is', () => {
    const person = { full_name: 'A', linkedin_url: 'https://www.linkedin.com/in/a' };
    expect(enrichPayload(person)).toBe(person);
  });

  it('returns the same object when there is no URL at all', () => {
    // Identity matters: the enrich response is joined on position, so the batch
    // must not be rebuilt into different objects for no reason.
    const person = { full_name: 'A' };
    expect(enrichPayload(person)).toBe(person);
  });

  it('does not mutate the person it was given', () => {
    const person = {
      full_name: 'A', linkedin_url: 'https://www.linkedin.com/company/northgate/',
    };
    enrichPayload(person);
    expect(person.linkedin_url).toBe('https://www.linkedin.com/company/northgate/');
  });
});
