# Cadence documentation

Start with [the architecture](architecture.md) — it explains the one idea the
rest of the system follows from. Then read an agent, or look at
[the design system](design-system.md).

## Platform

- **[Architecture](architecture.md)** — the four layers, the Owl Mind, the
  three-pillar vault, per-user memory, the deterministic services, the two
  platform rules, and the known limitations.
- **[The design system](design-system.md)** — "the studio": the position, the
  tokens, and the screens, rendered from the system's own preview pages.
- **[Running without a model](without-a-model.md)** — the event programme and
  the outbound tracker: two subsystems that run, are current, and deliberately
  reach no model at all.
- **[Operations](operations.md)** — the four v1 agents kept for part two, and
  what integrating them onto the Mind involves.
- **[Agent Creator](agent-creator.md)** — the v1 scaffolding tool, retained as
  part of the record.

## The eleven sales agents

Each one has a single job. Nine are registered as tools on Owl, so a user can
name one or let Owl pick; the other two are held back from this release.

The third column has three values. **yes** means the prompts are published
intact — three exemplar agents, so the prompt engineering is readable rather than
only described. *withheld* means the module ships with its signatures and
docstrings and the bodies raise `NotImplementedError`. *held back* means the
agent is finished and current but is not in this release at all: its router is
not mounted and Owl is not offered it. That is a different thing from
[Operations](operations.md), where the code predates the Mind and has not been
brought onto it.

| Agent | Job | Prompts in this build |
|---|---|---|
| [Lead Scoring](agents/scoring.md) | How hot is this lead, and why — score deterministic, reading by model | **yes** |
| [GTM](agents/gtm.md) | Propose accounts worth approaching; fast, unverified, checked downstream. Its tracker mode builds the classified list a campaign is worked from | **yes** |
| [X-ray](agents/xray.md) | Given an account and why it matters, find the people | **yes** |
| [Research](agents/research.md) | The brief you read before writing anything | *held back* |
| [Campaign Intelligence](agents/campaign-intelligence.md) | What this market already told us | withheld |
| [Campaign Selection](agents/campaign-selection.md) | The campaign shape — rules, no model at all | withheld |
| [Composer](agents/composer.md) | The outreach touches, for a human to send | withheld |
| [Call Analysis](agents/call-analysis.md) | A transcript, read as a colleague would read it | withheld |
| [Recap](agents/recap.md) | The follow-up email, for a human to send | withheld |
| [Knowledge Capture](agents/knowledge-capture.md) | What a call taught the company, written down | withheld |
| [Signals](agents/signals.md) | The watchlist that notices things | *held back* |

## Conventions

- Endpoint paths include the router prefix (e.g. `POST /api/sales/gtm/identify`).
- "Per-user scoped" means data filtered by the authenticated `username`.
- All mutable state lives under `DATA_ROOT` and never enters git — see
  [architecture](architecture.md).
- Agent pages are generated from their module docstrings by
  `tools/build-agent-docs.py`. Edit the code, not the page. The Operations pages
  and [Running without a model](without-a-model.md) are hand-written — those
  subsystems are not sales agents, and the generator reads only
  `backend/agents/sales/`.
