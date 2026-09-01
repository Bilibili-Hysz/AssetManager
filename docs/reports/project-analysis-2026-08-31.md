# AssetManager 项目系统化分析报告

> **分析性质**：专家团队联合评审（架构 / 功能 / 代码质量 / 安全 四个视角）
> **分析日期**：2026-08-31
> **分析范围**：`AssetsManager/` 主包（Python · PySide6 + 内嵌 aiohttp LAN 服务）、`webui/`（React SPA）、`Plugins/`、`tests/`、`docs/`、构建与 CI 配置
> **分析方法**：源码实地走查 + 子代理并行深度审计 + 关键结论交叉验证（所有结论均带 `文件:行号` 证据锚点）
> **配套证据**：本仓库已有 `docs/overview-2026-08-27.md`（LIVING 地图）、`docs/architecture.md`、`docs/lan-security.md`、`docs/migrations.md`、`docs/full-review/`、`docs/deep-weakness-audit-2026-08-22/`；本报告在正交视角上做独立评审，并校正其中已过期/夸大的结论。
> **持续执行**：后续实现、门禁数字和回滚边界统一写入 [`docs/plans/architecture-reliability-roadmap-2026-08-31.md`](../plans/architecture-reliability-roadmap-2026-08-31.md)；本报告保留架构/功能基线，不把路线图中的计划项视为已交付能力。

---

## 0. 执行摘要（TL;DR）

AssetManager 是一款**工程成熟度中上、安全基本功扎实、但存在若干结构性短板**的桌面资产管理器。它在"局域网可分享 + 可公网隧道"这一高危暴露面下，把路径穿越、令牌安全、密码哈希、失败关闭（fail-closed）、隧道供应链校验都做得到位，这是本项目最大的亮点。事务一致性（SAVEPOINT 嵌套 + CAS 重放）与并发设计（BoundedPool + Qt/asyncio 双线程干净桥接）也属上乘。

但评审也发现一类**必须由项目团队立即决策**的硬伤：

- **CRITICAL**：插件系统在宿主同进程无沙箱执行（可联网/公网暴露 = 以桌面用户身份 RCE）。
- **HIGH**：密码模式登录令牌的 HMAC 密钥直接复用存储的 `password_hash`，任何能读到库 DB 的人即可伪造令牌。
- **HIGH**：应用层全局写串行化 + 连接 `id()` 复用做锁归属，在高并发写入与多库场景下有停摆/锁串扰风险。
- **MEDIUM/文档信用**：README 多处与代码脱节——宣称的"商城 54 条路由"后端不存在、upload 能力已废弃却仍展示、仓库数量自相矛盾。

> **总体健康度判断**：**可用、可交付，但"暴露在公网"前必须封堵插件沙箱与令牌签名两处**；长期可维护性受单体模块膨胀与类型检查盲点拖累，建议纳入下一迭代规划。

---

## 1. 项目总体概述与背景

### 1.1 产品定位
AssetManager 是基于 **PySide6 (Qt)** 的桌面文件资产管理器，内置 **aiohttp** 局域网分享服务器，并配套 **React 18 + Vite + TS** 的 Web 端 SPA。用户可在桌面端管理多资产库（元数据、标签、缩略图、主题、撤销/重做），也可经浏览器在局域网内（甚至经 Cloudflare 隧道在公网）浏览/下载资产（`README.md:5-7`、`README.md:33-39`）。

### 1.2 技术栈（核实后）
| 层 | 技术 | 备注 |
|---|---|---|
| 核心 | Python 3.12/3.13/3.14、PySide6 `>=6.6,<7`、aiohttp（可选）、SQLite3（WAL，迁移 v1–v42）、Pillow `>=10,<13`、segno、send2trash、requests | `requirements.txt:10-14` |
| 桌面 | QDockWidget、QAbstractListModel、QThreadPool（自封装 BoundedPool）、signal_bus（7 信号）/event_bus（15 领域事件）、icons.py（56 图标，DPR 感知） | `README.md:48` |
| LAN | aiohttp（22 路由模块 / 71 路由 + WebSocket）、middleware 顺序 security→metrics→auth、PathGuard、HMAC 令牌、WebSocketManager、Cloudflare Tunnel | `README.md:49` |
| 数据 | DatabaseManager（连接级读写门 + 身份标记）、12–17 个 SQL 仓库、db_migrations（v1–v42）、schema_defs 契约、LibraryLock、json_store 原子持久化 | `README.md:50` |

### 1.3 规模（实测/自报）
- 主包 `AssetsManager/`：约 **270 个 `.py` / 9.2 万行**（README 自报，2026-08-27）。
- 测试：约 **310 个 test 文件**（unit / integration / lan / desktop / core / plugins / e2e / performance）；`README.md:240` 自报基线 2952→3722/3755 用例，**须附日期化证据方成立**（项目自身"验证边界"文化，`README.md:10`）。
- webui：约 **99 个 ts/tsx 生产源 + 103 Vitest + 6 E2E spec**（`README.md:94-96`）。

### 1.4 总体结论
项目具备清晰的产品边界与成熟的工程文化（证据文化、fail-closed 贯穿、契约回溯校验）。**但"文档自报口径"与"代码实际"存在落差**，评审以下结论以**代码实地走查为准**，对 README 的夸大/过期陈述逐一校正。

---

## 2. 架构设计与技术实现

### 2.1 分层与装配
主张的分层为 `domain ← repositories ← application ← lan/panels`，依赖向下、DI 装配（`README.md:62-70`）。实际落地：

- **入口极薄**：`main.py:19` / `run.py:57` 仅转发到 `AssetsManager.app.main`；`app.py:138` 建 `QApplication`，`:146` 单实例锁（`QLocalServer`），`:170-181` 构造 `ApplicationBootstrap` 并存于 `app` 属性。
- **DI 容器名存实亡**：`di/__init__.py:30` 的 `ServiceContainer` 支持单例+工厂+环检测（`:86-133`），但 `_build_services` 之外仅注册了 `DatabaseManager/LibraryService/PluginService` 三个服务（`bootstrap.py:335-347`），**绝大多数服务在 `bootstrap.py:563-730` 手工构造**；且 `resolve` 对自定义工厂**不缓存**（`di/__init__.py:123-126`），存在重复构造/不一致单例风险。所谓"DI via ServiceContainer"在代码层面并未真正兑现。
- **每库作用域清晰**：`LibrarySession`（`context.py:133`，frozen）封装 `LibraryContext`（db_conn/tag_store…，`:64`）；`operation()` 租约（`:220-238`）与 `_finish_close` 有界排空（`:287-316`，30s 超时）；`LibraryRuntime`（`runtime.py:17`）持有 frozen 的 `LibraryScopedServices`，`close()`/`close_adapters()`（`:150/:115`）线性化关闭。**这是架构上最值得肯定的部分。**

### 2.2 数据流样例（打标签）
`tag_tree_controller` → `TagService.add_tag`（`application/tag_service.py:317`，`@session_operation` 租约）→ `tag_repository.add_tag`（`:400`，SAVEPOINT 写域）→ 回读后 `get_event_bus().publish(AssetTagsChanged)`（`:238-243`）→ 订阅者刷新 → `_reindex_search_documents`（`:346`）。跨层方向正确、边界清晰。

### 2.3 并发模型
- 后台任务走私有 `BoundedPool`（`workers.py:109`，`cancel_all`/`drain` 有界，`:142/:157`），优于裸 `QThreadPool`。
- LAN 服务跑在**独立守护线程**的新 `asyncio` loop（`server.py:149-150`、`:464`），跨线程用 `asyncio.run_coroutine_threadsafe`（`:573`），DB 阻塞调用 `asyncio.to_thread`（`:611/:1144`）。Qt GUI 主循环与 asyncio 循环分属两线程，靠事件/回调桥接——**共存干净**。
- SQLite 每库单连接 `check_same_thread=False` + 写锁串行化（`database.py:918/:683`）。

### 2.4 架构优势（结论）
1. 会话绑定仓库 + SAVEPOINT 嵌套事务 + 受控提交 + SQLITE_BUSY 重放（`_common.py:81-96/:241/:295`），写安全扎实。
2. 每库 `LibraryRuntime`/`LibrarySession` 显式关闭线性化、操作租约、有界排空（`runtime.py:150`、`context.py:220`、`workers.py:157`），基本杜绝 UI 悬挂。
3. `event_bus` 弱引用订阅（`event_bus.py:46-110`）解耦层；`errors.py` 类型化错误层次。
4. `BoundedPool` 代际/取消令牌可协作取消、超时回收（`workers.py:65-205`）。
5. SQLite 跨线程策略刻意且文档化（`database.py:918/:683`）。

### 2.5 架构弱点（结论 + 证据）
1. **DI 名义化**：容器仅 3 服务（`bootstrap.py:335-347`）、自定义工厂不缓存（`di/__init__.py:123-126`）。
2. **God-object `window.py`（~65KB）**：`MainWindow` 直接管启动、库、共享开关、导入池（`:1248`）、状态栏，绕过声称的 panels/lan 分层，可维护性差。
3. **全局事件总线跨库泄漏**：`get_event_bus` 进程单例（`event_bus.py:79`），与每库 `LibrarySession` 作用域冲突；关闭库后强引用处理器仍可能触发。
4. **单共享 SQLite 连接跨三线程**：GUI + QThreadPool 工人 + LAN `asyncio.to_thread` 执行器共用一连接（`server.py:611/:1144`、`database.py:918`），仅靠一把写锁（`:683`）串行；持锁时发生阻塞 await/长读易停摆（详见 §5.3）。
5. **抽象债**：仓库基类命名 `_CommerceRepository`/`shop_repository`（`_common.py:1-16`）源自异域复制，概念错位；`for_session` 每次重建并重复校验 owner（`_common.py:154/:217`），有冗余开销。

---

## 3. 功能模块与业务流程

### 3.1 模块地图（证据锚点）
- **桌面 `panels/`**：`file_list/`（网格/列表/详情浏览器：`_grid_widget.py`、`_detail_model.py`、`_model.py`、`_thumbnail_delivery.py`、`_loader.py`）、`info.py`（元数据编辑器，~91KB）、`tag_tree.py`、`sidebar.py`、`image_viewer.py`（OpenGL 查看器）。
- **`dialogs/`**（~23）：`sharing_settings_dialog.py`（~60KB）+ 分包 `sharing_settings/`（`_configuration_page.py`/`_access_page.py`/`_endpoint_page.py`/`_links_page.py`/`_ui.py`）；另有 `share_link_dialog.py`、`tag_editor_dialog.py`、`settings_dialog.py`、`plugin_manager_dialog.py`、`undo_panel.py`、`activity_panel.py`、`startup.py` 等。
- **LAN `lan/routes/`**：22 模块、`__init__.py` 导出 ~70 handler；`api.py setup_routes()` 注册 ~71 路由。分组：auth / files / downloads / metadata / tags / collections / favorites / gallery / shares / thumbnails / image / quota / users / websocket / system / pages / quicksearch / sequence。
- **webui/src**：pages（`BrowsePage`/`DetailPage`/`Gallery*`/`LoginPage`/`ShareReceivePage`/`AdminPage`/`LandingPage`，~12 个 `.tsx`）、stores（`AuthContext.tsx`/`RealtimeContext.tsx`）、hooks `use*`（~28）、api 工厂（`auth/files/shares/tags/metadata/...`）。**无 shop/store 页面。**
- **插件系统**：`plugin_api/types.py`（`HOST_API_VERSION=2`，贡献基类 `CommandOperator`/`FileParser`/`ContextMenuItem`/`PanelContributor`/`EventHook`/`CategoryContributor`/`ThemeTokenContributor`/`Preferences`）；`core/plugins/manager.py`（`PluginManagerService` `:82`）、`descriptor.py`、`host_context.py`（~72KB）、`loader.py`。`Plugins/` 仅含 `Addons`/`Docs` 示例。

### 3.2 端到端业务流（已追踪）
**(a) 密码保护分享 + 下载**
- 桌面：`ShareLinkDialog`（`share_link_dialog.py:24`）→ `ShareCreationTask`（`_share_api.py:71`）→ `share_service.create_share`。
- 创建：`handle_create_share`（`shares.py:63`）要求 `manage_links`（`:64`），校验 `password/expires_hours/max_downloads`（`:99-127`），返回 `/s/{id}`（`:146`）。
- 验证：`handle_verify_share_password`（`shares.py:223`）线程内 PBKDF2、暴力失败 429 锁定（`:246-254`），下发 cookie/token（`:270`）。
- 下载：`handle_share_download`（`shares.py:275`）→ `validate_access`（`:290`）查 token/过期/限额/范围；`increment_download` 超配额 → 429（`:337-345`）。

**(b) 局域网浏览 + 下载**：`handle_files`/`handle_directory_summaries`（`files.py`）→ 缩略图 `handle_thumbnail`（`thumbnails.py`，经 `validate_path`）；下载 `handle_download`/`handle_batch_download`（`downloads.py`）→ `build_zip_async` + `validate_path` + `read_safe_file`。

**(c) 桌面打标签**：`info.py:1340` `_add_tag` → `controllers/info_controller.py:265` → `application/tag_service.py:318` → `repositories/tag_repository.py:400`。

### 3.3 功能缺口与不一致（结论 + 证据）
1. **【HIGH-文档信用】商城子系统是"纸面功能"**：README 宣称"`/api/shop/*`(54 条)"含目录/购物车/结账/订单/投递/卖家/分析（`README.md:206`）。但全 `lan/` 树 grep `shop|commerce|catalog|cart|checkout|/orders` **仅命中 `mcp_server.py`/`tunnel.py`/`shares.py` 的注释**，无独立 `shop.py`、无功能性 catalog/cart/checkout 路由；webui 亦无 store 页面。**后端商城未实现，README 与代码严重脱节。**
2. **【MEDIUM】upload 能力已废弃却仍展示**：`dto.py:103,111` 列出 `upload` 能力、`sidebar.py:105` 映射上传图标，README 称"upload 已下线"（`README.md:212`）；无 `routes/upload*.py`、无 webui 上传页。
3. **【MEDIUM】桌面↔Web 功能奇偶差**：桌面有插件、撤销/重做、AI 自动打标签（`panels/_ai_tag_common.py`）、24 主题、完整图片查看器；webui 均无（无插件宿主、无 undo store、无 AI 打标签、仅 `useServerTheme`）。
4. **【MEDIUM】分享创建的鉴权双 enforcement 点**：桌面直调 `ShareService.create_share`（无 `manage_links` 检查），HTTP 路由才 `require_permission("manage_links")`（`shares.py:64`）——同一特权两套强制逻辑，易漂移。
5. **【MEDIUM】配额双账本风险**：`quota.py` 的 `handle_free_quota` 与 `free_download_quota_service` 存在，但 `handle_share_download`（`shares.py:337`）只调 `share_svc.increment_download`，**未查询访客免费配额**，两套配额可能漂移。

---

## 4. 代码质量与可维护性

### 4.1 测试与门禁
- 测试文件众多（约 310），分区合理（unit/integration/lan/desktop/core/plugins/e2e/performance）。
- 默认 `pytest -m "not e2e and not perf"`（`pytest.ini:16`）**直接排除 e2e 与 perf**；CI `test` job 仅跑该默认套件，`windows-regression`/`media-decoders` 仅跑极小子集（`ci.yml`）。最重的集成/性能路径**从不在 PR 上强制**。
- 质量门脚本丰富（`scripts/check_*.py`、`check_doc_stats.py`），文化良好。

### 4.2 Lint / 类型检查严格度
- `ruff.toml` 仅选正确性族（E/F/B/LOG/G/DTZ…，`:10-25`），**刻意省略风格/ANN/D**——合理，但类型标注卫生全压给 pyright。
- `pyrightconfig.json` 为 **basic 模式**（`:28`），且 `reportMissingImports/TypeStubs/ModuleSource` 全 `false`（`:29-31`）；`include`（`:2-21`）**排除整个 `AssetsManager/background` 与 `AssetsManager/core/plugins`**（含 `host_context.py` 1657 行）。**两大子系统从不进类型检查。**

### 4.3 构建与加速
- `setup_cython.py:5-10` 指定对 `core/cache.py`、`color_utils.py`、`format_utils.py`、`application/asset_filters.py` 做 2–5x 加速，但 `build.py:21-26` 仅调 PyInstaller，`AssetManager.spec` **无 `.pyd`/二进制条目**——**Cython 加速未接进发布构建**，最热模块 `cache.py` 仍以纯 Python 出货，速度声明未兑现。

### 4.4 可维护性：单体模块集中度
最大文件（行数）集中于风险点：`dialogs/settings_dialog.py` 1939、`panels/info.py` 1896、`panels/file_list/_loader.py` 1883、`core/schema_defs.py` 1780、`core/plugins/host_context.py` 1657、`application/reconciliation_queue.py` 1656、`core/database.py` 1610。多个 1600+ 行模块职责混杂（如 `_loader.py` 混合 UI 投递、ffmpeg 池、烘焙、追踪），变更风险高。另：`grep` 在 `AssetsManager` 中**未发现任何 TODO/FIXME/HACK 标记**——要么异常整洁，要么使用非标准标记，建议核实。

### 4.5 代码质量结论
**优点**：测试广度好、门禁脚本文化成熟、缩略图解码正确下沉到 `QThreadPool`/`QRunnable`（`panels/file_list/_loader.py:189,418`），常见缩略图路径不在 UI 线程。
**短板**：类型检查有盲点（basic + 子系统排除）、**无性能门**（perf 仅 nightly 且 `continue-on-error`）、Cython 加速未进构建、单体模块膨胀、DI 名义化。

---

## 5. 性能与安全性

### 5.1 安全性（总体评价：高）
安全工程水平是本项目最大亮点。已确认的**安全项**（证据）：
- **路径穿越**：`path_guard.py:57-118` 拒控制字符/NTFS ADS；`resolve`/`assert_under_root` 双检；`image.py:247`、`downloads.py:170`、`quicksearch.py:80` 均经 `PathGuard`，image 路由二次 `assert_under_root` 防 TOCTOU。
- **ZIP 注入(slip)**：`_zip_entry_allowed`（`helpers.py:650-658`）`assert_under_root` + 拒符号链接；归档名来自 `os.path.relpath`（`:684`），`read_safe_file` 再校验。
- **HMAC 方案**：`ts.nonce.sig`，nonce 用 `secrets.token_hex(4)`（`domain/auth.py:153,218,278`），24h TTL，`hmac.compare_digest` 防时序。
- **密码哈希**：PBKDF2-SHA256 **600k** 迭代 + 32 字节随机盐、访问密钥 50k（`domain/auth.py:28,55,70`）；`token_secret = secrets.token_hex(32)` 每次启动生成（`bootstrap.py:685`），无硬编码密钥。
- **失败关闭**：`has_active_users` 出错→视为需认证（`server.py:1062-1073`、`auth_repository.py:210-217`）；无认证拒绝开隧道（`server.py:730-742`）。
- **注入面**：LAN 层无 `eval`/`os.system`/`pickle.load`/`yaml.load`；`subprocess` 仅用于固定参数 cloudflared 启动（`tunnel.py:265-278`）；`urlopen` 仅访问 GitHub 二进制下载，**无 SSRF**；image 路由只读 `library_root` 本地文件。
- **令牌撤销**：`revoked_token_repository` + 内存+DB 持久化（`server.py:584-611`、`auth_service.py:312-327`）。
- **隧道供应链**：固定版本 + SHA256 校验、失败关闭（`tunnel.py:36,59-69`）。
- **XSS**：webui 静态/JSON，pages 未发现反射未转义输入，风险低。

### 5.2 安全性弱点（按严重度）

| 级别 | 问题 | 证据 |
|---|---|---|
| 🔴 CRITICAL | **插件无沙箱**：与宿主同解释器、`importlib` 直接 `exec_module`（`loader.py:89,93`）；`host_context.py` 自述"same interpreter can call `_host_identity` directly"（`:354-357,1298-1319`）；自动发现 `Plugins/Addons/` 与 `RuntimeData/Shared/plugins/`，**无签名/白名单/审查**（`manager.py:205-232`）。可联网/公网暴露下 = 以桌面用户身份 RCE。 | `core/plugins/loader.py:89,93` |
| 🟠 HIGH | **密码模式令牌可被 DB 读取者伪造**：`generate_token` 的 HMAC 密钥就是存储的 `password_hash` 本身（`domain/auth.py:155,177`）。能读 `users.password` 列即可 mint 有效登录令牌（user/share 令牌依赖独立 `token_secret`，此令牌不依赖）。 | `domain/auth.py:155,177` |
| 🟡 MEDIUM | **暴力破解控制弱于声称**：实际 `AuthRateLimiter(max_attempts=10, window_seconds=300)`（`server.py:122`、`security.py:123,282-294`），**无硬性账户锁**；桶 per-IP（隧道下 `tunnel:client`），NAT 下 10 次/5 分钟被所有用户共享。 | `server.py:122`、`security.py:282-294` |
| 🟡 MEDIUM | **白名单在隧道下被绕过**：`security.py:269-276` 隧道激活时所有 loopback 来源**绕过 IP 白名单**；公网隧道访问控制完全依赖认证，运维易误判"白名单保护"。 | `security.py:269-276` |
| 🟢 LOW | 认证 Cookie：`httponly`+`Lax`+仅 TLS 时 `Secure`（`_helpers.py:506-516`），明文 HTTP 下不 Secure，可接受。 | `_helpers.py:506-516` |

### 5.3 性能（结论 + 证据）
- **主导性能风险在 DB 写层而非图片解码**：`core/database.py:461-536` 的 `_WriteGate.write()` 全库**仅允许一个写者**（`wait_for(lambda: not self._writer and self._readers == 0)`，`:523`），所有元数据写/N+1 upsert 全局串行，抵消了 WAL 本应带来的并发（`PRAGMA journal_mode=WAL`，`:399`）。
- **连接身份标记脆弱**：`_connection_locks` 以 `id(conn)` 为键（`database.py:543-552`），代码自承 sqlite3 连接不可弱引用（注释 539-542）；连接关闭/GC 后 Python 复用 `id()`，复用 id 可能继承陈旧 `_ConnectionWriteState`（owner_thread/owner_depth）→ **锁归属错乱或跨库锁串扰**。兼容路径共享一个 fallback 锁 `_unmanaged_write_state`（`:545`）。
- 单连接跨 GUI + QThreadPool 工人 + LAN `asyncio.to_thread` 三线程（`server.py:611/:1144`、`database.py:918`），持锁时阻塞 await/长读易停摆。
- **无性能门**：默认套件 deselected `perf`/`e2e`（`pytest.ini:16`）；`nightly-perf.yml` `continue-on-error: true`（cron 仅），无阈值断言阻断构建；`tests/performance`(2) + `tests/perf`(8) 全 opt-in。
- 正面：缩略图解码正确下沉到 worker 线程（`_loader.py:189,418`）。

---

## 6. 潜在风险与现存问题（风险登记）

| # | 风险 | 级别 | 维度 | 关键证据 |
|---|---|---|---|---|
| R1 | 插件同进程无沙箱，公网暴露 = RCE | 🔴 CRITICAL | 安全 | `core/plugins/loader.py:89,93`；`host_context.py:354-357` |
| R2 | 密码模式令牌 HMAC 密钥复用 `password_hash`，DB 可读即伪造 | 🟠 HIGH | 安全 | `domain/auth.py:155,177` |
| R3 | 应用层全局写串行化 + `id(conn)` 锁归属，多库/高并发停摆 | 🟠 HIGH | 性能/架构 | `database.py:523,543-552` |
| R4 | 类型检查盲点：basic 模式 + 排除 `background`/`core/plugins` 两子系统 | 🟡 MEDIUM | 质量 | `pyrightconfig.json:2-21,28-31` |
| R5 | README↔代码脱节：商城 54 路由后端不存在、upload 废弃仍展示、仓库数自相矛盾 | 🟡 MEDIUM | 文档信用 | `README.md:206` vs `lan/` grep；`dto.py:103`；`README.md:50 vs 84` |
| R6 | 登录失败锁定弱于声称（10/300s per-IP，无账户锁） | 🟡 MEDIUM | 安全 | `server.py:122`；`security.py:282-294` |
| R7 | 隧道下 IP 白名单被绕过（误导运维） | 🟡 MEDIUM | 安全 | `security.py:269-276` |
| R8 | 配额双账本：分享下载不查访客免费配额 | 🟡 MEDIUM | 功能 | `shares.py:337` vs `quota.py` |
| R9 | 全局 event_bus 跨库泄漏，关闭库后处理器仍可能触发 | 🟡 MEDIUM | 架构 | `event_bus.py:79` |
| R10 | CI 仅 `master/main` 触发，特性分支不进门禁 | 🟡 MEDIUM | 流程 | `ci.yml:3-7` |
| R11 | Cython 加速未接进发布构建（cache.py 仍纯 Python） | 🟡 MEDIUM | 性能/构建 | `setup_cython.py:5-10` vs `build.py:21-26` |
| R12 | DI 名义化（仅 3 服务、工厂不缓存） | 🟢 LOW | 架构 | `bootstrap.py:335-347`；`di/__init__.py:123-126` |
| R13 | God-object `window.py`(~65KB) 绕过分层 | 🟢 LOW | 架构/可维护 | `window.py:1248` |
| R14 | 单体模块膨胀（≥7 个 1600+ 行文件） | 🟢 LOW | 可维护 | `settings_dialog.py` 等 |
| R15 | 桌面↔Web 功能奇偶差（插件/undo/AI 打标签/主题） | 🟢 LOW | 功能 | webui/src 缺失 |

---

## 7. 改进建议与优化方向（可落地，按优先级）

### P0 — 必须在"公网暴露"前封堵（安全）
1. **插件沙箱化（R1）**
   - 短期：默认**禁用自动加载**，改为用户显式信任；对 `Plugins/Addons/` 与 `RuntimeData/Shared/plugins/` 做**代码签名校验**（启动校验签名，不符则拒绝加载）。
   - 中期：插件迁到**独立子进程 + 受限 IPC**（如 `multiprocessing` + 白名单消息协议），剥夺 filesystem/network/process 直通能力。至少把 `host_context.py` 暴露的 `_host_identity` 等敏感句柄从插件可见面移除。
2. **密码模式令牌改用独立 secret 签名（R2）**：`generate_token/verify_token`（`domain/auth.py:146-178`）的 HMAC 密钥从 `password_hash` 改为独立的 `token_secret`（与 user/share 令牌一致，`bootstrap.py:685` 已生成），使"读 DB"不再等于"可登录"。
3. **明确隧道安全语义（R7）**：在 `security.py:269-276` 处加启动期日志/文档告警——"隧道流量不受 IP 白名单约束，访问控制仅由认证保证"，避免运维误判。

### P1 — 下一迭代（架构/性能/质量）
4. **写并发瓶颈（R3）**：将 `_WriteGate` 的全局单写者（`database.py:523`）改为**每库独立写锁**，避免跨库互相阻塞；用连接池 + 持久对象标识替代 `id(conn)` 做锁归属（`database.py:543-552`），消除 `id()` 复用的串扰。
5. **类型检查补全（R4）**：`pyrightconfig.json` 升级 `typeCheckingMode:"strict"`（分步），并把 `AssetsManager/background`、`AssetsManager/core/plugins` 纳入 `include`；对 `host_context.py`(1657 行) 优先补注解。
6. **校正文档（R5）**：README 的"商城 54 路由"改为"规划中/未实现"，或真正实现后端；upload 从 `dto.py:103,111` 与 `sidebar.py:105` 移除或标注 deprecated；统一仓库数量口径（12 vs 17）。
7. **配额统一（R8）**：分享下载路径 `shares.py:337` 合并调用 `free_download_quota_service`，消除双账本。
8. **失败锁定（R6）**：实现 per-username 失败计数 + 硬性锁定（而非仅 per-IP 桶），对齐 README 声称的"5 次/60s 锁"。

### P2 — 持续打磨（可维护/流程）
9. **Cython 接构建（R11）**：`build.py`/`AssetManager.spec` 增加 `.pyd` 步骤，或明确放弃该加速并删除 `setup_cython.py` 以免误导。
10. **CI 覆盖特性分支（R10）**：`ci.yml` 增加 `pull_request` 宽泛触发或对特性分支加 required-status；把 `perf` 门从 `continue-on-error` 改为带阈值的阻断（至少 nightly 失败告警）。
11. **拆分单体模块（R13/R14）**：`window.py`、`settings_dialog.py`、`info.py`、`_loader.py`、`database.py`、`host_context.py`、`reconciliation_queue.py`、`schema_defs.py` 按职责切片（如 `_loader.py` 拆出 ffmpeg 池/烘焙/追踪）。
12. **DI 实质化（R12）**：把 `bootstrap.py:563-730` 的手工装配迁回 `ServiceContainer` 并修复工厂缓存（`di/__init__.py:123-126`）。
13. **event_bus 按会话隔离（R9）**：用每库 `LibrarySession` 作用域的总线替代进程单例（`event_bus.py:79`），关闭库时统一注销处理器。
14. **桌面↔Web 奇偶（R15）**：优先补齐 Web 端"主题跟随 / 撤销提示"，插件与 AI 打标签若短期不跨端，至少在文档声明差异。

---

## 8. 结论与决策建议

| 维度 | 评级 | 一句话 |
|---|---|---|
| 总体概述与背景 | B+ | 产品边界清晰、工程文化成熟，但文档自报口径需独立校验 |
| 架构设计与技术实现 | B | 分层/事务/并发设计上乘；DI 名义化、God-object、全局总线拖累 |
| 功能模块与业务流程 | B- | 核心流完整；商城纸面化、upload 废弃展示、双端奇偶差 |
| 代码质量与可维护性 | B- | 测试广度好；类型盲点、无性能门、单体膨胀 |
| 性能 | B- | 缩略图下沉到位；DB 全局写串行 + `id()` 锁脆弱是主风险 |
| 安全性 | B+（暴露前需补 2 处） | 路径/HMAC/PBKDF2/fail-closed 扎实；插件沙箱与令牌签名是硬伤 |
| 风险与问题 | 见 §6 | 1 CRITICAL / 2 HIGH / 多处 MEDIUM |
| 改进方向 | 见 §7 | P0 三项必须先行，P1 纳入下迭代 |

**给项目团队的三条决策建议：**
1. **发布红线**：在允许 Cloudflare 公网隧道前，**必须**完成 R1（插件沙箱/签名）与 R2（令牌签名）——否则即是以桌面用户身份暴露于 RCE。
2. **债务偿还排序**：先 R3（写并发）与 R4（类型盲点），再 R5（文档信用，关乎用户信任），其余排期。
3. **流程加固**：把"商城功能存在"从 README 撤下或实现，避免对外承诺与代码不符引发信任风险。

---

*本报告所有结论均基于 2026-08-31 的源码实地走查；行号锚点供直接跳转核实。对仓库既有 dated 文档中"已修复/已验证"类声明，建议仍按本项目"验证边界"文化附日期化证据复核。*
