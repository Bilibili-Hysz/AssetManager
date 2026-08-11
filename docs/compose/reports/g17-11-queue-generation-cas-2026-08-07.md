# G17.11 Reconciliation Queue Generation CAS Guard — Closure

**日期：** 2026-08-07  
**工作区：** `D:\~Vibe-Coding\Projects\AssetsManager_old-bak`  
**分支：** `master`  
**HEAD：** `fbf3403 Enforce schema object integrity for v6`

## 1. 阶段目标

G17.10 已完成单进程 JSON marker -> SQLite runtime cutover，但多个进程各自持有
in-memory `ReconciliationQueue` 时，原来的 snapshot `replace()` 可能出现：

```text
Process A loads generation N
Process B loads generation N
Process A publishes claim/update
Process B publishes stale snapshot and silently overwrites A
```

本阶段为 durable snapshot 增加 generation CAS guard，先阻止 silent lost update，保持
现有 queue caller API 和 worker 状态机不变。

## 2. 实现

### 2.1 Schema v15

新增：

```text
reconciliation_queue_state(
    library_root PRIMARY KEY,
    generation,
    updated_at
)
```

涉及：

- `AssetsManager/core/schema_defs.py`
- `AssetsManager/core/db_migrations.py`

schema 版本由 v14 升至 v15。generation 从 0 开始，每次 durable snapshot replace
成功后递增。

### 2.2 Queue contract

新增：

- `ReconciliationQueueSnapshot(tasks, generation)`；
- `ReconciliationQueuePersistenceConflict`；
- `ReconciliationQueue.persistence_generation`；
- `ReconciliationQueueStore.load_snapshot()`；
- `ReconciliationQueueStore.replace(..., expected_generation=...) -> generation`。

当 queue 以旧 generation 发布 snapshot 时：

1. SQLite store 在 `BEGIN IMMEDIATE` 事务内检查 generation；
2. generation 不匹配时回滚并抛出 `ReconciliationQueuePersistenceConflict`；
3. queue 丢弃本地未持久化快照，重新加载 durable snapshot；
4. caller/worker 得到明确冲突，而不是继续覆盖其他进程的状态。

因此两个进程同时 claim 同一 task 时，最多一个 claim 能成功发布；另一个进程会收到
冲突并恢复到 durable `RUNNING` 状态。

### 2.3 Store 事务边界

`SQLiteReconciliationQueueStore`：

- `load_snapshot()` 在一个 read transaction 内读取 tasks + generation；
- `replace()` 无外层事务时使用 `BEGIN IMMEDIATE`；
- caller 已持有外层事务时继续使用 savepoint；
- generation/state row 与 task snapshot 在同一事务中更新；
- generation conflict 不提交 task delete/insert；
- connection lifecycle 仍由 `DatabaseManager` 所有。

## 3. 验证

本阶段定向组合回归：

```text
132 passed
```

覆盖：

- v15 migration、state schema shape 和 incompatible state rejection；
- generation 初始值及递增；
- stale snapshot conflict；
- conflict 后本地 queue 恢复 durable tasks；
- 两个 SQLite connection 竞争 claim 时的 single-winner CAS；
- JSON marker migration/cutover；
- worker、runtime close 和 FileOperationService 既有链路。

静态/语法门禁：

```text
Ruff：通过
Pyright：0 errors
compileall：通过
git diff --check：通过（tracked 修改）
```

## 4. 明确边界

1. 本阶段是 optimistic snapshot generation CAS，不是完整的 per-task SQL claim API；
2. 冲突会 fail-closed 并要求 caller/worker 重试，当前没有自动无限 retry；
3. 多进程之间的 `Condition` notification 不共享，另一个进程可能需要 polling 或
   外部 wakeup 才能尽快发现新任务；
4. queue snapshot replace 仍会序列化整个 library queue，后续可再拆成 per-task SQL
   mutation；
5. generation row 还不是 projection generation 的统一合同；
6. `webui/**`、`tests/e2e/**`、`tmp/**` 保护写域未接管；
7. 工作区仍是多会话混合 dirty 状态，未执行 reset、checkout、全量 clean、staging 或
   commit。

## 5. 下一阶段建议

下一阶段应在不改变当前 CAS 安全性的前提下，单独研究：

1. per-task SQL `claim_next` / `mark_*` mutation，减少整表 snapshot replacement；
2. SQLite busy/lock retry 与跨进程 worker wakeup；
3. queue generation 与 asset-index/metadata projection generation 统一；
4. supervisor 在 persistence conflict 后的 bounded retry policy；
5. 底层 scan cancellation 和 lease heartbeat 合同。
