"""Google Sheets — the shared events working document, and only that.

The people who decide and deliver an event mostly have no Cadence account: Alex
and Nils take the decision, Jo produces the material, an operations manager
books the travel. A spreadsheet is where they already work, so Cadence keeps one
fed rather than asking four people to sign into something.

**Write only, deliberately.** There is a `values.get` in this API and this module
does not wrap it beyond reading the id column. Cadence does not honour edits made
in the sheet — Sam settled that: *"Sheet number 2 is only collecting all the
shows that we either take part to... I don't need Cadence to read it."* Two
writers on one row, with no per-cell history to arbitrate, is a way to lose
somebody's work quietly. If that changes, the read side is a deliberate build
with a conflict rule attached, not a convenience added here.

**No Drive scope.** `spreadsheets.create` puts the file in the connecting
account's Drive, which is all Cadence needs. Sharing it with four people is a
permissions decision that belongs to a person, once, in Drive.

Synchronous and routed through `google_oauth.authorised_request`, like
``gmail.py`` and ``google_calendar.py`` — it owns the refresh-and-persist dance
and returns Google's own error text, which is more use in a log than ours.

Docs: https://developers.google.com/sheets/api/reference/rest
"""
from __future__ import annotations

from typing import Any, Iterable, Sequence

from integrations.google_oauth import authorised_request

API = "https://sheets.googleapis.com/v4/spreadsheets"


def sheet_url(spreadsheet_id: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"


def create(username: str, title: str, tabs: Sequence[str]) -> str:
    """Make the spreadsheet, with its tabs, and return its id.

    Called once. The id is kept by the caller — a second call would make a second
    file, which is why nothing here looks one up by name: two spreadsheets with
    the same title and different contents is the worst outcome available.
    """
    body = {
        "properties": {"title": title},
        "sheets": [{"properties": {"title": tab}} for tab in tabs],
    }
    created = authorised_request(username, "POST", API, json_body=body)
    return created["spreadsheetId"]


def tab_ids(username: str, spreadsheet_id: str) -> dict[str, int]:
    """Tab name to its numeric id.

    Values are addressed by name (`Events!A1`) and formatting by id, which is a
    seam worth naming: a batchUpdate aimed at the wrong sheetId formats the wrong
    tab silently, because every tab is a valid target.
    """
    got = authorised_request(
        username, "GET",
        f"{API}/{spreadsheet_id}?fields=sheets.properties(sheetId,title)",
    )
    return {s["properties"]["title"]: s["properties"]["sheetId"] for s in got.get("sheets", [])}


def describe(username: str, spreadsheet_id: str) -> dict:
    """What the file already carries, for a re-run to undo before it redoes.

    Conditional formats, protected ranges and filter views all accumulate:
    applied twice they exist twice, and the second copy is invisible until
    somebody wonders why a cell has two rules or why the view menu lists "Jo's
    lines" four times. So formatting reads the current state and deletes before
    it adds — and **anything left out of this mask cannot be deleted**, which is
    how the filter views came to pile up.
    """
    return authorised_request(
        username, "GET",
        f"{API}/{spreadsheet_id}?fields=sheets.properties(sheetId,title),"
        "sheets.protectedRanges(protectedRangeId),"
        "sheets.filterViews(filterViewId,title),"
        "sheets.conditionalFormats",
    )


def batch_update(username: str, spreadsheet_id: str, requests: Sequence[dict]) -> None:
    """Apply structural and formatting changes in one call.

    Every piece of the document's design — frozen rows, merged banners,
    conditional formats, validation, protection — is a request in this list, so
    the whole appearance is applied atomically or not at all. A half-formatted
    sheet is harder to reason about than an unformatted one.
    """
    if not requests:
        return
    authorised_request(
        username, "POST", f"{API}/{spreadsheet_id}:batchUpdate",
        json_body={"requests": list(requests)},
    )


def tab_names(username: str, spreadsheet_id: str) -> list[str]:
    """The tabs the file actually has — used to add one that is missing."""
    got = authorised_request(
        username, "GET", f"{API}/{spreadsheet_id}?fields=sheets.properties.title"
    )
    return [s["properties"]["title"] for s in got.get("sheets", [])]


def add_tab(username: str, spreadsheet_id: str, title: str) -> None:
    authorised_request(
        username, "POST", f"{API}/{spreadsheet_id}:batchUpdate",
        json_body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
    )


def drop_tab(username: str, spreadsheet_id: str, sheet_id_: int) -> None:
    """Remove a tab the layout no longer has.

    Called for tabs this module used to write and does not any more. Leaving one
    behind is worse than removing it: a stale tab full of headings nobody feeds
    reads as current to anybody who opens it.
    """
    authorised_request(
        username, "POST", f"{API}/{spreadsheet_id}:batchUpdate",
        json_body={"requests": [{"deleteSheet": {"sheetId": sheet_id_}}]},
    )


def delete_rows(username: str, spreadsheet_id: str, sheet_id_: int,
                rows: Sequence[int]) -> None:
    """Remove rows from a tab, by their 1-based row number.

    Two rules the API forces, and both are easy to get wrong. `deleteDimension`
    takes **0-based, half-open** indices, so row *n* is ``[n - 1, n)``. And every
    deletion shifts what is below it up, so the rows are removed **bottom-up** —
    top-down would delete the wrong rows from the second request onwards.

    Contiguous runs collapse into one request. That is not only fewer calls: it
    is what keeps a long block of a show's checklist from being taken out a line
    at a time, each shifting the rest.
    """
    ordered = sorted({int(row) for row in rows if int(row) > 0}, reverse=True)
    if not ordered:
        return

    requests: list[dict] = []
    end = start = ordered[0]
    for row in ordered[1:]:
        if row == start - 1:
            start = row
            continue
        requests.append(_delete_range(sheet_id_, start, end))
        end = start = row
    requests.append(_delete_range(sheet_id_, start, end))

    batch_update(username, spreadsheet_id, requests)


def _delete_range(sheet_id_: int, first: int, last: int) -> dict:
    """One run of rows, `first`..`last` inclusive and 1-based, as the API wants it."""
    return {"deleteDimension": {"range": {
        "sheetId": sheet_id_, "dimension": "ROWS",
        "startIndex": first - 1, "endIndex": last,
    }}}


def column(username: str, spreadsheet_id: str, tab: str, letter: str = "A") -> list[str]:
    """One column, top to bottom — how a row is found again.

    The only read this module performs, and it reads identifiers rather than
    content: the id column tells an update which row to overwrite. Reading a
    person's edits is a different job with different rules; see the docstring.
    """
    got = authorised_request(
        username, "GET", f"{API}/{spreadsheet_id}/values/{tab}!{letter}:{letter}"
    )
    return [row[0] if row else "" for row in got.get("values", [])]


def columns(username: str, spreadsheet_id: str, tab: str, span: str) -> list[list[str]]:
    """Several columns at once, rows padded so every row is the same width.

    Sheets omits trailing empty cells, so an unticked checkbox comes back as a
    short row rather than a false one. Padding here means a caller never has to
    remember that, which is the kind of thing a caller forgets exactly once.
    """
    got = authorised_request(
        username, "GET", f"{API}/{spreadsheet_id}/values/{tab}!{span}"
    )
    rows = got.get("values", [])
    width = max((len(r) for r in rows), default=0)
    return [list(r) + [""] * (width - len(r)) for r in rows]


def append(username: str, spreadsheet_id: str, tab: str, rows: Iterable[Sequence[Any]]) -> None:
    """Add rows at the bottom."""
    values = [list(row) for row in rows]
    if not values:
        return
    authorised_request(
        username, "POST",
        f"{API}/{spreadsheet_id}/values/{tab}!A:A:append"
        "?valueInputOption=USER_ENTERED&insertDataOption=INSERT_ROWS",
        json_body={"values": values},
    )


def write_rows(username: str, spreadsheet_id: str,
               updates: Iterable[tuple]) -> None:
    """Overwrite rows anywhere in the document, in a single request.

    Each update is ``(tab, row_number, values)``, the row 1-indexed as the
    spreadsheet numbers it, and each write starts at column A and runs exactly
    as wide as the values given — the same contract `write_row` has, so the
    columns to the right of Cadence's block are still nobody's business but
    their owner's.

    **This exists because of a quota, and the quota is not generous.** Sheets
    allows sixty write requests a minute per user. Written a row at a time, one
    push spent six on banners and headers, forty on the Read me and two per
    checklist line — comfortably over the limit for a single approval, and
    everything past it failed with a 429 that only reached a log. One request
    covers all of it.
    """
    data = [{"range": f"{tab}!A{number}", "values": [list(values)]}
            for tab, number, values in updates]
    if not data:
        return
    authorised_request(
        username, "POST", f"{API}/{spreadsheet_id}/values:batchUpdate",
        json_body={"valueInputOption": "USER_ENTERED", "data": data},
    )


def write_row(
    username: str, spreadsheet_id: str, tab: str, row_number: int, values: Sequence[Any]
) -> None:
    """Overwrite one row, 1-indexed as the spreadsheet numbers them."""
    authorised_request(
        username, "PUT",
        f"{API}/{spreadsheet_id}/values/{tab}!A{row_number}?valueInputOption=USER_ENTERED",
        json_body={"values": [list(values)]},
    )
