# 模块排 Bug 清单（module-core-db.md · 2026-08-10 P0 第1轮）

> **状态（2026-08-12）**：全部 16 项已修。Bug 3/4/7 于 P2 轮修复；**Bug 1/2/5/6/8/9/10/11/12/13/14/15/16 于 2026-08-12 修复**（Bug 1/2 确认已在 ebf2514 修复仅补回归测试；Bug 8 与 core-store Bug 5 同源已修）。亮点：_WriteGate 双向死锁快速失败、迁移进程内互斥+重试、离线库 orphan 保护（recent_libraries 清单）、40-bit 碰撞二级探测。验证：3361 passed。

> 来源: 只读探索代理审计，行号经源码核对。修复前需第二子代理复核真实性。


# Core DB / 路径基础设施缺陷审计清单（只读 explore）

> 范围: AssetsManager/core/{database,db_migrations,library_lock,path_resolver,config_migrator}.py
> 教训参照: identity 标记不可靠（RuntimeData 测试残留污染），审计重点为状态与标记的失败路径。

## Bug 1 - migrate_path_metadata 大小写不对称 DELETE 导致元数据整子树丢失（Windows 大小写重命名）
- 位置: AssetsManager/core/database.py:1030-1043（file_tags SELECT/INSERT/DELETE）、1045-1067（file_meta）、1069-1090（library_favorites）；根因在 AssetsManager/core/path_resolver.py:70（remap_path_subtree 大小写敏感 startswith）
- 严重度: 高
- 描述: SELECT 用 `file_path=? OR file_path LIKE ?`（SQLite LIKE 对 ASCII 大小写不敏感，`=` 大小写敏感），而 remap_path_subtree 的 `current.startswith(old+sep)` 大小写敏感。当库内键实际大小写与传入 old_path 不同（典型：用户在资源管理器做纯大小写改名 "Assets"→"assets" 后，应用再对该文件夹执行 move），LIKE 命中旧键，remap 返回未改变的原路径 → INSERT OR IGNORE 变成 no-op → 随后的 DELETE（LIKE 大小写不敏感）把刚插入的新大小写行与旧行一并删除 → file_tags/file_meta/library_favorites 该子树全部行丢失且无提示。
- 触发/复现: Windows 下对已打标签目录做外部纯大小写改名，再用应用 move/rename 该目录；或 DB 键与 old_path 大小写不一致的任何场景。
- 修复建议: DELETE 与 remap 使用同一匹配语义（键按 normcase 存储，或仅删除 remap 后键确实变化的行）；先 DELETE 后 INSERT 且 INSERT 失败时保留原行；SELECT 与 DELETE 同时加 COLLATE NOCASE。

## Bug 2 - 身份 map_key 依赖 resolve()：symlink/junction 根"存在性切换"产生双 RuntimeData 槽位
- 位置: AssetsManager/core/path_resolver.py:86-97；使用方 AssetsManager/core/database.py:377-381、578-586
- 严重度: 中
- 描述: root_identity 在路径存在时 display = resolve(strict=True)（跟随符号链接/接合点），不存在时只解析父目录（保留词法路径）。同一物理库在"目标在线/离线"两状态下 map_key 不同 → library_data_name/库路径/身份标记均不同 → 离线期间会创建第二个空库目录并发布新 identity 标记；目标恢复后应用回到原槽位，离线期间写入的数据全部"消失"（分散在另一槽位）。Windows 接合点/外接盘场景真实可达。
- 触发/复现: 通过 junction/符号链接打开的库，链接目标临时不可达时再次 open_library。
- 修复建议: 身份基准使用稳定词法规范化键（normcase+normpath+abspath，不 resolve 符号链接），或在 identity 标记中记录链接目标的持久标识；对存在性切换做一致性校验而非静默新槽位。

## Bug 3 - sqlite3.connect 未设置 busy_timeout：跨进程/LAN 并发写 5 秒后裸抛 "database is locked"
- 位置: AssetsManager/core/database.py:616
- 严重度: 中
- 描述: 连接以默认 5s busy timeout 打开（connect 未传 timeout，也未执行 PRAGMA busy_timeout）。WAL 模式下跨进程（LAN 访问同一库文件、双实例）写竞争时等待超时后直接抛 sqlite3.OperationalError("database is locked")，无排队、无提示、无重试；GUI/工作线程直接收到原始异常。
- 触发/复现: 两个进程同时写同一 assetmanager.db（tests/lan/test_concurrent_db_access.py 已有并发写场景）。
- 修复建议: connect 时传 timeout=30（或 PRAGMA busy_timeout=30000），并对 OperationalError 增加有限重试与失败降级路径。

## Bug 4 - config_migrator 对未来版本配置静默降级盖章 _cfg_version
- 位置: AssetsManager/core/config_migrator.py:34-42（尤其 41 行无条件写 CURRENT_VERSION）
- 严重度: 中
- 描述: 当 settings.json 的 _cfg_version 大于 CURRENT_VERSION（由更新版本写过），while 循环不执行任何迁移，但最后无条件把版本戳改写成当前版本（如 99→2）。较新版本应用再次打开该配置时会把已是新形态的数据再跑一遍旧迁移 → 迁移非幂等时数据损坏；旧版本还会持久化这个降级后的版本戳。
- 触发/复现: 用新版本写入 _cfg_version=99 的 settings.json，再用本版本 migrate() 并 save。
- 修复建议: _cfg_version > CURRENT_VERSION 时拒绝迁移并保留原版本戳（或抛错），不要降级盖章。

## Bug 5 - 版本表并发：双 DatabaseManager 实例同时迁移同一库 → 版本行主键冲突/互踩
- 位置: AssetsManager/core/db_migrations.py:448-453（_record）、874-939（migrate）
- 严重度: 低
- 描述: migrate() 无文件级跨进程协调；LibraryLock 只在 service 层生效。两个 DatabaseManager（tests/unit/test_library_service.py:365-380；compat 路径 database.py:1122 的 ThreadSafeSingleton 第三实例 vs DI 注入实例）同时打开同一库时，各自在 savepoint 中 INSERT 相同 version → PRIMARY KEY 冲突（或 busy）→ 一方 open_library 失败且错误信息不明确；失败回滚后无重试。
- 触发/复现: 同一进程内两个 manager 实例并发 connection_for(同一root)。
- 修复建议: 迁移加进程内全局互斥（模块级锁）或 INSERT OR IGNORE + 重读 history 验证；失败时重试一次。

## Bug 6 - _WriteGate 自死锁：无参 db_write_lock() 嵌套在带 conn 形式内部
- 位置: AssetsManager/core/database.py:914（conn 形式持有 _write_gate.read()）与 942-943（无参形式取 _write_gate.write()）
- 严重度: 低
- 描述: 线程若已通过带 conn 形式进入（持有 read 凭证，_readers>0），再调用无参形式，write() 等待 _readers == 0，而自己正是读者 → 永久阻塞。目前应用代码无此嵌套（仅测试嵌套无参+无参，走 reentrant write 分支），属潜在死锁。
- 触发/复现: 未来代码在 `with db_write_lock(conn)` 块内调用无参 `db_write_lock()`。
- 修复建议: 在 write() 中检测当前线程持有 read 凭证并拒绝/升级，或移除无参形式（legacy 兼容已无应用调用方）。

## Bug 7 - _cfg_version 类型未校验：str/float/None 使整个 settings 加载失败或静默接受
- 位置: AssetsManager/core/config_migrator.py:35-37
- 严重度: 低
- 描述: `ver = settings_data.get("_cfg_version", 0)` 后直接 `ver < CURRENT_VERSION`。若值为字符串（如 "1"）→ TypeError 向上传播，settings.load 的 except 吞掉后 self._data 为空，应用全部设置丢失；若为浮点（2.5）→ 静默接受并盖章 2。
- 触发/复现: settings.json 中 _cfg_version 被手改/损坏为非 int。
- 修复建议: 强制 int() 转换并校验（失败时按 0 处理或回退备份），浮点先校验整数值。

## Bug 8 - 迁移结果不持久化：settings.load 迁移后不置 dirty，版本盖章每次启动重跑
- 位置: AssetsManager/core/config_migrator.py:41（盖章契约）；调用方 AssetsManager/core/settings.py:90-92
- 严重度: 低
- 描述: load() 中 `data = migrate(data); self._data.update(data)` 后不设置 self._dirty → 迁移后的 _cfg_version 与新增键（如 search_history）不会被保存（除非后续其它修改触发 save）。每次启动重复执行迁移（当前幂等所以无害，但版本戳机制形同虚设，一旦未来迁移非幂等即出问题）。
- 触发/复现: 旧版本配置文件首次加载后立即退出，settings.json 仍为旧版本戳。
- 修复建议: 在 load() 检测到版本变化时置 _dirty 并 save。
## Bug 9 - library_data_name 40-bit 摘要碰撞：fail-closed 但该库永久无法打开
- 位置: AssetsManager/core/path_resolver.py:128（sha256[:10]=40bit）；对比 146 行 lock 用 [:16]=64bit
- 严重度: 低
- 描述: 数据目录名仅取 40 bit。万级库规模下碰撞概率约 4.5%（n=10000）；碰撞时 _ensure_library_data_identity 检测到不同 identity 的 marker → RuntimeError，库永远打不开（无自动换名/重哈希路径）。碰撞本身被 fail-closed 拦截（不会静默串数据），但无恢复手段。
- 触发/复现: 构造两个 map_key 相同 40-bit 前缀的库（约 100 万次尝试可命中）。
- 修复建议: 摘要加长到 64-128bit（与 lock 一致），或碰撞时生成二级探测名而非直接拒绝。

## Bug 10 - legacy 目录迁移 TOCTOU：并发双进程迁移竞态，败者无重试
- 位置: AssetsManager/core/database.py:587-607（open_library）、991-1007（get_library_dir）
- 严重度: 低
- 描述: `legacy_dir.exists()` 检查与 `shutil.move` 之间无原子保证：两个进程同时打开同一库且 legacy 目录尚在时，两者都通过 exists 检查，一方 move 成功后另一方 move 抛 OSError → RuntimeError（fail-closed，不损坏数据），但调用方无重试，库打开失败。
- 触发/复现: 绕过 LibraryLock 的双进程同时首次打开含 legacy 目录的库。
- 修复建议: 失败时检测 lib_dir 已存在且内容一致则视为成功（幂等迁移），或对 OSError 增加一次重试/二次确认。

## Bug 11 - clean_orphan_dirs 对离线库的 legacy 目录 7 天后隔离（数据"消失"体验）
- 位置: AssetsManager/core/database.py:842-844（known_names 仅含"当前存在"的根）、860（7 天 cutoff）、884-899
- 严重度: 中
- 描述: known_names 的 legacy 名集合只收录 `Path(r).exists()` 的根；外接盘/未挂载库的 legacy 数据目录（未带 .identity 标记的老布局）在 7 天后被视为孤儿移入 _orphaned。库恢复在线后应用按 hashed 目录重建空库，用户数据看似丢失（实际在 _orphaned，但恢复路径不透明）。identity 标记目录受 marked_names 保护，不受影响。
- 触发/复现: 带 legacy 布局目录的库离线 >7 天后重新上线。
- 修复建议: legacy 名保护也基于配置/注册表里的库清单而非仅"当前存在"；隔离前增加二次确认或延长 cutoff。

## Bug 12 - LibraryLock 注册表键未规范化：同进程同一锁文件不同字符串形式 → 误报 LibraryAlreadyOpenError
- 位置: AssetsManager/core/library_lock.py:28-35（`_key = str(self.path)`）
- 严重度: 低
- 描述: 注册表按原始字符串寻址；相对/绝对、大小写、符号链接不同的写法指向同一锁文件时 registry 命中失败，第二个 QLockFile tryLock 在同一进程内失败 → 抛 LibraryAlreadyOpenError（自锁误报）。当前调用方均经 library_lock_path() 规范化，风险仅为未来调用方。
- 触发/复现: `LibraryLock("RuntimeData/Shared/x.lock")` 与 `LibraryLock(绝对路径)` 同进程先后创建。
- 修复建议: `_key = os.path.normcase(os.path.abspath(os.fspath(self.path)))`。

## Bug 13 - 迁移历史名称/版本强校验无修复路径：任何历史迁移改名即永久拒绝打开库
- 位置: AssetsManager/core/db_migrations.py:319-357（_validate_history 名称/连续/重复校验）
- 严重度: 低
- 描述: schema_migrations 中记录的 name 必须与 MIGRATIONS 完全一致、版本必须从 1 连续；一旦未来某次重构改名/重排历史迁移（v1~v23 名称未冻结），所有既有库将永久抛 MigrationHistoryError，且无"按版本号忽略名称"或修复工具。当前 v1-v23 名称与记录一致，属约束性风险。
- 触发/复现: 未来修改 MIGRATIONS 中任一历史 name 后打开旧库。
- 修复建议: 在文档/CI 中断言历史迁移元组（version,name）不可变；校验失败时提供显式 repair 路径。

## Bug 14 - 空/退化根路径映射到共享 _temp 与 Shared/.identity 槽位
- 位置: AssetsManager/core/path_resolver.py:119（library_data_dir）、132-135（identity 路径）、153（legacy_library_data_dir）
- 严重度: 低
- 描述: library_root 为空时所有空根共用 RuntimeData/_temp（数据目录与 legacy 目录相同），identity 标记路径退化为 Shared/.identity —— 所有空根共享同一槽位，一个空根库发布标记后其它空根库全部判定 collision 拒开；_temp 也不在 clean_orphan_dirs 保护清单内。退化输入（如 get_library_stats("")、db_path("")）可触发。
- 触发/复现: 以空串/None 调用 library_data_dir/db_path。
- 修复建议: 在入口层拒绝空根（raise ValueError），或为退化路径分配确定性独立槽位。

## Bug 15 - 兼容路径经 ThreadSafeSingleton 创建第三个 DatabaseManager：与 DI 实例并发连接同一库
- 位置: AssetsManager/core/database.py:1119-1127（migrate_path_metadata_for_library）、1138-1140（close_all_dbs）、1147-1155（get_library_stats）
- 严重度: 低
- 描述: bootstrap.py:268 的 DatabaseManager 是 DI 容器实例，而 compat 辅助函数走 ThreadSafeSingleton.get(DatabaseManager)（独立实例）。二者对同一库各持一条 sqlite 连接（check_same_thread=False），db_write_lock 按连接各自加锁 → 对同一 DB 文件的写互相不受应用锁约束，叠加 Bug 3 的 busy 超时风险。目前这些 compat 入口仅在无 session 的旧调用路径使用。
- 触发/复现: 无 session 场景调用 migrate_path_metadata_for_library，同时 session 路径持有同一库连接。
- 修复建议: compat 函数改为从容器/单例统一获取同一 manager，或显式注册 ThreadSafeSingleton 实例与 DI 共用。

## Bug 16 - thumbnail 迁移在 new_file 已存在时静默删除旧缩略图（无重新生成）
- 位置: AssetsManager/core/database.py:1100-1109
- 严重度: 低
- 描述: `if new_file.exists(): old_file.unlink()` —— 目标缩略图已存在时直接删除被移动文件的旧缩略图且不触发重新生成；随后 `UPDATE OR REPLACE` 用旧行（source_mtime/source_size 为旧源文件值）覆盖 new_key 行。若 new_file 实际属于另一源文件，磁盘内容与行数据不一致 → 错误缩略图或缓存失效。
- 触发/复现: 移动到目标路径已缓存同 key 缩略图的场景。
- 修复建议: new_file 存在且属于不同源时保留两者并令缓存失效触发重新生成，而非 unlink 后覆盖行。

---

# 检查点结论
- database（连接池/WAL/锁/归还/库路径/身份标记/旧目录迁移）: 发现 Bug 1/2/3/5/6/10/11/14/15/16；连接归还与 close 竞态、身份标记 no-clobber/崩溃释放/目录 flush 均正确，未发现问题。
- db_migrations（幂等/历史 DDL 冻结/中途失败/版本表并发）: 发现 Bug 5/13；savepoint 回滚与 v1~v23 可重放性核对无误，历史 DDL 快照（V8/V16）使用正确。
- library_lock（跨进程锁/崩溃释放/同进程重入）: 发现 Bug 12；崩溃后 OS 锁自动释放 + setStaleLockTime(0) 的取舍有注释说明，同进程重入引用计数正确。
- path_resolver（规范化/大小写/哈希/legacy 边界/特殊字符）: 发现 Bug 1/2/9/10/14；`.`/`..` 经 normpath 折叠正确（无问题），map_key 使用 normcase 正确。
- config_migrator（类型转换/缺失值/循环迁移）: 发现 Bug 4/7/8；循环迁移无问题（while 单调递增必然终止），缺失值由 setdefault 兜底但类型不校验。

