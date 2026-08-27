# Thumbnail Browser / Intermediary E2E Evidence (2026-08-23)

## Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `thumbnail-browser-intermediary-e2e-evidence-2026-08-23` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; loopback real-browser/intermediary acceptance batch |
| Baseline status SHA-256 | `1c756d0554cd9b12ad0b5cb0a8f4b00ff36143510daa706fdc8f98488cde30ce` |
| Baseline diff SHA-256 | `dba4371296eda67758fa484342d3ada8a7b5a458cebc317925cf8931798f216b` |
| Baseline tracked / untracked entries | `143 / 105` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Chromium via Playwright, Vitest 3.2.6 |

This append-only snapshot adds a loopback-only forwarding/cache harness and real Chromium acceptance tests. The machine-readable companion is [audit-manifest-thumbnail-browser-intermediary-e2e-evidence-2026-08-23.json](audit-manifest-thumbnail-browser-intermediary-e2e-evidence-2026-08-23.json).

## Implemented test contract

`tests/e2e/test_webui_thumbnail_privacy_acceptance.py` starts a real `LanServer` over loopback, creates an isolated temporary library, launches real Chromium, and forwards requests through a deterministic local intermediary. The intermediary:

- forwards only to the same-machine LAN server;
- records upstream and intermediary-hit counters without logging credentials or source bytes;
- caches only successful GET responses explicitly marked `public` and not `private/no-store`;
- never caches POST or private/no-store responses;
- has dynamic loopback binding and explicit teardown.

The browser tests exercise the real SPA/API origin path and assert:

- `/api/info` exposes a runtime namespace;
- the active `lan_thumb_cache:<encoded namespace>` sessionStorage key is used and the legacy key is absent;
- blurred single and batch thumbnail responses are `private, no-store`;
- explicit public processed thumbnail responses are served from the intermediary on the second GET;
- private batch responses are fetched upstream on every POST.

The existing real Chromium realtime acceptance remains green. The separate TypeScript Mock/Static Playwright suite was also run; it currently has unrelated accessibility failures and real-backend connection-refused warnings, so it is recorded as failed rather than treated as browser privacy evidence.

## Verification

### Real browser + controlled intermediary

```text
python -W error::RuntimeWarning -m pytest -m e2e -n 0 --basetemp=.zcode/pytest-batch25l-focused-evidence-final -q tests/e2e/test_webui_thumbnail_privacy_acceptance.py
```

Result: **3 passed, 0 failed**, exit code 0, 12.39 seconds. Raw output: `artifacts/evidence/2026-08-23/thumbnail-browser-intermediary-e2e/browser-focused.stdout.log`.

### Existing real LAN browser regression

```text
python -W error::RuntimeWarning -m pytest -m e2e -n 0 --basetemp=.zcode/pytest-batch25l-realtime-evidence-final -q tests/e2e/test_webui_realtime_acceptance.py
```

Result: **6 passed, 0 failed**, exit code 0, 27.97 seconds. Raw output: `artifacts/evidence/2026-08-23/thumbnail-browser-intermediary-e2e/realtime.stdout.log`.

### WebUI build and Vitest

```text
cd webui && npm run build
cd webui && npm test -- --run
```

Build passed. Full WebUI suite passed: **103 test files, 695 tests**. Raw outputs: `webui-build.stdout.log`, `webui-build.stderr.log`, `webui-vitest.stdout.log`, `webui-vitest.stderr.log`.

### Full Python suite

```text
python -W error::RuntimeWarning -m pytest --basetemp=.zcode/pytest-batch25l-full -n 0 -q
```

Result: **3996 passed, 14 skipped, 20 deselected, 2 warnings**, exit code 0, 637.86 seconds. Raw output: `artifacts/evidence/2026-08-23/thumbnail-browser-intermediary-e2e/full.stdout.log`.

### Static/governance gates

After updating the measured Python test-file count in README for the new E2E module, the full static chain passed: audit manifests, README stats, boundaries, style sources, route capabilities, frontend data-fetch, layer DAG, Ruff, compileall and `git diff --check`. Raw output: `static.stdout.log` and `static.stderr.log`.

### Separate TypeScript Playwright lane

`npm run test:e2e` was executed and **failed** in the pre-existing mock/static lane: accessibility color-contrast assertions failed across multiple routes, while optional real-commerce tests skipped and mocked tests emitted expected connection-refused proxy warnings because no backend is configured for that lane. Raw outputs: `webui-playwright.stdout.log` and `webui-playwright.stderr.log`. This lane is not used to claim real thumbnail/intermediary verification.

## Compatibility limits

The controlled intermediary proves only the local forwarding/cache policy implemented by this test harness and the observed origin responses. It does not prove arbitrary production CDNs, shared proxies, TLS termination, cross-network deployments, browser cache behavior across every browser/platform, v3/v2/legacy artifact fallback through a full UI image flow, or video JPG fallback through a production intermediary.

The result remains **fixed-unverified** for production intermediary behavior, cross-platform filesystem races, power-loss recovery, mutation atomicity, package/release, CVE/dependency, performance and clean-checkout. No production Cache-Control behavior was changed. No commit, push, release, revert, reset, clean or dirty-worktree overwrite was performed.
