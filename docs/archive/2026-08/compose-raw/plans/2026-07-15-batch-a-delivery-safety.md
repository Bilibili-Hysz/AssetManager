# Batch A Delivery Safety Implementation Plan
> **ARCHIVED (2026-08-27)**: 已执行完毕或被后续批次取代,仅追溯用;导航与现行参考见 docs/compose/README.md。

> [!NOTE]
> This document may not reflect the current implementation.
> See the final report for up-to-date state:
> [Final Report](../reports/batch-a-delivery-safety.md)

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver verified LAN SPA release safety and library-switch resource isolation.

**Architecture:** Keep browser credentials in cookies, validate both SPA and frozen package outputs, and use thumbnail runtime generations to reject stale work.

**Tech Stack:** aiohttp, PySide6, React, TypeScript, Vite, GitHub Actions, PyInstaller.

## Global Constraints

- Preserve existing LAN authorization and path-containment protections.
- Do not store new browser authentication tokens in URLs or browser storage.
- Keep the implementation limited to Batch A release and lifecycle concerns.

---

### Task 1: LAN SPA Browser Contract

**Covers:** [S1, S4, S5, S8]

- [x] Make SPA assets public under authentication.
- [x] Use cookie-backed browser sessions and scoped share cookies, while retaining explicit API-client Bearer issuance.
- [x] Send batch downloads as JSON and stabilize React API, request, and WebSocket lifecycles.
- [x] Add LAN regression coverage and run LAN/Web gates.

### Task 2: Web and Windows Package CI

**Covers:** [S1, S3, S8]

- [x] Add WebUI typecheck/build CI.
- [x] Package `webui/dist` in PyInstaller.
- [x] Add Windows package-content smoke and focused checker tests.

### Task 3: Library Switch Safety

**Covers:** [S1, S2, S6, S8]

- [x] Stop active LAN sharing before closing a library session.
- [x] Invalidate thumbnail generation, cache, failure, queue, and repository work before the switch.
- [x] Add switch-order and stale-task tests.

### Task 4: Acceptance Gates

**Covers:** [S1, S3, S4, S5, S6, S8]

- [x] Run Ruff, Pyright, compileall, and full Python tests.
- [x] Run locked WebUI typecheck and build.
- [x] Run a PyInstaller one-directory build and package-content checker.
