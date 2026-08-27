"""The Owl tool registry — one declaration per sales agent.

Every agent is reachable two ways: through its own page, and by asking Owl. This
module is the second path, and it exists so an agent is **declared once**. A
registration carries the tool's schema *and* the function that runs it, so there
is no way to add a tool Owl can call but nothing can execute, or vice versa.

It plugs into machinery that already exists — `agents.mind.tooling.run_tool_loop`
drives tool dispatch for Owl's stream today — so making an agent conversational
is a registration, not a new loop.

Two rules the registry enforces on behalf of the platform:

- **Read-only by default.** A tool marked ``writes=False`` cannot change anything;
  it answers. Anything that produces a draft, spends credit or persists a record
  must declare ``writes=True`` and is surfaced to the user as an agent run rather
  than folded silently into a sentence.
- **Never sends.** No tool may perform the outward action — that is the platform's
  "agents draft, the human sends" rule, and it is structural here: the registry
  offers no way to express a send, so a tool cannot accidentally acquire one.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

# A tool's runner receives the calling user and the model's arguments, and returns
# the text that goes back into the conversation as the tool result.
ToolRunner = Callable[[str, dict], str]


@dataclass(frozen=True)
class SalesTool:
    """One agent, as Owl sees it."""

    name: str
    description: str
    input_schema: dict
    run: ToolRunner
    #: True when running this changes state — a draft, a persisted record, spend.
    writes: bool = False

    def spec(self) -> dict:
        """The Anthropic tool definition."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


_REGISTRY: dict[str, SalesTool] = {}


def register(tool: SalesTool) -> SalesTool:
    """Add an agent to the registry. Re-registering the same name is an error —
    two agents answering to one name is a bug, not a late override."""
    if tool.name in _REGISTRY:
        raise ValueError(f"sales tool {tool.name!r} is already registered")
    _REGISTRY[tool.name] = tool
    return tool


def get(name: str) -> Optional[SalesTool]:
    return _REGISTRY.get(name)


def names() -> list[str]:
    return sorted(_REGISTRY)


def specs() -> list[dict]:
    """Tool definitions for the model, in a stable order.

    Sorted by name so the serialised tool list is byte-stable between turns —
    an unstable ordering would invalidate the prompt cache for no reason.
    """
    return [_REGISTRY[name].spec() for name in sorted(_REGISTRY)]


def dispatch(username: str, name: str, arguments: dict) -> str:
    """Run a registered tool and return its result text.

    Never raises into the streaming loop: an unknown tool or a failing agent
    comes back as a sentence the model can relay, because a dropped exception
    mid-stream would strand the turn with no explanation for the user.
    """
    tool = _REGISTRY.get(name)
    if tool is None:
        return f"No agent named {name!r} is available."
    try:
        return tool.run(username, arguments or {})
    except Exception as e:  # noqa: BLE001 — the loop must survive any agent
        print(f"[sales.tools] {name} failed: {e}")
        return f"The {name} agent could not complete: {e}"


def reset_for_tests() -> None:
    """Empty the registry. Tests only — registration is import-time in the app."""
    _REGISTRY.clear()
