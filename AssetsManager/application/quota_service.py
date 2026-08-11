"""Commerce quota application service."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from AssetsManager.application.context import ConnectionProvider, LibrarySession, session_operation
from AssetsManager.core.database import DatabaseManager
from AssetsManager.domain.errors import OperationNotPermitted, ValidationError
from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.events import QuotaChanged


class QuotaService:
    """Read and atomically consume named commerce quotas."""

    def __init__(self, connection_provider: ConnectionProvider | None = None,
                 session: LibrarySession | None = None, *, repository: Any | None = None) -> None:
        self._connection_provider = connection_provider
        self._session = session
        self._repository = repository

    def _repo(self, library_root: str | Path, db_conn: sqlite3.Connection | None) -> Any:
        if self._repository is not None:
            return self._repository
        root = Path(library_root).resolve()
        if db_conn is None:
            if self._connection_provider is None:
                raise RuntimeError("QuotaService requires a repository, db_conn, or ConnectionProvider")
            db_conn = self._connection_provider(root)
        conn = DatabaseManager.validate_connection_owner(root, db_conn, allow_unmanaged=True)
        from AssetsManager.repositories.quota_repository import QuotaRepository
        return QuotaRepository(conn)

    @session_operation
    def get_quota(self, library_root: str | Path, *, db_conn: sqlite3.Connection | None = None) -> dict[str, Any]:
        repo = self._repo(library_root, db_conn)
        getter = getattr(repo, "get_quota", None) or getattr(repo, "get_usage")
        value = dict(getter() or {})
        # Expose the stable optional-quota contract used by the WebUI while
        # retaining the repository's delivery-token aggregate fields.
        limit = int(value.get("download_limit", 0))
        used = int(value.get("downloads_used", 0))
        value.update({
            "enabled": bool(value.get("delivery_tokens", 0)),
            "period": "daily",
            "limit": limit,
            "used": used,
            "remaining": max(0, limit - used),
            "reset_at": None,
            "min_interval_seconds": 0,
        })
        return value

    @session_operation
    def consume(self, library_root: str | Path, name: str, amount: int = 1, *,
                db_conn: sqlite3.Connection | None = None) -> dict[str, Any]:
        key = str(name).strip()
        if not key:
            raise ValidationError("quota", "name is required")
        try:
            units = int(amount)
        except (TypeError, ValueError) as exc:
            raise ValidationError("amount", "must be an integer") from exc
        if units <= 0:
            raise ValidationError("amount", "must be positive")
        repo = self._repo(library_root, db_conn)
        result = repo.consume(key, units)
        if result is None or result is False:
            raise OperationNotPermitted(f"Quota exceeded: {key}")
        if self._session is not None:
            get_event_bus().publish(QuotaChanged(
                library_root=self._session.root_str,
                session_token=self._session.event_token,
                name=key,
            ))
        return dict(result) if not isinstance(result, bool) else {"name": key, "consumed": units}
