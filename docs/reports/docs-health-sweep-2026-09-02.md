# docs 文档记录完整梳理报告 · 2026-09-02

> 状态:**已完结** · 本报告是 2026-09-02 结构精简轮（b4ff17b~4b9a4af）之后的全量健康度梳理：状态头覆盖、INDEX 登记完整性、导航计数一致性、链接健康度逐项核验 · 状态登记:2026-09-02(文档梳理轮)

## 一、梳理范围与方法

- 范围：`docs/` 全部 492 份 md（活跃区 ~70 + 归档/FROZEN 422）。
- 方法：脚本全量扫描 + 逐文件核对（非抽样），核验维度五项：状态头覆盖、archive/INDEX 登记、导航文档计数、相对链接、空/孤儿目录。
- 并行会话避让：工作树 6 份 WIP（architecture.md、overview-2026-08-27、roadmap、cleanup-and-git-repair、expert-panel、task-package-2026-08-30）内容不动。

## 二、健康度结论

| 维度 | 结论 | 证据 |
|---|---|---|
| 相对链接 | **0 断链** | 活跃区 121 条相对链接全量解析通过（排除 FROZEN 前缀、代码块、`file:line` 证据锚点） |
| INDEX 登记 | **完整** | archive 255 份中 253 份逐行登记；豁免 2 份：INDEX.md 自身、recovered 快照自带的 MANIFEST.md |
| 导航计数 | **一致** | README: plans 12 ✓ compose distilled 9+1 ✓ reports 28 ✓ adr 5 ✓ 根级 9 ✓ diagrams(2 非 md) ✓ |
| 状态头覆盖 | **补齐后 100%**（2 份 WIP 除外） | 本轮补登 26 份，见第三节 |
| 门禁 | **exit 0 ×2** | check_documents + check_boundaries |

## 三、本轮处置（26 份状态头补登）

补登为**追加式元数据**（标题后插入状态行），正文零改写。

| 文件 | 状态判定 |
|---|---|
| `adr/0001-architecture-governance.md`、`adr/0002-library-session.md` | LIVING（决策仍有效，与其他 3 份 ADR 格式对齐） |
| `reports/module-lan-core.md`、`module-lan-routes.md`（08-10 P0 轮） | 历史底稿（行号已失效，发现项由后续批次关闭）→ 2026-09-02 收敛轮已蒸馏为 `module-audit-distilled-2026-09-02.md`，原件归档 `archive/2026-09/module-audits-superseded/` |
| `reports/module-assets-p1.md`、`module-repositories-p1.md`（08-11 P1 轮） | 历史底稿（同上）→ 同上 |
| `reports/desktop-uiux-review-2026-08-29.md`、`webui-review-2026-08-29.md` | 现行（评审基线） |
| `reports/t0-stabilization-summary-2026-08-30.md` | 已完结 → 2026-09-02 收敛轮归档 `archive/2026-09/reports-superseded/` |
| `reports/task-package-research-2026-08-30.md`、`task-package-validity-check-2026-09-01.md` | 已完结（任务包配套纪要/检验快照）→ 同上归档 |
| `reports/serpent-reference-study-2026-08-30.md` | ~~现行(参考)~~ 已于第二轮精简(2026-09-02)归档，取代者:serpent-expert-analysis-distilled |
| `reports/serpent-vs-assetmanager-2026-08-30.md` | ~~现行~~ 已归档，取代者:serpent-expert-analysis-distilled |
| `reports/functional-analysis-and-serpent-comparison-2026-08-31.md`、`pm-capability-analysis-2026-08-31.md`、`project-analysis-2026-08-31.md` | ~~现行(参考)~~ 已归档，取代者:serpent-expert-analysis-distilled |
| `reports/global-synthesis-analysis-2026-08-31.md` | ~~现行~~ 已归档，取代者:serpent-expert-analysis-distilled |
| `compose/distilled/` 9 份（2026-06-17 ~ 2026-08-04） | 历史蒸馏（已完结会话摘要，原件在 archive/2026-08/compose-raw/） |

> 初扫因命令输出截断只识别出 16 份缺口；以修正后的全量复扫为准（26 份，另 2 份 WIP 避让）。

## 四、口径修正

结构精简轮的表述"docs 总量 492→379"**有误**：`git mv` 不减少文件总量，总量始终 492；正确口径为**活跃区 185→70 份**。本报告为权威更正。

> **二次更正（第四节收敛轮后，以逐提交实测为准）**：上式中的 185/70 亦未采用统一口径。以 `git ls-tree -r -z --name-only <commit> -- docs` 逐提交实测，结构精简轮的真实变化是 **活跃区 256 → 143 份**（口径：排除 `docs/archive/` 与 `docs/full-review/archive/`）。差异源于 `full-review/archive/` 的 94 份 dated 证据是否计入，以及 `git ls-tree` 对中文路径加引号（以 `.md"` 结尾）导致按 `.md` 过滤时中文文件名被整批漏计。**凡引用活跃区数字，一律以本节实测口径为准。**

## 五、遗留观察项（不动手）

1. **并行 WIP 状态头**：`cleanup-and-git-repair-2026-09-01.md`、`expert-panel-deep-analysis-2026-08-31.md` 2 份待并行会话提交后补登。
2. **08-30~31 分析系列 7 份（~200K）蒸馏合并**：以 global-synthesis 为骨架可再省 ~150K 活跃区体积，属内容加工，留作第二轮精简候选。
3. **`docs/diagrams/`**：仅 .cw/.html 图示源，无 md，README §7 已登记，无需动作。

## 六、核验记录

- 扫描脚本口径与结构精简轮一致（剥离 fenced code block；`*.md:数字` 形态的代码证据锚点不计入导航断链）。
- archive 登记核对曾出现"缺 14 份"的中间结论，经逐段核查为匹配口径差异（recovered 段与 scratch 段登记行不带 `| docs/` 前缀），实际登记完整——详见 `archive/INDEX.md` 各段。

## 七、后续收敛轮登记（2026-09-02 第三/四轮）

本报告第五节遗留项 2（分析系列蒸馏）已在第二轮执行完毕；本节登记其后的两轮收敛及终态。

| 轮次 | 处置 | 活跃区变化 | 提交 |
|---|---|---|---|
| 第三轮 A | `reports/module-*` 11 份行号级审计底稿 → 蒸馏为 `module-audit-distilled-2026-09-02.md` | −10 | `bb4d321` |
| 第三轮 B | t0-stabilization-summary / task-package-research / task-package-validity-check 归档 | −3 | `f751a8d` |
| 第三轮 C | `bg-simplify-image-only` 范围决策并入父文档 `bg-gpu-shader-architecture` | −1 | `73c1c03` |
| 第四轮 D | 08-01 冻结基线簇 48 份 + deepseek 逐字副本 8 份迁入 `archive/2026-09/` | −56 | `afc4cf4` |
| 第四轮 E | 08-22 冻结弱审计簇 11 份迁入 `archive/2026-09/` | −11 | `691b37c` |

**关键判定（第四轮）**：门禁 `check_documents.py` 只校验「FROZEN 标记存在 / archive 逐份登记 / LIVING 时效 / 导航目标存在」，**不做全库断链检查**。因此 FROZEN 簇迁入 `archive/` 是可行的——只需把 `FROZEN_MARKERS` 路径同步到新位置，冻结保证（内容不可改写）完全不丢，`archive/` 与 `FROZEN` 两种状态正交共存。同步改动的还有 `check_boundaries.py` docstring 里的验收标准来源路径。

- **内容零改写**：两簇 67 份全部为位置变更。唯一的内容改动是 `deepseek-archive-2026-08-25/` 内部 21 处指向基线的相对链接（`../../../baseline-*` → `../../baseline-*`），属迁移必需的几何修正，正文未改。
- **复扫结果**：活跃区 103 条链接中 31 条为 `file:line` 代码证据锚点（非链接），**真实断链 0**；迁入两簇内部 113 条链接中剩 7 条断链，全部位于 FROZEN 基线簇内、指向上一轮已归档的 `compose/reports/`，系迁移前既有缺陷，FROZEN 纪律下不予改写。
- **终态**：docs 总量 495 份不变；活跃区 md **58 份**（根 9 / adr 5 / compose 10 / full-review 12 / plans 11 / reports 11）；另计 `docs/full-review/archive/` 94 份 dated 审计证据（进行中任务簇自带，勿动，不计入活跃区）；`docs/archive/` 343 份，其中 2026-09 段登记 **201 份**；双门禁每轮 exit 0；42 份并行会话 WIP 全程未触碰。
- **活跃区轨迹（逐提交实测）**：256（收敛前）→ 143（精简轮）→ 139（蒸馏轮）→ 125（收敛 A/B/C）→ 69（Round D）→ **58**（Round E）。口径与第四节二次更正一致。

**遗留**：根 `README.md`（第 101 行目录树、第 252 行表格）与 `docs/overview-2026-08-27.md`（第 137/398/415 行）仍写有旧的 `docs/baseline-2026-08-01/`、`docs/deep-weakness-audit-2026-08-22/` 路径；二者均为并行会话 WIP，待其提交后同步。
