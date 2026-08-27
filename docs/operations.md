# Operations — part two

Cadence began as two tracks. The sales track became the platform described in
[the architecture](architecture.md): eleven thin agents on the Owl Mind. The
operations track did not make that journey yet.

Four agents sit here, kept in the repository on purpose:

| Agent | What it does |
|---|---|
| [Duty & Tax](agents/duty.md) | Landed-cost estimation for a shipment — duty, VAT, the lot |
| [Forecasting](agents/forecast.md) | Pipeline analytics, weighted forecast, hygiene, and the Pipeline Manager morning briefing |
| [Onboarding](agents/onboarding.md) | Role-aware guided onboarding chat |
| [Meet](agents/meet.md) | Google Meet transcript capture, feeding Call Analysis |

## Why they are not running

They predate the Owl Mind and were written against the layer it replaced. Each
one calls `agents.shared.anthropic_client` directly — its own model choice, its
own retries, its own response parsing. That is precisely the pattern the Mind
exists to remove, and it is why these routers are **not registered** in
`backend/main.py`: wiring them up as they are would put thirteen-call-sites-worth
of the old problem back into a platform that just finished consolidating it.

`agents/shared/anthropic_client.py` is kept in this repo for the same reason.
Deleting it would make the Operations code unreadable, and the dependency is the
clearest possible statement of what the integration work actually is.

## What is here, and what is not

The **agents and their tests** are here: `backend/agents/{duty,forecast,onboarding}/`
and `meet-extension/`, with `backend/tests/test_duty.py`, `test_forecast.py` and
`test_pipeline_manager.py`.

Their **v1 user interface is not**. Those pages sit outside the design system,
touch `document` at build time, and are the first thing a studio rebuild would
delete — carrying them would mean shipping a repository that does not build in
order to preserve markup nobody intends to keep. The backend is the part with
something to say.

## What integrating them means

For each agent, in rough order of effort:

1. Replace the direct `anthropic_client` call with the task-shaped `mind` API —
   `analyze` for the readings, `compose` for anything a human sends.
2. Move its prompts into the shared prompt library so they are reviewable and
   cache-stable alongside the rest.
3. Put its consequential steps behind `services/review.py`, so the platform rule
   holds here too.
4. Bring its pages onto the studio design system; they still use the v1 shell
   (`AgentLayout`, `PageHeader`, `StatusDot`).
5. Register the router in `backend/main.py`.

Forecasting is the interesting one. Its Pipeline Manager briefing is
**deterministic** — analytics, not generation — which means it is already aligned
with the platform's position that a number a model could move is a number worth
less. It needs the least changing and would come first.

## The Agent Creator

[`docs/agent-creator.md`](agent-creator.md) documents `backend/scripts/create_agent.py`,
which scaffolded these four from a JSON spec. It is retained as part of the
record. In practice it has been superseded: once agents became thin, the
scaffolding they needed shrank to a module docstring, a `run_as_tool` entry and a
router, and generating that from a template stopped paying for itself.
