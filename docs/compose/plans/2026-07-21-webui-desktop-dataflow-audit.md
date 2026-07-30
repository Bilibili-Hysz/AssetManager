# WebUI and Desktop Dataflow Audit Plan

> [!NOTE]
> This document may not reflect the current implementation.
> See the final report for up-to-date state:
> [Final Report](../reports/webui-desktop-dataflow-audit.md)

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce an evidence-backed audit of information and data flow between the desktop application, shared application layer, LAN server, and React WebUI.

**Architecture:** Trace each user-visible domain flow from its source of truth through controllers/services, LAN serialization and transport, React API/hooks/state, and rendered consumers. Compare desktop and WebUI behavior at shared boundaries rather than assuming one UI directly controls the other.

**Tech Stack:** Python/PySide6 desktop application, application services and repositories, aiohttp LAN API/WebSocket, React 18/TypeScript WebUI, pytest, Vitest.

## Global Constraints

- This is a read-only audit; do not modify production implementation.
- Preserve all existing uncommitted changes.
- Every actionable finding must include severity, user impact, root cause, and navigable file:line evidence.
- Distinguish confirmed defects from architectural risks and test gaps.
- Trace authorization, library/session identity, path encoding, freshness/invalidation, serialization, and UI state ownership.
- Cover projects/files, metadata/tags/notes/URLs, thumbnails/previews, search/tree/navigation, downloads/shares, authentication/permissions, server lifecycle, and WebSocket refresh signals.
- Save the final audit to `docs/compose/reports/2026-07-21-webui-desktop-dataflow-audit.md`.

---

### Task 1: Map runtime boundaries and sources of truth

**Files:**
- Inspect: `AssetsManager/app.py`, `main_window.py`, `application/`, `controllers/`, `lan/server.py`, `lan/api.py`, `webui/src/App.tsx`, `webui/src/stores/`, `webui/src/hooks/`.

- [ ] Map desktop startup/library-session ownership and LAN server bootstrap.
- [ ] Map React bootstrap/auth/API ownership and static asset serving.
- [ ] Identify shared services/repositories versus duplicated UI logic.

### Task 2: Trace domain flows end to end

**Files:**
- Inspect: desktop panels/controllers, application services/repositories, LAN routes/security, WebUI APIs/hooks/pages/components, related tests.

- [ ] Trace files/projects/tree/search and navigation semantics.
- [ ] Trace metadata/tags/notes/URLs and mutation invalidation.
- [ ] Trace thumbnails/project previews/ImageViewer payloads and permissions.
- [ ] Trace downloads/shares/authentication and capability enforcement.
- [ ] Trace WebSocket events and server/library lifecycle changes.

### Task 3: Validate contracts and classify findings

**Files:**
- Inspect: `tests/lan/`, `tests/integration/`, `tests/desktop/`, `webui/src/**/*.test.*`, API TypeScript types and Python response dataclasses.

- [ ] Compare Python response shapes with TypeScript interfaces and consumers.
- [ ] Check stale-request, library-switch, reconnect, permission, path-encoding, and partial-failure behavior.
- [ ] Run narrow read-only contract tests where necessary to confirm or reject suspected defects.
- [ ] Classify findings as confirmed defect, architecture risk, or coverage gap.

### Task 4: Write and review the audit report

**Files:**
- Create: `docs/compose/reports/2026-07-21-webui-desktop-dataflow-audit.md`.

- [ ] Lead with actionable findings ordered P0–P3.
- [ ] Include a compact cross-runtime flow map and source-of-truth matrix.
- [ ] Document verified strengths and invariants separately from defects.
- [ ] Provide a prioritized remediation sequence without changing code.
- [ ] Run `git diff --check` on the report and verify all cited paths/lines exist.
