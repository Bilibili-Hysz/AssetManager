# Serpent 对照与专家分析蒸馏（2026-08-30~31 系列合并）

> 状态:**现行** · 本文档为 2026-09-02 精简轮蒸馏产物，取代下列 6 份原件（已归档至 [`archive/2026-09/analysis-superseded/`](../archive/2026-09/analysis-superseded/)，git 历史与原件均可查）：`serpent-reference-study-2026-08-30`、`serpent-vs-assetmanager-2026-08-30`、`functional-analysis-and-serpent-comparison-2026-08-31`、`project-analysis-2026-08-31`、`pm-capability-analysis-2026-08-31`、`global-synthesis-analysis-2026-08-31` · `expert-panel-deep-analysis-2026-08-31.md` 因并行会话占用暂留活跃区，待提交后补充蒸馏 · 状态登记:2026-09-02(第二轮精简)

## 一、Serpent 事实层（源自 reference-study + serpent-vs）

**技术栈与规模**：Electron 43 + React 19 + Vite + TS，better-sqlite3 同步驱动；667 文件 / 21.5 万行；7 周 1,268 commits（v0.1.5，单人 98%）；仅 darwin-arm64/win32-x64。核心集中在 `src/worker/library-service.ts`（43,822 行，占 40%——反面教材）。本地副本 `D:\~Vibe-Coding\Projects\_REF_Serpent`。

**关键设计**：55 张表；人工/AI 标签物理分表（`human_asset_tags`/`ai_asset_tags`）；collections + smart_collections（保存的搜索）；`.serpentignore`（gitignore 语法）；revisions 版本链 + 九类派生物（资产履历语义，非缓存语义）；FTS5 全文 + 高级语法检索；WebDAV 云同步；直接打开 Eagle/Billfish 库（零成本迁移入口）。

**AI 能力（修正后认知，以此为准）**：仅外部 API（用户自带 Key）+ 队列调度/并发限流；任务仅描述/打标/评分三类；**无以图搜图、无 AI 对话、无向量索引**——证据 `_REF_Serpent/docs/user-guide/ai.md:70`。reference-study 最初暗示具备以图搜图/AI 对话，已被 serpent-vs 实地清点修正。

**自动化**：84 命令注册表 + 全写命令强制 idempotencyKey + 审批三档（41/9/4）+ 只读沙箱 + undo/redo + `library_job_leases` 租约（fencing token + 心跳）；内嵌 MCP 服务器（凭据可撤销，工具带 riskTier）。

**并发架构**：四类进程，SQLite 整体放 Worker；变更序号由 20+ 张表触发器同事务推进（never best-effort）；7 条性能 lane + 截止时间信封。

**弱点**：无 CI、43K 行单文件、主分支 developer 文档缺失。

## 二、差异判断与借鉴决策

**AM 护城河（Serpent 全无）**：LAN 分享门户（六种 principal、密码/限时/限次分享链接、WS 推送、隧道）、商城全链路、13 job CI + 12+ AST 门禁 + 三语 i18n + axe 门禁。26 页面 16 个商城（62%）vs Serpent 全投核心能力——功能重心偏离的最强外部佐证。

**值得抄（按性价比）**：标签物理分表（✅已做 v36）、流式 ZIP、自动化三件套（日志已做 activity_log；幂等/审批=T8 缓办）、MCP 暴露（高性价比替代自建 AI）、任务租约、gitignore 尊重、竞品库直接打开（Eagle/Billfish 导入，候选评估）。

**不抄（判断被强化）**：43K 行单文件、Electron 重写、内置 AI 分析模块、商城再加码、多进程写租约全家桶、细粒度 MCP 权限、AI 多厂商长尾。

## 三、功能与 PM 决策（源自 functional-analysis + pm-capability）

**AM 缺失/弱点（对照后仍成立）**：智能合集、视频/3D/文档缩略图、WebDAV 同步、云 AI 适配器、Eagle/Billfish 导入、持久修订、浏览器扩展。文档失真：README 宣称商城 54 路由零实现（`README.md:206` vs `lan/routes/` 18 模块）。

**插件沙箱结论冲突的裁定**：功能报告判无沙箱为 CRITICAL/P0（`core/plugins/loader.py:89,93`——风险描述有效）；PM 报告 T4 定论不学 QuickJS 沙箱（Python 无成熟嵌入方案，manifest 权限 + 只读白名单已够——资源分配以此为准）。

**T1 快赢（1-2 天/项）**：中文子串检索（trigram+instr 双轨）、评分/收藏入检索排序、智能合集浏览态快照、派生物生命周期列、大库覆盖索引（B 实测 60ms→<0.1ms）、打包产物深度校验、ADR 修订链纪律。

**T2 战略**：T8 批量操作三件套 → 命令注册表 → MCP 服务器（FastMCP 挂 aiohttp）+ challenge 双确认；启动突发门；AI 打标栈（两条纪律必移植：白名单收敛已有标签、竞品导入永不自动 AI）；lane 化（前置 T10 读连接池）。

**反 lesson 三条**：机制堆叠须合并简化；勿升级迁移 checksum 模式（B v40 互判损坏教训）；单文件巨石是慢性毒（新域坚持子包化）。

## 四、专家评审与综合研判（源自 project-analysis + global-synthesis）

**R 风险登记（核心）**：
- 🔴 R1 插件同进程无沙箱 = 公网 RCE（`loader.py:89,93`）
- 🟠 R2 密码令牌 HMAC 密钥复用 `password_hash`，DB 可读即伪造（`domain/auth.py:155,177`）
- 🟠 R3 全局写串行 + `id(conn)` 锁归属脆弱（`database.py:523,543`）
- 🟡 R6 暴力锁定弱于声称、R7 隧道下白名单被绕过（`security.py:269`）
- MED：R4 pyright 排除两子系统、R8 配额双账本、R9 event_bus 跨库泄漏、R10 CI 不盖特性分支、R11 Cython 未接构建、R12 DI 名义化、R13 window.py God-object、R14 ≥7 个 1600+ 行巨型文件
- HIGH：商城 54 路由纸面化（文档信用）、R15 upload 废弃仍展示（`dto.py:103`）

**五大根因（global-synthesis，40+ 条目去重为 U-1~U-30）**：
- T1 文档-代码系统性背离（验证边界文化只管测试不管文档；U-8 是唯一越查越深的风险链）
- T2 安全姿态与暴露野心错位（威胁模型仍是"局域网可信"，公网假设全失效）
- T3 "最后 10%"欠账（缓存无淘汰、skip 零限流、整读无上限）
- T4 双端双实现成本（契约生成只覆盖 DTO 层）
- T5 名义分层 vs 实态拓扑（实为服务定位器 + 74 处 AppSettings.instance；骨架本身是好的）

**对 P0 方案的批判（仍需落实）**：P0-1 信任列表≠隔离、阶段 B 不可拖延；P0-4 两个被低估副作用——改密不再踢旧会话（建议 `pwd_version` 计数器）、重启风暴（建议 HKDF 从 token_secret 派生）；遗漏 U-6 缓存、S6 ZIP worker 配额应并入。

**三扇门决策框架**：门1 公网暴露（U-1..U-5）、门2 规模承载（U-6/7/24 + 10 万库基准门禁）、门3 工程深化；门1/门2 相互独立不可互证。插件沙箱是借鉴 Serpent 功能的工程前提。

## 五、承接关系

| 蒸馏内容 | 承接计划 |
|---|---|
| U-1~U-5 第一档（P0-1~P0-5） | `plans/p0-security-remediation-2026-08-31.md`（提案，未实施） |
| R3/R4/R8-R14 第二三档 + P1/P2 | `plans/architecture-reliability-roadmap-2026-08-31.md`（H1 实施中） |
| T1/T2 批次序列 | PM 报告 P1 快赢周 → P2 地基周 → P3 生态月 → P4 体验月 |

## 六、原件索引与取舍说明

| 原件（归档路径前缀 `../archive/2026-09/analysis-superseded/`） | 本摘要承载其 |
|---|---|
| `serpent-reference-study-2026-08-30.md` | §一事实 + §二借鉴；被修正条目以修正后为准 |
| `serpent-vs-assetmanager-2026-08-30.md` | §一修正认知 + §二判断；逐域功能矩阵细节弃 |
| `functional-analysis-and-serpent-comparison-2026-08-31.md` | §三缺失清单；Ollama 打标矛盾以其源码走查为准（`application/ai_tagging/service.py:39-88` 有实现） |
| `pm-capability-analysis-2026-08-31.md` | §三 T1/T2/T4/批次/反 lesson |
| `project-analysis-2026-08-31.md` | §四 R 登记（完整评级表见原件） |
| `global-synthesis-analysis-2026-08-31.md` | §四根因/批判/三扇门（U 表完整对应关系见原件） |

> 沙箱风险详情：project-analysis §5.2/§7 P0-1；关键锚点补充：`search_service.py:68`、`undo_service.py:84-85`、`security.py:62,120,127,151`、Serpent `library-service.ts:1399`、`app-update-service.ts`（824 行，未来自动更新器可当规格书）。
