"""Characterise the shared JSON extraction helpers.

Written during the Owl Core migration to lock the invariant that `high_intent`'s
private parse copies behaved identically to the shared module. That package was
retired in R4, so the comparison is gone; these assertions remain because the
shared helpers are still what every agent parses model output with.
"""
import json

import pytest

from agents.shared import jsonparse
from agents.shared.jsonparse import _quote_bare_keys, parse_json_array, parse_json_object


def test_parse_json_plain():
    assert jsonparse.parse_json('{"a": 1}') == {"a": 1}


def test_parse_json_fenced():
    raw = '```json\n{"a": 1, "b": [2, 3]}\n```'
    assert jsonparse.parse_json(raw) == {"a": 1, "b": [2, 3]}


def test_parse_json_bare_fence():
    raw = '```\n{"a": 1}\n```'
    assert jsonparse.parse_json(raw) == {"a": 1}


def test_parse_json_array_direct():
    assert jsonparse.parse_json_array('[1, 2, 3]') == [1, 2, 3]


def test_parse_json_array_from_prose():
    raw = 'Here are the results:\n[{"x": 1}, {"x": 2}]\nThat is all.'
    assert jsonparse.parse_json_array(raw) == [{"x": 1}, {"x": 2}]


def test_parse_json_array_failure_raises():
    with pytest.raises(ValueError):
        jsonparse.parse_json_array("no array here")



# --- terminal-array extraction with prose on both sides ---------------------
# A cited web_search turn narrates before the array and adds a caveat paragraph
# after it. The old first-`[`-to-last-`]` slice swallowed the prose and failed
# to parse, which surfaced as X-ray finding nobody.

def test_parse_json_array_ignores_trailing_prose():
    raw = 'Searched 4 queries.\n[{"x": 1}]\n\nNote: further prospecting would need a [sic] pass.'
    assert jsonparse.parse_json_array(raw) == [{"x": 1}]


def test_parse_json_array_ignores_brackets_inside_strings():
    raw = 'Findings:\n[{"note": "cited [sic] in the filing"}]\ndone.'
    assert jsonparse.parse_json_array(raw) == [{"note": "cited [sic] in the filing"}]


def test_parse_json_array_takes_the_last_array_not_the_first():
    raw = 'Example shape: [{"demo": true}]\nActual results:\n[{"real": 1}, {"real": 2}]'
    assert jsonparse.parse_json_array(raw) == [{"real": 1}, {"real": 2}]


def test_parse_json_array_handles_nested_arrays():
    raw = 'Result:\n[{"tags": ["a", "b"]}]\nEnd.'
    assert jsonparse.parse_json_array(raw) == [{"tags": ["a", "b"]}]


def test_parse_json_array_survives_escaped_quotes_in_values():
    """The case that silently emptied X-ray shortlists.

    A `source_query` naturally contains escaped quotes — `site:linkedin.com
    \\"Acme\\"` — and any hand-rolled bracket matcher that tracks strings while
    walking backwards mis-reads `\\"` as a string boundary, loses the array, and
    reports "found nobody" on a turn that found plenty.
    """
    raw = (
        'Searched 4 queries.\n'
        '[{"full_name": "Jane Doe", '
        '"source_query": "site:linkedin.com \\"Acme Corp\\" (Head OR VP)"}]'
    )
    rows = jsonparse.parse_json_array(raw)
    assert len(rows) == 1
    assert rows[0]["full_name"] == "Jane Doe"
    assert rows[0]["source_query"] == 'site:linkedin.com "Acme Corp" (Head OR VP)'


def test_parse_json_array_prefers_the_richest_array():
    """A restated schema must not win over the filled-in payload."""
    raw = (
        'Shape: [{"full_name": ""}]\n'
        'Results:\n[{"full_name": "A"}, {"full_name": "B"}, {"full_name": "C"}]'
    )
    assert len(jsonparse.parse_json_array(raw)) == 3


class TestTruncatedArrays:
    """A response cut off by `max_tokens` is a well-formed prefix with no closing
    bracket. The outer array therefore fails to decode, and the first array that
    *does* decode is a nested one — `options`, `tags`, whatever the objects
    carry. Returning that is worse than returning nothing: the caller gets a list
    of the right type and the wrong meaning, and reports "no usable items" for
    what is really a truncated answer.
    """

    def _batch(self, n=10):
        return json.dumps([{
            "type": "mcq",
            "question": f"Question {i} about PTP holdover?",
            "options": ["Rubidium", "Quartz OCXO", "TCXO", "None of these"],
            "correct": 0,
            "explanation": "Rubidium holds over longest because it ages far more slowly.",
        } for i in range(n)], indent=2)

    def test_never_returns_a_nested_array_in_place_of_a_truncated_one(self):
        cut = self._batch()[: int(len(self._batch()) * 0.75)]
        out = parse_json_array(cut)
        assert all(isinstance(item, dict) for item in out), (
            "a nested options array was returned as if it were the payload"
        )

    def test_salvages_the_complete_objects_from_a_truncated_array(self):
        full = self._batch(10)
        out = parse_json_array(full[: int(len(full) * 0.75)])
        assert 1 <= len(out) < 10
        assert out[0]["question"].startswith("Question 0")

    def test_an_intact_array_is_unaffected(self):
        out = parse_json_array(self._batch(3))
        assert len(out) == 3
        assert out[0]["type"] == "mcq"

    def test_a_fenced_intact_array_is_unaffected(self):
        out = parse_json_array("```json\n" + self._batch(2) + "\n```")
        assert len(out) == 2

    def test_prose_around_an_intact_array_is_unaffected(self):
        out = parse_json_array("Here you go:\n" + self._batch(2) + "\nHope that helps.")
        assert len(out) == 2

    def test_truncated_before_any_object_completes_still_raises(self):
        with pytest.raises(ValueError):
            parse_json_array('[\n  {\n    "type": "mcq",\n    "question": "half a qu')


# ── A bare key, repaired ────────────────────────────────────────────────────
#
# Observed live: Sonnet writing a nine-account target list dropped the quotes on
# one key — `geography: "Sweden / Nordics"` — in row two of an otherwise perfect
# three-thousand-token answer, and strict JSON discarded all of it. One slip
# costing a whole run is the wrong trade when the slip is unambiguous.
#
# The repair is the **last** thing tried, only in the best-effort object path, and
# it inserts quotes and nothing else. These pin the two halves of that: that it
# fixes the real case, and that it never reaches inside a string.

def test_a_bare_key_is_repaired():
    assert parse_json_object('{"a": 1, geography: "Sweden / Nordics"}') == {
        "a": 1, "geography": "Sweden / Nordics",
    }


def test_a_bare_first_key_is_repaired():
    assert parse_json_object('{account: "Meridian Towers"}') == {"account": "Meridian Towers"}


def test_a_hyphenated_bare_key_is_repaired():
    assert parse_json_object('{next-due: "2026-09-20"}') == {"next-due": "2026-09-20"}


def test_a_bare_key_inside_a_nested_object_is_repaired():
    assert parse_json_object('{"a": {inner: 1}}') == {"a": {"inner": 1}}


def test_a_colon_inside_a_string_is_prose_and_is_left_alone():
    """A note reading "the site: Madrid" must survive exactly as written."""
    assert parse_json_object('{"note": "the site: Madrid", "n": 1}') == {
        "note": "the site: Madrid", "n": 1,
    }


def test_a_key_like_word_inside_a_string_is_not_quoted():
    assert parse_json_object('{"note": "geography: Sweden", "n": 1}') == {
        "note": "geography: Sweden", "n": 1,
    }


def test_an_escaped_quote_does_not_confuse_the_scan():
    assert parse_json_object('{"note": "he said \\"yes\\"", n: 2}') == {
        "note": 'he said "yes"', "n": 2,
    }


def test_an_array_element_is_never_treated_as_a_key():
    assert parse_json_object('{"a": [1, 2], "b": 3}') == {"a": [1, 2], "b": 3}


def test_a_literal_is_not_quoted():
    assert parse_json_object('{"a": true, "b": null, "c": 1.5}') == {
        "a": True, "b": None, "c": 1.5,
    }


def test_well_formed_json_is_untouched():
    """The repair runs only after strict parsing has already failed."""
    assert parse_json_object('{"a": 1}') == {"a": 1}
    assert _quote_bare_keys('{"a": 1}') == '{"a": 1}'


def test_something_it_cannot_repair_still_raises():
    with pytest.raises(ValueError, match="could not parse JSON object"):
        parse_json_object('{"a": 1,,, "b"}')
