# docs/reports 导航(README)

> 状态:**LIVING(导航)** · updated: 2026-08-27 · 本目录是 08-10~08-15 的审查报告集合(module-* 分模块系列 + 08-15 评审系列),属 **full-review 之前的最后行号级证据**;内容零改写。全库文档导航见 `docs/overview-2026-08-27.md` §21,证据账本见 [`docs/compose/README.md`](../compose/README.md)。

## 文件清单(23 顶层 + 1 子目录)

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

### 子目录

- `deepseek-archive-2026-08-25/`(8 份)— DeepSeek Docs 选择性迁移的逐字副本,自带 INDEX 登记,勿改写链接。

## 与相邻证据的关系

- **查询状态请走**:`docs/full-review/**`(dated 快照 + manifest,进行中任务,勿动)。
- **查询会话证据请走**:`docs/compose/reports/`(98 份)。
- 本目录定位:full-review 之前(08-10~08-15)的行号级审查底稿;多数发现已由后续批次关闭或登记。