"""MediaDerivativesRecorder — payload persistence plus registry upserts (N-A).

Covers the write-side contract of ``application/media/derivatives.py``:
payloads land at ``<data_dir>/derivatives/<kind>/<sha1><ext>`` with POSIX
``rel_path`` rows in ``asset_derivatives``, same-kind re-recording overwrites,
clear removes files and rows, and every failure path is swallowed (log only).
"""

import hashlib
import sqlite3

import pytest

from AssetsManager.application.media.derivatives import (
    DERIVATIVE_KINDS,
    MediaDerivativesRecorder,
    derivatives_root,
)


@pytest.fixture
def db(memory_db):
    """Migrated in-memory library database (v37 tables present)."""
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import migrate

    memory_db.executescript(database._SCHEMA)
    assert migrate(memory_db) == 37
    return memory_db


@pytest.fixture
def recorder(db, tmp_path):
    return MediaDerivativesRecorder(lambda: db, tmp_path / "data_dir")


def _rows(conn):
    return conn.execute(
        "SELECT file_path, kind, rel_path, params, source_mtime, created_at "
        "FROM asset_derivatives"
    ).fetchall()


def _expected_rel_path(path_key, kind, ext):
    digest = hashlib.sha1(path_key.encode("utf-8")).hexdigest()
    return f"{kind}/{digest}{ext}"


def test_record_writes_payload_and_registry_row(recorder, db, tmp_path):
    source = tmp_path / "library" / "hero.png"
    recorder.record(
        source,
        "viewer_image",
        b"rendered-bytes",
        params={"width": 1024, "height": 768},
        source_mtime=1234.5,
        ext=".jpg",
    )

    path_key = str(source.resolve())
    rel_path = _expected_rel_path(path_key, "viewer_image", ".jpg")
    payload = tmp_path / "data_dir" / "derivatives" / rel_path
    assert payload.read_bytes() == b"rendered-bytes"

    rows = _rows(db)
    assert len(rows) == 1
    file_path, kind, row_rel_path, params, source_mtime, created_at = rows[0]
    assert file_path == path_key
    assert kind == "viewer_image"
    assert row_rel_path == rel_path  # POSIX slashes, relative to derivatives/
    assert "\\" not in row_rel_path
    assert params == '{"height": 768, "width": 1024}'
    assert source_mtime == 1234.5
    assert created_at > 0


def test_record_upserts_same_kind_instead_of_duplicating(recorder, db, tmp_path):
    source = tmp_path / "library" / "hero.png"
    recorder.record(source, "video_poster", b"first", ext=".jpg")
    recorder.record(
        source, "video_poster", b"second", ext=".jpg", params={"colors": 8}
    )

    rows = _rows(db)
    assert len(rows) == 1
    assert rows[0][3] == '{"colors": 8}'
    kind_dir = tmp_path / "data_dir" / "derivatives" / "video_poster"
    payloads = list(kind_dir.iterdir())
    assert len(payloads) == 1
    assert payloads[0].read_bytes() == b"second"


def test_record_ext_switch_removes_stale_payload(recorder, db, tmp_path):
    source = tmp_path / "library" / "hero.png"
    recorder.record(source, "contact_sheet", b"png-payload", ext=".png")
    recorder.record(source, "contact_sheet", b"jpg-payload", ext=".jpg")

    kind_dir = tmp_path / "data_dir" / "derivatives" / "contact_sheet"
    assert [p.name for p in kind_dir.iterdir()] == [
        _expected_rel_path(str(source.resolve()), "contact_sheet", ".jpg").split("/")[1]
    ]
    assert next(kind_dir.iterdir()).read_bytes() == b"jpg-payload"
    assert _rows(db)[0][2].endswith(".jpg")


def test_record_without_leading_dot_normalizes_extension(recorder, tmp_path):
    source = tmp_path / "library" / "hero.png"
    recorder.record(source, "audio_waveform", b"wave", ext="png")
    rel_path = _expected_rel_path(str(source.resolve()), "audio_waveform", ".png")
    assert (tmp_path / "data_dir" / "derivatives" / rel_path).read_bytes() == b"wave"


def test_record_copies_source_file_when_bytes_absent(recorder, db, tmp_path):
    source = tmp_path / "library" / "hero.png"
    render = tmp_path / "scratch" / "render.jpg"
    render.parent.mkdir(parents=True)
    render.write_bytes(b"copied-payload")

    recorder.record(source, "viewer_image", ext=".jpg", source_file=render)

    rel_path = _expected_rel_path(str(source.resolve()), "viewer_image", ".jpg")
    payload = tmp_path / "data_dir" / "derivatives" / rel_path
    assert payload.read_bytes() == b"copied-payload"
    assert len(_rows(db)) == 1


def test_record_without_any_payload_is_a_no_op(recorder, db, tmp_path):
    source = tmp_path / "library" / "hero.png"

    recorder.record(source, "viewer_image")  # must not raise

    assert _rows(db) == []
    assert not (tmp_path / "data_dir" / "derivatives").exists()


def test_record_unknown_kind_is_silently_skipped(recorder, db, tmp_path):
    source = tmp_path / "library" / "hero.png"

    recorder.record(source, "wallpaper", b"bytes")  # must not raise

    assert _rows(db) == []
    assert not (tmp_path / "data_dir" / "derivatives").exists()


def test_record_write_failure_does_not_raise(db, tmp_path):
    # data_dir exists as a *file*, so the derivatives mkdir fails.
    blocking = tmp_path / "blocked_data_dir"
    blocking.write_text("not a directory", encoding="utf-8")
    recorder = MediaDerivativesRecorder(lambda: db, blocking)

    recorder.record(tmp_path / "hero.png", "viewer_image", b"bytes")  # no raise

    assert _rows(db) == []


def test_record_survives_broken_connection_provider(tmp_path):
    def broken_provider():
        raise RuntimeError("session closed")

    recorder = MediaDerivativesRecorder(broken_provider, tmp_path / "data_dir")

    recorder.record(tmp_path / "hero.png", "viewer_image", b"bytes")  # no raise
    recorder.clear(tmp_path / "hero.png")  # no raise


def test_record_survives_none_connection(tmp_path):
    recorder = MediaDerivativesRecorder(lambda: None, tmp_path / "data_dir")

    recorder.record(tmp_path / "hero.png", "viewer_image", b"bytes")  # no raise
    recorder.clear(tmp_path / "hero.png")  # no raise
    assert not derivatives_root(tmp_path / "data_dir").exists()


def test_clear_removes_file_and_row_for_one_kind(recorder, db, tmp_path):
    source = tmp_path / "library" / "hero.png"
    recorder.record(source, "viewer_image", b"v", ext=".png")
    recorder.record(source, "video_poster", b"p", ext=".jpg")

    recorder.clear(source, "viewer_image")

    kinds = {row[1] for row in _rows(db)}
    assert kinds == {"video_poster"}
    assert not (
        tmp_path
        / "data_dir"
        / "derivatives"
        / _expected_rel_path(str(source.resolve()), "viewer_image", ".png")
    ).exists()
    assert (
        tmp_path
        / "data_dir"
        / "derivatives"
        / _expected_rel_path(str(source.resolve()), "video_poster", ".jpg")
    ).exists()


def test_clear_without_kind_removes_every_derivative(recorder, db, tmp_path):
    source = tmp_path / "library" / "hero.png"
    recorder.record(source, "viewer_image", b"v", ext=".png")
    recorder.record(source, "extracted_palette", b"p", ext=".json")

    recorder.clear(source)  # kind=None

    assert _rows(db) == []
    assert list(derivatives_root(tmp_path / "data_dir").rglob("*.*")) == []


def test_record_preserves_caller_transaction(recorder, db, tmp_path):
    source = tmp_path / "library" / "hero.png"
    db.execute("BEGIN")
    try:
        recorder.record(source, "viewer_image", b"v", ext=".png")
        # The recorder must not commit the caller's outer transaction.
        assert db.in_transaction
        db.rollback()
    finally:
        if db.in_transaction:
            db.rollback()
    assert _rows(db) == []


def test_kind_whitelist_matches_migration_v37_check():
    assert DERIVATIVE_KINDS == frozenset(
        {
            "viewer_image",
            "video_poster",
            "contact_sheet",
            "audio_waveform",
            "extracted_palette",
            "sequence_manifest",
        }
    )


def test_bootstrap_injects_recorder_into_runtime_services(opened_session):
    from AssetsManager.application.media.derivatives import MediaDerivativesRecorder

    bootstrap, session = opened_session
    services = bootstrap.runtime_for(session).services

    recorder = services.media_derivatives_recorder
    assert isinstance(recorder, MediaDerivativesRecorder)
    assert recorder.data_dir.resolve() == session.data_dir.resolve()


def test_bootstrap_recorder_roundtrip_through_session(opened_session, tmp_path):
    bootstrap, session = opened_session
    services = bootstrap.runtime_for(session).services
    asset = session.root / "asset.txt"
    asset.write_text("asset", encoding="utf-8")

    recorder = services.media_derivatives_recorder
    recorder.record(asset, "sequence_manifest", b'{"frames": []}', ext=".json")

    conn = session.connection_for(session.root)
    rows = conn.execute(
        "SELECT file_path, kind, rel_path FROM asset_derivatives"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == str(asset.resolve())
    assert rows[0][2] == _expected_rel_path(
        str(asset.resolve()), "sequence_manifest", ".json"
    )
    payload = recorder.data_dir / "derivatives" / rows[0][2]
    assert payload.read_bytes() == b'{"frames": []}'
    assert recorder.data_dir.resolve() == session.data_dir.resolve()


def test_sqlite_enforces_asset_derivatives_primary_key():
    """Guard the upsert contract: same (file_path, kind) cannot duplicate."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE asset_derivatives ("
        "file_path TEXT NOT NULL, kind TEXT NOT NULL, "
        "PRIMARY KEY (file_path, kind))"
    )
    conn.execute(
        "INSERT INTO asset_derivatives VALUES ('/a.png', 'viewer_image')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO asset_derivatives VALUES ('/a.png', 'viewer_image')"
        )
