// How a path walks its agents.
//
// `platform.ts` declares what exists — the agents, whether each is built, the
// three paths and their step order. This module adds only what *running* one
// needs: what a step requires before it can go, what its result contributes,
// and how that result becomes the next step's input.
//
// Everything here is pure. No DOM, no fetch, no storage. The runner page owns
// all three, so this logic can be reasoned about — and tested — on its own.

import { agentBySlug, stepsOf, type Agent, type Path } from './platform';

/** A company as GTM proposes it. The agent returns strings or objects. */
export interface Company {
  name: string;
  why: string;
}

/** A person as X-ray discovers them. Fields vary by discovery source. */
export type Person = Record<string, any>;

/**
 * What a run accumulates as it walks. Each step reads what it needs from here
 * and folds its own result back in.
 */
export interface Carry {
  /** Lead scoring's whole verdict — not just the company. See `requestFor`. */
  lead?: Record<string, any>;
  /** The company being worked: scored, or picked from GTM's proposals. */
  company?: string;
  /** GTM's proposals, awaiting a pick. */
  companies?: Company[];
  /** X-ray's discovery result. */
  people?: Person[];
  /** The decision-maker picked from `people`, for Research to profile. */
  person?: Person;
  /** Research's combined company + decision-maker brief. */
  brief?: Record<string, any>;
  /** Campaign Intelligence's outline of what this market has already told us. */
  intel?: Record<string, any>;
  /** The campaign plan — archetype, channel mix, touch structure. */
  campaign?: Record<string, any>;
  /** Composer's touches, keyed by channel. */
  drafts?: Record<string, any>;
}

/** What a step must already have before it can run. */
type Needs = 'nothing' | 'company' | 'brief';

/** What a step's result contributes to the carry. */
type Gives = 'lead' | 'companies' | 'people' | 'brief' | 'intel' | 'campaign' | 'drafts';

interface StepContract {
  needs: Needs;
  gives: Gives;
  /**
   * Set when this step's result is a *set* and the next step needs one of them.
   * The runner renders a selection on this step's result rather than inserting
   * a fourth kind of step — picking is not work an agent does.
   */
  pick?: 'company' | 'person';
}

/**
 * The contract per agent, keyed by the slug `platform.ts` already declares.
 * Only built agents appear: an unbuilt step is a stated stop, not a runnable
 * thing with a contract, and inventing one would let the runner pretend.
 */
const CONTRACTS: Record<string, StepContract> = {
  scoring: { needs: 'nothing', gives: 'lead' },
  gtm: { needs: 'nothing', gives: 'companies', pick: 'company' },
  // X-ray offers a pick because Research profiles a *selected* decision-maker.
  xray: { needs: 'company', gives: 'people', pick: 'person' },
  // `nothing`, deliberately: the inbound path has no step before this one, so the
  // company is typed. Downstream it arrives prefilled from the carry instead.
  research: { needs: 'nothing', gives: 'brief' },
  // Needs the brief because that is what tells it which market this account is in.
  // Run on its own page it takes the market directly; inside a path, asking the
  // person to restate something Research just wrote down would be asking twice.
  'campaign-intelligence': { needs: 'brief', gives: 'intel' },
  // `nothing`, because the rules always yield a plan: with no scored lead they
  // compute the ABM default, which is the right answer for "we are going after
  // them and nothing has happened yet". The plan says what it assumed.
  'campaign-selection': { needs: 'nothing', gives: 'campaign' },
  composer: { needs: 'brief', gives: 'drafts' },
};

/** Whether a step can be run at all, as opposed to being a stated stop. */
export const isRunnable = (agent: Agent): boolean => agent.built && agent.slug in CONTRACTS;

/** The agent a path stops at — its first step that cannot be run. */
export const stopsAt = (path: Path): Agent | undefined => stepsOf(path).find((a) => !isRunnable(a));

/** Whether this step's precondition is met by what the run has so far. */
export function canRun(slug: string, carry: Carry): boolean {
  const contract = CONTRACTS[slug];
  if (!contract) return false;
  if (contract.needs === 'company') return Boolean(carry.company);
  if (contract.needs === 'brief') return Boolean(carry.brief);
  return true;
}

/** What a step is waiting for, in words, when `canRun` is false. */
export function waitingFor(slug: string): string {
  switch (CONTRACTS[slug]?.needs) {
    case 'company': return 'Waiting for a company from the step above.';
    case 'brief': return 'Waiting for the research brief above.';
    default: return '';
  }
}

// ── The request ─────────────────────────────────────────────────────────────

/** What the runner collects from the person for a step that takes input. */
export interface StepInput {
  /** Lead scoring: the pasted behaviour. */
  text?: string;
  /** GTM: the vertical or ICP, a seed company to look like, and constraints. */
  vertical?: string;
  seedCompany?: string;
  notes?: string;
  /** Research: the company, when nothing upstream supplied one. */
  company?: string;
  /** Composer: which touches to write. */
  channels?: string[];
}

export interface StepRequest {
  url: string;
  body: Record<string, any>;
}

/**
 * The call a step makes. Every endpoint here already exists and is the same one
 * the agent's own page calls — a path is a wrapper, not a second implementation.
 *
 * The X-ray case shows what the carry buys. `/xray/search` accepts a
 * `signal_analysis` object, and the prompt builder threads its `product_fit`,
 * `signal_strength`, `role` and `signal_type` into the discovery prompt. So when
 * a scored lead is in the carry we hand over the *whole verdict*, and the search
 * is grounded in why the lead is warm.
 *
 * The standalone X-ray page reaches the same grounding through `lib/handoff`,
 * which carries a scored verdict between two separate documents. A path keeps
 * its carry in memory; the difference is transport, not capability.
 */
export function requestFor(slug: string, carry: Carry, input: StepInput = {}): StepRequest {
  switch (slug) {
    case 'scoring':
      return {
        url: '/api/sales/leads/analyze',
        body: { text: (input.text ?? '').trim() },
      };

    case 'gtm':
      return {
        url: '/api/sales/gtm/identify',
        body: {
          vertical: (input.vertical ?? '').trim(),
          seed_company: (input.seedCompany ?? '').trim(),
          notes: (input.notes ?? '').trim(),
        },
      };

    case 'xray': {
      const body: Record<string, any> = { company: carry.company ?? '' };
      if (carry.lead) body.signal_analysis = carry.lead;
      return { url: '/api/sales/xray/search', body };
    }

    case 'research':
      return {
        url: '/api/sales/research/brief',
        // The whole scored verdict again, for the same reason X-ray gets it: the
        // research then starts from why this company is warm, rather than
        // rediscovering it from a name.
        body: {
          company: (input.company ?? carry.company ?? '').trim(),
          person: carry.person ?? null,
          lead: carry.lead ?? null,
          notes: (input.notes ?? '').trim(),
        },
      };

    case 'campaign-intelligence':
      return {
        url: '/api/sales/intel/outline',
        body: {
          // No vertical is sent: the brief carries what the company does, and the
          // agent infers the market from it. Typing one here would let the run
          // recall a market the research does not support.
          company: (carry.brief?.subject ?? {}).company ?? carry.company ?? '',
          brief: carry.brief ?? {},
          notes: (input.notes ?? '').trim(),
        },
      };

    case 'campaign-selection':
      return {
        url: '/api/sales/campaign/select',
        body: {
          // The whole verdict again: the archetype turns on the signal type and
          // the touch count on the strength, both of which scoring already read.
          lead: carry.lead ?? null,
          // A person is only "named" once one has been picked, not merely found.
          has_named_contact: Boolean(carry.person),
        },
      };

    case 'composer':
      return {
        url: '/api/sales/composer/compose',
        body: {
          brief: carry.brief ?? {},
          // Canon's second grounding, when the run has it. Absent, the touches are
          // written from the brief alone — worse, not impossible.
          intel: carry.intel ?? null,
          // The plan's mix wins over the default, because otherwise Campaign
          // selection would be a step that computed a channel mix nobody used.
          // An explicit choice on the Composer step still overrides it.
          channels: input.channels ?? carry.campaign?.channels ?? ['email'],
          notes: (input.notes ?? '').trim(),
          // The address the email touch is drafted to, when X-ray revealed one
          // for the person picked. It has to travel explicitly: the brief's
          // `person` is Research's own profile of them, not the row selected on
          // the X-ray step, so an enriched address does not survive inside it.
          // Without this the recipient is retyped by hand at the last step of a
          // run that already paid to discover it.
          recipient: carry.person?._email ?? '',
        },
      };

    default:
      throw new Error(`No request is defined for the ${slug} step.`);
  }
}

/** Why a step cannot be sent yet, or empty when it can. */
export function inputProblem(slug: string, input: StepInput = {}, carry: Carry = {}): string {
  if (slug === 'scoring' && !(input.text ?? '').trim()) {
    return 'Paste what the visitor did first.';
  }
  if (slug === 'gtm' && !(input.vertical ?? '').trim() && !(input.seedCompany ?? '').trim()) {
    return 'Give a vertical to target, or a company to find look-alikes of.';
  }
  // Typed or carried — either will do, which is what lets the inbound path start here.
  if (slug === 'research' && !(input.company ?? '').trim() && !carry.company) {
    return 'Name the company to research.';
  }
  if (slug === 'composer' && !(input.channels ?? ['email']).length) {
    return 'Choose at least one channel to write.';
  }
  return '';
}

/**
 * The problem with a step's *response*, or '' when the response is usable.
 *
 * The sibling of `inputProblem`, on the way back. A step can succeed at HTTP and
 * still fail at its job: a grounded search that stopped early returns 200 with an
 * `error` set and nothing found. Folding that into the carry renders it as
 * "0 companies proposed" — a wrong answer stated confidently, which is exactly the
 * failure this check exists to stop.
 */
export function responseProblem(slug: string, response: any): string {
  switch (slug) {
    case 'gtm': {
      const companies = ((response?.final ?? {}).companies ?? []) as unknown[];
      if (companies.length) return '';
      return response?.error ? `The company search did not complete (${response.error}).` : '';
    }
    default:
      return '';
  }
}

// ── The result ──────────────────────────────────────────────────────────────

/** GTM returns either bare names or objects; normalise to one shape. */
function toCompany(raw: any): Company {
  if (typeof raw === 'string') return { name: raw, why: '' };
  return { name: raw?.name ?? '—', why: raw?.rationale ?? raw?.why ?? '' };
}

/**
 * Fold a step's response into the carry, returning a new one.
 *
 * Lead scoring gives both its whole verdict *and* the company, because the
 * company is what unblocks X-ray while the verdict is what sharpens it.
 */
export function absorb(slug: string, response: any, carry: Carry): Carry {
  switch (slug) {
    case 'scoring': {
      const lead = response?.final ?? {};
      // A re-score can change the grade, and the plan's archetype and touch count
      // are computed from it — so the plan is stale even though nothing else is.
      return {
        ...carry,
        lead,
        company: (lead.company ?? '').trim() || undefined,
        campaign: undefined,
      };
    }

    case 'gtm': {
      const companies = ((response?.final ?? {}).companies ?? []).map(toCompany);
      // A fresh proposal set invalidates any earlier pick — otherwise the run
      // would carry a company that is no longer on screen.
      return { ...carry, companies, company: undefined, people: undefined };
    }

    case 'xray':
      // A fresh search invalidates the person picked from the previous one, and
      // everything downstream of them.
      return {
        ...carry,
        people: response?.results ?? [],
        person: undefined,
        brief: undefined,
        intel: undefined,
        // Dropping the picked person changes whether there is a named contact,
        // which is one of the plan's three inputs.
        campaign: undefined,
        drafts: undefined,
      };

    case 'research':
      // Re-researching invalidates everything written from the previous brief —
      // the market recall as much as the touches, since a new brief can place the
      // account in a different market entirely.
      return { ...carry, brief: response ?? {}, intel: undefined, drafts: undefined };

    case 'campaign-intelligence':
      // A fresh outline invalidates touches written against the previous one.
      return { ...carry, intel: response ?? {}, drafts: undefined };

    case 'campaign-selection':
      // A different plan means a different channel mix, so touches written to the
      // previous one are for a campaign that is no longer being run.
      return { ...carry, campaign: response ?? {}, drafts: undefined };

    case 'composer':
      return { ...carry, drafts: response?.touches ?? {} };

    default:
      return carry;
  }
}

/** Record a pick made on a previous step's result set. */
export function pickCompany(name: string, carry: Carry): Carry {
  // Picking a different company drops people found for the previous one.
  return name === carry.company ? carry : { ...carry, company: name, people: undefined };
}

/** Record the decision-maker picked from X-ray's result. */
export function pickPerson(person: Person, carry: Carry): Carry {
  const same = carry.person && personKey(carry.person) === personKey(person);
  // Picking someone else drops the brief written about the previous person, and
  // everything written from it — the market recall included, since the recall is
  // aimed at the account that brief described. The plan survives: going from
  // nobody to somebody is what changes it, and either way somebody is now picked.
  return same ? carry : { ...carry, person, brief: undefined, intel: undefined, drafts: undefined };
}

/** How a person is identified for comparison — LinkedIn URL, else name. */
function personKey(person: Person): string {
  return String(person?.linkedin_url || person?.full_name || person?.name || '').toLowerCase();
}

/** Whether a step has produced its result yet. */
export function isDone(slug: string, carry: Carry): boolean {
  switch (CONTRACTS[slug]?.gives) {
    case 'lead': return Boolean(carry.lead);
    case 'companies': return Boolean(carry.companies?.length);
    case 'people': return Array.isArray(carry.people);
    case 'brief': return Boolean(carry.brief);
    // An outline that recalled nothing is still a result — the market genuinely has
    // no history here, and re-running will not change that.
    case 'intel': return Boolean(carry.intel);
    case 'campaign': return Boolean(carry.campaign?.touch_structure?.length);
    case 'drafts': return Boolean(carry.drafts && Object.keys(carry.drafts).length);
    default: return false;
  }
}

/** The one line a completed step collapses to. */
export function summarise(slug: string, carry: Carry): string {
  switch (slug) {
    case 'scoring': {
      const lead = carry.lead ?? {};
      const grade = lead.lead_grade ?? '—';
      const score = lead.lead_score ?? '—';
      const company = lead.company || 'Unidentified company';
      return `${company} · grade ${grade} · ${score}`;
    }

    case 'gtm': {
      const count = carry.companies?.length ?? 0;
      const proposed = `${count} ${count === 1 ? 'company' : 'companies'} proposed`;
      return carry.company ? `${proposed} · ${carry.company} picked` : proposed;
    }

    case 'xray': {
      const count = carry.people?.length ?? 0;
      const found = `${count} ${count === 1 ? 'person' : 'people'} found`;
      return carry.company ? `${carry.company} · ${found}` : found;
    }

    case 'research': {
      const brief = carry.brief ?? {};
      const company = (brief.subject ?? {}).company || carry.company || 'Company';
      const person = (brief.subject ?? {}).person;
      const sourced = (brief.sources ?? []).length;
      const cited = `${sourced} source${sourced === 1 ? '' : 's'}`;
      return person ? `${company} · ${person} · ${cited}` : `${company} · ${cited}`;
    }

    case 'campaign-intelligence': {
      const intel = carry.intel ?? {};
      const market = intel.vertical || 'market';
      const read = (intel.recall ?? []).length;
      if (!read) return `${market} · nothing recalled`;
      const objections = (intel.objections ?? []).length;
      return `${market} · ${read} call${read === 1 ? '' : 's'} recalled · ${objections} objection${objections === 1 ? '' : 's'}`;
    }

    case 'campaign-selection': {
      const plan = carry.campaign ?? {};
      const name = plan.archetype === 'warm_inbound_reengagement' ? 'warm re-engagement' : 'ABM';
      const touches = plan.touch_count ?? (plan.touch_structure ?? []).length;
      const mix = (plan.channels ?? []).join(' · ');
      const identify = plan.requires_identification ? ' · identify first' : '';
      return `${name} · ${touches} touches · ${mix}${identify}`;
    }

    case 'composer': {
      const written = Object.keys(carry.drafts ?? {});
      return written.length
        ? `${written.join(' · ')} — awaiting your review`
        : 'nothing written yet';
    }

    default:
      return '';
  }
}

// ── The walk ────────────────────────────────────────────────────────────────

export type StepState = 'done' | 'active' | 'waiting' | 'unbuilt';

export interface WalkStep {
  agent: Agent;
  state: StepState;
  /** Set on a `waiting` step: what it is waiting for. */
  waiting: string;
  /** Whether a pick is offered on this step's result. */
  offersPick: boolean;
}

/**
 * The state of every step, given what the run has so far.
 *
 * Exactly one step is `active` — the first one that can run and has not. Steps
 * after an unbuilt one are also unbuilt: a path stops where its agents stop, and
 * showing a later step as merely "waiting" would imply it becomes reachable.
 */
export function walk(path: Path, carry: Carry): WalkStep[] {
  const steps = stepsOf(path);
  let activeTaken = false;
  let stopped = false;

  return steps.map((agent) => {
    const contract = CONTRACTS[agent.slug];

    if (stopped || !isRunnable(agent)) {
      stopped = true;
      return { agent, state: 'unbuilt' as StepState, waiting: '', offersPick: false };
    }

    const offersPick = Boolean(contract?.pick) && isDone(agent.slug, carry);

    if (isDone(agent.slug, carry)) {
      return { agent, state: 'done' as StepState, waiting: '', offersPick };
    }
    if (!canRun(agent.slug, carry)) {
      return { agent, state: 'waiting' as StepState, waiting: waitingFor(agent.slug), offersPick };
    }
    if (activeTaken) {
      return { agent, state: 'waiting' as StepState, waiting: '', offersPick };
    }
    activeTaken = true;
    return { agent, state: 'active' as StepState, waiting: '', offersPick };
  });
}

/** How far a run has actually got, for the progress meter. */
export function progress(path: Path, carry: Carry): { done: number; runnable: number } {
  const steps = walk(path, carry);
  return {
    done: steps.filter((s) => s.state === 'done').length,
    runnable: steps.filter((s) => s.state !== 'unbuilt').length,
  };
}

// ── Keeping a run across a reload ───────────────────────────────────────────

const storageKey = (pathSlug: string) => `cadence.run.${pathSlug}`;

/**
 * Contact details are stripped before a run is stored.
 *
 * A revealed email or phone number was paid for and is personal data; browser
 * storage is the wrong home for it. The right home already exists — a saved
 * shortlist, server-side and per-user. So a restored run keeps who was found and
 * forgets what was revealed about them.
 */
function withoutRevealed(people: Person[] | undefined): Person[] | undefined {
  return people?.map(({ _email, _phone, ...rest }) => rest);
}

export function storableCarry(carry: Carry): Carry {
  // The picked person is one of `people` and carries the same revealed fields, so
  // it is stripped by the same rule — otherwise picking someone would put the
  // email back into storage that selecting them had just taken out.
  const [person] = withoutRevealed(carry.person ? [carry.person] : []) ?? [];
  return { ...carry, people: withoutRevealed(carry.people), person };
}

export function saveRun(pathSlug: string, carry: Carry): void {
  try {
    sessionStorage.setItem(storageKey(pathSlug), JSON.stringify(storableCarry(carry)));
  } catch {
    // A full or blocked store costs the reload-safety, nothing more. The run
    // itself must not fail because it could not be written down.
  }
}

export function loadRun(pathSlug: string): Carry {
  try {
    const stored = sessionStorage.getItem(storageKey(pathSlug));
    return stored ? (JSON.parse(stored) as Carry) : {};
  } catch {
    return {};
  }
}

export function clearRun(pathSlug: string): void {
  try {
    sessionStorage.removeItem(storageKey(pathSlug));
  } catch {
    // Nothing to do: the run is being abandoned anyway.
  }
}

/** Resolve a path's steps to agents. Re-exported so the runner has one import. */
export { stepsOf, agentBySlug };
