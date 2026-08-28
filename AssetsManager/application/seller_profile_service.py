"""Application service for the per-library seller profile."""
from __future__ import annotations

import re
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from AssetsManager.application.context import ConnectionProvider, LibrarySession, session_operation
from AssetsManager.core.database import DatabaseManager
from AssetsManager.domain.errors import ValidationError
from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.events import SellerProfileChanged

MAX_STORE_NAME_LENGTH = 200
MAX_CONTACT_EMAIL_LENGTH = 254
MAX_DESCRIPTION_LENGTH = 10_000
_PROFILE_FIELDS = frozenset({
    "store_name",
    "contact_email",
    "description",
    "accept_orders",
})
_EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+", re.ASCII)


class SellerProfileService:
    """Validate and persist seller-facing store settings."""

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
        if self._connection_provider is not None:
            connection = self._connection_provider(root)
        elif self._session is not None:
            connection = self._session.connection_for(root)
        else:
            raise RuntimeError(
                "SellerProfileService requires a repository, db_conn, or ConnectionProvider"
            )
        return DatabaseManager.validate_connection_owner(
            root, connection, allow_unmanaged=True
        )

    def _repo(self, root: Path, db_conn: sqlite3.Connection | None) -> Any:
        if self._repository is not None:
            return self._repository
        from AssetsManager.repositories.seller_profile_repository import SellerProfileRepository

        return SellerProfileRepository(self._connection(root, db_conn))

    @staticmethod
    def _root(library_root: str | Path) -> Path:
        return Path(library_root).resolve()

    @staticmethod
    def _text(value: Any, field: str, maximum: int) -> str:
        if not isinstance(value, str):
            raise ValidationError(field, "must be a string")
        value = value.strip()
        if len(value) > maximum:
            raise ValidationError(field, f"must be at most {maximum} characters")
        return value

    @classmethod
    def _fields(cls, payload: Mapping[str, Any]) -> dict[str, Any]:
        unknown = set(payload) - _PROFILE_FIELDS
        if unknown:
            names = ", ".join(sorted(str(name) for name in unknown))
            raise ValidationError("profile", f"unknown field(s): {names}")

        fields: dict[str, Any] = {}
        if "store_name" in payload:
            fields["store_name"] = cls._text(
                payload["store_name"], "store_name", MAX_STORE_NAME_LENGTH
            )
        if "contact_email" in payload:
            email = cls._text(
                payload["contact_email"], "contact_email", MAX_CONTACT_EMAIL_LENGTH
            )
            if email and _EMAIL_PATTERN.fullmatch(email) is None:
                raise ValidationError("contact_email", "must be a valid email address")
            fields["contact_email"] = email
        if "description" in payload:
            fields["description"] = cls._text(
                payload["description"], "description", MAX_DESCRIPTION_LENGTH
            )
        if "accept_orders" in payload:
            value = payload["accept_orders"]
            if not isinstance(value, bool):
                raise ValidationError("accept_orders", "must be a boolean")
            fields["accept_orders"] = value
        return fields

    @session_operation
    def get_profile(
        self, library_root: str | Path, db_conn: sqlite3.Connection | None = None
    ) -> dict[str, Any]:
        root = self._root(library_root)
        return dict(self._repo(root, db_conn).get_profile())

    @session_operation
    def update_profile(
        self,
        library_root: str | Path,
        payload: Mapping[str, Any],
        db_conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise ValidationError("body", "must be an object")
        fields = self._fields(payload)
        root = self._root(library_root)
        profile = dict(self._repo(root, db_conn).update_profile(fields))
        if self._session is not None:
            get_event_bus().publish(SellerProfileChanged(
                library_root=self._session.root_str,
                session_token=self._session.event_token,
            ))
        return profile


__all__ = [
    "MAX_CONTACT_EMAIL_LENGTH",
    "MAX_DESCRIPTION_LENGTH",
    "MAX_STORE_NAME_LENGTH",
    "SellerProfileService",
]
