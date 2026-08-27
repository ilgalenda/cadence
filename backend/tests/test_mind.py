"""Unit tests for the Owl Core Mind primitives, using a fake client (no SDK)."""
from types import SimpleNamespace

import pytest

from agents.mind import cache, governor, registry, tooling
from agents.mind import core as mind
from agents.mind.client import with_backoff


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
def _text_block(text):
    return SimpleNamespace(type="text", text=text)


def _tool_use_block(tool_id, name, tool_input):
    return SimpleNamespace(type="tool_use", id=tool_id, name=name, input=tool_input)


def _msg(blocks, stop_reason):
    return SimpleNamespace(content=blocks, usage=None, stop_reason=stop_reason)


class _FakeStreamCtx:
    def __init__(self, message):
        self._m = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def text_stream(self):
        return iter([tooling.text_of(self._m)])

    def get_final_message(self):
        return self._m


class _FakeMessages:
    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._scripted.pop(0)

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeStreamCtx(self._scripted.pop(0))


class _FakeClient:
    def __init__(self, scripted):
        self.messages = _FakeMessages(scripted)


def _noop_usage(label, usage, model):
    pass


def _drain(events):
    return list(events)


# --------------------------------------------------------------------------- #
# registry
# --------------------------------------------------------------------------- #
def test_registry_current_generation():
    assert registry.MODELS[registry.Tier.HAIKU] == "claude-haiku-4-5"
    assert registry.MODELS[registry.Tier.SONNET] == "claude-sonnet-5"
    assert registry.MODELS[registry.Tier.OPUS] == "claude-opus-4-8"


def test_tier_for_roundtrip_and_fallback():
    assert registry.tier_for("claude-sonnet-5") is registry.Tier.SONNET
    assert registry.tier_for("claude-sonnet-4-6") is registry.Tier.SONNET  # substring


def test_build_thinking_rules():
    assert registry.build_thinking(registry.Tier.HAIKU, "off") is None  # Haiku: omit
    assert registry.build_thinking(registry.Tier.SONNET, "off") == {"type": "disabled"}
    assert registry.build_thinking(registry.Tier.OPUS, "adaptive") == {"type": "adaptive"}


# --------------------------------------------------------------------------- #
# cache
# --------------------------------------------------------------------------- #
def test_cached_system_breakpoint_and_tail():
    blocks = cache.cached_system("PREFIX", "tail")
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in blocks[1]


def test_plain_system_has_no_cache_control():
    blocks = cache.plain_system("a", "b")
    assert all("cache_control" not in b for b in blocks)


# --------------------------------------------------------------------------- #
# tooling.run_tool_loop — both idioms + continuation
# --------------------------------------------------------------------------- #
def _loop(client, **over):
    base = dict(
        client=client,
        stream=False,
        model="claude-sonnet-5",
        system=None,
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        tool_choice=None,
        tool_dispatch=None,
        thinking=None,
        max_tokens=100,
        max_rounds=4,
        label="test",
        usage_record=_noop_usage,
    )
    base.update(over)
    return _drain(tooling.run_tool_loop(**base))


def test_tool_use_loop_dispatches_and_appends_result():
    client = _FakeClient(
        [
            _msg([_tool_use_block("tu1", "fetch", {"q": 1})], "tool_use"),
            _msg([_text_block("done")], "end_turn"),
        ]
    )
    seen = []
    events = _loop(
        client,
        tools=[{"type": "custom", "name": "fetch"}],
        tool_dispatch=lambda name, inp: seen.append((name, inp)) or "RESULT",
    )
    assert seen == [("fetch", {"q": 1})]
    # second request carried the tool_result user turn
    second = client.messages.calls[1]["messages"]
    assert second[-1]["role"] == "user"
    assert second[-1]["content"][0]["type"] == "tool_result"
    assert second[-1]["content"][0]["tool_use_id"] == "tu1"
    assert events[-1]["stop_reason"] == "end_turn"


def test_pause_turn_loop_reappends_assistant_only():
    client = _FakeClient(
        [
            _msg([_text_block("searching")], "pause_turn"),
            _msg([_text_block("answer")], "end_turn"),
        ]
    )
    _loop(client, tools=[{"type": "web_search_20260209", "name": "web_search"}])
    second = client.messages.calls[1]["messages"]
    # last appended turn is the assistant content, NOT a tool_result user turn
    assert second[-1]["role"] == "assistant"


def test_max_tokens_continuation_stitches_reply():
    client = _FakeClient(
        [
            _msg([_text_block("part one ")], "max_tokens"),
            _msg([_text_block("part two")], "end_turn"),
        ]
    )
    result = mind._collect(iter(_loop(client, stream=False)))
    assert result.text == "part one part two"
    second = client.messages.calls[1]["messages"]
    assert second[-1]["role"] == "user"  # the continue nudge


def test_streaming_yields_text_then_final():
    client = _FakeClient([_msg([_text_block("streamed")], "end_turn")])
    events = _loop(client, stream=True)
    assert events[0] == {"type": "text", "text": "streamed"}
    assert events[-1]["type"] == "final"


def test_loop_stops_at_max_rounds():
    # Always tool_use → must stop after max_rounds requests, not loop forever.
    scripted = [_msg([_tool_use_block(f"t{i}", "x", {})], "tool_use") for i in range(10)]
    client = _FakeClient(scripted)
    _loop(
        client,
        max_rounds=3,
        tools=[{"type": "custom", "name": "x"}],
        tool_dispatch=lambda n, i: "r",
    )
    assert len(client.messages.calls) == 3


# --------------------------------------------------------------------------- #
# build_kwargs — never leaks banned params
# --------------------------------------------------------------------------- #
def test_build_kwargs_omits_none_and_banned():
    kwargs = tooling.build_kwargs(
        model="claude-sonnet-5",
        max_tokens=100,
        messages=[],
        system=None,
        tools=None,
        thinking={"type": "disabled"},
    )
    assert "system" not in kwargs and "tools" not in kwargs
    assert kwargs["thinking"] == {"type": "disabled"}
    for banned in ("temperature", "top_p", "top_k", "budget_tokens"):
        assert banned not in kwargs


# --------------------------------------------------------------------------- #
# backoff
# --------------------------------------------------------------------------- #
def test_with_backoff_retries_then_succeeds(no_sleep):
    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ValueError("transient")
        return "ok"

    assert with_backoff(flaky, delays=(1, 1, 1), on=(ValueError,)) == "ok"
    assert attempts["n"] == 3


def test_with_backoff_reraises_after_exhausting(no_sleep):
    def always():
        raise ValueError("nope")

    with pytest.raises(ValueError):
        with_backoff(always, delays=(1,), on=(ValueError,))


# --------------------------------------------------------------------------- #
# governor
# --------------------------------------------------------------------------- #
def test_governor_slot_roundtrips():
    with governor.slot():
        pass
    with governor.slot():  # re-acquirable after release
        pass


def test_max_concurrency_default_is_one(monkeypatch):
    monkeypatch.delenv("MIND_MAX_CONCURRENCY", raising=False)
    assert governor._max_concurrency() == 1
    monkeypatch.setenv("MIND_MAX_CONCURRENCY", "junk")
    assert governor._max_concurrency() == 1
    monkeypatch.setenv("MIND_MAX_CONCURRENCY", "3")
    assert governor._max_concurrency() == 3


# --------------------------------------------------------------------------- #
# core single-shot request shape (through the real get_client via mock)
# --------------------------------------------------------------------------- #
def test_compose_request_shape(recording_anthropic):
    mind.compose(system=cache.cached_system("P"), messages=[{"role": "user", "content": "x"}])
    kwargs = recording_anthropic.only("create")
    assert kwargs["model"] == "claude-sonnet-5"
    assert kwargs["thinking"] == {"type": "disabled"}
    assert kwargs["max_tokens"] == 2048
    for banned in ("temperature", "top_p", "top_k", "budget_tokens"):
        assert banned not in kwargs


def test_classify_omits_thinking_on_haiku(recording_anthropic):
    mind.classify(system="cls", messages=[{"role": "user", "content": "x"}])
    kwargs = recording_anthropic.only("create")
    assert kwargs["model"] == "claude-haiku-4-5"
    assert "thinking" not in kwargs  # Haiku: never send thinking config


def test_analyze_prepends_image_before_text(recording_anthropic):
    mind.analyze(
        system=None,
        messages=[{"role": "user", "content": "describe"}],
        images=[{"data": "b64", "media_type": "image/png"}],
    )
    kwargs = recording_anthropic.only("create")
    content = kwargs["messages"][0]["content"]
    assert content[0]["type"] == "image"
    assert content[1] == {"type": "text", "text": "describe"}
