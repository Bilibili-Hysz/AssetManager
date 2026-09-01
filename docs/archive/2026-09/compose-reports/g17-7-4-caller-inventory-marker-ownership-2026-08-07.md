# G17.7.4 Caller Inventory / Marker Ownership Boundary

**日期：** 2026-08-07
**工作区：** `D:\~Vibe-Coding\Projects\AssetsManager_old-bak`
**状态：** 已完成非 Desktop caller inventory，并确认真实 runtime 的 marker 写入受现有 library ownership/lock 边界保护；本阶段没有引入重复 marker lock，避免与 `LibraryService` 已持有的 `QLockFile` 产生双重生命周期。marker v2 的 wall-clock restart semantics 和 worker bounded policy 已通过定向回归。

## 1. 非 Desktop caller inventory

### 1.1 已覆盖路径

#### FileOperationService

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\file_operation_service.py`

以下 filesystem mutation 都通过 `_record_index_refresh_issue()` 进入 reconciliation queue：

- create folder；
- rename/move；
- copy；
- duplicate；
- permanent delete；
- trash delete；
- restore backup；
- directory move/tree refresh。

#### UndoService

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\undo_service.py`

Undo/Redo 通过传入既有 `FileOperationService`，因此继续复用同一 queue，不需要另建 enqueue 分支。

#### Desktop caller

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\panels\file_list\_actions.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\panels\file_list\_base.py`

Desktop 只负责消费 warning/degraded feedback，不直接拥有 reconciliation task，符合 diagnostics 与 repair source 分离的合同。

### 1.2 不需要强行接入的路径

#### LibraryExportService.restore_backup

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\library_export_service.py`

restore backup 要求 session closed，并且在独立 root reservation 与 library lock 下替换整个 RuntimeData。此路径不是一个可以在现有 live runtime 中安全 enqueue 的普通 filesystem mutation。

恢复后的 reconciliation marker 随 RuntimeData 一起恢复；下次重新打开 library 时由 queue v2 loader 处理 wall-clock deadline 与旧 marker recovery。

#### LibrarySettingsAdapter.restore_backup

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\library_settings_adapter.py`

该 adapter 只是在 session closed 约束下委托给 `LibraryExportService.restore_backup()`，没有独立 projection refresh，因此不新增 queue 分支。

#### LAN metadata/tag/project routes

当前 LAN 路径主要修改 metadata、tags、project 或 commerce projection，不直接执行 FileOperationService 的 filesystem mutation + asset-index refresh 链路。本阶段不扩大 queue 到 LAN/commerce 写域。

### 1.3 当前结论

当前没有发现一个必须新增独立 enqueue 分支、且不经过 `FileOperationService` 的 live filesystem refresh caller。

因此本阶段选择：

```text
不重复扩展 caller 分支
保持 FileOperationService 为 live filesystem mutation 的唯一 enqueue 边界
```

## 2. Marker ownership boundary

### 2.1 现有 runtime ownership

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\library_service.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\core\library_lock.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\core\path_resolver.py`

真实 runtime 的 queue 构造路径是：

```text
LibraryService.open_session()
    ↓
获取 canonical root ownership
    ↓
获取 library QLockFile
    ↓
ApplicationBootstrap.runtime_for(session)
    ↓
构造 ReconciliationQueue
```

因此，同一 library 的第二个进程不能正常构造第二个 live runtime queue。

现有锁测试已验证：

- 同进程同 root 的 lock sharing；
- 不同 root 隔离；
- 子进程无法抢占已打开 library；
- close 后锁可释放；
- failed open/close 不会错误释放替代 ownership。

### 2.2 为什么本阶段不再添加 queue 专用 lock

如果在 `ReconciliationQueue` 内再次创建 `LibraryLock`：

- 会与 `LibraryService` 已持有的 QLockFile 产生重复引用；
- queue 生命周期可能延长 library lock；
- runtime close 与 queue close 的顺序更复杂；
- 容易造成“queue 已停但 library lock 未释放”的隐藏泄漏。

因此当前合同是：

```text
ReconciliationQueue 只在 live LibrarySession ownership 内使用
LibraryService 负责跨进程 library exclusion
```

### 2.3 剩余边界风险

直接手工构造：

```python
ReconciliationQueue(persistence_path=...)
```

本身不会验证外部 ownership。这是低层测试/基础设施 API，不是 canonical application wiring。后续如果需要公开跨进程 queue API，应增加显式 owner token 或改用 SQLite durable store，而不是让 queue 私自重复获取 library lock。

## 3. 当前验证

本阶段组合回归：

```text
221 passed
```

覆盖：

- reconciliation queue；
- worker failure/stop；
- marker restart semantics；
- bootstrap/runtime lifecycle；
- FileOperationService；
- LibraryService ownership/lock；
- PathResolver。

静态检查：

```text
Ruff：通过
Pyright：0 errors
```

## 4. 下一阶段 G17.7.5

下一阶段建议不再增加 caller 分支，而是进入：

1. queue generation/session epoch；
2. marker schema 与 generation 绑定；
3. worker faulted 后的 supervisor restart policy；
4. durable queue 与跨 projection generation 设计；
5. 最后才考虑把 metadata/tags/favorites/thumbnail 纳入同一 reconciliation contract。
