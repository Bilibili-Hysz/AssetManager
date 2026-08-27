# Thumbnail Batch Response Privacy Evidence (2026-08-23)

## Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `thumbnail-batch-response-privacy-evidence-2026-08-23` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; focused LAN thumbnail batch response privacy batch |
| Baseline status SHA-256 | `017f7de51fc802cf618c0a107fa803dc0d9af5b9962d3b6ec1f0db9608823836` |
| Baseline diff SHA-256 | `9ac20cfa9e8a90a93ced97bcb262a4da295b87ae8a3f861161fdc7cac124590f` |
| Baseline tracked / untracked entries | `137 / 90` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16, Vitest 3.2.6 |

This append-only snapshot records the narrow successful batch-response cache policy fix. It does not modify prior reports or manifests. The machine-readable companion is [audit-manifest-thumbnail-batch-response-privacy-evidence-2026-08-23.json](audit-manifest-thumbnail-batch-response-privacy-evidence-2026-08-23.json).

## Finding and implementation

`POST /api/thumbnails/batch` returns library-derived base64 thumbnail bytes at a fixed URL while `paths`, requested size, blur policy, and authenticated context are supplied outside the URL. The successful response previously had no explicit cache directive.

`handle_thumbnail_batch()` now returns the unchanged JSON shape with:

```text
Cache-Control: private, no-store
```

The header is intentionally applied only to the successful data-bearing response in this batch. Error bodies do not contain thumbnail bytes and route-wide error-header middleware is outside scope. No TypeScript API type, request body, response shape, sessionStorage LRU, retry behavior, route URL, single-thumbnail policy, key/schema, WebUI namespace, or mutation/recovery behavior changed.

## Verification

### Focused backend matrix

```text
python -W error::RuntimeWarning -m pytest -n 0 --basetemp=.zcode/pytest-batch25e-batch-focused-evidence -q tests/lan/test_thumbnail_admission.py tests/lan/test_lan_api.py
```

Result: **246 passed, 0 failed**, exit code 0. Raw output: `artifacts/evidence/2026-08-23/thumbnail-batch-response-privacy/focused.stdout.log`.

The existing batch response shape, aliases, deduplication, partial-result behavior, unique-source budget and telemetry contracts remain covered; successful batch responses now assert `private, no-store`.

### Frontend contract/cache matrix

```text
cd webui && npm test -- --run src/api/thumbnails.contract.test.ts src/hooks/useThumbnailCache.test.tsx
```

Result: **2 test files passed, 6 tests passed**, exit code 0. Raw output: `artifacts/evidence/2026-08-23/thumbnail-batch-response-privacy/frontend.stdout.log`.

The initial attempt from repository root was not counted as a test run because root has no `package.json`; it exited with npm `ENOENT`. The corrected command from `webui/` passed. The frontend tests confirm the header-only server change does not alter request/body or application cache behavior.

### Full Python suite

```text
python -W error::RuntimeWarning -m pytest --basetemp=.zcode/pytest-batch25e-batch-full -n 0 -q
```

Result: **3985 passed, 14 skipped, 17 deselected, 2 warnings**, exit code 0, 615.74 seconds. Raw output: `artifacts/evidence/2026-08-23/thumbnail-batch-response-privacy/full.stdout.log`.

Two earlier full-suite attempts were not test runs due to working-directory command errors (webui directory and Git Bash `cd /d` syntax); they are not represented as passing evidence. The recorded full output is from the corrected repository-root command.

### Static/governance gates

Audit manifests, README stats, boundaries, style sources, route capabilities, frontend data-fetch, layer DAG, Ruff, compileall, and `git diff --check` all passed. Raw output: `artifacts/evidence/2026-08-23/thumbnail-batch-response-privacy/static.stdout.log` and `static.stderr.log`.

## Remaining limits

This batch does not add no-store headers to every 4xx response, change direct GET caching, introduce WebUI/sessionStorage namespace isolation, add persistent blur provenance, implement v3/profile-aware keys, modify database schema, or address mutation/recovery atomicity. It does not prove browser/intermediary cache behavior, filesystem races, power-loss recovery, performance, CVE/dependency, package/release, or clean-checkout behavior.

No commit, push, release, revert, reset, clean, or dirty-worktree overwrite was performed.
