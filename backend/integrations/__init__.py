"""External API clients for Cadence.

Thin transport wrappers over third-party APIs (Lusha today; Gmail, HubSpot,
Slack in Phase 4). Clients own auth (keys from the environment) and HTTP; they
carry no business logic — the capability services in ``agents.services`` shape
their output into Cadence's domain.
"""
