"""Pure query-syntax parser for the FTS5 full-text search source.

Zero dependencies and no I/O — a string in, a :class:`ParsedQuery` out — so
the whole grammar is table-testable. Supported syntax:

- bare words are AND-combined            ``cat dog``
- ``|`` separates OR groups              ``cat | dog``
- ``-word`` / ``-"phrase"`` excludes     ``cat -dog``
- double quotes form phrases             ``"white cat"``
- field filters                          ``name:sunset  tag:风景  notes:hello``
  (``tag:`` maps to the FTS ``tags`` column; ``tags:`` is an alias; a space
  after the colon is allowed, ``name: sunset`` == ``name:sunset``)

Dual-track matching (v40 trigram rebuild). The asset_search index uses the
``trigram`` tokenizer, which makes every phrase of **3+ code points** a
substring match but cannot express shorter queries (a 1-2 code-point phrase
forms no trigram and would match nothing). The parser therefore tags every
term with its track and the output carries both halves:

- ``match`` is the FTS5 ``MATCH`` expression built from the **long**
  (>=3 code points) positives only, with the long exclusions appended as
  ``(positives) NOT ("e1" OR "e2")`` — a prefilter, never the whole truth;
- ``groups`` / ``excluded_units`` keep the full predicate as OR-groups of
  AND-ed :class:`QueryUnit` values (and the exclusion units). The caller
  runs :func:`make_row_predicate` over the candidate rows to apply the
  short (1-2 code point) terms and every exclusion exactly, case-folded,
  as substring checks. When a whole OR group has no long term the FTS
  prefilter cannot cover that group's rows; ``needs_full_scan`` tells the
  caller to scan the index directly instead of running MATCH.

Other semantics are unchanged: unclosed quotes (an odd quote count; the
quoted run is lost), ``*`` (prefix search is intentionally not exposed;
quoting neutralizes the star) and unknown ``foo:`` prefixes (the word is
downgraded to a quoted literal term) set the ``fallback`` flag. Degenerate
inputs have defined behavior and never produce an illegal MATCH: an
empty/whitespace query and a pure-exclusion query (``-dog``) both yield
``match=""`` with no groups — the search source returns no results for
those instead of executing anything.

CJK note (v40): a 2-character query such as ``风景`` now matches
``美丽的风景.png`` through the post-verification track; a 3+ character
query matches through the trigram MATCH track. Both tracks are substring
semantics, so the two agree on every candidate row.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

__all__ = [
    "ParsedQuery",
    "QueryUnit",
    "make_row_predicate",
    "parse_query",
]

#: Minimum code-point length for a term to ride the FTS5 MATCH (trigram)
#: track. Shorter terms are post-verified against candidate rows instead.
MIN_FTS_LENGTH = 3


@dataclass(frozen=True)
class QueryUnit:
    """One positive or excluded term with its optional column scope.

    ``column`` is ``None`` for an unscoped term (match any of name/tags/
    notes) or one of the FTS5 column names ``name``/``tags``/``notes``.
    """

    text: str
    column: str | None = None

    @property
    def is_fts(self) -> bool:
        """True when the term is long enough for the trigram MATCH track."""
        return len(self.text) >= MIN_FTS_LENGTH


@dataclass(frozen=True)
class ParsedQuery:
    """Result of parsing one user query into dual-track FTS5 terms.

    ``match`` is the FTS5 MATCH **prefilter**: the long positive terms with
    exclusions already applied via NOT; empty means the prefilter matches
    nothing (empty query, pure exclusion, or only-short positives — the
    latter is signalled by ``needs_full_scan`` instead). ``groups`` keeps
    the complete positive predicate (OR-groups of AND-ed units, short terms
    included) and ``excluded_units`` the exclusion units; callers apply
    them with :func:`make_row_predicate`. ``excluded`` keeps the raw
    excluded texts for diagnostics. ``fallback`` marks sanitized
    unsupported syntax.
    """

    match: str
    groups: tuple[tuple[QueryUnit, ...], ...] = ()
    excluded: tuple[str, ...] = ()
    excluded_units: tuple[QueryUnit, ...] = ()
    fallback: bool = False

    @property
    def needs_full_scan(self) -> bool:
        """True when some OR group has no long term.

        The MATCH prefilter is built from long terms only, so a group made
        entirely of short (1-2 code point) terms contributes no MATCH
        fragment and its rows are invisible to the prefilter. The caller
        must then scan the index and post-verify every row.
        """
        return bool(self.groups) and any(
            not any(unit.is_fts for unit in group) for group in self.groups
        )


#: Input tokens: quoted phrase (with "" escapes), a standalone ``|``, or a
#: bare word (any run of non-space, non-pipe, non-quote characters).
_TOKEN_RE = re.compile(
    r'"(?P<phrase>(?:[^"]|"")*)"'
    r"|(?P<pipe>\|)"
    r"|(?P<word>[^\s|\"]+)"
)

#: User-facing field prefixes mapped to FTS5 column names. ``tag:`` is the
#: documented spelling; ``tags:`` matches the physical column name.
_FIELD_COLUMNS = {
    "name": "name",
    "tag": "tags",
    "tags": "tags",
    "notes": "notes",
}

_FIELD_WORD_RE = re.compile(
    r"^(" + "|".join(_FIELD_COLUMNS) + r"):(.*)$",
    re.IGNORECASE,
)

# Characters whose FTS5 meaning is lost by quoting and which therefore mark
# sanitized intent (prefix search is the practical one).
_UNSUPPORTED_CHARS = ("*",)


def _fts_string(text: str) -> str:
    """Quote one term/phrase for FTS5 (doubling embedded double quotes)."""
    return '"' + text.replace('"', '""') + '"'


def _field_fragment(column: str, text: str) -> str:
    """Build a column-filtered fragment: ``{column}: "text"``."""
    return "{" + column + "}: " + _fts_string(text)


@dataclass
class _State:
    """Mutable parse accumulator: OR groups of positive fragments.

    Every positive/excluded term is kept as a ``(fragment, QueryUnit)``
    pair so the MATCH expression can drop short terms while the predicate
    keeps the complete term list.
    """

    groups: list[list[tuple[str, QueryUnit]]] = field(default_factory=lambda: [[]])
    excluded_fragments: list[str] = field(default_factory=list)
    excluded_units: list[QueryUnit] = field(default_factory=list)
    excluded_texts: list[str] = field(default_factory=list)
    fallback: bool = False
    pending_field: str | None = None
    pending_exclusion: bool = False

    def add_positive(self, fragment: str, unit: QueryUnit) -> None:
        self.groups[-1].append((fragment, unit))

    def add_exclusion(self, fragment: str, text: str, unit: QueryUnit) -> None:
        self.excluded_fragments.append(fragment)
        self.excluded_units.append(unit)
        self.excluded_texts.append(text)

    def flush_pending_field(self) -> None:
        """Downgrade a dangling field prefix (``name:`` with no value)."""
        if self.pending_field is not None:
            text = self.pending_field + ":"
            self.add_positive(_fts_string(text), QueryUnit(text))
            self.pending_field = None


def _unit_fragment(state: _State, text: str, column: str | None) -> str:
    """Build one fragment, flagging syntax whose intent quoting loses."""
    if any(char in text for char in _UNSUPPORTED_CHARS):
        state.fallback = True
    if column is None:
        return _fts_string(text)
    return _field_fragment(column, text)


def _feed_word(state: _State, word: str) -> None:
    """Classify and consume one bare word."""
    exclusion = state.pending_exclusion or (word.startswith("-") and len(word) > 1)
    was_marker = word == "-"
    state.pending_exclusion = was_marker
    if was_marker:
        # A lone ``-`` is an exclusion marker for the next token, not a term.
        return
    text = word[1:] if (exclusion and word.startswith("-")) else word

    # A field filter: either ``prefix:value`` inline, or a dangling
    # ``prefix:`` whose value arrives as the next token.
    prefix: str | None = None
    value: str | None = None
    if text.endswith(":") and text[:-1].lower() in _FIELD_COLUMNS:
        prefix = text[:-1].lower()
        value = ""
    else:
        field_match = _FIELD_WORD_RE.match(text)
        if field_match is not None:
            prefix = field_match.group(1).lower()
            value = field_match.group(2)

    if prefix is not None:
        column = _FIELD_COLUMNS[prefix]
        if not value:
            if exclusion:
                # ``-name:"white cat"``: keep both markers so the next
                # quoted token becomes a column-filtered exclusion.
                state.pending_exclusion = True
                state.pending_field = prefix
            else:
                state.flush_pending_field()
                state.pending_field = prefix
            return
        if exclusion:
            state.add_exclusion(
                _unit_fragment(state, value, column),
                f"{prefix}:{value}",
                QueryUnit(value, column),
            )
        else:
            state.flush_pending_field()
            state.add_positive(_unit_fragment(state, value, column), QueryUnit(value, column))
        return

    if state.pending_field is not None and not exclusion:
        # This word is the value of a preceding ``name:``-style prefix.
        column = _FIELD_COLUMNS[state.pending_field]
        state.pending_field = None
        state.add_positive(_unit_fragment(state, text, column), QueryUnit(text, column))
        return

    if ":" in text:
        # Unknown ``foo:bar`` prefix: FTS5 would reject the unknown column,
        # so the whole word is downgraded to a quoted literal term.
        state.fallback = True

    if not text:
        return
    if exclusion:
        state.add_exclusion(
            _unit_fragment(state, text, None), text, QueryUnit(text)
        )
        return
    state.flush_pending_field()
    state.add_positive(_unit_fragment(state, text, None), QueryUnit(text))


def parse_query(query: str) -> ParsedQuery:
    """Parse one user query string into a dual-track FTS5 query plan."""
    if not isinstance(query, str):
        raise TypeError("query must be a string")

    state = _State()
    fallback = query.count('"') % 2 == 1  # unclosed quote: phrase intent lost

    for match in _TOKEN_RE.finditer(query):
        phrase = match.group("phrase")
        if phrase is not None:
            text = phrase.replace('""', '"')
            if any(char in text for char in _UNSUPPORTED_CHARS):
                fallback = True
            if state.pending_exclusion:
                state.pending_exclusion = False
                if state.pending_field is not None:
                    column = _FIELD_COLUMNS[state.pending_field]
                    state.pending_field = None
                    state.add_exclusion(
                        _field_fragment(column, text), text, QueryUnit(text, column)
                    )
                else:
                    state.add_exclusion(_fts_string(text), text, QueryUnit(text))
            elif state.pending_field is not None:
                column = _FIELD_COLUMNS[state.pending_field]
                state.pending_field = None
                state.add_positive(
                    _field_fragment(column, text), QueryUnit(text, column)
                )
            else:
                state.add_positive(_fts_string(text), QueryUnit(text))
            continue
        if match.group("pipe") is not None:
            state.flush_pending_field()
            state.pending_exclusion = False
            state.groups.append([])
            continue
        word = match.group("word")
        if word:
            _feed_word(state, word)

    state.flush_pending_field()

    # The MATCH prefilter keeps only long (trigram-expressible) fragments.
    # Short fragments would form no trigram and match nothing, so folding
    # them into a group would kill the group's long terms too.
    match_groups = [
        [fragment for fragment, unit in group if unit.is_fts]
        for group in state.groups
        if group
    ]
    match_groups = [fragments for fragments in match_groups if fragments]
    long_exclusions = [
        fragment
        for fragment, unit in zip(state.excluded_fragments, state.excluded_units)
        if unit.is_fts
    ]

    if not match_groups:
        match_sql = ""
    elif len(match_groups) == 1:
        positives = " ".join(match_groups[0])
        match_sql = (
            f"({positives}) NOT ({' OR '.join(long_exclusions)})"
            if long_exclusions
            else positives
        )
    else:
        positives = " OR ".join("(" + " ".join(group) + ")" for group in match_groups)
        match_sql = (
            f"({positives}) NOT ({' OR '.join(long_exclusions)})"
            if long_exclusions
            else positives
        )

    return ParsedQuery(
        match=match_sql,
        groups=tuple(
            tuple(unit for _fragment, unit in group) for group in state.groups if group
        ),
        excluded=tuple(state.excluded_texts),
        excluded_units=tuple(state.excluded_units),
        fallback=fallback or state.fallback,
    )


def _unit_matches(unit: QueryUnit, name: str, tags: str, notes: str) -> bool:
    """Case-folded substring check of one unit against a document row."""
    needle = unit.text.casefold()
    if unit.column is None:
        return (
            needle in name.casefold()
            or needle in tags.casefold()
            or needle in notes.casefold()
        )
    column_text = {"name": name, "tags": tags, "notes": notes}[unit.column]
    return needle in column_text.casefold()


def make_row_predicate(
    parsed: ParsedQuery,
) -> Callable[[str, str, str], bool]:
    """Build the exact predicate for one parsed query.

    The returned callable takes a document row's ``(name, tags, notes)``
    texts and reports whether the row satisfies the query: OR over groups
    of AND-ed terms, minus every exclusion. All comparisons are
    case-folded substring checks, which agrees with the trigram MATCH
    track for long terms and implements the short terms exactly.
    """
    groups = parsed.groups
    excluded = parsed.excluded_units

    def predicate(name: str, tags: str, notes: str) -> bool:
        if not groups:
            # No positive term: empty query or pure exclusion — nothing
            # matches by contract (the MATCH track returns nothing too).
            return False
        if any(_unit_matches(unit, name, tags, notes) for unit in excluded):
            return False
        return any(
            all(_unit_matches(unit, name, tags, notes) for unit in group)
            for group in groups
        )

    return predicate
