"""Desktop file/tag/import operations land in the persisted activity_log (T6).

The desktop writes rows through ``application/activity_recorder.py`` into the
per-library ``activity_log`` table; the LAN ``ActivityLog.recent()`` reader
(web admin activity feed) must serve those rows unchanged.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest

from AssetsManager.application.bootstrap import ApplicationBootstrap
from AssetsManager.application.import_service import ImportService


@pytest.fixture(autouse=True)
def _no_reconciliation_worker(monkeypatch):
    """Keep the shared-connection reconciliation worker out of these tests.

    Same rationale as test_file_operation_service: the worker's claim
    transactions race the delete clean-boundary checks on slower CI.
    """
    from AssetsManager.application.asset_index_reconciliation_service import (
        AssetIndexReconciliationService,
    )

    monkeypatch.setattr(
        AssetIndexReconciliationService, "start", lambda self: False
    )


@pytest.fixture
def scoped(tmp_path):
    """Bootstrap session with the desktop activity recorder wired."""
    library = tmp_path / "library"
    library.mkdir(parents=True, exist_ok=True)
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(library)
    services = bootstrap.runtime_for(session).services
    services.reconciliation_service.stop()
    try:
        yield services, library
    finally:
        bootstrap.library_service.close()


def _activity_rows(services, library):
    conn = services.session.connection_for(library)
    return conn.execute(
        "SELECT username, action, details, ip FROM activity_log ORDER BY id"
    ).fetchall()


def test_delete_to_trash_records_single_activity_row(scoped):
    services, library = scoped
    target = library / "hero.png"
    target.write_text("image", encoding="utf-8")

    result = services.file_operation_service.delete_to_trash([target])

    assert result.ok
    rows = _activity_rows(services, library)
    assert len(rows) == 1
    username, action, details, ip = rows[0]
    assert username == "desktop"
    assert action == "delete_to_trash"
    assert str(target) in details
    assert ip == "local"


def test_batch_delete_records_one_row_with_target_count(scoped):
    services, library = scoped
    targets = []
    for index in range(3):
        target = library / f"asset_{index}.png"
        target.write_text("image", encoding="utf-8")
        targets.append(target)

    result = services.file_operation_service.delete_to_trash(targets)

    assert result.ok
    rows = _activity_rows(services, library)
    assert len(rows) == 1
    _username, action, details, _ip = rows[0]
    assert action == "delete_to_trash"
    # One row for the whole batch: count plus the (truncated) path list.
    assert details.startswith("3 targets: ")
    assert str(targets[0]) in details


def test_activity_recorder_failure_does_not_break_operation(scoped, monkeypatch):
    services, library = scoped
    target = library / "kept.png"
    target.write_text("image", encoding="utf-8")

    class ExplodingRecorder:
        def record(self, *args, **kwargs):
            raise RuntimeError("activity backend down")

    monkeypatch.setattr(
        services.file_operation_service, "_activity_recorder", ExplodingRecorder()
    )

    result = services.file_operation_service.delete_to_trash([target])

    assert result.ok
    assert not target.exists()


def test_recorder_never_raises_when_connection_unavailable(tmp_path):
    from AssetsManager.application.activity_recorder import ActivityRecorder

    def broken_provider():
        raise RuntimeError("session closed")

    recorder = ActivityRecorder(broken_provider)
    recorder.record("delete_to_trash", "whatever")  # must not raise


def test_lan_recent_reads_desktop_rows(scoped):
    from AssetsManager.lan.routes._helpers import ActivityLog

    services, library = scoped
    target = library / "shared.png"
    target.write_text("image", encoding="utf-8")
    assert services.file_operation_service.delete_to_trash([target]).ok

    lan_log = ActivityLog(
        connection_provider=lambda: services.session.connection_for(library)
    )
    rows = lan_log.recent(10)

    desktop_rows = [row for row in rows if row["username"] == "desktop"]
    assert len(desktop_rows) == 1
    assert desktop_rows[0]["action"] == "delete_to_trash"
    assert "shared.png" in desktop_rows[0]["details"]


def test_batch_tag_add_records_one_row(scoped):
    services, library = scoped
    files = []
    for index in range(3):
        target = library / f"photo_{index}.png"
        target.write_text("image", encoding="utf-8")
        files.append(target)

    added = services.tag_service.add_tag_to_files(
        services.session.root_str, files, "hero"
    )

    assert added == 3
    rows = _activity_rows(services, library)
    assert len(rows) == 1
    _username, action, details, _ip = rows[0]
    assert action == "tag_add"
    assert "hero" in details
    assert details.startswith("hero -> 3 targets: ")
    # The tagging itself still applied the tag to every file.
    for target in files:
        assert "hero" in services.tag_service.get_tags(
            services.session.root_str, target
        )


def test_batch_tag_add_skips_row_when_nothing_changed(scoped):
    services, library = scoped
    target = library / "already.png"
    target.write_text("image", encoding="utf-8")
    services.tag_service.add_tag_to_files(
        services.session.root_str, [target], "hero"
    )
    assert len(_activity_rows(services, library)) == 1

    # Re-applying the same tag is a no-op: no second activity row.
    added = services.tag_service.add_tag_to_files(
        services.session.root_str, [target], "hero"
    )

    assert added == 0
    assert len(_activity_rows(services, library)) == 1


def test_import_completion_records_one_row(scoped):
    services, library = scoped
    external = library.parent / "external"
    external.mkdir()
    for index in range(2):
        (external / f"shot_{index}.png").write_text("image", encoding="utf-8")

    service = ImportService(services.session, services.file_operation_service)
    result = service.import_sources(
        [external / "shot_0.png", external / "shot_1.png"],
        library / "imported",
    )

    assert result.copied == 2 and not result.failed
    rows = _activity_rows(services, library)
    assert len(rows) == 1
    _username, action, details, _ip = rows[0]
    assert action == "import"
    assert details.startswith("2 files -> ")
    assert str(library / "imported") in details


def test_rename_records_one_row(scoped):
    services, library = scoped
    target = library / "old_name.png"
    target.write_text("image", encoding="utf-8")

    renamed = services.file_operation_service.rename(target, "new_name.png")

    assert renamed == library / "new_name.png"
    rows = _activity_rows(services, library)
    assert len(rows) == 1
    _username, action, details, _ip = rows[0]
    # rename delegates to move internally but records a single "rename" row.
    assert action == "rename"
    assert str(library / "new_name.png") in details


def test_failed_delete_records_no_row(scoped, monkeypatch):
    services, library = scoped
    missing = library / "missing.png"

    result = services.file_operation_service.delete_to_trash([missing])

    assert not result.ok
    assert _activity_rows(services, library) == []


def test_activity_recorder_persists_directly(tmp_path):
    import sqlite3

    from AssetsManager.application.activity_recorder import (
        DESKTOP_USER,
        ActivityRecorder,
        summarize_targets,
    )

    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE activity_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL,"
        " action TEXT NOT NULL, details TEXT NOT NULL DEFAULT '',"
        " ip TEXT NOT NULL DEFAULT 'unknown', timestamp REAL NOT NULL)"
    )
    recorder = ActivityRecorder(lambda: conn)
    recorder.record("move", summarize_targets([Path("a"), Path("b")]))

    row = conn.execute(
        "SELECT username, action, details, ip FROM activity_log"
    ).fetchone()
    assert row[0] == DESKTOP_USER
    assert row[1] == "move"
    assert row[2] == "2 targets: a, b"
