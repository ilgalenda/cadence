# X-ray

| | |
|---|---|
| **Module** | `backend/agents/sales/xray/` |
| **Routes** | `/api/sales/xray` |
| **Mind profile** | `classify` |
| **Human gate** | the user selects people to reveal |

**Prompts: in this build.** This is one of the three exemplar agents, published with its prompts intact so the prompt engineering is readable, not just described.

---

**One question, and the "why" is half of it.** Discovery reasons from the
grounding it is given: the vertical, the product line in play, the role already
seen. Hand it a bare company name and it has to guess all three, which is why a
name typed by hand has always been the weakest search this agent does.

So there is one mechanism and three ways to acquire the grounding, strongest
first:

- **a scored lead** — handed over from Lead scoring, or dropped straight onto
  X-ray, which scores it inline through `scoring.analyse` and carries on. The
  primary source (Sam, 2026-08-24).
- **a GTM target** — arriving with the vertical and the reason the company is on
  the list.
- **a bare company** — where `derive_grounding` classifies the account first, so
  discovery still reasons from a vertical and a product fit rather than a name.

**Sweeping for a signal is no longer here.** "Who, anywhere, is showing this
signal" has no account and therefore no grounding, which is exactly why it alone
had no ranking and no eval arm. It moved to `sales.signals`, where a signal is
already the subject.

No LinkedIn API is involved: this searches the public web for profiles that
search engines have already indexed. Enrichment (email, and phone only when
explicitly asked) is a separate step on the selected shortlist, so credit is
spent on people a human chose.

---

*Generated from the module docstring by `tools/build-agent-docs.py`. Edit the code, not this page.*
