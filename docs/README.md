# Cadence documentation

Reference docs for the Cadence platform and each of its agents. Start with the
[architecture](architecture.md) for how the platform fits together, then dive
into a specific agent. To build your own agent, see the
[Agent Creator](agent-creator.md).

## Platform

- **[Architecture](architecture.md)** — layers, request lifecycle, auth & access
  control, the `DATA_ROOT` data model, the three-pillar knowledge vault, the
  shared Claude client, and the frontend conventions.
- **[Agent Creator](agent-creator.md)** — scaffold a new agent from a spec, the
  shared helpers every agent reuses, and the wiring it touches.

## Agents

| Agent | Track | What it does |
|---|---|---|
| [Calls](agents/calls.md) | Sales / GTM | Analyse call transcripts → signals, objections, learnings, quizzes |
| [Lead](agents/lead.md) | Sales / GTM | Campaigns, prospect X-Ray, outreach sequences, calendar |
| [Owl](agents/owl.md) | Sales / GTM | Grounded chat with model routing + correction capture |
| [High-Intent](agents/high-intent.md) | Sales / GTM | LinkedIn intent signals → outreach (admin sandbox) |
| [Meet](agents/meet.md) | Sales / GTM | Google Meet transcript capture (feeds Calls) |
| [Duty & Tax](agents/duty.md) | Operations | Autonomous shipment duty/VAT landed-cost estimation |
| [Onboarding](agents/onboarding.md) | Both | Role-aware guided onboarding chat |
| [Forecasting](agents/forecast.md) | Operations | Pipeline analytics, weighted forecast, hygiene, + the **Pipeline Manager** morning briefing |

## Conventions used in these docs

- Endpoint paths include the router prefix (e.g. `POST /api/forecast/sync`).
- "Per-user scoped" means data is filtered by the authenticated `username`.
- "Sandbox" refers to the admin per-session sandbox that routes writes into
  `_sandbox/` directories (see [architecture](architecture.md#sandbox)).
- All mutable state lives under `DATA_ROOT` and is never committed — this repo is
  code and structure only.
