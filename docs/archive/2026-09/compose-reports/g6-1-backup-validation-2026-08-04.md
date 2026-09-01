---
feature: g6-1-backup-validation-2026-08-04
status: partial-delivered
scope: timestamped RuntimeData backup archive and read-only restore validation
verification: 260-targeted-regression-tests-passed
---

# G6-1 备份归档与恢复前校验首切片 — 2026-08-04

## 结论

G6-1 的备份归档与恢复前校验首切片已完成。`LibraryExportService` 现在可以生成带时间戳命名建议的 `.assetbackup.zip`，归档使用 SQLite `backup()` 创建 WAL 一致性数据库快照，默认排除 `.thumbnails`，并将归档内容写入 `manifest.json`。

本切片不执行实际恢复写回；恢复写回已在 `g6-1-restore-2026-08-04.md` 作为独立切片实现。本报告仍不宣称 Desktop 设置页或 LAN/CLI 入口完成。

## 归档契约

- 顶层 manifest 使用 `format: "assetsmanager.library-backup"` 与 `schema_version: 1`。
- manifest 记录库名、创建时间、是否包含 thumbnails，以及每个 `data/` 成员的大小和 SHA-256。
- `assetmanager.db` 来自 SQLite 在线 backup 快照，并切回 `journal_mode=DELETE`，保证独立校验可读；不直接复制活动 WAL 主文件。
- 默认不包含 `.thumbnails`；调用方可显式设置 `include_thumbnails=True`。
- 归档目标必须位于当前库 RuntimeData 目录外，避免备份文件被自身扫描或覆盖源数据。
- 写入使用同目录临时文件后原子替换，失败时清理临时文件并保留既有目标。

## 恢复前校验

`validate_backup()` 只读执行以下检查：

- manifest 格式、schema version、库名和成员列表。
- ZIP 成员路径安全性，拒绝绝对路径、反斜杠穿越和 `..` 路径。
- 成员完整性：实际成员集合、声明大小和 SHA-256。
- `assetmanager.db` 反序列化后的 `PRAGMA quick_check`。
- 可选的目标库名匹配；不执行任何解压、移动、删除或数据库写回。

## 代码与测试

| 位置 | 作用 |
|---|---|
| `AssetsManager/application/library_export_service.py` | SQLite 快照、ZIP 归档、manifest、哈希与只读校验 |
| `AssetsManager/application/__init__.py` | 导出归档结果与校验结果类型 |
| `tests/unit/test_library_export_service.py` | 排除/包含 thumbnails、WAL 快照、目标路径保护、篡改和 zip-slip 回归 |

## 验证

| Gate | Result |
|---|---|
| G6-1 backup/export + Bootstrap/Runtime/数据库/架构/库服务回归 | `260 passed`，1 个既有 Windows `.pytest_cache` 警告 |
| Ruff | passed |
| compileall | passed |
| `git diff --check` | passed |

测试使用会话外可写 pytest basetemp；警告来自 Windows 环境下既有 `.pytest_cache` `WinError 183`，没有测试失败。

## 后续边界

- 产品入口：目标库选择、用户确认、恢复进度和失败反馈。
- Desktop 设置页、CLI 与 LAN 管理入口，以及恢复前用户确认和失败反馈。
- `_orphaned` 隔离区的可见恢复、清理和保留策略。
