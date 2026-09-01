# Cookie-Only SPA Authentication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the LAN authentication credential from React state while preserving Cookie-based login, visible public identity, and server compatibility.

**Architecture:** The aiohttp server continues setting the HttpOnly `lan_token` cookie and retains its JSON token response for non-browser compatibility. The React SPA ignores that token and manages only public user, role, and permission data. Flows without a returned user use cookie-authenticated `/api/auth/me` before navigation.

**Tech Stack:** React 18, TypeScript, Vitest, React Testing Library, aiohttp, pytest.

## Global Constraints

- Do not modify `AssetsManager/lan/routes/auth.py`, cookie flags, auth middleware, or WebSocket behavior.
- Do not store credentials in React state, Context, localStorage, sessionStorage, or another browser-readable cache.
- Retain `credentials: "same-origin"` in `webui/src/api/client.ts`.
- Preserve existing external JSON token response compatibility.
- Do not change dependencies or lockfiles.

---

### Task 1: Remove Browser Credential State

**Covers:** [S1, S2, S3, S4, S5, S6]

**Files:**
- Modify: `webui/src/stores/AuthContext.tsx`
- Modify: `webui/src/stores/AuthContext.test.tsx`
- Modify: `webui/src/pages/LoginPage.tsx`
- Modify: `webui/src/pages/LoginPage.test.tsx`
- Test: `tests/lan/test_lan_api.py`
- Test: `tests/lan/test_path_guard.py`
- Test: `tests/lan/test_t2_t4_contracts.py`

**Interfaces:**
- Consumes: `AuthApi.me(): Promise<MeResponse>`, `LoginResponse` with optional public `user`, and the HttpOnly cookie sent by `createApiClient()`.
- Produces: `AuthContextValue.setSessionUser(user?: User | null): void` with no `token` field; login handlers that ignore `LoginResponse.token`.

- [ ] **Step 1: Replace the token-retention test with a public-session test**

In `webui/src/stores/AuthContext.test.tsx`, replace the test that calls `setToken('session-token', user)` with:

```ts
it('retains only public user state after session setup', async () => {
  const { result } = renderHook(() => useAuthContext(), { wrapper: AuthProvider });
  await waitFor(() => expect(result.current.isLoading).toBe(false));

  result.current.setSessionUser({
    id: 1,
    username: 'member',
    role: 'user',
    active: true,
    created_at: '2026-07-15T00:00:00Z',
  });

  await waitFor(() => expect(result.current.user?.username).toBe('member'));
  expect(result.current.role).toBe('user');
  expect(result.current.permissions).toEqual(['browse', 'download', 'preview']);
  expect('token' in result.current).toBe(false);
});
```

- [ ] **Step 2: Run the AuthContext test to verify the current interface fails**

Run from `webui/`:

```powershell
npm test -- --run src/stores/AuthContext.test.tsx
```

Expected: FAIL because `setSessionUser` does not exist and the current context still exposes `token`.

- [ ] **Step 3: Replace token state with public session state**

In `AuthContext.tsx`:

```ts
export interface AuthContextValue extends AuthState {
  api: ApiClient;
  authApi: AuthApi;
  systemApi: SystemApi;
  setSessionUser: (user?: User | null) => void;
  logout: () => void;
  refreshMe: () => Promise<void>;
}
```

Remove `token` from `AuthState`, remove `setTokenState`, and implement:

```ts
const setSessionUser = useCallback((nextUser?: User | null) => {
  if (nextUser) {
    setUser(nextUser);
    setRole(nextUser.role === 'admin' ? 'admin' : 'user');
    setPermissions(
      nextUser.role === 'admin'
        ? ['browse', 'download', 'upload', 'manage_links', 'manage_users', 'settings', 'preview']
        : ['browse', 'download', 'preview'],
    );
    return;
  }
  setUser(null);
  setRole('guest');
  setPermissions(['browse', 'preview']);
}, []);
```

Use `setSessionUser()` in `logout()`. Update unauthorized handling to reset only public state.

- [ ] **Step 4: Make every LoginPage success flow ignore the token**

Replace login and registration success handling with:

```ts
setSessionUser(res.user);
navigate('/');
```

For password-only and key login, use:

```ts
await refreshMe();
navigate('/');
```

Update `useAuth()` consumption to obtain `setSessionUser` and `refreshMe`. Do not reference `res.token` in `LoginPage.tsx`.

- [ ] **Step 5: Add LoginPage behavior tests for token ignorance and cookie restore**

Mock `authApi.loginWithPassword` and `authApi.verifyKey` to resolve with `{ token: 'server-token' }`. Assert each handler calls `refreshMe()` and navigates, without a token setter. Mock user login/registration with `{ token: 'server-token', user }` and assert `setSessionUser(user)` is called. The test must never expose or assert `server-token` through context state.

- [ ] **Step 6: Run focused frontend tests**

Run from `webui/`:

```powershell
npm test -- --run src/stores/AuthContext.test.tsx src/pages/LoginPage.test.tsx
```

Expected: PASS. Search the changed SPA sources to confirm no browser auth flow references `res.token` or `setToken`:

```powershell
rg "res\.token|setToken|token:" src/stores/AuthContext.tsx src/pages/LoginPage.tsx
```

Expected: no credential-state matches; type-only `LoginResponse.token` elsewhere is outside the changed browser flow.

- [ ] **Step 7: Run full regression gates**

Run from `webui/`:

```powershell
npm run typecheck
npm test
npm run build
```

Run from repository root after build completes:

```powershell
python -m pytest tests/lan/test_lan_api.py tests/lan/test_path_guard.py tests/lan/test_t2_t4_contracts.py -q
```

Expected: all commands pass. The LAN command stays serial after the build because the SPA asset test requires built files.

- [ ] **Step 8: Commit**

```powershell
git add webui/src/stores/AuthContext.tsx webui/src/stores/AuthContext.test.tsx webui/src/pages/LoginPage.tsx webui/src/pages/LoginPage.test.tsx
git commit -m "fix: keep LAN credentials out of SPA state"
```

Expected: Commit contains only the Cookie-only SPA auth implementation and tests. Do not include reports, build output, or unrelated worktree files.
