# 01 — 当前状态与证据边界

## 1. 盘点快照

| 项目 | 当前值 |
|---|---|
| 盘点日期 | 2026-08-03 |
| 代码审查基线 | `de64492` |
| 上一轮交接提交 | `b9dca9d` |
| HEAD 主题 | `docs: record G6-5 integrity check slice` |
| WebUI 运行时 | React 18.3.1、React Router DOM 7.18.2、Vite 7.3.6 |
| TypeScript / Vitest | TypeScript 5.6.3、Vitest 3.2.6 |
| Node 要求 | `^20.19.0 || >=22.12.0` |
| 当前前端测试 | 37 个测试文件、292 个测试通过 |
| 当前类型检查 | `npm --prefix webui run typecheck` 通过 |
| 当前构建 | `npm --prefix webui run build` 通过，1632 modules transformed |
| 外置 Git 工作树 | 干净 |

以上测试、类型检查和构建数字来自 2026-08-03 在本工作树执行的命令；历史报告中的数字仅作为历史证据，不替代本快照。

## 2. 已交付的 WebUI 能力

### 应用骨架

- `BrowserRouter`、`AuthProvider`、`RealtimeProvider`、Toast 和下载进度 Provider 已组合在 [`webui/src/App.tsx`](../../../../webui/src/App.tsx)。
- 当前路由为 `/`、`/login`、受保护的 `/browse` 与 `/detail`、公开分享 `/s/:shareId`，未知路由重定向到 `/`。
- `/browse` 和 `/detail` 通过 `ProtectedRoute capability="browse"` 保护；分享接收页面不走普通浏览保护链。

### 认证与身份

- [`AuthContext.tsx`](../../../../webui/src/stores/AuthContext.tsx) 启动时请求 `/api/info`，认证开启时通过 `/api/auth/me` 恢复 session。
- 请求统一使用 `credentials: 'same-origin'`；HttpOnly cookie 对 JavaScript 不可见，但浏览器会自动携带。
- `SessionPrincipal`、`Capabilities`、`identityGeneration` 已进入前端状态；401 会清理身份并触发重新进入 guest 状态。
- 登录、access key、注册、邀请注册、登出和 `/auth/me` 的 API 工厂已经存在。

### 浏览、详情和分享

- BrowsePage 已覆盖目录列表、树导航、面包屑、grid/list、搜索、排序、标签过滤、选择、批量 ZIP、右键菜单、InfoPanel、项目详情、缩略图、分享和移动端布局。
- DetailPage 已覆盖项目详情、标签/笔记/URL 展示、文件列表、图片画廊、ImageViewer 和下载。
- ShareReceivePage 已实现分享信息、密码验证、分享范围展示、预览、单文件下载和批量下载；但目前没有同名页面测试，这是最明显的高价值测试空白。
- 管理页面已存在用户、邀请、活动日志、在线用户和分享管理组件，并使用 domain invalidation 触发权威 HTTP refetch。

### 实时数据流

- [`RealtimeContext.tsx`](../../../../webui/src/stores/RealtimeContext.tsx) 维护 `epoch + revision` cursor。
- 支持 `files`、`tree`、`home`、`project_detail`、`metadata`、`tags`、`shares`、`users`、`activity`、`online_users`、`stats` 失效域。
- 首次 `runtime_ready`、epoch 改变、revision gap 和 WebSocket 恢复都会走 `/api/revision` 或页面自己的权威 HTTP 重新读取。
- [`useInvalidation.ts`](../../../../webui/src/hooks/useInvalidation.ts) 将页面/组件订阅到具体 domain，避免消费者各自管理 transport。

## 3. 当前未闭合的事实

### 真实跨端验收未闭合

已有的 `tests/e2e/test_webui_realtime_acceptance.py` 能启动生产 LAN server、加载 `webui/dist`、使用 Chromium 和 cookie、验证 mutation/revision-gap/epoch recovery；但它仍主要是临时库、`127.0.0.1`、headless Chromium、单浏览器 context 的自动化。它不能替代：

- 真实 Desktop 主窗口操作与第二个真实 LAN 浏览器同时运行；
- access-key/password/user/guest/share 的完整权限矩阵；
- 移动浏览器、375px/窄屏、触控和真实下载行为；
- 真实图片、真实目录拓扑和真实存储介质性能；
- Desktop 修改后 WebUI 与 WebUI 修改后 Desktop 的完整用户旅程。

### 前端直接测试空白

并行只读盘点确认以下区域没有或只有间接测试：

- `ShareReceivePage.tsx`：没有同名测试。
- API 工厂：`auth.ts`、`metadata.ts`、`shares.ts`、`users.ts`、`tags.ts`、`thumbnails.ts`、`system.ts` 没有完整的独立方法合约测试。
- `ContextMenu.tsx`、`Modal.tsx`、`Skeleton.tsx`、`ResizablePanel.tsx` 没有直接测试。
- `UserManagement.tsx` 主要由 `AdminManagement.test.tsx` 间接覆盖。
- `useInvalidation`、`useDialogFocus`、`useMediaQuery` 等小型 hooks 缺少直接测试。
- `App.tsx` 没有路由组合级测试。
- `en`/`zh`/`ja` 缺少自动化 key parity 契约。

## 4. G6-5 状态边界

G6-5 第一切片的代码和报告已经进入当前 baseline，但独立审查并未认可其无条件交付。待修复问题为：

1. `file_meta` 孤儿判断与删除之间存在竞态，可能删除并发写入的新 notes/URLs。
2. thumbnail cache 也存在判断与删除之间的竞态。
3. 后台任务把 quick check、全表扫描和文件系统探测全部放在 session operation lease 内，切库/退出可能长时间等待。
4. `Thread.start()` 失败时 `_running` 没有回滚，可能永久锁死 single-flight。
5. thumbnail cache key 的 `../`、绝对路径、UNC、malformed key、symlink/junction 等对抗性测试不足。

第二会话可以独立推进纯前端测试和体验工作，但所有状态报告必须保留这个 blocker；不要因为 WebUI 测试通过而把整体 Desktop–LAN–WebUI 基线写成 fully delivered。

## 5. 当前最重要的判断

WebUI 的“功能骨架”已经存在，下一阶段的主要风险不是缺少页面，而是：

- 核心页面是否有直接证据；
- 前端是否严格遵守 LAN DTO、权限和 cookie/WebSocket 契约；
- 真实浏览器/移动端是否能完成用户旅程；
- 大量真实图片和目录下的视觉、缩略图和布局性能是否稳定。
