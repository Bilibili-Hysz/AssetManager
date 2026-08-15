"""Policy helpers for library paths that may be listed for sale."""
from __future__ import annotations

import os
import re
from collections.abc import Iterable
from typing import Any

from AssetsManager.application.app_settings_provider import get_app_settings
from AssetsManager.core.settings import AppSettings as AppSettings  # compat monkeypatch target
from AssetsManager.domain.errors import OperationNotPermitted, ValidationError

AUTHORIZED_ROOTS_SETTING = "lan_shop_authorized_roots"
AUTHORIZED_ROOTS_ENV = "SHOP_AUTHORIZED_ROOTS"
_MISSING = object()
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:($|/)")


class ShopAuthorizationConfigError(OperationNotPermitted):
    """The configured selling roots are invalid and cannot be safely applied."""

    def __init__(self) -> None:
        super().__init__("Shop authorization configuration is invalid")


class UnauthorizedShopPathError(OperationNotPermitted):
    """A relative library path is outside the configured selling roots."""

    def __init__(self) -> None:
        super().__init__("Path is not within an authorized selling root")


def normalize_relative_shop_path(value: Any, *, field: str = "path") -> str:
    """Normalize a user/library path without accepting absolute or parent paths."""
    if isinstance(value, bytes):
        raise ValidationError(field, "must be a relative path")
    if not isinstance(value, str):
        try:
            value = os.fspath(value)
        except TypeError as exc:
            raise ValidationError(field, "must be a relative path") from exc
        if isinstance(value, bytes):
            raise ValidationError(field, "must be a relative path")
    raw = value.strip().replace("\\", "/")
    if not raw or raw.startswith("/") or _WINDOWS_ABSOLUTE.match(raw):
        raise ValidationError(field, "must be a relative path")
    parts: list[str] = []
    for part in raw.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise ValidationError(field, "parent paths are not allowed")
        parts.append(part)
    if not parts:
        raise ValidationError(field, "must not be empty")
    return "/".join(parts)


def _raw_authorized_roots(settings: Any | None = None) -> Any:
    settings_obj: Any = get_app_settings() if settings is None else settings
    value = settings_obj.get(AUTHORIZED_ROOTS_SETTING, _MISSING)
    if value is _MISSING:
        return os.environ.get(AUTHORIZED_ROOTS_ENV, "")
    return value


def _iter_root_values(value: Any) -> Iterable[Any]:
    if isinstance(value, str):
        return value.split(";")
    if isinstance(value, (list, tuple, set, frozenset)):
        return value
    if value is None:
        return ()
    return (value,)


def get_shop_authorized_roots(settings: Any | None = None) -> tuple[str, ...]:
    """Return normalized roots, rejecting any non-empty invalid configuration."""
    roots: list[str] = []
    invalid = False
    for value in _iter_root_values(_raw_authorized_roots(settings)):
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        try:
            normalized = normalize_relative_shop_path(value, field=AUTHORIZED_ROOTS_SETTING)
        except ValidationError:
            invalid = True
            continue
        if normalized not in roots:
            roots.append(normalized)
    if invalid:
        raise ShopAuthorizationConfigError()
    return tuple(roots)


def is_authorized_shop_path(value: Any, settings: Any | None = None) -> bool:
    try:
        normalized = normalize_relative_shop_path(value)
    except ValidationError:
        return False
    roots = get_shop_authorized_roots(settings)
    if not roots:
        return True
    return any(normalized == root or normalized.startswith(root + "/") for root in roots)


def ensure_authorized_shop_path(value: Any, settings: Any | None = None) -> str:
    normalized = normalize_relative_shop_path(value)
    roots = get_shop_authorized_roots(settings)
    if roots and not any(normalized == root or normalized.startswith(root + "/") for root in roots):
        raise UnauthorizedShopPathError()
    return normalized


__all__ = [
    "AUTHORIZED_ROOTS_ENV",
    "AUTHORIZED_ROOTS_SETTING",
    "ShopAuthorizationConfigError",
    "UnauthorizedShopPathError",
    "ensure_authorized_shop_path",
    "get_shop_authorized_roots",
    "is_authorized_shop_path",
    "normalize_relative_shop_path",
]
