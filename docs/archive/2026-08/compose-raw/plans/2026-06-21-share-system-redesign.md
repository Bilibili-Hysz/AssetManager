# Share System Dialog Redesign — Implementation Plan
> **ARCHIVED (2026-08-27)**: 已执行完毕或被后续批次取代,仅追溯用;导航与现行参考见 docs/compose/README.md。

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the SharingSettingsDialog with dashboard card layout, real-time refresh, interaction feedback, and progressive disclosure settings.

**Architecture:** Refactor the existing 1553-line dialog file in-place. Add toast notification system as a reusable widget. All changes in PySide6 Python.

**Tech Stack:** Python 3.14, PySide6

---

### Task 1: Toast Notification Widget

**Covers:** S3

**Files:**
- Create: `AssetsManager/widgets/toast.py`

- [ ] **Step 1: Create toast widget**

```python
"""Toast notification widget — bottom-center overlay."""
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtWidgets import QWidget, QLabel, QHBoxLayout, QGraphicsOpacityEffect
from AssetsManager.core import themes
from AssetsManager.core.ui_scale import scaled_px, scaled_pt


class Toast(QWidget):
    """Auto-dismissing notification toast."""

    _instance = None
    _queue: list = []

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._setup_ui()
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity_effect)

    def _setup_ui(self):
        t = themes.get()
        self._label = QLabel()
        self._label.setStyleSheet(
            f"color: {t['body']}; font-size: {scaled_pt(12)}px; "
            f"padding: {scaled_px(10)}px {scaled_px(16)}px; "
            f"background: {t['panel']}; border: 1px solid {t['border']}; "
            f"border-radius: {scaled_px(8)}px;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label)

    def show_toast(self, message: str, duration: int = 3000, level: str = "info"):
        """Show a toast notification. level: 'info', 'success', 'error'"""
        t = themes.get()
        colors = {"info": t['accent'], "success": "#22c55e", "error": "#ef4444"}
        color = colors.get(level, t['accent'])
        self._label.setStyleSheet(
            f"color: {t['body']}; font-size: {scaled_pt(12)}px; "
            f"padding: {scaled_px(10)}px {scaled_px(16)}px; "
            f"background: {t['panel']}; border-left: 3px solid {color}; "
            f"border-radius: {scaled_px(8)}px;")
        self._label.setText(message)
        self.adjustSize()
        self._position()
        self._opacity_effect.setOpacity(1.0)
        self.show()
        QTimer.singleShot(duration, self._fade_out)

    def _position(self):
        parent = self.parent()
        if parent:
            pw, ph = parent.width(), parent.height()
            x = (pw - self.width()) // 2
            y = ph - self.height() - scaled_px(80)
            self.move(x, y)

    def _fade_out(self):
        anim = QPropertyAnimation(self._opacity_effect, b"opacity")
        anim.setDuration(300)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(self.hide)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    @classmethod
    def instance(cls, parent=None):
        if cls._instance is None or cls._instance.parent() != parent:
            cls._instance = cls(parent)
        return cls._instance
```

- [ ] **Step 2: Run quality gate**

Run: `python -m ruff check . --exclude ".Cython&Noikta" && python -m pyright && python -m pytest -q`

---

### Task 2: Dashboard Card Layout for Overview Tab

**Covers:** S1

**Files:**
- Modify: `AssetsManager/dialogs/sharing_settings_dialog.py`

- [ ] **Step 1: Create `_make_card` helper**

Add to `SharingSettingsDialog`:

```python
def _make_card(self, title: str, icon: str = "") -> tuple[QFrame, QVBoxLayout]:
    """Create a dashboard card frame with title."""
    t = _t()
    card = QFrame()
    card.setStyleSheet(
        f"QFrame {{ background: {t['panel']}; border: 1px solid {t['border']}; "
        f"border-radius: {scaled_px(10)}px; }}")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(scaled_px(14), scaled_px(12), scaled_px(14), scaled_px(12))
    layout.setSpacing(scaled_px(8))
    header = QLabel(f"{icon}  {title}" if icon else title)
    header.setStyleSheet(f"font-weight: 600; font-size: {scaled_pt(12)}px; color: {t['heading']};")
    layout.addWidget(header)
    return card, layout
```

- [ ] **Step 2: Refactor `_setup_overview_tab` to use grid layout**

Replace the current vertical layout with a 2-column grid:

```python
def _setup_overview_tab(self, parent):
    t = _t()
    layout = QVBoxLayout(parent)
    layout.setContentsMargins(scaled_px(12), scaled_px(12), scaled_px(12), scaled_px(12))
    layout.setSpacing(scaled_px(12))

    # Row 1: Status + Online Users
    row1 = QHBoxLayout()
    row1.setSpacing(scaled_px(12))
    status_card, status_lay = self._make_card(tr("sharing.overview.server_status"), "●")
    # ... build status content inside status_lay ...
    row1.addWidget(status_card, 1)

    users_card, users_lay = self._make_card(tr("sharing.overview.online_users"), "👥")
    # ... build users content inside users_lay ...
    row1.addWidget(users_card, 1)
    layout.addLayout(row1)

    # Row 2: Traffic + Quick Share
    row2 = QHBoxLayout()
    row2.setSpacing(scaled_px(12))
    traffic_card, traffic_lay = self._make_card(tr("sharing.overview.traffic"), "📊")
    # ... build traffic content ...
    row2.addWidget(traffic_card, 1)

    quick_card, quick_lay = self._make_card("", "🔗")
    # ... build quick share buttons ...
    row2.addWidget(quick_card, 1)
    layout.addLayout(row2)

    # Activity (full width)
    activity_card, activity_lay = self._make_card(tr("sharing.overview.recent_activity"), "📋")
    # ... build activity list ...
    layout.addWidget(activity_card)

    # Tunnel (full width, collapsible)
    tunnel_card, tunnel_lay = self._make_card(tr("sharing.overview.tunnel_status"), "🌐")
    # ... build tunnel content ...
    layout.addWidget(tunnel_card)

    layout.addStretch()
```

- [ ] **Step 3: Run quality gate**

---

### Task 3: Cross-Tab Data Refresh

**Covers:** S2, S5

**Files:**
- Modify: `AssetsManager/dialogs/sharing_settings_dialog.py`

- [ ] **Step 1: Add `data_changed` signal**

```python
class SharingSettingsDialog(TabbedDialog):
    settings_changed = Signal()
    _data_changed = Signal()  # internal: triggers refresh on all tabs
```

- [ ] **Step 2: Connect signal to refresh methods**

In `__init__`:
```python
self._data_changed.connect(self._refresh_all_tabs)
```

Add refresh method:
```python
def _refresh_all_tabs(self):
    """Refresh all tabs when data changes."""
    if self._server and self._server.is_running():
        self._load_share_links()
        self._load_activity()
        self._load_online_users()
```

- [ ] **Step 3: Emit signal after write operations**

After creating share link, deleting share, toggling server, etc.:
```python
self._data_changed.emit()
```

- [ ] **Step 4: Run quality gate**

---

### Task 4: Interaction Feedback (Loading States + Toast)

**Covers:** S3

**Files:**
- Modify: `AssetsManager/dialogs/sharing_settings_dialog.py`

- [ ] **Step 1: Add toast integration**

Import and use toast for all operations:
```python
from AssetsManager.widgets.toast import Toast

# After successful operation:
Toast.instance(self).show_toast(tr("sharing.toast.success"), level="success")

# After failed operation:
Toast.instance(self).show_toast(tr("sharing.toast.error"), level="error")
```

- [ ] **Step 2: Add loading state to toggle button**

```python
def _on_toggle_server(self):
    self._toggle_btn.setEnabled(False)
    self._toggle_btn.setText(tr("sharing.btn_connecting"))
    # ... do work ...
    # On success/failure, re-enable and update text
```

- [ ] **Step 3: Add i18n keys**

Add to en.json, zh.json, ja.json:
- `sharing.toast.share_created` — "Share link created!"
- `sharing.toast.share_deleted` — "Share link deleted"
- `sharing.toast.server_started` — "Server started"
- `sharing.toast.server_stopped` — "Server stopped"
- `sharing.toast.copied` — "Copied to clipboard"
- `sharing.toast.error` — "Operation failed"

- [ ] **Step 4: Run quality gate**

---

### Task 5: Settings Tab — Collapsible Panels

**Covers:** S4

**Files:**
- Modify: `AssetsManager/dialogs/sharing_settings_dialog.py`

- [ ] **Step 1: Create collapsible panel widget**

```python
class CollapsiblePanel(QWidget):
    def __init__(self, title: str, description: str = "", parent=None):
        super().__init__(parent)
        self._expanded = False
        # ... header with toggle button + title + description
        # ... content area that shows/hides
```

- [ ] **Step 2: Refactor `_setup_settings_tab` to use collapsible panels**

Replace the current flat layout with:
```python
def _setup_settings_tab(self, parent):
    layout = QVBoxLayout(parent)
    layout.addWidget(CollapsiblePanel(tr("sharing.settings.network"), ...))
    layout.addWidget(CollapsiblePanel(tr("sharing.settings.security"), ...))
    layout.addWidget(CollapsiblePanel(tr("sharing.settings.branding"), ..., expanded=False))
    layout.addWidget(CollapsiblePanel(tr("sharing.settings.advanced"), ..., expanded=False))
    layout.addWidget(CollapsiblePanel(tr("sharing.settings.tunnel"), ..., expanded=False))
    layout.addStretch()
```

- [ ] **Step 3: Run quality gate**

---

### Task 6: Final Integration + Testing

**Covers:** S1-S5

- [ ] **Step 1: Run full quality gate**

Run: `python -m ruff check . --exclude ".Cython&Noikta" && python -m pyright && python -m pytest -q`

- [ ] **Step 2: Verify all flows manually**

- [ ] Start server → all cards update
- [ ] Create share link → list auto-refreshes + toast
- [ ] Delete share link → fade-out + toast
- [ ] Start tunnel → progress → QR updates
- [ ] Settings: collapsible panels work
- [ ] Scroll: all tabs scrollable
- [ ] Theme change: all elements update

