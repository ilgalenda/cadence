# Forecasting Agent

> **Operations — part two.**
> A v1 agent, kept deliberately. It predates the Owl Mind and still calls the
> retired `agents.shared.anthropic_client` directly, so it is not registered in
> `backend/main.py` and does not run in this build. Bringing these onto the Mind
> is the next section of work; see [Operations](../operations.md).


Pipeline, hygiene, and revenue analysis over deals synced from a CRM. Splits the
pipeline by vertical and stage, computes a probability-weighted forecast, and
flags data-quality issues — all deterministic, no LLM. It also hosts the
**Pipeline Manager**, a deterministic morning briefing (see below).

Router prefix: `/api/forecast` (gated by `require_agent_access("forecast")`).
Backend: `backend/agents/forecast/`.

## How it works

- **Sync** pulls deals from a `CRMConnector` into the user's store. The default
  `MockHubSpotConnector` returns a generic sample pipeline so the agent is fully
  runnable with no credentials; implement the interface (OAuth shape mirrors the
  Lead agent's Google Calendar connector) and swap it in `get_connector()` to
  connect a real CRM.
- **Analytics** (`analytics.py`, pure functions): `group_by(deals, key)` (open
  deals by vertical/stage), `weighted_forecast(deals)` (open value + per-stage
  probability-weighted forecast), `hygiene(deals, today)` (missing amount /
  close date, past-due close, stale activity > 30d).

## Endpoints

Gated by `require_agent_access("forecast")`; JSON.

| Method · Path | Description |
|---|---|
| `GET /api/forecast/connector` | CRM connection status |
| `POST /api/forecast/sync` | Pull deals from the connector into the user's store |
| `GET /api/forecast/deals` | The user's synced deals |
| `GET /api/forecast/pipeline` | Open pipeline grouped by vertical and stage |
| `GET /api/forecast/forecast` | Probability-weighted forecast (+ per-stage) |
| `GET /api/forecast/hygiene` | Data-quality issues on open deals |
| `GET /api/forecast/stats` | Deal count, open value, weighted forecast |
| `GET /api/forecast/briefing` | **Pipeline Manager** — today's briefing (preview) |
| `POST /api/forecast/briefing/send` | **Pipeline Manager** — email the briefing |

## Data & storage

`deals` collection (per-user, sandbox-aware, cap 200) at
`${DATA_ROOT}/agents/forecast/data/deals.json`. A deal:
`{id, name, stage, amount, vertical, close_date, owner, last_activity,
created_at, stage_entered_at}` (ISO dates). Stages and win-probabilities are
defined by `STAGE_PROBABILITY` in `crm.py` (`OPEN_STAGES` excludes `closed_*`).

---

## Pipeline Manager (sub-capability)

A deterministic daily-review layer on the same deals — it tracks the pipeline,
surfaces **deals gone quiet**, flags **prospects sitting too long**, and delivers
a **morning briefing by email**. No LLM: every figure is computed, so the brief
is auditable and free to send. The Forecasting page stays the visible in-app
surface; the briefing is the email layer on top.

### Detection (`pipeline_manager.py`, configurable thresholds)

- `quiet_deals(deals, today, days=QUIET_DAYS)` — open deals with no activity for
  ≥ `QUIET_DAYS` (default **14**), sorted by how long they've been quiet.
- `aging_deals(deals, today, aging_days=AGING_DAYS, in_stage_days=IN_STAGE_DAYS)`
  — open deals older than `AGING_DAYS` (default **60**) since `created_at`, or in
  the current stage longer than `IN_STAGE_DAYS` (default **30**). Skips deals that
  carry neither date.
- `build_briefing(deals, today)` → `{date, summary{open_count, open_value,
  weighted_forecast, by_stage}, quiet[], aging[], overdue[]}`.
- `render_briefing_text(briefing)` → a plain-text email body.

### Delivery

- **In-app preview** — a "Morning briefing" section on the Forecasting page
  (`GET /api/forecast/briefing`) with an "Email to me" button
  (`POST /api/forecast/briefing/send`, via the admin SMTP; returns `{sent:false}`
  if SMTP is unset).
- **Every morning** — schedule `backend/scripts/morning_briefing.py`, a
  cron-friendly in-process script (no HTTP/auth) that builds the briefing and
  emails it. Exits 0 gracefully when there are no deals or SMTP is unset.

  ```bash
  # weekdays at 07:00 — emails ADMIN_NOTIFY_EMAIL
  0 7 * * 1-5 cd /path/to/cadence/backend && python scripts/morning_briefing.py --user admin
  ```

  Flags: `--user <name>` (whose pipeline to summarise; default `admin`),
  `--no-email` (print only). Email currently targets the single
  `ADMIN_NOTIFY_EMAIL`; per-user briefing email is a future extension.

## Frontend

`frontend/src/pages/agents/forecast/index.astro` — sync button; stats (open
deals, open value, weighted forecast, hygiene count); pipeline by vertical;
hygiene issues; and the morning-briefing preview (quiet + aging) with the send
button. Deal-derived strings are escaped before `innerHTML`.

## Tests

- `backend/tests/test_forecast.py` — open-pipeline filtering, grouping, weighting,
  hygiene flags.
- `backend/tests/test_pipeline_manager.py` — quiet/aging detection (incl. the
  threshold boundary and missing-date skip), briefing structure, plain-text render.

## Key files

- `routes.py` — endpoints (incl. `/briefing`, `/briefing/send`) · `crm.py` —
  connector interface + mock + stage constants · `analytics.py` — deterministic
  pipeline analytics · `pipeline_manager.py` — quiet/aging/briefing ·
  `storage.py` — deals collection · `backend/scripts/morning_briefing.py` — cron
  entry.
