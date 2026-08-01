---
feature: session-07d28cba9ffeR7yeBnz5N4prK7-closeout
status: delivered
specs:
  - docs/compose/specs/2026-07-21-desktop-lan-webui-architecture-recalibration-design.md
plans:
  - docs/compose/plans/2026-07-21-desktop-lan-webui-architecture-recalibration.md
branch: master
commits: 77492fe2b3ee9e4bb26e17b982d421993d545136
---

# Session Closeout — Desktop–LAN–WebUI Recalibration

## What Was Completed

This session closed the remaining evidence and documentation work for the
Desktop–LAN–WebUI architecture recalibration. The React SPA contract migration
tracked by T151 is complete, the Windows cross-surface acceptance tracked by
T530 is complete, and the Linux directory-symlink platform gate tracked by
T533 is complete.

The final release documentation now records `delivered` for the recalibrated
scope. The parent migration report, recalibration report, Task D handoff,
architecture overview, architecture diagram and Runtime ADR use the same
status and evidence vocabulary.

## Task Status

| Task | Status | Final evidence |
|---|---|---|
| T151 — 迁移 Task 2 SPA 测试契约 | `done` | LAN, SPA and package contract slice: `209 passed` |
| T530 — Execute Task E cross-surface release gate | `done` | Desktop/LAN/Chromium focused matrix: `186 passed` |
| T533 — 重试 Linux directory-symlink 发布门 | `done` | Ubuntu WSL isolated Linux gate: `1 passed, 23 deselected` |

## Verification

### T151

```text
python -m pytest tests/lan/test_lan_api.py tests/lan/test_t2_t4_contracts.py tests/core/test_package_contents.py -q
209 passed in 11.98s
```

### T530

```text
python -m pytest tests/e2e/test_webui_realtime_acceptance.py tests/desktop/test_file_list_shim.py tests/desktop/test_file_event_session_routing.py tests/desktop/test_tag_event_session_routing.py tests/lan/test_runtime_realtime.py tests/lan/test_server_lifecycle.py tests/integration/test_window_lifecycle_lan_failure.py -q
186 passed in 55.68s
```

The current count is `186`, not the earlier historical snapshot of `184`.
The added coverage includes real browser logout/401 teardown and Desktop
projection journeys.

### T533

The gate ran in Ubuntu WSL with:

- Ubuntu system PySide6 `6.10.2`, because PyPI had no compatible wheel for the
  WSL Python `3.14.4`;
- a temporary `system-site-packages` virtual environment for the remaining
  dependencies;
- `QT_QPA_PLATFORM=offscreen`;
- an isolated temporary RuntimeData root to avoid repository cache pollution.

The executed Linux command selected the directory-symlink test:

```text
python -m pytest tests/integration/test_project_service.py -k symlink -q
1 passed, 23 deselected
```

The test was rerun during final review and passed again with the same result.
This is direct Ubuntu WSL evidence, not hosted CI evidence.

### Documentation quality

- `git diff --check` passed; only normal Windows LF/CRLF warnings were emitted.
- Reviewed relative documentation links all resolve.
- Reviewed files contain no trailing whitespace.
- No code, database, commit, push or `DeepSeek Docs/` changes were made for
  this closeout.

## Final Decision

The recalibrated Desktop–LAN–WebUI scope is `delivered` based on the completed
T151, T530 and T533 evidence. The Windows full Python suite still reports its
expected directory-symlink skip; the passing Ubuntu WSL gate supplies the
platform-specific evidence that Windows cannot provide.

## Commit and Push

The scoped documentation closeout was committed as:

```text
77492fe2b3ee9e4bb26e17b982d421993d545136
```

A push was attempted immediately after the commit. It was not performed
because this checkout has no configured Git remote or push destination.
Git returned exit code `128` with:

```text
fatal: No configured push destination.
```

No remote was added or modified. The commit remains local on `master`.

## Journey Log

- [lesson] Task state must be checked in the task ledger rather than inferred
  from report prose.
- [lesson] T530's current focused count is `186`; prior report counts are
  historical snapshots and must be labeled or updated.
- [pivot] Ubuntu's system PySide6 package was used after the Python 3.14 WSL
  environment could not install PySide6 from PyPI.
- [lesson] Release status is only coherent when the ADR, architecture index,
  parent report, final report and plan agree on the same gate result.

## Source Materials

| File | Role |
|---|---|
| `docs/compose/reports/desktop-lan-webui-architecture-recalibration.md` | Current Task E release report |
| `docs/compose/reports/desktop-lan-webui-architecture-migration.md` | Parent architecture migration report |
| `docs/compose/reports/desktop-lan-webui-architecture-task-d.md` | Task D handoff and later Task E result |
| `docs/compose/plans/2026-07-21-desktop-lan-webui-architecture-recalibration.md` | Authoritative A–E plan and decision rules |
| `docs/adr/0003-library-runtime.md` | Runtime ownership and release architecture decision |
| `tests/lan/test_t2_t4_contracts.py` | SPA and WebSocket contract evidence |
| `tests/e2e/test_webui_realtime_acceptance.py` | Real browser realtime and identity evidence |
| `tests/integration/test_project_service.py` | Directory-symlink platform gate |
