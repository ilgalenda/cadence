"""Knowledge Capture — what a call taught the company, written down.

Canon's contract: *extract learnings + new glossary terms from a call → stage into
the vault (Dynamic Truth); promote proven ones to canon. Promotion to canon is
gated (curated); staging is automatic.*

Extracted from `run_call_analysis` in Stage 4, where it had been doing this work
inline. Splitting it out changes no behaviour and buys three things: Call Analysis
does one job, a failure to file learnings can no longer cost the analysis somebody
is waiting for, and the staging rules are somewhere you can read them.

**Staging is automatic, into Dynamic Truth, and that is canon's design.** Learnings
go to `dynamic/calls/` via `vault.write_learning`; new terms go to
`dynamic/glossary/` via `vault.write_glossary_term`. Neither is gated, deliberately:
Dynamic Truth *is* the staging tier — the place things live while they earn their
way further — and requiring approval to stage would mean nothing ever got staged.

**The gate canon asks for is the next tier up, and it is not built.** "Promote proven
ones to canon" means `dynamic/` → the canon tier, which is a curation pass over
accumulated Dynamic Truth rather than a per-call decision. Cadence's vault has no
writer for its canon tier (`company/`) at all, so there is nothing here to gate yet.
It is named in the roadmap rather than faked with an approval queue that would
promote nothing. Note the **Added pillar** (`added/pending` → admin) is a different
mechanism for a different thing — user corrections to Owl — and filing a term
definition into it would render as "Owl said: —".

**A term is written once.** `write_glossary_term` skips a slug that already exists in
either the seed or the dynamic glossary, so re-analysing a call that mentions PTP
does not produce a second PTP page.
"""
from __future__ import annotations

from datetime import datetime, timezone

from agents.sales.store import calls as store
from agents.shared.vault import write_glossary_term, write_learning

#: How the per-user markdown mirror is headed. Rewritten on every append, so it is
#: matched and stripped rather than duplicated.
_MD_HEADER = "<!-- Auto-generated from analysed calls. Each analysed call appends a section below. -->\n"

TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "call_id": {
            "type": "string",
            "description": (
                "The analysed call to capture from. Required — capture works from a "
                "reading, not from a transcript."
            ),
        },
    },
    "required": ["call_id"],
}


def _clean_extract(item) -> dict | None:
    """One learning, or None when it is too thin to be worth a vault page."""
    if not isinstance(item, dict):
        return None
    title = str(item.get("title") or "").strip()
    content = str(item.get("content") or "").strip()
    if not title or not content:
        return None

    description = str(item.get("description") or "").strip()
    if not description:
        # Fall back to the first sentence, capped — a page with no description is
        # unreadable in the wiki index.
        first = content.split(".")[0].strip()
        description = (first[:200] + ("…" if len(first) > 200 else "")) or title

    return {
        "title": title,
        "content": content,
        "description": description,
        "category": str(item.get("category") or "").strip() or "general",
    }


def _term_body(term_entry: dict) -> str:
    """A glossary page's body: definition, why it matters here, what it signals.

    Written as one developed explanation rather than three fields, so the page is
    useful to read on its own without the call that produced it.
    """
    parts = [str(term_entry.get("definition") or "").strip()]

    context = str(term_entry.get("company_context") or "").strip()
    if context:
        parts.append(f"**Acme context:** {context}")

    note = str(term_entry.get("sales_note") or "").strip()
    if note:
        parts.append(f"**Sales note:** {note}")

    products = [
        str(p).strip() for p in (term_entry.get("related_products") or [])
        if isinstance(p, str) and str(p).strip()
    ]
    if products:
        parts.append("**Related products:** " + ", ".join(f"[[{p}]]" for p in products))

    return "\n\n".join(parts)


def _stage_learnings(
    username: str, call_id: str, call_title: str, extracts: list, sandbox: bool,
) -> list[dict]:
    """Write the learnings to the vault and this user's own record. Returns the rows."""
    cleaned = [row for row in (_clean_extract(item) for item in extracts) if row is not None]
    if not cleaned:
        return []

    from agents.sales.store._json import new_id

    created_at = datetime.now(timezone.utc).isoformat()
    date_label = datetime.now(timezone.utc).strftime("%d %b %Y")

    rows = []
    md_blocks = []
    for entry in cleaned:
        rows.append({
            "id": new_id(),
            **entry,
            "source_call_id": call_id,
            "source_call_title": call_title,
            "created_at": created_at,
        })
        md_blocks.append(
            f"## {entry['title']} — {date_label} (from: {call_title})\n"
            f"*{entry['description']}*\n"
            f"*Category: {entry['category']}*\n\n"
            f"{entry['content']}\n"
        )

        # The shared vault is live-only: a sandbox run must not add to what the
        # whole company reads.
        if not sandbox:
            write_learning(
                title=entry["title"],
                description=entry["description"],
                content=entry["content"],
                category=entry["category"],
                origin="call",
                agent="call_analysis",
                contributed_by=username,
                source_id=call_id,
                source_title=call_title,
            )

    store.save_learnings(username, rows + store.load_learnings(username, sandbox), sandbox)
    _append_markdown_mirror(username, md_blocks, sandbox)
    return rows


def _append_markdown_mirror(username: str, blocks: list[str], sandbox: bool) -> None:
    """Keep the human-readable copy in step. Newest first, header written once."""
    path = store.user_learnings_md(username, sandbox)
    header = _MD_HEADER + f"# Learnings from {username}'s analysed calls\n\n"

    existing = ""
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if existing.startswith(header):
            existing = existing[len(header):]

    path.write_text(header + "\n".join(blocks) + "\n" + existing, encoding="utf-8")


def _stage_terms(
    username: str, call_id: str, call_title: str, terms: list, sandbox: bool
) -> list[str]:
    """Write genuinely new glossary terms. Returns the ones written.

    A term that already exists is skipped by `write_glossary_term`, which returns
    None — so the list that comes back is what is actually new, not what was
    proposed. One failing term does not cost the others.
    """
    if sandbox:
        return []

    written = []
    for term_entry in terms:
        if not isinstance(term_entry, dict):
            continue
        term = str(term_entry.get("term") or "").strip()
        definition = str(term_entry.get("definition") or "").strip()
        if not term or not definition:
            continue

        try:
            path = write_glossary_term(
                term=term,
                description=definition,
                body=_term_body(term_entry),
                source_id=call_id,
                source_title=call_title,
                contributed_by=username,
                aliases=term_entry.get("aliases") or [],
                tags=term_entry.get("tags") or [],
            )
        except Exception as e:
            print(f"[knowledge-capture] could not write term {term!r}: {e}")
            continue

        if path is not None:
            written.append(term)
    return written


def capture(
    username: str,
    *,
    call_id: str,
    call_title: str,
    extracts: list | None = None,
    terms: list | None = None,
    sandbox: bool = False,
) -> dict:
    """Stage what a call taught us. Returns what was staged.

    Never raises: the caller is usually Call Analysis, mid-response, and a vault
    write failing must not lose the reading. Each half is independent so one failing
    does not cost the other.
    """
    staged: dict = {"learnings": [], "terms": [], "error": None}
    problems = []

    try:
        staged["learnings"] = _stage_learnings(
            username, call_id, call_title, extracts or [], sandbox,
        )
    except Exception as e:
        print(f"[knowledge-capture] learnings not staged: {e}")
        problems.append(f"learnings: {e}")

    try:
        staged["terms"] = _stage_terms(username, call_id, call_title, terms or [], sandbox)
    except Exception as e:
        print(f"[knowledge-capture] terms not staged: {e}")
        problems.append(f"terms: {e}")

    if problems:
        staged["error"] = "; ".join(problems)
    return staged


def capture_from_call(username: str, call_id: str, sandbox: bool = False) -> dict:
    """Stage from an already-analysed call, by id.

    The re-run path: capture normally happens as part of an analysis, and this is
    how it is repeated after a failure without paying for the reading again.
    """
    session = store.get_session(call_id, username, sandbox=sandbox)
    if session is None or session.get("type") != "call_analysis":
        return {"learnings": [], "terms": [], "error": "no_such_call"}

    analysis = session.get("result") or {}
    if not isinstance(analysis, dict):
        return {"learnings": [], "terms": [], "error": "no_usable_analysis"}

    return capture(
        username,
        call_id=call_id,
        call_title=session.get("title") or "Untitled call",
        extracts=analysis.get("knowledge_extracts") or [],
        terms=analysis.get("new_terms") or [],
        sandbox=sandbox,
    )


def run_as_tool(username: str, args: dict) -> str:
    """Stage from a call named in conversation, reported in prose."""
    call_id = (args.get("call_id") or "").strip()
    if not call_id:
        return "Name the call to capture from — it works from a reading, not a transcript."

    staged = capture_from_call(username, call_id)

    if staged["error"] == "no_such_call":
        return "I cannot find that call in your library."
    if staged["error"] == "no_usable_analysis":
        return "That call has no usable reading to capture from."

    learnings = staged["learnings"]
    terms = staged["terms"]

    if not learnings and not terms:
        return (
            "Nothing new to capture from that call — either it taught us nothing "
            "recordable, or it has been captured already."
        )

    lines = []
    if learnings:
        lines.append(f"**{len(learnings)} learning{'' if len(learnings) == 1 else 's'} staged**")
        lines.extend(f"- {row['title']}" for row in learnings[:5])
    if terms:
        lines.append(f"\n**{len(terms)} new term{'' if len(terms) == 1 else 's'}** — " + ", ".join(terms))

    lines.append("\n_Staged into the vault's Dynamic Truth tier, where the team can read it._")

    if staged["error"]:
        lines.append(f"_(Some of it did not save: {staged['error']}.)_")

    return "\n".join(lines)
