export const LEAD_AGENT_NAME = 'Lead Agent';
export const LEAD_AGENT_TAGLINE = 'Campaign creation & outreach';

export const LEAD_NAV = [
  { href: '/agents/lead', label: 'Overview', icon: '⊞', id: '/agents/lead' },
  { href: '/agents/lead/new', label: 'New campaign', icon: '✨', id: '/agents/lead/new' },
  { href: '/agents/lead/campaigns', label: 'Campaigns', icon: '📨', id: '/agents/lead/campaigns', match: ['/agents/lead/campaigns/'] },
];

// KB Section 2.1 — touch count by signal strength.
export const SIGNAL_DEFAULT_TOUCHES: Record<string, number> = {
  hot: 3,
  warm: 4,
  cold: 5,
};

export function defaultTouchesFor(strength: string | undefined | null): number {
  return SIGNAL_DEFAULT_TOUCHES[(strength || '').toLowerCase()] ?? 4;
}
