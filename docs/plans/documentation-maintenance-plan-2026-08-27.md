# 文档处理方案:信息提炼与精简(2026-08-27,修订版)

> **范围声明(用户指定)**:`docs/full-review/**` 是进行中的任务证据,**本次不处理**(不修改、不标注、不动索引)。其余全部文档纳入本方案。
> 数据源:`docs/overview-2026-08-27.md` 一手实测 + 本次文档盘点。

## 0. 处理哲学:每个聚类只留"信息入口"

全仓库文档被分为三类角色,任何一份文档最终必须属于其一:

| 角色 | 含义 | 处理原则 |
|---|---|---|
| **LIVING 活性** | 读者日常查阅的当前事实 | 更新到 2026-08-27 实测;头部带 `updated:`;≤8 份,每份都有独立职责 |
| **FROZEN 冻结证据** | dated 快照、证据(compose/reports、docs/reports、DeepSeek Docs、deep-weakness-audit、adr) | **内容零改写**;只允许:加状态头、加导航条目、被"信息入口"引用 |
| **ARCHIVED 归档** | 已执行完毕/被取代,无日常查阅价值但需追溯 | 移入 `docs/archive/<yyyy>/`,原始路径→新路径登记入 `docs/archive/INDEX.md` |

**提炼的核心机制:不为每份旧文档改写内容,而是用"信息入口"承接其剩余信息量,再归档原件。** 四个信息入口:

1. `README.md` — 门面(快速开始/门禁/边界)
2. `docs/overview-2026-08-27.md` — 地图(结构/机制/数据流/弱点,已建成)
3. `docs/compose/README.md` — 证据导航(197 份 compose 文档的可检索索引)
4. `docs/archive/INDEX.md` — 归档登记(所有移出文档的溯源)

---

## 1. 聚类处理卡(A 组:活性文档,更新而非提炼)

| # | 文档 | 现状实测 | 信息量评估 | 处置 | 提炼产物 |
|---|---|---|---|---|---|
| A1 | `docs/overview-2026-08-27.md` | 391 行,本次建成 | 最高的信息密度;§18/§19 是核心价值 | **LIVING 主入口**;头部加 `updated:` 规则;末尾加"文档导航"节(指向 README/ADR/compose/archive 各入口) | 成为全库唯一"结构地图" |
| A2 | `README.md` | 670 行;stats 标记由 check_doc_stats 守护 | 大量细节已过时(树/行数)但门面作用不可替代 | 按 T5.1 精简至 ~300-350 行:定位/快速开始/门禁/验证边界/设计取舍/导航;结构树与细节下沉 overview | 门面 README |
| A3 | `docs/lan-security.md` | 102 行;PBKDF2(:76-78)仍写 100k/salt_hex:key_hex | 安全文档,错误描述有实际危害 | 更新:PBKDF2 600k 自描述格式、限流三档、撤销表、隧道 cookie、`/ws` 凭据;头部 updated | 当前版安全说明(约 100 行,零废话) |
| A4 | `docs/architecture.md` + `architecture-diagram.md` | 224/170 行,08-21 刷新过 | 层与边界规则仍准;服务表缺 08-21 后新增 | 服务表补 reconciliation/import/export/commerce/gallery 包;图与文同步;两文件头互链,避免双份漂移 | 架构一页纸(含图) |
| A5 | `docs/migrations.md` | 235 行,08-24 已到 v34 | 基本准确 | 逐版本与代码 MIGRATIONS 对账 + 补机制说明(冻结校验/契约回溯);与 overview §15 互链 | 迁移权威 |
| A6 | `docs/development.md` / `docs/testing.md` | 82/73 行 | 数字需复核(283 测试、CI 9 job 等) | 复核修正;CI job 表补 python-browser-e2e;命令与 pytest.ini 对齐 | 开发/测试一页纸 |
| A7 | `docs/adr/`(3 份) | 06-13/06-15 | 架构决策全集,价值高 | **保留不动**,头部加 `status: ratified + updated`;校验 0003 引用的 08-02/03 报告仍存在(compose/reports) | ADR 索引行加入 overview 导航 |

## 2. 聚类处理卡(B 组:冻结证据,只加壳不换芯)

| # | 聚类 | 现状实测 | 处置 | 提炼产物 |
|---|---|---|---|---|
| B1 | `docs/compose/`(197 = specs 25/plans 55/reports 98/handoffs 19) | 多智能体工作证据账本;"Historical-plan rule" 自制纪律已存在 | ① 新建 `docs/compose/README.md`:按子目录列表(名称/日期/主题/状态[executed-archived / evidence / reference]),把 197 份变成可检索索引;② pre-07-21 的 specs/plans 批量加统一 `> ARCHIVED: 已执行完毕,仅追溯用` 头;③ reports 与 handoffs **零改动**(纯证据) | compose/README 导航(≈60 行) |
| B2 | `docs/reports/`(31,含 deepseek-archive-2026-08-25) | module-* 系列是 08-11 分模块审查,full-review 之前的最后行号级证据 | **零改动**;INDEX 摘要并入 compose/README(或 overview 导航一行) | 一行导航 |
| B3 | `DeepSeek Docs/`(48) | 08-01 冻结基线;deepseek-archive INDEX 已登记"勿改写链接";决策-1 悬置 | **默认冻结不动**;仅在其 README 顶部加 2 行状态头(FROZEN 基线 + 指针:当前事实见 overview);是否物理迁移到 docs/deepseek/ 留决策 D-2 | 状态头 + 指针 |
| B4 | `docs/deep-weakness-audit-2026-08-22/`(11) | 完成态只读审计;09 已是提炼层(Top-30);C-1~C-5 待入正文 | 内容零改动;目录 README 顶部加"状态注记批次待 full-review 重开"一行;130 条发现的状态标注任务**移入待办池**(依赖 full-review 证据) | 待办登记,不执行 |
| B5 | `Plugins/Docs/`(3) | 06-09 v1 手册,落后于 v2 | 三份文件顶部各加 3 行状态头(v1 历史 / v2 现状指针:`AssetsManager/plugin_api/`);正文不动 | 指针头 |

## 3. 聚类处理卡(C 组:归档与去重)

| # | 对象 | 现状 | 处置 | 提炼产物 |
|---|---|---|---|---|
| C1 | docs/ 根 14 个散落文件(HANDOVER-2026-08-15、HANDOVER-PROMPT、session-handoff-06-17/06-18/07-15/08-08、task-handoff-06-16、P0-optimization-completion-report、performance-optimization-plan、project-assessment-2026-08-13、refactor-baseline、architecture-optimization-roadmap-06-19、agent-architecture-map-deep、agent-quick-map、workspace) | 全部被后续文档取代 | 每份写 1 行"内容摘要+被谁取代"进 `docs/archive/INDEX.md`,原件移入 `docs/archive/2026-08/root-loose/` | 14 行索引,零信息丢失 |
| C2 | `docs/history/`(5)+ `docs/Suggestions/`(7)+ `docs/plans/` 旧 2 份 | 明确 archived 横幅/方向已定 | 整体移入 archive(每份保留原始路径登记) | 索引 14 行 |
| C3 | 根目录 `_quality_audit_2026_08_17.md` vs `_quality_report.md` | 同一轮审查双份互抄 | 保留信息量较全者(08-17 质量审计报告),另一份移 archive 留指针;`_q1_complete.txt`/`_q1_gates.txt` 移 archive;`crash.log` 确认进 .gitignore | 一份质检报告 |
| C4 | 同名双份(ui-rendering-audit、webui-desktop-dataflow-audit) | compose/reports 与 docs/reports 各一份 | 保留 docs/reports 版,compose 版加"见 docs/reports 同名文件"指针头 | 去重 2 处 |
| C5 | 归档容器本身 | 不存在 | 建 `docs/archive/INDEX.md`(登记表:原始路径/新路径/归档原因/替代文档)+ 目录结构 `docs/archive/2026-08/{root-loose,history,suggestions,plans,scratch}` | 归档溯源总账 |

## 4. 门禁与防漂移(延续修订版核心:门禁护航)

| # | 任务 | 说明 |
|---|---|---|
| G1 | 扩展 `scripts/check_doc_stats.py` | 新增守卫锚点:controllers(4)、domain_events(15)、repositories(18)、app_services 口径注释;README 结构树相关 prose 锚点 |
| G2 | 新增 `scripts/check_documents.py` | ① LIVING 清单(overview/README/lan-security/architecture/architecture-diagram/migrations/development/testing/adr×3,含 updated 头 ≤30 天,可 --ignore-age);② 归档 INDEX 条目存在性(archive 内每个文件都有登记行);③ overview 导航节内列出的链接全部存在;④ FROZEN 清单(compose/reports、docs/reports、DeepSeek Docs、deep-weakness-audit)头部必须含状态标记;⑤ pre-07-21 compose specs/plans 必须含 ARCHIVED 头 |
| G3 | CI 接入 | check_documents.py 并入 lint job;check_doc_stats 维持现有漂移即失败语义 |
| G4 | README 开发指南 | 加 3 行"文档三态"约定,后续新人按此归类新文档 |

## 5. 执行批次与工作量(顺序 = 风险/收益)

| 批次 | 内容 | 工作量 | 依赖 |
|---|---|---|---|
| P1 | C 组归档与去重(C1-C5)+ 建 archive/INDEX | 0.5 天 | 无 |
| P2 | A 组活性文档更新(A1-A7),以 overview 为数据源 | 0.5-1 天 | P1(避免 README 指向已移走文件) |
| P3 | B 组加壳(B1 compose/README + 归档头、B3/B4/B5 状态头) | 0.5 天 | P2 确定指针文案 |
| P4 | README 精简(A2,670→~300) | 0.5 天 | P2 确定下沉目标 |
| P5 | 门禁(G1-G4) | 0.5-1 天 | P2-P4 完成后锚点才稳定 |
| P6 | 验收:全部门禁绿;总 md 数 371 → 目标 ≤330(净减=归档移动+去重,evidence 零删除);人工抽读 A 组 6 份 | 0.5 天 | P5 |

**合计 3-4 个工作日。产出物固定为 5 件:README(门面)、overview(地图)、compose/README(证据导航)、archive/INDEX(归档总账)、check_documents.py(防漂移)。**

## 6. 明确不做(本次范围外)

- `docs/full-review/**` 全部(含 00-INDEX 增补、banner、overview 指针)——**等任务结束后单独处理**,届时再:① 00-INDEX 登记 overview;② deep-weakness-audit 130 条发现按 evidence 标状态;③ 站内互链收口。
- 证据内容的任何改写(compose/reports、docs/reports、DeepSeek Docs 正文、audit 正文)。
- 代码/CI/流程问题(见 overview §19)——本文档只负责文档面。

## 7. 决策点(待用户拍板)

| # | 决策 | 选项 | 建议 |
|---|---|---|---|
| D-1 | 是否先提交工作树再执行 P1-P6(避免注记无 commit 号) | 先提交 / 边改边提交 | 按现有批次提交习惯,至少 P2 前提交一次 |
| D-2 | DeepSeek Docs/ 是否物理迁移到 docs/deepseek/ | 冻结原地(仅加状态头) / 按 deepseek-archive 登记执行方案 B 迁移 | 冻结原地;迁移并入 future 重构 |
| D-3 | 归档用 `docs/archive/`(推荐)还是复用 `docs/history/` | archive 新建 / history 扩展 | 新建(history 本身也进 archive) |
| D-4 | README 精简幅度 | 保守(只修数字) / 激进至 ~300 行 | 激进,细节已由 overview 承接 |

---
*修订日期:2026-08-27 · 替代上一版计划(其 full-review 相关章节全部挂起;deep-weakness 状态注记移入待办池)。*