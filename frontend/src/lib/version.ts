// Cadence version + changelog — single source of truth.
// To ship a new version: bump CADENCE_VERSION and prepend a new entry to CHANGELOG.
// Also bump /package.json and /frontend/package.json to match.

export const CADENCE_VERSION = '2.0.0';

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
    version: '2.0.0',
    date: '2026-08-14',
    headline: 'One platform: Owl Core, the sales section, and the design system',
    sections: [
      {
        label: 'Added',
        items: [
          '**Owl Core — the Mind** (`agents/mind`): the single governed LLM gateway every agent composes. Agents call task-shaped methods (`classify` · `compose` · `analyze` · `chat` · `chat_stream` · `research`) instead of the Anthropic SDK. One shared client, one retry policy, one place model IDs live (`registry.py` — Haiku 4.5 · Sonnet 5 · Opus 4.8), and a per-task profile fixing tier, token budget, thinking and backoff.',
          '**Unified tool loop** (`mind/tooling.py`): one implementation that continues a turn on `tool_use`, `pause_turn` (server-side web search) and `max_tokens`, so a client tool, a web search and a truncated reply are all handled the same way everywhere.',
          '**Per-user working memory** (`mind/memory.py`, SQLite + WAL): preferences, ongoing context, accounts, deals and per-account topics, persisted per user and injected on Owl’s uncached system tail so the cached persona+vault prefix stays byte-stable. `topics_for_vertical` cross-references what has already resonated on similar-vertical accounts. Idempotent backfill from existing research briefs and legacy campaigns.',
          '**One Persona** (`mind/persona.py`): a single owned identity, house voice and knowledge-governance stance, with a thin role overlay per agent — ending the three separately-drifting Owl prompts.',
          '**Owl organisation**: projects carrying standing instructions that ride into every conversation filed under them, nested folders, placement and search. Containment is soft — deleting a container never destroys the conversations inside it.',
          '**The sales section** (`agents/sales`, `/api/sales`): eleven agents, each its own module with its own routes — Call Analysis, Knowledge Capture, Recap, Research, Campaign Intelligence, Campaign Selection, Composer, GTM, X-ray, Signals, Scoring. Every one is reachable two ways, through its own page and by asking Owl, from a single registration that pairs the tool schema with the runner so Owl can never be offered a tool nothing can execute.',
          '**Capability services** (`agents/services`): the shared skills agents compose rather than duplicate — behavioural lead scoring and campaign selection (both deterministic, no LLM), web discovery, Lusha enrichment, the two-pass outreach composer, per-user style personalisation, the sitemap and name-source providers.',
          '**The review gate** (`services/review.py`): the platform’s one human-in-the-loop primitive. Consequential output is submitted as `pending` and does nothing until a human approves it; the primitive has no send or execute action at all, so *agents draft, the human decides* is enforced structurally rather than by convention.',
          '**Integrations layer** (`backend/integrations`): the Google grant split out of the Calendar client and shared, with per-user tokens and its own surface at `/api/integrations/google`; Gmail **drafts only** — the grant requested cannot send, so the fence sits outside our code; Lusha person enrichment with a two-tier reveal (email automatically, phone only on explicit request) so credits are spent deliberately.',
          '**Signals**: a lean watchlist that notices funding rounds and timing technographics on named accounts, keeping a fingerprint of every finding already reported so a sweep returns what is new rather than repeating the same search.',
          '**Acme Learning** (`agents/learn`, `/learn`): the quiz pool, the certification quiz and the client-facing newsletter questions, moved out of the calls module and anonymised as a rule; plus the call library and the knowledge reader.',
          '**The wiki** (`agents/wiki`, `/api/wiki`): the vault made readable by a human instead of a prompt — every knowledge page indexed with its provenance, ranked search, and one page as structured blocks with its links and backlinks.',
          '**The Cadence Design System, in the repo** (`frontend/src/design-system`): tokens, primitives, components, the spring motion vocabulary, fonts and previews, mirroring the design project. Enforced by an adherence gate (`npm run check:design`) with three severities — errors for off-inventory tokens, colours and fonts, a per-file ratchet for raw px so debt can never deepen, and loudly-reported gaps in the system itself. It runs in the build.',
          '**The platform shell**: one rail for the whole product — Work · Owl · Learn — built from `lib/platform.ts` so it cannot advertise a surface that does not exist, with a breadcrumb and a home surface.',
          '**A backend test suite**: around forty pytest modules covering the Mind, memory, persona, routing, the tool registry, every sales agent, the capability services, the integrations, the wiki and quizzes, X-ray output quality against a rubric, request shape, and a test that pins the model generation.',
        ],
      },
      {
        label: 'Changed',
        items: [
          'Information architecture rebuilt around the job rather than the code: `/work`, `/owl` and `/learn` replace `/dashboard` and the per-agent `/agents/*` trees. `main.py` now mounts four routers and stops changing as agents land.',
          'Call Analysis does one job — reading the transcript. The follow-up email, the learnings filed into the vault and the product-fit read are their own agents now, so a failure in one can no longer cost the analysis somebody is waiting for.',
          'No module builds its own Anthropic client or names a model any more; upgrading the whole platform is an edit to `MODELS`.',
          'Concurrency is one process-wide governor instead of two independent semaphores, applied at pipeline orchestration boundaries only so a batch run never serialises interactive chat behind it. Behaviour change: the two pipelines that used to run concurrently now contend for one slot (`MIND_MAX_CONCURRENCY`).',
          'Cost logging is rate-correct per tier. The old table hard-coded Sonnet rates for every call and mis-reported every non-Sonnet one.',
          '`paths.py` accessors renamed `lead_*` → `sales_*`, and now state the rule explicitly: a package may move, a live data snapshot does not. The directories keep their old names on purpose.',
        ],
      },
      {
        label: 'Fixed',
        items: [
          'A reply that hits the token ceiling now continues instead of being cut mid-sentence.',
          'One rail implementation for every surface. The second, hand-rolled one — a mono wordmark the design system bans, typed glyphs where the system draws icons, no search or collapsed state — is what the misaligned menus were.',
          'The changelog now renders its own inline formatting rather than printing the asterisks and backticks.',
        ],
      },
      {
        label: 'Removed',
        items: [
          'The `calls`, `lead`, `high_intent` and `meet` packages, retired whole — their work redistributed across the sales agents, Learn and the wiki. No endpoint serves the same job twice.',
          'The old frontend: the dashboard, the `/agents/*` pages, both layouts, `OwlDrawer`, `Tabs`, `StatusDot`, `PageHeader`, `LeadHandoffButton` and `owl.css`.',
          'The Meet Chrome extension, and the `faster-whisper` dependency with it — transcription happens outside Cadence.',
        ],
      },
    ],
  },
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
          'Self-updating site map (`agents/lead/sitemap.py`): fetches the live acme.example sitemap and pre-classifies every path into `page_map.json` so new pages are scored automatically; scoring itself stays offline. New `/page-map` and `/page-map/refresh` endpoints.',
          'X-Ray name sources (`agents/lead/name_sources.py`): pluggable provider architecture for prospect discovery — WebSearch provider always on, ZoomInfo/gtm.ai provider stubbed and disabled pending a seat.',
          'Prospect workflow: new prospect store and CRUD (`/prospects`, `/xray`, `/personas`) plus a new Prospect page in the Lead agent.',
          'Owl moved to a SQLite store (`agents/owl/db.py`) with WAL mode and per-call connections, replacing the shared `sessions.json` that suffered read-modify-write races; one-time importer `migrate_owl_sqlite.py` (idempotent, non-destructive). Session rename/delete via `PATCH`/`DELETE /sessions/{id}`. New standalone Owl chat page.',
          'Acme ICP / Persona knowledge entry in the vault.',
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
          '"SamOS Meet Capture" Chrome extension (MV3): observes Google Meet caption DOM and forwards transcripts to Cadence.',
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
          'Seed users: replaced placeholder `test` user with real users — `ian` (Co-Founder, admin) and `martin` (Head of Sales); env vars renamed to `IVAN_/IAN_/MARTIN_/JAKUB_PASSWORD`.',
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
