"""Exact model-ID pin — the intentional counterpart to the loose 'tier substring'
assertions in the request-shape tests. Update this file (and only this file)
deliberately when the platform's model generation changes.
"""
from agents.mind import registry
from agents.owl import routing


def test_registry_pins_current_generation():
    assert registry.MODELS == {
        registry.Tier.HAIKU: "claude-haiku-4-5",
        registry.Tier.SONNET: "claude-sonnet-5",
        registry.Tier.OPUS: "claude-opus-4-8",
    }


def test_chat_router_constants_track_registry():
    assert routing.HAIKU_MODEL == "claude-haiku-4-5"
    assert routing.SONNET_MODEL == "claude-sonnet-5"
