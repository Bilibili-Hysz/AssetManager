---
feature: repository-followup-review-2026-08-01
status: delivered
as_of: 2026-08-01
last_review: 2026-08-02
branch: master
base_commit: f7f9e14de6c644c60575ed28f16567b8b717133a
remote: none configured
---

# Repository Follow-up Review — 2026-08-01（2026-08-02 增量复核）

## 1. 结论

本报告是 [`repository-baseline-2026-08-01.md`](repository-baseline-2026-08-01.md) 之后的增量收口记录。目标是把本轮并行试验产生的代码、测试、文档状态和验证边界放到同一条线上；它不改写基线报告中的历史快照。

当前可以明确为：

- 阶段 1 数据安全：G6-4（Undo 残留启动清理）已完成 Windows 安全判定、清理上限和 sidecar 兼容补强，阶段整体仍未闭环。
- 阶段 2 性能：目录大小任务队列治理的一个子项已完成，reset 最小化、真实图片 IO 和发布机阈值仍待验收。
- 阶段 3 Desktop–LAN–WebUI：A1 应用层 `/api/` URL 剥离已完成并通过契约/路由测试；B2 ThumbnailLoader 直连 SQLite 经高风险审查确认仍需先完成服务设计。
- 本阶段创建的测试临时目录已按精确路径清理，未删除未知用户文件。

## 2. 本轮代码变更

### 2.1 Undo 临时目录残留清理

涉及：`AssetsManager/application/undo_service.py`、`tests/integration/test_undo_service.py`。

- 进程首次创建 `UndoService` 时执行一次启动扫描。
- 只扫描 `tempfile.gettempdir()` 的直接子目录，精确匹配 `AssetsManager_undo_` 前缀。
- 默认只处理超过 7 天的目录；当前进程登记目录、PID 标记指向的活跃进程目录和最近目录保留。
- 单次最多清理 256 项，删除失败或目录状态不确定时安全跳过。
- 新实例的 PID 标记放在 Undo 目录旁的 sidecar，保持 Undo 目录内部只包含真实备份；同时兼容早期放在目录内的标记。
- `cleanup()` 会移除 Undo 目录和 sidecar 标记。
- Windows PID 判定区分 `ERROR_INVALID_PARAMETER`（进程不存在）与 `ERROR_ACCESS_DENIED`/未知错误（保守保留）。
- 回归测试覆盖单次 256 项上限、sidecar/旧标记兼容、sidecar 清理和 Windows 权限不确定性。

这是对崩溃残留的受限缓解，不是完整数据安全闭环。单实例锁、数据库自检、导出/恢复和防误删仍未实现。

### 2.2 FileList 目录大小队列治理

涉及：`AssetsManager/panels/file_list/_model.py`、`tests/desktop/test_file_list_model.py`。

- 保持单并发 worker。
- 排队上限为 64；当前可见目录优先。
- 超限时淘汰不可见 prefetch 任务，保留 `"..."` 占位符；目录再次可见时会重新排队。
- 未改变浏览、排序、过滤、刷新、关闭和目录大小缓存语义。
- 批量缓存预热、“仅可见行排队”、reset 最小化仍是后续任务。

### 2.3 A1 应用层 URL 边界

- 已修改：`AssetsManager/application/project_service.py`、`search_service.py`、`AssetsManager/lan/routes/metadata.py`，并新增 `AssetsManager/lan/routes/_resource_urls.py`。

- 应用服务现在只返回相对业务引用（`thumbnail_path`/图片 `path`），LAN route 层统一生成 `/api/thumbnails`、`/api/download` URL。
- 通过契约测试保持 LAN 最终 JSON 字段、可选字段、URL 编码和图片结构不变；`rg "/api/" AssetsManager/application` 不再命中 URL 生成。

### 2.4 B2 ThumbnailLoader 服务化审查结论

本阶段没有合并 B2 代码。高风险审查确认：

- `_loader.py` 仍直接持有 `sqlite3.Connection` 和 `ThumbnailRepository`，包括 mtime 查询、touch、upsert、orphan cleanup 和 clear cache。
- `_base.py` 仍通过 `session.connection_for(...)` 向 Loader 传递原始连接。
- 不能只注入一个当前 `ThumbnailService` 字段；服务引用必须进入 `_Runtime` 快照，避免切库后旧任务写入新库。
- `ThumbnailService` 需要先补齐缓存元数据读写 API 和 session operation 租约，再迁移 Loader。

B2 已转为下一阶段设计任务，保持现有优先级、取消、generation、磁盘缓存 fallback 和关闭语义不变。

### 2.5 G6-3 按库单实例锁

涉及：`AssetsManager/core/library_lock.py`、`AssetsManager/core/path_resolver.py`、`AssetsManager/application/library_service.py`、对应路径与生命周期测试。

- 使用 Qt `QLockFile`，按规范化库根路径生成稳定散列锁名，锁文件位于 `RuntimeData/Shared/library-<hash>.lock`。
- 不使用全局 `instance.lock`：不同库可以并行打开；同一进程内多个 `LibraryService` 对象共享底层锁，保持既有 foreign/stale session 测试与服务隔离语义；不同进程打开同一库会被拒绝。
- 锁由 canonical library session 生命周期持有。初始化失败会关闭已打开的数据库并释放锁；session/runtime/数据库全部成功关闭后释放锁；关闭监听器或数据库关闭失败时保留锁，等待重试。
- stale session 关闭不会释放 replacement session 的锁；锁实现不读取 PID 或手工删除锁文件。

### 2.6 B2-A ThumbnailService 缓存元数据 API 与 session 租约

涉及：`AssetsManager/application/thumbnail_service.py`、`AssetsManager/application/bootstrap.py`、对应集成/单元测试。

- 新增缓存元数据服务 API：mtime 查询、访问时间更新、upsert、列表、单项删除和清空；调用方不再需要取得 SQLite 连接。
- Bootstrap 将 canonical `LibrarySession` 和 `session.connection_for` 注入 ThumbnailService；元数据操作与 `resolve()` 由 `session_operation` 覆盖完整 operation lease。
- session 关闭后拒绝新操作；`resolve()` 的数据库 provider 失败仍保持原有降级到原图且不遗留 operation lease 的行为。
- Loader 尚未迁移；下一阶段仍需把 ThumbnailService 引用纳入 Runtime 快照，并保持 generation、取消、优先级、磁盘 fallback 和 orphan cleanup 语义。

### 2.7 B2 后续工作树进展（2026-08-02）

本节记录本报告历史检查点之后的当前工作树状态，不改写 2.4/2.6 节所记录的 2026-08-01 事实，也不把未提交改动冒充新的基线提交。

- `ThumbnailLoader` 已迁移为只持有 `ThumbnailService` 与 immutable `_Runtime` 快照；`_base.py` 不再向 Loader 传递 SQLite 连接，缓存元数据、orphan cleanup 和显式清理均通过 `ThumbnailService` API 完成。
- 已保留并补强 generation、取消、优先级、deferred queue、stale result、旧 runtime drain、缓存清理与磁盘 fallback 语义；清理操作使用 cache epoch 防止旧 bake 回写。
- 增量目标测试：`tests/desktop/test_thumbnail_loader.py` 为 `38 passed`；`tests/desktop/test_file_list_shim.py` 为 `103 passed`，其中 1 个 LAN TagTree 用例在整文件批量运行时出现事件顺序抖动，单独重跑通过，未归因于 Loader 改动。
- 静态边界检查：`rg -n "ThumbnailRepository|sqlite3|set_cache_db|_db_conn|_repo" AssetsManager/panels` 无命中；compileall 通过。真实图片 IO、性能基准、全量回归与提交后的基线验证仍未闭合。

### 2.8 B3 TagTree Runtime 投影试点（2026-08-02）

在 B2 Loader 服务边界收口后，当前工作树完成了 TagTree 的最小 Runtime 投影切片：

- `TagTreePanel.set_runtime(runtime)` 绑定 immutable service snapshot 与 `LibraryRuntime.event_router`；仅处理 `ProjectionDomain.TAGS` invalidation。
- `RuntimeEventSubscription` 通过 Qt queued signal 投递，不在 EventBus/Router 发布线程直接访问 Qt widgets。
- 旧的 TagTree `TagCatalogChanged` 自动订阅已移除，避免 Runtime Router 与全局 domain bridge 双路径造成重复刷新；兼容性 handler 保留用于 session-scoped 直接调用与过渡测试。
- 切库/关闭时主动关闭旧 router subscription，并通过 binding generation、runtime identity、session token 和 epoch 拒绝延迟旧事件。
- B3 聚焦测试 `15 passed`；Runtime Router/事件发布筛选回归 `30 passed`；架构边界 `74 passed`；LAN 标签变更到桌面 TagTree 的真实用例单独重跑通过。

B3 仍未宣称完整交付：WebSocket/React authoritative refetch、桌面/Web 最终状态一致性、发布环境复测和提交后基线证据仍待完成。

## 3. 验证证据

| 检查 | 结果 | 解释 |
|---|---|---|
| A1 应用服务/URL 契约测试 | `42 passed, 1 skipped` | 项目、搜索和新建 URL projection contract 测试 |
| A1 相关 LAN route 测试 | `9 passed, 183 deselected` | 搜索、home、projects、project detail 相关用例 |
| G6-4 Undo 测试 | `32 passed` | 含 Windows 权限、256 上限和 sidecar/旧标记测试 |
| G6-3/B2 生命周期与服务交叉回归 | `163 passed` | 覆盖按库锁、跨进程竞争探针、初始化/关闭异常、Bootstrap、Runtime、窗口切换与 ThumbnailService |
| B2 ThumbnailService/Repository 目标测试 | `64 passed` | 缓存元数据 round-trip、session 拒绝、provider 失败降级与租约释放 |
| Core/unit/integration/LAN 非浏览器 sweep | `1264 passed, 1 skipped, 1 environment failure` | 唯一失败来自外部 visualization 基目录 ACL；将同一用例切换到工作区隔离基目录后 `1 passed` |
| A1 架构边界 | `74 passed` | 完整 `tests/unit/test_architecture_boundaries.py` |
| 静态质量 | Ruff passed；compileall passed；`git diff --check` passed | 覆盖本阶段修改文件及 `AssetsManager` |
| 外部基目录全量尝试 | `1589 passed, 1 skipped, 1 failed, 5 errors` | 1 个失败是外部 visualization 目录 ACL 造成的回收站删除失败；5 个错误均为 Chromium `spawn EPERM` |

因此，本轮不宣称“受当前 Windows 沙箱约束下的浏览器 E2E 全量通过”。目标代码测试、非 E2E 回归和静态检查均已通过；基线报告中的 Python `1590 passed, 1 skipped` 仍作为历史快照保留。

## 4. 系统临时目录风险披露

并行试验早期曾运行过一个未带 256 项上限的临时实现；代理当时报告本机系统 Temp 中约有 `50,692` 个历史 `AssetsManager_undo_*` 项，并提示可能已清理其中符合条件的残留。后续只读盘点仍观察到约 `50,231` 个同类目录；由于目录状态、删除时点和 PID 复用无法从当前快照反推出完整删除清单，本报告不把它们标为已安全清理，也不再扩大批量删除范围。

本轮明确创建的隔离目录均已删除；没有对系统 Temp 中剩余历史目录做额外处理。未来若要处理这批目录，应先做可恢复清单、按 PID/时间/标记分层审计，并在独立任务中获得明确验收证据。

## 5. 下一步入口

1. 先把本报告和路线图状态作为新的工作树事实入口。
2. 数据安全线：G6-3 已完成；继续立项数据库 quick check/孤儿修剪、导出/恢复、防误删策略，不要把单实例锁与 G6-4 的部分缓解误判为阶段 1 完成。
3. 性能线：继续 reset 最小化和真实图片 IO/发布机验收；目录大小队列治理可视为已完成子项。
4. 服务边界线：A1 与 B2-A 已完成；下一步进入 ThumbnailLoader 的 Runtime 快照迁移，完成后再做完整服务化行为回归。
