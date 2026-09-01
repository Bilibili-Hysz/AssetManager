# G17.17-F Cutover / Cross-process Hardening 长期任务计划 — 2026-08-08

**工作区：** `D:\~Vibe-Coding\Projects\AssetsManager_old-bak`  
**分支：** `master`  
**前置阶段：** G17.17-E 已完成 worker lease renewal、heartbeat 与硬 operation-age 验证；F 尚未完成。

## 1. F 的目标

把当前“同一进程内多 connection + SQLite generation polling”的验证，提升为可审计的进程边界合同：

```text
进程 A / 旧 worker
        │
        ├─ claim / renew / completion
        │
        ▼
SQLite durable queue
        ▲
        │
进程 B / recovery / 新 worker
```

F 不把“当前测试通过”直接等同于 rolling upgrade 安全；必须分别证明：

1. 真实独立进程之间不会重复 claim；
2. recovery 后旧 token 的 renew/completion 全部失效；
3. generation refresh 不回写旧 snapshot/token；
4. marker/schema cutover 期间旧 writer 要么被明确阻止，要么拥有可验证的 capability gate；
5. 数据库连接关闭、进程退出和重启不会留下无法回收的 running lease。

## 2. 当前覆盖与缺口

已有覆盖：

- 两个 SQLite connection 的 remote enqueue/wakeup；
- queue generation polling；
- same-process claim/completion/recovery CAS；
- JSON marker 到 SQLite 的单进程 cutover；
- bootstrap runtime 使用 managed SQLite queue；
- G17.17-E in-memory/SQLite lease heartbeat 定向测试。

尚缺覆盖：

- 两个真实 OS process 的 claim race；
- 一个进程 recovery、另一个进程 late completion 的端到端矩阵；
- 真实 managed `DatabaseManager` connection 的多进程关闭/重启；
- old writer 在 migration 17/18 后的行为；
- marker 文件在两个启动进程同时迁移时的锁与归档竞争；
- heartbeat in-flight 遇外部 SQLite lock 的清理行为。

## 3. 分阶段任务

### F-1：真实多进程 queue matrix

新增 Windows spawn-safe 的 integration tests，仅使用临时 SQLite 数据库和 queue schema：

- A/B 同时 claim：最多一个进程得到任务；
- A claim 后退出，B recovery 并重新 claim；
- A 使用旧 token late renew/succeeded/retryable/terminal/cancel：不得改变 B 的状态；
- generation refresh 后 queue snapshot 必须保留新 token；
- B completion 后 A 的 stale result 只能是 benign no-op 或明确 stale conflict。

验收：每个子场景可重复执行，不依赖测试顺序或固定 sleep。

### F-2：cutover / writer capability contract

先做设计决策，不直接假设 rolling upgrade 安全：

- **方案 A：stop-the-world cutover**。启动时停止旧 worker，完成 schema 17/18、marker retirement 后再启动新 worker；
- **方案 B：capability gate**。引入可持久化的 writer capability/epoch，旧 writer 在 claim、replace、completion 前 fail-closed；
- **方案 C：独立 lease 表/版本化 worker epoch**。将新旧 writer ownership 与 task row 解耦。

在没有可执行 gate 前，不宣称支持旧新进程并行。

### F-3：managed connection fault injection

使用真实 `DatabaseManager` 管理连接验证：

- connection close during claim/renew/completion；
- 外部 SQLite write lock；
- process termination after claim before completion；
- restart recovery；
- worker stop timeout 与 queue state 可观察性。

### F-4：release gate

F 只在以下条件同时满足后才允许进入 release candidate 审查：

- F-1/F-3 定向测试通过；
- migration/cutover 合同有明确版本边界；
- commerce schema v8/v18 迁移归属问题已由 commerce 会话修复并独立回归；
- Python、静态门禁、WebUI/e2e、LAN 测试形成可追踪 gate；
- 共享工作区建立明确 clean boundary，未经确认不 staging/commit。

## 4. 保护边界

本计划不修改：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\e2e\`
- commerce/LAN 领域 schema 与业务实现；
- 其他并行会话的未提交修改。

## 5. 当前状态

截至 2026-08-08：

- F-1 处于测试设计/实现阶段；
- F-2 尚未选择 capability gate 方案；
- F-3 尚未执行；
- 不进行 release、staging 或 commit。

## 6. 2026-08-08 执行更新：F-1 真实多进程矩阵已加入

新增（仅测试域，不改 production）：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_reconciliation_queue_process_matrix.py`

实现特征：

- `multiprocessing.get_context("spawn")`；
- 模块级 child target，Windows spawn-safe；
- 临时 SQLite WAL schema；
- 两个独立 OS process / SQLite connection；
- claim race、renew、recovery、旧 token completion 与新 owner completion。

验证：

```text
F-1 新文件：2 passed
F-1 + 既有 cross-process/runtime 集成：8 passed
queue/store/service/supervisor + F-1/cross-process/runtime：62 passed
Ruff（F-1 文件）：通过
```

F-1 结论：当前 token/attempt/expiry CAS 在真实独立进程下通过最小 claim/recovery/completion 矩阵；这仍不等于旧版本 writer rolling upgrade 已安全。

下一步转入 F-2：先确定 stop-the-world cutover、writer capability gate 或独立 lease/epoch 表三者之一，再编写对应 fail-closed 测试；在方案确定前不修改生产 schema/commerce 文件。

## 7. F-2 初步设计决策：采用 stop-the-world，不宣称 rolling upgrade

当前应用已有跨进程 `LibraryLock`：

- `LibraryService._open()` 在取得 managed connection 与 bootstrap service assembly 前先 acquire library lock；
- lock 生命周期覆盖整个 library session；
- 第二个完整应用进程不能同时打开同一 library；
- bootstrap 的 marker migration 与 reconciliation worker assembly 发生在该 owner session 内。

因此当前最小安全合同选择：

```text
单 library 单应用 owner
    ↓
停止旧 worker / 关闭旧 session
    ↓
完成 schema + marker cutover
    ↓
构造 SQLite queue + token-aware worker
    ↓
恢复新 worker
```

F-2 暂不引入独立 capability 表、writer epoch 或新 schema，因为这些方案无法在旧 writer 不认识新合同的情况下单独阻止旧 writer 的任意 SQL/replace 写入；贸然添加会制造新的 migration 与 rollback 风险。

明确边界：

- **支持：** 同一 library 单应用 owner 下的 crash recovery、独立 queue worker 进程级 CAS 验证、stop-the-world migration/cutover；
- **不支持：** 旧版本应用与新版本应用同时持有同一 library 的 rolling upgrade；
- **后续若必须支持 rolling：** 另立架构阶段，采用独立 writer capability/epoch 或强制 DB trigger/connection capability 机制，并先完成 threat model 与 rollback 设计。

F-2 后续应补一条 bootstrap ordering/LibraryLock integration test，确认 migration 不会在 library ownership lock 之前执行；在此之前不修改生产 schema。

## 8. F-3 执行更新：connection-close fault injection 已通过

新增（仅测试域）：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_reconciliation_queue_fault_injection.py`

覆盖：

1. old claim connection 在 renew 前关闭：renew fail-closed；另一 connection 可 recovery 并取得新 attempt/token；
2. old claim connection 在 completion 前关闭：completion 不报告成功；另一 connection recovery 后可用新 token 完成 succeeded/revision。

验证：

```text
F-3 fault injection + F-1 process matrix + cross-process/runtime：10 passed
Ruff（F-1/F-3 文件）：通过
compileall：通过
```

F-3 当前只覆盖 connection-close；外部 SQLite write lock、heartbeat in-flight、进程终止后的 managed connection cleanup 仍需后续 fault-injection 扩展。

## 9. 当前工作区最终验证（含 F-1/F-3 测试）

```text
全量 Python 回归：2657 passed, 6 skipped, 1 warning
Ruff：通过（全量扫描仅有 pytest 临时目录拒绝访问 warning）
Pyright：0 errors, 0 warnings, 0 informations
compileall：通过
```

6 个 skip 仍是 Windows symlink 权限限制；1 个 warning 仍是重复 ZIP 条目测试 warning。新增 F-1/F-3 测试没有引入生产回归。

当前仍未进行 staging、commit、reset、checkout 或全量清理。

## 10. 2026-08-08 后续执行：F-2/F-3 扩展验证

新增测试：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_reconciliation_cutover_lock_order.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_reconciliation_queue_external_lock.py`

F-2 覆盖：

- library session 获取 `LibraryLock` 必须先于数据库 connection；
- 该顺序作为 stop-the-world cutover 的 ownership boundary 固化。

F-3 覆盖：

- 外部 SQLite `BEGIN IMMEDIATE` write lock 阻塞 renew；
- 外部 write lock 下旧 completion fail-closed；
- 释放锁后新 connection recovery、重新 claim 和 completion。

验证：

```text
F-3 + F-1/cross-process/runtime：12 passed
F-2 + library/cutover：59 passed
Ruff（新增测试）：通过
compileall：通过
```

F-2/F-3 仍不宣称支持旧版本 rolling writer；F-3 尚需进一步覆盖 heartbeat in-flight 与进程被终止后的 managed connection cleanup。

## 11. 当前工作区全量门禁（2026-08-08）

新增 F-2/F-3 测试后重新执行：

```text
全量 Python：2660 passed, 6 skipped, 1 warning
Ruff（F-2/F-3 新增测试）：通过
Pyright：0 errors, 0 warnings, 0 informations
compileall：通过
```

F-2 组合测试输出了若干已有 library integration fixture 的 `ResourceWarning: unclosed database`，但没有 test failure；该资源治理问题应另立清理任务，不与 reconciliation ownership safety 混修。

## 12. 2026-08-08 F-4 heartbeat / process termination 复核

新增：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_reconciliation_queue_heartbeat_inflight.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_reconciliation_queue_process_termination.py`

### Heartbeat in-flight

heartbeat 竞态测试覆盖：

- renew in-flight 时 operation 完成必须等待 heartbeat 退出；
- heartbeat_stop / worker_stop 不得产生延迟 renew 或错误重启；
- recovery 与 completion mutation 竞态必须 fail-closed。

验证：

```text
heartbeat/supervisor：22 passed
稳定 F 组合：34 passed, 1 skipped
```

新增 heartbeat helper 初次触发 architecture boundary 的 `.current` 保留名，已改为 `owned_task`；无 production 修改。

### 进程终止

`test_reconciliation_queue_process_termination.py` 保留为 F-4 draft，但明确标记 skip：

- Windows spawn + `os._exit()`；
- 子进程持有 SQLite connection；
- multiprocessing Queue feeder/finalizer；
- pytest 主进程 join/finalization。

该组合在独立运行与共享主会话之间出现不一致，曾造成无 traceback 长时间等待，因此暂不纳入默认回归。稳定的 process matrix、connection-close 和 external-lock 测试仍然保留并通过。

## 13. 当前工作区全量验证

heartbeat helper 修正及进程终止 draft 显式 skip 后重新执行：

```text
全量 Python：2683 passed, 7 skipped, 1 warning
Ruff：通过（全量扫描仅有 pytest 临时目录拒绝访问 warning）
Pyright：0 errors, 0 warnings, 0 informations
compileall：通过
```

## 14. 新发现的并行领域风险

当前共享工作区的 `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\core\db_migrations.py` 已被其他并行领域扩展至 schema version 22。v22 helper 附近存在：

```python
if _table_exists(conn):
```

而 `_table_exists()` 当前需要 `table` 参数。该风险属于 commerce/schema 并行写域，本轮未修改；需要由归属会话单独修复并覆盖 v22 migration path。

该问题当前未阻塞本轮完整 Python 结果，但在真正触发 v22 migration 的数据库/fixture 上可能成为运行时阻塞。

## 15. 2026-08-08 F-4 进程终止 recovery 收尾

### 15.1 确定性 subprocess 验证

新增：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_reconciliation_queue_process_termination_subprocess.py`

该测试不再依赖 Windows `multiprocessing.Queue`、Queue feeder thread 或 pytest 进程内 finalizer，而是使用：

- `subprocess.Popen` 启动独立旧 worker / 新 worker；
- 临时 JSON 文件作为单向握手和结果通道；
- 临时文件写入后原子 rename，避免父进程读取半写入 JSON；
- 所有握手、进程退出和清理等待均有 bounded timeout；
- 父进程观察旧 worker claim 后调用 `Popen.terminate()`；
- 新 worker 在固定 `now=2.0`、`wallclock=1002.0` 下 recovery，在 `now=3.0`、`wallclock=1003.0` 下 reclaim；
- 旧 lease token 的 completion 必须 fail-closed，新 owner 完成后最终状态必须为 `succeeded`。

实现过程中确认：`ReconciliationQueue` 构造函数会执行 eager recovery，因此测试先用有效 lease 时钟加载 snapshot，再显式推进到 `now=2.0 / wallclock=1002.0` 执行 recovery；该边界已稳定验证。

验证：

```text
python -m pytest -q tests/integration/test_reconciliation_queue_process_termination_subprocess.py
1 passed in 1.98s

python -m pytest -q <reconciliation/core migration 定向组合>
87 passed, 1 skipped in 10.78s
```

原 `tests/integration/test_reconciliation_queue_process_termination.py` 仍保留为明确 skip 的历史 draft，不把不稳定的 multiprocessing Queue 终止组合重新纳入默认门禁；新的 subprocess 测试承担稳定的进程终止 recovery 合同验证。

### 15.2 v22 migration 只读复核结论修正

上一节记录的：

```python
if _table_exists(conn):
```

在当前工作区源码中并不存在。只读检索确认：

- `_table_exists` 定义于 `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\core\db_migrations.py:150`，需要 `(conn, table)` 两个参数；
- v22 实际调用位于同文件约第 672 行：`_table_exists(conn, table)`，参数完整；
- 全量 `AssetsManager` / `tests` Python 文件没有零参数 `_table_exists(conn)` 调用；
- `tests/core/test_delivery_attempt_migration.py::test_v21_to_v22_creates_delivery_attempts_table` 已覆盖 v21→v22 的“表不存在→创建”路径；
- v22 的“表已存在→兼容性校验/最终校验”分支仍缺少独立回归；该缺口属于 `schema/migration` 写域，不在本次 reconciliation 任务中修改；
- `tests/core/test_delivery_attempt_migration.py` 目前仍是未跟踪文件，必须由 schema/migration 归属会话决定是否纳入其交付范围。

v19→v22 定向 migration 回归已执行通过：

```text
python -m pytest -q tests/core/test_delivery_attempt_migration.py tests/core/test_db_migrations.py
54 passed in 0.92s
```

### 15.3 最终全量门禁

本轮新增 subprocess 测试及上述断言修正后，全量验证结果：

```text
python -m pytest -q
2686 passed, 7 skipped, 1 warning in 288.82s

ruff check .
All checks passed!
（仅报告 .pytest-tmp 目录访问拒绝 warning）

pyright
0 errors, 0 warnings, 0 informations

python -m compileall -q AssetsManager tests
通过
```

7 个 skip 为：

- 6 个 Windows symlink 权限限制；
- 1 个明确标记为历史 draft 的 multiprocessing Queue 进程终止测试。

1 个 warning 为既有重复 ZIP 条目测试 warning，不由本轮引入。

### 15.4 当前工作区与剩余边界

当前仍保持：

- 分支 `master`，HEAD `fbf3403`；
- 未 staging、未 commit；
- 未执行 reset、checkout 或全量 clean；
- 全量测试结束后无残留 Python/pytest 进程。

本次检查仍不宣称旧版本与新版本应用支持 rolling upgrade；F-2 继续采用 stop-the-world cutover 边界。剩余应单独立项的事项：

1. 由 schema/migration 归属会话补 v22 existing-table / incompatible-schema 分支回归，并决定是否纳入当前未跟踪的 `test_delivery_attempt_migration.py`；
2. 评估 `AssetsManager/core/db_migrations.py` 当前工作区末尾空行导致的 `git diff --check` 提示；本次未触碰该并行写域文件；
3. 后续若要把历史 multiprocessing Queue draft 变为门禁，必须先解决其 Windows spawn / Queue finalization 的确定性，而不是放宽超时或取消 bounded cleanup。

本阶段目标是 reconciliation G17.17-F 的 cross-process / lease ownership 验证收尾，不等价于整个 AssetsManager 工作区的 commerce、LAN、WebUI/E2E 或 schema 领域已经完成整合。
## 16. 2026-08-08 稳定性复核与主线一致性校准

### 16.1 subprocess 终止测试重复稳定性

由独立子代理在不写入工作区的前提下执行 10 次 bounded 重复验证：

```text
目标测试：tests/integration/test_reconciliation_queue_process_termination_subprocess.py
通过：10/10
失败：0
超时：0
总耗时：44.785 s
平均耗时：4.479 s
```

单次最长启动耗时约 15.426 秒，后续运行稳定在约 3 秒墙钟时间；没有发现 `python.exe`、`pythonw.exe`、`pytest.exe` 或 `py.exe` 残留。相关 87-test 组合在该复核中得到：

```text
86 passed, 1 skipped in 11.93s
```

因此建议将新的 subprocess 测试纳入常规 reconciliation 集成门禁；历史 multiprocessing Queue draft 继续保持明确 skip，不因重复稳定测试通过而取消原有豁免边界。

### 16.2 G6-1 restore R1 状态校准

当前代码与专项测试显示，主线 handoff 中“R1 尚未完成”的旧描述已经落后于工作区实际状态。当前已存在并通过验证的合同包括：

- `LibraryService.restore_reservation()` root-aware ownership reservation；
- replacement session 与 stale owner 拒绝；
- 没有 coordinator 时 restore fail-closed；
- staging、quarantine、install、quick_check、rollback 全部位于 reservation 内；
- quarantine failure、rollback failure、lock release failure 的 secondary error 暴露；
- restore poison/recovery token、跨 bootstrap admission block 和显式 acknowledgement；
- archive member、expanded size、compression ratio、manifest 与 database quick_check 上限。

专项验证：

```text
144 passed, 1 skipped, 1 warning
```

覆盖文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\unit\test_library_export_service.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\unit\test_library_service.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\unit\test_bootstrap.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_library_service.py`

因此后续不应重复从 R1 基础实现开始；如继续推进 G6-1，只剩产品入口/进度反馈/Runtime 重建/迁移提示等明确的后续切片，且不应混入 G17 reconciliation。

### 16.3 下一批可安全执行的任务边界

当前主线没有授权接管以下写域：

1. Commerce/schema：v22 existing-table/incompatible-schema migration 回归；
2. LAN：窗口关闭时 server-stop failure 生命周期竞态；
3. WebUI/E2E：Playwright 路径、服务启动与 CI E2E lane；
4. CI workflow：其他并行会话已修改 `.github/workflows/ci.yml`，本轮不直接重排其 jobs。

可安全继续的主线任务是：

- 将 G17 stop-the-world cutover 边界整理为 release checklist/ownership note；
- 更新 handoff 与长期任务记录，纠正 R1 已完成、G17-F 已验证、其余领域仍 partial 的状态；
- 为 schema/LAN/WebUI 会话提供只读证据和明确交接，不跨域写入。

在新的写域归属确认前，本轮不修改 Commerce、LAN、WebUI/E2E 或共享 CI job。
## 17. 2026-08-08 LAN 当前状态复核校准

此前只读审查引用了交接文件中的历史 LAN stop-failure 证据，但该证据不是当前工作区的新鲜结果。重新执行当前源码下的 LAN 生命周期测试得到：

```text
python -m pytest -q -p no:cacheprovider tests/integration/test_window_lifecycle_lan_failure.py
2 passed in 9.60s

LAN lifecycle 相关组合（tests/integration/test_window_lifecycle_lan_failure.py + tests/lan/test_server_lifecycle.py）
41 passed in 57.86s
```

因此当前不能把 LAN 描述为“已确认仍失败”；准确表述应为：

- 当前工作区的 LAN 生命周期回归可通过；
- 历史交接材料中仍有旧失败记录，需要与当前代码版本区分；
- `.github/workflows/ci.yml` 的 Windows regression 尚未明确运行 `test_window_lifecycle_lan_failure.py`，所以该场景仍存在 CI 覆盖缺口；
- LAN 仍保持独立写域，不在 G17 或 schema 任务中顺手修改。

该校准不改变 WebUI/E2E 未纳入浏览器门禁、Commerce/schema v22 existing-table 分支未独立回归等剩余边界。
## 18. 2026-08-08 v22 existing-table 路径只读行为验证

虽然本轮不接管 Commerce/schema 写域，也没有新增 migration 测试文件，但使用临时 SQLite 内存库对当前实现做了两条只读行为验证：

```text
v21 + 已存在且兼容的 shop_delivery_attempts -> v22：PASS
v21 + 已存在但不兼容的 shop_delivery_attempts -> InvalidSchemaError：PASS
不兼容路径 schema_migrations 仍保持版本 21：PASS
```

因此当前更准确的结论是：

- v22 `_table_exists(conn, table)` 运行时分支目前行为符合 fail-closed 预期；
- 现有缺口主要是独立回归测试与 migration ownership note，而不是已经复现的 v22 运行时 TypeError；
- 测试与归属仍应由 Commerce/schema 会话补齐，本轮不直接写入 `AssetsManager/core/db_migrations.py` 或其测试文件。
## 19. 2026-08-08 G17 release/ownership checklist 固化

新增独立可审计清单：

`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\docs\compose\reports\g17-stop-the-world-cutover-release-ownership-checklist-2026-08-08.md`

该清单不重复 G17.17-F 的实施计划，而是集中记录：

- stop-the-world 与“不支持 rolling upgrade”的决策边界；
- lock → connection → schema → marker → queue → worker 的启动顺序；
- 旧 worker stop、heartbeat drain、DB close、LibraryLock release 的关闭顺序；
- lease token、stale completion、进程终止 recovery 的门禁状态；
- 当前通过项、未完成项、owner、abort/no-go 条件；
- schema/commerce、LAN、WebUI/E2E、CI 的跨域阻断和归属。

当前清单结论为：

```text
G17.17-F 阶段证据：可进入阶段审查
整个 AssetsManager release：未批准
Rolling upgrade：不支持
```
## 20. 2026-08-08 当前运行时残留审计

在 checklist 证据路径核验结束时，发现一个当前运行的独立 LAN E2E helper：

```text
PID 46920
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tmp\e2e\run_real_lan_server.py
```

该进程由 PID 49212 的 PowerShell 启动，属于 `tmp/e2e` 保护域；不是本会话启动的 G17 subprocess 测试。本会话没有擅自终止进程或清理文件。

因此此前“无残留 Python/pytest 进程”的结论应限定为：**G17 subprocess 稳定性复核结束时未发现其自身残留**。当前整个工作区的 release clean boundary 仍需由该 E2E helper owner 确认后才能签署。
## 21. 2026-08-08 library-owner handoff 时间线测试收口

新增：

`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_reconciliation_library_owner_handoff.py`

该测试仅使用现有生产 API 的 wrapper 记录可观察事件，未新增生产 seam，覆盖：

- 旧 runtime 开始 closing；
- reconciliation worker stop；
- runtime cleanup；
- DB release；
- LibraryLock release；
- 新 owner 获取同一 root；
- 新 runtime 启动且 worker running；
- 旧 owner stop timeout 时，新 owner 不能提前接管；
- 旧 owner retry 成功后，新 owner 才能接管。

验证：

```text
python -m pytest -q tests/integration/test_reconciliation_library_owner_handoff.py
2 passed

handoff + runtime/lifecycle + library runtime 组合
32 passed

新测试连续复跑 5 次：每次 2 passed
Ruff：通过
```

该测试补齐了此前 checklist 中“library-owner 级旧 owner → 新 owner 交接”证据缺口。仍未把 schema migration → marker migration → worker start 的全部事件合并到同一条时间线，因此 schema/marker order 继续标记为部分覆盖，不宣称完整端到端 cutover gate 已建立。
## 22. 2026-08-08 schema → marker → worker 顺序测试收口

新增：

`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_reconciliation_bootstrap_order.py`

测试使用 `monkeypatch` wrapper 观察当前生产边界，并真实写入 legacy reconciliation marker，验证同一 `ApplicationBootstrap` 内：

```text
DatabaseManager.open_library 成功
→ schema_migration_complete
→ migrate_reconciliation_marker 完成
→ AssetIndexReconciliationService.start
→ worker is_running
```

验证：

```text
bootstrap order + runtime cutover + runtime lifecycle：5 passed
新测试连续 5 次：每次 1 passed
Ruff：通过
```

这补齐了此前 checklist 中 schema→marker→worker 的顺序证据。当前仍只证明单一 canonical bootstrap 的顺序，不证明两个独立 application process 并发 marker migration，也不扩展 rolling upgrade 能力。
## 23. 2026-08-08 LAN quota 缺表结果的可重复性校准

并行审查曾在包含 restore/bootstrap/LAN 测试的组合中观察到 10 个 `free_download_quota_windows` 缺表失败，但当前会话使用 `-p no:cacheprovider` 重新执行相同文件组合得到：

```text
402 passed, 1 skipped, 1 warning
```

独立 LAN API 组合也得到：

```text
224 passed
```

因此该缺表现象当前不能直接定性为生产 blocker。当前审计时另有一个外部 pytest 进程正在运行，不能排除并行测试环境、全局 monkeypatch 或 fixture 顺序对先前结果的影响；本会话没有终止该外部进程。

但 raw fixture 的结构性风险已被独立确认：

```text
database._SCHEMA
+ AuthRepository.init_tables()
+ ShareRepository.init_table()
→ free_download_quota_windows 不存在
```

生产 canonical 路径由 `DatabaseManager.open_library() → migrate_db() → migration v10` 创建 quota 表；`tests/lan/test_lan_api.py` 的 raw connection fixture 不会自动进入该 migration 链。

准确归类：

- 不是当前已稳定复现的 production quota blocker；
- 是 LAN raw fixture 在 quota enabled 场景下缺少 schema initialization contract 的潜在风险；
- 由 LAN/schema owner 决定是否补 fixture migration 或明确 raw connection compatibility contract；
- G17 会话不修改 quota service、LAN route 或 schema migration。
## 24. 2026-08-08 当前工作区快速基线更新

在无其他 pytest 进程运行后执行：

```text
python -m pytest -q -p no:cacheprovider
2702 passed, 7 skipped, 1 warning
```

新增的 library-owner handoff 与 bootstrap-order 测试已包含在该全量结果中。

静态门禁：

```text
ruff check AssetsManager tests
通过

pyright
0 errors, 0 warnings, 0 informations

python -m compileall -q AssetsManager tests
通过
```

本次 `ruff check .` 返回 0；

- `AssetsManager`、`tests` 范围通过；
- 扫描过程中对若干受 ACL 保护的临时目录打印“拒绝访问”警告，但未报告 lint error；
- 当前 `tmp/e2e` 目录没有可扫描的 `run_real_lan_server.py`；
- 这不是本轮 G17 测试引入的生产/测试代码错误。
## 25. 2026-08-08 README 门禁基线同步

已对 `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\README.md` 做最小局部同步：

- Python 基线更新为 `2702 passed, 7 skipped, 1 warning`；
- 主线 Ruff 命令明确为 `ruff check AssetsManager tests`；
- pytest 命令加入 `-p no:cacheprovider`，与本次稳定基线一致；
- CI jobs 更新为当前已有的 lint、hygiene、typecheck、WebUI、Windows package smoke、Windows regression、Python matrix；
- 明确 browser E2E 尚未纳入 CI；
- 增加 G17 stop-the-world、no rolling-upgrade 边界说明。

本次只修改 README 的状态/门禁说明，保留其他并行会话已经加入的 Commerce/Seller 文档内容。
## 26. 2026-08-08 README 质量门细节修正

README 质量门现已与实际基线一致：

```text
ruff check AssetsManager tests
python -m pyright
python -m compileall -q AssetsManager tests
python -m pytest -q -p no:cacheprovider
```

同时说明了 7 个 skip 的来源（Windows symlink 权限限制与历史 multiprocessing Queue draft）及既有重复 ZIP 条目 warning，避免把 skip/warning 误解成未记录的失败。