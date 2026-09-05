# 03 · application 应用服务层（AssetsManager/application/）

> 状态：**DATED ANALYSIS（2026-09-04 实测快照）** · deep-analysis 系列之一，索引见 [README.md](README.md)。
> 方法：并行只读勘察代理全量扫描 application/（60 个 .py，37,268 行实测）；分层纪律经全目录 grep 验证——application 不 import presentation/panels/lan（零命中）。

---

## 1. 模块全清单（行数实测，按域分组）

### 1.1 库/会话管理域（装配与生命周期）

| 模块 | 行数 | 角色 |
|---|---|---|
| `bootstrap.py` | 845 | ApplicationBootstrap：DI 容器装配、插件发现、runtime_for 工厂 |
| `runtime.py` | 211 | LibraryRuntime：每库运行时 + 生命周期适配器 + 事件路由宿主 |
| `context.py` | 324 | LibrarySession / LibraryContext：会话边界与操作租约 |
| `library_service.py` | 1468 | 开/关库、canonical session、restore 预约与恢复、隔离树清理 |
| `library_settings_adapter.py` | 287 | 库设置 ViewModel 适配器 |
| `library_watcher_service.py` | 277 | 常驻库目录轮询 watcher（→reconciliation 队列） |
| `library_governance.py` | 258 | 库治理策略 |
| `app_settings_provider.py` | 31 | G3 设置单例 seam |

### 1.2 资产管理域

| 模块 | 行数 | 角色 |
|---|---|---|
| `asset_service.py` | 433 | LAN 目录列表/目录缓存 |
| `asset_index_service.py` | 891 | asset_index 投影读写与发布 |
| `asset_index_reconciliation_service.py` | 1076 | 队列执行器（worker/sweeper/lease heartbeat） |
| `asset_filters.py` | 451 | 过滤类别/排序键纯函数 |
| `tag_service.py` | 548 | 标签 CRUD + 事件发布 + FTS 再索引 |
| `tag_canonicalizer.py` | 31 | 标签规范化 seam |
| `metadata_service.py` | 507 | notes/urls/rating/目录大小缓存 |
| `thumbnail_service.py` | 861 | 缩略图生成 |
| `thumbnail_cache_lifecycle.py` | 122 | 缩略图缓存键清理 |
| `favorite_service.py` | 211 | library_favorites（每 owner 上限） |
| `search_service.py` | 1133 | 多源搜索（tags/name/indexed/FTS/structured） |
| `search_index_service.py` | 271 | FTS 索引维护（迁移 v39 共享写者） |
| `search_syntax.py` | 391 | 搜索语法解析 |
| `collection_service.py` | 748 | 手动收藏集 + 智能查询视图 |

### 1.3 导入/导出域

| 模块 | 行数 | 角色 |
|---|---|---|
| `import_service.py` | 1576 | 复制导入 + 预算 + 重放 |
| `import_manifest_store.py` | 2557 | 持久导入意图 + 恢复 claim/lease + 恢复服务 |
| `file_operation_service.py` | 1588 | move/copy/delete/restore + 投影修复入队 |
| `relink_service.py` | 320 | 重定位库根后重链接 |
| `library_export_service.py` | 147 | 门面（Mixin 聚合） |
| `library_export_service_export.py` | 621 | 导出 Mixin |
| `library_export_service_restore.py` | 635 | 恢复 Mixin（预约 + 隔离区） |
| `library_export_service_validate.py` | 557 | 校验 Mixin |
| `library_export_service_types.py` | 84 | 结果/异常类型 |
| `library_export_io.py` | 756 | 无状态 IO/安全路径/恢复意图文件 |

### 1.4 基础设施服务域（对账/完整性）

| 模块 | 行数 | 角色 |
|---|---|---|
| `reconciliation_queue.py` | 2733 | 有界任务队列 + 转换 outbox（102 个 def） |
| `reconciliation_queue_store.py` | 2591 | SQLite 持久化存储（CAS 事务） |
| `reconciliation_queue_migration.py` | 335 | JSON marker → SQLite 单次 cutover |
| `filesystem_projection_repair_service.py` | 221 | move/delete/restore 投影修复执行 |
| `database_integrity_service.py` | 584 | quick_check + 元数据/缩略图孤儿修剪 |
| `database_maintenance_service.py` | 378 | vacuum / WAL checkpoint / 库大小 |

### 1.5 分享/认证域（每 Runtime 会话）

| 模块 | 行数 | 角色 |
|---|---|---|
| `auth_service.py` | 432 | 用户/邀请码/令牌吊销/密码成本迁移 |
| `share_service.py` | 460 | 分享链接 CRUD + 密码/过期/下载上限 |
| `free_download_quota_service.py` | 231 | 匿名下载配额（周期窗口 + 修剪） |
| `security_preflight.py` | 471 | LAN 安全预检快照/确认 |

### 1.6 其他域

undo_service(1061)、activity_recorder(157)、sequence_service(243)、plugin_service(121)、project_service(1125)、gallery_service(610) + gallery/ 子包（_incremental 1057 / _projection_builder 543 / _persistence 84 / _types 265）、ai_tagging/（service 88 / ollama_client 332 / write_policy 78）、media/（analysis 463 / decoders 369 / derivatives 589）、runtime_events(394)、desktop_ports(299)、command_registry(221)/command_executions(176)、__init__.py（252 行 re-export 门面，117 项 `__all__`）。

---

## 2. 核心装配链（bootstrap → runtime → context）

```
app.py（桌面组合根）
  └─ ApplicationBootstrap(container?)                      [bootstrap.py:299]
       ├─ install_app_settings_provider(...)               [bootstrap.py:318-319]  G3 seam
       ├─ install_event_bus_provider(get_event_bus)        [bootstrap.py:322]     G4 seam
       ├─ _register_services()                            [bootstrap.py:335-348]
       │     容器只注册【应用生命周期】服务：DatabaseManager、LibraryService、PluginService
       │     ——每会话服务【永不进容器】，全部在 _build_services 现场构造
       └─ library_service.add_session_closing_listener(_close_runtime)
          library_service.add_session_close_listener(_cleanup_session)
       │
       ├─ discover_plugins()                               [bootstrap.py:353-395]
       │     失败绝不静默：plugin_load_failures 记录各阶段；容器解析失败→降级 None
       │
       └─ runtime_for(session) → LibraryRuntime            [bootstrap.py:420-521]
            │  前置校验 owns_live_session（只认 canonical 会话）
            │  以 id(session) 为 key + Event 门闩实现【单飞创建】
            │
            ├─ _build_services(session) → LibraryScopedServices   [bootstrap.py:563-765]
            │   （session.operation() 租约内逐个构造，关键顺序：）
            │   SearchIndexService（FTS 唯一写者，迁移 v39）
            │   → AssetIndexService.for_session → SQLiteReconciliationQueueStore
            │   → migrate_reconciliation_marker（JSON→SQLite 一次性 cutover）
            │   → ImportManifestStore → ReconciliationQueue（cross_process_poll_interval=0.5）
            │   → ActivityRecorder / MediaDerivativesRecorder
            │   → FileOperationService → drain_pending_projection_repairs
            │   → FilesystemProjectionRepairService
            │   → ImportManifestRecoveryService + recover()
            │   → AssetIndexReconciliationService（max_worker_restarts=2）
            │   → RuntimeSharingServices: token_secret=secrets.token_hex(32)
            │       AuthService/ShareService + init_tables   ← 每个 Runtime 独享
            │   → LibraryExportService（restore_coordinator=library_service.restore_reservation）
            │   → TagService.for_session / UndoService
            │   → CommandExecutionStore + build_command_registry
            │   → Metadata/Thumbnail/Integrity/Maintenance/Collection
            │   → _lan_holder=_LanServicesHolder(...)        ← LAN 惰性投影
            │
            ├─ LibraryRuntime(session, services)            [runtime.py:20-37]
            │    每实例唯一 epoch=uuid4().hex、revision 计数器、event_router
            ├─ 注册生命周期适配器：integrity/maintenance/reconciliation
            ├─ _start_library_watcher（设置开关，非正间隔禁用）
            └─ 发布前再校验 owns_live_session + is_closed（防 TOCTOU）
                 reconciliation_service.start()
                 import_manifest_recovery.wait_for_ack(2.0)   ← 启动恢复的有界 ACK 窗
                 self._runtimes[key] = runtime（发布）
                 任一路径失败 → runtime.close() 清理
```

**LAN 惰性投影**（`_LanServicesHolder`，bootstrap.py:101-225）：
- **单飞（single-flight）**：每"代"只有一个线程构造 `LanRuntimeServices`（Asset/Project/Search/Gallery/Favorite）；同代等待者共享同一失败，后续调用者可开新代。
- **明文锁序契约**（:104-115）：只允许 `session 条件锁 → holder 条件锁` 的嵌套；`get` 的会话活性检查刻意在 holder 锁外——"ready"是单调状态，锁外快照仍有效，反向嵌套会死锁。
- `close_lan_services()`（:265-282）：GalleryService 构造时订阅全局事件总线（gallery_service.py:139-141），teardown 必须关闭已物化实例防订阅泄漏。

**会话关闭链**：`_close_runtime`（mark_closing 拒新工作 + 有界排空；仍有回调在飞 → TimeoutError，稍后重试）→ `_cleanup_session`（runtime.close() → 六标志位校验全归位，否则"cleanup pending"重试 → 从 _runtimes 摘除）。

### 2.1 runtime.py — LibraryRuntime

| 机制 | 锚点 | 要点 |
|---|---|---|
| services_snapshot | runtime.py:45-54 | UI 消费者必须捕获**自己绑定的 runtime** 的快照而非切换后重 resolve——生命周期边界显式 API 化 |
| register_lifecycle_adapter | :62-80 | open 时登记；非 open 时**立即调用 stop()** 兜底（注册晚于关闭的适配器不泄漏） |
| next_revision | :88-100 | closing 拒绝——除非当前线程是活跃事件回调（回调在 close 前获准进入，允许完成自己的 revision） |
| mark_closing | :102-113 | 状态迁移即"准许线性化点"；返回 False = 有界排空未完成，资源回收必须推迟 |
| close/_cleanup_adapters | :150-211 | 排空失败 → cleanup_pending + defer_after_drain 让最后回调完成回收；回收顺序 close_adapters → undo_service.cleanup → close_lan_services；异常 → state="failed" 并复位全部守护标志（后续 close 不永久卡死） |

### 2.2 context.py — LibrarySession / LibraryContext

| 机制 | 锚点 | 要点 |
|---|---|---|
| LibraryContext | :63-79 | frozen dataclass：root/data_dir/thumb_dir/db_conn/tag_store/project_data + 共享 `_SessionLiveness` 令牌 |
| connection_for | :115-130 | liveness 检查 + **请求根不匹配即抛错**（防跨库连接错用） |
| session_operation 装饰器 | :50-60 | 整个公开服务方法包在 session.operation() 租约里 |
| operation() | :220-238 | 线程本地深度计数 + 会话级活跃计数；`_ensure_access` 允许**已关闭会话上的在飞操作**继续——关库不打断进行中的工作 |
| _publish_while_live | :240-253 | 惰性 runtime 装配的原子发布点——要么在 close 前发布，要么被拒绝 |
| _finish_close | :287-316 | **30 秒有界排空**——卡死 worker 不能冻结 UI |

要点：db_conn 生命周期归 DatabaseManager，Session/Context 都不关连接。

---

## 3. 各域服务机制详解

### 3.1 undo_service — 撤销/重做的按库隔离

- **双重隔离**：①实例级——每 LibraryScopedServices 一个专属 UndoService（bootstrap.py:705-709），切库即换服务束；②字典级（遗留）——`_stacks: dict[str, ...]` 以 library_root 为 key（undo_service.py:315-318），实际是过渡兼容层（生产中每实例单 key）。
- **备份目录**：session 模式放 `<data_dir>/undo_backups/`（库树之外，watcher/索引永不扫描），**90 天**保留；失败回退系统 temp（**7 天** legacy 政策）且只降级不失败库打开。
- **活动实例保护**：`.assetsmanager-owner` sidecar 写 PID；启动清理遇活动目录跳过；Windows `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` 判活——仅 ERROR_INVALID_PARAMETER(87) 视为进程不存在，其余（含 ACCESS_DENIED）一律保守保留。启动扫描枚举 RuntimeData 全部库槽（含未打开库的崩溃遗留），上限 256 目录。
- **条目模型**：frozen UndoEntry；`callback` 钩子让**数据库级变更（标签/元数据）共享同一撤销栈**——Ctrl+Z 先撤销最近的标签变更；`children` 元组实现 batch 复合条目（50 文件删除 = 一条历史）；`degraded` 标记"文件恢复成功但投影快照未能重放"。
- **投影快照**：删除备份时在 db_write_lock 下 SELECT 三表行存 `<backup>.projection.json`；失败写 `.projection.failed` 哑标记——恢复路径能区分"旧版备份无快照"与"新备份快照失败"（后者报告降级恢复而非假装标签幸存）。
- **毒化条目**：执行失败的条目以 id 记入 `_failed_entries` 留栈顶，`skip_poisoned_undo/redo` 显式丢弃——一个失败条目不会堵死整条 LIFO；批量子条目全试（失败的保持回滚状态），聚合后整批作为"毒化单元"移动。
- **执行语义**：先执行文件系统操作、成功后才移动历史（并发 push 不让栈与文件系统脱钩）；push 淘汰最老并**清空整个 redo 栈**（经典 LIFO）。

### 3.2 reconciliation_queue 三件套 — G17 对账队列

**分工**：queue（内存状态机 + Condition + outbox drain）/ store（SQLite 事务后端，所有 CAS）/ migration（旧 JSON marker → SQLite 一次性迁移）。

**数据模型**：两种 Kind——ASSET_INDEX_ROOT_RESCAN（幂等重扫）与 FILESYSTEM_PROJECTION_REPAIR（精确修复，payload 严格校验：路径 resolve 到库根内、expected_state 精确匹配、restore 快照 ≤256KB/≤10000 行）；去重键 `(library_root, path, kind)`；`max_tasks=200` 有界，满时驱逐最老完成态。

**G17 三大机制**：
1. **Stop-the-world cutover（世代 CAS）**：store 的 `replace`（store:308-385）在 `BEGIN IMMEDIATE` 事务里读世代 → 不符即抛 retryable 冲突 → DELETE 全行 + INSERT + 世代递增 + 同事务写 outbox 批次。migration 的 cutover 是**显式单进程契约**（migration.py:99-100 明注 "single-process cutover contract"）；纪律"先持久化 SQLite 成功、后改名 marker 归档；归档失败异常携带 `durable_store_updated=True` 供下次只补归档"；非空 durable 队列只允许退役"空或完全等价"的 marker（等价比较刻意剔除 deadline 字段——monotonic 重读基线漂移不算冲突）。迁移读取**绝不构造队列**（构造器会做 lease recovery 改写 marker，把读变成写）。
2. **Lease recovery（租约恢复）**：队列**构造时**即恢复过期 running 任务（queue:751-757）；输掉跨进程世代竞争 → 降级只读加载新世代快照并**丢弃本方恢复事件**（另一进程已发布胜者快照），库打开不失败。过期 running → retryable（attempts 保留）或 terminal（耗尽）；恢复也内嵌在 `claim_next` 事务里——worker 领取时顺带观察恢复。
3. **Stale-worker protection**：全部完成原语带三重 CAS（task_id + expected_attempts + lease_token）；执行器 `_stale_completion_noop`（recon:801-848）把"陈旧完成"折算成 no-op；worker 心跳在 `renew_until = 开始 + worker_max_operation_age(300s)` 上限内续租，卡死扫描停止续租 → 租约过期被收回；**M6a-9 特例**：超龄但"已持久提交且 revision 仍是仓库当前值"的发布仍是权威完成。

**Durable transition outbox（v44/v45）**：每个队列状态迁移在**同一事务**里追加 outbox 行（进程崩溃不丢队列→manifest 交接）；drain：租一行 → 心跳续租（callback_max_age=300s）→ 调用**唯一持久消费者** → APPLIED/STALE 才 ACK、RETRY 归还重试；消费者身份**硬编码**为 IMPORT_MANIFEST_RECOVERY_CONSUMER_ID（outbox 只有一个 delivered_at 物理标记——schema 限制被编码成 API 限制）；v45 死信表：耗尽 → 不可变死信行，显式回放；有界保留 ACK 7 天/死信 30 天；内存队列（无 store）保留 advisory listener + 1024 有界 backlog——listener 注册前的恢复事件先缓冲不丢失。

**worker/清扫器**（AssetIndexReconciliationService）：`start()` 在 runtime 发布前启动 daemon worker + 周期 sweeper；`max_worker_restarts=2, backoff=1.0`——可从有界突发故障恢复但必须**可见地 faulted** 而非无限重启；process_once 是显式可测的 worker 边界；持久化冲突按 retryable/retry_after_refresh 分类，最多重试 2 次；错误分类学：RevisionConflict→stale、OperationalError→busy、FileNotFoundError→terminal、其余 OSError→scan_failed 重试。

### 3.3 import_manifest_store（2557 行）— 导入意图与恢复

- **单文件双类**：ImportManifestStore（持久意图）+ ImportManifestRecoveryService（恢复编排）。
- **Payload 三代版本**：v1/v2 JSON（≤10000 项、≤512KB）→ v3 stream 头 + `import_manifest_items` 行表（≤100000 项、总 ≤256MB、SHA-256 记账）——大清单走行存储而非放宽旧 JSON 上限。
- **状态机**：prepared→running→completed/degraded/cancelled/recovery_pending；项级 pending→copied/failed/skipped。
- **claim/lease**：`claim_recovery` 的 `UPDATE ... WHERE operation_id AND generation=期望 AND state IN 恢复态 AND (无 token OR 租约过期)`——generation+state+租约三重 CAS 原子认领，rowcount≠1 即失败；成功写 uuid token + 30s 租约。
- **双向联动**：恢复服务以唯一消费者身份注册为队列 outbox 消费者——任务 succeeded→acknowledge、running→mark_running、死信→重试或标记；反方向 bind_recovery_task 把 manifest 绑到 task_id。
- 启动时机：`recover()` 在 _build_services 中 + runtime 发布前 `wait_for_ack(2.0)`——**完成判定只来自 worker 的持久 ACK，绝不来自"入队被接受"**。

### 3.4 library_export_service*（导出/恢复/校验拆分）

- **拆分结构**：`LibraryExportService(ExportMixin, ValidateMixin, RestoreMixin)` 门面 + `library_export_io.py` 756 行**无状态函数库**（归档路径预检/zip 结构预检/reparse point 拒绝/恢复意图文件三件套/压缩炸弹防护）；Mixin 方法大多是一行转发。
- **导出**：create_backup → `_snapshot_database`（在线快照）→ `_iter_backup_files` → `_write_zip_file`。
- **恢复**：**restore_reservation 准入**（委托 LibraryService 预约状态机）→ 两步交换 → 失败进隔离区（只归档永不直接删，周龄折叠 + 数量上限 8/32）；恢复协调器经注入闭包与 LibraryService 握手，**acknowledger 闭包内做 generation + token 双重校验**防陈旧确认。
- **校验**：validate_backup → 打开备份（zip 结构/路径安全全检 + quick_check 快检连接）→ 提取。
- library_service 的 `_recover_interrupted_library_restore` 在下次开库时自愈中断的恢复。

### 3.5 gallery_service + gallery/ 子包

- **门面**：`GalleryService(PersistenceMixin, ProjectionMixin, IncrementalMixin)`——LAN WebUI 的只读文件系统投影，刻意与 ProjectService 分离（按可见目录而非用户配置深度）。
- **缓存层级**：内存 30s TTL → 库数据库持久投影 3600s TTL（286GB 库构建需数十秒，进程重启存活）→ 后台构建（miss 返回 building 信号，daemon 线程填缓存）→ 失败退避 60s。
- **增量机制**（_incremental.py）：订阅全局 FileSystemChanged（弱引用）→ 对消 add/delete 噪声 → 2s debounce → 对 _HomeState 树局部增删 → 沿祖先更新聚合计数 → 重算封面 → 无法局部处理时固定死线全量重建。generation 水位标记保证构建期间排队事件不被超越丢弃。
- **遍历预算**（_types.py:60-114）：时间/条目/解码数预算超限抛 413 类错误，跳过 PIL 解码只列文件。
- **关闭纪律**：取消事件 + 定时器取消 + 有界 join（5s）——join 是**响应性等待而非资源保证**，硬安全边界是 DatabaseManager 门控关闭（worker SQL 全走 db_write_lock/locked_read）。

### 3.6 runtime_events.py — 应用动作 → 领域事件 → 投影失效

```
应用服务发布领域事件（domain/events.py 12 类）到全局 EventBus
   ▼
RuntimeEventRouter（每个 LibraryRuntime 一个）订阅 12 类      [runtime_events.py:126]
   ▼ 三重过滤（:263-300）：
   1) session_token 匹配本 runtime 会话 event_token
   2) library_root resolve 相等
   3) 路径归一化到库根相对路径（全部不可归一化 → 返回 None 丢弃，防误刷全库）
   ▼
runtime.next_revision() 递增失效纪元
   ▼
InvalidationEvent(epoch, revision, domains, paths) → UI/面板订阅者按域刷新
```

- **域映射表**（EVENT_DOMAINS，:102-123）：FileSystemChanged → FILES/TREE/HOME/PROJECT_DETAIL/FAVORITES 等；MaintenanceChanged 等**纯 UI 通知刻意不映射**。
- **并发/关闭纪律**：每订阅者每线程计数；close 状态 accepting→closing→drained，有界等待 2s（2026-08-28 审计补丁：原来无死线）；超时保持 closing 而非谎报 drained；排空后回调线程自己执行 defer_after_drain 完成延迟清理。

### 3.7 desktop_ports.py — UI 端口抽象（依赖倒置）

8 个 Protocol（全部 runtime_checkable）+ 1 适配器：TagsViewPort（根绑定标签操作，无 library_root 参数）、ShareSettingsPort（LAN 工具面；由 `lan.ports.LanDesktopAdapter` 实现——对话框**永不 import lan 包**）、FallbackShareSettingsPort（无依赖默认实现，不伪造 Authorization 头）、LanControlPort + LanServerFactory（LAN server 生命周期窄面）、MetadataViewPort（root-first，保留前导参数——与标签端口约定**不同**，文件内注释了差异）、FileOpsViewPort（会话绑定文件操作 + last_operation_id/drain_refresh_diagnostics）、**ScopedServicesConsumer**（`set_scoped_services(services, *, runtime=None)` 统一注入入口——MainWindow 给所有 scoped 面板发同一份不可变服务束）、RootBoundTagService（兼容旧调用者的适配器）。

设计意图：面板只见**每个服务实际用的窄切片**；UI 可以在无 LAN 组合时安全运行。

---

## 4. 设计取舍（值得肯定）

1. **容器只装应用级服务**（bootstrap.py:335-348 注释）：每会话服务需要活的 LibrarySession，永远不进容器——避免"容器给错作用域"的常见 DI 反模式；作用域边界靠 runtime_for + services_snapshot 显式化。
2. **frozen 不可变数据类 + 显式可变 holder**：LibraryScopedServices frozen 保值语义，LAN 惰性投影的可变性收拢到 _LanServicesHolder 单点。
3. **fail-closed + 降级而非失败**：marker 迁移冲突即抛错不静默丢任务；LAN 物化输掉世代竞争降级只读；undo 备份目录不可用回退 temp 只降级保留策略；插件失败记录 id 不吞异常。
4. **每处并发契约都有书面锁序注释**（_LanServicesHolder :104-115、gallery close、migration 读路径）——高强度并发代码库的可维护性投资。

---

## 5. 弱点 / 技术债清单

| # | 问题 | 锚点 |
|---|---|---|
| W1 | **超大模块**：reconciliation_queue.py 2733 行/102 def（13 dataclass + 2 异常 + Protocol + 队列 + outbox drain 同文件）；store 2591 行；import_manifest_store 2557 行（双类同文件）；file_operation_service 1588；import_service 1576；library_service 1468。gallery 已示范"门面+子包"拆法，reconciliation 三件套应同样拆分 | wc -l |
| W2 | **受控循环依赖**：runtime.py:8 顶层 import bootstrap，bootstrap.py:427 延迟 import runtime——能跑但脆弱，任何人在 bootstrap 模块级 import runtime 即爆环 | runtime.py:8、bootstrap.py:75,427 |
| W3 | **跨模块私有访问**：_build_services 直接读 library_service._session_generations/_root_generation；close_lan_services 摸 _lan_holder._state/_value；_cleanup_session 摸 runtime._condition/_state——契约脆弱 | bootstrap.py:565,578,274-277,829-834 |
| W4 | **Runtime 关闭状态机 6 标志位**联合表达生命周期——状态空间大，靠注释与防御性校验维持；历史审计注释显示这类并发路径出过无死线问题 | runtime.py:26-35、runtime_events.py:39-41 |
| W5 | **UndoService 双轨制未清**：_stacks 字典是半死代码（生产中单 key）；`library_root=""` legacy 共享栈路径保留；RootBoundTagService 保留无 session 旧构造 | undo_service.py:315-318,296-297、desktop_ports.py:263-267 |
| W6 | **outbox 单消费者硬编码**：拒绝除 import_manifest_recovery 外的任何 id——"物理 outbox 只有一个 delivered_at"是 schema 限制被编码成 API 限制，第二消费者出现时需 schema 演进 | reconciliation_queue.py:27,856-890 |
| W7 | **G17 单 owner 边界是隐式前提**：跨进程安全依赖"同一库同时只有一个应用实例持有"；世代 CAS 只在应用内防竞争；migration 自己的注释承认"Cross-process marker locking remain a later phase"——双开应用的容错是部分而非完全 | README:153、migration.py:99 |
| W8 | **Mixin 拆分的隐式契约**：ExportMixin 等通过 self._connection_provider 等宿主属性通信，mixin 不能独立构造/单测；gallery/_incremental.py 1057 行 mixin 尤其重 | library_export_service.py:57、gallery_service.py:55 |
| W9 | **参数校验样板占比过高**：AssetIndexReconciliationService.__init__ 152 行里约 130 行手工 isinstance/isfinite——无 pydantic/dataclass 验证层，纯手写重复 | asset_index_reconciliation_service.py:101-193 |
| W10 | **__init__.py 全量 re-export 门面**（252 行、117 项 __all__）：把"包内符号可见性"做成平铺 API，鼓励星号导入耦合 | application/__init__.py:135-252 |
| W11 | **魔法常量分散**：max_tasks=200、callback_max_age=300、backlog 1024、max_worker_restarts=2/backoff=1.0/conflict_retries=2 分散三文件，无集中策略配置 | reconciliation_queue.py:28,745、bootstrap.py:678-683 |
| W12 | **desktop_ports 双约定**：TagsViewPort 无 root 参数、Metadata/FileOps 保留前导参数——同文件两种调用约定（文件自己注释了差异），调用者易混淆 | desktop_ports.py:23 vs 169 |

---

## 6. 总评

`application/` 是整个项目的**工程化重心**：装配链职责清晰、并发纪律严格（租约/世代 CAS/有界排空/书面锁序），reconciliation/manifest/export 三大子系统构成了一套小型的"outbox + 租约 + 死信"分布式队列语义（尽管运行在单机 SQLite 上）。主要债务集中在**规模失控的单文件**（W1）、**私有成员跨界访问**（W3）和**双轨遗留路径**（W5/W10）——不影响正确性，但显著抬高后续维护与测试的边际成本。

---

**关联阅读**：core 的连接门/身份标记如何被本层消费 → [01-core.md](01-core.md)；仓库层 for_session 绑定 → [02-domain-repositories.md](02-domain-repositories.md)；runtime 事件如何抵达 UI/WS → [04-lan.md](04-lan.md) 与 [08-entry-and-window-assembly.md](08-entry-and-window-assembly.md)。
