# AssetManager - Final Audit Review

> Review date: 2026-06-08
> Inputs: `code-audit-report.md`, `code-audit-resolution.md`
> Scope: remaining audit items, regression verification, and tool diagnostics

---

## 1. Changes Applied In This Pass

### Fixed

| ID | File | Change |
|----|------|--------|
| Q-extra | `AssetsManager/panels/file_list/_delegate.py` | Replaced hard-coded `QColor("white") / QColor("black")` badge text selection with theme-token selection using `on_accent` and `base`, choosing the higher contrast color via `contrast_ratio`. |
| Q-extra | `AssetsManager/panels/file_list/_delegate.py` | Replaced direct `parent().viewport().update()` with defensive dynamic lookup to avoid Qt parent typing/runtime assumptions. |
| Q-2 partial | `AssetsManager/lan/api.py` | Added `_log.exception(...)` for key swallowed database/cache failures in `handle_home()` and `handle_projects()`. |
| Type cleanup | `AssetsManager/lan/api.py` | Removed unresolved forward annotation from `_get_lan()`, made `_format_size()` use a float local value, and replaced direct `Image.LANCZOS` with Pillow `Image.Resampling`-compatible lookup. |
| Type cleanup | `AssetsManager/lan/auth.py` | Updated share-link helper annotations to accept `None` explicitly for optional arguments. |
| Regression fix | `AssetsManager/core/settings.py` | Added lazy `_get_lock()` so `AppSettings` remains thread-safe even for test instances created via `__new__` without running `__init__`. |
| Ruff cleanup | multiple files | Cleared remaining Ruff findings by fixing import-order violations, unused imports/locals, semicolon-separated statements, shadowed imports, and one undefined closure variable in paste error handling. |

---

## 2. Verification Results

| Command | Result |
|---------|--------|
| `python -m pip install ruff` | Installed `ruff 0.15.16` successfully |
| `python -m pytest` | 51 passed |
| `python -m ruff check .` | All checks passed |
| `pyright` | 309 errors, 6 warnings remain |

Notes:

- The first pytest run exposed a real regression in `AppSettings.load()` for `__new__`-constructed test instances. This was fixed with lazy lock initialization, and the second pytest run passed fully.
- `ruff` is now available in the environment, and the project currently passes `python -m ruff check .`.
- `pyright` improved slightly from the original audit baseline of 313 errors / 7 warnings to 309 errors / 6 warnings, but it remains dominated by existing dynamic Qt/mixin typing issues.

---

## 3. Remaining Items

### Q-1 pyright is still not CI-ready

- **Status**: Not fully fixed
- **Current result**: 309 errors, 6 warnings
- **Primary causes**: mixin classes access attributes supplied by concrete QWidget classes, Qt APIs return Optional values that are not narrowed, and factory methods such as dock/panel creation are typed as generic QWidget.
- **Recommended next step**: Create a dedicated typing pass using `Protocol` or typed base classes for `NavigationMixin`, `ActionsMixin`, `LanSharingMixin`, dock widgets, and panel factory returns.

### Q-2 swallowed exceptions are partially improved only

- **Status**: Partial
- **Current result**: Key LAN API database/cache paths now log exceptions, but many other `except Exception: pass` or broad catch blocks remain across LAN, thumbnail cache, project data, and UI helpers.
- **Recommended next step**: Continue file-by-file exception review. Prioritize persistence, network, and background task code before UI cosmetic paths.

### Q-4 Dialog single-QSS migration remains open

- **Status**: Not fixed in this pass
- **Reason**: This is a broad UI refactor across settings/sharing dialogs. It is higher risk than the low-level fixes completed here and should be done separately with visual regression checks.
- **Recommended next step**: Move per-widget styles into `TabbedDialog._dialog_qss()`, object names, or dynamic properties. Keep only documented exceptions such as heading/muted/gear button styling.

## 4. Final Assessment

All previously identified functional and performance fixes remain in place according to the resolution document. The full test suite passes, and Ruff now has zero findings. The remaining work is quality-focused and should be handled as dedicated cleanup tracks rather than mixed into feature fixes.

Recommended order:

1. Continue swallowed-exception review in persistence, LAN, and background task paths.
2. Do a dedicated pyright typing sprint for mixins/factories.
3. Refactor dialogs toward the single-QSS design constraint with visual checks.
