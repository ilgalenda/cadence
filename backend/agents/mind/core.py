"""The Owl Core "Mind" — the task-shaped gateway every agent composes.

Agents call `classify / compose / analyze / chat / chat_stream / research` instead
of touching the Anthropic SDK. Each method resolves a task profile (model tier,
max_tokens, thinking, backoff), never sends sampling params or budget_tokens,
logs usage at the correct per-model rate, and routes through the one shared
client. See registry.py for the profile table and the model generation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterator, Optional

from agents.mind import tooling, usage
from agents.mind.client import get_client, with_backoff
from agents.mind.registry import (
    MODELS,
    TASK_PROFILES,
    Tier,
    build_thinking,
    tier_for,
)
from agents.shared import jsonparse

# Current-generation web search tool (dynamic filtering; supported on the tiers
# in the registry). Callers may override per research task.
DEFAULT_WEB_SEARCH_TYPE = "web_search_20260209"


@dataclass
class LLMResult:
    text: str
    message: object
    stop_reason: Optional[str]

    @classmethod
    def from_message(cls, message) -> "LLMResult":
        return cls(
            text=tooling.text_of(message).strip(),
            message=message,
            stop_reason=getattr(message, "stop_reason", None),
        )

    def json(self):
        return jsonparse.parse_json(self.text)

    def json_array(self):
        return jsonparse.parse_json_array(self.text)


def _single(*, task: str, model: str, max_tokens: int, system, messages) -> LLMResult:
    """One-shot (non-agentic) request with the profile's backoff policy."""
    profile = TASK_PROFILES[task]
    thinking = build_thinking(tier_for(model), profile.thinking)
    kwargs = tooling.build_kwargs(
        model=model,
        max_tokens=max_tokens,
        messages=messages,
        system=system,
        thinking=thinking,
    )
    client = get_client()

    def _call():
        return client.messages.create(**kwargs)

    message = with_backoff(_call) if profile.long_backoff else _call()
    usage.record(task, getattr(message, "usage", None), model)
    return LLMResult.from_message(message)


def _collect(events: Iterator[dict]) -> LLMResult:
    """Drain a run_tool_loop generator into a single LLMResult."""
    text_parts: list[str] = []
    last_message = None
    last_stop = None
    for ev in events:
        if ev["type"] == "text":
            text_parts.append(ev["text"])
        elif ev["type"] == "final":
            last_message = ev["message"]
            last_stop = ev["stop_reason"]
    return LLMResult(
        text="".join(text_parts).strip(),
        message=last_message,
        stop_reason=last_stop,
    )


# --------------------------------------------------------------------------- #
# Single-shot task methods
# --------------------------------------------------------------------------- #
def classify(*, system, messages, max_tokens: Optional[int] = None) -> LLMResult:
    p = TASK_PROFILES["classify"]
    return _single(
        task="classify",
        model=MODELS[p.tier],
        max_tokens=max_tokens or p.default_max_tokens,
        system=system,
        messages=messages,
    )


def compose(*, system, messages, max_tokens: Optional[int] = None) -> LLMResult:
    p = TASK_PROFILES["compose"]
    return _single(
        task="compose",
        model=MODELS[p.tier],
        max_tokens=max_tokens or p.default_max_tokens,
        system=system,
        messages=messages,
    )


def analyze(
    *,
    system,
    messages,
    images: Optional[list[dict]] = None,
    max_tokens: Optional[int] = None,
) -> LLMResult:
    """Structured analysis. `images` = [{"data": <b64>, "media_type": <mime>}],
    prepended as image blocks before the text of the first user message.
    """
    p = TASK_PROFILES["analyze"]
    msgs = _with_images(messages, images) if images else messages
    return _single(
        task="analyze",
        model=MODELS[p.tier],
        max_tokens=max_tokens or p.default_max_tokens,
        system=system,
        messages=msgs,
    )


# --------------------------------------------------------------------------- #
# Agentic / streaming task methods
# --------------------------------------------------------------------------- #
def chat(
    *,
    system,
    messages,
    tools=None,
    tool_dispatch: Optional[Callable[[str, dict], str]] = None,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
    max_rounds: int = 4,
) -> LLMResult:
    """Non-streaming agentic chat with a client-tool loop (e.g. campaign builder)."""
    p = TASK_PROFILES["chat"]
    resolved = model or MODELS[p.tier]
    return _collect(
        tooling.run_tool_loop(
            client=get_client(),
            stream=False,
            model=resolved,
            system=system,
            messages=messages,
            tools=tools,
            tool_choice=None,
            tool_dispatch=tool_dispatch,
            thinking=build_thinking(tier_for(resolved), p.thinking),
            max_tokens=max_tokens or p.default_max_tokens,
            max_rounds=max_rounds,
            label="chat",
            usage_record=usage.record,
        )
    )


def chat_stream(
    *,
    system,
    messages,
    tools=None,
    tool_dispatch: Optional[Callable[[str, dict], str]] = None,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
    max_rounds: int = 4,
) -> Iterator[dict]:
    """Streaming chat. Returns a *sync* iterator of {"type":"text"|"final",...}
    events, usable inside the existing `async def generate()` SSE blocks.
    Handles the max_tokens continuation so replies are never hard-cut.
    """
    p = TASK_PROFILES["chat"]
    resolved = model or MODELS[p.tier]
    return tooling.run_tool_loop(
        client=get_client(),
        stream=True,
        model=resolved,
        system=system,
        messages=messages,
        tools=tools,
        tool_choice=None,
        tool_dispatch=tool_dispatch,
        thinking=build_thinking(tier_for(resolved), p.thinking),
        max_tokens=max_tokens or p.default_max_tokens,
        max_rounds=max_rounds,
        label="chat",
        usage_record=usage.record,
    )


def research(
    *,
    system,
    messages,
    tool_choice: dict,
    max_uses: int,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
    max_rounds: int = 6,
    web_search_type: str = DEFAULT_WEB_SEARCH_TYPE,
) -> LLMResult:
    """Web-search research with the server-tool pause_turn loop. `model` is passed
    explicitly for high-intent detection (Opus); defaults to the profile tier.

    `web_search_type` selects the tool generation. The default carries dynamic
    filtering, which summarises results before the model sees them — right for
    research that wants a digest, wrong for discovery that has to read raw
    snippets (see `services.name_sources`).

    A truncated turn is reported, never continued: research answers with one
    terminal JSON document, and continuing would split it in half.
    """
    p = TASK_PROFILES["research"]
    resolved = model or MODELS[p.tier]
    tools = [{"type": web_search_type, "name": "web_search", "max_uses": max_uses}]
    return _collect(
        tooling.run_tool_loop(
            client=get_client(),
            stream=False,
            model=resolved,
            system=system,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            tool_dispatch=None,
            thinking=build_thinking(tier_for(resolved), p.thinking),
            max_tokens=max_tokens or p.default_max_tokens,
            max_rounds=max_rounds,
            label="research",
            usage_record=usage.record,
            continue_on_max_tokens=False,
        )
    )


def _with_images(messages: list, images: list[dict]) -> list:
    """Prepend image blocks before the text of the first user message."""
    image_blocks = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": img["media_type"],
                "data": img["data"],
            },
        }
        for img in images
    ]
    out = [dict(m) for m in messages]
    for m in out:
        if m.get("role") == "user":
            content = m["content"]
            if isinstance(content, str):
                m["content"] = image_blocks + [{"type": "text", "text": content}]
            else:
                m["content"] = image_blocks + list(content)
            break
    return out
