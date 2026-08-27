"""Characterise the dynamic chat router (agents/owl/routing.py select_model).

Asserts against the routing module's own model symbols, NOT literal IDs, so the
test stays green when Owl Core upgrades those constants to the current model
generation.
"""
from agents.owl import routing


def _sonnet():
    return routing.SONNET_MODEL


def _haiku():
    return routing.HAIKU_MODEL


def test_long_message_routes_to_sonnet():
    long = "x" * 121
    assert routing.select_model(long) == _sonnet()


def test_short_lookup_routes_to_haiku():
    assert routing.select_model("what is PTP?") == _haiku()


def test_strong_keyword_routes_to_sonnet():
    for phrase in [
        "analyze this",
        "compare the two",
        "recommend an approach",
        "help me understand",
        "linkedin outreach",
        "prepare for the call",
    ]:
        assert routing.select_model(phrase) == _sonnet(), phrase


def test_single_weak_signal_stays_haiku():
    # One weak signal alone must not over-trigger.
    assert routing.select_model("why PTP?") == _haiku()


def test_two_weak_signals_route_to_sonnet():
    assert routing.select_model("why does the protocol matter?") == _sonnet()


def test_default_is_haiku():
    assert routing.select_model("hello") == _haiku()
