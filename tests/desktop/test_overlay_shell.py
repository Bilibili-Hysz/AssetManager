"""V05: OverlayShell — shared shell contract for the floating overlays.

Covers the runtime refresh subscription lifecycle (theme / language /
ui-scale, disconnected on every dismissal path), the named scrim variants
(workspace alpha unification 175/170 -> 172; media = pure black @ 180), the
availableGeometry screen constraint, and focus entry/return.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget

from AssetsManager.core import signal_bus, themes, ui_scale
from AssetsManager.core.ui_scale import scaled_px
from AssetsManager.widgets.command_palette import CommandPalette
from AssetsManager.widgets.overlay_shell import OverlayShell
from AssetsManager.widgets.quick_look_overlay import QuickLookOverlay
from AssetsManager.widgets.quick_tagger_overlay import QuickTaggerOverlay


@pytest.fixture()
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def bus():
    return signal_bus.get()


class _FakeTagService:
    def get_all_tags(self, root: str):
        return ["tag1"]

    def get_tags_for_file(self, root: str, filepath: str):
        return []


def _sample_image(path) -> str:
    img = QImage(60, 40, QImage.Format.Format_RGB32)
    img.fill(QColor("#336699"))
    img.save(str(path))
    return str(path)


def _dismiss(overlay) -> None:
    """Teardown: belt-and-braces release, then destroy."""
    try:
        overlay.shutdown()
        overlay.close()
        overlay.deleteLater()
    except RuntimeError:
        # WA_DeleteOnClose may already have destroyed the C++ object.
        pass


@pytest.fixture()
def quick_look(tmp_path):
    p = _sample_image(tmp_path / "shell_ql.png")
    overlay = QuickLookOverlay([p], current_index=0)
    yield overlay
    _dismiss(overlay)


@pytest.fixture()
def quick_tagger():
    dlg = QuickTaggerOverlay(["/path/to/a.png"], "/root", tag_service=_FakeTagService())
    yield dlg
    _dismiss(dlg)


@pytest.fixture()
def palette():
    dlg = CommandPalette(None)
    yield dlg
    _dismiss(dlg)


# ── Scrim variants ────────────────────────────────────────────────


def test_scrim_variants_are_named_constants():
    assert OverlayShell.SCRIM_WORKSPACE == "workspace"
    assert OverlayShell.SCRIM_MEDIA == "media"
    assert OverlayShell.SCRIM_ALPHA_MEDIA == 180


def test_workspace_scrim_alpha_unified_across_overlays(qapp, quick_look, quick_tagger):
    """QuickLook (historical 175) and QuickTagger (historical 170) now resolve
    the same SCRIM_WORKSPACE alpha — the 3px drift is collapsed onto 172."""
    assert OverlayShell.SCRIM_ALPHA_WORKSPACE == 172
    for overlay in (quick_look, quick_tagger):
        assert overlay.scrim_variant == OverlayShell.SCRIM_WORKSPACE
        assert overlay._scrim_color().alpha() == 172


def test_workspace_scrim_paints_theme_base_at_unified_alpha(qapp, quick_look, quick_tagger):
    base = QColor(themes.color("base"))
    for overlay in (quick_look, quick_tagger):
        overlay.resize(1600, 900)
        img = QImage(1600, 900, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        painter = QPainter(img)
        overlay.render(painter, QPoint(0, 0))
        painter.end()
        # Sample far from the centered card so no card/shadow pixel leaks in.
        px = img.pixelColor(2, 450)
        assert px.alpha() == 172
        # Premultiplied round-tripping can be off by 1 per channel.
        assert all(abs(a - b) <= 1 for a, b in zip(
            (px.red(), px.green(), px.blue()), (base.red(), base.green(), base.blue()),
            strict=True,
        ))


def test_command_palette_has_no_scrim(qapp, palette):
    """The palette floats a shadowed card on a transparent window and never
    painted a dimming backdrop — preserved as scrim_variant = None."""
    assert palette.scrim_variant is None


def test_media_scrim_variant_is_pure_black_180(qapp):
    shell = OverlayShell(scrim_variant=OverlayShell.SCRIM_MEDIA)
    try:
        assert shell.scrim_variant == OverlayShell.SCRIM_MEDIA
        color = shell._scrim_color()
        assert color.alpha() == 180
        assert (color.red(), color.green(), color.blue()) == (0, 0, 0)
        # Real overlays set WA_TranslucentBackground; mirror that so the
        # render below composites over transparency like production does.
        shell.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        shell.resize(120, 90)
        img = QImage(120, 90, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        painter = QPainter(img)
        shell.render(painter, QPoint(0, 0))
        painter.end()
        px = img.pixelColor(5, 45)
        assert (px.red(), px.green(), px.blue(), px.alpha()) == (0, 0, 0, 180)
    finally:
        _dismiss(shell)


def test_scrim_none_shell_paints_no_backdrop(qapp):
    """scrim_variant=None 的 paintEvent 契约：透明窗口零绘制。

    CommandPalette 依赖"无遮罩背景"（浮动卡片 + 全透明窗口）。属性级
    断言（scrim_variant is None）挡不住 paintEvent 丢掉 early-return 的
    回归——paintEvent 一旦无条件 fillRect，透明窗口就会整面 172 alpha
    的 workspace 遮罩。此处用与 media 变体相同的渲染法锁定"零绘制"：
    采样点保持完全透明（alpha 0）。
    """
    shell = OverlayShell()
    shell.scrim_variant = None
    try:
        assert shell.scrim_variant is None
        # Real overlays set WA_TranslucentBackground; mirror that so the
        # render below composites over transparency like production does.
        shell.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        shell.resize(120, 90)
        img = QImage(120, 90, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        painter = QPainter(img)
        shell.render(painter, QPoint(0, 0))
        painter.end()
        px = img.pixelColor(5, 45)
        assert px.alpha() == 0, (
            "scrim_variant=None must not paint any backdrop — the palette "
            "floats its card on a fully transparent window")
    finally:
        _dismiss(shell)


# ── Refresh contract (theme / language / ui-scale) ────────────────


def _assert_refresh_contract(bus, overlay, monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(overlay, "refresh_overlay_chrome", lambda: calls.append("hit"))
    bus.theme_changed.emit("dark")
    bus.language_changed.emit("ja")
    bus.ui_scale_changed.emit(1.5)
    assert calls == ["hit", "hit", "hit"]


@pytest.mark.parametrize("fixture_name", ["palette", "quick_look", "quick_tagger"])
def test_refresh_signals_drive_chrome_hook(qapp, bus, request, fixture_name, monkeypatch):
    _assert_refresh_contract(bus, request.getfixturevalue(fixture_name), monkeypatch)


@pytest.mark.parametrize("fixture_name", ["palette", "quick_look", "quick_tagger"])
def test_refresh_bus_disconnects_after_close(qapp, bus, request, fixture_name, monkeypatch):
    overlay = request.getfixturevalue(fixture_name)
    overlay.show()
    qapp.processEvents()
    calls: list[int] = []
    monkeypatch.setattr(overlay, "refresh_overlay_chrome", lambda: calls.append(1))
    bus.theme_changed.emit("x")
    assert calls == [1]
    overlay.close()
    qapp.processEvents()
    bus.theme_changed.emit("y")
    bus.language_changed.emit("zh")
    bus.ui_scale_changed.emit(1.0)
    assert calls == [1], "closed overlay must not receive further refresh calls"


def test_shell_disconnects_via_shutdown_alias(qapp, bus, monkeypatch):
    shell = OverlayShell()
    try:
        calls: list[int] = []
        monkeypatch.setattr(shell, "refresh_overlay_chrome", lambda: calls.append(1))
        bus.theme_changed.emit("a")
        assert calls == [1]
        shell.shutdown()
        bus.theme_changed.emit("b")
        assert calls == [1]
    finally:
        shell.deleteLater()


@pytest.mark.parametrize("finish", ["accept", "reject"])
def test_refresh_bus_disconnects_via_done_paths(qapp, bus, request, finish, monkeypatch):
    """accept()/reject() funnel through QDialog.done() (verified against Qt
    semantics) without a closeEvent, so the release must hook done() too —
    the palette closes via accept()/reject(), not close()."""
    overlay = request.getfixturevalue("palette")
    overlay.show()
    qapp.processEvents()
    calls: list[int] = []
    monkeypatch.setattr(overlay, "refresh_overlay_chrome", lambda: calls.append(1))
    bus.theme_changed.emit("x")
    assert calls == [1]
    getattr(overlay, finish)()
    qapp.processEvents()
    bus.theme_changed.emit("y")
    bus.language_changed.emit("zh")
    bus.ui_scale_changed.emit(1.0)
    assert calls == [1], f"{finish}() must disconnect the refresh bus via done()"


def test_command_palette_rescales_card_width_on_scale_change(qapp, bus, palette, monkeypatch):
    assert palette._card.width() == scaled_px(560)
    monkeypatch.setattr(ui_scale, "get_ui_scale", lambda: 1.5)
    try:
        bus.ui_scale_changed.emit(1.5)
        qapp.processEvents()
        assert palette._card.minimumWidth() == scaled_px(560)  # 560 * 1.5 = 840
        assert palette._card.width() == scaled_px(560)
    finally:
        monkeypatch.setattr(ui_scale, "get_ui_scale", lambda: 1.0)


def test_quick_tagger_rescales_card_width_on_scale_change(qapp, bus, quick_tagger, monkeypatch):
    assert quick_tagger._card.width() == scaled_px(440)
    monkeypatch.setattr(ui_scale, "get_ui_scale", lambda: 1.5)
    try:
        bus.ui_scale_changed.emit(1.5)
        qapp.processEvents()
        assert quick_tagger._card.minimumWidth() == scaled_px(440)  # 440 * 1.5 = 660
        assert quick_tagger._card.width() == scaled_px(440)
    finally:
        monkeypatch.setattr(ui_scale, "get_ui_scale", lambda: 1.0)


# ── Stage E: layout margins/spacing join the scale refresh ────────


def test_command_palette_rescales_layout_margins_on_scale_change(
    qapp, bus, palette, monkeypatch
):
    """Stage E: the palette's root shadow margin, search-row margins/spacing,
    and footer margins/spacing re-derive from ui_scale (previously frozen at
    the construction-time scale)."""
    assert palette._root_layout.contentsMargins().left() == scaled_px(16)
    monkeypatch.setattr(ui_scale, "get_ui_scale", lambda: 1.5)
    try:
        bus.ui_scale_changed.emit(1.5)
        qapp.processEvents()
        # 16 * 1.5 = 24
        assert palette._root_layout.contentsMargins().left() == scaled_px(16)
        assert palette._search_layout.contentsMargins().top() == scaled_px(10)  # 15
        assert palette._search_layout.spacing() == scaled_px(10)  # 15
        assert palette._footer_layout.contentsMargins().left() == scaled_px(14)  # 21
        assert palette._footer_layout.spacing() == scaled_px(12)  # 18
    finally:
        monkeypatch.setattr(ui_scale, "get_ui_scale", lambda: 1.0)


def test_quick_look_rescales_bar_margins_on_scale_change(qapp, bus, quick_look, monkeypatch):
    """Stage E: QuickLook header/footer bar margins + spacing re-derive."""
    assert quick_look._header_layout.contentsMargins().left() == scaled_px(16)
    monkeypatch.setattr(ui_scale, "get_ui_scale", lambda: 1.5)
    try:
        bus.ui_scale_changed.emit(1.5)
        qapp.processEvents()
        assert quick_look._header_layout.contentsMargins().left() == scaled_px(16)  # 24
        assert quick_look._header_layout.spacing() == scaled_px(10)  # 15
        assert quick_look._footer_layout.contentsMargins().bottom() == scaled_px(8)  # 12
        assert quick_look._footer_layout.spacing() == scaled_px(8)  # 12
    finally:
        monkeypatch.setattr(ui_scale, "get_ui_scale", lambda: 1.0)


def test_quick_tagger_rescales_spacing_on_scale_change(qapp, bus, quick_tagger, monkeypatch):
    """Stage E: QuickTagger card spacing + header/tag-row spacing re-derive."""
    assert quick_tagger._card_layout.spacing() == scaled_px(10)
    monkeypatch.setattr(ui_scale, "get_ui_scale", lambda: 1.5)
    try:
        bus.ui_scale_changed.emit(1.5)
        qapp.processEvents()
        assert quick_tagger._card_layout.spacing() == scaled_px(10)  # 15
        assert quick_tagger._header_layout.spacing() == scaled_px(8)  # 12
        assert quick_tagger._tags_layout.spacing() == scaled_px(4)  # 6
    finally:
        monkeypatch.setattr(ui_scale, "get_ui_scale", lambda: 1.0)


# ── Screen constraint ─────────────────────────────────────────────


def test_constrain_pulls_offscreen_geometry_back_inside(qapp, palette):
    palette.resize(400, 300)
    palette.move(-2000, -2000)
    avail = palette._constrain_to_screen()
    assert avail.isValid()
    geo = palette.geometry()
    assert geo.left() >= avail.left()
    assert geo.top() >= avail.top()
    assert geo.right() <= avail.right()
    assert geo.bottom() <= avail.bottom()


def test_constrain_oversized_widget_anchors_to_screen_origin(qapp):
    shell = OverlayShell()
    try:
        shell.resize(5000, 5000)
        shell.move(-3000, -3000)
        avail = shell._constrain_to_screen()
        assert shell.geometry().topLeft() == avail.topLeft()
    finally:
        _dismiss(shell)


def test_quick_tagger_without_parent_fills_available_geometry(qapp, quick_tagger):
    quick_tagger.show()
    qapp.processEvents()
    avail = QApplication.primaryScreen().availableGeometry()
    assert quick_tagger.geometry().size() == avail.size()
    assert avail.contains(quick_tagger.geometry())


# ── Focus entry / return ──────────────────────────────────────────


def test_command_palette_focuses_search_input_on_show(qapp, palette):
    palette.show()
    qapp.processEvents()
    assert QApplication.focusWidget() is palette._input


def test_overlay_focus_returns_to_parent_window_widget(qapp):
    parent = QWidget()
    parent.resize(800, 600)
    edit = QLineEdit(parent)
    parent.show()
    edit.setFocus()
    qapp.processEvents()
    dlg = QuickTaggerOverlay(
        ["/path/to/a.png"], "/root", tag_service=_FakeTagService(), parent=parent
    )
    try:
        dlg.show()
        qapp.processEvents()
        dlg.close()
        qapp.processEvents()
        assert QApplication.focusWidget() is edit
    finally:
        _dismiss(dlg)
        parent.close()
        parent.deleteLater()


def test_focus_target_hook_defaults_to_none():
    assert OverlayShell._focus_target(OverlayShell.__new__(OverlayShell)) is None


def test_focus_return_survives_destroyed_target_widget(qapp):
    """_return_focus 的 RuntimeError 分支：_focus_return_to 记录的控件在
    归还发生前 C++ 对象已被销毁（teardown 竞态：宿主窗口先于 overlay
    关闭）时，dismissal 不得抛 RuntimeError 崩溃——护栏吞掉异常即可，
    不要求归还成功。"""
    from PySide6.QtCore import QCoreApplication, QEvent

    parent = QWidget()
    edit = QLineEdit(parent)
    parent.show()
    edit.setFocus()
    qapp.processEvents()
    dlg = QuickTaggerOverlay(
        ["/path/to/a.png"], "/root", tag_service=_FakeTagService(), parent=parent
    )
    try:
        dlg.show()
        qapp.processEvents()
        assert dlg._focus_return_to is edit

        # Destroy the recorded target's C++ object while the overlay still
        # holds the Python reference (the exact teardown-race shape).
        edit.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

        # WA_DeleteOnClose destroys the overlay's own C++ object during
        # close(), so nothing beyond "did not raise" can be asserted here.
        dlg.close()  # must not raise RuntimeError
        qapp.processEvents()
    finally:
        _dismiss(dlg)
        parent.close()
        parent.deleteLater()
        qapp.processEvents()
