# G17.17-A/B Schema v17 与 `lease_token` 快照基础 — 2026-08-07

**工作区：** `D:\~Vibe-Coding\Projects\AssetsManager_old-bak`  
**分支：** `master`  
**HEAD：** `fbf3403`  
**状态：** A/B 基础切片完成；不代表 claim/completion token 语义完成。

## 1. 目标与边界

本切片只建立持久化字段和快照兼容基础：

```text
lease_token TEXT NULL
```

不在本切片中生成 token，不改变 worker claim/completion CAS，不允许旧 worker 与新 token worker 并行运行，也不宣称 rolling upgrade 已解决。

## 2. 已实现

### 2.1 Schema / migration v17

修改：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\core\schema_defs.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\core\db_migrations.py`

合同：

- `CURRENT_SCHEMA_VERSION = 17`；
- migration `17 / reconciliation_lease_token`；
- 对已有表幂等执行 `ALTER TABLE reconciliation_tasks ADD COLUMN lease_token TEXT`；
- 最终 schema contract 要求 `lease_token` 为可空 TEXT；
- migration 14 使用不含 token 的 legacy contract，避免 v14 创建阶段被新字段反向污染；
- v16 数据升级到 v17 时保留已有 task，token 默认 NULL。

### 2.2 Model / SQLite snapshot round-trip

修改：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\reconciliation_queue.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\reconciliation_queue_store.py`

合同：

- `ReconciliationTask.lease_token: str | None`；
- SQLite `_COLUMNS`、SELECT、INSERT、`_task_values()`、`_row_to_task()` 同步；
- `replace()` round-trip 保留 token；
- JSON fallback 对旧 marker 缺少 token 时加载为 `None`；
- generation / persistence conflict 逻辑未改变。

## 3. 新增验证

测试覆盖：

- v16→v17 migration 保留既有 task 且 token 为 NULL；
- SQLite token round-trip；
- 旧 JSON marker 缺失 token 仍可加载；
- 既有 queue migration、store、cross-process wakeup 回归。

当前初步结果：

```text
43 passed
Ruff：通过
Pyright：0 errors, 0 warnings
```

## 4. 明确未完成项

以下仍未实现：

1. claim 时生成不可预测的 `lease_token`；
2. completion/retry/terminal/cancel token CAS；
3. lease recovery 清除旧 token；
4. worker context 传递 token；
5. stale token / old worker fail-closed；
6. rolling upgrade capability gate；
7. managed SQLite connection 的真实跨进程 claim 矩阵。

因此当前安全结论是：

> A/B 只提供可迁移、可持久化、可回读的字段基础；token 仍为空，G17.17-C 之前不得让 worker 依赖该字段。

## 5. 下一步

1. 重新执行完整 G17.16 定向回归；
2. 重新执行当前工作区全量 Python 回归；
3. 开始 G17.17-C：claim token 生成与 claim CAS；
4. 在 C 通过后再接入 D/E/F，不得跨切片合并未验证的 worker 改动。

当前没有 staging、commit、reset、checkout 或清理操作。
