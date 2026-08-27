# Download Tracker Concurrency Evidence (2026-08-26)

## Scope
Finding `DOWNLOAD-TRACKER-CONCURRENCY-39-01` covered concurrent event-thread updates and GUI reads of the module-level `_history` dictionary.

## Changes
- Added a module-level `threading.RLock` around load, update, prune, parser reads, clear/undo, save, and unregister.
- `HistoryPanel.build()` copies and sorts immutable record snapshots under the lock, then constructs Qt widgets after releasing it.
- Preference bag read/write for tracker history is serialized within the tracker lock for same-process operations.

## Verification
- New concurrency and existing plugin contract matrix: **4 passed**.
- Final serial Python suite: **4089 passed, 16 skipped, 20 deselected, 2 warnings**, exit code 0.
- Full Ruff, compileall, diff-check, and repository governance gates passed.

## Boundaries
Status is `fixed-unverified`: this does not provide a cross-process JSON merge lock, strict host-level unload barrier, or proof across multiple dynamically loaded module instances. Qt verification used an offscreen/fake widget boundary; no production GUI soak was run.
