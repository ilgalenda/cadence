# Calls Agent

Analyses sales-call recordings and transcripts with Claude, extracts reusable
learnings, and builds a per-user knowledge layer plus team quizzes. The in-call
and onboarding knowledge partner for the sales team.

Router prefix: `/api` (tag `calls`). Backend: `backend/agents/calls/`.

## How it works

- Upload audio or paste a transcript → a structured analysis streams back:
  summary, buying signals, objections, talking points, concepts, learnings, new
  glossary terms, and a multiple-choice quiz.
- Atomic **learnings** are extracted per call and accumulate into a personal
  knowledge layer injected into future sessions.
- Analysis is grounded in a **transcript-scoped slice** of the vault
  (`load_vault_for_analysis`) — only what the call references plus an always-on
  core — so each run stays cheap.
- **Product fit is opt-in**: generated on demand from the stored analysis rather
  than on every call.

## Endpoints

All require a session; uploads/deletes of shared knowledge require admin.

| Method · Path | Type | Description |
|---|---|---|
| `POST /api/chat/stream` | SSE | Knowledge chat grounded in the vault |
| `POST /api/analyze` | JSON | Analyse a call transcript |
| `POST /api/transcribe` | JSON | Transcribe an uploaded recording |
| `GET /api/sessions` | JSON | List the user's analysed calls / sessions |
| `GET /api/stats` | JSON | Call/knowledge counts |
| `GET /api/calls` · `GET /api/calls/{id}` | JSON | List / fetch an analysed call |
| `POST /api/calls/{id}/product-recommendation` | JSON | Opt-in product fit for a stored analysis |
| `DELETE /api/calls/{id}` | JSON | Delete an analysed call |
| `GET /api/learnings` | JSON | The user's extracted learnings |
| `GET /api/quiz/pool` | JSON | Aggregate quiz pool from analysed calls |
| `POST /api/quiz/generate` · `POST /api/quiz/newsletter` | JSON | Generate team / client MCQs |
| `GET /api/glossary` · `GET /api/products` | JSON | Static reference data |
| `GET /api/knowledge` | JSON | List knowledge-base files |
| `POST /api/knowledge/upload` · `DELETE /api/knowledge/{filename}` | JSON | Manage KB files (admin) |

## Data & storage

Per-user, sandbox-aware, under `${DATA_ROOT}/agents/calls/`:

- `data/sessions.json` — analysed calls + chat sessions (the analysis, transcript,
  quiz, new terms). `save_session` / `patch_session_result` / `load_user_sessions`.
- `data/learnings/<username>.json` + `knowledge/<username>/learnings-auto.md` —
  per-user learnings (JSON + auto-rendered markdown).
- `knowledge/*.md|txt` — the shared, admin-managed knowledge base.

## Grounding & models

Vault via `load_vault_for_session` (chat), `load_vault_for_analysis` (analysis),
`load_vault_for_product_rec` (product fit). Persona + vault are sent as cached
content blocks. Model: `claude-sonnet-4-6`.

## Frontend

`frontend/src/pages/agents/calls/` — Overview, Call Analyser, Calls analysed,
Quiz, Glossary, Products, Knowledge Base, Meet Capture. Nav in
`frontend/src/agents/calls/config.ts`.

## Key files

- `routes.py` — endpoints, analysis orchestration, session/learning persistence,
  system-prompt assembly, static glossary/products.
- (uses `agents/shared/vault.py` for grounding and learning writes.)

Related: the [Meet](meet.md) agent captures Google Meet transcripts that feed the
Call Analyser.
