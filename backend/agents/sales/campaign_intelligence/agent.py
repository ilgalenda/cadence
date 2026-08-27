"""Campaign Intelligence — what this market already told us, before you write to it.

Canon's contract: *recall past conversations with clients in a similar vertical,
surface objections and pain points, and outline the relevant campaign angle to
inform selection*. No review gate — this is preparation, and it feeds Campaign
Selection and Composer rather than anything a customer sees.

This is the first agent that cashes in the vault's call learnings. Every other
agent that touches them reads a tag-scored slice; this one is *about* them.

**Two passes, and they do different jobs.** The corpus carries no vertical to
filter on, so retrieval is the hard part (the argument is in `index.py`). Pass one
shows the whole index of titles and asks which lines are worth reading — a
retrieval mechanic, so it runs on the cheap `classify` profile. Pass two does the
judgement canon specifies, on `analyze` (Sonnet), over only the bodies that were
picked. The cheap pass never sees a body, so it cannot synthesise from a title;
the expensive pass never sees the index, so it cannot cite a call it did not read.

**Read-only, deliberately.** It writes no vault entry, no memory row and no review
item. Canon gives it no gate and no persistence duty, and that is what makes it
safe for Owl to run mid-sentence. It *reads* Memory — `topics_for_vertical` — so
the outline knows what has already worked for this user, not just what the team
heard.

**It degrades rather than fails.** An empty shortlist, a market with no history, an
unparseable answer: each returns an outline that says so. The caller is usually a
path step with a person waiting at the end of it.
"""
from __future__ import annotations

from agents.mind import core as mind
from agents.mind import memory
from agents.mind.memory import _vertical as normalise_vertical
from agents.sales import prompts
from agents.sales.campaign_intelligence import index

#: How many learnings the synthesis pass reads. Enough for a market's recurring
#: objections without paying to re-read its whole history; past this the same
#: points repeat and the outline gets longer rather than better.
MAX_RECALL = 20

#: How much of the index the shortlist pass is shown. The index is newest-first, so
#: this drops the oldest learnings — the deliberate loss, not a random slice. The
#: cap exists because the corpus grows with every call and an unbounded prompt is a
#: cost that arrives quietly; `outline()` reports both numbers so it never does.
MAX_INDEX = 400

#: Room for a shortlist of line numbers. The `classify` profile defaults to 400,
#: which is ample for `[12, 4, 87]` but not worth being tight about.
SHORTLIST_MAX_TOKENS = 1024

TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "vertical": {
            "type": "string",
            "enum": list(memory.VERTICALS),
            "description": (
                "The market to recall. Required unless a company is given, in which "
                "case it is inferred."
            ),
        },
        "company": {
            "type": "string",
            "description": "Optional. The account being prepared for, if there is one.",
        },
        "notes": {
            "type": "string",
            "description": "Optional. Anything the outline should take account of.",
        },
    },
    "required": [],
}

#: Words that place a company or brief in one of Memory's markets. Used only when
#: the caller did not say which market — a hint, not a classifier, and it never
#: invents a market outside `memory.VERTICALS`.
_VERTICAL_HINTS: dict[str, tuple[str, ...]] = {
    "finance": (
        "bank", "exchange", "trading", "broker", "hedge fund", "market data",
        "mifid", "finra", "clearing", "capital markets", "fintech",
    ),
    "defence": (
        "defence", "defense", "military", "navy", "army", "air force", "aerospace",
        "sosa", "programme office", "gps-denied", "radar",
    ),
    "telecom": (
        "telecom", "telco", "operator", "carrier", "mobile network", "ran ",
        "backhaul", "fronthaul", "synce", "mno",
    ),
    "broadcast": (
        "broadcast", "broadcaster", "studio", "playout", "smpte", "st 2110",
        "outside broadcast", "television",
    ),
    "private-5g": (
        "private 5g", "private network", "campus network", "neutral host",
        "ndac", "cbrs", "industrial 5g",
    ),
}


def resolve_vertical(vertical: str = "", *, company: str = "", brief: dict | None = None) -> str:
    """The market to recall, as one of Memory's own verticals.

    An explicit vertical wins and is normalised through Memory's own normaliser, so
    this agent and Memory can never disagree about what "finance" is called. With
    none given, the company name and the brief's own text are searched for a hint —
    Research has usually already written down what the company does, and asking the
    user to restate it would be asking them for something the run already knows.

    Falls back to `other`, which is a real market in Memory's taxonomy and reads
    honestly in the outline, rather than guessing at the biggest one.
    """
    if (vertical or "").strip():
        return normalise_vertical(vertical)

    brief = brief or {}
    haystack = " ".join([
        company,
        str((brief.get("company") or {}).get("what_they_do") or ""),
        str((brief.get("company") or {}).get("infrastructure") or ""),
        str((brief.get("angle") or {}).get("why") or ""),
        str((brief.get("timing") or {}).get("why_now") or ""),
    ]).lower()

    for candidate, hints in _VERTICAL_HINTS.items():
        if any(hint in haystack for hint in hints):
            return candidate
    return "other"


def _shortlist(*, vertical: str, company: str, learnings: list[index.Learning]) -> list[index.Learning]:
    """Pass one: which lines of the index are worth reading.

    A failure here is not fatal — it means no recall, which the synthesis step and
    the outline both already know how to say. Raising instead would turn a thin
    outline into a broken path step.
    """
    if not learnings:
        return []

    try:
        result = mind.classify(
            system=prompts.CI_SHORTLIST_SYSTEM,
            messages=[{
                "role": "user",
                "content": prompts.ci_shortlist_prompt(
                    vertical=vertical,
                    company=company,
                    index_text=index.render_index(learnings),
                    want=MAX_RECALL,
                ),
            }],
            max_tokens=SHORTLIST_MAX_TOKENS,
        )
        handles = result.json_array()
    except Exception as e:
        print(f"[campaign-intelligence] shortlist unavailable: {e}")
        return []

    if not isinstance(handles, list):
        return []

    # Trimmed after resolving, not before: the model orders by relevance, but
    # `select` returns index order, so cutting first would drop by date instead.
    return index.select(learnings, handles)[:MAX_RECALL]


def _memory_topics(username: str, vertical: str) -> list[str]:
    """What has already resonated for this user in this market. Best-effort."""
    try:
        return memory.topics_for_vertical(username, vertical)
    except Exception as e:
        print(f"[campaign-intelligence] memory read skipped: {e}")
        return []


def _empty(vertical: str, *, error: str, considered: int = 0, indexed: int = 0) -> dict:
    return {
        "vertical": vertical,
        "objections": [],
        "pain_points": [],
        "angle": {},
        "proof_points": [],
        "recall_quality": "none",
        "recall": [],
        "considered": considered,
        "indexed": indexed,
        "error": error,
    }


def outline(
    username: str,
    *,
    vertical: str = "",
    company: str = "",
    brief: dict | None = None,
    notes: str = "",
) -> dict:
    """Recall a market and outline how to approach it.

    Returns `vertical`, `objections`, `pain_points`, `angle`, `proof_points`,
    `recall_quality`, the `recall` actually read, how much of the corpus was
    `considered` against how much is `indexed`, and `error` when a pass did not
    complete. A partial outline is returned rather than raised — the objections are
    usually there even when the angle is not, and they are the useful part.
    """
    market = resolve_vertical(vertical, company=company, brief=brief)

    indexed = index.build_index()
    considered = indexed[:MAX_INDEX]

    chosen = _shortlist(vertical=market, company=company, learnings=considered)
    if not chosen:
        return _empty(market, error="no_recall", considered=len(considered), indexed=len(indexed))

    try:
        result = mind.analyze(
            system=prompts.CI_SYNTHESIS_SYSTEM,
            messages=[{
                "role": "user",
                "content": prompts.ci_synthesis_prompt(
                    vertical=market,
                    company=company,
                    learnings=index.render_bodies(chosen),
                    memory_topics=_memory_topics(username, market),
                    notes=notes,
                ),
            }],
        )
        synthesis = result.json() or {}
    except Exception as e:
        print(f"[campaign-intelligence] synthesis failed: {e}")
        return _empty(
            market, error=f"synthesis_failed: {e}",
            considered=len(considered), indexed=len(indexed),
        )

    if not isinstance(synthesis, dict):
        return _empty(
            market, error="unparseable_outline",
            considered=len(considered), indexed=len(indexed),
        )

    return {
        "vertical": market,
        "objections": synthesis.get("objections") or [],
        "pain_points": synthesis.get("pain_points") or [],
        "angle": synthesis.get("angle") or {},
        "proof_points": synthesis.get("proof_points") or [],
        "recall_quality": synthesis.get("recall_quality") or "",
        # What it actually read, so a claim in the outline can be traced to a call.
        "recall": [{"id": row.id, "title": row.title} for row in chosen],
        "considered": len(considered),
        "indexed": len(indexed),
        "error": None,
    }


def _bullet(items: list, *, key: str, because: str) -> list[str]:
    """Format one outline list for prose, skipping anything that came back hollow."""
    lines = []
    for item in items[:4]:
        if not isinstance(item, dict):
            continue
        head = str(item.get(key) or "").strip()
        if not head:
            continue
        tail = str(item.get(because) or "").strip()
        lines.append(f"- **{head}**" + (f" — {tail}" if tail else ""))
    return lines


def run_as_tool(username: str, args: dict) -> str:
    """Recall a market from conversation, reported in prose.

    Read-only, and says what it read. "Which calls is this from" is the first thing
    anyone asks of a recall, so the count and the truncation are stated rather than
    left for the user to wonder about.
    """
    out = outline(
        username,
        vertical=(args.get("vertical") or ""),
        company=(args.get("company") or ""),
        notes=(args.get("notes") or ""),
    )

    market = out["vertical"]
    if out["error"] == "no_recall":
        return (
            f"Nothing in the {out['considered']} call learnings I can see speaks to "
            f"{market}. Worth analysing a call in that market first."
        )
    if out["error"]:
        return f"Could not recall {market} ({out['error']})."

    lines = [f"**{market}** — from {len(out['recall'])} past conversations."]

    objections = _bullet(out["objections"], key="objection", because="how_it_lands")
    if objections:
        lines.append("\n**Objections you will meet**\n" + "\n".join(objections))

    pains = _bullet(out["pain_points"], key="pain", because="why_it_bites")
    if pains:
        lines.append("\n**What hurts them**\n" + "\n".join(pains))

    angle = out["angle"] or {}
    if angle.get("open_with"):
        lines.append(f"\n**Open with** — {angle['open_with']}")
    if angle.get("avoid"):
        lines.append(f"**Avoid** — {angle['avoid']}")

    if out["proof_points"]:
        lines.append("\n**Has landed before** — " + "; ".join(str(p) for p in out["proof_points"][:3]))

    if out["recall_quality"] == "thin":
        lines.append("\n_The recall here is thin — treat this as a starting point, not the market._")

    if out["indexed"] > out["considered"]:
        lines.append(
            f"\n_Read the most recent {out['considered']} of {out['indexed']} learnings._"
        )

    return "\n".join(lines)
