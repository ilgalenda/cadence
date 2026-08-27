// The wiki's client-side rules, tested where they are easiest to get wrong.
//
// `wiki.ts` is pure so these can be checked here rather than by clicking. What
// matters most:
//
//   * an unresolved `[[link]]` never becomes an anchor — emitting one is the
//     defect this whole surface replaces;
//   * a body heading never becomes a second `h1` competing with the page title;
//   * grouping shows every result, including a type this build has not heard of,
//     because a filter that silently swallows pages teaches distrust;
//   * no filter selected means everything, not nothing;
//   * a source that cannot be opened still names what the page rests on, and
//     still never becomes an anchor — one recorded source in six points at a
//     call the library no longer holds.

import { describe, expect, it } from 'vitest';

import {
  filterByTypes, groupByType, headingTag, hrefFor, matchLabel, matchReason, orderByRank,
  owlPrompt, pillarLabel, pillarMark, plainText, rowMeta, rowPillar, rowSummary, shelves,
  sourceHref, sourceMeta, sourceName, sourceTitle, spanHref, summarise, typeLabel,
  typesPresent, vaultShape,
  type Block, type SearchHit, type Span, type WikiNode, type WikiPage, type WikiSource,
} from './wiki';

const node = (over: Partial<WikiNode> = {}): WikiNode => ({
  slug: 'glossary/holdover',
  title: 'Holdover',
  type: 'glossary',
  pillar: 'company',
  tags: ['holdover'],
  aliases: [],
  tagline: '',
  ...over,
});

describe('addressing', () => {
  it('encodes the slug, because it contains a slash and the site builds static', () => {
    expect(hrefFor('product/open-time-appliance'))
      .toBe('/learn/knowledge/page?slug=product%2Fopen-time-appliance');
  });

  it('survives a slug with characters that would break a URL', () => {
    // Vault stems come from filenames and have carried stranger things.
    expect(hrefFor('glossary/ptp+squared')).toBe('/learn/knowledge/page?slug=glossary%2Fptp%2Bsquared');
  });

  it('links a resolved span', () => {
    const span: Span = { kind: 'link', text: 'Holdover', target: 'Holdover', slug: 'glossary/holdover' };
    expect(spanHref(span)).toBe('/learn/knowledge/page?slug=glossary%2Fholdover');
  });

  it('refuses to link an unresolved span', () => {
    // The corpus links to pages that do not exist. A reader clicking one of
    // those learned nothing and lost their place — so it renders as text.
    const dead: Span = { kind: 'link', text: 'Nothing Here', target: 'Nothing Here', slug: null };
    expect(spanHref(dead)).toBeNull();
    expect(spanHref({ ...dead, slug: undefined })).toBeNull();
  });

  it('never links a span that is not a link', () => {
    expect(spanHref({ kind: 'strong', text: 'bold' })).toBeNull();
    expect(spanHref({ kind: 'text', text: 'plain', slug: 'glossary/holdover' } as Span)).toBeNull();
  });
});

describe('headings', () => {
  it('starts body headings at h2, because the page title is the h1', () => {
    expect(headingTag(2)).toBe('h2');
    expect(headingTag(3)).toBe('h3');
    expect(headingTag(4)).toBe('h4');
  });

  it('demotes a stray body h1 rather than honouring it', () => {
    expect(headingTag(1)).toBe('h2');
  });

  it('does not run past h4', () => {
    expect(headingTag(5)).toBe('h4');
    expect(headingTag(6)).toBe('h4');
  });
});

describe('grouping', () => {
  const nodes = [
    node({ slug: 'datasheet/ota', type: 'datasheet', title: 'OTA datasheet' }),
    node({ slug: 'glossary/ptp', title: 'PTP' }),
    node({ slug: 'product/ota', type: 'product', title: 'Open Time Appliance' }),
  ];

  it('orders groups for reading, not by the order results arrived', () => {
    expect(groupByType(nodes).map((g) => g.type)).toEqual(['glossary', 'product', 'datasheet']);
  });

  it('drops empty groups', () => {
    const groups = groupByType([node()]);
    expect(groups).toHaveLength(1);
    expect(groups[0].label).toBe('Terms');
  });

  it('still shows a type this build has not heard of', () => {
    // The backend can add a type before the frontend knows its label. Hiding
    // those pages would be a silent loss of knowledge.
    const groups = groupByType([...nodes, node({ slug: 'playbook/x', type: 'playbook', title: 'A playbook' })]);
    const playbook = groups.find((g) => g.type === 'playbook');
    expect(playbook?.nodes.map((n) => n.title)).toEqual(['A playbook']);
    expect(playbook?.label).toBe('playbook');
  });

  it('keeps every node when grouping', () => {
    const grouped = groupByType(nodes).flatMap((g) => g.nodes);
    expect(grouped).toHaveLength(nodes.length);
  });
});

describe('filtering', () => {
  const nodes = [
    node({ slug: 'glossary/a', type: 'glossary' }),
    node({ slug: 'product/b', type: 'product' }),
  ];

  it('treats no selection as no filter', () => {
    expect(filterByTypes(nodes, [])).toHaveLength(2);
  });

  it('keeps only the chosen types', () => {
    expect(filterByTypes(nodes, ['product']).map((n) => n.slug)).toEqual(['product/b']);
  });

  it('offers only the types actually present, in reading order', () => {
    expect(typesPresent([...nodes].reverse())).toEqual(['glossary', 'product']);
  });

  it('offers an unknown type last rather than dropping it', () => {
    expect(typesPresent([...nodes, node({ type: 'playbook' })])).toEqual(
      ['glossary', 'product', 'playbook'],
    );
  });
});

describe('provenance marks', () => {
  it('gives company truth the canon mark — the only gold in the system', () => {
    expect(pillarMark('company')).toBe('ds-mark ds-mark--canon');
  });

  it('reads an approved correction as locked, because it passed review', () => {
    expect(pillarMark('added')).toBe('ds-mark ds-mark--locked');
  });

  it('leaves a page grown from calls neutral rather than borrowing a signal', () => {
    expect(pillarMark('dynamic')).toBe('ds-mark ds-mark--idle');
    expect(pillarMark('something-new')).toBe('ds-mark ds-mark--idle');
  });
});

describe('vocabulary', () => {
  it('names provenance in words a reader can weigh', () => {
    expect(pillarLabel('company')).toBe('company truth');
    expect(pillarLabel('dynamic')).toBe('grown from calls');
    expect(pillarLabel('added')).toBe('added & approved');
  });

  it('says why a result matched', () => {
    expect(matchLabel('alias')).toBe('also called');
    expect(matchLabel('body')).toBe('mentioned');
  });

  it('falls back to the raw value rather than showing nothing', () => {
    expect(typeLabel('playbook')).toBe('playbook');
    expect(pillarLabel('future-pillar')).toBe('future-pillar');
    expect(matchLabel('semantic')).toBe('semantic');
  });
});

describe('summaries', () => {
  const page = (blocks: Block[]): WikiPage => ({
    ...node(), blocks, links: [], backlinks: [], unresolved: [], sources: [],
  });

  it('prefers the tagline', () => {
    expect(summarise(node({ tagline: 'A grandmaster.' }), page([]))).toBe('A grandmaster.');
  });

  it('falls back to the opening prose when there is no tagline', () => {
    const withProse = page([
      { kind: 'heading', level: 2, spans: [{ kind: 'text', text: 'Highlights' }] },
      { kind: 'para', spans: [{ kind: 'text', text: 'How long a clock keeps time.' }] },
    ]);
    expect(summarise(node(), withProse)).toBe('How long a clock keeps time.');
  });

  it('returns empty rather than throwing when there is no page yet', () => {
    expect(summarise(node(), null)).toBe('');
    expect(summarise(node())).toBe('');
  });

  it('flattens spans including links, so a summary is never markup', () => {
    const mixed: Span[] = [
      { kind: 'text', text: 'Uses ' },
      { kind: 'link', text: 'PTP', target: 'PTP', slug: 'glossary/ptp' },
      { kind: 'text', text: ' end to end.' },
    ];
    expect(plainText(mixed)).toBe('Uses PTP end to end.');
  });
});

describe('asking Owl', () => {
  it('names the page, because Owl reads the same vault', () => {
    expect(owlPrompt(node({ title: 'Clock Quorum' }))).toContain('"Clock Quorum"');
  });
});


describe('sources', () => {
  const source = (over: Partial<WikiSource> = {}): WikiSource => ({
    call_id: 'call-1',
    title: 'Datacentre operator — holdover',
    contributed_by: 'sam',
    captured_at: '2026-05-14T10:30:00+00:00',
    status: 'open',
    ...over,
  });

  it('links a call that is yours and still here', () => {
    expect(sourceHref(source())).toBe('/learn/library/call?id=call-1');
  });

  it('never links a call that is gone — the anchor-to-nothing defect', () => {
    expect(sourceHref(source({ status: 'missing' }))).toBeNull();
  });

  it("never links a colleague's call, which is theirs to read", () => {
    expect(sourceHref(source({ status: 'restricted' }))).toBeNull();
  });

  it('never links a source with no id, whatever its status claims', () => {
    expect(sourceHref(source({ call_id: '' }))).toBeNull();
  });

  it('encodes an id, so a stray character cannot break the address', () => {
    expect(sourceHref(source({ call_id: 'a/b c' }))).toBe('/learn/library/call?id=a%2Fb%20c');
  });

  it('keeps the state out of the name, which is the part that truncates', () => {
    // `.ds-source__name` ellipsises at 18rem; a call title routinely exceeds it,
    // so anything a reader needs must not ride on the end of the same string.
    expect(sourceTitle(source({ status: 'missing' }))).toBe('Datacentre operator — holdover');
    expect(sourceMeta(source({ status: 'missing' }))).toContain('no longer stored');
  });

  it('dates a live source', () => {
    expect(sourceMeta(source())).toBe('14 May');
  });

  it('credits a colleague, so a restricted source explains itself', () => {
    expect(sourceMeta(source({ status: 'restricted', contributed_by: 'martin' })))
      .toBe('14 May · martin');
  });

  it('says nothing rather than trailing a separator when there is nothing to add', () => {
    expect(sourceMeta(source({ captured_at: '' }))).toBe('');
    expect(sourceName(source({ captured_at: '' }))).toBe('Datacentre operator — holdover');
  });

  it('drops an unparseable date rather than printing "Invalid Date"', () => {
    expect(sourceMeta(source({ captured_at: 'not a date' }))).not.toContain('Invalid');
  });

  it('never renders blank, even with no title at all', () => {
    expect(sourceTitle(source({ title: '   ' }))).toBe('A call');
  });

  it('joins both halves for the tooltip, where nothing is cut', () => {
    expect(sourceName(source())).toBe('Datacentre operator — holdover · 14 May');
  });
});


// ---------------------------------------------------------------------------
// Results
// ---------------------------------------------------------------------------

const page = (over: Partial<WikiNode> = {}): WikiNode => ({
  slug: 'glossary/holdover',
  title: 'Holdover',
  type: 'glossary',
  pillar: 'company',
  tags: [],
  aliases: [],
  tagline: '',
  ...over,
});

const hit = (over: Partial<SearchHit> = {}): SearchHit => ({
  node: page(),
  rank: 0,
  matched_on: 'title',
  ...over,
});

describe('relevance', () => {
  it('keeps the best match first — the defect this replaces buried it', () => {
    const ranked = orderByRank([hit({ rank: 6 }), hit({ rank: 0 }), hit({ rank: 3 })]);
    expect(ranked.map((h) => h.rank)).toEqual([0, 3, 6]);
  });

  it("is stable, so the backend's title tie-break survives", () => {
    const first = hit({ rank: 2, node: page({ title: 'Alpha' }) });
    const second = hit({ rank: 2, node: page({ title: 'Beta' }) });
    expect(orderByRank([first, second]).map((h) => h.node.title)).toEqual(['Alpha', 'Beta']);
  });

  it('never reorders the array it was given', () => {
    const hits = [hit({ rank: 5 }), hit({ rank: 1 })];
    orderByRank(hits);
    expect(hits.map((h) => h.rank)).toEqual([5, 1]);
  });
});

describe('why a hit is here', () => {
  it('names the alias that matched, not just "also called"', () => {
    const h = hit({ matched_on: 'alias', node: page({ aliases: ['Free-running', 'OTA'] }) });
    expect(matchReason(h, 'free-running')).toBe('also called “Free-running”');
  });

  it('names the tag that matched', () => {
    const h = hit({ matched_on: 'tag', node: page({ tags: ['holdover', 'ocxo'] }) });
    expect(matchReason(h, 'ocxo')).toBe('tagged “ocxo”');
  });

  it("matches the backend's normalisation — case and collapsed whitespace", () => {
    const h = hit({ matched_on: 'alias', node: page({ aliases: ['White Rabbit'] }) });
    expect(matchReason(h, '  WHITE   rabbit ')).toBe('also called “White Rabbit”');
  });

  it('prefers the exact match over one that merely starts with the query', () => {
    // The backend matches a tag exactly, so naming the longer tag that happens
    // to share a prefix would state a reason that is false.
    const h = hit({ matched_on: 'tag', node: page({ tags: ['ptp-grandmaster', 'ptp'] }) });
    expect(matchReason(h, 'ptp')).toBe('tagged “ptp”');
  });

  it('prefers the exact alias over a longer one sharing its prefix', () => {
    const h = hit({ matched_on: 'alias', node: page({ aliases: ['OTA-2', 'OTA'] }) });
    expect(matchReason(h, 'ota')).toBe('also called “OTA”');
  });

  it('accepts a prefix, because the backend ranks prefixes too', () => {
    const h = hit({ matched_on: 'alias', node: page({ aliases: ['Free-running'] }) });
    expect(matchReason(h, 'free')).toBe('also called “Free-running”');
  });

  it('falls back to the plain label when it cannot identify the culprit', () => {
    const h = hit({ matched_on: 'alias', node: page({ aliases: ['Something else'] }) });
    expect(matchReason(h, 'holdover')).toBe('also called');
  });

  it('says something rather than nothing for a title or body match', () => {
    expect(matchReason(hit({ matched_on: 'title' }), 'holdover')).toBe('title');
    expect(matchReason(hit({ matched_on: 'body' }), 'holdover')).toBe('mentioned');
  });

  it('survives an empty query rather than claiming everything matched', () => {
    expect(matchReason(hit({ matched_on: 'alias' }), '')).toBe('also called');
  });
});

describe('the quiet line', () => {
  it('names aliases and tags as two facts, not one list', () => {
    const node = page({ aliases: ['OTA'], tags: ['sync'] });
    expect(rowMeta(node)).toBe('Also called OTA · Tagged sync');
  });

  it('counts what it held back rather than truncating mid-word', () => {
    const node = page({ tags: ['a', 'b', 'c', 'd'] });
    expect(rowMeta(node, 2)).toBe('Tagged a, b +2');
  });

  it('is uncapped when no limit is given — the tooltip must not cut', () => {
    const node = page({ tags: ['a', 'b', 'c', 'd'] });
    expect(rowMeta(node)).toBe('Tagged a, b, c, d');
  });

  it('omits a half it has nothing for, never trailing a separator', () => {
    expect(rowMeta(page({ aliases: ['OTA'] }))).toBe('Also called OTA');
    expect(rowMeta(page({ tags: ['sync'] }))).toBe('Tagged sync');
  });

  it('returns empty for a page with neither', () => {
    expect(rowMeta(page())).toBe('');
  });
});

describe('row summaries', () => {
  it('uses the tagline', () => {
    expect(rowSummary(page({ tagline: 'How long a clock keeps time.' })))
      .toBe('How long a clock keeps time.');
  });

  it('returns empty rather than pretending the index carries a body', () => {
    expect(rowSummary(page())).toBe('');
  });
});

describe('provenance on a row', () => {
  it('says nothing for company truth — the corpus default', () => {
    expect(rowPillar(page({ pillar: 'company' }))).toBeNull();
  });

  it('marks a page grown from calls', () => {
    expect(rowPillar(page({ pillar: 'dynamic' }))?.label).toBe('grown from calls');
  });

  it('marks an approved correction as locked', () => {
    expect(rowPillar(page({ pillar: 'added' }))?.mark).toContain('ds-mark--locked');
  });

  it('marks a pillar this build has not heard of rather than hiding it', () => {
    expect(rowPillar(page({ pillar: 'imported' }))?.label).toBe('imported');
  });
});

describe('shelves', () => {
  const many = (count: number, type = 'glossary') =>
    Array.from({ length: count }, (_, i) => page({ type, title: `Term ${i}`, slug: `${type}/t${i}` }));

  it('shows a face, and reports what it is holding back', () => {
    const [shelf] = shelves(many(10), 6, new Set());
    expect(shelf.shown).toHaveLength(6);
    expect(shelf.hidden).toBe(4);
  });

  it('reports nothing hidden for a shelf shorter than the face', () => {
    const [shelf] = shelves(many(3), 6, new Set());
    expect(shelf.hidden).toBe(0);
  });

  it('shows everything for a shelf the reader has opened', () => {
    const [shelf] = shelves(many(10), 6, new Set(['glossary']));
    expect(shelf.shown).toHaveLength(10);
    expect(shelf.hidden).toBe(0);
  });

  it('keeps reading order and keeps every node', () => {
    const nodes = [...many(2, 'product'), ...many(2, 'glossary')];
    const built = shelves(nodes, 6, new Set());
    expect(built.map((s) => s.type)).toEqual(['glossary', 'product']);
    expect(built.reduce((sum, s) => sum + s.nodes.length, 0)).toBe(4);
  });
});

describe('what the vault holds', () => {
  it('counts the pillar split, canon first', () => {
    const shape = vaultShape([
      page({ pillar: 'dynamic' }), page({ pillar: 'company' }), page({ pillar: 'company' }),
    ]);
    expect(shape.total).toBe(3);
    expect(shape.pillars.map((p) => [p.pillar, p.count])).toEqual([['company', 2], ['dynamic', 1]]);
  });

  it('counts a pillar this build has not heard of, last', () => {
    const shape = vaultShape([page({ pillar: 'imported' }), page({ pillar: 'company' })]);
    expect(shape.pillars.map((p) => p.pillar)).toEqual(['company', 'imported']);
  });

  it('counts the kinds present, not the whole vocabulary', () => {
    expect(vaultShape([page({ type: 'glossary' }), page({ type: 'product' })]).kinds).toBe(2);
  });

  it('survives an empty corpus', () => {
    expect(vaultShape([])).toEqual({ total: 0, kinds: 0, pillars: [] });
  });
});
