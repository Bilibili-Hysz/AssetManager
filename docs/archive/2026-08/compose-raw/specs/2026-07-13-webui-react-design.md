# WebUI React 重构设计规格
> **ARCHIVED (2026-08-27)**: 已执行完毕或被后续批次取代,仅追溯用;导航与现行参考见 docs/compose/README.md。

## [S1] 项目背景

AssetsManager 是一个基于 PySide6 (Qt) 的桌面资产管理器，内置 aiohttp 局域网分享服务器。当前 Web UI 是原生 JS 多页应用（MPA），位于 `AssetsManager/lan/static/` 目录下。本次重构目标是将其替换为现代 React SPA，置于 `webui/` 目录，与现有项目集成。

## [S2] 技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| React | 18.x | UI 框架 |
| TypeScript | 5.x | 类型安全 |
| Vite | 5.x | 构建工具 |
| React Router | 6.x | 前端路由 |
| Tailwind CSS | 3.x | 样式（原子化 CSS） |
| lucide-react | 最新 | 图标库 |

显式不选择的：
- 不使用 UI 组件库（如 shadcn/ui、Ant Design），保持视觉自由度和轻量化
- 不使用状态管理库（如 Zustand、Redux），React Context + hooks 足够
- 不引入 React Query/SWR，初期用原生 fetch + 自定义 hooks，后续按需引入

## [S3] 项目结构

```
webui/
├── index.html              # Vite 入口 HTML
├── package.json
├── tsconfig.json
├── vite.config.ts
├── tailwind.config.ts
├── postcss.config.js
├── src/
│   ├── main.tsx            # 应用入口
│   ├── App.tsx             # 路由根组件
│   ├── index.css           # Tailwind 基础样式 + 全局样式
│   │
│   ├── api/                # API 层
│   │   ├── client.ts       # fetch 封装，认证头管理
│   │   ├── auth.ts         # 认证 API
│   │   ├── files.ts        # 文件/项目 API
│   │   ├── tags.ts         # 标签 API
│   │   ├── shares.ts       # 分享 API
│   │   └── thumbnails.ts   # 缩略图 API
│   │
│   ├── hooks/              # 自定义 hooks
│   │   ├── useAuth.ts      # 认证状态管理
│   │   ├── useProjects.ts  # 项目列表获取
│   │   ├── useSearch.ts    # 搜索（防抖）
│   │   ├── useWebSocket.ts # WebSocket 连接
│   │   └── useThumbnailCache.ts  # 缩略图 LRU 缓存
│   │
│   ├── components/         # UI 组件
│   │   ├── layout/         # 布局组件
│   │   │   ├── AppLayout.tsx     # 三栏布局容器
│   │   │   ├── Header.tsx        # 顶栏
│   │   │   ├── Sidebar.tsx       # 侧边栏（目录树）
│   │   │   ├── InfoPanel.tsx     # 信息面板
│   │   │   └── ResizablePanel.tsx # 可拖拽面板
│   │   ├── files/          # 文件浏览
│   │   │   ├── ProjectGrid.tsx   # 网格视图
│   │   │   ├── ProjectList.tsx   # 列表视图
│   │   │   ├── ProjectCard.tsx   # 项目卡片
│   │   │   ├── Breadcrumb.tsx    # 面包屑导航
│   │   │   └── FileToolbar.tsx   # 工具栏
│   │   ├── auth/           # 认证
│   │   │   ├── LoginForm.tsx
│   │   │   └── RegisterForm.tsx
│   │   ├── shares/         # 分享
│   │   │   ├── ShareDialog.tsx
│   │   │   └── SharePage.tsx
│   │   ├── viewer/         # 图片查看器
│   │   │   └── ImageViewer.tsx
│   │   ├── tags/           # 标签
│   │   │   └── TagChip.tsx
│   │   └── ui/             # 通用 UI
│   │       ├── Toast.tsx
│   │       ├── ContextMenu.tsx
│   │       ├── Skeleton.tsx
│   │       └── Modal.tsx
│   │
│   ├── pages/              # 页面
│   │   ├── LandingPage.tsx     # 欢迎页
│   │   ├── BrowsePage.tsx      # 主浏览页
│   │   ├── DetailPage.tsx      # 项目详情页
│   │   ├── ShareReceivePage.tsx # 分享接收页
│   │   └── LoginPage.tsx       # 登录页
│   │
│   ├── stores/             # 状态管理
│   │   └── AuthContext.tsx # 认证上下文
│   │
│   ├── types/              # TypeScript 类型
│   │   └── api.ts          # API 响应类型定义
│   │
│   └── i18n/               # 国际化
│       ├── index.ts
│       ├── en.ts
│       ├── zh.ts
│       └── ja.ts
```

## [S4] 路由设计

| 路径 | 页面组件 | 说明 |
|------|---------|------|
| `/` | LandingPage | 欢迎页，显示服务器信息、进入按钮 |
| `/browse` | BrowsePage | 主浏览页，`?path=` 参数指定路径 |
| `/detail` | DetailPage | 项目详情，`?path=` 参数 |
| `/login` | LoginPage | 登录/注册 |
| `/s/:shareId` | ShareReceivePage | 分享链接接收页 |

## [S5] 布局设计

### 桌面端三栏布局

```
┌──────────────────────────────────────────────────────────┐
│  Header:  Logo | 搜索栏(request) | 用户菜单 | 语言切换    │
├───────┬──────────────────────────────┬───────────────────┤
│       │                              │                   │
│ Side  │  Main Content                │  Info Panel       │
│ bar   │  (网格/列表视图)              │  (元数据/标签/    │
│ (目   │  + 工具栏 + 面包屑)           │   备注/URL)       │
│ 录树) │                              │                   │
│       │                              │                   │
├───────┴──────────────────────────────┴───────────────────┤
│  Footer: 连接状态 / 文件统计                              │
└──────────────────────────────────────────────────────────┘
```

### 移动端布局

- 侧边栏改为滑出式 overlay（带遮罩层）
- 信息面板改为底部滑出式
- 底部固定操作栏（目录/视图切换/选择模式）
- 搜索栏折叠为图标按钮

### 响应式断点

- `lg (1024px)`：三栏布局 ↔ 两栏布局
- `md (768px)`：两栏布局 ↔ 单栏移动端布局

## [S6] 组件树

```
App
├── AuthProvider (Context)
└── Router
    ├── LandingPage
    ├── LoginPage
    │   ├── LoginForm
    │   └── RegisterForm
    ├── BrowsePage
    │   └── AppLayout
    │       ├── Header
    │       │   ├── Logo
    │       │   ├── SearchBar (带防抖)
    │       │   ├── UserMenu
    │       │   └── LanguageSwitcher
    │       ├── Sidebar
    │       │   ├── DirectoryTree (可展开/折叠)
    │       │   └── Shortcuts (收藏/最近)
    │       ├── MainContent
    │       │   ├── Breadcrumb
    │       │   ├── FileToolbar
    │       │   │   ├── SortSelector
    │       │   │   ├── ViewToggle (网格/列表)
    │       │   │   └── BatchActions
    │       │   ├── ViewContainer
    │       │   │   ├── ProjectGrid
    │       │   │   │   └── ProjectCard[]
    │       │   │   └── ProjectList
    │       │   │       └── ProjectRow[]
    │       │   └── Skeleton (加载态)
    │       ├── InfoPanel
    │       │   ├── MetadataSection
    │       │   ├── TagSection
    │       │   ├── NotesSection
    │       │   └── UrlSection
    │       └── ResizablePanel (拖拽手柄)
    ├── DetailPage
    │   ├── ProjectHero (缩略图/标题/操作)
    │   ├── FileGallery
    │   └── FileList
    └── ShareReceivePage
        ├── ShareInfo
        ├── PasswordGate (如果需密码)
        └── FilePreview
```

## [S7] API 数据流

### 认证流程

```
1. 应用启动 → fetch /api/info → 获取 auth_mode
2. 无需认证 → 直接进入 LandingPage
3. 需要认证 → 显示 LoginPage
4. 登录成功 → token 存入 AuthContext + sessionStorage
5. 后续请求 → API client 自动附加 Authorization header
6. 401 响应 → AuthContext 清空，跳转 LoginPage
```

### 文件浏览流程

```
用户点击目录 / 搜索
    → useProjects hook 更新参数
    → fetch /api/projects?path=xxx&sort=yyy
    → 更新 state → 渲染 ProjectGrid / ProjectList
    → 并发加载缩略图 (POST /api/thumbnails/batch)
```

### 实时更新

```
WebSocket 连接 (/ws)
    → 接收文件变更事件
    → 触发当前目录重新加载
    → 连接断开时指数退避重连 (1s, 2s, 4s, ... max 30s)
```

## [S8] 状态管理

### 认证状态 (AuthContext)

```typescript
interface AuthState {
  token: string | null;
  user: User | null;
  role: 'admin' | 'user' | 'guest' | null;
  permissions: string[];
  isAuthenticated: boolean;
  authMode: 'none' | 'key' | 'password' | 'user';
}
```

### 浏览状态 (hooks)

```typescript
// useProjects hook
interface UseProjectsReturn {
  projects: Project[];
  currentPath: string;
  parentPath: string | null;
  isLoading: boolean;
  error: Error | null;
  navigateTo: (path: string) => void;
  sort: SortConfig;
  setSort: (config: SortConfig) => void;
}

// useSearch hook
interface UseSearchReturn {
  query: string;
  results: SearchResult[];
  isSearching: boolean;
  setQuery: (q: string) => void;  // 带 200ms 防抖
}
```

## [S9] 功能清单

### 核心功能（必须实现）

- [x] Landing 欢迎页（显示服务器信息、进入按钮）
- [x] 认证系统（登录、注册、密钥验证、登出、访客模式）
- [x] 文件浏览（网格/列表视图，路径导航，面包屑，排序）
- [x] 目录树（展开/折叠，搜索过滤）
- [x] 信息面板（元数据、标签、备注、URL）
- [x] 缩略图加载（批量加载 + LRU 缓存）
- [x] 搜索（文件名/标签，防抖）
- [x] 文件下载（单文件 + 批量 ZIP）
- [x] 项目详情页（文件列表、图片画廊）
- [x] 右键菜单（打开/下载/分享/复制路径）
- [x] 分享链接创建（密码/有效期/限次/预览开关）
- [x] 分享链接接收页（密码验证、文件预览/下载）
- [x] 图片查看器（全屏、缩放、平移、方向键导航）
- [x] 国际化（中/英/日）
- [x] 响应式布局（桌面 + 移动端）
- [x] 骨架屏加载态
- [x] 深色/浅色主题切换
- [x] 统计信息显示（连接数、请求数、传输量）
- [x] WebSocket 实时更新

### 管理功能（需管理员权限）

- [x] 用户管理（列表、启用/禁用）
- [x] 邀请码管理（生成、撤销）
- [x] 分享链接管理（列表、删除）
- [x] 活动日志
- [x] 在线用户

## [S10] 视觉风格

- **主色调**：slate-900 (#0f172a) 深蓝灰背景，slate-50 (#f8fafc) 亮色背景
- **强调色**：indigo-500 (#6366f1)
- **文字层级**：white → gray-300 → gray-500（暗色）；gray-900 → gray-600 → gray-400（亮色）
- **卡片**：圆角 (rounded-lg)，半透明背景 (bg-white/5)，轻微边框
- **动效**：transition-all duration-200，hover:scale-[1.02]，loading skeleton 脉冲动画
- **字体**：Inter（与现有风格一致）

## [S11] 与后端的集成

- 开发时：Vite dev server 代理 `/api`、`/ws`、`/static` 到后端（`vite.config.ts` 中配置 proxy）
- 生产时：Vite 构建输出到 `dist/`，后端 `server.py` 的 `setup_routes()` 中注册静态文件路由指向 `webui/dist/`，替换原有的 `lan/static/` 路由
- 新 WebUI 完成后，旧 `lan/static/` 保留作为回退

## [S12] 实施顺序

1. 项目脚手架（Vite + React + TS + Tailwind + Router）
2. API 层（client.ts + 各模块 API）
3. 认证系统（AuthContext + LoginPage + LoginForm）
4. 布局框架（AppLayout + Header + Sidebar + InfoPanel + ResizablePanel）
5. 文件浏览（BrowsePage + ProjectGrid/List + ProjectCard + Breadcrumb + FileToolbar）
6. 搜索（useSearch hook + 搜索 UI）
7. 标签系统（TagChip + 标签 CRUD 集成）
8. 缩略图（useThumbnailCache + 批量加载）
9. 项目详情页（DetailPage + 文件列表 + 图片画廊）
10. 分享系统（ShareDialog + ShareReceivePage）
11. 图片查看器（ImageViewer）
12. 管理功能（用户管理 + 邀请码 + 分享管理 + 活动日志）
13. 国际化（i18n 模块 + 翻译文件）
14. 响应式适配（移动端布局）
15. 深色/浅色主题切换
16. WebSocket 实时更新
17. 右键菜单 + Toast + 骨架屏
18. 开发代理配置 + 生产构建集成
