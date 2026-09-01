# G17.15 Lease Recovery and SQLite Busy Retry — Closure

**日期：** 2026-08-07  
**工作区：** `D:\~Vibe-Coding\Projects\AssetsManager_old-bak`  
**分支：** `master`  
**HEAD：** `fbf3403 Enforce schema object integrity for v6`

## 1. 阶段目标

G17.14 已完成 enqueue/upsert per-task SQL 化。本阶段继续处理两项剩余基础能力：

1. public `recover_expired_running()` 仍走 queue snapshot path；
2. SQLite transient busy/locked 会被包装成 persistence error，缺少统一 bounded retry。

## 2. 实现

### 2.1 Public lease recovery per-task SQL

新增 `ReconciliationQueueRecoveryResult`，并将 SQLite-backed
`ReconciliationQueue.recover_expired_running()` 接入
`SQLiteReconciliationQueueStore.recover_expired_running()`。

现在 public recovery 在一个 `BEGIN IMMEDIATE` 事务中：

- 选择所有过期 running lease；
- attempts 未耗尽：更新为 retryable，并设置 LeaseExpired/backoff；
- attempts 已耗尽：更新为 terminal，并保留 LeaseExpired 审计；
- 同一事务递增 queue generation；
- 返回恢复后的 task snapshot；
- 多进程竞争 recovery 时不会重复执行同一状态转换。

JSON marker queue 继续使用原有 in-memory recovery path。

### 2.2 SQLite busy/locked bounded retry

`SQLiteReconciliationQueueStore` 增加可配置 bounded retry：

- 默认最多重试 3 次；
- 默认 base backoff 50ms，按 `2**retry` 递增；
- 只识别异常链中明确的 SQLite `busy/locked` OperationalError；
- 每次 retry 重新执行完整 store operation，而不是重复部分 SQL；
- transaction failure 会先 rollback/savepoint cleanup，再进入下一次 retry；
- 非 busy 错误、CAS conflict、schema/lifecycle 错误不被吞掉；
- 不允许无限 retry。

## 3. 验证

分组定向回归全部通过，合计：

```text
141 passed
```

分组结果：

- core/schema/queue/store/migration/worker/runtime：99 passed；
- FileOperationService integration：42 passed。

新增覆盖：

- public lease recovery per-task mutation；
- 双 connection recovery 不重复；
- lease recovery generation；
- transient `database is locked` bounded retry；
- busy retry budget 与完整 operation 重试；
- 既有 enqueue/claim/completion/runtime/file-operation 回归。

静态/语法门禁：

```text
Ruff：通过
Pyright：0 errors
compileall：通过
git diff --check：通过（tracked 修改）
```

## 4. 当前边界

1. busy retry 当前在 SQLite store operation 层完成，不等于所有数据库 caller 都已有统一
   retry；
2. persistence generation conflict 仍不是 transient busy，默认 fail-closed；
3. supervisor 对 completion/enqueue conflict 的 bounded retry 尚未加入；
4. 跨进程 worker 没有共享 Condition，仍需要 polling/外部 wakeup；
5. queue generation 仍不是全 projection generation；
6. `webui/**`、`tests/e2e/**`、`tmp/**` 保护写域未接管；
7. 工作区仍是多会话混合 dirty 状态，未执行 reset、checkout、全量 clean、staging 或
   commit。

## 5. 下一阶段建议

下一阶段优先处理跨进程 worker wakeup 和 supervisor 对 persistence conflict 的有限
重试，然后再进入 queue generation 与 metadata/tags/favorites/thumbnail 等 projection
generation 的统一设计。
