# Lead Agent

Turns inbound leads and target accounts into personalised outreach: behavioural
lead scoring, X-Ray prospect discovery, multi-touch email / LinkedIn / ABM
sequences, a conversational campaign builder, and Google Calendar sync.

Router prefix: `/api/lead` (gated by `require_agent_access("lead")`).
Backend: `backend/agents/lead/`.

## How it works

- **Score** a lead deterministically from page-visit data (`scoring.py`, no LLM),
  graded A/B/C from intent signals.
- **X-Ray** discovers likely prospects for a campaign via pluggable name sources
  (`name_sources.py` — web search on by default), grounded in customer personas
  from the vault.
- **Generate** email sequences, LinkedIn boolean searches, and ABM matrices
  (`pipeline.py`), with a conversational **campaign builder** that drives the
  pipeline via Owl tool-use (`builder.py`).
- **Sync** chosen touches to Google Calendar (`google_calendar.py`, OAuth).
- Campaign learnings are written back into the vault's Dynamic pillar.

## Endpoints (selected)

Gated by `require_agent_access("lead")` (sitemap refresh is admin; the OAuth
callback is unauthenticated by necessity).

| Method · Path | Description |
|---|---|
| `GET /api/lead/stats` | Campaign / sequence / lead counts |
| `POST /api/lead/analyze` · `POST /api/lead/prospect/score` | Score a lead |
| `GET·POST /api/lead/campaigns` · `GET·PATCH·DELETE /api/lead/campaigns/{id}` | Campaign CRUD |
| `POST /api/lead/campaigns/{id}/xray` · `POST /api/lead/xray` | Prospect discovery |
| `POST /api/lead/campaigns/{id}/chat` | Conversational campaign builder (tool-use) |
| `POST /api/lead/campaigns/{id}/sequence` · `.../sequence/touch/{n}/regenerate` | Email sequence |
| `POST /api/lead/campaigns/{id}/boolean` | LinkedIn boolean search |
| `POST /api/lead/campaigns/{id}/abm/identify` · `.../abm/sequence` | ABM identification + matrix |
| `GET·POST·DELETE /api/lead/prospects[/{id}]` · `POST /api/lead/campaigns/from-prospects` | Saved prospect lists |
| `GET /api/lead/personas` | Persona job-title focus options |
| `POST /api/lead/owl/fill` | Inline Owl field-filler |
| `GET /api/lead/google/status` · `/connect` · `/callback` · `POST /disconnect` | Google Calendar OAuth |
| `POST /api/lead/campaigns/{id}/calendar/sync` | Sync a touch to Calendar |
| `GET /api/lead/page-map` · `POST /api/lead/page-map/refresh` | Site-map for scoring |

## Data & storage

Per-user, sandbox-aware, under `${DATA_ROOT}/agents/lead/`:

- `data/campaigns.json` (cap 200), `data/leads.json` (cap 500),
  `data/prospects.json` (cap 200) — `storage.py` (`upsert_campaign`,
  `save_prospect_list`, …).
- `data/learnings/<username>.json` + `knowledge/<username>/learnings-auto.md`.
- `data/page_map.json` — classified site map for scoring.
- `data/google_tokens.json` — per-user OAuth tokens (gitignored).

## Grounding & models

`load_vault_for_session` / `load_combined_knowledge` for context;
`load_customer_personas()` reads `company/knowledge/Persona.md` to ground X-Ray.
Generation uses `claude-sonnet-4-6` (Owl refinement may use Haiku). Lead scoring
is deterministic (no model).

## Frontend

`frontend/src/pages/agents/lead/` — Overview, X-Ray search, New campaign, Saved
campaigns, Integrations. Shared card vocabulary in `frontend/src/lib/leadCards.ts`.

## Key files

- `routes.py` — all endpoints · `storage.py` — persistence · `pipeline.py` — LLM
  generation · `builder.py` — conversational builder (tool-use) ·
  `scoring.py` — deterministic scoring · `name_sources.py` — prospect sources ·
  `sitemap.py` — site-map sync · `google_calendar.py` — Calendar OAuth ·
  `knowledge.py` — vault loading + persona · `prompts.py` — prompts.
