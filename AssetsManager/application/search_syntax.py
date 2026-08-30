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

Output is an FTS5 ``MATCH`` expression for the positive part — exclusions
appended as ``(positives) NOT ("e1" OR "e2")`` with the positive expression
parenthesized first, so no reliance on FTS5's NOT/AND/OR precedence — plus
the raw excluded texts and a ``fallback`` flag set whenever unsupported
syntax had to be sanitized:

- unclosed quotes (an odd quote count; the quoted run is lost);
- ``*`` — FTS5 prefix search is intentionally not exposed; quoting
  neutralizes the star and the flag marks the lost intent;
- unknown ``foo:`` prefixes (FTS5 would reject the unknown column, so the
  word is downgraded to a quoted literal term instead).

Degenerate inputs have defined behavior and never produce an illegal MATCH:
an empty/whitespace query and a pure-exclusion query (``-dog``) both yield
``match=""`` — the search source returns no results for those instead of
executing MATCH.

CJK note (measured on SQLite 3.50.4, unicode61 tokenizer): a contiguous
CJK run is a **single token**, so a query hits a document only when the
query text equals one complete run (e.g. ``风景`` matches ``sunset 风景.png``
where ``风景`` is bounded by separators, but does not match the ``风景``
inside ``美丽的风景.png`` — that run is the single token ``美丽的风景``).
Substring search inside CJK runs needs the trigram tokenizer; that is a
possible follow-up and out of scope here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

__all__ = ["ParsedQuery", "parse_query"]


@dataclass(frozen=True)
class ParsedQuery:
    """Result of parsing one user query into FTS5 terms.

    ``match`` is the FTS5 MATCH expression for the positive part with
    exclusions already applied via NOT; empty means "nothing searchable"
    (empty query or pure exclusion). ``excluded`` keeps the raw excluded
    texts for diagnostics. ``fallback`` marks sanitized unsupported syntax.
    """

    match: str
    excluded: tuple[str, ...] = ()
    fallback: bool = False


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
    """Mutable parse accumulator: OR groups of positive fragments."""

    groups: list[list[str]] = field(default_factory=lambda: [[]])
    excluded_fragments: list[str] = field(default_factory=list)
    excluded_texts: list[str] = field(default_factory=list)
    fallback: bool = False
    pending_field: str | None = None
    pending_exclusion: bool = False

    def add_positive(self, fragment: str) -> None:
        self.groups[-1].append(fragment)

    def add_exclusion(self, fragment: str, text: str) -> None:
        self.excluded_fragments.append(fragment)
        self.excluded_texts.append(text)

    def flush_pending_field(self) -> None:
        """Downgrade a dangling field prefix (``name:`` with no value)."""
        if self.pending_field is not None:
            self.add_positive(_fts_string(self.pending_field + ":"))
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
                _unit_fragment(state, value, column), f"{prefix}:{value}"
            )
        else:
            state.flush_pending_field()
            state.add_positive(_unit_fragment(state, value, column))
        return

    if state.pending_field is not None and not exclusion:
        # This word is the value of a preceding ``name:``-style prefix.
        column = _FIELD_COLUMNS[state.pending_field]
        state.pending_field = None
        state.add_positive(_unit_fragment(state, text, column))
        return

    if ":" in text:
        # Unknown ``foo:bar`` prefix: FTS5 would reject the unknown column,
        # so the whole word is downgraded to a quoted literal term.
        state.fallback = True

    if not text:
        return
    if exclusion:
        state.add_exclusion(_unit_fragment(state, text, None), text)
        return
    state.flush_pending_field()
    state.add_positive(_unit_fragment(state, text, None))


def parse_query(query: str) -> ParsedQuery:
    """Parse one user query string into an FTS5 MATCH expression."""
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
                    state.add_exclusion(_field_fragment(column, text), text)
                else:
                    state.add_exclusion(_fts_string(text), text)
            elif state.pending_field is not None:
                column = _FIELD_COLUMNS[state.pending_field]
                state.pending_field = None
                state.add_positive(_field_fragment(column, text))
            else:
                state.add_positive(_fts_string(text))
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

    groups = [group for group in state.groups if group]
    if not groups:
        return ParsedQuery(
            match="",
            excluded=tuple(state.excluded_texts),
            fallback=fallback or state.fallback,
        )
    if len(groups) == 1:
        positives = " ".join(groups[0])
    else:
        positives = " OR ".join("(" + " ".join(group) + ")" for group in groups)

    if state.excluded_fragments:
        exclusions = " OR ".join(state.excluded_fragments)
        match_sql = f"({positives}) NOT ({exclusions})"
    else:
        match_sql = positives

    return ParsedQuery(
        match=match_sql,
        excluded=tuple(state.excluded_texts),
        fallback=fallback or state.fallback,
    )
