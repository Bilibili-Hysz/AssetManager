# 05 — 优先级任务队列

任务按“先冻结事实，再补证据，再做体验”的顺序排列。第二会话可先做纯前端工作，但不得隐去 G6-5 blocker 或把未经真实浏览器验证的结论写成发布门禁。

## W0 — 保持 G6-5 blocker 可见并修复

责任主体主要是 Desktop/application 线，不是 WebUI 视觉线；如果第二会话不负责后端修复，也必须在报告中引用并跟踪。

- 在写锁内重新验证 `file_meta` 孤儿状态，避免判断后删除竞态。
- 对 thumbnail cache 做相同的并发复核和 containment 对抗性测试。
- 为后台完整性检查设计可取消、有界 drain 或明确的关闭降级语义，避免切库/退出无限等待。
- `Thread.start()` 失败时回滚 `_running`，并补 single-flight 启动失败测试。
- 覆盖 `../victim`、绝对路径、UNC、malformed key、symlink/junction 等 key。
- 修复后重新运行 G6-5 targeted gate，再更新报告；在此之前不要宣称 G6-5 PASS。

## W1 — 冻结 WebUI/LAN 契约矩阵

本交接包的 [`03-api-and-cross-surface-contracts.md`](./03-api-and-cross-surface-contracts.md) 是起点，第二会话应把它转成可审计的测试/记录：

- 每个 API 标记 read、mutation、admin、capability、share-public、cookie 语义。
- 为 `auth.ts`、`metadata.ts`、`shares.ts`、`users.ts`、`tags.ts`、`thumbnails.ts`、`system.ts` 增加方法级 contract tests。
- 补 `/api/tunnel/status` 的文档-代码差异记录，按当前 route 的 admin 要求处理。
- 检查所有 path/query/body 字段名和中文、空格、斜杠、`..` 的 encoding。
- 禁止修改后端协议而不更新 `webui` contract test、`tests/lan` 和本交接矩阵。

## W2 — 补齐前端直接证据

建议第二会话的第一批代码任务：

### P0：ShareReceivePage 测试

新增 `webui/src/pages/ShareReceivePage.test.tsx`，覆盖 info、文件/目录、不存在、过期、密码错误/成功、preview/download URL 编码、单/批量下载、重复提交和缺字段降级。

> ✅ 2026-08-04 完成：14 个用例 + 页面缺失行为补齐（过期/空 paths/加载失败降级、`getPreviewUrl` preview 链接、验证防重复提交、stale 防护、i18n 三语 6 key）。契约注记：**公开分享无批量下载端点**（`POST /api/download/batch` 是登录态接口），页面按"下载链接"处理；密码保护首页 `getInfo` 返回 sanitized 响应无 `paths`（有路径即 cookie 已授权 `verified`）。收口提交 `7582a78`：`test: add ShareReceivePage coverage and degrade-gracefully states`。另修复全量 flaky：`AuthContext.test.tsx` logout identity-generation 断言并入 `waitFor`（guest `authenticated=false` 初始即满足，原断言在 state flush 前通过）。

### P0：API 工厂合约

按优先级：`auth.ts` → `metadata.ts` → `shares.ts` → `users.ts` → `tags.ts` → `thumbnails.ts` → `system.ts` → `files.ts` 非下载路径。每个测试至少断言 HTTP method、endpoint、query/body、encode、AbortSignal 透传和返回 DTO。

> ✅ 2026-08-04 完成：新增 8 个契约测试文件（`auth/metadata/shares/users/tags/thumbnails/system/files.contract.test.ts`），37 用例，全量 46 文件/343 通过。与 `AssetsManager/lan/api.py` 路由逐条核对：method/endpoint/query/body/encode/AbortSignal 均一致。契约注记：
> - `metadata.ts`/`files.ts`/`users.ts`/`tags.ts` 用 `encodeURIComponent` 整体编码 path（`/`→`%2F`），后端 `{path:.*}` 贪婪路由 + `unquote(match_info["path"])` 还原；`shares.ts` 用 `encodeSharePath` 分段编码（分隔符不转义）。两者对字面 `%` 文件名的解码行为不同，见 `08-known-risks.md`。
> - `client.ts` 的 `put`/`delete` 不接收 AbortSignal；factory 中 `tags.rename/delete`、`users.revokeInvite`、`shares.delete` 均无 signal，测试按现状断言。
> - `auth.register` 保留 `email`/`invite_code` key（undefined 由 client 过滤）。
> 收口提交 `37a849a`：`test: add API factory contract tests for all factories`。

### P1：基础交互组件

新增 `ContextMenu.test.tsx`、`Modal.test.tsx`、`ResizablePanel.test.tsx`，覆盖 Escape、outside click、focus、disabled item、键盘导航、pointer capture、最小/最大尺寸和卸载清理。

> ✅ 2026-08-04 完成：`ContextMenu.test.tsx`（8 用例）、`Modal.test.tsx`（9 用例）、`ResizablePanel.test.tsx`（7 用例），全量 52 文件/388 通过，typecheck/build 通过。另修复 `ResizablePanel.tsx` 缺陷：拖拽中卸载会残留 document `mousemove`/`mouseup` listener 与 body cursor/userSelect（`stopDrag` + move/up handler refs + `useEffect` 卸载清理）。收口提交 `3640c82`。
>
> 补充轮（同提交）：`TagChip.test.tsx`（7 用例：render name/count、count 缺省不显示、onClick 触发、onRemove stopPropagation、cursor-pointer 条件样式）；`useMediaQuery.test.tsx`（3 用例：初始 matchMedia 值、change event 更新、unmount 清理 listener）；`useDialogFocus.test.tsx`（6 用例：dialog 聚焦、Escape 关闭、Tab 循环、returnFocusTo、空 focusable 列表、isOpen=false 无效）。
>
> 环境注意：`~`/`#`/`%` 路径下必须用 `npm test`（`scripts/run-vitest.mjs` 经 `subst` 映射临时盘符）；直接 `npx vitest` 会报 `Cannot find module '/@vite/env'`。

### P1：页面组合与字典

- 新增 `App.test.tsx`，覆盖公开/受保护/share/未知路由和 Provider 组合。
- 新增 i18n key parity test，保证 `en`、`zh`、`ja` 结构一致。
- 为 `UserManagement` 补独立测试，覆盖 toggle、空态、错误 toast、旧响应丢弃和实时刷新。

> ✅ 2026-08-04 完成：`App.test.tsx`（9 用例：公开/受保护/share/未知路由、openGuest 直通、capability 缺失重定向 `/`、未认证重定向 `/login`、loading 空渲染；mock 页面与四个 Provider 后验证 `BrowserRouter` 路由映射）；`src/i18n/i18n.test.ts`（5 用例：zh/ja 与 en 扁平 key 完全一致、`{n}` 占位符一致、值非空、`setLang`/`subscribeToLang` 行为）；`UserManagement.test.tsx`（7 用例：渲染/空态/toggle 后 canonical refetch/invalidation refetch/旧响应丢弃/identityGeneration 变化清空/toggle 失败保留列表）。收口提交 `3640c82`。

### P2：hooks 与组件边缘覆盖

- 新增 `useInvalidation.test.tsx`、`useI18n.test.tsx`，补 `ShareDialog.test.tsx`（error/cancel/loading）和 `DownloadProgress.test.tsx`（null total/default label/clamp）。

> ✅ 2026-08-04 完成：`useInvalidation.test.tsx`（5 用例）、`useI18n.test.tsx`（5 用例）、`ShareDialog.test.tsx` +6 用例、`DownloadProgress.test.tsx` +3 用例，全量 57 文件/423 通过，typecheck/build 通过。

## W3 — 真实 Desktop/LAN/WebUI 验收

在 W1/W2 稳定后，建立真实跨端矩阵：

- Desktop 启动真实 library root 和 Runtime；
- Desktop 开启 LAN；
- 第二个真实浏览器通过 LAN origin 进入；
- login/access-key/password/user/guest/share 权限分别验证；
- 浏览、预览、下载、批量下载；
- WebUI 修改标签/文件后 Desktop 观察；
- Desktop 修改后 WebUI 不刷新页面即可恢复；
- LAN stop/start、同端口恢复、同 root reopen 的 revision/epoch recovery；
- 窄屏/移动浏览器、触控、焦点和 reduced motion；
- 记录浏览器、OS、端口、库 root 形态、认证模式、截图/日志和失败原因。

> ✅ 2026-08-04 Playwright E2E 验收（静态构建产物）完成：16/16 通过（`npx playwright test --reporter=list`，50s）。
>
> 覆盖范围：Landing page（标题/登录按钮/viewport meta）、Routing（未知路由 404 / share 页面 / 登录页面）、Responsive design（375px mobile / 1920px desktop 水平溢出检查 + 背景色验证）、Keyboard accessibility（Tab 焦点移动 / body 无负 tabIndex）、CSS layout（内容可见性 / overflow:hidden / favicon+title）、Network resilience（API 失败无白屏 / console 无 module 加载错误）。
>
> 测试环境：Python `http.server` 服务 `dist/` 静态产物（base URL `http://localhost:4173`），headless Chromium `chromium-1228`。**局限**：静态服务器不支持 SPA 路由 fallback（未知路由返回 404 而非 React Router 重定向），此为测试环境限制而非应用缺陷。无真实 API 交互（后端 PySide6 无法无头启动）。
>
> 收口提交 `2da5cef`：`test: add Playwright E2E tests for landing/routing/responsive/keyboard/css/network`。新增 `webui/playwright.config.ts`、`webui/e2e/app.spec.ts`；`package.json` 加 `test:e2e` 脚本；`vite.config.ts` 加 `server.fs.allow` 解决 `~` 路径 403。

当前 Chromium acceptance 是自动化基础，但不能直接写成上述完整矩阵已完成。完整的 Desktop+LAN 跨端验收需要后端（PySide6）无头模式或真实桌面环境。

## W4 — 真实图片与布局性能协议

性能改动前先定义可复现数据集协议：dataset ID/version、不含绝对路径的 manifest、规范化相对路径稳定排序、hash-based fixed sampling、thumbnail sample limit、directory/grid parent limit、cold/warm 定义、预热、5 次重复、P50/P95、异常剔除规则，以及 CPU/内存/存储/OS/浏览器/DPI/后台负载。

可复用入口：

- `tests/perf/thumbnail_telemetry_benchmark.py`
- `tests/perf/directory_telemetry_benchmark.py`
- `tests/perf/grid_telemetry_benchmark.py`
- `tests/performance/test_baselines.py`

先生成趋势证据，不要马上把真实数据接成阻断式 PR 门禁。

## W5 — 视觉和体验切片

契约和验收稳定后再处理：BrowsePage loading/empty/error/retry、ProjectCard/Grid/List 视觉和键盘状态、ShareDialog 错误和复制失败、ShareReceivePage 状态、Admin 页面状态、375px/触控/focus/reduced motion、预览交互和真实图片性能。

每个视觉切片都要保留行为测试，不能用 CSS 改动掩盖 loading、授权或 stale response 问题。

## W6 — DeepSeek 视觉与 WebUI 扩展路线

新增的 [`09-visual-optimization-and-design-system.md`](./09-visual-optimization-and-design-system.md) 定义卡片 Grid、缩放动画、token、状态、无障碍和视觉验收；新增的 [`10-deepseek-webui-expansion-roadmap.md`](./10-deepseek-webui-expansion-roadmap.md) 对照 G5-1～G5-9、A/B/C 阶段和未来 Storefront。

- V0：先冻结 token、按钮/图标语义、loading/empty/error/retry 和 reduced-motion 规则。
- V1：统一 Browse/FileList 的卡片尺寸、左对齐 Grid、正方形 thumbnail、hover/selected/focus 状态。
- V2：统一 Detail、ShareDialog、Admin 的反馈与移动端状态；补浏览器截图证据。
- V3：真实数据证明有必要后，再推进 G5-4 虚拟滚动或后端分页。
- S1 Storefront、G5-1 编辑、G5-2 上传、S2/S3 商品化均单独立项，不混入当前 Browse 视觉切片。

## W7 — G5-7 错误反馈统一

`client.ts` 原来仅有 `console.error` + `throw`，503 白屏无提示，401 无统一跳转。已实现：

- ✅ `webui/src/api/errors.ts`：`ApiError`（status/body）、`UnauthorizedError`（401）、`ForbiddenError`（403）、`ServiceUnavailableError`（503）、`NetworkError` + 类型守卫。
- ✅ `webui/src/api/client.ts`：三函数 HTTP 错误→结构化错误；三函数 fetch try-catch → `NetworkError`。
- ✅ `webui/src/stores/AuthContext.tsx`：`serviceUnavailable` 状态；init catch 检测 `isServiceUnavailableError`/`isNetworkError`。
- ✅ `webui/src/pages/LandingPage.tsx`：503 显示 Service Unavailable 页面 + Retry 按钮。
- ✅ i18n 三语增加 `error.unavailable` key。
- ✅ `webui/src/api/errors.test.ts`：6 用例覆盖所有错误类和类型守卫。
- ✅ 58 文件 / 429 测试通过，typecheck + build 通过。

提交 `待提交`：`feat: structured API errors and 503 service unavailable handling`。
