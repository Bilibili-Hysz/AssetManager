"""H2-c: InfoPanel "AI Tag" button — mock client through the real pipeline.

The button trigger runs the mocked analyze on a worker thread while the
write lands via the real scoped TagService (add_tag_to_files): tags are
persisted, and one batch ``tag_add`` ``activity_log`` row is recorded.
The button must be invisible while ``ai_tagging_enabled`` is off.
"""
import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QFileInfo
from PySide6.QtWidgets import QApplication
from PIL import Image

from AssetsManager.application.ai_tagging.ollama_client import AiTaggingResult
from AssetsManager.application.bootstrap import ApplicationBootstrap
from AssetsManager.core.settings import AppSettings
from AssetsManager.panels.info import InfoPanel


@pytest.fixture()
def enabled_settings():
    """Turn AI tagging on for the test, restore the off default after."""
    settings = AppSettings.instance()
    settings.set_ai_tagging_enabled(True)
    yield settings
    settings.set_ai_tagging_enabled(False)


@pytest.fixture()
def library(tmp_path):
    bootstrap = ApplicationBootstrap()
    root = tmp_path / "library"
    root.mkdir(parents=True, exist_ok=True)
    session = bootstrap.library_service.open_session(root)
    services = bootstrap.runtime_for(session).services
    try:
        yield root, session, services
    finally:
        bootstrap.library_service.close_session(session)


def _make_image(path: Path) -> Path:
    Image.new("RGB", (32, 24), (120, 40, 200)).save(path)
    return path


def _wait_until(predicate, timeout=5.0):
    app = QApplication.instance()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _activity_rows(session):
    conn = session.connection_for(session.root)
    return conn.execute(
        "SELECT action, details FROM activity_log ORDER BY timestamp"
    ).fetchall()


class TestVisibilityGate:
    def test_button_hidden_while_feature_disabled(self):
        app = QApplication.instance() or QApplication([])
        settings = AppSettings.instance()
        settings.set_ai_tagging_enabled(False)  # self-healing: force the off state
        panel = InfoPanel()
        try:
            assert not panel._ai_tag_btn.isVisible()
            # Showing the panel changes nothing: the feature is off.
            panel.show()
            app.processEvents()
            assert panel._ai_tag_btn.isVisibleTo(panel) is False
        finally:
            panel.shutdown()
            panel.deleteLater()
            app.processEvents()

    def test_button_appears_once_enabled_and_file_shown(self, enabled_settings, library):
        app = QApplication.instance() or QApplication([])
        root, session, services = library
        asset = _make_image(root / "photo.png")
        panel = InfoPanel()
        try:
            panel.set_scoped_services(services)
            panel.show()
            panel.update_info(QFileInfo(str(asset)))
            app.processEvents()
            assert panel._ai_tag_btn.isVisibleTo(panel) is True
        finally:
            panel.shutdown()
            panel.deleteLater()
            app.processEvents()

    def test_ai_tag_action_is_noop_while_disabled(self, library, monkeypatch):
        app = QApplication.instance() or QApplication([])
        AppSettings.instance().set_ai_tagging_enabled(False)
        root, session, services = library
        asset = _make_image(root / "photo.png")
        panel = InfoPanel()
        try:
            panel.set_scoped_services(services)
            panel.update_info(QFileInfo(str(asset)))
            # Even if something clicked the hidden button, the disabled
            # gate means no network call and no write.
            monkeypatch.setattr(
                "AssetsManager.application.ai_tagging.service.analyze_image",
                lambda *a, **k: pytest.fail("analyze must not run while disabled"),
            )
            panel._ai_tag()
            app.processEvents()
            assert services.tag_service.get_tags(session.root, str(asset)) == []
        finally:
            panel.shutdown()
            panel.deleteLater()
            app.processEvents()


class TestButtonTriggerWritesThroughService:
    def test_click_persists_whitelisted_tags_and_one_activity_row(
        self, enabled_settings, library, monkeypatch
    ):
        app = QApplication.instance() or QApplication([])
        root, session, services = library
        tag_service = services.tag_service
        asset = _make_image(root / "photo.png")
        seed = _make_image(root / "seed.png")
        assert tag_service.add_tag(session.root, seed, "hero")

        def fake_analyze(endpoint, model, path, *, existing_tags, max_tags, timeout):
            assert endpoint == "http://localhost:11434/v1"
            assert "hero" in existing_tags
            return AiTaggingResult(tags=("HERO", "sky"), description="a hero")

        monkeypatch.setattr(
            "AssetsManager.application.ai_tagging.service.analyze_image",
            fake_analyze,
        )
        settings = enabled_settings
        settings.set_ai_tagging_endpoint("http://localhost:11434/v1")

        panel = InfoPanel()
        try:
            panel.set_scoped_services(services)
            panel.update_info(QFileInfo(str(asset)))
            app.processEvents()
            panel._ai_tag_btn.click()
            # Wait for the completion callback (it renders the chips after
            # the write), not for the raw service state.
            assert _wait_until(lambda: panel._rendered_tags == ("hero",))
            # Write-boundary rule 1: "sky" was outside the whitelist and
            # never persisted; "HERO" converged to the existing spelling.
            assert tag_service.get_tags(session.root, asset) == ["hero"]

            rows = _activity_rows(session)
            assert len(rows) == 1
            action, details = rows[0]
            assert action == "tag_add"
            assert "hero" in details
            # The chips re-rendered from the service after the write.
            assert panel._rendered_tags == ("hero",)
        finally:
            panel.shutdown()
            panel.deleteLater()
            app.processEvents()

    def test_model_error_surfaces_kind_copy(
        self, enabled_settings, library, monkeypatch
    ):
        app = QApplication.instance() or QApplication([])
        from unittest.mock import patch

        root, session, services = library
        asset = _make_image(root / "photo.png")
        from AssetsManager.application.ai_tagging.ollama_client import (
            AiTaggingError,
            AiTaggingErrorKind,
        )

        def failing_analyze(*args, **kwargs):
            raise AiTaggingError(AiTaggingErrorKind.AUTH, "HTTP 403")

        monkeypatch.setattr(
            "AssetsManager.application.ai_tagging.service.analyze_image",
            failing_analyze,
        )
        panel = InfoPanel()
        try:
            panel.set_scoped_services(services)
            panel.update_info(QFileInfo(str(asset)))
            app.processEvents()
            with patch("PySide6.QtWidgets.QMessageBox.warning") as warning:
                panel._ai_tag_btn.click()
                assert _wait_until(lambda: warning.call_count == 1)
                assert "Ollama" in warning.call_args.args[2]
            assert panel._ai_tag_btn.isEnabled()
        finally:
            panel.shutdown()
            panel.deleteLater()
            app.processEvents()
