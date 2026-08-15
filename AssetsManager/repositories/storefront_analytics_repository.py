"""Session-bound persistence for privacy-preserving storefront visit counters."""
from __future__ import annotations

import time

from AssetsManager.repositories.shop_repository import _CommerceRepository, _repository_operation, _transaction, locked_read


class StorefrontAnalyticsRepository(_CommerceRepository):
    """Persist daily deduplicated store visits without recording client identity.

    ``visitor_hash`` is a SHA-256 digest of a signed, random HttpOnly cookie.
    The raw cookie is never persisted; the short-lived visitor table is only
    used to make one dashboard view count once per browser per UTC day.
    """

    @staticmethod
    def _validate_day(value: object) -> str:
        day = str(value).strip()
        if len(day) != 10 or day[4:5] != "-" or day[7:8] != "-":
            raise ValueError("day must be an ISO calendar date")
        return day

    @staticmethod
    def _validate_hash(value: object) -> str:
        visitor_hash = str(value).strip().lower()
        if len(visitor_hash) != 64 or any(char not in "0123456789abcdef" for char in visitor_hash):
            raise ValueError("visitor_hash must be a SHA-256 hex digest")
        return visitor_hash

    @_repository_operation
    def record_unique_view_and_prune(
        self,
        day: str,
        visitor_hash: str,
        prune_before: str,
        *,
        recorded_at: float | None = None,
    ) -> bool:
        """Record a new visitor/day and prune old hashes in one transaction.

        Note: every call runs a full-table ``DELETE ... WHERE day < ?`` prune
        over the visitors table. For large visitor tables, prefer scheduling
        a low-frequency maintenance task (``prune_visitors_before``) instead
        of relying on this method to clean up on every visit.
        """
        normalized_day = self._validate_day(day)
        normalized_hash = self._validate_hash(visitor_hash)
        cutoff = self._validate_day(prune_before)
        timestamp = time.time() if recorded_at is None else float(recorded_at)
        with _transaction(self._conn, "shop_storefront_view"):
            inserted = self._conn.execute(
                "INSERT OR IGNORE INTO shop_storefront_view_visitors "
                "(day, visitor_hash, created_at) VALUES (?, ?, ?)",
                (normalized_day, normalized_hash, timestamp),
            )
            recorded = inserted.rowcount == 1
            if recorded:
                self._conn.execute(
                    "INSERT INTO shop_storefront_view_days (day, view_count, updated_at) "
                    "VALUES (?, 1, ?) "
                    "ON CONFLICT(day) DO UPDATE SET "
                    "view_count=view_count + 1, updated_at=excluded.updated_at",
                    (normalized_day, timestamp),
                )
            self._conn.execute(
                "DELETE FROM shop_storefront_view_visitors WHERE day < ?", (cutoff,)
            )
            return recorded

    @_repository_operation
    def record_unique_view(
        self,
        day: str,
        visitor_hash: str,
        *,
        recorded_at: float | None = None,
    ) -> bool:
        """Record one visit for a visitor/day and return whether it was new."""
        normalized_day = self._validate_day(day)
        normalized_hash = self._validate_hash(visitor_hash)
        timestamp = time.time() if recorded_at is None else float(recorded_at)
        with _transaction(self._conn, "shop_storefront_view"):
            inserted = self._conn.execute(
                "INSERT OR IGNORE INTO shop_storefront_view_visitors "
                "(day, visitor_hash, created_at) VALUES (?, ?, ?)",
                (normalized_day, normalized_hash, timestamp),
            )
            if inserted.rowcount != 1:
                return False
            self._conn.execute(
                "INSERT INTO shop_storefront_view_days (day, view_count, updated_at) "
                "VALUES (?, 1, ?) "
                "ON CONFLICT(day) DO UPDATE SET "
                "view_count=view_count + 1, updated_at=excluded.updated_at",
                (normalized_day, timestamp),
            )
            return True

    @_repository_operation
    def prune_visitors_before(self, day: str) -> int:
        """Remove expired deduplication hashes while retaining aggregate counts."""
        cutoff = self._validate_day(day)
        with _transaction(self._conn, "shop_storefront_view_prune"):
            cursor = self._conn.execute(
                "DELETE FROM shop_storefront_view_visitors WHERE day < ?", (cutoff,)
            )
            return max(0, int(cursor.rowcount))

    @_repository_operation
    @locked_read
    def total_views(self) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(view_count), 0) FROM shop_storefront_view_days"
        ).fetchone()
        return max(0, int(row[0] if row else 0))

    @_repository_operation
    @locked_read
    def daily_views(self, day: str) -> int:
        normalized_day = self._validate_day(day)
        row = self._conn.execute(
            "SELECT view_count FROM shop_storefront_view_days WHERE day=?", (normalized_day,)
        ).fetchone()
        return max(0, int(row[0] if row else 0))
