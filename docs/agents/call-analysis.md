# Call Analysis

| | |
|---|---|
| **Module** | `backend/agents/sales/call_analysis/` |
| **Routes** | `/api/sales/calls` |
| **Mind profile** | `analyze` |
| **Human gate** | none — a reading |

**Prompts: withheld.** The module ships with its signatures and docstrings; the prompt bodies are proprietary and raise `NotImplementedError` in this build. Everything else — the orchestration, the schema, the gates — is real code.

---

Canon's contract: *pasted transcript → structured read: summary, buying signals,
objections, talking points, product-fit*. Trigger: the user pastes a transcript
(Granola transcribes externally). No review gate — it is a reading, not something a
customer sees.

Migrated out of `agents/calls` in Stage 4. Two things changed in the move.

**It stopped doing three other agents' jobs.** The old `run_call_analysis` analysed
the transcript *and* wrote learnings to the vault *and* wrote new glossary terms —
Knowledge Capture's work, done inline and ungated. That now belongs to
`sales/knowledge_capture`, which this module calls once and does not depend on: a
failure to file learnings must not lose the analysis the person is waiting for.

**It became reachable two ways.** It had a page but had never been an Owl tool, so
"analyse this call" was the one agent you could not ask for.

The vault prefix here is **transcript-scoped and deliberately uncached**
(`load_vault_for_analysis`): the scoped prefix differs per call, so caching would buy
the 1.25x write surcharge and no read benefit. That reasoning moved with the code
because it is the reason the prefix is ~30k tokens rather than ~130k.

---

*Generated from the module docstring by `tools/build-agent-docs.py`. Edit the code, not this page.*
