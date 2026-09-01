# G17.7.3 Worker Failure Policy / Restart-Safe Marker

**日期：** 2026-08-07
**工作区：** `D:\~Vibe-Coding\Projects\AssetsManager_old-bak`
**状态：** 已完成 bounded worker failure/stop contract 与 pending marker 的 restart-safe deadline 语义。跨进程 marker lock/merge 和非 Desktop caller 全量接入仍未完成。

## 1. 本阶段目标

G17.7.2 已完成 worker 启动、queue 唤醒和 runtime close，但仍有两个风险：

1. worker 普通异常可能无限重试；
2. marker 持久化了 monotonic timestamp，进程重启后不能直接比较。

本阶段只处理这两个问题，不改变 UI warning 语义，不接管 commerce/LAN 写域。

## 2. 已完成实现

### 2.1 Bounded worker exception policy

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\asset_index_reconciliation_service.py`

新增：

- `max_consecutive_errors`；
- `worker_faulted`；
- `consecutive_worker_errors`；
- `ReconciliationWorkerStopTimeout`；
- bounded retry/wait；
- thread start failure cleanup。

默认策略：

```text
连续 3 次未被 process_once 内部分类的异常
    ↓
worker 停止
    ↓
worker_faulted = True
last_worker_error 保留最近错误
```

普通 task-level failure 仍然由既有状态机处理：

```text
BUSY / STALE / SCAN_FAILED -> retryable
missing path               -> terminal
contract/schema error      -> terminal
```

### 2.2 Bounded stop contract

`stop(timeout=None)` 使用 service 配置的默认 timeout；当前默认值为 30 秒。

行为：

- 设置 stop event；
- 唤醒 queue condition；
- 等待当前 claim 收束；
- 在 timeout 内完成时正常返回；
- 超时则抛出 `ReconciliationWorkerStopTimeout`；
- 超时时不清除 worker state，不伪造 shutdown 成功；
- 底层 I/O 恢复后可以再次调用 stop 完成收口。

### 2.3 Restart-safe pending marker

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\reconciliation_queue.py`

marker format 从 v1 升级为 v2。

运行时仍使用 monotonic clock 计算 backoff，但 marker 不再保存可跨进程直接比较的 raw monotonic timestamp，而是保存 wall-clock deadline：

```text
next_attempt_at_wallclock
lease_expires_at_wallclock
```

启动时重新基于当前进程 monotonic clock rebasing：

```text
remaining = max(0, persisted_wall_deadline - current_wall_clock)
current_monotonic_deadline = current_monotonic + remaining
```

v1 marker 兼容策略：

- pending/retryable task：立即视为 due；
- running task：立即视为 lease expired，进入 recovery；
- 不信任旧进程的 monotonic timestamp，避免任务永久卡住。

### 2.4 Marker 数据校验

加载 marker 时新增：

- format version 校验；
- task state 校验；
- attempts 非负校验；
- max_attempts 正数校验；
- invalid marker fail-closed。

## 3. 测试结果

新增/补强：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\unit\test_reconciliation_queue.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\unit\test_asset_index_reconciliation_service.py`

覆盖：

- marker v2 persistence；
- retry deadline 跨重启 rebasing；
- v1 active marker fail-safe recovery；
- no-lease running marker recovery；
- bounded unexpected worker errors；
- worker faulted state；
- stop timeout；
- timeout 后保留 running state；
- retry stop 收口；
- thread start failure cleanup。

定向结果：

```text
16 passed
```

相关 bootstrap/runtime/file-operation 回归：

```text
135 passed
```

静态检查：

```text
Ruff：通过
Pyright：0 errors
```

## 4. 尚未完成风险

### 4.1 跨进程 marker lock/merge

当前 marker 使用 atomic replace，但多个进程仍可能：

1. 同时读取旧 marker；
2. 各自修改内存队列；
3. 后写入的一方覆盖前一方的新 task。

当前仍依赖已有 library ownership/lock。下一阶段需要决定：

- 复用现有 library lock；
- 增加 marker 专用 lock；
- 使用 SQLite durable queue；
- 或在写入前重新加载并 merge。

### 4.2 Worker restart policy

当前 worker faulted 后不会自动重启，必须由 runtime/application 层显式决定是否重新 `start()`。

### 4.3 非 Desktop caller

仍需继续审查并接入：

- library restore；
- startup recovery；
- background batch/import；
- LAN-triggered filesystem mutation；
- non-FileOperationService projection refresh。

### 4.4 Cross-projection generation

asset index 之外的 metadata、tags、favorites、thumbnail、directory cache 仍未统一 generation。

## 5. 下一阶段 G17.7.4

建议顺序：

1. 完成 non-Desktop caller inventory；
2. 决定 marker lock/merge 与 SQLite queue 的取舍；
3. 引入 queue generation / session epoch；
4. 增加 worker restart supervisor；
5. 最后进入跨 projection generation contract。
