"""H2-c: FileList batch "AI Tag (Selected)" action — mocked client.

The batch mirrors the H1 batch-tagging pipeline: worker thread, one
session-bound feedback label with a partial-failure summary, and the
write through ``TagService.add_tag_to_files``. The context-menu item only
exists while ``ai_tagging_enabled`` is on.
"""
import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication

from AssetsManager.application.ai_tagging.ollama_client import (
    AiTaggingError,
    AiTaggingErrorKind,
    AiTaggingResult,
)
from AssetsManager.core.settings import AppSettings
from AssetsManager.panels._ai_tag_common import ai_tagging_enabled


@pytest.fixture()
def enabled_settings():
    settings = AppSettings.instance()
    settings.set_ai_tagging_enabled(True)
    yield settings
    settings.set_ai_tagging_enabled(False)


def _make_image(path: Path) -> Path:
    Image.new("RGB", (24, 24), (10, 120, 40)).save(path)
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


def _tag_submenu_texts(panel, asset_path):
    """Return the action texts of the context menu's Tags submenu."""
    menu = panel._build_context_menu([str(asset_path)], panel.rect().center())
    try:
        for action in menu.actions():
            # One .menu() call per action, wrapper held in a local: a second
            # call's discarded wrapper would invalidate the C++ submenu.
            submenu = action.menu()
            if submenu is not None and action.text() == "Tags":
                return [item.text() for item in submenu.actions()]
        raise AssertionError("Tags submenu not found in context menu")
    finally:
        menu.deleteLater()


class TestContextMenuGate:
    def test_menu_item_absent_while_disabled(self, file_list_panel_ctx, tmp_path):
        panel, session, bootstrap, services = file_list_panel_ctx
        settings = AppSettings.instance()
        settings.set_ai_tagging_enabled(False)  # self-healing: force the off state
        settings.save()
        assert not ai_tagging_enabled()
        asset = _make_image(Path(session.root) / "photo.png")
        texts = _tag_submenu_texts(panel, asset)
        assert "Apply Tag..." in texts  # the human batch entry stays
        assert not any("AI Tag" in text for text in texts)

    def test_menu_item_present_when_enabled(self, enabled_settings, file_list_panel_ctx):
        panel, session, bootstrap, services = file_list_panel_ctx
        asset = _make_image(Path(session.root) / "photo.png")
        texts = _tag_submenu_texts(panel, asset)
        assert "AI Tag (Selected)" in texts


class TestBatchAction:
    def test_batch_tags_files_and_reports_partial_failure(
        self, enabled_settings, file_list_panel_ctx, monkeypatch
    ):
        panel, session, bootstrap, services = file_list_panel_ctx
        tag_service = services.tag_service
        seed = _make_image(Path(session.root) / "seed.png")
        ok_file = _make_image(Path(session.root) / "ok.png")
        bad_file = _make_image(Path(session.root) / "bad.png")
        assert tag_service.add_tag(session.root, seed, "hero")

        def fake_analyze(endpoint, model, path, *, existing_tags, max_tags, timeout):
            if "bad" in str(path):
                raise AiTaggingError(AiTaggingErrorKind.TIMEOUT, "timed out")
            return AiTaggingResult(tags=("HERO",), description="")

        monkeypatch.setattr(
            "AssetsManager.application.ai_tagging.service.analyze_image",
            fake_analyze,
        )
        panel._ai_tag_batch([str(ok_file), str(bad_file)])
        assert _wait_until(
            lambda: tag_service.get_tags(session.root, str(ok_file)) == ["hero"]
        )
        app = QApplication.instance()
        for _ in range(20):
            app.processEvents()
            text = panel._operation_feedback.text()
            if "failed" in text:
                break
            time.sleep(0.01)
        # Partial-failure summary: one tag added, one image failed.
        assert "AI tagging" in text
        assert "1" in text
        assert "failed" in text
        # The write went through the service (canonicalized spelling).
        assert tag_service.get_tags(session.root, str(ok_file)) == ["hero"]
        assert tag_service.get_tags(session.root, str(bad_file)) == []

    def test_batch_noop_while_disabled(self, file_list_panel_ctx, monkeypatch):
        panel, session, bootstrap, services = file_list_panel_ctx
        AppSettings.instance().set_ai_tagging_enabled(False)
        asset = _make_image(Path(session.root) / "photo.png")
        monkeypatch.setattr(
            "AssetsManager.application.ai_tagging.service.analyze_image",
            lambda *a, **k: pytest.fail("analyze must not run while disabled"),
        )
        panel._ai_tag_batch([str(asset)])
        app = QApplication.instance()
        for _ in range(10):
            app.processEvents()
        assert services.tag_service.get_tags(session.root, str(asset)) == []
