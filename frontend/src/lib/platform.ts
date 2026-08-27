// The platform's shape, declared once.
//
// The old structure mirrored how the code grew — a dashboard listing modules,
// then `calls`, `lead`, `high-intent` as parallel sections. This describes the
// **job** instead: two ways into the work, one place to ask, and a section for
// learning.
//
// The rail, the /work landing and the path runner all read from here, so the
// platform cannot advertise a surface that does not exist or forget one that
// does.

import type { IconName } from './icons';

/** Which agent grant a surface needs. Mirrors the slugs in `agents/users.json`. */
export type Grant = 'lead' | 'calls';

/**
 * Where an agent sits in the arc of the work. The launcher groups by this, so a
 * new agent cannot be added without deciding where it belongs — a flat list of
 * eleven answers "what exists" but never "which do I need first".
 *
 * The split is canon's own: the front half acquires and prepares, the back half
 * engages and converts, and what a call teaches goes back into the vault.
 */
export type Stage = 'find' | 'engage' | 'learn';

/** The sections of the launcher, in the order the work happens. */
export const STAGES: { id: Stage; label: string; blurb: string }[] = [
  { id: 'find', label: 'Find & qualify', blurb: 'Who to approach, and whether they are worth it.' },
  { id: 'engage', label: 'Engage', blurb: 'What to say, and the note that follows.' },
  { id: 'learn', label: 'Learn', blurb: 'What the conversation taught, kept.' },
];

export interface Agent {
  slug: string;
  name: string;
  /** Which section of the launcher it appears under. */
  stage: Stage;
  /** What it does, in one line, from the user's side. */
  does: string;
  href: string;
  grant: Grant;
  /** False until the agent is built — surfaces say so rather than 404. */
  built: boolean;
  /** The tool name Owl knows it by, when it is registered. */
  tool?: string;
  /** Its icon, by name in `lib/icons.ts`. The rail will not draw a row without one. */
  icon: IconName;
}

export const AGENTS: Agent[] = [
  {
    slug: 'scoring',
    stage: 'find',
    icon: 'scoring',
    name: 'Lead scoring',
    does: 'How warm a lead is, and the behaviour that made it so.',
    href: '/work/agents/scoring',
    grant: 'lead',
    built: true,
    tool: 'score_lead',
  },
  {
    slug: 'gtm',
    stage: 'find',
    icon: 'gtm',
    name: 'GTM',
    does: 'Which companies to approach — by vertical, or as look-alikes.',
    href: '/work/agents/gtm',
    grant: 'lead',
    built: true,
    tool: 'find_target_companies',
  },
  {
    slug: 'xray',
    stage: 'find',
    icon: 'xray',
    name: 'X-ray',
    does: 'The named people inside an account, or showing a buying signal.',
    href: '/work/agents/xray',
    grant: 'lead',
    built: true,
    tool: 'xray',
  },
  {
    slug: 'signals',
    stage: 'find',
    icon: 'signals',
    name: 'Signals',
    does: 'What changed at the accounts you watch — funding, build-outs, timing work.',
    href: '/work/agents/signals',
    grant: 'lead',
    built: true,
    tool: 'check_signals',
  },
  {
    slug: 'research',
    stage: 'find',
    icon: 'research',
    name: 'Research',
    does: 'A deep brief on the company and the decision-maker.',
    href: '/work/agents/research',
    grant: 'lead',
    built: true,
    tool: 'research_account',
  },
  {
    slug: 'campaign-intelligence',
    stage: 'engage',
    icon: 'campaign-intelligence',
    name: 'Campaign intelligence',
    does: 'What this market already told us — objections, pain, the angle.',
    href: '/work/agents/campaign-intelligence',
    grant: 'lead',
    built: true,
    tool: 'recall_market',
  },
  {
    slug: 'campaign-selection',
    stage: 'engage',
    icon: 'campaign-selection',
    name: 'Campaign selection',
    does: 'The shape of the campaign — archetype, channels, the sequence.',
    href: '/work/agents/campaign-selection',
    grant: 'lead',
    built: true,
    tool: 'select_campaign',
  },
  {
    slug: 'composer',
    stage: 'engage',
    icon: 'composer',
    name: 'Composer',
    does: 'The outreach touches — email, LinkedIn, call — in Owl’s voice.',
    href: '/work/agents/composer',
    grant: 'lead',
    built: true,
    tool: 'compose_outreach',
  },
  {
    slug: 'call-analysis',
    stage: 'learn',
    icon: 'call-analysis',
    name: 'Call analysis',
    does: 'A pasted transcript read into signals, objections and next steps.',
    href: '/work/agents/call-analysis',
    grant: 'calls',
    built: true,
    tool: 'analyse_call',
  },
  {
    slug: 'recap',
    stage: 'engage',
    icon: 'recap',
    name: 'Recap',
    does: 'The follow-up email after a call — what was covered, what happens next.',
    href: '/work/agents/recap',
    grant: 'calls',
    built: true,
    tool: 'draft_recap',
  },
  {
    // Declared here because it produces something for other people to read, which
    // is work. It used to sit inside the quiz page, sharing nothing with it but a
    // URL prefix — so the rail could not show it and nobody knew it existed.
    slug: 'newsletter-quiz',
    stage: 'learn',
    icon: 'newsletter-quiz',
    name: 'Newsletter quiz',
    does: 'Educational questions for the newsletter, ready to paste.',
    href: '/work/agents/newsletter-quiz',
    grant: 'calls',
    built: true,
  },
];

export const agentBySlug = (slug: string): Agent | undefined =>
  AGENTS.find((a) => a.slug === slug);

/**
 * A path is a sequence over those same agents — not a fourth kind of thing.
 * Each is entered from a channel: how the lead arrived, or how you decided to
 * go after it. That channel is what makes the sequence different, not the
 * agents in it.
 */
export interface Path {
  slug: string;
  name: string;
  /** How work enters this path. */
  channel: string;
  /** When to take it. */
  when: string;
  /** Agent slugs, in order. */
  steps: string[];
  grant: Grant;
  icon: IconName;
}

export const PATHS: Path[] = [
  {
    slug: 'inbound',
    name: 'Inbound',
    channel: 'A form, a download, or a message',
    when: 'They came to us and said who they are.',
    steps: ['research', 'campaign-intelligence', 'campaign-selection', 'composer'],
    grant: 'lead',
    icon: 'inbound',
  },
  {
    slug: 'website-lead',
    name: 'Website lead',
    channel: 'An anonymous company visit',
    when: 'We know the company but nobody has identified themselves.',
    steps: ['scoring', 'xray', 'research', 'campaign-intelligence', 'campaign-selection', 'composer'],
    grant: 'lead',
    icon: 'website-lead',
  },
  {
    slug: 'icp',
    name: 'ICP · vertical',
    channel: 'A vertical, or a company to look like',
    when: 'Nothing has happened yet — we are going after them.',
    steps: ['gtm', 'xray', 'research', 'campaign-intelligence', 'campaign-selection', 'composer'],
    grant: 'lead',
    icon: 'icp-vertical',
  },
];

export const pathBySlug = (slug: string): Path | undefined =>
  PATHS.find((p) => p.slug === slug);

/** The agents a path walks, resolved and in order. */
export const stepsOf = (path: Path): Agent[] =>
  path.steps.map(agentBySlug).filter((a): a is Agent => Boolean(a));

/** How far a path can currently be walked before it meets an unbuilt agent. */
export function pathReadiness(path: Path): { built: number; total: number } {
  const steps = stepsOf(path);
  const firstGap = steps.findIndex((s) => !s.built);
  return { built: firstGap === -1 ? steps.length : firstGap, total: steps.length };
}

export interface LearnSurface {
  name: string;
  does: string;
  href: string;
  grant: Grant;
  built: boolean;
  icon: IconName;
}

/**
 * Learn is *library · knowledge · practice*, not the old `calls` pages regrouped.
 *
 * "Enablement" used to mean a glossary page, a hard-coded product list and the
 * file-upload screen sitting together. Those were three different jobs: two of
 * them were copies of what the vault already holds, and the third configures what
 * *Owl* reads, which is an admin concern and now lives at `/admin`. Knowledge is
 * the vault itself, read through `/api/wiki`.
 */
export const LEARN: LearnSurface[] = [
  {
    name: 'Knowledge',
    icon: 'knowledge',
    does: 'Everything the company knows — terms, products, industries.',
    href: '/learn/knowledge',
    grant: 'calls',
    built: true,
  },
  {
    name: 'Call library',
    icon: 'library',
    does: 'Every analysed call, searchable.',
    href: '/learn/library',
    grant: 'calls',
    built: true,
  },
  {
    name: 'Practice',
    icon: 'practice',
    does: 'Test what you know against the calls the team has had.',
    href: '/learn/practice',
    grant: 'calls',
    built: true,
  },
];

/** One step in the trail shown in the sheet header. */
export interface Crumb {
  href: string;
  label: string;
}

/** A Learn surface's own name, so a renamed surface cannot leave a stale label. */
const learnName = (href: string): string =>
  LEARN.find((surface) => surface.href === href)?.name ?? href;

const HOME: Crumb = { href: '/home', label: 'Home' };

/**
 * The surfaces *above* a page, nearest last. The page itself is not included —
 * the shell appends it, because it already knows the page's title.
 *
 * Every page has a trail and every trail starts at Home, so there is a way back
 * from everywhere. `/home` is the only page with nothing above it.
 *
 * Written out rather than derived from URL segments, because the shape of the
 * URLs and the shape of the product disagree in both directions: `/changelog` is
 * one segment deep but sits under Home, and `/work/integrations` is two deep
 * while sitting directly under it. A segment-counting rule would be wrong in
 * both places and would look principled doing it.
 *
 * Hierarchy rather than history, because the agent pages hand off *laterally* to
 * each other in six places (signals → xray, composer → research, and so on).
 * Stepping "back" from Composer would otherwise land on Campaign Selection,
 * which is not above it.
 */
export function ancestorsOf(pathname: string): Crumb[] {
  const path = pathname.replace(/\/+$/, '') || '/';

  if (path === '/home') return [];

  if (path.startsWith('/work/agents/')) return [HOME, { href: '/work/agents', label: 'Agents' }];
  if (path === '/learn/knowledge/page') {
    return [HOME, { href: '/learn/knowledge', label: learnName('/learn/knowledge') }];
  }
  if (path === '/learn/library/call') {
    return [HOME, { href: '/learn/library', label: learnName('/learn/library') }];
  }
  if (path === '/admin/calls/call') return [HOME, { href: '/admin', label: 'Admin' }];
  if (path === '/work/integrations/callback') {
    return [HOME, { href: '/work/integrations', label: 'Integrations' }];
  }

  return [HOME];
}
