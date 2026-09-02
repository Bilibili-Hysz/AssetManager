# compose 证据账本导航(README)

> 状态:**LIVING(导航)** · updated: 2026-09-02 · 本目录是会话工作证据账本。**2026-09-02 精简批**:`reports/` 98 份原件整体移入 `docs/archive/2026-09/compose-reports/`(逐份登记于 archive INDEX);本目录现仅存蒸馏层。**2026-08-27 合并批**:specs/plans/handoffs 的 99 份原件已内容级合并为 `distilled/` 蒸馏层,原件移入 `docs/archive/2026-08/compose-raw/`(逐份登记于 archive INDEX,取代者=对应摘要)。**2026-09-02 收敛批**:`distilled/` 9 份「历史蒸馏(已完结会话摘要)」二次蒸馏合并为 [`compose-session-decisions-distilled-2026-09-02.md`](compose-session-decisions-distilled-2026-09-02.md),原件零改写归档至 `docs/archive/2026-09/compose-distilled-superseded/`。
> 检索规则:蒸馏层为日常入口;原件仅追溯用。**不执行**任何"不得执行未勾选项"的历史计划。

## 目录结构

| 子目录 | 说明 |
|---|---|
| `compose-session-decisions-distilled-2026-09-02.md` | **蒸馏层(9 份决策摘要,2026-08-27 生成;2026-09-02 二次蒸馏合并为 1 份):合并了原 specs/plans/handoffs 的信息量** |
| ~~reports/~~ | 98 份证据账本,2026-09-02 整体归档至 `docs/archive/2026-09/compose-reports/` |
| ~~specs/ plans/ handoffs/~~ | 原件已归档至 `docs/archive/2026-08/compose-raw/` |

## 蒸馏层(日常入口)

`distilled/` 9 份「历史蒸馏(已完结会话摘要)」已于 2026-09-02 收敛轮二次蒸馏合并为 **[`compose-session-decisions-distilled-2026-09-02.md`](compose-session-decisions-distilled-2026-09-02.md)**(按批次的「背景/决策要点/落地状态/仍生效约束」速查表,取代清单见该文档文末)。原件零改写归档至 `docs/archive/2026-09/compose-distilled-superseded/`。

| 批次 | 覆盖(原 99 份中的) |
|---|---|
| 2026-06-17~18 批:架构重构与主题系统 | 原 7 份 |
| 2026-06-19~21 批:背景效果/主题 UI/性能/分享/WebUI 视觉 | 原 12 份 |
| 2026-07-13 批:WebUI React 迁移与 LAN 安全修复 | 原 4 份 |
| 2026-07-15 批:投递安全/文件操作一致/LAN-WebUI 可靠/作用域服务 | 原 10 份 |
| 2026-07-17 批:渲染/元数据/主题稳定性 + 早期审计 | 原 7 份 |
| 2026-07-21 架构重定标批:Desktop-LAN-WebUI 分层与运行时 | 原 14 份 |
| 2026-07-21 功能/门禁子批 | 原 19 份 |
| 2026-07-24 批:WebUI 遗留清理与文件列表项目交互 | 原 6 份 |
| 2026-08-03~04 会话交接摘要(webui-02/desktop-ui-03/mainline-04) | 原 19 份 |

## reports/(98 份,已归档至 `docs/archive/2026-09/compose-reports/`)

以下系列检索表保留供按前缀定位;文件本体一律在 `docs/archive/2026-09/compose-reports/`:

按系列检索(全部为 07-21 之后证据):

| 系列 | 成员(文件名前缀) | 说明 |
|---|---|---|
| 基线 | `repository-baseline-2026-08-01`、`repository-followup-review-2026-08-01`、`2026-07-21-stability-baseline`、`2026-07-21-gate-home-react-migration`、`mainline-{parallel-batch-2026-08-04,audit-followup-2026-08-05}` | 08-01 基线盘点/Task A-E/迁移门 |
| 架构组装 | `desktop-lan-webui-architecture-{migration,recalibration,task-a,task-b,task-c,task-d}`、`a3-service-assembly-2026-08-02`、`b1-runtime-sharing-2026-08-03`、`realtime-dataflow-hardening`、`runtime-adapter-failure-ownership`、`desktop-ui-visual-closure-2026-08-01` | 分层迁移/DI 组装/实时链路证据 |
| G3-G9 | `g3e-raw-connection-compat-2026-08-05`、`g4-schema-lifecycle-2026-08-05`、`g5-search-error-contract-2026-08-06`、`g6-×9`、`g7-p1-safety-and-info-2026-08-06`、`g8-repository-error-contract-2026-08-06`、`g9-search-result-set-2026-08-06` | 08-05/06 硬化批次 |
| G10-G16(session binding) | `g10-project-session-binding` … `g16-tag-repository-session-binding`(均 2026-08-06) | 仓库会话绑定 |
| G17(31 份) | `g17-1..g17-17-*`(08-06~08-08);收尾件 `g17-stop-the-world-cutover-release-ownership-checklist-2026-08-08`、`g17-7-final-closure-2026-08-07` | 资产索引/对账队列完整证据链 |
| batch | `batch-a-delivery-safety`、`batch-b-file-operation-consistency`、`batch-c-lan-webui-reliability`、`batch-d-scoped-library-services` | 07-15 设计的落地报告 |
| task | `task-10-runtime-websocket-bridge` … `task-14-browser-realtime-acceptance` | WebUI 实时批次 |
| 会话账本 | `zcode-session-2026-08-11-*`、`zcode-session-2026-08-12-*`、`opencode-session-2026-08-10/11-*`、`session-07d28cba9ffeR7yeBnz5N4prK7-*` | 各会话实测账本(数字为当时快照) |
| webui | `webui-gap-analysis`、`webui-dependency-security-upgrade`、`webui-desktop-dataflow-audit`、`webui-migration-batch-commit-plan-2026-08-08`、`webui-migration-ownership-manifest-2026-08-08` | WebUI 迁移/审计 |
| 其他 | `lan-security-fixes`、`real-image-io-directory-benchmark-protocol-2026-08-04`、`ui-rendering-audit-2026-08-10`(复本,见 [`docs/archive/2026-09/reports-superseded/ui-rendering-audit-2026-08-10.md`](../archive/2026-09/reports-superseded/ui-rendering-audit-2026-08-10.md)) | 杂项/去重 |

## 归档原件(仅追溯)

原 `specs/`(25 份)、`plans/`(55 份)、`handoffs/`(19 份)原件位于 `docs/archive/2026-08/compose-raw/{specs,plans,handoffs}/`,每份的"原始路径 → 新路径 → 并入摘要"登记于 [`docs/archive/INDEX.md`](../archive/INDEX.md)。frozen 文档(如 ADR 0003)中指向 compose/plans 的历史链接以气味形式保留,解析请走 INDEX。