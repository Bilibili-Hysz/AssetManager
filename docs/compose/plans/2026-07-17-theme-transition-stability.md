# Theme Transition Stability Implementation Plan
> **ARCHIVED (2026-08-27)**: 已执行完毕或被后续批次取代,仅追溯用;导航与现行参考见 docs/compose/README.md。

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make rapid theme switches deterministic by using one animation owner, cancelling superseded transitions, and honoring reduce-motion settings.

**Architecture:** `MainWindow._on_theme_refresh()` delegates to `WindowCoordinator.on_theme_refresh()`. The coordinator owns fade animations and a monotonic generation; each request stops active animations, restores opacity, and only the current fade-out callback may apply the theme and create fade-in. Reduce-motion uses the same apply path immediately.

**Tech Stack:** Python 3.14, PySide6, pytest.

## Global Constraints

- Do not change theme files, colors, layouts, signal emission, or panel subscriptions.
- Keep normal theme refresh work identical: stylesheet, window/menu/status/workspace/background/file-list refresh.
- `WindowCoordinator` is the sole window-level transition owner.
- Stale callbacks must not apply theme state or start a fade-in.
- `reduce_motion=True` must not construct animations and must restore opacity to `1.0`.

---

### Task 1: Centralize And Guard Theme Transitions

**Files:**
- Modify: `AssetsManager/window.py:492-527`
- Modify: `AssetsManager/window_coordinator.py:58-89`
- Create: `tests/unit/test_window_coordinator.py`

**Interfaces:**
- Consumes: `MainWindow._coordinator`, `AppSettings.instance().get("reduce_motion", False)`, existing theme application collaborators.
- Produces: `WindowCoordinator.on_theme_refresh()` as the sole transition entry point.

- [ ] **Step 1: Write RED tests**

Add tests with fake window/animations that prove:

```python
def test_main_window_theme_refresh_delegates_to_coordinator():
    calls = []
    class _Coordinator:
        def on_theme_refresh(self): calls.append("refresh")
    MainWindow._on_theme_refresh(type("_Window", (), {"_coordinator": _Coordinator()})())
    assert calls == ["refresh"]

def test_reduce_motion_applies_without_constructing_animation(monkeypatch):
    # Settings returns True; patched QPropertyAnimation raises if constructed.
    # Assert one shared apply and window opacity 1.0.
    ...

def test_stale_fade_out_callback_cannot_start_fade_in(monkeypatch):
    # Capture fake animation callbacks, refresh twice, emit callback one then two.
    # Assert callback one does nothing; callback two applies once and starts one fade-in.
    ...
```

- [ ] **Step 2: Run RED tests**

Run:

```powershell
python -m pytest tests/unit/test_window_coordinator.py -q
```

Expected: failure because MainWindow owns local animation and coordinator has neither reduce-motion nor generation guards.

- [ ] **Step 3: Implement minimal lifecycle ownership**

Replace `MainWindow._on_theme_refresh()` with:

```python
def _on_theme_refresh(self):
    self._coordinator.on_theme_refresh()
```

Remove MainWindow's local transition method. In `WindowCoordinator`, add `_theme_generation`, `_stop_theme_animations()`, and `_apply_theme()`. `on_theme_refresh()` increments generation, stops animations, branches to immediate `_apply_theme()` for reduce-motion, otherwise starts fade-out. Its callback compares the captured generation before applying theme or creating/storing fade-in.

- [ ] **Step 4: Run GREEN and regressions**

Run:

```powershell
python -m pytest tests/unit/test_window_coordinator.py tests/unit/test_window_session_switching.py -q
python -m pytest tests/desktop/test_file_list_shim.py tests/desktop/test_info_async_identity.py -q
python -m ruff check AssetsManager/window.py AssetsManager/window_coordinator.py tests/unit/test_window_coordinator.py
```

Expected: all tests and Ruff pass.

- [ ] **Step 5: Commit**

```powershell
git add AssetsManager/window.py AssetsManager/window_coordinator.py tests/unit/test_window_coordinator.py docs/compose/plans/2026-07-17-theme-transition-stability.md
git commit -m "fix: stabilize theme transition lifecycle"
```

