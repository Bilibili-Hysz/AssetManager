# 01 · core 基础设施层（AssetsManager/core/）

> 状态：**DATED ANALYSIS（2026-09-04 实测快照）** · deep-analysis 系列之一，索引见 [README.md](README.md)。
> 方法：并行只读勘察代理全量通读 core/ 全部 44 个 .py（15,005 行，wc -l 实测，含 plugins/ 子包 6 文件），常量（迁移版本/图标数/契约表数）经脚本实测。

---

## 1. 模块清单（按功能分组，行数实测）

### A. 数据库 / 迁移 / Schema 契约

| 模块 | 行数 | 职责 |
|---|---|---|
| `database.py` | 1610 | SQLite 持久层核心：连接管理、读写门、身份标记、路径迁移 |
| `db_migrations.py` | 1693 | 迁移执行器：46 个 Migration、历史校验、savepoint 原子迁移 |
| `schema_defs.py` | 1975 | 静态 SQL DDL + 44 表 Schema 契约 + 运行时校验器 |
| `library_lock.py` | 273 | 跨进程库锁（QLockFile + PID 存活探测 + POSIX 陈旧锁恢复） |
| `directory_cache.py` | 241 | 目录元数据缓存（SQLite 表，概率修剪） |
| `project_data.py` | 296 | 文件备注/URL/目录尺寸缓存（TTL+mtime 双校验） |
| `tag_store.py` | 228 | TagStore 标签读写门面（委托 TagRepository，含 resolve 缓存） |
| `thumbnail_key.py` | 138 | 版本化缩略图缓存键（v2/v3 身份感知 sha256[:16]） |

### B. 路径 / 标识 / 契约 / 协议

| 模块 | 行数 | 职责 |
|---|---|---|
| `path_resolver.py` | 316 | 全部路径解析：RuntimeData 布局、哈希槽位、SQLite LIKE 转义 |
| `file_snapshot.py` | 194 | 根目录受限的"最终一致文件快照"打开器（防符号链接逃逸） |
| `event_contracts.py` | 33 | `DomainEventBase`/`EventBusPort` 协议（core↔domain 解耦缝） |
| `session_contract.py` | 31 | LibrarySession 身份令牌（区分真 session 与结构化测试 fake） |
| `protocols.py` | 52 | `TagStoreProtocol`（runtime_checkable） |

### C. 设置 / 持久化 JSON

| 模块 | 行数 | 职责 |
|---|---|---|
| `settings.py` | 581 | AppSettings 单例：键校验器、future-version 只读封锁、原子写 |
| `json_store.py` | 160 | JsonStore 基类：模板方法（`_default_data/_on_loaded/_on_before_save`） |
| `config_migrator.py` | 57 | settings.json 的 `_cfg_version` 迁移（CURRENT_VERSION=2） |
| `library_manager.py` | 86 | 库记录 CRUD（存于 AppSettings 的 `library_records`） |
| `tag_library.py` | 281 | Pixiv 式规范标签库（多语言别名→canonical） |
| `constants.py` | 92 | 全局常量：版本、扩展名、阈值、AI 标注端点 |

### D. 主题 / 图标 / UI 缩放 / 颜色

| 模块 | 行数 | 职责 |
|---|---|---|
| `themes.py` | 969 | 主题令牌体系 + ~320 行 QSS 生成（按钮变体、DPR/scale 感知缓存） |
| `theme_loader.py` | 356 | 主题 JSON 扫描/校验/热重载（D_/L_/U_ 前缀、QFileSystemWatcher） |
| `icons.py` | 260 | SVG 线性图标注册表：**48 基础图标 + 10 别名**（实测），DPR 感知 LRU 渲染 |
| `color_utils.py` | 172 | 颜色工具：alpha/lighter/darker（HSV 规范 hover 算法）、WCAG 对比度 |
| `ui_scale.py` | 29 | 全局缩放因子（0.5–3.0），`scaled_px/scaled_pt` |
| `bg_effects.py` | 347 | 背景特效：模糊（镜像填充）、马赛克、Kuwahara（numpy/纯 Python 双路径） |
| `format_utils.py` | 174 | 尺寸格式化 + `LiveCategoryMap`（原子快照发布的 dict 子类） |

### E. 并发 / 调度 / 事件

| 模块 | 行数 | 职责 |
|---|---|---|
| `workers.py` | 204 | BoundedPool：私有 QThreadPool + 生成代数 + 协作取消 + 守护回收 |
| `timers.py` | 54 | TimerHandle：可拥有、可取消的一次性 QTimer 包装 |
| `signal_bus.py` | 32 | Qt 展示层信号总线（7 个低频信号） |
| `singleton.py` | 105 | ThreadSafeSingleton：双检锁单例工厂 |
| `tool_scheduler.py` | 175 | 外部工具启动器（tools.json + 占位符替换 + 超时绞杀） |
| `performance.py` | 150 | PerformanceRecorder：有界 deque 诊断事件记录器 |
| `crash_handler.py` | 303 | 全局异常钩子 → crash.log（脱敏正则 + 重复崩溃检测） |
| `cache.py` | 312 | 四种缓存：DictCache/LRUCache/ByteLRUCache/TTLCache |

### F. 插件子系统（core/plugins/，6 文件共 3,025 行）

| 模块 | 行数 | 职责 |
|---|---|---|
| `host_context.py` | 1657 | 插件宿主上下文：注册表、ContextVar 权限门禁、生命周期清理 |
| `manager.py` | 765 | PluginManagerService：发现/加载/卸载、过渡串行化 |
| `descriptor.py` | 233 | manifest 解析、PluginRecord/Diagnostic、10 个权限令牌 |
| `preferences.py` | 216 | 每插件偏好袋（JSON + 跨进程 AdvisoryLock + 路径锁 LRU） |
| `loader.py` | 115 | 动态模块加载（importlib spec + 路径逃逸防护 + 3 类适配器） |

> **口径修正**：README 称 core 为 "34 模块"、icons "56 图标"——实测 **44 文件 / 48+10=58 图标命名**。本文以实测为准（check_doc_stats.py 的 stats 行另有自己的口径）。

---

## 2. 核心机制详解

### 2.1 database.py —— 连接级读写门与身份标记（1610 行，"半个 DB 框架"）

**① 慢查询遥测层**（`core/database.py:62-277`）：`SLOW_QUERY_THRESHOLD_MS=100.0`（环境变量可覆盖，坏值回落）；`SlowQueryConnection` 代理只拦截 `execute/executemany`，其余 `__getattr__` 透传；调用方归属经栈帧扫描定位 `repositories/`、`application/` 目录标记。**关键取舍**（:222-227 注释）：该代理故意不继承 `sqlite3.Connection`——`locked_read` 的 isinstance 检查会把它当"无锁桩连接"跳过锁获取，只在调用方已串行化访问时才可安全包裹。

**② `_WriteGate` 读者/写者门**（:461-536）：`threading.Condition` + 读者计数（threading.local 支持嵌套）+ 写者可重入（按 thread_id）+ **写者优先**（读者必须等 `_waiting_writers == 0`，:493，防写者饥饿）。

**③ 连接级写状态**（:449-458）：每连接一把 RLock + closed 标记 + `library_root/library_root_key`（**连接的身份归属元数据**，防"拿 A 库连接操作 B 库"，:959-1037 的 require/validate 两档 API）+ owner_thread/depth（供 close 时检测自持锁）。

**④ `db_write_lock(conn)`**（:1203-1263）：写路径统一入口，**双向死锁 fail-fast**——持有遗留全局写锁的线程禁止再取连接级锁（:1219-1224），反之亦然（:1257-1261），错误信息明说 "this would deadlock"；closed 连接立即抛错（fail-closed，:1230-1234）。

**⑤ `locked_read` 装饰器**（:1266-1302）：仓库读方法经 `self._conn` 的同一把连接锁串行化——LAN 场景是 aiohttp 事件循环线程、`to_thread` worker、gallery 构建线程**共享一条 `check_same_thread=False` 连接**（docstring :1267-1276 详述不加锁的后果）。

**⑥ RuntimeData 身份标记（identity marker）**（:562-871）——本模块最重的机制：
- `_identity_claim_lock`（:562-628）：对 `<slot>.identity.pending.lock` 的跨平台文件锁（msvcrt/fcntl），**故意在释放后保留锁文件**——用 OS 锁本身区分"活跃申请者"与"崩溃申请者"，不靠文件年龄/PID 复用猜测。
- `_ensure_library_data_identity`（:699-871）：核心原语是 **`os.link` 作为 no-clobber 发布**（:739-775）——只在目标不存在时成功，输者读取赢者内容而不是覆盖；内容碰撞抛 `RuntimeData identity collision`。
- **持久化诚实**（:282-347）：Windows 走 ctypes `CreateFileW(FILE_FLAG_BACKUP_SEMANTICS)` + `FlushFileBuffers`，POSIX 走 `O_DIRECTORY` fd fsync；失败即抛错（fail-closed），且正式标记发布成功后**绝不删除**（:766-774 注释：赢者标记不可被事后移除）。
- 发布一律走 `publish_from_unique_temp`（:777-812），正式标记永不别名可被重写的固定 pending 文件。

**⑦ `open_library`**（:873-957）顺序：身份标记 → 遗留目录迁移（保留名 shared/_orphaned 拒迁 fail-closed；`_legacy_migration_looks_complete` :631-647 把"他进程已完成改名"识别为幂等成功）→ mkdir → 建连接（`check_same_thread=False`、`timeout=30s`、`PRAGMA busy_timeout=30000`）→ **先注册后初始化**（:928-934，失败初始化保持同一可重试 close 契约）→ preflight + executescript + migrate → 异常时 closed=True 再关连接，close 失败 add_note 附加（:940-951）。

**⑧ close 三段式**（:1081-1132）：先发布 closed 拒新写者 → 检查自持锁并 raise → 全局独占下逐个 close；`_close_managed_connection`（:1063-1079）**先 conn.close() 成功才摘注册表**——失败保留重试所有权。

**⑨ 孤儿清理**（:1133-1201）：7 天 mtime + `.identity` 标记保护 + recent_libraries 持久注册表扩展保护（离线盘不误扫）+ 设置读取失败回退空集（"设置失败绝不能让孤儿清理变成破坏性清扫"）；清理是**隔离移动到 `_orphaned/`**（带时间戳去重），不是删除。

**⑩ `migrate_path_metadata`**（:1558-1601 + impl :1336-1556）：库目录移动时逐 6 表重映射，SAVEPOINT 包裹；"插入新路径行 → 只删 remap 真正改写的旧行"的**保守删除**策略（:1353-1357 论证大小写不匹配行绝不能删）。

**⑪ BUSY 工具**（:70-85）：`SQLITE_BUSY_TIMEOUT_MS=30_000`、3 次重试、指数退避封顶 0.25s；被 reconciliation_queue_store、repositories/_common、thumbnail_repository 消费。

### 2.2 db_migrations.py —— 迁移执行器

- **`CURRENT_SCHEMA_VERSION = 46`**（`core/db_migrations.py:54`，实测）；`MIGRATIONS` 元组 46 条（:1491-1550），v1 基线占位（open_library 已执行 _SCHEMA）。
- **基线契约**（:55-99）：4 张基线表（file_tags/file_meta/thumbnail_cache/library_stats）的形状锁定；`IncompleteSchemaError` 携带结构化 missing 字段（:120-150）。
- **历史不可变**（:1486-1490）：版本连续 + **名字逐条匹配**——改名会永久砖化已记录旧名的数据库；`frozen_history_signature()`（:1553-1562）供测试冻结。
- **版本感知契约**（:197-359）：对 8 组表按版本边界裁剪，使 v35 步骤能用 v35 形状校验而不被 v37 新列误伤。
- **savepoint 原子迁移**（`_migrate_once` :1577-1661）：SAVEPOINT migration_runner → 逐迁移 apply+record → 按版本逐段累积契约校验 → RELEASE。
- **跨进程迁移竞态**（`migrate` :1664-1688）：`_migration_guard` 串行本进程；IntegrityError/locked 时重读历史，他进程已完成则返回，否则**单次**重跑。
- 代表性迁移：v19 结账代数（重建表搬数据）、v30 文件系统投递 payload（RENAME→CREATE→INSERT→DROP）、v39/v40 FTS5（**trigram 分词器重建修 CJK 子串匹配**，共用一个实现）、v41 衍生物生命周期（CHECK 只列现存两态避免枚举扩张引发表重建）。

### 2.3 schema_defs.py —— 契约层

- 三个 TypedDict 契约类型 + ~40 个 DDL 常量（含不可变历史快照 `USERS_SCHEMA_V6`）。
- **`SCHEMA_OBJECT_CONTRACT`（:867-1740）**：**44 张表**的形状清单（实测键数）——列类型/not_null 契约、索引列序、CHECK 片段、外键五元组。
- **`validate_schema_object`（:1853-1966）**：纯读校验器，亮点是 `_sql_contains_tokens`（:1823-1850）——**SQL 词法分 token 做 CHECK 约束匹配**，等价重写（空白不同）不误报。

### 2.4 library_lock.py —— LibraryLock

- 基于 QLockFile，`setStaleLockTime(0)` **禁用 Qt 时间型陈旧恢复**（:58-64），恢复只信"PID 可证已死"。
- `_pid_is_alive`（:25-55）：Windows `OpenProcess(0x1000)` 探测；**无法判定时返回 True（fail-closed，把锁当活的）**。
- **进程内引用计数注册表**（:196-225）：同锁文件多种拼写经 normcase+abspath 归一共享一条 in-process lease——锁代表"应用所有权"而非某个 Service 对象（:184-189 docstring）。
- **POSIX 陈旧恢复**（:67-180）：以**父目录 fd 的 flock 为互斥量**序列化恢复窗口（防移除标记与新申请者竞争 unlinked inode），恢复能力不可用时 fail-closed 为 LibraryAlreadyOpenError。
- `release()`（:239-263）："无法证明已释放就不谎报成功"；unlock 后仍 locked 也返回 False。

### 2.5 path_resolver.py

- `RootIdentity` 冻结 dataclass：`display_path` + `map_key`（normcase 规范键），一次捕获终身使用。
- **可移植数据根**（:117-134）：frozen 构建数据在 exe 旁、dev 在仓库根；docstring 明说"设计上不静默搬数据到隐藏 per-user 路径"。
- **哈希槽位 + 碰撞探测**（:158-188）：`<basename>_<sha256(map_key)[:10]>`；marker 属他人且目录已存在时探测 `-2/-3` 后缀而非失败。
- **SQL LIKE 安全**（:65-91）：`escape_sql_like` 转义 `\ % _`；`sql_like_descendant_pattern` 按**最后出现的分隔符**判定（兼容 Windows `\` 与 fixtures `/`）。
- frozen/dev 双层目录（builtin themes/plugins 区分可写用户层与只读 `_MEIPASS` 层）。

### 2.6 settings / json_store / config_migrator

- **AppSettings**（581 行）：ThreadSafeSingleton + **首次访问自动加载**（防"set+save 先于 load 清空用户配置"，:153-163）；**atexit 单次注册**（只有单例本体注册，防副本退出时覆盖快照，:127-145）；**校验器注册表**（每键一个 lambda，MCP token 只收 str——"truthy 非 str 永远不能武装端点"）；**future-version 只读封锁**（`FutureConfigVersionError` 时清空内存、一切 set/save 拒写）；**损坏隔离**（`os.replace` 到 `.corrupt` 回落默认）；**原子写**（mkstemp+fsync+replace）；**fail-closed 读**贯穿全部 get_*（缺失/畸形回落安全默认且不写回）；**事务式提交**（暂存旧值→写入→save，失败回滚）。
- **JsonStore**（160 行）：模板方法基类；懒加载双检锁；损坏隔离 `.corrupt[-时间戳]`；写失败记日志吞掉（"调用方绝不在写中途崩溃"）。
- **config_migrator**：CURRENT_VERSION=2，链式迁移，未来版本抛 FutureConfigVersionError。

### 2.7 主题 / 图标 / UI 缩放

- **themes.py 令牌三层**：13 个 v1 必需令牌 → ~30 个内置扩展令牌回退表（`_BUILTIN_EXTENDED_FALLBACKS`，每个是主题感知 lambda，如 hover_overlay 依 dark 翻转黑/白）→ **插件令牌注入**（`set_plugin_token_fallbacks` :125-151，卸载一个 owner 自动恢复内置回退；显式主题 token 永不被回退覆盖）。
- **三层缓存失效联动**：`set_theme` 清 QSS 缓存 + 清图标缓存（延迟导入防环）+ 发总线信号；QSS 缓存键 `(theme, scale)` 二元组——**缩放变化也触发重生成**。
- **QSS 生成**（:627-946，~280 行 f-string）：全部尺寸过 `scaled_px/pt`；按钮四变体走动态属性选择器；hover/pressed 统一走 `color_utils.lighter/darker`（"规范 hover 算法，不得另立配方"）；原生控件指示器显式主题化（防暗色下回落系统浅色）。
- **theme_loader**：双层扫描（内置 + 用户覆盖）；`save_custom_theme` 只许覆写 `U_` 前缀 + tmp+replace 原子替换（"watcher 永不观察半写 JSON"）；删除优先 send2trash。
- **icons.py**：内嵌 24x24 viewBox SVG path（stroke=1.8 线性风格）→ QSvgRenderer → QIcon；**DPR 四级探测**（显式参数 > 焦点窗口 > 活动 widget > 主屏）；DPR≠1 时**同时附加 1.0 DPR 基础位图**（防非高 DPI 上下文取模糊图）；缓存键四元组 `(icon, tint, size, dpr)`，LRU 4096。
- **ui_scale**：钳 0.5–3.0；`scaled_pt` 下限 6（防缩成不可读）。
- 实测主题文件：assets/Themes 下 24 个 JSON（13 Dark + 11 Light）。

### 2.8 并发 / 调度

- **BoundedPool（workers.py）**：`CancellationToken` + `CancellableRunnable`（携带 generation 与 token）；**私有池而非全局池**（owner 只 drain 自己的工作且保证超时）；`close(timeout_ms)` 超时后移交**守护线程回收器**（5s×12 次有界轮询，楔死也不钉住回收线程，放弃时留在 `_retained_pools` 观察注册表）。
- **TimerHandle**：owned one-shot QTimer；触发即清 callback（"fired handle 不再钉住 owner"）；替代匿名 singleShot 在 owner 销毁后仍触发的隐患（D3）。
- **signal_bus**：7 个低频信号，docstring 明确**高频事件走面板直连**。
- **ThreadSafeSingleton**：每类一把 threading.Lock，get/reset 均在类锁内。
- **tool_scheduler**：tools.json 缺失回默认且**不写盘**（"查询不得触碰文件系统，共享目录可能只读"）；`\x00` 显式拒绝；Windows `.cmd/.bat` 自动包 `cmd /c`；timeout 走 terminate→5s 宽限→kill 三级。

### 2.9 plugins/ 宿主、门禁与生命周期

**身份模型（host_context.py 核心）**：三个 ContextVar——注册身份、执行身份、**独立的宿主标记**（:268-270）。代码反复强调的攻击面：**Python 线程不继承 ContextVar**，插件可把调用挪进自己 spawn 的线程洗白成"空身份=宿主"；因此：
- `_check_permission_warn`（:1212-1248）：空 subject 一律拒绝；
- `grant_permissions`（:318-380）：**双门禁**——任何活跃 subject 拒绝（含自我授权，"自我授权正是要封的提权"），无 subject 必须显式持有 host 标记；
- `unregister_plugin`（:1502-1546）：同双门禁，防插件互相剥离贡献。

**诚实的边界声明**：代码至少 4 处明说这是 **in-process honesty boundary 而非沙箱**——同解释器的插件可直通私有属性；门禁目的是"让声明的权限令牌有意义、抓住无意错误"。

**权限令牌三档**（descriptor.py:22-56）：`host.services` 强制（服务束+session 只能经 host API 到达）；`filesystem.read` 等咨询性；`filesystem.write/network.request/clipboard.*` 纯声明（host 无对应 API 可拦）。

**其余机制**：注册面按 9 类贡献基类分派（:562-625）；`_resolve_contribution_owner`（:858-892）拒绝"把贡献记到别人名下"；执行门禁——subject 只能执行/撤销自己的命令，undo 记录携带执行时 owner；偏好袋 owner 从 ContextVar 解析（"猜 id 也拿不到别人的 API key 袋"）；`_PluginServicesView`（:195-222）只暴露 3 个元数据服务（"连 hasattr 都看不见"认证材料）；`_HookDispatchDrain`（:73-104）——**在释放所有宿主锁之后**才 wait_idle（有界 1s），防在事件钩子锁下等待与回调死锁。

**manager.py**：过渡串行化（RLock + 每插件 Condition；回调线程内再发起生命周期操作直接拒绝——防回调内自杀死锁）；发现序号防旧结果覆盖新结果；**显式 disable 意图压过 manifest 默认**；core→application 的缝——`set_category_registry_provider` 由装配根注入，core 不 import application。

**preferences.py**：双层锁（进程内按**解析路径** LRU 化 RLock 容量 1024 + 跨进程 AdvisoryLock sidecar）；**写前合并**（每次 set 在锁内重读盘上 JSON 再合并，把 last-writer-wins 收窄到整个窗口被争用的罕见情形）。

### 2.10 其余支撑模块

- **crash_handler**：4 组脱敏正则（Bearer/key=value/自由形状 token/绝对路径）；重入护栏；重复崩溃窗口（10 分钟 5 次）；`crash.pending` 标记让**下一次会话**呈现"上次崩溃已恢复"；GitHub issue URL 二次脱敏 + 逐步截断至 ≤6000 字符。
- **file_snapshot**：防目录逃逸三连——resolve 后 is_relative_to + 控制字符与 NT 流分隔符拒绝 + **逐祖先组件拒绝 symlink/junction/REPARSE_POINT**（lstat 不可检查也 fail-closed）；POSIX 走 `O_NOFOLLOW` 逐组件 `open(dir_fd=)`；读后复查 fstat 身份。
- **project_data**：目录尺寸缓存 **mtime 精确相等（非 >=）+ 30s TTL 双校验**（"目录 mtime 只记子项增删，就地改内容不感知，TTL 兜底"）；**取消的 walk 部分总量绝不写缓存**（"把欠计数毒进缓存"）；深度预算 64 防递归爆栈。
- **LiveCategoryMap**（format_utils）：读走不可变快照、写复制后原子发布——"消费者绝不遍历正在重建的代"。
- **tag_library**：~70 个 canonical 标签 + 中/日别名内置表；"一个别名→一个 canonical"不变量去重；结构损坏回退默认标签集而非空库。

---

## 3. 设计模式总览

| 模式 | 落点 | 说明 |
|---|---|---|
| **Fail-closed** | library_lock.py:30-31/177-180/245-249；database.py:1230-1234；settings 全部 get_* | 探测不出→当作有锁/有身份/已确认 |
| **CAS / no-clobber 发布** | database.py:739-775（os.link） | 硬链接原子"仅当不存在才发布"，输者读赢者 |
| **原子写（tmp+fsync+replace）** | settings/json_store/tool_scheduler/tag_library/preferences/theme_loader | 全库 JSON 落盘统一配方 |
| **持久化诚实（目录 fsync）** | database.py:282-347 | Windows ctypes FlushFileBuffers；失败抛错且标记永不回收 |
| **连接身份标记** | database.py:449-458, 959-1037 | 防跨库连接误用 |
| **读者-写者门 + 双向死锁 fail-fast** | database.py:461-536, 1219-1261 | 写者优先防饥饿；锁序错误在调用点 raise |
| **模板方法** | json_store.py:39-51 | 三钩子 |
| **协议缝（依赖倒置）** | event_contracts/tag_store/manager.py:44-79 | core 不 import application/domain |
| **ContextVar 身份 + 宿主显式标记** | host_context.py:246-270 | 封堵"线程不继承 ContextVar"洗白路径 |
| **原子快照发布** | format_utils.py:44-170 | LiveCategoryMap |
| **有界一切** | icons(4096)/performance(200)/preferences(1024)/command_executions 表 4096 行 FIFO/workers 有界轮询 | 所有缓存/记录器/注册表都有上限 |
| **幂等迁移** | db_migrations 各 `_add_*` | IF NOT EXISTS/PRAGMA 探测 |
| **隔离而非删除** | .corrupt / _orphaned / 回收站优先 | 损坏数据留证据 |
| **生成代数 + 协作取消** | workers/project_data | 取消结果不落缓存 |

**注释明示的取舍**：慢查询代理不做 Connection 子类（兼容 locked_read 分派，代价是不受读写门保护）；写者优先牺牲读者并发；插件权限是诚实边界非沙箱；主题 prop 缺键返回 0 并 warning（历史上静默 0 藏住 token typo）；Kuwahara 纯 Python 回退降分辨率（无 numpy 保可用）；便携数据根假设安装目录可写（Program Files 显式失败）。

---

## 4. 弱点 / 技术债清单

1. **icons.py LRU 缓存无锁**（:99-255）：`_CACHE` OrderedDict 的结构操作未加锁；后台线程取图标可竞态（同项目 cache.py 的 LRUCache 是加锁的——风格不一致）。
2. **preferences.py:200 `if acquired or True:`**——恒真条件，留下死代码 `acquired`，实质放弃锁失败时的保守策略。
3. **preferences.py 原子写不 fsync**：与 settings/json_store 的 tmp+fsync+replace 相比缺 os.fsync——同类不一致。
4. **db_migrations 的 required_objects 手工阶梯**（:1597-1645）：15 个 `if version >= N` 硬编码，可由 MIGRATIONS 元数据派生。
5. **database.py 巨型模块**（1610 行、至少 6 职责）；`migrate_path_metadata_impl` 120 行内嵌 6 表复制粘贴式重映射——有模板化空间。
6. **database.py 全局可变状态**：三本注册表并存，"按 id 的锁"与"按 map_key 的锁"所有权关系靠注释维系，易拿错。
7. **settings.py set() 两段锁**（:320-329）：竞态被收敛但结构不易读。
8. **themes.py 模块级副作用**：import 即 `_load_all_themes()` + 连 watcher 信号——QApplication 之前 import 可能告警；测试隔离变难。
9. **schema_defs.py 1975 行纯数据**：DDL 常量与契约字典列清单各写一遍，无生成器保证同步——"用运行时校验弥补静态重复"的可辩护债务。
10. **library_lock PID 复用窗口**：崩溃进程 PID 被新进程占用时死锁被当活锁，锁永久无法自动恢复——固有方案限制，注释未文档化。
11. **crash_handler 脱敏正则**对含空格值可能截断 secret 前半段；traceback 帧行的异常参数 repr 可能带 secret——已知边界。
12. **directory_cache 概率修剪在读路径**：1% 概率该次 get 承担一次 DELETE+commit——读路径不可预测尾延迟。
13. **废弃 API 仍在导出**：tag_store.get_store / project_data.get_project_data 带 DeprecationWarning；清理周期未定。
14. **文档口径漂移**：README"34 模块/56 图标"vs 实测 44 文件/58 命名。

---

**关联阅读**：仓库层如何消费这套基础设施 → [02-domain-repositories.md](02-domain-repositories.md)；插件宿主与桌面挂载（tool_windows/menu_contributions）→ [07-desktop-ui.md](07-desktop-ui.md) 与 [08-entry-and-window-assembly.md](08-entry-and-window-assembly.md)。
