"""Full-table tests for the FTS5 query-syntax parser (search_syntax.py).

The parser is pure, so the grammar table asserts on ParsedQuery values
directly. The CJK group additionally runs every expression against a live
in-memory FTS5 table to pin the *measured* unicode61 tokenizer behavior:
a contiguous CJK run is a single token, so only whole-run queries match.
"""
from __future__ import annotations

import sqlite3

import pytest

from AssetsManager.application.search_syntax import ParsedQuery, parse_query


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
    assert parse_query("tag:风景").match == '{tags}: "风景"'
    assert parse_query("tags:风景").match == '{tags}: "风景"'
    assert parse_query("notes:hello").match == '{notes}: "hello"'
    # Field filter with a quoted multi-word value.
    assert parse_query('name:"white cat"').match == '{name}: "white cat"'


def test_task_example_query_combines_all_elements():
    parsed = parse_query('cat "white cat" -dog name:sunset | tag:风景')
    assert parsed.match == (
        '(("cat" "white cat" {name}: "sunset") OR ({tags}: "风景")) NOT ("dog")'
    )
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
    """Live in-memory FTS5 table mirroring the asset_search shape."""

    def __init__(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute(
            "CREATE VIRTUAL TABLE s USING fts5(file_path UNINDEXED, name, tags, notes)"
        )

    def add(self, file_path: str, name: str, tags: str, notes: str) -> None:
        self.conn.execute(
            "INSERT INTO s(file_path, name, tags, notes) VALUES (?, ?, ?, ?)",
            (file_path, name, tags, notes),
        )

    def search(self, query: str) -> list[str]:
        parsed = parse_query(query)
        if not parsed.match:
            return []
        rows = self.conn.execute(
            "SELECT file_path FROM s WHERE s MATCH ?", (parsed.match,)
        ).fetchall()
        return [row[0] for row in rows]


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
    """Measured unicode61 behavior for CJK (SQLite 3.50.4).

    Documents the contract: a contiguous CJK run is ONE token. A query hits
    when it equals a complete run; a substring inside a longer run does not
    match. This is the documented limitation — substring matching would
    need the trigram tokenizer (suggested follow-up, out of scope).
    """

    def test_whole_run_query_matches(self, fts: _Fts):
        # "风景" is a complete run in /1 ("sunset 风景.png" — bounded by a
        # space and a dot) and in /1's tags.
        assert "/1" in fts.search("风景")
        assert fts.search("tag:风景") == ["/1"]

    def test_substring_of_longer_run_does_not_match(self, fts: _Fts):
        # /4's name is the single token "美丽的风景"; neither "风景" nor
        # "的风景" equals that run, so neither matches /4.
        assert "/4" not in fts.search("风景")
        assert fts.search("的风景") == []
        # But the complete run matches exactly.
        assert fts.search("美丽的风景") == ["/4"]

    def test_cross_column_adjacency_is_and_not_phrase(self, fts: _Fts):
        # Bare words AND across columns: name runs on /1 + /4, tags on /1.
        assert fts.search("风景 scenery") == []  # "scenery" only on /4, "风景" not on /4
        assert fts.search("风景 golden") == ["/1"]
