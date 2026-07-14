# Anchor Worktree Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the current audited worktree into a reproducible Git anchor without deleting project source or local working files.

**Architecture:** Preserve all tracked changes and project-owned untracked files in one baseline commit. Expand `.gitignore` only for reproducible dependencies, generated outputs, local tooling directories, Cython intermediates, and the downloadable Cloudflare binary; then verify the Python and React applications before committing and tagging the baseline.

**Tech Stack:** Git, Python/PySide6, pytest, Ruff, Pyright, React, TypeScript, Vite.

## Global Constraints

- Do not use destructive Git commands or delete current worktree files.
- Keep application source, tests, documentation, plugin sources, CI files, and `webui` source under version control.
- Exclude `webui/node_modules/`, generated TypeScript build metadata, Cython C extension intermediates, local MiMoCode/OpenCode dependencies, packaging outputs, and `cloudflared-windows-amd64.exe`.
- Preserve the existing `webui/dist/` ignore rule because Vite regenerates it from tracked source.
- Establish the anchor only after the applicable verification commands have completed.

---

### Task 1: Define the Version-Control Boundary

**Files:**
- Modify: `.gitignore`
- Verify: `git check-ignore -v <candidate paths>`

**Interfaces:**
- Consumes: The current project-owned files and reproducible local artifacts identified by the audit.
- Produces: Ignore rules that leave only source-controlled project files in `git status`.

- [ ] **Step 1: Add targeted ignore rules**

Append these entries to `.gitignore` without changing existing rules:

```gitignore
# Local agent tooling dependencies.
.mimocode/node_modules/
.opencode/node_modules/

# React/Vite local dependencies and generated metadata.
/webui/node_modules/
/webui/tsconfig.tsbuildinfo

# Cython generated extension sources and binaries.
AssetsManager/application/asset_filters.c
AssetsManager/core/cache.c
AssetsManager/core/color_utils.c
AssetsManager/core/format_utils.c
*.pyd

# Downloaded Cloudflare Tunnel executable.
/cloudflared-windows-amd64.exe
```

- [ ] **Step 2: Verify each excluded category is ignored**

Run:

```powershell
git check-ignore -v webui/node_modules/react/index.js webui/tsconfig.tsbuildinfo AssetsManager/core/cache.c cloudflared-windows-amd64.exe
```

Expected: each path reports the corresponding `.gitignore` rule.

- [ ] **Step 3: Verify project source remains eligible for tracking**

Run:

```powershell
git check-ignore -v AssetsManager/app.py webui/src/App.tsx
```

Expected: no output and a non-zero exit status because neither source file is ignored.

### Task 2: Verify and Establish the Anchor

**Files:**
- Modify: all tracked and non-ignored project files currently shown by `git status`
- Create: Git commit and annotated tag `baseline-2026-07-15`

**Interfaces:**
- Consumes: the ignore boundary from Task 1 and the current worktree as the intended baseline.
- Produces: one committed, tagged, auditable baseline with no remaining source changes.

- [ ] **Step 1: Run Python quality checks**

Run:

```powershell
python -m ruff check . --exclude ".Cython&Noikta"
python -m pyright
python -m compileall AssetsManager -q
python -m pytest -q
```

Expected: each command completes successfully; record exact failures if the pre-existing worktree does not meet the documented baseline.

- [ ] **Step 2: Run Web UI validation**

Run from `webui/`:

```powershell
npm run typecheck
npm run build
```

Expected: TypeScript validation and Vite production build complete successfully.

- [ ] **Step 3: Stage only the intended anchor files**

Run:

```powershell
git add -A
git status --short
```

Expected: staging contains source, tests, docs, configuration, plugins, and `webui` source; no `node_modules`, Cython `.c` files, `dist`, `tsbuildinfo`, or Cloudflare executable appears.

- [ ] **Step 4: Create the anchor commit**

Run:

```powershell
git commit -m "chore: establish audited application baseline"
```

Expected: a new commit records the full audited project state.

- [ ] **Step 5: Tag and confirm the clean baseline**

Run:

```powershell
git tag -a baseline-2026-07-15 -m "Audited AssetManager application baseline"
git status --short --branch
git show --stat --oneline HEAD
```

Expected: the branch has no worktree changes and the tag resolves to the new anchor commit.
