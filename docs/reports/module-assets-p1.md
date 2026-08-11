# 模块排 Bug 清单（module-assets-p1.md · 2026-08-11 P1 第1轮）

> 来源: 只读探索代理审计（ZCode Explore），行号经源码逐一核对，调用点经 grep 交叉验证。
> 范围: asset/metadata/thumbnail/search/project/asset_index/asset_index_reconciliation/favorite/gallery + core/directory_cache、core/project_data + library_export_service（已知项核实）+ lan/server.py:1502（已知项核实）。
> 结果: 19 项（高 0 / 中 10 / 低 9）；已知 3 项交接问题全部核实为仍存在（1 项部分修复）。

## 缺陷清单

### 中（10）

**M6a-1 — 目录大小/库总大小缓存绕过 ProjectData TTL（已知项 #1：仍存在）**
- 位置: `application/metadata_service.py:260-288`（热路径）、267-270（库总大小）、274-281（目录大小）、282（ProjectData.compute_dir_size 静态调用）;`core/project_data.py:16`（_SIZE_CACHE_TTL_SECONDS=30）、175-180（TTL 判定）、160-184（ProjectData.get_dir_size）
- 描述: TTL 只存在于 ProjectData.get_dir_size,而生产代码无任何调用方（grep 全库确认）。热路径 MetadataService.get_dir_size 读持久化 cached_size 时仅比较目录 mtime: Windows 上文件内容就地编辑（大小、mtime 都不变的覆盖写）目录 mtime 不变 → 过期大小无限期返回;库根路径（267-270）连 mtime 都不查。LAN 侧长期显示过期总量。"就地编辑不刷新"bug 未修,G1 轮的 TTL 是死代码。
- 修复: MetadataService 加实例级 _size_cache_ts: dict[str, float],get_dir_size 在 cached[1] >= current_mtime 通过后追加 now - ts < 30s 判定（复用 project_data.py:16 常量）,重算处与 set_dir_size 更新 ts;库根路径同样用根键 TTL,或直接委托 session.context.project_data.get_dir_size（TTL 已实现）。

**M6a-2 — _scan_dir_summary 扫描异常吞掉整个循环并把部分计数写入缓存**
- 位置: `application/asset_service.py:355-372`（360-361 entry.is_file()、364-365 except OSError: pass、367-372 无条件 cache.set）
- 描述: os.scandir 后某条目在 is_file() 时消失（Windows 并发删除/下载中文件真实可达）→ OSError 中止整个 for 循环 → count 为部分值、preview 可能为 None → 仍把 (部分计数, 当前 mtime) 写入缓存 → 该目录计数/预览在 mtime 变化前持续错误。静默错误持久化。
- 修复: 单条目 try/except 继续而非整体中止;用完成标志控制缓存写入（未完整扫描不落缓存）;或异常时返回未缓存结果。

**M6a-4 — process_image: CMYK/P;I;16 模式保存 WEBP 必败,缩略图静默缺失;模糊先于缩放;无 EXIF 方向**
- 位置: `application/thumbnail_service.py:252-263`（Image.open → filter(GaussianBlur(15)) → resize → save(format="WEBP")）
- 描述: Pillow WEBP 编码器不支持 CMYK/P（透明调色板）等模式,save 抛 OSError → 264-265 捕获后返回 None → LAN 缩略图 404 或降级原图。设计稿（CMYK JPEG）是常见输入。附带: GaussianBlur(15) 在全分辨率原图上执行（253-254）后 259 行才缩放——6000px 大图每次缩略请求数秒;且全程未应用 EXIF 方向,手机照片缩略图旋转。
- 修复: save 前 img.convert("RGBA" if has_alpha else "RGB");先 resize 到 max_size 再按需模糊;ImageOps.exif_transpose(img)。

**M6a-8 — get_home 每次请求全表扫描缩略图元数据 + 每行 2 次 stat**
- 位置: `application/project_service.py:441-500`（_attach_baked_thumbnails,451 list_all_with_metadata() 全表、470/475 每行 source.stat()+baked.stat()）
- 描述: LAN 首页每请求全量 thumbnail_metadata 行（数千~数万）+ 每行 2 次 syscall + resolve;大库首页耗时秒级,与 gallery 首页全树遍历叠加。每请求无界全扫描。
- 修复: repository 增加按 project_paths 前缀过滤的查询（SQL parent 前缀匹配）,或先命中 directory_cache 预览再仅对缺失项目回退 baked 查询;baked 行按 project 路径建索引。

**M6a-9 — reconciliation: 操作超 worker_max_operation_age（300s）后即使已提交成功也判 stale,大库任务永不收敛**
- 位置: `application/asset_index_reconciliation_service.py:395`（renew_until 固定）、447-463（completion_timestamp >= renew_until → _stale_completion_noop → 抛 PersistenceError）、618-624（心跳续租有效时返回 None → 不承认成功）
- 描述: 心跳持续续租 DB 租约,但 renew_until 不随续租前移。index_directory_tree_result 在单事务内已提交树发布后,完成检查发现超龄 → 任务被 mark_retryable → 下次 claim 重扫全树 → 对扫描恒 >300s 的库无限重扫、任务永远 SUCCEEDED 不了。
- 修复: 完成时若 result.committed is True,跳过超龄判定直接按已提交 revision mark_succeeded;超龄判定仅用于未提交/未发布的结果。

**M6a-12 — library_export 残留硬上限: 1GB/成员、8GB/总量、1 万文件（已知项 #2a：仍存在）**
- 位置: `application/library_export_service.py:159`（_MAX_MEMBER_SIZE=1GB,执行点 1821、926、1535、955）、162（_MAX_EXPANDED_SIZE=8GB）、155/157（_MAX_ARCHIVE_MEMBERS=10000/_MAX_MANIFEST_FILES=9999）;"512MB 上限移除"仅落实为快检跳过: 160 + 784-787（database_quick_check="skipped"）
- 描述: create_backup 遇到 >1GB 单文件、展开总量 >8GB、或 RuntimeData 文件数 ≥1 万（含 .thumbnails 时很容易达到）仍整体抛 ValueError 中止。与既定"大库可备份"目标相悖。
- 修复: 按目标提高/移除成员与总量上限（保留成员数上限但大幅上调并给出明确错误信息）,或至少把上限提升到"快检跳过"同等的量级并在文档/错误信息中注明。

**M6a-13 — 并发修改检测 stat 与读取句柄不一致: rename-over 盲区 + 持续写入文件 3 次重试后整备份中止（已知项 #2b：仍存在）**
- 位置: `application/library_export_service.py:1806-1837`（句柄在 1806 只开一次;before=source.stat() 1818、读、after=source.stat() 1827 均为路径 stat;重试仅 input_stream.seek(0) 1837,不复开路径;attempts >= 3 1833-1836 抛 ValueError）
- 描述: (1) rename-over: 文件被替换后句柄仍读旧 inode,before/after 却 stat 新路径——重试永远读旧内容,3 次后整个备份中止;若新文件恰好同 size+mtime_ns 则静默打包旧内容。(2) 持续写入文件每次 before≠after → 3 次后中止整个备份而非跳过该文件。
- 修复: 重试时重新 open 路径（并重做 _assert_real_contained）;变更超阈值时跳过该文件并记 warning 而非中止整备份;把"读取句柄"与"校验快照"绑定（读句柄的 fstat 与内容校验,而不是路径 stat）。

**M6a-14 — 取消检查点未覆盖校验段（已知项 #2c：仍存在）**
- 位置: `application/library_export_service.py:530-534`（最后一个 should_cancel 在 530-531,随后 532-534 validate_backup(temporary) 无取消点;_validate_open_backup 589-813 与 _inspect_archive_member 940-975 逐成员解压校验）
- 描述: 生成备份后对临时文件做全量解压校验（8GB/1 万成员可达分钟级）,期间用户取消无效;校验还是全量二次 I/O。
- 修复: 给 _validate_open_backup/_inspect_archive_member 传入 should_cancel,每成员（或每 1MB 块）检查并抛"Backup cancelled"。

**M6a-15 — 快照全程持 db_write_lock（已知项 #2d：仍存在）**
- 位置: `application/library_export_service.py:1702-1714`（with db_write_lock(source): source.backup(backup) 1705-1712,SQLite 页级复制全程持锁）
- 描述: 备份期间进程内所有经该连接/门锁的 DB 写（LAN 用户改 notes、标签、收藏等）被阻塞整个快照时长;大 DB 快照可达秒~十秒级。
- 修复: 用独立只读连接做 backup（WAL 下 backup API 自身保证一致性快照）,锁内只做连接初始化/校验;或分页分批释放锁。

**M6a-16 — _has_active_users 无负缓存: DB 故障期间每请求一次失败查询 + 全堆栈日志洪水（已知项 #3：仍存在）**
- 位置: `lan/server.py:1502-1526`（函数体;成功缓存 1519-1520;except Exception 1522-1526 不写缓存且 _log.exception 全堆栈;缓存字段 327-329 TTL=30s）;调用点: 中间件 1689（每请求）+ auth_status 941
- 描述: DB 故障期间只有成功才写缓存,失败每次请求都重跑失败查询并打印完整 traceback → 日志洪水 + 故障期间 DB 被每请求锤一次。fail-closed 的 return True 本身正确。
- 修复: except 分支写负缓存（self._has_users_cache = True; 时间戳 now,让 fail-closed 决策享受同一 30s TTL）;日志降级为 warning 且 TTL 窗口内只记一次。

### 低（9）

**M6a-3 — list_directory 中 entry.is_dir() 无 OSError 保护,扫描中文件消失导致整个目录列表 500**
- 位置: `application/asset_service.py:277`（_summary_cache_entries 列表推导）与 221（_entry_to_item）
- 修复: 两处包 try/except OSError（按不存在处理,跳过该条目）。

**M6a-5 — _check_blur 的 fail-open 分支与注释意图相悖（当前不可达,防御性缺口）**
- 位置: `application/thumbnail_service.py:277-283`（if db_conn is None: return False,注释声称"不可把 provider 不可用解释为不需要模糊"）
- 描述: 已核实 LAN 两个调用点均传 library_root,bootstrap 构造为 session 绑定,目前不可达;但任何未来调用方漏传 library_root 即静默放行 NSFW 原图。
- 修复: library_root 为 None 且 blur_tags 非空时抛 ValueError（fail-closed）,与注释意图一致。

**M6a-6 — search_by_tags 多标签命中重复结果**
- 位置: `application/search_service.py:363-386`（for tag in tags 循环直接 append,无去重）;对比 SearchResultSet.merge（192-196）有去重而此路径没有
- 修复: 循环内按 rel 去重（或用 set 收集后排序）。

**M6a-7 — ProjectService.list_projects / get_project_detail 服务层无路径包含校验（仅依赖路由层）**
- 位置: `application/project_service.py:243-244`、568-569（Path(target).resolve() 后无 is_relative_to）
- 修复: 与 asset_service.py:97-98 一致,加入 if not target.is_relative_to(root): raise ValueError(...)。

**M6a-10 — ProjectDepthConfig 无界配置导致递归深度失控**
- 位置: `application/project_service.py:31-36`（from_dict 直接 int(...)）、383/391-393（_collect_projects 递归）、533-536、631-636
- 修复: clamp 到 [1, 32]（含 branch_depths 值）,非 int 拒绝或取默认。

**M6a-11 — DirectoryCache 写路径无条件 commit,可能提前提交调用方外层事务（潜伏）**
- 位置: `core/directory_cache.py:104、118、124、130`（set/set_batch/invalidate/clear 内 self._conn.commit()）
- 描述: 连接为共享会话连接;metadata_service.py:182-195 注释明示存在"保留外层事务"的 repository 用法;当前热路径无外层事务,属潜伏。
- 修复: 写前检测 conn.in_transaction 且事务非本模块开启时跳过 commit（或缓存改用独立连接）。

**M6a-17 — 资产索引扫描包含隐藏文件,与显示计数口径不一致**
- 位置: `application/asset_index_service.py:235-259`（_scan_directory_entries 无 name.startswith(".") 过滤）;对比 project_service.py:764、_batch_warm_file_counts 316、asset_service.py:357 均排除隐藏文件
- 修复: 索引扫描与展示口径统一（跳过 "." 开头条目,与 quick_search 754 行一致）。

**M6a-18 — index_directory_result 非 force 快路径 SKIPPED: 目录磁盘内容已变也不重扫**
- 位置: `application/asset_index_service.py:285-319`（count_by_parent(target) > 0 → SKIPPED,不校验目录 mtime/内容）
- 描述: 当前生产调用方均传 force=True,故为潜伏;任何忘传 force 的调用方会静默拿到陈旧索引。
- 修复: SKIPPED 分支对比 os.stat(target).st_mtime 与条目最大 mtime,变化时继续扫描。

**M6a-19 — _REFRESH_LOCKS 全局字典键永不清理**
- 位置: `application/asset_index_service.py:26-44`（按 map_key 存 RLock,无删除路径）
- 修复: 会话 close 时移除键,或改用 WeakValueDictionary。

## 检查点结论（无问题项 / 已修复核实）

1. revision CAS — 已修复: asset_index_repository.py:262-287（_advance_revision(expected=...) + IntegrityError 处理）与 replace_parent_entries 458-476;asset_index_service.py:359-367/504-513 STALE 路径完整。
2. moved_pairs — 已修复: file_operation_service.py:58、522-562、panels/file_list/_actions.py:203。
3. blur 判定 — 已修复（存在一处不可达 fail-open,见 M6a-5）。
4. 越界拒绝 — 已修复（project_service 服务层例外,见 M6a-7）: asset/metadata/favorite/search（commonpath+normcase 双保险）/asset_index/gallery（含逐组件 reparse 检查）均覆盖。
5. SQL 全部参数化;LIKE 通配符转义正确。
6. favorite_service — 无缺陷: owner_key 校验、路径包含、根目录拒绝、上限 500、不存在/不支持目标过滤均正确。
7. gallery_service — 无独立缺陷: 遍历预算、reparse 逐组件防护、resolve 后复检、路径规范化完整。
8. scanner 路径无泄漏: lan/scanner.py:45 存相对路径。
9. thumbnail_cache_key / directory_cache mtime 失效: 键含 resolve+mtime（有界 8192）、条目 mtime 比对正确。
10. 项目树/首页深度语义: _collect_projects/_scan_tree/_entry_to_item 的 branch_depths 覆盖逻辑一致。

## 修复分组（按文件集互不相交）

| 组 | 文件集 | 项 |
|---|---|---|
| A | metadata_service.py、core/project_data.py | M6a-1 |
| B | asset_service.py、core/directory_cache.py | M6a-2、3、11 |
| C | thumbnail_service.py | M6a-4、5 |
| D | search_service.py | M6a-6 |
| E | project_service.py | M6a-7、8、10 |
| F | asset_index_service.py、asset_index_reconciliation_service.py | M6a-9、17、18、19 |
| G | library_export_service.py | M6a-12、13、14、15 |
| H | lan/server.py | M6a-16 |
