# N3 LAN ZIP、下载与缩略图可靠性工作包（2026-09-14 周）

> 状态：待实施。基线 `817419a`；只使用合成库、loopback LAN 与测试注入，不增加公网 status 字段、路径或异常文本。
> 最近 W5 基线：[w5-results.json](../reports/weekly-recheck-round4-2026-09-08-evidence/w5-results.json) 已记录成功的 100 缩略图、100 下载、20-member ZIP、c8 混合请求和 192 MiB 中断重试。它是一次测量，不替代可重复的资源释放合同。

## 现状和所有者

| 区域 | 责任入口 | 已有合同 |
|---|---|---|
| 下载与 ZIP 编排 | `AssetsManager/lan/routes/downloads.py:100-202,205-370` | 权限、路径、quota、估算、预算 reservation、建 ZIP、TemporaryFileResponse 交接 |
| ZIP 构建/源上限 | `AssetsManager/lan/routes/_helpers.py`、`zip_sources.py` | 后台构建、输出/源容量限制、取消后 future 处理 |
| 临时响应所有权 | `AssetsManager/lan/temporary_file_response.py:18-265` | 打开与 cleanup 串行；请求结束/取消后 close→unlink；失败保留 handle/callback 并排队重试 |
| 延迟清理 | `AssetsManager/lan/zip_cleanup.py:30-140` | 有界 pending 队列、退避、仅计数/时长/异常类型诊断 |
| ZIP 预算 | `AssetsManager/lan/zip_resources.py:46-153` | 全进程 active_jobs/reserved_bytes 引用计数；response 完成前 reservation 不释放 |
| 访客额度 | `AssetsManager/lan/routes/quota.py`、`application/free_download_quota_service.py` | 文件与 ZIP 在 response ready 前消费，失败安全地拒绝（429/503） |
| 缩略图 | `AssetsManager/lan/routes/thumbnails.py:91-300`、`application/thumbnail_service.py` | 路径/权限、最终源校验、64 MiB 源限制、blur 二次检查、cache/ETag 与 route telemetry |

现有相关覆盖：`test_zip_cleanup_integration.py`（worker cancellation/释放）、`test_zip_response_cleanup.py`（prepare/cookie/quota/cancel 故障）、`test_zip_budget_routes.py` 与 `test_zip_budget_http.py`（预算/队列/response 交接）、`test_zip_cleanup_*`、`test_free_download_quota.py`，以及 `test_thumbnail_admission.py`、`test_thumbnail_snapshot_consistency.py`。下一步应复用这些 harness，不复制 HTTP 伪造器。

## 第一可实施测试：取消后的 ZIP 所有权闭环

在 `tests/lan/test_zip_response_cleanup.py` 或已有 `test_zip_cleanup_integration.py` 中，使用 app 注入的 `ZipResourceBudget(max_jobs=1)`、可控 `ZipCleanupService(start_worker=False, clock=...)`、临时 ZIP 路径和受控 `TemporaryFileResponse.prepare`：

1. 发起真实 batch ZIP，阻塞在开始发送后读取一小段，再取消客户端 task/断开 transport。
2. 在 cleanup 屏障仍持有 response owner/reservation 时，断言第二个 job 尚不接受；不以 HTTP handler 返回即认为释放。若 cleanup 已完成并将计数归零，第二 job 合法获准，不能误判为泄漏。
3. 驱动 cleanup retry clock：断言 ZIP 路径消失、owner handle 关闭、budget snapshot 回到 `active_jobs=0,reserved_bytes=0`，第二 job 可获准。
4. 对 `os.unlink` 首次抛 `PermissionError`：断言文件仍在、reservation 未释放、cleanup snapshot 增加 pending/retry、`last_error_type == "PermissionError"`；第二次成功后才释放并允许下一 job。
5. 对 identity 改变：断言重试绝不删除替换后的同路径文件，保留 `IdentityChangedError` 诊断和未完成所有权，避免“清理成功”假通过。

测试记录只读取私有对象或现有 admin-only `/api/stats` 的聚合 zip_resources；不得为了断言而新增对匿名/公网响应可见的状态、路径、文件名或错误消息。`dto.py:353-432` 的安全字段边界（计数、时长、异常类型）保持不变。

## 独占测量矩阵

测量由专用 probe/harness 执行，和功能单测分开；每轮新建临时运行域、archive 名随机、结束后记录 hash 而非路径。原始响应必须校验 status、正文及 ZIP member digest。

| 场景 | 负载和控制点 | 采样字段 | 通过条件 |
|---|---|---|---|
| c1 基线 | 100 thumbnail、100 file download、20-member ZIP | wall、p50/p95/max、RSS peak、client/server loop lag、成功/正文数 | 全部成功；ZIP members/digest 正确；无残留 temp/预算 |
| c8 混合 | 48 个 thumb/download，固定 semaphore=8 | issued→first-byte、first-byte→body、queue wait、wall、每类状态 | 每条成功且不把 semaphore 等待从容量结果中隐去 |
| 慢读取消 | >=192 MiB 可验证源；读约 1 MiB 后断开 | abort bytes/window、FD/临时 ZIP 数、budget、cleanup pending、RSS/lag | 同对象完整重试 SHA-256 一致；资源最终回归基线容差 |
| ZIP 并发饱和 | `max_jobs=1`，一 job 卡在 prepare，第二请求 | 503/Retry-After、budget 前中后快照、quota 是否消费 | 第二请求不建 ZIP且不消费额度；首个完成后才放行 |
| 清理 OS 失败 | unlink/close/cleanup executor 拒绝注入 | pending/retries/oldest/error type、reservation、替换文件 digest | 安全重试；不删替换文件；无路径泄露；最终成功后仅释放一次 |
| thumbnail 变化/压力 | cache miss/hit、blur policy 翻转、64 MiB 临界/超限 | status/content-type/cache headers、bytes、lag、RSS | 绝不返回旧未模糊正文；超限失败不污染 cache/预算 |
| quota 竞争 | 同 anonymous cookie 与 authenticated principal 并发下载 | allowed/429/503、quota headers、身份 cookie（不记 token） | 成功次数不超限；拒绝/服务故障不误记消费 |

## 实施顺序与完成判据

1. 先完成“取消后的 ZIP 所有权闭环”测试及 OS unlink/identity 两个故障分支；保留既有 response cleanup/预算测试的断言，不以替换方式弱化它们。
2. 补 ZIP 饱和与 quota 消费时序的 HTTP harness 测试，再补 thumbnail 变化/容量边界测试。
3. 最后扩展独占 W5 probe，采集表中字段并归档 JSON、commit、依赖版本和响应 digest 摘要；不将单次数字固化为产品 SLA。
4. 通过条件是：取消、建包失败、quota 拒绝和 OS 清理失败均不泄露预算/临时文件/额度；成功传输内容正确；现有隐私与权限头合同不回退。
