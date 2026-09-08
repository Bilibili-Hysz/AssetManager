# N3 执行线证据：取消后的 ZIP 所有权闭环（2026-09-08）

## 执行环境

| 项 | 值 |
|---|---|
| 快照基线 HEAD | `e3a908e46713a842451085d818d859ddaff9e0f1` |
| 快照目录 | `.pytest-tmp-lead-snapshots/n3-lan-ops`（`git archive HEAD` 独立快照，非 git 工作区） |
| 平台 / 版本 | win32 (10.0.26220) / Python 3.14.3 / pytest 9.0.2 / aiohttp 3.14.0 / anyio 4.13.0 |
| 运行命令 | `QT_QPA_PLATFORM=offscreen python -m pytest -q -o addopts='' -p no:cacheprovider --junitxml=artifacts/n3-zip-ownership.xml tests/lan/test_zip_cancel_ownership_loop.py tests/lan/test_zip_response_cleanup.py tests/lan/test_zip_cleanup_integration.py` |
| 结果 | **15 passed**（新测试 2 + 既有回归 13），4.38 s；稳定性：另加 3 轮重复运行全部 15 passed |
| 生产代码改动 | **零**（快照内仅新增一个测试文件；主工作区仅写回本目录 3 个 `n3-*` 证据文件） |

## 新增测试

`tests/lan/test_zip_cancel_ownership_loop.py`（快照内新增，主工作区不改生产代码、不回移测试）：

- `test_cancelled_batch_zip_ownership_loop` — 工作包第 1-4 步的连续叙事。
- `test_identity_change_keeps_ownership_and_spares_replacement` — 工作包第 5 步。

harness 复用既有手法（`test_zip_budget_http.py` 的 TestClient/TestServer 真实 HTTP、
`test_zip_cleanup_integration.py` 的 `retry_clock` fixture、`test_zip_response_cleanup.py` 的
mkstemp 追踪），未复制 HTTP 伪造器；app 注入 `ZipResourceBudget(max_jobs=1)`、
`ZipCleanupService(start_worker=False, clock=…)`、临时 ZIP 全部落在 `tmp_path`、
受控 `TemporaryFileResponse.prepare`（观察包装）与 `_make_response`（捕获 owner 打开的
BufferedReader）。

## 5 步断言组状态表

| 步骤 | 断言组 | 状态 |
|---|---|---|
| 1 真实 batch ZIP + 中途取消 | POST `/api/download/batch`（8 MiB 不可压缩负载）→ 200；客户端读前 4096 字节 → 取消续读 task → `response.close()` 断开 transport（服务端确定仍在发送中，≥7 MiB 未送达） | 通过 |
| 2 cleanup 屏障持有 owner/reservation | unlink 门闩使 owner 必然未完成：`pending_count == 1`；`budget == {active_jobs:1, reserved_bytes:512 MiB}`；`try_acquire() is None`；owner `_cleanup_requested` 且未 `_cleanup_complete`、release 回调仍被持有；第二个真实 HTTP job 得 503 `zip_capacity_exhausted` + `Retry-After: 1`，且**不**新建 ZIP（mkstemp 计数不变）、**不**消费额度（consume 计数不变）。“不以 HTTP handler 返回即认为释放”由“请求端已断开而预算仍被占用”直接证明；“若 cleanup 已完成归零则第二 job 合法获准”由门闩使提前完成不可能（屏障期无歧义），并在步骤 3 用真实 200 证明合法放行 | 通过 |
| 3 驱动 cleanup retry clock | 第二次 `run_due()` 成功后：ZIP 路径消失、owner `_file is None` 且捕获的 BufferedReader `.closed`、`budget == {active_jobs:0, reserved_bytes:0}`、`pending_count == 0`、`completed_count == 1`；随后真实第二个 batch job 获准（200、ZIP member 名与逐字节摘要正确），其自身清理后预算再次归零 | 通过 |
| 4 首次 `os.unlink` PermissionError | 取消时首次 unlink 失败（文件仍在、reservation 未释放、owner 记录 `_failed_unlink_identity`）；第一次 `run_due()` 重试仍失败：`pending_count == 1`、`retry_attempts == 1`、`completed_count == 0`、`last_error_type == "PermissionError"`；第二次 `run_due()` 成功后才释放并放行下一 job | 通过 |
| 5 identity 改变 | 首次失败后同路径写入不同内容替换文件；门闩放开后 `run_due()`：`last_error_type == "IdentityChangedError"`、`pending_count == 1`、`completed_count == 0`（无“清理成功”假通过）、替换文件逐字节保留、**unlink 甚至未被尝试**（门闩 spy 的 archive 调用数不变）；时钟再推进重试仍 pending、预算仍占用、`try_acquire() is None`、第二个真实 HTTP job 503 | 通过 |

## 与工作包的差异

1. **落点文件**：工作包原文建议“在 `test_zip_response_cleanup.py` 或已有
   `test_zip_cleanup_integration.py` 中”实施；本次按执行线任务落在独立新文件
   `tests/lan/test_zip_cancel_ownership_loop.py`。既有两个文件一字未动，其断言
   （15 项）原样全绿，满足“不以替换方式弱化”的硬约束。
2. **第 1 步“阻塞在开始发送后读取一小段”**：以“读 4096 字节 + 取消续读 task +
   `response.close()` 断开 transport”组合实现；8 MiB 不可压缩负载保证服务端在
   断开时确定处于发送中（socket 背压），使“发送中途取消”成为确定性前置而非竞态。
3. **第 4 步“第二次成功后才释放”的编排**：取消时的首次 unlink 失败 → 第一次
   `run_due` 重试失败（服务侧由此记录 `last_error_type == "PermissionError"`，
   工作包诊断边界内的异常类型字段）→ 第二次 `run_due` 成功后释放。比原文单次
   失败/成功两分法多一次受控重试，以便在服务诊断里可观察地断言错误类型。
4. **第 2 步的“不得误判泄漏”守卫**：以 unlink 门闩（测试内 monkeypatch
   `os.unlink` 仅对归档路径抛 PermissionError）使屏障期内 cleanup 在物理上不可能
   完成，从而“第二 job 尚不接受”与“cleanup 已归零后合法获准”两个分支在测试内
   先后确定性地各自成立，不依赖时序。
5. **无产品缺陷暴露**：五步全部一次通过（仅测试自身两处断言时序/比较修正），
   未发现需要停止断言组的产品缺陷。

## 独占测量矩阵的建议后续

- 按“独占测量矩阵”节把取消/清理场景并入专用 W5 probe（与功能单测分离）：
  每轮新建临时运行域、随机 archive 名、结束时记录 hash 而非路径；原始响应校验
  status、正文与 ZIP member digest。
- 慢读取消场景（≥192 MiB 可验证源、读约 1 MiB 后断开）应采样 abort bytes/window、
  FD/临时 ZIP 数、budget snapshot、cleanup pending、RSS/lag，并通过同对象完整重试
  的 SHA-256 一致性闭环——本次的功能测试只固定合同，不固化任何单次数字为 SLA。
- ZIP 并发饱和行（`max_jobs=1`、一 job 卡在 prepare、第二请求 503/Retry-After、
  budget 前中后快照、quota 不消费）本次已在功能层覆盖其断言骨架，probe 侧可直接
  复用本文件的门闩/时钟注入手法。
- 清理 OS 失败行建议增加 close 失败与 cleanup executor 拒绝注入两个分支的 probe
  采样（当前功能测试覆盖 unlink PermissionError 与 identity 改变两支）。

## 证据文件

- `docs/reports/week-closeout-2026-09-08-evidence/n3-zip-ownership.xml`（junitxml，15 项）
- `docs/reports/week-closeout-2026-09-08-evidence/n3-zip-ownership-output.txt`（pytest 输出）
- 本摘要文件
