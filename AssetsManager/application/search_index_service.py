"""Application-layer incremental maintainer for the ``asset_search`` FTS index.

The FTS5 virtual table (migration v39) aggregates one document per
``file_path`` from three sources — ``assets.name``, ``file_tags`` and
``file_meta.notes`` — so it cannot be maintained by triggers without
churning the whole index on every assets rescan (the scanner publishes
rows with DELETE+INSERT). Instead, the writers of those sources call into
this service after their own commit:

- ``TagService`` after add/remove tag, remove-file, tag rename/delete;
- ``MetadataService`` after notes/urls saves;
- ``AssetIndexService`` after a directory scan published changed paths.

Contract (mirrors the ``ActivityRecorder`` swallow-on-error semantics): a
reindex failure is logged and swallowed — full-text search is a derived,
rebuildable projection, so it must never fail or delay the operation that
dirtied it. A stale/missing document degrades search recall only until the
next ``reindex_file``/``reindex_all``.
"""
from __future__ import annotations

import logging
from pathlib import Path
from sqlite3 import Connection
from typing import Callable, Iterable

from AssetsManager.core.database import db_write_lock
from AssetsManager.core.schema_defs import (
    ASSET_SEARCH_FTS_SCHEMA,
    ASSET_SEARCH_SEED_SQL,
)

_log = logging.getLogger(__name__)

#: Bound the DELETE ... WHERE file_path IN (...) parameter lists. Modern
#: SQLite raises the variable limit far above this, but chunking keeps the
#: statement valid on every build and bounds one delete scan to a bounded
#: path set.
_CHUNK_SIZE = 500

# One document insert: aggregate the three sources per path with indexed
# key lookups (assets.file_path is UNIQUE, file_tags PK (file_path, tag),
# file_meta PK file_path). Used after the chunk DELETE, so no NOT IN guard
# is needed here — the delete-then-insert pair is the upsert.
_DOCUMENT_UPSERT_SQL = (
    "INSERT INTO asset_search(file_path, name, tags, notes) "
    "SELECT ?, "
    "COALESCE((SELECT name FROM assets WHERE file_path = ?), ''), "
    "COALESCE((SELECT group_concat(tag, ' ') FROM file_tags WHERE file_path = ?), ''), "
    "COALESCE((SELECT notes FROM file_meta WHERE file_path = ?), '')"
)


class SearchIndexService:
    """Keep the per-library ``asset_search`` FTS index in sync with its sources."""

    def __init__(self, connection_provider: Callable[[], Connection]):
        self._connection_provider = connection_provider

    # ── Incremental maintenance ──────────────────────────────────

    def reindex_file(self, file_path: str | Path) -> None:
        """Re-aggregate the document for one path; never raises."""
        self.reindex_files((file_path,))

    def reindex_files(self, file_paths: Iterable[str | Path]) -> int:
        """Re-aggregate documents for many paths; never raises.

        Returns the number of documents written. Paths are deduplicated and
        processed in chunks so one delete scan covers a bounded path set.
        """
        paths: list[str] = []
        seen: set[str] = set()
        for path in file_paths:
            key = str(Path(path))
            if key and key not in seen:
                seen.add(key)
                paths.append(key)
        if not paths:
            return 0
        written = 0
        try:
            conn = self._connection_provider()
            if conn is None:
                return 0
            with db_write_lock(conn):
                # A caller-owned outer transaction (if any) keeps ownership:
                # writes join it and the caller's commit finalizes them, so
                # a rollback cannot leave the index describing uncommitted
                # source rows.
                owned_commit = not conn.in_transaction
                try:
                    self._ensure_table(conn)
                    for start in range(0, len(paths), _CHUNK_SIZE):
                        chunk = paths[start:start + _CHUNK_SIZE]
                        placeholders = ", ".join("?" for _ in chunk)
                        conn.execute(
                            f"DELETE FROM asset_search WHERE file_path IN ({placeholders})",
                            chunk,
                        )
                        conn.executemany(
                            _DOCUMENT_UPSERT_SQL,
                            [(path, path, path, path) for path in chunk],
                        )
                        written += len(chunk)
                    if owned_commit:
                        conn.commit()
                except Exception:
                    # Swallowing the failure must not leave an open implicit
                    # transaction behind (the first DML opened one): roll
                    # back what this call wrote when it owned the commit.
                    # A caller-owned transaction is left for its owner.
                    if owned_commit and conn.in_transaction:
                        conn.rollback()
                    raise
        except Exception:
            _log.warning("Search index reindex failed", exc_info=True)
        return written

    def reindex_all(self) -> int:
        """Rebuild the whole index from its three sources; never raises.

        Runs the shared migration v39 seed SQL after clearing the table;
        its ``NOT IN`` idempotency guard is trivially true on the emptied
        table, so one constant serves both callers.
        """
        try:
            conn = self._connection_provider()
            if conn is None:
                return 0
            with db_write_lock(conn):
                owned_commit = not conn.in_transaction
                try:
                    self._ensure_table(conn)
                    conn.execute("DELETE FROM asset_search")
                    for statement in ASSET_SEARCH_SEED_SQL.split(";"):
                        if sql := statement.strip():
                            conn.execute(sql)
                    count = int(conn.execute("SELECT count(*) FROM asset_search").fetchone()[0])
                    if owned_commit:
                        conn.commit()
                    return count
                except Exception:
                    # Mirror reindex_files: never leak an open implicit
                    # transaction when this call owned the commit.
                    if owned_commit and conn.in_transaction:
                        conn.rollback()
                    raise
        except Exception:
            _log.warning("Search index rebuild failed", exc_info=True)
            return 0

    def search_file_paths(self, query: str, *, limit: int = 10_000) -> list[str]:
        """Return the file_paths of documents matching the query text.

        The query is parsed with the shared syntax parser (bare words AND,
        ``|`` OR, ``-`` exclusion, quoted phrases, ``name:``/``tag:``/
        ``notes:`` field filters). Used by smart-collection evaluation; any
        failure (missing table, malformed MATCH) degrades to no matches.
        """
        from AssetsManager.application.search_syntax import parse_query

        try:
            parsed = parse_query(query)
            if not parsed.match:
                return []
            return self.match_file_paths(parsed.match, limit=int(limit))
        except Exception:
            _log.warning("Search index path lookup failed", exc_info=True)
            return []

    def match_file_paths(
        self,
        match: str,
        *,
        limit: int = 10_000,
        db_conn: Connection | None = None,
    ) -> list[str]:
        """Execute one already-parsed FTS5 ``MATCH`` expression.

        Unlike the maintenance and lookup helpers above this is a strict
        read: a missing table or a bad expression raises, and the caller
        owns the error mapping (``SearchService.search_by_fts_detailed``
        degrades it to an ERROR source instead of a 500). ``db_conn`` lets
        a caller that already resolved a validated session connection keep
        one identity; otherwise the bound provider is used.
        """
        conn = db_conn if db_conn is not None else self._connection_provider()
        if conn is None:
            return []
        rows = conn.execute(
            "SELECT file_path FROM asset_search "
            "WHERE asset_search MATCH ? LIMIT ?",
            (match, int(limit)),
        ).fetchall()
        return [str(row[0]) for row in rows]

    # ── Internals ────────────────────────────────────────────────

    @staticmethod
    def _ensure_table(conn: Connection) -> None:
        """Create the FTS table when absent.

        Migration v39 owns provisioning for real databases; this idempotent
        DDL keeps the maintainer usable on fixtures/legacy connections
        without making the writers depend on migration timing.
        """
        for statement in ASSET_SEARCH_FTS_SCHEMA.split(";"):
            if sql := statement.strip():
                conn.execute(sql)
