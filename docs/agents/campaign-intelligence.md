# Campaign Intelligence

| | |
|---|---|
| **Module** | `backend/agents/sales/campaign_intelligence/` |
| **Routes** | `/api/sales/intel` |
| **Mind profile** | `classify + analyze` |
| **Human gate** | none — preparation |

**Prompts: withheld.** The module ships with its signatures and docstrings; the prompt bodies are proprietary and raise `NotImplementedError` in this build. Everything else — the orchestration, the schema, the gates — is real code.

---

Canon's contract: *recall past conversations with clients in a similar vertical,
surface objections and pain points, and outline the relevant campaign angle to
inform selection*. No review gate — this is preparation, and it feeds Campaign
Selection and Composer rather than anything a customer sees.

This is the first agent that cashes in the vault's call learnings. Every other
agent that touches them reads a tag-scored slice; this one is *about* them.

**Two passes, and they do different jobs.** The corpus carries no vertical to
filter on, so retrieval is the hard part (the argument is in `index.py`). Pass one
shows the whole index of titles and asks which lines are worth reading — a
retrieval mechanic, so it runs on the cheap `classify` profile. Pass two does the
judgement canon specifies, on `analyze` (Sonnet), over only the bodies that were
picked. The cheap pass never sees a body, so it cannot synthesise from a title;
the expensive pass never sees the index, so it cannot cite a call it did not read.

**Read-only, deliberately.** It writes no vault entry, no memory row and no review
item. Canon gives it no gate and no persistence duty, and that is what makes it
safe for Owl to run mid-sentence. It *reads* Memory — `topics_for_vertical` — so
the outline knows what has already worked for this user, not just what the team
heard.

**It degrades rather than fails.** An empty shortlist, a market with no history, an
unparseable answer: each returns an outline that says so. The caller is usually a
path step with a person waiting at the end of it.

---

*Generated from the module docstring by `tools/build-agent-docs.py`. Edit the code, not this page.*
