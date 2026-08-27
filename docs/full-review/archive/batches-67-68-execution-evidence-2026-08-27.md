# Batch 67–68 Execution Evidence (2026-08-27)

## Batch 67 — WebUI global degradation toasts (`WEBUI-GLOBAL-TOAST-MOUNT-67-01`, fixed-unverified)
New `webui/src/api/degradationBus.ts`: throttled pub/sub bus (10s/kind window, burst-storm default documented as the chosen policy). AuthContext's primary client now wires `onRateLimited/onServiceUnavailable` into the bus; App.tsx mounts `<GlobalApiDegradationToastMount/>` inside `<ToastProvider>` via `useApiDegradationToast()` hook that composes existing i18n keys (`error.rate_limited`/`error.server`) plus `≈Ns` suffix when Retry-After seconds are known. Tests: throttle window + cross-kind isolation regressions inside client.test.ts (**18 passed** there; full WebUI **701 passed**, typecheck clean at implementation time).

## Batch 68 — Shop optimistic-concurrency guard (`SHOP-OPTIMISTIC-UPDATEDAT-68-01`, fixed-unverified)
`ShopRepository.update_item` gains keyword-only `expected_updated_at`; mismatch raises `ShopItemVersionConflictError` (subclass of `OperationNotPermitted`, code `shop_item_version_conflict`, mapped to HTTP 409 by the canonical error contract). Service forwards an optional token read from the update payload; routes need no change since the body flows through. Callers omitting the token keep legacy semantics. Uses the existing `updated_at` column — no schema migration, no If-Match header contract; a formal version-column design remains available if product later wants explicit conflict payloads. Tests: stale-token conflict / fresh-token success / legacy no-token unchanged / error shape — commerce services suite **44 passed** with delivery-route subset.

## Final-review snapshot (honest attribution)

- Full serial Python at that byte-state was archived as **4128 passed** (`artifacts/evidence/2026-08-27/full-57-63.stdout.log`) BEFORE the user's unrelated in-progress GL feature stabilized.
- A subsequent suite attempt recorded 12 failed + 231 desktop collection **errors** rooted exclusively in the untracked `AssetsManager/background/gl/surface.py` importing `QOpenGLTexture` from `PySide6.QtGui` — an import that fails under installed PySide6 6.11 — landing/edited *during* collection. Those files belong to the user's separate `background/gl` workstream (design doc commit `fd22383`), not to batches 57–68; one mechanical Ruff F401 auto-fix applied to that untracked tree is disclosed here.
- Independent audit validator: **valid (90)** including this report.
