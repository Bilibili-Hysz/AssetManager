# WebUI 第二会话交接包

本目录是给第二会话准备的 WebUI 前端工作基线。第二会话的主职责是 React/Vite SPA 的测试、体验、响应式和浏览器级验收；Desktop Runtime、LAN 路由、认证和实时协议已经有现成实现，除非契约核查明确要求，不应在前端任务中随意改动这些边界。

## 当前基线

盘点日期：2026-08-03
仓库：`D:/~Vibe-Coding/Projects/AssetsManager_old-bak`
代码审查基线：`de64492 docs: record G6-5 integrity check slice`
上一轮交接提交：`b9dca9d docs: prepare WebUI session 02 handoff`
当前 HEAD 以外置 Git status 为准。

本环境的 Codex 沙箱仍不能把原仓库 `.git` 当作可写 Git 元数据，因此本项目使用外置 Git 元数据目录进行状态、暂存和提交操作：

```powershell
$repo = "D:\~Vibe-Coding\Projects\AssetsManager_old-bak"
$gitDir = "C:\Users\86177\.codex\visualizations\2026\07\31\019fb82d-6e7b-7731-9239-2a0d66ff4c54\assetsmanager-git-metadata-99e3971"

git --git-dir=$gitDir --work-tree=$repo status --short
git --git-dir=$gitDir --work-tree=$repo log -5 --oneline
```

外置 Git 工作树在本交接包创建前是干净的。原 `.git` 不要删除、重建或覆盖；新会话继续使用同一外置元数据目录，并在每个阶段结束时复核状态。

## 当前结论

- React/Vite WebUI 已经是 LAN 的正式 SPA 入口，旧静态页面不应重新引入。
- 当前 WebUI 测试、类型检查和生产构建都通过：本轮实测为 **37 个测试文件、292 个测试通过**；`npm --prefix webui run typecheck` 通过；构建转换 **1632 个模块**并成功产出 `webui/dist`。
- AuthContext、RealtimeContext、统一 API client、Browse/Detail/Landing/Login/ShareReceive 页面以及管理、分享、预览和文件组件已经存在。
- 实时消息是失效提示，不是权威数据。页面收到 invalidation 后必须重新请求 HTTP snapshot；不要把 WebSocket payload 当作完整文件、标签、分享或用户状态。
- 当前尚未形成完整的真实 Desktop → LAN → 第二浏览器 → Desktop 用户旅程门禁；jsdom/Vitest 通过不等于真实 Chromium、移动端和真实图片性能已经验收。
- G6-5 数据库完整性第一切片已提交到基线，但独立审查发现并发删除、关闭等待、线程启动回滚和缩略图 key 对抗性测试等阻塞项。第二会话不能把 G6-5 写成无条件 PASS；详见 [`05-priority-backlog.md`](./05-priority-backlog.md) 与 [`08-known-risks.md`](./08-known-risks.md)。
- DeepSeek Docs 的视觉优化和 WebUI 初期扩展计划已转为当前代码映射；视觉工作优先走增量 token/组件/状态验收，Storefront 和上传/编辑等扩展按契约与后端前置条件推进。

## 推荐阅读顺序

1. [`01-current-state.md`](./01-current-state.md)：当前代码与证据边界。
2. [`02-webui-architecture.md`](./02-webui-architecture.md)：Provider、数据流和实时恢复规则。
3. [`03-api-and-cross-surface-contracts.md`](./03-api-and-cross-surface-contracts.md)：前后端实际 API、认证和 WebSocket 契约。
4. [`04-file-map.md`](./04-file-map.md)：按职责定位源码、测试和文档。
5. [`05-priority-backlog.md`](./05-priority-backlog.md)：按风险排序的下一批任务。
6. [`06-verification-and-environment.md`](./06-verification-and-environment.md)：运行命令、环境限制和证据记录方式。
7. [`07-first-session-checklist.md`](./07-first-session-checklist.md)：第二会话第一轮执行清单。
8. [`08-known-risks.md`](./08-known-risks.md)：不能忽略的契约、测试和环境风险。
9. [`09-visual-optimization-and-design-system.md`](./09-visual-optimization-and-design-system.md)：DeepSeek 视觉原则迁移到 React/Vite 的执行规范。
10. [`10-deepseek-webui-expansion-roadmap.md`](./10-deepseek-webui-expansion-roadmap.md)：初期 G5 缺口、前后端分离和 Storefront 路线映射。

## 必须先看的仓库文件

- [`webui/DESIGN.md`](../../../../webui/DESIGN.md)：Gate 首页的视觉、无障碍和反模式约束。
- [`webui/src/App.tsx`](../../../../webui/src/App.tsx)：路由和 Provider 组合。
- [`webui/src/stores/AuthContext.tsx`](../../../../webui/src/stores/AuthContext.tsx)：cookie session、principal、capability 和身份世代。
- [`webui/src/stores/RealtimeContext.tsx`](../../../../webui/src/stores/RealtimeContext.tsx)：epoch/revision、失效域和 gap recovery。
- [`webui/src/pages/BrowsePage.tsx`](../../../../webui/src/pages/BrowsePage.tsx)：当前最大的业务页面。
- [`webui/src/types/api.ts`](../../../../webui/src/types/api.ts)：前端 DTO 类型边界。
- [`AssetsManager/lan/api.py`](../../../../AssetsManager/lan/api.py)：实际路由注册表。
- [`AssetsManager/lan/server.py`](../../../../AssetsManager/lan/server.py)：认证 middleware、公开路径和服务生命周期。
- [`docs/architecture.md`](../../../architecture.md)、[`docs/lan-security.md`](../../../lan-security.md)：架构和安全基线。

## 不要在没有契约证据时做的事

- 不要把 WebSocket 改成 query-string `token`/`key` 认证；生产路由会拒绝这类实时握手。
- 不要在组件内各自创建长期 WebSocket；`RealtimeContext`/`WebSocketTransportHost` 是中央 transport host。
- 不要在前端保存或重新拼装 Desktop 的 bearer token；浏览器使用同源 HttpOnly `lan_token` cookie。
- 不要通过改变 DTO 字段名、路径编码或权限判断来“顺手修 UI”；先更新契约测试和交接记录。
- 不要把历史报告中的 `251`、`256`、`1590` 等数字直接当作当前门禁；每次报告必须注明运行日期和命令。

## 第一轮建议

先运行 [`07-first-session-checklist.md`](./07-first-session-checklist.md) 的基线命令，然后优先补齐 ShareReceivePage/API 工厂/基础行为组件的证据，再进入真实 Chromium 和移动端验收。每个切片单独测试、复核、记录；代码与文档分开提交。
