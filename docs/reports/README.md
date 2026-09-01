# docs/reports 导航(README)

> 状态:**LIVING(导航)** · updated: 2026-09-02 · 本目录两层定位:① 分模块审查底稿(2026-08-10~11 P0/P1 轮,已蒸馏为 [`module-audit-distilled-2026-09-02.md`](module-audit-distilled-2026-09-02.md),原件归档至 `archive/2026-09/module-audits-superseded/`);② 08-29 起各会话产出报告的归流地。原 08-10~08-15 细扫描系列 12 份已于 2026-09-02 移入 `archive/2026-09/reports-superseded/`(结论被 08-29~09-02 评审取代)。报告正文内容零改写(2026-09-02 梳理轮仅追加状态头元数据)。全库功能分类导航见 [`docs/README.md`](../README.md),证据账本见 [`docs/compose/README.md`](../compose/README.md)。

## 文件清单(15 顶层 + 1 子目录)

### module-* 系列(已蒸馏为 1 份,2026-09-02 收敛轮)

> 2026-08-10~11 的 11 份 P0/P1 轮行号级模块排 Bug 审计底稿,全部发现项已于 2026-08-12 P2 轮修复或由后续评审关闭。**蒸馏产物**:[`module-audit-distilled-2026-09-02.md`](module-audit-distilled-2026-09-02.md)(模块汇总 + 主题索引 + 跨模块高频主题)。**原件**(11 份,零改写):`archive/2026-09/module-audits-superseded/`。

| 模块域 | 蒸馏后入口 |
|---|---|
| 资产/项目 / 商城订单配额 / 仓库层 P1 | module-audit-distilled §模块汇总 |
| database/db_migrations/schema_defs · settings/json_store/tag_library/project_data | module-audit-distilled §模块汇总 |
| FileOperation/Undo/Import | module-audit-distilled §主题索引(file-ops) |
| LAN 核心/路由/工具(扫描·隧道·WS) | module-audit-distilled §模块汇总 + §主题索引(lan-tools) |
| 完整性/维护服务 · Runtime 生命周期 | module-audit-distilled §模块汇总 |

### 08-15 评审系列 与 08-10/08-11 杂项(12 份,已归档)

`architecture-review-2026-08-15`、`file-list-architecture-review-2026-08-15`、`file-list-decomposition-plan-2026-08-15`、`file-list-refresh-audit-2026-08-15`、`panel-uiux-composition-audit-2026-08-15`、`ui-optimization-priority-2026-08-15`、`visual-drawing-audit-2026-08-15`、`desktop-fine-scan-2026-08-11`、`frontend-fine-scan-2026-08-11`、`menubar-review-2026-08-10`、`p2-round-2026-08-11`、`ui-rendering-audit-2026-08-10` —— 2026-09-02 移入 [`archive/2026-09/reports-superseded/`](../archive/2026-09/reports-superseded/),多数发现已由后续批次关闭或被 08-29~09-02 评审覆盖。

### 08-29 双端 UI/UX 评审系列(2 份)

`desktop-uiux-review-2026-08-29.md`(桌面端 M1–M7/L 项评审)、`webui-review-2026-08-29.md`(WebUI 评审)——对应方案见 `docs/plans/desktop-uiux-optimization-plan-2026-08-29.md`、`docs/plans/next-phase-design-2026-08-29.md`。

### 08-30 Serpent 对比与任务包研究系列(4 份,其中 2 份已蒸馏归档)

`serpent-reference-study-2026-08-30.md`、`serpent-vs-assetmanager-2026-08-30.md` —— 2026-09-02 蒸馏合并至 [`serpent-expert-analysis-distilled-2026-09-02.md`](serpent-expert-analysis-distilled-2026-09-02.md),原件移入 [`archive/2026-09/analysis-superseded/`](../archive/2026-09/analysis-superseded/);`task-package-research-2026-08-30.md`(任务包调研,已完结)、`t0-stabilization-summary-2026-08-30.md`(T0 稳定化总结,自 artifacts 归流)—— 已于 2026-09-02 收敛轮归档至 [`archive/2026-09/reports-superseded/`](../archive/2026-09/reports-superseded/)。

### 08-31 综合分析与专家评审系列(5 份,其中 4 份已蒸馏归档,1 份活跃)

`expert-panel-deep-analysis-2026-08-31.md`(五专家团深度评审,**活跃区,并行会话编辑中**,其第 5 行关联链接已随归档重写);`functional-analysis-and-serpent-comparison-2026-08-31.md`、`global-synthesis-analysis-2026-08-31.md`、`pm-capability-analysis-2026-08-31.md`、`project-analysis-2026-08-31.md` —— 2026-09-02 蒸馏合并至 [`serpent-expert-analysis-distilled-2026-09-02.md`](serpent-expert-analysis-distilled-2026-09-02.md),原件移入 [`archive/2026-09/analysis-superseded/`](../archive/2026-09/analysis-superseded/)。

### 09-01 审计与修复系列(4 份)

`architecture-function-and-reliability-review-2026-09-01.md`(当前架构权威复核,overview 头部指向本文)、`re-audit-2026-09-01.md`、`cleanup-and-git-repair-2026-09-01.md`(五轮工程垃圾清理与 git 对象库修复记录)、`task-package-validity-check-2026-09-01.md`(任务包时效性检验快照,已完结,2026-09-02 收敛轮归档至 [`archive/2026-09/reports-superseded/`](../archive/2026-09/reports-superseded/))。

### 09-02 完整盘点、交叉验证与文档梳理(2 份)

`inventory-cross-verification-2026-09-02.md`(主代理 + 4 专家子代理独立盘点与共享验证题交叉比对:仓库健康、0 密钥泄露、0 误提交垃圾、文档分类与失效链接、构建闭环缺口、`outputs/` 入库偏差);`docs-health-sweep-2026-09-02.md`(精简轮后全量健康度梳理:状态头补登 14 份、INDEX/导航/链接逐项核验、"总量 492→379"口径修正)。

### 子目录

- `deepseek-archive-2026-08-25/`(8 份)— DeepSeek Docs 选择性迁移的逐字副本,自带 INDEX 登记,勿改写链接。原目录已于 2026-09-02 整体迁至 `docs/baseline-2026-08-01/`。

## 与相邻证据的关系

- **查询状态请走**:`docs/full-review/**`(dated 快照 + manifest,进行中任务,勿动)。
- **查询会话证据请走**:`docs/archive/2026-09/compose-reports/`(98 份)。
- **08-01 基线审计走**:`docs/baseline-2026-08-01/`(原 DeepSeek Docs)。
- 本目录定位:08-11 module-* 审查底稿 + 08-29 起会话报告归流地;底稿多数发现已由后续批次关闭或登记。
