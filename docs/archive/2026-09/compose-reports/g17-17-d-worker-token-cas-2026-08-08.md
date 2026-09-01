# G17.17-D Worker-owned Mutation Lease Token CAS — 2026-08-08

**工作区：** `D:\~Vibe-Coding\Projects\AssetsManager_old-bak`  
**分支：** `master`  
**状态：** D 核心实现完成；仍不代表 G17.17 的 renew、rolling upgrade 与完整 cutover 全部完成。

## 1. 本切片目标

将 `lease_token` 纳入 worker-owned task mutation 的持久化 CAS，使旧 worker 或错误 token 不能修改 recovery 后的新 ownership。

## 2. 已实现

修改：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\reconciliation_queue.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\reconciliation_queue_store.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\asset_index_reconciliation_service.py`
- reconciliation queue/store/supervisor tests

合同：

1. `mark_succeeded`、`mark_retryable` 的 SQL WHERE 同时校验：
   ```text
   task_id + state + attempts + lease_expires_at_wallclock + lease_token
   ```
2. worker-owned `mark_terminal` / `cancel` 同样校验 token；非 running 的用户/队列状态变更不要求 lease token；
3. token 缺失或错误时 fail-closed，返回 `stale_worker_completion` conflict；
4. 成功、retryable、terminal、cancelled 会清空 token；
5. recovery 后缺失 token 的 running task 即使 expiry 尚未到，也会立即回收，避免 v16/旧 marker ownership 悬挂；
6. reconciliation supervisor 将 claimed task 的 token传入 succeeded/retryable/terminal路径；
7. in-memory fallback 与 SQLite durable store 保持同一 token 生命周期。

## 3. 验证

截至 2026-08-08：

```text
G17.16 定向回归：65 passed
C/D queue/store/runtime/supervisor 定向回归：51 passed
Ruff：通过
Pyright：0 errors, 0 warnings
compileall：通过
全量 Python 回归：2642 passed, 6 skipped, 1 warning
```

6 个 skip 是 Windows symlink 权限不可用；1 个 warning 是测试主动构造重复 ZIP 条目。

全量回归期间此前曾出现 1 次 LAN startup cleanup timing failure；LAN 定向两参数连续 5 次通过，之后全量 clean run 通过。该一次性失败不归因于 G17.17-D。

## 4. 明确未完成项

1. lease renew API；
2. token rotation / renew 与旧 token 失效的完整策略；
3. worker stop/restart 后旧 worker 的全链路 capability gate；
4. migration/cutover 期间旧版本 writer 的阻断；
5. 真正新旧进程并行时的 rolling-upgrade 安全合同；
6. managed SQLite connection 的真实多进程 claim/recovery/completion 矩阵；
7. queue archive retention、G18/G19/G20/G21/G22 后续阶段。

## 5. 下一步

下一切片为 **G17.17-E：worker/supervisor 完整适配与 renew 边界**：

- 明确 task operation context 是否必须携带不可变 token；
- 增加 renew API 或明确 lease 不可续约；
- 增加 stop/restart、stale completion、wrong-token、expired-token 的 supervisor 级测试；
- 完成后再进入 F 的 cutover/cross-process hardening。

当前没有 staging、commit、reset、checkout 或清理操作。
