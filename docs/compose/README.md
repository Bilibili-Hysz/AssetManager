# compose 证据账本导航(README)

> 状态:**LIVING(导航)** · updated: 2026-08-27 · 本目录 197 份文档是会话工作证据账本,按仓库纪律**内容零改写**;本文件只负责导航与归档状态标注。
> 检索规则:文件名即日期前缀(如 `2026-07-21-...`);无日期前缀的文件以内容日期为准。**不执行**任何"不得执行未勾选项"的历史计划(其头部自带 Historical-plan rule)。

## 目录结构

| 子目录 | 文件数 | 性质 |
|---|---|---|
| `specs/` | 25 | 设计契约(design);07-21 前 14 份已加 ARCHIVED 头 |
| `plans/` | 55 | 执行计划;07-21 前 24 份 + 2 份无日期已加 ARCHIVED 头 |
| `reports/` | 98 | **证据账本主体**(全部为 07-21 之后/参照,零改动) |
| `handoffs/` | 19 | 08-03/08-04 三个会话交接包(零改动) |

## specs/(25)

### 现行参考(07-21 起,11 份)
- `2026-07-21-desktop-lan-webui-architecture-recalibration-design.md` — recalibration 契约(基线门/任务处置表,当前架构口径的来源)
- `2026-07-21-runtime-event-router-design.md`、`2026-07-21-layered-preview-pool-design.md` — 事件路由/预览池设计
- `2026-07-21-{architecture-design,architecture-closure-design,project-library-workspace-design,realtime-dataflow-hardening,webui-workspace-redesign-design,weekly-stability-closure-design}.md` — 07-21 架构与稳定批
- `2026-07-24-webui-legacy-cleanup-design.md`、`2026-07-24-filelist-project-interaction-design.md` — 07-24 批

### ARCHIVED(07-21 前,14 份,已加头)
`2026-06-17-refactor-architecture-design`、`2026-06-18-{custom-theme-system,theme-editor-phase2}`、`2026-06-19-{background-enhancement,theme-ui-redesign}`、`2026-06-20-{performance-optimization,sharing-ui-redesign}`、`2026-06-21-{share-system-redesign,web-ui-visual-upgrade}`、`2026-07-13-webui-react-design`、`2026-07-15-{batch-a-delivery-safety,batch-b-file-operation-consistency,batch-d-scoped-library-services,lan-webui-reliability}-design`

## plans/(55)

### 现行参考(07-21 起,29 份)
- `2026-07-21-desktop-lan-webui-architecture-recalibration.md` — **唯一可执行任务链**(各批次执行入口)
- `2026-07-21-desktop-lan-webui-architecture-{migration,task-d}.md` — 迁移主线(Historical-plan rule 只追溯)与 Task D
- `2026-07-21-{gate-*,infopanel-*,lan-no-auth-login,layered-preview-pool,legacy-infopanel-project-preview,preview-gate-responsive-recovery,project-library-workspace,public-theme-setter,realtime-dataflow-hardening,runtime-adapter-failure-ownership,runtime-event-router-implementation,session-close-lan-websocket-regression,webui-*,weekly-stability-closure,window-*}.md` — 07-21 各子批
- `2026-07-24-{filelist-project-interaction,gate-workspace-preview-responsive-fix,theme-infopanel-preview,webui-legacy-cleanup}.md` — 07-24 批

### ARCHIVED(07-21 前 24 份 + 2 份无日期,已加头)
- 06-17/06-18/06-19/06-20/06-21 系列(10 份,与 specs 同名对应的执行计划)
- `2026-07-13-{lan-security-fixes,localized-view-mode-stable-id,webui-react-plan}`(3)
- `2026-07-15-{anchor-worktree,batch-a-delivery-safety,batch-b-file-operation-consistency,batch-c-lan-webui-reliability,batch-d-scoped-library-services,lan-webui-reliability}`(6)
- `2026-07-17-{lan-first-image-linear-scan,metadata-combined-read,smooth-scroll-thumbnail-timing,theme-transition-stability,zoom-grid-relayout}`(5)
- `lan-error-audit.md`、`p1-audit-findings.md`(无日期,06-17 内容日,结论"S 级 SAFE";仅追溯)

## reports/(98,零改动)

按系列检索(全部为 07-21 之后证据):

| 系列 | 成员(文件名前缀) | 说明 |
|---|---|---|
| 基线 | `repository-baseline-2026-08-01`、`repository-followup-review-2026-08-01`、`2026-07-21-stability-baseline`、`2026-07-21-gate-home-react-migration`、`mainline-{parallel-batch-2026-08-04,audit-followup-2026-08-05}` | 08-01 基线盘点/Task A-E/迁移门 |
| 架构组装 | `desktop-lan-webui-architecture-{migration,recalibration,task-a,task-b,task-c,task-d}`、`a3-service-assembly-2026-08-02`、`b1-runtime-sharing-2026-08-03`、`realtime-dataflow-hardening`、`runtime-adapter-failure-ownership`、`desktop-ui-visual-closure-2026-08-01` | 分层迁移/DI 组装/实时链路证据 |
| G3-G9 | `g3e-raw-connection-compat-2026-08-05`、`g4-schema-lifecycle-2026-08-05`、`g5-search-error-contract-2026-08-06`、`g6-×9(backup/metadata-export/orphan-quarantine/product-entry/restore/integrity/security-preflight×2/lan-fallback)`、`g7-p1-safety-and-info-2026-08-06`、`g8-repository-error-contract-2026-08-06`、`g9-search-result-set-2026-08-06` | 08-05/06 硬化批次 |
| G10-G16(session binding) | `g10-project-session-binding`、`g11-core-store-session-binding`、`g12-auth-share-session-contract`、`g13-auth-share-repository-session-binding`、`g14-auth-share-strict-repository-hardening`、`g15-metadata-repository-session-binding`、`g16-tag-repository-session-binding`(均 2026-08-06) | 仓库会话绑定 |
| G17(31 份) | `g17-1..g17-17-*` 系列(08-06~08-08),收尾件:`g17-stop-the-world-cutover-release-ownership-checklist-2026-08-08`、`g17-7-final-closure-2026-08-07` | 资产索引/对账队列完整证据链 |
| batch | `batch-a-delivery-safety`、`batch-b-file-operation-consistency`、`batch-c-lan-webui-reliability`、`batch-d-scoped-library-services` | 07-15 设想的落地报告 |
| task | `task-10-runtime-websocket-bridge`、`task-11-runtime-isolation`、`task-12-realtime-provider`、`task-13-projection-migration`、`task-14-browser-realtime-acceptance` | WebUI 实时批次 |
| 会话账本 | `zcode-session-2026-08-11-{desktop-fine-scan,frontend-scan,low-batch-1-lan-auth,p1-round,p2-round,summary}`、`zcode-session-2026-08-12-{dev-plan-rounds,low-priority-rounds}`、`opencode-session-2026-08-10-{startup,summary}`、`opencode-session-2026-08-11-{startup,summary}`、`session-07d28cba9ffeR7yeBnz5N4prK7-{final,organization}` | 各会话实测账本(数字为当时快照) |
| webui | `webui-gap-analysis`、`webui-dependency-security-upgrade`、`webui-desktop-dataflow-audit`、`webui-migration-batch-commit-plan-2026-08-08`、`webui-migration-ownership-manifest-2026-08-08` | WebUI 迁移/审计 |
| 其他 | `lan-security-fixes`、`real-image-io-directory-benchmark-protocol-2026-08-04`、`ui-rendering-audit-2026-08-10`(复本,见 [`docs/reports/ui-rendering-audit-2026-08-10.md`](../reports/ui-rendering-audit-2026-08-10.md)) | 杂项/去重 |

## handoffs/(19,零改动)

- `webui-session-02-2026-08-03/`(11 份)— WebUI 会话交接包(当前状态/架构/契约/文件映射/积压/验证/风险/视觉系统/路线图)
- `desktop-ui-session-03-2026-08-04/`(6 份)— 桌面表现层任务包与职责切分
- `assetsmanager-mainline-session-04-2026-08-04/`(2 份)— 主线程会话交接

> 已知工程限制:handoffs 部分文件硬编码外置 Git 元数据绝对路径(`C:\Users\...\.codex\...`),跨机失效。