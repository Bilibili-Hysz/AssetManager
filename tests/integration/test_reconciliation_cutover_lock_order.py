"""Cutover ownership ordering around the per-library process lock."""

from __future__ import annotations


def test_library_lock_is_acquired_before_database_connection_for_cutover(
    tmp_path, monkeypatch
):
    from AssetsManager.application.library_service import LibraryService
    from AssetsManager.core import path_resolver

    monkeypatch.setattr(path_resolver, "runtime_root", lambda: tmp_path / "RuntimeData")
    root = tmp_path / "library"
    root.mkdir()
    service = LibraryService()
    events: list[tuple[str, str]] = []
    real_acquire = service._acquire_library_lock
    real_connection_for = service._db.connection_for

    def acquire_lock(key: str):
        events.append(("lock", key))
        return real_acquire(key)

    def connection_for(identity):
        assert events and events[0][0] == "lock"
        events.append(("connection", str(identity)))
        return real_connection_for(identity)

    monkeypatch.setattr(service, "_acquire_library_lock", acquire_lock)
    monkeypatch.setattr(service._db, "connection_for", connection_for)

    session = service.open_session(root)
    try:
        assert [kind for kind, _value in events[:2]] == ["lock", "connection"]
        assert session.root == root.resolve()
    finally:
        service.close_session(session)
        service.close()
