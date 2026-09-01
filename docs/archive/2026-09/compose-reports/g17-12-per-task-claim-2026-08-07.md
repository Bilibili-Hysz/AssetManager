# G17.12 SQLite Per-Task Claim — Closure

**日期：** 2026-08-07  
**工作区：** `D:\~Vibe-Coding\Projects\AssetsManager_old-bak`  
**分支：** `master`  
**HEAD：** `fbf3403 Enforce schema object integrity for v6`

## 1. 阶段目标

G17.11 已通过 queue generation CAS 阻止 stale snapshot silent overwrite，但 claim 仍
走整表 snapshot replacement。本阶段把最敏感的 worker claim/lease 路径改为 SQLite
transaction-level per-task mutation，减少双进程竞争时的整表写入，并让 claim 由 SQLite
single-writer 事务直接裁决。

## 2. 实现

### 2.1 Store-level atomic claim

`SQLiteReconciliationQueueStore.claim_next()` 现在：

1. 使用 `BEGIN IMMEDIATE` 获得 SQLite writer admission；
2. 恢复已经过期的 running lease；
3. 选择最早 due 的 pending/retryable task；
4. 在同一事务内把该 row 更新为 running、递增 attempts、写入 wall-clock lease；
5. 在同一事务内递增 `reconciliation_queue_state.generation`；
6. 在同一事务内读取刷新后的 task snapshot；
7. 返回 `ReconciliationQueueClaimResult(snapshot, claimed)`。

如果另一个进程已经 claim，第二个进程不会重复 claim；它读取到当前 durable snapshot
并返回无 claim 的结果。

### 2.2 Queue integration

`ReconciliationQueue.claim_next()` 在 SQLite backend 下使用 store-level atomic claim，
同时刷新本地 task snapshot 和 generation；JSON marker queue 保留原有 in-memory
claim 路径。

新增公开 contract：

- `ReconciliationQueueClaimResult`；
- `ReconciliationQueuePersistenceConflict`（继续用于 stale snapshot 的 enqueue/mark
  等整表写操作）；
- `ReconciliationQueueSnapshot`；
- `persistence_generation`。

### 2.3 Lease recovery

SQLite claim transaction 内处理：

- lease 过期且 attempts 未耗尽：转 retryable，设置 `LeaseExpired` 和 bounded backoff；
- attempts 已耗尽：转 terminal，保留 `LeaseExpired` 审计信息；
- 恢复与新 claim 使用同一个 generation commit。

## 3. Schema / transaction 边界

- schema v15 的 `reconciliation_queue_state` 继续作为 generation owner；
- task deadline 继续以 wall-clock 持久化，返回 queue 时 rebasing 到 monotonic；
- queue snapshot `replace()` 仍保留 generation CAS，用于 enqueue/merge 和 mark_* 等尚未
  改为 per-task SQL 的路径；
- per-task claim 不会绕过 `DatabaseManager` ownership 或 `db_write_lock`；
- store 不拥有 connection lifecycle。

## 4. 验证

分组定向回归全部通过，合计：

```text
133 passed
```

分组包括：

- core migration/schema + queue/store/migration unit：77 passed；
- reconciliation worker、SQLite runtime reopen、runtime cutover/lifecycle：14 passed；
- FileOperationService integration：42 passed。

静态/语法门禁：

```text
Ruff：通过
Pyright：0 errors
compileall：通过
git diff --check：通过（tracked 修改）
```

新增/强化覆盖：

- generation 初始/递增；
- stale snapshot conflict；
- 双 SQLite connection 竞争 claim 的 single-winner 行为；
- 过期 lease 的 SQL recovery；
- claim 后本地 queue snapshot/generation 刷新；
- 既有 runtime worker 和 file-operation caller。

## 5. 当前仍保留的边界

1. enqueue/merge、mark_succeeded、mark_retryable、mark_terminal、cancel 仍使用整表
   snapshot CAS；
2. 这意味着多进程 enqueue/mark 冲突会 fail-closed 并要求上层 retry，而不是静默 merge；
3. 多进程 worker 没有共享 `Condition`，仍依赖 polling/外部唤醒；
4. claim 已经是 per-task SQL mutation，但 queue 的其他 projection mutation 尚未统一为
   per-task repository；
5. SQLite busy/lock 的跨进程 retry 和 supervisor conflict retry 仍未扩展；
6. `webui/**`、`tests/e2e/**`、`tmp/**` 保护写域未接管；
7. 工作区仍是多会话混合 dirty 状态，未执行 reset、checkout、全量 clean、staging 或
   commit。

## 6. 下一阶段建议

优先将 `mark_succeeded` / `mark_retryable` / `mark_terminal` 改为带 task state/lease
条件的 per-task SQL CAS；之后再处理 enqueue/merge 的 SQL upsert/operation-id merge。
这样可以逐步消除整表 snapshot replacement，而不一次性改变所有 queue caller 语义。
