# Desktop–LAN–WebUI 渐进式架构改造设计

> [!NOTE]
> **Status:** Accepted and verified by Phase 5 Task 17.
> See the final report for exact evidence and residual risks:
> [Desktop–LAN–WebUI Architecture Migration — Final Report](../reports/desktop-lan-webui-architecture-migration.md)

## [S1] 背景与目标

AssetsManager 当前以 `LibrarySession`、SQLite 和文件系统为共享数据源，由 PySide6 Desktop 与 aiohttp LAN/React WebUI 提供两套交互界面。现有应用服务、Repository、DomainEvent、路径守卫和认证中间件形成了良好基础，但 LAN 仍自行组装部分服务，网络 DTO 主要依赖裸字典，DomainEvent 未接入 WebSocket，React 权限与刷新策略也由页面局部推导。

本次改造的目标是把现有系统强化为一个以库运行时为核心的模块化单体：Desktop、HTTP、WebSocket 和 React 都成为同一应用核心的适配器；每个阶段保持三端可运行、可验证、可发布和可回滚。

## [S2] 成功标准

- 一个活动库只有一个 canonical `LibrarySession` 和一个 `LibraryRuntime`。
- Desktop 与 LAN 使用同一组 library-scoped 应用服务，不再各自组装业务依赖。
- Repository/Domain 对象不会直接泄漏为公共 JSON；所有网络响应经过显式 DTO。
- 所有认证方式统一表达为 `SessionPrincipal`，React 只消费服务端返回的 capabilities。
- Desktop 或 LAN 成功完成业务变更后，WebUI 能收到 session-scoped 投影失效通知并重新查询权威 HTTP 快照。
- WebSocket 断线、服务重启、库切换和事件跳号均能通过 `epoch + revision` 自愈。
- 每个阶段都通过 Desktop、Python integration/LAN、WebUI 和打包门禁后才进入下一阶段。

## [S3] 不可破坏的不变量

- `LibrarySession` 继续拥有库根、数据库连接、operation lease 和关闭顺序。
- SQLite 与文件系统仍是权威数据源；WebSocket 不是业务数据存储或可靠消息队列。
- Desktop 保持直接调用应用服务，不改为经本地 HTTP 调用。
- LAN 路径防逃逸、preview/download 权限、HttpOnly Cookie 和查询参数凭据限制不得弱化。
- 业务事务成功不依赖 WebSocket 投递成功；通知失败不得回滚已经提交的文件或数据库操作。
- 已有项目详情、缩略图、下载和分享 URL 在对应迁移阶段内保持兼容。
- 改造不引入独立服务进程、微服务、Redis、Kafka 或数据库替换。

## [S4] 目标架构

```text
ApplicationBootstrap
        │
        └── LibraryRuntime (one per canonical LibrarySession)
              ├── LibrarySession / connection provider / operation lease
              ├── library-scoped Application Services
              ├── Event Router
              │     ├── Qt projection adapter
              │     ├── LAN invalidation adapter
              │     ├── cache invalidation adapter
              │     └── telemetry adapter
              └── Runtime identity: epoch + monotonic revision

Desktop adapter ───────────────┐
HTTP routes ── API DTOs ───────┼── LibraryRuntime
WebSocket invalidations ───────┘
                   │
                   └── React data/invalidation provider → page projections
```

`ApplicationBootstrap.for_library()` 演进为 Runtime 的唯一创建入口并按 canonical session 缓存。Runtime 只组织现有服务和横切适配器，不吸收 route、Qt widget 或 React 逻辑。

## [S5] LibraryRuntime 与生命周期

`LibraryRuntime` 至少提供：

- `session`：canonical `LibrarySession`。
- `services`：当前 `LibraryScopedServices` 中的应用服务。
- `event_router`：session-scoped DomainEvent 的唯一分发入口。
- `epoch`：每次 Runtime 创建时生成的不可预测标识。
- `revision`：Runtime 内单调递增的失效序号。
- `close()`：幂等关闭，按“停止接收新操作 → 解除事件订阅 → 关闭 LAN/WebSocket adapter → 释放 session 资源”执行。

LAN 启动必须接收 Runtime 或显式的 Runtime service port，不再从数据库连接重新创建 Metadata/Tag/Project 等服务。Runtime 必须拒绝不属于当前 `ApplicationBootstrap` 的 session，并在 session 关闭监听器中自动清理缓存。

`LibraryService` 提供两个明确的生命周期通知：session 先进入 closing 状态并拒绝新 operation，再触发 `session_closing`，随后等待已有 operation lease 排空；该前置通知用于停止 LAN 接入并解除 Runtime 外部订阅。现有 `session_closed` 在 session 已排空并关闭后触发，用于移除 Runtime/Undo 缓存。前置通知失败会被记录，但不得跳过 session 和数据库连接的最终关闭。

## [S6] 公共 API DTO

在 LAN 层建立显式、不可变的响应 DTO。第一批覆盖：

- `UserResponse`、`InviteResponse`。
- `SessionPrincipalResponse`、`CapabilitiesResponse`。
- `TreeItemResponse`、`TagResponse`。
- `ActivityResponse`、`OnlineUserResponse`、`StatsResponse`。
- `InvalidationEventResponse`、`RevisionResponse`。

DTO 负责字段命名、时间格式、可空性和公开字段过滤。Repository 保留内部字段（例如 `is_active`）；路由 DTO 统一输出公共字段（例如 `active`）。TypeScript 类型必须由同一份 schema 生成，或在过渡期由 schema 验证的 fixture 驱动；不允许 Python 与 TypeScript 各自凭手写 mock 宣称契约正确。

## [S7] 身份与能力模型

所有请求身份统一为：

```text
SessionPrincipal
├── kind: user | password | access_key | local_ui | guest | share
├── authenticated
├── role: admin | user | guest
├── display_name
├── capabilities
└── user_profile? 仅持久用户存在
```

`capabilities` 至少包括 `browse`、`preview`、`download`、`upload`、`manage_links`、`manage_users`、`settings` 和 `realtime`。服务端仍逐请求执行最终授权；客户端 capabilities 只用于显示正确的操作入口和决定是否建立实时连接。

`/api/auth/me` 返回统一 principal，不再要求 password/key/local UI principal 伪装成完整持久 `User`。无认证 guest 是否允许 realtime 由服务端策略明确决定。

## [S8] 事件与投影失效协议

DomainEvent 只在业务事务成功后进入 Event Router。Router 按 `session.event_token` 或等价 runtime identity 过滤，旧库和其他库事件不得进入当前 Runtime。

WebSocket 只发送投影失效，不发送权威业务对象：

```json
{
  "type": "projection_invalidated",
  "epoch": "runtime-id",
  "revision": 42,
  "domains": ["files", "tree", "project_detail"],
  "paths": ["projects/alpha"]
}
```

首批 domain 为 `files`、`tree`、`home`、`project_detail`、`metadata`、`tags`、`shares`、`users` 和 `stats`。同一业务操作可失效多个 domain；paths 用于缩小刷新范围，但不得成为正确性的唯一条件。

`epoch` 仅在 Runtime 生命周期内有效，`revision` 在内存中单调递增。客户端遇到 epoch 变化、revision 跳号、消息解析失败或重连后状态不确定时，执行相关投影的完整补拉。阶段一不把 revision 高频写入 SQLite；只有未来出现跨进程常驻服务需求时再引入持久 cursor。

## [S9] React 数据与实时层

React 建立单一 realtime/invalidation provider，负责：

- 根据 `principal.capabilities.realtime` 建立连接。
- 持续指数退避重连，带上限与抖动；稳定连接后重置失败计数。
- 保存当前 epoch/revision，检测 gap。
- 将 domain invalidation 分发给查询/状态所有者。
- 在 provider 卸载、身份变化或库 epoch 变化时关闭旧连接和取消旧刷新。

业务页面继续通过 HTTP 获取权威快照。`BrowsePage`、Sidebar、Landing、InfoPanel/Detail、管理页不再各自解释 WebSocket 事件；它们只注册或消费相应投影的刷新动作。首轮改造不强制引入 React Query，可在现有 hooks 上建立小型 invalidation registry，避免无关状态管理迁移。

## [S10] 遥测与在线状态

遥测必须遵循“有 producer 才有 UI”：

- HTTP middleware 记录请求数、响应状态和可确定的传输字节。
- WebSocket add/remove 维护实时连接数。
- Runtime 启动时间计算 uptime。
- 登录、分享创建/删除、下载等明确动作写入规范化 Activity DTO。
- online user 必须有可靠 connect/disconnect 生命周期和稳定 principal key；无法可靠实现时先隐藏该面板。

遥测失败不得影响业务请求。任何无法准确计算的指标必须标记为不可用，不得返回看似有效的恒零值。

## [S11] 分阶段迁移

### Phase 0：基线与护栏

先增加真实 Python JSON→TypeScript consumer 契约夹具、Desktop mutation→事件链测试、WebSocket 多轮重连测试和库切换隔离测试。该阶段不改变生产架构。

### Phase 1：DTO 与 Principal/Capabilities

规范化已知漂移字段，建立统一 principal 与 capabilities，并让 React 权限展示改为消费服务端数据。保持现有 URL 和业务行为。

### Phase 2：唯一 LibraryRuntime

将 `ApplicationBootstrap.for_library()` 演进为缓存 Runtime，LAN 由 Desktop 生命周期所有者注入 Runtime。旧 `_build_lan_services()` 作为受测 fallback 只保留一个阶段，消费者迁移完成后删除。

### Phase 3：Event Router 与 epoch/revision

实现 session-scoped event mapping、失效 DTO、WebSocket broadcast adapter 和 revision 查询/握手。先覆盖文件、树、metadata、tags 和 project detail。

### Phase 4：React 投影失效与可靠重连

建立统一 provider/registry，迁移 Browse、Sidebar、Landing、InfoPanel/Detail 和管理页刷新策略，删除页面级事件解释。

### Phase 5：遥测、旧入口删除与全链路收口

接通可靠的请求、连接、活动和在线状态 producer；删除没有实现依据的 UI；移除 fallback、旧事件名和虚假 TypeScript 字段；执行真实 Desktop+LAN+浏览器验收。

## [S12] 兼容、失败与回滚

- 每个阶段单独形成可发布提交集，不允许依赖下一阶段才能恢复可用性。
- 新旧入口最多并存一个阶段，并由测试证明结果等价；迁移后立即删除旧入口。
- API 字段需要改名时，优先在同一响应短期双写，并在 React 完成迁移后删除旧字段；不创建长期 `/api/v2`。
- Event Router 或 WebSocket 失败时记录诊断并继续业务事务；客户端用 HTTP 补拉恢复。
- Runtime 启动或注入失败时 LAN 不得悄悄连接另一库或创建第二套 session；应拒绝启动并保留 Desktop 可用。
- 每阶段回滚只回退该阶段提交，不回滚数据库用户数据；本设计不要求破坏性 schema migration。

## [S13] 测试与发布门槛

每阶段至少执行：

- 受影响模块的 TDD 回归测试。
- `tests/integration` 中 LibrarySession/ApplicationBootstrap/应用服务测试。
- `tests/lan` 的完整 API、认证、WebSocket 和路径安全测试。
- `webui` 完整 Vitest、TypeScript build 和 Vite build。
- Desktop session close、库切换、LAN 启停/重启测试。
- 打包内容与入口测试。

Phase 3 起增加端到端链路：Desktop mutation → DomainEvent → LAN invalidation → WebUI HTTP refresh；LAN mutation → DomainEvent → Desktop projection refresh；断线错过事件 → reconnect → revision gap → snapshot recovery。

发布门槛是零新增失败、零契约漂移、零旧库事件污染，以及现有安全不变量全部保留。无法完成真实浏览器验收的阶段不得标记为最终收口。

## [S14] 非目标与未来提取点

本轮不拆分独立后端，不替换 SQLite，不实现多主协作或冲突解决，不将完整业务数据改为 WebSocket 推送，也不强制迁移到 React Query。

未来只有在 Desktop 不启动也需长期服务、需要 NAS/容器部署、多个客户端并发写入或 SQLite 不再满足并发时，才评估独立后端。完成本设计后，提取点将是 `LibraryRuntime` 的 ports 与 adapters，而不是重写业务服务。
