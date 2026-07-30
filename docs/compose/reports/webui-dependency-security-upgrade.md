---
feature: webui-dependency-security-upgrade
status: delivered
specs: []
plans:
  - docs/compose/plans/2026-07-21-webui-dependency-security-upgrade.md
branch: master
commits: 4afd851..HEAD
---

# WebUI Dependency Security Upgrade — Final Report

## What Was Built

The LAN WebUI now uses the React Router 7 declarative SPA package, Vite 7, Vitest 3, and the matching React Vite plugin versions. React 18, the existing route paths, the LAN API shape, and the current application behavior remain unchanged. The lockfile records the exact direct toolchain versions and the transitive packages selected by npm.

The WebUI test command also works from this repository's Windows path, whose `~` segment causes Vitest's worker/runtime path handling to fail when launched directly. `webui/scripts/run-vitest.mjs` maps the repository parent to an available drive letter for the duration of the run, forwards Vitest arguments and exit status, and removes the mapping even when Vitest fails. Vite preserves symlink paths so the mapped execution environment resolves the same source tree.

## Architecture

The production application remains a React 18 declarative SPA. `webui/src/App.tsx` continues to own `BrowserRouter` and route declarations; no data-router, SSR, RSC, or action-handler path is introduced. The dependency boundary is expressed in `webui/package.json` and `webui/package-lock.json`:

- `react-router-dom`: `7.18.2` with matching `react-router`.
- `vite`: `7.3.6`.
- `vitest`: `3.2.6`.
- `@vitejs/plugin-react`: `5.2.0`.
- Node engine: `^20.19.0 || >=22.12.0`, matching the selected Vite/plugin runtime floor.

The test wrapper is the only Windows-specific execution adapter. It uses `subst.exe` only when the current project path contains a path character known to break the Vitest execution path, runs the local `vitest.mjs` from the mapped `webui` directory, and cleans up the temporary mapping before returning the child status.

### Design Decisions

We chose exact versions for the affected top-level packages because reproducible toolchain boundaries make security review and future upgrades auditable. React, React DOM, Tailwind, TypeScript, lucide, jsdom, and unrelated testing libraries remain at their existing major versions.

We retained React Router 7.18.2 because it is the available `react-router-dom` release compatible with this SPA. The approved exception is advisory `GHSA-qwww-vcr4-c8h2` (npm source `1124282`), which affects React Router RSC mode. It is limited to unstable RSC APIs, while this application uses `ReactDOM.createRoot` and declarative `BrowserRouter`/`Routes` without RSC or SSR. The exception is therefore approved as unreachable for this application rather than addressed with an unsupported package override.

## Usage

From `webui/`, use the existing commands:

```powershell
npm run typecheck
npm test
npm run build
```

On Windows, `npm test` automatically applies the temporary drive mapping when the repository path requires it. The application is still built and served as the same root-based SPA, so LAN packaging and page-serving code require no alternate asset path.

## Verification

Fresh verification for this delivery produced:

- WebUI typecheck: passed.
- WebUI Vitest: `34/34` test files and `256/256` tests passed.
- WebUI production build: passed; Vite transformed `1631` modules.
- LAN suite: `330 passed`.
- SPA/public-contract and packaging subset: `8 passed`.
- Real Chromium realtime acceptance: `4 passed`.
- Full Python suite: `1519 passed, 1 skipped`; the skip is the platform-specific directory-symlink case on Windows.
- `npm audit --json`: `2` high findings, both the same approved React Router RSC-mode advisory (`GHSA-qwww-vcr4-c8h2`, source `1124282`) described above; no Vite or Vitest findings remain. The report intentionally does not claim a literal zero-vulnerability audit result because this approved exception remains in the resolved React Router package range.

The repository-wide Ruff and Pyright commands were also run. They still report one unused import and 35 type errors in the broader accumulated working-tree changes; those diagnostics are outside the T494 dependency/toolchain compatibility files and were not changed as part of this security upgrade.

## Journey Log

> Brief notes on what informed the final design. Not required reading.

- [pivot] Direct Vitest execution failed on the repository's Windows path because the `~` segment propagated into worker/runtime paths. A temporary drive mapping keeps the workaround local to the test launcher.
- [lesson] A passing build and browser acceptance do not make `npm audit` literally zero when the remaining advisory targets an unused execution mode. The affected mode must be checked against the actual application architecture and recorded explicitly.
- [lesson] The LAN suite is most reliable when run sequentially after the WebUI build; concurrent heavy gates can expose load-sensitive test timing without reproducing a production lifecycle defect.

## Source Materials

| File | Role | Notes |
|------|------|-------|
| `docs/compose/plans/2026-07-21-webui-dependency-security-upgrade.md` | Implementation plan | Scope and acceptance criteria; current implementation and audit exception are recorded here by reference to this report. |
| `webui/package.json` | Direct dependency contract | Exact router/toolchain versions, Node engine, and test wrapper command. |
| `webui/package-lock.json` | Reproducible dependency graph | Resolved direct and transitive package versions. |
| `webui/scripts/run-vitest.mjs` | Windows test adapter | Drive mapping, argument forwarding, exit propagation, and cleanup. |
| `webui/vite.config.ts` | Build/test configuration | Symlink preservation required by the mapped Windows test path. |
| `tests/e2e/test_webui_realtime_acceptance.py` | Browser acceptance | Real Chromium validation of the LAN realtime surface. |
