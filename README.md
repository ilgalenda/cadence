# Cadence

An internal AI-powered sales intelligence system built on Claude. Cadence gives sales and GTM teams three purpose-built agents — for analysing customer calls, managing lead pipelines, and asking questions — backed by a shared knowledge vault that grows with every interaction.

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
- Streams a structured analysis: buying signals, objections raised, product fit, suggested follow-up actions, and rep coaching notes
- Extracts atomic learnings from each call and stores them per-user
- Learnings accumulate over time into a personal knowledge layer, injected into future sessions as context
- Grounded in a product knowledge base and glossary loaded at runtime from the `knowledge/` directory

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

---

## Shared Vault

Every agent writes to a shared vault at `backend/vault/`. It is a valid [Obsidian](https://obsidian.md) vault — open the directory directly to browse it.

Structure:
```
backend/vault/
├── calls/          # one .md file per analysed call
├── lead/           # campaign and prospect intelligence
└── knowledge/
    ├── glossary/   # terms written by the Calls agent
    └── entities/   # auto-linked product and protocol entities
```

Entries use YAML-ish frontmatter and `[[wikilinks]]` for cross-referencing. Attribution (which user, which session) is preserved in frontmatter but the knowledge belongs to the system — all agents read from it.

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
│   │   │   ├── routes.py          # Upload, analysis, glossary, learnings endpoints
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
│   │   │   ├── routes.py          # Chat stream + session history endpoints
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

## Getting started

**Prerequisites:** Python 3.11+, Node 18+, an [Anthropic API key](https://console.anthropic.com).

```bash
# 1. Clone
git clone https://github.com/ilgalenda/cadence.git
cd cadence

# 2. Backend
cd backend
cp .env.example .env          # fill in ANTHROPIC_API_KEY and SESSION_SECRET
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python seed_users.py          # creates backend/agents/users.json
python main.py                # starts on http://localhost:8000

# 3. Frontend (separate terminal)
cd frontend
npm install
npm run build                 # or `npm run dev` for hot reload on :4321
```

The backend serves the built frontend from `frontend/dist/` at `/`. In development, run the Astro dev server separately and proxy API calls to `:8000`.

### Knowledge base

The agents are grounded in markdown knowledge files that you provide. Place them in:

- `backend/agents/calls/knowledge/` — product docs, sales narratives, competitive positioning
- `backend/agents/lead/knowledge/` — ICP definitions, campaign strategies, outreach playbooks

The vault at `backend/vault/` will populate automatically as the agents run.

---

## Licence

MIT — see [LICENSE](LICENSE).
