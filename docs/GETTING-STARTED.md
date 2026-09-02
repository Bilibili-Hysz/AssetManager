# AssetsManager 项目文档 · 阅读指南

> 状态：LIVING · updated: 2026-09-02
> 本文件是新人的单一入口；完整的「按功能分类」地图见 [`docs/README.md`](README.md)。

## 这是什么项目

**AssetsManager** 是一个**本地优先（local-first）的素材库管理工具**，用于采集、整理、检索个人/团队的图片与媒体资产。

- **桌面端**：PySide6（Python），承载主交互与本地文件治理。
- **Web 端**：React + TypeScript（`webui/`），与桌面端共享同一套后端/领域模型，提供远程浏览与操作。
- **服务端**：内置 LAN 服务（`AssetsManager/lan/`），桌面与 Web 双端都通过它访问资产，前后端通过契约（`contracts.ts`）解耦。

文档树经过 2026-08~09 的收敛整理：活跃文档约 50 份，历史/被取代证据约 210 份迁入 `docs/archive/`，全部在 [`docs/archive/INDEX.md`](archive/INDEX.md) 逐份登记，可溯源。

## 30 秒阅读路径

1. **项目现在是什么样** → [`docs/overview-2026-08-27.md`](overview-2026-08-27.md)（全库结构快照）+ [`docs/architecture.md`](architecture.md)（当前架构与模块职责，权威）+ [`docs/architecture-diagram.md`](architecture-diagram.md)（文本架构图）。
2. **数据库有哪些版本/迁移** → [`docs/migrations.md`](migrations.md)。
3. **怎么开发、怎么测试** → [`docs/development.md`](development.md) + [`docs/testing.md`](testing.md)。
4. **关键架构决策（为什么这么做）** → [`docs/adr/`](adr/)（0001~0005）。
5. **接下来做什么** → [`docs/plans/`](plans/)（11 份现行改造方案与任务包）。
6. **这次会话/这轮工作的证据** → [`docs/reports/`](reports/) + [`docs/compose/`](compose/) + [`docs/full-review/`](full-review/)。

## 文档的三层状态（必读纪律）

| 状态 | 含义 | 去哪看 |
|---|---|---|
| **LIVING** | 当前事实，日常查阅入口，带 `updated:` 头部 | `architecture.md` / `development.md` / `testing.md` / `adr/` / `docs/README.md` 等 |
| **FROZEN** | 历史快照/审计结论，**内容不改写**，数字断言均为当时时点 | `docs/archive/2026-09/baseline-2026-08-01/`、`docs/archive/2026-09/deep-weakness-audit-2026-08-22/`、`docs/full-review/` |
| **ARCHIVED** | 已执行完毕/被取代/去重原件，逐份登记 | [`docs/archive/INDEX.md`](archive/INDEX.md)（优先走 INDEX 溯源） |

红线：**FROZEN 簇内容零改写**；ARCHIVED 取回须删登记行。

## 按问题路由

| 我想知道… | 读 |
|---|---|
| 系统现在长什么样 | `architecture.md` + `architecture-diagram.md` |
| 当年（08-01）审计怎么评价这个项目 | `docs/archive/2026-09/baseline-2026-08-01/` |
| 已知弱点清单 | `docs/archive/2026-09/deep-weakness-audit-2026-08-22/` |
| LAN 服务安全模型 | `docs/lan-security.md` |
| 性能基线（实测） | `docs/perf-baseline-2026-08-29.md` |
| 某次会话/某轮工作的证据 | `docs/reports/`、`docs/archive/2026-09/compose-reports/`、`docs/archive/INDEX.md` |
| 历史/被取代文档原件 | `docs/archive/INDEX.md` |

## 并发维护提示（勿误改）

以下文件由另一个进行中的会话维护（含未提交改动），本指南不覆盖、不修改它们：

- `docs/README.md`（功能分类地图）、`docs/architecture.md`（当前架构）、`docs/overview-2026-08-27.md`（结构快照）
- `docs/plans/architecture-reliability-roadmap-2026-08-31.md`（可靠性路线图）
- `docs/reports/cleanup-and-git-repair-2026-09-01.md`、`docs/reports/expert-panel-deep-analysis-2026-08-31.md`

## 维护门禁

提交前两个脚本须绿（退出码 0）：

- `python scripts/check_documents.py` —— LIVING 新鲜度、archive 登记、FROZEN 标记、导航目标存在性。
- `python scripts/check_boundaries.py` —— 前后端分离静态边界（application 不吐传输 URL、表现层不构造 Repository/connection_for、dialogs 不内嵌 localhost 业务调用）。

> 口径：活跃区统计须排除 `docs/archive/` 与 `docs/full-review/archive/`（二者含大量登记/任务自带证据，漏排会虚报活跃数）。`git ls-tree` 对中文路径加引号，须用 `-z` 免引号输出。
