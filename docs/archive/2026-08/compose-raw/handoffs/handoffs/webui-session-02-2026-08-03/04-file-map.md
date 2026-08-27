# 04 — WebUI 文件地图

路径均相对于仓库根目录 `D:/~Vibe-Coding/Projects/AssetsManager_old-bak`。

## 1. 入口与路由

| 文件 | 责任 |
|---|---|
| [`webui/src/main.tsx`](../../../../webui/src/main.tsx) | React 挂载入口、全局样式加载 |
| [`webui/src/App.tsx`](../../../../webui/src/App.tsx) | Router、Provider、页面路由组合 |
| [`webui/src/index.css`](../../../../webui/src/index.css) | 全局主题、基础布局和样式 |
| [`webui/src/pages/LandingPage.tsx`](../../../../webui/src/pages/LandingPage.tsx) | Gate 首页、预览墙、主题/背景调节 |
| [`webui/src/pages/LoginPage.tsx`](../../../../webui/src/pages/LoginPage.tsx) | 用户名密码、access key、注册、邀请登录 |
| [`webui/src/pages/BrowsePage.tsx`](../../../../webui/src/pages/BrowsePage.tsx) | 主要文件管理业务页面 |
| [`webui/src/pages/DetailPage.tsx`](../../../../webui/src/pages/DetailPage.tsx) | 项目详情、画廊、ImageViewer |
| [`webui/src/pages/ShareReceivePage.tsx`](../../../../webui/src/pages/ShareReceivePage.tsx) | 公开分享接收与 share token 流程 |
| [`webui/src/pages/LandingPage.css`](../../../../webui/src/pages/LandingPage.css) | Gate 专属样式 |

## 2. 状态、hooks 和实时

| 文件 | 责任 |
|---|---|
| [`webui/src/stores/AuthContext.tsx`](../../../../webui/src/stores/AuthContext.tsx) | server info、principal、capabilities、身份世代、cookie session |
| [`webui/src/stores/RealtimeContext.tsx`](../../../../webui/src/stores/RealtimeContext.tsx) | cursor、domain invalidation、gap/epoch recovery |
| [`webui/src/hooks/useAuth.ts`](../../../../webui/src/hooks/useAuth.ts) | AuthContext 便捷访问 |
| [`webui/src/hooks/useWebSocket.ts`](../../../../webui/src/hooks/useWebSocket.ts) | WebSocket transport、重连、fan-out |
| [`webui/src/hooks/useInvalidation.ts`](../../../../webui/src/hooks/useInvalidation.ts) | domain 订阅封装 |
| [`webui/src/hooks/useProjects.ts`](../../../../webui/src/hooks/useProjects.ts) | 文件列表、目录导航、排序、refresh、目录 hydration |
| [`webui/src/hooks/useSearch.ts`](../../../../webui/src/hooks/useSearch.ts) | 防抖搜索、generation、防旧结果覆盖 |
| [`webui/src/hooks/useThumbnailCache.ts`](../../../../webui/src/hooks/useThumbnailCache.ts) | sessionStorage cache、批量缩略图、淘汰与恢复 |
| [`webui/src/hooks/useTheme.ts`](../../../../webui/src/hooks/useTheme.ts) | theme/localStorage/旧 key 迁移 |
| [`webui/src/hooks/useMediaQuery.ts`](../../../../webui/src/hooks/useMediaQuery.ts) | 响应式 viewport 判断 |
| [`webui/src/hooks/useDialogFocus.ts`](../../../../webui/src/hooks/useDialogFocus.ts) | 对话框焦点陷阱和回收 |

## 3. API 与类型

| 文件 | 责任 |
|---|---|
| [`webui/src/api/client.ts`](../../../../webui/src/api/client.ts) | 统一 fetch、cookie、错误、Blob、进度、AbortSignal |
| [`webui/src/api/auth.ts`](../../../../webui/src/api/auth.ts) | 登录、注册、key、logout、me |
| [`webui/src/api/files.ts`](../../../../webui/src/api/files.ts) | 文件列表、目录摘要、单/批量下载 |
| [`webui/src/api/metadata.ts`](../../../../webui/src/api/metadata.ts) | project detail、meta、search、tree、home |
| [`webui/src/api/shares.ts`](../../../../webui/src/api/shares.ts) | 创建/列表/删除分享、info、密码验证、URL |
| [`webui/src/api/tags.ts`](../../../../webui/src/api/tags.ts) | 标签 list/add/rename/delete |
| [`webui/src/api/thumbnails.ts`](../../../../webui/src/api/thumbnails.ts) | 批量缩略图 |
| [`webui/src/api/system.ts`](../../../../webui/src/api/system.ts) | info、stats、tunnel status |
| [`webui/src/api/users.ts`](../../../../webui/src/api/users.ts) | 用户、邀请码、活动、在线用户 |
| [`webui/src/types/api.ts`](../../../../webui/src/types/api.ts) | 公共 DTO、principal、capabilities、files、shares、admin 类型 |

## 4. 业务组件

### 文件与浏览

目录：[`webui/src/components/files/`](../../../../webui/src/components/files/)

- `Breadcrumb.tsx`：路径、侧栏和 InfoPanel 控件。
- `FileToolbar.tsx`：grid/list、排序、标签过滤、选择、批量下载入口。
- `ProjectCard.tsx`：卡片展示、单击/双击、键盘、选择。
- `ProjectGrid.tsx`：网格容器与目录/文件行为。
- `ProjectList.tsx`：列表容器、表头、操作。
- `LayeredPreview.tsx`：目录封面与多层预览。

### 布局

目录：[`webui/src/components/layout/`](../../../../webui/src/components/layout/)

`AppLayout`、`Header`、`Sidebar`、`InfoPanel`、`StatusBar`、`ResizablePanel`。

### 分享、认证、查看器、UI

- [`webui/src/components/shares/ShareDialog.tsx`](../../../../webui/src/components/shares/ShareDialog.tsx)：创建分享对话框。
- [`webui/src/components/auth/ProtectedRoute.tsx`](../../../../webui/src/components/auth/ProtectedRoute.tsx)：前端 capability gate。
- [`webui/src/components/viewer/ImageViewer.tsx`](../../../../webui/src/components/viewer/ImageViewer.tsx)：全屏图片浏览、缩放、拖拽、键盘。
- [`webui/src/components/tags/TagChip.tsx`](../../../../webui/src/components/tags/TagChip.tsx)：标签 chip。
- [`webui/src/components/ui/`](../../../../webui/src/components/ui/)：ContextMenu、Modal、Skeleton、Toast、DownloadProgress。

### 管理

目录：[`webui/src/components/admin/`](../../../../webui/src/components/admin/)

`ActivityLog`、`AdminManagement`、`InviteManagement`、`OnlineUsers`、`ShareManagement`、`UserManagement`。

## 5. 测试地图

- 页面：`webui/src/pages/*.test.tsx`，Browse/Landing 覆盖最完整，ShareReceive 缺同名测试。
- contexts：`AuthContext.test.tsx`、`RealtimeContext.test.tsx`。
- hooks：`useProjects`、`useSearch`、`useTheme`、`useThumbnailCache`、`useWebSocket` 有直接测试。
- 组件：文件 grid/list、布局、admin、viewer、ProtectedRoute 有较强覆盖。
- API：`client.test.ts`、`files-shares.contract.test.ts`、`public-contracts.test.ts`、`contracts.test.ts`；大部分 API 工厂还需独立方法合约测试。
- Python/Chromium：[`tests/e2e/test_webui_realtime_acceptance.py`](../../../../tests/e2e/test_webui_realtime_acceptance.py)、[`tests/lan/test_runtime_realtime.py`](../../../../tests/lan/test_runtime_realtime.py)。

## 6. 后端对应入口

| 文件 | 责任 |
|---|---|
| [`AssetsManager/lan/api.py`](../../../../AssetsManager/lan/api.py) | HTTP/WS route 注册、Runtime realtime bridge |
| [`AssetsManager/lan/server.py`](../../../../AssetsManager/lan/server.py) | aiohttp app、auth middleware、公开路径、生命周期 |
| [`AssetsManager/lan/routes/_helpers.py`](../../../../AssetsManager/lan/routes/_helpers.py) | principal、permission、path validation、share token helpers |
| `AssetsManager/lan/routes/auth.py` | 登录、注册、key、logout、me |
| `AssetsManager/lan/routes/files.py` | 文件列表、目录摘要 |
| `AssetsManager/lan/routes/downloads.py` | 单文件/目录/批量下载 |
| `AssetsManager/lan/routes/metadata.py` | meta、search、home、tree、projects |
| `AssetsManager/lan/routes/tags.py` | 标签读写 |
| `AssetsManager/lan/routes/thumbnails.py` | 单个/批量缩略图 |
| `AssetsManager/lan/routes/shares.py` | 分享创建、验证、info、preview、download |
| `AssetsManager/lan/routes/users.py` | 用户、邀请、活动、在线用户 |
| `AssetsManager/lan/routes/system.py` | info、revision、stats、tunnel status |
| `AssetsManager/lan/routes/websocket.py` | `/ws` admission、cursor barrier、authority lease |
| [`AssetsManager/lan/dto.py`](../../../../AssetsManager/lan/dto.py) | 公共响应 DTO |
