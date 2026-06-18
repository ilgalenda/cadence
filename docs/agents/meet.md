# Meet Agent

A lightweight capture endpoint for Google Meet transcripts. It stores a raw
transcript and hands the text off to the [Calls](calls.md) agent for analysis —
no LLM of its own.

Router prefix: `/api/meet` (gated by `require_authed`). Backend: `backend/agents/meet/`.

## Endpoints

| Method · Path | Type | Description |
|---|---|---|
| `POST /api/meet/submit` | JSON | Save a Meet transcript; returns a `transcript_id` |
| `GET /api/meet/transcript/{session_id}` | file | Download the stored transcript |

## Data & storage

Transcripts are stored **per user** at
`${DATA_ROOT}/agents/calls/data/transcripts/<username>/<session_id>.txt`
(`_user_transcript_path`). Scoping by username means a transcript id from one
user can't be read by another. The `session_id` is validated against
`^[a-zA-Z0-9_-]{1,64}$`.

## Frontend

Surfaced inside the Calls agent as the "Meet Capture" page
(`frontend/src/pages/agents/calls/meet.astro`), paired with the
`meet-extension/` browser capture script in the repo root.

## Key files

- `routes.py` — the two endpoints + the per-user path resolver.
