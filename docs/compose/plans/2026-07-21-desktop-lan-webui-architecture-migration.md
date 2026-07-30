# Desktop–LAN–WebUI Architecture Migration Implementation Plan

> [!NOTE]
> **Status:** Completed through Phase 5 Task 17.
> See the final report for exact evidence and residual risks:
> [Desktop–LAN–WebUI Architecture Migration — Final Report](../reports/desktop-lan-webui-architecture-migration.md)

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 AssetsManager 渐进改造成以唯一 `LibraryRuntime` 为核心、具有显式公共契约和可自愈跨端失效同步的模块化单体。

**Architecture:** 扩展现有 `ApplicationBootstrap.for_library()`，使一个 canonical `LibrarySession` 只对应一个缓存的 `LibraryRuntime`；Desktop 与 LAN 注入并共享该 Runtime。业务数据继续通过 HTTP 快照读取，session-scoped DomainEvent 经 Event Router 映射为带 `epoch + revision` 的 WebSocket 投影失效通知，React 由统一 provider 完成重连、gap 检测与按域补拉。

**Tech Stack:** Python 3、PySide6、SQLite、aiohttp、React 18、TypeScript 5、Vitest、pytest。

## Global Constraints

- 每个 Phase 是独立发布门；Phase 内任务完成前不得进入下一 Phase。
- 每个发布门必须保持 Desktop、LAN、WebUI 可运行并允许回滚该 Phase 的提交集。
- `LibrarySession` 继续拥有库根、数据库连接、operation lease 和关闭顺序。
- SQLite 与文件系统仍是权威数据源；WebSocket 只传失效通知，不传权威业务对象。
- Desktop 继续直接调用应用服务，不经本地 HTTP。
- 路径防逃逸、preview/download 权限、HttpOnly Cookie 和查询参数凭据限制不得弱化。
- 业务事务不得依赖通知投递成功；通知失败由客户端 revision gap 补拉恢复。
- 新旧入口最多并存一个 Phase；消费者迁移并验证后立即删除 fallback。
- 不引入独立服务、微服务、Redis、Kafka、数据库替换或强制 React Query 迁移。
- 不修改无关用户改动；只有用户明确授权时才创建阶段 checkpoint commit。

---

## File Responsibility Map

### Python application core

- `AssetsManager/application/runtime.py`：新增 `LibraryRuntime`，拥有 session、共享服务、event router、epoch、revision 和幂等关闭。
- `AssetsManager/application/runtime_events.py`：新增投影 domain、`InvalidationEvent`、领域事件映射与订阅生命周期。
- `AssetsManager/application/bootstrap.py`：成为 Runtime 唯一工厂与缓存所有者；`for_library()` 保持兼容返回 Runtime 的 services。
- `AssetsManager/application/library_service.py`：提供 `session_closing` 前置通知和 `session_closed` 后置通知，保证 Runtime adapter 在连接释放前退出。
- `AssetsManager/application/context.py`：保持 operation lease 和直接关闭语义，不吸收 transport 逻辑。

### LAN adapters and contracts

- `AssetsManager/lan/dto.py`：公共 API DTO 与唯一序列化规则。
- `AssetsManager/lan/principal.py`：`SessionPrincipal`、capabilities 和认证种类映射。
- `AssetsManager/lan/server.py`：接收 Runtime、挂载 LAN-only Auth/Share services、连接 event adapter、维护生命周期和统计。
- `AssetsManager/lan/routes/_helpers.py`：只解析 request/runtime/principal；删除应用服务构造职责。
- `AssetsManager/lan/routes/auth.py`、`users.py`、`tags.py`、`metadata.py`、`system.py`：只返回 DTO。
- `AssetsManager/lan/routes/websocket.py`、`AssetsManager/lan/ws.py`：principal-aware 连接、epoch/revision 握手与广播。
- `AssetsManager/widgets/lan_sharing.py`、`AssetsManager/lan/manager.py`：LAN 生命周期所有者负责注入 canonical Runtime。

### React adapters

- `webui/src/types/api.ts`：公共 DTO 的 TypeScript 镜像；删除虚假字段。
- `webui/src/stores/AuthContext.tsx`：持有 principal/capabilities，不再推导权限。
- `webui/src/stores/RealtimeContext.tsx`：新增单一连接、cursor 与 invalidation registry。
- `webui/src/hooks/useWebSocket.ts`：低层可靠连接与退避，不解释业务 domain。
- `webui/src/hooks/useInvalidation.ts`：新增 projection callback 注册接口。
- `BrowsePage`、`Sidebar`、`LandingPage`、`DetailPage`、管理组件：只注册自己的 projection refresh。

### Shared contract and acceptance evidence

- `tests/contracts/lan_public_contracts.json`：Python 真实 serializer 与 TypeScript consumer 共用的 golden payload。
- `tests/lan/test_public_contracts.py`：真实 route/DTO 对照 golden payload。
- `webui/src/api/public-contracts.test.ts`：TypeScript 类型与真实 consumer 对照同一 payload。
- `tests/integration/test_runtime_events.py`：业务变更到 invalidation 的生产链。
- `tests/lan/test_runtime_realtime.py`：Runtime 到 WebSocket、epoch/revision 与隔离。
- `webui/src/stores/RealtimeContext.test.tsx`：重连、gap、自愈和注册清理。

## Canonical Interfaces

实施者必须使用以下接口名，后续任务不得自行改名：

```python
# AssetsManager/application/runtime.py
@dataclass(frozen=True)
class RuntimeCursor:
    epoch: str
    revision: int

class LibraryRuntime:
    session: LibrarySession
    services: LibraryScopedServices
    event_router: RuntimeEventRouter

    @property
    def cursor(self) -> RuntimeCursor: ...
    def next_revision(self) -> RuntimeCursor: ...
    def close_adapters(self) -> None: ...
    def close(self) -> None: ...

class ApplicationBootstrap:
    def runtime_for(self, session: LibrarySession) -> LibraryRuntime: ...
    def for_library(self, session: LibrarySession) -> LibraryScopedServices:
        return self.runtime_for(session).services
```

```python
# AssetsManager/application/runtime_events.py
ProjectionDomain = Literal[
    "files", "tree", "home", "project_detail", "metadata",
    "tags", "shares", "users", "stats",
]

@dataclass(frozen=True)
class InvalidationEvent:
    epoch: str
    revision: int
    domains: tuple[ProjectionDomain, ...]
    paths: tuple[str, ...] = ()

class RuntimeEventRouter:
    def accept(self, event: DomainEvent) -> None: ...
    def subscribe(self, handler: Callable[[InvalidationEvent], None]) -> EventSubscription: ...
    def close(self) -> None: ...
```

```python
# AssetsManager/lan/principal.py
@dataclass(frozen=True)
class Capabilities:
    browse: bool
    preview: bool
    download: bool
    upload: bool
    manage_links: bool
    manage_users: bool
    settings: bool
    realtime: bool

@dataclass(frozen=True)
class SessionPrincipal:
    kind: Literal["user", "password", "access_key", "local_ui", "guest", "share"]
    authenticated: bool
    role: Literal["admin", "user", "guest"]
    display_name: str
    capabilities: Capabilities
    user_profile: UserResponse | None = None
```

```typescript
// webui/src/stores/RealtimeContext.tsx
export type ProjectionDomain =
  | 'files' | 'tree' | 'home' | 'project_detail' | 'metadata'
  | 'tags' | 'shares' | 'users' | 'stats';

export interface RuntimeCursor { epoch: string; revision: number }
export interface InvalidationEvent extends RuntimeCursor {
  type: 'projection_invalidated';
  domains: ProjectionDomain[];
  paths: string[];
}

export interface RealtimeContextValue extends RuntimeCursor {
  status: 'connecting' | 'connected' | 'disconnected';
  registerInvalidation(
    domains: readonly ProjectionDomain[],
    callback: (event: InvalidationEvent | null) => void,
  ): () => void;
  recover(): Promise<void>;
}
```

## Phase Size and Ownership

| Phase | Tasks | Expected effort | Primary risk | Release owner |
|---|---:|---:|---|---|
| 0 | 1–2 | 1–2 days | Test harness accidentally freezes defects | Platform/WebUI |
| 1 | 3–5 | 2–4 days | Auth compatibility and public JSON drift | LAN + WebUI |
| 2 | 6–8 | 3–5 days | Session teardown and duplicate service identity | Application/Desktop |
| 3 | 9–11 | 3–5 days | Cross-thread delivery and old-library leakage | Application/LAN |
| 4 | 12–14 | 3–5 days | Refetch storms and stale React responses | WebUI |
| 5 | 15–17 | 2–4 days | Misleading telemetry and incomplete cleanup | Cross-surface |

总量约 14–25 个工程日。每个 Phase 结束后重新估算下一 Phase；不得以总工期压力跳过发布门。

---

## Phase 0 — Baseline and Safety Rails

### Task 1: Freeze canonical session and security invariants

**Covers:** [S1, S2, S3, S13]

**Files:**
- Modify: `tests/unit/test_bootstrap.py`
- Modify: `tests/integration/test_event_publishing.py`
- Modify: `tests/lan/test_t2_t4_contracts.py`
- Modify: `tests/unit/test_architecture_boundaries.py`

**Interfaces:**
- Consumes: `ApplicationBootstrap.for_library(session)`, `LibraryService.owns_live_session()`, LAN path/auth middleware.
- Produces: regression gates that all later Runtime and LAN changes must preserve.

- [ ] **Step 1: Add canonical-session characterization tests** asserting repeated `for_library(session)` calls use the exact same canonical session, stale/synthetic sessions are rejected, and session close removes all scoped cache entries. Do not assert scoped service object identity yet.
- [ ] **Step 2: Run the focused tests.** Run: `python -m pytest tests/unit/test_bootstrap.py -q`. Expected: PASS before production changes.
- [ ] **Step 3: Add application-event characterization tests** proving Desktop-facing scoped FileOperation/Tag/Metadata services publish `FileSystemChanged`, `AssetTagsChanged`, `TagCatalogChanged`, `AssetNotesChanged` and `AssetUrlsChanged` with the exact canonical `session.event_token`; do not assert transport behavior yet.
- [ ] **Step 4: Run event baseline.** Run: `python -m pytest tests/integration/test_event_publishing.py -q`. Expected: PASS before the Event Router exists.
- [ ] **Step 5: Add LAN security characterization tests** for wrong library root rejection, `../` and encoded path escape, preview/download permission denial, HttpOnly cookie auth, and `/ws` rejection of `?token=`/`?key=`.
- [ ] **Step 6: Run the security tests.** Run: `python -m pytest tests/lan/test_t2_t4_contracts.py -q`. Expected: PASS with no relaxed status codes.
- [ ] **Step 7: Add static architecture gates** that LAN routes do not import repositories or `DatabaseManager.current`, and public DTO modules introduced later may not import Qt.
- [ ] **Step 8: Run architecture gates.** Run: `python -m pytest tests/unit/test_architecture_boundaries.py -q`. Expected: PASS.

### Task 2: Make WebSocket reconnection reliable before event migration

**Covers:** [S3, S9, S12, S13]

**Files:**
- Modify: `webui/src/hooks/useWebSocket.test.tsx`
- Modify: `webui/src/hooks/useWebSocket.ts`

**Interfaces:**
- Consumes: browser `WebSocket`, current `{ onEvent, enabled }` hook API.
- Produces: low-level hook that retries repeatedly with bounded exponential backoff and resets failure count after a stable open.

- [ ] **Step 1: Write failing fake-timer tests** for three consecutive close/reconnect cycles, retry reset after `onopen`, one pending timer maximum, disable/unmount cancellation, and no reconnect after disposal.
- [ ] **Step 2: Verify RED.** Run: `npm --prefix webui test -- --run src/hooks/useWebSocket.test.tsx`. Expected: FAIL because the second post-open disconnect currently creates no new socket.
- [ ] **Step 3: Implement minimal retry policy:** initial delay 1s, exponential growth capped at 30s, one timer at a time, retry count reset in `onopen`, and cleanup that closes the active socket and clears the timer. Do not add domain handling.
- [ ] **Step 4: Verify GREEN.** Run the command from Step 2. Expected: all hook tests PASS.
- [ ] **Step 5: Run Phase 0 gate.** Run:
  - `python -m pytest tests/unit/test_bootstrap.py tests/unit/test_architecture_boundaries.py tests/lan/test_t2_t4_contracts.py -q`
  - `npm --prefix webui run typecheck`
  - `npm --prefix webui test -- --run src/hooks/useWebSocket.test.tsx`
  Expected: zero failures. This is the first publishable checkpoint.

---

## Phase 1 — Explicit DTOs and Principal/Capabilities

### Task 3: Introduce public DTOs for drifted responses

**Covers:** [S2, S3, S6, S12]

**Files:**
- Create: `AssetsManager/lan/dto.py`
- Create: `tests/lan/test_public_contracts.py`
- Create: `tests/contracts/lan_public_contracts.json`
- Modify: `AssetsManager/lan/routes/users.py`
- Modify: `AssetsManager/lan/routes/tags.py`
- Modify: `AssetsManager/lan/routes/metadata.py`
- Modify: `AssetsManager/lan/routes/system.py`

**Interfaces:**
- Produces: frozen DTOs exposing `to_dict() -> dict[str, object]`: `UserResponse`, `InviteResponse`, `TagResponse`, `TreeItemResponse`, `StatsResponse`.
- Contract: public fields use `active`, `revoked`, `used_by`, numeric Unix timestamps, optional values as JSON `null`; secrets and repository-only fields never serialize.

**Implementation sketch:**

```python
@dataclass(frozen=True)
class UserResponse:
    id: int
    username: str
    role: str
    active: bool
    created_at: float

    @classmethod
    def from_record(cls, record: Mapping[str, object]) -> "UserResponse":
        return cls(
            id=int(record["id"]),
            username=str(record["username"]),
            role=str(record["role"]),
            active=bool(record["is_active"]),
            created_at=float(record["created_at"]),
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
```

```python
def test_user_response_normalizes_repository_fields():
    response = UserResponse.from_record({
        "id": 1, "username": "owner", "role": "admin",
        "is_active": 1, "created_at": 100.0, "password_hash": "secret",
    }).to_dict()
    assert response == {
        "id": 1, "username": "owner", "role": "admin",
        "active": True, "created_at": 100.0,
    }
```

- [ ] **Step 1: Write failing DTO tests** using repository-shaped dictionaries. Assert `is_active` maps to `active`, invite `is_active` maps to `revoked = not is_active`, `used_by` is preserved, tree/tag payloads contain only guaranteed fields, and password hashes are absent.
- [ ] **Step 2: Verify RED.** Run: `python -m pytest tests/lan/test_public_contracts.py -q`. Expected: FAIL because `AssetsManager.lan.dto` does not exist.
- [ ] **Step 3: Implement frozen DTO dataclasses** with explicit `from_record()` factories and `to_dict()` methods. Keep conversion in `lan/dto.py`; do not rename repository fields.
- [ ] **Step 4: Route all affected responses through DTOs.** For recursive trees, map children recursively. Do not change endpoint URLs or authorization checks.
- [ ] **Step 5: Add golden contract payload** containing representative user, used invite, revoked invite, tag, recursive tree and stats records; assert Python DTO output equals the JSON file.
- [ ] **Step 6: Verify GREEN.** Run: `python -m pytest tests/lan/test_public_contracts.py tests/lan/test_lan_api.py -q`. Expected: zero failures and real route responses use normalized fields.

### Task 4: Model every session as a principal with server capabilities

**Covers:** [S2, S3, S6, S7, S12]

**Files:**
- Create: `AssetsManager/lan/principal.py`
- Modify: `AssetsManager/lan/dto.py`
- Modify: `AssetsManager/lan/server.py`
- Modify: `AssetsManager/lan/routes/_helpers.py`
- Modify: `AssetsManager/lan/routes/auth.py`
- Modify: `AssetsManager/lan/routes/system.py`
- Modify: `tests/lan/test_lan_api.py`

**Interfaces:**
- Produces: `SessionPrincipal(kind, authenticated, role, display_name, capabilities, user_profile=None)` and `principal_for_request(...)` mapping guest/password/access_key/local_ui/user/share.
- Produces: `/api/auth/me -> {"principal": ...}` for authenticated and allowed guest requests; temporary `user` compatibility field is emitted only for persisted users during Phase 1.

**Implementation sketch:**

```python
def get_request_principal(request: web.Request) -> SessionPrincipal | None:
    return request.get(AUTH_PRINCIPAL_REQUEST_KEY)

def require_permission(request: web.Request, permission: str) -> bool:
    principal = get_request_principal(request)
    return bool(principal and getattr(principal.capabilities, permission, False))
```

```python
@pytest.mark.parametrize("kind", ["user", "password", "access_key", "local_ui", "guest", "share"])
def test_principal_serialization_never_contains_credentials(kind, principal_factory):
    payload = principal_factory(kind).to_dict()
    assert "token" not in payload
    assert "password" not in json.dumps(payload)
    assert "capabilities" in payload
```

- [ ] **Step 1: Write a failing principal matrix test** covering all six principal kinds and guest settings `lan_guest_list/download/preview`; assert `realtime` is explicit and server authorization helpers read the principal capabilities.
- [ ] **Step 2: Verify RED.** Run: `python -m pytest tests/lan/test_lan_api.py -q -k "principal or auth_me or guest_permission"`. Expected: FAIL because the principal response is absent.
- [ ] **Step 3: Implement `lan/principal.py`** as pure data/mapping code with no aiohttp or Qt imports. Keep server middleware responsible only for credential verification and attaching the resulting principal.
- [ ] **Step 4: Change request helpers** so `require_role`, `require_admin` and `require_permission` consume one principal object; retain a one-Phase compatibility adapter for existing tests that attach legacy user dictionaries.
- [ ] **Step 5: Change `/auth/me` and `/api/info`** to return the normalized principal/capabilities. Never expose cookie/token values.
- [ ] **Step 6: Verify all auth modes.** Run: `python -m pytest tests/lan/test_lan_api.py tests/lan/test_t2_t4_contracts.py -q`. Expected: zero failures for password, key, local UI, user, guest and share boundaries.

### Task 5: Move React auth and admin consumers to real contracts

**Covers:** [S2, S6, S7, S9, S12, S13]

**Files:**
- Modify: `webui/src/types/api.ts`
- Modify: `webui/src/stores/AuthContext.tsx`
- Modify: `webui/src/stores/AuthContext.test.tsx`
- Modify: `webui/src/components/admin/UserManagement.tsx`
- Modify: `webui/src/components/admin/InviteManagement.tsx`
- Modify: `webui/src/components/admin/AdminManagement.test.tsx`
- Create: `webui/src/api/public-contracts.test.ts`

**Interfaces:**
- Consumes: `SessionPrincipalResponse` and the shared `tests/contracts/lan_public_contracts.json` fixture.
- Produces: AuthContext fields `principal`, `capabilities`, `isAuthenticated`; temporary `user` getter reads `principal.user_profile ?? null` for existing consumers.

- [ ] **Step 1: Write failing TypeScript contract tests** that import the shared JSON fixture, render user/invite consumers, and assert correct active/used/revoked states. Add AuthContext tests for guest, password, key and persisted-user principals.
- [ ] **Step 2: Verify RED.** Run: `npm --prefix webui test -- --run src/api/public-contracts.test.ts src/stores/AuthContext.test.tsx src/components/admin/AdminManagement.test.tsx`. Expected: FAIL on current field and identity assumptions.
- [ ] **Step 3: Update API types** to exactly match DTOs: remove mandatory `TreeItem.type` and `Tag.id`, use normalized user/invite fields, and add `SessionPrincipal`/`Capabilities`.
- [ ] **Step 4: Refactor AuthContext** so `/auth/me` is authoritative after login/refresh, permissions are not hardcoded, and `isAuthenticated` comes from the principal. Preserve cookie-only credential handling.
- [ ] **Step 5: Refactor admin components** to consume normalized fields and display unavailable optional timestamps safely.
- [ ] **Step 6: Verify GREEN and Phase 1 gate.** Run:
  - `python -m pytest tests/lan/test_public_contracts.py tests/lan/test_lan_api.py tests/lan/test_t2_t4_contracts.py -q`
  - `npm --prefix webui test -- --run src/api/public-contracts.test.ts src/stores/AuthContext.test.tsx src/components/admin/AdminManagement.test.tsx src/components/layout/Sidebar.test.tsx`
  - `npm --prefix webui run build`
  Expected: zero failures and no TypeScript assertions compensating for missing server fields.

---

## Phase 2 — One Canonical LibraryRuntime

### Task 6: Turn the existing scoped bundle into a cached Runtime

**Covers:** [S1, S2, S3, S4, S5, S12]

**Files:**
- Create: `AssetsManager/application/runtime.py`
- Modify: `AssetsManager/application/bootstrap.py`
- Modify: `AssetsManager/application/library_service.py`
- Modify: `AssetsManager/application/__init__.py`
- Modify: `tests/unit/test_bootstrap.py`
- Create: `tests/unit/test_library_runtime.py`
- Modify: `tests/integration/test_library_service.py`

**Interfaces:**
- Produces: `LibraryRuntime.session`, `.services`, `.epoch`, `.revision`, `.next_revision()`, `.close()`.
- Produces: `ApplicationBootstrap.runtime_for(session) -> LibraryRuntime`.
- Produces: `LibraryService.add_session_closing_listener(listener)` before connection teardown; existing `add_session_close_listener(listener)` remains the post-close hook.
- Compatibility: `ApplicationBootstrap.for_library(session) -> LibraryScopedServices` delegates to `runtime_for(session).services` for one Phase.

**Implementation sketch:**

```python
def runtime_for(self, session: LibrarySession) -> LibraryRuntime:
    if not self.library_service.owns_live_session(session):
        raise ValueError("LibrarySession must be the live canonical session owned by this bootstrap")
    key = id(session)
    cached = self._runtimes.get(key)
    if cached is not None and cached.session is session:
        return cached
    runtime = LibraryRuntime(session=session, services=self._build_services(session))
    self._runtimes[key] = runtime
    return runtime
```

```python
def test_runtime_is_cached_for_exact_canonical_session(tmp_path):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path)
    assert bootstrap.runtime_for(session) is bootstrap.runtime_for(session)
    assert bootstrap.for_library(session) is bootstrap.runtime_for(session).services
```

The lifecycle split is internal and must preserve public `session.close()`:

```python
# context.py
def _begin_close(self) -> None:
    with self._operation_condition:
        object.__setattr__(self, "_closed", True)  # rejects new operations

def _finish_close(self) -> None:
    with self._operation_condition:
        self._operation_condition.wait_for(lambda: self._active_operations == 0)
    self._clear_owned_caches_once()

# library_service.py
session._begin_close()
self._notify_session_closing(session)
session._finish_close()
self._notify_session_closed(session)
```

- [ ] **Step 1: Write failing tests** for one Runtime per exact canonical session, shared service identity on repeated resolution, different Runtime/epoch after same-root reopen, monotonic revision, foreign/stale session rejection and idempotent close. Add a lifecycle-order test requiring: new operations already fail inside `session_closing`; an existing leased operation may finish; `session_closed` occurs after lease drain; DB closure occurs last.
- [ ] **Step 2: Verify RED.** Run: `python -m pytest tests/unit/test_library_runtime.py tests/unit/test_bootstrap.py -q`. Expected: FAIL because Runtime APIs do not exist.
- [ ] **Step 3: Implement the minimal Runtime** around the existing `LibraryScopedServices`; move all per-session service construction from `for_library()` into one private Bootstrap factory.
- [ ] **Step 4: Add the pre-close lifecycle hook and replace `_undo_services` with `_runtimes`** keyed by `id(session)` and guarded by exact object identity. The pre-close listener calls `runtime.close_adapters()` before `session._close_direct()`; the existing post-close listener removes the exact Runtime and runs final cache cleanup.
- [ ] **Step 5: Keep `for_library()` as a thin compatibility method** and add a test that it returns the exact `runtime.services` object.
- [ ] **Step 6: Verify GREEN.** Run the command from Step 2 plus `python -m pytest tests/integration/test_library_service.py tests/integration/test_file_operation_service.py -q`.

### Task 7: Inject Runtime into the LAN server lifecycle

**Covers:** [S2, S3, S4, S5, S12]

**Files:**
- Modify: `AssetsManager/lan/__init__.py`
- Modify: `AssetsManager/lan/server.py`
- Modify: `AssetsManager/lan/routes/_helpers.py`
- Modify: `AssetsManager/widgets/lan_sharing.py`
- Modify: `AssetsManager/lan/manager.py`
- Modify: `tests/unit/test_lan_sharing.py`
- Modify: `tests/lan/test_lan_api.py`

**Interfaces:**
- Consumes: `LibraryRuntime` from Task 6.
- Produces: `LanServer(runtime=runtime, ...)`; `lan.services` combines `runtime.services` with LAN-only Auth/Share/Activity/Online ports.
- Compatibility: legacy `library_root/thumbnail_dir/db_conn` construction is removed; low-level tests use explicit runtime-shaped fixtures.

- [ ] **Step 1: Write failing lifecycle tests** asserting Desktop sharing passes `bootstrap.runtime_for(session)`, LAN root/connection are the Runtime session resources, and a mismatched root is rejected before server startup.
- [ ] **Step 2: Verify RED.** Run: `python -m pytest tests/unit/test_lan_sharing.py tests/lan/test_lan_api.py -q -k "runtime or library_root or connection"`.
- [ ] **Step 3: Extend the facade/server constructor** to accept Runtime as the primary API. LAN-only `AuthService` and `ShareService` may still use the runtime connection and server token secret, but routes must obtain application services from `runtime.services`.
- [x] **Step 4: Replace lazy `_build_lan_services()` production use** with an eagerly attached `lan.services`; remove legacy factories after all callers and fixtures migrate.
- [ ] **Step 5: Update Desktop and ShareManager call sites** to resolve/inject canonical Runtime. Do not reconstruct `LibrarySession` from a context or root.
- [ ] **Step 6: Verify GREEN.** Run full `tests/unit/test_lan_sharing.py`, `tests/unit/test_bootstrap.py` and `tests/lan/test_lan_api.py`.

### Task 8: Remove duplicate LAN application-service assembly

**Covers:** [S2, S4, S5, S12, S13]

**Files:**
- Modify: `AssetsManager/lan/routes/_helpers.py`
- Modify: `AssetsManager/lan/manager.py`
- Modify: `tests/unit/test_architecture_boundaries.py`
- Modify: `tests/lan/test_lan_api.py`
- Modify: `docs/architecture.md`
- Create: `docs/adr/0003-library-runtime.md`

**Interfaces:**
- Consumes: Runtime injection from Task 7.
- Produces: one production service assembly path; `get_services(request)` becomes a direct lookup with no construction fallback.

- [ ] **Step 1: Write a failing static gate** asserting `_helpers.py` contains no construction of `MetadataService`, `ProjectService`, `TagService`, `SearchService`, `ThumbnailService` or `AssetService`.
- [ ] **Step 2: Verify RED.** Run: `python -m pytest tests/unit/test_architecture_boundaries.py -q`.
- [ ] **Step 3: Delete `_build_lan_services()` and legacy connection constructors** after converting remaining tests to a Runtime fixture. Fail LAN startup loudly when Runtime is absent.
- [ ] **Step 4: Document the composition decision** in ADR 0003 and update `docs/architecture.md` with Runtime ownership and teardown order.
- [ ] **Step 5: Verify GREEN and Phase 2 gate.** Run:
  - `python -m pytest tests/unit/test_bootstrap.py tests/unit/test_library_runtime.py tests/unit/test_architecture_boundaries.py tests/unit/test_lan_sharing.py -q`
  - `python -m pytest tests/integration tests/lan -q`
  - `npm --prefix webui run build`
  Expected: zero failures; search for `_build_lan_services` returns no production definition/call.

---

## Phase 3 — Event Router and Runtime Cursor

### Task 9: Map session-scoped DomainEvents to projection invalidations

**Covers:** [S2, S3, S4, S5, S8, S12]

**Files:**
- Create: `AssetsManager/application/runtime_events.py`
- Modify: `AssetsManager/application/runtime.py`
- Create: `tests/integration/test_runtime_events.py`
- Modify: `tests/integration/test_event_publishing.py`

**Interfaces:**
- Produces: `ProjectionDomain` string enum and frozen `InvalidationEvent(epoch, revision, domains, paths)`.
- Produces: `RuntimeEventRouter.subscribe(handler) -> EventSubscription` and `.close()`.
- Mapping: `FileSystemChanged -> files/tree/home/project_detail`; asset tag/notes/URLs and tag catalog events map to `metadata/tags/project_detail/home` as appropriate.

**Implementation sketch:**

```python
EVENT_DOMAINS: dict[type[DomainEvent], tuple[ProjectionDomain, ...]] = {
    FileSystemChanged: ("files", "tree", "home", "project_detail"),
    AssetTagsChanged: ("metadata", "tags", "project_detail", "home"),
    TagCatalogChanged: ("tags", "home"),
    AssetNotesChanged: ("metadata", "project_detail"),
    AssetUrlsChanged: ("metadata", "project_detail"),
}
```

```python
def test_router_ignores_other_session_event(runtime, publish):
    received = []
    runtime.event_router.subscribe(received.append)
    publish(FileSystemChanged(library_root=runtime.session.root_str, session_token="other"))
    assert received == []
```

- [ ] **Step 1: Write failing mapping tests** for every session-scoped event type, multi-domain mapping, normalized relative paths, monotonic revisions, wrong session token/root rejection and no callbacks after close.
- [ ] **Step 2: Verify RED.** Run: `python -m pytest tests/integration/test_runtime_events.py -q`.
- [ ] **Step 3: Implement pure event mapping** and subscribe only to session-scoped event classes. Legacy unscoped `TagsChanged/NotesChanged/UrlsChanged` must not drive LAN invalidation.
- [ ] **Step 4: Attach one router to each Runtime.** Revision increments only when an accepted event produces at least one invalidated domain.
- [ ] **Step 5: Verify GREEN.** Run the command from Step 2 plus `tests/integration/test_event_publishing.py`.

### Task 10: Bridge Runtime invalidations to authenticated WebSockets

**Covers:** [S3, S6, S7, S8, S10, S12]

**Files:**
- Modify: `AssetsManager/lan/dto.py`
- Modify: `AssetsManager/lan/server.py`
- Modify: `AssetsManager/lan/ws.py`
- Modify: `AssetsManager/lan/routes/websocket.py`
- Modify: `AssetsManager/lan/routes/system.py`
- Modify: `AssetsManager/lan/api.py`
- Create: `tests/lan/test_runtime_realtime.py`

**Interfaces:**
- Consumes: `InvalidationEvent` and Runtime principal/capabilities.
- Produces: `/api/revision -> {epoch, revision}` and WS initial `runtime_ready` followed by `projection_invalidated` DTOs.
- Threading: Runtime callback may run on Desktop thread; server schedules broadcast with `asyncio.run_coroutine_threadsafe` on its loop.

**Implementation sketch:**

```python
def _publish_invalidation(self, event: InvalidationEvent) -> None:
    loop = self._loop
    if loop is None or not self._running or loop.is_closed():
        return
    asyncio.run_coroutine_threadsafe(
        self._ws_manager.broadcast_json(InvalidationEventResponse.from_event(event).to_dict()),
        loop,
    )
```

```python
async def test_runtime_event_reaches_websocket(runtime_client, runtime):
    ws = await runtime_client.ws_connect("/ws")
    ready = await ws.receive_json()
    assert ready["type"] == "runtime_ready"
    runtime.event_router.accept(FileSystemChanged(
        library_root=runtime.session.root_str,
        session_token=runtime.session.event_token,
        kind="create",
    ))
    message = await ws.receive_json()
    assert message["type"] == "projection_invalidated"
    assert message["revision"] == 1
```

- [ ] **Step 1: Write failing real aiohttp WebSocket tests** for initial cursor, accepted event broadcast, exact DTO fields, guest realtime policy, wrong-session silence, and close/unsubscribe behavior.
- [ ] **Step 2: Verify RED.** Run: `python -m pytest tests/lan/test_runtime_realtime.py -q`.
- [ ] **Step 3: Add invalidation/revision DTOs** and one server adapter callback. Do not put full file, project, tag or metadata objects in messages.
- [ ] **Step 4: Add principal-aware WS connection bookkeeping** and `/api/revision`. Ensure route admission still rejects query credentials.
- [ ] **Step 5: Make startup/teardown deterministic:** subscribe after event loop/site readiness; unsubscribe before closing WS and Runtime references.
- [ ] **Step 6: Verify GREEN.** Run the command from Step 2 plus full `tests/lan/test_lan_api.py`.

### Task 11: Prove library-switch and missed-event isolation

**Covers:** [S2, S3, S5, S8, S12, S13]

**Files:**
- Modify: `tests/lan/test_runtime_realtime.py`
- Modify: `tests/unit/test_window_session_switching.py`
- Modify: `tests/unit/test_lan_sharing.py`

**Interfaces:**
- Consumes: Runtime epoch/revision and deterministic teardown.
- Produces: release gates for same-root reopen, old-loop callbacks and server restart.

- [ ] **Step 1: Add same-root reopen test:** close Runtime A, open Runtime B on the same path, assert new epoch and revision zero, then publish an A-token event and assert B clients receive nothing.
- [ ] **Step 2: Add LAN restart test:** stop/start with the same live Runtime, assert exactly one Runtime subscription and no duplicate broadcast.
- [ ] **Step 3: Add shutdown-race test:** enqueue an invalidation while stopping; assert no exception escapes, no dead loop scheduling repeats, and business state remains committed.
- [ ] **Step 4: Run Phase 3 gate.** Run:
  - `python -m pytest tests/integration/test_runtime_events.py tests/integration/test_event_publishing.py -q`
  - `python -m pytest tests/lan/test_runtime_realtime.py tests/lan/test_lan_api.py -q`
  - `python -m pytest tests/unit/test_window_session_switching.py tests/unit/test_lan_sharing.py -q`
  Expected: zero failures and no leaked subscriptions after teardown.

---

## Phase 4 — React Projection Invalidation and Recovery

### Task 12: Add one RealtimeProvider and cursor state machine

**Covers:** [S2, S7, S8, S9, S12, S13]

**Files:**
- Create: `webui/src/stores/RealtimeContext.tsx`
- Create: `webui/src/stores/RealtimeContext.test.tsx`
- Create: `webui/src/hooks/useInvalidation.ts`
- Modify: `webui/src/hooks/useWebSocket.ts`
- Modify: `webui/src/App.tsx`
- Modify: `webui/src/types/api.ts`

**Interfaces:**
- Produces: `registerInvalidation(domains, callback) -> unsubscribe`, `status`, `epoch`, `revision`, and `recover()`.
- Consumes: principal `capabilities.realtime`, `/api/revision`, WS `runtime_ready` and `projection_invalidated`.

**Implementation sketch:**

```typescript
function applyEvent(event: InvalidationEvent) {
  if (event.epoch !== cursor.epoch || event.revision > cursor.revision + 1) {
    void recover();
    return;
  }
  if (event.revision <= cursor.revision) return;
  setCursor({ epoch: event.epoch, revision: event.revision });
  notify(event.domains, event);
}
```

```typescript
it('recovers every registered projection once after a revision gap', async () => {
  const files = vi.fn();
  const tree = vi.fn();
  register(['files'], files);
  register(['tree'], tree);
  dispatch({ type: 'projection_invalidated', epoch: 'a', revision: 4, domains: ['files'], paths: [] });
  await waitFor(() => expect(files).toHaveBeenCalledTimes(1));
  expect(tree).toHaveBeenCalledTimes(1);
});
```

- [ ] **Step 1: Write failing provider tests** for one socket across multiple consumers, capability enable/disable, ordered revision delivery, duplicate suppression, gap recovery, epoch replacement, malformed message recovery and unmount cleanup.
- [ ] **Step 2: Verify RED.** Run: `npm --prefix webui test -- --run src/stores/RealtimeContext.test.tsx src/hooks/useWebSocket.test.tsx`.
- [ ] **Step 3: Keep `useWebSocket` transport-only** and implement RealtimeContext cursor logic. A gap is `incoming.revision > current + 1`; epoch change always triggers recovery.
- [ ] **Step 4: Implement a small callback registry** using exact domain strings from the DTO. Recovery calls every registered projection once per recovery cycle; it does not invent a global application reload.
- [ ] **Step 5: Mount provider once inside AuthProvider** and verify identity changes replace the connection.
- [ ] **Step 6: Verify GREEN.** Run the command from Step 2 and `npm --prefix webui run typecheck`.

### Task 13: Migrate all React projections off page-level WebSocket logic

**Covers:** [S2, S8, S9, S12]

**Files:**
- Modify: `webui/src/pages/BrowsePage.tsx`
- Modify: `webui/src/pages/BrowsePage.test.tsx`
- Modify: `webui/src/components/layout/Sidebar.tsx`
- Modify: `webui/src/components/layout/Sidebar.test.tsx`
- Modify: `webui/src/pages/LandingPage.tsx`
- Modify: `webui/src/pages/LandingPage.test.tsx`
- Modify: `webui/src/pages/DetailPage.tsx`
- Modify: `webui/src/pages/DetailPage.test.tsx`
- Modify: `webui/src/components/admin/ActivityLog.tsx`
- Modify: `webui/src/components/admin/OnlineUsers.tsx`
- Modify: relevant admin tests

**Interfaces:**
- Consumes: `useInvalidation(domains, callback)` from Task 12.
- Produces: domain ownership: Browse=`files/metadata/tags/project_detail`; Sidebar=`tree`; Landing=`home`; Detail=`project_detail/metadata/tags`; admin=`users/shares/stats`.

- [ ] **Step 1: Write failing component tests** that dispatch domain invalidations through a test provider and assert only the owning projection refetches. Include selected InfoPanel path match and stale-request cancellation.
- [ ] **Step 2: Verify RED.** Run focused Browse/Sidebar/Landing/Detail/admin tests. Expected: FAIL because pages do not register domain invalidations.
- [ ] **Step 3: Register existing stable refresh functions** with `useInvalidation`; do not duplicate fetch implementations inside the realtime layer.
- [ ] **Step 4: Remove `useWebSocket` from BrowsePage and StatusBar.** StatusBar consumes provider status; pages no longer parse event names.
- [ ] **Step 5: Preserve request generations/AbortControllers** so an invalidation cannot let an older response overwrite newer navigation or selection.
- [ ] **Step 6: Verify GREEN.** Run all focused component tests and `npm --prefix webui run typecheck`.

### Task 14: Verify browser recovery against a real LAN server

**Covers:** [S2, S8, S9, S13]

**Files:**
- Create: `tests/e2e/test_webui_realtime_acceptance.py` or extend the repository's existing real-browser LAN acceptance harness
- Modify: `tests/lan/test_runtime_realtime.py`

**Interfaces:**
- Consumes: completed server and React realtime protocol.
- Produces: end-to-end proof of snapshot refresh and cursor recovery.

- [ ] **Step 1: Add acceptance scenario:** open React Browse in a real browser, mutate through Desktop application service, assert visible listing/detail updates without manual reload.
- [ ] **Step 2: Add disconnect scenario:** block/close WebSocket, perform two mutations, reconnect, assert revision gap triggers HTTP refetch and final UI matches the authoritative server snapshot.
- [ ] **Step 3: Add server restart scenario:** restart LAN on the same library, assert epoch change and one complete recovery without duplicate requests looping.
- [ ] **Step 4: Run Phase 4 gate.** Run:
  - `npm --prefix webui test -- --run`
  - `npm --prefix webui run typecheck`
  - `npm --prefix webui run build`
  - `python -m pytest tests/lan/test_runtime_realtime.py tests/e2e/test_webui_realtime_acceptance.py -q`
  Expected: zero failures; browser reaches final authoritative state in all three scenarios.

---

## Phase 5 — Telemetry, Cleanup, and Final Closure

### Task 15: Connect only truthful telemetry producers

**Covers:** [S6, S7, S10, S12]

**Files:**
- Modify: `AssetsManager/lan/server.py`
- Modify: `AssetsManager/lan/security.py`
- Modify: `AssetsManager/lan/ws.py`
- Modify: `AssetsManager/lan/routes/_helpers.py`
- Modify: `AssetsManager/lan/routes/users.py`
- Modify: `AssetsManager/lan/routes/system.py`
- Modify: `AssetsManager/lan/routes/shares.py`
- Modify: `AssetsManager/lan/routes/downloads.py`
- Modify: `tests/lan/test_lan_api.py`
- Modify: `webui/src/components/admin/ActivityLog.tsx`
- Modify: `webui/src/components/admin/OnlineUsers.tsx`

**Interfaces:**
- Produces: truthful `connections`, `requests`, `bytes_transferred | null`, `uptime`; normalized activity and online-principal DTOs.
- Rule: a metric that cannot be measured accurately serializes as `null`/unavailable, never a fabricated zero.

**Implementation sketch:**

```python
@web.middleware
async def metrics_middleware(request, handler):
    request.app[LAN_APP_KEY].metrics.request_started()
    try:
        response = await handler(request)
        return response
    finally:
        request.app[LAN_APP_KEY].metrics.request_finished()
```

```python
async def test_stats_report_live_websocket_count(client, ws_url):
    before = await (await client.get("/api/stats")).json()
    async with client.ws_connect(ws_url):
        during = await (await client.get("/api/stats")).json()
        assert during["connections"] == before["connections"] + 1
```

- [x] **Step 1: Write failing producer tests** for request count, WS add/remove connection count, uptime growth, login/share/download activity and principal-keyed online presence cleanup.
- [x] **Step 2: Verify RED.** Run: `python -m pytest tests/lan/test_lan_api.py -q -k "stats or activity or online"`.
- [x] **Step 3: Add one middleware/lifecycle producer per metric.** Keep telemetry exceptions contained and unable to alter response status or business transactions.
- [x] **Step 4: Serialize unavailable byte counts explicitly** unless aiohttp response lifecycle gives a verified byte value. Update UI to show unavailable rather than zero.
- [x] **Step 5: Verify GREEN.** Run the command from Step 2 and relevant admin Vitest files.

### Task 16: Delete migration fallbacks and enforce architecture boundaries

**Covers:** [S2, S3, S4, S5, S6, S7, S8, S9, S12, S14]

**Files:**
- Modify: `AssetsManager/application/bootstrap.py`
- Modify: `AssetsManager/lan/server.py`
- Modify: `AssetsManager/lan/routes/_helpers.py`
- Modify: `AssetsManager/domain/events.py`
- Modify: `webui/src/types/api.ts`
- Modify: `tests/unit/test_architecture_boundaries.py`
- Modify: `tests/core/test_package_contents.py`
- Modify: `scripts/check_package_contents.py`

**Interfaces:**
- Consumes: all migrated Runtime, principal, DTO and realtime consumers.
- Produces: no duplicate LAN service assembly, no legacy user-dict auth adapter, no page-level WS consumer and no public type field absent from serializer.

- [x] **Step 1: Add failing static gates** for forbidden `_build_lan_services`, legacy Runtime constructors, legacy request-user dictionaries, direct page `useWebSocket`, and hand-declared public fields not represented in the shared contract fixture.
- [ ] **Step 2: Verify RED.** Run architecture and package-content tests.
- [ ] **Step 3: Delete all one-Phase compatibility paths** and unused unscoped network event mappings. Retain legacy domain events only when Desktop still has a verified producer/consumer contract.
- [ ] **Step 4: Update packaging manifest checks** for new Runtime/DTO/principal/realtime source files and ensure deleted fallbacks are not expected.
- [ ] **Step 5: Verify GREEN.** Run architecture, package and full LAN/WebUI gates.

### Task 17: Final cross-surface acceptance and documentation

**Covers:** [S1, S2, S3, S4, S5, S6, S7, S8, S9, S10, S11, S12, S13, S14]

**Files:**
- Modify: `docs/architecture.md`
- Modify: `docs/architecture-diagram.md`
- Modify: `docs/adr/0003-library-runtime.md`
- Create: `docs/compose/reports/desktop-lan-webui-architecture-migration.md`
- Mark: `docs/compose/specs/2026-07-21-desktop-lan-webui-architecture-design.md`
- Mark: `docs/compose/plans/2026-07-21-desktop-lan-webui-architecture-migration.md`

**Interfaces:**
- Consumes: all completed phases.
- Produces: final architecture truth, verification evidence and rollback notes.

This task is the **Phase 5 gate**. No migration work is complete until every step below has fresh passing evidence.

- [ ] **Step 1: Run complete Python verification.** Run: `python -m pytest -q`. Expected: zero failures.
- [ ] **Step 2: Run complete WebUI verification.** Run: `npm --prefix webui run typecheck`, `npm --prefix webui test -- --run`, and `npm --prefix webui run build`. Expected: zero failures.
- [ ] **Step 3: Run packaging gates.** Run: `python -m pytest tests/core/test_packaging_entrypoints.py tests/core/test_package_contents.py -q`. Expected: zero failures.
- [ ] **Step 4: Perform real Desktop–LAN–browser acceptance:** library open, sharing start, Desktop file/tag/notes mutation, LAN mutation reflected in Desktop, browser disconnect/reconnect, LAN restart, same-root reopen, guest/password/key/user authorization matrix, preview/download/share checks.
- [ ] **Step 5: Verify teardown evidence:** no old Runtime subscriptions, no old WebSocket clients, no operation after closed session, no wrong-library response.
- [ ] **Step 6: Update architecture docs and write final report** with exact commands/results, known residual risks and future independent-service extraction criteria.
- [ ] **Step 7: Run documentation checks.** Run: `git diff --check` and verify every cited file path exists.
- [ ] **Step 8: Optional release checkpoint, only after explicit user authorization:** stage only this migration's files and create a conventional commit or PR. Do not commit unrelated dirty-worktree changes.

---

## Release Gates and Rollback Conditions

| Phase | Publishable outcome | Roll back when |
|---|---|---|
| 0 | Existing invariants frozen; repeated reconnect works | Any auth/path guard regresses or timers/sockets leak |
| 1 | DTO/principal/capabilities are authoritative | Existing login mode or public route becomes incompatible |
| 2 | Desktop and LAN share one Runtime | Duplicate session/service construction remains or LAN can attach wrong root |
| 3 | Domain events reach WS with epoch/revision | Old-library event leaks, duplicate subscription, transaction depends on broadcast |
| 4 | React recovers projections after gaps/restarts | Stale response overwrites navigation or reconnect loops/refetch storms |
| 5 | Telemetry truthful; migration paths removed | Metrics fabricate values, packaging misses files, full cross-end acceptance fails |

## Execution Order

Execute strictly in numeric order. Tasks 3–5, 6–8, 9–11, 12–14 and 15–17 are phase-coupled and must not run concurrently against the same files. Within a task, use TDD red→green, then request a focused review before advancing. Use a fresh isolated worktree at execution time because the current workspace contains substantial unrelated changes.
