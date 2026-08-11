# G17.4 Transaction Finality / Degraded Observability — 深度审查报告

**日期：** 2026-08-06  
**工作区：** `D:\~Vibe-Coding\Projects\AssetsManager_old-bak`  
**分支：** `master`  
**HEAD：** `fbf3403 Enforce schema object integrity for v6`  
**状态：** G17.4 的第一轮事务最终性和 degraded refresh 可观测性已完成；跨 projection reconciliation、独立进程锁竞争和稳定错误码仍是后续任务。工作区保持多会话混合 dirty，未 staging、未 commit。

## 1. 本轮目标

G17.3 已建立 `AssetIndexPublishResult`，但深度审查发现：

1. `commit=False` / outer transaction 下，result 需要明确 staged 与 durable 的区别；
2. raw compatibility repository 不得提交调用方已经开启的 outer transaction；
3. FileOperationService 不能完全静默吞掉 `STALE` / `BUSY` / `SCAN_FAILED` refresh；
4. 必须用独立 connection 验证 `committed=True` 的 result 真正可见。

本轮仍不触碰：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\**`；
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\e2e\**`；
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tmp\**`；
- 并行 commerce/LAN 写域。

## 2. 已完成实现

### 2.1 Result 明确 committed / durable 语义

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\asset_index_service.py`

`AssetIndexPublishResult` 新增：

```python
committed: bool | None
```

并新增：

```python
result.durable
```

语义固定为：

- `committed=True`：本次调用已完成最终 commit；
- `committed=False`：写入只在当前 transaction 内成立，属于 staged result；
- `committed=None`：没有成功 publish，或由 compatibility double 构造的未知结果；
- `durable=True`：仅当 result 为 `PUBLISHED` / `EMPTY` 且 `committed=True`。

`degraded` 现在也会识别“逻辑 publish 成功但尚未 durable commit”的 result，避免调用方把 staged write 当成可靠完成。

### 2.2 修复 raw outer transaction 提前提交

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\repositories\asset_index_repository.py`

原问题：

```python
should_commit = commit and (self._session is None or not outer_transaction)
```

由于 raw compatibility repository 的 `self._session is None`，已有 outer transaction 时仍会 commit，从而可能连同 caller 的无关写入一起提交。

现在统一为：

```python
should_commit = commit and not outer_transaction
```

规则固定为：

- 本次调用自己创建 transaction 时，`commit=True` 才由本次调用提交；
- 调用开始前已经存在 outer transaction 时，始终由 caller 负责最终 commit/rollback；
- canonical session 与 raw compatibility path 采用相同 transaction ownership 规则。

### 2.3 FileOperationService degraded refresh telemetry

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\file_operation_service.py`

新增 opt-in performance event：

```text
file.index_refresh
```

事件记录：

- refresh phase：`parent` / `tree`；
- result status：`stale` / `busy` / `scan_failed` 等；
- retry count；
- failure type，而不是直接写入内部 exception object。

legacy fallback 若直接抛出 `AssetIndexRevisionConflict` 或 SQLite `OperationalError`，现在也会被记录为对应 degraded refresh，同时继续保持“filesystem mutation 不因新 writer conflict 反向失败”的兼容策略。

本轮没有把 degraded refresh 粗暴改成 filesystem operation failure；这保留了已有文件操作语义，但使问题在启用 `PerformanceRecorder` 时可观测。

## 3. 测试补充

新增覆盖：

### AssetIndexService

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_asset_index_service.py`

覆盖：

1. `commit=False` 返回 `committed=False` / `durable=False`；
2. rollback 后 rows 与 revision 同时回到旧状态；
3. canonical session 的 outer transaction 返回 staged result；
4. clean publish 的 `committed=True` / `durable=True`；
5. committed result 在第二个 SQLite connection 上可见；
6. tree publish 在 outer transaction 下的 staged 语义；
7. degraded result 继续保留既有 status/failure contract。

### AssetIndexRepository

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_asset_index_repository_session_binding.py`

新增 raw compatibility regression：

1. caller 先 `BEGIN` 并写入 `caller_data`；
2. raw repository 使用 `commit=True` 写 asset index；
3. repository 不得结束 caller transaction；
4. caller rollback 后，caller data、assets、revision 全部回滚。

### FileOperationService

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_file_operation_service.py`

新增 `file.index_refresh` telemetry 回归，验证 busy refresh 被记录为：

```text
phase=parent
status=busy
retry_count=2
failure_type=OperationalError
```

## 4. 验证结果

### 4.1 G17.4 定向回归

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
382 passed, 2 skipped
```

### 4.2 全量 Python 回归

执行：

```text
pytest -q
```

当前工作区快照结果：

```text
2509 passed, 4 skipped, 1 warning
```

当前没有 Python 测试失败。4 个 skip 仍是 Windows symlink/reparse 权限限制；1 个 warning 是测试故意写入重复 ZIP member 时的 `zipfile` warning。

`webui\**` 在本轮保持只读；全量测试期间该保护域由其他并行会话继续迁移，主线没有修改或回滚其文件。

### 4.3 静态门禁

```text
ruff check AssetsManager tests       通过
pyright                               0 errors, 0 warnings, 0 informations
git diff --check -- AssetsManager tests 通过
```

## 5. 当前剩余风险

### P1：degraded 仍是 opt-in telemetry，不是统一 reconciliation contract

当前 `file.index_refresh` 只有在配置 `PerformanceRecorder(enabled=True)` 时才保留；没有 recorder 的调用方仍只能得到 filesystem success，无法直接取得结构化 refresh warning。

下一步需要决定：

1. 是否向 `FileOperationResult` 增加 warnings/degraded projection；
2. Path-returning file commands 如何返回 refresh warning；
3. 是否引入 session-scoped reconciliation queue；
4. `STALE`、`BUSY`、`SCAN_FAILED` 各自的 retry/backoff/人工处理策略。

### P1：filesystem 与多 projection 仍不是一个跨系统原子命令

当前 transaction finality 只收口 asset-index 自身。metadata、tags、favorites、thumbnail、directory cache 等 projection 仍没有共同 generation marker；filesystem mutation 已完成而 projection refresh 失败时，仍依赖后续 reconciliation。

### P2：稳定错误码与失败路径尚未完成

Telemetry 目前记录 status、retry count 和 exception type，但没有：

- 稳定 error code；
- failed path；
- sharing violation / permission denied / missing directory 等细分原因；
- 可持久化的 refresh failure record。

### P2：独立进程 lock contention 尚未覆盖

当前已有：

- 双 connection stale CAS；
- 注入式 busy retry；
- raw/canonical outer transaction；
- 独立 connection durable visibility。

仍缺真正独立进程的 SQLite lock、busy timeout、进程崩溃恢复和重试窗口矩阵。

### P2：global refresh lock 生命周期

`_REFRESH_LOCKS` 按 root identity 全局缓存，目前没有在 session close 后回收 lock entry。长期运行、频繁打开大量 library root 时存在轻度内存生命周期风险，后续应改为 runtime/session-owned lock registry 或 weak reference 策略。

## 6. 下一阶段长期任务

### G17.5 — refresh warning / reconciliation contract（P1）

1. 定义 `FileOperationResult` warnings/degraded 兼容字段；
2. 为 Path-returning commands 提供可读取的 session-scoped refresh diagnostics；
3. 定义 stale/busy/scan-failed retry 策略和幂等 root rescan；
4. 将 telemetry 与 reconciliation queue 统一 correlation id；
5. 为 refresh failure 加入稳定 error code 和 failed path。

### G17.6 — cross-projection generation（P1）

1. 为 asset-index、metadata、tags、favorites、thumbnail、directory cache 定义 generation marker；
2. 明确 filesystem mutation、metadata migration、index publish 的提交顺序；
3. 增加 crash/interruption、重复消费、重扫幂等性测试；
4. 不在没有合同前把所有 projection 粗暴合并到一个 SQLite transaction。

### G18 — schema/migration lifecycle（P2）

继续冻结真实历史 fixture、schema-object manifest 和 lazy-ensure compatibility deprecation，不与 projection reconciliation 混改。

### G19 — process concurrency/performance evidence（P2）

补独立进程 SQLite lock/retry、真实目录扫描 benchmark、Windows/WSL reparse matrix，并评估 global refresh lock 的资源回收。

## 7. 工作区一致性声明

- 未执行 `git reset`、`git checkout`、全量 `git clean`；
- 未 staging、未 commit；
- 未回滚或覆盖其他会话改动；
- 未触碰 `webui\**`、`tests\e2e\**`、`tmp\**`；
- 未接管 commerce/LAN 并行写域；
- 本轮主线写入集中在 asset-index transaction finality、repository transaction ownership、FileOperationService telemetry 与对应测试。

## 8. 结论

G17.4 已解决一个真实 P1 数据安全问题：raw compatibility repository 不再提交 caller 已经开启的 outer transaction；同时 result API 现在能明确区分 durable commit 与 staged write，并用独立 connection 做了可见性验证。

G17.4 还为 degraded index refresh 建立了最低限度的 opt-in telemetry，避免 stale/busy/scan failure 完全不可见。

当前工程验证状态为：

```text
2509 passed, 4 skipped, 1 warning
ruff 通过
pyright 通过
git diff --check 通过
```

这表示当前 Python 主线门禁已通过，但不等同于跨 projection 数据一致性或发布完成。下一主线应进入 G17.5 refresh warning/reconciliation contract。
