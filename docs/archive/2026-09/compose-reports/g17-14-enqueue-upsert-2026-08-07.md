# G17.14 SQLite Enqueue Upsert — Closure

**日期：** 2026-08-07  
**工作区：** `D:\~Vibe-Coding\Projects\AssetsManager_old-bak`  
**分支：** `master`  
**HEAD：** `fbf3403 Enforce schema object integrity for v6`

## 1. 阶段目标

G17.12 已完成 per-task claim，G17.13 已完成 per-task completion。本阶段继续迁移
`enqueue_or_merge`，使 reconciliation queue 的三个主要写方向都具备 SQLite transaction
级别的 per-task 语义：

```text
enqueue/upsert → claim → completion
```

## 2. 实现

### 2.1 SQL dedupe/upsert

`SQLiteReconciliationQueueStore.enqueue_or_merge()` 现在在一个 `BEGIN IMMEDIATE`
事务中：

- 按 `(library_root, path, kind)` 查找现有 task；
- active task (`pending/running/retryable`)：
  - 保留 task id/state/attempt/lease；
  - merge reason；
  - merge operation_ids 并去重；
  - 更新 expected/observed revision；
  - 更新 audit timestamp；
- finished task (`succeeded/terminal/cancelled`)：
  - 删除旧 task；
  - 创建新的 pending task；
- 新 task：
  - 生成 task id；
  - 设置 attempts/max_attempts/deadline/audit fields；
- operation、task snapshot 和 generation 同事务提交。

### 2.2 Bounded capacity

SQL enqueue 现在也执行 bounded queue 合同：

- queue 未满：直接插入；
- queue 已满且有 finished task：淘汰最旧 finished task；
- queue 已满且只有 active/running task：抛出 `ReconciliationQueueFull`；
- finished replacement 会先释放原 task 的容量，再创建 replacement；
- capacity failure 不会提交半完成的 delete/insert。

### 2.3 Queue integration

SQLite-backed `ReconciliationQueue.enqueue_or_merge()` 已切换至 store-level upsert，
并刷新本地 snapshot/generation。

JSON marker queue 仍保留原有 in-memory enqueue/merge 路径。

## 3. 并发安全

两个 SQLite connection 可以在各自持有旧本地 snapshot 的情况下 enqueue：

- 不会通过整表 snapshot 覆盖其他进程的 task；
- active task 会在数据库中合并 operation id；
- 不同 repair key 会保留双方 task；
- generation 在同一事务内递增；
- SQLite writer admission 负责串行化事务。

当前 enqueue/upsert 已不再依赖 stale snapshot generation CAS 来完成正常写入；generation
CAS 仍保留用于尚未 per-task 化的 fallback/snapshot mutation。

## 4. 验证

分组定向回归全部通过，合计：

```text
138 passed
```

分组结果：

- core/schema/queue/store/migration/worker/runtime：96 passed；
- FileOperationService integration：42 passed。

新增覆盖：

- operation-id merge 与去重；
- revision merge；
- active task 保持 task id/state/lease；
- finished task replacement；
- finished eviction；
- active-only queue full guard；
- stale local snapshot enqueue 不覆盖其他 task；
- 既有 runtime/file-operation caller。

静态/语法门禁：

```text
Ruff：通过
Pyright：0 errors
compileall：通过
git diff --check：通过（tracked 修改）
```

## 5. 当前剩余边界

1. `recover_expired_running()` 公共 API 仍可继续收口为独立 per-task SQL mutation；
2. SQLite busy/lock 的跨进程 bounded retry 尚未统一；
3. 多进程 worker 没有共享 Condition，需要 polling/外部 wakeup 合同；
4. queue generation 仍不是全 projection generation；
5. enqueue/claim/completion 已 per-task，但部分 legacy/fallback snapshot path 仍存在；
6. `webui/**`、`tests/e2e/**`、`tmp/**` 保护写域未接管；
7. 工作区仍是多会话混合 dirty 状态，未执行 reset、checkout、全量 clean、staging 或
   commit。

## 6. 下一阶段建议

下一步可处理：

1. 公共 lease recovery per-task SQL 化；
2. SQLite busy/lock bounded retry 与 supervisor conflict retry；
3. 多进程 worker wakeup；
4. queue generation 与 projection generation 统一设计；
5. queue 主线收口后再进入 metadata/tags/favorites/thumbnail projection generation。
