// Cadence version + changelog — single source of truth.
// To ship a new version: bump CADENCE_VERSION and prepend a new entry to CHANGELOG.
// Also bump /package.json and /frontend/package.json to match.

export const CADENCE_VERSION = '1.4.0';

export type ChangeLabel = 'Added' | 'Changed' | 'Fixed' | 'Security' | 'Removed';

export interface ChangeSection {
  label: ChangeLabel;
  items: string[];
}

export interface ChangelogEntry {
  version: string;
  date: string;
  headline: string;
  sections: ChangeSection[];
}

export const CHANGELOG: ChangelogEntry[] = [
  {
    version: '1.4.0',
    date: '2026-06-16',
    headline: 'Call-analysis cost reduction & call-aware Owl chat',
    sections: [
      {
        label: 'Changed',
        items: [
          'Call analyser now sends a **transcript-scoped slice of the vault** instead of the full ~130k-token knowledge base on every call (`agents/shared/vault.py:load_vault_for_analysis`): deterministic mention-matching selects only the entities, glossary terms, and learnings the call references, plus an always-on core. ~130k → ~13–20k tokens per analysis (~84% fewer; ~$0.11 vs ~$0.44). An A/B against the full vault (absolute rubric) scored the scoped output equal-or-better with fewer unsupported claims.',
          '`load_vault_for_context` refactored into composable section-builders (byte-identical output) shared by the full and scoped paths.',
          'Per-call analysis quiz is now 6 multiple-choice questions (flashcard-type items dropped); aligns with the already-MCQ-only generated/newsletter quizzes.',
          '`log_cache_usage` now reports per-call input/output tokens and an estimated cost alongside the prompt-cache counters.',
        ],
      },
      {
        label: 'Added',
        items: [
          'Opt-in product recommendation: `POST /api/calls/{id}/product-recommendation` generates product fit on demand from the stored analysis (optionally naming the product), with a focused product vault — instead of computing it on every analysis. New "Generate recommendation" CTA in the analysis view.',
          'Call-aware Owl chat: `/api/owl/stream` accepts a `call_id`, grounds Owl in that call’s analysis as default context with a vault scoped to the call, and exposes the verbatim transcript via a `fetch_transcript` tool (streaming tool-use loop). Analysis-first, transcript pulled in only on a deep-dive. Transcripts are now stored on the analysed-call session to support this. "Ask Owl about this call" entry points open the grounded chat.',
        ],
      },
      {
        label: 'Removed',
        items: [
          '`product_fit` and `product_recommendation` are no longer part of the default `/analyze` response (now opt-in, see above). Existing readers already handled their absence defensively.',
        ],
      },
    ],
  },
  {
    version: '1.3.0',
    date: '2026-06-15',
    headline: 'Lead Owl revamp & behavioural scoring',
    sections: [
      {
        label: 'Added',
        items: [
          'Conversational campaign builder (`agents/lead/builder.py`): Owl chats with the user to shape an outreach campaign for a specific lead, then drives the existing generation pipeline via tool use; each tool result is persisted onto the campaign so the frontend re-hydrates the produced artifact (sequence / boolean / ABM matrix). New `/campaigns/{id}/chat` and `/campaigns/from-prospects` endpoints.',
          'Deterministic behavioural lead scoring (`agents/lead/scoring.py`, no LLM): parses Leadinfo page-visit data and scores buying intent from pages visited, time on product vs blog pages, low-intent-page penalties, bounce detection, and company size. All weights are tunable in one config block. Exposed via `/prospect/score`, with a `test_scoring.py` suite.',
          'Self-updating site map (`agents/lead/sitemap.py`): fetches the live timebeat.app sitemap and pre-classifies every path into `page_map.json` so new pages are scored automatically; scoring itself stays offline. New `/page-map` and `/page-map/refresh` endpoints.',
          'X-Ray name sources (`agents/lead/name_sources.py`): pluggable provider architecture for prospect discovery — WebSearch provider always on, ZoomInfo/gtm.ai provider stubbed and disabled pending a seat.',
          'Prospect workflow: new prospect store and CRUD (`/prospects`, `/xray`, `/personas`) plus a new Prospect page in the Lead agent.',
          'Owl moved to a SQLite store (`agents/owl/db.py`) with WAL mode and per-call connections, replacing the shared `sessions.json` that suffered read-modify-write races; one-time importer `migrate_owl_sqlite.py` (idempotent, non-destructive). Session rename/delete via `PATCH`/`DELETE /sessions/{id}`. New standalone Owl chat page.',
          'Timebeat ICP / Persona knowledge entry in the vault.',
          'Shared JSON-extraction helpers (`agents/shared/jsonparse.py`) for stripping fenced/prose-wrapped model output in one place.',
        ],
      },
      {
        label: 'Changed',
        items: [
          'Lead agent pipeline, prompts, routes, and storage substantially reworked around the new conversational builder and prospect/scoring flow.',
          'OwlDrawer and Agent layout rebuilt for the revamped Owl chat surface; new `owl.css` and a dedicated `owlChat.ts` client.',
        ],
      },
      {
        label: 'Fixed',
        items: [
          'Assorted bug fixes across the lead agent surface bundled with the revamp.',
        ],
      },
    ],
  },
  {
    version: '1.2.1',
    date: '2026-06-02',
    headline: 'Call analyser reliability',
    sections: [
      {
        label: 'Fixed',
        items: [
          'Call analysis no longer crashes the request when the underlying analysis throws: `/analyze` now wraps `run_call_analysis` and returns a clean HTTP 500 with the failure detail (and a server-side traceback) instead of an opaque error.',
          'Calls analyze page reads error responses defensively via a new `errorMessage` helper, so non-JSON or empty error bodies surface a readable message instead of failing to parse.',
        ],
      },
      {
        label: 'Changed',
        items: [
          'Shared vault writes now invalidate the session assembly cache: `write_learning`, `write_entity`, `write_glossary_term`, and `approve_added` call the new `invalidate_vault_cache()`, so a new learning from one user surfaces in every user\'s next Owl turn rather than waiting for the cache TTL.',
        ],
      },
    ],
  },
  {
    version: '1.2.0',
    date: '2026-05-22',
    headline: 'Prompt caching',
    sections: [
      {
        label: 'Added',
        items: [
          'Anthropic prompt-cache integration across the agent surface. New `load_vault_for_session` and `log_cache_usage` helpers in the shared vault.',
          'Owl, Calls, and High-Intent now assemble their system prompts as content blocks with a `cache_control: ephemeral` breakpoint, so the persona + vault prefix is reused across requests within the cache TTL.',
          'Per-user identity tail moved after the cache breakpoint so it never invalidates the cached prefix.',
          'New `owl_system_blocks(username)` API in `agents/lead/owl.py`; `owl_system_prompt` retained as a flat-string shim for legacy callers.',
        ],
      },
      {
        label: 'Changed',
        items: [
          'Owl, Calls analysis, and High-Intent pipeline now consume system prompts as cache-friendly content-block arrays rather than flat strings.',
        ],
      },
    ],
  },
  {
    version: '1.1.0',
    date: '2026-05-21',
    headline: 'Knowledge architecture',
    sections: [
      {
        label: 'Added',
        items: [
          'Added-Knowledge lifecycle in the shared vault: write, approve, reject, and list pending / approved / rejected entries.',
          'Owl correction flow: Owl now detects when a user is correcting it and offers to save the exchange as an Added-Knowledge entry pending admin review, without affecting Owl\'s answers until approved.',
          'OwlDrawer inline correction card capturing title, description, what-Owl-said, the user correction, and an optional source.',
          'Admin agent — new backend (overview, pending / approved / rejected queues, approve / reject actions, all calls, call detail, all campaigns, all users) and frontend (Admin Dashboard + per-call detail view).',
          'Admin link surfaced in Dashboard and Agent layout headers, gated on admin access.',
          'High-Intent agent — end-to-end LinkedIn signal detection and outreach: signal-type catalogue, per-type ICP configuration, signal detection pipeline, queue management, 3-touch sequence composer, follow-up generator, and history view.',
          'Meet agent backend: transcript submit and retrieval endpoints.',
          '"IvanOS Meet Capture" Chrome extension (MV3): observes Google Meet caption DOM and forwards transcripts to Cadence.',
          'Calls / Meet flow: analyze.astro auto-fills from the extension\'s hash payload, runs a 3-second countdown, then auto-submits; raw transcript persisted and exposed via a "Download transcript →" link on the AnalysisResult component.',
          'Calls Quiz: Question Bank and Newsletter Quiz endpoints (`/quiz/pool`, `/quiz/newsletter`, `/quiz/generate`) and a new Quiz page in the Calls agent.',
          'Admin sandbox mode: per-session toggle (admin-only) with status, enable, and disable endpoints; header toggle in both layouts and an amber pulse indicator on the dashboard.',
          'Admin email notifications module (`agents/shared/notifications.py`) with SMTP config; silently no-ops when env vars are absent so the in-app badge still works.',
          'One-shot maintenance script `backend/scripts/normalise_company_truth.py`.',
          '`backend/paths.py` — single source of truth for all mutable data locations. New `DATA_ROOT` env var (defaults to `~/cadence-data`) controls where vault, agent state, and `users.json` live; storage modules across `vault`, `lead`, `calls`, `owl`, `high_intent`, `meet`, `auth`, and `admin` now resolve paths through it instead of `Path(__file__).parent`. The repo working tree is never written to at runtime.',
          'Seed dataset committed alongside the code (`backend/vault/`, `backend/agents/*/data/`, `backend/agents/users.json` profiles), so internal deployments can clone-and-run with full state.',
          'IT-focused first-boot runbook in the README and `.env.example`, with a where-to-get-it pointer per env var; warning that `seed_users.py` must not be re-run on a fresh clone because `users.json` already ships seeded.',
          '`bin/sync-from-repo.sh` to refresh a local `DATA_ROOT` from the committed repo data after `git pull`, preserving `users_credentials.json`.',
        ],
      },
      {
        label: 'Changed',
        items: [
          'Calls and Lead storage helpers are now sandbox-aware throughout; every route threads the request so sandbox state propagates end-to-end.',
          'Lead Owl system prompt extended for the knowledge architecture.',
          'Seed users: replaced the placeholder `test` user with a configurable set of profiles (admin + standard users); each profile takes a matching `<NAME>_PASSWORD` env var.',
          'Credentials split from profiles: password hashes moved out of the committed `users.json` into a gitignored `users_credentials.json` under `DATA_ROOT`, so each environment (laptop, server) carries its own credentials and `seed_users.py` never touches the committed profile file.',
          'Dashboard, Calls analyze page, Dashboard layout, and Agent layout updated to surface the new admin link, sandbox toggle, and Meet-capture entry point.',
          'README refreshed for the v1.1.0 surface and the new deployment model.',
        ],
      },
      {
        label: 'Security',
        items: [
          'New optional SMTP environment variables (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `ADMIN_NOTIFY_EMAIL`) and optional Phase-2 keys (`PHANTOMBUSTER_API_KEY`, `DRIPIFY_API_KEY`, `DRIPIFY_WEBHOOK_SECRET`) — all documented in `.env.example`, none required.',
          'Password hashes are no longer committed to the repo: they live in `users_credentials.json` under `DATA_ROOT` and are gitignored.',
        ],
      },
    ],
  },
  {
    version: '1.0.0',
    date: '2026-05-08',
    headline: 'Initial release',
    sections: [
      {
        label: 'Added',
        items: [
          'Calls agent: analyse, knowledge, products, glossary, and analysed-call history.',
          'Lead agent: campaigns, X-Ray, sequence and touch generation, ABM identify / sequence, boolean string generation, Google Calendar OAuth callback and event sync.',
          'Owl agent: routing, topics, storage, and the global OwlDrawer chat surface.',
          'Shared vault module: learnings, entities, glossary terms, and contextual vault loading.',
          'Session-based auth with login, status, and seeded users.',
          'Astro frontend: Dashboard and Agent layouts, OwlDrawer, Tabs, Toast, AnalysisResult, StatusDot, PageHeader, LeadHandoffButton.',
          'README and MIT licence.',
        ],
      },
      {
        label: 'Security',
        items: [
          'Session secret hardening, HTTPS-only cookies in production, and DEBUG reload flag for local development.',
        ],
      },
      {
        label: 'Changed',
        items: [
          'User password naming convention standardised across env vars and seed script.',
        ],
      },
    ],
  },
];
