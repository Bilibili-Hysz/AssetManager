# G17.16 跨进程唤醒与持久化冲突策略 — 阶段记录

**日期：** 2026-08-07（星期五）
**工作区：** `D:\~Vibe-Coding\Projects\AssetsManager_old-bak`
**分支：** `master`
**HEAD：** `fbf3403` (`Enforce schema object integrity for v6`)
**状态：** 实现完成，待后续全量回归与工作区发布整理；不代表整个项目完成。

## 1. 阶段目标

G17.15 已完成 SQLite durable queue 的 per-task enqueue、claim、completion、lease recovery 和 store 层 busy/locked bounded retry。本阶段收口两个边界：

1. `threading.Condition` 只在进程内有效，跨进程 enqueue/cancel/retry/complete 不能依赖即时通知；
2. `ReconciliationQueuePersistenceConflict` 不能由 supervisor 统一当作普通异常处理，必须区分可重试 writer/claim race 与旧 worker completion 冲突。

## 2. 已实现合同

### 2.1 跨进程 worker wakeup

采用 **SQLite generation polling + 原子 snapshot refresh + 进程内 Condition fast path**，不引入 OS named event、独立 watcher 或额外 notification table。

- `reconciliation_queue_state.generation` 是 durable change sequence；
- 每次真正的 SQLite queue mutation 与 task 改变在同一事务内递增 generation；
- `load_snapshot()` 原子读取 generation 与 task rows；
- `threading.Condition` 仅用于同一进程的快速唤醒；
- store-backed `wait_for_ready()` 增加 `cross_process_poll_interval`，默认 `0.5` 秒，必须为有限正数且小于 60 秒；
- `wait_for_ready()` 初始先 refresh，覆盖 enqueue-before-wait race；之后以 bounded poll slice 检查 generation；
- 整体 timeout 使用单一 deadline，不会因每轮 poll 重置；
- refresh 的 SQLite I/O 在 Condition 锁外执行；
- `next_due_at()` 保持本地 snapshot 语义，不隐式触发数据库 I/O；
- `refresh()` 是显式 durable refresh 入口；
- `wake()` 仍由 stop event 配合用于快速退出，通知丢失不会造成永久睡眠；
- wake signal 使用独立 `Event`，Condition 获取采用 non-blocking best effort，避免 stop 在队列/数据库写锁上等待；
- 运行期 snapshot refresh 与 `_set_store_snapshot_unlocked()` 都拒绝 generation 回退；
- worker-scoped terminal/cancel mutation 始终保留 running state + attempts + lease CAS，不能覆盖 lease recovery 后的 retryable task；
- stale completion verifier 将非 running、过期 lease 和 attempts 变化视为旧 ownership 已失效，旧结果不再重放。

### 2.2 persistence conflict 分类与 supervisor policy

`ReconciliationQueuePersistenceConflict` 增加公开、向后兼容的元数据，不依赖解析错误消息：

- `retryable`；
- `retry_after_refresh`（与 `retryable` 同步的描述性别名）；
- `stale_worker_completion`；
- `operation`。

默认未知 conflict：不可重试。SQLite store 当前分类：

| 操作 | 分类 | supervisor 行为 |
|---|---|---|
| generation/replace、enqueue ownership、claim ownership | `retryable=True` | refresh 后 bounded semantic retry |
| `mark_succeeded`、`mark_retryable` 丢失 running lease/attempt | `stale_worker_completion=True` | 不重放旧结果；refresh 后确认后继状态则 benign no-op |
| terminal/cancel CAS、task disappearance、mutation-result 缺失 | 默认 fail-closed（worker attempt 的 state mutation 会标记 stale completion） | 无法确认所有权时继续抛出，不猜测状态 |
| schema、corruption、reload 失败、未知 conflict | 不可重试 | fail-closed，不进入 semantic retry |

`AssetIndexReconciliationService` 新增：

- `max_persistence_conflict_retries`，默认 `2`；
- `persistence_conflict_backoff`，默认 `0.05` 秒，有限且小于 60 秒；
- retry 前显式刷新 durable queue；
- backoff 可被 `stop_event` 打断；
- retry budget 耗尽后不再把旧 operation 无限交给 worker restart；
- stale completion 若发现 durable task 已 `SUCCEEDED`、`TERMINAL`、`CANCELLED` 或 attempts 已变化，则作为 `StaleWorkerCompletion` 结果返回，不重新执行旧 completion，也不消耗 worker restart budget；
- unknown/unresolved conflict 直接使 worker 显式 fault，保留 fail-closed 状态。

## 3. 修改文件

生产代码：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\reconciliation_queue.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\reconciliation_queue_store.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\asset_index_reconciliation_service.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\bootstrap.py`

测试：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_reconciliation_queue_cross_process_wakeup.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_reconciliation_runtime_lifecycle.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\unit\test_reconciliation_supervisor_conflicts.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\unit\test_reconciliation_queue_sqlite_store.py`

## 4. 验证记录

### G17.16 定向回归

交接时的初始记录为 57 passed；在修复生命周期测试文件并补充关闭重试覆盖后，于 2026-08-07 重新执行：

```text
59 passed
```

覆盖：

- queue JSON/SQLite 基线；
- SQLite store generation/claim/completion/recovery/busy retry；
- worker lifecycle、restart、stop timeout；
- supervisor retry budget、unknown conflict、stale completion；
- runtime cutover/lifecycle；
- 双连接远端 enqueue、enqueue-before-wait、wake/stop 竞态。

### 相邻服务回归

```text
77 passed, 1 skipped
```

范围：

- `tests/integration/test_file_operation_service.py`；
- `tests/integration/test_asset_index_service.py`。

唯一 skip 是 Windows symlink 权限不可用，不是 G17.16 失败。

### 当前工作区全量 Python 回归

在完成上述定向回归后，于 2026-08-07 对当前混合工作区执行 `pytest -q`：

```text
2635 passed, 6 skipped, 1 warning
```

6 个 skip 均为 Windows symlink 权限不可用；1 个 warning 是测试主动构造重复 ZIP 条目。

### 静态门禁

```text
Ruff：通过
Pyright：0 errors, 0 warnings
compileall：通过
定向文件 whitespace 检查：通过
```

未重复执行项目全量 Python 回归 `2583 passed`；该数字属于 G17.7 基线，不能作为本阶段全量回归结果。

## 5. 深度审查后的剩余边界

本阶段已修复审查发现的 generation 回退、wake 阻塞、普通 notify 过早返回、stale terminal 覆盖和 wait refresh 静默退出问题。仍明确保留以下后续边界，不将其伪装成已完成：

1. `wait_for_ready()` 的整体 timeout 在同步 SQLite `load_snapshot()` 已经开始后不能硬中断；当前保证是 refresh/persistence retry 有限，stop 由独立 wake event + bounded join 控制；
2. queue mutation 仍在 queue lock 保护下调用 store，后续可继续拆分 lock/I/O 边界；
3. task identity 仍使用 `task_id + attempts + lease`，尚未引入持久化 `claim_id/lease_token`；
4. 本阶段跨连接集成测试使用受控 unmanaged SQLite 连接，尚未覆盖两个 `DatabaseManager` 托管连接的真实多进程矩阵；
5. JSON marker 是单进程兼容 fallback：已增加显式 reload，但不宣称具有 SQLite generation 的跨进程同步合同。

## 6. 工作区一致性

本阶段没有执行：

- `git reset`；
- `git checkout`；
- 全量 `git clean`；
- staging；
- commit；
- 保护域写入。

本次复盘盘点 Git 为 `186` 个 tracked status entries、`249` 个 untracked entries；工作区仍是多会话混合 dirty 状态。`webui/**`、`tests/e2e/**`、`tmp/**` 仍保持只读/不接管；其已有 dirty 内容未被本阶段修改。

## 7. 当前边界与剩余任务

G17.16 只收口 queue wakeup 和 supervisor conflict policy，以下仍未完成：

1. busy/lock retry 在更高层的统一 ownership contract；
2. queue generation 与全 projection generation 统一（G18）；
3. queue archive retention/cleanup；
4. queue admission 的 library-root containment 与 marker migration 写域保护审查；
5. bounded filesystem/SQLite/ZIP cancellation（G19）；
6. legacy API 最终迁移（G20）；
7. WebUI/E2E、LAN reconnect、browser acceptance 和真实重启矩阵（G21）；
8. 混合 dirty worktree 的选择性 inventory、staging、可审计提交与发布整理（G22）。

因此当前正确结论是：**G17.16 定向实现、审查修复和验证已完成，但项目整体尚未完成，且尚未进入 release/commit 阶段。**

## 8. 2026-08-08 复测与 G17.17 兼容性更新

G17.17-A/B/C/D 在不改变 G17.16 wakeup/conflict 合同的前提下，新增了 schema v17、`lease_token` snapshot、claim token generation 和 worker mutation token CAS。复测结果：

```text
G17.16 定向回归：65 passed
当前工作区全量 Python：2642 passed, 6 skipped, 1 warning
Ruff：通过
Pyright：0 errors, 0 warnings
compileall：通过
```

6 个 skip 仍为 Windows symlink 权限不可用；1 个 warning 仍为测试主动构造重复 ZIP 条目。此前一次全量 run 出现过 1 个 LAN startup cleanup timing failure；该 LAN 测试单独连续 5 次、每次 2 参数通过，随后全量 clean run 通过，因此未将其归因于 G17.17。

本次复盘当前 Git 可枚举状态为：

```text
186 tracked modified
252 untracked
0 staged
```

仍未执行 staging、commit、reset、checkout 或清理；`webui/**`、`tests/e2e/**`、`tmp/**` 仍未接管。

G17.17-D 已完成核心 token CAS，但 G17.17-E/F、rolling-upgrade cutover、renew/rotation、真实 managed 多进程矩阵以及 G18–G22 仍未完成。

盘点修正（2026-08-08）：新增 D 阶段记录后，Git 当前可枚举状态为 `186 tracked modified`、`253 untracked`、`0 staged`；无源码冲突标记。
