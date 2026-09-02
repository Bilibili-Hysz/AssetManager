# 02 · 应用层数据管线薄弱项审计（2026-08-22）

**范围**：`AssetsManager/application/` 中的库生命周期/文件操作/导入导出/对账队列/资产索引：bootstrap.py、runtime.py、context.py、library_service.py、file_operation_service.py、undo_service.py、import_service.py、import_manifest_store.py（新）、library_export_service*.py、library_watcher_service.py、reconciliation_queue*.py（3 文件）、asset_index_service.py、asset_index_reconciliation_service.py、filesystem_projection_repair_service.py（新）。
**基线**：commit `5fbf930` 脏工作树。C6-C10 官方自认的限制（SQLite/FS 非原子、无 outbox、无 copy replay、缩略图不回放、watcher 无 cursor）不再重复展开。

## 总体评估

这批管线代码的整体工程素质明显高于常见桌面应用水平：对账队列有完整的 lease/token/attempts CAS 与跨进程 generation 机制，导出/恢复侧做了罕见的纵深防御（zip 结构预检、Windows 大小写折叠键、reparse 点反复复验、fstat 稳定性检查、quick_check 门禁），库生命周期有可重试的分阶段 teardown 进度对象，会话有 operation 租约与有界排水。C6-C10 新增的投影修复、恢复回放、导入意图清单确实闭合了大量主路径缺口。

但审查发现三个结构性残留问题：其一，**导入意图清单的恢复状态机没有终点**（`recovery_pending` 本身是恢复态），每次开库都会永久性地重复入队全库重扫；其二，**恢复/删除路径中仍有单向数据破坏窗口**（`restore_backup` 的失败清理会删除已存在的目标文件；restore 的 quarantine→install 两步替换在崩溃后无自动回滚）；其三，**关闭路径的超时语义不协调**——watcher 2 秒、worker 30 秒、事件路由无界的排水等待互相竞争，任何扫描中的任务都会让库关闭失败并进入待重试状态。此外，事件总线是同步分发，而 `FileOperationService` 在持有路径锁时发布事件，把订阅者的延迟和潜在重入变成了锁的持有时间。

## 主要发现（按严重度排序）

### [P1][状态机死角] 导入清单恢复没有终态，每次开库永久触发全库重扫 ✓已复核
- 位置：`AssetsManager/application/import_manifest_store.py:24`、`:262-285`；`AssetsManager/application/bootstrap.py:613`
- 证据：`_RECOVERY_STATES = {"prepared", "running", "degraded", "recovery_pending"}`，而 `ImportManifestRecoveryService.recover()` 对每个恢复态清单执行 `self.store.finish(operation_id, state="recovery_pending", increment_attempts=True)`——把恢复态再次 finish 成恢复态。【确认】
- 影响：任何一次被中断/降级的导入之后，该清单永远留在恢复集合中；每次打开库都会重新 `enqueue_or_merge` 一个以 `session.root` 为 scope 的 `ASSET_INDEX_ROOT_RESCAN` 任务（即使上一轮已成功），同时 `attempts` 无限递增、`import_manifests` 行永不清理。大库上表现为"每次启动都做一次全库索引重扫"，且随历史中断次数线性累积清单行。
- 建议：`recover()` 在成功入队后应迁移到终态（如新增 `recovered` 终态或复用 `completed`）；并给清单表加保留上限/归档策略。注意 `degraded` 也在恢复集合里——正常完成但降级的导入同样会进入该循环。

### [P1][数据破坏] restore_backup 失败清理会删除已存在的目标文件 ✓已复核
- 位置：`AssetsManager/application/file_operation_service.py:824-832`（`except OSError: self._remove_partial_target(target); raise`）
- 证据：`restore_backup` 不预先检查目标是否存在；若目标已被外部重建（或直接调用时目标存在），`shutil.copytree/copy2` 抛 `FileExistsError`（OSError 子类），随后 `_remove_partial_target` 对已存在的目录执行 `rmtree`、对文件执行 `unlink`，然后才重新抛出。对比同文件 `move`（546-549 行）在事前用 `lexists` 拒绝覆盖。【确认】undo 路径（`undo_service.py:510-515`）事前有 `lexists` 守卫，但检查与复制之间存在竞态窗口，且 `restore_backup` 是公开 API，未来调用方无守卫。
- 影响：恢复失败的同时把用户重建的同名文件/目录删掉——双重数据丢失。
- 建议：与 `move` 对齐，进入时 `os.path.lexists(target)` 即拒绝；`_remove_partial_target` 只应删除本次操作自己创建的文件（可在 copy 前先 reserve 标记）。

### [P2][崩溃窗口] 恢复流程 quarantine→install 两步替换间崩溃，库无 RuntimeData 且无自动回滚
- 位置：`AssetsManager/application/library_export_service_restore.py:297-307`（`data_dir.replace(previous)` 与 `staging.replace(data_dir)` 之间）
- 证据：进程在两步之间死亡时：原 RuntimeData 已在 `_orphaned/restore-backups/<...>`，`data_dir` 不存在，恢复失败状态（`restore_recovery_required`）只存在于进程内存，崩溃后没有任何持久记录。下次 `_open` 会经由 `DatabaseManager.connection_for` 自动新建空库。【确认】（空库自动创建为推理链）
- 影响：崩溃后库"静默变空"，原始数据躺在隔离区，用户无提示；依赖 UI 主动调用 `list_restore_quarantine` 才能找回。
- 建议：安装前在磁盘写一个持久化的 restore-in-progress 标记（如 data_dir 父目录下的 intent 文件），开库时检测到"data_dir 缺失 + 隔离区存在本次 token"即自动回滚或至少阻断打开并提示。

### [P2][取消/关闭] watcher 与对账 worker 的 stop 超时会让库关闭失败
- 位置：`AssetsManager/application/library_watcher_service.py:129-133`（2s join 后抛 `LibraryWatcherStopTimeout`）、`:205-234`（`scan_once` 循环内不检查 stop_event）；`AssetsManager/application/asset_index_reconciliation_service.py:239-273`（30s join 后抛 `ReconciliationWorkerStopTimeout`）；`runtime.py:115-125`（adapter stop 异常→runtime `_state="failed"`）
- 证据：`scan_once` 单轮最多扫 50,000 个目录（`MAX_DIRECTORIES`），中途无停止检查；慢盘/网络盘轻松超过 2 秒 stop 预算。worker 的 `index_directory_tree_result` 扫描同样不可中断，`stop_timeout` 默认 30s。两者超时异常沿 `close_adapters` → `_run_owned_teardown` 上抛，根停留在 `closing` 所有权，需手动重试 `close_session`。【确认】
- 影响：大库/慢盘上关闭库随机失败，进入"teardown pending"状态。
- 建议：在 `scan_once` 的 BFS 循环和目录树扫描中传入并检查 stop_event；或把 watcher 的 stop_timeout 放宽为与扫描预算匹配，并在超时后不抛异常而是记录日志（watcher 线程是 daemon，进程退出无风险）。

### [P2][事件顺序/锁] 同步事件分发发生在持有路径锁时
- 位置：`AssetsManager/application/file_operation_service.py:560-615`（`_publish_file_change("moved", ...)` 在 `with acquire_path_locks(src, dst):` 内）；`domain/event_bus.py` `publish`（同步内联调用）；`runtime_events.py:263-273`（路由器同步调用订阅者回调）
- 证据：`EventBus.publish` 是同步内联调用；`move`/`move_to_directory`/`delete_*` 都在持有 per-path `threading.Lock`（不可重入）时发布 `FileSystemChanged`，订阅者（LAN websocket 推送、面板缓存）在锁内执行。【确认】死锁需要订阅者重入同路径文件操作（当前未见），属"疑似"升级路径；慢订阅者拉长锁持有期是确定的。
- 影响：任何未来的同步订阅者触碰同路径文件操作即死锁；当前则表现为路径锁临界区被订阅者耗时放大。
- 建议：把 `_publish_file_change` 移出 `acquire_path_locks` 块；或改用异步分发队列。

### [P2][时钟假设] lease CAS 与过期判定全部依赖 wall clock，时钟回拨产生双 worker
- 位置：`AssetsManager/application/reconciliation_queue_store.py:535、587、671`（`lease_expires_at_wallclock > now_wallclock` 谓词）、`:989-994`（恢复扫描同样比较 wallclock）
- 证据：`renew_lease`/`mark_succeeded`/`mark_retryable` 的 CAS 与 `_recover_expired_running_unlocked` 的过期判定都用 `time.time()`。系统时钟回拨（NTP 校正、手动改时间）会让存活 worker 的 lease 立即"过期"，任务被翻回 retryable 并被另一 worker 领走；前拨则任务假死到期。【确认】
- 影响：同一修复任务并发执行两次（修复本身幂等，损害有限），或修复延迟一个 lease 周期。
- 建议：lease 判定改用单调时钟（连接内存中的 rebased monotonic），wallclock 仅作诊断字段；或对回拨幅度加保护带。

### [P2][正确性] move 在 IO 后发现事务边界被占时只告警，元数据迁移可能被外务回滚
- 位置：`AssetsManager/application/file_operation_service.py:578-583`
- 证据：`shutil.move` 完成后，若 `connection.in_transaction`（后台 rescan 开启的事务），代码只 `_log.warning` 然后继续 `_migrate_metadata`——迁移以 SAVEPOINT 嵌入外层事务，外层回滚时迁移静默消失而文件已移动。事前检查（562-565 行）会 raise，事后却降级为告警。【确认】
- 影响：move 的 DB 投影静默漂移；随后的 root rescan 兜底会修复索引，但 tags/metadata/favorites 漂移要等修复任务。
- 建议：事后发现占用时应走与 `_migrate_metadata` 失败相同的修复入队路径（带上 move 的 repair payload），而不是仅告警。

### [P2][可用性] 对账队列单行损坏导致整库无法打开（fail-closed 无隔离路径）
- 位置：`reconciliation_queue_store.py:1184-1193`（`_row_to_task` 对非法 payload 抛 ValueError）→ `:177-180`（`load_snapshot` 转 PersistenceError）→ `reconciliation_queue.py:1307-1317`（`_load` 直接上抛）→ `bootstrap.py:587-593`（构造即抛）→ `window.py:159`
- 证据：任一 `reconciliation_tasks` 行的 payload/状态值损坏，`ReconciliationQueue.__init__` 失败，`_build_services` 失败，库打开失败。无行级隔离/丢弃/计数上报。【确认】
- 影响：一个非核心辅助表的损坏行让整个库不可用，用户无法自助（需手工改 SQLite）。
- 建议：load 时把不可解析行移入 quarantine 表（或标记 terminal+last_error），记 warning，保持库可用。

### [P2][部分失败] 导入循环中 manifest 更新异常会中止整个导入
- 位置：`AssetsManager/application/import_service.py:359-373`
- 证据：文件复制的 OSError 被捕获并计入 `failed`，但随后 `manifest_store.update_item(...)` 未包 try——SQLite 瞬时 busy/校验异常直接冲出循环，已复制文件保留但调用方拿到异常而非部分结果，manifest 停在 `running`。【确认】
- 影响：瞬时 DB 锁即可让大批量导入中途夭折，UI 只能报错。
- 建议：`update_item` 失败按"清单失联"处理：计数、继续复制、最后统一走 `recovery_pending` 兜底（已有该状态）。

### [P2][资源/性能] 删除操作在持有连接写门期间执行 rmtree
- 位置：`file_operation_service.py:766-776`（`with self._clean_transaction_boundary():` 包住 `shutil.rmtree(p)`）；`:457-471`（`_clean_transaction_boundary` 持有 `db_write_lock` 直到 yield 结束）
- 证据：move 路径特意把文件 IO 移出写门（559 行注释），删除路径却让整个 rmtree（可能是巨型目录树）都在 `db_write_lock` 内。【确认】
- 影响：删除大目录期间该库所有 DB 写者（含对账 worker、缩略图、LAN 写入）被阻塞。
- 建议：先在写门内做边界检查，释放后再 rmtree，最后在写门内做投影清理。

### [P2][耐久性] 备份归档发布前无 fsync，掉电可产出"已验证但截断"的备份
- 位置：`library_export_service_export.py:340-360`（`validate_backup(temporary)` 后 `temporary.replace(target)`）；对比 `reconciliation_queue.py:1404-1409`（JSON 标记有 fsync）
- 证据：zip 关闭后数据仅在 OS 缓存；validate 读的是同一份缓存（能通过）；`os.replace` 原子但不含数据落盘语义。掉电后 target 可能是零长/截断的备份。【确认】（触发条件为掉电/内核崩溃级别）
- 影响：用户最信任的"安全备份"在极端情况下损坏且无提示。
- 建议：replace 前对临时文件 `os.fsync`，并对目标目录做 fsync（Windows 上 `FlushFileBuffers`）。

### [P2][取消传播] 取消的导入不发布任何事件，已复制文件对索引不可见
- 位置：`import_service.py:341-357`（取消直接 raise，跳过 432-437 的事件发布与索引刷新）
- 证据：取消时 `raise ImportCancelled(partial)`，`FileSystemChanged(kind="import")` 与 `_refresh_directory_tree` 都不执行；manifest 标 `cancelled`（不在恢复集合内），所以重启也不会补扫，只能靠 watcher 下一轮（默认 120s，且只发目录级事件）。【确认】
- 影响：取消后已复制的文件在索引/统计中长期缺失，直到 watcher 或手动刷新。
- 建议：取消路径也应对已复制部分发布 `FileSystemChanged` 或入队一次目录级 rescan。

### [P3][正确性] 并发 perform_undo/perform_redo 可把有效条目标记为中毒
- 位置：`undo_service.py:433-453`
- 证据：`_undo_stack[-1]` 只 peek 不 pop，执行在锁外；两个线程可同时取同一 entry，第二个因目标已存在而失败并 `_mark_failed(entry)`，而第一个已成功并把 entry 推入 redo；之后 `skip_poisoned_redo` 会丢弃这个其实有效的 redo 条目（连同其备份）。【确认】（触发需并发 undo 调用，当前 UI 单线程发起）
- 建议：peek 时用"执行中"标记或在锁内先 pop、失败再还栈。

### [P3][一致性] 队列 store 的 created_at/updated_at 持久化了单调钟值，跨重启语义错乱
- 位置：`reconciliation_queue_store.py:370-377`（INSERT 用 `now`=monotonic）、`:433-441`、`:533-538`；驱逐排序 `:340-344` 按 `updated_at ASC`
- 证据：monotonic 是"开机以来"的值，重启后归零；重启前写入的行 updated_at 恒大于新行，导致 LRU 驱逐/快照裁剪与 `snapshot()` 排序失真。【确认】
- 影响：驱逐顺序错（新完成行先被逐）、审计时间戳不可读。正确性影响有限。
- 建议：store 写入统一用 wallclock（`_task_values` 已是正确示范）。

### [P3][一致性] 路径规范化三套标准并存
- 位置：`reconciliation_queue.py:1438-1439`（`_canonical_path`=normcase 小写）vs `:106-114`（payload 的 `canonical_path` 返回保留大小写的 `resolve()`）vs `filesystem_projection_repair_service.py:169`（也保留大小写）；另 `undo_service.py:312-313` 快照 base 保留大小写
- 证据：同一个物理目录，任务去重键是小写化路径，payload/快照内是原大小写路径；restore 回放 `map_path` 产出的大小写与 DB 中既有行可能不一致。【确认】（Windows 大小写不敏感使实际影响小）
- 影响：dedup 键与 payload 指向可能形式不同；跨平台（若未来支持 Linux）会出真实分叉。
- 建议：规范化统一收敛到一个 helper（normcase+resolve）。

### [P3][状态机] 非存储队列 ReconciliationQueueFull 抛出前已删除已完成任务，内存与标记分叉
- 位置：`reconciliation_queue.py:706-712`
- 证据：`del self._tasks[key]` 先执行，`_ensure_capacity_unlocked()` 后抛异常；此时内存丢了该已完成任务而磁盘标记仍保留，下次持久化时静默消失。存储路径因事务回滚无此问题。【确认】
- 影响：仅审计行丢失，容量边界时发生。
- 建议：把删除移到容量保障成功之后。

## 次要问题清单

- `filesystem_projection_repair_service.py:199`：`parent = path.parent if path.exists() else path.parent` 两分支相同，死条件（疑似本意的区分被写丢了）
- `file_operation_service.py:503`：`create_folder` 中 `_refresh_parents` 未包异常保护，非预期索引异常会让"已建成目录"以失败返回
- `file_operation_service.py:646`：`copy_to_directory` 只捕 OSError，`AssetIndexRevisionConflict` 会冲出并中止批量复制（部分结果丢失）
- `file_operation_service.py:140-162`：`_path_locks` 进程级注册表只增不减（每个触及过的路径一个 Lock，永不回收）
- `import_service.py:393-395`：借用 `file_operations._begin_refresh_diagnostics` 重置了该线程的 telemetry operation_id
- `undo_service.py:305-348`：`_snapshot_projection` 三段 SELECT 无事务无 db_write_lock，快照可能跨并发修改不一致
- `file_operation_service.py:574`：POSIX 上 `shutil.move`→`os.rename` 会静默覆盖已存在目标（Windows 拒绝）
- `runtime_events.py:323-328`：路由器 `close()` 的排水等待无超时（对比 `_RouterSubscription.close` 有 2s 上限），卡死的订阅回调会挂起整库关闭
- `reconciliation_queue.py:1365-1377`：`_persist_unlocked` 的冲突恢复在持有队列 Condition 锁时做 `load_snapshot()` DB 读，违背该文件自己立下的"store IO 不进锁"原则
- `reconciliation_queue.py:555-557`：`wait_for_ready(timeout=0)` 走纯内存快速路径不刷新 store（当前调用方用 1.0s，无实际影响）
- `import_manifest_store.py:132-149`：`get`/`list_recovery` 读操作未走 `db_write_lock`，与同文件写路径的锁纪律不一致
- `reconciliation_queue.py:47`：恢复快照上限 256KB/10000 行——重度标签库的 undo 恢复任务会被判 terminal 永不重放
- `file_operation_service.py:366-392`：带 repair payload 的告警同时入队"定向修复 + 全库根重扫"两个任务，定向修复的省力效果被兜底全扫抵消
- `bootstrap.py:544、733-738`：bootstrap 直接读 `library_service._session_generations`、`runtime._condition/_state` 等私有成员
- `context.py:263-266`：已关闭会话再次 `close()` 会重复调用 `_close_callback`（当前无害但契约脆弱）

## 规模与复杂度观察

**Top10 行数**：

| # | 模块 | 行数 |
|---|---|---|
| 1 | reconciliation_queue.py | 1656 |
| 2 | file_operation_service.py | 1257 |
| 3 | reconciliation_queue_store.py | 1228 |
| 4 | asset_index_reconciliation_service.py | 922 |
| 5 | library_service.py | 835 |
| 6 | bootstrap.py | 749 |
| 7 | asset_index_service.py | 744 |
| 8 | undo_service.py | 685 |
| 9 | library_export_io.py | 625 |
| 10 | library_export_service_restore.py | 613 |

（library_export_service 原单文件已拆为 4 个 mixin 模块共 ~2013 行，拆分方向正确）

**超过 150 行的函数**：
- `import_service.import_sources` — 260 行（:179）：收集/规划/清单/复制/刷新/收尾六段混在一函数
- `library_export_service_validate._validate_open_backup` — 234 行（:94）
- `asset_index_service.index_directory_result` — 168 行（:278）
- `library_export_service_export.create_backup` — 163 行（:212）
- `asset_index_reconciliation_service._process_once_attempt` — 157 行（:406）
- `reconciliation_queue_store.enqueue_or_merge` — 156 行（:240）

**应拆分的类**：
- `FileOperationService`（38 方法/1012 行）：文件命令、遥测、对账入队、投影恢复四职并存
- `ReconciliationQueue`（29 方法/1012 行）：每个公开方法都是"store 路径 + JSON 路径"双份实现，建议收拢为 `_store_mutation` 模板方法
- `SQLiteReconciliationQueueStore`（23 方法/1135 行）：每个方法的"事务+CAS+快照重读"样板高度重复
- `AssetIndexReconciliationService`（23 方法/867 行）：worker 监督、租约心跳、完成策略可拆三类
- `UndoService`（40 方法）与 `LibraryService`（37 方法）：后者含开/关/恢复/监听四组状态机

**耦合热点**：`asset_index_reconciliation_service.py:631-668` 反射访问队列私有成员；`import_service.py:197,393,441` 访问 `file_operations` 三个私有成员；`filesystem_projection_repair_service.py:90` 调用 `_clear_deleted_projection`；`file_operation_service.py:1025` 导入 `reconciliation_queue._validate_restore_snapshot` 私有函数——这些跨模块私有访问是重构时的第一优先收敛点。
