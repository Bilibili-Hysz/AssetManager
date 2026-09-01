# G17.10 Reconciliation Queue Runtime Cutover — Closure

**日期：** 2026-08-07  
**工作区：** `D:\~Vibe-Coding\Projects\AssetsManager_old-bak`  
**分支：** `master`  
**HEAD：** `fbf3403 Enforce schema object integrity for v6`

## 1. 阶段目标

G17.9 已完成 SQLite durable queue foundation，但 canonical runtime 仍使用 JSON marker。
本阶段完成一次性 marker migration 和 canonical bootstrap cutover：

```text
legacy JSON marker
        ↓ strict one-time migration
SQLite reconciliation_tasks
        ↓
SQLiteReconciliationQueueStore
        ↓
ReconciliationQueue + worker runtime
```

## 2. 实现组成

### 2.1 Marker migration contract

新增：

- `AssetsManager/application/reconciliation_queue_migration.py`

提供：

- `migrate_reconciliation_marker()`；
- `ReconciliationMarkerMigrationStatus`；
- `ReconciliationMarkerMigrationResult`；
- `ReconciliationMarkerMigrationError`。

合同：

1. marker 不存在：no-op；
2. SQLite queue 为空且 marker 有任务：先 durable `replace()`，再归档 marker；
3. SQLite queue 为空且 marker 为空：只归档 marker；
4. SQLite queue 非空且 marker 为空：只归档 marker；
5. SQLite queue 非空且 marker 非空：只有 stable task snapshot 等价时才允许归档；
6. 不等价时 fail-closed，拒绝静默丢任务或状态降级；
7. SQLite 持久化成功但 marker rename 失败时抛出
   `durable_store_updated=True`，下次启动可重试归档而不会重复导入；
8. 已存在且内容不同的 `.migrated` archive 不会被覆盖。

JSON/SQLite 在重新加载时都可能把 wall-clock deadline rebasing 成不同的 monotonic
值，因此等价性比较只忽略 deadline/lease 的进程内表示差异，仍严格比较 task identity、
state、attempt、reason、operation id、error、revision、audit timestamps 和 bounds。

### 2.2 Canonical bootstrap cutover

修改：

- `AssetsManager/application/bootstrap.py`
- `AssetsManager/application/__init__.py`

canonical `ApplicationBootstrap._build_services()` 现在：

1. 取得 managed library connection；
2. 构造 `SQLiteReconciliationQueueStore`；
3. 迁移并归档旧 `reconciliation-queue.json`；
4. 构造以 SQLite store 为 backend 的 `ReconciliationQueue`；
5. 后续 FileOperationService、runtime worker 和 close lifecycle 继续复用同一个 queue。

旧 marker 归档名为：

```text
reconciliation-queue.json.migrated
```

store 不拥有 connection 生命周期，仍由 `DatabaseManager` 管理；runtime close 先停止
worker，再由原有 session/database lifecycle 关闭连接。

## 3. 验证

本阶段定向组合回归：

```text
73 passed
```

覆盖：

- JSON marker import；
- marker archive；
- empty marker retirement；
- durable publish 后 rename 失败再启动重试；
- SQLite publish failure 保留原 marker；
- non-empty durable queue conflict fail-closed；
- canonical bootstrap runtime cutover；
- worker lifecycle；
- FileOperationService caller adoption；
- DatabaseManager close/reopen；
- queue、store、v14 migration 全部相关状态转换。

静态/语法门禁：

```text
Ruff：通过
Pyright：0 errors
compileall：通过
git diff --check：通过（tracked 修改）
```

## 4. 重要边界

1. 这是单进程启动 cutover 合同，不是多进程 marker lock/merge 合同；
2. marker archive 归档不会被覆盖；archive conflict 会阻止启动；
3. worker 未开始前 migration 失败不会主动关闭 session，runtime creation gate 可重试；
4. migration 失败不会把 filesystem operation 伪装成失败，因为 migration 发生在 runtime
   assembly，而不是 FileOperationService 的 filesystem mutation 内；
5. `webui/**`、`tests/e2e/**`、`tmp/**` 保护写域未接管；
6. 工作区仍是多会话混合 dirty 状态，未执行 reset、checkout、全量 clean、staging 或
   commit。

## 5. 下一阶段建议

G17.10 只解决了单进程 cutover。后续应另立阶段处理：

1. 多进程 marker/queue generation 与 single-writer 责任；
2. SQLite queue 的多进程 claim/lease CAS，而非当前 session-scoped in-process queue
   snapshot replacement；
3. queue generation 与 projection generation 的统一审计合同；
4. migration archive retention/cleanup policy；
5. bounded cancellation 与底层 filesystem scan interruption。
