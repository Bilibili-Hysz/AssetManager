# Shop Partial Update Metadata Preservation Evidence (2026-08-26)

## Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `shop-partial-metadata-preservation-evidence-2026-08-26` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; bounded commerce partial-update metadata preservation batch |
| Baseline status SHA-256 | `21a02c322b14610ecc5f0e02e804625451268025e54bdd83932b33d6301be7d7` |
| Baseline diff SHA-256 | `50287335149b02f72ee4f5d5eefdaa5bf8790528a3717b83c1272aa1c2735fba` |
| Baseline tracked / untracked entries | `160 / 146` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This append-only snapshot records the fix for confirmed commerce data loss in `ShopService.update_item()`. The machine-readable companion is [audit-manifest-shop-partial-metadata-preservation-evidence-2026-08-26.json](audit-manifest-shop-partial-metadata-preservation-evidence-2026-08-26.json).

## Implemented contract

Partial updates now assemble metadata from the persisted record instead of rebuilding it from the payload alone. `update_item()` shallow-copies the current metadata, overlays an explicitly supplied `metadata` mapping, and applies a normalized `status` overlay when one is supplied. When `gallery_paths` is present, only the reserved `image_paths` slot is replaced on that merged dictionary, after gallery authorization validation.

This closes the previously destructive combinations: status-only updates no longer erase arbitrary metadata or the gallery, metadata-only updates no longer drop omitted keys (including stored status), and combined status/metadata/gallery payloads apply in a deterministic order instead of overwriting each other. Intentional replacement semantics are preserved: `gallery_paths=[]` clears only the gallery, `ShopRepository.update_item()` remains a full-metadata-value persistence contract, routes remain pass-through, public serialization still strips `image_paths`, and events/index behavior is unchanged. The merge is shallow with no concurrency/CAS guarantee for simultaneous seller updates.

## Verification

### Focused commerce matrix

```text
python -m pytest -n 0 -q tests/unit/test_commerce_services.py tests/unit/test_commerce_repositories.py tests/lan/test_commerce_routes.py tests/lan/test_order_receipt_routes.py
```

Result: **67 passed**, exit code 0. Raw output: `artifacts/evidence/2026-08-26/shop-metadata-preservation/focused.stdout.log`.

New service regressions cover: status-only update preserving arbitrary metadata and gallery while applying draft status; metadata-only shallow merge preserving unrelated keys and stored state without inventing status; and combined status+metadata+gallery update preserving unrelated metadata, applying archived status, and replacing only the gallery — each reloaded through `get_item()` to prove persistence.

### Full Python suite

```text
python -m pytest -n 0 -q
```

Result: **4058 passed, 16 skipped, 20 deselected, 2 warnings**, exit code 0, 631.88 seconds. Raw output: `artifacts/evidence/2026-08-26/shop-metadata-preservation/full.stdout.log`.

Skips remain capability/platform-gated (Windows symlink privilege, POSIX flock recovery, nondeterministic Windows queue termination). The two warnings are the pre-existing Qt signal disconnect and duplicate ZIP member warnings.

### Static and repository gates

Targeted Ruff, full Ruff, targeted compileall, full compileall, `git diff --check`, and the six repository governance scripts all exited 0; outputs live under `artifacts/evidence/2026-08-26/shop-metadata-preservation/`. The independent audit-manifest validator runs after this report/manifest/index are written and its result is retained separately.

## Finding and boundaries

- `SHOP-PARTIAL-METADATA-PRESERVATION-34-01` is **fixed-unverified**. The tested preservation matrix and the full serial suite pass on Windows. Status remains conservative: no concurrent-seller-update race test, no production E2E/browser run, no cross-system atomicity/power-loss/exactly-once claim, no dependency/CVE/release/clean-checkout verification.
- Read-only inspection additionally documented adjacent behaviors intentionally left unchanged: create-time `image_paths` overwrite by validated gallery, malformed stored JSON normalizing to `{}` on next write, and the frontend `ShopItemPayload` type not declaring `metadata`. These are separate contract decisions, not part of this batch.

The frozen `DeepSeek Docs/` directory and ignored `.worktrees/grid-zoom-interpolation-fix` directory were not modified. No commit, push, release, revert, reset, clean, or dirty-worktree overwrite was performed.
