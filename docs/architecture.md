# Architecture

Cadence is a platform for sales and operations work, built around eleven agents
that share one brain.

The organising idea is that the agents should be small. Reasoning, voice,
knowledge and memory are all platform services, so what is left in an agent is
the job it actually does and the seam either side of it. Most of this document is
about the layer underneath them, because that is where the work went.

## The four layers

```
┌──────────────────────────────────────────────────────────────┐
│  Astro frontend, one shell, 26 pages                         │
│  workspace · agent pages · knowledge wiki · call library     │
└───────────────────────────┬──────────────────────────────────┘
                            │  REST + SSE
┌───────────────────────────▼──────────────────────────────────┐
│  FastAPI backend                                             │
│                                                              │
│   eleven agents, each also a tool on Owl                     │
│                                      ▼                       │
│   ┌──────────────────────────────────────────────────────┐   │
│   │  OWL, the platform brain                             │   │
│   │                                                      │   │
│   │  Mind       one governed gateway to the model        │   │
│   │  Persona    one voice, with a stance overlay         │   │
│   │  Knowledge  the vault, in three pillars              │   │
│   │  Memory     per user accounts, deals, preferences    │   │
│   └──────────────────────────────────────────────────────┘   │
│                                      ▲                       │
│   capability services                                        │
│   scoring · review · selection · discovery · enrichment      │
│   outreach · mail drafting · style personalisation           │
│                                                              │
│   integrations: Google OAuth · Gmail · Calendar · enrichment │
└───────────────────────────┬──────────────────────────────────┘
                            │
                   ┌────────▼────────┐
                   │  Anthropic API  │
                   └─────────────────┘
```

## Mind: one gateway instead of thirteen

`backend/agents/mind/` is the only code in Cadence that talks to a model.

In the 1.0 version of the platform there were thirteen separate call sites, each
with its own retry behaviour, its own model choice and its own way of handling a
response that came back with prose wrapped around the JSON. Every change had to
be made thirteen times, and one of them always got missed.

Consolidating them made a few things possible that were not possible before.

Callers ask for a task rather than a model. The API is `analyze`, `compose`,
`chat`, `classify` and `research`, and the mapping from task to model lives in
`registry.py`. Changing which model serves analysis is one edit in one file.

Concurrency is capped in one place. `governor.py` holds a `BoundedSemaphore`,
default size 1, configurable with `MIND_MAX_CONCURRENCY`. Rate limits are a
property of the platform, and eleven agents should not each be discovering that
separately.

Prompt caching actually works. `blocks.py` assembles the system prompt as an
ordered set of blocks with the stable content first, so the cached prefix stays
byte identical between calls. Anything that changes per run is appended at the
end.

There is one JSON parser. `jsonparse` deals with the model explaining itself
around its output, which it sometimes does, in one place rather than eleven.

Cost is visible. `usage.py` records tokens and cost per call, so an expensive
path shows up while it is being written rather than on the bill.

| module | job |
|---|---|
| `core.py` | the task shaped API every agent calls |
| `client.py` | the Anthropic client and its retry behaviour |
| `registry.py` | which model serves which task |
| `governor.py` | concurrency ceiling |
| `blocks.py` | system prompt assembly, ordered so the cache holds |
| `cache.py` | prompt cache bookkeeping |
| `tooling.py` | the tool use loop |
| `persona.py` | the single voice, plus the chat stance overlay |
| `memory.py`, `memory_db.py` | per user memory over SQLite |
| `contributions_block.py` | contributed knowledge, fenced before it reaches a prompt |
| `memory_seed.py` | first run memory for a new user |
| `usage.py` | token and cost accounting |

### Persona

In the 1.0 version of the platform there were three different personas: one for
chat, one for refining drafts and one for composing outreach. Each had its own
prompt, and over a few months they had drifted into three separate
personalities.

`persona.py` fixed that. One persona core, and a `CHAT_STANCE` overlay that is
applied only on conversational surfaces. Composition and analysis never see it,
so the voice that writes to a customer cannot pick up the register of a chat
window.

## Knowledge: the vault, in three pillars

The vault is Markdown on disk, Obsidian compatible, under `${DATA_ROOT}/vault`.

1. **Company Truth** (`company/`) is hand curated and canonical. When two pillars
   disagree, this one wins.
2. **Dynamic Truth** (`dynamic/`) is what the platform learned from real calls and
   campaigns. It is written automatically and treated as a strong signal about
   how the company sells today.
3. **Added Knowledge** (`added/`) is user submitted corrections. They sit in
   `pending/` until an admin approves them into `approved/`.

Loader precedence is what protects canon: a lower pillar can add to the picture
but cannot overwrite the top one. Every write needs a `title` and a
`description`, so nothing enters the vault anonymously.

Contributed knowledge is untrusted text on a direct path into a prompt, and it is
handled that way. Headings in a contribution are demoted below `###` so a
submission cannot forge a section boundary, and content shaped like an
instruction is refused rather than quietly stripped. A contributor who can see
the rejection can fix it; one whose text was silently edited cannot.

The vault ships in the public repository as empty scaffolding. The structure
travels and the content does not.

## Memory: per user, and not shared

`memory_db.py` keeps accounts, deals, context and preferences per user in SQLite.

Style Personalisation is deliberately private to each person. It shapes what you
draft and never feeds the shared Owl persona, so two people using Cadence do not
gradually end up writing like each other.

## Capability services

`backend/agents/services/` holds the work that is not reasoning.

| service | job |
|---|---|
| `lead_scoring.py` | the score itself, from rules rather than a model |
| `campaign_selection.py` | the campaign shape, also from rules |
| `review.py` | the approval queue that consequential work passes through |
| `web_discovery.py` | grounded search |
| `enrichment.py` | contact reveal, one person at a time, paid per credit |
| `name_sources.py` | the second name source behind X-ray discovery |
| `outreach.py` | the two pass draft then refine primitive |
| `mail_draft.py` | filing an approved draft into Gmail |
| `style_personalisation.py` | the per user writing overlay |
| `sitemap.py` | keeping the page taxonomy in step with the live site |

Two of these have no model in them at all, and that is the point. A lead score
has to be reproducible and tunable: if the same behaviour can produce a different
number on a second run, nobody can act on it and nobody can improve it. The same
reasoning covers the campaign shape. The model's job in both cases is to read raw
signal into structure, not to decide the answer.

## The two rules the platform enforces

Both are built into the code rather than written in a policy.

**Agents draft and populate; a person sends.** The Google grant is
`gmail.compose`, which can create a draft and cannot send mail or read the
mailbox. Google enforces the restraint, so a later change of mind cannot quietly
remove it.

**Anything consequential waits for approval.** `services/review.py` is the queue,
and approving is what moves work forward.

## Request lifecycle

```
browser  →  /api/sales/<agent>/…            FastAPI route
         →  agent.<verb>()                  the job itself
         →  mind.<task>()                   governed model call
         →  services / integrations         deterministic work, side effects
         →  review queue                    if consequential
         ←  SSE stream or JSON
```

Long running agent work streams over SSE. There is one exception, recorded under
known limitations below rather than hidden.

## Data model: `DATA_ROOT`

`backend/paths.py` resolves every mutable path through `DATA_ROOT`. This is the
mechanism that keeps operational content out of version control.

In development, `DATA_ROOT` points at a directory outside the repository, so test
writes never appear in `git status` and there is no daily decision about what to
stage. In production it points at the deployment's own data directory.

The separation is structural, which means nothing has to remember to exclude
anything.

## Frontend conventions

Astro, with one shell (`PlatformLayout`) and the design system in
`frontend/src/design-system/`. See [the design system](design-system.md).

`tokens.css` is the source of truth for colour, type, space and motion, and a
build gate fails on a raw pixel value anywhere in the app. Behaviour lives in
`frontend/src/lib/` as plain TypeScript modules with their unit tests beside
them, which keeps the page code declarative.

## Testing

`backend/tests/` holds 42 suites, all green in this build.

The discipline is that the acceptance bar gets written or refreshed before a
change is trusted, and that it is contract shaped wherever the contract is the
thing that matters. `test_request_shape.py` pins what actually goes to the API,
`test_models_pinned.py` pins model routing, and `test_system_blocks.py` pins the
prompt assembly the cache depends on.

## Known limitations

These are stated rather than tidied away. A showcase that hides its rough edges
is not showing the work.

**`mind.research` does not stream** (`mind/core.py`). A research turn that runs
for several minutes can be disconnected outright, and nothing on that path
retries. This is why GTM was deliberately moved off grounded search; see
[GTM](agents/gtm.md).

**`tool_choice: "any"` is re-sent every round** by `tooling.run_tool_loop`, so it
keeps forcing a tool call after `max_uses` is spent. The model thrashes and never
emits its terminal JSON. `research/agent.py` and `signals/agent.py` still ride
it. `services/name_sources.py` already uses `"auto"`, which is the fix.

**There is no reply or bounce detection.** `gmail.compose` cannot read the
mailbox, so suppression is manual.

**The Phase 2 agents are not registered.** See [Operations](operations.md).
