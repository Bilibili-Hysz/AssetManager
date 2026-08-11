"""Principal-scoped favorites application service."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from AssetsManager.application.context import ConnectionProvider, LibrarySession, session_operation
from AssetsManager.core.database import DatabaseManager
from AssetsManager.domain.asset import IMAGE_EXTS, assert_under_root
from AssetsManager.domain.errors import MissingPathError, PathEscapeError, ValidationError
from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.events import FavoritesChanged
from AssetsManager.repositories.favorite_repository import FavoriteRepository

MAX_FAVORITES_PER_OWNER = 500
MAX_OWNER_KEY_LENGTH = 256


class FavoriteService:
    """Persist and validate favorites for one principal and library."""

    def __init__(
        self,
        connection_provider: ConnectionProvider | None = None,
        session: LibrarySession | None = None,
    ) -> None:
        self._connection_provider = connection_provider
        self._session = session

    @staticmethod
    def normalize_owner_key(owner_key: str) -> str:
        if not isinstance(owner_key, str):
            raise ValidationError("owner_key", "must be a string")
        clean = owner_key.strip()
        if not clean:
            raise ValidationError("owner_key", "must not be empty")
        if len(clean) > MAX_OWNER_KEY_LENGTH:
            raise ValidationError(
                "owner_key", f"must be at most {MAX_OWNER_KEY_LENGTH} characters"
            )
        return clean

    def _connection(
        self,
        library_root: str | Path,
        db_conn: sqlite3.Connection | None,
    ) -> sqlite3.Connection:
        root = Path(library_root).resolve()
        if db_conn is not None:
            return DatabaseManager.validate_connection_owner(
                root, db_conn, allow_unmanaged=True
            )
        if self._connection_provider is None:
            raise RuntimeError(
                "FavoriteService requires an explicit db_conn or ConnectionProvider."
            )
        return DatabaseManager.validate_connection_owner(
            root, self._connection_provider(root), allow_unmanaged=True
        )

    @staticmethod
    def _target(library_root: str | Path, path: str | Path) -> tuple[Path, Path]:
        root = Path(library_root).resolve()
        raw = Path(path)
        target = assert_under_root(raw if raw.is_absolute() else root / raw, root)
        return root, target

    @staticmethod
    def _relative(root: Path, target: Path) -> str:
        relative = target.relative_to(root)
        return "" if relative == Path(".") else relative.as_posix()

    @staticmethod
    def _is_supported_target(target: Path) -> bool:
        return target.is_dir() or (
            target.is_file() and target.suffix.lower() in IMAGE_EXTS
        )

    def _publish(self, owner_key: str, paths: tuple[str, ...]) -> None:
        if self._session is None:
            return
        get_event_bus().publish(FavoritesChanged(
            library_root=self._session.root_str,
            session_token=self._session.event_token,
            owner_key=owner_key,
            paths=paths,
        ))

    @session_operation
    def list_paths(
        self,
        library_root: str | Path,
        owner_key: str,
        *,
        db_conn: sqlite3.Connection | None = None,
    ) -> list[str]:
        root = Path(library_root).resolve()
        owner = self.normalize_owner_key(owner_key)
        repo = FavoriteRepository(self._connection(root, db_conn))
        result: list[str] = []
        for stored_path in repo.list_paths(owner, limit=MAX_FAVORITES_PER_OWNER):
            try:
                target = assert_under_root(Path(stored_path), root)
            except (OSError, PathEscapeError, ValueError):
                continue
            if target == root or not target.exists() or not self._is_supported_target(target):
                continue
            relative = self._relative(root, target)
            if relative and relative not in result:
                result.append(relative)
        return result

    @session_operation
    def add(
        self,
        library_root: str | Path,
        owner_key: str,
        path: str | Path,
        *,
        db_conn: sqlite3.Connection | None = None,
    ) -> tuple[str, bool]:
        owner = self.normalize_owner_key(owner_key)
        root, target = self._target(library_root, path)
        if target == root:
            raise ValidationError("path", "library root cannot be favorited")
        if not target.exists():
            raise MissingPathError(str(path))
        if not self._is_supported_target(target):
            raise ValidationError("path", "favorite target must be a directory or image")
        repo = FavoriteRepository(self._connection(root, db_conn))
        try:
            changed = repo.add(
                owner, str(target), max_items=MAX_FAVORITES_PER_OWNER
            )
        except OverflowError as exc:
            raise ValidationError(
                "path", f"at most {MAX_FAVORITES_PER_OWNER} favorites are allowed"
            ) from exc
        relative = self._relative(root, target)
        if changed:
            self._publish(owner, (str(target),))
        return relative, changed

    @session_operation
    def remove(
        self,
        library_root: str | Path,
        owner_key: str,
        path: str | Path,
        *,
        db_conn: sqlite3.Connection | None = None,
    ) -> tuple[str, bool]:
        owner = self.normalize_owner_key(owner_key)
        root, target = self._target(library_root, path)
        if target == root:
            raise ValidationError("path", "library root cannot be favorited")
        repo = FavoriteRepository(self._connection(root, db_conn))
        changed = repo.remove(owner, str(target))
        relative = self._relative(root, target)
        if changed:
            self._publish(owner, (str(target),))
        return relative, changed


__all__ = [
    "FavoriteService",
    "MAX_FAVORITES_PER_OWNER",
]
