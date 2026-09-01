# G17.7 Reconciliation Queue — Final Closure

**日期：** 2026-08-07
**工作区：** `D:\~Vibe-Coding\Projects\AssetsManager_old-bak`
**分支：** `master`
**HEAD：** `fbf3403 Enforce schema object integrity for v6`
**状态：** G17.7 主线阶段完成收尾。reconciliation queue、asset-index repair worker、runtime lifecycle、bounded failure/stop、restart-safe marker、caller inventory 和 ownership boundary 均已完成当前约定范围内的实现与验证。跨 projection generation、SQLite durable queue、worker supervisor restart 仍作为后续架构阶段，不作为本阶段未完成的隐性功能继续堆叠。

## 1. 本阶段最终范围

G17.7 最终形成以下链路：

```text
FileOperationService refresh warning
        ↓
独立 ReconciliationQueue
        ↓
dedupe / bounded capacity / pending marker
        ↓
claim / lease / retry / backoff
        ↓
AssetIndexReconciliationService
        ↓
LibraryRuntime lifecycle worker
        ↓
durable asset-index publish
```

UI diagnostics 和 repair task source 保持独立：

- `drain_refresh_diagnostics()` 只消费 UI diagnostics；
- reconciliation task 不会因为 UI drain 被删除；
- filesystem success 不会因 warning/degraded 被改写为 filesystem failure。

## 2. 最终实现组成

### 2.1 Queue

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\reconciliation_queue.py`

已具备：

- `pending/running/retryable/succeeded/terminal/cancelled` 状态；
- canonical root/path/kind dedupe；
- operation id merge；
- bounded queue；
- queue full protection；
- claim/lease；
- expired running recovery；
- busy/stale/scan_failed/staged backoff；
- condition notification；
- retry next-attempt wait；
- atomic JSON marker；
- marker v1 fail-safe compatibility；
- marker v2 wall-clock deadline rebasing；
- invalid marker fail-closed。

### 2.2 Repair worker

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\asset_index_reconciliation_service.py`

已具备：

- explicit `process_once()`；
- `process_available()`；
- session-scoped daemon worker；
- start/stop idempotence；
- worker error budget；
- `worker_faulted`；
- `last_worker_error`；
- bounded stop timeout；
- thread start failure cleanup；
- durable publish success gate。

### 2.3 Runtime wiring

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\bootstrap.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\runtime.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\__init__.py`

已具备：

- `LibraryScopedServices.reconciliation_queue`；
- `LibraryScopedServices.reconciliation_service`；
- runtime creation 时 worker start；
- runtime close 时 worker stop/join；
- public application exports。

### 2.4 Caller boundary

live filesystem mutation 的统一 enqueue 边界保持为：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\file_operation_service.py`

已确认不需要为以下路径重复增加 queue 分支：

- Undo/Redo：复用 FileOperationService；
- Library restore：session closed + root reservation + RuntimeData replacement；
- LibrarySettingsAdapter restore：仅委托 export service；
- LAN metadata/tag/project/commerce：当前不直接执行 live asset-index filesystem refresh。

## 3. 收尾阶段修复

全量回归中曾出现一个 bootstrap 顺序污染：

```text
performance tests 创建独立 DatabaseManager
但未主动 close
全局 connection registry 遗留旧 id
后续 unmanaged-provider 测试受到影响
```

修改：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\performance\test_baselines.py`

为 4 个独立 `DatabaseManager()` 性能测试增加 pytest finalizer，确保每个测试结束时关闭 manager，避免连接 registry 污染后续测试。

该修复不改变生产行为，只修复测试资源生命周期。

## 4. 最终验证

### G17.7 定向组合回归

```text
221 passed
```

覆盖：

- queue；
- worker；
- marker restart semantics；
- bootstrap/runtime lifecycle；
- FileOperationService；
- LibraryService ownership/lock；
- PathResolver。

### 全量 Python 回归

```text
2583 passed, 6 skipped, 1 warning
```

6 个 skip 均为 Windows symlink/reparse 权限限制。

1 个 warning 是标准库 `zipfile` 对重复 ZIP member 的 warning：

```text
Duplicate name: 'data/assetmanager.db'
```

本次全量回归没有失败。

### 静态门禁

```text
Ruff：通过
Pyright：0 errors
git diff --check：通过
```

## 5. 当前明确保留的后续架构任务

这些不是 G17.7 当前实现的隐藏缺陷，而是下一阶段明确拆出的工作：

1. SQLite durable reconciliation queue；
2. 多进程 marker lock/merge 或 queue generation；
3. worker faulted 后 supervisor restart policy；
4. bounded cancellation 与底层 I/O interrupt；
5. metadata/tags/favorites/thumbnail/directory cache 的统一 projection generation；
6. legacy integer asset-index API 的最终迁移。

## 6. 工作区安全状态

本阶段没有：

- staging；
- commit；
- reset；
- checkout；
- 全量 clean；
- 覆盖其他并行会话修改；
- 修改 WebUI 写域；
- 修改 E2E 写域；
- 修改 tmp 写域；
- 接管 commerce/LAN 写域。

当前工作区仍是多会话混合 dirty 状态，最终应由用户在确认所有并行会话边界后，再决定如何拆分、staging 和提交。
