# Campaign Selection

| | |
|---|---|
| **Module** | `backend/agents/sales/campaign_selection/` |
| **Routes** | `/api/sales/campaign` |
| **Mind profile** | `none — deterministic` |
| **Human gate** | the selection is the gate |

**Prompts: withheld.** The module ships with its signatures and docstrings; the prompt bodies are proprietary and raise `NotImplementedError` in this build. Everything else — the orchestration, the schema, the gates — is real code.

---

Canon's contract: *compute the eligible campaign per the Campaign Playbook; the
user selects*. Deterministic, like Lead scoring — there is **no LLM call anywhere
in this module**. The archetype, the channel mix, the touch count and the four-week
structure are rules, and a model that could move them would make them arbitrary.

**The selection is the gate.** Canon says the human step *is* the choosing, so
there is no review queue to file into and nothing to persist: recomputing the same
plan from the same lead costs nothing, and a stored plan would only go stale
against a playbook that changes.

`agents/services/campaign_selection.py` holds the rules. This module's job is the
seam either side of them: turning what Lead scoring actually produced into the
inputs those rules demand, and reporting anything it had to assume.

**Why the seam needs care.** The scoring analysis is written by a model, and it
emits prose — `"Inbound action"`, `"Vertical fit"`, `"No signal"`. The service
takes `inbound_action` / `vertical_fit` / `no_signal` and **raises on anything
else**. Left implicit, a stray capital letter would either crash a path step or,
worse, be silently read as "no signal" and quietly pick the wrong archetype. So
normalisation is explicit here, and every fallback is named in `assumed` — a plan
that guessed its own inputs and did not say so is worse than one that admits it.

---

*Generated from the module docstring by `tools/build-agent-docs.py`. Edit the code, not this page.*
