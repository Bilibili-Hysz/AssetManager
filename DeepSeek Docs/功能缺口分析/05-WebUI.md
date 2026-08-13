# 05 · WebUI 功能缺口

覆盖：`webui/src/*`

## G5-1 无编辑能力（备注/标签/URL）[P1][M]

- **现状**：`components/layout/InfoPanel.tsx` 只读展示（GET /api/meta）；无 PUT/POST meta 端点调用；标签写接口存在但 admin-only（tags.py:41-70），且 WebUI 无编辑 UI
- **缺口**：移动端无法"随手记一条备注/加标签"
- **实现路径**：① 后端：`PUT /api/meta/{path}`（notes/urls）+ `POST/DELETE /api/tags/{name}/files` 对注册用户开放（配合 G4-2 权限）② 前端：InfoPanel 编辑态 + 保存（M）

## G5-2 无上传组件 [P1][L]

- **现状**：无任何上传 UI；能力模型有 upload（见 G4-1）
- **实现路径**：与 G4-1 同批交付：BrowsePage 拖放上传（目标=当前目录）+ 上传进度列表（复用 `DownloadProgress.tsx` 反向实现）（L）

## G5-3 无批量选择/批量下载 [P2][M]

- **现状**：ProjectGrid/ProjectList 单文件交互；FileToolbar 有排序/刷新但无"全选/多选"；批量下载走 `/api/download/batch`（端点存在，前端无入口——需确认后补 UI）
- **实现路径**：项目卡片 checkbox 选择模式 → 底部操作栏（批量下载/（未来）批量打标签）（M）

## G5-4 大目录无虚拟滚动 [P2][L]

- **现状**：`ProjectGrid` 全量渲染 items；`/api/files` 单次返回全部（无分页参数，与 `/api/projects` 的分页 offset/limit 不同）；万级文件目录 DOM 爆炸
- **实现路径**：① 前端虚拟滚动（react-window 或自研窗口化，L）② 后端 files 端点补 offset/limit（S）

## G5-5 无搜索历史/快捷筛选 [P2][S]

- **现状**：搜索框每次手输；无最近搜索、无"最近浏览目录"面包屑记忆
- **实现路径**：localStorage 搜索历史 + 下拉建议（S）

## G5-6 无亮/暗模式切换 [P2][M]

- **现状**：`lan_theme_color` 单色（system.py handle_info）供主题色 accent 用；前端样式（index.css/tailwind）以暗色为主；DESIGN.md 提到浏览器存储 theme 偏好但仅限 Gate 页背景
- **实现路径**：CSS 变量化 + 设置持久化（localStorage + 后端设置可选同步）（M）

## G5-7 错误反馈静默 [P1][S]

- **现状**：`api/client.ts` fetch 失败/非 2xx 仅 console/部分组件 Toast；导航到不可用库（503 SPA 缺失）显示空白页；认证过期（401）无统一跳转登录
- **实现路径**：client.ts 统一错误分类 → 401 跳 /login、503 显示"服务未构建"页、网络错误全局 Toast（S）

> **已处理（2026-08-15 核实）**：`api/errors.ts` 已有 `ApiError/UnauthorizedError(401)/ForbiddenError(403)/ServiceUnavailableError(503)/NetworkError`；`api/client.ts` 已统一分类 401/403/429/503 + 网络错误；`AuthContext`/`SellerAuthContext` 经 `onUnauthorized` 跳转登录、`serviceUnavailable` 状态；`LandingPage` 渲染 `service_unavailable` 页；`ProtectedRoute` 未认证 `<Navigate to="/login">`。此缺口已随 `f2dc8b7`/`51e5020`/`a315868` 关闭，文档标注仅做状态同步。

## G5-8 无分享创建与管理的前端闭环 [P2][M]

- **现状**：`components/shares/ShareDialog.tsx` 存在（管理列表）；创建分享依赖桌面端对话框（ShareLinkDialog）；无 QR 显示
- **实现路径**：ShareDialog 增加"新建分享"表单（paths/密码/限时/限次）+ QR 码渲染（后端 `/api/shares` POST 已就绪，纯前端工作，M）

## G5-9 测试覆盖缺口 [P2][M]

- **现状**：组件测试密度高（每组件 .test.tsx），但：无端到端（浏览器 × 真实服务器）测试、无 API 契约的运行时校验（public-contracts 是静态快照）、无 WebSocket 消息的集成测试
- **实现路径**：vitest 环境 mock WebSocket 消息驱动组件更新（M）；Playwright 冒烟（可选，L）
