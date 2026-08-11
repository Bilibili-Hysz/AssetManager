# 模块排 Bug 清单（module-runtime.md · 2026-08-10 P0 第1轮）

> 来源: 只读探索代理审计，行号经源码核对。修复前需第二子代理复核真实性。


# M8 Runtime/事件/对账/启动链路 深度缺陷审计清单（2026-08-10）

> 只读审计（explore 子代理），范围 12 个文件。
> 依据: docs/plans/bug-hunting-2026-08-10.md M8 任务卡（C3 分组）。
> 严重度: 高/中/低。所有行号均以本仓库当前版本为准。

## Bug 1 - 关闭失败回滚把 Runtime 置回 "open"，与已关闭的事件路由形成半开状态
- 位置: AssetsManager/application/runtime.py:118-125（close_adapters 异常回滚）与 runtime.py:153-159（_cleanup_adapters 异常回滚）
- 严重度: 中
- 描述: `mark_closing()`/`close()` 都会先执行 `event_router.close()`（runtime.py:92、143），随后才停适配器。若任一 `adapter.stop()` 抛异常，两个回滚分支都把 `self._state` 重置为 `"open"`，但事件路由已永久关闭、`_accepting=False` 且已从全局 bus 退订。结果：`is_open` 误报 True；`next_revision()` 继续成功推进（状态为 open），但不会有任何事件送达（路由已死）；`runtime_for()`（bootstrap.py:336-339）会把该 runtime 当作可用返回给 UI；此时还能注册新的 lifecycle adapter（register_lifecycle_adapter 只检查 state=="open"），但这些 adapter 只能在下次重试时被停止。
- 触发/复现: 任一 lifecycle adapter（integrity/maintenance/reconciliation service）的 `stop()` 抛异常（例如 reconciliation worker 未在超时内停止 → ReconciliationWorkerStopTimeout），随后观察 `is_open` 为 True 但 router.closed 为 True。
- 修复建议: 回滚时区分"从未关闭过路由"与"路由已关闭"两种情形；路由已关闭时 `_state` 应回滚到 "closing" 而非 "open"，或在 `_state` 之外单独维护 router 活性标志。

## Bug 2 - close() 在回调线程且清理进行中时静默丢弃关闭请求
- 位置: AssetsManager/application/runtime.py:136-139
- 严重度: 低
- 描述: `while self._cleanup_in_progress: if callback_thread: return` — 若当前线程正处于事件回调中且另一线程正在执行 `_cleanup_adapters`，`close()` 直接 return，本次关闭请求被静默丢弃，且此路径下 `event_router.close()`（143 行）不会执行。虽然 `_cleanup_session`（bootstrap.py:596-605）最终会因 `cleanup_complete=False` 抛 RuntimeError 让调用方重试，但任何不检查返回值/异常的 close() 调用方会以为关闭已完成。
- 触发/复现: 在事件回调（如 FileSystemChanged 处理）中调用 `session.close()`，同时另一个线程正在清理该 runtime。
- 修复建议: 改为 `defer_after_drain` 把"继续关闭"挂到 drain 之后，而不是直接 return；或在返回值/异常中显式表达"close 被推迟"。

## Bug 3 - _dispatch_event 中 next_revision() 未捕获，关闭竞态下异常冒泡到全局 bus
- 位置: AssetsManager/application/runtime_events.py:231
- 严重度: 低
- 描述: `revision = self.runtime.next_revision()` 不在任何 try 内。竞态窗口：事件已在 `_on_event` 通过 `_accepting` 检查（在途），随后 `mark_closing()` 把 state 置为 "closing" → `next_revision()` 抛 RuntimeError → 异常从 `_dispatch_event` 冒出、`_on_event` 的 finally 只做计数回退，异常继续冒到 `EventBus.publish` 被吞并打 "Event handler failed" 日志（event_bus.py:114-117）。结果是关闭期间在途事件被静默丢弃且产生误导性日志。
- 触发/复现: 事件发布线程与 `mark_closing()` 并发（会话关闭过程中恰好有 FileSystemChanged 在途）。
- 修复建议: 在 `_dispatch_event` 内捕获 RuntimeError（或先检查 `runtime.is_open`），关闭期直接丢弃并打 debug 日志，避免依赖 bus 兜底。

## Bug 4 - 单个路径规范化失败导致整个失效事件被丢弃
- 位置: AssetsManager/application/runtime_events.py:141-151（_normalize_path）与 165-171（_paths_for 聚合）
- 严重度: 低
- 描述: `_paths_for` 中任一 raw 路径 `_normalize_path` 返回 None（resolve 抛 OSError/RuntimeError/ValueError，或路径在 library root 之外）→ 整个 `paths` 返回 None → `_dispatch_event` 直接 return（229-230 行），该事件的 FILES/TREE/HOME 等所有域投影都不刷新。一个坏路径连坐全部投影。
- 触发/复现: 事件 paths 中混入库外路径（如收藏了库外文件触发的 FavoritesChanged）或不可解析路径。
- 修复建议: 逐路径跳过坏项，而不是整体丢弃；至少对"部分失败"单独记录日志。

## Bug 5 - _RouterSubscription.close() 等待在途回调无超时
- 位置: AssetsManager/application/runtime_events.py:76-77
- 严重度: 低
- 描述: `while self._inflight > own_callbacks: self._router._drain_condition.wait()` — 若订阅者回调在另一线程长期阻塞（如 LAN 广播、DB 慢查询），调用 `close()` 的线程（可能是 Qt 主线程，见 panels/_event_bridge.py:49-57）会无限期阻塞。
- 触发/复现: 订阅者回调阻塞 + UI 线程关闭订阅。
- 修复建议: 增加超时并在超时后标记"残留 inflight"由路由关闭兜底。

## Bug 6 - 队列启动恢复持久化遇跨进程 generation 冲突直接抛异常，阻断库打开
- 位置: AssetsManager/application/reconciliation_queue.py:341-345（__init__ 内恢复持久化无容错）与 1211-1223（_persist_unlocked 冲突刷新后仍 re-raise）
- 严重度: 中
- 描述: `ReconciliationQueue.__init__` 先 `_load()` 再 `_recover_expired_running_unlocked`，若有恢复项则调用 `_persist_and_notify_unlocked()` → `store.replace(..., expected_generation=self._generation)`。若另一进程已推进 generation（两实例同时启动，各自恢复过期租约），CAS 失败 → `_persist_unlocked` 刷新内存快照后仍 re-raise `ReconciliationQueuePersistenceConflict` → 构造失败 → `_build_services`（bootstrap.py:468-474）失败 → 整个库无法打开。而队列其余操作（enqueue/claim 等）均通过 `_refresh_after_persistence_conflict_unlocked` + 调用方重试处理冲突，唯独启动路径没有。
- 触发/复现: 同一库目录被两个进程同时打开，且都存在过期 RUNNING 任务。
- 修复建议: `__init__` 恢复持久化捕获冲突：刷新快照后视为成功（内存状态已一致），不 re-raise；或在 bootstrap 层对该冲突重试。

## Bug 7 - wait_for_ready 使用调用方传入的 now，过期时钟导致到期任务延迟一轮
- 位置: AssetsManager/application/reconciliation_queue.py:424（`current_now = now`）与 430-431（is_due(current_now) 判断）
- 严重度: 低
- 描述: 循环首轮用调用方传入的 `now`（worker 在进入 wait_for_ready 前取钟，可能已过期数百 ms），首轮 `is_due` 判断可能把已到期任务判为未到期，需等一轮 condition 唤醒 + 刷新后才处理。
- 触发/复现: worker 在 `now=self._clock()` 之后、wait_for_ready 之前发生一次较长的 DB 读。
- 修复建议: 循环首轮即用 `self._clock()` 刷新 current_now。

## Bug 8 - 管理员无法终止 RUNNING 任务（无 lease token 的管理操作被拒）
- 位置: AssetsManager/application/reconciliation_queue_store.py:803-807（_mark_nonretryable）
- 严重度: 低
- 描述: `expected_attempts=None`（管理路径）且任务处于 RUNNING 时直接抛 `ReconciliationQueuePersistenceConflict("Running reconciliation task requires attempt CAS")`；内存路径 reconciliation_queue.py:1328-1336 相同。管理员 cancel/terminal 一个正在运行的任务只能等 lease 过期（最长 lease_seconds 默认 30s）。
- 触发/复现: 用户在任务 RUNNING 期间点击取消（若 UI 走管理路径）。
- 修复建议: 管理终止 RUNNING 任务应有独立语义（如强行置 TERMINAL 并使 worker 后续 mutation 因 lease CAS 失败而失效），或明确文档化为限制。

## Bug 9 - 损坏/不支持的 JSON marker 使迁移抛错，阻断整个库打开
- 位置: AssetsManager/application/reconciliation_queue_migration.py:103-108（读取 marker 失败 → 迁移 raise）→ bootstrap.py:463-467（迁移失败冒泡 → runtime_for 失败）
- 严重度: 中
- 描述: `migrate_reconciliation_marker` 对损坏 JSON / 未知版本（reconciliation_queue.py:1171-1173 抛 ValueError → 包装为 ReconciliationQueuePersistenceError）直接抛错。一个损坏的遗留 marker（用户数据文件）会让整个库无法打开（fail-closed 过严）。同样，marker 存在但 SQLite 已有不同任务快照（`_same_snapshot` 不匹配，migration.py:120-124）也会抛错阻断打开。
- 触发/复现: reconciliation-queue.json 被外部截断/手改；或双进程迁移窗口内 SQLite 已有任务。
- 修复建议: 损坏 marker 降级为"重命名归档 + 日志告警"而非阻断打开；快照冲突时记录并继续（以 SQLite 为准），不再抛错。

## Bug 10 - 迁移读取 marker 即触发持久化副作用（构造即重写 marker）
- 位置: AssetsManager/application/reconciliation_queue_migration.py:96-102（legacy_queue 构造）配合 reconciliation_queue.py:341-345（构造时恢复并持久化）
- 严重度: 低
- 描述: 用 `persistence_path=marker` 构造 `ReconciliationQueue` 时，`__init__` 若发现过期 RUNNING 任务会立即 `_persist_and_notify_unlocked()` 把 marker 改写为 v2 格式。于是"迁移导入"的其实是恢复后的数据；若随后 `store.replace(legacy_tasks)` 失败，marker 已被改写而 SQLite 未更新，下次启动的 `_same_snapshot` 比较基于改写后的数据。行为正确但隐式、难以审计。
- 触发/复现: marker 含 RUNNING 且租约过期任务时执行迁移。
- 修复建议: 迁移用只读方式加载 marker（跳过恢复/持久化），或在迁移结果中记录"marker 被就地升级"。

## Bug 11 - _LanServicesHolder 与 _publish_while_live 锁顺序反转（潜在死锁）
- 位置: AssetsManager/application/bootstrap.py:109-111（holder 锁 → session 条件锁，`get()` 内 is_closed 检查）与 AssetsManager/application/context.py:273-276（session 条件锁 → holder 锁，`_publish_while_live` → `_publish`）
- 严重度: 低
- 描述: 锁顺序 A（holder→session）与 B（session→holder）互为逆序。当前因状态机不变量（`get()` 在 state=="ready" 时不可能有构建线程在 `_publish` 中）不可达，但任何未来改动（如 ready 状态下刷新、或 is_closed 检查移入发布路径）都会引爆死锁。
- 触发/复现: 当前不可复现（潜伏缺陷）。
- 修复建议: 在 `get()` 的 ready 分支把 `is_closed` 检查移出 holder 锁（与 126 行一致），统一锁序为 session→holder。

## Bug 12 - LibrarySession.close() 有 close_callback 时不设置 _closed，is_closed 长期为 False
- 位置: AssetsManager/application/context.py:293-296（callback 分支只调 callback + _invalidate_resources，不置 _closed）
- 严重度: 中
- 描述: 带 callback 的 `close()` 依赖 callback（library_service.close_session）内部调用 `_begin_close()` 才置 `_closed=True`。若 callback 是轻量实现（测试/插件/未来重构），`_closed` 永远为 False：`is_closed` 误报 False；`_ensure_access`/`operation()` 放行新操作（仅靠 liveness token 在 connection_for 处拦截）；`_LanServicesHolder.get()`（bootstrap.py:111）在 session 已失效时仍可能返回已发布的 LAN 服务。此外 286-289 行"已关闭+有 callback"分支依赖 `_closed` 为 True 才能触发，实际因 `_closed` 恒 False 而成为死代码，第二次 close() 会再次调用 callback。
- 触发/复现: 使用非 library_service 的 close_callback 关闭 session 后检查 `session.is_closed`。
- 修复建议: `close()` 的 callback 分支在调用 callback 前先 `_begin_close()`（或要求 callback 契约显式置位）。

## Bug 13 - _finish_close 等待活跃操作清零无超时
- 位置: AssetsManager/application/context.py:314
- 严重度: 低
- 描述: `self._operation_condition.wait_for(lambda: self._active_operations == 0)` — 若某 operation 永久挂起（如持 connection 的 LAN 请求），`close()` 无限期阻塞，`_cleanup_session` 的 RuntimeError 重试机制也无法推进。
- 触发/复现: 一个卡死的 `with session.operation():` 上下文 + 调用 close()。
- 修复建议: 增加超时/强制失效策略，或将挂起 operation 标记为"关闭后拒绝提交"。

## Bug 14 - PerformanceRecorder.measure 正常路径 record() 校验异常冒泡破坏业务代码
- 位置: AssetsManager/core/performance.py:102-110（else 分支 record 无保护）对比 88-101（异常分支捕获 TypeError/ValueError）
- 严重度: 低
- 描述: 被测量代码正常返回时，`record()` 若因 name 为空 / elapsed 非有限值（_validate_context，122-139 行）抛 ValueError/TypeError，会直接冒泡到业务调用方；而异常路径（88-101 行）会吞掉同类错误。行为不一致，且"诊断代码"可能在 enabled 时破坏业务。
- 触发/复现: `recorder.enabled=True` 且某处 `measure(name="", ...)` 或传入非有限 elapsed_ms。
- 修复建议: 两条路径统一吞掉校验异常（仅日志），与模块"诊断不得干扰业务"的注释一致。

## Bug 15 - recent(负 limit) 返回全部事件
- 位置: AssetsManager/core/performance.py:116
- 严重度: 低
- 描述: `events[-max(0, limit):]` — limit=-5 时 `max(0,-5)=0`，`events[-0:]` 即 `events[0:]`，返回全部事件，与"limit 截断"语义相悖。
- 触发/复现: `recorder.recent(-3)`。
- 修复建议: 负 limit 抛 ValueError 或按 0 处理返回空。

## Bug 16 - 崩溃日志明文记录异常消息与完整堆栈，无敏感信息脱敏
- 位置: AssetsManager/core/crash_handler.py:37-48
- 严重度: 中
- 描述: crash.log 直接写入 `Message: {exc_value}` 与 `traceback.format_tb`。异常消息常含文件绝对路径，且可能包含 token/密钥片段（本仓库大量服务在异常消息中拼接路径与标识符，如 reconciliation_queue_store.py:206-208）。crash.log 位于 RuntimeData/Shared（用户目录），无脱敏、无权限限制说明。
- 触发/复现: 任一带路径/密钥片段的异常触发 sys.excepthook。
- 修复建议: 记录前对已知敏感字段（路径可按需保留但密钥/token 需掩码）脱敏；至少文档化该文件包含路径信息。

## Bug 17 - 仅安装 sys.excepthook，工作线程异常不落盘
- 位置: AssetsManager/core/crash_handler.py:59-64
- 严重度: 低
- 描述: `install()` 只覆盖 `sys.excepthook`。本应用大量后台线程（reconciliation worker、integrity/maintenance 调度线程、LAN asyncio 线程）的未捕获异常走 `threading.excepthook`，在 console=False 的打包环境下静默消失。
- 触发/复现: 任意 daemon 工作线程抛出未捕获异常。
- 修复建议: 同时安装 `threading.excepthook`。

## Bug 18 - 无崩溃计数/重启循环防护
- 位置: AssetsManager/core/crash_handler.py:21-29（_rotate_log 仅按大小轮转）
- 严重度: 低
- 描述: 崩溃处理器不记录崩溃次数/时间窗口，若上层存在自动重启逻辑，连续崩溃（如启动即崩）不会降级或停止。当前仅 512KB 轮转。
- 触发/复现: 打包应用在启动阶段反复崩溃并自动重启。
- 修复建议: 记录连续崩溃计数与时间戳，超出阈值时禁用自动重启。

## Bug 19 - run_tool 对 args 无类型校验，异常未捕获冒出
- 位置: AssetsManager/core/tool_scheduler.py:71-75
- 严重度: 中
- 描述: `args = tool.get("args", [])` 未校验类型：若 tools.json 中 args 是字符串（"blender"）→ 逐字符迭代，`full` 变成 `[cmd, 'b','l','e'...]`；若元素为非 str（数字）→ `a.replace` 抛 AttributeError 直接冒泡到 UI 调用方（run_tool 只捕获 Popen 的 OSError）。tools.json 由用户可编辑，属外部输入。
- 触发/复现: 用户在 tools.json 写 `"args": "blender"` 或 `"args": [123]`，点击工具菜单。
- 修复建议: 校验 args 为 list 且元素均为 str，非法时抛 ValueError 并带工具名。

## Bug 20 - Windows 下 .cmd/.bat 命令 + shell=False 无法启动
- 位置: AssetsManager/core/tool_scheduler.py:79-81（Popen shell=False）
- 严重度: 低
- 描述: 文档示例与常见配置使用 `"cmd": "code.cmd"`。Windows 上 `CreateProcess` 无法直接执行 .cmd/.bat（WinError 193），且此处 `shell=False` 无回退，工具静默启动失败（仅日志）。DEFAULT_TOOLS 用的 "blender"/"code"（无扩展名）不受影响。
- 触发/复现: Windows + tools.json 配置 `.cmd` 命令。
- 修复建议: 对 .cmd/.bat 走 `["cmd.exe", "/c", *full]` 或 `shell=True`（配合已验证的命令字符串）。

## Bug 21 - run_tool 无超时/进程跟踪，挂起工具无法终止
- 位置: AssetsManager/core/tool_scheduler.py:78-84
- 严重度: 低
- 描述: `subprocess.Popen` 后立即返回，句柄未保存、无超时、无终止入口。工具进程挂死只能由用户任务管理器处理；多次调用会产生孤儿进程。
- 触发/复现: 配置的外部工具启动后挂起。
- 修复建议: 返回 Popen 句柄供 UI 跟踪/终止，或至少记录 pid。

## Bug 22 - list_tools() 查询带写盘副作用
- 位置: AssetsManager/core/tool_scheduler.py:54-56（list_tools → _load）与 33-35（_load 缺失时 _save 默认配置）
- 严重度: 低
- 描述: 只读查询 `list_tools()` 在 tools.json 缺失时会创建默认文件（写 SHARED_DIR）。共享目录可能只读（打包安装到 Program Files 时），且查询语义不应有副作用。
- 触发/复现: tools.json 缺失 + SHARED_DIR 只读 → 每次菜单打开都触发一次失败的写。
- 修复建议: _load 拆分为"缺失时仅返回默认值"与"显式初始化"两个路径。

## Bug 23 - 安全预检不覆盖端口占用/防火墙/目录权限
- 位置: AssetsManager/application/security_preflight.py（类 SecurityPreflight 291-361、preflight_snapshot 226-288）
- 严重度: 中
- 描述: 预检仅覆盖契约状态（ack 版本、绑定范围扩展、认证移除、受信网络确认）。端口占用、防火墙放行、共享目录写权限等实际启动前提均不检查——绑定失败只能在服务启动后由 ShareState.FAILED 事后暴露，用户无法在确认对话框前得知端口被占。
- 触发/复现: 端口已被其他进程占用时启动 LAN 分享。
- 修复建议: 在 preflight 层增加可注入的"环境探测"（bind 端口可用性、目录可写、防火墙状态），失败时进入 confirmation/failed 而非启动后失败。

## Bug 24 - session_contract 错误消息硬编码错误的模块名
- 位置: AssetsManager/core/session_contract.py:27
- 严重度: 低
- 描述: `require_library_session` 抛出的 TypeError 消息为 "MetadataRepository requires a real LibrarySession"，但该函数被所有需要真实 session 的仓库/服务共用，错误归因误导排障。
- 触发/复现: 任意非注册对象传入 require_library_session。
- 修复建议: 消息改为中性表述（"requires a registered LibrarySession"）。

## Bug 25 - discover_plugins 吞掉全部异常并把插件服务置 None，调用方无感知
- 位置: AssetsManager/application/bootstrap.py:287-304
- 严重度: 低
- 描述: `discover_plugins` 捕获一切异常（含插件加载过程中单个插件导致的崩溃），吞掉后 `self._plugin_svc = None`。随后 `plugin_service` property（311-312 行）返回 None，UI/其他服务解引用即 NPE；`LibraryScopedServices.plugin_service`（bootstrap.py:531）直接 `self.container.resolve(PluginService)` 不受影响，但对外访问路径不一致。
- 触发/复现: 一个坏插件在 load_all_enabled 时抛异常。
- 修复建议: 记录具体失败插件清单并提供查询接口；None 化只应在"容器本身不可用"时发生。

# 检查点结论（明确无问题的面）
- runtime 服务快照生命周期（frozen LibraryScopedServices / services_snapshot 属性）: 无问题。
- runtime_events 域投影 epoch/generation 对比（InvalidationEvent.epoch=uuid、revision 单调递增）: 无问题。
- 队列幂等消费与单消费者保证（SQLite BEGIN IMMEDIATE + 每任务 CAS + lease token/attempt 双校验）: 无问题。
- 队列存储原子性（JSON mkstemp+fsync+os.replace；SQLite savepoint/独立事务）: 无问题。
- 队列迁移旧格式（v1 单调钟 deadline 转为立即到期/恢复，避免卡死）: 逻辑正确（副作用问题见 Bug 10）。
- bootstrap 属性注入（app property）、插件发现本身、失败回滚主链路（runtime.close()）: 无问题。
- runtime_events 线程投递: 无问题（UI 经 panels/_event_bridge.py QueuedConnection 转 Qt 线程；LAN 经 asyncio.run_coroutine_threadsafe 转事件循环）。
- session_contract 契约校验（字段/类型）: 无问题（模块极小，见 Bug 24 消息归因问题）。

