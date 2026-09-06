"""OverlayShell — shared chrome shell for frameless floating overlays (V05).

CommandPalette, QuickLookOverlay, and QuickTaggerOverlay used to be
free-standing QDialogs that each hand-rolled their dimming backdrop, ignored
runtime theme/language/ui-scale changes, and repeated their own positioning
rules.  This shell centralizes the *chrome* only — content areas stay owned
by the subclasses:

  - Named scrim variants: ``SCRIM_WORKSPACE`` (theme ``base`` + alpha 172)
    and ``SCRIM_MEDIA`` (pure black + alpha 180).  172 unifies the historical
    175 (QuickLook) / 170 (QuickTagger) drift — the 3px spread was
    unintentional, so collapsing both onto one value is an expected
    micro-change under V05; 172 is the 172.5 midpoint floored, keeping
    within 3 of each historical value.  ``SCRIM_MEDIA`` is the named export
    for dedicated media scrims: panels/image_viewer.py keeps painting its
    own neutral dark backdrop but documents it as this variant.  A subclass
    that paints no backdrop at all (CommandPalette floats a shadowed card on
    a fully transparent window) sets ``scrim_variant = None``.

  - Refresh contract: the process signal bus (theme_changed /
    language_changed / ui_scale_changed) is subscribed at construction,
    mirroring the ``PanelContent._connect_bus`` / ``shutdown`` pattern in
    panels/base.py, but overlays disconnect on their own dismissal paths —
    ``closeEvent`` and ``done()`` (accept()/reject()/close() all funnel
    through one of the two) — instead of a panel-style shutdown hook.  A
    ``shutdown()`` alias is still provided for symmetry with panels.
    Subclasses retranslate / restyle / rescale their content in
    ``refresh_overlay_chrome()``.

  - Screen constraint: ``_constrain_to_screen(widget=None)`` clamps a
    top-level overlay back inside the ``availableGeometry`` of the screen it
    is on; subclasses keep their own anchor/centering math and call this
    afterwards.

  - Focus entry/return: ``_focus_target()`` names the widget to focus when
    the overlay opens (None preserves the subclass's previous default-focus
    behavior); the last widget focused outside the overlay before it was
    shown is handed focus back on dismissal.

Note on motion: none of the three migrated overlays has an entry/exit
animation today (verified for V05), so there is no reduce_motion guard to
wire yet; any future fade must consult ``StyleKit.reduce_motion()`` like
TabbedDialog does.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QGuiApplication, QPaintEvent, QPainter
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from AssetsManager.core import themes


class OverlayShell(QDialog):
    """Base class for the frameless floating overlays (command palette,
    QuickLook, QuickTagger).  Provides the shared backdrop, runtime-refresh
    wiring, screen constraint, and focus entry/return; subclasses own their
    content and implement :meth:`refresh_overlay_chrome`.
    """

    # ── Scrim semantics (named backdrop variants) ─────────────────
    SCRIM_WORKSPACE = "workspace"
    SCRIM_MEDIA = "media"

    # Single workspace scrim alpha for all floating overlays.  Historically
    # QuickLookOverlay painted base@175 and QuickTaggerOverlay base@170; the
    # 3px spread was drift, not intent.  172 (the 172.5 midpoint floored)
    # unifies them within 3 of each prior value — an expected V05 micro-change.
    SCRIM_ALPHA_WORKSPACE = 172
    # Dedicated media-scrim alpha (pure black) — matches the neutral dark
    # backdrop panels/image_viewer.py paints for its full-size image view.
    SCRIM_ALPHA_MEDIA = 180

    #: Which backdrop this overlay paints.  ``None`` = no dimming layer at
    #: all (transparent window; used by CommandPalette, which never had a
    #: scrim).  Overridable per class or per instance via the ctor kwarg.
    scrim_variant: str | None = SCRIM_WORKSPACE

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        scrim_variant: str | None = None,
    ) -> None:
        super().__init__(parent)
        if scrim_variant is not None:
            self.scrim_variant = scrim_variant
        self._bus_connections: list[tuple[Any, Any]] = []
        self._focus_return_to: QWidget | None = None
        self._overlay_released = False
        self._connect_overlay_bus()

    # ── Runtime refresh contract (mirrors panels/base.py) ─────────

    def _connect_bus(self, signal: Any, slot: Any) -> None:
        """Connect a bus signal and track it for automatic disconnection."""
        signal.connect(slot)
        self._bus_connections.append((signal, slot))

    def _connect_overlay_bus(self) -> None:
        """Subscribe theme/language/ui-scale changes for the overlay lifetime."""
        from AssetsManager.core.signal_bus import get as bus

        b = bus()
        self._connect_bus(b.theme_changed, self._handle_theme_changed)
        self._connect_bus(b.language_changed, self._handle_language_changed)
        self._connect_bus(b.ui_scale_changed, self._handle_ui_scale_changed)

    def _disconnect_bus(self) -> None:
        for signal, slot in self._bus_connections:
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._bus_connections.clear()

    def _handle_theme_changed(self, name: str = "") -> None:
        self.refresh_overlay_chrome()

    def _handle_language_changed(self, lang: str = "") -> None:
        self.refresh_overlay_chrome()

    def _handle_ui_scale_changed(self, scale: float = 1.0) -> None:
        self.refresh_overlay_chrome()

    def refresh_overlay_chrome(self) -> None:
        """Shell hook: retranslate / restyle / rescale the overlay's content.

        Called on every theme, language, or UI-scale bus signal.  The shell
        owns no content, so the base implementation is a no-op; subclasses
        re-derive their QSS, translated labels, and scaled metrics here
        (full per-subclass scaling re-layout may land in stage E).
        """

    # ── Scrim painting ────────────────────────────────────────────

    def _scrim_color(self) -> QColor:
        """Resolve the named scrim variant into a concrete backdrop color."""
        if self.scrim_variant == OverlayShell.SCRIM_MEDIA:
            return QColor(0, 0, 0, OverlayShell.SCRIM_ALPHA_MEDIA)
        base_color = themes.color("base")
        scrim = QColor(base_color) if base_color else QColor(0, 0, 0)
        scrim.setAlpha(OverlayShell.SCRIM_ALPHA_WORKSPACE)
        return scrim

    def paintEvent(self, event: QPaintEvent) -> None:
        if self.scrim_variant is None:
            return  # transparent window: the overlay paints no backdrop
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._scrim_color())

    # ── Screen constraint ─────────────────────────────────────────

    def _available_geometry_for(self, widget: QWidget) -> QRect:
        """Available geometry of the screen the widget currently sits on."""
        screen = widget.screen() if widget is not None else None
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        return screen.availableGeometry() if screen is not None else QRect()

    def _constrain_to_screen(self, widget: QWidget | None = None) -> QRect:
        """Clamp ``widget`` (default: this overlay) inside the taskbar-free
        ``availableGeometry`` of its screen.  Anchoring/centering stays the
        subclass's job; this only pulls an out-of-bounds position back in.
        Oversized widgets anchor to the screen's top-left.  Returns the
        available rect that was applied.
        """
        target = widget if widget is not None else self
        avail = self._available_geometry_for(target)
        if not avail.isValid():
            return avail
        # A parented QDialog is still a top-level window: geometry()/move()
        # are in global screen coordinates, so clamping applies to it the
        # same as to a parent-less overlay.
        geo = target.geometry()
        if geo.width() >= avail.width():
            x = avail.left()
        else:
            x = max(avail.left(), min(geo.left(), avail.right() - geo.width() + 1))
        if geo.height() >= avail.height():
            y = avail.top()
        else:
            y = max(avail.top(), min(geo.top(), avail.bottom() - geo.height() + 1))
        if (x, y) != (geo.left(), geo.top()):
            target.move(x, y)
        return avail

    # ── Positioning / focus hooks ─────────────────────────────────

    def _position_overlay(self) -> None:
        """Hook: place the overlay before it is shown (anchor choice is the
        subclass's).  Default: keep the current geometry, constrained."""

    def _focus_target(self) -> QWidget | None:
        """Widget to focus on open (None = keep the dialog default behavior)."""
        return None

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._focus_return_to is None:
            fw = QApplication.focusWidget()
            if fw is not None and not self.isAncestorOf(fw):
                self._focus_return_to = fw
        self._position_overlay()
        self._constrain_to_screen()
        target = self._focus_target()
        if target is not None:
            target.setFocus()

    # ── Dismissal: disconnect + focus return ──────────────────────

    def closeEvent(self, event) -> None:
        self._release_overlay()
        super().closeEvent(event)

    def done(self, result: int) -> None:
        # accept()/reject() hide modal dialogs through done() without a
        # closeEvent, so the release must hook both dismissal paths
        # (same reason TabbedDialog overrides done()).
        self._release_overlay()
        super().done(result)

    def shutdown(self) -> None:
        """Panel-style teardown alias; mirrors PanelContent.shutdown."""
        self._release_overlay()

    def _release_overlay(self) -> None:
        """Disconnect the refresh bus and hand focus back to the parent
        window.  Idempotent: close(), accept()/reject()/done() and explicit
        shutdown() may all funnel through here."""
        self._disconnect_bus()
        self._return_focus()

    def _return_focus(self) -> None:
        if self._overlay_released:
            return
        self._overlay_released = True
        try:
            target = self._focus_return_to
            if target is not None:
                win = target.window()
                if win is not None and win.isVisible():
                    win.activateWindow()
                    target.setFocus()
                    return
            parent = self.parentWidget()
            win = parent.window() if parent is not None else None
            if win is not None and win.isVisible():
                win.activateWindow()
        except RuntimeError:
            # Underlying C++ widget already destroyed during teardown.
            pass
