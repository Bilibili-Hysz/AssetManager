---
feature: task-12-realtime-provider
status: delivered
specs:
  - docs/compose/specs/2026-07-21-desktop-lan-webui-architecture-design.md
plans:
  - docs/compose/plans/2026-07-21-desktop-lan-webui-architecture-migration.md
branch: working-tree
commits: uncommitted
---

# Task 12 — RealtimeProvider and Cursor Recovery Final Report

## What Was Built

Task 12 建立了统一的 React `RealtimeProvider` 和 projection cursor 状态机。Provider
消费同源 cookie 认证的 `/api/revision`、`runtime_ready` 和
`projection_invalidated`，向多个 WebSocket consumer 提供一个共享 transport，
并暴露 `status`、`epoch`、`revision`、`recover()` 与
`registerInvalidation(domains, callback)`。

Provider 能识别顺序事件、重复事件、revision gap、Runtime epoch 切换和断线重连。
恢复请求具备 generation、epoch、cursor 和 promise identity 防护；stale response
不会覆盖当前游标。若恢复期间 gap intent 仍未覆盖，会进行最多一次补偿恢复，避免
永久停留在缺口或无限重试。

## Architecture

`App.tsx` 在 `AuthProvider` 内挂载单一 `RealtimeProvider`。Provider 根据 canonical
principal 的 realtime capability 和 opaque identity 管理一个
`WebSocketTransportHost`。现有页面级 `useWebSocket` consumer 在 Provider 内
通过 transport bridge 复用该物理连接，consumer 卸载只取消自身 listener，不关闭
Provider transport；Provider 卸载才关闭实际 socket。Provider 外部仍保留
standalone `useWebSocket` 兼容行为。

cursor 状态机遵循以下规则：

- 同 epoch 的 lower/equal `runtime_ready` 忽略；newer ready 触发恢复；
- 新 epoch 始终替换 cursor，并至少触发一次 projection recovery/fan-out；
- 同 epoch 的连续 revision 才直接投递；重复或旧 revision 忽略；
- revision gap 触发去重后的 HTTP recovery；
- recovery response 必须保持 epoch/revision 单调；stale response 不回写；
- gap intent 在必要时最多执行一次补偿 recovery；
- 每个 projection callback 独立隔离异常。

## Design Decisions

- 选择在 `useWebSocket` 内部提供 transport bridge，因为这样可以让尚未迁移的旧
  consumer 复用 Provider socket，同时避免 `RealtimeContext` 与 hook 形成循环依赖。
- 选择使用 `AuthContext.principal` 的 opaque identity 作为 transport 重建条件，
  因为两个连续用户都具备 realtime capability 时，单纯 boolean 依赖无法替换旧认证
  会话；identity key 不包含 token。
- 选择把 epoch 变化视为完整 projection invalidation，即使 `/api/revision` 返回
  相同 revision，也必须通知 projection 刷新旧库快照。
- 选择每个 recovery intent 最多一次补偿请求，因为 stale HTTP snapshot 需要一次
  再尝试，但无限重试会把断线状态变成客户端请求风暴。

## Usage

Provider consumer 可以注册 projection invalidation：

```tsx
const { status, epoch, revision, registerInvalidation, recover } = useRealtime();

useEffect(() => {
  return registerInvalidation(['files', 'tree'], () => {
    void reloadAuthoritativeSnapshot();
  });
}, [registerInvalidation]);
```

当前任务只建立统一 Provider、transport bridge 和 cursor recovery。BrowsePage、
StatusBar 及其它页面的业务刷新逻辑迁移到 `useInvalidation` 属于 Task 13，尚未在
本任务实现；工作区中已有的页面 dirty changes 被保留且未归因到 Task 12。

## Verification

- Focused WebUI tests：34 passed
- Full WebUI tests：32 files，243 passed
- WebUI typecheck：通过
- WebUI production build：通过
- LAN realtime/API：173 passed
- Integration + LAN：582 passed，1 skipped
- Ruff：通过
- scoped `git diff --check`：通过
- 独立 defect-first review：无 P0/P1/P2

跳过项是 Windows 平台不支持目录 symlink 的既有测试，不属于 Task 12 回归。

## Journey Log

- [lesson] Provider 接入不能只看自身是否创建一个 socket；旧 consumer 仍可能创建
  额外 transport，因此必须提供 bridge 或完成页面迁移门槛。
- [lesson] `runtime_ready` 同时承担重连期间 revision cursor 更新和 Runtime epoch
  切换信号；两种情况都需要 projection recovery 语义。
- [lesson] recovery 的 stale 判断必须覆盖 epoch、generation、请求起点、当前 cursor
  和 gap intent，且要限制补偿次数。
- [lesson] 每个 bridge/recovery callback 都必须独立隔离异常，避免一个消费者阻断
  其他 projection 的刷新。

## Source Materials

| File | Role | Notes |
|------|------|-------|
| `docs/compose/specs/2026-07-21-desktop-lan-webui-architecture-design.md` | Architecture specification | Defines projection invalidation and recovery boundary |
| `docs/compose/plans/2026-07-21-desktop-lan-webui-architecture-migration.md` | Implementation plan | Task 12 provider/cursor contract |
| `webui/src/stores/RealtimeContext.tsx` | Provider/state machine | Cursor, recovery, registration and transport host |
| `webui/src/hooks/useInvalidation.ts` | Consumer hook | Projection registration surface |
| `webui/src/hooks/useWebSocket.ts` | Transport/bridge hook | Standalone and Provider-owned transport behavior |
| `webui/src/App.tsx` | Application integration | Single Provider mount under AuthProvider |
| `webui/src/stores/RealtimeContext.test.tsx` | Provider regression suite | Epoch, gap, recovery, bridge and lifecycle tests |
