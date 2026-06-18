# Owl

The conversational knowledge partner. A streaming chat grounded in the whole
vault, with cheapest-capable-model routing, a call-aware deep-dive mode, and an
inline correction-capture flow that feeds the Added Knowledge pillar.

Router prefix: `/api/owl` (gated by `require_authed`). Backend: `backend/agents/owl/`.

## How it works

- **Model routing** (`routing.py`): each message goes to the cheapest model that
  can handle it — **Haiku** for short lookups, **Sonnet** for analytical or long
  questions. The model is locked to a conversation on its first turn so the voice
  doesn't flip mid-thread.
- **Grounding**: `owl_system_blocks(username)` assembles persona + the cached
  vault (`load_vault_for_session`) as content blocks with a `cache_control`
  breakpoint, with the per-user tail after it.
- **Call-aware mode**: pass `call_id` and Owl is grounded in that call's analysis
  as default context (vault scoped to the call); the verbatim transcript is
  pulled in only on demand via a `fetch_transcript` tool (a bounded streaming
  tool-use loop).
- **Corrections**: a lightweight Haiku classifier detects when a user is
  correcting Owl and offers to save it; on confirm it lands in
  `vault/added/pending/` for admin review.

## Endpoints

| Method · Path | Type | Description |
|---|---|---|
| `POST /api/owl/stream` | SSE | Chat turn (optional `call_id`; `fetch_transcript` tool) |
| `GET /api/owl/sessions` | JSON | List conversations (newest first; `?q=` search) |
| `GET /api/owl/sessions/{id}` | JSON | Full conversation with messages |
| `PATCH /api/owl/sessions/{id}` | JSON | Rename a conversation |
| `DELETE /api/owl/sessions/{id}` | JSON | Delete a conversation |
| `POST /api/owl/corrections/submit` | JSON | Submit a proposed correction → Added/pending |

## Data & storage

SQLite at `${DATA_ROOT}/agents/owl/owl.db` (WAL mode) — `conversations` and
`messages` tables, per-user, capped at 200 conversations, with topic tags for the
dashboard graph. `storage.py` / `db.py`. (Owl uses SQLite rather than the JSON
store because conversation history is higher-volume and benefits from indexed,
concurrent reads.)

## Models

`claude-sonnet-4-6` and `claude-haiku-4-5-20251001`, selected per message by
`select_model()`; the correction classifier always uses Haiku.

## Frontend

`frontend/src/pages/agents/owl/index.astro` (full-page chat) and the shared Owl
drawer; the SSE client + markdown renderer live in `frontend/src/lib/owlChat.ts`
and are reused by other agents' chat surfaces.

## Key files

- `routes.py` — streaming endpoint, tool-use loop, correction classifier, session
  management · `storage.py` — SQLite CRUD · `db.py` — schema + connections ·
  `routing.py` — model selection · `topics.py` — topic extraction.
- Persona + `owl_system_blocks` live in `agents/lead/knowledge.py`.
