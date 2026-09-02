# 04 · 核心基础设施 + 插件系统薄弱项审计（2026-08-22）

**范围**：`AssetsManager/core/` 全部 32 模块、`core/plugins/`（descriptor/host_context/loader/manager）、`AssetsManager/plugin_api/`、`Plugins/`（Addons/booth_link、download_tracker）。合计 14,884 行。
**基线**：commit `5fbf930` 脏工作树。已知背景（不再重复）：插件权限体系官方已声明"非沙箱"；19 个 type: ignore 集中在 db_migrations。

## 总体评估

core 层的整体工程质量明显高于同类桌面项目：数据库层的崩溃一致性设计（identity marker 的 no-clobber 发布、目录链 fsync、Windows FlushFileBuffers 回退）、迁移层的 savepoint 原子性 + 契约回溯校验、插件宿主基于 ContextVar 的身份/权限双门（并明确文档化了"诚实边界而非沙箱"），都显示出对失败模式的认真思考。注释密度高且大多解释"为什么"，测试冻结钩子（frozen_history_signature）等防线到位。

但三个系统性弱点值得注意。**其一，锁纪律不对称**：`locked_read`/`db_write_lock` 为共享连接建立了完整的写门，但 `ProjectData` 的读路径完全绕开它，`_WriteGate` 只隔离"全局写 vs 连接写"而不隔离"连接写 vs 连接写"，跨连接嵌套是未设防的死锁面。**其二，"拒绝降级"类保护只做了前半段**：settings 遇到未来版本时拒绝迁移却不隔离后续写入，任何一次 `set()` 都会把新版本配置整体覆盖掉——这是本次审查中唯一接近数据丢失等级的问题。**其三，契约覆盖有盲区**：v2-v5、v24 创建的五个表不在任何契约清单里，迁移系统对它们既不校验也不修复，损坏会推迟到运行期查询才暴露。

插件系统方面，host_context 的身份传播分析（ContextVar 不进线程、host 标记不进线程）是扎实的；主要剩余问题是无界增长的 `_undo_stack`/`_notifications`、以及示例插件 download_tracker 向第三方开发者示范了无锁共享状态 + 事件线程写 GUI 数据的危险模式——示例代码即事实上的 API 文档，这个坏榜样会被复制。

## 主要发现（按严重度排序）

### [P1][设置/数据丢失] settings.json"未来版本"拒绝降级的保护未闭环，首次写入即整体覆盖 ✓已复核
- 位置：`AssetsManager/core/settings.py:129-153`、`:233-243`、`:109-111`
- 证据：`load()` 中 `migrate(data)` 对 `_cfg_version > CURRENT_VERSION` 抛 `ValueError`（config_migrator.py:38-42），被 `except (ValueError, TypeError)` 捕获后仅记日志（settings.py:150-151）——`self._data` 保持为空 dict，**原文件未被隔离**。此后任何 `set()`（settings.py:243 置 dirty）触发 `save()` 用近空 dict 覆盖整个文件；`library_manager.record_visit`（library_manager.py:29-56）在每次打开库时都会写入。
- 影响：用户用旧版程序打开一次新版写过的配置后，所有设置（LAN 安全确认、主题、库注册表、插件禁用列表）静默丢失。`atexit` flush（:109-111）同样以 dirty 为条件，方向一致。
- 建议：未来版本路径应与 `_quarantine_corrupt_settings` 同等对待——把原文件改名保留（如 `.newer`），或至少在内存中设置 `read_only` 标志让后续 `set()`/`save()` 直接拒绝并告警。

### [P1][正确性] ProjectData 全部读路径绕过连接写锁，与 locked_read 自述的故障模式直接冲突
- 位置：`core/project_data.py:83-88`（get_notes）、`:105-111`（has_notes）、`:117-138`（get_urls）、`:226-231`（get_dir_size 读缓存）、`:280-282`（prune_missing 的 SELECT）
- 证据：写路径（set_notes:94、add_url:145、_set_cached_size:261、invalidate_size_cache:273）都取 `db_write_lock(self._db)`，而读路径是裸 `self._db.execute(...)`。`database.py:1237-1247` 的 `locked_read` docstring 明确说明：同一 `check_same_thread=False` 连接上无锁 SELECT 与在途写事务竞争会表现为间歇性 `OperationalError`/递归游标错误——这正是这些裸读的暴露面。
- 影响：Info 面板 worker 线程读 notes/urls 与导入/对账线程写 file_data 并发时出现间歇性异常；`prune_missing` 还在写锁内做逐行 `os.path.exists`（:284-288），网络库上长时间占住连接写锁。
- 建议：为读方法加 `locked_read` 同款保护；`prune_missing` 把 exists() 检查移出锁。

### [P1][死锁面·疑似] `db_write_lock(conn)` 跨连接嵌套无全局锁序，_WriteGate 不覆盖该场景
- 位置：`core/database.py:1196-1199`（先取 `_write_gate.read()` 再取 per-connection `state.lock`）、`:458-512`（_WriteGate 全文）
- 证据：每个连接的写锁是独立 RLock，`_WriteGate` 的 reader 准入是共享的——两个线程分别持有 connA/connB 的 `state.lock` 后互相请求对方连接的锁，gate.read 双方都持有着，永远不会仲裁。代码只对**同线程**的 global↔conn 混用做了 fail-fast（:1190-1195、:1228-1232），未防跨线程的 conn-conn 环。仓库层若出现"持有库 A 事务时调用操作库 B 的服务"即成死锁。
- 影响：多库同时打开（桌面 + LAN 会话）时潜在的进程级挂死，且无超时（RLock 不可中断）。目前未找到必然嵌套的调用链，故列为疑似，但架构上没有任何文档或断言阻止该模式。
- 建议：至少在开发构建中给 `state.lock` 换成带 owner 追踪的可重入锁并做锁序断言；或规定单一时间只允许持有一个库的写锁并在 `open_library` 层面强制。

### [P2][可用性] LibraryLock staleLockTime(0)：Windows PID 复用导致崩溃后的锁永久无法回收
- 位置：`core/library_lock.py:58-64`（setStaleLockTime(0)）、`:25-55`（_pid_is_alive）、`:209-219`（Windows 恢复分支）
- 证据：Qt 自带的时间型 stale 回收被显式关闭，唯一的恢复依据是 `getLockInfo()` 的 PID 存活探测。Windows PID 复用非常快：进程崩溃 → PID 被任意新进程占用 → `_pid_is_alive` 返回 True → 锁永远被判"活"，`LibraryAlreadyOpenError` 直到用户手删锁文件。恢复分支拿到了 `_host, _app`（:211）却丢弃不用。
- 影响：崩溃后库打不开的偶发但用户不可自愈的故障（fail-closed 方向，无数据损坏；POSIX 侧因 flock 序列化 + unlink 重检而无此问题）。
- 建议：恢复判定加入 `getLockInfo` 的 appname 比对；或提供启动时的锁文件诊断提示（报告锁属 PID/进程名/写入时间）。

### [P2][迁移健壮性] 契约回溯校验存在五个表的死角
- 位置：`core/schema_defs.py:672-1201`（SCHEMA_OBJECT_CONTRACT）、`core/db_migrations.py:48-91`（_BASELINE_SCHEMA_CONTRACT）、`:1117-1153`（required_objects 清单）
- 证据：`assets`（v2）、`tag_metadata`（v3）、`plugin_metadata`（v4）、`directory_cache`（v5）、`asset_dir_snapshot`（v24）五表**不在**任何契约清单。这五表的 DDL 是迁移函数内联字符串（如 db_migrations.py:487-511），没有 schema_defs 单一事实源。
- 影响：这五张表缺列/坏形状时开库不报任何错，故障推迟到 asset_index 扫描、目录缓存或 Info 面板查询期才以莫名的 `OperationalError` 出现——恰好是最难诊断的一类。`directory_cache` 现在还是 GUI 热路径的持久层。
- 建议：为五表补 SchemaObjectContract（允许 additive 列）并纳入 required_objects 的版本分支。

### [P2][迁移健壮性] MIGRATIONS 连续性与 CURRENT_SCHEMA_VERSION 一致性缺运行时断言，跳版即砖库
- 位置：`core/db_migrations.py:47`、`:1038-1070`、`:1111-1116`、`:362-369`
- 证据：`_validate_history` 要求磁盘记录必须是 `1..max` 的连续集（:368-369），但 MIGRATIONS 元组本身的连续性、以及 `len(MIGRATIONS) == CURRENT_SCHEMA_VERSION` 只有测试侧 `frozen_history_signature` 间接保障。若未来发布跳过 v32 直发 v33：应用后磁盘记录 {1..31, 33}，**下一次打开任何库都抛 MigrationHistoryError**（提示需"修复工具"，而项目没有修复工具）。若元组 32 项而常量忘改成 32：`migration.version > CURRENT_SCHEMA_VERSION: continue`（:1112）让 v32 **静默不执行**。
- 影响：一次提交疏忽即可造成用户库不可用或半迁移状态，且失败模式是永久的。
- 建议：在模块加载时断言 `tuple(m.version for m in MIGRATIONS) == tuple(range(1, CURRENT_SCHEMA_VERSION + 1))`，fail fast 于开发期。

### [P2][插件质量/并发] download_tracker 示例插件：无锁共享 dict 跨线程读写，演示了危险模式
- 位置：`Plugins/Addons/download_tracker/tracker.py:22`（模块级 `_history`）、`:86-110`（ImportHook.handle 在事件发布线程执行）、`:143-159`（HistoryPanel.build 在 GUI 线程 `sorted(_history.items())`）
- 证据：`FileSystemChanged` 由 watcher/import/file_operation 多处发布，EventBus 同步调用 handler（domain/event_bus.py:129-131）；面板重建在 GUI 线程迭代同一 dict。插入发生在迭代中即 `RuntimeError: dictionary changed size during iteration`。此外 `_save_history` 每次取全新 bag（host_context.py:404-426 每次调用重新读盘）后整文件重写，两线程并发保存丢更新。
- 影响：示例插件即教程——第三方插件作者会复制这个"模块级可变状态 + 事件线程写 + GUI 线程读"的模式。宿主 API 未提供任何同步原语或线程化指导。
- 建议：tracker 加一把 `threading.Lock`（或快照读）；宿主在 plugin_api 文档明确并发契约，并提供 `ctx.post_to_main` 类投递原语。

### [P2][资源泄漏] BoundedPool 令牌注册表只增不减，长会话线性累积
- 位置：`core/workers.py:109-115`（start 追加 token）、`:117-130`（仅 cancel_all/close 清空）
- 证据：`_model.py:250-251` 在目录切换时直接 `self._scan_token.cancel()` 并新建 token，**不经过 pool**，`_scan_pool._tokens` 因此在整个库会话内为每次 `set_directory` 保留一个条目；`_size_pool.start(task)` 同理按目录累积。`cancel_all` 只在 shutdown/库切换触发。
- 影响：长浏览会话下每次导航/每个目录尺寸任务泄漏一个 CancellationToken（内含 Lock），数小时会话可累积数千项。量级小但方向确定，与"有界池"的设计意图相悖。
- 建议：`drain()` 成功后也清空 `_tokens`；或改为弱引用集合。

### [P2][设置基础设施] PluginPreferenceBag 无锁、每次调用重读盘、set 即全量重写
- 位置：`core/plugins/preferences.py:38-46`（每次 `__init__` 从盘 load）、`:59-68`（_save 无锁、无 fsync）、`:73-75`（set 全量重写）
- 证据：`_preferences_for`（host_context.py:404-426）每次 `preferences()` 调用 new 一个 bag；`set()` 是"新读盘 → 改一键 → 整文件替换"，两个线程交错时后写者覆盖前写者的其他键。`_save` 既无 `fsync`（与 settings.py:210、json_store.py:132 的自身规范不一致）也无任何互斥。
- 影响：多事件线程插件并发写偏好丢数据；高频事件产生每次事件的磁盘读+写放大。
- 建议：按 plugin_id 缓存 bag 实例（带锁），`set` 合并写；`_save` 对齐 mkstemp+fsync 模式。

### [P2][并发·疑似] themes 全局字典无一致锁保护，热重载与 get()/stylesheet() 存在竞态
- 位置：`core/themes.py:258-272`（get 无锁返回**可变** dict）、`:125-151`（set_plugin_token_fallbacks 无锁改 `_EXTENDED_FALLBACKS` 并直接改各 theme dict）、`:161-174`（reload_themes 无锁 clear `_THEMES`）
- 证据：`_themes_lock` 只用于样式表缓存的读写；`reload_themes` 由 QFileSystemWatcher 触发（:331-332，可在任意线程回调），期间 `get()` 的 `key in _THEMES` 与 `_THEMES[key]` 之间被 clear 即 KeyError。`get()` 返回活 dict 也让调用方误改成为可能。
- 影响：主题文件热重载或插件 token 注册期间偶发异常/样式闪烁。主题操作多数在 GUI 线程，故列为疑似，但 watcher 线程回调是真实入口。
- 建议：`get()` 返回不可变 MappingProxy 或浅拷贝；`reload`/`set_plugin_token_fallbacks` 全程持 `_themes_lock`。

### [P3][耐久性] JSON 写链路的目录 fsync 全面缺失，与 database 层标准不一致
- 位置：`core/json_store.py:105-148`、`settings.py:195-221`、`tag_library.py:177-190`、`tool_scheduler.py:52-71`（以上有文件 fsync 无目录 fsync）；`preferences.py:59-68`（两者皆无）
- 证据：database.py:261-326 为 identity marker 实现了完整的 `_flush_directory_durable`（含 Windows FILE_FLAG_BACKUP_SEMANTICS + FlushFileBuffers），说明作者清楚 rename 的目录项持久化问题；但所有 JSON 存储的 `os.replace` 之后都没有对父目录做对应处理。
- 影响：POSIX 上断电可能丢掉 rename 本身；Windows/NTFS 元数据日志使风险较低。preferences.py 连文件 fsync 都没有。
- 建议：抽取公共的 atomic_write(path, data) 工具（mkstemp + fsync + replace + 可选目录 flush），四处复用，消除四种几乎相同的实现并存。

### [P3][渲染] icons 缓存键只取主屏 DPR，混合 DPI 多屏与屏幕切换不失效
- 位置：`core/icons.py:147-149`（`QGuiApplication.primaryScreen().devicePixelRatio()`）、`:177-179`（clear_cache 仅主题/缩放调用）
- 证据：缓存键 `(resolved, tint, pixel_size, dpr)` 中的 dpr 固定来自主屏；副屏 DPR 不同时复用主屏位图 → 模糊。无 `QScreen.geometryChange`/`screenAdded` 钩子。
- 影响：混合 DPI 环境图标发虚；空间上缓存有界（4096）无泄漏之虞。
- 建议：渲染时用目标 widget 的 `devicePixelRatio()` 参与键控，或监听 `primaryScreenChanged` 清缓存。

### [P3][时钟源] TTL 一律使用墙钟 time.time()，时钟回拨引发批量失效或滞留
- 位置：`core/cache.py:274`（TTLCache）、`directory_cache.py:169`（_PRUNE_AGE）、`project_data.py:239`（_SIZE_CACHE_TTL）
- 证据：三处 TTL/淘汰均以 `time.time()` 为基；NTP 校时或手动改时间向后跳 N 秒，则所有新鲜条目瞬间"过期"（缓存雪崩，全量重扫）。对比 performance.py:85 已正确使用 `perf_counter`。
- 影响：低频但用户可感知（改时间后卡顿/旧数据）。
- 建议：TTL 判定改用单调钟，仅持久化字段保留墙钟。

### [P3][内存] host_context._undo_stack 与 _notifications 无界增长
- 位置：`core/plugins/host_context.py:241`（_undo_stack 定义）、`:754-757`（每次可撤销命令 append，无上限）、`:254`/`:936-940`（notifications 只增）
- 证据：长会话中每个 undoable 插件命令追加一条（含完整参数 dict），`show_notification` 每次调用追加；没有消费端清空 `_notifications`。
- 影响：慢增长内存驻留；undo 记录持有插件类引用还阻止其模块回收。
- 建议：`_undo_stack` 设上限（如 100，超出丢最旧）；notifications 提供 drain/consume API。

### [P3][插件系统] loader 从不注册 sys.modules，unload 的模块清理是死代码；manifest 权限不校验
- 位置：`core/plugins/loader.py:88-93`（module_from_spec + exec_module，无 sys.modules 写入）、`core/plugins/manager.py:322-326`（unload 时 `del sys.modules[module_name]` 永远 miss）、`descriptor.py:194-198`（permissions 若为字符串会被逐字符拆成垃圾 token 集合，未知 token 也不在加载期拒绝）
- 证据：importlib 规范中 `exec_module` 不自动注册；当前"重载=新模块对象"行为碰巧正确，清理代码给人已处理的假象。未知权限运行期才由 `check_permission`（host_context.py:1165-1166）告警。
- 影响：死代码误导维护者；manifest 拼写错误（如 `"filesystemread"`）静默无效，到运行期才以"无权限"警告浮现。
- 建议：删除 sys.modules 清理或真正注册；`parse_plugin_descriptor` 加载期即校验 permissions ⊆ ALL_PERMISSIONS 并落 diagnostics。

## 次要问题清单

- `db_migrations._migrate_once` 的 except 路径中 `ROLLBACK TO SAVEPOINT` 自身抛错会掩盖原始迁移异常（:1164-1167）
- 多个迁移用 `schema.split(";")` 朴素分割 DDL，字符串字面量一旦含分号即碎裂（:597-599 等 10 余处；当前 schema 无分号，属脆弱模式）
- `PRAGMA foreign_keys=ON` 只在 DatabaseManager 连接上生效；integrity/export 的临时连接（database_integrity_service.py:333 等 5 处）未设
- 未设置 `PRAGMA synchronous=NORMAL`，WAL 下保持默认 FULL，每 commit fsync WAL，写吞吐受损（database.py:378-379）
- `PluginManagerService.discover_plugins` 整体重置 `_records`（manager.py:100-101），加载后再次 discover 会孤儿化已加载实例——潜伏 API 陷阱
- `_persist_enabled_state`/禁用状态恢复用 bare `except Exception: pass` 吞掉持久化失败（manager.py:103-113, 161-171）
- 插件 `register()` 在 `_records_lock`（RLock）内执行第三方代码（manager.py:228-254），插件自建线程调 manager 方法将被阻塞至注册完成
- `open_path` 的 `os.startfile` 无异常处理（host_context.py:1394-1395）
- `theme_loader.create_custom_theme` 非原子写（theme "w" 直写，:209-213），与 save_custom_theme 的原子写不一致
- schema 契约把部分唯一索引当作表级 UNIQUE 接受（如 shop_carts 的 ("user_id",) 实为 `WHERE owner_type='user'` 部分索引），契约弱于真实 schema（schema_defs.py:1358-1366 vs :407）
- 直接构造的 AppSettings 实例注册的 atexit 处理器因 LIFO 顺序可能用陈旧快照覆盖 singleton 的最终保存（settings.py:77-82，仅测试/直构路径）
- `themes.py` 模块导入即扫盘、读设置、启动 QFileSystemWatcher（:222, 243, 331-332），加重测试与无头场景的导入副作用
- `path_resolver.root_identity` 用 abspath 不 resolve，symlink 两种拼写的库根会分到两个 RuntimeData slot（:107-114）
- `clean_orphan_dirs` 中 `Path(r).resolve()` 对持久化的 recent_libraries 条目无保护（database.py:1109-1117）
- crash_handler 的 traceback 帧有意不脱敏，但异常链中 `__cause__` 的消息不经过 `_redact`；SHARED_DIR 只读时报告完全静默丢失（crash_handler.py:101-113）
- `TTLCache.__len__` 统计含已过期条目；`__contains__` 不清理过期项（cache.py:303-312）
- `plugin_api/types.py:56` `PluginContext.session` 保留 `_runtime_session` 遗留回退，绕过 host.services 门的历史缺口
- host_context API 收紧机会：`current_window()` 返回原始 QMainWindow（可达 `_library_session` 等私有面）；`get_current_root_path/get_selected_paths/request_refresh` 完全不设权限（应显式列为"无门 API"清单）
- manager.py:471 从 core 导入 application 的 `_BUILTIN_CATEGORY_MAP` 私有名（经 format_utils 中转，层次合规但命名私有）

## 规模与复杂度观察

- 审查范围合计 14,884 行：core 本体约 9,500 行 + core/plugins 2,538 行 + plugin_api 305 行 + Plugins 229 行。database.py（1487）+ schema_defs.py（1436）+ db_migrations.py（1199）三件套占 core 约 43%，是复杂度主巢。
- schema 存在**三重手工同步**：当前 DDL（schema_defs 各 `*_SCHEMA`）、历史快照（`USERS_SCHEMA_V6`、`COMMERCE_SCHEMAS_V8`、`SHOP_CARTS_SCHEMA_V16`）、契约 dict（`SCHEMA_OBJECT_CONTRACT` + `_versioned_schema_contract`），另有两处表重建 DDL 内联在迁移函数里（v19: db_migrations.py:766-781、v30: :962-989）。任一处漂移只能靠运行期 InvalidSchemaError 或测试发现——这正是五表死角和 19 个 type: ignore 的根源。值得考虑从单一 DDL 源生成快照与契约。
- host_context.py 单类 1569 行、30+ 公开方法，身份管理（ContextVar 三元组）、权限判定、八种贡献注册表、undo 栈、通知队列揉在一起；`unregister_plugin` 一个方法重写 13 个容器（:1455-1555）。拆分为 IdentityScope/PermissionBook/ContributionRegistry 三件会让权限审计面小一个数量级。
- themes.py 735 行中约 170 行是内联 QSS f-string；`_SCHEMA`（database.py:377-422）与其说是 schema 不如说是"迁移第 0 步"，与 db_migrations 的边界值得在注释中再明确。
