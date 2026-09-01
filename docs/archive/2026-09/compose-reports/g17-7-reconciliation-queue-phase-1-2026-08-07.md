# G17.7 Reconciliation Queue — Phase 1

**日期：** 2026-08-07
**工作区：** `D:\~Vibe-Coding\Projects\AssetsManager_old-bak`
**分支：** `master`
**基线：** `fbf3403 Enforce schema object integrity for v6`
**状态：** 第一阶段已完成：建立独立 bounded reconciliation queue、持久 pending marker、dedupe、backoff、claim/lease、过期 lease recovery，并接入 asset-index refresh warning。真正的后台调度、跨进程 marker 协调和跨 projection generation 尚未完成。

## 1. 本阶段目标

G17.6 已经完成 Desktop caller 对 `FileOperationWarning` / `degraded` 的消费，但旧的 diagnostics deque 仍然只是 UI 报告通道：

- diagnostics 可以被 destructive drain；
- 进程退出后丢失；
- 没有 pending 状态；
- 没有 retry/backoff；
- 没有 claim/lease；
- 没有 crash recovery；
- 同一 root 的多个 warning 没有独立去重。

本阶段不复用 diagnostics queue，而是建立独立的 reconciliation task source。

## 2. 已完成实现

### 2.1 独立 queue 合同

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\reconciliation_queue.py`

新增：

- `ReconciliationKind`；
- `ReconciliationState`；
- `ReconciliationTask`；
- `ReconciliationQueue`；
- `ReconciliationQueueFull`；
- `ReconciliationQueuePersistenceError`；
- `reconciliation_backoff()`。

第一阶段只支持：

```text
asset_index_root_rescan
```

任务去重 key：

```text
(canonical_library_root, canonical_path, repair_kind)
```

`operation_id` 只作为审计关联字段，不参与唯一去重。

### 2.2 状态迁移与 worker lease

支持状态：

```text
pending
running
retryable
succeeded
terminal
cancelled
```

支持操作：

- `enqueue_or_merge()`；
- `claim_next()`；
- `mark_succeeded()`；
- `mark_retryable()`；
- `mark_terminal()`；
- `cancel()`；
- `recover_expired_running()`；
- `snapshot()`；
- `get()`。

`claim_next()` 会：

- 只领取到期的 `pending/retryable` 任务；
- 增加 queue 自己的 `attempts`；
- 写入 `lease_expires_at`；
- 保证同一队列实例内原子 claim。

启动时如果 marker 中有过期 `running` task，会自动转回 `retryable` 或 `terminal`，避免 worker 崩溃后任务永久卡死。

### 2.3 bounded 与去重

队列默认最大容量为 200。

容量不足时：

- 优先清理已完成的 `succeeded/terminal/cancelled` task；
- 不会静默丢弃 active task；
- 没有可安全清理的记录时抛出 `ReconciliationQueueFull`。

FileOperationService 会捕获 queue 写入异常，保持原有 filesystem 成功语义不变；同时通过 `file.index_refresh` telemetry 记录：

```text
reconciliation_state = queued | enqueue_failed | not_configured
```

### 2.4 原子 pending marker

`ReconciliationQueue` 支持可选 JSON marker：

```text
RuntimeData/<library-data>/reconciliation-queue.json
```

写入采用：

1. 同目录临时文件；
2. flush；
3. fsync；
4. `os.replace()` 原子替换。

该 marker 是 pending/recovery 数据源，不是跨进程锁。跨进程资源排他仍由现有 library lock / session ownership 负责。

### 2.5 FileOperationService 接入

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\file_operation_service.py`

`_record_index_refresh_issue()` 现在在保留原 warning 的同时，将 refresh issue 转换为 reconciliation task。

接入的 status 包括：

- `stale`；
- `busy`；
- `scan_failed`；
- `staged`。

关键不变量保持：

```text
FileOperationResult.ok == not errors
warning 不会转成 filesystem error
UI drain diagnostics 不会移除 reconciliation task
```

### 2.6 Asset-index rescan 执行边界

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\asset_index_reconciliation_service.py`

新增：

- `ReconciliationAttemptResult`；
- `AssetIndexReconciliationService.process_once()`；
- `AssetIndexReconciliationService.process_available()`。

执行动作固定为：

```python
asset_index_service.index_directory_tree_result(
    connection,
    session.root,
    task.path,
)
```

只有以下条件同时满足时才标记 `succeeded`：

```text
result.published is True
result.committed is True
```

处理策略：

- `BUSY` / `OperationalError`：retryable；
- `STALE`：retryable；
- `SCAN_FAILED` / 一般 OSError：retryable；
- `FileNotFoundError` / `NotADirectoryError`：terminal；
- 未知 contract/schema 异常：terminal；
- `committed=False` staged publish：retryable，不误报成功。

当前 service 是显式、可测试的 worker boundary，尚未启动后台线程。

### 2.7 Bootstrap/public wiring

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\bootstrap.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\__init__.py`

每个 `LibraryScopedServices` 现在可以取得：

- `reconciliation_queue`；
- `reconciliation_service`。

`FileOperationService` 与二者使用同一个 session-scoped queue。

## 3. 测试覆盖

新增：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\unit\test_reconciliation_queue.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\unit\test_asset_index_reconciliation_service.py`

补充：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_file_operation_service.py`

覆盖：

1. active task 去重；
2. operation id 合并；
3. bounded eviction；
4. queue full 不静默丢 active task；
5. JSON marker 原子恢复；
6. corrupt marker fail-closed；
7. claim/lease；
8. retry/backoff；
9. expired running recovery；
10. durable publish success；
11. staged publish 不误报成功；
12. OperationalError 重试；
13. missing path terminal；
14. diagnostics drain 不消费 reconciliation task；
15. warning enqueue telemetry。

当前已执行的定向回归：

```text
52 passed
```

并对 queue、reconciliation worker、file operation、bootstrap、runtime、asset-index、runtime-events、scoped service access 执行：

```text
184 passed, 1 skipped
```

全量 Python 回归在本轮最新代码上得到：

```text
2570 passed, 6 skipped, 1 warning, 2 failed
```

两个失败均位于既有保护域之外的 commerce/LAN 测试：

- `tests/lan/test_order_receipt_routes.py::test_receipt_cookie_is_sent_to_legacy_and_plural_order_routes`
- `tests/lan/test_storefront_commerce_integration.py::test_buyer_checkout_returns_503_when_seller_pauses_new_orders`

未修改这些文件；随后对这两个失败用例单独重跑，结果为：

```text
2 passed
```

因此当前判断为并行 dirty 工作区/全量运行环境造成的非稳定失败，不能将全量结果宣称为完全无失败。queue/reconciliation 相关及 bootstrap/runtime 相关回归目前保持通过。

## 4. 尚未完成事项

### 4.1 后台调度线程

G17.7.2 已补齐：

- session-scoped worker thread；
- condition/event wake-up；
- runtime lifecycle adapter；
- close 时停止并等待当前 claim；
- worker 异常隔离与 `last_worker_error`。

详细记录见：

`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\docs\compose\reports\g17-7-2-runtime-worker-lifecycle-2026-08-07.md`

仍未完成：

- worker restart policy；
- bounded stop/cancellation contract；
- 跨进程 marker lock/merge；
- wall-clock restart semantics。

### 4.2 跨进程 pending marker 协调

当前 JSON marker 使用原子替换，但没有独立的跨进程 marker lock。它依赖已有 library lock/session ownership。

后续需要验证：

- 多进程是否可能同时加载同一个 marker；
- marker merge 是否会丢任务；
- close/reopen 期间的读写顺序；
- lock 失败时是否应该转为 `BUSY` task。

### 4.3 非 Desktop 调用方

当前主要 enqueue 边界是：

```text
FileOperationService._record_index_refresh_issue()
```

Library restore、启动恢复、后台批处理及其他非 Desktop refresh 还没有全部接入统一 reconciliation layer。

### 4.4 跨 projection generation

asset index 之外的：

- metadata；
- tags；
- favorites；
- thumbnail；
- directory cache；

仍未纳入统一 generation contract。

## 5. 下一阶段 G17.7.3

G17.7.2 已完成，下一阶段建议按以下顺序继续：

1. 明确 worker exception policy 与 bounded restart；
2. 设计 bounded stop/cancellation contract；
3. 将 pending marker 的 retry time 转换为可重启语义；
4. 评估跨进程 marker lock/merge；
5. 统一非 Desktop caller 的 enqueue boundary；
6. 再进入跨 projection generation。

本阶段刻意没有改变 Desktop warning 的展示语义，也没有触碰：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\**`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\e2e\**`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tmp\**`
- commerce/LAN 写域。
