# AssetManager 架构可靠性长期任务（2026-08-31）

> 状态：H0 已实施并通过定向门禁；H1 正在实施（导入预算/源安全、v43 行式 manifest、recovery ACK、v44 持久 transition outbox、v45 poison-row 隔离、v46 暂态投递失败的持久退避、唯一 canonical manifest durable consumer / ACK 后 observer 契约、有界 delivery-lease heartbeat、默认八次普通失败 dead-letter，以及人工 replay/retention/metrics 已落地；仍有完整跨进程故障注入待收敛）。当前没有第二个生产 durable consumer，per-consumer receipt/inbox 明确延后至真实需求出现时；H2 已有 MCP 请求边界的安全切片，完整 LAN/WebUI 契约仍待推进；H3 为后续规划。来源：本次源码勘察与数据库、生命周期、导入恢复、LAN 安全、MCP、ZIP 传输、Windows 文件快照、WebUI 实时、任务治理专家审查。
> 本文只描述当前工作树可观察到的风险和建议，不替代实现验收；当前工作树存在其他未提交改动。

## 0. 长期目标

把项目收敛为“桌面即服务器”的本地优先资产库：同一个 canonical `LibraryRuntime` 服务桌面端与 LAN/WebUI，数据事实以文件系统 + SQLite 为准，所有长任务可取消、可恢复、可观测，所有远程入口有明确的认证、能力和传输安全边界。

长期不变量：

1. 关闭中的 runtime 不再接受新操作；in-flight 操作排空前不销毁其依赖。
2. 事实数据提交、幂等记录和 projection/revision 的关系可追踪；失败不会伪装成成功。
3. 文件路径永不单独代表资产身份；导入、恢复、派生物都抵抗链接、竞态和中断。
4. WebSocket 只负责缓存失效提示，不冒充持久审计日志；协议可校验、可恢复、可观测。
5. 新功能必须同时交付消费端、测试和文档；未接入的 schema/descriptor 不得被当作产品能力。

## 1. 证据与风险登记

| 优先级 | 问题 | 证据 | 影响 | 完成判据 |
|---|---|---|---|---|
| P0 | 永久删除调用不存在的 `CommandExecutionStore.plan_hash` | [command_executions.py](../../AssetsManager/application/command_executions.py:40)、[_actions.py](../../AssetsManager/panels/file_list/_actions.py:486) | 桌面删除在执行前 `AttributeError` | 桌面删除冒烟、异常和重复提交测试通过 |
| P0/P1 | event router 超时仍标记 drained；runtime 先 drain 后变更状态 | [runtime_events.py](../../AssetsManager/application/runtime_events.py:350)、[runtime.py](../../AssetsManager/application/runtime.py:90) | callback 与 DB teardown 竞态、deferred cleanup 丢失 | 阻塞 callback、重复 close、close retry 均无 use-after-close |
| P1 | v42 required-object 检查遗漏 `command_executions` | [db_migrations.py](../../AssetsManager/core/db_migrations.py:1497) | 损坏库静默失去去重 | 缺表/索引在 reopen/migrate 阶段明确失败 |
| P1 | command claim 为 SELECT→UPSERT，跨进程非原子 | [command_executions.py](../../AssetsManager/application/command_executions.py:69) | 同一破坏性命令可能并发执行 | 双连接/多进程只产生一个 owner |
| P1 | 部分删除仍写 `succeeded` | [file_operation_service.py](../../AssetsManager/application/file_operation_service.py:968)、[_actions.py](../../AssetsManager/panels/file_list/_actions.py:525) | 失败目标被永久 dedup，无法重试 | `partial/failed` 可见且失败目标可重试 |
| P1 | 导入无预算且直接文件源未统一拒绝链接 | [import_service.py](../../AssetsManager/application/import_service.py:138) | 内存峰值、越界读取、TOCTOU | 数量/深度/字节预算和 symlink/reparse/竞态测试通过 |
| P1 | manifest 入队后过早标记 recovery completed | [import_manifest_store.py](../../AssetsManager/application/import_manifest_store.py:637) | 队列丢失后恢复意图不可追溯 | 只有 rescan ACK 才进入 terminal |
| P0/P1 | v44 outbox 将 listener 的“正常返回”视作依赖状态已经持久化 | [reconciliation_queue.py](../../AssetsManager/application/reconciliation_queue.py:888)、[import_manifest_store.py](../../AssetsManager/application/import_manifest_store.py:1903) | manifest 写入失败可被静默 ACK；跨进程 at-least-once 退化为“回调曾被调用” | 显式 `APPLIED/STALE/RETRY` disposition；DB 故障后未 ACK 且自动回放 |
| P1 | 派生物先写文件后写 DB，清理错误被吞 | [derivatives.py](../../AssetsManager/application/media/derivatives.py:235) | orphan/stale payload 长期堆积 | pending/ready 状态、启动 GC、错误指标可验证 |
| P1 | 公开分享下载整文件读入内存 | [shares.py](../../AssetsManager/lan/routes/shares.py:318) | 大文件和并发下载耗尽内存 | 分块流式、大小上限和断连清理测试通过 |
| P1/P2 | WebSocket recovery/重连/帧校验与 route policy 有缺口 | [RealtimeContext.tsx](../../webui/src/stores/RealtimeContext.tsx:87)、[useWebSocket.ts](../../webui/src/hooks/useWebSocket.ts:63)、[route_policy.py](../../AssetsManager/lan/route_policy.py:1) | stale 请求、重连尖峰、协议漂移、能力漏配 | schema/能力契约和断档恢复 E2E 通过 |
| P1/P2 | MCP 请求体、执行线程和鉴权策略未形成单一边界 | [mcp_server.py](../../AssetsManager/lan/mcp_server.py:145)、[mcp_server.py](../../AssetsManager/lan/mcp_server.py:206)、[api.py](../../AssetsManager/lan/api.py:252) | chunked body 可绕过 1 MB 预检；搜索阻塞 aiohttp loop；`/mcp` 在 route policy 中标为 public，Bearer、撤销、审计和限流分散 | 受限流读取、worker offload、专用 auth/capability/rate-limit/audit/schema 契约测试通过 |
| P1/P2 | ZIP/分享下载按成员整块读入，只有单请求大小估算 | [_helpers.py](../../AssetsManager/lan/routes/_helpers.py:660)、[downloads.py](../../AssetsManager/lan/routes/downloads.py:23)、[server.py](../../AssetsManager/lan/server.py:104) | 两个 ZIP worker 可同时处理 500 MB 批次，峰值接近 1 GB 以上；估算→打包之间存在增长/替换竞态；临时 ZIP 磁盘无全局预算 | 文件句柄分块写入、并发字节/临时盘配额、取消清理和 entry 上限测试通过 |
| P1/P2 | WebUI recovery 的旧 identity/generation 仍可回写新会话 | [RealtimeContext.tsx](../../webui/src/stores/RealtimeContext.tsx:87)、[RealtimeContext.tsx](../../webui/src/stores/RealtimeContext.tsx:145)、[RealtimeContext.tsx](../../webui/src/stores/RealtimeContext.tsx:221) | 身份切换后旧 promise 的 success/failure 会清除或设置新身份状态并触发 `notify(null)`；旧请求未 abort，造成 stale UI 和无谓流量 | generation+epoch 守卫覆盖 then/catch/finally，切换显式 AbortController，旧请求成功/失败回归测试通过 |
| P1/P2 | 高风险路由的 admission/内容策略与最终快照未绑定同一 identity；Windows 无等价 no-follow open | [image.py](../../AssetsManager/lan/routes/image.py:157)、[shares.py](../../AssetsManager/lan/routes/shares.py:314)、[downloads.py](../../AssetsManager/lan/routes/downloads.py:172)、[file_snapshot.py](../../AssetsManager/core/file_snapshot.py:149) | POSIX final-open 已逐级 `O_NOFOLLOW`，但先前的 `is_file`/`stat`/内容或缓存决策仍可能与最终文件不一致；Windows 只能依赖打开前后 reparse 检查，替换窗口无法原子排除 | admission、内容/权限决策、读取与响应投影绑定同一 fd/identity；Windows reparse/no-follow 策略与对抗替换测试明确通过 |

## 2. 分阶段执行路线

### H0：发布门槛（先做，1 个迭代）

- [x] 修复 `plan_hash` API，并保留永久删除桌面回归测试。
- [x] v42 将 `command_executions` 纳入 required objects；增加缺表、缺索引和二次迁移测试。
- [x] 删除流程只在全量成功时 `succeeded`；部分结果清除 journal 以保持可重试，并保留用户反馈。
- [x] runtime 进入关闭时先原子设置 `CLOSING`；router 超时返回 pending，不得伪造 drained；最后 callback 触发一次 deferred cleanup。
- [x] 建立最小门禁：相关 pytest、桌面删除冒烟、migration corruption test、`python run.py --package-smoke`。

H0 实施证据（2026-08-31）：

- `pytest` 相关单元/集成/桌面/迁移集合：145 passed；新增 router timeout、runtime 状态线性化、journal metadata 和缺表回归。
- `python run.py --package-smoke`：exit code 0；变更文件 `compileall` 与 `ruff check` 均通过。
- 本轮未声称完成跨进程竞争、完整前端构建或 LAN E2E；这些属于 H1/H2 门禁。

### H1：事实与恢复一致性（1–3 个迭代）

> 清单标记：`[x]` 已完成并有门禁，`[~]` 已有安全切片但仍有未完成边界，`[ ]` 尚未实施。

- [ ] 用 SQLite 原子 claim（条件 UPSERT/`BEGIN IMMEDIATE`）替换 SELECT→UPSERT；加入 owner、lease、attempt、started/finished 和错误摘要。
- [ ] 规范化绝对路径、大小写和 Unicode；plan 目标加入 file ID/size/mtime 或内容快照，覆盖“同路径新文件”场景。
- [ ] 明确 journal 的事务所有权，避免内部无条件 `commit()` 提交外层业务事务；实现 `mark_failed` 或移除死状态。
- [~] 对导入使用流式/分块 manifest，增加文件数、深度、单文件和总字节预算；v43 以受限 header + `import_manifest_items` 行表承载大批量 item，旧 v1/v2 JSON 上限保持不变。所有 source 做 lstat/reparse 检查，并在打开后的源/目标自有句柄上复核身份、复制与内容校验。Windows 需给出可验证的 reparse/no-follow 打开策略，不能仅依赖路径的前后检查。
- [~] 将 recovery 状态改为 `enqueued -> running -> reconciled`，持久化 operation/task id；队列失败进入可见的 recovery_pending/dead-letter。`_enqueue_index_rescan()` 现已返回并绑定真实 task id，覆盖 enqueue→bind 崩溃窗口的补偿绑定、worker ACK 丢失后的重启扫描、stale lease 和多 operation 合并的基本路径；terminal/cancelled/evicted 已统一回写。v44 将 queue transition 与持久 outbox 放进同一事务；唯一 canonical `import_manifest_recovery` consumer 必须显式返回 `APPLIED/STALE/RETRY`，而通用 listener 作为 ACK 后的非阻塞 observer；v45 隔离不可安全解码的 immutable outbox 行并收紧 snapshot 身份/scope；v46 以持久 not-before deadline 抑制 canonical consumer 的暂态失败热重放。SQLite delivery lease 在 callback 期间以 token-CAS heartbeat 续期，默认 300 秒 callback age 后停止续期并拒绝其迟到 ACK；v45 表存在时普通失败默认第八次会以原子 dead-letter 终态隔离，v44 保持 retry 以避免无证删除。应用层已补普通 delivery dead-letter 的人工 replay、retention/prune 与 age/attempt/dead-letter metrics；当前没有第二个生产 durable consumer，因此不引入 receipt/inbox；出现第二个独立 projection 时才实现 `(event_id, consumer_id)` receipt、registry、历史和 retention。仍缺完整故障注入。
- [~] 收紧 recovery task 身份校验：`mark_recovery_running`/`acknowledge_recovery` 对非 terminal manifest 不再接受未绑定 task，ACK 前及 queue 终态回写均校验 operation、library、path、kind；dead-letter/cancelled 提供 CAS 型人工重试入口和旧 task 事件隔离；仍需 task event sequence/phase graph、recovery epoch/nonce 与完整跨进程故障注入证据。
- [ ] 派生物采用 temp + fsync + atomic rename 与 `pending -> ready`；启动/定期扫描 orphan、stale pending 和缺失 payload。
- [ ] 备份/恢复校验移到可取消后台 operation，提供 phase、进度、deadline、quick_check 耗时和失败 marker。

### H2：边界与契约（2–4 个迭代）

- [ ] 分享、单文件下载和预览读取改为受保护的分块流式响应；将 path admission、内容门禁、权限/缓存决策、读取和响应投影绑定到同一个 owned handle/identity，避免 `is_file`/`stat`/再次按路径读取之间的语义错配。Windows reparse point 的威胁模型、可验证 no-follow 打开策略和发布门槛必须明确；POSIX 继续复用逐级 `openat`/`O_NOFOLLOW` 的安全路径。
- [ ] ZIP 使用文件句柄分块写入（不得对每个 archive member `read_safe_file` 后 `writestr`）；为单任务设置 entry/解压前字节/内存预算，为整个 LAN 实例设置并发源字节、临时 ZIP 磁盘和 worker 预算。估算与实际打包均重新检查 identity；取消、断连、异常和停服后临时文件、worker 与配额都能收敛。
- [~] MCP 使用受限流的请求体读取（即使 `Content-Length` 缺失的 chunked 请求也最多读取 `MAX_BODY_BYTES + 1`）；所有可能阻塞的服务调用都移出 aiohttp loop。以专用 MCP/integration policy 统一 token rotation/revocation、capability、审计和专用限流，不把 handler 内 Bearer 检查与 `auth="public"` route policy 作为两套 authority；对 `params.arguments` 按 tool schema 做严格 mapping/type/range 校验。
- [ ] 非 loopback 暴露默认要求 TLS 或显式风险确认；修正 TLS URL、guest bootstrap、分享密码锁定和 WebSocket re-auth 的事件循环阻塞。
- [ ] route policy 覆盖 `/ws` 的 `realtime` capability；用 OpenAPI/JSON Schema（或等价生成物）统一 Python DTO、TypeScript 类型、错误结构和能力声明。
- [ ] WebSocket envelope 增加版本和严格 schema；identity/卸载时 abort 旧 recovery，并让每个 `then`/`catch`/`finally` 的状态写入、`notify`、引用清理同时匹配 generation 与 cursor epoch。timeout 使用可区分的 `TimeoutError`，重连加入 jitter 和离线感知。
- [ ] provider 级合并 gap recovery，限制一次事件造成的 query fan-out；API `Retry-After` 设置上限，query key 使用稳定序列化。
- [ ] 增加 Playwright/LAN contract 流程：登录→浏览→另一客户端修改→失效刷新；丢事件→`/api/revision` 恢复；登出时旧 socket/请求不得回写。补充旧 recovery 在身份切换后成功、失败、超时三种情况，均不得改写新身份的 cursor、`recoveryFailed` 或发出 `notify(null)`。

### H3：规模化任务平台（触发式，4 个月以后）

- [ ] 先定义统一 operation record：`operation_id`、kind/phase、runtime_epoch、processed/total/bytes、attempt/lease、last_error、result_summary。
- [ ] 将 Gallery、ReconciliationQueue、导入、派生和 AI tagging 逐步迁移到 JobRunner：有界并发、取消、重试、dead-letter、优雅 drain、资源配额和持久 lease。
- [ ] AI tagging 改为批量事务/聚合事件，记录模型、提示版本、置信度，并分离“模型建议”和“用户确认”。
- [ ] 仅在容量仪表显示触发信号后再考虑读连接池、revision log、watcher/FTS 分片和缩略图容量策略；v44 outbox 的可靠性交付先在 H1 收敛，没有触发信号不做大规模基础设施重写。

## 3. 验证矩阵与可观测性

### H1 当前增量（2026-08-31）

已实施并通过定向门禁：

- `ImportBudget`/`ImportLimits`：文件数、总字节、单文件字节和目录深度的扫描预算；复制阶段使用实际读取预算，源文件在扫描后增长时会停止、清理部分目标并保留后续 manifest 项待重试。
- 导入源边界：直接/嵌套 symlink、Windows reparse 和特殊文件拒绝；lstat/fstat 身份复核；POSIX 最终父目录使用 pinned dirfd、`O_NOFOLLOW` 和 `O_EXCL`；目标内容校验复用 owned descriptor。
- manifest recovery ACK gating：真实 reconciliation task 入队后保持 `recovery_pending`，worker 成功且匹配 task id 后才 ACK 为 terminal；启动阶段可对已成功任务做补偿 ACK；旧 fake queue 保留兼容分支。
- manifest recovery 在检查已绑定 task 前主动刷新持久队列快照；刷新失败只保留 pending，不伪造 ACK。新增 stale-snapshot 回归测试，覆盖 active task 复用及 durable succeeded task 原绑定 ACK。
- replay 路径接入相同的 fingerprint/copy-time 文件与总字节预算；超过上限时清理当前目标、停止后续项并保留其 manifest 状态为 `pending`，新增回归测试。
- 指纹策略改为逐项 fail-closed：有 manifest 存储时无法生成 fingerprint 的 source 以 v2 `failed` item 持久化并跳过复制，兄弟项继续按 v2 指纹校验导入；不再让整批隐式降级为 v1。对应回归测试已加入。
- v43 行式 manifest：`create_stream` 在单个事务内分批写入 `import_manifest_items`，父表仅保存有界 header；`iter_items`/`has_pending_items` 避免 replay 一次性物化大 payload；单 item 更新采用父 generation CAS + 子行更新，并校验行数、连续索引、元数据字节数和 identity checksum。旧 v1/v2 API 和 payload 上限保持兼容。
- recovery enqueue 现在返回 `RecoveryEnqueueOutcome` 并在有真实 task id 时绑定 manifest；worker 的 running/ACK 回调会补偿 enqueue→bind 窗口，并拒绝 operation、library、path 或 kind 不匹配的任务。同步旧队列仍保留兼容分支。
- queue→manifest 终态回写已补一层可复用的安全切片：`ReconciliationTaskTransition(previous,current,reason,operation_ids)` 在 queue durable mutation 提交后、释放 queue 锁后派发；覆盖 enqueue、claim、retryable、succeeded、terminal、cancelled、lease-expired，以及 SQLite 容量 eviction。SQLite claim 返回同一事务内恢复的 expired rows，enqueue 返回被替换/淘汰的完整 task 元数据，避免 listener 只能看到本地快照而丢失 operation scope。
- `ImportManifestRecoveryService.handle_task_transition()` 对合并 task 的 operation id 逐项做 CAS 和 library/path/kind 校验；成功 ACK 保留绑定 task id 且重复事件幂等，retryable 保持 `recovery_pending`，terminal/cancelled 写入可见的 `dead_letter`/`cancelled` phase，evicted 清除绑定并允许后续恢复重新入队。listener 失败不会回滚已提交 queue 状态，启动恢复仍可补偿。
- durable outbox 的完成条件已收敛到唯一 `import_manifest_recovery` consumer：它必须显式返回 `APPLIED`、`STALE` 或 `RETRY`，前两者才会 token-CAS ACK；构造参数与 `set_transition_listener()`/`add_transition_listener()` 形成的通用 listener 都是 observer，事件 ACK 后通知，异常仅进入本地 advisory backlog，不能造成 durable retry、队首阻塞或重复 manifest 写入。未注册 canonical consumer 时 SQLite outbox 不 claim、不 ACK。内存/旧 adapter 保持兼容 listener 派发。
- 验证结果：`tests/unit/test_import_manifest_store.py` + `tests/integration/test_import_service.py` 为 `71 passed, 3 skipped`；v43 迁移/历史门禁为 `95 passed`；恢复进程门禁（未包含旧的“入队即完成”断言）和 v3 专项测试另行执行。相关 `pyright`、`ruff`、`compileall` 均通过；`python run.py --package-smoke` exit code 0。Windows symlink 测试因当前进程无创建链接权限而 skip，不等同于覆盖完成。
- 本轮 transition 增量定向门禁：queue memory/SQLite 与 manifest store 合计 `62 passed`（含终态 listener、eviction、重复 succeeded 幂等和 dead-letter 不自动重排）；这只是状态回写切片证据，尚不构成 H1 完成。

### H1 复核增量（2026-09-01）

- 修复 transition scope 边界：`ImportManifestRecoveryService` 只信任 `current.operation_ids ∪ previous.operation_ids`，事件 envelope 中额外注入的 operation id 会被忽略；新增伪造 scope 与旧 attempt 乱序回归测试。
- 加强 listener 失败交付：失败回调按 listener 维度保留、在下一次 queue mutation 或显式 `retry_transition_backlog()` 时重试；重复 task 事件合并，超过有界 backlog 时记录 `transition_backlog_overflow_count` 并写日志，不再静默丢失。`ImportManifestRecoveryService.recover()` 会主动触发 backlog 重试。
- 启动冲突安全：SQLite queue startup recovery 发生 generation 冲突时清除本地旧 `startup_recovered` 事件，避免向 manifest 回写已被其他进程接管的 stale lease transition。
- 新增/复核门禁：queue + manifest unit `45 passed`；reconciliation cross-process/lifecycle 子集 `16 passed`；导入集成排除旧“入队即 completed”断言后 `47 passed, 3 skipped`；核心定向静态门禁 `ruff`、`compileall`、`pyright`、`python run.py --package-smoke` 均通过。
- 仍保留的证据缺口：优雅关闭不会主动释放 running lease，重开后可能需等待 lease expiry；恢复进程门禁中 3 个旧测试仍将 enqueue acceptance 当作 completed（另有一项 clean-import 旧断言），应改为显式 worker durable success ACK 或明确等待 lease/worker，而不是回退 ACK-gated 语义。

### H1 人工重试增量（2026-09-01）

- `ImportManifestStore.request_recovery_retry(operation_id)` 只接受带有已绑定 task id 的 `dead_letter`/`cancelled` manifest，使用 generation CAS 清除活跃绑定和 claim，记录重试时间、次数、被替代 task id，并保留最多 16 个 retired task id 的审计集合。
- `ImportManifestRecoveryService.retry_dead_letter(operation_id)` 先尝试该 CAS；若 queue 已 durable terminal/cancelled 但 listener 回写丢失，会从刷新后的持久 queue snapshot 补写终态后再重试。CAS 成功后复用正常 `recover()` 调度，enqueue 失败仍将 manifest 保留为可见 `pending` 并记录错误，而不伪造完成。
- 延迟到达的 retired task transition 在新任务绑定前后均是幂等 no-op，不得重新绑定、dead-letter 或 ACK 新 attempt；重复人工操作和双连接竞争最多接受一次 retry request。
- 门禁：`tests/unit/test_reconciliation_queue.py`、`tests/unit/test_reconciliation_queue_sqlite_store.py`、`tests/unit/test_import_manifest_store.py` 共 `71 passed`；导入集成（排除旧 enqueue 即完成断言）`47 passed, 3 skipped, 1 deselected`；变更文件 `ruff check` 和 `pyright` 均通过。Windows 链接用例仍因当前进程无创建链接权限而跳过。

### H1 v44-v46 持久 transition outbox 复核（2026-09-01）

已落地的基础能力：

- v44 新增 `reconciliation_transition_outbox`、schema contract、v43→v44 升级和缺表拒绝门禁；queue mutation 与 outbox append 位于同一 SQLite transaction，append 失败会回滚 task mutation。
- `claim_transition_outbox()`、ACK 与 fail 使用 `BEGIN IMMEDIATE` 和 delivery-token CAS；过期 lease 可接管，旧 token 不得 ACK 或释放新 owner。
- claim 严格处理最早未交付的 outbox `id`；队首被其他进程持有有效 lease 时不会跳过，避免后续 transition 越序。listener 在 queue mutation 提交并释放 queue lock 后调用。
- `ReconciliationTransitionDisposition` 已落地：manifest durable consumer 对每个 operation scope 证明已写入时返回 `APPLIED`、已被覆盖/无关时返回 `STALE`、无法证明时返回 `RETRY`；drain 仅 ACK 前两者，后者释放 lease 留待至少一次重放。manifest 数据库故障不再会因 callback 正常返回而错误 ACK。
- `AssetIndexReconciliationService` 已在 production bootstrap 的 runtime 生命周期中启动可停止 sweeper；每 10 秒调用 outbox retry/drain，因此 64 条同步批次后的剩余积压和空闲时的临时 consumer 失败会继续推进。直接嵌入 queue 而不启动该 lifecycle service 的兼容调用方仍须显式 drain。
- v45 新增 `reconciliation_transition_outbox_dead_letters`。只要最早 live row 无法安全解码（坏 JSON、任一 snapshot 的 task id 不匹配、或 `operation_ids` 不等于 snapshots 的确定性并集），claim 会在同一个 `BEGIN IMMEDIATE` transaction 内 CAS lease、复制原始 payload 与 attempts/诊断到 dead-letter、删除 source row，并继续队首扫描；v46 也用同一事务隔离无法判断 live/expired 的损坏 active delivery lease 或 retry deadline。dead-letter 表缺失或 copy/delete 失败时完整回滚，绝不静默丢行或越序。listener 异常、`RETRY` 和 SQLite 暂态错误不属于 poison，仍保留严格顺序和重试语义。
- v46 向 live outbox 追加 `next_delivery_at`。listener 异常、`RETRY` 或非法 disposition 会在 token-CAS 事务内清 lease、记录错误并写入稳定 hash jitter 的 15–300 秒 not-before deadline；jitter 后的最终延迟仍封顶为 300 秒。claim 始终只看最早未投递 id，未到期 deadline 与有效 lease 一样阻塞后续 event，ACK 会清除 deadline。v45/第三方旧 schema 缺该列时保留即时重试兼容行为；外部损坏的 retry 或 active delivery lease deadline 走 v45 原子隔离，不能卡死队首。
- SQLite outbox delivery lease 已新增 token-CAS `renew_transition_outbox_lease()`。drain 在 canonical callback 运行期间每约三分之一 lease 续期（间隔限制在 0.01–5 秒），默认 `callback_max_age=300` 秒；超过 age 后 heartbeat 停止，callback 即使后来返回也会以 timeout 走 retry 而非 ACK，最后一次 lease 到期后另一连接可接管。续租失败同样不 ACK。短租约的慢 callback、deadline 接管与 stale-token 回归已覆盖。
- 普通 delivery failure 现有默认 8 次上限。第八次 token-CAS failure 会调用 v45 dead-letter copy/delete；错误以 `_TransitionOutboxDeliveryAttemptsExhausted` 记录最后一次 consumer 失败，后续 head 可推进。v44 无 dead-letter 表时故意保持 retry，stale token 不能删除新 owner 的 row。
- 本轮新增人工运维切片：`list_transition_outbox_dead_letters()` fail-closed 列出审计死信；`replay_transition_outbox_dead_letter()` 用 event-id 与可选 `expected_dead_lettered_at` CAS 恢复原 event，保留死信审计、历史 attempts，并在后续事件已有 ACK/lease/attempt 或死信时返回 `transition_outbox_replay_order` 冲突；重复恢复为幂等 no-op，恢复后再次失败不会因 event-id 主键冲突而遗留 live lease。`transition_outbox_metrics()` 提供 pending/ACK/dead-letter/lease/过期 lease、attempt 汇总和 oldest age；`prune_transition_outbox()` 用绝对 cutoff 与 bounded limit 仅删除过期 ACK/dead-letter，永不删除 pending/leased 行。旧 v44/v45 schema 继续返回兼容空结果或即时 retry，不新增 v47 DDL。
- 本轮 H1 定向集合：`tests/unit/test_reconciliation_queue_sqlite_store.py` 的 transition-outbox 子集 `35 passed`，queue + SQLite store + manifest store `109 passed`，恢复/导入集成 `71 passed, 3 skipped`，迁移/锁门禁 `101 passed`；`pyright`、`ruff check`、`compileall`、`git diff --check` 和 `python scripts/check_doc_stats.py` 均通过。这些数字只证明定向回归，不等同于 H1 退出。

仍未完成、必须保持 H1 `[~]` 的退出条件：

- 失败和生命周期：v45 dead-letter 表已处理损坏 immutable payload/delivery metadata，以及默认第八次普通 delivery failure；v46 为暂态投递失败持久化 15–300 秒的指数退避与稳定 jitter；人工 replay、retention/prune 和队列年龄/重试/死信指标已有 store/queue API 与定向门禁。仍需把 retention 策略接入正式运维调度，并评估 ACK 后完整 snapshot 的长期存储成本。
- consumer 模型：已明确 `import_manifest_recovery` 为唯一 canonical durable consumer；单个 `delivered_at` 表示该 consumer 已确认，通用 listener 不再参与确认，`None` 也不能作为 durable disposition。没有第二个生产 durable consumer，故不提前构建 receipt/inbox。产品新增独立 durable projection 时，必须先定义 `(event_id, consumer_id)` receipt/inbox、持久 registry、历史起点、consumer 移除与 retention，再允许第二个 consumer 注册。
- 租约：SQLite canonical callback 已有有界 heartbeat 和 callback age，慢回调不再在 lease 内被另一连接抢占；callback 无法被强制取消，因此 deadline 后只停止续租并拒绝迟到 ACK，至多在最后一个 lease window 后触发 at-least-once 重放。仍需真实进程级 crash/replay 注入来覆盖 manifest CAS 后、ACK 前的退出窗口。
- 跨进程证据：已有双进程 manifest claim winner 与 token-lease 测试，但尚未覆盖“worker durable success → outbox delivery → manifest CAS → ACK 前进程退出 → 另一进程重放”的完整链路，也未覆盖 terminal/eviction 合并 task 的多进程故障注入。

下一批验收测试：canonical consumer 已写入但 ACK 前进程退出后的跨进程幂等重放；terminal/eviction 合并 task 的进程级故障注入；正式 retention 调度与告警阈值。只有引入第二个独立 durable projection 后，才补每 consumer receipt/inbox 的历史和独立重放测试。

### H2 早期增量（2026-08-31）

- MCP 请求体在 `Content-Length` 缺失时仍按 `MAX_BODY_BYTES + 1` 分块读取；超限返回 413。
- MCP `tools/call` 参数执行严格 mapping/type/range 校验，非法参数返回 JSON-RPC `-32602`；搜索等潜在阻塞服务调用通过 `asyncio.to_thread` 调度。
- `tests/lan/test_mcp_server.py` 与 route-policy 合计 `15 passed`，MCP 文件 `pyright`、`ruff`、`compileall` 均通过。
- 尚未完成：MCP 专用 capability/auth/revocation/audit/rate-limit 单一策略、route policy 对齐、输出大小预算与完整 LAN contract；因此 H2 不得标记完成。

尚未完成、不得宣称 H1 完成的边界：

- v3 manifest 已解决父表 JSON 的 10,000 项/512 KiB 上限冲突，但 ImportService 当前仍先在内存构造 `files`/`targets`/`fingerprints` 列表；下一步要把规划、指纹和 row iterator 进一步流式化，并为自定义 budget 超过 100,000 item/256 MiB metadata 的情况提供结构化容量失败。
- recovery queue 已有 per-listener failed-delivery backlog、重试和 overflow telemetry 的安全切片，也已提供 dead-letter/cancelled 的显式人工 retry；v44 已补持久 outbox、跨进程 token lease、精确 previous/current snapshot、严格队首顺序、唯一 canonical manifest durable consumer 的 `APPLIED/STALE/RETRY` disposition 与 lifecycle-owned idle sweeper；通用 observer 在 ACK 后隔离执行；v45 已补不可安全解码行的原子 dead-letter、严格 snapshot identity/scope 校验，以及默认八次普通 delivery failure 的 atomic dead-letter；v46 已补暂态 delivery 的持久 not-before backoff、最终 300 秒 cap、损坏 lease/deadline 隔离和有界 callback-age delivery heartbeat；普通 delivery dead-letter 已补人工 replay、retention/prune、指标和顺序/CAS 门禁。仍缺 terminal/eviction 合并 task 的完整跨进程故障注入；per-consumer receipt 仅在出现第二个 durable projection 后进入范围。
- queue refresh 失败仍采取 fail-closed；enqueue→bind kill-window、双进程 claim winner、stale lease 接管、人工 replay 后跨进程重放和 listener 回调失败后的跨进程重启补偿仍需独立进程门禁。当前优雅关闭保留 live lease 是已确认语义；旧 integration 测试中要求“入队即 completed”的 3 项及 clean-import 断言需改成显式 durable success ACK/worker 驱动，不得回退状态机。
- POSIX 中间目录逐级 `openat`/`openat2`、源文件 fd-based no-follow 打开以及 Windows 等价 no-follow 语义仍需完整实现和对抗测试。
- replay 的 fingerprint 与 copy 均受预算约束；manifest 分块、目录数量/扫描时间预算仍待完成。

每个阶段至少提供：

- 单元/集成：迁移、事务边界、CAS/lease、路径规范化、partial result。
- 故障注入：进程在导入复制、manifest 入队、派生写入、restore staging/install/rollback 各点退出。
- 并发：双进程 command claim、不同库并行 open、关闭期间新请求、慢 WebSocket 客户端。
- 边界安全：chunked MCP 大 body、无效 tool arguments、撤销 token、阻塞搜索；直接/嵌套 symlink、Windows reparse、POSIX 目录交换和扫描→读取替换，均不能越界读取或遗留外部产物。
- 资源与取消：两个接近 500 MB 的 ZIP、目录/批次 entry 上限、源文件在估算后增长、客户端断连/任务取消/服务停止；验证 RSS、临时盘、worker 数和残留文件不超过声明配额。
- 前端竞态：旧 identity 的 recovery 在切换后 success/fail/abort，与新 identity 的 recovery 并发时，状态、通知、cursor 和注册消费者始终由当前 generation 拥有。
- 降级：无 `aiohttp`、`rawpy`、`psd-tools`、Ollama 时仍能启动并给出明确能力状态。
- 端到端：桌面永久删除；LAN 认证/分享/下载；WebSocket 断档恢复；登录切换缓存隔离。

建议统一记录 `request_id`、`operation_id`、`runtime_epoch`、`revision`、安全的 library 标识，并监控：writer 等待、队列深度/lease 过期、recovery_pending、orphan 字节、派生/解码失败率、WebSocket gap recovery/abort/stale-drop、关闭超时、MCP body 拒绝/worker 排队/认证拒绝，以及 ZIP 下载的活跃任务、源字节、RSS、临时盘和清理失败。

## 4. 约束、取舍与回滚

- 不因上述问题立即拆微服务或替换 SQLite；先用状态机、原子事务、后台任务和契约测试解决单进程架构的已知边界。
- 不把 command descriptor 的 `required_capabilities`、`approval`、`impact` 当作安全机制；在任何 MCP/自动化/远程 gateway 暴露前必须强制 capability、审批、审计和目标范围。
- 不恢复商城运行时；产品定位以 [0005-commerce-extraction](../adr/0005-commerce-extraction.md:1) 为准，README 和 PyInstaller hiddenimports 单独清理。
- 每个阶段以 feature flag 或小步提交交付；迁移必须 append-only、可重复执行，后台任务必须可暂停/回滚。任何 H1 改动若导致旧库无法打开，先恢复兼容路径，再继续扩展。

### 长线任务执行协议

- **任务状态**：持续推进，当前游标为 H1 的 v46 outbox 持久退避、canonical consumer 契约、有界 delivery lease heartbeat 和最大尝试 dead-letter 之后的人工 replay/保留/指标与跨进程 replay；H0 只作为已通过的回归基线，H2 早期 MCP 切片不视为阶段完成。
- **每轮输入**：先读取本路线图、相关专家报告和上一轮门禁结果；只在当前工作树可观察证据范围内更新状态，不把计划项写成已完成。
- **每轮交付**：至少包含一项可复现实现或测试、对应的风险/回滚说明，以及本文件的验证数字、剩余边界和变更日志更新。
- **推进顺序**：普通 dead-letter 人工 replay/retention/指标已完成，先收敛其正式调度与跨进程 crash-replay 协议；若产品增加第二个独立 durable projection，再以 receipt/inbox 的 registry、历史和 retention 设计作为前置条件。随后收敛 manifest 分块与预算统一、recovery task 状态机和跨进程门禁，再完成 POSIX/Windows safe-open；H2 的统一 MCP 策略、ZIP 资源配额和 WebUI generation/abort 契约必须以后述 H1 门禁为前置条件。
- **暂停条件**：若旧库兼容性、任务身份、路径安全或资源配额的证据不足，保持 `[~]`/`[ ]`，不得用兼容分支或静态检查替代运行时门禁；若发现与现有无关的工作树改动，隔离并保留，不做广泛清理。
- **阶段退出**：只有实现、故障注入、并发/跨平台边界测试、可观测指标和回滚证据齐备，才将对应 `[~]` 改为 `[x]`；总长期任务在 H3 触发信号出现前保持活动状态。

## 5. 当前基线与限制

本计划基于静态源码审查和分阶段验证：H0 相关测试当前 145 passed，`run.py --package-smoke`、变更文件 `compileall` 和 `ruff` 已通过；本轮没有启动交互式桌面/LAN 服务，也没有完成全量 pytest、前端 typecheck/build、PyInstaller 或 Playwright。当前工作树仍有其他未提交改动；后续阶段应记录基线 commit、隔离无关改动，并把每次门禁结果写回本文。

### 变更日志

- 2026-08-31：首次建立；汇总专家团架构、可靠性、安全和实时审查。
- 2026-08-31：完成 H0 发布门槛实现与定向验证；H1–H3 保持活动长期目标。
- 2026-08-31：补充 MCP chunked body/worker/auth、ZIP 内存与临时盘预算、WebUI identity generation/abort，以及 Windows safe-open/文件快照 TOCTOU 的 H1/H2 风险、验收与观测项。
- 2026-08-31：H1 增量落地导入扫描/复制预算、源安全与 manifest recovery ACK gating；新增扫描后增长与 stale queue snapshot 回归测试，并记录分块 manifest、queue terminal callback、跨平台 safe-open 等剩余门禁。
- 2026-08-31：H2 早期增量落地 MCP chunked body 限制、严格工具参数校验和 worker offload；保留统一 auth/capability/审计/限流及 route policy 对齐为后续门禁。
- 2026-08-31：H1 继续收敛 replay copy-time 预算、逐项 fingerprint fail-closed 与 refresh 失败不重绑；定向 H1 门禁更新为 `83 passed, 3 skipped`。
- 2026-08-31：H1 将 fingerprint 读取本身纳入预算；无指纹项以 v2 `failed` 单项记录，兄弟项不再整体降级，定向 H1/H2 门禁为 `98 passed, 3 skipped`。
- 2026-08-31：修正文档以匹配逐项 fingerprint fail-closed 实现；补充 recovery task 身份校验、terminal/cancel/dead-letter 回写和长线任务执行协议，长期 goal 继续保持 active。
- 2026-08-31：新增 v43 `import_manifest_items` 行式 manifest；大批量导入自动选择有界 header + 分批 item rows，replay 改为迭代读取，补充迁移、原子回滚、损坏行和容量选择门禁；recovery enqueue 返回真实 task id 并补偿绑定窗口，长期 goal 继续保持 active。
- 2026-08-31：按恢复状态机专家复核补齐 queue transition listener 的提交后派发、SQLite expired/evicted 元数据传递、逐 operation scope/CAS、终态 dead-letter/cancelled/evicted 回写和重复成功幂等；新增定向回归测试，长期 goal 继续保持 active，H1 仍保持 `[~]`。
- 2026-09-01：复核并修正 transition envelope scope 注入、旧 attempt 乱序与 listener 失败 backlog 重试/溢出可观测；启动 generation 冲突时丢弃本地 stale recovery 事件。新增定向门禁（queue + manifest `45 passed`、reconciliation 子集 `16 passed`、导入集成 `47 passed, 3 skipped`），H1 仍保持 `[~]`，长期 goal 保持 active。
- 2026-09-01：v44 持久 transition outbox 复核确认 transaction append、strict head-of-line claim、token lease CAS 与至少一次 drain 已落地；补记 ACK disposition、自动 dispatcher、毒消息隔离、backoff/dead-letter/retention、consumer identity 和 lease renew 为 H1 退出条件。定向 migration/queue/manifest 集合 `174 passed`，H1 保持 `[~]`。
- 2026-09-01：复核确认 manifest durable consumer 的 `APPLIED/STALE/RETRY` disposition 和 runtime lifecycle-owned idle sweeper 已实施；SQLite manifest 写入故障会保留 outbox，65+ 空闲积压可由 sweeper 排空。H1 剩余焦点收敛为 poison-row isolation、持久 backoff/dead-letter/retention、per-consumer receipt、outbox lease renew 与完整跨进程 worker→manifest crash-replay 门禁；最新相关定向重跑 `65 passed`。
- 2026-09-01：v46 将 transient retry 的最终 jittered delay 固定封顶为 300 秒；专家复核发现并关闭损坏 active delivery lease 可永久阻塞队首的边界，复用 v45 原子隔离路径。H1 定向集合更新为 `215 passed`，H1 仍保持 `[~]`，长期 goal 保持 active。
- 2026-09-01：专家团确认当前生产路径只有 `import_manifest_recovery` 一个 durable consumer。实现将其注册为 canonical consumer，要求显式 `APPLIED/STALE/RETRY`；通用 listener 改为 ACK 后非阻塞 observer，observer 异常不影响 durable ACK、退避或队首顺序。错误 consumer id、冲突 callback 与 `None` disposition 均被拒绝/保留 pending。未增加 v47 receipt/inbox，因为尚无第二个独立 durable projection。H1 定向集合更新为 `218 passed`，H1 仍保持 `[~]`，长期 goal 保持 active。
- 2026-09-01：SQLite outbox 新增 delivery-token CAS lease heartbeat。canonical callback 执行期间按约三分之一 lease 续期，默认 300 秒 callback age 后停止续期；迟到 callback 不再 ACK，最后一个 lease window 后允许另一连接 at-least-once 接管。新增 current-token、慢 callback 和 callback-age takeover 回归；H1 定向集合更新为 `221 passed`，H1 仍保持 `[~]`，长期 goal 保持 active。
- 2026-09-01：普通 durable delivery 默认第八次失败时复用 v45 dead-letter 的 token-CAS copy/delete 事务；保留原始 snapshots、attempts 和最后一次错误，并解除后续 head。v44 无 dead-letter 表仍保持 retry，stale token 不能删除新 owner。人工 replay、retention 和指标仍在范围内。新增三项回归后 H1 定向集合更新为 `224 passed`，H1 仍保持 `[~]`，长期 goal 保持 active。
- 2026-09-01：完成普通 delivery dead-letter 运维切片：新增 fail-closed 列表、event-id/CAS 人工 replay、顺序保护、历史 attempts 保留、重复 replay 幂等、ACK/dead-letter bounded retention/prune，以及 pending/ACK/dead-letter/lease/attempt/age metrics；补充 replay 后再次死信和 pending/leased 不误删回归。定向 outbox 子集 `35 passed`，queue + SQLite store + manifest store `109 passed`，恢复/导入集成 `71 passed, 3 skipped`，迁移/锁门禁 `101 passed`；H1 仍保持 `[~]`，剩余完整进程级 crash-replay 与 terminal/eviction 故障注入。
