"""Regression tests for AuthService revocation session leases."""

from __future__ import annotations

import threading

import pytest

from AssetsManager.application.auth_service import AuthService


class _OperationSession:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._closed = False
        self.active = 0
        self.entered = threading.Event()
        self.release = threading.Event()

    def operation(self):
        session = self

        class Lease:
            def __enter__(self):
                with session._condition:
                    if session._closed:
                        raise RuntimeError("Cannot use a closed LibrarySession")
                    session.active += 1
                    session.entered.set()
                return None

            def __exit__(self, exc_type, exc, tb):
                with session._condition:
                    session.active -= 1
                    session._condition.notify_all()

        return Lease()

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.wait_for(lambda: self.active == 0, timeout=2)


class _BlockingRevocationRepository:
    def add(self, digest: str, *, expires_at: float) -> None:
        self.started.set()
        assert self.release.wait(2)

    def is_revoked(self, digest: str) -> bool:
        return False

    def load_active(self) -> dict[str, float]:
        return {}

    def prune_expired(self) -> int:
        return 0

    def bind(self, started: threading.Event, release: threading.Event) -> None:
        self.started = started
        self.release = release


def test_revocation_database_operation_is_drained_before_session_close(schema_db):
    session = _OperationSession()
    service = AuthService(schema_db, "secret")
    service._session = session
    repository = _BlockingRevocationRepository()
    started = threading.Event()
    release = threading.Event()
    repository.bind(started, release)
    service._revoked_repo = repository

    worker_error: list[BaseException] = []

    def revoke() -> None:
        try:
            service.revoke_token("token")
        except BaseException as exc:  # pragma: no cover - diagnostic assertion below
            worker_error.append(exc)

    worker = threading.Thread(target=revoke)
    worker.start()
    assert started.wait(2)

    close_thread = threading.Thread(target=session.close)
    close_thread.start()
    assert close_thread.is_alive()

    release.set()
    worker.join(timeout=2)
    close_thread.join(timeout=2)

    assert worker_error == []
    assert not worker.is_alive()
    assert not close_thread.is_alive()
    assert session.active == 0


def test_revocation_service_propagates_persistence_failure(schema_db, monkeypatch):
    service = AuthService(schema_db, "secret")

    def fail(*args, **kwargs):
        raise RuntimeError("database write failed")

    monkeypatch.setattr(service._revocation_repo(), "add", fail)

    with pytest.raises(RuntimeError, match="database write failed"):
        service.revoke_token("token")
