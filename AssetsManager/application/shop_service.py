"""Commerce catalog application service.

The service owns validation and path normalization. Persistence is delegated to
``ShopRepository`` supplied by the commerce repository work line.
"""
from __future__ import annotations

import sqlite3
import re
import unicodedata
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from AssetsManager.application.context import ConnectionProvider, LibrarySession, session_operation
from AssetsManager.core.database import DatabaseManager
from AssetsManager.domain.asset import assert_under_root
from AssetsManager.domain.errors import (
    DuplicateError,
    MissingPathError,
    NotFoundError,
    ValidationError,
)
from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.events import FileSystemChanged, ShopItemChanged
from AssetsManager.application.shop_authorization import (
    UnauthorizedShopPathError,
    ensure_authorized_shop_path,
    get_shop_authorized_roots,
    is_authorized_shop_path,
    normalize_relative_shop_path,
)

MAX_TITLE_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 10_000
MAX_CATALOG_QUERY_LENGTH = 200
# 100 亿元 (CNY 10 billion). Keeps stored values far below SQLite's 64-bit
# INTEGER ceiling so oversized prices can never wrap or corrupt the column.
MAX_PRICE_CENTS = 10**12
SUPPORTED_CURRENCIES = frozenset({"CNY", "USD"})
SHOP_STATUSES = frozenset({"active", "draft", "archived"})
GALLERY_MAX = 20
GALLERY_EXTS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".avif"})


def _record(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return dict(value)
    keys = getattr(value, "keys", None)
    if callable(keys):
        key_values = keys()
        if isinstance(key_values, Iterable):
            return {str(key): value[key] for key in key_values}
    data = getattr(value, "__dict__", None)
    return dict(data) if isinstance(data, dict) else None


def normalize_catalog_query(value: str | None) -> str | None:
    """Normalize the public catalog search query without changing legacy APIs.

    Empty and whitespace-only values mean "no search". Internal whitespace is
    preserved because the repository performs a literal substring match.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError("q", "must be a string")
    if len(value) > MAX_CATALOG_QUERY_LENGTH:
        raise ValidationError(
            "q", f"must be at most {MAX_CATALOG_QUERY_LENGTH} characters"
        )
    if any(unicodedata.category(char) == "Cc" for char in value):
        raise ValidationError("q", "must not contain control characters")
    normalized = value.strip()
    return normalized or None


class ShopService:
    """Manage library-backed products without exposing absolute paths."""

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

    def _connection(self, root: Path, db_conn: sqlite3.Connection | None) -> sqlite3.Connection:
        if db_conn is not None:
            return DatabaseManager.validate_connection_owner(root, db_conn, allow_unmanaged=True)
        if self._connection_provider is None:
            raise RuntimeError("ShopService requires a repository, db_conn, or ConnectionProvider")
        return DatabaseManager.validate_connection_owner(
            root, self._connection_provider(root), allow_unmanaged=True
        )

    def _repo(self, root: Path, db_conn: sqlite3.Connection | None) -> Any:
        if self._repository is not None:
            return self._repository
        from AssetsManager.repositories.shop_repository import ShopRepository

        return ShopRepository(self._connection(root, db_conn))

    @staticmethod
    def _root(library_root: str | Path) -> Path:
        return Path(library_root).resolve()

    @staticmethod
    def _path(
        root: Path,
        raw_path: str | Path,
        *,
        must_exist: bool = True,
        authorized: bool = True,
    ) -> tuple[Path, str]:
        relative_input = (
            ensure_authorized_shop_path(raw_path)
            if authorized
            else normalize_relative_shop_path(raw_path)
        )
        target = assert_under_root(root / relative_input, root)
        if target == root:
            raise ValidationError("path", "library root cannot be sold")
        if must_exist and not target.exists():
            raise MissingPathError(relative_input)
        relative = target.relative_to(root).as_posix()
        return target, relative

    @staticmethod
    def _gallery(root: Path, raw: Any) -> list[str]:
        if raw is None:
            return []
        if not isinstance(raw, (list, tuple)):
            raise ValidationError("gallery_paths", "must be an array")
        result: list[str] = []
        for value in raw:
            target, relative = ShopService._path(root, str(value))
            if not target.is_file():
                raise ValidationError("gallery_paths", "each path must be a file")
            if target.suffix.lower() not in GALLERY_EXTS:
                raise ValidationError("gallery_paths", "unsupported image extension")
            if len(relative) > 500:
                raise ValidationError("gallery_paths", "path is too long")
            if relative not in result:
                result.append(relative)
        if len(result) > GALLERY_MAX:
            raise ValidationError("gallery_paths", "at most 20 images")
        return result

    @staticmethod
    def _fields(payload: Mapping[str, Any], *, partial: bool) -> dict[str, Any]:
        fields: dict[str, Any] = {}
        if not partial or "title" in payload:
            title = str(payload.get("title", "")).strip()
            if not title or len(title) > MAX_TITLE_LENGTH:
                raise ValidationError("title", f"must be 1-{MAX_TITLE_LENGTH} characters")
            fields["title"] = title
        if not partial or "description" in payload:
            description = str(payload.get("description", "")).strip()
            if len(description) > MAX_DESCRIPTION_LENGTH:
                raise ValidationError("description", f"must be at most {MAX_DESCRIPTION_LENGTH} characters")
            fields["description"] = description
        if not partial or "price_cents" in payload:
            try:
                price_cents = int(payload.get("price_cents", 0))
            except (TypeError, ValueError) as exc:
                raise ValidationError("price_cents", "must be an integer") from exc
            if price_cents < 0:
                raise ValidationError("price_cents", "must not be negative")
            if price_cents > MAX_PRICE_CENTS:
                raise ValidationError(
                    "price_cents", f"must be at most {MAX_PRICE_CENTS}"
                )
            fields["price_cents"] = price_cents
        if not partial or "currency" in payload:
            currency = str(payload.get("currency", "CNY")).strip().upper()
            if currency not in SUPPORTED_CURRENCIES:
                raise ValidationError("currency", "must be CNY or USD")
            fields["currency"] = currency
        if not partial or "enabled" in payload or "status" in payload:
            status = payload.get("status")
            if status is not None:
                status = str(status).strip().lower()
                if status not in {"active", "archived", "draft"}:
                    raise ValidationError("status", "must be active, archived, or draft")
                fields["enabled"] = status == "active"
            else:
                fields["enabled"] = bool(payload.get("enabled", True))
        if not partial or "metadata" in payload or "status" in payload:
            raw_metadata = payload.get("metadata", {})
            metadata = dict(raw_metadata) if isinstance(raw_metadata, Mapping) else {}
            if "status" in payload and payload.get("status") is not None:
                metadata["status"] = str(payload["status"]).strip().lower()
            fields["metadata"] = metadata
        return fields

    @staticmethod
    def _public_item(item: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(item)
        for key in ("path", "cover_path"):
            value = result.get(key)
            if value is not None:
                result[key] = str(value).replace("\\", "/")
        metadata = dict(result.get("metadata") or {}) if isinstance(result.get("metadata"), Mapping) else {}
        gallery = metadata.pop("image_paths", [])
        result["metadata"] = metadata
        result["gallery_paths"] = [str(x).replace("\\", "/") for x in gallery] if isinstance(gallery, list) else []
        # The database stores enabled as 0/1; the public API exposes the
        # boolean the frontend ShopItem type declares. Missing defaults to
        # True, matching the historical status derivation below.
        result["enabled"] = bool(result.get("enabled", True))
        stored_status = metadata.get("status")
        result["status"] = (stored_status if stored_status in {"active", "archived", "draft"}
                             else "active" if result["enabled"] else "archived")
        return result

    def _publish(self, *paths: str) -> None:
        if self._session is None:
            return
        normalized = tuple(path for path in paths if path)
        bus = get_event_bus()
        # Keep the legacy file projection notification for existing consumers,
        # while exposing a dedicated Commerce projection domain to the WebUI.
        bus.publish(FileSystemChanged(
            library_root=self._session.root_str,
            session_token=self._session.event_token,
            kind="shop",
            paths=normalized,
        ))
        bus.publish(ShopItemChanged(
            library_root=self._session.root_str,
            session_token=self._session.event_token,
            paths=normalized,
        ))

    @session_operation
    def list_items(
        self,
        library_root: str | Path,
        *,
        include_disabled: bool = False,
        status: str | None = None,
        db_conn: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        if status is not None:
            status = str(status).strip().lower()
            if status not in SHOP_STATUSES:
                raise ValidationError("status", "must be active, archived, or draft")
        root = self._root(library_root)
        repository = self._repo(root, db_conn)
        if status is None:
            # Keep compatibility with repository adapters implemented before
            # the optional status filter was added.
            rows = repository.list_items(include_disabled=include_disabled)
        else:
            rows = repository.list_items(
                include_disabled=include_disabled, status=status
            )
        return [
            self._public_item(row)
            for raw in rows
            if (row := _record(raw)) is not None
            and is_authorized_shop_path(row.get("path"))
        ]

    @session_operation
    def list_catalog(
        self,
        library_root: str | Path,
        *,
        q: str | None = None,
        page: int = 1,
        page_size: int = 24,
        sort: str = "newest",
        db_conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        """Return the public active catalog using an independent paging contract."""
        q = normalize_catalog_query(q)
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise ValidationError("page", "must be a positive integer")
        if isinstance(page_size, bool) or not isinstance(page_size, int):
            raise ValidationError("page_size", "must be an integer between 1 and 100")
        if not 1 <= page_size <= 100:
            raise ValidationError("page_size", "must be between 1 and 100")
        if str(sort).strip().lower() != "newest":
            raise ValidationError("sort", "must be newest")

        root = self._root(library_root)
        result = self._repo(root, db_conn).list_catalog(
            q=q,
            page=page,
            page_size=page_size,
            authorized_roots=get_shop_authorized_roots(),
        )
        raw_items = result.get("items", []) if isinstance(result, Mapping) else []
        items: list[dict[str, Any]] = []
        for raw in raw_items:
            item = _record(raw)
            if item is None or not is_authorized_shop_path(item.get("path")):
                continue
            public_item = self._public_item(item)
            if bool(item.get("enabled", False)) and public_item.get("status") == "active":
                items.append(public_item)
        return {
            "items": items,
            "page": int(result.get("page", page)),
            "page_size": int(result.get("page_size", page_size)),
            "total": int(result.get("total", len(items))),
        }

    @session_operation
    def get_item(
        self, library_root: str | Path, item_id: int, *, db_conn: sqlite3.Connection | None = None
    ) -> dict[str, Any]:
        root = self._root(library_root)
        item = _record(self._repo(root, db_conn).get_item(int(item_id)))
        if item is None:
            raise NotFoundError("shop item", str(item_id))
        if not is_authorized_shop_path(item.get("path")):
            raise UnauthorizedShopPathError()
        return self._public_item(item)

    @session_operation
    def get_public_item(
        self, library_root: str | Path, item_id: int, *, db_conn: sqlite3.Connection | None = None
    ) -> dict[str, Any]:
        """Return an active, authorized item for the public Commerce detail route.

        Public callers must not be able to distinguish draft/archived items or
        items outside the configured selling roots from an unknown item.
        """
        root = self._root(library_root)
        item = _record(self._repo(root, db_conn).get_item(int(item_id)))
        if item is None or not is_authorized_shop_path(item.get("path")):
            raise NotFoundError("shop item", str(item_id))
        public = self._public_item(item)
        if not bool(item.get("enabled", False)) or public.get("status") != "active":
            raise NotFoundError("shop item", str(item_id))
        return public

    @session_operation
    def get_public_item_by_path(
        self,
        library_root: str | Path,
        path: str,
        *,
        db_conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        """Return the public active item for a normalized relative path."""
        root = self._root(library_root)
        normalized = normalize_relative_shop_path(path)
        item = _record(self._repo(root, db_conn).get_by_path(normalized))
        if item is None or not is_authorized_shop_path(normalized):
            raise NotFoundError("shop item", normalized)
        public = self._public_item(item)
        if not bool(item.get("enabled", False)) or public.get("status") != "active":
            raise NotFoundError("shop item", normalized)
        return public

    @session_operation
    def get_public_item_media_path(
        self,
        library_root: str | Path,
        item_id: int,
        slot: str,
        *,
        db_conn: sqlite3.Connection | None = None,
    ) -> str:
        """Resolve one public Commerce media slot to a library-relative path.

        Slot names are deliberately an allow-list rather than a path-shaped
        input. The item is re-read through the same active/enabled/authorized
        gate as the public detail endpoint, and the selected media path is
        checked against the configured authorized roots as well.
        """
        root = self._root(library_root)
        try:
            public = self.get_public_item(root, int(item_id), db_conn=db_conn)
            normalized_slot = str(slot or "")
            if normalized_slot == "cover":
                selected = public.get("cover_path") or public.get("path")
            else:
                match = re.fullmatch(r"gallery-(\d+)", normalized_slot)
                if match is None:
                    raise ValueError("invalid media slot")
                index = int(match.group(1))
                gallery = public.get("gallery_paths")
                if not isinstance(gallery, list) or index >= len(gallery):
                    raise LookupError("media slot not found")
                selected = gallery[index]
            if not selected:
                raise LookupError("media slot not found")
            target, relative = self._path(root, str(selected), must_exist=True, authorized=True)
            if not target.is_file():
                raise LookupError("media target is not a file")
            return relative
        except Exception as exc:
            # Public media deliberately collapses malformed slots, missing
            # files, stale catalog rows, and authorization failures to 404.
            if isinstance(exc, NotFoundError):
                raise
            raise NotFoundError("shop media", f"{item_id}/{slot}") from exc

    @session_operation
    def create_item(
        self,
        library_root: str | Path,
        payload: Mapping[str, Any],
        *,
        db_conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        root = self._root(library_root)
        _, path = self._path(root, payload.get("path", ""))
        fields = self._fields(payload, partial=False)
        fields.setdefault("metadata", {})["image_paths"] = self._gallery(root, payload.get("gallery_paths", []))
        cover_path = payload.get("cover_path")
        if cover_path:
            _, fields["cover_path"] = self._path(root, str(cover_path))
        else:
            fields["cover_path"] = None
        try:
            created = self._repo(root, db_conn).create_item(path=path, **fields)
        except DuplicateError as exc:
            raise ValidationError(
                "path", "an item with this path already exists"
            ) from exc
        item = _record(created)
        if item is None:
            item_id = int(created)
            item = _record(self._repo(root, db_conn).get_item(item_id))
        if item is None:
            raise RuntimeError("ShopRepository.create_item did not return a record or id")
        self._publish(path)
        return self._public_item(item)

    @session_operation
    def update_item(
        self,
        library_root: str | Path,
        item_id: int,
        payload: Mapping[str, Any],
        *,
        db_conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        root = self._root(library_root)
        repo = self._repo(root, db_conn)
        current = _record(repo.get_item(int(item_id)))
        if current is None:
            raise NotFoundError("shop item", str(item_id))
        ensure_authorized_shop_path(current.get("path", ""))
        fields = self._fields(payload, partial=True)
        if "path" in payload:
            _, fields["path"] = self._path(root, payload["path"])
        if "cover_path" in payload:
            cover = payload.get("cover_path")
            fields["cover_path"] = self._path(root, cover)[1] if cover else None
        if "gallery_paths" in payload:
            metadata = dict(current.get("metadata") or {}) if isinstance(current.get("metadata"), Mapping) else {}
            metadata["image_paths"] = self._gallery(root, payload.get("gallery_paths"))
            fields["metadata"] = metadata
        if not fields:
            raise ValidationError("item", "no fields to update")
        try:
            updated = _record(repo.update_item(int(item_id), **fields))
        except DuplicateError as exc:
            raise ValidationError(
                "path", "an item with this path already exists"
            ) from exc
        if updated is None:
            updated = _record(repo.get_item(int(item_id)))
        if updated is None:
            raise NotFoundError("shop item", str(item_id))
        self._publish(str(current.get("path", "")), str(updated.get("path", "")))
        return self._public_item(updated)

    @session_operation
    def delete_item(
        self, library_root: str | Path, item_id: int, *, db_conn: sqlite3.Connection | None = None
    ) -> bool:
        root = self._root(library_root)
        repo = self._repo(root, db_conn)
        current = _record(repo.get_item(int(item_id)))
        if current is None:
            raise NotFoundError("shop item", str(item_id))
        deleted = bool(repo.delete_item(int(item_id)))
        if deleted:
            self._publish(str(current.get("path", "")))
        return deleted


