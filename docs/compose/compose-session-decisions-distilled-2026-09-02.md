# compose 会话决策速查（二次蒸馏 · 2026-09-02）

> 状态:**现行** · 本文档为 2026-09-02 收敛轮对 `docs/compose/distilled/` 下 9 份「历史蒸馏(已完结会话摘要)」的**二次蒸馏合并产物**,取代清单见文末「取代清单」。

> 9 份原件**零改写**归档至 `docs/archive/2026-09/compose-distilled-superseded/`;更早的 specs/plans/handoffs 99 份原件见 `docs/archive/2026-08/compose-raw/`。检索规则同原账本:**蒸馏层(此处)为日常入口,原件仅追溯**。

## 来源批次一览

| 批次 | 覆盖(原 99 份中的) | 原文件 |
|---|---|---|
| 2026-06-17~18 批：架构重构与主题系统 | 原 7 份(06-17 架构重构设计/计划 + 06-18 主题系统与主题编辑器) | `2026-06-17-18-architecture-and-theme-system.md` |
| 2026-06-19~21 批：背景效果/主题 UI/性能/分享/WebUI 视觉 | 原 12 份(06-19 背景效果/主题 UI、06-20 性能/分享 UI、06-21 分享系统/WebUI 视觉) | `2026-06-19-21-ux-performance-sharing-webui.md` |
| 2026-07-13 批：WebUI React 迁移与 LAN 安全修复 | 原 4 份(WebUI React 迁移设计/计划 + LAN 安全修复 + view mode 稳定 id) | `2026-07-13-webui-react-migration.md` |
| 2026-07-15 批：投递安全/文件操作一致/LAN-WebUI 可靠/作用域服务 | 原 10 份(投递安全/文件操作一致/LAN-WebUI 可靠/作用域服务四大批 + anchor worktree) | `2026-07-15-delivery-fileops-reliability-batches.md` |
| 2026-07-17 批：渲染/元数据/主题稳定性 + 早期审计 | 原 7 份(渲染/元数据/主题稳定性五批 + 早期 LAN 错误审计与 P1 审计结论) | `2026-07-17-rendering-metadata-batch.md` |
| 2026-07-21 架构重定标批：Desktop-LAN-WebUI 分层与运行时 | 原 14 份(分层边界/运行时作用域/事件路由/工作区模型/任务链) | `2026-07-21-architecture-recalibration.md` |
| 2026-07-21 功能/门禁子批：预览池/信息面板/WebUI 工作区/窗口退出 | 原 19 份(预览池/信息面板/WebUI 工作区/会话关闭/窗口退出/依赖安全) | `2026-07-21-feature-gates-batch.md` |
| 2026-07-24 批：WebUI 遗留清理与文件列表项目交互 | 原 6 份(WebUI 遗留清理 + 文件列表项目交互) | `2026-07-24-webui-cleanup-filelist.md` |
| 2026-08-03~04 会话交接摘要(webui-02/desktop-ui-03/mainline-04) | 原 19 份(三会话交接包:webui-session-02/desktop-ui-session-03/mainline-session-04) | `2026-08-03-04-session-summaries.md` |

## 各批次速查

### 2026-06-17~18 批：架构重构与主题系统

- **覆盖**：原 7 份(06-17 架构重构设计/计划 + 06-18 主题系统与主题编辑器)
- **背景**：- 06-17:启动"严格分层架构重构",7 阶段自底向上(SQLite 线程安全 → 应用层清理 → lan/auth.py 清理 → 单例移除 → 面板解耦 → 会话生命周期 → 架构边界测试),目标:每层只经明确定义接口依赖下层,消灭全局函数回退/重复代码/隐式跨线程访问。

**决策要点**
1. **架构重构 7 阶段 + 每阶段独立可提交**:P1 SQLite 跨线程安全(审计 LAN 路由 DB 路径,回归测试并发读)→ P2 应用服务统一 ConnectionProvider(移除 `get_lib_db()` 回退)→ P3 lan/auth.py 只留 re-export + init_tables,DB 操作迁入 AuthRepository/ShareRepository → P4 移除 `get_manager()/get_store()/get_project_data()/get_library_service()` 全局单例(先 deprecated 包装再删)→ P5 面板删除 `has_bootstrap()` 回退路径,强制 `require_scoped_services()` → P6 LibrarySession.close() 关闭会话资源、切库先关旧会话、is_closed 守卫 → P7 扩展架构边界测试(domain 不 import sqlite3/上层;repositories 只依赖 core.database+domain;lan 不 import Qt/panels 等) | design [S2-S9]
2. **质量门(每任务)**:`ruff check .` + `pyright` + `compileall AssetsManager -q` + `pytest -q`(当时基线 603 passed) | design [S1]
3. **主题文件约定**:`Assets/Themes/` 下 `D_`(暗,内置不可编辑)/`L_`(亮,内置)/`U_`(用户,可编辑可删)前缀;旧 `AssetsManager/themes/*.json` 迁移并自动映射旧主题名;PyInstaller datas 更新 | custom-theme-design [S1][S4]
4. **ThemeLoader 动态加载**:启动扫描 + JSON schema 校验(必须含 colors/properties)+ QFileSystemWatcher 热重载;`core/themes.py` 改为委托 ThemeLoader | [S2]
5. **主题选择器三入口**:外观模式(Dark/Light/Follow System)过滤、主题菜单(悬停预览/点击确认/可复制为自定义)、自定义菜单(编辑/导出/删除/新建 U_ 前缀) | [S3]
6. **主题编辑器实时预览**:设置对话框左右分栏(左:外观模式+主题列表+自定义;右:全组件预览:按钮/输入/标签/列表/表格/对话框/复选/滑条/进度/GroupBox);选主题→apply_theme 实时渲染 | theme-editor-phase2 [S1][S2]
7. **HSV 取色器**:HSV 色轮 + 亮度滑条 + RGB/HSV 切换 + HEX 输入 + 实时预览;预览区色块点击打开,改色实时应用到主题 JSON | phase3(基于 phase2 [S4])

**落地状态（2026-08-27 抽查）**
- **架构分层:✅ 已落地并继续演进**:`check_boundaries.py`/`check_layers.py` 门禁 + `tests/unit/test_architecture_boundaries.py` 均存在且全绿;`tag_store.get_store()`、`project_data.get_project_data()` 仍保留为 deprecated 包装(部分旧单例清理未彻底,属已知遗留);`LibrarySession` 具备 `_begin_close/_finish_close/is_closed` 语义(远超 P6 范围)。
- **主题基础设施:✅ 已落地**:`core/theme_loader.py`(315 行,scan/validate/hot-reload)+ `core/themes.py`(735 行,委托加载 + 22 主题)+ `Assets/Themes/`(24 JSON);`dialogs/settings_dialog.py` 主题选择器;`core/color_utils.py`/`ui_scale.py` 支持。
- **主题编辑器:✅ 已落地**:`widgets/theme_preview.py`(714)+ `dialogs/theme_preview_dialog.py`(238)+ `dialogs/color_picker_dialog.py`(216)+ `widgets/hsv_wheel.py`(218)。
- P1 审计结论记录于 `docs/compose/plans/p1-audit-findings.md`("无并发安全问题,修复可跳过",见 07-17 批摘要)。

**仍生效的约束 / 未决项**
- 层依赖规则(domain 零上层依赖、panels 不经 DB、lan 不 import Qt)仍是当前架构红线,由静态门禁强制。
- deprecated 全局包装(`get_store`/`get_project_data` 等)仍未完全移除——作为兼容 seam 保留,新代码不得使用。
- 主题文件前缀约定与"热重载"语义仍生效。

### 2026-06-19~21 批：背景效果/主题 UI/性能/分享/WebUI 视觉

- **覆盖**：原 12 份(06-19 背景效果/主题 UI、06-20 性能/分享 UI、06-21 分享系统/WebUI 视觉)
- **背景**：- 06-19~21 五条设计线:桌面背景增强(视频+模糊/马赛克)、主题选择器 UI 重构、性能优化(缓存+Cython)、分享模块 UI/UX 重设计、LAN Web UI 视觉升级。全部为 PySide6/WEB 前端层面的产品级设计,为后续 07-13 WebUI React 重写提供了视觉基线。

**决策要点**
1. **背景增强**:设置项(+视频背景 QMediaPlayer 自动循环静音 + 图片模糊/马赛克,强度可调;视频时效果区置灰);存储键 `bg_type/bg_blur_enabled/bg_blur_intensity/bg_mosaic_enabled/bg_mosaic_intensity`;模糊作用于原图缩放前;马赛克=降采样再就近放大 | background-enhancement [S2]
2. **主题 UI 重构(三区→两按钮)**:设置对话框主题区改为 [模式按钮 深色▼][主题按钮 Forest Dark▼] 双 popup;模式切换自动选该模式首个主题;自定义主题按基色亮度自动归入 Dark/Light(luminance<128→Dark);菜单含新建/编辑(仅自定义启用)/导入/删除 | theme-ui-redesign [S2][S3]
3. **目录元数据缓存**:新增 SQLite `directory_cache(dir_path PK, item_count, preview_path, mtime, scanned_at)`,mtime 校验失效重扫;`AssetService.list_directory()` 默认不扫摘要、LAN `?summaries=true` 按需;桌面 async 首屏渲染目标 1000 文件 <100ms | performance [S1]
4. **Cython 热点加速白名单**:仅 4 个纯计算模块——`core/cache.py`(LRUCache)、`core/color_utils.py`(hex↔rgb)、`core/format_utils.py`(format_size)、`application/asset_filters.py`(matches_search/is_hidden/sort_key_for_entry);排除 Qt 依赖、`__future__ annotations`、I/O 密集模块 | performance [S2]
5. **分享桌面快速入口**:文件右键"Quick Share"浮出卡片(文件名/数量/大小 + 生成链接 + 复制 + QR + 密码/限次/限时折叠项),入口=右键+工具栏+`Ctrl+Shift+S`;托盘图标绿=分享中 | sharing-ui [S1]
6. **分享管理对话框 4 页**:概览(状态卡/快速分享/活动/隧道)/分享链接(表格+搜索过滤+批量)/用户管理(管理员/邀请码/在线 kick /访客默认权限)/设置(网络/安全/品牌/高级) | sharing-ui [S2]
7. **实时刷新与反馈**:写操作统一发 `data_changed` 信号驱动自动刷新;活动 2s 轮询(原 6s)+ 新条目淡入;状态卡 300ms 边框色动画;复制按钮"Copied ✓"1.5s;建链 loading→结果展开+QR;删除确认→淡出→toast;隧道"Connecting...";API 错误红色 toast 5s;骨架屏 | 06-21 share-system [S1-S3]
8. **Web 视觉升级**(为 React 重写提供基线):Lucide SVG 图标、Inter 字体、基字 16px、统一动画 token(--ease-out/duration 150-300ms)、骨架 shimmer、可见焦点环、hover/press 反馈;精化色板(indigo #818cf8 强调、#1e1e2e 卡片底、slate 文本) | web-ui-visual-upgrade [S1-S4]

**落地状态（2026-08-27 抽查）**
- **背景增强:✅ 部分落地**:`core/bg_effects.py`(模糊/马赛克,4K 源先降采样)存在;settings_dialog 有背景区(一次写 7 个 bg_* 键);**视频背景(QMediaPlayer)未见独立实现**,以图片背景+效果为主。
- **主题 UI:✅ 落地并演进**:settings_dialog 现为 6 页设置,主题区由后续批次继续演进;`Assets/Themes` 24 主题、暗/亮分组仍在。
- **性能:✅ 落地**:`directory_cache` 即迁移 v5 表,`core/directory_cache.py`(241 行)+ AssetService 摘要缓存;`/api/files/summaries` 端点存在;4 个 Cython 目标全部编译(.pyd 存在,源码回退保留),加速表见 README。
- **分享 UI/UX:✅ 大体落地**:`widgets/lan_sharing.py` 快速分享入口 + `dialogs/share_link_dialog.py` 浮卡 + `dialogs/sharing_settings_dialog.py`(1374 行外壳:端点/链接/访问/配置 4 页 + 2s 轮询)+ `toast.py` + tray 状态同步 —— 设计全部兑现,后续被 08-21+ 批次深度加工。
> …(余下已省略,考古见归档原件)

**仍生效的约束 / 未决项**
- 目录摘要必须走 `directory_cache` + mtime 校验(不得每次全扫);`?summaries` 语义仍生效。
- Cython 白名单 4 模块仍为唯一编译目标(README 声明的加速契约,`setup_cython.py` 维护)。
- 分享 4 页结构与 2s 轮询、toast 反馈语义仍生效于当前 sharing_settings 外壳。

### 2026-07-13 批：WebUI React 迁移与 LAN 安全修复

- **覆盖**：原 4 份(WebUI React 迁移设计/计划 + LAN 安全修复 + view mode 稳定 id)
- **背景**：- 原 Web 前端是 `AssetsManager/lan/static/` 下的原生 JS 多页应用(MPA)。

**决策要点**
1. **技术栈**:React 18 + TypeScript 5 + Vite 5 + React Router 6 + Tailwind CSS 3 + lucide-react;**明确不选** UI 组件库(shadcn/ui、Ant Design)、状态库(Zustand/Redux)与 React Query/SWR,以原生 fetch + Context + hooks 起步 | design [S2]
2. **项目形态**:新 SPA 置于 `webui/`;构建输出 `webui/dist/`,由后端 `setup_routes()` 注册静态路由;旧 `lan/static/` 的"保留回退"决策**已被后续批次推翻(目录已删)** | design [S1][S11]
3. **路由**:`/`(Landing)、`/browse?path=`、`/detail?path=`、`/login`、`/s/:shareId`,未匹配重定向 `/` | design [S4]、plan Task 4
4. **认证数据流**:启动 `fetch /api/info` 判 `auth_mode` → 免认证直进/进 Login;token 存 AuthContext + sessionStorage;401 清状态跳登录(**后被 cookie-only 模型取代**) | design [S7]、plan Task 2/3
5. **权限模型**(前端侧):admin 全量、user browse/download/preview、guest browse/preview;`AuthContext` 统一维护 | plan Task 3
6. **实时更新**:WS `/ws` 文件变更事件触发当前目录重载,断线退避重连(1s、2s、4s…上限 30s) | design [S7]、plan Task 17
7. **缩略图**:`POST /api/thumbnails/batch` 批量 + 前端 LRU 缓存(容量 200,sessionStorage) | design [S7]、plan Task 8
8. **功能边界**[S9]:核心套(浏览/认证/搜索/下载/详情/菜单/分享/查看器/i18n/响应式/骨架/主题/统计/WS)+ 管理套(用户/邀请码/分享/活动/在线用户)全实现
9. **视觉规范**[S10]:slate-900/slate-50 底、indigo-500 强调、圆角半透明卡片、Inter、transition-all duration-200、骨架脉冲
10. **实施顺序**:18 Task(脚手架→API→认证→路由基础页→i18n→通用 UI→布局→搜索浏览→标签→详情→分享→查看器→管理→响应式→主题→WS→后端集成) | plan Task 1-18
11. **前端工程约束**:全 TS 函数组件、仅 Tailwind utility、文本全走 i18n、API 统一 `client.ts`、类型集中 `types/api.ts`、PascalCase 组件/camelCase hook、认证豁免路径匹配 | plan 全局约束
12. **开发/生产对接**:Vite dev(5173)代理 `/api` `/ws` → 127.0.0.1:8080;生产由 `setup_routes()` 注册 `/assets` 静态 + `/` 返 index.html | plan Task 1/18
13. **LAN 修复范围纪律**:只修已审查问题、不重构 LAN;沿用 `get_user_permissions()`;行为变更必须带回归测试 | lan-security-fixes 全局约束
14. **路由级权限门**:`_helpers.py` 新增 `require_permission()`,在文件列表/下载/缩略图/分享入口调用 | Task 1
> …(余下已省略,考古见归档原件)

**落地状态（2026-08-27 抽查）**
- **webui React 化:✅ 已落地(且超出原计划)**:`react ^18.3.1 / react-router-dom 7.18.2 / tailwind ^3.4.15 / vite 7.3.6`;`webui/dist/` 已构建;`lan/api.py` 注册 `/assets` SPA 静态路由;`lan/static` 已删除;功能扩展到 storefront/seller/gallery、RealtimeContext、queryCache 等(后续批次)。
- **LAN 权限门:✅ 已落地**:`require_permission` 在 `lan/routes/_helpers.py`,被 11 个路由文件使用;`downloads.py` 含 `_estimate_download_size` + `MAX_BATCH_DOWNLOAD_BYTES`(500MB)。
- **view mode 稳定 ID:✅ 已落地**:`panels/file_list/_base_layout.py` L147-148 `userData="Grid"/"Details"`,L329-330 `currentData() or currentText()`(计划书写的 `_base.py` 已拆分为 `_base_layout.py`)。
- 版本约束被取代:React Router 6/Vite 5 → 7.x。

**仍生效的约束 / 未决项**
- LAN 修复三约束仍有效:小范围修复、沿用角色/权限模型、变更带回归测试。
- 前端工程约束(仅 Tailwind、无 UI/状态库、i18n 全覆盖、统一 client.ts)现行仍可观察。
- 视图模式稳定 ID 约定("Grid"/"Details")仍生效。
- 未决:实施计划 Task 18 的 E2E 验证清单未勾选;验证结论以后续批次报告为准。

### 2026-07-15 批：投递安全/文件操作一致/LAN-WebUI 可靠/作用域服务

- **覆盖**：原 10 份(投递安全/文件操作一致/LAN-WebUI 可靠/作用域服务四大批 + anchor worktree)
- **背景**：- 07-15 四大批(投递安全 / 文件操作一致性 / LAN-WebUI 可靠性 / 作用域服务)+ anchor worktree 纪律,构成 Phase 2 的"可连续验证 + 生命周期隔离"主线;batch-b 计划已全部勾选完成,batch-a/c/d 落地报告存在于 compose/reports。

**决策要点**
1. **anchor worktree 纪律**:把已审计工作树固化为可复现 Git 锚点(基线提交 + tag),不删源码与本地产物;`.gitignore` 只扩可复现依赖/生成物/本地工具/Cython 中间产物/cloudflared 二进制;`webui/dist/` 忽略规则保留(Vite 由源码再生) | anchor-worktree 全局约束
2. **Batch A 投递安全**:CI 增加 WebUI lockfile 安装/typecheck/build + Windows 打包冒烟(验 exe/SPA 入口与 assets/翻译/主题/插件/RuntimeData);Vite `/assets/*` 公开(登录页/分享壳引导依赖);浏览器会话凭据=HttpOnly `lan_token` cookie,密码分享用独立作用域 HttpOnly cookie;响应体不给 token(Bearer 仅显式 API client 保留) | batch-a-design [S3-S5]
3. **Batch A 库切换生命周期**:切库=停 LAN → 使缩略图运行时失效 → 关旧会话 → 开新会话;缩略图工作捕获不可变 generation,陈旧完成/缓存/仓库写入一律拒绝 | [S6]
4. **Batch B 文件操作一致性**:`FileOperationService` 是唯一桌面变异边界(绑定 active library root;无作用域服务即拒绝);文件系统变异成功后按序更新 metadata/thumbnails/asset-index 投影再发事件;删除清路径/子树投影;移动/复制对账后代 | batch-b-design [S3-S5]
5. **Batch B Undo 语义**:undo/redo 经操作服务执行、成功后移动历史条目;permanent-delete 备份按实际删除路径提交;trash 不可逆;网格重命名经意图委托;带作用域:库内拖放=移动、外部拖放=复制 | [S5-S6]
6. **Batch C LAN-WebUI 可靠性**:`webui/dist/index.html` 存在即活性页面壳,`lan/static` 仅为回退;先修服务器/公开资源边界,再对齐 share/download 传输与后端响应类型,再稳定 React effect/WS 清理,最后策略/无障碍/最小回退修复;share 密码 cookie 按 share 路径作用域、SameSite=Lax、TTL=分享令牌寿命、与 lan_token 独立;密码分享 info 无 cookie 时返回净化 200(仅密码/过期/预览状态),匹配 cookie 才返回完整公开分享 | lan-webui-reliability [S1-S3]
7. **Batch D 作用域服务**:`LibrarySession` 为新代码唯一公开打开库边界;`ApplicationBootstrap.for_library(session)` 是唯一作用域服务束工厂;MainWindow 在开/切库时注入一次 `set_scoped_services()` 到面板;变异动作无作用域即失败,禁止 `FileOperationService()`/`UndoService()` 无绑定回退;Undo 按库隔离(AB 两库并存互不串);`DatabaseManager.close_library(root)` 显式逐库 teardown,幂等、不关他库 | batch-d-design [S1-S5]

**落地状态（2026-08-27 抽查）**
- **Batch A:✅ 落地**:`webui/dist` 打包进 PyInstaller(`_internal/webui/dist`),`check_package_contents.py` 校验收紧;SPA assets 公开策略在 `lan/api.py`(/assets add_static);cookie-only 认证为现行模型;缩略图 generation 机制在 `panels/file_list/_loader.py`/`_thumbnail_delivery.py`。
- **Batch B:✅ 落地(计划全勾选)**:`FileOperationService` 会话绑定 + 投影修复/清理 + 事件发布顺序符合;undo 经操作服务;集成/桌面回归测试在 tests/integration、tests/desktop。
- **Batch C:✅ 落地**:share 作用域 cookie(`share_token` path=/api/shares/{id}、1h)按设计;`/assets` 公开;SPA-or-503(pages.py);错误契约迁移至 canonical envelope。
- **Batch D:✅ 落地并演进**:`bootstrap.runtime_for`(for_library 已被其后 recalibration 取代为 runtime_for)+ `set_scoped_services` 面板注入;会话租约/`_publish_while_live`/幂等 close 均在 context.py;逐库 teardown 由 `LibraryService.close_session` 编排。
> …(余下已省略,考古见归档原件)

**仍生效的约束 / 未决项**
- "库切换先停 LAN→失效缩略图→关旧→开新"顺序仍是当前 lifecycle coordinator 的硬约定。
- 变异必须带作用域服务(无绑定回退为红线,由 check_boundaries/架构测试守护)。
- share cookie 作用域与 TTL、`/assets` 公开分类仍生效;browser 凭据不进 query/localStorage/sessionStorage。
- 未决:anchor 单基线 tag 未在 git 历史中显式出现(以 mirror bundle 形式留存)。

### 2026-07-17 批：渲染/元数据/主题稳定性 + 早期审计

- **覆盖**：原 7 份(渲染/元数据/主题稳定性五批 + 早期 LAN 错误审计与 P1 审计结论)
- **背景**：- 5 份实现计划(性能/稳定性/渲染)+ 2 份早期审计(结论优先于设计,均判"已安全、无需修复");全部 TDD 式分步,带回归测试。

**决策要点**
1. **LAN 首图单趟线性扫描**:`find_first_image()` 由"收集候选+排序"改为单趟 `os.scandir` 保留最优(不区分大小写最小文件名);空/无图/OSError→None;只认直接子文件且 ∈ IMAGE_EXTS;不改路由/鉴权/调用方 | lan-first-image-linear-scan
2. **metadata 合并读**:新增 `MetadataRepository.get_notes_and_urls()` 一次行内读 notes+urls;URL 解码/畸形→[]/非列表拒绝留在仓库层(共享 `_decode_urls`);`get_metadata()` 为 tag 1 次+合并读 1 次(=2 查询);`get_notes/get_urls` 独立行为不变 | metadata-combined-read
3. **平滑滚动推迟缩略图**:动画驱动(scrollbar by smooth-scroll)的更新不触发防抖,仅"最新动画完成"调度最终防抖(单调 generation);手动滚动保留 100ms 防抖;休眠 legacy QListView 路径不在范围 | smooth-scroll-thumbnail-timing
4. **主题过渡单所有者**:WindowCoordinator 独占窗口级过渡(单调 `_theme_generation`);每次先停活动动画恢复 opacity,仅当前 fade-out 回调可应用主题并启 fade-in;reduce_motion 无动画、同样 apply 路径并恢复 opacity 1.0 | theme-transition-stability
5. **缩放动画轻量重排**:`update_layout(*, relayout_only)` 只重算几何与滚动范围、不动 `_textures/_dirty`;zoom 帧走轻量路径;zoom 完成仍失效纹理+全量布局 | zoom-grid-relayout
6. **audit-LAN 错误响应**:Critical 0/Minor 0/Safe 62;无 str(exc)/traceback/repr 入客户端错误;"User not found" 与 "Invalid password" 为有意 UX 文案(附用户枚举风险注记);validate_path reason 只进状态行不进响应体 | lan-error-audit
7. **audit-P1 LAN DB 线程安全**:写路径全持连接级 `db_write_lock`;to_thread 内只读(WAL);connection_for 恒同连接并校验 root;LAN 不关连接(生命周期归主线程);结论=无需修复(4 条 minor 卫生观察) | p1-audit-findings

**落地状态（2026-08-27 抽查）**
- **渲染/缩放 ✅**:`_grid_widget_data.py:381` `update_layout(..., *, relayout_only)`;`:392-394` `keep_zoom_anchor = bool(self._zoom_source_rects) and not relayout_only`;`_base_events.py:263,279` zoom 帧;`_grid_widget_interact.py:60` 同步签名;后续 git 叠加 zoom 目标尺寸预渲染等(af5d0ca、36436ae)。
- **metadata 合并读 ✅**:`metadata_repository.py:272` `get_notes_and_urls`;`:322` `_decode_urls` 共享;`metadata_service.py:204-213` 走合并读。
- **thumbnail timing ✅**:`_base_events.py:139-146` 100ms 单次防抖 + `_scroll_animation_generation`;`_begin_smooth_scroll`(:410-424)动画驱动短路;`_finish_smooth_scroll`(:426-430)generation 校验后调度防抖。
- **主题 ✅**:`window_coordinator.py:65` `_theme_generation`、`:103 on_theme_refresh()`、`:148` 过期拦截;`window.py:650-651` 委托。
> …(余下已省略,考古见归档原件)

**仍生效的约束 / 未决项**
- 首图选取不依赖枚举顺序、`OSError→None`;URL 解码留在仓库层;防抖 100ms 且动画驱动不触发;WindowCoordinator 独占过渡;`relayout_only` 不动 textures/dirty。
- 未决:用户枚举风险(auth 文案差异)为非阻断独立议题;4 条 minor observations 未列修复;两份审计为时点性结论,归档后以现行代码为准。

### 2026-07-21 架构重定标批：Desktop-LAN-WebUI 分层与运行时

- **覆盖**：原 14 份(分层边界/运行时作用域/事件路由/工作区模型/任务链)
- **背景**：- 原始迁移(0-5 期)建立结构地基(LibraryRuntime 缓存、Runtime 注入 LAN 组合、DTO、SessionPrincipal/capabilities、epoch+revision、WS 硬化、React RealtimeProvider),但 07-21 current-state audit 判定"全绿测试不等于架构收口":生命周期交错、身份转换、投影 producer 缺可执行证据;迁移兼容路径仍留在生产。

**决策要点**
### 分层边界
- **模块化单体**:`ApplicationBootstrap → LibraryRuntime(每个 canonical LibrarySession 恰一个)→ Desktop/LAN/React 适配器`;Desktop 直调应用服务不经本地 HTTP;SQLite/文件系统为权威,WS 只传失效通知 | architecture-design [S2-S4]
- **单一组合边界**:`runtime_for(session)` 是唯一生产 Runtime 组合入口;`for_library()/cleanup_library()` 在 Task D 删除 | [S5]
- **禁路由自组装**:LAN 路由只解析 request/runtime/principal,不得从裸连接构造服务;静态门禁强制 + DTO 不 import Qt、打包清单 | migration Task 8/16
- **显式公共 DTO + golden payload**:Python/TS 用同一 golden 驱动,禁止双端手写 mock 宣称契约正确 | [S6]
- **兼容与回滚**:新旧入口并存最多一阶段并证明等价后立即删除;字段改名优先短期双写,不建长期 /api/v2 | [S11/S12]
### 运行时与服务作用域
- **Runtime 职责**:拥有 session/services/event_router/epoch(每次创建不可预测)/revision(单调)/幂等 close;不吸收 route/Qt/React 逻辑 | [S5]
- **canonical 关闭顺序(硬契约)**:live → mark closed(拒新 lease)→ stop 各 adapter → drain → 清 session-owned cache → 移除缓存所有权 → 关 per-library DB;`session_closing` 为前置边界 | recalibration [S3]
- **失败可观察可重试**:adapter stop 失败保留 actionable handle + failed state,close 不得报"干净关闭";`ShareManager.stop()` 不得把 live server 变 None/stopped | closure [C1]
- **server generation 注册语义**:构造/startup commit 成功后才注册,每次 start 恰好一次;构造失败永不进 lifecycle_adapters;terminal rollback 注销,不完整清理保留供重试 | Task A
### 事件路由与实时
- **每 Runtime 一 Router**:只订阅五类 session-scoped 事件(FileSystemChanged/AssetTagsChanged/TagCatalogChanged/AssetNotesChanged/AssetUrlsChanged);接受条件=token+root+未关闭+映射非空;非法 token/legacy 事件/未知/路径无法归一化 → 整事件静默忽略且不增 revision | event-router-design [S2/S4/S5]
- **InvalidationEvent**:frozen;epoch+revision+domains+paths(相对根 POSIX、去重、禁 ../ 逃逸);不携带连接/凭据 | [S3/S5]
> …(余下已省略,考古见归档原件)

**落地状态（2026-08-27 抽查）**
- `bootstrap.py`:`runtime_for`(owns_live_session + id(session) 缓存 + 单飞);`add_session_closing_listener(_close_runtime)`/`add_session_close_listener(_cleanup_session)`("Runtime cleanup is pending" 重试语义);无 for_library/cleanup_library;`_LanServicesHolder` 单次惰性投影。
- `context.py`:`LibrarySession` 的 `event_token/_begin_close/_finish_close(30s drain)/_publish_while_live/connection_for 异库拒`。
- `runtime_events.py`:ProjectionDomain 14 值(六基础+favorites/shares/users/activity/online_users/shop/orders/quota);EVENT_DOMAINS 覆盖五类原事件+Task C producer;过滤/归一化/逃逸拒绝/subscriber 隔离/drain 2s/三态 close。
- `workspace_bar.py`:WorkspaceBar/WorkspaceSection 为桌面 UI tab 状态,未涉及 Runtime 组合(与 Task D 约束一致)。

**仍生效的约束 / 未决项**
- Windows symlink skip 与发布决策分离,Linux 必须跑(现以 Ubuntu WSL 证据通过)。
- stats 无 producer 序列化 null/Unavailable,禁恒零。
- 永不引入:第二组装路径、持久 revision store、独立后端进程/微服务、Redis/Kafka、React Query、WS 业务对象传输、破坏性 schema migration。
- 产品级未决(路线图):登录页视觉、移动 UX、分享/标签 UX、下载进度、主题;独立后端提取点仅在 NAS/容器/多写场景评估。
- 两份补充实现计划(runtime-adapter-failure-ownership、runtime-event-router-implementation)范围已并入 Task A/Task C,不应再按 checkbox 单独执行。

### 2026-07-21 功能/门禁子批：预览池/信息面板/WebUI 工作区/窗口退出

- **覆盖**：原 19 份(预览池/信息面板/WebUI 工作区/会话关闭/窗口退出/依赖安全)
- **背景**：- 本批是与 07-21 架构重定标并行的功能/门禁子批:预览池与 Gate 首页、滚动与 InfoPanel 预览、WebUI 工作区、会话关闭与窗口退出容错、依赖安全与数据流审计。大量 plan 是"验证先于修改"的门禁型任务(纯回归证明通过时只加测试不改产品)。

**决策要点**
### 预览池与门禁
- 缓存即数据源:预览仅复用 `directory_cache.preview_path`(按 mtime/存在性/根包含校验),不新增扫描管道/图片仓库/新 API | layered-preview-pool-design [S2]
- `/api/thumbnails/{path}` 保持唯一浏览器图片通道 | [S2/S6]
- `/api/home` 项目项可选 `thumbnail_url`,新增 `preview_pool` 字段;recent 20 条上限 | gate-full-library-preview-pool
- Gate 洗牌一次化(Fisher-Yates,主题切换/微调不重排);失败候选降级 lucide 图标,不阻塞导航 | layered-preview-pool
- 共享 `LayeredPreview` 组件(grid/list 尺寸、alt、无自交互);目录缩略图经 `thumbnailMap[path]` | [S4/S5]
- Gate 迁移边界:保留 `/`、cookie 认证、`/login`、`/browse`;删 `/api/config`、`/api/images` 原型 | gate-home-react-migration
- 动效生命周期:图像墙 ≤72 节点、20s 轮转待预载成功、reduced-motion/document hidden 暂停并清理 | [S3]
- `useTheme()` 追加公开 `setTheme`;Gate 特效节点在 body 需内联 `--gate-effect-color` | public-theme-setter / preview-gate [S2]
### 信息面板与滚动
- InfoPanel 预览与列表 `thumbnail_url` 解耦:按 path 推导 `/api/thumbnails/<path>?size=512`,显式 loading/ready/error | infopanel-grid-scroll-boundaries / preview-gate [S1]
- 预览适配不裁剪:object-contain;缩放 25%-500% 相对 fit;Reset/双击/切图回归 fit | infopanel-viewer-image-fit
- 项目预览:`/api/projects/{path}` ProjectDetail + 封面/图片;旧请求 abort+代际守卫 | legacy-infopanel-project-preview
- 滚动边界:header 固定、唯一滚动区 file-list-canvas;ProjectGrid `grid-cols-[repeat(auto-fill,minmax(168px,1fr))]` | filelist-scroll-boundary / infopanel [S2]
> …(余下已省略,考古见归档原件)

**落地状态（2026-08-27 抽查）**
- WebUI:`LayeredPreview.tsx` 存在并被 ProjectCard/ProjectList/LandingPage 引用;`BrowsePage.tsx` 含 browse-workspace/file-list-header/file-list-canvas 结构;`ProjectGrid` 用 auto-fill 168px;InfoPanel 项目预览 + thumbnailUrlFor(path,512/2048);useTheme 返回 {theme,setTheme,toggleTheme};依赖版本与基线一致。
- 后端:project_service 含 `preview_pool`(集成测试覆盖);lan/server、__init__、manager 含 auth_mode 接线;`tests/lan/test_lan_api.py` 有 `test_explicit_none_auth_mode_ignores_active_users`。
- 窗口/生命周期:`window_lifecycle_coordinator.py` switch_library(L118)/shutdown_resources(L276,first_error);window.py closeEvent 嵌套执行;`tests/integration/test_window_lifecycle_lan_failure.py` 两条真实 LAN stop 失败回归。
- 报告产物:compose/reports 下存在 stability-baseline/gate-home-react-migration/webui-dependency-security-upgrade/webui-desktop-dataflow-audit。

**仍生效的约束 / 未决项**
- 全部"不允许"清单:不提交无关脏文件、禁 audit fix --force、不复制 legacy static/app.js、不伪造客户端权限/分享、不加浏览器可读令牌、WS 不用 query 凭据。
- 周闭包前全绿命令集(riff→pyright→compileall→pytest 与 npm ci/typecheck/test/build);被阻塞命令不得声称可发布。
- 未决:weekly 闭包的后续日期报告(07-23/24/26/27)未在 reports 发现,最终发布结论待补验;plan checkbox 大多未勾选(实现归属后续批次,仅以现状为准)。

### 2026-07-24 批：WebUI 遗留清理与文件列表项目交互

- **覆盖**：原 6 份(WebUI 遗留清理 + 文件列表项目交互)
- **背景**：- 07-24 收口两条交互线:Filelist 项目交互语义(桌面单击/双击、is_project 契约)与 WebUI 旧前端清理(删除 lan/static 多页,SPA 唯一入口)。方法:每 plan 声明 REQUIRED SUB-SKILL、checkbox TDD、尾部统一质量门。

**决策要点**
1. **is_project 由后端权威计算**:`/api/files` 目录项暴露 is_project(sidebar_depth_cfg/ProjectDepthConfig);前端禁止按路径深度/文件夹名推断 | filelist spec [S4/S9]
2. **桌面交互矩阵**:单击=选择+InfoPanel(不导航);双击=进入普通目录;项目目录双击=复用 `/detail?path=` 独立页;移动端保留单击直航;批量选择显式模式 | [S2/S5/S10]
3. **键盘**:Enter 触发双击同主动作;Space 选择;保留可见焦点环 | [S5/S8]
4. **Back 语义**:回到进入详情前的精确 `/browse?path=...` URL(含筛选);不建第二详情页 | [S7/S10]
5. **删除 legaay WebUI**:删 `AssetsManager/lan/static/` 全部旧页面 + 静默回退 | webui-legacy-cleanup spec [S5]
6. **SPA-or-503**:页面路由只服务 `webui/dist/index.html`,缺失返回 503 + 构建提示 | [S4]
7. **公开路由分类**:`/static/*` 移出公开与限流跳过列表,`/assets` 保持公开;API/ws/下载/分享协议不变 | [S4/S7]
8. **源码分层保留**:pages/components/api/hooks/stores/types 不做 feature-first 大迁移 | [S3/S9]
9. **测试与打包契约**:测试迁 SPA-or-503 契约;打包检查 `_internal/webui/dist/index.html+assets`;.gitignore 增 `/webui/dist/`、`/webui/.vite/` | [S6]
10. **杂项修复**:Gate 指针光效恢复;thumbnailUrlFor 按段 encode 保留 `/`;工作区开关移 Breadcrumb 行;768px 自动关面板持久化;useTheme 统一外部 store(am_theme 唯一,含旧 key 迁移);Gate 背景设置与主题偏好分离;InfoPanel 预览=button+ImageViewer(高清源 size=2048,不开未鉴权原图端点);图片判定扩到 .bmp/.tiff/.ico/.svg;统一 .asset-preview-surface | 各 plan

**落地状态（2026-08-27 抽查）**
- `webui/dist/index.html` + dist/assets(55 文件)存在;`lan/static/` 已不存在;`lan/routes/pages.py` 含 SPA_DIR/503;`lan/api.py` 仅剩 `/assets` add_static。
- `asset_service.py`/`files.py`/`types/api.ts` 均有 is_project;`BrowsePage.tsx` 含 handleItemOpen/is_project/isMobile(25 处命中)。
- `useTheme.ts` 含 am_theme 与 gate-theme 迁移;`LandingPage.tsx` 含 gate-cursor-glow;`InfoPanel.tsx` 含 asset-preview-surface / size=2048 / ImageViewer。

**仍生效的约束 / 未决项**
- LAN 启动前必须构建 webui/dist,否则 503(设计意图)。
- is_project 只能来自后端;桌面双击约定仅限桌面,移动语义不变。
- 未决:全页面视觉 parity 与真实浏览器/移动验收未闭合;G6-5 数据库完整性 blocker 未收口;文件名含字面 % 的 aiohttp {path:.*} 双重解码风险未修复(08-03 交接仍记)。

### 2026-08-03~04 会话交接摘要(webui-02/desktop-ui-03/mainline-04)

- **覆盖**：原 19 份(三会话交接包:webui-session-02/desktop-ui-session-03/mainline-session-04)

## 取代清单

下列 9 份原件(均 2026-08-27 从 `docs/archive/2026-08/compose-raw/` 合并而来)于 2026-09-02 收敛轮零改写归档至 `docs/archive/2026-09/compose-distilled-superseded/`:

- `2026-06-17-18-architecture-and-theme-system.md`（2026-06-17~18 批：架构重构与主题系统）
- `2026-06-19-21-ux-performance-sharing-webui.md`（2026-06-19~21 批：背景效果/主题 UI/性能/分享/WebUI 视觉）
- `2026-07-13-webui-react-migration.md`（2026-07-13 批：WebUI React 迁移与 LAN 安全修复）
- `2026-07-15-delivery-fileops-reliability-batches.md`（2026-07-15 批：投递安全/文件操作一致/LAN-WebUI 可靠/作用域服务）
- `2026-07-17-rendering-metadata-batch.md`（2026-07-17 批：渲染/元数据/主题稳定性 + 早期审计）
- `2026-07-21-architecture-recalibration.md`（2026-07-21 架构重定标批：Desktop-LAN-WebUI 分层与运行时）
- `2026-07-21-feature-gates-batch.md`（2026-07-21 功能/门禁子批：预览池/信息面板/WebUI 工作区/窗口退出）
- `2026-07-24-webui-cleanup-filelist.md`（2026-07-24 批：WebUI 遗留清理与文件列表项目交互）
- `2026-08-03-04-session-summaries.md`（2026-08-03~04 会话交接摘要(webui-02/desktop-ui-03/mainline-04)）

## 溯源

- 一次蒸馏原件：`docs/archive/2026-08/compose-raw/{specs,plans,handoffs}/`（逐份登记于 `docs/archive/INDEX.md`）
- 现行架构事实：`docs/architecture.md` · 架构决策记录：`docs/adr/`
- 仍生效约束若与现行代码冲突,以 `docs/overview-2026-08-27.md` §实测 与代码为准