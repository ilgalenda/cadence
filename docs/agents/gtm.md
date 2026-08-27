# GTM

| | |
|---|---|
| **Module** | `backend/agents/sales/gtm/` |
| **Routes** | `/api/sales/gtm` |
| **Mind profile** | `analyze` |
| **Human gate** | the user selects targets |

**Prompts: in this build.** This is one of the three exemplar agents, published with its prompts intact so the prompt engineering is readable, not just described.

---

One job: given an ICP, a vertical, or a seed company to find look-alikes of,
propose the accounts worth approaching. It proposes; **the user selects** — the
list is a review gate, not a queue that starts working on its own.

**Fast and deliberately unverified.** GTM proposes candidates from recall in a few
seconds; the checking happens downstream, where the path already puts it — the user
picks a company, and X-ray and the research brief (both of which do search the web)
establish whether it is real. Grounding GTM itself was tried and measured: the output
was excellent when it arrived, but it arrived about two times in five and took two to
five minutes, because a multi-minute non-streaming turn drops and an exhausted search
budget ends with no terminal text. A shortlist you cannot get beats nothing, but a
shortlist you can get and then check beats both.

The consequence is a duty of honesty, not just of speed: every entry carries what to
`check` and any `caveat`, and the page tells the user these are unverified.

**Gained the Signals layer in Phase 5.** When the user watches accounts, what
Signals has found is folded into the `notes` the prompt already reads as "a timing
signal to weight towards". With an empty watchlist the digest is empty and the prompt
is **byte-identical** to before Signals existed — the same guarantee Campaign
Intelligence and Gmail drafting were each built to preserve, so a feature nobody uses
costs nothing.

---

*Generated from the module docstring by `tools/build-agent-docs.py`. Edit the code, not this page.*
