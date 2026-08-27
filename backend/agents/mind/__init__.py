"""Owl Core — the "Mind": the shared, governed LLM gateway every agent composes.

Public surface:
    from agents.mind import core as mind
    mind.classify(...) / mind.compose(...) / mind.analyze(...)
    mind.chat(...) / mind.chat_stream(...) / mind.research(...)

Model generation and per-task config live in `agents.mind.registry`.
Concurrency governor: `agents.mind.governor.slot()`.
Prompt-cache helpers: `agents.mind.cache`.
"""
from agents.mind import cache, core, governor, registry
from agents.mind.core import LLMResult

__all__ = ["core", "cache", "governor", "registry", "LLMResult"]
