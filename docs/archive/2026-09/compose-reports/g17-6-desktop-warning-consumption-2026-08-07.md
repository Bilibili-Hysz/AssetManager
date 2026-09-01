# G17.6 Desktop Warning Consumption — 深度审查报告

**日期：** 2026-08-07  
**工作区：** `D:\~Vibe-Coding\Projects\AssetsManager_old-bak`  
**分支：** `master`  
**HEAD：** `fbf3403 Enforce schema object integrity for v6`  
**状态：** G17.6 已完成 Desktop file-list caller 的 warning/degraded adoption；filesystem 成功与 Undo/Redo 成功语义保持不变。真正可恢复的 reconciliation queue、持久化 pending marker 和跨 projection generation 仍未完成。工作区保持多会话混合 dirty，未 staging、未 commit。

## 1. 本轮目标

G17.5 已建立：

- `FileOperationResult.warnings`；
- `FileOperationResult.degraded`；
- `FileOperationWarning`；
- operation-correlated diagnostics queue。

但 Desktop file-list caller 仍有三个问题：

1. batch result 的 warnings 没有统一进入 feedback；
2. Path-returning 命令可能依赖错误的 thread-local warning；
3. Undo/Redo、duplicate、drag-drop 的 refresh warning 可能被丢弃或错误归属。

本轮只处理 Desktop caller adoption，不触碰 WebUI、E2E、tmp 或 commerce/LAN 写域。

## 2. 已完成实现

### 2.1 Operation-filtered diagnostics drain

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\file_operation_service.py`

`drain_refresh_diagnostics()` 现在支持：

```python
service.drain_refresh_diagnostics(operation_id)
```

传入 operation id 时：

- 只消费对应 operation 的 diagnostics；
- 其他并发 operation 的 warning 保留在 queue；
- 不会因为 duplicate、rename 或 Undo 先执行 drain 而吞掉其他操作的 warning。

### 2.2 ActionsMixin 统一 Path warning consumer

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\panels\file_list\_actions.py`

新增统一 helper：

```python
_consume_refresh_warnings(service)
```

其职责：

1. 获取当前 Path command 的 `last_operation_id`；
2. 按 operation id 消费 diagnostics；
3. 兼容没有新 drain API 的旧 service double；
4. 保留 warnings，不把 warning 转成 exception；
5. 将 warning 传入当前 operation feedback。

已接入：

- rename；
- new folder；
- duplicate；
- batch rename；
- Undo；
- Redo。

Undo/Redo 的 bool 成功语义保持不变：

- `True` 仍然推进 Undo/Redo history；
- warning 只产生 degraded feedback；
- warning 不会导致 `undo_failed` / `redo_failed`；
- warning 不会跳过已经成功的 undo record。

### 2.3 Batch result warning feedback

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\panels\file_list\_actions.py`

以下 batch caller 现在将 `result.warnings` 传递到统一 feedback：

- paste copy/move；
- move to trash；
- permanent delete；
- duplicate aggregate。

当 warning 与 errors 同时存在时：

- errors 仍然决定主状态是 partial/failed；
- warning 作为附加 degraded summary 展示；
- 不会让 warning 覆盖 filesystem error 语义。

### 2.4 Drag-drop feedback adoption

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\panels\file_list\_base.py`

drag-drop 现在：

- 聚合内部 move 与外部 copy 的 `changed_paths`；
- 聚合 `errors`；
- 聚合 `warnings`；
- 保持内部 move 的 Undo record；
- 保持 selection、refresh、detail reload；
- 最终调用统一 `_show_operation_feedback()`；
- 同时保留日志记录用于诊断。

warning-only drag-drop 不会弹出错误对话框，也不会被显示成 filesystem failure。

### 2.5 Feedback 与多语言合同

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\panels\file_list\_base.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\i18n\en.json`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\i18n\zh.json`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\i18n\ja.json`

新增 feedback 状态：

- `filelist.feedback.degraded`；
- `filelist.feedback.partial_degraded`；
- `filelist.feedback.failed_degraded`；
- `filelist.feedback.operation.drop`。

状态优先级：

```text
running
errors + changed_paths + warnings => partial_degraded
errors + warnings                 => failed_degraded
errors                            => partial / failed
warnings                          => degraded
无 errors/warnings                 => succeeded
```

## 3. 测试补充

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\desktop\test_file_list_shim.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_file_operation_service.py`

新增/补强覆盖：

1. operation feedback 的 degraded 状态；
2. partial/failed 与 warning 同时存在时的 feedback；
3. paste warning 传递；
4. drag-drop warning 进入统一 feedback；
5. rename/new-folder warning 消费；
6. duplicate warning 消费；
7. batch rename warning 消费；
8. Undo/Redo 成功时仍传递 warning，history 语义不变；
9. worker thread 产生 warning 后 operation id 仍可被正确关联；
10. operation-filtered diagnostics 不消费其他 command 的 warning；
11. stale session completion 防护保持不变。

## 4. 验证结果

### 4.1 G17.6 定向回归

执行：

```text
pytest -q \
  tests/core/test_db_migrations.py \
  tests/integration/test_asset_index_repository_session_binding.py \
  tests/integration/test_asset_index_service.py \
  tests/integration/test_search_service.py \
  tests/integration/test_file_operation_service.py \
  tests/lan/test_lan_api.py \
  tests/desktop/test_file_list_shim.py --tb=short
```

结果：

```text
490 passed, 2 skipped
```

### 4.2 全量 Python 回归

执行：

```text
pytest -q
```

结果：

```text
2513 passed, 4 skipped, 1 warning
```

4 个 skip 仍是 Windows symlink/reparse 权限限制；1 个 warning 是重复 ZIP member 测试产生的标准 `zipfile` warning。

### 4.3 静态门禁

```text
ruff check AssetsManager tests       通过
pyright                               0 errors, 0 warnings, 0 informations
git diff --check -- AssetsManager tests 通过
```

## 5. 当前剩余风险

### P1：仍没有真正可恢复的 reconciliation queue

当前 diagnostics queue 解决了：

- warning 不丢失；
- worker/UI 跨线程传递；
- operation id 精确归属。

但它仍然是 bounded in-memory queue：

- 进程退出后丢失；
- 没有自动 retry；
- 没有 crash recovery；
- 没有 pending marker；
- 没有 root rescan deduplication。

### P1：部分非 Desktop 调用方仍不会主动 drain diagnostics

Desktop file-list 主要路径已经接入，但其他直接调用 `FileOperationService` Path API 的调用方仍可能不消费 diagnostics。尤其是脱离当前 Panel feedback 生命周期的 Undo/Redo 或后台 service 调用，需要后续统一进入 session-scoped reconciliation layer。

### P2：warning 展示仍是摘要级别

当前 UI 显示 warning 数量和 degraded 状态，但没有把具体：

- code；
- failed path；
- retry policy；
- 下一次 rescan 时间；

展示给用户。详细信息仍依赖 `FileOperationWarning` 和 telemetry。

### P2：legacy integer API 仍无法区分空目录与 scan failure

旧 API 返回 `0` 时，仍无法稳定区分：

- 合法 empty；
- scan failed；
- skipped。

异常形式 stale/busy 已有兼容处理，但 integer degraded 仍需后续 deprecation。

### P2：跨 projection generation 尚未统一

asset index、metadata、tags、favorites、thumbnail、directory cache 仍没有共享 generation marker。Desktop feedback 已能显示 warning，但还没有最终一致性修复机制。

## 6. 下一阶段长期任务

### G17.7 — Reconciliation queue（P1）

1. session-scoped bounded retry queue；
2. `STALE` / `BUSY` / `SCAN_FAILED` 分级 backoff；
3. root rescan 幂等与去重；
4. pending marker 与 crash/restart 恢复；
5. operation id 与 reconciliation task correlation；
6. 不把 warning 误升级为 filesystem failure。

### G17.8 — Cross-projection generation（P1）

1. 为 asset index、metadata、tags、favorites、thumbnail、directory cache 定义 generation marker；
2. 明确 filesystem mutation、metadata migration、index publish 顺序；
3. 增加 crash/interruption、重复消费、重扫幂等测试；
4. 定义 projection repair 的优先级和失败隔离。

### G18 — Schema/migration lifecycle（P2）

继续冻结真实历史 fixture、schema-object manifest、lazy-ensure compatibility deprecation，不与 Desktop reconciliation 混改。

### G19 — Process concurrency/performance evidence（P2）

补独立进程 SQLite lock/retry、真实目录扫描 benchmark、Windows/WSL reparse 矩阵和 diagnostics queue 容量测试。

## 7. 工作区一致性声明

- 未执行 `git reset`、`git checkout`、全量 `git clean`；
- 未 staging、未 commit；
- 未回滚或覆盖其他会话修改；
- 未触碰 `webui\**`、`tests\e2e\**`、`tmp\**`；
- 未接管 commerce/LAN 并行写域；
- 本轮主线写入集中在 Desktop file-list warning consumption、feedback translations、operation-filtered diagnostics 和对应测试。

## 8. 结论

G17.6 已把 warning/degraded contract 从 application service 推进到 Desktop file-list 的主要用户操作路径：

- paste；
- move/copy；
- trash/permanent delete；
- drag-drop；
- rename；
- batch rename；
- new folder；
- duplicate；
- Undo/Redo。

当前 Python 全量门禁为：

```text
2513 passed, 4 skipped, 1 warning
ruff 通过
pyright 通过
git diff --check 通过
```

下一步应进入 G17.7 reconciliation queue，而不是继续增加只显示 warning 数量的 UI 分支。真正的工程闭环需要让 degraded refresh 最终可重试、可恢复、可审计。
