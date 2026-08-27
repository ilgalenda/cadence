"""Shared test fixtures for the backend test suite.

The characterisation tests lock the deterministic seams and the *request shape*
each agent constructs — not model output (which is non-deterministic and, during
the Owl Core migration, deliberately changing model). `recording_anthropic`
mocks the SDK boundary that every call site uses (`anthropic.Anthropic`), so the
same structural assertions hold before and after a call site is repointed at the
Owl Core Mind.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

# Make `agents`, `paths`, etc. importable without per-file sys.path hacks.
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@pytest.fixture(autouse=True)
def anthropic_key(monkeypatch):
    """Every call site reads ANTHROPIC_API_KEY at construction; give it one."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")


@pytest.fixture
def no_sleep(monkeypatch):
    """Neutralise retry backoff sleeps so retry-path tests don't wait 10/30/60s."""
    monkeypatch.setattr(time, "sleep", lambda *a, **k: None)


def _canned_usage():
    return SimpleNamespace(
        input_tokens=10,
        output_tokens=5,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )


class _StreamCtx:
    """Minimal stand-in for the SDK's streaming context manager."""

    def __init__(self, recorder):
        self._rec = recorder

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def text_stream(self):
        return iter(self._rec.stream_deltas)

    def get_final_message(self):
        text = "".join(self._rec.stream_deltas)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=text)],
            usage=_canned_usage(),
            stop_reason=self._rec.stop_reason,
        )


class _Recorder:
    """Captures every SDK call's kwargs and serves deterministic canned responses.

    Tests read `.calls` — a list of (method_name, kwargs) — to assert the request
    shape a call site constructs. Tune `create_text` / `stream_deltas` /
    `stop_reason` per test when the parsed content matters.
    """

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.create_text = "{}"
        self.stream_deltas = ["hello ", "world"]
        self.stop_reason = "end_turn"

    # --- the mocked client surface ---
    def create(self, **kwargs):
        self.calls.append(("create", kwargs))
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self.create_text)],
            usage=_canned_usage(),
            stop_reason=self.stop_reason,
        )

    def stream(self, **kwargs):
        self.calls.append(("stream", kwargs))
        return _StreamCtx(self)

    # --- helpers for assertions ---
    def only(self, method: str = "create") -> dict:
        """Return the kwargs of the single call of `method` (asserts exactly one)."""
        matches = [kw for m, kw in self.calls if m == method]
        assert len(matches) == 1, f"expected 1 {method} call, got {len(matches)}"
        return matches[0]


@pytest.fixture
def recording_anthropic(monkeypatch):
    """Patch `anthropic.Anthropic` so any call site gets the recorder as its client.

    Also resets the Owl Core Mind client singleton (once it exists) so it picks
    up the patched constructor rather than a client built in an earlier test.
    """
    import anthropic

    recorder = _Recorder()

    def _factory(*args, **kwargs):
        return SimpleNamespace(messages=recorder)

    monkeypatch.setattr(anthropic, "Anthropic", _factory)

    try:  # Mind may not exist yet at Step 1; ignore if absent.
        from agents.mind import client as mind_client

        mind_client._reset_client_for_tests()
    except Exception:
        pass

    return recorder
