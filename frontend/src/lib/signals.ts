// The buying signals X-ray can sweep for, and how they read to a person.
//
// The wire values are the backend's `SIGNAL_TYPES`; these are the labels. Kept
// here rather than in `platform.ts` because they are X-ray's vocabulary, not the
// platform's shape — and kept out of the agent's page so the runner in R2 can
// name a step's signal without importing a page.

const SIGNAL_LABELS: Record<string, string> = {
  competitor_engagement: 'Engaging a competitor',
  influencer_engagement: 'Engaging an influencer',
  job_change: 'Recently changed role',
  funding: 'Recently funded',
  top_icp: 'Top 5% ICP activity',
  company_engagement: 'Engaged with Acme',
};

/** A signal's label, falling back to the raw type so an unknown one still reads. */
export const signalLabel = (type: string): string => SIGNAL_LABELS[type] ?? type;
