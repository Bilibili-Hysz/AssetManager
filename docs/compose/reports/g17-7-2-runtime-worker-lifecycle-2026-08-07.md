# G17.7.2 Runtime Worker / Lifecycle Integration

**日期：** 2026-08-07
**工作区：** `D:\~Vibe-Coding\Projects\AssetsManager_old-bak`
**状态：** 已完成 session-scoped worker 的唤醒、停止、异常记录和 `LibraryRuntime` lifecycle 接入。跨进程 marker 协调、worker restart policy 和跨 projection generation 仍未完成。

## 1. 本阶段目标

G17.7 Phase 1 已经提供：

- bounded reconciliation queue；
- pending marker；
- retry/backoff；
- claim/lease；
- asset-index rescan executor。

本阶段将显式 executor 接入 session runtime，但不改变 Desktop warning 语义。

## 2. 已完成实现

### 2.1 Queue condition notification

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\reconciliation_queue.py`

新增：

- queue-owned `Condition`；
- `wait_for_change()`；
- `wait_for_ready()`；
- `wake()`；
- queue mutation notification；
- next due time 计算。

`wait_for_ready()` 将：

- due task 检查；
- queue mutation wait；
- next retry time wait；

放在同一个 condition lock 下，避免 enqueue 与 worker wait 之间产生丢唤醒窗口。

### 2.2 可停止 reconciliation worker

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\asset_index_reconciliation_service.py`

新增：

- `start()`；
- `stop()`；
- `is_running`；
- `last_worker_error`；
- daemon worker loop。

worker 行为：

```text
claim due task
    ↓
process_once()
    ↓
成功：继续处理下一个 task
失败/无任务：等待 queue notification 或 next retry time
    ↓
stop event
    ↓
唤醒并 join 当前 worker
```

保证：

- 重复 `start()` 不会启动第二个 worker；
- `stop()` 可重复调用；
- stop 会唤醒 condition wait；
- 当前 rescan 未结束前，stop 会等待当前 claim 完成；
- worker 内部异常不会直接杀死应用进程；
- 最近一次 worker exception 会通过 `last_worker_error` 暴露；
- 线程启动失败时会清理内部 lifecycle state，不留下伪 running worker。

### 2.3 Runtime lifecycle 接入

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\bootstrap.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\runtime.py`

`ApplicationBootstrap.runtime_for()` 现在：

1. 构造 session-scoped reconciliation service；
2. 将其注册为 `LibraryRuntime` lifecycle adapter；
3. runtime 接受前启动 worker；
4. runtime close 时由现有 adapter cleanup 顺序停止 worker；
5. 再继续 undo/service cleanup 和 session teardown。

因此 worker 不会在 `LibrarySession` 已经失效后继续持有数据库操作 lease。

## 3. 测试覆盖

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\unit\test_asset_index_reconciliation_service.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_reconciliation_runtime_lifecycle.py`

覆盖：

- worker enqueue 唤醒；
- background worker 完成 durable publish；
- worker stop；
- stop 幂等；
- start 幂等；
- thread start failure cleanup；
- bootstrap runtime 自动启动 worker；
- library close 停止 worker。

本阶段定向 worker/runtime 回归：

```text
7 passed
93 passed
```

静态门禁：

```text
Ruff：通过
Pyright：0 errors
```

## 4. 当前风险

### 4.1 Worker restart policy 尚未正式定义

当前 worker 捕获普通 `Exception` 后继续等待，保留 `last_worker_error`。但还没有：

- 最大连续异常次数；
- worker 自动重启次数上限；
- terminal worker state；
- UI/diagnostics 对 worker stopped 的专门提示。

### 4.2 跨进程 marker 仍不是并发安全 store

JSON marker 使用 atomic replace，但当前不提供独立跨进程 merge lock。它仍依赖 library ownership/lock。

### 4.3 Stop 等待是无超时的

`stop()` 会等待当前 rescan 完成。这样可以保护 session 资源不被提前关闭，但如果底层 I/O 永久阻塞，runtime close 也会被拖住。下一阶段需要评估：

- bounded stop timeout；
- lease 与 cancellation；
- 超时后的可审计 degraded close。

### 4.4 时间来源

worker 使用 monotonic clock，适合 retry/backoff；pending marker 仍需在后续阶段明确 wall-clock/restart 语义，不能直接将 monotonic timestamp 当作跨进程持久时间。

## 5. 下一阶段

建议进入 G17.7.3：

1. 明确 worker exception policy；
2. 加入 bounded stop/cancellation contract；
3. 设计跨进程 marker lock/merge；
4. 将 pending marker 的 retry time 转换为可重启语义；
5. 统一非 Desktop caller 的 enqueue boundary；
6. 最后再进入跨 projection generation。
