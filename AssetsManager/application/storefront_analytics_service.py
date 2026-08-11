"""Privacy-preserving aggregate storefront analytics."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
from pathlib import Path
import sqlite3
from typing import Any

from AssetsManager.application.context import ConnectionProvider, LibrarySession, session_operation
from AssetsManager.core.database import DatabaseManager
from AssetsManager.domain.errors import ValidationError

_VISITOR_RETENTION_DAYS = 2  # Keep the current and immediately previous UTC day.
_MIN_VISITOR_TOKEN_LENGTH = 24
_MAX_VISITOR_TOKEN_LENGTH = 256


class StorefrontAnalyticsService:
    """Record deduplicated storefront views and expose seller-safe totals."""

    def __init__(
        self,
        connection_provider: ConnectionProvider | None = None,
        session: LibrarySession | None = None,
        *,
        repository: Any | None = None,
    ) -> None:
        self._connection_provider = connection_provider
        self._session = session
        self._repository = repository

    @staticmethod
    def _root(library_root: str | Path) -> Path:
        return Path(library_root).resolve()

    def _connection(self, root: Path, db_conn: sqlite3.Connection | None) -> sqlite3.Connection:
        if db_conn is not None:
            return DatabaseManager.validate_connection_owner(root, db_conn, allow_unmanaged=True)
        if self._connection_provider is None:
            raise RuntimeError("StorefrontAnalyticsService requires a repository, db_conn, or ConnectionProvider")
        return DatabaseManager.validate_connection_owner(
            root, self._connection_provider(root), allow_unmanaged=True
        )

    def _repo(self, root: Path, db_conn: sqlite3.Connection | None) -> Any:
        if self._repository is not None:
            return self._repository
        from AssetsManager.repositories.storefront_analytics_repository import StorefrontAnalyticsRepository

        return StorefrontAnalyticsRepository(self._connection(root, db_conn))

    @staticmethod
    def _visitor_hash(token: object) -> str:
        if not isinstance(token, str):
            raise ValidationError("visitor", "must be a browser-issued token")
        value = token.strip()
        if not (_MIN_VISITOR_TOKEN_LENGTH <= len(value) <= _MAX_VISITOR_TOKEN_LENGTH):
            raise ValidationError("visitor", "is invalid")
        if not value.isascii():
            raise ValidationError("visitor", "is invalid")
        return hashlib.sha256(value.encode("ascii")).hexdigest()

    @staticmethod
    def _day(timestamp: float) -> str:
        return datetime.fromtimestamp(timestamp, UTC).date().isoformat()

    @session_operation
    def record_storefront_view(
        self,
        library_root: str | Path,
        visitor_token: str,
        *,
        now: float | None = None,
        db_conn: sqlite3.Connection | None = None,
    ) -> bool:
        timestamp = datetime.now(UTC).timestamp() if now is None else float(now)
        root = self._root(library_root)
        repo = self._repo(root, db_conn)
        day = self._day(timestamp)
        # Keep the current and previous UTC day.  The exclusive delete cutoff
        # is therefore yesterday: an older day is deleted, while yesterday is
        # still available for deduplication.
        cutoff = (
            datetime.fromtimestamp(timestamp, UTC).date()
            - timedelta(days=_VISITOR_RETENTION_DAYS - 1)
        ).isoformat()
        return bool(
            repo.record_unique_view_and_prune(
                day,
                self._visitor_hash(visitor_token),
                cutoff,
                recorded_at=timestamp,
            )
        )

    @session_operation
    def stats(
        self,
        library_root: str | Path,
        *,
        db_conn: sqlite3.Connection | None = None,
    ) -> dict[str, int]:
        root = self._root(library_root)
        return {"store_views": self._repo(root, db_conn).total_views()}