"""Tag store — per-library tags via SQLite (file_tags table in per-library DB).

Tags are stored using canonical names resolved by TagLibrary.
Tags are shared across the library - same DB as file_meta.

TagLibrary (core/tag_library.py) is a process-global canonical-definition
table shared by every library by design: canonicalization is a global
contract, while the file_tags rows themselves live in each library's own
DB.  add_tag and get_files_by_tag both resolve through the shared library,
so aliases behave identically in every library.

This store delegates to TagRepository for all SQL operations.
"""
import warnings
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable, TypeVar
from pathlib import Path
from sqlite3 import Connection

from AssetsManager.core.database import DatabaseManager
from AssetsManager.core.tag_library import get_library


_T = TypeVar("_T")

# The repository factory is installed by the application composition root
# (library_service) and by the test session (tests/conftest.py).  Core must
# not import repositories, so SQL wiring crosses the layer boundary through
# this explicit seam instead of a static import.
_RepositoryFactory = Callable[..., Any]
_default_repository_factory: _RepositoryFactory | None = None


def install_repository_factory(factory: _RepositoryFactory) -> None:
    """Install the application-layer TagRepository factory.

    ``factory(conn, *, library_root, session)`` must return an object with
    the TagRepository surface used by :class:`TagStore`.
    """
    global _default_repository_factory
    _default_repository_factory = factory


def _build_repository(
    library_root: str,
    db_conn: Connection,
    session: Any | None,
) -> Any:
    factory = _default_repository_factory
    if factory is None:
        raise RuntimeError(
            "TagStore repository factory is not installed; import "
            "AssetsManager.application.library_service (production) or let "
            "tests/conftest.py register one before constructing TagStore"
        )
    return factory(db_conn, library_root=library_root, session=session)


def _tag_store_operation(method: Callable[..., _T]) -> Callable[..., _T]:
    """Hold a real session operation lease across one public store call."""
    @wraps(method)
    def wrapped(self: Any, *args: Any, **kwargs: Any) -> _T:
        with self._operation_scope():
            self._ensure_live()
            return method(self, *args, **kwargs)

    return wrapped


class TagStore:
    _RESOLVE_CACHE_MAX = 10000

    def __init__(
        self,
        library_root: str,
        db_conn: Connection | None = None,
        *,
        session=None,
        repository: Any | None = None,
    ):
        self._root = str(Path(library_root).resolve())
        self._liveness = None
        self._session = None
        if session is not None and db_conn is None:
            self._db = session.connection_for(self._root)
        elif db_conn is None:
            raise TypeError(f"{type(self).__name__} requires db_conn or a LibrarySession")
        else:
            # Legacy constructor: preserve compatibility with caller-owned raw connections.
            self._db = DatabaseManager.validate_connection_owner(
                self._root, db_conn, allow_unmanaged=True
            )
        self._repo = (
            repository
            if repository is not None
            else _build_repository(self._root, self._db, session)
        )
        self._resolve_cache: dict[str, str] = {}
        from threading import Lock
        self._resolve_cache_lock = Lock()
        if session is not None:
            self._bind_session(session)

    def _bind_liveness(self, liveness) -> None:
        self._liveness = liveness

    def _bind_session(self, session) -> None:
        if self._session is not None and self._session is not session:
            raise RuntimeError("TagStore is already bound to another LibrarySession")
        session_connection = session.connection_for(self._root)
        if session_connection is not self._db:
            raise ValueError("TagStore connection does not belong to the LibrarySession")
        self._repo._bind_session(session, library_root=self._root)
        self._session = session
        session_liveness = getattr(getattr(session, "context", None), "_liveness", None)
        if session_liveness is not None:
            self._liveness = session_liveness

    @contextmanager
    def _operation_scope(self):
        if self._session is None:
            yield
            return
        with self._session.operation():
            yield

    def _ensure_live(self) -> None:
        if self._liveness is not None:
            self._liveness.ensure_live()

    def _resolve(self, filepath: str) -> str:
        """Cached Path.resolve() to avoid repeated filesystem I/O."""
        with self._resolve_cache_lock:
            cached = self._resolve_cache.get(filepath)
            if cached is not None:
                return cached
            if len(self._resolve_cache) >= self._RESOLVE_CACHE_MAX:
                self._resolve_cache.clear()
            resolved = str(Path(filepath).resolve())
            self._resolve_cache[filepath] = resolved
            return resolved

    @_tag_store_operation
    def get_tags(self, filepath: str) -> list[str]:
        key = self._resolve(filepath)
        return self._repo.get_tags(key)

    @_tag_store_operation
    def get_tags_for_files(self, filepaths: list[str]) -> dict[str, list[str]]:
        """Return tags keyed by resolved file path for many files at once."""
        keys = [self._resolve(p) for p in filepaths]
        return self._repo.get_tags_for_files(keys)

    @_tag_store_operation
    def add_tag(self, filepath: str, tag: str):
        # TagLibrary is a process-global canonical-definition table shared
        # across libraries by design (only the file_tags rows are per
        # library).  get_files_by_tag canonicalizes the same way, keeping
        # writes and reads symmetric.
        tag = get_library().canonical(tag)
        if not tag:
            return
        key = self._resolve(filepath)
        existing = self.get_tags(filepath)
        if tag.lower() in {t.lower() for t in existing}:
            return
        self._repo.add_tag(key, tag)

    @_tag_store_operation
    def remove_tag(self, filepath: str, tag: str):
        key = self._resolve(filepath)
        existing = self.get_tags(filepath)
        match = next((t for t in existing if t.lower() == tag.lower()), None)
        if match:
            self._repo.remove_tag(key, match)

    @_tag_store_operation
    def get_files_by_tag(self, tag: str) -> set[str]:
        """Return all files tagged with the given tag.

        The tag is canonicalized exactly like :meth:`add_tag` — the
        file_tags table stores canonical names, so alias queries resolve to
        the stored canonical form (unknown tags pass through unchanged).
        """
        canonical = get_library().canonical(tag)
        if not canonical:
            return set()
        return set(self._repo.get_files_by_tag(canonical))

    @_tag_store_operation
    def get_all_tags(self) -> list[str]:
        return self._repo.get_all_tags()

    @_tag_store_operation
    def get_all_tagged_files(self) -> set[str]:
        return {file_path for file_path, _tag in self._repo.list_file_tags()}

    @_tag_store_operation
    def remove_file(self, filepath: str):
        key = self._resolve(filepath)
        self._repo.remove_file(key)

    def clear_cache(self) -> None:
        """Drop the resolve cache. Called on session close."""
        with self._resolve_cache_lock:
            self._resolve_cache.clear()

    @_tag_store_operation
    def save(self):
        """Persist pending changes. No-op for SQLite (auto-commit per operation)."""
        return None


def get_store(library_root: str, db_conn: Connection | None = None) -> TagStore:
    """Deprecated compatibility constructor without global store retention."""
    warnings.warn("get_store() is deprecated, use TagService instead", DeprecationWarning, stacklevel=2)
    return TagStore(str(Path(library_root).resolve()), db_conn=db_conn)
