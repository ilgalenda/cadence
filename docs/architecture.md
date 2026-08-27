# Architecture

Cadence is an agentic platform for sales and operations. Its organising idea is
that **the agents should be thin because the platform is thick**: reasoning,
voice, knowledge and memory are platform services, so an agent is left with one
job and the seam either side of it.

That is what most of this document is about.

---

## The four layers

```
┌──────────────────────────────────────────────────────────────┐
│  Astro frontend — one shell, 26 pages                        │
│  workspace · agent pages · knowledge wiki · call library     │
└───────────────────────────┬──────────────────────────────────┘
                            │  REST + SSE
┌───────────────────────────▼──────────────────────────────────┐
│  FastAPI backend                                             │
│                                                              │
│   eleven sales agents  ──────────────┐                       │
│   each one job, each a tool on Owl   │                       │
│                                      ▼                       │
│   ┌──────────────────────────────────────────────────────┐   │
│   │  OWL — the platform brain                            │   │
│   │                                                      │   │
│   │  Mind       one governed gateway to the model        │   │
│   │  Persona    one voice, with a stance overlay         │   │
│   │  Knowledge  the three-pillar vault                   │   │
│   │  Memory     per-user accounts, deals, preferences    │   │
│   └──────────────────────────────────────────────────────┘   │
│                                      ▲                       │
│   capability services ───────────────┘                       │
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

---

## Mind — one gateway, not thirteen call sites

`backend/agents/mind/` is the only place in Cadence that talks to a model.

Before it existed there were thirteen hand-rolled call sites, each with its own
retry behaviour, its own idea of how to parse a response and its own model
choice. Consolidating them bought the things you only get from a single seam:

- **A task-shaped API.** Callers ask for `analyze`, `compose`, `chat`,
  `classify` or `research` — not for a model and a temperature. Which model
  serves a task is a routing decision (`registry.py`), made once and changed
  once.
- **A governor.** `governor.py` holds a `BoundedSemaphore`, default size 1
  (`MIND_MAX_CONCURRENCY`). Concurrency against a rate-limited API is a property
  of the platform, not something each agent should rediscover.
- **Prompt caching that actually hits.** `blocks.py` assembles the system prompt
  as an ordered set of blocks with the stable content first, so the cached prefix
  stays byte-identical across calls. Anything per-run rides at the tail.
- **One parser.** `jsonparse` handles the model returning prose around JSON,
  which it sometimes does, in one place instead of eleven.
- **Usage accounting.** `usage.py` records tokens and cost per call, so an
  expensive path is visible rather than inferred from the bill.

| module | job |
|---|---|
| `core.py` | the task-shaped API every agent calls |
| `client.py` | the Anthropic client and its retry behaviour |
| `registry.py` | which model serves which task |
| `governor.py` | concurrency ceiling |
| `blocks.py` | system-prompt assembly, cache-stable ordering |
| `cache.py` | prompt-cache bookkeeping |
| `tooling.py` | the tool-use loop |
| `persona.py` | the single voice, plus the chat stance overlay |
| `memory.py`, `memory_db.py` | per-user memory over SQLite |
| `usage.py` | token and cost accounting |
| `contributions_block.py` | contributed knowledge, demoted and fenced before it reaches a prompt |
| `memory_seed.py` | first-run memory for a new user |

### Persona — one voice, one overlay

There used to be three Owls: a chat Owl, a refinement Owl and a composition Owl,
each with its own drifting personality. `persona.py` is the correction. One
persona core, plus a `CHAT_STANCE` overlay that applies **only** to conversational
surfaces. Composition and analysis never see it, so the voice that writes to a
customer cannot pick up the register of a chat window.

---

## Knowledge — three pillars, in priority order

The vault is Markdown on disk, Obsidian-compatible, under `${DATA_ROOT}/vault`.

1. **Company Truth** (`company/`) — hand-curated, canonical, locked. When pillars
   conflict, this wins.
2. **Dynamic Truth** (`dynamic/`) — learnings the platform extracted from real
   calls and campaigns. Written automatically; strong signal about how the
   company actually sells today.
3. **Added Knowledge** (`added/`) — user-submitted corrections, `pending/` until
   an admin approves them into `approved/`.

Loader precedence is what protects canon: a lower pillar can add to the picture
but cannot overwrite the top one. Every write requires a `title` and a
`description`, so nothing enters the vault anonymously.

**Contributed knowledge is untrusted input on a direct path into a prompt**, and
is treated as such: headings in a contribution are demoted below `###` so a
submission cannot forge a section boundary, and instruction-shaped content is
*refused* rather than stripped — a rejection the contributor can see beats a
silent edit they cannot.

The vault ships in this repo as empty scaffolding. Content is data, and data does
not travel.

---

## Memory — per user, and deliberately not shared

`memory_db.py` keeps accounts, deals, context and preferences per user in SQLite.
Style Personalisation is per-user and private: it shapes what *you* draft and
never feeds the shared Owl persona. Two people using Cadence do not end up
writing like each other.

---

## Capability services

`backend/agents/services/` holds the work that is not reasoning:

| service | job |
|---|---|
| `lead_scoring.py` | the deterministic score — rules, not a model |
| `campaign_selection.py` | the deterministic campaign shape |
| `review.py` | the approval queue every consequential step passes through |
| `web_discovery.py` | grounded search |
| `enrichment.py` | contact reveal, per person, paid per credit |
| `outreach.py` | the two-pass draft → refine primitive |
| `mail_draft.py` | filing an approved draft into Gmail |
| `style_personalisation.py` | the per-user writing overlay |
| `sitemap.py` | keeping the page-taxonomy map in step with the live site |
| `name_sources.py` | the second name source behind X-ray discovery |

Two of these are deterministic on purpose. **A model that could move the lead
score would make the score meaningless**, and the same argument applies to the
campaign shape. Where a number has to be reproducible and tunable, it is rules;
the model's job is only to read raw signal into structure.

---

## The two platform rules

Both are architectural, not policy notes.

1. **Agents draft and populate; the human always sends.** The Google grant is
   `gmail.compose`, which can create a draft and can neither read the mailbox nor
   send. The restraint is enforced by Google rather than by our own discipline.
2. **Every consequential step passes a review gate.** `services/review.py` is the
   queue; approving is what moves work forward.

---

## Request lifecycle

```
browser  →  /api/sales/<agent>/…            FastAPI route
         →  agent.<verb>()                  one job
         →  mind.<task>()                   governed model call
         →  services / integrations         deterministic work, side effects
         →  review queue                    if consequential
         ←  SSE stream or JSON
```

Long-running agent work streams over SSE. One exception is recorded rather than
hidden: see Known limitations below.

---

## Auth and access

Session cookies via starlette, bcrypt password hashes written to
`${DATA_ROOT}/agents/users_credentials.json` by `seed_users.py`. Credentials never
enter git; the roster is regenerated per environment.

---

## Data model — `DATA_ROOT`

`backend/paths.py` resolves every mutable path through `DATA_ROOT`, and this is
the mechanism that keeps operational content out of version control:

- **Development:** point `DATA_ROOT` at a directory *outside* the repo. Test
  writes then never appear in `git status`, so there is no daily judgement call
  about what to stage.
- **Production:** point it at the deployment's own data directory.

The separation is structural. Nothing has to remember to exclude anything.

---

## Frontend conventions

Astro, one shell (`PlatformLayout`), with the design system in
`frontend/src/design-system/` — see [the design system](design-system.md).
`tokens.css` is the source of truth for colour, type, space and motion; a build
gate fails on raw `px`. Behaviour lives in `frontend/src/lib/` as plain
TypeScript modules with unit tests beside them, so page code stays declarative.

---

## Testing

`backend/tests/` — 42 suites, green in this build. The discipline is that the
acceptance bar is written
or refreshed before a change is trusted, and it is contract-shaped rather than
unit-shaped where the contract is what matters: `test_request_shape.py` pins what
actually goes to the API, `test_models_pinned.py` pins model routing,
`test_system_blocks.py` pins the cache-stable prompt assembly.

---

## Known limitations

Stated rather than tidied away, because a showcase that hides its rough edges is
not showing you the work.

- **`require_agent_access` has no call sites.** `backend/auth.py` defines
  per-agent access control; nothing calls it. Page access is enforced in the
  frontend only. Anyone running this for real should wire it up server-side
  before trusting it.
- **`mind.research` is non-streaming** (`mind/core.py`). A multi-minute research
  turn can be disconnected outright, and nothing in that path retries. It is why
  GTM was deliberately moved *off* grounded search — see [GTM](agents/gtm.md).
- **`tool_choice: "any"` is re-sent every round** by `tooling.run_tool_loop`, so
  it keeps forcing a tool call after `max_uses` is spent; the model thrashes and
  never emits its terminal JSON. `research/agent.py` and `signals/agent.py` still
  ride it. `services/name_sources.py` already uses `"auto"`, which is the fix.
- **No reply or bounce detection.** `gmail.compose` cannot read the mailbox, so
  suppression is manual.
- **The Operations agents are not registered.** See [Operations](operations.md).
