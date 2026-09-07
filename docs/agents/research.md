# Research

| | |
|---|---|
| **Module** | `backend/agents/sales/research/` |
| **Routes** | `/api/sales/research` |
| **Mind profile** | `research` |
| **Human gate** | none — internal preparation |

**Not in this release.** The code is here and current — this is not a Phase 2 agent waiting to be brought onto the Mind. It is finished, and held back: its router is not mounted, it is not registered as a tool on Owl, and its page says so. Both agents held back drove a web-search turn that was compelled to call a tool after its search budget was spent, so the turn thrashed and never produced its answer — about two completions in five attempts. Its prompts are withheld with the rest.

---

Canon's contract: *deep research on the company as a whole plus the selected key
decision-maker(s) → one combined brief*. Company context, why timing matters now,
the product angle, then the person. No review gate: this is internal preparation,
and gating your own homework would only slow the person who asked for it.

Two things make it more than a web search.

**It starts from what the run already knows.** When Lead scoring has graded the
company, the whole verdict goes into the prompt — the signal strength, the inferred
product fit, the behaviour that drove the grade. The research then begins from the
real reason there is an opportunity instead of rediscovering it from a company name.
This is the same argument that justified paths existing at all.

**It writes back to Memory.** Canon says Research feeds Memory, and this is the
first agent that does: the account and its topic are recorded, so the next brief on
the same company — and every Owl conversation about it — starts warmer.

The product angle is grounded in the vault rather than left to the model's
recollection, because the portfolio is a fact about Acme and the vault is where
that fact lives.

---

*Generated from the module docstring by `tools/build-agent-docs.py`. Edit the code, not this page.*
