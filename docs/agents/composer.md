# Composer

| | |
|---|---|
| **Module** | `backend/agents/sales/composer/` |
| **Routes** | `/api/sales/composer` |
| **Mind profile** | `compose` |
| **Human gate** | review queue, then a Gmail draft |

**Prompts: withheld.** The module ships with its signatures and docstrings; the prompt bodies are proprietary and raise `NotImplementedError` in this build. Everything else — the orchestration, the schema, the gates — is real code.

---

Canon's contract: *generate the outreach touches across email · LinkedIn · call, in
Owl's voice, grounded in Research + Campaign Intelligence*. Two passes — draft, then
refine — with the per-user style overlay on both, so the order is draft → Owl-voice
→ how this person actually writes. They send it as themselves; that is what the
overlay is for.

Both of canon's groundings are real now. Research says what is true about *this*
account; Campaign Intelligence says what this *market* has already told us. The
outline is optional and the touches degrade without it rather than refusing, so a
path that skips Campaign Intelligence still walks.

**Nothing here sends anything, and now it does not have to.** Every composition is
filed to the review queue as pending, which is canon's primary review gate. On
approval, Phase 4a puts the **email** touch into the person's Gmail as a draft
(`services/mail_draft`); LinkedIn and call touches have no mailbox to land in and stay
text to copy. They press send either way — the grant cannot send.

Only the channels asked for are generated. The requested mix decides the JSON shape
the model is given, because asking for a shape you do not want is how an unasked-for
channel ends up in the output.

`agents/services/outreach.py` does the work of composing — this module decides what
to ask for, refuses what came back wrong, and records the decision trail.

---

*Generated from the module docstring by `tools/build-agent-docs.py`. Edit the code, not this page.*
