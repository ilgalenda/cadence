"""A tracker as a standalone page, for publishing as a read-only snapshot.

**Read-only, deliberately.** The page this replaces kept its own state and saved
new versions of itself, which is how the working surface and the vault's copy of
the list came to disagree on fifteen accounts. So the export has no Save button,
no `window.claude` call and no way to record a touch: Cadence owns the record, and
this is a photograph of it. The footer says when it was taken, because a snapshot
that does not date itself gets read as live.

**The columns are declared once, as data.** Each column is a `(header, cell)` pair
and the header row is written from the same list that fills the cells, so a column
cannot exist in one and not the other — the rule `agents/events/sheet.py` sets for
the shared spreadsheet, and for the same reason: a header that has drifted from its
column is worse than a missing column.

**An absent value writes an em dash, not a blank.** On a page somebody else reads,
an empty cell means "nobody has filled this in yet" and a dash means "there is
nothing to fill in". Those are different facts to whoever is chasing.

**No prices leave here except the ones already on the record.** The catalogue is
commercially confidential and never reaches a published page; a row's own
first-deal figure does, because that is what the tracker is for.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from html import escape
from typing import Callable, Optional

from agents.outbound import store

#: The five touches as single letters, so five columns fit where five words would
#: not: connect, message, email, value-add, break-up.
TOUCH_INITIALS = ("C", "M", "E", "V", "B")

STATUS_TONE = {
    "not_started": "idle",
    "sequencing": "drift",
    "replied": "live",
    "meeting": "live",
    "qualified": "locked",
    "dead": "idle",
}

TIER_NAMES = {1: "Spec author", 2: "Trigger-qualified", 3: "OEM / embed"}

CAMPAIGN_NAMES = {"A-jamming": "Jamming", "B-tdd": "5G TDD", "C-finance": "Finance"}


def _dash(value: object) -> str:
    text = "" if value is None else str(value).strip()
    return text or "—"


def _money(gbp: Optional[int]) -> str:
    return "unpriced" if gbp is None else f"£{gbp:,}"


def _touches(row: dict) -> str:
    """Five marks: the initial of each touch, filled when it was sent."""
    cells = []
    for touch, initial in zip(row["touches"], TOUCH_INITIALS):
        state = "is-on" if touch["fired"] else ""
        title = f'{touch["label"]} — sent {touch["at"][:10]}' if touch["fired"] else f'{touch["label"]} — not sent'
        cells.append(f'<span class="tk {state}" title="{escape(title)}">{initial}</span>')
    return f'<span class="touches">{"".join(cells)}</span>'


def _status(row: dict) -> str:
    tone = STATUS_TONE.get(row["status"], "idle")
    label = row["status"].replace("_", " ")
    return f'<span class="mark mark--{tone}">{escape(label)}</span>'


def _account(row: dict) -> str:
    sub = " · ".join(part for part in (row["segment"], row["geography"]) if part)
    body = f'<span class="co">{escape(row["account"])}</span>'
    if sub:
        body += f'<span class="co__sub">{escape(sub)}</span>'
    return body


#: One column: its heading, how to fill it, and the class its cells carry.
#:
#: **Target roles are deliberately not here.** They are on the record in Cadence,
#: they are the widest text on the row, and a ninth column pushed the first-deal
#: figure off the edge of the page — a snapshot that hides the number it exists to
#: report. Nine columns of everything beats eight columns that fit, only until you
#: look at it.
Column = tuple[str, Callable[[dict], str], str]

COLUMNS: tuple[Column, ...] = (
    ("Account", _account, "cell--account"),
    ("Tier", lambda row: escape(TIER_NAMES.get(row["tier"], f'Tier {row["tier"]}')), "cell--tag"),
    ("Campaign", lambda row: escape(CAMPAIGN_NAMES.get(row["campaign"], _dash(row["campaign"]))), "cell--tag"),
    ("Trigger", lambda row: escape(_dash(row["trigger_text"])), "cell--trigger"),
    ("Touches", _touches, "cell--touches"),
    ("Status", _status, "cell--status"),
    ("Next due", lambda row: escape(_dash(row["next_due"])), "cell--date"),
    ("First deal", lambda row: escape(_money(row["value_est_gbp"])), "cell--num"),
)


def render(tracker_id: str, *, taken_at: Optional[str] = None) -> str:
    """The whole page, as one string of HTML."""
    tracker = store.get_tracker(tracker_id)
    if not tracker:
        raise ValueError("No such tracker")

    rows = store.get_rows(tracker_id)
    counters = store.counters(tracker_id)
    stamp = taken_at or datetime.now(timezone.utc).strftime("%d %B %Y, %H:%M UTC")

    # Substituted rather than `.format`ed: the stylesheet is full of braces, and
    # every one of them would have to be doubled to survive a format string.
    filled = _PAGE
    for token, value in (
        ("__CSS__", _CSS),
        ("__NAME__", escape(tracker["name"])),
        ("__STAMP__", escape(stamp)),
        ("__STATS__", _stats(counters)),
        ("__COVERAGE__", escape(_coverage(counters))),
        ("__HEADERS__", _headers()),
        ("__GROUPS__", _groups(rows)),
        ("__STATE__", _state_json(rows)),
    ):
        filled = filled.replace(token, value)
    return filled


def _state_json(rows: list[dict]) -> str:
    """The state block's contents, safe to sit inside a `<script>` element.

    `json.dumps` leaves `<` and `>` alone, so an account name containing
    `</script>` would close the element and every byte after it would be parsed as
    markup. Escaping the three characters as unicode keeps the JSON identical to a
    parser and inert to the HTML tokeniser.
    """
    payload = json.dumps(_state(rows), separators=(",", ":"))
    return payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _state(rows: list[dict]) -> list[dict]:
    """The rows as data, embedded so the page carries its own numbers.

    A published snapshot whose figures exist only as rendered text cannot be read
    back or diffed. Two things are left out. The trail names who did what and
    belongs in Cadence, not on a page that may be shared. Target roles are absent
    for the same reason the column is: dropping a column but keeping the field in
    the data would make "not published" only half true.
    """
    return [
        {
            "account": row["account"],
            "segment": row["segment"],
            "tier": row["tier"],
            "campaign": row["campaign"],
            "trigger": row["trigger_text"],
            "geography": row["geography"],
            "confidence": row["confidence"],
            "value_est_gbp": row["value_est_gbp"],
            "status": row["status"],
            "next_due": row["next_due"],
            "touches": [touch["fired"] for touch in row["touches"]],
        }
        for row in rows
    ]


def _stats(counters: dict) -> str:
    """The readout, in the order the sequence runs."""
    tiles = [
        ("targets", str(counters["targets"]), ""),
        ("touch actions", str(counters["touches"]), _of(counters["target_touches"])),
        ("in sequence", str(counters["in_sequence"]), _of(counters["targets"])),
        ("replies", str(counters["replies"]), _of(counters["target_replies"])),
        ("calls", str(counters["calls"]), _of(counters["target_calls"])),
        ("qualified", str(counters["qualified"]), _of(counters["target_qualified"])),
        ("qualified value", _money(counters["qualified_value_gbp"]), _of_money(counters["goal_gbp"])),
    ]
    return "".join(
        f'<div class="stat"><span class="stat__n">{escape(value)}</span>'
        f'<span class="stat__l">{escape(label)}{escape(against)}</span></div>'
        for label, value, against in tiles
    )


def _of(target: int) -> str:
    return f" · of {target}" if target else ""


def _of_money(target: int) -> str:
    return f" · of £{target:,}" if target else ""


def _coverage(counters: dict) -> str:
    """What the total covers, and what it does not."""
    total = _money(counters["total_value_gbp"])
    caveats = []
    if counters["unpriced"]:
        caveats.append(f'{counters["unpriced"]} carry no figure at all')
    if counters.get("uncomposed"):
        caveats.append(
            f'{counters["uncomposed"]} carry a figure with no recorded composition, '
            "so they cannot be repriced"
        )

    priced = counters["targets"] - counters["unpriced"]
    covered = (
        f'{total} across {priced} of {counters["targets"]} accounts'
        if counters["unpriced"]
        else f'{total} across all {counters["targets"]} accounts'
    )
    return f"{covered}." if not caveats else f'{covered} — {", and ".join(caveats)}.'


def _groups(rows: list[dict]) -> str:
    """The table body, grouped by where each account is in the sequence.

    Grouped rather than flat for the reason the control surface is: on a list this
    long, "who is mid-sequence and going stale" is a question you should be able to
    answer by looking rather than by sorting.
    """
    order = list(store.STATUSES)
    buckets: dict[str, list[dict]] = {status: [] for status in order}
    for row in rows:
        buckets.setdefault(row["status"], []).append(row)

    out = []
    for status in order:
        bucket = sorted(buckets[status], key=lambda r: (r["tier"], r["account"]))
        if not bucket:
            continue
        label = status.replace("_", " ")
        out.append(
            f'<tbody><tr class="grouphead"><th colspan="{len(COLUMNS)}">'
            f'{escape(label)} · {len(bucket)}</th></tr>'
        )
        for row in bucket:
            cells = "".join(
                f'<td class="{klass}">{fill(row)}</td>' for _, fill, klass in COLUMNS
            )
            out.append(f"<tr>{cells}</tr>")
        out.append("</tbody>")
    return "".join(out)


def _headers() -> str:
    return "".join(f"<th>{escape(header)}</th>" for header, _, _ in COLUMNS)


_CSS = """
:root{
  --ground:#ffffff; --sunken:#f4f3f1; --ink:#1a1a19; --ink-2:#4a4d52;
  --ink-3:#767d88; --rule:#e4e2df; --rule-2:#c9c6c1;
  --blue:#0084ff; --amber:#a8730b; --green:#2a8800;
  --blue-wash:rgba(0,132,255,.08); --amber-wash:rgba(246,161,0,.14);
  --green-wash:rgba(42,136,0,.10);
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --ground:#121212; --sunken:#1c1c1b; --ink:#f2f4f7; --ink-2:#b4bbc6;
    --ink-3:#848c98; --rule:#2c3036; --rule-2:#3d434b;
    --blue:#3fa2ff; --amber:#ffb627; --green:#5dbb2e;
    --blue-wash:rgba(63,162,255,.13); --amber-wash:rgba(255,182,39,.14);
    --green-wash:rgba(93,187,46,.13);
  }
}
:root[data-theme="dark"]{
  --ground:#121212; --sunken:#1c1c1b; --ink:#f2f4f7; --ink-2:#b4bbc6;
  --ink-3:#848c98; --rule:#2c3036; --rule-2:#3d434b;
  --blue:#3fa2ff; --amber:#ffb627; --green:#5dbb2e;
  --blue-wash:rgba(63,162,255,.13); --amber-wash:rgba(255,182,39,.14);
  --green-wash:rgba(93,187,46,.13);
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--ground); color:var(--ink);
  font-family:Roboto,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  font-size:15px; line-height:1.55; -webkit-font-smoothing:antialiased;
}
.wrap{max-width:80rem; margin:0 auto; padding:0 1.5rem 4rem}
/* Kode Mono is a whisper: timestamps and identifiers only — with one sanctioned
   exception the app already makes. `.ds-table__num` in the design system sets the
   mono face for a numeric table column, so money in the table matches it here.
   The counter tiles do not: the app's own tiles use `.ds-numeric`, which is
   tabular figures in the brand face, and a headline number in mono is what made
   the old page read as a terminal readout rather than a document. */
.mono,.cell--date,.cell--num,.tk{
  font-family:"Kode Mono",ui-monospace,Menlo,monospace;
  font-variant-numeric:tabular-nums;
}
.stat__n{font-variant-numeric:tabular-nums;}
header{padding:3rem 0 1.5rem; display:flex; flex-direction:column; gap:.75rem}
.brand{display:flex; align-items:baseline; gap:.8rem; flex-wrap:wrap}
.brand__mark{font-family:"Kode Mono",monospace; font-weight:600; font-size:.78rem;
  letter-spacing:.2em; text-transform:uppercase}
.brand__rule{width:1.2rem; height:1px; background:var(--rule-2)}
.brand__tag{font-family:"Kode Mono",monospace; font-size:.72rem; color:var(--ink-3)}
.eyebrow{font-family:"Kode Mono",monospace; font-size:.7rem; font-weight:500;
  letter-spacing:.16em; text-transform:uppercase; color:var(--ink-3); margin:0}
h1{font-size:clamp(1.9rem,4vw,2.6rem); font-weight:700; line-height:1.05;
  letter-spacing:-.02em; margin:.4rem 0 0; text-wrap:balance}

/* A snapshot that does not say so gets worked in. */
.snapshot{
  display:flex; gap:.6rem; align-items:baseline; flex-wrap:wrap;
  background:var(--amber-wash); border-left:3px solid var(--amber);
  padding:.85rem 1.15rem; margin:1.5rem 0 0; font-size:.9rem;
}
.snapshot b{color:var(--amber)}

.stats{display:grid; grid-template-columns:repeat(auto-fit,minmax(9rem,1fr));
  gap:.25rem 1.75rem; padding:1.5rem 0 1rem; border-top:1px solid var(--rule);
  margin-top:1.5rem}
.stat{display:flex; flex-direction:column; gap:.15rem}
.stat__n{font-size:1.35rem; font-weight:600; line-height:1.1}
.stat__l{font-size:.78rem; color:var(--ink-3)}
.coverage{color:var(--ink-2); font-size:.85rem; max-width:52rem; margin:0 0 1.75rem}

/* No border. Depth comes from the group bands pressed into the white field and
   from the hairline row rules, not from an outline round the whole table. */
.tablewrap{overflow-x:auto}
table{border-collapse:collapse; width:100%; min-width:54rem; font-size:.85rem}
thead th{
  padding:.7rem .8rem; background:var(--sunken); border-bottom:1px solid var(--rule);
  font-size:.7rem; font-weight:500; letter-spacing:.1em; text-transform:uppercase;
  color:var(--ink-3); text-align:left; white-space:nowrap;
}
tbody td{padding:.65rem .8rem; border-bottom:1px solid var(--rule); vertical-align:middle}
.grouphead th{
  padding:.6rem .8rem; background:var(--sunken); border-bottom:1px solid var(--rule);
  font-family:"Kode Mono",monospace; font-size:.7rem; font-weight:500;
  letter-spacing:.12em; text-transform:uppercase; color:var(--ink-3); text-align:left;
}
.co{font-weight:500; display:block; white-space:nowrap}
.co__sub{display:block; font-size:.75rem; color:var(--ink-3); white-space:nowrap}
.cell--tag{white-space:nowrap; color:var(--ink-2)}
.cell--trigger{max-width:26rem; color:var(--ink-2)}
.cell--num{text-align:right; white-space:nowrap; font-weight:600}
.cell--date,.cell--status,.cell--touches{white-space:nowrap}

.touches{display:inline-flex; gap:.2rem}
.tk{
  width:1.15rem; height:1.15rem; display:grid; place-items:center;
  border:1px solid var(--rule-2); border-radius:999px; font-size:.62rem;
  font-weight:600; color:var(--ink-3);
}
.tk.is-on{background:var(--blue); border-color:var(--blue); color:#fff}

.mark{display:inline-flex; align-items:center; gap:.35rem; font-size:.72rem;
  padding:.15rem .5rem; border-radius:999px; white-space:nowrap}
.mark::before{content:""; width:5px; height:5px; border-radius:50%;
  background:currentColor; flex:0 0 auto}
.mark--idle{color:var(--ink-3)}
.mark--drift{color:var(--amber); background:var(--amber-wash)}
.mark--live{color:var(--blue); background:var(--blue-wash)}
.mark--locked{color:var(--green); background:var(--green-wash)}

footer{margin-top:2.5rem; padding-top:1.25rem; border-top:1px solid var(--rule);
  display:flex; flex-direction:column; gap:.35rem}
footer p{margin:0; font-family:"Kode Mono",monospace; font-size:.7rem;
  letter-spacing:.04em; color:var(--ink-3)}
@media (max-width:40rem){.wrap{padding:0 1rem 3rem}}
"""


_PAGE = """<title>__NAME__</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&family=Kode+Mono:wght@400;500;600&display=swap">
<style>__CSS__</style>
<div class="wrap">
  <header>
    <div class="brand">
      <span class="brand__mark">Acme</span>
      <span class="brand__rule"></span>
      <span class="brand__tag">Infrastructure, on time</span>
    </div>
    <div>
      <p class="eyebrow">Outbound tracker</p>
      <h1>__NAME__</h1>
    </div>
    <p class="snapshot">
      <b>Snapshot.</b>
      <span>Read-only. Touches and statuses are recorded in Cadence, not here — a tick
      on this page would only disagree with the record. Taken __STAMP__.</span>
    </p>
  </header>

  <div class="stats">__STATS__</div>
  <p class="coverage">__COVERAGE__</p>

  <div class="tablewrap">
    <table>
      <thead><tr>__HEADERS__</tr></thead>
      __GROUPS__
    </table>
  </div>

  <footer>
    <p>Cadence · outbound tracker · snapshot __STAMP__</p>
    <p>Commercially confidential. First-deal figures are estimates, not quotes.</p>
  </footer>
</div>
<script id="state" type="application/json">__STATE__</script>
"""
