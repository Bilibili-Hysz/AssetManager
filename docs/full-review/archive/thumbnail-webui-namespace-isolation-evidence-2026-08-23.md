# WebUI Thumbnail Cache Namespace Isolation Evidence (2026-08-23)

## Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `thumbnail-webui-namespace-isolation-evidence-2026-08-23` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; focused WebUI/runtime thumbnail namespace batch |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16, Vitest 3.2.6 |

This append-only snapshot records the runtime-scoped WebUI thumbnail cache namespace implementation. It does not modify prior reports or manifests. The machine-readable companion is [audit-manifest-thumbnail-webui-namespace-isolation-evidence-2026-08-23.json](audit-manifest-thumbnail-webui-namespace-isolation-evidence-2026-08-23.json).

## Finding and implementation

The WebUI thumbnail cache previously used one fixed `sessionStorage` key, `lan_thumb_cache`, and path-only memory entries. `identityGeneration` protected ordinary principal transitions but did not distinguish runtime/library contexts when the principal stayed unchanged.

The LAN `/api/info` response now exposes the optional `thumbnail_cache_namespace` field sourced from the live runtime's opaque `epoch`. The field is nullable for legacy runtime adapters. The epoch is generated per `LibraryRuntime`, so it does not expose a filesystem path or internal telemetry token.

The WebUI now:

- exposes the normalized API client scope through `ApiClient.scope`;
- derives `thumbnailCacheNamespace` from origin, API scope, runtime epoch (or a page-lifetime fallback), and principal identity;
- stores thumbnails under `lan_thumb_cache:<encoded namespace>`;
- clears in-memory/pending state when namespace or identity generation changes;
- restores only the active namespace's persisted map;
- rejects responses captured under a previous namespace or identity generation;
- retains the existing 300-entry LRU, request body `{paths, size}`, response `{thumbnails}`, and application sessionStorage behavior;
- clears namespaced and legacy thumbnail storage on logout/non-auth 401 through AuthContext.

No access token, cookie, raw root path, `event_token`, or credential was added to browser storage. Persistent v3 thumbnail keys, database schema, LAN thumbnail response DTO, and mutation/recovery were not changed.

## Verification

### Focused backend matrix

```text
python -W error::RuntimeWarning -m pytest -n 0 --basetemp=.zcode/pytest-batch25f-namespace-focused-final -q tests/lan/test_public_contracts.py tests/lan/test_lan_api.py tests/lan/test_system_feature_flags.py
```

Result: **259 passed, 0 failed**, exit code 0. Raw output: `artifacts/evidence/2026-08-23/thumbnail-webui-namespace-isolation/focused-final.stdout.log`.

Coverage includes `/api/info` public field compatibility, runtime namespace exposure, legacy runtime null compatibility, LAN route/security behavior and existing thumbnail batch contracts.

### Focused WebUI matrix

```text
cd webui && npm test -- --run src/api/client.test.ts src/hooks/useThumbnailCache.test.tsx src/stores/AuthContext.test.tsx src/api/thumbnails.contract.test.ts
```

Result: **4 test files passed, 34 tests passed**, exit code 0. Raw output: `artifacts/evidence/2026-08-23/thumbnail-webui-namespace-isolation/frontend-focused-final.stdout.log`.

The focused tests cover normalized API scope, namespace-separated persisted thumbnails, identity-generation clearing, stale response rejection, AuthContext identity behavior and unchanged thumbnail request contracts.

TypeScript validation:

```text
cd webui && npm run typecheck
```

Result: exit code 0. Raw output: `artifacts/evidence/2026-08-23/thumbnail-webui-namespace-isolation/typecheck-final.stdout.log`.

### Full Python suite

```text
python -W error::RuntimeWarning -m pytest --basetemp=.zcode/pytest-batch25f-namespace-full-final -n 0 -q
```

Result: **3985 passed, 14 skipped, 17 deselected, 2 warnings**, exit code 0, 635.37 seconds. Raw output: `artifacts/evidence/2026-08-23/thumbnail-webui-namespace-isolation/full.stdout.log`.

### Full WebUI suite

```text
cd webui && npm test -- --run
```

Result: **103 test files passed, 695 tests passed**, exit code 0. Raw output was captured by the completed full WebUI run; the summary is recorded here from the command result. The full run includes the namespace, API client, BrowsePage, AuthContext, realtime and application cache suites.

### Static/governance gates

Audit manifests, README stats, boundaries, style sources, route capabilities, frontend data-fetch, layer DAG, Ruff, compileall, and `git diff --check` passed before the new dated report was indexed. A post-index rerun is recorded in `static-post-index.stdout.log` and `static-post-index.stderr.log` and must be interpreted with the companion manifest.

## Remaining limits

This batch does not provide a mathematically unique namespace when an old backend lacks `thumbnail_cache_namespace`; the page-lifetime fallback intentionally avoids persistent cross-context reuse but is not a server identity proof. It does not add `/api/revision` access for low-privilege clients, browser/intermediary E2E, persistent v3/profile-aware thumbnail keys, blur provenance, complete WebUI namespace Cartesian testing, database schema migration, ProjectService convergence, or mutation/recovery atomicity. It also does not prove cross-platform filesystem races, power-loss recovery, performance, CVE/dependency, package/release, or clean-checkout behavior.

No commit, push, release, revert, reset, clean, or dirty-worktree overwrite was performed.
