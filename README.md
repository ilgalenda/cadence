# Cadence

Cadence is a sales and operations platform: eleven agents sharing one brain, made
up of a single gateway to the model, one writing voice, a knowledge vault of what
the company knows, and a memory of each user's accounts and deals.

It was built for one company, in production use, and this repository is the
architecture behind it.

![Cadence home](docs/images/screen-cadence-home.png)

## About the name "Acme"

The code refers to a company called Acme. It is a stand in for the company
Cadence was built for, whose product knowledge fills the vault the platform reads
from. The branding came out because the platform is the interesting part, not
whose logo sits on it. Point a clone at a different knowledge base and Acme is
where that company's name goes.

## What this repository is

A showcase. It exists to show what has been built: the architecture, the
reasoning behind it, and the shape of a go to market platform where agents do the
preparation and a person does the deciding.

Parts of it are genuinely usable and worth testing:

- **The frontend runs.** `npm run build` in `frontend/` executes the unit tests,
  the design system adherence check and 29 routes. The design system itself, in
  `frontend/src/design-system/`, is complete and self contained. Its preview
  pages open in a browser with no backend at all.
- **The backend suite passes.** `pytest` in `backend/` runs 56 suites green.
- **Three agents are complete**, prompts and all: Lead Scoring, GTM and X-ray.
  The scoring logic in `services/lead_scoring.py` is deterministic and runs
  without a model.

What will not work is the platform end to end. Eight of the eleven agents have
had their prompts removed, and there is no knowledge in the vault for them to
reason over.

Two of the eleven — Research and Signals — are **held back from this release**
rather than redacted. Their code is here and current; their routers are not
mounted and Owl is not offered them. Both drove a web-search turn that was
compelled to call a tool after its search budget was spent, so the turn thrashed
and never produced its answer: about two completions in five attempts. Shipping
an agent at that rate would teach a reader the wrong lesson about the
architecture.

## How it's built

The short version: work kept moving out of the agents and into the platform,
until the agents were almost nothing.

Early on, every agent talked to the Anthropic API directly. Thirteen places in
the codebase, each with its own retry logic, its own model choice, and its own
way of coping when the model wrapped its JSON in a paragraph of explanation.
Changing anything meant changing it thirteen times, and one always got missed.

There is now exactly one way to reach a model, in `backend/agents/mind/`. Callers
ask for a task rather than a model: `analyze`, `compose`, `chat`, `classify`,
`research`. Which model handles which task lives in `registry.py` and nowhere
else. A semaphore in `governor.py` caps concurrent calls, because rate limits are
the platform's problem rather than something eleven agents should each hold
opinions about. `blocks.py` assembles system prompts with the stable parts first
so the cache gets hit, and `usage.py` counts tokens so an expensive path shows up
before the invoice does.

The same argument applied to voice. At one point there were three different Owls:
one for chat, one for polishing drafts, one for writing outreach. They had
drifted into three personalities. Now there is one persona in `persona.py`, plus
a chat overlay that only conversational screens ever see. The voice that writes
to a customer cannot pick up the tone of a chat window.

What is left in an agent is the job itself, which is why the modules are short
and most of what is worth reading sits in the layer underneath.

```
Astro frontend, one shell, 27 pages
        │  REST + SSE
FastAPI backend
        │
    eleven agents, nine of them also registered as a tool on Owl
        │
    Owl:  Mind · Persona · Knowledge · Memory
        │
    services (scoring, review, selection, discovery, enrichment,
              outreach, mail drafting, style) and integrations
        │
    Anthropic API
```

[docs/architecture.md](docs/architecture.md) covers the vault's three pillars,
how contributed knowledge is treated as untrusted input, and the list of things
that are still wrong.

## A human first approach

Cadence could send email on its own. It does not, and that was a decision rather
than a limitation.

Automated outbound is easy to build and hard to be proud of. The failure mode is
not a bug. It is a hundred plausible, slightly wrong emails going out under
someone's name to people they can no longer approach. That cost lands on the
relationship, and it is not recoverable. A person reading a draft catches the
thing no evaluation set would have flagged: that this account went quiet for a
reason, that the timing is bad, that the argument is right but the person is
wrong.

So the platform prepares and a person decides. Two mechanisms hold it.

**The Google scope is `gmail.compose`.** It can put a draft in a mailbox and it
physically cannot send mail or read an inbox. That restraint is enforced by
Google rather than by good intentions, which is the point. A later change of mind
cannot quietly undo it.

**Anything consequential waits in a queue.** `services/review.py` holds the work,
and approving is what moves it forward.

The agents are there to remove the hour of preparation, not the judgement.

## The agents

| | |
|---|---|
| [Lead Scoring](docs/agents/scoring.md) | How warm a lead is, and why. The number is calculated rather than generated. A model that could nudge the score would make the score worth less |
| [GTM](docs/agents/gtm.md) | Suggests companies worth approaching — fast, and unverified on purpose, because checking happens a step later. Its second mode builds the classified list a tracker is made from, queued for a person to approve |
| [X-ray](docs/agents/xray.md) | Given a company and a reason it matters, works out who there might own the problem |
| [Research](docs/agents/research.md) | The briefing to read before writing anything. **Held back from this release** |
| [Campaign Intelligence](docs/agents/campaign-intelligence.md) | What this market has already said on previous calls |
| [Campaign Selection](docs/agents/campaign-selection.md) | The shape of the campaign. No model involved anywhere in it |
| [Composer](docs/agents/composer.md) | Writes the outreach, for a person to send |
| [Call Analysis](docs/agents/call-analysis.md) | Reads a transcript the way a colleague would |
| [Recap](docs/agents/recap.md) | Drafts the follow up email after a call |
| [Knowledge Capture](docs/agents/knowledge-capture.md) | Files what a call taught the company |
| [Signals](docs/agents/signals.md) | Watches a list of accounts and reports when something happens. **Held back from this release** |

Two of them are marked *soon* in the launcher and on their own pages, which is
what a held-back agent looks like from the inside.

![The agent launcher](docs/images/screen-agents.png)

*The running platform, on seeded demo data. Unlike the design-system screenshots, this is the software — the names and figures in it are invented.*

## Running without a model

Two subsystems reason about nothing and call no model at all — not lesser
agents, and not agents in waiting. The **event programme** records the trade
shows, who is going, and what they still need, counting every deadline backwards
from the show's own dates. The **outbound tracker** holds a campaign's account
list with an append-only trail of what has happened to each row, and publishes it
as a dated read-only page.

A deadline counted backwards from a date is not an opinion, and a record of what
happened to an account is not a judgement. The same argument the platform already
makes about lead scoring: a number a model could move is a number worth less.

See [Running without a model](docs/without-a-model.md).

## Phase 2

Four older agents are still in the repository: Duty & Tax, Forecasting,
Onboarding and a Meet transcript extension. They belong to Phase 2 of Cadence
2.0, the operations half of the platform, which has not been rebuilt yet.

They were written before the Mind existed and still call the layer it replaced,
so they are not wired into `main.py` and do not run. The old client stays in the
repository on purpose: that dependency is the clearest possible description of
what the Phase 2 work actually is.

Their backends and tests are here. Their old interface is not. It does not build,
it predates the design system, and it is the first thing that would go when those
screens are rebuilt. [docs/operations.md](docs/operations.md) has the detail.

## The design

![The studio](docs/images/screen-owl-workspace.png)

The interface follows a minimal Scandinavian direction, deliberately plain, with
the complexity kept out of the user's way. That choice was about adoption. A
sales team will abandon an internal tool in a fortnight if using it feels like
work, so the platform had to be quiet enough that people would keep coming back
to it.

The result came out of trial and error rather than training. Glass is reserved
for things that float above the page and never used on structure. Forms are soft
and geometric, space is generous, and the palette is restrained enough that
colour states a condition instead of decorating. Someone works in this for hours
at a time, and a screen that shouts loses that person by mid afternoon.

One system covers all 27 pages. `tokens.css` holds every colour, size and timing
value, and a build step fails on a raw pixel value anywhere in the app. That is
the only reason the pages still match each other after a year of changes.

The screenshots in this README come from the design system's own preview pages
rather than the live platform, so the names and figures in them are invented.
[docs/design-system.md](docs/design-system.md) has the full set.

## A showcase, and a view of GTM

This repository is a showcase of what has been built and of a particular view of
how go to market work should run. The knowledge a company already owns, compiled
and kept current, does the preparation. The person spends their time on the
conversation instead of on getting ready for it.

Because it is a showcase rather than a deployment, five things are absent by
design:

- **The vault contents.** Real product and customer knowledge. It ships as empty
  folders.
- **Operational data:** call learnings, campaigns, sessions, the user list. None
  of it ever lived in the repository. `backend/paths.py` routes every write to a
  `DATA_ROOT` outside it, which is why none of it has ever appeared in
  `git status`.
- **Most of the prompts.** They took a long time to get right and they belong to
  Acme. The eight redacted modules keep their signatures and docstrings, so
  what each prompt is asked to produce is still readable. The bodies raise
  `NotImplementedError`.
- **Two agents, held back.** Research and Signals ship as code and as pages
  that say so, but their routers are not mounted and Owl is not offered them.
  Unlike the four Phase 2 agents, this is not about age — see above.
- **Credentials.** `.env.example` shows what is required and nothing else.

`tools/` keeps that boundary mechanical rather than remembered: the sync script
copies from an allowlist and refuses anything not named in it, and
`leak-gate.sh` has to pass before anything is pushed.

## Stack

Astro, Tailwind, FastAPI, Uvicorn, SQLite, and the Anthropic API over SSE, with
Haiku, Sonnet and Opus selected per task.

## Where things are

```
backend/
  agents/mind/          the model gateway, persona, memory
  agents/services/      scoring, review, selection, discovery, enrichment
  agents/sales/         the eleven agents
  agents/events/        trade shows and their deadlines — no model
  agents/outbound/      a campaign's account list — no model
  agents/owl/           workspace: projects, threads, search
  agents/learn/ wiki/ admin/
  agents/duty/ forecast/ onboarding/    Phase 2, not wired up
  integrations/         Google OAuth, Gmail, Calendar, contact enrichment
  tests/                56 suites
frontend/src/
  design-system/        tokens, primitives, previews
  lib/                  behaviour, with its tests next to it
  pages/                the 27 pages
docs/
tools/
```

## Licence

MIT. See [LICENSE](LICENSE).
