/**
 * Agent-to-agent handoff carried through the browser, not the URL.
 *
 * A path (`/work/paths/*`) keeps its carry in memory and threads a scored lead's
 * whole verdict into the next step. Standalone agent pages are separate
 * documents, so a handoff between them needs somewhere to put the payload. The
 * query string is the wrong place for this one: the scored verdict is a sizeable
 * object carrying the lead's role, company and behavioural signals, and a URL
 * would persist that in browser history and in any access log along the way.
 *
 * sessionStorage is scoped to the tab and cleared when it closes, and the
 * payload is *taken* rather than read — a handoff is consumed once, so a later
 * reload does not silently re-apply a lead the user has moved on from.
 */

const SCORED_LEAD_KEY = 'cadence:handoff:scored-lead';

/** The scored-lead verdict a handoff can carry. Shape mirrors `/leads/analyze`. */
export interface ScoredLead {
  company?: string;
  role?: string;
  industry?: string;
  product_fit?: string;
  signal_strength?: string;
  signal_type?: string;
  score?: number;
  score_signals?: string[];
  [key: string]: unknown;
}

/** Stash a verdict for the next page. Never throws — a failed handoff degrades. */
export function offerScoredLead(lead: ScoredLead): void {
  try {
    sessionStorage.setItem(SCORED_LEAD_KEY, JSON.stringify(lead));
  } catch {
    // Storage disabled, private mode, or full. The link still navigates; the
    // receiving page falls back to whatever the query string gave it.
  }
}

/**
 * Take the pending verdict, removing it. Returns null when there is none, or
 * when what is stored is not a usable verdict.
 */
export function takeScoredLead(): ScoredLead | null {
  let raw: string | null = null;
  try {
    raw = sessionStorage.getItem(SCORED_LEAD_KEY);
    sessionStorage.removeItem(SCORED_LEAD_KEY);
  } catch {
    return null;
  }
  if (!raw) return null;

  try {
    const parsed = JSON.parse(raw);
    // A verdict without a company cannot ground a company-scoped search, so it
    // is not a handoff — treat it as absent rather than half-applying it.
    if (parsed && typeof parsed === 'object' && typeof parsed.company === 'string' && parsed.company.trim()) {
      return parsed as ScoredLead;
    }
  } catch {
    // Corrupted payload — already removed above, so it cannot wedge the page.
  }
  return null;
}
