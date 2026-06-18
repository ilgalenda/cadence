# High-Intent Agent

Detects LinkedIn buying-intent signals across a set of signal types, composes
multi-touch outreach, and tracks what's been sent. Ships as an **admin-only,
always-sandboxed** capability — a staging ground that never writes to the shared
vault or production data.

Router prefix: `/api/high-intent` (gated by `require_admin`).
Backend: `backend/agents/high_intent/`.

## How it works

- Configure an **ICP** per signal type (e.g. job change, funding, competitor
  engagement, influencer engagement, top-ICP activity, company engagement).
- **Detect** runs signal detection filtered by that ICP and queues prospects with
  a strength rating.
- **Compose** generates a multi-touch outreach sequence for a signal;
  **follow-up** drafts a reply to a prospect response.

## Endpoints

All `require_admin`; JSON.

| Method · Path | Description |
|---|---|
| `GET /api/high-intent/signal-types` | Signal types, labels, ICP field definitions |
| `GET /api/high-intent/stats` | Signal / queue / sent counts |
| `GET·POST /api/high-intent/icp[/{signal_type}]` | Read / save ICP configs |
| `POST /api/high-intent/detect` | Run detection for a signal type |
| `GET /api/high-intent/queue` | Pending / composing / composed signals by strength |
| `GET /api/high-intent/signals[/{id}]` · `PATCH·DELETE .../signals/{id}` | Signal list / CRUD |
| `POST /api/high-intent/compose` | Compose a multi-touch sequence for a signal |
| `GET /api/high-intent/messages/{signal_id}` · `PATCH .../messages/{id}` | Composed message read / update |
| `POST /api/high-intent/followup` | Generate a follow-up to a reply |
| `GET /api/high-intent/history` | Sent signals |

## Data & storage

**Sandbox-only** — everything under `${DATA_ROOT}/agents/high_intent/_sandbox/`:
`signals.json` (cap 500), `messages.json` (cap 500), `icp_configs.json`
(per-user, keyed by signal type). `storage.py`.

## Models

`claude-sonnet-4-6` for detection and composition (`pipeline.py`, `prompts.py`).

## Frontend

`frontend/src/pages/agents/high-intent/` — Overview, Signal agents (ICP setup),
Signal queue, Compose, History. The dashboard card carries a "test/sandbox" badge.

## Key files

- `routes.py` — ICP, detection, composition, message approval · `storage.py` —
  sandbox JSON persistence · `pipeline.py` — detection + composition ·
  `prompts.py` — prompts.
