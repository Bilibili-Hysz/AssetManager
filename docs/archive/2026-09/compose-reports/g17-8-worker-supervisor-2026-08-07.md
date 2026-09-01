# G17.8 Reconciliation Worker Supervisor Restart — Phase Closure

**日期：** 2026-08-07  
**工作区：** `D:\~Vibe-Coding\Projects\AssetsManager_old-bak`  
**分支：** `master`  
**基线 HEAD：** `fbf3403 Enforce schema object integrity for v6`

## 1. 本切片目标

G17.7 已完成 session-scoped reconciliation queue、asset-index repair worker、marker
恢复和 runtime close 生命周期。本切片只处理其中一个明确后续架构项：

> worker 在连续未预期异常达到 error budget 后，不应只能永久 faulted；在有限次数内
> 可以自动开始新的 processing epoch，同时保留最终 faulted 的有界终止语义。

## 2. 实现边界

修改文件：

- `AssetsManager/application/asset_index_reconciliation_service.py`
- `AssetsManager/application/bootstrap.py`
- `tests/unit/test_asset_index_reconciliation_service.py`

实现内容：

- 新增 `max_worker_restarts`，默认值为 `0`，因此 standalone/历史测试构造保持原有
  “error budget 用尽即 faulted”语义；
- 新增 `worker_restart_backoff`，拒绝负值，并通过同一个 `stop_event` 等待，使 close
  可以打断 restart backoff；
- 新增 `worker_restart_count` 可观测属性；
- 当连续异常达到 `max_consecutive_errors` 时：
  - 仍有 restart budget：清零当前 error epoch，在同一个 daemon supervisor loop 中
    开启新 processing epoch；
  - restart budget 用尽：设置 `worker_faulted=True` 并终止 worker；
- canonical `ApplicationBootstrap` 为 runtime worker 启用最多 2 次自动 restart，
  每次基础 backoff 为 1 秒；
- 保留现有 bounded stop、start failure cleanup、last error 和 consecutive error
  可观测语义。

这里没有把 supervisor 扩展成无限重启，也没有把 queue 改造成 SQLite durable queue；
多进程 marker 协调、持久队列、底层 I/O cancellation 仍是独立后续阶段。

## 3. 验证

定向回归：

```text
11 passed
```

覆盖：

- 原有 durable publish/retry/terminal 状态转换；
- worker start/stop/idempotence；
- worker start failure cleanup；
- error budget exhausted 后 faulted；
- 自动 restart 后继续运行；
- restart budget 用尽后 faulted；
- stop timeout 后保留可重试生命周期。

静态/语法门禁：

```text
Ruff：通过
Pyright（bootstrap + reconciliation service）：0 errors
compileall（相关 Python 文件）：通过
git diff --check（tracked 修改）：通过
```

没有重复执行此前已通过的全量 Python 回归；G17.7 的全量基线仍为 `2583 passed,
6 skipped, 1 warning`，本切片只新增并验证局部代码。

## 4. 已知边界与未宣称事项

1. restart policy 只覆盖 worker loop 捕获的 `Exception`；进程控制类 `BaseException`
   仍按原有生命周期语义传播。
2. 如果异常发生在任务已 claim 之后，任务仍依赖 lease/recovery 机制重新可见；本切片
   没有改变 queue 的 claim lease 合同。
3. `worker_restart_count` 是当前 worker session 的统计，调用 `start()` 重新启动后
   会重置为 0。
4. 工作区仍为多会话混合 dirty 状态；未执行 `git reset`、`git checkout`、全量
   `git clean`、staging 或 commit。
5. `webui/**`、`tests/e2e/**`、`tmp/**` 继续属于保护写域，本切片未接管。

## 5. 下一阶段建议

建议不要立即把 SQLite durable queue、跨进程 marker lock、projection generation 和
legacy integer API 混在同一个切片。优先顺序应保持：

1. SQLite durable queue：先完成 schema/ownership/transaction contract 与双实现兼容
   测试，再接入 runtime；
2. 多进程 marker/queue generation：明确 single-writer 与并发 merge 责任；
3. bounded cancellation：补充底层 scan I/O 可中断边界；
4. projection generation：将 asset index、metadata/tags/favorites/thumbnail/cache
   的 generation 统一成可审计合同；
5. legacy integer asset-index API：完成 caller inventory 后再做最终删除或 deprecation。
