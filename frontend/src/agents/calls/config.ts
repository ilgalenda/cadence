export const CALLS_AGENT_NAME = 'Calls Support Agent';
export const CALLS_AGENT_TAGLINE = 'In-call & onboarding partner';

export const CALLS_NAV = [
  { href: '/agents/calls',            label: 'Overview',        icon: '⊞',  id: '/agents/calls'           },
  { href: '/agents/calls/analyze',    label: 'Call Analyser',   icon: '🎯', id: '/agents/calls/analyze'   },
  { href: '/agents/calls/analysed',   label: 'Calls analysed',  icon: '📞', id: '/agents/calls/analysed', match: ['/agents/calls/call'] },
  { href: '/agents/calls/glossary',   label: 'Glossary',        icon: '📖', id: '/agents/calls/glossary'  },
  { href: '/agents/calls/products',   label: 'Products',        icon: '📦', id: '/agents/calls/products'  },
  { href: '/agents/calls/knowledge',  label: 'Knowledge Base',  icon: '🗂️', id: '/agents/calls/knowledge' },
];
