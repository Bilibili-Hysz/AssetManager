# AssetsManager 深度代码质量、架构、工作树与依赖治理审计（2026-08-20）

## 1. 执行摘要

本报告补充以下已完成的审计快照：模块内全量扫描、跨模块数据流/API、性能与时序。范围是代码可维护性、架构边界、当前工作树可提交性、文档权威关系、依赖可复现性和发布治理。

本轮未修改生产代码、测试或工作树，未运行 pytest、npm、pip、PyInstaller、网络漏洞扫描或发布。除文档审查代理所做的只读结构性检查外，所有运行态结论都明确标记为待动态验证。

**没有新的 P0。** 已确认的高优先级质量问题集中于：

- session-bound 服务和 DI 组合根仍允许 raw/foreign connection 与 session-sensitive service 构造旁路。
- 仓储事务所有权尚未统一，单项/批量文件操作、metadata URL、auth/favorite/gallery 等路径表现不一致。
- 插件全局贡献没有来源所有权和并发生命周期状态机，卸载或并发 load/unload 可能破坏分类/theme/host 状态。
- 当前未提交 Desktop 异步改动存在 3 项提交前 P1：Qt cover-scan 回调线程亲和性、拖放异常被伪装为成功、pool drain 超时后析构可能再次阻塞。
- HTTP/WebUI DTO、错误与身份世代存在双来源和局部绕过，导致状态/API contract 难以长期维护。
- 文档把过期 `full-review` 快照称为当前权威，迁移、路由和运行结果出现冲突。
- Python 依赖、Actions pin/permissions、release provenance、SBOM/许可证和发布 gate 治理不足。

## 2. 审计边界与权威层级

### 2.1 审计范围

- Python：`core`、`domain`、`repositories`、`application`、`controllers`、`lan`、Desktop panels/widgets/dialogs、plugins。
- WebUI：API client/types、contexts、hooks、state、route/pages/component data access。
- 工程：当前 Git worktree、README/docs/ADR、requirements/npm lock、PyInstaller、workflows、release/nightly、生成器、许可证/SBOM。

### 2.2 建议的文档权威模型

| 层级 | 权威对象 | 允许内容 | 禁止内容 |
|---|---|---|---|
| L0 | 代码、测试、CI 配置 | 当前可执行事实 | 手工历史运行数字替代代码 |
| L1 | README、development/testing/migrations/architecture | 带 commit 的当前操作说明 | 未验证的“当前通过”声明 |
| L2 | ADR | 长期决策、accepted/superseded 状态 | 可变实施进度作为唯一事实 |
| L3 | full-review、compose reports/handoffs/plans | 日期/commit 固定的审计和交接快照 | “当前工作区权威”措辞 |
| L4 | history/已完成计划 | 追溯材料 | 当前验收依据 |

当前 schema 以 `AssetsManager/core/db_migrations.py:46` 为 L0，路由以 `AssetsManager/lan/api.py:241` 为 L0。任何文档数字均应能追溯到这两类源或带 commit/run ID 的 CI artifact。

## 3. 架构实况与组合根

```text
ApplicationBootstrap
  -> LibraryService.open_session
  -> LibrarySession(root, managed connection, operation lease)
  -> runtime_for(session)
  -> LibraryRuntime(service bundle, event router, adapters)
       |-> Desktop scoped services
       |-> lazy LAN services/server
       |-> repositories/application services
       |-> managed SQLite / LibraryLock
```

现有 `check_layers.py`、architecture tests、session/runtime ADR 和 route policy 已提供强基础：静态层方向、LAN 不依赖 Desktop、部分 raw DB 访问限制、session operation、managed connection owner、route policy/DTO 生成均有门禁。

但静态层方向并不保证运行期组合根唯一、session/resource binding 完整或全局 provider 可恢复。本报告的重点是这些“静态层正确但运行期边界仍可旁路”的路径。

## 4. 已确认架构与代码质量问题

### CQ-01 FavoriteService 允许 foreign/raw connection，未实现 canonical session binding

- **级别/置信度**：P1 / 高。
- **位置**：`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\favorite_service.py:22,43`；构造 `application/bootstrap.py:686`。
- **证据链**：FavoriteService 保存 `session`/provider，但显式 `db_conn` 和 provider 结果统一走 `allow_unmanaged=True`，没有校验 session root、canonical managed connection 或关闭状态；对比 Metadata/Tag/Index repository 的 `for_session` 契约。
- **影响**：调用者可以让“属于 session A”的 favorite 操作实际读写 B 或 unmanaged connection，事件却仍以 A 的 runtime/root 发布；生命周期与跨库隔离成为约定而非执行边界。
- **建议**：实现严格 session 分支，锁定 root identity/provider/connection，闭合后拒绝访问；raw 模式只由显式 compatibility factory 提供。
- **最小门禁**：跨 root、foreign managed connection、unmanaged connection、closed session 都必须失败且不执行 SQL。

### CQ-02 GalleryService 的 persistence mixin 仍是 raw compatibility path

- **级别/置信度**：P1 / 高。
- **位置**：`application/gallery_service.py:68,368,459`；`application/gallery/_persistence.py:32`。
- **证据链**：GalleryService 声明 session/provider，核心 get_home/get_collection 仍接受 caller db_conn；persistence `_connection` 无 session root/liveness 检查并允许 unmanaged connection。
- **影响**：gallery cache/projection 可绕过 LibrarySession root/operation/managed owner；runtime lazy LAN service 的实际边界与 Metadata/Tag/Index 不一致。
- **建议**：将 persistence connection 改为 instance session-aware accessor；session 模式禁止 caller 覆盖 db_conn，legacy raw 模式独立构造。
- **最小门禁**：同 CQ-01，增加 lazy LAN materialization 正常回归。

### CQ-03 DI container 注册 session-sensitive 服务，保留第二组合根

- **级别/置信度**：P1 / 高。
- **位置**：`application/bootstrap.py:319,608`；`di/__init__.py:112`；`application/file_operation_service.py:207,495`。
- **证据链**：Bootstrap 将 Metadata/Tag/FileOperation/Thumbnail/Search/Index/Undo 等注册为无 session singleton，同时正确 session bundle 又会构造 scoped instance。`resolve()` 缓存 singleton，而部分服务可在无 session 下执行部分操作。
- **影响**：未来 `container.resolve(FileOperationService)` 可以绕过 runtime bundle，缺 session lifecycle、event/index refresh 或 root binding 的单独业务路径。
- **建议**：container 仅注册 application-wide service；session service 使用显式 factory/LibrarySession 参数，并只能由 runtime bundle 暴露。
- **最小门禁**：architecture test 禁止注册/resolve session-sensitive class；扫描生产 `container.resolve` 调用。

### CQ-04 runtime/bootstrap 和 desktop_ports/tag_service 存在被 deferred import 隐藏的循环

- **级别/置信度**：P2 / 高。
- **位置**：`application/bootstrap.py:405`；`application/runtime.py:8`；`application/tag_service.py:414`；`application/desktop_ports.py:246`。
- **证据链**：runtime_for 函数内 import LibraryRuntime，runtime 顶层反向导入 scoped type；TagService 兼容 re-export desktop adapter，adapter 默认构造又延迟 import TagService。
- **影响**：层 DAG 通过不代表运行期无 SCC；模块隔离、类型重构和生命周期单测难度上升。
- **建议**：抽离无行为 `runtime_types`；Bootstrap 保持唯一 runtime factory；adapter re-export 迁移到明确 compatibility module。
- **最小门禁**：AST import SCC gate，动态/局部 import 单独报告；SCC 需登记退役期限。

### CQ-05 全局 provider seam 是隐式第二组合根

- **级别/置信度**：P2 / 高。
- **位置**：`application/library_service.py:25,30`；`core/tag_store.py:32`；`application/bootstrap.py:299`。
- **证据链**：import/Bootstrap 过程安装 repository/settings/event-bus provider 到 module-global mutable variable；没有 owner token、单次安装限制或生产覆写拒绝。
- **影响**：多个 Bootstrap、嵌入宿主、并发测试可替换装配行为，和 session 不是 service locator 的目标冲突。
- **建议**：provider 需要 owner token、显式 test reset、生产一次安装；TagStore 通过构造注入 repository/protocol。

### CQ-06 插件分类/扩展名贡献没有来源所有权和恢复模型

- **级别/置信度**：P1 / 高。
- **位置**：`core/plugins/manager.py:431,440`；`application/asset_filters.py:13`；`core/format_utils.py:19`。
- **证据链**：A/B 可覆盖同一 category/ext；unload A 对 key/ext 无条件 pop，无法恢复 B 或内置 mapping。
- **影响**：插件卸载会破坏仍活跃插件或内置分类，导致 Desktop/LAN 分类和扩展展示错误。
- **建议**：基线加 `(plugin_id,key/ext)` 贡献栈/多值所有权，load/unload 确定性重建；默认拒绝覆盖内置 key。
- **最小门禁**：双插件重叠 key/ext 和覆盖 `.png` 的各卸载顺序回归。

### CQ-07 插件主题 token 同时存在“非即时可用”和卸载误删问题

- **级别/置信度**：P1 / 高。
- **位置**：`core/plugins/manager.py:455,471`；`core/themes.py:125,167`。
- **证据链**：register 只写 fallback，已加载 theme 不重新 merge；unload 无条件删 token。
- **影响**：插件 API 声称 token 可用却未即时反映；相同 token/内置 token 会被错误删除。
- **建议**：带来源 overlay、冲突规则、注册/卸载后 merge/cache invalidate/theme_changed；不得直接 pop。

### CQ-08 插件 lifecycle 无单一状态锁，部分 callback 丢 ContextVar 身份

- **级别/置信度**：P1 / 高（lifecycle）；P2 / 高（legacy parser identity）。
- **位置**：`core/plugins/manager.py:74,158,248,368,382`；`core/plugins/host_context.py:1104,1311,1416`。
- **证据链**：load/unload/discover 短暂锁 record 后在锁外 register/unregister，存在双 load 或 load/unload/discover 交错；legacy parser 直接调用 callback，未使用 host identity scope。
- **影响**：重复 handler/hook、host/theme/category 残留、最终 record 与实际贡献分裂；legacy plugin callback 无法正确读取 preferences/permission subject。
- **建议**：per-plugin single-flight lifecycle state machine + record epoch；所有 callback 统一经 `invoke_as_plugin(plugin_id,...)`。

### CQ-09 AppSettings 跨进程 last-writer-wins，持久化失败仍广播内存状态

- **级别/置信度**：P2 / 高（跨进程）；P3 / 中高（持久化失败 UI）。
- **位置**：`core/settings.py:67,113,195`；`core/library_manager.py:15`；`i18n/__init__.py:53`；`core/themes.py:237`；`dialogs/settings_dialog.py:960`。
- **证据链**：多个进程 load 自己 snapshot 后各自 temp+replace settings.json，无法 merge；语言/theme/scale 先改内存再忽略 save false 仍 emit signal。
- **影响**：独立实例静默覆盖语言/主题/插件禁用/安全确认；当前 UI 看似成功但重启恢复旧值。
- **建议**：单 writer lock 或 key revision/CAS merge；偏好使用统一 persistence result，成功后 emit 或可见 pending-sync 状态。

## 5. 应用、仓储、领域与 API 职责质量

### CQ-10 单项与批量 file move 的事务前置条件不一致

- **级别/置信度**：P1 / 高。
- **位置**：`application/file_operation_service.py:494`（move 有 clean boundary）与 `:599`（move_to_directory 无同等检查）。
- **影响**：批量拖放可在 caller transaction 中先移动不可回滚文件系统资源，再留下可 rollback/partial DB projection，与单项 move 行为不同。
- **建议**：统一 command precondition，或定义显式 file-system-before-projection UoW；copy/duplicate/restore 同步纳入。
- **测试**：outer BEGIN 后批量 move 必须 fail，FS 与 caller row 保持原状。

### CQ-11 Metadata remove_url 在 commit 前发事件

- **级别/置信度**：P1 / 高。
- **位置**：`application/metadata_service.py:227,241,253`；`repositories/metadata_repository.py:384-403`。
- **影响**：set_notes/add_url 都拒绝 outer transaction，remove_url 却即时 publish；rollback 后客户端仍认为 URL 删除。
- **建议**：同一 transaction guard 或 commit-aware outbox；禁止各 service 自行决定 event timing。

### CQ-12 仓储事务所有权碎片化，旧路径强制 commit

- **级别/置信度**：P1 / 高。
- **位置**：`repositories/auth_repository.py:261`；`favorite_repository.py:37,58`；`gallery_home_repository.py:35`；对照 `metadata_repository.py:212`、`tag_repository.py:190`、`shop_repository.py:58`。
- **影响**：应用层无法可靠组合跨服务 UoW，caller 未提交修改可被 auth/favorite/gallery 操作提前 commit。
- **建议**：统一 session-aware `write_scope`：独立 commit、outer transaction、savepoint 三种明示模式；迁移旧 repository。
- **测试**：BEGIN + caller marker + every write repository + rollback，断言没有提前提交。

### CQ-13 ProjectService 读模型隐式写 raw metadata cache

- **级别/置信度**：P2 / 高。
- **位置**：`application/project_service.py:329,790`。
- **证据链**：GET project listing -> cache warm -> raw `MetadataRepository(db_conn)` batch write。
- **影响**：读 API 具有未声明持久化副作用，绕过 MetadataService 的 session/transaction/event contract，测试难以判断查询可否改变状态。
- **建议**：显式 `ProjectProjectionCache` port 或 session-bound metadata batch API；定义 cache-write failure/result contract。

### CQ-14 Favorite/Gallery raw repository 生命周期模型未收敛

- **级别/置信度**：P2 / 高。
- **位置**：`favorite_repository.py:11`；`gallery_home_repository.py:14`；`application/gallery/_persistence.py:32`。
- **影响**：同 LAN bundle 内不同 adapter 使用不同 root/lease/connection 契约，阻碍统一 UoW 和 close semantics。
- **建议**：迁到统一 session-bound repository base，legacy raw API 显式隔离。

### CQ-15 Domain error、DTO/projection 和 HTTP mapper 尚未统一

- **级别/置信度**：P2 / 中高（错误）；P3 / 中高（service result）。
- **位置**：`lan/routes/tags.py:16`、`metadata.py:58`、`favorites.py:60`、`routes/_errors.py:47`；`application/auth_service.py:195`、`favorite_service.py:114`。
- **影响**：部分 expected domain error 落入手写 500；auth/favorite/metadata/tag 返回裸 dict/tuple/side effect，adapter 需了解内部 record shape。
- **建议**：canonical exception mapper，binary route 明确 allowlist；逐步引入 `AuthenticationResult`/`MutationResult`，repository record 不跨 repository boundary。

### CQ-16 LAN/WebUI contract 仍有重复 DTO 与局部身份绕过

- **级别/置信度**：P1 / 高（私有 page identity）；P1 / 高（ActivityLog time DTO）；P2 / 高（重复 DTO/error/response）。
- **位置**：
  - `webui/src/pages/StorefrontCheckoutPage.tsx:39`、`StorefrontCheckoutGroupPage.tsx:56`、`StorefrontBuyerOrdersPage.tsx:51`、`StorefrontDeliveryPage.tsx:27`。
  - `lan/routes/_helpers.py:88,119`、`lan/routes/users.py:115`、`webui/src/types/api.ts:371`、`components/admin/ActivityLog.tsx:37`。
  - `webui/src/types/contracts.ts:56`、`types/api.ts:28,215`。
- **影响**：局部 private data request 没有统一 identityGeneration/AbortSignal，旧订单/receipt response 可在身份切换后提交；Activity timestamp epoch seconds 与 string DTO 不一致；generated/shared DTO 与手写 API type 已发生 TreeItem nullability 漂移。
- **建议**：buyer domain hook/useCachedQuery 统一 identity-scoped read；所有 read API 接受 signal；ActivityLogResponse 纳入 LAN DTO，timestamp 明确 epoch seconds；`api.ts` 重导出 generated contract，保留 WebUI-only composite。

### CQ-17 JSON/error/route data access 的单一事实来源不完整

- **级别/置信度**：P2 / 高（error/response）；P3 / 高（component data gate）。
- **位置**：`lan/security.py:209,222,233`；`lan/routes/favorites.py:26,105`；`lan/routes/shop/_common.py:29,57`；`webui/src/components/layout/Sidebar.tsx:122`、`StatusBar.tsx:21`、`components/admin/ActivityLog.tsx:4`；`scripts/check_frontend_data_fetch.py:24`。
- **影响**：rate limit/HTTPException/media 与 canonical error 形状不同；shop reflection+direct service dict 使 HTTP payload 不可静态追踪；page-only data-fetch rule 无法治理 component 请求。
- **建议**：JSON API 的 global HTTPException/rate-limit mapper；binary exceptions allowlist；typed response builders；组件数据访问统一 domain hook/API context，静态 gate 覆盖整个 src。

## 6. 当前工作树预提交审查

工作树受跟踪修改为 12 个文件，集中在 file-list cover scan、drop background、ImageViewer async decode、i18n/README/desktop tests。报告不修改这些文件。

### 提交前阻断项

#### WT-01 cover scan 回调未保证 GUI 线程

- **级别/置信度**：P1 / 高。
- **位置**：`AssetsManager/panels/file_list/_base_logic.py:533-570`。
- **链**：worker `_CoverScanTask.run` -> `signals.done.connect(_deliver)` 普通 Python closure -> `_on_cover_scan_result` -> model/grid/layout/loader access。
- **影响**：无 QObject receiver/QueuedConnection 保证时，回调可能在 worker thread 访问 Qt model/widget，造成 warning、竞态或崩溃。
- **提交条件**：使用 parent QObject bridge/bound slot 或显式 queued connection；测试断言 callback/QObject 操作在 panel GUI thread。

#### WT-02 drop worker session/非预期异常被转化为“零变更成功”

- **级别/置信度**：P1 / 中高。
- **位置**：`_base_logic.py:669-728`；`panels/file_list/_background.py:43-50`。
- **链**：`session.operation()` 在 try 外或 service 抛未捕获 RuntimeError/TypeError -> background runner 记录异常仍 emit done -> empty holder -> done handler 显示 0 change/no error 并 refresh。
- **提交条件**：operation context 纳入 try；done payload 显式携带 exception/result；测试 session worker 启动前 close 和 service RuntimeError，不得报告成功。

#### WT-03 bounded drain timeout 后丢弃私有 QThreadPool 可能再次无限等待

- **级别/置信度**：P1 / 中高。
- **位置**：`panels/file_list/_base.py:133-139`；`panels/image_viewer.py:879-896`。
- **链**：cancel -> `waitForDone(timeout)` -> timeout -> pool ref drop/widget destruction -> QThreadPool destructor 可能再次等未完成 QRunnable。
- **提交条件**：对永不完成 worker 执行真实 panel shutdown/viewer close；证明 UI 不因析构等待。超时后保留隔离 pool/owner 并记录，或确保任务可强制终止。

### P2 行为回归与质量观察

- `image_viewer.py:336-345`：坏 strip thumb `qimg.isNull()` 不清 `_strip_pending`，该 index 永久 placeholder。
- `image_viewer.py:602-610`：T 快速 off/on 清 pending 但不取消旧 task，同 generation/index 可重复排队/交付。
- `_base_logic.py:408-412`：显式 refresh 仅 invalidate in-flight，不清 folder cover cache，封面变化后仍可显示旧 cache。
- `image_viewer.py:260-283`：EXIF 仍同步；`image_viewer.py:40` 为 reuse stderr helper 导入 `_loader`，触发进程级 ffmpeg pool 模块耦合。应把 helper 移到无 loader 副作用模块。

### 已确认工作树正向检查

- cover pool 有单 worker、64 pending 上限、generation cancel、可视行 delivery。
- drop 后台化具 session identity completion guard；viewer 有 private pool、generation/path stale drop、QImage worker/QPixmap UI thread 区分。
- i18n 三语言 JSON 均 837 key、集合一致、有效 UTF-8 无 BOM；README 结构 markers 对应当前源码统计，文档统计脚本通过。
- `git diff --check` 无空白错误。index 基线为 LF；多数 working copy 改动为 CRLF，`_host.py` 为 LF，提交前需统一仓库 EOL 约定以防整文件噪声。

## 7. 文档治理问题

### DOC-01 full-review 被标为当前权威但整体是旧快照

- **级别/置信度**：P1 / 高。
- **位置**：`docs/development.md:73`；`docs/full-review/00-INDEX.md:4,48`；`01-construction.md:31`；`02-module-map.md:30`。
- **证据**：full-review 仍写 schema v23、139 routes、2952 tests 等，而 L0 当前为 v29、140 routes、48 application modules。
- **建议**：改名/标记为 `2026-08-11 snapshot @ commit`，撤销“当前工作区权威”；建立小型当前事实索引链接 L0/L1。

### DOC-02 migrations/architecture 仍记录 schema v23，遗漏 v24-v29

- **级别/置信度**：P1 / 高。
- **位置**：`docs/migrations.md:3`、`docs/architecture.md:117`；对照 `core/db_migrations.py:46,981`。
- **建议**：从结构化 migration manifest/source 生成或校验清单；更新 1-29 并在 schema change CI 强制同步。

### DOC-03 route、test 运行结果和索引存在双事实来源

- **级别/置信度**：P2 / 高。
- **位置**：`README.md:8,249,288,366,478,629`；`check_doc_stats.py:12,63`；`docs/full-review/00-INDEX.md:31`。
- **证据**：README 140 分组和为 139；3778/3737 passed 并存；doc stats 只验证结构/marker，运行结果可手工 stamp；索引漏 11/12/13 及三份 2026-08-20 审计。
- **建议**：route 分组求和 gate；README 改链接 CI artifact，artifact 含 commit/run/platform/command/skip；索引覆盖所有 tracked review 文件并给审计快照加日期/commit/验证状态。

### DOC-04 ADR/compose 实施状态边界不清

- **级别/置信度**：P3 / 中高。
- **位置**：`docs/adr/0001-architecture-governance.md:60`、`0002-library-session.md:45`、`0003-library-runtime.md:5`。
- **建议**：ADR 只保存决策与 accepted/superseded；实施进度移到 dated report 并链接 verified commit。

## 8. 依赖、构建、发布、插件与许可证治理

### GOV-01 release 未绑定完整 CI，允许覆盖资产且无可验证 provenance

- **级别/置信度**：P1 / 高。
- **位置**：`.github/workflows/release.yml:11-53`。
- **证据**：release 只 build/package smoke/upload，缺 `needs` full CI、完整 tests/E2E/frozen runtime stay-alive；使用 `gh release upload --clobber`；无 SHA-256、signature、SBOM、provenance。
- **建议**：protected tag + successful required CI binding；拆 upload job；拒绝已有 asset；发布 archive hash/signature/provenance/commit/toolchain/lock metadata。

### GOV-02 Python dependencies 宽范围且无 lock/constraints/hash

- **级别/置信度**：P1 / 高。
- **位置**：`requirements.txt:3-7`、`requirements-dev.txt:2-7`、`requirements-lan.txt:3-4`；CI `ci.yml:243-247`；release `release.yml:26-33`。
- **影响**：相同 commit 的 test/package 依赖解析会漂移，PyInstaller/Qt 行为和制品不可稳定复现。
- **建议**：runtime/LAN/dev/package/perf 分层 lock/constraints；release 使用 hash install；输出完整 dependency graph。此项不等同于已发现 CVE。

### GOV-03 Actions 可变 tag 和权限过宽/不统一

- **级别/置信度**：P1 / 高。
- **位置**：`ci.yml:17-18,53,76-77,95-96,114-115,182-183,205-206,238-239,264-265`；`nightly-perf.yml:17-27`；`release.yml:7-8,15-16`。
- **建议**：全部 `uses` pin 40 位 SHA；所有 workflow 默认 contents:read；构建与 upload job 分离，upload 最小 write 权限/环境保护。

### GOV-04 SBOM、LICENSE/NOTICE 与第三方许可证治理缺失

- **级别/置信度**：P2 / 高（SBOM/NOTICE）；P3 / 高（项目 license policy）。
- **位置**：根目录未跟踪 LICENSE/NOTICE/SBOM；`README.md:653-655`；`webui/package-lock.json:37-45`。
- **建议**：明确内部/发布许可证策略；生成 Python/npm/bundle SPDX/CycloneDX、NOTICE 和 license report，作为 release asset。

### GOV-05 PyInstaller/生成物完整性和 release 构建路径未统一

- **级别/置信度**：P2 / 高。
- **位置**：`AssetManager.spec:14-227`；`build.py:15-65`；`scripts/check_package_contents.py:95-127`。
- **证据**：hiddenimports/excludes/UPX/datas 手工维护；build.py optimize 删除 DLL，但 release 不走同一 build path；checker 只验证关键存在，不验证完整 manifest/version/digest/runtime closure。
- **建议**：统一 build entry；生成 sorted file manifest/SHA、bundle SBOM、toolchain metadata；optimize 后 runtime/import/exit smoke；固定或记录 UPX。

### GOV-06 插件是同进程全信任动态 Python 代码

- **级别/置信度**：P2 / 高。
- **位置**：`core/plugins/loader.py:79-103`、`manager.py:78-87`、`bootstrap.py:357-377`、`Plugins/Docs/PLUGIN_SYSTEM.md:341-368`、`descriptor.py:46-56`。
- **结论**：manifest permissions 是 host API 意图门，不是 sandbox；外部 plugin 代码等同本地代码。entry path containment 已存在，不应误报为完全无保护。
- **建议**：明确 trusted model、默认外部 plugin disabled、显示 source/version/digest；manifest schema/host_version/digest；若需隔离改 subprocess+IPC，不应把 ContextVar permission 当隔离。

### GOV-07 支持平台与工具链/性能门禁声明不充分

- **级别/置信度**：P2 / 中高（platform）；P3 / 高（toolchain/nightly）。
- **位置**：`README.md:312-333`；`ci.yml:80-86,230-255`；`nightly-perf.yml:11-31`；`pytest.ini:7`。
- **证据**：Windows 是唯一 frozen release；Linux/macOS cross-platform branches 没有对等 release matrix。nightly perf continue-on-error，默认 pytest 排除 perf/e2e，只有 grid artifact 无 p95 gate。
- **建议**：README 明确 Windows/Linux/macOS status；宣称支持的平台必须有 source/frozen matrix；记录 exact toolchain；PR deterministic perf smoke + nightly/release p95 policy。

## 9. 已确认防护与不应误报项

- 静态 layer DAG、route policy/capability、LAN/Desktop boundary、部分 raw DB 访问、TS/CSS generator drift 皆已有 CI gate。
- Metadata/Tag/Shop/Share/Index/Reconciliation 较新的 repository 路径已有 session/savepoint/outer transaction 契约；问题是旧 auth/favorite/gallery 等迁移未收敛。
- npm 有 lockfile v3、`npm ci` 和 moderate audit；这不覆盖 Python lock、SBOM 或 release。
- PyInstaller 有 data/hiddenimport/check-package/Windows smoke；缺口是可重复 manifest/provenance、release 复用和运行时矩阵。
- plugin entry 有 root containment、失败隔离和 unload cleanup；这不构成 sandbox。
- `check_doc_stats` 能验证 README 结构 markers，且当前对应源码；它不能验证历史 pytest/E2E/CI 数字或 full-review snapshot 时效。

## 10. 工作树状态与提交建议

本轮结束时工作树包含原有 12 个受跟踪改动和 4 个未跟踪审计文档：

- 受跟踪：三个 i18n JSON、file-list `_base.py/_base_logic.py/_host.py/_navigation.py`、`image_viewer.py`、README、两份 Desktop test、unit panel test。
- 未跟踪：`full-scan-2026-08-20.md`、`cross-module-flow-api-audit-2026-08-20.md`、`performance-timing-audit-2026-08-20.md`、本报告。

**提交前必须完成**：WT-01、WT-02、WT-03 的实现或真实 Qt/worker 验证；随后运行与 FileList/ImageViewer/lifecycle 相关的定向测试、完整 Python suite、静态 gates 和 Windows package smoke。不得将当前审计文档中的“未复跑”结论写成测试已通过。

**建议拆分提交**：

1. Desktop async implementation + P1/P2 Qt lifecycle fixes + focused tests。
2. i18n/README structural marker 更新（仅在对应门禁实际通过后）。
3. 四份 dated audit snapshot + full-review index/authority metadata 调整。

## 11. 测试与门禁映射

| 问题域 | 最小回归测试 | 静态/CI 门禁 |
|---|---|---|
| Favorite/Gallery session binding | cross-root/raw/closed-session integration | session-bound repository constructor rule |
| DI session service bypass | container resolve architecture test | AST denylist for session service registration/resolve |
| plugin contribution/lifecycle | dual plugin overlap + concurrent barriers | callback invocation via identity helper rule |
| transaction ownership | BEGIN/rollback matrix for all write repositories | shared write_scope contract tests |
| API error/DTO | route HTTP error matrix + ActivityLog timestamp fixture | generated/shared DTO duplicate denylist |
| component data access | identity switch deferred order tests | frontend fetch gate covers entire src |
| worktree Qt async | GUI-thread callback, worker exception, stuck pool close | targeted desktop + Windows lifecycle job |
| docs | schema/route sums/index coverage | doc metadata + CI artifact links |
| dependency/release | clean lock install/build/package smoke | Action SHA/permission/release artifact gate |

## 12. 分阶段修复路线

### Phase 1：阻断工作树与隔离边界

1. 修 WT-01/02/03 和对应真实 Qt tests。
2. 收紧 Favorite/Gallery session binding。
3. 统一 file operation clean transaction precondition，修 remove_url event timing。
4. 把普通 logout/session API、private buyer page identity 统一归入 scope/generation contract。

### Phase 2：收敛事务、DTO、全局贡献

1. 迁移强制 commit repository 到 shared write_scope。
2. Project cache warming 显式化；Favorite/Gallery/Activity persistence session-bound 化。
3. canonical error/response builder、Activity DTO、generated type re-export。
4. plugin contribution owner overlay、lifecycle state machine、all-callback identity helper。

### Phase 3：架构与文档治理

1. container session factory 化，移除第二组合根；拆 runtime type cycle；增强 SCC/dynamic import/provider gate。
2. 将 full-review 降为 snapshot，修 migration/schema/route/test 双事实，索引所有审计。
3. README 改为指向 CI artifact，不维护手工 passed/skipped。

### Phase 4：可复现发布与动态验证

1. Python lock/hash、Action SHA/minimal permission、release needs CI、artifact hash/signature/provenance。
2. SBOM/license/NOTICE、bundle manifest、统一 PyInstaller build path。
3. 在隔离环境执行 pip/OSV/npm audit、clean checkout build、plugin loading、Windows/Linux/macOS matrix；记录实际证据后再定具体依赖/平台风险。

## 13. 动态验证边界

尚未执行的验证包括：真实 Qt queued connection 的线程归属、QThreadPool 析构等待、session close/race、双进程 settings 冲突、SQLite outer transaction、浏览器 identity switch、clean dependency resolve、package/release、跨平台 bundle、漏洞和许可证扫描。修复必须先将这些静态调用链转为确定性测试，再做目标平台黑盒或压力验证。