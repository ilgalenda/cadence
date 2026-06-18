# Cadence — an Agentic GTM Platform

Cadence gives sales and GTM teams purpose-built AI agents backed by a shared knowledge vault that grows with every interaction. Analyse calls, run prospect pipelines, and chat with an assistant that learns from both.

This repository is the **open architecture**, not a turnkey product with data inside. Clone it, point it at your own Anthropic key and your own knowledge, seed your own users, and you have your own system. It ships **code and structure only** — no vault content, no runtime data, no user records.

> **What's included vs what you bring.** The repo contains the application, the agent logic, and an empty vault/knowledge skeleton. The knowledge vault, agent runtime state (campaigns, leads, sessions, learnings), and user accounts are **created at runtime under your `DATA_ROOT`** — see [Where runtime data lives](#where-runtime-data-lives) and [Getting started](#getting-started). Nothing proprietary is committed here.

The example domain throughout (a timing-technology sales team) is just illustrative — Cadence is domain-agnostic. Swap in your own product knowledge and personas and it adapts.

---

## System overview

```
┌───────────────────────────────────────────────────────────────────┐
│                           Astro Frontend                            │
│    Dashboard · Calls · Lead · Owl · Duty · Onboarding · Forecast    │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ REST + SSE (streaming)
┌──────────────────────────────▼──────────────────────────────────────┐
│                          FastAPI Backend                            │
│                                                                     │
│   Sales / GTM                          Operations                   │
│   ┌───────┐ ┌──────┐ ┌─────┐    ┌──────┐ ┌────────────┐ ┌──────────┐│
│   │ Calls │ │ Lead │ │ Owl │    │ Duty │ │ Onboarding │ │ Forecast ││
│   └───┬───┘ └──┬───┘ └──┬──┘    └──┬───┘ └─────┬──────┘ └────┬─────┘│
│       └────────┴────────┴─────┬────┴───────────┴─────────────┘      │
│                               │                                     │
│          ┌────────────────────▼─────────────────────┐              │
│          │                Shared Vault               │              │
│          │              (Obsidian-compat.)           │              │
│          └───────────────────────────────────────────┘              │
│                                                                     │
│   Agent Creator (CLI) → scaffolds new agents from a spec            │
│   Duty & Forecast also call swappable external connectors           │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                 ┌─────────────▼──────────────┐
                 │         Anthropic API        │
                 │       Haiku 4.5 · Sonnet      │
                 └──────────────────────────────┘
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

### Duty & Tax

Autonomous shipment landed-cost estimation for operations teams.

- Describe a shipment in plain language and the agent classifies the HS code, looks up duty/VAT rates, and computes the breakdown via a tool-use loop — or enter the figures directly for a deterministic quote
- The arithmetic (`agents/duty/calc.py`) and the rates (`agents/duty/rates.py`) are deterministic local functions; the model only orchestrates and explains
- Rates come from a swappable `DutyRateProvider` — a generic sample table ships by default; implement the interface against a real tariff/customs API to go live

### Onboarding

A role-aware guided chat for new sales and ops users.

- Grounded in the shared knowledge vault and an editable onboarding curriculum (`agents/onboarding/curriculum.md`)
- Picks a track (sales / GTM or operations) and walks newcomers through the platform one step at a time, with a per-user progress checklist

### Forecasting

Pipeline, hygiene, and revenue analysis.

- Pipeline split by vertical and stage, a probability-weighted revenue forecast, and pipeline-hygiene flags (stale deals, missing amounts/close dates, past-due closes)
- Deals are pulled from a swappable `CRMConnector` — a mock HubSpot connector with sample data ships by default; implement the interface (OAuth shape mirrors the Lead agent's Google Calendar connector) to connect a real CRM

---

## Cadence Knowledge — three-pillar architecture

Every agent writes to and reads from a shared vault at `${DATA_ROOT}/vault/`. It is a valid [Obsidian](https://obsidian.md) vault — open the directory directly to browse the full knowledge graph. `[[wikilinks]]` cross pillar boundaries freely, so Obsidian renders the three pillars as a single connected graph.

The vault is split into three pillars, each with a distinct lifecycle:

```
vault/
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

**Pillar 1 — Company Truth.** Hand-curated, canonical knowledge for your organisation — products, protocols, research. Locked: the runtime never writes here. New folders are dropped into `company/` and normalised with `python3 backend/scripts/normalise_company_truth.py`, which adds the `tier: company`, `locked: true`, `description`, and `[[wikilink]]` injection in place. Idempotent — safe to re-run. This is the pillar you populate to make Cadence your own.

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
│   ├── main.py                     # FastAPI app, auth middleware, router mounting
│   ├── auth.py                     # Login, session, role + per-agent-access helpers
│   ├── paths.py                    # Resolves every mutable path under DATA_ROOT
│   ├── seed_users.py               # Seeds your user accounts + credentials
│   ├── .env.example                # Required environment variables
│   ├── requirements.txt
│   ├── agents/
│   │   ├── calls/                  # Call analysis, glossary, learnings, opt-in product fit
│   │   ├── lead/                   # Campaigns, prospecting, scoring, Google Calendar
│   │   ├── owl/                    # Grounded chat (SQLite), model routing, topics
│   │   ├── high_intent/            # LinkedIn intent signals + outreach (admin sandbox)
│   │   ├── meet/                   # Google Meet transcript capture
│   │   ├── duty/                   # Duty & Tax — calc.py, rates.py, tool-use routes
│   │   ├── onboarding/             # Role-aware guided chat + curriculum.md
│   │   ├── forecast/               # Pipeline analytics + crm.py connector
│   │   └── shared/
│   │       ├── vault.py            # Vault read/write, entity linking, frontmatter
│   │       ├── anthropic_client.py # Shared Claude client + rate-limit slot + model ids
│   │       ├── jsonstore.py        # Generic per-user JSON CRUD (used by new agents)
│   │       ├── jsonparse.py        # Tolerant JSON extraction from model output
│   │       └── notifications.py    # Admin email (approval flow)
│   ├── scripts/
│   │   ├── create_agent.py         # Agent Creator — scaffold a new agent from a spec
│   │   ├── templates/agent/        # Templates the generator renders
│   │   ├── specs/                  # Example agent specs (duty, onboarding, forecast)
│   │   └── normalise_company_truth.py
│   └── tests/                      # Deterministic unit tests (scoring, duty, forecast)
└── frontend/
    ├── src/
    │   ├── agents/                 # Per-agent UI config (name, tagline, nav)
    │   ├── pages/agents/           # calls · lead · owl · duty · onboarding · forecast
    │   ├── components/             # Shared UI (Owl drawer, page header, status dot)
    │   ├── layouts/                # AgentLayout, DashboardLayout, LoginLayout
    │   └── lib/                    # owlChat.ts (SSE client + markdown), leadCards.ts, version.ts
    └── astro.config.mjs
```

---

## Where runtime data lives

Cadence stores all mutable state (vault, leads, sessions, Owl conversations, `users.json`, `users_credentials.json`, etc.) under a directory named by the `DATA_ROOT` env var. **None of it is committed to this repo** — it is created the first time you run the app.

| Variable | Purpose | Default |
|---|---|---|
| `DATA_ROOT` | Root for all mutable state | `~/cadence-data` if unset; set it explicitly for production, e.g. `/srv/cadence/backend` |

Two files split the user model, and **neither is committed**:

- `${DATA_ROOT}/agents/users.json` — profiles (name, role, access, agents). Generate it from your own roster with `python backend/seed_users.py --rewrite-profiles` (edit `_DEFAULT_PROFILES` in that file first).
- `${DATA_ROOT}/agents/users_credentials.json` — per-environment bcrypt password hashes. Each machine runs `python backend/seed_users.py` once to populate it from the local `.env`.

> **Optional: data-in-git.** If you want a team to share live data through the repo, you can point `DATA_ROOT` at the repo's own `backend/` directory and run a cron that commits and pushes new data back — every clone then stays coherent. This is an advanced, opt-in pattern; keep your repo **private** if you do this, since the vault and runtime state then contain your real data. By default `DATA_ROOT` lives outside the repo and nothing operational is ever committed.

---

## Getting started

**Prerequisites:** Python 3.11+, Node 18+, an [Anthropic API key](https://console.anthropic.com/).

**Environment variables you supply (see `backend/.env.example`):**

| Variable | Where to get it |
|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com → Settings → API Keys |
| `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` (optional) | Google Cloud Console → APIs & Services → Credentials → Create OAuth client (Web). Only needed for the Lead agent's Calendar integration. Add `GOOGLE_REDIRECT_URI` to "Authorised redirect URIs" |
| `GOOGLE_REDIRECT_URI` (optional) | The deployment URL + `/api/lead/google/callback` (e.g. `https://your-deployment-host/api/lead/google/callback`) |
| `SESSION_SECRET` | Generate: `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `SMTP_*` (optional) | For admin approval emails. Gmail needs an App Password. The system degrades gracefully if unset |

**Steps:**

```bash
# 1. Clone
git clone https://github.com/ilgalenda/cadence.git
cd cadence

# 2. Backend env
cd backend
cp .env.example .env
# In .env, set at minimum:
#   DATA_ROOT=/path/to/cadence-data        (a directory OUTSIDE the repo)
#   SESSION_SECRET, ANTHROPIC_API_KEY
#   DEBUG=true                             (false in production)
#   A password per profile in seed_users.py, e.g. ADMIN_PASSWORD, USER1_PASSWORD
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Seed your users
#    --rewrite-profiles writes users.json from _DEFAULT_PROFILES (edit it first
#    for your own team). Drop the flag on later runs to refresh credentials only.
#    Both files land under DATA_ROOT and are gitignored.
python seed_users.py --rewrite-profiles

# 4. Start the backend
python main.py                # starts on http://localhost:8000

# 5. Frontend (separate terminal)
cd frontend
npm install
npm run dev                   # hot reload on :4321, proxies the API to :8000
```

For a production-style run, build the frontend once (`npm run build`) — the backend then serves the built UI from `frontend/dist/` at `/`.

You can now log in with one of the accounts you seeded (e.g. `admin` with the `ADMIN_PASSWORD` you set). Anything the app writes — Owl conversations, learnings, leads, vault changes — lands under your `DATA_ROOT`, so `git status` stays clean while you experiment.

### Make it your own

1. **Add product/company knowledge.** Drop markdown into `${DATA_ROOT}/vault/company/` (and `agents/calls/knowledge/`, `agents/lead/knowledge/`), then run `python3 backend/scripts/normalise_company_truth.py` to normalise frontmatter and wikilinks. This is what grounds every agent.
2. **Define your users.** Edit `_DEFAULT_PROFILES` in `backend/seed_users.py` and re-run `seed_users.py --rewrite-profiles`.
3. **Tune the agents.** Prompts live in `backend/agents/*/prompts.py`; Owl's model routing in `backend/agents/owl/routing.py`.
4. **Add your own agent.** Scaffold one from a small spec with the Agent Creator — it emits the backend dir, the frontend config + page, and all the wiring:
   ```bash
   python backend/scripts/create_agent.py --slug renewals --name "Renewals" \
     --tagline "Track and forecast renewals" --kind crud --entity renewal
   # or from a spec file: --spec backend/scripts/specs/<slug>.json  (add --dry-run to preview)
   ```

### Admin per-session sandbox (in-app)

Admins can flip a session-scoped sandbox toggle (`POST /api/admin/sandbox/enable`) to route writes for the active session into `_sandbox/` subdirs alongside the canonical paths. Use this to try a flow in a real deployment without polluting production data. Disable to return to normal.

### Connecting Google Calendar (optional)

`google_tokens.json` is never committed. In the Lead agent → "Connect Google Calendar" → complete OAuth → the token file is created automatically under `${DATA_ROOT}/agents/lead/data/`.

---

## Deploying

Run `bin/deploy.sh` on the server. It pulls the latest code, installs frontend deps, **rebuilds `frontend/dist/`**, and restarts the backend — in that order.

```bash
bin/deploy.sh
# override the service name if it isn't "cadence":
CADENCE_SERVICE=my-service bin/deploy.sh
```

> ⚠️ Do **not** deploy with `git pull && systemctl restart cadence` alone. The backend serves the UI from `frontend/dist/`, which is gitignored and built on the server — a plain pull updates the source but not `dist/`, so the **old UI keeps being served** until `npm run build` runs. `bin/deploy.sh` is that missing build step wrapped up so it can't be forgotten.

---

## Licence

MIT — see [LICENSE](LICENSE).
