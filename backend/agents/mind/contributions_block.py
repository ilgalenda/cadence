"""What the person Owl is talking to has contributed, framed as theirs.

**This changes presentation, never access.** The vault is global: everything
anybody contributes is in every user's context, and nothing here hides anything
from anyone. What it does is tell Owl which of that shared knowledge came from
the person currently asking, so their own work does not dissolve into an
anonymous corpus the moment it is imported. They can keep building on it.

Two parts, and the split is the whole design:

  * **Their entries already in the shared section are named, not repeated.** The
    approved-knowledge section is in the cached prefix and already carries the
    full text; restating it would double the tokens to say nothing new.
  * **Their entries that did *not* make the shared selection are carried in
    full.** The shared section is scored against the turn's tags and products
    and capped, so on any given turn most of a large contribution is absent. For
    everyone else that is correct — it is what keeps the prompt affordable. For
    the person who wrote it, it would mean their own material vanishing
    depending on what else scored well that day.

**It rides the uncached tail, and must.** `persona.system_blocks` caches
persona + vault as a byte-stable prefix shared across every user
(`agents/mind/persona.py:80-92`); anything user-specific spliced into that prefix
would collapse the prompt cache to one prefix per user on every turn. So this is
joined into `tail_extras` beside the memory block, exactly as
`memory.render_memory_block` is — and it is capped, because uncached tokens are
paid in full on every single turn.
"""
from __future__ import annotations

from agents.shared import vault

#: How many of the contributor's unselected entries to carry, and how much text
#: in total. Deliberately modest: this is uncached, so every character is paid
#: again on each turn of every conversation that user has.
MAX_CARRIED = 8
MAX_CARRIED_CHARS = 6_000

#: How many titles to name for entries already present in the shared section.
MAX_NAMED = 25


def render_own_contributions_block(
    username: str,
    display_name: str = "",
    *,
    tags: list[str] | None = None,
    products: list[str] | None = None,
    max_added: int = 60,
) -> str:
    """The viewer's own contributed knowledge, framed as theirs.

    Returns "" when they have contributed nothing, so the tail stays clean for
    the users this does not apply to — the same contract as
    `memory.render_memory_block`.

    `tags`/`products`/`max_added` must match what the shared section was built
    with, or the two disagree about which entries were selected and an entry is
    either repeated or lost. The caller passes the same values it passed to
    `load_vault_for_context`.
    """
    if not username or not username.strip():
        return ""

    mine, selected_ids = vault.contributions_by(username, tags=tags, products=products, max_added=max_added)
    if not mine:
        return ""

    who = (display_name or username).strip()
    named = [c for c in mine if c.entry_id in selected_ids]
    carried = [c for c in mine if c.entry_id not in selected_ids]

    lines = [
        f"# {who}'s own contributions to the vault",
        f"The knowledge below was contributed by {who}, the person you are talking to. "
        "It is part of the shared vault and every colleague can see it — this section only "
        "tells you which of it is theirs. Credit it as their work when it is relevant, and "
        "help them build on and correct it.",
    ]

    if named:
        titles = "; ".join(c.title for c in named[:MAX_NAMED] if c.title)
        if titles:
            more = f" (and {len(named) - MAX_NAMED} more)" if len(named) > MAX_NAMED else ""
            lines.append(
                "\nAlready quoted in full under Approved Added Knowledge above — do not "
                f"repeat it, refer to it: {titles}{more}."
            )

    if carried:
        budget = MAX_CARRIED_CHARS
        blocks: list[str] = []
        for candidate in carried[:MAX_CARRIED]:
            rendered = vault.format_for_context(candidate)
            if len(rendered) > budget:
                break
            blocks.append(rendered)
            budget -= len(rendered)

        if blocks:
            dropped = len(carried) - len(blocks)
            tail = (
                f"\n\n({dropped} further contribution{'s' if dropped != 1 else ''} by {who} "
                "are in the vault but not shown this turn — ask and they can be looked up.)"
                if dropped > 0 else ""
            )
            lines.append(
                "\nMore of their own work, not otherwise in this prompt:\n\n"
                + "\n\n---\n\n".join(blocks)
                + tail
            )

    return "\n".join(lines)
