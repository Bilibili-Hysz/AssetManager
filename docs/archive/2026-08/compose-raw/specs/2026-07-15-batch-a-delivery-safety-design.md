# Batch A Delivery Safety Design
> **ARCHIVED (2026-08-27)**: 已执行完毕或被后续批次取代,仅追溯用;导航与现行参考见 docs/compose/README.md。

> [!NOTE]
> This document may not reflect the current implementation.
> See the final report for up-to-date state:
> [Final Report](../reports/batch-a-delivery-safety.md)

**Status:** Delivered

## [S1] Purpose and Scope

Batch A makes LAN sharing and the React SPA continuously verifiable, packages the SPA into the Windows bundle, and prevents old library resources from surviving a library switch.

## [S2] Non-Goals

This batch does not introduce SessionDatabase, migrate all raw database connections, redesign desktop UI, refactor Undo/Redo, sandbox plugins, or add signing and installers.

## [S3] CI and Packaging

CI runs WebUI lockfile installation, typecheck, and build. A Windows package smoke builds the SPA before PyInstaller and verifies that the one-directory bundle contains the executable, SPA entry/assets, legacy static files, translations, themes, plugins, and RuntimeData.

## [S4] LAN Browser Authentication

Vite `/assets/*` resources are public so login and share shells bootstrap under LAN authentication. User sessions use the HttpOnly `lan_token` cookie. Password share verification uses a separate scoped HttpOnly cookie; browser responses are token-free, while explicit API-client verification preserves Bearer token issuance.

## [S5] SPA Contract

The browser API client uses same-origin credentials. Batch downloads send JSON and consume a Blob. Share pages derive verified state from the full cookie-authorized info response. API objects, requests, and WebSocket lifecycle are stable across React renders.

## [S6] Library Switch Lifecycle

Switching a library stops LAN sharing, invalidates thumbnail runtime state, closes the previous session, then opens the target session. Thumbnail work captures an immutable generation and rejects stale completion, cache, and repository writes.

## [S7] Delivery Order

Implement and verify the LAN/SPA contract, add release CI, then introduce lifecycle isolation before running the full quality gates.

## [S8] Acceptance Criteria

Authentication cannot block SPA assets; cookies cover browser session flows; package contents are validated; stale thumbnail work cannot affect the next library; and Python/Web quality gates pass.
