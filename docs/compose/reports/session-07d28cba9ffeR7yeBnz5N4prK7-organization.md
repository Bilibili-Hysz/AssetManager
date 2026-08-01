---
feature: session-07d28cba9ffeR7yeBnz5N4prK7-organization
status: historical_snapshot
branch: master
snapshot_head: pre-baseline working tree
superseded_by: repository-baseline-2026-08-01.md
---

# 本会话任务、代码与工作树整理报告（历史快照）

> 本文记录较早时间点的组织盘点，保留原始证据但不再作为当前任务状态入口。当前状态以 `repository-baseline-2026-08-01.md` 为准。

## 1. 整理范围与结论

本报告整理会话 `ses_07d28cba9ffeR7yeBnz5N4prK7` 在 `D:\~Vibe-Coding\Projects\AssetsManager_old-bak` 中留下的任务记录、代码变更、文档产物、测试证据和 Git 工作树状态。

本次采用“安全收口”策略：

- 已核对并关闭有明确后续完成证据的陈旧 `in_progress` 任务。
- 保留 `T151 blocked`、`T39/T102 abandoned` 等历史状态，不伪造完成。
- 在该历史快照时没有执行 `reset`、`checkout`、`clean`、删除、物理移动、提交、暂存或推送；随后基线整理已按新报告完成。
- 不把当前 dirty worktree 归因给单一任务；它包含多个此前阶段的用户改动和本会话延续的架构/WebUI/LAN 改动。

## 2. 任务总览

任务数据库中的本会话任务编号已延伸到 `T427`，其中包含主任务、带小数编号的子任务、审查项和修复项；本报告按阶段与关键任务链整理，逐条状态仍以任务数据库为准。任务主要分为以下阶段：

| 阶段 | 任务范围 | 结果 |
|---|---|---|
| 基线与稳定性 | `T1–T36` | 架构认知、稳定性基线、Day 1–7 验证、工具链与测试适配完成；保留可复现的 P2 风险记录 |
| 旧版 LAN WebUI 对齐 | `T37–T53` | 旧版功能迁移到 React WebUI，补齐下载、标签、分享、树导航、查看器和移动端语义 |
| 资源库工作区重构 | `T54–T171` | Gate 首页、三栏工作区、FileList 项目层级交互、预览池、InfoPanel、ImageViewer 与滚动边界完成 |
| 数据流审计与架构迁移 | `T172–T359` | Desktop–LAN–WebUI 数据流审计；`LibrarySession`/`LibraryRuntime`、DTO、principal、RuntimeEventRouter、React realtime provider 和 projection migration 完成 |
| Realtime hardening | `T370` 及其子任务 | WebSocket admission、授权撤销、shutdown truthfulness、failed-socket eviction、回调取消安全与跨端门禁完成 |
| 本次整理 | `T428` | 本报告、任务状态和工作树盘点完成 |

### 2.1 Realtime hardening 任务链

这是本会话最后收口的主线，已全部完成：

| 任务 | 内容 | 状态 |
|---|---|---|
| `T370.1` | WebSocket admission race | done |
| `T370.2` | WebSocket live authorization revocation | done |
| `T370.3` | LAN server shutdown state | done |
| `T370.4` | Startup rollback failed-future retry | done |
| `T370.5` | Failed socket eviction 与 presence cleanup | done |
| `T370.6–T370.7` | Direct/reservation callback predecessor cancellation shielding | done |
| `T370.8` | Hardening 相关 LAN 回归复现与收口 | done |
| `T370.9` | 最终跨端验收 | done |
| `T370.10` | 最终报告与证据 | done |
| `T427` | 最终只读 delivery review | done |

### 2.2 本次确认并收口的陈旧状态

这些任务原本仍显示 `in_progress`，但后续任务和报告已提供完成证据，因此本次安全关闭：

- `T124`：由 `T125` 完成跨项目缩略图缓存校验修复，`T126` 完成复审。
- `T172`、`T172.1–T172.4`：审计结果已汇总到 `T173`，并由 `T174` 形成架构改造计划。
- `T355`：由 `T356` 完成显式 LAN 无认证模式修复。

### 2.3 保留的非完成状态

- `T151 blocked`：这是该历史快照时的任务状态；后续 closeout 已提供 `209 passed` 证据并交付。
- `T39 abandoned`、`T102 abandoned`：历史放弃项保持原状态。

## 3. 代码与文件地图

### 3.1 核心架构与运行时

| 路径 | 作用/变更主题 |
|---|---|
| `AssetsManager/application/bootstrap.py` | canonical `LibrarySession`/`LibraryRuntime` 组装与生命周期入口 |
| `AssetsManager/application/runtime.py` | 缓存运行时与 session-bound service bundle |
| `AssetsManager/application/runtime_events.py` | runtime event/invalidation 路由基础设施 |
| `AssetsManager/application/context.py`、`library_service.py` | session/root/connection provider 边界 |
| `AssetsManager/application/asset_service.py`、`project_service.py` | Desktop/LAN 共用的资源与项目服务 |
| `AssetsManager/lan/dto.py` | 公共 LAN response DTO 契约 |
| `AssetsManager/lan/principal.py` | canonical `SessionPrincipal` 与 capability 边界 |
| `AssetsManager/lan/api.py`、`manager.py`、`security.py` | LAN 应用装配、路由与安全中间件 |
| `AssetsManager/lan/server.py` | runtime-only LAN server、metrics、auth、启动/停止状态机 |
| `AssetsManager/lan/ws.py` | WebSocket authority leases、admission、broadcast/heartbeat、eviction、close_all |
| `AssetsManager/lan/routes/websocket.py` | cookie-only authenticated WebSocket admission 与 runtime cursor barrier |
| `AssetsManager/lan/routes/*.py` | SPA/API 路由迁移到 runtime service bundle 和 DTO |
| `AssetsManager/widgets/lan_sharing.py` | 桌面端 LAN sharing 与 runtime 生命周期连接 |

### 3.2 React WebUI

| 路径 | 作用/变更主题 |
|---|---|
| `webui/src/App.tsx`、`webui/index.html` | SPA 入口、路由与主题/认证装配 |
| `webui/src/stores/AuthContext.tsx` | cookie-only auth、refresh、guest/protected navigation |
| `webui/src/stores/RealtimeContext.tsx` | `epoch + revision` cursor、gap recovery、provider fan-out |
| `webui/src/hooks/useWebSocket.ts` | WebSocket transport、reconnect、unmount 状态隔离 |
| `webui/src/hooks/useInvalidation.ts` | projection domain/path invalidation 消费接口 |
| `webui/src/api/*.ts`、`webui/src/types/api.ts` | HTTP API 与 DTO 类型契约 |
| `webui/src/pages/LandingPage.tsx` | Gate/resource-library 首页、preview pool、auth boundary |
| `webui/src/pages/BrowsePage.tsx`、`DetailPage.tsx` | 项目层级浏览、深链、详情与 projection 刷新 |
| `webui/src/components/files/*` | Grid/List、项目交互、标签过滤、批量下载、分层预览 |
| `webui/src/components/layout/*` | Sidebar、Header、InfoPanel、StatusBar、workspace layout |
| `webui/src/components/viewer/ImageViewer.tsx` | 图片查看器缩放、键盘、pointer/focus 生命周期 |
| `webui/src/index.css`、`LandingPage.css` | 主题、响应式与工作区视觉边界 |

### 3.3 测试与契约

| 路径 | 覆盖范围 |
|---|---|
| `tests/lan/test_lan_api.py` | LAN API、WebSocket manager、eviction、callback cancellation、presence/accounting |
| `tests/lan/test_runtime_realtime.py` | runtime cursor、admission race、revocation、epoch/revision、shutdown bridge |
| `tests/lan/test_server_lifecycle.py` | shutdown/join timeout、restart、startup cleanup retry、owner-loop 生命周期 |
| `tests/lan/test_public_contracts.py`、`test_t2_t4_contracts.py`、`test_role_permissions.py` | SPA、DTO、auth/query credential、capability 与权限契约 |
| `tests/unit/test_architecture_boundaries.py` | `DatabaseManager.current` 等架构边界 AST 门禁 |
| `tests/integration/test_runtime_events.py`、`test_*service.py` | runtime、事件、服务层集成契约 |
| `tests/e2e/test_webui_realtime_acceptance.py` | 真实 Chromium mutation/reconnect/revision-gap/epoch/teardown |
| `webui/src/**/*.test.ts(x)` | React 组件、auth、realtime、projection、交互与视觉契约 |
| `tests/contracts/lan_public_contracts.json` | LAN public contract fixture |

### 3.4 文档、规格与报告

当前目录盘点：

- `docs/compose/plans`：46 个计划文件。
- `docs/compose/specs`：23 个规格文件。
- `docs/compose/reports`：16 个报告文件。
- `docs/architecture.md`、`docs/architecture-diagram.md`：架构事实与数据流说明。
- `docs/adr/0003-library-runtime.md`：runtime/library lifecycle ADR。
- 本会话新增/确认的关键报告：
  - `docs/compose/reports/desktop-lan-webui-architecture-migration.md`
  - `docs/compose/reports/realtime-dataflow-hardening.md`
  - `docs/compose/reports/session-07d28cba9ffeR7yeBnz5N4prK7-organization.md`

## 4. 工作树状态

该节是历史快照：当时仓库为 `master` 的普通 Git 工作区。当前 Git 状态见基线报告。

`git status --short` 盘点结果：

| 状态 | 数量 | 说明 |
|---|---:|---|
| 已跟踪修改 | 100 | 包含架构、LAN、桌面、测试、React WebUI、构建与文档改动 |
| 删除 | 25 | 10 个 `.opencode` 历史文件，以及 15 个旧 `AssetsManager/lan/static/*` 文件 |
| 未跟踪 | 73 | runtime/DTO/principal、测试、React 新组件、计划/spec/report、`.mimocode` 等；包含本报告文件 |
| 总变更路径 | 198 | 不能在未分组/未确认前整体提交或清理 |

### 4.1 已跟踪修改的主要分区

- 构建与包边界：`.Cython&Noikta/*`、`AssetManager.spec`、`scripts/check_package_contents.py`。
- 核心/服务层：`AssetsManager/application/*`、`repositories/thumbnail_repository.py`。
- LAN：`AssetsManager/lan/*`，尤其 `server.py`、`ws.py`、`routes/*`。
- 桌面 UI：`AssetsManager/dialogs/*`、`widgets/lan_sharing.py`、i18n。
- 测试：`tests/core/*`、`tests/desktop/*`、`tests/integration/*`、`tests/lan/*`、`tests/unit/*`。
- React WebUI：`webui/src/App.tsx`、API、auth/realtime stores/hooks、pages、layout/files/viewer、测试与样式。

### 4.2 删除项的语义

- `.opencode/*` 删除项属于旧计划/旧代理指令树，未在本次整理中恢复或二次处理。
- `AssetsManager/lan/static/*` 删除项属于旧静态 LAN WebUI；当前 SPA 构建由 `webui/dist` 和 React route 提供，删除边界已由 package/contract tests 覆盖。

### 4.3 未跟踪项的语义

- 架构新增：`runtime.py`、`runtime_events.py`、`dto.py`、`principal.py`、ADR 和架构计划。
- 质量证据：`tests/e2e`、`tests/lan/test_runtime_realtime.py`、`test_server_lifecycle.py`、`tests/contracts`、runtime/library tests。
- React 新增：`RealtimeContext`、`useInvalidation`、`LayeredPreview`、Landing/Detail/CSS 测试等。
- Compose 产物：计划、规格、报告以及 `.mimocode` 配置/计划。

## 5. 验证证据

本会话最后收口的 fresh evidence：

| 验证 | 结果 |
|---|---|
| `python -m pytest tests/lan -q` | `314 passed` |
| realtime/security/architecture gate | `134 passed` |
| Chromium realtime acceptance | `4 passed` |
| WebUI full Vitest | `34 files, 256 passed` |
| WebUI realtime subset | `4 files, 67 passed` |
| WebUI typecheck | passed |
| WebUI production build | passed，1626 modules transformed |
| hardening-scoped Ruff | passed |
| `git diff --check` | passed |

已知但未在本次整理中修改的问题：

- `tests/lan/test_t2_t4_contracts.py:2` 存在已有未使用 `sqlite3` import；它不影响本次 hardening-scoped Ruff，因为被排除在该范围之外。
- React Router v7 future-flag warnings 仍会在部分测试 stderr 出现，但不是失败。
- Windows 环境无法运行依赖目录 symlink 的测试时，相关 skip 应保留并交由 Linux CI 覆盖。
- `T151 blocked` 仅保留为历史状态；后续 T151 closeout 已完成，不应把旧阻塞状态当作当前状态。

## 6. 后续建议

1. 以功能边界拆分提交：先提交 runtime/session/LAN 架构迁移，再提交 WebUI 迁移，最后提交文档与测试证据；不要把 198 个路径一次性提交。
2. 先对 `.opencode` 删除、旧 `lan/static` 删除、`.mimocode` 新增和各类 compose 文档做归属确认，再决定是否纳入版本控制。
3. 单独处理 `tests/lan/test_t2_t4_contracts.py` 的未使用 import；这属于独立质量清理，不要混入 realtime hardening 逻辑提交。
4. 对 `T151 blocked` 建立明确的解阻条件；对 `T39/T102` 仅保留历史 abandoned 记录即可。
5. 下一次提交前使用 `git diff --name-status` 和按目录的 `git diff --stat` 逐组检查，确保没有误将用户已有改动归入单一任务。

## 7. 收口决策

本历史快照完成了当时的任务盘点、陈旧状态收口、代码/文件地图和工作树报告。之后的提交与工作树收口不在本文时间点内；请使用当前基线报告。
