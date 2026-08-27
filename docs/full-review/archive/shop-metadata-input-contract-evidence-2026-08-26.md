# Shop Metadata Input Contract Evidence (2026-08-26)

## Scope
Finding `SHOP-METADATA-INPUT-CONTRACT-42-01` covered create-time metadata allowing callers to write the internal `metadata.image_paths` gallery slot directly and the frontend payload type omitting metadata.

## Changes
- `ShopService._fields()` removes reserved `image_paths` from public metadata input; normalized `gallery_paths` remains the sole source for that internal slot.
- `ShopItemPayload.metadata` is now declared as an optional `Record<string, unknown>`.
- Python and TypeScript contract tests cover create/update payloads, normalized gallery behavior, and public serialization.

## Verification
- Commerce/recovery Python focused matrix: **41 passed, 31 deselected**.
- Frontend Shop/public contract tests: **24 passed**.
- Final serial Python suite: **4089 passed, 16 skipped, 20 deselected, 2 warnings**, exit code 0.
- Full Ruff, compileall, diff-check, and repository governance gates passed.

## Boundaries
Status is `fixed-unverified`: metadata merge remains shallow, concurrent seller updates still have no CAS contract, and no production browser or external storage test was run. Internal gallery storage remains an implementation detail and is removed from public metadata.
