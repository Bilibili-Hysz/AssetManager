# Batches 57-63m Execution Evidence (2026-08-27)

Consolidated execution record for the seven confirmed batches from the 57-66 confirmation round (57/59/66 vetoed by that audit). Machine-readable per-batch manifests follow this report. Full serial suite on final bytes: **4128 passed, 16 skipped, 20 deselected, 2 warnings**.

## Batch 58 — restore-marker dialog i18n (`RESTORE-MARKER-I18N-58-01`, fixed-unverified)
app.py's five hardcoded English strings now route through `i18n.tr` with six new `restore_marker.*` keys added to en/zh/ja in lockstep (839→845). JSON key-parity regression guards future drift. Focused: startup-window tests **2 passed**.

## Batch 60 — download/delivery quota consume off the loop (`QUOTA-CONSUME-OFFLOAD-60-01`, fixed-unverified)
All five call sites wrapped: three `downloads.py` paths plus both `delivery.py` consume branches run through `asyncio.to_thread`; `QuotaUnavailableError`→503 and 429 ordering unchanged; `delivery.py` stays within the 350-line budget. One pre-existing contract test updated to its post-batch-60 semantics: file-only batch size estimation must stay on-loop while quota consume intentionally uses a worker (asserted by function name). Focused: **51 passed**. Boundary: shared `to_thread` default executor; no dedicated pool, no latency benchmark.

## Batch 61 — plugin unload in-flight drain (`UNLOAD-DRAIN-BARRIER-61-01`, fixed-unverified)
Per-subscription `Condition` count incremented inside the dispatch path after the active-check; `unregister_plugin` waits up to 1s total across subscriptions with a warn-only timeout, never holding host locks while waiting. Deterministic regressions cover blocked-until-handler-returns (~0.51s) and timeout-return (~1.01s) paths. Focused: **32 passed** including plugin-api-v2 contracts. Boundary: microsecond TOCTOU window between active-check and enter remains (documented); does not touch EventBus public API.

## Batch 62m — client degradation hooks (`WEBUI-DEGRADE-HOOKS-62M-01`, fixed-unverified)
`createApiClient` gains `onRateLimited(path, retryAfterSeconds|null)` and `onServiceUnavailable(path)`; the 429 notify fires after header/body merge so seconds are reliable. No App-level Toast mounted — that UI decision remains open by design. Focused: client/errors suites **23 passed**, typecheck clean; full WebUI run green (one unrelated RealtimeContext flake re-ran clean, no code change between runs).

## Batch 63s — shop update baseline read inside transaction (`SHOP-BASELINE-READ-TXN-63S-01`, fixed-unverified)
`ShopRepository.update_item`'s baseline read (decode+validate) moved into the `shop_item_update` `_transaction` window, closing the cross-thread lost-update TOCTOU documented in deep-weakness-audit §05. Regression uses a gate-probe freeze at `_row_to_dict`: mutant (old shape) fails with title reverted; fixed shape preserves both concurrent writers' fields. Focused: **21 passed**. Boundary: pins single shared-connection serialization only; cross-process is SQLite locking territory.

## Batch 64 — tracker panel refresh signal (`TRACKER-PANEL-REFRESH-64-01`, fixed-unverified)
Module-level `_RefreshSignal(QObject)` with class-attribute Signal; `ImportHook.handle` emits on real changes; panel connects an explicit QueuedConnection slot that rebuilds labels from a fresh locked snapshot, self-heals stale widget teardown. PySide6 present: full worker→emit→pump chain exercised under QCoreApplication. Focused: **6 passed** ×3 stable. Boundaries: merged zero-payload queued emits collapse to one delivery per pump (benign); first-notifier-before-app race can silently skip one refresh (documented).

## Batch 65 — quarantine capacity caps (`QUARANTINE-CAP-LIMITS-65-01`, fixed-unverified)
Within the existing library-lock sweep: active quarantine entries beyond `_QUARANTINE_ACTIVE_MAX=8` fold into `_expired` oldest-first; `_expired` trims oldest past `_EXPIRED_MAX=32` via the sole sanctioned deletion exception (directories only, links refused, failures warn-and-skip). Two regressions cover both gates. Focused: library_service **28 passed**. Agent finding folded in: sweep's `create_missing=False` None-path hardened during implementation.

## Final review
Full Ruff/compileall/governance/diff-check green; WebUI vitest **103 files / 699 tests** + typecheck green. Environment note: three SPA tests failed when `webui/dist/assets` was absent mid-run — rebuilt via `npm run build`, all three pass, confirming environmental rather than code cause. External checkpoint commits continued advancing HEAD during this round (observed `cd34018`, `a6206566`); no commit made by this session.
