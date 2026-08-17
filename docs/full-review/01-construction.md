# 软件构造详情（01-construction.md）

> 审查日期：2026-08-11 · 工作区实况（含未提交改动）· 行号实测

## 1. 项目定位与三端形态

**AssetManager**：个人数字资产管理平台，桌面优先、Web 为辅的混合应用。

```
┌─ 桌面端（PySide6/Qt6，主界面）─────────────────────────────┐
│  run.py/main.py → app.py → MainWindow → panels/widgets/dialogs │
│  controllers（无 Qt 业务逻辑）→ application 服务层             │
└────────────────────────────┬──────────────────────────────────┘
                             ▼
┌─ LAN 端（aiohttp，内置分享服务器，可选）────────────────────┐
│  ShareManager → _LanServerImpl → 139 条路由（REST+WS+SPA）    │
│  → WebSocket /ws → 浏览器（webui/dist）                       │
└────────────────────────────┬──────────────────────────────────┘
                             ▼
┌─ Web 端（React 18 + Vite + TS SPA，webui/）────────────────┐
│  由 LAN 服务器托管 dist；REST /api/* 权威 + WS 失效提示      │
└──────────────────────────────────────────────────────────────┘
```

## 2. 技术栈全景

| 层 | 技术 | 说明 |
|---|---|---|
| 桌面 UI | PySide6 >=6.6,<7（Qt6） | QDockWidget/QAbstractListModel/QThreadPool/QOpenGLWidget/QtSvg；无内嵌浏览器 |
| LAN | aiohttp >=3.9 | 异步 HTTP + WebSocket + middleware；可选依赖（requirements-lan.txt） |
| 持久化 | SQLite3（WAL） | 每库独立文件，迁移 v1-v23，schema 契约校验 fail-closed；少量 JSON（settings/tag_library/tools） |
| 图像 | Pillow>=10 | 缩略图（WEBP/Lanczos）、EXIF 方向、NSFW 模糊 |
| 密码学 | hashlib/hmac/secrets | PBKDF2-SHA256（access key 50k / 密码 100k 迭代）、HMAC-SHA256 令牌、compare_digest |
| 二维码 | segno | 分享链接 QR |
| 隧道 | cloudflared | 公网穿透（自动下载+校验+崩溃监控） |
| 前端 | React 18.3.1 / TS 5.6 / Vite 7.3 / Tailwind 3.4 / react-router 7.18 / lucide-react | 无状态库（全 Context） |
| 加速 | Cython | cache/color_utils/format_utils/asset_filters 编译（.pyd，源码回退保留） |
| 打包 | PyInstaller 6.x | 单目录 bundle，SPA 打进 dist |
| 质量 | ruff/pyright/pytest/PySide6 offscreen/Vitest/Playwright | CI 9 job |

**Python 版本**：本机 3.14（当前实测 3.13 全量亦过）；CI 矩阵 3.12/3.13/3.14。

## 3. 六层架构与依赖方向

```
Presentation（桌面 UI + LAN routes + React）
   │ 调用
Controllers（无 Qt 业务控制器，桌面专用）          LAN routes（handler → 服务）
   │                                              │
   ▼                                              ▼
Application 服务层（39 模块：bootstrap 装配 → 每库 LibraryRuntime/LibrarySession）
   │
   ▼
Repositories（15 个 SQL 仓库：for_session 绑定 + savepoint 事务 + CAS）
   │
   ▼
Domain（纯值对象 + 事件 + 错误层级，无基础设施依赖）
   ▲
Infrastructure core/（database/迁移/schema 契约/锁/路径/主题/图标/缓存/插件）
   ▲
LAN（aiohttp：认证/限流/隧道/WS）── 与 core 共享，经 application 服务访问数据
```

**依赖方向**：`domain ← repositories ← application ← (lan | controllers/panels)`；`core` 被所有层共享；`di/`（ServiceContainer）供 bootstrap 使用；`webui` 独立，经 `/api/*` 与 `/ws` 消费。

## 4. 装配与生命周期（DI 图）

### 4.1 启动链（桌面）

```
run.py/main.py → app.main()
 → crash_handler.install()（sys.excepthook + 脱敏 + 512KB 轮转）
 → QApplication（HighDPI + themes.stylesheet + ui_scale）
 → i18n.init()（en/zh/ja，AppSettings.language）
 → ApplicationBootstrap（ServiceContainer 注册：DatabaseManager 实例 +
      LibraryService/Asset/Metadata/Tag/FileOperation/Thumbnail/Search/
      AssetIndex/Undo/Plugin 类注册自动单例）
 → discover_plugins() → StartupWindow → _on_open(path)
 → MainWindow(bootstrap) → workspace.add_library(path)
 → LibraryService.open_session(root)  [锁→身份→迁移→LibrarySession]
 → bootstrap.runtime_for(session)     [LibraryScopedServices + RuntimeEventRouter
      + 3 个 lifecycle adapter + reconciliation worker 启动]
 → 可选 lan_auto_start → ShareManager.start → _LanServerImpl
```

### 4.2 每库作用域（关键结构）

| 结构 | 内容 |
|---|---|
| `LibraryContext`（frozen） | root/data_dir/thumb_dir/db_conn/tag_store/project_data/root_key + `_liveness` |
| `LibrarySession`（frozen+可变） | event_token、operation 租约、`_publish_while_live` 线性化、幂等 close；`register_library_session` 跨层令牌 |
| `LibraryRuntime` | services_snapshot、event_router、next_revision 单调、epoch(uuid4)、分阶段 close |
| `LibraryScopedServices`（frozen 14 字段） | session/sharing_services/integrity/maintenance/export/metadata/tag/thumbnail/file_operation/undo/plugin/asset_index/_lan_holder/performance/reconciliation 系列 |
| `RuntimeSharingServices` | token_secret（每 Runtime 随机 32B）+ auth_service + share_service |
| `LanRuntimeServices`（懒投影） | asset/project/search/gallery/favorite，经 `_LanServicesHolder` 单飞物化（代数失败共享 + close 线性化） |
| 商务栈（不进 bootstrap） | shop/order/quota/seller 系列由 `lan/routes/shop.py::get_commerce_services()` 每 LAN 实例缓存构造 |

## 5. 核心机制（设计意图）

| 机制 | 位置 | 要点 |
|---|---|---|
| **会话租约** | context.py `operation()`/`session_operation`/`_publish_while_live` | 每服务方法自动持租约；close 排空存量租约；发布与关闭精确线性化（杜绝 use-after-close） |
| **fail-closed 贯穿** | server.py `_has_active_users`（30s 负缓存）、library_lock、schema 契约、`_check_blur`、settings 损坏隔离 | 无法确认安全状态时拒绝而非放行 |
| **CAS + 代数** | asset_index revision、reconciliation lease_token/generation、`_LanServicesHolder` 代数、订单状态 CAS、配额条件 UPDATE | 所有并发/重试有代际冲突检测 |
| **事件驱动投影失效** | EventBus → RuntimeEventRouter → WS `projection_invalidated`（epoch+revision+domains+paths）→ 前端失效重拉 | **WS 只是失效提示，HTTP snapshot 才是权威** |
| **锁体系** | `LibraryLock`（QLockFile 引用计数、staleLockTime(0) 永不自行判陈旧）、`db_write_lock`（连接级 RLock + `_WriteGate` 读写门）、`acquire_path_locks`（进程级路径锁，normcase 排序防死锁） | 跨进程/进程内/路径三级互斥 |
| **原子持久化** | JsonStore/AppSettings：mkstemp+fsync+os.replace；SQLite：SAVEPOINT 迁移与事务；身份标记：os.link 无覆盖发布 | 崩溃无半写 |
| **值对象 + 契约化 schema** | frozen dataclass 贯穿；`schema_defs` SchemaObjectContract 逐版本校验（`_versioned_schema_contract` 回溯历史形状） | 迁移边界磁盘兼容契约 |
| **双轨兼容** | 所有服务保留裸连接/旧接口路径（allow_unmanaged/session_contract 令牌区分真会话） | 渐进式规范化 |
| **幂等** | 结账 request_key（casefold+sha256）、delivery request_key 哈希、checkout_generation、receipt 回放安全 | 重试安全 |
| **性能可观测** | PerformanceRecorder（200 有界环）：db 写锁 wait/hold、grid 帧/纹理、file.command 四级遥测；"遥测失败不影响业务" | 内建 |

## 6. 存储体系

- **SQLite**：每库 `RuntimeData/{basename}_{sha256[:10]}/assetmanager.db`，WAL + foreign_keys ON；`_SCHEMA` 4 基线表 + 迁移 v1-v23（完整清单见 02 §5）。
- **JSON**：`RuntimeData/Shared/settings.json`（原子+损坏隔离）、`tag_library.json`（规范标签同义词）、`tools.json`（外部工具定义）、`<lib>/favorites.json`+`recent.json`（桌面侧栏，JsonStore）。
- **缩略图**：`<lib>/.thumbnails/*.webp`（键=sha256(path|mtime)[:16]）；内存 8192 LRU。
- **运行时文件**：`RuntimeData/Shared/library-{sha256[:16]}.lock`（库锁）、`Shared/crash.log`、`Shared/plugins/`、`Shared/{basename}_{sha256[:10]}.identity`（身份标记）。
- **Undo 备份**：系统临时目录 `AssetsManager_undo_*`（+ `{backup}.projection.json` 标签/元数据/收藏快照 + owner 侧车文件）。

## 7. 认证与令牌（LAN）

六种 principal（guest/password/access_key/local_ui/user/share）+ 8 位 capabilities（browse/preview/download/upload/manage_links/manage_users/settings/realtime）。

| 令牌 | 格式 | TTL | 密钥 |
|---|---|---|---|
| password token | `ts.nonce.sig` | 24h | password_hash |
| local_ui token | `ts.nonce.sig` | 24h | local_ui_auth_secret（派生自 token_secret+认证配置） |
| user token | `ts.uid.nonce.sig` | 24h | Runtime token_secret |
| share token | `ts.nonce.sig` | 1h | token_secret |
| seller session | 不透明（内存） | 12h | hash_seller_token |
| quota/visit cookie | 签名 cookie | 30d/24h | local_ui 派生/进程随机 |

全部 sig=HMAC-SHA256[:32]；新格式带 nonce（消除同秒确定性），verify 兼容旧格式。**不支持 query 参数认证**（防日志/Referer 泄露）。

## 8. 构建与打包

- `build.py`：clean → PyInstaller（AssetManager.spec）→ optimize（删非白名单 Qt 翻译/opengl32sw/DLL）→ report；产物 `dist/AssetManager/AssetManager.exe`（约 127MB）。
- `AssetManager.spec`：入口 run.py；datas 含 icons/i18n/Themes/`webui/dist`/Plugins；hiddenimports 覆盖 aiohttp 全家 + lan/application 模块树；excludes 优化体积。
- `--package-smoke`：冻结态验证 QtSvg + icon 渲染。
- 开发态：`vite dev`（代理 /api、/ws → 127.0.0.1:8080）。

## 9. 质量门（实测，详见 07）

- `ruff check AssetsManager tests scripts run.py` → **全绿**
- `pytest tests -q` → **2952 passed, 7 skipped, 0 failed**（304s）
- pyright（白名单 scope，basic 模式）CI 0 errors；compileall CI 全绿
- 前端：`npm test`（90 Vitest 文件）+ typecheck + build + Playwright E2E（30 用例，28 passed/2 skipped）

## 10. 关键设计取舍（新任务必读）

1. **单进程模型**：桌面与 LAN 同进程；SQLite 单连接 + 连接级写锁；跨进程一致性靠文件锁（WAL+timeout=30）与 CAS。
2. **"WebSocket 只是失效提示"**：前端断线恢复用 HTTP `/api/revision` 权威游标；广播帧 >1MB 截断 paths（不静默丢）。
3. **rotate 语义 = 轮换作废**：投递令牌 rotate 同事务作废旧令牌，总配额守恒（见 03 §B5）。
4. **guest 默认不可下载**（`lan_guest_download` 默认 False）；下载经免费配额（20 次/日，匿名身份=签名 cookie）。
5. **插件权限门禁是诚实/意图边界**：`host.services`、`settings.write` 等 token 在主机 API 上有强制拦截（缺权限拒绝/返回 None），但插件同解释器运行无沙箱，任何门禁都可用标准库直通绕过，不构成安全边界。
6. **隐藏文件不索引**（展示口径统一）；目录 mtime 相等判定不可靠（M6a-18 回退，需迁移支持）。
7. **测试夹具时钟坑**：mock clock（1000.0）与数据库默认时间戳基准不同——令牌"最新"判定用 rowid 排序（免疫时钟）。
