# Lead Scoring

| | |
|---|---|
| **Module** | `backend/agents/sales/scoring/` |
| **Routes** | `/api/sales/leads` |
| **Mind profile** | `analyze` |
| **Human gate** | none — a reading |

**Prompts: in this build.** This is one of the three exemplar agents, published with its prompts intact so the prompt engineering is readable, not just described.

---

One job: given what a visitor did, say how hot they are and why. The score
itself is **deterministic** (`services.lead_scoring`) so it is reproducible and
tunable; the model's part is only to read the raw signal into a structured
analysis. Those two halves are kept apart deliberately — a model that could move
the number would make the number meaningless.

Order matters and is locked by test: the analysis is refined first, then scored,
so the score reflects the corrected reading rather than the first pass.

---

*Generated from the module docstring by `tools/build-agent-docs.py`. Edit the code, not this page.*
