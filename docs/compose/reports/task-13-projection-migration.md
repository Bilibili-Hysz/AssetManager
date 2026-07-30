---
feature: task-13-projection-migration
status: delivered
specs:
  - docs/compose/specs/2026-07-21-desktop-lan-webui-architecture-design.md
plans:
  - docs/compose/plans/2026-07-21-desktop-lan-webui-architecture-migration.md
branch: working-tree
commits: uncommitted
---

# Task 13 — React Projection Migration Final Report

## What Was Built

Task 13 将 React 页面和管理投影从页面级 WebSocket 事件解析迁移到统一的
`useInvalidation(domains, callback)` 注册接口。页面继续复用原有的 HTTP refresh
函数，实时层只负责按 projection domain 触发刷新，不复制业务数据请求逻辑。

页面现在按 ownership 注册失效域：Browse 负责 files/metadata/tags/project_detail，
Sidebar 负责 tree，Landing 负责 home，Detail 负责 project_detail/metadata/tags，
ActivityLog 和 OnlineUsers 负责 users/shares/stats，StatusBar 负责 stats。

## Architecture

BrowsePage 和 StatusBar 不再直接使用 `useWebSocket` 或解析 raw event name。所有
生产组件通过 `useInvalidation` 接收经过 Provider cursor、epoch、gap recovery 和
duplicate suppression 处理后的 domain callback。

各投影仍保留自己的请求安全边界：

- Browse/Detail 使用已有 AbortController、request generation 和 selected path
  matching；
- Landing 保留 home refresh、generation 和图片/请求清理；
- Sidebar、ActivityLog、OnlineUsers 使用 mounted guard + generation guard，避免
  连续 invalidation 的乱序响应覆盖新数据；
- StatusBar 将 stats invalidation 与 10 秒 polling 共用同一个 generation guard，
  避免旧统计响应覆盖新统计。

## Design Decisions

- 选择按 projection ownership 注册精确 domain，而不是所有页面收到所有失效后自行
  判断，因为这样可以避免无关网络请求并让刷新责任可审计。
- 选择复用现有 refresh 函数，因为 HTTP 快照仍是权威数据源，RealtimeProvider 不应
  复制页面数据读取或构建全局 reload。
- 选择在每个 projection 内保留 generation/mounted 保护，因为 invalidation 可以
  与轮询、导航、选择变化和多个 HTTP 请求并发发生。
- StatusBar 保留原有轮询作为兜底，同时用 stats invalidation 提供即时刷新；两条
  路径共享 generation guard，不改变既有视觉和连接状态展示。

## Usage

页面通过 `useInvalidation` 注册稳定 refresh callback：

```tsx
useInvalidation(['files', 'metadata', 'tags', 'project_detail'], refresh);
```

组件卸载或依赖变化时，hook 自动取消注册。Task 13 不实现真实浏览器 LAN
acceptance、断线场景和 server restart 场景；这些属于 Task 14。

## Verification

- Task 13 focused suite：7 files，73 passed
- Full WebUI tests：34 files，251 passed
- WebUI typecheck：通过
- WebUI production build：通过
- LAN realtime/API：173 passed
- Integration + LAN：582 passed，1 skipped
- Ruff：通过
- scoped `git diff --check`：通过
- 生产页面/组件不再直接创建 WebSocket 或解析 raw event name
- 独立 defect-first review：无 P0/P1/P2

跳过项是 Windows 平台不支持目录 symlink 的既有测试，不属于 Task 13 回归。

## Journey Log

- [lesson] 页面级 WebSocket transport 即使复用 Provider 物理连接，也会绕过统一
  cursor/gap/domain 语义，因此必须迁移业务事件解释，而不仅是合并 socket。
- [lesson] invalidation refresh 可能与导航、轮询和其它失效并发，mounted 标志不足，
  每个 projection 还需要 request generation 或 AbortController。
- [pivot] StatusBar 保留轮询作为可靠兜底，同时注册 stats invalidation 提供即时刷新，
  避免改变已有状态栏行为。

## Source Materials

| File | Role | Notes |
|------|------|-------|
| `docs/compose/specs/2026-07-21-desktop-lan-webui-architecture-design.md` | Architecture specification | Defines projection ownership and refresh boundary |
| `docs/compose/plans/2026-07-21-desktop-lan-webui-architecture-migration.md` | Implementation plan | Task 13 migration contract |
| `webui/src/pages/BrowsePage.tsx` | Browse projection | Registers files/metadata/tags/project_detail |
| `webui/src/components/layout/Sidebar.tsx` | Tree projection | Registers tree invalidation |
| `webui/src/pages/LandingPage.tsx` | Home projection | Registers home invalidation |
| `webui/src/pages/DetailPage.tsx` | Detail projection | Registers project_detail/metadata/tags |
| `webui/src/components/admin/ActivityLog.tsx` | Admin projection | Registers users/shares/stats |
| `webui/src/components/admin/OnlineUsers.tsx` | Admin projection | Registers users/shares/stats |
| `webui/src/components/layout/StatusBar.tsx` | Stats projection | Registers stats and keeps polling fallback |
