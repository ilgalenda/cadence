"""The shape of a target list, declared rather than hoped for.

`identify` returns a shortlist whose entries are validated nowhere: each consumer
re-guesses the fields, and one of them silently drops three of the five. That is
survivable for a list of names read by a person. It is not survivable for a list
that lands in a tracker and gets priced, because a missing `deal_shape` is not a
cosmetic gap — it is the difference between £300 and £1,000 on an account
somebody then quotes.

So this mode has a schema, and the schema is where the domain rules live that a
prompt can only ask for politely:

  * **Tier means a kind of account, not a rank.** Tier 1 is the spec author who
    writes Acme into someone else's design and may never buy directly; tier 2
    is an end user with a live dated reason; tier 3 ships under someone else's
    brand. A model that reads "tier" as "how good" produces a list of ones.
  * **A trigger must name where it came from.** An unsourced trigger is
    indistinguishable from an invented one, and this agent has no web access.
  * **The deal shape is a classification, not a price.** The model says how the
    first contract is put together; `agents.outbound.valuation` prices it. Asking
    a model for the figure would produce a number nobody can check.

Validation failures are reported by the caller, never raised — the house rule at
`agent.py:69`.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

#: The three campaigns the message library is written for. A row assigned to none
#: of them has no copy to send, so the field is closed rather than free text.
Campaign = Literal["A-jamming", "B-tdd", "C-finance"]

Confidence = Literal["high", "medium", "low"]

#: The deal shapes the price catalogue knows. Closed deliberately: an invented
#: shape cannot be priced, and a near-miss priced as its neighbour is the failure
#: the valuation module exists to prevent.
DealShape = Literal[
    "primary_quorum",
    "defence_grade_quorum",
    "brownfield_backup",
    "brownfield_entry",
    "wr_node",
    "wr_poc_kit",
    "wr_early_adopter",
    "portable",
]


class DealLine(BaseModel):
    """One component of a first contract: a shape, and how many."""

    shape: DealShape
    quantity: int = Field(default=1, ge=1, le=20)


class TargetRow(BaseModel):
    """One account, as GTM proposes it.

    Everything here is generated. The tracker adds the state — touches, status,
    next due, procurement route — because those are facts about what has happened
    and nothing has happened yet.
    """

    account: str = Field(min_length=1, max_length=120)
    domain: str = ""
    segment: str = Field(default="", max_length=60)
    tier: Literal[1, 2, 3]
    campaign: Campaign
    geography: str = Field(default="", max_length=80)
    target_roles: str = Field(default="", max_length=200)
    confidence: Confidence = "medium"

    #: Only ever filled from the Signals digest. Empty is the honest answer for an
    #: account nobody is watching, which is every account on a fresh list.
    trigger_text: str = ""
    trigger_source: str = ""

    #: How the first contract is composed. Empty is allowed — an account too
    #: early to shape is better recorded unpriced than priced on a guess.
    deal_lines: list[DealLine] = Field(default_factory=list)
    attach_support: bool = False

    #: Why this shape, and what would change it. The figure is arithmetic; this is
    #: the reasoning behind the arithmetic, and it is what a person argues with.
    deal_rationale: str = Field(default="", max_length=400)

    #: What to verify before approaching, and anything uncertain about the company
    #: itself. Carried into the tracker's notes, because the honesty duty
    #: `identify` took on does not stop being owed when the output is richer.
    check: str = Field(default="", max_length=300)
    caveat: str = Field(default="", max_length=300)

    @field_validator("trigger_source")
    @classmethod
    def _sourced(cls, source: str, info) -> str:
        """A trigger without a source is refused, not silently accepted.

        The prompt is told this; the schema is what makes it true. A model asked
        for a dated reason to move, with no way to look one up, will invent one —
        and an invented trigger is the one error that reaches a prospect.
        """
        trigger = (info.data.get("trigger_text") or "").strip()
        if trigger and not source.strip():
            raise ValueError(
                "a trigger must name where it came from; leave it empty if there is none"
            )
        return source

    def notes(self) -> str:
        """The row's notes, as the tracker stores them.

        `check` and `caveat` are joined rather than kept apart because the tracker
        has one notes field and losing the caveat is how an unverified candidate
        comes to look like a confident one.
        """
        parts = []
        if self.check:
            parts.append(f"Check: {self.check}")
        if self.caveat:
            parts.append(f"Unsure: {self.caveat}")
        if self.deal_rationale:
            parts.append(f"Deal: {self.deal_rationale}")
        return " · ".join(parts)

    def as_proposal(self) -> dict:
        """This row in the shape `agents.outbound.store.add_rows` accepts."""
        return {
            "account": self.account,
            "domain": self.domain,
            "segment": self.segment,
            "tier": self.tier,
            "campaign": self.campaign,
            "geography": self.geography,
            "target_roles": self.target_roles,
            "confidence": self.confidence,
            "trigger_text": self.trigger_text,
            "trigger_source": self.trigger_source,
            "deal_lines": [line.model_dump() for line in self.deal_lines],
            "attach_support": self.attach_support,
            "notes": self.notes(),
        }


class TargetList(BaseModel):
    """A whole proposal: the accounts, and how the list was scoped."""

    rows: list[TargetRow] = Field(default_factory=list)

    #: How the list was scoped and what was deliberately left out. Kept because
    #: "what I did not include" is the part a person can correct.
    notes: str = ""

    def proposals(self) -> list[dict]:
        return [row.as_proposal() for row in self.rows]

    @property
    def accounts(self) -> list[str]:
        return [row.account for row in self.rows]


def empty() -> dict:
    """The contract's empty value, for a caller that could not get an answer."""
    return {"rows": [], "notes": ""}
