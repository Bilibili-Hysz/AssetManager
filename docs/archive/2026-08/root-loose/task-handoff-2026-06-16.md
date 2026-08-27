# Task Handoff - 2026-06-16

## Current Goal

Continue auditing and fixing confirmed bugs in the flattened root project, using small, low-risk changes with regression tests.

## Current State

The workspace has been flattened: the active project is at the repository root, and `Project/` is retained as an ignored backup of the previous workspace. Focus edits under:

- `AssetsManager/`
- `tests/`
- `docs/`

Latest full quality gate passed:

```powershell
python -m ruff check .
python -m pyright
python -m compileall AssetsManager -q
python -m pytest -q
```

Latest result:

- Ruff: passed
- Pyright: `0 errors, 0 warnings, 0 informations`
- Compileall: passed
- Pytest: `603 passed`
- Pytest warnings: none

## Completed In This Session

### Workspace

- Flattened `Project/AssetsManager_Python_Rewrite_refactor` into the repository root.
- Preserved the full pre-flattened `Project/` directory as an ignored backup.
- Removed unrelated root-level clutter and runtime/cache directories.
- Reinitialized Git at the flattened root; no initial baseline commit has been created yet.
- Added `docs/workspace.md` to document the new layout.

### Core / DI / Cache

- Fixed `TTLCache.__contains__` so membership respects TTL expiry.
- Fixed `ThreadSafeSingleton._locks` race by guarding lock creation.
- Fixed `ServiceContainer.resolve()` class-registered singleton race during concurrent first resolve.
- Bounded `FileListController` first-image cache.

### Repository / Application

- Fixed `MetadataRepository.get_cached_stats()` SQLite variable-limit crash by chunking large `IN` queries.
- Added atomic `MetadataRepository.add_url()` / `remove_url()` and updated `MetadataService` to avoid URL read-modify-write loss.
- Fixed `AuthService.verify_share_password()` for passwordless shares.
- Fixed invite-code TOCTOU by adding `AuthRepository.insert_user_with_invite()` and conditional invite consumption.
- Fixed `FileOperationService.rename()` path traversal via `../name`.
- Fixed `FileOperationService.copy_to_directory()` to resolve source/destination event paths.
- Fixed `ShareService.validate_access()` to preserve expired/download-limit reasons.
- Fixed `ShareRepository.increment_download()` with conditional atomic update.
- Fixed `UndoService` delete undo/redo lifecycle so delete redo can be undone again.
- Changed `UndoService` backup dir from fixed `AssetsManager_undo` to unique `tempfile.mkdtemp(prefix="AssetsManager_undo_")`.

### LAN

- Fixed password-protected `/api/shares/{id}/info` path leakage.
- Added `/api/download/batch` path-count/type limits.
- Fixed ZIP temp cleanup to run even when response `write_eof()` fails.
- Stopped LAN route OSError responses from leaking internal exception strings in selected routes.
- Fixed tag routes:
  - `handle_tags()` no longer silently returns empty list on failure.
  - `handle_create_tag()` now requires `file_path`.
  - tag route failures return generic errors.
- Optimized `RateLimiter` / `AuthRateLimiter` LRU tracking using `OrderedDict`.
- Fixed key/password/local UI token auth to set admin-like request user context.
- Fixed `/api/shares` enumeration: unauthenticated/no user context now gets `401`; admin context lists all; normal users list own shares.
- Replaced LAN auth raw request dict keys with typed `web.RequestKey` helpers and removed aiohttp `NotAppKeyWarning` warnings.
- Fixed LAN user-state cache invalidation for user toggle operations.
- Added route-level regression coverage proving `/api/users/{id}/toggle` clears the active-user cache through HTTP.
- Fixed share-download route semantics so exhausted shares return `403` and atomic increment failure blocks file serving.

### Presentation / Desktop

- Fixed `_suppress_libpng_warnings()` with a process-level lock around fd redirection.
- Fixed `_Op(QRunnable)` background task constructor in file-list actions.
- Fixed `ThumbnailLoader.stop()` to stop accepting late results and wait briefly for threadpool work.
- Fixed `QImage.save()` WEBP format argument type.
- Fixed `InfoPanel` library-switch cache pollution by clearing `_urls_scanned` and `_classify_cache`.
- Fixed `TabContainer` stale tab-index capture by resolving tab index from panel at update time.
- Fixed `_SelShim` selection model:
  - made it a `QObject` with a real Qt signal;
  - returned a stable selection model instance;
  - emitted `selectionChanged` on grid selection updates.
- Bounded `FileListPanel._first_image_cache`.
- Fixed `Quick Share` URL construction to use server status URL instead of hardcoded localhost.
- Fixed `ImageViewerOverlay` host/event-filter lifecycle with guarded `_host_window` tracking.

## Tests Added Or Updated

Representative regression coverage added/updated for:

- TTL membership expiry.
- Singleton and DI concurrent first resolve.
- Large metadata stats chunking.
- Passwordless share password verification.
- Protected share info path leakage.
- File operation rename traversal.
- Canonical copy event paths.
- Share expired/download-limit validation.
- Atomic share download increment.
- Batch download limits.
- Library manager no settings mutation.
- Invite code single-consumption and transaction rollback.
- URL add/remove repository semantics.
- Rate limiter LRU eviction.
- ZIP cleanup on write failure.
- Tag route missing `file_path`.
- Tab title update after tab close.
- Quick Share status URL.
- ThumbnailLoader stopped late results.
- Selection shim signal emission.
- First-image cache bound.
- Undo delete redo then undo again.
- Unique undo backup dirs.
- Image viewer event-filter cleanup.
- LAN `/api/shares` auth behavior.
- LAN auth `web.RequestKey` request context without `NotAppKeyWarning`.
- LAN user cache invalidation on toggle operations.
- LAN `/api/users/{id}/toggle` route-level cache invalidation.
- LAN share-download exhausted-limit and atomic-increment-failure behavior.

## Remaining Long-Term Tasks

Prioritize these with the same workflow: verify existence, make minimal fix, add regression test, run full gate.

### Security / LAN

- Continue reviewing LAN error responses for internal path/exception leakage beyond files/metadata/tags.
- Review share download completion semantics: route checks now use atomic increment, but file response serving after increment can still fail after counting.
- Review temp ZIP cleanup for all response paths and large download cancellation behavior.
- Review `/api/shares/{id}/download` and preview public semantics for passwordless shares.
- Review LAN SQLite access across event loop and threadpool boundaries. Some routes still use shared `sqlite3.Connection` from both request handlers and `asyncio.to_thread`.
- Review user-cache invalidation on future user state changes. Existing register and toggle route paths have coverage.

### Application / Data Consistency

- Review `FileOperationService.unique_destination()` TOCTOU. Existing behavior still uses check-then-copy/move; fixing may require atomic open/copy strategy.
- Review permanent delete/backup race between backup creation and deletion.
- Review `MetadataRepository` URL JSON corruption behavior and whether malformed JSON should be repaired.
- Review cross-library scoping of `UndoService`: bootstrap currently resolves it as a singleton in scoped services. Decide whether undo stacks should be per-library/session.

### Presentation / Desktop

- Review whether `ThumbnailLoader.stop()` should wait longer or expose explicit async shutdown for UI close paths.
- Review `InfoPanel._classify_cache` bound. It is now cleared on library switch, but still unbounded within one library.
- Review `FileListPanel._first_image_cache` clearing strategy. It now has a hard bound and clears all at limit; LRU may be better later.
- Review `ImageViewerOverlay` behavior when host is destroyed before viewer close in real UI; current fix guards against RuntimeError but does not auto-close viewer.

### Architecture / Cleanup

- Continue replacing presentation direct store/db access with scoped services where practical.
- Continue enforcing architecture boundary tests for new code.
- Continue using LAN auth context helpers instead of direct request storage access.
- Keep documentation synchronized only when code behavior changes materially.

## Recommended Next Step

Start by reviewing LAN SQLite access across event-loop and threadpool boundaries:

1. Verify routes that use a shared `sqlite3.Connection` from both request handlers and `asyncio.to_thread`.
2. Make the smallest low-risk fix.
3. Add a focused regression test.
4. Run full quality gate.

## New Session Prompt

Use this prompt in the next session:

```text
We are working in D:\~Vibe-Coding\Projects\AssetsManager_old-bak. The active project is now flattened at the repository root; Project/ is an ignored backup of the old workspace.

Continue the bug-audit/fix work from docs/task-handoff-2026-06-16.md. Make only small, low-risk fixes after verifying the issue still exists. Do not edit Project/ unless explicitly asked; it is a backup.

Latest full gate passed before handoff:
- python -m ruff check .
- python -m pyright
- python -m compileall AssetsManager -q
- python -m pytest -q => 603 passed, 0 warnings.

Recommended first task: review LAN SQLite access across event-loop and threadpool boundaries. Then add/adjust tests and run the full gate.

Workflow:
1. Read docs/workspace.md and docs/task-handoff-2026-06-16.md.
2. For any non-trivial task, read docs/agent-quick-map.md first.
3. Verify current code before editing.
4. Patch minimal files only.
5. Add regression tests.
6. Run full gate: python -m ruff check . && python -m pyright && python -m compileall AssetsManager -q && python -m pytest -q.
```
