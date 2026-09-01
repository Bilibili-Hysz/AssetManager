# docs/reports 导航(README)

> 状态:**LIVING(导航)** · updated: 2026-09-02 · 本目录两层定位:① 08-10~08-15 的行号级审查底稿(module-* 系列 + 08-15 评审系列,full-review 之前的最后证据);② 08-29 起各会话产出报告的归流地。报告正文内容零改写。全库功能分类导航见 [`docs/README.md`](../README.md),证据账本见 [`docs/compose/README.md`](../compose/README.md)。

## 文件清单(40 顶层 + 1 子目录)

### module-* 系列(11 份,2026-08-11 分模块审查,P1 第一轮)

| 文件 | 模块域 |
|---|---|
| `module-assets-p1.md` | 资产/项目服务(19 项缺陷,如 M6a-9 重扫永不收敛) |
| `module-commerce-p1.md` | 商城/订单/配额 P1 |
| `module-core-db.md` | database/db_migrations/schema_defs |
| `module-core-store.md` | settings/json_store/tag_library/project_data |
| `module-file-ops.md` | FileOperation/Undo/Import |
| `module-lan-core.md` | LAN 服务器核心(含 NUL/ADS 低危待办,Bug8/9 已由 08-12 批次关闭) |
| `module-lan-routes.md` / `module-lan-tools.md` | LAN 路由层 / 工具(扫描/隧道/WS) |
| `module-maintenance.md` | 完整性/维护服务 |
| `module-repositories-p1.md` / `module-runtime.md` | 仓库层 P1 / Runtime 生命周期 |

### 08-15 评审系列(7 份)

`architecture-review-2026-08-15`、`file-list-architecture-review-2026-08-15`、`file-list-decomposition-plan-2026-08-15`(file_list 拆分方案,后续已落地)、`file-list-refresh-audit-2026-08-15`、`panel-uiux-composition-audit-2026-08-15`、`ui-optimization-priority-2026-08-15`、`visual-drawing-audit-2026-08-15`

### 08-10/08-11 杂项(5 份)

`desktop-fine-scan-2026-08-11`、`frontend-fine-scan-2026-08-11`(前端 75 项扫描,已全部修复)、`menubar-review-2026-08-10`、`p2-round-2026-08-11`、`ui-rendering-audit-2026-08-10`(**本目录为权威复本**;compose/reports 下的同名文件仅作证据保留)

### 08-29 双端 UI/UX 评审系列(2 份)

`desktop-uiux-review-2026-08-29.md`(桌面端 M1–M7/L 项评审)、`webui-review-2026-08-29.md`(WebUI 评审)——对应方案见 `docs/plans/desktop-uiux-optimization-plan-2026-08-29.md`、`docs/plans/next-phase-design-2026-08-29.md`。

### 08-30 Serpent 对比与任务包研究系列(4 份)

`serpent-reference-study-2026-08-30.md`(参考项目研究)、`serpent-vs-assetmanager-2026-08-30.md`(能力对比)、`task-package-research-2026-08-30.md`(任务包调研)、`t0-stabilization-summary-2026-08-30.md`(T0 稳定化总结,自 artifacts 归流)。

### 08-31 综合分析与专家评审系列(5 份)

`expert-panel-deep-analysis-2026-08-31.md`(五专家团深度评审)、`functional-analysis-and-serpent-comparison-2026-08-31.md`、`global-synthesis-analysis-2026-08-31.md`、`pm-capability-analysis-2026-08-31.md`、`project-analysis-2026-08-31.md`。

### 09-01 审计与修复系列(4 份)

`architecture-function-and-reliability-review-2026-09-01.md`(当前架构权威复核,overview 头部指向本文)、`re-audit-2026-09-01.md`、`cleanup-and-git-repair-2026-09-01.md`(五轮工程垃圾清理与 git 对象库修复记录)、`task-package-validity-check-2026-09-01.md`。

### 09-02 完整盘点与多专家交叉验证(1 份)

`inventory-cross-verification-2026-09-02.md`(主代理 + 4 专家子代理独立盘点与共享验证题交叉比对:仓库健康、0 密钥泄露、0 误提交垃圾、文档分类与失效链接、构建闭环缺口、`outputs/` 入库偏差)。

### 子目录

- `deepseek-archive-2026-08-25/`(8 份)— DeepSeek Docs 选择性迁移的逐字副本,自带 INDEX 登记,勿改写链接。原目录已于 2026-09-02 整体迁至 `docs/baseline-2026-08-01/`。

## 与相邻证据的关系

- **查询状态请走**:`docs/full-review/**`(dated 快照 + manifest,进行中任务,勿动)。
- **查询会话证据请走**:`docs/compose/reports/`(98 份)。
- **08-01 基线审计走**:`docs/baseline-2026-08-01/`(原 DeepSeek Docs)。
- 本目录定位:08-10~08-15 行号级审查底稿 + 08-29 起会话报告归流地;底稿多数发现已由后续批次关闭或登记。
