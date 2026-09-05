"""Canonical session contract tests for AuthService and ShareService."""

from __future__ import annotations

from contextlib import nullcontext
import sqlite3
from types import SimpleNamespace

import pytest

from AssetsManager.application import ApplicationBootstrap
from AssetsManager.application.auth_service import AuthService
from AssetsManager.application.share_service import ShareService
from AssetsManager.core.session_contract import register_library_session


class _EventCollector:
    def __init__(self) -> None:
        self.events: list[object] = []

    def publish(self, event: object) -> None:
        self.events.append(event)


def test_bootstrap_binds_auth_and_share_services_to_current_session(tmp_path):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    try:
        services = bootstrap.runtime_for(session).services.sharing_services
        assert services.auth_service._session is session
        assert services.share_service._session is session
        assert services.auth_service._repo._session is session
        assert services.share_service._repo._session is session
        assert services.auth_service._conn is session.connection_for(session.root)
        assert services.share_service._conn is session.connection_for(session.root)
    finally:
        bootstrap.library_service.close()


def test_session_bound_auth_and_share_services_reject_operations_after_close(tmp_path):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    try:
        services = bootstrap.runtime_for(session).services.sharing_services
        session.close()
        with pytest.raises(RuntimeError, match="closed LibrarySession"):
            services.auth_service.list_users()
        with pytest.raises(RuntimeError, match="closed LibrarySession"):
            services.share_service.list_shares()
    finally:
        bootstrap.library_service.close()


def test_session_bound_auth_share_mutations_after_close_do_not_touch_repo_or_publish(
    tmp_path, monkeypatch
):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    try:
        services = bootstrap.runtime_for(session).services.sharing_services
        collector = _EventCollector()
        services.auth_service._event_bus = collector
        services.share_service._event_bus = collector

        auth_mutations: list[tuple[tuple, dict]] = []
        share_mutations: list[tuple[tuple, dict]] = []

        def record_auth_mutation(*args, **kwargs):
            auth_mutations.append((args, kwargs))
            return True

        def record_share_mutation(*args, **kwargs):
            share_mutations.append((args, kwargs))
            return True

        monkeypatch.setattr(
            services.auth_service._repo,
            "set_user_active",
            record_auth_mutation,
        )
        monkeypatch.setattr(
            services.share_service._repo,
            "delete",
            record_share_mutation,
        )

        session.close()

        with pytest.raises(RuntimeError, match="closed LibrarySession"):
            services.auth_service.activate_user(1)
        with pytest.raises(RuntimeError, match="closed LibrarySession"):
            services.share_service.delete_share("share-id")

        assert auth_mutations == []
        assert share_mutations == []
        assert collector.events == []
    finally:
        bootstrap.library_service.close()


@pytest.mark.parametrize(
    ("service_type", "message"),
    [
        (AuthService, "AuthService connection does not belong"),
        (ShareService, "ShareService connection does not belong"),
    ],
)
def test_session_bound_auth_share_services_reject_foreign_connection(service_type, message, tmp_path):
    expected = sqlite3.connect(":memory:")
    foreign = sqlite3.connect(":memory:")
    session = SimpleNamespace(
        root=tmp_path / "library",
        root_str=str(tmp_path / "library"),
        event_token="session-token",
        connection_for=lambda _root: expected,
        operation=nullcontext,
    )
    try:
        with pytest.raises(ValueError, match=message):
            service_type(foreign, "secret", session=session)
    finally:
        expected.close()
        foreign.close()


@pytest.mark.parametrize("service_type", [AuthService, ShareService], ids=["auth", "share"])
@pytest.mark.parametrize(
    "case",
    ["noncallable-provider", "missing-operation", "missing-root"],
)
def test_malformed_session_does_not_silently_downgrade_to_raw_legacy(
    service_type, case, tmp_path
):
    conn = sqlite3.connect(":memory:")
    service = service_type(conn, "secret")
    original_repository = service._repo
    root = tmp_path / "library"
    if case == "noncallable-provider":
        session = SimpleNamespace(
            root=root,
            root_str=str(root),
            event_token="session-token",
            connection_for=None,
            operation=nullcontext,
        )
    elif case == "missing-operation":
        session = SimpleNamespace(
            root_str=str(root),
            event_token="session-token",
        )
    else:
        session = SimpleNamespace(
            event_token="session-token",
            operation=nullcontext,
        )

    try:
        with pytest.raises(TypeError):
            service._bind_session(session)
        assert service._session is None
        assert service._repo is original_repository
    finally:
        conn.close()


@pytest.mark.parametrize("service_type", [AuthService, ShareService], ids=["auth", "share"])
def test_service_binding_is_not_published_when_session_starts_closing(
    service_type, tmp_path
):
    bootstrap = ApplicationBootstrap()
    real_session = bootstrap.library_service.open_session(tmp_path / "library")
    try:
        conn = real_session.connection_for(real_session.root)
        publication_count = 0

        def publish_while_live(callback):
            nonlocal publication_count
            publication_count += 1
            if publication_count == 1:
                return callback()
            raise RuntimeError("Cannot publish services for a closing LibrarySession")

        session = register_library_session(
            SimpleNamespace(
                root=real_session.root,
                root_str=real_session.root_str,
                event_token="session-token",
                connection_for=lambda _root: conn,
                operation=nullcontext,
                _publish_while_live=publish_while_live,
                # The strict dialect resolves the captured identity, not the
                # duck-typed root strings above.
                context=SimpleNamespace(
                    root_identity=real_session.context.root_identity
                ),
            )
        )
        service = service_type(conn, "secret")
        original_repository = service._repo

        with pytest.raises(RuntimeError, match="closing LibrarySession"):
            service._bind_session(session)

        assert publication_count == 2
        assert service._session is None
        assert service._repo is original_repository
        assert service._library_root == ""
        assert service._session_token == ""
    finally:
        bootstrap.library_service.close()


def test_legacy_fake_session_without_connection_provider_remains_compatible():
    conn = sqlite3.connect(":memory:")
    session = SimpleNamespace(
        root_str="/legacy/library",
        event_token="legacy-token",
        operation=nullcontext,
    )
    try:
        auth = AuthService(conn, "secret", session=session)
        share = ShareService(conn, "secret", session=session)
        assert auth._session is session
        assert share._session is session
        assert auth._library_root == "/legacy/library"
        assert share._library_root == "/legacy/library"
        assert auth._repo._session is None
        assert share._repo._session is None
    finally:
        conn.close()
