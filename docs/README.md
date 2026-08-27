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
- **[Operations](operations.md)** — the four v1 agents kept for part two, and
  what integrating them onto the Mind involves.
- **[Agent Creator](agent-creator.md)** — the v1 scaffolding tool, retained as
  part of the record.

## The eleven sales agents

Each one has a single job and is registered as a tool on Owl, so a user can name
it or let Owl pick it.

| Agent | Job | Prompts in this build |
|---|---|---|
| [Lead Scoring](agents/scoring.md) | How hot is this lead, and why — score deterministic, reading by model | **yes** |
| [GTM](agents/gtm.md) | Propose accounts worth approaching; fast, unverified, checked downstream | **yes** |
| [X-ray](agents/xray.md) | Given an account and why it matters, find the people | **yes** |
| [Research](agents/research.md) | The brief you read before writing anything | withheld |
| [Campaign Intelligence](agents/campaign-intelligence.md) | What this market already told us | withheld |
| [Campaign Selection](agents/campaign-selection.md) | The campaign shape — rules, no model at all | withheld |
| [Composer](agents/composer.md) | The outreach touches, for a human to send | withheld |
| [Call Analysis](agents/call-analysis.md) | A transcript, read as a colleague would read it | withheld |
| [Recap](agents/recap.md) | The follow-up email, for a human to send | withheld |
| [Knowledge Capture](agents/knowledge-capture.md) | What a call taught the company, written down | withheld |
| [Signals](agents/signals.md) | The watchlist that notices things | withheld |

## Conventions

- Endpoint paths include the router prefix (e.g. `POST /api/sales/gtm/identify`).
- "Per-user scoped" means data filtered by the authenticated `username`.
- All mutable state lives under `DATA_ROOT` and never enters git — see
  [architecture](architecture.md).
- Agent pages are generated from their module docstrings by
  `tools/build-agent-docs.py`. Edit the code, not the page.
