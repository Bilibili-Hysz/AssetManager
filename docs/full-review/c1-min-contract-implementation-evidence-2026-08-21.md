# C1-min HTTP/TypeScript 契约实施证据（2026-08-21）

## 1. Scope and baseline

本报告记录 C1-min 的 Gallery、Activity Log、canonical JSON error envelope 和 WebUI API error body 收口。它是既有 `evidence-convergence-2026-08-20.md` 及 S1/S5/S2-min 动态证据的新增补充，不修改既有 manifest。

| Field | Value |
|---|---|
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Worktree source | Dirty worktree |
| Status fingerprint | `0b40da8990da6d7bb3a454bd9b66d1f5eb92ea479fd323cceb2dcdb941b477e2` |
| Binary diff fingerprint | `416074c292936693efd0cb75014d1eef3220a78106be0d615242b23f017f3379` |
| Tracked / untracked changes | 49 / 13 before this report's manifest was added |
| Runtime | Windows, Python 3.14 local environment, WebUI Node/Vite environment |

The worktree contains pre-existing user changes, earlier audit artifacts and implementation batches. No commit, push, reset, clean, dependency installation, browser E2E, full Python suite, release validation, or vulnerability scan was performed.

## 2. Implemented findings

### C1-01 / EVID-07 / XAPI-06: Gallery home response union

The backend already emits either `202 {"building": true}` or the ready projection. `webui/src/types/api.ts:126-143` now models this as `GalleryHomeBuildingResponse | GalleryHomeReadyResponse`; `GalleryHomePage.tsx:50-52` narrows on the `building` discriminant and no longer uses the local intersection type or promise cast. Existing polling and ready-state rendering remain unchanged.

**Result:** Gallery page, public contract, and backend gallery tests passed. The browser/real-backend surface was not run; status is `fixed-unverified`.

### C1-02 / CQ-16: Activity timestamp unit parity

The backend activity record uses `time.time()` Unix epoch seconds. `webui/src/types/api.ts:383` now declares `timestamp: number`, and `ActivityLog.tsx:38` multiplies by `1000` before constructing a JavaScript `Date`. Fixtures and tests now use numeric seconds and explicitly verify a 2026 display instead of a 1970-era millisecond interpretation.

**Result:** Activity component tests and LAN activity assertions passed; status is `fixed-unverified` pending real-browser validation.

### C1-03 / EVID-13 / XAPI-02: Canonical JSON error envelope slices

The canonical frontend `ErrorResponse` at `webui/src/types/api.ts:400-406` now requires `error`, `code`, and `details`, with optional `field` and extensible route-specific fields. `webui/src/api/errors.ts:1-17` adds `ApiErrorBody` and `isErrorResponse`. `client.ts:52-55,113-133,183-210` parses and retains response bodies for 401, 403, 429, 503 and generic errors; 429 preserves both canonical body details and Retry-After/rate-limit headers.

Backend slices now use the canonical envelope:

- Commerce/seller feature-disabled responses include `details: {}` through `commerce_policy.py:60-73`.
- Security auth, browse and general rate limits include machine codes and `details.retry_after` while preserving the compatibility top-level `retry_after` and `Retry-After` header at `security.py:203-245`.
- Download quota denial returns canonical 429 responses with `details.quota`, `details.retry_after`, compatibility `quota`, and existing quota headers at `downloads.py:24-44`.
- `IdempotencyKeyReusedError` keeps its declared `idempotency_key_reused` code before generic `OperationNotPermitted` mapping at `_errors.py:198-201`.

The batch intentionally does not normalize every direct `aiohttp.web.HTTPException`; binary/media 404s, page fallback, and a route/status matrix remain a separate scope.

**Result:** Backend error/quota contract tests and frontend API error tests passed. Full route matrix and browser error UX were not run; status is `fixed-unverified`.

## 3. Executed validation

| Command | Result |
|---|---|
| `pytest tests/lan/test_gallery_routes.py tests/lan/test_commerce_error_contract.py tests/lan/test_commerce_routes.py tests/lan/test_route_capabilities.py tests/lan/test_l2_rate_input_cpu.py tests/lan/test_lan_api.py -k 'gallery or quota or activity or share_preview or middleware or commerce_disabled or seller_capability or idempotency' -q -n 0 --basetemp=.zcode/pytest-c1-all` | 29 passed, 264 deselected |
| Focused WebUI Vitest suite (`errors`, `client`, Gallery, Activity, public contracts) | 34 passed across 5 files |
| `npm run typecheck` | passed |
| `npm run build` | passed; 1,702 modules transformed |
| `ruff check` on C1 backend scope | passed |
| `ruff check AssetsManager tests scripts run.py` | passed |
| `python scripts/check_doc_stats.py` | README stats current |
| `python scripts/check_audit_reports.py` | 3 existing manifests valid before this report was added |
| `python scripts/check_boundaries.py` | passed |
| `python scripts/check_style_sources.py` | 0 violations across 83 files |
| `python scripts/check_route_capabilities.py` | 0 violations |
| `python scripts/check_frontend_data_fetch.py` | 0 violations across 26 pages |
| `python scripts/check_layers.py` | layer DAG passed |
| `git diff --check` | no whitespace errors; LF/CRLF conversion warnings only |

The default pytest temp root remains inaccessible in this environment (`WinError 5`), so pytest commands used repository-local `--basetemp` and `-n 0`.

## 4. Explicit non-goals and remaining evidence

- No global HTTP exception normalizer was introduced.
- Gallery pagination/`next_cursor`, buyer-order `total`, TreeItem generated/manual DTO consolidation, and full API DTO generation remain separate work.
- No full Python suite, browser E2E, real-backend LAN acceptance, performance benchmark, dependency/CVE scan, package/release validation, or independent Windows lifecycle CI was run.
- C1 findings remain `fixed-unverified`; no finding is marked `verified-fixed` by this report.
