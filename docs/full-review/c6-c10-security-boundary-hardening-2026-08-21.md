# C6-C10 与安全边界 Hardening 回归证据（2026-08-21）

## 1. Snapshot Metadata

| Field | Value |
|---|---|
| Report ID | `c6-c10-security-boundary-hardening-2026-08-21` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; baseline captured before this report and manifest were added |
| Status fingerprint | `a366734cd67a4d9d76d93470e41191cdb6cc702a1cd79a50ae4e6dc7f2d3e247` |
| Binary diff fingerprint | `20df394ee7dbdb988da2db71a9f9711e106fdb32f8de94a412e6ea9b52874e70` |
| Tracked / untracked changes | 103 / 47 before this report and manifest were added |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This is an append-only dated snapshot. Earlier reports and manifests remain unchanged. The machine-readable companion is [audit-manifest-c6-c10-security-boundary-hardening-2026-08-21.json](audit-manifest-c6-c10-security-boundary-hardening-2026-08-21.json).

## 2. Implemented Hardening

- Project/tree containment now rejects public link/reparse targets, revalidates during scans, and uses POSIX `O_NOFOLLOW` descriptor traversal where available. Windows remains a bounded repeated-validation fallback rather than a claim of complete cross-platform atomic open semantics.
- Thumbnail admission now uses source-size limits, platform-aware deduplication, source identity snapshots, pre-consumption validation, and explicit `409 source_changed` behavior. Final file opening remains path-based.
- POSIX stale-lock recovery now serializes recovery with directory-level `flock`, cleans transient recovery markers on normal and exceptional paths, and fails closed when the required capability is unavailable. Windows QLockFile/PID behavior remains separate.
- Release workflow now pins actions to full SHAs, isolates write permission, passes the repository explicitly to `gh`, transfers and verifies a SHA-256 sidecar, and refuses duplicate release assets instead of silently overwriting them.

## 3. Parallel Verification

### Project containment

```text
python -m pytest --basetemp=.zcode/pytest-final-focused tests/integration/test_project_service.py tests/integration/test_project_service_containment.py tests/integration/test_project_service_session_binding.py
```

Result: **45 collected, 42 passed, 3 skipped, 0 failed**, exit code 0, 105.49 seconds. Skips were Windows symlink/directory-link capability limitations.

### Thumbnail admission

```text
python -m pytest --basetemp=.zcode/pytest-final-focused tests/lan/test_thumbnail_admission.py tests/integration/test_thumbnail_service.py
```

Result: **43 passed, 0 skipped, 0 failed**, exit code 0, 152.27 seconds.

### POSIX lock recovery

```text
python -m pytest --basetemp=.zcode/pytest-final-focused tests/integration/test_library_lock_posix_recovery.py tests/unit/test_db_lock_low_batch.py
```

Result: **16 collected, 13 passed, 3 skipped, 0 failed**, exit code 0, 249.48 seconds. POSIX `flock` tests were skipped on Windows.

### Release workflow

PyYAML parsing and static assertions passed: all action references use full 40-character SHAs; default permissions are `{}`; build is `contents: read`; publish is `contents: write`; repository context is explicit; no `--clobber`; checksum sidecar transfer and verification are present. GitHub runner execution, token authorization, upload/download actions, generated archive contents, and concurrent rerun behavior were not executed locally.

### Full Python suite

```text
python -m pytest --basetemp=.zcode/pytest-final-full -n 0
```

Result: **3922 collected, 17 deselected, 3905 selected, 3893 passed, 0 failed, 12 skipped, 2 warnings**, exit code 0, 574.40 seconds. Skips were Windows symlink/reparse privilege limitations, POSIX `flock` unavailable on Windows, and nondeterministic Windows process termination/queue finalization. Warnings were the existing Qt signal disconnect warning and duplicate ZIP entry warning.

## 4. Final Gates

The final local gates all passed:

- `check_audit_reports.py`: current manifest/index validation.
- `check_doc_stats.py`: README `python_test_files=267` matches the current tree.
- `check_boundaries.py`, `check_style_sources.py`, `check_route_capabilities.py`, `check_frontend_data_fetch.py`, `check_layers.py`.
- Full Ruff, compileall, and `git diff --check`.
- Release workflow YAML/static policy assertions.

Raw final gate logs are stored under `artifacts/evidence/2026-08-21/c6-c10-security-boundary-hardening-final/`. Agent-reported pytest runs are recorded as exact execution summaries; no agent stdout is represented as a local raw artifact.

## 5. Remaining Limitations

- POSIX multi-process stale-lock proof was not executed on this Windows host.
- Windows symlink/reparse behavior was not fully exercised because required privileges/capabilities are unavailable.
- Windows containment still narrows, but does not eliminate, replacement races between final validation and path-based operations.
- Thumbnail final-open is not an atomic descriptor-based operation.
- GitHub Actions release execution, permissions, artifact transfer, and duplicate-asset race behavior remain unverified locally.
- Browser E2E, real-backend LAN, dependency/CVE, performance, package/release, clean-checkout, and power-loss validation were not run.
- All C6-C10 and this hardening batch findings remain `fixed-unverified`; no finding is promoted by this report.
