# 08 · WebUI、插件系统、i18n 与测试

## 1. WebUI（React 前端，`webui/`）

### 技术栈
React 18.3 + TypeScript 5.6 + Vite 7 + Tailwind 3.4 + react-router-dom 7 + vitest 3 + Testing Library。

### 路由（App.tsx:14-27）
```
/            LandingPage（Gate 首页：模糊缩略图墙 + 进入库）
/login       LoginPage
/browse      BrowsePage（项目网格/列表 + 侧边栏 + 信息面板）
/detail      DetailPage（项目详情：文件清单 + 图片画廊）
/s/:shareId  ShareReceivePage（分享接收页）
*            → / 重定向
```

### 分层结构
```
src/
├── api/           # 后端 API 客户端（client.ts + 领域模块）
│   ├── client.ts  # fetch 封装（HttpOnly Cookie、错误处理）
│   ├── auth.ts / files.ts / metadata.ts / shares.ts / system.ts
│   ├── tags.ts / thumbnails.ts / users.ts
│   └── *.test.ts  # 含 public-contracts.test.ts（公开契约测试）
├── components/
│   ├── layout/    # AppLayout / Header / Sidebar / StatusBar / ResizablePanel / InfoPanel
│   ├── files/     # ProjectGrid / ProjectList / ProjectCard / Breadcrumb / FileToolbar / LayeredPreview
│   ├── admin/     # UserManagement / InviteManagement / ShareManagement / OnlineUsers / ActivityLog
│   ├── shares/    # ShareDialog
│   ├── tags/      # TagChip
│   ├── viewer/    # ImageViewer
│   └── ui/        # Modal / Toast / Skeleton / ContextMenu / DownloadProgress
└── App.tsx / main.tsx / index.css
```

### 与后端数据流
- API 客户端直连后端 REST（同源部署：aiohttp 服务 SPA 静态文件 + `/api/*`）
- 认证：浏览器使用 `lan_token` HttpOnly Cookie；React 不保存或注入 bearer token，Bearer 仅保留给受控非浏览器客户端
- **实时更新**：WebSocket `/ws` 接收 `projection_invalidated`（epoch/revision/domains/paths）→ 前端按 domains 失效缓存并重取；`/api/revision` 提供轮询游标（旧浏览器回退）
- 缩略图：`/api/thumbnails/{path}?size=`；批量 base64 接口用于网格
- 契约测试：`public-contracts.test.ts` 验证前端 DTO 与 `lan/dto.py` 保持一致（防前后端契约漂移）

### Gate 首页设计约束（DESIGN.md）
- 唯一数据源 `/api/info` + `/api/home` + `thumbnail_url`
- 反模式清单：不加功能卡片网格/第二 CTA/外部图片/假指标/无限动画 DOM

## 2. 插件系统

### 插件生命周期（core/plugins/manager.py）
```
discover_plugins() → PluginDescriptor 列表（扫描 plugin.json）
enable_plugin(id)  → 记录启用状态（Shared/plugins 状态文件）
load_plugin(id, host) → importlib 导入 entry 模块 → 调用 register(host)
disable_plugin(id) → 先 unload（调用 unregister）再禁用
```

### 插件清单（plugin.json）
`id / name / version / entry / permissions`（权限为**建议性**，不强制执行——README 明示插件运行在完整 Python 解释器中）。

### 宿主能力（host_context.py，8 种贡献）
| 贡献 | 用途 |
|---|---|
| `CommandContribution` | 全局命令（工具菜单执行） |
| `MenuContribution` | 菜单项（如 tools 菜单） |
| `ToolWindowContribution` | 工具窗口 |
| `FileHandlerContribution` | 文件处理器 |
| `ContextMenuContribution` | 文件右键菜单（`_actions.py:102` 注入面板） |
| `CategoryContribution` | 自定义分类 |
| `ColumnContribution` | 详情视图列 |
| `SearchProviderContribution` | 搜索提供者 |
| `ThemeTokenContribution` | 主题 token |

### 内置插件（Plugins/Addons/）
- `booth_link`：Booth.pm 链接解析 → 写入 `plugin_metadata`（InfoPanel 显示作者/条目名等）
- `download_tracker`：下载追踪

插件元数据落库（`plugin_metadata` 表）→ 插件禁用后信息面板仍可显示——持久化设计良好。

## 3. 国际化 `i18n/`

- `init()`：读 AppSettings `language` → 加载 `en.json / zh.json / ja.json`
- `tr(key, **kwargs)`：点路径查找 + 参数替换 + 缺失回退 key 本身
- `set_language`：切换后 `AppSettings` 持久化 + 发 `signal_bus.language_changed`
- Web 端独立 i18n：`webui/src/api/i18n.js` + `lan/static/i18n/*.json`（旧静态 UI 遗留）——**新旧两套 Web i18n 并存**（旧静态 UI 已被 React 替换，仅遗留文件）

## 4. 测试体系（tests/，229 个测试文件；当前 Python 全量 3462 passed, 7 skipped；WebUI 单测 103 files / 683 tests；浏览器 E2E 48 passed, 2 skipped 含 axe 门禁）

| 目录 | 覆盖 | 说明 |
|---|---|---|
| `core/` | 数据库、迁移、设置、主题、缓存、锁 | DatabaseManager 并发/关闭协调 |
| `unit/` | 领域对象、控制器、过滤器、事件、服务 | 无 Qt 依赖的纯逻辑 |
| `integration/` | 服务层 + Repository + 库生命周期 | 真实 SQLite |
| `desktop/` | PySide6 offscreen 面板/窗口 | QT_QPA_PLATFORM=offscreen |
| `panels/` | 文件列表/侧边栏/信息面板行为 | 含网格缩放插值测试 |
| `lan/` | API 安全、路径防护、服务器生命周期、WebSocket | aiohttp test_client |
| `contracts/` | LAN 公开契约 JSON（lan_public_contracts.json） | 双端契约基准 |
| `perf/` + `performance/` | 目录列表/搜索/缓存基准 + Cython 基准 | — |
| `e2e/` | 端到端少量用例 | — |

### fixture（conftest.py）
`temp_dir` / `memory_db` / `schema_db` / `_cleanup_stores`（autouse，每测试后关连接+清事件总线）/ `_ensure_qapp`。

## 5. 数据流要点

```
React 组件 → api/*.ts（fetch + token）→ aiohttp route → application service → SQLite
WebSocket 收到 projection_invalidated → 组件缓存失效 → 重新 GET 受影响域
插件 register(host) → 贡献注册 → 菜单/右键/命令注入 → 执行时调插件逻辑 → 可选写 plugin_metadata
```

## 6. 观察

- WebUI 已完全取代旧静态 UI（`lan/static/` 遗留但路由已指向 `webui/dist`，pages.py:14）
- 契约测试是双端协作的亮点；`tests/contracts/lan_public_contracts.json` 是公开契约快照
- 前端测试密度高（几乎每个组件有 .test.tsx），后端 LAN 测试侧重安全而非覆盖率
