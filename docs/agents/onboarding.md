# Onboarding Agent

> **Operations — part two.**
> A v1 agent, kept deliberately. It predates the Owl Mind and still calls the
> retired `agents.shared.anthropic_client` directly, so it is not registered in
> `backend/main.py` and does not run in this build. Bringing these onto the Mind
> is the next section of work; see [Operations](../operations.md).


A role-aware guided chat that walks new sales and operations users through the
platform, grounded in the team's knowledge vault and an editable curriculum.
Used by both tracks.

Router prefix: `/api/onboarding` (gated by `require_agent_access("onboarding")`).
Backend: `backend/agents/onboarding/`.

## How it works

- The user picks a **track** — sales/GTM or operations — and chats. The system
  prompt is assembled per track by `onboarding_system_blocks(username, role)`:
  the onboarding persona, a track-specific focus, the editable curriculum
  (`curriculum.md`), and the shared vault (`load_vault_for_session`), with a
  `cache_control` breakpoint for multi-turn efficiency.
- Role is normalised from the request (or the user's profile `role`): sales / gtm
  / account / sdr / revenue / founder → **sales**; everything else → **ops**.
- A lightweight per-user **progress checklist** tracks completed steps.

## Endpoints

Gated by `require_agent_access("onboarding")`.

| Method · Path | Type | Description |
|---|---|---|
| `POST /api/onboarding/stream?role=sales\|ops` | SSE | Grounded onboarding chat turn |
| `GET /api/onboarding/progress` | JSON | The user's completed steps |
| `POST /api/onboarding/progress` | JSON | Mark a step done / undone |
| `GET /api/onboarding/stats` | JSON | Count of completed steps |

The stream endpoint accepts the standard chat body (`{messages, conversation_id?,
call_id?}`) and emits the shared SSE shape, so the frontend reuses `streamChat`
(passing `url` + the `role` query param).

## Data & storage

`progress` collection (one record per user, `id == username`) at
`${DATA_ROOT}/agents/onboarding/data/progress.json` — a sorted list of completed
step keys. Sandbox-aware.

## Knowledge & models

Grounded via `load_vault_for_session(username)` plus the curriculum file. Model:
`claude-sonnet-4-6`. Edit `backend/agents/onboarding/curriculum.md` to tailor the
onboarding path to your team.

## Frontend

`frontend/src/pages/agents/onboarding/index.astro` — a sales/ops track toggle and
a streaming chat surface (reusing `streamChat` + `renderMarkdown`).

## Key files

- `routes.py` — stream + progress endpoints · `knowledge.py` — role-aware system
  blocks · `prompts.py` — the onboarding persona · `curriculum.md` — editable
  onboarding content · `storage.py` — progress collection.
