# 07 — 第二会话第一轮清单

## A. 建立基线

- [ ] 阅读本目录 `README.md` 到 `08-known-risks.md`。
- [ ] 读取外置 Git HEAD，确认是 `de64492` 或明确记录新的基线。
- [ ] 用外置 Git 检查工作树；不覆盖其他会话的用户改动。
- [ ] 阅读 `webui/DESIGN.md`、`App.tsx`、`AuthContext.tsx`、`RealtimeContext.tsx`、`BrowsePage.tsx`、`types/api.ts`。
- [ ] 阅读 [`09-visual-optimization-and-design-system.md`](./09-visual-optimization-and-design-system.md) 与 [`10-deepseek-webui-expansion-roadmap.md`](./10-deepseek-webui-expansion-roadmap.md)。
- [ ] 运行 WebUI test、typecheck、build，记录真实计数。

## B. 先冻结契约

- [ ] 阅读 [`03-api-and-cross-surface-contracts.md`](./03-api-and-cross-surface-contracts.md)。
- [ ] 对照 `AssetsManager/lan/api.py`、`server.py`、`routes/_helpers.py`、`routes/websocket.py`。
- [ ] 确认浏览器使用 same-origin HttpOnly cookie，不在 JS state 中保存 bearer token。
- [ ] 确认 WebSocket URL 只使用 `/ws`，不带 query `token`/`key`。
- [ ] 确认 WebSocket 只作为 invalidation hint，权威状态由 HTTP refetch 提供。
- [ ] 不修改后端 DTO、权限和路径编码，除非同时补齐契约测试和文档。

## C. 第一批前端工作

- [ ] 新增 `ShareReceivePage.test.tsx`，覆盖 info、密码、过期、预览、单/批量下载和错误。
- [ ] 为 `auth.ts`、`metadata.ts`、`shares.ts` 建立方法级 API contract tests。
- [ ] 视时间补 `users.ts`、`tags.ts`、`thumbnails.ts`、`system.ts`、`files.ts` 的方法级测试。
- [ ] 每个请求断言 method、path、query/body、编码和错误/取消语义。
- [ ] 跑最小回归：相关测试 → 全 WebUI test → typecheck → build。

## D. 第二批前端工作

- [ ] 补 `ContextMenu`、`Modal`、`ResizablePanel` 行为测试。
- [ ] 补 `App` 路由组合测试。
- [ ] 补 i18n `en`/`zh`/`ja` key parity。
- [ ] 补 `UserManagement` 独立测试。
- [ ] 在不改变行为的前提下处理 loading/empty/error/retry 视觉状态。
- [ ] 先冻结 token、卡片 Grid 和 motion 规则，再改 ProjectCard/ProjectGrid。
- [ ] 视觉改动验证 dark/light、375px、focus-visible、reduced-motion 和 broken thumbnail。

## E. 真实验收准备

- [ ] 重新构建 `webui/dist`。
- [ ] 运行已有 Chromium realtime acceptance，记录是产品失败还是环境失败。
- [ ] 建立真实 Desktop/LAN/第二浏览器矩阵，至少覆盖 cookie auth、share auth、realtime、stop/start、same-root reopen。
- [ ] 增加窄屏、触控、focus-visible、reduced-motion 证据。
- [ ] 对真实图片性能先定义 dataset/manifest/sample/repeat 协议，再改生产代码。

## F. 阶段收口

- [ ] 复核没有修改 LAN 协议或认证边界。
- [ ] 复核旧请求不会覆盖新 identity/路径/搜索结果。
- [ ] 运行 `git diff --check`，并检查相对链接。
- [ ] 文档与代码分开提交；提交信息清楚描述范围。
- [ ] 汇报：完成项、未完成项、测试计数、环境限制、外置 Git HEAD、G6-5 blocker 状态。
