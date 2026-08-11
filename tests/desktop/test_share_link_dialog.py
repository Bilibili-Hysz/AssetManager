import os
from pathlib import Path
from sqlite3 import connect
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication, QLineEdit

from AssetsManager.application.context import LibraryContext, LibrarySession
from AssetsManager.dialogs.share_link_dialog import ShareLinkDialog


def test_share_link_dialog_keeps_password_input_as_line_edit():
    app = QApplication.instance() or QApplication([])
    dialog = ShareLinkDialog(path="asset.txt", server=Mock(_port=8080))
    try:
        assert isinstance(dialog._password_input, QLineEdit)
        assert dialog._password_input.echoMode() == QLineEdit.EchoMode.Password
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_share_link_dialog_normalizes_legacy_and_multi_path_inputs():
    legacy = ShareLinkDialog(path="asset.txt", server=Mock(_port=8080))
    multiple = ShareLinkDialog(paths=["one.txt", "two.txt"], server=Mock(_port=8080))
    try:
        assert legacy._paths == ["asset.txt"]
        assert multiple._paths == ["one.txt", "two.txt"]
    finally:
        legacy.close()
        multiple.close()
        legacy.deleteLater()
        multiple.deleteLater()


def test_share_link_dialog_disables_unscoped_creation():
    dialog = ShareLinkDialog(server=Mock(_port=8080))
    try:
        assert not dialog._create_btn.isEnabled()
        assert not dialog._selection_hint.isHidden()
    finally:
        dialog.close()
        dialog.deleteLater()


def test_share_link_result_mode_requires_explicit_create_another():
    # The server stub declares an explicit no-session contract so the
    # staleness checks in _on_create_result treat it as sessionless.
    dialog = ShareLinkDialog(paths=["one.txt", "two.txt"], server=Mock(_port=8080, session=None))
    try:
        dialog._on_create_result(True, {"url": "http://share.test/s/1"})

        assert dialog.get_share_url() == "http://share.test/s/1"
        assert dialog._create_btn.isHidden()
        assert not dialog._create_another_btn.isHidden()
        assert dialog._qr_btn.isEnabled()

        dialog._create_another()

        assert dialog.get_share_url() is None
        assert not dialog._create_btn.isHidden()
        assert dialog._create_another_btn.isHidden()
        assert not dialog._qr_btn.isEnabled()
    finally:
        dialog.close()
        dialog.deleteLater()


def test_share_link_ignores_result_from_replaced_server():
    server = Mock(_port=8080)
    dialog = ShareLinkDialog(paths=["asset.txt"], server=server)
    try:
        dialog._creating = True
        dialog._server = Mock(_port=8081)
        dialog._on_create_result(True, {"url": "http://share.test/s/1"}, server)

        assert dialog.get_share_url() is None
        assert dialog._creating is True
    finally:
        dialog.close()
        dialog.deleteLater()


def test_share_link_dialog_creates_with_service_without_server(monkeypatch):
    app = QApplication.instance() or QApplication([])
    service = Mock()
    dialog = ShareLinkDialog(
        paths=["asset.txt"], share_service=service,
        base_url="http://share.test:8080", requires_key=True,
    )
    started = []
    monkeypatch.setattr(QThreadPool.globalInstance(), "start", started.append)
    monkeypatch.setattr("requests.request", Mock(side_effect=AssertionError("HTTP POST used")))
    try:
        dialog._create_link()

        assert dialog._creating is True
        assert len(started) == 1
        assert started[0].__class__.__name__ == "ShareCreationTask"
        assert started[0]._share_service is service
        assert started[0]._base_url == "http://share.test:8080"
        assert started[0]._options["created_by"] == "local_ui"
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_share_link_dialog_ignores_result_from_replaced_service():
    first_service = Mock()
    second_service = Mock()
    dialog = ShareLinkDialog(paths=["asset.txt"], share_service=first_service)
    try:
        dialog._creating = True
        dialog._share_service = second_service
        dialog._on_create_result(True, {"url": "http://share.test/s/1"}, first_service)

        assert dialog.get_share_url() is None
        assert dialog._creating is True
    finally:
        dialog.close()
        dialog.deleteLater()


def test_share_link_dialog_does_not_roll_back_ui_on_stale_result():
    first_service = Mock()
    second_service = Mock()
    dialog = ShareLinkDialog(paths=["asset.txt"], share_service=first_service)
    try:
        dialog._creating = True
        dialog._create_btn.setEnabled(False)
        dialog._create_btn.setText("creating")
        dialog._share_service = second_service
        dialog._on_create_result(False, {"error": "old"}, first_service)

        assert dialog._creating is True
        assert not dialog._create_btn.isEnabled()
        assert dialog._create_btn.text() == "creating"
    finally:
        dialog.close()
        dialog.deleteLater()


def _real_session():
    context = LibraryContext(
        root=Path("."), data_dir=Path("."), thumb_dir=Path("."),
        db_conn=connect(":memory:"), tag_store=Mock(), project_data=Mock(),
    )
    return LibrarySession.from_context(context)


def test_share_link_rejects_result_after_real_session_close():
    session = _real_session()
    runtime = SimpleNamespace(epoch="runtime-1")
    service = Mock(_session=session, _runtime=runtime)
    dialog = ShareLinkDialog(
        paths=["asset.txt"], share_service=service,
        base_url="http://share.test:8080", session=session, runtime=runtime,
    )
    try:
        dialog._creating = True
        dialog._request_generation = 1
        session.close()

        dialog._on_create_result(
            True, {"url": "http://share.test/s/closed"}, service,
            session, runtime, "runtime-1", 1,
        )

        assert dialog.get_share_url() is None
        assert dialog._creating is True
    finally:
        dialog.close()
        dialog.deleteLater()


def test_share_link_rejects_result_after_runtime_epoch_changes():
    session = _real_session()
    runtime = SimpleNamespace(epoch="runtime-1")
    service = Mock(_session=session, _runtime=runtime)
    dialog = ShareLinkDialog(
        paths=["asset.txt"], share_service=service,
        base_url="http://share.test:8080", session=session, runtime=runtime,
    )
    try:
        dialog._creating = True
        dialog._request_generation = 1
        runtime.epoch = "runtime-2"

        dialog._on_create_result(
            True, {"url": "http://share.test/s/old-runtime"}, service,
            session, runtime, "runtime-1", 1,
        )

        assert dialog.get_share_url() is None
        assert dialog._creating is True
    finally:
        dialog.close()
        dialog.deleteLater()
        session.close()
