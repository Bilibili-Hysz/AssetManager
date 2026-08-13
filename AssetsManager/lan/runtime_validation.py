"""Canonical LAN runtime / service-binding validation helpers.

Pure, instance-independent helpers extracted from ``lan/server.py`` so the
server module stays focused on lifecycle orchestration.  Every function here
was moved verbatim from ``server.py``; the server keeps calling them by the
same names, so behavior is unchanged.  These helpers validate that a live
``LibraryRuntime`` provides the canonical session/service snapshot contract the
LAN server relies on, and derive the auth-config-bound local UI secret.
"""
from __future__ import annotations

import hashlib
import hmac
import inspect
import json
import logging
from typing import Any, cast

_log = logging.getLogger(__name__)

_MISSING = object()


def _observe_broadcast(future):
    """Consume a background broadcast future so exceptions never go unobserved."""
    try:
        future.result()
    except Exception:
        _log.exception("WebSocket broadcast failed")


def _runtime_services_snapshot(runtime: Any) -> Any:
    """Return the required canonical runtime service snapshot."""
    if inspect.getattr_static(runtime, "services_snapshot", _MISSING) is _MISSING:
        raise ValueError("runtime must expose the canonical services_snapshot contract")
    return runtime.services_snapshot


def _runtime_operation(runtime: Any, session: Any):
    """Return the required canonical session operation boundary."""
    operation = getattr(session, "operation", None)
    if not callable(operation):
        raise ValueError("runtime session must provide an operation boundary")
    return cast(Any, operation())


def _derive_local_ui_auth_secret(
    token_secret: str,
    *,
    password: str | None,
    access_key: str | None,
    auth_mode: str | None,
) -> str:
    """Derive a stable, auth-config-bound secret for access-key UI tokens."""
    auth_config = json.dumps(
        {
            "access_key": access_key,
            "auth_mode": auth_mode,
            "password": password,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hmac.new(
        token_secret.encode("utf-8"),
        b"lan-local-ui-auth-v1\0" + auth_config,
        hashlib.sha256,
    ).hexdigest()


def _provider_matches_session(service: Any, session: Any) -> bool:
    provider = getattr(service, "_connection_provider", None)
    expected_provider = session.connection_for
    provider_self = getattr(provider, "__self__", None)
    provider_func = getattr(provider, "__func__", None)
    if provider_self is not None:
        return (
            provider_self is session
            and provider_func is getattr(expected_provider, "__func__", None)
        )
    return provider == expected_provider


def _service_session_matches(
    service: Any, session: Any, *, required: bool
) -> bool:
    has_session_binding = (
        inspect.getattr_static(service, "_session", _MISSING) is not _MISSING
    )
    if not has_session_binding:
        return not required
    bound_session = service._session
    if required:
        return bound_session is session
    return bound_session is None or bound_session is session


def _validate_runtime_service_bindings(
    runtime_services: Any,
    lan_services: Any,
    sharing_services: Any,
    session: Any,
    db_conn: Any,
) -> None:
    for owner, name, requires_session in (
        (runtime_services, "metadata_service", True),
        (runtime_services, "tag_service", True),
        (runtime_services, "thumbnail_service", True),
        (lan_services, "project_service", True),
        # Every canonical LAN service is bound to the current session.
        (lan_services, "search_service", True),
    ):
        service = getattr(owner, name, None)
        if (
            service is None
            or not _provider_matches_session(service, session)
            or not _service_session_matches(
                service,
                session,
                required=requires_session,
            )
        ):
            raise ValueError(
                f"runtime {name} provider is not bound to its LibrarySession"
            )

    project_service = getattr(lan_services, "project_service", None)
    for name in ("_metadata_svc", "_tag_svc"):
        nested = getattr(project_service, name, None)
        if (
            nested is None
            or not _provider_matches_session(nested, session)
            or not _service_session_matches(
                nested, session, required=True
            )
        ):
            raise ValueError(
                "runtime project_service internals are not bound to its LibrarySession"
            )

    gallery_service = getattr(lan_services, "gallery_service", None)
    if gallery_service is not None and (
        not _provider_matches_session(gallery_service, session)
        or not _service_session_matches(gallery_service, session, required=True)
    ):
        raise ValueError("runtime gallery_service is not bound to its LibrarySession")

    favorite_service = getattr(lan_services, "favorite_service", None)
    if favorite_service is not None and (
        not _provider_matches_session(favorite_service, session)
        or not _service_session_matches(favorite_service, session, required=True)
    ):
        raise ValueError("runtime favorite_service is not bound to its LibrarySession")

    asset_service = getattr(lan_services, "asset_service", None)
    directory_cache = getattr(asset_service, "_directory_cache", None)
    if directory_cache is None or getattr(directory_cache, "_conn", _MISSING) is not db_conn:
        raise ValueError(
            "runtime asset_service cache is not bound to its LibrarySession"
        )

    token_secret = getattr(sharing_services, "token_secret", None)
    if not isinstance(token_secret, str) or not token_secret:
        raise ValueError("runtime sharing token secret is unavailable")
    for name in ("auth_service", "share_service"):
        service = getattr(sharing_services, name, None)
        if (
            service is None
            or getattr(service, "_conn", _MISSING) is not db_conn
            or getattr(service, "_secret", _MISSING) != token_secret
            or not _service_session_matches(
                service, session, required=True
            )
        ):
            raise ValueError(
                f"runtime {name} is not bound to its LibrarySession sharing bundle"
            )
