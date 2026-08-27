# Knowledge Capture

| | |
|---|---|
| **Module** | `backend/agents/sales/knowledge_capture/` |
| **Routes** | `— surfaceless` |
| **Mind profile** | `analyze` |
| **Human gate** | staging automatic; promotion curated |

**Prompts: withheld.** The module ships with its signatures and docstrings; the prompt bodies are proprietary and raise `NotImplementedError` in this build. Everything else — the orchestration, the schema, the gates — is real code.

---

Canon's contract: *extract learnings + new glossary terms from a call → stage into
the vault (Dynamic Truth); promote proven ones to canon. Promotion to canon is
gated (curated); staging is automatic.*

Extracted from `run_call_analysis` in Stage 4, where it had been doing this work
inline. Splitting it out changes no behaviour and buys three things: Call Analysis
does one job, a failure to file learnings can no longer cost the analysis somebody
is waiting for, and the staging rules are somewhere you can read them.

**Staging is automatic, into Dynamic Truth, and that is canon's design.** Learnings
go to `dynamic/calls/` via `vault.write_learning`; new terms go to
`dynamic/glossary/` via `vault.write_glossary_term`. Neither is gated, deliberately:
Dynamic Truth *is* the staging tier — the place things live while they earn their
way further — and requiring approval to stage would mean nothing ever got staged.

**The gate canon asks for is the next tier up, and it is not built.** "Promote proven
ones to canon" means `dynamic/` → the canon tier, which is a curation pass over
accumulated Dynamic Truth rather than a per-call decision. Cadence's vault has no
writer for its canon tier (`company/`) at all, so there is nothing here to gate yet.
It is named in the roadmap rather than faked with an approval queue that would
promote nothing. Note the **Added pillar** (`added/pending` → admin) is a different
mechanism for a different thing — user corrections to Owl — and filing a term
definition into it would render as "Owl said: —".

**A term is written once.** `write_glossary_term` skips a slug that already exists in
either the seed or the dynamic glossary, so re-analysing a call that mentions PTP
does not produce a second PTP page.

---

*Generated from the module docstring by `tools/build-agent-docs.py`. Edit the code, not this page.*
