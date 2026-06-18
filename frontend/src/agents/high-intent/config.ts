export const HI_AGENT_NAME = 'High-Intent — Test';
export const HI_AGENT_TAGLINE = 'LinkedIn signal detection & outreach';

export const HI_NAV = [
  { href: '/agents/high-intent',         label: 'Overview',       icon: '⊞',  id: '/agents/high-intent'         },
  { href: '/agents/high-intent/setup',   label: 'Signal agents',  icon: '⚙',  id: '/agents/high-intent/setup'   },
  { href: '/agents/high-intent/queue',   label: 'Signal queue',   icon: '↓',  id: '/agents/high-intent/queue'   },
  { href: '/agents/high-intent/compose', label: 'Compose',        icon: '✍',  id: '/agents/high-intent/compose' },
  { href: '/agents/high-intent/history', label: 'History',        icon: '◌',  id: '/agents/high-intent/history' },
];

export const SIGNAL_TYPE_LABELS: Record<string, string> = {
  competitor_engagement: 'Competitor Engagement',
  influencer_engagement: 'Influencer Engagement',
  job_change: 'Recently Changed Roles',
  funding: 'Recently Funded',
  top_icp: 'Top 5% ICP Activity',
  company_engagement: 'Engaged with Timebeat',
};

export const SIGNAL_TYPE_ICONS: Record<string, string> = {
  competitor_engagement: '⚔',
  influencer_engagement: '◎',
  job_change: '→',
  funding: '↑',
  top_icp: '★',
  company_engagement: '◈',
};

export const SIGNAL_STRENGTH_LABELS: Record<string, string> = {
  hot: 'Hot',
  warm: 'Warm',
  cold: 'Cold',
};
