# G17 Stop-the-World Cutover Release / Ownership Checklist

**日期：** 2026-08-08  
**工作区：** `D:\~Vibe-Coding\Projects\AssetsManager_old-bak`  
**分支：** `master`  
**HEAD：** `fbf3403`  
**状态：** G17.17-F 阶段证据已完成；本清单不构成整个 AssetsManager 的 release approval。

> 本文件是可审计的切换/归属清单，不是新的 G17.17-F 实施计划。
> 当前明确采用 **stop-the-world cutover**：同一 library 同一时刻只允许一个 canonical application owner。
> **不支持旧版/新版应用同时持有同一 library 的 rolling upgrade。**

## 1. 决策边界

| 项目 | 当前决策 |
|---|---|
| Library ownership | 单 library、单 application owner |
| Cutover 模式 | stop-the-world |
| Rolling upgrade | 不支持；不得以本清单推导支持 |
| Marker migration | 在 canonical owner 的 bootstrap 内执行；当前不是独立 multi-process marker merge 合同 |
| Schema migration | 由 managed database connection 执行，属于 schema/migration 责任域 |
| Reconciliation queue | SQLite durable store + generation/lease token CAS |
| 本清单权限 | 只记录证据、owner 与阻断项；不自动授权 staging/commit |
| 当前 release 判定 | 仅可进入 G17 阶段审查；不能宣称整个项目 ready |

## 2. Cutover 前置条件

### 2.1 Owner 与工作区

- [x] 已识别当前 branch/HEAD 与 dirty workspace。
- [x] 已确认 `webui/**`、`tests/e2e/**`、Commerce/schema、LAN 等并行写域不由 G17 会话接管。
- [ ] Release owner、reviewer、evidence owner 已由主线/项目负责人填写。
- [ ] 要进入 release candidate 审查前，已确认并行工作区的 clean boundary；不得默认把全部 dirty 文件纳入同一次提交。
- [x] 本会话未执行 reset、checkout、全量 clean、staging 或 commit。

### 2.2 Library lock 与连接顺序

- [x] canonical library owner 先获取 `LibraryLock`，再建立 database connection。
- [x] lock 获取失败时 fail-closed，不创建后续 runtime owner。
- [x] lock release 返回失败时不得伪装为成功。
- [x] 顺序证据：
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\library_service.py`
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\core\library_lock.py`
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_reconciliation_cutover_lock_order.py`

### 2.3 版本与 marker 边界

- [x] schema migration 在 database open 阶段完成。
- [x] marker migration 在 runtime assembly 阶段、worker 启动之前完成。
- [x] SQLite durable publish 成功后才 retire/archive JSON marker。
- [x] marker archive rename 失败时保留原 marker，并携带可重试状态。
- [x] 不兼容 schema、marker conflict 或 archive conflict 必须中止 cutover。
- [ ] Commerce/schema v22 existing-table/incompatible-schema 正式回归已由 schema owner 纳入交付。
- [ ] v8/v18/v22 migration ownership note 已由 Commerce/schema owner 确认。

证据来源：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\core\database.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\core\db_migrations.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\reconciliation_queue_migration.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\bootstrap.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_reconciliation_runtime_cutover.py`

## 3. 旧 owner 停止与 drain

在新 owner 启动前，必须按以下顺序完成旧 owner 停止：

1. 停止新的 filesystem/reconciliation admission；
2. 标记 runtime closing；
3. 设置 worker stop signal 并唤醒 queue；
4. 等待 worker join；
5. 等待 heartbeat/current operation 收尾；
6. 若 worker 仍存活，报告 `ReconciliationWorkerStopTimeout`，不得假装完成；
7. 完成 runtime cleanup；
8. 关闭 database connection；
9. 释放 `LibraryLock`；
10. 只有确认上述步骤完成后，才允许新 owner 获取同一 library。

验收项：

- [x] stop 有 bounded timeout。
- [x] stop timeout 后保留真实 worker/runtime 状态，可重试 cleanup。
- [x] heartbeat stop 与 worker stop 都能抑制迟到 renew。
- [x] heartbeat join 在 operation completion mutation 之前完成。
- [x] session/database/lock cleanup 失败不被静默吞掉。

证据：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\asset_index_reconciliation_service.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\runtime.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\library_service.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_reconciliation_runtime_lifecycle.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_reconciliation_queue_heartbeat_inflight.py`

## 4. 新 owner 启动顺序

新 owner 必须遵循：

1. 获取 `LibraryLock`；
2. 建立并登记 managed database connection；
3. 执行 schema preflight/migration；
4. 建立 SQLite reconciliation store；
5. 执行 JSON marker → SQLite migration；
6. 确认 marker archive/retirement 结果；
7. 构造 SQLite-backed queue 与 reconciliation service；
8. 启动 worker；
9. 执行 cutover 后 regression checks；
10. 对外发布“owner ready”状态。

验收项：

- [x] worker 不会在 marker migration 返回前启动。
- [x] queue 使用 SQLite durable store。
- [x] queue generation refresh 具有单调性保护。
- [x] claim、renew、recovery、completion 使用 task/attempt/lease token CAS。
- [x] 新 owner 可以从 expired lease recovery 后重新 claim 并完成任务。
- [x] 已新增 library-owner 级 handoff 测试，串联旧 owner stop/cleanup、DB release、LibraryLock release、新 owner open/runtime start。

## 5. Lease / worker ownership gate

- [x] claim 生成新的 lease token。
- [x] lease renew 只能由当前 attempt/token 延长。
- [x] renew 长度受 hard operation deadline 限制。
- [x] expired/missing-token running task 可以 recovery。
- [x] stale worker completion 只能 fail-closed/no-op，不得覆盖新 owner。
- [x] retryable、terminal、cancel、succeeded mutation 具有 CAS 边界。
- [x] heartbeat in-flight、external SQLite lock、closed connection 均有故障注入覆盖。
- [x] 旧 worker 进程终止后，新 subprocess 能 recovery/reclaim/complete。

核心证据：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_reconciliation_queue_process_matrix.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_reconciliation_queue_fault_injection.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_reconciliation_queue_external_lock.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_reconciliation_queue_heartbeat_inflight.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_reconciliation_queue_process_termination_subprocess.py`

## 6. 故障注入与恢复门禁

| 场景 | 当前状态 | 证据 |
|---|---|---|
| connection close 后 renew | 已通过 | `test_reconciliation_queue_fault_injection.py` |
| connection close 后 completion | 已通过 | `test_reconciliation_queue_fault_injection.py` |
| 外部 SQLite write lock | 已通过 | `test_reconciliation_queue_external_lock.py` |
| heartbeat in-flight | 已通过 | `test_reconciliation_queue_heartbeat_inflight.py` |
| Windows spawn claim/renew matrix | 已通过 | `test_reconciliation_queue_process_matrix.py` |
| abrupt process termination | 新 subprocess 测试 10/10 通过 | `test_reconciliation_queue_process_termination_subprocess.py` |
| 历史 multiprocessing Queue draft | 明确 skip | `test_reconciliation_queue_process_termination.py` |
| library-owner 级完整交接时间线 | 未建立 | 后续增强任务 |

## 7. Cutover 后回归门禁

### 7.1 当前已通过

```text
reconciliation/core migration 定向组合：86 passed, 1 skipped
restore/lifecycle 专项：144 passed, 1 skipped, 1 warning
LAN lifecycle 当前组合：41 passed
subprocess termination 重复验证：10/10 passed
全量 Python：2686 passed, 7 skipped, 1 warning
Ruff：通过
Pyright：0 errors, 0 warnings, 0 informations
Compileall：通过
```

### 7.2 当前仍未纳入 G17 release approval

- WebUI browser E2E 尚未形成可靠 CI lane；
- Commerce/schema v22 正式 existing/incompatible migration 回归及 ownership note 尚未由对应 owner 确认；
- LAN 当前测试通过，但 Windows CI 尚未明确纳入 `test_window_lifecycle_lan_failure.py`；
- 当前 workspace 仍是多会话 dirty mixed state；
- 当前清单未取得 release owner / reviewer / evidence owner sign-off。

## 8. Abort / no-go 条件

以下任一条件出现时，必须中止 cutover 或拒绝进入 release candidate 审查：

- 旧 owner 未完成 worker/heartbeat drain；
- 旧 database connection 或 `LibraryLock` 仍被持有；
- schema preflight/migration 失败或 schema contract 不兼容；
- marker 与 durable queue 不等价且无法明确归并；
- marker archive 已存在不同内容；
- queue generation regression 或 lease token CAS 失败；
- 新 owner 无法完成 recovery/reclaim/completion 验证；
- 发现旧 worker 仍可覆盖新 owner；
- 任何 rollback/quarantine/lock release secondary failure 没有可追踪记录；
- 需要依赖旧版/新版应用同时写同一 library 才能完成部署；
- 需要借 staging/commit 或清理其他并行会话文件来“通过”门禁。

## 9. Ownership / sign-off

| 领域 | Owner | 当前状态 | 本清单动作 |
|---|---|---|---|
| G17 reconciliation / queue / runtime | 主线 G17 会话 | 阶段验证完成 | 维护本清单与测试证据 |
| Schema / Commerce migrations | schema/commerce 会话 | v22 正式回归待归属确认 | 不直接改共享 migration 文件 |
| LAN lifecycle | LAN 会话 | 当前回归通过，CI 覆盖仍需确认 | 不与 G17 混改 |
| WebUI / browser E2E | WebUI 会话 | 未形成浏览器 CI 门 | 保持保护域 |
| CI / release workflow | CI/主线 owner | 已有并行修改 | 需 owner 确认后再改 |
| Release decision | 项目负责人 | 未签署 | 不宣称 release ready |

## 10. 结论

当前可以确认：

> G17.17-F 的 SQLite queue、lease ownership、heartbeat、跨进程 recovery 和 stop-the-world 设计已经具备充分的阶段性证据，新的 subprocess 终止测试也已通过 10/10 重复验证。

当前不能确认：

> 整个 AssetsManager 已完成发布验收，或旧版/新版应用支持 rolling upgrade。

下一步只有在对应 owner 明确接管后，才推进：

1. schema/commerce v22 正式回归与 ownership note；
2. CI 将新 subprocess/LAN 场景纳入合适门禁；
3. WebUI browser E2E 独立 lane；
4. 统一 cutover regression gate（如项目决定将其提升为硬门禁）；schema→marker→worker 顺序已有 wrapper 级测试。

本清单不授权 staging、commit、reset、checkout、clean，也不改变任何并行会话保护域。
## 11. 运行时残留与当前审计注意事项

重复 subprocess recovery 门禁结束时未发现其自身残留的 Python/pytest 进程。但随后工作区审计发现一个已存在的独立 LAN E2E helper：

```text
PID 46920
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tmp\e2e\run_real_lan_server.py
```

其父 PowerShell 进程为 PID 49212，脚本监听真实 LAN E2E 环境。该进程不是本 checklist 启动的，且位于 `tmp/e2e` 保护域；本会话没有擅自终止或清理它。

因此：

- [ ] release candidate 审查前，必须由该 E2E helper 的 owner 确认它是否应继续运行；
- [ ] 未确认前，不能把“工作区无任何运行时残留”写入 release sign-off；
- [x] G17 subprocess 测试自身没有已知残留；
- [x] 本会话没有执行 destructive process/file cleanup。
## 12. Schema → marker → worker 顺序证据

新增：

`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_reconciliation_bootstrap_order.py`

该测试复用同一个 `ApplicationBootstrap`，通过 wrapper 观察真实生产调用边界：

```text
DatabaseManager.open_library 成功
→ schema_migration_complete
→ migrate_reconciliation_marker 完成
→ AssetIndexReconciliationService.start
→ reconciliation worker is_running
```

测试同时写入最小 legacy reconciliation marker，确保 marker migration 走真实路径，而不是只验证空路径。

验证：

```text
bootstrap order + runtime cutover + runtime lifecycle：5 passed
新测试连续 5 次：每次 1 passed
Ruff：通过
```

该测试补齐了 schema→marker→worker 的同一 bootstrap 顺序证据；仍未证明两个独立 application process 同时执行 marker migration，也不改变当前 single-process marker cutover 边界。
## 13. LAN quota fixture 风险校准

当前工作区的隔离验证结果：

```text
单独 tests/lan/test_lan_api.py：224 passed
与 restore/bootstrap/LAN lifecycle 组合：402 passed, 1 skipped, 1 warning
quota 最小状态测试：1 passed
quota 429 测试：1 passed
```

因此目前不能把 `free_download_quota_windows` 缺表写成稳定的生产 blocker。

但 raw fixture 的结构性事实仍成立：仅执行：

```text
database._SCHEMA
+ AuthRepository.init_tables()
+ ShareRepository.init_table()
```

后，`free_download_quota_windows` 不存在。生产 canonical 路径由 `DatabaseManager.open_library() → migrate_db() → migration v10` 创建该表；LAN raw connection fixture 不会自动触发这条链。

状态：

- [x] 生产 canonical migration v10 归属已确认；
- [x] 独立 LAN API 当前回归通过；
- [ ] raw LAN fixture 在 quota enabled 场景下的初始化合同仍需由 LAN/schema owner 明确；
- [ ] 不得在没有隔离复现和 owner 确认的情况下修改 production quota service 或 migration。
## 14. 当前全量基线更新

```text
Python：2702 passed, 7 skipped, 1 warning
Ruff（AssetsManager + tests）：通过
Pyright：0 errors, 0 warnings, 0 informations
Compileall：通过
```

本次根目录 `ruff check .` 返回 0；扫描过程中对若干受 ACL 保护的临时目录打印“拒绝访问”警告，但未报告 lint error。发布门禁仍应以 CI 的 `ruff check AssetsManager tests` 为主线证据。