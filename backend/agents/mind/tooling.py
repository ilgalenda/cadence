"""Request construction and the unified multi-round loop.

`run_tool_loop` is the one place that knows how to continue a turn, branching on
`stop_reason`:

- `tool_use`  — a client tool was requested: append the assistant turn, run the
                dispatcher, append a user turn of tool_result blocks, continue.
- `pause_turn`— a server tool (web_search) paused: append the assistant content
                only (no tool_result) and continue.
- `max_tokens`— the reply was truncated: append the assistant partial and a user
                nudge to continue, so chat replies are never hard-cut mid-sentence.
                Callers whose answer is one terminal document (research: a single
                JSON array or object) pass `continue_on_max_tokens=False`, because
                continuing splits that document across two messages — leaving the
                caller a fragment that fails to parse for no visible reason. They
                want the truncation reported instead.
- anything else (`end_turn`, ...) — terminal; stop.

It is a generator yielding {"type":"text",...} deltas and a {"type":"final",...}
per round, so the streaming chat path can render incrementally while the
non-streaming callers (builder, research) collect the same events.
"""
from __future__ import annotations

from typing import Callable, Iterator, Optional

_CONTINUE_NUDGE = (
    "Continue exactly where you left off. Do not repeat anything already written."
)


def build_kwargs(
    *,
    model: str,
    max_tokens: int,
    messages: list,
    system=None,
    tools=None,
    tool_choice=None,
    thinking: Optional[dict] = None,
) -> dict:
    """Assemble create/stream kwargs. Never emits sampling params or budget_tokens."""
    kwargs: dict = {"model": model, "max_tokens": max_tokens, "messages": messages}
    if system is not None:
        kwargs["system"] = system
    if tools:
        kwargs["tools"] = tools
    if tool_choice is not None:
        kwargs["tool_choice"] = tool_choice
    if thinking is not None:
        kwargs["thinking"] = thinking
    return kwargs


def text_of(message) -> str:
    """Concatenate the text blocks of an SDK message."""
    parts = []
    for block in getattr(message, "content", None) or []:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", "") or "")
    return "".join(parts)


def run_tool_loop(
    *,
    client,
    stream: bool,
    model: str,
    system,
    messages: list,
    tools,
    tool_choice,
    tool_dispatch: Optional[Callable[[str, dict], str]],
    thinking: Optional[dict],
    max_tokens: int,
    max_rounds: int,
    label: str,
    usage_record: Callable[[str, object, str], None],
    continue_on_max_tokens: bool = True,
) -> Iterator[dict]:
    convo = list(messages)
    for _round in range(max_rounds):
        kwargs = build_kwargs(
            model=model,
            max_tokens=max_tokens,
            messages=convo,
            system=system,
            tools=tools,
            tool_choice=tool_choice,
            thinking=thinking,
        )

        if stream:
            with client.messages.stream(**kwargs) as s:
                for delta in s.text_stream:
                    yield {"type": "text", "text": delta}
                message = s.get_final_message()
        else:
            message = client.messages.create(**kwargs)
            chunk = text_of(message)
            if chunk:
                yield {"type": "text", "text": chunk}

        usage_record(label, getattr(message, "usage", None), model)
        stop_reason = getattr(message, "stop_reason", None)
        yield {"type": "final", "message": message, "stop_reason": stop_reason}

        if stop_reason == "tool_use":
            convo.append({"role": "assistant", "content": message.content})
            results = []
            for block in message.content:
                if getattr(block, "type", None) == "tool_use":
                    out = tool_dispatch(block.name, block.input) if tool_dispatch else ""
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": out,
                        }
                    )
            convo.append({"role": "user", "content": results})
            continue

        if stop_reason == "pause_turn":
            # Server tool (web_search) paused: re-send with the assistant content
            # appended and NO tool_result — the server resumes on its own.
            convo.append({"role": "assistant", "content": message.content})
            continue

        if stop_reason == "max_tokens" and continue_on_max_tokens:
            convo.append({"role": "assistant", "content": message.content})
            convo.append({"role": "user", "content": _CONTINUE_NUDGE})
            continue

        break  # end_turn / stop_sequence / refusal / anything terminal
