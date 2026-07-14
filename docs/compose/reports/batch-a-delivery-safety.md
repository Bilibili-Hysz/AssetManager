---
feature: batch-a-delivery-safety
status: delivered
specs:
  - docs/compose/specs/2026-07-15-batch-a-delivery-safety-design.md
plans:
  - docs/compose/plans/2026-07-15-batch-a-delivery-safety.md
branch: batch-a-delivery-safety
commits: 5f84b4d..uncommitted
---

# Batch A Delivery Safety - Final Report

## What Was Built

Batch A makes the active LAN React SPA usable under authentication, adds reproducible WebUI and Windows packaging gates, and prevents old LAN or thumbnail work from outliving a library switch. The packaged one-directory application now includes the Vite build and validates its hashed asset references.

The browser uses cookie-backed sessions for APIs, previews, native downloads, and WebSockets. Password-protected shares receive a share-scoped HttpOnly cookie; browser verification stays token-free, while an explicit API-client header retains the legacy Bearer-token flow for non-browser clients.

## Architecture

`AssetsManager/lan/server.py` treats `/assets` as a public prefix while retaining authentication for protected routes. `AssetsManager/lan/routes/shares.py` isolates password-share credentials per share, and `webui/src/api/client.ts` sends same-origin cookies and exposes Blob downloads for JSON batch requests.

`AssetManager.spec` includes `webui/dist`; `.github/workflows/ci.yml` adds a WebUI job and a Windows PyInstaller content-smoke job. `scripts/check_package_contents.py` validates the executable, package resources, and every Vite asset referenced by the SPA index.

`MainWindow._on_switch_library()` stops LAN sharing and invalidates the thumbnail runtime before closing the old session. `ThumbnailLoader` captures a runtime generation for load, bake, cache, and repository paths, rejecting stale work and clearing old in-memory state on invalidation.

### Design Decisions

Cookie credentials were chosen for browser-native downloads and image previews because headers cannot be attached to those navigations. The separate share cookie limits password-share credentials to a single share route.

Explicit API-client token issuance was retained because accepting Bearer credentials alone does not preserve external client compatibility when browsers receive HttpOnly cookies.

Generation-based invalidation was chosen over a broad session abstraction because it addresses cross-library worker side effects without expanding Batch A into a database lifecycle redesign.

## Usage

CI automatically runs the WebUI build and Windows package smoke for pushes and pull requests. Locally, run:

```powershell
cd webui
npm ci
npm run typecheck
npm run build
cd ..
python -m PyInstaller AssetManager.spec --noconfirm --clean
python scripts/check_package_contents.py dist/AssetManager
```

Browser share clients verify a password normally and rely on the scoped cookie. Non-browser clients that need a Bearer token send `X-AssetsManager-API-Client: 1` to the password verification endpoint, then use the returned token in `Authorization: Bearer <token>`.

## Verification

Fresh final verification completed successfully:

- `python -m ruff check . --exclude ".Cython&Noikta"`: passed.
- `python -m pyright`: `0 errors, 0 warnings`.
- `python -m compileall AssetsManager -q`: passed.
- `python -m pytest -q`: `757 passed`.
- `npm ci && npm run typecheck && npm run build` in `webui/`: passed.
- `python -m PyInstaller AssetManager.spec --noconfirm --clean` followed by `python scripts/check_package_contents.py dist/AssetManager`: passed on the first sequential package run.

Focused regression coverage includes authenticated SPA assets, sanitized and cookie-authorized share info, explicit API-client Bearer issuance, JSON batch downloads, package resource validation, thumbnail stale-work rejection, and switch order.

## Journey Log

> Brief notes on what informed the final design. Not required reading.

- [lesson] Registering a public static route does not bypass authentication middleware; the middleware prefix policy must change too.
- [pivot] Password-share cookies replaced browser-exposed tokens, with explicit opt-in token issuance retaining API compatibility.
- [lesson] Vite output must be built and packaged sequentially; concurrent builds can invalidate hash-based package checks.
- [lesson] Task cancellation alone is insufficient for library switching; stale cache and failure state must be cleared with generation invalidation.

## Source Materials

| File | Role | Notes |
|---|---|---|
| `docs/compose/specs/2026-07-15-batch-a-delivery-safety-design.md` | Batch design | Delivered scope and acceptance criteria. |
| `docs/compose/plans/2026-07-15-batch-a-delivery-safety.md` | Implementation plan | Completed task record. |
