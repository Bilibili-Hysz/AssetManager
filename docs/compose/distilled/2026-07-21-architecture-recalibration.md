# 2026-07-21 架构重定标批:Desktop-LAN-WebUI 分层与运行时(决策摘要)
> 状态:**历史蒸馏(已完结会话摘要)** · 2026-08-27 内容级合并自 compose-raw 原件,原件见 docs/archive/2026-08/compose-raw/ · 状态登记:2026-09-02(文档梳理轮补登)


> 摘要起草: 2026-08-27 · 源文件(15 份):`docs/compose/specs/2026-07-21-{desktop-lan-webui-architecture-closure-design,desktop-lan-webui-architecture-design,desktop-lan-webui-architecture-recalibration-design,realtime-dataflow-hardening,runtime-event-router-design,project-library-workspace-design}.md` + `docs/compose/plans/2026-07-21-{desktop-lan-webui-architecture-migration,desktop-lan-webui-architecture-recalibration,desktop-lan-webui-architecture-task-d,desktop-lan-webui-architecture-closure,realtime-dataflow-hardening,runtime-adapter-failure-ownership,runtime-event-router-implementation,project-library-workspace,webui-resource-library-workspace-redesign}.md` · 原件归档: `docs/archive/2026-08/compose-raw/`

## 背景

- 原始迁移(0-5 期)建立结构地基(LibraryRuntime 缓存、Runtime 注入 LAN 组合、DTO、SessionPrincipal/capabilities、epoch+revision、WS 硬化、React RealtimeProvider),但 07-21 current-state audit 判定"全绿测试不等于架构收口":生命周期交错、身份转换、投影 producer 缺可执行证据;迁移兼容路径仍留在生产。
- **重定标取代七任务 closure 计划**:基于"当前代码+全新基线"只做架构收口,UI 产品差距单列;recalibration 计划成为**唯一可执行任务链**(Task A→E),migration/closure 计划历史化(Historical-plan rule,不得并行执行)。

## 核心决策

### 分层边界
- **模块化单体**:`ApplicationBootstrap → LibraryRuntime(每个 canonical LibrarySession 恰一个)→ Desktop/LAN/React 适配器`;Desktop 直调应用服务不经本地 HTTP;SQLite/文件系统为权威,WS 只传失效通知 | architecture-design [S2-S4]
- **单一组合边界**:`runtime_for(session)` 是唯一生产 Runtime 组合入口;`for_library()/cleanup_library()` 在 Task D 删除 | [S5]
- **禁路由自组装**:LAN 路由只解析 request/runtime/principal,不得从裸连接构造服务;静态门禁强制 + DTO 不 import Qt、打包清单 | migration Task 8/16
- **显式公共 DTO + golden payload**:Python/TS 用同一 golden 驱动,禁止双端手写 mock 宣称契约正确 | [S6]
- **兼容与回滚**:新旧入口并存最多一阶段并证明等价后立即删除;字段改名优先短期双写,不建长期 /api/v2 | [S11/S12]

### 运行时与服务作用域
- **Runtime 职责**:拥有 session/services/event_router/epoch(每次创建不可预测)/revision(单调)/幂等 close;不吸收 route/Qt/React 逻辑 | [S5]
- **canonical 关闭顺序(硬契约)**:live → mark closed(拒新 lease)→ stop 各 adapter → drain → 清 session-owned cache → 移除缓存所有权 → 关 per-library DB;`session_closing` 为前置边界 | recalibration [S3]
- **失败可观察可重试**:adapter stop 失败保留 actionable handle + failed state,close 不得报"干净关闭";`ShareManager.stop()` 不得把 live server 变 None/stopped | closure [C1]
- **server generation 注册语义**:构造/startup commit 成功后才注册,每次 start 恰好一次;构造失败永不进 lifecycle_adapters;terminal rollback 注销,不完整清理保留供重试 | Task A

### 事件路由与实时
- **每 Runtime 一 Router**:只订阅五类 session-scoped 事件(FileSystemChanged/AssetTagsChanged/TagCatalogChanged/AssetNotesChanged/AssetUrlsChanged);接受条件=token+root+未关闭+映射非空;非法 token/legacy 事件/未知/路径无法归一化 → 整事件静默忽略且不增 revision | event-router-design [S2/S4/S5]
- **InvalidationEvent**:frozen;epoch+revision+domains+paths(相对根 POSIX、去重、禁 ../ 逃逸);不携带连接/凭据 | [S3/S5]
- **domain 契约**:基础六域(files/tree/home/project_detail/metadata/tags);Task C 补 producer 域 shares/users/activity/online_users;stats 无 producer 显式 Unavailable 禁恒零;search 视为 files/metadata 投影 | recalibration [S4]/closure [C4]
- **epoch+revision 自愈**:epoch 变化/跳号/解析失败/重连不确定 → 投影完整补拉;阶段一不把 revision 高频写 SQLite | [S8]
- **原子 WS admission**:新连接先收 runtime_ready 基线、准入屏障后才收广播;admission 期间 mutation → 重读 cursor;空 cursor ready 必须触发一次权威 /api/revision fan-out;失败不留 client/pong/presence 残留 | realtime-hardening [S2/S5]
- **实时鉴权非一次性**:连接保留 canonical identity,用户禁用/降级/吊销时停广播并按正常生命周期清理;拒绝 query 凭据 | [S3]
- **统一 eviction**:heartbeat 与 broadcast 失败共用幂等清理路径(移除/关闭/记账/presence) | [S5]
- **React 单 realtime provider**:capabilities.realtime 门控、指数退避(1s→30s+抖动)、cursor/gap 检测、domain registry、身份/卸载关旧连接;页面不再自行解释 WS | architecture-design [S9]
- **cookie-only 身份**:登录/注册/密钥校验只 Set-Cookie(HttpOnly lan_token),响应无 token 字段;AuthContext 以 /auth/me 为权威;401/logout/身份切换清全部前端状态;`/browse` 与 `/detail` 共用 capability 守卫,公开路由单独作用域 | [S7]/Task B/closure [C3]

### 工作区模型
- **/browse 为项目库工作区**:配置深度目录=项目;`is_project` 由服务端 ProjectDepthConfig 权威判定,客户端不得推断 | workspace-design [S2/S9/S10]
- **信息架构**:TreeList=层级索引;FileList 消费单份 ProjectListing(folder/project 分区、工具栏分开计数);InfoPanel 仅对项目请求 `/api/projects/{path}`;单击=检查、双击/Enter=打开、显式选择模式才入批量;Detail 页 tag 返航 /browse?tag= | [S3/S4]
- **边界保留**:不替换 /api/files 与 AssetService、不改 ProjectDepthConfig、本批不加分享/权限面 | [S9]

## 任务链与门禁实录

- 唯一可执行链 Task A→E;每任务 TDD red→green→focused gate。
- Task A closed-lifecycle `210 passed`;Task B(front) focused 74 + WebUI 35 files/267;Task C backend 77 + WebUI 7 files/35(全 Python 1555/1);Task D focused 402、全量 1590 passed/1 skipped、WebUI 37 files/289、build 1632 modules、无 for_library/cleanup_library 残留;Task E 发布门真实矩阵收口,决策=`delivered`(Ubuntu WSL symlink gate 1 passed/23 deselected)。

## 落地状态(2026-08-27 抽查)

- `bootstrap.py`:`runtime_for`(owns_live_session + id(session) 缓存 + 单飞);`add_session_closing_listener(_close_runtime)`/`add_session_close_listener(_cleanup_session)`("Runtime cleanup is pending" 重试语义);无 for_library/cleanup_library;`_LanServicesHolder` 单次惰性投影。
- `context.py`:`LibrarySession` 的 `event_token/_begin_close/_finish_close(30s drain)/_publish_while_live/connection_for 异库拒`。
- `runtime_events.py`:ProjectionDomain 14 值(六基础+favorites/shares/users/activity/online_users/shop/orders/quota);EVENT_DOMAINS 覆盖五类原事件+Task C producer;过滤/归一化/逃逸拒绝/subscriber 隔离/drain 2s/三态 close。
- `workspace_bar.py`:WorkspaceBar/WorkspaceSection 为桌面 UI tab 状态,未涉及 Runtime 组合(与 Task D 约束一致)。

## 仍生效的约束或未决项

- Windows symlink skip 与发布决策分离,Linux 必须跑(现以 Ubuntu WSL 证据通过)。
- stats 无 producer 序列化 null/Unavailable,禁恒零。
- 永不引入:第二组装路径、持久 revision store、独立后端进程/微服务、Redis/Kafka、React Query、WS 业务对象传输、破坏性 schema migration。
- 产品级未决(路线图):登录页视觉、移动 UX、分享/标签 UX、下载进度、主题;独立后端提取点仅在 NAS/容器/多写场景评估。
- 两份补充实现计划(runtime-adapter-failure-ownership、runtime-event-router-implementation)范围已并入 Task A/Task C,不应再按 checkbox 单独执行。