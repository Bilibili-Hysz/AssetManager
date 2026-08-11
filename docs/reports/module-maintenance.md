# 模块排 Bug 清单（module-maintenance.md · 2026-08-10 P0 第1轮）

> **状态（2026-08-12）**：全部 18 项已修。Bug 1/2/7/8/10/15 于 P2 轮修复；**Bug 5/6/9/11/12/13/14/16/17/18 于 2026-08-12 修复**（快照锁范围核验、quick_check busy 重试+缓存、run 守卫、锁外复查+批量删除、vacuum 边界拒绝、完成事件失败路径发布）。验证：3338 passed。
> **后续接线项**：维护完成事件的服务端发布已就绪（_publish_completed），UI 订阅（设置页/状态栏）待接线。

> 来源: 只读探索代理审计，行号经源码核对。修复前需第二子代理复核真实性。


# 库导出与数据库维护服务 — 深度缺陷审计清单

审计范围:
- AssetsManager/application/library_export_service.py
- AssetsManager/application/database_integrity_service.py
- AssetsManager/application/database_maintenance_service.py
审计时间: 2026-08-10 (只读, 未修改任何代码)

---

## Bug 1 - 512MB 数据库硬上限使大库备份/恢复永远失败
- 位置: library_export_service.py:160 (上限常量), :731-736 (校验门), :511-518 (create_backup 无条件校验), :1595-1599 (_quick_check_database_file)
- 严重度: 高
- 描述: `_MAX_DATABASE_QUICK_CHECK_SIZE = 512MB`。`create_backup` 生成归档后无条件调用 `validate_backup`(:511-518)；`_validate_open_backup` 对 >512MB 的 DB 成员直接追加错误(:731-736)，导致校验必失败并 raise，备份无法生成。恢复路径 `_quick_check_database_file`(:1595-1599) 同样拒绝 >512MB 数据库。元数据型库超过 512MB 是真实场景（约百万级文件）。
- 触发/复现: 库的 assetmanager.db 超过 512MB 后调用 create_backup / restore_backup，立即失败且无绕过途径。
- 修复建议: 将 quick_check 上限改为可配置（如环境变量/设置项），或对超大库跳过校验/降级为页级抽查；校验失败应区分"策略拒绝"与"大小超限"，允许生成备份并跳过自校验。

## Bug 2 - 目标路径静默覆盖（备份可丢失旧归档，导出可覆盖任意文件）
- 位置: library_export_service.py:385 (export_metadata_json), :520 (create_backup), :376-377 (导出仅防护 db_path), :1826-1831 (_validate_backup_destination 仅拒 data_dir 内)
- 严重度: 高
- 描述: 两处均以 `temporary.replace(target)` 无提示覆盖已存在目标。备份场景：同路径第二次备份会静默销毁先前归档（数据丢失）。导出场景：`export_metadata_json` 只拒绝覆盖 db_path(:376-377)，未拒绝覆盖 RuntimeData 内其他文件（如 favorites.json、recent.json）或用户资产文件，可意外覆盖库内真实文件。
- 触发/复现: 对同一目标路径连续调用两次 create_backup；或将导出目标选为库内既有文件。
- 修复建议: 为 create_backup 增加 exists_ok/overwrite 显式开关（默认拒绝覆盖并报 FileExistsError）；导出目标校验扩展到整个 RuntimeData 目录及库根目录内，仿照 `_validate_backup_destination` 增加 containment 检查。

## Bug 3 - 备份读取源文件时无并发修改检测（撕裂快照自洽通过校验）
- 位置: library_export_service.py:1790-1797 (_write_zip_file 读取循环), :1760-1813
- 严重度: 中
- 描述: `_write_zip_file` 对源文件只做一次顺序读取并计算 sha256，没有 stat(mtime/size) 前后对比；文件在读取期间被并发修改时，归档内容为撕裂混合版本，但其 sha256 与 manifest 自洽，`validate_backup` 必然通过，用户拿到损坏数据且无任何告警。
- 触发/复现: 备份进行中，缩略图/缓存文件被另一个线程写入。
- 修复建议: 读取前/后各做一次 `os.stat`，若 size 或 mtime 变化则重试或将该文件标记为"变更跳过"并在 manifest/报告中记录；读取期间使用文件锁或临时快照。

## Bug 4 - 备份/导出无进度回调与取消机制，UI 线程全程阻塞
- 位置: library_export_service.py:415-533 (create_backup), :367-396 (export_metadata_json), :414 (@session_operation)
- 严重度: 中
- 描述: 两个操作均无进度回调、无取消钩子；`library_settings_adapter.create_backup`(:113-124) 为同步调用，大库备份期间 UI 线程被整段占用（包含 `_snapshot_database`、全目录枚举、逐文件双遍压缩、生成后全量校验），且整个操作持有 session operation lease。无取消时用户只能等待。
- 触发/复现: 对含数万文件/大缩略图目录的库执行备份。
- 修复建议: 增加可选的 progress/cancel 回调参数（按文件计数与字节数上报），由适配器层用工作线程+Qt 信号驱动；lease 改为仅在快照与 publish 阶段持有，枚举/压缩阶段降级为共享读。

## Bug 5 - 快照期间持 db_write_lock 阻塞全库写入
- 位置: library_export_service.py:1682-1687 (_snapshot_database)
- 严重度: 低
- 描述: `source.backup(backup)` 在 `db_write_lock(source)` 内执行，整个 SQLite 快照拷贝期间库内所有写入（标签/备注/缩略图入库）被应用层锁串行阻塞。WAL 模式下 backup API 本身在只读一致快照，无需应用层写锁；大库快照可达分钟级。
- 触发/复现: 大库备份时 UI 同时执行写操作，明显卡顿。
- 修复建议: 去掉 db_write_lock，改为短读锁/不加锁（backup API 自带一致性）；若担心 WAL 膨胀，可在快照前做一次 PASSIVE checkpoint。

## Bug 6 - 备份内嵌 DB 的 quick_check 耗时无界且全程串行
- 位置: library_export_service.py:764-767 (校验内 quick_check), :1584-1589 (_configure_quick_check_connection cache_size=-8MB), :731-736
- 严重度: 低
- 描述: 生成备份后立即对归档内 DB 跑 `PRAGMA quick_check`，且连接配置 8MB page cache(:1589)，512MB 上限内的库也可能耗时数分钟；生成+校验整体串行，无并行/无进度。
- 触发/复现: 数百 MB 库创建备份时长时间无响应。
- 修复建议: 将自校验移到后台任务并上报进度；增大 cache_size 或用 `quick_check(1)` 页抽查模式。

---

## Bug 7 - 存储临时不可见（外置盘未挂载/网络断连）导致批量元数据误删
- 位置: database_integrity_service.py:403-421 (_exists), :285-286 (判 MISSING 入列), :296-305 (复查+DELETE), :281 (全表扫描); 触发链: window.py:84-91 (每次会话应用自动 schedule)
- 严重度: 高
- 描述: `_exists` 中 `candidate.resolve(strict=False)` 在父目录/盘符缺失时不抛异常，`resolved.is_file()` 返回 False 即判 `MISSING`（三态设计只把"抛异常"归为 UNKNOWN，未覆盖"暂时不可见"）。当库根位于外置盘/网络共享且短暂断连时，自动完整性检查（每次打开会话即调度，window.py:86）会把全部 file_meta 行判为缺失并 DELETE(:301-305)，批量丢失用户标签/备注/URL 元数据；复查(:298)在盘仍不可见时同样判 MISSING，无法兜底。
- 触发/复现: 库在 U 盘/网络盘上，检查运行中拔掉盘或断网数秒。
- 修复建议: 对 root 自身先做一次可达性探测（root 不存在/不可访问时整轮中止并记 UNKNOWN）；MISSING 判定增加"父目录存在性"前提，父目录缺失一律 UNKNOWN；或对非本地存储（remote/removable）默认跳过自动清理。

## Bug 8 - 缩略图烘焙文件"先提交后删除"，失败即永久孤儿
- 位置: database_integrity_service.py:353 (commit), :354-358 (commit 后 unlink)
- 严重度: 中
- 描述: `_prune_thumbnail_orphans` 先 `_commit_while_live(conn)` 删除 thumbnail_cache 行，再逐个 unlink 烘焙文件；若 unlink 抛 OSError（被捕获仅告警 :359-360）或进程在 commit 与 unlink 之间崩溃，烘焙文件永久残留——因为 DB 行已删，后续任何清理都无法再发现该文件。文件删除失败也没有计入 issues/报告。
- 触发/复现: 只读文件/杀毒占用导致 unlink 失败，或 commit 后立即断电。
- 修复建议: 先删文件后删行（失败回滚保留行），或对"行已删但文件残留"建立第二次孤儿文件扫描（以 thumb_dir 目录为源，反向核对 cache_key 集合）。

## Bug 9 - 复查-删除非原子（TOCTOU），文件重建后元数据仍被删
- 位置: database_integrity_service.py:298-305, :338-344
- 严重度: 低
- 描述: 复查 `_path_existence` 与 `DELETE` 之间没有原子性；若文件在复查后、DELETE 前被用户/索引器重建，该文件的 file_meta/thumbnail_cache 行仍被删除。
- 触发/复现: 检查进行中，索引器恰好重建了刚被扫描为缺失的文件。
- 修复建议: 把"文件存在性"合并进 SQL 侧再确认成本高；至少将复查与删除紧邻，并在报告里给出删除清单供复核；或对重建概率高的文件（近 5 分钟 mtime 变更）跳过删除。

## Bug 10 - stop() 1 秒超时在慢文件系统上假失败，阻断会话关闭
- 位置: database_integrity_service.py:215-231 (stop), :283-286 (文件存在性循环不可被 interrupt 中断), 影响链: bootstrap.py:589 close_adapters -> runtime.py:118-125 (异常回滚为 open 并传播)
- 严重度: 中
- 描述: `stop()` 通过 `conn.interrupt()` 只能中断 DB 语句；`_prune_missing_metadata`/`_prune_thumbnail_orphans` 的文件存在性循环（网络盘/慢盘，单次 stat 可超 1 秒）无法被中断。`_run_done.wait(timeout=1.0)` 超时即抛 RuntimeError(:227-228)，`LibraryRuntime.close_adapters` 捕获异常后把 runtime 状态回滚为 "open" 并向上传播，会话关闭报 "cleanup is pending; retry close_session"，用户关闭库/退出应用失败，需人工重试。
- 触发/复现: 库位于慢网络盘，关闭库时自动检查正卡在文件扫描循环。
- 修复建议: 为文件存在性循环引入与 cancel_event 联动的可中断等待（如每次 stat 前检查、对慢路径设置超时）；stop() 超时后改为"标记待清理+后台 drain"而非抛异常；或把 stop() 的等待上限与循环粒度对齐。

## Bug 11 - run() 不受 _closed/_running 保护，stop() 后仍可直跑
- 位置: database_integrity_service.py:98-104 (run), :173-213 (schedule 才有守卫)
- 严重度: 低
- 描述: `run()` 是公共方法，不检查 `self._closed` 与 `_running`；`stop()` 之后任何调用方仍可触发一次完整检查（含删除类操作），且与已调度的 pass 并发计数 `_active_runs` 混在一起。
- 触发/复现: 服务关闭后调用方误调 run()。
- 修复建议: run() 开头检查 `_closed`/`_running` 并抛 RuntimeError，与 schedule() 守卫对齐。

## Bug 12 - last_schedule_error 陈旧不清理
- 位置: database_integrity_service.py:177, :180 (拒绝时记录), :233-241 (_run_scheduled 从不重置)
- 严重度: 低
- 描述: `_last_schedule_error` 只在"下一次成功的 schedule()"时被清空(:182)。若最后一次 schedule 因 already_running/service_closed 被拒，错误字符串永久保留；后续自动/手动检查完成后 UI 仍显示过期错误（library_settings_adapter:88 直接透传）。
- 触发/复现: 连续两次 schedule，第一次成功运行中第二次被拒，检查完成后设置页仍显示 "already_running"。
- 修复建议: `_run_scheduled` 完成时在持锁下将 `_last_schedule_error` 置 None（运行期失败改走 report/issues）。

## Bug 13 - quick_check 独立连接 500ms busy_timeout，繁忙时假不健康且无重试
- 位置: database_integrity_service.py:254-275 (_quick_check), :263 (busy_timeout=500)
- 严重度: 低
- 描述: `_quick_check` 用裸连接直连 db 文件，busy_timeout 仅 500ms；若库正被长事务占用（非 WAL 模式或 checkpoint 窗口），`PRAGMA quick_check` 抛 OperationalError，被记为 issues 使整轮检查判不健康，无重试/无 busy 区分。
- 触发/复现: 长事务窗口内触发自动检查。
- 修复建议: 对 "database is locked" 单独归类为可重试（如指数退避重试 2-3 次），或在报告里区分 busy 与真实损坏。

## Bug 14 - 删除循环在 db_write_lock 内执行慢速文件系统 stat，阻塞全库写入
- 位置: database_integrity_service.py:294-306 (_prune_missing_metadata 持锁循环), :298, :334-353 (_prune_thumbnail_orphans)
- 严重度: 低
- 描述: 复查与删除在 `with db_write_lock(conn)` 内进行，每行一次 `_path_existence`（网络盘上可数百 ms）；缺失行多时应用层写锁被长时间占用，UI 的标签/备注写入全部排队。
- 触发/复现: 大库大量缺失行 + 网络盘。
- 修复建议: 先把待删路径在锁外复查完毕，锁内仅做纯 SQL 批量 DELETE（按路径 IN 列表分批），把慢 I/O 移出持锁区间。

---

## Bug 15 - PASSIVE checkpoint busy>0 被误报为失败
- 位置: database_maintenance_service.py:164-172 (success = busy == 0, error="WAL checkpoint is busy")
- 严重度: 中
- 描述: PASSIVE 模式在存在活跃读者（文件列表查询、LAN 会话、完整性检查的裸连接）时返回 busy>0 是正常的部分 checkpoint 结果；当前实现一律 success=False，UI 通过 `_maintenance_error`(library_settings_adapter:160-169) 显示 "WAL checkpoint is busy" 失败，制造假告警。
- 触发/复现: 库处于活跃使用中执行 PASSIVE checkpoint。
- 修复建议: 对 PASSIVE 模式放宽语义（busy>0 但 checkpointed>0 视为部分成功并提示），仅对 FULL/RESTART/TRUNCATE 保留失败判定；或把 busy 计数展示为信息而非错误。

## Bug 16 - 会话已关但服务未关时 schedule() 不记录 last_schedule_error
- 位置: database_maintenance_service.py:192-198
- 严重度: 低
- 描述: `schedule()` 捕获 `_ensure_live_session()` 的 RuntimeError 后，仅当 `self._closed` 为真才写 `_last_schedule_error="service_closed"`；若仅 session 关闭（服务对象未标记 closed），错误记录保持 None/旧值，且抛出的 RuntimeError 消息与记录不一致（"Cannot use a closed LibrarySession" vs "service_closed"），调用方按 last_schedule_error 判断失败原因会得到错误结论。
- 触发/复现: 会话关闭后对同服务调用 schedule()。
- 修复建议: 统一在 except 分支无条件记录（区分 session_closed 与 service_closed 两种原因）。

## Bug 17 - vacuum 恒"不支持"仍走工作线程并被 UI 显示为失败
- 位置: database_maintenance_service.py:174-177 (vacuum), :179-232 (schedule 仍接受 "vacuum"), library_settings_adapter.py:160-169 (_maintenance_error 把 reason 当错误显示)
- 严重度: 低
- 描述: `schedule("vacuum")` 接受该操作并启动 daemon 线程，线程内仅返回 `VacuumResult(supported=False)`；adapter 把 `reason` 字符串当错误展示。设计上"库在使用中不执行 VACUUM"是对的，但 API 表面仍允许调度该操作并产生误导性"失败"，且没有任何维护窗口/时机的协调实现（无 VACUUM 排队、无空闲检测）。
- 触发/复现: 调用 schedule("vacuum")。
- 修复建议: 在 schedule 层直接拒绝 "vacuum"（抛 ValueError 或返回 False 并记录 last_schedule_error），或实现真正的空闲窗口检测后再执行。

---

## Bug 18 - 维护完成无事件发布，UI 通知链缺失
- 位置: database_integrity_service.py:233-241 (_run_scheduled 仅写 _last_report), database_maintenance_service.py:252-276 (_run_scheduled 仅写 _last_result), window.py:84-91 (只调度不订阅完成), library_settings_adapter.py:76-93 (view_model 无任何消费方), settings_dialog.py:57-63 (adapter 仅存储,"for future settings sections")
- 严重度: 中
- 描述: 完整性检查/数据库维护完成后，工作线程只更新内部 `_last_report`/`_last_result` 并打日志，不发布任何事件/信号；`window.py` 在会话应用时仅调用 `schedule()` 后即结束，从未订阅完成或失败通知；`LibrarySettingsAdapter.view_model()` 在代码库中无任何调用方（settings 对话框只保存 adapter 引用），UI 永远无法得知检查完成/失败/健康状态，用户对自动检查结果零可见性。
- 触发/复现: 打开含问题的库，自动检查完成后界面无任何提示（仅日志）。
- 修复建议: 在 `_run_scheduled` 完成后通过 runtime.event_router 或 Qt 信号发布 maintenance_completed/maintenance_failed（携带报告摘要），由设置对话框/状态栏订阅并刷新 view_model；同时补上设置页中 integrity/checkpoint 的实际展示与操作入口。

---

## 检查点结论摘要
- ZIP 打包/大文件内存/流式: 流式与内存有界 OK；发现: 无进度/取消(Bug 4)、无并发修改检测(Bug 3)、快照持锁(Bug 5)、512MB 上限(Bug 1)。
- zip slip/符号链接: 生成与校验/恢复侧均有 containment 与 link/junction 防护，未发现穿越漏洞。
- 目标路径覆盖: Bug 2（备份静默覆盖 + 导出仅防护 db_path）。
- 导出内容完整性: 校验与 manifest 交叉核对严谨；隐患为撕裂快照自洽(Bug 3)。
- 完整性检查 SQL/悬空引用: SQL 简单正确；缺陷集中在文件存在性判定(Bug 7)、清理顺序(Bug 8)、TOCTOU(Bug 9)。
- 修复事务/备份: 事务与回滚正确；缺"文件删除失败可发现性"(Bug 8)。
- 大库性能: Bug 6、Bug 13、Bug 14。
- 检查与写入并发(WAL 快照): 快照本身一致；写锁内慢 I/O(Bug 14)、busy 假阳性(Bug 13)。
- schedule 机制/last_schedule_error: Bug 12、Bug 16。
- VACUUM/清理时机与并发: 主动拒绝设计合理，但 API 表面矛盾与缺维护窗口(Bug 17)。
- 孤儿目录/文件清理安全性: 目录隔离 OK；烘焙文件清理顺序缺陷(Bug 8)。
- 缩略图缓存清理策略: Bug 8、Bug 9。
- 统计更新: 无(未涉及 library_stats 更新，见检查点"无"说明)。
- 错误处理/部分失败: 事务回滚、取消语义正确；stop 超时假失败(Bug 10)、异常全吞为 issues(Bug 11 相关)。
- 事件/UI 通知链: Bug 18。

