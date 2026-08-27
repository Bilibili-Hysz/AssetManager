# C2/C3-min Session 与事务边界实施证据（2026-08-21）

## 1. Scope and baseline

本报告记录 FavoriteService session-bound connection enforcement 与 MetadataService.remove_url transaction guard 两个最小切片。它是既有 C1、S1/S5/S2-min 和 Desktop 动态证据的新增补充，不修改既有 manifest。

| Field | Value |
|---|---|
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Worktree source | Dirty worktree |
| Status fingerprint | `55283c28a331ff7d0580e9f60f884ccd262875ce45c187b6f68eeef6377e3c15` |
| Binary diff fingerprint | `88a0814dfd1ff23fc5bc29d25ef05a4191f297013c4b8d9b55c84b9a9ff8e6ab` |
| Tracked / untracked changes | 53 / 14 before this report and manifest were added |
| Runtime | Windows, Python 3.14 local environment |

The worktree contains pre-existing user changes and earlier audit/implementation artifacts. No commit, push, reset, clean, dependency installation, browser E2E, full Python suite, release validation, or vulnerability scan was performed.

## 2. Implemented findings

### C2-01 / EVID-06: FavoriteService session-bound connection enforcement

`AssetsManager/application/favorite_service.py` now validates the provider during construction when a real `LibrarySession` is supplied, using the same bound-method identity pattern as TagService. The service captures the session root identity and, in `_connection()`, rejects foreign roots and explicit connections that are not the exact bound session connection. The `session=None` provider/raw compatibility path remains unchanged.

Previously, a service bound to session A could accept root B plus connection B, mutate B, and publish a FavoritesChanged event labeled with session A. The new tests in `tests/integration/test_favorite_service.py` cover foreign root/connection and same-root/foreign-connection attempts while retaining the existing session-scoped happy path.

**Result:** FavoriteService integration coverage passed; status is `fixed-unverified` pending broader runtime and multi-process validation.

### C3-01 / EVID-05: Metadata remove_url transaction/event ordering

`MetadataService.remove_url()` now calls the existing `_require_event_safe_transaction()` guard before repository mutation, matching `set_notes()` and `add_url()`. A session-bound caller-owned outer transaction therefore fails closed before mutation or event publication. This prevents `AssetUrlsChanged` from being broadcast for a write that a later caller rollback could undo.

`tests/integration/test_event_publishing.py` now covers both the dirty-transaction rejection (no event, URL remains) and the clean session-bound success path (URL removed, one event with empty `new_urls`). Raw compatibility tests remain unchanged.

**Result:** transaction/event ordering tests passed; status is `fixed-unverified` pending broader transaction and runtime validation.

## 3. Executed validation

| Command | Result |
|---|---|
| `pytest tests/integration/test_favorite_service.py tests/integration/test_event_publishing.py -q -n 0 --basetemp=.zcode/pytest-c2c3-min` | 23 passed |
| `pytest tests/integration/test_favorite_service.py tests/integration/test_event_publishing.py tests/integration/test_metadata_service.py tests/integration/test_tag_service.py tests/integration/test_project_service_session_binding.py -q -n 0 --basetemp=.zcode/pytest-c2c3-related` | 74 passed |
| Python compile for changed services/tests | passed |
| Scoped Ruff | passed |
| `python scripts/check_doc_stats.py` | README stats current |
| `python scripts/check_audit_reports.py` | 4 existing manifests valid before this report was added |
| `python scripts/check_boundaries.py` | passed |
| `python scripts/check_style_sources.py` | 0 violations across 83 files |
| `python scripts/check_layers.py` | layer DAG passed |
| `python scripts/check_route_capabilities.py` | 0 violations |
| `python scripts/check_frontend_data_fetch.py` | 0 violations across 26 pages |
| `ruff check AssetsManager tests scripts run.py` | passed |
| `git diff --check` | no whitespace errors; LF/CRLF conversion warnings only |

The default pytest temp root remains inaccessible in this environment (`WinError 5`), so pytest commands used repository-local `--basetemp` and `-n 0`.

## 4. Explicit non-goals and remaining evidence

- FavoriteRepository unconditional commit behavior was not redesigned.
- No global after-commit callback, transaction context, or durable outbox was introduced.
- GalleryService raw connection overrides remain a separate slice.
- C4 filesystem projection repair, durable reconciliation envelope, watcher/import repair, and FileSystemChanged protocol changes were not attempted.
- No full Python suite, browser E2E, real-backend LAN acceptance, performance benchmark, dependency/CVE scan, package/release validation, or independent Windows lifecycle CI was run.
- C2/C3 findings remain `fixed-unverified`; this report does not mark them `verified-fixed`.
