# G17.17 Claim Identity（`lease_token`）实施计划 — 2026-08-07

**工作区：** `D:\~Vibe-Coding\Projects\AssetsManager_old-bak`  
**分支：** `master`  
**HEAD：** `fbf3403`  
**前置阶段：** G17.16 跨进程唤醒与持久化冲突策略已完成并通过当前工作区验证；本计划不代表 G17.17 已实现。

## 1. 当前验证基线

在进入 G17.17 前，当前工作区已完成：

```text
G17.16 定向回归：59 passed
相邻服务回归：77 passed, 1 skipped
全量 Python 回归：2635 passed, 6 skipped, 1 warning
Ruff：通过
Pyright：0 errors, 0 warnings
compileall：通过
```

当前工作区仍为多会话混合 dirty 状态：

```text
186 tracked modified
249 untracked
0 staged
```

没有执行 staging、commit、reset、checkout 或清理。

## 2. 当前 claim identity 事实

当前 queue 的 ownership 依赖：

```text
task_id + attempts + lease_expires_at_wallclock
```

现有实现位置：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\reconciliation_queue.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\reconciliation_queue_store.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\asset_index_reconciliation_service.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\core\schema_defs.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\core\db_migrations.py`

SQLite store 的快照替换仍是：

```text
DELETE FROM reconciliation_tasks WHERE library_root=?
INSERT ... (<显式 _COLUMNS>)
```

因此不能先在表里加 `lease_token`，再慢慢补 store 或 worker：旧列清单的全量 replace 会静默把新 token 写成 NULL，或者让新旧 worker 产生不兼容的 completion 语义。

## 3. 设计决策

### 3.1 第一版只引入一个持久化字段

只引入：

```text
lease_token TEXT NULL
```

不同时引入 `claim_id + lease_token`。第一版 token 的职责是表达一次持久化 lease ownership，并和 `attempts`、expiry、generation CAS 一起校验。

### 3.2 不宣称支持旧新进程并行

同表 nullable token 方案只有在以下 cutover 前提成立时才安全：

1. 停止旧 reconciliation worker；
2. 完成 migration 17；
3. 部署包含完整 token 读写和 CAS 的新代码；
4. 验证旧 worker 不再继续写；
5. 再恢复新 worker。

如果产品要求真正的 rolling upgrade / 新旧 worker 并行，必须改为独立 lease 表或等价 capability gate；不能依赖同表 nullable 列解决。

### 3.3 严格保留旧版本兼容边界

migration 14 的 legacy schema 校验不能突然要求 `lease_token`。需要使用版本化的 legacy contract：

- migration 14 创建/校验无 token 的旧表；
- migration 17 幂等地 `ALTER TABLE ... ADD COLUMN lease_token TEXT`；
- migration 17 后的最终 schema contract 才要求该列；
- migration 17 必须验证已有 rows 的 token 默认为 NULL 且不改变其他字段。

## 4. 分片实施顺序

### G17.17-A：schema v17 / migration guard

写入范围：

- `AssetsManager/core/schema_defs.py`
- `AssetsManager/core/db_migrations.py`
- `tests/core/test_reconciliation_queue_migration.py`

必须完成：

- migration version 17；
- nullable `lease_token`；
- legacy v14 contract 不被新列要求污染；
- fresh DB、v16 DB、重复 migration、已有 task rows 的升级测试；
- schema contract 明确 token 类型和 nullable 语义。

### G17.17-B：model / durable snapshot round-trip

写入范围：

- `AssetsManager/application/reconciliation_queue.py`
- `AssetsManager/application/reconciliation_queue_store.py`
- reconciliation 专属 unit tests

必须完成：

- `ReconciliationTask.lease_token`；
- SQLite `_COLUMNS`、SELECT、INSERT、row conversion、replace round-trip 同步；
- JSON fallback 对旧 marker 缺失 token 默认为 NULL；
- generation conflict refresh 不得丢 token；
- 不在此切片提前放宽或改变 completion ownership 语义。

### G17.17-C：claim token 生成与 claim CAS

必须完成：

- 每次成功 claim 生成不可预测的新 token；
- token 与 attempts、running state、lease expiry 同一事务写入；
- 同一次 claim 的返回对象和 durable snapshot 使用同一 token；
- claim 失败或冲突不得泄漏半成品 token；
- lease recovery 清除旧 token。

### G17.17-D：completion / retry / terminal / cancel token CAS

所有 worker-owned mutation 必须带 token：

- `mark_succeeded`；
- `mark_retryable`；
- `mark_terminal`；
- `cancel`；
- 未来的 renew API。

错误 token、空 token、过期 token、attempts 不匹配必须 fail-closed 或转为明确 stale no-op，不能回退到仅 task_id/attempts 的旧语义。

### G17.17-E：worker / supervisor 适配

必须同步：

- claim result → worker operation context；
- succeeded/retryable/terminal/cancel 调用；
- persistence conflict refresh 后使用最新 durable ownership；
- stale token 不得重放旧 operation；
- stop/restart 后旧 worker 不得继续提交；
- retry budget 与 stale completion 观测保持现有合同。

### G17.17-F：cutover / cross-process hardening

必须覆盖：

- 两连接竞争 claim；
- lease recovery 与旧 completion 竞争；
- generation conflict 不回写旧 token；
- cross-process wakeup 读取完整 token；
- migration/cutover 期间旧 worker 被明确阻止；
- 真实 managed SQLite connection 的关闭与重启矩阵。

## 5. 必须固化的关键测试

1. `replace()` round-trip 保留 token；
2. 旧 schema marker/JSON 缺少 token 可加载；
3. v16 → v17 migration 幂等且不丢 task；
4. claim 每次产生不同 token；
5. recovery 清除旧 token；
6. 正确 token才能 succeeded/retryable/terminal/cancel；
7. 旧 token 不能修改 recovery 后的新 attempt；
8. 错 token和过期 token不改变任务；
9. generation conflict refresh 后不回写旧 token；
10. 旧 writer 的全量 replace 不得静默清空 token；
11. worker stale completion 不触发错误 restart；
12. 新旧进程并行策略要么 fail-closed，要么有明确 capability gate。

## 6. 已执行切片（截至 2026-08-07）

本次已实际完成 G17.17-A 与 G17.17-B 的最小基础切片：

- `CURRENT_SCHEMA_VERSION` 升至 17；
- 新增幂等 migration `reconciliation_lease_token`；
- migration 14 使用 legacy contract，不会在 v17 之前强制要求 token；
- `reconciliation_tasks.lease_token TEXT NULL` 加入最终 schema contract；
- `ReconciliationTask`、SQLite `_COLUMNS`、row conversion、snapshot replace round-trip 同步；
- JSON marker 对缺失 `lease_token` 的旧版本数据保持兼容；
- 新增 v16→v17 保留任务数据、SQLite token round-trip、旧 JSON marker 兼容测试。

本切片**没有**接入 claim/completion token CAS，也没有改变 worker ownership 语义；当前所有新任务 token 仍为 NULL。因而不能把本切片称为 G17.17 完成，也不能宣称 rolling upgrade 已安全。

初步验证：

```text
G17.17-A/B 定向回归：43 passed
Ruff：通过
Pyright：0 errors, 0 warnings
```

涉及文件仍未 staging/commit；没有执行 reset、checkout 或清理。对共享的 `core/schema_defs.py` 与 `core/db_migrations.py` 只做了 reconciliation 增量修改，未回滚或覆盖既有 commerce/LAN 内容。

## 7. 剩余任务与下一执行入口

下一执行入口是 **G17.17-C：claim token 生成与 claim CAS**。在此之前必须再次运行 G17.16 定向回归和当前工作区全量 Python 回归，确认 migration v17 不影响既有 queue、commerce 与 runtime 合同。

G17.17-C 之后仍必须按 D→E→F 顺序完成 completion/retry/terminal/cancel CAS、worker/supervisor 适配、cutover 与跨进程 hardening。

## 8. 当前结论

> G17.16 已验证完成；G17.17-A/B 已实现并通过初步定向门禁；claim identity 仍未接入 worker，项目整体尚未完成。
## 9. 2026-08-08 执行更新：G17.17-C/D

在 A/B 基础上已完成 C/D：

- claim 生成并持久化 `uuid4().hex` lease token；
- recovery 清空 token，缺失 token 的 running task 立即回收；
- succeeded/retryable/terminal/cancel worker mutations 纳入 token CAS；
- supervisor 将 claimed token 传入 completion/retry/terminal；
- 错 token fail-closed，终态清空 token。

最新验证：

```text
G17.16 定向回归：65 passed
C/D 定向子集：51 passed
全量 Python：2642 passed, 6 skipped, 1 warning
Ruff：通过
Pyright：0 errors, 0 warnings
compileall：通过
```

G17.17-E 仍未完成：renew/rotation 边界、stop/restart capability gate、真实 managed 多进程矩阵与 rolling-upgrade cutover。
