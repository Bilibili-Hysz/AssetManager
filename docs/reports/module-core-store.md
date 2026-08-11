# 模块排 Bug 清单（module-core-store.md · 2026-08-10 P0 第1轮）

> **状态（2026-08-12）**：全部 27 项已修。Bug 1/2/6/8/11/14 于 P2 轮修复；**Bug 3/4/5/7/9/10/12/13/15/16/17/18/19/20/21/22/23/24/25/26/27 于 2026-08-12 修复**（Bug 16/27 确认已修仅补测试；Bug 23 的 normcase 否决——跨组件键契约，实证 Path.resolve 已归一大写）。验证：3263 passed。
> **跨组件协调项（独立批次）**：ProjectData._key 与 MetadataRepository._path_key 的键归一未统一（normcase 会破坏契约）；color_utils/format_utils 的陈旧 .pyd 遮蔽源码（cache.pyd 已删）。

> 来源: 只读探索代理审计，行号经源码核对。修复前需第二子代理复核真实性。


# Core 配置/存储/标签基础设施缺陷审计清单（M8, 2026-08-10）

范围：settings.py / json_store.py / cache.py / directory_cache.py / tag_store.py / tag_library.py / project_data.py / schema_defs.py / protocols.py / singleton.py

## Bug 1 - settings.save() 仅捕获 OSError：JSON 序列化/编码异常逃逸且临时文件泄漏
- 位置: AssetsManager/core/settings.py:126-152（json.dumps 在 134 行，except OSError 在 145 行）
- 严重度: 中
- 描述: `save()` 的异常处理只覆盖 OSError。`set()`/`set_list()` 对未知键不校验类型，`_data` 可含不可 JSON 序列化的值（set、Path、自定义对象等），此时 `json.dumps` 抛 TypeError；`f.write` 也可能抛 UnicodeEncodeError。这些异常均非 OSError，会直接冒泡：临时文件（`tempfile.mkstemp` 已创建）不清理而残留；调用方（如 window.py:545 `AppSettings.instance().save()`）崩溃；进程退出时 `_atexit_save` 也会抛异常。
- 触发/复现: `s.set("custom_key", {"set_obj"})` 后调用 `s.save()` —— TypeError 逃逸，磁盘残留 `settings_*.tmp`。
- 修复建议: 捕获 `(OSError, TypeError, ValueError, UnicodeError)`；finally 中统一清理 tmp；或在 `set()`/`set_list()` 写入前做 JSON 可序列化预检。

## Bug 2 - settings.load() 遇损坏 settings.json：静默空数据、不修复文件、跳过 legacy 迁移
- 位置: AssetsManager/core/settings.py:85-97
- 严重度: 中
- 描述: `json.loads` 抛异常被 96-97 行吞掉后 `_data` 保持空 dict，且 `_dirty=False`（不会在退出时重写修复），`_legacy_migrated` 也未置位（94-95 行的 legacy 迁移被异常跳过）。结果：损坏文件永远不被修复，每次启动重复报错并回退到全部默认值；用户已有设置在本会话全部"丢失"，无任何提示。
- 触发/复现: 手动写坏 settings.json（如截断一半）→ 启动 → 所有 get() 返回默认值，文件原样保留。
- 修复建议: except 分支中回填默认数据并置 `_dirty=True`（下次保存时原子修复文件），或明确告警用户；同时把 `_migrate_legacy_settings` 移出 try 块或保证其必被执行。

## Bug 3 - settings.prepend_list/remove_from_list 读-改-写非原子（两次独立加锁）
- 位置: AssetsManager/core/settings.py:292-303
- 严重度: 低
- 描述: `prepend_list` 先 `get_list()`（加锁一次）再 `set_list()`（再加锁一次），两把锁之间列表可被其他线程修改 → 并发 prepend 会丢失更新（如搜索历史）。RLock 只保证单次操作内的原子性，不能覆盖整个 RMW。
- 触发/复现: 两线程同时 `prepend_list("search_history", "A")` 与 `prepend_list("search_history", "B")` → 其中一项可能丢失。
- 修复建议: 将读-改-写整体放入一次 `with self._lock` 内完成。

## Bug 4 - AppSettings._instance 死属性 + 直接构造会重复注册 atexit 处理器
- 位置: AssetsManager/core/settings.py:61, 68
- 严重度: 低
- 描述: `ThreadSafeSingleton` 使用 `_singleton_instance` 属性（singleton.py:42-52），`AppSettings._instance = None` 从未被读取/写入，是死代码；更实际的问题是 `__init__` 每次构造都会 `atexit.register(self._atexit_save)`——代码若直接 `AppSettings()`（如 tests/unit/test_security_preflight.py:287），会产生多个实例与多个 atexit 处理器，退出时多个实例互相覆盖磁盘文件。
- 触发/复现: 任意处 `AppSettings()` 直接构造 → 进程退出时多实例竞相 save。
- 修复建议: 删除 `_instance`；`__init__` 内检测"已存在单例"或仅在 `ThreadSafeSingleton` 创建路径注册 atexit。

## Bug 5 - 配置迁移结果不落盘：_cfg_version 升级依赖其他 dirty 事件
- 位置: AssetsManager/core/settings.py:85-97（与 core/config_migrator.py:34-42 交互）
- 严重度: 低
- 描述: `load()` 中 `migrate(data)` 会提升 `_cfg_version` 并补默认键（如 search_history），但 `_dirty` 未被置位。若 settings.json 已含 `_legacy_migrated: true`，`_migrate_legacy_settings` 不会置 dirty → 迁移结果（新版本号/新默认键）永远不会写回磁盘，直到用户下一次修改设置。
- 触发/复现: 手工在 settings.json 写入 `{"_legacy_migrated": true, "_cfg_version": 1}` → 启动 → 文件仍为 v1，search_history 默认未落盘。
- 修复建议: load() 中若 `migrate` 改变了数据（版本提升或有补键），置 `_dirty=True`。

## Bug 6 - JsonStore._save 无任何锁：并发写丢失更新（dirty 标志竞态）
- 位置: AssetsManager/core/json_store.py:71-104
- 严重度: 中
- 描述: `_save` 全程不加锁。两线程并发 `_save`：线程 A 先快照旧数据但慢完成 replace，线程 B 后快照新数据先完成 replace 并置 `_dirty=False`，随后 A 的 replace 用旧数据覆盖 → 新数据丢失且 dirty 标志已被清，后续不再保存。`_mark_dirty` 与 `_save` 之间也无互斥。
- 触发/复现: 后台线程调用 `_save` 的同时主线程修改数据并保存（SidebarFavorites/SidebarRecent 虽目前多在 GUI 线程，但 API 无线程保障）。
- 修复建议: 增加独立写锁（或把 `_load_lock` 升级为 RLock 并让 `_save` 持锁），`_save` 在锁内重新检查并快照最新数据。

## Bug 7 - JsonStore 损坏文件回退默认但不回写修复；TypeError 逃逸且 tmp 泄漏
- 位置: AssetsManager/core/json_store.py:53-69, 83-104
- 严重度: 低
- 描述: 与 Bug 1/2 同类：(a) 读损坏 JSON 时静默回退 `_default_data()` 且 `_loaded=True`，损坏文件永不修复、不重试；(b) `_save` 的 `except OSError`（103 行）不覆盖 `json.dumps` TypeError，异常逃逸且 96-101 行的 tmp 清理逻辑（仅 OSError 分支）不会执行 → tmp 残留。
- 触发/复现: 写坏 favorites.json → 启动后每次回退空列表，文件不变；数据含不可序列化对象时 save 抛 TypeError 且留 `.favorites_*.tmp`。
- 修复建议: except 加宽并统一清理；加载失败时可选回写默认数据修复文件。

## Bug 8 - LRUCache.__contains__ 对 None 值误判，且成员测试改变淘汰顺序
- 位置: AssetsManager/core/cache.py:82-83
- 严重度: 中
- 描述: `__contains__` 委托 `get()`：缓存值为 None 时 `key in cache` 返回 False，与 `len(cache)`/迭代结果不一致；同时 `in` 会执行 `move_to_end`，纯查询改变 LRU 顺序（成员测试产生副作用）。
- 触发/复现: `cache.set("k", None); "k" in cache` → False；对热点 key 做 `in` 检查会错误延长其生命周期。
- 修复建议: `__contains__` 改为锁内 `return key in self._store`，不触碰顺序。

## Bug 9 - LRUCache/TTLCache 构造参数无校验：max_size<=0 时 set 抛 KeyError
- 位置: AssetsManager/core/cache.py:53-56, 70-71, 115
- 严重度: 低
- 描述: `max_size` 未校验。`LRUCache(0).set(k,v)` 进入 `while len(self._store) >= 0` → 空 OrderedDict 上 `popitem(last=False)` 抛 KeyError（TTLCache.set 同理，139-141 行），而非给出明确的 ValueError 或退化为无缓存。
- 触发/复现: `LRUCache(0).set("a", 1)` → KeyError。
- 修复建议: `__init__` 中 `if max_size <= 0: raise ValueError(...)`。

## Bug 10 - DictCache 无任何线程同步，与 LRUCache/TTLCache 线程安全契约不一致
- 位置: AssetsManager/core/cache.py:22-47
- 严重度: 低
- 描述: 模块 docstring 宣称"All caches share the same interface"，LRUCache/TTLCache 均带锁，DictCache 的 set/get/clear 全部裸操作 dict。若被后台线程使用，并发修改 dict 会竞态/损坏。当前代码库未发现使用方，属潜在契约缺陷。
- 触发/复现: 多线程并发 set/get（当前无调用点，属防御缺口）。
- 修复建议: 加锁，或文档明确 DictCache 仅限单线程。

## Bug 11 - TTLCache.__contains__ 同样委托 get：None 值误判 + 触发过期删除副作用
- 位置: AssetsManager/core/cache.py:155-156
- 严重度: 低
- 描述: 与 Bug 8 同类：值为 None 时 `in` 误判 False；且 `in` 会触发过期条目删除（`get` 内的 del），成员测试产生写副作用。
- 修复建议: 锁内直接查 `key in self._store`（过期判断留给显式 get）。

## Bug 12 - DirectoryCache 路径键无规范化：相对/大小写路径产生重复条目
- 位置: AssetsManager/core/directory_cache.py:61-73, 93-104, 120-124
- 严重度: 低
- 描述: get/set/invalidate 直接用入参 `dir_path` 作 SQLite 键，不做 resolve/大小写归一（对比 tag_store.py:45、project_data.py:55-56 均 `Path(...).resolve()`）。Windows 上同一目录 `C:\Lib\A` 与 `c:\lib\a` 存为两条，get 用另一大小写查不到、invalidate 删不到。当前调用方 asset_service.py 先 resolve 所以未暴露，但 API 自身不防御。
- 触发/复现: 两次以不同大小写/相对路径 set 同一目录 → 表中重复行，get 命中率与一致性受损。
- 修复建议: set/get/invalidate/get_batch 内部统一 `str(Path(dir_path).resolve())` 后再作为键。

## Bug 13 - DirectoryCache.get_batch 不做 mtime 失效过滤，与 get() 语义不对称
- 位置: AssetsManager/core/directory_cache.py:75-91
- 严重度: 低
- 描述: `get()` 支持按 mtime 判失效，`get_batch` 原样返回所有命中行（含过期项），调用方需自行再比对（asset_service.py:343 有补做，但 API 不对称，其他调用方易漏）。另外 mtime 用浮点 `!=` 比较，FAT/低精度文件系统上 stat 抖动会导致缓存永不命中（持续重扫，性能问题；方向安全）。
- 触发/复现: 目录内容变化后 `get_batch` 仍返回旧 item_count，依赖调用方记得过滤。
- 修复建议: get_batch 增加可选 mtime 参数并过滤；mtime 比较改为容差或显式"仅当相同才命中"语义并文档化。

## Bug 14 - TagLibrary 默认同义词冲突："场景"/"毛发" 同属两个 canonical，解析结果取决于 dict 插入顺序
- 位置: AssetsManager/core/tag_library.py:20, 27, 38, 54, 114-120
- 严重度: 中
- 描述: DEFAULT_SYNONYMS 中 "场景" 同时出现在 Background(20) 与 Environment(27)，"毛发" 同时出现在 Hair(38) 与 Fur(54)。`_build_reverse` 按插入顺序后者覆盖前者（reverse["场景"]="Background"、reverse["毛发"]="Hair"），而 `synonyms_of("Environment")` 仍返回 "场景" → `canonical("场景")` 与 `synonyms_of` 结果互相矛盾；用户输入 "场景" 永远解析为 "Background"。
- 触发/复现: `get_library().canonical("场景")` → "Background"；`synonyms_of("Environment")` 却包含 "场景"。
- 修复建议: 加载/构建时检测别名跨 canonical 冲突并告警，仅保留一个归属；从 DEFAULT_SYNONYMS 中移除重复别名。

## Bug 15 - TagLibrary.add_synonym 静默覆盖已有别名映射，且与 _build_reverse 全量重建结果不一致
- 位置: AssetsManager/core/tag_library.py:161-172（对照 114-120）
- 严重度: 低
- 描述: `add_synonym` 直接 `self._reverse[alias.lower()] = canonical`（立即覆盖），而 `register_tag`/`remove_canonical` 走 `_build_reverse` 全量重建（按 dict 顺序，后插入者胜）。同一别名在两条路径下解析结果可能不同；被覆盖的旧 canonical 的 synonyms 列表仍残留该别名，且 add_synonym 不做别名冲突检测（alias 已映射到别的 canonical 时静默改道）。
- 触发/复现: 先 `register_tag("Scene", ["场景"])` 再 `add_synonym("Environment", "场景")` → 输入 "场景" 解析为 "Environment"，但 "Scene" 的 synonyms 仍列出 "场景"。
- 修复建议: add_synonym 改为先检查冲突再 `_build_reverse()` 统一重建，保证两条路径一致。

## Bug 16 - TagLibrary 无锁：并发 canonical/_build_reverse 下 reverse 表瞬时残缺或丢更新
- 位置: AssetsManager/core/tag_library.py:99-112, 114-120, 161-172
- 严重度: 低
- 描述: `_ensure_loaded` 检查 `_loaded` 不加锁；`_build_reverse` 先 `clear()` 再重建期间，另一线程的 `canonical()` 可能读到空/部分映射（标签不规范化，返回原始输入）；`add_synonym`/`register_tag` 并发修改 `_synonyms`/`_reverse` 会丢更新。TagStore.add_tag（tag_store.py:120）在后台线程调用时即可触发。
- 触发/复现: 扫描线程 add_tag 与 UI 线程 register_tag 并发 → 个别标签未规范化或新别名丢失。
- 修复建议: 加 RLock 覆盖 _ensure_loaded/canonical/synonyms_of 及所有写操作。

## Bug 17 - TagLibrary._save 无 fsync 且静默吞错；损坏文件缺 synonyms 键 → 静默空库
- 位置: AssetsManager/core/tag_library.py:104-105, 122-132
- 严重度: 低
- 描述: (a) `_save` 无 `f.flush()+os.fsync`（settings.save 有 fsync，json_store 也有——此处不一致），断电可能留下空/截断文件；(b) `except Exception` 吞错，调用方无法感知保存失败；(c) 文件存在但 JSON 结构缺 `synonyms` 键（或非 dict）时 `data.get("synonyms", {})` 静默得到空库，`_loaded=True` 后永不重载，所有标签退化为原样输入。
- 触发/复现: 手改 tag_library.json 为 `{"foo": 1}` → 启动后全部标签不规范化。
- 修复建议: 补 fsync；结构校验失败时回退 DEFAULT_SYNONYMS 并回写修复；_save 失败返回状态或告警。

## Bug 18 - TagStore 按库分片而 TagLibrary 全局共享：跨库标签定义互相污染
- 位置: AssetsManager/core/tag_store.py:17, 120；AssetsManager/core/tag_library.py:94, 201-202
- 严重度: 低
- 描述: TagStore 每库一个实例（按 library_root + 每库 DB），但 `get_library()` 是全局单例（SHARED_DIR/tag_library.json 跨库共享）。任一库的 add_synonym/register_tag（tag_tree_controller.py:60-72 直接调用）会立即改变所有库的标签解析。若架构意图是"每库独立标签体系"，此处分片不一致；至少属于未声明的共享契约。
- 触发/复现: 库 A 注册 "场景"→"Environment" 后，库 B 中 "场景" 的解析结果同步改变。
- 修复建议: 明确文档化为全局共享，或 TagLibrary 改为按库加载/隔离。

## Bug 19 - TagStore.get_files_by_tag 不做 canonical 化：别名查询返回空集（与 add_tag 不对称）
- 位置: AssetsManager/core/tag_store.py:137-139
- 严重度: 低
- 描述: `add_tag` 先 `get_library().canonical(tag)` 再入库，`get_files_by_tag` 却把入参原样做 SQL 精确匹配（tag_repository.py:297-303 `WHERE tag=?`）。直接传别名（如 "贴图"）→ 空集，即使该文件已打 canonical "Texture"。上层 TagService 有 canonical（tag_service.py:197），但 TagStore 自身契约不对称，Protocol（protocols.py:46）也未说明。
- 触发/复现: `store.get_files_by_tag("贴图")` 返回空，而 `store.get_files_by_tag("Texture")` 有结果。
- 修复建议: get_files_by_tag 内部先 canonical 化；或文档明确要求调用方规范化。

## Bug 20 - ProjectData.get_dir_size 的目录 mtime 缓存无法捕获子文件内容修改 → 尺寸缓存过期
- 位置: AssetsManager/core/project_data.py:154-172（mtime 判定 163-169）
- 严重度: 中
- 描述: 目录 mtime 只在目录条目增删时变化，子文件内容修改（大小变化）不改变目录 mtime。`compute_dir_size` 统计的正是各文件 st_size。因此文件被编辑后，`row[1] >= current_mtime` 恒为真 → 返回过期 cached_size，除非调用方显式 force=True 或先 invalidate。目录缓存（directory_cache）不受此影响（count/preview 只随条目增删变化）。
- 触发/复现: 缓存某目录大小 → 修改其中文件（大小变化）→ `get_dir_size(dir)` 仍返回旧值（非 force）。
- 修复建议: 缓存项记录子文件 (path, size, mtime) 指纹，或文档强制调用方在写操作后 invalidate_size_cache；至少将判定改为 `>` 并在同秒粒度下强制重扫。

## Bug 21 - ProjectData.get_urls 对合法 JSON 但非 list 的列值不防御：add_url/remove_url 抛 AttributeError
- 位置: AssetsManager/core/project_data.py:94-124（append 116 行 / remove 123 行）
- 严重度: 低
- 描述: `get_urls` 只捕 JSONDecodeError。若 urls 列是合法 JSON 但类型非 list（如 `{}`、`"abc"`，可能来自手工编辑或旧版本写入），`add_url` 中 `urls.append` 抛 AttributeError、`remove_url` 中 `urls.remove` 抛 AttributeError，且 `"abc"` 场景下 `url in "abc"` 还是子串误判。
- 触发/复现: 将 file_meta.urls 改为 `"{}"` → `add_url(path, "https://x")` 崩溃。
- 修复建议: get_urls 校验 `isinstance(result, list)`，否则返回 []。

## Bug 22 - ProjectData.compute_dir_size 递归无深度保护：深层目录树抛 RecursionError
- 位置: AssetsManager/core/project_data.py:138-152（递归 147 行）
- 严重度: 低
- 描述: 递归遍历只捕 OSError；目录深度超过 Python 递归限制（约 1000 层）时抛 RecursionError 且不捕获，`get_dir_size` 调用链崩溃；另外权限错误被 `except OSError: pass` 静默计为 0 字节。
- 触发/复现: 构造 1500 层深目录 → `get_dir_size(dir, force=True)` → RecursionError。
- 修复建议: 改为显式栈迭代遍历。

## Bug 23 - ProjectData._key 用 Path.resolve() 但 Windows 大小写不归一：同文件不同大小写产生重复 file_meta 行
- 位置: AssetsManager/core/project_data.py:55-56
- 严重度: 低
- 描述: resolve() 保留输入的大小写；Windows 文件系统大小写不敏感但字符串键比较大小写敏感（SQLite 默认），`C:\Foo` 与 `c:\foo` 会生成两条 file_meta 行，get_notes/get_urls 用另一种大小写查不到。上游扫描一般给规范大小写，属防御缺口（与 Bug 12 同族）。
- 触发/复现: `set_notes("C:\\Foo\\a.txt", "x")` 后 `get_notes("c:\\foo\\a.txt")` 返回 ""。
- 修复建议: _key 统一 `os.path.normcase(str(Path(path).resolve()))`（Windows 下转小写）。

## Bug 24 - schema_defs 的 CHECK 约束校验基于规范化 SQL 子串匹配：对等价重建的表产生误报/漏报
- 位置: AssetsManager/core/schema_defs.py:1114-1120
- 严重度: 低
- 描述: 校验把契约 CHECK 文本与 `sqlite_master.sql` 归一化（空白折叠 + 大写）后做子串包含。当前 DDL 均自生成所以全绿，但未来迁移若以等价写法重建（如 `revision>=0` 无空格、不同引号、别名、括号位置），归一化后子串不匹配 → 误报 InvalidSchemaError；反之语义不同但文本相似也可能漏报。属于脆弱的兼容校验（向后兼容契约的一部分）。
- 触发/复现: 手工将表 DDL 的 CHECK 改为 `revision>=0` → validate_schema_object 报 missing check。
- 修复建议: 用 AST/分词级别解析 CHECK 语义，或维护逐迁移的精确快照而非子串匹配。

## Bug 25 - singleton 文档宣称可用作装饰器，但 ThreadSafeSingleton 未实现 __call__
- 位置: AssetsManager/core/singleton.py:15-17（docstring 示例 `@ThreadSafeSingleton`）
- 严重度: 低
- 描述: docstring 声称 "Or as a decorator: @ThreadSafeSingleton class MyService"，但类未实现 `__call__`，实际使用 `@ThreadSafeSingleton` 会直接 TypeError（把类当参数构造）。当前代码库无使用点，属文档契约错误。
- 触发/复现: 照文档写 `@ThreadSafeSingleton class X: pass` → TypeError。
- 修复建议: 删除装饰器示例，或实现 `__call__` 支持装饰用法。

## Bug 26 - singleton.get 快路径无锁读取，与 reset() 并发时可能返回已重置的旧实例
- 位置: AssetsManager/core/singleton.py:41-53, 55-64
- 严重度: 低
- 描述: fast path（42-44 行）不加锁读取 `_singleton_instance`；`reset()` 置 None 与并发 `get()` 之间无同步，一个线程可能在 reset 完成前拿到旧实例引用（测试场景；生产无 reset 调用）。`_locks` 字典按类无限增长（类数量有限，影响可忽略）。
- 触发/复现: 线程 A 循环 instance()，线程 B 调用 reset() → A 偶发返回旧实例。
- 修复建议: reset 与 get 共享同一把类锁并双检；文档注明 reset 仅限测试且需全局同步。

## Bug 27 - AppSettings 单例加载时序依赖 import 副作用：未显式 load() 前读取到默认值
- 位置: AssetsManager/core/settings.py:70-79（instance() 不触发 load）；相关证据 app.py:45、core/themes.py:150-171
- 严重度: 低
- 描述: `AppSettings.instance()` 只创建实例，不保证已 load()。生产上数据加载实际靠 `themes.py` 模块级 `_load_saved()`（import 时执行 settings.load()）这一隐式副作用；app.py:45 在 bootstrap 前读取 `performance_telemetry_enabled`，其正确性依赖 themes 已先被 import（app.py:8 恰好 import themes 才安全）。任何未来调整 import 顺序或新增早读模块，都可能静默读到全默认值。
- 触发/复现: 在未 import themes 的模块中 `AppSettings.instance().get("theme")` → None（默认）。
- 修复建议: instance() 首次创建时自动 load()（幂等），或在 bootstrap 显式调用 settings.load() 并移除对 import 副作用的依赖。

# 复核备注（非 bug）
- protocols.py：TagStoreProtocol 与 TagStore 实现签名一致（runtime_checkable 可用）；协议未声明 get_all_tagged_files/clear_cache 属子集设计，非缺陷。无问题。
- schema_defs 契约与 DDL 一致性：reconciliation_tasks 的 lease_token 由迁移 v17 补齐，db_migrations.py:161-182 有 include_lease_token=False 的旧版契约分支，非缺陷。
- db_write_lock 为 RLock（database.py:198,287），project_data.add_url → _save_urls 嵌套获取不会死锁。
- DirectoryCache 读路径不持写锁在 WAL 模式下安全（database.py:155 PRAGMA journal_mode=WAL）。
- TagStore 嵌套操作作用域（add_tag 内调 get_tags）经 context.py:243-261 确认可重入。

