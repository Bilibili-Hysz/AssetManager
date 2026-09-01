---
feature: task-11-runtime-isolation
status: delivered
specs:
  - docs/compose/specs/2026-07-21-desktop-lan-webui-architecture-design.md
plans:
  - docs/compose/plans/2026-07-21-desktop-lan-webui-architecture-migration.md
branch: working-tree
commits: uncommitted
---

# Task 11 — Runtime Isolation and Restart Final Report

## What Was Built

Task 11 建立了 Runtime/WebSocket 的库切换、同路径重开、LAN restart 和停机竞态
验收护栏。关闭 Runtime A 后重新打开同一 library root 会得到新的 epoch 和新的
revision 游标；携带 A 的旧 session token/root 的事件不会污染 Runtime B 或其
WebSocket 客户端。

同一个 live Runtime 反复停止和启动 LAN server 时，Runtime subscription 始终
保持 exactly one，事件只广播一次；cleanup 后旧 subscription 会被关闭，旧 loop
和 stale callback 不再继续调度广播。

## Architecture

LAN realtime 生命周期现在由统一的 gate-stop helper 管理。`stop_runtime_realtime`
先在 gate 内停止接收、等待已经进入跨线程调度区段的 callback 完成，再在 gate
外关闭 subscription；随后才关闭 WebSocket、site 和 runner。aiohttp cleanup 与
`_LanServerImpl._shutdown()` 复用同一流程，避免两套 teardown 语义漂移。

startup 会为每次新 server loop 创建新的 gate、loop 引用和 active 状态，并建立
唯一 Runtime subscription。cleanup 后重新启动不会复用旧 gate 或旧 loop。

## Design Decisions

- 选择 epoch 与 session token/root 双重隔离，因为仅比较 library root 无法区分同一路径
  的先后两次 Runtime 生命周期。
- 选择在 `on_invalidation` 从 active 检查到 `run_coroutine_threadsafe` 提交之间持有
  生命周期 gate，因为普通布尔检查无法防止 cleanup 线程插入 TOCTOU 窗口。
- 选择让 server shutdown 和 aiohttp cleanup 调用同一个停止 helper，因为真实
  `_shutdown()` 可能早于 runner cleanup 执行，不能依赖后续 callback 才关闭 realtime。
- 保留用户已有 WebUI 改动，不把 Task 12 的客户端变更混入 Task 11，也不在本任务
  实现 React RealtimeProvider。

## Usage

Runtime 与 LAN server 的正常生命周期无需新增调用方 API。启动时自动建立实时订阅，
停止或 cleanup 时自动关闭；同一 Runtime 可以安全地 stop/start。

Task 11 验收覆盖：

- same-root Runtime reopen
- old token/root event rejection
- live Runtime LAN restart
- single subscription/single broadcast
- callback 与 cleanup 的交错停机
- server `_shutdown()` 期间不再提交 stale broadcast

## Verification

- Runtime event integration：`25 passed`
- LAN realtime/API：`173 passed`
- Window/session + LAN sharing：`29 passed`
- Integration + LAN：`582 passed, 1 skipped`
- WebUI tests：`221 passed`
- WebUI typecheck：通过
- WebUI production build：通过
- Ruff：通过
- `compileall -q AssetsManager/lan`：通过
- scoped `git diff --check`：通过
- 独立 defect-first review：无 P0/P1/P2

跳过项是 Windows 平台不支持目录 symlink 的既有测试，不属于 Task 11 回归。

## Journey Log

- [lesson] 仅使用 `_realtime_active` 布尔值无法覆盖 active 检查到 coroutine 提交之间
  的并发窗口，必须用同一 gate 保护完整调度区段。
- [pivot] 将 aiohttp cleanup 与真实 server `_shutdown()` 收敛到同一个 gate-stop/drain
  helper，避免 server teardown 早于 app cleanup 时残留 stale callback。
- [lesson] 重启验证必须同时检查 subscription count、broadcast 次数和 cleanup 后旧
  callback 行为，单独检查连接可用性不足以证明生命周期隔离。

## Source Materials

| File | Role | Notes |
|------|------|-------|
| `docs/compose/specs/2026-07-21-desktop-lan-webui-architecture-design.md` | Architecture specification | Runtime epoch, event isolation and adapter lifecycle |
| `docs/compose/plans/2026-07-21-desktop-lan-webui-architecture-migration.md` | Implementation plan | Task 11 release gates |
| `AssetsManager/lan/api.py` | Realtime lifecycle gate | Shared startup/cleanup and callback dispatch guard |
| `AssetsManager/lan/server.py` | Server teardown | Shutdown invokes the shared realtime stop path |
| `tests/lan/test_runtime_realtime.py` | Realtime isolation suite | Reopen, restart and shutdown race tests |
| `tests/unit/test_lan_sharing.py` | Desktop LAN lifecycle tests | Runtime and sharing compatibility coverage |
