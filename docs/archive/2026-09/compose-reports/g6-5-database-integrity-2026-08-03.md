---
feature: g6-5-database-integrity-2026-08-03
status: partial-delivered
scope: session-bound quick_check and conservative orphan maintenance
verification: m1-targeted-167-passed; non-e2e-2034-passed-2-skipped-1-warning
---

# G6-5 数据库完整性自检第一切片 — 2026-08-03

## 结论

G6-5 本轮阻塞项已修复：每个 Runtime 的 Desktop/shared service snapshot 现在包含一个绑定 canonical `LibrarySession` 的 `DatabaseIntegrityService`。库切换时通过后台单飞任务执行维护，不阻塞 UI；`quick_check` 使用独立的 SQLite 连接，数据库读写仅持有短 operation lease，慢速文件系统扫描不占用 session lease。

Runtime 生命周期已注册完整性服务适配器。session/Runtime 关闭时会取消后台检查、尝试中断活动的 `quick_check` 连接，并在有限等待后退出；后台任务不会在关闭的 session 上重新取得数据库访问权。孤儿记录和缩略图缓存的破坏性删除均在写锁内重新验证，避免文件恢复、记录更新或缓存行替换导致误删。

本切片不宣称数据安全阶段完成。导出/恢复、可恢复防误删、半完成文件操作恢复、设置页“上次检查”展示和真实崩溃恢复演练仍是后续任务。

## 已实现行为

- 执行 SQLite `PRAGMA quick_check`。
- `quick_check` 非 `ok` 时只记录问题，不执行任何孤儿清理。
- `quick_check` 使用独立连接；关闭流程可通过活动连接的 interrupt 取消检查。
- 清理 `file_meta` 中指向不存在文件或目录的记录。
- 清理 `thumbnail_cache` 中指向不存在源文件的记录，并尽力删除对应 `.webp` 缓存文件。
- 不删除用户库文件；缩略图缓存 key 生成的目标路径必须保持在当前库 thumbnail 目录内。
- 文件系统扫描在 session lease 外执行；执行删除前在 `db_write_lock` 内重新确认源路径状态。
- `file_meta` 删除按当前 `file_path` 重新验证；`thumbnail_cache` 删除同时约束 `cache_key` 和 `source_path`，缓存行被替换时不会删除新行或新缓存文件。
- `../`、反斜杠穿越、绝对路径和 malformed/null 缓存 key 只允许清理数据库元数据，不触碰 thumbnail 根目录外文件。
- `schedule()` 是单飞的：同一个服务已有任务运行时，重复调度直接返回 `False`。
- worker 启动失败会回滚单飞状态；已关闭的 session 直接生成错误报告，不执行 `quick_check` 或孤儿清理。
- 结果保留为 `IntegrityCheckReport`，并写入日志，包含检查时间、耗时、quick_check 结果和清理数量。

## 代码位置

| 位置 | 作用 |
|---|---|
| `AssetsManager/application/database_integrity_service.py` | session-bound 检查和后台调度 |
| `AssetsManager/application/bootstrap.py` | 将检查服务装配到 Runtime snapshot 并注册生命周期适配器 |
| `AssetsManager/window.py` | 切库后后台调度检查 |
| `tests/unit/test_database_integrity_service.py` | quick_check、孤儿清理、并发重新验证、单飞和 close 语义 |

## 验证

| Gate | Result |
|---|---|
| G6-5 首切片历史 targeted regression（2026-08-03） | `207 passed`，1 个既有 Windows `.pytest_cache` 警告 |
| Ruff | passed |
| compileall | passed |
| `git diff --check` | passed |

测试运行使用会话外可写 pytest basetemp；唯一警告是 Windows 环境下既有 `.pytest_cache` `WinError 183`，没有测试失败。本次验证覆盖：`test_database_integrity_service`、`test_bootstrap`、`test_library_runtime`、`test_window_session_switching`、`test_runtime_events`、`test_runtime_realtime`、`test_thumbnail_service`、`test_thumbnail_repository` 和 `test_thumbnail_loader`。

## 2026-08-05 M1 安全与反馈收口补充

本次续接审计修复了完整性维护的关闭提交竞态：

- `file_meta` 与 `thumbnail_cache` prune 的数据库 commit 均经过 `LibrarySession._publish_while_live()`；session close 先取得线性化点时，维护事务 rollback，不会在 close 返回 pending 后迟到提交。
- 缩略图 baked 文件改为 commit 成功后才 best-effort 删除，rollback 不再留下“元数据恢复但缓存文件已删”的中间状态。
- 修复 scheduled worker 尚未进入执行体时 `_run_done` 被并发 direct `run()` 提前置位的 active-run 计数竞态；线程启动失败继续回收预留状态。
- `DatabaseMaintenanceService` checkpoint 临时修改共享连接的 `busy_timeout` 后会恢复原值；service stop 后的新 checkpoint 保持 closed-service 语义。
- Integrity/Maintenance service 现在保留 `last_schedule_error`，worker 启动失败会写入失败报告/结果；`LibrarySettingsAdapter` 暴露执行错误与调度拒绝原因，窗口自动调度失败不再静默丢弃。
- VACUUM 仍明确 unsupported，且测试确认不会取得连接或执行 SQL。

验证证据：M1 targeted `167 passed`；Integrity/Maintenance/Adapter focused `35 passed`，MainWindow 调度反馈测试另有 `5 passed`；新增的 4 个关闭/取消/active-run 竞态测试连续 3 次通过；非 E2E 全量为 `2034 passed, 2 skipped, 1 warning`。这仍只代表当前 Python 非 E2E 证据，不代表 WebUI/E2E、Desktop 视觉或整个 AssetsManager 发布完成。

## 未完成边界

- Qt-free `LibrarySettingsAdapter` 已暴露完整性/维护执行结果、调度拒绝原因与错误；实际设置页控件、异步反馈和启动失败的用户指导仍未完成。
- 还没有检测和恢复半完成的移动/复制/删除操作。
- `clean_orphan_dirs` 的可恢复隔离子项已在 2026-08-04 完成；G6-1 的 metadata JSON 导出、WAL 一致性备份归档、只读恢复校验和受控恢复 API 已另行完成，产品恢复入口和隔离区管理仍未实现，详见 `g6-1-orphan-quarantine-2026-08-04.md`、`g6-1-metadata-export-2026-08-04.md`、`g6-1-backup-validation-2026-08-04.md` 与 `g6-1-restore-2026-08-04.md`。
- 还没有 Desktop/CLI/LAN 恢复入口、用户确认和真实崩溃后启动演练。
- `quick_check` 失败后的用户可见告警和恢复指导仍待产品层设计。

因此当前准确状态是：**G6-5 数据库自检和保守孤儿清理第一切片已交付，数据安全阶段仍未闭环。**

本报告只确认 G6-5 首切片与本轮 M1 阻塞修复及其分层回归；Desktop/LAN/WebUI 的完整发布范围门禁仍需按主线计划单独复核，不能由本轮 M1 targeted 167 项或非 E2E 2034 项测试替代。
