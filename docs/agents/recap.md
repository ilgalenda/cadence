# Recap

| | |
|---|---|
| **Module** | `backend/agents/sales/recap/` |
| **Routes** | `/api/sales/recap` |
| **Mind profile** | `compose` |
| **Human gate** | review queue, then a Gmail draft |

**Prompts: withheld.** The module ships with its signatures and docstrings; the prompt bodies are proprietary and raise `NotImplementedError` in this build. Everything else — the orchestration, the schema, the gates — is real code.

---

Canon's contract: *draft the client follow-up email — meeting summary + next steps
in writing*. Trigger: after Call Analysis. Owl · Sonnet. **Review gate before send.**

Two passes with the per-user style overlay on both, so the order is draft →
Owl-voice → how this person actually writes. They send it as themselves; that is
what the overlay is for. `services/outreach.two_pass` does the composing.

**Nothing here sends anything, and now it does not have to.** Every recap is filed
to the review queue as pending; on approval, Phase 4a puts a real draft in the
person's Gmail (`services/mail_draft`). They still press send — the grant cannot send,
so that is enforced by Google rather than by our restraint.

**Grounded in the reading, not the transcript.** The summary, the objections and the
agreed next steps are what a follow-up is made of, and Call Analysis has already
extracted them. Re-sending the transcript would pay for it twice and invite the model
to quote things nobody meant to be quoted.

---

*Generated from the module docstring by `tools/build-agent-docs.py`. Edit the code, not this page.*
