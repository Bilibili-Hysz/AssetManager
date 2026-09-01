---
feature: task-10-runtime-websocket-bridge
status: delivered
specs:
  - docs/compose/specs/2026-07-21-desktop-lan-webui-architecture-design.md
plans:
  - docs/compose/plans/2026-07-21-desktop-lan-webui-architecture-migration.md
branch: working-tree
commits: uncommitted
---

# Task 10 — Runtime WebSocket Bridge Final Report

## What Was Built

Task 10 将 `LibraryRuntime` 的 `InvalidationEvent` 接入认证 LAN WebSocket。具备
`realtime` capability 的 canonical principal 连接后，首先收到 `runtime_ready`
游标消息，随后收到当前 Runtime 接受的 `projection_invalidated` 消息。HTTP
客户端也可以通过 `/api/revision` 获取当前 `{epoch, revision}` 游标。

WebSocket 只发送 projection invalidation 元数据，不发送完整业务对象、数据库
记录或凭据。Runtime 回调可以来自 Desktop 线程，服务器通过目标 asyncio loop
安全调度广播；loop 停止、提交失败、广播异常和取消都不会传播回业务事件发布者。

## Architecture

`LanServer` 在 aiohttp startup/site readiness 后为 canonical Runtime 注册一个
invalidation subscription。Runtime callback 将 DTO 广播到当前
`WebSocketManager` 客户端；cleanup 阶段先关闭该 subscription，再清理 WebSocket
连接和 server 资源。

主要接口：

- `GET /api/revision` → `{ "epoch": string, "revision": number }`
- WebSocket 首条消息：`{ "type": "runtime_ready", "epoch": string, "revision": number }`
- 后续消息：`{ "type": "projection_invalidated", "epoch": string, "revision": number, "domains": string[], "paths": string[] }`

WebSocket 和 `/api/revision` 都要求 middleware 提供 canonical principal，且
`principal.capabilities.realtime` 为真。legacy `request["user"]` 只保留给兼容
HTTP 读取，不能授予 realtime；query `token` 和 `key` 也不能绕过认证。

## Design Decisions

- 选择 Runtime subscription 而不是在 route 中重新读取 EventBus，因为 Runtime
  已经负责 session token、root、epoch 和 revision 隔离。
- 选择只发送失效通知而不是业务对象，因为 SQLite/文件系统仍是权威数据源，
  客户端应通过 HTTP 快照恢复数据。
- 选择在调度失败时显式关闭未提交 coroutine，并在 future done callback 中消费
  所有 `BaseException`，因为 WebSocket 生命周期可能与 Runtime/asyncio loop
  并发关闭。
- WebSocket 在 manager 注册后统一由 `try/finally` 清理，保证初始
  `runtime_ready` 发送失败不会泄漏 dead client。

## Usage

认证并具备 realtime capability 的客户端连接 `/ws`：

```text
WS /ws
← {"type":"runtime_ready","epoch":"...","revision":7}
← {"type":"projection_invalidated","epoch":"...","revision":8,"domains":["files","tree"],"paths":["a.txt"]}
```

当前任务仅实现后端 bridge 和 DTO。React realtime provider、客户端 cursor
恢复、revision gap 检测和 library-switch/restart isolation 属于后续 Task 11/12，
未在本任务中实现。

## Verification

- Task 10 LAN/runtime contracts：`182 passed`
- Architecture/bootstrap/runtime unit gates：`102 passed`
- Integration + LAN：`578 passed, 1 skipped`
- WebUI tests：`221 passed`
- WebUI typecheck：通过
- WebUI production build：通过
- Ruff：通过
- `compileall -q AssetsManager/lan`：通过
- scoped `git diff --check`：通过
- 独立 defect-first review：无 P0/P1/P2

跳过项是 Windows 平台不支持目录 symlink 的既有测试，不属于 Task 10 回归。

## Journey Log

- [lesson] realtime admission 必须只信 canonical principal；legacy user context
  不能成为 capability 的授权后备来源。
- [lesson] `run_coroutine_threadsafe` 的提交失败和 future 完成异常必须分别处理，
  且未提交 coroutine 要显式关闭。
- [lesson] WebSocket 注册、初始 ready 发送和 receive loop 必须处于同一个清理边界，
  才能覆盖客户端握手后立即断开的路径。

## Source Materials

| File | Role | Notes |
|------|------|-------|
| `docs/compose/specs/2026-07-21-desktop-lan-webui-architecture-design.md` | Architecture specification | Defines Runtime invalidation and WebSocket boundary |
| `docs/compose/plans/2026-07-21-desktop-lan-webui-architecture-migration.md` | Implementation plan | Task 10 contract and verification gates |
| `AssetsManager/lan/dto.py` | DTO definitions | Runtime cursor and invalidation response shapes |
| `AssetsManager/lan/server.py` | Runtime/server bridge | Subscription lifecycle and broadcast scheduling |
| `AssetsManager/lan/api.py` | LAN API setup | Runtime callback registration and revision route wiring |
| `AssetsManager/lan/routes/websocket.py` | WebSocket route | Principal admission, ready message, cleanup |
| `tests/lan/test_runtime_realtime.py` | Task 10 regression suite | Runtime cursor, broadcast, auth and failure lifecycle contracts |
