# Public Theme Setter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the existing shared theme setter through `useTheme()` so consumers can explicitly select a theme.

**Architecture:** Preserve the module-level theme store as the single source of truth. The hook will return the existing `setTheme(theme)` function alongside its current `theme` snapshot and `toggleTheme()` command; no new state, storage key, or consumer abstraction is introduced.

**Tech Stack:** React 18, TypeScript, Vitest, Testing Library.

## Global Constraints

- Preserve the existing `am_theme` storage behavior, legacy-key migration, system-theme fallback, document synchronization, and cross-consumer notifications.
- Do not change theme styling, LandingPage, or other consumers for this contract-only task.
- Do not commit, create a branch, or overwrite unrelated dirty-worktree changes.

---

### Task 1: Expose the Shared Theme Setter

**Covers:** Approved design: `useTheme(): { theme; toggleTheme; setTheme }` exposes the existing setter and proves explicit selection reaches all shared outputs.

**Files:**
- Modify: `webui/src/hooks/useTheme.ts`
- Modify: `webui/src/hooks/useTheme.test.tsx`

**Interfaces:**
- Consumes: module-level `setTheme(theme: Theme): void`.
- Produces: `useTheme(): { theme: Theme; toggleTheme: () => void; setTheme: (theme: Theme) => void }`.

- [x] **Step 1: Write the failing public-contract test**

Add a hook test that invokes `result.current.setTheme('light')` and asserts the returned `theme`, `localStorage['am_theme']`, and `document.documentElement.dataset.theme` are all `light`.

```tsx
act(() => result.current.setTheme('light'));

expect(result.current.theme).toBe('light');
expect(localStorage.getItem('am_theme')).toBe('light');
expect(document.documentElement.dataset.theme).toBe('light');
```

- [x] **Step 2: Verify RED**

Run: `npm --prefix webui test -- --run src/hooks/useTheme.test.tsx`

Expected: the new test fails because `setTheme` is absent from the hook return value.

- [x] **Step 3: Return the existing setter from the hook**

Change only the hook return object:

```ts
return { theme, toggleTheme, setTheme };
```

- [x] **Step 4: Verify GREEN and type safety**

Run: `npm --prefix webui test -- --run src/hooks/useTheme.test.tsx`

Run: `npm --prefix webui run typecheck`

Expected: the focused hook suite and TypeScript typecheck pass.

- [x] **Step 5: Review scope**

Run: `git diff --check -- webui/src/hooks/useTheme.ts webui/src/hooks/useTheme.test.tsx`

Expected: only the public hook return contract and its focused regression test change; no whitespace errors.
