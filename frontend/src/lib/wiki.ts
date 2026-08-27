// Reading the vault, on the client.
//
// `/api/wiki` returns the company's knowledge as nodes and typed blocks. This
// module holds the rules the two Learn surfaces share: where a page lives, how
// results are grouped and filtered, how a block maps to an element, and how a
// link that resolved to nothing degrades.
//
// Everything here is pure. No DOM, no fetch, no storage — the pages own all
// three, so these rules can be reasoned about and tested on their own, the same
// arrangement `paths.ts` uses.

/** A knowledge page, as `/api/wiki/index` lists it. */
export interface WikiNode {
  /** `type/name`, e.g. `product/open-time-appliance`. */
  slug: string;
  title: string;
  type: string;
  pillar: string;
  tags: string[];
  aliases: string[];
  tagline: string;
  /** The Cadence username the vault recorded as contributing this page, if any. */
  contributed_by?: string;
  /**
   * The viewer contributed this page.
   *
   * Presentation, never permission. The corpus is readable by everyone either
   * way; this only lets a contributor find their own work inside it, which
   * matters most right after importing a body of knowledge.
   */
  mine?: boolean;
}

/** One run of text inside a block. A `link` with no `slug` never became a link. */
export interface Span {
  kind: 'text' | 'strong' | 'em' | 'link';
  text: string;
  target?: string;
  slug?: string | null;
}

export type Block =
  | { kind: 'heading'; level: number; spans: Span[] }
  | { kind: 'para'; spans: Span[] }
  | { kind: 'list'; items: Span[][] }
  | { kind: 'table'; head: Span[][]; rows: Span[][][] };

/**
 * One call a page's knowledge came from.
 *
 * `status` rather than a boolean because the vault is shared and the call
 * library is not: a page a colleague contributed points at a call you cannot
 * open, and calling that "deleted" would be untrue of most of the corpus.
 *
 *  - `open`       your own call — link it
 *  - `restricted` a colleague's, still here — name it, do not link it
 *  - `missing`    gone: deleted, or trimmed by the store's session cap
 *
 * `title` is resolved server-side: the live name where the call survives, the
 * name captured at the time where it does not. It is never empty.
 */
export interface WikiSource {
  call_id: string;
  title: string;
  contributed_by: string;
  /** ISO-8601, or '' when the vault recorded no date. */
  captured_at: string;
  status: 'open' | 'restricted' | 'missing';
}

export interface WikiPage extends WikiNode {
  blocks: Block[];
  links: { target: string; slug: string | null }[];
  backlinks: WikiNode[];
  unresolved: string[];
  /** Empty for company-tier pages: they are the company's own truth, not a citation. */
  sources: WikiSource[];
}

export interface SearchHit {
  node: WikiNode;
  rank: number;
  matched_on: 'title' | 'alias' | 'tag' | 'body';
}

// ---------------------------------------------------------------------------
// Vocabulary
//
// The order is the order a reader wants: what a term means, then what we sell,
// then who we sell it to, then the supporting paper.
// ---------------------------------------------------------------------------

export const TYPE_ORDER = [
  'glossary', 'entity', 'product', 'solution', 'industry', 'reference', 'research', 'datasheet',
] as const;

const TYPE_LABELS: Record<string, string> = {
  glossary: 'Terms',
  entity: 'Concepts',
  product: 'Hardware',
  solution: 'Software & services',
  industry: 'Industries',
  reference: 'Reference',
  research: 'Research',
  datasheet: 'Datasheets',
};

/** Where a page's knowledge came from — shown so a reader can weigh it. */
const PILLAR_LABELS: Record<string, string> = {
  company: 'company truth',
  dynamic: 'grown from calls',
  added: 'added & approved',
};

const MATCH_LABELS: Record<string, string> = {
  title: 'title',
  alias: 'also called',
  tag: 'tagged',
  body: 'mentioned',
};

export const typeLabel = (type: string): string => TYPE_LABELS[type] ?? type;
export const pillarLabel = (pillar: string): string => PILLAR_LABELS[pillar] ?? pillar;
export const matchLabel = (matchedOn: string): string => MATCH_LABELS[matchedOn] ?? matchedOn;

// ---------------------------------------------------------------------------
// Addressing
// ---------------------------------------------------------------------------

/**
 * Where a page lives.
 *
 * A query parameter rather than a path segment because the site builds static:
 * a route like `/learn/knowledge/[...slug]` would need all 176 slugs enumerable
 * at build time, and the vault is runtime data that changes without a rebuild.
 * The slug contains a slash, so it is encoded — `call?id=` and `xray?company=`
 * already address their subjects the same way.
 */
export function hrefFor(slug: string): string {
  return `/learn/knowledge/page?slug=${encodeURIComponent(slug)}`;
}

/**
 * The mark that states where a page's knowledge came from.
 *
 * `--canon` is gold and the design system reserves gold for canon alone, which is
 * exactly what company truth is. An approved correction has passed the review
 * gate, so it reads as locked; a page grown from calls is neither confirmed nor
 * in doubt, so it stays neutral rather than borrowing a signal colour it has not
 * earned.
 */
export function pillarMark(pillar: string): string {
  const modifier = pillar === 'company' ? 'canon' : pillar === 'added' ? 'locked' : 'idle';
  return `ds-mark ds-mark--${modifier}`;
}

/**
 * Where a source opens, or null when it cannot be opened.
 *
 * Null means the chip renders as a span rather than an anchor. Offering a link
 * into a call the library no longer holds — or one that is not yours to read —
 * is the same defect `spanHref` exists to prevent, one surface along.
 */
export function sourceHref(source: WikiSource): string | null {
  if (source.status !== 'open' || !source.call_id) return null;
  return `/learn/library/call?id=${encodeURIComponent(source.call_id)}`;
}

/**
 * What a source is called. The subject alone — never the date or the state.
 *
 * Split from `sourceMeta` because `.ds-source__name` ellipsises at 18rem and a
 * call title routinely exceeds it. Kept in one string, the suffix is the first
 * thing lost — including "no longer stored", which is the part a reader most
 * needs. The name truncates; the meta does not.
 */
export function sourceTitle(source: WikiSource): string {
  return source.title.trim() || 'A call';
}

/**
 * What is worth knowing about a source besides its name: when it was captured,
 * whose it is when it is not yours, and whether it is still there at all.
 *
 * Empty when there is nothing to add — an undated call of your own says only
 * its name rather than trailing a bare separator.
 */
export function sourceMeta(source: WikiSource): string {
  const parts: string[] = [];

  const when = sourceDate(source.captured_at);
  if (when) parts.push(when);

  if (source.status === 'restricted' && source.contributed_by) {
    parts.push(source.contributed_by);
  }
  if (source.status === 'missing') parts.push('no longer stored');

  return parts.join(' · ');
}

/**
 * The whole source as one line, for a tooltip — where nothing truncates and the
 * reader has asked for the detail.
 */
export function sourceName(source: WikiSource): string {
  const meta = sourceMeta(source);
  return meta ? `${sourceTitle(source)} · ${meta}` : sourceTitle(source);
}

/** `14 May` from an ISO date. Empty for '' and for anything unparseable. */
function sourceDate(at: string): string {
  if (!at) return '';
  const when = new Date(at);
  if (Number.isNaN(when.getTime())) return '';
  return when.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
}

/**
 * The href a span should link to, or null when it must render as plain text.
 *
 * The corpus links to pages that do not exist. Emitting an anchor for those is
 * the defect this replaces — a reader clicking it learned nothing and lost their
 * place. Unresolved means text.
 */
export function spanHref(span: Span): string | null {
  if (span.kind !== 'link' || !span.slug) return null;
  return hrefFor(span.slug);
}

// ---------------------------------------------------------------------------
// Grouping and filtering
// ---------------------------------------------------------------------------

export interface TypeGroup {
  type: string;
  label: string;
  nodes: WikiNode[];
}

/**
 * Results grouped by type, in reading order. Empty groups are dropped — a
 * heading over nothing tells a reader the search failed when it did not.
 */
export function groupByType(nodes: WikiNode[]): TypeGroup[] {
  const groups: TypeGroup[] = [];
  const known = new Set<string>(TYPE_ORDER);

  for (const type of TYPE_ORDER) {
    const matching = nodes.filter((n) => n.type === type);
    if (matching.length) groups.push({ type, label: typeLabel(type), nodes: matching });
  }
  // A type the frontend has not heard of still gets shown rather than vanishing.
  for (const node of nodes) {
    if (known.has(node.type)) continue;
    const existing = groups.find((g) => g.type === node.type);
    if (existing) existing.nodes.push(node);
    else groups.push({ type: node.type, label: typeLabel(node.type), nodes: [node] });
  }
  return groups;
}

/** Filter to the chosen types. No choice means no filter, not no results. */
export function filterByTypes(nodes: WikiNode[], active: readonly string[]): WikiNode[] {
  if (!active.length) return nodes;
  const wanted = new Set(active);
  return nodes.filter((n) => wanted.has(n.type));
}

/** The types actually present, in reading order — the filter offers only these. */
export function typesPresent(nodes: WikiNode[]): string[] {
  const present = new Set(nodes.map((n) => n.type));
  const ordered = TYPE_ORDER.filter((t) => present.has(t)) as string[];
  const extra = [...present].filter((t) => !ordered.includes(t)).sort();
  return [...ordered, ...extra];
}

// ---------------------------------------------------------------------------
// Results
//
// What a browse or a search actually shows. The rules live here rather than in
// the screen because each has an edge worth pinning: relevance that must not be
// re-sorted, a match reason that has to agree with the backend's normalisation,
// and a summary that is allowed to truncate only where a tooltip can recover it.
// ---------------------------------------------------------------------------

/**
 * Hits in the order the backend ranked them, best first.
 *
 * `/api/wiki/search` already sorts by rank. This restates the contract on the
 * client so a change of transport cannot silently scramble relevance — the
 * screen used to re-group hits by type, which put the best match for a query
 * below four sections of worse ones. `sort` is stable, so the backend's
 * title tie-break survives, and the input is copied rather than sorted in place.
 */
export function orderByRank(hits: readonly SearchHit[]): SearchHit[] {
  return [...hits].sort((a, b) => a.rank - b.rank);
}

/**
 * The query as the backend sees it.
 *
 * Mirrors `" ".join(str(query).lower().split())` in `agents/shared/wiki.py`
 * (`search`, the `needle` line). The two have to agree: this decides which
 * alias we claim matched, and that one decided whether it matched at all.
 */
function needle(query: string): string {
  return query.toLowerCase().split(/\s+/).filter(Boolean).join(' ');
}

/**
 * Why a hit is here, naming the alias or the tag where there is one to name.
 *
 * `matched_on` said a page matched "also called" or "tagged" and stopped there,
 * leaving a reader to guess which of six aliases did it.
 *
 * **An exact match wins over a prefix**, because the backend prefers it too: a
 * tag matches only exactly (rank 5) and an alias exactly at rank 1 before any
 * prefix at rank 3. Taking the first array entry that merely starts with the
 * query would name `ptp-grandmaster` for a page the backend matched on the tag
 * `ptp` — a stated reason that is false, which is worse than no reason at all.
 * When nothing can be identified, the plain label is still true.
 */
export function matchReason(hit: SearchHit, query: string): string {
  const label = matchLabel(hit.matched_on);
  const wanted = needle(query);
  if (!wanted) return label;

  const candidates = hit.matched_on === 'alias' ? hit.node.aliases
    : hit.matched_on === 'tag' ? hit.node.tags
    : [];

  const exact = candidates.find((candidate) => candidate.toLowerCase() === wanted);
  const found = exact ?? candidates.find((candidate) => candidate.toLowerCase().startsWith(wanted));

  return found ? `${label} “${found}”` : label;
}

/**
 * What else a page is called and how it is filed — the quiet second line.
 *
 * `limit` caps each list for the row; omit it for the tooltip, where nothing is
 * cut. Aliases and tags are separated by a middot because they are two different
 * facts, and the members of each by commas because each is one.
 */
export function rowMeta(node: WikiNode, limit?: number): string {
  const parts: string[] = [];
  const clip = (values: string[]): string => {
    if (limit === undefined || values.length <= limit) return values.join(', ');
    // "+2" rather than an ellipsis: a reader can tell how much is missing, and
    // the untruncated string is on the tooltip.
    return `${values.slice(0, limit).join(', ')} +${values.length - limit}`;
  };

  if (node.aliases.length) parts.push(`Also called ${clip(node.aliases)}`);
  if (node.tags.length) parts.push(`Tagged ${clip(node.tags)}`);
  return parts.join(' · ');
}

/**
 * The line under a result.
 *
 * The index carries no body, so this is the tagline or nothing. `summarise`
 * takes an optional page and falls back to its opening prose; calling it here
 * only made that fallback look like a working feature on a surface that can
 * never supply the page.
 */
export function rowSummary(node: WikiNode): string {
  return node.tagline;
}

/**
 * The provenance worth stating on a row, or null when it is the corpus default.
 *
 * Most of the vault is company truth, and a mark firing on nine rows in ten says
 * nothing while spending gold, which the system reserves. The exceptions — grown
 * from a call, corrected and approved — are what a reader weighing a page needs.
 * The whole proportion belongs on the standing card, where a proportion belongs.
 */
/** The mark for a page the viewer contributed, or null when it is not theirs. */
export function rowMine(node: WikiNode): { label: string; mark: string } | null {
  return node.mine ? { label: 'yours', mark: 'ds-mark ds-mark--canon' } : null;
}

export function rowPillar(node: WikiNode): { label: string; mark: string } | null {
  if (!node.pillar || node.pillar === 'company') return null;
  return { label: pillarLabel(node.pillar), mark: pillarMark(node.pillar) };
}

export interface Shelf extends TypeGroup {
  /** The rows to render — the face, or everything once the reader has opened it. */
  shown: WikiNode[];
  /** How many the face is holding back. Zero when there is nothing behind it. */
  hidden: number;
}

/**
 * Browse groups, each showing a face rather than its whole depth.
 *
 * Eight sections totalling the whole vault arrive as a wall nobody reads, and
 * the reader wanted the shape of the corpus, not row 41 of Terms. Each shelf
 * shows its first few; the count in its head already states how deep it goes,
 * so nothing is concealed by showing less.
 */
export function shelves(
  nodes: WikiNode[], face: number, opened: ReadonlySet<string>,
): Shelf[] {
  return groupByType(nodes).map((group) => {
    const open = opened.has(group.type);
    const shown = open ? group.nodes : group.nodes.slice(0, face);
    return { ...group, shown, hidden: group.nodes.length - shown.length };
  });
}

export interface PillarShare {
  pillar: string;
  label: string;
  count: number;
}

export interface VaultShape {
  total: number;
  kinds: number;
  pillars: PillarShare[];
}

/** The pillars in the order a reader weighs them: canon first, then what grew. */
const PILLAR_ORDER = ['company', 'dynamic', 'added'] as const;

/**
 * What the vault holds, derived from the index rather than fetched.
 *
 * The split by pillar is the one fact the browse surface could never tell you:
 * how much of what you are reading is the company's own truth, and how much grew
 * out of a call. A pillar this build has not heard of is counted and shown last,
 * never dropped — the same rule `groupByType` follows for an unknown type.
 */
export function vaultShape(nodes: readonly WikiNode[]): VaultShape {
  const counts = new Map<string, number>();
  for (const node of nodes) {
    const pillar = node.pillar || 'company';
    counts.set(pillar, (counts.get(pillar) ?? 0) + 1);
  }

  const known = PILLAR_ORDER.filter((pillar) => counts.has(pillar)) as string[];
  const extra = [...counts.keys()].filter((pillar) => !known.includes(pillar)).sort();

  return {
    total: nodes.length,
    kinds: new Set(nodes.map((node) => node.type)).size,
    pillars: [...known, ...extra].map((pillar) => ({
      pillar,
      label: pillarLabel(pillar),
      count: counts.get(pillar) ?? 0,
    })),
  };
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

/**
 * The element a block becomes.
 *
 * Body headings start at `h2`: the page's own title is the `h1`, and a second one
 * would compete with it for both readers and screen readers. A level-1 heading in
 * the body is therefore demoted rather than honoured.
 */
export function headingTag(level: number): 'h2' | 'h3' | 'h4' {
  if (level <= 2) return 'h2';
  if (level === 3) return 'h3';
  return 'h4';
}

/** Flatten a run of spans to plain text — for titles, summaries and aria labels. */
export function plainText(spans: Span[]): string {
  return spans.map((s) => s.text).join('');
}

/** The one-line summary under a result. Falls back to the opening prose. */
export function summarise(node: WikiNode, page?: WikiPage | null): string {
  if (node.tagline) return node.tagline;
  const para = page?.blocks.find((b) => b.kind === 'para');
  return para && 'spans' in para ? plainText(para.spans) : '';
}

/**
 * What to ask Owl about a page. Owl already reads this vault, so the question
 * names the page and asks for what a wiki page cannot give: how to use it.
 */
export function owlPrompt(node: WikiNode): string {
  return `Tell me more about "${node.title}" in the context of selling Acme — `
    + 'how it comes up on calls, and how to position it.';
}
