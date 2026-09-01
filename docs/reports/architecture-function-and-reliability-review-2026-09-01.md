# AssetManager 架构、功能与可靠性复核（2026-09-01）

> 状态：当前工作树的架构/功能总览与专家复核结论。本文为决策和长期任务的导航，不替代 [架构事实](../architecture.md)、[迁移事实](../migrations.md)、[专家团深度报告](expert-panel-deep-analysis-2026-08-31.md) 或 [架构可靠性长期任务](../plans/architecture-reliability-roadmap-2026-08-31.md)。
>
> 复核范围：源码静态走查、迁移 v44、导入恢复状态机、reconciliation queue 的持久 transition outbox，以及此前架构、安全、性能和双端体验专家结论。工作树同时存在其他未提交改动；下列“已实施”只表示当前可观察实现，不等同于发布验收。

## 结论先行

项目的合理方向不是拆成微服务，而是继续把“桌面即服务器”的单进程、本地优先模型做扎实：桌面端和 LAN/WebUI 复用同一个按库作用域的 `LibraryRuntime`，文件系统与 SQLite 是权威事实，长任务通过可恢复状态机收敛。

当前最应该优先处理的不是增加功能，而是把跨事务恢复信号真正做成可证明的交付契约。迁移 v44 已加入持久 transition outbox，消除了仅靠进程内 listener 的一大类丢事件窗口；但它还没有达到 H1 的退出条件。尤其是 manifest listener 吞掉数据库错误后，outbox 仍会被 ACK，这会把“回调返回”误记为“依赖状态已持久化”。

## 1. 当前架构

```text
PySide6 Desktop          aiohttp LAN API / React WebUI
        \                       /
         \                     /
          ApplicationBootstrap
                  |
       LibrarySession / LibraryRuntime (per library)
                  |
  application services, recovery, queue, event routing
                  |
    repositories / domain contracts / SQLite migrations
                  |
  filesystem, SQLite WAL, cache, plugins, settings, networking
```

| 层级 | 职责 | 当前关键机制 |
|---|---|---|
| 表现层 | PySide6 面板与对话框、LAN routes、React SPA | 只经控制器或 application service 访问业务；Qt 信号留在 UI 边界 |
| 应用层 | 用例编排、会话生命周期、后台任务 | `ApplicationBootstrap` 装配每库 `LibraryRuntime`；桌面与 LAN 共享服务快照 |
| 领域/仓库 | 业务概念、领域事件、持久化接口 | 领域事件驱动投影失效；仓库按 session 绑定，使用事务和 CAS |
| 基础设施 | SQLite、文件系统、迁移、锁、缓存、设置、网络 | 每库数据库、WAL、迁移契约、库锁与路径安全原语 |

与恢复一致性最相关的数据流如下：

```text
ImportService -> ImportManifestStore -> ReconciliationQueue -> worker
       ^                                                      |
       |                   durable v44 transition outbox <---+
       +----------- ImportManifestRecoveryService <-----------+
```

queue 的状态变更与 outbox 写入位于同一 SQLite 事务；outbox 以严格事件顺序、delivery lease 和 token CAS 交付。慢 canonical callback 期间会有有界 lease heartbeat，超过 callback age 后停止续期并拒绝迟到 ACK。这是正确的 at-least-once 基础。`ImportManifestRecoveryService` 再用 operation、library、path、kind 与 manifest generation/CAS 把状态回写到导入恢复记录。

## 2. 主要功能地图

| 领域 | 已有能力 | 边界/说明 |
|---|---|---|
| 本地资产库 | 文件浏览、网格/列表、缩略图、元数据、标签、评分、搜索、项目/合集、主题与国际化 | 核心体验在桌面端；数据按 library session 隔离 |
| 文件操作 | 复制、移动、重命名、删除、回收/撤销重做、索引与缩略图失效 | 应由 application service 统一处理路径、元数据与投影 |
| 导入与恢复 | 扫描、预算、指纹、复制、行式 manifest、恢复 claim/lease、后台 reconciliation | v43 解决大 manifest 父 JSON 膨胀；v44 解决 queue transition 的持久交付基础 |
| LAN 分享 | 浏览、搜索、缩略图/原图、下载/ZIP、分享链接、认证、配额、WebSocket 失效通知、隧道 | WebSocket 是缓存失效提示，HTTP/revision 是权威恢复面 |
| 扩展与自动化 | 插件、三语、MCP 服务端入口 | 插件与宿主同解释器，不应被表述为安全沙箱；MCP 的统一授权与审计仍是后续工作 |

产品和文档应继续以 [ADR 0005](../adr/0005-commerce-extraction.md) 为准：已剥离的商城不应作为当前可用功能对外承诺。README、spec 或历史报告中仍出现的商城描述属于待收敛的文档/构建债务，而非新增产品路线。

## 3. 已验证的基础优势

1. **按库隔离已是系统主轴。** `LibrarySession`、`LibraryRuntime`、数据库连接、事件过滤和服务快照为桌面与 LAN 共用，而不是两套业务实现。
2. **工程门禁成熟。** 迁移版本与 schema contract、分层边界检查、Python/前端类型与测试门禁提供了可重复的回归基础。
3. **恢复链路从内存回调走向持久化。** v44 的 outbox 使用 `BEGIN IMMEDIATE`、delivery token 和 lease；租约过期后可重新领取，旧 token 不能 ACK 新 owner。
4. **风险意识正确。** manifest、路径、导入预算、worker lease、WebSocket gap recovery 均已经有显式模型，下一步应补齐故障语义，而不是以“正常路径可跑”代替可靠性证明。

## 4. 专家团优先建议

### H1：恢复与事实一致性

| 优先级 | 发现 | 建议 | 最小验收 |
|---|---|---|---|
| P0 | `handle_task_transition()` 记录 DB 错误后返回；`drain_transition_outbox()` 因 listener 未抛错而 ACK | listener 返回显式 disposition（`APPLIED`、可证明的幂等 `STALE`、`RETRY`）；只有前两者 ACK | manifest DB 暂不可用时 `delivered_at` 保持空，恢复后自动回放并仅 ACK 一次 |
| P1 | 通用多 listener API 只有一个全局 `delivered_at` | 已将 outbox 收敛为唯一 `import_manifest_recovery` canonical consumer；通用 listener 为 ACK 后 observer。未来第二个独立 durable consumer 才引入 `(event_id, consumer_id)` receipt | 当前 observer 失败不阻塞 ACK 或重放 manifest；第二 durable consumer 出现后，必须验证 A 成功、B 失败时只重放 B，以及受策略控制的历史 |
| P1 | drain 只在 mutation、注册或显式 recovery 时运行，且单次上限 64 | 增加有界后台 drainer，具备停止语义、jitter、退避和可观测性 | 65+ 条积压、一次 listener 失败后，在无新 mutation 情况下全部推进 |
| P1 | 最早损坏 outbox 行会卡住严格顺序；decoder 对 previous/current snapshot 的 task 身份校验不足 | 原子隔离 poison row，记录诊断；每个 snapshot 都校验 event task id 和 operation scope | 坏 JSON/坏 snapshot 被隔离，后续合法事件可交付且不污染 manifest |
| P1 | fail 原先立即释放 lease，无退避、最大尝试、死信或 retention | 已有 `next_delivery_at`、指数退避、默认八次尝试和 v45 dead-letter；应用层已提供人工 replay、ACK/dead-letter bounded prune 与 metrics，正式 retention 调度仍待接入 | 持续失败不热循环；第八次保留死信并释放后续 head；老 ACK 按策略清理，age/attempt/dead-letter 有指标 |
| P2 | 同一 attempt 只用状态 marker 去重，不能表达完整状态偏序；enqueue->bind 关联仍以 operation id 为主 | 持久化单任务 event sequence/允许的 phase graph；为 recovery attempt 保存 epoch/nonce | terminal 后的低序状态不回退；旧 task 或旧 attempt 无法写入新 recovery |

这组工作的第一步已经收敛：`import_manifest_recovery` 是唯一 durable consumer，`APPLIED/STALE/RETRY` 是其确认协议，通用 listener 是 ACK 后 observer。SQLite outbox 已有有界 delivery-lease heartbeat；普通失败的终态、人工 replay、bounded retention/prune 和 age/attempt/dead-letter metrics 已落地；只有新增第二个独立 durable projection 时才扩展为 per-consumer receipt。后续工作聚焦正式 retention 调度与 crash-replay 证据。

### H2：安全、传输与实时边界

- 把插件定义为可信代码扩展，而不是安全隔离；公网/隧道场景应先完成显式信任、签名或进程隔离路线。
- 收敛 LAN/MCP 的认证、能力、撤销、限流和审计为单一 policy；不能依赖 handler 内临时 Bearer 校验和 `public` route policy 的组合。
- 下载、预览和 ZIP 采用受预算的分块流，权限/内容检查、打开文件和响应投影绑定同一 owned handle/identity；为取消、断连和临时盘清理提供门禁。
- WebSocket envelope 需要版本与 schema，客户端 identity 切换要 abort 旧请求并对 `then/catch/finally` 均做 generation/epoch 守卫。

### H2/H3：架构可维护性与规模

- 逐步收敛全局 singleton/Service Locator，先把高频 `AppSettings` 和事件订阅接入既有 provider/session seam；不需要一次性重写 DI。
- 让 domain 不再反向依赖 core，清理 UI 的直接全局事件订阅；关闭超时应保留可诊断状态，不能把未排空写成 drained。
- 将大文件按稳定职责切分（数据库身份/写闸门、queue store/dispatch、LAN lifecycle、桌面加载器），每一刀都先补契约测试。
- 用容量与延迟指标决定何时引入读连接、FTS 分片或 JobRunner；不要在没有触发信号时替换 SQLite 或拆服务。

## 5. 长线任务

本任务已建立为活动目标：**把架构、功能和专家结论持续沉淀为可执行、可验证的可靠性改进。** 路线以 [架构可靠性长期任务](../plans/architecture-reliability-roadmap-2026-08-31.md) 为执行账本，按以下顺序推进。

| 阶段 | 目标 | 退出条件 |
|---|---|---|
| R1：outbox 交付语义 | 完成 consumer 身份、ACK disposition、自动 drain、退避/死信/retention 与 poison 隔离 | crash、DB 暂不可用、slow listener、多进程、坏事件、65+ backlog 的集成测试与指标通过 |
| R2：导入恢复闭环 | 统一 manifest 流式规划/预算、task epoch、状态偏序和 enqueue->bind kill-window 证明 | 进程中断、旧 attempt、双连接 claim、人工重试均不伪造完成或回退状态 |
| R3：安全 I/O 与契约 | owned-handle 流式传输、MCP policy、TLS/隧道、WebSocket schema/gap recovery | LAN/Playwright 安全与断连测试，资源/临时盘/worker 配额可观测 |
| R4：规模与产品收口 | 任务平台、派生物生命周期、容量治理、检索/活动/分发体验 | 仅在指标触发后引入扩容基础设施；每项有回滚、迁移和负载证据 |

每轮只把一项标为完成，且必须同时提交：实现或测试、故障/并发证据、回滚说明、指标变化和本文/路线图的状态更新。没有运行时故障注入与跨进程验证时，保持“进行中”，不以静态检查替代。

## 6. 推荐观测项

优先暴露：outbox pending 最老年龄、delivery attempts、lease 过期、`last_error`、poison/dead-letter 数、消费延迟、manifest `recovery_pending` 年龄、worker queue 深度、SQLite 写等待、导入/ZIP 的源字节与临时盘占用、WebSocket gap recovery/abort/stale-drop、MCP 拒绝与 worker 排队时间。

这些指标同时是后续是否需要读连接池、JobRunner、FTS 分片或容量策略的触发信号。

## 7. 证据入口

- [当前架构](../architecture.md)
- [当前迁移说明](../migrations.md) 与 [`CURRENT_SCHEMA_VERSION = 44`](../../AssetsManager/core/db_migrations.py)
- [专家团深度分析](expert-panel-deep-analysis-2026-08-31.md)
- [全局综合分析](global-synthesis-analysis-2026-08-31.md)
- [架构可靠性长期任务](../plans/architecture-reliability-roadmap-2026-08-31.md)
- [transition outbox schema](../../AssetsManager/core/schema_defs.py) 与 [dispatch 实现](../../AssetsManager/application/reconciliation_queue.py)
