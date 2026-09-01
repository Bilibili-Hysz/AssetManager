---
feature: g6-1-metadata-export-2026-08-04
status: partial-delivered
scope: session-bound portable tags-notes-urls JSON export
verification: 202-targeted-regression-tests-passed
---

# G6-1 元数据 JSON 导出首切片 — 2026-08-04

## 结论

G6-1 的 metadata JSON 导出首切片已完成。每个 Runtime 的 `LibraryScopedServices` 现在提供 `LibraryExportService`，以只读方式读取 `file_tags` 和 `file_meta`，输出可被脚本和其他工具消费的 schema-versioned JSON。

本切片不宣称完整备份能力完成：SQLite 数据目录归档、`.thumbnails` 排除策略、恢复前校验和受控恢复 API 已在后续报告收口；恢复入口和导出 UI 仍待后续任务。

## JSON 契约

- 顶层包含 `format: "assetsmanager.metadata"`、`schema_version: 1`、UTC `exported_at`、库名与条目数组。
- 每个条目包含 `path`、`path_type`、`tags`、`notes` 和 `urls`。
- 库内路径以相对库根路径输出并使用 `/` 分隔；数据库中存在的库外路径保留为显式 `absolute` 类型。
- 条目和标签按稳定规则排序，重复标签去重，确保同一数据库状态可以产生可比较的 JSON。
- 不导出 thumbnail cache、SQLite 内部缓存字段、用户凭据或 share password hash。
- `export_metadata_json()` 先写同目录临时文件，再原子替换目标文件；写入失败时清理临时文件并保留原目标。

## 代码与测试

| 位置 | 作用 |
|---|---|
| `AssetsManager/application/library_export_service.py` | Runtime scoped 导出契约、路径投影与原子 JSON 写入 |
| `AssetsManager/application/bootstrap.py` | 将导出服务装配到 `LibraryScopedServices` |
| `AssetsManager/repositories/metadata_repository.py` | 提供 file_meta 批量只读导出行 |
| `AssetsManager/repositories/tag_repository.py` | 提供 file_tags 批量只读导出行 |
| `tests/unit/test_library_export_service.py` | schema、路径、稳定排序、敏感字段排除和原子写入回归 |

## 验证

| Gate | Result |
|---|---|
| G6-1 导出 + Bootstrap/Runtime/数据库/架构回归 | `202 passed`，1 个既有 Windows `.pytest_cache` 警告 |
| Ruff | passed |
| compileall | passed |
| `git diff --check` | passed |

测试使用会话外可写 pytest basetemp；警告来自 Windows 环境下既有 `.pytest_cache` `WinError 183`，没有测试失败。

## 后续边界

- Desktop/CLI/LAN 恢复入口、用户确认和失败反馈仍待实现。
- 为 Desktop 设置页、未来 CLI 和 LAN 管理端提供显式入口；本切片暂不新增 UI 或 HTTP 路由。
