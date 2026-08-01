---
feature: repository-followup-review-2026-08-01
status: delivered
as_of: 2026-08-01
branch: master
base_commit: f7f9e14de6c644c60575ed28f16567b8b717133a
remote: none configured
---

# Repository Follow-up Review — 2026-08-01

## 1. 结论

本报告是 [`repository-baseline-2026-08-01.md`](repository-baseline-2026-08-01.md) 之后的增量收口记录。目标是把本轮并行试验产生的代码、测试、文档状态和验证边界放到同一条线上；它不改写基线报告中的历史快照。

当前可以明确为：

- 阶段 1 数据安全：G6-4（Undo 残留启动清理）已完成一个受限实现，阶段整体仍未闭环。
- 阶段 2 性能：目录大小任务队列治理的一个子项已完成，reset 最小化、真实图片 IO 和发布机阈值仍待验收。
- 阶段 3 Desktop–LAN–WebUI：本轮只做只读核查，应用层 `/api/` URL 生成和 ThumbnailLoader 直连 SQLite 均未改动，仍是独立后续任务。
- 工作树清理完成后，只保留本轮明确的代码/测试/文档改动；本轮创建的测试临时目录已删除，未删除未知用户文件。

## 2. 本轮代码变更

### 2.1 Undo 临时目录残留清理

涉及：`AssetsManager/application/undo_service.py`、`tests/integration/test_undo_service.py`。

- 进程首次创建 `UndoService` 时执行一次启动扫描。
- 只扫描 `tempfile.gettempdir()` 的直接子目录，精确匹配 `AssetsManager_undo_` 前缀。
- 默认只处理超过 7 天的目录；当前进程登记目录、PID 标记指向的活跃进程目录和最近目录保留。
- 单次最多清理 256 项，删除失败或目录状态不确定时安全跳过。
- 新实例的 PID 标记放在 Undo 目录旁的 sidecar，保持 Undo 目录内部只包含真实备份；同时兼容早期放在目录内的标记。
- `cleanup()` 会移除 Undo 目录和 sidecar 标记。

这是对崩溃残留的受限缓解，不是完整数据安全闭环。单实例锁、数据库自检、导出/恢复和防误删仍未实现。

### 2.2 FileList 目录大小队列治理

涉及：`AssetsManager/panels/file_list/_model.py`、`tests/desktop/test_file_list_model.py`。

- 保持单并发 worker。
- 排队上限为 64；当前可见目录优先。
- 超限时淘汰不可见 prefetch 任务，保留 `"..."` 占位符；目录再次可见时会重新排队。
- 未改变浏览、排序、过滤、刷新、关闭和目录大小缓存语义。
- 批量缓存预热、“仅可见行排队”、reset 最小化仍是后续任务。

### 2.3 服务边界只读核查

确认但未修改：

- `AssetsManager/application/project_service.py` 与 `search_service.py` 仍生成 `/api/...` URL，属于阶段 3 A1。
- `AssetsManager/panels/file_list/_loader.py` 仍直接持有 SQLite/`ThumbnailRepository`，属于阶段 3 B2。

建议保持后续顺序：先扩展 `ThumbnailService`，再迁移 ThumbnailLoader，最后增加架构边界门禁；URL 剥离则单独以最终 JSON 契约测试锁定。

## 3. 验证证据

| 检查 | 结果 | 解释 |
|---|---|---|
| Undo + FileList 目标测试 | `63 passed` | 使用隔离 TEMP 与工作区 pytest 基目录，包含本轮新增测试 |
| 非 E2E Python 回归 | `1586 passed, 1 skipped, 3 deselected` | 排除 Playwright E2E；3 个路径格式测试因临时基目录位于仓库内而显式排除 |
| 静态质量 | Ruff passed；compileall passed | 覆盖本轮修改文件及 `AssetsManager` |
| 外部基目录全量尝试 | `1589 passed, 1 skipped, 1 failed, 5 errors` | 1 个失败是外部 visualization 目录 ACL 造成的回收站删除失败；5 个错误均为 Chromium `spawn EPERM` |

因此，本轮不宣称“受当前 Windows 沙箱约束下的浏览器 E2E 全量通过”。目标代码测试、非 E2E 回归和静态检查均已通过；基线报告中的 Python `1590 passed, 1 skipped` 仍作为历史快照保留。

## 4. 系统临时目录风险披露

并行试验早期曾运行过一个未带 256 项上限的临时实现；代理当时报告本机系统 Temp 中约有 `50,692` 个历史 `AssetsManager_undo_*` 项，并提示可能已清理其中符合条件的残留。后续只读盘点仍观察到约 `50,231` 个同类目录；由于目录状态、删除时点和 PID 复用无法从当前快照反推出完整删除清单，本报告不把它们标为已安全清理，也不再扩大批量删除范围。

本轮明确创建的隔离目录均已删除；没有对系统 Temp 中剩余历史目录做额外处理。未来若要处理这批目录，应先做可恢复清单、按 PID/时间/标记分层审计，并在独立任务中获得明确验收证据。

## 5. 下一步入口

1. 先把本报告和路线图状态作为新的工作树事实入口。
2. 数据安全线：单实例锁、数据库 quick check/孤儿修剪、导出/恢复、防误删策略分别立项；不要把 G6-4 的部分缓解误判为阶段 1 完成。
3. 性能线：继续 reset 最小化和真实图片 IO/发布机验收；目录大小队列治理可视为已完成子项。
4. 服务边界线：按 A1（URL 剥离）与 B2（ThumbnailLoader 服务化）拆成互不重叠的后续任务。
