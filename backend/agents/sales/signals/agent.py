"""Signals — the watchlist that notices things.

Canon's contract: *a scheduled monitor over a target-account watchlist for funding
rounds and timing technographics; feeds GTM. A lean monitor, not a `high_intent`
rebuild.*

Two shapes of question live here, and they used to live apart.

**Account-shaped** — "what happened at *this named company*" — is `check`/`sweep`,
one document per account, composing `web_discovery.research_object` on **Sonnet**. A
narrow lookup against a named company does not need the wider model, and a watchlist
multiplies every per-account cost.

**People-shaped** — "who, anywhere, is showing this signal" — is `detect`, which was
X-ray's signal mode until it moved here (Sam, 2026-08-24). It never belonged there:
X-ray's job is *given an account and why it matters, find the people*, and a sweep
with no account has no grounding to work from — which is why it alone had no ranking,
no eval arm and no way to tell a good result from a bad one. Signals is where a
signal is already the subject, so it is where the question belongs. What `detect`
finds is a person **and the account they point at**, which is the natural feed into
a watchlist entry and then into a grounded X-ray.

**"Scheduled" means something specific here, and the honest word is smaller.**
Cadence has no scheduler — no cron, no worker, nothing in `requirements.txt`. The one
precedent is `services/sitemap.py`: a staleness check that kicks a daemon thread. For
an app that only runs while somebody is using it, that is the only cadence that ever
fires; a cron entry firing while the app is down does nothing. So `maybe_sweep()`
checks on open, and the page says so rather than implying an overnight watch.

**A finding without a URL is dropped.** An unsourced claim that a company raised a
round is worse than no finding, because it will be repeated on a call with nothing to
check it against.

**Failures are named, never folded into the count.** A sweep where three of eight
accounts errored must not read as "five findings" — that is the shape of report that
makes someone believe a quiet watchlist means quiet accounts.
"""
from __future__ import annotations

import threading

from agents.mind import governor as mind_governor
from agents.mind.registry import MODELS, Tier
from agents.sales import prompts, signal_prompts
from agents.sales.store import signals as store
from agents.services import name_sources, web_discovery

#: Searches per account. A watchlist multiplies this, so it is deliberately tight:
#: recent news, money, infrastructure.
MAX_SEARCHES = 4
MAX_ROUNDS = 6
MAX_TOKENS = 2048

#: The categories the prompt returns, in the order a person would read them.
CATEGORIES = ("funding", "technographics", "other")

#: How many people one `detect` sweep returns. Unlike an account check this has no
#: company to anchor it, so the bound is the only thing keeping it finite.
DETECTION_MAX_RESULTS = 15

#: How many accounts one sweep will check. A guard against a full watchlist and a
#: cold cache costing fifty web-search turns in one page load; the rest are picked up
#: on the next sweep, oldest-first.
MAX_PER_SWEEP = 8

TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "company": {
            "type": "string",
            "description": (
                "Optional. Check one company now, whether or not it is on the "
                "watchlist. Omit to report what is new across the whole watchlist."
            ),
        },
        "force": {
            "type": "boolean",
            "description": (
                "Optional. Re-check accounts even if they were checked recently. "
                "Costs a web search per account."
            ),
        },
    },
    "required": [],
}

#: One sweep at a time per process. Two surfaces loading at once must not each start
#: their own — the same guard `services/sitemap.py` uses, for the same reason.
_sweep_lock = threading.Lock()


def _usable(finding, kind: str) -> dict | None:
    """One finding, or None when it cannot be trusted or remembered.

    A finding needs a headline to be worth reading and a URL to be worth believing.
    Dropping the unsourced ones here means the prompt's rule is enforced rather than
    merely requested.
    """
    if not isinstance(finding, dict):
        return None

    headline = str(finding.get("headline") or "").strip()
    url = str(finding.get("url") or "").strip()
    if not headline or not url:
        return None

    return {
        "kind": str(finding.get("kind") or kind).strip() or kind,
        "headline": headline,
        "when": str(finding.get("when") or "").strip(),
        "why_it_matters": str(finding.get("why_it_matters") or "").strip(),
        "url": url,
    }


def check(username: str, *, company: str, seen: list[str] | None = None) -> dict:
    """Look for what is new at one company.

    Returns `{"company", "findings", "fingerprints", "error"}`. `findings` excludes
    anything whose fingerprint is already in `seen`, so a second sweep over a quiet
    company reports nothing rather than the same items again.

    Never raises: the caller is usually a sweep over several accounts, and one
    unreachable company must not end the others.
    """
    company = (company or "").strip()
    if not company:
        return {"company": "", "findings": [], "fingerprints": [], "error": "no_company"}

    seen = list(seen or [])

    try:
        with mind_governor.slot():
            turn = web_discovery.research_object(
                system=prompts.SIGNALS_SYSTEM,
                user_message=prompts.signals_prompt(company=company),
                tool_choice={"type": "any"},
                max_uses=MAX_SEARCHES,
                # Sonnet, stated rather than inherited: a named-company lookup does
                # not need the Opus that broad people-discovery uses.
                model=MODELS[Tier.SONNET],
                max_tokens=MAX_TOKENS,
                max_rounds=MAX_ROUNDS,
            )
    except Exception as e:  # noqa: BLE001 — one company must not end a sweep
        return {"company": company, "findings": [], "fingerprints": [], "error": f"check_failed: {e}"}

    result = turn["result"] or {}
    findings: list[dict] = []
    fingerprints: list[str] = []

    for category in CATEGORIES:
        for raw in result.get(category) or []:
            finding = _usable(raw, category)
            if finding is None:
                continue
            mark = store.fingerprint(finding)
            if not mark or mark in seen:
                continue
            # Guards against the same item appearing twice within one response.
            if mark in fingerprints:
                continue
            fingerprints.append(mark)
            findings.append(finding)

    return {
        "company": company,
        "findings": findings,
        "fingerprints": fingerprints,
        # A turn that ended early still returns what it found; the error says so.
        "error": turn["error"],
    }


def sweep(username: str, *, force: bool = False, sandbox: bool = False) -> dict:
    """Check the watched accounts that are due, and record what was found.

    Returns `{"checked", "skipped", "findings", "failures", "watched"}`. `failures`
    names the accounts that errored — a sweep that half-worked must say so, because a
    quiet report is otherwise indistinguishable from quiet accounts.

    Accounts are checked one at a time under the Mind's governor: a ten-account
    watchlist opening ten concurrent web-search turns against a default concurrency
    of 1 would queue anyway, and would look like a hang.
    """
    watched = store.watchlist(username, sandbox)
    if not watched:
        return {"checked": 0, "skipped": 0, "findings": [], "failures": [], "watched": 0}

    candidates = watched if force else store.due(username, sandbox=sandbox)
    picked = candidates[:MAX_PER_SWEEP]

    findings: list[dict] = []
    failures: list[dict] = []

    for entry in picked:
        out = check(username, company=entry.get("company") or "", seen=entry.get("seen") or [])

        # Stamped even on failure: a company whose page reliably errors would
        # otherwise be retried on every sweep, spending a turn each time. The
        # findings are stored, not just their fingerprints — a background sweep has
        # no caller waiting, so anything it does not store is reported to nobody.
        store.record_check(
            entry["id"], username,
            fingerprints=out["fingerprints"],
            findings=out["findings"],
            sandbox=sandbox,
        )

        if out["error"] and not out["findings"]:
            failures.append({"company": out["company"], "error": out["error"]})
            continue

        for finding in out["findings"]:
            findings.append({**finding, "company": out["company"], "entry_id": entry["id"]})

    return {
        "checked": len(picked),
        "skipped": max(0, len(candidates) - len(picked)),
        "findings": findings,
        "failures": failures,
        "watched": len(watched),
    }


def maybe_sweep(username: str, sandbox: bool = False) -> bool:
    """Start a sweep in the background if anything is due. Returns whether it started.

    The `services/sitemap.py` pattern: never blocks the caller, and skips entirely
    when a sweep is already running. This is what "scheduled" means in an app with no
    scheduler — it happens when a surface is opened, not overnight.
    """
    if _sweep_lock.locked():
        return False
    if not store.due(username, sandbox=sandbox):
        return False

    def _run() -> None:
        # The lock is taken inside the thread so the caller returns immediately even
        # if another sweep grabs it first.
        if not _sweep_lock.acquire(blocking=False):
            return
        try:
            sweep(username, sandbox=sandbox)
        except Exception as e:  # noqa: BLE001 — a background sweep cannot raise anywhere useful
            print(f"[signals] background sweep failed: {e}")
        finally:
            _sweep_lock.release()

    threading.Thread(target=_run, daemon=True).start()
    return True


def digest(username: str, sandbox: bool = False, limit: int = 8) -> str:
    """What GTM should weight towards, as prose.

    One line per watched account with a recent finding. **Empty when the watchlist is
    empty**, which is what keeps GTM's prompt byte-identical to before Signals
    existed — the same guarantee Campaign Intelligence and Gmail drafting were each
    built to preserve.

    Reads what is stored; never triggers a check. A prompt builder that could spend a
    web search would make GTM's cost unpredictable.
    """
    lines = []
    for entry in store.watchlist(username, sandbox):
        recent = entry.get("recent") or []
        for finding in recent[:2]:
            headline = str((finding or {}).get("headline") or "").strip()
            if headline:
                lines.append(f"- {entry.get('company')}: {headline}")
        if len(lines) >= limit:
            break

    if not lines:
        return ""
    return (
        "Accounts already on the watchlist with a recent signal — weight towards "
        "these and towards companies like them:\n" + "\n".join(lines[:limit])
    )


# ── People-shaped: who is showing this signal, anywhere ─────────────────────

def detect(username: str, signal_type: str, icp_config: dict) -> dict:
    """People showing a named buying signal, regardless of company.

    A broad sweep with no company to anchor it, so it governs its own single
    call and caps the result set.

    Returns ``{results, raw, error, provider_errors, truncated}``. Unlike the
    company-scoped mode these rows are **not ranked** — there is no shared
    company to judge relative fit against — so they arrive in the order the
    model emitted them.
    """
    user_message = signal_prompts.detection_user_message(signal_type, icp_config)

    with mind_governor.slot():
        out = web_discovery.search_people(
            system=signal_prompts.DETECTION_SYSTEM_PROMPT,
            user_message=user_message,
            normalise=_normalise_signal_row,
            tool_choice={"type": "any"},
            max_uses=8,
            model=MODELS[Tier.OPUS],
            # Was 4096, which could not have been right: this schema is *larger*
            # than the company-scoped one — nine fields a row, several of them
            # narrative — and that mode needs 16384 for the same fifteen rows. A
            # cut turn was being salvaged into a partial array and reported as a
            # clean result, because `flag_incomplete` was off as well.
            max_tokens=name_sources.XRAY_MAX_TOKENS,
            text_extract="join",
            flag_incomplete=True,
            # Same reason as the company-scoped mode (see `name_sources`): this
            # reads named individuals out of raw result snippets, so it stays on
            # the generation that returns them rather than the one that
            # summarises results and spends the tool budget filtering.
            web_search_type=name_sources.XRAY_WEB_SEARCH_TYPE,
        )

    cleaned = web_discovery.dedup_by_linkedin_url(out["results"])[:DETECTION_MAX_RESULTS]
    incomplete = "incomplete_response" in str(out["error"] or "")

    # A truncated sweep still returns the people it had gathered. Those are worth
    # keeping — but only if the caller is told the answer was cut, which is
    # exactly what the old `if out["error"]: return []` threw away along with them.
    if out["error"] and not cleaned:
        return {
            "results": [], "raw": out["raw"], "error": out["error"],
            "provider_errors": [out["error"]], "truncated": incomplete,
        }

    return {
        "results": cleaned,
        "raw": out["raw"],
        "error": None,
        "provider_errors": [out["error"]] if out["error"] else [],
        "truncated": incomplete,
    }


def _normalise_signal_row(row: dict) -> dict | None:
    """One detected person, or None when the row is unusable.

    A row without a name or without the context that makes it a signal is not a
    lead — dropping it here keeps the caller from having to defend against it.
    """
    if not isinstance(row, dict):
        return None
    full_name = (row.get("full_name") or "").strip()
    signal_context = (row.get("signal_context") or "").strip()
    if not full_name or not signal_context:
        return None

    confidence = (row.get("confidence") or "").strip().lower()
    if confidence not in {"high", "medium", "low"}:
        confidence = "low"

    text = lambda key: (row.get(key) or "").strip()  # noqa: E731 — local shorthand
    return {
        "full_name": full_name,
        "job_title": text("job_title"),
        "company": text("company"),
        "linkedin_url": text("linkedin_url"),
        "confidence": confidence,
        "signal_type": text("signal_type"),
        "signal_context": signal_context,
        "signal_date": text("signal_date"),
        "fit_reason": text("fit_reason"),
        "recommended_product": text("recommended_product"),
        "source_query": text("source_query"),
        # Stamped so provenance reads the same in both modes. Company-scoped rows
        # get this from `name_sources.normalise_row`; without it here the run
        # panel could cite its sources for one mode and not the other.
        "source": "web_search",
    }


def run_as_tool(username: str, args: dict) -> str:
    """Report the watchlist from conversation, in prose."""
    company = (args.get("company") or "").strip()

    if company:
        out = check(username, company=company)
        if out["error"] and not out["findings"]:
            return f"Could not check {company} ({out['error']})."
        if not out["findings"]:
            return f"Nothing new at {company}."
        return f"**{company}**\n" + "\n".join(
            f"- {f['headline']}" + (f" _({f['when']})_" if f["when"] else "")
            for f in out["findings"][:6]
        )

    out = sweep(username, force=bool(args.get("force")))

    if not out["watched"]:
        return (
            "Nothing is on your watchlist yet. Add the accounts you want watched and "
            "I will check them for funding, build-outs and timing work."
        )

    if not out["findings"] and not out["failures"]:
        return f"Nothing new across {out['watched']} watched account{'' if out['watched'] == 1 else 's'}."

    lines = []
    if out["findings"]:
        by_company: dict[str, list[dict]] = {}
        for finding in out["findings"]:
            by_company.setdefault(finding["company"], []).append(finding)
        for name, items in by_company.items():
            lines.append(f"\n**{name}**")
            lines.extend(
                f"- {i['headline']}" + (f" — {i['why_it_matters']}" if i["why_it_matters"] else "")
                for i in items[:4]
            )

    # Named, not folded into the count: a quiet report must not be mistaken for
    # quiet accounts.
    if out["failures"]:
        named = ", ".join(f["company"] for f in out["failures"])
        lines.append(f"\n_Could not check: {named}._")

    if out["skipped"]:
        lines.append(f"_{out['skipped']} more still due — run it again to continue._")

    return "\n".join(lines).strip()
