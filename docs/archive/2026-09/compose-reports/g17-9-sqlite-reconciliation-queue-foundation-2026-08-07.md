# G17.9 SQLite Durable Reconciliation Queue — Foundation Closure

**日期：** 2026-08-07  
**工作区：** `D:\~Vibe-Coding\Projects\AssetsManager_old-bak`  
**分支：** `master`  
**基线 HEAD：** `fbf3403 Enforce schema object integrity for v6`

## 1. 本阶段定位

G17.7 已完成 JSON pending marker、queue 状态机、claim/lease/retry 和 worker 生命周期。
G17.8 已完成有限 worker supervisor restart。本阶段继续推进下一项架构任务，但只收口
**SQLite durable queue foundation**，不在同一切片中强行完成 runtime cutover、旧 marker
迁移和多进程协调。

## 2. 已完成

### 2.1 SQLite schema v14

新增 `reconciliation_tasks` 表及唯一约束/索引：

- task identity：`(library_root, path, kind)`；
- queue state：`pending/running/retryable/succeeded/terminal/cancelled`；
- attempt、lease、error、revision、operation id 审计字段；
- `next_attempt_at_wallclock` 和 `lease_expires_at_wallclock` 明确使用 wall-clock
  持久化，避免把 Python monotonic 值直接写入跨进程存储；
- `idx_reconciliation_tasks_due` 用于按 library/state/deadline 查找任务；
- schema-object contract 会在首次创建及后续版本复核时检查表形状、唯一约束、索引和
  CHECK 合同。

涉及：

- `AssetsManager/core/schema_defs.py`
- `AssetsManager/core/db_migrations.py`

schema 版本从 v13 提升到 v14。

### 2.2 Persistence backend

新增：

- `AssetsManager/application/reconciliation_queue_store.py`

`SQLiteReconciliationQueueStore`：

- canonical construction 默认要求 managed connection ownership；
- raw/in-memory 测试只能显式传 `allow_unmanaged=True`；
- 使用 `db_write_lock(connection)` 统一连接访问；
- 无外层事务时独立 commit，已有外层事务时使用 savepoint，不提交 caller-owned writes；
- `replace()` 以单一事务替换一个 library 的 durable snapshot；
- 读取时把 wall-clock deadline rebasing 回当前进程的 monotonic deadline；
- 非法 state/kind/attempt/JSON operation id 记录会 fail-closed。

### 2.3 Queue backend contract

`ReconciliationQueue` 新增 `ReconciliationQueueStore` Protocol 和
`persistence_store` 注入点：

- 保留原有 JSON `persistence_path` 行为；
- `persistence_path` 与 `persistence_store` 不能同时使用；
- enqueue/claim/retry/succeed/terminal/cancel 等 caller 语义未改变；
- queue 仍负责进程内状态机和 condition notification，store 只负责 durable snapshot。

canonical application export 已增加：

- `SQLiteReconciliationQueueStore`
- `ReconciliationQueueStore`

## 3. 当前刻意未做的事情

本阶段**没有**把 `ApplicationBootstrap` 直接切换到 SQLite store，原因是 runtime cutover
还需要一个明确的旧 JSON marker 一次性迁移合同：

1. marker 导入与 SQLite snapshot 的线性化顺序；
2. 导入成功后的 marker rename/delete 失败处理；
3. marker 与 SQLite 同时存在时的 stale re-import 防护；
4. cutover 期间 queue worker、close 和 crash recovery 的顺序；
5. 多进程 marker/queue generation 的协调责任。

当前 canonical runtime 仍使用 G17.7 的 JSON marker 路径；本阶段仅提供经过测试的
SQLite backend 和 v14 schema，不宣称 durable backend 已经接入生产 runtime。

## 4. 验证

组合定向回归：

```text
68 passed
```

覆盖：

- 原有 JSON queue 全部状态转换与 marker 恢复；
- SQLite store round-trip；
- wall-clock deadline restart rebasing；
- outer transaction rollback/savepoint ownership；
- managed/unmanaged connection ownership；
- malformed SQLite row fail-closed；
- v14 schema creation、idempotence、incompatible pre-existing table rejection；
- DatabaseManager close/reopen 后 durable queue 恢复。

静态/语法门禁：

```text
Ruff：通过
Pyright（queue/store/schema/migration）：0 errors
compileall：通过
git diff --check：通过（tracked 修改）
```

## 5. 工作区纪律

- 未执行 `git reset`、`git checkout`、全量 `git clean`；
- 未 staging、未 commit；
- 未回滚或覆盖其他会话的 dirty 修改；
- 未接管 `webui/**`、`tests/e2e/**`、`tmp/**` 保护写域。

## 6. 下一阶段建议

下一步应单独启动 **G17.10 runtime cutover and legacy marker migration**：

1. 先定义 JSON marker -> SQLite 的一次性导入合同；
2. 增加 crash/retry/rename failure 矩阵；
3. 只在导入合同通过后，让 canonical bootstrap 构造 SQLite-backed queue；
4. 暂时保留 JSON marker 只读迁移兼容，不做双写；
5. 再单独处理多进程 lock/queue generation，而不是把它隐含在本次 cutover 中。
