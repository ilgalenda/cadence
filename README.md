# Cadence — Timebeat internal Agentic Platform

An internal AI-powered intelligence system built for the Sales team. Cadence gives sales and GTM teams purpose-built agents backed by a shared knowledge vault that grows with every interaction.

> **INTERNAL NOTE.** This repo ships with operational data included: the Cadence knowledge vault (`backend/vault/`), agent runtime state (campaigns, leads, sessions, learnings), and seeded user records (with bcrypt-hashed passwords). Out-of-band you only need to supply credentials — see **First-boot for Timebeat IT** below.

---

## System overview

```
┌─────────────────────────────────────────────────────────┐
│                      Astro Frontend                     │
│        Dashboard · Calls · Lead · Owl drawer            │
└───────────────────────┬─────────────────────────────────┘
                        │ REST + SSE (streaming)
┌───────────────────────▼─────────────────────────────────┐
│                   FastAPI Backend                       │
│                                                         │
│  ┌─────────────┐  ┌─────────────┐  ┌────────────────┐  │
│  │ Calls Agent │  │ Lead Agent  │  │   Owl Agent    │  │
│  └──────┬──────┘  └──────┬──────┘  └───────┬────────┘  │
│         │                │                  │           │
│         └────────────────┼──────────────────┘           │
│                          │                              │
│               ┌──────────▼──────────┐                  │
│               │    Shared Vault     │                  │
│               │  (Obsidian-compat.) │                  │
│               └─────────────────────┘                  │
└─────────────────────────────────────────────────────────┘
                          │
              ┌───────────▼───────────┐
              │  Anthropic API        │
              │  Haiku 4.5 · Sonnet   │
              └───────────────────────┘
```

---

## Agents

### Calls Agent

Analyses sales call recordings and transcripts using Claude.

- Upload an audio file or paste a transcript
- Streams a structured analysis: summary, buying signals, objections raised, follow-up talking points, concepts mentioned, learnings, new glossary terms, and a short multiple-choice quiz
- Product fit is **opt-in** — generated on demand (`POST /api/calls/{id}/product-recommendation`, optionally naming the product) rather than on every call, since the rep usually already knows the product
- Extracts atomic learnings from each call and stores them per-user
- Learnings accumulate over time into a personal knowledge layer, injected into future sessions as context
- Grounded in a **transcript-scoped slice of the vault** (`load_vault_for_analysis`) — only the entities, glossary terms, and learnings the call references, plus a small always-on core — so each analysis stays cheap without losing relevant context

### Lead Agent

Manages prospect pipelines and campaign intelligence.

- Analyses companies for ICP fit, buying intent signals, and product alignment
- Generates outreach recommendations and campaign summaries
- Google Calendar integration for scheduling follow-ups
- Connects to the shared vault so call-derived intelligence informs lead strategy

### Owl

A conversational assistant with intelligent model routing.

- Full chat interface grounded in the combined knowledge vault
- Routes each message to the cheapest model that can handle it well:
  - **Haiku** — simple lookups, short factual questions
  - **Sonnet** — analytical questions, strategy, multi-step reasoning
- Routing is keyword-based with length heuristics (see `backend/agents/owl/routing.py`)
- Tags each session with extracted topics for browsable history
- **Call-aware mode**: opened on an analysed call (`?call_id=…`), Owl is grounded in that call's analysis as its default context and scopes the vault to it; the verbatim transcript is pulled in only on demand via a `fetch_transcript` tool, so a call deep-dive stays cheap until exact wording is actually needed

---

## Cadence Knowledge — three-pillar architecture

Every agent writes to and reads from a shared vault at `backend/vault/`. It is a valid [Obsidian](https://obsidian.md) vault — open the directory directly to browse the full knowledge graph. `[[wikilinks]]` cross pillar boundaries freely, so Obsidian renders the three pillars as a single connected graph.

The vault is split into three pillars, each with a distinct lifecycle:

```
backend/vault/
├── company/        # Pillar 1 — Company Truth (locked, canonical)
│   ├── products/         # hardware, solutions, industries, datasheets
│   ├── research/         # learn pillars, clusters, weekly digests
│   ├── knowledge/        # curated KB markdown
│   ├── entities/         # product / protocol / customer definitions
│   └── glossary/         # seed glossary terms
├── dynamic/        # Pillar 2 — Dynamic Truth (auto-grown)
│   ├── calls/            # learnings extracted from every analysed call
│   ├── lead/             # learnings from every outreach campaign
│   └── glossary/         # new terms discovered at runtime
└── added/          # Pillar 3 — Added Knowledge (admin-gated)
    ├── pending/          # awaiting admin review — NOT loaded by Owl
    ├── approved/         # admin-approved corrections — loaded by Owl
    └── rejected/         # archived; never loaded
```

**Pillar 1 — Company Truth.** Hand-curated, canonical Timebeat knowledge. Locked: the runtime never writes here. New folders are dropped into `company/` and normalised with `python3 backend/scripts/normalise_company_truth.py`, which adds the `tier: company`, `locked: true`, `description`, and `[[wikilink]]` injection in place. Idempotent — safe to re-run.

**Pillar 2 — Dynamic Truth.** Empirical insights extracted by the Calls and Lead agents from real customer interactions. Every entry carries both a `title` and a one-sentence `description`, enforced by the vault writer.

**Pillar 3 — Added Knowledge.** When a user corrects Owl in conversation ("actually that's wrong, X is…"), a lightweight classifier detects the correction intent and shows an inline confirmation card in the Owl drawer. On confirm, the correction lands in `added/pending/`. The admin gets an in-app badge on the `/admin` Approvals tab and an email (if SMTP is configured). On approve, the file moves to `added/approved/` and is loaded into Owl's context on the next turn. On reject, it moves to `added/rejected/` and is never loaded.

**Loader precedence.** Owl assembles context in this order, so Company Truth is never crowded out: Company Truth → Entities → Glossary (company first, then dynamic) → Dynamic Truth (scored top-N) → Approved Added Knowledge (capped) → linked entities pulled in via `[[wikilinks]]`.

Frontmatter contract: every runtime write requires both `title` and `description`; Added entries also carry `status: pending|approved|rejected` plus `reviewed_by` / `reviewed_at` / `review_notes` once an admin acts.

---

## Stack

| Layer | Technology |
|---|---|
| Frontend | [Astro](https://astro.build), Tailwind CSS |
| Backend | Python, [FastAPI](https://fastapi.tiangolo.com), Uvicorn |
| AI | [Anthropic SDK](https://github.com/anthropics/anthropic-sdk-python), streaming via SSE |
| Models | Claude Haiku 4.5, Claude Sonnet 4.6 |
| Auth | Session-based (bcrypt passwords, `starlette` sessions) |

---

## Project structure

```
cadence/
├── backend/
│   ├── main.py                    # FastAPI app, auth middleware, router mounting
│   ├── auth.py                    # Login, session, role helpers
│   ├── .env.example               # Required environment variables
│   ├── requirements.txt
│   ├── agents/
│   │   ├── calls/
│   │   │   ├── routes.py          # Upload, analysis, product-recommendation, glossary, learnings endpoints
│   │   │   └── knowledge/         # Product knowledge base (add your own .md files)
│   │   ├── lead/
│   │   │   ├── routes.py          # Campaign, lead, calendar endpoints
│   │   │   ├── pipeline.py        # Lead scoring and enrichment logic
│   │   │   ├── prompts.py         # Claude prompt definitions
│   │   │   ├── knowledge.py       # Knowledge loader + Owl system prompt builder
│   │   │   ├── storage.py         # Campaign and lead persistence
│   │   │   ├── google_calendar.py # Google Calendar OAuth + event management
│   │   │   └── knowledge/         # Lead intelligence knowledge (add your own .md files)
│   │   ├── owl/
│   │   │   ├── routes.py          # Chat stream (+ call-aware grounding & fetch_transcript tool) + session history endpoints
│   │   │   ├── routing.py         # Haiku vs Sonnet routing logic
│   │   │   ├── topics.py          # Keyword-based topic extraction
│   │   │   └── storage.py         # Per-user session persistence
│   │   └── shared/
│   │       └── vault.py           # Vault read/write, entity linking, frontmatter
│   └── vault/                     # Shared knowledge vault (populated at runtime)
└── frontend/
    ├── src/
    │   ├── pages/
    │   │   ├── agents/calls/      # Call upload, analysis view, glossary, knowledge
    │   │   ├── agents/lead/       # Lead list, campaign view, new lead flow
    │   │   └── dashboard.astro
    │   ├── components/            # Shared UI components (Owl drawer, tabs, toasts)
    │   └── layouts/               # AgentLayout, DashboardLayout, LoginLayout
    └── astro.config.mjs
```

---

## Where runtime data lives

Cadence stores all mutable state (vault, leads, sessions, Owl conversations, `users.json`, `users_credentials.json`, etc.) under a directory named by `DATA_ROOT`. The architecture is **data-in-git**: the live server's `DATA_ROOT` points at the repo's `backend/` directory, and a cron commits + pushes new ingested data back to git so every clone stays coherent.

| Variable | Purpose | Local dev | Production |
|---|---|---|---|
| `DATA_ROOT` | Where mutable state lives | path **outside** the repo, e.g. `~/cadence-data` | the repo's `backend/`, e.g. `/srv/cadence/backend` |

Two files split the user model:

- `backend/agents/users.json` — **committed**. Profiles (name, role, access, agents). Versioned with the code that consumes them.
- `${DATA_ROOT}/agents/users_credentials.json` — **gitignored**. Per-environment bcrypt password hashes. Each laptop/server runs `python backend/seed_users.py` once to populate it from the local `.env`.

## First-boot for Timebeat - TO READ

**Prerequisites:** Python 3.11+, Node 18+.

**Credentials Timebeat supplies (not in the repo):**

| Variable | Where to get it |
|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com → Settings → API Keys |
| `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` | Google Cloud Console → APIs & Services → Credentials → Create OAuth client (Web). Add `GOOGLE_REDIRECT_URI` to "Authorised redirect URIs" |
| `GOOGLE_REDIRECT_URI` | The deployment URL + `/api/lead/google/callback` (e.g. `https://your-deployment-host/api/lead/google/callback`) |
| `SESSION_SECRET` | Generate: `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `SMTP_*` (optional) | For admin approval emails. Gmail needs an App Password. System degrades gracefully if unset |

**Steps:**

```bash
# 1. Clone
git clone <internal-repo-url> cadence
cd cadence

# 2. Backend env
cd backend
cp .env.example .env
# In .env:
#   DATA_ROOT=/srv/cadence/backend         (point at the repo's backend dir)
#   ADMIN_PASSWORD=..., USER1_PASSWORD=...    (one per user)
#   SESSION_SECRET, ANTHROPIC_API_KEY, GOOGLE_*, SMTP_*, DEBUG=false
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Seed credentials (writes ${DATA_ROOT}/agents/users_credentials.json,
#    which is gitignored — never enters the repo).
python seed_users.py

# 4. Start the backend
python main.py                # starts on http://localhost:8000

# 5. Frontend (separate terminal)
cd frontend
npm install
npm run build                 # or `npm run dev` for hot reload on :4321
```

The backend serves the built frontend from `frontend/dist/` at `/`. In development, run the Astro dev server separately and proxy API calls to `:8000`.

**Subsequent deploys.** Run `bin/deploy.sh` on the server. It pulls the latest code, installs frontend deps, **rebuilds `frontend/dist/`**, and restarts the backend — in that order.

```bash
bin/deploy.sh
# override the service name if it isn't "cadence":
CADENCE_SERVICE=my-service bin/deploy.sh
```

> ⚠️ Do **not** deploy with `git pull && systemctl restart cadence` alone. The backend serves the UI from `frontend/dist/`, which is gitignored and built on the server — a plain pull updates the source but not `dist/`, so the **old UI keeps being served** until `npm run build` runs. `bin/deploy.sh` is that missing build step wrapped up so it can't be forgotten.

`users_credentials.json` is gitignored, so the pull never touches credentials. New ingested data (calls, leads, Owl convos) is committed back by the server's data-sync cron and arrives the next time anyone pulls.

**First Google Calendar connection.** `google_tokens.json` is not in the repo. From the Lead agent → "Connect Google Calendar" → completes OAuth → the token file is created automatically under `DATA_ROOT/agents/lead/data/`.

## Local development (Ivan)

Point `DATA_ROOT` at a path **outside** the repo so test writes never appear in `git status`. In `backend/.env`:

```
DATA_ROOT=/path/to/cadence-data
ADMIN_PASSWORD=<your dev password>
USER1_PASSWORD=...    # any value; only the accounts you want to log in as need passwords you remember
USER2_PASSWORD=...
```

Then:

```bash
# One-shot: seed the local DATA_ROOT with the committed snapshot,
# then write the local credentials file from .env.
bin/sync-from-repo.sh
cd backend && python seed_users.py
python main.py
```

Now log in as `ivan` with the password you just set. Anything the app writes (Owl convos, learnings, new leads, vault changes) lands in `~/cadence-data`, **not** in the repo working tree — `git status` stays clean while you experiment.

When the live server pushes new data back to git:

```bash
git pull
bin/sync-from-repo.sh   # refresh ~/cadence-data with the new data
# (your users_credentials.json is preserved)
```

Commit code only. Push. Your colleague pulls `main` on the live server and restarts; their credentials file is gitignored and untouched.

### Admin per-session sandbox (in-app)

Independent of the above, admins can flip a session-scoped sandbox toggle (`POST /api/admin/sandbox/enable`) to route writes for the active session into `_sandbox/` subdirs alongside the canonical paths. Use this to try a flow in a real deployment without polluting prod data. Disable to return to normal.

### Knowledge base

The vault and per-agent knowledge directories are committed as the **seed**. They live at runtime under `DATA_ROOT/`, not in the repo tree.

- `vault/` — three-pillar Cadence Knowledge (Obsidian-compatible)
- `agents/calls/knowledge/` — product docs, sales narratives, competitive positioning
- `agents/lead/knowledge/` — ICP definitions, campaign strategies, outreach playbooks

---

## Licence

MIT — see [LICENSE](LICENSE).
