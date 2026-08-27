"""Capability services — the shared skills Cadence agents compose.

Phase 2 of the migration (see the Cadence Migration Plan). A capability service
is a single, well-scoped skill an agent calls, owned here rather than duplicated
inside each agent's module. The conventions every service follows:

  * One job. A service does one thing (score a lead, select a campaign, discover
    people on the web, enrich a contact) and exposes a small, typed contract.
  * Compose the Mind, never raw Anthropic. LLM-backed services call
    ``agents.mind`` (classify / compose / analyze / research); they never build
    their own Anthropic client. Deterministic services take no LLM at all.
  * Stateless where possible. Persistence and orchestration stay with the agent;
    a service transforms inputs to outputs.

Services are extracted from the ``lead`` / ``high_intent`` god-modules one at a
time (strangler-fig), so the running app keeps working throughout.
"""
