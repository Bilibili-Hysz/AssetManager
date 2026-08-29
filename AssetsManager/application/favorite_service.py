"""Principal-scoped favorites application service."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from AssetsManager.application.context import ConnectionProvider, LibrarySession, session_operation
from AssetsManager.core.database import DatabaseManager
from AssetsManager.core.path_resolver import root_identity
from AssetsManager.domain.asset import assert_under_root
from AssetsManager.domain.errors import MissingPathError, PathEscapeError, ValidationError
from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.events import FavoritesChanged
from AssetsManager.repositories.favorite_repository import FavoriteRepository

# Per-owner favorites cap, raised from 500: a library with tens of thousands of
# images hit the old ceiling within a week of starring work.  There is still no
# pagination (a future concern), so adds beyond the cap are rejected — but the
# ValidationError surfaces as a LAN 400 JSON and a WebUI toast, never a silent
# drop.
MAX_FAVORITES_PER_OWNER = 10_000
MAX_OWNER_KEY_LENGTH = 256


class FavoriteService:
    """Persist and validate favorites for one principal and library."""

    def __init__(
        self,
        connection_provider: ConnectionProvider | None = None,
        session: LibrarySession | None = None,
    ) -> None:
        self._session = session
        self._root_identity = None
        if isinstance(session, LibrarySession):
            expected_provider = session.connection_for
            provider = connection_provider or expected_provider
            provider_self = getattr(provider, "__self__", None)
            provider_func = getattr(provider, "__func__", None)
            expected_func = getattr(expected_provider, "__func__", None)
            if not (
                provider == expected_provider
                or (provider_self is session and provider_func is expected_func)
            ):
                raise ValueError(
                    "FavoriteService connection provider does not belong to "
                    "the LibrarySession"
                )
            self._connection_provider = expected_provider
            self._root_identity = session.context.root_identity
        else:
            self._connection_provider = connection_provider

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
        if isinstance(self._session, LibrarySession):
            requested = root_identity(root, strict=False)
            captured = self._root_identity
            if captured is None or requested.map_key != captured.map_key:
                raise ValueError(
                    "FavoriteService library_root does not match the bound LibrarySession"
                )
            expected = self._session.connection_for(captured)
            if db_conn is not None and db_conn is not expected:
                raise ValueError(
                    "FavoriteService connection does not belong to the bound LibrarySession"
                )
            return expected
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
        # Any directory or regular file inside the library qualifies; the old
        # image-extension whitelist starved every other category (video, PSD,
        # archives, ...).  Path safety stays with _target()/assert_under_root,
        # and the callers reject the library root itself; what is left to
        # exclude here is the obviously broken (missing/broken symlinks and
        # other non-directory, non-regular entries report neither kind).
        return target.is_dir() or target.is_file()

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
            raise ValidationError(
                "path", "favorite target must be a directory or a regular file"
            )
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
