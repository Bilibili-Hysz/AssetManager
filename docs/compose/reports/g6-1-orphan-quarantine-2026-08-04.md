---
feature: g6-1-orphan-quarantine-2026-08-04
status: partial-delivered
scope: reversible RuntimeData orphan-directory quarantine
verification: 161-targeted-regression-tests-passed
---

# G6-1 孤儿目录可恢复隔离子项 — 2026-08-04

## 结论

G6-1 的低风险防误删子项已完成：`DatabaseManager.clean_orphan_dirs()` 不再直接删除超过 7 天且未被当前库识别的 RuntimeData 目录，而是将其移动到 `RuntimeData/_orphaned/`。目录内容保持不变，目标名称冲突时使用带时间戳和序号的后缀；已知 hashed/legacy 目录、`Shared`、近期目录和 `_orphaned` 本身不会被处理。

本报告不宣称 G6-1 完整完成。JSON 导出首切片已在 `g6-1-metadata-export-2026-08-04.md` 单独收口，备份归档与只读恢复校验已在 `g6-1-backup-validation-2026-08-04.md` 收口，受控恢复 API 已在 `g6-1-restore-2026-08-04.md` 收口；产品恢复入口和隔离区生命周期管理仍是后续独立切片。

## 已实现行为

- 仅处理超过 7 天的未知运行时目录。
- 使用目录移动替代 `shutil.rmtree`，不会因一次识别错误直接丢失数据库和元数据。
- 优先使用同卷原子替换；失败时使用保守的移动回退，失败则保留原目录。
- `_orphaned` 被排除在扫描范围之外，避免隔离目录被再次嵌套处理。
- 目标目录已存在时生成唯一后缀，不覆盖先前隔离的内容。
- 符号链接不参与目录隔离，避免跟随链接影响运行时根目录外资源。

## 代码与测试

| 位置 | 作用 |
|---|---|
| `AssetsManager/core/database.py` | 可恢复孤儿目录隔离与冲突处理 |
| `AssetsManager/window.py` | 保持原有开库后的清理调用点不变 |
| `tests/core/test_path_resolver.py` | 已知目录、旧目录、近期目录、隔离内容与名称冲突回归 |

## 验证

| Gate | Result |
|---|---|
| G6-1 相关数据库/库生命周期/完整性/窗口回归 | `161 passed`，1 个既有 Windows `.pytest_cache` 警告 |
| Ruff | passed |
| compileall | passed |
| `git diff --check` | passed |

测试使用会话外可写 pytest basetemp；警告来自 Windows 环境下既有 `.pytest_cache` `WinError 183`，没有测试失败。

## 后续边界

- JSON 导出 schema 首切片已冻结并实现，详见 `g6-1-metadata-export-2026-08-04.md`；后续仍可扩展 CSV 与 tag metadata。
- 为 `_orphaned` 增加可见的恢复/清理入口与保留策略。
