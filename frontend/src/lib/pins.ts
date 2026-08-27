// The agents a person keeps in the rail.
//
// A personal preference about this browser's chrome, so it sits in localStorage
// beside `cadence.rail.closed` rather than on the server. Nothing about the work
// depends on it; losing it costs three clicks.
//
// Three is the ceiling, and the ceiling is the point. The rail listed all eleven
// agents before, which is what made it unreadable — with the top controls and the
// foot that is twenty-six controls in a column taller than the screen, so
// Knowledge fell below the fold. A pin list that can grow without limit is the old
// rail with extra steps.
//
// The reading half is duplicated, deliberately and once, by the inline script in
// `PlatformLayout.astro`: it has to run before the first paint and so cannot
// import. If the key or the ceiling changes here, it changes there too.

import { AGENTS } from './platform';

export const PINNED_KEY = 'cadence.agents.pinned';
export const MAX_PINNED_AGENTS = 3;

/**
 * The stored list, made safe to use.
 *
 * A preference that has been hand-edited, written by an older build, or left
 * behind by a since-deleted agent must not be able to break the rail — so unknown
 * slugs and duplicates are dropped and the list is cut to the ceiling.
 */
export function clean(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  const known = new Set(AGENTS.map((agent) => agent.slug));
  const seen = new Set<string>();
  return raw
    .filter((slug): slug is string => typeof slug === 'string')
    .filter((slug) => known.has(slug) && !seen.has(slug) && seen.add(slug) !== undefined)
    .slice(0, MAX_PINNED_AGENTS);
}

/** The pinned slugs. Empty when nothing is stored or the storage is unreadable. */
export function readPinned(): string[] {
  try {
    return clean(JSON.parse(localStorage.getItem(PINNED_KEY) || '[]'));
  } catch {
    return [];
  }
}

/** Store the list, cleaned. Storage failures are not worth an error to the user. */
export function writePinned(slugs: string[]): string[] {
  const kept = clean(slugs);
  try {
    localStorage.setItem(PINNED_KEY, JSON.stringify(kept));
  } catch { /* private browsing, a full quota — the page still works */ }
  return kept;
}
