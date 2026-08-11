"""Test-only adapters for pre-canonical LAN runtime fixtures.

Nothing in ``AssetsManager`` may import this module.  The adapter exists only
so historical low-level route fixtures can be upgraded to the canonical
runtime contract before they reach ``_LanServerImpl``.
"""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any

_MISSING = object()


class LegacyBoundServiceProjection:
    """Structural session projection for a provider-only legacy service.

    Historical LAN fixtures construct raw application services with an explicit
    connection provider but no canonical ``LibrarySession`` binding.  Mutating
    strict services in-place (especially ``MetadataService``) is unsafe because
    their binding state includes captured root identity and a retained
    repository.  This test-only projection exposes the fields inspected by the
    canonical LAN server while delegating all behavior to the original raw
    service.
    """

    __slots__ = ("_service", "_session", "_connection_provider")

    def __init__(self, service: Any, session: Any) -> None:
        self._service = service
        self._session = session
        self._connection_provider = getattr(service, "_connection_provider", None)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._service, name)


def _bind_session(service: Any, session: Any) -> None:
    """Bind legacy non-strict service objects when they expose the field."""
    if hasattr(service, "_session") and service._session is None:
        service._session = session
    if hasattr(service, "_library_root") and not service._library_root:
        service._library_root = str(getattr(session, "root_str", session.root))
    if hasattr(service, "_session_token") and not service._session_token:
        service._session_token = getattr(session, "event_token", "")


def _metadata_projection(
    service: Any, session: Any, projections: dict[int, LegacyBoundServiceProjection]
) -> Any:
    """Project only raw ``MetadataService`` instances; keep canonical ones intact."""
    from AssetsManager.application.metadata_service import MetadataService

    if isinstance(service, MetadataService) and service._session is None:
        key = id(service)
        projection = projections.get(key)
        if projection is None:
            projection = LegacyBoundServiceProjection(service, session)
            projections[key] = projection
        return projection
    _bind_session(service, session)
    return service


def _adapt_project_service(
    service: Any,
    session: Any,
    projections: dict[int, LegacyBoundServiceProjection],
) -> Any:
    """Bind a legacy project service without falsifying strict metadata state."""
    nested_metadata = getattr(service, "_metadata_svc", None)
    if nested_metadata is not None:
        adapted = _metadata_projection(nested_metadata, session, projections)
        if adapted is not nested_metadata:
            # ProjectService reads this dependency from its own instance, so the
            # projection must be installed on the delegated raw service too.
            service._metadata_svc = adapted
    nested_tag = getattr(service, "_tag_svc", None)
    if nested_tag is not None:
        _bind_session(nested_tag, session)
    _bind_session(service, session)
    return service


def adapt_legacy_runtime(runtime: Any) -> Any:
    """Upgrade a legacy SimpleNamespace runtime to the canonical test shape.

    The adapter supplies only the contracts that old fixtures omitted:
    ``session.operation``, ``runtime.services_snapshot``, the explicit
    ``lan_services`` projection, and the ``sharing_services`` projection.
    Provider-only legacy SearchService fixtures are bound to the fixture's
    session here; the production LAN server never accepts an unbound service.
    """
    session = runtime.session
    if not callable(getattr(session, "operation", None)):
        session.operation = nullcontext

    legacy_services = getattr(runtime, "services", None)
    if legacy_services is None:
        raise ValueError("legacy runtime fixture must expose services")

    existing_snapshot = getattr(runtime, "services_snapshot", _MISSING)
    if existing_snapshot is not _MISSING:
        snapshot = existing_snapshot
    elif all(
        hasattr(legacy_services, name)
        for name in ("lan_services", "sharing_services")
    ):
        snapshot = legacy_services
    else:
        from AssetsManager.application import RuntimeSharingServices

        token_secret = getattr(legacy_services, "token_secret", None)
        if token_secret is None:
            token_secret = getattr(legacy_services, "_token_secret", None)
        if token_secret is None:
            token_secret = getattr(legacy_services, "_secret", None)
        sharing_services = getattr(legacy_services, "sharing_services", None)
        if sharing_services is None:
            sharing_services = RuntimeSharingServices(
                token_secret=token_secret or "legacy-runtime-test-secret",
                auth_service=legacy_services.auth_service,
                share_service=legacy_services.share_service,
            )
        snapshot = SimpleNamespace(
            session=session,
            sharing_services=sharing_services,
            metadata_service=legacy_services.metadata_service,
            tag_service=legacy_services.tag_service,
            thumbnail_service=legacy_services.thumbnail_service,
            lan_services=SimpleNamespace(
                asset_service=legacy_services.asset_service,
                project_service=legacy_services.project_service,
                search_service=legacy_services.search_service,
            ),
        )

    if not hasattr(snapshot, "session"):
        setattr(snapshot, "session", session)

    projections: dict[int, LegacyBoundServiceProjection] = {}
    for owner, names in (
        (snapshot, ("metadata_service", "tag_service", "thumbnail_service")),
        (
            getattr(snapshot, "lan_services", None),
            ("asset_service", "project_service", "search_service"),
        ),
        (
            getattr(snapshot, "sharing_services", None),
            ("auth_service", "share_service"),
        ),
    ):
        if owner is None:
            continue
        for name in names:
            service = getattr(owner, name, None)
            if service is None:
                continue
            if name == "metadata_service":
                adapted = _metadata_projection(service, session, projections)
                if adapted is not service:
                    setattr(owner, name, adapted)
            elif name == "project_service":
                _adapt_project_service(service, session, projections)
            else:
                _bind_session(service, session)

    runtime.services_snapshot = snapshot
    return runtime
