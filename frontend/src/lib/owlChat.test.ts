import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  deleteAllConversations, deleteConversation, escHtml, renameConversation,
  renderInline, renderMarkdown,
} from './owlChat';

// The markdown renderer emits bare tags. `.ds-answer` styles them; the renderer
// itself carries no class names, so the design system stays the only thing that
// decides how an answer looks.

describe('escHtml', () => {
  it('escapes the four characters that could break out of markup', () => {
    expect(escHtml('<a href="x">1 & 2</a>')).toBe(
      '&lt;a href=&quot;x&quot;&gt;1 &amp; 2&lt;/a&gt;',
    );
  });
});

describe('renderInline', () => {
  it('renders code, bold, italic and bold-italic as bare tags', () => {
    expect(renderInline('`c`')).toBe('<code>c</code>');
    expect(renderInline('**b**')).toBe('<strong>b</strong>');
    expect(renderInline('*i*')).toBe('<em>i</em>');
    expect(renderInline('***bi***')).toBe('<strong><em>bi</em></strong>');
  });

  it('renders a markdown link as a safe external anchor', () => {
    expect(renderInline('[Acme](https://acme.example)')).toBe(
      '<a href="https://acme.example" target="_blank" rel="noopener noreferrer">Acme</a>',
    );
  });

  it('autolinks a bare URL without double-wrapping a markdown link', () => {
    const out = renderInline('see [x](https://a.test) and https://b.test');
    expect(out).toContain('>x</a>');
    expect(out).toContain('>https://b.test</a>');
    expect(out.match(/<a /g)).toHaveLength(2);
  });

  it('escapes markup before emphasis is applied', () => {
    expect(renderInline('<script>')).toBe('&lt;script&gt;');
  });

  // Owl's prose is model-generated over vault content and, on a grounded turn,
  // over an uploaded transcript. A planted link must not be able to carry a
  // scheme that executes.
  it('refuses a javascript: link, keeping the label as text', () => {
    const out = renderInline('[click](javascript:alert(1))');
    expect(out).not.toContain('<a ');
    expect(out).toContain('click');
  });

  it('refuses a data: link', () => {
    expect(renderInline('[x](data:text/html,<script>)')).not.toContain('<a ');
  });

  it('allows http, https and relative links', () => {
    expect(renderInline('[a](https://x.test)')).toContain('href="https://x.test"');
    expect(renderInline('[b](http://x.test)')).toContain('href="http://x.test"');
    expect(renderInline('[c](/learn/knowledge)')).toContain('href="/learn/knowledge"');
  });

  it('emits no class attribute at all', () => {
    const out = renderInline('`c` **b** *i* [l](https://a.test) https://b.test');
    expect(out).not.toContain('class=');
  });
});

describe('renderMarkdown', () => {
  it('renders headings, lists, quotes, rules and paragraphs as bare tags', () => {
    expect(renderMarkdown('# h1')).toBe('<h1>h1</h1>');
    expect(renderMarkdown('## h2')).toBe('<h2>h2</h2>');
    expect(renderMarkdown('### h3')).toBe('<h3>h3</h3>');
    expect(renderMarkdown('> q')).toBe('<blockquote>q</blockquote>');
    expect(renderMarkdown('---')).toBe('<hr>');
    expect(renderMarkdown('plain')).toBe('<p>plain</p>');
    expect(renderMarkdown('- a\n- b')).toBe('<ul><li>a</li><li>b</li></ul>');
    expect(renderMarkdown('1. a\n2. b')).toBe('<ol><li>a</li><li>b</li></ol>');
  });

  it('renders a fenced code block with its contents escaped', () => {
    expect(renderMarkdown('```\n<b>&\n```')).toBe(
      '<pre><code>&lt;b&gt;&amp;</code></pre>',
    );
  });

  it('closes an unterminated code fence rather than dropping it', () => {
    expect(renderMarkdown('```\nstill streaming')).toBe(
      '<pre><code>still streaming</code></pre>',
    );
  });

  it('renders a table with a header row split on the separator', () => {
    expect(renderMarkdown('| a | b |\n| --- | --- |\n| 1 | 2 |')).toBe(
      '<table><thead><tr><th>a</th><th>b</th></tr></thead>'
      + '<tbody><tr><td>1</td><td>2</td></tr></tbody></table>',
    );
  });

  it('keeps a data row whose first cell is a dash', () => {
    // `| - | Not supported |` is a real shape in a comparison table: the dash is
    // "no value", not a header separator. It used to be eaten as one.
    expect(renderMarkdown('| a | b |\n| --- | --- |\n| - | Not supported |')).toBe(
      '<table><thead><tr><th>a</th><th>b</th></tr></thead>'
      + '<tbody><tr><td>-</td><td>Not supported</td></tr></tbody></table>',
    );
  });

  it('still recognises real separator rows, including aligned ones', () => {
    expect(renderMarkdown('| a |\n| :-: |\n| 1 |')).toBe(
      '<table><thead><tr><th>a</th></tr></thead><tbody><tr><td>1</td></tr></tbody></table>',
    );
  });

  it('emits no class attribute anywhere, across every construct', () => {
    const out = renderMarkdown(
      '# h\n\ntext with `code` and **bold**\n\n- item\n\n1. item\n\n> quote\n\n---\n\n'
      + '| a |\n| --- |\n| 1 |\n\n```\ncode\n```',
    );
    expect(out).not.toContain('class=');
  });
});

// The page passes these through a `guard()` that reports failure as a falsy
// return, so resolving `undefined` on success made a completed delete look like
// a failed one: the row stayed, no toast fired, and only a refresh revealed
// that the server had done the work. The contract is that success is truthy.

describe('conversation mutations', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  const respond = (ok: boolean) => {
    const fetchMock = vi.fn().mockResolvedValue({ ok });
    vi.stubGlobal('fetch', fetchMock);
    return fetchMock;
  };

  it('deletes against the route the backend actually serves', async () => {
    const fetchMock = respond(true);
    await deleteConversation('abc');
    expect(fetchMock).toHaveBeenCalledWith('/api/owl/sessions/abc', { method: 'DELETE' });
  });

  it('resolves truthy when a delete succeeds', async () => {
    respond(true);
    expect(await deleteConversation('abc')).toBeTruthy();
  });

  it('throws when a delete is refused', async () => {
    respond(false);
    await expect(deleteConversation('abc')).rejects.toThrow('Delete failed');
  });

  it('renames against the same session route, with the title as the body', async () => {
    const fetchMock = respond(true);
    await renameConversation('abc', 'New name');
    expect(fetchMock).toHaveBeenCalledWith('/api/owl/sessions/abc', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: 'New name' }),
    });
  });

  it('resolves truthy when a rename succeeds', async () => {
    respond(true);
    expect(await renameConversation('abc', 'New name')).toBeTruthy();
  });

  it('throws when a rename is refused', async () => {
    respond(false);
    await expect(renameConversation('abc', 'New name')).rejects.toThrow('Rename failed');
  });

  const respondWith = (ok: boolean, body: unknown) => {
    const fetchMock = vi.fn().mockResolvedValue({ ok, json: async () => body });
    vi.stubGlobal('fetch', fetchMock);
    return fetchMock;
  };

  it('deletes every conversation against the collection route', async () => {
    const fetchMock = respondWith(true, { ok: true, deleted: 3 });
    await deleteAllConversations();
    expect(fetchMock).toHaveBeenCalledWith('/api/owl/sessions', { method: 'DELETE' });
  });

  it('reports how many were deleted, so the toast can be specific', async () => {
    respondWith(true, { ok: true, deleted: 14 });
    expect(await deleteAllConversations()).toEqual({ ok: true, deleted: 14 });
  });

  it('treats a missing or unreadable count as zero rather than NaN', async () => {
    respondWith(true, {});
    expect((await deleteAllConversations()).deleted).toBe(0);

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, json: async () => { throw new Error('not json'); },
    });
    vi.stubGlobal('fetch', fetchMock);
    expect((await deleteAllConversations()).deleted).toBe(0);
  });

  it('throws when the bulk delete is refused', async () => {
    respondWith(false, {});
    await expect(deleteAllConversations()).rejects.toThrow('Delete failed');
  });
});
