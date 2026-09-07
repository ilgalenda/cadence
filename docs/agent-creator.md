# Agent Creator

A CLI that scaffolds a new agent from a small spec — emitting the backend
package, the frontend config and page, and all the wiring — so a new agent is
minutes of work rather than boilerplate. It's the fastest way to extend the
platform.

Script: `backend/scripts/create_agent.py`. Templates: `backend/scripts/templates/agent/`.
Example specs: `backend/scripts/specs/`.

## Usage

```bash
# From a spec file
python backend/scripts/create_agent.py --spec backend/scripts/specs/duty.json

# Or inline
python backend/scripts/create_agent.py --slug renewals --name "Renewals" \
  --tagline "Track and forecast renewals" --kind crud --entity renewal

# Preview without writing anything
python backend/scripts/create_agent.py --spec backend/scripts/specs/duty.json --dry-run
```

## Spec fields

| Field | Required | Default | Meaning |
|---|---|---|---|
| `slug` | yes | — | URL/route slug (lowercase, letters/digits/hyphens, leading letter) |
| `name` | yes | — | Display name |
| `tagline` | yes | — | One-line description |
| `icon` | no | `◆` | Emoji/glyph for the nav |
| `kind` | no | `crud` | `simple` \| `crud` \| `chat` \| `tool` |
| `entity` | no | `item` | Singular record name (e.g. `quote`) |
| `status` | no | `active` | `active` \| `test` \| `coming-soon` (dashboard badge) |

## What it emits

- Backend package: `backend/agents/<slug>/{__init__.py, routes.py, storage.py}`
  (a `/stats` + CRUD scaffold over a `JsonCollection`).
- Frontend: `frontend/src/agents/<slug>/config.ts` and
  `frontend/src/pages/agents/<slug>/index.astro`.
- Wiring, inserted at anchor comments (idempotent — it won't double-insert):
  - `backend/paths.py` — a `<slug>_data()` helper.
  - `backend/main.py` — the router import and `include_router(...)`.
  - `frontend/src/pages/dashboard.astro` — an agent card.
  - `backend/seed_users.py` — the slug added to seeded profiles.

> **Three of those paths no longer exist.** 2.0 has no `frontend/src/agents/`, no
> `frontend/src/pages/agents/` — pages live under `work/agents/` — and no
> dashboard. The tool is kept as a record of how the v1 agents were scaffolded,
> not as something to run against this tree. `lib/platform.ts` is where an agent
> is declared now.

It refuses to overwrite an existing agent directory. After running, grant access
with `python backend/seed_users.py --rewrite-profiles`, then build out the
generated `routes.py` / page with real logic.

## Anchors

The generator inserts at these markers (added once to the host files):

| File | Anchor |
|---|---|
| `backend/paths.py` | `# >>> cadence:paths` |
| `backend/main.py` | `# >>> cadence:agent-imports`, `# >>> cadence:agent-routers` |
| `frontend/src/pages/dashboard.astro` | `// >>> cadence:agents` |

## What a hand-built agent reuses

Generated or hand-written, an agent composes the shared layer:

- **Auth** — gate the router with `require_agent_access("<slug>")` (or
  `require_admin`); read `is_sandbox(request)`; pass `user["username"]` down.
- **Paths** — add a `<slug>_data()` helper in `paths.py`.
- **Storage** — `agents/shared/jsonstore.py` `JsonCollection` for per-user,
  capped, sandbox-aware JSON (or SQLite for heavy history, as Owl does).
- **Claude** — `agents/shared/anthropic_client.py`
  (`call_claude` / `call_claude_text` / `slot()` + model constants).
- **JSON parsing** — `agents/shared/jsonparse.py` for tolerant model-output
  parsing.
- **Knowledge** — `agents/shared/vault.py` `load_vault_for_session(username)` (or
  `load_vault_for_analysis`) to ground prompts; assemble system blocks with a
  `cache_control: ephemeral` breakpoint.
- **Streaming** — emit the SSE shape (`data: {text|model|error}` + `[DONE]`) and
  reuse the frontend `streamChat({url, ...})` client.
- **Notifications** — `agents/shared/notifications.py` `send_admin_email(...)` for
  email (no-ops gracefully if SMTP is unset).

See [architecture](architecture.md) for the details of each.
