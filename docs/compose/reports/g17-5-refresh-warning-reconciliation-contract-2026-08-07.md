# G17.5 Refresh Warning / Reconciliation Contract — 深度审查报告

**日期：** 2026-08-07  
**工作区：** `D:\~Vibe-Coding\Projects\AssetsManager_old-bak`  
**分支：** `master`  
**HEAD：** `fbf3403 Enforce schema object integrity for v6`  
**状态：** G17.5 已建立兼容的 refresh warning、degraded result 和跨线程 diagnostics contract；Desktop file-list 调用方尚未消费 warning，长期 reconciliation queue 仍待下一阶段处理。工作区保持多会话混合 dirty，未 staging、未 commit。

## 1. 本轮目标

G17.4 已增加 `file.index_refresh` opt-in telemetry，但仍存在两个实际问题：

1. 批量 filesystem 操作的 result 没有结构化 warnings；
2. Path-returning 命令的 `last_refresh_warnings` 只存在于当前线程，后台 worker 完成后 UI 线程无法可靠读取。

本轮目标是在不改变既有 Path 返回合同、不把 warning 错误地升级为 filesystem failure 的前提下，建立最小安全的 warning/diagnostics contract。

## 2. 已完成实现

### 2.1 FileOperationWarning

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\file_operation_service.py`

新增不可变结构：

```python
@dataclass(frozen=True, slots=True)
class FileOperationWarning:
    code: str
    phase: str
    path: str
    status: str
    retry_count: int
    failure_type: str | None
    operation_id: str
```

当前 refresh warning code 采用稳定前缀：

```text
asset_index_refresh_stale
asset_index_refresh_busy
asset_index_refresh_scan_failed
asset_index_refresh_staged
```

warning 不携带原始 exception 实例，只保留 failure type，避免把不可序列化的内部异常对象暴露给上层合同。

### 2.2 FileOperationResult warnings/degraded

`FileOperationResult` 保持原有前两个位置参数：

```python
FileOperationResult(changed_paths, errors)
```

新增尾部字段：

```python
warnings: tuple[FileOperationWarning, ...] = ()
```

语义固定为：

- `changed_paths`：已经完成 filesystem mutation 的路径；
- `errors`：filesystem operation 本身失败的错误；
- `warnings`：filesystem mutation 成功，但 projection/index refresh 非致命 degraded；
- `ok`：只由 `errors` 决定，warning 不会把文件操作错误地判为失败；
- `degraded`：`warnings` 非空。

已接入：

- `copy_to_directory()`；
- `move_to_directory()`；
- `delete_permanent()`；
- `delete_to_trash()`。

### 2.3 Path-returning 命令保持兼容

以下命令仍然返回 `Path`，没有改成 union result：

- `move()` / rename；
- `duplicate()`；
- `restore_backup()`。

新增 session-service 实例级、线程安全 diagnostics queue：

```python
service.drain_refresh_diagnostics()
```

并保留同线程便利 API：

```python
service.last_refresh_warnings
service.last_operation_id
```

`drain_refresh_diagnostics()` 返回带 `operation_id` 的完整 warning 集合，因此后台 worker 与 UI callback 不再依赖同一个 `threading.local()` 才能传递诊断。

### 2.4 staged/non-durable 明确标记

如果 `AssetIndexPublishResult` 是：

```text
status=PUBLISHED
committed=False
```

FileOperationService 会将其转换为：

```text
code=asset_index_refresh_staged
status=staged
```

避免把“尚未 durable commit”的 staged publish 伪装成普通 `published` refresh。

### 2.5 Performance telemetry correlation

既有事件继续保留：

```text
file.index_refresh
```

现在增加：

- `operation_id`；
- stable warning code 对应的 status；
- retry count；
- failure type。

`file.command` 也携带同一 operation id，并在 result 有 warnings 时将 outcome 标记为 `degraded`。

### 2.6 Application public export

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\__init__.py`

公开导出：

- `FileOperationResult`；
- `FileOperationWarning`；
- `FileOperationService`。

## 3. 测试补充

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_file_operation_service.py`

新增/补强覆盖：

1. copy + busy refresh：result 保持 `ok=True`，同时 `degraded=True`；
2. warning code、phase、path、retry count、failure type；
3. staged/non-durable publish 被标记为 `asset_index_refresh_staged`；
4. rename + stale warning；
5. Path-returning command 在 worker thread 执行后，主线程通过 `drain_refresh_diagnostics()` 获取 warning；
6. operation id 与 warning correlation；
7. drain 后队列清空，下一次 clean command 不继承旧 warning；
8. 既有 copy/move/delete/restore/duplicate/Undo 兼容测试继续通过。

## 4. 验证结果

### 4.1 G17.5 定向回归

执行：

```text
pytest -q \
  tests/core/test_db_migrations.py \
  tests/integration/test_asset_index_repository_session_binding.py \
  tests/integration/test_asset_index_service.py \
  tests/integration/test_search_service.py \
  tests/integration/test_file_operation_service.py \
  tests/lan/test_lan_api.py --tb=short
```

结果：

```text
384 passed, 2 skipped
```

### 4.2 全量 Python 回归

执行：

```text
pytest -q
```

结果：

```text
2511 passed, 4 skipped, 1 warning
```

4 个 skip 仍是 Windows symlink/reparse 权限限制；1 个 warning 是测试故意写入重复 ZIP member 时的 `zipfile` warning。

### 4.3 静态门禁

```text
ruff check AssetsManager tests       通过
pyright                               0 errors, 0 warnings, 0 informations
git diff --check -- AssetsManager tests 通过
```

## 5. 当前剩余风险

### P1：Desktop file-list 调用方尚未消费 warnings

主要调用方仍只使用：

- `changed_paths`；
- `errors`；
- `ok`。

涉及保护/高耦合范围：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\panels\file_list\_actions.py`；
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\panels\file_list\_base.py`。

本轮没有直接改动该写域。当前合同已经能保存 warning，但 UI 还不会向用户显示 degraded refresh，也不会主动加入 reconciliation queue。

必须保持的语义是：

```text
ok=False, errors 非空
    => filesystem 操作失败/部分失败

ok=True, degraded=True
    => filesystem 操作成功，但 projection refresh 需要提示/重试
```

不能因为 warning 非空就跳过 Undo 记录或把成功的 filesystem mutation 判为失败。

### P1：尚无 session-scoped reconciliation queue

当前 `drain_refresh_diagnostics()` 是 bounded in-memory diagnostics channel，不是持久化队列：

- 进程退出后丢失；
- 没有自动 retry；
- 没有 crash recovery；
- 没有跨 projection generation marker。

它解决的是“warning 不丢失”，还没有解决“warning 必须最终被修复”。

### P2：legacy fallback 的整数返回仍无法完整表达 scan failure

旧 integer API 返回 `0` 时仍不能可靠区分：

- 合法空目录；
- scan failure；
- skipped。

异常形式的 stale/busy 已有兼容处理；整数 degraded 的最终 deprecation 仍需后续安排。

### P2：warning 仍未持久化

当前 warning 只存在于：

- `FileOperationResult.warnings`；
- service diagnostics queue；
- opt-in performance recorder。

尚未写入数据库或 session recovery store。

### P2：独立进程 lock contention 尚未覆盖

已有双 connection CAS、bounded busy retry 和 transaction finality 测试，但仍缺真正独立进程的 SQLite lock、busy timeout、进程崩溃恢复与 retry window。

## 6. 下一阶段长期任务

### G17.6 — Desktop caller adoption（P1）

在明确不改变 Undo 成功语义的前提下：

1. file-list copy/move/delete/drag-drop 聚合 `warnings`；
2. warning 进入现有 feedback/toast 或状态栏，而不是被当成 error；
3. Path-returning duplicate/restore/rename 使用 `drain_refresh_diagnostics()` 做 operation correlation；
4. 为 Desktop caller 增加 degraded UI 回归，不触碰 WebUI；
5. 继续保持 panel 写域的最小范围和跨模块复审。

### G17.7 — Reconciliation queue（P1）

1. session-scoped bounded retry queue；
2. stale/busy/scan_failed 分级 backoff；
3. root rescan 幂等与 deduplication；
4. crash/restart 后可恢复的 pending marker；
5. 与 asset-index generation、metadata/tags/favorites/thumbnail projection 对齐。

### G18 — schema/migration lifecycle（P2）

继续冻结真实历史 fixture、schema-object manifest、lazy-ensure compatibility deprecation，不与 Desktop warning 消费混改。

### G19 — process concurrency/performance evidence（P2）

补独立进程 SQLite lock/retry、真实目录扫描 benchmark、Windows/WSL reparse 矩阵，并评估 diagnostics queue 的容量与回收策略。

## 7. 工作区一致性声明

- 未执行 `git reset`、`git checkout`、全量 `git clean`；
- 未 staging、未 commit；
- 未回滚或覆盖其他会话修改；
- 未触碰 `webui\**`、`tests\e2e\**`、`tmp\**`；
- 未接管 commerce/LAN 并行写域；
- 本轮主线写入集中在 `FileOperationWarning`、`FileOperationResult.warnings/degraded`、跨线程 diagnostics queue、operation correlation 与对应测试。

## 8. 结论

G17.5 已把 refresh degraded 从“仅 opt-in telemetry”推进到可由业务调用方读取的结构化合同：

- batch commands 通过 `FileOperationResult.warnings` 返回；
- Path commands 保持 `Path` 兼容，同时通过 operation-correlated diagnostics queue 暴露 refresh warning；
- staged/non-durable publish 有明确 `staged` warning code；
- warning 不影响 `ok` 与 Undo 成功语义；
- worker/UI 跨线程场景已有回归验证。

当前 Python 全量门禁为：

```text
2511 passed, 4 skipped, 1 warning
ruff 通过
pyright 通过
git diff --check 通过
```

这仍不是整个产品完成声明。下一步应在高耦合 Desktop file-list 写域中消费 warnings，并建立真正可恢复的 reconciliation queue。
