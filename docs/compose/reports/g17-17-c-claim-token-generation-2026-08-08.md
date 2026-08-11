# G17.17-C Claim Token Generation 与 Lease Recovery — 2026-08-08

**工作区：** `D:\~Vibe-Coding\Projects\AssetsManager_old-bak`  
**分支：** `master`  
**前置：** G17.17-A/B schema v17 与 snapshot round-trip 已通过。

## 1. 本切片目标

为成功 claim 建立一次持久化 lease identity，但暂不把 token 作为 completion CAS 入参；completion token 校验属于下一切片 D。

本切片保持以下旧合同：

```text
task_id + attempts + lease_expires_at_wallclock
```

仍然有效；新增 token 只作为同一 claim 的持久化 identity 和后续 D 切片的输入。

## 2. 已实现

修改：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\reconciliation_queue.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\reconciliation_queue_store.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\unit\test_reconciliation_queue.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\unit\test_reconciliation_queue_sqlite_store.py`

行为：

1. 内存 queue 成功 claim 生成 `uuid4().hex` token；
2. SQLite claim 在同一事务中生成 token，并与 running state、attempts+1、lease expiry 一起写入；
3. claim 返回的 task 与 durable snapshot 读取到同一 token；
4. expired lease recovery 将 token 清空，再回到 retryable/terminal；
5. succeeded/retryable/terminal/cancelled 状态转换清空 token，避免 finished task 保留旧 lease identity；
6. claim 失败、无候选或 recovery-only 路径不会生成无主 token。

## 3. 当前未实现

以下仍明确未完成：

- `mark_succeeded` / `mark_retryable` / `mark_terminal` / `cancel` 的 token CAS；
- renew API；
- 错 token、空 token、过期 token的 fail-closed policy；
- worker context 传递 token；
- stale worker 完成与 token 的最终组合语义。

因此 C 不能单独宣称 claim identity 安全闭环完成。

## 4. 验证

截至 2026-08-08：

```text
C 相关 queue/store/runtime/cross-process 定向回归：33 passed
Ruff：通过
Pyright：0 errors, 0 warnings
compileall：通过
```

G17.16 全量定向集合需要在 C 后再次执行；当前工作区全量 Python 回归在 A/B 后的最近一次 clean run 为：

```text
2639 passed, 6 skipped, 1 warning
```

其中此前一次全量 run 出现过 1 个 LAN startup cleanup timing failure；该 LAN 测试单独连续 5 次、每次 2 参数均通过，随后全量 clean run 通过。该异常不归因于 reconciliation C。

## 5. 下一切片

G17.17-D：把 `lease_token` 纳入所有 worker-owned mutation 的 CAS：

- API 显式传入 token；
- SQL WHERE 同时校验 task、state、attempts、expiry、token；
- mutation 成功后清空 token；
- stale token 不得修改 recovery 后的新 attempt；
- supervisor 传递 token，旧 worker completion fail-closed。

在 D 未完成前，不得恢复“新旧 worker并行安全”结论。
