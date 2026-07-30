# WebUI Dependency Security Upgrade Implementation Plan

> [!NOTE]
> This document may not reflect the current implementation.
> See the final report for up-to-date state:
> [Final Report](../reports/webui-dependency-security-upgrade.md)

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate all currently reported WebUI npm vulnerabilities while preserving React 18 application behavior and the existing LAN SPA contract.

**Architecture:** Upgrade only the affected runtime router and development toolchain to their current secure majors, then make the smallest compatibility edits proven necessary by typecheck, tests, and build output. Keep React, Tailwind, application state, routes, styling, and Python LAN behavior unchanged.

**Tech Stack:** React 18, React Router 7, Vite 7, Vitest 3, TypeScript, npm lockfile, Chromium acceptance.

## Global Constraints

- Preserve the dirty worktree and all unrelated changes; do not stage, commit, reset, checkout, clean, or upgrade unrelated packages.
- Dependency scope is limited to `react-router-dom`, `vite`, `vitest`, `@vitejs/plugin-react`, and lockfile-resolved transitive dependencies required by them.
- Do not upgrade React 18, React DOM 18, Tailwind 3, TypeScript, lucide, jsdom, or unrelated test libraries.
- Do not migrate to data routers, SSR, React 19, Tailwind 4, or new product behavior.
- The final `npm audit --json` result must report zero vulnerabilities outside the explicitly approved, unreachable React Router RSC-mode advisory documented in the final report.
- Existing WebUI typecheck, full Vitest suite, production build, Python LAN SPA contracts, and real Chromium acceptance must pass.

---

### Task 1: Upgrade the secure dependency baseline

**Files:**
- Modify: `webui/package.json`
- Modify: `webui/package-lock.json`

**Interfaces:**
- Consumes: current npm audit evidence, Node `v24.14.0`, existing React 18 declarative router and Vite/Vitest configuration.
- Produces: a reproducible lockfile with React Router DOM `7.18.2`, Vite `7.3.6`, Vitest `3.2.6`, and `@vitejs/plugin-react` `5.2.0`, with only the approved React Router RSC-mode advisory remaining.

- [x] Record RED with `npm audit --json`: the initial audit reported 7 vulnerabilities, including the React Router open-redirect/XSS advisories, Vite Windows path bypass, and Vitest UI arbitrary file read/execute advisory.
- [ ] Run an explicit scoped install from `webui/`:

```powershell
npm install react-router-dom@7.18.2 --save-exact
npm install vite@7.3.6 vitest@3.2.6 @vitejs/plugin-react@5.2.0 --save-dev --save-exact
```

Do not use `npm audit fix --force`; it obscures the intended version boundary and may upgrade unrelated dependencies.

- [ ] Add a `package.json` Node engine compatible with the selected Vite version only if required by package metadata. Use the actual Vite engine floor; do not require the local Node 24 version.
- [x] Run `npm audit --json` and verify that only the approved React Router RSC-mode advisory remains. Inspect `git diff -- webui/package.json webui/package-lock.json` to ensure no unrelated top-level dependency changed.

### Task 2: Apply only evidence-driven Router/toolchain compatibility fixes

**Files:**
- Modify only failing WebUI source/config/test files demonstrated by Task 1 commands.
- Test: existing `webui/src/**/*.test.ts(x)` suite.

**Interfaces:**
- Consumes: the secure dependency baseline from Task 1.
- Produces: the same declarative SPA routes, auth behavior, realtime behavior, tests, and production build under Router 7/Vite 7/Vitest 3.

- [ ] Run RED compatibility gates independently:

```powershell
npm run typecheck
npm test
npm run build
```

Record every failure before editing code. A passing gate requires no compatibility edit.

- [ ] For each actual failure, make the smallest supported-API change. Preserve route paths and components. Remove obsolete Router future flags only if Router 7 reports them invalid; do not adopt data-router APIs.
- [x] If Vitest 3 changes mock/timer or environment behavior, update only tests/config that fail. Do not weaken assertions, add broad timeouts, or skip tests.
- [ ] Re-run typecheck, full Vitest, and production build until all pass with no Router future-flag warnings introduced by obsolete configuration.

### Task 3: Cross-surface security and release verification

**Files:**
- Test only unless a gate demonstrates a scoped compatibility defect.

**Interfaces:**
- Consumes: the secure WebUI build output.
- Produces: evidence that the dependency upgrade did not break Python LAN SPA serving or real browser behavior.

- [x] Run `npm audit --json` again: 2 high findings remain, both the approved React Router RSC-mode advisory; no Vite or Vitest findings remain.
- [ ] Run Python LAN page/build/public-contract tests that verify the generated SPA paths and assets.
- [ ] Run the real Chromium realtime acceptance suite.
- [ ] Run `git diff --check -- webui/package.json webui/package-lock.json` plus every compatibility file changed in Task 2.
- [x] Perform an independent security/compatibility review of package scope, audit evidence, Router navigation, Vite build output, Vitest assertions, and real browser acceptance. No P0/P1/P2 finding remains.
