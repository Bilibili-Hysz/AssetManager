# AssetManager - Code Audit Report

> Audit date: 2026-06-08
> Scope: `AssetsManager/**/*.py`, performance hot paths, functional risks, and code quality checks
> Source task: `.opencode/plans/code-audit-task.md`

---

## 1. Diagnostics

| Command | Result |
|------|------|
| `python -m pytest` | 51 passed |
| `pyright` | 313 errors, 7 warnings |
| `python -m ruff check .` | Failed to run: `ruff` is not installed in the current Python environment |

Notes: most `pyright` errors are caused by unmodeled Qt/mixin dynamic attributes, but the output also exposes real risks such as Optional access, QObject lifetime ambiguity, and unclear return types. Reduce type noise before making pyright a CI gate.

---

## 2. Detailed Findings

### 性能-1 Canvas layout refresh marks all rows dirty

- **文件**: `AssetsManager/panels/file_list/_grid_widget.py:180`
- **严重度**: High
- **描述**: `update_layout()` runs `self._dirty |= set(range(item_count))` on each layout/resize, invalidating all item textures and causing repaint storms in large directories.
- **复现**: Open a directory with 10K+ files, then resize the window or trigger layout recalculation.
- **建议**: Only invalidate all rows when column count, thumbnail size, or theme changes. For ordinary resize, keep existing textures or invalidate only visible rows.

### 性能-2 Rubber-band release scans every model row

- **文件**: `AssetsManager/panels/file_list/_grid_widget.py:731`
- **严重度**: Medium
- **描述**: `mouseReleaseEvent()` checks intersection for every row via `range(self._model_rows)`, making drag-select release expensive in large directories.
- **复现**: Drag a selection rectangle in a directory containing 10K+ items, then release the mouse.
- **建议**: Use `_layout.visible_rows()` or compute the row/column range from rubber-band coordinates, then only test possible hits.

### 性能-3 Thumbnail loader creates QPixmap in worker threads

- **文件**: `AssetsManager/panels/file_list/_loader.py:215`
- **严重度**: High
- **描述**: `QPixmap.fromImage()` is executed in a worker thread and the pixmap is emitted across threads. Qt generally expects `QPixmap` to be created and used on the GUI thread, which can cause platform-specific crashes or rendering issues.
- **复现**: Load many thumbnails concurrently, especially on Windows or high-DPI systems.
- **建议**: Return `QImage` or raw bytes from workers, then convert to `QPixmap` on the main thread. Disk-cache reads should follow the same rule.

### 性能-4 Directory size tasks lack deduplication and cancellation

- **文件**: `AssetsManager/panels/file_list/_model.py:140`
- **严重度**: High
- **描述**: `_subtitle()` starts `_start_async_dir_size()` for each first-time directory display, without an in-flight set, cancellation flag, or generation token for directory/library switches.
- **复现**: Scroll quickly through a directory containing many subdirectories, or enter a deeply nested asset library.
- **建议**: Add `_pending_dir_sizes` so the same path is queued once. Increment a generation token on model reset/directory switch and discard stale task results.

### 性能-5 LAN zip downloads block the aiohttp event loop

- **文件**: `AssetsManager/lan/api.py:796`
- **严重度**: High
- **描述**: `handle_download()` and batch/share download handlers synchronously run `os.walk()` and `zipfile.ZipFile()` inside async handlers, blocking the entire LAN service while zipping large folders.
- **复现**: Download a large folder over LAN, then request `/api/files`, thumbnails, or WebSocket updates from another client.
- **建议**: Move zip creation to an executor/background task, use streaming zip responses, and enforce max size/concurrency limits.

### 功能-1 Background file operation calls QMessageBox off the GUI thread

- **文件**: `AssetsManager/panels/file_list/_actions.py:185`
- **严重度**: High
- **描述**: `_paste()` calls `QMessageBox.warning()` inside `_do_paste()`, which runs in a thread pool. Qt widgets must be created and used on the GUI thread.
- **复现**: Paste into a destination without permission, paste a locked file, or hit a path-length error.
- **建议**: Have the worker collect errors and emit them to the main thread. Show all user-facing dialogs from the main-thread completion handler.

### 功能-2 Background operation signal object may be collected too early

- **文件**: `AssetsManager/panels/file_list/_actions.py:481`
- **严重度**: High
- **描述**: `_run_in_background()` creates a local `_Sig()` object and only passes it into a `QRunnable`. Its lifetime depends on Python reference behavior, so the `done` signal can be lost.
- **复现**: Run copy/delete/undo operations and observe occasional missing UI refresh after task completion.
- **建议**: Store active operation/signal objects on `self._background_ops` and remove them when done, or use a persistent QObject worker.

### 功能-3 Thumbnail regeneration cannot be cancelled safely

- **文件**: `AssetsManager/panels/file_list/_loader.py:398`
- **严重度**: Medium
- **描述**: `regenerate_all()` performs a full `os.walk()` and keeps queuing bake tasks. `clear_queue()` and `stop()` cannot stop already running tasks or prevent writes after library switch/close.
- **复现**: Start thumbnail regeneration, then immediately close the library or switch to another library.
- **建议**: Add cancellation state, generation tokens, and cache/DB path ownership checks before writing results.

### 功能-4 TabbedDialog permanently connects global theme signal

- **文件**: `AssetsManager/core/tabbed_dialog.py:139`
- **严重度**: Medium
- **描述**: `showEvent()` lazily connects `bus().theme_changed`, but there is no disconnect in `closeEvent` or `destroyed`. Repeatedly opened dialogs can accumulate stale connections.
- **复现**: Open and close settings dialogs many times, then switch theme.
- **建议**: Disconnect in `closeEvent`/`destroyed`, or reuse a managed connection helper similar to `PanelContent._connect_bus`.

### 功能-5 AppSettings atomic write has no thread lock

- **文件**: `AssetsManager/core/settings.py:36`
- **严重度**: Medium
- **描述**: `AppSettings.save()` uses temp file plus `os.replace()`, but `_data`, `_dirty`, and save operations are not guarded by a lock. Concurrent callbacks can lose writes.
- **复现**: Trigger theme save, recent-library save, and sidebar config save close together.
- **建议**: Add an `RLock` around `load/get/set/save`, save from a copied `_data` snapshot, and consider a batched update API.

### 功能-6 LAN server stop may leave the event loop thread alive

- **文件**: `AssetsManager/lan/server.py:101`
- **严重度**: Medium
- **描述**: `stop()` submits `_shutdown()` and immediately joins the thread. It does not wait on the returned future, close the loop explicitly, or reliably surface shutdown exceptions.
- **复现**: Start LAN sharing, then close the app quickly while WebSocket/runner cleanup is active.
- **建议**: Store the `run_coroutine_threadsafe()` future, call `future.result(timeout=...)`, then close the loop and log cleanup failures.

### 功能-7 Theme system directly accesses sys._MEIPASS

- **文件**: `AssetsManager/core/themes.py:62`
- **严重度**: Low
- **描述**: `_themes_dir()` directly reads `sys._MEIPASS` when `sys.frozen` is true. This violates the task constraint that `_MEIPASS` access should be protected with `getattr`.
- **复现**: Run in a test or custom bundled environment where `sys.frozen` is set but `_MEIPASS` is absent.
- **建议**: Use `getattr(sys, "_MEIPASS", fallback_path)`.

### 质量-1 pyright cannot currently be used as a regression gate

- **文件**: `pyrightconfig.json` / multiple files
- **严重度**: Medium
- **描述**: `pyright` reports 313 errors, mostly around dynamic mixin attributes, Qt Optional returns, and missing QObject member typing. The noise hides real Optional and lifecycle bugs.
- **复现**: Run `pyright` in the project root.
- **建议**: Add Protocol/base-class typing for mixins, type `dock.create()` and panel attributes, and reduce the error count before enabling CI enforcement.

### 质量-2 Many swallowed exceptions reduce diagnosability

- **文件**: `AssetsManager/lan/api.py:333`
- **严重度**: Medium
- **描述**: The project has many `except Exception: pass` or empty `pass` blocks. LAN API, thumbnail cache, and config loading can silently hide important failures.
- **复现**: Trigger DB query failure, cache deletion failure, or URL parsing failure; user feedback and logs are often missing.
- **建议**: Catch specific expected exceptions. At minimum log `_log.debug` or `_log.exception` with path, operation, and context.

### 质量-3 User-visible UI text is not fully routed through i18n

- **文件**: `AssetsManager/panels/info.py:310`
- **严重度**: Low
- **描述**: Strings such as `Open`, `Copy Path`, `Notes`, and `Add Tag` are hard-coded, so language switching will not refresh all visible UI.
- **复现**: Switch language and inspect InfoPanel, Sidebar, and FileList context menus.
- **建议**: Route visible strings through `tr()` and connect panels to `language_changed` for fixed-text refresh.

### 质量-4 Dialog single-QSS design constraint is not consistently followed

- **文件**: `AssetsManager/core/settings_dialog.py:35`
- **严重度**: Low
- **描述**: Settings/dialog UI still applies child-level `setStyleSheet()` in several places, which conflicts with the task constraint that dialogs should set stylesheet only at the dialog level except for explicit exceptions.
- **复现**: Search `setStyleSheet(` in settings and sharing dialogs.
- **建议**: Move styling into `TabbedDialog._dialog_qss()`, object names, or dynamic properties to avoid missed theme refresh paths.

---

## 3. Summary Table

| 类别 | Critical | High | Medium | Low | 合计 |
|------|----------|------|--------|-----|------|
| 性能 | 0 | 4 | 1 | 0 | 5 |
| 功能 | 0 | 2 | 4 | 1 | 7 |
| 质量 | 0 | 0 | 2 | 2 | 4 |

---

## 4. Recommended Fix Order

1. Fix worker-thread `QPixmap` creation in `_loader.py`, worker-thread `QMessageBox` usage in `_actions.py`, and LAN zip blocking in `api.py` first. These are the highest crash or freeze risks.
2. Add cancellation/deduplication for directory-size and thumbnail-regeneration tasks to reduce large-directory pressure.
3. Reduce pyright noise and clean i18n/QSS constraint violations so future audits can find real regressions faster.
