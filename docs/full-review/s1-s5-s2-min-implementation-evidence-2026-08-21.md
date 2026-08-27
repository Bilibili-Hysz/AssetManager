# S1 / S5 / S2-min 实施证据（2026-08-21）

## 1. Scope and baseline

本报告记录当前批次对分享预览、WebUI 身份/缓存竞态和纯 CPU 认证边界的实施与动态验证。它是 `evidence-convergence-2026-08-20.md` 的新增动态补充，不修改既有静态审计输入或 Desktop 实施证据。

| Field | Value |
|---|---|
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Worktree source | Dirty worktree |
| Status fingerprint | `eefdc933c71fb23dfa06834a7e809ac6da1a608f6ca1c5a05fdba31f38b3a56d` |
| Binary diff fingerprint | `df88d5d409fd2b8618f9ae55971929f9225f94b763d3a96b1183cb5eaacc0d56` |
| Tracked / untracked changes | 34 / 10 before this report and its manifest were added |
| Runtime | Windows, Python 3.14 local environment, WebUI Node/Vite environment |

The worktree includes pre-existing user changes, earlier audit artifacts, Desktop async changes, and this batch. No commit, push, reset, clean, dependency installation, browser E2E, full Python suite, release validation, or vulnerability scan was performed.

## 2. Implemented findings

### S1 / EVID-01: Share preview policy parity

`AssetsManager/lan/routes/shares.py:17` and `:385` now route an authorized share preview through `serve_verified_image` with `BLURRED_PREVIEW_SIZE`. Share-specific existence, expiry, `allow_preview`, password-token, and scope checks remain in the share route; the shared image pipeline supplies actual Pillow format verification, private no-store headers, blur processing, bounded blurred output, and fail-closed processing errors.

Coverage includes `tests/lan/test_share_preview_policy.py` and the existing share API matrix in `tests/lan/test_lan_api.py:4383`, `:5302`, and `:5450`. Legacy fake PNG success fixtures were replaced by real Pillow PNGs; corrupt-image cases remain intentionally invalid.

**Result:** 3 dedicated policy tests and 25 broader share regressions passed. This is locally fixed and dynamically exercised, but browser/real-backend and full-suite validation remain out of scope; status is `fixed-unverified`.

### S2-min / EVID-02: Simple password-token verification offload

`AssetsManager/lan/auth.py:35` adds `verify_token_async`, which executes the pure token verification function through `asyncio.to_thread`. The middleware paths at `AssetsManager/lan/server.py:1562` and `:1629`, plus the WebSocket password validator at `AssetsManager/lan/routes/websocket.py:72`, use the shared async boundary. Access-key PBKDF2 offload remains unchanged. DB-backed user authentication, revocation persistence, seller authority mapping, and a generic async LAN service layer were intentionally not changed.

`tests/lan/test_l2_rate_input_cpu.py:174` covers the middleware path, and `tests/lan/test_websocket_auth_offload.py` covers WebSocket access-key/password behavior.

**Result:** 10 L2/auth offload tests and 15 combined S1/S2 LAN tests passed. The scope is intentionally narrow and does not prove the unchanged DB-backed authentication chain; status is `fixed-unverified`.

### S5 / EVID-07: WebUI identity and stale-response boundaries

The key query parameter is removed with `history.replaceState` at `webui/src/pages/LoginPage.tsx:105` while preserving unrelated query parameters and hash. Stale main-auth generation results no longer report success. Seller state has an operation generation at `webui/src/stores/SellerAuthContext.tsx:42`, seller logout uses the optional seller context in `webui/src/components/storefront/StorefrontShell.tsx`, and `useCachedQuery` publishes against the captured request key at `webui/src/hooks/useCachedQuery.ts:99` and `:111-140`.

The focused suite covers login URL cleanup, auth generation, seller login/logout races, storefront logout domain, and old-key/new-key response publication.

**Result:** 42 focused Vitest tests passed, TypeScript typecheck passed, and the production WebUI build passed (1,702 modules transformed). Browser E2E was not run; status is `fixed-unverified`.

## 3. Executed validation

| Command | Result |
|---|---|
| `pytest tests/lan/test_share_preview_policy.py tests/lan/test_websocket_auth_offload.py -q -n 0 --basetemp=.zcode/pytest-s1-s2` | 5 passed |
| `pytest tests/lan/test_l2_rate_input_cpu.py -q -n 0 --basetemp=.zcode/pytest-auth-offload` | 10 passed |
| `pytest tests/lan/test_lan_api.py -k 'share_preview or share_verify_api_client_header or password_share_cookie or expired_password_share or share_verify or share_download' -q -n 0 --basetemp=.zcode/pytest-share-broad` | 25 passed, 211 deselected |
| `pytest tests/lan/test_share_preview_policy.py tests/lan/test_websocket_auth_offload.py tests/lan/test_l2_rate_input_cpu.py -q -n 0 --basetemp=.zcode/pytest-s1-s2-full` | 15 passed |
| Focused WebUI Vitest suite (5 files) | 42 passed |
| `npm run typecheck` | passed |
| `npm run build` | passed; 1,702 modules transformed |
| `ruff check AssetsManager tests scripts run.py` | passed |
| `python scripts/check_audit_reports.py` | valid manifests before this report was added |
| `python scripts/check_doc_stats.py` | README stats current after updating `python_test_files` to 262 |
| `python scripts/check_boundaries.py` | passed |
| `python scripts/check_style_sources.py` | 0 violations across 83 files |
| `python scripts/check_route_capabilities.py` | 0 violations |
| `python scripts/check_frontend_data_fetch.py` | 0 violations across 26 pages |
| `python scripts/check_layers.py` | layer DAG passed |
| `git diff --check` | no whitespace errors; existing LF/CRLF conversion warnings only |

The default pytest temp root remains inaccessible in this environment (`WinError 5`), so executed pytest commands used repository-local `--basetemp` and `-n 0`.

## 4. Explicit non-goals and remaining evidence

- No DB-backed `authenticate_user` offload or transaction/session redesign was attempted.
- Revocation persistence fail-open behavior, seller-to-WebSocket authority mapping, and broad synchronous LAN service conversion remain separate workstreams.
- No full Python suite, browser E2E, real-backend LAN acceptance, performance benchmark, dependency/CVE scan, package/release validation, or independent Windows CI was run.
- Findings in this report remain `fixed-unverified` until the applicable broader validation lanes produce durable artifacts.
