# Cadence

An agentic platform for sales and operations. Eleven purpose-built agents on a
shared brain: one governed gateway to the model, one voice, a three-pillar
knowledge vault, and per-user memory.

Built for Acme, the company I work for. Published here as an **architecture
showcase** — the knowledge vault, all operational data and the prompt library
stay private.

![Cadence home](docs/images/screen-cadence-home.png)

> **This is a showcase repository.** The architecture, the orchestration, the
> design system and three exemplar agents are here in full, working code. The
> other eight agents ship with their signatures, docstrings and contracts, and
> with their prompt bodies withheld.
>
> It is real code, and it checks out: `npm run build` runs the frontend tests,
> the design-system adherence gate and 28 routes; `pytest` runs green. What it
> will not do is useful work — the agents whose prompts are withheld cannot
> reason, and there is no vault content for them to reason over. Read it to see
> how the thing is built, not to run it.

---

## The idea

**Agents should be thin because the platform is thick.**

Reasoning, voice, knowledge and memory are platform services. What is left of an
agent is one job and the seam either side of it — which is why the modules are
short and the interesting code is in the layer underneath them.

```
┌──────────────────────────────────────────────────────────┐
│  Astro frontend — one shell, 26 pages                    │
└──────────────────────────┬───────────────────────────────┘
                           │ REST + SSE
┌──────────────────────────▼───────────────────────────────┐
│  FastAPI backend                                         │
│                                                          │
│   eleven sales agents — each one job, each a tool on Owl │
│                          │                               │
│   ┌──────────────────────▼──────────────────────────┐    │
│   │  OWL                                            │    │
│   │  Mind · Persona · Knowledge · Memory            │    │
│   └──────────────────────┬──────────────────────────┘    │
│                          │                               │
│   capability services · integrations                     │
└──────────────────────────┬───────────────────────────────┘
                           │
                  ┌────────▼────────┐
                  │  Anthropic API  │
                  └─────────────────┘
```

Read [the architecture](docs/architecture.md) for how that actually works.

---

## Two rules the platform enforces

1. **Agents draft and populate; the human always sends.** The Google grant is
   `gmail.compose` — it can create a draft, and can neither read the mailbox nor
   send. Google enforces the restraint, not our discipline.
2. **Every consequential step passes a human review gate.**

---

## The eleven agents

| | Job |
|---|---|
| **[Lead Scoring](docs/agents/scoring.md)** | How hot is this lead, and why. The score is deterministic — a model that could move the number would make the number meaningless |
| **[GTM](docs/agents/gtm.md)** | Propose accounts worth approaching. Fast and deliberately unverified; checking happens downstream where the path already puts it |
| **[X-ray](docs/agents/xray.md)** | Given an account and why it matters, find the people who could own the problem |
| **[Research](docs/agents/research.md)** | The brief you read before you write anything |
| **[Campaign Intelligence](docs/agents/campaign-intelligence.md)** | What this market already told us, before you write to it |
| **[Campaign Selection](docs/agents/campaign-selection.md)** | The shape of the campaign. No LLM call anywhere in the module |
| **[Composer](docs/agents/composer.md)** | The outreach touches, in Owl's voice, for a human to send |
| **[Call Analysis](docs/agents/call-analysis.md)** | A transcript, read the way a sales colleague would read it |
| **[Recap](docs/agents/recap.md)** | The follow-up the client gets, in writing, for a human to send |
| **[Knowledge Capture](docs/agents/knowledge-capture.md)** | What a call taught the company, written down |
| **[Signals](docs/agents/signals.md)** | The watchlist that notices things |

Lead Scoring, GTM and X-ray are published with their prompts intact.

---

## Operations — part two

Four v1 agents — Duty & Tax, Forecasting, Onboarding and Meet — are kept in this
repository on purpose. They predate the Owl Mind, still call the layer it
replaced, and are **not registered** in `backend/main.py`. Bringing them onto the
Mind is the next section of work.

See [Operations](docs/operations.md) for what that involves and why the old
client is still here.

---

## The design system

![The studio](docs/images/screen-owl-workspace.png)

One system across 26 pages — "the studio". `tokens.css` is the source of truth
and a build gate fails on raw `px`, so a value outside the system cannot quietly
appear in a page.

[See the whole thing](docs/design-system.md) — screens, colour, type, motion,
material, components.

---

## What is deliberately not here

| | Why |
|---|---|
| The knowledge vault's content | It is real company knowledge, and the architecture is the part worth showing. Ships as empty scaffolding |
| Call learnings, campaigns, sessions, the user roster | Operational data. It lives outside the repository entirely, under `DATA_ROOT` |
| The prompt library | The commercial edge. Eight agents keep their signatures, docstrings and contracts; the bodies raise `NotImplementedError` |
| Credentials of any kind | `.env.example` shows the shape; nothing else |

The boundary is mechanical rather than remembered — `tools/sync-from-internal.sh`
copies by allowlist and fails on anything not named in it, and
`backend/paths.py` routes every mutable path through `DATA_ROOT` so operational
writes never land in the working tree in the first place.

---

## Stack

Astro · Tailwind · FastAPI · Uvicorn · SQLite · the Anthropic API over SSE, with
Haiku, Sonnet and Opus routed per task by `agents/mind/registry.py`.

## Layout

```
backend/
  agents/
    mind/        the governed gateway: client, registry, governor, cache,
                 tooling, persona, memory, usage
    services/    deterministic capability: scoring, review, selection,
                 discovery, enrichment, outreach, style
    sales/       the eleven agents
    owl/         workspace: projects, threads, search
    learn/  wiki/  admin/
    duty/ forecast/ onboarding/     Operations — part two
  integrations/  Google OAuth, Gmail, Calendar, contact enrichment
  tests/         42 suites, green
frontend/src/
  design-system/ tokens, primitives, components, previews
  lib/           behaviour, with unit tests beside it
  pages/         the 26-page surface
docs/            architecture, design system, operations, per-agent pages
tools/           the publication boundary
```

## Licence

MIT. See [LICENSE](LICENSE).
