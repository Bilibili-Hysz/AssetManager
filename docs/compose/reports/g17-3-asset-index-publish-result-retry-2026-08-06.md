# G17.3 Asset Index Publish Result / Bounded Busy Retry — 深度审查报告

**日期：** 2026-08-06  
**工作区：** `D:\~Vibe-Coding\Projects\AssetsManager_old-bak`  
**分支：** `master`  
**HEAD：** `fbf3403 Enforce schema object integrity for v6`  
**状态：** G17.3 的结果合同、bounded retry 和调用方适配已继续收口；仍有 P1 事务最终性与 degraded 可观测性风险，不能宣称整个工程完成。工作区保持多会话混合 dirty，未 staging、未 commit。

## 1. 本轮目标

在 G17/G17.1/G17.2 的 session binding、persistent revision/CAS 和严格 schema contract 基础上，继续收口 asset-index publish 的结果语义：

1. 区分 `published`、`empty`、`skipped`、`scan_failed`、`stale`、`busy`；
2. 将 SQLite `locked` / `busy` 的 retry policy 限定为有界、可测试的 application-service 行为；
3. 让 `FileOperationService` 优先使用结果 API，同时保留旧 integer API 兼容；
4. 不修改 `webui/**`、`tests/e2e/**`、`tmp/**`，不接管并行 commerce/LAN 写域。

## 2. 本轮变更

### 2.1 Publish result contract

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\asset_index_service.py`

新增：

```python
class AssetIndexPublishStatus(str, Enum):
    PUBLISHED = "published"
    EMPTY = "empty"
    SKIPPED = "skipped"
    SCAN_FAILED = "scan_failed"
    STALE = "stale"
    BUSY = "busy"
```

以及不可变的 `AssetIndexPublishResult`，包含：

- `status`、`count`；
- `revision`、`expected_revision`、`actual_revision`；
- `retry_count`；
- 供诊断使用的 `failure`。

新增 API：

- `index_directory_result(...)`；
- `index_directory_tree_result(...)`。

完整 tree publish 继续以一个 root-level CAS 写入为边界，并清除已经消失的 descendant rows。

### 2.2 Bounded busy retry

当前 policy：

- 最多重试 2 次；
- 延迟为 `0.01s`、`0.02s`；
- 只对 SQLite `OperationalError` 消息中包含 `locked` 或 `busy` 的情况重试；
- 保留原始 expected revision，不在 retry 中盲目重新读取 revision；
- 预检读取 `count_by_parent()` / `current_revision()` 与 publish 阶段统一进入 bounded retry；
- 超出上限返回 `BUSY` result；旧 integer wrapper 继续抛出 busy exception，避免静默返回伪成功。

### 2.3 Compatibility 与 public API

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\file_operation_service.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\__init__.py`

`FileOperationService` 已优先探测并调用 result API，旧 service double 或旧实现仍回退到 integer API。legacy wrapper 现在按 `status` 处理没有附带 `failure` 的 `STALE` / `BUSY` result，不再依赖异常对象是否恰好存在。

`AssetIndexPublishResult` 与 `AssetIndexPublishStatus` 已从 `AssetsManager.application` 公开导出，并增加 public import 回归测试。

## 3. 测试补充

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_asset_index_service.py`

新增/补强覆盖：

1. 单目录 `EMPTY` / `PUBLISHED` / `SKIPPED` / `SCAN_FAILED`；
2. 单目录 `STALE` 与 bounded publish busy retry；
3. 单目录 preflight `count_by_parent` / `current_revision` busy retry；
4. tree `EMPTY` / `PUBLISHED` / `SCAN_FAILED` / `STALE` / preflight `BUSY`；
5. legacy wrapper 在 `failure=None` 的 stale result 下仍抛出冲突；
6. application package 的 public import contract；
7. 既有 session binding、双 connection CAS、tree rollback、filesystem rename best-effort 行为。

## 4. 验证结果

### 4.1 G17 相关定向回归

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
377 passed, 2 skipped
```

跳过项仍是 Windows 当前进程没有创建 symlink 的权限（`WinError 1314`），不是业务断言失败。

### 4.2 全量 Python 回归

执行：

```text
pytest -q
```

结果：

```text
2497 passed, 4 skipped, 1 failed, 1 warning
```

唯一失败仍来自保护域 WebUI 架构合同：

```text
tests/unit/test_architecture_boundaries.py::test_browser_auth_contract_has_no_bearer_token_state
```

触发文件：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\types\api.ts
```

其中仍存在：

```text
delivery_token: string;
delivery_url: string;
```

本轮没有修改 `webui\**`，也没有放宽该架构断言。4 个 skip 仍为平台 symlink 能力限制；1 个 warning 是测试故意写入重复 ZIP member 时的 `zipfile` 警告。

### 4.3 静态门禁

```text
ruff check AssetsManager tests     通过
pyright                             0 errors, 0 warnings, 0 informations
git diff --check -- AssetsManager tests 通过
```

## 5. 深度审查结论与剩余风险

### P1：result status 仍不能证明 durable commit

`AssetIndexPublishResult` 目前按 `expected_revision + 1` 推导返回 revision。若调用者传入 `commit=False`，或调用时已经存在 outer transaction，repository 可能只完成 staged write，随后 caller rollback；此时 result 仍可能是 `PUBLISHED`，但数据库 revision/rows 最终回到旧状态。

下一阶段必须明确以下二选一合同：

1. 增加 `committed` / `STAGED` 语义，明确 result 只代表 staged 或 durable；或；
2. canonical result API 禁止在 caller outer transaction / `commit=False` 下宣称 `PUBLISHED`。

在该合同完成前，不把 result 当作跨 projection event 的 durable commit receipt。

### P1：FileOperationService 对 degraded refresh 仍静默继续

`SCAN_FAILED`、`STALE`、`BUSY` 当前会被 `_refresh_parents()` / `_refresh_directory_tree()` best-effort continue/return。这样可以避免 filesystem 已完成后被新 writer conflict 反向报告失败，但也可能让索引长期停留在旧状态，且没有：

- bounded follow-up retry；
- reconciliation queue；
- error/event/telemetry；
- 对 `FileOperationResult.errors` 的诊断投影。

下一阶段应至少区分：

- `STALE`：重新排队 root scan；
- `BUSY`：延迟重试；
- `SCAN_FAILED`：保留失败路径和 OSError 原因。

### P2：scan failure 诊断信息不足

扫描层当前将 `OSError` 压缩为 `None`，result 只给 `SCAN_FAILED`，没有失败路径、错误码或稳定 error code。`failure` 直接携带内部异常对象也不适合作为长期 API 序列化合同。

### P2：`count` 语义仍需进一步统一

当前不同状态下的 `count` 可能表示：

- 本次扫描发现条目数；
- `SKIPPED` 时已有索引条目数；
- tree stale/busy 时已扫描 snapshot 条目数。

下一阶段应拆分 `scanned_count`、`published_count`、`existing_count`，或把 `count` 明确定义为“本次实际写入条目数”。

### P2：真实独立进程 busy-lock 尚未覆盖

当前 retry 测试主要通过注入 `OperationalError` 验证 policy；双 connection 测试验证 stale CAS，但尚未覆盖真正独立进程的 SQLite lock、busy timeout、进程退出后的 rollback 与重试窗口。

### P2：跨 projection generation 尚未统一

asset-index revision 只保护自身 replacement/delete。metadata、tags、favorites、thumbnail projection 尚未共享同一 generation/reconciliation contract；filesystem + 多 projection 仍不是跨系统原子事务。

### P2：canonical result API 仍缺少 bound-session 最终性矩阵

目前 raw compatibility 形式和 FileOperationService 调用方已有较多覆盖，但还应补：

- canonical `AssetIndexService.for_session(session)` 的 result API；
- outer transaction / `commit=False`；
- stale/busy status 与 `failure=None` 不变量；
- tree result 的完整 session binding matrix。

## 6. 长期任务路线

### G17.4 — transaction finality / degraded observability（P1）

1. 冻结 `AssetIndexPublishResult` 的 durable/staged 语义，加入 outer transaction 回归；
2. 将 result 作为 event/reconciliation 的输入，而不是只返回整数；
3. FileOperationService 对 `STALE` / `BUSY` / `SCAN_FAILED` 增加 bounded follow-up、telemetry 和可诊断错误；
4. 把 scan failure 统一为稳定 error code + failed path，不直接暴露内部 exception object；
5. 补 canonical session、commit=False、tree result 的完整测试矩阵。

### G17.5 — cross-projection generation（P1）

1. 为 asset index、metadata、tags、favorites、thumbnail 定义 generation/reconciliation marker；
2. 明确 filesystem mutation 后 projections 的提交顺序和恢复策略；
3. 增加 crash/interruption、重复消费、重扫幂等性测试；
4. 不在没有合同前把多个 projection 粗暴合并进一个 SQLite transaction。

### G18 — migration/schema history hardening（P2）

1. 冻结更多真实历史 fixture；
2. 完成 schema-object manifest 的唯一 owner；
3. 收口 repository lazy-ensure compatibility API 的 deprecation；
4. 为 migration 失败提供可审计的 recovery report。

### G19 — concurrency/performance evidence（P2）

1. 独立进程 SQLite lock/retry 回归；
2. 真实目录扫描 benchmark 与 publish latency budget；
3. 确认 lock map 生命周期与 session close 后资源回收；
4. 在 Windows/WSL 矩阵中分别记录 symlink/reparse 行为。

### 当前 P0 外部阻塞

由保护域 WebUI 会话处理：

```text
tests/unit/test_architecture_boundaries.py::test_browser_auth_contract_has_no_bearer_token_state
```

主线不修改 `webui\**`，也不删除断言。只有 WebUI 所属会话完成 `delivery_token` / `delivery_url` 与浏览器认证合同迁移后，全量回归才可能清零。

## 7. 工作区一致性声明

- 未执行 `git reset`、`git checkout`、全量 `git clean`；
- 未 staging、未 commit；
- 未回滚或覆盖并行会话修改；
- 未触碰 `webui\**`、`tests\e2e\**`、`tmp\**`；
- 本轮主线写入集中在 asset-index result/retry 适配、application public export 与对应集成测试；
- commerce/LAN 并行工作线保持独立，不纳入本轮修复范围。

## 8. 结论

G17.3 已从“只返回整数并在 publish 阶段有限 retry”推进到：

- 单目录与完整 tree 均有显式 publish result；
- preflight read 与 publish 均有 bounded busy retry；
- stale/busy 不再因为 legacy wrapper 缺少异常对象而伪成功返回；
- result contract 可从 `AssetsManager.application` 公开导入；
- 377 项 G17 相关回归、ruff、Pyright、diff check 均通过。

但当前工程仍不是完成态：全量 Python 回归仍有 1 个保护域 WebUI 架构失败，asset-index durable commit 语义和 degraded reconciliation 仍是下一阶段 P1。报告不执行 staging/commit，不回滚、不删除任何其他会话产物。
