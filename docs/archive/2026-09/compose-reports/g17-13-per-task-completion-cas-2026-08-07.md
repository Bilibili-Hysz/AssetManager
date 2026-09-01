# G17.13 SQLite Per-Task Completion CAS — Closure

**日期：** 2026-08-07  
**工作区：** `D:\~Vibe-Coding\Projects\AssetsManager_old-bak`  
**分支：** `master`  
**HEAD：** `fbf3403 Enforce schema object integrity for v6`

## 1. 阶段目标

G17.12 已将 SQLite `claim_next()` 改为 transaction-level per-task mutation。本阶段
继续处理 worker completion 路径，把 `mark_succeeded`、`mark_retryable`、
`mark_terminal` 和 `cancel` 从整表 snapshot replacement 迁移到带 state/attempt/lease
条件的 per-task SQL CAS。

## 2. 实现

### 2.1 Store-level completion mutations

`SQLiteReconciliationQueueStore` 新增：

- `mark_succeeded()`；
- `mark_retryable()`；
- `mark_terminal()`；
- `cancel()`。

每个 mutation：

- 使用 `BEGIN IMMEDIATE`；
- 校验 `task_id + library_root`；
- 对 running task 校验 `state='running'`；
- 校验 `attempts=expected_attempts`，避免旧 worker 完成新 worker 的 lease；
- 校验 `lease_expires_at_wallclock > now`，拒绝已过期 lease 的 completion；
- 在同一事务中更新 task row、generation 和刷新后的 snapshot；
- CAS 失败抛出 `ReconciliationQueuePersistenceConflict`；
- 已完成 task 的 terminal/cancel 操作保持幂等读取语义，不重复递增 generation。

`mark_retryable()` 会根据当前 attempts 判断 retryable 或 terminal，并在 SQLite 中将
monotonic `next_attempt_at` 转换为 wall-clock deadline。

### 2.2 Queue integration

SQLite-backed `ReconciliationQueue` 的 completion methods 现在调用 store-level mutation，
然后刷新本地 snapshot/generation。

如果旧 worker 在另一个 worker 完成 task 后尝试提交 completion：

1. SQL state/attempt/lease CAS 失败；
2. queue 重新加载 durable snapshot；
3. 向旧 worker 抛出明确 persistence conflict；
4. 不覆盖新 worker 的结果。

JSON marker queue 继续使用原有 in-memory 状态转换和 snapshot persistence。

## 3. 验证

分组定向回归全部通过，合计：

```text
135 passed
```

分组结果：

- core schema/migration、queue/store/migration、worker/runtime：93 passed；
- FileOperationService integration：42 passed。

新增覆盖：

- stale worker completion rejection；
- completion conflict 后 queue snapshot refresh；
- retryable/terminal generation 递增；
- pending/retryable terminal mutation；
- running task attempt/lease CAS；
- lease expired 后拒绝旧 completion；
- 既有 worker 和 file-operation caller regression。

静态/语法门禁：

```text
Ruff：通过
Pyright：0 errors
compileall：通过
git diff --check：通过（tracked 修改）
```

## 4. 当前边界

1. `enqueue_or_merge` 仍使用整表 snapshot CAS；
2. `recover_expired_running()` 公共 API 对 SQLite 仍走 queue snapshot path，worker claim
   内部已经使用 SQL recovery；
3. 多进程 worker 没有共享 Condition，仍依赖 polling 或外部 wakeup；
4. SQLite busy/lock 的跨进程 retry 尚未统一到 supervisor policy；
5. generation 仍是 queue generation，不是所有 projection 的统一 generation；
6. `webui/**`、`tests/e2e/**`、`tmp/**` 保护写域未接管；
7. 工作区仍是多会话混合 dirty 状态，未执行 reset、checkout、全量 clean、staging 或
   commit。

## 5. 下一阶段建议

下一阶段优先处理 `enqueue_or_merge`：

- 以 `(library_root, path, kind)` 做 SQL upsert/dedup；
- operation id 做事务内 JSON merge；
- active task 保留 state/attempt/lease；
- finished task 的新 warning 使用明确 replacement 规则；
- bounded queue capacity 与 finished eviction 也要在 SQL transaction 内完成。
