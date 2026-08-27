// The step contract, tested where it is easiest to get wrong.
//
// `paths.ts` is written pure — no DOM, no fetch, no storage — precisely so the
// rules a run depends on can be checked here rather than by clicking through the
// app. What matters most:
//
//   * the handoff actually carries the scored verdict to X-ray, because that is
//     the whole reason a path beats running the agents by hand;
//   * a step cannot run before its precondition is met;
//   * a path stops where its agents stop, and nothing after that looks pending;
//   * stale state is dropped when an earlier step is re-run, so the run can never
//     show people found for a company that is no longer chosen;
//   * revealed contact details never reach browser storage.

import { describe, expect, it } from 'vitest';

import { agentBySlug, pathBySlug } from './platform';
import {
  absorb, canRun, inputProblem, isDone, isRunnable, pickCompany, pickPerson, progress,
  requestFor, responseProblem, storableCarry, stopsAt, summarise, walk, type Carry,
} from './paths';

const websiteLead = pathBySlug('website-lead')!;
const icp = pathBySlug('icp')!;
const inbound = pathBySlug('inbound')!;

/** A scored lead, as `/leads/analyze` returns it under `final`. */
const SCORED = {
  company: 'Northgate Nordics',
  lead_grade: 'A',
  lead_score: 82,
  product_fit: 'Open Time Server',
  signal_strength: 'strong',
  role: 'Head of Infrastructure',
};

describe('the handoff to X-ray', () => {
  it('carries the whole scored verdict, not just the company name', () => {
    // This is the capability the path exists for: `signal_analysis` is threaded
    // into the discovery prompt, so the search knows *why* the lead is warm.
    const carry = absorb('scoring', { final: SCORED }, {});
    const { url, body } = requestFor('xray', carry);

    expect(url).toBe('/api/sales/xray/search');
    expect(body.company).toBe('Northgate Nordics');
    expect(body.signal_analysis).toEqual(SCORED);
  });

  it('sends no signal_analysis when the company came from a GTM pick', () => {
    // Nothing was scored, so there is no signal to ground the search in, and
    // sending an empty one would be a claim about a lead we never read.
    const carry = pickCompany('Northgate Nordics', absorb('gtm', { final: { companies: ['Northgate Nordics'] } }, {}));
    const { body } = requestFor('xray', carry);

    expect(body.company).toBe('Northgate Nordics');
    expect(body).not.toHaveProperty('signal_analysis');
  });
});

describe('preconditions', () => {
  it('will not run X-ray before a company is known', () => {
    expect(canRun('xray', {})).toBe(false);
    expect(canRun('xray', { company: 'Northgate Nordics' })).toBe(true);
  });

  it('lets the openers run with nothing in hand', () => {
    expect(canRun('scoring', {})).toBe(true);
    expect(canRun('gtm', {})).toBe(true);
  });

  it('refuses a step whose agent has no contract', () => {
    // Call analysis is built but is not a path step — being an agent is not
    // enough, a step has to declare how it gets its input and what it gives.
    expect(canRun('call-analysis', { company: 'Northgate Nordics' })).toBe(false);
  });

  it('states what an unsendable step is missing', () => {
    expect(inputProblem('scoring', { text: '  ' })).toMatch(/paste/i);
    expect(inputProblem('scoring', { text: '/pricing 45s' })).toBe('');
    expect(inputProblem('gtm', {})).toMatch(/vertical/i);
    expect(inputProblem('gtm', { seedCompany: 'Northgate' })).toBe('');
  });
});

describe('absorbing a result', () => {
  it('takes both the verdict and the company from scoring', () => {
    const carry = absorb('scoring', { final: SCORED }, {});
    expect(carry.lead).toEqual(SCORED);
    expect(carry.company).toBe('Northgate Nordics');
  });

  it('leaves the company unset when the lead could not be identified', () => {
    const carry = absorb('scoring', { final: { lead_grade: 'D', company: '' } }, {});
    expect(carry.company).toBeUndefined();
    expect(canRun('xray', carry)).toBe(false);
  });

  it('normalises GTM companies whether they arrive as strings or objects', () => {
    const carry = absorb('gtm', {
      final: { companies: ['Northgate Nordics', { name: 'Vantage Exchange', rationale: 'MiFID II exposure' }] },
    }, {});

    expect(carry.companies).toEqual([
      { name: 'Northgate Nordics', why: '' },
      { name: 'Vantage Exchange', why: 'MiFID II exposure' },
    ]);
  });

  it('survives an empty or malformed response without inventing results', () => {
    expect(absorb('gtm', {}, {}).companies).toEqual([]);
    expect(absorb('xray', {}, {}).people).toEqual([]);
    expect(absorb('scoring', {}, {}).lead).toEqual({});
  });
});

// A 200 that failed at its job. GTM once returned exactly this — a well-formed
// response with the wrong keys — and the run reported "0 companies proposed"
// rather than a broken step, which is why the fault went unnoticed.
describe('a step that succeeded at HTTP but failed at its job', () => {
  it('reports a search that stopped early with nothing found', () => {
    const problem = responseProblem('gtm', { final: { companies: [] }, error: 'max_rounds_reached' });
    expect(problem).toContain('did not complete');
    expect(problem).toContain('max_rounds_reached');
  });

  it('does not fault a search that genuinely found nothing', () => {
    expect(responseProblem('gtm', { final: { companies: [] }, error: null })).toBe('');
  });

  it('does not fault a partial list — the companies found are still usable', () => {
    const response = { final: { companies: ['Northgate Nordics'] }, error: 'max_rounds_reached' };
    expect(responseProblem('gtm', response)).toBe('');
    expect(absorb('gtm', response, {}).companies).toHaveLength(1);
  });

  it('says nothing about steps that have no response contract to check', () => {
    expect(responseProblem('xray', { error: 'anything' })).toBe('');
  });
});

describe('dropping stale state', () => {
  it('forgets the picked company and its people when GTM is re-run', () => {
    const carry: Carry = {
      companies: [{ name: 'Vantage Exchange', why: '' }],
      company: 'Vantage Exchange',
      people: [{ full_name: 'Ada Lovelace' }],
    };
    const rerun = absorb('gtm', { final: { companies: ['Northgate Nordics'] } }, carry);

    // Otherwise the run would show people found for a company no longer on screen.
    expect(rerun.company).toBeUndefined();
    expect(rerun.people).toBeUndefined();
  });

  it('forgets people when a different company is picked', () => {
    const carry: Carry = { company: 'Vantage Exchange', people: [{ full_name: 'Ada Lovelace' }] };
    expect(pickCompany('Northgate Nordics', carry).people).toBeUndefined();
  });

  it('keeps people when the same company is picked again', () => {
    const carry: Carry = { company: 'Vantage Exchange', people: [{ full_name: 'Ada Lovelace' }] };
    expect(pickCompany('Vantage Exchange', carry)).toBe(carry);
  });
});

describe('walking a path', () => {
  it('opens with exactly one active step and nothing done', () => {
    const steps = walk(websiteLead, {});
    // Research needs no precondition — it takes a typed company — so it is
    // runnable from the start rather than waiting on the steps above it.
    expect(steps.map((s) => s.state))
      .toEqual(['active', 'waiting', 'waiting', 'waiting', 'waiting', 'waiting']);
  });

  it('advances the active step once the previous one has run', () => {
    const carry = absorb('scoring', { final: SCORED }, {});
    const steps = walk(websiteLead, carry);
    expect(steps.map((s) => s.state))
      .toEqual(['done', 'active', 'waiting', 'waiting', 'waiting', 'waiting']);
  });

  it('walks the inbound path, which has no step before Research', () => {
    // This path was entirely unwalkable until Research and Composer were built —
    // it reported "0 of 2 built" and nothing on it could be clicked.
    const steps = walk(inbound, {});
    expect(steps.map((s) => s.state)).toEqual(['active', 'waiting', 'waiting', 'waiting']);
    expect(stopsAt(inbound)).toBeUndefined();
  });

  it('offers a pick only once GTM has proposed something', () => {
    expect(walk(icp, {})[0].offersPick).toBe(false);

    const proposed = absorb('gtm', { final: { companies: ['Northgate Nordics'] } }, {});
    expect(walk(icp, proposed)[0].offersPick).toBe(true);
  });

  it('holds X-ray waiting, with a reason, until a company is picked', () => {
    const proposed = absorb('gtm', { final: { companies: ['Northgate Nordics'] } }, {});
    const xray = walk(icp, proposed)[1];

    expect(xray.state).toBe('waiting');
    expect(xray.waiting).toMatch(/company/i);
  });

  it('counts progress over the steps that can actually run', () => {
    expect(progress(websiteLead, {})).toEqual({ done: 0, runnable: 6 });
    expect(progress(websiteLead, absorb('scoring', { final: SCORED }, {}))).toEqual({ done: 1, runnable: 6 });
    expect(progress(inbound, {})).toEqual({ done: 0, runnable: 4 });
  });

  it('no longer stops any path short', () => {
    // Every step of all three paths is built. When the next agent lands unbuilt,
    // `stopsAt` is what will name it again.
    expect(stopsAt(websiteLead)).toBeUndefined();
    expect(stopsAt(icp)).toBeUndefined();
    expect(stopsAt(inbound)).toBeUndefined();
  });

  it('counts an empty X-ray result as done, because "nobody" is an answer', () => {
    const carry: Carry = { company: 'Northgate Nordics', people: [] };
    expect(walk(websiteLead, carry)[1].state).toBe('done');
  });
});

describe('summaries', () => {
  it('states the grade and the company a scored step produced', () => {
    const carry = absorb('scoring', { final: SCORED }, {});
    expect(summarise('scoring', carry)).toBe('Northgate Nordics · grade A · 82');
  });

  it('says so when a lead could not be identified', () => {
    const carry = absorb('scoring', { final: { lead_grade: 'D', lead_score: 12 } }, {});
    expect(summarise('scoring', carry)).toBe('Unidentified company · grade D · 12');
  });

  it('reports the pick alongside the proposal count', () => {
    const proposed = absorb('gtm', { final: { companies: ['Northgate Nordics', 'Vantage Exchange'] } }, {});
    expect(summarise('gtm', proposed)).toBe('2 companies proposed');
    expect(summarise('gtm', pickCompany('Vantage Exchange', proposed))).toBe('2 companies proposed · Vantage Exchange picked');
  });

  it('counts people found, singular and plural', () => {
    expect(summarise('xray', { company: 'Northgate', people: [{}] })).toBe('Northgate · 1 person found');
    expect(summarise('xray', { company: 'Northgate', people: [{}, {}] })).toBe('Northgate · 2 people found');
  });
});

describe('what is written down', () => {
  it('strips revealed emails and phone numbers before a run is stored', () => {
    // Those were paid for and are personal data. Browser storage is the wrong
    // home for them; a saved shortlist is the right one.
    const carry: Carry = {
      company: 'Northgate Nordics',
      people: [
        { full_name: 'Ada Lovelace', job_title: 'Head of Infrastructure', _email: 'ada@northgate.com', _phone: '+46 8 000 000' },
      ],
    };

    const stored = storableCarry(carry);
    const written = JSON.stringify(stored);

    expect(stored.people![0]).toEqual({ full_name: 'Ada Lovelace', job_title: 'Head of Infrastructure' });
    expect(written).not.toContain('ada@northgate.com');
    expect(written).not.toContain('+46 8 000 000');
  });

  it('does not mutate the run it was asked to store', () => {
    const carry: Carry = { people: [{ full_name: 'Ada Lovelace', _email: 'ada@northgate.com' }] };
    storableCarry(carry);
    expect(carry.people![0]._email).toBe('ada@northgate.com');
  });

  it('keeps the rest of the run intact', () => {
    const carry: Carry = { lead: SCORED, company: 'Northgate Nordics', companies: [{ name: 'Vantage Exchange', why: '' }] };
    expect(storableCarry(carry)).toEqual({ ...carry, people: undefined });
  });
});

describe('runnability', () => {
  it('is false for a built agent with no contract', () => {
    const steps = walk(icp, {}).map((s) => s.agent);
    const analysis = agentBySlug('call-analysis')!;

    expect(analysis.built).toBe(true);
    expect(isRunnable(analysis)).toBe(false);
    expect(isRunnable({ ...analysis, built: false })).toBe(false);
  });

  it('refuses to build a request for a step it cannot run', () => {
    expect(() => requestFor('call-analysis', { company: 'Northgate' })).toThrow(/call-analysis/);
  });
});

/** A brief as `/research/brief` returns one. */
const BRIEF = {
  subject: { company: 'Northgate Nordics', person: 'Lena Ohlsson' },
  company: { what_they_do: 'Operates the Stockholm exchange.' },
  timing: { why_now: 'Migrating matching engines in 2027.' },
  angle: { fit: 'Open Time Server' },
  person: { name: 'Lena Ohlsson' },
  sources: [{ claim: 'tender', url: 'https://example.com' }],
};

const PICKED = { full_name: 'Lena Ohlsson', linkedin_url: 'https://linkedin.com/in/lena', _email: 'lena@northgate.com', _phone: '+46 8 555' };

describe('the handoff to Research', () => {
  it('carries the scored verdict, so research starts from why they are warm', () => {
    const carry = absorb('scoring', { final: SCORED }, {});
    const { url, body } = requestFor('research', carry);

    expect(url).toBe('/api/sales/research/brief');
    expect(body.company).toBe('Northgate Nordics');
    expect(body.lead).toEqual(SCORED);
  });

  it('carries the picked person, not just their name', () => {
    const carry = pickPerson(PICKED, { company: 'Northgate Nordics' });
    expect(requestFor('research', carry).body.person).toEqual(PICKED);
  });

  it('takes a typed company when nothing upstream supplied one', () => {
    // This is what makes the inbound path startable at all.
    const { body } = requestFor('research', {}, { company: '  Ashford Capital  ' });
    expect(body.company).toBe('Ashford Capital');
    expect(body.lead).toBeNull();
  });

  it('prefers the typed company over the carried one', () => {
    const { body } = requestFor('research', { company: 'Northgate' }, { company: 'Ashford Capital' });
    expect(body.company).toBe('Ashford Capital');
  });

  it('asks for a company when it has none from either source', () => {
    expect(inputProblem('research', {}, {})).toMatch(/name the company/i);
    expect(inputProblem('research', { company: 'Ashford Capital' }, {})).toBe('');
    expect(inputProblem('research', {}, { company: 'Northgate' })).toBe('');
  });
});

describe('the handoff to Composer', () => {
  it('hands over the whole brief, because the touches are grounded in it', () => {
    const carry = absorb('research', BRIEF, {});
    const { url, body } = requestFor('composer', carry);

    expect(url).toBe('/api/sales/composer/compose');
    expect(body.brief).toEqual(BRIEF);
  });

  it('writes email alone unless more channels are chosen', () => {
    expect(requestFor('composer', { brief: BRIEF }).body.channels).toEqual(['email']);
    expect(requestFor('composer', { brief: BRIEF }, { channels: ['email', 'call'] }).body.channels)
      .toEqual(['email', 'call']);
  });

  it('takes its mix from the plan, or Campaign selection computed one nobody used', () => {
    const carry = { brief: BRIEF, campaign: PLAN };
    expect(requestFor('composer', carry).body.channels).toEqual(['linkedin', 'email', 'call']);
  });

  it('still lets an explicit choice on the step override the plan', () => {
    const carry = { brief: BRIEF, campaign: PLAN };
    expect(requestFor('composer', carry, { channels: ['email'] }).body.channels).toEqual(['email']);
  });

  it('will not run before there is a brief to write from', () => {
    expect(canRun('composer', {})).toBe(false);
    expect(canRun('composer', { brief: BRIEF })).toBe(true);
    expect(walk(inbound, {})[1].waiting).toMatch(/brief/i);
  });

  it('refuses an empty channel mix rather than composing nothing', () => {
    expect(inputProblem('composer', { channels: [] })).toMatch(/channel/i);
  });
});

describe('stale state after the new steps', () => {
  it('drops the brief, the recall and the touches when a different person is picked', () => {
    const carry = { company: 'Northgate', person: PICKED, brief: BRIEF, intel: INTEL, drafts: { email: {} } };
    const repicked = pickPerson({ full_name: 'Erik Berg' }, carry);

    expect(repicked.brief).toBeUndefined();
    expect(repicked.intel).toBeUndefined();
    expect(repicked.drafts).toBeUndefined();
  });

  it('keeps the brief when the same person is picked again', () => {
    const carry = { person: PICKED, brief: BRIEF };
    expect(pickPerson({ ...PICKED }, carry)).toBe(carry);
  });

  it('drops the touches when the brief is re-run', () => {
    const carry = absorb('research', BRIEF, { drafts: { email: { subject: 'old' } } });
    expect(carry.drafts).toBeUndefined();
  });

  it('drops the person, brief and touches when X-ray is searched again', () => {
    const carry = absorb('xray', { results: [] }, {
      person: PICKED, brief: BRIEF, drafts: { email: {} },
    });
    expect(carry.person).toBeUndefined();
    expect(carry.brief).toBeUndefined();
    expect(carry.drafts).toBeUndefined();
  });
});

describe('what the new steps report', () => {
  it('summarises a brief by who it is about and how well sourced it is', () => {
    const carry = absorb('research', BRIEF, {});
    expect(summarise('research', carry)).toBe('Northgate Nordics · Lena Ohlsson · 1 source');
  });

  it('summarises the touches by channel, and says they await review', () => {
    const carry = absorb('composer', { touches: { email: {}, call: {} } }, {});
    expect(summarise('composer', carry)).toMatch(/email · call/);
    expect(summarise('composer', carry)).toMatch(/awaiting your review/);
  });

  it('counts an empty set of touches as not done', () => {
    // Composer is the last step of the inbound path: research → recall → plan →
    // compose. Everything before it is done, so it is the active one.
    const carry = { brief: BRIEF, intel: INTEL, campaign: PLAN, drafts: {} };
    const composer = walk(inbound, carry).at(-1)!;
    expect(composer.agent.slug).toBe('composer');
    expect(composer.state).toBe('active');
  });
});

/** An outline as `/intel/outline` returns one. */
const INTEL = {
  vertical: 'finance',
  objections: [{ objection: 'GNSS alone is enough', how_it_lands: 'Not been jammed yet.' }],
  pain_points: [{ pain: '100 µs is audited', why_it_bites: 'MiFID II.' }],
  angle: { open_with: 'the audit, not the clock', avoid: 'leading on holdover' },
  proof_points: ['Clock Quorum'],
  recall: [{ id: 'aaa1', title: 'Holdover was the objection' }],
  recall_quality: 'strong',
  considered: 400,
  indexed: 544,
  error: null,
};

describe('the handoff to Campaign intelligence', () => {
  it('takes the market from the brief rather than asking again', () => {
    // Research has already written down what the company does, so the agent infers
    // the market from it. Typing one here would let the run recall a market the
    // research does not support.
    const carry = absorb('research', BRIEF, {});
    const { url, body } = requestFor('campaign-intelligence', carry);

    expect(url).toBe('/api/sales/intel/outline');
    expect(body.brief).toEqual(BRIEF);
    expect(body.company).toBe('Northgate Nordics');
    expect(body).not.toHaveProperty('vertical');
  });

  it('will not run before there is a brief to place the account', () => {
    expect(canRun('campaign-intelligence', {})).toBe(false);
    expect(canRun('campaign-intelligence', { brief: BRIEF })).toBe(true);
    expect(walk(inbound, {})[1].waiting).toMatch(/brief/i);
  });

  it('needs nothing typed', () => {
    expect(inputProblem('campaign-intelligence', {}, { brief: BRIEF })).toBe('');
  });

  it('counts an outline that recalled nothing as done', () => {
    // "This market has no history" is a real answer, and re-running will not
    // change it — so the step must not sit active waiting to be tried again.
    const carry = absorb('campaign-intelligence', { vertical: 'broadcast', recall: [], error: 'no_recall' }, { brief: BRIEF });
    expect(walk(inbound, carry)[1].state).toBe('done');
  });

  it('summarises what it recalled and how much came back', () => {
    const carry = absorb('campaign-intelligence', INTEL, { brief: BRIEF });
    expect(summarise('campaign-intelligence', carry)).toBe('finance · 1 call recalled · 1 objection');
  });

  it('says so plainly when it recalled nothing', () => {
    const carry = absorb('campaign-intelligence', { vertical: 'broadcast', recall: [] }, {});
    expect(summarise('campaign-intelligence', carry)).toBe('broadcast · nothing recalled');
  });
});

/** A plan as `/campaign/select` returns one. */
const PLAN = {
  archetype: 'abm_account_push',
  channels: ['linkedin', 'email', 'call'],
  touch_count: 4,
  cadence: '4 weeks, relationship-first',
  touch_structure: ['week1_connect', 'week2_followup_email', 'week3_value_add', 'week4_soft_ask'],
  requires_identification: false,
  rationale: 'vertical fit → outbound, run as ABM',
  inputs: { signal_type: 'vertical_fit', signal_strength: 'cold', has_named_contact: true },
  assumed: [],
  error: null,
};

describe('the handoff to Campaign selection', () => {
  it('carries the whole verdict, because the plan is computed from it', () => {
    const carry = absorb('scoring', { final: SCORED }, {});
    const { url, body } = requestFor('campaign-selection', carry);

    expect(url).toBe('/api/sales/campaign/select');
    expect(body.lead).toEqual({ ...SCORED });
  });

  it('counts a person as named only once one has been picked', () => {
    // Found is not picked: X-ray returning twelve people does not mean the
    // campaign has somebody to write to.
    const found = absorb('xray', { results: [PICKED] }, {});
    expect(requestFor('campaign-selection', found).body.has_named_contact).toBe(false);

    const picked = pickPerson(PICKED, found);
    expect(requestFor('campaign-selection', picked).body.has_named_contact).toBe(true);
  });

  it('runs with nothing at all, because the rules always yield a plan', () => {
    // The ABM default is the right answer for "nothing has happened yet".
    expect(canRun('campaign-selection', {})).toBe(true);
    expect(inputProblem('campaign-selection', {}, {})).toBe('');
    expect(requestFor('campaign-selection', {}).body.lead).toBeNull();
  });

  it('is not done until a plan with a sequence is in the carry', () => {
    expect(isDone('campaign-selection', {})).toBe(false);
    expect(isDone('campaign-selection', { campaign: {} })).toBe(false);
    expect(isDone('campaign-selection', { campaign: PLAN })).toBe(true);
  });

  it('summarises the plan by archetype, touches and mix', () => {
    const carry = absorb('campaign-selection', PLAN, {});
    expect(summarise('campaign-selection', carry))
      .toBe('ABM · 4 touches · linkedin · email · call');
  });

  it('says when the campaign has to find somebody first', () => {
    const carry = absorb('campaign-selection', { ...PLAN, requires_identification: true }, {});
    expect(summarise('campaign-selection', carry)).toMatch(/identify first/);
  });
});

describe('stale plans', () => {
  it('drops the plan when the lead is re-scored', () => {
    // A new grade changes the touch count, so the plan on screen is for a lead
    // that no longer exists.
    const carry = absorb('scoring', { final: SCORED }, { campaign: PLAN });
    expect(carry.campaign).toBeUndefined();
  });

  it('drops the plan when X-ray is searched again', () => {
    // The picked person goes, and whether one is named is a plan input.
    const carry = absorb('xray', { results: [] }, { campaign: PLAN, person: PICKED });
    expect(carry.campaign).toBeUndefined();
  });

  it('keeps the plan when the brief is re-run', () => {
    // The plan derives from the verdict, not the brief — dropping it here would
    // make the person redo a step whose inputs did not change.
    const carry = absorb('research', BRIEF, { campaign: PLAN });
    expect(carry.campaign).toEqual(PLAN);
    expect(carry.drafts).toBeUndefined();
  });

  it('drops the touches when the plan is recomputed', () => {
    const carry = absorb('campaign-selection', PLAN, { drafts: { email: { subject: 'old' } } });
    expect(carry.drafts).toBeUndefined();
  });
});

describe('what Composer does with the outline', () => {
  it('carries the outline when the run has one — canon\'s second grounding', () => {
    const carry = absorb('campaign-intelligence', INTEL, absorb('research', BRIEF, {}));
    expect(requestFor('composer', carry).body.intel).toEqual(INTEL);
  });

  it('sends none when the recall was skipped, rather than an empty claim', () => {
    const carry = absorb('research', BRIEF, {});
    expect(requestFor('composer', carry).body.intel).toBeNull();
  });

  it('drops the touches when the outline is re-run', () => {
    const carry = absorb('campaign-intelligence', INTEL, {
      brief: BRIEF, drafts: { email: { subject: 'old' } },
    });
    expect(carry.drafts).toBeUndefined();
  });

  it('drops the outline as well as the touches when the brief is re-run', () => {
    // A new brief can place the account in a different market entirely, which
    // would make the recall about somewhere else.
    const carry = absorb('research', BRIEF, { intel: INTEL, drafts: { email: {} } });
    expect(carry.intel).toBeUndefined();
    expect(carry.drafts).toBeUndefined();
  });

  it('drops the outline when X-ray is searched again', () => {
    const carry = absorb('xray', { results: [] }, { brief: BRIEF, intel: INTEL });
    expect(carry.brief).toBeUndefined();
    expect(carry.intel).toBeUndefined();
  });
});

describe('paid-for contact details and the picked person', () => {
  it('strips the revealed fields from the picked person too', () => {
    // Selecting someone must not put back into storage the email that stripping
    // `people` had just taken out.
    const stored = storableCarry({ company: 'Northgate', person: PICKED, people: [PICKED] });

    expect(stored.person).not.toHaveProperty('_email');
    expect(stored.person).not.toHaveProperty('_phone');
    expect(stored.person!.full_name).toBe('Lena Ohlsson');
    expect(JSON.stringify(stored)).not.toContain('lena@northgate.com');
  });

  it('leaves a run with nobody picked alone', () => {
    expect(storableCarry({ company: 'Northgate' }).person).toBeUndefined();
  });
});
