# docs 目录导航（按功能分类）

> 状态：LIVING · updated: 2026-09-02
> 本文件是 `docs/` 的功能分类索引：回答"我要的信息在哪类文档里"。各目录内部的细粒度导航见各自的 README/INDEX。

## 按功能分类

### 1. 当前事实（LIVING，日常查阅入口）

| 文档 | 职责 |
|---|---|
| [`architecture.md`](architecture.md) | 当前架构与模块职责（权威） |
| [`architecture-diagram.md`](architecture-diagram.md) | 架构图（文本版） |
| [`migrations.md`](migrations.md) | 数据库迁移版本账本 |
| [`development.md`](development.md) | 开发规则与工程约定 |
| [`testing.md`](testing.md) | 测试策略与门禁 |
| [`lan-security.md`](lan-security.md) | LAN 服务安全模型 |
| [`perf-baseline-2026-08-29.md`](perf-baseline-2026-08-29.md) | 性能基线（dated 实测） |
| [`adr/`](adr/) | 架构决策记录（0001~0005） |
| [`overview-2026-08-27.md`](overview-2026-08-27.md) | 全库结构地图（DATED SNAPSHOT，08-27 实测，语料考古入口） |

### 2. 08-01 基线审计与规划（FROZEN）

[`baseline-2026-08-01/`](baseline-2026-08-01/README.md)（原仓库根 `DeepSeek Docs/`，2026-09-02 整体迁入，内容零改写）：

| 子集 | 功能 |
|---|---|
| `01~10-*.md` | 10 章逐层架构走查（总览/启动链/应用服务/基础设施/领域与数据/LAN/桌面 UI/WebUI 与插件/端到端数据流/风险建议） |
| `交接文档-2026-08-13*.md` | 会话交接（dated） |
| `施行路线图.md` | 08-01 时点路线图 |
| [`架构与设计评价/`](baseline-2026-08-01/架构与设计评价/README.md) | 前端/后端/UI·UX/工程质量/可扩展性/前后端分离评价 |
| [`功能缺口分析/`](baseline-2026-08-01/功能缺口分析/README.md) | 桌面/服务与数据/LAN/WebUI/安全缺口 + 优先级路线图 |
| [`前后端分离改造计划/`](baseline-2026-08-01/前后端分离改造计划/README.md) | 方案利弊、推荐实施计划、验收标准与风险预案 |
| [`插件API设计规划/`](baseline-2026-08-01/插件API设计规划/README.md) | 现状审计、Blender 启示、目标 API 规范、兼容迁移、验收 |
| [`未来方向/`](baseline-2026-08-01/未来方向/README.md) | 店铺/商业化/橱窗 UI/桌面视觉/技术路线/性能优化方向 |

红线：内容不改写；数字断言均为 08-01 历史快照。

### 3. 审计与评审（FROZEN / dated）

| 目录 | 职责 |
|---|---|
| [`full-review/`](full-review/) | 08-21 起的 dated 审计快照与批次证据（进行中，勿动） |
| [`deep-weakness-audit-2026-08-22/`](deep-weakness-audit-2026-08-22/) | 08-22 全领域弱审计（130 条发现 + Top-30） |

### 4. 方案与计划（plans）

[`plans/`](plans/) —— 改造方案与任务包，11 份现行：`architecture-reliability-roadmap-2026-08-31.md`（H1 实施中）、`task-package-2026-09-01.md`（交托手册 v2）、`p0-security-remediation-2026-08-31.md`（提案，未实施）、`port-architecture-2026-08-30.md`（分期实施）、`evolution-strategy-2026-08-31.md`、`development-roadmap-2026-08-30.md`、`ux-improvement-plan-2026-08-30.md`（未实施）、`desktop-uiux-optimization-plan-2026-08-29.md`、`next-phase-design-2026-08-29.md`、`bg-gpu-shader-architecture-2026-08-27.md`（M1 已落地；范围收窄注记见其头部，原 `bg-simplify-image-only-2026-08-28.md` 已并入本文）、`workspace-cleanup-plan-2026-08-31.md`（阶段 0 完毕）。已执行完毕/被取代的 4 份（`build-closure-remediation-plan-2026-09-02`、`documentation-maintenance-plan-2026-08-27`、`task-package-2026-08-30`、`bg-simplify-image-only-2026-08-28`）于 2026-09-02 移入 [`archive/2026-09/plans-done/`](archive/2026-09/plans-done/)。

### 5. 证据账本（compose）

[`compose/`](compose/README.md) —— 多智能体工作证据：现仅 `distilled/`（9 份决策摘要，日常入口）。原 `reports/`（98 份会话报告）于 2026-09-02 整体移入 [`archive/2026-09/compose-reports/`](archive/2026-09/compose-reports/)；更早的 specs/plans/handoffs 原件在 `archive/2026-08/compose-raw/`。

### 6. 报告归流（reports）

[`reports/`](reports/) —— 会话产出报告的归流地（08-29 起评审/专家分析系列 + module-* 分模块审查底稿，如 `cleanup-and-git-repair-2026-09-01.md`、`expert-panel-deep-analysis-2026-08-31.md`、`deepseek-archive-2026-08-25/`）。已被 08-29~09-02 评审取代的 12 份 08-10~08-15 细扫描于 2026-09-02 移入 [`archive/2026-09/reports-superseded/`](archive/2026-09/reports-superseded/)。

### 7. 图示（diagrams）

[`diagrams/`](diagrams/) —— 独立图源文件。

### 8. 归档（ARCHIVED）

[`archive/`](archive/INDEX.md) —— 已执行完毕/被取代的历史文档，逐份登记于 `archive/INDEX.md`；溯源优先查 INDEX。

## 快速路由

- "系统现在是什么样" → `architecture.md` + `architecture-diagram.md`
- "数据库现在有哪些版本/迁移" → `migrations.md`
- "当年 08-01 审计怎么评价这个项目" → `baseline-2026-08-01/`
- "已知弱点清单" → `deep-weakness-audit-2026-08-22/`
- "接下来做什么" → `plans/`
- "某次会话/某轮工作的证据" → `reports/`、`archive/2026-09/compose-reports/`、`archive/INDEX.md`
