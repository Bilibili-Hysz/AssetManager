# G17.17-E Worker Lease Renewal、Heartbeat 与硬截止 — 2026-08-08

**工作区：** `D:\~Vibe-Coding\Projects\AssetsManager_old-bak`  
**分支：** `master`  
**阶段状态：** E 核心实现与验证完成；不代表 G17.17-F cutover、rolling upgrade 或整个项目 release 完成。

## 1. 本切片目标

在 G17.17-D 的 `lease_token` CAS 基础上，完成 worker/supervisor 的长任务 lease renewal、heartbeat、stop/restart、stale completion 与 in-memory/SQLite 一致性适配，确保旧 worker 不能在 recovery 或新 ownership 后改写任务状态。

## 2. 已实现

涉及文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\reconciliation_queue.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\reconciliation_queue_store.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\asset_index_reconciliation_service.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\unit\test_reconciliation_queue.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\unit\test_reconciliation_queue_sqlite_store.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\unit\test_asset_index_reconciliation_service.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\unit\test_reconciliation_supervisor_conflicts.py`

### 2.1 Claim context 与完整 CAS

1. worker-owned mutation 显式携带 claim 时捕获的 `expected_attempts` 与 `lease_token`；
2. `succeeded`、`retryable`、`terminal`、`cancel`、`renew` 不再依据已刷新 snapshot 推断旧 worker ownership；
3. in-memory 与 SQLite 均要求：
   ```text
   state == running
   attempts == expected_attempts
   lease_token 匹配
   lease_expires_at > now
   ```
4. recovery 后旧 worker 的 `terminal/cancel` 不会把 retryable 或新 attempt 改成 terminal/cancelled；
5. 过期 token 的 renew/completion 在两个 backend 中均 fail-closed，并分类为 `stale_worker_completion`。

### 2.2 Heartbeat 与硬 operation-age

1. 新增 `renew_lease()` store/queue API；
2. 长任务期间 heartbeat 周期性续租；
3. 增加 `worker_max_operation_age` 配置，默认 300 秒；
4. 续租长度被截断到 operation deadline 的剩余预算，不允许最后一次 renew 把 lease 无限延长；
5. operation deadline 从 claim 成功返回后的实际 operation start 计算；
6. operation 在 deadline 后完成时只能 stale-no-op，不能提交 succeeded/retryable/terminal mutation；
7. heartbeat 启动失败会回退当前 claim 的 retry；
8. 正常路径先停止并等待 heartbeat 退出，再执行 completion mutation；
9. stop 仍保持 bounded shutdown contract：若底层 operation/SQLite I/O 不返回，worker 不伪装成已停止，调用方会收到 `ReconciliationWorkerStopTimeout`。

### 2.3 Completion 时间语义

操作失败、成功 publish、stale 判定均使用 operation 完成时的 fresh clock，不再复用 claim 前的旧 timestamp。

## 3. 新增/补强测试

覆盖：

- in-memory expired lease renew/completion；
- in-memory recovery 后旧 worker terminal/cancel；
- SQLite expired lease renew/completion；
- SQLite queue snapshot 已刷新为 retryable 后旧 worker mutation；
- 长任务 heartbeat renew；
- heartbeat 硬 operation-age deadline 后 recovery 与 stale completion；
- stop timeout、lease expiry 与旧 completion；
- worker heartbeat/worker stop 的异常路径。

## 4. 验证结果

截至 **2026-08-08**：

```text
G17.17-E 定向回归：54 passed
全量 Python 回归：2653 passed, 6 skipped, 1 warning
Ruff：通过（全量扫描出现若干 pytest 临时目录拒绝访问 warning，但无 lint error）
Pyright：0 errors, 0 warnings, 0 informations
compileall：通过
受影响 LAN/window 集成测试：2 passed
```

6 个 skip 均为 Windows 当前 symlink 权限不可用；1 个 warning 为测试主动构造重复 ZIP 条目。全量回归耗时约 4 分 36 秒。

## 5. 并行审查结论

### Goodall：G17.17-E lease/heartbeat 只读复审

- 未发现本轮 P0；
- claim attempts/token/expiry CAS 已闭环；
- completion fresh clock 已闭环；
- 第二轮指出的 hard deadline overshoot、claim-age 起点与 heartbeat cleanup 边界已在本阶段修正；
- 仍需在 F 或真实多进程测试中继续验证底层 SQLite 外部锁导致的极端 heartbeat in-flight 情况。

### Kepler：commerce schema 只读归属审查

发现独立 commerce 领域存在迁移版本链风险：当前工作树把 v18 的 `buyer_owner_type/buyer_owner_key` 字段与 checks 提前混入 v8 的共享 commerce DDL/contract，而真正增量添加字段的逻辑位于 v18。该问题属于其他并行领域，本阶段未修改：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\core\schema_defs.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\core\db_migrations.py`

本次全量回归与受影响 LAN/window 测试均通过，但这不等于该迁移版本语义风险已经解决；后续必须由 commerce 归属会话确认并按 v8/v18 历史 contract 拆分处理。

## 6. 当前工作区与边界

当前仍是共享脏工作区，未做 staging、commit、reset、checkout 或全量清理。最新盘点：

```text
tracked modified：186
untracked：460
staged：0
conflicts：0
```

其中大量未提交修改、commerce/LAN/WebUI 文件和 `tmp/.pytest-tmp` 测试产物来自并行会话或验证过程；本阶段未覆盖、未回滚其他领域。

## 7. 阶段结论

**G17.17-E 的 worker lease renewal 与 ownership safety 核心目标已完成并通过当前 Python 全量回归。**

项目整体仍不能宣称完成，原因包括：

1. commerce v8/v18 migration contract 尚未完成归属确认与历史版本修复；
2. G17.17-F cutover/rolling-upgrade hardening 尚未开始；
3. 真实多进程 managed SQLite heartbeat/claim/recovery/completion 矩阵仍需补齐；
4. WebUI/e2e、LAN、commerce 与其他并行领域尚未形成统一 release gate；
5. 共享工作区没有可提交的 clean boundary。

## 8. 下一步：G17.17-F

建议按以下顺序推进：

1. **F-1：真实多进程矩阵**——独立进程 claim、renew、recovery、completion、generation wakeup；
2. **F-2：rolling upgrade contract**——旧版本 writer 对 lease_token/新 schema 的 fail-closed 行为；
3. **F-3：cutover gate**——generation、schema version、queue marker 与 worker capability 的一致性检查；
4. **F-4：stop/restart fault injection**——外部 SQLite lock、connection close、heartbeat in-flight、worker restart；
5. **F-5：完成 F 专项回归后，再决定是否进入 release candidate 审查。**

当前不进行 release、staging 或 commit。
