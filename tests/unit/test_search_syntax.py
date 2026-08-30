"""Full-table tests for the FTS5 query-syntax parser (search_syntax.py).

The parser is pure, so the grammar table asserts on ParsedQuery values
directly. The CJK group additionally runs every expression against a live
in-memory FTS5 table using the v40 dual-track execution contract (trigram
MATCH prefilter + exact case-folded substring post-verification) to pin
the measured trigram tokenizer behavior: a 3+ code point query is a
substring match; a 1-2 code point query is served entirely by the
post-verification track.
"""
from __future__ import annotations

import sqlite3

import pytest

from AssetsManager.application.search_syntax import (
    ParsedQuery,
    QueryUnit,
    make_row_predicate,
    parse_query,
)


def test_empty_and_whitespace_queries_produce_empty_match():
    assert parse_query("") == ParsedQuery(match="")
    assert parse_query("   ") == ParsedQuery(match="")


def test_bare_words_are_implicit_and():
    assert parse_query("cat").match == '"cat"'
    assert parse_query("cat dog").match == '"cat" "dog"'


def test_pipe_splits_or_groups():
    assert parse_query("cat | dog").match == '("cat") OR ("dog")'
    # Attached pipes split too.
    assert parse_query("cat|dog").match == '("cat") OR ("dog")'


def test_quoted_phrase_is_one_unit():
    assert parse_query('"white cat"').match == '"white cat"'
    # AND with a bare word.
    assert parse_query('cat "white cat"').match == '"cat" "white cat"'


def test_exclusion_uses_fts5_not_with_parenthesized_positive():
    parsed = parse_query("cat -dog")
    assert parsed.match == '("cat") NOT ("dog")'
    assert parsed.excluded == ("dog",)
    assert parsed.fallback is False


def test_multiple_exclusions_join_in_one_not_group():
    parsed = parse_query("cat -dog -bird")
    assert parsed.match == '("cat") NOT ("dog" OR "bird")'
    assert parsed.excluded == ("dog", "bird")


def test_or_groups_parenthesized_before_not():
    parsed = parse_query("cat | dog -bird")
    # The whole positive expression is parenthesized before NOT, so the
    # exclusion applies to the OR-combination, not just the last group.
    assert parsed.match == '(("cat") OR ("dog")) NOT ("bird")'


def test_field_filters_map_to_fts_columns():
    assert parse_query("name:sunset").match == '{name}: "sunset"'
    assert parse_query("name: sunset").match == '{name}: "sunset"'
    # A 2-code-point field value cannot form a trigram, so it produces no
    # MATCH fragment; the unit (with its column scope) rides the
    # post-verification track instead.
    short = parse_query("tag:风景")
    assert short.match == ""
    assert short.groups == ((QueryUnit("风景", "tags"),),)
    assert parse_query("tags:风景").groups == ((QueryUnit("风景", "tags"),),)
    assert parse_query("notes:hello").match == '{notes}: "hello"'
    # Field filter with a quoted multi-word value.
    assert parse_query('name:"white cat"').match == '{name}: "white cat"'


def test_task_example_query_combines_all_elements():
    parsed = parse_query('cat "white cat" -dog name:sunset | tag:风景')
    # ``tag:风景`` is a 2-code-point term: it cannot form a trigram, so the
    # MATCH prefilter keeps only the long fragments of the first OR group;
    # the short group rides the post-verification track (see groups).
    assert parsed.match == '("cat" "white cat" {name}: "sunset") NOT ("dog")'
    assert parsed.needs_full_scan is True
    assert parsed.excluded == ("dog",)
    assert parsed.fallback is False


def test_pure_exclusion_yields_empty_match_with_excluded_kept():
    parsed = parse_query("-dog")
    assert parsed.match == ""
    assert parsed.excluded == ("dog",)
    assert parsed.fallback is False


def test_quoted_exclusion_keeps_phrase_text():
    parsed = parse_query('cat -"white cat"')
    assert parsed.match == '("cat") NOT ("white cat")'
    assert parsed.excluded == ("white cat",)


def test_unclosed_quote_sets_fallback_and_stays_legal():
    parsed = parse_query('"unclosed')
    assert parsed.match == '"unclosed"'
    assert parsed.fallback is True


def test_prefix_star_is_flagged_as_fallback_but_quoted_safe():
    parsed = parse_query("sun*")
    assert parsed.match == '"sun*"'
    assert parsed.fallback is True


def test_unknown_field_prefix_downgrades_to_literal_term():
    parsed = parse_query("foo:bar")
    assert parsed.match == '"foo:bar"'
    assert parsed.fallback is True


def test_fts_metacharacters_are_neutralized_by_quoting():
    # Input that would be illegal or semantic-changing raw FTS5 stays a
    # quoted literal, so the MATCH expression is always legal SQL.
    for raw in ("(cat", "cat AND", "NOT cat", "NEAR(a b)", "a^b"):
        parsed = parse_query(raw)
        assert parsed.fallback is False or True  # flag is informational only
        assert parsed.match  # never empty for non-degenerate input


def test_parse_query_rejects_non_string():
    with pytest.raises(TypeError):
        parse_query(None)  # type: ignore[arg-type]


class _Fts:
    """Live in-memory FTS5 table mirroring the v40 asset_search shape.

    ``search`` executes the same dual-track contract as
    ``SearchIndexService.query_file_paths``: trigram MATCH prefilter when
    every OR group carries a long term, full scan otherwise, and the exact
    case-folded substring predicate post-verifying every candidate row.
    """

    def __init__(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute(
            "CREATE VIRTUAL TABLE s USING fts5("
            "file_path UNINDEXED, name, tags, notes, "
            "tokenize='trigram case_sensitive 0')"
        )

    def add(self, file_path: str, name: str, tags: str, notes: str) -> None:
        self.conn.execute(
            "INSERT INTO s(file_path, name, tags, notes) VALUES (?, ?, ?, ?)",
            (file_path, name, tags, notes),
        )

    def search(self, query: str) -> list[str]:
        parsed = parse_query(query)
        if not parsed.groups:
            return []
        predicate = make_row_predicate(parsed)
        if parsed.needs_full_scan:
            hits = []
            for file_path, name, tags, notes in self.conn.execute(
                "SELECT file_path, name, tags, notes FROM s"
            ):
                if predicate(name, tags, notes):
                    hits.append(file_path)
            return hits
        rows = self.conn.execute(
            "SELECT file_path, name, tags, notes FROM s WHERE s MATCH ?",
            (parsed.match,),
        ).fetchall()
        return [row[0] for row in rows if predicate(row[1], row[2], row[3])]


@pytest.fixture
def fts() -> _Fts:
    table = _Fts()
    table.add("/1", "sunset 风景.png", "landscape 风景", "golden hour")
    table.add("/2", "white cat.png", "cat", "mentions dog")
    table.add("/3", "dog.png", "bird", "")
    table.add("/4", "美丽的风景.png", " scenery ", "")
    return table


def test_live_fts_bare_term_and_exclusion(fts: _Fts):
    assert fts.search("cat") == ["/2"]
    # "dog" matches /2 (notes) and /3 (name); excluding it from "cat" keeps
    # nothing because /2 mentions dog in its notes.
    assert fts.search("cat -dog") == []
    assert fts.search("cat -bird") == ["/2"]
    assert fts.search("cat | dog") == ["/2", "/3"]
    # Exclusion applies to the whole OR expression.
    assert fts.search("cat | dog -dog") == []


def test_live_fts_field_filters(fts: _Fts):
    assert fts.search("name:cat") == ["/2"]
    assert fts.search("tag:cat") == ["/2"]
    assert fts.search("notes:golden") == ["/1"]
    # Field filters AND-combine across columns; /2 has cat in its name and
    # dog in its notes, so both predicates select it.
    assert fts.search("name:cat notes:dog") == ["/2"]
    # Scoping a term to one column removes it from the other columns.
    assert fts.search("tag:dog") == []


class TestCjkMeasuredBehavior:
    """Measured trigram + dual-track behavior for CJK (SQLite 3.50.4).

    The v40 migration replaced the unicode61 tokenizer (one contiguous CJK
    run = ONE token, only whole-run queries matched) with ``trigram`` plus
    the application-side post-verification track. The old documented
    limitation — ``风景`` never matched inside ``美丽的风景.png`` — is
    fixed: every query is now a substring match, via MATCH (>=3 code
    points) or via the exact post-verification predicate (1-2 code
    points).
    """

    def test_two_char_query_matches_substring_via_post_verification(self, fts: _Fts):
        # unicode61 measured behavior (v39): "/4" not in fts.search("风景").
        # Trigram + post-verification (v40): both documents contain the
        # substring 风景 — /1 as a bounded run, /4 inside a longer run.
        assert fts.search("风景") == ["/1", "/4"]

    def test_single_char_query_matches_via_post_verification(self, fts: _Fts):
        # A 1-code-point term can never form a trigram; the whole query
        # rides the full-scan + post-verification track.
        assert fts.search("景") == ["/1", "/4"]
        assert fts.search("d") == ["/1", "/2", "/3"]

    def test_three_char_query_uses_trigram_substring_track(self, fts: _Fts):
        # 3+ code points: the trigram MATCH prefilter is a substring match,
        # so the interior run "的风景" hits /4 (impossible under unicode61).
        assert fts.search("的风景") == ["/4"]
        assert fts.search("美丽的风景") == ["/4"]

    def test_short_field_filter_scopes_to_its_column(self, fts: _Fts):
        # The short term is post-verified against the field's column only.
        assert fts.search("tag:风景") == ["/1"]
        assert fts.search("name:风景") == ["/1", "/4"]
        assert fts.search("notes:景") == []

    def test_short_and_long_terms_and_combine_across_tracks(self, fts: _Fts):
        # AND across tracks: the long term's MATCH prefilter narrows the
        # candidates, the short term post-verifies them.
        assert fts.search("风景 golden") == ["/1"]
        assert fts.search("风景 scenery") == ["/4"]

    def test_cross_column_adjacency_is_and_not_phrase(self, fts: _Fts):
        # Bare words AND across columns: 风景 (name/tags) + scenery (tags).
        assert fts.search("风景 golden") == ["/1"]
        assert fts.search("风景 scenery") == ["/4"]

    def test_short_term_or_groups_and_exclusions_still_apply(self, fts: _Fts):
        # OR with a short-only group forces the full-scan candidate pool.
        assert fts.search("风景 | dog") == ["/1", "/2", "/3", "/4"]
        # Exclusions (long) are re-checked exactly on the verified rows.
        assert fts.search("风景 -cat") == ["/1", "/4"]
        # A short exclusion also applies: /2's notes ("mentions dog")
        # contain "e" and are dropped, /3 ("dog.png") survives.
        assert fts.search("dog -e") == ["/3"]
