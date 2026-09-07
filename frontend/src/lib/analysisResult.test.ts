// What can be checked about the shared call reading without a browser.
//
// `AnalysisResult.astro` is the one component four surfaces render, and its
// script is `is:inline` so that `renderAnalysisResult` can be a global. That
// makes every class name a **string literal** passed to `el(tag, className)`
// rather than an import anything can follow. Nothing in the toolchain sees
// those strings: `check-adherence.mjs` checks tokens, colours and raw px, and
// has no concept of "this class exists". So a renamed class that is missed in
// one builder is a silently unstyled element, shipped.
//
// These are the structural rules that close that hole. They are deliberately
// cheap — no DOM, no render — and they read the `.astro` source directly, the
// same way `platform.test.ts` reads `tokens.css`.
//
// **One known limit, stated rather than hidden.** A class built by
// concatenation (`'ds-mark ds-mark--' + mark`) is only checkable as far as its
// stem; the extraction records `ds-mark` and cannot know the suffix. That is
// the sole dynamic construction in the file and its four suffixes are the
// design system's status vocabulary, checked where they are declared.

import { readFileSync, readdirSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

const COMPONENT = new URL('../components/AnalysisResult.astro', import.meta.url);
const DESIGN_SYSTEM = new URL('../design-system/', import.meta.url);
const GLOBAL_CSS = new URL('../styles/global.css', import.meta.url);

const source = readFileSync(COMPONENT, 'utf8');

/**
 * The component split at its stylesheet: a name inside the `<style>` block is a
 * declaration, a name anywhere else is a use. Keeping them apart is what lets a
 * rule with no use and a use with no rule be told apart.
 */
const styleOpen = source.indexOf('<style is:global>');
const styleClose = source.indexOf('</style>', styleOpen);
const styleBlock = source.slice(styleOpen, styleClose);
const markupAndScript = source.slice(0, styleOpen) + source.slice(styleClose);

/** Every capture of `pattern` in `text`, deduplicated. */
function namesIn(text: string, pattern: RegExp): Set<string> {
  return new Set([...text.matchAll(pattern)].map((match) => match[1]));
}

/** Every `.ds-*` rule the design system and the app stylesheet declare. */
function declaredDesignSystemClasses(): Set<string> {
  let css = readFileSync(GLOBAL_CSS, 'utf8');
  for (const file of readdirSync(DESIGN_SYSTEM)) {
    if (file.endsWith('.css')) css += readFileSync(new URL(file, DESIGN_SYSTEM), 'utf8');
  }
  return namesIn(css, /\.(ds-[a-z0-9_-]+)/g);
}

const declaredLocal = namesIn(styleBlock, /\.(ar__[a-z0-9_-]+)/g);
const usedLocal = namesIn(markupAndScript, /\b(ar__[a-z0-9_-]+)\b/g);
const usedDesignSystem = namesIn(markupAndScript, /\b(ds-[a-z0-9_-]+)\b/g);

describe('the call reading’s classes', () => {
  it('styles every local class it uses', () => {
    const orphans = [...usedLocal].filter((name) => !declaredLocal.has(name)).sort();

    expect(orphans).toEqual([]);
  });

  it('uses every local class it styles', () => {
    const unused = [...declaredLocal].filter((name) => !usedLocal.has(name)).sort();

    expect(unused).toEqual([]);
  });

  it('only reaches for design-system classes that exist', () => {
    const declared = declaredDesignSystemClasses();
    const unknown = [...usedDesignSystem].filter((name) => !declared.has(name)).sort();

    expect(unknown).toEqual([]);
  });

  // The uniformity pass retired these in favour of the primitives that already
  // named them. Listing them by name is what makes a missed builder string fail
  // loudly here rather than quietly on the page.
  it('does not resurrect a class the design system already names', () => {
    const retired = ['ar__list', 'ar__none', 'ar__tags', 'ar__well', 'ar__panel'];
    const survivors = retired.filter((name) => source.includes(name));

    expect(survivors).toEqual([]);
  });
});

describe('the call reading’s tabs', () => {
  const tabs = [...source.matchAll(/<button[^>]*class="[^"]*result-tab[^"]*"[^>]*>/g)].map((m) => m[0]);
  const panelIds = [...source.matchAll(/<div id="(tab-[a-z]+)" class="result-panel/g)].map((m) => m[1]);

  it('draws one tab per panel', () => {
    expect(tabs).toHaveLength(panelIds.length);
    expect(tabs.length).toBeGreaterThan(0);
  });

  it('gives every tab the state assistive technology reads', () => {
    const incomplete = tabs.filter(
      (tab) => !tab.includes('aria-selected') || !tab.includes('aria-controls') || !/\bid="/.test(tab),
    );

    expect(incomplete).toEqual([]);
  });

  it('points every tab at a panel that exists', () => {
    const controlled = tabs
      .map((tab) => tab.match(/aria-controls="([^"]+)"/)?.[1])
      .filter((id): id is string => Boolean(id));
    const dangling = controlled.filter((id) => !panelIds.includes(id));

    expect(dangling).toEqual([]);
    expect(controlled).toHaveLength(tabs.length);
  });

  it('labels every panel with the tab that opens it', () => {
    const panels = [...source.matchAll(/<div id="tab-[a-z]+" class="result-panel[^>]*>/g)].map((m) => m[0]);
    const unlabelled = panels.filter(
      (panel) => !panel.includes('role="tabpanel"') || !panel.includes('aria-labelledby'),
    );

    expect(unlabelled).toEqual([]);
  });
});
