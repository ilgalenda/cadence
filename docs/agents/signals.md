# Signals

| | |
|---|---|
| **Module** | `backend/agents/sales/signals/` |
| **Routes** | `/api/sales/signals` |
| **Mind profile** | `research` |
| **Human gate** | none — a monitor |

**Not in this release.** The code is here and current — this is not a Phase 2 agent waiting to be brought onto the Mind. It is finished, and held back: its router is not mounted, it is not registered as a tool on Owl, and its page says so. Both agents held back drove a web-search turn that was compelled to call a tool after its search budget was spent, so the turn thrashed and never produced its answer — about two completions in five attempts. Its prompts are withheld with the rest.

---

Canon's contract: *a scheduled monitor over a target-account watchlist for funding
rounds and timing technographics; feeds GTM. A lean monitor, not a `high_intent`
rebuild.*

Two shapes of question live here, and they used to live apart.

**Account-shaped** — "what happened at *this named company*" — is `check`/`sweep`,
one document per account, composing `web_discovery.research_object` on **Sonnet**. A
narrow lookup against a named company does not need the wider model, and a watchlist
multiplies every per-account cost.

**People-shaped** — "who, anywhere, is showing this signal" — is `detect`, which was
X-ray's signal mode until it moved here (Sam, 2026-08-24). It never belonged there:
X-ray's job is *given an account and why it matters, find the people*, and a sweep
with no account has no grounding to work from — which is why it alone had no ranking,
no eval arm and no way to tell a good result from a bad one. Signals is where a
signal is already the subject, so it is where the question belongs. What `detect`
finds is a person **and the account they point at**, which is the natural feed into
a watchlist entry and then into a grounded X-ray.

**"Scheduled" means something specific here, and the honest word is smaller.**
Cadence has no scheduler — no cron, no worker, nothing in `requirements.txt`. The one
precedent is `services/sitemap.py`: a staleness check that kicks a daemon thread. For
an app that only runs while somebody is using it, that is the only cadence that ever
fires; a cron entry firing while the app is down does nothing. So `maybe_sweep()`
checks on open, and the page says so rather than implying an overnight watch.

**A finding without a URL is dropped.** An unsourced claim that a company raised a
round is worse than no finding, because it will be repeated on a call with nothing to
check it against.

**Failures are named, never folded into the count.** A sweep where three of eight
accounts errored must not read as "five findings" — that is the shape of report that
makes someone believe a quiet watchlist means quiet accounts.

---

*Generated from the module docstring by `tools/build-agent-docs.py`. Edit the code, not this page.*
