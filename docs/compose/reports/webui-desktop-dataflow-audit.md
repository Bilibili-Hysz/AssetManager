---
feature: webui-desktop-dataflow-audit
status: delivered
specs: []
plans:
  - docs/compose/plans/2026-07-21-webui-desktop-dataflow-audit.md
branch: master
commits: 4afd85116421002eafe637a440bb52ab0103f081
---

# WebUI 与桌面端数据流审计 — Final Report

## What Was Built

本报告审计桌面 PySide6、共享应用服务、aiohttp LAN 服务与 React WebUI 的当前生产数据流。结论是：库根目录、SQLite 连接、路径防逃逸、Cookie 认证与预览权限边界总体可靠；但跨端实时一致性没有形成闭环，管理页还有多组已到达真实消费者的 JSON 契约失配。未发现 P0 数据泄露、跨库访问或权限绕过。

## Architecture

桌面 `LibrarySession` 是库生命周期与数据库连接的权威所有者；`LanSharingMixin` 将同一个库根、连接、缩略图目录和 `event_token` 传给 `LanServer`。LAN 按服务器实例缓存一组应用服务，React 通过 HTTP 获取投影快照，理论上由 WebSocket 事件触发重新拉取。

| 数据域 | 权威源 | LAN 传输 | React 消费 | 当前一致性 |
|---|---|---|---|---|
| 文件/项目/树 | 文件系统 + SQLite | `/api/files`、`/api/projects`、`/api/tree` | `useProjects`、Sidebar | HTTP 快照可用；实时断链 |
| 标签/备注/URL | SQLite | `/api/tags`、`/api/meta` | Browse/InfoPanel | CRUD 可用；变更不刷新 |
| 缩略图/预览 | 文件系统 + ThumbnailService | batch 与单图路由 | Grid/List/InfoPanel | 权限、路径和数据源分离正确 |
| 身份/权限 | LAN 中间件 + AuthService | HttpOnly Cookie + `/auth/me` | AuthContext | 服务端权威；客户端能力推导有漂移 |

### Findings

#### P1 — WebSocket 没有接入任何生产变更源

应用服务确实发布文件、标签和元数据事件（`AssetsManager/application/file_operation_service.py:144`、`tag_service.py:59`、`metadata_service.py:58`），但仓库内 `LanServer.broadcast` 只有门面与实现（`AssetsManager/lan/__init__.py:85`、`lan/server.py:164`），没有生产调用方。React 又只在收到三种文件事件时刷新列表（`webui/src/pages/BrowsePage.tsx:157`）。结果是桌面端修改文件、LAN 端修改标签/元数据后，已打开的浏览器不会实时更新；必须手工刷新或重新导航。最小修复是由 LAN 生命周期所有者订阅 session-scoped 领域事件，按库 `event_token` 过滤后映射为稳定的失效事件，并让 React 按投影刷新列表、树、详情与标签。

#### P1 — 用户与邀请码响应直接违反管理页契约

用户仓储返回 `is_active` 和数值 `created_at`（`AssetsManager/repositories/auth_repository.py:156`），而 React 要求 `active` 和字符串时间（`webui/src/types/api.ts:29`）；`UserManagement` 直接读取 `user.active`（`webui/src/components/admin/UserManagement.tsx:47`），因此真实用户会显示为禁用，首次切换还会基于 `undefined` 发出错误意图。邀请码列表只返回 `code/created_by/created_at/is_active`（`AssetsManager/repositories/auth_repository.py:206`），客户端却读取 `revoked/used_by`（`webui/src/types/api.ts:252`、`components/admin/InviteManagement.tsx:53`），导致已使用或已撤销状态无法正确显示。应在 Python 公共响应边界统一规范化字段，并以真实路由 JSON 驱动前端契约测试。

#### P1 — WebSocket 断线恢复在一次失败后永久停止

客户端在 `retryRef.current >= 1` 后停止重连，且成功 `onopen` 不重置计数（`webui/src/hooks/useWebSocket.ts:38`、`:53`）。一次短暂网络抖动后再次断线，页面余下生命周期内不再恢复实时连接。应采用有上限的持续指数退避，并在稳定连接后重置失败计数；补充多轮断开/恢复测试。

#### P2 — 管理端活动、在线用户和服务器统计没有生产数据源

`ActivityLog` 与 `OnlineUsers` 只在 LAN 服务包中实例化（`AssetsManager/lan/routes/_helpers.py:43`、`:62`），全仓库没有 `activity_log.add`、`online_users.connect/disconnect` 生产调用，所以对应管理页永远为空。服务器的 connections/requests/bytes 只初始化并原样返回（`AssetsManager/lan/server.py:94`、`:149`），`uptime` 未进入 status，故 `/api/stats` 基本恒为零（`AssetsManager/lan/routes/system.py:67`）。应在请求/WS 生命周期建立唯一计数与记录点，或删除尚未实现的 UI，避免展示虚假遥测。

#### P2 — guest 实时能力与权限展示不是服务端策略的投影

无认证模式不会建立 `user`，BrowsePage 以 `Boolean(user)` 禁用 WebSocket（`webui/src/pages/BrowsePage.tsx:164`）；即使直接连接，`/ws` 也拒绝没有 request user 的 guest（`AssetsManager/lan/routes/websocket.py:11`）。同时服务端 guest 权限来自 `lan_guest_list/download/preview`（`lan/routes/_helpers.py:231`），AuthContext 却硬编码不同组合（`webui/src/stores/AuthContext.tsx:61`、`:100`）。这会让 UI 操作入口与真实 403 策略不一致。应让 `/api/info` 或 `/auth/me` 返回规范化 principal + capabilities，并用 capability 而非 `Boolean(user)` 控制 WebSocket和操作入口。

#### P3 — TypeScript 还声明了服务端从不提供的字段

项目树节点只有 `name/path/is_leaf/children`（`AssetsManager/application/project_service.py:562`），而 `TreeItem.type` 必填（`webui/src/types/api.ts:116`）；标签只有 `{name,count}`（`AssetsManager/repositories/tag_repository.py:31`），而 `Tag.id` 必填（`webui/src/types/api.ts:169`）。当前消费者分别依赖 `is_leaf` 和 `name`，尚未观察到运行时崩溃，但这些错误类型会掩盖未来集成缺陷。应删除不存在字段或在服务端明确补齐，不要用断言维持虚假契约。

### Design Decisions

我们把“共享 SQLite”与“实时一致性”分开评价，因为同一数据源只能保证下一次查询可见，不能使已渲染的 React 状态自动失效。我们也把 synthetic principal 与持久用户分开建模：密码、访问密钥和 local UI 经中间件可获 admin 权限（`AssetsManager/lan/server.py:441`），但 `/auth/me` 返回的 synthetic 字典不满足持久 `User` 全字段契约。

## Usage

修复顺序建议：先建立 session-scoped DomainEvent→WebSocket 桥并覆盖多轮重连；再统一 principal/capabilities 与用户、邀请码响应 DTO；随后接通或移除活动/在线/统计面板；最后清理 Tree/Tag 的声明漂移。每一步都应加入“真实 Python JSON→TypeScript consumer”的契约夹具，而不是各端独立 mock。

## Verification

- `python -m pytest tests/lan/test_lan_api.py -q`：144 passed。
- `npm test -- --run src/hooks/useWebSocket.test.tsx src/stores/AuthContext.test.tsx src/components/admin/AdminManagement.test.tsx src/components/layout/Sidebar.test.tsx`：20 passed；Sidebar 仍输出两条 React Router v7 future-flag 警告。
- `npm run build`：TypeScript 与 Vite 生产构建成功。
- 这些绿色门禁覆盖局部管理器和 mock consumer，但没有覆盖桌面事件→WebSocket→React 或真实管理路由 JSON→渲染，因此不反驳上述生产链缺陷。

## Journey Log

> Brief notes on what informed the final design. Not required reading.

- [pivot] 密码/密钥 principal 会由 `/auth/me` 恢复为 synthetic admin；问题从“必然认证失败”收敛为公共身份契约漂移。
- [lesson] WebSocket endpoint、manager 和前端 hook 同时存在，不等于领域变更已经接入实时传输。
- [dead end] 五次独立审查代理均因运行时 APIError 启动失败；其输出未被作为证据。

## Source Materials

| File | Role | Notes |
|---|---|---|
| `docs/compose/plans/2026-07-21-webui-desktop-dataflow-audit.md` | 审计计划 | 范围与证据标准 |
| `AssetsManager/widgets/lan_sharing.py` | 桌面 LAN 生命周期 | session/connection 绑定 |
| `AssetsManager/lan/server.py` | LAN 生命周期与认证 | WebSocket 门面和 synthetic principal |
| `webui/src/stores/AuthContext.tsx` | React 身份状态 | 客户端角色与权限推导 |
